import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import config, VIDEOS_DIR, BASE_DIR
from app.monitoring.logger import stream_logger
from app.video.validator import video_validator


class SourceManager:
    @staticmethod
    def list_local_videos() -> List[Dict[str, Any]]:
        """List all video files in the videos/ directory."""
        supported_extensions = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".ts", ".video"}
        video_list = []

        if not VIDEOS_DIR.exists():
            VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

        for item in VIDEOS_DIR.iterdir():
            if item.is_file() and (item.suffix.lower() in supported_extensions or item.name.endswith(".video")):
                stat = item.stat()
                size_mb = round(stat.st_size / (1024 * 1024), 2)
                video_list.append({
                    "name": item.name,
                    "path": str(item.resolve()),
                    "size_mb": size_mb,
                    "modified": int(stat.st_mtime),
                    "is_current": (config.video_source == item.name or config.video_source == str(item.resolve())),
                })

        # Also check if root has asd.video or specified source
        root_asd = BASE_DIR / "asd.video"
        if root_asd.exists() and root_asd.is_file():
            stat = root_asd.stat()
            video_list.append({
                "name": "asd.video",
                "path": str(root_asd.resolve()),
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "modified": int(stat.st_mtime),
                "is_current": (config.video_source == "asd.video" or config.video_source == str(root_asd.resolve())),
            })

        return sorted(video_list, key=lambda x: x["name"])

    @classmethod
    def get_current_source_info(cls) -> Dict[str, Any]:
        """Returns details about currently configured video source."""
        source = config.video_source
        is_url = video_validator.is_url(source)
        is_valid, resolved_target, error_msg = video_validator.resolve_path(source)
        metadata = video_validator.probe_metadata(resolved_target) if is_valid else {}

        return {
            "source_raw": source,
            "is_url": is_url,
            "is_valid": is_valid,
            "resolved_target": resolved_target,
            "error_message": error_msg,
            "metadata": metadata,
        }

    @classmethod
    def create_sample_video(cls, filename: str = "asd.video", duration: int = 15) -> Dict[str, Any]:
        """
        Creates a high quality test video with color bars, ticking clock, and 1kHz sine audio
        using FFmpeg if installed, or creates a demo marker file.
        """
        target_path = VIDEOS_DIR / filename
        ffmpeg_bin = shutil.which(config.ffmpeg_path) or config.ffmpeg_path

        stream_logger.info("SOURCE", f"Generating sample test video at {target_path} (duration: {duration}s)...")

        # FFmpeg command to generate test video with SMPTE color bars + moving timecode + stereo audio
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi",
            "-i", f"smptebars=size=1920x1080:rate=30",
            "-f", "lavfi",
            "-i", "sine=frequency=1000:sample_rate=44100",
            "-vf", "drawtext=text='24/7 LIVE STREAM TEST PATTERN %{pts\\:hms}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.6:boxborderw=10:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            str(target_path)
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if res.returncode == 0 and target_path.exists():
                stream_logger.info("SOURCE", f"Sample video generated successfully: {target_path.name}")
                # Also create asd.video symlink or copy to root for quick out-of-the-box experience
                root_copy = BASE_DIR / "asd.video"
                shutil.copy2(target_path, root_copy)
                return {
                    "success": True,
                    "path": str(target_path),
                    "name": target_path.name,
                    "size_mb": round(target_path.stat().st_size / (1024 * 1024), 2),
                }
            else:
                err_msg = res.stderr[-300:] if res.stderr else "Unknown FFmpeg error"
                stream_logger.warn("SOURCE", f"FFmpeg video creation failed: {err_msg}")
                return {"success": False, "error": err_msg}
        except Exception as e:
            stream_logger.error("SOURCE", f"Could not create sample video: {e}")
            return {"success": False, "error": str(e)}


source_manager = SourceManager()
