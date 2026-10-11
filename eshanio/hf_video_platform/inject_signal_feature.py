import os

html_path = "frontend/index.html"
with open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. CSS eklemesi
signal_css = '''
/* Tatlı, Şirin Sinyal Butonu (PC Yüklü mü?) */
.np-signal-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border-radius: 100px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  backdrop-filter: blur(12px);
  user-select: none;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  color: var(--tx2);
}
.np-signal-btn:hover {
  transform: translateY(-1px) scale(1.02);
}
.np-signal-btn .signal-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
  background: #8b949e;
}
/* YEŞİL: PC Yüklü & Aktif */
.np-signal-btn.signal-active {
  background: rgba(0, 229, 180, 0.14) !important;
  color: #00e5b4 !important;
  border-color: rgba(0, 229, 180, 0.4) !important;
  box-shadow: 0 0 14px rgba(0, 229, 180, 0.2);
}
.np-signal-btn.signal-active .signal-dot {
  background: #00e5b4 !important;
  box-shadow: 0 0 10px #00e5b4;
  animation: pulseGreen 1.8s infinite ease-in-out;
}
/* KIRMIZI: PC Yüklü Değil */
.np-signal-btn.signal-inactive {
  background: rgba(255, 71, 87, 0.15) !important;
  color: #ff6b81 !important;
  border-color: rgba(255, 71, 87, 0.4) !important;
  box-shadow: 0 0 14px rgba(255, 71, 87, 0.2);
}
.np-signal-btn.signal-inactive .signal-dot {
  background: #ff4757 !important;
  box-shadow: 0 0 10px #ff4757;
  animation: pulseRed 1.8s infinite ease-in-out;
}
@keyframes pulseGreen {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.35); opacity: 0.65; }
}
@keyframes pulseRed {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.35); opacity: 0.65; }
}

/* 3 Saniyelik Teşvik / Tanıtım Kartı */
.np-promo-toast {
  position: absolute;
  top: 54px;
  left: 18px;
  z-index: 80;
  max-width: 440px;
  background: rgba(13, 17, 23, 0.94);
  backdrop-filter: blur(18px) saturate(180%);
  border: 1px solid rgba(0, 229, 180, 0.35);
  border-radius: 12px;
  padding: 11px 15px;
  display: flex;
  align-items: center;
  gap: 12px;
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.7), 0 0 20px rgba(0, 229, 180, 0.15);
  transition: opacity 0.45s ease, transform 0.45s ease;
  animation: slideDownToast 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.np-promo-toast.hidden {
  opacity: 0;
  transform: translateY(-12px);
  pointer-events: none;
}
@keyframes slideDownToast {
  from { opacity: 0; transform: translateY(-16px); }
  to { opacity: 1; transform: translateY(0); }
}
.promo-toast-icon { font-size: 24px; flex-shrink: 0; }
.promo-toast-content { flex: 1; min-width: 0; }
.promo-toast-title { font-size: 12px; font-weight: 800; color: #fff; display: flex; align-items: center; gap: 8px; }
.promo-countdown { font-size: 10px; font-weight: 800; padding: 1px 6px; border-radius: 100px; background: rgba(0, 229, 180, 0.2); color: #00e5b4; border: 1px solid rgba(0, 229, 180, 0.3); }
.promo-toast-desc { font-size: 11px; color: var(--tx2); margin-top: 2px; line-height: 1.35; }
.promo-toast-action { padding: 5px 11px; border-radius: 8px; font-size: 11px; font-weight: 700; background: var(--acc); color: #000; cursor: pointer; transition: all 0.2s; flex-shrink: 0; }
.promo-toast-action:hover { opacity: 0.85; transform: scale(1.03); }
.promo-toast-close { background: none; border: none; color: var(--tx3); font-size: 14px; cursor: pointer; padding: 2px 4px; transition: color 0.2s; flex-shrink: 0; }
.promo-toast-close:hover { color: #fff; }

/* Teşvik / Sinyal Modalı */
.signal-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 99999;
  background: rgba(0, 0, 0, 0.82);
  backdrop-filter: blur(10px);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.signal-modal-backdrop.open { display: flex; }
.signal-modal-card {
  background: #0d1117;
  border: 1px solid rgba(0, 229, 180, 0.3);
  border-radius: 16px;
  max-width: 480px;
  width: 100%;
  padding: 24px;
  box-shadow: 0 25px 60px rgba(0,0,0,0.8), 0 0 35px rgba(0,229,180,0.15);
  animation: modalScale 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  text-align: center;
}
@keyframes modalScale {
  from { transform: scale(0.92); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
.signal-modal-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.signal-modal-status-badge { font-size: 12px; font-weight: 700; display: flex; align-items: center; gap: 6px; }
.signal-close-btn { color: var(--tx3); font-size: 18px; cursor: pointer; background: none; border: none; }
.signal-close-btn:hover { color: #fff; }
.signal-modal-icon { font-size: 44px; margin-bottom: 10px; }
.signal-modal-body h3 { font-size: 18px; font-weight: 800; color: #fff; margin-bottom: 8px; }
.signal-modal-body p { font-size: 13px; color: var(--tx2); line-height: 1.5; margin-bottom: 18px; }
.signal-steps { background: #161b22; border-radius: 10px; padding: 12px; margin-bottom: 20px; text-align: left; }
.sig-step { font-size: 12px; color: var(--tx); margin-bottom: 7px; display: flex; align-items: center; gap: 9px; }
.sig-step:last-child { margin-bottom: 0; }
.sig-step span { width: 18px; height: 18px; border-radius: 50%; background: var(--acc); color: #000; font-weight: 800; font-size: 10px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
.signal-modal-footer { display: flex; gap: 10px; justify-content: center; }
.signal-btn-download { flex: 1; padding: 10px 16px; border-radius: 10px; background: linear-gradient(135deg, var(--acc), #00b89c); color: #000; font-weight: 800; font-size: 13px; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.2s; }
.signal-btn-download:hover { opacity: 0.9; transform: translateY(-1px); }
.signal-btn-check { padding: 10px 16px; border-radius: 10px; background: #21262d; color: var(--tx2); font-weight: 700; font-size: 13px; cursor: pointer; border: none; transition: all 0.2s; }
.signal-btn-check:hover { background: #30363d; color: #fff; }
'''

