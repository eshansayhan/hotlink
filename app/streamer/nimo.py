from typing import Any, Dict, Tuple

from app.config import config


class NimoManager:
    @staticmethod
    def validate_credentials() -> Tuple[bool, str]:
        """Validate the Nimo RTMP endpoint and publish key."""
        url = config.nimo_rtmp_url.strip()
        key = config.nimo_stream_key.strip()

        if not url:
            return False, "Nimo RTMP URL is missing."
        if not (url.startswith("rtmp://") or url.startswith("rtmps://")):
            return False, "Nimo RTMP URL must begin with rtmp:// or rtmps://"
        if not key:
            return False, "Nimo stream key is missing. Enter the key from Nimo Live settings."

        return True, ""

    @staticmethod
    def get_destination_url() -> str:
        base_url = config.nimo_rtmp_url.strip().rstrip("/")
        stream_key = config.nimo_stream_key.strip().lstrip("/")
        return f"{base_url}/{stream_key}"

    @staticmethod
    def get_masked_destination_url() -> str:
        base_url = config.nimo_rtmp_url.strip().rstrip("/")
        masked_key = config.get_masked_nimo_stream_key()
        return f"{base_url}/{masked_key}" if masked_key else f"{base_url}/[NO_KEY]"

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        is_valid, error_message = cls.validate_credentials()
        return {
            "is_enabled": config.nimo_enabled,
            "is_configured": bool(config.nimo_stream_key),
            "is_valid": is_valid,
            "error_message": error_message,
            "rtmp_url": config.nimo_rtmp_url,
            "masked_destination": cls.get_masked_destination_url(),
        }


nimo_manager = NimoManager()
