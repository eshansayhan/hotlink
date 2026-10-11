#include "StreamServer.h"
#include "httplib.h"
#include <curl/curl.h>
#include <iostream>
#include <filesystem>
#include "Downloader.h"
#include "Config.h"
#include "../embedded/embedded_frontend.h"

namespace fs = std::filesystem;

struct CurlWriteData {
    httplib::DataSink* sink;
    std::ofstream* cacheFile;
    uint64_t writtenBytes = 0;
};

static size_t curlWriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    size_t realsize = size * nmemb;
    CurlWriteData* data = (CurlWriteData*)userp;
    if (data->sink->is_writable()) {
        data->sink->write((const char*)contents, realsize);
        
        // Sifreleyerek diske yazma (XOR)
        if (data->cacheFile && data->cacheFile->is_open()) {
            std::vector<char> encrypted(realsize);
            const char* raw = (const char*)contents;
            for (size_t i = 0; i < realsize; i++) {
                encrypted[i] = raw[i] ^ 0x42; // HFVideoPlatform Ozel Sifreleme Algoritmasi
            }
            data->cacheFile->write(encrypted.data(), realsize);
            data->writtenBytes += realsize;
        }
        
        return realsize;
    }
    return 0; // abort if browser disconnected
}

StreamServer::StreamServer() : isRunning(false), svr_ptr(nullptr) {
    cleanupOldCacheFiles();
}

StreamServer::~StreamServer() {
    stop();
}

uint64_t djb2_hash(const std::string& str) {
    uint64_t hash = 5381;
    for (char c : str) {
        hash = ((hash << 5) + hash) + c; /* hash * 33 + c */
    }
    return hash;
}

std::string StreamServer::addVideo(const std::string& vName, const std::string& packUrl, uint64_t vOffset, uint64_t vSize, 
                                   const std::string& vCategory, const std::string& vImdb, const std::string& vDesc,
                                   const std::string& customId, const std::string& vTitle, const std::string& vGenre,
                                   const std::string& vTags, const std::string& vDirector, const std::string& vCast,
                                   const std::string& vYear, const std::string& vCountry, const std::string& vAudioLang,
                                   const std::string& vBackdrops, const std::string& vCover,
                                   bool isSeries, const std::string& seriesTitle, int season, int episode,
                                   const std::string& episodeTitle, const std::string& packName,
                                   uint64_t coverOffset, uint64_t coverSize, const std::string& coverMime) {
    std::string id = customId.empty() ? std::to_string(djb2_hash(vName)) : customId;
    std::lock_guard<std::mutex> lock(targetsMutex);
    std::string cat = vCategory.empty() ? (const char*)u8"Sinema & Film" : vCategory;
    std::string title = vTitle.empty() ? vName : vTitle;
    std::string audio = vAudioLang.empty() ? (const char*)u8"Türkçe Dublaj" : vAudioLang;
    
    VideoTarget vt;
    vt.packUrl      = packUrl;
    vt.packName     = packName.empty() ? "dataset.pack" : packName;
    vt.offset       = vOffset;
    vt.size         = vSize;
    vt.name         = vName;
    vt.id           = id;
    vt.title        = title;
    vt.category     = cat;
    vt.genre        = vGenre;
    vt.tags         = vTags;
    vt.director     = vDirector;
    vt.cast         = vCast;
    vt.year         = vYear;
    vt.country      = vCountry;
    vt.audioLang    = audio;
    vt.imdb         = vImdb;
    vt.description  = vDesc;
    vt.backdrops    = vBackdrops;
    vt.coverUrl     = vCover;
    vt.coverOffset  = coverOffset;
    vt.coverSize    = coverSize;
    vt.coverMime    = coverMime.empty() ? "image/jpeg" : coverMime;
    vt.isSeries     = isSeries;
    vt.seriesTitle  = seriesTitle;
    vt.season       = season > 0 ? season : 1;
    vt.episode      = episode > 0 ? episode : 1;
    vt.episodeTitle = episodeTitle;
    
    targets[id] = vt;
    return id;
}

void StreamServer::clearVideos() {
    std::lock_guard<std::mutex> lock(targetsMutex);
    targets.clear();
}

