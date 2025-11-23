# Git Diff Viewer Setup Guide

This guide will help you set up the Git Diff Viewer feature for your Telegram bot.

## Overview

The Diff Viewer adds a "👁️ View Diff" button to the pinned status message, which opens a beautiful Web App to view git changes.

## Prerequisites

- Python 3.10+
- Poetry (package manager)
- A public HTTPS URL (via Cloudflare Tunnel or ngrok)

## Step-by-Step Setup

### 1. Install Dependencies

Dependencies are already added to `pyproject.toml`. If you need to reinstall:

```bash
poetry install
```

This installs:
- `pyjwt` - JWT token generation/validation
- `fastapi` - Web API framework
- `uvicorn` - ASGI server

### 2. Generate Secret Key

Generate a secure random key for JWT tokens:

```bash
openssl rand -hex 32
```

Copy the output (should be 64 characters).

### 3. Configure Environment Variables

Edit your `.env` file and add:

```env
# === WEB APP SETTINGS ===
# Base URL for Telegram Web App (from Cloudflare Tunnel or ngrok)
WEBAPP_BASE_URL=https://your-tunnel-url.trycloudflare.com

# Secret key for diff viewer JWT tokens
DIFF_VIEWER_SECRET=<paste the key from step 2>
```

**Important:** Leave `WEBAPP_BASE_URL` empty for now, we'll fill it in step 5.

### 4. Start the API Server

In a **separate terminal window**, run:

```bash
python run_api.py
```

You should see:

```
🚀 Starting FastAPI server...
📁 Webapp directory: /path/to/webapp
⚠️  WEBAPP_BASE_URL not configured. Web App buttons will not appear.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Keep this running.

### 5. Setup Public Tunnel

Telegram Web Apps require a public HTTPS URL. Choose **one** option:

#### Option A: Cloudflare Tunnel (Recommended - Free, No Account)

```bash
# Install (macOS)
brew install cloudflare/cloudflare/cloudflared

# Or download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

# Run tunnel (in another terminal)
cloudflared tunnel --url http://localhost:8000
```

You'll see output like:

```
Your quick Tunnel has been created! Visit it at:
https://random-name-abc123.trycloudflare.com
```

**Copy this URL** and paste it as `WEBAPP_BASE_URL` in `.env`:

```env
WEBAPP_BASE_URL=https://random-name-abc123.trycloudflare.com
```

#### Option B: ngrok (Alternative)

```bash
# Install (macOS)
brew install ngrok

# Or download from: https://ngrok.com/download

# Run tunnel
ngrok http 8000
```

Copy the `https://` URL and use it as `WEBAPP_BASE_URL`.

**Note:** Free ngrok URLs change each time you restart, so you'll need to update `.env` each time.

### 6. Restart the Bot

Stop your bot (Ctrl+C) and start it again:

```bash
python -m src.main
```

The bot will now pick up the new configuration.

### 7. Test the Feature

1. Send a message to your bot from a directory that's a git repository
2. Make some changes to files in the repository
3. Look at the pinned status message
4. You should see a "👁️ View Diff" button
5. Click it - a beautiful diff viewer should open in Telegram!

## Architecture

```
┌──────────────────┐
│  Telegram User   │
│  Clicks button   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  status_pin.py   │  Generates JWT token with repo path
│  (Bot)           │  Creates Web App URL with token
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Telegram Web    │  Opens in-app browser
│  App opens       │  Loads webapp/diff-viewer/index.html
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  app.js          │  Extracts token from URL
│  (Frontend)      │  Calls /api/diff/{token}
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  diff_viewer.py  │  Verifies JWT token
│  (API)           │  Validates repo path
│                  │  Runs git diff
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  git_integration │  Executes safe git command
│  (Git)           │  Returns diff output
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  diff2html       │  Renders beautiful diff
│  (Frontend)      │  Shows in Web App
└──────────────────┘
```

## Verification Checklist

- [ ] Dependencies installed (`poetry install`)
- [ ] Secret key generated and added to `.env`
- [ ] API server running (`python run_api.py`)
- [ ] Tunnel running (cloudflared or ngrok)
- [ ] `WEBAPP_BASE_URL` configured in `.env`
- [ ] `DIFF_VIEWER_SECRET` configured in `.env`
- [ ] Bot restarted
- [ ] In a git repository
- [ ] Changes made to files
- [ ] "👁️ View Diff" button appears
- [ ] Button opens Web App successfully
- [ ] Diff displays correctly

