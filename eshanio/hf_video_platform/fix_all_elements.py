# -*- coding: utf-8 -*-
with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Make sure np-context-menu and embedModal exist in HTML before </body>
extra_html = """
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

# Remove old occurrences of extra_html if any
content = content.replace(extra_html, '')

# Now replace script section with ultra-safe, hardened JS
s_idx = content.find('<script>')
if s_idx != -1:
    body_html = content[:s_idx]
else:
    body_html = content

# Ensure extra_html is right before the script
if 'id="embedModal"' not in body_html:
    body_html += extra_html

safe_js = """<script>
var allVideos = [];
var currentVideo = null;
var currentFilter = 'all';
var searchQuery = '';
var currentEpList = [];
var currentEpIdx = 0;
var isEmbedMode = false;

var CATS = [
  { id: 'Sinema & Film', icon: '🎬', desc: 'Sinema filmleri' },
  { id: 'Dizi', icon: '📺', desc: 'TV dizileri' },
  { id: 'Belgesel', icon: '🎥', desc: 'Belgesel filmler' },
  { id: 'Animasyon', icon: '🎨', desc: 'Animasyon' },
  { id: 'Aksiyon', icon: '💥', desc: 'Aksiyon' },
  { id: 'Komedi', icon: '😂', desc: 'Komedi' },
  { id: 'Korku', icon: '👻', desc: 'Korku' },
  { id: 'Romantik', icon: '❤', desc: 'Romantik' }
];

window.addEventListener('DOMContentLoaded', async function() {
  checkEmbedMode();
  buildFilterBar();
  buildCatWidget();
  setupClickDelegation();
  // 1. Videolari HER SEYDEN ONCE YUKLE
  await loadVideos();
  // 2. Sayfa yonlendirmesi
  handleRouting();
  // 3. Oynatici kontrollerini baslat
  try {
    initNovaPlayer();
  } catch(e) {
    console.warn('initNovaPlayer uyarisi:', e);
  }
});

window.addEventListener('popstate', handleRouting);

function checkEmbedMode() {
  if (location.pathname.indexOf('/embed/') === 0) {
    isEmbedMode = true;
    document.body.classList.add('embed-mode');
  }
}

// Global click delegation
function setupClickDelegation() {
  document.addEventListener('click', function(e) {
    var card = e.target.closest('.vc');
    if (card && card.dataset && card.dataset.id) {
      e.preventDefault();
      openVideo(card.dataset.id);
      return;
    }
    var sbc = e.target.closest('.sbc');
    if (sbc && sbc.dataset && sbc.dataset.id) {
      e.preventDefault();
      openVideo(sbc.dataset.id);
      return;
    }
    var epc = e.target.closest('.epc');
    if (epc && epc.dataset && epc.dataset.id) {
      e.preventDefault();
      openVideo(epc.dataset.id);
      return;
    }
    var pill = e.target.closest('.cat-pill-btn');
    if (pill && pill.dataset && pill.dataset.cat) {
      e.preventDefault();
      showCategory(pill.dataset.cat);
      return;
    }
    var chip = e.target.closest('.chip');
    if (chip && chip.dataset && chip.dataset.filter) {
      e.preventDefault();
      setFilter(chip.dataset.filter);
      return;
    }
    var speedMenu = document.getElementById('npSpeedDropdown');
    var speedBtn = document.getElementById('npSpeedBtn');
    if (speedMenu && speedMenu.classList.contains('open')) {
      if (!speedMenu.contains(e.target) && e.target !== speedBtn) {
        speedMenu.classList.remove('open');
      }
    }
    var ctxMenu = document.getElementById('npContextMenu');
    if (ctxMenu && ctxMenu.style.display === 'flex') {
      ctxMenu.style.display = 'none';
    }
  });
}

function handleRouting() {
  var p = location.pathname;
  if (p.indexOf('/watch/') === 0 || p.indexOf('/post/') === 0 || p.indexOf('/embed/') === 0) {
    var parts = p.split('/');
    var id = parts[2];
    var v = allVideos.find(function(x) { return String(x.id) === String(id); });
    if (v) { showWatch(v); return; }
  }
  if (p.indexOf('/cat/') === 0) {
    var c = decodeURIComponent(p.split('/')[2] || '');
    if (c) { showCategory(c); return; }
  }
  if (!isEmbedMode) {
    showPage('home');
    renderHomeGrid();
  }
}

