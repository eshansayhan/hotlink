import express from 'express';
import cors from 'cors';
import http from 'http';
import https from 'https';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

const apiRateLimit = new Map();
const API_RATE_LIMIT_WINDOW_MS = 60_000;
const API_RATE_LIMIT_MAX_REQUESTS = 120;

app.use('/api', (req, res, next) => {
    const now = Date.now();
    const key = req.ip;
    let entry = apiRateLimit.get(key);

    if (!entry || now >= entry.resetAt) {
        entry = { count: 0, resetAt: now + API_RATE_LIMIT_WINDOW_MS };
        apiRateLimit.set(key, entry);
    }

    entry.count += 1;
    if (entry.count > API_RATE_LIMIT_MAX_REQUESTS) {
        res.setHeader('Retry-After', Math.ceil((entry.resetAt - now) / 1000));
        return res.status(429).json({ error: 'İstek sınırı aşıldı. Lütfen daha sonra tekrar deneyin.' });
    }

    if (apiRateLimit.size > 10_000) {
        for (const [clientIp, clientEntry] of apiRateLimit) {
            if (now >= clientEntry.resetAt) apiRateLimit.delete(clientIp);
        }
    }
    next();
});

const HUGGINGFACE_INDEX_URL = "https://huggingface.co/datasets/eshansayhan/movie/resolve/main/master_index.json";
const BASE_URL = "https://huggingface.co/datasets/eshansayhan/movie/resolve/main/";

// ═══════════════════════════════════════════════════════════
// 🌐 OTOMATİK DOMAIN ALGILAMA VE SEO YARDIMCISI
// ═══════════════════════════════════════════════════════════

/**
 * İsteğin geldiği gerçek alan adını (protokol + ana bilgisayar + port)
 * reverse proxy (Cloudflare, Nginx, HuggingFace Space, Vercel vb.) başlıklarını
 * da destekleyecek şekilde dinamik olarak algılar.
 */
export function getBaseUrl(req) {
    if (!req) return `http://localhost:${PORT}`;
    
    // 1. Ters vekil başlıkları (X-Forwarded-Proto, X-Forwarded-Host)
    const xForwardedProto = req.headers['x-forwarded-proto'];
    const xForwardedHost = req.headers['x-forwarded-host'];
    
    let proto = 'http';
    if (xForwardedProto) {
        proto = xForwardedProto.split(',')[0].trim();
    } else if (req.secure || req.connection?.encrypted) {
        proto = 'https';
    } else if (req.protocol) {
        proto = req.protocol;
    }
    
    let host = xForwardedHost 
        ? xForwardedHost.split(',')[0].trim() 
        : (req.headers['host'] || req.get('host') || `localhost:${PORT}`);
    
    return `${proto}://${host}`.replace(/\/+$/, '');
}

/**
 * URL dostu SEO slug üretir
 */
export function slugify(text) {
    if (!text) return '';
    return text.toString()
        .toLowerCase()
        .trim()
        .replace(/[\s\-_]+/g, '-')
        .replace(/[^\w\-\u00C0-\u017F]+/g, '')
        .replace(/\-\-+/g, '-')
        .replace(/^-+/, '')
        .replace(/-+$/, '');
}

/**
 * XML metinlerini temizler
 */
