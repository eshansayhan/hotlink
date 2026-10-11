# -*- coding: utf-8 -*-
import sys

# Read index.html
with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Custom Player CSS
player_css = """
/* ========================================================
   ESHAN CINEMA PLAYER (NOVAPLAYER) - OZEL MEDIA OYNATICI
======================================================== */
:root {
  --np-acc: #00e5b4;
  --np-acc-glow: rgba(0, 229, 180, 0.4);
  --np-bg-overlay: linear-gradient(180deg, rgba(8,8,14,0.85) 0%, rgba(8,8,14,0) 25%, rgba(8,8,14,0) 65%, rgba(8,8,14,0.95) 100%);
}

.nova-player {
  position: relative;
  width: 100%;
  aspect-ratio: 16/9;
  background: #000;
  border-radius: var(--rl);
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(0,229,180,0.08);
  border: 1px solid rgba(255,255,255,0.08);
  user-select: none;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}
.nova-player.theater-mode {
  position: fixed !important;
  top: 70px;
  left: 0;
  width: 100vw !important;
  max-width: 100vw !important;
  height: calc(100vh - 70px) !important;
  aspect-ratio: auto !important;
  z-index: 1000;
  border-radius: 0;
}
.nova-player video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
  cursor: pointer;
}

/* OSD Overlay Layers */
.np-overlay {
  position: absolute;
  inset: 0;
  background: var(--np-bg-overlay);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  opacity: 1;
  transition: opacity 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
  pointer-events: none;
  z-index: 10;
}
.nova-player.idle .np-overlay {
  opacity: 0;
}
.nova-player.paused .np-overlay {
  opacity: 1 !important;
}
.np-overlay > * {
  pointer-events: auto;
}

/* Top Bar */
.np-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
}
.np-top-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.np-badge-p2p {
  background: rgba(0, 229, 180, 0.15);
  border: 1px solid var(--np-acc);
  color: var(--np-acc);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.6px;
  padding: 4px 10px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  gap: 5px;
  box-shadow: 0 0 14px var(--np-acc-glow);
}
.np-badge-p2p .pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--np-acc);
  box-shadow: 0 0 8px var(--np-acc);
  animation: pdot 1.4s infinite;
}
@keyframes pdot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.7); } }
.np-video-title {
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  text-shadow: 0 2px 6px rgba(0,0,0,0.8);
  max-width: 450px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.np-top-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.np-top-btn {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 13px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  backdrop-filter: blur(8px);
  transition: all 0.2s ease;
}
.np-top-btn:hover {
  background: var(--np-acc);
  color: #000;
  border-color: var(--np-acc);
  box-shadow: 0 0 16px var(--np-acc-glow);
  transform: translateY(-1px);
}

/* Center Animation / Notifications */
.np-center-hud {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 20;
}
.np-center-icon {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  background: rgba(8, 8, 14, 0.75);
  border: 2px solid var(--np-acc);
  box-shadow: 0 0 30px var(--np-acc-glow);
  backdrop-filter: blur(12px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--np-acc);
  font-size: 32px;
  opacity: 0;
  transform: scale(0.6);
  transition: all 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.np-center-icon.active {
  opacity: 1;
  transform: scale(1);
}
.np-skip-badge {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  background: rgba(8,8,14,0.85);
  border: 1px solid rgba(255,255,255,0.2);
  color: #fff;
  padding: 12px 20px;
  border-radius: 50px;
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
  opacity: 0;
  pointer-events: none;
  transition: all 0.25s ease;
  z-index: 20;
}
.np-skip-left { left: 40px; }
.np-skip-right { right: 40px; }
.np-skip-badge.active {
  opacity: 1;
  transform: translateY(-50%) scale(1.08);
}

/* Bottom Controls */
.np-bottom-bar {
  padding: 0 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Progress Area */
.np-progress-box {
  position: relative;
  width: 100%;
  height: 20px;
  display: flex;
  align-items: center;
  cursor: pointer;
}
.np-progress-bg {
  position: relative;
  width: 100%;
  height: 5px;
  background: rgba(255,255,255,0.2);
  border-radius: 4px;
  overflow: visible;
  transition: height 0.15s ease;
}
.np-progress-box:hover .np-progress-bg {
  height: 8px;
}
.np-buffer-bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 0%;
  background: rgba(255,255,255,0.35);
  border-radius: 4px;
  pointer-events: none;
}
.np-played-bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, #00f2fe 0%, var(--np-acc) 100%);
  border-radius: 4px;
  box-shadow: 0 0 10px var(--np-acc-glow);
  pointer-events: none;
}
.np-scrub-thumb {
  position: absolute;
  top: 50%;
  left: 0%;
  transform: translate(-50%, -50%) scale(0);
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--np-acc);
  box-shadow: 0 0 12px var(--np-acc);
  pointer-events: none;
  transition: transform 0.15s ease;
}
.np-progress-box:hover .np-scrub-thumb {
  transform: translate(-50%, -50%) scale(1);
}
.np-time-bubble {
  position: absolute;
  bottom: 24px;
  transform: translateX(-50%);
  background: rgba(8,8,14,0.92);
  border: 1px solid var(--np-acc);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 6px;
  pointer-events: none;
  opacity: 0;
  box-shadow: 0 4px 14px rgba(0,0,0,0.6);
  transition: opacity 0.15s ease;
  white-space: nowrap;
}
.np-progress-box:hover .np-time-bubble {
  opacity: 1;
}

/* Control Buttons Row */
.np-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.np-left-grp, .np-right-grp {
  display: flex;
  align-items: center;
  gap: 14px;
}
.np-btn {
  background: transparent;
  border: none;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.2s ease;
  position: relative;
}
.np-btn:hover {
  color: var(--np-acc);
  transform: scale(1.12);
}
.np-btn svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}

/* Volume Slider */
.np-vol-box {
  display: flex;
  align-items: center;
  gap: 8px;
}
.np-vol-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 0px;
  opacity: 0;
  height: 5px;
  background: rgba(255,255,255,0.3);
  border-radius: 3px;
  outline: none;
  transition: width 0.25s ease, opacity 0.25s ease;
  cursor: pointer;
}
.np-vol-box:hover .np-vol-slider {
  width: 70px;
  opacity: 1;
}
.np-vol-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--np-acc);
  box-shadow: 0 0 8px var(--np-acc);
}

/* Time Display */
.np-time-txt {
  color: #d1d5db;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.3px;
  cursor: pointer;
}
.np-time-txt span {
  color: #fff;
}

/* Quality Tag */
.np-tag-res {
  background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.15);
  color: #e5e7eb;
  font-size: 11px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: default;
}

/* Speed Dropdown Menu */
.np-menu-wrap {
  position: relative;
}
.np-dropdown {
  position: absolute;
  bottom: 38px;
  right: 0;
  background: rgba(14, 14, 22, 0.95);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 10px;
  padding: 6px 0;
  min-width: 120px;
  box-shadow: 0 12px 36px rgba(0,0,0,0.8);
  backdrop-filter: blur(14px);
  display: none;
  flex-direction: column;
  z-index: 30;
}
.np-dropdown.open {
  display: flex;
}
.np-drop-item {
  padding: 8px 16px;
  color: #e5e7eb;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.15s ease;
}
.np-drop-item:hover {
  background: rgba(0, 229, 180, 0.15);
  color: var(--np-acc);
}
.np-drop-item.selected {
  color: var(--np-acc);
  font-weight: 800;
}

/* Context Menu */
.np-context-menu {
  position: fixed;
  background: rgba(13, 13, 20, 0.96);
  border: 1px solid rgba(0, 229, 180, 0.25);
  border-radius: 12px;
  padding: 8px 0;
  min-width: 220px;
  box-shadow: 0 14px 40px rgba(0,0,0,0.9), 0 0 20px rgba(0,229,180,0.1);
  backdrop-filter: blur(16px);
  display: none;
  flex-direction: column;
  z-index: 99999;
}
.np-context-header {
  padding: 8px 16px 6px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--np-acc);
}
.np-ctx-item {
  padding: 10px 16px;
  color: #f3f4f6;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: all 0.15s ease;
}
.np-ctx-item:hover {
  background: rgba(0, 229, 180, 0.15);
  color: var(--np-acc);
}

/* Embed Modal */
.embed-modal-content {
  background: var(--sur);
  border: 1px solid rgba(0, 229, 180, 0.3);
  border-radius: var(--rl);
  padding: 28px;
  width: 90%;
  max-width: 580px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(0,229,180,0.1);
}
.embed-code-box {
  width: 100%;
  height: 90px;
  background: #09090f;
  border: 1px solid var(--brd);
  border-radius: 8px;
  color: #00f2fe;
  font-family: Consolas, monospace;
  font-size: 12px;
  padding: 12px;
  resize: none;
  outline: none;
  margin-top: 12px;
  margin-bottom: 16px;
}
.embed-preview-tag {
  font-size: 12px;
  color: var(--tx3);
  margin-bottom: 6px;
}

/* STANDALONE EMBED MODE (Iframe icinde calisirken) */
body.embed-mode {
  background: transparent !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}
body.embed-mode .hdr,
body.embed-mode footer,
body.embed-mode .breadcrumb,
body.embed-mode .p-left,
body.embed-mode .p-right,
body.embed-mode .info-card,
body.embed-mode .ep-sec,
body.embed-mode .series-bar,
body.embed-mode #pv-home,
body.embed-mode #pv-cat {
  display: none !important;
}
body.embed-mode #app,
body.embed-mode .post-wrap,
body.embed-mode .p3,
body.embed-mode .p-mid {
  padding: 0 !important;
  margin: 0 !important;
  max-width: 100% !important;
  width: 100vw !important;
  height: 100vh !important;
}
body.embed-mode .nova-player {
  border-radius: 0 !important;
  border: none !important;
  width: 100vw !important;
  height: 100vh !important;
  max-width: 100vw !important;
  max-height: 100vh !important;
  aspect-ratio: auto !important;
}
"""