function navigate(page, push) {
  if (push === undefined) push = true;
  if (page === 'home') {
    if (push) history.pushState({}, '', '/');
    showPage('home');
    renderHomeGrid();
  } else if (page === 'categories') {
    if (push) history.pushState({}, '', '/cat/all');
    showCategory('all');
  }
}

function showPage(id) {
  document.querySelectorAll('.pv').forEach(function(p) { p.classList.remove('on'); });
  var el = document.getElementById('pv-' + id);
  if (el) el.classList.add('on');
  document.querySelectorAll('.nav-a').forEach(function(a) { a.classList.remove('on'); });
  var n = document.getElementById('nav-' + id);
  if (n) n.classList.add('on');
}

async function loadVideos() {
  try {
    var r = await fetch('/api/videos');
    if (!r.ok) throw new Error(r.status);
    allVideos = await r.json();
    console.log('[HFStream] Videolar basariyla yuklendi:', allVideos.length);
  } catch (e) {
    console.warn('Video yuklenemedi:', e.message);
    allVideos = [];
  }
  renderHomeGrid();
}

function renderHomeGrid() {
  var grid = document.getElementById('videoGrid');
  if (!grid) return;
  var filtered = allVideos.slice();
  if (currentFilter !== 'all') {
    filtered = filtered.filter(function(v) {
      return (v.category === currentFilter) || (v.genre && v.genre.indexOf(currentFilter) >= 0);
    });
  }
  if (searchQuery) {
    var q = searchQuery.toLowerCase();
    filtered = filtered.filter(function(v) {
      return ((v.title || v.name || '').toLowerCase().indexOf(q) >= 0) ||
             ((v.description || '').toLowerCase().indexOf(q) >= 0);
    });
  }
  var hHeading = document.getElementById('homeHeading');
  if (hHeading) {
    hHeading.textContent = searchQuery ? ('"' + searchQuery + '" sonuclari') : (currentFilter === 'all' ? 'Tüm Videolar' : currentFilter);
  }
  var cBadge = document.getElementById('cntBadge');
  if (cBadge) {
    cBadge.textContent = filtered.length + ' video';
  }
  if (!filtered.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:60px 0;color:var(--tx3)"><div style="font-size:48px">🎬</div><div>İçerik bulunamadı</div></div>';
    return;
  }
  grid.innerHTML = filtered.map(videoCard).join('');
}

function videoCard(v) {
  var title = v.title || v.name || 'İsimsiz Video';
  var meta = [v.year, v.audio_lang].filter(Boolean).join(' · ');
  var id = String(v.id);
  var thumb = v.cover ? '<img src="' + esc(v.cover) + '" alt="' + esc(title) + '" loading="lazy" onerror="this.style.display=\\'none\\'">' : '';
  var fb = '<div class="vc-fb"' + (thumb ? ' style="display:none"' : '') + '>🎬</div>';
  var wl = v.is_series ? '<span class="vc-wl">DİZİ</span>' : '';
  return '<div class="vc" data-id="' + esc(id) + '" style="cursor:pointer">'
    + '<div class="vc-thumb">' + thumb + fb
    + '<div class="vc-play"><div class="play-c">▶</div></div>'
    + '<span class="vc-cat">' + esc(v.category || 'Film') + '</span>' + wl
    + '</div><div class="vc-body"><div class="vc-title">' + esc(title) + '</div>'
    + '<div class="vc-meta">' + esc(meta) + '</div></div></div>';
}

function openVideo(id) {
  var vid = allVideos.find(function(v) { return String(v.id) === String(id); });
  if (!vid) {
    showToast('Video bulunamadı');
    return;
  }
  var path = isEmbedMode ? ('/embed/' + id) : ('/watch/' + id);
  history.pushState({}, '', path);
  showWatch(vid);
}

