"""
Recursively scans a Google Team Drive folder for video files.
Returns structured metadata for each file using PTN parsing.

Supports incremental scanning: pass a `since` datetime to only
retrieve files modified after the last successful scan.
"""
from datetime import datetime, timezone
from typing import Optional
import PTN
from Backend.gdrive.client import get_drive_service
from Backend.config import GDrive
from Backend.logger import LOGGER

VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/x-matroska",
    "video/x-msvideo",
    "video/quicktime",
    "video/webm",
    "video/x-ms-wmv",
    "video/mpeg",
}

SKIP_KEYWORDS = {"sample", "trailer", "featurette", "extras", "behind", "deleted"}


async def list_all_video_files(since: Optional[datetime] = None) -> list[dict]:
    """
    Paginate through all files in GDRIVE_FOLDER_ID (and subfolders).
    Returns list of parsed file dicts.

    Args:
        since: If provided, only return files modified after this datetime.
               This enables fast incremental scanning on restarts.
    """
    service = await get_drive_service()
    results = []

    # Pre-format the time filter once if doing incremental scan
    time_filter = ""
    if since:
        # Ensure UTC and format for Drive API (RFC 3339)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        time_filter = f" and modifiedTime > '{since.strftime('%Y-%m-%dT%H:%M:%S.000Z')}'"
        LOGGER.info(f"Incremental scan: only files modified after {since.isoformat()}")

    def crawl_folder(folder_id: str, path: str = ""):
        page_token = None
        while True:
            query = f"'{folder_id}' in parents and trashed=false"
            # For subfolders, always list them (they don't change mimeType)
            # but for files, apply the time filter
            file_query = query + time_filter
            # We need to list folders regardless of time filter to recurse
            folder_query = query + f" and mimeType='application/vnd.google-apps.folder'"

            try:
                # First, always discover subfolders (cheap, no time filter needed)
                folder_page_token = None
                while True:
                    folder_resp = service.files().list(
                        q=folder_query,
                        fields="nextPageToken, files(id, name, mimeType)",
                        pageSize=100,
                        pageToken=folder_page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    ).execute()
                    for f in folder_resp.get("files", []):
                        crawl_folder(f["id"], path=f"{path}/{f['name']}")
                    folder_page_token = folder_resp.get("nextPageToken")
                    if not folder_page_token:
                        break
            except Exception as e:
                LOGGER.error(f"Drive API error listing subfolders of {folder_id}: {e}")

            try:
                # Now list files (with time filter for incremental scan)
                non_folder_query = file_query + " and mimeType!='application/vnd.google-apps.folder'"
                response = service.files().list(
                    q=non_folder_query,
                    fields="nextPageToken, files(id, name, size, mimeType, parents, modifiedTime)",
                    pageSize=100,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            except Exception as e:
                LOGGER.error(f"Drive API error scanning folder {folder_id}: {e}")
                break

            for f in response.get("files", []):
                mime = f.get("mimeType", "")
                name = f.get("name", "")

                # Skip non-video files
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                is_video_mime = mime in VIDEO_MIME_TYPES
                is_video_ext = ext in {"mp4", "mkv", "avi", "mov", "webm", "wmv", "m4v", "mpg"}
                if not (is_video_mime or is_video_ext):
                    continue

                # Skip samples/trailers
                if any(kw in name.lower() for kw in SKIP_KEYWORDS):
                    continue

                # Parse filename with PTN
                parsed = PTN.parse(name)
                title = parsed.get("title", "").strip()
                if not title:
                    continue

                season = parsed.get("season")
                episode = parsed.get("episode")
                media_type = "series" if season is not None else "movie"

                results.append({
                    "gdrive_file_id": f["id"],
                    "filename": name,
                    "title": title,
                    "year": parsed.get("year"),
                    "season": season,
                    "episode": episode,
                    "quality": parsed.get("resolution", "Unknown"),
                    "codec": parsed.get("codec", ""),
                    "size": int(f.get("size", 0)),
                    "mime_type": mime if is_video_mime else f"video/{ext}",
                    "folder_path": path,
                    "media_type": media_type,
                    "modified_time": f.get("modifiedTime"),
                })

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    crawl_folder(GDrive.FOLDER_ID)
    LOGGER.info(f"Drive scanner found {len(results)} video files" +
                (" (incremental)" if since else " (full scan)"))
    return results
