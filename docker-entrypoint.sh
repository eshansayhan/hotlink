#!/usr/bin/env bash
set -u

export M3U_SERVICE_URL="${M3U_SERVICE_URL:-http://127.0.0.1:3000}"
export HFVIDEO_API_URL="${HFVIDEO_API_URL:-http://127.0.0.1:8080}"
export M3U_STORE_PATH="${M3U_STORE_PATH:-/data/playlist-shares.json}"
app_port="${PORT:-7860}"

mkdir -p "$(dirname "$M3U_STORE_PATH")"

python -m uvicorn src.main:app \
    --app-dir /app/eshanio/hf_video_platform/ai_python \
    --host 127.0.0.1 \
    --port 8080 &
video_api_pid=$!

PORT=3000 node /app/eshanio/hf_video_platform/backend_node/server.js &
m3u_api_pid=$!

uvicorn app.main:app --host 0.0.0.0 --port "$app_port" &
streamer_api_pid=$!

shutdown() {
    trap - TERM INT
    kill "$video_api_pid" "$m3u_api_pid" "$streamer_api_pid" 2>/dev/null || true
    wait "$video_api_pid" 2>/dev/null || true
    wait "$m3u_api_pid" 2>/dev/null || true
    wait "$streamer_api_pid" 2>/dev/null || true
}

trap shutdown TERM INT
wait -n "$video_api_pid" "$m3u_api_pid" "$streamer_api_pid"
status=$?
shutdown
exit "$status"
