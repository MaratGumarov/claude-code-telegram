"""Topic creation handler for creating new forum topics."""

import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from ...config.settings import Settings

logger = structlog.get_logger()

# States
WAITING_FOR_TOPIC_NAME = 1


class CreateTopicHandler:
    """Handler for creating new forum topics."""

    @staticmethod
    async def start_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the topic creation process."""
        query = update.callback_query
        await query.answer()

        # Check if we are in a group chat
        if update.effective_chat.type == "private":
            await query.edit_message_text(
                "❌ **Cannot Create Topic**\n\n"
                "Topics can only be created in **Supergroups** with Topics enabled.\n\n"
                "**To use this feature:**\n"
                "1. Create a Group in Telegram\n"
                "2. Enable 'Topics' in Group Settings\n"
                "3. Add this bot as an Admin\n"
                "4. Try again in the group!",
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        await query.edit_message_text(
            "📝 **Create New Topic**\n\n"
            "Please enter the name for the new topic (e.g., 'Project Alpha').\n\n"
            "Type /cancel to abort.",
            parse_mode="Markdown"
        )
        return WAITING_FOR_TOPIC_NAME

    @staticmethod
    async def handle_topic_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the topic name input and create the topic."""
        topic_name = update.message.text
        chat_id = update.effective_chat.id
        user = update.effective_user

        if len(topic_name) > 128:
            await update.message.reply_text(
                "❌ **Name Too Long**\n\n"
                "Topic name must be 128 characters or less. Please try again."
            )
            return WAITING_FOR_TOPIC_NAME

        try:
            # Create the forum topic
            topic = await context.bot.create_forum_topic(
                chat_id=chat_id,
                name=topic_name,
                icon_color=0x6FB9F0  # Default blue color
            )

            # Send welcome message to the new topic
            await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=topic.message_thread_id,
                text=(
                    f"🚀 **Topic Created: {topic_name}**\n\n"
                    f"Created by {user.mention_markdown()}\n\n"
                    f"This topic has its own independent Claude session.\n"
                    f"Use `/new` to start a fresh conversation here."
                ),
                parse_mode="Markdown"
            )

            # Confirm in the main thread (where command was started)
            await update.message.reply_text(
                f"✅ **Topic Created!**\n\n"
                f"Go to the new topic **{topic_name}** to start working.",
                parse_mode="Markdown"
            )

        except Exception as e:
            error_msg = str(e)
            if "not enough rights" in error_msg.lower():
                await update.message.reply_text(
                    "❌ **Permission Error**\n\n"
                    "I don't have permission to create topics.\n"
                    "Please promote me to **Admin** with 'Manage Topics' rights."
                )
            elif "forum not enabled" in error_msg.lower() or "not a forum" in error_msg.lower():
                await update.message.reply_text(
                    "❌ **Topics Not Enabled**\n\n"
                    "This group does not have Topics enabled.\n"
                    "Please enable 'Topics' in Group Settings."
                )
            else:
                await update.message.reply_text(
                    f"❌ **Error**\n\nFailed to create topic: {error_msg}"
                )
            
            logger.error("Failed to create topic", error=error_msg, chat_id=chat_id)

        return ConversationHandler.END

    @staticmethod
    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        await update.message.reply_text(
            "❌ Topic creation cancelled.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    @classmethod
    def get_handler(cls):
        """Return the ConversationHandler for registration."""
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(cls.start_creation, pattern="^action:create_topic$")
            ],
            states={
                WAITING_FOR_TOPIC_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, cls.handle_topic_name)
                ],
            },
            fallbacks=[CommandHandler("cancel", cls.cancel)],
        )
