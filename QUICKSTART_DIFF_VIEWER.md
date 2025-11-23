# Quick Start: Git Diff Viewer

## TL;DR - Get Started in 5 Minutes

### 1. Generate Secret Key

```bash
openssl rand -hex 32
```

Copy the output.

### 2. Edit `.env`

Add these lines at the end:

```env
# Leave empty for now - we'll fill this in step 4
WEBAPP_BASE_URL=

# Paste the key from step 1
DIFF_VIEWER_SECRET=<your-64-character-key>
```

### 3. Start API Server

Open a **new terminal** and run:

```bash
python run_api.py
```

Keep this running.

### 4. Start Cloudflare Tunnel

Open **another terminal** and run:

```bash
# If not installed: brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel --url http://localhost:8000
```

You'll see output like:

```
Your quick Tunnel has been created! Visit it at:
https://random-words-1234.trycloudflare.com
```

**Copy that URL** (starts with `https://`).

### 5. Update `.env` with URL

Edit `.env` and paste the URL:

```env
WEBAPP_BASE_URL=https://random-words-1234.trycloudflare.com
```

Save the file.

### 6. Restart the Bot

In your bot terminal, press `Ctrl+C` to stop, then run:

```bash
python -m src.main
```

### 7. Test It!

1. Send a message to your bot from a git repository
2. Make some changes to files: `echo "test" >> test.txt`
3. Look at the pinned message - you should see "👁️ View Diff" button
4. Click it!

## What You Should See

✅ Pinned message with: `🟢 main +3/-0 ~/...src` and a button
✅ Click button → Beautiful diff viewer opens in Telegram
✅ Syntax-highlighted changes displayed

## Troubleshooting

### No button appears?

```bash
# Check configuration
python -c "from src.config.loader import load_settings; s = load_settings(); print(f'URL: {s.webapp_base_url}, Secret: {bool(s.diff_viewer_secret_str)}')"
```

Should show:
```
URL: https://your-url.com, Secret: True
```

If not, check `.env` and restart the bot.

### Button appears but Web App doesn't load?

1. Check API server is running (terminal with `run_api.py`)
2. Check tunnel is running (terminal with `cloudflared`)
3. Verify URL in `.env` matches the tunnel URL

### Need help?

See full documentation: `docs/DIFF_VIEWER_SETUP.md`

## Terminal Setup Summary

You need 3 terminals running:

```
Terminal 1: python -m src.main              # Telegram bot
Terminal 2: python run_api.py               # API server
Terminal 3: cloudflared tunnel --url ...    # Public tunnel
```

That's it! Enjoy your beautiful diff viewer! 🎉
