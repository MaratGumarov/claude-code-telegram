"""Message handlers for non-command inputs."""

import asyncio
from typing import Optional

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...claude.exceptions import ClaudeToolValidationError
from ...claude import ClaudeIntegration
from ...claude.types import StreamUpdate
from ...config.settings import Settings
from ...security.audit import AuditLogger
from ...security.rate_limiter import RateLimiter
from ...security.validators import SecurityValidator
from ..context_manager import ContextManager

logger = structlog.get_logger()


async def _format_progress_update(update_obj) -> Optional[str]:
    """Format progress updates with enhanced context and visual indicators."""
    if update_obj.type == "tool_result":
        # Show tool completion status
        tool_name = "Unknown"
        if update_obj.metadata and update_obj.metadata.get("tool_use_id"):
            # Try to extract tool name from context if available
            tool_name = update_obj.metadata.get("tool_name", "Tool")

        if update_obj.is_error():
            return f"❌ **{tool_name} failed**\n\n_{update_obj.get_error_message()}_"
        else:
            execution_time = ""
            if update_obj.metadata and update_obj.metadata.get("execution_time_ms"):
                time_ms = update_obj.metadata["execution_time_ms"]
                execution_time = f" ({time_ms}ms)"
            return f"✅ **{tool_name} completed**{execution_time}"

    elif update_obj.type == "progress":
        # Handle progress updates
        progress_text = f"🔄 **{update_obj.content or 'Working...'}**"

        percentage = update_obj.get_progress_percentage()
        if percentage is not None:
            # Create a simple progress bar
            filled = int(percentage / 10)  # 0-10 scale
            bar = "█" * filled + "░" * (10 - filled)
            progress_text += f"\n\n`{bar}` {percentage}%"

        if update_obj.progress:
            step = update_obj.progress.get("step")
            total_steps = update_obj.progress.get("total_steps")
            if step and total_steps:
                progress_text += f"\n\nStep {step} of {total_steps}"

        return progress_text

    elif update_obj.type == "error":
        # Handle error messages
        return f"❌ **Error**\n\n_{update_obj.get_error_message()}_"

    elif update_obj.type == "assistant" and update_obj.tool_calls:
        # Show when tools are being called
        tool_names = update_obj.get_tool_names()
        if tool_names:
            tools_text = ", ".join(tool_names)
            return f"🔧 **Using tools:** {tools_text}"

    elif update_obj.type == "assistant" and update_obj.content:
        # Regular content updates with preview
        content_preview = (
            update_obj.content[:150] + "..."
            if len(update_obj.content) > 150
            else update_obj.content
        )
        return f"🤖 **Claude is working...**\n\n_{content_preview}_"

    elif update_obj.type == "system":
        # System initialization or other system messages
        if update_obj.metadata and update_obj.metadata.get("subtype") == "init":
            tools_count = len(update_obj.metadata.get("tools", []))
            model = update_obj.metadata.get("model", "Claude")
            return f"🚀 **Starting {model}** with {tools_count} tools available"

    return None


