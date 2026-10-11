#pragma once

#include <string>
#include <vector>
#include <iostream>

class Downloader {
public:
    Downloader();
    ~Downloader();

    // Torrent mantığı gibi, dosyanın sadece belirli bir parçasını (chunk) indirir
    bool downloadChunk(const std::string& url, size_t startByte, size_t endByte, std::vector<uint8_t>& outBuffer);
    
    // Asla disk önbelleği kullanmadan doğrudan HuggingFace sunucusundan taze veri çeker
    bool downloadFresh(const std::string& url, std::vector<uint8_t>& outBuffer);

    // Bir .pack dosyasının kuyruğundaki (tail) gömülü JSON başlığını okumak için taze range isteği yapar
    bool downloadTailFresh(const std::string& url, size_t fileSize, size_t tailBytes, std::vector<uint8_t>& outBuffer);

    // Toplam dosya boyutunu öğrenmek için (böylece dataset.pack içindeki verilerin yerlerini haritalandırabiliriz)
    size_t getFileSize(const std::string& url);

private:
    static size_t writeCallback(void* contents, size_t size, size_t nmemb, void* userp);
};
