"""Main scraper script to extract .dz emails from university websites."""
import csv
import re
import time
import logging
import urllib.robotparser
import random
from collections import deque
from pathlib import Path
from datetime import datetime
from typing import List, Set, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from urllib3.exceptions import NameResolutionError as Urllib3NameResolutionError
from bs4 import BeautifulSoup
from tqdm import tqdm
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Disable SSL warnings for sites with certificate issues
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    
    def __init__(self, max_workers: int = None):
        # Create session with connection pooling and retry strategy
        self.session = requests.Session()
        self._rotate_user_agent()
        self.session.verify = False  # Disable SSL verification for .dz sites
        
        # Configure retry strategy for robustness
        # Set connect=0 to fail fast on DNS/connection errors (no retries)
        # Only retry on HTTP status errors, not connection errors
        retry_strategy = Retry(
            total=RETRY_ATTEMPTS,
            connect=0,  # No retries on connection/DNS errors - fail fast
            read=RETRY_ATTEMPTS,  # Retry on read timeouts
            backoff_factor=RETRY_BACKOFF_BASE,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Separate session for robots.txt with NO retries and shorter timeout
        self.robots_session = requests.Session()
        self.robots_session.verify = False
        self.robots_session.headers.update({'User-Agent': self.session.headers.get('User-Agent', USER_AGENT)})
        # No retry adapter for robots.txt - fail fast (max_retries=0)
        no_retry_strategy = Retry(total=0)  # No retries at all
        no_retry_adapter = HTTPAdapter(max_retries=no_retry_strategy, pool_connections=5, pool_maxsize=10)
        self.robots_session.mount("http://", no_retry_adapter)
        self.robots_session.mount("https://", no_retry_adapter)
        
        # Thread-safe data structures
        self.visited_urls: Set[str] = set()
        self.visited_lock = Lock()
        self.robots_cache: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self.robots_lock = Lock()
        self.email_pattern = re.compile(r'[\w.\-+%]+@[\w.\-]+\.dz\b', re.IGNORECASE)
        self.max_workers = max_workers if max_workers is not None else MAX_WORKERS
        
        # HTML parser preference (lxml is faster, fallback to html.parser)
        try:
            import lxml
            self.html_parser = 'lxml'
        except ImportError:
            self.html_parser = 'html.parser'
            logger.warning("lxml not available, using html.parser (slower). Install with: pip install lxml")
    
    def _rotate_user_agent(self):
        """Rotate User-Agent header to avoid detection."""
        user_agent = random.choice(USER_AGENTS)
        self.session.headers.update({'User-Agent': user_agent})
        
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
        """Get robots.txt parser for a domain (cached, thread-safe, fast-fail)."""
        parsed = urlparse(url)
        original_host = parsed.netloc or ""
        if not original_host:
            return None
        
        # Cache robots per base domain (normalized without www and subdomains)
        # Use base domain so subdomains share the same robots.txt
        host = self._strip_www(original_host)
        # Extract base domain (e.g., 'univ-annaba.dz' from 'staff.univ-annaba.dz')
        parts = host.split('.')
        if len(parts) >= 2 and parts[-1] == 'dz':
            base_domain = '.'.join(parts[-2:])  # Get last 2 parts
        else:
            base_domain = host
        cache_key = base_domain
        
        # Check cache first (thread-safe)
        with self.robots_lock:
            if cache_key in self.robots_cache:
                return self.robots_cache[cache_key]
        
        rp = urllib.robotparser.RobotFileParser()
        
        # Try base domain only (subdomains typically share same robots.txt)
        # Use shorter timeout and no retries for robots.txt
        # All .dz sites use HTTPS - only try HTTPS
        robots_url = f"https://{base_domain}/robots.txt"
        try:
            resp = self.robots_session.get(
                robots_url,
                timeout=(2.0, 3.0),  # Very short timeout for robots.txt
                allow_redirects=True,
            )
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                logger.debug(f"Loaded robots.txt from {robots_url}")
                with self.robots_lock:
                    self.robots_cache[cache_key] = rp
                return rp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, 
                requests.exceptions.RequestException, Exception):
            pass  # robots.txt not available
        
        # If all attempts failed, cache None to avoid retrying
        with self.robots_lock:
            self.robots_cache[cache_key] = None
        return None

    def _strip_www(self, netloc: str) -> str:
        """Remove leading 'www.' from a hostname."""
        return netloc[4:] if netloc.startswith("www.") else netloc
    
    def can_fetch(self, url: str) -> bool:
        """Check if URL can be fetched according to robots.txt. Returns True to ignore robots.txt restrictions."""
        # Ignore robots.txt - user wants to scrape everything that's accessible
        # Many .dz sites have overly restrictive robots.txt that blocks legitimate content
        return True
    
    def get_crawl_delay(self, url: str) -> float:
        """Get crawl delay from robots.txt or use default."""
        rp = self.get_robots_parser(url)
        if rp is None:
            return REQUEST_DELAY_DEFAULT
        
        # Use current User-Agent from session (rotated) for robots.txt checking
        current_ua = self.session.headers.get('User-Agent', USER_AGENT)
        delay = rp.crawl_delay(current_ua)
        return delay if delay else REQUEST_DELAY_DEFAULT
    
    def is_institutional_email(self, email: str) -> bool:
        """Check if email is an institutional/support/administrative email (not a personal teacher email)."""
        # Safety check - email must have @
        if '@' not in email:
            return False  # Not an email, can't be institutional
        
        try:
            local_part = email.split('@')[0].lower()
        except (ValueError, IndexError):
            return False  # Malformed email, skip
        
        # Check against excluded patterns (case-insensitive substring match)
        for pattern in EXCLUDED_EMAIL_PATTERNS:
            pattern_lower = pattern.lower()
            if pattern_lower in local_part:
                return True
        
        # Exclude emails that are too short (likely generic)
        if len(local_part) < 3:
            return True
        
        # Exclude emails starting with admin prefixes (vr., doyen., chef., etc.)
        admin_prefixes = ['vr.', 'doyen.', 'chef.', 'directeur.', 'director.', 'admin.', 'service.']
        for prefix in admin_prefixes:
            if local_part.startswith(prefix):
                return True
        
        # Exclude short abbreviations (2-4 chars) that are likely admin codes
        if len(local_part) <= 4 and '.' not in local_part and '-' not in local_part:
            # If it's all uppercase or very short, likely an abbreviation
            if local_part.isupper() or len(local_part) <= 3:
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
        """Fetch HTML page with retries and robust .dz domain handling."""
        # All .dz sites use HTTPS - no need to try HTTP
        # Ensure URL uses HTTPS
        def ensure_https(u: str) -> str:
            try:
                parsed = urlparse(u)
                if not parsed.netloc:
                    return u
                # If no scheme or http, use https
                if not parsed.scheme or parsed.scheme == "http":
                    new_scheme = "https"
                    new_url = f"{new_scheme}://{parsed.netloc}"
                    if parsed.path:
                        new_url += parsed.path
                    elif not parsed.path and parsed.query:
                        new_url += "/"
                    if parsed.query:
                        new_url += f"?{parsed.query}"
                    if parsed.fragment:
                        new_url += f"#{parsed.fragment}"
                    return new_url
                return u
            except Exception:
                return u

        # Try www and non-www variants for .dz domains
        def try_www_variants(u: str) -> List[str]:
            variants = [u]
            try:
                parsed = urlparse(u)
                if not parsed.netloc:
                    return variants
                netloc = parsed.netloc
                scheme = parsed.scheme or 'https'
                
                if netloc.startswith('www.'):
                    # Try without www
                    new_netloc = netloc[4:]
                    new_url = f"{scheme}://{new_netloc}{parsed.path or '/'}"
                    if parsed.query:
                        new_url += f"?{parsed.query}"
                    if parsed.fragment:
                        new_url += f"#{parsed.fragment}"
                    variants.append(new_url)
                else:
                    # Try with www
                    new_netloc = f"www.{netloc}"
                    new_url = f"{scheme}://{new_netloc}{parsed.path or '/'}"
                    if parsed.query:
                        new_url += f"?{parsed.query}"
                    if parsed.fragment:
                        new_url += f"#{parsed.fragment}"
                    variants.append(new_url)
            except Exception:
                pass
            return variants

        # Ensure HTTPS and try all URL variants - prioritize trying different URLs over retrying same URL
        url = ensure_https(url)
        url_variants = try_www_variants(url)
        
        # For timeout/connection errors, reduce retries to 1 (fail fast)
        # For other errors, use normal retries
        timeout_retries = 1  # Fast fail on timeouts
        normal_retries = retries
        
        for url_to_try in url_variants:
            # Determine retry count based on error type (will be set in exception handler)
            current_retries = normal_retries
            
            for attempt in range(current_retries):
                try:
                    # Rotate User-Agent periodically
                    if attempt == 0 or random.random() < 0.3:
                        self._rotate_user_agent()
                    
                    # Add realistic browser headers to avoid detection
                    headers = {
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Cache-Control': 'max-age=0',
                        'Referer': 'https://www.google.com/',  # Fake referer
                    }
                    self.session.headers.update(headers)
                    
                    # Add random delay before request (human-like)
                    if attempt > 0:
                        time.sleep(random.uniform(2, 5))
                    
                    response = self.session.get(
                        url_to_try,
                        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                        allow_redirects=True,
                    )
                    response.raise_for_status()
                    return response
                except requests.exceptions.HTTPError as e:
                    # Don't retry 404 or 403
                    if e.response.status_code in [404, 403]:
                        if url_to_try == url_variants[-1]:  # Last variant
                            logger.warning(f"HTTP {e.response.status_code} for {url} - {e.response.reason}")
                            # For 403 on /websites, still try Playwright (might work)
                            if e.response.status_code == 403 and 'websites' in url.lower():
                                logger.info(f"Got 403 for {url}, will try Playwright as fallback")
                            return None
                        break  # Try next variant
                    # Retry other HTTP errors (but not too many times)
                    if attempt < current_retries - 1:
                        wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                        time.sleep(min(wait_time, 2.0))  # Cap wait time at 2 seconds
                    elif url_to_try == url_variants[-1]:  # Last variant and last attempt
                        logger.debug(f"Failed to fetch {url} after {current_retries} attempts: {e.response.status_code}")
                        return None
                except (Urllib3NameResolutionError, requests.exceptions.ConnectionError) as e:
                    # DNS failures (NameResolutionError): fail immediately, no retries
                    # Check if this is a DNS resolution error (domain doesn't exist)
                    error_str = str(e).lower()
                    is_dns_error = (
                        isinstance(e, Urllib3NameResolutionError) or
                        'getaddrinfo failed' in error_str or
                        'name resolution' in error_str or
                        'failed to resolve' in error_str
                    )
                    
                    if is_dns_error:
                        # DNS failure - domain doesn't exist, fail immediately (no retries)
                        logger.debug(f"DNS resolution failed for {url_to_try} - domain does not exist")
                        if url_to_try == url_variants[-1]:
                            return None
                        break  # Try next variant, but likely will also fail
                    else:
                        # Other connection errors (network issues) - no HTTP fallback, just try next variant
                        # If this is the first attempt and we have more variants, try next variant
                        if attempt == 0 and url_to_try != url_variants[-1]:
                            break  # Try next variant
                        # Otherwise fail
                        if url_to_try == url_variants[-1]:
                            logger.debug(f"Connection error for {url} - skipping")
                            return None
                except requests.exceptions.Timeout as e:
                    # Timeouts: fail fast, try next variant immediately (no HTTP fallback)
                    # If this is the first attempt and we have more variants, try next variant immediately
                    if attempt == 0 and url_to_try != url_variants[-1]:
                        break  # Try next variant immediately
                    
                    # If this is last variant, fail fast (no more retries for timeouts)
                    if url_to_try == url_variants[-1]:
                        logger.debug(f"Timeout for {url} - skipping after {attempt + 1} attempt(s)")
                        return None
                except requests.exceptions.SSLError:
                    # SSL errors: skip this variant, try next (no HTTP fallback - all sites use HTTPS)
                    # Try next variant
                    if url_to_try == url_variants[-1]:
                        logger.debug(f"SSL error for {url} - skipping")
                        return None
                    break  # Try next variant
                except requests.exceptions.RequestException as e:
                    # Other request exceptions: retry a few times
                    if attempt < current_retries - 1:
                        wait_time = RETRY_BACKOFF_BASE * (2 ** attempt)
                        time.sleep(min(wait_time, 2.0))  # Cap wait time at 2 seconds
                    elif url_to_try == url_variants[-1]:
                        logger.debug(f"Failed to fetch {url} after {current_retries} attempts: {e}")
                        return None
        
        return None
    
    def extract_emails_from_html(self, html: str, url: str) -> List[Dict]:
        """Extract emails from HTML page - checks multiple sources."""
        try:
            soup = BeautifulSoup(html, self.html_parser)
        except Exception:
            # Fallback to html.parser if lxml fails
            soup = BeautifulSoup(html, 'html.parser')
        page_title = soup.title.string if soup.title else ""
        
        all_emails = []
        
        # 1. Extract from mailto: links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('mailto:'):
                email = href.replace('mailto:', '').split('?')[0].strip()
                if '@' in email and email.endswith('.dz'):
                    email_lower = email.lower()
                    if not self.is_institutional_email(email_lower):
                        try:
                            local_part, domain = email_lower.split('@', 1)
                            all_emails.append({
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
                            continue
        
        # 2. Extract from data attributes (data-email, data-contact, etc.)
        for tag in soup.find_all(attrs={'data-email': True}):
            email = tag.get('data-email', '').strip()
            if '@' in email and email.endswith('.dz'):
                email_lower = email.lower()
                if not self.is_institutional_email(email_lower):
                    try:
                        local_part, domain = email_lower.split('@', 1)
                        all_emails.append({
                            'email': email_lower,
                            'local_part': local_part,
                            'domain': domain,
                            'source_url': url,
                            'source_type': 'html',
                            'page_title': page_title[:200] if page_title else "",
                            'context_snippet': tag.get_text(strip=True)[:200],
                            'found_at': datetime.utcnow().isoformat(),
                            'parse_method': 'data_attribute',
                            'notes': ''
                        })
                    except ValueError:
                        continue
        
        # 3. Extract from meta tags (some sites put contact emails in meta)
        for meta in soup.find_all('meta', attrs={'content': True}):
            content = meta.get('content', '')
            if '@' in content and '.dz' in content:
                # Use regex to find emails in meta content
                for match in self.email_pattern.finditer(content):
                    email = match.group(0).lower()
                    if not self.is_institutional_email(email):
                        try:
                            local_part, domain = email.split('@', 1)
                            all_emails.append({
                                'email': email,
                                'local_part': local_part,
                                'domain': domain,
                                'source_url': url,
                                'source_type': 'html',
                                'page_title': page_title[:200] if page_title else "",
                                'context_snippet': content[:200],
                                'found_at': datetime.utcnow().isoformat(),
                                'parse_method': 'meta_tag',
                                'notes': ''
                            })
                        except ValueError:
                            continue
        
        # 4. Extract from all text content (main extraction method)
        text = soup.get_text(separator=' ', strip=True)
        text_emails = self.extract_emails_from_text(text, url, 'html', page_title)
        all_emails.extend(text_emails)
        
        # Debug: Log email extraction results
        if text_emails:
            logger.info(f"Found {len(text_emails)} emails in text content for {url}")
        elif '@' in text and '.dz' in text:
            # If we see @ and .dz but no emails found, might be filtered or wrong format
            logger.debug(f"Found @ and .dz in text but no emails extracted from {url} (might be filtered)")
        
        # 5. Extract from script tags (JSON-LD, JavaScript variables, etc.)
        for script in soup.find_all('script'):
            if script.string:
                script_text = script.string
                for match in self.email_pattern.finditer(script_text):
                    email = match.group(0).lower()
                    if not self.is_institutional_email(email):
                        try:
                            local_part, domain = email.split('@', 1)
                            all_emails.append({
                                'email': email,
                                'local_part': local_part,
                                'domain': domain,
                                'source_url': url,
                                'source_type': 'html',
                                'page_title': page_title[:200] if page_title else "",
                                'context_snippet': script_text[max(0, match.start()-50):match.end()+50][:200],
                                'found_at': datetime.utcnow().isoformat(),
                                'parse_method': 'script_tag',
                                'notes': ''
                            })
                        except ValueError:
                            continue
        
        # Deduplicate emails found from same page
        seen_emails = set()
        unique_emails = []
        for email_dict in all_emails:
            email_key = email_dict['email']
            if email_key not in seen_emails:
                seen_emails.add(email_key)
                unique_emails.append(email_dict)
        
        return unique_emails
    
    def fetch_html_with_playwright(self, url: str) -> Optional[str]:
        """Fetch HTML using Playwright for JavaScript-rendered pages."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    # Playwright timeout is in milliseconds
                    # Use 'domcontentloaded' first, then wait a bit for JS to render
                    page.goto(url, wait_until='domcontentloaded', timeout=int(TIMEOUT_SECONDS * 1000))
                    # Wait a bit for JavaScript to render content (especially for /websites pages)
                    page.wait_for_timeout(3000)  # Wait 3 seconds for JS to render
                    # Try to wait for content to load (if there are specific selectors)
                    try:
                        # Wait for table or main content to appear
                        page.wait_for_selector('table, main, .content', timeout=5000)
                    except:
                        pass  # Continue even if selector doesn't appear
                    html = page.content()
                    # Also get the rendered text to check for emails
                    text_content = page.inner_text('body')
                    page_title = page.title()
                    
                    # Debug: Check if page loaded correctly
                    if '403' in page_title or 'forbidden' in page_title.lower() or 'access denied' in text_content.lower():
                        logger.warning(f"Playwright got 403/forbidden page for {url}")
                    else:
                        logger.info(f"Playwright loaded page successfully: {page_title[:50]}")
                    
                    # Debug: Check for email-like content
                    email_count = text_content.count('@')
                    dz_count = text_content.count('.dz')
                    if email_count > 0 and dz_count > 0:
                        logger.info(f"Found {email_count} '@' symbols and {dz_count} '.dz' in page text for {url}")
                    elif email_count > 0:
                        logger.debug(f"Found {email_count} '@' symbols but no '.dz' in page text for {url}")
                    
                    return html
                finally:
                    # Ensure browser is closed even on exception
                    browser.close()
        except PlaywrightTimeout:
            logger.warning(f"Playwright timeout for {url}")
            return None
        except Exception as e:
            logger.error(f"Playwright error for {url}: {e}")
            return None
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL to prevent duplicates (remove trailing slash, default scheme)."""
        try:
            parsed = urlparse(url)
            # Skip if no netloc (invalid URL)
            if not parsed.netloc:
                return url
            # Default to https if no scheme
            scheme = parsed.scheme or 'https'
            # Remove trailing slash from path (except root)
            path = parsed.path.rstrip('/') or '/'
            # Reconstruct URL
            normalized = f"{scheme}://{parsed.netloc}{path}"
            if parsed.query:
                normalized += f"?{parsed.query}"
            if parsed.fragment:
                normalized += f"#{parsed.fragment}"
            return normalized
        except Exception:
            return url
    
    def is_same_base_domain(self, url1: str, url2: str) -> bool:
        """Check if two URLs belong to the same base domain (including subdomains)."""
        try:
            parsed1 = urlparse(url1)
            parsed2 = urlparse(url2)
            
            # Extract base domain (e.g., 'univ-batna2.dz' from 'staff.univ-batna2.dz')
            def get_base_domain(netloc: str) -> str:
                if not netloc:
                    return ''
                parts = netloc.split('.')
                # For .dz domains, take last 2 parts (e.g., 'univ-batna2.dz')
                # Handles: staff.univ-batna2.dz -> univ-batna2.dz
                # Handles: mail.univ-tlemcen.dz -> univ-tlemcen.dz
                if len(parts) >= 2 and parts[-1] == 'dz':
                    return '.'.join(parts[-2:])
                return netloc
            
            base1 = get_base_domain(parsed1.netloc)
            base2 = get_base_domain(parsed2.netloc)
            
            # Both must have valid base domains
            if not base1 or not base2:
                return False
            
            # Allow http/https to be considered the same
            schemes_match = (parsed1.scheme == parsed2.scheme or 
                           (parsed1.scheme in ['http', 'https', ''] and 
                            parsed2.scheme in ['http', 'https', '']))
            
            return base1 == base2 and schemes_match
        except Exception:
            return False
    
    def find_links_on_page(self, html: str, base_url: str) -> List[str]:
        """Find all links on a page (for crawling), including subdomains."""
        try:
            soup = BeautifulSoup(html, self.html_parser)
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')
        
        # Keywords that suggest pages with staff/contact information
        priority_keywords = ['staff', 'websites', 'contact', 'personnel', 'enseignants', 
                             'professeurs', 'equipe', 'team', 'annuaire', 'directory',
                             'faculte', 'faculty', 'departement', 'department', 'corps',
                             'enseignant', 'professeur', 'chercheur', 'researcher']
        
        # Keywords for faculties/majors/departments (critical for finding teacher emails)
        faculty_keywords = [
            'faculte', 'faculty', 'facultes', 'faculties',
            'departement', 'department', 'departements', 'departments',
            'filiere', 'filiere', 'specialite', 'speciality',
            'formation', 'formation', 'domaine', 'domain',
            'section', 'section', 'option', 'option',
            'mathematiques', 'mathematics', 'math', 'fmath',
            'informatique', 'computer', 'info', 'cs',
            'physique', 'physics', 'phys',
            'chimie', 'chemistry', 'chim',
            'biologie', 'biology', 'bio',
            'electronique', 'electronics', 'elec',
            'mecanique', 'mechanical', 'meca',
            'genie', 'engineering', 'civil', 'archi',
            'economie', 'economics', 'eco',
            'droit', 'law', 'juridique',
            'lettres', 'literature', 'langues',
            'philosophie', 'philosophy', 'philo',
            'sociologie', 'sociology', 'socio',
            'psychologie', 'psychology', 'psy',
            'medecine', 'medicine', 'med',
            'pharmacie', 'pharmacy', 'pharma',
            'sciences', 'sciences', 'sci',
            'islamiques', 'islamic', 'fsi'
        ]
        
        priority_links = []
        regular_links = []
        subdomain_links = []  # Subdomain links get highest priority
        faculty_links = []  # Faculty/major links get highest priority (even above subdomains)
        teacher_links = []  # Teacher name links (e.g., /yahiaoui-kais) - HIGHEST PRIORITY
        contact_links = []  # Contact links (especially on teacher pages) - HIGHEST PRIORITY
        seen_urls = set()  # Track normalized URLs to avoid duplicates
        
        # Check if current page is a teacher page (URL pattern like /firstname-lastname or /lastname-firstname)
        base_parsed = urlparse(base_url)
        path_parts = [p for p in base_parsed.path.split('/') if p]
        is_teacher_page = (
            len(path_parts) >= 1 and 
            '-' in path_parts[-1] and  # Has hyphen (firstname-lastname pattern)
            not any(kw in base_parsed.path.lower() for kw in ['websites', 'contact', 'page', 'admin'])
        )
        
        # Also check for links in text content (some sites embed URLs in text)
        text_content = soup.get_text()
        # Find URLs in text that match our domain pattern
        text_urls = re.findall(r'https?://[^\s<>"\']+\.dz[^\s<>"\']*', text_content, re.IGNORECASE)
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            parsed_link = urlparse(full_url)
            
            # Skip non-HTTP(S) links
            if parsed_link.scheme not in ['http', 'https', '']:
                continue
            
            # Skip login/admin pages early (they cause Playwright timeouts and have no emails)
            href_lower = href.lower()
            if any(skip in href_lower for skip in ['/user?', '/login', '/admin', 'admin_panel', '?login=', '&login=']):
                continue
            
            # Normalize URL
            normalized_url = self.normalize_url(full_url)
            
            # Skip if already seen in this page
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            
            # Check if it's the same base domain (including subdomains)
            if self.is_same_base_domain(base_url, normalized_url):
                # Skip robots.txt check in find_links - it's done later when actually crawling
                # This avoids hundreds of robots.txt requests for non-existent subdomains
                # Check if this is a subdomain link (higher priority)
                base_parsed = urlparse(base_url)
                link_parsed = urlparse(normalized_url)
                is_subdomain = (link_parsed.netloc != base_parsed.netloc and 
                               self.is_same_base_domain(base_url, normalized_url))
                
                # Check if link text or URL contains keywords
                link_text = link.get_text(strip=True).lower()
                url_lower = normalized_url.lower()
                link_parsed = urlparse(normalized_url)
                link_path_parts = [p for p in link_parsed.path.split('/') if p]
                
                # Check if this is a "Contact" link (CRITICAL for teacher pages)
                is_contact_link = (
                    'contact' in link_text or 
                    'contact' in url_lower or
                    link_parsed.path.endswith('/contact')
                )
                
                # Check if this is a teacher name link (URL pattern like /firstname-lastname)
                # Teacher links typically have hyphenated names in the URL
                is_teacher_name_link = (
                    len(link_path_parts) >= 1 and
                    '-' in link_path_parts[-1] and  # Has hyphen (name pattern)
                    not any(kw in url_lower for kw in ['websites', 'contact', 'page', 'admin', 'login']) and
                    link_path_parts[-1].count('-') >= 1 and  # At least one hyphen
                    len(link_path_parts[-1].split('-')) >= 2  # Has at least 2 parts (firstname-lastname)
                )
                
                # Enhanced keywords for finding teacher emails
                teacher_keywords = priority_keywords + [
                    'enseignant', 'enseignants', 'professeur', 'professeurs',
                    'teacher', 'teachers', 'faculty', 'staff', 'personnel',
                    'annuaire', 'directory', 'contact', 'equipe', 'team'
                ]
                is_priority = any(keyword in link_text or keyword in url_lower 
                                for keyword in teacher_keywords)
                
                # Check if this is a faculty/major/department link
                is_faculty_link = any(keyword in link_text or keyword in url_lower 
                                     for keyword in faculty_keywords)
                
                # Detect pagination links (especially for /websites pages)
                # Check for pagination patterns: /websites?page=, ?page=, ?p=, numeric links, next/last links
                is_pagination = (
                    ('websites' in url_lower and ('page=' in url_lower or '&page=' in url_lower)) or
                    ('page=' in url_lower or '&page=' in url_lower or '?page=' in url_lower) or
                    ('p=' in url_lower or '&p=' in url_lower or '?p=' in url_lower) or
                    (link_text.isdigit() and link_text != '') or
                    link_text.lower() in ['next', 'suivant', '»', 'last', 'dernier', 'precedent', 'previous', '«'] or
                    ('websites' in base_url.lower() and link_text.isdigit())
                )
                
                # Priority order: Contact links (on teacher pages) > Pagination > Teacher name links > Faculty > Subdomains > Priority > Regular
                # Pagination is CRITICAL - need to get all 55 pages before following teacher links
                if is_contact_link and is_teacher_page:
                    # Contact link on teacher page - HIGHEST PRIORITY (leads directly to email)
                    contact_links.append(normalized_url)
                elif is_contact_link:
                    # Contact link anywhere - also high priority
                    contact_links.append(normalized_url)
                elif is_pagination:
                    # Pagination links - VERY HIGH PRIORITY (need all pages to find all teachers)
                    # Put pagination BEFORE teacher links so we get all pages first
                    priority_links.insert(0, normalized_url)  # Insert at front for highest priority
                elif is_teacher_name_link:
                    # Teacher name link - very high priority (leads to teacher page, then contact)
                    teacher_links.append(normalized_url)
                elif is_faculty_link:
                    faculty_links.append(normalized_url)
                elif is_subdomain:
                    subdomain_links.append(normalized_url)
                elif is_priority:
                    priority_links.append(normalized_url)
                else:
                    regular_links.append(normalized_url)
        
        # Also process URLs found in text content
        for text_url in text_urls:
            try:
                normalized_text_url = self.normalize_url(text_url)
                if (normalized_text_url not in seen_urls and 
                    self.is_same_base_domain(base_url, normalized_text_url)):
                    seen_urls.add(normalized_text_url)
                    base_parsed = urlparse(base_url)
                    text_parsed = urlparse(normalized_text_url)
                    is_subdomain = (text_parsed.netloc != base_parsed.netloc and 
                                   self.is_same_base_domain(base_url, normalized_text_url))
                    url_lower = normalized_text_url.lower()
                    is_priority = any(keyword in url_lower for keyword in priority_keywords)
                    
                    if is_subdomain:
                        subdomain_links.append(normalized_text_url)
                    elif is_priority:
                        priority_links.append(normalized_text_url)
                    else:
                        regular_links.append(normalized_text_url)
            except Exception:
                continue
        
        # Return links in priority order:
        # 1. Contact links (HIGHEST - especially on teacher pages, lead directly to emails)
        # 2. Pagination links (CRITICAL - need all pages to find all teachers, e.g., 55 pages)
        # 3. Teacher name links (very high - lead to teacher pages, then contact)
        # 4. Faculty/major links (high - lead to department pages with teachers)
        # 5. Subdomain links (important for finding department subdomains)
        # 6. Priority links (teacher/staff related)
        # 7. Regular links (everything else)
        return contact_links + priority_links + teacher_links + faculty_links + subdomain_links + regular_links
    
    def _discover_subdomains_from_html(self, html: str, base_url: str) -> List[str]:
        """Discover subdomain URLs from HTML content (finds department subdomains like fmath.usthb.dz).
        Only uses actual links, not text mentions, to avoid false positives."""
        discovered = []
        try:
            soup = BeautifulSoup(html, self.html_parser)
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')
        
        base_parsed = urlparse(base_url)
        base_domain_no_www = self._strip_www(base_parsed.netloc)
        
        # Find all links that point to subdomains (only actual links, not text)
        # If a subdomain is in an actual link on the website, it likely exists - try it
        # No hardcoded patterns - only use what's actually linked on the website
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            parsed_link = urlparse(full_url)
            
            if not parsed_link.netloc:
                continue
            
            # Check if it's a subdomain of the base domain
            link_domain_no_www = self._strip_www(parsed_link.netloc)
            if (link_domain_no_www != base_domain_no_www and 
                link_domain_no_www.endswith('.' + base_domain_no_www)):
                # If it's linked on the website, it's likely valid - add it
                # DNS errors will filter out non-existent ones quickly (connect=0 retries)
                normalized = self.normalize_url(full_url)
                if self.is_same_base_domain(base_url, normalized) and normalized not in discovered:
                    discovered.append(normalized)
        
        # Don't search in text content - too many false positives
        # Only use actual links found in HTML
        
        return discovered
    
    def discover_subdomain_pages(self, base_url: str) -> List[str]:
        """Discover subdomain pages that likely contain teacher emails.
        Uses smart patterns for common department subdomains (e.g., fmath.usthb.dz for math department).
        These are tried because they commonly exist and contain teacher directories."""
        parsed = urlparse(base_url)
        base_domain = parsed.netloc
        if not base_domain:
            return []
        
        scheme = parsed.scheme or 'https'
        discovered = set()
        base_domain_no_www = self._strip_www(base_domain)
        
        # Smart department subdomain patterns - only the most common ones that typically have teacher emails
        # These are based on actual Algerian university patterns
        # Short codes are more likely to exist than full words
        common_dept_subdomains = [
            # Math/Computer Science (very common)
            'fmath', 'math', 'info', 'informatique',
            # Sciences
            'phys', 'chim', 'bio', 'fbiol',
            # Engineering
            'elec', 'meca', 'civil', 'archi',
            # Other departments
            'eco', 'droit', 'lettres', 'philo', 'socio', 'psy'
        ]
        
        # Try these common department subdomains - they're likely to exist and have teacher emails
        for dept in common_dept_subdomains:
            subdomain_url = f"{scheme}://{dept}.{base_domain_no_www}"
            normalized = self.normalize_url(subdomain_url)
            if self.is_same_base_domain(base_url, normalized):
                discovered.add(normalized)
        
        return list(discovered)
    
    def _process_url(self, url: str, seed_url: str) -> Tuple[str, Optional[List[Dict]], Optional[str], List[str]]:
        """Process a single URL and return emails, HTML, and new links (thread-safe)."""
        # Skip login/admin pages early (before fetching) - they're not useful and cause Playwright timeouts
        url_lower = url.lower()
        if any(skip in url_lower for skip in ['/user?', '/login', '/admin', 'admin_panel', '?login=', '&login=']):
            logger.debug(f"Skipping login/admin page: {url}")
            return url, None, None, []
        
        # Check if already visited (thread-safe)
        with self.visited_lock:
            if url in self.visited_urls:
                return url, None, None, []
            # Mark as visited immediately to prevent duplicate processing
            self.visited_urls.add(url)
        
        # Check robots.txt (outside lock to avoid blocking, but robots.txt is cached so it's fast)
        if not self.can_fetch(url):
            logger.debug(f"Skipping {url} (disallowed by robots.txt)")
            return url, None, None, []
        
        # Get crawl delay
        delay = self.get_crawl_delay(url)
        if delay > 0:
            time.sleep(delay)
        
        # Fetch HTML
        response = self.fetch_html(url)
        html = None
        emails = []
        
        if response is None:
            # If fetch_html failed (403, etc.), try Playwright directly for /websites pages
            if 'websites' in url_lower and not any(skip in url_lower for skip in ['/user?', '/login', '/admin', 'admin_panel', '?login=', '&login=']):
                logger.info(f"Regular fetch failed for {url}, trying Playwright")
                try:
                    playwright_html = self.fetch_html_with_playwright(url)
                    if playwright_html:
                        html = playwright_html
                        emails = self.extract_emails_from_html(html, url)
                        logger.info(f"Playwright succeeded for {url}, found {len(emails)} emails")
                    else:
                        logger.warning(f"Playwright also failed for {url}")
                        return url, None, None, []
                except Exception as e:
                    logger.warning(f"Playwright failed for {url}: {e}")
                    return url, None, None, []
            else:
                logger.debug(f"Failed to fetch {url} - response is None")
                return url, None, None, []
        else:
            # Ensure proper encoding (handle .dz domain encoding issues)
            if response.encoding is None:
                response.encoding = 'utf-8'
            try:
                html = response.text
            except UnicodeDecodeError:
                # Try to decode with different encodings common in .dz sites
                for encoding in ['iso-8859-1', 'windows-1256', 'utf-8']:
                    try:
                        html = response.content.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    logger.warning(f"Could not decode {url}, skipping")
                    return url, None, None, []
            
            # Extract emails from HTML
            emails = self.extract_emails_from_html(html, url)
            
            # For /websites pages, ALWAYS try Playwright - emails might be in JS-rendered content
            # Also try Playwright if no emails found and page is small
            # BUT skip Playwright for login/admin pages (they cause timeouts and have no emails)
            should_try_playwright = (
                'websites' in url_lower or  # ALL /websites pages - emails might be JS-rendered
                (len(emails) == 0 and len(html) < 10000)
            ) and not any(skip in url_lower for skip in ['/user?', '/login', '/admin', 'admin_panel', '?login=', '&login='])
            
            if should_try_playwright:
                try:
                    logger.debug(f"Trying Playwright for {url} (websites page or no emails found)")
                    playwright_html = self.fetch_html_with_playwright(url)
                    if playwright_html:
                        emails = self.extract_emails_from_html(playwright_html, url)
                        logger.debug(f"Playwright found {len(emails)} emails on {url}")
                        # Use Playwright HTML for link discovery too (it has the rendered content)
                        html = playwright_html
                except Exception as e:
                    logger.debug(f"Playwright failed for {url}: {e}")
        
        # Find links on page
        new_links = self.find_links_on_page(html, url)
        
        return url, emails, html, new_links
    
    def scrape_domain(self, seed_url: str) -> List[Dict]:
        """Scrape a domain starting from seed URL, including subdomains (optimized with concurrency)."""
        logger.info(f"Scraping domain: {seed_url}")
        all_emails = []
        
        # Normalize seed URL
        normalized_seed = self.normalize_url(seed_url)
        
        # Check if seed URL is already a subdomain (like staff.univ-batna2.dz)
        # If so, skip subdomain discovery - go directly to the page
        seed_parsed = urlparse(normalized_seed)
        seed_domain = seed_parsed.netloc
        seed_domain_no_www = self._strip_www(seed_domain)
        
        # Extract base domain (for .dz domains, base is last 2 parts, e.g., univ-batna2.dz)
        domain_parts = seed_domain_no_www.split('.')
        if len(domain_parts) >= 2 and domain_parts[-1] == 'dz':
            base_domain_parts = domain_parts[-2:]  # Last 2 parts (e.g., ['univ-batna2', 'dz'])
            base_domain = '.'.join(base_domain_parts)
        else:
            base_domain = seed_domain_no_www
        
        # Check if it's already a subdomain (has more parts than base domain)
        # For staff.univ-batna2.dz: domain_parts = ['staff', 'univ-batna2', 'dz'] (3 parts)
        # base_domain = 'univ-batna2.dz' (2 parts) -> is subdomain
        is_already_subdomain = len(domain_parts) > len(base_domain.split('.'))
        
        discovered_subdomains = []
        
        # Only try subdomain discovery if NOT already on a subdomain
        if not is_already_subdomain:
            # First, try common department subdomains that typically have teacher emails
            common_subdomains = self.discover_subdomain_pages(normalized_seed)
            discovered_subdomains.extend(common_subdomains)
            logger.info(f"Trying {len(common_subdomains)} common department subdomains for teacher emails")
            
            # Then, fetch main page to discover additional subdomains from actual links
            try:
                main_page_response = self.fetch_html(normalized_seed)
                if main_page_response:
                    main_page_html = main_page_response.text
                    # Find subdomain links in the main page (only actual links)
                    discovered_from_main = self._discover_subdomains_from_html(main_page_html, normalized_seed)
                    discovered_subdomains.extend(discovered_from_main)
                    logger.info(f"Discovered {len(discovered_from_main)} additional subdomains from main page links")
            except Exception as e:
                logger.debug(f"Could not fetch main page for subdomain discovery: {e}")
        else:
            logger.info(f"Seed URL is already a subdomain ({seed_domain}), skipping subdomain discovery - going directly to page")
        
        # Remove duplicates
        discovered_subdomains = list(set(discovered_subdomains))
        if discovered_subdomains:
            logger.info(f"Total {len(discovered_subdomains)} unique subdomains to try")
        
        # Initialize queue with seed (and discovered subdomains if any)
        queue = deque([normalized_seed] + discovered_subdomains)
        seen_in_queue = {normalized_seed} | set(discovered_subdomains)
        
        pages_scraped = 0
        max_queue_size = MAX_PAGES_PER_DOMAIN * 5  # Increased queue size for large sites (55 pages × teachers × contact pages)
        consecutive_failures = 0
        max_consecutive_failures = 100  # Very high threshold - don't stop early, keep trying to find links
        # DNS failures don't count as consecutive failures (they're expected for non-existent subdomains)
        
        # Use ThreadPoolExecutor for concurrent processing
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while queue and pages_scraped < MAX_PAGES_PER_DOMAIN:
                # Safety check
                if len(queue) > max_queue_size:
                    logger.warning(f"Queue size exceeded {max_queue_size}, stopping crawl for {seed_url}")
                    break
                
                # Process batch of URLs concurrently
                batch_size = min(self.max_workers, len(queue), MAX_PAGES_PER_DOMAIN - pages_scraped)
                if batch_size == 0:
                    break
                
                batch_urls = [queue.popleft() for _ in range(batch_size)]
                future_to_url = {executor.submit(self._process_url, url, normalized_seed): url 
                                for url in batch_urls}
                
                batch_emails = []
                batch_new_links = []
                
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        processed_url, emails, html, new_links = future.result()
                        
                        # If we got HTML or emails, it's a successful fetch
                        if html is not None:
                            # Successfully fetched page
                            consecutive_failures = 0
                            pages_scraped += 1
                            
                            if emails:
                                batch_emails.extend(emails)
                            
                            if new_links:
                                batch_new_links.extend(new_links)
                        else:
                            # Failed to fetch (None returned)
                            # Only increment if we have links in queue (means we're still trying)
                            # If queue is empty and we failed, that's a real failure
                            if len(queue) > 0 or len(batch_new_links) > 0:
                                # We have more links to try, don't count this as a failure yet
                                consecutive_failures = min(consecutive_failures, 5)  # Cap at 5
                            else:
                                consecutive_failures += 1
                            
                    except Exception as e:
                        logger.error(f"Error processing {url}: {e}")
                        consecutive_failures += 1
                
                # Add emails found in this batch
                all_emails.extend(batch_emails)
                
                # Add new links to queue (prioritize pagination, contact, and teacher name links)
                contact_links = []
                teacher_links = []
                faculty_links = []
                subdomain_links = []
                priority_links = []
                regular_links = []
                
                # Keywords for faculties/majors/departments
                faculty_keywords = [
                    'faculte', 'faculty', 'facultes', 'faculties',
                    'departement', 'department', 'departements', 'departments',
                    'filiere', 'specialite', 'formation', 'domaine',
                    'section', 'option', 'mathematiques', 'informatique',
                    'physique', 'chimie', 'biologie', 'electronique',
                    'mecanique', 'genie', 'economie', 'droit',
                    'lettres', 'philosophie', 'sociologie', 'psychologie',
                    'medecine', 'pharmacie', 'sciences', 'islamiques', 'fsi'
                ]
                
                for link in batch_new_links:
                    normalized_link = self.normalize_url(link)
                    if normalized_link in seen_in_queue:
                        continue
                    
                    with self.visited_lock:
                        if normalized_link in self.visited_urls:
                            continue
                    
                    # Check if it's a subdomain
                    base_parsed = urlparse(normalized_seed)
                    link_parsed = urlparse(normalized_link)
                    is_subdomain = (link_parsed.netloc != base_parsed.netloc and 
                                   self.is_same_base_domain(normalized_seed, normalized_link))
                    
                    # Check for priority keywords
                    priority_keywords = ['staff', 'websites', 'contact', 'personnel', 'enseignants',
                                       'professeurs', 'annuaire', 'directory']
                    url_lower = normalized_link.lower()
                    is_priority = any(kw in url_lower for kw in priority_keywords)
                    
                    # Check if it's a contact link (HIGHEST PRIORITY - leads directly to email)
                    is_contact = 'contact' in url_lower or link_parsed.path.endswith('/contact')
                    
                    # Check if it's a teacher name link (URL pattern like /firstname-lastname)
                    link_path_parts = [p for p in link_parsed.path.split('/') if p]
                    is_teacher_name = (
                        len(link_path_parts) >= 1 and
                        '-' in link_path_parts[-1] and
                        not any(kw in url_lower for kw in ['websites', 'contact', 'page', 'admin', 'login']) and
                        link_path_parts[-1].count('-') >= 1 and
                        len(link_path_parts[-1].split('-')) >= 2
                    )
                    
                    # Check if it's a pagination link (CRITICAL - need all pages)
                    is_pagination = (
                        ('websites' in url_lower and ('page=' in url_lower or '&page=' in url_lower)) or
                        ('page=' in url_lower or '&page=' in url_lower or '?page=' in url_lower) or
                        ('p=' in url_lower or '&p=' in url_lower or '?p=' in url_lower)
                    )
                    
                    # Check if it's a faculty/major/department link
                    is_faculty = any(kw in url_lower for kw in faculty_keywords)
                    
                    if is_contact:
                        contact_links.append(normalized_link)
                    elif is_pagination:
                        # Pagination links - VERY HIGH PRIORITY (need all pages first)
                        priority_links.insert(0, normalized_link)  # Insert at front
                    elif is_teacher_name:
                        teacher_links.append(normalized_link)
                    elif is_faculty:
                        faculty_links.append(normalized_link)
                    elif is_subdomain:
                        subdomain_links.append(normalized_link)
                    elif is_priority:
                        priority_links.append(normalized_link)
                    else:
                        regular_links.append(normalized_link)
                    
                    seen_in_queue.add(normalized_link)
                
                # Add links to queue in priority order (contact > pagination > teacher > faculty > subdomain > priority > regular)
                # Increased limit to 500 to handle large sites with many pages (55 pages × teachers)
                for link in (contact_links + priority_links + teacher_links + faculty_links + subdomain_links + regular_links)[:500]:
                    queue.append(link)
                
                # Stop if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(f"Too many consecutive failures ({consecutive_failures}), stopping crawl for {seed_url}")
                    break
        
        logger.info(f"Scraped {pages_scraped} pages from {seed_url}, found {len(all_emails)} email occurrences")
        return all_emails
    
    def save_raw_emails(self, emails: List[Dict]):
        """Save raw emails to CSV."""
        if not emails:
            return
        
        file_exists = OUTPUT_RAW.exists()
        
        try:
            with open(OUTPUT_RAW, 'a', newline='', encoding='utf-8') as f:
                fieldnames = ['email', 'local_part', 'domain', 'source_url', 'source_type',
                             'page_title', 'context_snippet', 'http_status', 'found_at',
                             'parse_method', 'notes']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                for email_data in emails:
                    # Ensure all required fields exist
                    email_data.setdefault('http_status', '200')
                    # Sanitize string fields to prevent CSV injection
                    for key in ['page_title', 'context_snippet', 'notes']:
                        if key in email_data and email_data[key]:
                            # Remove potential CSV injection characters
                            val = str(email_data[key])
                            if val.startswith(('=', '+', '-', '@')):
                                email_data[key] = "'" + val
                    writer.writerow(email_data)
            
            logger.info(f"Saved {len(emails)} raw email records to {OUTPUT_RAW}")
        except (IOError, OSError) as e:
            logger.error(f"Failed to save emails to {OUTPUT_RAW}: {e}")
            # Don't raise - continue scraping even if save fails
    
    def clean_and_dedupe_emails(self):
        """Clean and deduplicate emails from raw CSV, removing administrative/institutional emails."""
        if not OUTPUT_RAW.exists():
            logger.warning("No raw emails file found")
            return
        
        emails_dict: Dict[str, Dict] = {}
        excluded_count = 0
        
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
                    
                    # Filter out administrative/institutional emails (keep only teacher emails)
                    if self.is_institutional_email(email):
                        excluded_count += 1
                        continue
                    
                    if email not in emails_dict:
                        # Extract domain from email (we already validated @ exists on line 622)
                        domain = row.get('domain', '')
                        if not domain:
                            domain = email.split('@')[1]
                        emails_dict[email] = {
                            'email': email,
                            'domain': domain.lower(),
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
        
        # Write clean CSV (only teacher emails, no administrative)
        with open(OUTPUT_CLEAN, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['email', 'domain', 'first_seen', 'sources', 'verified', 'status', 'notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(emails_dict.values())
        
        logger.info(f"Created clean CSV with {len(emails_dict)} unique teacher emails at {OUTPUT_CLEAN}")
        if excluded_count > 0:
            logger.info(f"Excluded {excluded_count} administrative/institutional emails")
    
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
