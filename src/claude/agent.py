"""Claude Agent SDK integration.

Wraps the official claude-agent-sdk to provide a compatible interface for the bot.
"""

import asyncio
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Union

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from ..config.settings import Settings
from .types import ClaudeResponse, StreamUpdate

logger = structlog.get_logger()


class ClaudeAgentClient:
    """Client for interacting with Claude Code via the official SDK."""

    def __init__(self, settings: Settings):
        """Initialize Claude Agent client."""
        self.settings = settings
        # Store state per session to handle history replay
        # Map session_id -> {"total_blocks_seen": int, "current_text_content": str}
        self.session_states: Dict[str, Dict[str, Any]] = {}

    async def stream_message(
        self,
        message: str,
        session_id: str,
        working_directory: Path,
        restart: bool = False,
    ) -> AsyncIterator[StreamUpdate]:
        """Stream a message to Claude and yield updates.

        Args:
            message: The message to send
            session_id: The session ID (used for context isolation)
            working_directory: The current working directory
            restart: Whether to restart the session

        Yields:
            StreamUpdate objects
        """
        # Configure options
        options_dict = {
            "cwd": working_directory,
            "allowed_tools": self.settings.claude_allowed_tools,
        }
        
        # Use custom CLI path if configured
        if self.settings.claude_cli_path:
            options_dict["cli_path"] = self.settings.claude_cli_path
            logger.info("Using custom Claude CLI", path=self.settings.claude_cli_path)
        
        options = ClaudeAgentOptions(**options_dict)

        # Initialize client
        try:
            async with ClaudeSDKClient(options=options) as client:
                # Send the query
                await client.query(message)
                
                # Yield initial progress
                yield StreamUpdate(
                    type="progress",
                    content="Starting Claude Agent...",
                    progress={"percentage": 0},
                )

                # Get or initialize state for this session
                if session_id not in self.session_states:
                    self.session_states[session_id] = {
                        "total_blocks_seen": 0,
                        "current_text_content": ""
                    }
                
                state = self.session_states[session_id]
                current_block_index = 0  # Track global block index across all messages

                async for msg in client.receive_messages():
                    msg_type = type(msg).__name__
                    logger.info(
                        "Received SDK message", 
                        type=msg_type, 
                    )
                    
                    if isinstance(msg, AssistantMessage):
                        # Process each block
                        for block in msg.content:
                            # Skip blocks we've already processed
                            if current_block_index < state["total_blocks_seen"]:
                                current_block_index += 1
                                continue
                            
                            if isinstance(block, TextBlock):
                                # Calculate delta from last text state
                                delta = block.text[len(state["current_text_content"]):]
                                if delta:
                                    yield StreamUpdate(
                                        type="assistant",
                                        content=delta,
                                    )
                                    state["current_text_content"] = block.text
                                
                                # Mark as processed only if it's complete (not the last block being streamed)
                                # We check if there are more blocks or if this is final
                                current_block_index += 1
                                    
                            elif isinstance(block, ToolUseBlock):
                                # Yield tool call
                                yield StreamUpdate(
                                    type="assistant",
                                    tool_calls=[{
                                        "name": block.name,
                                        "input": block.input,
                                        "id": block.id,
                                    }],
                                )
                                
                                # Mark tool block as processed
                                current_block_index += 1
                                state["total_blocks_seen"] = current_block_index
                                state["current_text_content"] = ""  # Reset text state after tool

                    elif isinstance(msg, UserMessage):
                        # Handle tool results
                        tool_results = []
                        for block in msg.content:
                            if isinstance(block, ToolResultBlock):
                                tool_results.append({
                                    "tool_use_id": block.tool_use_id,
                                    "is_error": block.is_error,
                                })
                        
                        if tool_results:
                            yield StreamUpdate(
                                type="tool_result",
                                tool_calls=tool_results,
                            )

                    elif isinstance(msg, ResultMessage):
                        # Update state to mark all blocks as seen
                        state["total_blocks_seen"] = current_block_index
                        
                        if msg.is_error:
                            yield StreamUpdate(
                                type="error",
                                content=str(msg.result),
                                error_info={"message": str(msg.result)},
                            )
                        else:
                            yield StreamUpdate(
                                type="result",
                                content="Task completed",
                                progress={"percentage": 100},
                            )
                        break

        except Exception as e:
            logger.error("Claude Agent error", error=str(e))
            yield StreamUpdate(
                type="error",
                content=str(e),
                error_info={"message": str(e)},
            )

    def _convert_message_to_update(
        self,
        message: Union[AssistantMessage, UserMessage, SystemMessage, ResultMessage],
    ) -> Optional[StreamUpdate]:
        """Deprecated: Logic moved to stream_message for stateful processing."""
        return None
            

