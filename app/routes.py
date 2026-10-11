import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Header, Request, Depends
from pydantic import BaseModel

from app.config import config, VIDEOS_DIR
from app.monitoring.logger import stream_logger
from app.monitoring.health import get_system_metrics, format_duration
from app.streamer.ffmpeg import ffmpeg_streamer
from app.streamer.youtube import youtube_manager
from app.streamer.kick import kick_manager
from app.streamer.twitch import twitch_manager
from app.streamer.nimo import nimo_manager
from app.streamer.tiktok import tiktok_manager
from app.streamer.tiktok_generator import tiktok_generator
from app.streamer.recovery import watchdog
from app.video.source import source_manager
from app.video.validator import video_validator
from app.video.playlist import playlist_manager
from app.streamer.overlay import overlay_manager
from app.streamer.metadata import metadata_mutator

router = APIRouter()


def check_admin_auth(request: Request, x_admin_password: Optional[str] = Header(None, alias="X-Admin-Password")):
    """Validates admin password if ADMIN_PASSWORD is set in configuration."""
    if config.admin_password:
        auth_val = x_admin_password or request.query_params.get("admin_password")
        if not auth_val or auth_val != config.admin_password:
            raise HTTPException(
                status_code=401,
                detail="Yetkilendirme gerekli: Geçersiz veya eksik Admin Şifresi (X-Admin-Password)."
            )


class ConfigUpdateRequest(BaseModel):
    youtube_enabled: Optional[bool] = None
    youtube_rtmp_url: Optional[str] = None
    youtube_stream_key: Optional[str] = None
    kick_enabled: Optional[bool] = None
    kick_rtmp_url: Optional[str] = None
    kick_stream_key: Optional[str] = None
    twitch_enabled: Optional[bool] = None
    twitch_rtmp_url: Optional[str] = None
    twitch_stream_key: Optional[str] = None
    nimo_enabled: Optional[bool] = None
    nimo_rtmp_url: Optional[str] = None
    nimo_stream_key: Optional[str] = None
    tiktok_enabled: Optional[bool] = None
    tiktok_rtmp_url: Optional[str] = None
    tiktok_stream_key: Optional[str] = None
    tiktok_session_id: Optional[str] = None
    tiktok_room_id: Optional[str] = None
    tiktok_event_id: Optional[str] = None
    tiktok_title: Optional[str] = None
    video_source: Optional[str] = None
    stream_width: Optional[int] = None
    stream_height: Optional[int] = None
    stream_fps: Optional[int] = None
    stream_bitrate: Optional[str] = None
    stream_audio_bitrate: Optional[str] = None
    stream_preset: Optional[str] = None
    hw_accel: Optional[str] = None
    video_loop: Optional[bool] = None
    auto_start: Optional[bool] = None
    reconnect_enabled: Optional[bool] = None
    admin_password: Optional[str] = None
    persist: Optional[bool] = True


class TikTokKeyGenRequest(BaseModel):
    session_id: Optional[str] = None
    event_id: Optional[str] = None
    title: Optional[str] = None
    auto_apply: Optional[bool] = True
    start_stream: Optional[bool] = False


class TikTokFinishRequest(BaseModel):
    room_id: Optional[str] = None


class PlaylistAddRequest(BaseModel):
    source: str
    title: Optional[str] = None


class ChatPushRequest(BaseModel):
    user: str
    text: str
    color: Optional[str] = "#ffffff"


class OverlaySettingsRequest(BaseModel):
    show_uptime: Optional[bool] = None
    show_chat: Optional[bool] = None
    show_goal: Optional[bool] = None
    show_notifications: Optional[bool] = None
    auto_chat_enabled: Optional[bool] = None
    noise_enabled: Optional[bool] = None
    noise_strength: Optional[int] = None  # 1-10 arası
    hash_evasion_enabled: Optional[bool] = None
    spatial_shift_enabled: Optional[bool] = None
    color_oscillation_enabled: Optional[bool] = None
    unsharp_enabled: Optional[bool] = None
    audio_evasion_enabled: Optional[bool] = None


class GiftPushRequest(BaseModel):
    user: str
    gift_name: Optional[str] = "Gül"
    count: Optional[int] = 1


class FollowerPushRequest(BaseModel):
    user: str


