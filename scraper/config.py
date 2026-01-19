"""Configuration settings for the scraper."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
# Tries scraper/.env first, then falls back to root .env
# All scraper vars use SCRAPER_ prefix to avoid conflicts with n8n (N8N_ prefix)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()  # Fall back to root .env

# Base paths
BASE_DIR = Path(__file__).parent
SCRAPER_DIR = BASE_DIR
DATA_DIR = SCRAPER_DIR / "data"
DOWNLOADS_DIR = SCRAPER_DIR / "downloads"
LOGS_DIR = SCRAPER_DIR / "logs"
SEEDS_FILE = SCRAPER_DIR / "seeds.txt"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Scraper settings
USER_AGENT = os.getenv("SCRAPER_USER_AGENT", "UniversityEmailScraper/1.0 (Contact: your-email@example.com)")
REQUEST_DELAY_DEFAULT = float(os.getenv("SCRAPER_DELAY", "2.0"))  # seconds
MAX_PAGES_PER_DOMAIN = int(os.getenv("SCRAPER_MAX_PAGES", "50"))
TIMEOUT_SECONDS = int(os.getenv("SCRAPER_TIMEOUT", "15"))
RETRY_ATTEMPTS = int(os.getenv("SCRAPER_RETRIES", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("SCRAPER_BACKOFF", "1.0"))

# Output files
OUTPUT_RAW = DATA_DIR / "emails_raw.csv"
OUTPUT_CLEAN = DATA_DIR / "emails_clean.csv"

# Email filtering
ALLOWED_EMAIL_DOMAIN = ".dz"  # Only .dz emails

# Institutional email patterns to exclude (support, contact, generic emails)
EXCLUDED_EMAIL_PATTERNS = [
    'noreply', 'no-reply', 'donotreply',
    'contact', 'info', 'support', 'help',
    'webmaster', 'admin', 'administrator',
    'postmaster', 'abuse', 'security',
    'service', 'services', 'assistance',
    'secretariat', 'secretary', 'secretaire',
    'direction', 'directeur', 'director',
    'rectorat', 'rector', 'recteur',
    'communication', 'com', 'marketing',
    'presse', 'media', 'relations',
    'accueil', 'reception', 'welcome',
    'inscription', 'admission', 'registration',
    'biblio', 'bibliotheque', 'library',
    'technique', 'technical', 'tech',
    'system', 'systems', 'sysadmin',
    'test', 'testing', 'demo',
    'mail', 'email', 'courrier',
    'generic', 'default', 'example'
]

# Logging
LOG_LEVEL = os.getenv("SCRAPER_LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "scraper.log"
