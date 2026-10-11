FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    PORT=7860 \
    M3U_STORE_PATH=/data/playlist-shares.json \
    HFVIDEO_API_URL=http://127.0.0.1:8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend_node/package.json backend_node/package-lock.json ./backend_node/
RUN npm ci --omit=dev --prefix ./backend_node

COPY ai_python/requirements.txt ./ai_python/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r ./ai_python/requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

COPY backend_node ./backend_node
COPY ai_python/src ./ai_python/src
COPY frontend ./frontend
COPY master_index.json robots.txt sitemap.xml ./
COPY docker-entrypoint.sh ./

RUN mkdir -p /data && chown -R node:node /app /data

USER node

EXPOSE 7860

CMD ["bash", "/app/docker-entrypoint.sh"]
