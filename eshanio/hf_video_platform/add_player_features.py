# -*- coding: utf-8 -*-
with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update CSS with Ambient Glow, Nerds Stats, Quality Menu & Autoplay Switch
extra_css = """
/* ========================================================
   SINEMATIK ISIKLANDIRMA (AMBIENT MODE)
======================================================== */
.np-ambient-canvas {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%) scale(1.15);
  width: 100%;
  height: 100%;
  filter: blur(55px) saturate(180%) brightness(0.9);
  opacity: 0.65;
  pointer-events: none;
  z-index: 1;
  transition: opacity 0.5s ease;
}
.nova-player.ambient-off .np-ambient-canvas {
  display: none !important;
}

/* ========================================================
   MERAKLISI ICIN ISTATISTIKLER (STATS FOR NERDS)
======================================================== */
.np-stats-hud {
  position: absolute;
  top: 60px;
  left: 20px;
  background: rgba(8, 8, 14, 0.88);
  border: 1px solid rgba(0, 229, 180, 0.3);
  box-shadow: 0 14px 40px rgba(0,0,0,0.85), 0 0 20px rgba(0,229,180,0.12);
  border-radius: 12px;
  padding: 16px 20px;
  font-family: Consolas, Monaco, monospace;
  font-size: 11px;
  color: #a7f3d0;
  backdrop-filter: blur(16px);
  z-index: 50;
  display: none;
  min-width: 320px;
  max-width: 400px;
  line-height: 1.6;
  user-select: text;
}
.np-stats-hud.open {
  display: block;
  animation: hudIn 0.25s ease;
}
@keyframes hudIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
.np-stats-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  padding-bottom: 8px;
  margin-bottom: 10px;
  color: #fff;
  font-weight: 700;
  font-size: 12px;
}
.np-stats-head span {
  color: var(--np-acc);
}
.np-stats-close {
  cursor: pointer;
  color: #9ca3af;
  font-size: 16px;
  transition: color 0.15s;
}
.np-stats-close:hover {
  color: #fff;
}
.np-stat-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.np-stat-label {
  color: #9ca3af;
}
.np-stat-val {
  color: #fff;
  font-weight: 600;
}

/* ========================================================
   OTOMATIK OYNATMA (AUTOPLAY SWITCH)
======================================================== */
.np-autoplay-box {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  user-select: none;
}
.np-autoplay-label {
  font-size: 11px;
  font-weight: 700;
  color: #9ca3af;
  letter-spacing: 0.3px;
  transition: color 0.2s;
}
.np-autoplay-box:hover .np-autoplay-label {
  color: #fff;
}
.np-switch {
  position: relative;
  width: 32px;
  height: 18px;
  display: inline-block;
}
.np-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.np-slider-round {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background-color: rgba(255, 255, 255, 0.2);
  transition: .3s;
  border-radius: 20px;
}
.np-slider-round:before {
  position: absolute;
  content: "";
  height: 12px;
  width: 12px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: .3s;
  border-radius: 50%;
}
.np-switch input:checked + .np-slider-round {
  background-color: var(--np-acc);
  box-shadow: 0 0 10px var(--np-acc-glow);
}
.np-switch input:checked + .np-slider-round:before {
  transform: translateX(14px);
  background-color: #000;
}

/* ========================================================
   KALITE SECICI MENUSU (QUALITY DROPDOWN)
======================================================== */
.np-quality-btn {
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  padding: 4px 9px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 5px;
  transition: all 0.2s ease;
}
.np-quality-btn:hover {
  background: var(--np-acc);
  color: #000;
  border-color: var(--np-acc);
  box-shadow: 0 0 12px var(--np-acc-glow);
}
.np-quality-menu {
  position: absolute;
  bottom: 38px;
  right: 0;
  background: rgba(14, 14, 22, 0.96);
  border: 1px solid rgba(0, 229, 180, 0.3);
  border-radius: 10px;
  padding: 6px 0;
  min-width: 140px;
  box-shadow: 0 12px 36px rgba(0,0,0,0.85);
  backdrop-filter: blur(14px);
  display: none;
  flex-direction: column;
  z-index: 35;
}
.np-quality-menu.open {
  display: flex;
}

/* OTOMATIK GECIS GERI SAYIM OVERLAY */
.np-next-overlay {
  position: absolute;
  bottom: 80px;
  right: 24px;
  background: rgba(8, 8, 14, 0.92);
  border: 1px solid var(--np-acc);
  box-shadow: 0 10px 30px rgba(0,0,0,0.8), 0 0 20px var(--np-acc-glow);
  padding: 14px 18px;
  border-radius: 12px;
  display: none;
  align-items: center;
  gap: 14px;
  z-index: 40;
  animation: slideNext 0.3s ease;
}
@keyframes slideNext { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: none; } }
.np-next-info {
  display: flex;
  flex-direction: column;
}
.np-next-tit {
  font-size: 11px;
  color: var(--np-acc);
  font-weight: 700;
  text-transform: uppercase;
}
.np-next-name {
  font-size: 13px;
  color: #fff;
  font-weight: 600;
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.np-next-cancel {
  background: rgba(255,255,255,0.15);
  border: none;
  color: #fff;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}
.np-next-cancel:hover { background: rgba(255,255,255,0.25); }
"""

