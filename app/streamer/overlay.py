"""
overlay.py — Video Overlay ve Hash Evasion Filtre Yöneticisi
=============================================================
FFmpeg drawtext ve filtre zinciri ile video üzerine şunları basar:

  ① 🔴 Canlı Yayın Süresi Sayacı (Uptime Bar)
  ② 🛡️ Anti-Fingerprint & Hash Evasion Filtreleri
     - Uzamsal Kaydırma (1px micro crop & pad)
     - Harmonik Renk/Luma Salınımı (pHash DCT bozucu)
     - Frekans/Kenar Pertürbasyonu (dHash bozucu)
     - Zamansal Rastgele Gürültü (Temporal Noise)
     - Akustik Mikro Hacim Modülasyonu
"""

import threading
import time
from typing import List, Optional, Any


class OverlayManager:
    """
    FFmpeg -vf ve -af filtre zinciri oluşturucusu.
    Sade: sadece Uptime sayacı + Anti-Hash Evasion filtreleri içerir.
    """

    NOISE_STRENGTH = 3

    def __init__(self):
        self._lock = threading.Lock()

        # Görsel Katman Kontrolleri
        self.show_uptime: bool = False
        self.show_chat: bool = False
        self.show_goal: bool = False
        self.show_notifications: bool = False
        self.auto_chat_enabled: bool = False
        self.goal_title: str = "Hedef"
        self.goal_current: int = 0
        self.goal_target: int = 10000

        # Hash Evasion Anahtarları
        self.hash_evasion_enabled: bool = True
        self.noise_enabled: bool = True
        self.noise_strength: int = self.NOISE_STRENGTH
        self.spatial_shift_enabled: bool = True
        self.color_oscillation_enabled: bool = True
        self.unsharp_enabled: bool = True
        self.audio_evasion_enabled: bool = True

    # ── Compatibility Stubs (No-Op) ────────────────────────────────────

    def add_chat_message(self, user: str, text: str, color: str = "#ffffff"):
        class DummyMsg:
            msg_id = "0"
            user = user
            text = text
            display_duration = 0
            color = color
            arrived_at = time.time()
        return DummyMsg()

    def get_active_messages(self) -> List[Any]:
        return []

    def clear_chat(self) -> None:
        pass

    def add_gift_notification(self, user: str, gift_name: str = "Gül", count: int = 1):
        class DummyNotif:
            notif_id = "0"
        return DummyNotif()

    def add_follower_notification(self, user: str):
        class DummyNotif:
            notif_id = "0"
        return DummyNotif()

    def get_active_notifications(self) -> List[Any]:
        return []

    def set_goal(self, title: Optional[str] = None, current: Optional[int] = None, target: Optional[int] = None):
        if title is not None:
            self.goal_title = title
        if current is not None:
            self.goal_current = current
        if target is not None:
            self.goal_target = target


    # ── FFmpeg Filter Builder ──────────────────────────────────────────

    def build_video_filter(
        self,
        width: int,
        height: int,
        stream_start_time: Optional[float] = None,
        encoder_name: str = "libx264",
    ) -> str:
        """Tam FFmpeg -vf zincirini tek string olarak döndürür."""
        parts: List[str] = []

        # 1. Scale + pad + format
        parts.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"format=yuv420p"
        )

        # 2. Hash Evasion — Uzamsal Kaydırma (1-pixel micro crop & pad)
        if self.hash_evasion_enabled and self.spatial_shift_enabled:
            parts.append(f"crop={width}-2:{height}-2:1:1,pad={width}:{height}:1:1")

        # 3. Hash Evasion — Harmonik Renk/Luma Salınımı (pHash DCT bozucusu)
        if self.hash_evasion_enabled and self.color_oscillation_enabled:
            parts.append(
                "eq=contrast='1+0.006*sin(2*3.14159265*t/17)':"
                "brightness='0.001*sin(2*3.14159265*t/13)':"
                "saturation='1+0.005*cos(2*3.14159265*t/19)'"
            )

        # 4. Hash Evasion — Frekans/Kenar Pertürbasyonu (dHash bozucusu)
        if self.hash_evasion_enabled and self.unsharp_enabled:
            parts.append("unsharp=lx=3:ly=3:la=0.15:cx=3:cy=3:ca=0.10")

        # 5. Hash Evasion — Zamansal Rastgele Gürültü (Temporal Uniform Noise)
        if self.noise_enabled:
            parts.append(self._build_noise_filter(encoder_name))

        return ",".join(parts)

    def build_audio_filter(self) -> str:
        """Sese mikroskobik pertürbasyon ekleyerek akustik hash algoritmalarını atlatır."""
        af_parts = ["aresample=async=1000"]
        if self.hash_evasion_enabled and self.audio_evasion_enabled:
            # isnan(t) kontrolü ile ilk frame başlatma anındaki NaN uyarısı engellenir.
            af_parts.append("volume='if(isnan(t), 1, 1+0.003*sin(2*3.14159265*t/23))':eval=frame")
        return ",".join(af_parts)

    def _build_noise_filter(self, encoder_name: str) -> str:
        """Encoder tipine göre en uyumlu temporal noise filtresini döndürür."""
        strength = max(1, min(10, self.noise_strength))
        ffmpeg_strength = strength * 2  # 1→2, 3→6, 5→10, 10→20
        return (
            f"noise="
            f"all_strength={ffmpeg_strength}:"
            f"all_flags=t+u"
        )

    @staticmethod
    def _escape(text: str) -> str:
        """FFmpeg drawtext için Türkçe karakterleri çevirir ve özel karakterleri escape eder."""
        tr_map = {
            "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G",
            "ı": "i", "İ": "I", "ö": "o", "Ö": "O",
            "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
        }
        for k, v in tr_map.items():
            text = text.replace(k, v)

        text = text.replace("\\", "\\\\")
        text = text.replace("'", "\\'")
        text = text.replace(":", "\\:")
        text = text.replace("[", "\\[")
        text = text.replace("]", "\\]")
        text = text.replace("=", "\\=")
        import re
        text = re.sub(r"[^\x00-\x7F]", "", text)
        return text


# Singleton
overlay_manager = OverlayManager()