# Insert CSS right before </style>
if "/* ESHAN CINEMA PLAYER */" not in html:
    html = html.replace("</style>", player_css + "\n</style>")

# 2. Custom Player DOM Structure
custom_player_dom = """
          <!-- ESHAN CINEMA PLAYER (NOVAPLAYER) -->
          <div class="nova-player" id="novaPlayerWrap">
            <video id="mainVideo" playsinline preload="metadata"></video>
            
            <!-- Central HUD / Animations -->
            <div class="np-center-hud">
              <div class="np-center-icon" id="npCenterIcon">▶</div>
            </div>
            <div class="np-skip-badge np-skip-left" id="npSkipLeft">« 10s Geri</div>
            <div class="np-skip-badge np-skip-right" id="npSkipRight">10s İleri »</div>

            <!-- Loader / Buffering Spinner -->
            <div class="vload" id="vload">
              <div class="spin"></div>
              <span class="ltxt">Stream Hazırlanıyor…</span>
            </div>

            <!-- OSD Overlays -->
            <div class="np-overlay" id="npOverlay">
              <!-- Top Bar -->
              <div class="np-top-bar">
                <div class="np-top-left">
                  <div class="np-badge-p2p"><span class="pulse-dot"></span> P2P 1080P</div>
                  <div class="np-video-title" id="npVideoTitle">Video Başlığı</div>
                </div>
                <div class="np-top-right">
                  <button class="np-top-btn" id="btnEmbedCode" title="Sitene Ekle (Embed)">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z"/></svg>
                    Embed
                  </button>
                  <button class="np-top-btn" id="btnShareVideoTop" title="Paylaş">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z"/></svg>
                    Paylaş
                  </button>
                </div>
              </div>

              <!-- Bottom Bar -->
              <div class="np-bottom-bar">
                <!-- Progress Scrubber -->
                <div class="np-progress-box" id="npProgressBox">
                  <div class="np-time-bubble" id="npTimeBubble">00:00</div>
                  <div class="np-progress-bg">
                    <div class="np-buffer-bar" id="npBufferBar"></div>
                    <div class="np-played-bar" id="npPlayedBar"></div>
                    <div class="np-scrub-thumb" id="npScrubThumb"></div>
                  </div>
                </div>

                <!-- Controls Row -->
                <div class="np-row">
                  <!-- Left Controls -->
                  <div class="np-left-grp">
                    <!-- Play / Pause -->
                    <button class="np-btn" id="npPlayBtn" title="Oynat / Duraklat (Space)">
                      <svg id="npPlaySvg" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                    </button>
                    <!-- -10s -->
                    <button class="np-btn" id="npRewindBtn" title="10s Geri (J / Sol Ok)">
                      <svg viewBox="0 0 24 24"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6l8.5 6V6l-8.5 6z"/></svg>
                    </button>
                    <!-- +10s -->
                    <button class="np-btn" id="npForwardBtn" title="10s İleri (L / Sağ Ok)">
                      <svg viewBox="0 0 24 24"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg>
                    </button>
                    <!-- Volume Box -->
                    <div class="np-vol-box">
                      <button class="np-btn" id="npMuteBtn" title="Sesi Aç / Kapat (M)">
                        <svg id="npVolSvg" viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
                      </button>
                      <input type="range" class="np-vol-slider" id="npVolSlider" min="0" max="1" step="0.05" value="1">
                    </div>
                    <!-- Time Display -->
                    <div class="np-time-txt" id="npTimeDisplay" title="Geçen / Kalan Süre Modu">
                      <span id="npCurTime">00:00</span> / <span id="npDurTime">00:00</span>
                    </div>
                  </div>

                  <!-- Right Controls -->
                  <div class="np-right-grp">
                    <span class="np-tag-res">1080P HD</span>
                    
                    <!-- Speed Menu -->
                    <div class="np-menu-wrap">
                      <button class="np-btn" id="npSpeedBtn" title="Oynatma Hızı" style="font-weight:700;font-size:12px;width:34px">1x</button>
                      <div class="np-dropdown" id="npSpeedDropdown">
                        <div class="np-drop-item" data-spd="0.5">0.5x</div>
                        <div class="np-drop-item" data-spd="0.75">0.75x</div>
                        <div class="np-drop-item selected" data-spd="1">Normal (1x)</div>
                        <div class="np-drop-item" data-spd="1.25">1.25x</div>
                        <div class="np-drop-item" data-spd="1.5">1.5x</div>
                        <div class="np-drop-item" data-spd="2">2.0x</div>
                      </div>
                    </div>

                    <!-- Picture-in-Picture -->
                    <button class="np-btn" id="npPipBtn" title="Resim İçinde Resim (P)">
                      <svg viewBox="0 0 24 24"><path d="M19 7h-8v6h8V7zm2-4H3c-1.1 0-2 .9-2 2v14c0 1.1.9 1.98 2 1.98h18c1.1 0 2-.88 2-1.98V5c0-1.1-.9-2-2-2zm0 16.01H3V4.98h18v14.03z"/></svg>
                    </button>

                    <!-- Theater Mode -->
                    <button class="np-btn" id="npTheaterBtn" title="Sinema Modu (T)">
                      <svg viewBox="0 0 24 24"><path d="M19 6H5c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 10H5V8h14v8z"/></svg>
                    </button>

                    <!-- Fullscreen -->
                    <button class="np-btn" id="npFullscreenBtn" title="Tam Ekran (F)">
                      <svg id="npFsSvg" viewBox="0 0 24 24"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
"""

