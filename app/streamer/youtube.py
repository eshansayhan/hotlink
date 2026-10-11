import re
from typing import Dict, Any, Tuple
from app.config import config


class YouTubeManager:
    @staticmethod
    def validate_credentials() -> Tuple[bool, str]:
        """Verify YouTube RTMP URL and Stream Key."""
        url = config.youtube_rtmp_url.strip()
        key = config.youtube_stream_key.strip()

        if not url:
            return False, "YouTube RTMP URL is missing."
        if not (url.startswith("rtmp://") or url.startswith("rtmps://")):
            return False, "YouTube RTMP URL must begin with rtmp:// or rtmps://"

        if not key:
            return False, "YouTube Stream Key is missing. Please enter your stream key in the panel or .env."

        # YouTube stream keys are typically 4-4-4-4 characters or alphanumeric with hyphens
        if len(key) < 8:
            return False, "YouTube Stream Key is suspiciously short (usually 16-24 characters)."

        return True, ""

    @staticmethod
    def get_destination_url() -> str:
        """Returns the full RTMP URL including stream key for FFmpeg."""
        base_url = config.youtube_rtmp_url.rstrip("/")
        key = config.youtube_stream_key.strip()
        return f"{base_url}/{key}"

    @staticmethod
    def get_masked_destination_url() -> str:
        """Returns the RTMP URL with masked stream key for UI display."""
        base_url = config.youtube_rtmp_url.rstrip("/")
        masked_key = config.get_masked_stream_key()
        return f"{base_url}/{masked_key}" if masked_key else f"{base_url}/[NO_KEY]"

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        is_valid, error_msg = cls.validate_credentials()
        return {
            "is_enabled": config.youtube_enabled,
            "is_configured": bool(config.youtube_stream_key),
            "is_valid": is_valid,
            "error_message": error_msg,
            "rtmp_url": config.youtube_rtmp_url,
            "masked_destination": cls.get_masked_destination_url(),
        }


youtube_manager = YouTubeManager()
