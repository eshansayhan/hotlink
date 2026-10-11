from pydantic import BaseModel
import os
import subprocess

import secrets
from contextlib import asynccontextmanager
import requests
from fastapi import FastAPI, Request, HTTPException
import re, json, urllib.request
from urllib.parse import quote, urljoin, urlencode
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, Response, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import math, time
from starlette.concurrency import run_in_threadpool

from app import access_store
from app.config import config, BASE_DIR
from app.monitoring.logger import stream_logger
from app.streamer.recovery import watchdog
from app.monitoring.health import start_memory_hygiene, stop_memory_hygiene
from app.middleware import (
    DisabledAccessRoutesMiddleware,
    GeoAndClientRestrictionMiddleware,
    HFVIDEO_API_URL,
    M3U_SERVICE_URL,
    M3UServiceProxyMiddleware,
    NoCacheForPrivateAPIMiddleware,
    get_proxy_target_url,
    should_proxy_m3u_service,
)
from app.video_metadata import (
    EMBED_CONFIG_FILE,
    EMBED_HTML_FILE,
    load_embed_config,
    save_embed_config,
    parse_video_metadata,
)
from app.routes import router
from app.admin_service import (
    admin_router,
    _admin_session,
    send_admin_discord_notification,
    _send_discord_announcement_sync,
    _discord_action_components,
    CustomCodeRequest,
    AnnounceRequest,
    ReportSubmitRequest,
    BanClientRequest,
    get_admin_analytics,
    generate_admin_access_code,
    generate_custom_access_code,
    admin_announce_video,
    submit_issue_report,
    get_admin_reports,
    resolve_admin_report,
    delete_admin_report,
    cleanup_admin_codes,
    get_admin_banned_clients,
    add_admin_banned_client,
    remove_admin_banned_client,
    get_admin_access_logs,
    clear_admin_access_logs,
)
from app.routers.catalog import (
    catalog_router,
    serve_monetization_config,
    serve_mesh_cluster_map,
    get_embed_configuration,
    update_embed_configuration,
    list_all_video_apis,
    get_single_video_api,
    serve_embed_player,
)
from app.routers.access import (
    access_router,
    _active_access,
    _secure_cookie,
    _oauth_redirect_uri,
    _discord_api_request,
    _catalog_video_list,
    _json_object,
    access_identity,
    login_with_access_code,
    logout_access,
    get_accessible_videos,
    stream_access_video,
    download_access_video,
    StreamHeartbeatRequest,
    handle_stream_heartbeat,
    login_admin_with_password,
    finish_admin_discord_login,
    logout_admin,
    get_admin_video_catalog,
    get_admin_access_settings,
    update_admin_access_settings,
    revoke_admin_access_code,
)
from app.routers.discord import (
    discord_router,
    _verify_discord_interaction,
    handle_discord_interactions,
)
from app.routers.auth import auth_router
from app.routers.onion import router as onion_router

WEB_DIR = BASE_DIR / "web"
INDEX_FILE = WEB_DIR / "index.html"
ESHANIO_DIR = BASE_DIR / "eshanio" / "hf_video_platform" / "frontend"
ESHANIO_INDEX = ESHANIO_DIR / "index.html"



@asynccontextmanager
async def lifespan(app: FastAPI):
    access_store.initialize()

    # Startup sequence
    stream_logger.info("SYSTEM", "=" * 60)
    stream_logger.info("SYSTEM", "24/7 Multi-Platform Live Streaming System (YouTube, Kick, Twitch, Nimo & TikTok) Starting...")
    stream_logger.info("SYSTEM", f"Server binding: http://{config.host}:{config.port}")
    stream_logger.info("SYSTEM", f"Video Source: {config.video_source}")
    stream_logger.info("SYSTEM", f"YouTube [Enabled: {config.youtube_enabled}]: {'Key Configured' if config.youtube_stream_key else 'No Key'}")
    stream_logger.info("SYSTEM", f"Kick    [Enabled: {config.kick_enabled}]: {'Key Configured' if config.kick_stream_key else 'No Key'}")
    stream_logger.info("SYSTEM", f"Twitch  [Enabled: {config.twitch_enabled}]: {'Key Configured' if config.twitch_stream_key else 'No Key'}")
    stream_logger.info("SYSTEM", f"Nimo    [Enabled: {config.nimo_enabled}]: {'Key Configured' if config.nimo_stream_key else 'No Key'}")
    stream_logger.info("SYSTEM", f"TikTok  [Enabled: {config.tiktok_enabled}]: {'Key Configured' if config.tiktok_stream_key else 'No Key'}")
    stream_logger.info("SYSTEM", "=" * 60)

    # Start the watchdog supervisor & memory hygiene
    watchdog.start_watchdog()
    start_memory_hygiene(interval_seconds=300)

    # Check for AUTO_START
    if config.auto_start:
        if config.youtube_stream_key or config.kick_stream_key or config.twitch_stream_key or config.nimo_stream_key or config.tiktok_stream_key:
            stream_logger.info("SYSTEM", "AUTO_START is enabled. Triggering immediate stream launch...")
            watchdog.request_start()
        else:
            stream_logger.warn("SYSTEM", "AUTO_START is true, but no stream keys are configured yet.")

    yield

    # Shutdown sequence
    stream_logger.info("SYSTEM", "System shutting down. Terminating stream processes...")
    stop_memory_hygiene()
    watchdog.stop_watchdog()
    watchdog.request_stop()
    stream_logger.info("SYSTEM", "Shutdown complete.")


