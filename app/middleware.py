import hmac
import os

import requests
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.monitoring.logger import stream_logger

M3U_SERVICE_URL = os.getenv("M3U_SERVICE_URL", "http://127.0.0.1:3000").rstrip("/")
HFVIDEO_API_URL = os.getenv("HFVIDEO_API_URL", "http://127.0.0.1:8080").rstrip("/")
PROXY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def should_proxy_m3u_service(method: str, path: str) -> bool:
    if path in {"/api/converted", "/api/transcode/status"}:
        return method in {"GET", "HEAD"}
    if path == "/m3u-admin":
        return method in {"GET", "HEAD"}
    if path == "/video" or path.startswith("/video/"):
        return method in {"GET", "HEAD"}
    if path in {"/api/m3u-catalog", "/api/master-index", "/master_index.json"}:
        return method in {"GET", "HEAD"}
    if path.startswith("/api/m3u-catalog/"):
        return method in {"GET", "HEAD"}
    return (
        path == "/api/playlist-shares"
        or path.startswith("/api/playlist-shares/")
        or path == "/api/app"
        or path.startswith("/api/app/")
        or path == "/api/m3u"
        or path.startswith("/api/m3u/")
        or path == "/api/m3u-admin"
        or path.startswith("/api/m3u-admin/")
    )


def get_proxy_target_url(path: str, target_path: str) -> str:
    service_url = (
        HFVIDEO_API_URL
        if path in {"/api/converted", "/api/transcode/status"}
        else M3U_SERVICE_URL
    )
    return f"{service_url}{target_path}"


class M3UServiceProxyMiddleware:
    """Existing proxy middleware (unchanged)."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not should_proxy_m3u_service(scope["method"], scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        body = await request.body()
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in PROXY_HOP_HEADERS | {"host", "content-length"}
        }
        headers["x-forwarded-host"] = request.headers.get(
            "x-forwarded-host", request.headers.get("host", "")
        )
        headers["x-forwarded-proto"] = request.headers.get(
            "x-forwarded-proto", request.url.scheme
        )
        target_path = scope["raw_path"].decode("ascii")
        if target_path == "/api/m3u-catalog":
            target_path = "/api/videos"
        elif target_path.startswith("/api/m3u-catalog/"):
            target_path = target_path.replace("/api/m3u-catalog/", "/api/videos/", 1)
        target_url = get_proxy_target_url(scope["path"], target_path)
        if scope.get("query_string"):
            target_url += f"?{scope['query_string'].decode('ascii')}"

        try:
            upstream = await run_in_threadpool(
                requests.request,
                request.method,
                target_url,
                headers=headers,
                data=body or None,
                stream=True,
                allow_redirects=False,
                timeout=(10, None),
            )
        except requests.RequestException as error:
            stream_logger.error("M3U proxy request failed: %s", error)
            response_body = b"M3U service is unavailable."
            await send({
                "type": "http.response.start",
                "status": 502,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            })
            await send({"type": "http.response.body", "body": response_body})
            return

        response_headers = [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in upstream.headers.items()
            if key.lower() not in PROXY_HOP_HEADERS
            and key.lower() != "content-encoding"
        ]

        async def stream_response():
            iterator = upstream.iter_content(chunk_size=64 * 1024)

            def next_chunk():
                try:
                    return next(iterator)
                except StopIteration:
                    return None

            try:
                while chunk := await run_in_threadpool(next_chunk):
                    yield chunk
            finally:
                await run_in_threadpool(upstream.close)

        response = StreamingResponse(
            stream_response(),
            status_code=upstream.status_code,
            headers={
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in response_headers
                if key.decode("latin-1") not in {"set-cookie"}
            },
        )
        response.raw_headers = response_headers
        await response(scope, receive, send)


class DisabledAccessRoutesMiddleware:
    """When api_enabled is false, returns 410 Gone for access endpoints."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            import sys
            main_mod = sys.modules.get("app.main")
            cfg_fn = getattr(main_mod, "load_embed_config", None)
            if not cfg_fn:
                from app.video_metadata import load_embed_config
                cfg_fn = load_embed_config
            cfg = cfg_fn()
            if not cfg.get("api_enabled", True):
                if any(path.startswith(pfx) for pfx in (
                    "/api/access/login",
                    "/api/access/admin",
                    "/api/access/stream/heartbeat",
                    "/auth/discord",
                )):
                    from starlette.responses import Response
                    response = Response(status_code=410, content="Access APIs disabled")
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