function showWatch(vid) {
  currentVideo = vid;
  showPage('watch');
  document.querySelectorAll('.nav-a').forEach(function(a) { a.classList.remove('on'); });
  
  var catName = vid.category || 'Film';
  var bc = document.getElementById('breadcrumb');
  if (bc) {
    bc.innerHTML = '<a onclick="navigate(\\'home\\')">Ana Sayfa</a><span class="sep">›</span><a onclick="filterByCategory(' + JSON.stringify(catName) + ')">' + esc(catName) + '</a><span class="sep">›</span><span class="bc-cur">' + esc(vid.title || vid.name) + '</span>';
  }

  var npTitle = document.getElementById('npVideoTitle');
  if (npTitle) npTitle.textContent = vid.title || vid.name || 'HFStream';
  var pTitle = document.getElementById('playerTitle');
  if (pTitle) pTitle.textContent = vid.title || vid.name || '';
  var iTitle = document.getElementById('infoTitle');
  if (iTitle) iTitle.textContent = vid.title || vid.name || '';
  
  var video = document.getElementById('mainVideo');
  var vload = document.getElementById('vload');
  var wrap = document.getElementById('novaPlayerWrap');

  if (video && vload) {
    vload.style.display = 'flex';
    vload.innerHTML = '<div class="spin"></div><span class="ltxt">Stream Hazırlanıyor…</span>';
    
    if (vid.cover) {
      video.poster = vid.cover;
    }
    video.src = '/video/' + encodeURIComponent(vid.id);

    var hideLoader = function() {
      if (vload) vload.style.display = 'none';
    };
    video.onloadedmetadata = hideLoader;
    video.onloadeddata = hideLoader;
    video.oncanplay = hideLoader;
    video.onplaying = hideLoader;
    video.ontimeupdate = hideLoader;

    vload.onclick = function() {
      hideLoader();
      if (window.togglePlay) window.togglePlay();
    };

    setTimeout(function() {
      if (vload && vload.style.display !== 'none') {
        vload.innerHTML = '<div style="cursor:pointer;text-align:center"><div style="font-size:52px;color:var(--np-acc);margin-bottom:8px">▶</div><div style="font-size:15px;color:#fff;font-weight:700">Videoyu Başlat</div></div>';
      }
    }, 2200);

    video.play().then(function() {
      if (wrap) wrap.classList.remove('paused');
    }).catch(function(err) {
      if (wrap) wrap.classList.add('paused');
    });

    video.onerror = function() {
      vload.innerHTML = '<div style="text-align:center"><div style="font-size:48px">⚠️</div><div>Video akışı hazırlanamadı</div></div>';
    };
  }

  var desc = document.getElementById('infoDesc');
  var toggle = document.getElementById('descToggle');
  var full = vid.description || 'Açıklama bulunmuyor.';
  var short = full.length > 300 ? full.slice(0, 300) + '…' : full;
  if (desc) {
    desc.textContent = short;
    desc._full = full;
    desc._short = short;
    desc._exp = false;
  }
  if (toggle) {
    toggle.style.display = full.length > 300 ? 'block' : 'none';
    toggle.textContent = 'Daha fazla göster ▼';
  }
  var cRow = document.getElementById('catRow');
  if (cRow) {
    cRow.innerHTML = [vid.category, vid.genre, vid.audio_lang, vid.country, vid.year].filter(Boolean).map(function(p) {
      return '<span class="cpill">' + esc(p) + '</span>';
    }).join('');
  }

  var sb = document.getElementById('seriesBar');
  var ep = document.getElementById('epSec');
  if (vid.is_series) {
    var series = allVideos.filter(function(v) {
      return v.series_title === vid.series_title && v.is_series;
    }).sort(function(a, b) {
      return (a.season - b.season) || (a.episode - b.episode);
    });
    currentEpList = series;
    currentEpIdx = series.findIndex(function(v) { return v.id === vid.id; });
    if (sb) {
      document.getElementById('seriesName').textContent = vid.series_title || '';
      document.getElementById('seriesEpInfo').textContent = 'S' + vid.season + 'B' + vid.episode + (vid.episode_title ? ' - ' + vid.episode_title : '');
      document.getElementById('btnPrevEp').disabled = currentEpIdx <= 0;
      document.getElementById('btnNextEp').disabled = currentEpIdx >= series.length - 1;
      sb.style.display = 'flex';
    }
    if (ep) {
      document.getElementById('epCnt').textContent = series.length;
      document.getElementById('epScroll').innerHTML = series.map(function(e2, i) {
        return '<div class="epc ' + (i === currentEpIdx ? 'cur' : '') + '" data-id="' + esc(String(e2.id)) + '">'
          + '<div class="ep-num">B' + e2.episode + '</div><div class="ep-ttl">' + esc(e2.episode_title || e2.title || e2.name) + '</div></div>';
      }).join('');
      ep.style.display = 'block';
    }
  } else {
    if (sb) sb.style.display = 'none';
    if (ep) ep.style.display = 'none';
    currentEpList = [];
  }

  renderRelated(vid);
  if (!isEmbedMode) {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

// NovaPlayer Control Setup
var idleTimer = null;
var isTimeRemainingMode = false;
var isLoopEnabled = false;

function initNovaPlayer() {
  var video = document.getElementById('mainVideo');
  var wrap = document.getElementById('novaPlayerWrap');
  if (!video || !wrap) return;

  var playBtn = document.getElementById('npPlayBtn');
  var playSvg = document.getElementById('npPlaySvg');
  var centerIcon = document.getElementById('npCenterIcon');
  var curTimeEl = document.getElementById('npCurTime');
  var durTimeEl = document.getElementById('npDurTime');
  var playedBar = document.getElementById('npPlayedBar');
  var bufferBar = document.getElementById('npBufferBar');
  var scrubThumb = document.getElementById('npScrubThumb');
  var progressBox = document.getElementById('npProgressBox');
  var timeBubble = document.getElementById('npTimeBubble');
  var muteBtn = document.getElementById('npMuteBtn');
  var volSvg = document.getElementById('npVolSvg');
  var volSlider = document.getElementById('npVolSlider');
  var speedBtn = document.getElementById('npSpeedBtn');
  var speedDropdown = document.getElementById('npSpeedDropdown');
  var pipBtn = document.getElementById('npPipBtn');
  var theaterBtn = document.getElementById('npTheaterBtn');
  var fsBtn = document.getElementById('npFullscreenBtn');
  var fsSvg = document.getElementById('npFsSvg');
  var rewindBtn = document.getElementById('npRewindBtn');
  var forwardBtn = document.getElementById('npForwardBtn');
  var btnEmbed = document.getElementById('btnEmbedCode');
  var btnShareTop = document.getElementById('btnShareVideoTop');
  var timeDisplay = document.getElementById('npTimeDisplay');

  function formatTime(s) {
    if (isNaN(s) || s < 0) return '00:00';
    var hrs = Math.floor(s / 3600);
    var mins = Math.floor((s % 3600) / 60);
    var secs = Math.floor(s % 60);
    var p = function(n) { return (n < 10 ? '0' : '') + n; };
    if (hrs > 0) return hrs + ':' + p(mins) + ':' + p(secs);
    return p(mins) + ':' + p(secs);
  }

  window.togglePlay = function() {
    if (video.paused || video.ended) {
      video.play().then(function() {
        showCenterHud('▶');
        wrap.classList.remove('paused');
      }).catch(function(){});
    } else {
      video.pause();
      showCenterHud('❚❚');
      wrap.classList.add('paused');
    }
  };

  function updatePlayState() {
    if (!playSvg) return;
    if (video.paused) {
      playSvg.innerHTML = '<path d="M8 5v14l11-7z"/>';
      wrap.classList.add('paused');
    } else {
      playSvg.innerHTML = '<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>';
      wrap.classList.remove('paused');
    }
  }

  function showCenterHud(icon) {
    if (!centerIcon) return;
    centerIcon.textContent = icon;
    centerIcon.classList.add('active');
    setTimeout(function() { centerIcon.classList.remove('active'); }, 500);
  }

  video.addEventListener('play', updatePlayState);
  video.addEventListener('pause', updatePlayState);
  if (playBtn) playBtn.addEventListener('click', togglePlay);

  var clickTimeout = null;
  video.addEventListener('click', function(e) {
    if (clickTimeout) {
      clearTimeout(clickTimeout);
      clickTimeout = null;
      return;
    }
    clickTimeout = setTimeout(function() {
      clickTimeout = null;
      togglePlay();
    }, 250);
  });

  video.addEventListener('dblclick', function(e) {
    if (clickTimeout) { clearTimeout(clickTimeout); clickTimeout = null; }
    var rect = video.getBoundingClientRect();
    var x = e.clientX - rect.left;
    if (x < rect.width / 2) {
      skipTime(-10);
    } else {
      skipTime(10);
    }
  });

  window.skipTime = function(delta) {
    video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + delta));
    if (delta < 0) {
      var b = document.getElementById('npSkipLeft');
      if (b) {
        b.classList.add('active');
        setTimeout(function() { b.classList.remove('active'); }, 600);
      }
    } else {
      var b = document.getElementById('npSkipRight');
      if (b) {
        b.classList.add('active');
        setTimeout(function() { b.classList.remove('active'); }, 600);
      }
    }
  };

  if (rewindBtn) rewindBtn.addEventListener('click', function() { skipTime(-10); });
  if (forwardBtn) forwardBtn.addEventListener('click', function() { skipTime(10); });

  video.addEventListener('timeupdate', function() {
    var cur = video.currentTime;
    var dur = video.duration || 0;
    var pct = dur > 0 ? (cur / dur) * 100 : 0;
    if (playedBar) playedBar.style.width = pct + '%';
    if (scrubThumb) scrubThumb.style.left = pct + '%';

    if (curTimeEl) {
      if (isTimeRemainingMode && dur > 0) {
        curTimeEl.textContent = '-' + formatTime(dur - cur);
      } else {
        curTimeEl.textContent = formatTime(cur);
      }
    }
    if (durTimeEl) durTimeEl.textContent = formatTime(dur);

    if (bufferBar && video.buffered && video.buffered.length > 0) {
      for (var i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= cur && cur <= video.buffered.end(i)) {
          var bufPct = (video.buffered.end(i) / dur) * 100;
          bufferBar.style.width = bufPct + '%';
          break;
        }
      }
    }
  });

  if (timeDisplay) {
    timeDisplay.addEventListener('click', function() {
      isTimeRemainingMode = !isTimeRemainingMode;
    });
  }

  var isScrubbing = false;
  function seekTo(e) {
    if (!progressBox) return;
    var rect = progressBox.getBoundingClientRect();
    var pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (video.duration) {
      video.currentTime = pos * video.duration;
    }
  }

  if (progressBox) {
    progressBox.addEventListener('mousemove', function(e) {
      var rect = progressBox.getBoundingClientRect();
      var pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      var hoverTime = pos * (video.duration || 0);
      if (timeBubble) {
        timeBubble.textContent = formatTime(hoverTime);
        timeBubble.style.left = (pos * 100) + '%';
      }
      if (isScrubbing) seekTo(e);
    });

    progressBox.addEventListener('mousedown', function(e) {
      isScrubbing = true;
      seekTo(e);
    });
  }

  window.addEventListener('mouseup', function() { isScrubbing = false; });
  window.addEventListener('mousemove', function(e) { if (isScrubbing) seekTo(e); });

  function updateVolumeIcon(vol, muted) {
    if (!volSvg) return;
    if (muted || vol === 0) {
      volSvg.innerHTML = '<path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>';
    } else if (vol < 0.5) {
      volSvg.innerHTML = '<path d="M18.5 12c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM5 9v6h4l5 5V4L9 9H5z"/>';
    } else {
      volSvg.innerHTML = '<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>';
    }
  }

  if (volSlider) {
    volSlider.addEventListener('input', function() {
      video.volume = parseFloat(this.value);
      video.muted = video.volume === 0;
      updateVolumeIcon(video.volume, video.muted);
    });
  }

  if (muteBtn) {
    muteBtn.addEventListener('click', function() {
      video.muted = !video.muted;
      if (volSlider) volSlider.value = video.muted ? 0 : video.volume;
      updateVolumeIcon(video.volume, video.muted);
    });
  }

  wrap.addEventListener('wheel', function(e) {
    e.preventDefault();
    var delta = e.deltaY < 0 ? 0.05 : -0.05;
    video.volume = Math.max(0, Math.min(1, video.volume + delta));
    video.muted = video.volume === 0;
    if (volSlider) volSlider.value = video.volume;
    updateVolumeIcon(video.volume, video.muted);
  }, { passive: false });

  if (speedBtn && speedDropdown) {
    speedBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      speedDropdown.classList.toggle('open');
    });

    speedDropdown.querySelectorAll('.np-drop-item').forEach(function(item) {
      item.addEventListener('click', function() {
        var spd = parseFloat(this.dataset.spd);
        video.playbackRate = spd;
        speedBtn.textContent = spd === 1 ? '1x' : (spd + 'x');
        speedDropdown.querySelectorAll('.np-drop-item').forEach(function(it) { it.classList.remove('selected'); });
        this.classList.add('selected');
        speedDropdown.classList.remove('open');
        showToast('Oynatma Hızı: ' + spd + 'x');
      });
    });
  }

  if (pipBtn) {
    pipBtn.addEventListener('click', async function() {
      try {
        if (document.pictureInPictureElement) {
          await document.exitPictureInPicture();
        } else {
          await video.requestPictureInPicture();
        }
      } catch (err) {
        showToast('PiP desteklenmiyor');
      }
    });
  }

  if (theaterBtn) {
    theaterBtn.addEventListener('click', function() {
      wrap.classList.toggle('theater-mode');
      var isTh = wrap.classList.contains('theater-mode');
      showToast(isTh ? 'Sinema Modu Açık' : 'Normal Mod');
    });
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      if (wrap.requestFullscreen) wrap.requestFullscreen();
      else if (wrap.webkitRequestFullscreen) wrap.webkitRequestFullscreen();
      else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
      if (fsSvg) fsSvg.innerHTML = '<path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-14v3h3v2h-5V5h2z"/>';
    } else {
      if (document.exitFullscreen) document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      if (fsSvg) fsSvg.innerHTML = '<path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>';
    }
  }
  if (fsBtn) fsBtn.addEventListener('click', toggleFullscreen);

  function resetIdle() {
    wrap.classList.remove('idle');
    clearTimeout(idleTimer);
    if (!video.paused) {
      idleTimer = setTimeout(function() {
        wrap.classList.add('idle');
      }, 3500);
    }
  }
  wrap.addEventListener('mousemove', resetIdle);
  wrap.addEventListener('mouseenter', resetIdle);
  video.addEventListener('play', resetIdle);

  if (btnEmbed) {
    btnEmbed.addEventListener('click', function(e) {
      e.stopPropagation();
      openEmbedModal();
    });
  }
  if (btnShareTop) {
    btnShareTop.addEventListener('click', function(e) {
      e.stopPropagation();
      if (currentVideo) openShare(currentVideo.id);
    });
  }

  // Safe Context Menu bindings
  var ctxMenu = document.getElementById('npContextMenu');
  wrap.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    if (!ctxMenu) return;
    ctxMenu.style.display = 'flex';
    ctxMenu.style.left = e.clientX + 'px';
    ctxMenu.style.top = e.clientY + 'px';
  });

  var elCtxUrl = document.getElementById('ctxCopyUrl');
  if (elCtxUrl) {
    elCtxUrl.addEventListener('click', function() {
      if (!currentVideo) return;
      var t = Math.floor(video.currentTime);
      var u = location.origin + '/watch/' + currentVideo.id + '?t=' + t;
      navigator.clipboard.writeText(u).then(function() {
        showToast('Zaman damgalı video linki kopyalandı! (' + formatTime(t) + ')');
      });
    });
  }

  var elCtxEmbed = document.getElementById('ctxCopyEmbed');
  if (elCtxEmbed) {
    elCtxEmbed.addEventListener('click', function() {
      openEmbedModal();
    });
  }

  var elCtxLoop = document.getElementById('ctxToggleLoop');
  if (elCtxLoop) {
    elCtxLoop.addEventListener('click', function() {
      isLoopEnabled = !isLoopEnabled;
      video.loop = isLoopEnabled;
      this.textContent = isLoopEnabled ? '🔁 Döngü (Loop: Açık)' : '🔁 Döngü (Loop: Kapalı)';
      showToast(isLoopEnabled ? 'Döngü Modu Açık' : 'Döngü Modu Kapalı');
    });
  }

  var elCtxPip = document.getElementById('ctxPip');
  if (elCtxPip) {
    elCtxPip.addEventListener('click', function() {
      if (pipBtn) pipBtn.click();
    });
  }

  window.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    var key = e.key.toLowerCase();
    if (e.code === 'Space' || key === 'k') {
      e.preventDefault();
      togglePlay();
    } else if (e.code === 'ArrowRight' || key === 'l') {
      e.preventDefault();
      skipTime(10);
    } else if (e.code === 'ArrowLeft' || key === 'j') {
      e.preventDefault();
      skipTime(-10);
    } else if (e.code === 'ArrowUp') {
      e.preventDefault();
      video.volume = Math.min(1, video.volume + 0.1);
      if (volSlider) volSlider.value = video.volume;
      updateVolumeIcon(video.volume, video.muted);
      showToast('Ses: %' + Math.round(video.volume * 100));
    } else if (e.code === 'ArrowDown') {
      e.preventDefault();
      video.volume = Math.max(0, video.volume - 0.1);
      if (volSlider) volSlider.value = video.volume;
      updateVolumeIcon(video.volume, video.muted);
      showToast('Ses: %' + Math.round(video.volume * 100));
    } else if (key === 'm') {
      e.preventDefault();
      if (muteBtn) muteBtn.click();
    } else if (key === 'f') {
      e.preventDefault();
      toggleFullscreen();
    } else if (key === 't') {
      e.preventDefault();
      if (theaterBtn) theaterBtn.click();
    } else if (key === 'p') {
      e.preventDefault();
      if (pipBtn) pipBtn.click();
    } else if (key === 'c') {
      e.preventDefault();
      openEmbedModal();
    }
  });
}

