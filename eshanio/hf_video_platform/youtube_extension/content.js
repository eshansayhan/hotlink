function getSearchQuery() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('search_query');
}

// Eklentinin calisip calismadigini kesin gormek icin en tepeye banner ekle
const banner = document.createElement('div');
banner.style.position = 'fixed';
banner.style.top = '0';
banner.style.left = '0';
banner.style.width = '100%';
banner.style.background = '#00fff2';
banner.style.color = '#000';
banner.style.zIndex = '999999';
banner.style.padding = '10px';
banner.style.textAlign = 'center';
banner.style.fontWeight = 'bold';
banner.style.fontSize = '18px';
banner.innerText = '🔥 HFVideoPlatform Eklentisi Başarıyla Yüklendi! YouTube Aramasını Bekliyor... 🔥';
document.documentElement.appendChild(banner);

function injectCustomVideo(videoData) {
    // YouTube arama sonuclari kutusu (bazen birkac saniye gec yuklenebilir)
    const searchContainers = document.querySelectorAll('ytd-item-section-renderer #contents');
    let targetContainer = null;
    
    // Arama sonuclarinin oldugu ana container'i bul (reklam veya widget olmayan)
    for (let i = 0; i < searchContainers.length; i++) {
        if (searchContainers[i].querySelector('ytd-video-renderer, ytd-shelf-renderer')) {
            targetContainer = searchContainers[i];
            break;
        }
    }

    if (!targetContainer) {
        // Eger ytd-item-section-renderer bulunamazsa, direkt olarak sayfanin ortasina bas!
        targetContainer = document.querySelector('ytd-search') || document.body;
        console.log("HFVideoPlatform: Alternatif container kullaniliyor.");
    }

    // Ayni videoyu tekrar eklememek icin kontrol
    const existing = document.getElementById('hf-custom-' + videoData.id);
    if (existing) return;

    // YouTube sahte video karti (Shadow DOM / HTML)
    const cardHtml = `
    <div id="hf-custom-${videoData.id}" style="margin: 16px 0; padding: 16px; border: 2px solid #00fff2; border-radius: 12px; background: rgba(0,0,0,0.8); display: flex; align-items: center; cursor: pointer; transition: transform 0.2s;">
        <div style="flex-shrink: 0; width: 360px; height: 202px; background: #222; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 24px; color: #fff;">
            HFVideoPlatform Kapak
        </div>
        <div style="margin-left: 16px; display: flex; flex-direction: column;">
            <h3 style="color: #fff; font-size: 20px; font-family: 'Roboto', sans-serif; margin: 0 0 8px 0;">${videoData.name}</h3>
            <span style="color: #00fff2; font-size: 14px; margin-bottom: 8px;">HFVideoPlatform Ağı (Sınırsız)</span>
            <span style="color: #aaa; font-size: 13px;">Bu video HFVideoPlatform yerel sunucunuzdan geliyor. Üzerine tıklayarak doğrudan izleyebilirsiniz.</span>
        </div>
    </div>
    `;

    // En üste ekliyoruz
    const div = document.createElement('div');
    div.innerHTML = cardHtml;
    
    div.firstElementChild.addEventListener('click', () => {
        window.open(videoData.url, '_blank');
    });

    const firstItem = targetContainer.querySelector('ytd-video-renderer, ytd-shelf-renderer');
    if (firstItem) {
        firstItem.parentNode.insertBefore(div.firstElementChild, firstItem);
    } else {
        targetContainer.appendChild(div.firstElementChild);
    }
}

async function performHFSearch() {
    const query = getSearchQuery();
    if (!query) return;

    try {
        const response = await fetch(`http://127.0.0.1:8080/api/search?q=${encodeURIComponent(query)}`);
        const results = await response.json();
        
        results.forEach(video => {
            injectCustomVideo(video);
        });
    } catch (e) {
        console.log("HFVideoPlatform arama sunucusuna bağlanılamadı. Uygulamanın açık olduğundan emin olun.");
    }
}

// YouTube'un SPA (Single Page Application) yapisi yuzunden sayfa degisimlerini dinliyoruz
let lastUrl = location.href;
new MutationObserver(() => {
    const url = location.href;
    if (url !== lastUrl) {
        lastUrl = url;
        if (url.includes('/results?search_query=')) {
            setTimeout(performHFSearch, 1500); // YouTube iceriginin yuklenmesi icin
            setTimeout(performHFSearch, 3000); // Garanti olmasi icin 2. kez tetikle
        }
    }
}).observe(document, {subtree: true, childList: true});

// Ilk sayfa yuklenmesi icin
if (location.href.includes('/results?search_query=')) {
    setTimeout(performHFSearch, 1500);
    setTimeout(performHFSearch, 3000);
}
