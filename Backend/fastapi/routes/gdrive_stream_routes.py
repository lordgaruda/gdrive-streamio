"""
Google Drive video streaming proxy with Range support for Stremio.
Proxies byte-range requests to Google Drive API, streaming chunks
without buffering the full file in memory.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import pickle
import logging
import asyncio
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


async def _get_file_meta(file_id: str, token: str) -> dict | None:
    """Fetch file metadata (size, mimeType, name) from Google Drive."""
    meta_url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?fields=size,mimeType,name&supportsAllDrives=true"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(meta_url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return None
    return resp.json()


@router.options("/dl/{file_id}/video.mkv")
async def stream_options(file_id: str):
    """Handle CORS preflight from Stremio Web (browser)."""
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mkv")
async def stream_head(file_id: str):
    """Stremio probes with HEAD before playback — return file size & type."""
    token = await get_fresh_token()
    meta = await _get_file_meta(file_id, token)

    if not meta:
        return Response(status_code=404, content="File not found", headers=CORS_HEADERS)

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
    """
    Proxy Google Drive video with proper Range support.
    Each request opens a streaming connection to Google — no buffering.
    """
    token = await get_fresh_token()
    meta = await _get_file_meta(file_id, token)

    if not meta:
        return Response(status_code=404, content="File not found", headers=CORS_HEADERS)

    file_size = int(meta.get("size", 0))
    mime_type = _resolve_mime(meta)
    filename = meta.get("name", "video")
    download_url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?alt=media&supportsAllDrives=true"
    )

    range_header = request.headers.get("Range")

    if range_header:
        # --- Ranged request (206) ---
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
            return Response(status_code=416, content="Invalid Range", headers=CORS_HEADERS)

        content_length = end - start + 1

        async def stream_range():
            try:
                t = await get_fresh_token()
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(connect=15, read=300, write=15, pool=15),
                ) as cl:
                    async with cl.stream(
                        "GET",
                        download_url,
                        headers={
                            "Authorization": f"Bearer {t}",
                            "Range": f"bytes={start}-{end}",
                        },
                    ) as resp:
                        async for chunk in resp.aiter_bytes(chunk_size=262_144):
                            yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as e:
                log.error(f"Range stream error {file_id} [{start}-{end}]: {e}")

        return StreamingResponse(
            stream_range(),
            status_code=206,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
    else:
        # --- Full file (200) ---
        async def stream_full():
            try:
                t = await get_fresh_token()
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(connect=15, read=300, write=15, pool=15),
                ) as cl:
                    async with cl.stream(
                        "GET",
                        download_url,
                        headers={"Authorization": f"Bearer {t}"},
                    ) as resp:
                        async for chunk in resp.aiter_bytes(chunk_size=262_144):
                            yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as e:
                log.error(f"Full stream error {file_id}: {e}")

        return StreamingResponse(
            stream_full(),
            status_code=200,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
