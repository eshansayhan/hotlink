cmake_minimum_required(VERSION 3.14)
project(HFVideoPlatform)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

include(FetchContent)

# =====================================================
# 1. libcurl (HTTP/HTTPS indirme + streaming)
# =====================================================
FetchContent_Declare(
    curl
    URL https://github.com/curl/curl/releases/download/curl-8_10_1/curl-8.10.1.tar.gz
)
set(CURL_DISABLE_DICT ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_FILE ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_FTP  ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_GOPHER ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_IMAP ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_LDAP ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_LDAPS ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_POP3 ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_RTSP ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_SMB  ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_SMTP ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_TELNET ON CACHE BOOL "" FORCE)
set(CURL_DISABLE_TFTP ON CACHE BOOL "" FORCE)
set(BUILD_TESTING     OFF CACHE BOOL "" FORCE)
set(BUILD_CURL_EXE    OFF CACHE BOOL "" FORCE)
set(CURL_USE_SCHANNEL ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(curl)

# =====================================================
# 2. cpp-httplib (header-only HTTP/S sunucu — StreamServer icin)
# =====================================================
FetchContent_Declare(
    httplib
    GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
    GIT_TAG        v0.16.0
)
set(HTTPLIB_USE_OPENSSL_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_COMPILE OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(httplib)

# =====================================================
# 3. nlohmann/json (JSON parse)
# =====================================================
FetchContent_Declare(
    nlohmann_json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
)
FetchContent_MakeAvailable(nlohmann_json)

# =====================================================
# 4. Frontend gomme: index.html -> embedded_frontend.h
#    (CMake configure zamaninda .ps1 dosyasi calistirilir)
# =====================================================
file(MAKE_DIRECTORY "${CMAKE_SOURCE_DIR}/src/embedded")

execute_process(
    COMMAND powershell -ExecutionPolicy Bypass
        -File "${CMAKE_SOURCE_DIR}/tools/embed_frontend.ps1"
        "${CMAKE_SOURCE_DIR}/../frontend/index.html"
        "${CMAKE_SOURCE_DIR}/src/embedded/embedded_frontend.h"
    RESULT_VARIABLE EMBED_RESULT
    OUTPUT_VARIABLE EMBED_OUT
    ERROR_VARIABLE  EMBED_ERR
)
if(EMBED_RESULT EQUAL 0)
    message(STATUS "Frontend gomuldu: src/embedded/embedded_frontend.h")
else()
    message(WARNING "embed_frontend.ps1 hata verdi: ${EMBED_ERR}")
    message(WARNING "Mevcut embedded_frontend.h kullanilacak (varsa).")
endif()

# =====================================================
# 5. HFVideoPlatform.exe  — Ana Calistirabilir
# =====================================================
set(HTTPLIB_HEADER_DIR "${httplib_SOURCE_DIR}")

add_executable(HFVideoPlatform
    src/main.cpp
    src/downloader/Downloader.cpp
    src/stream/StreamServer.cpp
    res/app.rc
)

target_include_directories(HFVideoPlatform PRIVATE
    src
    src/utils
    src/stream
    src/downloader
    src/embedded
    "${HTTPLIB_HEADER_DIR}"
)

target_link_libraries(HFVideoPlatform PRIVATE
    libcurl
    nlohmann_json::nlohmann_json
    ws2_32
    crypt32
    advapi32
    ole32
    shell32
    shlwapi
    user32
    version
)

# =====================================================
# POST_BUILD: Gerekli DLL'leri Release klasorune kopyala
# =====================================================
add_custom_command(TARGET HFVideoPlatform POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$<TARGET_FILE:libcurl>"
        "$<TARGET_FILE_DIR:HFVideoPlatform>"
    COMMENT "libcurl.dll kopyalaniyor..."
)

# =====================================================
# 6. PackManager.exe
# =====================================================
FetchContent_Declare(
    glfw
    GIT_REPOSITORY https://github.com/glfw/glfw.git
    GIT_TAG        3.3.8
)
set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_DOCS     OFF CACHE BOOL "" FORCE)
set(GLFW_INSTALL        OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(glfw)

FetchContent_Declare(
    imgui
    GIT_REPOSITORY https://github.com/ocornut/imgui.git
    GIT_TAG        v1.89.9
)
FetchContent_MakeAvailable(imgui)

add_executable(PackManager
    src/pack/PackManager.cpp
    src/downloader/Downloader.cpp
    ${imgui_SOURCE_DIR}/imgui.cpp
    ${imgui_SOURCE_DIR}/imgui_draw.cpp
    ${imgui_SOURCE_DIR}/imgui_tables.cpp
    ${imgui_SOURCE_DIR}/imgui_widgets.cpp
    ${imgui_SOURCE_DIR}/backends/imgui_impl_glfw.cpp
    ${imgui_SOURCE_DIR}/backends/imgui_impl_opengl3.cpp
    res/pack.rc
)

target_include_directories(PackManager PRIVATE
    src
    src/utils
    src/pack
    src/downloader
    ${imgui_SOURCE_DIR}
    ${imgui_SOURCE_DIR}/backends
    ${glfw_SOURCE_DIR}/include
)

target_link_libraries(PackManager PRIVATE
    glfw
    opengl32
    comdlg32
    libcurl
    ws2_32
    crypt32
    advapi32
    nlohmann_json::nlohmann_json
)

if(MSVC)
    target_compile_options(PackManager PRIVATE /utf-8)
    target_compile_options(HFVideoPlatform PRIVATE /utf-8)
endif()

add_custom_command(TARGET PackManager POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$<TARGET_FILE:glfw>"
        "$<TARGET_FILE_DIR:PackManager>"
    COMMENT "glfw3.dll kopyalaniyor..."
)