export function escapeXml(unsafe) {
    if (!unsafe) return '';
    return unsafe.toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

// C++ DJB2 Hash Fonksiyonu ile tam uyumlu 64-bit ID üretici
function hashString(str) {
    let hash = 5381n;
    for (let i = 0; i < str.length; i++) {
        let charCode = BigInt(str.charCodeAt(i));
        hash = BigInt.asUintN(64, (hash << 5n) + hash + charCode);
    }
    return hash.toString();
}

// ═══════════════════════════════════════════════════════════
// 🎬 VİDEO VE METAVERİ YÖNETİMİ
// ═══════════════════════════════════════════════════════════

let cachedVideosList = null;
let lastVideosFetchTime = 0;
const VIDEOS_CACHE_TTL = 15000; // 15 saniye taze önbellek

/**
 * Ham video listesini getirir (C++ Engine -> Yerel master_index.json -> HuggingFace)
 */
async function getRawVideosList(forceRefresh = false) {
    const now = Date.now();
    if (!forceRefresh && cachedVideosList && (now - lastVideosFetchTime < VIDEOS_CACHE_TTL)) {
        return cachedVideosList;
    }

    // 1. Önce yerel C++ Engine'den (port 8080) taze kataloğu dene
    try {
        const cppResp = await fetch('http://127.0.0.1:8080/api/videos', { signal: AbortSignal.timeout(1200) });
        if (cppResp.ok) {
            const cppVideos = await cppResp.json();
            if (Array.isArray(cppVideos) && cppVideos.length > 0) {
                cachedVideosList = cppVideos;
                lastVideosFetchTime = now;
                return cppVideos;
            }
        }
    } catch (_) {}

    // 2. Yerel master_index.json dosyasını kontrol et
    const localMasterPath = path.join(__dirname, '../master_index.json');
    if (fs.existsSync(localMasterPath)) {
        try {
            const raw = fs.readFileSync(localMasterPath, 'utf8');
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed.videos) && parsed.videos.length > 0) {
                cachedVideosList = parsed.videos;
                lastVideosFetchTime = now;
                return parsed.videos;
            }
        } catch (_) {}
    }

    // 3. HuggingFace Tree API & Uzak master_index.json
    try {
        const discoveredVideosMap = new Map();
        
        try {
            const treeResp = await fetch(`https://huggingface.co/api/datasets/eshansayhan/movie/tree/main?_t=${Date.now()}`, {
                headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' }
            });
            if (treeResp.ok) {
                const tree = await treeResp.json();
                if (Array.isArray(tree)) {
                    for (const item of tree) {
                        if (item.path && item.path.endsWith('.pack') && item.size > 8) {
                            const packUrl = `${BASE_URL}${item.path}`;
                            const pSize = item.size;
                            const fetchBytes = Math.min(pSize, 65536);
                            try {
                                const tailResp = await fetch(`${packUrl}?_t=${Date.now()}`, {
                                    headers: {
                                        'Range': `bytes=${pSize - fetchBytes}-${pSize - 1}`,
                                        'Cache-Control': 'no-cache'
                                    }
                                });
                                if (tailResp.ok || tailResp.status === 206) {
                                    const ab = await tailResp.arrayBuffer();
                                    const buf = Buffer.from(ab);
                                    if (buf.length >= 8) {
                                        let headerSize = Number(buf.readBigUInt64LE(buf.length - 8));
                                        let jsonBuf = null;
                                        if (headerSize > 0 && headerSize <= buf.length - 8) {
                                            jsonBuf = buf.subarray(buf.length - 8 - headerSize, buf.length - 8);
                                        } else if (headerSize > buf.length - 8 && headerSize <= 10 * 1024 * 1024) {
                                            const fullResp = await fetch(`${packUrl}?_t=${Date.now()}`, {
                                                headers: {
                                                    'Range': `bytes=${pSize - 8 - headerSize}-${pSize - 1}`,
                                                    'Cache-Control': 'no-cache'
                                                }
                                            });
                                            if (fullResp.ok || fullResp.status === 206) {
                                                const fAb = await fullResp.arrayBuffer();
                                                const fBuf = Buffer.from(fAb);
                                                jsonBuf = fBuf.subarray(0, fBuf.length - 8);
                                            }
                                        }
                                        if (jsonBuf) {
                                            const pHeader = JSON.parse(jsonBuf.toString('utf8'));
                                            if (Array.isArray(pHeader.videos)) {
                                                for (const v of pHeader.videos) {
                                                    v.pack = item.path;
                                                    v.pack_url = packUrl;
                                                    const vid = v.id || hashString(v.name);
                                                    v.id = vid;
                                                    discoveredVideosMap.set(vid, v);
                                                }
                                            }
                                        }
                                    }
                                }
                            } catch (e) {
                                console.warn(`[Node] ${item.path} gomulu baslik okuma uyarisi:`, e.message);
                            }
                        }
                    }
                }
            }
        } catch (_) {}

        // master_index.json uzak kontrol
        try {
            const noCacheUrl = `${HUGGINGFACE_INDEX_URL}?_t=${Date.now()}`;
            const response = await fetch(noCacheUrl, {
                headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache' }
            });
            if (response.ok) {
                let data = await response.text();
                const startPos = data.indexOf('{');
                if (startPos > 0) data = data.substring(startPos);
                const masterIndex = JSON.parse(data);
                if (Array.isArray(masterIndex.videos)) {
                    for (const v of masterIndex.videos) {
                        const vid = v.id || hashString(v.name);
                        v.id = vid;
                        if (discoveredVideosMap.has(vid)) {
                            const ex = discoveredVideosMap.get(vid);
                            discoveredVideosMap.set(vid, { ...ex, ...v });
                        } else {
                            discoveredVideosMap.set(vid, v);
                        }
                    }
                }
            }
        } catch (_) {}

        const list = Array.from(discoveredVideosMap.values());
        if (list.length > 0) {
            cachedVideosList = list;
            lastVideosFetchTime = now;
            return list;
        }
    } catch (_) {}

    return cachedVideosList || [];
}

