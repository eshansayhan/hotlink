import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import VIDEOS_DIR
from app.monitoring.logger import stream_logger

PLAYLIST_FILE = VIDEOS_DIR / "playlist.json"


class PlaylistManager:
    def __init__(self):
        self.items: List[Dict[str, Any]] = []
        self.current_index: int = 0
        self.load()

    def load(self):
        """Load playlist from playlist.json."""
        if PLAYLIST_FILE.exists():
            try:
                with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.items = data.get("items", [])
                    self.current_index = data.get("current_index", 0)
            except Exception as e:
                stream_logger.warn("PLAYLIST", f"Failed to load playlist file: {e}")
                self.items = []
                self.current_index = 0
        else:
            self.items = []
            self.current_index = 0

    def save(self):
        """Save playlist items and state to disk."""
        try:
            with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "items": self.items,
                    "current_index": self.current_index
                }, f, indent=2)
        except Exception as e:
            stream_logger.error("PLAYLIST", f"Failed to save playlist: {e}")

    def get_playlist(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "current_index": self.current_index,
            "total": len(self.items),
        }

    def set_items(self, new_items: List[Dict[str, Any]]):
        self.items = new_items
        if self.current_index >= len(self.items):
            self.current_index = 0
        self.save()

    def add_item(self, source: str, title: Optional[str] = None):
        title = title or Path(source).name
        self.items.append({
            "id": len(self.items) + 1,
            "source": source,
            "title": title
        })
        self.save()

    def remove_item(self, index: int):
        if 0 <= index < len(self.items):
            self.items.pop(index)
            if self.current_index >= len(self.items):
                self.current_index = 0
            self.save()

    def next_item(self) -> Optional[Dict[str, Any]]:
        if not self.items:
            return None
        self.current_index = (self.current_index + 1) % len(self.items)
        self.save()
        return self.items[self.current_index]

    def current_item(self) -> Optional[Dict[str, Any]]:
        if not self.items:
            return None
        if self.current_index >= len(self.items):
            self.current_index = 0
        return self.items[self.current_index]

    def generate_concat_file(self) -> Optional[Path]:
        """Generates an FFmpeg concat demuxer file for smooth seamless multi-video playback."""
        if not self.items:
            return None

        concat_path = VIDEOS_DIR / "concat_playlist.txt"
        with open(concat_path, "w", encoding="utf-8") as f:
            for item in self.items:
                source = item.get("source", "")
                # Format for ffmpeg concat: file 'filepath'
                # escape single quotes
                safe_path = source.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        return concat_path


playlist_manager = PlaylistManager()
