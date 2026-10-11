import asyncio
import time
from typing import Dict, Any, List, Optional

from app.config import config
from app.monitoring.logger import stream_logger
from app.streamer.ffmpeg import ffmpeg_streamer
from app.streamer.youtube import youtube_manager

# Backoff ladder as specified in the README
BACKOFF_STEPS: List[int] = [5, 10, 20, 30, 60]


class RecoveryWatchdog:
    def __init__(self):
        self.is_active: bool = False
        self.is_desired_running: bool = False
        self.reconnect_count: int = 0
        self.current_step_index: int = 0
        self.next_retry_at: Optional[float] = None
        self.last_stable_timestamp: Optional[float] = None
        self._task: Optional[asyncio.Task] = None

    def start_watchdog(self):
        """Start async background watchdog loop."""
        if not self.is_active:
            self.is_active = True
            self._task = asyncio.create_task(self._watchdog_loop())
            stream_logger.info("WATCHDOG", "Watchdog recovery monitor activated.")

    def stop_watchdog(self):
        """Stop watchdog."""
        self.is_active = False
        if self._task:
            self._task.cancel()
            self._task = None
        stream_logger.info("WATCHDOG", "Watchdog recovery monitor stopped.")

    def request_start(self) -> bool:
        """User or system requested stream start."""
        self.reconnect_count = 0
        self.current_step_index = 0
        self.next_retry_at = None
        success = ffmpeg_streamer.start()
        if success:
            self.is_desired_running = True
            self.last_stable_timestamp = time.time()
        else:
            self.is_desired_running = False
        return success

    def request_stop(self) -> bool:
        """User or system requested stream stop."""
        self.is_desired_running = False
        self.next_retry_at = None
        return ffmpeg_streamer.stop()

    def request_restart(self) -> bool:
        """User or system requested stream restart."""
        self.reconnect_count = 0
        self.current_step_index = 0
        self.next_retry_at = None
        success = ffmpeg_streamer.restart()
        if success:
            self.is_desired_running = True
            self.last_stable_timestamp = time.time()
        else:
            self.is_desired_running = False
        return success

    def get_status(self) -> Dict[str, Any]:
        seconds_to_retry = None
        if self.next_retry_at:
            seconds_to_retry = max(0, int(self.next_retry_at - time.time()))

        return {
            "watchdog_active": self.is_active,
            "is_desired_running": self.is_desired_running,
            "reconnect_count": self.reconnect_count,
            "current_backoff_delay": BACKOFF_STEPS[min(self.current_step_index, len(BACKOFF_STEPS) - 1)],
            "seconds_to_retry": seconds_to_retry,
            "reconnect_enabled": config.reconnect_enabled,
        }

    async def _watchdog_loop(self):
        """Continuously monitors FFmpeg and automatically reconnects on failures."""
        while self.is_active:
            try:
                await asyncio.sleep(2)

                if not self.is_desired_running:
                    continue

                if not config.reconnect_enabled:
                    continue

                # Don't trigger recovery if FFmpeg is still preparing or starting
                if getattr(ffmpeg_streamer, "status", "") in ("STARTING", "WAITING_TIKTOK"):
                    continue

                running = ffmpeg_streamer.is_running()

                # If running, check for frozen / stalled pipeline (0 frames produced for > 40 seconds)
                if running:
                    if ffmpeg_streamer.is_stalled(threshold_sec=40):
                        stream_logger.warn(
                            "WATCHDOG",
                            "FFmpeg akış kilitlenmesi (Freeze / Stalled stream) algılandı! 40 saniyedir yeni kare gelmedi. Otomatik kurtarma başlatılıyor..."
                        )
                        ffmpeg_streamer.restart()
                        self.last_stable_timestamp = time.time()
                        continue

                    # If running stably for more than 60 seconds, reset backoff ladder
                    if self.last_stable_timestamp and (time.time() - self.last_stable_timestamp > 60):
                        if self.current_step_index > 0:
                            stream_logger.info("WATCHDOG", "Stream has been stable for >60s. Resetting retry backoff counter.")
                            self.current_step_index = 0
                    continue

                # Stream died unexpectedly while desired running is True!
                stream_logger.warn("WATCHDOG", "Detected FFmpeg stream drop! Initiating recovery sequence...")

                # Calculate delay according to ladder
                delay = BACKOFF_STEPS[min(self.current_step_index, len(BACKOFF_STEPS) - 1)]
                self.reconnect_count += 1
                self.current_step_index = min(self.current_step_index + 1, len(BACKOFF_STEPS) - 1)
                self.next_retry_at = time.time() + delay

                stream_logger.warn(
                    "WATCHDOG",
                    f"Recovery attempt #{self.reconnect_count} scheduled in {delay} seconds (Step {self.current_step_index}/{len(BACKOFF_STEPS)})..."
                )

                # Wait for backoff duration while respecting cancellation / state change
                sleep_start = time.time()
                while time.time() - sleep_start < delay:
                    if not self.is_desired_running or not self.is_active:
                        self.next_retry_at = None
                        break
                    await asyncio.sleep(1)

                if not self.is_desired_running or not self.is_active:
                    continue

                self.next_retry_at = None
                # TikTok SessionID varsa ve TikTok yayını etkinse, yeni oda/anahtar kontrolü yap
                if config.tiktok_enabled and config.tiktok_session_id:
                    try:
                        from app.streamer.tiktok_generator import tiktok_generator
                        stream_logger.info("WATCHDOG", "TikTok oturumu için canlı yayın anahtarı kontrol ediliyor / otomatik yenileniyor...")
                        tiktok_generator.create_room_and_get_key(
                            session_cookie=config.tiktok_session_id,
                            title=config.tiktok_title
                        )
                    except Exception as e:
                        stream_logger.warn("WATCHDOG", f"Otomatik TikTok anahtar yenileme atlandı: {e}")

                # Restart FFmpeg
                success = ffmpeg_streamer.start()
                if success:
                    stream_logger.info("WATCHDOG", f"Recovery reconnect attempt #{self.reconnect_count} succeeded!")
                    self.last_stable_timestamp = time.time()
                else:
                    stream_logger.error("WATCHDOG", f"Recovery reconnect attempt #{self.reconnect_count} failed. Will back off further.")

            except asyncio.CancelledError:
                break
            except Exception as e:
                stream_logger.error("WATCHDOG", f"Watchdog iteration error: {e}")
                await asyncio.sleep(5)


watchdog = RecoveryWatchdog()
