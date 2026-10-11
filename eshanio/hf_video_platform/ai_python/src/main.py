import json
import logging
import os
import re
import struct
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

if __package__:
    from .transcode import (
        get_conversion_status,
        get_converted_file,
        get_legacy_converted_file,
    )
else:
    from transcode import (
        get_conversion_status,
        get_converted_file,
        get_legacy_converted_file,
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hfvideo_api")

DATASET_REPO = os.getenv("HF_DATASET_REPO", "eshansayhan/movie")
DATASET_REVISION = os.getenv("HF_DATASET_REVISION", "main")
MASTER_INDEX_URL = os.getenv(
    "HF_MASTER_INDEX_URL",
    f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/{DATASET_REVISION}/master_index.json",
)
CACHE_TTL_SECONDS = max(0, int(os.getenv("VIDEO_CACHE_TTL_SECONDS", "60")))
LOCAL_MASTER_INDEX = Path(__file__).resolve().parents[2] / "master_index.json"
CHUNK_SIZE = 64 * 1024
PACK_TAIL_SIZE = 64 * 1024
MAX_PACK_HEADER_SIZE = 20 * 1024 * 1024
HF_TOKEN = os.getenv("HF_TOKEN", "")

app = FastAPI(title="HFVideoPlatform Video API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Accept-Ranges", "Content-Length", "Content-Range"],
)

_video_cache: list[dict[str, Any]] | None = None
_video_cache_at = 0.0


def _valid_catalog(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("videos"), list):
        raise ValueError("Master index must contain a videos array")
    return [video for video in data["videos"] if isinstance(video, dict)]


def _read_local_catalog() -> list[dict[str, Any]] | None:
    if not LOCAL_MASTER_INDEX.is_file():
        return None
    with LOCAL_MASTER_INDEX.open("r", encoding="utf-8") as master_file:
        return _valid_catalog(json.load(master_file))


