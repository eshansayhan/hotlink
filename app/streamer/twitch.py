from typing import Dict, Any, Tuple

from app.config import config


class TwitchManager:
    @staticmethod
    def normalize_rtmp_url(raw_url: str) -> str:
        url = raw_url.strip().rstrip("/")
        if not url:
            return ""
        if not url.endswith("/app"):
            url = f"{url}/app"
        return url

    @staticmethod
    def validate_credentials() -> Tuple[bool, str]:
        """Validate Twitch RTMP URL and stream key."""
        url = config.twitch_rtmp_url.strip()
        key = config.twitch_stream_key.strip()

        if not url:
            return False, "Twitch RTMP URL is missing."
        if not (url.startswith("rtmp://") or url.startswith("rtmps://")):
            return False, "Twitch RTMP URL must begin with rtmp:// or rtmps://"

        if not key:
            return False, "Twitch Stream Key is missing. Please enter your key in the panel or .env."

        if len(key) < 8:
            return False, "Twitch Stream Key is suspiciously short."

        return True, ""

    @staticmethod
    def get_destination_url() -> str:
        base_url = config.twitch_rtmp_url.rstrip("/")
        key = config.twitch_stream_key.strip()
        return f"{base_url}/{key}"

    @staticmethod
    def get_masked_destination_url() -> str:
        base_url = config.twitch_rtmp_url.rstrip("/")
        masked_key = config.get_masked_twitch_stream_key()
        return f"{base_url}/{masked_key}" if masked_key else f"{base_url}/[NO_KEY]"

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        is_valid, error_msg = cls.validate_credentials()
        return {
            "is_enabled": config.twitch_enabled,
            "is_configured": bool(config.twitch_stream_key),
            "is_valid": is_valid,
            "error_message": error_msg,
            "rtmp_url": config.twitch_rtmp_url,
            "masked_destination": cls.get_masked_destination_url(),
        }


twitch_manager = TwitchManager()