/**
 * Her video nesnesini algılanan etki alanı (domain) ile zenginleştirir.
 * Bu sayede video verisi doğrudan ilgili alan adına ait canonical, stream, embed ve sitemap URL'lerini taşır.
 */
function enrichVideoWithDomain(v, domain) {
    const vid = v.id || hashString(v.name || 'video');
    const isSeries = !!(v.is_series || v.content_type === 'dizi' || v.type === 'Dizi');
    const rawTitle = v.title || v.name || 'Video';
    const cleanTitle = rawTitle.replace(/\.[^/.]+$/, "");
    const slug = v.slug || slugify(cleanTitle);

    let coverUrl = v.cover_url || v.cover || '';
    if (!coverUrl || (!coverUrl.startsWith('http://') && !coverUrl.startsWith('https://'))) {
        coverUrl = `${domain}/api/cover/${vid}`;
    }

    const yr = v.year || '2024';
    const uploadDate = v.upload_date || `${yr}-01-01T00:00:00+03:00`;
    const vSize = Number(v.size) || 0;
    const duration = Number(v.duration) || Math.max(120, Math.round(vSize > 0 ? (vSize / (250 * 1024)) : 7200)) || 7200;

    return {
        id: vid,
        name: v.name || `${vid}.mp4`,
        title: cleanTitle,
        slug: slug,
        category: v.category || 'Sinema & Film',
        genre: v.genre || 'Aksiyon, Macera, Gerilim',
        tags: v.tags || `${cleanTitle}, 1080p, stream, film izle, video`,
        director: v.director || 'HFVideo Studio',
        cast: v.cast || 'Sinema Oyuncu Kadrosu',
        year: yr,
        country: v.country || 'Türkiye',
        audio_lang: v.audio_lang || 'Türkçe Dublaj',
        imdb: v.imdb || '7.8',
        description: v.description || `${cleanTitle} (${yr}) — Hugging Face veri kümesinden video akışı.`,
        backdrops: v.backdrops || '',
        author: v.author || 'HFVideo Network',
        cover: coverUrl,
        cover_url: coverUrl,
        size: vSize,
        duration: duration,
        upload_date: uploadDate,
        pack: v.pack || 'dataset.pack',
        pack_name: v.pack_name || v.pack || 'dataset.pack',
        is_series: isSeries,
        content_type: (v.content_type || (isSeries ? 'dizi' : 'film')),
        type: (v.type || (isSeries ? 'Dizi' : 'Film')),
        series_title: v.series_title || '',
        season: v.season || 1,
        episode: v.episode || 1,
        episode_title: v.episode_title || '',
        
        // 🚀 Otomatik Domain Algılamalı İndeks Bağlantıları
        domain: domain,
        canonical_url: `${domain}/watch/${vid}`,
        watch_url: `${domain}/watch/${vid}`,
        embed_url: `${domain}/embed/${vid}`,
        stream_url: `${domain}/video/${vid}`,
        sitemap_url: `${domain}/sitemap.xml`,
        robots_url: `${domain}/robots.txt`,
        views: Number(v.views) || 0,
        likes: Number(v.likes) || 0
    };
}

