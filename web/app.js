/**
 * 24/7 YouTube Live Streaming Control Panel Client
 * Real-time WebSocket telemetry, interactive stream controls & log streaming.
 */

// State
let appConfig = {};
let isKeyRevealed = false;
let isKickKeyRevealed = false;
let isTwitchKeyRevealed = false;
let isNimoKeyRevealed = false;
let isTiktokKeyRevealed = false;
let autoScroll = true;
let allLogs = [];
let statusWs = null;
let logsWs = null;
let pollInterval = null;

// DOM Elements
const topStatusBadge = document.getElementById("topStatusBadge");
const topStatusText = document.getElementById("topStatusText");
const wsConnectionBadge = document.getElementById("wsConnectionBadge");
const wsConnectionText = document.getElementById("wsConnectionText");
const masterStatusTitle = document.getElementById("masterStatusTitle");
const liveRadar = document.getElementById("liveRadar");
const radarCenterIcon = document.getElementById("radarCenterIcon");

const lblActiveSource = document.getElementById("lblActiveSource");
const lblYtStatus = document.getElementById("lblYtStatus");
const lblKickStatus = document.getElementById("lblKickStatus");
const lblNimoStatus = document.getElementById("lblNimoStatus");
const lblTiktokStatus = document.getElementById("lblTiktokStatus");
const lblBroadcastMode = document.getElementById("lblBroadcastMode");
const lblWatchdogState = document.getElementById("lblWatchdogState");

const valStreamUptime = document.getElementById("valStreamUptime");
const valAppUptime = document.getElementById("valAppUptime");
const valFpsBitrate = document.getElementById("valFpsBitrate");
const valBitrateSpeed = document.getElementById("valBitrateSpeed");
const valReconnectCount = document.getElementById("valReconnectCount");
const valRetryStatus = document.getElementById("valRetryStatus");
const valCpuRam = document.getElementById("valCpuRam");
const valFfmpegPid = document.getElementById("valFfmpegPid");
const valStreamHealth = document.getElementById("valStreamHealth");

// Admin Auth Elements & Helpers
const btnAdminAuth = document.getElementById("btnAdminAuth");
const iconAdminAuth = document.getElementById("iconAdminAuth");
const txtAdminAuth = document.getElementById("txtAdminAuth");
const inputAdminPassword = document.getElementById("inputAdminPassword");
const btnToggleAdminPass = document.getElementById("btnToggleAdminPass");
let isAdminPassRevealed = false;

function getAdminPassword() {
  return localStorage.getItem("stream_admin_pass") || "";
}

function setAdminPassword(pass) {
  if (pass) {
    localStorage.setItem("stream_admin_pass", pass);
  } else {
    localStorage.removeItem("stream_admin_pass");
  }
  updateAdminAuthButtonState();
}

function authHeaders(extra = {}) {
  const pass = getAdminPassword();
  const headers = { ...extra };
  if (pass) {
    headers["X-Admin-Password"] = pass;
  }
  return headers;
}

function updateAdminAuthButtonState(hasServerPassword = null) {
  if (hasServerPassword !== null) {
    window._serverHasPassword = hasServerPassword;
  }
  const isReq = window._serverHasPassword;
  const currentPass = getAdminPassword();

  if (txtAdminAuth && iconAdminAuth) {
    if (isReq) {
      if (currentPass) {
        iconAdminAuth.textContent = "🔒";
        txtAdminAuth.textContent = "Yetkili";
        txtAdminAuth.style.color = "#34d399";
      } else {
        iconAdminAuth.textContent = "🔑";
        txtAdminAuth.textContent = "Giriş Yap";
        txtAdminAuth.style.color = "#f59e0b";
      }
    } else {
      iconAdminAuth.textContent = "🔓";
      txtAdminAuth.textContent = "Admin";
      txtAdminAuth.style.color = "#94a3b8";
    }
  }
}

async function authenticatedFetch(url, options = {}) {
  options.headers = authHeaders(options.headers || {});
  let res = await fetch(url, options);
  if (res.status === 401) {
    const entered = prompt("🔒 Bu işlem için Admin Şifresi gereklidir. Lütfen şifrenizi giriniz:");
    if (entered) {
      setAdminPassword(entered.trim());
      options.headers = authHeaders(options.headers || {});
      res = await fetch(url, options);
    }
  }
  return res;
}

// Buttons
const btnStartStream = document.getElementById("btnStartStream");
const btnStopStream = document.getElementById("btnStopStream");
const btnRestartStream = document.getElementById("btnRestartStream");

// Settings Elements - YouTube, Kick & TikTok
const formCredentials = document.getElementById("formCredentials");
const chkYoutubeEnabled = document.getElementById("chkYoutubeEnabled");
const inputRtmpUrl = document.getElementById("inputRtmpUrl");
const inputStreamKey = document.getElementById("inputStreamKey");
const btnToggleKeyVisibility = document.getElementById("btnToggleKeyVisibility");

const chkKickEnabled = document.getElementById("chkKickEnabled");
const inputKickRtmpUrl = document.getElementById("inputKickRtmpUrl");
const inputKickStreamKey = document.getElementById("inputKickStreamKey");
const btnToggleKickKeyVisibility = document.getElementById("btnToggleKickKeyVisibility");

const chkTwitchEnabled = document.getElementById("chkTwitchEnabled");
const inputTwitchRtmpUrl = document.getElementById("inputTwitchRtmpUrl");
const inputTwitchStreamKey = document.getElementById("inputTwitchStreamKey");
const btnToggleTwitchKeyVisibility = document.getElementById("btnToggleTwitchKeyVisibility");

const chkNimoEnabled = document.getElementById("chkNimoEnabled");
const inputNimoRtmpUrl = document.getElementById("inputNimoRtmpUrl");
const inputNimoStreamKey = document.getElementById("inputNimoStreamKey");
const btnToggleNimoKeyVisibility = document.getElementById("btnToggleNimoKeyVisibility");

const chkTiktokEnabled = document.getElementById("chkTiktokEnabled");
const inputTiktokRtmpUrl = document.getElementById("inputTiktokRtmpUrl");
const inputTiktokStreamKey = document.getElementById("inputTiktokStreamKey");
const btnToggleTiktokKeyVisibility = document.getElementById("btnToggleTiktokKeyVisibility");

let isTiktokSessionRevealed = false;
const inputTiktokSessionId = document.getElementById("inputTiktokSessionId");
const btnToggleTiktokSessionVisibility = document.getElementById("btnToggleTiktokSessionVisibility");
const btnToggleCookieGuide = document.getElementById("btnToggleCookieGuide");
const cookieGuideBox = document.getElementById("cookieGuideBox");
const inputTiktokEvent = document.getElementById("inputTiktokEvent");
const inputTiktokTitle = document.getElementById("inputTiktokTitle");
const btnGenerateTiktokKey = document.getElementById("btnGenerateTiktokKey");
const lblBtnGenKey = document.getElementById("lblBtnGenKey");
const btnGenerateAndStartTiktok = document.getElementById("btnGenerateAndStartTiktok");
const lblBtnGenAndStart = document.getElementById("lblBtnGenAndStart");
const btnFinishTiktokRoom = document.getElementById("btnFinishTiktokRoom");
const badgeActiveRoom = document.getElementById("badgeActiveRoom");
const lblActiveRoomId = document.getElementById("lblActiveRoomId");
const genStatusMessage = document.getElementById("genStatusMessage");

