#pragma once
#include <string>
#include <cstdlib>
#include <filesystem>

inline std::string getAppCacheDir() {
    std::string basePath = "cache";
#ifdef _WIN32
    const char* appdata = getenv("APPDATA");
    if (appdata) {
        basePath = std::string(appdata) + "\\HFVideoPlatform\\cache";
    }
#endif
    std::filesystem::create_directories(basePath);
    return basePath;
}

inline void cleanupOldCacheFiles() {
    try {
        std::string cacheDir = getAppCacheDir();
        std::vector<std::filesystem::path> files;
        uintmax_t totalSize = 0;
        
        for (const auto& entry : std::filesystem::directory_iterator(cacheDir)) {
            if (entry.is_regular_file() && entry.path().extension() == ".enc") {
                files.push_back(entry.path());
                totalSize += std::filesystem::file_size(entry);
            }
        }
        
        // Eger diskte 500 MB'dan fazla .enc varsa en eskileri sil (500 * 1024 * 1024)
        // Maksat disk sismesin.
        const uintmax_t MAX_CACHE_SIZE = 500ULL * 1024ULL * 1024ULL;
        
        if (totalSize > MAX_CACHE_SIZE) {
            std::sort(files.begin(), files.end(), [](const std::filesystem::path& a, const std::filesystem::path& b) {
                return std::filesystem::last_write_time(a) < std::filesystem::last_write_time(b);
            });
            
            for (const auto& p : files) {
                totalSize -= std::filesystem::file_size(p);
                std::filesystem::remove(p);
                if (totalSize <= MAX_CACHE_SIZE) break;
            }
        }
    } catch(...) {}
}

// Akilli Cache Guncelleme (Yapay Zeka Benzeri Mantik)
// Eger ayni videoya ait daha kucuk veya cakisan bir eski parca varsa, onu silip yenisiyle (daha buyuguyle) gunceller.
// Boylece diskte ayni videonun ayni saniyelerinin 10 farkli kopyasi olusmaz.
inline void updateSmartCache(const std::string& urlHash, uint64_t startByte, uint64_t endByte) {
    try {
        std::string cacheDir = getAppCacheDir();
        std::string prefix = "vid_" + urlHash + "_";
        
        for (const auto& entry : std::filesystem::directory_iterator(cacheDir)) {
            if (entry.is_regular_file() && entry.path().extension() == ".enc") {
                std::string filename = entry.path().filename().string();
                
                // Eger bu dosya bizim videomuza aitse
                if (filename.find(prefix) == 0) {
                    // vid_HASH_START_END.enc formatini ayikla
                    std::string rest = filename.substr(prefix.length());
                    size_t underscore = rest.find('_');
                    size_t dot = rest.find(".enc");
                    if (underscore != std::string::npos && dot != std::string::npos) {
                        uint64_t cStart = std::stoull(rest.substr(0, underscore));
                        uint64_t cEnd = std::stoull(rest.substr(underscore + 1, dot - underscore - 1));
                        
                        // Eger eski cache, yeni indirecegimiz araligin icinde kaliyorsa (kapsaniyorsa) veya tamamen ayniysa
                        // Bu eski (veya kucuk) dosyayi sil, yeni buyuk olan yazilacak.
                        if (cStart >= startByte && cEnd <= endByte) {
                            std::filesystem::remove(entry.path());
                        }
                    }
                }
            }
        }
    } catch(...) {}
}

// Yeni: Mevcut cache dosyalarindan, istenen bolgenin baslangicini kapsayan en uygun cache dosyasini bulur.
// Eger kullanici 0-vSize istediyse ve 0-5MB varsa, 0-5MB'i kullanir.
inline std::string findBestCacheChunk(const std::string& urlHash, uint64_t startByte, uint64_t endByte, uint64_t& outCacheStart, uint64_t& outCacheEnd) {
    std::string bestFile = "";
    uint64_t bestSize = ULLONG_MAX;
    
    try {
        std::string cacheDir = getAppCacheDir();
        std::string prefix = "vid_" + urlHash + "_";
        
        for (const auto& entry : std::filesystem::directory_iterator(cacheDir)) {
            if (entry.is_regular_file() && entry.path().extension() == ".enc") {
                std::string filename = entry.path().filename().string();
                if (filename.find(prefix) == 0) {
                    std::string rest = filename.substr(prefix.length());
                    size_t underscore = rest.find('_');
                    size_t dot = rest.find(".enc");
                    if (underscore != std::string::npos && dot != std::string::npos) {
                        uint64_t cStart = std::stoull(rest.substr(0, underscore));
                        uint64_t cEnd = std::stoull(rest.substr(underscore + 1, dot - underscore - 1));
                        
                        // Eger bu dosya, aradigimiz araligin baslangicini (startByte) iceriyorsa
                        if (cStart <= startByte && cEnd >= startByte) {
                            uint64_t size = cEnd - cStart;
                            // En kucuk (en optimal) cache'i secelim
                            if (size < bestSize) {
                                bestSize = size;
                                bestFile = entry.path().string();
                                outCacheStart = cStart;
                                outCacheEnd = cEnd;
                            }
                        }
                    }
                }
            }
        }
    } catch(...) {}
    
    return bestFile;
}
