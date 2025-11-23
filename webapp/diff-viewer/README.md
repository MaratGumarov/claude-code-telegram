# Git Diff Viewer - Telegram Web App

Beautiful diff viewer for git changes, integrated with Telegram Web App.

## Features

- 🎨 Beautiful syntax-highlighted diff display using diff2html
- 📱 Mobile-optimized interface
- 🌓 Automatic dark/light theme based on Telegram settings
- 🔒 Secure JWT token-based authentication
- ⚡ Fast, lightweight, no build step required

## How it works

1. Bot generates a JWT token containing the repository path
2. Token is embedded in Web App URL
3. User clicks "👁️ View Diff" button in pinned message
4. Web App opens in Telegram, fetches diff from API
5. Diff is beautifully rendered with syntax highlighting

## Setup

### 1. Configure Environment Variables

Add to your `.env` file:

```env
# Base URL for your Web App (from Cloudflare Tunnel or ngrok)
WEBAPP_BASE_URL=https://your-tunnel-url.trycloudflare.com

# Secret key for JWT tokens (generate with: openssl rand -hex 32)
DIFF_VIEWER_SECRET=your-secret-key-here
```

### 2. Setup Public URL

You need a public HTTPS URL for Telegram Web App. Choose one:

#### Option A: Cloudflare Tunnel (Recommended)

```bash
# Install
brew install cloudflare/cloudflare/cloudflared

# Run tunnel
cloudflared tunnel --url http://localhost:8000

# Copy the https://*.trycloudflare.com URL to WEBAPP_BASE_URL
```

#### Option B: ngrok

```bash
# Install
brew install ngrok

# Run tunnel
ngrok http 8000

# Copy the https URL to WEBAPP_BASE_URL
```

### 3. Start the API Server

```bash
# In a separate terminal
python -m uvicorn src.api.server:create_app --factory --host 0.0.0.0 --port 8000
```

Or use the provided script (if available):

```bash
make run-api
```

### 4. Start the Bot

```bash
python -m src.main
```

## Usage

1. Send a message to your bot from a git repository
2. Look at the pinned status message
3. Click "👁️ View Diff" button
4. Enjoy beautiful diff view in Telegram!

## Architecture

```
┌─────────────────┐
│  Telegram Bot   │
│   (status_pin)  │
└────────┬────────┘
         │ generates JWT token
         │
         ▼
┌─────────────────┐
│   Web App URL   │
│ /diff-viewer/   │
│  ?token=xxx     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   FastAPI API   │
│  /api/diff/{t}  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Git Integration│
│   (git diff)    │
└─────────────────┘
```

## Security

- JWT tokens expire after 1 hour
- Tokens are signed with DIFF_VIEWER_SECRET
- Repository path is validated against approved directory
- Only read-only git operations are allowed

## Customization

### Change Token Expiry

Edit `src/bot/features/status_pin.py`:

```python
token = generate_diff_token(
    current_path, settings.diff_viewer_secret_str,
    expiry_hours=2  # Change from 1 to 2 hours
)
```

### Customize Diff View

Edit `webapp/diff-viewer/app.js` configuration:

```javascript
const configuration = {
    drawFileList: true,      // Show file list
    outputFormat: 'side-by-side',  // or 'line-by-line'
    highlight: true,         // Syntax highlighting
    // ... more options
};
```

## Troubleshooting

### Button doesn't appear

Check:
1. `WEBAPP_BASE_URL` is set in `.env`
2. `DIFF_VIEWER_SECRET` is set in `.env`
3. API server is running
4. Bot has been restarted after config changes

### "Invalid token" error

- Token expired (default 1 hour)
- Click button again to generate new token
- Check `DIFF_VIEWER_SECRET` matches in bot and API

### Diff doesn't load

- Check API server logs
- Verify tunnel is running and accessible
- Check CORS settings in `src/api/server.py`

## Development

### Run API in development mode with auto-reload

```bash
uvicorn src.api.server:create_app --factory --reload --port 8000
```

### Test API directly

```bash
# Generate a test token (you'll need to create a script)
python -c "from src.api.diff_viewer import generate_diff_token; print(generate_diff_token('/path/to/repo', 'secret'))"

# Test endpoint
curl http://localhost:8000/api/diff/{token}
```

## Future Enhancements

- [ ] Stage/unstage files from Web App
- [ ] Commit from Web App
- [ ] File tree navigation
- [ ] Search within diff
- [ ] Export diff as patch file
