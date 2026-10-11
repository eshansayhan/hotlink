import time
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie

import pytest
import requests
from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient

from app import access_store, main


@pytest.fixture
def access_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HFSTREAM_ACCESS_DB", str(tmp_path / "access.sqlite3"))
    monkeypatch.setenv("HFSTREAM_AUTH_SECRET", "test-api-secret")
    monkeypatch.setenv("DISCORD_ADMIN_USER_ID", "owner-id")
    access_store.initialize()
    return None


def make_request(path, query="", cookies=None, body=b"", extra_headers=None):
    headers = []
    if cookies:
        headers.append(
            (b"cookie", "; ".join(f"{key}={value}" for key, value in cookies.items()).encode())
        )
    if extra_headers:
        for k, v in extra_headers.items():
            headers.append((k.lower().encode(), str(v).encode()))
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive=receive,
    )


def run_middleware(path, query="", cookies=None):
    messages = []
    headers = []
    if cookies:
        headers.append(
            (b"cookie", "; ".join(f"{key}={value}" for key, value in cookies.items()).encode())
        )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    asyncio.run(
        main.DisabledAccessRoutesMiddleware(downstream)(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": query.encode(),
                "headers": headers,
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "root_path": "",
            },
            receive,
            send,
        )
    )
    return messages[0]["status"]


def test_catalog_is_public_and_contains_all_videos(access_environment, monkeypatch):
    videos = [
        {"id": "movie.safetensors::video_0000", "title": "Guest movie"},
        {"id": "movie.safetensors::video_0001", "title": "Private movie"},
    ]

    async def list_videos(request, search="", season=0):
        return {"videos": videos, "total": len(videos)}

    monkeypatch.setattr(main, "list_all_video_apis", list_videos)
    access_store.update_settings([], 24)

    # 1. Giriş yapılmadığında liste boştur
    unauth_resp = asyncio.run(main.get_accessible_videos(make_request("/api/access/videos")))
    assert unauth_resp["videos"] == []

    # 2. Oturum açıldığında tüm videolar döner
    code = access_store.issue_code("test_cat_user")
    redemption = access_store.redeem_code(code, "dev_cat_123", "127.0.0.1", 24)
    token = access_store.create_access_session(redemption["code_hash"], redemption["discord_user_id"], redemption["expires_at"])
    req = make_request("/api/access/videos", cookies={"hf_access_session": token, "hf_device_id": "dev_cat_123"})

    response = asyncio.run(main.get_accessible_videos(req))
    assert [video["id"] for video in response["videos"]] == [
        "movie.safetensors::video_0000",
        "movie.safetensors::video_0001",
    ]


def test_stream_is_public_for_all_videos(access_environment, monkeypatch):
    async def fake_stream(tensor_name="", source_file="", request=None, **kwargs):
        return Response(content=f"{source_file}::{tensor_name}")

    monkeypatch.setattr(main, "stream_safetensors_video", fake_stream)

    first = asyncio.run(
        main.stream_access_video(
            "video_0000",
            make_request("/api/access/stream/video_0000"),
            "movie.safetensors",
        )
    )
    second = asyncio.run(
        main.stream_access_video(
            "video_0001",
            make_request("/api/access/stream/video_0001"),
            "movie.safetensors",
        )
    )
    assert first.body == b"movie.safetensors::video_0000"
    assert second.body == b"movie.safetensors::video_0001"


