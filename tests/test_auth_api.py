import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app import access_store, main


@pytest.fixture
def auth_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HFSTREAM_ACCESS_DB", str(tmp_path / "access.sqlite3"))
    monkeypatch.setenv("HFSTREAM_AUTH_SECRET", "test-auth-secret-12345")
    access_store.initialize()
    return None


def test_auth_me_unauthenticated(auth_environment):
    client = TestClient(main.app)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False
    assert data["user"] is None


def test_dev_login_and_logout(auth_environment):
    client = TestClient(main.app)
    resp = client.post("/api/auth/dev-login", json={"email": "eshan@example.com", "name": "Eshan Sayhan"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True
    assert data["user"]["email"] == "eshan@example.com"
    assert data["user"]["name"] == "Eshan Sayhan"
    assert "hf_user_session" in resp.cookies
    assert "hf_access_session" in resp.cookies

    # Check /api/auth/me retains session via cookie
    me_resp = client.get("/api/auth/me", cookies=resp.cookies)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["authenticated"] is True
    assert me_data["user"]["email"] == "eshan@example.com"

    # Logout
    logout_resp = client.post("/api/auth/logout", cookies=resp.cookies)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["authenticated"] is False

    # Check /api/auth/me is unauthenticated after logout
    after_resp = client.get("/api/auth/me", cookies=logout_resp.cookies)
    assert after_resp.json()["authenticated"] is False


def test_google_login_success(auth_environment):
    client = TestClient(main.app)

    mock_google_response = {
        "iss": "https://accounts.google.com",
        "sub": "google-1234567890",
        "email": "testuser@gmail.com",
        "email_verified": "true",
        "name": "Test Google User",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://lh3.googleusercontent.com/a/test-pic",
        "exp": int(time.time()) + 3600,
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_google_response
        mock_get.return_value = mock_resp

        resp = client.post("/api/auth/google", json={"credential": "valid-sample-jwt-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["email"] == "testuser@gmail.com"
        assert data["user"]["google_id"] == "google-1234567890"
        assert "hf_user_session" in resp.cookies


def test_google_login_invalid_token(auth_environment):
    client = TestClient(main.app)

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Invalid Value"
        mock_get.return_value = mock_resp

        resp = client.post("/api/auth/google", json={"credential": "invalid-token-123"})
        assert resp.status_code == 401


def test_google_login_access_token_success(auth_environment):
    client = TestClient(main.app)

    mock_userinfo = {
        "sub": "google-token-456",
        "email": "tokenuser@gmail.com",
        "name": "Token User",
        "picture": "https://lh3.googleusercontent.com/a/token-user",
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_userinfo
        mock_get.return_value = mock_resp

        resp = client.post("/api/auth/google", json={"access_token": "ya29.sample-access-token"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
        assert resp.json()["user"]["email"] == "tokenuser@gmail.com"



def test_google_redirect_callback_success(auth_environment):
    client = TestClient(main.app)

    mock_google_response = {
        "iss": "https://accounts.google.com",
        "sub": "google-redirect-9999",
        "email": "redirectuser@gmail.com",
        "email_verified": "true",
        "name": "Redirect Google User",
        "given_name": "Redirect",
        "family_name": "User",
        "picture": "https://lh3.googleusercontent.com/a/redirect-pic",
        "exp": int(time.time()) + 3600,
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_google_response
        mock_get.return_value = mock_resp

        # Form data submission like Google does in redirect mode
        resp = client.post(
            "/api/auth/google/callback",
            data={"credential": "sample-valid-credential-token"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert "hf_user_session" in resp.cookies
        assert "hf_access_session" in resp.cookies


def test_coop_header_present(auth_environment):
    client = TestClient(main.app)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.headers.get("cross-origin-opener-policy") == "same-origin-allow-popups"


def test_google_popup_callback_success(auth_environment):
    client = TestClient(main.app)

    mock_google_response = {
        "iss": "https://accounts.google.com",
        "sub": "google-popup-777",
        "email": "popupuser@gmail.com",
        "email_verified": "true",
        "name": "Popup Google User",
        "exp": int(time.time()) + 3600,
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_google_response
        mock_get.return_value = mock_resp

        # Form post with state='popup_123'
        resp = client.post(
            "/api/auth/google/callback",
            data={"credential": "sample-valid-popup-token", "state": "popup_abc123"},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "GOOGLE_AUTH_SUCCESS" in resp.text
        assert "popupuser@gmail.com" in resp.text
        assert "hf_user_session" in resp.cookies


def test_google_callback_get_hash_extractor(auth_environment):
    client = TestClient(main.app)
    # GET without credential should serve extractor HTML
    resp = client.get("/api/auth/google/callback?state=popup_xyz")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "window.location.hash" in resp.text


def test_user_engagement_features(auth_environment):
    client = TestClient(main.app)
    # Authenticate via dev login
    login_resp = client.post("/api/auth/dev-login", json={"email": "member@example.com", "name": "Member User"})
    assert login_resp.status_code == 200
    session_cookie = login_resp.cookies.get("hf_user_session")
    assert session_cookie
    client.cookies.set("hf_user_session", session_cookie)

    # 1. Video Progress
    prog_resp = client.post("/api/user/progress", json={
        "video_id": "vid-101",
        "position_sec": 125.5,
        "duration_sec": 300.0,
    })
    assert prog_resp.status_code == 200
    assert prog_resp.json().get("status") == "ok"

    get_prog = client.get("/api/user/progress/vid-101")
    assert get_prog.status_code == 200
    progress_item = get_prog.json().get("progress")
    assert progress_item is not None
    assert progress_item.get("position_sec") == 125.5

    all_prog = client.get("/api/user/progress")
    assert all_prog.status_code == 200
    assert len(all_prog.json().get("progress", [])) == 1

    # 2. Favorites
    fav_toggle = client.post("/api/user/favorites/toggle", json={
        "video_id": "vid-101",
        "video_title": "Episode 1",
        "cover_url": "https://example.com/poster.jpg"
    })
    assert fav_toggle.status_code == 200
    assert fav_toggle.json().get("is_favorite") is True

    fav_list = client.get("/api/user/favorites")
    assert fav_list.status_code == 200
    assert len(fav_list.json().get("favorites", [])) == 1

    # 3. Watch History
    hist_post = client.post("/api/user/history", json={
        "video_id": "vid-101",
        "video_title": "Episode 1",
        "cover_url": "https://example.com/poster.jpg"
    })
    assert hist_post.status_code == 200
    hist_list = client.get("/api/user/history")
    assert hist_list.status_code == 200
    assert len(hist_list.json().get("history", [])) == 1

    # 4. Comments & Ratings
    comment_post = client.post("/api/video/vid-101/comments", json={
        "comment": "Harika bir film, cok begendim!",
        "rating": 9
    })
    assert comment_post.status_code == 200
    assert comment_post.json().get("status") == "ok"

    comments_get = client.get("/api/video/vid-101/comments")
    assert comments_get.status_code == 200
    comments = comments_get.json().get("comments", [])
    assert len(comments) == 1
    assert comments[0]["comment"] == "Harika bir film, cok begendim!"
    assert comments[0]["rating"] == 9
    assert comments[0]["user_name"] == "Member User"


def test_pwa_routes(auth_environment):
    client = TestClient(main.app)
    resp_m = client.get("/manifest.json")
    assert resp_m.status_code == 200
    assert resp_m.json()["display"] == "standalone"

    resp_sw = client.get("/sw.js")
    assert resp_sw.status_code == 200
    assert "Service-Worker-Allowed" in resp_sw.headers


def test_google_user_can_access_videos(auth_environment, monkeypatch):
    client = TestClient(main.app)

    # 1. Giriş yapılmadığında içerikler gizli (0 video)
    unauth_resp = client.get("/api/access/videos")
    assert unauth_resp.status_code == 200
    data = unauth_resp.json()
    assert data["total"] == 0
    assert data["videos"] == []

    # 2. Mock video listesi
    sample_videos = [
        {"id": "movie.safetensors::video_0000", "title": "Test Filmi", "category": "Film"},
        {"id": "series.safetensors::video_0001", "title": "Test Dizisi", "category": "Dizi"},
    ]
    async def fake_list_videos(request, search="", season=0):
        return {"videos": sample_videos, "total": len(sample_videos)}
    monkeypatch.setattr(main, "list_all_video_apis", fake_list_videos)

    # 3. Google / Dev hesabı ile giriş yap
    login_resp = client.post("/api/auth/dev-login", json={"email": "googleuser@gmail.com", "name": "Google Kullanıcısı"})
    assert login_resp.status_code == 200
    session_cookie = login_resp.cookies.get("hf_user_session")
    session_token = login_resp.json().get("session_token")
    assert session_cookie or session_token

    # 4. Giriş yapıldığında videolar görünür
    client.cookies.set("hf_user_session", session_cookie or session_token)
    auth_resp = client.get("/api/access/videos", headers={"Authorization": f"Bearer {session_token or session_cookie}"})
    assert auth_resp.status_code == 200
    auth_data = auth_resp.json()
    assert auth_data["total"] == 2
    assert len(auth_data["videos"]) == 2
    assert auth_data["videos"][0]["title"] == "Test Filmi"


def test_desktop_login_blocked_and_mobile_allowed(auth_environment):
    client = TestClient(main.app)

    desktop_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

    # 1. Masaüstü UA ile dev-login engellenmeli (403 Forbidden)
    d_resp = client.post(
        "/api/auth/dev-login",
        json={"email": "desktop@example.com", "name": "Desktop User"},
        headers={"User-Agent": desktop_ua},
    )
    assert d_resp.status_code == 403
    assert "mobil" in d_resp.json()["detail"].lower()

    # 2. Masaüstü UA ile 14 haneli kod login engellenmeli (403 Forbidden)
    d_code_resp = client.post(
        "/api/access/login",
        json={"code": "12345678901234"},
        headers={"User-Agent": desktop_ua},
    )
    assert d_code_resp.status_code == 403
    assert "mobil" in d_code_resp.json()["detail"].lower()

    # 3. Mobil iPhone UA ile giriş başarılı olmalı (200 OK)
    m_resp = client.post(
        "/api/auth/dev-login",
        json={"email": "mobile@example.com", "name": "Mobile User"},
        headers={"User-Agent": mobile_ua},
    )
    assert m_resp.status_code == 200
    assert m_resp.json()["authenticated"] is True
    session_token = m_resp.json().get("session_token")

    # 4. Sec-CH-UA-Mobile Client Hint ile giriş başarılı olmalı
    hint_resp = client.post(
        "/api/auth/dev-login",
        json={"email": "hint@example.com", "name": "Hint User"},
        headers={"Sec-CH-UA-Mobile": "?1"},
    )
    assert hint_resp.status_code == 200
    assert hint_resp.json()["authenticated"] is True

    # 5. Masaüstü tarayıcı ile oturum token'ı gönderilse bile video erişimi engellenmeli
    d_video_resp = client.get(
        "/api/access/videos",
        headers={"User-Agent": desktop_ua, "Authorization": f"Bearer {session_token}"},
    )
    assert d_video_resp.status_code == 200
    assert d_video_resp.json()["videos"] == []
    assert d_video_resp.json()["total"] == 0


def test_user_profile_system(auth_environment):
    client = TestClient(main.app)
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"

    # 1. Giriş yap
    login_resp = client.post(
        "/api/auth/dev-login",
        json={"email": "eshan@example.com", "name": "Eshan Sayhan"},
        headers={"User-Agent": mobile_ua},
    )
    assert login_resp.status_code == 200
    session_cookie = login_resp.cookies.get("hf_user_session")
    cookies = {"hf_user_session": session_cookie}

    # 2. Otomatik profil ve kullanıcı adı kontrolü
    me_resp = client.get("/api/auth/me", cookies=cookies, headers={"User-Agent": mobile_ua})
    assert me_resp.status_code == 200
    me_user = me_resp.json()["user"]
    assert me_user["username"] == "eshan"

    # 3. Profil detaylarını çek
    prof_resp = client.get("/api/user/profile", cookies=cookies, headers={"User-Agent": mobile_ua})
    assert prof_resp.status_code == 200
    prof = prof_resp.json()["profile"]
    assert prof["username"] == "eshan"
    assert "favorites_count" in prof
    assert "history_count" in prof

    # 4. Profili güncelle (Takma ad, doğum tarihi, yaş oto-hesap, biyografi, cinsiyet, telefon)
    update_payload = {
        "name": "Eshan Pro",
        "username": "eshan",  # Kalıcı kullanıcı adı
        "birth_date": "2000-01-01",
        "gender": "erkek",
        "bio": "Film ve teknoloji meraklısı",
        "phone": "+905550000000",
        "phone_verified": True,
    }
    up_resp = client.post("/api/user/profile", json=update_payload, cookies=cookies, headers={"User-Agent": mobile_ua})
    assert up_resp.status_code == 200
    up_prof = up_resp.json()["profile"]
    assert up_prof["username"] == "eshan"
    assert up_prof["name"] == "Eshan Pro"
    assert up_prof["birth_date"] == "2000-01-01"
    assert up_prof["age"] is not None
    assert up_prof["age"] >= 24  # Otomatik hesaplanan yaş
    assert up_prof["gender"] == "erkek"
    assert up_prof["bio"] == "Film ve teknoloji meraklısı"
    assert up_prof["phone"] == "+905550000000"
    assert up_prof["phone_verified"] == 1

    # 5. Kullanıcı adını değiştirmeye çalışma (Kalıcı olduğu için 400 döner)
    change_uname_resp = client.post("/api/user/profile", json={"username": "baska_biri"}, cookies=cookies, headers={"User-Agent": mobile_ua})
    assert change_uname_resp.status_code == 400
    assert "değiştirilemez" in change_uname_resp.json()["detail"].lower()

    # 6. Takma ad boş bırakılamaz kontrolü
    bad_name_resp = client.post("/api/user/profile", json={"name": "   "}, cookies=cookies, headers={"User-Agent": mobile_ua})
    assert bad_name_resp.status_code == 400
    assert "takma ad" in bad_name_resp.json()["detail"].lower()


def test_video_comment_likes_and_ranking_and_deletion(auth_environment):
    client = TestClient(main.app)
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"

    # 1. İki kullanıcı oluştur
    u1_resp = client.post("/api/auth/dev-login", json={"email": "u1@example.com", "name": "User One"}, headers={"User-Agent": mobile_ua})
    c1 = {"hf_user_session": u1_resp.cookies.get("hf_user_session")}
    
    u2_resp = client.post("/api/auth/dev-login", json={"email": "u2@example.com", "name": "User Two"}, headers={"User-Agent": mobile_ua})
    c2 = {"hf_user_session": u2_resp.cookies.get("hf_user_session")}

    video_id = "film-test-101"

    # 2. U1 ilk yorumu atar (Düşük kalp alacak)
    p1 = client.post(
        f"/api/video/{video_id}/comments",
        json={"comment": "İlk yorum, normal.", "rating": 7},
        cookies=c1,
        headers={"User-Agent": mobile_ua},
    )
    assert p1.status_code == 200
    comm1_id = p1.json()["comment"]["id"]

    # 3. U2 ikinci yorumu atar (Çok kalp alacak)
    p2 = client.post(
        f"/api/video/{video_id}/comments",
        json={"comment": "Efsane film, 05:20 sahnesine dikkat!", "rating": 10},
        cookies=c2,
        headers={"User-Agent": mobile_ua},
    )
    assert p2.status_code == 200
    comm2_id = p2.json()["comment"]["id"]

    # 4. Yorum 2'ye U1 ve U2 kalp bırakır
    like1 = client.post(f"/api/video/comments/{comm2_id}/like", cookies=c1, headers={"User-Agent": mobile_ua})
    assert like1.status_code == 200
    assert like1.json()["liked"] is True
    assert like1.json()["likes_count"] == 1

    like2 = client.post(f"/api/video/comments/{comm2_id}/like", cookies=c2, headers={"User-Agent": mobile_ua})
    assert like2.status_code == 200
    assert like2.json()["liked"] is True
    assert like2.json()["likes_count"] == 2

    # 5. Sıralama kontrolü: Popüler sırada en çok kalp alan (comm2) en üstte olmalı
    pop_resp = client.get(f"/api/video/{video_id}/comments?sort=popular", cookies=c1, headers={"User-Agent": mobile_ua})
    assert pop_resp.status_code == 200
    pop_comments = pop_resp.json()["comments"]
    assert len(pop_comments) == 2
    assert pop_comments[0]["id"] == comm2_id
    assert pop_comments[0]["likes_count"] == 2
    assert pop_comments[0]["is_liked"] == 1
    assert pop_comments[1]["id"] == comm1_id
    assert pop_comments[1]["likes_count"] == 0

    # 6. Yorum silme: U1 başkasının (U2'nin) yorumunu silmeye çalışınca 403 almalı
    del_forbidden = client.delete(f"/api/video/comments/{comm2_id}", cookies=c1, headers={"User-Agent": mobile_ua})
    assert del_forbidden.status_code == 403

    # 7. U1 kendi yorumunu (comm1) silebilmeli
    del_own = client.delete(f"/api/video/comments/{comm1_id}", cookies=c1, headers={"User-Agent": mobile_ua})
    assert del_own.status_code == 200
    assert del_own.json()["deleted"] is True

    # 8. Listede sadece comm2 kalmalı
    after_del = client.get(f"/api/video/{video_id}/comments", headers={"User-Agent": mobile_ua})
    assert len(after_del.json()["comments"]) == 1
    assert after_del.json()["comments"][0]["id"] == comm2_id


def test_public_profile_and_social_interactions(auth_environment):
    client = TestClient(main.app)
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"

    # 1. İki kullanıcı oluştur
    u1_resp = client.post("/api/auth/dev-login", json={"email": "alice@example.com", "name": "Alice Wonderland"}, headers={"User-Agent": mobile_ua})
    c1 = {"hf_user_session": u1_resp.cookies.get("hf_user_session")}
    alice_username = u1_resp.json()["user"]["username"]

    u2_resp = client.post("/api/auth/dev-login", json={"email": "bob@example.com", "name": "Bob Builder"}, headers={"User-Agent": mobile_ua})
    c2 = {"hf_user_session": u2_resp.cookies.get("hf_user_session")}
    bob_username = u2_resp.json()["user"]["username"]

    # 2. Bob, Alice'in profilini herkese açık olarak sorgular
    prof_resp = client.get(f"/api/user/public/{alice_username}", cookies=c2, headers={"User-Agent": mobile_ua})
    assert prof_resp.status_code == 200
    alice_prof = prof_resp.json()["profile"]
    assert alice_prof["username"] == alice_username
    assert alice_prof["name"] == "Alice Wonderland"
    assert "email" not in alice_prof  # Güvenlik: email sızdırılmamalı
    assert alice_prof["is_following"] is False
    assert alice_prof["is_friend"] is False
    assert alice_prof["followers_count"] == 0

    # 3. Bob, Alice'i takip eder
    follow_resp = client.post(f"/api/user/public/{alice_username}/follow", cookies=c2, headers={"User-Agent": mobile_ua})
    assert follow_resp.status_code == 200
    assert follow_resp.json()["following"] is True
    assert follow_resp.json()["followers_count"] == 1

    # Takip durumu profile yansımalı
    prof2 = client.get(f"/api/user/public/{alice_username}", cookies=c2, headers={"User-Agent": mobile_ua}).json()["profile"]
    assert prof2["is_following"] is True
    assert prof2["followers_count"] == 1

    # 4. Bob, Alice'i arkadaş olarak ekler
    friend_resp = client.post(f"/api/user/public/{alice_username}/friend", cookies=c2, headers={"User-Agent": mobile_ua})
    assert friend_resp.status_code == 200
    assert friend_resp.json()["is_friend"] is True
    assert friend_resp.json()["friends_count"] == 1

    # 5. Kendini takip etme engeli (400)
    self_follow = client.post(f"/api/user/public/{alice_username}/follow", cookies=c1, headers={"User-Agent": mobile_ua})
    assert self_follow.status_code == 400


def test_direct_messaging_system(auth_environment):
    client = TestClient(main.app)
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"

    # 1. İki kullanıcı oluştur
    u1_resp = client.post("/api/auth/dev-login", json={"email": "c1@example.com", "name": "Chatter One"}, headers={"User-Agent": mobile_ua})
    c1 = {"hf_user_session": u1_resp.cookies.get("hf_user_session")}
    u1_uname = u1_resp.json()["user"]["username"]

    u2_resp = client.post("/api/auth/dev-login", json={"email": "c2@example.com", "name": "Chatter Two"}, headers={"User-Agent": mobile_ua})
    c2 = {"hf_user_session": u2_resp.cookies.get("hf_user_session")}
    u2_uname = u2_resp.json()["user"]["username"]

    # 2. C1 -> C2 mesaj gönderir
    send1 = client.post(
        f"/api/messages/{u2_uname}",
        json={"message": "Selam, filmi izledin mi?"},
        cookies=c1,
        headers={"User-Agent": mobile_ua},
    )
    assert send1.status_code == 200
    assert send1.json()["message"]["message"] == "Selam, filmi izledin mi?"

    # 3. C2 konuşmaları listeler
    conv_resp = client.get("/api/messages/conversations", cookies=c2, headers={"User-Agent": mobile_ua})
    assert conv_resp.status_code == 200
    convs = conv_resp.json()["conversations"]
    assert len(convs) == 1
    assert convs[0]["partner"]["username"] == u1_uname
    assert convs[0]["unread_count"] == 1

    # 4. C2 mesaj geçmişini açar (mesajlar okunur)
    chat_resp = client.get(f"/api/messages/{u1_uname}", cookies=c2, headers={"User-Agent": mobile_ua})
    assert chat_resp.status_code == 200
    messages = chat_resp.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["message"] == "Selam, filmi izledin mi?"

    # 5. C2 cevap verir
    send2 = client.post(
        f"/api/messages/{u1_uname}",
        json={"message": "Evet, kesinlikle harikaydı!"},
        cookies=c2,
        headers={"User-Agent": mobile_ua},
    )
    assert send2.status_code == 200

    # 6. Toplam 2 mesaj olmalı
    chat_resp2 = client.get(f"/api/messages/{u2_uname}", cookies=c1, headers={"User-Agent": mobile_ua})
    assert len(chat_resp2.json()["messages"]) == 2


def test_follow_back_and_comment_video_title(auth_environment):
    client = TestClient(main.app)
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"

    # 1. Kullanıcı A ve Kullanıcı B
    res_a = client.post("/api/auth/dev-login", json={"email": "usera@example.com", "name": "User Alpha"}, headers={"User-Agent": mobile_ua})
    c_a = {"hf_user_session": res_a.cookies.get("hf_user_session")}
    uname_a = res_a.json()["user"]["username"]

    res_b = client.post("/api/auth/dev-login", json={"email": "userb@example.com", "name": "User Beta"}, headers={"User-Agent": mobile_ua})
    c_b = {"hf_user_session": res_b.cookies.get("hf_user_session")}
    uname_b = res_b.json()["user"]["username"]

    # 2. User A bir filme video_title ile yorum bırakır
    comm_post = client.post(
        "/api/video/movie-matrix/comments",
        json={"comment": "Efsane bilim kurgu!", "rating": 10, "video_title": "The Matrix (1999)"},
        cookies=c_a,
        headers={"User-Agent": mobile_ua},
    )
    assert comm_post.status_code == 200

    # 3. User B, User A'nın profilini açar
    prof_resp = client.get(f"/api/user/public/{uname_a}", cookies=c_b, headers={"User-Agent": mobile_ua})
    assert prof_resp.status_code == 200
    prof = prof_resp.json()["profile"]
    assert len(prof["recent_comments"]) == 1
    assert prof["recent_comments"][0]["video_title"] == "The Matrix (1999)"
    assert prof["recent_comments"][0]["video_id"] == "movie-matrix"
    assert prof["is_following"] is False
    assert prof["follows_you"] is False
    assert prof["is_mutual"] is False

    # 4. User A, User B'yi takip eder
    follow_a_to_b = client.post(f"/api/user/public/{uname_b}/follow", cookies=c_a, headers={"User-Agent": mobile_ua})
    assert follow_a_to_b.status_code == 200

    # 5. User B artık User A'nın kendisini takip ettiğini görür (Geri Takip fırsatı)
    prof_resp2 = client.get(f"/api/user/public/{uname_a}", cookies=c_b, headers={"User-Agent": mobile_ua})
    prof2 = prof_resp2.json()["profile"]
    assert prof2["is_following"] is False
    assert prof2["follows_you"] is True
    assert prof2["is_mutual"] is False

    # 6. User B geri takip eder
    follow_b_to_a = client.post(f"/api/user/public/{uname_a}/follow", cookies=c_b, headers={"User-Agent": mobile_ua})
    assert follow_b_to_a.status_code == 200
    b_data = follow_b_to_a.json()
    assert b_data["following"] is True
    assert b_data["follows_you"] is True
    assert b_data["is_mutual"] is True

    # 7. Her iki tarafın profilinde is_mutual = True
    prof_resp3 = client.get(f"/api/user/public/{uname_a}", cookies=c_b, headers={"User-Agent": mobile_ua})
    assert prof_resp3.json()["profile"]["is_mutual"] is True
    prof_resp4 = client.get(f"/api/user/public/{uname_b}", cookies=c_a, headers={"User-Agent": mobile_ua})
    assert prof_resp4.json()["profile"]["is_mutual"] is True
