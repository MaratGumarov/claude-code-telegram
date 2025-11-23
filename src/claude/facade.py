"""High-level Claude Code integration facade.

Provides simple interface for bot handlers.
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import structlog

from ..config.settings import Settings
from .agent import ClaudeAgentClient
from .exceptions import ClaudeToolValidationError
from .monitor import ToolMonitor
from .session import SessionManager
from .types import ClaudeResponse, StreamUpdate

logger = structlog.get_logger()


class ClaudeIntegration:
    """Main integration point for Claude Code."""

    def __init__(
        self,
        config: Settings,
        session_manager: Optional[SessionManager] = None,
        tool_monitor: Optional[ToolMonitor] = None,
    ):
        """Initialize Claude integration facade."""
        self.config = config
        self.client = ClaudeAgentClient(config)
        self.session_manager = session_manager
        self.tool_monitor = tool_monitor

    async def run_command(
        self,
        prompt: str,
        working_directory: Path,
        user_id: int,
        session_id: Optional[str] = None,
        on_stream: Optional[Callable[[StreamUpdate], None]] = None,
    ) -> ClaudeResponse:
        """Run Claude Code command with full integration."""
        logger.info(
            "Running Claude command",
            user_id=user_id,
            working_directory=str(working_directory),
            session_id=session_id,
            prompt_length=len(prompt),
        )

        # Get or create session
        session = await self.session_manager.get_or_create_session(
            user_id, working_directory, session_id
        )

        # Track streaming updates and validate tool calls
        tools_validated = True
        validation_errors = []
        blocked_tools = set()
        
        # Accumulate response data
        full_content = []
        tools_used = []
        start_time = 0 # TODO: Track time
        
        async def stream_handler(update: StreamUpdate):
            nonlocal tools_validated
            
            # Accumulate content
            if update.content:
                if update.type == "assistant":
                    full_content.append(update.content)
                elif update.type == "error":
                    full_content.append(f"Error: {update.content}")
                    # We'll set is_error=True in the final response construction if we see an error

            # Validate tool calls
            if update.tool_calls and update.type == "assistant":
                for tool_call in update.tool_calls:
                    tool_name = tool_call["name"]
                    tools_used.append(tool_call)
                    
                    valid, error = await self.tool_monitor.validate_tool_call(
                        tool_name,
                        tool_call.get("input", {}),
                        working_directory,
                        user_id,
                    )

                    if not valid:
                        tools_validated = False
                        validation_errors.append(error)

                        # Track blocked tools
                        if "Tool not allowed:" in error:
                            blocked_tools.add(tool_name)

                        logger.error(
                            "Tool validation failed",
                            tool_name=tool_name,
                            error=error,
                            user_id=user_id,
                        )

                        # For critical tools, we should fail fast
                        if tool_name in ["Task", "Read", "Write", "Edit"]:
                            # Create comprehensive error message
                            if blocked_tools:
                                admin_instructions = self._get_admin_instructions(
                                    list(blocked_tools)
                                )
                                error_msg = self._create_tool_error_message(
                                    list(blocked_tools),
                                    self.config.claude_allowed_tools or [],
                                    admin_instructions,
                                )
                            else:
                                # Generic validation error (e.g. path traversal)
                                error_msg = (
                                    f"🚫 **Tool Validation Failed**\n\n"
                                    f"Operation blocked by security policy.\n\n"
                                    f"**Reason:** {error}\n\n"
                                    f"**Details:**\n"
                                    f"• Tool: `{tool_name}`\n"
                                    f"• Action: Blocked for security\n"
                                )

                            raise ClaudeToolValidationError(
                                error_msg,
                                blocked_tools=list(blocked_tools),
                                allowed_tools=self.config.claude_allowed_tools or [],
                            )

            # Pass to caller's handler
            if on_stream:
                try:
                    await on_stream(update)
                except Exception as e:
                    logger.warning("Stream callback failed", error=str(e))

        # Execute command
        try:
            # Only continue session if it's not a new session
            # should_continue = bool(session_id) and not getattr(
            #     session, "is_new_session", False
            # )
            
            # Execute via agent client
            async for update in self.client.stream_message(
                message=prompt,
                session_id=session.session_id,
                working_directory=working_directory,
            ):
                await stream_handler(update)

            # Construct response
            response = ClaudeResponse(
                content="".join(full_content),
                session_id=session.session_id,
                cost=0.0, # SDK might not provide cost yet
                duration_ms=0, # TODO: Calculate duration
                num_turns=1,
                is_error=not tools_validated or any(line.startswith("Error:") for line in full_content),
                tools_used=tools_used,
            )

            # Check if tool validation failed
            if not tools_validated:
                logger.error(
                    "Command completed but tool validation failed",
                    validation_errors=validation_errors,
                )
                # Mark response as having errors and include validation details
                response.is_error = True
                response.error_type = "tool_validation_failed"

                # Extract blocked tool names for user feedback
                blocked_tools = []
                for error in validation_errors:
                    if "Tool not allowed:" in error:
                        tool_name = error.split("Tool not allowed: ")[1]
                        blocked_tools.append(tool_name)

                # Create user-friendly error message
                if blocked_tools:
                    tool_list = ", ".join(f"`{tool}`" for tool in blocked_tools)
                    response.content = (
                        f"🚫 **Tool Access Blocked**\n\n"
                        f"Claude tried to use tools not allowed:\n"
                        f"{tool_list}\n\n"
                        f"**What you can do:**\n"
                        f"• Contact the administrator to request access to these tools\n"
                        f"• Try rephrasing your request to use different approaches\n"
                        f"• Check what tools are currently available with `/status`\n\n"
                        f"**Currently allowed tools:**\n"
                        f"{', '.join(f'`{t}`' for t in self.config.claude_allowed_tools or [])}"
                    )
                else:
                    response.content = (
                        f"🚫 **Tool Validation Failed**\n\n"
                        f"Tools failed security validation. Try different approach.\n\n"
                        f"Details: {'; '.join(validation_errors)}"
                    )

            # Update session
            await self.session_manager.update_session(session.session_id, response)

            logger.info(
                "Claude command completed",
                session_id=response.session_id,
                is_error=response.is_error,
            )

            return response

        except Exception as e:
            logger.error(
                "Claude command failed",
                error=str(e),
                user_id=user_id,
                session_id=session.session_id,
            )
            raise

    async def continue_session(
        self,
        user_id: int,
        working_directory: Path,
        prompt: Optional[str] = None,
        on_stream: Optional[Callable[[StreamUpdate], None]] = None,
    ) -> Optional[ClaudeResponse]:
        """Continue the most recent session."""
        logger.info(
            "Continuing session",
            user_id=user_id,
            working_directory=str(working_directory),
            has_prompt=bool(prompt),
        )

        # Get user's sessions
        sessions = await self.session_manager._get_user_sessions(user_id)

        # Find most recent session in this directory (exclude temporary sessions)
        matching_sessions = [
            s
            for s in sessions
            if s.project_path == working_directory
            and not s.session_id.startswith("temp_")
        ]

        if not matching_sessions:
            logger.info("No matching sessions found", user_id=user_id)
            return None

        # Get most recent
        latest_session = max(matching_sessions, key=lambda s: s.last_used)

        # Continue session
        return await self.run_command(
            prompt=prompt or "",
            working_directory=working_directory,
            user_id=user_id,
            session_id=latest_session.session_id,
            on_stream=on_stream,
        )

    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session information."""
        return await self.session_manager.get_session_info(session_id)

    async def get_user_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        sessions = await self.session_manager._get_user_sessions(user_id)
        return [
            {
                "session_id": s.session_id,
                "project_path": str(s.project_path),
                "created_at": s.created_at.isoformat(),
                "last_used": s.last_used.isoformat(),
                "total_cost": s.total_cost,
                "message_count": s.message_count,
                "tools_used": s.tools_used,
                "expired": s.is_expired(self.config.session_timeout_hours),
            }
            for s in sessions
        ]

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions."""
        return await self.session_manager.cleanup_expired_sessions()

    async def get_tool_stats(self) -> Dict[str, Any]:
        """Get tool usage statistics."""
        return self.tool_monitor.get_tool_stats()

    async def get_user_summary(self, user_id: int) -> Dict[str, Any]:
        """Get comprehensive user summary."""
        session_summary = await self.session_manager.get_user_session_summary(user_id)
        tool_usage = self.tool_monitor.get_user_tool_usage(user_id)

        return {
            "user_id": user_id,
            **session_summary,
            **tool_usage,
        }

    async def shutdown(self) -> None:
        """Shutdown integration and cleanup resources."""
        logger.info("Shutting down Claude integration")
        # No specific cleanup needed for SDK client yet
        
        # Clean up expired sessions
        await self.cleanup_expired_sessions()

        logger.info("Claude integration shutdown complete")

    def _get_admin_instructions(self, blocked_tools: List[str]) -> str:
        """Generate admin instructions for enabling blocked tools."""
        instructions = []

        # Check if settings file exists
        settings_file = Path(".env")

        if blocked_tools:
            # Get current allowed tools and create merged list without duplicates
            current_tools = [
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Glob",
                "Grep",
                "LS",
                "Task",
                "MultiEdit",
                "NotebookRead",
                "NotebookEdit",
                "WebFetch",
                "TodoRead",
                "TodoWrite",
                "WebSearch",
            ]
            merged_tools = list(
                dict.fromkeys(current_tools + blocked_tools)
            )  # Remove duplicates while preserving order
            merged_tools_str = ",".join(merged_tools)
            merged_tools_py = ", ".join(f'"{tool}"' for tool in merged_tools)

            instructions.append("**For Administrators:**")
            instructions.append("")

            if settings_file.exists():
                instructions.append(
                    "To enable these tools, add them to your `.env` file:"
                )
                instructions.append("```")
                instructions.append(f'CLAUDE_ALLOWED_TOOLS="{merged_tools_str}"')
                instructions.append("```")
            else:
                instructions.append("To enable these tools:")
                instructions.append("1. Create a `.env` file in your project root")
                instructions.append("2. Add the following line:")
                instructions.append("```")
                instructions.append(f'CLAUDE_ALLOWED_TOOLS="{merged_tools_str}"')
                instructions.append("```")

            instructions.append("")
            instructions.append("Or modify the default in `src/config/settings.py`:")
            instructions.append("```python")
            instructions.append("claude_allowed_tools: Optional[List[str]] = Field(")
            instructions.append(f"    default=[{merged_tools_py}],")
            instructions.append('    description="List of allowed Claude tools",')
            instructions.append(")")
            instructions.append("```")

        return "\n".join(instructions)

    def _create_tool_error_message(
        self,
        blocked_tools: List[str],
        allowed_tools: List[str],
        admin_instructions: str,
    ) -> str:
        """Create a comprehensive error message for tool validation failures."""
        tool_list = ", ".join(f"`{tool}`" for tool in blocked_tools)
        allowed_list = (
            ", ".join(f"`{tool}`" for tool in allowed_tools)
            if allowed_tools
            else "None"
        )

        message = [
            "🚫 **Tool Access Blocked**",
            "",
            f"Claude tried to use tools that are not currently allowed:",
            f"{tool_list}",
            "",
            "**Why this happened:**",
            "• Claude needs these tools to complete your request",
            "• These tools are not in the allowed tools list",
            "• This is a security feature to control what Claude can do",
            "",
            "**What you can do:**",
            "• Contact the administrator to request access to these tools",
            "• Try rephrasing your request to use different approaches",
            "• Use simpler requests that don't require these tools",
            "",
            "**Currently allowed tools:**",
            f"{allowed_list}",
            "",
            admin_instructions,
        ]

        return "\n".join(message)