def _hf_headers() -> dict[str, str]:
    headers = {"User-Agent": "HFVideoPlatform-Video-API/1.0"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    return headers


def _parse_pack_header(tail: bytes) -> list[dict[str, Any]] | None:
    if len(tail) < 8:
        return None
    header_size = struct.unpack("<Q", tail[-8:])[0]
    if header_size <= 0 or header_size > len(tail) - 8:
        return None
    header_bytes = tail[-8 - header_size : -8]
    try:
        header_text = header_bytes.decode("utf-8")
        object_start = header_text.find("{")
        if object_start < 0:
            return None
        header = json.loads(header_text[object_start:])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    videos = header.get("videos") if isinstance(header, dict) else None
    if not isinstance(videos, list):
        return None
    return [video for video in videos if isinstance(video, dict)]


def _fetch_range(url: str, start: int, end: int) -> bytes:
    headers = _hf_headers()
    headers["Range"] = f"bytes={start}-{end}"
    request = UrlRequest(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        if response.status != 206:
            return b""
        return response.read(end - start + 1)


def _discover_catalog_from_packs() -> list[dict[str, Any]]:
    tree_url = (
        f"https://huggingface.co/api/datasets/{DATASET_REPO}/tree/"
        f"{quote(DATASET_REVISION, safe='')}?recursive=true"
    )
    request = UrlRequest(tree_url, headers=_hf_headers())
    with urlopen(request, timeout=20) as response:
        tree = json.load(response)
    if not isinstance(tree, list):
        raise ValueError("Hugging Face dataset tree response must be a list")

    base_url = (
        f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/"
        f"{quote(DATASET_REVISION, safe='')}/"
    )
    discovered: dict[str, dict[str, Any]] = {}
    for item in tree:
        if not isinstance(item, dict):
            continue
        pack_path = item.get("path")
        pack_size = _positive_int(item.get("size"))
        if not isinstance(pack_path, str) or not pack_path.endswith(".pack") or pack_size < 8:
            continue

        pack_url = urljoin(base_url, quote(pack_path, safe="/"))
        tail_size = min(pack_size, PACK_TAIL_SIZE)
        try:
            tail = _fetch_range(pack_url, pack_size - tail_size, pack_size - 1)
            videos = _parse_pack_header(tail)
            if videos is None and len(tail) >= 8:
                header_size = struct.unpack("<Q", tail[-8:])[0]
                if 0 < header_size <= MAX_PACK_HEADER_SIZE and header_size + 8 <= pack_size:
                    tail = _fetch_range(pack_url, pack_size - header_size - 8, pack_size - 1)
                    videos = _parse_pack_header(tail)
        except (URLError, TimeoutError, OSError, ValueError) as error:
            logger.warning("Could not read pack header from %s: %s", pack_path, error)
            continue

        if videos is None:
            logger.warning("No readable video header found in %s", pack_path)
            continue
        for video in videos:
            video.setdefault("pack", pack_path)
            video.setdefault("node_url", base_url.rstrip("/"))
            video.setdefault("pack_url", pack_url)
            video.setdefault("source_repo", DATASET_REPO)
            video.setdefault("source_revision", DATASET_REVISION)
            video_id = _video_id(video)
            if video_id:
                discovered[video_id] = video

    return list(discovered.values())


def get_video_catalog(force_refresh: bool = False) -> list[dict[str, Any]]:
    global _video_cache, _video_cache_at

    now = time.monotonic()
    if (
        not force_refresh
        and _video_cache is not None
        and now - _video_cache_at < CACHE_TTL_SECONDS
    ):
        return _video_cache

    try:
        headers = {"User-Agent": "HFVideoPlatform-Video-API/1.0"}
        if HF_TOKEN:
            headers["Authorization"] = f"Bearer {HF_TOKEN}"
        request = UrlRequest(MASTER_INDEX_URL, headers=headers)
        with urlopen(request, timeout=10) as response:
            remote_catalog = _valid_catalog(json.load(response))
        _video_cache = remote_catalog
        _video_cache_at = now
        return remote_catalog
    except (URLError, TimeoutError, OSError, ValueError) as error:
        logger.warning("Hugging Face master index could not be loaded: %s", error)

    try:
        discovered_catalog = _discover_catalog_from_packs()
    except (URLError, TimeoutError, OSError, ValueError) as error:
        logger.warning("Hugging Face video packs could not be indexed: %s", error)
        discovered_catalog = []
    if discovered_catalog:
        _video_cache = discovered_catalog
        _video_cache_at = now
        return discovered_catalog

    try:
        local_catalog = _read_local_catalog()
    except (OSError, ValueError) as error:
        logger.warning("Local master index could not be loaded: %s", error)
        local_catalog = None

    if local_catalog is not None:
        _video_cache = local_catalog
        _video_cache_at = now
        return local_catalog
    if _video_cache is not None:
        logger.warning("Using stale video catalog because the data source is unavailable")
        return _video_cache
    raise HTTPException(
        status_code=502,
        detail="Video catalog is unavailable; check the Hugging Face dataset settings.",
    )


def _video_id(video: dict[str, Any]) -> str:
    value = video.get("id")
    if value is None or str(value).strip() == "":
        value = video.get("name") or video.get("title")
    return str(value) if value is not None else ""


def _positive_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return result if result > 0 else 0


def _nonnegative_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return result if result >= 0 else 0


def _is_hugging_face_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "huggingface.co"
        or host.endswith(".huggingface.co")
        or host == "hf.co"
        or host.endswith(".hf.co")
    )


def _pack_url(video: dict[str, Any]) -> str:
    direct_url = video.get("pack_url")
    if isinstance(direct_url, str) and _is_hugging_face_url(direct_url):
        return direct_url

    pack = video.get("pack") or video.get("pack_file")
    pack_parts = Path(pack).parts if isinstance(pack, str) else ()
    if (
        not isinstance(pack, str)
        or not pack.strip()
        or pack.startswith(("/", "\\"))
        or "\\" in pack
        or any(part in {".", ".."} for part in pack_parts)
    ):
        return ""

    node_url = video.get("node_url")
    if isinstance(node_url, str) and _is_hugging_face_url(node_url):
        base_url = node_url.rstrip("/") + "/"
    else:
        source_repo = video.get("source_repo")
        repo_parts = source_repo.split("/") if isinstance(source_repo, str) else []
        repo = (
            source_repo
            if len(repo_parts) == 2
            and all(
                part not in {"", ".", ".."}
                and re.fullmatch(r"[A-Za-z0-9_.-]+", part)
                for part in repo_parts
            )
            else DATASET_REPO
        )
        base_url = (
            f"https://huggingface.co/datasets/{repo}/resolve/"
            f"{quote(DATASET_REVISION, safe='')}/"
        )
    return urljoin(base_url, quote(pack, safe="/"))


def serialize_video(video: dict[str, Any], base_url: str) -> dict[str, Any]:
    video_id = _video_id(video)
    encoded_id = quote(video_id, safe="")
    api_base = f"{base_url.rstrip('/')}/api/videos/{encoded_id}"
    external_cover = video.get("cover_url") or video.get("cover")
    if not isinstance(external_cover, str) or not external_cover.startswith(("https://", "http://")):
        external_cover = f"{api_base}/thumbnail"

    return {
        "id": video_id,
        "title": str(video.get("title") or video.get("name") or "Untitled video"),
        "thumbnail_url": external_cover,
        "stream_url": f"{api_base}/stream",
        "duration": _positive_int(video.get("duration")),
        "description": str(video.get("description") or ""),
        "category": str(video.get("category") or ""),
        "genre": str(video.get("genre") or ""),
        "year": str(video.get("year") or ""),
        "content_type": str(video.get("content_type") or video.get("type") or ""),
        "is_series": bool(video.get("is_series", False)),
    }


def _find_video(video_id: str) -> dict[str, Any]:
    for video in get_video_catalog():
        if _video_id(video) == video_id:
            return video
    raise HTTPException(status_code=404, detail="Video not found")


def _video_source(video: dict[str, Any]) -> tuple[str, int, int]:
    source_url = _pack_url(video)
    offset = _nonnegative_int(video.get("offset"))
    size = _positive_int(video.get("size"))
    if not source_url or size == 0:
        raise HTTPException(
            status_code=404,
            detail="Video is missing a valid Hugging Face pack URL, offset, or size.",
        )
    return source_url, offset, size


def _parse_byte_range(range_header: str | None, total_size: int) -> tuple[int, int] | None:
    if total_size <= 0:
        return None
    if not range_header:
        return 0, total_size - 1
    if len(range_header) > 128:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match:
        return None

    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        suffix_size = int(end_text)
        if suffix_size <= 0:
            return None
        return max(0, total_size - suffix_size), total_size - 1

    start = int(start_text)
    end = int(end_text) if end_text else total_size - 1
    if start >= total_size or end < start:
        return None
    return start, min(end, total_size - 1)


def _open_pack_range(
    source_url: str, pack_offset: int, start: int, end: int
):
    headers = {
        "Range": f"bytes={pack_offset + start}-{pack_offset + end}",
        "User-Agent": "HFVideoPlatform-Video-API/1.0",
    }
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    try:
        response = urlopen(UrlRequest(source_url, headers=headers), timeout=20)
    except (URLError, TimeoutError, OSError) as error:
        logger.error("Could not fetch video bytes from Hugging Face: %s", error)
        raise HTTPException(status_code=502, detail="Video stream could not be fetched.") from error

    if response.status != 206:
        response.close()
        raise HTTPException(
            status_code=502,
            detail="Hugging Face did not honor the requested byte range.",
        )
    return response


def _iter_response(response):
    try:
        while chunk := response.read(CHUNK_SIZE):
            yield chunk
    finally:
        response.close()


def _iter_local_file(path: Path, start: int, length: int):
    with path.open("rb") as video_file:
        video_file.seek(start)
        remaining = length
        while remaining:
            chunk = video_file.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _converted_response(path: Path, request: Request):
    total_size = path.stat().st_size
    byte_range = _parse_byte_range(request.headers.get("range"), total_size)
    if byte_range is None:
        raise HTTPException(
            status_code=416,
            detail="Requested byte range is not satisfiable.",
            headers={"Content-Range": f"bytes */{total_size}"},
        )

    start, end = byte_range
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        "Content-Length": str(end - start + 1),
    }
    status_code = 200
    if request.headers.get("range"):
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
    return StreamingResponse(
        _iter_local_file(path, start, end - start + 1),
        status_code=status_code,
        media_type="video/mp4",
        headers=headers,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "HFVideoPlatform Video API"}


