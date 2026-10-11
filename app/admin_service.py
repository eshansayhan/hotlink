import json
import os
import time
import urllib.request
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import access_store

admin_router = APIRouter()


def _admin_session(request: Request) -> dict | None:
    token = request.cookies.get("hf_admin_session")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
    if not token:
        token = request.query_params.get("admin_token")
    if not token:
        return None
    return access_store.get_admin_session(token)


def send_admin_discord_notification(title: str, fields: list[dict], color: int = 58804) -> None:
    settings = access_store.get_settings()
    webhook = (settings.get("admin_log_webhook") or "").strip() or os.getenv("DISCORD_ADMIN_LOG_WEBHOOK", "").strip()
    if not webhook or not webhook.startswith("http"):
        return
    payload = {
        "content": "🛡️ **HFStream Güvenlik & Sistem Bildirimi**",
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {"text": "HFStream Güvenlik Monitörü"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }

    def _post():
        try:
            req = urllib.request.Request(
                webhook,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "HFStream/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass
        except Exception:
            pass

    import threading
    threading.Thread(target=_post, daemon=True).start()


def _send_discord_announcement_sync(webhook_url: str, title: str, description: str = "", poster_url: str = "") -> dict:
    if not webhook_url or not webhook_url.startswith(("http://", "https://")):
        return {"success": False, "error": "Geçersiz Discord Webhook URL. (https://discord.com/api/webhooks/... ile başlamalıdır)"}
    embed = {
        "title": f"🎬 Yeni İçerik Eklendi: {title}",
        "description": description or "HFStream platformuna yeni bir film/bölüm eklendi! Hemen uygulamadan izleyebilirsiniz.",
        "color": 0x00E5B4,
        "fields": [
            {"name": "⚡ Kalite", "value": "1080p Full HD", "inline": True},
            {"name": "🔑 Nasıl İzlenir?", "value": "Discord'da `/kod` yazarak 24 saatlik erişim kodunuzu alabilirsiniz!", "inline": True},
        ],
        "footer": {"text": "HFStream Cinema Platform"},
    }
    if poster_url and poster_url.startswith(("http://", "https://")):
        embed["image"] = {"url": poster_url}

    payload = {
        "content": "📢 **Yeni Film / Dizi Eklendi!**",
        "embeds": [embed],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "📱 Android Uygulamayı İndir",
                        "url": "https://play.google.com/store/apps/details?id=com.eshansayhan.hfstream",
                    }
                ],
            }
        ],
    }
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "HFStream-Announcer/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {"success": True, "status": resp.status}
    except Exception as err:
        return {"success": False, "error": str(err)}


def _discord_action_components() -> list[dict]:
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": "📱 Android Uygulamayı İndir",
                    "url": "https://play.google.com/store/apps/details?id=com.eshansayhan.hfstream",
                },
                {
                    "type": 2,
                    "style": 2,
                    "custom_id": "btn_check_remaining_time",
                    "label": "⏳ Kalan Süremi Göster",
                },
            ],
        }
    ]


class CustomCodeRequest(BaseModel):
    hours: int = 24
    note: str = ""


class AnnounceRequest(BaseModel):
    title: str
    description: str = ""
    poster_url: str = ""
    webhook_url: str = ""


class ReportSubmitRequest(BaseModel):
    video_id: str
    video_title: str = ""
    issue_type: str = "Video Açılmıyor"
    message: str = ""


class BanClientRequest(BaseModel):
    identifier: str
    client_type: str = "ip"
    reason: str = ""


