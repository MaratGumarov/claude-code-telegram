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
	@echo "  run               - Run the bot"
	@echo ""
	@echo "Diff Viewer commands:"
	@echo "  run-api           - Run API server for Web App"
	@echo "  run-tunnel        - Run Cloudflare tunnel (requires cloudflared)"
	@echo "  run-all           - Run API + tunnel in background"
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
	@command -v cloudflared >/dev/null 2>&1 || { echo "❌ cloudflared not installed. Run: brew install cloudflare/cloudflare/cloudflared"; exit 1; }
	@cloudflared tunnel --url http://localhost:8000 > /tmp/claude-tunnel.log 2>&1 & echo $$! > /tmp/claude-tunnel.pid
	@echo "   Waiting for tunnel to start..."
	@sleep 5
	@TUNNEL_URL=$$(grep -o 'https://[^[:space:]]*\.trycloudflare\.com' /tmp/claude-tunnel.log | head -1); \
	if [ -n "$$TUNNEL_URL" ]; then \
		echo "   ✅ Tunnel running (PID: $$(cat /tmp/claude-tunnel.pid))"; \
		echo "   📍 URL: $$TUNNEL_URL"; \
		echo ""; \
		echo "3. Updating .env with tunnel URL..."; \
		if grep -q "^WEBAPP_BASE_URL=" .env; then \
			sed -i.bak "s|^WEBAPP_BASE_URL=.*|WEBAPP_BASE_URL=$$TUNNEL_URL|" .env && rm .env.bak; \
			echo "   ✅ Updated WEBAPP_BASE_URL in .env"; \
		else \
			echo "WEBAPP_BASE_URL=$$TUNNEL_URL" >> .env; \
			echo "   ✅ Added WEBAPP_BASE_URL to .env"; \
		fi; \
		echo ""; \
		echo "4. Now run the bot:"; \
		echo "   make run"; \
	else \
		echo "   ❌ Failed to get tunnel URL. Check logs:"; \
		echo "   tail -f /tmp/claude-tunnel.log"; \
	fi
	@echo ""
	@echo "Logs:"
	@echo "  API:    tail -f /tmp/claude-api.log"
	@echo "  Tunnel: tail -f /tmp/claude-tunnel.log"
	@echo ""
	@echo "To stop all: make stop-all"

# Stop all background processes
stop-all:
	@echo "Stopping all components..."
	@if [ -f /tmp/claude-api.pid ]; then kill $$(cat /tmp/claude-api.pid) 2>/dev/null && rm /tmp/claude-api.pid && echo "✅ API server stopped"; fi
	@if [ -f /tmp/claude-tunnel.pid ]; then kill $$(cat /tmp/claude-tunnel.pid) 2>/dev/null && rm /tmp/claude-tunnel.pid && echo "✅ Tunnel stopped"; fi

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