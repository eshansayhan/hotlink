from typing import Dict, Any, Tuple
from app.config import config


class TikTokManager:
    _last_session_unavailable: bool = False
    @staticmethod
    def normalize_rtmp_url(raw_url: str) -> str:
        """
        Normalize TikTok RTMP server URL.
        TikTok Live typically provides URLs like:
        - rtmp://live-push.tiktok.com/live/
        - rtmps://live-push.tiktok.com/live/
        Ensure there is no trailing slash for clean concatenation with stream key.
        """
        url = raw_url.strip().rstrip("/")
        return url

    @classmethod
    def validate_credentials(cls) -> Tuple[bool, str]:
        """Verify TikTok RTMP URL and Stream Key."""
        url = config.tiktok_rtmp_url.strip()
        key = config.tiktok_stream_key.strip()

        if not url:
            return False, "TikTok RTMP URL is missing."
        if not (url.startswith("rtmp://") or url.startswith("rtmps://")):
            return False, "TikTok RTMP URL must begin with rtmp:// or rtmps://"

        if not key:
            return False, "TikTok Stream Key is missing. Enter your stream key in the panel or .env."

        if len(key) < 6:
            return False, "TikTok Stream Key is suspiciously short."

        return True, ""

    @classmethod
    def get_destination_url(cls) -> str:
        """Returns the full RTMP(S) destination URL including stream key for FFmpeg."""
        base_url = cls.normalize_rtmp_url(config.tiktok_rtmp_url)
        key = config.tiktok_stream_key.strip()
        return f"{base_url}/{key}"

    @classmethod
    def get_masked_destination_url(cls) -> str:
        """Returns the RTMP URL with masked stream key for UI display."""
        base_url = cls.normalize_rtmp_url(config.tiktok_rtmp_url)
        masked_key = config.get_masked_tiktok_stream_key()
        return f"{base_url}/{masked_key}" if masked_key else f"{base_url}/[NO_KEY]"

    @classmethod
    def ensure_active_session(cls) -> bool:
        """
        If TikTok is enabled and a session cookie is configured, ensures an active
        live room and valid RTMP stream key exist before streaming starts.
        If the current room is finished, absent, or key is missing, automatically
        creates a new live room via TikTok's Webcast API.
        """
        cls._last_session_unavailable = False
        if not (config.tiktok_enabled and config.tiktok_session_id):
            return False

        from app.streamer.tiktok_generator import tiktok_generator
        from app.monitoring.logger import stream_logger

        # Check if the room is actually live on TikTok right now
        info = tiktok_generator.get_current_room_info(config.tiktok_session_id)
        is_live = info.get("is_live", False)
        live_room_id = str(info.get("room_id") or "").strip()

        # If live_status is 1 AND matching room_id and key are in config, it's ready!
        if (
            is_live
            and live_room_id
            and config.tiktok_room_id == live_room_id
            and config.tiktok_room_event_id == config.tiktok_event_id
            and config.tiktok_stream_key
        ):
            return True

        # Otherwise, an active room is missing or key is outdated
        needs_new_room = True

        if needs_new_room:
            stream_logger.info(
                "TIKTOK",
                "Mevcut TikTok odası inaktif veya anahtar eksik. Oturum çerezi ile otomatik yeni canlı yayın odası oluşturuluyor..."
            )
            ok, res_data, msg = tiktok_generator.create_room_and_get_key(
                session_cookie=config.tiktok_session_id,
                title=config.tiktok_title or "24/7 Canlı Yayın",
            )
            if ok:
                config.update(
                    {
                        "tiktok_rtmp_url": res_data.get("rtmp_url", ""),
                        "tiktok_stream_key": res_data.get("stream_key", ""),
                        "tiktok_room_id": res_data.get("room_id", ""),
                    },
                    persist=True,
                )
                stream_logger.info(
                    "TIKTOK",
                    f"Otomatik TikTok canlı yayın odası hazır! Room ID: {res_data.get('room_id')}"
                )
                return True
            else:
                stream_logger.warn("TIKTOK", f"Otomatik TikTok odası oluşturulamadı: {msg}")
                cls._last_session_unavailable = True
                # Reset stale local keys to avoid accidental forbidden stream push
                config.reset_tiktok_session(persist=True)
                return False

        return True

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        is_valid, error_msg = cls.validate_credentials()
        return {
            "is_enabled": config.tiktok_enabled,
            "is_configured": bool(config.tiktok_stream_key),
            "is_valid": is_valid,
            "error_message": error_msg,
            "rtmp_url": config.tiktok_rtmp_url,
            "normalized_rtmp_url": cls.normalize_rtmp_url(config.tiktok_rtmp_url),
            "masked_destination": cls.get_masked_destination_url(),
            "has_session_id": bool(config.tiktok_session_id),
            "masked_session_id": config.get_masked_tiktok_session_id(),
            "room_id": config.tiktok_room_id,
            "title": config.tiktok_title,
        }


tiktok_manager = TikTokManager()