if ".np-signal-btn" not in content:
    content = content.replace("</style>", signal_css + "\n</style>", 1)
    print("Added signal and promo CSS.")

# 2. HTML: Top bar'a np-signal-btn ekle
old_top_right = '''                <div class="np-top-right">
                  <button class="np-top-btn" id="btnEmbedCode" title="Sitene Ekle (Embed)">'''

new_top_right = '''                <div class="np-top-right">
                  <!-- Şirin Sinyal Butonu (PC Yüklü mü?) -->
                  <button class="np-signal-btn signal-inactive" id="npPcSignalBtn" title="HFVideoPlatform Sinyal Kontrolü">
                    <span class="signal-dot"></span>
                    <span class="signal-txt" id="npSignalTxt">Sinyal Aranıyor...</span>
                  </button>

                  <button class="np-top-btn" id="btnEmbedCode" title="Sitene Ekle (Embed)">'''

if old_top_right in content:
    content = content.replace(old_top_right, new_top_right, 1)
    print("Added npPcSignalBtn to np-top-right.")

# 3. HTML: npOverlay içine 3 saniyelik promo toast ekle
old_overlay_top = '''            <!-- OSD Overlays -->
            <div class="np-overlay" id="npOverlay">'''

new_overlay_top = '''            <!-- OSD Overlays -->
            <div class="np-overlay" id="npOverlay">
              <!-- 3 Saniyelik Tanıtım & Teşvik Duyurusu -->
              <div class="np-promo-toast" id="npPromoToast">
                <div class="promo-toast-icon">⚡</div>
                <div class="promo-toast-content">
                  <div class="promo-toast-title">
                    HFVideoPlatform P2P Dağıtık Akış
                    <span class="promo-countdown" id="promoCountdown">3s</span>
                  </div>
                  <div class="promo-toast-desc">
                    Kesintisiz 1080p hızlandırması için bilgisayarınıza kurun!
                  </div>
                </div>
                <button class="promo-toast-action" id="promoToastAction">Kurulumu Gör</button>
                <button class="promo-toast-close" id="promoToastClose" title="Kapat">✕</button>
              </div>'''

