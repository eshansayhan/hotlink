import json
import os
import re
import secrets
import sys
import time
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from app import access_store
from app.admin_service import _admin_session, send_admin_discord_notification
from app.monitoring.logger import stream_logger
from app.routers.auth import is_mobile_request, require_mobile_device

access_router = APIRouter()


class AccessibleVideosResponse(JSONResponse):
    """JSONResponse that also supports dictionary-style access for test helpers."""
    def __init__(self, content: dict, *args, **kwargs):
        self._content_dict = content
        super().__init__(content, *args, **kwargs)

    def __getitem__(self, key):
        return self._content_dict[key]

    def get(self, key, default=None):
        return self._content_dict.get(key, default)

    def __contains__(self, key):
        return key in self._content_dict


def _active_access(request: Request) -> dict | None:
    # 1. Admin oturum kontrolü (hf_admin_session / hf_admin_token) - Masaüstünden de erişebilir
    admin = _admin_session(request)
    if admin:
        return {
            "type": "admin",
            "discord_user_id": admin.get("discord_user_id", "admin"),
            "expires_at": admin.get("expires_at", int(time.time()) + 86400),
        }

    # 2. Normal kullanıcılar için mobil cihaz zorunluluğu (Masaüstü erişimi engellenir)
    if not is_mobile_request(request):
        return None

    # 3. Google oturum kontrolü (hf_user_session çerezi, Bearer token, x-user-session veya query param)
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header.split(" ", 1)[1].strip() if auth_header.lower().startswith("bearer ") else ""
    google_token = (
        request.cookies.get("hf_user_session")
        or request.headers.get("x-user-session")
        or bearer_token
        or request.query_params.get("user_session")
    )
    if google_token:
        google_user = access_store.get_google_session(google_token)
        if google_user:
            return {
                "type": "google",
                "google_id": google_user.get("google_id"),
                "email": google_user.get("email"),
                "name": google_user.get("name"),
                "role": google_user.get("role"),
                "expires_at": google_user.get("expires_at"),
            }

    # 2. Admin oturum kontrolü (hf_admin_session / hf_admin_token)
    admin = _admin_session(request)
    if admin:
        return {
            "type": "admin",
            "discord_user_id": admin.get("discord_user_id", "admin"),
            "expires_at": admin.get("expires_at", int(time.time()) + 86400),
        }

    # 3. Klasik erişim kodu oturumu (hf_access_session)
    session_token = (
        request.cookies.get("hf_access_session")
        or request.headers.get("x-access-session")
        or request.query_params.get("session")
        or request.query_params.get("token")
        or request.query_params.get("access_token")
    )
    device_id = (
        request.cookies.get("hf_device_id")
        or request.headers.get("x-device-id")
        or request.query_params.get("device_id")
    )
    return access_store.get_access_session(
        session_token,
        device_id,
    )


def _secure_cookie(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https"


def _oauth_redirect_uri() -> str:
    public_url = os.getenv(
        "HFSTREAM_PUBLIC_URL",
        "https://eshansayhan-hotlink.hf.space",
    ).rstrip("/")
    return f"{public_url}/auth/discord/callback"


def _discord_api_request(method: str, url: str, **kwargs):
    main_mod = sys.modules.get("app.main")
    req_lib = getattr(main_mod, "requests", requests)
    time_lib = getattr(main_mod, "time", time)
    for attempt in range(3):
        try:
            return req_lib.request(method, url, **kwargs)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectTimeout):
            if attempt == 2:
                raise
            time_lib.sleep(0.5 * (attempt + 1))


def _catalog_video_list(payload: dict) -> list[dict]:
    videos = payload.get("videos", [])
    return videos if isinstance(videos, list) else []


async def _json_object(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError as error:
        raise HTTPException(status_code=400, detail="JSON isteği geçersiz.") from error
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="İstek gövdesi geçersiz.")
    return body


@access_router.get("/api/access/me")
def access_identity(request: Request):
    device_id = request.cookies.get("hf_device_id") or request.headers.get("x-device-id")
    if not device_id:
        device_id = secrets.token_urlsafe(32)
    session_token = request.cookies.get("hf_access_session") or request.headers.get("x-access-session")
    access = access_store.get_access_session(
        session_token,
        device_id,
    )
    admin = _admin_session(request)
    is_secure = _secure_cookie(request)
    # content_access: True only when middleware confirmed Turkey + mobile/app (§5, §13 dost.md)
    content_country = getattr(request.state, "content_country", None)
    content_access = content_country == "TR"
    response = JSONResponse(
        {
            "authenticated": access is not None,
            "expires_at": access["expires_at"] if access else None,
            "code": access.get("raw_code") if access else None,
            "device_id": device_id,
            "admin": admin is not None,
            "admin_password_configured": len(os.getenv("HFSTREAM_ADMIN_PASSWORD", "")) >= 16,
            "content_access": content_access,
            "country": content_country or "",
        },
        headers={"Cache-Control": "no-store, private"},
    )
    if not request.cookies.get("hf_device_id"):
        response.set_cookie(
            "hf_device_id",
            device_id,
            max_age=60 * 60 * 24 * 60,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )
    return response


