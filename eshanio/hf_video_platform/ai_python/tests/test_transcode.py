import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import transcode


def safetensors_header(metadata, tensors):
    header = {"__metadata__": metadata, **tensors}
    encoded = json.dumps(header).encode("utf-8")
    return len(encoded).to_bytes(8, "little") + encoded


class FakeResponse:
    status = 206

    def __init__(self, content):
        self.content = content

    def read(self, size=-1):
        return self.content if size < 0 else self.content[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class SafetensorsTranscodeTests(unittest.TestCase):
    def test_parse_header_and_video_manifest(self):
        header_bytes = safetensors_header(
            {
                "packmanager_manifest": json.dumps(
                    {
                        "assets": [
                            {
                                "role": "video",
                                "tensor": "video_1",
                                "filename": "episode.mp4",
                            },
                            {"role": "cover", "tensor": "cover_1"},
                        ]
                    }
                )
            },
            {"video_1": {"data_offsets": [0, 100]}},
        )
        header = transcode._parse_safetensors_header(header_bytes)

        self.assertEqual(
            transcode._video_entries(header),
            [
                {
                    "role": "video",
                    "tensor": "video_1",
                    "filename": "episode.mp4",
                }
            ],
        )

    def test_discovery_calculates_safetensors_payload_range(self):
        header_bytes = safetensors_header(
            {"packmanager_manifest": json.dumps({"assets": [
                {"role": "video", "tensor": "video_1", "filename": "episode.mp4"}
            ]})},
            {"video_1": {"data_offsets": [0, 4]}},
        )
        file_size = len(header_bytes) + 4
        tree = json.dumps(
            [
                {
                    "path": "library/episodes.safetensors",
                    "size": file_size,
                    "oid": "source-oid",
                }
            ]
        ).encode("utf-8")

        def fake_urlopen(request, timeout):
            url = request.full_url
            if "/api/datasets/" in url:
                return FakeResponse(tree)
            if request.get_header("Range") == "bytes=0-7":
                return FakeResponse(header_bytes[:8])
            return FakeResponse(header_bytes[8:])

        with patch("src.transcode.urlopen", side_effect=fake_urlopen):
            assets = transcode.discover_video_assets()

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["offset"], len(header_bytes))
        self.assertEqual(assets[0]["size"], 4)
        self.assertEqual(assets[0]["source_oid"], "source-oid")

    def test_invalid_header_size_is_rejected(self):
        with self.assertRaises(ValueError):
            transcode._parse_safetensors_header((100).to_bytes(8, "little") + b"{}")

    def test_adaptive_crf_uses_source_resolution_and_bitrate(self):
        self.assertEqual(
            transcode._select_crf(
                [
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "bit_rate": "9000000",
                    }
                ]
            ),
            21,
        )
        self.assertEqual(
            transcode._select_crf(
                [{"codec_type": "video", "width": 640, "height": 360}]
            ),
            25,
        )

    def test_transcode_adds_silent_aac_when_source_has_no_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.bin"
            destination = Path(temp_dir) / "output.mp4"
            source.touch()
            probe = [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "bit_rate": "5000000",
                }
            ]
            with (
                patch("src.transcode._probe_streams", side_effect=[probe, [
                    {"codec_type": "video", "codec_name": "h264"},
                    {"codec_type": "audio", "codec_name": "aac"},
                ]]),
                patch("src.transcode.subprocess.run") as run,
            ):
                transcode._transcode(source, destination)

        args = run.call_args.args[0]
        self.assertIn("anullsrc=channel_layout=stereo:sample_rate=48000", args)
        self.assertIn("libx264", args)
        self.assertIn("aac", args)
        self.assertIn("-shortest", args)

    def test_converted_file_lookup_uses_source_and_tensor_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            output = output_dir / "converted.mp4"
            output.write_bytes(b"mp4")
            key = transcode._asset_key("library.safetensors", "video_1")
            index_path = output_dir / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "assets": {
                            key: {
                                "path": "converted.mp4",
                                "tensor": "video_1",
                                "source_file": "library.safetensors",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(transcode, "OUTPUT_DIR", output_dir):
                self.assertEqual(
                    transcode.get_converted_file("library.safetensors", "video_1"),
                    output,
                )
                self.assertIsNone(
                    transcode.get_converted_file("other.safetensors", "video_1")
                )

    def test_batch_conversion_persists_index_and_skips_unchanged_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            asset_key = transcode._asset_key("library.safetensors", "video_1")
            asset = {
                "asset_key": asset_key,
                "asset_id": transcode._asset_digest(asset_key),
                "source_file": "library.safetensors",
                "source_oid": "source-oid",
                "source_file_size": 2048,
                "tensor": "video_1",
                "filename": "episode.mp4",
                "source_url": "https://huggingface.co/source",
                "offset": 128,
                "size": 1024,
            }
            index = {"assets": {}}

            def fake_transcode(_source, destination):
                destination.write_bytes(b"converted mp4")

            with (
                patch.object(transcode, "OUTPUT_DIR", output_dir),
                patch("src.transcode._download_asset"),
                patch("src.transcode._transcode", side_effect=fake_transcode) as encode,
            ):
                self.assertTrue(transcode._convert_one(asset, index))
                self.assertFalse(transcode._convert_one(asset, index))

            self.assertEqual(encode.call_count, 1)
            self.assertEqual(len(index["assets"]), 1)
            self.assertEqual(
                json.loads((output_dir / "index.json").read_text(encoding="utf-8"))["assets"],
                index["assets"],
            )


if __name__ == "__main__":
    unittest.main()
