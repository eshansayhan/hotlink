#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>
#include <chrono>
#include <windows.h>
#include <filesystem>
#include <vector>
#include "StreamServer.h"
#include "Downloader.h"
#include "RegistryUtils.h"
#include "TrayManager.h"
#include <nlohmann/json.hpp>

using json = nlohmann::json;
namespace fs = std::filesystem;

// ============================================================
// GLOBAL STATE
// ============================================================
StreamServer streamServer;
json masterIndex;
std::string baseUrl = "https://huggingface.co/datasets/eshansayhan/movie/resolve/main/";

// Başlatılan child process handle'ı
HANDLE g_hPythonProcess = INVALID_HANDLE_VALUE;

// ============================================================
// Yardımcı: EXE'nin bulunduğu dizini al
// ============================================================
std::string getExeDir() {
    char buf[MAX_PATH];
    GetModuleFileNameA(NULL, buf, MAX_PATH);
    std::string path(buf);
    size_t pos = path.find_last_of("\\/");
    return (pos != std::string::npos) ? path.substr(0, pos) : ".";
}

static uint64_t djb2_hash(const std::string& str) {
    uint64_t hash = 5381;
    for (char c : str) {
        hash = ((hash << 5) + hash) + static_cast<unsigned char>(c);
    }
    return hash;
}


// ============================================================
// Yardımcı: Bir process başlat ve handle döndür
// ============================================================
HANDLE launchProcess(const std::string& exePath, const std::string& args, const std::string& workDir) {
    if (!fs::exists(exePath)) {
        std::cerr << "[UYARI] Dosya bulunamadi, atlanıyor: " << exePath << std::endl;
        return INVALID_HANDLE_VALUE;
    }

    std::string cmdLine = "\"" + exePath + "\"";
    if (!args.empty()) cmdLine += " " + args;

    STARTUPINFOA si = {};
    PROCESS_INFORMATION pi = {};
    si.cb = sizeof(si);
    // Konsol penceresini gizle (kullanıcıya siyah ekranlar gösterme)
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    std::vector<char> cmd(cmdLine.begin(), cmdLine.end());
    cmd.push_back('\0');

    BOOL ok = CreateProcessA(
        NULL, cmd.data(), NULL, NULL, FALSE,
        CREATE_NO_WINDOW, NULL,
        workDir.empty() ? NULL : workDir.c_str(),
        &si, &pi
    );

    if (!ok) {
        std::cerr << "[HATA] Process baslatılamadı: " << exePath << " (Hata: " << GetLastError() << ")" << std::endl;
        return INVALID_HANDLE_VALUE;
    }

    CloseHandle(pi.hThread);
    return pi.hProcess;
}

// ============================================================
// Tarayıcıyı aç (belirli bir süre sonra)
// ============================================================
void openBrowserDelayed(int delayMs, const std::string& url) {
    std::this_thread::sleep_for(std::chrono::milliseconds(delayMs));
    ShellExecuteA(NULL, "open", url.c_str(), NULL, NULL, SW_SHOWNORMAL);
}

// ============================================================
// Yardımcı: Bir tail buffer'dan gömülü JSON başlığını çıkar
// ============================================================
bool parsePackHeaderFromTail(const std::vector<uint8_t>& tailBuf, json& outHeader) {
    if (tailBuf.size() < 8) return false;
    uint64_t headerSize = 0;
    memcpy(&headerSize, tailBuf.data() + tailBuf.size() - 8, sizeof(uint64_t));
    if (headerSize == 0 || headerSize > 20 * 1024 * 1024) return false;
    if (headerSize > tailBuf.size() - 8) return false; // Daha büyük buffer gerekiyor
    
    std::string jsonStr(reinterpret_cast<const char*>(tailBuf.data() + tailBuf.size() - 8 - headerSize), headerSize);
    try {
        size_t startPos = jsonStr.find('{');
        if (startPos != std::string::npos) jsonStr = jsonStr.substr(startPos);
        outHeader = json::parse(jsonStr);
        return outHeader.is_object() && outHeader.contains("videos") && outHeader["videos"].is_array();
    } catch (...) {
        return false;
    }
}

