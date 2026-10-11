#include "imgui.h"
#include "imgui_impl_glfw.h"
#include "imgui_impl_opengl3.h"
#include <GLFW/glfw3.h>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <windows.h>
#include <commdlg.h>
#include <random>
#include <algorithm>
#include <sstream>
#include <system_error>
#include "Downloader.h"

using json = nlohmann::json;
namespace fs = std::filesystem;

// ═══════════════════════════════════════════════════════════
//  GÜVENLİ YARDIMCI FONKSİYONLAR & DOSYA İŞLEMLERİ
// ═══════════════════════════════════════════════════════════

// Tırnak işaretlerini (" ") ve baştaki/sondaki boşlukları temizler
std::string cleanPath(const std::string& raw) {
    std::string s = raw;
    while (!s.empty() && (s.front() == ' ' || s.front() == '\t' || s.front() == '\r' || s.front() == '\n' || s.front() == '"' || s.front() == '\'')) {
        s.erase(s.begin());
    }
    while (!s.empty() && (s.back() == ' ' || s.back() == '\t' || s.back() == '\r' || s.back() == '\n' || s.back() == '"' || s.back() == '\'')) {
        s.pop_back();
    }
    return s;
}

// Bir dizgenin HTTP/HTTPS URL olup olmadığını kontrol eder
bool isHttpUrl(const std::string& str) {
    return str.rfind("http://", 0) == 0 || str.rfind("https://", 0) == 0;
}

// Dosya varlığını çökme olmadan (error_code ile) kontrol eder
bool fileExists(const std::string& path) {
    if (path.empty() || isHttpUrl(path)) return false;
    std::error_code ec;
    return fs::exists(path, ec) && !fs::is_directory(path, ec);
}

// Dosya boyutunu çökme olmadan (error_code ile) döndürür
uint64_t getFileSize(const std::string& filename) {
    if (filename.empty() || isHttpUrl(filename)) return 0;
    std::error_code ec;
    if (!fs::exists(filename, ec)) return 0;
    auto sz = fs::file_size(filename, ec);
    return ec ? 0 : (uint64_t)sz;
}

// JSON'dan güvenli bir şekilde string okur (sayı, bool veya eksik olsa bile çökmez)
std::string getJsonString(const json& j, const std::string& key, const std::string& defVal = "") {
    if (!j.is_object() || !j.contains(key) || j[key].is_null()) return defVal;
    const auto& val = j[key];
    if (val.is_string()) return val.get<std::string>();
    if (val.is_number_integer()) return std::to_string(val.get<int64_t>());
    if (val.is_number_unsigned()) return std::to_string(val.get<uint64_t>());
    if (val.is_number_float()) {
        std::ostringstream ss;
        ss << val.get<double>();
        return ss.str();
    }
    if (val.is_boolean()) return val.get<bool>() ? "true" : "false";
    return defVal;
}

// JSON'dan güvenli bir şekilde uint64 okur
uint64_t getJsonUint64(const json& j, const std::string& key, uint64_t defVal = 0) {
    if (!j.is_object() || !j.contains(key) || j[key].is_null()) return defVal;
    const auto& val = j[key];
    if (val.is_number_unsigned()) return val.get<uint64_t>();
    if (val.is_number_integer()) return (uint64_t)std::max<int64_t>(0, val.get<int64_t>());
    if (val.is_string()) {
        try {
            return std::stoull(val.get<std::string>());
        } catch (...) {
            return defVal;
        }
    }
    return defVal;
}

// Dosya Seçim Penceresi
std::string openFileDialog(const char* filter) {
    OPENFILENAMEA ofn;
    CHAR szFile[1024] = {0};
    ZeroMemory(&ofn, sizeof(OPENFILENAMEA));
    ofn.lStructSize = sizeof(OPENFILENAMEA);
    ofn.hwndOwner = NULL;
    ofn.lpstrFile = szFile;
    ofn.nMaxFile = sizeof(szFile);
    ofn.lpstrFilter = filter;
    ofn.nFilterIndex = 1;
    ofn.lpstrFileTitle = NULL;
    ofn.nMaxFileTitle = 0;
    ofn.lpstrInitialDir = NULL;
    ofn.Flags = OFN_PATHMUSTEXIST | OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR;

    if (GetOpenFileNameA(&ofn) == TRUE) {
        return cleanPath(std::string(ofn.lpstrFile));
    }
    return "";
}

// Rastgele Benzersiz ID Üretici
std::string generateRandomId() {
    static const char chars[] = "0123456789abcdefghijklmnopqrstuvwxyz";
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, sizeof(chars) - 2);
    std::string id = "vid_";
    for (int i = 0; i < 10; ++i) {
        id += chars[dis(gen)];
    }
    return id;
}

// djb2 Hash Fonksiyonu
uint64_t djb2HashStr(const std::string& str) {
    uint64_t hash = 5381;
    for (char c : str) {
        hash = ((hash << 5) + hash) + (unsigned char)c;
    }
    return hash;
}

// ═══════════════════════════════════════════════════════════
//  GLOBAL DURUM & DEĞİŞKENLER
// ═══════════════════════════════════════════════════════════
std::string currentPackFile = "dataset.pack";
json currentHeader;
std::string statusMessage = "Hazır. Hoş geldiniz!";

// ═══════════════════════════════════════════════════════════
//  PAKET BAŞLIĞINI GÜVENLİ YÜKLEME
// ═══════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════
//  HUGGINGFACE ÇOKLU HESAP (MULTI-ACCOUNT) SENKRONİZASYONU
// ═══════════════════════════════════════════════════════════
struct HfAccount {
    std::string id;
    std::string name;
    std::string repoId;
    std::string branch = "main";
    std::string token;
    bool active = true;
};

std::vector<HfAccount> g_hfAccounts;
json g_hfDiscoveredVideos = json::array();
bool g_hfSyncing = false;
std::string g_hfSyncStatus = "Henüz senkronize edilmedi.";

void saveHfAccounts() {
    try {
        json j;
        j["sync_interval_seconds"] = 60;
        j["accounts"] = json::array();
        for (const auto& a : g_hfAccounts) {
            json item;
            item["id"] = a.id;
            item["name"] = a.name;
            item["repo_id"] = a.repoId;
            item["branch"] = a.branch;
            item["token"] = a.token;
            item["active"] = a.active;
            j["accounts"].push_back(item);
        }
        std::ofstream f("hf_accounts.json");
        if (f.is_open()) {
            f << j.dump(2);
            f.close();
        }
    } catch (...) {}
}

void loadHfAccounts() {
    g_hfAccounts.clear();
    if (fs::exists("hf_accounts.json")) {
        try {
            std::ifstream f("hf_accounts.json");
            json j = json::parse(f);
            if (j.contains("accounts") && j["accounts"].is_array()) {
                for (const auto& a : j["accounts"]) {
                    HfAccount acc;
                    acc.id = getJsonString(a, "id", "acc_" + std::to_string(g_hfAccounts.size() + 1));
                    acc.name = getJsonString(a, "name", "Depo");
                    acc.repoId = getJsonString(a, "repo_id", "eshansayhan/movie");
                    acc.branch = getJsonString(a, "branch", "main");
                    acc.token = getJsonString(a, "token", "");
                    acc.active = a.contains("active") && a["active"].is_boolean() ? a["active"].get<bool>() : true;
                    g_hfAccounts.push_back(acc);
                }
            }
        } catch (...) {}
    }
    if (g_hfAccounts.empty()) {
        HfAccount def;
        def.id = "acc_primary";
        def.name = "Eshan Ana Film Deposu";
        def.repoId = "eshansayhan/movie";
        def.branch = "main";
        def.active = true;
        g_hfAccounts.push_back(def);
        saveHfAccounts();
    }
}

void syncHuggingFaceVideos() {
    g_hfSyncing = true;
    g_hfDiscoveredVideos = json::array();
    Downloader dl;
    int packCount = 0;

    for (const auto& acc : g_hfAccounts) {
        if (!acc.active || acc.repoId.empty()) continue;
        std::string treeUrl = "https://huggingface.co/api/datasets/" + acc.repoId + "/tree/" + acc.branch;
        std::string repoBaseUrl = "https://huggingface.co/datasets/" + acc.repoId + "/resolve/" + acc.branch + "/";
        std::vector<uint8_t> treeBuf;
        if (dl.downloadFresh(treeUrl, treeBuf) && !treeBuf.empty()) {
            try {
                std::string treeStr(treeBuf.begin(), treeBuf.end());
                json tree = json::parse(treeStr);
                if (tree.is_array()) {
                    for (const auto& item : tree) {
                        if (!item.contains("path") || !item["path"].is_string()) continue;
                        std::string p = item["path"].get<std::string>();
                        if (p.size() >= 5 && p.rfind(".pack") == p.size() - 5) {
                            uint64_t pSize = item.contains("size") && item["size"].is_number() ? item["size"].get<uint64_t>() : 0;
                            if (pSize < 8) continue;
                            packCount++;
                            std::string packUrl = repoBaseUrl + p;
                            std::vector<uint8_t> tailBuf;
                            size_t fetchTail = (pSize < 65536) ? (size_t)pSize : 65536;
                            if (dl.downloadTailFresh(packUrl, pSize, fetchTail, tailBuf)) {
                                json pHeader;
                                if (tailBuf.size() >= 8) {
                                    uint64_t hSize = 0;
                                    memcpy(&hSize, tailBuf.data() + tailBuf.size() - 8, sizeof(uint64_t));
                                    if (hSize > 0 && hSize <= tailBuf.size() - 8) {
                                        size_t start = tailBuf.size() - 8 - hSize;
                                        std::string s(tailBuf.begin() + start, tailBuf.begin() + start + hSize);
                                        try { pHeader = json::parse(s); } catch(...) {}
                                    }
                                }
                                if (pHeader.contains("videos") && pHeader["videos"].is_array()) {
                                    for (auto& v : pHeader["videos"]) {
                                        v["source_repo"] = acc.repoId;
                                        v["source_account"] = acc.name;
                                        v["pack_file"] = p;
                                        v["is_remote_hf"] = true;
                                        g_hfDiscoveredVideos.push_back(v);
                                    }
                                }
                            }
                        }
                    }
                }
            } catch (...) {}
        }
    }
    g_hfSyncing = false;
    g_hfSyncStatus = "Aktif! " + std::to_string(packCount) + " paket ve " + std::to_string(g_hfDiscoveredVideos.size()) + " HF videosu senkronize edildi.";
}