const inputVideoSource = document.getElementById("inputVideoSource");

const formStreamSettings = document.getElementById("formStreamSettings");
const selectResolution = document.getElementById("selectResolution");
const selectFps = document.getElementById("selectFps");
const inputBitrate = document.getElementById("inputBitrate");
const selectPreset = document.getElementById("selectPreset");
const selectHwAccel = document.getElementById("selectHwAccel");
const chkLoop = document.getElementById("chkLoop");
const chkAutoReconnect = document.getElementById("chkAutoReconnect");
const chkAutoStart = document.getElementById("chkAutoStart");

// Video Elements
const videoListContainer = document.getElementById("videoListContainer");
const uploadDropzone = document.getElementById("uploadDropzone");
const fileVideoUpload = document.getElementById("fileVideoUpload");
const uploadProgressBar = document.getElementById("uploadProgressBar");
const uploadProgressFill = document.getElementById("uploadProgressFill");
const btnGenerateSampleVideo = document.getElementById("btnGenerateSampleVideo");

// Inspector
const inspTarget = document.getElementById("inspTarget");
const inspStatus = document.getElementById("inspStatus");
const inspResolution = document.getElementById("inspResolution");
const inspDuration = document.getElementById("inspDuration");
const inspCodecs = document.getElementById("inspCodecs");
const badgeSourceType = document.getElementById("badgeSourceType");

// Playlist
const playlistCounter = document.getElementById("playlistCounter");
const playlistItemsBox = document.getElementById("playlistItemsBox");
const inputPlaylistSource = document.getElementById("inputPlaylistSource");
const btnAddPlaylist = document.getElementById("btnAddPlaylist");

// Console
const consoleOutput = document.getElementById("consoleOutput");
const logSearchInput = document.getElementById("logSearchInput");
const logLevelFilter = document.getElementById("logLevelFilter");
const chkAutoScroll = document.getElementById("chkAutoScroll");
const btnClearLogs = document.getElementById("btnClearLogs");
const btnCopyLogs = document.getElementById("btnCopyLogs");

// Toasts
const toastContainer = document.getElementById("toastContainer");

function showToast(message, type = "info") {
  const target = document.getElementById("toastContainer");
  if (!target) {
    console.log(`[Toast ${type}]: ${message}`);
    return;
  }
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  target.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

window.showToast = window.showToast || showToast;

/* ==========================================================================
   INITIALIZATION
   ========================================================================== */
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupEventListeners();
  initStudioControls();
  loadConfig();
  loadVideos();
  loadPlaylist();
  initWebSockets();
});

/* ==========================================================================
   TAB NAVIGATION
   ========================================================================== */
function setupTabs() {
  const tabButtons = document.querySelectorAll(".tab-button");
  const tabPanes = document.querySelectorAll(".tab-pane");

  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-tab");

      tabButtons.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");
    });
  });
}

/* ==========================================================================
   EVENT LISTENERS
   ========================================================================== */
function setupEventListeners() {
  // Stream Controls
  btnStartStream.addEventListener("click", () => handleStreamAction("start"));
  btnStopStream.addEventListener("click", () => handleStreamAction("stop"));
  btnRestartStream.addEventListener("click", () => handleStreamAction("restart"));

  // YouTube Key Visibility Toggle
  if (btnToggleKeyVisibility && inputStreamKey) {
    btnToggleKeyVisibility.addEventListener("click", () => {
      isKeyRevealed = !isKeyRevealed;
      inputStreamKey.type = isKeyRevealed ? "text" : "password";
      btnToggleKeyVisibility.textContent = isKeyRevealed ? "🔒" : "👁️";
    });
  }

  // Kick Key Visibility Toggle
  if (btnToggleKickKeyVisibility && inputKickStreamKey) {
    btnToggleKickKeyVisibility.addEventListener("click", () => {
      isKickKeyRevealed = !isKickKeyRevealed;
      inputKickStreamKey.type = isKickKeyRevealed ? "text" : "password";
      btnToggleKickKeyVisibility.textContent = isKickKeyRevealed ? "🔒" : "👁️";
    });
  }

  // Twitch Key Visibility Toggle
  if (btnToggleTwitchKeyVisibility && inputTwitchStreamKey) {
    btnToggleTwitchKeyVisibility.addEventListener("click", () => {
      isTwitchKeyRevealed = !isTwitchKeyRevealed;
      inputTwitchStreamKey.type = isTwitchKeyRevealed ? "text" : "password";
      btnToggleTwitchKeyVisibility.textContent = isTwitchKeyRevealed ? "🔒" : "👁️";
    });
  }

  // Nimo Key Visibility Toggle
  if (btnToggleNimoKeyVisibility && inputNimoStreamKey) {
    btnToggleNimoKeyVisibility.addEventListener("click", () => {
      isNimoKeyRevealed = !isNimoKeyRevealed;
      inputNimoStreamKey.type = isNimoKeyRevealed ? "text" : "password";
      btnToggleNimoKeyVisibility.textContent = isNimoKeyRevealed ? "🔒" : "👁️";
    });
  }

  // TikTok Key Visibility Toggle
  if (btnToggleTiktokKeyVisibility && inputTiktokStreamKey) {
    btnToggleTiktokKeyVisibility.addEventListener("click", () => {
      isTiktokKeyRevealed = !isTiktokKeyRevealed;
      inputTiktokStreamKey.type = isTiktokKeyRevealed ? "text" : "password";
      btnToggleTiktokKeyVisibility.textContent = isTiktokKeyRevealed ? "🔒" : "👁️";
    });
  }

  // TikTok Session ID Visibility Toggle
  if (btnToggleTiktokSessionVisibility && inputTiktokSessionId) {
    btnToggleTiktokSessionVisibility.addEventListener("click", () => {
      isTiktokSessionRevealed = !isTiktokSessionRevealed;
      inputTiktokSessionId.type = isTiktokSessionRevealed ? "text" : "password";
      btnToggleTiktokSessionVisibility.textContent = isTiktokSessionRevealed ? "🔒" : "👁️";
    });
  }

  // TikTok Cookie Guide Toggle
  if (btnToggleCookieGuide && cookieGuideBox) {
    btnToggleCookieGuide.addEventListener("click", () => {
      const isHidden = cookieGuideBox.style.display === "none";
      cookieGuideBox.style.display = isHidden ? "block" : "none";
      btnToggleCookieGuide.textContent = isHidden ? "✖️ Rehberi Kapat" : "❓ sessionid nasıl alınır?";
    });
  }

  // TikTok Generator Buttons
  if (btnGenerateTiktokKey) {
    btnGenerateTiktokKey.addEventListener("click", () => triggerTikTokKeyGeneration(false));
  }
  if (btnGenerateAndStartTiktok) {
    btnGenerateAndStartTiktok.addEventListener("click", () => triggerTikTokKeyGeneration(true));
  }
  if (btnFinishTiktokRoom) {
    btnFinishTiktokRoom.addEventListener("click", finishTikTokRoom);
  }

  // Settings Forms
  formCredentials.addEventListener("submit", (e) => {
    e.preventDefault();
    saveCredentials();
  });

  formStreamSettings.addEventListener("submit", (e) => {
    e.preventDefault();
    saveStreamSettings();
  });

  // Admin Auth Header Button
  if (btnAdminAuth) {
    btnAdminAuth.addEventListener("click", () => {
      const current = getAdminPassword();
      const newPass = prompt("Admin Şifresini girin veya güncelleyin (Mevcut: " + (current ? "Ayarlı" : "Yok") + "):", current);
      if (newPass !== null) {
        setAdminPassword(newPass.trim());
        showToast(newPass.trim() ? "Admin şifresi tarayıcıya kaydedildi." : "Admin şifresi temizlendi.", "info");
      }
    });
  }

  // Admin Password Visibility Toggle in Settings
  if (btnToggleAdminPass && inputAdminPassword) {
    btnToggleAdminPass.addEventListener("click", () => {
      isAdminPassRevealed = !isAdminPassRevealed;
      inputAdminPassword.type = isAdminPassRevealed ? "text" : "password";
      btnToggleAdminPass.textContent = isAdminPassRevealed ? "🔒" : "👁️";
    });
  }

  selectResolution.addEventListener("change", (e) => {
    updateModeBadge(e.target.value);
  });

  // Generate Sample Video Button
  btnGenerateSampleVideo.addEventListener("click", generateSampleVideo);

  // File Upload
  uploadDropzone.addEventListener("click", () => fileVideoUpload.click());
  uploadDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadDropzone.classList.add("dragover");
  });
  uploadDropzone.addEventListener("dragleave", () => uploadDropzone.classList.remove("dragover"));
  uploadDropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadDropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });
  fileVideoUpload.addEventListener("change", () => {
    if (fileVideoUpload.files.length > 0) {
      handleFileUpload(fileVideoUpload.files[0]);
    }
  });

  // Playlist actions
  btnAddPlaylist.addEventListener("click", addPlaylistSource);

  // Console actions
  logSearchInput.addEventListener("input", renderLogs);
  logLevelFilter.addEventListener("change", renderLogs);
  chkAutoScroll.addEventListener("change", (e) => { autoScroll = e.target.checked; });
  btnClearLogs.addEventListener("click", clearConsoleLogs);
  btnCopyLogs.addEventListener("click", copyConsoleLogs);
}

