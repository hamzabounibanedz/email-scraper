# n8n Email Marketing Agent - University Teacher Outreach

A local n8n setup for automated email campaigns to Algerian university teachers with batch sending, Gmail response classification, and CRM tracking.

## Prerequisites

- **Docker Desktop** (Windows/Mac) - **~2-3 GB disk space** for Docker + n8n image
- A transactional email provider account (SendGrid, Mailgun, Mailjet, or Amazon SES)
- Gmail account with API access (for response classification)
- CSV file with teacher emails (`emails_clean.csv`)
- **Domain (Optional but Recommended)**: You can start without a domain, but buying one ($10-20/year) improves deliverability

**Exact Download Sizes:**
- **Docker Desktop installer**: ~500 MB download
- **Docker Desktop installed**: ~1.5-2 GB on disk
- **n8n Docker image**: ~200 MB download (first time only)
- **n8n data folder**: ~50-100 MB initially (grows with usage)
- **Total initial download**: ~700 MB
- **Total disk space needed**: ~2-3 GB minimum, 5 GB recommended for growth

## Quick Start

> 📖 **For exact step-by-step commands, see [QUICK_START.md](QUICK_START.md)**

### 1. Navigate to Project Folder

```powershell
cd C:\Users\User\Desktop\n8n-email-agent
```

### 2. Configure Secrets & Authentication

**Option A: Automated Setup (Recommended)**
```powershell
.\setup-secrets.ps1
```
This script will generate encryption keys and prompt you for a password.

**Option B: Manual Setup**
```powershell
Copy-Item env.example .env
```

Then edit `.env` and set:
- `N8N_BASIC_AUTH_PASSWORD` - Choose a strong password for n8n UI access
- `N8N_ENCRYPTION_KEY` - Generate a random 32-character string:
  ```powershell
  $key = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_}); Write-Host $key
  ```
- `WEBHOOK_URL` - For local testing, you'll update this to your ngrok URL later

**Required Values:**
- `N8N_BASIC_AUTH_PASSWORD` - Strong password (12+ characters)
- `N8N_ENCRYPTION_KEY` - 32-character random string (generate with script above)

### 3. Start Docker Desktop & n8n

**Step 1: Open Docker Desktop**
- Launch Docker Desktop application
- Wait until it shows "Docker Desktop is running" (whale icon in system tray)
- **First time**: Docker Desktop will download and install (~1.5-2 GB)

**Step 2: Start n8n**

**Option A: Using PowerShell script (Windows)**
```powershell
.\start.ps1
```

**What happens when you run `.\start.ps1`:**
1. ✅ Checks if `.env` file exists (warns if missing)
2. ✅ Checks if Docker is running
3. ✅ Downloads n8n Docker image (~200 MB) - **first time only**
4. ✅ Creates Docker container named `n8n-email-agent`
5. ✅ Starts n8n service on port 5678
6. ✅ Creates `data/` folder for persistent storage
7. ✅ Shows success message with access URL

**Option B: Using Docker Compose directly**
```powershell
docker-compose up -d
```

**What happens when you run `docker-compose up -d`:**
1. ✅ Reads `docker-compose.yml` configuration
2. ✅ Downloads `n8nio/n8n:latest` image (~200 MB) - **first time only**
3. ✅ Creates and starts container in background (`-d` flag)
4. ✅ Maps port 5678 to your localhost
5. ✅ Mounts `./data` folder for persistence
6. ✅ Container runs until you stop it

**Step 3: Wait & Access**
- Wait 30-60 seconds for n8n to initialize
- Open: **http://localhost:5678**
- Login with:
  - Username: `admin` (or your `N8N_BASIC_AUTH_USER`)
  - Password: (your `N8N_BASIC_AUTH_PASSWORD`)

### 4. Configure Credentials in n8n UI

Go to **Settings → Credentials** and create:

#### SMTP Credential
- **Type**: SMTP
- **Host**: 
  - SendGrid: `smtp.sendgrid.net`
  - Mailjet: `in-v3.mailjet.com`
  - Mailgun: `smtp.mailgun.org`
  - Amazon SES: `email-smtp.[region].amazonaws.com`
- **Port**: `587` (TLS) or `465` (SSL)
- **User**: (your SMTP username or API key)
- **Password**: (your SMTP password or API key)
- **Secure**: Enable TLS/SSL as required

