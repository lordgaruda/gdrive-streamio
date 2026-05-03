"""
Google Drive video streaming proxy with Range support for Stremio.
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

# Persistent client for connection reuse
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=15, read=300, write=15, pool=15),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        )
    return _client


async def get_fresh_token() -> str:
    raw = await db.load_gdrive_token()
    if not raw:
        raise RuntimeError("Google Drive credentials not configured")
    creds = pickle.loads(raw)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        await db.update_gdrive_token_after_refresh(pickle.dumps(creds))
    return creds.token


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


def _download_url(file_id: str) -> str:
    return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"


async def _get_meta(file_id: str) -> dict | None:
    token = await get_fresh_token()
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size,mimeType,name&supportsAllDrives=true"
    cl = _get_client()
    r = await cl.get(url, headers={"Authorization": f"Bearer {token}"})
    return r.json() if r.status_code == 200 else None


@router.options("/dl/{file_id}/video.mkv")
async def stream_options(file_id: str):
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mkv")
async def stream_head(file_id: str):
    meta = await _get_meta(file_id)
    if not meta:
        return Response(status_code=404, headers=CORS_HEADERS)
    return Response(status_code=200, headers={
        **CORS_HEADERS,
        "Accept-Ranges": "bytes",
        "Content-Length": meta.get("size", "0"),
        "Content-Type": _resolve_mime(meta),
    })


@router.get("/dl/{file_id}/video.mkv")
async def stream_gdrive(file_id: str, request: Request):
    meta = await _get_meta(file_id)
    if not meta:
        return Response(status_code=404, content="Not found", headers=CORS_HEADERS)

    file_size = int(meta.get("size", 0))
    mime_type = _resolve_mime(meta)
    filename = meta.get("name", "video")
    dl_url = _download_url(file_id)

    range_header = request.headers.get("Range")

    if range_header:
        try:
            rv = range_header.replace("bytes=", "").strip()
            s, _, e = rv.partition("-")
            start = int(s) if s else 0
            end = int(e) if e else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                return Response(status_code=416, headers={
                    **CORS_HEADERS, "Content-Range": f"bytes */{file_size}"
                })
        except Exception:
            return Response(status_code=416, headers=CORS_HEADERS)

        length = end - start + 1

        async def gen_range():
            try:
                token = await get_fresh_token()
                cl = _get_client()
                async with cl.stream("GET", dl_url, headers={
                    "Authorization": f"Bearer {token}",
                    "Range": f"bytes={start}-{end}",
                }) as resp:
                    async for chunk in resp.aiter_bytes(262_144):
                        yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as e:
                log.error(f"Range error {file_id}: {e}")

        return StreamingResponse(gen_range(), status_code=206, media_type=mime_type, headers={
            **CORS_HEADERS,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Disposition": f'inline; filename="{filename}"',
        })
    else:
        async def gen_full():
            try:
                token = await get_fresh_token()
                cl = _get_client()
                async with cl.stream("GET", dl_url, headers={
                    "Authorization": f"Bearer {token}",
                }) as resp:
                    async for chunk in resp.aiter_bytes(262_144):
                        yield chunk
            except (GeneratorExit, asyncio.CancelledError):
                pass
            except Exception as e:
                log.error(f"Full error {file_id}: {e}")

        return StreamingResponse(gen_full(), status_code=200, media_type=mime_type, headers={
            **CORS_HEADERS,
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{filename}"',
        })
