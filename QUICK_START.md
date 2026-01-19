# Quick Start Guide - Exact Commands

Since you already have Docker Desktop installed, follow these steps in order:

## Step-by-Step Commands

### Step 1: Open Docker Desktop
1. Launch **Docker Desktop** application
2. Wait until you see "Docker Desktop is running" (whale icon in system tray)
3. **Don't proceed until Docker is running!**

### Step 2: Navigate to Project Folder
```powershell
cd C:\Users\User\Desktop\n8n-email-agent
```

### Step 3: Setup Secrets (First Time Only)
```powershell
.\setup-secrets.ps1
```

**What this does:**
- Creates `.env` file from `env.example`
- Generates a secure encryption key
- Prompts you for an admin password
- Updates `.env` with your credentials

**You'll be asked:**
- Enter a password for n8n admin access (choose a strong password)

### Step 4: Start n8n
```powershell
.\start.ps1
```

**What this does:**
- Checks if `.env` file exists ✅
- Checks if Docker is running ✅
- Downloads n8n Docker image (~200 MB) - **first time only**
- Creates and starts n8n container
- Makes n8n available at http://localhost:5678

**Expected output:**
```
Starting n8n Email Agent...
Starting Docker Compose...

n8n is starting up...
Wait 30-60 seconds, then open:
  http://localhost:5678
```

### Step 5: Wait & Access n8n
1. **Wait 30-60 seconds** for n8n to fully start
2. Open your browser
3. Go to: **http://localhost:5678**
4. Login with:
   - **Username**: `admin`
   - **Password**: (the password you entered in Step 3)

## What to Do After Login

### 1. Configure SMTP Credential (Email Sending)

1. Click **Settings** (gear icon) → **Credentials**
2. Click **+ Add Credential**
3. Search for **SMTP** and select it
4. Fill in:
   - **Name**: `Mailjet SMTP` (or your provider name)
   - **Host**: 
     - Mailjet: `in-v3.mailjet.com`
     - SendGrid: `smtp.sendgrid.net`
     - Mailgun: `smtp.mailgun.org`
   - **Port**: `587`
   - **User**: Your API key or SMTP username
   - **Password**: Your API secret or SMTP password
   - **Secure**: Enable **TLS**
5. Click **Save**

### 2. Configure Gmail Credential (Response Classification)

1. In **Credentials**, click **+ Add Credential**
2. Search for **Gmail OAuth2** and select it
3. Follow the OAuth flow:
   - You'll be redirected to Google
   - Sign in with your Gmail account
   - Grant permissions to read emails
   - Return to n8n
4. Click **Save**

**Note**: If you don't have Gmail API set up yet, you can skip this for now and add it later.

### 3. Place Your Email List

1. Put your `emails_clean.csv` file in the project folder:
   ```
   C:\Users\User\Desktop\n8n-email-agent\emails_clean.csv
   ```

2. CSV should have columns:
   - `email` (required)
   - `name` (optional)
   - `university` (optional)
   - `department` (optional)

### 4. Create Your First Workflow

1. Click **+ Add workflow** in n8n
2. Follow the workflow setup from README.md section 6
3. Start with a test workflow sending to your own email

## Troubleshooting

### If `.\start.ps1` fails:

**Error: "Docker is not running"**
- Make sure Docker Desktop is open and running
- Check system tray for Docker icon
- Restart Docker Desktop if needed

**Error: ".env file not found"**
- Run `.\setup-secrets.ps1` first (Step 3)

**Error: "Port 5678 is already in use"**
- Another application is using port 5678
- Change port in `.env`: `N8N_PORT=5679`
- Or stop the other application

### If you can't access http://localhost:5678:

1. Check if container is running:
   ```powershell
   docker ps
   ```
   You should see `n8n-email-agent` in the list

2. Check logs:
   ```powershell
   docker-compose logs n8n
   ```

3. Wait longer (sometimes takes 60+ seconds on first start)

## Next Commands You'll Need

### View Logs (if something goes wrong)
```powershell
docker-compose logs -f n8n
```

### Stop n8n
```powershell
.\stop.ps1
```
or
```powershell
docker-compose down
```

### Restart n8n
```powershell
docker-compose restart
```

### Check Container Status
```powershell
docker ps
```

---

## Summary - Exact Order

1. ✅ Open Docker Desktop (wait for it to start)
2. ✅ `cd C:\Users\User\Desktop\n8n-email-agent`
3. ✅ `.\setup-secrets.ps1` (enter password when prompted)
4. ✅ `.\start.ps1` (wait 30-60 seconds)
5. ✅ Open http://localhost:5678 in browser
6. ✅ Login with `admin` + your password
7. ✅ Configure SMTP credential
8. ✅ Configure Gmail credential (optional for now)
9. ✅ Place `emails_clean.csv` in project folder
10. ✅ Create workflows in n8n UI

**That's it!** You're ready to build your email campaign workflows.
