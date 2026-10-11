"""
metadata.py — Video Loop Metadata Mutasyon Sistemi
===================================================
Her video loop'unda FFmpeg stream'ine farklı metadata enjekte eder.

Algoritma:
  1. ffprobe ile videonun süresini saniye cinsinden öğrenir (bir kez)
  2. FFmpeg stats'tan gelen 'time' değerini (HH:MM:SS) izler
  3. time > video_duration sınırını geçtiğinde → loop tespit edildi
  4. Loop sayısına + zaman damgasına göre pseudo-random metadata üretir
  5. Loop tespitinde FFmpeg'i soft-restart eder → yeni metadata aktif olur

Metadata alanları (FLV/RTMP stream'ine gömülür):
  - title        : Her loop farklı jenerik başlık
  - comment      : Rastgele kısa açıklama
  - encoder      : Hafif varyasyonlu encoder string'i
  - date         : O anki ISO tarih-saat
  - creation_time: Gerçek oluşturma zamanı (rastgele offset ile)
  - album        : Döngü sekansı (okunmaz bir değer)
  - genre        : Rastgele seçilmiş müzik tarzı vb.
"""

import hashlib
import json
import random
import re
import shutil
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from app.monitoring.logger import stream_logger


# ─── Metadata havuzları (her loop'ta bu havuzlardan rastgele seçilir) ─────────

_TITLES = [
    "Live Stream", "Live Broadcast", "Online Stream", "Streaming Now",
    "Live Feed", "Broadcast Live", "Video Stream", "Live Video",
    "Live Session", "Stream Online", "24/7 Broadcast", "Continuous Stream",
    "Live Channel", "Video Broadcast", "Real-time Stream",
]

_COMMENTS = [
    "Streaming in progress", "Live content delivery", "Real-time broadcast",
    "Continuous video feed", "Ongoing live session", "Active stream",
    "Video pipeline active", "Broadcasting live", "Stream active",
    "Live output enabled", "Encoder online", "Pipeline running",
]

_ENCODER_BASES = [
    "Lavf", "FFmpeg", "libav", "MediaEncoder", "VideoProcessor",
]

_GENRES = [
    "Entertainment", "Music", "Gaming", "Technology", "Education",
    "Sports", "News", "Comedy", "Drama", "Live",
]

_ARTISTS = [
    "Broadcast", "LiveChannel", "MediaStream", "VideoFeed", "StreamCast",
]


