import asyncio
import datetime
import logging
import sys
from collections import deque
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import config, LOGS_DIR

# Keep maximum 500 log items in memory for live web viewer
MAX_IN_MEMORY_LOGS = 500
LOG_FILE_PATH = LOGS_DIR / "stream.log"


class StreamLogger:
    def __init__(self):
        self.logs: deque = deque(maxlen=MAX_IN_MEMORY_LOGS)
        self._listeners: set = set()
        self._setup_file_logger()

    def _setup_file_logger(self):
        self.file_logger = logging.getLogger("stream_system")
        self.file_logger.setLevel(logging.INFO)
        self.file_logger.handlers.clear()

        # Rotating/file handler
        fh = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
        fh.setFormatter(formatter)
        self.file_logger.addHandler(fh)

        # Console handler with safe UTF-8 encoding
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        self.file_logger.addHandler(ch)

    def _sanitize(self, message: Any) -> str:
        """Sanitize secrets like Stream Keys and Session IDs from any logged text."""
        msg_str = str(message)
        if config.youtube_stream_key and len(config.youtube_stream_key) > 4:
            msg_str = msg_str.replace(config.youtube_stream_key, "••••[REDACTED_STREAM_KEY]••••")
        if config.kick_stream_key and len(config.kick_stream_key) > 4:
            msg_str = msg_str.replace(config.kick_stream_key, "••••[REDACTED_KICK_KEY]••••")
        if config.tiktok_stream_key and len(config.tiktok_stream_key) > 4:
            msg_str = msg_str.replace(config.tiktok_stream_key, "••••[REDACTED_TIKTOK_KEY]••••")
        if config.tiktok_session_id and len(config.tiktok_session_id) > 4:
            msg_str = msg_str.replace(config.tiktok_session_id, "••••[REDACTED_SESSION_ID]••••")
        return msg_str

    def log(self, level: str, tag: str, message: str) -> Dict[str, Any]:
        """Record log in memory, write to file, and notify live listeners."""
        safe_msg = self._sanitize(message)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entry = {
            "timestamp": timestamp,
            "level": level.upper(),
            "tag": tag,
            "message": safe_msg,
        }

        self.logs.append(entry)

        # File & Console logger
        if level.upper() == "ERROR":
            self.file_logger.error(f"[{tag}] {safe_msg}")
        elif level.upper() == "WARN" or level.upper() == "WARNING":
            self.file_logger.warning(f"[{tag}] {safe_msg}")
        else:
            self.file_logger.info(f"[{tag}] {safe_msg}")

        # Broadcast asynchronously to any connected web viewers
        self._notify_listeners(entry)
        return entry

    def debug(self, tag: str, message: str):
        return self.log("DEBUG", tag, message)

    def info(self, tag: str, message: str):
        return self.log("INFO", tag, message)

    def warn(self, tag: str, message: str):
        return self.log("WARN", tag, message)

    def error(self, tag: str, message: str):
        return self.log("ERROR", tag, message)

    def ffmpeg(self, message: str):
        return self.log("FFMPEG", "FFMPEG", message)

    def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.logs)[-limit:]

    def clear(self):
        self.logs.clear()

    def register_listener(self, queue: asyncio.Queue):
        self._listeners.add(queue)

    def unregister_listener(self, queue: asyncio.Queue):
        self._listeners.discard(queue)

    def _notify_listeners(self, entry: Dict[str, Any]):
        for queue in list(self._listeners):
            try:
                queue.put_nowait(entry)
            except Exception:
                pass


stream_logger = StreamLogger()
