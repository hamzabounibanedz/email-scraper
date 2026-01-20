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
CONNECT_TIMEOUT_SECONDS = float(os.getenv("SCRAPER_CONNECT_TIMEOUT", "8"))
READ_TIMEOUT_SECONDS = float(os.getenv("SCRAPER_READ_TIMEOUT", str(TIMEOUT_SECONDS)))
ROBOTS_TIMEOUT_SECONDS = float(os.getenv("SCRAPER_ROBOTS_TIMEOUT", "6"))
RETRY_ATTEMPTS = int(os.getenv("SCRAPER_RETRIES", "3"))
RETRY_BACKOFF_BASE = float(os.getenv("SCRAPER_BACKOFF", "1.0"))

# User-Agent rotation for better stealth
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]

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
    'generic', 'default', 'example',
    'elearning', 'e-learning', 'elearn',
    'authentification', 'auth', 'authentication',
    'vrp', 'vrex', 'vr-relex', 'vr-',  # Vice-rector emails
    'cei', 'ceil', 'lsp', 'laa',  # Department/service codes
    'xxx.xxx',  # Placeholder emails
]

# Logging
LOG_LEVEL = os.getenv("SCRAPER_LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "scraper.log"