/* ==========================================================================
   WEBSOCKETS & TELEMETRY
   ========================================================================== */
let wsReconnectTimeout = null;

function setWsStatus(state) {
  if (!wsConnectionBadge || !wsConnectionText) return;
  if (state === "connected") {
    wsConnectionBadge.className = "ws-badge ws-badge-connected";
    wsConnectionText.textContent = "WebSocket Canlı";
    wsConnectionBadge.title = "Gerçek Zamanlı Çift Yönlü WebSocket Bağlantısı Aktif";
  } else if (state === "polling") {
    wsConnectionBadge.className = "ws-badge ws-badge-polling";
    wsConnectionText.textContent = "Polling Modu";
    wsConnectionBadge.title = "WebSocket kesildi, 2sn HTTP yoklama devrede";
  } else {
    wsConnectionBadge.className = "ws-badge ws-badge-disconnected";
    wsConnectionText.textContent = "Bağlantı Kesildi";
    wsConnectionBadge.title = "Sunucu bağlantısı koptu";
  }
}

function initWebSockets() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;

  // Status WebSocket
  try {
    statusWs = new WebSocket(`${protocol}//${host}/ws/status`);
    statusWs.onopen = () => {
      setWsStatus("connected");
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    };
    statusWs.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        updateTelemetryUI(data);
      } catch (err) {
        console.error("Telemetry parse error", err);
      }
    };
    statusWs.onerror = () => {
      setWsStatus("polling");
      startPollingFallback();
      scheduleWsReconnect();
    };
    statusWs.onclose = () => {
      setWsStatus("polling");
      startPollingFallback();
      scheduleWsReconnect();
    };
  } catch (e) {
    setWsStatus("polling");
    startPollingFallback();
  }

  // Logs WebSocket
  try {
    logsWs = new WebSocket(`${protocol}//${host}/ws/logs`);
    logsWs.onmessage = (event) => {
      try {
        const logEntry = JSON.parse(event.data);
        appendLogEntry(logEntry);
      } catch (err) {
        console.error("Log parse error", err);
      }
    };
    logsWs.onerror = () => fetchLogsRest();
  } catch (e) {
    fetchLogsRest();
  }
}

function scheduleWsReconnect() {
  if (wsReconnectTimeout) return;
  wsReconnectTimeout = setTimeout(() => {
    wsReconnectTimeout = null;
    if (!statusWs || statusWs.readyState === WebSocket.CLOSED) {
      initWebSockets();
    }
  }, 3000);
}

function startPollingFallback() {
  if (!pollInterval) {
    pollInterval = setInterval(async () => {
      try {
        const res = await fetch("/api/status");
        if (res.ok) {
          const data = await res.json();
          updateTelemetryUI(data);
        }
      } catch (e) {}
    }, 2000);
  }
}

/* ==========================================================================
   UI TELEMETRY UPDATES
   ========================================================================== */