@access_router.post("/api/access/login")
async def login_with_access_code(request: Request):
    require_mobile_device(request)
    body = await _json_object(request)
    code = str(body.get("code", "")).strip()
    device_id = (
        request.cookies.get("hf_device_id")
        or str(body.get("device_id", "")).strip()
        or request.headers.get("x-device-id", "").strip()
    )
    if not device_id:
        device_id = secrets.token_urlsafe(32)
    if not re.fullmatch(r"[0-9]{14}", code):
        raise HTTPException(status_code=400, detail="Geçerli bir 14 haneli kod gir.")

    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host
    try:
        redemption = access_store.redeem_code(
            code,
            device_id,
            client_ip,
            access_store.get_settings()["session_hours"],
        )
    except access_store.AccessRateLimitError as error:
        raise HTTPException(status_code=429, detail="Çok fazla deneme yapıldı. Bir dakika sonra tekrar dene.") from error
    if not redemption:
        raise HTTPException(
            status_code=401,
            detail="Kod geçersiz veya süresi dolmuş.",
        )

    send_admin_discord_notification(
        title="🔑 Erişim Kodu Kullanıldı (Giriş Yapıldı)",
        fields=[
            {"name": "Discord Üye", "value": str(redemption.get("discord_user_id", "Bilinmiyor")), "inline": True},
            {"name": "Kod", "value": f"`{code}`", "inline": True},
            {"name": "İstemci IP", "value": f"`{client_ip or 'Bilinmiyor'}`", "inline": True},
            {"name": "Cihaz ID", "value": f"`{device_id[:16]}...`" if len(device_id) > 16 else f"`{device_id}`", "inline": True},
        ],
        color=2278750,
    )

    token = access_store.create_access_session(
        redemption["code_hash"],
        redemption["discord_user_id"],
        redemption["expires_at"],
    )
    remaining = max(0, redemption["expires_at"] - int(time.time()))
    is_secure = _secure_cookie(request)
    content_country = getattr(request.state, "content_country", None)
    response = JSONResponse(
        {
            "authenticated": True,
            "expires_at": redemption["expires_at"],
            "code": redemption.get("raw_code") or code,
            "device_id": device_id,
            "token": token,
            "content_access": content_country == "TR",
            "country": content_country or "",
        },
        headers={"Cache-Control": "no-store, private"},
    )
    response.set_cookie(
        "hf_access_session",
        token,
        max_age=remaining,
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        path="/",
    )
    if not request.cookies.get("hf_device_id"):
        response.set_cookie(
            "hf_device_id",
            device_id,
            max_age=60 * 60 * 24 * 60,
            httponly=True,
            secure=is_secure,
            samesite="none" if is_secure else "lax",
            path="/",
        )
    return response


@access_router.post("/api/access/logout")
def logout_access(request: Request):
    session_token = request.cookies.get("hf_access_session") or request.headers.get("x-access-session")
    access_store.revoke_access_session(session_token)
    response = JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
    is_secure = _secure_cookie(request)
    response.delete_cookie(
        "hf_access_session",
        path="/",
        secure=is_secure,
        samesite="none" if is_secure else "lax",
    )
    return response