def test_catalog_and_stream_are_public_while_access_apis_are_disabled(
    access_environment, monkeypatch
):
    monkeypatch.setattr(main, "load_embed_config", lambda: {
        "api_enabled": False,
        "embed_enabled": True,
    })
    monkeypatch.setattr(main, "discover_safetensors_files", lambda: ["movie.safetensors"])
    monkeypatch.setattr(
        main,
        "get_safetensors_index",
        lambda source_file: (
            "movie.safetensors",
            {"video_0000": {"data_offsets": [0, 1]}},
            0,
        ),
    )
    monkeypatch.setattr(
        main,
        "parse_video_metadata",
        lambda tensor, index, size, request, source_file, **kwargs: {
            "id": f"{source_file}::{tensor}",
            "stream_url": f"/api/stream/{tensor}?source_file={source_file}",
        },
    )

    class FakeUpstream:
        sent = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            if self.sent:
                return b""
            self.sent = True
            return b"x"

    monkeypatch.setattr(
        main.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeUpstream(),
    )

    client = TestClient(main.app)
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["videos"] == [
        {
            "id": "movie.safetensors::video_0000",
            "stream_url": "/api/stream/video_0000?source_file=movie.safetensors",
        }
    ]

    stream = client.get(
        "/api/stream/video_0000",
        params={"source_file": "movie.safetensors"},
    )
    assert stream.status_code == 206
    assert stream.headers["content-range"] == "bytes 0-0/1"
    assert stream.content == b"x"

    legacy_stream = client.get(
        "/api/access/stream/video_0000",
        params={"source_file": "movie.safetensors"},
    )
    assert legacy_stream.status_code == 206
    assert legacy_stream.headers["content-range"] == "bytes 0-0/1"
    assert legacy_stream.content == b"x"

    for path in (
        "/api/access/login",
        "/api/access/admin/settings",
        "/api/access/stream/heartbeat",
        "/auth/discord/callback",
    ):
        assert client.get(path).status_code == 410


def test_slow_catalog_upstream_does_not_block_other_requests(
    access_environment, monkeypatch
):
    upstream_started = threading.Event()
    release_upstream = threading.Event()
    monkeypatch.setattr(main, "discover_safetensors_files", lambda: ["movie.safetensors"])

    def slow_index(source_file):
        upstream_started.set()
        assert release_upstream.wait(timeout=3)
        return source_file, {"video_0000": {"data_offsets": [0, 1]}}, 0

    monkeypatch.setattr(main, "get_safetensors_index", slow_index)
    monkeypatch.setattr(
        main,
        "parse_video_metadata",
        lambda tensor, index, size, request, source_file, **kwargs: {
            "id": f"{source_file}::{tensor}",
            "stream_url": f"/api/stream/{tensor}?source_file={source_file}",
            "title": "Test video",
            "description": "",
        },
    )

    code = access_store.issue_code("slow_user")
    redemption = access_store.redeem_code(code, "dev_slow", "127.0.0.1", 24)
    token = access_store.create_access_session(redemption["code_hash"], redemption["discord_user_id"], redemption["expires_at"])
    client = TestClient(main.app, cookies={"hf_access_session": token, "hf_device_id": "dev_slow"})
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            catalog_future = executor.submit(client.get, "/api/catalog")
            assert upstream_started.wait(timeout=1)
            config_future = executor.submit(client.get, "/api/config/embed")
            config = config_future.result(timeout=1)
            release_upstream.set()
            catalog = catalog_future.result(timeout=3)
    finally:
        release_upstream.set()

    assert config.status_code == 200
    assert catalog.status_code == 200


def test_discord_admin_session_can_open_admin_api(access_environment):
    token, _ = access_store.create_admin_session("password-admin")

    response = main.get_admin_access_settings(
        make_request("/api/access/admin/settings", cookies={"hf_admin_session": token})
    )
    assert response["public_video_ids"] == []


def test_admin_password_login_sets_http_only_session(access_environment, monkeypatch):
    admin_password = "a-long-random-admin-password"
    monkeypatch.setenv("HFSTREAM_ADMIN_PASSWORD", admin_password)

    response = asyncio.run(
        main.login_admin_with_password(
            make_request(
                "/api/access/admin/login",
                body=json.dumps({"password": admin_password}).encode(),
            )
        )
    )

    assert response.status_code == 200
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert cookie["hf_admin_session"]["httponly"]
    assert access_store.get_admin_session(
        cookie["hf_admin_session"].value,
        "password-admin",
    ) is not None


