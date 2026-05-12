"""
Google Drive video streaming proxy with Range support for Stremio.

Supports two streaming modes:
  - /dl/{file_id}/video.mkv  → raw passthrough (for Stremio desktop / VLC)
  - /dl/{file_id}/video.mp4  → on-the-fly FFmpeg remux MKV→MP4 (for browsers/Safari)

The .mp4 route uses `ffmpeg -c copy` (transmux only, no re-encoding)
so it's fast, low-CPU, and preserves full quality.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import pickle
import logging
import asyncio
import shutil
from Backend import db
from google.auth.transport.requests import Request as GRequest

router = APIRouter(tags=["GDrive Streaming"])
log = logging.getLogger("gdrive_stream")

# Check FFmpeg availability at module load
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
if not FFMPEG_AVAILABLE:
    log.warning("FFmpeg not found in PATH — MKV→MP4 remuxing will be unavailable")

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


def _is_mkv(meta: dict) -> bool:
    """Check if a file is MKV based on mime type or extension."""
    mime = meta.get("mimeType", "")
    name = meta.get("name", "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return mime == "video/x-matroska" or ext == "mkv"


def _download_url(file_id: str) -> str:
    return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"


async def _get_meta(file_id: str) -> dict | None:
    token = await get_fresh_token()
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=size,mimeType,name&supportsAllDrives=true"
    cl = _get_client()
    r = await cl.get(url, headers={"Authorization": f"Bearer {token}"})
    return r.json() if r.status_code == 200 else None


# ──────────────────────────────────────────────────────────
#  Raw passthrough endpoint (MKV / any format as-is)
# ──────────────────────────────────────────────────────────

@router.options("/dl/{file_id}/video.mkv")
async def stream_options_mkv(file_id: str):
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mkv")
async def stream_head_mkv(file_id: str):
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
async def stream_gdrive_raw(file_id: str, request: Request):
    """Raw passthrough — serves the file exactly as stored in Drive."""
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


# ──────────────────────────────────────────────────────────
#  FFmpeg remux endpoint (MKV → MP4 on-the-fly for browsers)
# ──────────────────────────────────────────────────────────

@router.options("/dl/{file_id}/video.mp4")
async def stream_options_mp4(file_id: str):
    return Response(status_code=204, headers=CORS_HEADERS)


@router.head("/dl/{file_id}/video.mp4")
async def stream_head_mp4(file_id: str):
    meta = await _get_meta(file_id)
    if not meta:
        return Response(status_code=404, headers=CORS_HEADERS)
    # For remuxed streams we can't know the exact size in advance
    return Response(status_code=200, headers={
        **CORS_HEADERS,
        "Content-Type": "video/mp4",
    })


@router.get("/dl/{file_id}/video.mp4")
async def stream_gdrive_mp4(file_id: str, request: Request):
    """
    Browser-compatible endpoint: if the source file is MKV, pipes it
    through FFmpeg to remux into an MP4 container (codec copy, no re-encoding).
    If the source is already MP4/WebM, streams it directly.
    """
    meta = await _get_meta(file_id)
    if not meta:
        return Response(status_code=404, content="Not found", headers=CORS_HEADERS)

    file_size = int(meta.get("size", 0))
    filename = meta.get("name", "video")
    dl_url = _download_url(file_id)

    # If the file is already MP4, just passthrough (no FFmpeg needed)
    if not _is_mkv(meta):
        mime_type = _resolve_mime(meta)
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

            async def gen_range_passthrough():
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
                    log.error(f"MP4 passthrough range error {file_id}: {e}")

            return StreamingResponse(gen_range_passthrough(), status_code=206, media_type=mime_type, headers={
                **CORS_HEADERS,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f'inline; filename="{filename}"',
            })
        else:
            async def gen_full_passthrough():
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
                    log.error(f"MP4 passthrough full error {file_id}: {e}")

            return StreamingResponse(gen_full_passthrough(), status_code=200, media_type=mime_type, headers={
                **CORS_HEADERS,
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f'inline; filename="{filename}"',
            })

    # ── MKV → MP4 remux via FFmpeg ────────────────────────
    if not FFMPEG_AVAILABLE:
        return Response(
            status_code=500,
            content="FFmpeg not available — cannot remux MKV to MP4",
            headers=CORS_HEADERS,
        )

    mp4_filename = filename.rsplit(".", 1)[0] + ".mp4" if "." in filename else filename + ".mp4"

    async def gen_ffmpeg_remux():
        """
        Download MKV from GDrive → pipe into FFmpeg stdin → read MP4 from stdout.
        Uses `-c copy` (transmux) so there's no re-encoding overhead.
        The `-movflags frag_keyframe+empty_moov+default_base_moof` flags enable
        fragmented MP4 output which is streamable (no need to seek back to write moov atom).
        """
        proc = None
        try:
            token = await get_fresh_token()
            cl = _get_client()

            # Start FFmpeg: read MKV from stdin, output fragmented MP4 to stdout
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",                          # read from stdin
                "-c", "copy",                            # no re-encoding (transmux)
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4",                             # output format
                "pipe:1",                                # write to stdout
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def feed_stdin():
                """Download from GDrive and pipe into FFmpeg stdin."""
                try:
                    async with cl.stream("GET", dl_url, headers={
                        "Authorization": f"Bearer {token}",
                    }) as resp:
                        async for chunk in resp.aiter_bytes(262_144):
                            if proc.stdin.is_closing():
                                break
                            proc.stdin.write(chunk)
                            await proc.stdin.drain()
                except Exception as e:
                    log.error(f"FFmpeg feed error {file_id}: {e}")
                finally:
                    try:
                        proc.stdin.close()
                        await proc.stdin.wait_closed()
                    except Exception:
                        pass

            # Start feeding GDrive data to FFmpeg in the background
            feed_task = asyncio.create_task(feed_stdin())

            # Read remuxed MP4 chunks from FFmpeg stdout
            while True:
                chunk = await proc.stdout.read(262_144)
                if not chunk:
                    break
                yield chunk

            # Wait for feeder to finish
            await feed_task

            # Capture any FFmpeg errors
            stderr_output = await proc.stderr.read()
            if stderr_output:
                log.warning(f"FFmpeg stderr for {file_id}: {stderr_output.decode(errors='ignore')}")

            await proc.wait()

        except (GeneratorExit, asyncio.CancelledError):
            pass
        except Exception as e:
            log.error(f"FFmpeg remux error {file_id}: {e}")
        finally:
            if proc and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass

    return StreamingResponse(
        gen_ffmpeg_remux(),
        status_code=200,
        media_type="video/mp4",
        headers={
            **CORS_HEADERS,
            # No Content-Length since remuxed size is unknown
            "Content-Disposition": f'inline; filename="{mp4_filename}"',
            "Transfer-Encoding": "chunked",
        },
    )