@access_router.get("/api/access/videos")
async def get_accessible_videos(request: Request):
    # 1. Masaüstü cihaz denetimi: Masaüstü ise içerikler gizli (§2 dost.md)
    if not is_mobile_request(request):
        return AccessibleVideosResponse(
            {"total": 0, "videos": []},
            headers={"Cache-Control": "no-store, private"},
        )

    # 2. Ülke denetimi: Yurt dışı ise film/dizi içerikleri gizli (§5, §6 dost.md)
    country = (
        getattr(request.state, "content_country", None)
        or request.headers.get("cf-ipcountry")
        or request.headers.get("x-country")
        or ""
    ).upper()
    if country and country != "TR":
        return AccessibleVideosResponse(
            {"total": 0, "videos": []},
            headers={"Cache-Control": "no-store, private"},
        )

    # 3. Oturum denetimi (embed_config require_authenticated_session kontrolü)
    main_mod = sys.modules.get("app.main")
    cfg_fn = getattr(main_mod, "load_embed_config", None)
    if not cfg_fn:
        from app.video_metadata import load_embed_config
        cfg_fn = load_embed_config
    cfg = cfg_fn()
    content_cfg = cfg.get("content_access", {})
    if content_cfg.get("require_authenticated_session", True):
        if not _active_access(request):
            return AccessibleVideosResponse(
                {"total": 0, "videos": []},
                headers={"Cache-Control": "no-store, private"},
            )

    list_fn = getattr(main_mod, "list_all_video_apis", None)
    if list_fn:
        payload = await list_fn(request)
    else:
        from app.routers.catalog import list_all_video_apis
        payload = await list_all_video_apis(request)
    videos = _catalog_video_list(payload)
    return AccessibleVideosResponse(
        {"total": len(videos), "videos": videos},
        headers={"Cache-Control": "no-store, private"},
    )


@access_router.get("/api/access/debug")
def access_debug(request: Request):
    """Geliştirme tanılama — middleware state + auth durumunu gösterir."""
    return JSONResponse({
        "is_app": getattr(request.state, "is_app", None),
        "content_country": getattr(request.state, "content_country", None),
        "authenticated": _active_access(request) is not None,
        "user_agent": request.headers.get("user-agent", ""),
        "cf_ipcountry": request.headers.get("cf-ipcountry", ""),
        "x_country": request.headers.get("x-country", ""),
        "has_session_cookie": bool(request.cookies.get("hf_access_session")),
        "has_session_header": bool(request.headers.get("x-access-session")),
    })

@access_router.api_route(
    "/api/access/stream/{tensor_name}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def stream_access_video(tensor_name: str, request: Request, source_file: str = ""):
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Content-Type, Accept-Encoding",
                "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
            },
        )
    main_mod = sys.modules.get("app.main")
    stream_fn = getattr(main_mod, "stream_safetensors_video", None)
    return await stream_fn(
        tensor_name=tensor_name,
        source_file=source_file,
        request=request,
    )


@access_router.api_route("/api/access/download/{tensor_name}", methods=["GET", "HEAD", "OPTIONS"])
@access_router.api_route("/api/access/download", methods=["GET", "HEAD", "OPTIONS"])
async def download_access_video(
    tensor_name: str = "",
    tensor: str = "",
    source_file: str = "",
    quality: str = "",
    title: str = "",
    url: str = "",
    request: Request = None,
):
    if request and request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Content-Type, Accept-Encoding",
                "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, Content-Range",
            },
        )
    main_mod = sys.modules.get("app.main")
    dl_fn = getattr(main_mod, "download_safetensors_video", None)
    if not dl_fn:
        raise HTTPException(status_code=500, detail="Download service unavailable")
    return await dl_fn(
        tensor_name=tensor_name,
        tensor=tensor,
        source_file=source_file,
        quality=quality,
        title=title,
        url=url,
        request=request,
    )


class StreamHeartbeatRequest(BaseModel):
    stream_id: str
    is_new: bool = False


@access_router.post("/api/access/stream/heartbeat")
def handle_stream_heartbeat(req: StreamHeartbeatRequest, request: Request):
    access = _active_access(request)
    if not access:
        raise HTTPException(status_code=401, detail="Geçerli bir erişim oturumu bulunamadı.")
    code_hash = access["code_hash"]
    allowed, msg = access_store.update_stream_heartbeat(code_hash, req.stream_id, req.is_new)
    if not allowed:
        return JSONResponse({"status": "concurrency_limit", "message": msg}, status_code=409)
    return {"status": "ok"}


