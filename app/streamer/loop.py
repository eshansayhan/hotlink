from typing import List, Optional
from app.config import config
from app.video.validator import video_validator


class LoopController:
    @staticmethod
    def get_input_flags(is_url: bool, enable_loop: bool = True) -> List[str]:
        """
        Builds FFmpeg input arguments for infinite looping and network resiliency.

        -re is only appropriate for live/network inputs. Using it for local looped files
        causes FFmpeg to duplicate frames and jitter after long-running 24/7 streams.
        """
        flags: List[str] = []

        # Live/network sources should be throttled to real-time playback.
        if is_url:
            flags.extend(["-re"])
            flags.extend([
                "-reconnect", "1",
                "-reconnect_at_eof", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
            ])

        # Infinite loop is valid for both local files and remote seekable streams.
        if enable_loop:
            flags.extend(["-stream_loop", "-1"])

        return flags


loop_controller = LoopController()
