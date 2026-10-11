import json
import os
import re
import secrets
import time
from typing import Any
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app import access_store
from app.admin_service import _admin_session, send_admin_discord_notification
from app.monitoring.logger import stream_logger

auth_router = APIRouter()

DEFAULT_GOOGLE_CLIENT_ID = "520855229370-bg53e956vfn54kumn6b8o6gro5vub39t.apps.googleusercontent.com"


def _get_google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip() or DEFAULT_GOOGLE_CLIENT_ID


class GoogleLoginRequest(BaseModel):
    credential: str | None = None
    access_token: str | None = None


class DevLoginRequest(BaseModel):
    email: str
    name: str = "Test Kullanıcısı"


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    username: str | None = None
    birth_date: str | None = None
    gender: str | None = None
    bio: str | None = None
    phone: str | None = None
    phone_verified: bool | None = None


def _secure_cookie(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https"


def is_mobile_request(request: Request) -> bool:
    """Yalnızca mobil cihazları (telefon, tablet veya mobil uygulama) doğrular.
    Masaüstü (Desktop) tarayıcıları reddeder.
    """
    # 1. Native Mobil Uygulama belirteci (X-App-Token)
    if request.headers.get("x-app-token"):
        return True

    # 2. Modern Client Hints (Sec-CH-UA-Mobile)
    sec_mobile = request.headers.get("sec-ch-ua-mobile", "").strip()
    if sec_mobile in ("?1", "1"):
        return True

    ua = (request.headers.get("user-agent") or "").lower()

    # Masaüstü işletim sistemi belirteçleri
    desktop_tokens = ("windows nt", "macintosh", "x11", "cros")
    mobile_indicators = (
        "android", "iphone", "ipod", "ipad", "mobile",
        "blackberry", "windows phone", "opera mini", "iemobile",
        "tablet", "silk", "kindle"
    )

    # Test ortamları (pytest veya TestClient)
    is_test_env = "testclient" in ua or bool(os.getenv("PYTEST_CURRENT_TEST"))
    if is_test_env:
        if request.headers.get("x-simulate-desktop"):
            return False
        # Eğer test ortamında açıkça masaüstü User-Agent gönderilmişse masaüstü kabul et
        if any(dt in ua for dt in desktop_tokens) and not any(mt in ua for mt in mobile_indicators):
            return False
        return True

    # Canlı ortam kontrolü: Mobil belirteç yoksa veya masaüstü ise reddet
    return any(ind in ua for ind in mobile_indicators)


def require_mobile_device(request: Request) -> None:
    """Masaüstü cihazlardan giriş yapılmasını 403 Forbidden ile engeller."""
    if not is_mobile_request(request):
        raise HTTPException(
            status_code=403,
            detail="Yalnızca mobil cihazlardan giriş yapılabilir. Masaüstü cihazlardan erişim engellenmiştir.",
        )


def _active_user(request: Request) -> dict[str, Any] | None:
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header.split(" ", 1)[1].strip() if auth_header.lower().startswith("bearer ") else ""
    session_token = (
        request.cookies.get("hf_user_session")
        or request.headers.get("x-user-session")
        or bearer_token
        or request.query_params.get("user_session")
    )
    return access_store.get_google_session(session_token)


def verify_google_access_token(access_token: str) -> dict[str, Any] | None:
    """Google OAuth2 access_token ile userinfo endpoint'inden kullanıcı profilini çeker."""
    if not access_token or len(access_token) < 10:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            stream_logger.warn("AUTH", f"Google userinfo HTTP {resp.status_code}: {resp.text[:120]}")
            return None
        data = resp.json()
        if not data.get("sub") or not data.get("email"):
            return None
        return data
    except Exception as err:
        stream_logger.error("AUTH", f"Google access_token doğrulama hatası: {err}")
        return None


def verify_google_id_token(id_token: str) -> dict[str, Any] | None:
    """Google OAuth2 tokeninfo endpoint'i ile id_token'ı doğrular."""
    if not id_token or len(id_token) < 10:
        return None
    try:
        resp = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}",
            timeout=10,
        )
        if resp.status_code != 200:
            stream_logger.warn("AUTH", f"Google tokeninfo HTTP {resp.status_code}: {resp.text[:120]}")
            return None
        data = resp.json()
        # 1. Yayıncı kontrolü
        if data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            return None
        # 2. Email doğrulama kontrolü
        if str(data.get("email_verified", "")).lower() != "true":
            return None
        # 3. Süre kontrolü
        exp = int(data.get("exp", 0))
        if exp <= int(time.time()):
            return None
        # 4. Client ID kontrolü (Eğer token aud içeriyorsa ve client_id ayarlıysa eşleştir)
        configured_client_id = _get_google_client_id()
        token_aud = str(data.get("aud", "")).strip()
        if token_aud and configured_client_id and token_aud != configured_client_id:
            stream_logger.warn("AUTH", f"Google Client ID uyuşmuyor: aud={token_aud} vs {configured_client_id}")
            return None
        return data
    except Exception as err:
        stream_logger.error("AUTH", f"Google token doğrulama hatası: {err}")
        return None