// ============================================================
// Yardımcı: Yerel bir .pack dosyasının gömülü başlığını oku
// ============================================================
bool parsePackHeaderLocal(const std::string& filePath, json& outHeader) {
    std::error_code ec;
    uint64_t totalSize = fs::file_size(filePath, ec);
    if (ec || totalSize < 8) return false;
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) return false;
    file.seekg(-8, std::ios::end);
    uint64_t headerSize = 0;
    file.read(reinterpret_cast<char*>(&headerSize), sizeof(uint64_t));
    if (headerSize == 0 || headerSize > totalSize - 8 || headerSize > 20 * 1024 * 1024) return false;
    uint64_t startPos = totalSize - 8 - headerSize;
    file.seekg(startPos, std::ios::beg);
    std::string jsonStr(headerSize, '\0');
    file.read(&jsonStr[0], headerSize);
    file.close();
    try {
        size_t p = jsonStr.find('{');
        if (p != std::string::npos) jsonStr = jsonStr.substr(p);
        outHeader = json::parse(jsonStr);
        return outHeader.is_object() && outHeader.contains("videos") && outHeader["videos"].is_array();
    } catch (...) {
        return false;
    }
}

// ============================================================
// HuggingFace & Yerel Paketleri Otomatik Algıla ve İndeksle
// ============================================================
void fetchMasterIndex() {
    try {
        Downloader downloader;
        std::map<std::string, json> allDiscoveredVideos; // id -> video json
        std::vector<std::string> detectedPacks;

        // ────────────────────────────────────────────────────────────
        // 0. HuggingFace Çoklu Hesap Yapılandırmasını Yükle
        // ────────────────────────────────────────────────────────────
        std::vector<std::pair<std::string, std::string>> hfRepos; // {repo_id, branch}
        if (fs::exists("hf_accounts.json")) {
            try {
                std::ifstream accFile("hf_accounts.json");
                json accJson = json::parse(accFile);
                if (accJson.contains("accounts") && accJson["accounts"].is_array()) {
                    for (const auto& acc : accJson["accounts"]) {
                        bool active = acc.contains("active") ? acc["active"].get<bool>() : true;
                        if (!active) continue;
                        std::string rId = acc.contains("repo_id") ? acc["repo_id"].get<std::string>() : "eshansayhan/movie";
                        std::string br = acc.contains("branch") ? acc["branch"].get<std::string>() : "main";
                        if (!rId.empty()) {
                            hfRepos.push_back({rId, br});
                        }
                    }
                }
            } catch (...) {}
        }
        if (hfRepos.empty()) {
            hfRepos.push_back({"eshansayhan/movie", "main"});
        }

        // ────────────────────────────────────────────────────────────
        // 1. Çoklu HuggingFace Hesaplarındaki Paketleri Tara
        // ────────────────────────────────────────────────────────────
        for (const auto& [repoId, branch] : hfRepos) {
            std::string repoBaseUrl = "https://huggingface.co/datasets/" + repoId + "/resolve/" + branch + "/";
            std::string treeUrl = "https://huggingface.co/api/datasets/" + repoId + "/tree/" + branch;
            std::vector<uint8_t> treeBuf;
            if (downloader.downloadFresh(treeUrl, treeBuf) && !treeBuf.empty()) {
                try {
                    std::string treeStr(treeBuf.begin(), treeBuf.end());
                    json treeJson = json::parse(treeStr);
                    if (treeJson.is_array()) {
                        for (const auto& item : treeJson) {
                            if (!item.contains("path") || !item["path"].is_string()) continue;
                            std::string path = item["path"].get<std::string>();
                            
                            // .pack dosyası mı?
                            if (path.size() >= 5 && path.rfind(".pack") == path.size() - 5) {
                                uint64_t pSize = item.contains("size") && item["size"].is_number() ? item["size"].get<uint64_t>() : 0;
                                if (pSize < 8) continue;
                                
                                detectedPacks.push_back("[" + repoId + "] " + path + " (" + std::to_string(pSize / (1024 * 1024)) + "MB)");
                                std::string packUrl = repoBaseUrl + path;
                                
                                // Son 64KB'ı çek ve gömülü başlığı oku
                                std::vector<uint8_t> tailBuf;
                                size_t fetchTail = (pSize < 65536) ? (size_t)pSize : 65536;
                                if (downloader.downloadTailFresh(packUrl, pSize, fetchTail, tailBuf)) {
                                    json packHeader;
                                    if (!parsePackHeaderFromTail(tailBuf, packHeader)) {
                                        if (tailBuf.size() >= 8) {
                                            uint64_t neededSize = 0;
                                            memcpy(&neededSize, tailBuf.data() + tailBuf.size() - 8, sizeof(uint64_t));
                                            if (neededSize > 0 && neededSize <= 10 * 1024 * 1024) {
                                                std::vector<uint8_t> largeTail;
                                                if (downloader.downloadTailFresh(packUrl, pSize, neededSize + 8, largeTail)) {
                                                    parsePackHeaderFromTail(largeTail, packHeader);
                                                }
                                            }
                                        }
                                    }

                                    if (packHeader.contains("videos") && packHeader["videos"].is_array()) {
                                        for (auto& v : packHeader["videos"]) {
                                            if (!v.contains("pack") || v["pack"].get<std::string>().empty()) {
                                                v["pack"] = path;
                                            }
                                            if (!v.contains("node_url") || v["node_url"].get<std::string>().empty()) {
                                                v["node_url"] = repoBaseUrl;
                                            }
                                            std::string vidName = v.contains("name") ? v["name"].get<std::string>() : "video.mp4";
                                            std::string vidId = v.contains("id") && !v["id"].get<std::string>().empty() ? v["id"].get<std::string>() : std::to_string(djb2_hash(vidName));
                                            v["id"] = vidId;
                                            allDiscoveredVideos[vidId] = v;
                                        }
                                    }
                                }
                            }
                        }
                    }
                } catch (const std::exception& e) {
                    std::cerr << "[C++] HuggingFace tree parse uyarisi (" << repoId << "): " << e.what() << std::endl;
                }
            }

            // master_index.json kontrolü
            std::string indexUrl = repoBaseUrl + "master_index.json";
            std::vector<uint8_t> mBuffer;
            if (downloader.downloadFresh(indexUrl, mBuffer) && !mBuffer.empty()) {
                std::string mJsonStr(mBuffer.begin(), mBuffer.end());
                try {
                    size_t startPos = mJsonStr.find('{');
                    if (startPos != std::string::npos) mJsonStr = mJsonStr.substr(startPos);
                    json mObj = json::parse(mJsonStr);
                    if (mObj.contains("videos") && mObj["videos"].is_array()) {
                        for (auto& v : mObj["videos"]) {
                            std::string vidName = v.contains("name") ? v["name"].get<std::string>() : "video.mp4";
                            std::string vidId = v.contains("id") && !v["id"].get<std::string>().empty() ? v["id"].get<std::string>() : std::to_string(djb2_hash(vidName));
                            if (allDiscoveredVideos.find(vidId) != allDiscoveredVideos.end()) {
                                auto& ex = allDiscoveredVideos[vidId];
                                for (auto& [key, val] : v.items()) {
                                    if (!ex.contains(key) || ex[key].is_null() || (ex[key].is_string() && ex[key].get<std::string>().empty())) {
                                        ex[key] = val;
                                    }
                                }
                            }
                        }
                    }
                } catch (...) {}
            }
        }

        // ────────────────────────────────────────────────────────────
        // 2. Yerel Klasördeki Tüm *.pack Dosyalarını Tara
        // ────────────────────────────────────────────────────────────
        std::error_code ec;
        for (const auto& entry : fs::directory_iterator(".", ec)) {
            if (ec) break;
            if (entry.path().extension() == ".pack") {
                std::string lPackName = entry.path().filename().string();
                json lHeader;
                if (parsePackHeaderLocal(lPackName, lHeader)) {
                    for (auto& v : lHeader["videos"]) {
                        if (!v.contains("pack") || v["pack"].get<std::string>().empty()) {
                            v["pack"] = lPackName;
                        }
                        std::string vidName = v.contains("name") ? v["name"].get<std::string>() : "video.mp4";
                        std::string vidId = v.contains("id") && !v["id"].get<std::string>().empty() ? v["id"].get<std::string>() : std::to_string(djb2_hash(vidName));
                        v["id"] = vidId;
                        if (allDiscoveredVideos.find(vidId) == allDiscoveredVideos.end()) {
                            allDiscoveredVideos[vidId] = v;
                        }
                    }
                }
            }
        }

        // ────────────────────────────────────────────────────────────
        // 3. StreamServer'a Kaydet ve Canlı Tut
        // ────────────────────────────────────────────────────────────
        streamServer.clearVideos();
        masterIndex = json::object();
        masterIndex["videos"] = json::array();

        if (!allDiscoveredVideos.empty()) {
            for (auto const& [vidId, v] : allDiscoveredVideos) {
                std::string nodeUrl = "";
                if (v.contains("node_url") && !v["node_url"].is_null() && v["node_url"].is_string()) {
                    nodeUrl = v["node_url"].get<std::string>();
                }
                std::string packUrl = nodeUrl.empty() ? baseUrl : nodeUrl;
                if (!packUrl.empty() && packUrl.back() != '/') packUrl += '/';
                
                std::string packName = "dataset.pack";
                if (v.contains("pack") && v["pack"].is_string() && !v["pack"].get<std::string>().empty()) {
                    packName = v["pack"].get<std::string>();
                }
                packUrl += packName;
                
                std::string vName = v.contains("name") && v["name"].is_string() ? v["name"].get<std::string>() : "video.mp4";
                std::string vTitle = v.contains("title") && v["title"].is_string() ? v["title"].get<std::string>() : vName;
                std::string cat = v.contains("category") && v["category"].is_string() ? v["category"].get<std::string>() : (const char*)u8"Sinema & Film";
                std::string genre = v.contains("genre") && v["genre"].is_string() ? v["genre"].get<std::string>() : "";
                std::string tags = v.contains("tags") && v["tags"].is_string() ? v["tags"].get<std::string>() : "";
                std::string director = v.contains("director") && v["director"].is_string() ? v["director"].get<std::string>() : "";
                std::string cast = v.contains("cast") && v["cast"].is_string() ? v["cast"].get<std::string>() : "";
                
                std::string year = "";
                if (v.contains("year")) {
                    if (v["year"].is_string()) year = v["year"].get<std::string>();
                    else if (v["year"].is_number()) year = std::to_string(v["year"].get<int64_t>());
                }
                std::string country = v.contains("country") && v["country"].is_string() ? v["country"].get<std::string>() : "";
                std::string audioLang = v.contains("audio_lang") && v["audio_lang"].is_string() ? v["audio_lang"].get<std::string>() : (const char*)u8"Türkçe Dublaj";
                
                std::string imdb = "";
                if (v.contains("imdb")) {
                    if (v["imdb"].is_string()) imdb = v["imdb"].get<std::string>();
                    else if (v["imdb"].is_number()) {
                        std::ostringstream ss; ss << v["imdb"].get<double>(); imdb = ss.str();
                    }
                }
                std::string desc = v.contains("description") && v["description"].is_string() ? v["description"].get<std::string>() : "";
                std::string backdrops = v.contains("backdrops") && v["backdrops"].is_string() ? v["backdrops"].get<std::string>() : "";
                std::string cover = "";
                if (v.contains("cover") && v["cover"].is_string()) {
                    cover = v["cover"].get<std::string>();
                } else if (v.contains("cover_url") && v["cover_url"].is_string()) {
                    cover = v["cover_url"].get<std::string>();
                }

                uint64_t vOffset = 0;
                if (v.contains("offset")) {
                    if (v["offset"].is_number()) vOffset = v["offset"].get<uint64_t>();
                    else if (v["offset"].is_string()) {
                        try { vOffset = std::stoull(v["offset"].get<std::string>()); } catch(...) {}
                    }
                }
                uint64_t vSize = 0;
                if (v.contains("size")) {
                    if (v["size"].is_number()) vSize = v["size"].get<uint64_t>();
                    else if (v["size"].is_string()) {
                        try { vSize = std::stoull(v["size"].get<std::string>()); } catch(...) {}
                    }
                }

                // Gömülü Kapak Resmi Bilgileri
                uint64_t coverOffset = 0;
                if (v.contains("cover_offset")) {
                    if (v["cover_offset"].is_number()) coverOffset = v["cover_offset"].get<uint64_t>();
                    else if (v["cover_offset"].is_string()) {
                        try { coverOffset = std::stoull(v["cover_offset"].get<std::string>()); } catch(...) {}
                    }
                }
                uint64_t coverSize = 0;
                if (v.contains("cover_size")) {
                    if (v["cover_size"].is_number()) coverSize = v["cover_size"].get<uint64_t>();
                    else if (v["cover_size"].is_string()) {
                        try { coverSize = std::stoull(v["cover_size"].get<std::string>()); } catch(...) {}
                    }
                }
                std::string coverMime = "image/jpeg";
                if (v.contains("cover_mime") && v["cover_mime"].is_string()) {
                    coverMime = v["cover_mime"].get<std::string>();
                }

                // Dizi & Seri Meta Bilgileri
                bool isSeries = false;
                if (v.contains("is_series")) {
                    if (v["is_series"].is_boolean()) isSeries = v["is_series"].get<bool>();
                    else if (v["is_series"].is_number()) isSeries = (v["is_series"].get<int>() != 0);
                }
                std::string seriesTitle = v.contains("series_title") && v["series_title"].is_string() ? v["series_title"].get<std::string>() : "";
                int season = 1;
                if (v.contains("season")) {
                    if (v["season"].is_number()) season = v["season"].get<int>();
                    else if (v["season"].is_string()) {
                        try { season = std::stoi(v["season"].get<std::string>()); } catch(...) {}
                    }
                }
                int episode = 1;
                if (v.contains("episode")) {
                    if (v["episode"].is_number()) episode = v["episode"].get<int>();
                    else if (v["episode"].is_string()) {
                        try { episode = std::stoi(v["episode"].get<std::string>()); } catch(...) {}
                    }
                }
                std::string episodeTitle = v.contains("episode_title") && v["episode_title"].is_string() ? v["episode_title"].get<std::string>() : "";

                streamServer.addVideo(
                    vName, packUrl, vOffset, vSize,
                    cat, imdb, desc,
                    vidId, vTitle, genre, tags, director, cast, year, country, audioLang, backdrops, cover,
                    isSeries, seriesTitle, season, episode, episodeTitle, packName,
                    coverOffset, coverSize, coverMime
                );

                masterIndex["videos"].push_back(v);
            }

            std::cout << "[C++] 🚀 Paket Otomasyonu: " << hfRepos.size() << " HF hesabi taranarak toplam " << allDiscoveredVideos.size() << " video aktif!" << std::endl;
            if (!detectedPacks.empty()) {
                std::cout << "[C++] Algilanan HuggingFace paketleri: ";
                for (const auto& dp : detectedPacks) std::cout << dp << " ";
                std::cout << std::endl;
            }
        } else {
            std::cerr << "[C++ UYARI] Henuz paket veya video bulunamadi." << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "[C++] fetchMasterIndex hatasi: " << e.what() << std::endl;
    } catch (...) {
        std::cerr << "[C++] fetchMasterIndex bilinmeyen bir hata yakaladi." << std::endl;
    }
}

// ============================================================
// Çıkışta tüm child process'leri kapat
// ============================================================
void cleanupProcesses() {
    if (g_hPythonProcess != INVALID_HANDLE_VALUE) {
        TerminateProcess(g_hPythonProcess, 0);
        CloseHandle(g_hPythonProcess);
        g_hPythonProcess = INVALID_HANDLE_VALUE;
    }
}

static TrayManager g_tray;
static std::atomic<bool> g_appRunning{true};

BOOL WINAPI consoleCtrlHandler(DWORD ctrlType) {
    if (ctrlType == CTRL_CLOSE_EVENT) {
        bool minimizeToTray = RegistryUtils::ReadBool("MinimizeToTray", true);
        if (minimizeToTray) {
            HWND hCons = GetConsoleWindow();
            if (hCons) {
                ShowWindow(hCons, SW_HIDE);
            }
            std::cout << "\n[*] Pencere saat tarafina (System Tray) kucultuldu. Arka planda calisiyor." << std::endl;
            return TRUE; // Islemi sonlandirma, arka planda saat yaninda canli tut!
        }
    }
    std::cout << "\n[*] Kapatiliyor..." << std::endl;
    g_appRunning = false;
    cleanupProcesses();
    streamServer.stop();
    return TRUE;
}

// ============================================================
// MAIN
// ============================================================
int main(int argc, char* argv[]) {
    SetConsoleCtrlHandler(consoleCtrlHandler, TRUE);

    // Parametreleri kontrol et (--tray veya --background ile baslatilmissa gizli basla)
    bool startHidden = false;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--tray" || arg == "--background" || arg == "-b") {
            startHidden = true;
        }
    }

    // Regedit varsayılan ayarlarını oluştur ve kontrol et
    char exePathBuf[MAX_PATH];
    GetModuleFileNameA(NULL, exePathBuf, MAX_PATH);
    RegistryUtils::WriteAppSetting("InstallPath", exePathBuf);
    RegistryUtils::WriteAppSetting("Version", "1.0.0");
    if (RegistryUtils::ReadDword("Port", 0) == 0) {
        RegistryUtils::WriteDword("Port", 8080);
    }
    if (RegistryUtils::ReadAppSetting("MinimizeToTray", "") == "") {
        RegistryUtils::WriteBool("MinimizeToTray", true);
    }
    DWORD listenPort = RegistryUtils::ReadDword("Port", 8080);

    // System Tray (Saat Tarafi) Iconunu Baslat
    g_tray.SetExitCallback([]() {
        g_appRunning = false;
    });
    g_tray.Start(startHidden);

    std::string exeDir = getExeDir();
    std::string runtimeDir = exeDir + "\\runtime";

    std::cout << "==========================================" << std::endl;
    std::cout << "  HFVideoPlatform  |  Premium Streaming   " << std::endl;
    std::cout << "  C++ Local Video Engine |  by Eshan      " << std::endl;
    std::cout << "  Versiyon: 1.0.0 (Windows Tray Destekli) " << std::endl;
    std::cout << "==========================================" << std::endl;
    std::cout << std::endl;

    // --- 0. Önceki çalıştırmadan başlatılmış Python sürecini kapat ---
    std::cout << "[0/3] Uygulamanın önceki yardımcı süreci kapatılıyor..." << std::endl;
    cleanupProcesses();

    // --- 1. C++ Stream Server (port 8080) ---
    std::cout << "[1/3] C++ Stream Engine baslatiliyor (port " << listenPort << ")..." << std::endl;
    streamServer.setRefreshCallback(fetchMasterIndex);
    streamServer.start(listenPort);
    std::thread(fetchMasterIndex).detach();
    std::cout << "[1/3] C++ Stream Engine hazir." << std::endl;

    // HuggingFace arka plan otomatik senkronizasyon (her 25 saniyede bir)
    std::thread([]() {
        while (g_appRunning) {
            std::this_thread::sleep_for(std::chrono::seconds(25));
            try {
                fetchMasterIndex();
            } catch (const std::exception& e) {
                std::cerr << "[C++] Arka plan senkronizasyon hatasi: " << e.what() << std::endl;
            } catch (...) {
                std::cerr << "[C++] Arka plan senkronizasyon bilinmeyen hata!" << std::endl;
            }
        }
    }).detach();

    std::cout << "[2/3] Web UI ve API: C++ Engine (port " << listenPort << ") [gomulu]" << std::endl;

    // --- 3. Python AI Engine (port 5000) ---
    std::string pythonAiExe = runtimeDir + "\\python\\python_ai.exe";
    std::string pythonSrc   = exeDir + "\\..\\ai_python\\src\\main.py";

    if (fs::exists(pythonAiExe)) {
        std::cout << "[3/3] Python AI Engine baslatiliyor (port 5000)..." << std::endl;
        g_hPythonProcess = launchProcess(pythonAiExe, "", runtimeDir + "\\python");
    } else if (fs::exists(pythonSrc)) {
        const char* configuredPython = std::getenv("HFVP_PYTHON_EXECUTABLE");
        std::string pythonExe = configuredPython && *configuredPython
            ? configuredPython
            : "python";
        std::cout << "[3/3] Python AI Engine (dev mode) baslatiliyor..." << std::endl;
        const fs::path absolutePythonSrc = fs::absolute(pythonSrc).lexically_normal();
        g_hPythonProcess = launchProcess(
            pythonExe,
            "\"" + absolutePythonSrc.string() + "\"",
            absolutePythonSrc.parent_path().string()
        );
    } else {
        std::cout << "[3/3] Python AI Engine bulunamadi, atlanıyor." << std::endl;
    }
    if (g_hPythonProcess == INVALID_HANDLE_VALUE &&
        (fs::exists(pythonAiExe) || fs::exists(pythonSrc))) {
        std::cerr << "[HATA] Python AI Engine başlatılamadı; ayrıntı için önceki hata mesajını kontrol edin." << std::endl;
    }

    // --- Tarayiciyi ac (startHidden degilse) ---
    if (!startHidden) {
        std::thread(openBrowserDelayed, 1200, "http://localhost:" + std::to_string(listenPort)).detach();
    }

    std::cout << std::endl;
    std::cout << "==========================================" << std::endl;
    std::cout << "  C++ video motoru aktif." << std::endl;
    std::cout << "  Web Arayuzu : http://localhost:" << listenPort << "  <-- Tarayicida ac!" << std::endl;
    std::cout << "  Stream+API  : http://localhost:" << listenPort << std::endl;
    std::cout << "  Sistem Tepsisi: Saat yaninda simge olusturuldu." << std::endl;
    std::cout << "  (Carpidan kapattiginizda saat tarafina kuculur)" << std::endl;
    std::cout << "==========================================" << std::endl;

    // Ana dongu - Tray veya Ctrl+C cikis verene kadar canli
    while (g_appRunning) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }

    std::cout << "[*] Kapatma tamamlanıyor..." << std::endl;
    g_tray.Stop();
    cleanupProcesses();
    streamServer.stop();
    return 0;
}