void loadHeader() {
    try {
        if (!fileExists(currentPackFile) || getFileSize(currentPackFile) < 8) {
            currentHeader = json::object();
            currentHeader["videos"] = json::array();
            return;
        }
        std::ifstream file(currentPackFile, std::ios::binary);
        if (!file.is_open()) {
            currentHeader = json::object();
            currentHeader["videos"] = json::array();
            return;
        }
        file.seekg(-8, std::ios::end);
        uint64_t headerSize = 0;
        file.read(reinterpret_cast<char*>(&headerSize), sizeof(uint64_t));
        uint64_t totalSize = getFileSize(currentPackFile);
        if (headerSize == 0 || headerSize > totalSize - 8) {
            currentHeader = json::object();
            currentHeader["videos"] = json::array();
            return;
        }
        uint64_t headerStartPos = totalSize - 8 - headerSize;
        file.seekg(headerStartPos, std::ios::beg);
        std::string headerStr(headerSize, '\0');
        file.read(&headerStr[0], headerSize);
        file.close();

        currentHeader = json::parse(headerStr);
        if (!currentHeader.is_object() || !currentHeader.contains("videos") || !currentHeader["videos"].is_array()) {
            currentHeader = json::object();
            currentHeader["videos"] = json::array();
        }
    } catch (const std::exception& e) {
        currentHeader = json::object();
        currentHeader["videos"] = json::array();
        statusMessage = std::string("Paket okuma uyarısı: ") + e.what();
    } catch (...) {
        currentHeader = json::object();
        currentHeader["videos"] = json::array();
    }
}

// ═══════════════════════════════════════════════════════════
//  PAKET BAŞLIĞINI GÜVENLİ YAZMA
// ═══════════════════════════════════════════════════════════
bool writePackHeader(std::fstream& file, uint64_t headerStartPos) {
    try {
        std::string headerStr = currentHeader.dump();
        uint64_t headerSize = headerStr.size();
        file.seekp(headerStartPos, std::ios::beg);
        file.write(headerStr.c_str(), headerSize);
        file.write(reinterpret_cast<const char*>(&headerSize), sizeof(uint64_t));
        file.flush();
        file.close();

        std::error_code ec;
        fs::resize_file(currentPackFile, headerStartPos + headerSize + 8, ec);
        return true;
    } catch (const std::exception& e) {
        statusMessage = std::string("Hata: Başlık yazılamadı: ") + e.what();
        return false;
    }
}

// ═══════════════════════════════════════════════════════════
//  MASTER_INDEX.JSON OLUŞTURUCU (TÜM META BİLGİLERLE)
// ═══════════════════════════════════════════════════════════
void generateMasterIndex() {
    try {
        json master;
        master["sitemap"] = "/sitemap.xml";
        master["robots"]  = "/robots.txt";
        master["videos"]  = json::array();
        std::error_code ec;

        for (const auto& entry : fs::directory_iterator(".", ec)) {
            if (ec) break;
            if (entry.path().extension() == ".pack") {
                std::string packFileName = entry.path().filename().string();
                if (getFileSize(packFileName) < 8) continue;

                std::ifstream file(packFileName, std::ios::binary);
                if (!file.is_open()) continue;
                file.seekg(-8, std::ios::end);
                uint64_t headerSize = 0;
                file.read(reinterpret_cast<char*>(&headerSize), sizeof(uint64_t));
                uint64_t tot = getFileSize(packFileName);
                if (headerSize == 0 || headerSize > tot - 8) continue;

                uint64_t headerStartPos = tot - 8 - headerSize;
                file.seekg(headerStartPos, std::ios::beg);
                std::string headerStr(headerSize, '\0');
                file.read(&headerStr[0], headerSize);
                file.close();

                try {
                    json header = json::parse(headerStr);
                    if (header.is_object() && header.contains("videos") && header["videos"].is_array()) {
                        for (auto& v : header["videos"]) {
                            json entryInfo;
                            std::string vName = getJsonString(v, "name", "video.mp4");
                            std::string vidId = getJsonString(v, "id", std::to_string(djb2HashStr(vName)));
                            std::string vTitle = getJsonString(v, "title", vName);

                            std::string slug = "";
                            for (char c : vTitle) {
                                if (isalnum((unsigned char)c)) slug += (char)tolower((unsigned char)c);
                                else if (c == ' ' || c == '-' || c == '_') {
                                    if (!slug.empty() && slug.back() != '-') slug += '-';
                                }
                            }
                            if (slug.empty()) slug = vidId;

                            std::string yr = getJsonString(v, "year", "2024");
                            std::string uploadDate = getJsonString(v, "upload_date", yr + "-01-01T00:00:00+03:00");
                            uint64_t vSize = getJsonUint64(v, "size", 0);
                            uint64_t duration = getJsonUint64(v, "duration", (vSize > 0 ? (vSize / (250 * 1024)) : 7200));
                            if (duration < 60) duration = 7200;

                            entryInfo["name"]        = vName;
                            entryInfo["id"]          = vidId;
                            entryInfo["title"]       = vTitle;
                            entryInfo["slug"]        = slug;
                            entryInfo["upload_date"] = uploadDate;
                            entryInfo["duration"]    = duration;
                            entryInfo["canonical_url"] = "/watch/" + vidId;
                            entryInfo["watch_url"]     = "/watch/" + vidId;
                            entryInfo["embed_url"]     = "/embed/" + vidId;
                            entryInfo["stream_url"]    = "/video/" + vidId;
                            entryInfo["category"]    = getJsonString(v, "category", "Sinema & Film");
                            entryInfo["genre"]       = getJsonString(v, "genre", "");
                            entryInfo["tags"]        = getJsonString(v, "tags", "");
                            entryInfo["director"]    = getJsonString(v, "director", "");
                            entryInfo["cast"]        = getJsonString(v, "cast", "");
                            entryInfo["year"]        = yr;
                            entryInfo["country"]     = getJsonString(v, "country", "");
                            entryInfo["audio_lang"]  = getJsonString(v, "audio_lang", "Türkçe Dublaj");
                            entryInfo["imdb"]        = getJsonString(v, "imdb", "");
                            entryInfo["description"] = getJsonString(v, "description", "");
                            entryInfo["backdrops"]   = getJsonString(v, "backdrops", "");
                            entryInfo["node_url"]    = getJsonString(v, "node_url", "");
                            entryInfo["size"]        = vSize;
                            entryInfo["offset"]      = getJsonUint64(v, "offset", 0);
                            bool isSer = v.contains("is_series") && v["is_series"].is_boolean() ? v["is_series"].get<bool>() : false;
                            if (v.contains("content_type") && v["content_type"].is_string()) {
                                std::string ct = v["content_type"].get<std::string>();
                                isSer = (ct == "dizi" || ct == "series");
                            }
                            entryInfo["is_series"]   = isSer;
                            entryInfo["content_type"]= isSer ? "dizi" : "film";
                            entryInfo["type"]        = isSer ? "Dizi" : "Film";
                            entryInfo["series_title"]= getJsonString(v, "series_title", "");
                            entryInfo["season"]      = v.contains("season") && v["season"].is_number() ? v["season"].get<int>() : 1;
                            entryInfo["episode"]     = v.contains("episode") && v["episode"].is_number() ? v["episode"].get<int>() : 1;
                            entryInfo["episode_title"]= getJsonString(v, "episode_title", "");
                            if (v.contains("cover_size")) {
                                entryInfo["cover_size"]   = getJsonUint64(v, "cover_size", 0);
                                entryInfo["cover_offset"] = getJsonUint64(v, "cover_offset", 0);
                            }
                            if (v.contains("cover_url")) {
                                entryInfo["cover_url"]   = getJsonString(v, "cover_url", "");
                            }
                            if (v.contains("sub_size")) {
                                entryInfo["sub_size"]   = getJsonUint64(v, "sub_size", 0);
                                entryInfo["sub_offset"] = getJsonUint64(v, "sub_offset", 0);
                            }
                            entryInfo["pack"] = packFileName;
                            master["videos"].push_back(entryInfo);
                        }
                    }
                } catch (...) {}
            }
        }

        std::ofstream out("master_index.json");
        if (out.is_open()) {
            out << master.dump(4);
            out.close();
            statusMessage = "Başarılı: master_index.json oluşturuldu! (" + std::to_string(master["videos"].size()) + " video)";
        }

        // Otomatik Google Video Uyumlu Sitemap XML & Robots.txt Üretimi
        std::string sitemapXml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
        sitemapXml += "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"\n";
        sitemapXml += "        xmlns:video=\"http://www.google.com/schemas/sitemap-video/1.1\">\n";
        sitemapXml += "  <url>\n    <loc>/</loc>\n    <changefreq>hourly</changefreq>\n    <priority>1.0</priority>\n  </url>\n";

        for (const auto& vi : master["videos"]) {
            std::string vId = vi["id"].get<std::string>();
            std::string vTtl = vi["title"].get<std::string>();
            std::string vDesc = vi["description"].get<std::string>();
            std::string vCat = vi["category"].get<std::string>();
            std::string vDate = vi["upload_date"].get<std::string>();
            uint64_t vDur = vi["duration"].get<uint64_t>();

            sitemapXml += "  <url>\n";
            sitemapXml += "    <loc>/watch/" + vId + "</loc>\n";
            sitemapXml += "    <lastmod>" + (vDate.size() >= 10 ? vDate.substr(0, 10) : "2024-01-01") + "</lastmod>\n";
            sitemapXml += "    <changefreq>weekly</changefreq>\n";
            sitemapXml += "    <priority>0.9</priority>\n";
            sitemapXml += "    <video:video>\n";
            sitemapXml += "      <video:thumbnail_loc>/api/cover/" + vId + "</video:thumbnail_loc>\n";
            sitemapXml += "      <video:title><![CDATA[" + vTtl + "]]></video:title>\n";
            sitemapXml += "      <video:description><![CDATA[" + vDesc + "]]></video:description>\n";
            sitemapXml += "      <video:content_loc>/video/" + vId + "</video:content_loc>\n";
            sitemapXml += "      <video:player_loc allow_embed=\"yes\" autoplay=\"ap=1\">/embed/" + vId + "</video:player_loc>\n";
            sitemapXml += "      <video:duration>" + std::to_string(vDur) + "</video:duration>\n";
            sitemapXml += "      <video:publication_date>" + vDate + "</video:publication_date>\n";
            sitemapXml += "      <video:family_friendly>yes</video:family_friendly>\n";
            sitemapXml += "      <video:category><![CDATA[" + vCat + "]]></video:category>\n";
            sitemapXml += "    </video:video>\n";
            sitemapXml += "  </url>\n";
        }
        sitemapXml += "</urlset>\n";

        std::ofstream smOut("sitemap.xml");
        if (smOut.is_open()) { smOut << sitemapXml; smOut.close(); }
        if (fs::exists("frontend")) {
            std::ofstream smOutF("frontend/sitemap.xml");
            if (smOutF.is_open()) { smOutF << sitemapXml; smOutF.close(); }
        }

        std::string robotsContent = "User-agent: *\nAllow: /\nAllow: /watch/\nAllow: /video/\nAllow: /embed/\nDisallow: /api/status\n\nSitemap: /sitemap.xml\n";
        std::ofstream rbOut("robots.txt");
        if (rbOut.is_open()) { rbOut << robotsContent; rbOut.close(); }
        if (fs::exists("frontend")) {
            std::ofstream rbOutF("frontend/robots.txt");
            if (rbOutF.is_open()) { rbOutF << robotsContent; rbOutF.close(); }
        }
    } catch (const std::exception& e) {
        statusMessage = std::string("İndeksleme Uyarısı: ") + e.what();
    }
}