**Note**: You can also use n8n's built-in **Mailjet node** (no SMTP needed) - go to Nodes → Mailjet in n8n UI.

#### Gmail Credential (for Response Classification)
1. Go to **Settings → Credentials** in n8n
2. Create **Gmail OAuth2** credential
3. Follow n8n's OAuth flow to authenticate with your Gmail account
4. This allows n8n to read emails from your inbox

**Note**: Gmail API is used to automatically read and classify email responses.

### 5. Prepare Your Email List

Place your `emails_clean.csv` file in the project folder with columns:
- `email` (required) - Teacher email addresses
- `name` (optional) - Teacher name for personalization
- `university` (optional) - University name
- `department` (optional) - Department/faculty
- Any other fields you need for personalization

**Important**: The CSV file will be ignored by git for security. Keep it local.

### 6. Create the Email Sending Workflow

#### Node Sequence for Batch Sending:

1. **Manual Trigger** or **Cron** - Start workflow
2. **Read Binary File** or **Google Sheets** - Read `emails_clean.csv`
3. **CSV Parse** - Convert CSV to JSON rows
4. **SplitInBatches** - Set `batchSize: 5-10` (adjust based on provider limits)
5. **Set** - Build email fields:
   - `to`: `{{ $json.email }}`
   - `subject`: Personalized subject (e.g., "Opportunity for {{ $json.university }} Teachers")
   - `bodyHtml`: HTML email body with tracking pixel and unsubscribe link
   - `tracking_id`: Unique ID for each email (for open tracking)
6. **Send Email** - Map fields to SMTP credential
7. **IF** - Check for errors
8. **Write to CSV** or **Google Sheets** - Log to master tracking file:
   - `email`, `sent_date`, `status`, `tracking_id`, `batch_number`
9. **Wait** - Wait 30-60 seconds between batches (respect provider limits)
10. **Finish** - Summary log

**Batch Settings:**
- Start with 5-10 emails per batch
- Wait 30-60 seconds between batches
- Monitor provider dashboard for throttling
- Gradually increase if no issues

### 7. Create Automatic Gmail Response Classification Workflow

#### Node Sequence for Automatic Response Handling:

1. **Gmail Trigger** - Watch for new emails in your inbox (poll every 5-15 minutes)
2. **IF** - Filter emails:
   - From addresses in your `emails_clean.csv`
   - Subject contains your campaign keywords
   - Not from yourself (avoid loops)
3. **Set** - Extract email data:
   - `from_email`: Sender address
   - `subject`: Email subject (lowercase for matching)
   - `body`: Email content (lowercase for matching)
   - `received_date`: When email arrived
4. **Code Node** - Automatic Classification Logic:
   
   Use keyword matching to classify automatically:
   
   ```javascript
   const subject = $input.item.json.subject.toLowerCase();
   const body = $input.item.json.body.toLowerCase();
   const combined = subject + ' ' + body;
   
   let classification = 'Unknown';
   
   // Potential Buyers - Strong purchase intent
   if (combined.match(/\b(buy|purchase|order|price|cost|pricing|quote|interested in buying|ready to buy|want to buy)\b/)) {
     classification = 'Potential Buyers';
   }
   // Demo Scheduled - Agreed to demo
   else if (combined.match(/\b(demo|schedule|meeting|call|zoom|teams|calendar|appointment|available|time slot)\b/)) {
     classification = 'Demo Scheduled';
   }
   // Leads - Interested, asking questions
   else if (combined.match(/\b(interested|tell me more|more information|info|details|how does|what is|questions|curious|learn more)\b/)) {
     classification = 'Leads';
   }
   // More Information - Asking for specific details
   else if (combined.match(/\b(more info|more details|specifications|specs|features|benefits|how it works)\b/)) {
     classification = 'More Information';
   }
   // Price Objection - Interested but price concern
   else if (combined.match(/\b(expensive|too much|cost|budget|afford|cheaper|discount|deal)\b/)) {
     classification = 'Price Objection';
   }
   // Not Right Time - Interested but timing issue
   else if (combined.match(/\b(not now|later|next month|next year|busy|timing|not the right time|future)\b/)) {
     classification = 'Not Right Time';
   }
   // Follow-up Needed - Needs consideration
   else if (combined.match(/\b(think about|consider|discuss|team|manager|decision|review|evaluate)\b/)) {
     classification = 'Follow-up Needed';
   }
   // Not Interested - Declining
   else if (combined.match(/\b(not interested|no thanks|decline|pass|not for us|don't need)\b/)) {
     classification = 'Not Interested';
   }
   // Wrong Person - Not the right contact
   else if (combined.match(/\b(wrong person|not me|not the right|different department|forwarded)\b/)) {
     classification = 'Wrong Person';
   }
   // Out of Office - Auto-replies
   else if (combined.match(/\b(out of office|ooo|away|vacation|unavailable|auto-reply|automatic reply)\b/)) {
     classification = 'Out of Office';
   }
   // Unsubscribe - Requesting removal
   else if (combined.match(/\b(unsubscribe|remove|stop|opt out|don't email|no more emails)\b/)) {
     classification = 'Unsubscribe';
   }
   // Customer - Already converted/purchased
   else if (combined.match(/\b(purchased|bought|customer|already have|using|implemented)\b/)) {
     classification = 'Customer';
   }
   
   return {
     json: {
       ...$input.item.json,
       classification: classification
     }
   };
   ```