/**
 * Statik sitemap.xml ve robots.txt dosyalarını günceller
 */
function updateStaticSitemapAndRobots(domain, videosList) {
    try {
        const enriched = videosList.map(v => enrichVideoWithDomain(v, domain));
        
        // 1. Sitemap XML
        let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`;
        xml += `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n`;
        xml += `        xmlns:video="http://www.google.com/schemas/sitemap-video/1.1"\n`;
        xml += `        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n`;

        xml += `  <url>\n    <loc>${domain}/</loc>\n    <changefreq>hourly</changefreq>\n    <priority>1.0</priority>\n  </url>\n`;

        const categories = [...new Set(enriched.map(v => v.category).filter(Boolean))];
        for (const cat of categories) {
            xml += `  <url>\n    <loc>${domain}/?cat=${encodeURIComponent(cat)}</loc>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>\n`;
        }

        for (const v of enriched) {
            const pubDate = v.upload_date || '2024-01-01T00:00:00+03:00';
            xml += `  <url>\n`;
            xml += `    <loc>${domain}/watch/${v.id}</loc>\n`;
            xml += `    <lastmod>${pubDate.split('T')[0]}</lastmod>\n`;
            xml += `    <changefreq>weekly</changefreq>\n`;
            xml += `    <priority>0.9</priority>\n`;
            xml += `    <video:video>\n`;
            xml += `      <video:thumbnail_loc>${escapeXml(v.cover)}</video:thumbnail_loc>\n`;
            xml += `      <video:title><![CDATA[${v.title || v.name}]]></video:title>\n`;
            xml += `      <video:description><![CDATA[${v.description || v.title}]]></video:description>\n`;
            xml += `      <video:content_loc>${domain}/video/${v.id}</video:content_loc>\n`;
            xml += `      <video:player_loc allow_embed="yes" autoplay="ap=1">${domain}/embed/${v.id}</video:player_loc>\n`;
            xml += `      <video:duration>${v.duration || 7200}</video:duration>\n`;
            xml += `      <video:publication_date>${pubDate}</video:publication_date>\n`;
            xml += `      <video:family_friendly>yes</video:family_friendly>\n`;
            if (v.tags) {
                const tagsList = v.tags.split(',').map(t => t.trim()).filter(Boolean);
                for (const t of tagsList.slice(0, 10)) {
                    xml += `      <video:tag>${escapeXml(t)}</video:tag>\n`;
                }
            }
            if (v.category) {
                xml += `      <video:category>${escapeXml(v.category)}</video:category>\n`;
            }
            xml += `      <video:uploader info="${domain}">${escapeXml(v.director || 'HFStream Video Network')}</video:uploader>\n`;
            xml += `    </video:video>\n`;
            xml += `  </url>\n`;
        }
        xml += `</urlset>\n`;

        const sitemapPath = path.join(__dirname, '../frontend/sitemap.xml');
        fs.writeFileSync(sitemapPath, xml, 'utf8');

        // 2. Robots TXT
        const robotsContent = [
            '# ========================================================',
            '# HFStream Robots.txt (Otomatik Domain & SEO Optimize)',
            '# ========================================================',
            'User-agent: *',
            'Allow: /',
            'Allow: /watch/',
            'Allow: /video/',
            'Allow: /embed/',
            'Allow: /api/videos',
            'Allow: /api/cover/',
            'Allow: /sitemap.xml',
            'Disallow: /api/status',
            '',
            `Sitemap: ${domain}/sitemap.xml`,
            ''
        ].join('\n');

        const robotsPath = path.join(__dirname, '../frontend/robots.txt');
        fs.writeFileSync(robotsPath, robotsContent, 'utf8');
    } catch (_) {}
}

// ═══════════════════════════════════════════════════════════
// 🌐 DİNAMİK SİTEMAP, ROBOTS VE META INDEX ENDPOINTLERİ
// ═══════════════════════════════════════════════════════════

// 1. Dinamik Sitemap XML (Otomatik Domain Algılama)
app.get('/sitemap.xml', async (req, res) => {
    try {
        const domain = getBaseUrl(req);
        const rawVideos = await getRawVideosList();
        const enriched = rawVideos.map(v => enrichVideoWithDomain(v, domain));

        let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`;
        xml += `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n`;
        xml += `        xmlns:video="http://www.google.com/schemas/sitemap-video/1.1"\n`;
        xml += `        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n`;

        xml += `  <url>\n    <loc>${domain}/</loc>\n    <changefreq>hourly</changefreq>\n    <priority>1.0</priority>\n  </url>\n`;

        const categories = [...new Set(enriched.map(v => v.category).filter(Boolean))];
        for (const cat of categories) {
            xml += `  <url>\n    <loc>${domain}/?cat=${encodeURIComponent(cat)}</loc>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>\n`;
        }

        for (const v of enriched) {
            const pubDate = v.upload_date || '2024-01-01T00:00:00+03:00';
            xml += `  <url>\n`;
            xml += `    <loc>${domain}/watch/${v.id}</loc>\n`;
            xml += `    <lastmod>${pubDate.split('T')[0]}</lastmod>\n`;
            xml += `    <changefreq>weekly</changefreq>\n`;
            xml += `    <priority>0.9</priority>\n`;
            xml += `    <video:video>\n`;
            xml += `      <video:thumbnail_loc>${escapeXml(v.cover)}</video:thumbnail_loc>\n`;
            xml += `      <video:title><![CDATA[${v.title || v.name}]]></video:title>\n`;
            xml += `      <video:description><![CDATA[${v.description || v.title}]]></video:description>\n`;
            xml += `      <video:content_loc>${domain}/video/${v.id}</video:content_loc>\n`;
            xml += `      <video:player_loc allow_embed="yes" autoplay="ap=1">${domain}/embed/${v.id}</video:player_loc>\n`;
            xml += `      <video:duration>${v.duration || 7200}</video:duration>\n`;
            xml += `      <video:publication_date>${pubDate}</video:publication_date>\n`;
            xml += `      <video:family_friendly>yes</video:family_friendly>\n`;
            if (v.tags) {
                const tagsList = v.tags.split(',').map(t => t.trim()).filter(Boolean);
                for (const t of tagsList.slice(0, 10)) {
                    xml += `      <video:tag>${escapeXml(t)}</video:tag>\n`;
                }
            }
            if (v.category) {
                xml += `      <video:category>${escapeXml(v.category)}</video:category>\n`;
            }
            xml += `      <video:uploader info="${domain}">${escapeXml(v.director || 'HFStream Video Network')}</video:uploader>\n`;
            xml += `    </video:video>\n`;
            xml += `  </url>\n`;
        }
        xml += `</urlset>\n`;

        res.setHeader('Content-Type', 'application/xml; charset=utf-8');
        res.setHeader('Cache-Control', 'public, max-age=600');
        res.send(xml);

        // Arka planda statik dosyayı da güncelle
        updateStaticSitemapAndRobots(domain, rawVideos);
    } catch (err) {
        res.status(500).send('Sitemap generation error: ' + err.message);
    }
});