function openEmbedModal() {
  if (!currentVideo) {
    showToast('Video seçilmedi');
    return;
  }
  var vidId = currentVideo.id;
  var embedUrl = location.origin + '/embed/' + vidId;
  var iframeCode = '<iframe src="' + embedUrl + '" width="100%" height="450" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen style="border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,0.5)"></iframe>';
  
  var box = document.getElementById('embedCodeText');
  if (box) box.value = iframeCode;
  
  var modal = document.getElementById('embedModal');
  if (modal) modal.classList.add('open');
}

function closeEmbedModal() {
  var modal = document.getElementById('embedModal');
  if (modal) modal.classList.remove('open');
}

function copyEmbedCode() {
  var box = document.getElementById('embedCodeText');
  if (!box) return;
  box.select();
  navigator.clipboard.writeText(box.value).then(function() {
    showToast('Embed kodu kopyalandı! İstediğin siteye yapıştırabilirsin.');
    closeEmbedModal();
  }).catch(function() {
    showToast('Kopyalanamadı');
  });
}

function changeEpisode(dir) {
  var i = currentEpIdx + dir;
  if (i < 0 || i >= currentEpList.length) return;
  openVideo(currentEpList[i].id);
}

function toggleDesc() {
  var d = document.getElementById('infoDesc');
  var t = document.getElementById('descToggle');
  if (!d || !t) return;
  d._exp = !d._exp;
  d.textContent = d._exp ? d._full : d._short;
  t.textContent = d._exp ? 'Daha az ▲' : 'Daha fazla göster ▼';
}