5. **Switch Node** - Route by classification to different CSV files:
   - `csv/potential_buyers.csv`
   - `csv/demo_scheduled.csv`
   - `csv/leads.csv`
   - `csv/more_information.csv`
   - `csv/price_objection.csv`
   - `csv/not_right_time.csv`
   - `csv/follow_up_needed.csv`
   - `csv/not_interested.csv`
   - `csv/wrong_person.csv`
   - `csv/out_of_office.csv`
   - `csv/unsubscribes.csv`
   - `csv/customers.csv`
   - `csv/unknown.csv` (for unclassified)

6. **Write to CSV** - Append to respective classification file with:
   - `email`, `name`, `university`, `subject`, `body`, `received_date`, `classification`

7. **Update Master CSV** - Update `csv/master_tracking.csv`:
   - Find row by `email`
   - Update: `replied=Yes`, `reply_date`, `classification`

**Note**: Adjust keywords based on your actual email responses. Test with sample replies first.

### 8. Email Open Tracking (Cheap Options)

#### How Open Tracking Works:

Open tracking uses a **tracking pixel** - a tiny 1x1 transparent image embedded in your HTML email. When the email is opened, the image loads from your server, which logs the open event.

#### Best Cheap Options:

**Option 1: Mailjet (Recommended - Best Free Tier)**
- **Cost**: Free up to 6,000 emails/month (200/day)
- **Features**: Built-in open tracking, click tracking, bounce handling, analytics
- **Setup**: Use Mailjet's SMTP or built-in n8n Mailjet node
- **How**: Mailjet automatically adds tracking pixels to HTML emails
- **Pros**: Best free tier, easy setup, includes analytics dashboard
- **Cons**: None for free tier

**Option 2: SendGrid (Free Tier)**
- **Cost**: Free up to 100 emails/day
- **Features**: Built-in open tracking, click tracking, bounce handling
- **Setup**: Use SendGrid's SMTP with tracking enabled
- **How**: SendGrid automatically adds tracking pixels to HTML emails
- **Pros**: Easiest, no coding needed, includes analytics dashboard
- **Cons**: Free tier limited to 100/day

**Option 3: Mailgun (Free Tier)**
- **Cost**: Free up to 5,000 emails/month (first 3 months)
- **Features**: Open tracking via webhooks
- **Setup**: Configure webhook URL in Mailgun dashboard
- **How**: Mailgun sends webhook to your n8n webhook endpoint when email opens
- **Pros**: Good free tier, reliable
- **Cons**: Requires webhook setup, free tier expires after 3 months

**Option 4: Self-Hosted Tracking Pixel (Free)**
- **Cost**: Free (uses your n8n webhook)
- **Features**: Full control, unlimited
- **Setup**: 
  1. Create a webhook node in n8n: `/webhook/track-open/:tracking_id`
  2. Return a 1x1 transparent PNG image
  3. Embed in email: `<img src="http://your-ngrok-url/webhook/track-open/{{tracking_id}}" width="1" height="1">`
- **Pros**: Completely free, unlimited, full control
- **Cons**: Requires ngrok for local testing, more setup

**Recommended**: Start with **Mailjet** (best free tier - 6,000/month) or **SendGrid** (easiest), then switch to self-hosted if you need more control.

#### Implementation in n8n:

1. **In Email Sending Workflow** - Add tracking pixel to HTML:
   ```html
   <html>
   <body>
     <p>Your email content here...</p>
     <!-- Tracking pixel -->
     <img src="http://your-ngrok-url/webhook/track-open/{{$json.tracking_id}}" 
          width="1" height="1" style="display:none;" />
   </body>
   </html>
   ```

2. **Create Webhook Node** for open tracking:
   - Path: `/webhook/track-open/:tracking_id`
   - Method: GET
   - Response: Return 1x1 transparent PNG
   - Action: Update `csv/master_tracking.csv` with `opened=Yes`, `opened_date`

3. **Use ngrok** for local testing:
   ```powershell
   ngrok http 5678
   ```
   Update tracking pixel URL with ngrok URL.

### 9. Create CRM Tracking & Analytics

#### Master Tracking CSV Structure:

The `csv/master_tracking.csv` file should track:
- `email` - Recipient email
- `name` - Teacher name
- `university` - University name
- `sent_date` - When email was sent
- `opened` - Yes/No (tracking pixel clicked)
- `opened_date` - When email was opened (first open)
- `opened_count` - Number of times opened
- `replied` - Yes/No
- `reply_date` - When reply received
- `classification` - See classification types below
- `status` - Sent/Delivered/Bounced/Unsubscribed
- `demo_scheduled` - Yes/No
- `demo_date` - Date of demo
- `customer` - Yes/No (converted to customer)
- `tracking_id` - Unique ID for tracking

#### Complete Classification Types:

1. **Potential Buyers** - Expressing strong purchase intent
2. **Demo Scheduled** - Agreed to schedule a demo/meeting
3. **Leads** - Interested, asking general questions
4. **More Information** - Requesting specific details/info
5. **Price Objection** - Interested but concerned about price
6. **Not Right Time** - Interested but timing issue
7. **Follow-up Needed** - Needs time to consider/discuss
8. **Not Interested** - Declining the offer
9. **Wrong Person** - Not the right contact
10. **Out of Office** - Auto-reply messages
11. **Unsubscribe** - Requesting to be removed
12. **Customer** - Already converted/purchased
13. **Bounce** - Delivery failure (handled separately)
14. **Unknown** - Could not be classified automatically

#### Metrics to Calculate:

**Engagement Metrics:**
- **Open Rate**: (Opened / Sent) × 100
- **Reply Rate**: (Replied / Sent) × 100
- **Open-to-Reply Rate**: (Replied / Opened) × 100

**Conversion Metrics:**
- **Lead Conversion**: (Leads / Sent) × 100
- **Potential Buyer Rate**: (Potential Buyers / Sent) × 100
- **Demo Conversion**: (Demos Scheduled / Leads) × 100
- **Customer Conversion**: (Customers / Sent) × 100
- **Overall Conversion**: (Customers / Sent) × 100

**Pipeline Metrics:**
- **Lead-to-Demo Rate**: (Demos Scheduled / Leads) × 100
- **Demo-to-Customer Rate**: (Customers / Demos Scheduled) × 100
- **Average Time to Reply**: Average days between sent_date and reply_date
- **Average Time to Convert**: Average days between sent_date and customer conversion

Create a workflow in n8n to:
1. Read `csv/master_tracking.csv`
2. Calculate all metrics
3. Write to `csv/metrics_summary.csv` or display in n8n UI

### 7. Test Unsubscribe Flow

1. Create a **Webhook** node:
   - Method: `GET` or `POST`
   - Path: `/webhook/unsubscribe`
   - Extract `token` parameter
2. Add logic to:
   - Validate token
   - Log unsubscribe to Google Sheets or database
   - Return confirmation page

3. For local testing, use ngrok:
   ```bash
   ngrok http 5678
   ```
   Update `WEBHOOK_URL` in `.env` to the ngrok URL, then restart:
   ```bash
   docker-compose restart
   ```

### 8. Testing Checklist

- [ ] Test reading email list (Google Sheets/HTTP Request)
- [ ] Test CSV parsing
- [ ] Test single email send to your own address
- [ ] Test error handling
- [ ] Test logging to Google Sheets
- [ ] Test unsubscribe webhook (via ngrok)
- [ ] Test batching (5-10 emails)
- [ ] Verify wait times respect provider limits

### 9. Run Small Pilot

After all tests pass:
- Use 20-50 real recipients
- Monitor deliverability
- Check bounce reports
- Verify unsubscribe links work

### 10. Backup Workflows

Export your workflow:
- In n8n UI: Click workflow → Export
- Save to `backups/` folder
- Keep credential configs secure (never commit to git)