function updateTelemetryUI(data) {
  if (!data) return;

  const status = data.overall_status || "STOPPED";
  const streamer = data.streamer || {};
  const yt = data.youtube || {};
  const kick = data.kick || {};
  const twitch = data.twitch || {};
  const nimo = data.nimo || {};
  const tiktok = data.tiktok || {};
  const src = data.source || {};
  const watchdog = data.watchdog || {};
  const sys = data.system || {};
  const isMulti = data.is_multistream || (streamer.active_targets && streamer.active_targets.length > 1);

  // 1. Top Status Badge
  topStatusBadge.setAttribute("data-status", status);
  topStatusText.textContent = status;

  // 2. Master Radar & Card
  if (status === "LIVE") {
    liveRadar.classList.add("active");
    radarCenterIcon.textContent = "🟢";
    masterStatusTitle.className = "status-title-live";
    const targets = streamer.active_targets || [];
    if (isMulti) {
      masterStatusTitle.textContent = `MULTI-STREAM LIVE (${targets.join(" + ").toUpperCase() || "ACTIVE"})`;
    } else if (targets.includes("TikTok")) {
      masterStatusTitle.textContent = "TIKTOK LIVE BROADCAST LIVE";
    } else if (targets.includes("Kick")) {
      masterStatusTitle.textContent = "KICK.COM BROADCAST LIVE";
    } else if (targets.includes("Nimo")) {
      masterStatusTitle.textContent = "NIMO TV BROADCAST LIVE";
    } else if (targets.includes("Twitch")) {
      masterStatusTitle.textContent = "TWITCH BROADCAST LIVE";
    } else {
      masterStatusTitle.textContent = "YOUTUBE BROADCAST LIVE";
    }
  } else if (status === "RECONNECTING") {
    liveRadar.classList.remove("active");
    radarCenterIcon.textContent = "🟡";
    masterStatusTitle.className = "status-title-reconnecting";
    masterStatusTitle.textContent = "RECONNECTING BROADCAST...";
  } else if (status === "WAITING_TIKTOK") {
    liveRadar.classList.remove("active");
    radarCenterIcon.textContent = "🎵";
    masterStatusTitle.className = "status-title-reconnecting";
    masterStatusTitle.textContent = "WAITING FOR TIKTOK LIVE ROOM...";
  } else if (status === "ERROR") {
    liveRadar.classList.remove("active");
    radarCenterIcon.textContent = "⚠️";
    masterStatusTitle.className = "status-title-error";
    masterStatusTitle.textContent = "STREAM ERROR";
  } else {
    liveRadar.classList.remove("active");
    radarCenterIcon.textContent = "🔴";
    masterStatusTitle.className = "status-title-stopped";
    masterStatusTitle.textContent = "OFFLINE / STOPPED";
  }

  // Meta tags
  lblActiveSource.textContent = src.source_raw || "video.mp4";

  if (lblYtStatus) {
    if (!yt.is_enabled) {
      lblYtStatus.textContent = "Disabled";
      lblYtStatus.style.color = "#94a3b8";
    } else if (yt.is_valid) {
      lblYtStatus.textContent = (status === "LIVE" && streamer.active_targets?.includes("YouTube")) ? "Live Streaming" : "Ready / Key Set";
      lblYtStatus.style.color = "#34d399";
    } else {
      lblYtStatus.textContent = "Missing Key";
      lblYtStatus.style.color = "#f87171";
    }
  }

  if (lblKickStatus) {
    if (!kick.is_enabled) {
      lblKickStatus.textContent = "Disabled";
      lblKickStatus.style.color = "#94a3b8";
    } else if (kick.is_valid) {
      lblKickStatus.textContent = (status === "LIVE" && streamer.active_targets?.includes("Kick")) ? "Live Streaming" : "Ready / Key Set";
      lblKickStatus.style.color = "#53fc18";
    } else {
      lblKickStatus.textContent = "Missing Key";
      lblKickStatus.style.color = "#f87171";
    }
  }

  if (lblNimoStatus) {
    if (!nimo.is_enabled) {
      lblNimoStatus.textContent = "Disabled";
      lblNimoStatus.style.color = "#94a3b8";
    } else if (nimo.is_valid) {
      lblNimoStatus.textContent = (status === "LIVE" && streamer.active_targets?.includes("Nimo")) ? "Live Streaming" : "Ready / Key Set";
      lblNimoStatus.style.color = "#ff8a00";
    } else {
      lblNimoStatus.textContent = "Missing Key";
      lblNimoStatus.style.color = "#f87171";
    }
  }

  if (lblTiktokStatus) {
    if (!tiktok.is_enabled) {
      lblTiktokStatus.textContent = "Disabled";
      lblTiktokStatus.style.color = "#94a3b8";
    } else if (tiktok.automation?.active) {
      const retryIn = tiktok.automation.retry_in_seconds;
      lblTiktokStatus.textContent = retryIn == null
        ? `Creating room (${tiktok.automation.attempts || 0})`
        : `Auto retry in ${retryIn}s`;
      lblTiktokStatus.style.color = "#fbbf24";
    } else if (tiktok.is_valid) {
      lblTiktokStatus.textContent = (status === "LIVE" && streamer.active_targets?.includes("TikTok")) ? "Live Streaming" : "Ready / Key Set";
      lblTiktokStatus.style.color = "#25f4ee";
    } else {
      lblTiktokStatus.textContent = "Missing Key";
      lblTiktokStatus.style.color = "#f87171";
    }
  }

  if (lblBroadcastMode) {
    const readyList = [];
    if (yt.is_enabled && yt.is_valid) readyList.push("YT");
    if (kick.is_enabled && kick.is_valid) readyList.push("Kick");
    if (twitch.is_enabled && twitch.is_valid) readyList.push("Twitch");
    if (nimo.is_enabled && nimo.is_valid) readyList.push("Nimo");
    if (tiktok.is_enabled && tiktok.is_valid) readyList.push("TikTok");

    if (readyList.length >= 2) {
      lblBroadcastMode.textContent = `${readyList.length}-Platform (${readyList.join(" + ")})`;
      lblBroadcastMode.style.color = "#a855f7";
    } else if (readyList.length === 1) {
      lblBroadcastMode.textContent = `${readyList[0]} Only`;
      lblBroadcastMode.style.color = "#38bdf8";
    } else {
      lblBroadcastMode.textContent = "None Ready";
      lblBroadcastMode.style.color = "#94a3b8";
    }
  }

  lblWatchdogState.textContent = watchdog.watchdog_active ? "Supervising" : "Inactive";

  // 3. Stat Cards
  valStreamUptime.textContent = streamer.uptime_formatted || "00:00:00";
  valAppUptime.textContent = `Server Uptime: ${sys.app_uptime || "0s"}`;

  const fps = streamer.fps || 0;
  valFpsBitrate.textContent = `${fps} fps`;
  valBitrateSpeed.textContent = `Bitrate: ${streamer.bitrate || "0kbits/s"} | Speed: ${streamer.speed || "0x"}`;

  // Stream Health / Frame Drop Stability Indicator
  if (valStreamHealth) {
    const drops = streamer.dropped_frames || 0;
    const dups = streamer.dup_frames || 0;
    if (status === "LIVE") {
      if (drops === 0) {
        valStreamHealth.innerHTML = `<span style="color: #34d399;">🟢 100% Kararlı (Kayıp: 0 | Tekrar: ${dups})</span>`;
      } else {
        valStreamHealth.innerHTML = `<span style="color: #f59e0b;">⚠️ Frame Kaybı: ${drops} (Tekrar: ${dups})</span>`;
      }
    } else {
      valStreamHealth.innerHTML = `<span style="color: #94a3b8;">⚪ Yayın Beklemede</span>`;
    }
  }

  // Admin Auth Status badge sync
  if (data.config && typeof data.config.has_admin_password === "boolean") {
    updateAdminAuthButtonState(data.config.has_admin_password);
  }

  valReconnectCount.textContent = watchdog.reconnect_count || 0;
  if (watchdog.seconds_to_retry !== null && watchdog.seconds_to_retry > 0) {
    valRetryStatus.textContent = `Retrying in ${watchdog.seconds_to_retry}s (Step ${watchdog.current_backoff_delay}s)`;
  } else {
    valRetryStatus.textContent = watchdog.reconnect_enabled ? "Auto-recovery: Armed" : "Auto-recovery: Disabled";
  }

  const ramUsedMb = sys.memory_used_mb || 0;
  const ramTotalGb = sys.memory_total_mb ? Math.round(sys.memory_total_mb / 1024) : 16;
  valCpuRam.textContent = `CPU ${sys.cpu_percent || 0}% | RAM ${sys.memory_percent || 0}% (${ramUsedMb} MB / ${ramTotalGb} GB)`;
  const encName = streamer.active_encoder || "libx264";
  const isGpu = encName.includes("nvenc") || encName.includes("qsv") || encName.includes("videotoolbox") || encName.includes("vaapi");
  const encBadge = isGpu ? `🚀 GPU (${encName})` : `💻 CPU (${encName})`;
  valFfmpegPid.textContent = streamer.pid ? `PID: ${streamer.pid} | ${encBadge}` : `FFmpeg: Inactive | ${encBadge}`;

  // 4. Source Inspector Updates
  inspTarget.textContent = src.source_raw || "None";
  badgeSourceType.textContent = src.is_url ? "Remote URL" : "Local File";
  inspStatus.textContent = src.is_valid ? "✅ Valid & Accessible" : `❌ ${src.error_message || "Invalid"}`;
  inspStatus.style.color = src.is_valid ? "#34d399" : "#f87171";

  const meta = src.metadata || {};
  inspResolution.textContent = (meta.width && meta.height) ? `${meta.width}x${meta.height}` : "Unknown";
  inspDuration.textContent = meta.duration ? `${meta.duration}s` : "Stream/Unknown";
  inspCodecs.textContent = (meta.video_codec || meta.audio_codec) ? `V: ${meta.video_codec || '-'} / A: ${meta.audio_codec || '-'}` : "Undetected";

  // 5. Live Studio Preview & Dropped Frames Telemetry Update
  updateStudioLivePreview(data);
}

