import sys
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.video_metadata import (
    EMBED_HTML_FILE,
    load_embed_config,
    save_embed_config,
    parse_video_metadata,
)

from app import access_store

catalog_router = APIRouter()


def _get_main():
    return sys.modules.get("app.main")


def _require_authenticated(request: Request):
    """Katalog listelemesi herkes için açıktır."""
    return


@catalog_router.get("/api/monetization")
def serve_monetization_config():
    return {"enabled": False}


@catalog_router.get("/api/v2/mesh_cluster_map.json")
def serve_mesh_cluster_map():
    return {"status": "ok", "nodes": []}


@catalog_router.get("/api/config/embed")
async def get_embed_configuration():
    """Ayar dosyasını görüntüler (Aktif/Pasif, İzin Verilen Domainler, Watermark)"""
    return load_embed_config()


@catalog_router.post("/api/config/embed")
async def update_embed_configuration(request: Request):
    """Ayar dosyasını günceller"""
    try:
        body = await request.json()
        current = load_embed_config()
        current.update(body)
        current["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_embed_config(current)
        return {"status": "success", "message": "Embed ayar dosyası başarıyla güncellendi", "config": current}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@catalog_router.get("/api/catalog")
@catalog_router.get("/api/safetensors/videos")
@catalog_router.get("/api/series/videos")
async def list_all_video_apis(
    request: Request,
    search: str = "",
    season: int = 0,
    _: None = Depends(_require_authenticated),
):
    """safetensors içindeki tüm videoların otomatik API kataloğunu listeler"""
    # §2 & §5 & §6 dost.md: Masaüstü veya Yurt Dışı ise boş döner
    from app.routers.auth import is_mobile_request
    from app.admin_service import _admin_session
    
    is_admin = _admin_session(request) is not None
    if not is_admin:
        if not is_mobile_request(request):
            return {"total": 0, "sources": [], "embed_enabled": False, "videos": []}
        country = (
            getattr(request.state, "content_country", None)
            or request.headers.get("cf-ipcountry")
            or request.headers.get("x-country")
            or ""
        ).upper()
        if country and country != "TR":
            return {"total": 0, "sources": [], "embed_enabled": False, "videos": []}

    main_mod = _get_main()
    cfg_fn = getattr(main_mod, "load_embed_config", load_embed_config)
    meta_fn = getattr(main_mod, "parse_video_metadata", parse_video_metadata)
    cfg = cfg_fn()
    source_files = await run_in_threadpool(main_mod.discover_safetensors_files)

    results = []
    for source_file in source_files:
        _, header_obj, _ = await main_mod._get_safetensors_index_async(source_file)
        video_keys = sorted(
            key for key, value in header_obj.items()
            if key.startswith("video_")
            and isinstance(value, dict)
            and isinstance(value.get("data_offsets"), list)
            and len(value["data_offsets"]) == 2
        )
        for idx, v_key in enumerate(video_keys):
            offsets = header_obj[v_key]["data_offsets"]
            size_bytes = offsets[1] - offsets[0]
            meta = meta_fn(v_key, idx, size_bytes, request, source_file, header_obj=header_obj)

            if season > 0 and meta.get("season") != season:
                continue
            if search:
                q = search.lower()
                if q not in meta["title"].lower() and q not in meta["description"].lower() and q not in meta.get("series_title", "").lower():
                    continue
            results.append(meta)

    return {
        "total": len(results),
        "sources": source_files,
        "embed_enabled": cfg.get("embed_enabled", True),
        "videos": results,
    }


@catalog_router.get("/api/video/{tensor_name}")
async def get_single_video_api(
    tensor_name: str,
    request: Request,
    source_file: str = "",
    _: None = Depends(_require_authenticated),
):
    from app.routers.auth import is_mobile_request
    from app.admin_service import _admin_session
    if not _admin_session(request):
        if not is_mobile_request(request):
            raise HTTPException(status_code=404, detail="Video bulunamadı")
        country = (
            getattr(request.state, "content_country", None)
            or request.headers.get("cf-ipcountry")
            or request.headers.get("x-country")
            or ""
        ).upper()
        if country and country != "TR":
            raise HTTPException(status_code=404, detail="Video bulunamadı")

    main_mod = _get_main()
    cfg_fn = getattr(main_mod, "load_embed_config", load_embed_config)
    meta_fn = getattr(main_mod, "parse_video_metadata", parse_video_metadata)
    cfg = cfg_fn()
    source_file, header_obj, _ = await main_mod._get_safetensors_index_async(source_file)
    t_name = main_mod.resolve_tensor_name(tensor_name, header_obj, "video")
    t_info = header_obj.get(t_name)
    if not t_info:
        raise HTTPException(status_code=404, detail="Video bulunamadı")

    video_keys = sorted([k for k in header_obj.keys() if k.startswith("video_")])
    idx = video_keys.index(t_name) if t_name in video_keys else 0
    offsets = t_info["data_offsets"]
    size_bytes = offsets[1] - offsets[0]

    meta = meta_fn(t_name, idx, size_bytes, request, source_file, header_obj=header_obj)
    meta["embed_allowed"] = cfg.get("embed_enabled", True)
    return meta


@catalog_router.get("/embed/{tensor_name}", response_class=HTMLResponse)
async def serve_embed_player(tensor_name: str, request: Request, source_file: str = ""):
    """Mobil, Android TV, PC ve WebView uyumlu hafif evrensel Embed oynatıcı sayfası"""
    from app.routers.access import _active_access
    if not _active_access(request):
        return HTMLResponse(
            "<div style='color:#fff;text-align:center;padding:40px;background:#000;height:100vh'>Lütfen giriş yapın.</div>",
            status_code=403,
        )
    main_mod = _get_main()
    cfg_fn = getattr(main_mod, "load_embed_config", load_embed_config)
    meta_fn = getattr(main_mod, "parse_video_metadata", parse_video_metadata)
    cfg = cfg_fn()
    embed_enabled = cfg.get("embed_enabled", True)

    allowed_domains = cfg.get("allowed_domains", ["*"])
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain_allowed = True
    if allowed_domains and "*" not in allowed_domains:
        domain_allowed = any(d.lower() in origin.lower() for d in allowed_domains)

    source_file, header_obj, _ = await main_mod._get_safetensors_index_async(source_file)
    t_name = main_mod.resolve_tensor_name(tensor_name, header_obj, "video")
    t_info = header_obj.get(t_name)
    if not t_info:
        return HTMLResponse("<h3 style='color:#fff;text-align:center;padding:40px'>Video bulunamadı</h3>", status_code=404)

    video_keys = sorted([k for k in header_obj.keys() if k.startswith("video_")])
    idx = video_keys.index(t_name) if t_name in video_keys else 0
    offsets = t_info["data_offsets"]
    size_bytes = offsets[1] - offsets[0]
    meta = meta_fn(t_name, idx, size_bytes, request, source_file, header_obj=header_obj)

    if EMBED_HTML_FILE.exists():
        tpl = EMBED_HTML_FILE.read_text(encoding="utf-8")
    else:
        tpl = "<html><body style='margin:0;background:#000'><video src='{{STREAM_URL}}' controls playsinline style='width:100%;height:100%'></video></body></html>"

    if not embed_enabled or not domain_allowed:
        reason_msg = "Bu video için harici web sitelerinde oynatma (Embed) ayar dosyasından kapatılmıştır." if not embed_enabled else f"Bu alan adı ({origin}) için embed izni bulunmamaktadır."
        disabled_html = f'''
        <div class="disabled-container">
          <div class="disabled-icon">🔒</div>
          <div class="disabled-title">Embed Oynatıcı Devre Dışı</div>
          <div class="disabled-desc">{reason_msg}</div>
          <a href="/eshanio" class="btn-primary" target="_blank">Ana Platformda İzle</a>
        </div>
        '''
        tpl = tpl.replace("{{DISABLED_BLOCK}}", disabled_html)
        tpl = tpl.replace("{{PLAYER_STYLE}}", "display:none !important")
    else:
        tpl = tpl.replace("{{DISABLED_BLOCK}}", "")
        tpl = tpl.replace("{{PLAYER_STYLE}}", "")

    tpl = tpl.replace("{{TITLE}}", meta["title"])
    tpl = tpl.replace("{{STREAM_URL}}", meta["stream_url"])
    tpl = tpl.replace("{{POSTER_URL}}", meta["cover_url"])
    tpl = tpl.replace("{{WATERMARK_URL}}", cfg.get("watermark_url", "https://www.tiktok.com/@eshansayhan"))
    tpl = tpl.replace("{{WATERMARK_TEXT}}", cfg.get("watermark_text", "HFStream"))
    tpl = tpl.replace("{{EMBED_IFRAME_CODE}}", meta["embed_code"])

    return HTMLResponse(content=tpl, status_code=200)
