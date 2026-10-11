import pytest
from fastapi.testclient import TestClient
from app import main, access_store

DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
APP_TOKEN = "eshanio-app-secret-2026"


@pytest.fixture
def auth_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HFSTREAM_ACCESS_DB", str(tmp_path / "access.sqlite3"))
    monkeypatch.setenv("HFSTREAM_AUTH_SECRET", "test-auth-secret-12345")
    monkeypatch.setenv("APP_ACCESS_TOKEN", APP_TOKEN)
    access_store.initialize()
    return None


def test_turkey_mobile_web_allowed(auth_environment):
    """[PASS] Turkey + Mobile Web (§1, §14 dost.md)"""
    client = TestClient(main.app)
    resp = client.get("/eshanio/", headers={"User-Agent": MOBILE_UA, "cf-ipcountry": "TR"})
    assert resp.status_code == 200


def test_turkey_mobile_app_allowed(auth_environment, monkeypatch):
    """[PASS] Turkey + Mobile App (§4, §14 dost.md)"""
    client = TestClient(main.app)
    # Dev login
    login_resp = client.post(
        "/api/auth/dev-login",
        json={"email": "tr_app@example.com", "name": "TR App User"},
        headers={"User-Agent": MOBILE_UA, "cf-ipcountry": "TR", "x-app-token": APP_TOKEN},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["session_token"]

    # Video listesi tam erişilebilir
    resp = client.get(
        "/api/access/videos",
        headers={
            "User-Agent": MOBILE_UA,
            "cf-ipcountry": "TR",
            "x-app-token": APP_TOKEN,
            "Authorization": f"Bearer {token}",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["total"] > 0


def test_turkey_desktop_blocked(auth_environment):
    """[PASS] Turkey + Desktop Block (§1, §2 dost.md)"""
    client = TestClient(main.app)
    # Masaüstü tarayıcı ile web sitesi tamamen gizli (404)
    resp = client.get("/eshanio/", headers={"User-Agent": DESKTOP_UA, "cf-ipcountry": "TR"})
    assert resp.status_code == 404

    # Masaüstü doğrudan video endpointi gizli (404)
    resp_video = client.get("/video/video_0000", headers={"User-Agent": DESKTOP_UA, "cf-ipcountry": "TR"})
    assert resp_video.status_code == 404


def test_foreign_desktop_blocked(auth_environment):
    """[PASS] Foreign + Desktop Block (§1, §3 dost.md)"""
    client = TestClient(main.app)
    resp = client.get("/eshanio/", headers={"User-Agent": DESKTOP_UA, "cf-ipcountry": "DE"})
    assert resp.status_code == 404


def test_foreign_mobile_web_blocked(auth_environment):
    """[PASS] Foreign + Mobile Web Block (§1, §3, §14 dost.md)"""
    client = TestClient(main.app)
    resp = client.get("/eshanio/", headers={"User-Agent": MOBILE_UA, "cf-ipcountry": "DE"})
    assert resp.status_code == 404


def test_foreign_mobile_app_login_allowed_and_content_hidden(auth_environment):
    """
    [PASS] Foreign + Mobile App Login Allowed
    [PASS] Foreign + Mobile App Movies Hidden
    [PASS] Foreign + Mobile App Series Hidden
    [PASS] Foreign + Mobile App Search Hidden
    [PASS] Foreign + Mobile App Playback Blocked
    (§4, §5, §6, §7 dost.md)
    """
    client = TestClient(main.app)
    headers = {
        "User-Agent": MOBILE_UA,
        "cf-ipcountry": "DE",
        "x-app-token": APP_TOKEN,
    }

    # 1. Foreign + Mobile App Login Allowed
    login_resp = client.post(
        "/api/auth/dev-login",
        json={"email": "de_app@example.com", "name": "Hans Muller"},
        headers=headers,
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["authenticated"] is True
    session_token = login_resp.json()["session_token"]
    auth_headers = {**headers, "Authorization": f"Bearer {session_token}"}

    # Profil kullanılabilir
    me_resp = client.get("/api/auth/me", headers=auth_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is True

    # 2. Foreign + Mobile App Movies Hidden (/api/access/videos)
    movies_resp = client.get("/api/access/videos", headers=auth_headers)
    assert movies_resp.status_code == 200
    assert movies_resp.json()["videos"] == []
    assert movies_resp.json()["total"] == 0

    # 3. Foreign + Mobile App Series Hidden (/api/series/videos & /api/catalog)
    series_resp = client.get("/api/series/videos", headers=auth_headers)
    assert series_resp.status_code == 200
    assert series_resp.json()["videos"] == []
    assert series_resp.json()["total"] == 0

    # 4. Foreign + Mobile App Search Hidden
    search_resp = client.get("/api/catalog?search=batman", headers=auth_headers)
    assert search_resp.status_code == 200
    assert search_resp.json()["videos"] == []
    assert search_resp.json()["total"] == 0

    # 5. Foreign + Mobile App Playback Blocked (403 Forbidden / allowed: false)
    play_resp = client.get("/api/access/stream/video_0000", headers=auth_headers)
    assert play_resp.status_code == 403


def test_direct_api_and_video_url_protected(auth_environment):
    """
    [PASS] Direct API Request Blocked
    [PASS] Direct Video URL Protected
    (§8 dost.md)
    """
    client = TestClient(main.app)
    # Masaüstünden doğrudan video API veya akış isteği 404 / engelli
    resp = client.get("/video/video_0000", headers={"User-Agent": DESKTOP_UA, "cf-ipcountry": "TR"})
    assert resp.status_code == 404

    resp_stream = client.get("/api/stream/video_0000", headers={"User-Agent": DESKTOP_UA, "cf-ipcountry": "TR"})
    assert resp_stream.status_code == 404


def test_user_agent_manipulation_blocked(auth_environment):
    """[PASS] Desktop User-Agent Manipulation Tested (§2 dost.md)"""
    client = TestClient(main.app)
    # Sec-CH-UA-Mobile ?0 gönderen manipüle edilmiş istek
    resp = client.get(
        "/eshanio/",
        headers={
            "User-Agent": MOBILE_UA,
            "Sec-CH-UA-Mobile": "?0",
            "cf-ipcountry": "TR",
        },
    )
    assert resp.status_code == 404


def test_anonymizer_and_vpn_blocked(auth_environment):
    """[PASS] GeoIP / Anonymizer Bypass Tested (§10 dost.md)"""
    client = TestClient(main.app)
    # Via proxy header taşıyan istekler engellenir (404)
    resp = client.get(
        "/eshanio/",
        headers={
            "User-Agent": MOBILE_UA,
            "cf-ipcountry": "TR",
            "Via": "1.1 anonymizer-proxy.net",
        },
    )
    assert resp.status_code == 404


def test_cache_leakage_prevented(auth_environment):
    """[PASS] Cache Leakage Tested (§11 dost.md)"""
    client = TestClient(main.app)
    resp = client.get(
        "/api/auth/me",
        headers={"User-Agent": MOBILE_UA, "cf-ipcountry": "TR"},
    )
    assert resp.status_code == 200
    cache_control = resp.headers.get("cache-control", "").lower()
    assert "no-store" in cache_control
    assert "private" in cache_control