def test_admin_password_rejects_invalid_or_weak_configuration(access_environment, monkeypatch):
    monkeypatch.setenv("HFSTREAM_ADMIN_PASSWORD", "short")
    with pytest.raises(HTTPException) as weak_config:
        asyncio.run(
            main.login_admin_with_password(
                make_request("/api/access/admin/login", body=b'{"password":"short"}')
            )
        )
    assert weak_config.value.status_code == 503

    monkeypatch.setenv("HFSTREAM_ADMIN_PASSWORD", "a-long-random-admin-password")
    with pytest.raises(HTTPException) as wrong_password:
        asyncio.run(
            main.login_admin_with_password(
                make_request("/api/access/admin/login", body=b'{"password":"wrong"}')
            )
        )
    assert wrong_password.value.status_code == 401


def test_admin_password_login_rate_limit(access_environment, monkeypatch):
    monkeypatch.setenv("HFSTREAM_ADMIN_PASSWORD", "a-long-random-admin-password")
    for _ in range(12):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(
                main.login_admin_with_password(
                    make_request("/api/access/admin/login", body=b'{"password":"wrong"}')
                )
            )
        assert denied.value.status_code == 401

    with pytest.raises(HTTPException) as limited:
        asyncio.run(
            main.login_admin_with_password(
                make_request(
                    "/api/access/admin/login",
                    body=b'{"password":"a-long-random-admin-password"}',
                )
            )
        )
    assert limited.value.status_code == 429


def test_login_sets_device_bound_http_only_session(access_environment):
    code = access_store.issue_code("discord-user")
    response = asyncio.run(
        main.login_with_access_code(
            make_request(
                "/api/access/login",
                cookies={"hf_device_id": "device-one"},
                body=json.dumps({"code": code}).encode(),
            )
        )
    )
    assert response.status_code == 200
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    session_token = cookie["hf_access_session"].value
    assert cookie["hf_access_session"]["httponly"]
    assert access_store.get_access_session(session_token, "device-one") is not None
    assert access_store.get_access_session(session_token, "device-two") is not None


def test_oauth_timeout_returns_safe_error_without_breaking_error_logging(access_environment, monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "test-client-secret")
    access_store.save_oauth_state("oauth-state", "oauth-nonce")
    logged = []

    def raise_timeout(*args, **kwargs):
        raise requests.ReadTimeout("Discord request timed out")

    monkeypatch.setattr(main.requests, "request", raise_timeout)
    monkeypatch.setattr(main.stream_logger, "error", lambda tag, message: logged.append((tag, message)))

    with pytest.raises(main.HTTPException) as result:
        main.finish_admin_discord_login(
            make_request(
                "/auth/discord/callback",
                cookies={"hf_admin_oauth_nonce": "oauth-nonce"},
            ),
            code="authorization-code",
            state="oauth-state",
        )

    assert result.value.status_code == 502
    assert logged[0][0] == "AUTH"
    assert "Discord request timed out" in logged[0][1]


def test_discord_api_request_retries_tls_handshake_failure(monkeypatch):
    expected_response = object()
    calls = []

    def flaky_request(method, url, **kwargs):
        calls.append((method, url))
        if len(calls) == 1:
            raise requests.exceptions.SSLError("TLS handshake closed")
        return expected_response

    monkeypatch.setattr(main.requests, "request", flaky_request)
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)

    response = main._discord_api_request("POST", "https://discord.com/api/oauth2/token")

    assert response is expected_response
    assert len(calls) == 2


def test_discord_api_request_stops_after_three_tls_failures(monkeypatch):
    calls = []

    def failing_request(method, url, **kwargs):
        calls.append((method, url))
        raise requests.exceptions.SSLError("TLS handshake closed")

    monkeypatch.setattr(main.requests, "request", failing_request)
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)

    with pytest.raises(requests.exceptions.SSLError):
        main._discord_api_request("GET", "https://discord.com/api/users/@me")

    assert len(calls) == 3