# Replace the old vstage
old_vstage_pattern = """          <div class="vstage" id="vstage">
            <div class="vload" id="vload">
              <div class="spin"></div>
              <span class="ltxt">Video yükleniyor…</span>
            </div>
            <video id="mainVideo" controls preload="metadata" style="display:none"></video>
          </div>"""

if '<div class="vstage" id="vstage">' in html:
    # Find start and end of vstage div
    s_idx = html.find('<div class="vstage" id="vstage">')
    e_idx = html.find('</div>\n          <div class="ptitle-top"', s_idx)
    if e_idx != -1:
        html = html[:s_idx] + custom_player_dom + html[e_idx+6:]
    else:
        # direct replace
        html = html.replace(old_vstage_pattern, custom_player_dom)

# 3. Add Custom Context Menu & Embed Modal to body
extra_modals = """
<!-- Ozel Context Menu -->
<div class="np-context-menu" id="npContextMenu">
  <div class="np-context-header">HFStream Cinema Player</div>
  <div class="np-ctx-item" id="ctxCopyUrl">🔗 Bu andaki video linkini kopyala</div>
  <div class="np-ctx-item" id="ctxCopyEmbed">📋 Embed kodunu kopyala (&lt;iframe&gt;)</div>
  <div class="np-ctx-item" id="ctxToggleLoop">🔁 Döngü (Loop: Kapalı)</div>
  <div class="np-ctx-item" id="ctxPip">🖼 Resim İçinde Resim (PiP)</div>
</div>

<!-- Embed Kodu Modal -->
<div class="modal-bg" id="embedModal">
  <div class="embed-modal-content">
    <div class="mhd">
      <h3>Sitene Ekle (Embed Kodu)</h3>
      <span class="mclose" onclick="closeEmbedModal()">✕</span>
    </div>
    <div class="embed-preview-tag">Aşağıdaki HTML kodunu web sitenize, blogunuza veya forumunuza yapıştırın:</div>
    <textarea class="embed-code-box" id="embedCodeText" readonly></textarea>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span style="font-size:12px;color:var(--tx3)">Otomatik boyutlanan (Responsive) ve Fullscreen destekli</span>
      <button class="btn-copy" onclick="copyEmbedCode()">Embed Kodunu Kopyala</button>
    </div>
  </div>
</div>
"""

if '<div class="modal-bg" id="embedModal">' not in html:
    html = html.replace('</body>', extra_modals + '\n</body>')

with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("CSS and HTML DOM updated successfully.")