function renderRelated(vid) {
  var list = document.getElementById('relatedList');
  if (!list) return;
  var rel = allVideos.filter(function(v) {
    return v.id !== vid.id && (v.category === vid.category || v.genre === vid.genre);
  }).slice(0, 10);
  if (!rel.length) {
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--tx3)">İlgili içerik yok</div>';
    return;
  }
  list.innerHTML = rel.map(function(v) {
    var rid = String(v.id);
    var th = v.cover ? '<img class="sb-img" src="' + esc(v.cover) + '" loading="lazy" onerror="this.style.display=\\'none\\'">' : '<div class="sb-ifb">🎬</div>';
    return '<div class="sbc" data-id="' + esc(rid) + '" style="cursor:pointer">' + th + '<div class="sb-inf"><div class="sb-t">' + esc(v.title || v.name) + '</div><div class="sb-c">' + esc(v.category || '') + (v.year ? ' · ' + v.year : '') + '</div></div></div>';
  }).join('');
}

function showCategory(catId) {
  showPage('cat');
  var cat = CATS.find(function(c) { return c.id === catId; });
  var cTitle = document.getElementById('catTitle');
  if (cTitle) cTitle.textContent = catId === 'all' ? 'Tüm Kategoriler' : (cat ? cat.id : catId);
  var cDesc = document.getElementById('catDesc');
  if (cDesc) cDesc.textContent = cat ? cat.desc : 'Bu kategorideki içerikler';
  var cIcon = document.getElementById('catIcon');
  if (cIcon) cIcon.textContent = cat ? cat.icon : '🎬';
  var cPills = document.getElementById('catPills');
  if (cPills) {
    cPills.innerHTML = [{ id: 'all', icon: '🌐' }].concat(CATS).map(function(c) {
      return '<button class="cat-pill-btn ' + (c.id === catId ? 'on' : '') + '" data-cat="' + esc(c.id) + '">' + c.icon + ' ' + (c.id === 'all' ? 'Tümü' : c.id) + '</button>';
    }).join('');
  }
  var vids = catId === 'all' ? allVideos : allVideos.filter(function(v) {
    return v.category === catId || (v.genre && v.genre.indexOf(catId) >= 0);
  });
  var cGrid = document.getElementById('catGrid');
  if (cGrid) {
    cGrid.innerHTML = vids.length ? vids.map(videoCard).join('') : '<div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--tx3)">Bu kategoride içerik yok</div>';
  }
  history.pushState({}, '', '/cat/' + encodeURIComponent(catId));
}