class GoalUpdateRequest(BaseModel):
    title: Optional[str] = None
    current: Optional[int] = None
    target: Optional[int] = None
    show_goal: Optional[bool] = None


class MetadataSettingsRequest(BaseModel):
    loop_restart_enabled: Optional[bool] = None




@router.get("/health")
def health_check() -> Dict[str, Any]:
    """
    Standard Health Check endpoint for Uptime monitors and Hugging Face.
    Matches the specification in README.md.
    """
    is_ffmpeg_running = ffmpeg_streamer.is_running()
    watchdog_status = watchdog.get_status()

    # Stream state
    if is_ffmpeg_running:
        stream_state = "running"
        ffmpeg_state = "running"
        youtube_state = "connected" if config.youtube_enabled else "disabled"
        kick_state = "connected" if config.kick_enabled else "disabled"
        twitch_state = "connected" if config.twitch_enabled else "disabled"
        nimo_state = "connected" if config.nimo_enabled else "disabled"
        tiktok_state = (
            "connected"
            if "TikTok" in ffmpeg_streamer.active_targets
            else "connecting" if config.tiktok_enabled and ffmpeg_streamer.is_tiktok_auto_retry_active()
            else "disconnected" if config.tiktok_enabled
            else "disabled"
        )
    elif watchdog_status.get("is_desired_running"):
        stream_state = "reconnecting"
        ffmpeg_state = "stopped"
        youtube_state = "connecting" if config.youtube_enabled else "disabled"
        kick_state = "connecting" if config.kick_enabled else "disabled"
        twitch_state = "connecting" if config.twitch_enabled else "disabled"
        nimo_state = "connecting" if config.nimo_enabled else "disabled"
        tiktok_state = "connecting" if config.tiktok_enabled else "disabled"
    else:
        stream_state = "stopped"
        ffmpeg_state = "stopped"
        youtube_state = "disconnected" if config.youtube_enabled else "disabled"
        kick_state = "disconnected" if config.kick_enabled else "disabled"
        twitch_state = "disconnected" if config.twitch_enabled else "disabled"
        nimo_state = "disconnected" if config.nimo_enabled else "disabled"
        tiktok_state = "disconnected" if config.tiktok_enabled else "disabled"

    sys_metrics = get_system_metrics()

    enabled_platform_count = sum([config.youtube_enabled, config.kick_enabled, config.twitch_enabled, config.nimo_enabled, config.tiktok_enabled])

    return {
        "status": "ok",
        "stream": stream_state,
        "ffmpeg": ffmpeg_state,
        "youtube": youtube_state,
        "kick": kick_state,
        "twitch": twitch_state,
        "nimo": nimo_state,
        "tiktok": tiktok_state,
        "multistream": enabled_platform_count > 1,
        "uptime": sys_metrics["app_uptime"],
        "reconnects": watchdog_status["reconnect_count"],
        "cpu_percent": sys_metrics["cpu_percent"],
        "memory_percent": sys_metrics["memory_percent"],
        "last_error": ffmpeg_streamer.last_error,
    }


@router.get("/api/status")
def get_detailed_status() -> Dict[str, Any]:
    """Provides full status telemetry for the web dashboard."""
    ffmpeg_info = ffmpeg_streamer.get_status_info()
    yt_info = youtube_manager.get_status()
    kick_info = kick_manager.get_status()
    twitch_info = twitch_manager.get_status()
    nimo_info = nimo_manager.get_status()
    tiktok_info = tiktok_manager.get_status()
    tiktok_info["automation"] = ffmpeg_info["tiktok_automation"]
    source_info = source_manager.get_current_source_info()
    watchdog_info = watchdog.get_status()
    sys_metrics = get_system_metrics()

    # Determine overall high-level state
    if ffmpeg_info["is_running"]:
        overall_status = "LIVE"
    elif ffmpeg_info["status"] == "WAITING_TIKTOK":
        overall_status = "WAITING_TIKTOK"
    elif watchdog_info["is_desired_running"]:
        overall_status = "RECONNECTING"
    elif ffmpeg_info["status"] == "ERROR":
        overall_status = "ERROR"
    else:
        overall_status = "STOPPED"

    configured_destinations = sum([
        bool(config.youtube_enabled and config.youtube_stream_key),
        bool(config.kick_enabled and config.kick_stream_key),
        bool(config.twitch_enabled and config.twitch_stream_key),
        bool(config.nimo_enabled and config.nimo_stream_key),
        bool(config.tiktok_enabled and config.tiktok_stream_key),
    ])

    return {
        "overall_status": overall_status,
        "streamer": ffmpeg_info,
        "youtube": yt_info,
        "kick": kick_info,
        "twitch": twitch_info,
        "nimo": nimo_info,
        "tiktok": tiktok_info,
        "is_multistream": configured_destinations > 1,
        "source": source_info,
        "watchdog": watchdog_info,
        "system": sys_metrics,
        "config": config.to_dict(mask_secret=True),
    }