/* ==========================================================================
   STREAM ACTIONS
   ========================================================================== */
async function handleStreamAction(action) {
  try {
    const res = await authenticatedFetch(`/api/stream/${action}`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || `Stream ${action} succeeded.`, "success");
    } else {
      showToast(data.detail || `Stream ${action} failed.`, "error");
    }
  } catch (err) {
    showToast(`Network error triggering stream ${action}`, "error");
  }
}

/* ==========================================================================
   CONFIG & SETTINGS
   ========================================================================== */
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      appConfig = await res.json();
      populateConfigUI(appConfig);
    }
  } catch (e) {
    console.error("Failed to load config", e);
  }
}

function populateConfigUI(cfg) {
  if (chkYoutubeEnabled) chkYoutubeEnabled.checked = cfg.youtube_enabled !== false;
  if (inputRtmpUrl) inputRtmpUrl.value = cfg.youtube_rtmp_url || "rtmp://a.rtmp.youtube.com/live2";
  if (inputStreamKey) inputStreamKey.value = cfg.youtube_stream_key || "";

  if (chkKickEnabled) chkKickEnabled.checked = cfg.kick_enabled !== false;
  if (inputKickRtmpUrl) inputKickRtmpUrl.value = cfg.kick_rtmp_url || "rtmps://fa723fc1b171.global-contribute.live-video.net/app";
  if (inputKickStreamKey) inputKickStreamKey.value = cfg.kick_stream_key || "";

  if (chkTwitchEnabled) chkTwitchEnabled.checked = cfg.twitch_enabled !== false;
  if (inputTwitchRtmpUrl) inputTwitchRtmpUrl.value = cfg.twitch_rtmp_url || "rtmp://live.twitch.tv/app";
  if (inputTwitchStreamKey) inputTwitchStreamKey.value = cfg.twitch_stream_key || "";

  if (chkNimoEnabled) chkNimoEnabled.checked = cfg.nimo_enabled === true;
  if (inputNimoRtmpUrl) inputNimoRtmpUrl.value = cfg.nimo_rtmp_url || "rtmp://alpush.rtmp.nimo.tv/live/";
  if (inputNimoStreamKey) inputNimoStreamKey.value = cfg.nimo_stream_key || "";

  if (chkTiktokEnabled) chkTiktokEnabled.checked = cfg.tiktok_enabled !== false;
  if (inputTiktokRtmpUrl) inputTiktokRtmpUrl.value = cfg.tiktok_rtmp_url || "rtmp://live-push.tiktok.com/live/";
  if (inputTiktokStreamKey) inputTiktokStreamKey.value = cfg.tiktok_stream_key || "";
  if (inputTiktokSessionId) inputTiktokSessionId.value = cfg.tiktok_session_id || "";
  if (inputTiktokEvent) inputTiktokEvent.value = cfg.tiktok_event_id || "";
  if (inputTiktokTitle) inputTiktokTitle.value = cfg.tiktok_title || "24/7 Canlı Yayın";

  if (cfg.tiktok_room_id) {
    if (badgeActiveRoom) badgeActiveRoom.style.display = "inline-flex";
    if (lblActiveRoomId) lblActiveRoomId.textContent = cfg.tiktok_room_id;
  } else {
    if (badgeActiveRoom) badgeActiveRoom.style.display = "none";
  }
  if (btnFinishTiktokRoom) btnFinishTiktokRoom.style.display = "inline-flex";

  if (inputVideoSource) inputVideoSource.value = cfg.video_source || "video.mp4";

  const resStr = `${cfg.stream_width || 1080}x${cfg.stream_height || 1920}`;
  if (selectResolution.querySelector(`option[value="${resStr}"]`)) {
    selectResolution.value = resStr;
  }
  updateModeBadge(resStr);
  selectFps.value = String(cfg.stream_fps || 30);
  inputBitrate.value = cfg.stream_bitrate || "4500k";
  selectPreset.value = cfg.stream_preset || "veryfast";
  if (selectHwAccel) selectHwAccel.value = cfg.hw_accel || "auto";

  chkLoop.checked = cfg.video_loop !== false;
  chkAutoReconnect.checked = cfg.reconnect_enabled !== false;
  chkAutoStart.checked = cfg.auto_start === true;

  const portLbl = document.getElementById("lblPort");
  if (portLbl && cfg.port) portLbl.textContent = cfg.port;
}