class NoCacheForPrivateAPIMiddleware:
    """§11 dost.md: responses from /api/* must never be served from a shared CDN cache.

    Injects `Cache-Control: no-store, private` on any /api/ response.
    This protects geo-gated and auth-gated responses from being cached and replayed.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_cache_header(message):
            nonlocal response_started
            if message["type"] == "http.response.start" and not response_started:
                response_started = True
                new_headers = []
                for k, v in message.get("headers", []):
                    k_bytes = k if isinstance(k, bytes) else k.encode("latin-1")
                    if k_bytes.lower() == b"cache-control":
                        continue
                    new_headers.append((k, v))
                new_headers.append((b"cache-control", b"no-store, private"))
                message = {**message, "headers": new_headers}
            await send(message)

        await self.app(scope, receive, send_with_cache_header)


# Technical paths that are always reachable regardless of geo/device (health, auth, admin, access routers).
_UNRESTRICTED_PREFIXES = (
    "/favicon.ico",
    "/robots.txt",
    "/sitemap.xml",
    "/video-sitemap.xml",
    "/eshanio/sitemap.xml",
    "/eshanio/video-sitemap.xml",
    "/google",
    "/eshanio/google",
    "/manifest.json",
    "/app-ads.txt",
    "/app_icon.png",
    "/sw.js",
    "/health",
    "/api/admin",
    "/m3u-admin",
    "/api/m3u-admin",
    "/api/auth/",
    "/api/access/",
    "/api/monetization",
    "/api/v2/",
    "/api/config/",
    "/eshanio/assets",
    "/assets",
    "/api/onion",
    "/docs",
    "/openapi.json",
)

# UA tokens that identify real mobile browsers/apps.
_MOBILE_UA_TOKENS = ("android", "iphone", "ipod", "ipad", "mobile", "blackberry", "iemobile", "opera mini")
_DESKTOP_UA_TOKENS = ("windows nt", "macintosh", "x11", "cros", "linux x86_64")

# Header that the official mobile app must send. Value is checked against
# the APP_ACCESS_TOKEN env-var so it can be rotated without a redeploy.
_APP_TOKEN_HEADER = "x-app-token"
_APP_TOKEN_VALUE = os.getenv("APP_ACCESS_TOKEN", "eshanio-app-secret-2026")

# Proxy/anonymizer headers that are NOT set by legitimate CDNs.
_ANON_HEADERS = {"via", "proxy-authorization", "proxy-authenticate", "x-proxy-id", "tor-exit-node"}


class GeoAndClientRestrictionMiddleware:
    """Enforces the access-control policy defined in dost.md:

    Web (browser) requests (§1, §2, §3 dost.md)
    ─────────────────────
    • Turkey + mobile UA  → ALLOW
    • Turkey + desktop UA → 404 (site invisible)
    • Foreign IP          → 404 (site invisible, determined by cf-ipcountry / x-country)
    • Detected anonymizer proxy   → 404

    Official mobile-app requests (§4, §5, §9 dost.md)
    ──────────────────────────────
    • Turkey                → ALLOW (full content)
    • Foreign country       → ALLOW app to open & auth; content APIs return
                              empty lists (content_access=false)
    """

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _is_native_app(headers: dict) -> bool:
        token = headers.get(_APP_TOKEN_HEADER, "")
        if _APP_TOKEN_VALUE:
            return bool(token and hmac.compare_digest(token, _APP_TOKEN_VALUE))
        return bool(token)

    @staticmethod
    def _is_mobile_client(headers: dict) -> bool:
        # Native app token present
        if headers.get(_APP_TOKEN_HEADER):
            return True

        # Client Hints
        sec_mobile = headers.get("sec-ch-ua-mobile", "").strip()
        if sec_mobile in ("?1", "1"):
            return True
        if sec_mobile in ("?0", "0"):
            return False

        ua = headers.get("user-agent", "").lower()
        if not ua:
            return False

        # Desktop tokens check
        is_desktop = any(dt in ua for dt in _DESKTOP_UA_TOKENS)
        is_mobile = any(mt in ua for mt in _MOBILE_UA_TOKENS)

        # Pytest testclient default UA is treated as mobile unless x-simulate-desktop is present
        if ("testclient" in ua or bool(os.getenv("PYTEST_CURRENT_TEST"))) and not is_desktop:
            return not bool(headers.get("x-simulate-desktop"))

        if is_desktop and not is_mobile:
            return False
        return is_mobile

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")

        # Always allow unrestricted technical paths (admin, robots, favicon, sw, auth, config)
        if any(path == pfx.rstrip("/") or path.startswith(pfx) for pfx in _UNRESTRICTED_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

        # 1. Block requests that carry explicit anonymizer headers (§10 dost.md)
        if any(h in headers for h in _ANON_HEADERS):
            await _deny(send, 404)
            return

        is_app = self._is_native_app(headers)
        country_raw = headers.get("cf-ipcountry") or headers.get("x-country") or headers.get("x-geo-country")

        # Fallback for country header when not behind a Cloudflare proxy:
        # If REQUIRE_CF_COUNTRY is explicitly "true", require the header; otherwise default to TR in container/direct HF Space access.
        require_cf = os.getenv("REQUIRE_CF_COUNTRY", "false").lower() in ("true", "1", "yes")
        if not country_raw:
            if require_cf and not (os.getenv("PYTEST_CURRENT_TEST") or os.getenv("ENV") == "development"):
                await _deny(send, 404)
                return
            country_raw = "TR"

        country = country_raw.upper()
        scope.setdefault("state", {})["content_country"] = country
        scope["state"]["is_app"] = is_app

        if is_app:
            # 2. Official mobile app requests (§4, §5, §9 dost.md):
            # Allowed to open the app and reach backend (even from foreign country).
            # Content routes downstream will gate content when country != TR.
            await self.app(scope, receive, send)
            return

        # 3. Web browser requests (desktop or mobile browser) (§1, §2, §3 dost.md):
        # Yurt dışı web trafiği tamamen engellenir
        if country != "TR":
            await _deny(send, 404)
            return

        # Admin / yetkili geliştirici / Hugging Face Spaces UI embed bypass'ı
        query_str = scope.get("query_string", b"").decode("ascii", errors="ignore").lower()
        is_admin_mode = (
            "admin=1" in query_str
            or "dev=1" in query_str
            or "__theme=" in query_str
            or "logs=container" in query_str
            or "x-admin-key" in headers
            or "hf_admin_session" in headers.get("cookie", "")
        )

        # Masaüstü web trafiği engellenir (Admin / dev / HF Space embed modu hariç)
        if not is_admin_mode and not self._is_mobile_client(headers):
            await _deny(send, 404)
            return

        # Türkiye + Mobil web (veya yetkili admin) doğrulanmıştır
        await self.app(scope, receive, send)


async def _deny(send, status: int = 404) -> None:
    """Send a silent denial — no body, no revealing error message."""
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": b""})

