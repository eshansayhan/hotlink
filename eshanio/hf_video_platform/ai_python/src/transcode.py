import hashlib
import json
import logging
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger("hfvideo_transcode")

DATASET_REPO = os.getenv("SAFETENSORS_DATASET_REPO", os.getenv("HF_DATASET_REPO", "eshansayhan/movie"))
DATASET_REVISION = os.getenv("SAFETENSORS_DATASET_REVISION", os.getenv("HF_DATASET_REVISION", "main"))
OUTPUT_DIR = Path(os.getenv("TRANSCODE_OUTPUT_DIR", "/data/hfvideo_converted"))
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CHUNK_SIZE = 1024 * 1024
MAX_HEADER_SIZE = 64 * 1024 * 1024


def _hf_headers() -> dict[str, str]:
    headers = {"User-Agent": "HFVideoPlatform-Transcoder/1.0"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    return headers


def _asset_key(source_file: str, tensor: str) -> str:
    return json.dumps([source_file, tensor], ensure_ascii=True, separators=(",", ":"))


def _asset_digest(asset_key: str) -> str:
    return hashlib.sha256(asset_key.encode("utf-8")).hexdigest()


def _dataset_base_url() -> str:
    return (
        f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/"
        f"{quote(DATASET_REVISION, safe='')}/"
    )


def _fetch_range(url: str, start: int, end: int) -> bytes:
    headers = _hf_headers()
    headers["Range"] = f"bytes={start}-{end}"
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        if response.status != 206:
            raise RuntimeError("Hugging Face did not honor the requested byte range")
        data = response.read(end - start + 1)
    if len(data) != end - start + 1:
        raise RuntimeError("Hugging Face returned an incomplete byte range")
    return data


def _parse_safetensors_header(header_bytes: bytes) -> dict[str, Any]:
    if len(header_bytes) < 8:
        raise ValueError("Safetensors header is missing its length prefix")
    header_size = int.from_bytes(header_bytes[:8], "little")
    if not 0 < header_size <= MAX_HEADER_SIZE:
        raise ValueError("Safetensors header size is invalid or exceeds the configured limit")
    if len(header_bytes) != header_size + 8:
        raise ValueError("Safetensors header response has an unexpected size")
    header = json.loads(header_bytes[8:].decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("Safetensors header must be a JSON object")
    return header


def _video_entries(header: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = header.get("__metadata__", {})
    manifest = metadata.get("packmanager_manifest") if isinstance(metadata, dict) else None
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    assets = manifest.get("assets", []) if isinstance(manifest, dict) else []
    entries = [
        asset for asset in assets
        if isinstance(asset, dict) and asset.get("role") == "video"
    ]
    if entries:
        return entries
    return [
        {"tensor": name, "role": "video", "filename": f"{name}.mp4"}
        for name in header
        if name.startswith("video_") and name != "__metadata__"
    ]


def discover_video_assets() -> list[dict[str, Any]]:
    tree_url = (
        f"https://huggingface.co/api/datasets/{DATASET_REPO}/tree/"
        f"{quote(DATASET_REVISION, safe='')}?recursive=true&limit=1000"
    )
    with urlopen(Request(tree_url, headers=_hf_headers()), timeout=60) as response:
        tree = json.load(response)
    if not isinstance(tree, list):
        raise ValueError("Hugging Face dataset tree response must be a list")

    base_url = _dataset_base_url()
    discovered: list[dict[str, Any]] = []
    for item in tree:
        if not isinstance(item, dict):
            continue
        source_file = item.get("path")
        file_size = item.get("size")
        if (
            not isinstance(source_file, str)
            or not source_file.lower().endswith(".safetensors")
            or not isinstance(file_size, int)
            or file_size < 8
        ):
            continue

        file_url = base_url + quote(source_file, safe="/")
        prefix = _fetch_range(file_url, 0, 7)
        header_size = int.from_bytes(prefix, "little")
        if not 0 < header_size <= MAX_HEADER_SIZE or header_size + 8 > file_size:
            raise ValueError(f"Invalid Safetensors header size in {source_file}")
        header = _parse_safetensors_header(
            prefix + _fetch_range(file_url, 8, header_size + 7)
        )
        data_start = header_size + 8

        for asset in _video_entries(header):
            tensor = asset.get("tensor")
            tensor_info = header.get(tensor) if isinstance(tensor, str) else None
            offsets = tensor_info.get("data_offsets") if isinstance(tensor_info, dict) else None
            if (
                not isinstance(tensor, str)
                or not tensor
                or not isinstance(offsets, list)
                or len(offsets) != 2
                or not all(isinstance(value, int) for value in offsets)
            ):
                logger.warning("Skipping video with invalid tensor offsets in %s", source_file)
                continue

            start, end = offsets
            if start < 0 or end <= start or data_start + end > file_size:
                logger.warning("Skipping video with out-of-file tensor offsets in %s", source_file)
                continue

            asset_key = _asset_key(source_file, tensor)
            discovered.append(
                {
                    "asset_key": asset_key,
                    "asset_id": _asset_digest(asset_key),
                    "source_file": source_file,
                    "source_url": file_url,
                    "source_oid": item.get("oid") or (
                        item.get("lfs", {}).get("oid")
                        if isinstance(item.get("lfs"), dict)
                        else None
                    ),
                    "source_file_size": file_size,
                    "tensor": tensor,
                    "filename": str(asset.get("filename") or f"{tensor}.mp4"),
                    "offset": data_start + start,
                    "size": end - start,
                }
            )
    return discovered


def _read_index() -> dict[str, Any]:
    index_path = OUTPUT_DIR / "index.json"
    if not index_path.is_file():
        return {"assets": {}}
    with index_path.open("r", encoding="utf-8") as index_file:
        index = json.load(index_file)
    if not isinstance(index, dict) or not isinstance(index.get("assets"), dict):
        raise ValueError("Transcode index is malformed")
    return index


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as output_file:
            json.dump(value, output_file, ensure_ascii=False, indent=2)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _download_asset(asset: dict[str, Any], destination: Path) -> None:
    headers = _hf_headers()
    headers["Range"] = (
        f"bytes={asset['offset']}-{asset['offset'] + asset['size'] - 1}"
    )
    total = 0
    with urlopen(Request(asset["source_url"], headers=headers), timeout=60) as response:
        if response.status != 206:
            raise RuntimeError("Hugging Face did not honor the video byte range")
        with destination.open("wb") as output_file:
            while chunk := response.read(CHUNK_SIZE):
                output_file.write(chunk)
                total += len(chunk)
    if total != asset["size"]:
        raise RuntimeError(
            f"Incomplete video payload: expected {asset['size']} bytes, received {total}"
        )


def _probe_streams(path: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            FFPROBE_BIN,
            "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height,bit_rate",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("FFprobe returned invalid stream metadata") from error
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list):
        raise RuntimeError("FFprobe did not return stream metadata")
    return [stream for stream in streams if isinstance(stream, dict)]


def _select_crf(streams: list[dict[str, Any]]) -> int:
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("Source file has no video stream")
    width = video.get("width", 0)
    height = video.get("height", 0)
    try:
        bitrate = int(video.get("bit_rate", 0))
    except (TypeError, ValueError):
        bitrate = 0
    pixels = width * height if isinstance(width, int) and isinstance(height, int) else 0
    if pixels >= 1920 * 1080:
        return 21 if bitrate >= 8_000_000 else 22
    if pixels >= 1280 * 720:
        return 23 if bitrate >= 4_000_000 else 24
    return 25


def _transcode(source: Path, destination: Path) -> None:
    streams = _probe_streams(source)
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    args = [
        FFMPEG_BIN,
        "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
    ]
    if not has_audio:
        args.extend(
            [
                "-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
    args.extend(
        [
            "-map", "0:v:0",
            "-map", "0:a:0?" if has_audio else "1:a:0",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(_select_crf(streams)),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-f", "mp4",
        ]
    )
    if not has_audio:
        args.append("-shortest")
    args.append(str(destination))

    try:
        subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("TRANSCODE_TIMEOUT_SECONDS", "21600")),
        )
    except subprocess.CalledProcessError as error:
        details = (error.stderr or "").strip()[-2000:]
        raise RuntimeError(f"FFmpeg conversion failed: {details}") from error

    output_streams = _probe_streams(destination)
    if not any(
        stream.get("codec_type") == "video" and stream.get("codec_name") == "h264"
        for stream in output_streams
    ):
        raise RuntimeError("Converted MP4 does not contain an H.264 video stream")
    if not any(
        stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac"
        for stream in output_streams
    ):
        raise RuntimeError("Converted MP4 does not contain an AAC audio stream")


def _convert_one(asset: dict[str, Any], index: dict[str, Any]) -> bool:
    asset_key = asset["asset_key"]
    digest = asset["asset_id"]
    output_path = OUTPUT_DIR / f"{digest}.mp4"
    current = index["assets"].get(asset_key)
    source_fingerprint = {
        "source_file": asset["source_file"],
        "source_oid": asset.get("source_oid"),
        "source_file_size": asset["source_file_size"],
        "offset": asset["offset"],
        "size": asset["size"],
        "revision": DATASET_REVISION,
    }
    if (
        current
        and source_fingerprint["source_oid"] is not None
        and current.get("source") == source_fingerprint
        and output_path.is_file()
        and output_path.stat().st_size > 0
    ):
        return False

    source_path: Path | None = None
    temp_output = OUTPUT_DIR / f".{digest}.{uuid.uuid4().hex}.mp4"
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{digest}.",
            suffix=".source",
            dir=OUTPUT_DIR,
            delete=False,
        ) as source_file:
            source_path = Path(source_file.name)
        _download_asset(asset, source_path)
        _transcode(source_path, temp_output)
        os.replace(temp_output, output_path)
        index["assets"][asset_key] = {
            "asset_id": digest,
            "source_file": asset["source_file"],
            "tensor": asset["tensor"],
            "filename": asset["filename"],
            "source": source_fingerprint,
            "path": output_path.name,
            "size": output_path.stat().st_size,
            "video_codec": "h264",
            "audio_codec": "aac",
            "converted_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json_atomic(OUTPUT_DIR / "index.json", index)
        return True
    finally:
        if source_path:
            source_path.unlink(missing_ok=True)
        temp_output.unlink(missing_ok=True)


def convert_all() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    assets = discover_video_assets()
    index = _read_index()
    status_path = OUTPUT_DIR / "batch_status.json"
    failures: list[dict[str, str]] = []
    status: dict[str, Any] = {
        "state": "running",
        "total": len(assets),
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "errors": [],
    }
    _write_json_atomic(status_path, status)

    for asset in assets:
        try:
            converted = _convert_one(asset, index)
            status["completed"] += 1
            if not converted:
                status["skipped"] += 1
        except (OSError, RuntimeError, ValueError, URLError, TimeoutError, subprocess.SubprocessError) as error:
            logger.exception("Could not convert %s from %s", asset["tensor"], asset["source_file"])
            failures.append(
                {
                    "source_file": asset["source_file"],
                    "tensor": asset["tensor"],
                    "error": str(error),
                }
            )
            status["failed"] += 1
            status["errors"] = failures[-100:]
        _write_json_atomic(status_path, status)

    status["state"] = "failed" if failures else "completed"
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    status["converted"] = len(index["assets"])
    status["errors"] = failures[-100:]
    _write_json_atomic(status_path, status)
    return status


def get_converted_file(source_file: str, tensor: str) -> Path | None:
    index = _read_index()
    entry = index["assets"].get(_asset_key(source_file, tensor))
    if not isinstance(entry, dict):
        return None
    filename = entry.get("path")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("Transcode index contains an invalid output path")
    output_path = OUTPUT_DIR / filename
    return output_path if output_path.is_file() else None


def get_legacy_converted_file(tensor: str) -> Path | None:
    index = _read_index()
    matches = [
        entry
        for entry in index["assets"].values()
        if isinstance(entry, dict) and entry.get("tensor") == tensor
    ]
    if len(matches) > 1:
        raise ValueError("Tensor name is ambiguous; provide its Safetensors source file")
    if not matches:
        return None
    return get_converted_file(matches[0]["source_file"], tensor)


def get_conversion_status() -> dict[str, Any]:
    status_path = OUTPUT_DIR / "batch_status.json"
    if not status_path.is_file():
        return {"state": "not_started", "converted": 0, "total": 0}
    with status_path.open("r", encoding="utf-8") as status_file:
        status = json.load(status_file)
    if not isinstance(status, dict):
        raise ValueError("Transcode batch status is malformed")
    return status


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = convert_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed"]:
        raise SystemExit(1)
