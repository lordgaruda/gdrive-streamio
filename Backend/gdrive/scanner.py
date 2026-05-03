"""
Recursively scans a Google Team Drive folder for video files.
Returns structured metadata for each file using PTN parsing.
"""
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


async def list_all_video_files() -> list[dict]:
    """
    Paginate through all files in GDRIVE_FOLDER_ID (and subfolders).
    Returns list of parsed file dicts.
    """
    service = await get_drive_service()
    results = []

    def crawl_folder(folder_id: str, path: str = ""):
        page_token = None
        while True:
            query = f"'{folder_id}' in parents and trashed=false"
            try:
                response = service.files().list(
                    q=query,
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

                # Recurse into subfolders
                if mime == "application/vnd.google-apps.folder":
                    crawl_folder(f["id"], path=f"{path}/{name}")
                    continue

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
    LOGGER.info(f"Drive scanner found {len(results)} video files")
    return results
