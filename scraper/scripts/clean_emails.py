"""Script to clean existing emails CSV and remove non-person emails."""
import csv
import sys
from pathlib import Path

# Add parent directory to path for config import
scraper_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scraper_dir))
from config import EXCLUDED_EMAIL_PATTERNS, OUTPUT_CLEAN


def is_institutional_email(email: str) -> bool:
    """Check if email is an institutional/support email (not a real person)."""
    if '@' not in email:
        return False
    
    try:
        local_part = email.split('@')[0].lower()
    except (ValueError, IndexError):
        return False
    
    # Check against excluded patterns
    for pattern in EXCLUDED_EMAIL_PATTERNS:
        if pattern in local_part:
            return True
    
    # Exclude emails that are too short (likely generic)
    if len(local_part) < 3:
        return True
    
    return False


def clean_csv():
    """Clean the emails CSV by removing institutional emails."""
    if not OUTPUT_CLEAN.exists():
        print(f"File not found: {OUTPUT_CLEAN}")
        return
    
    # Read all emails
    emails = []
    removed_count = 0
    
    with open(OUTPUT_CLEAN, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        for row in reader:
            email = row.get('email', '').lower().strip()
            
            if not email or '@' not in email:
                continue
            
            # Check if it's an institutional email
            if is_institutional_email(email):
                removed_count += 1
                print(f"Removing institutional email: {email}")
                continue
            
            emails.append(row)
    
    # Write cleaned emails back
    with open(OUTPUT_CLEAN, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(emails)
    
    print(f"\nCleaned CSV:")
    print(f"  Removed: {removed_count} institutional emails")
    print(f"  Remaining: {len(emails)} person emails")
    print(f"  Saved to: {OUTPUT_CLEAN}")


if __name__ == "__main__":
    clean_csv()
