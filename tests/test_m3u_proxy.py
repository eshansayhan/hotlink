import app.main as main
from fastapi.testclient import TestClient

from app.main import should_proxy_m3u_service


def test_m3u_proxy_routes_do_not_capture_streamer_video_api():
    assert should_proxy_m3u_service("GET", "/api/m3u-catalog")
    assert should_proxy_m3u_service("GET", "/api/playlist-shares")
    assert should_proxy_m3u_service("POST", "/api/app/activate")
    assert should_proxy_m3u_service("GET", "/api/m3u-admin/session")
    assert should_proxy_m3u_service("GET", "/api/m3u/a-random-token")
    assert not should_proxy_m3u_service("GET", "/api/videos")
    assert not should_proxy_m3u_service("POST", "/api/videos/upload")
    assert not should_proxy_m3u_service("GET", "/api/status")


def test_converted_video_routes_proxy_to_hfvideo_api():
    assert should_proxy_m3u_service("GET", "/api/converted")
    assert should_proxy_m3u_service("HEAD", "/api/converted")
    assert should_proxy_m3u_service("GET", "/api/transcode/status")
    assert not should_proxy_m3u_service("POST", "/api/converted")
    assert main.get_proxy_target_url(
        "/api/converted", "/api/converted?source_file=library.safetensors"
    ) == "http://127.0.0.1:8080/api/converted?source_file=library.safetensors"


def test_m3u_admin_page_and_video_stream_routes_are_proxied():
    assert should_proxy_m3u_service("GET", "/m3u-admin")
    assert should_proxy_m3u_service("GET", "/video/movie-123")
    assert should_proxy_m3u_service("HEAD", "/video/movie-123")
    assert not should_proxy_m3u_service("POST", "/video/movie-123")


def test_proxy_forwards_public_host_and_preserves_session_cookie(monkeypatch):
    calls = []

    class FakeUpstream:
        status_code = 200
        headers = {
            "content-type": "text/html; charset=utf-8",
            "set-cookie": "m3u_admin_session=test; HttpOnly",
        }

        def iter_content(self, chunk_size):
            yield b"admin panel"

        def close(self):
            pass

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeUpstream()

    monkeypatch.setattr(main.requests, "request", fake_request)
    response = TestClient(main.app).get(
        "/m3u-admin",
        headers={"host": "public.example", "x-forwarded-proto": "https"},
    )

    assert response.status_code == 200
    assert response.content == b"admin panel"
    assert response.headers["set-cookie"] == "m3u_admin_session=test; HttpOnly"
    assert calls[0][1] == "http://127.0.0.1:3000/m3u-admin"
    assert calls[0][2]["headers"]["x-forwarded-host"] == "public.example"
    assert calls[0][2]["headers"]["x-forwarded-proto"] == "https"
