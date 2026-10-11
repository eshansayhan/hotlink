#pragma once
#include <string>
#include <thread>
#include <map>
#include <mutex>
#include <nlohmann/json.hpp>

struct VideoTarget {
    std::string packUrl;
    std::string packName;
    uint64_t offset;
    uint64_t size;
    std::string name;
    std::string id;
    std::string title;
    std::string category;
    std::string genre;
    std::string tags;
    std::string director;
    std::string cast;
    std::string year;
    std::string country;
    std::string audioLang;
    std::string imdb;
    std::string description;
    std::string backdrops;
    std::string coverUrl;
    uint64_t coverOffset = 0;
    uint64_t coverSize = 0;
    std::string coverMime = "image/jpeg";
    // Dizi & Seri Meta Bilgileri
    bool isSeries = false;
    std::string seriesTitle;
    int season = 1;
    int episode = 1;
    std::string episodeTitle;
};

class StreamServer {
public:
    StreamServer();
    ~StreamServer();
    
    void start(int port);
    void stop();
    
    std::string addVideo(const std::string& vName, const std::string& packUrl, uint64_t vOffset, uint64_t vSize, 
                         const std::string& vCategory = "Sinema & Film", const std::string& vImdb = "", const std::string& vDesc = "",
                         const std::string& customId = "", const std::string& vTitle = "", const std::string& vGenre = "",
                         const std::string& vTags = "", const std::string& vDirector = "", const std::string& vCast = "",
                         const std::string& vYear = "", const std::string& vCountry = "", const std::string& vAudioLang = "Türkçe Dublaj",
                         const std::string& vBackdrops = "", const std::string& vCover = "",
                         bool isSeries = false, const std::string& seriesTitle = "", int season = 1, int episode = 1,
                         const std::string& episodeTitle = "", const std::string& packName = "dataset.pack",
                         uint64_t coverOffset = 0, uint64_t coverSize = 0, const std::string& coverMime = "image/jpeg");
    void clearVideos();
    std::string searchVideos(const std::string& query);
    void setRefreshCallback(std::function<void()> cb) { onRefresh = cb; }

private:
    void run(int port);
    
    std::thread serverThread;
    bool isRunning;
    void* svr_ptr;
    
    std::map<std::string, VideoTarget> targets;
    std::mutex targetsMutex;
    std::function<void()> onRefresh;
    
};
