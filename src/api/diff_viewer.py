"""Diff viewer API endpoint for Telegram Web App."""

import datetime
import logging
from pathlib import Path
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.bot.features.git_integration import GitError, GitIntegration
from src.config.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter()


class DiffResponse(BaseModel):
    """Response model for diff endpoint."""

    diff: str
    repo_path: str
    branch: Optional[str] = None


def generate_diff_token(repo_path: Path, secret: str, expiry_hours: int = 1) -> str:
    """Generate JWT token for secure diff access.

    Args:
        repo_path: Path to the git repository
        secret: Secret key for JWT encoding
        expiry_hours: Token expiry time in hours

    Returns:
        Encoded JWT token
    """
    payload = {
        "repo_path": str(repo_path),
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=expiry_hours),
        "iat": datetime.datetime.now(datetime.UTC),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_diff_token(token: str, secret: str) -> Path:
    """Verify and decode diff viewer token.

    Args:
        token: JWT token to verify
        secret: Secret key for JWT decoding

    Returns:
        Repository path from token

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        repo_path = Path(payload["repo_path"])
        return repo_path
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


@router.get("/diff/{token}")
async def get_diff(token: str) -> DiffResponse:
    """Get git diff by token.

    Args:
        token: JWT token containing repository path

    Returns:
        DiffResponse with git diff output

    Raises:
        HTTPException: If token invalid, expired, or git operation fails
    """
    # Get settings (in production, inject via dependency)
    from src.config.loader import load_config

    settings = load_config()

    if not settings.diff_viewer_secret_str:
        raise HTTPException(
            status_code=500, detail="Diff viewer not configured (missing secret)"
        )

    # Verify and decode token
    repo_path = verify_diff_token(token, settings.diff_viewer_secret_str)

    # Validate path is within approved directory
    try:
        repo_path = repo_path.resolve()
        if not repo_path.is_relative_to(settings.approved_directory):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid repository path")

    # Get git diff
    try:
        git_integration = GitIntegration(settings)

        # Get current branch
        status = await git_integration.get_status(repo_path)
        branch = status.branch

        # Get diff output (raw, without emoji formatting for diff2html)
        diff_output, _ = await git_integration.execute_git_command(
            ["git", "diff", "--no-color"], repo_path
        )

        if not diff_output.strip():
            diff_output = "No changes to show"

        logger.info(f"Generated diff for {repo_path}, branch={branch}")

        return DiffResponse(diff=diff_output, repo_path=str(repo_path), branch=branch)

    except GitError as e:
        logger.error(f"Git error getting diff: {e}")
        raise HTTPException(status_code=500, detail=f"Git error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error getting diff: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
