# ==============================================================================
# 24/7 YouTube Live Streaming System - Dockerfile
# Optimized for Hugging Face Spaces & Production Containers
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files & enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=7860 \
    PYTHONPATH=/app

# Install system dependencies & FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Verify FFmpeg installation
RUN ffmpeg -version

# Set working directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install the independent Eshanio Node API used by the M3U manager.
COPY eshanio/hf_video_platform/backend_node/package.json \
     eshanio/hf_video_platform/backend_node/package-lock.json \
     /app/eshanio/hf_video_platform/backend_node/
RUN npm ci --omit=dev --prefix /app/eshanio/hf_video_platform/backend_node

# Create non-root user (Standard for Hugging Face Spaces)
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/videos /app/logs /data && \
    chown -R appuser:appuser /app /data

# Copy application source code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Hugging Face Spaces default port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# Start the streaming app, Eshanio video API and M3U API.
CMD ["bash", "/app/docker-entrypoint.sh"]