// ═══════════════════════════════════════════════════════════
//  VİDEO EKLEME (AKICILIK & ÇÖKME KORUMALI ÇOKLU BLOK KOPYALAMA)
// ═══════════════════════════════════════════════════════════
void addVideo(
    const std::string& rawVideoPath, const std::string& rawCoverPath, const std::string& rawSubPath,
    const std::string& id, const std::string& title, const std::string& category,
    const std::string& genre, const std::string& tags, const std::string& director,
    const std::string& cast, const std::string& year, const std::string& country,
    const std::string& audioLang, const std::string& imdb, const std::string& description,
    const std::string& backdrops, const std::string& nodeUrl,
    bool isSeries = false, const std::string& seriesTitle = "", int season = 1, int episode = 1,
    const std::string& episodeTitle = ""
) {
    try {
        std::string videoPath = cleanPath(rawVideoPath);
        std::string coverPath = cleanPath(rawCoverPath);
        std::string subPath   = cleanPath(rawSubPath);

        // 1. Video Dosyası Kontrolü
        if (videoPath.empty()) {
            statusMessage = "Hata: Lütfen geçerli bir video dosyası seçin!";
            return;
        }
        if (!fileExists(videoPath)) {
            statusMessage = "Hata: Video dosyası bulunamadı! (" + videoPath + ")";
            return;
        }
        uint64_t vidSize = getFileSize(videoPath);
        if (vidSize == 0) {
            statusMessage = "Hata: Seçilen video dosyası boş (0 bayt)!";
            return;
        }

        // 2. Kapak Kontrolü (Yerel dosya girilmişse var olmalı, URL ise uzaktan kabul edilir)
        if (!coverPath.empty() && !isHttpUrl(coverPath) && !fileExists(coverPath)) {
            statusMessage = "Uyarı: Belirtilen yerel kapak resmi bulunamadı (" + coverPath + "). Lütfen geçerli bir resim seçin veya URL girin.";
            return;
        }

        loadHeader();
    loadHfAccounts();
    syncHuggingFaceVideos();
        std::string vidName = fs::path(videoPath).filename().string();
        for (auto& v : currentHeader["videos"]) {
            if (getJsonString(v, "name") == vidName) {
                statusMessage = "Hata: '" + vidName + "' adlı video pakette zaten mevcut!";
                return;
            }
        }

        uint64_t headerStartPos = 0;
        if (fileExists(currentPackFile) && getFileSize(currentPackFile) >= 8) {
            std::ifstream file(currentPackFile, std::ios::binary);
            if (file.is_open()) {
                file.seekg(-8, std::ios::end);
                uint64_t headerSize = 0;
                file.read(reinterpret_cast<char*>(&headerSize), sizeof(uint64_t));
                uint64_t tot = getFileSize(currentPackFile);
                if (headerSize > 0 && headerSize <= tot - 8) {
                    headerStartPos = tot - 8 - headerSize;
                } else {
                    headerStartPos = tot;
                }
                file.close();
            }
        }

        // Video Dosyasını Aç
        std::ifstream vfile(videoPath, std::ios::binary);
        if (!vfile.is_open()) {
            statusMessage = "Hata: Video dosyası okuma için açılamadı!";
            return;
        }

        // Paket Dosyasını Aç (Yoksa oluştur)
        std::fstream packFile;
        if (!fileExists(currentPackFile)) {
            std::ofstream createPack(currentPackFile, std::ios::binary);
            createPack.close();
        }
        packFile.open(currentPackFile, std::ios::in | std::ios::out | std::ios::binary);
        if (!packFile.is_open()) {
            statusMessage = "Hata: Paket dosyası (" + currentPackFile + ") yazılamıyor!";
            return;
        }
        packFile.seekp(headerStartPos, std::ios::beg);

        // RAM patlamasını önleyen 4MB'lık güvenli akış bloğu
        const size_t CHUNK_SIZE = 4 * 1024 * 1024;
        std::vector<char> chunk(CHUNK_SIZE);

        uint64_t writtenVidBytes = 0;
        while (vfile && writtenVidBytes < vidSize) {
            uint64_t remaining = vidSize - writtenVidBytes;
            size_t toRead = (remaining < CHUNK_SIZE) ? (size_t)remaining : CHUNK_SIZE;
            vfile.read(chunk.data(), toRead);
            std::streamsize bytes = vfile.gcount();
            if (bytes <= 0) break;
            packFile.write(chunk.data(), bytes);
            writtenVidBytes += (uint64_t)bytes;
        }
        vfile.close();

        // Kapak Resmi Yazımı (Yerel dosya ise göm, URL ise metadata'ya kaydet)
        uint64_t coverSize = 0;
        std::string coverUrlVal = "";
        if (isHttpUrl(coverPath)) {
            coverUrlVal = coverPath;
        } else if (!coverPath.empty() && fileExists(coverPath)) {
            coverSize = getFileSize(coverPath);
            std::ifstream cfile(coverPath, std::ios::binary);
            if (cfile.is_open()) {
                while (cfile) {
                    cfile.read(chunk.data(), chunk.size());
                    std::streamsize bytes = cfile.gcount();
                    if (bytes <= 0) break;
                    packFile.write(chunk.data(), bytes);
                }
                cfile.close();
            }
        }

        // Altyazı Dosyası Yazımı (Varsa)
        uint64_t subSize = 0;
        if (!subPath.empty() && fileExists(subPath)) {
            subSize = getFileSize(subPath);
            std::ifstream sfile(subPath, std::ios::binary);
            if (sfile.is_open()) {
                while (sfile) {
                    sfile.read(chunk.data(), chunk.size());
                    std::streamsize bytes = sfile.gcount();
                    if (bytes <= 0) break;
                    packFile.write(chunk.data(), bytes);
                }
                sfile.close();
            }
        }

        std::string uniqueId = id.empty() ? generateRandomId() : id;
        std::string cleanTitle = title.empty() ? vidName : title;

        json newVid;
        newVid["id"]          = uniqueId;
        newVid["name"]        = vidName;
        newVid["title"]       = cleanTitle;
        newVid["size"]        = writtenVidBytes;
        newVid["offset"]      = headerStartPos;
        newVid["cover_size"]  = coverSize;
        newVid["cover_offset"]= (coverSize > 0) ? (headerStartPos + writtenVidBytes) : 0;
        std::string coverMimeVal = "image/jpeg";
        if (!coverPath.empty()) {
            std::string ext = fs::path(coverPath).extension().string();
            std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
            if (ext == ".png") coverMimeVal = "image/png";
            else if (ext == ".webp") coverMimeVal = "image/webp";
        }
        newVid["cover_mime"] = coverMimeVal;
        if (!coverUrlVal.empty()) {
            newVid["cover_url"] = coverUrlVal;
        }
        newVid["sub_size"]    = subSize;
        newVid["sub_offset"]  = (subSize > 0) ? (headerStartPos + writtenVidBytes + coverSize) : 0;
        newVid["category"]    = category.empty() ? "Sinema & Film" : category;
        newVid["genre"]       = genre;
        newVid["tags"]        = tags;
        newVid["director"]    = director;
        newVid["cast"]        = cast;
        newVid["year"]        = year;
        newVid["country"]     = country;
        newVid["audio_lang"]  = audioLang.empty() ? "Türkçe Dublaj" : audioLang;
        newVid["imdb"]        = imdb;
        newVid["description"] = description;
        newVid["backdrops"]   = backdrops;
        newVid["node_url"]    = nodeUrl;
        newVid["is_series"]     = isSeries;
        newVid["content_type"]  = isSeries ? "dizi" : "film";
        newVid["type"]          = isSeries ? "Dizi" : "Film";
        newVid["series_title"]  = seriesTitle;
        newVid["season"]      = season;
        newVid["episode"]     = episode;
        newVid["episode_title"] = episodeTitle;
        newVid["pack"]        = currentPackFile;

        std::string yrVal = year.empty() ? "2024" : year;
        newVid["year"] = yrVal;
        newVid["upload_date"] = yrVal + "-01-01T00:00:00+03:00";
        uint64_t dur = (writtenVidBytes > 0) ? (writtenVidBytes / (250 * 1024)) : 7200;
        if (dur < 60) dur = 7200;
        newVid["duration"] = dur;
        std::string sSlug = "";
        for (char c : cleanTitle) {
            if (isalnum((unsigned char)c)) sSlug += (char)tolower((unsigned char)c);
            else if (c == ' ' || c == '-' || c == '_') {
                if (!sSlug.empty() && sSlug.back() != '-') sSlug += '-';
            }
        }
        if (sSlug.empty()) sSlug = uniqueId;
        newVid["slug"] = sSlug;
        newVid["canonical_url"] = "/watch/" + uniqueId;
        newVid["watch_url"] = "/watch/" + uniqueId;
        newVid["embed_url"] = "/embed/" + uniqueId;
        newVid["stream_url"] = "/video/" + uniqueId;

        currentHeader["videos"].push_back(newVid);

        writePackHeader(packFile, headerStartPos + writtenVidBytes + coverSize + subSize);
        generateMasterIndex();
        statusMessage = "Başarılı: '" + cleanTitle + "' pakete eklendi ve master_index senkronize edildi!";
    } catch (const std::exception& e) {
        statusMessage = std::string("Ekleme Hatası: ") + e.what();
    } catch (...) {
        statusMessage = "Bilinmeyen bir hata nedeniyle video eklenemedi!";
    }
}