app = FastAPI(
    title="24/7 Multi-Stream System (YouTube, Kick, TikTok)",
    description="Automated continuous video loop streamer to YouTube, Kick.com, and TikTok Live via FFmpeg",
    version="1.1.0",
    lifespan=lifespan
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_coop_header_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return response

# Register backend routes
app.include_router(router)
app.include_router(admin_router)
app.include_router(access_router)
app.include_router(catalog_router)
app.include_router(discord_router)
app.include_router(auth_router)
app.include_router(onion_router)
app.add_middleware(M3UServiceProxyMiddleware)
app.add_middleware(DisabledAccessRoutesMiddleware)
app.add_middleware(NoCacheForPrivateAPIMiddleware)
app.add_middleware(GeoAndClientRestrictionMiddleware)

# Mount static files and index routes for Eshanio Video Platform
if ESHANIO_DIR.exists():
    @app.get("/eshanio")
    @app.get("/eshanio/")
    @app.get("/eshanio/index.html")
    def serve_eshanio_root():
        return FileResponse(
            str(ESHANIO_INDEX),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/watch/{path:path}")
    @app.get("/eshanio/watch/{path:path}")
    def serve_watch_route(path: str = ""):
        return FileResponse(
            str(ESHANIO_INDEX),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


# Mount static files for the Web Panel UI
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def serve_frontend(request: Request):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"/eshanio/{query}", status_code=308)

    @app.get("/control")
    def serve_control_panel():
        return FileResponse(str(INDEX_FILE))

APP_ADS_TXT_CONTENT = "google.com, pub-3366068343218156, DIRECT, f08c47fec0942fa0\n"

@app.api_route("/app-ads.txt", methods=["GET", "HEAD"])
@app.api_route("/eshanio/app-ads.txt", methods=["GET", "HEAD"])
def serve_app_ads_txt():
    return Response(
        content=APP_ADS_TXT_CONTENT,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )

@app.api_route("/robots.txt", methods=["GET", "HEAD"])
@app.api_route("/eshanio/robots.txt", methods=["GET", "HEAD"])
def serve_robots_txt():
    robots_content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /app-ads.txt\n"
        "Allow: /eshanio/\n"
        "Allow: /watch/\n"
        "Allow: /video/\n"
        "Allow: /embed/\n"
        "Allow: /api/videos\n"
        "Allow: /api/cover/\n"
        "Allow: /sitemap.xml\n"
        "Allow: /video-sitemap.xml\n"
        "Allow: /eshanio/sitemap.xml\n"
        "Allow: /eshanio/video-sitemap.xml\n"
        "Disallow: /api/status\n\n"
        "Sitemap: https://eshansayhan-hotlink.hf.space/sitemap.xml\n"
        "Sitemap: https://eshansayhan-hotlink.hf.space/video-sitemap.xml\n"
        "Sitemap: https://eshansayhan-hotlink.hf.space/eshanio/sitemap.xml\n"
        "Sitemap: https://eshansayhan-hotlink.hf.space/eshanio/video-sitemap.xml\n"
    )
    return Response(
        content=robots_content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )

@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
@app.api_route("/video-sitemap.xml", methods=["GET", "HEAD"])
@app.api_route("/eshanio/sitemap.xml", methods=["GET", "HEAD"])
@app.api_route("/eshanio/video-sitemap.xml", methods=["GET", "HEAD"])
def serve_sitemap_xml(request: Request = None):
    candidates = [
        Path("eshanio/hf_video_platform/frontend/video-sitemap.xml"),
        Path("eshanio/hf_video_platform/video-sitemap.xml"),
        Path("eshanio/video-sitemap.xml"),
        Path("web/video-sitemap.xml"),
        Path("video-sitemap.xml"),
        Path("eshanio/hf_video_platform/frontend/sitemap.xml"),
        Path("eshanio/hf_video_platform/sitemap.xml"),
        Path("eshanio/sitemap.xml"),
        Path("web/sitemap.xml"),
        Path("sitemap.xml"),
    ]
    for p in candidates:
        if p.exists():
            try:
                xml_data = p.read_text(encoding="utf-8")
                return Response(
                    content=xml_data,
                    media_type="application/xml; charset=utf-8",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
            except Exception:
                pass

    fallback = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">\n'
        '  <url>\n'
        '    <loc>https://eshansayhan-hotlink.hf.space/eshanio/</loc>\n'
        '    <changefreq>daily</changefreq>\n'
        '    <priority>1.0</priority>\n'
        '  </url>\n'
        '</urlset>'
    )
    return Response(
        content=fallback,
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"},
    )

@app.api_route("/google{verification_id}.html", methods=["GET", "HEAD"])
@app.api_route("/eshanio/google{verification_id}.html", methods=["GET", "HEAD"])
def serve_google_verification(verification_id: str):
    filename = f"google{verification_id}.html"
    return Response(
        content=f"google-site-verification: {filename}\n",
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )

@app.api_route("/manifest.json", methods=["GET", "HEAD"])
@app.api_route("/eshanio/manifest.json", methods=["GET", "HEAD"])
def serve_manifest_json():
    manifest_data = {
        "name": "HFStream • Eshanio Video Platform",
        "short_name": "HFStream",
        "description": "24/7 Multi-Platform Film, Dizi & Canlı Yayın Platformu",
        "start_url": "/eshanio/?__theme=system",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#070a13",
        "theme_color": "#00e5b4",
        "icons": [
            {
                "src": "/app_icon.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    return Response(
        content=json.dumps(manifest_data),
        media_type="application/manifest+json; charset=utf-8",
        headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"}
    )

@app.api_route("/sw.js", methods=["GET", "HEAD"])
@app.api_route("/eshanio/sw.js", methods=["GET", "HEAD"])
def serve_service_worker():
    sw_code = """// HFStream Service Worker
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener('push', (e) => {
  const d = e.data ? e.data.json() : {};
  const t = d.title || 'HFStream • Yeni İçerik Eklendi!';
  const opt = {
    body: d.body || 'Yeni film ve dizileri keşfetmek için hemen tıklayın.',
    icon: '/app_icon.png',
    badge: '/app_icon.png',
    data: { url: d.url || '/eshanio/?__theme=system' }
  };
  e.waitUntil(self.registration.showNotification(t, opt));
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const u = e.notification.data?.url || '/eshanio/?__theme=system';
  e.waitUntil(clients.openWindow(u));
});
"""
    return Response(
        content=sw_code,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"}
    )

@app.api_route("/app_icon.png", methods=["GET", "HEAD"])
@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
def serve_app_icon():
    icon_path = BASE_DIR / "assets" / "watermark.png"
    if icon_path.exists():
        return FileResponse(str(icon_path), media_type="image/png")
    return Response(status_code=204)

# Mount static files for Eshanio Video Platform (fallback for assets and static files)
if ESHANIO_DIR.exists():
    app.mount("/eshanio", StaticFiles(directory=str(ESHANIO_DIR), html=True), name="eshanio")


# ========================================================
# SAFETENSORS HTTP 206 RANGE STREAM PROXY & COVER API
# ========================================================
HF_DATASET_REPO = os.getenv("HF_DATASET_REPO", "eshansayhan/movie")
HF_DATASET_REVISION = os.getenv("HF_DATASET_REVISION", "main")
HF_TOKEN = os.getenv("HF_TOKEN", "")
SAFETENSORS_DEFAULT_FILE = os.getenv("SAFETENSORS_DEFAULT_FILE", "")
SAFETENSORS_BASE_URL = (
    f"https://huggingface.co/datasets/{HF_DATASET_REPO}/resolve/"
    f"{quote(HF_DATASET_REVISION, safe='')}/"
)
SAFETENSORS_TREE_URL = (
    f"https://huggingface.co/api/datasets/{HF_DATASET_REPO}/tree/"
    f"{quote(HF_DATASET_REVISION, safe='')}?recursive=true&limit=1000"
)
_sf_files_cache = None
_sf_files_cache_at = 0.0
_sf_header_cache = {}


def _safetensors_headers():
    headers = {"User-Agent": "HFStreamServer"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    return headers


def _is_safe_safetensors_path(path):
    return (
        isinstance(path, str)
        and path.lower().endswith(".safetensors")
        and not path.startswith(("/", "\\"))
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


def discover_safetensors_files(force_refresh=False):
    global _sf_files_cache, _sf_files_cache_at
    if (
        not force_refresh
        and _sf_files_cache is not None
        and time.monotonic() - _sf_files_cache_at < 300
    ):
        return _sf_files_cache

    discovered = []
    next_url = SAFETENSORS_TREE_URL
    visited = set()
    while next_url and next_url not in visited:
        visited.add(next_url)
        req = urllib.request.Request(next_url, headers=_safetensors_headers())
        with urllib.request.urlopen(req, timeout=20) as resp:
            tree = json.load(resp)
            link_header = resp.headers.get("Link", "")
        if not isinstance(tree, list):
            raise ValueError("Hugging Face dataset tree response must be a list")
        discovered.extend(
            item["path"]
            for item in tree
            if isinstance(item, dict)
            and _is_safe_safetensors_path(item.get("path"))
            and item.get("type") == "file"
            and isinstance(item.get("size"), int)
            and item["size"] >= 8
        )
        next_match = re.search(r'<([^>]+)>;\s*rel="?next"?', link_header)
        next_url = urljoin(next_url, next_match.group(1)) if next_match else None

    _sf_files_cache = sorted(set(discovered))
    _sf_files_cache_at = time.monotonic()
    return _sf_files_cache


def _resolve_safetensors_file(source_file):
    files = discover_safetensors_files()
    if source_file:
        if source_file not in files:
            raise HTTPException(status_code=404, detail="Safetensors file not found in the dataset")
        return source_file
    if SAFETENSORS_DEFAULT_FILE:
        if SAFETENSORS_DEFAULT_FILE not in files:
            raise HTTPException(status_code=404, detail="Configured Safetensors file is not in the dataset")
        return SAFETENSORS_DEFAULT_FILE
    if len(files) == 1:
        return files[0]
    if not files:
        raise HTTPException(status_code=404, detail="No Safetensors files were found in the dataset")
    raise HTTPException(
        status_code=400,
        detail="source_file is required when the dataset contains multiple Safetensors files",
    )


def safetensors_file_url(source_file):
    return SAFETENSORS_BASE_URL + quote(source_file, safe="/")


def get_safetensors_index(source_file=""):
    source_file = _resolve_safetensors_file(source_file)
    cached = _sf_header_cache.get(source_file)
    if cached is not None and time.monotonic() - cached[2] < 300:
        return source_file, cached[0], cached[1]

    source_url = safetensors_file_url(source_file)
    req = urllib.request.Request(
        source_url,
        headers={**_safetensors_headers(), "Range": "bytes=0-7"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        len_buf = resp.read(8)
    if len(len_buf) != 8:
        raise HTTPException(status_code=502, detail=f"Could not read Safetensors header for {source_file}")
    header_len = int.from_bytes(len_buf, "little")
    if not 0 < header_len <= 64 * 1024 * 1024:
        raise HTTPException(status_code=502, detail=f"Invalid Safetensors header size for {source_file}")
    req = urllib.request.Request(
        source_url,
        headers={
            **_safetensors_headers(),
            "Range": f"bytes=8-{8 + header_len - 1}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        json_bytes = resp.read(header_len)
    if len(json_bytes) != header_len:
        raise HTTPException(status_code=502, detail=f"Incomplete Safetensors header for {source_file}")
    header_obj = json.loads(json_bytes.decode("utf-8"))
    if not isinstance(header_obj, dict):
        raise HTTPException(status_code=502, detail=f"Invalid Safetensors header for {source_file}")
    data_start = 8 + header_len
    _sf_header_cache[source_file] = (header_obj, data_start, time.monotonic())
    return source_file, header_obj, data_start


async def _get_safetensors_index_async(source_file=""):
    return await run_in_threadpool(get_safetensors_index, source_file)


def resolve_tensor_name(raw_name: str, header_keys: dict, prefix: str = "video") -> str:
    # 1. Eğer raw_name doğrudan istenen prefix ile başlıyorsa ve mevcutsa
    if prefix and raw_name.startswith(f"{prefix}_") and raw_name in header_keys:
        return raw_name

    # 2. Sayısal indeks varsa, istenen prefix ile eşleştir (örn. video_0000 -> cover_0000)
    if prefix:
        m = re.search(r"\d+", raw_name)
        if m:
            num = int(m.group(0))
            for cand in (f"{prefix}_{num:04d}", f"{prefix}_{num}", f"{prefix}{num}"):
                if cand in header_keys:
                    return cand

    # 3. Doğrudan eşleşme kontrolü
    if raw_name in header_keys:
        return raw_name
    return raw_name

@app.api_route("/api/stream/{tensor_name}", methods=["GET", "HEAD", "OPTIONS"])
@app.api_route("/stream", methods=["GET", "HEAD", "OPTIONS"])
async def stream_safetensors_video(
    tensor_name: str = "",
    tensor: str = "",
    source_file: str = "",
    quality: str = "",
    request: Request = None,
):
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Content-Type, Accept-Encoding",
        "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
    }
    
    if request and request.method == "OPTIONS":
        return Response(status_code=204, headers=cors_headers)

    # §7 dost.md: playback must be verified server-side FIRST before loading file indexes.
    # Kural: Yalnızca mobil + Türkiye (veya Admin) ve yetkili kullanıcı video byte'larını alabilir.
    if request:
        cfg = load_embed_config()
        if cfg.get("api_enabled", True):
            from app.admin_service import _admin_session
            from app.routers.auth import is_mobile_request
            from app.routers.access import _active_access

            is_admin = _admin_session(request) is not None
            if not is_admin:
                if not is_mobile_request(request):
                    return JSONResponse(status_code=403, content={"allowed": False, "detail": "Masaüstü oynatma engellendi"}, headers=cors_headers)

                country = (
                    getattr(request.state, "content_country", None)
                    or request.headers.get("cf-ipcountry")
                    or request.headers.get("x-country")
                    or ""
                ).upper()
                if country and country != "TR":
                    return JSONResponse(status_code=403, content={"allowed": False, "detail": "Yurt dışından oynatma engellendi"}, headers=cors_headers)

            content_cfg = cfg.get("content_access", {})
            if content_cfg.get("require_authenticated_session", True) and not is_admin:
                authenticated = _active_access(request) is not None
                if not authenticated:
                    return JSONResponse(status_code=403, content={"allowed": False, "detail": "Giriş yapmanız gerekmektedir"}, headers=cors_headers)

    raw_name = tensor_name or tensor or "video_0000"
    source_file, header_obj, data_start = await _get_safetensors_index_async(source_file)
    source_url = safetensors_file_url(source_file)
    t_name = resolve_tensor_name(raw_name, header_obj, "video")
    t_info = header_obj.get(t_name)
    if not t_info:
        raise HTTPException(status_code=404, detail=f"Tensor {raw_name} not found")
    
    # Çoklu kalite tensörü kontrolü (video_0000_720p, video_720p vb.)
    quality_clean = (quality or "").lower().strip()
    if quality_clean and quality_clean not in ("1080p", "auto"):
        for ck in (f"{t_name}_{quality_clean}", f"{raw_name}_{quality_clean}", f"video_{quality_clean}"):
            if ck in header_obj and isinstance(header_obj[ck], dict) and "data_offsets" in header_obj[ck]:
                t_name = ck
                t_info = header_obj[ck]
                break

    offsets = t_info["data_offsets"]
    tensor_size = offsets[1] - offsets[0]
    abs_start = data_start + offsets[0]

    
    if request and request.method not in ("OPTIONS", "HEAD"):
        try:
            access_store.record_video_view(f"{source_file}::{t_name}", t_name)
        except Exception:
            pass
    if request and request.method == "HEAD":
        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(tensor_size),
            "Accept-Ranges": "bytes",
            **cors_headers
        }
        return Response(status_code=200, headers=headers)
    
    range_header = request.headers.get("range") if request else None
    
    # YouTube / Netflix tarzı adaptif veri tasarrufu tampon boyutlandırması
    if quality_clean in ("144p", "240p"):
        MAX_CHUNK = 512 * 1024       # 512 KB (Veri Tasarrufu Modu)
    elif quality_clean == "480p":
        MAX_CHUNK = 1024 * 1024      # 1 MB SD
    elif quality_clean == "720p":
        MAX_CHUNK = 2 * 1024 * 1024  # 2 MB HD
    else:
        MAX_CHUNK = 4 * 1024 * 1024  # 4 MB Full 1080p Ultra HD (Hafıza güvenliği)
    
    if not range_header:
        start = 0
        end = min(MAX_CHUNK - 1, tensor_size - 1)
        status_code = 206
    else:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if not m:
            raise HTTPException(status_code=416, detail="Invalid Range Header")
        start = int(m.group(1))
        if m.group(2):
            requested_end = int(m.group(2))
            end = min(requested_end, start + MAX_CHUNK - 1, tensor_size - 1)
        else:
            end = min(start + MAX_CHUNK - 1, tensor_size - 1)
        status_code = 206
    
    if start >= tensor_size:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")
    if end < start:
        end = start
    
    chunk_length = end - start + 1
    target_start = abs_start + start
    target_end = abs_start + end
    
    def iter_stream():
        try:
            hf_req = urllib.request.Request(
                source_url,
                headers={
                    **_safetensors_headers(),
                    "Range": f"bytes={target_start}-{target_end}",
                },
            )
            with urllib.request.urlopen(hf_req, timeout=30) as resp:
                while chunk := resp.read(64 * 1024):
                    # Android / Chromium HEVC MediaCodec compatibility:
                    # Chromium demuxer rejects FourCC 'hev1' but accepts 'hvc1' when hvcC box is present.
                    if b"hev1" in chunk:
                        chunk = chunk.replace(b"hev1", b"hvc1")
                    yield chunk
        except Exception:
            return

    resp_headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length),
        "Content-Range": f"bytes {start}-{end}/{tensor_size}",
        **cors_headers
    }
    
    return StreamingResponse(iter_stream(), status_code=status_code, headers=resp_headers)


@app.api_route("/api/download/{tensor_name}", methods=["GET", "HEAD", "OPTIONS"])
@app.api_route("/download/{tensor_name}", methods=["GET", "HEAD", "OPTIONS"])
@app.api_route("/api/download", methods=["GET", "HEAD", "OPTIONS"])
@app.api_route("/download", methods=["GET", "HEAD", "OPTIONS"])
async def download_safetensors_video(
    tensor_name: str = "",
    tensor: str = "",
    source_file: str = "",
    quality: str = "",
    title: str = "",
    url: str = "",
    request: Request = None,
):
    """
    Sadece video indirenler için özel filigran (watermark) gömülü video indirme servisi.
    Online oynatıcı (stream) filigransız temiz kalır; indirilen dosyaya otomatik gömülür.
    """
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Content-Type, Accept-Encoding",
        "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, Content-Range, Accept-Ranges",
    }

    if request and request.method == "OPTIONS":
        return Response(status_code=204, headers=cors_headers)

    raw_name = tensor_name or tensor or "video_0000"
    clean_title = re.sub(r'[/\\?%*:|"<>]+', '_', title or raw_name).strip()
    if not clean_title.lower().endswith(".mp4"):
        clean_title += ".mp4"

    # Filigran görselini belirle
    watermark_path = None
    try:
        from app.watermark_asset import ensure_watermark_image
        watermark_path = ensure_watermark_image()
    except Exception:
        pass
    if not watermark_path or not watermark_path.exists():
        for cand in [
            BASE_DIR / "assets" / "watermark.png",
            BASE_DIR / "app" / "assets" / "watermark.png",
            Path(__file__).resolve().parent / "assets" / "watermark.png",
            BASE_DIR / "eshanio" / "assets" / "watermark.png",
            BASE_DIR / "eshanio" / "hf_video_platform" / "frontend" / "assets" / "watermark.png",
        ]:
            if cand.exists() and cand.stat().st_size > 0:
                watermark_path = cand
                break

    cache_dir = BASE_DIR / "cache" / "watermarked"
    raw_dir = BASE_DIR / "cache" / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    safe_sf = re.sub(r"[^a-zA-Z0-9_-]", "_", source_file or "default")
    safe_tn = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
    safe_q = re.sub(r"[^a-zA-Z0-9_-]", "_", quality or "orig")
    cache_key = f"{safe_sf}_{safe_tn}_{safe_q}"
    cached_file = cache_dir / f"{cache_key}_watermarked.mp4"

    # 1. Önceden filigranlanmış ve diskte mevcutsa doğrudan FileResponse ile sun
    if cached_file.exists() and cached_file.stat().st_size > 1024:
        if request and request.method == "HEAD":
            return Response(
                status_code=200,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(cached_file.stat().st_size),
                    "Content-Disposition": f'attachment; filename="{clean_title}"',
                    "Accept-Ranges": "bytes",
                    **cors_headers,
                },
            )
        return FileResponse(
            path=str(cached_file),
            media_type="video/mp4",
            filename=clean_title,
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}"',
                **cors_headers,
            },
        )

    # 2. Kaynak videoyu çözümle
    raw_video_path = None
    local_vid = BASE_DIR / "videos" / "video.mp4"

    if url and url.startswith(("http://", "https://")):
        raw_video_path = raw_dir / f"url_{abs(hash(url))}.mp4"
        if not raw_video_path.exists() or raw_video_path.stat().st_size < 1024:
            tmp_url = raw_dir / f"url_{abs(hash(url))}.tmp"
            def _fetch_url():
                req = urllib.request.Request(url, headers={"User-Agent": "HFStreamServer"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_url, "wb") as f_out:
                    while chunk := resp.read(128 * 1024):
                        f_out.write(chunk)
                if tmp_url.exists():
                    tmp_url.replace(raw_video_path)
            await run_in_threadpool(_fetch_url)
    else:
        try:
            source_file, header_obj, data_start = await _get_safetensors_index_async(source_file)
            source_url = safetensors_file_url(source_file)
            t_name = resolve_tensor_name(raw_name, header_obj, "video")
            
            # Kalite seçimi
            quality_clean = (quality or "").lower().strip()
            if quality_clean and quality_clean not in ("1080p", "auto"):
                for ck in (f"{t_name}_{quality_clean}", f"{raw_name}_{quality_clean}", f"video_{quality_clean}"):
                    if ck in header_obj and isinstance(header_obj[ck], dict) and "data_offsets" in header_obj[ck]:
                        t_name = ck
                        break

            t_info = header_obj.get(t_name)
            if not t_info:
                if local_vid.exists():
                    raw_video_path = local_vid
                else:
                    raise HTTPException(status_code=404, detail=f"Tensor {raw_name} not found")
            else:
                offsets = t_info["data_offsets"]
                tensor_size = offsets[1] - offsets[0]
                abs_start = data_start + offsets[0]
                abs_end = data_start + offsets[1] - 1
                
                raw_video_path = raw_dir / f"{safe_sf}_{t_name}_raw.mp4"
                if not raw_video_path.exists() or raw_video_path.stat().st_size != tensor_size:
                    raw_tmp = raw_dir / f"{safe_sf}_{t_name}_raw_{os.getpid()}.tmp"
                    req = urllib.request.Request(
                        source_url,
                        headers={
                            **_safetensors_headers(),
                            "Range": f"bytes={abs_start}-{abs_end}",
                        },
                    )
                    def _fetch_tensor():
                        with urllib.request.urlopen(req, timeout=60) as resp, open(raw_tmp, "wb") as f_out:
                            while chunk := resp.read(128 * 1024):
                                if b"hev1" in chunk:
                                    chunk = chunk.replace(b"hev1", b"hvc1")
                                f_out.write(chunk)
                        if raw_tmp.exists():
                            raw_tmp.replace(raw_video_path)
                    await run_in_threadpool(_fetch_tensor)
        except Exception:
            if local_vid.exists():
                raw_video_path = local_vid
            else:
                raise HTTPException(status_code=404, detail="Video source could not be resolved for download")

    if request and request.method == "HEAD":
        return Response(
            status_code=200,
            headers={
                "Content-Type": "video/mp4",
                "Content-Disposition": f'attachment; filename="{clean_title}"',
                "Accept-Ranges": "bytes",
                **cors_headers,
            },
        )

    # 3. FFmpeg ve filigran mevcutsa videoya otomatik filigran göm
    if watermark_path and raw_video_path and raw_video_path.exists():
        filter_str = "[1:v][0:v]scale2ref=w=trunc(iw/2)*2:h=trunc(ih/2)*2[wm][base];[base][wm]overlay=0:0,format=yuv420p"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_video_path),
            "-i", str(watermark_path),
            "-filter_complex", filter_str,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-f", "mp4",
            "pipe:1"
        ]

        cache_tmp = cache_dir / f"{cache_key}_tmp_{os.getpid()}_{int(time.time())}.mp4"

        def iter_watermarked_stream():
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=64 * 1024,
            )
            f_cache = None
            try:
                f_cache = open(cache_tmp, "wb")
            except Exception:
                pass
            try:
                while True:
                    chunk = proc.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    if f_cache:
                        f_cache.write(chunk)
                    yield chunk
                proc.wait()
                if f_cache:
                    f_cache.close()
                    f_cache = None
                    if proc.returncode == 0 and cache_tmp.exists() and cache_tmp.stat().st_size > 1024:
                        cache_tmp.replace(cached_file)
                    elif cache_tmp.exists():
                        cache_tmp.unlink(missing_ok=True)
            except Exception:
                if proc.poll() is None:
                    proc.kill()
                if f_cache:
                    f_cache.close()
                if cache_tmp.exists():
                    cache_tmp.unlink(missing_ok=True)
                raise

        resp_headers = {
            "Content-Type": "video/mp4",
            "Content-Disposition": f'attachment; filename="{clean_title}"',
            **cors_headers,
        }
        return StreamingResponse(iter_watermarked_stream(), media_type="video/mp4", headers=resp_headers)

    # FFmpeg yoksa orijinal ham videoyu doğrudan ek olarak sun
    if raw_video_path and raw_video_path.exists():
        return FileResponse(
            path=str(raw_video_path),
            media_type="video/mp4",
            filename=clean_title,
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}"',
                **cors_headers,
            },
        )

    raise HTTPException(status_code=404, detail="Video could not be downloaded")


