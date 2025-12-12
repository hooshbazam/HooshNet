"""
Channel Membership Checker
Ensures users are members of required channel before using bot features
"""

import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest, Forbidden
from config import BOT_CONFIG
from message_templates import MessageTemplates

logger = logging.getLogger(__name__)


async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_config=None) -> bool:
    """
    Check if user is member of required channel
    
    Args:
        update: Telegram update
        context: Bot context
        bot_config: Optional bot config dict (if None, uses BOT_CONFIG from config)
    
    Returns:
        bool: True if user is member or admin, False otherwise
    """
    try:
        # Get bot config
        if bot_config is None:
            from config import BOT_CONFIG
            bot_config = BOT_CONFIG
        
        user_id = update.effective_user.id
        
        # Admin bypass
        if user_id == bot_config['admin_id']:
            return True
        
        channel_id = bot_config.get('channel_id')
        if not channel_id:
            # No channel configured, allow access
            return True
        
        # Normalize channel_id: if it's a username without @, add @
        if isinstance(channel_id, str) and not channel_id.startswith('@') and not channel_id.startswith('-'):
            # It's a username, add @ prefix
            channel_id = f"@{channel_id}"
            logger.debug(f"Normalized channel_id to: {channel_id}")
        
        # Get bot instance from context
        bot = context.bot
        
        # Check membership
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            # Check if user is member, administrator, or creator
            status = member.status
            if status in ['member', 'administrator', 'creator']:
                return True
            else:
                return False
        except BadRequest as e:
            logger.error(f"BadRequest checking channel membership: {e}")
            # If channel not found or user not found, deny access
            return False
        except Forbidden as e:
            logger.error(f"Forbidden checking channel membership: {e}")
            # Bot may not have access to channel, allow access but log warning
            logger.warning("Bot may not have access to check channel membership")
            return True  # Allow access if bot can't check
        except TelegramError as e:
            logger.error(f"TelegramError checking channel membership: {e}")
            # On error, allow access but log
            return True
            
    except Exception as e:
        logger.error(f"Error in check_channel_membership: {e}")
        # On unexpected error, allow access
        return True


async def show_force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_config=None):
    """Show force join message with channel link"""
    if bot_config is None:
        from config import BOT_CONFIG
        bot_config = BOT_CONFIG
    
    channel_id = bot_config.get('channel_id', '@AzadJooNet')
    channel_link = bot_config.get('channel_link', 'https://t.me/AzadJooNet')
    
    message = MessageTemplates.WELCOME_MESSAGES.get('force_join', """
📢 برای استفاده از ربات آزاد‌جو نت، لطفاً ابتدا در کانال ما عضو شوید

🔹 چرا عضویت در کانال؟
• دریافت آخرین اخبار و به‌روزرسانی‌ها
• اطلاع از تخفیف‌ها و پیشنهادات ویژه
• آموزش‌های رایگان و نکات کاربردی
• پشتیبانی سریع‌تر و اولویت‌دار

✅ مراحل فعال‌سازی:
۱. روی دکمه زیر کلیک کنید
۲. وارد کانال شوید و عضو شوید
۳. به ربات برگردید و دوباره /start را بزنید

🌐 آزاد‌جو نت | دریچه‌ای به دنیای آزاد
    """)
    
    keyboard = [
        [InlineKeyboardButton("📢 عضویت در کانال", url=channel_link)],
        [InlineKeyboardButton("✅ عضو شدم", callback_data="check_channel_join")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Try to edit message if callback query, otherwise send new message
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await update.callback_query.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    elif update.message:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )


def require_channel_membership(func):
    """
    Decorator to require channel membership before executing handler
    
    Usage:
        @require_channel_membership
        async def my_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            ...
    """
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # Check if user is member of channel
        is_member = await check_channel_membership(update, context)
        
        if not is_member:
            # Show force join message
            await show_force_join_message(update, context)
            return  # Don't execute handler
        
        # User is member, execute handler
        return await func(self, update, context, *args, **kwargs)
    
    return wrapper