function filterByCategory(cat) {
  currentFilter = cat || 'all';
  document.querySelectorAll('.chip').forEach(function(c) {
    c.classList.toggle('on', (c.dataset.filter || 'all') === currentFilter);
  });
  var homeEl = document.getElementById('pv-home');
  if (homeEl && homeEl.classList.contains('on')) {
    renderHomeGrid();
  } else {
    navigate('home');
    setTimeout(renderHomeGrid, 50);
  }
}

function buildFilterBar() {
  var bar = document.getElementById('filterBar');
  if (!bar) return;
  bar.innerHTML = [{ label: 'Tümü', val: 'all' }].concat(CATS.map(function(c) {
    return { label: c.icon + ' ' + c.id, val: c.id };
  })).map(function(f) {
    return '<button class="chip ' + (f.val === 'all' ? 'on' : '') + '" data-filter="' + esc(f.val) + '">' + f.label + '</button>';
  }).join('');
}

function setFilter(val) {
  currentFilter = val;
  document.querySelectorAll('.chip').forEach(function(c) {
    c.classList.toggle('on', c.dataset.filter === val);
  });
  renderHomeGrid();
}

function buildCatWidget() {
  var list = document.getElementById('catWidgetList');
  if (!list) return;
  list.innerHTML = CATS.map(function(c) {
    return '<li><a onclick="filterByCategory(' + JSON.stringify(c.id) + ')" style="cursor:pointer">' + c.icon + ' ' + c.id + '</a></li>';
  }).join('');
}

