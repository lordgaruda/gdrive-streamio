"""
Google Drive video streaming proxy with Range support for Stremio.
Uses redirect-to-CDN approach: instead of proxying every byte through Heroku,
we resolve Google's temporary CDN URL and redirect the player there.
Google's CDN handles Range requests, Content-Type, etc. natively.
Falls back to proxying only if redirect resolution fails.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse, RedirectResponse
import httpx
import pickle
import logging
import asyncio
import time
from Backend import db
from google.auth.transport.requests import Request as GRequest

router = APIRouter(tags=["GDrive Streaming"])
log = logging.getLogger("gdrive_stream")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Range, Content-Type, Authorization",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
}

# Cache CDN URLs — they're valid for ~30 min
_cdn_cache: dict[str, tuple[str, float]] = {}
CDN_CACHE_TTL = 1500  # 25 minutes (conservative)

# Reusable httpx client for metadata / redirect resolution
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            follow_redirects=False,  # We need to capture redirect URLs
        )
    return _client


async def get_fresh_token() -> str:
    """Load credentials from MongoDB, refresh if needed, return access token."""
    raw = await db.load_gdrive_token()
    if not raw:
        raise RuntimeError("Google Drive credentials not configured")
    creds = pickle.loads(raw)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        await db.update_gdrive_token_after_refresh(pickle.dumps(creds))
    return creds.token


async def _resolve_cdn_url(file_id: str) -> str | None:
    """
    Resolve a temporary Google CDN URL for the file.
    Google Drive API redirects alt=media requests to *.googleusercontent.com
    which supports Range requests natively and doesn't need auth.
    """
    cached = _cdn_cache.get(file_id)
    if cached and time.time() - cached[1] < CDN_CACHE_TTL:
        return cached[0]

    token = await get_fresh_token()
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
    client = _get_client()

    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (302, 303, 307, 308):
            cdn_url = resp.headers.get("Location")
            if cdn_url:
                _cdn_cache[file_id] = (cdn_url, time.time())
                log.info(f"Resolved CDN URL for {file_id}")
                return cdn_url
        log.warning(f"No redirect for {file_id}, status={resp.status_code}")
    except Exception as e:
        log.error(f"CDN resolve failed for {file_id}: {e}")

    return None


def _resolve_mime(meta: dict) -> str:
    """Resolve MIME type from GDrive metadata, falling back to extension."""
    mime_type = meta.get("mimeType", "video/mp4")
    if mime_type == "application/octet-stream":
        name = meta.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        mime_map = {
            "mkv": "video/x-matroska", "mp4": "video/mp4",
            "avi": "video/x-msvideo", "webm": "video/webm",
            "ts": "video/mp2t", "m4v": "video/mp4",
        }
        mime_type = mime_map.get(ext, "video/mp4")
    return mime_type


@router.options("/dl/{file_id}/video.mkv")
async def stream_options(file_id: str):
    """Handle CORS preflight from Stremio Web (browser)."""
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mkv")
async def stream_head(file_id: str):
    """
    Stremio probes with HEAD before playback.
    Try redirect to CDN first; fall back to metadata-based response.
    """
    # Try CDN redirect — Google's CDN responds to HEAD natively
    cdn_url = await _resolve_cdn_url(file_id)
    if cdn_url:
        return Response(
            status_code=302,
            headers={"Location": cdn_url, **CORS_HEADERS},
        )

    # Fallback: return metadata-based HEAD response
    token = await get_fresh_token()
    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size,mimeType,name&supportsAllDrives=true"
    client = _get_client()
    resp = await client.get(meta_url, headers={"Authorization": f"Bearer {token}"})

    if resp.status_code != 200:
        return Response(status_code=404, content="File not found", headers=CORS_HEADERS)

    meta = resp.json()
    file_size = int(meta.get("size", 0))
    mime_type = _resolve_mime(meta)

    return Response(
        status_code=200,
        headers={
            **CORS_HEADERS,
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
        },
    )


@router.get("/dl/{file_id}/video.mkv")
async def stream_gdrive(file_id: str, request: Request):
    """
    Stream Google Drive video.
    Primary: redirect to Google's CDN (zero bandwidth on our side).
    Fallback: proxy the stream through our server.
    """
    # --- Primary: redirect to CDN ---
    cdn_url = await _resolve_cdn_url(file_id)
    if cdn_url:
        return Response(
            status_code=302,
            headers={"Location": cdn_url, **CORS_HEADERS},
        )

    # --- Fallback: proxy stream ---
    log.info(f"Falling back to proxy for {file_id}")
    token = await get_fresh_token()
    download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"

    # Get file metadata for size + mime
    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size,mimeType,name&supportsAllDrives=true"
    client = _get_client()
    meta_resp = await client.get(meta_url, headers={"Authorization": f"Bearer {token}"})

    if meta_resp.status_code != 200:
        return Response(status_code=404, content="File not found on Google Drive", headers=CORS_HEADERS)

    meta = meta_resp.json()
    file_size = int(meta.get("size", 0))
    mime_type = _resolve_mime(meta)
    filename = meta.get("name", "video")

    range_header = request.headers.get("Range")

    if range_header:
        try:
            range_val = range_header.replace("bytes=", "").strip()
            start_str, _, end_str = range_val.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)

            if start > end or start >= file_size:
                return Response(
                    status_code=416,
                    content="Range Not Satisfiable",
                    headers={**CORS_HEADERS, "Content-Range": f"bytes */{file_size}"},
                )
        except Exception:
            return Response(status_code=416, content="Invalid Range header", headers=CORS_HEADERS)

        chunk_size = end - start + 1

        async def generate():
            try:
                fresh_token = await get_fresh_token()
                async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=300)) as dl:
                    async with dl.stream(
                        "GET", download_url,
                        headers={"Authorization": f"Bearer {fresh_token}", "Range": f"bytes={start}-{end}"},
                    ) as resp:
                        async for data in resp.aiter_bytes(chunk_size=262144):
                            yield data
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as e:
                log.error(f"Proxy stream error for {file_id}: {e}")

        return StreamingResponse(
            generate(),
            status_code=206,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
    else:
        async def generate_full():
            try:
                fresh_token = await get_fresh_token()
                async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=300)) as dl:
                    async with dl.stream(
                        "GET", download_url,
                        headers={"Authorization": f"Bearer {fresh_token}"},
                    ) as resp:
                        async for data in resp.aiter_bytes(chunk_size=262144):
                            yield data
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as e:
                log.error(f"Proxy stream error for {file_id}: {e}")

        return StreamingResponse(
            generate_full(),
            status_code=200,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