@admin_router.get("/api/access/admin/analytics")
def get_admin_analytics(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    return access_store.get_analytics_summary()


@admin_router.post("/api/access/admin/codes/generate")
def generate_admin_access_code(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    code = access_store.issue_code("admin-panel", ip_address=client_ip, note="Admin panel hızlı kod")
    public_url = os.getenv(
        "HFSTREAM_PUBLIC_URL",
        "https://eshansayhan-hotlink.hf.space",
    ).rstrip("/")
    access_url = f"{public_url}/eshanio/?code={code}"
    return {"code": code, "url": access_url}


@admin_router.post("/api/access/admin/codes/custom")
def generate_custom_access_code(req: CustomCodeRequest, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    hours = max(1, min(req.hours, 8760))
    note = req.note.strip() or f"{hours} saatlik özel promosyon kodu"
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    code = access_store.issue_code(
        discord_user_id="admin-panel",
        custom_hours=hours,
        note=note,
        ip_address=client_ip,
    )
    public_url = os.getenv("HFSTREAM_PUBLIC_URL", "https://eshansayhan-hotlink.hf.space").rstrip("/")
    return {
        "code": code,
        "hours": hours,
        "note": note,
        "url": f"{public_url}/eshanio/?code={code}",
        "status": "available",
    }


@admin_router.post("/api/access/admin/announce")
async def admin_announce_video(req: AnnounceRequest, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    webhook_url = (req.webhook_url or "").strip() or os.getenv("DISCORD_ANNOUNCE_WEBHOOK_URL", "").strip() or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url or not webhook_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="Geçerli bir Discord Webhook URL'i girin (https://discord.com/api/webhooks/... ile başlamalıdır).",
        )
    result = await run_in_threadpool(
        _send_discord_announcement_sync,
        webhook_url,
        req.title,
        req.description,
        req.poster_url,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Duyuru gönderilemedi."))
    return result


@admin_router.post("/api/reports/submit")
def submit_issue_report(req: ReportSubmitRequest, request: Request):
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    device_id = request.cookies.get("hf_device_id", "")
    if access_store.is_banned(client_ip, device_id):
        raise HTTPException(status_code=403, detail="Yasaklı istemci.")
    report_id = access_store.create_issue_report(
        video_id=req.video_id,
        video_title=req.video_title,
        issue_type=req.issue_type,
        message=req.message,
    )
    send_admin_discord_notification(
        title="⚠️ Yeni İzleyici Hata Bildirimi",
        fields=[
            {"name": "Sorun Tipi", "value": req.issue_type, "inline": True},
            {"name": "Video", "value": req.video_title or req.video_id, "inline": True},
            {"name": "Mesaj", "value": req.message or "Açıklama belirtilmedi", "inline": False},
            {"name": "İstemci IP", "value": f"`{client_ip or 'Bilinmiyor'}`", "inline": True},
        ],
        color=15679588,
    )
    return {"success": True, "report_id": report_id}


@admin_router.get("/api/access/admin/reports")
def get_admin_reports(request: Request, unresolved_only: bool = True):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    return {"reports": access_store.list_issue_reports(unresolved_only=unresolved_only)}


@admin_router.post("/api/access/admin/reports/{report_id}/resolve")
def resolve_admin_report(report_id: int, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    success = access_store.resolve_issue_report(report_id)
    return {"success": success}


@admin_router.delete("/api/access/admin/reports/{report_id}")
def delete_admin_report(report_id: int, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    success = access_store.delete_issue_report(report_id)
    return {"success": success}


@admin_router.post("/api/access/admin/codes/cleanup")
def cleanup_admin_codes(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    deleted_count = access_store.cleanup_expired_codes()
    return {"success": True, "deleted_count": deleted_count}


@admin_router.get("/api/access/admin/banned")
def get_admin_banned_clients(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    return {"banned_clients": access_store.list_banned_clients()}


@admin_router.post("/api/access/admin/banned")
def add_admin_banned_client(req: BanClientRequest, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    if not req.identifier.strip():
        raise HTTPException(status_code=400, detail="Engellenecek IP veya Cihaz ID gereklidir.")
    access_store.ban_client(req.identifier, req.client_type, req.reason)
    return {"success": True, "banned_clients": access_store.list_banned_clients()}


@admin_router.delete("/api/access/admin/banned/{identifier:path}")
def remove_admin_banned_client(identifier: str, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    success = access_store.unban_client(identifier)
    return {"success": success, "banned_clients": access_store.list_banned_clients()}


@admin_router.get("/api/access/admin/logs")
def get_admin_access_logs(request: Request, limit: int = 150):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    return {"logs": access_store.list_access_logs(limit=limit)}


@admin_router.delete("/api/access/admin/logs")
def clear_admin_access_logs(request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    cleared_count = access_store.clear_access_logs()
    return {"success": True, "cleared_count": cleared_count}


@admin_router.get("/api/access/admin/google-users")
def get_admin_google_users(request: Request, limit: int = 200):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    users = access_store.list_google_users(limit=limit)
    return {"status": "ok", "total": len(users), "users": users}


class BanGoogleUserRequest(BaseModel):
    google_id: str
    is_banned: bool = True


@admin_router.post("/api/access/admin/google-users/ban")
def ban_admin_google_user(req: BanGoogleUserRequest, request: Request):
    if not _admin_session(request):
        raise HTTPException(status_code=401, detail="Yönetici girişi gerekli.")
    access_store.set_google_user_ban(req.google_id, req.is_banned)
    return {"success": True, "google_id": req.google_id, "is_banned": req.is_banned}

