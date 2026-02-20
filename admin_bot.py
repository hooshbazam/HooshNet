"""
ربات مدیریتی حرفه‌ای برای مدیریت ربات‌های VPN
این ربات امکان ساخت، ویرایش، حذف و مدیریت ربات‌های فعال را فراهم می‌کند
"""

import os
import sys
import re
import logging
import asyncio
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from telegram.constants import ParseMode

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bots.bot_config_manager import BotConfigManager

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
(
    MAIN_MENU,
    CREATE_BOT_NAME,
    CREATE_BOT_TOKEN,
    CREATE_BOT_ADMIN_ID,
    CREATE_BOT_USERNAME,
    CREATE_BOT_REPORTS_CHANNEL,
    CREATE_BOT_LICENSE,
    CREATE_BOT_DATABASE,
    CREATE_BOT_WEBAPP_PORT,
    CREATE_BOT_WEBAPP_URL,
    CREATE_BOT_CONFIRM,
    EDIT_BOT_SELECT,
    EDIT_BOT_FIELD_SELECT,
    EDIT_BOT_VALUE,
    DELETE_BOT_CONFIRM,
    TOGGLE_BOT_CONFIRM
) = range(18)

# Field names for display
FIELD_NAMES = {
    'token': '🔑 توکن ربات',
    'admin_id': '👤 شناسه ادمین',
    'bot_username': '📱 یوزرنیم ربات',
    'reports_channel_id': '📢 شناسه گروه گزارشات',
    'starsefar_license': '⭐ لایسنس StarsOffer',
    'database_name': '💾 نام دیتابیس',
    'webapp_port': '🌐 پورت وب‌اپ',
    'webapp_url': '🌐 آدرس وب‌اپ'
}

# Required fields for bot creation
REQUIRED_FIELDS = [
    'token', 'admin_id', 'bot_username', 'reports_channel_id',
    'starsefar_license', 'database_name'
]

# Optional fields
OPTIONAL_FIELDS = ['webapp_port', 'webapp_url']