class MetadataMutator:
    """
    Video loop'larını tespit edip her loop'ta FFmpeg metadata'sını değiştirir.

    Kullanım:
        # FFmpeg command'a ekle:
        cmd.extend(metadata_mutator.get_ffmpeg_flags())

        # FFmpeg başladığında:
        metadata_mutator.on_stream_start(video_path, ffprobe_bin)

        # Her stats satırında:
        metadata_mutator.on_stats_update(time_str, trigger_restart_fn)
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Video süresi (saniye) — ffprobe ile bir kez öğrenilir
        self._video_duration_sec: Optional[float] = None

        # Mevcut loop sayısı
        self._loop_count: int = 0

        # Bu session'ın rastgele seed'i
        self._session_seed: int = int(time.time() * 1000) % (2**31)

        # Son tespit edilen zaman (saniye)
        self._last_pts_sec: float = 0.0

        # Restart bekleniyor mu? (debounce için)
        self._restart_pending: bool = False
        self._last_restart_at: float = 0.0

        # Loop restart etkinleştirildi mi?
        self.loop_restart_enabled: bool = True

        # Minimum loop uzunluğu — video 30 saniyeden kısaysa loop tespiti devre dışı
        self.MIN_LOOP_DURATION_SEC: float = 10.0

        # İlk metadata (stream başlamadan önce üretilir)
        self._current_metadata: Dict[str, str] = self._generate_metadata(loop=0)

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_stream_start(self, video_source: str, ffprobe_bin: str = "ffprobe") -> None:
        """FFmpeg başladığında çağrılır. Video süresini öğrenir, yeni metadata üretir."""
        with self._lock:
            self._loop_count = 0
            self._last_pts_sec = 0.0
            self._restart_pending = False
            self._session_seed = int(time.time() * 1000) % (2**31)
            self._current_metadata = self._generate_metadata(loop=0)

        # ffprobe'u arka planda çalıştır (start() metodunu bloklamaz)
        thread = threading.Thread(
            target=self._probe_video_duration,
            args=(video_source, ffprobe_bin),
            daemon=True,
        )
        thread.start()

    def get_ffmpeg_flags(self) -> List[str]:
        """
        FFmpeg komutuna eklenecek -metadata bayraklarını döndürür.
        Her build_command() çağrısında yeni değerler üretilir.
        """
        with self._lock:
            meta = self._current_metadata

        flags: List[str] = []
        for key, value in meta.items():
            flags.extend(["-metadata", f"{key}={value}"])
        return flags

    def on_stats_update(
        self,
        time_str: str,
        trigger_restart_fn=None,
    ) -> bool:
        """
        FFmpeg istatistik satırından gelen 'time' değerini işler.
        Loop tespit edilirse True döner ve (varsa) trigger_restart_fn'i çağırır.

        Args:
            time_str: FFmpeg 'time' değeri, örn. '00:08:22'
            trigger_restart_fn: Çağrıldığında stream'i yeniden başlatır (opsiyonel)

        Returns:
            True eğer bu çağrıda loop tespit edildiyse
        """
        with self._lock:
            dur = self._video_duration_sec
            if dur is None or dur < self.MIN_LOOP_DURATION_SEC:
                return False
            if not self.loop_restart_enabled:
                return False

        pts_sec = self._parse_time_str(time_str)
        if pts_sec is None:
            return False

        with self._lock:
            prev_pts = self._last_pts_sec
            self._last_pts_sec = pts_sec
            dur = self._video_duration_sec

        # Loop tespiti: pts geçen değere göre önemli ölçüde geriledi
        # veya video süresinin ötesine geçti
        loop_detected = False

        # Yöntem 1: PTS sıfırlandı / geriye gitti (loop sınırında FFmpeg pts sıfırlar)
        if prev_pts > 5.0 and pts_sec < 2.0:
            loop_detected = True

        # Yöntem 2: pts video süresini aştı (tam sayıda loop doldu)
        if dur and pts_sec >= dur - 0.5 and prev_pts < dur - 0.5:
            loop_detected = True

        if not loop_detected:
            return False

        # Debounce: 10 saniye içinde tekrar restart istemini engelle
        with self._lock:
            now = time.time()
            if now - self._last_restart_at < 10.0:
                return False
            if self._restart_pending:
                return False
            self._loop_count += 1
            new_loop = self._loop_count
            self._last_restart_at = now
            self._restart_pending = True
            self._current_metadata = self._generate_metadata(loop=new_loop)

        stream_logger.info(
            "METADATA",
            f"Video loop #{new_loop} tespit edildi (pts={pts_sec:.1f}s / dur={dur:.1f}s). "
            f"Yeni metadata enjekte ediliyor: title='{self._current_metadata.get('title', '')}'"
        )

        if trigger_restart_fn is not None:
            try:
                trigger_restart_fn()
            except Exception as e:
                stream_logger.warn("METADATA", f"Loop restart tetiklenemedi: {e}")

        with self._lock:
            self._restart_pending = False

        return True

    def get_current_metadata(self) -> Dict[str, str]:
        """Mevcut aktif metadata sözlüğünü döndürür (debug/UI için)."""
        with self._lock:
            return dict(self._current_metadata)

    def get_loop_count(self) -> int:
        with self._lock:
            return self._loop_count

    def get_video_duration(self) -> Optional[float]:
        with self._lock:
            return self._video_duration_sec

    def force_new_metadata(self) -> Dict[str, str]:
        """Manuel olarak yeni metadata üretir (API çağrısı için)."""
        with self._lock:
            self._loop_count += 1
            self._current_metadata = self._generate_metadata(loop=self._loop_count)
            return dict(self._current_metadata)

    # ── Internal Helpers ───────────────────────────────────────────────────────

    def _generate_metadata(self, loop: int) -> Dict[str, str]:
        """
        Loop sayısı ve zaman damgasına göre deterministik ama görünüşte
        rastgele metadata üretir.

        Deterministik olması: aynı loop sayısı için hep aynı sonucu verir
        (restart sonrası tutarlılık).
        """
        # Seed = session_seed XOR loop_count XOR dakika (saatlik döngü)
        rng_seed = self._session_seed ^ (loop * 31337) ^ (int(time.time()) // 60)
        rng = random.Random(rng_seed)

        # Rastgele seçimler
        title = rng.choice(_TITLES)
        comment = rng.choice(_COMMENTS)
        genre = rng.choice(_GENRES)
        artist = rng.choice(_ARTISTS)
        encoder_base = rng.choice(_ENCODER_BASES)

        # Encoder versiyonu: örn. "Lavf59.27.100" → her loop farklı patch numarası
        enc_major = rng.randint(56, 61)
        enc_minor = rng.randint(1, 40)
        enc_patch = rng.randint(1, 250)
        encoder_str = f"{encoder_base}{enc_major}.{enc_minor}.{enc_patch}"

        # Zaman damgası — gerçek zamana yakın ama küçük rastgele offset ile
        now = time.time()
        time_offset = rng.uniform(-300, 300)  # ±5 dakika sapma
        creation_ts = now + time_offset
        date_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(creation_ts))

        # Album: loop numarasını içeren ama okunaksız bir değer
        loop_hash = hashlib.md5(
            f"{self._session_seed}:{loop}:{int(now)}".encode()
        ).hexdigest()[:8]
        album = f"S{self._session_seed & 0xFFFF:04X}{loop_hash}"

        # Track numarası: 1-99 arası rastgele
        track = str(rng.randint(1, 99))

        return {
            "title": title,
            "comment": comment,
            "encoder": encoder_str,
            "date": date_str,
            "creation_time": date_str,
            "album": album,
            "genre": genre,
            "artist": artist,
            "track": track,
        }

    def _probe_video_duration(self, video_source: str, ffprobe_bin: str) -> None:
        """ffprobe ile video süresini arka planda öğrenir."""
        try:
            bin_path = shutil.which(ffprobe_bin) or ffprobe_bin
            cmd = [
                bin_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_entries", "format=duration",
                video_source,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                dur = float(data.get("format", {}).get("duration", 0))
                if dur > 0:
                    with self._lock:
                        self._video_duration_sec = dur
                    stream_logger.info(
                        "METADATA",
                        f"Video suresi tespit edildi: {dur:.2f}s "
                        f"({dur/60:.1f} dk). "
                        f"Her {dur:.0f}s'de loop metadata guncellenecek."
                    )
                else:
                    stream_logger.warn("METADATA", "Video suresi 0 veya alinamadi, loop tespiti devre disi.")
            else:
                stream_logger.warn("METADATA", f"ffprobe hatasi (kod {result.returncode}): loop tespiti devre disi.")
        except Exception as e:
            stream_logger.warn("METADATA", f"ffprobe calistirilamadi: {e}. Loop tespiti devre disi.")

    @staticmethod
    def _parse_time_str(time_str: str) -> Optional[float]:
        """'HH:MM:SS.ms' veya 'HH:MM:SS' formatını saniyeye çevirir."""
        try:
            # Noktalı kısmı temizle
            clean = time_str.split(".")[0].strip()
            parts = clean.split(":")
            if len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:
                m, s = int(parts[0]), int(parts[1])
                return m * 60 + s
        except Exception:
            pass
        return None


# Singleton
metadata_mutator = MetadataMutator()