def generate_fallback_cover_svg(title: str = "Video") -> bytes:
    escaped_title = (title or "HFStream").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:40]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600" width="400" height="600">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#070a13"/>
      <stop offset="50%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#020617"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00e5b4"/>
      <stop offset="100%" stop-color="#00b4d8"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#g)"/>
  <rect x="20" y="20" width="360" height="560" fill="none" stroke="rgba(255,255,255,0.08)" rx="16" stroke-width="1.5"/>
  <circle cx="200" cy="240" r="54" fill="rgba(0,229,180,0.08)" stroke="url(#accent)" stroke-width="2"/>
  <path d="M192 218 L218 240 L192 262 Z" fill="url(#accent)"/>
  <text x="200" y="360" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#ffffff" text-anchor="middle">{escaped_title}</text>
  <text x="200" y="395" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700" fill="#38bdf8" letter-spacing="3" text-anchor="middle">1080P FULL HD</text>
  <rect x="130" y="430" width="140" height="28" fill="rgba(0,229,180,0.12)" stroke="rgba(0,229,180,0.3)" rx="14"/>
  <text x="200" y="449" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#00e5b4" text-anchor="middle">HFSTREAM</text>
</svg>"""
    return svg.encode("utf-8")


@app.api_route("/api/cover/{tensor_name}", methods=["GET", "HEAD"])
async def serve_safetensors_cover(tensor_name: str, source_file: str = ""):
    t_info = None
    header_obj = {}
    data_start = 0
    try:
        source_file, header_obj, data_start = await _get_safetensors_index_async(source_file)
        c_name = resolve_tensor_name(tensor_name, header_obj, "cover")
        t_info = header_obj.get(c_name)
        if not t_info or "data_offsets" not in t_info:
            # Fallback: herhangi bir cover tensörü ara
            c_cand = [k for k in header_obj.keys() if "cover" in k.lower()]
            if c_cand:
                t_info = header_obj[c_cand[0]]
                c_name = c_cand[0]
    except Exception:
        t_info = None

    if not t_info or "data_offsets" not in t_info:
        # Kapak tensörü bulunamadığında şık dinamik SVG poster dön
        display_title = (Path(source_file).stem if source_file else tensor_name).replace("_", " ").replace(".", " ").title()
        svg_content = generate_fallback_cover_svg(display_title)
        return Response(
            content=svg_content,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"}
        )

    offsets = t_info["data_offsets"]
    c_size = offsets[1] - offsets[0]

    # Güvenlik: Kapak resmi boyutu 5 MB'tan büyük olamaz (videolar kapak olarak okunamaz)
    if c_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=404, detail="Geçersiz kapak resmi tensörü")

    c_start = data_start + offsets[0]
    c_end = data_start + offsets[1] - 1

    # Yerel disk önbelleği (Hızlı milisaniyelik yanıt)
    cache_dir = BASE_DIR / "cache" / "covers"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_sf = re.sub(r"[^\w\-.]", "_", source_file)
    cache_file = cache_dir / f"{safe_sf}_{c_name}.webp"

    if cache_file.exists() and cache_file.stat().st_size == c_size:
        return FileResponse(
            str(cache_file),
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=604800, immutable", "Access-Control-Allow-Origin": "*"}
        )

    hf_req = urllib.request.Request(
        safetensors_file_url(source_file),
        headers={
            **_safetensors_headers(),
            "Range": f"bytes={c_start}-{c_end}",
        },
    )
    def read_cover():
        with urllib.request.urlopen(hf_req, timeout=15) as resp:
            data = resp.read()
        try:
            with open(cache_file, "wb") as f_out:
                f_out.write(data)
        except Exception:
            pass
        return data

    cover_data = await run_in_threadpool(read_cover)
    return Response(
        content=cover_data,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=604800, immutable", "Access-Control-Allow-Origin": "*"}
    )


@app.get("/api/subtitle/{tensor_name}")
async def serve_safetensors_subtitle(
    tensor_name: str,
    lang: str = "tr",
    source_file: str = "",
):
    """
    Safetensors içinde gömülü olan veya dataset üzerindeki .srt / .vtt altyazılarını
    otomatik algılar, Türkçe karakter desteğiyle (UTF-8 / CP1254) döner.
    """
    try:
        source_file, header_obj, data_start = await _get_safetensors_index_async(source_file)
    except Exception:
        raise HTTPException(status_code=404, detail="Safetensors index bulunamadı")

    target_lang = lang.lower().strip()
    if target_lang not in ("tr", "en"):
        target_lang = "tr"

    num_match = re.search(r"\d+", tensor_name)
    num_str = f"{int(num_match.group(0)):04d}" if num_match else ""

    candidates = [
        f"sub_{target_lang}_{num_str}" if num_str else "",
        f"subtitle_{target_lang}_{num_str}" if num_str else "",
        f"sub_{num_str}_{target_lang}" if num_str else "",
        f"{tensor_name}_{target_lang}",
        f"{tensor_name}_{target_lang}.vtt",
        f"{tensor_name}_{target_lang}.srt",
        f"sub_{target_lang}",
        f"subtitle_{target_lang}",
        f"subtitles_{target_lang}",
        f"{target_lang}.vtt",
        f"{target_lang}.srt",
    ]
    candidates = [c for c in candidates if c]

    found_key = None
    for cand in candidates:
        if cand in header_obj:
            found_key = cand
            break

    if not found_key and num_str:
        for k in header_obj.keys():
            k_lower = k.lower()
            if num_str in k_lower and target_lang in k_lower and any(w in k_lower for w in ("sub", "caption", "srt", "vtt")):
                found_key = k
                break

    # Metadata araması
    meta_dict = header_obj.get("__metadata__", {})
    if isinstance(meta_dict, dict):
        meta_candidates = [
            f"subtitle_{target_lang}_{num_str}" if num_str else "",
            f"sub_{target_lang}_{num_str}" if num_str else "",
            f"{tensor_name}_{target_lang}",
            f"subtitles_{target_lang}",
            f"subtitle_{target_lang}",
            f"sub_{target_lang}",
        ]
        for mc in meta_candidates:
            if mc and mc in meta_dict and isinstance(meta_dict[mc], str):
                sub_text = meta_dict[mc]
                return Response(
                    content=sub_text,
                    media_type="text/vtt; charset=utf-8",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                    },
                )

    if not found_key:
        raise HTTPException(status_code=404, detail=f"Gömülü {target_lang.upper()} altyazı bulunamadı")

    t_info = header_obj.get(found_key)
    if not t_info or "data_offsets" not in t_info:
        raise HTTPException(status_code=404, detail="Geçersiz altyazı tensörü")

    offsets = t_info["data_offsets"]
    s_start = data_start + offsets[0]
    s_end = data_start + offsets[1] - 1

    hf_req = urllib.request.Request(
        safetensors_file_url(source_file),
        headers={
            **_safetensors_headers(),
            "Range": f"bytes={s_start}-{s_end}",
        },
    )

    def read_sub():
        with urllib.request.urlopen(hf_req, timeout=15) as resp:
            return resp.read()

    sub_bytes = await run_in_threadpool(read_sub)

    # Türkçe karakter desteği: UTF-8 -> CP1254 (Windows-1254) -> ISO-8859-9
    try:
        sub_text = sub_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            sub_text = sub_bytes.decode("cp1254")
        except UnicodeDecodeError:
            sub_text = sub_bytes.decode("iso-8859-9", errors="replace")

    # Eğer SRT ise ve WEBVTT başlığı yoksa otomatik WebVTT standardına çevir
    if not sub_text.lstrip().startswith("WEBVTT"):
        vtt_body = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", sub_text)
        sub_text = "WEBVTT\n\n" + vtt_body

    return Response(
        content=sub_text,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


__all__ = [
    "app",
    "discover_safetensors_files",
    "get_safetensors_index",
    "stream_safetensors_video",
    "download_safetensors_video",
    "serve_safetensors_cover",
    "serve_safetensors_subtitle",
    "resolve_tensor_name",
    "safetensors_file_url",
    "list_all_video_apis",
    "get_single_video_api",
    "serve_embed_player",
    "get_embed_configuration",
    "update_embed_configuration",
    "serve_monetization_config",
    "serve_mesh_cluster_map",
    "access_identity",
    "login_with_access_code",
    "logout_access",
    "get_accessible_videos",
    "stream_access_video",
    "download_access_video",
    "StreamHeartbeatRequest",
    "handle_stream_heartbeat",
    "login_admin_with_password",
    "finish_admin_discord_login",
    "logout_admin",
    "get_admin_video_catalog",
    "get_admin_access_settings",
    "update_admin_access_settings",
    "revoke_admin_access_code",
    "_discord_api_request",
    "_verify_discord_interaction",
    "handle_discord_interactions",
    "CustomCodeRequest",
    "AnnounceRequest",
    "ReportSubmitRequest",
    "BanClientRequest",
    "get_admin_analytics",
    "generate_admin_access_code",
    "generate_custom_access_code",
    "admin_announce_video",
    "submit_issue_report",
    "get_admin_reports",
    "resolve_admin_report",
    "delete_admin_report",
    "cleanup_admin_codes",
    "get_admin_banned_clients",
    "add_admin_banned_client",
    "remove_admin_banned_client",
    "get_admin_access_logs",
    "clear_admin_access_logs",
    "load_embed_config",
    "save_embed_config",
    "parse_video_metadata",
    "EMBED_CONFIG_FILE",
    "EMBED_HTML_FILE",
]