@access_router.post("/api/access/admin/login")
async def login_admin_with_password(request: Request):
    admin_password = os.getenv("HFSTREAM_ADMIN_PASSWORD", "")
    if len(admin_password) < 16:
        raise HTTPException(
            status_code=503,
            detail="Yönetici parolası ayarlanmamış veya en az 16 karakter değil.",
        )

    body = await _json_object(request)
    password = str(body.get("password", ""))
    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host
    try:
        access_store.check_admin_login_attempt(client_ip)
    except access_store.AccessRateLimitError as error:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla yönetici giriş denemesi. Bir dakika sonra tekrar dene.",
        ) from error

    if not secrets.compare_digest(password.encode("utf-8"), admin_password.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Yönetici parolası hatalı.")

    token, expires_at = access_store.create_admin_session("password-admin")
    response = JSONResponse(
        {"admin": True, "expires_at": expires_at, "token": token},
        headers={"Cache-Control": "no-store"},
    )
    is_secure = _secure_cookie(request)
    response.set_cookie(
        "hf_admin_session",
        token,
        max_age=max(0, expires_at - int(time.time())),
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        path="/",
    )
    return response


@access_router.get("/auth/discord/callback")
def finish_admin_discord_login(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    nonce = request.cookies.get("hf_admin_oauth_nonce", "")
    if error or not code or not state or not nonce or not access_store.consume_oauth_state(state, nonce):
        raise HTTPException(status_code=400, detail="Discord yönetici doğrulaması tamamlanamadı.")

    client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    admin_user_id = os.getenv("DISCORD_ADMIN_USER_ID", "").strip()
    if not client_id or not client_secret or not admin_user_id:
        raise HTTPException(status_code=503, detail="Discord yönetici girişi henüz yapılandırılmadı.")

    try:
        token_response = _discord_api_request(
            "POST",
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _oauth_redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=(30, 30),
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        user_response = _discord_api_request(
            "GET",
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(30, 30),
        )
        user_response.raise_for_status()
        discord_user_id = str(user_response.json()["id"])
    except (requests.RequestException, KeyError, ValueError) as error:
        stream_logger.error("AUTH", f"Discord admin OAuth exchange failed: {error}")
        raise HTTPException(status_code=502, detail="Discord hesabı doğrulanamadı.") from error

    if not secrets.compare_digest(discord_user_id, admin_user_id):
        raise HTTPException(status_code=403, detail="Bu Discord hesabının yönetici paneline erişimi yok.")

    token, expires_at = access_store.create_admin_session(discord_user_id)
    response = RedirectResponse("/eshanio/?admin=1", status_code=303)
    is_secure = _secure_cookie(request)
    response.set_cookie(
        "hf_admin_session",
        token,
        max_age=max(0, expires_at - int(time.time())),
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        path="/",
    )
    response.delete_cookie("hf_admin_oauth_nonce", path="/")
    return response


@access_router.post("/api/access/admin/logout")
def logout_admin(request: Request):
    token = request.cookies.get("hf_admin_session")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
    if token:
        access_store.revoke_admin_session(token)
    response = JSONResponse({"admin": False}, headers={"Cache-Control": "no-store"})
    response.delete_cookie("hf_admin_session", path="/")
    return response


@access_router.get("/api/access/admin/videos")
async def get_admin_video_catalog(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    main_mod = sys.modules.get("app.main")
    list_fn = getattr(main_mod, "list_all_video_apis", None)
    if list_fn:
        payload = await list_fn(request)
    else:
        from app.routers.catalog import list_all_video_apis
        payload = await list_all_video_apis(request)
    return {"videos": _catalog_video_list(payload)}


@access_router.get("/api/access/admin/settings")
def get_admin_access_settings(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    return {**access_store.get_settings(), "codes": access_store.list_codes()}


@access_router.post("/api/access/admin/settings")
async def update_admin_access_settings(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    body = await _json_object(request)
    public_ids = body.get("public_video_ids", [])
    if not isinstance(public_ids, list) or not all(isinstance(item, str) for item in public_ids):
        raise HTTPException(status_code=400, detail="Varsayılan video listesi geçersiz.")
    try:
        session_hours = int(body.get("session_hours", access_store.DEFAULT_SESSION_HOURS))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Kod süresi saat cinsinden sayı olmalı.") from error
    main_mod = sys.modules.get("app.main")
    list_fn = getattr(main_mod, "list_all_video_apis", None)
    if list_fn:
        catalog = _catalog_video_list(await list_fn(request))
    else:
        from app.routers.catalog import list_all_video_apis
        catalog = _catalog_video_list(await list_all_video_apis(request))
    allowed_ids = {str(video.get("id")) for video in catalog if video.get("id")}
    unknown_ids = set(public_ids) - allowed_ids
    if unknown_ids:
        raise HTTPException(status_code=400, detail="Seçilen video kataloğun içinde bulunamadı.")
    admin_log_webhook = body.get("admin_log_webhook")
    return access_store.update_settings(public_ids, session_hours, admin_log_webhook=admin_log_webhook)


@access_router.post("/api/access/admin/codes/{code_hash}/revoke")
def revoke_admin_access_code(code_hash: str, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    if not re.fullmatch(r"[a-f0-9]{64}", code_hash):
        raise HTTPException(status_code=400, detail="Kod kaydı geçersiz.")
    if not access_store.revoke_code(code_hash):
        raise HTTPException(status_code=404, detail="Kod bulunamadı veya zaten iptal edilmiş.")
    return {"revoked": True}
