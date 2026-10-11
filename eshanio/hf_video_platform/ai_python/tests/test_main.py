import asyncio
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from src.main import (
    _pack_url,
    _parse_pack_header,
    _parse_byte_range,
    get_video_catalog,
    serialize_video,
    stream_converted_video,
    stream_video,
)


def make_request(range_header=None):
    headers = []
    if range_header:
        headers.append((b"range", range_header.encode("ascii")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/videos/movie-1/stream",
            "raw_path": b"/api/videos/movie-1/stream",
            "query_string": b"",
            "headers": headers,
            "server": ("example.hf.space", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


class FakeUpstream:
    status = 206

    def __init__(self, content):
        self.content = io.BytesIO(content)

    def read(self, size):
        return self.content.read(size)

    def close(self):
        self.content.close()


class VideoApiHelpersTests(unittest.TestCase):
    def test_parse_pack_header_reads_trailing_little_endian_size(self):
        videos = [{"id": "movie-1", "name": "movie.mp4"}]
        header = json.dumps({"videos": videos}).encode("utf-8")
        tail = header + struct.pack("<Q", len(header))

        self.assertEqual(_parse_pack_header(tail), videos)
        self.assertIsNone(_parse_pack_header(tail[:-3]))

    def test_serialized_video_has_native_client_urls(self):
        item = serialize_video(
            {
                "id": "movie-1",
                "name": "movie.mp4",
                "title": "Movie",
                "cover_offset": 100,
                "cover_size": 20,
                "offset": 500,
                "size": 1000,
                "pack": "movies/library.pack",
            },
            "https://example.hf.space",
        )

        self.assertEqual(item["title"], "Movie")
        self.assertEqual(
            item["thumbnail_url"],
            "https://example.hf.space/api/videos/movie-1/thumbnail",
        )
        self.assertEqual(
            item["stream_url"],
            "https://example.hf.space/api/videos/movie-1/stream",
        )

    def test_external_thumbnail_url_is_preserved(self):
        item = serialize_video(
            {"id": "movie-2", "cover_url": "https://cdn.example/cover.jpg"},
            "https://example.hf.space",
        )

        self.assertEqual(item["thumbnail_url"], "https://cdn.example/cover.jpg")

    def test_pack_url_uses_dataset_node_url(self):
        item = {
            "node_url": "https://huggingface.co/datasets/owner/videos/resolve/main",
            "pack": "library/my pack.pack",
        }

        self.assertEqual(
            _pack_url(item),
            "https://huggingface.co/datasets/owner/videos/resolve/main/library/my%20pack.pack",
        )

    def test_pack_url_rejects_non_hugging_face_override(self):
        self.assertEqual(
            _pack_url(
                {
                    "pack_url": "http://127.0.0.1/private",
                    "node_url": "http://127.0.0.1/",
                    "pack": "movie.pack",
                }
            ),
            "https://huggingface.co/datasets/eshansayhan/movie/resolve/main/movie.pack",
        )

    def test_pack_url_rejects_traversal_path(self):
        self.assertEqual(_pack_url({"pack": "../private.pack"}), "")
        self.assertEqual(_pack_url({"pack": r"..\private.pack"}), "")

    def test_byte_range_supports_normal_open_ended_and_suffix_ranges(self):
        self.assertEqual(_parse_byte_range("bytes=10-19", 100), (10, 19))
        self.assertEqual(_parse_byte_range("bytes=90-", 100), (90, 99))
        self.assertEqual(_parse_byte_range("bytes=-10", 100), (90, 99))
        self.assertEqual(_parse_byte_range(None, 100), (0, 99))

    def test_byte_range_rejects_invalid_ranges(self):
        self.assertIsNone(_parse_byte_range("bytes=100-", 100))
        self.assertIsNone(_parse_byte_range("bytes=20-10", 100))
        self.assertIsNone(_parse_byte_range("bytes=0-1,4-5", 100))
        self.assertIsNone(_parse_byte_range("bytes=" + ("9" * 200) + "-", 100))

    def test_catalog_falls_back_to_the_project_master_index(self):
        with (
            patch("src.main._video_cache", None),
            patch("src.main.urlopen", side_effect=URLError("offline")),
        ):
            catalog = get_video_catalog(force_refresh=True)

        self.assertTrue(catalog)
        self.assertTrue(catalog[0].get("title"))
        self.assertTrue(catalog[0].get("pack"))

    def test_stream_route_translates_client_range_to_pack_offset(self):
        video = {
            "id": "movie-1",
            "node_url": "https://huggingface.co/datasets/owner/videos/resolve/main",
            "pack": "library.pack",
            "offset": 500,
            "size": 100,
        }
        upstream = FakeUpstream(b"abc")
        with (
            patch("src.main.get_video_catalog", return_value=[video]),
            patch("src.main.urlopen", return_value=upstream) as open_url,
        ):
            response = stream_video("movie-1", make_request("bytes=2-4"))
            request = open_url.call_args.args[0]
            response_body = asyncio.run(self._consume(response))

        self.assertEqual(request.get_header("Range"), "bytes=502-504")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 2-4/100")
        self.assertEqual(response_body, b"abc")

    def test_converted_stream_supports_byte_ranges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "converted.mp4"
            video_path.write_bytes(b"0123456789")
            with patch("src.main.get_converted_file", return_value=video_path):
                response = stream_converted_video(
                    "library.safetensors",
                    "video_1",
                    make_request("bytes=3-6"),
                )
                response_body = asyncio.run(self._consume(response))

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 3-6/10")
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(response_body, b"3456")

    def test_converted_stream_reports_not_ready(self):
        with (
            patch("src.main.get_converted_file", return_value=None),
            self.assertRaises(HTTPException) as error,
        ):
            stream_converted_video(
                "library.safetensors",
                "video_1",
                make_request(),
            )

        self.assertEqual(error.exception.status_code, 503)

    @staticmethod
    async def _consume(response):
        return b"".join([chunk async for chunk in response.body_iterator])


if __name__ == "__main__":
    unittest.main()
