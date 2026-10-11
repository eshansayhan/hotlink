import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple
import requests

from app.config import config, BASE_DIR, VIDEOS_DIR
from app.monitoring.logger import stream_logger


class VideoValidator:
    @staticmethod
    def is_url(source: str) -> bool:
        """Check if source string is an HTTP/HTTPS or RTMP URL."""
        return source.startswith("http://") or source.startswith("https://") or source.startswith("rtmp://") or source.startswith("rtmps://")

    @classmethod
    def resolve_path(cls, source: str) -> Tuple[bool, str, str]:
        """
        Resolves video source location.
        Returns: (is_valid, resolved_target, error_message)
        """
        source = source.strip().strip('"').strip("'")
        if not source:
            return False, "", "Video source is empty."

        # Automatically convert Hugging Face blob viewer URLs to direct raw streaming URLs
        if "huggingface.co" in source and "/blob/" in source:
            source = source.replace("/blob/", "/resolve/")

        if cls.is_url(source):
            # Check URL connectivity
            try:
                # Use stream=True and header Range to avoid downloading full file
                resp = requests.head(source, timeout=8, allow_redirects=True)
                if resp.status_code >= 400:
                    # Some servers reject HEAD requests, fallback to GET with range
                    resp = requests.get(source, headers={"Range": "bytes=0-1024"}, timeout=8, stream=True)
                
                if resp.status_code < 400:
                    return True, source, ""
                return False, source, f"Remote URL returned HTTP status {resp.status_code}"
            except Exception as e:
                # If network fails or timeout, log warning but allow URL in case it's an internal or authenticated stream
                stream_logger.warn("VALIDATOR", f"URL probe warning for {source}: {e}")
                return True, source, ""

        # Local file checks: check relative to VIDEOS_DIR, BASE_DIR, filename fallback, or absolute
        candidates = [
            Path(source),
            VIDEOS_DIR / source,
            VIDEOS_DIR / Path(source).name,
            BASE_DIR / source,
            BASE_DIR / Path(source).name,
        ]

        for p in candidates:
            if p.exists() and p.is_file():
                if p.stat().st_size > 0:
                    return True, str(p.resolve()), ""
                else:
                    return False, str(p.resolve()), f"File {p.name} is 0 bytes."

        # Smart fallback 1: if requested source is missing but videos/video.mp4 exists
        fallback_video = VIDEOS_DIR / "video.mp4"
        if fallback_video.exists() and fallback_video.is_file() and fallback_video.stat().st_size > 0:
            stream_logger.info("VALIDATOR", f"Requested '{source}' not found; using '{fallback_video.name}'.")
            return True, str(fallback_video.resolve()), ""

        # Smart fallback 2: find any valid video file in VIDEOS_DIR or BASE_DIR
        supported_exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".ts", ".video"}
        for search_dir in [VIDEOS_DIR, BASE_DIR]:
            if search_dir.exists():
                for f in search_dir.iterdir():
                    if f.is_file() and (f.suffix.lower() in supported_exts or f.name.endswith(".video")) and f.stat().st_size > 1024:
                        stream_logger.info("VALIDATOR", f"Requested '{source}' not found; using existing fallback video: '{f.name}'.")
                        return True, str(f.resolve()), ""

        # Smart fallback 3: auto-generate a high-quality standby test loop video using FFmpeg
        try:
            from app.video.source import source_manager
            standby_res = source_manager.create_sample_video("standby.mp4", duration=15)
            if standby_res.get("success") and standby_res.get("path"):
                stream_logger.info("VALIDATOR", f"Requested '{source}' not found. Automatically generated and activated standby test loop: {standby_res['path']}")
                return True, standby_res["path"], ""
        except Exception as e:
            stream_logger.warn("VALIDATOR", f"Failed to auto-generate standby video: {e}")

        return False, source, f"Local file not found: {source} (checked {VIDEOS_DIR} and {BASE_DIR})"

    @classmethod
    def resolve_source(cls, source: str) -> Tuple[bool, str, str]:
        """Alias for resolve_path."""
        return cls.resolve_path(source)

    @classmethod
    def probe_metadata(cls, target: str) -> Dict[str, Any]:
        """Run ffprobe to extract video information (duration, resolution, fps, codecs)."""
        ffprobe_bin = shutil.which(config.ffprobe_path) or config.ffprobe_path
        info: Dict[str, Any] = {
            "duration": None,
            "width": None,
            "height": None,
            "fps": None,
            "video_codec": None,
            "audio_codec": None,
            "has_video": False,
            "has_audio": False,
        }

        try:
            cmd = [
                ffprobe_bin,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                target
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                streams = data.get("streams", [])
                format_info = data.get("format", {})

                duration_val = format_info.get("duration")
                if duration_val:
                    try:
                        info["duration"] = round(float(duration_val), 2)
                    except ValueError:
                        pass

                for stream in streams:
                    codec_type = stream.get("codec_type")
                    if codec_type == "video" and not info["has_video"]:
                        info["has_video"] = True
                        info["video_codec"] = stream.get("codec_name")
                        info["width"] = stream.get("width")
                        info["height"] = stream.get("height")
                        # Parse frame rate
                        r_frame_rate = stream.get("r_frame_rate", "")
                        if "/" in r_frame_rate:
                            num, den = r_frame_rate.split("/")
                            if float(den) > 0:
                                info["fps"] = round(float(num) / float(den), 2)
                    elif codec_type == "audio" and not info["has_audio"]:
                        info["has_audio"] = True
                        info["audio_codec"] = stream.get("codec_name")

        except Exception as e:
            # ffprobe might not be installed or source is not locally probeable
            pass

        return info


video_validator = VideoValidator()