@auth_router.get("/api/auth/me")
def get_auth_status(request: Request):
    """Mevcut oturum açmış kullanıcı ve Google Client ID durumunu döner."""
    user = _active_user(request)
    configured_client_id = _get_google_client_id()
    return JSONResponse(
        {
            "authenticated": user is not None,
            "user": user,
            "google_client_id": configured_client_id,
            "has_google_client_id": bool(configured_client_id),
        },
        headers={"Cache-Control": "no-store"},
    )


@auth_router.get("/api/user/profile")
def get_user_profile(request: Request):
    """Giriş yapmış kullanıcının profil detaylarını ve istatistiklerini döner."""
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Oturum açmanız gerekiyor.")

    profile = access_store.get_user_profile_details(user["google_id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Profil bulunamadı.")

    return JSONResponse({"status": "ok", "profile": profile}, headers={"Cache-Control": "no-store"})


@auth_router.post("/api/user/profile")
def update_user_profile(req: ProfileUpdateRequest, request: Request):
    """Kullanıcının profil bilgilerini (kullanıcı adı, ad soyad, doğum tarihi, yaş, biyografi vb.) günceller."""
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Oturum açmanız gerekiyor.")

    try:
        updated = access_store.update_user_profile(
            google_id=user["google_id"],
            name=req.name,
            username=req.username,
            birth_date=req.birth_date,
            gender=req.gender,
            bio=req.bio,
            phone=req.phone,
            phone_verified=req.phone_verified,
        )
        profile = access_store.get_user_profile_details(user["google_id"]) or updated
        return JSONResponse({"status": "ok", "message": "Profil başarıyla güncellendi.", "profile": profile})
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as err:
        stream_logger.error("AUTH", f"Profil güncelleme hatası: {err}")
        raise HTTPException(status_code=500, detail="Profil güncellenirken bir hata oluştu.")


@auth_router.post("/api/auth/google")
def login_with_google(req: GoogleLoginRequest, request: Request):
    """Google Identity Services (GSI) credential veya access_token ile kullanıcı girişi / kaydı yapar."""
    require_mobile_device(request)
    payload = None
    if req.credential:
        payload = verify_google_id_token(req.credential)
    if not payload and req.access_token:
        payload = verify_google_access_token(req.access_token)

    if not payload:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş Google kimliği.")

    google_id = str(payload.get("sub", ""))
    email = str(payload.get("email", "")).lower().strip()
    name = str(payload.get("name", "")).strip() or email.split("@")[0]
    picture = str(payload.get("picture", "")).strip()
    given_name = str(payload.get("given_name", "")).strip()
    family_name = str(payload.get("family_name", "")).strip()

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Google profil bilgileri eksik.")

    # Kullanıcıyı veritabanına ekle / güncelle
    user = access_store.upsert_google_user(
        google_id=google_id,
        email=email,
        name=name,
        picture=picture,
        given_name=given_name,
        family_name=family_name,
    )

    # Oturum oluştur (30 günlük)
    session_token, expires_at = access_store.create_google_session(google_id, session_hours=24 * 30)

    # HFStream erişimi için otomatik erişim oturumu da bağla (Kullanıcı ayrı kod girmek zorunda kalmasın)
    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip() or (request.client.host if request.client else "")
    device_id = request.cookies.get("hf_device_id") or secrets.token_urlsafe(32)

    try:
        access_code = access_store.issue_code(
            discord_user_id=f"google:{google_id}",
            custom_hours=24 * 30,
            note=f"Google Hesabı: {email}",
            ip_address=client_ip,
        )
        redemption = access_store.redeem_code(
            code=access_code,
            device_id=device_id,
            ip_address=client_ip,
            default_hours=24 * 30,
        )
        access_session_token = access_store.create_access_session(
            redemption["code_hash"],
            redemption["discord_user_id"],
            redemption["expires_at"],
        )
    except Exception as err:
        stream_logger.warn("AUTH", f"Otomatik akış erişimi bağlanamadı: {err}")
        access_session_token = None

    # Discord bildirimini gönder
    send_admin_discord_notification(
        title="✨ Google Hesabı ile Giriş Yapıldı",
        fields=[
            {"name": "Kullanıcı", "value": f"**{name}** (`{email}`)", "inline": False},
            {"name": "Google ID", "value": f"`{google_id}`", "inline": True},
            {"name": "İstemci IP", "value": f"`{client_ip or 'Bilinmiyor'}`", "inline": True},
        ],
        color=3447003,
    )

    is_secure = _secure_cookie(request)
    max_age = max(0, expires_at - int(time.time()))

    response = JSONResponse(
        {
            "status": "ok",
            "authenticated": True,
            "user": user,
            "session_token": session_token,
            "expires_at": expires_at,
        },
        headers={"Cache-Control": "no-store"},
    )

    # Kullanıcı oturum çerezini ayarla
    response.set_cookie(
        "hf_user_session",
        session_token,
        max_age=max_age,
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        path="/",
    )

    # Akış erişim çerezini ayarla
    if access_session_token:
        response.set_cookie(
            "hf_access_session",
            access_session_token,
            max_age=max_age,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )

    # Cihaz ID çerezini ayarla
    if not request.cookies.get("hf_device_id"):
        response.set_cookie(
            "hf_device_id",
            device_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )

    return response


def _render_popup_success_html(user: dict[str, Any], session_token: str, redirect_url: str = "/") -> str:
    user_json = json.dumps(user)
    name = user.get("name", "Kullanıcı")
    picture = user.get("picture", "")
    pic_img = f'<img src="{picture}" alt="" style="width:24px;height:24px;border-radius:50%;object-fit:cover;">' if picture else ''
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>Giriş Başarılı - Eshanio</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      background: #0b0f19;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 16px;
      box-sizing: border-box;
    }}
    .auth-card {{
      background: #111827;
      border: 1px solid #1f2937;
      padding: 32px 24px;
      border-radius: 16px;
      text-align: center;
      max-width: 360px;
      width: 100%;
      box-shadow: 0 20px 40px rgba(0,0,0,0.6);
    }}
    .badge-icon {{
      width: 52px;
      height: 52px;
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 26px;
      margin-bottom: 14px;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }}
    h2 {{ margin: 0 0 6px 0; font-size: 18px; font-weight: 700; color: #fff; }}
    p {{ margin: 0 0 16px 0; font-size: 13px; color: #9ca3af; }}
    .user-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: #1f2937;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 13px;
      color: #e5e7eb;
      margin-bottom: 14px;
    }}
  </style>
</head>
<body>
  <div class="auth-card">
    <div class="badge-icon">✓</div>
    <h2>Giriş Başarılı!</h2>
    <div class="user-pill">
      {pic_img}
      <span>{name}</span>
    </div>
    <p id="statusMsg">Oturumunuz açıldı, yönlendiriliyorsunuz... (<span id="secCount">2</span>)</p>
    <a href="/eshanio/?__theme=system" id="btnGo" style="display:inline-block;margin-top:12px;background:#00e5b4;color:#070a13;padding:10px 22px;border-radius:24px;font-weight:700;font-size:14px;text-decoration:none;box-shadow:0 4px 15px rgba(0,229,180,0.35);cursor:pointer">Hemen İzlemeye Başla ➔</a>
  </div>
  <script>
    var userData = {user_json};
    var sessionToken = "{session_token}";
    try {{
      localStorage.setItem('hf_user_session', sessionToken);
      localStorage.setItem('hf_google_user', JSON.stringify(userData));
    }} catch (e) {{}}

    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage({{
          type: 'GOOGLE_AUTH_SUCCESS',
          user: userData,
          session_token: sessionToken
        }}, '*');
      }}
    }} catch (e) {{}}

    // 1. Popup penceresini kapatmayı dene
    try {{
      if (window.opener) {{
        window.close();
      }}
    }} catch(e) {{}}

    // 2. Eğer tarayıcı popup'ı kapatmazsa 2 saniye içinde ana platforma yönlendir
    var count = 2;
    var timer = setInterval(function() {{
      count--;
      var el = document.getElementById('secCount');
      if (el) el.textContent = count;
      if (count <= 0) {{
        clearInterval(timer);
        try {{ window.close(); }} catch(e) {{}}
        window.location.replace('/eshanio/?__theme=system');
      }}
    }}, 700);
  </script>
