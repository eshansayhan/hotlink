#include <iostream>
#include <string>
#include <vector>
#include "Downloader.h"
#include <nlohmann/json.hpp>

int main() {
    Downloader d;
    std::vector<uint8_t> buf;
    if (d.downloadChunk("https://huggingface.co/datasets/eshansayhan/movie/resolve/main/master_index.json", 0, 1024*1024, buf)) {
        std::string s(buf.begin(), buf.end());
        std::cout << "RAW: \n" << s << "\n";
        try { nlohmann::json::parse(s); std::cout << "PARSE OK\n"; }
        catch (std::exception& e) { std::cout << "PARSE FAIL: " << e.what() << "\n"; }
    } else { std::cout << "DOWNLOAD FAIL\n"; }
}
