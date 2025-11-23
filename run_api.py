#!/usr/bin/env python3
"""Run FastAPI server for Telegram Web App."""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    """Run the API server."""
    import uvicorn

    from src.api.server import create_app
    from src.config.loader import load_config

    # Load settings
    settings = load_config()

    # Check configuration
    if not settings.webapp_base_url:
        logger.warning(
            "⚠️  WEBAPP_BASE_URL not configured. Web App buttons will not appear."
        )
        logger.warning("   Set WEBAPP_BASE_URL in .env to your public URL")

    if not settings.diff_viewer_secret_str:
        logger.warning(
            "⚠️  DIFF_VIEWER_SECRET not configured. Diff viewer will not work."
        )
        logger.warning("   Generate with: openssl rand -hex 32")

    logger.info("🚀 Starting FastAPI server...")
    logger.info(f"📁 Webapp directory: {Path(__file__).parent / 'webapp'}")

    if settings.webapp_base_url:
        logger.info(f"🌐 Web App URL: {settings.webapp_base_url}")
        logger.info(f"   Diff Viewer: {settings.webapp_base_url}/diff-viewer/")

    # Create app
    app = create_app()

    # Run server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