@router.post("/api/auth/verify")
def verify_admin_auth(request: Request, x_admin_password: Optional[str] = Header(None, alias="X-Admin-Password")):
    """Check if admin password is required and if the supplied password is valid."""
    if not config.admin_password:
        return {"authenticated": True, "password_required": False}
    auth_val = x_admin_password or request.query_params.get("admin_password")
    if auth_val == config.admin_password:
        return {"authenticated": True, "password_required": True}
    return {"authenticated": False, "password_required": True}


@router.post("/api/stream/start", dependencies=[Depends(check_admin_auth)])
def start_stream() -> Dict[str, Any]:
    """Start streaming to YouTube, Kick, and/or TikTok."""
    stream_logger.info("API", "Received Start Stream request.")

    # 1. Validation check for video source
    is_valid, src, err = video_validator.resolve_path(config.video_source)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Cannot start: {err}")

    # 2. Validation check for destinations
    valid_destinations = 0
    errors = []

    if config.youtube_enabled:
        is_yt, yt_err = youtube_manager.validate_credentials()
        if is_yt:
            valid_destinations += 1
        else:
            errors.append(f"YouTube: {yt_err}")

    if config.kick_enabled:
        is_kick, kick_err = kick_manager.validate_credentials()
        if is_kick:
            valid_destinations += 1
        else:
            errors.append(f"Kick: {kick_err}")

    if config.twitch_enabled:
        is_twitch, twitch_err = twitch_manager.validate_credentials()
        if is_twitch:
            valid_destinations += 1
        else:
            errors.append(f"Twitch: {twitch_err}")

    if config.nimo_enabled:
        is_nimo, nimo_err = nimo_manager.validate_credentials()
        if is_nimo:
            valid_destinations += 1
        else:
            errors.append(f"Nimo: {nimo_err}")

    if config.tiktok_enabled:
        if config.tiktok_session_id:
            valid_destinations += 1
        else:
            is_tiktok, tiktok_err = tiktok_manager.validate_credentials()
            if is_tiktok:
                valid_destinations += 1
            else:
                errors.append(f"TikTok: {tiktok_err}")

    if valid_destinations == 0:
        err_msg = "No broadcast platforms are valid. " + "; ".join(errors)
        raise HTTPException(status_code=400, detail=f"Cannot start: {err_msg}")

    success = watchdog.request_start()
    if not success:
        last_err = ffmpeg_streamer.last_error or "Failed to start FFmpeg process."
        raise HTTPException(status_code=500, detail=last_err)

    targets_desc = ", ".join(ffmpeg_streamer.active_targets) if ffmpeg_streamer.active_targets else "enabled platforms"
    return {
        "success": True,
        "pending": ffmpeg_streamer.status == "WAITING_TIKTOK",
        "message": (
            "TikTok oda oluşturma arka planda sürüyor; oda hazır olduğunda yayın otomatik başlayacak."
            if ffmpeg_streamer.status == "WAITING_TIKTOK"
            else f"Stream started successfully to {targets_desc}."
        ),
        "pid": ffmpeg_streamer.get_pid(),
        "active_targets": ffmpeg_streamer.active_targets,
    }


@router.post("/api/stream/stop", dependencies=[Depends(check_admin_auth)])
def stop_stream() -> Dict[str, Any]:
    """Stop the current stream while preserving active broadcast sessions."""
    stream_logger.info("API", "Received Stop Stream request.")
    success = watchdog.request_stop()
    return {"success": success, "message": "Stream stopped."}


