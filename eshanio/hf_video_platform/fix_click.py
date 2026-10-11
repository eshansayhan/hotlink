import re

file_path = r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\frontend\index.html'
with open(file_path, 'r', encoding='utf-8') as f:
    html = f.read()

s_tag = '<script>'
start_idx = html.find(s_tag)
if start_idx == -1:
    print('Error: <script> not found')
    exit(1)

clean_js = """<script>
var allVideos = [];
var currentVideo = null;
var currentFilter = 'all';
var searchQuery = '';
var currentEpList = [];
var currentEpIdx = 0;

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
  buildFilterBar();
  buildCatWidget();
  setupClickDelegation();
  await loadVideos();
  handleRouting();
});

window.addEventListener('popstate', handleRouting);

// Global click delegation - Hicbir inline tırnak hatası olusmaz!
function setupClickDelegation() {
  document.addEventListener('click', function(e) {
    // 1. Video Kartı Tıklaması
    var card = e.target.closest('.vc');
    if (card && card.dataset && card.dataset.id) {
      e.preventDefault();
      openVideo(card.dataset.id);
      return;
    }
    // 2. Sidebar / İlgili Video Tıklaması
    var sbc = e.target.closest('.sbc');
    if (sbc && sbc.dataset && sbc.dataset.id) {
      e.preventDefault();
      openVideo(sbc.dataset.id);
      return;
    }
    // 3. Bölüm Kartı Tıklaması
    var epc = e.target.closest('.epc');
    if (epc && epc.dataset && epc.dataset.id) {
      e.preventDefault();
      openVideo(epc.dataset.id);
      return;
    }
    // 4. Kategori Pill Tıklaması
    var pill = e.target.closest('.cat-pill-btn');
    if (pill && pill.dataset && pill.dataset.cat) {
      e.preventDefault();
      showCategory(pill.dataset.cat);
      return;
    }
    // 5. Filter Chip Tıklaması
    var chip = e.target.closest('.chip');
    if (chip && chip.dataset && chip.dataset.filter) {
      e.preventDefault();
      setFilter(chip.dataset.filter);
      return;
    }
  });
}

function handleRouting() {
  var p = location.pathname;
  if (p.indexOf('/watch/') === 0 || p.indexOf('/post/') === 0) {
    var parts = p.split('/');
    var id = parts[2];
    var v = allVideos.find(function(x) { return String(x.id) === String(id); });
    if (v) { showWatch(v); return; }
  }
  if (p.indexOf('/cat/') === 0) {
    var c = decodeURIComponent(p.split('/')[2] || '');
    if (c) { showCategory(c); return; }
  }
  showPage('home');
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
  console.log('[HFStream] openVideo cagrildi, Video ID:', id);
  var vid = allVideos.find(function(v) { return String(v.id) === String(id); });
  if (!vid) {
    showToast('Video bulunamadı: ' + id);
    return;
  }
  history.pushState({}, '', '/watch/' + id);
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
  var video = document.getElementById('mainVideo');
  var vload = document.getElementById('vload');
  if (video && vload) {
    video.style.display = 'none';
    vload.style.display = 'flex';
    vload.innerHTML = '<div class="spin"></div><span class="ltxt">Video yükleniyor…</span>';
    video.src = '/video/' + encodeURIComponent(vid.id);
    video.style.display = 'block';
    video.play().catch(function(err) {
      console.log('[HFStream] Otomatik oynatma engellendi, kullanici tiklayabilir:', err);
    });
    video.addEventListener('canplay', function() { vload.style.display = 'none'; }, { once: true });
    video.addEventListener('error', function() {
      vload.innerHTML = '<div style="text-align:center"><div style="font-size:48px">⚠️</div><div>Video akışı hazırlanıyor, lütfen bekleyin...</div></div>';
    }, { once: true });
  }
  var pTitle = document.getElementById('playerTitle');
  if (pTitle) pTitle.textContent = vid.title || vid.name || '';
  var iTitle = document.getElementById('infoTitle');
  if (iTitle) iTitle.textContent = vid.title || vid.name || '';
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
    toggle.textContent = 'Daha fazla ▼';
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
  window.scrollTo({ top: 0, behavior: 'smooth' });
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
  t.textContent = d._exp ? 'Daha az ▲' : 'Daha fazla ▼';
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

new_html = html[:start_idx] + clean_js + "\n</body>\n</html>\n"

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_html)

# Extract only JS to test with node --check
only_js = clean_js.replace('<script>', '').replace('</script>', '')
with open(r'c:\Users\Eshan\Desktop\eshanio\hf_video_platform\temp_test.js', 'w', encoding='utf-8') as f:
    f.write(only_js)

print("Updated with event delegation!")
