"""Main scraper script to extract .dz emails from university websites."""
import csv
import re
import time
import logging
import urllib.robotparser
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import List, Set, Dict, Optional
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
from tqdm import tqdm
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

import sys
# Add parent directory to path for config import
scraper_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scraper_dir))
from config import *


# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class EmailScraper:
    """Scraper for extracting .dz emails from university websites."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        self.visited_urls: Set[str] = set()
        self.robots_cache: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self.email_pattern = re.compile(r'[\w.\-+%]+@[\w.\-]+\.dz\b', re.IGNORECASE)
        
    def load_seeds(self) -> List[str]:
        """Load seed URLs from seeds.txt."""
        seeds = []
        if not SEEDS_FILE.exists():
            logger.warning(f"seeds.txt not found at {SEEDS_FILE}")
            return seeds
            
        with open(SEEDS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    seeds.append(line)
        
        logger.info(f"Loaded {len(seeds)} seed URLs")
        return seeds
    
    def get_robots_parser(self, url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        """Get robots.txt parser for a domain (cached)."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        if domain in self.robots_cache:
            return self.robots_cache[domain]
        
        robots_url = urljoin(domain, '/robots.txt')
        rp = urllib.robotparser.RobotFileParser()
        
        try:
            rp.set_url(robots_url)
            rp.read()
            logger.debug(f"Loaded robots.txt for {domain}")
        except Exception as e:
            logger.warning(f"Could not load robots.txt for {domain}: {e}")
            rp = None
        
        self.robots_cache[domain] = rp
        return rp
    
    def can_fetch(self, url: str) -> bool:
        """Check if URL can be fetched according to robots.txt."""
        rp = self.get_robots_parser(url)
        if rp is None:
            return True  # If robots.txt unavailable, proceed conservatively
        
        return rp.can_fetch(USER_AGENT, url)
    
    def get_crawl_delay(self, url: str) -> float:
        """Get crawl delay from robots.txt or use default."""
        rp = self.get_robots_parser(url)
        if rp is None:
            return REQUEST_DELAY_DEFAULT
        
        delay = rp.crawl_delay(USER_AGENT)
        return delay if delay else REQUEST_DELAY_DEFAULT
    
    def is_institutional_email(self, email: str) -> bool:
        """Check if email is an institutional/support email (not a real person)."""
        # Safety check - email must have @
        if '@' not in email:
            return False  # Not an email, can't be institutional
        
        try:
            local_part = email.split('@')[0].lower()
        except (ValueError, IndexError):
            return False  # Malformed email, skip
        
        # Check against excluded patterns
        for pattern in EXCLUDED_EMAIL_PATTERNS:
            if pattern in local_part:
                return True
        
        # Exclude emails that are too short (likely generic)
        if len(local_part) < 3:
            return True
        
        return False
    
    def extract_emails_from_text(self, text: str, source_url: str, source_type: str, 
                                  page_title: str = "") -> List[Dict]:
        """Extract .dz emails from text with context."""
        emails = []
        for match in self.email_pattern.finditer(text):
            email = match.group(0).lower()
            start, end = match.span()
            
            # Skip institutional/support emails
            if self.is_institutional_email(email):
                logger.debug(f"Skipping institutional email: {email}")
                continue
            
            # Get context snippet (100 chars before/after)
            context_start = max(0, start - 100)
            context_end = min(len(text), end + 100)
            context = text[context_start:context_end].strip()
            
            # Parse email parts (regex ensures @ exists, but add safety check)
            try:
                local_part, domain = email.split('@', 1)
            except ValueError:
                logger.debug(f"Skipping malformed email from regex: {email}")
                continue
            
            emails.append({
                'email': email,
                'local_part': local_part,
                'domain': domain,
                'source_url': source_url,
                'source_type': source_type,
                'page_title': page_title[:200] if page_title else "",
                'context_snippet': context[:200],
                'found_at': datetime.utcnow().isoformat(),
                'parse_method': f'regex_{source_type}',
                'notes': ''
            })
        
        return emails
    
    def fetch_html(self, url: str, retries: int = RETRY_ATTEMPTS) -> Optional[requests.Response]:
        """Fetch HTML page with retries."""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=TIMEOUT_SECONDS, allow_redirects=True)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                # Don't retry 404 (Not Found) or 403 (Forbidden) - these are permanent
                if e.response.status_code in [404, 403]:
                    logger.debug(f"Skipping {url} - {e.response.status_code} {e.response.reason}")
                    return None
                # Retry other HTTP errors (500, 502, 503, etc.)
                if attempt < retries - 1:
                    wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{retries} for {url} after {wait_time}s: {e.response.status_code} {e.response.reason}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to fetch {url} after {retries} attempts: {e.response.status_code} {e.response.reason}")
                    return None
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # Retry timeouts and connection errors
                if attempt < retries - 1:
                    wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{retries} for {url} after {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to fetch {url} after {retries} attempts: {e}")
                    return None
            except requests.exceptions.RequestException as e:
                # Other request exceptions
                if attempt < retries - 1:
                    wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{retries} for {url} after {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to fetch {url} after {retries} attempts: {e}")
                    return None
        return None
    
    def extract_emails_from_html(self, html: str, url: str) -> List[Dict]:
        """Extract emails from HTML page."""
        soup = BeautifulSoup(html, 'html.parser')
        page_title = soup.title.string if soup.title else ""
        
        # Extract text from HTML
        text = soup.get_text(separator=' ', strip=True)
        
        # Also check in href attributes (mailto links)
        mailto_emails = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('mailto:'):
                email = href.replace('mailto:', '').split('?')[0].strip()
                # Validate email has @ and ends with .dz
                if '@' in email and email.endswith('.dz'):
                    email_lower = email.lower()
                    # Skip institutional/support emails
                    if self.is_institutional_email(email_lower):
                        logger.debug(f"Skipping institutional mailto email: {email_lower}")
                        continue
                    
                    try:
                        local_part, domain = email_lower.split('@', 1)
                        mailto_emails.append({
                            'email': email_lower,
                            'local_part': local_part,
                            'domain': domain,
                            'source_url': url,
                            'source_type': 'html',
                            'page_title': page_title[:200] if page_title else "",
                            'context_snippet': link.get_text(strip=True)[:200],
                            'found_at': datetime.utcnow().isoformat(),
                            'parse_method': 'mailto_link',
                            'notes': ''
                        })
                    except ValueError:
                        # Skip malformed emails
                        logger.debug(f"Skipping malformed mailto email: {email}")
                        continue
        
        # Extract from text
        text_emails = self.extract_emails_from_text(text, url, 'html', page_title)
        
        return mailto_emails + text_emails
    
    def extract_pdf_links(self, html: str, base_url: str) -> List[str]:
        """Extract PDF links from HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        pdf_links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            
            # Check if it's a PDF
            if href.lower().endswith('.pdf') or 'application/pdf' in link.get('type', '').lower():
                parsed_base = urlparse(base_url)
                parsed_link = urlparse(full_url)
                
                # Only same-domain PDFs
                if parsed_base.netloc == parsed_link.netloc:
                    if self.can_fetch(full_url):
                        pdf_links.append(full_url)
        
        return pdf_links
    
    def download_and_parse_pdf(self, pdf_url: str) -> Optional[str]:
        """Download PDF and extract text."""
        try:
            response = self.session.get(pdf_url, timeout=TIMEOUT_SECONDS, stream=True)
            response.raise_for_status()
            
            # Save to downloads folder (handle filename collisions)
            filename = Path(pdf_url).name or "document.pdf"
            safe_filename = "".join(c for c in filename if c.isalnum() or c in ".-_")[:100]
            pdf_path = DOWNLOADS_DIR / safe_filename
            
            # Handle filename collisions by adding counter
            counter = 1
            original_path = pdf_path
            while pdf_path.exists():
                stem = original_path.stem
                suffix = original_path.suffix
                pdf_path = DOWNLOADS_DIR / f"{stem}_{counter}{suffix}"
                counter += 1
                if counter > 1000:  # Safety limit
                    logger.warning(f"Too many filename collisions for {pdf_url}")
                    return None
            
            # Write PDF to disk
            with open(pdf_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Extract text
            text = extract_text(str(pdf_path), laparams=LAParams())
            return text
            
        except requests.exceptions.HTTPError as e:
            # Don't log 404s as errors - broken PDF links are common
            if e.response.status_code == 404:
                logger.debug(f"PDF not found (404): {pdf_url}")
            else:
                logger.warning(f"Error downloading PDF {pdf_url}: {e.response.status_code} {e.response.reason}")
            return None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"Connection error downloading PDF {pdf_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_url}: {e}")
            return None
    
    def fetch_html_with_playwright(self, url: str) -> Optional[str]:
        """Fetch HTML using Playwright for JavaScript-rendered pages."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='networkidle', timeout=TIMEOUT_SECONDS * 1000)
                html = page.content()
                browser.close()
                return html
        except PlaywrightTimeout:
            logger.warning(f"Playwright timeout for {url}")
            return None
        except Exception as e:
            logger.error(f"Playwright error for {url}: {e}")
            return None
    
    def find_links_on_page(self, html: str, base_url: str) -> List[str]:
        """Find all links on a page (for crawling)."""
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            parsed_base = urlparse(base_url)
            parsed_link = urlparse(full_url)
            
            # Only same-domain links
            if parsed_base.netloc == parsed_link.netloc:
                if full_url not in self.visited_urls and self.can_fetch(full_url):
                    links.append(full_url)
        
        return links
    
    def scrape_domain(self, seed_url: str) -> List[Dict]:
        """Scrape a domain starting from seed URL."""
        logger.info(f"Scraping domain: {seed_url}")
        all_emails = []
        queue = [seed_url]
        pages_scraped = 0
        
        while queue and pages_scraped < MAX_PAGES_PER_DOMAIN:
            url = queue.pop(0)
            
            if url in self.visited_urls:
                continue
                
            if not self.can_fetch(url):
                logger.info(f"Skipping {url} (disallowed by robots.txt)")
                continue
            
            self.visited_urls.add(url)
            delay = self.get_crawl_delay(url)
            time.sleep(delay)
            
            # Fetch HTML once
            response = self.fetch_html(url)
            if response is None:
                continue
            
            html = response.text
            
            # Extract emails from HTML
            emails = self.extract_emails_from_html(html, url)
            
            # If no emails and page is small, try Playwright
            if len(emails) == 0 and len(html) < 5000:
                logger.info(f"Trying Playwright for {url} (small page, might be JS-rendered)")
                playwright_html = self.fetch_html_with_playwright(url)
                if playwright_html:
                    emails = self.extract_emails_from_html(playwright_html, url)
            
            # Skip PDF processing - we only want HTML emails from real pages
            # PDFs often contain generic/institutional emails, not teacher emails
            
            all_emails.extend(emails)
            pages_scraped += 1
            
            # Find more links to crawl (use the HTML we already fetched)
            if pages_scraped < MAX_PAGES_PER_DOMAIN:
                new_links = self.find_links_on_page(html, url)
                # Add to queue (limit to avoid too many)
                queue.extend(new_links[:20])
                queue = list(set(queue))  # Dedupe
        
        logger.info(f"Scraped {pages_scraped} pages from {seed_url}, found {len(all_emails)} email occurrences")
        return all_emails
    
    def save_raw_emails(self, emails: List[Dict]):
        """Save raw emails to CSV."""
        if not emails:
            return
        
        file_exists = OUTPUT_RAW.exists()
        
        with open(OUTPUT_RAW, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['email', 'local_part', 'domain', 'source_url', 'source_type',
                         'page_title', 'context_snippet', 'http_status', 'found_at',
                         'parse_method', 'notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            for email_data in emails:
                email_data['http_status'] = email_data.get('http_status', '200')
                writer.writerow(email_data)
        
        logger.info(f"Saved {len(emails)} raw email records to {OUTPUT_RAW}")
    
    def clean_and_dedupe_emails(self):
        """Clean and deduplicate emails from raw CSV."""
        if not OUTPUT_RAW.exists():
            logger.warning("No raw emails file found")
            return
        
        emails_dict: Dict[str, Dict] = {}
        
        try:
            with open(OUTPUT_RAW, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    logger.error("Raw CSV file is empty or has no headers")
                    return
                
                for row in reader:
                    # Validate required fields
                    if 'email' not in row or not row['email']:
                        continue
                    
                    email = row['email'].lower().strip()
                    if not email or '@' not in email:
                        continue
                    
                    if email not in emails_dict:
                        emails_dict[email] = {
                            'email': email,
                            'domain': row.get('domain', email.split('@')[1] if '@' in email else '').lower(),
                            'first_seen': row.get('found_at', datetime.utcnow().isoformat()),
                            'sources': row.get('source_url', ''),
                            'verified': 'false',
                            'status': 'unknown',
                            'notes': ''
                        }
                    else:
                        # Merge sources
                        new_source = row.get('source_url', '')
                        if new_source:
                            existing_sources = emails_dict[email]['sources'].split(';')
                            if new_source not in existing_sources:
                                emails_dict[email]['sources'] += ';' + new_source
                        
                        # Update first_seen if earlier
                        found_at = row.get('found_at', '')
                        if found_at and found_at < emails_dict[email]['first_seen']:
                            emails_dict[email]['first_seen'] = found_at
        except Exception as e:
            logger.error(f"Error reading raw CSV: {e}")
            return
        
        # Write clean CSV
        with open(OUTPUT_CLEAN, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['email', 'domain', 'first_seen', 'sources', 'verified', 'status', 'notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(emails_dict.values())
        
        logger.info(f"Created clean CSV with {len(emails_dict)} unique emails at {OUTPUT_CLEAN}")
    
    def run(self):
        """Main run method."""
        logger.info("Starting email scraper")
        
        seeds = self.load_seeds()
        if not seeds:
            logger.error("No seed URLs found. Please add URLs to seeds.txt")
            return
        
        all_emails = []
        
        for seed in tqdm(seeds, desc="Scraping domains"):
            try:
                emails = self.scrape_domain(seed)
                all_emails.extend(emails)
                self.save_raw_emails(emails)  # Save incrementally
            except Exception as e:
                logger.error(f"Error scraping {seed}: {e}")
                continue
        
        # Clean and deduplicate
        logger.info("Cleaning and deduplicating emails...")
        self.clean_and_dedupe_emails()
        
        logger.info(f"Scraping complete! Found {len(all_emails)} email occurrences")


if __name__ == "__main__":
    scraper = EmailScraper()
    scraper.run()