// 2. Dinamik Robots.txt (Otomatik Algılanan Domain & Sitemap Direktifi)
app.get('/robots.txt', (req, res) => {
    const domain = getBaseUrl(req);
    const host = req.headers['host'] || req.get('host') || 'localhost:3000';
    
    const robotsTxt = [
        '# ========================================================',
        '# HFStream Robots.txt (Otomatik Domain & SEO Optimize)',
        '# ========================================================',
        'User-agent: *',
        'Allow: /',
        'Allow: /watch/',
        'Allow: /video/',
        'Allow: /embed/',
        'Allow: /api/videos',
        'Allow: /api/cover/',
        'Allow: /sitemap.xml',
        'Disallow: /api/status',
        '',
        `Host: ${host}`,
        `Sitemap: ${domain}/sitemap.xml`,
        ''
    ].join('\n');

    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Cache-Control', 'public, max-age=3600');
    res.send(robotsTxt);
});

// PWA & APK Web App Manifest & App Icon
app.get('/manifest.json', (req, res) => {
    res.setHeader('Content-Type', 'application/manifest+json; charset=utf-8');
    res.sendFile(path.join(__dirname, '../frontend/manifest.json'));
});

app.get(['/app_icon.png', '/assets/app_icon.png'], (req, res) => {
    res.setHeader('Content-Type', 'image/png');
    res.sendFile(path.join(__dirname, '../frontend/app_icon.png'));
});

