# University Email Scraper

Simple scraper to extract `.dz` email addresses from Algerian university websites.

## Quick Start

### 1. Install Dependencies

```powershell
pip install -r requirements.txt
```

**Note**: Playwright requires browser installation:
```powershell
playwright install chromium
```

### 2. Add University URLs

Edit `seeds.txt` and add one URL per line:

```
https://www.univ-alger.dz
https://www.usthb.dz
https://www.univ-constantine2.dz
```

### 3. Configure (Optional)

Create a `.env` file in the scraper folder or set environment variables:

```env
SCRAPER_DELAY=2.0
SCRAPER_MAX_PAGES=50
SCRAPER_TIMEOUT=15
SCRAPER_RETRIES=3
SCRAPER_LOG_LEVEL=INFO
```

### 4. Run the Scraper

```powershell
python run.py
```

Or from the scripts folder:

```powershell
python scripts/scraper.py
```

## Output Files

- **`data/emails_raw.csv`** - All email occurrences found (one row per occurrence)
- **`data/emails_clean.csv`** - Deduplicated list (one row per unique email)
- **`downloads/`** - Downloaded PDF files
- **`logs/scraper.log`** - Scraper logs

## How It Works

1. Reads URLs from `seeds.txt`
2. Respects `robots.txt` for each domain
3. Scrapes HTML pages and extracts `.dz` emails
4. Downloads and parses PDF files
5. Uses Playwright for JavaScript-rendered pages (when needed)
6. Saves all findings to `emails_raw.csv`
7. Cleans and deduplicates to create `emails_clean.csv`

## Features

- ✅ Respects robots.txt
- ✅ Rate limiting (configurable delay)
- ✅ PDF parsing
- ✅ JavaScript rendering (Playwright)
- ✅ Retry logic with exponential backoff
- ✅ Only extracts `.dz` emails
- ✅ Context snippets for verification
- ✅ Incremental saving (won't lose data if interrupted)

## Configuration

All settings are in `config.py` and can be overridden via environment variables:

- `SCRAPER_DELAY` - Delay between requests (default: 2.0 seconds)
- `SCRAPER_MAX_PAGES` - Max pages per domain (default: 50)
- `SCRAPER_TIMEOUT` - HTTP timeout (default: 15 seconds)
- `SCRAPER_RETRIES` - Retry attempts (default: 3)
- `SCRAPER_LOG_LEVEL` - Logging level (default: INFO)

## CSV Format

### emails_raw.csv
- `email` - Found email address
- `local_part` - Part before @
- `domain` - Domain part
- `source_url` - Where it was found
- `source_type` - `html` or `pdf`
- `page_title` - Page title
- `context_snippet` - Text around the email
- `found_at` - Timestamp
- `parse_method` - How it was found

### emails_clean.csv
- `email` - Unique email address
- `domain` - Domain part
- `first_seen` - First time found
- `sources` - All URLs where found (semicolon-separated)
- `verified` - Always `false` (manual verification)
- `status` - `unknown` (update manually)
- `notes` - Additional notes

## Usage with n8n

After scraping, use `data/emails_clean.csv` in your n8n workflows:

1. Copy `scraper/data/emails_clean.csv` to the main project `csv/` folder (or root folder)
2. Use n8n's "Read Binary File" or "Google Sheets" node to read it
3. Process emails in your email sending workflow

**Note**: The scraper is completely separate from n8n:
- Scraper outputs: `scraper/data/emails_clean.csv`
- n8n data: `data/` (n8n's own database)
- n8n CSV files: `csv/` (for n8n workflows)
- No conflicts or dependencies between scraper and n8n

## Notes

- The scraper is polite: respects robots.txt and rate limits
- Only extracts emails ending with `.dz`
- Saves incrementally (won't lose progress if interrupted)
- PDFs are downloaded to `downloads/` folder
- Logs are saved to `logs/scraper.log`

## Troubleshooting

**No emails found?**
- Check `seeds.txt` has valid URLs
- Check `logs/scraper.log` for errors
- Verify websites are accessible

**Playwright errors?**
- Run: `playwright install chromium`

**Too slow?**
- Increase `SCRAPER_DELAY` if getting rate-limited
- Decrease `SCRAPER_MAX_PAGES` to limit crawling

**Memory issues?**
- The scraper saves incrementally, so it shouldn't use too much memory
- If processing many PDFs, they're saved to disk first
