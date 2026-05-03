"""
Admin-only Telegram bot commands.
Regular users and channel messages are fully ignored.
Only user IDs listed in ADMIN_TELEGRAM_IDS can interact.
"""
from pyrogram import Client, filters
from pyrogram.types import Message
from Backend.config import Telegram
import pickle, io

def is_admin(_, __, message: Message) -> bool:
    return message.from_user and message.from_user.id in Telegram.ADMIN_TELEGRAM_IDS

admin_filter = filters.create(is_admin)


@Client.on_message(admin_filter & filters.document)
async def receive_token_pickle(client: Client, message: Message):
    """
    Admin sends token.pickle file to the bot.
    Bot validates it, stores binary in MongoDB.
    """
    doc = message.document

    # Validate filename
    if not doc.file_name or not doc.file_name.endswith(".pickle"):
        await message.reply("Send a file named token.pickle")
        return

    await message.reply("⏳ Downloading and validating token.pickle...")

    # Download into memory (do NOT save to disk)
    file_bytes = io.BytesIO()
    await client.download_media(message, file_name=file_bytes)
    file_bytes.seek(0)
    raw = file_bytes.read()

    # Validate: must be a valid pickle containing Google OAuth2 credentials
    try:
        creds = pickle.loads(raw)
        from google.oauth2.credentials import Credentials
        if not isinstance(creds, Credentials):
            raise ValueError("Not a Google Credentials object")
        if not creds.refresh_token:
            raise ValueError("Credentials have no refresh_token — re-authenticate")
    except Exception as e:
        await message.reply(f"❌ Invalid token.pickle: {e}\n\nRe-run the OAuth flow and try again.")
        return

    # Store in MongoDB
    from Backend import db
    await db.save_gdrive_token(raw, uploaded_by=message.from_user.id)
    await message.reply(
        "✅ token.pickle saved to database.\n"
        "Google Drive is now connected.\n"
        "Starting initial scan — use /scanstatus to check progress."
    )

    # Trigger initial scan
    from Backend.gdrive.ingest import run_full_ingest
    import asyncio
    asyncio.create_task(run_full_ingest())


@Client.on_message(admin_filter & filters.command("scanstatus"))
async def scan_status(client: Client, message: Message):
    """Show how many movies/shows are indexed."""
    from Backend import db
    movies = await db.count_movies()
    shows = await db.count_shows()
    token_exists = await db.load_gdrive_token() is not None
    await message.reply(
        f"**Google Drive Token:** {'✅ Connected' if token_exists else '❌ NOT uploaded'}\n"
        f"**Movies indexed:** {movies}\n"
        f"**TV Shows indexed:** {shows}"
    )


@Client.on_message(admin_filter & filters.command("rescan"))
async def trigger_rescan(client: Client, message: Message):
    """Manually trigger a Google Drive rescan."""
    from Backend.gdrive.ingest import run_full_ingest
    import asyncio
    await message.reply("🔄 Rescan started. Use /scanstatus to monitor.")
    asyncio.create_task(run_full_ingest())


@Client.on_message(admin_filter & filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply(
        "**GDrive Stremio Bot — Admin Commands:**\n\n"
        "📎 Send `token.pickle` file → uploads Google Drive credentials\n"
        "📊 /scanstatus — show indexing status\n"
        "🔄 /rescan — trigger a manual Drive rescan"
    )