var stimer = null;
function onSearch(val) {
  searchQuery = val.trim();
  var sClear = document.getElementById('searchClear');
  var sIcon = document.getElementById('searchIcon');
  if (sClear) sClear.style.display = val ? 'block' : 'none';
  if (sIcon) sIcon.style.display = val ? 'none' : 'block';
  clearTimeout(stimer);
  stimer = setTimeout(function() {
    var homeEl = document.getElementById('pv-home');
    if (!homeEl || !homeEl.classList.contains('on')) navigate('home', false);
    renderHomeGrid();
  }, 280);
}

function clearSearch() {
  var sInput = document.getElementById('searchInput');
  if (sInput) sInput.value = '';
  searchQuery = '';
  var sClear = document.getElementById('searchClear');
  var sIcon = document.getElementById('searchIcon');
  if (sClear) sClear.style.display = 'none';
  if (sIcon) sIcon.style.display = 'block';
  renderHomeGrid();
}

function openShare(id) {
  var shareUrl = document.getElementById('shareUrl');
  if (shareUrl) shareUrl.value = location.origin + '/watch/' + id;
  var sm = document.getElementById('shareModal');
  if (sm) sm.classList.add('open');
}

function closeModal() {
  var sm = document.getElementById('shareModal');
  if (sm) sm.classList.remove('open');
}

