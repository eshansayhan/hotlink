from typing import Dict, Any, Tuple
from app.config import config


class KickManager:
    @staticmethod
    def normalize_rtmp_url(raw_url: str) -> str:
        """
        Normalize Kick RTMP server URL.
        Kick uses Amazon IVS ingestion which requires '/app' as application name.
        e.g. 'rtmps://...live-video.net/' -> 'rtmps://...live-video.net/app'
        """
        url = raw_url.strip().rstrip("/")
        if not url:
            return ""
        if not url.endswith("/app"):
            url = f"{url}/app"
        return url

    @classmethod
    def validate_credentials(cls) -> Tuple[bool, str]:
        """Verify Kick RTMP URL and Stream Key."""
        url = config.kick_rtmp_url.strip()
        key = config.kick_stream_key.strip()

        if not url:
            return False, "Kick RTMP URL is missing."
        if not (url.startswith("rtmp://") or url.startswith("rtmps://")):
            return False, "Kick RTMP URL must begin with rtmp:// or rtmps://"

        if not key:
            return False, "Kick Stream Key is missing. Please enter your stream key in the panel or .env."

        if len(key) < 8:
            return False, "Kick Stream Key is suspiciously short."

        return True, ""

    @classmethod
    def get_destination_url(cls) -> str:
        """Returns the full RTMP(S) destination URL including stream key for FFmpeg."""
        base_url = cls.normalize_rtmp_url(config.kick_rtmp_url)
        key = config.kick_stream_key.strip()
        return f"{base_url}/{key}"

    @classmethod
    def get_masked_destination_url(cls) -> str:
        """Returns the RTMP URL with masked stream key for UI display."""
        base_url = cls.normalize_rtmp_url(config.kick_rtmp_url)
        masked_key = config.get_masked_kick_stream_key()
        return f"{base_url}/{masked_key}" if masked_key else f"{base_url}/[NO_KEY]"

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        is_valid, error_msg = cls.validate_credentials()
        return {
            "is_enabled": config.kick_enabled,
            "is_configured": bool(config.kick_stream_key),
            "is_valid": is_valid,
            "error_message": error_msg,
            "rtmp_url": config.kick_rtmp_url,
            "normalized_rtmp_url": cls.normalize_rtmp_url(config.kick_rtmp_url),
            "masked_destination": cls.get_masked_destination_url(),
        }


kick_manager = KickManager()
