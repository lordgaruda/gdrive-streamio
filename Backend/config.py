from os import getenv, path
from dotenv import load_dotenv

load_dotenv(path.join(path.dirname(path.dirname(__file__)), "config.env"))

class Telegram:
    API_ID = int(getenv("API_ID", "0"))
    API_HASH = getenv("API_HASH", "")
    BOT_TOKEN = getenv("BOT_TOKEN", "")

    BASE_URL = getenv("BASE_URL", "").rstrip('/')
    PORT = int(getenv("PORT", "8000"))

    DATABASE = [db.strip() for db in (getenv("DATABASE") or "").split(",") if db.strip()]

    TMDB_API = getenv("TMDB_API", "")

    UPSTREAM_REPO = getenv("UPSTREAM_REPO", "")
    UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "")

    OWNER_ID = int(getenv("OWNER_ID", "5422223708"))
    ADMIN_TELEGRAM_IDS = [
        int(x.strip()) for x in (getenv("ADMIN_TELEGRAM_IDS") or "").split(",")
        if x.strip().isdigit()
    ]

    ADMIN_USERNAME = getenv("ADMIN_USERNAME", "fyvio")
    ADMIN_PASSWORD = getenv("ADMIN_PASSWORD", "fyvio")
    
    SUBSCRIPTION = getenv("SUBSCRIPTION", "false").lower() == "true"
    SUBSCRIPTION_GROUP_ID = int(getenv("SUBSCRIPTION_GROUP_ID", "0"))
    SUBSCRIPTION_URL = getenv("SUBSCRIPTION_URL", "https://t.me/")
    APPROVER_IDS = [int(x.strip()) for x in (getenv("APPROVER_IDS") or "").split(",") if x.strip().isdigit()]


class GDrive:
    FOLDER_ID = getenv("GDRIVE_FOLDER_ID", "")
    SCAN_INTERVAL_HOURS = int(getenv("GDRIVE_SCAN_INTERVAL_HOURS", "6"))