if old_overlay_top in content and "npPromoToast" not in content:
    content = content.replace(old_overlay_top, new_overlay_top, 1)
    print("Added npPromoToast to npOverlay.")

# 4. HTML: Sinyal Modalı ekle (body sonuna)
signal_modal_html = '''
<!-- PC Kurulum Teşvik & Sinyal Modalı -->
<div class="signal-modal-backdrop" id="signalModal">
  <div class="signal-modal-card">
    <div class="signal-modal-header">
      <div class="signal-modal-status-badge" id="sigModalBadge">
        <span class="signal-dot"></span> <span id="sigModalStatusTitle">HFVideoPlatform Sinyal Durumu</span>
      </div>
      <button class="signal-close-btn" id="sigModalClose">✕</button>
    </div>
    <div class="signal-modal-body">
      <div class="signal-modal-icon" id="sigModalIcon">🚀</div>
      <h3 id="sigModalHeading">HFVideoPlatform'u Bilgisayarınıza Kurun!</h3>
      <p id="sigModalDesc">
        Bu videoyu ve ağdaki tüm içerikleri sıfır donma, kristal netliğinde 1080p Ultra HD ve dağıtık P2P bant genişliği ile izleyin.
      </p>
      <div class="signal-steps" id="sigModalSteps">
        <div class="sig-step"><span>1</span> HFVideoPlatform.exe'yi bilgisayarınıza indirin</div>
        <div class="sig-step"><span>2</span> Programı çalıştırın (Port 8080 motoru devreye girer)</div>
        <div class="sig-step"><span>3</span> Tüm web sitelerindeki gömülü videolar anında yeşil sinyale döner ve son hızda akar!</div>
      </div>
    </div>
    <div class="signal-modal-footer">
      <a class="signal-btn-download" id="sigBtnDownload" href="http://127.0.0.1:8080/" target="_blank">
        📥 HFVideoPlatform İndir / Bağlan
      </a>
      <button class="signal-btn-check" id="sigBtnRecheck">🔄 Yeniden Kontrol Et</button>
    </div>
  </div>
</div>
'''

if "signalModal" not in content:
    content = content.replace("</body>", signal_modal_html + "\n</body>", 1)
    print("Added signalModal HTML to body.")