## Provider Limits Reference

### SendGrid
- Free: 100 emails/day
- Essentials: 40,000 emails/month
- Rate: ~100 emails/second
- SMTP: `smtp.sendgrid.net:587`

### Mailjet ⭐ (Recommended for Free Tier)
- **Free: 6,000 emails/month** (200/day)
- SMTP: `in-v3.mailjet.com:587`
- API Key + Secret Key required
- Built-in n8n node available
- **Best free tier for volume**

### Mailgun
- Free: 5,000 emails/month (first 3 months)
- Rate: Varies by plan
- SMTP: `smtp.mailgun.org:587`

### Amazon SES
- Sandbox: 200 emails/day, 1 email/second
- Production: Request limit increase
- Rate: Varies by region
- SMTP: `email-smtp.[region].amazonaws.com:587`

**Recommended Settings:**
- Batch size: 5-10 emails
- Wait time: 30-60 seconds between batches
- Adjust based on your provider's limits

## Domain Requirements

### Do You Need a Domain?

**Short Answer**: No, but highly recommended.

**Without Domain (Can Start Immediately):**
- ✅ Can use free email providers (Gmail, Outlook) as sender
- ✅ Works for testing and small campaigns
- ⚠️ Lower deliverability (may go to spam)
- ⚠️ Limited authentication options

**With Domain (Recommended for Production):**
- ✅ Better deliverability (less spam)
- ✅ Professional sender address (e.g., `noreply@yourdomain.com`)
- ✅ Can set up SPF, DKIM, DMARC authentication
- ✅ Required by some providers for higher limits
- 💰 Cost: $10-20/year for .com/.net domain

**When to Buy Domain:**
- Before sending to real recipients
- When scaling beyond 100-200 emails/day
- For professional/business use

**Domain Setup Steps** (after buying):
1. Verify domain in your email provider dashboard
2. Add SPF record to DNS
3. Add DKIM record to DNS
4. Add DMARC record (optional but recommended)
5. Provider will guide you through this process


## Folder Structure

```
n8n-email-agent/
├── docker-compose.yml    # Docker Compose configuration
├── .env                  # Environment variables (create from env.example)
├── env.example           # Example environment file
├── start.ps1            # Start n8n script
├── stop.ps1             # Stop n8n script
├── setup-secrets.ps1    # Setup authentication script
├── README.md            # This file
├── data/                # n8n persistent data (created automatically)
├── backups/             # Workflow backups (export from n8n UI)
├── csv/                 # CSV files (emails, classifications, tracking)
│   ├── emails_clean.csv        # Your input email list
│   ├── master_tracking.csv     # Master CRM tracking file
│   ├── potential_buyers.csv   # Potential buyers
│   ├── demo_scheduled.csv     # Demo scheduled
│   ├── leads.csv              # Leads
│   ├── more_information.csv   # More information requests
│   ├── price_objection.csv    # Price objections
│   ├── not_right_time.csv     # Not right time
│   ├── follow_up_needed.csv   # Follow-up needed
│   ├── not_interested.csv     # Not interested
│   ├── wrong_person.csv       # Wrong person
│   ├── out_of_office.csv      # Out of office
│   ├── unsubscribes.csv       # Unsubscribes
│   ├── customers.csv          # Customers
│   ├── bounces.csv            # Bounced emails
│   ├── unknown.csv            # Unclassified
│   └── metrics_summary.csv    # Calculated metrics
└── metrics/             # Analytics and reports (optional)
```

## Workflow Summary

### Workflow 1: Batch Email Sending
- Reads `emails_clean.csv`
- Sends emails in batches (5-10 at a time)
- Waits 30-60 seconds between batches
- Logs to `csv/master_tracking.csv`

### Workflow 2: Automatic Gmail Response Classification
- Monitors your Gmail inbox for replies (every 5-15 minutes)
- **Automatically classifies** responses using keyword matching
- 14 classification types: Potential Buyers, Demo Scheduled, Leads, More Information, Price Objection, Not Right Time, Follow-up Needed, Not Interested, Wrong Person, Out of Office, Unsubscribe, Customer, Bounce, Unknown
- Writes to separate CSV files per classification
- Updates `csv/master_tracking.csv` with reply status and classification

### Workflow 3: CRM Analytics (Optional)
- Reads `csv/master_tracking.csv`
- Calculates metrics: open rate, reply rate, conversion rates
- Generates reports

