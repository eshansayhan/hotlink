#!/usr/bin/env bash
set -u

cd /app/ai_python
uvicorn src.main:app --host 127.0.0.1 --port 8080 &
video_api_pid=$!

cd /app
node backend_node/server.js &
web_api_pid=$!

shutdown() {
    trap - TERM INT
    kill "$video_api_pid" "$web_api_pid" 2>/dev/null || true
    wait "$video_api_pid" 2>/dev/null || true
    wait "$web_api_pid" 2>/dev/null || true
}

trap shutdown TERM INT
wait -n "$video_api_pid" "$web_api_pid"
status=$?
shutdown
exit "$status"
