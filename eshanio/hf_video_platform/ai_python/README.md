---
title: HFVideoPlatform Video API
emoji: 📺
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# HFVideoPlatform Video API

This Hugging Face Space exposes the public video catalog stored in a Hugging Face
Dataset as JSON and serves each video and embedded thumbnail through HTTP byte-range
endpoints. Copy the contents of `ai_python` to the root of a Docker-based Space.

## Endpoints

- `GET /health` — service health
- `GET /api/videos` — video cards as a JSON array
- `GET /api/videos/{video_id}` — one video card
- `GET /api/videos/{video_id}/stream` — MP4 stream with byte-range support
- `GET /api/converted?source_file=...&tensor=...` — converted H.264/AAC MP4 with byte-range support
- `GET /api/transcode/status` — last batch conversion status
- `GET /api/videos/{video_id}/thumbnail` — embedded/external thumbnail or placeholder

Each catalog entry includes `id`, `title`, `thumbnail_url`, and `stream_url`. The
stream endpoint translates the player's byte ranges to the video byte range inside
the Hugging Face `.pack` file, so clients do not need to understand the pack format.

## Configuration

The default data source is the public `eshansayhan/movie` dataset and its
`master_index.json`. Set these Space variables if the dataset location changes:

- `HF_DATASET_REPO` — dataset repository in `owner/name` format
- `HF_DATASET_REVISION` — dataset branch or revision (default: `main`)
- `HF_MASTER_INDEX_URL` — optional complete URL to `master_index.json`
- `VIDEO_CACHE_TTL_SECONDS` — catalog cache lifetime (default: `60`)

For a private dataset, add `HF_TOKEN` as a Space secret. It is sent only by the API
server to Hugging Face; clients receive the Space API URLs, not the token. The default
public dataset does not require a token.

## Safetensors H.264/AAC batch conversion

The batch converter reads video tensor offsets from each `.safetensors` header,
downloads only those byte ranges, and creates MP4 files encoded as H.264 (`libx264`)
and AAC. Its adaptive encoding profile uses source resolution and bitrate to select
the H.264 CRF; files without an audio track receive a silent AAC track. The output
index is written atomically, and completed files are skipped on later runs unless
their source fingerprint changes.

Run the whole dataset batch from the `ai_python` directory:

```sh
python -m src.transcode
```

The default output directory is `/data/hfvideo_converted`. Mount persistent storage
there before running the batch; container-local files are lost when an ephemeral
Space restarts. Set `TRANSCODE_OUTPUT_DIR` to another persistent volume if needed.
The source repository and revision default to `HF_DATASET_REPO` and
`HF_DATASET_REVISION`; override them with `SAFETENSORS_DATASET_REPO` and
`SAFETENSORS_DATASET_REVISION`. `HF_TOKEN` is reused for private repositories.
`FFMPEG_BIN`, `FFPROBE_BIN`, and `TRANSCODE_TIMEOUT_SECONDS` can override the
installed tools and per-file timeout.

The player requests a converted file only after the batch has produced it. While a
conversion is missing, the converted endpoint returns `503`; check the status endpoint
and rerun the batch to retry failed assets.