// ═══════════════════════════════════════════════════════════
//  VİDEO META GÜNCELLEME (RE-ENCODE GEREKTİRMEZ - ANINDA)
// ═══════════════════════════════════════════════════════════
void updateVideoMetadata(
    int index, const std::string& id, const std::string& title, const std::string& category,
    const std::string& genre, const std::string& tags, const std::string& director,
    const std::string& cast, const std::string& year, const std::string& country,
    const std::string& audioLang, const std::string& imdb, const std::string& description,
    const std::string& backdrops, const std::string& nodeUrl,
    bool isSeries = false, const std::string& seriesTitle = "", int season = 1, int episode = 1,
    const std::string& episodeTitle = ""
) {
    try {
        loadHeader();
        if (index >= 0 && index < (int)currentHeader["videos"].size()) {
            auto& v = currentHeader["videos"][index];
            std::string curName = getJsonString(v, "name", "video.mp4");
            v["id"]          = id.empty() ? generateRandomId() : id;
            v["title"]       = title.empty() ? curName : title;
            v["category"]    = category.empty() ? "Sinema & Film" : category;
            v["genre"]       = genre;
            v["tags"]        = tags;
            v["director"]    = director;
            v["cast"]        = cast;
            v["year"]        = year;
            v["country"]     = country;
            v["audio_lang"]  = audioLang.empty() ? "Türkçe Dublaj" : audioLang;
            v["imdb"]        = imdb;
            v["description"] = description;
            v["backdrops"]   = backdrops;
            v["node_url"]    = nodeUrl;
            v["is_series"]     = isSeries;
            v["content_type"]  = isSeries ? "dizi" : "film";
            v["type"]          = isSeries ? "Dizi" : "Film";
            v["series_title"]  = seriesTitle;
            v["season"]      = season;
            v["episode"]     = episode;
            v["episode_title"] = episodeTitle;
            v["pack"]        = currentPackFile;

            std::string yrVal = year.empty() ? "2024" : year;
            v["year"]        = yrVal;
            if (!v.contains("upload_date") || v["upload_date"].is_null()) {
                v["upload_date"] = yrVal + "-01-01T00:00:00+03:00";
            }
            std::string sSlug = "";
            std::string curTtl = v.contains("title") && v["title"].is_string() ? v["title"].get<std::string>() : curName;
            for (char c : curTtl) {
                if (isalnum((unsigned char)c)) sSlug += (char)tolower((unsigned char)c);
                else if (c == ' ' || c == '-' || c == '_') {
                    if (!sSlug.empty() && sSlug.back() != '-') sSlug += '-';
                }
            }
            std::string curId = v["id"].get<std::string>();
            if (sSlug.empty()) sSlug = curId;
            v["slug"] = sSlug;
            v["canonical_url"] = "/watch/" + curId;
            v["watch_url"] = "/watch/" + curId;
            v["embed_url"] = "/embed/" + curId;
            v["stream_url"] = "/video/" + curId;

            if (fileExists(currentPackFile) && getFileSize(currentPackFile) >= 8) {
                std::ifstream file(currentPackFile, std::ios::binary);
                if (file.is_open()) {
                    file.seekg(-8, std::ios::end);
                    uint64_t oldHeaderSize = 0;
                    file.read(reinterpret_cast<char*>(&oldHeaderSize), sizeof(uint64_t));
                    uint64_t tot = getFileSize(currentPackFile);
                    file.close();
                    if (oldHeaderSize > 0 && oldHeaderSize <= tot - 8) {
                        uint64_t headerStartPos = tot - 8 - oldHeaderSize;
                        std::fstream pfile(currentPackFile, std::ios::in | std::ios::out | std::ios::binary);
                        if (pfile.is_open()) {
                            writePackHeader(pfile, headerStartPos);
                            generateMasterIndex();
                            statusMessage = "Başarılı: '" + getJsonString(v, "title") + "' meta bilgileri güncellendi!";
                            return;
                        }
                    }
                }
            }
            statusMessage = "Uyarı: Paket dosyasına yazılamadı!";
        } else {
            statusMessage = "Hata: Güncellenecek video indeksi geçersiz!";
        }
    } catch (const std::exception& e) {
        statusMessage = std::string("Hata (Güncelleme): ") + e.what();
    }
}

// ═══════════════════════════════════════════════════════════
//  VİDEO SİLME (PAKETİ KÜÇÜLTME & GÜVENLİ ERASE)
// ═══════════════════════════════════════════════════════════
void removeVideo(int index) {
    try {
        loadHeader();
        if (index < 0 || index >= (int)currentHeader["videos"].size()) {
            statusMessage = "Hata: Silinecek video indeksi geçersiz!";
            return;
        }
        auto deletedVideo = currentHeader["videos"][index];
        uint64_t delOffset = getJsonUint64(deletedVideo, "offset");
        uint64_t delSize = getJsonUint64(deletedVideo, "size") + getJsonUint64(deletedVideo, "cover_size");
        if (deletedVideo.contains("sub_size")) {
            delSize += getJsonUint64(deletedVideo, "sub_size");
        }
        std::string vName = getJsonString(deletedVideo, "name", "Video");

        // GÜVENLİ SİLME: std::vector benzeri iterator ile silinir (type_error önlenir)
        currentHeader["videos"].erase(currentHeader["videos"].begin() + index);

        for (auto& v : currentHeader["videos"]) {
            uint64_t vOff = getJsonUint64(v, "offset");
            if (vOff > delOffset) {
                v["offset"] = vOff - delSize;
                uint64_t covOff = getJsonUint64(v, "cover_offset");
                if (covOff >= delSize) v["cover_offset"] = covOff - delSize;
                uint64_t subOff = getJsonUint64(v, "sub_offset");
                if (subOff >= delSize) v["sub_offset"] = subOff - delSize;
            }
        }

        std::string tmpFile = currentPackFile + ".tmp";
        {
            std::ifstream inFile(currentPackFile, std::ios::binary);
            std::ofstream outFile(tmpFile, std::ios::binary);

            if (!inFile.is_open() || !outFile.is_open()) {
                statusMessage = "Hata: Dosya kopyalama işlemi başlatılamadı!";
                return;
            }

            std::vector<char> buffer(64 * 1024);
            uint64_t bytesToCopy = delOffset;
            while (bytesToCopy > 0) {
                uint64_t toRead = (bytesToCopy < buffer.size()) ? bytesToCopy : buffer.size();
                inFile.read(buffer.data(), toRead);
                std::streamsize r = inFile.gcount();
                if (r <= 0) break;
                outFile.write(buffer.data(), r);
                bytesToCopy -= (uint64_t)r;
            }

            inFile.seekg(-8, std::ios::end);
            uint64_t oldHeaderSize = 0;
            inFile.read(reinterpret_cast<char*>(&oldHeaderSize), sizeof(uint64_t));
            uint64_t tot = getFileSize(currentPackFile);
            uint64_t oldHeaderStartPos = (oldHeaderSize <= tot - 8) ? (tot - 8 - oldHeaderSize) : tot;

            inFile.seekg(delOffset + delSize, std::ios::beg);
            uint64_t bytesToCopyAfter = 0;
            if (oldHeaderStartPos > (delOffset + delSize)) {
                bytesToCopyAfter = oldHeaderStartPos - (delOffset + delSize);
            }

            while (bytesToCopyAfter > 0) {
                uint64_t toRead = (bytesToCopyAfter < buffer.size()) ? bytesToCopyAfter : buffer.size();
                inFile.read(buffer.data(), toRead);
                std::streamsize r = inFile.gcount();
                if (r <= 0) break;
                outFile.write(buffer.data(), r);
                bytesToCopyAfter -= (uint64_t)r;
            }

            std::string headerStr = currentHeader.dump();
            uint64_t headerSize = headerStr.size();
            outFile.write(headerStr.c_str(), headerSize);
            outFile.write(reinterpret_cast<const char*>(&headerSize), sizeof(uint64_t));
            outFile.flush();
        }

        std::error_code ec;
        fs::remove(currentPackFile, ec);
        fs::rename(tmpFile, currentPackFile, ec);
        if (ec) {
            statusMessage = "Uyarı: Paket güncellenirken hata oluştu: " + ec.message();
        } else {
            generateMasterIndex();
            statusMessage = "Başarılı: '" + vName + "' paketten çıkarıldı ve dosya boyutu optimize edildi.";
        }
    } catch (const std::exception& e) {
        statusMessage = std::string("Hata (Silme): ") + e.what();
    }
}

// ═══════════════════════════════════════════════════════════
//  YAPAY ZEKA DESTEKLİ SEO VE META BİLGİ ÜRETİCİ
// ═══════════════════════════════════════════════════════════
void generateAIMetadata(
    const std::string& inputName,
    char* titleBuf, size_t titleSize,
    char* catBuf, size_t catSize,
    char* genreBuf, size_t genreSize,
    char* tagsBuf, size_t tagsSize,
    char* dirBuf, size_t dirSize,
    char* castBuf, size_t castSize,
    char* yearBuf, size_t yearSize,
    char* countryBuf, size_t countrySize,
    char* audioBuf, size_t audioSize,
    char* imdbBuf, size_t imdbSize,
    char* descBuf, size_t descSize,
    bool* isSeriesOut = nullptr,
    char* seriesTitleBuf = nullptr, size_t seriesTitleSize = 0,
    int* seasonOut = nullptr,
    int* episodeOut = nullptr,
    char* episodeTitleBuf = nullptr, size_t episodeTitleSize = 0
) {
    try {
        std::string s = fs::path(inputName).stem().string();
        if (s.empty()) s = "Yeni Sinema Filmi";

        std::string clean = s;
        const std::vector<std::string> junk = {
            "1080p", "720p", "4k", "2160p", "bluray", "web-dl", "webrip", "x264", "x265",
            "hevc", "dvdrip", "aac", "ac3", "dts", "dual", "hdtv", "yify", "rarbg"
        };
        std::string lower = clean;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        for (const auto& j : junk) {
            size_t pos = 0;
            while ((pos = lower.find(j, pos)) != std::string::npos) {
                clean.replace(pos, j.length(), " ");
                lower.replace(pos, j.length(), " ");
            }
        }
        for (char& c : clean) {
            if (c == '.' || c == '_' || c == '-') c = ' ';
        }

        std::string detectedYear = "2024";
        for (int y = 2026; y >= 1950; --y) {
            std::string ys = std::to_string(y);
            size_t p = clean.find(ys);
            if (p != std::string::npos) {
                detectedYear = ys;
                clean.replace(p, ys.length(), " ");
                break;
            }
        }

        std::string formattedTitle;
        bool capNext = true;
        for (char c : clean) {
            if (isspace((unsigned char)c)) {
                if (!formattedTitle.empty() && formattedTitle.back() != ' ') {
                    formattedTitle += ' ';
                }
                capNext = true;
            } else {
                formattedTitle += capNext ? (char)toupper((unsigned char)c) : (char)tolower((unsigned char)c);
                capNext = false;
            }
        }
        while (!formattedTitle.empty() && formattedTitle.back() == ' ') formattedTitle.pop_back();
        if (formattedTitle.empty()) formattedTitle = "Yeni Sinema İçeriği";

        std::string detectedCat = "Aksiyon";
        std::string detectedGenre = "Aksiyon, Macera, Gerilim";
        std::string tLower = formattedTitle;
        std::transform(tLower.begin(), tLower.end(), tLower.begin(), ::tolower);

        // Dizi & Bölüm Algılama (S01E05, 1x05, Bölüm vb.)
        bool detectedIsSeries = false;
        std::string detectedSeriesTitle = "";
        int detectedSeason = 1;
        int detectedEpisode = 1;

        for (size_t i = 0; i + 3 < lower.size(); ++i) {
            if (lower[i] == 's' && isdigit((unsigned char)lower[i+1])) {
                size_t ePos = lower.find('e', i + 1);
                if (ePos != std::string::npos && ePos <= i + 4 && ePos + 1 < lower.size() && isdigit((unsigned char)lower[ePos+1])) {
                    try {
                        detectedSeason = std::stoi(lower.substr(i + 1, ePos - (i + 1)));
                        detectedEpisode = std::stoi(lower.substr(ePos + 1));
                        detectedIsSeries = true;
                        detectedCat = "Macera";
                        detectedGenre = "Dizi, Macera, Heyecan";
                        std::string sTitle = formattedTitle.substr(0, std::min<size_t>(formattedTitle.size(), i));
                        while (!sTitle.empty() && (sTitle.back() == ' ' || sTitle.back() == '-')) sTitle.pop_back();
                        detectedSeriesTitle = sTitle;
                    } catch (...) {}
                    break;
                }
            }
        }

        if (tLower.find("korku") != std::string::npos || tLower.find("fear") != std::string::npos || tLower.find("dead") != std::string::npos || tLower.find("zombi") != std::string::npos) {
            detectedCat = "Korku";
            detectedGenre = "Korku, Gerilim, Gizem";
        } else if (tLower.find("komedi") != std::string::npos || tLower.find("laugh") != std::string::npos || tLower.find("comedy") != std::string::npos || tLower.find("yoktur") != std::string::npos) {
            detectedCat = "Komedi";
            detectedGenre = "Komedi, Eğlence";
        } else if (tLower.find("uzay") != std::string::npos || tLower.find("star") != std::string::npos || tLower.find("kurgu") != std::string::npos || tLower.find("sci") != std::string::npos) {
            detectedCat = "Bilim Kurgu";
            detectedGenre = "Bilim Kurgu, Uzay";
        } else if (tLower.find("dram") != std::string::npos || tLower.find("life") != std::string::npos) {
            detectedCat = "Dram";
            detectedGenre = "Dram, Duygusal";
        } else if (tLower.find("anime") != std::string::npos || tLower.find("naruto") != std::string::npos || tLower.find("animasyon") != std::string::npos) {
            detectedCat = "Animasyon";
            detectedGenre = "Animasyon, Fantastik";
        } else if (tLower.find("ask") != std::string::npos || tLower.find("love") != std::string::npos) {
            detectedCat = "Romantik";
            detectedGenre = "Romantik, Duygusal";
        } else if (tLower.find("belgesel") != std::string::npos || tLower.find("doc") != std::string::npos) {
            detectedCat = "Belgesel";
            detectedGenre = "Belgesel, Doğa";
        } else if (tLower.find("suc") != std::string::npos || tLower.find("crime") != std::string::npos || tLower.find("mafya") != std::string::npos) {
            detectedCat = "Suç";
            detectedGenre = "Suç, Polisiye";
        } else if (tLower.find("macera") != std::string::npos || tLower.find("adventure") != std::string::npos) {
            detectedCat = "Macera";
            detectedGenre = "Macera, Keşif";
        } else if (tLower.find("fantastik") != std::string::npos || tLower.find("magic") != std::string::npos) {
            detectedCat = "Fantastik";
            detectedGenre = "Fantastik, Büyü";
        }

        std::string generatedTags = detectedCat + ", 1080p, stream, turkce dublaj, " + detectedYear;
        std::string generatedDesc = formattedTitle + " (" + detectedYear + ") — Hugging Face veri kümesinden video akışı. " + detectedGenre + " türündeki bu yapım, sürükleyici hikayesiyle izleyicileri ekran başına kilitliyor.";

        strncpy_s(titleBuf, titleSize, formattedTitle.c_str(), _TRUNCATE);
        strncpy_s(catBuf, catSize, detectedCat.c_str(), _TRUNCATE);
        strncpy_s(genreBuf, genreSize, detectedGenre.c_str(), _TRUNCATE);
        strncpy_s(tagsBuf, tagsSize, generatedTags.c_str(), _TRUNCATE);
        if (strlen(dirBuf) == 0) strncpy_s(dirBuf, dirSize, "HFVideo Studio", _TRUNCATE);
        if (strlen(castBuf) == 0) strncpy_s(castBuf, castSize, "Sinema Oyuncu Kadrosu", _TRUNCATE);
        strncpy_s(yearBuf, yearSize, detectedYear.c_str(), _TRUNCATE);
        if (strlen(countryBuf) == 0) strncpy_s(countryBuf, countrySize, "Türkiye", _TRUNCATE);
        if (strlen(audioBuf) == 0) strncpy_s(audioBuf, audioSize, "Türkçe Dublaj", _TRUNCATE);
        if (strlen(imdbBuf) == 0) strncpy_s(imdbBuf, imdbSize, "7.9", _TRUNCATE);
        strncpy_s(descBuf, descSize, generatedDesc.c_str(), _TRUNCATE);

        if (isSeriesOut) *isSeriesOut = detectedIsSeries;
        if (seriesTitleBuf && seriesTitleSize > 0 && !detectedSeriesTitle.empty()) {
            strncpy_s(seriesTitleBuf, seriesTitleSize, detectedSeriesTitle.c_str(), _TRUNCATE);
        }
        if (seasonOut) *seasonOut = detectedSeason;
        if (episodeOut) *episodeOut = detectedEpisode;
        if (episodeTitleBuf && episodeTitleSize > 0 && detectedIsSeries) {
            std::string epTitle = "Bölüm " + std::to_string(detectedEpisode);
            strncpy_s(episodeTitleBuf, episodeTitleSize, epTitle.c_str(), _TRUNCATE);
        }
    } catch (...) {}
}