@app.get("/api/videos")
def list_videos(request: Request) -> list[dict[str, Any]]:
    catalog = get_video_catalog()
    base_url = str(request.base_url).rstrip("/")
    return [
        serialize_video(video, base_url)
        for video in catalog
        if _video_id(video)
    ]


@app.get("/api/videos/{video_id}")
def get_video(video_id: str, request: Request) -> dict[str, Any]:
    return serialize_video(_find_video(video_id), str(request.base_url).rstrip("/"))


@app.get("/api/videos/{video_id}/stream", name="stream_video")
def stream_video(video_id: str, request: Request):
    video = _find_video(video_id)
    source_url, pack_offset, total_size = _video_source(video)
    byte_range = _parse_byte_range(request.headers.get("range"), total_size)
    if byte_range is None:
        raise HTTPException(
            status_code=416,
            detail="Requested byte range is not satisfiable.",
            headers={"Content-Range": f"bytes */{total_size}"},
        )

    start, end = byte_range
    upstream = _open_pack_range(source_url, pack_offset, start, end)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }
    status_code = 200
    if request.headers.get("range"):
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
    return StreamingResponse(
        _iter_response(upstream),
        status_code=status_code,
        media_type="video/mp4",
        headers=headers,
    )


@app.get("/api/transcode/status")
def transcode_status() -> dict[str, Any]:
    try:
        return get_conversion_status()
    except (OSError, ValueError) as error:
        logger.error("Could not read transcode status: %s", error)
        raise HTTPException(status_code=500, detail="Transcode status is unavailable.") from error


