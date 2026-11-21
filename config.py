import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

class Settings:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_ADMIN_ID: int = int(os.getenv("TELEGRAM_ADMIN_ID", "0"))
    
    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    
    # WAHA WhatsApp API (use 127.0.0.1 for explicit IPv4 in Docker)
    WAHA_URL: str = os.getenv("WAHA_URL", "http://127.0.0.1:3000").rstrip("/")
    WAHA_SESSION: str = os.getenv("WAHA_SESSION", "default").strip()
    WAHA_API_KEY: str = os.getenv("WAHA_API_KEY", "silentxop_waha_secure_key_2026").strip()
    
    # Database (Supabase PostgreSQL or fallback SQLite)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    SQLITE_PATH: Path = BASE_DIR / "data" / "assistant.db"
    
    # Server Port
    PORT: int = int(os.getenv("PORT", "10000"))
    
    # Anti-Spam & Delay Settings
    DEBOUNCE_SECONDS: int = 5         # Wait 5s for consecutive messages
    HUMAN_TYPING_DELAY: int = 3       # 3s typing indicator delay
    COOLDOWN_MINUTES: int = 15        # Don't repeat auto-replies to same user within 15 mins

settings = Settings()
