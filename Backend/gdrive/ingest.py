"""
Ties Drive scanner → TMDB metadata → MongoDB upsert.
Safe to run repeatedly — uses gdrive_file_id as dedup key.

Supports incremental scanning: on restart, only files modified
since the last successful scan are fetched from Drive.
"""
import logging
from datetime import datetime, timezone
from Backend.gdrive.scanner import list_all_video_files
from Backend.helper.metadata import metadata as fetch_metadata
from Backend import db

log = logging.getLogger("gdrive_ingest")


async def run_full_ingest(force_full: bool = False):
    """
    Run the GDrive → DB ingest pipeline.

    Args:
        force_full: If True, ignore the last scan timestamp and do a full scan.
                    Otherwise, does an incremental scan based on last saved timestamp.
    """
    # Determine whether to do incremental or full scan
    since = None
    if not force_full:
        since = await db.load_gdrive_last_scan()
        if since:
            log.info(f"Incremental scan — only files modified after {since.isoformat()}")
        else:
            log.info("No previous scan found — running initial full scan")

    # Record the scan start time BEFORE calling Drive API
    # so we don't miss files modified during the scan
    scan_start = datetime.now(timezone.utc)

    log.info("GDrive ingest started")
    try:
        files = await list_all_video_files(since=since)
    except RuntimeError as e:
        log.warning(f"GDrive ingest skipped: {e}")
        return
    log.info(f"Found {len(files)} video files in Drive" +
             (" (incremental)" if since else " (full scan)"))

    if not files and since:
        log.info("No new/modified files since last scan — nothing to do")
        await db.save_gdrive_last_scan(scan_start)
        return

    indexed = 0
    skipped = 0
    failed = 0

    for f in files:
        try:
            # Skip if already indexed with same file_id
            if await db.gdrive_file_exists(f["gdrive_file_id"]):
                skipped += 1
                continue

            # Use existing metadata engine to fetch TMDB/IMDB data
            # We pass a dummy channel/msg_id since we don't need telegram encoding
            meta = await fetch_metadata(
                filename=f["filename"],
                channel=0,
                msg_id=0,
            )
            if not meta:
                log.warning(f"No metadata match for: {f['filename']}")
                failed += 1
                continue

            stream = {
                "gdrive_file_id": f["gdrive_file_id"],
                "filename": f["filename"],
                "quality": f["quality"],
                "size": f["size"],
                "mime_type": f["mime_type"],
            }

            if f["media_type"] == "movie":
                await db.upsert_movie_stream(
                    tmdb_id=meta.get("tmdb_id"),
                    stream=stream,
                    meta=meta,
                )
            else:
                await db.upsert_episode_stream(
                    tmdb_id=meta.get("tmdb_id"),
                    season=f["season"],
                    episode=f["episode"],
                    stream=stream,
                    meta=meta,
                )
            indexed += 1
            log.info(f"Indexed: {f['filename']}")

        except Exception as e:
            log.error(f"Failed to index {f['filename']}: {e}")
            failed += 1

    # Save the scan timestamp so the next restart does incremental
    await db.save_gdrive_last_scan(scan_start)
    log.info(f"GDrive ingest complete — indexed={indexed}, skipped={skipped}, failed={failed}")