@app.get("/api/converted")
def stream_converted_video(source_file: str, tensor: str, request: Request):
    try:
        path = get_converted_file(source_file, tensor)
    except (OSError, ValueError) as error:
        logger.error("Could not resolve converted video: %s", error)
        raise HTTPException(status_code=500, detail="Converted video index is unavailable.") from error
    if path is None:
        raise HTTPException(
            status_code=503,
            detail="H.264/AAC MP4 is not ready; run the Safetensors batch converter.",
            headers={"Retry-After": "300"},
        )
    return _converted_response(path, request)


@app.get("/api/stream/{asset_id}")
def stream_legacy_converted_video(asset_id: str, request: Request):
    try:
        path = get_legacy_converted_file(asset_id)
    except (OSError, ValueError) as error:
        logger.error("Could not resolve legacy converted video id %s: %s", asset_id, error)
        raise HTTPException(status_code=409, detail=str(error)) from error
    if path is None:
        raise HTTPException(
            status_code=503,
            detail="H.264/AAC MP4 is not ready; run the Safetensors batch converter.",
            headers={"Retry-After": "300"},
        )
    return _converted_response(path, request)


@app.get("/api/videos/{video_id}/thumbnail", name="get_thumbnail")
def get_thumbnail(video_id: str):
    video = _find_video(video_id)
    cover_url = video.get("cover_url") or video.get("cover")
    if isinstance(cover_url, str) and cover_url.startswith(("http://", "https://")):
        return Response(status_code=307, headers={"Location": cover_url})

    cover_size = _positive_int(video.get("cover_size"))
    if cover_size:
        source_url, pack_offset, _ = _video_source(
            {
                **video,
                "offset": video.get("cover_offset", 0),
                "size": cover_size,
            }
        )
        upstream = _open_pack_range(source_url, pack_offset, 0, cover_size - 1)
        mime_type = str(video.get("cover_mime") or "image/jpeg")
        return StreamingResponse(
            _iter_response(upstream),
            media_type=mime_type,
            headers={"Content-Length": str(cover_size), "Cache-Control": "public, max-age=3600"},
        )

    return Response(
        content=(
            "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180'>"
            "<rect width='100%' height='100%' fill='#111120'/>"
            "<text x='50%' y='50%' fill='#9496b8' text-anchor='middle' "
            "dominant-baseline='middle'>No thumbnail</text></svg>"
        ),
        media_type="image/svg+xml",
    )


@app.get("/api/ai/recommend")
async def recommend() -> dict[str, Any]:
    return {
        "status": "success",
        "message": "AI Engine is running",
        "recommendations": [],
    }


static_root = Path(__file__).resolve().parents[1]
if (static_root / "index.html").is_file():
    app.mount("/", StaticFiles(directory=static_root, html=True), name="frontend")


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    logger.info("HFVideoPlatform Video API starting on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