# 5. JS: Sinyal kontrolü ve 3 saniyelik promo toast mantığı
js_logic = '''
// ========================================================
// HFVIDEOPLATFORM PC KURULUM SINYAL MOTORU & 3S PROMO TOAST
// ========================================================
window.isPlatformInstalled = false;
var promoTimer = null;

function checkPcPlatformSignal() {
  var btn = document.getElementById('npPcSignalBtn');
  var txt = document.getElementById('npSignalTxt');
  var modalTitle = document.getElementById('sigModalStatusTitle');
  var modalHeading = document.getElementById('sigModalHeading');
  var modalDesc = document.getElementById('sigModalDesc');
  var modalIcon = document.getElementById('sigModalIcon');
  if (!btn) return;

  var controller = new AbortController();
  var timeoutId = setTimeout(function() { controller.abort(); }, 1800);

  fetch('http://127.0.0.1:8080/api/status', {
    method: 'GET',
    signal: controller.signal,
    mode: 'cors'
  }).then(function(res) {
    clearTimeout(timeoutId);
    return res.json();
  }).then(function(data) {
    if (data && (data.status === 'Online' || data.service)) {
      // 🟢 YEŞİL: PC Yüklü & Aktif
      btn.className = 'np-signal-btn signal-active';
      if (txt) txt.textContent = 'PC Motoru: Aktif (P2P)';
      btn.title = 'HFVideoPlatform bilgisayarınızda aktif ve çalışıyor!';
      window.isPlatformInstalled = true;

      if (modalTitle) modalTitle.innerHTML = '<span style=\"color:#00e5b4\">🟢 PC Motoru Aktif</span>';
      if (modalIcon) modalIcon.textContent = '🎉';
      if (modalHeading) modalHeading.textContent = 'Harika! HFVideoPlatform Aktif';
      if (modalDesc) modalDesc.textContent = 'Bilgisayarınızda yerel motorunuz çalışıyor. Videoları dağıtık P2P ağınız üzerinden en yüksek hızda, donmadan ve 1080p kalitesinde izliyorsunuz.';
    } else {
      setSignalInactive();
    }
  }).catch(function(err) {
    clearTimeout(timeoutId);
    setSignalInactive();
  });

  function setSignalInactive() {
    // 🔴 KIRMIZI: PC Yüklü Değil / Kapalı
    btn.className = 'np-signal-btn signal-inactive';
    if (txt) txt.textContent = 'PC Motoru: Yüklü Değil';
    btn.title = 'HFVideoPlatform bilgisayarınızda açık değil. Tıklayıp hemen kurun!';
    window.isPlatformInstalled = false;

    if (modalTitle) modalTitle.innerHTML = '<span style=\"color:#ff4757\">🔴 PC Motoru Yüklü Değil</span>';
    if (modalIcon) modalIcon.textContent = '🚀';
    if (modalHeading) modalHeading.textContent = 'HFVideoPlatform\\'u Bilgisayarınıza Kurun!';
    if (modalDesc) modalDesc.textContent = 'Bu videoyu ve binlerce HuggingFace içeriğini sıfır donma, 1080p Ultra HD ve P2P dağıtık ağ hızıyla izlemek için HFVideoPlatform motorunu bilgisayarınıza kurun.';
  }
}

function trigger3sPromoToast() {
  var toast = document.getElementById('npPromoToast');
  var countdownEl = document.getElementById('promoCountdown');
  if (!toast) return;

  toast.classList.remove('hidden');
  var timeLeft = 3;
  if (countdownEl) countdownEl.textContent = timeLeft + 's';

  if (promoTimer) clearInterval(promoTimer);
  promoTimer = setInterval(function() {
    timeLeft--;
    if (countdownEl) countdownEl.textContent = timeLeft + 's';
    if (timeLeft <= 0) {
      clearInterval(promoTimer);
      toast.classList.add('hidden');
    }
  }, 1000);
}

function initSignalAndPromoEvents() {
  // Sinyal butonu tıklandığında modalı aç
  var btn = document.getElementById('npPcSignalBtn');
  var modal = document.getElementById('signalModal');
  var closeBtn = document.getElementById('sigModalClose');
  var recheckBtn = document.getElementById('sigBtnRecheck');
  var toastAction = document.getElementById('promoToastAction');
  var toastClose = document.getElementById('promoToastClose');

  if (btn && modal) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      modal.classList.add('open');
    });
  }

  if (toastAction && modal) {
    toastAction.addEventListener('click', function(e) {
      e.stopPropagation();
      modal.classList.add('open');
    });
  }

  if (toastClose) {
    toastClose.addEventListener('click', function(e) {
      e.stopPropagation();
      var toast = document.getElementById('npPromoToast');
      if (toast) toast.classList.add('hidden');
      if (promoTimer) clearInterval(promoTimer);
    });
  }

  if (closeBtn && modal) {
    closeBtn.addEventListener('click', function() {
      modal.classList.remove('open');
    });
  }

  if (modal) {
    modal.addEventListener('click', function(e) {
      if (e.target === modal) modal.classList.remove('open');
    });
  }

  if (recheckBtn) {
    recheckBtn.addEventListener('click', function() {
      showToast('Sinyal kontrol ediliyor...');
      checkPcPlatformSignal();
    });
  }

  // İlk sinyal kontrolünü başlat ve periyodik her 10 saniyede bir kontrol et
  checkPcPlatformSignal();
  setInterval(checkPcPlatformSignal, 10000);
}
'''

if "checkPcPlatformSignal" not in content:
    content = content.replace("document.addEventListener('DOMContentLoaded', function() {", js_logic + "\n document.addEventListener('DOMContentLoaded', function() {\n  initSignalAndPromoEvents();\n", 1)
    print("Added checkPcPlatformSignal and initSignalAndPromoEvents.")

# showWatch içine de trigger3sPromoToast() ekleyelim
if "trigger3sPromoToast();" not in content:
    content = content.replace("function showWatch(vid) {", "function showWatch(vid) {\n  trigger3sPromoToast();\n  checkPcPlatformSignal();\n", 1)
    print("Added trigger3sPromoToast() call in showWatch.")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(content)

print("frontend/index.html updated with PC Signal Button and 3s Promo Toast!")
