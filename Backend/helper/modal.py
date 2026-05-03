from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------
# GDrive Stream (replaces Telegram QualityDetail)
# ---------------------------
class GDriveStream(BaseModel):
    """Stream quality entry backed by a Google Drive file."""
    gdrive_file_id: str        # Google Drive file ID (e.g. "1BxiMVs0XRA5...")
    filename: str              # original filename
    quality: str               # "1080p", "720p", "4K", "Unknown"
    size: int                  # file size in bytes
    mime_type: str             # "video/mp4", "video/x-matroska", etc.
    added_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------
# Episode Schema
# ---------------------------
class Episode(BaseModel):
    episode_number: int
    title: str
    episode_backdrop: Optional[str] = None
    overview: Optional[str] = None
    released: Optional[str] = None
    streams: Optional[List[GDriveStream]] = Field(default_factory=list)


# ---------------------------
# Season Schema
# ---------------------------
class Season(BaseModel):
    season_number: int
    episodes: List[Episode] = Field(default_factory=list)


# ---------------------------
# TV Show Schema
# ---------------------------
class TVShowSchema(BaseModel):
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    db_index: int
    title: str
    genres: Optional[List[str]] = None
    description: Optional[str] = None
    rating: Optional[float] = None
    release_year: Optional[int] = None
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    logo: Optional[str] = None
    cast: Optional[List[str]] = None
    runtime: Optional[str] = None
    media_type: str
    updated_on: datetime = Field(default_factory=datetime.utcnow)
    seasons: List[Season] = Field(default_factory=list)


# ---------------------------
# Movie Schema
# ---------------------------
class MovieSchema(BaseModel):
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    db_index: int
    title: str
    genres: Optional[List[str]] = None
    description: Optional[str] = None
    rating: Optional[float] = None
    release_year: Optional[int] = None
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    logo: Optional[str] = None
    cast: Optional[List[str]] = None
    runtime: Optional[str] = None
    media_type: str
    updated_on: datetime = Field(default_factory=datetime.utcnow)
    streams: Optional[List[GDriveStream]] = Field(default_factory=list)


# ---------------------------
# GDrive Credential (token.pickle stored in MongoDB)
# ---------------------------
class GDriveCredential(BaseModel):
    """
    Stores the binary content of token.pickle in MongoDB.
    Only one document exists in this collection at a time (upserted by _id).
    """
    pickle_bytes: bytes                 # raw binary of token.pickle
    uploaded_by: int                    # Telegram user_id who sent the file
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    refreshed_at: Optional[datetime] = None  # updated each time creds are refreshed