# Append extra_css before </style>
if "/* SINEMATIK ISIKLANDIRMA */" not in html:
    html = html.replace("</style>", extra_css + "\n</style>")

# 2. Update NovaPlayer DOM with Ambient Canvas, Stats HUD, Next Overlay & Quality Dropdown
old_player_start = '<div class="nova-player" id="novaPlayerWrap">'
new_player_start = """<div class="nova-player" id="novaPlayerWrap">
            <!-- Sinematik Isiklandirma (Ambient Canvas) -->
            <canvas class="np-ambient-canvas" id="npAmbientCanvas"></canvas>

            <!-- Meraklısı İçin İstatistikler (Stats for Nerds HUD) -->
            <div class="np-stats-hud" id="npStatsHud">
              <div class="np-stats-head">
                <div>⚡ <span>HFStream</span> Stats for Nerds</div>
                <div class="np-stats-close" onclick="toggleStatsHud()">✕</div>
              </div>
              <div class="np-stat-row"><span class="np-stat-label">Video ID:</span><span class="np-stat-val" id="statVidId">--</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Çözünürlük:</span><span class="np-stat-val" id="statRes">1920x1080@60fps (1080p)</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Bant Genişliği / Hız:</span><span class="np-stat-val" id="statBitrate">~14.2 Mbps (HuggingFace CDN)</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Tampon Sağlığı:</span><span class="np-stat-val" id="statBuffer">0.0 s</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Video Kodek:</span><span class="np-stat-val">avc1.64002a (H.264 High)</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Ses Kodek:</span><span class="np-stat-val">mp4a.40.2 (AAC-LC Stereo)</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Düşen Kareler:</span><span class="np-stat-val" id="statDropped">0 / 0 (%0.0)</span></div>
              <div class="np-stat-row"><span class="np-stat-label">Şifreleme & P2P:</span><span class="np-stat-val">HF-XOR 0x42 Dağıtık Akış</span></div>
            </div>

            <!-- Sıradaki Video Otomatik Başlama Overlay -->
            <div class="np-next-overlay" id="npNextOverlay">
              <div class="np-next-info">
                <span class="np-next-tit">Sıradaki Video (<span id="nextSecCount">4</span>s)</span>
                <span class="np-next-name" id="nextVideoTitle">Sonraki Bölüm</span>
              </div>
              <button class="np-next-cancel" onclick="cancelNextCountdown()">İptal Et</button>
            </div>
"""

if '<canvas class="np-ambient-canvas"' not in html:
    html = html.replace(old_player_start, new_player_start)

# Replace <span class="np-tag-res">1080P HD</span> with Quality Dropdown + Autoplay Switch + Ambient Toggle + Stats Button
old_tag_res = '<span class="np-tag-res">1080P HD</span>'
new_controls_extra = """
                    <!-- Otomatik Oynatma Switch -->
                    <div class="np-autoplay-box" title="Otomatik Sonraki Videoya Geç">
                      <span class="np-autoplay-label">Oto</span>
                      <label class="np-switch">
                        <input type="checkbox" id="npAutoplayToggle" checked>
                        <span class="np-slider-round"></span>
                      </label>
                    </div>

                    <!-- Sinematik Isıklandırma Butonu -->
                    <button class="np-btn" id="npAmbientBtn" title="Sinematik Işıklandırma (Ambient Glow: Açık/Kapalı)">
                      <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
                    </button>

                    <!-- Kalite Seçici Menüsü -->
                    <div class="np-menu-wrap">
                      <button class="np-quality-btn" id="npQualityBtn" title="Görüntü Kalitesi">
                        <span id="npCurQuality">1080p HD</span>
                        <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg>
                      </button>
                      <div class="np-quality-menu" id="npQualityMenu">
                        <div class="np-drop-item" data-res="auto">Otomatik (1080p)</div>
                        <div class="np-drop-item selected" data-res="1080p">1080p HD Ultra</div>
                        <div class="np-drop-item" data-res="720p">720p HD</div>
                        <div class="np-drop-item" data-res="480p">480p SD</div>
                        <div class="np-drop-item" data-res="240p">240p</div>
                        <div class="np-drop-item" data-res="144p">144p Tasarruf</div>
                      </div>
                    </div>
"""

if '<button class="np-quality-btn"' not in html:
    html = html.replace(old_tag_res, new_controls_extra)

# Add "İstatistikler" and "Sinematik Işıklandırma" to Custom Context Menu
old_ctx = '<div class="np-ctx-item" id="ctxPip">🖼 Resim İçinde Resim (PiP)</div>'
new_ctx = """<div class="np-ctx-item" id="ctxPip">🖼 Resim İçinde Resim (PiP)</div>
  <div class="np-ctx-item" id="ctxStats">📊 Meraklısı İçin İstatistikler (Stats)</div>
  <div class="np-ctx-item" id="ctxAmbient">💡 Sinematik Işıklandırma (Ambient Glow)</div>"""

if '<div class="np-ctx-item" id="ctxStats">' not in html:
    html = html.replace(old_ctx, new_ctx)

with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("CSS, HUD, Ambient, Quality, and Context DOM updated successfully.")
