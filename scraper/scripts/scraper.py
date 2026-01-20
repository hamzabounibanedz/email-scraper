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
from typing import List, Set, Dict, Optional
from urllib.parse import urljoin, urlparse
import requests
import urllib3
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
    
    def __init__(self):
        self.session = requests.Session()
        self._rotate_user_agent()  # Set initial User-Agent
        # Disable SSL verification for sites with expired/invalid certificates
        # (Many Algerian university sites have certificate issues)
        self.session.verify = False
        self.visited_urls: Set[str] = set()
        self.robots_cache: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self.email_pattern = re.compile(r'[\w.\-+%]+@[\w.\-]+\.dz\b', re.IGNORECASE)
    
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
        """Get robots.txt parser for a domain (cached)."""
        parsed = urlparse(url)
        original_host = parsed.netloc or ""
        if not original_host:
            return None
        
        # Cache robots per host (normalized without www)
        host = self._strip_www(original_host)
        cache_key = host
        
        if cache_key in self.robots_cache:
            return self.robots_cache[cache_key]
        
        rp = urllib.robotparser.RobotFileParser()
        
        # Try both stripped and original host (some sites only have www. subdomain)
        hosts_to_try = [host] if host == original_host else [host, original_host]
        
        for try_host in hosts_to_try:
            for scheme in ['https', 'http']:
                robots_url = f"{scheme}://{try_host}/robots.txt"
                try:
                    resp = self.session.get(
                        robots_url,
                        timeout=(CONNECT_TIMEOUT_SECONDS, ROBOTS_TIMEOUT_SECONDS),
                        allow_redirects=True,
                    )
                    if resp.status_code == 200:
                        rp.parse(resp.text.splitlines())
                        logger.debug(f"Loaded robots.txt from {robots_url}")
                        self.robots_cache[cache_key] = rp
                        return rp
                except Exception:
                    continue  # Try next scheme/host
        
        # If all attempts failed, cache None to avoid retrying
        logger.debug(f"Could not load robots.txt for {host} (tried {len(hosts_to_try)} host(s), 2 schemes)")
        self.robots_cache[cache_key] = None
        return None

    def _strip_www(self, netloc: str) -> str:
        """Remove leading 'www.' from a hostname."""
        return netloc[4:] if netloc.startswith("www.") else netloc
    
    def can_fetch(self, url: str) -> bool:
        """Check if URL can be fetched according to robots.txt."""
        rp = self.get_robots_parser(url)
        if rp is None:
            return True  # If robots.txt unavailable, proceed conservatively
        
        # Use current User-Agent from session (rotated) for robots.txt checking
        current_ua = self.session.headers.get('User-Agent', USER_AGENT)
        return rp.can_fetch(current_ua, url)
    
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
        # Try both http/https when one is clearly failing (very common on .dz sites)
        def alt_scheme(u: str) -> Optional[str]:
            try:
                parsed = urlparse(u)
                if not parsed.netloc:
                    return None
                if parsed.scheme == "http":
                    new_scheme = "https"
                elif parsed.scheme == "https":
                    new_scheme = "http"
                else:
                    return None
                # Reconstruct URL preserving all components
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
            except Exception:
                return None

        for attempt in range(retries):
            try:
                # Rotate User-Agent periodically to avoid detection
                if attempt == 0 or random.random() < 0.3:  # 30% chance to rotate on retries
                    self._rotate_user_agent()
                
                response = self.session.get(
                    url,
                    timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                    allow_redirects=True,
                )
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
                # If we are on the last attempt, try switching scheme once before giving up
                if attempt == retries - 1:
                    alt = alt_scheme(url)
                    if alt and alt != url:
                        try:
                            logger.info(f"Retrying with alternate scheme: {alt}")
                            response = self.session.get(
                                alt,
                                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                                allow_redirects=True,
                            )
                            response.raise_for_status()
                            return response
                        except Exception:
                            pass
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
        """Extract emails from HTML page - checks multiple sources."""
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
                    page.goto(url, wait_until='networkidle', timeout=int(TIMEOUT_SECONDS * 1000))
                    html = page.content()
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
        soup = BeautifulSoup(html, 'html.parser')
        
        # Keywords that suggest pages with staff/contact information
        priority_keywords = ['staff', 'websites', 'contact', 'personnel', 'enseignants', 
                             'professeurs', 'equipe', 'team', 'annuaire', 'directory',
                             'faculte', 'faculty', 'departement', 'department', 'corps',
                             'enseignant', 'professeur', 'chercheur', 'researcher']
        
        priority_links = []
        regular_links = []
        subdomain_links = []  # Subdomain links get highest priority
        seen_urls = set()  # Track normalized URLs to avoid duplicates
        
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
            
            # Normalize URL
            normalized_url = self.normalize_url(full_url)
            
            # Skip if already seen in this page
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            
            # Check if it's the same base domain (including subdomains)
            if self.is_same_base_domain(base_url, normalized_url):
                if normalized_url not in self.visited_urls and self.can_fetch(normalized_url):
                    # Check if this is a subdomain link (higher priority)
                    base_parsed = urlparse(base_url)
                    link_parsed = urlparse(normalized_url)
                    is_subdomain = (link_parsed.netloc != base_parsed.netloc and 
                                   self.is_same_base_domain(base_url, normalized_url))
                    
                    # Check if link text or URL contains priority keywords
                    link_text = link.get_text(strip=True).lower()
                    url_lower = normalized_url.lower()
                    is_priority = any(keyword in link_text or keyword in url_lower 
                                    for keyword in priority_keywords)
                    
                    if is_subdomain:
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
                    self.is_same_base_domain(base_url, normalized_text_url) and
                    normalized_text_url not in self.visited_urls and
                    self.can_fetch(normalized_text_url)):
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
        
        # Return subdomain links first (highest priority), then priority links, then regular links
        return subdomain_links + priority_links + regular_links
    
    def discover_subdomain_pages(self, base_url: str) -> List[str]:
        """Try to discover common subdomain pages that might contain staff emails."""
        parsed = urlparse(base_url)
        base_domain = parsed.netloc
        if not base_domain:
            return []
        
        scheme = parsed.scheme or 'https'
        discovered = set()
        # IMPORTANT: if seed is like www.usthb.dz, subdomains should be staff.usthb.dz (not staff.www.usthb.dz)
        base_domain_no_www = self._strip_www(base_domain)
        
        # Common patterns for university staff pages
        patterns = ['staff', 'personnel', 'enseignants', 'professeurs', 
                   'faculty', 'annuaire', 'directory', 'contact', 'websites']
        
        # Try subdomain patterns (e.g., staff.univ-batna2.dz)
        for pattern in patterns:
            subdomain_url = f"{scheme}://{pattern}.{base_domain_no_www}"
            normalized = self.normalize_url(subdomain_url)
            if self.is_same_base_domain(base_url, normalized):
                discovered.add(normalized)
        
        # Try path patterns (e.g., univ-batna2.dz/websites)
        for pattern in patterns:
            # Use both www and non-www for paths, since both exist in the wild
            for host in {base_domain, base_domain_no_www}:
                path_url = f"{scheme}://{host}/{pattern}"
                normalized = self.normalize_url(path_url)
                if self.is_same_base_domain(base_url, normalized):
                    discovered.add(normalized)
        
        return list(discovered)
    
    def scrape_domain(self, seed_url: str) -> List[Dict]:
        """Scrape a domain starting from seed URL, including subdomains."""
        logger.info(f"Scraping domain: {seed_url}")
        all_emails = []
        
        # Normalize seed URL
        normalized_seed = self.normalize_url(seed_url)
        
        # Start with seed URL only - we'll add discovered subdomains after crawling main page
        pages_scraped = 0
        queue = deque([normalized_seed])
        seen_in_queue = {normalized_seed}  # Track URLs already in queue to avoid duplicates
        discovered_subdomains = self.discover_subdomain_pages(normalized_seed)
        discovered_added = False  # Track if we've added discovered subdomains yet
        
        # Safety limit: prevent unbounded queue growth if pages keep failing
        max_queue_size = MAX_PAGES_PER_DOMAIN * 10
        consecutive_failures = 0
        max_consecutive_failures = 5
        
        while queue and pages_scraped < MAX_PAGES_PER_DOMAIN:
            # Safety check: prevent queue from growing too large
            if len(queue) > max_queue_size:
                logger.warning(f"Queue size exceeded {max_queue_size}, stopping crawl for {seed_url}")
                break
            
            url = queue.popleft()
            
            if url in self.visited_urls:
                continue
                
            if not self.can_fetch(url):
                logger.info(f"Skipping {url} (disallowed by robots.txt)")
                self.visited_urls.add(url)  # Mark as visited to avoid retrying
                continue
            
            self.visited_urls.add(url)
            delay = self.get_crawl_delay(url)
            time.sleep(delay)
            
            # Fetch HTML once
            response = self.fetch_html(url)
            if response is None:
                consecutive_failures += 1
                # If too many consecutive failures, stop adding new links
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(f"Too many consecutive failures ({consecutive_failures}), stopping crawl for {seed_url}")
                    break
                continue
            
            # Reset failure counter on success
            consecutive_failures = 0
            
            # Ensure proper encoding (requests handles this, but be explicit)
            if response.encoding is None:
                response.encoding = 'utf-8'
            html = response.text
            
            # Extract emails from HTML
            emails = self.extract_emails_from_html(html, url)
            
            # If no emails and page is small, try Playwright for JS-rendered content
            if len(emails) == 0 and len(html) < 5000:
                logger.info(f"Trying Playwright for {url} (small page, might be JS-rendered)")
                playwright_html = self.fetch_html_with_playwright(url)
                if playwright_html:
                    emails = self.extract_emails_from_html(playwright_html, url)
            
            all_emails.extend(emails)
            pages_scraped += 1
            
            # Find more links to crawl (use the HTML we already fetched)
            if pages_scraped < MAX_PAGES_PER_DOMAIN:
                new_links = self.find_links_on_page(html, url)
                
                # If this was the seed URL and we found links, prioritize those over discovered subdomains
                # Otherwise, add discovered subdomains as fallback if we haven't added them yet
                if url == normalized_seed and len(new_links) > 0:
                    # Seed URL found links - add them first, then discovered subdomains as fallback
                    for link in new_links[:30]:  # Limit to 30 links
                        normalized_link = self.normalize_url(link)
                        if normalized_link not in seen_in_queue and normalized_link not in self.visited_urls:
                            queue.append(normalized_link)
                            seen_in_queue.add(normalized_link)
                    
                    # Add discovered subdomains to the END of queue (lower priority) if not already found
                    if not discovered_added:
                        for disc_url in discovered_subdomains:
                            if disc_url not in seen_in_queue and disc_url not in self.visited_urls:
                                queue.append(disc_url)  # Add to end, not beginning
                                seen_in_queue.add(disc_url)
                        discovered_added = True
                elif url == normalized_seed and len(new_links) == 0:
                    # Seed URL found no links - add discovered subdomains as fallback
                    if not discovered_added:
                        for disc_url in discovered_subdomains:
                            if disc_url not in seen_in_queue and disc_url not in self.visited_urls:
                                queue.append(disc_url)
                                seen_in_queue.add(disc_url)
                        discovered_added = True
                else:
                    # Regular page - just add its links
                    for link in new_links[:30]:  # Limit to 30 links
                        normalized_link = self.normalize_url(link)
                        if normalized_link not in seen_in_queue and normalized_link not in self.visited_urls:
                            queue.append(normalized_link)
                            seen_in_queue.add(normalized_link)
        
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