// ═══════════════════════════════════════════════════════════
//  ANA PROGRAM & IMGUI ARAYÜZÜ
// ═══════════════════════════════════════════════════════════
int main() {
    if (!glfwInit()) return -1;

    GLFWwindow* window = glfwCreateWindow(1180, 800, (const char*)u8"HF Video Paket Yöneticisi — AI & SEO Stüdyosu", NULL, NULL);
    if (!window) { glfwTerminate(); return -1; }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1); 

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO(); (void)io;
    ImGui::StyleColorsDark();

    // Türkçe Karakter Desteği
    static const ImWchar turkish_glyph_ranges[] = {
        0x0020, 0x00FF, // Basic Latin + Latin Supplement
        0x0100, 0x017F, // Latin Extended-A (ğ, Ğ, ı, İ, ş, Ş vb.)
        0x2000, 0x206F, // Genel Noktalama
        0x20A0, 0x20CF, // Para birimleri
        0x2190, 0x21FF, // Ok simgeleri
        0,
    };

    ImFont* mainFont = nullptr;
    const char* fontCandidates[] = {
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf"
    };
    for (const char* fpath : fontCandidates) {
        std::error_code ec;
        if (fs::exists(fpath, ec)) {
            mainFont = io.Fonts->AddFontFromFileTTF(fpath, 18.0f, nullptr, turkish_glyph_ranges);
            if (mainFont) break;
        }
    }
    if (!mainFont) {
        io.Fonts->AddFontDefault();
    }

    // Özel modern renk paleti
    ImVec4* colors = ImGui::GetStyle().Colors;
    colors[ImGuiCol_WindowBg]          = ImVec4(0.06f, 0.06f, 0.09f, 1.00f);
    colors[ImGuiCol_Header]            = ImVec4(0.12f, 0.14f, 0.20f, 1.00f);
    colors[ImGuiCol_HeaderHovered]     = ImVec4(0.00f, 0.90f, 0.70f, 0.40f);
    colors[ImGuiCol_HeaderActive]      = ImVec4(0.00f, 0.90f, 0.70f, 0.80f);
    colors[ImGuiCol_Button]            = ImVec4(0.12f, 0.14f, 0.22f, 1.00f);
    colors[ImGuiCol_ButtonHovered]     = ImVec4(0.00f, 0.85f, 0.65f, 0.50f);
    colors[ImGuiCol_ButtonActive]      = ImVec4(0.00f, 0.90f, 0.70f, 0.90f);
    colors[ImGuiCol_FrameBg]           = ImVec4(0.10f, 0.10f, 0.15f, 1.00f);
    colors[ImGuiCol_FrameBgHovered]    = ImVec4(0.16f, 0.16f, 0.25f, 1.00f);
    colors[ImGuiCol_Tab]               = ImVec4(0.11f, 0.11f, 0.16f, 1.00f);
    colors[ImGuiCol_TabHovered]        = ImVec4(0.00f, 0.85f, 0.65f, 0.60f);
    colors[ImGuiCol_TabActive]         = ImVec4(0.00f, 0.75f, 0.60f, 1.00f);

    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init("#version 130");

    loadHeader();

    // Form Değişkenleri
    char inputBuffer[512]       = "";
    char coverBuffer[512]       = "";
    char subBuffer[512]         = "";
    char idBuffer[64]           = "";
    char titleBuffer[256]       = "";
    char categoryBuffer[128]    = "Aksiyon";
    char genreBuffer[128]       = "Aksiyon, Macera";
    char tagsBuffer[256]        = "4k, stream, turkce dublaj";
    char directorBuffer[128]    = "";
    char castBuffer[512]        = "";
    char yearBuffer[32]         = "2024";
    char countryBuffer[64]      = "Türkiye";
    char audioLangBuffer[64]    = "Türkçe Dublaj";
    char imdbBuffer[32]         = "7.8";
    char descBuffer[2048]       = "";
    char backdropsBuffer[1024]  = "";
    char nodeUrlBuffer[512]     = "https://huggingface.co/datasets/eshansayhan/movie/resolve/main";
    char searchFilterBuffer[128]= "";
    static char packNameBuffer[128] = "dataset.pack";
    // 0: 🎬 Film, 1: 📺 Dizi (Zorunlu Seçim)
    static int contentTypeChoice = 0;
    static char seriesTitleBuffer[256] = "";
    static int seasonInt = 1;
    static int episodeInt = 1;
    static char episodeTitleBuffer[256] = "";

    std::string initialId = generateRandomId();
    strncpy_s(idBuffer, sizeof(idBuffer), initialId.c_str(), _TRUNCATE);

    static const char* categoryPresets[] = {
        "Aksiyon", "Macera", "Animasyon", "Komedi", "Dram", "Suç",
        "Gizem", "Gerilim", "Korku", "Romantik", "Bilim Kurgu", "Fantastik",
        "Aile", "Belgesel", "Biyografi", "Tarih", "Savaş", "Western",
        "Müzikal", "Spor", "Müzik", "Film-Noir", "Kısa Film"
    };
    static int selectedCategoryPreset = 0;

    static const char* audioOptions[] = {
        "Türkçe Dublaj", "Türkçe Altyazılı", "Orijinal Dil (İngilizce)",
        "Orijinal Dil (Japonca)", "Orijinal Dil (Korece)", "Çift Ses (Dual)", "Yerli Yapım"
    };
    static int selectedAudioOption = 0;

    int editingVideoIndex = -1; // -1: Ekleme Modu, >= 0: Düzenleme Modu

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        ImGui::SetNextWindowPos(ImVec2(0, 0));
        ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
        ImGui::Begin("ManagerPro", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove);

        // ══════════════════════════════════════════════════════
        // 1. ÜST BAR: PAKET SEÇİMİ VE GENEL AKSİYONLAR
        // ══════════════════════════════════════════════════════
        ImGui::TextColored(ImVec4(0.0f, 0.9f, 0.7f, 1.0f), "HF VIDEO PACK MANAGER PRO");
        ImGui::SameLine();
        ImGui::TextDisabled("| Merkeziyetsiz Video, AI & SEO Meta Stüdyosu");
        ImGui::Separator();

        ImGui::SetNextItemWidth(220);
        ImGui::InputText("##packname", packNameBuffer, IM_ARRAYSIZE(packNameBuffer));
        ImGui::SameLine();
        if (ImGui::Button("📂 Paketi Yükle")) {
            currentPackFile = cleanPath(packNameBuffer);
            loadHeader();
            size_t vCount = (currentHeader.contains("videos") && currentHeader["videos"].is_array()) ? currentHeader["videos"].size() : 0;
            statusMessage = currentPackFile + " yüklendi. Toplam: " + std::to_string(vCount) + " video.";
        }
        ImGui::SameLine();
        if (ImGui::Button("✨ Yeni Paket")) {
            std::string newPName = "yeni_paket_" + std::to_string(rand() % 900 + 100) + ".pack";
            strncpy_s(packNameBuffer, sizeof(packNameBuffer), newPName.c_str(), _TRUNCATE);
            currentPackFile = newPName;
            currentHeader = json::object();
            currentHeader["videos"] = json::array();
            statusMessage = "Yeni paket hazırlandı: " + newPName + " (Videolarınızı ekleyip kaydedebilirsiniz)";
        }
        ImGui::SameLine();
        if (ImGui::Button("⚡ Tüm Paketleri İndeksle (master_index.json)")) {
            generateMasterIndex();
        }
        ImGui::SameLine();
        size_t currentVideoCount = (currentHeader.contains("videos") && currentHeader["videos"].is_array()) ? currentHeader["videos"].size() : 0;
        ImGui::TextDisabled("(Aktif: %s | %zu Video)", currentPackFile.c_str(), currentVideoCount);

        ImGui::Separator();
        if (statusMessage.find("Hata") != std::string::npos) {
            ImGui::TextColored(ImVec4(1.0f, 0.3f, 0.3f, 1.0f), "❌ %s", statusMessage.c_str());
        } else if (statusMessage.find("Uyarı") != std::string::npos) {
            ImGui::TextColored(ImVec4(1.0f, 0.7f, 0.2f, 1.0f), "⚠️ %s", statusMessage.c_str());
        } else {
            ImGui::TextColored(ImVec4(0.2f, 0.9f, 0.5f, 1.0f), "ℹ️ Durum: %s", statusMessage.c_str());
        }
        ImGui::Separator();

        // ══════════════════════════════════════════════════════
        // 2. SEKMELİ YÖNETİM PANELİ (FORM & LİSTE)
        // ══════════════════════════════════════════════════════
        if (ImGui::BeginTabBar("ManagerTabs")) {

            // ──────────────────────────────────────────────────
            // TAB 1: VİDEO EKLE & META / AI DÜZENLE
            // ──────────────────────────────────────────────────
            std::string tabTitle = (editingVideoIndex >= 0) ? "✏️ Video Düzenle (DÜZENLEME MODU)" : "🎬 Yeni Video Ekle";
            if (ImGui::BeginTabItem(tabTitle.c_str())) {

                if (editingVideoIndex >= 0) {
                    ImGui::TextColored(ImVec4(0.0f, 1.0f, 0.5f, 1.0f), "⚠️ ŞU ANDA '%s' VİDEOSUNUN METAVERİSİNİ DÜZENLİYORSUNUZ", titleBuffer);
                    ImGui::SameLine();
                    if (ImGui::Button("✕ Düzenlemeyi İptal Et (Yeni Moduna Dön)")) {
                        editingVideoIndex = -1;
                        inputBuffer[0] = '\0';
                        coverBuffer[0] = '\0';
                        subBuffer[0] = '\0';
                        std::string nid = generateRandomId();
                        strncpy_s(idBuffer, sizeof(idBuffer), nid.c_str(), _TRUNCATE);
                        titleBuffer[0] = '\0';
                        descBuffer[0] = '\0';
                        backdropsBuffer[0] = '\0';
                        contentTypeChoice = 0;
                        seriesTitleBuffer[0] = '\0';
                        seasonInt = 1;
                        episodeInt = 1;
                        episodeTitleBuffer[0] = '\0';
                        statusMessage = "Yeni video ekleme moduna dönüldü.";
                    }
                    ImGui::Separator();
                }

                // Dosya Seçimleri
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "1. Medya Dosyaları:");
                ImGui::SetNextItemWidth(600);
                ImGui::InputText("Video Dosyası", inputBuffer, IM_ARRAYSIZE(inputBuffer));
                ImGui::SameLine();
                if (ImGui::Button("Video Seç...")) {
                    std::string path = openFileDialog("Video Dosyaları (*.mp4;*.mkv;*.avi)\0*.mp4;*.mkv;*.avi;*.mov\0Tüm Dosyalar (*.*)\0*.*\0");
                    if (!path.empty()) {
                        strncpy_s(inputBuffer, sizeof(inputBuffer), path.c_str(), _TRUNCATE);
                        bool detectedSer = false;
                        generateAIMetadata(path, titleBuffer, sizeof(titleBuffer), categoryBuffer, sizeof(categoryBuffer), genreBuffer, sizeof(genreBuffer), tagsBuffer, sizeof(tagsBuffer), directorBuffer, sizeof(directorBuffer), castBuffer, sizeof(castBuffer), yearBuffer, sizeof(yearBuffer), countryBuffer, sizeof(countryBuffer), audioLangBuffer, sizeof(audioLangBuffer), imdbBuffer, sizeof(imdbBuffer), descBuffer, sizeof(descBuffer), &detectedSer, seriesTitleBuffer, sizeof(seriesTitleBuffer), &seasonInt, &episodeInt, episodeTitleBuffer, sizeof(episodeTitleBuffer));
                        contentTypeChoice = detectedSer ? 1 : 0;
                    }
                }

                ImGui::SetNextItemWidth(600);
                ImGui::InputText("Kapak Resmi (Dosya veya URL)", coverBuffer, IM_ARRAYSIZE(coverBuffer));
                ImGui::SameLine();
                if (ImGui::Button("Kapak Seç...")) {
                    std::string path = openFileDialog("Resim Dosyaları (*.jpg;*.png;*.webp)\0*.jpg;*.jpeg;*.png;*.webp;*.bmp\0Tüm Dosyalar (*.*)\0*.*\0");
                    if (!path.empty()) {
                        strncpy_s(coverBuffer, sizeof(coverBuffer), path.c_str(), _TRUNCATE);
                    }
                }
                ImGui::TextDisabled("İster bilgisayarınızdan resim seçin, isterseniz doğrudan resim URL'si girin (örn: https://.../poster.jpg)");

                ImGui::SetNextItemWidth(600);
                ImGui::InputText("Altyazı Dosyası (.srt/.vtt)", subBuffer, IM_ARRAYSIZE(subBuffer));
                ImGui::SameLine();
                if (ImGui::Button("Altyazı Seç...")) {
                    std::string path = openFileDialog("Altyazı Dosyaları (*.srt;*.vtt)\0*.srt;*.vtt\0Tüm Dosyalar (*.*)\0*.*\0");
                    if (!path.empty()) {
                        strncpy_s(subBuffer, sizeof(subBuffer), path.c_str(), _TRUNCATE);
                    }
                }

                ImGui::Separator();
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "2. Benzersiz ID & Başlık:");

                ImGui::SetNextItemWidth(250);
                ImGui::InputText("Benzersiz ID", idBuffer, IM_ARRAYSIZE(idBuffer));
                ImGui::SameLine();
                if (ImGui::Button("🎲 Yeni Rastgele ID Üret")) {
                    std::string nid = generateRandomId();
                    strncpy_s(idBuffer, sizeof(idBuffer), nid.c_str(), _TRUNCATE);
                }

                ImGui::SetNextItemWidth(500);
                ImGui::InputText("Film / Video Başlığı", titleBuffer, IM_ARRAYSIZE(titleBuffer));
                ImGui::SameLine();
                if (ImGui::Button("🤖 Yapay Zeka ile SEO & Meta Doldur")) {
                    std::string src = strlen(inputBuffer) > 0 ? inputBuffer : titleBuffer;
                    bool detectedSer = false;
                    generateAIMetadata(src, titleBuffer, sizeof(titleBuffer), categoryBuffer, sizeof(categoryBuffer), genreBuffer, sizeof(genreBuffer), tagsBuffer, sizeof(tagsBuffer), directorBuffer, sizeof(directorBuffer), castBuffer, sizeof(castBuffer), yearBuffer, sizeof(yearBuffer), countryBuffer, sizeof(countryBuffer), audioLangBuffer, sizeof(audioLangBuffer), imdbBuffer, sizeof(imdbBuffer), descBuffer, sizeof(descBuffer), &detectedSer, seriesTitleBuffer, sizeof(seriesTitleBuffer), &seasonInt, &episodeInt, episodeTitleBuffer, sizeof(episodeTitleBuffer));
                    contentTypeChoice = detectedSer ? 1 : 0;
                    statusMessage = "Yapay zeka başlık, dizi/bölüm, kategori ve etiketleri otomatik hazırladı!";
                }

                ImGui::Separator();
                ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.2f, 1.0f), "3. Zorunlu İçerik Türü (Film veya Dizi Seçimi):");
                ImGui::PushStyleColor(ImGuiCol_Text, contentTypeChoice == 0 ? ImVec4(1.0f, 0.45f, 0.45f, 1.0f) : ImVec4(0.7f, 0.7f, 0.7f, 1.0f));
                if (ImGui::RadioButton("🎬 FİLM (Tek Parça Sinema Yapımı)", contentTypeChoice == 0)) {
                    contentTypeChoice = 0;
                }
                ImGui::PopStyleColor();
                ImGui::SameLine(340);
                ImGui::PushStyleColor(ImGuiCol_Text, contentTypeChoice == 1 ? ImVec4(0.85f, 0.45f, 1.0f, 1.0f) : ImVec4(0.7f, 0.7f, 0.7f, 1.0f));
                if (ImGui::RadioButton("📺 DİZİ (Sezonlu & Bölümlü Yapım)", contentTypeChoice == 1)) {
                    contentTypeChoice = 1;
                }
                ImGui::PopStyleColor();

                bool isSeries = (contentTypeChoice == 1);
                if (isSeries) {
                    ImGui::Spacing();
                    ImGui::TextColored(ImVec4(0.6f, 0.9f, 1.0f, 1.0f), "  ↳ Dizi / Seri Detayları:");
                    ImGui::SetNextItemWidth(350);
                    ImGui::InputText("Dizi / Seri Adı", seriesTitleBuffer, IM_ARRAYSIZE(seriesTitleBuffer));
                    ImGui::SameLine();
                    ImGui::SetNextItemWidth(100);
                    ImGui::InputInt("Sezon No", &seasonInt);
                    ImGui::SameLine();
                    ImGui::SetNextItemWidth(100);
                    ImGui::InputInt("Bölüm No", &episodeInt);
                    
                    ImGui::SetNextItemWidth(550);
                    ImGui::InputText("Bölüm Başlığı", episodeTitleBuffer, IM_ARRAYSIZE(episodeTitleBuffer));
                    ImGui::TextDisabled("Örn: Dizi: 'Breaking Bad' | Sezon: 1 | Bölüm: 1 | Bölüm Başlığı: 'Pilot'");
                } else {
                    ImGui::TextDisabled("Seçili Tür: Film (Video kartında ve oynatıcıda kırmızı '🎬 FİLM' etiketi yer alacaktır)");
                }

                ImGui::Separator();
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "4. Kategori, Tür ve SEO Etiketleri:");

                ImGui::SetNextItemWidth(220);
                if (ImGui::Combo("Hazır Kategori", &selectedCategoryPreset, categoryPresets, IM_ARRAYSIZE(categoryPresets))) {
                    strncpy_s(categoryBuffer, sizeof(categoryBuffer), categoryPresets[selectedCategoryPreset], _TRUNCATE);
                }
                ImGui::SameLine();
                ImGui::SetNextItemWidth(220);
                ImGui::InputText("Ana Kategori", categoryBuffer, IM_ARRAYSIZE(categoryBuffer));

                ImGui::SameLine();
                ImGui::SetNextItemWidth(300);
                ImGui::InputText("Detaylı Türler", genreBuffer, IM_ARRAYSIZE(genreBuffer));

                ImGui::SetNextItemWidth(700);
                ImGui::InputText("SEO Etiketleri (virgülle ayrılmış)", tagsBuffer, IM_ARRAYSIZE(tagsBuffer));
                ImGui::TextDisabled("Örn: aksiyon, 1080p stream, türkçe dublaj, nolan, uzay, oscar");

                ImGui::Separator();
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "5. Kadro & Yapım Bilgileri:");

                ImGui::SetNextItemWidth(320);
                ImGui::InputText("Yönetmen", directorBuffer, IM_ARRAYSIZE(directorBuffer));
                ImGui::SameLine();
                ImGui::SetNextItemWidth(450);
                ImGui::InputText("Oyuncular", castBuffer, IM_ARRAYSIZE(castBuffer));

                ImGui::SetNextItemWidth(120);
                ImGui::InputText("Yapım Yılı", yearBuffer, IM_ARRAYSIZE(yearBuffer));
                ImGui::SameLine();
                ImGui::SetNextItemWidth(180);
                ImGui::InputText("Ülke / Bölge", countryBuffer, IM_ARRAYSIZE(countryBuffer));
                ImGui::SameLine();
                ImGui::SetNextItemWidth(100);
                ImGui::InputText("IMDb Puanı", imdbBuffer, IM_ARRAYSIZE(imdbBuffer));

                ImGui::Separator();
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "6. Dil & Ses Seçenekleri:");

                ImGui::SetNextItemWidth(240);
                if (ImGui::Combo("Ses / Dublaj", &selectedAudioOption, audioOptions, IM_ARRAYSIZE(audioOptions))) {
                    strncpy_s(audioLangBuffer, sizeof(audioLangBuffer), audioOptions[selectedAudioOption], _TRUNCATE);
                }
                ImGui::SameLine();
                ImGui::SetNextItemWidth(200);
                ImGui::InputText("Seçili Dil", audioLangBuffer, IM_ARRAYSIZE(audioLangBuffer));

                ImGui::Separator();
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "7. Çoklu Resim / Backdrop & Galeri (İsteğe Bağlı):");
                ImGui::SetNextItemWidth(750);
                ImGui::InputText("Backdrop / Galeri Resim URL'leri", backdropsBuffer, IM_ARRAYSIZE(backdropsBuffer));
                ImGui::TextDisabled("Birden fazla resim URL'si arasına virgül koyun (ör: https://.../scene1.jpg, https://.../scene2.jpg)");

                ImGui::Separator();
                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "8. Konu Özeti & HF Düğüm URL:");
                ImGui::InputTextMultiline("Konu / Açıklama", descBuffer, IM_ARRAYSIZE(descBuffer), ImVec2(750, 70));

                ImGui::SetNextItemWidth(750);
                ImGui::InputText("HF Düğüm (Node) URL", nodeUrlBuffer, IM_ARRAYSIZE(nodeUrlBuffer));

                ImGui::Separator();
                // Aksiyon Butonu
                if (editingVideoIndex >= 0) {
                    if (ImGui::Button("💾 Değişiklikleri Kaydet (Meta Güncelle)", ImVec2(280, 36))) {
                        updateVideoMetadata(editingVideoIndex, idBuffer, titleBuffer, categoryBuffer, genreBuffer, tagsBuffer, directorBuffer, castBuffer, yearBuffer, countryBuffer, audioLangBuffer, imdbBuffer, descBuffer, backdropsBuffer, nodeUrlBuffer, contentTypeChoice == 1, seriesTitleBuffer, seasonInt, episodeInt, episodeTitleBuffer);
                        editingVideoIndex = -1;
                    }
                    ImGui::SameLine();
                    if (ImGui::Button("İptal", ImVec2(100, 36))) {
                        editingVideoIndex = -1;
                    }
                } else {
                    if (ImGui::Button("➕ Videoyu Pakete Göm ve Ekle", ImVec2(260, 36))) {
                        addVideo(inputBuffer, coverBuffer, subBuffer, idBuffer, titleBuffer, categoryBuffer, genreBuffer, tagsBuffer, directorBuffer, castBuffer, yearBuffer, countryBuffer, audioLangBuffer, imdbBuffer, descBuffer, backdropsBuffer, nodeUrlBuffer, contentTypeChoice == 1, seriesTitleBuffer, seasonInt, episodeInt, episodeTitleBuffer);
                        if (statusMessage.find("Başarılı") != std::string::npos) {
                            inputBuffer[0] = '\0';
                            coverBuffer[0] = '\0';
                            subBuffer[0]   = '\0';
                            std::string nid = generateRandomId();
                            strncpy_s(idBuffer, sizeof(idBuffer), nid.c_str(), _TRUNCATE);
                            titleBuffer[0] = '\0';
                            descBuffer[0]  = '\0';
                            backdropsBuffer[0] = '\0';
                        }
                    }
                }

                ImGui::EndTabItem();
            }

            // ──────────────────────────────────────────────────
            // TAB 2: MEVCUT VİDEOLAR & HIZLI ARAMA / DÜZENLEME
            // ──────────────────────────────────────────────────
            if (ImGui::BeginTabItem("📋 Mevcut Videolar & HuggingFace Arama")) {

                ImGui::SetNextItemWidth(340);
                ImGui::InputText("🔍 Canlı Ara", searchFilterBuffer, IM_ARRAYSIZE(searchFilterBuffer));
                ImGui::SameLine();
                if (ImGui::Button("Temizle")) {
                    searchFilterBuffer[0] = '\0';
                }
                ImGui::SameLine();
                if (ImGui::Button("🔄 HuggingFace'i Tara & Senkronize Et", ImVec2(240, 0))) {
                    syncHuggingFaceVideos();
                }
                ImGui::SameLine();
                ImGui::TextDisabled("(Durum: %s)", g_hfSyncStatus.c_str());

                size_t localCount = (currentHeader.contains("videos") && currentHeader["videos"].is_array()) ? currentHeader["videos"].size() : 0;
                size_t hfCount = g_hfDiscoveredVideos.size();
                ImGui::TextColored(ImVec4(0.0f, 0.9f, 0.7f, 1.0f), "💾 Yerel Videolar: %zu  |  🌐 HuggingFace Bulut Videolari: %zu  |  Toplam: %zu", localCount, hfCount, localCount + hfCount);
                ImGui::Separator();

                std::string q = searchFilterBuffer;
                std::transform(q.begin(), q.end(), q.begin(), ::tolower);

                // Birleşik Video Havuzu Oluştur
                json combinedList = json::array();
                if (currentHeader.contains("videos") && currentHeader["videos"].is_array()) {
                    for (auto& lv : currentHeader["videos"]) {
                        json item = lv;
                        item["is_remote_hf"] = false;
                        item["source_repo"] = "Yerel (" + currentPackFile + ")";
                        combinedList.push_back(item);
                    }
                }
                for (auto& hv : g_hfDiscoveredVideos) {
                    combinedList.push_back(hv);
                }

                if (ImGui::BeginTable("CombinedVideosTable", 8, ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg | ImGuiTableFlags_Resizable | ImGuiTableFlags_ScrollY, ImVec2(0, 520))) {
                    ImGui::TableSetupColumn("Kaynak / Konum", ImGuiTableColumnFlags_WidthFixed, 140.0f);
                    ImGui::TableSetupColumn("ID", ImGuiTableColumnFlags_WidthFixed, 90.0f);
                    ImGui::TableSetupColumn("Başlık / İsim", ImGuiTableColumnFlags_WidthStretch);
                    ImGui::TableSetupColumn("Kategori", ImGuiTableColumnFlags_WidthFixed, 100.0f);
                    ImGui::TableSetupColumn("Kapak (Gömülü)", ImGuiTableColumnFlags_WidthFixed, 110.0f);
                    ImGui::TableSetupColumn("Dil / Ses", ImGuiTableColumnFlags_WidthFixed, 95.0f);
                    ImGui::TableSetupColumn("Boyut", ImGuiTableColumnFlags_WidthFixed, 85.0f);
                    ImGui::TableSetupColumn("İşlemler", ImGuiTableColumnFlags_WidthFixed, 120.0f);
                    ImGui::TableHeadersRow();

                    int index = 0;
                    int videoToDelete = -1;
                    int videoToEdit = -1;

                    for (auto& v : combinedList) {
                        bool isHf = v.contains("is_remote_hf") && v["is_remote_hf"].get<bool>();
                        std::string vName     = getJsonString(v, "name", "video.mp4");
                        std::string vidId     = getJsonString(v, "id", std::to_string(djb2HashStr(vName)));
                        std::string vTitle    = getJsonString(v, "title", vName);
                        std::string vCat      = getJsonString(v, "category", "Sinema");
                        std::string vDir      = getJsonString(v, "director", "");
                        std::string vCast     = getJsonString(v, "cast", "");
                        std::string vAudio    = getJsonString(v, "audio_lang", "Türkçe Dublaj");
                        std::string vTags     = getJsonString(v, "tags", "");
                        std::string vSrc      = getJsonString(v, "source_repo", "Yerel");
                        uint64_t vSize        = getJsonUint64(v, "size", 0);
                        uint64_t covSize      = getJsonUint64(v, "cover_size", 0);

                        // Arama Filtresi
                        if (!q.empty()) {
                            std::string searchScope = vName + " " + vTitle + " " + vCat + " " + vDir + " " + vCast + " " + vTags + " " + vSrc;
                            std::transform(searchScope.begin(), searchScope.end(), searchScope.begin(), ::tolower);
                            if (searchScope.find(q) == std::string::npos) {
                                index++;
                                continue;
                            }
                        }

                        ImGui::TableNextRow();

                        // 1. Kaynak
                        ImGui::TableSetColumnIndex(0);
                        if (isHf) {
                            ImGui::TextColored(ImVec4(0.2f, 0.7f, 1.0f, 1.0f), "🌐 HF: %s", vSrc.c_str());
                        } else {
                            ImGui::TextColored(ImVec4(0.4f, 1.0f, 0.5f, 1.0f), "💾 %s", vSrc.c_str());
                        }

                        // 2. ID
                        ImGui::TableSetColumnIndex(1);
                        ImGui::TextDisabled("%s", vidId.substr(0, 10).c_str());

                        // 3. Başlık ve Tür Rozeti
                        ImGui::TableSetColumnIndex(2);
                        bool isVidSeries = false;
                        if (v.contains("content_type") && v["content_type"].is_string()) {
                            std::string ct = v["content_type"].get<std::string>();
                            isVidSeries = (ct == "dizi" || ct == "series");
                        } else if (v.contains("type") && v["type"].is_string()) {
                            std::string tp = v["type"].get<std::string>();
                            isVidSeries = (tp == "Dizi" || tp == "dizi");
                        } else if (v.contains("is_series") && v["is_series"].is_boolean()) {
                            isVidSeries = v["is_series"].get<bool>();
                        }

                        if (isVidSeries) {
                            ImGui::TextColored(ImVec4(0.85f, 0.45f, 1.0f, 1.0f), "[📺 DİZİ] ");
                            ImGui::SameLine();
                            ImGui::Text("%s", vTitle.c_str());
                            std::string sTitle = getJsonString(v, "series_title", "");
                            int sNo = v.contains("season") && v["season"].is_number() ? v["season"].get<int>() : 1;
                            int eNo = v.contains("episode") && v["episode"].is_number() ? v["episode"].get<int>() : 1;
                            ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.2f, 1.0f), "    ↳ %s (S%d:E%d)", sTitle.c_str(), sNo, eNo);
                        } else {
                            ImGui::TextColored(ImVec4(1.0f, 0.45f, 0.45f, 1.0f), "[🎬 FİLM] ");
                            ImGui::SameLine();
                            ImGui::Text("%s", vTitle.c_str());
                        }

                        // 4. Kategori
                        ImGui::TableSetColumnIndex(3);
                        ImGui::TextColored(ImVec4(0.0f, 0.9f, 0.7f, 1.0f), "🏷️ %s", vCat.c_str());

                        // 5. Kapak Durumu
                        ImGui::TableSetColumnIndex(4);
                        if (covSize > 0) {
                            ImGui::TextColored(ImVec4(0.2f, 1.0f, 0.4f, 1.0f), "🖼️ Gömülü (%d KB)", (int)(covSize / 1024));
                        } else if (v.contains("cover_url") && !v["cover_url"].get<std::string>().empty()) {
                            ImGui::TextColored(ImVec4(1.0f, 0.7f, 0.2f, 1.0f), "🔗 Harici URL");
                        } else {
                            ImGui::TextDisabled("- (Otomatik 273x410)");
                        }

                        // 6. Dil / Ses
                        ImGui::TableSetColumnIndex(5);
                        ImGui::Text("🎧 %s", vAudio.c_str());

                        // 7. Boyut
                        ImGui::TableSetColumnIndex(6);
                        double mb = (double)vSize / (1024.0 * 1024.0);
                        ImGui::Text("%.1f MB", mb);

                        // 8. İşlemler
                        ImGui::TableSetColumnIndex(7);
                        ImGui::PushID(index);
                        if (!isHf) {
                            if (ImGui::Button("✏️ Düzenle")) {
                                videoToEdit = index;
                            }
                            ImGui::SameLine();
                            if (ImGui::Button("🗑️ Sil")) {
                                videoToDelete = index;
                            }
                        } else {
                            ImGui::TextDisabled("HF Bulut");
                        }
                        ImGui::PopID();

                        index++;
                    }
                    ImGui::EndTable();

                    if (videoToEdit != -1 && videoToEdit < (int)currentHeader["videos"].size()) {
                        editingVideoIndex = videoToEdit;
                        auto& vid = currentHeader["videos"][editingVideoIndex];
                        std::string vName = getJsonString(vid, "name", "video.mp4");
                        std::string vidId = getJsonString(vid, "id", std::to_string(djb2HashStr(vName)));
                        std::string vTitle = getJsonString(vid, "title", vName);

                        strncpy_s(idBuffer, sizeof(idBuffer), vidId.c_str(), _TRUNCATE);
                        strncpy_s(titleBuffer, sizeof(titleBuffer), vTitle.c_str(), _TRUNCATE);
                        strncpy_s(categoryBuffer, sizeof(categoryBuffer), getJsonString(vid, "category", "Sinema").c_str(), _TRUNCATE);
                        strncpy_s(genreBuffer, sizeof(genreBuffer), getJsonString(vid, "genre", "").c_str(), _TRUNCATE);
                        strncpy_s(tagsBuffer, sizeof(tagsBuffer), getJsonString(vid, "tags", "").c_str(), _TRUNCATE);
                        strncpy_s(directorBuffer, sizeof(directorBuffer), getJsonString(vid, "director", "").c_str(), _TRUNCATE);
                        strncpy_s(castBuffer, sizeof(castBuffer), getJsonString(vid, "cast", "").c_str(), _TRUNCATE);
                        strncpy_s(yearBuffer, sizeof(yearBuffer), getJsonString(vid, "year", "2024").c_str(), _TRUNCATE);
                        strncpy_s(countryBuffer, sizeof(countryBuffer), getJsonString(vid, "country", "Türkiye").c_str(), _TRUNCATE);
                        strncpy_s(audioLangBuffer, sizeof(audioLangBuffer), getJsonString(vid, "audio_lang", "Türkçe Dublaj").c_str(), _TRUNCATE);
                        strncpy_s(imdbBuffer, sizeof(imdbBuffer), getJsonString(vid, "imdb", "7.8").c_str(), _TRUNCATE);
                        strncpy_s(descBuffer, sizeof(descBuffer), getJsonString(vid, "description", "").c_str(), _TRUNCATE);
                        strncpy_s(backdropsBuffer, sizeof(backdropsBuffer), getJsonString(vid, "backdrops", "").c_str(), _TRUNCATE);
                        strncpy_s(nodeUrlBuffer, sizeof(nodeUrlBuffer), getJsonString(vid, "node_url", "").c_str(), _TRUNCATE);
                        if (vid.contains("cover_url")) {
                            strncpy_s(coverBuffer, sizeof(coverBuffer), getJsonString(vid, "cover_url", "").c_str(), _TRUNCATE);
                        }

                        bool isSer = false;
                        if (vid.contains("content_type") && vid["content_type"].is_string()) {
                            std::string ct = vid["content_type"].get<std::string>();
                            isSer = (ct == "dizi" || ct == "series");
                        } else if (vid.contains("type") && vid["type"].is_string()) {
                            std::string tp = vid["type"].get<std::string>();
                            isSer = (tp == "Dizi" || tp == "dizi");
                        } else if (vid.contains("is_series") && vid["is_series"].is_boolean()) {
                            isSer = vid["is_series"].get<bool>();
                        }
                        contentTypeChoice = isSer ? 1 : 0;
                        strncpy_s(seriesTitleBuffer, sizeof(seriesTitleBuffer), getJsonString(vid, "series_title", "").c_str(), _TRUNCATE);
                        seasonInt = vid.contains("season") && vid["season"].is_number() ? vid["season"].get<int>() : 1;
                        episodeInt = vid.contains("episode") && vid["episode"].is_number() ? vid["episode"].get<int>() : 1;
                        strncpy_s(episodeTitleBuffer, sizeof(episodeTitleBuffer), getJsonString(vid, "episode_title", "").c_str(), _TRUNCATE);

                        statusMessage = "Düzenlemek için 1. Sekmeye geçildi: " + vTitle;
                    }

                    if (videoToDelete != -1) {
                        removeVideo(videoToDelete);
                    }
                }

                ImGui::EndTabItem();
            }

            // ──────────────────────────────────────────────────
            // TAB 3: ÇOKLU HUGGINGFACE HESAPLARI & SENKRONİZASYON
            // ──────────────────────────────────────────────────
            if (ImGui::BeginTabItem("🏢 Çoklu HF Hesapları")) {
                ImGui::TextColored(ImVec4(0.0f, 0.9f, 0.7f, 1.0f), "HuggingFace Çoklu Depo / Hesap Yönetimi & Senkronizasyon");
                ImGui::TextDisabled("Birden fazla HuggingFace hesabı veya veri seti deposu ekleyebilirsiniz. Platform tüm hesaplardaki .pack dosyalarını otomatik birleştirir.");
                ImGui::Separator();

                static char newAccName[128] = "";
                static char newAccRepo[256] = "";
                static char newAccBranch[64] = "main";
                static char newAccToken[256] = "";

                ImGui::TextColored(ImVec4(0.4f, 0.8f, 1.0f, 1.0f), "➕ Yeni HuggingFace Hesabı / Deposu Ekle:");
                ImGui::SetNextItemWidth(200);
                ImGui::InputText("Hesap Adı", newAccName, IM_ARRAYSIZE(newAccName));
                ImGui::SameLine();
                ImGui::SetNextItemWidth(260);
                ImGui::InputText("Repo ID (ör: kullanici/depo)", newAccRepo, IM_ARRAYSIZE(newAccRepo));
                ImGui::SameLine();
                ImGui::SetNextItemWidth(100);
                ImGui::InputText("Dal (Branch)", newAccBranch, IM_ARRAYSIZE(newAccBranch));
                
                ImGui::SetNextItemWidth(470);
                ImGui::InputText("HF Token (Gizli/Özel repolar için, isteğe bağlı)", newAccToken, IM_ARRAYSIZE(newAccToken), ImGuiInputTextFlags_Password);
                ImGui::SameLine();
                if (ImGui::Button("➕ Listeye Ekle", ImVec2(120, 26))) {
                    if (strlen(newAccRepo) > 0) {
                        HfAccount a;
                        a.id = "acc_" + std::to_string(rand() % 9000 + 1000);
                        a.name = strlen(newAccName) > 0 ? newAccName : newAccRepo;
                        a.repoId = cleanPath(newAccRepo);
                        a.branch = strlen(newAccBranch) > 0 ? cleanPath(newAccBranch) : "main";
                        a.token = cleanPath(newAccToken);
                        a.active = true;
                        g_hfAccounts.push_back(a);
                        saveHfAccounts();
                        newAccName[0] = '\0';
                        newAccRepo[0] = '\0';
                        newAccToken[0] = '\0';
                        statusMessage = "Yeni HuggingFace hesabı eklendi!";
                    }
                }

                ImGui::Separator();
                ImGui::Text("Kayıtlı HuggingFace Hesapları (%zu):", g_hfAccounts.size());

                int accToDelete = -1;
                for (size_t i = 0; i < g_hfAccounts.size(); ++i) {
                    ImGui::PushID((int)i);
                    auto& acc = g_hfAccounts[i];
                    ImGui::Checkbox("##active", &acc.active);
                    ImGui::SameLine();
                    ImGui::TextColored(acc.active ? ImVec4(0.2f, 1.0f, 0.5f, 1.0f) : ImVec4(0.5f, 0.5f, 0.5f, 1.0f), "[%s]", acc.name.c_str());
                    ImGui::SameLine();
                    ImGui::Text("Repo: %s (%s)", acc.repoId.c_str(), acc.branch.c_str());
                    ImGui::SameLine();
                    if (ImGui::Button("🗑️ Sil")) {
                        accToDelete = (int)i;
                    }
                    ImGui::PopID();
                }
                if (accToDelete >= 0 && accToDelete < (int)g_hfAccounts.size()) {
                    g_hfAccounts.erase(g_hfAccounts.begin() + accToDelete);
                    saveHfAccounts();
                }

                ImGui::Separator();
                if (ImGui::Button("💾 Hesapları Kaydet & Anında Senkronize Et", ImVec2(320, 36))) {
                    saveHfAccounts();
                    syncHuggingFaceVideos();
                }

                ImGui::EndTabItem();
            }


            ImGui::EndTabBar();
        }

        ImGui::End();
        ImGui::Render();
        int display_w, display_h;
        glfwGetFramebufferSize(window, &display_w, &display_h);
        glViewport(0, 0, display_w, display_h);
        glClearColor(0.06f, 0.06f, 0.09f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        glfwSwapBuffers(window);
    }

    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
