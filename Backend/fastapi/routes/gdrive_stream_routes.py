"""
Google Drive video streaming proxy with Range support for Stremio Web.
Handles CORS, HEAD, OPTIONS preflight, and partial content (206).
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import pickle
import logging
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


@router.options("/dl/{file_id}/video.mkv")
async def stream_options(file_id: str):
    """Handle CORS preflight from Stremio Web (browser)."""
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mkv")
async def stream_head(file_id: str):
    """Stremio Web probes with HEAD before starting playback."""
    token = await get_fresh_token()
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"

    async with httpx.AsyncClient() as client:
        resp = await client.head(url, headers={"Authorization": f"Bearer {token}"})

    headers = {
        **CORS_HEADERS,
        "Accept-Ranges": "bytes",
        "Content-Length": resp.headers.get("Content-Length", "0"),
        "Content-Type": resp.headers.get("Content-Type", "video/mp4"),
    }
    return Response(status_code=200, headers=headers)


@router.get("/dl/{file_id}/video.mkv")
async def stream_gdrive(file_id: str, request: Request):
    """Proxy Google Drive video stream with Range support for Stremio Web."""
    token = await get_fresh_token()
    download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"

    # Get file metadata for size + mime
    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size,mimeType,name&supportsAllDrives=true"
    async with httpx.AsyncClient() as client:
        meta_resp = await client.get(meta_url, headers={"Authorization": f"Bearer {token}"})

    if meta_resp.status_code != 200:
        return Response(
            status_code=404,
            content="File not found on Google Drive",
            headers=CORS_HEADERS,
        )

    meta = meta_resp.json()
    file_size = int(meta.get("size", 0))
    mime_type = meta.get("mimeType", "video/mp4")

    # Normalize MIME for browser playback
    if mime_type == "application/octet-stream":
        name = meta.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        mime_map = {"mkv": "video/x-matroska", "mp4": "video/mp4",
                    "avi": "video/x-msvideo", "webm": "video/webm"}
        mime_type = mime_map.get(ext, "video/mp4")

    range_header = request.headers.get("Range")

    if range_header:
        try:
            range_val = range_header.replace("bytes=", "").strip()
            start_str, _, end_str = range_val.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else min(start + 10_000_000, file_size - 1)
            end = min(end, file_size - 1)
        except Exception:
            return Response(status_code=416, content="Invalid Range header", headers=CORS_HEADERS)

        chunk_size = end - start + 1

        async def generate():
            try:
                fresh_token = await get_fresh_token()
                async with httpx.AsyncClient(timeout=60) as client:
                    async with client.stream(
                        "GET", download_url,
                        headers={"Authorization": f"Bearer {fresh_token}", "Range": f"bytes={start}-{end}"}
                    ) as resp:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            yield chunk
            except Exception as e:
                log.error(f"Stream error for {file_id}: {e}")

        return StreamingResponse(
            generate(),
            status_code=206,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Content-Disposition": f'inline; filename="{meta.get("name", "video")}"',
            }
        )
    else:
        async def generate_full():
            fresh_token = await get_fresh_token()
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "GET", download_url,
                    headers={"Authorization": f"Bearer {fresh_token}"}
                ) as resp:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        yield chunk

        return StreamingResponse(
            generate_full(),
            status_code=200,
            media_type=mime_type,
            headers={
                **CORS_HEADERS,
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            }
        )
