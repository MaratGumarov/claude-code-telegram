"""FastAPI server for Telegram Web App endpoints."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.diff_viewer import router as diff_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Claude Code Telegram Bot API",
        description="Web App endpoints for Telegram bot",
        version="0.1.0",
    )

    # Configure CORS for Telegram Web App
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://web.telegram.org"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Mount static files for webapp
    webapp_dir = Path(__file__).parent.parent.parent / "webapp"
    if webapp_dir.exists():
        app.mount("/static", StaticFiles(directory=str(webapp_dir)), name="static")
        logger.info(f"Mounted static files from {webapp_dir}")

    # Register API routers
    app.include_router(diff_router, prefix="/api", tags=["diff-viewer"])

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {"message": "Claude Code Telegram Bot API", "status": "running"}

    @app.get("/diff-viewer/")
    async def diff_viewer_app():
        """Serve diff viewer Web App."""
        index_path = webapp_dir / "diff-viewer" / "index.html"
        if not index_path.exists():
            return {"error": "Diff viewer not found"}
        return FileResponse(index_path)

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