@router.post("/api/stream/restart", dependencies=[Depends(check_admin_auth)])
def restart_stream() -> Dict[str, Any]:
    """Restart the stream."""
    stream_logger.info("API", "Received Restart Stream request.")
    success = watchdog.request_restart()
    return {"success": success, "message": "Stream restarted.", "pid": ffmpeg_streamer.get_pid()}


@router.get("/api/config")
def get_config() -> Dict[str, Any]:
    """Get current configuration."""
    return config.to_dict(mask_secret=True)


@router.post("/api/config", dependencies=[Depends(check_admin_auth)])
def update_config(req: ConfigUpdateRequest) -> Dict[str, Any]:
    """Update settings and optionally save to .env."""
    data = req.model_dump(exclude_unset=True)
    persist = data.pop("persist", True)
    if "tiktok_event_id" in data and data["tiktok_event_id"] is not None:
        try:
            data["tiktok_event_id"] = tiktok_generator.normalize_event_id(data["tiktok_event_id"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    config.update(data, persist=persist)
    if data.get("tiktok_enabled") is False:
        ffmpeg_streamer.stop_tiktok_auto_retry()
    stream_logger.info("API", "Configuration updated successfully.")

    # If stream is running and video source or credentials changed, notify
    return {"success": True, "config": config.to_dict(mask_secret=True)}


@router.post("/api/tiktok/generate-key", dependencies=[Depends(check_admin_auth)])
def generate_tiktok_key(req: TikTokKeyGenRequest) -> Dict[str, Any]:
    """Automatically create TikTok Live room and retrieve RTMP URL + Stream Key."""
    try:
        session_val = (req.session_id or "").strip()
        # If masked or empty, fall back to stored runtime config session_id
        if not session_val or session_val.startswith("••••"):
            session_val = config.tiktok_session_id

        if not session_val:
            raise HTTPException(
                status_code=400,
                detail="TikTok sessionid çerezi girilmedi. Lütfen oturum çerezinizi (sessionid) giriniz."
            )

        title = req.title.strip() if req.title else (config.tiktok_title or "24/7 Live Stream")
        try:
            event_id = tiktok_generator.normalize_event_id(
                config.tiktok_event_id if req.event_id is None else req.event_id
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        if req.auto_apply and ffmpeg_streamer.is_tiktok_auto_retry_active():
            config.update(
                {
                    "tiktok_enabled": True,
                    "tiktok_event_id": event_id,
                    "tiktok_session_id": session_val,
                    "tiktok_title": title,
                },
                persist=True,
            )
            should_start_stream = req.start_stream or ffmpeg_streamer.is_running()
            ffmpeg_streamer.start_tiktok_auto_retry(
                start_stream_on_success=should_start_stream,
                initial_delay_sec=30,
            )
            stream_started = False
            if req.start_stream and not ffmpeg_streamer.is_running():
                stream_started = watchdog.request_start()
            return {
                "success": True,
                "pending": True,
                "message": "TikTok oda oluşturma zaten arka planda sürüyor; aynı hesap için yinelenen oda isteği önlendi.",
                "stream_started": stream_started or ffmpeg_streamer.is_running(),
                "config": config.to_dict(mask_secret=True),
            }

        success, res_data, msg = ffmpeg_streamer.create_tiktok_room(
            session_cookie=session_val,
            title=title,
            event_id=event_id,
        )
        if not success:
            if req.auto_apply and ("10037" in msg or "20800" in msg):
                config.update(
                    {
                        "tiktok_enabled": True,
                        "tiktok_event_id": event_id,
                        "tiktok_session_id": session_val,
                        "tiktok_title": title,
                    },
                    persist=True,
                )
                should_start_stream = req.start_stream or ffmpeg_streamer.is_running()
                ffmpeg_streamer.start_tiktok_auto_retry(
                    start_stream_on_success=should_start_stream,
                    initial_delay_sec=30,
                )

                stream_started = False
                if req.start_stream and not ffmpeg_streamer.is_running():
                    stream_started = watchdog.request_start()

                return {
                    "success": True,
                    "pending": True,
                    "message": (
                        "TikTok 10037/20800 cooldown sürüyor. Oda oluşturma arka planda "
                        "otomatik olarak tekrar denenecek; diğer etkin platformlar çalışmaya devam eder."
                    ),
                    "stream_started": stream_started or ffmpeg_streamer.is_running(),
                    "config": config.to_dict(mask_secret=True),
                }
            detail = msg.split(":", 1)[1].strip() if msg.startswith(
                ("SESSION_REJECTED:", "SESSION_UNVERIFIED:")
            ) else msg
            raise HTTPException(status_code=400, detail=detail)

        # Save to runtime config and .env if auto_apply is True
        if req.auto_apply:
            updates = {
                "tiktok_enabled": True,
                "tiktok_event_id": event_id,
                "tiktok_rtmp_url": res_data.get("rtmp_url", ""),
                "tiktok_stream_key": res_data.get("stream_key", ""),
                "tiktok_session_id": session_val,
                "tiktok_room_id": res_data.get("room_id", ""),
                "tiktok_title": title,
            }
            config.update(updates, persist=True)

        stream_started = False
        if req.start_stream or (req.auto_apply and ffmpeg_streamer.is_running()):
            if ffmpeg_streamer.is_running():
                stream_logger.info(
                    "API",
                    "Yayın çalışırken yeni TikTok anahtarı uygulandı. Çoklu yayın (Kick + TikTok) için FFmpeg yeniden başlatılıyor..."
                )
                stream_success = watchdog.request_restart()
            else:
                stream_success = watchdog.request_start()
            stream_started = bool(stream_success)

        return {
            "success": True,
            "message": msg,
            "rtmp_url": res_data.get("rtmp_url", ""),
            "stream_key": res_data.get("stream_key", ""),
            "room_id": res_data.get("room_id", ""),
            "title": title,
            "stream_started": stream_started,
            "config": config.to_dict(mask_secret=True),
        }
    except HTTPException:
        raise
    except Exception as e:
        stream_logger.error("API", f"TikTok generate-key error: {e}")
        raise HTTPException(status_code=500, detail=f"TikTok anahtarı üretilirken hata oluştu: {str(e)}")


@router.post("/api/tiktok/finish-room", dependencies=[Depends(check_admin_auth)])
def finish_tiktok_room(req: Optional[TikTokFinishRequest] = None) -> Dict[str, Any]:
    """End active TikTok Live room and wipe temporary keys."""
    ffmpeg_streamer.stop_tiktok_auto_retry(wait_for_in_flight_request=True)
    if not config.tiktok_session_id:
        config.reset_tiktok_session(persist=True)
        return {"success": True, "message": "TikTok anahtarları sıfırlandı."}

    target_room_id = (req.room_id if req and req.room_id else "") or config.tiktok_room_id or ""

    success, msg = tiktok_generator.finish_room(
        session_cookie=config.tiktok_session_id,
        room_id=target_room_id,
    )
    # Ensure local session keys and room ID are always wiped
    config.reset_tiktok_session(persist=True)

    return {
        "success": success,
        "message": msg,
        "closed_room_id": target_room_id,
        "tiktok_stream_key": "",
        "tiktok_room_id": "",
    }


@router.get("/api/videos")
def list_videos() -> Dict[str, Any]:
    """List available local videos and current source details."""
    videos = source_manager.list_local_videos()
    current = source_manager.get_current_source_info()
    return {"videos": videos, "current": current}


@router.post("/api/videos/upload", dependencies=[Depends(check_admin_auth)])
async def upload_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a new video file to the videos/ directory."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")

    # Sanitize filename
    safe_filename = Path(file.filename).name
    destination = VIDEOS_DIR / safe_filename

    stream_logger.info("API", f"Uploading video: {safe_filename}...")

    try:
        with open(destination, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        size_mb = round(destination.stat().st_size / (1024 * 1024), 2)
        stream_logger.info("API", f"Video {safe_filename} uploaded successfully ({size_mb} MB).")

        return {
            "success": True,
            "filename": safe_filename,
            "path": str(destination),
            "size_mb": size_mb,
        }
    except Exception as e:
        stream_logger.error("API", f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/api/videos/generate-sample", dependencies=[Depends(check_admin_auth)])
def generate_sample_video() -> Dict[str, Any]:
    """Generates an asd.video test pattern with colorbars and audio using FFmpeg."""
    result = source_manager.create_sample_video("asd.video", duration=15)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to generate video."))
    return result


@router.get("/api/playlist")
def get_playlist() -> Dict[str, Any]:
    """Get playlist items."""
    return playlist_manager.get_playlist()


@router.post("/api/playlist/add")
def add_to_playlist(req: PlaylistAddRequest) -> Dict[str, Any]:
    """Add a video source to the playlist."""
    playlist_manager.add_item(req.source, req.title)
    return {"success": True, "playlist": playlist_manager.get_playlist()}


@router.delete("/api/playlist/{index}")
def remove_from_playlist(index: int) -> Dict[str, Any]:
    """Remove video by index from the playlist."""
    playlist_manager.remove_item(index)
    return {"success": True, "playlist": playlist_manager.get_playlist()}


@router.get("/api/logs")
def get_logs(limit: int = 200) -> Dict[str, Any]:
    """Get recent logs."""
    return {"logs": stream_logger.get_logs(limit=limit)}


@router.delete("/api/logs")
def clear_logs() -> Dict[str, Any]:
    """Clear memory logs."""
    stream_logger.clear()
    return {"success": True, "message": "Logs cleared."}


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Real-time log streaming over WebSocket."""
    await websocket.accept()
    queue = asyncio.Queue()
    stream_logger.register_listener(queue)

    try:
        # Send recent initial batch of logs first
        recent_logs = stream_logger.get_logs(limit=50)
        for log_entry in recent_logs:
            await websocket.send_json(log_entry)

        # Stream new incoming logs
        while True:
            entry = await queue.get()
            await websocket.send_json(entry)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        stream_logger.unregister_listener(queue)


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """
    Real-time full-duplex WebSocket endpoint.
    - Pushes live telemetry status every 1 second.
    - Accepts incoming client commands ('ping', 'refresh', 'start', 'stop', 'restart')
      and responds immediately.
    """
    await websocket.accept()

    async def push_telemetry():
        while True:
            status = get_detailed_status()
            await websocket.send_json(status)
            await asyncio.sleep(1)

    async def receive_commands():
        while True:
            try:
                data = await websocket.receive_json()
                action = data.get("action")
                if action == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
                elif action == "refresh":
                    await websocket.send_json(get_detailed_status())
                elif action in ("start", "stop", "restart"):
                    if config.admin_password:
                        client_pass = data.get("admin_password")
                        if client_pass != config.admin_password:
                            await websocket.send_json({"type": "error", "message": "Yetkilendirme gerekli: Geçersiz Admin Şifresi."})
                            continue
                    if action == "start":
                        watchdog.request_start()
                    elif action == "stop":
                        watchdog.request_stop()
                    elif action == "restart":
                        watchdog.request_restart()
                    await websocket.send_json(get_detailed_status())
            except Exception:
                break

    push_task = asyncio.create_task(push_telemetry())
    recv_task = asyncio.create_task(receive_commands())

    try:
        done, pending = await asyncio.wait(
            [push_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except (WebSocketDisconnect, asyncio.CancelledError):
        push_task.cancel()
        recv_task.cancel()


# ═══════════════════════════════════════════════════════════════════════
# OVERLAY API — Yayın süresi + TikTok Chat Overlay
# ═══════════════════════════════════════════════════════════════════════

@router.post("/overlay/chat")
async def push_chat_message(req: ChatPushRequest, _auth=Depends(check_admin_auth)):
    """
    TikTok (veya herhangi bir) chat mesajını video overlay kuyruğuna ekler.
    FFmpeg yeniden başlatılmadan, bir sonraki build_command çağrısında etkinleşir.

    Örnek:
        POST /overlay/chat
        {"user": "Eshan", "text": "Merhaba!", "color": "#fe2c55"}
    """
    user = (req.user or "Anonim").strip()[:20]
    text = (req.text or "").strip()[:80]
    if not text:
        raise HTTPException(status_code=422, detail="Mesaj metni boş olamaz.")

    msg = overlay_manager.add_chat_message(user=user, text=text, color=req.color or "#ffffff")
    return {
        "ok": True,
        "msg_id": msg.msg_id,
        "user": msg.user,
        "text": msg.text,
        "display_duration": msg.display_duration,
    }


@router.get("/overlay/chat")
async def get_chat_messages():
    """Şu anda aktif (süresi dolmamış) chat mesajlarını listeler."""
    active = overlay_manager.get_active_messages()
    return {
        "ok": True,
        "count": len(active),
        "messages": [
            {
                "msg_id": m.msg_id,
                "user": m.user,
                "text": m.text,
                "color": m.color,
                "age_seconds": round(time.time() - m.arrived_at, 1),
                "remaining_seconds": round(m.display_duration - (time.time() - m.arrived_at), 1),
            }
            for m in active
        ],
    }


@router.delete("/overlay/chat")
async def clear_chat_messages(_auth=Depends(check_admin_auth)):
    """Tüm overlay chat mesajlarını temizler."""
    overlay_manager.clear_chat()
    return {"ok": True, "message": "Chat overlay temizlendi."}


@router.post("/overlay/gift")
async def push_gift_notification(req: GiftPushRequest, _auth=Depends(check_admin_auth)):
    """Canlı yayına hediye (Gift) pop-up efekti gönderir."""
    notif = overlay_manager.add_gift_notification(
        user=req.user,
        gift_name=req.gift_name or "Gül",
        count=req.count or 1
    )
    return {
        "ok": True,
        "message": f"Hediye bildirimi eklendi: @{req.user} {req.gift_name} (x{req.count})",
        "notif_id": notif.notif_id,
        "goal_current": overlay_manager.goal_current,
    }


@router.post("/overlay/follower")
async def push_follower_notification(req: FollowerPushRequest, _auth=Depends(check_admin_auth)):
    """Canlı yayına yeni takipçi pop-up efekti gönderir."""
    notif = overlay_manager.add_follower_notification(user=req.user)
    return {
        "ok": True,
        "message": f"Takipçi bildirimi eklendi: @{req.user}",
        "notif_id": notif.notif_id,
        "goal_current": overlay_manager.goal_current,
    }


@router.post("/overlay/goal")
async def update_live_goal(req: GoalUpdateRequest, _auth=Depends(check_admin_auth)):
    """Canlı hedef ve beğeni ilerleme çubuğunu günceller."""
    overlay_manager.set_goal(title=req.title, current=req.current, target=req.target)
    if req.show_goal is not None:
        overlay_manager.show_goal = req.show_goal
    return {
        "ok": True,
        "goal_title": overlay_manager.goal_title,
        "goal_current": overlay_manager.goal_current,
        "goal_target": overlay_manager.goal_target,
        "show_goal": overlay_manager.show_goal,
    }


@router.get("/overlay/goal")
async def get_live_goal():
    """Mevcut canlı hedef durumunu döndürür."""
    pct = min(100.0, (overlay_manager.goal_current / max(1, overlay_manager.goal_target)) * 100.0)
    return {
        "ok": True,
        "goal_title": overlay_manager.goal_title,
        "goal_current": overlay_manager.goal_current,
        "goal_target": overlay_manager.goal_target,
        "goal_percentage": round(pct, 1),
        "show_goal": overlay_manager.show_goal,
    }


@router.patch("/overlay/settings")
async def update_overlay_settings(req: OverlaySettingsRequest, _auth=Depends(check_admin_auth)):
    """Overlay, noise, hedef, otomatik chat ve anti-hash ayarlarını günceller."""
    if req.show_uptime is not None:
        overlay_manager.show_uptime = req.show_uptime
    if req.show_chat is not None:
        overlay_manager.show_chat = req.show_chat
    if req.show_goal is not None:
        overlay_manager.show_goal = req.show_goal
    if req.show_notifications is not None:
        overlay_manager.show_notifications = req.show_notifications
    if req.auto_chat_enabled is not None:
        overlay_manager.auto_chat_enabled = req.auto_chat_enabled
    if req.noise_enabled is not None:
        overlay_manager.noise_enabled = req.noise_enabled
    if req.noise_strength is not None:
        overlay_manager.noise_strength = max(1, min(10, req.noise_strength))
    if req.hash_evasion_enabled is not None:
        overlay_manager.hash_evasion_enabled = req.hash_evasion_enabled
    if req.spatial_shift_enabled is not None:
        overlay_manager.spatial_shift_enabled = req.spatial_shift_enabled
    if req.color_oscillation_enabled is not None:
        overlay_manager.color_oscillation_enabled = req.color_oscillation_enabled
    if req.unsharp_enabled is not None:
        overlay_manager.unsharp_enabled = req.unsharp_enabled
    if req.audio_evasion_enabled is not None:
        overlay_manager.audio_evasion_enabled = req.audio_evasion_enabled

    return {
        "ok": True,
        "show_uptime": overlay_manager.show_uptime,
        "show_chat": overlay_manager.show_chat,
        "show_goal": overlay_manager.show_goal,
        "show_notifications": overlay_manager.show_notifications,
        "auto_chat_enabled": overlay_manager.auto_chat_enabled,
        "noise_enabled": overlay_manager.noise_enabled,
        "noise_strength": overlay_manager.noise_strength,
        "hash_evasion_enabled": overlay_manager.hash_evasion_enabled,
        "spatial_shift_enabled": overlay_manager.spatial_shift_enabled,
        "color_oscillation_enabled": overlay_manager.color_oscillation_enabled,
        "unsharp_enabled": overlay_manager.unsharp_enabled,
        "audio_evasion_enabled": overlay_manager.audio_evasion_enabled,
    }


@router.get("/overlay/status")
async def get_overlay_status():
    """Overlay ve Hash Evasion mevcut ayarlarını ve aktif mesaj/bildirim sayılarını döndürür."""
    active_chats = overlay_manager.get_active_messages()
    active_notifs = overlay_manager.get_active_notifications()
    pct = min(100.0, (overlay_manager.goal_current / max(1, overlay_manager.goal_target)) * 100.0)
    return {
        "ok": True,
        "show_uptime": overlay_manager.show_uptime,
        "show_chat": overlay_manager.show_chat,
        "show_goal": overlay_manager.show_goal,
        "show_notifications": overlay_manager.show_notifications,
        "auto_chat_enabled": overlay_manager.auto_chat_enabled,
        "noise_enabled": overlay_manager.noise_enabled,
        "noise_strength": overlay_manager.noise_strength,
        "hash_evasion_enabled": overlay_manager.hash_evasion_enabled,
        "spatial_shift_enabled": overlay_manager.spatial_shift_enabled,
        "color_oscillation_enabled": overlay_manager.color_oscillation_enabled,
        "unsharp_enabled": overlay_manager.unsharp_enabled,
        "audio_evasion_enabled": overlay_manager.audio_evasion_enabled,
        "goal_title": overlay_manager.goal_title,
        "goal_current": overlay_manager.goal_current,
        "goal_target": overlay_manager.goal_target,
        "goal_percentage": round(pct, 1),
        "active_chat_count": len(active_chats),
        "active_notif_count": len(active_notifs),
        "stream_running": ffmpeg_streamer.is_running(),
        "stream_uptime": ffmpeg_streamer.get_status_info().get("uptime_formatted", "00:00:00"),
    }


@router.get("/metadata/status")
async def get_metadata_status():
    """Mevcut aktif metadata, loop sayısı ve video süresi durumunu döndürür."""
    return {
        "ok": True,
        "current_metadata": metadata_mutator.get_current_metadata(),
        "loop_count": metadata_mutator.get_loop_count(),
        "video_duration": metadata_mutator.get_video_duration(),
        "loop_restart_enabled": metadata_mutator.loop_restart_enabled,
    }


@router.post("/metadata/force")
async def force_new_metadata(_auth=Depends(check_admin_auth)):
    """Manuel olarak yeni rastgele metadata üretir."""
    new_meta = metadata_mutator.force_new_metadata()
    return {
        "ok": True,
        "message": "Yeni metadata üretildi.",
        "metadata": new_meta,
        "loop_count": metadata_mutator.get_loop_count(),
    }


@router.patch("/metadata/settings")
async def update_metadata_settings(req: MetadataSettingsRequest, _auth=Depends(check_admin_auth)):
    """Metadata mutasyon ayarlarını günceller."""
    if req.loop_restart_enabled is not None:
        metadata_mutator.loop_restart_enabled = req.loop_restart_enabled
    return {
        "ok": True,
        "loop_restart_enabled": metadata_mutator.loop_restart_enabled,
    }