## Configuration Summary

✅ **Response Classification**: Automatic (keyword-based)  
✅ **Open Tracking**: Enabled (using SendGrid/Mailgun or self-hosted)  
✅ **Classification Types**: 14 types (see section 9 above)  
✅ **CSV Storage**: Local files in `csv/` folder  
✅ **Gmail Setup**: Required - Enable Gmail API in Google Cloud Console

### Gmail API Setup (Required)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable **Gmail API**
4. Create **OAuth 2.0 credentials** (Desktop app)
5. Download credentials JSON
6. In n8n UI → Credentials → Gmail OAuth2
7. Upload credentials and complete OAuth flow
8. Grant permissions to read emails

## Essential Commands

### Start/Stop n8n
```powershell
.\start.ps1              # Start n8n
.\stop.ps1               # Stop n8n
docker-compose restart   # Restart n8n
```

### View Logs & Status
```powershell
docker-compose logs -f n8n    # View logs (follow mode)
docker-compose ps             # Check container status
docker ps                     # List all containers
```

### Update n8n
```powershell
docker-compose pull      # Download latest image
docker-compose up -d     # Restart with new image
```

### Troubleshooting Commands
```powershell
docker info                                    # Check Docker is running
netstat -ano | findstr :5678                  # Check if port 5678 is in use
Get-Content .env | Select-String "N8N"       # Verify .env file
docker-compose down -v                        # Remove everything (⚠️ deletes data)
```

## Quick Reference

### Access Points
- **n8n UI**: http://localhost:5678
- **Username**: `admin` (or your `N8N_BASIC_AUTH_USER`)
- **Password**: (your `N8N_BASIC_AUTH_PASSWORD`)

### Provider Limits
| Provider | Free Tier | Rate Limit | SMTP Host |
|----------|-----------|------------|-----------|
| **Mailjet** ⭐ | **6,000/month** | Varies | `in-v3.mailjet.com` |
| SendGrid | 100/day | ~100/sec | `smtp.sendgrid.net` |
| Mailgun | 5,000/month (3mo) | Varies | `smtp.mailgun.org` |
| SES | 200/day (sandbox) | 1/sec | `email-smtp.[region].amazonaws.com` |

**Recommended**: Batch size 5-10, wait 30-60 seconds between batches

### Classification Types
See [CLASSIFICATION_TYPES.md](CLASSIFICATION_TYPES.md) for complete list of 14 classification types and keywords.

## Setup Checklist

- [ ] Docker Desktop installed and running
- [ ] Run `.\setup-secrets.ps1` to configure authentication
- [ ] Start n8n: `.\start.ps1`
- [ ] Access http://localhost:5678 and login
- [ ] Configure SMTP credential in n8n UI
- [ ] Configure Gmail OAuth2 credential in n8n UI
- [ ] Place `emails_clean.csv` in project folder
- [ ] Create email sending workflow
- [ ] Create Gmail classification workflow
- [ ] Test with 5-10 own email addresses first

## Troubleshooting

### n8n won't start
- Check Docker Desktop is running
- Verify port 5678 is not in use: `netstat -ano | findstr :5678`
- Check logs: `docker-compose logs n8n`

### Can't access UI
- Verify `.env` file exists and has credentials
- Check firewall settings
- Try http://localhost:5678 (not https)
- Restart: `docker-compose restart`

### Authentication failed
- Verify `N8N_BASIC_AUTH_PASSWORD` in `.env`
- Restart n8n after changing `.env`
- Check logs for errors

### Webhooks not working
- Start ngrok: `ngrok http 5678`
- Update `WEBHOOK_URL` in `.env` to ngrok URL
- Restart: `docker-compose restart`

### Email sending fails
- Verify SMTP credentials in n8n UI
- Check provider sending limits
- Review provider dashboard for errors
- Test SMTP connection outside n8n first

## Security Notes

- ⚠️ Never commit `.env` file to git
- ⚠️ Store credentials in n8n UI, not in code
- ⚠️ Use strong passwords (12+ characters)
- ⚠️ Keep `emails_clean.csv` secure (in .gitignore)
- ⚠️ Test with your own emails first before real campaigns

---

**Important**: 
- Always test with your own email addresses first
- Start with small batches (5-10 emails)
- Monitor your email provider dashboard for limits
- Keep `emails_clean.csv` secure (it's in .gitignore)
