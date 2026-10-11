#include "Downloader.h"
#include <curl/curl.h>
#include <filesystem>
#include <fstream>
#include <functional>
#include "Config.h"
#include <functional>

Downloader::Downloader() {
    curl_global_init(CURL_GLOBAL_ALL);
}

Downloader::~Downloader() {
    curl_global_cleanup();
}

size_t Downloader::writeCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    size_t realsize = size * nmemb;
    auto* mem = static_cast<std::vector<uint8_t>*>(userp);
    
    auto* data = static_cast<uint8_t*>(contents);
    mem->insert(mem->end(), data, data + realsize);
    
    return realsize;
}

size_t Downloader::getFileSize(const std::string& url) {
    CURL* curl = curl_easy_init();
    double filesize = 0.0;
    
    if (curl) {
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_NOBODY, 1L); // Sadece başlıkları al (body'yi indirme)
        curl_easy_setopt(curl, CURLOPT_HEADER, 0L);
        curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L); // Yönlendirmeleri takip et (Hugging Face CDN için şart)
        
        CURLcode res = curl_easy_perform(curl);
        if (res == CURLE_OK) {
            curl_easy_getinfo(curl, CURLINFO_CONTENT_LENGTH_DOWNLOAD, &filesize);
        } else {
            std::cerr << "curl_easy_perform() failed: " << curl_easy_strerror(res) << std::endl;
        }
        curl_easy_cleanup(curl);
    }
    return static_cast<size_t>(filesize);
}

bool Downloader::downloadChunk(const std::string& url, size_t startByte, size_t endByte, std::vector<uint8_t>& outBuffer) {
    // Cache dizinini APPDATA altinda olustur/getir
    std::string cacheDir = getAppCacheDir();

    // Cache dosyasi adini olustur
    std::string cacheKey = url + "_" + std::to_string(startByte) + "_" + std::to_string(endByte);
    size_t hash = std::hash<std::string>{}(cacheKey);
    std::string cachePath = cacheDir + "\\chunk_" + std::to_string(hash) + ".bin";

    // Reuse locally cached chunks when available.
    if (std::filesystem::exists(cachePath)) {
        std::ifstream file(cachePath, std::ios::binary | std::ios::ate);
        if (file.is_open()) {
            std::streamsize size = file.tellg();
            file.seekg(0, std::ios::beg);
            outBuffer.resize(size);
            if (file.read(reinterpret_cast<char*>(outBuffer.data()), size)) {
                return true; // Cache'den basariyla okundu
            }
        }
    }

    // Cache'de yoksa internetten / agdan indir
    CURL* curl = curl_easy_init();
    if (!curl) return false;

    std::string range = std::to_string(startByte) + "-" + std::to_string(endByte);

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_RANGE, range.c_str()); 
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, writeCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &outBuffer);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        std::cerr << "Download failed: " << curl_easy_strerror(res) << std::endl;
        return false;
    }

    // Cache the downloaded chunk for local reuse.
    if (!outBuffer.empty()) {
        std::ofstream file(cachePath, std::ios::binary);
        if (file.is_open()) {
            file.write(reinterpret_cast<const char*>(outBuffer.data()), outBuffer.size());
        }
    }

    return true;
}

bool Downloader::downloadFresh(const std::string& url, std::vector<uint8_t>& outBuffer) {
    CURL* curl = curl_easy_init();
    if (!curl) return false;

    // Cache buster parametresi (Hugging Face ve ara proxy önbelleğini kesin olarak atla)
    std::string noCacheUrl = url;
    auto now = std::chrono::system_clock::now().time_since_epoch().count();
    noCacheUrl += (url.find('?') == std::string::npos ? "?_t=" : "&_t=") + std::to_string(now);

    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Cache-Control: no-cache, no-store, must-revalidate");
    headers = curl_slist_append(headers, "Pragma: no-cache");
    headers = curl_slist_append(headers, "Expires: 0");

    curl_easy_setopt(curl, CURLOPT_URL, noCacheUrl.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_FRESH_CONNECT, 1L);
    curl_easy_setopt(curl, CURLOPT_FORBID_REUSE, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, writeCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &outBuffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 15L);

    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        std::cerr << "[Downloader] Fresh download failed: " << curl_easy_strerror(res) << std::endl;
        return false;
    }
    return !outBuffer.empty();
}

bool Downloader::downloadTailFresh(const std::string& url, size_t fileSize, size_t tailBytes, std::vector<uint8_t>& outBuffer) {
    if (fileSize < 8) return false;
    if (tailBytes > fileSize) tailBytes = fileSize;
    size_t startByte = fileSize - tailBytes;
    size_t endByte = fileSize - 1;

    CURL* curl = curl_easy_init();
    if (!curl) return false;

    std::string rangeStr = std::to_string(startByte) + "-" + std::to_string(endByte);

    std::string noCacheUrl = url;
    auto now = std::chrono::system_clock::now().time_since_epoch().count();
    noCacheUrl += (url.find('?') == std::string::npos ? "?_t=" : "&_t=") + std::to_string(now);

    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Cache-Control: no-cache, no-store, must-revalidate");
    headers = curl_slist_append(headers, "Pragma: no-cache");

    curl_easy_setopt(curl, CURLOPT_URL, noCacheUrl.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_FRESH_CONNECT, 1L);
    curl_easy_setopt(curl, CURLOPT_FORBID_REUSE, 1L);
    curl_easy_setopt(curl, CURLOPT_RANGE, rangeStr.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, writeCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &outBuffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 15L);

    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        std::cerr << "[Downloader] downloadTailFresh failed for " << url << ": " << curl_easy_strerror(res) << std::endl;
        return false;
    }
    return !outBuffer.empty();
}
