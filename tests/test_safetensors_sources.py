import io
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main


class FakeResponse(io.BytesIO):
    def __init__(self, content, headers=None):
        super().__init__(content)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_discovery_includes_safetensors_from_all_tree_pages():
    first_page = [
        {"type": "file", "path": "season-1/episodes.safetensors", "size": 100},
        {"type": "file", "path": "ignored.pack", "size": 200},
        {"type": "file", "path": "../unsafe.safetensors", "size": 300},
    ]
    second_page = [
        {"type": "file", "path": "season-2/episodes.safetensors", "size": 400},
    ]

    def fake_urlopen(request, timeout):
        if request.full_url == main.SAFETENSORS_TREE_URL:
            return FakeResponse(
                json.dumps(first_page).encode(),
                {"Link": '<https://huggingface.co/api/datasets/page-2>; rel="next"'},
            )
        assert request.full_url == "https://huggingface.co/api/datasets/page-2"
        return FakeResponse(json.dumps(second_page).encode())

    with (
        patch.object(main, "_sf_files_cache", None),
        patch("app.main.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        assert main.discover_safetensors_files(force_refresh=True) == [
            "season-1/episodes.safetensors",
            "season-2/episodes.safetensors",
        ]


def test_same_tensor_name_is_read_from_the_requested_safetensors_file():
    file_headers = {
        "first.safetensors": {"video_0000": {"data_offsets": [0, 4]}},
        "second.safetensors": {"video_0000": {"data_offsets": [0, 9]}},
    }
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        source_file = request.full_url.rsplit("/", 1)[-1]
        header = json.dumps(file_headers[source_file]).encode()
        payload = len(header).to_bytes(8, "little") + header
        byte_range = request.get_header("Range")
        if byte_range == "bytes=0-7":
            return FakeResponse(payload[:8])
        return FakeResponse(payload[8:])

    with (
        patch.object(
            main,
            "discover_safetensors_files",
            return_value=["first.safetensors", "second.safetensors"],
        ),
        patch.object(main, "_sf_header_cache", {}),
        patch("app.main.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        first = main.get_safetensors_index("first.safetensors")
        second = main.get_safetensors_index("second.safetensors")

    assert first[0] == "first.safetensors"
    assert first[1]["video_0000"]["data_offsets"] == [0, 4]
    assert second[0] == "second.safetensors"
    assert second[1]["video_0000"]["data_offsets"] == [0, 9]
    assert any(url.endswith("/first.safetensors") for url in requested_urls)
    assert any(url.endswith("/second.safetensors") for url in requested_urls)


def test_ambiguous_legacy_stream_requires_an_explicit_source_file():
    with (
        patch.object(
            main,
            "discover_safetensors_files",
            return_value=["first.safetensors", "second.safetensors"],
        ),
        patch.object(main, "SAFETENSORS_DEFAULT_FILE", ""),
        pytest.raises(HTTPException) as error,
    ):
        main._resolve_safetensors_file("")

    assert error.value.status_code == 400


def test_catalog_metadata_keeps_source_file_in_stream_url_and_video_id():
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/catalog",
            "raw_path": b"/api/catalog",
            "query_string": b"",
            "headers": [(b"host", b"example.test")],
            "client": ("127.0.0.1", 12345),
            "server": ("example.test", 443),
        }
    )

    video = main.parse_video_metadata(
        "video_0000",
        0,
        1024,
        request,
        "season-1/episodes.safetensors",
    )

    assert video["id"] == "season-1/episodes.safetensors::video_0000"
    assert video["stream_url"].endswith(
        "/api/stream/video_0000?source_file=season-1%2Fepisodes.safetensors"
    )


def test_subtitle_endpoint_serves_embedded_vtt_and_turkish_chars():
    import asyncio
    header_data = {
        "sub_tr_0000": {"data_offsets": [0, 48]},
    }
    turkish_sub_bytes = "1\n00:00:01,000 --> 00:00:03,000\nTürkçe: Şirin, Ağır, Çiçek\n".encode("utf-8")

    def fake_urlopen(request, timeout):
        return FakeResponse(turkish_sub_bytes)

    with (
        patch.object(main, "_get_safetensors_index_async", return_value=("test.safetensors", header_data, 100)),
        patch("app.main.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        resp = asyncio.run(main.serve_safetensors_subtitle("video_0000", lang="tr"))
        assert resp.status_code == 200
        content = resp.body.decode("utf-8")
        assert "WEBVTT" in content
        assert "Türkçe: Şirin, Ağır, Çiçek" in content
        assert resp.headers["content-type"].startswith("text/vtt")


def test_subtitle_endpoint_returns_404_when_missing():
    import asyncio
    header_data = {
        "video_0000": {"data_offsets": [0, 100]},
    }
    with (
        patch.object(main, "_get_safetensors_index_async", return_value=("test.safetensors", header_data, 100)),
        pytest.raises(HTTPException) as exc,
    ):
        asyncio.run(main.serve_safetensors_subtitle("video_0000", lang="tr"))
    assert exc.value.status_code == 404


def test_cover_endpoint_serves_valid_image_and_resolves_video_prefix():
    import asyncio
    header_data = {
        "video_0000": {"data_offsets": [0, 1000000]},
        "cover_0000": {"data_offsets": [1000000, 1043444]},
    }
    fake_webp_bytes = b"RIFF\x2c\xa9\x00\x00WEBPVP8 " + b"\x00" * 100

    def fake_urlopen(request, timeout):
        return FakeResponse(fake_webp_bytes)

    with (
        patch.object(main, "_get_safetensors_index_async", return_value=("test.safetensors", header_data, 100)),
        patch("app.main.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        # Even if video_0000 is requested, resolve_tensor_name resolves to cover_0000
        resp = asyncio.run(main.serve_safetensors_cover("video_0000", source_file="test.safetensors"))
        assert resp.status_code == 200
        assert resp.media_type == "image/webp"
        assert resp.body == fake_webp_bytes
        assert "immutable" in resp.headers.get("cache-control", "")