def test_discord_interactions_ping_and_command(access_environment, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_hex = pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", pub_hex)

    # 1. PING
    ts = "1234567890"
    ping_body = b'{"type": 1}'
    sig = priv.sign(ts.encode("utf-8") + ping_body).hex()

    req = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig, "x-signature-timestamp": ts},
        body=ping_body,
    )
    resp = asyncio.run(main.handle_discord_interactions(req))
    assert resp.status_code == 200
    assert json.loads(resp.body.decode()) == {"type": 1}

    # 2. Invalid signature
    bad_req = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": "bad" * 21 + "a", "x-signature-timestamp": ts},
        body=ping_body,
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.handle_discord_interactions(bad_req))
    assert exc.value.status_code == 401

    # 3. /kod command
    cmd_body = json.dumps({
        "type": 2,
        "data": {"name": "kod"},
        "member": {"user": {"id": "123456789"}},
        "channel_id": "999",
    }).encode("utf-8")
    sig_cmd = priv.sign(ts.encode("utf-8") + cmd_body).hex()

    cmd_req = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig_cmd, "x-signature-timestamp": ts},
        body=cmd_body,
    )
    resp_cmd = asyncio.run(main.handle_discord_interactions(cmd_req))
    assert resp_cmd.status_code == 200
    data = json.loads(resp_cmd.body.decode())
    assert data["type"] == 4
    assert "HFStream" in data["data"]["content"]
    assert len(data["data"]["components"][0]["components"]) == 2

    # 4. /bilgi command test
    bilgi_body = json.dumps({
        "type": 2,
        "data": {"name": "bilgi"},
        "member": {"user": {"id": "123456789"}},
        "channel_id": "999",
    }).encode("utf-8")
    sig_bilgi = priv.sign(ts.encode("utf-8") + bilgi_body).hex()
    bilgi_req = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig_bilgi, "x-signature-timestamp": ts},
        body=bilgi_body,
    )
    resp_bilgi = asyncio.run(main.handle_discord_interactions(bilgi_req))
    data_bilgi = json.loads(resp_bilgi.body.decode())
    assert "Aktif Kodunuz" in data_bilgi["data"]["content"]
    assert len(data_bilgi["data"]["components"][0]["components"]) == 2



def test_admin_generate_access_code(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    req = make_request(
        "/api/access/admin/codes/generate",
        cookies={"hf_admin_session": token},
    )
    resp = main.generate_admin_access_code(req)
    assert "code" in resp
    assert len(resp["code"]) == 14
    assert resp["url"].startswith("https://")



def test_admin_analytics_endpoint(access_environment):
    access_store.issue_code("user-a")
    access_store.record_video_view("movie.safetensors::video_0000", "Bölüm 1")
    token, _ = access_store.create_admin_session("password-admin")

    req = make_request(
        "/api/access/admin/analytics",
        cookies={"hf_admin_session": token},
    )
    resp = main.get_admin_analytics(req)
    assert resp["codes_today"] >= 1
    assert resp["total_codes"] >= 1
    assert len(resp["top_videos"]) >= 1
    assert resp["top_videos"][0]["views"] >= 1


def test_admin_custom_code_endpoint(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    req = make_request(
        "/api/access/admin/codes/custom",
        cookies={"hf_admin_session": token},
    )
    custom_req = main.CustomCodeRequest(hours=72, note="VIP Ahmet")
    resp = main.generate_custom_access_code(custom_req, req)
    assert "code" in resp
    assert resp["hours"] == 72
    assert resp["note"] == "VIP Ahmet"

    # Verify redemption uses custom hours
    redeem = access_store.redeem_code(resp["code"], "dev-vip", "1.2.3.4")
    assert redeem is not None
    # Check expiry is roughly now + 72h
    assert redeem["expires_at"] > int(time.time()) + 71 * 3600


def test_discord_interactions_role_requirement_and_vip(access_environment, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_hex = pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", pub_hex)
    monkeypatch.setenv("DISCORD_REQUIRED_ROLE_ID", "55555")
    monkeypatch.setenv("DISCORD_VIP_ROLE_ID", "77777")
    monkeypatch.setenv("DISCORD_VIP_HOURS", "48")

    ts = "1234567890"

    # 1. User without required role
    no_role_body = json.dumps({
        "type": 2,
        "data": {"name": "kod"},
        "member": {"user": {"id": "user-no-role"}, "roles": ["11111"]},
        "channel_id": "999",
    }).encode("utf-8")
    sig1 = priv.sign(ts.encode("utf-8") + no_role_body).hex()
    req1 = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig1, "x-signature-timestamp": ts},
        body=no_role_body,
    )
    resp1 = asyncio.run(main.handle_discord_interactions(req1))
    data1 = json.loads(resp1.body.decode())
    assert "gerekli sunucu rolüne sahip olmanız" in data1["data"]["content"]

    # 2. User with required role + VIP role
    vip_body = json.dumps({
        "type": 2,
        "data": {"name": "kod"},
        "member": {"user": {"id": "user-vip"}, "roles": ["55555", "77777"]},
        "channel_id": "999",
    }).encode("utf-8")
    sig2 = priv.sign(ts.encode("utf-8") + vip_body).hex()
    req2 = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig2, "x-signature-timestamp": ts},
        body=vip_body,
    )
    resp2 = asyncio.run(main.handle_discord_interactions(req2))
    data2 = json.loads(resp2.body.decode())
    assert "VIP / Booster" in data2["data"]["content"]
    assert "48 saatlik" in data2["data"]["content"]