function updateModeBadge(resVal) {
  const [w, h] = (resVal || "1080x1920").split("x").map(Number);
  const lblStreamMode = document.getElementById("lblStreamMode");
  const metaModeTag = document.getElementById("metaModeTag");
  if (lblStreamMode) {
    if (w < h) {
      lblStreamMode.textContent = "Shorts Live (9:16)";
      lblStreamMode.style.color = "#f472b6";
      if (metaModeTag) {
        metaModeTag.style.borderColor = "rgba(236, 72, 153, 0.4)";
        metaModeTag.style.background = "rgba(236, 72, 153, 0.15)";
      }
    } else {
      lblStreamMode.textContent = "Desktop (16:9)";
      lblStreamMode.style.color = "#60a5fa";
      if (metaModeTag) {
        metaModeTag.style.borderColor = "rgba(59, 130, 246, 0.4)";
        metaModeTag.style.background = "rgba(59, 130, 246, 0.15)";
      }
    }
  }
}

async function saveCredentials() {
  const payload = {
    youtube_enabled: chkYoutubeEnabled ? chkYoutubeEnabled.checked : true,
    youtube_rtmp_url: inputRtmpUrl ? inputRtmpUrl.value.trim() : "",
    youtube_stream_key: inputStreamKey ? inputStreamKey.value.trim() : "",
    kick_enabled: chkKickEnabled ? chkKickEnabled.checked : true,
    kick_rtmp_url: inputKickRtmpUrl ? inputKickRtmpUrl.value.trim() : "",
    kick_stream_key: inputKickStreamKey ? inputKickStreamKey.value.trim() : "",
    twitch_enabled: chkTwitchEnabled ? chkTwitchEnabled.checked : true,
    twitch_rtmp_url: inputTwitchRtmpUrl ? inputTwitchRtmpUrl.value.trim() : "",
    twitch_stream_key: inputTwitchStreamKey ? inputTwitchStreamKey.value.trim() : "",
    nimo_enabled: chkNimoEnabled ? chkNimoEnabled.checked : false,
    nimo_rtmp_url: inputNimoRtmpUrl ? inputNimoRtmpUrl.value.trim() : "",
    nimo_stream_key: inputNimoStreamKey ? inputNimoStreamKey.value.trim() : "",
    tiktok_enabled: chkTiktokEnabled ? chkTiktokEnabled.checked : true,
    tiktok_rtmp_url: inputTiktokRtmpUrl ? inputTiktokRtmpUrl.value.trim() : "",
    tiktok_stream_key: inputTiktokStreamKey ? inputTiktokStreamKey.value.trim() : "",
    tiktok_session_id: inputTiktokSessionId ? inputTiktokSessionId.value.trim() : "",
    tiktok_event_id: inputTiktokEvent ? inputTiktokEvent.value.trim() : "",
    tiktok_title: inputTiktokTitle ? inputTiktokTitle.value.trim() : "",
    video_source: inputVideoSource ? inputVideoSource.value.trim() : "",
  };

  try {
    const res = await authenticatedFetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Broadcast platforms and source saved!", "success");
      loadConfig();
    } else {
      showToast(data.detail || "Failed to save configuration", "error");
    }
  } catch (err) {
    showToast("Network error saving configuration", "error");
  }
}

/* ==========================================================================
   TIKTOK STREAM KEY GENERATOR
   ========================================================================== */
async function triggerTikTokKeyGeneration(startStream = false) {
  const sessionId = inputTiktokSessionId ? inputTiktokSessionId.value.trim() : "";
  if (!sessionId) {
    showGenStatus("Lütfen TikTok sessionid çerezinizi giriniz.", "error");
    if (inputTiktokSessionId) inputTiktokSessionId.focus();
    return;
  }

  const title = inputTiktokTitle ? inputTiktokTitle.value.trim() : "24/7 Canlı Yayın";
  const eventId = inputTiktokEvent ? inputTiktokEvent.value.trim() : "";

  // UI loading state
  setGenButtonsLoading(true, startStream);
  showGenStatus("⏳ Önce TikTok oturumu doğrulanıyor, ardından yayın odası oluşturuluyor...", "loading");

  try {
    const res = await authenticatedFetch("/api/tiktok/generate-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        event_id: eventId,
        title: title,
        auto_apply: true,
        start_stream: startStream
      })
    });

    let data;
    const rawText = await res.text();
    try {
      data = JSON.parse(rawText);
    } catch (parseErr) {
      throw new Error(rawText || `Sunucu yanıt vermedi (HTTP ${res.status})`);
    }

    if (res.ok && data.success) {
      if (data.pending) {
        showGenStatus(`⏳ ${data.message}`, "loading");
        showToast(data.message, "success");
        loadConfig();
        return;
      }

      if (inputTiktokRtmpUrl) inputTiktokRtmpUrl.value = data.rtmp_url;
      if (inputTiktokStreamKey) inputTiktokStreamKey.value = data.stream_key;
      if (badgeActiveRoom) badgeActiveRoom.style.display = "inline-flex";
      if (lblActiveRoomId) lblActiveRoomId.textContent = data.room_id || "Aktif";
      if (btnFinishTiktokRoom) btnFinishTiktokRoom.style.display = "inline-flex";

      const startMsg = data.stream_started ? " ve Canlı Yayın Başlatıldı (Kick + TikTok) 🚀" : "";
      showGenStatus(`✅ RTMP URL ve Yayın Anahtarı başarıyla alındı${startMsg}!`, "success");
      showToast(data.message || `TikTok anahtarı alındı${startMsg}`, "success");

      // Reload config to sync telemetry
      loadConfig();
    } else {
      const errMsg = data.detail || data.message || "TikTok anahtarı alınamadı.";
      showGenStatus(`❌ ${errMsg}`, "error");
      showToast(errMsg, "error");
    }
  } catch (err) {
    showGenStatus(`❌ ${err.message}`, "error");
    showToast(`TikTok: ${err.message}`, "error");
  } finally {
    setGenButtonsLoading(false, startStream);
  }
}

function setGenButtonsLoading(isLoading, forStart = false) {
  if (btnGenerateTiktokKey) {
    btnGenerateTiktokKey.disabled = isLoading;
    if (lblBtnGenKey) lblBtnGenKey.textContent = isLoading && !forStart ? "İşleniyor..." : "Otomatik Anahtar Üret & Uygula";
  }
  if (btnGenerateAndStartTiktok) {
    btnGenerateAndStartTiktok.disabled = isLoading;
    if (lblBtnGenAndStart) lblBtnGenAndStart.textContent = isLoading && forStart ? "Başlatılıyor..." : "Anahtar Al & Yayını Başlat";
  }
}

function showGenStatus(message, type) {
  const target = document.getElementById("genStatusMessage");
  if (!target) return;
  target.style.display = "block";
  target.className = `gen-status-box ${type}`;
  target.textContent = message;
}

window.showGenStatus = window.showGenStatus || showGenStatus;