function copyUrl() {
  var shareUrl = document.getElementById('shareUrl');
  if (!shareUrl) return;
  navigator.clipboard.writeText(shareUrl.value).then(function() {
    showToast('Link kopyalandı!');
  }).catch(function() {
    showToast('Kopyalanamadı');
  });
}

function shareOn(pl) {
  var shareUrl = document.getElementById('shareUrl');
  if (!shareUrl) return;
  var u = encodeURIComponent(shareUrl.value);
  var l = {
    twitter: 'https://twitter.com/intent/tweet?url=' + u,
    whatsapp: 'https://wa.me/?text=' + u,
    telegram: 'https://t.me/share/url?url=' + u
  };
  if (l[pl]) window.open(l[pl], '_blank');
}

var smodal = document.getElementById('shareModal');
if (smodal) {
  smodal.addEventListener('click', function(e) {
    if (e.target === e.currentTarget) closeModal();
  });
}

function showToast(msg, dur) {
  dur = dur || 3000;
  var w = document.getElementById('toastWrap');
  if (!w) return;
  var t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  w.appendChild(t);
  setTimeout(function() {
    t.style.opacity = '0';
    t.style.transform = 'translateY(20px)';
    t.style.transition = '.3s';
    setTimeout(function() { t.remove(); }, 300);
  }, dur);
}

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
</script>"""

final_html = body_html + safe_js + "\n</body>\n</html>\n"

with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html', 'w', encoding='utf-8') as f:
    f.write(final_html)

# Extract only JS to test with node --check
only_js = safe_js.replace('<script>', '').replace('</script>', '')
with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\temp_test.js', 'w', encoding='utf-8') as f:
    f.write(only_js)

print("HTML, Modals, and Safe JS completely synced.")