std::string StreamServer::searchVideos(const std::string& query) {
    std::string lowerQuery = query;
    std::transform(lowerQuery.begin(), lowerQuery.end(), lowerQuery.begin(), ::tolower);
    
    nlohmann::json results = nlohmann::json::array();
    
    std::lock_guard<std::mutex> lock(targetsMutex);
    for (auto const& [vid, target] : targets) {
        std::string searchable = target.name + " " + target.title + " " + target.category + " " +
                                 target.genre + " " + target.director + " " + target.cast + " " +
                                 target.tags + " " + target.year;
        std::transform(searchable.begin(), searchable.end(), searchable.begin(), ::tolower);
        
        if (searchable.find(lowerQuery) != std::string::npos) {
            nlohmann::json item;
            item["id"] = vid;
            item["name"] = target.name;
            item["title"] = target.title;
            item["category"] = target.category;
            item["director"] = target.director;
            item["cast"] = target.cast;
            item["url"] = "/watch/" + vid;
            results.push_back(item);
        }
    }
    
    return results.dump();
}

void StreamServer::start(int port) {
    if (isRunning) return;
    isRunning = true;
    serverThread = std::thread(&StreamServer::run, this, port);
}

void StreamServer::stop() {
    if (!isRunning) return;
    if (svr_ptr) {
        httplib::Server* svr = (httplib::Server*)svr_ptr;
        svr->stop();
    }
    if (serverThread.joinable()) {
        serverThread.join();
    }
    isRunning = false;
}