async function finishTikTokRoom() {
  if (!confirm("TikTok'taki canlı yayın odasını sonlandırmak ve sıfırlamak istediğinize emin misiniz?")) {
    return;
  }

  showGenStatus("⏳ TikTok odası kapatılıyor ve sıfırlanıyor...", "loading");

  const activeRoomId = lblActiveRoomId ? lblActiveRoomId.textContent.trim() : "";
  const roomPayload = (activeRoomId && activeRoomId !== "Aktif") ? { room_id: activeRoomId } : {};

  try {
    const res = await authenticatedFetch("/api/tiktok/finish-room", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(roomPayload),
    });
    const data = await res.json();
    showToast(data.message || "TikTok odası sıfırlandı.", "success");
    showGenStatus("✅ TikTok canlı yayın odası ve anahtarları başarıyla sıfırlandı! Şimdi yeni oda açabilirsiniz.", "success");
    if (badgeActiveRoom) badgeActiveRoom.style.display = "none";
    if (lblActiveRoomId) lblActiveRoomId.textContent = "";
    if (inputTiktokStreamKey) inputTiktokStreamKey.value = "";
    await loadConfig();
  } catch (e) {
    showToast("Oda kapatılırken hata oluştu.", "error");
    showGenStatus("❌ Oda kapatılırken hata oluştu.", "error");
  }
}

async function saveStreamSettings() {
  const [w, h] = selectResolution.value.split("x").map(Number);
  const payload = {
    stream_width: w,
    stream_height: h,
    stream_fps: Number(selectFps.value),
    stream_bitrate: inputBitrate.value.trim(),
    stream_preset: selectPreset.value,
    hw_accel: selectHwAccel ? selectHwAccel.value : "auto",
    video_loop: chkLoop.checked,
    reconnect_enabled: chkAutoReconnect.checked,
    auto_start: chkAutoStart.checked,
  };

  if (inputAdminPassword && inputAdminPassword.value.trim()) {
    payload.admin_password = inputAdminPassword.value.trim();
  }

  try {
    const res = await authenticatedFetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      if (payload.admin_password) {
        setAdminPassword(payload.admin_password);
      }
      showToast("Stream encoding settings applied!", "success");
      loadConfig();
    } else {
      const errData = await res.json().catch(() => ({}));
      showToast(errData.detail || "Failed to save stream settings.", "error");
    }
  } catch (e) {
    showToast("Network error updating stream settings.", "error");
  }
}

/* ==========================================================================
   VIDEO MANAGEMENT
   ========================================================================== */
async function loadVideos() {
  try {
    const res = await fetch("/api/videos");
    if (res.ok) {
      const data = await res.json();
      renderVideoList(data.videos || []);
    }
  } catch (e) {
    console.error("Failed to load videos", e);
  }
}

function renderVideoList(videos) {
  if (videos.length === 0) {
    videoListContainer.innerHTML = '<div class="empty-state">No local videos found in videos/ directory. Click Generate asd.video or upload a file.</div>';
    return;
  }

  videoListContainer.innerHTML = videos.map(vid => `
    <div class="video-file-card ${vid.is_current ? 'is-active' : ''}">
      <div class="file-info">
        <span class="file-name">${vid.name}</span>
        <span class="file-meta">${vid.size_mb} MB &bull; ${new Date(vid.modified * 1000).toLocaleDateString()}</span>
      </div>
      <div>
        ${vid.is_current
          ? '<span class="badge-tag" style="background:rgba(16,185,129,0.2);color:#34d399;">Active Source</span>'
          : `<button class="btn btn-sm btn-outline" onclick="selectVideoSource('${vid.name}')">Select</button>`
        }
      </div>
    </div>
  `).join('');
}

window.selectVideoSource = async function(sourceName) {
  inputVideoSource.value = sourceName;
  await saveCredentials();
};

async function handleFileUpload(file) {
  const formData = new FormData();
  formData.append("file", file);

  uploadProgressBar.style.display = "block";
  uploadProgressFill.style.width = "30%";

  try {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/videos/upload", true);
    const pass = getAdminPassword();
    if (pass) {
      xhr.setRequestHeader("X-Admin-Password", pass);
    }

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        uploadProgressFill.style.width = `${percent}%`;
      }
    };

    xhr.onload = () => {
      uploadProgressBar.style.display = "none";
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        showToast(`Uploaded ${data.filename} (${data.size_mb} MB)`, "success");
        loadVideos();
        // Ask or automatically set as current source
        selectVideoSource(data.filename);
      } else {
        showToast("Upload failed: " + xhr.responseText, "error");
      }
    };

    xhr.onerror = () => {
      uploadProgressBar.style.display = "none";
      showToast("Upload error.", "error");
    };

    xhr.send(formData);
  } catch (err) {
    uploadProgressBar.style.display = "none";
    showToast("Upload exception: " + err, "error");
  }
}

async function generateSampleVideo() {
  btnGenerateSampleVideo.disabled = true;
  btnGenerateSampleVideo.innerHTML = "<span>⏳ Generating...</span>";

  try {
    const res = await authenticatedFetch("/api/videos/generate-sample", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("Test video asd.video created successfully!", "success");
      loadVideos();
      selectVideoSource("asd.video");
    } else {
      showToast(data.detail || "Failed to generate video.", "error");
    }
  } catch (e) {
    showToast("Network error generating sample video.", "error");
  } finally {
    btnGenerateSampleVideo.disabled = false;
    btnGenerateSampleVideo.innerHTML = "<span>🎨 Generate asd.video</span>";
  }
}

/* ==========================================================================
   PLAYLIST MANAGEMENT
   ========================================================================== */
async function loadPlaylist() {
  try {
    const res = await fetch("/api/playlist");
    if (res.ok) {
      const data = await res.json();
      renderPlaylist(data);
    }
  } catch (e) {}
}

function renderPlaylist(playlist) {
  const items = playlist.items || [];
  playlistCounter.textContent = `${items.length} videos`;

  if (items.length === 0) {
    playlistItemsBox.innerHTML = '<div class="empty-state">No videos in playlist. Single source mode active.</div>';
    return;
  }

  playlistItemsBox.innerHTML = items.map((item, idx) => `
    <div class="video-file-card">
      <div class="file-info">
        <span class="file-name">#${idx + 1} ${item.title || item.source}</span>
        <span class="file-meta">${item.source}</span>
      </div>
      <button class="btn btn-sm btn-outline" onclick="removePlaylistItem(${idx})">🗑️</button>
    </div>
  `).join('');
}

async function addPlaylistSource() {
  const src = inputPlaylistSource.value.trim();
  if (!src) return;

  try {
    const res = await authenticatedFetch("/api/playlist/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: src }),
    });
    if (res.ok) {
      inputPlaylistSource.value = "";
      loadPlaylist();
      showToast("Added item to playlist", "success");
    }
  } catch (e) {}
}

window.removePlaylistItem = async function(index) {
  try {
    const res = await authenticatedFetch(`/api/playlist/${index}`, { method: "DELETE" });
    if (res.ok) {
      loadPlaylist();
      showToast("Removed from playlist", "info");
    }
  } catch (e) {}
};

/* ==========================================================================
   LIVE CONSOLE & LOGS
   ========================================================================== */
