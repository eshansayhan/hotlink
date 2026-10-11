import os
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Dict, Any, Optional, List

from app.config import config
from app.monitoring.logger import stream_logger
from app.video.validator import video_validator
from app.streamer.youtube import youtube_manager
from app.streamer.kick import kick_manager
from app.streamer.twitch import twitch_manager
from app.streamer.nimo import nimo_manager
from app.streamer.tiktok import tiktok_manager
from app.streamer.loop import loop_controller
from app.streamer.hwaccel import hwaccel_detector
from app.streamer.overlay import overlay_manager
from app.streamer.metadata import metadata_mutator

TIKTOK_AUTO_RETRY_DELAYS: tuple[int, ...] = (30, 60, 120, 300)


class FFmpegStreamer:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.status: str = "STOPPED"  # STOPPED, STARTING, RUNNING, STOPPING, ERROR
        self.start_time: Optional[float] = None
        self.last_error: Optional[str] = None
        self.active_targets: List[str] = []
        self.active_encoder: str = "libx264"
        self.active_encoder_desc: str = "CPU (libx264 Software Encoder)"
        self.last_frame_timestamp: Optional[float] = None
        self.stats: Dict[str, Any] = {
            "fps": 0.0,
            "bitrate": "0kbits/s",
            "speed": "0x",
            "frame": 0,
            "time": "00:00:00",
            "dropped_frames": 0,
            "dup_frames": 0,
        }
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # Background TikTok auto-join remains active until the user stops it.
        self._bg_retry_stop: threading.Event = threading.Event()
        self._bg_retry_thread: Optional[threading.Thread] = None
        self._bg_retry_lock = threading.Lock()
        self._bg_retry_api_lock = threading.Lock()
        self._tiktok_auto_status_lock = threading.Lock()
        self._tiktok_auto_status = "idle"
        self._tiktok_auto_attempts = 0
        self._tiktok_auto_last_error: Optional[str] = None
        self._tiktok_auto_next_retry_at: Optional[float] = None
        self._tiktok_auto_start_requested = False

    def is_running(self) -> bool:
        if self.process is not None:
            return self.process.poll() is None
        return False

    def is_stalled(self, threshold_sec: int = 40) -> bool:
        """
        Detects zombie / frozen streams where the process is technically alive,
        but stopped producing frames (e.g. frozen network socket or pipeline deadlock).
        """
        if not self.is_running() or not self.start_time:
            return False
        # Grace period for startup encoding
        if time.time() - self.start_time < 20:
            return False
        last_active = self.last_frame_timestamp or self.start_time
        return (time.time() - last_active) > threshold_sec

    def get_pid(self) -> Optional[int]:
        if self.process and self.is_running():
            return self.process.pid
        return None

    def get_duration(self) -> float:
        if self.is_running() and self.start_time:
            return time.time() - self.start_time
        return 0.0

    def get_status_info(self) -> Dict[str, Any]:
        running = self.is_running()
        if not running and self.status == "RUNNING":
            self.status = "STOPPED"

        with self._tiktok_auto_status_lock:
            retry_in = None
            if self._tiktok_auto_next_retry_at is not None:
                retry_in = max(0, int(self._tiktok_auto_next_retry_at - time.time()))
            tiktok_automation = {
                "active": self._tiktok_auto_status in ("waiting", "retrying"),
                "status": self._tiktok_auto_status,
                "attempts": self._tiktok_auto_attempts,
                "retry_in_seconds": retry_in,
                "last_error": self._tiktok_auto_last_error,
            }

        duration_sec = self.get_duration()
        total_sec = int(duration_sec)
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        secs = total_sec % 60
        duration_fmt = f"{hours:02d}:{minutes:02d}:{secs:02d}"

        return {
            "status": self.status,
            "is_running": running,
            "pid": self.get_pid(),
            "uptime_seconds": int(duration_sec),
            "uptime_formatted": duration_fmt,
            "fps": self.stats.get("fps", 0.0),
            "bitrate": self.stats.get("bitrate", "0kbits/s"),
            "speed": self.stats.get("speed", "0x"),
            "frame": self.stats.get("frame", 0),
            "time": self.stats.get("time", "00:00:00"),
            "dropped_frames": self.stats.get("dropped_frames", 0),
            "dup_frames": self.stats.get("dup_frames", 0),
            "last_error": self.last_error,
            "active_targets": self.active_targets,
            "active_encoder": self.active_encoder,
            "active_encoder_desc": self.active_encoder_desc,
            "is_multistream": len(self.active_targets) > 1,
            "tiktok_automation": tiktok_automation,
        }

    def build_command(self) -> List[str]:
        """Builds production-grade FFmpeg streaming command with Multi-Stream support."""
        ffmpeg_bin = shutil.which(config.ffmpeg_path) or config.ffmpeg_path

        # 1. Resolve Video Source
        is_valid, resolved_source, err = video_validator.resolve_path(config.video_source)
        if not is_valid:
            raise ValueError(f"Invalid video source: {err}")

        is_url = video_validator.is_url(resolved_source)

        # 2. Resolve Active RTMP Destinations (YouTube, Kick, or both)
        targets: List[tuple] = []
        validation_errors = []

        if config.youtube_enabled:
            is_yt_valid, yt_err = youtube_manager.validate_credentials()
            if is_yt_valid:
                targets.append(("YouTube", youtube_manager.get_destination_url()))
            else:
                validation_errors.append(f"YouTube: {yt_err}")

        if config.kick_enabled:
            is_kick_valid, kick_err = kick_manager.validate_credentials()
            if is_kick_valid:
                targets.append(("Kick", kick_manager.get_destination_url()))
            else:
                validation_errors.append(f"Kick: {kick_err}")

        if config.twitch_enabled:
            is_twitch_valid, twitch_err = twitch_manager.validate_credentials()
            if is_twitch_valid:
                targets.append(("Twitch", twitch_manager.get_destination_url()))
            else:
                validation_errors.append(f"Twitch: {twitch_err}")

        if config.nimo_enabled:
            is_nimo_valid, nimo_err = nimo_manager.validate_credentials()
            if is_nimo_valid:
                targets.append(("Nimo", nimo_manager.get_destination_url()))
            else:
                validation_errors.append(f"Nimo: {nimo_err}")

        if config.tiktok_enabled:
            # Track session readiness to prevent stale key from being used
            tiktok_session_ready = True

            if config.tiktok_session_id:
                # Avoid a second room-creation request while the background worker retries.
                if self.is_tiktok_auto_retry_active():
                    tiktok_session_ready = False
                else:
                    with self._bg_retry_api_lock:
                        tiktok_session_ready = tiktok_manager.ensure_active_session()
                if not tiktok_session_ready:
                    stream_logger.warn(
                        "TIKTOK",
                        "TikTok oturumu hazır değil veya otomatik tekrar denemesi sürüyor. "
                        "Bu yayında TikTok atlanıyor — arka plan otomatik katılım modu aktif olacak."
                    )

            if tiktok_session_ready:
                # Check credentials (freshly generated via session, or manually configured key)
                is_tiktok_valid, tiktok_err = tiktok_manager.validate_credentials()
                if is_tiktok_valid:
                    targets.append(("TikTok", tiktok_manager.get_destination_url()))
                    stream_logger.info("TIKTOK", "TikTok hedefi yayına başarıyla dahil edildi.")
                else:
                    validation_errors.append(f"TikTok: {tiktok_err}")

        if not targets:
            err_details = "; ".join(validation_errors) if validation_errors else "No streaming destinations enabled."
            raise ValueError(f"Broadcast configuration error: {err_details}")

        self.active_targets = [t[0] for t in targets]

        # 3. Input Flags (Rate control, loop, reconnects)
        input_flags = loop_controller.get_input_flags(is_url=is_url, enable_loop=config.video_loop)

        w = config.stream_width
        h = config.stream_height
        fps = config.stream_fps
        gop = fps * 2  # 2-second keyframe interval recommended for YouTube and Kick

        # Buffer size calculation
        try:
            bitrate_num = int(re.sub(r"[^\d]", "", config.stream_bitrate))
            bufsize = f"{bitrate_num * 2}k"
        except Exception:
            bufsize = "9000k"

        # Resolve hardware acceleration encoder and optimal flags
        encoder_name, encoder_desc = hwaccel_detector.detect_best_encoder(ffmpeg_bin, config.hw_accel)
        self.active_encoder = encoder_name
        self.active_encoder_desc = encoder_desc
        stream_logger.info("STREAMER", f"Video Encoder: {encoder_name} ({encoder_desc})")
        enc_settings = hwaccel_detector.get_encoder_settings(encoder_name, config.stream_preset)

        # Scale, pad, noise pertürbasyon ve overlay filtreleri (uptime + TikTok chat)
        scale_filter = overlay_manager.build_video_filter(
            width=w,
            height=h,
            stream_start_time=self.start_time,
            encoder_name=encoder_name
        )

        # Dinamik metadata havuzundan bayrakları al
        metadata_flags = metadata_mutator.get_ffmpeg_flags()

        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "info",
            "-y",
            *input_flags,
            "-i", resolved_source,
            # Explicit stream mapping (required for tee muxer and filters)
            "-map", "0:v:0",
            "-map", "0:a:0?",
            # Dynamic loop metadata injection
            *metadata_flags,
            # Video encoding with hardware acceleration
            "-vf", scale_filter,
            *enc_settings["flags"],
            "-pix_fmt", "yuv420p",
            "-b:v", config.stream_bitrate,
            "-maxrate", config.stream_bitrate,
            "-bufsize", bufsize,
            "-g", str(gop),
            "-keyint_min", str(gop),
            "-r", str(fps),
            # Audio encoding with resync & anti-fingerprint filter to eliminate drift and acoustic hash
            "-af", overlay_manager.build_audio_filter(),
            "-c:a", "aac",
            "-b:a", config.stream_audio_bitrate,
            "-ar", "44100",
            "-ac", "2",
        ]

        if len(targets) == 1:
            # Single destination direct FLV output
            target_name, rtmp_target = targets[0]
            cmd.extend([
                "-flvflags", "no_duration_filesize",
                "-f", "flv",
                rtmp_target
            ])
        else:
            # Multi-Stream: Duplicate output simultaneously to YouTube and Kick via tee muxer
            # onfail=ignore prevents temporary network issues on one platform from killing the entire stream
            tee_parts = [
                f"[f=flv:flvflags=no_duration_filesize:onfail=ignore]{target_url}"
                for _, target_url in targets
            ]
            tee_output = "|".join(tee_parts)
            cmd.extend([
                "-flags", "+global_header",
                "-f", "tee",
                tee_output
            ])

        return cmd

    def start(self) -> bool:
        """Start FFmpeg live streaming process."""
        with self._lock:
            if self.is_running():
                stream_logger.warn("FFMPEG", "FFmpeg process is already running.")
                return True

            self.status = "STARTING"
            self.last_error = None
            self.last_frame_timestamp = time.time()
            self.stats = {
                "fps": 0.0,
                "bitrate": "0kbits/s",
                "speed": "0x",
                "frame": 0,
                "time": "00:00:00",
                "dropped_frames": 0,
                "dup_frames": 0,
            }

            try:
                tiktok_manager._last_session_unavailable = False
                cmd = self.build_command()
                is_valid, resolved_src, _ = video_validator.resolve_path(config.video_source)
                if is_valid:
                    metadata_mutator.on_stream_start(resolved_src, config.ffprobe_path)

                # Print safe command line without exposing any stream keys
                safe_cmd = []
                for c in cmd:
                    val = c
                    if config.youtube_stream_key and config.youtube_stream_key in val:
                        val = val.replace(config.youtube_stream_key, "[YOUTUBE_KEY]")
                    if config.kick_stream_key and config.kick_stream_key in val:
                        val = val.replace(config.kick_stream_key, "[KICK_KEY]")
                    if config.twitch_stream_key and config.twitch_stream_key in val:
                        val = val.replace(config.twitch_stream_key, "[TWITCH_KEY]")
                    if config.nimo_stream_key and config.nimo_stream_key in val:
                        val = val.replace(config.nimo_stream_key, "[NIMO_KEY]")
                    if config.tiktok_stream_key and config.tiktok_stream_key in val:
                        val = val.replace(config.tiktok_stream_key, "[TIKTOK_KEY]")
                    safe_cmd.append(val)
                safe_cmd_str = " ".join(safe_cmd)
                stream_logger.info("FFMPEG", f"Starting FFmpeg process: {safe_cmd_str}")

                # Launch process
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                self.start_time = time.time()
                self.last_frame_timestamp = time.time()
                self.status = "RUNNING"
                stream_logger.info("FFMPEG", f"FFmpeg started successfully with PID {self.process.pid}")

                # Start background log and stats reader thread
                self._reader_thread = threading.Thread(target=self._read_stderr_loop, daemon=True)
                self._reader_thread.start()

                # Keep retrying TikTok if its room could not be prepared before stream start.
                if (
                    config.tiktok_enabled
                    and config.tiktok_session_id
                    and "TikTok" not in self.active_targets
                    and tiktok_manager._last_session_unavailable
                ):
                    tiktok_manager._last_session_unavailable = False
                    self.start_tiktok_auto_retry(start_stream_on_success=False)

                return True

            except ValueError as e:
                if (
                    config.tiktok_enabled
                    and config.tiktok_session_id
                    and (tiktok_manager._last_session_unavailable or self.is_tiktok_auto_retry_active())
                ):
                    self.status = "WAITING_TIKTOK"
                    self.last_error = str(e)
                    self.active_targets = []
                    stream_logger.warn(
                        "TIKTOK",
                        "TikTok tek etkin hedef ve oda henüz hazır değil. Yayın isteği kuyruklandı; "
                        "oda açılınca FFmpeg otomatik başlatılacak."
                    )
                    self.start_tiktok_auto_retry(
                        start_stream_on_success=True,
                        initial_delay_sec=TIKTOK_AUTO_RETRY_DELAYS[0],
                    )
                    return True

                self.status = "ERROR"
                self.last_error = str(e)
                stream_logger.error("FFMPEG", f"Failed to start FFmpeg: {e}")
                return False
            except FileNotFoundError:
                err = f"FFmpeg executable not found at '{config.ffmpeg_path}'. Please install FFmpeg or set FFMPEG_PATH."
                self.status = "ERROR"
                self.last_error = err
                stream_logger.error("FFMPEG", err)
                return False
            except Exception as e:
                self.status = "ERROR"
                self.last_error = str(e)
                stream_logger.error("FFMPEG", f"Failed to start FFmpeg: {e}")
                return False

    def _read_stderr_loop(self):
        """Reads FFmpeg output in real-time, extracts telemetry stats, and forwards logs."""
        if not self.process or not self.process.stderr:
            return

        stat_pattern = re.compile(
            r"frame=\s*(\d+)\s+fps=\s*([\d\.]+).*?time=\s*([\d:\.]+).*?bitrate=\s*(\S+)(?:.*?dup=\s*(\d+))?(?:.*?drop=\s*(\d+))?(?:.*?speed=\s*([\d\.]+x))?"
        )

        try:
            for raw_line in iter(self.process.stderr.readline, ''):
                line = raw_line.strip()
                if not line:
                    continue

                # Match stats lines
                match = stat_pattern.search(line)
                if match:
                    try:
                        self.last_frame_timestamp = time.time()
                        self.stats["frame"] = int(match.group(1))
                        self.stats["fps"] = float(match.group(2))
                        time_val = match.group(3).split(".")[0]
                        self.stats["time"] = time_val
                        # Video loop ve metadata güncelleme kontrolü
                        metadata_mutator.on_stats_update(time_val)
                        br = match.group(4)
                        self.stats["bitrate"] = br if br != "N/A" else config.stream_bitrate
                        if match.group(5):
                            self.stats["dup_frames"] = int(match.group(5))
                        if match.group(6):
                            self.stats["dropped_frames"] = int(match.group(6))
                        if match.group(7):
                            self.stats["speed"] = match.group(7)
                    except Exception:
                        pass
                else:
                    # Regular log or warning/error
                    if "error" in line.lower() or "failed" in line.lower():
                        self.last_error = line
                        stream_logger.error("FFMPEG", line)
                    elif "warning" in line.lower():
                        stream_logger.warn("FFMPEG", line)
                    else:
                        stream_logger.ffmpeg(line)

            self.process.stderr.close()
        except Exception as e:
            stream_logger.warn("FFMPEG", f"Stderr reader closed: {e}")

        # Process exited
        return_code = self.process.poll() if self.process else None
        if self.status != "STOPPING":
            if return_code is not None and return_code != 0:
                self.status = "ERROR"
                msg = f"FFmpeg exited unexpectedly with exit code {return_code}"
                if not self.last_error:
                    self.last_error = msg
                stream_logger.error("FFMPEG", msg)
            else:
                self.status = "STOPPED"
                stream_logger.info("FFMPEG", f"FFmpeg stream finished (code {return_code}).")

    def stop(self, preserve_tiktok_room: bool = False) -> bool:
        """Gracefully stop FFmpeg process."""
        self.stop_tiktok_auto_retry()
        with self._lock:
            if self.is_running():
                self.status = "STOPPING"
                stream_logger.info("FFMPEG", f"Stopping FFmpeg stream (PID {self.process.pid})...")
                try:
                    if self.process.stdin:
                        try:
                            self.process.stdin.write("q\n")
                            self.process.stdin.flush()
                        except OSError as e:
                            stream_logger.warn("FFMPEG", f"Could not send graceful stop to FFmpeg: {e}")

                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            self.process.terminate()
                        else:
                            self.process.send_signal(signal.SIGINT)
                        try:
                            self.process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            self.process.kill()
                            self.process.wait()

                    self.status = "STOPPED"
                    stream_logger.info("FFMPEG", "FFmpeg process stopped successfully.")
                except Exception as e:
                    stream_logger.error("FFMPEG", f"Error stopping FFmpeg: {e}")
                    self.status = "ERROR"
                    return False
            else:
                self.status = "STOPPED"

        with self._tiktok_auto_status_lock:
            if self._tiktok_auto_status in ("waiting", "retrying"):
                self._tiktok_auto_status = "stopped"
                self._tiktok_auto_next_retry_at = None

        if not preserve_tiktok_room and config.tiktok_enabled and config.tiktok_session_id:
            from app.streamer.tiktok_generator import tiktok_generator

            def cleanup_tiktok_on_stop() -> None:
                try:
                    with self._bg_retry_api_lock:
                        success, msg = tiktok_generator.finish_room(config.tiktok_session_id)
                    if not success:
                        stream_logger.warn("TIKTOK", f"Yayın durdurulurken TikTok odası kapatılamadı: {msg}")
                except Exception as e:
                    stream_logger.error("TIKTOK", f"Yayın durdurulurken oda kapatma hatası: {e}")
                finally:
                    config.reset_tiktok_session(persist=True)

            threading.Thread(
                target=cleanup_tiktok_on_stop,
                daemon=True,
                name="TikTokStopCleanup",
            ).start()

        return True

    def stop_tiktok_auto_retry(self, wait_for_in_flight_request: bool = False) -> None:
        """Cancel TikTok room retries, optionally waiting for a current API request to finish."""
        with self._bg_retry_lock:
            self._bg_retry_stop.set()
        with self._tiktok_auto_status_lock:
            if self._tiktok_auto_status in ("waiting", "retrying"):
                self._tiktok_auto_status = "stopped"
                self._tiktok_auto_next_retry_at = None
        if wait_for_in_flight_request:
            with self._bg_retry_api_lock:
                pass

    def create_tiktok_room(
        self,
        session_cookie: str,
        title: str,
        event_id: Optional[str] = None,
    ) -> tuple[bool, Dict[str, Any], str]:
        """Serialize TikTok room creation with background retries and cleanup."""
        from app.streamer.tiktok_generator import tiktok_generator

        with self._bg_retry_api_lock:
            return tiktok_generator.create_room_and_get_key(
                session_cookie=session_cookie,
                title=title,
                event_id=event_id,
            )

    def restart(self) -> bool:
        """Restart stream."""
        self.stop(preserve_tiktok_room=True)
        time.sleep(1)
        return self.start()

    def is_tiktok_auto_retry_active(self) -> bool:
        with self._bg_retry_lock:
            thread_active = bool(
                self._bg_retry_thread
                and self._bg_retry_thread.is_alive()
                and not self._bg_retry_stop.is_set()
            )
        with self._tiktok_auto_status_lock:
            return thread_active and self._tiktok_auto_status in ("waiting", "retrying")

    def start_tiktok_auto_retry(
        self,
        start_stream_on_success: bool = False,
        initial_delay_sec: int = 30,
    ) -> None:
        """
        Keep retrying room creation at a capped interval until success or stop.
        """
        if not config.tiktok_enabled or not config.tiktok_session_id:
            return

        with self._bg_retry_lock:
            if self._bg_retry_thread and self._bg_retry_thread.is_alive() and not self._bg_retry_stop.is_set():
                self._tiktok_auto_start_requested |= start_stream_on_success
                return

            self._bg_retry_stop.set()
            stop_event = threading.Event()
            self._bg_retry_stop = stop_event
            self._tiktok_auto_start_requested = start_stream_on_success
            self._bg_retry_thread = threading.Thread(
                target=self._tiktok_background_worker,
                args=(stop_event, initial_delay_sec),
                daemon=True,
                name="TikTokBgJoin",
            )
            with self._tiktok_auto_status_lock:
                self._tiktok_auto_status = "waiting"
                self._tiktok_auto_attempts = 0
                self._tiktok_auto_last_error = None
                self._tiktok_auto_next_retry_at = time.time() + initial_delay_sec
            self._bg_retry_thread.start()

        stream_logger.info(
            "TIKTOK",
            "[AUTO-JOIN] TikTok oda oluşturma arka planda başlatıldı. "
            "Diğer etkin platformlar çalışmaya devam edecek.",
        )

    def _tiktok_background_worker(self, stop_event: threading.Event, initial_delay_sec: int) -> None:
        wait_index = 0
        delay = initial_delay_sec
        if stop_event.wait(delay):
            return

        while not stop_event.is_set() and config.tiktok_enabled and config.tiktok_session_id:
            with self._tiktok_auto_status_lock:
                self._tiktok_auto_status = "retrying"
                self._tiktok_auto_attempts += 1
                attempt = self._tiktok_auto_attempts
                self._tiktok_auto_next_retry_at = None

            stream_logger.info(
                "TIKTOK-BG",
                f"Otomatik TikTok oda oluşturma denemesi #{attempt} başlıyor...",
            )
            try:
                if stop_event.is_set():
                    return
                ok, data, msg = self.create_tiktok_room(
                    session_cookie=config.tiktok_session_id,
                    title=config.tiktok_title or "24/7 Canlı Yayın",
                )
            except Exception as e:
                ok, data, msg = False, {}, f"Beklenmeyen TikTok otomasyon hatası: {e}"

            if stop_event.is_set():
                return

            if ok:
                with self._tiktok_auto_status_lock:
                    self._tiktok_auto_status = "ready"
                    self._tiktok_auto_last_error = None
                    self._tiktok_auto_next_retry_at = None
                stream_logger.info(
                    "TIKTOK-BG",
                    f"TikTok canlı oda/anahtar hazır (Room ID: {data.get('room_id', '?')}).",
                )

                if self.is_running():
                    if not self.restart():
                        stream_logger.error("TIKTOK-BG", "TikTok hazır oldu ancak FFmpeg yeniden başlatılamadı.")
                elif self._tiktok_auto_start_requested:
                    from app.streamer.recovery import watchdog
                    if not watchdog.request_start():
                        stream_logger.error(
                            "TIKTOK-BG",
                            f"TikTok odası hazır ancak yayın başlatılamadı: {self.last_error or 'FFmpeg start failed.'}",
                        )
                return

            if msg.startswith(("SESSION_REJECTED:", "SESSION_UNVERIFIED:")):
                user_message = msg.split(":", 1)[1].strip()
                with self._tiktok_auto_status_lock:
                    self._tiktok_auto_status = "error"
                    self._tiktok_auto_last_error = user_message
                    self._tiktok_auto_next_retry_at = None
                stream_logger.warn(
                    "TIKTOK-BG",
                    f"Otomatik oda denemeleri oturum doğrulaması geçmediği için durduruldu: {user_message}",
                )
                return

            with self._tiktok_auto_status_lock:
                self._tiktok_auto_status = "waiting"
                self._tiktok_auto_last_error = msg

            delay = TIKTOK_AUTO_RETRY_DELAYS[min(wait_index, len(TIKTOK_AUTO_RETRY_DELAYS) - 1)]
            wait_index += 1
            with self._tiktok_auto_status_lock:
                self._tiktok_auto_next_retry_at = time.time() + delay
            stream_logger.warn(
                "TIKTOK-BG",
                f"Oda oluşturulamadı ({msg}). Otomatik tekrar {delay} saniye sonra yapılacak.",
            )
            if stop_event.wait(delay):
                return

        with self._tiktok_auto_status_lock:
            self._tiktok_auto_status = "stopped"
            self._tiktok_auto_next_retry_at = None


ffmpeg_streamer = FFmpegStreamer()