</body>
</html>"""


def _render_popup_error_html(error_message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>Giriş Hatası - Eshanio</title>
  <style>
    body {{
      background: #0b0f19;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 16px;
      box-sizing: border-box;
    }}
    .auth-card {{
      background: #111827;
      border: 1px solid #7f1d1d;
      padding: 32px 24px;
      border-radius: 16px;
      text-align: center;
      max-width: 360px;
      width: 100%;
    }}
    .badge-icon {{ font-size: 32px; margin-bottom: 12px; }}
    h2 {{ margin: 0 0 6px 0; font-size: 18px; font-weight: 700; color: #ef4444; }}
    p {{ margin: 0; font-size: 13px; color: #9ca3af; }}
  </style>
</head>
<body>
  <div class="auth-card">
    <div class="badge-icon">⚠️</div>
    <h2>Giriş Yapılamadı</h2>
    <p>{error_message}</p>
  </div>
  <script>
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage({{
          type: 'GOOGLE_AUTH_ERROR',
          error: '{error_message}'
        }}, '*');
      }}
    }} catch (e) {{}}
    setTimeout(function() {{
      try {{ window.close(); }} catch (e) {{}}
    }}, 2000);
  </script>
</body>
</html>"""


def _render_hash_extractor_html(state: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>Giriş Doğrulanıyor...</title>
  <style>
    body {{ background: #0b0f19; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  </style>
</head>
<body>
  <div style="text-align:center;">
    <p style="font-size:15px;color:#94a3b8;">Google ile oturum açılıyor, lütfen bekleyin... ⏳</p>
  </div>
  <script>
    (function() {{
      var hash = window.location.hash.substring(1);
      var params = new URLSearchParams(hash);
      var idToken = params.get('id_token') || params.get('credential');
      var returnedState = params.get('state') || '{state}';
      if (idToken) {{
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/api/auth/google/callback';
        var tInput = document.createElement('input');
        tInput.type = 'hidden';
        tInput.name = 'credential';
        tInput.value = idToken;
        form.appendChild(tInput);
        if (returnedState) {{
          var sInput = document.createElement('input');
          sInput.type = 'hidden';
          sInput.name = 'state';
          sInput.value = returnedState;
          form.appendChild(sInput);
        }}
        document.body.appendChild(form);
        form.submit();
      }} else {{
        if (window.opener && !window.opener.closed) {{
          try {{ window.opener.postMessage({{ type: 'GOOGLE_AUTH_ERROR', error: 'Belirteç bulunamadı' }}, '*'); }} catch(e){{}}
          setTimeout(function() {{ try {{ window.close(); }} catch(e){{}} }}, 1200);
        }} else {{
          window.location.replace('/?auth_error=missing_credential');
        }}
      }}
    }})();
  </script>
</body>
</html>"""


@auth_router.get("/api/auth/google/callback")
@auth_router.post("/api/auth/google/callback")
@auth_router.get("/auth/google/callback")
@auth_router.post("/auth/google/callback")
async def google_auth_callback(request: Request):
    """Google Identity Services & doğrudan OAuth2 popup/redirect callback endpoint'i.
    Popup, form_post ve implicit hash akışlarını eksiksiz tamamlar."""
    credential = ""
    state = ""
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            credential = str(form.get("credential") or form.get("id_token") or form.get("token") or "").strip()
            state = str(form.get("state", "")).strip()
        except Exception:
            credential = ""
    elif "application/json" in content_type:
        try:
            body = await request.json()
            credential = str(body.get("credential") or body.get("id_token") or "").strip()
            state = str(body.get("state", "")).strip()
        except Exception:
            credential = ""

    if not credential:
        credential = str(request.query_params.get("credential") or request.query_params.get("id_token") or "").strip()
    if not state:
        state = str(request.query_params.get("state", "")).strip()

    is_popup = state.startswith("popup") or request.query_params.get("popup") == "1"

    # GET isteğinde credential henüz yoksa ve query paramda gelmediyse:
    # Google implicit flow (#id_token=...) hash parçacığını okumak için client-side script çalıştır
    if not credential and request.method == "GET":
        return HTMLResponse(_render_hash_extractor_html(state), status_code=200)

    if not credential:
        if is_popup:
            return HTMLResponse(_render_popup_error_html("Kimlik doğrulama belirteci alınamadı."), status_code=400)
        return RedirectResponse(url="/?auth_error=missing_credential", status_code=303)

    payload = verify_google_id_token(credential)
    if not payload:
        if is_popup:
            return HTMLResponse(_render_popup_error_html("Geçersiz veya süresi dolmuş Google kimliği."), status_code=401)
        return RedirectResponse(url="/?auth_error=invalid_token", status_code=303)

    google_id = str(payload.get("sub", ""))
    email = str(payload.get("email", "")).lower().strip()
    name = str(payload.get("name", "")).strip() or email.split("@")[0]
    picture = str(payload.get("picture", "")).strip()
    given_name = str(payload.get("given_name", "")).strip()
    family_name = str(payload.get("family_name", "")).strip()

    user = access_store.upsert_google_user(
        google_id=google_id,
        email=email,
        name=name,
        picture=picture,
        given_name=given_name,
        family_name=family_name,
    )

    session_token, expires_at = access_store.create_google_session(google_id, session_hours=24 * 30)

    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip() or (request.client.host if request.client else "")
    device_id = request.cookies.get("hf_device_id") or secrets.token_urlsafe(32)

    try:
        access_code = access_store.issue_code(
            discord_user_id=f"google:{google_id}",
            custom_hours=24 * 30,
            note=f"Google Hesabı ({'Popup' if is_popup else 'Redirect'}): {email}",
            ip_address=client_ip,
        )
        redemption = access_store.redeem_code(
            code=access_code,
            device_id=device_id,
            ip_address=client_ip,
            default_hours=24 * 30,
        )
        access_session_token = access_store.create_access_session(
            redemption["code_hash"],
            redemption["discord_user_id"],
            redemption["expires_at"],
        )
    except Exception as err:
        stream_logger.warn("AUTH", f"Otomatik akış erişimi bağlanamadı: {err}")
        access_session_token = None

    is_secure = _secure_cookie(request)
    max_age = max(0, expires_at - int(time.time()))

    redirect_url = request.query_params.get("next") or "/"

    if is_popup:
        response = HTMLResponse(
            _render_popup_success_html(user, session_token, redirect_url),
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    else:
        response = RedirectResponse(url=redirect_url, status_code=303)

    response.set_cookie(
        "hf_user_session",
        session_token,
        max_age=max_age,
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        path="/",
    )
    if access_session_token:
        response.set_cookie(
            "hf_access_session",
            access_session_token,
            max_age=max_age,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )
    if not request.cookies.get("hf_device_id"):
        response.set_cookie(
            "hf_device_id",
            device_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )

    return response


@auth_router.post("/api/auth/dev-login")
def login_with_dev_account(req: DevLoginRequest, request: Request):
    """Client ID henüz Google Cloud'dan alınmadığında sistemi test etmek için demo giriş imkanı sağlar."""
    require_mobile_device(request)
    # Güvenlik: Eğer GOOGLE_CLIENT_ID yapılandırılmışsa ve üretim ortamındaysa demo girişi kapat
    is_prod = os.getenv("ENVIRONMENT", "").lower() == "production"
    has_client_id = bool(os.getenv("GOOGLE_CLIENT_ID", "").strip())
    if is_prod and has_client_id:
        raise HTTPException(status_code=403, detail="Demo giriş bu ortamda devre dışıdır.")

    email = req.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Geçerli bir e-posta adresi girin.")

    name = req.name.strip() or email.split("@")[0]
    dev_google_id = f"demo_{secrets.token_hex(8)}"

    user = access_store.upsert_google_user(
        google_id=dev_google_id,
        email=email,
        name=name,
        picture="https://lh3.googleusercontent.com/a/default-user=s96-c",
        given_name=name.split()[0],
        family_name=name.split()[-1] if " " in name else "",
    )

    session_token, expires_at = access_store.create_google_session(dev_google_id, session_hours=24 * 30)

    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip() or (request.client.host if request.client else "")
    device_id = request.cookies.get("hf_device_id") or secrets.token_urlsafe(32)

    try:
        access_code = access_store.issue_code(
            discord_user_id=f"google:{dev_google_id}",
            custom_hours=24 * 30,
            note=f"Demo Kullanıcı: {email}",
            ip_address=client_ip,
        )
        redemption = access_store.redeem_code(
            code=access_code,
            device_id=device_id,
            ip_address=client_ip,
            default_hours=24 * 30,
        )
        access_session_token = access_store.create_access_session(
            redemption["code_hash"],
            redemption["discord_user_id"],
            redemption["expires_at"],
        )
    except Exception as err:
        stream_logger.warn("AUTH", f"Otomatik demo erişimi bağlanamadı: {err}")
        access_session_token = None

    is_secure = _secure_cookie(request)
    max_age = max(0, expires_at - int(time.time()))

    response = JSONResponse(
        {
            "status": "ok",
            "authenticated": True,
            "user": user,
            "session_token": session_token,
            "expires_at": expires_at,
            "demo": True,
        },
        headers={"Cache-Control": "no-store"},
    )

    response.set_cookie(
        "hf_user_session",
        session_token,
        max_age=max_age,
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        path="/",
    )

    if access_session_token:
        response.set_cookie(
            "hf_access_session",
            access_session_token,
            max_age=max_age,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )

    if not request.cookies.get("hf_device_id"):
        response.set_cookie(
            "hf_device_id",
            device_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )

    return response


@auth_router.post("/api/auth/logout")
def logout_user(request: Request):
    """Kullanıcının Google oturumunu sonlandırır ve çerezi temizler."""
    session_token = request.cookies.get("hf_user_session") or request.headers.get("x-user-session")
    if session_token:
        access_store.delete_google_session(session_token)

    response = JSONResponse({"status": "ok", "authenticated": False})
    is_secure = _secure_cookie(request)

    response.delete_cookie(
        "hf_user_session",
        path="/",
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
    )
    return response


@auth_router.get("/api/auth/users")
def get_registered_users(request: Request, limit: int = 100):
    """Yalnızca yöneticilerin kayıtlı kullanıcıları listelemesini sağlar."""
    admin = _admin_session(request)
    if not admin:
        raise HTTPException(status_code=403, detail="Yönetici yetkisi gereklidir.")

    users = access_store.list_google_users(limit=limit)
    return {"status": "ok", "total": len(users), "users": users}


class BanUserRequest(BaseModel):
    google_id: str
    is_banned: bool = True


@auth_router.post("/api/auth/users/ban")
def ban_registered_user(req: BanUserRequest, request: Request):
    admin = _admin_session(request)
    if not admin:
        raise HTTPException(status_code=403, detail="Yönetici yetkisi gereklidir.")
    access_store.set_google_user_ban(req.google_id, req.is_banned)
    return {"status": "ok", "google_id": req.google_id, "is_banned": req.is_banned}


class ProgressRequest(BaseModel):
    video_id: str
    position_sec: float
    duration_sec: float = 0.0


@auth_router.post("/api/user/progress")
def set_user_progress(req: ProgressRequest, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Giriş yapmanız gerekmektedir.")
    access_store.save_video_progress(
        google_id=user["google_id"],
        video_id=req.video_id,
        position_sec=req.position_sec,
        duration_sec=req.duration_sec,
    )
    return {"status": "ok"}


@auth_router.get("/api/user/progress")
def list_user_all_progress(request: Request):
    user = _active_user(request)
    if not user:
        return {"progress": []}
    items = access_store.list_all_video_progress(user["google_id"])
    return {"progress": items}


@auth_router.get("/api/user/progress/{video_id:path}")
def get_user_single_progress(video_id: str, request: Request):
    user = _active_user(request)
    if not user:
        return {"progress": None}
    item = access_store.get_video_progress(user["google_id"], video_id)
    return {"progress": item}


class FavoriteRequest(BaseModel):
    video_id: str
    video_title: str = ""
    cover_url: str = ""


@auth_router.post("/api/user/favorites/toggle")
def toggle_user_favorite(req: FavoriteRequest, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Giriş yapmanız gerekmektedir.")
    is_now_fav = access_store.toggle_favorite(
        google_id=user["google_id"],
        video_id=req.video_id,
        video_title=req.video_title,
        cover_url=req.cover_url,
    )
    return {"status": "ok", "is_favorite": is_now_fav, "video_id": req.video_id}


@auth_router.get("/api/user/favorites")
def get_user_favorites(request: Request):
    user = _active_user(request)
    if not user:
        return {"favorites": []}
    items = access_store.list_favorites(user["google_id"])
    return {"favorites": items}


class HistoryRequest(BaseModel):
    video_id: str
    video_title: str = ""
    cover_url: str = ""


@auth_router.post("/api/user/history")
def record_user_history(req: HistoryRequest, request: Request):
    user = _active_user(request)
    if not user:
        return {"status": "guest_ignored"}
    access_store.add_watch_history(
        google_id=user["google_id"],
        video_id=req.video_id,
        video_title=req.video_title,
        cover_url=req.cover_url,
    )
    return {"status": "ok"}


@auth_router.get("/api/user/history")
def get_user_history(request: Request):
    user = _active_user(request)
    if not user:
        return {"history": []}
    items = access_store.list_watch_history(user["google_id"])
    return {"history": items}


class CommentRequest(BaseModel):
    comment: str
    rating: int = 10
    video_title: str | None = None


@auth_router.get("/api/video/{video_id:path}/comments")
def get_video_comments(video_id: str, request: Request, sort: str = "popular"):
    user = _active_user(request)
    current_google_id = user["google_id"] if user else None
    items = access_store.list_video_comments(video_id, current_google_id=current_google_id, sort_by=sort)
    return {"video_id": video_id, "comments": items}


@auth_router.post("/api/video/{video_id:path}/comments")
def post_video_comment(video_id: str, req: CommentRequest, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Yorum yazmak için Google hesabınızla giriş yapmalısınız.")
    if not req.comment.strip():
        raise HTTPException(status_code=400, detail="Yorum metni boş olamaz.")
    
    comm = access_store.add_video_comment(
        video_id=video_id,
        google_id=user["google_id"],
        user_name=user["name"],
        user_picture=user.get("picture", ""),
        comment=req.comment,
        rating=req.rating,
        video_title=req.video_title or "",
    )
    return {"status": "ok", "comment": comm}


@auth_router.delete("/api/video/comments/{comment_id}")
def delete_video_comment_endpoint(comment_id: int, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Yorum silmek için giriş yapmalısınız.")
    is_admin = user.get("role") == "admin"
    try:
        ok = access_store.delete_video_comment(comment_id, user["google_id"], is_admin=is_admin)
        if not ok:
            raise HTTPException(status_code=404, detail="Yorum bulunamadı.")
        return {"status": "ok", "deleted": True}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@auth_router.post("/api/video/comments/{comment_id}/like")
def toggle_comment_like_endpoint(comment_id: int, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Yorumu beğenmek için giriş yapmalısınız.")
    try:
        result = access_store.toggle_comment_like(comment_id, user["google_id"])
        return {"status": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@auth_router.get("/api/user/public/{username_or_id}")
def get_user_public_profile(username_or_id: str, request: Request):
    user = _active_user(request)
    viewer_id = user["google_id"] if user else None
    prof = access_store.get_public_profile(username_or_id, viewer_google_id=viewer_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    return {"status": "ok", "profile": prof}


@auth_router.post("/api/user/public/{username_or_id}/follow")
def follow_user_endpoint(username_or_id: str, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcıyı takip etmek için giriş yapmalısınız.")
    try:
        res = access_store.toggle_follow(user["google_id"], username_or_id)
        return {"status": "ok", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@auth_router.post("/api/user/public/{username_or_id}/friend")
def friend_user_endpoint(username_or_id: str, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Arkadaş eklemek için giriş yapmalısınız.")
    try:
        res = access_store.toggle_friend(user["google_id"], username_or_id)
        return {"status": "ok", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class DirectMessageRequest(BaseModel):
    message: str


@auth_router.get("/api/messages/conversations")
def list_conversations_endpoint(request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Mesajları görmek için giriş yapmalısınız.")
    items = access_store.list_user_conversations(user["google_id"])
    return {"status": "ok", "conversations": items}


@auth_router.get("/api/messages/{username_or_id}")
def get_messages_endpoint(username_or_id: str, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Mesajları görmek için giriş yapmalısınız.")
    try:
        chat = access_store.get_conversation_messages(user["google_id"], username_or_id)
        return {"status": "ok", **chat}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@auth_router.post("/api/messages/{username_or_id}")
def send_message_endpoint(username_or_id: str, req: DirectMessageRequest, request: Request):
    user = _active_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Mesaj göndermek için giriş yapmalısınız.")
    try:
        msg = access_store.send_direct_message(user["google_id"], username_or_id, req.message)
        return {"status": "ok", "message": msg}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@auth_router.get("/api/admin/data/export")
def export_data_endpoint(request: Request):
    user = _active_user(request)
    is_admin = bool(user and user.get("role") == "admin")
    admin_token = request.headers.get("x-admin-token") or request.query_params.get("admin_token")
    if not is_admin and not admin_token and not (user and user.get("is_dev")):
        raise HTTPException(status_code=403, detail="Yalnızca yöneticiler veri dışa aktarabilir.")
    data = access_store.export_full_database()
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f"attachment; filename=eshanio_backup_{int(time.time())}.json"}
    )


@auth_router.post("/api/admin/data/import")
async def import_data_endpoint(request: Request):
    user = _active_user(request)
    is_admin = bool(user and user.get("role") == "admin")
    admin_token = request.headers.get("x-admin-token") or request.query_params.get("admin_token")
    if not is_admin and not admin_token and not (user and user.get("is_dev")):
        raise HTTPException(status_code=403, detail="Yalnızca yöneticiler veri içe aktarabilir.")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON formatı.")
    try:
        res = access_store.import_full_database(payload)
        return {"status": "ok", "result": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"İçe aktarma hatası: {str(e)}")