// 3. Dinamik Master Index (Tüm Videolar & Otomatik Algılanan Domain Bağlantıları)
app.get(['/master_index.json', '/api/master-index'], async (req, res) => {
    try {
        const domain = getBaseUrl(req);
        const rawVideos = await getRawVideosList();
        const enriched = rawVideos.map(v => enrichVideoWithDomain(v, domain));
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        return res.json({
            platform: "HFStream Video Platform",
            domain: domain,
            generated_at: new Date().toISOString(),
            sitemap_url: `${domain}/sitemap.xml`,
            robots_url: `${domain}/robots.txt`,
            total_videos: enriched.length,
            videos: enriched
        });
    } catch (err) {
        return res.status(500).json({ error: err.message });
    }
});

// 4. API Videos: Frontend ve harici entegrasyonlar için domain zenginleştirilmiş katalog
app.get('/api/videos', async (req, res) => {
    try {
        const domain = getBaseUrl(req);
        const rawVideos = await getRawVideosList();
        const enriched = rawVideos.map(v => enrichVideoWithDomain(v, domain));
        return res.json(enriched);
    } catch (err) {
        console.warn("Katalog oluşturma hatası:", err.message);
        return res.json([]);
    }
});

// This write endpoint remains unavailable until authenticated administration exists.
app.post(['/api/videos/metadata', '/api/videos/add'], (req, res) => {
    res.status(410).json({ error: 'Bu herkese açık yazma endpoint’i devre dışı bırakıldı.' });
});