class AdminBot:
    """ربات مدیریتی برای مدیریت ربات‌های VPN"""
    
    def __init__(self, token: str, admin_ids: List[int]):
        """
        Initialize Admin Bot
        
        Args:
            token: Telegram bot token
            admin_ids: List of admin user IDs who can use this bot
        """
        self.token = token
        self.admin_ids = admin_ids
        self.config_manager = BotConfigManager()
        self.user_sessions = {}  # Store user session data for multi-step forms
        
        # Build application
        self.application = Application.builder().token(token).build()
        
        # Add handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup all bot handlers"""
        # Start and menu commands (always send new message)
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("menu", self.show_main_menu))
        
        # Main menu conversation (for callback queries)
        main_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.handle_main_menu, pattern="^main_menu$"),
                # Entry point for callback queries when user is already in conversation
                CallbackQueryHandler(self.handle_main_menu_callback, pattern="^(create_bot|list_bots|edit_bot|delete_bot|toggle_bot)$")
            ],
            per_chat=True,
            per_user=True,
            per_message=False,
            states={
                MAIN_MENU: [
                    CallbackQueryHandler(self.handle_create_bot, pattern="^create_bot$"),
                    CallbackQueryHandler(self.handle_list_bots, pattern="^list_bots$"),
                    CallbackQueryHandler(self.handle_edit_bot_menu, pattern="^edit_bot$"),
                    CallbackQueryHandler(self.handle_delete_bot_menu, pattern="^delete_bot$"),
                    CallbackQueryHandler(self.handle_toggle_bot_menu, pattern="^toggle_bot$"),
                    CallbackQueryHandler(self.handle_bot_details, pattern="^bot_details:")
                ],
                ConversationHandler.WAITING: [],
                CREATE_BOT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_name)
                ],
                CREATE_BOT_TOKEN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_token)
                ],
                CREATE_BOT_ADMIN_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_admin_id)
                ],
                CREATE_BOT_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_username)
                ],
                CREATE_BOT_REPORTS_CHANNEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_reports_channel)
                ],
                CREATE_BOT_LICENSE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_license)
                ],
                CREATE_BOT_DATABASE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_database)
                ],
                CREATE_BOT_WEBAPP_PORT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_webapp_port)
                ],
                CREATE_BOT_WEBAPP_URL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_create_bot_webapp_url)
                ],
                CREATE_BOT_CONFIRM: [
                    CallbackQueryHandler(self.handle_create_bot_confirm, pattern="^confirm_create$"),
                    CallbackQueryHandler(self.handle_cancel_create, pattern="^cancel_create$")
                ],
                EDIT_BOT_SELECT: [
                    CallbackQueryHandler(self.handle_edit_bot_select, pattern="^edit_bot:")
                ],
                EDIT_BOT_FIELD_SELECT: [
                    CallbackQueryHandler(self.handle_edit_field_select, pattern="^edit_field:"),
                    CallbackQueryHandler(self.handle_back_to_edit_menu, pattern="^back_to_edit")
                ],
                EDIT_BOT_VALUE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_edit_value)
                ],
                DELETE_BOT_CONFIRM: [
                    CallbackQueryHandler(self.handle_delete_select, pattern="^delete_bot:"),
                    CallbackQueryHandler(self.handle_delete_confirm, pattern="^delete_confirm:"),
                    CallbackQueryHandler(self.handle_cancel_delete, pattern="^cancel_delete$")
                ],
                TOGGLE_BOT_CONFIRM: [
                    CallbackQueryHandler(self.handle_toggle_select, pattern="^toggle_bot:"),
                    CallbackQueryHandler(self.handle_toggle_confirm, pattern="^toggle_confirm:"),
                    CallbackQueryHandler(self.handle_cancel_toggle, pattern="^cancel_toggle$")
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_command),
                CallbackQueryHandler(self.handle_cancel, pattern="^cancel$")
            ]
        )
        
        self.application.add_handler(main_conv)
        
        # Add a catch-all callback handler for debugging (should not be needed but helps debug)
        async def debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Debug callback handler"""
            if update.callback_query:
                logger.warning(f"Unhandled callback query: {update.callback_query.data}")
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
    
    def _is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_ids
    
    async def _safe_edit_message(self, query, text: str, reply_markup=None, parse_mode=None):
        """Safely edit message, ignoring 'Message is not modified' error"""
        try:
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )
        except Exception as e:
            # Ignore "Message is not modified" error
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message: {e}")
                raise
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - always sends new message"""
        user_id = update.effective_user.id
        
        if not self._is_admin(user_id):
            await update.message.reply_text(
                "❌ شما دسترسی به این ربات را ندارید.\n"
                "این ربات فقط برای مدیران سیستم است."
            )
            return
        
        # Show main menu (always sends new message)
        await self.show_main_menu(update, context)
        
        # Manually set conversation state for callback queries
        context.user_data['conversation_state'] = MAIN_MENU
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu"""
        user_id = update.effective_user.id
        
        if not self._is_admin(user_id):
            return
        
        # Get bot statistics
        all_bots = self.config_manager.get_all_bots()
        active_bots = self.config_manager.get_active_bots()
        
        text = (
            "🤖 پنل مدیریت ربات‌های VPN\n\n"
            f"📊 آمار:\n"
            f"• کل ربات‌ها: {len(all_bots)}\n"
            f"• ربات‌های فعال: {len(active_bots)}\n"
            f"• ربات‌های غیرفعال: {len(all_bots) - len(active_bots)}\n\n"
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ ساخت ربات جدید", callback_data="create_bot")],
            [InlineKeyboardButton("📋 لیست ربات‌ها", callback_data="list_bots")],
            [InlineKeyboardButton("✏️ ویرایش ربات", callback_data="edit_bot")],
            [InlineKeyboardButton("🗑️ حذف ربات", callback_data="delete_bot")],
            [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data="toggle_bot")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            # Manually set conversation state for callback queries
            context.user_data['conversation_state'] = MAIN_MENU
    
    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle main menu callback"""
        return await self.show_main_menu(update, context)
    
    async def handle_main_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries that should start conversation"""
        query = update.callback_query
        await query.answer()
        
        # Route to appropriate handler based on callback data
        callback_data = query.data
        if callback_data == "create_bot":
            return await self.handle_create_bot(update, context)
        elif callback_data == "list_bots":
            return await self.handle_list_bots(update, context)
        elif callback_data == "edit_bot":
            return await self.handle_edit_bot_menu(update, context)
        elif callback_data == "delete_bot":
            return await self.handle_delete_bot_menu(update, context)
        elif callback_data == "toggle_bot":
            return await self.handle_toggle_bot_menu(update, context)
        
        return MAIN_MENU
    
    # ==================== CREATE BOT ====================
    
    async def handle_create_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start bot creation process"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        self.user_sessions[user_id] = {'creating_bot': {}}
        
        text = (
            "➕ ساخت ربات جدید\n\n"
            "لطفاً نام ربات را وارد کنید:\n"
            "⚠️ فقط حروف انگلیسی، اعداد، خط تیره و آندرلاین مجاز است."
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_NAME
    
    async def handle_create_bot_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot name input"""
        user_id = update.effective_user.id
        bot_name = update.message.text.strip()
        
        # Validate bot name
        if not re.match(r'^[a-zA-Z0-9_\-]+$', bot_name):
            await update.message.reply_text(
                "❌ نام ربات نامعتبر است!\n"
                "فقط حروف انگلیسی، اعداد، خط تیره و آندرلاین مجاز است.\n"
                "لطفاً دوباره وارد کنید:"
            )
            return CREATE_BOT_NAME
        
        # Check if bot exists
        if bot_name in self.config_manager.get_all_bots():
            await update.message.reply_text(
                f"❌ ربات با نام '{bot_name}' از قبل وجود دارد!\n"
                "لطفاً نام دیگری انتخاب کنید:"
            )
            return CREATE_BOT_NAME
        
        # Store bot name
        self.user_sessions[user_id]['creating_bot']['bot_name'] = bot_name
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'token'
        
        text = (
            f"✅ نام ربات: *{bot_name}*\n\n"
            f"لطفاً {FIELD_NAMES['token']} را وارد کنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_TOKEN
    
    async def handle_create_bot_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot token input"""
        user_id = update.effective_user.id
        token = update.message.text.strip()
        
        # Basic validation
        if not token or len(token) < 20:
            await update.message.reply_text(
                "❌ توکن نامعتبر است!\nلطفاً توکن صحیح را وارد کنید:"
            )
            return CREATE_BOT_TOKEN
        
        self.user_sessions[user_id]['creating_bot']['token'] = token
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'admin_id'
        
        text = (
            f"✅ توکن ثبت شد\n\n"
            f"لطفاً {FIELD_NAMES['admin_id']} را وارد کنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_ADMIN_ID
    
    async def handle_create_bot_admin_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin ID input"""
        user_id = update.effective_user.id
        admin_id_str = update.message.text.strip()
        
        try:
            admin_id = int(admin_id_str)
        except ValueError:
            await update.message.reply_text(
                "❌ شناسه باید یک عدد باشد!\nلطفاً دوباره وارد کنید:"
            )
            return CREATE_BOT_ADMIN_ID
        
        self.user_sessions[user_id]['creating_bot']['admin_id'] = admin_id
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'bot_username'
        
        text = (
            f"✅ شناسه ادمین ثبت شد: {admin_id}\n\n"
            f"لطفاً {FIELD_NAMES['bot_username']} را وارد کنید (بدون @):"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_USERNAME
    
    async def handle_create_bot_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot username input"""
        user_id = update.effective_user.id
        username = update.message.text.strip().replace('@', '')
        
        if not username:
            await update.message.reply_text(
                "❌ یوزرنیم نمی‌تواند خالی باشد!\nلطفاً دوباره وارد کنید:"
            )
            return CREATE_BOT_USERNAME
        
        self.user_sessions[user_id]['creating_bot']['bot_username'] = username
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'reports_channel_id'
        
        text = (
            f"✅ یوزرنیم ثبت شد: @{username}\n\n"
            f"لطفاً {FIELD_NAMES['reports_channel_id']} را وارد کنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_REPORTS_CHANNEL
    
    async def handle_create_bot_reports_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle reports channel ID input"""
        user_id = update.effective_user.id
        channel_id_str = update.message.text.strip()
        
        try:
            channel_id = int(channel_id_str)
        except ValueError:
            await update.message.reply_text(
                "❌ شناسه باید یک عدد باشد!\nلطفاً دوباره وارد کنید:"
            )
            return CREATE_BOT_REPORTS_CHANNEL
        
        self.user_sessions[user_id]['creating_bot']['reports_channel_id'] = channel_id
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'starsefar_license'
        
        text = (
            f"✅ شناسه گروه گزارشات ثبت شد: {channel_id}\n\n"
            f"لطفاً {FIELD_NAMES['starsefar_license']} را وارد کنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_LICENSE
    
    
    async def handle_create_bot_license(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle license key input"""
        user_id = update.effective_user.id
        license_key = update.message.text.strip()
        
        if not license_key:
            await update.message.reply_text(
                "❌ لایسنس نمی‌تواند خالی باشد!\nلطفاً دوباره وارد کنید:"
            )
            return CREATE_BOT_LICENSE
        
        self.user_sessions[user_id]['creating_bot']['starsefar_license'] = license_key
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'database_name'
        
        bot_name = self.user_sessions[user_id]['creating_bot']['bot_name']
        default_db = f"vpn_bot_{bot_name.lower()}"
        
        text = (
            f"✅ لایسنس ثبت شد\n\n"
            f"لطفاً {FIELD_NAMES['database_name']} را وارد کنید:\n"
            f"💡 پیش‌فرض: {default_db}\n"
            f"برای استفاده از پیش‌فرض، فقط Enter بزنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_DATABASE
    
    async def handle_create_bot_database(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle database name input"""
        user_id = update.effective_user.id
        db_name = update.message.text.strip()
        
        bot_name = self.user_sessions[user_id]['creating_bot']['bot_name']
        if not db_name:
            db_name = f"vpn_bot_{bot_name.lower()}"
        
        self.user_sessions[user_id]['creating_bot']['database_name'] = db_name
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'webapp_port'
        
        text = (
            f"✅ نام دیتابیس ثبت شد: {db_name}\n\n"
            f"لطفاً {FIELD_NAMES['webapp_port']} را وارد کنید:\n"
            f"💡 برای تخصیص خودکار، خالی بگذارید یا Enter بزنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_WEBAPP_PORT
    
    async def handle_create_bot_webapp_port(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle webapp port input"""
        user_id = update.effective_user.id
        port_str = update.message.text.strip()
        
        if port_str:
            try:
                port = int(port_str)
                if port < 1 or port > 65535:
                    raise ValueError("Port out of range")
                self.user_sessions[user_id]['creating_bot']['webapp_port'] = port
            except ValueError:
                await update.message.reply_text(
                    "❌ پورت نامعتبر است! (باید عددی بین 1 تا 65535 باشد)\n"
                    "لطفاً دوباره وارد کنید یا خالی بگذارید:"
                )
                return CREATE_BOT_WEBAPP_PORT
        
        self.user_sessions[user_id]['creating_bot']['current_field'] = 'webapp_url'
        
        text = (
            f"✅ پورت ثبت شد: {port_str if port_str else 'خودکار'}\n\n"
            f"لطفاً {FIELD_NAMES['webapp_url']} را وارد کنید:\n"
            f"💡 برای استفاده از localhost، خالی بگذارید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_WEBAPP_URL
    
    async def handle_create_bot_webapp_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle webapp URL input and show confirmation"""
        user_id = update.effective_user.id
        webapp_url = update.message.text.strip()
        
        if webapp_url:
            # Ensure https:// prefix
            if not webapp_url.startswith('https://'):
                if webapp_url.startswith('http://'):
                    webapp_url = webapp_url.replace('http://', 'https://', 1)
                else:
                    webapp_url = f"https://{webapp_url}"
            
            self.user_sessions[user_id]['creating_bot']['webapp_url'] = webapp_url
        
        # Prepare config for registration
        bot_data = self.user_sessions[user_id]['creating_bot']
        bot_name = bot_data['bot_name']
        config = {k: v for k, v in bot_data.items() if k != 'bot_name' and k != 'current_field'}
        
        # Show confirmation
        text = self._format_bot_config_summary(bot_name, config)
        text += "\n\n⚠️ آیا می‌خواهید این ربات را ثبت کنید؟"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ تایید و ثبت", callback_data="confirm_create"),
                InlineKeyboardButton("❌ لغو", callback_data="cancel_create")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return CREATE_BOT_CONFIRM
    
    async def handle_create_bot_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and register bot"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        bot_data = self.user_sessions[user_id]['creating_bot']
        bot_name = bot_data['bot_name']
        config = {k: v for k, v in bot_data.items() if k != 'bot_name' and k != 'current_field'}
        
        # Register bot
        if self.config_manager.register_bot(bot_name, config):
            text = (
                f"✅ *ربات با موفقیت ثبت شد!*\n\n"
                f"📝 نام ربات: *{bot_name}*\n"
                f"📱 یوزرنیم: @{config['bot_username']}\n\n"
                f"💡 برای راه‌اندازی ربات از دستور زیر استفاده کنید:\n"
                f"`python run_all_bots.py`"
            )
            
            # Clear session
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            
            keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
            return ConversationHandler.END
        else:
            text = (
                "❌ خطا در ثبت ربات\n\n"
                "لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
            return ConversationHandler.END
    
    async def handle_cancel_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel bot creation"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        
        await query.edit_message_text(
            "❌ عملیات ساخت ربات لغو شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
            ]])
        )
        
        return ConversationHandler.END
    
    # ==================== LIST BOTS ====================
    
    async def handle_list_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of all bots"""
        query = update.callback_query
        await query.answer()
        
        all_bots = self.config_manager.get_all_bots()
        
        if not all_bots:
            text = "❌ هیچ رباتی ثبت نشده است."
            keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
            return MAIN_MENU
        
        text = "📋 لیست ربات‌ها:\n\n"
        keyboard = []
        
        for bot_name, bot_config in all_bots.items():
            is_active = bot_config.get('is_active', True)
            status = "✅" if is_active else "❌"
            username = bot_config.get('bot_username', 'N/A')
            
            # Escape special characters for Markdown
            escaped_bot_name = escape_markdown(bot_name, version=2)
            escaped_username = escape_markdown(username, version=2)
            escaped_db_name = escape_markdown(str(bot_config.get('database_name', 'N/A')), version=2)
            
            text += f"{status} {escaped_bot_name}\n"
            text += f"   📱 @{escaped_username}\n"
            text += f"   💾 {escaped_db_name}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {bot_name}",
                    callback_data=f"bot_details:{bot_name}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return MAIN_MENU
    
    async def handle_bot_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed information about a bot"""
        query = update.callback_query
        await query.answer()
        
        bot_name = query.data.split(":")[1]
        bot_config = self.config_manager.get_bot_config(bot_name)
        
        if not bot_config:
            await query.answer("❌ ربات یافت نشد!", show_alert=True)
            return MAIN_MENU
        
        text = self._format_bot_config_details(bot_name, bot_config)
        
        keyboard = [
            [
                InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_bot:{bot_name}"),
                InlineKeyboardButton("🔄 وضعیت", callback_data=f"toggle_bot:{bot_name}")
            ],
            [InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_bot:{bot_name}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="list_bots")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return MAIN_MENU
    
    # ==================== EDIT BOT ====================
    
    async def handle_edit_bot_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show edit bot menu"""
        query = update.callback_query
        await query.answer()
        
        all_bots = self.config_manager.get_all_bots()
        
        if not all_bots:
            text = "❌ هیچ رباتی برای ویرایش وجود ندارد."
            keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
            return MAIN_MENU
        
        text = "✏️ ویرایش ربات\n\nلطفاً ربات مورد نظر را انتخاب کنید:"
        keyboard = []
        
        for bot_name in all_bots.keys():
            keyboard.append([
                InlineKeyboardButton(
                    f"📱 {bot_name}",
                    callback_data=f"edit_bot:{bot_name}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return EDIT_BOT_SELECT
    
    async def handle_edit_bot_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Select bot to edit"""
        query = update.callback_query
        await query.answer()
        
        bot_name = query.data.split(":")[1]
        bot_config = self.config_manager.get_bot_config(bot_name)
        
        if not bot_config:
            await query.answer("❌ ربات یافت نشد!", show_alert=True)
            return EDIT_BOT_SELECT
        
        user_id = update.effective_user.id
        self.user_sessions[user_id] = {
            'editing_bot': bot_name,
            'bot_config': bot_config.copy()
        }
        
        text = f"✏️ ویرایش ربات: {bot_name}\n\n"
        text += "لطفاً فیلد مورد نظر را انتخاب کنید:\n\n"
        
        keyboard = []
        editable_fields = REQUIRED_FIELDS + OPTIONAL_FIELDS
        
        for field in editable_fields:
            current_value = bot_config.get(field, 'N/A')
            if field == 'token' and current_value != 'N/A':
                current_value = f"{current_value[:10]}..."  # Show only first 10 chars
            elif field in ['admin_id', 'reports_channel_id', 'webapp_port']:
                current_value = str(current_value)
            
            field_display = FIELD_NAMES.get(field, field)
            keyboard.append([
                InlineKeyboardButton(
                    f"{field_display}: {current_value}",
                    callback_data=f"edit_field:{field}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_edit")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self._safe_edit_message(
            query, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return EDIT_BOT_FIELD_SELECT
    
    async def handle_edit_field_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Select field to edit"""
        query = update.callback_query
        await query.answer()
        
        field = query.data.split(":")[1]
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            await query.answer("❌ خطا در دریافت اطلاعات!", show_alert=True)
            return EDIT_BOT_FIELD_SELECT
        
        bot_name = self.user_sessions[user_id]['editing_bot']
        bot_config = self.user_sessions[user_id]['bot_config']
        current_value = bot_config.get(field, '')
        
        self.user_sessions[user_id]['editing_field'] = field
        
        field_name = FIELD_NAMES.get(field, field)
        
        text = (
            f"✏️ *ویرایش فیلد: {field_name}*\n\n"
            f"مقدار فعلی: `{current_value}`\n\n"
            f"لطفاً مقدار جدید را وارد کنید:"
        )
        
        keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="back_to_edit")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return EDIT_BOT_VALUE
    
    async def handle_edit_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new value input"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            await update.message.reply_text("❌ خطا در دریافت اطلاعات!")
            return ConversationHandler.END
        
        field = self.user_sessions[user_id].get('editing_field')
        bot_name = self.user_sessions[user_id]['editing_bot']
        new_value = update.message.text.strip()
        
        # Validate based on field type
        if field in ['admin_id', 'reports_channel_id', 'webapp_port']:
            try:
                new_value = int(new_value)
            except ValueError:
                await update.message.reply_text(
                    f"❌ مقدار باید یک عدد باشد!\nلطفاً دوباره وارد کنید:"
                )
                return EDIT_BOT_VALUE
        
        if field == 'bot_username' or field == 'channel_id':
            new_value = new_value.replace('@', '')
        
        if field == 'channel_link' and not new_value.startswith('http'):
            await update.message.reply_text(
                "❌ لینک باید با http یا https شروع شود!\nلطفاً دوباره وارد کنید:"
            )
            return EDIT_BOT_VALUE
        
        # Update config
        updates = {field: new_value}
        if self.config_manager.update_bot_config(bot_name, updates):
            text = (
                f"✅ *فیلد با موفقیت به‌روزرسانی شد!*\n\n"
                f"فیلد: {FIELD_NAMES.get(field, field)}\n"
                f"مقدار جدید: `{new_value}`"
            )
            
            # Update session
            self.user_sessions[user_id]['bot_config'][field] = new_value
            
            keyboard = [
                [
                    InlineKeyboardButton("✏️ ویرایش فیلد دیگر", callback_data=f"edit_bot:{bot_name}"),
                    InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
            return ConversationHandler.END
        else:
            text = "❌ خطا در به‌روزرسانی فیلد!"
            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text, reply_markup=reply_markup
            )
            
            return ConversationHandler.END
    
    async def handle_back_to_edit_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Go back to edit menu"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id in self.user_sessions and 'editing_bot' in self.user_sessions[user_id]:
            bot_name = self.user_sessions[user_id]['editing_bot']
            bot_config = self.user_sessions[user_id].get('bot_config', self.config_manager.get_bot_config(bot_name))
            
            if not bot_config:
                await query.answer("❌ ربات یافت نشد!", show_alert=True)
                return EDIT_BOT_FIELD_SELECT
            
            text = f"✏️ ویرایش ربات: {escape_markdown(bot_name, version=2)}\n\n"
            text += "لطفاً فیلد مورد نظر را انتخاب کنید:\n\n"
            
            keyboard = []
            editable_fields = REQUIRED_FIELDS + OPTIONAL_FIELDS
            
            for field in editable_fields:
                current_value = bot_config.get(field, 'N/A')
                if field == 'token' and current_value != 'N/A':
                    current_value = f"{current_value[:10]}..."  # Show only first 10 chars
                elif field in ['admin_id', 'reports_channel_id', 'webapp_port']:
                    current_value = str(current_value)
                
                field_display = FIELD_NAMES.get(field, field)
                keyboard.append([
                    InlineKeyboardButton(
                        f"{field_display}: {current_value}",
                        callback_data=f"edit_field:{field}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_edit")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self._safe_edit_message(
                query, text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
            return EDIT_BOT_FIELD_SELECT
        
        return await self.handle_edit_bot_menu(update, context)
    
    # ==================== DELETE BOT ====================
    
    async def handle_delete_bot_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show delete bot menu"""
        query = update.callback_query
        await query.answer()
        
        all_bots = self.config_manager.get_all_bots()
        
        if not all_bots:
            text = "❌ هیچ رباتی برای حذف وجود ندارد."
            keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
            return MAIN_MENU
        
        text = "🗑️ حذف ربات\n\nلطفاً ربات مورد نظر را انتخاب کنید:"
        keyboard = []
        
        for bot_name, bot_config in all_bots.items():
            is_active = bot_config.get('is_active', True)
            status = "✅ فعال" if is_active else "❌ غیرفعال"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {bot_name}",
                    callback_data=f"delete_bot:{bot_name}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return DELETE_BOT_CONFIRM
    
    async def handle_delete_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Select bot to delete and show confirmation"""
        query = update.callback_query
        await query.answer()
        
        bot_name = query.data.split(":")[1]
        bot_config = self.config_manager.get_bot_config(bot_name)
        
        if not bot_config:
            await query.answer("❌ ربات یافت نشد!", show_alert=True)
            return DELETE_BOT_CONFIRM
        
        text = (
            f"🗑️ حذف ربات: {bot_name}\n\n"
            f"📱 یوزرنیم: @{bot_config.get('bot_username', 'N/A')}\n"
            f"💾 دیتابیس: {bot_config.get('database_name', 'N/A')}\n\n"
            f"⚠️ آیا مطمئن هستید که می‌خواهید این ربات را غیرفعال کنید؟\n"
            f"این عمل قابل بازگشت است."
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ بله، غیرفعال کن", callback_data=f"delete_confirm:{bot_name}"),
                InlineKeyboardButton("❌ خیر", callback_data="cancel_delete")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return DELETE_BOT_CONFIRM
    
    async def handle_delete_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute bot deletion"""
        query = update.callback_query
        await query.answer()
        
        bot_name = query.data.split(":")[1]
        
        if self.config_manager.delete_bot(bot_name):
            text = (
                f"✅ ربات '{bot_name}' با موفقیت غیرفعال شد\n\n"
                f"💡 می‌توانید بعداً آن را دوباره فعال کنید."
            )
        else:
            text = f"❌ خطا در غیرفعال کردن ربات '{bot_name}'!"
        
        keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
    
    async def handle_cancel_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel deletion"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "❌ عملیات حذف لغو شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
            ]])
        )
        
        return ConversationHandler.END
    
    # ==================== TOGGLE BOT ====================
    
    async def handle_toggle_bot_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show toggle bot menu"""
        query = update.callback_query
        await query.answer()
        
        all_bots = self.config_manager.get_all_bots()
        
        if not all_bots:
            text = "❌ هیچ رباتی وجود ندارد."
            keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
            return MAIN_MENU
        
        text = "🔄 فعال/غیرفعال کردن ربات\n\nلطفاً ربات مورد نظر را انتخاب کنید:"
        keyboard = []
        
        for bot_name, bot_config in all_bots.items():
            is_active = bot_config.get('is_active', True)
            status = "✅ فعال" if is_active else "❌ غیرفعال"
            action = "غیرفعال" if is_active else "فعال"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} → {action}",
                    callback_data=f"toggle_bot:{bot_name}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return TOGGLE_BOT_CONFIRM
    
    async def handle_toggle_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Select bot to toggle and show confirmation"""
        query = update.callback_query
        await query.answer()
        
        bot_name = query.data.split(":")[1]
        bot_config = self.config_manager.get_bot_config(bot_name)
        
        if not bot_config:
            await query.answer("❌ ربات یافت نشد!", show_alert=True)
            return TOGGLE_BOT_CONFIRM
        
        current_status = bot_config.get('is_active', True)
        new_status = not current_status
        status_text = "فعال" if new_status else "غیرفعال"
        current_status_text = "فعال" if current_status else "غیرفعال"
        
        text = (
            f"🔄 تغییر وضعیت ربات: {bot_name}\n\n"
            f"📱 یوزرنیم: @{bot_config.get('bot_username', 'N/A')}\n"
            f"💾 دیتابیس: {bot_config.get('database_name', 'N/A')}\n\n"
            f"وضعیت فعلی: {current_status_text}\n"
            f"وضعیت جدید: {status_text}\n\n"
            f"⚠️ آیا مطمئن هستید؟"
        )
        
        keyboard = [
            [
                InlineKeyboardButton(f"✅ بله، {status_text} کن", callback_data=f"toggle_confirm:{bot_name}"),
                InlineKeyboardButton("❌ خیر", callback_data="cancel_toggle")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return TOGGLE_BOT_CONFIRM
    
    async def handle_toggle_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute toggle bot status"""
        query = update.callback_query
        await query.answer()
        
        bot_name = query.data.split(":")[1]
        bot_config = self.config_manager.get_bot_config(bot_name)
        
        if not bot_config:
            await query.answer("❌ ربات یافت نشد!", show_alert=True)
            return TOGGLE_BOT_CONFIRM
        
        current_status = bot_config.get('is_active', True)
        new_status = not current_status
        
        updates = {'is_active': new_status}
        if self.config_manager.update_bot_config(bot_name, updates):
            status_text = "فعال" if new_status else "غیرفعال"
            text = (
                f"✅ *ربات '{bot_name}' {status_text} شد!*\n\n"
                f"وضعیت قبلی: {'فعال' if current_status else 'غیرفعال'}\n"
                f"وضعیت جدید: {status_text}"
            )
        else:
            text = f"❌ خطا در تغییر وضعیت ربات '{bot_name}'!"
        
        keyboard = [[InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
    
    async def handle_cancel_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel toggle"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "❌ عملیات لغو شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
            ]])
        )
        
        return ConversationHandler.END
    
    # ==================== UTILITY FUNCTIONS ====================
    
    def _format_bot_config_summary(self, bot_name: str, config: Dict) -> str:
        """Format bot configuration as summary text"""
        text = f"📋 خلاصه اطلاعات ربات:\n\n"
        text += f"📝 نام ربات: {bot_name}\n"
        
        for field in REQUIRED_FIELDS:
            value = config.get(field, 'N/A')
            if field == 'token' and value != 'N/A':
                value = f"{value[:10]}..."  # Show only first 10 chars
            text += f"{FIELD_NAMES.get(field, field)}: `{value}`\n"
        
        for field in OPTIONAL_FIELDS:
            if field in config:
                value = config.get(field, 'N/A')
                text += f"{FIELD_NAMES.get(field, field)}: `{value}`\n"
        
        return text
    
    def _format_bot_config_details(self, bot_name: str, config: Dict) -> str:
        """Format bot configuration as detailed text"""
        is_active = config.get('is_active', True)
        status = "✅ فعال" if is_active else "❌ غیرفعال"
        
        text = (
            f"📱 *جزئیات ربات: {bot_name}*\n\n"
            f"📊 وضعیت: {status}\n\n"
        )
        
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if field in config:
                value = config.get(field, 'N/A')
                if field == 'token' and value != 'N/A':
                    value = f"{value[:15]}..."  # Show only first 15 chars
                text += f"{FIELD_NAMES.get(field, field)}: `{value}`\n"
        
        created_at = config.get('created_at', 'N/A')
        updated_at = config.get('updated_at', 'N/A')
        
        text += f"\n📅 تاریخ ایجاد: `{created_at}`\n"
        if updated_at != 'N/A':
            text += f"📅 آخرین به‌روزرسانی: `{updated_at}`\n"
        
        return text
    
    # ==================== CANCEL HANDLERS ====================
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current operation"""
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        
        await update.message.reply_text(
            "❌ عملیات لغو شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
            ]])
        )
        
        return ConversationHandler.END
    
    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cancel callback"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        
        await query.edit_message_text(
            "❌ عملیات لغو شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")
            ]])
        )
        
        return ConversationHandler.END
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        import traceback
        logger.error(f"Exception while handling an update: {context.error}")
        logger.error(f"Update: {update}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        if isinstance(update, Update):
            if update.callback_query:
                try:
                    await update.callback_query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
                except:
                    pass
            elif update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید."
                    )
                except:
                    pass
    
    def run(self):
        """Run the bot"""
        logger.info("Starting Admin Bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Main entry point"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Get admin bot token and admin IDs from environment
    admin_bot_token = os.getenv('ADMIN_BOT_TOKEN')
    admin_ids_str = os.getenv('ADMIN_BOT_ADMIN_IDS', '')
    
    if not admin_bot_token:
        logger.error("ADMIN_BOT_TOKEN must be set in .env file")
        return
    
    # Parse admin IDs
    admin_ids = []
    if admin_ids_str:
        for admin_id_str in admin_ids_str.split(','):
            try:
                admin_ids.append(int(admin_id_str.strip()))
            except ValueError:
                logger.warning(f"Invalid admin ID: {admin_id_str}")
    
    if not admin_ids:
        logger.error("ADMIN_BOT_ADMIN_IDS must be set in .env file with at least one admin ID")
        return
    
    # Create and run bot
    bot = AdminBot(admin_bot_token, admin_ids)
    bot.run()


if __name__ == '__main__':
    main()