void StreamServer::run(int port) {
    httplib::Server svr;
    svr_ptr = &svr;
    
    // ============================================================
    // GET / — Gomulu index.html (frontend klasoru gerekmiyor!)
    // ============================================================
    auto serveHtml = [&](const httplib::Request& req, httplib::Response& res) {
        // Diskteki frontend/index.html'i dinamik oku (böylece 3000 ve 8080 her zaman birebir aynı dosyayı sunar)
        std::vector<std::string> searchPaths = {
            "../frontend/index.html",
            "frontend/index.html",
            "../../frontend/index.html",
            "../../../frontend/index.html"
        };
        for (const auto& sp : searchPaths) {
            std::ifstream f(sp, std::ios::binary);
            if (f.is_open()) {
                std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
                res.set_content(content, "text/html; charset=utf-8");
                return;
            }
        }
        // Bulunamazsa gömülü olanı sun
        res.set_content(
            reinterpret_cast<const char*>(embedded::index_html),
            embedded::index_html_len,
            "text/html; charset=utf-8"
        );
    };

    svr.Get("/", serveHtml);
    svr.Get(R"(/watch/([a-zA-Z0-9_-]+))", serveHtml);
    svr.Get(R"(/post/([a-zA-Z0-9_-]+))", serveHtml);
    svr.Get(R"(/embed/([a-zA-Z0-9_-]+))", serveHtml);

    auto serveStaticFile = [](const std::vector<std::string>& paths, const std::string& mime, httplib::Response& res) {
        for (const auto& p : paths) {
            std::ifstream f(p, std::ios::binary);
            if (f.is_open()) {
                std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
                res.set_content(content, mime.c_str());
                return true;
            }
        }
        return false;
    };

    svr.Get("/manifest.json", [=](const httplib::Request& req, httplib::Response& res) {
        serveStaticFile({
            "../frontend/manifest.json",
            "frontend/manifest.json",
            "../../frontend/manifest.json",
            "../../../frontend/manifest.json"
        }, "application/manifest+json; charset=utf-8", res);
    });

    auto serveAppIcon = [=](const httplib::Request& req, httplib::Response& res) {
        serveStaticFile({
            "../frontend/app_icon.png",
            "frontend/app_icon.png",
            "../../frontend/app_icon.png",
            "../../../frontend/app_icon.png",
            "../assets/app_icon.png"
        }, "image/png", res);
    };
    svr.Get("/app_icon.png", serveAppIcon);
    svr.Get("/assets/app_icon.png", serveAppIcon);

    // ============================================================
    // GET /api/videos — Video katalogu (Node.js ile birebir ayni JSON formati)
    // ============================================================
    svr.Get("/api/videos", [&](const httplib::Request& req, httplib::Response& res) {
        nlohmann::json result = nlohmann::json::array();
        {
            std::lock_guard<std::mutex> lock(targetsMutex);
            for (auto const& [vid, target] : targets) {
                nlohmann::json item;
                item["id"]          = vid;
                item["name"]        = target.name;
                item["title"]       = target.title.empty() ? target.name : target.title;
                item["category"]    = target.category.empty() ? (const char*)u8"Sinema & Film" : target.category;
                item["genre"]       = target.genre;
                item["tags"]        = target.tags;
                item["director"]    = target.director;
                item["cast"]        = target.cast;
                item["year"]        = target.year;
                item["country"]     = target.country;
                item["audio_lang"]  = target.audioLang.empty() ? (const char*)u8"Türkçe Dublaj" : target.audioLang;
                item["imdb"]        = target.imdb;
                item["description"] = target.description;
                item["backdrops"]   = target.backdrops;
                item["author"]      = "HFVideo Network";
                if (target.coverSize > 0) {
                    item["cover"]   = "/api/cover/" + vid;
                } else if (!target.coverUrl.empty()) {
                    item["cover"]   = target.coverUrl;
                } else {
                    item["cover"]   = "/api/cover/" + vid;
                }
                std::string yr = target.year.empty() ? "2024" : target.year;
                item["upload_date"]   = yr + "-01-01T00:00:00+03:00";
                item["duration"]      = target.size > 0 ? (target.size / (250 * 1024)) : 7200;
                item["url"]           = "/watch/" + vid;
                item["canonical_url"] = "/watch/" + vid;
                item["watch_url"]     = "/watch/" + vid;
                item["embed_url"]     = "/embed/" + vid;
                item["stream_url"]    = "/video/" + vid;
                item["sitemap_url"]   = "/sitemap.xml";
                item["size"]          = target.size;
                item["pack"]          = target.packUrl;
                item["pack_name"]     = target.packName;
                item["is_series"]     = target.isSeries;
                item["content_type"]  = target.isSeries ? "dizi" : "film";
                item["type"]          = target.isSeries ? (const char*)u8"Dizi" : (const char*)u8"Film";
                item["series_title"]  = target.seriesTitle;
                item["season"]        = target.season;
                item["episode"]       = target.episode;
                item["episode_title"] = target.episodeTitle;
                item["views"]         = 1500;
                item["likes"]         = 220;
                result.push_back(item);
            }
        }
        res.set_content(result.dump(), "application/json; charset=utf-8");
    });

    // ============================================================
    // GET /api/cover/:videoId (Gömülü .pack Kapağı veya 273x410 Poster)
    // ============================================================
    svr.Get(R"(/api/cover/([a-zA-Z0-9_\-]+))", [&](const httplib::Request& req, httplib::Response& res) {
        std::string vid = req.matches[1];
        VideoTarget target;
        bool found = false;
        {
            std::lock_guard<std::mutex> lock(targetsMutex);
            auto it = targets.find(vid);
            if (it != targets.end()) {
                target = it->second;
                found = true;
            }
        }
        if (!found) {
            res.status = 404;
            res.set_content("Video not found", "text/plain");
            return;
        }

        // 1. Gömülü .pack kapağı varsa (coverSize > 0)
        if (target.coverSize > 0) {
            std::string localPack = target.packName;
            std::error_code ec;
            if (fs::exists(localPack, ec) && fs::file_size(localPack, ec) >= target.coverOffset + target.coverSize) {
                std::ifstream f(localPack, std::ios::binary);
                if (f.is_open()) {
                    f.seekg(target.coverOffset, std::ios::beg);
                    std::vector<char> buf(target.coverSize);
                    f.read(buf.data(), target.coverSize);
                    res.set_header("Cache-Control", "public, max-age=86400");
                    res.set_content(buf.data(), target.coverSize, target.coverMime.c_str());
                    return;
                }
            }

            // Yerel yoksa uzak HTTP paketten Range ile indir
            if (target.packUrl.rfind("http://", 0) == 0 || target.packUrl.rfind("https://", 0) == 0) {
                Downloader dl;
                std::vector<uint8_t> cBuf;
                if (dl.downloadChunk(target.packUrl, target.coverOffset, target.coverOffset + target.coverSize - 1, cBuf)) {
                    res.set_header("Cache-Control", "public, max-age=86400");
                    res.set_content(reinterpret_cast<const char*>(cBuf.data()), cBuf.size(), target.coverMime.c_str());
                    return;
                }
            }
        }

        // 2. Harici URL varsa ve HTTP ise yönlendir
        if (!target.coverUrl.empty() && (target.coverUrl.rfind("http://", 0) == 0 || target.coverUrl.rfind("https://", 0) == 0)) {
            res.set_redirect(target.coverUrl.c_str());
            return;
        }

        // 3. Fallback: 273x410 Temiz Sinematik Degrade Poster Arka Planı (Yazı ve ikon içermez)
        std::ostringstream ss;
        ss << "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 273 410' width='273' height='410'>"
           << "<defs>"
           << "<linearGradient id='bgGrad' x1='0%' y1='0%' x2='100%' y2='100%'>"
           << "<stop offset='0%' stop-color='#0b0f19'/>"
           << "<stop offset='50%' stop-color='#070a12'/>"
           << "<stop offset='100%' stop-color='#020408'/>"
           << "</linearGradient>"
           << "<linearGradient id='glowGrad' x1='0%' y1='100%' x2='100%' y2='0%'>"
           << "<stop offset='0%' stop-color='#00e5b4' stop-opacity='0.20'/>"
           << "<stop offset='60%' stop-color='#3b82f6' stop-opacity='0.08'/>"
           << "<stop offset='100%' stop-color='#8b5cf6' stop-opacity='0.16'/>"
           << "</linearGradient>"
           << "<radialGradient id='spotlight' cx='50%' cy='42%' r='55%'>"
           << "<stop offset='0%' stop-color='#00e5b4' stop-opacity='0.10'/>"
           << "<stop offset='100%' stop-color='#000000' stop-opacity='0'/>"
           << "</radialGradient>"
           << "</defs>"
           << "<rect width='273' height='410' fill='url(#bgGrad)' rx='12'/>"
           << "<rect width='273' height='410' fill='url(#glowGrad)' rx='12'/>"
           << "<circle cx='136' cy='185' r='115' fill='url(#spotlight)'/>"
           << "<rect x='8' y='8' width='257' height='394' rx='8' fill='none' stroke='#ffffff' stroke-opacity='0.05' stroke-width='1'/>"
           << "</svg>";

        res.set_header("Cache-Control", "public, max-age=86400");
        res.set_content(ss.str(), "image/svg+xml; charset=utf-8");
    });

    // ============================================================
    // GET /api/status
    // ============================================================
    svr.Get("/api/status", [&](const httplib::Request& req, httplib::Response& res) {
        nlohmann::json s;
        s["status"]  = "Online";
        s["service"] = "HFVideoPlatform C++ Engine";
        s["port"]    = 8080;
        {
            std::lock_guard<std::mutex> lock(targetsMutex);
            s["videos"] = (int)targets.size();
        }
        res.set_content(s.dump(), "application/json");
    });

    // ============================================================
    // GET /api/refresh — HuggingFace'ten master_index.json taze çek
    // ============================================================
    svr.Get("/api/refresh", [&](const httplib::Request& req, httplib::Response& res) {
        if (onRefresh) {
            onRefresh();
        }
        nlohmann::json r;
        r["success"] = true;
        {
            std::lock_guard<std::mutex> lock(targetsMutex);
            r["count"] = (int)targets.size();
        }
        res.set_content(r.dump(), "application/json; charset=utf-8");
    });

    // ============================================================
    // GET /?v=ID — Video player sayfasi (eski format)
    // ============================================================
    svr.Get("/player", [&](const httplib::Request& req, httplib::Response& res) {
        if (!req.has_param("v")) {
            res.status = 400;
            res.set_content("v parametresi gerekli", "text/plain");
            return;
        }
        std::string vid = req.get_param_value("v");

        VideoTarget target;
        {
            std::lock_guard<std::mutex> lock(targetsMutex);
            if (targets.find(vid) == targets.end()) {
                res.set_content("<h1>Film Bulunamadı</h1>Film silinmiş veya geçerli değil.", "text/html; charset=utf-8");
                return;
            }
            target = targets[vid];
        }
        // Okunacak progress.json
        std::string progressPath = getAppCacheDir() + "\\progress.json";
        double startTime = 0.0;
        try {
            std::ifstream pf(progressPath);
            if (pf.is_open()) {
                nlohmann::json pj;
                pf >> pj;
                if (pj.contains(vid)) {
                    startTime = pj[vid].get<double>();
                }
            }
        } catch(...) {}

        std::string html = R"HTML(
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>)" + target.name + R"( - HF Video Player</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background-color: #000; font-family: 'Inter', sans-serif; overflow: hidden; display: flex; align-items: center; justify-content: center; height: 100vh; }
        .player-container { position: relative; width: 100%; height: 100%; background: #000; overflow: hidden; }
        video { width: 100%; height: 100%; object-fit: contain; }
        
        /* OSD (On-Screen Display) / Controls */
        .controls {
            position: absolute; bottom: 0; left: 0; right: 0;
            background: linear-gradient(transparent, rgba(0,0,0,0.9));
            padding: 30px 40px 20px; display: flex; flex-direction: column;
            transition: opacity 0.3s ease; opacity: 1; z-index: 20;
        }
        .player-container.idle .controls, .player-container.idle .top-bar { opacity: 0; cursor: none; }
        
        /* Top Bar */
        .top-bar {
            position: absolute; top: 0; left: 0; right: 0;
            background: linear-gradient(rgba(0,0,0,0.8), transparent);
            padding: 20px 40px; display: flex; align-items: center; justify-content: space-between;
            transition: opacity 0.3s ease; opacity: 1; z-index: 20;
        }
        .title { color: white; font-size: 24px; font-weight: 600; text-shadow: 0 2px 4px rgba(0,0,0,0.5); }
        .back-btn { color: white; font-size: 24px; cursor: pointer; text-decoration: none; margin-right: 20px; transition: color 0.2s; }
        .back-btn:hover { color: #e50914; }

        /* Progress Bar */
        .progress-container { width: 100%; height: 6px; background: rgba(255,255,255,0.2); border-radius: 3px; cursor: pointer; position: relative; margin-bottom: 20px; transition: height 0.1s; }
        .progress-container:hover { height: 10px; }
        .progress-bar { height: 100%; background: #e50914; border-radius: 3px; width: 0%; position: relative; }
        .progress-bar::after {
            content: ''; position: absolute; right: -6px; top: 50%; transform: translateY(-50%);
            width: 12px; height: 12px; background: white; border-radius: 50%; opacity: 0; transition: opacity 0.2s;
        }
        .progress-container:hover .progress-bar::after { opacity: 1; }
        .buffer-bar { height: 100%; background: rgba(255,255,255,0.4); border-radius: 3px; position: absolute; top: 0; left: 0; width: 0%; pointer-events: none; }
        
        /* Bottom Controls */
        .buttons { display: flex; align-items: center; justify-content: space-between; }
        .left-controls, .right-controls { display: flex; align-items: center; gap: 25px; }
        .btn { color: white; font-size: 22px; cursor: pointer; transition: transform 0.2s, color 0.2s; }
        .btn:hover { transform: scale(1.2); color: #e50914; }
        
        /* Time */
        .time-display { color: #fff; font-size: 15px; font-weight: 400; font-variant-numeric: tabular-nums; opacity: 0.9; }
        
        /* Volume */
        .volume-container { display: flex; align-items: center; gap: 10px; cursor: pointer; }
        .volume-slider { 
            width: 0; opacity: 0; transition: width 0.3s, opacity 0.3s;
            -webkit-appearance: none; background: rgba(255,255,255,0.2); height: 5px; border-radius: 2px; outline: none;
        }
        .volume-container:hover .volume-slider, .volume-slider:focus { width: 80px; opacity: 1; }
        .volume-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; background: white; border-radius: 50%; cursor: pointer; }
        
        /* Overlay Play Button */
        .overlay-play {
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            width: 80px; height: 80px; background: rgba(0,0,0,0.6); border-radius: 50%;
            display: flex; align-items: center; justify-content: center; color: white; font-size: 32px;
            cursor: pointer; transition: opacity 0.2s, transform 0.2s; opacity: 0; pointer-events: none; z-index: 10;
        }
        .overlay-play.show { opacity: 1; transform: translate(-50%, -50%) scale(1.1); }
        
        /* Loader */
        .loader {
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            border: 4px solid rgba(255,255,255,0.1); border-top-color: #e50914; border-radius: 50%;
            width: 60px; height: 60px; animation: spin 1s linear infinite; display: none; z-index: 10;
        }
        @keyframes spin { 100% { transform: translate(-50%, -50%) rotate(360deg); } }
    </style>
</head>
<body>
    <div class="player-container" id="playerContainer">
        <div class="top-bar">
            <div style="display: flex; align-items: center;">
                <i class="fas fa-arrow-left back-btn" onclick="window.close()" title="Kapat"></i>
                <div class="title">)HTML" + target.name + R"HTML(</div>
            </div>
        </div>

        <video id="vplayer" src="/video/)HTML" + vid + R"HTML(.mp4"></video>
        
        <div class="overlay-play" id="overlayPlay"><i class="fas fa-play"></i></div>
        <div class="loader" id="loader"></div>

        <div class="controls">
            <div class="progress-container" id="progressContainer">
                <div class="buffer-bar" id="bufferBar"></div>
                <div class="progress-bar" id="progressBar"></div>
            </div>
            
            <div class="buttons">
                <div class="left-controls">
                    <i class="fas fa-play btn" id="playBtn"></i>
                    <i class="fas fa-backward-step btn" id="rewindBtn" title="10s Geri"></i>
                    <i class="fas fa-forward-step btn" id="forwardBtn" title="10s İleri"></i>
                    <div class="volume-container">
                        <i class="fas fa-volume-up btn" id="muteBtn"></i>
                        <input type="range" class="volume-slider" id="volumeSlider" min="0" max="1" step="0.05" value="1">
                    </div>
                    <div class="time-display">
                        <span id="currentTime">00:00</span> / <span id="duration">00:00</span>
                    </div>
                </div>
                
                <div class="right-controls">
                    <i class="fas fa-closed-captioning btn" id="ccBtn" title="Altyazı (Yakında)"></i>
                    <i class="fas fa-expand btn" id="fullscreenBtn"></i>
                </div>
            </div>
        </div>
    </div>

    <script>
        const vp = document.getElementById('vplayer');
        const container = document.getElementById('playerContainer');
        const playBtn = document.getElementById('playBtn');
        const overlayPlay = document.getElementById('overlayPlay');
        const progressBar = document.getElementById('progressBar');
        const bufferBar = document.getElementById('bufferBar');
        const progressContainer = document.getElementById('progressContainer');
        const currentTimeEl = document.getElementById('currentTime');
        const durationEl = document.getElementById('duration');
        const muteBtn = document.getElementById('muteBtn');
        const volumeSlider = document.getElementById('volumeSlider');
        const fullscreenBtn = document.getElementById('fullscreenBtn');
        const loader = document.getElementById('loader');
        
        let isFirstPlay = true;
        let idleTimer;

        // Zaman formatı
        function formatTime(seconds) {
            let h = Math.floor(seconds / 3600);
            let m = Math.floor((seconds % 3600) / 60);
            let s = Math.floor(seconds % 60);
            if(isNaN(m) || isNaN(s)) return "00:00";
            if(h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
            return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }

        // Oynat/Duraklat
        function togglePlay() {
            if (vp.paused) {
                vp.play();
                playBtn.className = 'fas fa-pause btn';
                overlayPlay.className = 'overlay-play';
            } else {
                vp.pause();
                playBtn.className = 'fas fa-play btn';
                overlayPlay.className = 'overlay-play show';
                overlayPlay.innerHTML = '<i class="fas fa-pause"></i>';
                setTimeout(() => overlayPlay.className = 'overlay-play', 500);
            }
        }
        
        playBtn.addEventListener('click', togglePlay);
        vp.addEventListener('click', togglePlay);
        
        vp.addEventListener('play', () => playBtn.className = 'fas fa-pause btn');
        vp.addEventListener('pause', () => playBtn.className = 'fas fa-play btn');

        // İleri/Geri
        document.getElementById('rewindBtn').onclick = () => { vp.currentTime -= 10; };
        document.getElementById('forwardBtn').onclick = () => { vp.currentTime += 10; };

        // Süre ve Progress Güncelleme
        vp.addEventListener('timeupdate', () => {
            const percent = (vp.currentTime / vp.duration) * 100;
            progressBar.style.width = percent + '%';
            currentTimeEl.textContent = formatTime(vp.currentTime);
        });

        vp.addEventListener('loadedmetadata', () => {
            durationEl.textContent = formatTime(vp.duration);
        });

        // Buffer (Önbellek) Çubuğu
        vp.addEventListener('progress', () => {
            if (vp.buffered.length > 0) {
                const bufferedEnd = vp.buffered.end(vp.buffered.length - 1);
                const duration = vp.duration;
                if (duration > 0) bufferBar.style.width = (bufferedEnd / duration) * 100 + '%';
            }
        });

        // Progress Tıklama
        progressContainer.addEventListener('click', (e) => {
            const rect = progressContainer.getBoundingClientRect();
            const pos = (e.clientX - rect.left) / rect.width;
            vp.currentTime = pos * vp.duration;
        });

        // Ses Kontrolü
        volumeSlider.addEventListener('input', (e) => {
            vp.volume = e.target.value;
            vp.muted = (vp.volume == 0);
            updateVolumeIcon();
        });

        muteBtn.addEventListener('click', () => {
            vp.muted = !vp.muted;
            if(!vp.muted && vp.volume == 0) vp.volume = 0.5;
            volumeSlider.value = vp.muted ? 0 : vp.volume;
            updateVolumeIcon();
        });

        function updateVolumeIcon() {
            if (vp.muted || vp.volume == 0) muteBtn.className = 'fas fa-volume-mute btn';
            else if (vp.volume < 0.5) muteBtn.className = 'fas fa-volume-down btn';
            else muteBtn.className = 'fas fa-volume-up btn';
        }

        // Tam Ekran
        fullscreenBtn.addEventListener('click', () => {
            if (!document.fullscreenElement) {
                container.requestFullscreen().catch(err => console.log(err));
                fullscreenBtn.className = 'fas fa-compress btn';
            } else {
                document.exitFullscreen();
                fullscreenBtn.className = 'fas fa-expand btn';
            }
        });

        // Fare Hareketinde UI Göster/Gizle (Idle)
        function resetIdleTimer() {
            container.classList.remove('idle');
            clearTimeout(idleTimer);
            if (!vp.paused) {
                idleTimer = setTimeout(() => container.classList.add('idle'), 3000);
            }
        }
        container.addEventListener('mousemove', resetIdleTimer);
        vp.addEventListener('play', resetIdleTimer);
        vp.addEventListener('pause', () => { container.classList.remove('idle'); clearTimeout(idleTimer); });

        // Yükleniyor Animasyonu (Loader)
        vp.addEventListener('waiting', () => loader.style.display = 'block');
        vp.addEventListener('playing', () => loader.style.display = 'none');
        vp.addEventListener('canplay', () => loader.style.display = 'none');

        // Klavye Kısayolları
        document.addEventListener('keydown', (e) => {
            if(e.code === 'Space') { e.preventDefault(); togglePlay(); }
            if(e.code === 'ArrowRight') { vp.currentTime += 10; }
            if(e.code === 'ArrowLeft') { vp.currentTime -= 10; }
            if(e.code === 'KeyF') { fullscreenBtn.click(); }
        });

        // İlk Yükleme ve Kaldığı Yerden Devam
        vp.addEventListener('canplay', () => {
            if (isFirstPlay) {
                let startT = )HTML" + std::to_string(startTime) + R"HTML(;
                if (startT > 1.0) vp.currentTime = startT;
                vp.play();
                isFirstPlay = false;
            }
        });

        // 5 saniyede bir ilerlemeyi kaydet
        setInterval(() => {
            if(!vp.paused && vp.currentTime > 0) {
                fetch('/api/progress?v=)HTML" + vid + R"HTML(&t=' + vp.currentTime);
            }
        }, 5000);
    </script>
</body>
</html>
        )HTML";
        res.set_content(html, "text/html; charset=utf-8");
    });
    
    // YENI: İlerleme Kaydetme API'si
    svr.Get("/api/progress", [&](const httplib::Request& req, httplib::Response& res) {
        if (req.has_param("v") && req.has_param("t")) {
            std::string v = req.get_param_value("v");
            double t = std::stod(req.get_param_value("t"));
            
            std::string progressPath = getAppCacheDir() + "\\progress.json";
            nlohmann::json pj;
            try {
                std::ifstream pf(progressPath);
                if (pf.is_open()) pf >> pj;
            } catch(...) {}
            
            pj[v] = t;
            
            std::ofstream pfw(progressPath);
            if (pfw.is_open()) pfw << pj.dump();
        }
        res.set_content("ok", "text/plain");
    });
    
    // YENI: Chrome Eklentisi icin Arama API'si
    svr.Get("/api/search", [&](const httplib::Request& req, httplib::Response& res) {
        if (!req.has_param("q")) {
            res.set_content("[]", "application/json");
            return;
        }
        
        std::string query = req.get_param_value("q");
        std::transform(query.begin(), query.end(), query.begin(), ::tolower);
        
        nlohmann::json results = nlohmann::json::array();
        
        std::lock_guard<std::mutex> lock(targetsMutex);
        for (auto const& [vid, target] : targets) {
            std::string lowerName = target.name;
            std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(), ::tolower);
            
            if (lowerName.find(query) != std::string::npos) {
                nlohmann::json item;
                item["id"] = vid;
                item["name"] = target.name;
                item["url"] = "http://127.0.0.1:8080/?v=" + vid;
                results.push_back(item);
            }
        }
        
        res.set_content(results.dump(), "application/json; charset=utf-8");
    });
    
    auto videoHandler = [&](const httplib::Request& req, httplib::Response& res) {
        std::string vid;
        if (req.matches.size() > 1) {
            vid = req.matches[1].str();
        } else if (req.has_param("v")) {
            vid = req.get_param_value("v");
        } else {
            res.status = 404;
            return;
        }

        // Eğer .mp4 veya uzantı ile gelirse temizle
        if (vid.size() > 4 && vid.substr(vid.size() - 4) == ".mp4") {
            vid = vid.substr(0, vid.size() - 4);
        }

        VideoTarget target;
        bool found = false;
        {
            std::lock_guard<std::mutex> lock(targetsMutex);
            if (targets.find(vid) != targets.end()) {
                target = targets[vid];
                found = true;
            } else {
                for (auto const& [k, vt] : targets) {
                    if (vt.id == vid || vt.name == vid || std::to_string(djb2_hash(vt.name)) == vid) {
                        target = vt;
                        found = true;
                        break;
                    }
                }
            }
        }
        
        if (!found) {
            res.status = 404;
            res.set_content("Video katalogda bulunamadi", "text/plain; charset=utf-8");
            return;
        }

        res.set_header("Accept-Ranges", "bytes");
        
        std::string packUrl = target.packUrl;
        uint64_t vOffset = target.offset;
        uint64_t vSize = target.size;
        
        res.set_content_provider(
            vSize,
            "video/mp4",
            [packUrl, vOffset](size_t offset, size_t length, httplib::DataSink &sink) {
                // Akilli Sifreli (XOR) Cache Dosya Adi (vid_HASH_START_END.enc)
                size_t urlHash = std::hash<std::string>{}(packUrl);
                uint64_t startByte = vOffset + offset;
                uint64_t endByte = startByte + length - 1;
                std::string cachePath = getAppCacheDir() + "\\vid_" + std::to_string(urlHash) + "_" + std::to_string(startByte) + "_" + std::to_string(endByte) + ".enc";

                // Eger araligi kapsayan herhangi bir cache varsa, onu bul ve icinden (seek ile) oku
                uint64_t foundCacheStart = 0;
                uint64_t foundCacheEnd = 0;
                std::string bestCache = findBestCacheChunk(std::to_string(urlHash), startByte, endByte, foundCacheStart, foundCacheEnd);
                
                if (!bestCache.empty() && foundCacheEnd >= endByte) {
                    std::ifstream file(bestCache, std::ios::binary);
                    if (file.is_open()) {
                        uint64_t skipBytes = startByte - foundCacheStart;
                        if (skipBytes > 0) file.seekg(skipBytes, std::ios::beg);
                        
                        char buffer[8192];
                        uint64_t availableInCache = foundCacheEnd - startByte + 1;
                        uint64_t remaining = std::min((uint64_t)length, availableInCache);
                        
                        while (remaining > 0 && (file.read(buffer, std::min((uint64_t)sizeof(buffer), remaining)) || file.gcount() > 0)) {
                            if (!sink.is_writable()) break;
                            std::streamsize bytesRead = file.gcount();
                            for (std::streamsize i = 0; i < bytesRead; i++) {
                                buffer[i] ^= 0x42; // Decrypt
                            }
                            sink.write(buffer, bytesRead);
                            remaining -= bytesRead;
                        }
                        return true;
                    }
                }

                // Yalnizca disk kirliligini onlemek adina 512 KB'tan buyuk istekleri diske yazalim
                // HTML5 player bazen 10-20 kb'lik kucuk arama (metadata) istekleri atar.
                bool shouldCacheOnDisk = (length >= 512 * 1024);

                std::string tempCachePath = cachePath + ".tmp";
                std::ofstream cacheFile;
                if (shouldCacheOnDisk) {
                    cacheFile.open(tempCachePath, std::ios::binary);
                }

                CURL* curl = curl_easy_init();
                if (!curl) return false;
                
                curl_easy_setopt(curl, CURLOPT_URL, packUrl.c_str());
                curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
                curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
                curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);
                
                std::string rangeStr = std::to_string(startByte) + "-" + std::to_string(endByte);
                curl_easy_setopt(curl, CURLOPT_RANGE, rangeStr.c_str());
                
                CurlWriteData wd = { &sink, &cacheFile, 0 };
                curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curlWriteCallback);
                curl_easy_setopt(curl, CURLOPT_WRITEDATA, &wd);
                
                CURLcode res_curl = curl_easy_perform(curl);
                curl_easy_cleanup(curl);
                
                if (cacheFile.is_open()) {
                    cacheFile.close();
                    if (wd.writtenBytes > 0) {
                        uint64_t actualEndByte = startByte + wd.writtenBytes - 1;
                        std::string finalCachePath = getAppCacheDir() + "\\vid_" + std::to_string(urlHash) + "_" + std::to_string(startByte) + "_" + std::to_string(actualEndByte) + ".enc";
                        // Eger yeni ve buyuk bir sey indirdiysek, gereksiz eski kucuk cacheleri silelim
                        updateSmartCache(std::to_string(urlHash), startByte, actualEndByte);
                        std::filesystem::rename(tempCachePath, finalCachePath);
                        
                        // Disk sismemesi icin otomatik temizlik
                        cleanupOldCacheFiles();
                    } else {
                        std::filesystem::remove(tempCachePath);
                    }
                }
                
                return true; 
            }
        );
    };

    // Tum video isteklerini destekle: /video?v=ID, /video/ID.mp4, /video/ID
    svr.Get("/video", videoHandler);
    svr.Get(R"(/video/([a-zA-Z0-9_\-\.]+))", videoHandler);
    
    svr.listen("127.0.0.1", port);
}
