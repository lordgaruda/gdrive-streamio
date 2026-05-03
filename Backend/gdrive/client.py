"""
Google Drive client that loads credentials from MongoDB (not from disk).
Saves refreshed credentials back to MongoDB automatically.
"""
import pickle
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from Backend import db


async def get_drive_service():
    """
    Build and return an authenticated Google Drive v3 service.
    Credentials are loaded from MongoDB and refreshed if expired.
    Raises RuntimeError if token.pickle has never been uploaded.
    """
    raw = await db.load_gdrive_token()
    if raw is None:
        raise RuntimeError(
            "Google Drive not configured. "
            "Send token.pickle to the Telegram bot to connect."
        )

    creds = pickle.loads(raw)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token back to MongoDB
        refreshed_raw = pickle.dumps(creds)
        await db.update_gdrive_token_after_refresh(refreshed_raw)

    return build("drive", "v3", credentials=creds)
