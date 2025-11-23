.PHONY: install dev test lint format clean help run run-api run-tunnel run-all stop-all setup-diff-viewer

# Default target
help:
	@echo "Available commands:"
	@echo "  install           - Install production dependencies"
	@echo "  dev               - Install development dependencies"
	@echo "  test              - Run tests"
	@echo "  lint              - Run linting checks"
	@echo "  format            - Format code"
	@echo "  clean             - Clean up generated files"
	@echo "  run               - Run the bot (foreground)"
	@echo ""
	@echo "Diff Viewer commands:"
	@echo "  run-api           - Run API server for Web App"
	@echo "  run-tunnel        - Run Cloudflare tunnel (requires cloudflared)"
	@echo "  run-all           - Run bot + API + tunnel in background"
	@echo "  stop-all          - Stop all background processes"
	@echo "  setup-diff-viewer - Generate secret and show setup instructions"

install:
	poetry install --no-dev

dev:
	poetry install
	poetry run pre-commit install --install-hooks || echo "pre-commit not configured yet"

test:
	poetry run pytest

lint:
	poetry run black --check src tests
	poetry run isort --check-only src tests
	poetry run flake8 src tests
	poetry run mypy src

format:
	poetry run black src tests
	poetry run isort src tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/ dist/ build/

run:
	poetry run claude-telegram-bot

# For debugging
run-debug:
	poetry run claude-telegram-bot --debug

# Diff Viewer - Run API server
run-api:
	@echo "🚀 Starting API server on http://localhost:8000"
	@echo "   API Docs: http://localhost:8000/docs"
	poetry run python run_api.py

# Diff Viewer - Run Cloudflare tunnel
run-tunnel:
	@echo "🌐 Starting Cloudflare tunnel..."
	@echo "   Copy the https:// URL and add to .env as WEBAPP_BASE_URL"
	@command -v cloudflared >/dev/null 2>&1 || { echo "❌ cloudflared not installed. Run: brew install cloudflare/cloudflare/cloudflared"; exit 1; }
	cloudflared tunnel --url http://localhost:8000

# Run all components (bot + API + tunnel) in background
run-all:
	@echo "🚀 Starting all components..."
	@echo ""
	@echo "1. Starting API server..."
	@poetry run python run_api.py > /tmp/claude-api.log 2>&1 & echo $$! > /tmp/claude-api.pid
	@sleep 2
	@echo "   ✅ API server running (PID: $$(cat /tmp/claude-api.pid))"
	@echo "   Logs: tail -f /tmp/claude-api.log"
	@echo ""
	@echo "2. Starting Cloudflare tunnel..."
	@command -v cloudflared >/dev/null 2>&1 || { echo "⚠️  cloudflared not installed (optional). Skipping tunnel..."; exit 0; }
	@cloudflared tunnel --url http://localhost:8000 > /tmp/claude-tunnel.log 2>&1 & echo $$! > /tmp/claude-tunnel.pid
	@echo "   Waiting for tunnel to start..."
	@sleep 8
	@TUNNEL_URL=$$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/claude-tunnel.log | tail -1); \
	if [ -n "$$TUNNEL_URL" ]; then \
		echo "   ✅ Tunnel running (PID: $$(cat /tmp/claude-tunnel.pid))"; \
		echo "   📍 URL: $$TUNNEL_URL"; \
		echo "$$TUNNEL_URL" > /tmp/claude-tunnel-url.txt; \
	else \
		echo "   ⚠️  Failed to get tunnel URL. Web App diff viewer will not work."; \
		echo "   Check logs: tail -f /tmp/claude-tunnel.log"; \
	fi
	@echo ""
	@echo "3. Starting Telegram bot..."
	@if [ -f /tmp/claude-tunnel-url.txt ]; then \
		WEBAPP_BASE_URL=$$(cat /tmp/claude-tunnel-url.txt) poetry run python -m src.main > /tmp/claude-bot.log 2>&1 & echo $$! > /tmp/claude-bot.pid; \
		echo "   ✅ Bot running with tunnel URL: $$(cat /tmp/claude-tunnel-url.txt)"; \
	else \
		poetry run python -m src.main > /tmp/claude-bot.log 2>&1 & echo $$! > /tmp/claude-bot.pid; \
		echo "   ✅ Bot running (using .env URL)"; \
	fi
	@sleep 2
	@echo "   PID: $$(cat /tmp/claude-bot.pid)"
	@echo "   Logs: tail -f /tmp/claude-bot.log"
	@echo ""
	@echo "✅ All components started!"
	@echo ""
	@echo "Logs:"
	@echo "  Bot:    tail -f /tmp/claude-bot.log"
	@echo "  API:    tail -f /tmp/claude-api.log"
	@if [ -f /tmp/claude-tunnel.pid ]; then echo "  Tunnel: tail -f /tmp/claude-tunnel.log"; fi
	@echo ""
	@echo "To stop all: make stop-all"

# Stop all background processes
stop-all:
	@echo "🛑 Stopping all components..."
	@if [ -f /tmp/claude-bot.pid ]; then kill $$(cat /tmp/claude-bot.pid) 2>/dev/null && rm /tmp/claude-bot.pid && echo "   ✅ Bot stopped"; fi
	@if [ -f /tmp/claude-api.pid ]; then kill $$(cat /tmp/claude-api.pid) 2>/dev/null && rm /tmp/claude-api.pid && echo "   ✅ API server stopped"; fi
	@if [ -f /tmp/claude-tunnel.pid ]; then kill $$(cat /tmp/claude-tunnel.pid) 2>/dev/null && rm /tmp/claude-tunnel.pid && echo "   ✅ Tunnel stopped"; fi
	@echo "   All components stopped."

# Setup diff viewer - generate secret and show instructions
setup-diff-viewer:
	@echo "🔧 Diff Viewer Setup"
	@echo ""
	@echo "1. Generate secret key:"
	@SECRET=$$(openssl rand -hex 32); \
	echo "   DIFF_VIEWER_SECRET=$$SECRET"; \
	echo ""; \
	echo "2. Add to .env file:"; \
	echo "   DIFF_VIEWER_SECRET=$$SECRET"; \
	echo "   WEBAPP_BASE_URL=<will be filled after running tunnel>"; \
	echo ""; \
	echo "3. Start components:"; \
	echo "   make run-api      # Terminal 1"; \
	echo "   make run-tunnel   # Terminal 2 (copy URL to .env)"; \
	echo "   make run          # Terminal 3"; \
	echo ""; \
	echo "Or run all at once:"; \
	echo "   make run-all"; \
	echo ""; \
	echo "See QUICKSTART_DIFF_VIEWER.md for details."