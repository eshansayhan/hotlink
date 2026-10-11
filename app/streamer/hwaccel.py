import os
import shutil
import subprocess
from typing import Dict, Any, Tuple, Optional
from app.monitoring.logger import stream_logger

class HardwareAccelerationDetector:
    """
    Intelligent hardware acceleration detector and manager for FFmpeg.
    Supports NVIDIA NVENC, Intel QuickSync (QSV), Apple VideoToolbox, and Linux VAAPI,
    with robust automated dry-run testing and seamless fallback to CPU (libx264).
    """

    SUPPORTED_ENCODERS = {
        "nvenc": "h264_nvenc",
        "qsv": "h264_qsv",
        "videotoolbox": "h264_videotoolbox",
        "vaapi": "h264_vaapi",
        "cpu": "libx264"
    }

    _detected_encoder: Optional[str] = None
    _detection_details: Optional[str] = None

    @classmethod
    def test_encoder(cls, ffmpeg_bin: str, encoder: str) -> bool:
        """
        Runs an ultra-fast in-memory dry-run test with the given encoder
        to verify that the GPU driver and FFmpeg build truly support it.
        """
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "color=c=black:s=64x64:d=0.1",
            "-c:v", encoder,
            "-f", "null",
            "-"
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                check=False
            )
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def detect_best_encoder(cls, ffmpeg_bin: str, requested_mode: str = "auto") -> Tuple[str, str]:
        """
        Detects the best available video encoder based on user request ('auto', 'cpu', 'nvenc', etc.)
        and verified hardware availability.
        Returns: (encoder_name, description)
        """
        requested_mode = (requested_mode or "auto").lower().strip()

        # If user explicitly forced CPU
        if requested_mode in ("cpu", "libx264", "software"):
            return "libx264", "CPU (libx264 Software Encoder)"

        # If user explicitly requested an encoder
        if requested_mode in cls.SUPPORTED_ENCODERS and requested_mode != "auto":
            target_encoder = cls.SUPPORTED_ENCODERS[requested_mode]
            if cls.test_encoder(ffmpeg_bin, target_encoder):
                desc = f"Hardware Accelerated ({target_encoder.upper()})"
                return target_encoder, desc
            else:
                stream_logger.warn("HWACCEL", f"Requested encoder '{target_encoder}' failed validation. Falling back to CPU.")
                return "libx264", "CPU (libx264 Fallback - Requested GPU Unavailable)"

        # AUTO MODE: Check in order of performance
        # 1. NVIDIA NVENC
        if cls.test_encoder(ffmpeg_bin, "h264_nvenc"):
            return "h264_nvenc", "NVIDIA GPU (h264_nvenc Hardware Acceleration)"

        # 2. Intel QuickSync (QSV)
        if cls.test_encoder(ffmpeg_bin, "h264_qsv"):
            return "h264_qsv", "Intel QuickSync (h264_qsv Hardware Acceleration)"

        # 3. Apple VideoToolbox (macOS)
        if cls.test_encoder(ffmpeg_bin, "h264_videotoolbox"):
            return "h264_videotoolbox", "Apple VideoToolbox (Hardware Acceleration)"

        # 4. VAAPI (Linux)
        if cls.test_encoder(ffmpeg_bin, "h264_vaapi"):
            return "h264_vaapi", "Linux VAAPI (Hardware Acceleration)"

        # Default fallback: libx264 CPU
        return "libx264", "CPU (libx264 Software Encoder)"

    @classmethod
    def get_encoder_settings(cls, encoder: str, requested_preset: str = "veryfast") -> Dict[str, Any]:
        """
        Returns optimized FFmpeg flags suited for the selected encoder.
        """
        flags: list = ["-c:v", encoder]

        if encoder == "h264_nvenc":
            # NVENC presets: p1 to p7 or fast, medium, slow
            nvenc_preset_map = {
                "ultrafast": "p1",
                "superfast": "p2",
                "veryfast": "p3",
                "faster": "p4",
                "fast": "p4",
                "medium": "p5",
                "slow": "p6",
                "slower": "p7",
                "veryslow": "p7"
            }
            p = nvenc_preset_map.get(requested_preset.lower(), "p4")
            flags.extend([
                "-preset", p,
                "-tune", "ll",  # low latency tuning
                "-rc", "cbr",   # constant bitrate for live streaming
            ])

        elif encoder == "h264_qsv":
            qsv_preset_map = {
                "ultrafast": "veryfast",
                "superfast": "faster",
                "veryfast": "fast",
                "faster": "medium",
                "fast": "medium",
                "medium": "balanced",
                "slow": "quality",
                "veryslow": "veryslow"
            }
            p = qsv_preset_map.get(requested_preset.lower(), "balanced")
            flags.extend([
                "-preset", p,
            ])

        elif encoder == "h264_videotoolbox":
            flags.extend([
                "-realtime", "1",
            ])

        else:
            # Default libx264 CPU settings - Optimized for low CPU live streaming
            flags.extend([
                "-preset", requested_preset or "veryfast",
                "-tune", "zerolatency",
                "-x264-params", "no-scenecut=1:rc-lookahead=0:sync-lookahead=0",
                "-threads", "0",
            ])

        return {"flags": flags, "encoder": encoder}


hwaccel_detector = HardwareAccelerationDetector()
