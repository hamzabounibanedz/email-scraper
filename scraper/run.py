"""Simple runner script for the scraper."""
import sys
from pathlib import Path

# Add scraper directory to path for imports
scraper_dir = Path(__file__).parent
sys.path.insert(0, str(scraper_dir))

from scripts.scraper import EmailScraper

if __name__ == "__main__":
    scraper = EmailScraper()
    scraper.run()
