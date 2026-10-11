import json
import math
import re
from pathlib import Path
from urllib.parse import quote
from fastapi import Request

EMBED_CONFIG_FILE = Path(__file__).resolve().parent / "embed_config.json"
EMBED_HTML_FILE = Path(__file__).resolve().parent / "embed_player.html"


def load_embed_config() -> dict:
    if EMBED_CONFIG_FILE.exists():
        try:
            return json.loads(EMBED_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "embed_enabled": True,
        "api_enabled": True,
        "allowed_domains": ["*"],
        "watermark_enabled": True,
        "watermark_text": "HFStream",
        "watermark_url": "https://www.tiktok.com/@eshansayhan",
        "player_theme": "cyber_dark",
        "auto_play": False,
        "allow_fullscreen": True,
        "hardware_acceleration": True,
    }


def save_embed_config(cfg: dict) -> None:
    EMBED_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_video_metadata(
    t_name: str,
    index: int,
    size_bytes: int,
    request: Request = None,
    source_file: str = "",
    header_obj: dict = None,
    get_index_func=None,
) -> dict:
    if header_obj is None and source_file:
        try:
            if get_index_func:
                _, header_obj, _ = get_index_func(source_file)
            else:
                from app import main
                _, header_obj, _ = main.get_safetensors_index(source_file)
        except Exception:
            header_obj = {}
    elif header_obj is None:
        header_obj = {}

    manifest = {}
    metadata_entry = header_obj.get("__metadata__")
    if isinstance(metadata_entry, dict) and "packmanager_manifest" in metadata_entry:
        try:
            manifest = json.loads(metadata_entry["packmanager_manifest"])
        except Exception:
            manifest = {}

    mv = {}
    if isinstance(manifest.get("videos"), list):
        for item in manifest["videos"]:
            if isinstance(item, dict) and item.get("video_tensor") == t_name:
                mv = item
                break
        if not mv and index < len(manifest["videos"]):
            item = manifest["videos"][index]
            if isinstance(item, dict):
                mv = item

    package_info = manifest.get("package", {}) if isinstance(manifest.get("package"), dict) else {}
    package_title = str(package_info.get("title") or "").strip()
    if not package_title and source_file:
        package_title = Path(source_file).stem.replace("_", " ").replace(".", " ").strip()

    raw_title = str(mv.get("title") or mv.get("video_filename") or "").strip()
    if not raw_title:
        raw_title = f"{package_title} {index + 1}" if package_title else f"Video {index + 1}"

    desc = str(mv.get("description") or "").strip()
    category_raw = str(mv.get("category") or "").strip()
    collection_raw = str(mv.get("collection") or "").strip()

    season = None
    episode = None
    series_candidate = ""

    se_match = re.search(r'(?i)\bS(\d{1,2})[\s._-]*E(\d{1,3})\b', raw_title)
    if not se_match and desc:
        se_match = re.search(r'(?i)\bS(\d{1,2})[\s._-]*E(\d{1,3})\b', desc)

    if not se_match:
        se_match = re.search(r'(?i)\b(\d{1,2})x(\d{1,3})\b', raw_title)

    if not se_match:
        se_match = re.search(r'(?i)(\d{1,2})\s*\.?\s*(?:sezon|season)[\s._-]*(\d{1,3})\s*\.?\s*(?:bölüm|bolum|episode|ep)\b', raw_title)

    ep_only_match = None
    if not se_match:
        ep_only_match = re.search(r'(?i)(?:bölüm|bolum|episode|ep)[\s._-]*(\d{1,3})\b', raw_title)

    if se_match:
        season = int(se_match.group(1))
        episode = int(se_match.group(2))
        series_candidate = raw_title[:se_match.start()].strip(" ._-\t")
    elif ep_only_match:
        season = 1
        episode = int(ep_only_match.group(1))
        series_candidate = raw_title[:ep_only_match.start()].strip(" ._-\t")

    if season is None and source_file:
        s_dir_match = re.search(r'(?i)season[-_]?(\d+)', source_file)
        if s_dir_match:
            season = int(s_dir_match.group(1))
            episode = index + 1

    is_series = False
    if season is not None and episode is not None:
        is_series = True
    elif category_raw.lower() in {"dizi", "series"} or (collection_raw and collection_raw.lower() not in {"genel", "default"}):
        is_series = True
        season = season or 1
        episode = episode or (index + 1)
        series_candidate = collection_raw or package_title

    def clean_name(txt: str) -> str:
        txt = re.sub(r'(?i)\.(mp4|mkv|avi|webm|mov|safetensors)$', '', txt)
        txt = re.sub(r'(?i)\b(1080p|720p|2160p|4k|bluray|bdrip|web-?dl|webrip|hdrip|x264|x265|hevc|rarbg|aac|dts|ddp5\.1|dual|multi)\b.*$', '', txt)
        txt = re.sub(r'[._]+', ' ', txt)
        return re.sub(r'\s+', ' ', txt).strip(' -_')

    if is_series:
        series_title = clean_name(series_candidate or collection_raw or package_title or "Dizi")
        if not series_title:
            series_title = "Dizi"
        title = f"{series_title} - {season}. Sezon {episode}. Bölüm"
        category = "Dizi"
    else:
        series_title = ""
        season = 0
        episode = 0
        title = clean_name(raw_title)
        if not title:
            title = f"Video {index + 1}"
        category = "Film" if (category_raw.lower() in {"film", "movie", "sinema"} or not category_raw or category_raw.lower() == "genel") else category_raw

    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', raw_title) or re.search(r'\b(19\d{2}|20\d{2})\b', desc)
    year = year_match.group(1) if year_match else "2024"
    if "game of thrones" in title.lower():
        year = {1: "2011", 2: "2012", 3: "2013", 4: "2014", 5: "2015", 6: "2016", 7: "2017", 8: "2019"}.get(season, "2011")
        imdb = "9.2"
    else:
        imdb = "8.4" if is_series else "7.8"

    quality = "1080p BluRay"
    if re.search(r'(?i)\b(2160p|4k)\b', raw_title):
        quality = "4K Ultra HD"
    elif re.search(r'(?i)\b720p\b', raw_title):
        quality = "720p HD"

    source_label = source_file or "Safetensors"
    if not desc:
        if is_series:
            desc = f"{series_title} {season}. Sezon {episode}. Bölüm. {source_label} kaynağından 1080p kalitesinde sunulmaktadır."
        else:
            desc = f"{title}. {source_label} kaynağından doğrudan sunulmaktadır."

    k = 1024
    sizes = ["B", "KB", "MB", "GB", "TB"]
    if size_bytes > 0:
        i = int(math.floor(math.log(size_bytes) / math.log(k)))
        size_fmt = f"{size_bytes / (k ** i):.2f} {sizes[i]}"
    else:
        size_fmt = "0 B"

    if request:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme or "https")
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        base_url = f"{proto}://{host}".rstrip("/")
    else:
        base_url = ""

    source_query = f"?source_file={quote(source_file, safe='')}" if source_file else ""
    video_id = f"{source_file}::{t_name}" if source_file else t_name
    stream_url = f"{base_url}/api/stream/{quote(t_name, safe='')}{source_query}"
    embed_url = f"{base_url}/embed/{quote(t_name, safe='')}{source_query}"
    api_url = f"{base_url}/api/video/{quote(t_name, safe='')}{source_query}"
    cover_t_name = t_name.replace("video_", "cover_", 1) if t_name.startswith("video_") else t_name
    cover_url = f"{base_url}/api/cover/{quote(cover_t_name, safe='')}{source_query}"
    embed_code = f'<iframe src="{embed_url}" width="100%" height="100%" frameborder="0" allowfullscreen allow="autoplay; fullscreen; encrypted-media; picture-in-picture"></iframe>'

    return {
        "id": video_id,
        "source_type": "safetensors",
        "tensor": t_name,
        "safetensors_file": source_file,
        "index": index,
        "title": title,
        "series_title": series_title,
        "is_series": is_series,
        "season": season,
        "episode": episode,
        "year": year,
        "quality": quality,
        "codec": "H.264 / HEVC (hvc1)",
        "imdb": imdb,
        "category": category,
        "content_type": "dizi" if is_series else "film",
        "description": desc,
        "size_bytes": size_bytes,
        "size_fmt": size_fmt,
        "cover": cover_url,
        "cover_url": cover_url,
        "stream_url": stream_url,
        "embed_url": embed_url,
        "api_url": api_url,
        "embed_code": embed_code,
    }
