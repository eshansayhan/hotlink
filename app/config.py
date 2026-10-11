import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
LOCAL_ENV_FILE = BASE_DIR / ".env.local"
VIDEOS_DIR = BASE_DIR / "videos"
LOGS_DIR = BASE_DIR / "logs"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Load existing .env if present
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()
if LOCAL_ENV_FILE.exists():
    load_dotenv(dotenv_path=LOCAL_ENV_FILE, override=True)


class AppConfig:
    def __init__(self):
        self.reload()

    def reload(self):
        """Reload configuration from environment variables."""
        if ENV_FILE.exists():
            load_dotenv(dotenv_path=ENV_FILE, override=True)
        if LOCAL_ENV_FILE.exists():
            load_dotenv(dotenv_path=LOCAL_ENV_FILE, override=True)

        self.port: int = int(os.getenv("PORT", "7860"))
        self.host: str = os.getenv("HOST", "0.0.0.0")

        # YouTube RTMP Settings
        self.youtube_enabled: bool = os.getenv("YOUTUBE_ENABLED", "true").lower() in ("true", "1", "yes", "on")
        self.youtube_rtmp_url: str = os.getenv("YOUTUBE_RTMP_URL", "rtmp://a.rtmp.youtube.com/live2").strip()
        self.youtube_stream_key: str = os.getenv("YOUTUBE_STREAM_KEY", "").strip()

        # Kick RTMP Settings
        self.kick_enabled: bool = os.getenv("KICK_ENABLED", "true").lower() in ("true", "1", "yes", "on")
        self.kick_rtmp_url: str = os.getenv("KICK_RTMP_URL", "rtmps://fa723fc1b171.global-contribute.live-video.net/app").strip()
        self.kick_stream_key: str = os.getenv("KICK_STREAM_KEY", "sk_us-west-2_kUbclakx6168_dzuMJSwCju6G8RX9s721cRkTMF4A3m").strip()

        # Twitch RTMP Settings
        self.twitch_enabled: bool = os.getenv("TWITCH_ENABLED", "true").lower() in ("true", "1", "yes", "on")
        self.twitch_rtmp_url: str = os.getenv("TWITCH_RTMP_URL", "rtmp://live.twitch.tv/app").strip()
        self.twitch_stream_key: str = os.getenv("TWITCH_STREAM_KEY", "").strip()

        # Nimo TV RTMP Settings
        self.nimo_enabled: bool = os.getenv("NIMO_ENABLED", "false").lower() in ("true", "1", "yes", "on")
        self.nimo_rtmp_url: str = os.getenv("NIMO_RTMP_URL", "rtmp://alpush.rtmp.nimo.tv/live/").strip()
        self.nimo_stream_key: str = os.getenv("NIMO_STREAM_KEY", "").strip()

        # TikTok RTMP Settings
        self.tiktok_enabled: bool = os.getenv("TIKTOK_ENABLED", "true").lower() in ("true", "1", "yes", "on")
        self.tiktok_rtmp_url: str = os.getenv("TIKTOK_RTMP_URL", "rtmp://live-push.tiktok.com/live/").strip()
        self.tiktok_stream_key: str = os.getenv("TIKTOK_STREAM_KEY", "").strip()
        self.tiktok_session_id: str = os.getenv("TIKTOK_SESSION_ID", "").strip()
        self.tiktok_room_id: str = os.getenv("TIKTOK_ROOM_ID", "").strip()
        self.tiktok_event_id: str = os.getenv("TIKTOK_EVENT_ID", "").strip()
        self.tiktok_room_event_id: str = os.getenv("TIKTOK_ROOM_EVENT_ID", "").strip()
        self.tiktok_title: str = os.getenv("TIKTOK_TITLE", "24/7 Live Stream").strip()

        # Video Source (defaults to video.mp4)
        self.video_source: str = os.getenv("VIDEO_SOURCE", "video.mp4").strip()

        # Encoding Settings (defaults to 1080x1920 9:16 for YouTube Shorts Mobile Live)
        self.stream_width: int = int(os.getenv("STREAM_WIDTH", "1080"))
        self.stream_height: int = int(os.getenv("STREAM_HEIGHT", "1920"))
        self.stream_fps: int = int(os.getenv("STREAM_FPS", "30"))
        self.stream_bitrate: str = os.getenv("STREAM_BITRATE", "4500k").strip()
        self.stream_audio_bitrate: str = os.getenv("STREAM_AUDIO_BITRATE", "160k").strip()
        self.stream_preset: str = os.getenv("STREAM_PRESET", "veryfast").strip()
        self.hw_accel: str = os.getenv("HW_ACCEL", "auto").strip().lower()

        # Automation & Loop
        self.video_loop: bool = os.getenv("VIDEO_LOOP", "true").lower() in ("true", "1", "yes", "on")
        self.auto_start: bool = os.getenv("AUTO_START", "false").lower() in ("true", "1", "yes", "on")

        # Watchdog & Recovery
        self.reconnect_enabled: bool = os.getenv("RECONNECT_ENABLED", "true").lower() in ("true", "1", "yes", "on")
        self.reconnect_initial_delay: int = int(os.getenv("RECONNECT_INITIAL_DELAY", "5"))
        self.reconnect_max_delay: int = int(os.getenv("RECONNECT_MAX_DELAY", "60"))
        self.reconnect_max_retries: int = int(os.getenv("RECONNECT_MAX_RETRIES", "0"))  # 0 = infinite

        # Binaries
        self.ffmpeg_path: str = os.getenv("FFMPEG_PATH", "ffmpeg").strip()
        self.ffprobe_path: str = os.getenv("FFPROBE_PATH", "ffprobe").strip()

        # Security
        self.admin_password: str = os.getenv("ADMIN_PASSWORD", "").strip()

    def get_masked_stream_key(self) -> str:
        """Returns YouTube stream key masked for UI safety."""
        if not self.youtube_stream_key:
            return ""
        if len(self.youtube_stream_key) <= 4:
            return "••••"
        return "••••••••" + self.youtube_stream_key[-4:]

    def get_masked_kick_stream_key(self) -> str:
        """Returns Kick stream key masked for UI safety."""
        if not self.kick_stream_key:
            return ""
        if len(self.kick_stream_key) <= 6:
            return "••••••"
        return "••••••••" + self.kick_stream_key[-4:]

    def get_masked_twitch_stream_key(self) -> str:
        """Returns Twitch stream key masked for UI safety."""
        if not self.twitch_stream_key:
            return ""
        if len(self.twitch_stream_key) <= 4:
            return "••••"
        return "••••••••" + self.twitch_stream_key[-4:]

    def get_masked_nimo_stream_key(self) -> str:
        """Returns Nimo stream key masked for UI safety."""
        if not self.nimo_stream_key:
            return ""
        if len(self.nimo_stream_key) <= 4:
            return "••••"
        return "••••••••" + self.nimo_stream_key[-4:]

    def get_masked_tiktok_stream_key(self) -> str:
        """Returns TikTok stream key masked for UI safety."""
        if not self.tiktok_stream_key:
            return ""
        if len(self.tiktok_stream_key) <= 4:
            return "••••"
        return "••••••••" + self.tiktok_stream_key[-4:]

    def get_masked_tiktok_session_id(self) -> str:
        """Returns TikTok session id masked for UI safety."""
        if not self.tiktok_session_id:
            return ""
        if len(self.tiktok_session_id) <= 6:
            return "••••••"
        return "••••••••" + self.tiktok_session_id[-4:]

    def to_dict(self, mask_secret: bool = True) -> dict:
        """Export config as dictionary."""
        active_dest_count = sum([
            bool(self.youtube_enabled and self.youtube_stream_key),
            bool(self.kick_enabled and self.kick_stream_key),
            bool(self.twitch_enabled and self.twitch_stream_key),
            bool(self.nimo_enabled and self.nimo_stream_key),
            bool(self.tiktok_enabled and self.tiktok_stream_key),
        ])
        return {
            "port": self.port,
            "host": self.host,
            "youtube_enabled": self.youtube_enabled,
            "youtube_rtmp_url": self.youtube_rtmp_url,
            "youtube_stream_key": self.get_masked_stream_key() if mask_secret else self.youtube_stream_key,
            "has_stream_key": bool(self.youtube_stream_key),
            "kick_enabled": self.kick_enabled,
            "kick_rtmp_url": self.kick_rtmp_url,
            "kick_stream_key": self.get_masked_kick_stream_key() if mask_secret else self.kick_stream_key,
            "has_kick_stream_key": bool(self.kick_stream_key),
            "twitch_enabled": self.twitch_enabled,
            "twitch_rtmp_url": self.twitch_rtmp_url,
            "twitch_stream_key": self.get_masked_twitch_stream_key() if mask_secret else self.twitch_stream_key,
            "has_twitch_stream_key": bool(self.twitch_stream_key),
            "nimo_enabled": self.nimo_enabled,
            "nimo_rtmp_url": self.nimo_rtmp_url,
            "nimo_stream_key": self.get_masked_nimo_stream_key() if mask_secret else self.nimo_stream_key,
            "has_nimo_stream_key": bool(self.nimo_stream_key),
            "tiktok_enabled": self.tiktok_enabled,
            "tiktok_rtmp_url": self.tiktok_rtmp_url,
            "tiktok_stream_key": self.get_masked_tiktok_stream_key() if mask_secret else self.tiktok_stream_key,
            "tiktok_session_id": self.get_masked_tiktok_session_id() if mask_secret else self.tiktok_session_id,
            "tiktok_room_id": self.tiktok_room_id,
            "tiktok_event_id": self.tiktok_event_id,
            "tiktok_title": self.tiktok_title,
            "has_tiktok_stream_key": bool(self.tiktok_stream_key),
            "has_tiktok_session_id": bool(self.tiktok_session_id),
            "is_multistream": active_dest_count > 1,
            "video_source": self.video_source,
            "stream_width": self.stream_width,
            "stream_height": self.stream_height,
            "stream_fps": self.stream_fps,
            "stream_bitrate": self.stream_bitrate,
            "stream_audio_bitrate": self.stream_audio_bitrate,
            "stream_preset": self.stream_preset,
            "hw_accel": self.hw_accel,
            "video_loop": self.video_loop,
            "auto_start": self.auto_start,
            "reconnect_enabled": self.reconnect_enabled,
            "reconnect_initial_delay": self.reconnect_initial_delay,
            "reconnect_max_delay": self.reconnect_max_delay,
            "reconnect_max_retries": self.reconnect_max_retries,
            "ffmpeg_path": self.ffmpeg_path,
            "ffprobe_path": self.ffprobe_path,
            "has_admin_password": bool(self.admin_password),
        }

    def update(self, updates: dict, persist: bool = True) -> None:
        """Update runtime config and optionally write changes back to .env file."""
        key_mapping = {
            "youtube_enabled": "YOUTUBE_ENABLED",
            "youtube_rtmp_url": "YOUTUBE_RTMP_URL",
            "youtube_stream_key": "YOUTUBE_STREAM_KEY",
            "kick_enabled": "KICK_ENABLED",
            "kick_rtmp_url": "KICK_RTMP_URL",
            "kick_stream_key": "KICK_STREAM_KEY",
            "twitch_enabled": "TWITCH_ENABLED",
            "twitch_rtmp_url": "TWITCH_RTMP_URL",
            "twitch_stream_key": "TWITCH_STREAM_KEY",
            "nimo_enabled": "NIMO_ENABLED",
            "nimo_rtmp_url": "NIMO_RTMP_URL",
            "nimo_stream_key": "NIMO_STREAM_KEY",
            "tiktok_enabled": "TIKTOK_ENABLED",
            "tiktok_rtmp_url": "TIKTOK_RTMP_URL",
            "tiktok_stream_key": "TIKTOK_STREAM_KEY",
            "tiktok_session_id": "TIKTOK_SESSION_ID",
            "tiktok_room_id": "TIKTOK_ROOM_ID",
            "tiktok_event_id": "TIKTOK_EVENT_ID",
            "tiktok_room_event_id": "TIKTOK_ROOM_EVENT_ID",
            "tiktok_title": "TIKTOK_TITLE",
            "video_source": "VIDEO_SOURCE",
            "stream_width": "STREAM_WIDTH",
            "stream_height": "STREAM_HEIGHT",
            "stream_fps": "STREAM_FPS",
            "stream_bitrate": "STREAM_BITRATE",
            "stream_audio_bitrate": "STREAM_AUDIO_BITRATE",
            "stream_preset": "STREAM_PRESET",
            "hw_accel": "HW_ACCEL",
            "video_loop": "VIDEO_LOOP",
            "auto_start": "AUTO_START",
            "reconnect_enabled": "RECONNECT_ENABLED",
            "reconnect_initial_delay": "RECONNECT_INITIAL_DELAY",
            "reconnect_max_delay": "RECONNECT_MAX_DELAY",
            "reconnect_max_retries": "RECONNECT_MAX_RETRIES",
            "ffmpeg_path": "FFMPEG_PATH",
            "ffprobe_path": "FFPROBE_PATH",
            "admin_password": "ADMIN_PASSWORD",
        }

        env_updates = {}
        force_clear = updates.get("__force_clear__", False)
        for k, v in updates.items():
            if k == "__force_clear__":
                continue
            if k in key_mapping and v is not None:
                # Avoid overwriting secrets if incoming value is masked
                if k in ("youtube_stream_key", "kick_stream_key", "twitch_stream_key", "nimo_stream_key", "admin_password", "tiktok_session_id"):
                    if not v or v.startswith("••••"):
                        continue
                if k == "tiktok_stream_key" and not force_clear:
                    if v.startswith("••••"):
                        continue
                env_var = key_mapping[k]
                if isinstance(v, bool):
                    val_str = "true" if v else "false"
                else:
                    val_str = str(v)
                os.environ[env_var] = val_str
                env_updates[env_var] = val_str

        if persist and env_updates:
            self._save_env_file(env_updates)

        self.reload()

    def reset_tiktok_session(self, persist: bool = True) -> None:
        """Completely clears active TikTok room ID, ephemeral stream key, and resets RTMP URL."""
        self.update({
            "__force_clear__": True,
            "tiktok_room_id": "",
            "tiktok_room_event_id": "",
            "tiktok_stream_key": "",
            "tiktok_rtmp_url": "rtmp://live-push.tiktok.com/live/",
        }, persist=persist)

    def _save_env_file(self, new_vars: dict) -> None:
        """Write key-value pairs into .env file while preserving existing settings."""
        try:
            existing_lines = []
            existing_keys = set()

            if LOCAL_ENV_FILE.exists():
                with open(LOCAL_ENV_FILE, "r", encoding="utf-8") as f:
                    existing_lines = f.readlines()

            new_lines = []
            for line in existing_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in new_vars:
                        new_lines.append(f"{k}={new_vars[k]}\n")
                        existing_keys.add(k)
                        continue
                new_lines.append(line)

            # Append variables not already in the file
            for k, v in new_vars.items():
                if k not in existing_keys:
                    new_lines.append(f"{k}={v}\n")

            with open(LOCAL_ENV_FILE, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            # Non-fatal warning if container environment is read-only
            pass


config = AppConfig()