def test_admin_cleanup_codes(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    c1 = access_store.issue_code("user-old-1")
    # revoke c1
    access_store.revoke_code(access_store.digest(c1))

    req = make_request(
        "/api/access/admin/codes/cleanup",
        cookies={"hf_admin_session": token},
    )
    resp = main.cleanup_admin_codes(req)
    assert resp["success"] is True
    assert resp["deleted_count"] >= 1


def test_banned_clients_and_access_block(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    req = make_request("/api/access/admin/banned", cookies={"hf_admin_session": token})

    # 1. Ban an IP
    ban_req = main.BanClientRequest(identifier="192.168.1.99", client_type="ip", reason="Spam")
    resp_ban = main.add_admin_banned_client(ban_req, req)
    assert resp_ban["success"] is True
    assert access_store.is_banned("192.168.1.99") is True

    # 2. Redeem fails for banned IP
    code = access_store.issue_code("user-banned")
    assert access_store.redeem_code(code, "dev-1", "192.168.1.99") is None

    # 3. Unban
    resp_unban = main.remove_admin_banned_client("192.168.1.99", req)
    assert resp_unban["success"] is True
    assert access_store.is_banned("192.168.1.99") is False


def test_issue_reports_flow(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    admin_req = make_request("/api/access/admin/reports", cookies={"hf_admin_session": token})

    # 1. Viewer submits report
    client_req = make_request("/api/reports/submit")
    rep_req = main.ReportSubmitRequest(video_id="vid_001", video_title="Film 1", issue_type="Ses Yok", message="Ses gelmiyor")
    res_submit = main.submit_issue_report(rep_req, client_req)
    assert res_submit["success"] is True
    rep_id = res_submit["report_id"]

    # 2. Admin lists reports
    reports_data = main.get_admin_reports(admin_req)
    assert any(r["id"] == rep_id for r in reports_data["reports"])

    # 3. Admin resolves report
    res_resolve = main.resolve_admin_report(rep_id, admin_req)
    assert res_resolve["success"] is True

    # 4. Verified not in unresolved reports
    reports_after = main.get_admin_reports(admin_req, unresolved_only=True)
    assert not any(r["id"] == rep_id for r in reports_after["reports"])


def test_admin_access_logs_flow(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    admin_req = make_request("/api/access/admin/logs", cookies={"hf_admin_session": token})

    # 1. Clear any prior logs
    main.clear_admin_access_logs(admin_req)

    # 2. Issue code with Discord user ID & IP
    code = access_store.issue_code("discord_user_999", ip_address="198.51.100.5", note="Discord test")
    assert code is not None

    # 3. Redeem code with device ID & client IP
    redeemed = access_store.redeem_code(code, "device_mobile_1", "198.51.100.42")
    assert redeemed is not None

    # 4. Admin inspects logs
    logs_resp = main.get_admin_logs(admin_req) if hasattr(main, "get_admin_logs") else main.get_admin_access_logs(admin_req)
    logs = logs_resp["logs"]
    assert len(logs) >= 2

    # Check redeemed log
    redeemed_log = next((l for l in logs if l["event_type"] == "redeemed"), None)
    assert redeemed_log is not None
    assert redeemed_log["discord_user_id"] == "discord_user_999"
    assert redeemed_log["code"] == code
    assert redeemed_log["ip_address"] == "198.51.100.42"
    assert redeemed_log["device_id"] == "device_mobile_1"

    # Check issued log
    issued_log = next((l for l in logs if l["event_type"] == "issued"), None)
    assert issued_log is not None
    assert issued_log["discord_user_id"] == "discord_user_999"
    assert issued_log["code"] == code
    assert issued_log["ip_address"] == "198.51.100.5"

    # 5. Clear logs
    del_resp = main.clear_admin_access_logs(admin_req)
    assert del_resp["success"] is True
    assert del_resp["cleared_count"] >= 2

    empty_logs = main.get_admin_access_logs(admin_req)["logs"]
    assert len(empty_logs) == 0


def test_stream_heartbeat_concurrency_lock(access_environment):
    code = access_store.issue_code("user_stream_test")
    redemption = access_store.redeem_code(code, "dev_stream_1", "10.0.0.1")
    token = access_store.create_access_session(
        redemption["code_hash"],
        redemption["discord_user_id"],
        redemption["expires_at"],
    )

    req = make_request(
        "/api/access/stream/heartbeat",
        cookies={"hf_access_session": token},
    )

    # 1. İlk akış (Stream A) heartbeat gönderir -> 200 OK
    body_a = main.StreamHeartbeatRequest(stream_id="stream_client_A", is_new=True)
    resp_a = main.handle_stream_heartbeat(body_a, req)
    assert resp_a["status"] == "ok"

    # Stream A kalp atışını yeniler -> 200 OK
    body_a_repeat = main.StreamHeartbeatRequest(stream_id="stream_client_A", is_new=False)
    resp_a_rep = main.handle_stream_heartbeat(body_a_repeat, req)
    assert resp_a_rep["status"] == "ok"

    # 2. İkinci bir cihaz/sekme (Stream B) aynı kodla is_new=False ile izlemeye kalkarsa -> 409 Conflict
    body_b = main.StreamHeartbeatRequest(stream_id="stream_client_B", is_new=False)
    resp_b = main.handle_stream_heartbeat(body_b, req)
    assert resp_b.status_code == 409
    data_b = json.loads(resp_b.body.decode())
    assert data_b["status"] == "concurrency_limit"

    # 3. İkinci cihaz (Stream B) "Buradan Devam Et" (is_new=True) derse -> 200 OK devralır
    body_b_takeover = main.StreamHeartbeatRequest(stream_id="stream_client_B", is_new=True)
    resp_b_takeover = main.handle_stream_heartbeat(body_b_takeover, req)
    assert resp_b_takeover["status"] == "ok"

    # 4. Artık Stream A'nın sonraki kalp atışı 409 almalıdır (otomatik durdurulur)
    resp_a_conf = main.handle_stream_heartbeat(body_a_repeat, req)
    assert resp_a_conf.status_code == 409


def test_discord_interaction_btn_check_remaining_time(access_environment, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_hex = pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", pub_hex)
    ts = "1234567890"

    # 1. Kodu olmayan bir üye butona basarsa
    btn_body_empty = json.dumps({
        "type": 3,
        "data": {"custom_id": "btn_check_remaining_time"},
        "member": {"user": {"id": "no_code_user_456"}},
    }).encode("utf-8")
    sig_empty = priv.sign(ts.encode("utf-8") + btn_body_empty).hex()
    req_empty = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig_empty, "x-signature-timestamp": ts},
        body=btn_body_empty,
    )
    resp_empty = asyncio.run(main.handle_discord_interactions(req_empty))
    assert resp_empty.status_code == 200
    data_empty = json.loads(resp_empty.body.decode())
    assert "Aktif bir erişim kodunuz bulunmamaktadır" in data_empty["data"]["content"]

    # 2. Kodu olan bir üye butona basarsa
    code = access_store.issue_code("user_with_code_789")
    btn_body = json.dumps({
        "type": 3,
        "data": {"custom_id": "btn_check_remaining_time"},
        "member": {"user": {"id": "user_with_code_789"}},
    }).encode("utf-8")
    sig = priv.sign(ts.encode("utf-8") + btn_body).hex()
    req = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig, "x-signature-timestamp": ts},
        body=btn_body,
    )
    resp = asyncio.run(main.handle_discord_interactions(req))
    assert resp.status_code == 200
    data = json.loads(resp.body.decode())
    assert "HFStream Erişim Durumunuz" in data["data"]["content"]
    assert code in data["data"]["content"]


def test_discord_command_surem(access_environment, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_hex = pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", pub_hex)
    ts = "1234567890"

    code = access_store.issue_code("user_surem_123")
    cmd_body = json.dumps({
        "type": 2,
        "data": {"name": "surem"},
        "member": {"user": {"id": "user_surem_123"}},
    }).encode("utf-8")
    sig = priv.sign(ts.encode("utf-8") + cmd_body).hex()
    req = make_request(
        "/api/discord/interactions",
        extra_headers={"x-signature-ed25519": sig, "x-signature-timestamp": ts},
        body=cmd_body,
    )
    resp = asyncio.run(main.handle_discord_interactions(req))
    assert resp.status_code == 200
    data = json.loads(resp.body.decode())
    assert "Aktif Kodunuz" in data["data"]["content"]
    assert code in data["data"]["content"]


def test_admin_log_webhook_settings(access_environment):
    token, _ = access_store.create_admin_session("password-admin")
    admin_req = make_request(
        "/api/access/admin/settings",
        cookies={"hf_admin_session": token},
        body=json.dumps({
            "public_video_ids": [],
            "session_hours": 36,
            "admin_log_webhook": "https://discord.com/api/webhooks/123/abc"
        }).encode("utf-8")
    )
    resp = asyncio.run(main.update_admin_access_settings(admin_req))
    assert resp["session_hours"] == 36
    assert resp["admin_log_webhook"] == "https://discord.com/api/webhooks/123/abc"

    settings = access_store.get_settings()
    assert settings["admin_log_webhook"] == "https://discord.com/api/webhooks/123/abc"


def test_access_me_and_login_returns_active_code(access_environment):
    code = access_store.issue_code("user_test_me_code")
    req = make_request(
        "/api/access/login",
        cookies={"hf_device_id": "device-test-123"},
        body=json.dumps({"code": code}).encode("utf-8")
    )
    resp = asyncio.run(main.login_with_access_code(req))
    assert resp.status_code == 200
    data = json.loads(resp.body.decode())
    assert data["authenticated"] is True
    assert data["code"] == code

    cookie = SimpleCookie()
    cookie.load(resp.headers["set-cookie"])
    token = cookie["hf_access_session"].value
    assert token

    me_req = make_request(
        "/api/access/me",
        cookies={"hf_access_session": token, "hf_device_id": "device-test-123"}
    )
    me_resp = main.access_identity(me_req)
    me_data = json.loads(me_resp.body.decode())
    assert me_data["authenticated"] is True
    assert me_data["code"] == code
    assert me_data["expires_at"] > int(time.time())

    logout_req = make_request(
        "/api/access/logout",
        cookies={"hf_access_session": token}
    )
    logout_resp = main.logout_access(logout_req)
    assert logout_resp.status_code == 200
    logout_data = json.loads(logout_resp.body.decode())
    assert logout_data["authenticated"] is False

    me_after_req = make_request(
        "/api/access/me",
        cookies={"hf_access_session": token, "hf_device_id": "device-test-123"}
    )
    me_after_resp = main.access_identity(me_after_req)
    me_after_data = json.loads(me_after_resp.body.decode())
    assert me_after_data["authenticated"] is False
    assert me_after_data["code"] is None


def test_app_ads_txt_endpoint_returns_correct_iab_snippet():
    resp = main.serve_app_ads_txt()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    content = resp.body.decode("utf-8")
    assert "google.com, pub-3366068343218156, DIRECT, f08c47fec0942fa0" in content

    # Test via TestClient for GET and HEAD
    client = TestClient(main.app)
    head_resp = client.head("/app-ads.txt")
    assert head_resp.status_code == 200
    assert head_resp.headers["content-type"].startswith("text/plain")


def test_robots_txt_allows_app_ads_txt():
    resp = main.serve_robots_txt()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    content = resp.body.decode("utf-8")
    assert "Allow: /app-ads.txt" in content

    client = TestClient(main.app)
    head_resp = client.head("/robots.txt")
    assert head_resp.status_code == 200
    assert head_resp.headers["content-type"].startswith("text/plain")


def test_watermark_asset_exists_and_is_valid():
    from pathlib import Path
    from app.config import BASE_DIR
    watermark_file = BASE_DIR / "assets" / "watermark.png"
    if not watermark_file.exists():
        watermark_file = BASE_DIR / "app" / "assets" / "watermark.png"
    assert watermark_file.exists(), "Watermark asset file must exist"
    assert watermark_file.stat().st_size > 0, "Watermark file must not be empty"
    with open(watermark_file, "rb") as f:
        header = f.read(24)
    # Valid PNG magic number
    assert header.startswith(b"\x89PNG\r\n\x1a\n")


def test_download_safetensors_video_options_and_head():
    options_req = make_request("/api/download/video_0000")
    options_req.scope["method"] = "OPTIONS"
    resp = asyncio.run(main.download_safetensors_video(tensor_name="video_0000", request=options_req))
    assert resp.status_code == 204
    assert resp.headers["access-control-allow-origin"] == "*"

    head_req = make_request("/api/download/video_0000")
    head_req.scope["method"] = "HEAD"
    resp_head = asyncio.run(main.download_safetensors_video(tensor_name="video_0000", title="Test Movie", request=head_req))
    assert resp_head.status_code == 200
    assert "attachment" in resp_head.headers.get("content-disposition", "")
    assert "Test Movie.mp4" in resp_head.headers.get("content-disposition", "")


def test_download_access_video_delegates_to_download_safetensors(monkeypatch):
    called = {}
    async def fake_download(**kwargs):
        called.update(kwargs)
        return Response(content=b"ok", media_type="video/mp4", headers={"Content-Disposition": 'attachment; filename="dl.mp4"'})

    monkeypatch.setattr(main, "download_safetensors_video", fake_download)
    req = make_request("/api/access/download/video_0000")
    resp = asyncio.run(main.download_access_video(tensor_name="video_0000", source_file="test.safetensors", title="My Title", request=req))
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="dl.mp4"'
    assert called.get("tensor_name") == "video_0000"
    assert called.get("source_file") == "test.safetensors"
    assert called.get("title") == "My Title"


def test_google_site_verification_route():
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    resp = client.get("/googlef4087a9e005524eb.html")
    assert resp.status_code == 200
    assert resp.text.strip() == "google-site-verification: googlef4087a9e005524eb.html"

    resp_eshanio = client.get("/eshanio/googlef4087a9e005524eb.html")
    assert resp_eshanio.status_code == 200
    assert resp_eshanio.text.strip() == "google-site-verification: googlef4087a9e005524eb.html"


def test_sitemap_and_video_sitemap_routes():
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    for path in (
        "/sitemap.xml",
        "/video-sitemap.xml",
        "/eshanio/sitemap.xml",
        "/eshanio/video-sitemap.xml",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"Failed for {path}: {resp.status_code}"
        assert "xml" in resp.headers.get("content-type", "").lower()
        assert "<urlset" in resp.text