def _format_error_message(error_str: str) -> str:
    """Format error messages for user-friendly display."""
    if "usage limit reached" in error_str.lower():
        # Usage limit error - already user-friendly from integration.py
        return error_str
    elif "tool not allowed" in error_str.lower():
        # Tool validation error - already handled in facade.py
        return error_str
    elif "no conversation found" in error_str.lower():
        return (
            f"🔄 **Session Not Found**\n\n"
            f"The Claude session could not be found or has expired.\n\n"
            f"**What you can do:**\n"
            f"• Use `/new` to start a fresh session\n"
            f"• Try your request again\n"
            f"• Use `/status` to check your current session"
        )
    elif "rate limit" in error_str.lower():
        return (
            f"⏱️ **Rate Limit Reached**\n\n"
            f"Too many requests in a short time period.\n\n"
            f"**What you can do:**\n"
            f"• Wait a moment before trying again\n"
            f"• Use simpler requests\n"
            f"• Check your current usage with `/status`"
        )
    elif "timeout" in error_str.lower():
        return (
            f"⏰ **Request Timeout**\n\n"
            f"Your request took too long to process and timed out.\n\n"
            f"**What you can do:**\n"
            f"• Try breaking down your request into smaller parts\n"
            f"• Use simpler commands\n"
            f"• Try again in a moment"
        )
    else:
        # Generic error handling
        return (
            f"❌ **Claude Code Error**\n\n"
            f"Failed to process your request: {error_str}\n\n"
            f"Please try again or contact the administrator if the problem persists."
        )


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle regular text messages as Claude prompts."""
    user_id = update.effective_user.id
    message_text = update.message.text
    settings: Settings = context.bot_data["settings"]

    # Get services
    rate_limiter: Optional[RateLimiter] = context.bot_data.get("rate_limiter")
    audit_logger: Optional[AuditLogger] = context.bot_data.get("audit_logger")

    logger.info(
        "Processing text message", user_id=user_id, message_length=len(message_text)
    )

    try:
        # Check rate limit with estimated cost for text processing
        estimated_cost = _estimate_text_processing_cost(message_text)

        if rate_limiter:
            allowed, limit_message = await rate_limiter.check_rate_limit(
                user_id, estimated_cost
            )
            if not allowed:
                await update.message.reply_text(f"⏱️ {limit_message}")
                return

        # Send typing action to indicate bot is working
        await update.message.chat.send_action("typing")

        # Get Claude integration and storage from context
        claude_integration = context.bot_data.get("claude_integration")
        storage = context.bot_data.get("storage")

        if not claude_integration:
            await update.message.reply_text(
                "❌ **Claude integration not available**\n\n"
                "The Claude Code integration is not properly configured. "
                "Please contact the administrator.",
                parse_mode="Markdown",
            )
            return

        # Get current directory
        current_dir = ContextManager.get_current_directory(update, context, settings)

        # Get existing session ID
        session_id = ContextManager.get_session_id(update, context)

        # Enhanced stream updates handler with progress tracking and text streaming
        import time
        
        # Stream handler for real-time updates
        stream_state = {
            "last_update_time": 0,
            "current_message": None,
            "last_typing_time": 0,
            "events": [],  # Chronological list of {type: "tool"|"text", ...}
            "update_lock": asyncio.Lock(),
        }

        async def stream_handler(update_obj: StreamUpdate):
            nonlocal stream_state
            try:
                current_time = asyncio.get_event_loop().time()
                
                # Log all events for debugging
                logger.debug("Stream event", type=update_obj.type, has_content=bool(update_obj.content), has_tools=bool(update_obj.tool_calls))
                
                # Handle different update types
                if update_obj.type == "assistant" and update_obj.tool_calls:
                    # Tool call - add to events with input data
                    for tool_call in update_obj.tool_calls:
                        logger.info("Tool call received", name=tool_call.get("name"), input=tool_call.get("input"))
                        stream_state["events"].append({
                            "type": "tool",
                            "name": tool_call.get("name"),
                            "input": tool_call.get("input", {}),
                            "id": tool_call.get("id"),
                            "status": "running"
                        })
                    
                    await _update_stream_message()
                
                elif update_obj.type == "tool_result" and update_obj.tool_calls:
                    # Tool finished - update status
                    for result in update_obj.tool_calls:
                        tool_id = result.get("tool_use_id")
                        for event in stream_state["events"]:
                            if event["type"] == "tool" and event.get("id") == tool_id:
                                event["status"] = "done"
                                break
                    
                    await _update_stream_message()

                elif update_obj.type == "result":
                    # Mark ALL running tools as complete (SDK sends one result after all tools finish)
                    # This is a fallback in case we missed individual updates
                    for event in stream_state["events"]:
                        if event["type"] == "tool" and event["status"] == "running":
                            event["status"] = "done"
                    
                    await _update_stream_message()
                        
                elif update_obj.type == "assistant" and update_obj.content:
                    # Text content - append to last text event or create new one
                    new_content = update_obj.content
                    
                    # Text update - merge with previous if it was text
                    if stream_state["events"] and stream_state["events"][-1]["type"] == "text":
                        stream_state["events"][-1]["content"] += update_obj.content
                    else:
                        stream_state["events"].append({
                            "type": "text",
                            "content": update_obj.content
                        })
                    
                    # Throttling for text updates (0.5s or 50+ chars)
                    if (current_time - stream_state["last_update_time"] >= 0.5) or len(update_obj.content) > 50:
                        await _update_stream_message()
                        stream_state["last_update_time"] = current_time
                            
            except Exception as e:
                logger.warning("Failed to update stream", error=str(e), error_type=type(e).__name__)
                # If it's a Markdown parsing error, try to send without parse_mode
                if "Can't parse entities" in str(e):
                    logger.info("Detected Markdown parsing error, retrying without parse_mode")
                    try:
                        # Use the last known accumulated text for retry
                        content_for_retry = stream_state["accumulated_text"]
                        if not stream_state.get("current_message"):
                            logger.info("Creating new message without parse_mode")
                            stream_state["current_message"] = await update.message.reply_text(
                                content_for_retry,
                                parse_mode=None,
                            )
                        else:
                            logger.info("Editing existing message without parse_mode", content_preview=content_for_retry[:100])
                            await stream_state["current_message"].edit_text(
                                content_for_retry,
                                parse_mode=None,
                            )
                        logger.info("Successfully sent message without parse_mode")
                    except Exception as retry_error:
                        logger.error("Failed to update stream even without parse_mode", error=str(retry_error))
        
        # Initialize stream state
        stream_state = {
            "accumulated_text": "",
            "events": [],  # List of {type: "tool"|"text", ...}
            "messages": [], # List of message objects
            "message_contents": [], # List of content strings corresponding to messages
            "update_lock": asyncio.Lock(),
            "update_pending": False
        }
        
        # Tool icons mapping
        TOOL_ICONS = {
            "Bash": "💻",
            "Read": "📄", 
            "ReadFile": "📄",
            "Write": "✏️",
            "WriteFile": "✏️", 
            "Edit": "📝",
            "EditFile": "📝",
            "Glob": "🔍",
            "LS": "📂",
            "ls": "📂",
        }

        async def _update_stream_message():
            """Helper to update the stream message with current events in chronological order."""
            nonlocal stream_state
            
            # Acquire lock to prevent concurrent updates
            async with stream_state["update_lock"]:
                if not stream_state["events"]:
                    return  # Nothing to show yet
                
                # Build message from events in chronological order
                message_parts = []
                tool_counter = 0
                has_separator = False
                
                for event in stream_state["events"]:
                    if event["type"] == "tool":
                        tool_counter += 1
                        status_icon = "⏳" if event["status"] == "running" else "✓"
                        
                        # Format tool with icon and details
                        tool_name = event["name"]
                        tool_input = event.get("input", {})
                        type_icon = TOOL_ICONS.get(tool_name, "🔧")
                        
                        details = ""
                        if tool_name == "Bash" and "command" in tool_input:
                            cmd = tool_input["command"].strip()
                            if len(cmd) > 40:
                                cmd = cmd[:37] + "..."
                            details = f": `{cmd}`"
                        elif tool_name in ["Read", "ReadFile", "Write", "WriteFile", "Edit", "EditFile"]:
                            # Try different keys for path
                            path = tool_input.get("path") or tool_input.get("file_path") or tool_input.get("file")
                            if not path and "paths" in tool_input:
                                paths = tool_input["paths"]
                                if isinstance(paths, list) and paths:
                                    path = paths[0] + (f" (+{len(paths)-1})" if len(paths) > 1 else "")
                            
                            if path:
                                details = f": `{path}`"
                            else:
                                # Debug: show keys if no path found
                                logger.warning("No path found in tool input", tool=tool_name, keys=list(tool_input.keys()))
                                
                        elif tool_name in ["Glob"]:
                            pattern = tool_input.get("pattern") or tool_input.get("include")
                            if pattern:
                                details = f": `{pattern}`"
                            
                        message_parts.append(f"{tool_counter}. {status_icon} {type_icon} **{tool_name}**{details}")
                        has_separator = False
                    elif event["type"] == "text":
                        # Add separator before text if there were tools before and no separator yet
                        if tool_counter > 0 and not has_separator:
                            message_parts.append("\n---\n")
                            has_separator = True
                        message_parts.append(event["content"])
                
                combined_text = "\n".join(message_parts)
                
                if not combined_text.strip():
                    return

                # Split text into chunks (Telegram limit is 4096, use 4000 for safety)
                CHUNK_SIZE = 4000
                chunks = [combined_text[i:i+CHUNK_SIZE] for i in range(0, len(combined_text), CHUNK_SIZE)]
                
                # Update or send messages for each chunk
                for i, chunk in enumerate(chunks):
                    # Check if we have a message for this chunk
                    if i < len(stream_state["messages"]):
                        # Only edit if content changed
                        if i < len(stream_state["message_contents"]) and stream_state["message_contents"][i] == chunk:
                            continue
                            
                        try:
                            await stream_state["messages"][i].edit_text(
                                chunk,
                                parse_mode="Markdown",
                            )
                            # Update stored content
                            if i < len(stream_state["message_contents"]):
                                stream_state["message_contents"][i] = chunk
                            else:
                                stream_state["message_contents"].append(chunk)
                        except Exception:
                            pass  # Ignore if same content or other error
                    else:
                        # Send new message
                        msg = await update.message.reply_text(
                            chunk,
                            parse_mode="Markdown",
                        )
                        stream_state["messages"].append(msg)
                        stream_state["message_contents"].append(chunk)


        # Background task to keep typing status active
        async def keep_typing():
            try:
                while True:
                    await update.message.chat.send_action("typing")
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Typing task failed", error=str(e))

        typing_task = asyncio.create_task(keep_typing())

        # Run Claude command
        try:
            claude_response = await claude_integration.run_command(
                prompt=message_text,
                working_directory=current_dir,
                user_id=user_id,
                session_id=session_id,
                on_stream=stream_handler,
            )

            # Update session ID
            ContextManager.set_session_id(update, context, claude_response.session_id)

            # Check if Claude changed the working directory and update our tracking
            _update_working_directory_from_claude_response(
                claude_response, update, context, settings, user_id
            )

            # Log interaction to storage
            if storage:
                try:
                    await storage.save_claude_interaction(
                        user_id=user_id,
                        session_id=claude_response.session_id,
                        prompt=message_text,
                        response=claude_response,
                        ip_address=None,  # Telegram doesn't provide IP
                    )
                except Exception as e:
                    logger.warning("Failed to log interaction to storage", error=str(e))

        except ClaudeToolValidationError as e:
            # Tool validation error with detailed instructions
            logger.error(
                "Tool validation error",
                error=str(e),
                user_id=user_id,
                blocked_tools=e.blocked_tools,
            )
            # Error message already formatted, create FormattedMessage
            from ..utils.formatting import FormattedMessage
            formatted_messages = [FormattedMessage(str(e), parse_mode="Markdown")]
            
        except Exception as e:
            # Generic error
            logger.error("Error running Claude command", error=str(e), user_id=user_id)
            from ..utils.formatting import FormattedMessage
            
            formatted_messages = [
                FormattedMessage(
                    f"❌ **Error**\n\nAn unexpected error occurred: {str(e)}",
                    parse_mode="Markdown"
                )
            ]

        finally:
            # Stop typing task
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

            # Format response if not already formatted (success case)
            if 'formatted_messages' not in locals():
                if 'claude_response' in locals():
                    from ..utils.formatting import ResponseFormatter
                    formatter = ResponseFormatter(settings)
                    formatted_messages = formatter.format_claude_response(
                        claude_response.content
                    )
                else:
                    # Fallback if claude_response is not defined (should be handled by except blocks, but just in case)
                    from ..utils.formatting import FormattedMessage
                    formatted_messages = [
                        FormattedMessage(
                            "❌ **Error**\n\nFailed to get response from Claude.",
                            parse_mode="Markdown"
                        )
                    ]

        # Send formatted responses (may be multiple messages)
        # Only send if it's an error message or if we didn't stream anything
        should_send = False
        if 'formatted_messages' in locals():
            # Check if it's an error message
            if any(icon in msg.text for msg in formatted_messages for icon in ["❌", "🚫"]):
                should_send = True
            # Or if we didn't stream any messages (no messages were sent via streaming)
            elif not stream_state.get("messages"):
                should_send = True

        if should_send:
            for i, message in enumerate(formatted_messages):
                try:
                    try:
                        await update.message.reply_text(
                            message.text,
                            parse_mode=message.parse_mode,
                            reply_markup=message.reply_markup,
                            reply_to_message_id=update.message.message_id if i == 0 else None,
                        )
                    except Exception:
                        # Fallback if markdown fails
                        await update.message.reply_text(
                            message.text,
                            parse_mode=None,
                            reply_markup=message.reply_markup,
                            reply_to_message_id=update.message.message_id if i == 0 else None,
                        )

                    # Small delay between messages to avoid rate limits
                    if i < len(formatted_messages) - 1:
                        await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(
                        "Failed to send response message", error=str(e), message_index=i
                    )
                    # Try to send error message without parse_mode to avoid formatting issues
                    try:
                        await update.message.reply_text(
                            message.text,
                            parse_mode=None,  # Disable Markdown parsing
                            reply_to_message_id=update.message.message_id if i == 0 else None,
                        )
                    except Exception as retry_error:
                        logger.error("Failed to send even without parse_mode", error=str(retry_error))
                        await update.message.reply_text(
                            "❌ Failed to send response. Please try again.",
                            reply_to_message_id=update.message.message_id if i == 0 else None,
                        )

        # Update session info
        # context.user_data["last_message"] = update.message.text  # TODO: Check if needed for topics

        # Add conversation enhancements if available
        features = context.bot_data.get("features")
        conversation_enhancer = (
            features.get_conversation_enhancer() if features else None
        )

        if conversation_enhancer and claude_response:
            try:
                # Update conversation context
                # Update conversation context
                conversation_enhancer.update_context(
                    user_id=user_id,
                    response=claude_response,
                )
                
                # Get updated context
                conversation_context = conversation_enhancer.get_or_create_context(user_id)

                # Check if we should show follow-up suggestions
                if conversation_enhancer.should_show_suggestions(claude_response):
                    # Generate follow-up suggestions
                    suggestions = conversation_enhancer.generate_follow_up_suggestions(
                        claude_response,
                        conversation_context,
                    )

                    if suggestions:
                        # Create keyboard with suggestions
                        suggestion_keyboard = (
                            conversation_enhancer.create_follow_up_keyboard(suggestions)
                        )

                        # Send follow-up suggestions
                        await update.message.reply_text(
                            "💡 **What would you like to do next?**",
                            parse_mode="Markdown",
                            reply_markup=suggestion_keyboard,
                        )

            except Exception as e:
                logger.warning(
                    "Conversation enhancement failed", error=str(e), user_id=user_id
                )

        # Log successful message processing
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="text_message",
                args=[update.message.text[:100]],  # First 100 chars
                success=True,
            )

        logger.info("Text message processed successfully", user_id=user_id)

    except Exception as e:
        # Clean up progress message if it exists
        try:
            await progress_msg.delete()
        except:
            pass

        error_msg = f"❌ **Error processing message**\n\n{str(e)}"
        await update.message.reply_text(error_msg, parse_mode="Markdown")

        # Log failed processing
        if audit_logger:
            await audit_logger.log_command(
                user_id=user_id,
                command="text_message",
                args=[update.message.text[:100]],
                success=False,
            )

        logger.error("Error processing text message", error=str(e), user_id=user_id)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file uploads."""
    user_id = update.effective_user.id
    document = update.message.document
    settings: Settings = context.bot_data["settings"]

    # Get services
    security_validator: Optional[SecurityValidator] = context.bot_data.get(
        "security_validator"
    )
    audit_logger: Optional[AuditLogger] = context.bot_data.get("audit_logger")
    rate_limiter: Optional[RateLimiter] = context.bot_data.get("rate_limiter")

    logger.info(
        "Processing document upload",
        user_id=user_id,
        filename=document.file_name,
        file_size=document.file_size,
    )

    try:
        # Validate filename using security validator
        if security_validator:
            valid, error = security_validator.validate_filename(document.file_name)
            if not valid:
                await update.message.reply_text(
                    f"❌ **File Upload Rejected**\n\n{error}"
                )

                # Log security violation
                if audit_logger:
                    await audit_logger.log_security_violation(
                        user_id=user_id,
                        violation_type="invalid_file_upload",
                        details=f"Filename: {document.file_name}, Error: {error}",
                        severity="medium",
                    )
                return

        # Check file size limits
        max_size = 10 * 1024 * 1024  # 10MB
        if document.file_size > max_size:
            await update.message.reply_text(
                f"❌ **File Too Large**\n\n"
                f"Maximum file size: {max_size // 1024 // 1024}MB\n"
                f"Your file: {document.file_size / 1024 / 1024:.1f}MB"
            )
            return

        # Check rate limit for file processing
        file_cost = _estimate_file_processing_cost(document.file_size)
        if rate_limiter:
            allowed, limit_message = await rate_limiter.check_rate_limit(
                user_id, file_cost
            )
            if not allowed:
                await update.message.reply_text(f"⏱️ {limit_message}")
                return

        # Send processing indicator
        await update.message.chat.send_action("upload_document")

        progress_msg = await update.message.reply_text(
            f"📄 Processing file: `{document.file_name}`...", parse_mode="Markdown"
        )

        # Check if enhanced file handler is available
        features = context.bot_data.get("features")
        file_handler = features.get_file_handler() if features else None

        if file_handler:
            # Use enhanced file handler
            try:
                processed_file = await file_handler.handle_document_upload(
                    document,
                    user_id,
                    update.message.caption or "Please review this file:",
                )
                prompt = processed_file.prompt

                # Update progress message with file type info
                await progress_msg.edit_text(
                    f"📄 Processing {processed_file.type} file: `{document.file_name}`...",
                    parse_mode="Markdown",
                )

            except Exception as e:
                logger.warning(
                    "Enhanced file handler failed, falling back to basic handler",
                    error=str(e),
                )
                file_handler = None  # Fall back to basic handling

        if not file_handler:
            # Fall back to basic file handling
            file = await document.get_file()
            file_bytes = await file.download_as_bytearray()

            # Try to decode as text
            try:
                content = file_bytes.decode("utf-8")

                # Check content length
                max_content_length = 50000  # 50KB of text
                if len(content) > max_content_length:
                    content = (
                        content[:max_content_length]
                        + "\n... (file truncated for processing)"
                    )

                # Create prompt with file content
                caption = update.message.caption or "Please review this file:"
                prompt = f"{caption}\n\n**File:** `{document.file_name}`\n\n```\n{content}\n```"

            except UnicodeDecodeError:
                await progress_msg.edit_text(
                    "❌ **File Format Not Supported**\n\n"
                    "File must be text-based and UTF-8 encoded.\n\n"
                    "**Supported formats:**\n"
                    "• Source code files (.py, .js, .ts, etc.)\n"
                    "• Text files (.txt, .md)\n"
                    "• Configuration files (.json, .yaml, .toml)\n"
                    "• Documentation files"
                )
                return

        # Delete progress message
        await progress_msg.delete()

        # Create a new progress message for Claude processing
        claude_progress_msg = await update.message.reply_text(
            "🤖 Processing file with Claude...", parse_mode="Markdown"
        )

        # Get Claude integration from context
        claude_integration = context.bot_data.get("claude_integration")

        if not claude_integration:
            await claude_progress_msg.edit_text(
                "❌ **Claude integration not available**\n\n"
                "The Claude Code integration is not properly configured.",
                parse_mode="Markdown",
            )
            return

        # Get current directory and session
        current_dir = ContextManager.get_current_directory(update, context, settings)
        session_id = ContextManager.get_session_id(update, context)

        # Process with Claude
        try:
            claude_response = await claude_integration.run_command(
                prompt=prompt,
                working_directory=current_dir,
                user_id=user_id,
                session_id=session_id,
            )

            # Update session ID
            ContextManager.set_session_id(update, context, claude_response.session_id)

            # Check if Claude changed the working directory and update our tracking
            _update_working_directory_from_claude_response(
                claude_response, update, context, settings, user_id
            )

            # Format and send response
            from ..utils.formatting import ResponseFormatter

            formatter = ResponseFormatter(settings)
            formatted_messages = formatter.format_claude_response(
                claude_response.content
            )

            # Delete progress message
            await claude_progress_msg.delete()

            # Send responses
            for i, message in enumerate(formatted_messages):
                await update.message.reply_text(
                    message.text,
                    parse_mode=message.parse_mode,
                    reply_markup=message.reply_markup,
                    reply_to_message_id=(update.message.message_id if i == 0 else None),
                )

                if i < len(formatted_messages) - 1:
                    await asyncio.sleep(0.5)

        except Exception as e:
            await claude_progress_msg.edit_text(
                _format_error_message(str(e)), parse_mode="Markdown"
            )
            logger.error("Claude file processing failed", error=str(e), user_id=user_id)

        # Log successful file processing
        if audit_logger:
            await audit_logger.log_file_access(
                user_id=user_id,
                file_path=document.file_name,
                action="upload_processed",
                success=True,
                file_size=document.file_size,
            )

    except Exception as e:
        try:
            await progress_msg.delete()
        except:
            pass

        error_msg = f"❌ **Error processing file**\n\n{str(e)}"
        await update.message.reply_text(error_msg, parse_mode="Markdown")

        # Log failed file processing
        if audit_logger:
            await audit_logger.log_file_access(
                user_id=user_id,
                file_path=document.file_name,
                action="upload_failed",
                success=False,
                file_size=document.file_size,
            )

        logger.error("Error processing document", error=str(e), user_id=user_id)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads."""
    user_id = update.effective_user.id
    settings: Settings = context.bot_data["settings"]

    # Check if enhanced image handler is available
    features = context.bot_data.get("features")
    image_handler = features.get_image_handler() if features else None

    if image_handler:
        try:
            # Send processing indicator
            progress_msg = await update.message.reply_text(
                "📸 Processing image...", parse_mode="Markdown"
            )

            # Get the largest photo size
            photo = update.message.photo[-1]

            # Process image with enhanced handler
            processed_image = await image_handler.process_image(
                photo, update.message.caption
            )

            # Delete progress message
            await progress_msg.delete()

            # Create Claude progress message
            claude_progress_msg = await update.message.reply_text(
                "🤖 Analyzing image with Claude...", parse_mode="Markdown"
            )

            # Get Claude integration
            claude_integration = context.bot_data.get("claude_integration")

            if not claude_integration:
                await claude_progress_msg.edit_text(
                    "❌ **Claude integration not available**\n\n"
                    "The Claude Code integration is not properly configured.",
                    parse_mode="Markdown",
                )
                return

            # Get current directory and session
            current_dir = ContextManager.get_current_directory(update, context, settings)
            session_id = ContextManager.get_session_id(update, context)

            # Process with Claude
            try:
                claude_response = await claude_integration.run_command(
                    prompt=processed_image.prompt,
                    working_directory=current_dir,
                    user_id=user_id,
                    session_id=session_id,
                )

                # Update session ID
                ContextManager.set_session_id(update, context, claude_response.session_id)

                # Format and send response
                from ..utils.formatting import ResponseFormatter

                formatter = ResponseFormatter(settings)
                formatted_messages = formatter.format_claude_response(
                    claude_response.content
                )

                # Delete progress message
                await claude_progress_msg.delete()

                # Send responses
                for i, message in enumerate(formatted_messages):
                    await update.message.reply_text(
                        message.text,
                        parse_mode=message.parse_mode,
                        reply_markup=message.reply_markup,
                        reply_to_message_id=(
                            update.message.message_id if i == 0 else None
                        ),
                    )

                    if i < len(formatted_messages) - 1:
                        await asyncio.sleep(0.5)

            except Exception as e:
                await claude_progress_msg.edit_text(
                    _format_error_message(str(e)), parse_mode="Markdown"
                )
                logger.error(
                    "Claude image processing failed", error=str(e), user_id=user_id
                )

        except Exception as e:
            logger.error("Image processing failed", error=str(e), user_id=user_id)
            await update.message.reply_text(
                f"❌ **Error processing image**\n\n{str(e)}", parse_mode="Markdown"
            )
    else:
        # Fall back to unsupported message
        await update.message.reply_text(
            "📸 **Photo Upload**\n\n"
            "Photo processing is not yet supported.\n\n"
            "**Currently supported:**\n"
            "• Text files (.py, .js, .md, etc.)\n"
            "• Configuration files\n"
            "• Documentation files\n\n"
            "**Coming soon:**\n"
            "• Image analysis\n"
            "• Screenshot processing\n"
            "• Diagram interpretation"
        )


def _estimate_text_processing_cost(text: str) -> float:
    """Estimate cost for processing text message."""
    # Base cost
    base_cost = 0.001

    # Additional cost based on length
    length_cost = len(text) * 0.00001

    # Additional cost for complex requests
    complex_keywords = [
        "analyze",
        "generate",
        "create",
        "build",
        "implement",
        "refactor",
        "optimize",
        "debug",
        "explain",
        "document",
    ]

    text_lower = text.lower()
    complexity_multiplier = 1.0

    for keyword in complex_keywords:
        if keyword in text_lower:
            complexity_multiplier += 0.5

    return (base_cost + length_cost) * min(complexity_multiplier, 3.0)


def _estimate_file_processing_cost(file_size: int) -> float:
    """Estimate cost for processing uploaded file."""
    # Base cost for file handling
    base_cost = 0.005

    # Additional cost based on file size (per KB)
    size_cost = (file_size / 1024) * 0.0001

    return base_cost + size_cost


async def _generate_placeholder_response(
    message_text: str, context: ContextTypes.DEFAULT_TYPE
) -> dict:
    """Generate placeholder response until Claude integration is implemented."""
    settings: Settings = context.bot_data["settings"]
    current_dir = getattr(
        context.user_data, "current_directory", settings.approved_directory
    )
    relative_path = current_dir.relative_to(settings.approved_directory)

    # Analyze the message for intent
    message_lower = message_text.lower()

    if any(
        word in message_lower for word in ["list", "show", "see", "directory", "files"]
    ):
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I understand you want to see files. Try using the `/ls` command to list files "
            f"in your current directory (`{relative_path}/`).\n\n"
            f"**Available commands:**\n"
            f"• `/ls` - List files\n"
            f"• `/cd <dir>` - Change directory\n"
            f"• `/projects` - Show projects\n\n"
            f"_Note: Full Claude Code integration will be available in the next phase._"
        )

    elif any(word in message_lower for word in ["create", "generate", "make", "build"]):
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I understand you want to create something! Once the Claude Code integration "
            f"is complete, I'll be able to:\n\n"
            f"• Generate code files\n"
            f"• Create project structures\n"
            f"• Write documentation\n"
            f"• Build complete applications\n\n"
            f"**Current directory:** `{relative_path}/`\n\n"
            f"_Full functionality coming soon!_"
        )

    elif any(word in message_lower for word in ["help", "how", "what", "explain"]):
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I'm here to help! Try using `/help` for available commands.\n\n"
            f"**What I can do now:**\n"
            f"• Navigate directories (`/cd`, `/ls`, `/pwd`)\n"
            f"• Show projects (`/projects`)\n"
            f"• Manage sessions (`/new`, `/status`)\n\n"
            f"**Coming soon:**\n"
            f"• Full Claude Code integration\n"
            f"• Code generation and editing\n"
            f"• File operations\n"
            f"• Advanced programming assistance"
        )

    else:
        response_text = (
            f"🤖 **Claude Code Response** _(Placeholder)_\n\n"
            f"I received your message: \"{message_text[:100]}{'...' if len(message_text) > 100 else ''}\"\n\n"
            f"**Current Status:**\n"
            f"• Directory: `{relative_path}/`\n"
            f"• Bot core: ✅ Active\n"
            f"• Claude integration: 🔄 Coming soon\n\n"
            f"Once Claude Code integration is complete, I'll be able to process your "
            f"requests fully and help with coding tasks!\n\n"
            f"For now, try the available commands like `/ls`, `/cd`, and `/help`."
        )

    return {"text": response_text, "parse_mode": "Markdown"}


def _update_working_directory_from_claude_response(
    claude_response, update, context, settings, user_id
):
    """Update the working directory based on Claude's response content."""
    import re
    from pathlib import Path

    # Look for directory changes in Claude's response
    # This searches for common patterns that indicate directory changes
    patterns = [
        r"(?:^|\n).*?cd\s+([^\s\n]+)",  # cd command
        r"(?:^|\n).*?Changed directory to:?\s*([^\s\n]+)",  # explicit directory change
        r"(?:^|\n).*?Current directory:?\s*([^\s\n]+)",  # current directory indication
        r"(?:^|\n).*?Working directory:?\s*([^\s\n]+)",  # working directory indication
    ]

    content = claude_response.content.lower()
    current_dir = ContextManager.get_current_directory(update, context, settings)

    for pattern in patterns:
        matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            try:
                # Clean up the path
                new_path = match.strip().strip("\"'`")

                # Handle relative paths
                if new_path.startswith("./") or new_path.startswith("../"):
                    new_path = (current_dir / new_path).resolve()
                elif not new_path.startswith("/"):
                    # Relative path without ./
                    new_path = (current_dir / new_path).resolve()
                else:
                    # Absolute path
                    new_path = Path(new_path).resolve()

                # Validate that the new path is within the approved directory
                if (
                    new_path.is_relative_to(settings.approved_directory)
                    and new_path.exists()
                ):
                    ContextManager.set_current_directory(update, context, new_path)
                    logger.info(
                        "Updated working directory from Claude response",
                        old_dir=str(current_dir),
                        new_dir=str(new_path),
                        user_id=user_id,
                    )
                    return  # Take the first valid match

            except (ValueError, OSError) as e:
                # Invalid path, skip this match
                logger.debug(
                    "Invalid path in Claude response", path=match, error=str(e)
                )
                continue