async function fetchLogsRest() {
  try {
    const res = await fetch("/api/logs?limit=100");
    if (res.ok) {
      const data = await res.json();
      allLogs = data.logs || [];
      renderLogs();
    }
  } catch (e) {}
}

function appendLogEntry(entry) {
  allLogs.push(entry);
  if (allLogs.length > 500) allLogs.shift();

  // Check filter match before DOM append
  if (isLogMatchingFilter(entry)) {
    const lineEl = createLogElement(entry);
    consoleOutput.appendChild(lineEl);
    if (autoScroll) {
      consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }
  }
}

function isLogMatchingFilter(entry) {
  const levelFilter = logLevelFilter.value;
  const searchTerm = logSearchInput.value.toLowerCase().trim();

  if (levelFilter !== "ALL" && entry.level !== levelFilter) {
    return false;
  }
  if (searchTerm && !entry.message.toLowerCase().includes(searchTerm) && !entry.tag.toLowerCase().includes(searchTerm)) {
    return false;
  }
  return true;
}

function createLogElement(entry) {
  const div = document.createElement("div");
  const levelClass = entry.level.toLowerCase();
  div.className = `log-line log-${levelClass}`;

  div.innerHTML = `
    <span class="log-time">[${entry.timestamp || ''}]</span>
    <span class="log-badge badge-${levelClass}">${entry.level}</span>
    <span class="log-msg">[${entry.tag}] ${escapeHtml(entry.message)}</span>
  `;
  return div;
}

function renderLogs() {
  consoleOutput.innerHTML = "";
  const matching = allLogs.filter(isLogMatchingFilter);

  if (matching.length === 0) {
    consoleOutput.innerHTML = '<div class="empty-state">No matching log entries found.</div>';
    return;
  }

  matching.forEach(entry => {
    consoleOutput.appendChild(createLogElement(entry));
  });

  if (autoScroll) {
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
  }
}

async function clearConsoleLogs() {
  allLogs = [];
  consoleOutput.innerHTML = "";
  try {
    await authenticatedFetch("/api/logs", { method: "DELETE" });
  } catch (e) {}
}

function copyConsoleLogs() {
  const text = allLogs.map(l => `[${l.timestamp}] [${l.level}] [${l.tag}] ${l.message}`).join("\n");
  navigator.clipboard.writeText(text).then(() => {
    showToast("Logs copied to clipboard!", "info");
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ==========================================================================
   LIVE STUDIO, TELEMETRY & HASH EVASION
   ========================================================================== */
function initStudioControls() {
  // Toggles for Hash Evasion & Audio Filters
  setupStudioToggle("chkHashEvasion", "hash_evasion_enabled");
  setupStudioToggle("chkNoise", "noise_enabled");
  setupStudioToggle("chkSpatialShift", "spatial_shift_enabled");
  setupStudioToggle("chkColorOsc", "color_oscillation_enabled");
  setupStudioToggle("chkUnsharp", "unsharp_enabled");
  setupStudioToggle("chkAudioEvasion", "audio_evasion_enabled");

  // Initial fetch of overlay settings
  fetchStudioStatus();
}

function setupStudioToggle(elementId, apiKey) {
  const el = document.getElementById(elementId);
  if (!el) return;

  el.addEventListener("change", async () => {
    try {
      const payload = {};
      payload[apiKey] = el.checked;
      await authenticatedFetch("/api/overlay/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showToast(`Ayar güncellendi: ${elementId} = ${el.checked ? 'Açık' : 'Kapalı'}`, "info");
      fetchStudioStatus();
    } catch (err) {}
  });
}

async function fetchStudioStatus() {
  try {
    const res = await fetch("/api/overlay/status");
    if (res.ok) {
      const data = await res.json();
      syncStudioUI(data);
    }
  } catch (err) {}
}

function syncStudioUI(data) {
  // Sync Checkboxes
  syncChk("chkHashEvasion", data.hash_evasion_enabled);
  syncChk("chkNoise", data.noise_enabled);
  syncChk("chkSpatialShift", data.spatial_shift_enabled);
  syncChk("chkColorOsc", data.color_oscillation_enabled);
  syncChk("chkUnsharp", data.unsharp_enabled);
  syncChk("chkAudioEvasion", data.audio_evasion_enabled);
}

function syncChk(id, val) {
  const el = document.getElementById(id);
  if (el && val !== undefined) {
    el.checked = val === true;
  }
}

function updateStudioLivePreview(data) {
  const streamer = data.streamer || {};
  const status = data.status || "STOPPED";

  // 1. Uptime
  const prevValUptime = document.getElementById("prevValUptime");
  if (prevValUptime) {
    prevValUptime.textContent = streamer.uptime_formatted || "00:00:00";
  }

  // 2. Preview active source badge
  const lblPreviewSource = document.getElementById("lblPreviewSource");
  if (lblPreviewSource && data.source && data.source.source_raw) {
    lblPreviewSource.textContent = data.source.source_raw;
  }

  // 3. Studio Telemetry Metrics
  const metricStudioFps = document.getElementById("metricStudioFps");
  const metricStudioBitrate = document.getElementById("metricStudioBitrate");
  const metricStudioSpeed = document.getElementById("metricStudioSpeed");
  const metricStudioDrop = document.getElementById("metricStudioDrop");
  const metricStudioDup = document.getElementById("metricStudioDup");
  const metricStudioFrame = document.getElementById("metricStudioFrame");

  if (metricStudioFps) metricStudioFps.textContent = `${streamer.fps || 0} fps`;
  if (metricStudioBitrate) metricStudioBitrate.textContent = streamer.bitrate || "0 kb/s";
  if (metricStudioSpeed) metricStudioSpeed.textContent = streamer.speed || "0x";
  if (metricStudioDrop) {
    const drops = streamer.dropped_frames || 0;
    metricStudioDrop.textContent = drops;
    metricStudioDrop.style.color = drops === 0 ? "#34d399" : "#f59e0b";
  }
  if (metricStudioDup) metricStudioDup.textContent = streamer.dup_frames || 0;
  if (metricStudioFrame) metricStudioFrame.textContent = streamer.frame || 0;

  // 4. Studio Live Badge
  const badgeStudioLive = document.getElementById("badgeStudioLive");
  if (badgeStudioLive) {
    if (status === "LIVE") {
      badgeStudioLive.textContent = "🔴 CANLI YAYINDA";
      badgeStudioLive.style.background = "rgba(239,68,68,0.25)";
      badgeStudioLive.style.borderColor = "#ef4444";
      badgeStudioLive.style.color = "#fca5a5";
    } else {
      badgeStudioLive.textContent = "⚪ YAYIN KAPALI";
      badgeStudioLive.style.background = "rgba(148,163,184,0.15)";
      badgeStudioLive.style.borderColor = "#64748b";
      badgeStudioLive.style.color = "#94a3b8";
    }
  }
}
