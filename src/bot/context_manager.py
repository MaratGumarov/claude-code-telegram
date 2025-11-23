"""Context manager for handling Telegram Topics (threads) state.

This module provides helpers to manage session state (current directory, session ID)
scoped to the specific chat thread (topic) rather than just the user.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from telegram import Update
from telegram.ext import ContextTypes

from ..config.settings import Settings


class ContextManager:
    """Manages bot context and state across topics."""

    @staticmethod
    def get_context_key(update: Update) -> str:
        """Get unique key for the current context (chat_id + thread_id)."""
        chat_id = update.effective_chat.id
        thread_id = update.effective_message.message_thread_id if update.effective_message else None
        
        if thread_id:
            return f"{chat_id}:{thread_id}"
        return str(chat_id)

    @staticmethod
    def get_state(context: ContextTypes.DEFAULT_TYPE, key: str) -> Dict[str, Any]:
        """Get state dictionary for the given key from chat_data."""
        if "topic_states" not in context.chat_data:
            context.chat_data["topic_states"] = {}
        
        if key not in context.chat_data["topic_states"]:
            context.chat_data["topic_states"][key] = {}
            
        return context.chat_data["topic_states"][key]

    @classmethod
    def get_current_directory(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE, settings: Settings
    ) -> Path:
        """Get current working directory for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        return state.get("current_directory", settings.approved_directory)

    @classmethod
    def set_current_directory(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE, path: Path
    ) -> None:
        """Set current working directory for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        state["current_directory"] = path

    @classmethod
    def get_session_id(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> Optional[str]:
        """Get Claude session ID for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        return state.get("claude_session_id")

    @classmethod
    def set_session_id(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: Optional[str]
    ) -> None:
        """Set Claude session ID for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        state["claude_session_id"] = session_id

    @classmethod
    def get_session_started(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Check if session is started for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        return state.get("session_started", False)

    @classmethod
    def set_session_started(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE, started: bool
    ) -> None:
        """Set session started status for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        state["session_started"] = started

    @classmethod
    def get_pinned_message_id(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> Optional[int]:
        """Get pinned status message ID for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        return state.get("pinned_message_id")

    @classmethod
    def set_pinned_message_id(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE, message_id: Optional[int]
    ) -> None:
        """Set pinned status message ID for the current topic."""
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        state["pinned_message_id"] = message_id

    @classmethod
    def get_current_status(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> str:
        """Get current processing status for the current topic.
        
        Returns:
            One of: "ready", "processing", "error"
        """
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        return state.get("current_status", "ready")

    @classmethod
    def set_current_status(
        cls, update: Update, context: ContextTypes.DEFAULT_TYPE, status: str
    ) -> None:
        """Set current processing status for the current topic.
        
        Args:
            status: One of "ready", "processing", "error"
        """
        key = cls.get_context_key(update)
        state = cls.get_state(context, key)
        state["current_status"] = status

