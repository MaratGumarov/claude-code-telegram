"""Type definitions for Claude integration."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ClaudeResponse:
    """Response from Claude Code."""

    content: str
    session_id: str
    cost: float
    duration_ms: int
    num_turns: int
    is_error: bool = False
    error_type: Optional[str] = None
    tools_used: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class StreamUpdate:
    """Enhanced streaming update from Claude with richer context."""

    type: str  # 'assistant', 'user', 'system', 'result', 'tool_result', 'error', 'progress'
    content: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    metadata: Optional[Dict] = None

    # Enhanced fields for better tracking
    timestamp: Optional[str] = None
    session_context: Optional[Dict] = None
    progress: Optional[Dict] = None
    error_info: Optional[Dict] = None

    # Execution tracking
    execution_id: Optional[str] = None
    parent_message_id: Optional[str] = None

    def is_error(self) -> bool:
        """Check if this update represents an error."""
        return self.type == "error" or (
            self.metadata and self.metadata.get("is_error", False)
        )

    def get_tool_names(self) -> List[str]:
        """Extract tool names from tool calls."""
        if not self.tool_calls:
            return []
        return [call.get("name") for call in self.tool_calls if call.get("name")]

    def get_progress_percentage(self) -> Optional[int]:
        """Get progress percentage if available."""
        if self.progress:
            return self.progress.get("percentage")
        return None

    def get_error_message(self) -> Optional[str]:
        """Get error message if this is an error update."""
        if self.error_info:
            return self.error_info.get("message")
        elif self.is_error() and self.content:
            return self.content
        return None
