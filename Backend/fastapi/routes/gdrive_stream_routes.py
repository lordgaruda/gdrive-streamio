"""
Google Drive video streaming proxy with Range support for Stremio.
Uses streaming (no buffering) and verifies Google's response status.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
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

# ---------------------------------------------------------------------------
# Resolved-URL cache: resolve the final CDN URL once, reuse for 25 min.
# Google Drive API redirects alt=media GET to a *.googleusercontent.com URL.
# That CDN URL needs no auth and supports Range natively.
# ---------------------------------------------------------------------------
_resolved_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 1500  # 25 min


async def get_fresh_token() -> str:
    raw = await db.load_gdrive_token()
    if not raw:
        raise RuntimeError("Google Drive credentials not configured")
    creds = pickle.loads(raw)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        await db.update_gdrive_token_after_refresh(pickle.dumps(creds))
    return creds.token


async def _resolve_url(file_id: str) -> str:
    """
    Follow redirects from the Drive API download endpoint and return
    the final URL (usually a googleusercontent CDN link).
    Uses stream() so the response body is NEVER read into memory.
    """
    cached = _resolved_cache.get(file_id)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        return cached[0]

    token = await get_fresh_token()
    api_url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?alt=media&supportsAllDrives=true"
    )

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as cl:
        # stream() reads only headers; body is NOT buffered.
        async with cl.stream(
            "GET", api_url, headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            final = str(resp.url)
            log.info(
                f"Resolved {file_id}: status={resp.status_code} "
                f"redirected={'Yes' if final != api_url else 'No'} "
                f"final_host={resp.url.host}"
            )
            # body is discarded when context manager closes

    _resolved_cache[file_id] = (final, time.time())
    return final


def _resolve_mime(meta: dict) -> str:
    mime = meta.get("mimeType", "video/mp4")
    if mime == "application/octet-stream":
        name = meta.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        mime = {
            "mkv": "video/x-matroska", "mp4": "video/mp4",
            "avi": "video/x-msvideo", "webm": "video/webm",
            "ts": "video/mp2t", "m4v": "video/mp4",
        }.get(ext, "video/mp4")
    return mime


async def _get_meta(file_id: str, token: str) -> dict | None:
    url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?fields=size,mimeType,name&supportsAllDrives=true"
    )
    async with httpx.AsyncClient(timeout=15) as cl:
        r = await cl.get(url, headers={"Authorization": f"Bearer {token}"})
    return r.json() if r.status_code == 200 else None


# ---- Routes ---------------------------------------------------------------

@router.options("/dl/{file_id}/video.mkv")
async def stream_options(file_id: str):
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mkv")
async def stream_head(file_id: str):
    token = await get_fresh_token()
    meta = await _get_meta(file_id, token)
    if not meta:
        return Response(status_code=404, headers=CORS_HEADERS)
    return Response(
        status_code=200,
        headers={
            **CORS_HEADERS,
            "Accept-Ranges": "bytes",
            "Content-Length": meta.get("size", "0"),
            "Content-Type": _resolve_mime(meta),
        },
    )


@router.get("/dl/{file_id}/video.mkv")
async def stream_gdrive(file_id: str, request: Request):
    token = await get_fresh_token()
    meta = await _get_meta(file_id, token)
    if not meta:
        return Response(status_code=404, content="Not found", headers=CORS_HEADERS)

    file_size = int(meta.get("size", 0))
    mime_type = _resolve_mime(meta)
    filename = meta.get("name", "video")

    # Resolve the real download URL (CDN or API)
    download_url = await _resolve_url(file_id)
    is_cdn = "googleusercontent.com" in download_url

    range_header = request.headers.get("Range")

    if range_header:
        try:
            rv = range_header.replace("bytes=", "").strip()
            s, _, e = rv.partition("-")
            start = int(s) if s else 0
            end = int(e) if e else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                return Response(
                    status_code=416,
                    headers={**CORS_HEADERS, "Content-Range": f"bytes */{file_size}"},
                )
        except Exception:
            return Response(status_code=416, headers=CORS_HEADERS)

        length = end - start + 1

        async def gen_range():
            hdrs = {"Range": f"bytes={start}-{end}"}
            if not is_cdn:
                t = await get_fresh_token()
                hdrs["Authorization"] = f"Bearer {t}"
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(15, read=300),
                ) as cl:
                    async with cl.stream("GET", download_url, headers=hdrs) as resp:
                        log.info(
                            f"Range {file_id} [{start}-{end}]: "
                            f"google_status={resp.status_code} "
                            f"cr={resp.headers.get('Content-Range','?')}"
                        )
                        async for chunk in resp.aiter_bytes(262_144):
                            yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as exc:
                log.error(f"Range stream error {file_id}: {exc}")

        return StreamingResponse(
            gen_range(),
            status_code=206,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
    else:
        async def gen_full():
            hdrs: dict[str, str] = {}
            if not is_cdn:
                t = await get_fresh_token()
                hdrs["Authorization"] = f"Bearer {t}"
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(15, read=300),
                ) as cl:
                    async with cl.stream("GET", download_url, headers=hdrs) as resp:
                        log.info(f"Full {file_id}: google_status={resp.status_code}")
                        async for chunk in resp.aiter_bytes(262_144):
                            yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as exc:
                log.error(f"Full stream error {file_id}: {exc}")

        return StreamingResponse(
            gen_full(),
            status_code=200,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
