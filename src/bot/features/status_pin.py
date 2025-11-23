"""Pinned status message management for compact status display.

Provides compact status formatting optimized for mobile displays (~36 characters).
Format: 🟢main +42/-27 ~/...src
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

from telegram import Chat, Message
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ...config.settings import Settings
from .git_integration import GitIntegration, GitError

logger = logging.getLogger(__name__)


class StatusFormatter:
    """Formats status information in compact form for pinned messages."""

    MAX_VISIBLE_CHARS = 36  # Typical mobile display limit
    MAX_BRANCH_LENGTH = 12  # Max length for branch name
    MAX_PATH_LENGTH = 15  # Max length for path display

    @staticmethod
    def format_compact_status(
        status_emoji: str,
        branch: Optional[str],
        added_lines: Optional[int],
        deleted_lines: Optional[int],
        current_path: Path,
        approved_directory: Path,
        changed_files: Optional[list] = None,
    ) -> str:
        """Format compact status message with detailed file list.

        Args:
            status_emoji: Status emoji (🟢/🟡/🔴)
            branch: Git branch name
            added_lines: Lines added in diff
            deleted_lines: Lines deleted in diff
            current_path: Current working directory
            approved_directory: Approved base directory
            changed_files: List of (filename, added, deleted) tuples

        Returns:
            Multi-line status: first line compact, rest are file details
        """
        parts = [status_emoji]

        # Add branch if available
        if branch:
            short_branch = StatusFormatter._shorten_branch(branch)
            parts.append(short_branch)

        # Add diff stats if available
        if added_lines is not None and deleted_lines is not None:
            diff_stats = StatusFormatter._format_diff_stats(added_lines, deleted_lines)
            if diff_stats:
                parts.append(diff_stats)

        # Add path
        short_path = StatusFormatter._shorten_path(current_path, approved_directory)
        parts.append(short_path)

        # First line: compact status
        lines = [" ".join(parts)]
        
        # Add file details if available
        if changed_files:
            for filename, added, deleted in changed_files[:20]:  # Limit to 20 files
                # Shorten long filenames
                if len(filename) > 40:
                    filename = "..." + filename[-37:]
                file_stats = f"+{added}/-{deleted}"
                lines.append(f"{filename} {file_stats}")
            
            if len(changed_files) > 20:
                lines.append(f"... and {len(changed_files) - 20} more files")

        return "\n".join(lines)

    @staticmethod
    def _shorten_branch(branch: str) -> str:
        """Shorten branch name to fit display.

        Examples:
            - main -> main
            - feature/authentication -> feat/auth
            - bugfix/very-long-name -> bug.../name
        """
        if len(branch) <= StatusFormatter.MAX_BRANCH_LENGTH:
            return branch

        # Try common prefixes
        prefix_map = {
            "feature/": "feat/",
            "bugfix/": "bug/",
            "hotfix/": "hot/",
            "release/": "rel/",
        }

        for long_prefix, short_prefix in prefix_map.items():
            if branch.startswith(long_prefix):
                rest = branch[len(long_prefix):]
                shortened = short_prefix + rest
                if len(shortened) <= StatusFormatter.MAX_BRANCH_LENGTH:
                    return shortened
                # Still too long, truncate
                available = StatusFormatter.MAX_BRANCH_LENGTH - len(short_prefix) - 3
                return f"{short_prefix}{rest[:available]}..."

        # No prefix match, show beginning and end
        if "/" in branch:
            parts = branch.split("/")
            # Show last part with ellipsis
            last_part = parts[-1]
            if len(last_part) <= StatusFormatter.MAX_BRANCH_LENGTH - 4:
                return f".../{last_part}"

        # Just truncate
        return branch[:StatusFormatter.MAX_BRANCH_LENGTH - 3] + "..."

    @staticmethod
    def _shorten_path(current_path: Path, approved_directory: Path) -> str:
        """Shorten path for compact display.

        Examples:
            - /Users/user/Projects/bot/src -> ~/...src
            - /Users/user/Projects/bot -> ~/bot
        """
        try:
            # Get relative path
            rel_path = current_path.relative_to(approved_directory)
            path_str = f"~/{rel_path}" if str(rel_path) != "." else "~"

            # If short enough, return as-is
            if len(path_str) <= StatusFormatter.MAX_PATH_LENGTH:
                return path_str

            # Show ~/...ending format
            parts = rel_path.parts
            if parts:
                # Try to show last 1-2 parts
                ending = parts[-1]
                if len(ending) + 5 <= StatusFormatter.MAX_PATH_LENGTH:  # ~/... + ending
                    return f"~/...{ending}"

                # Just show truncated ending
                max_ending = StatusFormatter.MAX_PATH_LENGTH - 5
                return f"~/...{ending[:max_ending]}"

            return "~"

        except ValueError:
            # Path is not relative to approved directory
            return "~"

    @staticmethod
    def _format_diff_stats(added: int, deleted: int) -> str:
        """Format diff statistics compactly.

        Args:
            added: Lines added
            deleted: Lines deleted

        Returns:
            Formatted string like "+42/-27" or empty if no changes
        """
        if added == 0 and deleted == 0:
            return ""

        # Format large numbers compactly
        def format_num(n: int) -> str:
            if n >= 1000:
                return f"{n / 1000:.1f}k"
            return str(n)

        return f"+{format_num(added)}/-{format_num(deleted)}"

    @staticmethod
    def get_status_emoji(status: str) -> str:
        """Get emoji for current status.

        Args:
            status: One of "ready", "processing", "error"

        Returns:
            Status emoji
        """
        emoji_map = {
            "ready": "🟢",
            "processing": "🟡",
            "error": "🔴",
        }
        return emoji_map.get(status, "🟢")


class PinnedMessageManager:
    """Manages pinned status message updates."""

    def __init__(self, git_integration: Optional[GitIntegration] = None):
        """Initialize pinned message manager.

        Args:
            git_integration: Git integration instance for stats
        """
        self.git_integration = git_integration
        self._update_lock = asyncio.Lock()

    async def update_status(
        self,
        chat: Chat,
        context: ContextTypes.DEFAULT_TYPE,
        context_key: str,
        current_path: Path,
        settings: Settings,
        status: str = "ready",
    ) -> Optional[Message]:
        """Update or create pinned status message.

        Args:
            chat: Telegram chat object
            context: Bot context
            context_key: Context key for this chat/thread
            current_path: Current working directory
            settings: Bot settings
            status: Current status (ready/processing/error)

        Returns:
            Pinned message object or None
        """
        async with self._update_lock:
            try:
                # Get status emoji
                status_emoji = StatusFormatter.get_status_emoji(status)

                # Get git stats if available
                branch, added, deleted, changed_files = await self._get_git_stats(current_path)

                # Format compact status
                status_text = StatusFormatter.format_compact_status(
                    status_emoji=status_emoji,
                    branch=branch,
                    added_lines=added,
                    deleted_lines=deleted,
                    current_path=current_path,
                    approved_directory=settings.approved_directory,
                    changed_files=changed_files,
                )
                
                logger.info(f"Formatted status: '{status_text[:100]}...' (branch={branch}, +{added}/-{deleted}, {len(changed_files) if changed_files else 0} files, path={current_path})")


                # Get state
                if "topic_states" not in context.chat_data:
                    context.chat_data["topic_states"] = {}
                if context_key not in context.chat_data["topic_states"]:
                    context.chat_data["topic_states"][context_key] = {}

                state = context.chat_data["topic_states"][context_key]
                pinned_msg_id = state.get("pinned_message_id")

                # Try to update existing pinned message
                if pinned_msg_id:
                    try:
                        # Try to edit existing message directly
                        await context.bot.edit_message_text(
                            chat_id=chat.id,
                            message_id=pinned_msg_id,
                            text=status_text
                        )
                        logger.debug(f"Updated pinned status: {status_text}")
                        return None  # We don't have the message object, but update succeeded
                    except TelegramError as e:
                        logger.debug(f"Failed to update pinned message: {e}")
                        # Message was deleted or error, create new one
                        pinned_msg_id = None

                # Create new pinned message
                msg = await chat.send_message(status_text)

                # Pin the message (silently, without notification)
                try:
                    await msg.pin(disable_notification=True)
                    state["pinned_message_id"] = msg.message_id
                    logger.info(f"Created and pinned status message: {status_text}")
                    return msg
                except TelegramError as e:
                    logger.warning(f"Failed to pin message: {e}")
                    # Keep the message ID anyway, we can update it
                    state["pinned_message_id"] = msg.message_id
                    return msg

            except Exception as e:
                logger.error(f"Error updating pinned status: {e}")
                return None

    async def _get_git_stats(
        self, repo_path: Path
    ) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[list]]:
        """Get git branch and diff statistics.

        Args:
            repo_path: Path to check for git repository

        Returns:
            Tuple of (branch_name, added_lines, deleted_lines, changed_files_list)
        """
        logger.info(f"Checking git stats for path: {repo_path}")
        
        if not self.git_integration:
            logger.info("No git integration available")
            return None, None, None, None

        try:
            # Just try to get git status - git itself will determine if we're in a repo
            # This works from any subdirectory of a git repository
            status = await self.git_integration.get_status(repo_path)
            branch = status.branch
            logger.info(f"Git branch: {branch}")

            # Get diff stats
            added, deleted, _ = await self.git_integration.get_diff_stats(repo_path)
            logger.info(f"Git diff stats: +{added}/-{deleted}")
            
            # Get list of changed files
            changed_files = await self.git_integration.get_changed_files(repo_path)
            logger.info(f"Changed files: {len(changed_files)} files")

            return branch, added, deleted, changed_files

        except GitError as e:
            # Not a git repo or git command failed
            logger.debug(f"Git error getting stats (probably not a git repo): {e}")
            return None, None, None, None
        except Exception as e:
            logger.warning(f"Unexpected error getting git stats: {e}")
            return None, None, None, None