## Troubleshooting

### Button doesn't appear

**Check:**
1. Is `WEBAPP_BASE_URL` set in `.env`?
2. Is `DIFF_VIEWER_SECRET` set in `.env`?
3. Did you restart the bot after editing `.env`?
4. Is the API server running?

**Debug:**
```bash
# Check if settings are loaded
python -c "from src.config.loader import load_settings; s = load_settings(); print(f'URL: {s.webapp_base_url}, Secret: {bool(s.diff_viewer_secret_str)}')"
```

Should output:
```
URL: https://your-url.com, Secret: True
```

### "Invalid token" error

**Causes:**
- Token expired (default: 1 hour)
- Secret key mismatch between bot and API
- Bot and API using different `.env` files

**Fix:**
- Click button again to generate new token
- Verify `DIFF_VIEWER_SECRET` is the same in `.env`
- Restart both bot and API server

### Web App doesn't load

**Check:**
1. Is API server running? (`python run_api.py`)
2. Is tunnel running? (cloudflared/ngrok)
3. Does `WEBAPP_BASE_URL` match tunnel URL?

**Test API directly:**
```bash
# Should return: {"message": "Claude Code Telegram Bot API", "status": "running"}
curl https://your-tunnel-url.trycloudflare.com/
```

### Diff doesn't display

**Check API logs:**
- Look at the API server terminal output
- Should see: `INFO: GET /api/diff/{token}`

**Common issues:**
- Repository path not in approved directory
- Git repository not initialized
- No changes to show

**Test:**
```bash
# In your repository
git status
git diff  # Should show changes
```

### Tunnel URL keeps changing

If using ngrok free tier, URL changes each restart.

**Solutions:**
1. Use Cloudflare Tunnel (free, stable URLs during session)
2. Upgrade to ngrok paid plan (static URLs)
3. Deploy API to a VPS with static domain

## Production Deployment

For production use, instead of tunnels:

1. Deploy API to a server with a domain (e.g., Heroku, Railway, DigitalOcean)
2. Set up SSL/TLS certificate
3. Configure `WEBAPP_BASE_URL` to your domain
4. Consider using environment-specific secrets

Example production setup:

```env
# Production .env
WEBAPP_BASE_URL=https://bot-api.yourdomain.com
DIFF_VIEWER_SECRET=<production-secret-key>
```

## Development Tips

### Run API with auto-reload

```bash
uvicorn src.api.server:create_app --factory --reload --port 8000
```

### Test token generation

```python
from pathlib import Path
from src.api.diff_viewer import generate_diff_token, verify_diff_token

# Generate token
repo_path = Path("/path/to/repo")
token = generate_diff_token(repo_path, "test-secret")
print(f"Token: {token}")

# Verify token
verified_path = verify_diff_token(token, "test-secret")
print(f"Verified path: {verified_path}")
```

### Customize token expiry

Edit `src/bot/features/status_pin.py`:

```python
token = generate_diff_token(
    current_path,
    settings.diff_viewer_secret_str,
    expiry_hours=24  # Change from 1 to 24 hours
)
```

## Security Notes

- JWT tokens are signed with `DIFF_VIEWER_SECRET`
- Tokens expire after 1 hour by default
- Repository paths are validated against `APPROVED_DIRECTORY`
- Only read-only git operations are allowed
- No authentication is needed beyond the token

**Keep your `DIFF_VIEWER_SECRET` secret!** Don't commit it to git.

## Next Steps

After successful setup, you might want to:

1. Add more buttons (e.g., "Git Status", "Refresh")
2. Customize the diff viewer appearance
3. Add features like file filtering or search
4. Integrate with other git operations

See `webapp/diff-viewer/README.md` for customization options.

## Support

If you encounter issues:

1. Check logs: bot terminal + API server terminal + tunnel terminal
2. Verify all environment variables are set correctly
3. Test each component individually (API, tunnel, token generation)
4. Check Telegram Web App documentation: https://core.telegram.org/bots/webapps

## Summary

You now have a beautiful, secure git diff viewer integrated with your Telegram bot!

The workflow is:
1. User makes changes in git repo
2. Bot shows status with "View Diff" button
3. User clicks button
4. Telegram Web App opens with beautiful diff view
5. Changes are displayed with syntax highlighting

Enjoy! 🎉