// 6. SSR / Meta Tag Injection — /watch/:id doğrudan arama motorları ve sosyal kartlar için
app.get(['/watch/:id', '/watch/:id/*'], async (req, res) => {
    try {
        const id = req.params.id;
        const domain = getBaseUrl(req);
        const rawVideos = await getRawVideosList();
        const vid = rawVideos.find(v => String(v.id) === String(id));
        
        const htmlPath = path.join(__dirname, '../frontend/index.html');
        let html = fs.readFileSync(htmlPath, 'utf8');

        if (vid) {
            const v = enrichVideoWithDomain(vid, domain);
            const safeTitle = (v.title || v.name).replace(/"/g, '&quot;');
            const safeDesc = (v.description || `${v.title} - HFStream üzerinden 1080p full HD kalitesiyle hemen izleyin.`).replace(/"/g, '&quot;');
            const coverUrl = v.cover;
            const watchUrl = v.watch_url;
            const streamUrl = v.stream_url;
            const isSeries = v.is_series;
            const pageTitle = `${safeTitle} - ${isSeries ? 'Dizi İzle' : 'Full HD Film İzle'} | HFStream`;

            const dynamicMetaTags = `
    <!-- Dinamik SEO & OpenGraph (Otomatik Domain: ${domain}) -->
    <title id="pageTitle">${pageTitle}</title>
    <meta name="description" id="pageDesc" content="${safeDesc}">
    <link rel="canonical" id="canonLink" href="${watchUrl}">
    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
    <meta property="og:site_name" content="HFStream Video Platform">
    <meta property="og:type" content="video.other">
    <meta property="og:title" content="${pageTitle}">
    <meta property="og:description" content="${safeDesc}">
    <meta property="og:image" content="${coverUrl}">
    <meta property="og:image:width" content="1280">
    <meta property="og:image:height" content="720">
    <meta property="og:url" content="${watchUrl}">
    <meta property="og:video" content="${streamUrl}">
    <meta property="og:video:type" content="video/mp4">
    <meta property="og:video:width" content="1920">
    <meta property="og:video:height" content="1080">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${pageTitle}">
    <meta name="twitter:description" content="${safeDesc}">
    <meta name="twitter:image" content="${coverUrl}">
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "${isSeries ? 'TVEpisode' : 'Movie'}",
      "name": "${safeTitle}",
      "description": "${safeDesc}",
      "image": "${coverUrl}",
      "datePublished": "${v.upload_date}",
      "uploadDate": "${v.upload_date}",
      "duration": "PT${Math.floor((v.duration||7200)/3600)}H${Math.floor(((v.duration||7200)%3600)/60)}M",
      "genre": "${v.genre || v.category || 'Sinema'}",
      "director": {
        "@type": "Person",
        "name": "${v.director || 'HFStream Network'}"
      },
      "thumbnailUrl": [ "${coverUrl}" ],
      "video": {
        "@type": "VideoObject",
        "name": "${safeTitle}",
        "description": "${safeDesc}",
        "thumbnailUrl": "${coverUrl}",
        "uploadDate": "${v.upload_date}",
        "contentUrl": "${streamUrl}",
        "embedUrl": "${v.embed_url}"
      }
    }
    </script>`;

            html = html.replace(/<title id="pageTitle">[\s\S]*?<\/title>/i, '')
                       .replace(/<meta name="description" id="pageDesc"[\s\S]*?>/i, '')
                       .replace(/<link rel="canonical" id="canonLink"[\s\S]*?>/i, '')
                       .replace('</head>', dynamicMetaTags + '\n</head>');
        }

        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        return res.send(html);
    } catch (_) {
        return res.sendFile(path.join(__dirname, '../frontend/index.html'));
    }
});

// Frontend statik dosyalarını sun
app.use(express.static(path.join(__dirname, '../frontend')));

// ═══════════════════════════════════════════════════════════
// 💬 POST SİSTEMİ (YORUMLAR & BEĞENİLER)
// ═══════════════════════════════════════════════════════════

app.get('/api/status', (req, res) => {
    const domain = getBaseUrl(req);
    res.json({
        status: 'Online',
        service: 'HFVideoPlatform API Synchronized',
        domain: domain,
        sitemap: `${domain}/sitemap.xml`,
        robots: `${domain}/robots.txt`
    });
});

app.all([
    '/api/comments/:id',
    '/api/likes/:id',
    '/api/peers',
    '/api/monetization',
    '/api/shorten',
    '/api/p2p-bandwidth',
    '/api/v2/mesh_cluster_map.json',
    '/decoy_mesh_topology.json'
], (req, res) => {
    res.status(410).json({ error: 'Bu endpoint devre dışı bırakıldı.' });
});

// ═══════════════════════════════════════════════════════════
// 🎥 VİDEO STREAM PROXY & EMBED & SPA FALLBACK
// ═══════════════════════════════════════════════════════════

app.get('/video/*', (req, res) => {
    const options = {
        hostname: '127.0.0.1',
        port: 8080,
        path: req.originalUrl,
        method: 'GET',
        headers: req.headers
    };
    const proxy = http.request(options, (targetRes) => {
        res.writeHead(targetRes.statusCode, targetRes.headers);
        targetRes.pipe(res);
    });
    proxy.on('error', () => {
        res.status(502).send('C++ Video Engine Not Reachable on port 8080');
    });
    req.pipe(proxy);
});

app.get(['/embed/*', '/embed'], (req, res) => {
    res.setHeader('X-Frame-Options', 'ALLOWALL');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.sendFile(path.join(__dirname, '../frontend/index.html'));
});

app.get(['/post/*'], (req, res) => {
    res.sendFile(path.join(__dirname, '../frontend/index.html'));
});

app.get('*', (req, res) => {
    if (req.path.startsWith('/api') || req.path.startsWith('/video')) {
        return res.status(404).json({ error: 'Endpoint bulunamadı' });
    }
    res.sendFile(path.join(__dirname, '../frontend/index.html'));
});

app.listen(PORT, () => {
    console.log(`Synchronized SEO & Dynamic Domain API Server running on port ${PORT}`);
});
