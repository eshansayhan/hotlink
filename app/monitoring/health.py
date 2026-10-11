import os
import time
from typing import Dict, Any, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

APP_START_TIME = time.time()


def format_duration(seconds: float) -> str:
    """Format seconds into 00h 00m 00s format."""
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    elif minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def get_container_memory() -> tuple[float, float, float]:
    """
    Calculates accurate memory usage for containerized environments (Docker / Hugging Face Spaces).
    Instead of reporting the shared host node's 128GB RAM, this measures the actual memory consumed
    by this application and its child processes (FFmpeg) relative to the container allocation.
    Returns (used_mb, total_mb, percent).
    """
    proc_used_bytes = 0
    if PSUTIL_AVAILABLE:
        try:
            curr_proc = psutil.Process(os.getpid())
            proc_used_bytes = curr_proc.memory_info().rss
            for child in curr_proc.children(recursive=True):
                try:
                    proc_used_bytes += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    # Check cgroup v2
    cgroup_limit_bytes = 0
    cgroup_used_bytes = 0
    if os.path.exists("/sys/fs/cgroup/memory.current"):
        try:
            with open("/sys/fs/cgroup/memory.current", "r") as f:
                cgroup_used_bytes = int(f.read().strip())
        except Exception:
            pass
        if os.path.exists("/sys/fs/cgroup/memory.max"):
            try:
                with open("/sys/fs/cgroup/memory.max", "r") as f:
                    val = f.read().strip()
                    if val != "max" and val.isdigit():
                        cgroup_limit_bytes = int(val)
            except Exception:
                pass
    # Check cgroup v1
    elif os.path.exists("/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        try:
            with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", "r") as f:
                cgroup_used_bytes = int(f.read().strip())
        except Exception:
            pass
        if os.path.exists("/sys/fs/cgroup/memory/memory.limit_in_bytes"):
            try:
                with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as f:
                    val = int(f.read().strip())
                    if val < 1099511627776:  # Less than 1TB limit
                        cgroup_limit_bytes = val
            except Exception:
                pass

    # Calculate total container allocation (Hugging Face basic CPU is 16 GB = 16384 MB)
    if cgroup_limit_bytes > 0:
        total_mb = round(cgroup_limit_bytes / (1024 * 1024), 1)
    elif PSUTIL_AVAILABLE:
        try:
            # If total host RAM is huge (e.g. 128GB on cloud host), cap realistic container view to 16GB
            host_total = round(psutil.virtual_memory().total / (1024 * 1024), 1)
            total_mb = 16384.0 if host_total > 32768.0 else host_total
        except Exception:
            total_mb = 16384.0
    else:
        total_mb = 16384.0

    # Calculate used RAM by the app and ffmpeg
    if proc_used_bytes > 0:
        used_mb = round(proc_used_bytes / (1024 * 1024), 1)
    elif cgroup_used_bytes > 0:
        used_mb = round(cgroup_used_bytes / (1024 * 1024), 1)
    elif PSUTIL_AVAILABLE:
        try:
            used_mb = round(psutil.virtual_memory().used / (1024 * 1024), 1)
        except Exception:
            used_mb = 0.0
    else:
        used_mb = 0.0

    percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
    percent = min(100.0, max(0.0, percent))
    return used_mb, total_mb, percent


def get_system_metrics() -> Dict[str, Any]:
    """Retrieve current CPU and container-accurate RAM metrics."""
    cpu_percent = 0.0

    if PSUTIL_AVAILABLE:
        try:
            # Measure CPU of this application and its child worker (FFmpeg)
            curr_proc = psutil.Process(os.getpid())
            proc_cpu = curr_proc.cpu_percent(interval=None)
            for child in curr_proc.children(recursive=True):
                try:
                    proc_cpu += child.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            # If process CPU measurement is available, use it; otherwise fallback to host CPU
            if proc_cpu > 0:
                cpu_percent = round(proc_cpu, 1)
            else:
                cpu_percent = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            try:
                cpu_percent = round(psutil.cpu_percent(interval=None), 1)
            except Exception:
                pass

    memory_used_mb, memory_total_mb, memory_percent = get_container_memory()
    app_uptime_sec = time.time() - APP_START_TIME

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_mb": memory_used_mb,
        "memory_total_mb": memory_total_mb,
        "app_uptime_seconds": int(app_uptime_sec),
        "app_uptime": format_duration(app_uptime_sec),
    }


import gc
import threading

_hygiene_running = False
_hygiene_thread: Optional[threading.Thread] = None


def run_garbage_collection() -> int:
    """Explicitly triggers garbage collection to keep long-running 24/7 memory usage minimal."""
    collected = gc.collect()
    return collected


def _memory_hygiene_worker(interval_seconds: int = 300):
    global _hygiene_running
    while _hygiene_running:
        time.sleep(interval_seconds)
        if not _hygiene_running:
            break
        try:
            gc.collect()
        except Exception:
            pass


def start_memory_hygiene(interval_seconds: int = 300):
    """Starts background thread to run periodic memory cleanup (every 5 minutes)."""
    global _hygiene_running, _hygiene_thread
    if not _hygiene_running:
        _hygiene_running = True
        _hygiene_thread = threading.Thread(target=_memory_hygiene_worker, args=(interval_seconds,), daemon=True)
        _hygiene_thread.start()


def stop_memory_hygiene():
    """Stops background memory hygiene thread."""
    global _hygiene_running
    _hygiene_running = False
