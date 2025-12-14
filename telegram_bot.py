"""
Telegram Bot for 3x-ui Panel Management
Simple bot to create VPN clients and send configurations
"""

import logging
import asyncio
import time
import io
from datetime import datetime, timedelta
import qrcode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
from telegram.helpers import escape_markdown
from panel_manager import PanelManager
from admin_manager import AdminManager
from professional_database import ProfessionalDatabaseManager
from payment_system import PaymentManager
from button_layout import ProfessionalButtonLayout as ButtonLayout
from username_formatter import UsernameFormatter
from message_templates import MessageTemplates
from reporting_system import ReportingSystem
from statistics_system import StatisticsSystem
# Payment callback removed
from config import BOT_CONFIG, CLIENT_DEFAULTS, DEFAULT_PANEL_CONFIG, WEBAPP_CONFIG
from traffic_monitor import TrafficMonitor
from persian_datetime import PersianDateTime, format_db_datetime, format_db_date
from user_info_updater import auto_update_user_info, ensure_user_updated
from user_info_updater import auto_update_user_info, ensure_user_updated
from channel_checker import require_channel_membership, check_channel_membership, show_force_join_message
from system_manager import SystemManager

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

from telegram.request import HTTPXRequest

import httpx

# Monkeypatch httpx.AsyncClient to force disable proxies
original_async_client_init = httpx.AsyncClient.__init__

def patched_async_client_init(self, *args, **kwargs):
    kwargs['proxy'] = None
    kwargs['trust_env'] = False
    if 'proxies' in kwargs:
        del kwargs['proxies']
    original_async_client_init(self, *args, **kwargs)

httpx.AsyncClient.__init__ = patched_async_client_init

class NoProxyRequest(HTTPXRequest):
    """Custom Request class that ignores system proxies"""
    def __init__(self, *args, **kwargs):
        httpx_kwargs = kwargs.get('httpx_kwargs', {})
        httpx_kwargs['trust_env'] = False
        httpx_kwargs['proxy'] = None
        kwargs['httpx_kwargs'] = httpx_kwargs
        super().__init__(*args, **kwargs)

class VPNBot:
    def __init__(self, bot_config=None, db=None, starsefar_config=None, callback_port=4000):
        """
        Initialize VPN Bot
        
        Args:
            bot_config: Bot configuration dict (if None, uses BOT_CONFIG from config)
            db: Database manager instance (if None, creates new one)
            starsefar_config: StarsOffer configuration dict (if None, uses STARSEFAR_CONFIG from config)
            callback_port: Port for payment callback server
        """
        # Store configs
        if bot_config is None:
            from config import BOT_CONFIG
            self.bot_config = BOT_CONFIG.copy()
        else:
            self.bot_config = bot_config.copy()
            
        # Ensure webapp_url is set in bot_config
        if 'webapp_url' not in self.bot_config or not self.bot_config['webapp_url']:
            from config import WEBAPP_CONFIG
            self.bot_config['webapp_url'] = WEBAPP_CONFIG['url']
            logger.info(f"✅ Set webapp_url from config: {self.bot_config['webapp_url']}")
            
        self.bot_username = self.bot_config.get('bot_username', '')
        
        # Payment config removed
        self.starsefar_config = {}
            
        self.callback_port = callback_port
        
        # Initialize database
        if db is None:
            self.db = ProfessionalDatabaseManager()
        else:
            self.db = db
            
        self.system_manager = None
        
        self.panel_manager = PanelManager()
        self.user_sessions = {}  # Store user session data
        
        # Initialize admin manager with correct database
        self.admin_manager = AdminManager(self.db)
        
        # Initialize payment system
        # Payment gateway removed as per request
        self.starsefar_api = None
        self.payment_manager = PaymentManager(self.db, None)
        
        # Payment callback server removed
        
        # Initialize traffic monitor (will be set later in main)
        self.traffic_monitor = None
        
        # Initialize reporting system (will be set later in main)
        self.reporting_system = None
        self.statistics_system = None
        
        # Initialize TextManager for customizable texts
        try:
            from text_manager import TextManager
            self.text_manager = TextManager(self.db)
            # Set TextManager in MessageTemplates for global access
            MessageTemplates.set_text_manager(self.text_manager)
            # Also set database name in thread-local storage for this bot instance
            MessageTemplates.set_database_name(self.db.database_name)
            logger.info(f"✅ TextManager initialized successfully for database: {self.db.database_name}")
            
            # Test: Try to get a text from database to verify it works
            try:
                test_text = self.text_manager.get_text('welcome.main', use_default_if_missing=True)
                if test_text:
                    logger.info(f"✅ TextManager test successful - loaded text 'welcome.main' (length: {len(test_text)})")
                else:
                    logger.warning("⚠️ TextManager test: Could not load text 'welcome.main'")
            except Exception as test_e:
                logger.warning(f"⚠️ TextManager test failed: {test_e}")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize TextManager: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.text_manager = None
        
    async def process_user_registration_with_referral(self, user_id: int, user, context: ContextTypes.DEFAULT_TYPE, referral_code: str = None):
        """
        Process user registration with referral code support
        This is a helper function that can be called from start_command or check_channel_join callback
        """
        from config import REFERRAL_CONFIG, BOT_MESSAGES
        
        # Check if user already exists
        existing_user = self.db.get_user(user_id)
        if existing_user:
            # User already exists, just update activity and user info
            self.db.update_user_activity(user_id)
            # Update user info in case it changed
            self.db.update_user_info(
                user_id,
                user.username,
                user.first_name,
                user.last_name
            )
            
            # IMPORTANT: Check if user has a referral code but hasn't been referred yet
            # If they came with a referral code, we should still process it if they don't have a referrer
            if referral_code and not existing_user.get('referred_by'):
                referrer = self.db.get_user_by_referral_code(referral_code)
                if referrer and referrer['id'] != existing_user['id']:
                    # User came with referral code but wasn't referred before
                    # Update the user's referred_by field
                    referrer_id = referrer['id']
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('UPDATE users SET referred_by = %s WHERE id = %s', (referrer_id, existing_user['id']))
                        conn.commit()
                    
                    # Process referral reward
                    referral_reward = REFERRAL_CONFIG.get('reward_amount', 3000)
                    referral_id = self.db.add_referral(referrer_id, existing_user['id'], referral_reward)
                    
                    if referral_id:
                        # Give reward to referrer
                        referrer_user = self.db.get_user_by_id(referrer_id)
                        if referrer_user:
                            self.db.update_user_balance(
                                referrer_user['telegram_id'], 
                                referral_reward, 
                                'referral_reward', 
                                f'پاداش معرفی کاربر {user.first_name or user_id}'
                            )
                            
                            # Mark as paid
                            self.db.pay_referral_reward(referral_id)
                            
                            # Update stats
                            self.db.update_user_referral_stats(referrer_id, referral_reward)
                            
                            # Send notification to referrer
                            try:
                                reward_message = BOT_MESSAGES['referral_reward_notification'].format(amount=referral_reward)
                                await context.bot.send_message(
                                    chat_id=referrer_user['telegram_id'],
                                    text=reward_message
                                )
                            except:
                                pass
                            
                            logger.info(f"✅ Processed late referral for existing user {user_id} referred by {referrer_id}")
            
            logger.info(f"User {user_id} already exists, skipping registration")
            return False
        
        # Generate unique referral code for new user
        new_referral_code = self.db.generate_referral_code()
        
        # Check if referred by someone
        referrer_id = None
        if referral_code:
            referrer = self.db.get_user_by_referral_code(referral_code)
            if referrer and referrer.get('id') != user_id:  # Can't refer yourself
                referrer_id = referrer['id']
                logger.info(f"✅ User {user_id} referred by {referrer_id} with code {referral_code}")
        
        # Add user and get database ID
        new_user_db_id = self.db.add_user(
            telegram_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_admin=((user_id == self.bot_config['admin_id']) or self.db.is_admin(user_id)),
            referred_by=referrer_id,
            referral_code=new_referral_code
        )
        
        # Get welcome bonus from config
        welcome_bonus = REFERRAL_CONFIG.get('welcome_bonus', 1000)
        
        # Add welcome bonus
        if welcome_bonus > 0:
            self.db.update_user_balance(
                user_id, 
                welcome_bonus, 
                'welcome_bonus', 
                'هدیه ثبت نام'
            )
            
            # Invalidate cache for new user
            try:
                from cache_utils import invalidate_user_cache
                invalidate_user_cache(user_id)
            except ImportError:
                pass  # Cache utils not available
            
            # Send notification about welcome bonus
            bonus_message = BOT_MESSAGES['welcome_bonus_notification'].format(amount=welcome_bonus)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 {bonus_message}"
                )
            except:
                pass
        
        # Process referral reward
        if referrer_id and new_user_db_id:
            referral_reward = REFERRAL_CONFIG.get('reward_amount', 3000)
            
            # Add referral record (use database IDs, not telegram IDs)
            referral_id = self.db.add_referral(referrer_id, new_user_db_id, referral_reward)
            
            if referral_id:
                # Give reward to referrer
                referrer_user = self.db.get_user_by_id(referrer_id)
                if referrer_user:
                    self.db.update_user_balance(
                        referrer_user['telegram_id'], 
                        referral_reward, 
                        'referral_reward', 
                        f'پاداش معرفی کاربر {user.first_name or user_id}'
                    )
                    
                    # Invalidate cache for referrer
                    try:
                        from cache_utils import invalidate_user_cache
                        invalidate_user_cache(referrer_user['telegram_id'])
                    except ImportError:
                        pass  # Cache utils not available
                    
                    # Mark as paid
                    self.db.pay_referral_reward(referral_id)
                    
                    # Update stats
                    self.db.update_user_referral_stats(referrer_id, referral_reward)
                    
                    # Send notification to referrer
                    try:
                        reward_message = BOT_MESSAGES['referral_reward_notification'].format(amount=referral_reward)
                        await context.bot.send_message(
                            chat_id=referrer_user['telegram_id'],
                            text=reward_message
                        )
                    except:
                        pass
        
        # Report new user registration
        if self.reporting_system:
            user_data = {
                'telegram_id': user_id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'welcome_bonus': welcome_bonus,
                'referral_reward': REFERRAL_CONFIG.get('reward_amount', 3000) if referrer_id else 0
            }
            # Get referrer data if exists
            referrer_user_data = None
            if referrer_id:
                referrer_user_data = self.db.get_user_by_id(referrer_id)
            
            await self.reporting_system.report_user_registration(user_data, referrer_user_data)
        
        return True
        
    @auto_update_user_info
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with referral support"""
        user_id = update.effective_user.id
        user = update.effective_user
        
        # IMPORTANT: Extract referral code BEFORE checking channel membership
        # This ensures we don't lose the referral code if user is not a member
        referral_code = None
        if context.args and len(context.args) > 0:
            referral_code = context.args[0].strip() if context.args[0] else None
            # Validate referral code (should not be empty, None, or invalid)
            if referral_code and referral_code.lower() != 'none' and len(referral_code) > 0:
                # Store referral code in user_data for later use if user is not a member
                # context.user_data is a dict-like object that persists per user
                context.user_data['pending_referral_code'] = referral_code
                logger.info(f"📝 Stored referral code for user {user_id}: {referral_code}")
            else:
                referral_code = None
                logger.warning(f"⚠️ Invalid referral code received for user {user_id}: {context.args[0]}")
        
        # Check channel membership (except for admin)
        if user_id != self.bot_config['admin_id']:
            is_member = await check_channel_membership(update, context, bot_config=self.bot_config)
            if not is_member:
                await show_force_join_message(update, context, bot_config=self.bot_config)
                return
        
        # Process user registration with referral code (if new user)
        # For existing users, this will just update activity
        is_new_user = await self.process_user_registration_with_referral(user_id, user, context, referral_code)
        
        # Clear stored referral code after processing (whether new user or existing)
        if 'pending_referral_code' in context.user_data:
            del context.user_data['pending_referral_code']
            logger.info(f"🗑️ Cleared stored referral code for user {user_id}")
        
        # Check if user is admin - check both database and config
        # First check if user_id matches admin_id from config
        is_admin_by_config = (user_id == self.bot_config['admin_id'])
        # Also check database
        is_admin_by_db = self.db.is_admin(user_id)
        # User is admin if either condition is true
        is_admin = is_admin_by_config or is_admin_by_db
        
        # If user is admin by config but not in database, update database
        if is_admin_by_config and not is_admin_by_db:
            # Update user's is_admin flag in database
            try:
                user_data = self.db.get_user(user_id)
                if user_data:
                    # Update is_admin flag
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('UPDATE users SET is_admin = 1 WHERE telegram_id = %s', (user_id,))
                        conn.commit()
                        cursor.close()
                        logger.info(f"Updated is_admin flag for user {user_id} in database")
            except Exception as e:
                logger.error(f"Error updating is_admin flag: {e}")
        
        logger.info(f"User {user_id} is admin: {is_admin} (by config: {is_admin_by_config}, by db: {is_admin_by_db}), Admin ID: {self.bot_config['admin_id']}")
        
        # Also check user data from database
        user_data = self.db.get_user(user_id)
        if user_data:
            logger.info(f"User data from DB: {user_data}")
        else:
            logger.info("No user data found in database")
        
        # Get user data for personalized welcome
        user_data = self.db.get_user(user_id)
        # Ensure database name is set in thread-local storage for this bot instance
        MessageTemplates.set_database_name(self.db.database_name)
        
        bot_name = self.bot_config.get('bot_name', '')
        welcome_text = MessageTemplates.format_welcome_message(
            user_data or {}, is_admin, bot_name=bot_name
        )
        
        # Create professional main menu
        # Get webapp URL with bot name prefix
        base_url = self.bot_config.get('webapp_url', 'http://localhost:443')
        
        # 1. Main Menu (Reply Keyboard)
        reply_markup = ButtonLayout.create_main_menu(
            is_admin=is_admin,
            user_balance=user_data.get('balance', 0) if user_data else 0,
            user_id=user_id,
            webapp_url=base_url,
            bot_name=bot_name,
            db=self.db
        )
        
        # 2. Web App Button (Inline Keyboard)
        webapp_markup = ButtonLayout.create_webapp_keyboard(
            webapp_url=base_url,
            bot_name=bot_name
        )
        
        # Send welcome message with Reply Keyboard (Main Menu)
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Send Web App button separately
        await update.message.reply_text(
            "🌐 **ورود به پنل کاربری پیشرفته (وب اپلیکیشن)** 👇",
            reply_markup=webapp_markup,
            parse_mode='Markdown'
        )
    
    async def myid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user ID for web app login"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "بدون نام کاربری"
        first_name = update.effective_user.first_name or ""
        
        # Get webapp URL from environment or database
        import os
        # Get webapp URL from bot config (with bot name prefix)
        base_url = self.bot_config.get('webapp_url', 'http://localhost:443')
        # Remove trailing slash if exists
        base_url = base_url.rstrip('/')
        # Get bot name from config
        bot_name = self.bot_config.get('bot_name', '')
        webapp_url = f"{base_url}/{bot_name}" if bot_name else base_url
        
        message = f"""
🆔 **اطلاعات حساب شما**

👤 **نام:** {first_name}
📝 **نام کاربری:** @{username}
🔢 **شناسه کاربری:** `{user_id}`

🌐 **ورود به وب‌اپلیکیشن:**

**مرحله 1:** به آدرس زیر بروید
{webapp_url}

**مرحله 2:** شناسه کاربری خود را وارد کنید
`{user_id}`

**مرحله 3:** وارد پنل شوید!

💡 **نکته:** شناسه را کپی کنید و در وب‌اپ وارد کنید
        """
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
📖 **راهنمای کامل استفاده از ربات**

**🎯 مراحل خرید و استفاده از سرویس:**

**1️⃣ افزایش موجودی:**
• از منوی اصلی گزینه "💰 موجودی" را انتخاب کنید
• روی "افزایش موجودی" کلیک کنید
• مبلغ دلخواه را انتخاب کنید
• پرداخت را از طریق درگاه بانکی تکمیل کنید

**2️⃣ خرید سرویس VPN:**
• از منوی اصلی گزینه "🛒 خرید سرویس" را انتخاب کنید
• پنل مورد نظر را انتخاب کنید
• حجم دلخواه (گیگابایت) را انتخاب کنید
• روش پرداخت را انتخاب کنید (موجودی یا آنلاین)

**3️⃣ دریافت کانفیگ:**
• به "📊 داشبورد کاربری" بروید
• سرویس خریداری شده را انتخاب کنید
• روی "📋 دریافت کانفیگ" کلیک کنید
• کانفیگ را در برنامه VPN خود وارد کنید

**📱 نرم‌افزارهای پیشنهادی:**
• **اندروید:** v2rayNG
• **iOS:** Shadowrocket, Fair VPN
• **ویندوز:** v2rayN, Nekoray
• **مک:** V2RayX

**🔧 مدیریت سرویس:**
• مشاهده وضعیت سرویس
• تمدید سرویس (افزودن حجم)
• دریافت مجدد کانفیگ
• حذف سرویس

**💡 نکات مهم:**
• همیشه قبل از خرید موجودی کافی داشته باشید
• برای تمدید سرویس به پنل کاربری مراجعه کنید
• در صورت هر مشکلی با پشتیبانی تماس بگیرید

**📞 پشتیبانی:**
• برای راهنمایی بیشتر از دکمه "❓ راهنما" استفاده کنید
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    
    async def show_inbounds(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available inbounds - ADMIN ONLY"""
        user_id = update.effective_user.id
        
        # Only allow admin access
        if user_id != self.bot_config['admin_id']:
            error_text = "❌ این بخش فقط برای مدیر سیستم قابل دسترسی است.\n\n💡 برای خرید سرویس از منوی 🛒 خرید سرویس استفاده کنید."
            query = update.callback_query
            if query:
                await query.answer()
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
            return
        
        query = update.callback_query
        if query:
            await query.answer()
        
        # Try to login and get inbounds
        if not self.panel_manager.login():
            error_text = "❌ خطا در اتصال به پنل. لطفاً بعداً تلاش کنید."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
            return
        
        inbounds = self.panel_manager.get_inbounds()
        
        if not inbounds:
            no_inbounds_text = "❌ هیچ اینباندی یافت نشد."
            if query:
                await query.edit_message_text(no_inbounds_text)
            else:
                await update.message.reply_text(no_inbounds_text)
            return
        
        # Create keyboard with inbounds
        keyboard = []
        for inbound in inbounds:
            inbound_id = inbound.get('id', 0)
            inbound_name = inbound.get('remark', f'Inbound {inbound_id}')
            inbound_protocol = inbound.get('protocol', 'unknown')
            inbound_port = inbound.get('port', 0)
            
            button_text = f"🔗 {inbound_name} ({inbound_protocol}:{inbound_port})"
            keyboard.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"select_inbound_{inbound_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="show_inbounds")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        inbounds_text = f"📋 **اینباندهای موجود ({len(inbounds)} عدد):**\n\n"
        for i, inbound in enumerate(inbounds, 1):
            inbound_name = inbound.get('remark', f'Inbound {inbound.get("id", 0)}')
            inbound_protocol = inbound.get('protocol', 'unknown')
            inbound_port = inbound.get('port', 0)
            inbound_status = "🟢 فعال" if inbound.get('enable', False) else "🔴 غیرفعال"
            
            inbounds_text += f"{i}. **{inbound_name}**\n"
            inbounds_text += f"   پروتکل: `{inbound_protocol}`\n"
            inbounds_text += f"   پورت: `{inbound_port}`\n"
            inbounds_text += f"   وضعیت: {inbound_status}\n\n"
        
        if query:
            await query.edit_message_text(
                inbounds_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                inbounds_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    @auto_update_user_info
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        logger.info(f"Received callback data: {data}")
        
        # Check channel membership for all callbacks except check_channel_join itself
        if data != "check_channel_join":
            is_member = await check_channel_membership(update, context, bot_config=self.bot_config)
            if not is_member:
                await show_force_join_message(update, context, bot_config=self.bot_config)
                return
        
        try:
            if data == "check_channel_join":
                # Re-check membership
                is_member = await check_channel_membership(update, context, bot_config=self.bot_config)
                if is_member:
                    # User is now a member, process registration with stored referral code
                    user_id = update.effective_user.id
                    user = update.effective_user
                    
                    # Check if user already exists (to avoid duplicate registration)
                    existing_user = self.db.get_user(user_id)
                    is_already_registered = existing_user is not None
                    
                    # Get stored referral code from user_data
                    stored_referral_code = None
                    if context.user_data and 'pending_referral_code' in context.user_data:
                        stored_referral_code = context.user_data['pending_referral_code']
                        logger.info(f"📝 Processing stored referral code for user {user_id}: {stored_referral_code}")
                        # Clear stored referral code after use
                        del context.user_data['pending_referral_code']
                    
                    # Process user registration with referral code (only if not already registered)
                    if not is_already_registered:
                        await self.process_user_registration_with_referral(user_id, user, context, stored_referral_code)
                    else:
                        logger.info(f"User {user_id} already registered, skipping registration but processing referral if needed")
                        # If user already exists but has a stored referral code, we still need to check
                        # But since they're already registered, we can't process new referral
                        # (Referrals are only processed during initial registration)
                    
                    # Show success message and main menu
                    user_data = self.db.get_user(user_id)
                    # Check if user is admin - check both database and config
                    is_admin_by_config = (user_id == self.bot_config['admin_id'])
                    is_admin_by_db = self.db.is_admin(user_id)
                    is_admin = is_admin_by_config or is_admin_by_db
                    # Ensure database name is set in thread-local storage
                    MessageTemplates.set_database_name(self.db.database_name)
                    welcome_text = MessageTemplates.format_welcome_message(
                        user_data or {}, is_admin
                    )
                    
                    # Get webapp URL with bot name prefix
                    base_url = self.bot_config.get('webapp_url', 'http://localhost:443')
                    bot_name = self.bot_config.get('bot_name', '')
                    
                    reply_markup = ButtonLayout.create_main_menu(
                        is_admin=is_admin,
                        user_balance=user_data.get('balance', 0) if user_data else 0,
                        user_id=user_id,
                        webapp_url=base_url,
                        bot_name=bot_name,
                        db=self.db
                    )
                    
                    webapp_markup = ButtonLayout.create_webapp_keyboard(
                        webapp_url=base_url,
                        bot_name=bot_name
                    )
                    
                    # Delete the "Check Join" message
                    try:
                        await query.delete_message()
                    except:
                        pass
                    
                    # Send welcome message with Reply Keyboard
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ تبریک! شما با موفقیت عضو کانال شدید.\n\n{welcome_text}",
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                    
                    # Send Web App button
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="🌐 **ورود به پنل کاربری پیشرفته (وب اپلیکیشن)** 👇",
                        reply_markup=webapp_markup,
                        parse_mode='Markdown'
                    )

                else:
                    # User is not a member yet
                    await show_force_join_message(update, context, bot_config=self.bot_config)
                return
            elif data == "show_inbounds":
                await self.show_inbounds(update, context)
            elif data == "help":
                await self.show_help(update, context)
            elif data == "main_menu":
                await self.show_main_menu(update, context)
            elif data == "custom_balance":
                await self.handle_custom_balance_input(update, context)
            elif data.startswith("custom_volume_"):
                panel_id = int(data.split("_")[2])
                await self.handle_custom_volume_input(update, context, panel_id)
            elif data.startswith("custom_add_volume_"):
                parts = data.split("_")
                service_id = int(parts[3])
                panel_id = int(parts[4])
                context.user_data['add_volume_service_id'] = service_id
                await self.handle_custom_volume_input(update, context, panel_id)
            elif data.startswith("enter_discount_code_add_volume_"):
                parts = data.split("_")
                service_id = int(parts[5])
                panel_id = int(parts[6])
                volume_gb = int(parts[7])
                price = int(parts[8])
                await self.handle_enter_discount_code_add_volume(update, context, service_id, panel_id, volume_gb, price)
            elif data.startswith("continue_without_discount_add_volume_"):
                parts = data.split("_")
                service_id = int(parts[4])
                panel_id = int(parts[5])
                volume_gb = int(parts[6])
                price = int(parts[7])
                await self.handle_continue_without_discount_add_volume(update, context, service_id, panel_id, volume_gb, price)
            elif data.startswith("select_volume_"):
                parts = data.split("_")
                panel_id = int(parts[2])
                volume_gb = int(parts[3])
                await self.handle_volume_selection(update, context, panel_id, volume_gb)
            elif data.startswith("enter_discount_code_renew_"):
                parts = data.split("_")
                panel_id = int(parts[4])
                gb_amount = int(parts[5])
                context.user_data['renewing_service'] = True
                await self.handle_enter_discount_code(update, context, panel_id, gb_amount)
            elif data.startswith("continue_without_discount_renew_"):
                parts = data.split("_")
                panel_id = int(parts[4])
                gb_amount = int(parts[5])
                context.user_data['renewing_service'] = True
                await self.handle_continue_without_discount(update, context, panel_id, gb_amount)
            elif data.startswith("enter_discount_code_volume_"):
                parts = data.split("_")
                panel_id = int(parts[4])
                volume_gb = int(parts[5])
                price = int(parts[6])
                await self.handle_enter_discount_code_volume(update, context, panel_id, volume_gb, price)
            elif data.startswith("continue_without_discount_volume_"):
                parts = data.split("_")
                panel_id = int(parts[4])
                volume_gb = int(parts[5])
                price = int(parts[6])
                await self.handle_continue_without_discount_volume(update, context, panel_id, volume_gb, price)
            elif data.startswith("enter_discount_code_"):
                parts = data.split("_")
                panel_id = int(parts[3])
                gb_amount = int(parts[4])
                await self.handle_enter_discount_code(update, context, panel_id, gb_amount)
            elif data.startswith("continue_without_discount_product_"):
                parts = data.split("_")
                product_id = int(parts[4])
                await self.handle_continue_without_discount_product(update, context, product_id)
            elif data.startswith("continue_without_discount_"):
                parts = data.split("_")
                panel_id = int(parts[3])
                gb_amount = int(parts[4])
                await self.handle_continue_without_discount(update, context, panel_id, gb_amount)
            elif data == "financial_management":
                await self.show_financial_management(update, context)
            elif data == "card_settings":
                await self.show_card_settings(update, context)
            elif data == "set_card_number":
                await self.prompt_card_number(update, context)
            elif data == "set_card_owner":
                await self.prompt_card_owner(update, context)
            elif data.startswith("pay_card_"):
                invoice_id = int(data.split("_")[2])
                await self.show_card_payment(update, context, invoice_id)
            elif data.startswith("approve_receipt_"):
                invoice_id = int(data.split("_")[2])
                await self.handle_approve_receipt(update, context, invoice_id)
            elif data.startswith("reject_receipt_"):
                invoice_id = int(data.split("_")[2])
                await self.handle_reject_receipt(update, context, invoice_id)
            elif data.startswith("apply_discount_"):
                parts = data.split("_")
                panel_id = int(parts[2])
                gb_amount = int(parts[3])
                await self.handle_enter_discount_code(update, context, panel_id, gb_amount)
            elif data.startswith("add_balance_"):
                amount = int(data.split("_")[2])
                await self.handle_balance_amount_selection(update, context, amount)
            elif data == "payment_minimum_error":
                await query.edit_message_text(
                    "❌ حداقل مبلغ برای پرداخت آنلاین 10,000 تومان است.\n\n"
                    "برای مبالغ کمتر از 10,000 تومان، لطفاً از موجودی حساب خود استفاده کنید."
                )
            elif data.startswith("select_inbound_panel_"):
                parts = data.split("_")
                logger.info(f"Select inbound panel callback - parts: {parts}")
                # select_inbound_panel_2_1 -> ['select', 'inbound', 'panel', '2', '1']
                if len(parts) >= 5 and parts[3].isdigit() and parts[4].isdigit():
                    panel_id = int(parts[3])
                    inbound_id = int(parts[4])
                    logger.info(f"Selecting inbound - Panel ID: {panel_id}, Inbound ID: {inbound_id}")
                    await self.select_inbound_for_purchase(update, context, panel_id, inbound_id)
                else:
                    logger.error(f"Invalid select_inbound_panel callback data: {data}, parts: {parts}")
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("create_client_panel_"):
                parts = data.split("_")
                logger.info(f"Create client panel callback - parts: {parts}")
                # create_client_panel_2_1 -> ['create', 'client', 'panel', '2', '1']
                if len(parts) >= 5 and parts[3].isdigit() and parts[4].isdigit():
                    panel_id = int(parts[3])
                    inbound_id = int(parts[4])
                    logger.info(f"Creating client - Panel ID: {panel_id}, Inbound ID: {inbound_id}")
                    await self.create_client_prompt_panel(update, context, panel_id, inbound_id)
                else:
                    logger.error(f"Invalid create_client_panel callback data: {data}, parts: {parts}")
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("select_inbound_for_panel_"):
                inbound_id = int(data.split("_")[4])
                await self.handle_inbound_selection_for_panel(update, context, inbound_id)
            elif data.startswith("select_inbound_"):
                # Only admin can select inbounds directly (non-payment flow)
                user_id = update.effective_user.id
                if user_id != self.bot_config['admin_id']:
                    await query.edit_message_text("❌ دسترسی غیرمجاز. لطفاً از بخش خرید سرویس استفاده کنید.")
                    return
                inbound_id = int(data.split("_")[2])
                await self.select_inbound(update, context, inbound_id)
            elif data.startswith("create_client_"):
                # Only admin can create clients directly without payment
                user_id = update.effective_user.id
                if user_id != self.bot_config['admin_id']:
                    await query.edit_message_text("❌ دسترسی غیرمجاز. برای خرید سرویس از منوی اصلی استفاده کنید.")
                    return
                inbound_id = int(data.split("_")[2])
                await self.create_client_prompt(update, context, inbound_id)
            elif data.startswith("quick_create_"):
                # Only admin can quick create clients without payment
                user_id = update.effective_user.id
                if user_id != self.bot_config['admin_id']:
                    await query.edit_message_text("❌ دسترسی غیرمجاز. برای خرید سرویس از منوی اصلی استفاده کنید.")
                    return
                inbound_id = int(data.split("_")[2])
                await self.handle_quick_create(update, context, inbound_id)
            elif data.startswith("advanced_settings_"):
                inbound_id = int(data.split("_")[2])
                await self.handle_advanced_settings(update, context, inbound_id)
            elif data.startswith("confirm_create_"):
                parts = data.split("_")
                inbound_id = int(parts[2])
                client_name = parts[3]
                await self.create_client(update, context, inbound_id, client_name)
            elif data == "referral_system":
                await self.handle_referral_system(update, context)
            elif data == "admin_discount_codes_list":
                await self.handle_admin_discount_codes_list(update, context)
            elif data == "admin_gift_codes_list":
                await self.handle_admin_gift_codes_list(update, context)
            elif data.startswith("admin_discount_codes"):
                await self.handle_admin_discount_codes_menu(update, context)
            elif data.startswith("discount_create_"):
                await self.handle_create_discount_code(update, context, data.split("_")[2])
            elif data.startswith("discount_delete_"):
                await self.handle_delete_discount_code(update, context, int(data.split("_")[2]))
            elif data.startswith("discount_toggle_"):
                await self.handle_toggle_discount_code(update, context, int(data.split("_")[2]))
            elif data.startswith("discount_view_"):
                await self.handle_view_discount_code(update, context, int(data.split("_")[2]))
            elif data.startswith("gift_create_"):
                await self.handle_create_gift_code(update, context, data.split("_")[2])
            elif data.startswith("gift_delete_"):
                await self.handle_delete_gift_code(update, context, int(data.split("_")[2]))
            elif data.startswith("gift_toggle_"):
                await self.handle_toggle_gift_code(update, context, int(data.split("_")[2]))
            elif data.startswith("gift_view_"):
                await self.handle_view_gift_code(update, context, int(data.split("_")[2]))
            elif data == "manage_products":
                await self.handle_manage_products_menu(update, context)
            elif data == "manage_categories":
                await self.handle_manage_categories(update, context)
            elif data == "manage_products_list":
                await self.handle_manage_products_list(update, context)
            elif data.startswith("panel_categories_"):
                panel_id = int(data.split("_")[2])
                await self.handle_panel_categories(update, context, panel_id)
            elif data.startswith("add_category_"):
                panel_id = int(data.split("_")[2])
                await self.handle_add_category_start(update, context, panel_id)
            elif data.startswith("edit_category_"):
                category_id = int(data.split("_")[2])
                await self.handle_edit_category(update, context, category_id)
            elif data.startswith("category_edit_name_"):
                category_id = int(data.split("_")[3])
                await self.handle_category_edit_name(update, context, category_id)
            elif data.startswith("category_toggle_"):
                category_id = int(data.split("_")[2])
                await self.handle_category_toggle(update, context, category_id)
            elif data.startswith("category_delete_"):
                category_id = int(data.split("_")[2])
                await self.handle_category_delete(update, context, category_id)
            elif data.startswith("confirm_category_delete_"):
                category_id = int(data.split("_")[3])
                await self.handle_confirm_category_delete(update, context, category_id)
            elif data.startswith("panel_products_"):
                panel_id = int(data.split("_")[2])
                await self.handle_panel_products(update, context, panel_id)
            elif data.startswith("buy_products_no_category_"):
                panel_id = int(data.split("_")[4])
                await self.handle_show_products_for_purchase_no_category(update, context, panel_id)
            elif data.startswith("products_no_category_"):
                panel_id = int(data.split("_")[3])
                await self.handle_products_no_category(update, context, panel_id)
            elif data.startswith("category_products_"):
                category_id = int(data.split("_")[2])
                await self.handle_category_products(update, context, category_id)
            elif data.startswith("add_product_"):
                parts = data.split("_")
                if len(parts) == 3:
                    panel_id = int(parts[2])
                    category_id = None
                else:
                    panel_id = int(parts[2])
                    category_id = int(parts[3])
                await self.handle_add_product_start(update, context, panel_id, category_id)
            elif data.startswith("edit_product_"):
                product_id = int(data.split("_")[2])
                await self.handle_edit_product(update, context, product_id)
            elif data.startswith("product_edit_"):
                parts = data.split("_")
                product_id = int(parts[2])
                field = parts[3]
                await self.handle_product_edit_field(update, context, product_id, field)
            elif data.startswith("product_toggle_"):
                product_id = int(data.split("_")[2])
                await self.handle_product_toggle(update, context, product_id)
            elif data.startswith("product_delete_"):
                product_id = int(data.split("_")[2])
                await self.handle_product_delete(update, context, product_id)
            elif data.startswith("confirm_product_delete_"):
                product_id = int(data.split("_")[3])
                await self.handle_confirm_product_delete(update, context, product_id)
            elif data == "admin_panel":
                await self.handle_admin_panel(update, context)
            elif data == "system_settings":
                await self.handle_system_settings(update, context)
            elif data == "system_logs":
                await self.handle_system_action(update, context, "logs")
            elif data.startswith("sys_"):
                await self.handle_system_action(update, context, data.split("_")[1])
            elif data == "admin_stats":
                await self.handle_admin_stats(update, context)
            elif data == "stats_users":
                await self.handle_stats_users(update, context)
            elif data.startswith("stats_all_users_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_all_users(update, context, page)
            elif data.startswith("stats_active_users_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_active_users(update, context, page)
            elif data == "stats_services":
                await self.handle_stats_services(update, context)
            elif data.startswith("stats_all_services_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_all_services(update, context, page)
            elif data.startswith("stats_active_services_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_active_services(update, context, page)
            elif data.startswith("stats_disabled_services_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_disabled_services(update, context, page)
            elif data == "stats_payments":
                await self.handle_stats_payments(update, context)
            elif data.startswith("stats_recent_payments_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_recent_payments(update, context, page)
            elif data == "stats_revenue":
                await self.handle_stats_revenue(update, context)
            elif data.startswith("stats_recent_orders_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_recent_orders(update, context, page)
            elif data == "stats_online":
                await self.handle_stats_online(update, context)
            elif data == "stats_lists":
                await self.handle_stats_lists(update, context)
            elif data.startswith("stats_new_users_"):
                page = int(data.split("_")[-1])
                await self.handle_stats_new_users(update, context, page)
            elif data == "broadcast_menu":
                await self.handle_broadcast_menu(update, context)
            elif data == "broadcast_message_request":
                await self.handle_broadcast_message_request(update, context)
            elif data == "broadcast_forward_request":
                await self.handle_broadcast_forward_request(update, context)
            elif data == "confirm_broadcast_message":
                await self.confirm_broadcast_message(update, context)
            elif data == "confirm_broadcast_forward":
                await self.confirm_broadcast_forward(update, context)
            elif data == "user_services_menu":
                await self.handle_user_services_menu(update, context)
            elif data == "user_info_request":
                await self.handle_user_info_request(update, context)
            elif data == "gift_all_users_request":
                await self.handle_gift_all_users_request(update, context)
            elif data.startswith("confirm_gift_all_"):
                gift_amount = int(data.split("_")[3])
                await self.handle_confirm_gift_all_users(update, context, gift_amount)
            elif data == "get_test_account":
                await self.handle_get_test_account(update, context)
            elif data.startswith("user_add_balance_"):
                await self.handle_user_add_balance_request(update, context)
            elif data.startswith("user_decrease_balance_"):
                await self.handle_user_decrease_balance_request(update, context)
            elif data.startswith("user_services_"):
                await self.handle_user_services_view(update, context)
            elif data.startswith("user_transactions_"):
                await self.handle_user_transactions_view(update, context)
            elif data.startswith("user_info_show_"):
                await self.handle_user_info_show(update, context)
            elif data == "manage_admins":
                await self.handle_manage_admins(update, context)
            elif data == "add_admin":
                await self.handle_add_admin_request(update, context)
            elif data.startswith("admin_detail_"):
                admin_telegram_id = int(data.split("_")[2])
                await self.handle_admin_detail(update, context, admin_telegram_id)
            elif data.startswith("admin_toggle_"):
                admin_telegram_id = int(data.split("_")[2])
                await self.handle_admin_toggle(update, context, admin_telegram_id)
            elif data.startswith("admin_delete_"):
                admin_telegram_id = int(data.split("_")[2])
                await self.handle_admin_delete(update, context, admin_telegram_id)
            elif data.startswith("admin_manage_service_"):
                await self.handle_admin_manage_service(update, context)
            elif data == "migrate_panel_start":
                await self.start_migrate_panel(update, context)
            elif data.startswith("migrate_source_"):
                panel_id = int(data.split("_")[2])
                await self.handle_migrate_source_select(update, context, panel_id)
            elif data.startswith("migrate_dest_"):
                panel_id = int(data.split("_")[2])
                await self.handle_migrate_dest_select(update, context, panel_id)
            elif data == "migrate_confirm":
                await self.handle_migrate_confirm(update, context)
            elif data == "manage_panels":
                await self.handle_manage_panels(update, context)
            elif data == "system_logs":
                await self.handle_system_logs(update, context)
            elif data == "manage_users":
                await self.handle_manage_users(update, context)
            elif data == "manage_products":
                await self.handle_manage_products(update, context)
            elif data == "configure_test_account":
                await self.handle_configure_test_account(update, context)
            elif data.startswith("test_account_select_panel_"):
                panel_id = int(data.split("_")[-1])
                await self.handle_test_account_select_panel(update, context, panel_id)
            elif data.startswith("test_account_select_inbound_"):
                parts = data.split("_")
                panel_id = int(parts[-2])
                inbound_id = int(parts[-1])
                await self.handle_test_account_select_inbound(update, context, panel_id, inbound_id)
            elif data == "test_account_skip_inbound":
                await self.handle_test_account_skip_inbound(update, context)
            elif data == "list_panels":
                await self.handle_list_panels(update, context)
            elif data == "add_panel":
                await self.start_add_panel(update, context)
            elif data.startswith("panel_type_"):
                panel_type = data.replace("panel_type_", "")
                await self.handle_panel_type_selection(update, context, panel_type)
            elif data.startswith("select_sale_type_"):
                sale_type = data.replace("select_sale_type_", "")
                await self.handle_sale_type_selection(update, context, sale_type)
            elif data.startswith("panel_details_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    panel_id = int(parts[2])
                    await self.handle_panel_details(update, context, panel_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("edit_panel_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    panel_id = int(parts[2])
                    await self.start_edit_panel(update, context, panel_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("edit_name_"):
                panel_id = int(data.split("_")[2])
                await self.handle_edit_panel_field(update, context, panel_id, "name")
            elif data.startswith("edit_url_"):
                panel_id = int(data.split("_")[2])
                await self.handle_edit_panel_field(update, context, panel_id, "url")
            elif data.startswith("edit_username_"):
                panel_id = int(data.split("_")[2])
                await self.handle_edit_panel_field(update, context, panel_id, "username")
            elif data.startswith("edit_password_"):
                panel_id = int(data.split("_")[2])
                await self.handle_edit_panel_field(update, context, panel_id, "password")
            elif data.startswith("edit_suburl_"):
                panel_id = int(data.split("_")[2])
                await self.handle_edit_panel_field(update, context, panel_id, "subscription_url")
            elif data.startswith("edit_price_"):
                panel_id = int(data.split("_")[2])
                await self.handle_edit_panel_field(update, context, panel_id, "price")
            elif data.startswith("edit_inbound_"):
                panel_id = int(data.split("_")[2])
                await self.handle_change_main_inbound_selection(update, context, panel_id)
            elif data.startswith("edit_sale_type_"):
                panel_id = int(data.split("_")[3])
                await self.handle_edit_sale_type(update, context, panel_id)
            elif data.startswith("set_sale_type_"):
                parts = data.split("_")
                panel_id = int(parts[3])
                sale_type = parts[4]
                await self.handle_set_sale_type(update, context, panel_id, sale_type)
            elif data.startswith("delete_panel_"):
                parts = data.split("_")
                logger.info(f"Delete panel callback - parts: {parts}")
                if len(parts) >= 3 and parts[2].isdigit():
                    panel_id = int(parts[2])
                    logger.info(f"Deleting panel ID: {panel_id}")
                    await self.handle_delete_panel(update, context, panel_id)
                else:
                    logger.error(f"Invalid delete_panel callback data: {data}, parts: {parts}")
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("confirm_delete_panel_"):
                parts = data.split("_")
                logger.info(f"Confirm delete panel callback - parts: {parts}")
                if len(parts) >= 4 and parts[3].isdigit():
                    panel_id = int(parts[3])
                    logger.info(f"Confirming deletion of panel ID: {panel_id}")
                    await self.handle_confirm_delete_panel(update, context, panel_id)
                else:
                    logger.error(f"Invalid confirm_delete_panel callback data: {data}, parts: {parts}")
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data == "buy_service":
                await self.handle_buy_service(update, context)
            elif data == "test_account":
                await self.handle_get_test_account(update, context)
            elif data.startswith("select_panel_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    panel_id = int(parts[2])
                    await self.handle_select_panel(update, context, panel_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("buy_gigabyte_"):
                panel_id = int(data.split("_")[2])
                await self.handle_buy_gigabyte(update, context, panel_id)
            elif data.startswith("buy_plan_"):
                panel_id = int(data.split("_")[2])
                await self.handle_buy_plan(update, context, panel_id)
            elif data.startswith("buy_category_products_"):
                category_id = int(data.split("_")[3])
                await self.handle_buy_category_products(update, context, category_id)
            elif data.startswith("buy_product_"):
                product_id = int(data.split("_")[2])
                await self.handle_buy_product(update, context, product_id)
            elif data.startswith("enter_discount_code_product_"):
                product_id = int(data.split("_")[4])
                await self.handle_enter_discount_code_product(update, context, product_id)
            elif data.startswith("pay_balance_volume_"):
                parts = data.split("_")
                panel_id = int(parts[3])
                volume_gb = int(parts[4])
                price = int(parts[5])
                await self.handle_balance_volume_payment(update, context, panel_id, volume_gb, price)
            elif data.startswith("pay_card_volume_"):
                parts = data.split("_")
                panel_id = int(parts[3])
                volume_gb = int(parts[4])
                price = int(parts[5])
                # Create invoice and show card payment
                invoice_id = self.db.create_invoice(
                    user_id=update.effective_user.id,
                    amount=price,
                    description=f"خرید {volume_gb} گیگابایت حجم اضافه",
                    payment_method='card'
                )
                await self.show_card_payment(update, context, invoice_id)
            elif data.startswith("add_volume_select_"):
                parts = data.split("_")
                service_id = int(parts[3])
                panel_id = int(parts[4])
                volume_gb = int(parts[5])
                await self.handle_add_volume_selection(update, context, service_id, panel_id, volume_gb)
            elif data.startswith("pay_balance_add_volume_"):
                parts = data.split("_")
                service_id = int(parts[4])
                panel_id = int(parts[5])
                volume_gb = int(parts[6])
                price = int(parts[7])
                await self.handle_balance_add_volume_payment(update, context, service_id, panel_id, volume_gb, price)
            elif data.startswith("pay_card_add_volume_"):
                parts = data.split("_")
                service_id = int(parts[4])
                panel_id = int(parts[5])
                volume_gb = int(parts[6])
                price = int(parts[7])
                # Create invoice and show card payment
                invoice_id = self.db.create_invoice(
                    user_id=update.effective_user.id,
                    amount=price,
                    description=f"خرید {volume_gb} گیگابایت حجم اضافه برای سرویس {service_id}",
                    payment_method='card'
                )
                await self.show_card_payment(update, context, invoice_id)
            elif data.startswith("test_panel_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    panel_id = int(parts[2])
                    await self.test_panel_connection(update, context, panel_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data == "user_panel":
                await self.handle_user_panel(update, context)
            elif data == "start":
                # Handle "start" callback - return to main menu
                await self.show_main_menu(update, context)
            elif data == "all_services" or data == "my_services" or data.startswith("all_services_page_"):
                # Handle "all_services" and "my_services" callbacks - show all services list with pagination
                await self.handle_all_services(update, context)
            elif data.startswith("select_gb_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit() and parts[3].isdigit():
                    panel_id = int(parts[2])
                    gb_amount = int(parts[3])
                    await self.handle_gb_selection(update, context, panel_id, gb_amount)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("pay_balance_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    invoice_id = int(parts[2])
                    await self.handle_balance_payment(update, context, invoice_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("pay_card_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    invoice_id = int(parts[2])
                    await self.show_card_payment(update, context, invoice_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data == "account_balance":
                await self.handle_account_balance(update, context)
            elif data == "payment_history":
                await self.handle_payment_history(update, context)
            elif data == "add_balance":
                await self.handle_add_balance(update, context)
            elif data.startswith("add_balance_"):
                parts = data.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    amount = int(parts[2])
                    await self.handle_add_balance_amount(update, context, amount)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("manage_service_"):
                service_id = int(data.split("_")[2])
                await self.handle_manage_service(update, context, service_id)
            elif data.startswith("manage_panel_inbounds_"):
                panel_id = int(data.split("_")[3])
                await self.handle_manage_panel_inbounds(update, context, panel_id)
            elif data.startswith("toggle_inbound_"):
                parts = data.split("_")
                if len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
                    panel_id = int(parts[2])
                    inbound_id = int(parts[3])
                    await self.handle_toggle_inbound(update, context, panel_id, inbound_id)
            elif data.startswith("change_main_inbound_"):
                parts = data.split("_")
                if len(parts) >= 4 and parts[3].isdigit() and parts[4].isdigit():
                    panel_id = int(parts[3])
                    inbound_id = int(parts[4])
                    await self.handle_change_main_inbound(update, context, panel_id, inbound_id)
            elif data.startswith("sync_inbounds_"):
                panel_id = int(data.split("_")[2])
                await self.handle_sync_inbounds(update, context, panel_id)
            elif data.startswith("change_panel_"):
                service_id = int(data.split("_")[2])
                await self.handle_change_panel(update, context, service_id)
            elif data.startswith("select_new_panel_"):
                parts = data.split("_")
                if len(parts) >= 4 and parts[3].isdigit() and parts[4].isdigit():
                    service_id = int(parts[3])
                    new_panel_id = int(parts[4])
                    await self.handle_select_new_panel(update, context, service_id, new_panel_id)
            elif data.startswith("confirm_change_panel_"):
                parts = data.split("_")
                if len(parts) >= 4 and parts[3].isdigit() and parts[4].isdigit():
                    service_id = int(parts[3])
                    new_panel_id = int(parts[4])
                    await self.handle_confirm_change_panel(update, context, service_id, new_panel_id)
            elif data.startswith("select_new_inbound_"):
                # Format: select_new_inbound_{service_id}_{panel_id}_{inbound_id}
                parts = data.split("_")
                if len(parts) >= 6:
                    try:
                        service_id = int(parts[3])
                        new_panel_id = int(parts[4])
                        new_inbound_id = int(parts[5])
                        await self.handle_select_new_inbound(update, context, service_id, new_panel_id, new_inbound_id)
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error parsing select_new_inbound callback: {e}, data: {data}")
            elif data.startswith("confirm_change_inbound_"):
                # Format: confirm_change_inbound_{service_id}_{panel_id}_{inbound_id}
                parts = data.split("_")
                if len(parts) >= 6:
                    try:
                        service_id = int(parts[3])
                        new_panel_id = int(parts[4])
                        new_inbound_id = int(parts[5])
                        await self.handle_confirm_change_inbound(update, context, service_id, new_panel_id, new_inbound_id)
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error parsing confirm_change_inbound callback: {e}, data: {data}")
            elif data.startswith("get_config_"):
                service_id = int(data.split("_")[2])
                await self.handle_get_config(update, context, service_id)
            elif data.startswith("get_qr_code_"):
                service_id = int(data.split("_")[3])
                await self.handle_get_qr_code(update, context, service_id)
            elif data.startswith("reset_service_link_"):
                service_id = int(data.split("_")[3])
                await self.handle_reset_service_link(update, context, service_id)
            elif data.startswith("confirm_reset_link_"):
                service_id = int(data.split("_")[3])
                await self.handle_confirm_reset_link(update, context, service_id)
            elif data.startswith("add_volume_"):
                service_id = int(data.split("_")[2])
                await self.handle_add_volume(update, context, service_id)
            elif data.startswith("renew_service_"):
                service_id = int(data.split("_")[2])
                await self.handle_renew_service(update, context, service_id)
            elif data.startswith("renew_category_products_"):
                parts = data.split("_")
                if len(parts) >= 5 and parts[3].isdigit() and parts[4].isdigit():
                    category_id = int(parts[3])
                    service_id = int(parts[4])
                    await self.handle_renew_category_products(update, context, category_id, service_id)
            elif data.startswith("renew_product_"):
                parts = data.split("_")
                if len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
                    product_id = int(parts[2])
                    service_id = int(parts[3])
                    await self.handle_renew_product(update, context, product_id, service_id)
            elif data.startswith("enter_discount_code_renew_product_"):
                parts = data.split("_")
                if len(parts) >= 6 and parts[5].isdigit() and parts[6].isdigit():
                    product_id = int(parts[5])
                    service_id = int(parts[6])
                    await self.handle_enter_discount_code_renew_product(update, context, product_id, service_id)
            elif data.startswith("continue_without_discount_renew_product_"):
                parts = data.split("_")
                if len(parts) >= 6 and parts[5].isdigit() and parts[6].isdigit():
                    product_id = int(parts[5])
                    service_id = int(parts[6])
                    await self.handle_continue_without_discount_renew_product(update, context, product_id, service_id)
            elif data.startswith("delete_service_"):
                service_id = int(data.split("_")[2])
                await self.handle_delete_service(update, context, service_id)
            elif data.startswith("confirm_delete_service_"):
                service_id = int(data.split("_")[3])
                await self.handle_confirm_delete_service(update, context, service_id)
            elif data.startswith("select_inbound_for_panel_"):
                parts = data.split("_")
                if len(parts) >= 4 and parts[3].isdigit():
                    inbound_id = int(parts[3])
                    await self.handle_inbound_selection_for_panel(update, context, inbound_id)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("select_protocol_for_panel_"):
                # Handle protocol selection for Marzban panels
                protocol = data.split("_")[4]  # vless, vmess, or trojan
                await self.handle_protocol_selection_for_panel(update, context, protocol)
            elif data.startswith("select_group_for_panel_"):
                # Handle group selection for Pasargad panels
                # group_id might be string (name) or int
                group_id = data.split("_", 4)[4]
                await self.handle_group_selection_for_panel(update, context, group_id)
            elif data == "page_info":
                # Handle page info button - just show a simple alert
                await query.answer("ℹ️ این دکمه فقط نمایشگر شماره صفحه است", show_alert=False)
            elif data.startswith("pay_gateway_volume_"):
                # Redirect to card-to-card payment for volume purchase
                parts = data.split("_")
                # pay_gateway_volume_{panel_id}_{volume_gb}_{price}
                if len(parts) >= 6 and parts[3].isdigit() and parts[4].isdigit() and parts[5].isdigit():
                    panel_id = int(parts[3])
                    volume_gb = int(parts[4])
                    price = int(parts[5])
                    await self.handle_gateway_volume_payment(update, context, panel_id, volume_gb, price)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("pay_gateway_add_volume_"):
                # Redirect to card-to-card payment for add volume
                parts = data.split("_")
                # pay_gateway_add_volume_{service_id}_{panel_id}_{volume_gb}_{price}
                if len(parts) >= 8:
                    service_id = int(parts[4])
                    panel_id = int(parts[5])
                    volume_gb = int(parts[6])
                    price = int(parts[7])
                    await self.handle_gateway_add_volume_payment(update, context, service_id, panel_id, volume_gb, price)
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            elif data.startswith("pay_gateway_"):
                # Generic gateway callback - redirect to card-to-card
                parts = data.split("_")
                # pay_gateway_{invoice_id} or pay_gateway_{something}
                if len(parts) >= 3 and parts[2].isdigit():
                    invoice_id = int(parts[2])
                    await self.show_card_payment(update, context, invoice_id)
                else:
                    await query.edit_message_text("❌ درگاه پرداخت آنلاین غیرفعال است. لطفاً از کارت به کارت استفاده کنید.")
            elif data.startswith("approve_receipt_"):
                invoice_id = int(data.split("_")[2])
                await self.handle_approve_receipt(update, context, invoice_id)
            elif data.startswith("reject_receipt_"):
                invoice_id = int(data.split("_")[2])
                await self.handle_reject_receipt(update, context, invoice_id)
            else:
                # Handle unknown callback data
                logger.warning(f"Unknown callback data: {data}")
                await query.edit_message_text("❌ درخواست نامعتبر است. لطفاً دوباره تلاش کنید.")
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            logger.error(f"Callback data: {data}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
    
    async def select_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE, inbound_id: int):
        """Handle inbound selection with advanced options"""
        query = update.callback_query
        
        # Get inbound details
        inbounds = self.panel_manager.get_inbounds()
        selected_inbound = None
        for inbound in inbounds:
            if inbound.get('id') == inbound_id:
                selected_inbound = inbound
                break
        
        if not selected_inbound:
            await query.edit_message_text("❌ اینباند یافت نشد.")
            return
        
        inbound_name = selected_inbound.get('remark', f'Inbound {inbound_id}')
        inbound_protocol = selected_inbound.get('protocol', 'unknown')
        inbound_port = selected_inbound.get('port', 0)
        
        # Store inbound selection in user session
        user_id = update.effective_user.id
        self.user_sessions[user_id] = {'selected_inbound': inbound_id}
        
        text = f"""
⚙️ **تنظیمات کلاینت**

**اینباند انتخاب شده:** {inbound_name}
**پروتکل:** `{inbound_protocol}`
**پورت:** `{inbound_port}`

**گزینه‌های ایجاد کلاینت:**
• **ایجاد سریع:** کلاینت با تنظیمات پیش‌فرض (نامحدود)
• **تنظیمات پیشرفته:** تعیین حجم و مدت زمان
        """
        
        keyboard = [
            [InlineKeyboardButton("⚙️ تنظیمات پیشرفته", callback_data=f"advanced_settings_{inbound_id}")],
            [InlineKeyboardButton("🚀 ایجاد سریع (پیش‌فرض)", callback_data=f"quick_create_{inbound_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="show_inbounds")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def create_client_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, inbound_id: int):
        """Prompt user for client name"""
        query = update.callback_query
        
        text = """
📝 **ایجاد کلاینت جدید**

لطفاً نام کلاینت را وارد کنید:

**نکات:**
• نام باید منحصر به فرد باشد
• فقط حروف انگلیسی و اعداد مجاز است
• طول نام باید بین 3 تا 20 کاراکتر باشد

برای لغو عملیات /cancel را ارسال کنید.
        """
        
        keyboard = [
            [InlineKeyboardButton("❌ لغو", callback_data=f"select_inbound_{inbound_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_quick_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE, inbound_id: int):
        """Handle quick client creation with default settings"""
        query = update.callback_query
        
        text = """
📝 **نام کلاینت را وارد کنید**

**تنظیمات پیش‌فرض:**
• مدت زمان: نامحدود
• حجم ترافیک: نامحدود

نام کلاینت باید:
• 3-20 کاراکتر باشد
• فقط شامل حروف، اعداد، خط تیره و زیرخط باشد
• مثال: `my_client`, `user123`, `test-user`
        """
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown'
        )
        
        # Set state for quick client creation
        context.user_data['waiting_for_client_name'] = True
        context.user_data['selected_inbound_id'] = inbound_id
        context.user_data['client_type'] = 'quick'  # quick or advanced
    
    async def handle_advanced_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE, inbound_id: int):
        """Handle advanced client creation settings"""
        query = update.callback_query
        
        text = """
📝 **نام کلاینت را وارد کنید**

**تنظیمات پیشرفته:**
• بعد از وارد کردن نام، حجم و مدت زمان را تعیین خواهید کرد

نام کلاینت باید:
• 3-20 کاراکتر باشد
• فقط شامل حروف، اعداد، خط تیره و زیرخط باشد
• مثال: `my_client`, `user123`, `test-user`
        """
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown'
        )
        
        # Set state for advanced client creation
        context.user_data['waiting_for_client_name'] = True
        context.user_data['selected_inbound_id'] = inbound_id
        context.user_data['client_type'] = 'advanced'  # quick or advanced
        
        # Set user state to waiting for client name
        user_id = update.effective_user.id
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {}
        self.user_sessions[user_id]['waiting_for_name'] = True
        self.user_sessions[user_id]['inbound_id'] = inbound_id
    
    @auto_update_user_info
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages with advanced flow"""
        user_id = update.effective_user.id
        text = update.message.text
        
        # Check channel membership for all text messages (except if it's part of admin flow)
        # Allow admin to bypass
        if user_id != self.bot_config['admin_id']:
            is_member = await check_channel_membership(update, context, bot_config=self.bot_config)
            if not is_member:
                await show_force_join_message(update, context, bot_config=self.bot_config)
                return
        
        # Handle Main Menu Buttons
        if text == "🛒 خرید سرویس":
            await self.handle_buy_service(update, context)
            return
        elif text == "📊 پنل کاربری":
            await self.handle_user_panel(update, context)
            return
        elif text == "💰 موجودی":
            await self.handle_account_balance(update, context)
            return
        elif text == "🧪 اکانت تست":
            await self.handle_get_test_account(update, context)
            return
        elif text == "🎁 دعوت دوستان":
            await self.handle_referral_system(update, context)
            return
        elif text == "❓ راهنما و پشتیبانی":
            await self.show_help(update, context)
            return
        elif text == "⚙️ پنل مدیریت":
            if self.db.is_admin(user_id):
                await self.handle_admin_panel(update, context)
            return
        
        # Check if admin is sending broadcast message
        if context.user_data.get('awaiting_broadcast_message', False):
            await self.handle_broadcast_message(update, context)
            return
        
        # Check if admin is forwarding broadcast message
        if context.user_data.get('awaiting_broadcast_forward', False):
            await self.handle_broadcast_forward(update, context)
            return
        
        # Check if admin is entering admin ID to add
        if context.user_data.get('awaiting_admin_id', False):
            await self.handle_add_admin_id(update, context)
            return
        
        # Check if admin is entering user ID for info
        if context.user_data.get('awaiting_user_id_for_info', False):
            await self.handle_user_info_display(update, context)
            return

        # Check if admin is entering card number or owner
        if context.user_data.get('awaiting_card_number', False) or context.user_data.get('awaiting_card_owner', False):
            await self.handle_card_settings_input(update, context, text)
            return
        
        # Check if admin is entering gift amount
        if context.user_data.get('awaiting_gift_amount', False):
            await self.handle_gift_all_users_execute(update, context)
            return
        
        # Check if admin is entering balance amount
        if context.user_data.get('awaiting_balance_amount', False):
            await self.handle_balance_amount_input(update, context)
            return
        
        # Check if user is editing a panel
        if context.user_data.get('editing_panel', False):
            await self.handle_edit_panel_text_input(update, context, text)
            return
        
        # Check if user is adding a panel
        if context.user_data.get('adding_panel', False):
            await self.handle_add_panel_text_flow(update, context, text)
            return
        
        # Check if user is adding a category
        if context.user_data.get('adding_category', False):
            await self.handle_add_category_text(update, context, text)
            return
        
        # Check if user is editing category name
        if context.user_data.get('editing_category_name', False):
            await self.handle_category_text_edit(update, context, text)
            return
        
        # Check if user is adding a product
        if context.user_data.get('adding_product', False):
            await self.handle_add_product_text_flow(update, context, text)
            return
        
        # Check if user is editing a product field
        if context.user_data.get('editing_product_field', False):
            await self.handle_product_text_edit(update, context, text)
            return
        
        # Check if user is entering custom balance amount
        if context.user_data.get('waiting_for_custom_balance', False):
            await self.handle_custom_balance_text_input(update, context, text)
            return
        
        # Check if user is entering custom volume amount
        if context.user_data.get('waiting_for_custom_volume', False):
            await self.handle_custom_volume_text_input(update, context, text)
            return
        
        # Check if user is creating client on panel
        if context.user_data.get('creating_client_panel', False):
            await self.handle_create_client_panel_flow(update, context, text)
            return
        
        # Check if user is waiting for client name
        if context.user_data.get('waiting_for_client_name', False):
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                context.user_data.clear()
                return
            
            # Validate client name
            if not self._validate_client_name(text):
                await update.message.reply_text(
                    "❌ نام کلاینت نامعتبر است. لطفاً نام دیگری انتخاب کنید:"
                )
                return
            
            inbound_id = context.user_data.get('selected_inbound_id')
            client_type = context.user_data.get('client_type', 'quick')
            
            if client_type == 'quick':
                # Quick create with default settings
                await self.create_client(update, context, inbound_id, text)
                context.user_data.clear()
            else:
                # Advanced create - ask for settings
                await self.handle_advanced_flow(update, context, inbound_id, text)
        
        # Check if user is waiting for expire days
        elif context.user_data.get('waiting_for_expire_days', False):
            try:
                expire_days = int(text)
                if expire_days == -1:
                    await update.message.reply_text("❌ عملیات لغو شد.")
                    context.user_data.clear()
                    return
                
                context.user_data['expire_days'] = expire_days
                context.user_data['waiting_for_expire_days'] = False
                context.user_data['waiting_for_total_gb'] = True
                
                text = """
📊 **حجم ترافیک کلاینت (گیگابایت)**

لطفاً حجم ترافیک کلاینت را وارد کنید:

**گزینه‌ها:**
• عدد مثبت: حجم به گیگابایت (مثال: 50)
• 0: نامحدود
• -1: لغو عملیات

**مثال:** `50` برای 50 گیگابایت، `0` برای نامحدود
                """
                
                await update.message.reply_text(text, parse_mode='Markdown')
                
            except ValueError:
                await update.message.reply_text(
                    "❌ لطفاً یک عدد معتبر وارد کنید یا -1 برای لغو:"
                )
        
        # Check if user is waiting for discount code (for purchase)
        elif context.user_data.get('waiting_for_discount_code', False):
            code = text.strip().upper()
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                context.user_data.clear()
                return
            
            if not code:
                await update.message.reply_text("❌ لطفاً کد تخفیف را وارد کنید یا /cancel برای لغو:")
                return
            
            panel_id = context.user_data.get('discount_panel_id')
            gb_amount = context.user_data.get('discount_gb_amount')
            
            if not panel_id or not gb_amount:
                await update.message.reply_text("❌ خطا در پردازش. لطفاً دوباره تلاش کنید.")
                context.user_data.clear()
                return
            
            # Validate discount code
            await self.validate_and_apply_discount_code(update, context, panel_id, gb_amount, code)
            context.user_data.pop('waiting_for_discount_code', None)
            context.user_data.pop('discount_panel_id', None)
            context.user_data.pop('discount_gb_amount', None)
        
        # Check if user is waiting for discount code (for volume purchase)
        elif context.user_data.get('waiting_for_discount_code_volume', False):
            code = text.strip().upper()
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                context.user_data.pop('waiting_for_discount_code_volume', None)
                context.user_data.pop('discount_panel_id', None)
                context.user_data.pop('discount_volume_gb', None)
                context.user_data.pop('discount_price', None)
                return
            
            if not code:
                await update.message.reply_text("❌ لطفاً کد تخفیف یا کد هدیه را وارد کنید یا /cancel برای لغو:")
                return
            
            panel_id = context.user_data.get('discount_panel_id')
            volume_gb = context.user_data.get('discount_volume_gb')
            price = context.user_data.get('discount_price')
            
            if not panel_id or not volume_gb or not price:
                await update.message.reply_text("❌ خطا در پردازش. لطفاً دوباره تلاش کنید.")
                context.user_data.pop('waiting_for_discount_code_volume', None)
                context.user_data.pop('discount_panel_id', None)
                context.user_data.pop('discount_volume_gb', None)
                context.user_data.pop('discount_price', None)
                return
            
            # Validate and apply discount code or gift code
            await self.validate_and_apply_discount_code_volume(update, context, panel_id, volume_gb, price, code)
            context.user_data.pop('waiting_for_discount_code_volume', None)
            context.user_data.pop('discount_panel_id', None)
            context.user_data.pop('discount_volume_gb', None)
            context.user_data.pop('discount_price', None)
        
        # Check if user is waiting for discount code (for adding volume)
        elif context.user_data.get('waiting_for_discount_code_add_volume', False):
            code = text.strip().upper()
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                service_id = context.user_data.get('discount_add_volume_service_id')
                panel_id = context.user_data.get('discount_panel_id')
                volume_gb = context.user_data.get('discount_volume_gb')
                price = context.user_data.get('discount_price')
                if service_id and panel_id and volume_gb and price:
                    await self.handle_continue_without_discount_add_volume(update, context, service_id, panel_id, volume_gb, price)
                context.user_data.pop('waiting_for_discount_code_add_volume', None)
                context.user_data.pop('discount_add_volume_service_id', None)
                context.user_data.pop('discount_panel_id', None)
                context.user_data.pop('discount_volume_gb', None)
                context.user_data.pop('discount_price', None)
                return
            
            if not code:
                await update.message.reply_text("❌ لطفاً کد تخفیف یا کد هدیه را وارد کنید یا /cancel برای لغو:")
                return
            
            service_id = context.user_data.get('discount_add_volume_service_id')
            panel_id = context.user_data.get('discount_panel_id')
            volume_gb = context.user_data.get('discount_volume_gb')
            price = context.user_data.get('discount_price')
            
            if not service_id or not panel_id or not volume_gb or not price:
                await update.message.reply_text("❌ خطا در پردازش. لطفاً دوباره تلاش کنید.")
                context.user_data.pop('waiting_for_discount_code_add_volume', None)
                context.user_data.pop('discount_add_volume_service_id', None)
                context.user_data.pop('discount_panel_id', None)
                context.user_data.pop('discount_volume_gb', None)
                context.user_data.pop('discount_price', None)
                return
            
            # Validate and apply discount code or gift code
            await self.validate_and_apply_discount_code_add_volume(update, context, service_id, panel_id, volume_gb, price, code)
            context.user_data.pop('waiting_for_discount_code_add_volume', None)
            context.user_data.pop('discount_add_volume_service_id', None)
            context.user_data.pop('discount_panel_id', None)
            context.user_data.pop('discount_volume_gb', None)
            context.user_data.pop('discount_price', None)
        
        # Check if user is waiting for discount code (for product purchase)
        elif context.user_data.get('waiting_for_discount_code_product', False):
            code = text.strip().upper()
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                product_id = context.user_data.get('discount_product_id')
                context.user_data.pop('waiting_for_discount_code_product', None)
                context.user_data.pop('discount_product_id', None)
                if product_id:
                    await update.message.reply_text(
                        "لطفاً دوباره از دکمه خرید استفاده کنید.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📦 بازگشت به خرید", callback_data=f"buy_product_{product_id}")]
                        ])
                    )
                return
            
            if not code:
                await update.message.reply_text("❌ لطفاً کد تخفیف یا کد هدیه را وارد کنید یا /cancel برای لغو:")
                return
            
            product_id = context.user_data.get('discount_product_id')
            
            if not product_id:
                await update.message.reply_text("❌ خطا در پردازش. لطفاً دوباره تلاش کنید.")
                context.user_data.pop('waiting_for_discount_code_product', None)
                context.user_data.pop('discount_product_id', None)
                return
            
            # Validate and apply discount code or gift code
            await self.validate_and_apply_discount_code_product(update, context, product_id, code)
            context.user_data.pop('waiting_for_discount_code_product', None)
            context.user_data.pop('discount_product_id', None)
        
        # Check if user is waiting for discount code (for product renewal)
        elif context.user_data.get('waiting_for_discount_code_renew_product', False):
            code = text.strip().upper()
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                product_id = context.user_data.get('discount_product_id')
                service_id = context.user_data.get('discount_service_id')
                context.user_data.pop('waiting_for_discount_code_renew_product', None)
                context.user_data.pop('discount_product_id', None)
                context.user_data.pop('discount_service_id', None)
                if product_id and service_id:
                    await update.message.reply_text(
                        "لطفاً دوباره از دکمه تمدید استفاده کنید.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 بازگشت به تمدید", callback_data=f"renew_product_{product_id}_{service_id}")]
                        ])
                    )
                return
            
            if not code:
                await update.message.reply_text("❌ لطفاً کد تخفیف یا کد هدیه را وارد کنید یا /cancel برای لغو:")
                return
            
            product_id = context.user_data.get('discount_product_id')
            service_id = context.user_data.get('discount_service_id')
            
            if not product_id or not service_id:
                await update.message.reply_text("❌ خطا در پردازش. لطفاً دوباره تلاش کنید.")
                context.user_data.pop('waiting_for_discount_code_renew_product', None)
                context.user_data.pop('discount_product_id', None)
                context.user_data.pop('discount_service_id', None)
                return
            
            # Validate and apply discount code or gift code for renewal
            await self.validate_and_apply_discount_code_product_renewal(update, context, product_id, service_id, code)
            context.user_data.pop('waiting_for_discount_code_renew_product', None)
            context.user_data.pop('discount_product_id', None)
            context.user_data.pop('discount_service_id', None)
        
        # Check if admin is creating discount code
        elif context.user_data.get('creating_discount_code', False):
            await self.handle_create_discount_code_flow(update, context, text)
        
        # Check if admin is creating gift code
        elif context.user_data.get('creating_gift_code', False):
            await self.handle_create_gift_code_flow(update, context, text)
        
        # Check if user is waiting for total GB
        elif context.user_data.get('waiting_for_total_gb', False):
            try:
                total_gb = int(text)
                if total_gb == -1:
                    await update.message.reply_text("❌ عملیات لغو شد.")
                    context.user_data.clear()
                    return
                
                # Create client with all settings
                inbound_id = context.user_data.get('selected_inbound_id')
                client_name = context.user_data.get('client_name')
                expire_days = context.user_data.get('expire_days', 0)
                
                await self.create_client(update, context, inbound_id, client_name, expire_days, total_gb)
                context.user_data.clear()
                
            except ValueError:
                await update.message.reply_text(
                    "❌ لطفاً یک عدد معتبر وارد کنید یا -1 برای لغو:"
                )
        
        else:
            await update.message.reply_text(
                "لطفاً از منو استفاده کنید یا /start را ارسال کنید."
            )
    
    async def handle_advanced_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                 inbound_id: int, client_name: str):
        """Handle advanced client creation flow"""
        context.user_data['client_name'] = client_name
        context.user_data['waiting_for_client_name'] = False
        context.user_data['waiting_for_expire_days'] = True
        
        text = """
📅 **مدت زمان کلاینت (روز)**

لطفاً تعداد روزهای اعتبار کلاینت را وارد کنید:

**گزینه‌ها:**
• عدد مثبت: تعداد روز (مثال: 30)
• 0: نامحدود
• -1: لغو عملیات

**مثال:** `30` برای 30 روز، `0` برای نامحدود
        """
        
        await update.message.reply_text(text, parse_mode='Markdown')
    
    def _validate_client_name(self, name: str) -> bool:
        """Validate client name"""
        if not name or len(name) < 3 or len(name) > 20:
            return False
        
        # Check if name contains only alphanumeric characters
        return name.replace('_', '').replace('-', '').isalnum()
    
    async def create_client(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                          inbound_id: int, client_name: str, expire_days: int = 0, total_gb: int = 0):
        """Create a new client with custom settings - NOTE: This is for admin only, creates on one inbound"""
        if isinstance(update, Update) and update.message:
            message = update.message
        else:
            message = update.callback_query.message
        
        # Show creating message
        creating_msg = await message.reply_text("⏳ در حال ایجاد کلاینت...")
        
        try:
            # Get inbound details to determine protocol
            inbounds = self.panel_manager.get_inbounds()
            selected_inbound = None
            for inbound in inbounds:
                if inbound.get('id') == inbound_id:
                    selected_inbound = inbound
                    break
            
            if not selected_inbound:
                await creating_msg.edit_text("❌ اینباند یافت نشد.")
                return
            
            protocol = selected_inbound.get('protocol', 'vmess')
            
            # Create client with custom settings (single inbound for admin)
            client = self.panel_manager.create_client(
                inbound_id=inbound_id,
                client_name=client_name,
                protocol=protocol,
                expire_days=expire_days,
                total_gb=total_gb
            )
            
            if not client:
                await creating_msg.edit_text("❌ خطا در ایجاد کلاینت. لطفاً دوباره تلاش کنید.")
                return
            
            # Get configuration link (single config for single inbound)
            config_link = self.panel_manager.get_client_config_link(
                inbound_id, client.get('id'), protocol
            )
            
            # Format expiry and traffic info
            expiry_info = f"{expire_days} روز" if expire_days > 0 else "نامحدود"
            traffic_info = f"{total_gb} گیگابایت" if total_gb > 0 else "نامحدود"
            
            success_text = f"""
✅ **کلاینت با موفقیت ایجاد شد!**

**نام کلاینت:** `{client_name}`
**پروتکل:** `{protocol}`
**مدت زمان:** {expiry_info}
**حجم ترافیک:** {traffic_info}
**سرور:** `{client.get('server_host', 'N/A')}:{client.get('inbound_port', 'N/A')}`
**شبکه:** `{client.get('network_type', 'N/A')}` ({client.get('security_type', 'N/A')})

**کانفیگ:**
```
{config_link if config_link else 'کانفیگ در دسترس نیست'}
```

**نکات:**
• این کلاینت فقط روی یک اینباند ساخته شده است
• برای ساخت روی همه اینباندها، از بخش خرید سرویس استفاده کنید
• کانفیگ را در اپلیکیشن VPN خود وارد کنید
            """
            
            keyboard = [
                [InlineKeyboardButton("📋 مشاهده اینباندها", callback_data="show_inbounds")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await creating_msg.edit_text(
                success_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error creating client: {e}")
            await creating_msg.edit_text("❌ خطا در ایجاد کلاینت. لطفاً دوباره تلاش کنید.")
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        query = update.callback_query
        if query:
            await query.answer()
        
        help_text = """
📖 **راهنمای کامل استفاده از ربات**

**🎯 مراحل خرید و استفاده از سرویس:**

**1️⃣ افزایش موجودی:**
• از منوی اصلی گزینه "💰 موجودی" را انتخاب کنید
• روی "افزایش موجودی" کلیک کنید
• مبلغ دلخواه را انتخاب کنید
• پرداخت را از طریق درگاه بانکی تکمیل کنید

**2️⃣ خرید سرویس VPN:**
• از منوی اصلی گزینه "🛒 خرید سرویس" را انتخاب کنید
• پنل مورد نظر را انتخاب کنید
• حجم دلخواه (گیگابایت) را انتخاب کنید
• روش پرداخت را انتخاب کنید (موجودی یا آنلاین)

**3️⃣ دریافت کانفیگ:**
• به "📊 داشبورد کاربری" بروید
• سرویس خریداری شده را انتخاب کنید
• روی "📋 دریافت کانفیگ" کلیک کنید
• کانفیگ را در برنامه VPN خود وارد کنید

**📱 نرم‌افزارهای پیشنهادی:**
• **اندروید:** v2rayNG
• **iOS:** Shadowrocket, Fair VPN
• **ویندوز:** v2rayN, Nekoray
• **مک:** V2RayX

**🔧 مدیریت سرویس:**
• مشاهده وضعیت سرویس
• تمدید سرویس (افزودن حجم)
• دریافت مجدد کانفیگ
• حذف سرویس

**💡 نکات مهم:**
• همیشه قبل از خرید موجودی کافی داشته باشید
• برای تمدید سرویس به پنل کاربری مراجعه کنید
• در صورت هر مشکلی با پشتیبانی تماس بگیرید
        """
        
        keyboard = [
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(
                help_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                help_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    @auto_update_user_info
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu - same as start command"""
        user_id = update.effective_user.id
        
        if update.callback_query:
            query = update.callback_query
            # Delete the old message
            try:
                await query.delete_message()
            except:
                pass
        
        # Get user data
        user_data = self.db.get_user(user_id)
        # Check if user is admin - check both database and config
        is_admin_by_config = (user_id == self.bot_config['admin_id'])
        is_admin_by_db = self.db.is_admin(user_id)
        is_admin = is_admin_by_config or is_admin_by_db
        
        # Create welcome message - handle None user_data
        if user_data is None:
            user_data = {}
        # Ensure database name is set in thread-local storage
        MessageTemplates.set_database_name(self.db.database_name)
        
        bot_name = self.bot_config.get('bot_name', '')
        welcome_text = MessageTemplates.format_welcome_message(user_data, is_admin, bot_name=bot_name)
        
        # Create professional main menu
        # Get webapp URL with bot name prefix
        base_url = self.bot_config.get('webapp_url', 'http://localhost:443')
        
        # 1. Main Menu (Reply Keyboard)
        reply_markup = ButtonLayout.create_main_menu(
            is_admin=is_admin,
            user_balance=user_data.get('balance', 0) if user_data else 0,
            user_id=user_id,
            webapp_url=base_url,
            bot_name=bot_name,
            db=self.db
        )
        
        # 2. Web App Button (Inline Keyboard)
        webapp_markup = ButtonLayout.create_webapp_keyboard(
            webapp_url=base_url,
            bot_name=bot_name
        )
        
        # Send welcome message with Reply Keyboard
        await context.bot.send_message(
            chat_id=user_id,
            text=welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Send Web App button separately
        await context.bot.send_message(
            chat_id=user_id,
            text="🌐 **ورود به پنل کاربری پیشرفته (وب اپلیکیشن)** 👇",
            reply_markup=webapp_markup,
            parse_mode='Markdown'
        )
    
    # Admin Panel Methods
    @auto_update_user_info
    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin panel main menu"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await query.edit_message_text("❌ دسترسی غیرمجاز.")
            return
        
        admin_text = """
⚙️ **پنل مدیریت**

به پنل مدیریت خوش آمدید. گزینه مورد نظر را انتخاب کنید:
        """
        
        # Use the centralized button layout
        reply_markup = ButtonLayout.create_admin_panel(bot_name=self.bot_username)
        
        await query.edit_message_text(
            admin_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def show_manage_panels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show panel management options"""
        query = update.callback_query
        await query.answer()
        
        panels_text = """
🔧 **مدیریت پنل‌ها**

برای مدیریت پنل‌های x-ui گزینه مورد نظر را انتخاب کنید:
        """
        
        keyboard = [
            [InlineKeyboardButton("📋 لیست پنل‌های موجود", callback_data="list_panels")],
            [InlineKeyboardButton("➕ اضافه کردن پنل", callback_data="add_panel")],
            [InlineKeyboardButton("🔄 مهاجرت پنل", callback_data="migrate_panel_start")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            panels_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def show_panels_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of all panels"""
        query = update.callback_query
        await query.answer()
        
        panels = self.admin_manager.get_panels_list()
        
        if not panels:
            no_panels_text = """
❌ **هیچ پنلی ثبت نشده است**

برای اضافه کردن پنل جدید از دکمه زیر استفاده کنید:
            """
            
            keyboard = [
                [InlineKeyboardButton("➕ اضافه کردن پنل", callback_data="add_panel")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_panels")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                no_panels_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        panels_text = f"📋 **پنل‌های موجود ({len(panels)} عدد):**\n\n"
        
        keyboard = []
        for panel in panels:
            status = "🟢 فعال" if panel['is_active'] else "🔴 غیرفعال"
            panel_text = f"🔗 {panel['name']} {status}"
            keyboard.append([InlineKeyboardButton(
                panel_text, 
                callback_data=f"panel_details_{panel['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("➕ اضافه کردن پنل", callback_data="add_panel")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_panels")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            panels_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def show_panel_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show detailed information about a panel"""
        query = update.callback_query
        await query.answer()
        
        panel = self.admin_manager.get_panel_details(panel_id)
        if not panel:
            await query.edit_message_text("❌ پنل یافت نشد.")
            return
        
        # Test connection
        success, message = self.admin_manager.test_panel_connection(panel_id)
        
        # Get main inbound info
        main_inbound_info = ""
        main_inbound = panel.get('main_inbound')
        if main_inbound:
            main_inbound_info = f"• اینباند اصلی: `{main_inbound.get('name', 'نامشخص')}` ({main_inbound.get('protocol', 'unknown')}:{main_inbound.get('port', 0)})"
        elif panel.get('default_inbound_id'):
            main_inbound_info = f"• اینباند اصلی ID: `{panel.get('default_inbound_id')}`"
        else:
            main_inbound_info = "• اینباند اصلی: ❌ تنظیم نشده"
        
        panel_text = f"""
🔗 **جزئیات پنل: {panel['name']}**

**اطلاعات پنل:**
• نام: `{panel['name']}`
• URL: `{panel['url']}`
• یوزرنیم: `{panel['username']}`
• وضعیت: {'🟢 آنلاین' if success else '🔴 آفلاین'}

**آمار:**
• تعداد اینباندها: {panel.get('inbounds_count', 0)}
{main_inbound_info}
• وضعیت اتصال: {message}

**گزینه‌ها:**
        """
        
        keyboard = [
            [InlineKeyboardButton("✏️ ویرایش پنل", callback_data=f"edit_panel_{panel_id}")],
            [InlineKeyboardButton("🔗 مدیریت اینباندها", callback_data=f"manage_panel_inbounds_{panel_id}")],
            [InlineKeyboardButton("🗑️ حذف پنل", callback_data=f"delete_panel_{panel_id}")],
            [InlineKeyboardButton("🔄 تست اتصال", callback_data=f"test_panel_{panel_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="list_panels")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            panel_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def start_migrate_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start panel migration process - Select Source Panel"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get all panels
            panels = self.db.get_all_panels()
            
            if not panels:
                await query.edit_message_text(
                    "❌ هیچ پنلی یافت نشد.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
                return
            
            if len(panels) < 2:
                await query.edit_message_text(
                    "❌ برای مهاجرت حداقل به دو پنل نیاز است.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
                return
            
            keyboard = []
            for panel in panels:
                keyboard.append([InlineKeyboardButton(
                    f"📤 {panel['name']} ({panel.get('panel_type', '3x-ui')})", 
                    callback_data=f"migrate_source_{panel['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_panels")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🔄 **مهاجرت پنل - مرحله اول**\n\n"
                "لطفاً **پنل مبدا** (پنلی که می‌خواهید کاربران آن را منتقل کنید) را انتخاب کنید:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Clear previous migration data
            context.user_data.clear()
            context.user_data['migration_step'] = 'source'
            
        except Exception as e:
            logger.error(f"Error starting migration: {e}")
            await query.edit_message_text("❌ خطا در شروع مهاجرت.")

    async def handle_migrate_source_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle source panel selection - Select Destination Panel"""
        query = update.callback_query
        await query.answer()
        
        try:
            source_panel = self.db.get_panel(panel_id)
            if not source_panel:
                await query.edit_message_text("❌ پنل مبدا یافت نشد.")
                return
            
            # Save source panel
            context.user_data['migration_source_id'] = panel_id
            context.user_data['migration_source_name'] = source_panel['name']
            
            # Get all panels except source
            panels = self.db.get_all_panels()
            dest_panels = [p for p in panels if p['id'] != panel_id]
            
            if not dest_panels:
                await query.edit_message_text(
                    "❌ پنل دیگری برای مقصد یافت نشد.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
                return
            
            keyboard = []
            for panel in dest_panels:
                keyboard.append([InlineKeyboardButton(
                    f"📥 {panel['name']} ({panel.get('panel_type', '3x-ui')})", 
                    callback_data=f"migrate_dest_{panel['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="migrate_panel_start")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"🔄 **مهاجرت پنل - مرحله دوم**\n\n"
                f"✅ پنل مبدا: **{source_panel['name']}**\n\n"
                "لطفاً **پنل مقصد** (پنلی که کاربران به آن منتقل می‌شوند) را انتخاب کنید:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            context.user_data['migration_step'] = 'dest'
            
        except Exception as e:
            logger.error(f"Error selecting source panel: {e}")
            await query.edit_message_text("❌ خطا در انتخاب پنل مبدا.")

    async def handle_migrate_dest_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle destination panel selection - Confirm Migration"""
        query = update.callback_query
        await query.answer()
        
        try:
            dest_panel = self.db.get_panel(panel_id)
            if not dest_panel:
                await query.edit_message_text("❌ پنل مقصد یافت نشد.")
                return
            
            source_id = context.user_data.get('migration_source_id')
            source_name = context.user_data.get('migration_source_name')
            
            if not source_id:
                await query.edit_message_text("❌ اطلاعات پنل مبدا یافت نشد. لطفاً دوباره تلاش کنید.")
                return
            
            # Save dest panel
            context.user_data['migration_dest_id'] = panel_id
            context.user_data['migration_dest_name'] = dest_panel['name']
            
            keyboard = [
                [InlineKeyboardButton("✅ تأیید و شروع مهاجرت", callback_data="migrate_confirm")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"migrate_source_{source_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"⚠️ **تأیید نهایی مهاجرت**\n\n"
                f"📤 **مبدا:** {source_name}\n"
                f"📥 **مقصد:** {dest_panel['name']}\n\n"
                "آیا از انجام این عملیات اطمینان دارید؟\n"
                "این عملیات ممکن است زمان‌بر باشد.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            context.user_data['migration_step'] = 'confirm'
            
        except Exception as e:
            logger.error(f"Error selecting dest panel: {e}")
            await query.edit_message_text("❌ خطا در انتخاب پنل مقصد.")

    async def handle_migrate_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute migration"""
        query = update.callback_query
        # Don't answer yet, we might need time
        
        try:
            source_id = context.user_data.get('migration_source_id')
            dest_id = context.user_data.get('migration_dest_id')
            source_name = context.user_data.get('migration_source_name')
            dest_name = context.user_data.get('migration_dest_name')
            
            if not all([source_id, dest_id]):
                await query.answer("❌ اطلاعات ناقص است.")
                return
            
            await query.answer("⏳ در حال پردازش...")
            await query.edit_message_text(
                f"⏳ **در حال انجام مهاجرت...**\n\n"
                f"از: {source_name}\n"
                f"به: {dest_name}\n\n"
                "لطفاً صبر کنید. این عملیات ممکن است چند دقیقه طول بکشد.\n"
                "پس از پایان، نتیجه به شما نمایش داده می‌شود.",
                parse_mode='Markdown'
            )
            
            # Run migration in a separate thread to avoid blocking
            # We use asyncio.to_thread to run the synchronous migrate_panel method
            loop = asyncio.get_running_loop()
            success, message, stats = await loop.run_in_executor(
                None, 
                self.admin_manager.migrate_panel, 
                source_id, 
                dest_id
            )
            
            if success:
                details = "\n".join(stats.get('details', [])[:10]) # Show first 10 details
                if len(stats.get('details', [])) > 10:
                    details += f"\n... و {len(stats.get('details', [])) - 10} مورد دیگر"
                
                result_text = (
                    f"✅ **مهاجرت با موفقیت انجام شد!**\n\n"
                    f"📊 **آمار:**\n"
                    f"کل: {stats.get('total', 0)}\n"
                    f"✅ موفق: {stats.get('success', 0)}\n"
                    f"❌ ناموفق: {stats.get('failed', 0)}\n"
                    f"⏭️ نادیده گرفته شده: {stats.get('skipped', 0)}\n\n"
                    f"📝 **جزئیات:**\n{details}"
                )
            else:
                result_text = f"❌ **خطا در مهاجرت:**\n\n{message}"
            
            await query.edit_message_text(
                result_text,
                reply_markup=ButtonLayout.create_back_button("manage_panels"),
                parse_mode='Markdown'
            )
            
            # Clear data
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error executing migration: {e}")
            await query.edit_message_text(
                f"❌ خطای سیستمی در مهاجرت: {str(e)}",
                reply_markup=ButtonLayout.create_back_button("manage_panels")
            )

    async def handle_manage_panels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Alias for show_manage_panels - called from callback query routing"""
        await self.show_manage_panels(update, context)

    async def start_add_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the process of adding a new panel"""
        query = update.callback_query
        await query.answer()
        
        # Clear any previous state to avoid conflicts
        context.user_data.clear()
        context.user_data['adding_panel'] = True
        
        add_text = """
🔧 **اضافه کردن پنل جدید**

لطفاً نوع پنل را انتخاب کنید:

🔵 **3x-ui**: پنل قدرتمند 3x-ui با قابلیت‌های پیشرفته
🟢 **Marzban**: پنل مدرن Marzban با رابط کاربری ساده
🟣 **Rebecca**: پنل مدیریت کاربران Rebecca
🟠 **Pasargad**: پنل مدیریت کاربران Pasargad
        """
        
        reply_markup = ButtonLayout.create_panel_type_selection()
        
        await query.edit_message_text(
            add_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_panel_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_type: str):
        """Handle panel type selection"""
        query = update.callback_query
        await query.answer()
        
        context.user_data['panel_type'] = panel_type
        context.user_data['panel_step'] = 'name'
        
        add_text = f"""
➕ **اضافه کردن پنل جدید ({panel_type})**

لطفاً نام پنل را وارد کنید:

**نکات:**
• نام باید منحصر به فرد باشد
• فقط حروف انگلیسی و اعداد مجاز است
• طول نام باید بین 3 تا 20 کاراکتر باشد

برای لغو عملیات /cancel را ارسال کنید.
        """
        
        keyboard = [
            [InlineKeyboardButton("❌ لغو", callback_data="manage_panels")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            add_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def start_edit_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Start editing a panel"""
        query = update.callback_query
        await query.answer()
        
        panel = self.db.get_panel(panel_id)
        if not panel:
            await query.edit_message_text("❌ پنل یافت نشد.")
            return
        
        edit_text = f"""
✏️ **ویرایش پنل: {panel['name']}**

کدام مورد را می‌خواهید ویرایش کنید؟
        """
        
        keyboard = [
            [InlineKeyboardButton("📝 نام پنل", callback_data=f"edit_name_{panel_id}"), InlineKeyboardButton("🔗 URL پنل", callback_data=f"edit_url_{panel_id}")],
            [InlineKeyboardButton("👤 یوزرنیم", callback_data=f"edit_username_{panel_id}"), InlineKeyboardButton("🔑 پسورد", callback_data=f"edit_password_{panel_id}")],
            [InlineKeyboardButton("🔗 لینک سابسکریپشن", callback_data=f"edit_suburl_{panel_id}"), InlineKeyboardButton("💰 قیمت هر گیگ", callback_data=f"edit_price_{panel_id}")],
            [InlineKeyboardButton("🛒 نوع فروش", callback_data=f"edit_sale_type_{panel_id}"), InlineKeyboardButton("🔗 Inbound ID", callback_data=f"edit_inbound_{panel_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_details_{panel_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            edit_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_edit_panel_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, field: str):
        """Handle editing a specific panel field"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Skip inbound field - it's handled by handle_change_main_inbound_selection
            if field == 'inbound':
                # Redirect to the selection interface
                await self.handle_change_main_inbound_selection(update, context, panel_id)
                return
            
            # Store editing state
            context.user_data['editing_panel'] = True
            context.user_data['panel_id'] = panel_id
            context.user_data['edit_field'] = field
            
            # Create appropriate message based on field
            field_names = {
                'name': 'نام پنل',
                'url': 'URL پنل',
                'username': 'یوزرنیم',
                'password': 'پسورد',
                'subscription_url': 'لینک سابسکریپشن',
                'price': 'قیمت هر گیگابایت'
            }
            
            examples = {
                'name': 'مثال: Germany Server',
                'url': 'مثال: https://panel.example.com:2080',
                'username': 'مثال: admin',
                'password': 'مثال: mypassword123',
                'subscription_url': 'مثال: https://gr.astonnetwork.xyz:2096/sub',
                'price': 'مثال: 15000'
            }
            
            message = f"""
✏️ **ویرایش {field_names.get(field, field)}**

**مقدار فعلی:** {panel.get(field if field != 'price' else 'price_per_gb', 'تنظیم نشده')}

لطفاً مقدار جدید را وارد کنید:

{examples.get(field, '')}

💡 برای لغو عملیات /cancel را ارسال کنید.
            """
            
            await query.edit_message_text(
                message,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling edit panel field: {e}")
            await query.edit_message_text("❌ خطا در شروع ویرایش.")
    
    async def handle_edit_panel_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle text input for panel editing"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ ویرایش لغو شد.")
            context.user_data.clear()
            return
        
        panel_id = context.user_data.get('panel_id')
        field = context.user_data.get('edit_field')
        
        if not panel_id or not field:
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
            context.user_data.clear()
            return
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await update.message.reply_text("❌ پنل یافت نشد.")
                context.user_data.clear()
                return
            
            # Validate and convert input based on field type
            update_dict = {}
            
            if field == 'price':
                try:
                    price = int(text)
                    if price < 0:
                        await update.message.reply_text("❌ قیمت نمی‌تواند منفی باشد. لطفاً عدد صحیح وارد کنید:")
                        return
                    update_dict['price_per_gb'] = price
                except ValueError:
                    await update.message.reply_text("❌ قیمت نامعتبر است. لطفاً عدد صحیح وارد کنید:")
                    return
            elif field == 'url':
                if not self._validate_url(text):
                    await update.message.reply_text("❌ URL نامعتبر است. لطفاً URL صحیح وارد کنید:")
                    return
                update_dict[field] = text
                update_dict['api_endpoint'] = text  # Update api_endpoint too
            elif field == 'subscription_url':
                if not self._validate_url(text):
                    await update.message.reply_text("❌ لینک سابسکریپشن نامعتبر است. لطفاً URL صحیح وارد کنید:")
                    return
                update_dict[field] = text
            else:
                update_dict[field] = text
            
            # Update panel in database
            result = self.db.update_panel(panel_id, **update_dict)
            
            if result:
                field_names = {
                    'name': 'نام پنل',
                    'url': 'URL پنل',
                    'username': 'یوزرنیم',
                    'password': 'پسورد',
                    'subscription_url': 'لینک سابسکریپشن',
                    'price': 'قیمت هر گیگابایت',
                    'inbound': 'Inbound ID'
                }
                
                await update.message.reply_text(
                    f"✅ {field_names.get(field, field)} با موفقیت به‌روزرسانی شد!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔧 مشاهده جزئیات پنل", callback_data=f"panel_details_{panel_id}")
                    ]])
                )
            else:
                await update.message.reply_text("❌ خطا در به‌روزرسانی پنل.")
            
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error updating panel: {e}")
            await update.message.reply_text("❌ خطا در به‌روزرسانی پنل.")
            context.user_data.clear()
    
    async def handle_edit_sale_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle sale type editing"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            current_sale_type = panel.get('sale_type', 'gigabyte')
            sale_type_names = {
                'gigabyte': 'گیگابایتی',
                'plan': 'پلنی',
                'both': 'هر دو'
            }
            
            message = f"""
🛒 **تغییر نوع فروش**

پنل: **{panel['name']}**
نوع فعلی: **{sale_type_names.get(current_sale_type, current_sale_type)}**

نوع فروش جدید را انتخاب کنید:
            """
            
            keyboard = [
                [InlineKeyboardButton("📊 گیگابایتی", callback_data=f"set_sale_type_{panel_id}_gigabyte"), InlineKeyboardButton("📦 پلنی", callback_data=f"set_sale_type_{panel_id}_plan")],
                [InlineKeyboardButton("🔄 هر دو", callback_data=f"set_sale_type_{panel_id}_both")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"edit_panel_{panel_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling edit sale type: {e}")
            await query.edit_message_text("❌ خطا در ویرایش نوع فروش.")
    
    async def handle_set_sale_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, sale_type: str):
        """Set sale type for panel"""
        query = update.callback_query
        await query.answer()
        
        try:
            if self.db.update_panel(panel_id, sale_type=sale_type):
                sale_type_names = {
                    'gigabyte': 'گیگابایتی',
                    'plan': 'پلنی',
                    'both': 'هر دو'
                }
                await query.edit_message_text(
                    f"✅ نوع فروش به '{sale_type_names.get(sale_type, sale_type)}' تغییر کرد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"edit_panel_{panel_id}")]
                    ])
                )
            else:
                await query.edit_message_text("❌ خطا در تغییر نوع فروش.")
        except Exception as e:
            logger.error(f"Error setting sale type: {e}")
            await query.edit_message_text("❌ خطا در تغییر نوع فروش.")
    
    async def confirm_delete_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Confirm panel deletion"""
        query = update.callback_query
        await query.answer()
        
        panel = self.db.get_panel(panel_id)
        if not panel:
            await query.edit_message_text("❌ پنل یافت نشد.")
            return
        
        confirm_text = f"""
⚠️ **تأیید حذف پنل**

آیا مطمئن هستید که می‌خواهید پنل زیر را حذف کنید؟

**نام پنل:** {panel['name']}
**URL:** {panel['url']}

⚠️ **هشدار:** این عمل قابل بازگشت نیست!
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"confirm_delete_panel_{panel_id}"), InlineKeyboardButton("❌ لغو", callback_data=f"panel_details_{panel_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            confirm_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def delete_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Delete a panel"""
        query = update.callback_query
        await query.answer()
        
        success, message = self.admin_manager.delete_panel(panel_id)
        
        if success:
            await query.edit_message_text(f"✅ {message}")
        else:
            await query.edit_message_text(f"❌ {message}")
        
        # Return to panels list after a delay
        await asyncio.sleep(2)
        await self.show_panels_list(update, context)
    
    async def test_panel_connection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Test connection to a specific panel"""
        query = update.callback_query
        await query.answer()
        
        # Show testing message
        testing_msg = await query.edit_message_text("🔄 در حال تست اتصال به پنل...")
        
        try:
            success, message = self.admin_manager.test_panel_connection(panel_id)
            
            if success:
                await testing_msg.edit_text(f"✅ {message}")
            else:
                await testing_msg.edit_text(f"❌ {message}")
            
            # Return to panel details after a delay
            await asyncio.sleep(3)
            await self.show_panel_details(update, context, panel_id)
            
        except Exception as e:
            logger.error(f"Error testing panel connection: {e}")
            await testing_msg.edit_text("❌ خطا در تست اتصال به پنل.")
    
    # User Panel Methods
    @auto_update_user_info
    async def show_buy_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available panels for service purchase"""
        query = update.callback_query
        await query.answer()
        
        panels = self.admin_manager.get_panels_list()
        
        if not panels:
            no_panels_text = """
❌ **هیچ پنلی در دسترس نیست**

لطفاً بعداً تلاش کنید یا با ادمین تماس بگیرید.
            """
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                no_panels_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        panels_text = f"🛒 **خرید سرویس VPN**\n\nپنل مورد نظر را انتخاب کنید:\n\n"
        
        keyboard = []
        for panel in panels:
            if panel['is_active']:
                panel_text = f"🔗 {panel['name']}"
                keyboard.append([InlineKeyboardButton(
                    panel_text, 
                    callback_data=f"select_panel_{panel['id']}"
                )])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            panels_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def show_panel_inbounds(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show inbounds for a specific panel"""
        query = update.callback_query
        await query.answer()
        
        panel = self.db.get_panel(panel_id)
        if not panel:
            await query.edit_message_text("❌ پنل یافت نشد.")
            return
        
        inbounds = self.admin_manager.get_panel_inbounds(panel_id)
        
        if not inbounds:
            no_inbounds_text = f"""
❌ **هیچ اینباندی در پنل {panel['name']} یافت نشد**

لطفاً با ادمین تماس بگیرید.
            """
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="buy_service")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                no_inbounds_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Check if panel has price set
        if not panel.get('price_per_gb', 0):
            await query.edit_message_text(
                "❌ قیمت این پنل تنظیم نشده است. لطفاً با ادمین تماس بگیرید.",
                reply_markup=ButtonLayout.create_back_button("buy_service")
            )
            return
        
        price_per_gb = panel.get('price_per_gb', 0)
        if isinstance(price_per_gb, (int, float)):
            price_text = f"{int(price_per_gb):,} تومان/گیگابایت"
        else:
            price_text = f"{price_per_gb} تومان/گیگابایت"
        
        inbounds_text = f"🔗 **پنل: {panel['name']}**\n💰 **قیمت: {price_text}**\n\nمقدار حجم مورد نیاز را انتخاب کنید:"
        
        # Use professional data plans layout
        reply_markup = ButtonLayout.create_data_plans(panel_id)
        
        await query.edit_message_text(
            inbounds_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def select_inbound_for_purchase(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                        panel_id: int, inbound_id: int):
        """Handle inbound selection for service purchase"""
        query = update.callback_query
        await query.answer()
        
        panel = self.db.get_panel(panel_id)
        if not panel:
            await query.edit_message_text("❌ پنل یافت نشد.")
            return
        
        # Get inbound details
        inbounds = self.admin_manager.get_panel_inbounds(panel_id)
        logger.info(f"Found {len(inbounds)} inbounds for panel {panel_id}")
        selected_inbound = None
        for inbound in inbounds:
            logger.info(f"Inbound data: {inbound}")
            inbound_id_from_data = inbound.get('id')
            logger.info(f"Comparing inbound_id_from_data ({inbound_id_from_data}) with inbound_id ({inbound_id})")
            if inbound_id_from_data == inbound_id:
                selected_inbound = inbound
                break
        
        if not selected_inbound:
            await query.edit_message_text("❌ اینباند یافت نشد.")
            return
        
        inbound_name = selected_inbound.get('remark', f'Inbound {inbound_id}')
        inbound_protocol = selected_inbound.get('protocol', 'unknown')
        inbound_port = selected_inbound.get('port', 0)
        
        # Store selection in user session
        user_id = update.effective_user.id
        self.user_sessions[user_id] = {
            'selected_panel_id': panel_id,
            'selected_inbound_id': inbound_id,
            'panel_name': panel['name']
        }
        
        text = f"""
⚙️ **تنظیمات کلاینت**

**پنل انتخاب شده:** {panel['name']}
**اینباند انتخاب شده:** {inbound_name}
**پروتکل:** `{inbound_protocol}`
**پورت:** `{inbound_port}`

**تنظیمات پیش‌فرض:**
• مدت زمان: نامحدود
• حجم ترافیک: نامحدود

برای ایجاد کلاینت روی دکمه زیر کلیک کنید:
        """
        
        keyboard = [
            [InlineKeyboardButton("🚀 ایجاد کلاینت", callback_data=f"create_client_panel_{panel_id}_{inbound_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"select_panel_{panel_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def create_client_prompt_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                       panel_id: int, inbound_id: int):
        """Prompt user for client name for panel purchase"""
        query = update.callback_query
        await query.answer()
        
        text = """
📝 **نام کلاینت را وارد کنید**

**تنظیمات:**
• مدت زمان: نامحدود
• حجم ترافیک: نامحدود

نام کلاینت باید:
• 3-20 کاراکتر باشد
• فقط شامل حروف، اعداد، خط تیره و زیرخط باشد
• مثال: `my_client`, `user123`, `test-user`

برای لغو عملیات /cancel را ارسال کنید.
        """
        
        keyboard = [
            [InlineKeyboardButton("❌ لغو", callback_data=f"select_inbound_panel_{panel_id}_{inbound_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Set state for client creation
        context.user_data['creating_client_panel'] = True
        context.user_data['panel_id'] = panel_id
        context.user_data['inbound_id'] = inbound_id
    
    @auto_update_user_info
    async def show_user_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user panel with their clients"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        clients = self.db.get_user_clients(user_id)
        
        if not clients:
            no_clients_text = """
📋 **پنل کاربری**

شما هیچ کلاینتی ندارید.

برای خرید سرویس جدید از دکمه زیر استفاده کنید:
            """
            
            # Use ButtonLayout for user panel
            reply_markup = ButtonLayout.create_user_panel_buttons()
            
            await query.edit_message_text(
                no_clients_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        clients_text = f"📋 **پنل کاربری**\n\nکلاینت‌های شما ({len(clients)} عدد):\n\n"
        
        for i, client in enumerate(clients, 1):
            expire_info = f"{client['expire_days']} روز" if client['expire_days'] > 0 else "نامحدود"
            traffic_info = f"{client['total_gb']} گیگابایت" if client['total_gb'] > 0 else "نامحدود"
            
            clients_text += f"{i}. **{escape_markdown(client['client_name'], version=1)}**\n"
            clients_text += f"   پنل: {escape_markdown(client['panel_name'], version=1)}\n"
            clients_text += f"   پروتکل: {escape_markdown(client['protocol'], version=1)}\n"
            clients_text += f"   مدت زمان: {expire_info}\n"
            clients_text += f"   حجم: {traffic_info}\n\n"
        
        # Use ButtonLayout for user panel
        reply_markup = ButtonLayout.create_user_panel_buttons()
        
        await query.edit_message_text(
            clients_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # Text Message Handlers
    async def handle_add_panel_text_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle the flow of adding a new panel via text messages"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ عملیات لغو شد.")
            context.user_data.clear()
            return
        
        step = context.user_data.get('panel_step', 'name')
        
        if step == 'name':
            # Validate panel name
            if not self._validate_panel_name(text):
                await update.message.reply_text(
                    "❌ نام پنل نامعتبر است. لطفاً نام دیگری انتخاب کنید:"
                )
                return
            
            context.user_data['panel_name'] = text
            context.user_data['panel_step'] = 'url'
            
            await update.message.reply_text(
                "🔗 **لینک کامل ورود به پنل را وارد کنید:**\n\nمثال: `https://panel.example.com:2080/username`"
            )
            
        elif step == 'url':
            # Validate URL
            if not self._validate_url(text):
                await update.message.reply_text(
                    "❌ لینک نامعتبر است. لطفاً لینک صحیح وارد کنید:"
                )
                return
            
            context.user_data['panel_url'] = text
            context.user_data['panel_step'] = 'username'
            
            await update.message.reply_text(
                "👤 **یوزرنیم پنل را وارد کنید:**"
            )
            
        elif step == 'username':
            context.user_data['panel_username'] = text
            context.user_data['panel_step'] = 'password'
            
            await update.message.reply_text(
                "🔑 **پسورد پنل را وارد کنید:**"
            )
            
        elif step == 'password':
            context.user_data['panel_password'] = text
            context.user_data['panel_step'] = 'subscription_url'
            
            await update.message.reply_text(
                "🔗 **لینک سابسکریپشن پنل را وارد کنید:**\n\n"
                "مثال: `https://gr.astonnetwork.xyz:2080/sub`\n\n"
                "💡 این لینک برای ارسال کانفیگ‌های سابسکریپشن به کاربران استفاده می‌شود.",
                parse_mode='Markdown'
            )
            
        elif step == 'subscription_url':
            # Validate subscription URL
            if not self._validate_url(text):
                await update.message.reply_text(
                    "❌ لینک سابسکریپشن نامعتبر است. لطفاً لینک صحیح وارد کنید:\n\n"
                    "مثال: `https://gr.astonnetwork.xyz:2080/sub`",
                    parse_mode='Markdown'
                )
                return
            
            context.user_data['panel_subscription_url'] = text
            context.user_data['panel_step'] = 'sale_type'
            
            await update.message.reply_text(
                "🛒 **نوع فروش پنل را انتخاب کنید:**\n\n"
                "• گیگابایتی: فروش بر اساس حجم (مثل قبل)\n"
                "• پلنی: فروش بر اساس پلن‌های تعریف شده\n"
                "• هر دو: هم گیگابایتی و هم پلنی",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 گیگابایتی", callback_data="select_sale_type_gigabyte")],
                    [InlineKeyboardButton("📦 پلنی", callback_data="select_sale_type_plan")],
                    [InlineKeyboardButton("🔄 هر دو", callback_data="select_sale_type_both")],
                    [InlineKeyboardButton("❌ لغو", callback_data="manage_panels")]
                ])
            )
            
        elif step == 'price':
            try:
                price_per_gb = int(text)
                if price_per_gb <= 0:
                    await update.message.reply_text(
                        "❌ قیمت باید بیشتر از صفر باشد. لطفاً قیمت صحیح وارد کنید:"
                    )
                    return
                
                context.user_data['panel_price'] = price_per_gb
                context.user_data['panel_step'] = 'inbound'
                
                panel_type = context.user_data.get('panel_type', '3x-ui')
                
                # For Pasargad, ask for Group
                if panel_type == 'pasargad':
                    panel_url = context.user_data['panel_url']
                    panel_username = context.user_data['panel_username']
                    panel_password = context.user_data['panel_password']
                    
                    await update.message.reply_text("⏳ در حال دریافت لیست گروه‌ها...")
                    
                    try:
                        from pasargad_manager import PasargadPanelManager
                        temp_panel = PasargadPanelManager()
                        temp_panel.base_url = panel_url
                        temp_panel.username = panel_username
                        temp_panel.password = panel_password
                        
                        if temp_panel.login():
                            groups = temp_panel.get_groups()
                            if not groups:
                                await update.message.reply_text("❌ هیچ گروهی یافت نشد.")
                                return
                            
                            keyboard = []
                            for group in groups:
                                keyboard.append([InlineKeyboardButton(
                                    f"📂 {group['name']} (ID: {group['id']})", 
                                    callback_data=f"select_group_for_panel_{group['id']}"
                                )])
                            
                            keyboard.append([InlineKeyboardButton("❌ لغو", callback_data="manage_panels")])
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            await update.message.reply_text(
                                "📂 **لطفاً گروه اصلی (Main Group) را انتخاب کنید:**\n\n"
                                "کاربران جدید در این گروه ساخته خواهند شد.",
                                reply_markup=reply_markup,
                                parse_mode='Markdown'
                            )
                        else:
                            await update.message.reply_text("❌ خطا در اتصال به پنل. لطفاً اطلاعات را بررسی کنید.")
                            context.user_data.clear()
                            return
                            
                    except Exception as e:
                        logger.error(f"Error fetching Pasargad groups: {e}")
                        await update.message.reply_text(f"❌ خطا: {str(e)}")
                        context.user_data.clear()
                        return

                # For Marzban and Rebecca, ask for protocol instead of inbound
                elif panel_type in ['marzban', 'rebecca']:
                    text = "🔗 **انتخاب پروتکل برای ساخت کلاینت‌ها:**\n\n"
                    text += "کاربران از تمامی inbound های پروتکل انتخابی استفاده خواهند کرد.\n\n"
                    
                    keyboard = [
                        [InlineKeyboardButton("🔵 VLESS", callback_data="select_protocol_for_panel_vless")],
                        [InlineKeyboardButton("🟢 VMess", callback_data="select_protocol_for_panel_vmess")],
                        [InlineKeyboardButton("🟣 Trojan", callback_data="select_protocol_for_panel_trojan")],
                        [InlineKeyboardButton("❌ لغو", callback_data="manage_panels")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                else:
                    # For 3x-ui, get inbounds as before
                    panel_url = context.user_data['panel_url']
                    panel_username = context.user_data['panel_username']
                    panel_password = context.user_data['panel_password']
                    
                    # Create temporary panel manager for this panel
                    from panel_manager import PanelManager
                    temp_panel = PanelManager()
                    
                    temp_panel.base_url = panel_url
                    temp_panel.username = panel_username
                    temp_panel.password = panel_password
                    
                    inbounds = temp_panel.get_inbounds()
                    
                    if not inbounds:
                        await update.message.reply_text(
                            f"❌ هیچ inbound فعالی در این پنل 3x-ui یافت نشد. لطفاً پنل را بررسی کنید."
                        )
                        context.user_data.clear()
                        return
                    
                    # Show inbounds for selection
                    text = "🔗 **انتخاب inbound برای ساخت کلاینت‌ها:**\n\n"
                    keyboard = []
                    
                    for inbound in inbounds:
                        inbound_name = inbound.get('remark', f'Inbound {inbound.get("id")}')
                        inbound_protocol = inbound.get('protocol', 'unknown')
                        inbound_port = inbound.get('port', 0)
                        
                        text += f"• **{inbound_name}** ({inbound_protocol}:{inbound_port})\n"
                        keyboard.append([InlineKeyboardButton(
                            f"🔗 {inbound_name} ({inbound_protocol})", 
                            callback_data=f"select_inbound_for_panel_{inbound.get('id')}"
                        )])
                    
                    keyboard.append([InlineKeyboardButton("❌ لغو", callback_data="manage_panels")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                
            except ValueError:
                await update.message.reply_text(
                    "❌ قیمت نامعتبر است. لطفاً عدد صحیح وارد کنید:"
                )
                return
    
    async def handle_create_client_panel_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle the flow of creating a client on a panel"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ عملیات لغو شد.")
            context.user_data.clear()
            return
        
        # Validate client name
        if not self._validate_client_name(text):
            await update.message.reply_text(
                "❌ نام کلاینت نامعتبر است. لطفاً نام دیگری انتخاب کنید:"
            )
            return
        
        panel_id = context.user_data.get('panel_id')
        inbound_id = context.user_data.get('inbound_id')
        
        # Show creating message
        creating_msg = await update.message.reply_text("⏳ در حال ایجاد کلاینت...")
        
        try:
            # Create client on all inbounds of panel with shared subscription ID
            success, message, client = self.admin_manager.create_client_on_all_panel_inbounds(
                panel_id=panel_id,
                client_name=text,
                expire_days=0,  # Unlimited
                total_gb=0      # Unlimited
            )
            
            if success and client:
                # Add client to database
                user_id = update.effective_user.id
                user = self.db.get_user(user_id)
                if user:
                    self.db.add_client(
                        user_id=user['id'],
                        panel_id=panel_id,
                        client_name=text,
                        client_uuid=client.get('id', ''),
                        inbound_id=client.get('inbound_id', 1),
                        protocol=client.get('protocol', 'vmess'),
                        expire_days=0,
                        total_gb=0,
                        sub_id=client.get('sub_id')  # Store sub_id in database
                    )
                
                # Get subscription link
                subscription_link = client.get('subscription_link') or client.get('subscription_url', client.get('config_link', ''))
                
                # Format success message
                success_text = f"""
✅ **کلاینت با موفقیت ایجاد شد!**

**نام کلاینت:** `{text}`
**پنل:** {client.get('panel_name', 'Unknown')}
**پروتکل:** `{client.get('protocol', 'vmess')}`
**مدت زمان:** نامحدود
**حجم ترافیک:** نامحدود
**تعداد اینباندها:** {client.get('created_on_inbounds', 0)}

🔗 **لینک سابسکریپشن:**
```
{subscription_link}
```

**نکات:**
• لینک سابسکریپشن را در برنامه VPN خود اضافه کنید
• برای پشتیبانی با ادمین تماس بگیرید
                """
                
                keyboard = [
                    [InlineKeyboardButton("🛒 خرید جدید", callback_data="buy_service")],
                    [InlineKeyboardButton("📋 پنل", callback_data="user_panel")],
                    [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await creating_msg.edit_text(
                    success_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await creating_msg.edit_text(f"❌ {message}")
            
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error creating client on panel: {e}")
            await creating_msg.edit_text("❌ خطا در ایجاد کلاینت. لطفاً دوباره تلاش کنید.")
            context.user_data.clear()
    
    def _validate_panel_name(self, name: str) -> bool:
        """Validate panel name"""
        if not name or len(name) < 3 or len(name) > 20:
            return False
        
        # Check if name contains only alphanumeric characters and spaces
        return name.replace(' ', '').replace('-', '').replace('_', '').isalnum()
    
    def _validate_url(self, url: str) -> bool:
        """Validate URL"""
        import re
        pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return bool(re.match(pattern, url))
    
    # Payment System Methods
    async def handle_gb_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                panel_id: int, gb_amount: int):
        """Handle GB selection for purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get panel details
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Calculate total amount
            price_per_gb = panel.get('price_per_gb', 0) or 0
            total_amount = gb_amount * price_per_gb
            
            # Get user ID
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if this is a renewal
            if context.user_data.get('renewing_service', False):
                # This is a renewal, not a new purchase
                renew_service_id = context.user_data.get('renew_service_id')
                context.user_data['renew_gb_amount'] = gb_amount
                
                # Create invoice for renewal
                invoice_result = self.payment_manager.create_invoice(
                    user_id, panel_id, gb_amount, total_amount
                )
                
                # Show discount code entry screen for renewal too
                text = f"""
🔄 **تمدید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📊 **حجم تمدید:** {gb_amount} گیگابایت
💰 **قیمت هر گیگابایت:** {price_per_gb:,} تومان
💵 **مبلغ کل:** {total_amount:,} تومان

🎁 اگر کد تخفیف دارید، از دکمه زیر استفاده کنید:
                """
                
                keyboard = [
                    [InlineKeyboardButton("🏷️ وارد کردن کد تخفیف", callback_data=f"enter_discount_code_renew_{panel_id}_{gb_amount}")],
                    [InlineKeyboardButton("⏭️ ادامه بدون کد تخفیف", callback_data=f"continue_without_discount_renew_{panel_id}_{gb_amount}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="user_panel")]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return
            
            # Store purchase info for discount code entry
            context.user_data['purchase_panel_id'] = panel_id
            context.user_data['purchase_gb_amount'] = gb_amount
            context.user_data['purchase_total_amount'] = total_amount
            context.user_data['purchase_price_per_gb'] = price_per_gb
            
            # Show discount code entry screen
            text = f"""
💳 **فاکتور خرید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📊 **حجم:** {gb_amount} گیگابایت
💰 **قیمت هر گیگابایت:** {price_per_gb:,} تومان
💵 **مبلغ کل:** {total_amount:,} تومان

🎁 اگر کد تخفیف دارید، از دکمه زیر استفاده کنید:
            """
            
            keyboard = [
                [InlineKeyboardButton("🏷️ وارد کردن کد تخفیف", callback_data=f"enter_discount_code_{panel_id}_{gb_amount}")],
                [InlineKeyboardButton("⏭️ ادامه بدون کد تخفیف", callback_data=f"continue_without_discount_{panel_id}_{gb_amount}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="buy_service")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling GB selection: {e}")
            await query.edit_message_text("❌ خطا در پردازش انتخاب حجم.")
    
    async def handle_enter_discount_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                         panel_id: int, gb_amount: int):
        """Handle discount code entry request"""
        query = update.callback_query
        await query.answer()
        
        try:
            context.user_data['waiting_for_discount_code'] = True
            context.user_data['discount_panel_id'] = panel_id
            context.user_data['discount_gb_amount'] = gb_amount
            
            text = """
🏷️ **وارد کردن کد تخفیف**

لطفاً کد تخفیف خود را ارسال کنید:

⚠️ توجه: کد تخفیف فقط یک بار قابل استفاده است و باید قبل از پرداخت وارد شود.

برای لغو: /cancel
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"continue_without_discount_{panel_id}_{gb_amount}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling discount code entry: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_continue_without_discount(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                              panel_id: int, gb_amount: int):
        """Continue purchase without discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear discount code waiting state
            context.user_data.pop('waiting_for_discount_code', None)
            context.user_data.pop('discount_panel_id', None)
            context.user_data.pop('discount_gb_amount', None)
            
            # Create invoice and show payment options
            await self.create_invoice_and_show_payment(update, context, panel_id, gb_amount, None)
            
        except Exception as e:
            logger.error(f"Error continuing without discount: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_enter_discount_code_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Handle discount code entry request for product purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            context.user_data['waiting_for_discount_code_product'] = True
            context.user_data['discount_product_id'] = product_id
            
            text = """
🏷️ **وارد کردن کد تخفیف یا کد هدیه**

لطفاً کد تخفیف یا کد هدیه خود را ارسال کنید:

⚠️ توجه: کد تخفیف فقط یک بار قابل استفاده است و باید قبل از پرداخت وارد شود.

💡 کد هدیه: موجودی حساب شما را افزایش می‌دهد
💡 کد تخفیف: روی مبلغ خرید شما تخفیف اعمال می‌کند

برای لغو: /cancel
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"continue_without_discount_product_{product_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling discount code entry for product: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_continue_without_discount_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Continue product purchase without discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear discount code waiting state
            context.user_data.pop('waiting_for_discount_code_product', None)
            context.user_data.pop('discount_product_id', None)
            
            # Create invoice and show payment options for product
            await self.create_invoice_and_show_payment_product(update, context, product_id, None)
            
        except Exception as e:
            logger.error(f"Error continuing product purchase without discount: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def create_invoice_and_show_payment_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                     product_id: int, discount_code: str = None):
        """Create invoice for product purchase and show payment options"""
        try:
            product = self.db.get_product(product_id)
            if not product or not product.get('is_active'):
                await update.callback_query.edit_message_text("❌ محصول یافت نشد یا غیرفعال است.")
                return
            
            panel = self.db.get_panel(product['panel_id'])
            if not panel:
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Calculate amounts
            original_amount = product['price']
            final_amount = original_amount
            discount_amount = 0
            
            # Apply discount if exists
            if discount_code:
                from discount_manager import DiscountManager
                discount_manager = DiscountManager(self.db)
                discount_result = discount_manager.validate_and_apply_discount(discount_code, user_id, original_amount)
                
                if discount_result['success']:
                    final_amount = discount_result['final_amount']
                    discount_amount = discount_result['discount_amount']
            
            # Create invoice - for products, we use gb_amount as volume_gb and add duration_days
            # We'll need to modify add_invoice to support product purchases
            # For now, use gb_amount as volume_gb
            invoice_result = self.payment_manager.create_invoice(
                user_id, product['panel_id'], product['volume_gb'], final_amount, 'gateway', discount_code
            )
            
            if not invoice_result['success']:
                await update.callback_query.edit_message_text(f"❌ {invoice_result['message']}")
                return
            
            # Store product info for client creation
            invoice_id = invoice_result['invoice_id']
            self.db.update_invoice_product_info(invoice_id, product_id, product['duration_days'])
            
            # Show payment options
            text = f"""
💳 **فاکتور خرید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📦 **محصول:** {escape_markdown(product['name'], version=1)}
📊 **حجم:** {product['volume_gb']} گیگابایت
⏱️ **مدت زمان:** {product['duration_days']} روز
"""
            
            if discount_amount > 0:
                text += f"""
💵 **مبلغ قبل از تخفیف:** {original_amount:,} تومان
🎁 **تخفیف:** {discount_amount:,} تومان
💵 **مبلغ قابل پرداخت:** {final_amount:,} تومان
"""
            else:
                text += f"💵 **مبلغ کل:** {original_amount:,} تومان\n"
            
            text += "\nروش پرداخت را انتخاب کنید:"
            
            # Get user balance
            user_balance = self.payment_manager.get_user_balance(user_id)
            
            reply_markup = ButtonLayout.create_payment_method_buttons(
                invoice_id, user_balance, final_amount
            )
            
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error creating invoice for product: {e}")
            await update.callback_query.edit_message_text("❌ خطا در ایجاد فاکتور.")
    
    async def create_client_from_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice: dict):
        """Create client from product purchase"""
        try:
            logger.info(f"🔍 Starting create_client_from_product for invoice {invoice['id']}")
            
            # Get product info from invoice
            product_id = invoice.get('product_id')
            if not product_id:
                logger.error("Product ID not found in invoice")
                await update.callback_query.edit_message_text("❌ اطلاعات محصول یافت نشد.")
                return
            
            product = self.db.get_product(product_id)
            if not product:
                logger.error(f"Product {product_id} not found")
                await update.callback_query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            # Get panel details
            panel = self.db.get_panel(invoice['panel_id'])
            if not panel:
                logger.error(f"Panel {invoice['panel_id']} not found")
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            logger.info(f"✅ Panel found: {panel['name']}")
            
            # Get user details
            user = self.db.get_user_by_id(invoice['user_id'])
            if not user:
                logger.error(f"User {invoice['user_id']} not found")
                await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            logger.info(f"✅ User found: {user['telegram_id']}")
            
            # Generate professional client name
            client_name = UsernameFormatter.format_client_name(
                telegram_id=user['telegram_id'],
                username=user.get('username'),
                first_name=user.get('first_name'),
                service_type="VPN"
            )
            
            # Calculate expiration date
            expire_days = product['duration_days']
            expires_at = datetime.now() + timedelta(days=expire_days) if expire_days > 0 else None
            
            logger.info(f"🔍 Creating client on all inbounds of panel:")
            logger.info(f"   Panel ID: {invoice['panel_id']}")
            logger.info(f"   Client name: {client_name}")
            logger.info(f"   Volume GB: {product['volume_gb']}")
            logger.info(f"   Expire days: {expire_days}")
            
            # Create client on all inbounds of panel with shared subscription ID
            success, message, client_data = self.admin_manager.create_client_on_all_panel_inbounds(
                panel_id=invoice['panel_id'],
                client_name=client_name,
                expire_days=expire_days,
                total_gb=product['volume_gb']
            )
            
            logger.info(f"🔍 create_client_on_panel result:")
            logger.info(f"   Success: {success}")
            logger.info(f"   Message: {message}")
            logger.info(f"   Client data keys: {list(client_data.keys()) if client_data else 'None'}")
            
            if not success:
                logger.error(f"❌ Client creation failed: {message}")
                await update.callback_query.edit_message_text(f"❌ خطا در ایجاد کلاینت: {message}")
                return
            
            if success and client_data:
                logger.info("✅ Client created successfully, saving to database...")
                
                # Save client to database
                client_id = self.db.add_client(
                    user_id=invoice['user_id'],
                    panel_id=invoice['panel_id'],
                    client_name=client_name,
                    client_uuid=client_data.get('id', ''),
                    inbound_id=panel.get('default_inbound_id', 1),
                    protocol=client_data.get('protocol', 'vless'),
                    expire_days=expire_days,
                    total_gb=product['volume_gb'],
                    expires_at=expires_at,
                    sub_id=client_data.get('sub_id')
                )
                
                if client_id > 0:
                    logger.info(f"✅ Client saved to database with ID: {client_id}")
                    
                    # Get subscription link
                    subscription_link = client_data.get('subscription_link') or client_data.get('config_link') or client_data.get('subscription_url')
                    
                    # If still empty, try to construct it from panel subscription_url
                    if not subscription_link and client_data.get('sub_id'):
                        sub_url = panel.get('subscription_url', '')
                        if sub_url:
                            # Clean up sub_url
                            if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                                base_url = sub_url.rstrip('/')
                                subscription_link = f"{base_url}/{client_data['sub_id']}"
                            elif '/sub' in sub_url:
                                subscription_link = f"{sub_url}/{client_data['sub_id']}"
                            else:
                                subscription_link = f"{sub_url}/sub/{client_data['sub_id']}"
                            
                            logger.info(f"✅ Constructed subscription link: {subscription_link}")
                    
                    # Format success message
                    success_text = f"""
✅ **سرویس با موفقیت فعال شد!**

**نام سرویس:** `{client_name}`
**پنل:** {panel['name']}
**محصول:** {product['name']}
**حجم:** {product['volume_gb']} گیگابایت
**مدت زمان:** {product['duration_days']} روز
**پروتکل:** `{client_data.get('protocol', 'vless')}`

🔗 **لینک سابسکریپشن:**
```
{subscription_link}
```

**نکات:**
• لینک سابسکریپشن را در برنامه VPN خود اضافه کنید
• برای مشاهده سرویس‌های خود از پنل کاربری استفاده کنید
                    """
                    
                    keyboard = [
                        [InlineKeyboardButton("📊 پنل کاربری", callback_data="user_panel")],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.callback_query.edit_message_text(
                        success_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                    
                    # Report service purchase
                    try:
                        user_data = self.db.get_user(user['telegram_id'])
                        if self.reporting_system:
                            service_data = {
                                'service_name': client_name,
                                'data_amount': product['volume_gb'],
                                'amount': invoice['amount'],
                                'panel_name': panel['name'],
                                'duration_days': product['duration_days'],
                                'product_name': product['name'],
                                'purchase_type': 'plan',
                                'payment_method': 'gateway'  # This is from gateway payment callback
                            }
                            await self.reporting_system.report_service_purchased(user_data, service_data)
                    except Exception as e:
                        logger.error(f"Error reporting service purchase: {e}")
                else:
                    logger.error("❌ Failed to save client to database")
                    await update.callback_query.edit_message_text("❌ خطا در ذخیره کلاینت در دیتابیس.")
                    
        except Exception as e:
            logger.error(f"❌ Error creating client from product: {e}", exc_info=True)
            await update.callback_query.edit_message_text("❌ خطا در ایجاد کلاینت از محصول.")
    
    async def handle_enter_discount_code_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                panel_id: int, volume_gb: int, price: int):
        """Handle discount code entry request for volume purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            context.user_data['waiting_for_discount_code_volume'] = True
            context.user_data['discount_panel_id'] = panel_id
            context.user_data['discount_volume_gb'] = volume_gb
            context.user_data['discount_price'] = price
            
            text = """
🏷️ **وارد کردن کد تخفیف یا کد هدیه**

لطفاً کد تخفیف یا کد هدیه خود را ارسال کنید:

⚠️ توجه: کد تخفیف فقط یک بار قابل استفاده است و باید قبل از پرداخت وارد شود.

💡 کد هدیه: موجودی حساب شما را افزایش می‌دهد
💡 کد تخفیف: روی مبلغ خرید شما تخفیف اعمال می‌کند

برای لغو: /cancel
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"continue_without_discount_volume_{panel_id}_{volume_gb}_{price}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling discount code entry volume: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_continue_without_discount_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                      panel_id: int, volume_gb: int, price: int):
        """Continue volume purchase without discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear discount code waiting state
            context.user_data.pop('waiting_for_discount_code_volume', None)
            context.user_data.pop('discount_panel_id', None)
            context.user_data.pop('discount_volume_gb', None)
            context.user_data.pop('discount_price', None)
            context.user_data.pop('applied_discount_code', None)
            context.user_data.pop('discount_amount', None)
            context.user_data.pop('original_amount', None)
            
            # Show payment options again
            await self.handle_volume_purchase_options(update, context, panel_id, volume_gb, price)
            
        except Exception as e:
            logger.error(f"Error continuing without discount volume: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_enter_discount_code_add_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                    service_id: int, panel_id: int, volume_gb: int, price: int):
        """Handle discount code entry request for adding volume to existing service"""
        query = update.callback_query
        await query.answer()
        
        try:
            context.user_data['waiting_for_discount_code_add_volume'] = True
            context.user_data['discount_add_volume_service_id'] = service_id
            context.user_data['discount_panel_id'] = panel_id
            context.user_data['discount_volume_gb'] = volume_gb
            context.user_data['discount_price'] = price
            
            text = """
🏷️ **وارد کردن کد تخفیف یا کد هدیه**

لطفاً کد تخفیف یا کد هدیه خود را ارسال کنید:

⚠️ توجه: کد تخفیف فقط یک بار قابل استفاده است و باید قبل از پرداخت وارد شود.

💡 کد هدیه: موجودی حساب شما را افزایش می‌دهد
💡 کد تخفیف: روی مبلغ خرید شما تخفیف اعمال می‌کند

برای لغو: /cancel
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"continue_without_discount_add_volume_{service_id}_{panel_id}_{volume_gb}_{price}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling discount code entry add volume: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_continue_without_discount_add_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                         service_id: int, panel_id: int, volume_gb: int, price: int):
        """Continue adding volume without discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear discount code waiting state
            context.user_data.pop('waiting_for_discount_code_add_volume', None)
            context.user_data.pop('discount_add_volume_service_id', None)
            context.user_data.pop('discount_panel_id', None)
            context.user_data.pop('discount_volume_gb', None)
            context.user_data.pop('discount_price', None)
            context.user_data.pop('applied_discount_code', None)
            context.user_data.pop('discount_amount', None)
            context.user_data.pop('original_amount', None)
            
            # Show payment options again
            await self.handle_add_volume_purchase_options(update, context, service_id, panel_id, volume_gb, price)
            
        except Exception as e:
            logger.error(f"Error continuing without discount add volume: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def validate_and_apply_discount_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                              panel_id: int, gb_amount: int, code: str):
        """Validate and apply discount code"""
        try:
            user_id = update.effective_user.id
            
            # Get panel details
            panel = self.db.get_panel(panel_id)
            if not panel:
                await update.message.reply_text("❌ پنل یافت نشد.")
                return
            
            # Calculate total amount
            price_per_gb = panel.get('price_per_gb', 0) or 0
            total_amount = gb_amount * price_per_gb
            
            # Validate discount code
            from discount_manager import DiscountCodeManager
            discount_manager = DiscountCodeManager(self.db)
            
            discount_result = discount_manager.validate_and_apply_discount(code, user_id, total_amount)
            
            if discount_result['success']:
                # Store discount info
                context.user_data['applied_discount_code'] = code
                context.user_data['discount_amount'] = discount_result['discount_amount']
                context.user_data['original_amount'] = total_amount
                context.user_data['final_amount'] = discount_result['final_amount']
                
                # Create invoice with discount
                await self.create_invoice_and_show_payment(update, context, panel_id, gb_amount, code)
            else:
                await update.message.reply_text(f"❌ {discount_result.get('message', 'کد تخفیف نامعتبر است')}")
                
        except Exception as e:
            logger.error(f"Error validating discount code: {e}")
            await update.message.reply_text("❌ خطا در بررسی کد تخفیف.")
    
    async def validate_and_apply_discount_code_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                     product_id: int, code: str):
        """Validate and apply discount code for product purchase"""
        try:
            product = self.db.get_product(product_id)
            if not product or not product.get('is_active'):
                await update.message.reply_text("❌ محصول یافت نشد یا غیرفعال است.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            original_amount = product['price']
            
            from discount_manager import DiscountManager
            discount_manager = DiscountManager(self.db)
            
            # First try as gift code
            gift_result = discount_manager.validate_and_apply_gift_code(code, user_id)
            
            if gift_result['success']:
                # Gift code applied successfully
                new_balance = self.db.get_user(user_id).get('balance', 0)
                await update.message.reply_text(
                    f"✅ کد هدیه اعمال شد!\n\n"
                    f"💰 مبلغ هدیه: {gift_result['amount']:,} تومان\n"
                    f"💵 موجودی جدید: {new_balance:,} تومان\n\n"
                    f"💡 لطفاً دوباره به بخش خرید برگردید و پرداخت را انجام دهید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📦 بازگشت به خرید", callback_data=f"buy_product_{product_id}")]
                    ])
                )
                return
            
            # If not gift code, try as discount code
            discount_result = discount_manager.validate_and_apply_discount(code, user_id, original_amount)
            
            if discount_result['success']:
                # Store discount info
                context.user_data['applied_discount_code'] = code
                context.user_data['discount_amount'] = discount_result['discount_amount']
                context.user_data['original_amount'] = original_amount
                context.user_data['final_amount'] = discount_result['final_amount']
                
                # Create invoice with discount and show payment options
                await self.create_invoice_and_show_payment_product(update, context, product_id, code)
            else:
                await update.message.reply_text(
                    f"❌ {discount_result.get('message', 'کد نامعتبر است')}\n\n"
                    f"💡 لطفاً کد تخفیف یا کد هدیه را دوباره وارد کنید."
                )
                
        except Exception as e:
            logger.error(f"Error validating discount code for product: {e}")
            await update.message.reply_text("❌ خطا در بررسی کد.")
    
    async def validate_and_apply_discount_code_product_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                              product_id: int, service_id: int, code: str):
        """Validate and apply discount code for product renewal"""
        try:
            product = self.db.get_product(product_id)
            if not product or not product.get('is_active'):
                await update.message.reply_text("❌ محصول یافت نشد یا غیرفعال است.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            original_amount = product['price']
            
            from discount_manager import DiscountManager
            discount_manager = DiscountManager(self.db)
            
            # First try as gift code
            gift_result = discount_manager.validate_and_apply_gift_code(code, user_id)
            
            if gift_result['success']:
                # Gift code applied successfully
                new_balance = self.db.get_user(user_id).get('balance', 0)
                await update.message.reply_text(
                    f"✅ کد هدیه اعمال شد!\n\n"
                    f"💰 مبلغ هدیه: {gift_result['amount']:,} تومان\n"
                    f"💵 موجودی جدید: {new_balance:,} تومان\n\n"
                    f"💡 لطفاً دوباره به بخش تمدید برگردید و پرداخت را انجام دهید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 بازگشت به تمدید", callback_data=f"renew_product_{product_id}_{service_id}")]
                    ])
                )
                return
            
            # If not gift code, try as discount code
            discount_result = discount_manager.validate_and_apply_discount(code, user_id, original_amount)
            
            if discount_result['success']:
                # Store discount info
                context.user_data['applied_discount_code'] = code
                context.user_data['discount_amount'] = discount_result['discount_amount']
                context.user_data['original_amount'] = original_amount
                context.user_data['final_amount'] = discount_result['final_amount']
                
                # Create invoice with discount and show payment options
                await self.create_invoice_and_show_payment_product_renewal(update, context, product_id, service_id, code)
            else:
                await update.message.reply_text(
                    f"❌ {discount_result.get('message', 'کد نامعتبر است')}\n\n"
                    f"💡 لطفاً کد تخفیف یا کد هدیه را دوباره وارد کنید."
                )
                
        except Exception as e:
            logger.error(f"Error validating discount code for product renewal: {e}")
            await update.message.reply_text("❌ خطا در بررسی کد.")
    
    async def validate_and_apply_discount_code_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                     panel_id: int, volume_gb: int, price: int, code: str):
        """Validate and apply discount code or gift code for volume purchase"""
        try:
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            from discount_manager import DiscountCodeManager
            discount_manager = DiscountCodeManager(self.db)
            
            # First try as gift code
            gift_result = discount_manager.validate_and_apply_gift_code(code, user_id)
            
            if gift_result['success']:
                # Gift code applied successfully
                new_balance = self.db.get_user(user_id).get('balance', 0)
                await update.message.reply_text(
                    f"✅ کد هدیه اعمال شد!\n\n"
                    f"💰 مبلغ هدیه: {gift_result['amount']:,} تومان\n"
                    f"💵 موجودی جدید: {new_balance:,} تومان"
                )
                
                # Show payment options again with updated balance
                await self.handle_volume_purchase_options(update, context, panel_id, volume_gb, price)
                return
            
            # If not gift code, try as discount code
            discount_result = discount_manager.validate_and_apply_discount(code, user_id, price)
            
            if discount_result['success']:
                # Store discount info
                context.user_data['applied_discount_code'] = code
                context.user_data['discount_amount'] = discount_result['discount_amount']
                context.user_data['original_amount'] = price
                context.user_data['final_amount'] = discount_result['final_amount']
                
                # Show payment options with discount applied (message includes discount info)
                await self.handle_volume_purchase_options(update, context, panel_id, volume_gb, price)
            else:
                # Neither gift code nor discount code worked
                await update.message.reply_text(
                    f"❌ {discount_result.get('message', 'کد نامعتبر است')}\n\n"
                    f"💡 لطفاً کد تخفیف یا کد هدیه را دوباره وارد کنید."
                )
                
        except Exception as e:
            logger.error(f"Error validating discount/gift code volume: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text("❌ خطا در بررسی کد.")
    
    async def validate_and_apply_discount_code_add_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                         service_id: int, panel_id: int, volume_gb: int, price: int, code: str):
        """Validate and apply discount code or gift code for adding volume to existing service"""
        try:
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            from discount_manager import DiscountCodeManager
            discount_manager = DiscountCodeManager(self.db)
            
            # First try as gift code
            gift_result = discount_manager.validate_and_apply_gift_code(code, user_id)
            
            if gift_result['success']:
                # Gift code applied successfully
                new_balance = self.db.get_user(user_id).get('balance', 0)
                await update.message.reply_text(
                    f"✅ کد هدیه اعمال شد!\n\n"
                    f"💰 مبلغ هدیه: {gift_result['amount']:,} تومان\n"
                    f"💵 موجودی جدید: {new_balance:,} تومان"
                )
                
                # Show payment options again with updated balance
                await self.handle_add_volume_purchase_options(update, context, service_id, panel_id, volume_gb, price)
                return
            
            # If not gift code, try as discount code
            discount_result = discount_manager.validate_and_apply_discount(code, user_id, price)
            
            if discount_result['success']:
                # Store discount info
                context.user_data['applied_discount_code'] = code
                context.user_data['discount_amount'] = discount_result['discount_amount']
                context.user_data['original_amount'] = price
                context.user_data['final_amount'] = discount_result['final_amount']
                
                # Show payment options with discount applied
                await self.handle_add_volume_purchase_options(update, context, service_id, panel_id, volume_gb, price)
            else:
                # Neither gift code nor discount code worked
                await update.message.reply_text(
                    f"❌ {discount_result.get('message', 'کد نامعتبر است')}\n\n"
                    f"💡 لطفاً کد تخفیف یا کد هدیه را دوباره وارد کنید."
                )
                
        except Exception as e:
            logger.error(f"Error validating discount/gift code add volume: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text("❌ خطا در بررسی کد.")
    
    async def create_invoice_and_show_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                             panel_id: int, gb_amount: int, discount_code: str = None):
        """Create invoice and show payment options"""
        try:
            user_id = update.effective_user.id
            
            # Get panel details
            panel = self.db.get_panel(panel_id)
            if not panel:
                await update.message.reply_text("❌ پنل یافت نشد.")
                return
            
            # Calculate amounts
            price_per_gb = panel.get('price_per_gb', 0) or 0
            original_amount = gb_amount * price_per_gb
            final_amount = original_amount
            
            # Apply discount if exists
            if discount_code:
                final_amount = context.user_data.get('final_amount', original_amount)
                discount_amount = context.user_data.get('discount_amount', 0)
            else:
                discount_amount = 0
            
            # Create invoice
            invoice_result = self.payment_manager.create_invoice(
                user_id, panel_id, gb_amount, final_amount, 'gateway', discount_code
            )
            
            if not invoice_result['success']:
                await update.message.reply_text(f"❌ {invoice_result['message']}")
                return
            
            # Check if this is a renewal
            if context.user_data.get('renewing_service', False):
                context.user_data['renew_invoice_id'] = invoice_result['invoice_id']
                context.user_data['renew_gb_amount'] = gb_amount
            
            # Show payment options
            text = f"""
💳 **فاکتور خرید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📊 **حجم:** {gb_amount} گیگابایت
💰 **قیمت هر گیگابایت:** {price_per_gb:,} تومان
"""
            
            if discount_amount > 0:
                text += f"""
💵 **مبلغ قبل از تخفیف:** {original_amount:,} تومان
🎁 **تخفیف:** {discount_amount:,} تومان
💵 **مبلغ قابل پرداخت:** {final_amount:,} تومان
"""
            else:
                text += f"💵 **مبلغ کل:** {original_amount:,} تومان\n"
            
            text += "\nروش پرداخت را انتخاب کنید:"
            
            # Get user balance
            user_balance = self.payment_manager.get_user_balance(user_id)
            
            reply_markup = ButtonLayout.create_payment_method_buttons(
                invoice_result['invoice_id'], user_balance, final_amount
            )
            
            if isinstance(update, Update) and update.message:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Clear discount info
            context.user_data.pop('applied_discount_code', None)
            context.user_data.pop('discount_amount', None)
            context.user_data.pop('original_amount', None)
            context.user_data.pop('final_amount', None)
            
        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text("❌ خطا در ایجاد فاکتور.")
    
    async def handle_balance_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: int):
        """Handle payment using user balance"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            logger.info(f"🔍 Processing balance payment for user {user_id}, invoice {invoice_id}")
            
            # Process payment
            payment_result = self.payment_manager.process_balance_payment(user_id, invoice_id)
            
            if payment_result['success']:
                logger.info("✅ Payment processed successfully")
                
                # Check if this is a renewal
                if context.user_data.get('renewing_service', False):
                    logger.info("🔄 This is a service renewal")
                    # Handle service renewal
                    await self.handle_service_renewal(update, context, invoice_id)
                else:
                    logger.info("🆕 This is a new service purchase")
                    try:
                        # Get invoice details
                        invoice = self.db.get_invoice(invoice_id)
                        if invoice:
                            logger.info(f"✅ Invoice found: {invoice['gb_amount']} GB for {invoice['amount']} Toman")
                            # Check if this is a product purchase
                            purchase_type = invoice.get('purchase_type', 'gigabyte')
                            if purchase_type == 'plan' and invoice.get('product_id'):
                                # This is a product purchase
                                await self.create_client_from_product(update, context, invoice)
                            else:
                                # This is a gigabyte purchase
                                await self.create_client_from_invoice(update, context, invoice)
                        else:
                            logger.error("❌ Invoice not found after payment")
                            await query.edit_message_text("✅ پرداخت انجام شد اما خطا در ایجاد سرویس.")
                    except Exception as client_err:
                        logger.error(f"❌ Client creation failed after balance payment: {client_err}")
                        # Refund user balance to prevent loss
                        try:
                            # Get invoice for refund
                            invoice = self.db.get_invoice(invoice_id)
                            if invoice:
                                # Update user balance in database
                                self.db.update_user_balance(user_id, invoice['amount'], 'balance_added', 'شارژ حساب - پرداخت موفق')
                                self.db.update_invoice_status(invoice_id, 'refunded')
                                logger.info("✅ Refund processed successfully")
                        except Exception as refund_err:
                            logger.error(f"❌ Failed to refund after client creation error: {refund_err}")
                        await query.edit_message_text("❌ خطا در ایجاد سرویس پس از پرداخت. مبلغ به کیف پول شما بازگشت داده شد.")
                        return
            else:
                logger.error(f"❌ Payment failed: {payment_result['message']}")
                await query.edit_message_text(f"❌ {payment_result['message']}")
                
        except Exception as e:
            logger.error(f"❌ Error handling balance payment: {e}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در پردازش پرداخت.")
    
    async def handle_service_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: int):
        """Handle service renewal after payment"""
        try:
            logger.info(f"🔍 Starting service renewal for invoice {invoice_id}")
            
            renew_service_id = context.user_data.get('renew_service_id')
            renew_gb_amount = context.user_data.get('renew_gb_amount', 0)
            renew_product_id = context.user_data.get('renew_product_id')
            renew_invoice_id = context.user_data.get('renew_invoice_id', invoice_id)
            is_expired = context.user_data.get('renew_is_expired', False)
            
            logger.info(f"🔍 Renewal details:")
            logger.info(f"   Service ID: {renew_service_id}")
            logger.info(f"   GB Amount: {renew_gb_amount}")
            logger.info(f"   Product ID: {renew_product_id}")
            logger.info(f"   Invoice ID: {renew_invoice_id}")
            logger.info(f"   Is Expired: {is_expired}")
            
            # Get invoice to check if it's a product renewal
            invoice = self.db.get_invoice(invoice_id)
            if not invoice:
                logger.error("❌ Invoice not found")
                await update.callback_query.edit_message_text("❌ فاکتور یافت نشد.")
                return
            
            # Check if this is a product-based renewal
            if invoice.get('product_id') and renew_product_id:
                await self.handle_product_service_renewal(update, context, invoice_id, renew_service_id, renew_product_id, is_expired)
                return
            
            # Otherwise, handle gigabyte-based renewal
            if not renew_service_id or not renew_gb_amount:
                logger.error("❌ Missing renewal information")
                await update.callback_query.edit_message_text("❌ اطلاعات تمدید یافت نشد.")
                return
            
            # Get service details
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                logger.error(f"❌ User {user_id} not found")
                await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            logger.info(f"✅ User found: {user['telegram_id']}")
            
            # Get service from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT c.*, p.name as panel_name, p.default_inbound_id
                FROM clients c 
                JOIN panels p ON c.panel_id = p.id 
                    WHERE c.id = %s AND c.user_id = %s
            ''', (renew_service_id, user['id']))
            
            service_row = cursor.fetchone()
            
            if not service_row:
                logger.error(f"❌ Service {renew_service_id} not found")
                await update.callback_query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'client_name': service_row['client_name'],
                'client_uuid': service_row['client_uuid'],
                'inbound_id': service_row['inbound_id'],
                'panel_name': service_row['panel_name'],
                'default_inbound_id': service_row['default_inbound_id']
            }
            
            logger.info(f"✅ Service found: {service['panel_name']}")
            
            # Add traffic to existing client
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if not panel_manager:
                logger.error(f"❌ Panel manager not found for panel {service['panel_id']}")
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
                
            logger.info("🔍 Attempting to login to panel...")
            if not panel_manager.login():
                logger.error("❌ Failed to login to panel")
                await update.callback_query.edit_message_text("❌ خطا در اتصال به پنل.")
                return
            
            logger.info("✅ Successfully logged in to panel")
            
            # Get current client details from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT total_gb, status FROM clients WHERE id = %s', (renew_service_id,))
                service_data = cursor.fetchone()
            
            if not service_data:
                logger.error(f"❌ Service {renew_service_id} not found in database")
                await update.callback_query.edit_message_text("❌ سرویس در دیتابیس یافت نشد.")
                return
            
            current_total_gb_from_db = float(service_data['total_gb'] or 0)
            current_status = service_data.get('status', 'active')
            
            # Get invoice details to get the paid amount
            paid_amount = invoice.get('amount', 0) if invoice else 0
            logger.info(f"💰 Paid amount from invoice: {paid_amount} Toman")
            
            # Calculate new total GB from invoice
            renew_gb_amount = float(invoice.get('gb_amount', 0) or 0)
            new_total_gb = current_total_gb_from_db + renew_gb_amount
            
            # Check if service was disabled
            was_disabled = current_status != 'active' or not service.get('is_active', True)
            
            logger.info(f"🔍 Traffic calculation:")
            logger.info(f"   Current total: {current_total_gb_from_db} GB")
            logger.info(f"   Additional: {renew_gb_amount} GB")
            logger.info(f"   New total: {new_total_gb} GB")
            logger.info(f"   Was disabled: {was_disabled}")
            
            # Update client traffic directly
            logger.info("🔍 Updating client traffic...")
            success = panel_manager.update_client_traffic(
                service['inbound_id'], 
                service['client_uuid'], 
                new_total_gb
            )
            
            if success:
                logger.info("✅ Client traffic updated successfully")
                
                # Enable client on panel if it was disabled
                if was_disabled:
                    logger.info("🔧 Enabling client on panel (was disabled)...")
                    enable_success = panel_manager.enable_client(
                        service['inbound_id'],
                        service['client_uuid']
                    )
                    if enable_success:
                        logger.info("✅ Client enabled on panel successfully")
                    else:
                        logger.warning("⚠️ Failed to enable client on panel, but continuing...")
                
                # Update database with new total GB and reset notification flags and status
                with self.db.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute('''
                        UPDATE clients 
                        SET total_gb = %s,
                            status = 'active',
                            is_active = 1,
                            warned_70_percent = 0,
                            warned_100_percent = 0,
                            warned_expired = 0,
                            warned_three_days = 0,
                            warned_one_week = 0,
                            notified_70_percent = 0,
                            notified_80_percent = 0,
                            exhausted_at = NULL,
                            expired_at = NULL,
                            deletion_grace_period_end = NULL
                        WHERE id = %s
                    ''', (new_total_gb, renew_service_id))
                    conn.commit()
                
                logger.info("✅ Database updated successfully (status=active, is_active=1)")
                
                # Clear renewal session
                context.user_data.pop('renewing_service', None)
                context.user_data.pop('renew_service_id', None)
                context.user_data.pop('renew_gb_amount', None)
                
                # Format renewal success message
                renewal_data = {
                    'panel_name': service['panel_name'],
                    'additional_data': renew_gb_amount,
                    'total_data': new_total_gb,
                    'amount': paid_amount
                }
                # Ensure database name is set in thread-local storage
                MessageTemplates.set_database_name(self.db.database_name)
                message = MessageTemplates.format_renewal_success_message(renewal_data)
                
                # Create buttons to go back to user panel and service management
                keyboard = [
                    [InlineKeyboardButton("🔧 مدیریت سرویس", callback_data=f"manage_service_{renew_service_id}")],
                    [InlineKeyboardButton("🏠 پنل کاربری", callback_data="user_panel")],
                    [InlineKeyboardButton("◀️ منوی اصلی", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                logger.info("✅ Service renewal completed successfully")
                
                # Report service renewal
                try:
                    user_data = self.db.get_user(user_id)
                    if user_data and self.reporting_system:
                        renewal_data = {
                            'service_name': service.get('client_name', 'نامشخص'),
                            'additional_data': renew_gb_amount,
                            'total_data': new_total_gb,
                            'amount': paid_amount
                        }
                        await self.reporting_system.report_service_renewed(user_data, renewal_data)
                except Exception as e:
                    logger.error(f"Failed to send renewal report: {e}")
            else:
                logger.error("❌ Failed to update client traffic")
                await update.callback_query.edit_message_text("❌ خطا در تمدید سرویس.")
            
        except Exception as e:
            logger.error(f"Error handling service renewal: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Report user error
            try:
                user_id = update.effective_user.id
                user_data = self.db.get_user(user_id)
                if user_data and self.reporting_system:
                    await self.reporting_system.report_user_error(
                        user_data, "service_renewal_error", str(e), "service_renewal"
                    )
            except Exception as report_error:
                logger.error(f"Failed to send error report: {report_error}")
            
            await update.callback_query.edit_message_text("❌ خطا در تمدید سرویس.")
    
    async def handle_product_service_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                            invoice_id: int, service_id: int, product_id: int, is_expired: bool):
        """Handle product-based service renewal"""
        try:
            logger.info(f"🔍 Starting product service renewal for invoice {invoice_id}")
            
            product = self.db.get_product(product_id)
            if not product:
                logger.error(f"❌ Product {product_id} not found")
                await update.callback_query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                logger.error(f"❌ User {user_id} not found")
                await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get service details
            service = self.db.get_user_service(service_id, user['id'])
            if not service:
                logger.error(f"❌ Service {service_id} not found")
                await update.callback_query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            panel = self.db.get_panel(service['panel_id'])
            if not panel:
                logger.error(f"❌ Panel {service['panel_id']} not found")
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Get invoice
            invoice = self.db.get_invoice(invoice_id)
            if not invoice:
                logger.error(f"❌ Invoice {invoice_id} not found")
                await update.callback_query.edit_message_text("❌ فاکتور یافت نشد.")
                return
            
            # Instant renewal - add volume and time to existing service
            from datetime import datetime, timedelta
            now = datetime.now()
            expire_days = product['duration_days']
            volume_gb = product['volume_gb']
            
            # Get current values
            current_total_gb = float(service.get('total_gb', 0) or 0)
            current_used_gb = float(service.get('cached_used_gb', 0) or 0)
            current_remaining_gb = current_total_gb - current_used_gb
            
            # Calculate new total volume (add new volume to remaining volume)
            new_total_gb = current_remaining_gb + volume_gb
            
            # Calculate new expiration date
            current_expires_at = None
            if service.get('expires_at'):
                try:
                    current_expires_at = datetime.fromisoformat(service['expires_at'])
                except:
                    pass
            
            expires_at = None
            new_expire_days = 0
            if expire_days > 0:
                if current_expires_at and current_expires_at > now:
                    # Add days to current expiration
                    expires_at = current_expires_at + timedelta(days=expire_days)
                    # Calculate total days from now to new expiration
                    new_expire_days = int((expires_at - now).days)
                    logger.info(f"✅ Adding {expire_days} days to existing expiration (new total: {new_expire_days} days)")
                else:
                    # Service expired or no expiration, set new expiration from now
                    expires_at = now + timedelta(days=expire_days)
                    new_expire_days = expire_days
                    logger.info(f"✅ Setting new expiration: {expire_days} days from now")
            
            logger.info(f"✅ Instant renewal: +{volume_gb}GB (new total: {new_total_gb:.2f}GB), +{expire_days} days (new total: {new_expire_days} days)")
            
            # Update service on panel
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if not panel_manager:
                logger.error(f"❌ Panel manager not found")
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            if not panel_manager.login():
                logger.error("❌ Failed to login to panel")
                await update.callback_query.edit_message_text("❌ خطا در اتصال به پنل.")
                return
            
            # Update client with new total volume (add to remaining)
            success = panel_manager.update_client_traffic(
                service['inbound_id'],
                service['client_uuid'],
                new_total_gb
            )
            
            if not success:
                logger.error("❌ Failed to update client traffic")
                await update.callback_query.edit_message_text("❌ خطا در بروزرسانی سرویس.")
                return
            
            # If expire_days > 0, update expiration date
            if expire_days > 0 and panel_manager.update_client_expiration:
                expires_timestamp = int(expires_at.timestamp()) if expires_at else None
                panel_manager.update_client_expiration(
                    service['inbound_id'],
                    service['client_uuid'],
                    expires_timestamp
                )
            
            # Update database - add to existing values
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET total_gb = %s,
                        expire_days = %s,
                        expires_at = %s,
                        product_id = %s,
                        status = 'active',
                        is_active = 1,
                        warned_70_percent = 0,
                        warned_100_percent = 0,
                        warned_expired = 0,
                        warned_three_days = 0,
                        warned_one_week = 0,
                        notified_70_percent = 0,
                        notified_80_percent = 0,
                        exhausted_at = NULL,
                        expired_at = NULL,
                        deletion_grace_period_end = NULL
                    WHERE id = %s
                ''', (new_total_gb, new_expire_days, expires_at.isoformat() if expires_at else None, product_id, service_id))
                conn.commit()
            
            logger.info("✅ Service updated successfully")
            
            # Clear renewal session
            context.user_data.pop('renewing_service', None)
            context.user_data.pop('renew_service_id', None)
            context.user_data.pop('renew_product_id', None)
            context.user_data.pop('renew_is_expired', None)
            
            # Format success message
            success_text = f"""
✅ **تمدید آنی سرویس با موفقیت انجام شد!**

**نام سرویس:** `{service['client_name']}`
**پنل:** {panel['name']}
**محصول:** {product['name']}
**حجم اضافه شده:** {volume_gb} گیگابایت
**حجم کل جدید:** {new_total_gb:.2f} گیگابایت
**مدت زمان اضافه شده:** {expire_days} روز
**مبلغ پرداخت:** {invoice['amount']:,} تومان

🎯 سرویس شما آماده استفاده است!
            """
            
            keyboard = [
                [InlineKeyboardButton("🔧 مدیریت سرویس", callback_data=f"manage_service_{service_id}")],
                [InlineKeyboardButton("🏠 پنل کاربری", callback_data="user_panel")],
                [InlineKeyboardButton("◀️ منوی اصلی", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                success_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Report service renewal
            try:
                if self.reporting_system:
                    renewal_data = {
                        'service_name': service['client_name'],
                        'panel_name': panel['name'],
                        'volume_gb': product['volume_gb'],
                        'duration_days': product['duration_days'],
                        'amount': invoice['amount'],
                        'product_name': product['name']
                    }
                    await self.reporting_system.report_service_renewed(user, renewal_data)
            except Exception as e:
                logger.error(f"Error reporting service renewal: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error handling product service renewal: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.callback_query.edit_message_text("❌ خطا در تمدید سرویس.")
    
    async def handle_gateway_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: int):
        """Handle payment using gateway"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            
            # Process payment
            payment_result = self.payment_manager.process_gateway_payment(user_id, invoice_id)
            
            if payment_result['success']:
                text = f"""
🔗 **لینک پرداخت ایجاد شد**

💰 **مبلغ:** {payment_result.get('amount', 0):,} تومان

برای تکمیل پرداخت روی دکمه زیر کلیک کنید:
                """
                
                keyboard = [
                    [InlineKeyboardButton("💳 پرداخت آنلاین", url=payment_result.get('payment_link', payment_result.get('payment_url')))],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="buy_service")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                error_message = payment_result.get('message', 'خطای نامشخص در ایجاد لینک پرداخت')
                await query.edit_message_text(f"❌ {error_message}")
                
        except Exception as e:
            logger.error(f"Error handling gateway payment: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در ایجاد لینک پرداخت.")
    
    async def create_client_from_invoice(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice: dict):
        """Create client from paid invoice"""
        try:
            logger.info(f"🔍 Starting create_client_from_invoice for invoice {invoice['id']}")
            
            # Get panel details
            panel = self.db.get_panel(invoice['panel_id'])
            if not panel:
                logger.error(f"Panel {invoice['panel_id']} not found")
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            logger.info(f"✅ Panel found: {panel['name']}")
            
            # Get user details
            user = self.db.get_user_by_id(invoice['user_id'])
            if not user:
                logger.error(f"User {invoice['user_id']} not found")
                await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            logger.info(f"✅ User found: {user['telegram_id']}")
            
            # Generate professional client name
            client_name = UsernameFormatter.format_client_name(
                telegram_id=user['telegram_id'],
                username=user.get('username'),
                first_name=user.get('first_name'),
                service_type="VPN"
            )
            
            logger.info(f"🔍 Creating client on all inbounds of panel:")
            logger.info(f"   Panel ID: {invoice['panel_id']}")
            logger.info(f"   Client name: {client_name}")
            logger.info(f"   GB amount: {invoice['gb_amount']}")
            
            # Create client on all inbounds of panel with shared subscription ID
            success, message, client_data = self.admin_manager.create_client_on_all_panel_inbounds(
                panel_id=invoice['panel_id'],
                client_name=client_name,
                expire_days=0,  # expire_days (unlimited)
                total_gb=invoice['gb_amount']  # Keep as GB, panel_manager will convert to bytes
            )
            
            logger.info(f"🔍 create_client_on_panel result:")
            logger.info(f"   Success: {success}")
            logger.info(f"   Message: {message}")
            logger.info(f"   Client data keys: {list(client_data.keys()) if client_data else 'None'}")
            
            if not success:
                logger.error(f"❌ Client creation failed: {message}")
                await update.callback_query.edit_message_text(f"❌ خطا در ایجاد کلاینت: {message}")
                return
            
            if success and client_data:
                logger.info("✅ Client created successfully, saving to database...")
                
                # Save client to database
                client_id = self.db.add_client(
                    user_id=invoice['user_id'],
                    panel_id=invoice['panel_id'],
                    client_name=client_name,
                    client_uuid=client_data.get('id', ''),
                    inbound_id=panel.get('default_inbound_id', 1),
                    protocol=client_data.get('protocol', 'vless'),
                    total_gb=invoice['gb_amount'],
                    sub_id=client_data.get('sub_id')  # Store sub_id in database
                )
                
                if client_id > 0:
                    logger.info(f"✅ Client saved to database with ID: {client_id}")
                    
                    # Report service purchase
                    try:
                        user_data = self.db.get_user(invoice['user_id'])
                        if user_data and self.reporting_system:
                            purchase_type = invoice.get('purchase_type', 'gigabyte')
                            service_data = {
                                'service_name': client_name,
                                'data_amount': invoice['gb_amount'],
                                'amount': invoice['amount'],
                                'panel_name': panel['name'],
                                'purchase_type': purchase_type,
                                'payment_method': 'gateway'
                            }
                            await self.reporting_system.report_service_purchased(user_data, service_data)
                    except Exception as e:
                        logger.error(f"Failed to send service purchase report: {e}")
                else:
                    logger.error("❌ Failed to save client to database")
                
                # Get subscription link
                subscription_link = client_data.get('subscription_link', client_data.get('config_link', ''))
                logger.info(f"✅ Subscription link generated: {subscription_link[:50]}...")
                logger.info(f"   Created on {client_data.get('created_on_inbounds', 0)} inbounds")
                
                # Get user's new balance
                user_data = self.db.get_user(user['telegram_id'])
                new_balance = user_data.get('balance', 0) if user_data else 0
                
                text = f"""
✅ **سرویس {invoice['gb_amount']} گیگابایتی با موفقیت ایجاد شد!**

💰 **مبلغ کسر شده:** {invoice['amount']:,} تومان
💳 **موجودی جدید:** {new_balance:,} تومان
📊 **تعداد اینباندها:** {client_data.get('created_on_inbounds', 0)}

🎉 **سرویس شما آماده استفاده است!**

🔗 **لینک سابسکریپشن:**
```
{subscription_link}
```

💡 **راهنمای استفاده:**
1. لینک بالا را کپی کنید
2. در برنامه VPN خود (مثل v2rayN، v2rayNG) به عنوان سابسکریپشن اضافه کنید
3. کانفیگ‌ها را به‌روزرسانی کنید و اتصال را برقرار کنید
                """
                
                keyboard = [
                    [InlineKeyboardButton("📋 پنل", callback_data="user_panel")],
                    [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                logger.info("✅ Client creation completed successfully")
            else:
                logger.error(f"❌ Client creation failed: {message}")
                await update.callback_query.edit_message_text(f"❌ خطا در ایجاد کلاینت: {message}")
                
        except Exception as e:
            logger.error(f"❌ Error creating client from invoice: {e}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            await update.callback_query.edit_message_text("❌ خطا در ایجاد سرویس.")
    
    @auto_update_user_info
    async def show_account_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user account balance"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            balance = self.payment_manager.get_user_balance(user_id)
            
            text = f"""
💳 **موجودی حساب شما**

💰 **موجودی فعلی:** {balance:,} تومان

برای مدیریت موجودی از دکمه‌های زیر استفاده کنید:
            """
            
            reply_markup = ButtonLayout.create_balance_management_buttons()
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing account balance: {e}")
            await query.edit_message_text("❌ خطا در دریافت موجودی.")
    
    async def show_add_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show add balance options"""
        query = update.callback_query
        await query.answer()
        
        try:
            text = """
💳 **افزایش موجودی**

برای افزایش موجودی حساب خود، یکی از روش‌های زیر را انتخاب کنید:

• **پرداخت آنلاین:** از طریق درگاه بانکی
• **تماس با ادمین:** برای روش‌های دیگر

لطفاً مبلغ مورد نظر را انتخاب کنید:
            """
            
            # Create balance amount buttons
            amounts = [50000, 100000, 200000, 500000, 1000000, 2000000]
            keyboard = []
            
            for i in range(0, len(amounts), 2):
                row = []
                for j in range(2):
                    if i + j < len(amounts):
                        amount = amounts[i + j]
                        row.append(InlineKeyboardButton(
                            f"{amount:,} تومان", 
                            callback_data=f"add_balance_{amount}"
                        ))
                keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="user_panel")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing add balance: {e}")
            await query.edit_message_text("❌ خطا در نمایش گزینه‌های افزایش موجودی.")
    
    async def handle_add_balance_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
        """Handle add balance amount selection - Card to Card"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            
            # Create invoice for balance addition
            description = f"افزایش موجودی به مبلغ {amount:,} تومان"
            
            invoice_id = self.db.create_invoice(
                user_id=user_id,
                amount=amount,
                description=description,
                payment_method='card',
                purchase_type='balance'
            )
            
            if invoice_id:
                # Show card payment details
                await self.show_card_payment(update, context, invoice_id)
            else:
                await query.edit_message_text("❌ خطا در ایجاد فاکتور. لطفاً با پشتیبانی تماس بگیرید.")
                
        except Exception as e:
            logger.error(f"Error handling add balance amount: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_gateway_volume_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                            panel_id: int, volume_gb: int, price: int):
        """Handle gateway payment for volume purchase - redirect to card-to-card"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            
            # Get panel info
            panel = self.db.get_panel(panel_id)
            panel_name = panel['name'] if panel else 'نامشخص'
            
            # Create invoice for service purchase
            description = f"خرید {volume_gb} گیگابایت از پنل {panel_name}"
            
            invoice_id = self.db.create_invoice(
                user_id=user_id,
                amount=price,
                description=description,
                payment_method='card',
                purchase_type='service',
                panel_id=panel_id
            )
            
            if invoice_id:
                # Store purchase info in context for later use
                context.user_data['pending_purchase'] = {
                    'panel_id': panel_id,
                    'volume_gb': volume_gb,
                    'price': price,
                    'invoice_id': invoice_id
                }
                
                # Show card payment details
                await self.show_card_payment(update, context, invoice_id)
            else:
                await query.edit_message_text("❌ خطا در ایجاد فاکتور. لطفاً با پشتیبانی تماس بگیرید.")
                
        except Exception as e:
            logger.error(f"Error handling gateway volume payment: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_gateway_add_volume_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                 service_id: int, panel_id: int, volume_gb: int, price: int):
        """Handle gateway payment for add volume - redirect to card-to-card"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            
            # Get panel info
            panel = self.db.get_panel(panel_id)
            panel_name = panel['name'] if panel else 'نامشخص'
            
            # Create invoice for volume addition
            description = f"افزایش {volume_gb} گیگابایت به سرویس"
            
            invoice_id = self.db.create_invoice(
                user_id=user_id,
                amount=price,
                description=description,
                payment_method='card',
                purchase_type='renew',
                panel_id=panel_id
            )
            
            if invoice_id:
                # Store purchase info in context for later use
                context.user_data['pending_add_volume'] = {
                    'service_id': service_id,
                    'panel_id': panel_id,
                    'volume_gb': volume_gb,
                    'price': price,
                    'invoice_id': invoice_id
                }
                
                # Show card payment details
                await self.show_card_payment(update, context, invoice_id)
            else:
                await query.edit_message_text("❌ خطا در ایجاد فاکتور. لطفاً با پشتیبانی تماس بگیرید.")
                
        except Exception as e:
            logger.error(f"Error handling gateway add volume payment: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_protocol_selection_for_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, protocol: str):
        """Handle protocol selection for Marzban panel creation"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get panel data from user session
            panel_name = context.user_data.get('panel_name')
            panel_url = context.user_data.get('panel_url')
            panel_username = context.user_data.get('panel_username')
            panel_password = context.user_data.get('panel_password')
            panel_subscription_url = context.user_data.get('panel_subscription_url')
            panel_price = context.user_data.get('panel_price')
            panel_type = context.user_data.get('panel_type', '3x-ui')
            panel_sale_type = context.user_data.get('panel_sale_type', 'gigabyte')
            
            if not all([panel_name, panel_url, panel_username, panel_password, panel_price]):
                await query.edit_message_text("❌ اطلاعات پنل ناقص است.")
                return
            
            # For Marzban, use protocol instead of inbound_id
            # We set default_inbound_id to 0 for Marzban (not used)
            success = self.db.add_panel(
                name=panel_name,
                url=panel_url,
                username=panel_username,
                password=panel_password,
                api_endpoint=panel_url,
                default_inbound_id=0,  # Not used for Marzban
                price_per_gb=panel_price,
                subscription_url=panel_subscription_url,
                panel_type=panel_type,
                default_protocol=protocol,
                sale_type=panel_sale_type
            )
            
            if success:
                protocol_persian = {
                    'vless': 'VLESS',
                    'vmess': 'VMess',
                    'trojan': 'Trojan'
                }.get(protocol, protocol.upper())
                
                panel_type_persian = 'ربکا' if panel_type == 'rebecca' else 'مرزبان'
                
                sub_url_display = f"🔗 لینک سابسکریپشن: {panel_subscription_url}\n" if panel_subscription_url else ""
                await query.edit_message_text(
                    f"✅ پنل '{panel_name}' با موفقیت اضافه شد!\n\n"
                    f"📦 نوع پنل: {panel_type_persian}\n"
                    f"🔗 URL: {panel_url}\n"
                    f"👤 Username: {panel_username}\n"
                    f"{sub_url_display}"
                    f"🔗 پروتکل پیش‌فرض: {protocol_persian}\n"
                    f"💰 قیمت هر گیگابایت: {panel_price:,} تومان\n\n"
                    f"💡 کاربران از تمامی inbound های {protocol_persian} استفاده خواهند کرد.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
            else:
                await query.edit_message_text(
                    "❌ خطا در اضافه کردن پنل. ممکن است نام پنل تکراری باشد.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
            
            # Clear user data
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error handling protocol selection for panel: {e}")
            await query.edit_message_text("❌ خطا در اضافه کردن پنل.")
    
    async def handle_inbound_selection_for_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, inbound_id: int):
        """Handle inbound selection for panel creation"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get panel data from user session
            panel_name = context.user_data.get('panel_name')
            panel_url = context.user_data.get('panel_url')
            panel_username = context.user_data.get('panel_username')
            panel_password = context.user_data.get('panel_password')
            panel_subscription_url = context.user_data.get('panel_subscription_url')
            panel_price = context.user_data.get('panel_price')
            panel_type = context.user_data.get('panel_type', '3x-ui')
            panel_sale_type = context.user_data.get('panel_sale_type', 'gigabyte')
            
            if not all([panel_name, panel_url, panel_username, panel_password, panel_price]):
                await query.edit_message_text("❌ اطلاعات پنل ناقص است.")
                return
            
            # Add panel to database
            success = self.db.add_panel(
                name=panel_name,
                url=panel_url,
                username=panel_username,
                password=panel_password,
                api_endpoint=panel_url,
                default_inbound_id=inbound_id,
                price_per_gb=panel_price,
                subscription_url=panel_subscription_url,
                panel_type=panel_type,
                sale_type=panel_sale_type
            )
            
            if success:
                panel_type_persian = {
                    'marzban': 'مرزبان',
                    'rebecca': 'ربکا',
                    '3x-ui': '3x-ui'
                }.get(panel_type, panel_type)
                sub_url_display = f"🔗 لینک سابسکریپشن: {panel_subscription_url}\n" if panel_subscription_url else ""
                await query.edit_message_text(
                    f"✅ پنل '{panel_name}' با موفقیت اضافه شد!\n\n"
                    f"📦 نوع پنل: {panel_type_persian}\n"
                    f"🔗 URL: {panel_url}\n"
                    f"👤 Username: {panel_username}\n"
                    f"{sub_url_display}"
                    f"🔗 Inbound ID: {inbound_id}\n"
                    f"💰 قیمت هر گیگابایت: {panel_price:,} تومان",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
            else:
                await query.edit_message_text(
                    "❌ خطا در اضافه کردن پنل. ممکن است نام پنل تکراری باشد.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
            
            # Clear user data
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error handling inbound selection for panel: {e}")
            await query.edit_message_text("❌ خطا در اضافه کردن پنل.")
    
    async def handle_add_panel_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the add panel flow"""
        query = update.callback_query
        await query.answer()
        
        try:
            # First, ask for panel type
            keyboard = [
                [InlineKeyboardButton("🔵 3x-ui Panel", callback_data="panel_type_3x-ui")],
                [InlineKeyboardButton("🟢 Marzban Panel", callback_data="panel_type_marzban")],
                [InlineKeyboardButton("🟣 Rebecca Panel", callback_data="panel_type_rebecca")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_panels")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🔧 **اضافه کردن پنل جدید**\n\n"
                "لطفاً نوع پنل را انتخاب کنید:\n\n"
                "🔵 **3x-ui**: پنل قدرتمند 3x-ui با قابلیت‌های پیشرفته\n"
                "🟢 **Marzban**: پنل مدرن Marzban با رابط کاربری ساده",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Clear any previous state to avoid conflicts
            context.user_data.clear()
            
            # Set state for panel type selection
            context.user_data['adding_panel'] = True
            context.user_data['panel_step'] = 'type'
            
        except Exception as e:
            logger.error(f"Error starting add panel flow: {e}")
            await query.edit_message_text("❌ خطا در شروع فرآیند اضافه کردن پنل.")
    
    async def handle_panel_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_type: str):
        """Handle panel type selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Save panel type
            context.user_data['panel_type'] = panel_type
            context.user_data['panel_step'] = 'name'
            
            panel_type_persian = {
                'marzban': 'مرزبان',
                'rebecca': 'ربکا',
                '3x-ui': '3x-ui'
            }.get(panel_type, panel_type)
            
            await query.edit_message_text(
                f"✅ نوع پنل انتخاب شد: **{panel_type_persian}**\n\n"
                "لطفاً نام پنل را وارد کنید:",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling panel type selection: {e}")
            await query.edit_message_text("❌ خطا در انتخاب نوع پنل.")
    
    async def handle_sale_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, sale_type: str):
        """Handle sale type selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Save sale type
            context.user_data['panel_sale_type'] = sale_type
            context.user_data['panel_step'] = 'price'
            
            sale_type_names = {
                'gigabyte': 'گیگابایتی',
                'plan': 'پلنی',
                'both': 'هر دو'
            }
            
            sale_type_persian = sale_type_names.get(sale_type, sale_type)
            
            await query.edit_message_text(
                f"✅ نوع فروش انتخاب شد: **{sale_type_persian}**\n\n"
                "💰 **قیمت هر گیگابایت را به تومان وارد کنید:**\n\n"
                "مثال: 1000\n\n"
                "💡 این قیمت برای فروش گیگابایتی استفاده می‌شود.",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling sale type selection: {e}")
            await query.edit_message_text("❌ خطا در انتخاب نوع فروش.")
    
    async def handle_panel_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle panel details display"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get panel details with inbound info
            panel = self.admin_manager.get_panel_details(panel_id, sync_inbounds=True)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Create panel details message
            price_per_gb = panel.get('price_per_gb', 0)
            if isinstance(price_per_gb, (int, float)):
                price_text = f"{int(price_per_gb):,} تومان"
            else:
                price_text = f"{price_per_gb} تومان"
            
            subscription_url = panel.get('subscription_url', 'تنظیم نشده')
            panel_type = panel.get('panel_type', '3x-ui')
            panel_type_persian = {
                'marzban': 'مرزبان',
                'rebecca': 'ربکا',
                '3x-ui': '3x-ui'
            }.get(panel_type, panel_type)
            
            # Get main inbound info
            main_inbound_info = ""
            main_inbound = panel.get('main_inbound')
            if main_inbound:
                main_inbound_info = f"🔗 اینباند اصلی: {main_inbound.get('name', 'نامشخص')} ({main_inbound.get('protocol', 'unknown')}:{main_inbound.get('port', 0)})"
            elif panel.get('default_inbound_id'):
                main_inbound_info = f"🔗 اینباند اصلی ID: {panel.get('default_inbound_id')}"
            else:
                main_inbound_info = "🔗 اینباند اصلی: ❌ تنظیم نشده"
            
            inbound_count = panel.get('inbounds_count', 0)
            inbound_info = f"✅ {inbound_count} اینباند موجود" if inbound_count > 0 else "❌ هیچ اینباندی یافت نشد"
            
            message = (
                f"🔧 جزئیات پنل: {panel['name']}\n\n"
                f"📦 نوع پنل: {panel_type_persian}\n"
                f"🔗 URL: {panel['url']}\n"
                f"👤 Username: {panel['username']}\n"
                f"🔑 Password: {'*' * len(panel['password'])}\n"
                f"{main_inbound_info}\n"
                f"📊 تعداد اینباندها: {inbound_count}\n"
                f"🔗 لینک سابسکریپشن: {subscription_url}\n"
                f"💰 قیمت هر گیگابایت: {price_text}\n"
                f"📊 وضعیت: {inbound_info}"
            )
            
            # Create buttons
            keyboard = [
                [InlineKeyboardButton("✏️ ویرایش پنل", callback_data=f"edit_panel_{panel_id}")],
                [InlineKeyboardButton("🔗 مدیریت اینباندها", callback_data=f"manage_panel_inbounds_{panel_id}")],
                [InlineKeyboardButton("🗑️ حذف پنل", callback_data=f"delete_panel_{panel_id}")],
                [InlineKeyboardButton("🔄 تست اتصال", callback_data=f"test_panel_{panel_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_panels")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling panel details: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در نمایش جزئیات پنل.")
    
    async def handle_manage_panel_inbounds(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle panel inbounds management"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Get inbounds with status
            inbounds = self.admin_manager.get_panel_inbounds_with_status(panel_id)
            if not inbounds:
                await query.edit_message_text(
                    "❌ هیچ اینباندی یافت نشد. لطفاً ابتدا اینباندها را همگام‌سازی کنید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 همگام‌سازی اینباندها", callback_data=f"sync_inbounds_{panel_id}")],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_details_{panel_id}")]
                    ])
                )
                return
            
            # Create message
            main_inbound_id = panel.get('default_inbound_id')
            message = f"🔗 **مدیریت اینباندهای پنل: {panel['name']}**\n\n"
            message += f"📊 تعداد اینباندها: {len(inbounds)}\n\n"
            
            keyboard = []
            for inbound in inbounds:
                status_icon = "🟢" if inbound['is_enabled'] else "🔴"
                main_icon = "⭐" if inbound['is_main'] else "  "
                inbound_text = f"{status_icon} {main_icon} {inbound['name']} ({inbound['protocol']}:{inbound['port']})"
                
                # Create toggle button
                toggle_text = "❌ غیرفعال" if inbound['is_enabled'] else "✅ فعال"
                keyboard.append([
                    InlineKeyboardButton(inbound_text, callback_data=f"inbound_info_{panel_id}_{inbound['id']}")
                ])
                keyboard.append([
                    InlineKeyboardButton(
                        toggle_text,
                        callback_data=f"toggle_inbound_{panel_id}_{inbound['id']}"
                    ),
                    InlineKeyboardButton(
                        "⭐ اصلی" if not inbound['is_main'] else "⭐ اصلی (فعلی)",
                        callback_data=f"change_main_inbound_{panel_id}_{inbound['id']}" if not inbound['is_main'] else "noop"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔄 همگام‌سازی اینباندها", callback_data=f"sync_inbounds_{panel_id}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_details_{panel_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            except BadRequest as e:
                # Handle "Message is not modified" error gracefully
                if "not modified" in str(e).lower():
                    # Message content is the same, just answer the callback
                    await query.answer()
                else:
                    raise
            
        except Exception as e:
            logger.error(f"Error managing panel inbounds: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در مدیریت اینباندها.")
    
    async def handle_toggle_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, inbound_id: int):
        """Toggle inbound enabled status"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get current status
            inbound = self.db.get_panel_inbound(panel_id, inbound_id)
            if not inbound:
                await query.edit_message_text("❌ اینباند یافت نشد.")
                return
            
            current_status = inbound.get('is_enabled', 1)
            new_status = not current_status
            
            # Check if trying to disable main inbound
            panel = self.db.get_panel(panel_id)
            if panel.get('default_inbound_id') == inbound_id and new_status == False:
                await query.answer("❌ نمی‌توانید اینباند اصلی را غیرفعال کنید. ابتدا اینباند اصلی را تغییر دهید.", show_alert=True)
                return
            
            # Toggle status
            success, message = self.admin_manager.set_inbound_enabled_status(panel_id, inbound_id, new_status)
            if success:
                await query.answer(message, show_alert=True)
                # Refresh the management page
                await self.handle_manage_panel_inbounds(update, context, panel_id)
            else:
                await query.answer(message, show_alert=True)
                
        except Exception as e:
            logger.error(f"Error toggling inbound: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.answer("❌ خطا در تغییر وضعیت اینباند.", show_alert=True)
    
    async def handle_change_main_inbound_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show list of inbounds to select new main inbound"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Get inbounds with status
            inbounds = self.admin_manager.get_panel_inbounds_with_status(panel_id)
            
            if not inbounds:
                await query.edit_message_text(
                    "❌ اینباندی یافت نشد.\n\n"
                    "لطفاً ابتدا اینباندها را همگام‌سازی کنید.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_details_{panel_id}")
                    ]])
                )
                return
            
            current_main_inbound_id = panel.get('default_inbound_id')
            
            text = f"🔧 **تغییر اینباند اصلی پنل: {panel['name']}**\n\n"
            text += "لطفاً اینباند جدید را انتخاب کنید:\n\n"
            
            keyboard = []
            for inbound in inbounds:
                status_icon = "✅" if inbound.get('is_enabled', True) else "❌"
                main_icon = "⭐" if inbound['id'] == current_main_inbound_id else ""
                inbound_name = inbound.get('name', f"Inbound {inbound['id']}")
                button_text = f"{status_icon} {main_icon} {inbound_name}"
                
                # Only allow selecting enabled inbounds that are not already the main inbound
                if inbound.get('is_enabled', True) and inbound['id'] != current_main_inbound_id:
                    keyboard.append([InlineKeyboardButton(
                        button_text,
                        callback_data=f"change_main_inbound_{panel_id}_{inbound['id']}"
                    )])
                elif inbound['id'] == current_main_inbound_id:
                    keyboard.append([InlineKeyboardButton(
                        button_text + " (فعلی)",
                        callback_data="noop"
                    )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"start_edit_panel_{panel_id}")])
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error in handle_change_main_inbound_selection: {e}")
            await query.edit_message_text("❌ خطا در نمایش اینباندها.")
    
    async def handle_change_main_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, inbound_id: int):
        """Change main inbound for a panel"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Verify inbound is enabled
            inbound = self.db.get_panel_inbound(panel_id, inbound_id)
            if not inbound:
                await query.answer("❌ اینباند یافت نشد.", show_alert=True)
                return
            
            if not inbound.get('is_enabled', 1):
                await query.answer("❌ نمی‌توانید اینباند غیرفعال را به عنوان اینباند اصلی انتخاب کنید.", show_alert=True)
                return
            
            # Change main inbound
            success, message = self.admin_manager.change_panel_main_inbound(panel_id, inbound_id)
            if success:
                await query.answer(message, show_alert=True)
                # Determine which page to refresh based on message text
                message_text = query.message.text or ""
                if "مدیریت اینباندهای پنل" in message_text:
                    # We're in the manage inbounds page, refresh it
                    await self.handle_manage_panel_inbounds(update, context, panel_id)
                else:
                    # We're in the selection page (edit flow), refresh it
                    await self.handle_change_main_inbound_selection(update, context, panel_id)
            else:
                await query.answer(message, show_alert=True)
                
        except Exception as e:
            logger.error(f"Error changing main inbound: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.answer("❌ خطا در تغییر اینباند اصلی.", show_alert=True)
    
    async def handle_sync_inbounds(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Sync inbounds from panel API to database"""
        query = update.callback_query
        await query.answer("در حال همگام‌سازی...")
        
        try:
            success, message = self.admin_manager.sync_panel_inbounds_to_db(panel_id)
            if success:
                await query.answer(message, show_alert=True)
                # Refresh the management page
                await self.handle_manage_panel_inbounds(update, context, panel_id)
            else:
                await query.answer(message, show_alert=True)
                
        except Exception as e:
            logger.error(f"Error syncing inbounds: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.answer("❌ خطا در همگام‌سازی اینباندها.", show_alert=True)
    
    async def handle_delete_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle panel deletion"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get panel details
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Show confirmation
            message = (
                f"⚠️ آیا مطمئن هستید که می‌خواهید پنل '{panel['name']}' را حذف کنید؟\n\n"
                f"این عمل غیرقابل بازگشت است!"
            )
            
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"confirm_delete_panel_{panel_id}")],
                [InlineKeyboardButton("❌ لغو", callback_data="manage_panels")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling delete panel: {e}")
            await query.edit_message_text("❌ خطا در حذف پنل.")
    
    async def handle_confirm_delete_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle panel deletion confirmation"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Delete panel from database
            if self.db.delete_panel(panel_id):
                await query.edit_message_text(
                    "✅ پنل با موفقیت حذف شد!",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
            else:
                await query.edit_message_text(
                    "❌ خطا در حذف پنل.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
                
        except Exception as e:
            logger.error(f"Error confirming delete panel: {e}")
            await query.edit_message_text("❌ خطا در حذف پنل.")
    
    async def handle_list_panels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle listing all panels"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get all panels
            panels = self.db.get_panels()
            
            if not panels:
                await query.edit_message_text(
                    "📋 هیچ پنلی ثبت نشده است.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
                return
            
            # Create panel buttons
            keyboard = []
            for panel in panels:
                button_text = f"🔧 {panel['name']}"
                callback_data = f"panel_details_{panel['id']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_panels")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"📋 پنل‌های موجود ({len(panels)} پنل):\n\nروی هر پنل کلیک کنید تا جزئیات آن را ببینید."
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling list panels: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست پنل‌ها.")
    
    async def handle_manage_panels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manage panels menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "🔧 مدیریت پنل‌ها\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
            
            keyboard = [
                [InlineKeyboardButton("📋 لیست پنل‌های موجود", callback_data="list_panels")],
                [InlineKeyboardButton("➕ اضافه کردن پنل", callback_data="add_panel")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling manage panels: {e}")
            await query.edit_message_text("❌ خطا در نمایش منوی مدیریت پنل‌ها.")
    
    async def handle_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin panel menu"""
        query = update.callback_query
        if query:
            await query.answer()
        
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            error_text = "❌ دسترسی غیرمجاز."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
            return

        try:
            message = """
👑 **پنل مدیریت**

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:
            """
            
            # Use the centralized button layout
            reply_markup = ButtonLayout.create_admin_panel(bot_name=self.bot_username)
            
            if query:
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling admin panel: {e}")
            error_text = "❌ خطا در نمایش پنل مدیریت."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
    
    async def handle_system_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle system logs display"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get recent logs
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT * FROM system_logs 
                    ORDER BY created_at DESC 
                    LIMIT 50
                ''')
                logs = [dict(row) for row in cursor.fetchall()]
            
            if not logs:
                message = "📋 لاگ‌های سیستم\n\nهیچ لاگی یافت نشد."
            else:
                message = "📋 لاگ‌های سیستم\n\n"
                for log in logs[:20]:  # Show last 20 logs
                    level_emoji = {
                        'INFO': 'ℹ️',
                        'WARNING': '⚠️',
                        'ERROR': '❌',
                        'DEBUG': '🔍'
                    }.get(log.get('level', 'INFO'), 'ℹ️')
                    
                    log_time = log.get('created_at', '')[:19] if log.get('created_at') else 'نامشخص'
                    log_message = log.get('message', '')[:100]  # Truncate long messages
                    
                    message += f"{level_emoji} `{log_time}`\n{log_message}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling system logs: {e}")
            await query.edit_message_text("❌ خطا در نمایش لاگ‌ها.")
    
    async def handle_manage_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manage users menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            users = self.db.get_all_users()
            total_users = len(users)
            
            message = f"👥 مدیریت کاربران\n\nتعداد کل کاربران: {total_users:,}\n\nگزینه موردنظر را انتخاب کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔍 مشاهده اطلاعات کاربر", callback_data="user_info_request")],
                [InlineKeyboardButton("📋 مشاهده سرویس‌های کاربر", callback_data="user_services_menu")],
                [InlineKeyboardButton("🎁 هدیه به همه کاربران", callback_data="gift_all_users_request")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling manage users: {e}")
            await query.edit_message_text("❌ خطا در نمایش مدیریت کاربران.")
    
    async def handle_manage_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manage products menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            panels = self.db.get_panels(active_only=True)
            total_panels = len(panels)
            
            message = f"📦 مدیریت محصولات\n\nتعداد پنل‌های فعال: {total_panels}\n\nاز طریق پنل مدیریت وب می‌توانید محصولات را مدیریت کنید."
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling manage products: {e}")
            await query.edit_message_text("❌ خطا در نمایش مدیریت محصولات.")
    
    async def handle_broadcast_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcast menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "📢 همگانی\n\nنوع ارسال را انتخاب کنید:"
            
            keyboard = [
                [InlineKeyboardButton("💬 ارسال پیام همگانی", callback_data="broadcast_message_request"), InlineKeyboardButton("📤 فوروارد همگانی", callback_data="broadcast_forward_request")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling broadcast menu: {e}")
            await query.edit_message_text("❌ خطا در نمایش منوی همگانی.")
    
    async def handle_broadcast_message_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request message for broadcasting"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "💬 ارسال پیام همگانی\n\nلطفاً پیام مورد نظر خود را ارسال کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data="broadcast_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state for next message
            context.user_data['awaiting_broadcast_message'] = True
            
        except Exception as e:
            logger.error(f"Error requesting broadcast message: {e}")
            await query.edit_message_text("❌ خطا در درخواست پیام همگانی.")
    
    async def handle_broadcast_forward_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request message for forwarding"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "📤 فوروارد همگانی\n\nلطفاً پیام مورد نظر خود را فوروارد کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data="broadcast_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state for next message
            context.user_data['awaiting_broadcast_forward'] = True
            
        except Exception as e:
            logger.error(f"Error requesting broadcast forward: {e}")
            await query.edit_message_text("❌ خطا در درخواست فوروارد همگانی.")
    
    # Product Management Methods
    async def handle_manage_products_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show product management menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get current test account configuration
            test_config = self.db.get_test_account_config()
            config_info = ""
            if test_config['panel_id']:
                panel = self.db.get_panel(test_config['panel_id'])
                panel_name = panel['name'] if panel else "نامشخص"
                config_info = f"\n\n🧪 **تنظیمات اکانت تست:**\nپنل: {panel_name}"
                if test_config['inbound_id']:
                    config_info += f"\nاینباند: {test_config['inbound_id']}"
            else:
                config_info = "\n\n🧪 **تنظیمات اکانت تست:**\n⚠️ تنظیم نشده"
            
            message = f"""
📦 **مدیریت محصولات**

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:
{config_info}
            """
            
            keyboard = [
                [InlineKeyboardButton("📁 مدیریت دسته‌بندی‌ها", callback_data="manage_categories"), InlineKeyboardButton("📦 مدیریت محصولات", callback_data="manage_products_list")],
                [InlineKeyboardButton("🧪 تنظیمات اکانت تست", callback_data="configure_test_account")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling manage products menu: {e}")
            await query.edit_message_text("❌ خطا در نمایش منوی مدیریت محصولات.")
    
    async def handle_manage_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show category management - panel selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get all panels
            panels = self.db.get_panels(active_only=True)
            
            if not panels:
                await query.edit_message_text(
                    "❌ هیچ پنل فعالی وجود ندارد.\n\nلطفاً ابتدا یک پنل اضافه کنید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products")]
                    ])
                )
                return
            
            message = "📁 **انتخاب پنل برای مدیریت دسته‌بندی‌ها:**\n\n"
            keyboard = []
            
            for panel in panels:
                keyboard.append([InlineKeyboardButton(
                    f"🔗 {panel['name']}",
                    callback_data=f"panel_categories_{panel['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling manage categories: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست پنل‌ها.")
    
    async def handle_panel_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show categories for a specific panel"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Get categories for this panel
            categories = self.db.get_categories(panel_id, active_only=False)
            
            message = f"📁 **دسته‌بندی‌های پنل {panel['name']}:**\n\n"
            
            if not categories:
                message += "هیچ دسته‌بندی‌ای وجود ندارد.\n\n"
            else:
                for cat in categories:
                    status = "🟢" if cat['is_active'] else "🔴"
                    message += f"{status} {cat['name']}\n"
            
            keyboard = []
            
            # Show category buttons
            for cat in categories:
                status_icon = "🟢" if cat['is_active'] else "🔴"
                keyboard.append([InlineKeyboardButton(
                    f"{status_icon} {cat['name']}",
                    callback_data=f"edit_category_{cat['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("➕ اضافه کردن دسته‌بندی", callback_data=f"add_category_{panel_id}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_categories")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling panel categories: {e}")
            await query.edit_message_text("❌ خطا در نمایش دسته‌بندی‌ها.")
    
    async def handle_add_category_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Start adding a new category"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            message = f"""
➕ **اضافه کردن دسته‌بندی جدید**

پنل: **{panel['name']}**

لطفاً نام دسته‌بندی را وارد کنید:

💡 برای لغو عملیات /cancel را ارسال کنید.
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"panel_categories_{panel_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Set state for adding category
            context.user_data['adding_category'] = True
            context.user_data['category_panel_id'] = panel_id
            
        except Exception as e:
            logger.error(f"Error starting add category: {e}")
            await query.edit_message_text("❌ خطا در شروع افزودن دسته‌بندی.")
    
    async def handle_add_category_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle category name text input"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ عملیات لغو شد.")
            panel_id = context.user_data.get('category_panel_id')
            context.user_data.clear()
            if panel_id:
                from telegram import Update
                # Create a mock update for callback
                class MockCallbackQuery:
                    def __init__(self, edit_message_text_func):
                        self.edit_message_text_func = edit_message_text_func
                    async def answer(self):
                        pass
                
                class MockUpdate:
                    def __init__(self, callback_query):
                        self.callback_query = callback_query
                
                mock_query = MockCallbackQuery(lambda text, **kwargs: update.message.reply_text(text))
                mock_update = MockUpdate(mock_query)
                await self.handle_panel_categories(mock_update, context, panel_id)
            return
        
        panel_id = context.user_data.get('category_panel_id')
        if not panel_id:
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
            context.user_data.clear()
            return
        
        try:
            # Validate category name
            if not text or len(text.strip()) < 2:
                await update.message.reply_text("❌ نام دسته‌بندی باید حداقل ۲ کاراکتر باشد.")
                return
            
            category_name = text.strip()
            
            # Add category
            category_id = self.db.add_category(panel_id, category_name)
            
            if category_id:
                await update.message.reply_text(
                    f"✅ دسته‌بندی '{category_name}' با موفقیت اضافه شد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📁 مشاهده دسته‌بندی‌ها", callback_data=f"panel_categories_{panel_id}")]
                    ])
                )
            else:
                await update.message.reply_text("❌ خطا در افزودن دسته‌بندی. ممکن است نام تکراری باشد.")
            
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error adding category: {e}")
            await update.message.reply_text("❌ خطا در افزودن دسته‌بندی.")
            context.user_data.clear()
    
    async def handle_edit_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Show category edit menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            panel = self.db.get_panel(category['panel_id'])
            panel_name = panel['name'] if panel else 'نامشخص'
            
            status_text = "🟢 فعال" if category['is_active'] else "🔴 غیرفعال"
            
            message = f"""
✏️ **ویرایش دسته‌بندی**

**نام:** {category['name']}
**پنل:** {panel_name}
**وضعیت:** {status_text}

کدام مورد را می‌خواهید ویرایش کنید؟
            """
            
            keyboard = [
                [InlineKeyboardButton("📝 تغییر نام", callback_data=f"category_edit_name_{category_id}"), InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"category_toggle_{category_id}")],
                [InlineKeyboardButton("🗑️ حذف", callback_data=f"category_delete_{category_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_categories_{category['panel_id']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling edit category: {e}")
            await query.edit_message_text("❌ خطا در نمایش ویرایش دسته‌بندی.")
    
    async def handle_category_edit_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Start editing category name"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            message = f"""
✏️ **تغییر نام دسته‌بندی**

**نام فعلی:** {category['name']}

لطفاً نام جدید را وارد کنید:

💡 برای لغو عملیات /cancel را ارسال کنید.
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"edit_category_{category_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Set state
            context.user_data['editing_category_name'] = True
            context.user_data['category_id'] = category_id
            
        except Exception as e:
            logger.error(f"Error starting category name edit: {e}")
            await query.edit_message_text("❌ خطا در شروع ویرایش نام.")
    
    async def handle_category_text_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle category name text edit"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ ویرایش لغو شد.")
            category_id = context.user_data.get('category_id')
            context.user_data.clear()
            if category_id:
                # We can't easily call async handler from text handler, so just clear
                pass
            return
        
        category_id = context.user_data.get('category_id')
        if not category_id:
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
            context.user_data.clear()
            return
        
        try:
            if not text or len(text.strip()) < 2:
                await update.message.reply_text("❌ نام دسته‌بندی باید حداقل ۲ کاراکتر باشد.")
                return
            
            new_name = text.strip()
            
            # Update category
            if self.db.update_category(category_id, name=new_name):
                await update.message.reply_text(
                    f"✅ نام دسته‌بندی با موفقیت تغییر کرد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📁 مشاهده دسته‌بندی", callback_data=f"edit_category_{category_id}")]
                    ])
                )
            else:
                await update.message.reply_text("❌ خطا در تغییر نام دسته‌بندی.")
            
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error updating category name: {e}")
            await update.message.reply_text("❌ خطا در تغییر نام دسته‌بندی.")
            context.user_data.clear()
    
    async def handle_category_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Toggle category active status"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            new_status = not category['is_active']
            
            if self.db.update_category(category_id, is_active=new_status):
                status_text = "فعال" if new_status else "غیرفعال"
                await query.edit_message_text(
                    f"✅ دسته‌بندی {status_text} شد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"edit_category_{category_id}")]
                    ])
                )
            else:
                await query.edit_message_text("❌ خطا در تغییر وضعیت دسته‌بندی.")
            
        except Exception as e:
            logger.error(f"Error toggling category: {e}")
            await query.edit_message_text("❌ خطا در تغییر وضعیت دسته‌بندی.")
    
    async def handle_category_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Delete a category"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            panel_id = category['panel_id']
            
            message = f"""
⚠️ **تأیید حذف دسته‌بندی**

آیا مطمئن هستید که می‌خواهید دسته‌بندی '{category['name']}' را حذف کنید؟

⚠️ این عمل غیرقابل بازگشت است!
            """
            
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"confirm_category_delete_{category_id}")],
                [InlineKeyboardButton("❌ لغو", callback_data=f"edit_category_{category_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling category delete: {e}")
            await query.edit_message_text("❌ خطا در حذف دسته‌بندی.")
    
    async def handle_confirm_category_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Confirm category deletion"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            panel_id = category['panel_id']
            
            if self.db.delete_category(category_id):
                await query.edit_message_text(
                    f"✅ دسته‌بندی '{category['name']}' با موفقیت حذف شد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_categories_{panel_id}")]
                    ])
                )
            else:
                await query.edit_message_text("❌ خطا در حذف دسته‌بندی.")
            
        except Exception as e:
            logger.error(f"Error confirming category delete: {e}")
            await query.edit_message_text("❌ خطا در حذف دسته‌بندی.")
    
    async def handle_manage_products_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show product management - panel selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get all panels
            panels = self.db.get_panels(active_only=True)
            
            if not panels:
                await query.edit_message_text(
                    "❌ هیچ پنل فعالی وجود ندارد.\n\nلطفاً ابتدا یک پنل اضافه کنید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products")]
                    ])
                )
                return
            
            message = "📦 **انتخاب پنل برای مدیریت محصولات:**\n\n"
            keyboard = []
            
            for panel in panels:
                keyboard.append([InlineKeyboardButton(
                    f"🔗 {panel['name']}",
                    callback_data=f"panel_products_{panel['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling manage products list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست پنل‌ها.")
    
    async def handle_panel_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show products for a panel - category selection or direct products"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Check if panel has products without category (check all products, not just active ones for admin panel)
            products_without_category = self.db.get_products(panel_id, category_id=False, active_only=False)
            has_products_without_category = len(products_without_category) > 0
            categories = self.db.get_categories(panel_id, active_only=True)
            
            # If no categories exist and no products without category, ask admin
            if not categories and not has_products_without_category:
                message = f"""
⚠️ **توجه**

هیچ دسته‌بندی‌ای برای پنل '{panel['name']}' وجود ندارد.

آیا می‌خواهید بدون دسته‌بندی محصول اضافه کنید؟
                """
                
                keyboard = [
                    [InlineKeyboardButton("✅ بله، ادامه", callback_data=f"products_no_category_{panel_id}")],
                    [InlineKeyboardButton("📁 افزودن دسته‌بندی", callback_data=f"add_category_{panel_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products_list")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                return
            
            # Show categories for selection (if categories exist)
            # If no categories but has products without category, show products directly
            if not categories and has_products_without_category:
                await self.handle_show_products_without_category(update, context, panel_id)
                return
            
            # Show categories for selection
            message = f"📦 **انتخاب دسته‌بندی برای پنل {panel['name']}:**\n\n"
            
            keyboard = []
            for cat in categories:
                keyboard.append([InlineKeyboardButton(
                    f"📁 {cat['name']}",
                    callback_data=f"category_products_{cat['id']}"
                )])
            
            # If has products without category, add a button for them
            if has_products_without_category:
                keyboard.append([InlineKeyboardButton(
                    "📦 محصولات بدون دسته‌بندی",
                    callback_data=f"products_no_category_{panel_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("➕ اضافه کردن محصول", callback_data=f"add_product_{panel_id}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products_list")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling panel products: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_products_no_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle products without category confirmation"""
        query = update.callback_query
        await query.answer()
        
        # Store that admin confirmed no category
        context.user_data['products_no_category_confirmed'] = True
        context.user_data['products_panel_id'] = panel_id
        
        # Show products without category
        await self.handle_show_products_without_category(update, context, panel_id)
    
    async def handle_show_products_without_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show products without category"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            products = self.db.get_products(panel_id, category_id=False, active_only=False)
            
            message = f"📦 **محصولات بدون دسته‌بندی - پنل {panel['name']}:**\n\n"
            
            if not products:
                message += "هیچ محصولی وجود ندارد.\n\n"
            else:
                for prod in products:
                    status = "🟢" if prod['is_active'] else "🔴"
                    message += f"{status} {prod['name']}\n"
                    message += f"   💰 {prod['price']:,} تومان | 📊 {prod['volume_gb']} GB | ⏱️ {prod['duration_days']} روز\n\n"
            
            keyboard = []
            
            for prod in products:
                status_icon = "🟢" if prod['is_active'] else "🔴"
                keyboard.append([InlineKeyboardButton(
                    f"{status_icon} {prod['name']} - {prod['price']:,} تومان",
                    callback_data=f"edit_product_{prod['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("➕ اضافه کردن محصول", callback_data=f"add_product_{panel_id}")])
            
            # If no products, allow adding categories
            if not products:
                keyboard.append([InlineKeyboardButton("📁 افزودن دسته‌بندی", callback_data=f"add_category_{panel_id}")])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products_list")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing products without category: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_category_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Show products in a category"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            panel = self.db.get_panel(category['panel_id'])
            panel_name = panel['name'] if panel else 'نامشخص'
            
            products = self.db.get_products(category['panel_id'], category_id=category_id, active_only=False)
            
            message = f"📦 **محصولات دسته‌بندی '{category['name']}' - پنل {panel_name}:**\n\n"
            
            if not products:
                message += "هیچ محصولی وجود ندارد.\n\n"
            else:
                for prod in products:
                    status = "🟢" if prod['is_active'] else "🔴"
                    message += f"{status} {prod['name']}\n"
                    message += f"   💰 {prod['price']:,} تومان | 📊 {prod['volume_gb']} GB | ⏱️ {prod['duration_days']} روز\n\n"
            
            keyboard = []
            
            for prod in products:
                status_icon = "🟢" if prod['is_active'] else "🔴"
                keyboard.append([InlineKeyboardButton(
                    f"{status_icon} {prod['name']} - {prod['price']:,} تومان",
                    callback_data=f"edit_product_{prod['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("➕ اضافه کردن محصول", callback_data=f"add_product_{category['panel_id']}_{category_id}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_products_{category['panel_id']}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling category products: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_add_product_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, category_id: int = None):
        """Start adding a new product"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            category_name = ""
            if category_id:
                category = self.db.get_category(category_id)
                if category:
                    category_name = f"دسته‌بندی: **{category['name']}**\n"
            
            message = f"""
➕ **اضافه کردن محصول جدید**

پنل: **{panel['name']}**
{category_name}
لطفاً نام محصول را وارد کنید:

💡 برای لغو عملیات /cancel را ارسال کنید.
            """
            
            callback_data = f"panel_products_{panel_id}" if not category_id else f"category_products_{category_id}"
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=callback_data)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Set state for adding product
            context.user_data['adding_product'] = True
            context.user_data['product_panel_id'] = panel_id
            context.user_data['product_category_id'] = category_id
            context.user_data['product_step'] = 'name'
            
        except Exception as e:
            logger.error(f"Error starting add product: {e}")
            await query.edit_message_text("❌ خطا در شروع افزودن محصول.")
    
    async def handle_add_product_text_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle product addition text flow"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ عملیات لغو شد.")
            panel_id = context.user_data.get('product_panel_id')
            category_id = context.user_data.get('product_category_id')
            context.user_data.clear()
            if panel_id:
                if category_id:
                    await self.handle_category_products(update, context, category_id)
                else:
                    await self.handle_panel_products(update, context, panel_id)
            return
        
        step = context.user_data.get('product_step', 'name')
        panel_id = context.user_data.get('product_panel_id')
        category_id = context.user_data.get('product_category_id')
        
        if step == 'name':
            if not text or len(text.strip()) < 2:
                await update.message.reply_text("❌ نام محصول باید حداقل ۲ کاراکتر باشد.")
                return
            
            context.user_data['product_name'] = text.strip()
            context.user_data['product_step'] = 'volume'
            await update.message.reply_text(
                "📊 **حجم محصول را به گیگابایت وارد کنید:**\n\nمثال: 10 یا 50"
            )
            
        elif step == 'volume':
            try:
                volume_gb = int(text)
                if volume_gb <= 0:
                    await update.message.reply_text("❌ حجم باید بیشتر از صفر باشد.")
                    return
                
                context.user_data['product_volume_gb'] = volume_gb
                context.user_data['product_step'] = 'duration'
                await update.message.reply_text(
                    "⏱️ **مدت زمان محصول را به روز وارد کنید:**\n\nمثال: 30 یا 90"
                )
            except ValueError:
                await update.message.reply_text("❌ حجم نامعتبر است. لطفاً عدد صحیح وارد کنید.")
                
        elif step == 'duration':
            try:
                duration_days = int(text)
                if duration_days <= 0:
                    await update.message.reply_text("❌ مدت زمان باید بیشتر از صفر باشد.")
                    return
                
                context.user_data['product_duration_days'] = duration_days
                context.user_data['product_step'] = 'price'
                await update.message.reply_text(
                    "💰 **قیمت محصول را به تومان وارد کنید:**\n\nمثال: 50000 یا 100000"
                )
            except ValueError:
                await update.message.reply_text("❌ مدت زمان نامعتبر است. لطفاً عدد صحیح وارد کنید.")
                
        elif step == 'price':
            try:
                price = int(text)
                if price <= 0:
                    await update.message.reply_text("❌ قیمت باید بیشتر از صفر باشد.")
                    return
                
                # Get all product data
                product_name = context.user_data.get('product_name')
                volume_gb = context.user_data.get('product_volume_gb')
                duration_days = context.user_data.get('product_duration_days')
                
                # Add product
                product_id = self.db.add_product(
                    panel_id=panel_id,
                    name=product_name,
                    volume_gb=volume_gb,
                    duration_days=duration_days,
                    price=price,
                    category_id=category_id
                )
                
                if product_id:
                    # Determine the correct callback based on whether product has category
                    if category_id:
                        callback_data = f"category_products_{category_id}"
                    else:
                        # Product without category - go to products without category view
                        callback_data = f"products_no_category_{panel_id}"
                    
                    await update.message.reply_text(
                        f"✅ محصول '{product_name}' با موفقیت اضافه شد!\n\n"
                        f"📊 حجم: {volume_gb} GB\n"
                        f"⏱️ مدت زمان: {duration_days} روز\n"
                        f"💰 قیمت: {price:,} تومان",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "📦 مشاهده محصولات",
                                callback_data=callback_data
                            )]
                        ])
                    )
                else:
                    await update.message.reply_text("❌ خطا در افزودن محصول.")
                
                context.user_data.clear()
                
            except ValueError:
                await update.message.reply_text("❌ قیمت نامعتبر است. لطفاً عدد صحیح وارد کنید.")
            except Exception as e:
                logger.error(f"Error adding product: {e}")
                await update.message.reply_text("❌ خطا در افزودن محصول.")
                context.user_data.clear()
    
    async def handle_edit_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Show product edit menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            panel = self.db.get_panel(product['panel_id'])
            panel_name = panel['name'] if panel else 'نامشخص'
            
            category_name = "بدون دسته‌بندی"
            if product.get('category_id'):
                category = self.db.get_category(product['category_id'])
                if category:
                    category_name = category['name']
            
            status_text = "🟢 فعال" if product['is_active'] else "🔴 غیرفعال"
            
            message = f"""
✏️ **ویرایش محصول**

**نام:** {product['name']}
**پنل:** {panel_name}
**دسته‌بندی:** {category_name}
**حجم:** {product['volume_gb']} GB
**مدت زمان:** {product['duration_days']} روز
**قیمت:** {product['price']:,} تومان
**وضعیت:** {status_text}

کدام مورد را می‌خواهید ویرایش کنید؟
            """
            
            keyboard = [
                [InlineKeyboardButton("📝 تغییر نام", callback_data=f"product_edit_{product_id}_name"), InlineKeyboardButton("📊 تغییر حجم", callback_data=f"product_edit_{product_id}_volume")],
                [InlineKeyboardButton("⏱️ تغییر مدت زمان", callback_data=f"product_edit_{product_id}_duration"), InlineKeyboardButton("💰 تغییر قیمت", callback_data=f"product_edit_{product_id}_price")],
                [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"product_toggle_{product_id}"), InlineKeyboardButton("🗑️ حذف", callback_data=f"product_delete_{product_id}")],
            ]
            
            # Add back button based on category
            if product.get('category_id'):
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"category_products_{product['category_id']}")])
            else:
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"panel_products_{product['panel_id']}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling edit product: {e}")
            await query.edit_message_text("❌ خطا در نمایش ویرایش محصول.")
    
    async def handle_product_edit_field(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, field: str):
        """Start editing a product field"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            field_names = {
                'name': 'نام محصول',
                'volume': 'حجم (GB)',
                'duration': 'مدت زمان (روز)',
                'price': 'قیمت (تومان)'
            }
            
            field_values = {
                'name': product['name'],
                'volume': str(product['volume_gb']),
                'duration': str(product['duration_days']),
                'price': f"{product['price']:,}"
            }
            
            message = f"""
✏️ **تغییر {field_names.get(field, field)}**

**مقدار فعلی:** {field_values.get(field, 'نامشخص')}

لطفاً مقدار جدید را وارد کنید:

💡 برای لغو عملیات /cancel را ارسال کنید.
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"edit_product_{product_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Set state
            context.user_data['editing_product_field'] = True
            context.user_data['product_id'] = product_id
            context.user_data['product_field'] = field
            
        except Exception as e:
            logger.error(f"Error starting product field edit: {e}")
            await query.edit_message_text("❌ خطا در شروع ویرایش.")
    
    async def handle_product_text_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle product field text edit"""
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ ویرایش لغو شد.")
            product_id = context.user_data.get('product_id')
            context.user_data.clear()
            if product_id:
                # Can't easily call async handler from text handler
                pass
            return
        
        product_id = context.user_data.get('product_id')
        field = context.user_data.get('product_field')
        
        if not product_id or not field:
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
            context.user_data.clear()
            return
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await update.message.reply_text("❌ محصول یافت نشد.")
                context.user_data.clear()
                return
            
            update_dict = {}
            
            if field == 'name':
                if not text or len(text.strip()) < 2:
                    await update.message.reply_text("❌ نام محصول باید حداقل ۲ کاراکتر باشد.")
                    return
                update_dict['name'] = text.strip()
                
            elif field == 'volume':
                try:
                    volume_gb = int(text)
                    if volume_gb <= 0:
                        await update.message.reply_text("❌ حجم باید بیشتر از صفر باشد.")
                        return
                    update_dict['volume_gb'] = volume_gb
                except ValueError:
                    await update.message.reply_text("❌ حجم نامعتبر است. لطفاً عدد صحیح وارد کنید.")
                    return
                    
            elif field == 'duration':
                try:
                    duration_days = int(text)
                    if duration_days <= 0:
                        await update.message.reply_text("❌ مدت زمان باید بیشتر از صفر باشد.")
                        return
                    update_dict['duration_days'] = duration_days
                except ValueError:
                    await update.message.reply_text("❌ مدت زمان نامعتبر است. لطفاً عدد صحیح وارد کنید.")
                    return
                    
            elif field == 'price':
                try:
                    # Remove commas and spaces
                    price_text = text.replace(',', '').replace(' ', '')
                    price = int(price_text)
                    if price <= 0:
                        await update.message.reply_text("❌ قیمت باید بیشتر از صفر باشد.")
                        return
                    update_dict['price'] = price
                except ValueError:
                    await update.message.reply_text("❌ قیمت نامعتبر است. لطفاً عدد صحیح وارد کنید.")
                    return
            
            # Update product
            if self.db.update_product(product_id, **update_dict):
                field_names = {
                    'name': 'نام محصول',
                    'volume': 'حجم',
                    'duration': 'مدت زمان',
                    'price': 'قیمت'
                }
                
                await update.message.reply_text(
                    f"✅ {field_names.get(field, field)} با موفقیت تغییر کرد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📦 مشاهده محصول", callback_data=f"edit_product_{product_id}")]
                    ])
                )
            else:
                await update.message.reply_text("❌ خطا در بروزرسانی محصول.")
            
            context.user_data.clear()
            
        except Exception as e:
            logger.error(f"Error updating product field: {e}")
            await update.message.reply_text("❌ خطا در بروزرسانی محصول.")
            context.user_data.clear()
    
    async def handle_product_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Toggle product active status"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            new_status = not product['is_active']
            
            if self.db.update_product(product_id, is_active=new_status):
                status_text = "فعال" if new_status else "غیرفعال"
                await query.edit_message_text(
                    f"✅ محصول {status_text} شد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"edit_product_{product_id}")]
                    ])
                )
            else:
                await query.edit_message_text("❌ خطا در تغییر وضعیت محصول.")
            
        except Exception as e:
            logger.error(f"Error toggling product: {e}")
            await query.edit_message_text("❌ خطا در تغییر وضعیت محصول.")
    
    # Test Account Configuration Methods
    async def handle_configure_test_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show test account configuration menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get current configuration
            test_config = self.db.get_test_account_config()
            current_info = ""
            if test_config['panel_id']:
                panel = self.db.get_panel(test_config['panel_id'])
                panel_name = panel['name'] if panel else "نامشخص"
                current_info = f"\n\n**تنظیمات فعلی:**\n🔗 پنل: {panel_name}"
                if test_config['inbound_id']:
                    current_info += f"\n📡 اینباند: {test_config['inbound_id']}"
            else:
                current_info = "\n\n**تنظیمات فعلی:**\n⚠️ تنظیم نشده"
            
            message = f"""
🧪 **تنظیمات اکانت تست**

از این بخش می‌توانید پنل و اینباند مورد نظر برای خرید اکانت تست (۱ گیگابایت) را تنظیم کنید.
{current_info}

لطفاً پنل مورد نظر را انتخاب کنید:
            """
            
            # Get all active panels with gigabyte sale type
            panels = self.db.get_panels(active_only=True)
            gigabyte_panels = [p for p in panels if p.get('sale_type', 'gigabyte') in ['gigabyte', 'both']]
            
            if not gigabyte_panels:
                await query.edit_message_text(
                    "❌ هیچ پنل فعالی با امکان خرید گیگابایتی موجود نیست.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products")]
                    ])
                )
                return
            
            keyboard = []
            for panel in gigabyte_panels:
                # Mark current panel if configured
                prefix = "✅ " if test_config['panel_id'] == panel['id'] else "🔗 "
                keyboard.append([InlineKeyboardButton(
                    f"{prefix}{panel['name']}",
                    callback_data=f"test_account_select_panel_{panel['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="manage_products")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling configure test account: {e}")
            await query.edit_message_text("❌ خطا در نمایش تنظیمات اکانت تست.")
    
    async def handle_test_account_select_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle panel selection for test account"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Get inbounds for this panel
            panel_manager = self.admin_manager.get_panel_manager(panel_id)
            if not panel_manager:
                await query.edit_message_text("❌ خطا در اتصال به پنل.")
                return
            
            if not panel_manager.login():
                await query.edit_message_text("❌ خطا در ورود به پنل.")
                return
            
            inbounds = panel_manager.get_inbounds()
            
            if not inbounds:
                # No inbounds, save panel only
                success = self.db.set_test_account_config(panel_id, None)
                if success:
                    await query.edit_message_text(
                        f"✅ پنل **{panel['name']}** برای اکانت تست تنظیم شد.\n\n⚠️ هیچ اینباندی در این پنل یافت نشد.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 بازگشت", callback_data="configure_test_account")]
                        ]),
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ خطا در ذخیره تنظیمات.")
                return
            
            # Show inbounds selection
            message = f"""
🧪 **انتخاب اینباند برای اکانت تست**

پنل انتخاب شده: **{panel['name']}**

لطفاً اینباند مورد نظر را انتخاب کنید:
            """
            
            keyboard = []
            for inbound in inbounds:
                inbound_id = inbound.get('id', 0)
                inbound_name = inbound.get('remark', f'Inbound {inbound_id}')
                inbound_protocol = inbound.get('protocol', 'unknown')
                inbound_port = inbound.get('port', 0)
                
                button_text = f"🔗 {inbound_name} ({inbound_protocol}:{inbound_port})"
                keyboard.append([InlineKeyboardButton(
                    button_text,
                    callback_data=f"test_account_select_inbound_{panel_id}_{inbound_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("⏭️ رد کردن (بدون اینباند)", callback_data="test_account_skip_inbound")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="configure_test_account")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Store panel_id in context for skip handler
            context.user_data['test_account_panel_id'] = panel_id
            
        except Exception as e:
            logger.error(f"Error handling test account panel selection: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در انتخاب پنل.")
    
    async def handle_test_account_select_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, inbound_id: int):
        """Handle inbound selection for test account"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Save configuration
            success = self.db.set_test_account_config(panel_id, inbound_id)
            
            if success:
                # Get inbound info for display
                panel_manager = self.admin_manager.get_panel_manager(panel_id)
                inbound_name = f"Inbound {inbound_id}"
                if panel_manager and panel_manager.login():
                    inbounds = panel_manager.get_inbounds()
                    for inbound in inbounds:
                        if inbound.get('id') == inbound_id:
                            inbound_name = inbound.get('remark', inbound_name)
                            break
                
                await query.edit_message_text(
                    f"✅ تنظیمات اکانت تست با موفقیت ذخیره شد.\n\n"
                    f"🔗 پنل: **{panel['name']}**\n"
                    f"📡 اینباند: **{inbound_name}** (ID: {inbound_id})\n\n"
                    f"از این پس، خرید اکانت تست از این پنل و اینباند انجام می‌شود.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="configure_test_account")]
                    ]),
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ خطا در ذخیره تنظیمات.")
            
        except Exception as e:
            logger.error(f"Error handling test account inbound selection: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در انتخاب اینباند.")
    
    async def handle_test_account_skip_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle skipping inbound selection for test account"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel_id = context.user_data.get('test_account_panel_id')
            if not panel_id:
                await query.edit_message_text("❌ خطا: پنل یافت نشد.")
                return
            
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Save configuration without inbound
            success = self.db.set_test_account_config(panel_id, None)
            
            if success:
                await query.edit_message_text(
                    f"✅ پنل **{panel['name']}** برای اکانت تست تنظیم شد.\n\n"
                    f"⚠️ اینباند تنظیم نشده است. از اینباند پیش‌فرض پنل استفاده خواهد شد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="configure_test_account")]
                    ]),
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ خطا در ذخیره تنظیمات.")
            
            # Clear context
            context.user_data.pop('test_account_panel_id', None)
            
        except Exception as e:
            logger.error(f"Error handling test account skip inbound: {e}")
            await query.edit_message_text("❌ خطا در ذخیره تنظیمات.")
    
    async def handle_product_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Delete a product"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            category_id = product.get('category_id')
            panel_id = product['panel_id']
            
            message = f"""
⚠️ **تأیید حذف محصول**

آیا مطمئن هستید که می‌خواهید محصول '{product['name']}' را حذف کنید؟

⚠️ این عمل غیرقابل بازگشت است!
            """
            
            keyboard = [
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"confirm_product_delete_{product_id}")],
                [InlineKeyboardButton("❌ لغو", callback_data=f"edit_product_{product_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling product delete: {e}")
            await query.edit_message_text("❌ خطا در حذف محصول.")
    
    async def handle_confirm_product_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Confirm product deletion"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            category_id = product.get('category_id')
            panel_id = product['panel_id']
            
            if self.db.delete_product(product_id):
                callback_data = f"category_products_{category_id}" if category_id else f"panel_products_{panel_id}"
                await query.edit_message_text(
                    f"✅ محصول '{product['name']}' با موفقیت حذف شد!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=callback_data)]
                    ])
                )
            else:
                await query.edit_message_text("❌ خطا در حذف محصول.")
            
        except Exception as e:
            logger.error(f"Error confirming product delete: {e}")
            await query.edit_message_text("❌ خطا در حذف محصول.")
    
    async def handle_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcasting a message to all users"""
        user_id = update.effective_user.id
        
        # Check if admin
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ شما دسترسی به این بخش ندارید.")
            return
        
        # Check if we're awaiting a broadcast message
        if not context.user_data.get('awaiting_broadcast_message'):
            return
        
        try:
            # Get all users
            user_ids = self.db.get_all_users_telegram_ids()
            
            if not user_ids:
                await update.message.reply_text("❌ هیچ کاربری در دیتابیس یافت نشد.")
                return
            
            # Send confirmation
            confirmation_text = f"📊 آماده ارسال پیام به {len(user_ids)} کاربر.\n\nآیا مطمئن هستید؟"
            
            keyboard = [
                [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_broadcast_message")],
                [InlineKeyboardButton("🚫 لغو", callback_data="broadcast_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
            
            # Store the message to broadcast
            context.user_data['broadcast_message_text'] = update.message.text
            context.user_data['broadcast_message_entities'] = update.message.entities
            context.user_data['total_users_to_broadcast'] = len(user_ids)
            context.user_data['awaiting_broadcast_message'] = False
            
        except Exception as e:
            logger.error(f"Error preparing broadcast message: {e}")
            await update.message.reply_text("❌ خطا در آماده‌سازی پیام همگانی.")
            context.user_data['awaiting_broadcast_message'] = False
    
    async def handle_broadcast_forward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle forwarding a message to all users"""
        user_id = update.effective_user.id
        
        # Check if admin
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ شما دسترسی به این بخش ندارید.")
            return
        
        # Check if we're awaiting a broadcast forward
        if not context.user_data.get('awaiting_broadcast_forward'):
            return
        
        try:
            # Get all users
            user_ids = self.db.get_all_users_telegram_ids()
            
            if not user_ids:
                await update.message.reply_text("❌ هیچ کاربری در دیتابیس یافت نشد.")
                return
            
            # Send confirmation
            confirmation_text = f"📊 آماده فوروارد پیام به {len(user_ids)} کاربر.\n\nآیا مطمئن هستید؟"
            
            keyboard = [
                [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_broadcast_forward")],
                [InlineKeyboardButton("🚫 لغو", callback_data="broadcast_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
            
            # Store the message to forward
            context.user_data['broadcast_message_id'] = update.message.message_id
            context.user_data['broadcast_chat_id'] = update.message.chat_id
            context.user_data['total_users_to_broadcast'] = len(user_ids)
            context.user_data['awaiting_broadcast_forward'] = False
            
        except Exception as e:
            logger.error(f"Error preparing broadcast forward: {e}")
            await update.message.reply_text("❌ خطا در آماده‌سازی فوروارد همگانی.")
            context.user_data['awaiting_broadcast_forward'] = False
    
    async def confirm_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and execute message broadcast"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_ids = self.db.get_all_users_telegram_ids()
            message_text = context.user_data.get('broadcast_message_text')
            message_entities = context.user_data.get('broadcast_message_entities')
            
            if not message_text:
                await query.edit_message_text("❌ پیام یافت نشد.")
                return
            
            # Send progress message
            progress_msg = await query.edit_message_text("⏳ در حال ارسال پیام همگانی...")
            
            success_count = 0
            failed_count = 0
            
            for user_id in user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        entities=message_entities
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)  # Small delay to avoid rate limiting
                except Exception as e:
                    logger.error(f"Failed to send message to user {user_id}: {e}")
                    failed_count += 1
            
            # Send completion message
            result_text = f"✅ ارسال پیام همگانی به پایان رسید.\n\n📊 تعداد کاربران: {len(user_ids)}\n✅ موفق: {success_count}\n❌ ناموفق: {failed_count}"
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await progress_msg.edit_text(result_text, reply_markup=reply_markup)
            
            # Send report to channel
            if self.reporting_system:
                admin_user = self.db.get_user(query.from_user.id)
                success_rate = (success_count / len(user_ids) * 100) if user_ids else 0
                await self.reporting_system.send_report(
                    'broadcast_message',
                    {
                        'total_users': len(user_ids),
                        'success_count': success_count,
                        'failed_count': failed_count,
                        'success_rate': success_rate,
                        'message_preview': message_text
                    },
                    admin_user
                )
            
            # Clean up user data
            context.user_data.pop('broadcast_message_text', None)
            context.user_data.pop('broadcast_message_entities', None)
            context.user_data.pop('total_users_to_broadcast', None)
            
        except Exception as e:
            logger.error(f"Error executing broadcast message: {e}")
            await query.edit_message_text("❌ خطا در ارسال پیام همگانی.")
    
    async def confirm_broadcast_forward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and execute message forward"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_ids = self.db.get_all_users_telegram_ids()
            message_id = context.user_data.get('broadcast_message_id')
            chat_id = context.user_data.get('broadcast_chat_id')
            
            if not message_id or not chat_id:
                await query.edit_message_text("❌ پیام یافت نشد.")
                return
            
            # Send progress message
            progress_msg = await query.edit_message_text("⏳ در حال فوروارد پیام همگانی...")
            
            success_count = 0
            failed_count = 0
            
            for user_id in user_ids:
                try:
                    await context.bot.forward_message(
                        chat_id=user_id,
                        from_chat_id=chat_id,
                        message_id=message_id
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)  # Small delay to avoid rate limiting
                except Exception as e:
                    logger.error(f"Failed to forward message to user {user_id}: {e}")
                    failed_count += 1
            
            # Send completion message
            result_text = f"✅ فوروارد پیام همگانی به پایان رسید.\n\n📊 تعداد کاربران: {len(user_ids)}\n✅ موفق: {success_count}\n❌ ناموفق: {failed_count}"
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await progress_msg.edit_text(result_text, reply_markup=reply_markup)
            
            # Send report to channel
            if self.reporting_system:
                admin_user = self.db.get_user(query.from_user.id)
                success_rate = (success_count / len(user_ids) * 100) if user_ids else 0
                await self.reporting_system.send_report(
                    'broadcast_forward',
                    {
                        'total_users': len(user_ids),
                        'success_count': success_count,
                        'failed_count': failed_count,
                        'success_rate': success_rate
                    },
                    admin_user
                )
            
            # Clean up user data
            context.user_data.pop('broadcast_message_id', None)
            context.user_data.pop('broadcast_chat_id', None)
            context.user_data.pop('total_users_to_broadcast', None)
            
        except Exception as e:
            logger.error(f"Error executing broadcast forward: {e}")
            await query.edit_message_text("❌ خطا در فوروارد پیام همگانی.")
    
    async def handle_user_services_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user services menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "👥 خدمات کاربران\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
            
            keyboard = [
                [InlineKeyboardButton("👤 اطلاعات کاربران", callback_data="user_info_request"), InlineKeyboardButton("🎁 هدیه به تمام کاربران", callback_data="gift_all_users_request")],
                [InlineKeyboardButton("👑 مدیریت ادمین‌ها", callback_data="manage_admins")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling user services menu: {e}")
            await query.edit_message_text("❌ خطا در نمایش منوی خدمات کاربران.")
    
    async def handle_user_info_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request user ID for viewing info"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "👤 اطلاعات کاربران\n\nلطفاً آیدی عددی کاربر مورد نظر را ارسال کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data="user_services_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state for next message
            context.user_data['awaiting_user_id_for_info'] = True
            
        except Exception as e:
            logger.error(f"Error requesting user info: {e}")
            await query.edit_message_text("❌ خطا در درخواست اطلاعات کاربر.")
    
    async def handle_gift_all_users_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request gift amount for all users"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "🎁 هدیه به تمام کاربران\n\nلطفاً مبلغ هدیه (به تومان) را ارسال کنید:\n\nمثال: 5000 یا 10000"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data="user_services_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state for next message
            context.user_data['awaiting_gift_amount'] = True
            
        except Exception as e:
            logger.error(f"Error requesting gift amount: {e}")
            await query.edit_message_text("❌ خطا در درخواست مبلغ هدیه.")
    
    async def handle_manage_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle manage admins menu - show list of admins"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get all admins from database
            admins = self.db.get_all_admins()
            
            if not admins:
                message = "👑 مدیریت ادمین‌ها\n\nهیچ ادمینی یافت نشد."
            else:
                message = "👑 مدیریت ادمین‌ها"
            
            keyboard = []
            
            # Add button for each admin
            for admin in admins:
                admin_name = admin.get('first_name', '') or admin.get('username', '') or 'بدون نام'
                admin_telegram_id = admin.get('telegram_id', 0)
                is_active = admin.get('is_admin', 0) == 1
                status_emoji = "🟢" if is_active else "🔴"
                
                button_text = f"{status_emoji} {admin_name} ({admin_telegram_id})"
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"admin_detail_{admin_telegram_id}")
                ])
            
            # Add button to add new admin
            keyboard.append([
                InlineKeyboardButton("➕ اضافه کردن ادمین", callback_data="add_admin")
            ])
            
            # Add back button
            keyboard.append([
                InlineKeyboardButton("🔙 بازگشت", callback_data="user_services_menu")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling manage admins: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست ادمین‌ها.")
    
    async def handle_add_admin_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request admin telegram ID to add"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "➕ اضافه کردن ادمین\n\nلطفاً آیدی عددی کاربر مورد نظر برای ادمین کردن را ارسال کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data="manage_admins")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state for next message
            context.user_data['awaiting_admin_id'] = True
            
        except Exception as e:
            logger.error(f"Error requesting admin ID: {e}")
            await query.edit_message_text("❌ خطا در درخواست آیدی ادمین.")
    
    async def handle_add_admin_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle adding admin by telegram ID"""
        try:
            # Get the admin ID from message
            admin_telegram_id = int(update.message.text.strip())
            
            # Check if user exists
            user = self.db.get_user(admin_telegram_id)
            
            if not user:
                # Try to get user from Telegram API and register them
                try:
                    from telegram import Bot
                    bot = context.bot
                    tg_user = await bot.get_chat(admin_telegram_id)
                    
                    # Register the user
                    new_user_db_id = self.db.add_user(
                        telegram_id=admin_telegram_id,
                        username=tg_user.username,
                        first_name=tg_user.first_name,
                        last_name=tg_user.last_name,
                        is_admin=True
                    )
                    
                    if new_user_db_id:
                        user = self.db.get_user(admin_telegram_id)
                        logger.info(f"✅ User {admin_telegram_id} registered and set as admin")
                    else:
                        await update.message.reply_text("❌ کاربر با این آیدی یافت نشد و امکان ثبت خودکار وجود نداشت.")
                        context.user_data['awaiting_admin_id'] = False
                        return
                except Exception as e:
                    logger.error(f"Error trying to auto-register admin {admin_telegram_id}: {e}")
                    await update.message.reply_text("❌ کاربر با این آیدی یافت نشد.")
                    context.user_data['awaiting_admin_id'] = False
                    return
            
            # Set user as admin
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_admin = 1 WHERE telegram_id = %s', (admin_telegram_id,))
                conn.commit()
                cursor.close()
            
            admin_name = user.get('first_name', '') or user.get('username', '') or 'بدون نام'
            message = f"✅ کاربر {admin_name} ({admin_telegram_id}) با موفقیت به عنوان ادمین اضافه شد."
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت به لیست ادمین‌ها", callback_data="manage_admins")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, reply_markup=reply_markup)
            
            # Clear state
            context.user_data['awaiting_admin_id'] = False
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await update.message.reply_text("❌ خطا در اضافه کردن ادمین.")
            context.user_data['awaiting_admin_id'] = False
    
    async def handle_admin_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, admin_telegram_id: int):
        """Handle admin detail view - show management options"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get admin info
            admin = self.db.get_user(admin_telegram_id)
            if not admin:
                await query.edit_message_text("❌ ادمین یافت نشد.")
                return
            
            admin_name = admin.get('first_name', '') or admin.get('username', '') or 'بدون نام'
            is_active = admin.get('is_admin', 0) == 1
            status_text = "فعال" if is_active else "غیرفعال"
            status_emoji = "🟢" if is_active else "🔴"
            
            message = f"👑 مدیریت ادمین\n\n👤 نام: {admin_name}\n🆔 آیدی: {admin_telegram_id}\n📊 وضعیت: {status_emoji} {status_text}"
            
            keyboard = []
            
            # Toggle status button
            toggle_text = "🔴 غیرفعال کردن" if is_active else "🟢 فعال کردن"
            keyboard.append([
                InlineKeyboardButton(toggle_text, callback_data=f"admin_toggle_{admin_telegram_id}")
            ])
            
            # Delete admin button
            keyboard.append([
                InlineKeyboardButton("🗑️ حذف ادمین", callback_data=f"admin_delete_{admin_telegram_id}")
            ])
            
            # Back button
            keyboard.append([
                InlineKeyboardButton("🔙 بازگشت", callback_data="manage_admins")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling admin detail: {e}")
            await query.edit_message_text("❌ خطا در نمایش جزئیات ادمین.")
    
    async def handle_admin_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, admin_telegram_id: int):
        """Toggle admin status (active/inactive)"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get current admin status
            admin = self.db.get_user(admin_telegram_id)
            if not admin:
                await query.edit_message_text("❌ ادمین یافت نشد.")
                return
            
            current_status = admin.get('is_admin', 0) == 1
            new_status = not current_status
            
            # Update admin status in database
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_admin = %s WHERE telegram_id = %s', (1 if new_status else 0, admin_telegram_id))
                conn.commit()
                cursor.close()
            
            status_text = "فعال" if new_status else "غیرفعال"
            message = f"✅ وضعیت ادمین به {status_text} تغییر یافت."
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_admins")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error toggling admin status: {e}")
            await query.edit_message_text("❌ خطا در تغییر وضعیت ادمین.")
    
    async def handle_admin_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE, admin_telegram_id: int):
        """Delete admin (remove admin privileges)"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Prevent deleting main admin from config
            if admin_telegram_id == self.bot_config['admin_id']:
                await query.edit_message_text("❌ نمی‌توانید ادمین اصلی را حذف کنید.")
                return
            
            # Get admin info
            admin = self.db.get_user(admin_telegram_id)
            if not admin:
                await query.edit_message_text("❌ ادمین یافت نشد.")
                return
            
            # Remove admin privileges
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_admin = 0 WHERE telegram_id = %s', (admin_telegram_id,))
                conn.commit()
                cursor.close()
            
            admin_name = admin.get('first_name', '') or admin.get('username', '') or 'بدون نام'
            message = f"✅ دسترسی ادمین برای {admin_name} ({admin_telegram_id}) حذف شد."
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="manage_admins")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error deleting admin: {e}")
            await query.edit_message_text("❌ خطا در حذف ادمین.")
    
    async def handle_gift_all_users_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute gift to all users"""
        user_id = update.effective_user.id
        
        # Check if admin
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ شما دسترسی به این بخش ندارید.")
            return
        
        # Check if we're awaiting gift amount
        if not context.user_data.get('awaiting_gift_amount'):
            return
        
        try:
            # Get the gift amount from message
            amount_text = update.message.text.strip().replace(',', '').replace('،', '')
            gift_amount = int(amount_text)
            
            if gift_amount <= 0:
                await update.message.reply_text("❌ مبلغ باید بیشتر از صفر باشد.")
                context.user_data['awaiting_gift_amount'] = False
                return
            
            # Get all users
            all_users = self.db.get_all_users()
            
            if not all_users or len(all_users) == 0:
                await update.message.reply_text("❌ هیچ کاربری یافت نشد.")
                context.user_data['awaiting_gift_amount'] = False
                return
            
            # Show confirmation
            total_cost = gift_amount * len(all_users)
            message = f"""
🎁 **هدیه به تمام کاربران**

💰 مبلغ هدیه: {gift_amount:,} تومان
👥 تعداد کاربران: {len(all_users)} نفر
💵 مجموع هزینه: {total_cost:,} تومان

⚠️ آیا از ارسال این هدیه اطمینان دارید؟
            """
            
            keyboard = [
                [InlineKeyboardButton("✅ تأیید و ارسال", callback_data=f"confirm_gift_all_{gift_amount}")],
                [InlineKeyboardButton("❌ انصراف", callback_data="user_services_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Store gift amount in context
            context.user_data['gift_amount'] = gift_amount
            context.user_data['awaiting_gift_amount'] = False
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.\n\nمثال: 5000")
        except Exception as e:
            logger.error(f"Error processing gift amount: {e}")
            await update.message.reply_text("❌ خطا در پردازش مبلغ هدیه.")
            context.user_data['awaiting_gift_amount'] = False
    
    async def handle_confirm_gift_all_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE, gift_amount: int):
        """Confirm and execute gift to all users"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        # Check if admin
        if not self.db.is_admin(user_id):
            await query.edit_message_text("❌ شما دسترسی به این بخش ندارید.")
            return
        
        try:
            # Get all users
            all_users = self.db.get_all_users()
            
            if not all_users or len(all_users) == 0:
                await query.edit_message_text("❌ هیچ کاربری یافت نشد.")
                return
            
            # Update message to show progress
            await query.edit_message_text("⏳ در حال ارسال هدیه به تمام کاربران...")
            
            success_count = 0
            failed_count = 0
            
            # Process each user
            for user in all_users:
                try:
                    telegram_id = user.get('telegram_id')
                    if not telegram_id:
                        failed_count += 1
                        continue
                    
                    # Add balance to user
                    current_balance = user.get('balance', 0)
                    new_balance = current_balance + gift_amount
                    
                    # Update balance in database
                    self.db.update_user_balance(telegram_id, gift_amount, 'gift', f'هدیه از طرف مدیریت')
                    
                    # Send notification to user
                    try:
                        notification_message = f"""
🎁 **هدیه از طرف مدیریت**

💰 مبلغ هدیه: {gift_amount:,} تومان
💵 موجودی جدید: {new_balance:,} تومان

💡 می‌توانید از این موجودی برای خرید بسته و حجم دلخواه خود استفاده کنید.

🔹 برای خرید سرویس از منوی اصلی استفاده کنید.
                        """
                        
                        keyboard = [
                            [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy_service")],
                            [InlineKeyboardButton("📊 پنل کاربری", callback_data="user_panel")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await context.bot.send_message(
                            chat_id=telegram_id,
                            text=notification_message,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                        
                        success_count += 1
                        
                    except Exception as e:
                        logger.error(f"Error sending notification to user {telegram_id}: {e}")
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Error processing gift for user {user.get('telegram_id')}: {e}")
                    failed_count += 1
            
            # Show final result
            result_message = f"""
✅ **هدیه با موفقیت ارسال شد**

💰 مبلغ هدیه: {gift_amount:,} تومان
✅ موفق: {success_count} کاربر
❌ ناموفق: {failed_count} کاربر
👥 مجموع: {len(all_users)} کاربر
            """
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت به منوی خدمات کاربران", callback_data="user_services_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(result_message, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Report to admin if reporting system exists
            try:
                if hasattr(self, 'reporting_system') and self.reporting_system:
                    admin_user = self.db.get_user(user_id)
                    await self.reporting_system.send_report(
                        'gift_all_users',
                        {
                            'gift_amount': gift_amount,
                            'total_users': len(all_users),
                            'success_count': success_count,
                            'failed_count': failed_count
                        },
                        admin_user
                    )
            except Exception as e:
                logger.error(f"Error sending gift report: {e}")
            
        except Exception as e:
            logger.error(f"Error executing gift to all users: {e}")
            await query.edit_message_text("❌ خطا در ارسال هدیه به کاربران.")
    
    async def handle_user_info_display(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display user information"""
        user_id = update.effective_user.id
        
        # Check if admin
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ شما دسترسی به این بخش ندارید.")
            return
        
        # Check if we're awaiting a user ID
        if not context.user_data.get('awaiting_user_id_for_info'):
            return
        
        try:
            # Get the user ID from message
            target_user_id = int(update.message.text.strip())
            
            # Get user info
            user_info = self.db.get_user(target_user_id)
            
            if not user_info:
                # Try to get user from Telegram API and register them
                try:
                    from telegram import Bot
                    bot = context.bot
                    tg_user = await bot.get_chat(target_user_id)
                    
                    # Register the user
                    new_user_db_id = self.db.add_user(
                        telegram_id=target_user_id,
                        username=tg_user.username,
                        first_name=tg_user.first_name,
                        last_name=tg_user.last_name,
                        is_admin=((target_user_id == self.bot_config['admin_id']) or self.db.is_admin(target_user_id))
                    )
                    
                    if new_user_db_id:
                        # Get the newly registered user
                        user_info = self.db.get_user(target_user_id)
                        logger.info(f"✅ User {target_user_id} registered automatically during admin search")
                    else:
                        await update.message.reply_text("❌ کاربر با این آیدی یافت نشد و امکان ثبت خودکار وجود نداشت.")
                        context.user_data['awaiting_user_id_for_info'] = False
                        return
                except Exception as e:
                    logger.error(f"Error trying to auto-register user {target_user_id}: {e}")
                    await update.message.reply_text("❌ کاربر با این آیدی یافت نشد.")
                    context.user_data['awaiting_user_id_for_info'] = False
                    return
            
            if not user_info:
                await update.message.reply_text("❌ کاربر با این آیدی یافت نشد.")
                context.user_data['awaiting_user_id_for_info'] = False
                return
            
            # Format user info with Persian dates
            # Handle both datetime objects and strings
            created_at_raw = user_info.get('created_at', '')
            if created_at_raw:
                if isinstance(created_at_raw, datetime):
                    created_at = PersianDateTime.format_datetime(created_at_raw)
                else:
                    created_at = format_db_datetime(str(created_at_raw))
            else:
                created_at = 'نامشخص'
            
            last_activity_raw = user_info.get('last_activity', '')
            if last_activity_raw:
                if isinstance(last_activity_raw, datetime):
                    last_activity = PersianDateTime.format_datetime(last_activity_raw)
                else:
                    last_activity = format_db_datetime(str(last_activity_raw))
            else:
                last_activity = 'نامشخص'
            
            # Escape special Markdown characters in user-provided data
            # For values inside backticks, we need to escape backticks themselves
            telegram_id_raw = str(user_info['telegram_id'])
            telegram_id_str = telegram_id_raw.replace('`', '\\`') if '`' in telegram_id_raw else telegram_id_raw
            # For regular text, escape all markdown special characters
            first_name = escape_markdown(user_info.get('first_name', 'نامشخص') or 'نامشخص', version=1)
            last_name = escape_markdown(user_info.get('last_name', '') or '', version=1)
            username = escape_markdown(user_info.get('username', 'ندارد') or 'ندارد', version=1)
            # Ensure created_at and last_activity are strings before escaping
            created_at_escaped = escape_markdown(str(created_at), version=1)
            last_activity_escaped = escape_markdown(str(last_activity), version=1)
            
            info_text = f"""
👤 **اطلاعات کاربر**

🆔 آیدی: `{telegram_id_str}`
👤 نام: {first_name} {last_name}
📝 نام کاربری: @{username}
💰 موجودی: {user_info.get('balance', 0):,} تومان
📅 تاریخ عضویت: {created_at_escaped}
⏰ آخرین فعالیت: {last_activity_escaped}
🔧 تعداد سرویس‌ها: {user_info.get('total_services', 0)}
💸 مجموع خرید: {user_info.get('total_spent', 0):,} تومان
"""
            
            keyboard = [
                [
                    InlineKeyboardButton("➕ افزایش موجودی", callback_data=f"user_add_balance_{target_user_id}"),
                    InlineKeyboardButton("➖ کاهش موجودی", callback_data=f"user_decrease_balance_{target_user_id}")
                ],
                [InlineKeyboardButton("🔧 دیدن سرویس‌ها", callback_data=f"user_services_{target_user_id}_1")],
                [InlineKeyboardButton("💳 تراکنش‌های اخیر", callback_data=f"user_transactions_{target_user_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')
            
            # Send report to channel
            if self.reporting_system:
                admin_user = self.db.get_user(user_id)
                await self.reporting_system.send_report(
                    'admin_view_user_info',
                    {
                        'target_user': user_info
                    },
                    admin_user
                )
            
            # Clean up
            context.user_data['awaiting_user_id_for_info'] = False
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
        except Exception as e:
            logger.error(f"Error displaying user info: {e}")
            await update.message.reply_text("❌ خطا در نمایش اطلاعات کاربر.")
            context.user_data['awaiting_user_id_for_info'] = False
    
    async def handle_user_add_balance_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request amount for adding to user balance"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract user ID from callback data
            target_user_id = int(query.data.split("_")[-1])
            
            message = f"➕ افزایش موجودی کاربر {target_user_id}\n\nلطفاً مقدار مورد نظر را به تومان وارد کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data=f"user_info_show_{target_user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state
            context.user_data['awaiting_balance_amount'] = 'add'
            context.user_data['target_user_id'] = target_user_id
            
        except Exception as e:
            logger.error(f"Error requesting balance addition: {e}")
            await query.edit_message_text("❌ خطا در درخواست افزایش موجودی.")
    
    async def handle_user_decrease_balance_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request amount for decreasing user balance"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract user ID from callback data
            target_user_id = int(query.data.split("_")[-1])
            
            message = f"➖ کاهش موجودی کاربر {target_user_id}\n\nلطفاً مقدار مورد نظر را به تومان وارد کنید:"
            
            keyboard = [
                [InlineKeyboardButton("🔙 انصراف", callback_data=f"user_info_show_{target_user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
            # Store state
            context.user_data['awaiting_balance_amount'] = 'decrease'
            context.user_data['target_user_id'] = target_user_id
            
        except Exception as e:
            logger.error(f"Error requesting balance decrease: {e}")
            await query.edit_message_text("❌ خطا در درخواست کاهش موجودی.")
    
    async def handle_balance_amount_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle balance amount input from admin"""
        user_id = update.effective_user.id
        
        # Check if admin
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ شما دسترسی به این بخش ندارید.")
            return
        
        # Check if we're awaiting a balance amount
        if not context.user_data.get('awaiting_balance_amount'):
            return
        
        try:
            amount = int(update.message.text.strip().replace(',', ''))
            action = context.user_data.get('awaiting_balance_amount')
            target_user_id = context.user_data.get('target_user_id')
            
            if not target_user_id:
                await update.message.reply_text("❌ خطا: کاربر هدف یافت نشد.")
                return
            
            # Get current balance
            user_info = self.db.get_user(target_user_id)
            if not user_info:
                await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            current_balance = user_info.get('balance', 0)
            
            if action == 'add':
                # Add to balance (only update_user_balance which updates both balance and logs transaction)
                self.db.update_user_balance(target_user_id, amount, 'admin_credit', f'افزایش توسط ادمین')
                new_balance = current_balance + amount
                
                result_text = f"✅ موجودی کاربر {target_user_id} با موفقیت افزایش یافت.\n\n💰 موجودی قبلی: {current_balance:,} تومان\n➕ مقدار افزایش: {amount:,} تومان\n💰 موجودی جدید: {new_balance:,} تومان"
                
                # Send notification to user
                try:
                    user_notification = f"""
🎉 موجودی شما افزایش یافت!

💰 مبلغ افزایش: {amount:,} تومان
💰 موجودی قبلی: {current_balance:,} تومان
💰 موجودی جدید: {new_balance:,} تومان

✅ این موجودی توسط مدیریت به حساب شما اضافه شده است.
"""
                    await context.bot.send_message(chat_id=target_user_id, text=user_notification)
                except Exception as e:
                    logger.error(f"Failed to send notification to user {target_user_id}: {e}")
                
                # Send report to channel
                if self.reporting_system:
                    admin_user = self.db.get_user(user_id)
                    await self.reporting_system.send_report(
                        'admin_balance_increase',
                        {
                            'target_user': user_info,
                            'old_balance': current_balance,
                            'amount': amount,
                            'new_balance': new_balance
                        },
                        admin_user
                    )
                    
            else:  # decrease
                # Decrease balance (only update_user_balance which updates both balance and logs transaction)
                self.db.update_user_balance(target_user_id, -amount, 'admin_debit', f'کاهش توسط ادمین')
                new_balance = max(0, current_balance - amount)
                
                result_text = f"✅ موجودی کاربر {target_user_id} با موفقیت کاهش یافت.\n\n💰 موجودی قبلی: {current_balance:,} تومان\n➖ مقدار کاهش: {amount:,} تومان\n💰 موجودی جدید: {new_balance:,} تومان"
                
                # Send notification to user
                try:
                    user_notification = f"""
⚠️ موجودی شما کاهش یافت!

💰 مبلغ کاهش: {amount:,} تومان
💰 موجودی قبلی: {current_balance:,} تومان
💰 موجودی جدید: {new_balance:,} تومان

📌 این موجودی توسط مدیریت از حساب شما کسر شده است.
"""
                    await context.bot.send_message(chat_id=target_user_id, text=user_notification)
                except Exception as e:
                    logger.error(f"Failed to send notification to user {target_user_id}: {e}")
                
                # Send report to channel
                if self.reporting_system:
                    admin_user = self.db.get_user(user_id)
                    await self.reporting_system.send_report(
                        'admin_balance_decrease',
                        {
                            'target_user': user_info,
                            'old_balance': current_balance,
                            'amount': amount,
                            'new_balance': new_balance
                        },
                        admin_user
                    )
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت به اطلاعات کاربر", callback_data=f"user_info_show_{target_user_id}")],
                [InlineKeyboardButton("🏠 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(result_text, reply_markup=reply_markup)
            
            # Clean up
            context.user_data.pop('awaiting_balance_amount', None)
            context.user_data.pop('target_user_id', None)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
        except Exception as e:
            logger.error(f"Error handling balance amount: {e}")
            await update.message.reply_text("❌ خطا در تغییر موجودی کاربر.")
            context.user_data.pop('awaiting_balance_amount', None)
            context.user_data.pop('target_user_id', None)
    
    async def handle_user_services_view(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View user services with pagination"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract user ID and page from callback data
            parts = query.data.split("_")
            target_user_id = int(parts[2])
            page = int(parts[3])
            
            # Get services with pagination
            services, total = self.db.get_user_services_paginated(target_user_id, page, 10)
            
            if not services:
                await query.edit_message_text(
                    f"❌ کاربر {target_user_id} هیچ سرویسی ندارد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"user_info_show_{target_user_id}")]])
                )
                return
            
            # Calculate pages
            total_pages = (total + 9) // 10
            
            # Format header
            services_text = f"🔧 **سرویس‌های کاربر {target_user_id}**\n\n📊 صفحه {page} از {total_pages} (مجموع: {total} سرویس)"
            
            # Create service buttons
            keyboard = []
            
            for service in services:
                status_emoji = "🟢" if service.get('is_active') else "🔴"
                service_name = service.get('client_name', 'Unknown')
                service_gb = service.get('total_gb', 0)
                
                button_text = f"{status_emoji} {service_name} ({service_gb}GB)"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"admin_manage_service_{service['id']}")])
            
            # Create pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"user_services_{target_user_id}_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"user_services_{target_user_id}_{page+1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"user_info_show_{target_user_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(services_text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error viewing user services: {e}")
            await query.edit_message_text("❌ خطا در نمایش سرویس‌های کاربر.")
    
    async def handle_user_transactions_view(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View user transactions"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract user ID from callback data (format: user_transactions_123456789)
            parts = query.data.split("_")
            target_user_id = int(parts[2])
            
            logger.info(f"Fetching transactions for user {target_user_id}")
            
            # Get transactions
            transactions = self.db.get_user_transactions(target_user_id, 10)
            
            logger.info(f"Found {len(transactions)} transactions")
            
            if not transactions:
                await query.edit_message_text(
                    f"❌ کاربر {target_user_id} هیچ تراکنشی ندارد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"user_info_show_{target_user_id}")]])
                )
                return
            
            # Format transactions list (without markdown to avoid parsing issues)
            trans_text = f"💳 تراکنش‌های اخیر کاربر {target_user_id}\n\n"
            
            # Persian translation for transaction types
            trans_type_persian = {
                'service_purchase': 'خرید سرویس',
                'balance_added': 'افزایش موجودی',
                'balance_recharge': 'شارژ حساب',
                'refund': 'بازگشت مبلغ',
                'referral_reward': 'پاداش دعوت',
                'welcome_bonus': 'هدیه ثبت نام',
                'gift': 'هدیه',
                'admin_credit': 'افزایش توسط ادمین',
                'admin_debit': 'کاهش توسط ادمین',
                'volume_purchase': 'خرید حجم',
                'service_renewal': 'تمدید سرویس'
            }
            
            for idx, trans in enumerate(transactions, start=1):
                amount = trans.get('amount', 0)
                trans_type = trans.get('transaction_type', 'unknown')
                description = trans.get('description', 'بدون توضیح')
                created_at_raw = trans.get('created_at', 'نامشخص')
                
                # Format Persian date
                created_at = format_db_datetime(created_at_raw) if created_at_raw and created_at_raw != 'نامشخص' else 'نامشخص'
                
                # Translate transaction type to Persian
                trans_type_persian_text = trans_type_persian.get(trans_type, trans_type.replace('_', ' '))
                
                # Escape special characters that might interfere
                description = str(description).replace('_', ' ').replace('*', ' ').replace('`', ' ').replace('[', '(').replace(']', ')')
                
                amount_sign = "+" if amount > 0 else ""
                trans_text += f"{idx}. {amount_sign}{amount:,} تومان\n"
                trans_text += f"   📝 نوع: {trans_type_persian_text}\n"
                trans_text += f"   💬 توضیح: {description}\n"
                trans_text += f"   📅 تاریخ: {created_at}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"user_info_show_{target_user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send without parse_mode to avoid parsing issues
            await query.edit_message_text(trans_text, reply_markup=reply_markup)
            
        except Exception as e:
            import traceback
            logger.error(f"Error viewing user transactions: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در نمایش تراکنش‌های کاربر.")
    
    async def handle_user_info_show(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user info again after actions"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract user ID from callback data
            target_user_id = int(query.data.split("_")[-1])
            
            # Get user info
            user_info = self.db.get_user(target_user_id)
            
            if not user_info:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Format user info with Persian dates
            # Handle both datetime objects and strings
            created_at_raw = user_info.get('created_at', '')
            if created_at_raw:
                if isinstance(created_at_raw, datetime):
                    created_at = PersianDateTime.format_datetime(created_at_raw)
                else:
                    created_at = format_db_datetime(str(created_at_raw))
            else:
                created_at = 'نامشخص'
            
            last_activity_raw = user_info.get('last_activity', '')
            if last_activity_raw:
                if isinstance(last_activity_raw, datetime):
                    last_activity = PersianDateTime.format_datetime(last_activity_raw)
                else:
                    last_activity = format_db_datetime(str(last_activity_raw))
            else:
                last_activity = 'نامشخص'
            
            # Escape special Markdown characters in user-provided data
            # For values inside backticks, we need to escape backticks themselves
            telegram_id_raw = str(user_info['telegram_id'])
            telegram_id_str = telegram_id_raw.replace('`', '\\`') if '`' in telegram_id_raw else telegram_id_raw
            # For regular text, escape all markdown special characters
            first_name = escape_markdown(user_info.get('first_name', 'نامشخص') or 'نامشخص', version=1)
            last_name = escape_markdown(user_info.get('last_name', '') or '', version=1)
            username = escape_markdown(user_info.get('username', 'ندارد') or 'ندارد', version=1)
            # Ensure created_at and last_activity are strings before escaping
            created_at_escaped = escape_markdown(str(created_at), version=1)
            last_activity_escaped = escape_markdown(str(last_activity), version=1)
            
            info_text = f"""
👤 **اطلاعات کاربر**

🆔 آیدی: `{telegram_id_str}`
👤 نام: {first_name} {last_name}
📝 نام کاربری: @{username}
💰 موجودی: {user_info.get('balance', 0):,} تومان
📅 تاریخ عضویت: {created_at_escaped}
⏰ آخرین فعالیت: {last_activity_escaped}
🔧 تعداد سرویس‌ها: {user_info.get('total_services', 0)}
💸 مجموع خرید: {user_info.get('total_spent', 0):,} تومان
"""
            
            keyboard = [
                [
                    InlineKeyboardButton("➕ افزایش موجودی", callback_data=f"user_add_balance_{target_user_id}"),
                    InlineKeyboardButton("➖ کاهش موجودی", callback_data=f"user_decrease_balance_{target_user_id}")
                ],
                [InlineKeyboardButton("🔧 دیدن سرویس‌ها", callback_data=f"user_services_{target_user_id}_1")],
                [InlineKeyboardButton("💳 تراکنش‌های اخیر", callback_data=f"user_transactions_{target_user_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="user_services_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing user info: {e}")
            await query.edit_message_text("❌ خطا در نمایش اطلاعات کاربر.")
    
    @auto_update_user_info
    async def handle_admin_manage_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin management of user service with full control"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Extract service ID from callback data
            service_id = int(query.data.split("_")[-1])
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, u.telegram_id as user_telegram_id,
                           u.first_name as user_first_name, u.last_name as user_last_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    JOIN users u ON c.user_id = u.id
                    WHERE c.id = %s
                ''', (service_id,))
                row = cursor.fetchone()
                
                if not row:
                    await query.edit_message_text("❌ سرویس یافت نشد.")
                    return
                
                service = dict(row)
            
            # Get detailed client info from panel (similar to user view)
            remaining_gb = service.get('total_gb', 0)
            used_gb = 0
            status = "❌ نامشخص"
            connection_status = "❌ نامشخص"
            expire_days = "نامحدود"
            client_email = service.get('client_name', 'Unknown')
            total_gb = service.get('total_gb', 0)
            
            try:
                panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
                if panel_manager and panel_manager.login():
                    logger.info(f"Admin: Getting client details for service {service['id']}")
                    
                    # Create callback to update inbound_id if found in different inbound
                    def update_inbound_callback(service_id, new_inbound_id):
                        try:
                            self.db.update_service_inbound_id(service_id, new_inbound_id)
                            logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                        except Exception as e:
                            logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
                    
                    # Get client details directly from panel
                    # Check if panel manager supports optional parameters (Marzban does, PanelManager doesn't)
                    import inspect
                    sig = inspect.signature(panel_manager.get_client_details)
                    params = list(sig.parameters.keys())
                    
                    if 'update_inbound_callback' in params and 'service_id' in params:
                        # MarzbanPanelManager - supports callback
                        client = panel_manager.get_client_details(
                            service['inbound_id'], 
                            service['client_uuid'],
                            update_inbound_callback=update_inbound_callback,
                            service_id=service['id'],
                            client_name=service.get('client_name')
                        )
                    else:
                        # PanelManager - only accepts inbound_id and client_uuid
                        client = panel_manager.get_client_details(
                            service['inbound_id'], 
                            service['client_uuid'],
                            client_name=service['client_name']
                        )
                    
                    if client:
                        logger.info(f"Admin: Found client: {client.get('email', 'Unknown')}")
                        
                        # Get client details
                        client_email = client.get('email', service.get('client_name', 'Unknown'))
                        is_enabled = client.get('enable', False)
                        status = "✅ فعال" if is_enabled else "❌ غیرفعال"
                        
                        # Calculate traffic usage with high precision
                        total_traffic_bytes = client.get('total_traffic', 0)
                        used_traffic_bytes = client.get('used_traffic', 0)
                        
                        logger.info(f"Admin Traffic - Total: {total_traffic_bytes}, Used: {used_traffic_bytes}")
                        
                        if total_traffic_bytes > 0:
                            remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
                            remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
                            used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 2)
                            total_gb = round(total_traffic_bytes / (1024 * 1024 * 1024), 2)
                        else:
                            remaining_gb = "نامحدود"
                            used_gb = 0
                            total_gb = "نامحدود"
                        
                        # Get expire time
                        expire_time = client.get('expiryTime', 0)
                        if expire_time > 0:
                            current_time = int(time.time() * 1000)
                            remaining_ms = expire_time - current_time
                            if remaining_ms > 0:
                                days = remaining_ms // (1000 * 60 * 60 * 24)
                                hours = (remaining_ms % (1000 * 60 * 60 * 24)) // (1000 * 60 * 60)
                                expire_days = f"{days} روز و {hours} ساعت"
                            else:
                                expire_days = "منقضی شده"
                        
                        # Check connection status
                        connection_status = await self.check_client_connection_status(panel_manager, service['inbound_id'], service['client_uuid'], client_name=service.get('client_name'))
                        
                    else:
                        logger.warning(f"Admin: Client {service['client_uuid']} not found in panel")
                        status = "❌ کلاینت در پنل یافت نشد"
                        connection_status = "❌ کلاینت در پنل یافت نشد"
                else:
                    logger.error("Admin: Failed to connect to panel")
                    status = "❌ خطا در اتصال به پنل"
                    connection_status = "❌ خطا در اتصال به پنل"
                    
            except Exception as e:
                logger.error(f"Admin: Error getting client details: {e}")
                status = "❌ خطا در اتصال به پنل"
                connection_status = "❌ خطا در اتصال به پنل"
            
            # Escape special characters for Markdown
            safe_client_email = str(client_email).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_panel_name = str(service.get('panel_name', 'نامشخص')).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_status = str(status).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_connection_status = str(connection_status).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_expire_days = str(expire_days).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_remaining_gb = str(remaining_gb).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_total_gb = str(total_gb).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            
            # Calculate usage percentage for display
            usage_info = ""
            if isinstance(remaining_gb, (int, float)) and isinstance(total_gb, (int, float)):
                usage_percentage = ((total_gb - remaining_gb) / total_gb * 100) if total_gb > 0 else 0
                usage_bar = "🟩" * int(usage_percentage / 10) + "⬜" * (10 - int(usage_percentage / 10))
                usage_info = f"\n📈 **میزان مصرف:** {used_gb} گیگ ({usage_percentage:.1f}%)\n{usage_bar}"
            
            # Format creation date
            creation_date = ""
            try:
                if service.get('created_at'):
                    from datetime import datetime
                    created_dt = datetime.strptime(service['created_at'], '%Y-%m-%d %H:%M:%S')
                    creation_date = f"\n📅 **تاریخ فعالسازی:** {created_dt.strftime('%Y/%m/%d - %H:%M')}"
            except:
                pass
            
            # User info
            user_name = UsernameFormatter.format_display_name(
                None,
                service.get('user_first_name'),
                service.get('user_last_name')
            )
            
            message = f"""
🔧 **مدیریت سرویس (ادمین)**

👤 **کاربر:** {user_name} (`{service.get('user_telegram_id')}`)

🆔 **شناسه کاربری**
   • {safe_client_email}

📊 **وضعیت سرویس**
   • وضعیت: {safe_status}
   • اتصال: {safe_connection_status}
   • سرور: {safe_panel_name}

⏰ **مدت اعتبار**
   • {safe_expire_days}

📦 **اطلاعات ترافیک**
   • باقیمانده: {safe_remaining_gb} گیگابایت
   • کل حجم: {safe_total_gb} گیگابایت{usage_info}{creation_date}
            """
            
            # Use same management buttons as user with admin context
            reply_markup = ButtonLayout.create_service_management(
                service, 
                is_admin=True, 
                admin_user_id=service.get('user_telegram_id')
            )
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error managing service (admin): {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در مدیریت سرویس.")
    
    async def handle_get_test_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle test account request - uses configured panel and inbound, or falls back to first available panel"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            user_id = update.effective_user.id
            
            # Get test account configuration
            test_config = self.db.get_test_account_config()
            panel_id = test_config.get('panel_id')
            inbound_id = test_config.get('inbound_id')
            
            # If no panel configured, fall back to old behavior (first available panel)
            if not panel_id:
                # Get all panels
                panels = self.db.get_panels(active_only=True)
                
                if not panels:
                    error_text = "❌ هیچ پنلی برای خرید سرویس موجود نیست."
                    back_markup = ButtonLayout.create_back_button("main_menu")
                    if query:
                        await query.edit_message_text(error_text, reply_markup=back_markup)
                    else:
                        await update.message.reply_text(error_text, reply_markup=back_markup)
                    return
                
                # Get the first available panel with gigabyte sale type
                panel = None
                for p in panels:
                    sale_type = p.get('sale_type', 'gigabyte')
                    if sale_type in ['gigabyte', 'both']:
                        panel = p
                        break
                
                if not panel:
                    error_text = (
                        "❌ هیچ پنلی با امکان خرید گیگابایتی موجود نیست.\n\n"
                        "💡 لطفاً از بخش مدیریت محصولات، تنظیمات اکانت تست را انجام دهید."
                    )
                    back_markup = ButtonLayout.create_back_button("main_menu")
                    if query:
                        await query.edit_message_text(error_text, reply_markup=back_markup)
                    else:
                        await update.message.reply_text(error_text, reply_markup=back_markup)
                    return
                
                panel_id = panel['id']
                inbound_id = None  # Use default inbound
            
            # Verify panel exists and is active
            panel = self.db.get_panel(panel_id)
            if not panel or not panel.get('is_active'):
                error_text = (
                    "❌ پنل تنظیم شده برای اکانت تست یافت نشد یا غیرفعال است.\n\n"
                    "💡 لطفاً از بخش مدیریت محصولات، تنظیمات اکانت تست را به‌روزرسانی کنید."
                )
                back_markup = ButtonLayout.create_back_button("main_menu")
                if query:
                    await query.edit_message_text(error_text, reply_markup=back_markup)
                else:
                    await update.message.reply_text(error_text, reply_markup=back_markup)
                return
            
            # Verify panel supports gigabyte sales
            sale_type = panel.get('sale_type', 'gigabyte')
            if sale_type not in ['gigabyte', 'both']:
                error_text = (
                    "❌ پنل تنظیم شده از نوع خرید گیگابایتی پشتیبانی نمی‌کند.\n\n"
                    "💡 لطفاً از بخش مدیریت محصولات، تنظیمات اکانت تست را به‌روزرسانی کنید."
                )
                back_markup = ButtonLayout.create_back_button("main_menu")
                if query:
                    await query.edit_message_text(error_text, reply_markup=back_markup)
                else:
                    await update.message.reply_text(error_text, reply_markup=back_markup)
                return
            
            # Set volume to 1 GB
            volume_gb = 1
            
            # Calculate price
            price_per_gb = panel.get('price_per_gb', 1000) or 1000
            price = volume_gb * price_per_gb
            
            # Store inbound_id in context if configured (for use in purchase flow)
            if inbound_id:
                context.user_data['test_account_inbound_id'] = inbound_id
                context.user_data['test_account_panel_id'] = panel_id
            
            # Go directly to payment options
            await self.handle_volume_purchase_options(update, context, panel_id, volume_gb, price)
            
        except Exception as e:
            logger.error(f"Error handling get test account: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            error_text = "❌ خطا در دریافت اکانت تست."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
    
    @auto_update_user_info
    async def handle_buy_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle buy service menu"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            # Get all active panels only
            panels = self.db.get_panels(active_only=True)
            
            if not panels:
                error_text = "❌ هیچ پنلی برای خرید سرویس موجود نیست."
                back_markup = ButtonLayout.create_back_button("user_panel")
                
                if query:
                    await query.edit_message_text(error_text, reply_markup=back_markup)
                else:
                    await update.message.reply_text(error_text, reply_markup=back_markup)
                return
            
            # If there's exactly one active panel, automatically select it
            if len(panels) == 1:
                panel_id = panels[0]['id']
                # Automatically proceed to panel selection handler
                await self.handle_select_panel(update, context, panel_id)
                return
            
            # Multiple panels - show selection menu
            # Create panel buttons
            keyboard = []
            for panel in panels:
                price_per_gb = panel.get('price_per_gb', 0)
                if isinstance(price_per_gb, (int, float)):
                    price_text = f"{int(price_per_gb):,} ت/GB"
                else:
                    price_text = f"{price_per_gb} ت/GB"
                
                button_text = f"🌐 {panel['name']} • {price_text}"
                callback_data = f"select_panel_{panel['id']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("◀️ بازگشت به منو", callback_data="main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = """
🛒 خرید سرویس VPN جدید

مزایای سرویس ما:
• سرعت بالا و پایدار
• پشتیبانی ۲۴ ساعته
• بدون محدودیت دستگاه
• قیمت مناسب و منصفانه

🌐 لطفاً سرور مورد نظر خود را انتخاب کنید:
            """
            
            if query:
                await query.edit_message_text(message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling buy service: {e}")
            error_text = "❌ خطا در نمایش پنل‌های خرید سرویس."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
    
    async def handle_select_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle panel selection for service purchase"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            # Get panel details
            panel = self.db.get_panel(panel_id)
            if not panel:
                error_text = "❌ پنل یافت نشد."
                if query:
                    try:
                        await query.edit_message_text(error_text)
                    except BadRequest as e:
                        if "not modified" not in str(e).lower():
                            raise
                else:
                    await update.message.reply_text(error_text)
                return
            
            # Store panel ID in user data
            context.user_data['selected_panel_id'] = panel_id
            
            # Get sale type
            sale_type = panel.get('sale_type', 'gigabyte')
            
            # If sale type is 'both', ask user to choose
            if sale_type == 'both':
                message = f"""
🛒 **انتخاب نوع خرید**

پنل: **{panel['name']}**

لطفاً نوع خرید مورد نظر را انتخاب کنید:
                """
                
                # Check if there's only one active panel - if so, go back to main menu
                active_panels = self.db.get_panels(active_only=True)
                back_callback = "user_panel" if len(active_panels) == 1 else "buy_service"
                
                keyboard = [
                    [InlineKeyboardButton("📊 خرید گیگابایتی", callback_data=f"buy_gigabyte_{panel_id}")],
                    [InlineKeyboardButton("📦 خرید پلنی", callback_data=f"buy_plan_{panel_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if query:
                    try:
                        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                    except BadRequest as e:
                        if "not modified" not in str(e).lower():
                            raise
                else:
                    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                return
            
            # If sale type is 'gigabyte', show volume selection
            if sale_type == 'gigabyte':
                price_per_gb = panel.get('price_per_gb', 1000) or 1000
                
                message = f"""
🌐 انتخاب حجم سرویس

📍 سرور: {panel['name']}
💎 نرخ: {price_per_gb:,} تومان / گیگابایت

⬇️ حجم مورد نظر خود را انتخاب کنید:
                """
                
                reply_markup = ButtonLayout.create_volume_suggestions(panel_id, price_per_gb)
                
                if query:
                    try:
                        await query.edit_message_text(message, reply_markup=reply_markup)
                    except BadRequest as e:
                        if "not modified" not in str(e).lower():
                            raise
                else:
                    await update.message.reply_text(message, reply_markup=reply_markup)
                return
            
            # If sale type is 'plan', show products
            if sale_type == 'plan':
                await self.handle_show_products_for_purchase(update, context, panel_id)
                return
            
            # Default to gigabyte for backward compatibility
            price_per_gb = panel.get('price_per_gb', 1000) or 1000
            
            message = f"""
🌐 انتخاب حجم سرویس

📍 سرور: {panel['name']}
💎 نرخ: {price_per_gb:,} تومان / گیگابایت

⬇️ حجم مورد نظر خود را انتخاب کنید:
            """
            
            reply_markup = ButtonLayout.create_volume_suggestions(panel_id, price_per_gb)
            
            if query:
                try:
                    await query.edit_message_text(message, reply_markup=reply_markup)
                except BadRequest as e:
                    if "not modified" not in str(e).lower():
                        raise
            else:
                await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling select panel: {e}")
            error_text = "❌ خطا در انتخاب پنل."
            if query:
                try:
                    await query.edit_message_text(error_text)
                except BadRequest:
                    pass
            else:
                await update.message.reply_text(error_text)
    
    async def handle_buy_gigabyte(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle gigabyte purchase selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            price_per_gb = panel.get('price_per_gb', 1000) or 1000
            
            message = f"""
🌐 انتخاب حجم سرویس

📍 سرور: {panel['name']}
💎 نرخ: {price_per_gb:,} تومان / گیگابایت

⬇️ حجم مورد نظر خود را انتخاب کنید:
            """
            
            reply_markup = ButtonLayout.create_volume_suggestions(panel_id, price_per_gb)
            
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling buy gigabyte: {e}")
            await query.edit_message_text("❌ خطا در نمایش خرید گیگابایتی.")
    
    async def handle_buy_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle plan purchase selection"""
        query = update.callback_query
        await query.answer()
        
        await self.handle_show_products_for_purchase(update, context, panel_id)
    
    async def handle_show_products_for_purchase(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show products for purchase - categories or direct products"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                error_text = "❌ پنل یافت نشد."
                if query:
                    try:
                        await query.edit_message_text(error_text)
                    except BadRequest:
                        pass
                else:
                    await update.message.reply_text(error_text)
                return
            
            # Check if panel has products without category
            has_products_without_category = self.db.has_products_without_category(panel_id)
            categories = self.db.get_categories(panel_id, active_only=True)
            
            # If no categories and has products without category, show them directly
            if not categories and has_products_without_category:
                await self.handle_show_products_for_purchase_no_category(update, context, panel_id)
                return
            
            # If no categories and no products, show error
            if not categories and not has_products_without_category:
                # Check if there's only one active panel - if so, go back to main menu
                active_panels = self.db.get_panels(active_only=True)
                back_callback = "user_panel" if len(active_panels) == 1 else "buy_service"
                
                error_msg = "❌ هیچ محصولی برای این پنل تعریف نشده است.\n\nلطفاً با ادمین تماس بگیرید."
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)]
                ])
                if query:
                    try:
                        await query.edit_message_text(error_msg, reply_markup=reply_markup)
                    except BadRequest:
                        pass
                else:
                    await update.message.reply_text(error_msg, reply_markup=reply_markup)
                return
            
            # Show categories for selection
            message = f"📦 **انتخاب دسته‌بندی - پنل {panel['name']}:**\n\n"
            
            keyboard = []
            for cat in categories:
                keyboard.append([InlineKeyboardButton(
                    f"📁 {cat['name']}",
                    callback_data=f"buy_category_products_{cat['id']}"
                )])
            
            # If has products without category, add a button for them
            if has_products_without_category:
                keyboard.append([InlineKeyboardButton(
                    "📦 محصولات بدون دسته‌بندی",
                    callback_data=f"buy_products_no_category_{panel_id}"
                )])
            
            # Check if there's only one active panel - if so, go back to main menu
            active_panels = self.db.get_panels(active_only=True)
            back_callback = "user_panel" if len(active_panels) == 1 else "buy_service"
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                try:
                    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                except BadRequest:
                    pass
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing products for purchase: {e}")
            error_text = "❌ خطا در نمایش محصولات."
            if query:
                try:
                    await query.edit_message_text(error_text)
                except BadRequest:
                    pass
            else:
                await update.message.reply_text(error_text)
    
    async def handle_show_products_for_purchase_no_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Show products without category for purchase"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                error_text = "❌ پنل یافت نشد."
                if query:
                    try:
                        await query.edit_message_text(error_text)
                    except BadRequest:
                        pass
                else:
                    await update.message.reply_text(error_text)
                return
            
            products = self.db.get_products(panel_id, category_id=False, active_only=True)
            
            if not products:
                # Check if there's only one active panel - if so, go back to main menu
                active_panels = self.db.get_panels(active_only=True)
                back_callback = "user_panel" if len(active_panels) == 1 else "buy_service"
                
                error_msg = "❌ هیچ محصول فعالی وجود ندارد."
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)]
                ])
                if query:
                    try:
                        await query.edit_message_text(error_msg, reply_markup=reply_markup)
                    except BadRequest:
                        pass
                else:
                    await update.message.reply_text(error_msg, reply_markup=reply_markup)
                return
            
            message = f"📦 **محصولات - پنل {panel['name']}:**\n\n"
            
            keyboard = []
            for prod in products:
                # Create three buttons side by side: name, price, days
                keyboard.append([
                    InlineKeyboardButton(
                        prod['name'],
                        callback_data=f"buy_product_{prod['id']}"
                    ),
                    InlineKeyboardButton(
                        f"💰 {prod['price']:,}",
                        callback_data=f"buy_product_{prod['id']}"
                    ),
                    InlineKeyboardButton(
                        f"⏱️ {prod['duration_days']} روز",
                        callback_data=f"buy_product_{prod['id']}"
                    )
                ])
            
            # Check if there's only one active panel - if so, go back to main menu
            active_panels = self.db.get_panels(active_only=True)
            back_callback = "user_panel" if len(active_panels) == 1 else "buy_service"
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                try:
                    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                except BadRequest:
                    pass
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing products without category: {e}")
            error_text = "❌ خطا در نمایش محصولات."
            if query:
                try:
                    await query.edit_message_text(error_text)
                except BadRequest:
                    pass
            else:
                await update.message.reply_text(error_text)
    
    async def handle_buy_category_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Show products in a category for purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            panel = self.db.get_panel(category['panel_id'])
            panel_name = panel['name'] if panel else 'نامشخص'
            
            products = self.db.get_products(category['panel_id'], category_id=category_id, active_only=True)
            
            if not products:
                await query.edit_message_text(
                    f"❌ هیچ محصول فعالی در دسته‌بندی '{category['name']}' وجود ندارد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"buy_plan_{category['panel_id']}")]
                    ])
                )
                return
            
            message = f"📦 **محصولات دسته‌بندی '{category['name']}' - پنل {panel_name}:**\n\n"
            
            keyboard = []
            for prod in products:
                # Create three buttons side by side: name, price, days
                keyboard.append([
                    InlineKeyboardButton(
                        prod['name'],
                        callback_data=f"buy_product_{prod['id']}"
                    ),
                    InlineKeyboardButton(
                        f"💰 {prod['price']:,}",
                        callback_data=f"buy_product_{prod['id']}"
                    ),
                    InlineKeyboardButton(
                        f"⏱️ {prod['duration_days']} روز",
                        callback_data=f"buy_product_{prod['id']}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"buy_plan_{category['panel_id']}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing category products for purchase: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_buy_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Handle product purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product or not product.get('is_active'):
                await query.edit_message_text("❌ محصول یافت نشد یا غیرفعال است.")
                return
            
            panel = self.db.get_panel(product['panel_id'])
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            total_price = product['price']
            
            # Store purchase info for discount code entry
            context.user_data['purchase_panel_id'] = product['panel_id']
            context.user_data['purchase_product_id'] = product_id
            context.user_data['purchase_total_amount'] = total_price
            context.user_data['purchase_type'] = 'plan'  # Mark as plan purchase
            
            # Show product details and discount code entry screen
            message = f"""
💳 **فاکتور خرید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📦 **محصول:** {escape_markdown(product['name'], version=1)}
📊 **حجم:** {product['volume_gb']} گیگابایت
⏱️ **مدت زمان:** {product['duration_days']} روز
💵 **مبلغ کل:** {total_price:,} تومان

🎁 اگر کد تخفیف دارید، از دکمه زیر استفاده کنید:
            """
            
            keyboard = [
                [InlineKeyboardButton("🏷️ وارد کردن کد تخفیف", callback_data=f"enter_discount_code_product_{product_id}")],
                [InlineKeyboardButton("⏭️ ادامه بدون کد تخفیف", callback_data=f"continue_without_discount_product_{product_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="buy_service")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling buy product: {e}")
            await query.edit_message_text("❌ خطا در پردازش خرید محصول.")
    
    async def handle_user_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user panel menu"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            # Get user data
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                error_text = "❌ کاربر یافت نشد."
                if query:
                    await query.edit_message_text(error_text)
                else:
                    await update.message.reply_text(error_text)
                return
            
            # Get user's services
            services = self.db.get_user_services(user['id'])
            
            # Format services for display
            formatted_services = []
            for service in services:
                formatted_services.append({
                    'id': service['id'],
                    'client_name': UsernameFormatter.format_display_name(
                        service.get('client_name', ''),
                        service.get('first_name', ''),
                        service.get('last_name', '')
                    ),
                    'total_gb': service.get('total_gb', 0),
                    'status': service.get('status', 'unknown'),
                    'panel_name': service.get('panel_name', 'نامشخص')
                })
            
            # Create professional dashboard message
            message = f"""
📊 داشبورد کاربری

👤 اطلاعات کاربر:
• نام: {UsernameFormatter.format_display_name(None, user.get('first_name'), user.get('last_name'))}
• موجودی: {UsernameFormatter.format_balance(user.get('balance', 0))}
• تعداد سرویس‌ها: {len(services)}

🎯 برای شروع، یکی از گزینه‌های زیر را انتخاب کنید:
            """
            
            # Create professional dashboard buttons
            reply_markup = ButtonLayout.create_user_dashboard(
                services=formatted_services,
                user_balance=user.get('balance', 0)
            )
            
            if query:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error handling user panel: {e}")
            # Ensure database name is set in thread-local storage
            MessageTemplates.set_database_name(self.db.database_name)
            error_msg = MessageTemplates.format_error_message('general_error', 
                    error_message=str(e), error_code='USER_PANEL_ERROR')
            
            if query:
                await query.edit_message_text(error_msg)
            else:
                await update.message.reply_text(error_msg)
    
    async def handle_all_services(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle showing all services in detail"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get user data
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get user's services
            services = self.db.get_user_services(user['id'])
            
            if not services or len(services) == 0:
                message = """
📋 لیست سرویس‌ها

❌ هنوز هیچ سرویسی ندارید

💡 برای شروع:
از منوی زیر اولین سرویس خود را خریداری کنید.
                """
                keyboard = [
                    [InlineKeyboardButton("🛒 خرید سرویس جدید", callback_data="buy_service")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="user_panel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return
            
            # Get page number from callback data (default to page 1)
            page = 1
            if query.data.startswith('all_services_page_'):
                try:
                    page = int(query.data.split('_')[-1])
                except:
                    page = 1
            
            # Pagination settings
            items_per_page = 10
            total_pages = (len(services) + items_per_page - 1) // items_per_page  # Ceiling division
            
            # Ensure page is within valid range
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages
            
            # Get services for current page
            start_idx = (page - 1) * items_per_page
            end_idx = start_idx + items_per_page
            page_services = services[start_idx:end_idx]
            
            # Create simple message without service details
            message = f"""
📋 لیست کامل سرویس‌ها

📊 تعداد کل: {len(services)} سرویس
💰 موجودی شما: {user.get('balance', 0):,} تومان

💡 برای مدیریت هر سرویس، روی دکمه آن کلیک کنید.
            """
            
            # Create buttons - show only current page services
            keyboard = []
            for service in page_services:
                service_name = service.get('client_name', 'نامشخص')
                # Shorten name to max 10 chars
                if len(service_name) > 10:
                    service_name = service_name[:10]
                
                status_icon = "🟢" if service.get('is_active', 0) == 1 else "🔴"
                gb = service.get('total_gb', 0)
                keyboard.append([InlineKeyboardButton(
                    f"{status_icon} {service_name} • {gb}G",
                    callback_data=f"manage_service_{service['id']}"
                )])
            
            # Pagination buttons
            if total_pages > 1:
                nav_buttons = []
                if page > 1:
                    nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"all_services_page_{page - 1}"))
                
                # Page indicator
                nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
                
                if page < total_pages:
                    nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"all_services_page_{page + 1}"))
                
                keyboard.append(nav_buttons)
            
            # Navigation buttons
            keyboard.extend([
                [InlineKeyboardButton("🛒 خرید جدید", callback_data="buy_service")],
                [InlineKeyboardButton("🔙 پنل کاربری", callback_data="user_panel")]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling all services: {e}")
            # Ensure database name is set in thread-local storage
            MessageTemplates.set_database_name(self.db.database_name)
            await query.edit_message_text(
                MessageTemplates.format_error_message('general_error', 
                    error_message=str(e), error_code='ALL_SERVICES_ERROR')
            )
    
    @auto_update_user_info
    async def handle_referral_system(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle referral system - show referral link and stats"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            from config import REFERRAL_CONFIG, BOT_CONFIG
            
            # Check if referral system is enabled
            if not REFERRAL_CONFIG.get('enabled', True):
                error_text = "❌ سیستم رفرال در حال حاضر غیرفعال است."
                if query:
                    await query.edit_message_text(error_text)
                else:
                    await update.message.reply_text(error_text)
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                error_text = "❌ کاربر یافت نشد."
                if query:
                    await query.edit_message_text(error_text)
                else:
                    await update.message.reply_text(error_text)
                return
            
            # Get user's referral stats
            referrals = self.db.get_user_referrals(user['id'])
            total_referrals = len(referrals)
            total_earnings = user.get('total_referral_earnings', 0)
            referral_code = user.get('referral_code', '')
            
            # If user doesn't have a referral code, generate one
            if not referral_code:
                referral_code = self.db.generate_referral_code()
                # Update user with new referral code
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE users SET referral_code = %s WHERE id = %s', (referral_code, user['id']))
                    conn.commit()
                logger.info(f"Generated referral code for user {user_id}: {referral_code}")
            
            # Create referral link
            bot_username = self.bot_config.get('bot_username', 'YourBot')
            if not bot_username or bot_username == 'YourBot':
                # Try to get bot username from bot info
                try:
                    bot_info = await context.bot.get_me()
                    bot_username = bot_info.username
                except:
                    bot_username = 'YourBot'
            
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            
            # Format referral stats
            referrals_list = []
            if referrals and len(referrals) > 0:
                for idx, ref in enumerate(referrals[:10], 1):  # Show last 10
                    ref_name = ref.get('first_name', 'کاربر')
                    ref_username = ref.get('username', '')
                    username_display = f"@{ref_username}" if ref_username else "بدون نام کاربری"
                    reward = ref.get('reward_amount', 0)
                    # Ensure reward is an integer - handle all possible types
                    if reward is None:
                        reward = 0
                    elif isinstance(reward, str):
                        # If it's a string, try to convert to int
                        try:
                            reward = int(float(reward))
                        except (ValueError, TypeError):
                            reward = 0
                    elif not isinstance(reward, (int, float)):
                        try:
                            reward = int(reward)
                        except (ValueError, TypeError):
                            reward = 0
                    else:
                        reward = int(reward)
                    
                    # Format reward with comma separator - use str.format() to avoid f-string issues
                    reward_formatted = '{:,}'.format(reward)
                    # Build string without f-string to avoid format specifier conflicts
                    referral_item = f"{idx}. {ref_name} ({username_display}) - {reward_formatted} تومان"
                    referrals_list.append(referral_item)
            
            referrals_text = "\n".join(referrals_list) if referrals_list else "هنوز کسی از لینک شما ثبت نام نکرده است."
            
            # Format numbers separately to avoid format string issues - use str.format()
            # Ensure values are integers
            try:
                reward_amount = int(REFERRAL_CONFIG.get('reward_amount', 3000))
            except (ValueError, TypeError):
                reward_amount = 3000
            
            try:
                total_earnings = int(total_earnings) if total_earnings else 0
            except (ValueError, TypeError):
                total_earnings = 0
            
            reward_amount_formatted = '{:,}'.format(reward_amount)
            total_earnings_formatted = '{:,}'.format(total_earnings)
            
            # Create message - build parts separately to avoid format specifier conflicts
            message_parts = [
                "🎁 **سیستم معرفی به دوستان**",
                "",
                f"💰 **پاداش معرفی:** {reward_amount_formatted} تومان",
                "",
                "📊 **آمار شما:**",
                f"   • تعداد معرفی‌ها: {total_referrals} نفر",
                f"   • مجموع درآمد: {total_earnings_formatted} تومان",
                "",
                "🔗 **لینک اختصاصی شما:**",
                f"`{referral_link}`",
                "",
                "💡 **راهنما:**",
                "• لینک بالا را با دوستان خود به اشتراک بگذارید",
                f"• هر نفر که از طریق لینک شما ثبت نام کند، {reward_amount_formatted} تومان به شما تعلق می‌گیرد",
                "• پاداش به صورت خودکار به حساب شما واریز می‌شود"
            ]
            message = "\n".join(message_parts)
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="user_panel")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error handling referral system: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            error_text = "❌ خطا در نمایش سیستم رفرال."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
    
    @auto_update_user_info
    async def handle_manage_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle service management"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message has text (if it's a photo/media, we need to send new message)
            is_media_message = query.message.photo or query.message.video or query.message.document
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                # Ensure database name is set in thread-local storage
                MessageTemplates.set_database_name(self.db.database_name)
                await query.edit_message_text(
                    MessageTemplates.format_error_message('user_not_found', user_id=user_id)
                )
                return
            
            # Get service from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT c.*, p.name as panel_name, p.url as panel_url, p.subscription_url, p.panel_type
                FROM clients c 
                JOIN panels p ON c.panel_id = p.id 
                    WHERE c.id = %s AND c.user_id = %s
            ''', (service_id, user['id']))
            
            service_row = cursor.fetchone()
                # Connection closed automatically
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Map service_row columns properly
            # Columns: id, user_id, panel_id, client_name, client_uuid, inbound_id, 
            #          protocol, expire_days, total_gb, used_gb, is_active, 
            #          created_at, updated_at, expires_at, last_used, config_link, notes, 
            #          panel_name, panel_url, subscription_url, panel_type
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'client_name': service_row['client_name'],
                'client_uuid': service_row['client_uuid'],
                'inbound_id': service_row['inbound_id'],
                'protocol': service_row['protocol'],
                'total_gb': service_row['total_gb'],
                'used_gb': service_row.get('used_gb') or 0,
                'is_active': service_row.get('is_active', 0) or 0,
                'status': service_row.get('status', 'unknown') or 'unknown',
                'created_at': service_row['created_at'],
                'panel_name': service_row['panel_name'],
                'panel_url': service_row['panel_url'],
                'subscription_url': service_row.get('subscription_url'),
                'panel_type': service_row.get('panel_type', '3x-ui'),
                'sub_id': service_row.get('sub_id')
            }
            
            # If panel_name is None or empty, get it from panel details
            if not service['panel_name']:
                panel = self.db.get_panel(service['panel_id'])
                if panel:
                    service['panel_name'] = panel.get('name', 'نامشخص')
                else:
                    service['panel_name'] = 'نامشخص'
            
            # Get detailed client info from panel
            remaining_gb = service['total_gb']
            used_gb = 0
            status = "❌ نامشخص"
            connection_status = "❌ نامشخص"
            expire_days = "نامحدود"
            client_email = service['client_name']
            # Ensure total_gb is initialized for later display even if panel calls fail
            total_gb = service['total_gb']
            
            # Check database status as fallback
            db_is_active = service.get('is_active', 0) or 0
            db_status = service.get('status', 'unknown') or 'unknown'
            
            # Convert to int/str to handle None values
            if db_is_active is None:
                db_is_active = 0
            else:
                db_is_active = int(db_is_active)
            
            if db_status is None:
                db_status = 'unknown'
            else:
                db_status = str(db_status)
            
            # Determine status from database if panel check fails
            if db_is_active == 1 and db_status == 'active':
                status = "✅ فعال"
            elif db_status == 'exhausted':
                status = "❌ تمام شده"
            elif db_status == 'expired':
                status = "❌ منقضی شده"
            else:
                status = "❌ غیرفعال"
            
            try:
                panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
                if panel_manager and panel_manager.login():
                    logger.info(f"Getting client details for service {service['id']}")
                    
                    # Create callback to update inbound_id if found in different inbound
                    def update_inbound_callback(service_id, new_inbound_id):
                        try:
                            self.db.update_service_inbound_id(service_id, new_inbound_id)
                            logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                        except Exception as e:
                            logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
                    
                    # Get client details directly from panel
                    # Check if panel manager supports optional parameters (Marzban does, PanelManager doesn't)
                    import inspect
                    sig = inspect.signature(panel_manager.get_client_details)
                    params = list(sig.parameters.keys())
                    
                    if 'update_inbound_callback' in params and 'service_id' in params:
                        # MarzbanPanelManager - supports callback
                        client = panel_manager.get_client_details(
                            service['inbound_id'], 
                            service['client_uuid'],
                            update_inbound_callback=update_inbound_callback,
                            service_id=service['id'],
                            client_name=service['client_name']
                        )
                    else:
                        # PanelManager - only accepts inbound_id and client_uuid
                        client = panel_manager.get_client_details(
                            service['inbound_id'], 
                            service['client_uuid'],
                            client_name=service['client_name']
                        )
                    
                    if client:
                        logger.info(f"Found client: {client.get('email', 'Unknown')}")
                        
                        # Get client details
                        raw_email = client.get('email', service['client_name'])
                        # Clean up Marzban email format (username@marzban -> username)
                        if '@marzban' in str(raw_email).lower():
                            client_email = raw_email.split('@')[0]
                        else:
                            client_email = raw_email
                        
                        is_enabled = client.get('enable', False)
                        # Prioritize database status if service is active in database
                        # (panel status might be stale after renewal/volume addition)
                        if db_is_active == 1 and db_status == 'active':
                            status = "✅ فعال"
                        else:
                            status = "✅ فعال" if is_enabled else "❌ غیرفعال"
                        
                        # Calculate traffic usage with high precision
                        total_traffic_bytes = client.get('total_traffic', 0)
                        used_traffic_bytes = client.get('used_traffic', 0)
                        
                        logger.info(f"Traffic - Total: {total_traffic_bytes}, Used: {used_traffic_bytes}")
                        
                        if total_traffic_bytes > 0:
                            remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
                            remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
                            used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 2)
                            total_gb = round(total_traffic_bytes / (1024 * 1024 * 1024), 2)
                        else:
                            remaining_gb = "نامحدود"
                            used_gb = 0
                            total_gb = "نامحدود"
                        
                        # Get expire time
                        expire_time = client.get('expiryTime', 0)
                        if expire_time > 0:
                            current_time = int(time.time() * 1000)
                            remaining_ms = expire_time - current_time
                            if remaining_ms > 0:
                                days = remaining_ms // (1000 * 60 * 60 * 24)
                                hours = (remaining_ms % (1000 * 60 * 60 * 24)) // (1000 * 60 * 60)
                                expire_days = f"{days} روز و {hours} ساعت"
                            else:
                                expire_days = "منقضی شده"
                        
                        # Check connection status by getting real-time stats from panel
                        connection_status = await self.check_client_connection_status(panel_manager, service['inbound_id'], service['client_uuid'], client_name=service['client_name'])
                        
                    else:
                        logger.warning(f"Client {service['client_uuid']} not found in panel")
                        # Use database status if panel client not found
                        if db_is_active == 1 and db_status == 'active':
                            status = "✅ فعال"
                        else:
                            status = "❌ کلاینت در پنل یافت نشد"
                        connection_status = "❌ کلاینت در پنل یافت نشد"
                else:
                    logger.error("Failed to connect to panel")
                    # Use database status if panel connection fails
                    if db_is_active == 1 and db_status == 'active':
                        status = "✅ فعال"
                    else:
                        status = "❌ خطا در اتصال به پنل"
                    connection_status = "❌ خطا در اتصال به پنل"
                    
            except Exception as e:
                logger.error(f"Error getting client details: {e}")
                # Use database status if panel connection fails
                if db_is_active == 1 and db_status == 'active':
                    status = "✅ فعال"
                else:
                    status = "❌ خطا در اتصال به پنل"
                connection_status = "❌ خطا در اتصال به پنل"
            
            # Escape special characters for Markdown
            safe_client_email = str(client_email).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_panel_name = str(service['panel_name']).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_status = str(status).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_connection_status = str(connection_status).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_expire_days = str(expire_days).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_remaining_gb = str(remaining_gb).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            safe_total_gb = str(total_gb).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            
            # Calculate usage percentage for display
            usage_info = ""
            if isinstance(remaining_gb, (int, float)) and isinstance(total_gb, (int, float)):
                usage_percentage = ((total_gb - remaining_gb) / total_gb * 100) if total_gb > 0 else 0
                usage_bar = "🟩" * int(usage_percentage / 10) + "⬜" * (10 - int(usage_percentage / 10))
                usage_info = f"\n📈 **میزان مصرف:** {used_gb} گیگ ({usage_percentage:.1f}%)\n{usage_bar}"
            
            # Format creation date if available
            creation_date = ""
            try:
                if service.get('created_at'):  # created_at field
                    from datetime import datetime
                    created_dt = datetime.strptime(service['created_at'], '%Y-%m-%d %H:%M:%S')
                    creation_date = f"\n📅 **تاریخ فعالسازی:** {created_dt.strftime('%Y/%m/%d - %H:%M')}"
            except:
                pass
            
            message = f"""
🎯 مشخصات سرویس VPN

🆔 شناسه کاربری
   • {safe_client_email}

📊 وضعیت سرویس
   • وضعیت: {safe_status}
   • اتصال: {safe_connection_status}
   • سرور: {safe_panel_name}

⏰ مدت اعتبار
   • {safe_expire_days}

📦 اطلاعات ترافیک
   • باقیمانده: {safe_remaining_gb} گیگابایت
   • کل حجم: {safe_total_gb} گیگابایت{usage_info}{creation_date}

💡 نکته: سرویس شما بلافاصله پس از خرید فعال شده است
            """
            
            # Use professional button layout for service management
            reply_markup = ButtonLayout.create_service_management(service, is_admin=False)
            
            # If previous message was media (like QR code), delete it and send new text message
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                # Edit existing text message
                try:
                    await query.edit_message_text(
                        message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    # Ignore "Message is not modified" error
                    if "Message is not modified" in str(e):
                        logger.debug("Message is not modified, skipping update")
                    else:
                        raise e
            
        except Exception as e:
            logger.error(f"Error managing service: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Try to handle error gracefully
            try:
                if query.message.photo or query.message.video or query.message.document:
                    await query.message.delete()
                    await query.message.reply_text("❌ خطا در مدیریت سرویس.")
                else:
                    await query.edit_message_text("❌ خطا در مدیریت سرویس.")
            except:
                # Last resort - send new message
                await query.message.reply_text("❌ خطا در مدیریت سرویس.")
    
    @auto_update_user_info
    async def handle_get_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle get config request"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message has text
            is_media_message = query.message.photo or query.message.video or query.message.document
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service from database
            with self.db.get_connection() as conn:
                # Enable column access by name
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.url as panel_url, p.subscription_url, p.panel_type
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.url as panel_url, p.subscription_url, p.panel_type
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
            
                service_row = cursor.fetchone()
                # Connection closed automatically
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'client_name': service_row['client_name'],
                'client_uuid': service_row['client_uuid'],
                'inbound_id': service_row['inbound_id'],
                'protocol': service_row['protocol'],
                'total_gb': service_row['total_gb'],
                'config_link': service_row.get('config_link'),
                'panel_name': service_row['panel_name'] or 'نامشخص',
                'panel_url': service_row['panel_url'],
                'sub_id': service_row.get('sub_id'),
                'subscription_url': service_row.get('subscription_url'),
                'panel_type': service_row.get('panel_type', '3x-ui')
            }
            
            # Get subscription link - always construct subscription link (not direct config)
            subscription_link = ""
            
            try:
                # Get panel to determine type
                panel = self.db.get_panel(service['panel_id'])
                if panel:
                    panel_type = panel.get('panel_type', '3x-ui')
                    
                    if panel_type in ['marzban', 'rebecca', 'pasargad']:
                        # For Marzban, Rebecca, and Pasargad, get subscription link from panel API
                        panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
                        if panel_manager and panel_manager.login():
                            # Get subscription URL from panel (Marzban/Rebecca/Pasargad returns subscription link)
                            subscription_link = panel_manager.get_client_config_link(
                                service['inbound_id'],
                                service['client_uuid'],
                                service['protocol']
                            )
                    else:
                        # For 3x-ui, ALWAYS construct subscription link from subscription_url + sub_id
                        # NEVER use get_client_config_link for 3x-ui (it returns direct config, not subscription)
                        sub_url = service.get('subscription_url') or panel.get('subscription_url', '')
                        if sub_url and service.get('sub_id'):
                            if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                                sub_url = sub_url.rstrip('/')
                                subscription_link = f"{sub_url}/{service.get('sub_id')}"
                            elif '/sub' in sub_url:
                                # If sub is in the middle of URL
                                subscription_link = f"{sub_url}/{service.get('sub_id')}"
                            else:
                                subscription_link = f"{sub_url}/sub/{service.get('sub_id')}"
                        
                        # If no subscription_url in service, try to get from panel
                        if not subscription_link and panel.get('subscription_url') and service.get('sub_id'):
                            sub_url = panel.get('subscription_url', '')
                            if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                                sub_url = sub_url.rstrip('/')
                                subscription_link = f"{sub_url}/{service.get('sub_id')}"
                            elif '/sub' in sub_url:
                                subscription_link = f"{sub_url}/{service.get('sub_id')}"
                            else:
                                subscription_link = f"{sub_url}/sub/{service.get('sub_id')}"
                    
                    # Save subscription link to database for future use
                    if subscription_link:
                        self.db.update_client_config(service['id'], subscription_link)
                
                # Fallback to saved config_link if construction failed (should be subscription link)
                if not subscription_link and service.get('config_link'):
                    # Check if config_link is actually a subscription link (contains /sub/ or ends with sub_id)
                    config_link = service.get('config_link', '')
                    if '/sub/' in config_link or '/sub' in config_link or (service.get('sub_id') and service.get('sub_id') in config_link):
                        subscription_link = config_link
                    else:
                        # If it's a direct config link (starts with vless://, vmess://, etc.), construct subscription link
                        if config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                            # This is a direct config link, not subscription - construct subscription link
                            if panel and panel.get('subscription_url') and service.get('sub_id'):
                                sub_url = panel.get('subscription_url', '')
                                if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                                    sub_url = sub_url.rstrip('/')
                                    subscription_link = f"{sub_url}/{service.get('sub_id')}"
                                elif '/sub' in sub_url:
                                    subscription_link = f"{sub_url}/{service.get('sub_id')}"
                                else:
                                    subscription_link = f"{sub_url}/sub/{service.get('sub_id')}"
                                if subscription_link:
                                    self.db.update_client_config(service['id'], subscription_link)
                    
            except Exception as e:
                logger.error(f"Error getting subscription link: {e}")
                # Fallback to saved config_link on error (only if it looks like subscription link)
                if not subscription_link and service.get('config_link'):
                    config_link = service.get('config_link', '')
                    # Only use if it's a subscription link, not a direct config
                    if '/sub/' in config_link or '/sub' in config_link or (service.get('sub_id') and service.get('sub_id') in config_link):
                        if not config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                            subscription_link = config_link
            
            if subscription_link:
                config = f"""
🔗 لینک سابسکریپشن سرویس VPN

🔐 مشخصات سرویس:
• نام: {escape_markdown(service['client_name'], version=1)}
• پروتکل: {service['protocol'].upper()}
• حجم: {service['total_gb']} گیگابایت
• سرور: {escape_markdown(service['panel_name'], version=1)}

📱 لینک سابسکریپشن:
```
{subscription_link}
```

نحوه استفاده:
1️⃣ لینک بالا را کپی کنید (لمس طولانی روی متن)
2️⃣ در برنامه VPN خود به عنوان Subscription اضافه کنید:
    • اندروید: v2rayNG یا SagerNet
    • iOS: Streisand یا Shadowrocket
    • ویندوز: v2rayN یا Nekoray
3️⃣ کانفیگ‌ها را به‌روزرسانی کنید (Update Subscription)
4️⃣ یکی از کانفیگ‌ها را انتخاب و اتصال را برقرار کنید!

💡 مزیت: با لینک سابسکریپشن، تمام کانفیگ‌های شما به صورت خودکار به‌روز می‌شوند
                    """
            else:
                config = f"""
📋 لینک سرویس VPN

🔐 مشخصات سرویس:
• نام: {escape_markdown(service['client_name'], version=1)}
• پروتکل: {service['protocol'].upper()}
• حجم: {service['total_gb']} گیگابایت
• سرور: {escape_markdown(service['panel_name'], version=1)}

⚠️ خطا در اتصال به پنل
متأسفانه در حال حاضر امکان دریافت لینک از پنل وجود ندارد.
لطفاً با پشتیبانی تماس بگیرید.
                """
            
            keyboard = [
                [InlineKeyboardButton("📱 دریافت QR Code", callback_data=f"get_qr_code_{service_id}")],
                [InlineKeyboardButton("◀️ بازگشت", callback_data=f"manage_service_{service_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Handle media message (from QR code back button)
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    config,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                try:
                    await query.edit_message_text(
                        config,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    # Ignore "Message is not modified" error
                    if "Message is not modified" in str(e):
                        logger.debug("Message is not modified, skipping update")
                    else:
                        raise e
            
            # Report subscription link retrieval to channel
            if subscription_link and self.reporting_system:
                try:
                    service_data = {
                        'service_name': service.get('client_name', 'سرویس'),
                        'total_gb': service.get('total_gb', 0),
                        'panel_name': service.get('panel_name', 'نامشخص'),
                        'protocol': service.get('protocol', 'vless')
                    }
                    await self.reporting_system.report_subscription_link_retrieved(user, service_data)
                except Exception as e:
                    logger.error(f"Failed to send subscription link retrieval report: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            try:
                if query.message.photo or query.message.video or query.message.document:
                    await query.message.delete()
                    await query.message.reply_text("❌ خطا در دریافت کانفیگ.")
                else:
                    await query.edit_message_text("❌ خطا در دریافت کانفیگ.")
            except:
                await query.message.reply_text("❌ خطا در دریافت کانفیگ.")
    
    @auto_update_user_info
    async def handle_get_qr_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle QR code generation request"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.url as panel_url
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.url as panel_url
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
            
            service_row = cursor.fetchone()
                # Connection closed automatically
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'client_name': service_row['client_name'],
                'client_uuid': service_row['client_uuid'],
                'inbound_id': service_row['inbound_id'],
                'protocol': service_row['protocol'],
                'total_gb': service_row['total_gb'],
                'config_link': service_row.get('config_link'),
                'panel_name': service_row['panel_name'],
                'panel_url': service_row['panel_url']
            }
            
            # Get config link - first try saved link
            config_link = service.get('config_link')
            
            # If not saved, get from panel
            if not config_link:
                panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
                if not panel_manager:
                    await query.edit_message_text("❌ خطا در اتصال به پنل.")
                    return
                
                config_link = panel_manager.get_client_config_link(
                    service['inbound_id'],
                    service['client_uuid'],
                    service['protocol']
                )
                
                # Save it for future use
                if config_link:
                    self.db.update_client_config(service['id'], config_link)
            
            if not config_link:
                await query.edit_message_text("❌ خطا در دریافت کانفیگ از پنل.")
                return
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(config_link)
            qr.make(fit=True)
            
            # Create QR code image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Save to BytesIO
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            
            # Create caption
            caption = f"""
📱 QR Code سرویس VPN

📝 نام: {escape_markdown(service['client_name'], version=1)}
🔗 پنل: {escape_markdown(service['panel_name'], version=1)}
📊 حجم: {service['total_gb']} گیگابایت

💡 راهنمای استفاده:
این QR Code را با برنامه VPN خود اسکن کنید
            """
            
            # Create back button
            keyboard = [[InlineKeyboardButton("◀️ بازگشت", callback_data=f"manage_service_{service_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send QR code image
            await query.message.reply_photo(
                photo=bio,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Delete the original message
            await query.delete_message()
            
        except Exception as e:
            logger.error(f"Error generating QR code: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در ساخت QR Code.")
    
    async def handle_reset_service_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle reset service link request with confirmation"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message has text
            is_media_message = query.message.photo or query.message.video or query.message.document
            message = """
🔗 **دریافت لینک جدید**

⚠️ **توجه:** با دریافت لینک جدید، لینک قبلی شما غیرفعال می‌شود.
• تمام اطلاعات سرویس (حجم، زمان و...) حفظ خواهد شد
• فقط UUID تغییر می‌کند و باید کانفیگ جدید را استفاده کنید

آیا مطمئن هستید؟
            """
            
            keyboard = [
                [InlineKeyboardButton("✅ بله، لینک جدید بساز", callback_data=f"confirm_reset_link_{service_id}")],
                [InlineKeyboardButton("❌ انصراف", callback_data=f"manage_service_{service_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Handle media message
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error in reset service link: {e}")
            try:
                if query.message.photo or query.message.video or query.message.document:
                    await query.message.delete()
                    await query.message.reply_text("❌ خطا در پردازش درخواست.")
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            except:
                await query.message.reply_text("❌ خطا در پردازش درخواست.")
    
    async def handle_confirm_reset_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle confirmed reset service link"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Show processing message
            await query.edit_message_text("⏳ در حال ساخت لینک جدید...")
            
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.subscription_url
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.subscription_url
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'client_name': service_row['client_name'],
                'client_uuid': service_row['client_uuid'],
                'inbound_id': service_row['inbound_id'],
                'panel_name': service_row['panel_name'],
                'sub_id': service_row.get('sub_id'),
                'subscription_url': service_row.get('subscription_url')
            }
            
            # Reset UUID using panel manager
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if not panel_manager:
                await query.edit_message_text("❌ خطا در اتصال به پنل.")
                return
            
            # Use reset_client_uuid instead of delete/create to prevent duplicates
            new_client_info = panel_manager.reset_client_uuid(
                service['inbound_id'],
                service['client_uuid']
            )
            
            if not new_client_info:
                await query.edit_message_text("❌ خطا در ساخت لینک جدید. لطفاً دوباره تلاش کنید.")
                return
            
            # Get the subId from the reset result (it preserves the old one or creates new)
            preserved_sub_id = new_client_info.get('sub_id', '')
            
            # If no sub_id from reset (old service), generate a new one
            if not preserved_sub_id:
                import uuid
                preserved_sub_id = str(uuid.uuid4()).replace('-', '')[:16]
                logger.info(f"⚠️ No sub_id in reset result, generated new: {preserved_sub_id}")
            logger.info(f"✅ Service {service_id} link reset successfully")
            logger.info(f"   Old UUID: {service['client_uuid'][:8]}...")
            logger.info(f"   New UUID: {new_client_info['new_uuid'][:8]}...")
            logger.info(f"   Preserved subId: {preserved_sub_id}")
            
            # Get panel info to determine type
            panel = self.db.get_panel(service['panel_id'])
            panel_type = panel.get('panel_type', '3x-ui') if panel else '3x-ui'
            
            # Get subscription link based on panel type (NOT direct config)
            subscription_link = ""
            if panel_type in ['marzban', 'rebecca', 'pasargad']:
                # For Marzban, Rebecca, and Pasargad, use the subscription_url from reset result
                subscription_link = new_client_info.get('subscription_url', '')
                # Make sure it's a full URL
                if subscription_link and not subscription_link.startswith('http'):
                    subscription_link = f"{panel.get('url', '')}{subscription_link}"
            else:
                # For 3x-ui, ALWAYS construct subscription link using sub_id
                # NEVER use get_client_config_link (it returns direct config, not subscription)
                sub_url = service.get('subscription_url') or (panel.get('subscription_url') if panel else '')
                if sub_url and preserved_sub_id:
                    if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                        sub_url = sub_url.rstrip('/')
                        subscription_link = f"{sub_url}/{preserved_sub_id}"
                    elif '/sub' in sub_url:
                        subscription_link = f"{sub_url}/{preserved_sub_id}"
                    else:
                        subscription_link = f"{sub_url}/sub/{preserved_sub_id}"
            
            # Update database with new UUID, sub_id, and subscription link
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET client_uuid = %s, sub_id = %s, config_link = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (new_client_info['new_uuid'], preserved_sub_id, subscription_link, service_id))
                conn.commit()
            
            message = f"""
✅ لینک جدید با موفقیت ساخته شد!

🔗 پنل: {escape_markdown(service['panel_name'], version=1)}
🆔 نام سرویس: {escape_markdown(service['client_name'], version=1)}

تغییرات:
• UUID جدید ایجاد شد
• تمام اطلاعات سرویس حفظ شد

💡 نکته: لینک سابسکریپشن جدید شما آماده است. با استفاده از دکمه زیر آن را دریافت کنید.
            """
            
            keyboard = [
                [InlineKeyboardButton("📋 دریافت کانفیگ جدید", callback_data=f"get_config_{service_id}")],
                [InlineKeyboardButton("📱 دریافت QR Code", callback_data=f"get_qr_code_{service_id}")],
                [InlineKeyboardButton("◀️ بازگشت به سرویس", callback_data=f"manage_service_{service_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error resetting service link: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در ساخت لینک جدید. لطفاً دوباره تلاش کنید.")
    
    async def handle_renew_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle service renewal"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message has text
            is_media_message = query.message.photo or query.message.video or query.message.document
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service from database
            with self.db.get_connection() as conn:
                # Enable column access by name
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.id, c.panel_id, c.product_id, c.expires_at, p.name as panel_name, 
                               p.price_per_gb, p.sale_type
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.id, c.panel_id, c.product_id, c.expires_at, p.name as panel_name, 
                               p.price_per_gb, p.sale_type
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
            
            service_row = cursor.fetchone()
                # Connection closed automatically
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'product_id': service_row['product_id'],
                'expires_at': service_row['expires_at'],
                'panel_name': service_row['panel_name'] or 'نامشخص',
                'price_per_gb': service_row['price_per_gb'] or 0,
                'sale_type': service_row['sale_type'] or 'gigabyte'
            }
            
            # Check if this is a plan-based service (must have product_id)
            if not service.get('product_id'):
                await query.edit_message_text(
                    "❌ این سرویس پلنی نیست.\n\n"
                    "برای افزایش حجم سرویس‌های گیگی، از دکمه افزایش حجم استفاده کنید.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("◀️ بازگشت", callback_data=f"manage_service_{service_id}")
                    ]])
                )
                return
            
            # Store renewal info in user session
            context.user_data['renewing_service'] = True
            context.user_data['renew_service_id'] = service_id
            context.user_data['renew_panel_id'] = service['panel_id']
            
            # Check if this is a plan-based service or panel has plan sale type
            panel = self.db.get_panel(service['panel_id'])
            sale_type = panel.get('sale_type', 'gigabyte') if panel else 'gigabyte'
            has_product = service.get('product_id') is not None
            
            # If service has product_id or panel sale_type is plan/both, show plan selection
            if has_product or sale_type in ['plan', 'both']:
                # Check if service has expired
                is_expired = False
                if service.get('expires_at'):
                    from datetime import datetime
                    expires_at = datetime.fromisoformat(service['expires_at']) if isinstance(service['expires_at'], str) else service['expires_at']
                    is_expired = datetime.now() > expires_at
                
                context.user_data['renew_is_expired'] = is_expired
                
                # Show plan selection for renewal
                await self.handle_show_products_for_renewal(update, context, service['panel_id'], service_id, is_expired)
                return
            
            # Otherwise, show gigabyte-based renewal
            price_per_gb = service['price_per_gb']
            message = f"""
🔄 تمدید و افزایش حجم سرویس

🔗 سرور: {escape_markdown(service['panel_name'], version=1)}
💰 نرخ: {price_per_gb:,} تومان به ازای هر گیگابایت

مزایا:
• افزایش فوری حجم
• بدون قطع سرویس فعلی
• نیازی به تغییر کانفیگ نیست

📦 حجم مورد نظر خود را انتخاب کنید:
            """
            
            # Show professional data plans
            reply_markup = ButtonLayout.create_data_plans(service['panel_id'])
            
            # Handle media message
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error renewing service: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                if query.message.photo or query.message.video or query.message.document:
                    await query.message.delete()
                    await query.message.reply_text("❌ خطا در تمدید سرویس.")
                else:
                    await query.edit_message_text("❌ خطا در تمدید سرویس.")
            except:
                await query.message.reply_text("❌ خطا در تمدید سرویس.")
    
    async def handle_add_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle add volume request"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message has text
            is_media_message = query.message.photo or query.message.video or query.message.document
            
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service from database
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    cursor.execute('''
                        SELECT c.id, c.panel_id, c.product_id, c.expires_at, p.name as panel_name, 
                               p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    cursor.execute('''
                        SELECT c.id, c.panel_id, c.product_id, c.expires_at, p.name as panel_name, 
                               p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
            
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'panel_name': service_row['panel_name'] or 'نامشخص',
                'price_per_gb': service_row['price_per_gb'] or 0
            }
            
            # Show add volume options
            price_per_gb = service['price_per_gb']
            message = f"""
➕ **افزایش حجم سرویس**

🔗 سرور: {escape_markdown(service['panel_name'], version=1)}
💰 نرخ: {price_per_gb:,} تومان به ازای هر گیگابایت

مزایا:
• افزایش فوری حجم
• بدون قطع سرویس فعلی
• نیازی به تغییر کانفیگ نیست

📦 حجم مورد نظر خود را انتخاب کنید:
            """
            
            # Use create_add_volume_plans which includes service_id
            reply_markup = ButtonLayout.create_add_volume_plans(service['panel_id'], service_id)
            
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error in add volume: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                if query.message.photo or query.message.video or query.message.document:
                    await query.message.delete()
                    await query.message.reply_text("❌ خطا در پردازش درخواست.")
                else:
                    await query.edit_message_text("❌ خطا در پردازش درخواست.")
            except Exception:
                pass

    async def handle_show_products_for_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                                panel_id: int, service_id: int, is_expired: bool):
        """Show products for service renewal"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Check if panel has products without category
            has_products_without_category = self.db.has_products_without_category(panel_id)
            categories = self.db.get_categories(panel_id, active_only=True)
            
            # If has products without category, show them directly
            if has_products_without_category:
                await self.handle_show_products_for_renewal_no_category(update, context, panel_id, service_id, is_expired)
                return
            
            # If no categories and no products, show error
            if not categories and not has_products_without_category:
                await query.edit_message_text(
                    "❌ هیچ محصولی برای این پنل تعریف نشده است.\n\nلطفاً با ادمین تماس بگیرید.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"manage_service_{service_id}")]
                    ])
                )
                return
            
            # Show categories for selection
            expired_text = "⚠️ سرویس شما منقضی شده است. پس از انتخاب پلن، سرویس فوراً فعال خواهد شد." if is_expired else "ℹ️ سرویس فعلی شما هنوز فعال است. پس از انتخاب پلن، سرویس فعلی رزرو و پلن جدید فعال خواهد شد."
            
            message = f"""
🔄 **تمدید سرویس - انتخاب پلن جدید**

پنل: **{escape_markdown(panel['name'], version=1)}**

{expired_text}

📦 **انتخاب دسته‌بندی:**
            """
            
            keyboard = []
            for cat in categories:
                keyboard.append([InlineKeyboardButton(
                    f"📁 {cat['name']}",
                    callback_data=f"renew_category_products_{cat['id']}_{service_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"manage_service_{service_id}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing products for renewal: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_show_products_for_renewal_no_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                                            panel_id: int, service_id: int, is_expired: bool):
        """Show products without category for renewal"""
        query = update.callback_query
        await query.answer()
        
        try:
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            products = self.db.get_products(panel_id, category_id=False, active_only=True)
            
            if not products:
                await query.edit_message_text(
                    "❌ هیچ محصول فعالی وجود ندارد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"manage_service_{service_id}")]
                    ])
                )
                return
            
            expired_text = "⚠️ سرویس شما منقضی شده است. پس از انتخاب پلن، سرویس فوراً فعال خواهد شد." if is_expired else "ℹ️ سرویس فعلی شما هنوز فعال است. پس از انتخاب پلن، سرویس فعلی رزرو و پلن جدید فعال خواهد شد."
            
            message = f"""
🔄 **تمدید سرویس - انتخاب پلن جدید**

پنل: **{panel['name']}**

{expired_text}

📦 **محصولات:**
            """
            
            keyboard = []
            for prod in products:
                prod_text = f"{prod['name']}\n💰 {prod['price']:,} تومان | 📊 {prod['volume_gb']} GB | ⏱️ {prod['duration_days']} روز"
                keyboard.append([InlineKeyboardButton(
                    prod_text,
                    callback_data=f"renew_product_{prod['id']}_{service_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"manage_service_{service_id}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing products without category for renewal: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_renew_category_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                             category_id: int, service_id: int):
        """Show products in a category for renewal"""
        query = update.callback_query
        await query.answer()
        
        try:
            category = self.db.get_category(category_id)
            if not category:
                await query.edit_message_text("❌ دسته‌بندی یافت نشد.")
                return
            
            panel = self.db.get_panel(category['panel_id'])
            panel_name = panel['name'] if panel else 'نامشخص'
            
            products = self.db.get_products(category['panel_id'], category_id=category_id, active_only=True)
            
            if not products:
                await query.edit_message_text(
                    f"❌ هیچ محصول فعالی در دسته‌بندی '{category['name']}' وجود ندارد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"renew_service_{service_id}")]
                    ])
                )
                return
            
            # Check if service is expired
            is_expired = context.user_data.get('renew_is_expired', False)
            expired_text = "⚠️ سرویس شما منقضی شده است. پس از انتخاب پلن، سرویس فوراً فعال خواهد شد." if is_expired else "ℹ️ سرویس فعلی شما هنوز فعال است. پس از انتخاب پلن، سرویس فعلی رزرو و پلن جدید فعال خواهد شد."
            
            message = f"""
🔄 **تمدید سرویس - انتخاب پلن جدید**

دسته‌بندی: **{escape_markdown(category['name'], version=1)}**
پنل: **{escape_markdown(panel_name, version=1)}**

{expired_text}

📦 **محصولات:**
            """
            
            keyboard = []
            for prod in products:
                prod_text = f"{prod['name']}\n💰 {prod['price']:,} تومان | 📊 {prod['volume_gb']} GB | ⏱️ {prod['duration_days']} روز"
                keyboard.append([InlineKeyboardButton(
                    prod_text,
                    callback_data=f"renew_product_{prod['id']}_{service_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"renew_service_{service_id}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing category products for renewal: {e}")
            await query.edit_message_text("❌ خطا در نمایش محصولات.")
    
    async def handle_renew_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, service_id: int):
        """Handle product renewal"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product or not product.get('is_active'):
                await query.edit_message_text("❌ محصول یافت نشد یا غیرفعال است.")
                return
            
            panel = self.db.get_panel(product['panel_id'])
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get service details
            service = self.db.get_user_service(service_id, user['id'])
            if not service:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Check if expired
            is_expired = context.user_data.get('renew_is_expired', False)
            
            total_price = product['price']
            
            # Store renewal info
            context.user_data['renewing_service'] = True
            context.user_data['renew_service_id'] = service_id
            context.user_data['renew_panel_id'] = product['panel_id']
            context.user_data['renew_product_id'] = product_id
            context.user_data['renew_is_expired'] = is_expired
            context.user_data['purchase_panel_id'] = product['panel_id']
            context.user_data['purchase_product_id'] = product_id
            context.user_data['purchase_total_amount'] = total_price
            context.user_data['purchase_type'] = 'plan'
            
            expired_msg = "⚠️ سرویس شما منقضی شده است. پس از پرداخت، سرویس فوراً فعال خواهد شد." if is_expired else "ℹ️ سرویس فعلی شما هنوز فعال است. پس از پرداخت، سرویس فعلی رزرو و پلن جدید فعال خواهد شد."
            
            # Show product details and discount code entry screen
            message = f"""
💳 **فاکتور تمدید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📦 **محصول:** {escape_markdown(product['name'], version=1)}
📊 **حجم:** {product['volume_gb']} گیگابایت
⏱️ **مدت زمان:** {product['duration_days']} روز
💵 **مبلغ کل:** {total_price:,} تومان

{expired_msg}

🎁 اگر کد تخفیف دارید، از دکمه زیر استفاده کنید:
            """
            
            keyboard = [
                [InlineKeyboardButton("🏷️ وارد کردن کد تخفیف", callback_data=f"enter_discount_code_renew_product_{product_id}_{service_id}")],
                [InlineKeyboardButton("⏭️ ادامه بدون کد تخفیف", callback_data=f"continue_without_discount_renew_product_{product_id}_{service_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"manage_service_{service_id}")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling renew product: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در پردازش تمدید محصول.")
    
    async def handle_enter_discount_code_renew_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                                        product_id: int, service_id: int):
        """Handle discount code entry request for product renewal"""
        query = update.callback_query
        await query.answer()
        
        try:
            product = self.db.get_product(product_id)
            if not product:
                await query.edit_message_text("❌ محصول یافت نشد.")
                return
            
            context.user_data['waiting_for_discount_code_renew_product'] = True
            context.user_data['discount_product_id'] = product_id
            context.user_data['discount_service_id'] = service_id
            
            text = """
🏷️ **وارد کردن کد تخفیف یا کد هدیه**

لطفاً کد تخفیف یا کد هدیه خود را ارسال کنید:

⚠️ توجه: کد تخفیف فقط یک بار قابل استفاده است و باید قبل از پرداخت وارد شود.

💡 کد هدیه: موجودی حساب شما را افزایش می‌دهد
💡 کد تخفیف: روی مبلغ خرید شما تخفیف اعمال می‌کند

برای لغو: /cancel
            """
            
            keyboard = [[InlineKeyboardButton("❌ لغو", callback_data=f"continue_without_discount_renew_product_{product_id}_{service_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling discount code entry for product renewal: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_continue_without_discount_renew_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                                             product_id: int, service_id: int):
        """Continue product renewal without discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Clear discount code waiting state
            context.user_data.pop('waiting_for_discount_code_renew_product', None)
            context.user_data.pop('discount_product_id', None)
            context.user_data.pop('discount_service_id', None)
            
            # Create invoice and show payment options for product renewal
            await self.create_invoice_and_show_payment_product_renewal(update, context, product_id, service_id, None)
            
        except Exception as e:
            logger.error(f"Error continuing product renewal without discount: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def create_invoice_and_show_payment_product_renewal(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                              product_id: int, service_id: int, discount_code: str = None):
        """Create invoice for product renewal and show payment options"""
        try:
            product = self.db.get_product(product_id)
            if not product or not product.get('is_active'):
                await update.callback_query.edit_message_text("❌ محصول یافت نشد یا غیرفعال است.")
                return
            
            panel = self.db.get_panel(product['panel_id'])
            if not panel:
                await update.callback_query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            if not user:
                await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Calculate amounts
            original_amount = product['price']
            final_amount = original_amount
            discount_amount = 0
            
            # Apply discount if exists
            if discount_code:
                from discount_manager import DiscountManager
                discount_manager = DiscountManager(self.db)
                discount_result = discount_manager.validate_and_apply_discount(discount_code, user_id, original_amount)
                
                if discount_result['success']:
                    final_amount = discount_result['final_amount']
                    discount_amount = discount_result['discount_amount']
            
            # Create invoice for renewal
            invoice_result = self.payment_manager.create_invoice(
                user_id, product['panel_id'], product['volume_gb'], final_amount, 'gateway', discount_code
            )
            
            if not invoice_result['success']:
                await update.callback_query.edit_message_text(f"❌ {invoice_result['message']}")
                return
            
            # Store product info and renewal info for client creation
            invoice_id = invoice_result['invoice_id']
            self.db.update_invoice_product_info(invoice_id, product_id, product['duration_days'])
            
            # Store renewal info
            context.user_data['renew_invoice_id'] = invoice_id
            context.user_data['renew_service_id'] = service_id
            context.user_data['renew_product_id'] = product_id
            context.user_data['renew_is_expired'] = context.user_data.get('renew_is_expired', False)
            
            # Show payment options
            is_expired = context.user_data.get('renew_is_expired', False)
            expired_msg = "⚠️ سرویس شما منقضی شده است. پس از پرداخت، سرویس فوراً فعال خواهد شد." if is_expired else "ℹ️ سرویس فعلی شما هنوز فعال است. پس از پرداخت، سرویس فعلی رزرو و پلن جدید فعال خواهد شد."
            
            text = f"""
💳 **فاکتور تمدید سرویس**

🔗 **پنل:** {escape_markdown(panel['name'], version=1)}
📦 **محصول:** {escape_markdown(product['name'], version=1)}
📊 **حجم:** {product['volume_gb']} گیگابایت
⏱️ **مدت زمان:** {product['duration_days']} روز
"""
            
            if discount_amount > 0:
                text += f"""
💵 **مبلغ قبل از تخفیف:** {original_amount:,} تومان
🎁 **تخفیف:** {discount_amount:,} تومان
💵 **مبلغ قابل پرداخت:** {final_amount:,} تومان
"""
            else:
                text += f"💵 **مبلغ کل:** {original_amount:,} تومان\n"
            
            text += f"\n{expired_msg}\n\nروش پرداخت را انتخاب کنید:"
            
            # Get user balance
            user_balance = self.payment_manager.get_user_balance(user_id)
            
            reply_markup = ButtonLayout.create_payment_method_buttons(
                invoice_id, user_balance, final_amount
            )
            
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error creating invoice for product renewal: {e}")
            await update.callback_query.edit_message_text("❌ خطا در ایجاد فاکتور.")
    
    async def handle_delete_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle service deletion"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Check if message has text
            is_media_message = query.message.photo or query.message.video or query.message.document
            message = """
🗑️ حذف سرویس

⚠️ هشدار مهم:
آیا از حذف این سرویس اطمینان دارید؟

❌ توجه کنید:
• این عمل غیرقابل بازگشت است
• تمام اطلاعات و کانفیگ سرویس پاک می‌شود
• حجم باقیمانده قابل بازگشت نیست
• هزینه پرداخت شده مسترد نمی‌شود

💡 پیشنهاد: اگر فقط می‌خواهید کانفیگ جدید بگیرید، از گزینه "دریافت لینک جدید" استفاده کنید
            """
            
            keyboard = [
                [InlineKeyboardButton("✅ بله، کاملاً مطمئنم", callback_data=f"confirm_delete_service_{service_id}")],
                [InlineKeyboardButton("◀️ انصراف و بازگشت", callback_data=f"manage_service_{service_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Handle media message
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error deleting service: {e}")
            try:
                if query.message.photo or query.message.video or query.message.document:
                    await query.message.delete()
                    await query.message.reply_text("❌ خطا در حذف سرویس.")
                else:
                    await query.edit_message_text("❌ خطا در حذف سرویس.")
            except:
                await query.message.reply_text("❌ خطا در حذف سرویس.")
    
    async def check_client_connection_status(self, panel_manager, inbound_id: int, client_uuid: str, client_name: str = None) -> str:
        """
        Check if client is currently online by getting real-time stats from panel
        
        For Marzban panels, online_at is updated every time the client connects.
        We consider a client online if online_at is within the last 2 minutes.
        This provides real-time, accurate connection status.
        """
        try:
            logger.info(f"🔍 Checking connection status for client {client_uuid[:8]}... on inbound {inbound_id}")
            
            # Get real-time client details from panel
            # Note: service_id not available in this context, so no callback
            client_details = panel_manager.get_client_details(inbound_id, client_uuid, client_name=client_name)
            
            if client_details:
                last_activity = client_details.get('last_activity', 0)
                online_at_raw = client_details.get('online_at_raw')
                
                # Log raw value for debugging
                logger.info(f"📊 Raw online_at from Marzban: {online_at_raw}")
                
                # Handle None value
                if last_activity is None:
                    last_activity = 0
                
                # Handle string datetime (should already be converted in marzban_manager)
                if isinstance(last_activity, str):
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                        last_activity = int(dt.timestamp() * 1000)  # Convert to milliseconds
                    except Exception as e:
                        logger.warning(f"⚠️ Could not parse last_activity string '{last_activity}': {e}")
                        last_activity = 0
                
                logger.info(f"📊 Client details found. last_activity = {last_activity} ms")
                
                if last_activity > 0:
                    # Check if client has been active in the last 2 minutes (120 seconds)
                    # Reduced from 5 minutes for more accurate real-time status
                    current_time = int(time.time() * 1000)  # milliseconds
                    time_since_last_activity = current_time - last_activity
                    
                    logger.info(f"⏰ Current time: {current_time} ms, Last activity: {last_activity} ms")
                    logger.info(f"⏰ Time since last activity: {time_since_last_activity} ms ({time_since_last_activity // 1000} seconds)")
                    
                    # If time_since_last_activity is negative, it means datetime parsing was wrong
                    # or there's a timezone issue. Treat as "just now"
                    if time_since_last_activity < 0:
                        logger.warning(f"⚠️ Negative time difference detected! Last activity appears to be in the future.")
                        logger.warning(f"⚠️ This usually means timezone issue. Treating as 'online now'")
                        return "🟢 آنلاین (همین الان)"
                    
                    # 2 minutes = 2 * 60 * 1000 milliseconds = 120,000 ms
                    # This threshold provides real-time accuracy
                    ONLINE_THRESHOLD_MS = 2 * 60 * 1000
                    
                    if time_since_last_activity < ONLINE_THRESHOLD_MS:
                        seconds_ago = time_since_last_activity // 1000
                        logger.info(f"✅ Client {client_uuid[:8]}... is ONLINE (last activity: {seconds_ago}s ago)")
                        
                        # Show "just now" for very recent connections (< 5 seconds)
                        if seconds_ago < 5:
                            return "🟢 آنلاین (همین الان)"
                        else:
                            return f"🟢 آنلاین ({seconds_ago}ث پیش)"
                    else:
                        minutes_ago = time_since_last_activity // (60 * 1000)
                        hours_ago = minutes_ago // 60
                        
                        # Always return plain offline without time suffix
                        if hours_ago > 0:
                            logger.info(f"❌ Client {client_uuid[:8]}... is OFFLINE (last activity: {hours_ago} hours ago)")
                        else:
                            logger.info(f"❌ Client {client_uuid[:8]}... is OFFLINE (last activity: {minutes_ago} minutes ago)")
                        return "🔴 آفلاین"
                else:
                    logger.info(f"⚠️ Client {client_uuid[:8]}... has no activity recorded (last_activity = 0)")
                    return "⚪ هرگز متصل نشده"
            else:
                logger.warning(f"⚠️ Could not get client details for {client_uuid[:8]}...")
                return "❌ نامشخص"
                
        except Exception as e:
            logger.error(f"Error checking connection status: {e}")
            import traceback
            traceback.print_exc()
            return "❌ خطا در بررسی"
    
    async def handle_confirm_delete_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle confirmed service deletion"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get service details
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get service details before deletion
            service_row = None
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                ''', (service_id, user['id']))
                
                service_row = cursor.fetchone()
                # Connection closed automatically
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'client_uuid': service_row['client_uuid'],
                'inbound_id': service_row['inbound_id'],
                'panel_name': service_row['panel_name']
            }
            
            # Delete client from panel first
            try:
                panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
                if panel_manager and panel_manager.login():
                    # Delete client from panel
                    success = panel_manager.delete_client(service['inbound_id'], service['client_uuid'])
                    if success:
                        logger.info(f"Client {service['client_uuid']} deleted from panel {service['panel_name']}")
                    else:
                        logger.warning(f"Failed to delete client {service['client_uuid']} from panel {service['panel_name']}")
            except Exception as e:
                logger.error(f"Error deleting client from panel: {e}")
            
            # Delete service from database
            deleted_rows = 0
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM clients WHERE id = %s AND user_id = %s', (service_id, user['id']))
                deleted_rows = cursor.rowcount
                conn.commit()
                # Connection closed automatically
            
            if deleted_rows > 0:
                message = "✅ سرویس با موفقیت حذف شد."
                
                # Report service deletion to channel
                if self.reporting_system:
                    try:
                        service_data = {
                            'service_name': service_row.get('client_name', 'سرویس'),
                            'data_amount': service_row.get('total_gb', 0),
                            'panel_name': service_row.get('panel_name', 'نامشخص')
                        }
                        await self.reporting_system.report_service_deleted(user, service_data, "حذف دستی توسط کاربر")
                    except Exception as e:
                        logger.error(f"Failed to send service deletion report: {e}")
            else:
                message = "❌ سرویس یافت نشد یا قبلاً حذف شده است."
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل کاربری", callback_data="user_panel")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in handle_confirm_delete_service: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در حذف سرویس.")
    
    async def handle_change_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle panel/location change request"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Get current panel price
            current_price_per_gb = service_row.get('price_per_gb', 0)
            if not current_price_per_gb or current_price_per_gb == 0:
                await query.edit_message_text(
                    "❌ این سرویس قیمت گیگابایت مشخصی ندارد. تغییر لوکیشن فقط برای پنل‌های با قیمت یکسان امکان‌پذیر است."
                )
                return
            
            # Get panels with same price (excluding current panel)
            compatible_panels = self.db.get_panels_with_same_price(
                current_price_per_gb, 
                exclude_panel_id=service_row['panel_id']
            )
            
            # Get active inbounds from all panels with same price (excluding current panel)
            active_inbounds = self.db.get_active_inbounds_for_change(
                exclude_panel_id=service_row['panel_id'],
                exclude_inbound_id=service_row['inbound_id'],
                price_per_gb=current_price_per_gb
            )
            
            # Also get inbounds from current panel (excluding current inbound)
            current_panel_inbounds = self.db.get_active_inbounds_for_change(
                exclude_panel_id=None,
                exclude_inbound_id=service_row['inbound_id'],
                price_per_gb=current_price_per_gb
            )
            current_panel_inbounds = [ib for ib in current_panel_inbounds if ib['panel_id'] == service_row['panel_id']]
            
            if not compatible_panels and not active_inbounds and not current_panel_inbounds:
                await query.edit_message_text(
                    f"❌ هیچ پنل یا اینباند دیگری با قیمت {current_price_per_gb:,} تومان/گیگابایت یافت نشد.\n\n"
                    "تغییر لوکیشن فقط برای پنل‌های با قیمت یکسان امکان‌پذیر است."
                )
                return
            
            # Get current service traffic info
            panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
            remaining_gb = service_row.get('total_gb', 0)
            used_gb = service_row.get('used_gb', 0) or 0
            
            if panel_manager and panel_manager.login():
                # Create callback to update inbound_id if found in different inbound
                def update_inbound_callback(service_id, new_inbound_id):
                    try:
                        self.db.update_service_inbound_id(service_id, new_inbound_id)
                        logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
                
                # Check if panel manager supports optional parameters
                import inspect
                sig = inspect.signature(panel_manager.get_client_details)
                params = list(sig.parameters.keys())
                
                if 'update_inbound_callback' in params and 'service_id' in params:
                    client = panel_manager.get_client_details(
                        service_row['inbound_id'], 
                        service_row['client_uuid'],
                        update_inbound_callback=update_inbound_callback,
                        service_id=service_id
                    )
                else:
                    client = panel_manager.get_client_details(
                        service_row['inbound_id'], 
                        service_row['client_uuid']
                    )
                if client:
                    total_traffic_bytes = client.get('total_traffic', 0)
                    used_traffic_bytes = client.get('used_traffic', 0)
                    if total_traffic_bytes > 0:
                        remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
                        remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
                        used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 2)
            
            if remaining_gb <= 0:
                await query.edit_message_text(
                    "❌ حجم باقیمانده سرویس شما صفر است. امکان تغییر لوکیشن وجود ندارد."
                )
                return
            
            # Create selection buttons
            keyboard = []
            
            # Add current panel's other inbounds first
            if current_panel_inbounds:
                keyboard.append([InlineKeyboardButton("🔗 اینباندهای همین پنل:", callback_data="noop")])
                for inbound in current_panel_inbounds:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"  🔗 {inbound['inbound_name']}",
                            callback_data=f"select_new_inbound_{service_id}_{inbound['panel_id']}_{inbound['inbound_id']}"
                        )
                    ])
            
            # Add other panels
            if compatible_panels:
                if keyboard:
                    keyboard.append([])  # Add separator
                keyboard.append([InlineKeyboardButton("🌍 پنل‌های دیگر:", callback_data="noop")])
                for panel in compatible_panels:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🌍 {panel['name']}",
                            callback_data=f"select_new_panel_{service_id}_{panel['id']}"
                        )
                    ])
            
            # Add other panels' inbounds
            if active_inbounds:
                if keyboard:
                    keyboard.append([])  # Add separator
                keyboard.append([InlineKeyboardButton("🔗 اینباندهای پنل‌های دیگر:", callback_data="noop")])
                
                # Group inbounds by panel
                inbounds_by_panel = {}
                for inbound in active_inbounds:
                    panel_id = inbound['panel_id']
                    if panel_id not in inbounds_by_panel:
                        inbounds_by_panel[panel_id] = []
                    inbounds_by_panel[panel_id].append(inbound)
                
                for panel_id, inbounds_list in inbounds_by_panel.items():
                    panel_name = inbounds_list[0]['panel_name']
                    keyboard.append([InlineKeyboardButton(f"📡 {panel_name}:", callback_data="noop")])
                    for inbound in inbounds_list:
                        keyboard.append([
                            InlineKeyboardButton(
                                f"  🔗 {inbound['inbound_name']}",
                                callback_data=f"select_new_inbound_{service_id}_{inbound['panel_id']}_{inbound['inbound_id']}"
                            )
                        ])
            
            keyboard.append([
                InlineKeyboardButton("◀️ بازگشت", callback_data=f"manage_service_{service_id}")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
🌍 **تغییر لوکیشن/پنل/اینباند**

📊 **وضعیت فعلی:**
   • پنل فعلی: {service_row['panel_name']}
   • حجم باقیمانده: {remaining_gb:.2f} گیگابایت
   • حجم مصرف شده: {used_gb:.2f} گیگابایت
   • قیمت هر گیگابایت: {current_price_per_gb:,} تومان

💡 **نکته مهم:**
   • حجم باقیمانده ({remaining_gb:.2f} گیگابایت) به مقصد منتقل می‌شود
   • کلاینت از مبدا حذف و در مقصد ایجاد می‌شود
   • حجم کلی سرویس به {remaining_gb:.2f} گیگابایت به‌روزرسانی می‌شود

📋 **انتخاب مقصد:**
            """
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in handle_change_panel: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_select_new_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, new_panel_id: int):
        """Handle new panel selection for location change"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Get new panel details
            new_panel = self.db.get_panel(new_panel_id)
            if not new_panel:
                await query.edit_message_text("❌ پنل مقصد یافت نشد.")
                return
            
            # Verify price match
            if new_panel.get('price_per_gb', 0) != service_row.get('price_per_gb', 0):
                await query.edit_message_text("❌ قیمت پنل مقصد با پنل فعلی یکسان نیست.")
                return
            
            # Get current service traffic info
            panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
            remaining_gb = service_row.get('total_gb', 0)
            used_gb = service_row.get('used_gb', 0) or 0
            
            if panel_manager and panel_manager.login():
                # Create callback to update inbound_id if found in different inbound
                def update_inbound_callback(service_id, new_inbound_id):
                    try:
                        self.db.update_service_inbound_id(service_id, new_inbound_id)
                        logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
                
                # Check if panel manager supports optional parameters
                import inspect
                sig = inspect.signature(panel_manager.get_client_details)
                params = list(sig.parameters.keys())
                
                if 'update_inbound_callback' in params and 'service_id' in params:
                    client = panel_manager.get_client_details(
                        service_row['inbound_id'], 
                        service_row['client_uuid'],
                        update_inbound_callback=update_inbound_callback,
                        service_id=service_id
                    )
                else:
                    client = panel_manager.get_client_details(
                        service_row['inbound_id'], 
                        service_row['client_uuid']
                    )
                if client:
                    total_traffic_bytes = client.get('total_traffic', 0)
                    used_traffic_bytes = client.get('used_traffic', 0)
                    if total_traffic_bytes > 0:
                        remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
                        remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
                        used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 2)
            
            if remaining_gb <= 0:
                await query.edit_message_text("❌ حجم باقیمانده سرویس شما صفر است.")
                return
            
            # Create confirmation message
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ تأیید تغییر",
                        callback_data=f"confirm_change_panel_{service_id}_{new_panel_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ انصراف",
                        callback_data=f"change_panel_{service_id}"
                    )
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
⚠️ **تأیید تغییر لوکیشن/پنل**

📊 **اطلاعات انتقال:**
   • پنل مبدا: {service_row['panel_name']}
   • پنل مقصد: {new_panel['name']}
   • حجم منتقل شونده: {remaining_gb:.2f} گیگابایت

🔄 **عملیات انجام شده:**
   • حذف کلاینت از پنل {service_row['panel_name']}
   • ایجاد کلاینت جدید در پنل {new_panel['name']}
   • به‌روزرسانی حجم کلی سرویس به {remaining_gb:.2f} گیگابایت

⚠️ **هشدار:** این عملیات غیرقابل بازگشت است!

آیا از تغییر لوکیشن اطمینان دارید؟
            """
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in handle_select_new_panel: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_confirm_change_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, new_panel_id: int):
        """Handle confirmed panel change"""
        query = update.callback_query
        await query.answer("در حال انتقال...")
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Get new panel details
            new_panel = self.db.get_panel(new_panel_id)
            if not new_panel:
                await query.edit_message_text("❌ پنل مقصد یافت نشد.")
                return
            
            # Verify price match
            if new_panel.get('price_per_gb', 0) != service_row.get('price_per_gb', 0):
                await query.edit_message_text("❌ قیمت پنل مقصد با پنل فعلی یکسان نیست.")
                return
            
            # Get source panel manager
            source_panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
            if not source_panel_manager or not source_panel_manager.login():
                await query.edit_message_text("❌ خطا در اتصال به پنل مبدا.")
                return
            
            # Create callback to update inbound_id if found in different inbound
            def update_inbound_callback(service_id, new_inbound_id):
                try:
                    self.db.update_service_inbound_id(service_id, new_inbound_id)
                    logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
            
            # Get current client details and calculate remaining GB
            # Check if panel manager supports optional parameters
            import inspect
            sig = inspect.signature(source_panel_manager.get_client_details)
            params = list(sig.parameters.keys())
            
            if 'update_inbound_callback' in params and 'service_id' in params:
                client = source_panel_manager.get_client_details(
                    service_row['inbound_id'], 
                    service_row['client_uuid'],
                    update_inbound_callback=update_inbound_callback,
                    service_id=service_id
                )
            else:
                client = source_panel_manager.get_client_details(
                    service_row['inbound_id'], 
                    service_row['client_uuid']
                )
            if not client:
                await query.edit_message_text("❌ کلاینت در پنل مبدا یافت نشد.")
                return
            
            total_traffic_bytes = client.get('total_traffic', 0)
            used_traffic_bytes = client.get('used_traffic', 0)
            expire_time = client.get('expiryTime', 0)
            
            if total_traffic_bytes <= 0:
                await query.edit_message_text("❌ حجم سرویس نامحدود است. امکان تغییر لوکیشن وجود ندارد.")
                return
            
            remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
            remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
            
            if remaining_gb <= 0:
                await query.edit_message_text("❌ حجم باقیمانده سرویس صفر است.")
                return
            
            # Calculate expire_days from expiryTime
            expire_days = 0  # 0 means unlimited
            if expire_time and expire_time > 0:
                import time
                current_time_ms = int(time.time() * 1000)
                # Handle both milliseconds (3x-ui) and seconds (Marzban) format
                if expire_time > 1000000000000:  # Milliseconds
                    remaining_ms = expire_time - current_time_ms
                else:  # Seconds
                    remaining_ms = (expire_time * 1000) - current_time_ms
                
                if remaining_ms > 0:
                    expire_days = max(1, int(remaining_ms / (1000 * 60 * 60 * 24)))
            
            # Get destination panel manager
            dest_panel_manager = self.admin_manager.get_panel_manager(new_panel_id)
            if not dest_panel_manager or not dest_panel_manager.login():
                await query.edit_message_text("❌ خطا در اتصال به پنل مقصد.")
                return
            
            # Get inbounds from destination panel
            dest_inbounds = dest_panel_manager.get_inbounds()
            if not dest_inbounds:
                await query.edit_message_text("❌ هیچ اینباندی در پنل مقصد یافت نشد.")
                return
            
            # Use default inbound or first available
            dest_inbound_id = new_panel.get('default_inbound_id') or dest_inbounds[0].get('id')
            if not dest_inbound_id:
                await query.edit_message_text("❌ اینباند پیش‌فرض در پنل مقصد یافت نشد.")
                return
            
            # Step 1: Create new client in destination panel with same expiry
            client_name = service_row.get('client_name', f"user_{user_id}")
            new_client = dest_panel_manager.create_client(
                inbound_id=dest_inbound_id,
                client_name=client_name,
                protocol=service_row.get('protocol', 'vless'),
                expire_days=expire_days,  # Preserve expiry time
                total_gb=remaining_gb
            )
            
            if not new_client:
                await query.edit_message_text("❌ خطا در ایجاد کلاینت در پنل مقصد.")
                return
            
            new_client_uuid = new_client.get('id') or new_client.get('uuid')
            new_sub_id = new_client.get('sub_id') or new_client.get('subId')
            
            logger.info(f"📋 New client created - UUID: {new_client_uuid[:8]}..., sub_id: {new_sub_id}")
            
            # Get new subscription link from destination panel (NOT direct config)
            new_subscription_link = ""
            try:
                panel_type = new_panel.get('panel_type', '3x-ui')
                subscription_url = new_panel.get('subscription_url', '')
                
                logger.info(f"🔗 Panel type: {panel_type}, subscription_url: {subscription_url}")
                
                if panel_type in ['marzban', 'rebecca']:
                    # For Marzban and Rebecca, get subscription link from panel API
                    new_subscription_link = dest_panel_manager.get_client_config_link(
                        dest_inbound_id,
                        new_client_uuid,
                        service_row.get('protocol', 'vless')
                    )
                    # Marzban/Rebecca returns subscription link directly
                    if not new_subscription_link and new_client.get('subscription_url'):
                        new_subscription_link = new_client.get('subscription_url')
                else:
                    # For 3x-ui, ALWAYS construct subscription link from subscription_url + sub_id
                    # NEVER use get_client_config_link (it returns direct config, not subscription)
                    if new_sub_id and subscription_url:
                        if subscription_url.endswith('/sub') or subscription_url.endswith('/sub/'):
                            sub_url = subscription_url.rstrip('/')
                            new_subscription_link = f"{sub_url}/{new_sub_id}"
                        elif '/sub' in subscription_url:
                            new_subscription_link = f"{subscription_url}/{new_sub_id}"
                        else:
                            new_subscription_link = f"{subscription_url}/sub/{new_sub_id}"
                        
                        logger.info(f"✅ Constructed subscription link: {new_subscription_link[:50]}...")
                    else:
                        logger.warning(f"⚠️ Cannot construct subscription link - sub_id: {new_sub_id}, subscription_url: {subscription_url}")
                    
            except Exception as e:
                logger.error(f"Error getting new subscription link: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Continue even if subscription link fails - we can get it later
            
            # Step 2: Delete client from source panel
            delete_success = source_panel_manager.delete_client(
                service_row['inbound_id'],
                service_row['client_uuid']
            )
            
            if not delete_success:
                # If deletion failed, try to delete the new client to rollback
                try:
                    dest_panel_manager.delete_client(dest_inbound_id, new_client_uuid)
                except:
                    pass
                await query.edit_message_text("❌ خطا در حذف کلاینت از پنل مبدا. عملیات لغو شد.")
                return
            
            # Step 3: Update service in database with new panel info and subscription link
            update_success = self.db.update_service_panel(
                service_id=service_id,
                new_panel_id=new_panel_id,
                new_inbound_id=dest_inbound_id,
                new_client_uuid=new_client_uuid,
                new_total_gb=remaining_gb,
                config_link=new_subscription_link if new_subscription_link else None,
                sub_id=new_sub_id if new_sub_id else None
            )
            
            if not update_success:
                await query.edit_message_text("❌ خطا در به‌روزرسانی اطلاعات سرویس در دیتابیس.")
                return
            
            # Success! Show success message with option to view updated service
            keyboard = [
                [InlineKeyboardButton("🔧 مشاهده سرویس به‌روزرسانی شده", callback_data=f"manage_service_{service_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
✅ **تغییر لوکیشن با موفقیت انجام شد!**

📊 **اطلاعات جدید:**
   • پنل جدید: {new_panel['name']}
   • حجم سرویس: {remaining_gb:.2f} گیگابایت
   • شناسه کلاینت: {new_client_uuid[:8]}...

💡 **تغییرات انجام شده:**
   ✅ کلاینت از پنل {service_row['panel_name']} حذف شد
   ✅ کلاینت جدید در پنل {new_panel['name']} ایجاد شد
   ✅ لینک کانفیگ/subscription به‌روزرسانی شد
   ✅ حجم سرویس به {remaining_gb:.2f} گیگابایت تنظیم شد

🔗 لینک کانفیگ و subscription شما اکنون مربوط به پنل جدید است.

برای مشاهده اطلاعات کامل سرویس، دکمه زیر را بزنید.
            """
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Report panel change to channel
            if self.reporting_system:
                try:
                    # Get inbound names
                    old_inbound_name = None
                    new_inbound_name = None
                    
                    # Get old inbound name
                    try:
                        source_panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
                        if source_panel_manager and source_panel_manager.login():
                            old_inbounds = source_panel_manager.get_inbounds()
                            for inbound in old_inbounds:
                                if inbound.get('id') == service_row.get('inbound_id'):
                                    old_inbound_name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound.get('id')}"
                                    break
                    except:
                        pass
                    
                    # Get new inbound name
                    try:
                        dest_panel_manager = self.admin_manager.get_panel_manager(new_panel_id)
                        if dest_panel_manager and dest_panel_manager.login():
                            new_inbounds = dest_panel_manager.get_inbounds()
                            for inbound in new_inbounds:
                                if inbound.get('id') == dest_inbound_id:
                                    new_inbound_name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound.get('id')}"
                                    break
                    except:
                        pass
                    
                    service_data = {
                        'service_name': service_row.get('client_name', 'سرویس'),
                        'old_panel_name': service_row.get('panel_name', 'نامشخص'),
                        'new_panel_name': new_panel.get('name', 'نامشخص'),
                        'remaining_gb': remaining_gb,
                        'old_panel_id': service_row['panel_id'],
                        'new_panel_id': new_panel_id,
                        'old_inbound_name': old_inbound_name,
                        'new_inbound_name': new_inbound_name
                    }
                    await self.reporting_system.report_panel_change(user, service_data)
                except Exception as e:
                    logger.error(f"Failed to send panel change report: {e}")
            
        except Exception as e:
            logger.error(f"Error in handle_confirm_change_panel: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در انجام عملیات تغییر لوکیشن.")
    
    async def handle_select_new_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, new_panel_id: int, new_inbound_id: int):
        """Handle new inbound selection for inbound change"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Get destination panel and inbound info
            new_panel = self.db.get_panel(new_panel_id)
            if not new_panel:
                await query.edit_message_text("❌ پنل مقصد یافت نشد.")
                return
            
            # Get inbound info
            inbound_info = self.db.get_panel_inbound(new_panel_id, new_inbound_id)
            if not inbound_info:
                await query.edit_message_text("❌ اینباند مقصد یافت نشد.")
                return
            
            # Verify inbound is enabled
            if not inbound_info.get('is_enabled', 1):
                await query.edit_message_text("❌ اینباند مقصد غیرفعال است.")
                return
            
            # Verify price match if changing panel
            if new_panel_id != service_row['panel_id']:
                if new_panel.get('price_per_gb', 0) != service_row.get('price_per_gb', 0):
                    await query.edit_message_text("❌ قیمت پنل مقصد با پنل فعلی یکسان نیست.")
                    return
            
            # Get current service traffic info
            panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
            remaining_gb = service_row.get('total_gb', 0)
            used_gb = service_row.get('used_gb', 0) or 0
            
            if panel_manager and panel_manager.login():
                # Create callback to update inbound_id if found in different inbound
                def update_inbound_callback(service_id, new_inbound_id):
                    try:
                        self.db.update_service_inbound_id(service_id, new_inbound_id)
                        logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
                
                # Check if panel manager supports optional parameters
                import inspect
                sig = inspect.signature(panel_manager.get_client_details)
                params = list(sig.parameters.keys())
                
                if 'update_inbound_callback' in params and 'service_id' in params:
                    client = panel_manager.get_client_details(
                        service_row['inbound_id'], 
                        service_row['client_uuid'],
                        update_inbound_callback=update_inbound_callback,
                        service_id=service_id
                    )
                else:
                    client = panel_manager.get_client_details(
                        service_row['inbound_id'], 
                        service_row['client_uuid']
                    )
                if client:
                    total_traffic_bytes = client.get('total_traffic', 0)
                    used_traffic_bytes = client.get('used_traffic', 0)
                    if total_traffic_bytes > 0:
                        remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
                        remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
                        used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 2)
            
            if remaining_gb <= 0:
                await query.edit_message_text("❌ حجم باقیمانده سرویس شما صفر است.")
                return
            
            # Determine if this is a panel change or just inbound change
            is_panel_change = new_panel_id != service_row['panel_id']
            destination_text = f"{new_panel['name']} - {inbound_info['inbound_name']}" if is_panel_change else inbound_info['inbound_name']
            
            # Create confirmation message
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ تأیید تغییر",
                        callback_data=f"confirm_change_inbound_{service_id}_{new_panel_id}_{new_inbound_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ انصراف",
                        callback_data=f"change_panel_{service_id}"
                    )
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            change_type = "پنل/اینباند" if is_panel_change else "اینباند"
            message = f"""
⚠️ **تأیید تغییر {change_type}**

📊 **اطلاعات انتقال:**
   • پنل مبدا: {service_row['panel_name']}
   • اینباند مبدا: {service_row.get('inbound_id', 'نامشخص')}
   • پنل مقصد: {new_panel['name']}
   • اینباند مقصد: {inbound_info['inbound_name']}
   • حجم منتقل شونده: {remaining_gb:.2f} گیگابایت

🔄 **عملیات انجام شده:**
   • حذف کلاینت از {service_row['panel_name']}
   • ایجاد کلاینت جدید در {destination_text}
   • به‌روزرسانی حجم کلی سرویس به {remaining_gb:.2f} گیگابایت

⚠️ **هشدار:** این عملیات غیرقابل بازگشت است!

آیا از تغییر {change_type} اطمینان دارید؟
            """
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in handle_select_new_inbound: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در پردازش درخواست.")
    
    async def handle_confirm_change_inbound(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, new_panel_id: int, new_inbound_id: int):
        """Handle confirmed inbound/panel change"""
        query = update.callback_query
        await query.answer("در حال انتقال...")
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Get destination panel and inbound info
            new_panel = self.db.get_panel(new_panel_id)
            if not new_panel:
                await query.edit_message_text("❌ پنل مقصد یافت نشد.")
                return
            
            # Verify inbound is enabled
            inbound_info = self.db.get_panel_inbound(new_panel_id, new_inbound_id)
            if not inbound_info or not inbound_info.get('is_enabled', 1):
                await query.edit_message_text("❌ اینباند مقصد یافت نشد یا غیرفعال است.")
                return
            
            # Verify price match if changing panel
            if new_panel_id != service_row['panel_id']:
                if new_panel.get('price_per_gb', 0) != service_row.get('price_per_gb', 0):
                    await query.edit_message_text("❌ قیمت پنل مقصد با پنل فعلی یکسان نیست.")
                    return
            
            # Get source panel manager
            source_panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
            if not source_panel_manager or not source_panel_manager.login():
                await query.edit_message_text("❌ خطا در اتصال به پنل مبدا.")
                return
            
            # Create callback to update inbound_id if found in different inbound
            def update_inbound_callback(service_id, new_inbound_id):
                try:
                    self.db.update_service_inbound_id(service_id, new_inbound_id)
                    logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
            
            # Get current client details and calculate remaining GB
            # Check if panel manager supports optional parameters
            import inspect
            sig = inspect.signature(source_panel_manager.get_client_details)
            params = list(sig.parameters.keys())
            
            if 'update_inbound_callback' in params and 'service_id' in params:
                client = source_panel_manager.get_client_details(
                    service_row['inbound_id'], 
                    service_row['client_uuid'],
                    update_inbound_callback=update_inbound_callback,
                    service_id=service_id
                )
            else:
                client = source_panel_manager.get_client_details(
                    service_row['inbound_id'], 
                    service_row['client_uuid']
                )
            if not client:
                await query.edit_message_text("❌ کلاینت در پنل مبدا یافت نشد.")
                return
            
            total_traffic_bytes = client.get('total_traffic', 0)
            used_traffic_bytes = client.get('used_traffic', 0)
            expire_time = client.get('expiryTime', 0)
            
            if total_traffic_bytes <= 0:
                await query.edit_message_text("❌ حجم سرویس نامحدود است. امکان تغییر وجود ندارد.")
                return
            
            remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
            remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
            
            if remaining_gb <= 0:
                await query.edit_message_text("❌ حجم باقیمانده سرویس صفر است.")
                return
            
            # Calculate expire_days from expiryTime
            expire_days = 0  # 0 means unlimited
            if expire_time and expire_time > 0:
                import time
                current_time_ms = int(time.time() * 1000)
                # Handle both milliseconds (3x-ui) and seconds (Marzban) format
                if expire_time > 1000000000000:  # Milliseconds
                    remaining_ms = expire_time - current_time_ms
                else:  # Seconds
                    remaining_ms = (expire_time * 1000) - current_time_ms
                
                if remaining_ms > 0:
                    expire_days = max(1, int(remaining_ms / (1000 * 60 * 60 * 24)))
            
            # Get destination panel manager
            dest_panel_manager = self.admin_manager.get_panel_manager(new_panel_id)
            if not dest_panel_manager or not dest_panel_manager.login():
                await query.edit_message_text("❌ خطا در اتصال به پنل مقصد.")
                return
            
            # Verify inbound exists in destination panel
            dest_inbounds = dest_panel_manager.get_inbounds()
            dest_inbound = None
            for inbound in dest_inbounds:
                if inbound.get('id') == new_inbound_id:
                    dest_inbound = inbound
                    break
            
            if not dest_inbound:
                await query.edit_message_text("❌ اینباند مقصد در پنل یافت نشد.")
                return
            
            # Get protocol from destination inbound
            protocol = dest_inbound.get('protocol', service_row.get('protocol', 'vless'))
            
            # Step 1: Create new client in destination panel/inbound with same expiry
            client_name = service_row.get('client_name', f"user_{user_id}")
            new_client = dest_panel_manager.create_client(
                inbound_id=new_inbound_id,
                client_name=client_name,
                protocol=protocol,
                expire_days=expire_days,  # Preserve expiry time
                total_gb=remaining_gb
            )
            
            if not new_client:
                await query.edit_message_text("❌ خطا در ایجاد کلاینت در مقصد.")
                return
            
            new_client_uuid = new_client.get('id') or new_client.get('uuid')
            new_sub_id = new_client.get('sub_id') or new_client.get('subId')
            
            logger.info(f"📋 New client created - UUID: {new_client_uuid[:8]}..., sub_id: {new_sub_id}")
            
            # Get new subscription link from destination panel (NOT direct config)
            new_subscription_link = ""
            try:
                panel_type = new_panel.get('panel_type', '3x-ui')
                subscription_url = new_panel.get('subscription_url', '')
                
                logger.info(f"🔗 Panel type: {panel_type}, subscription_url: {subscription_url}")
                
                if panel_type in ['marzban', 'rebecca']:
                    # For Marzban and Rebecca, get subscription link from panel API
                    new_subscription_link = dest_panel_manager.get_client_config_link(
                        new_inbound_id,
                        new_client_uuid,
                        protocol
                    )
                    # Marzban/Rebecca returns subscription link directly
                    if not new_subscription_link and new_client.get('subscription_url'):
                        new_subscription_link = new_client.get('subscription_url')
                else:
                    # For 3x-ui, ALWAYS construct subscription link from subscription_url + sub_id
                    # NEVER use get_client_config_link (it returns direct config, not subscription)
                    if new_sub_id and subscription_url:
                        if subscription_url.endswith('/sub') or subscription_url.endswith('/sub/'):
                            sub_url = subscription_url.rstrip('/')
                            new_subscription_link = f"{sub_url}/{new_sub_id}"
                        elif '/sub' in subscription_url:
                            new_subscription_link = f"{subscription_url}/{new_sub_id}"
                        else:
                            new_subscription_link = f"{subscription_url}/sub/{new_sub_id}"
                        
                        logger.info(f"✅ Constructed subscription link: {new_subscription_link[:50]}...")
                    else:
                        logger.warning(f"⚠️ Cannot construct subscription link - sub_id: {new_sub_id}, subscription_url: {subscription_url}")
                    
            except Exception as e:
                logger.error(f"Error getting new subscription link: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Continue even if subscription link fails - we can get it later
            
            # Step 2: Delete client from source panel
            delete_success = source_panel_manager.delete_client(
                service_row['inbound_id'],
                service_row['client_uuid']
            )
            
            if not delete_success:
                # If deletion failed, try to delete the new client to rollback
                try:
                    dest_panel_manager.delete_client(new_inbound_id, new_client_uuid)
                except:
                    pass
                await query.edit_message_text("❌ خطا در حذف کلاینت از مبدا. عملیات لغو شد.")
                return
            
            # Step 3: Update service in database with new panel/inbound info and subscription link
            update_success = self.db.update_service_panel(
                service_id=service_id,
                new_panel_id=new_panel_id,
                new_inbound_id=new_inbound_id,
                new_client_uuid=new_client_uuid,
                new_total_gb=remaining_gb,
                config_link=new_subscription_link if new_subscription_link else None,
                sub_id=new_sub_id if new_sub_id else None
            )
            
            if not update_success:
                await query.edit_message_text("❌ خطا در به‌روزرسانی اطلاعات سرویس در دیتابیس.")
                return
            
            # Success! Show success message with option to view updated service
            keyboard = [
                [InlineKeyboardButton("🔧 مشاهده سرویس به‌روزرسانی شده", callback_data=f"manage_service_{service_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            is_panel_change = new_panel_id != service_row['panel_id']
            change_type = "پنل/اینباند" if is_panel_change else "اینباند"
            inbound_name = inbound_info.get('inbound_name', f'Inbound {new_inbound_id}')
            destination_text = f"{new_panel['name']} - {inbound_name}" if is_panel_change else inbound_name
            
            message = f"""
✅ **تغییر {change_type} با موفقیت انجام شد!**

📊 **اطلاعات جدید:**
   • پنل جدید: {new_panel['name']}
   • اینباند جدید: {inbound_name}
   • حجم سرویس: {remaining_gb:.2f} گیگابایت
   • شناسه کلاینت: {new_client_uuid[:8]}...

💡 **تغییرات انجام شده:**
   ✅ کلاینت از {service_row['panel_name']} حذف شد
   ✅ کلاینت جدید در {destination_text} ایجاد شد
   ✅ لینک کانفیگ/subscription به‌روزرسانی شد
   ✅ حجم سرویس به {remaining_gb:.2f} گیگابایت تنظیم شد

🔗 لینک کانفیگ و subscription شما اکنون مربوط به مقصد جدید است.

برای مشاهده اطلاعات کامل سرویس، دکمه زیر را بزنید.
            """
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            # Report panel/inbound change to channel
            if self.reporting_system:
                try:
                    # Get inbound names
                    old_inbound_name = None
                    new_inbound_name = None
                    
                    # Get old inbound name
                    try:
                        source_panel_manager = self.admin_manager.get_panel_manager(service_row['panel_id'])
                        if source_panel_manager and source_panel_manager.login():
                            old_inbounds = source_panel_manager.get_inbounds()
                            for inbound in old_inbounds:
                                if inbound.get('id') == service_row.get('inbound_id'):
                                    old_inbound_name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound.get('id')}"
                                    break
                    except:
                        pass
                    
                    # Get new inbound name
                    try:
                        dest_panel_manager = self.admin_manager.get_panel_manager(new_panel_id)
                        if dest_panel_manager and dest_panel_manager.login():
                            new_inbounds = dest_panel_manager.get_inbounds()
                            for inbound in new_inbounds:
                                if inbound.get('id') == new_inbound_id:
                                    new_inbound_name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound.get('id')}"
                                    break
                    except:
                        pass
                    
                    service_data = {
                        'service_name': service_row.get('client_name', 'سرویس'),
                        'old_panel_name': service_row.get('panel_name', 'نامشخص'),
                        'new_panel_name': new_panel.get('name', 'نامشخص'),
                        'remaining_gb': remaining_gb,
                        'old_panel_id': service_row['panel_id'],
                        'new_panel_id': new_panel_id,
                        'old_inbound_name': old_inbound_name,
                        'new_inbound_name': new_inbound_name
                    }
                    await self.reporting_system.report_panel_change(user, service_data)
                except Exception as e:
                    logger.error(f"Failed to send panel change report: {e}")
            
        except Exception as e:
            logger.error(f"Error in handle_confirm_change_inbound: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در انجام عملیات تغییر اینباند.")
    
    async def handle_account_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account balance display"""
        query = update.callback_query
        if query:
            await query.answer()
        
        try:
            # Get user balance
            user_id = update.effective_user.id
            balance = self.db.get_user_balance(user_id)
            
            message = (
                f"💰 موجودی حساب شما\n\n"
                f"💵 موجودی فعلی: {balance:,} تومان\n\n"
                f"برای افزایش موجودی، روی دکمه 'افزودن موجودی' کلیک کنید."
            )
            
            reply_markup = ButtonLayout.create_balance_management_buttons()
            
            if query:
                await query.edit_message_text(message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling account balance: {e}")
            error_text = "❌ خطا در نمایش موجودی حساب."
            if query:
                await query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
    
    async def handle_payment_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle payment history display - shows all gateway transactions"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get all transactions (invoices + balance transactions)
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
            
            # Get invoices (service purchases)
            cursor.execute('''
                SELECT 'service' as type, i.amount, i.gb_amount, i.status, i.created_at, i.paid_at, p.name as panel_name
                FROM invoices i
                LEFT JOIN panels p ON i.panel_id = p.id
                    WHERE i.user_id = %s AND (i.status = 'paid' OR i.payment_method = 'gateway')
                ORDER BY i.created_at DESC
                LIMIT 10
            ''', (user['id'],))
            
            service_transactions = cursor.fetchall()
            
            # Get balance transactions (top-ups)
            cursor.execute('''
                SELECT 'balance' as type, amount, transaction_type, description, created_at
                FROM balance_transactions
                    WHERE user_id = %s AND transaction_type = 'credit'
                ORDER BY created_at DESC
                LIMIT 10
            ''', (user['id'],))
            
            balance_transactions = cursor.fetchall()
                # Connection closed automatically
            
            # Combine and sort all transactions
            all_transactions = []
            
            for tx in service_transactions:
                all_transactions.append({
                    'type': 'خرید سرویس',
                    'amount': tx[1],
                    'detail': f"{tx[2]} گیگابایت - {tx[6] if tx[6] else 'نامشخص'}",
                    'status': 'پرداخت شده' if tx[3] == 'paid' else 'در انتظار',
                    'date': tx[5] if tx[5] else tx[4],
                    'emoji': '🛒'
                })
            
            for tx in balance_transactions:
                all_transactions.append({
                    'type': 'افزایش موجودی',
                    'amount': tx[1],
                    'detail': tx[3] if tx[3] else 'درگاه بانکی',
                    'status': 'موفق',
                    'date': tx[4],
                    'emoji': '💰'
                })
            
            # Sort by date (newest first)
            all_transactions.sort(key=lambda x: x['date'], reverse=True)
            all_transactions = all_transactions[:10]  # Limit to 10 most recent
            
            if not all_transactions:
                message = """
📋 **تاریخچه تراکنش‌ها**

🔍 **هیچ تراکنشی یافت نشد**

شما هنوز هیچ تراکنشی انجام نداده‌اید.
                """
            else:
                message = f"""
📋 **تاریخچه تراکنش‌ها**

📊 **آخرین {len(all_transactions)} تراکنش:**

"""
                
                for i, tx in enumerate(all_transactions, 1):
                    status_emoji = "✅" if tx['status'] in ['پرداخت شده', 'موفق'] else "⏳"
                    message += f"""
{i}. {tx['emoji']} **{tx['type']}**
   💰 مبلغ: {tx['amount']:,} تومان
   📝 جزئیات: {tx['detail']}
   📅 تاریخ: {tx['date']}
   {status_emoji} وضعیت: {tx['status']}

"""
            
            # Add back button
            reply_markup = ButtonLayout.create_back_button("account_balance")
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling payment history: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ خطا در نمایش تاریخچه تراکنش‌ها.")
    
    async def handle_add_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle add balance menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            message = "💰 **افزودن موجودی**\n\nلطفاً مبلغ مورد نظر خود را انتخاب کنید:"
            
            reply_markup = ButtonLayout.create_balance_suggestions()
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling add balance: {e}")
            await query.edit_message_text("❌ خطا در نمایش منوی افزودن موجودی.")
    
    async def handle_custom_balance_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle custom balance amount input"""
        query = update.callback_query
        await query.answer()
        
        message = """
💰 **مبلغ دلخواه**

لطفاً مبلغ مورد نظر خود را وارد کنید:
• حداقل: 10,000 تومان
• حداکثر: 2,000,000 تومان

مثال: 50000
        """
        
        keyboard = [
            [InlineKeyboardButton("◀️ بازگشت", callback_data="add_balance")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Store flag for text processing
        context.user_data['waiting_for_custom_balance'] = True
    
    async def handle_custom_volume_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int):
        """Handle custom volume amount input"""
        query = update.callback_query
        await query.answer()
        
        message = """
📊 **حجم دلخواه**

لطفاً حجم مورد نظر خود را وارد کنید:
• حداقل: 1 گیگابایت
• حداکثر: 10,000 گیگابایت

⚠️ **نکته مهم:**
خرید حجم زیر 10 گیگابایت فقط از طریق موجودی حساب امکان‌پذیر است.

مثال: 50
        """
        
        keyboard = [
            [InlineKeyboardButton("◀️ بازگشت", callback_data=f"select_panel_{panel_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Store panel_id in context for text processing
        context.user_data['waiting_for_custom_volume'] = True
        context.user_data['custom_volume_panel_id'] = panel_id
    
    async def handle_volume_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int):
        """Handle predefined volume selection"""
        query = update.callback_query
        await query.answer()
        
        # Get panel to retrieve actual price
        panel = self.db.get_panel(panel_id)
        if not panel:
            await query.edit_message_text("❌ پنل یافت نشد.")
            return
        
        # Calculate price using panel's price_per_gb
        price_per_gb = panel.get('price_per_gb', 1000) or 1000
        price = volume_gb * price_per_gb
        
        # Clear any previously applied discount code when volume changes
        # (discount was calculated for the old volume/price)
        context.user_data.pop('applied_discount_code', None)
        context.user_data.pop('discount_amount', None)
        context.user_data.pop('original_amount', None)
        context.user_data.pop('final_amount', None)
        
        # Check if amount is below 10 GB (gateway restriction)
        if volume_gb < 10:
            # Force balance payment for small amounts
            await self.handle_small_volume_purchase(update, context, panel_id, volume_gb, price)
        else:
            # Show payment options
            await self.handle_volume_purchase_options(update, context, panel_id, volume_gb, price)
    
    async def handle_balance_amount_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
        """Handle predefined balance amount selection"""
        query = update.callback_query
        await query.answer()
        
        # Process the balance addition
        await self.handle_add_balance_amount(update, context, amount)
    
    async def handle_custom_balance_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle custom balance amount text input"""
        try:
            amount = int(text.strip())
            
            # Validate range
            if amount < 10000 or amount > 2000000:
                await update.message.reply_text(
                    "❌ مبلغ وارد شده نامعتبر است.\n"
                    "لطفاً مبلغی بین 10,000 تا 2,000,000 تومان وارد کنید:"
                )
                return
            
            # Process the balance addition
            await self.handle_add_balance_amount(update, context, amount)
            
            # Clear context
            context.user_data.pop('waiting_for_custom_balance', None)
            
        except ValueError:
            await update.message.reply_text(
                "❌ لطفاً یک عدد معتبر وارد کنید.\n"
                "مثال: 50000"
            )
        except Exception as e:
            logger.error(f"Error handling custom balance input: {e}")
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
    
    async def handle_custom_volume_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle custom volume amount text input"""
        try:
            volume_gb = int(text.strip())
            
            # Validate range
            if volume_gb < 1 or volume_gb > 10000:
                await update.message.reply_text(
                    "❌ حجم وارد شده نامعتبر است.\n"
                    "لطفاً عددی بین 1 تا 10,000 وارد کنید:"
                )
                return
            
            panel_id = context.user_data.get('custom_volume_panel_id')
            service_id = context.user_data.get('add_volume_service_id')
            
            # Get panel to retrieve actual price
            panel = self.db.get_panel(panel_id)
            if not panel:
                await update.message.reply_text("❌ پنل یافت نشد.")
                return
            
            # Calculate price using panel's price_per_gb
            price_per_gb = panel.get('price_per_gb', 1000) or 1000
            price = volume_gb * price_per_gb
            
            # Clear any previously applied discount code when volume changes
            # (discount was calculated for the old volume/price)
            context.user_data.pop('applied_discount_code', None)
            context.user_data.pop('discount_amount', None)
            context.user_data.pop('original_amount', None)
            context.user_data.pop('final_amount', None)
            
            # Check if this is for adding volume to existing service
            if service_id:
                # Show add volume payment options
                await self.handle_add_volume_purchase_options(update, context, service_id, panel_id, volume_gb, price)
            else:
                # Show payment options for new purchase
                await self.handle_volume_purchase_options_from_message(update, context, panel_id, volume_gb, price)
            
            # Clear context
            context.user_data.pop('waiting_for_custom_volume', None)
            context.user_data.pop('custom_volume_panel_id', None)
            context.user_data.pop('add_volume_service_id', None)
            
        except ValueError:
            await update.message.reply_text(
                "❌ لطفاً یک عدد معتبر وارد کنید.\n"
                "مثال: 50"
            )
        except Exception as e:
            logger.error(f"Error handling custom volume input: {e}")
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
    
    async def handle_volume_purchase_options_from_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int, price: int):
        """Handle volume purchase options from text message input"""
        try:
            user_id = update.message.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            # Get panel info
            panel = self.db.get_panel(panel_id)
            panel_name = panel['name'] if panel else "نامشخص"
            
            # Check if discount is already applied
            applied_discount_code = context.user_data.get('applied_discount_code')
            discount_amount = context.user_data.get('discount_amount', 0)
            original_amount = context.user_data.get('original_amount', price)
            final_price = original_amount - discount_amount if discount_amount > 0 else price
            
            # Has enough balance - show payment options
            message = f"""
  📦 **انتخاب روش پرداخت**


📊 **مشخصات بسته:**
   • حجم: {volume_gb} گیگابایت
   • سرور: {panel_name}
   • قیمت: {final_price:,} تومان"""
            
            if discount_amount > 0:
                message += f"\n   🎁 کد تخفیف: {applied_discount_code}\n   💵 مبلغ تخفیف: {discount_amount:,} تومان\n   📌 قیمت اصلی: {original_amount:,} تومان"
            
            message += f"""

💰 **موجودی شما:** {user['balance']:,} تومان


💡 **روش پرداخت خود را انتخاب کنید**
            """
            
            keyboard = []
            
            # Add discount code button
            keyboard.append([InlineKeyboardButton(
                "🏷️ وارد کردن کد تخفیف/هدیه",
                callback_data=f"enter_discount_code_volume_{panel_id}_{volume_gb}_{price}"
            )])
            
            keyboard.append([InlineKeyboardButton("💰 پرداخت از موجودی", callback_data=f"pay_balance_volume_{panel_id}_{volume_gb}_{final_price}")])
            
            # Add gateway option if price >= 10,000 Toman
            if final_price >= 10000:
                keyboard.append([InlineKeyboardButton("💳 پرداخت آنلاین", callback_data=f"pay_gateway_volume_{panel_id}_{volume_gb}_{final_price}")])
            
            keyboard.extend([
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"select_panel_{panel_id}")],
                [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling volume purchase from message: {e}")
            await update.message.reply_text("❌ خطا در پردازش درخواست.")
    
    async def handle_small_volume_purchase(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int, price: int):
        """Handle small volume purchase (balance only) - from callback query - Show confirmation"""
        query = update.callback_query
        user_id = query.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            await query.edit_message_text("❌ کاربر یافت نشد.")
            return
        
        # Get panel info for display
        panel = self.db.get_panel(panel_id)
        panel_name = panel['name'] if panel else "نامشخص"
        
        if user['balance'] < price:
            # Insufficient balance
            shortage = price - user['balance']
            
            message = f"""

  💳 **موجودی ناکافی**


❌ **متأسفانه موجودی حساب شما کافی نیست**

📊 **جزئیات خرید:**
   • بسته انتخابی: {volume_gb} گیگابایت
   • سرور: {panel_name}
   • قیمت: {price:,} تومان

💰 **وضعیت مالی:**
   • موجودی فعلی: {user['balance']:,} تومان
   • کمبود موجودی: {shortage:,} تومان
   • حداقل شارژ مورد نیاز: {shortage:,} تومان


💡 **راهنمایی:**
برای خرید این بسته، ابتدا حساب کاربری خود را شارژ کنید.
            """
            
            keyboard = [
                [InlineKeyboardButton("💳 شارژ حساب", callback_data="add_balance")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"select_panel_{panel_id}")],
                [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Has enough balance - Show confirmation with payment button
        message = f"""

  📦 **تأیید خرید**


📊 **مشخصات بسته:**
   • حجم: {volume_gb} گیگابایت
   • سرور: {panel_name}
   • قیمت: {price:,} تومان

💰 **وضعیت مالی:**
   • موجودی فعلی: {user['balance']:,} تومان
   • موجودی پس از خرید: {user['balance'] - price:,} تومان


⚠️ **توجه:** این بسته زیر 10 گیگابایت است و فقط با موجودی حساب قابل خرید است.
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و پرداخت از موجودی", callback_data=f"pay_balance_volume_{panel_id}_{volume_gb}_{price}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"select_panel_{panel_id}")],
            [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_volume_purchase_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int, price: int):
        """Handle volume purchase payment options"""
        # Support both callback_query and message
        if update.callback_query:
            query = update.callback_query
            user_id = query.from_user.id
            edit_message = query.edit_message_text
        elif update.message:
            user_id = update.message.from_user.id
            edit_message = None  # Will use reply_text
        else:
            user_id = update.effective_user.id
            edit_message = None
        
        user = self.db.get_user(user_id)
        
        if not user:
            if edit_message:
                await edit_message("❌ کاربر یافت نشد.")
            else:
                await update.message.reply_text("❌ کاربر یافت نشد.")
            return
        
        # Check if discount is already applied
        applied_discount_code = context.user_data.get('applied_discount_code')
        discount_amount = context.user_data.get('discount_amount', 0)
        original_amount = context.user_data.get('original_amount', price)
        final_price = original_amount - discount_amount if discount_amount > 0 else price
        
        # Build message with discount info if applicable
        message = f"""
📊 **جزئیات خرید**

📦 **حجم:** {volume_gb} گیگابایت
💰 **قیمت:** {final_price:,} تومان"""
        
        if discount_amount > 0:
            message += f"\n🎁 **کد تخفیف:** {applied_discount_code}\n💵 **مبلغ تخفیف:** {discount_amount:,} تومان\n📌 **قیمت اصلی:** {original_amount:,} تومان"
        
        message += f"\n👤 **موجودی فعلی:** {user['balance']:,} تومان\n\n💳 **روش پرداخت:**"
        
        keyboard = []
        
        # Add discount code button
        keyboard.append([InlineKeyboardButton(
            "🏷️ وارد کردن کد تخفیف/هدیه",
            callback_data=f"enter_discount_code_volume_{panel_id}_{volume_gb}_{price}"
        )])
        
        # Balance payment option
        if user['balance'] >= final_price:
            keyboard.append([InlineKeyboardButton(
                f"💰 پرداخت از موجودی ({final_price:,} تومان)",
                callback_data=f"pay_balance_volume_{panel_id}_{volume_gb}_{final_price}"
            )])
        
        # Gateway payment option (minimum 10,000 Toman)
        if final_price >= 10000:
            keyboard.append([InlineKeyboardButton(
                f"💳 پرداخت آنلاین ({final_price:,} تومان)",
                callback_data=f"pay_gateway_volume_{panel_id}_{volume_gb}_{final_price}"
            )])
        
        keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data=f"select_panel_{panel_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if edit_message:
            await edit_message(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def create_client_from_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int, price: int, discount_code: str = None):
        """Create client from volume amount"""
        try:
            user_id = update.effective_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                logger.error(f"User {user_id} not found")
                return {'success': False, 'subscription_link': None}
            
            # Get panel details
            panel = self.db.get_panel(panel_id)
            if not panel:
                logger.error(f"Panel {panel_id} not found")
                return {'success': False, 'subscription_link': None}
            
            # Generate client name
            client_name = UsernameFormatter.format_client_name(
                user_id, 
                user.get('username'), 
                user.get('first_name'),
                "VPN"
            )
            
            # Check if this is a test account purchase with configured inbound
            test_account_inbound_id = None
            test_account_panel_id = None
            if context:
                test_account_inbound_id = context.user_data.get('test_account_inbound_id')
                test_account_panel_id = context.user_data.get('test_account_panel_id')
            
            # If this is a test account purchase with configured panel and inbound, use specific inbound
            if test_account_panel_id == panel_id and test_account_inbound_id:
                logger.info(f"Creating test account client {client_name} with {volume_gb}GB on specific inbound {test_account_inbound_id} of panel {panel_id}")
                success, message, client_data = self.admin_manager.create_client_on_panel(
                    panel_id=panel_id,
                    inbound_id=test_account_inbound_id,
                    client_name=client_name,
                    expire_days=0,  # Unlimited
                    total_gb=volume_gb
                )
                # Clear test account context after use
                if context:
                    context.user_data.pop('test_account_inbound_id', None)
                    context.user_data.pop('test_account_panel_id', None)
            else:
                # Create client on all inbounds of panel with shared subscription ID (default behavior)
                logger.info(f"Creating client {client_name} with {volume_gb}GB on all inbounds of panel {panel_id}")
                success, message, client_data = self.admin_manager.create_client_on_all_panel_inbounds(
                    panel_id=panel_id,
                    client_name=client_name,
                    expire_days=0,  # Unlimited
                    total_gb=volume_gb
                )
            
            logger.info(f"Client creation result: success={success}, message={message}")
            
            if success and client_data:
                # Get subscription link
                subscription_link = client_data.get('subscription_link') or client_data.get('config_link') or client_data.get('subscription_url')
                
                # If still empty, try to construct it from panel subscription_url
                if not subscription_link and client_data.get('sub_id'):
                    sub_url = panel.get('subscription_url', '')
                    if sub_url:
                        # Clean up sub_url
                        if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                            base_url = sub_url.rstrip('/')
                            subscription_link = f"{base_url}/{client_data['sub_id']}"
                        elif '/sub' in sub_url:
                            subscription_link = f"{sub_url}/{client_data['sub_id']}"
                        else:
                            subscription_link = f"{sub_url}/sub/{client_data['sub_id']}"
                        
                        logger.info(f"✅ Constructed subscription link: {subscription_link}")
                
                # Use configured inbound_id for test account, otherwise use from client_data
                inbound_id_to_save = test_account_inbound_id if (test_account_panel_id == panel_id and test_account_inbound_id) else client_data.get('inbound_id', 1)
                
                # Save to database
                client_id = self.db.add_client(
                    user_id=user['id'],
                    panel_id=panel_id,
                    client_name=client_name,
                    client_uuid=client_data.get('id', ''),
                    inbound_id=inbound_id_to_save,
                    protocol=client_data.get('protocol', 'vless'),
                    expire_days=0,  # Unlimited
                    total_gb=volume_gb,
                    sub_id=client_data.get('sub_id')  # Save sub_id to database
                )
                
                # Get discount info if applied
                discount_amount = context.user_data.get('discount_amount', 0) if context else 0
                original_amount = context.user_data.get('original_amount', price) if context else price
                
                # Get discount code ID if code provided
                discount_code_id = None
                if discount_code:
                    discount_code_obj = self.db.get_discount_code(discount_code)
                    if discount_code_obj:
                        discount_code_id = discount_code_obj['id']
                
                # Create invoice record with discount info
                invoice_id = self.db.add_invoice(
                    user_id=user['id'],
                    panel_id=panel_id,
                    gb_amount=volume_gb,
                    amount=price,
                    payment_method='balance',
                    status='completed',
                    discount_code_id=discount_code_id,
                    discount_amount=discount_amount,
                    original_amount=original_amount if discount_amount > 0 else None
                )
                
                # Report service purchase
                if self.reporting_system:
                    service_data = {
                        'service_name': client_name,
                        'data_amount': volume_gb,
                        'amount': price,
                        'panel_name': panel['name'],
                        'purchase_type': 'gigabyte',
                        'payment_method': 'balance'
                    }
                    await self.reporting_system.report_service_purchased(user, service_data)
                
                logger.info(f"Successfully created client {client_name} with {volume_gb}GB on {client_data.get('created_on_inbounds', 0)} inbounds")
                return {
                    'success': True, 
                    'subscription_link': subscription_link,
                    'client_uuid': client_data.get('id', ''),
                    'inbound_id': inbound_id_to_save,
                    'protocol': client_data.get('protocol', 'vless')
                }
            else:
                logger.error(f"Failed to create client: {message}")
                return {'success': False, 'subscription_link': None}
                
        except Exception as e:
            logger.error(f"Error creating client from volume: {e}")
            return {'success': False, 'subscription_link': None}
    
    async def handle_balance_volume_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int, price: int):
        """Handle balance payment for volume purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get discount info if applied
            applied_discount_code = context.user_data.get('applied_discount_code')
            discount_amount = context.user_data.get('discount_amount', 0)
            original_amount = context.user_data.get('original_amount', price)
            final_price = original_amount - discount_amount if discount_amount > 0 else price
            
            if user['balance'] < final_price:
                await query.edit_message_text(
                    f"❌ موجودی کافی نیست.\n"
                    f"موجودی شما: {user['balance']:,} تومان\n"
                    f"مبلغ مورد نیاز: {final_price:,} تومان"
                )
                return
            
            # Deduct from balance
            old_balance = user['balance']
            new_balance = user['balance'] - final_price
            self.db.update_user_balance(user_id, -final_price, 'service_purchase', f'خرید اشتراک {volume_gb} گیگ')
            
            # Record discount usage if applied
            if applied_discount_code and discount_amount > 0:
                from discount_manager import DiscountCodeManager
                discount_manager = DiscountCodeManager(self.db)
                discount_code_obj = discount_manager.db.get_discount_code(applied_discount_code)
                if discount_code_obj:
                    discount_manager.db.apply_discount_code(
                        discount_code_obj['id'], user_id, None, original_amount, discount_amount, final_price
                    )
            
            # Get panel info for display
            panel = self.db.get_panel(panel_id)
            panel_name = panel['name'] if panel else "نامشخص"
            
            # Create service with final price
            result = await self.create_client_from_volume(update, context, panel_id, volume_gb, final_price, applied_discount_code)
            
            if result.get('success'):
                # Add subscription link if available
                sub_link = result.get('subscription_link')
                
                # Fallback: If link is missing, try to fetch it from the panel
                if not sub_link:
                    try:
                        client_uuid = result.get('client_uuid')
                        inbound_id = result.get('inbound_id')
                        protocol = result.get('protocol', 'vless')
                        
                        if client_uuid:
                            # Initialize panel manager
                            pm = self.admin_manager.get_panel_manager(panel_id)
                            if pm and pm.login():
                                # If inbound_id is missing, try 0 or 1
                                target_inbound = inbound_id if inbound_id is not None else 1
                                sub_link = pm.get_client_config_link(target_inbound, client_uuid, protocol)
                    except Exception as e:
                        logger.error(f"Error fetching missing subscription link in balance payment: {e}")

                config_message = f"\n\n🔧 **کانفیگ VPN:**\n`{sub_link}`" if sub_link else ""
                
                discount_message = ""
                if discount_amount > 0:
                    discount_message = f"\n🎁 **کد تخفیف:** {applied_discount_code}\n💵 **مبلغ تخفیف:** {discount_amount:,} تومان\n📌 **قیمت اصلی:** {original_amount:,} تومان\n"
                
                message = f"""
✅ **پرداخت با موفقیت انجام شد!**

🔗 **پنل:** {panel_name}
📊 **حجم:** {volume_gb} گیگابایت{discount_message}💰 **مبلغ پرداخت شده:** {final_price:,} تومان

سرویس شما آماده است و می‌توانید از پنل کاربری آن را دریافت کنید.{config_message}
                """
                
                keyboard = [
                    [InlineKeyboardButton("📋 پنل کاربری", callback_data="user_panel")],
                    [InlineKeyboardButton("🛒 خرید جدید", callback_data="buy_service")],
                    [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # Clear discount info
                context.user_data.pop('applied_discount_code', None)
                context.user_data.pop('discount_amount', None)
                context.user_data.pop('original_amount', None)
                context.user_data.pop('final_amount', None)
            else:
                # Refund the amount if service creation failed
                self.db.update_user_balance(user_id, final_price, 'refund', f'بازگشت مبلغ - خطا در ایجاد سرویس {volume_gb} گیگ')
                
                message = f"""

  ❌ **خطا در ایجاد سرویس**


⚠️ **متأسفانه خطایی در ایجاد سرویس رخ داد**

💰 **اطلاعات مالی:**
   • مبلغ بازگشت داده شد: {final_price:,} تومان
   • موجودی فعلی: {old_balance:,} تومان


💡 **راهنمایی:** لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید
                """
                
                keyboard = [
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=f"select_panel_{panel_id}")],
                    [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error handling balance volume payment: {e}")
            await query.edit_message_text("❌ خطا در پردازش پرداخت.")
    
    async def handle_gateway_volume_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, panel_id: int, volume_gb: int, price: int):
        """Handle gateway payment for volume purchase"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            
            # Get discount info if applied
            applied_discount_code = context.user_data.get('applied_discount_code')
            discount_amount = context.user_data.get('discount_amount', 0)
            original_amount = context.user_data.get('original_amount', price)
            final_price = original_amount - discount_amount if discount_amount > 0 else price
            
            # Create payment link for volume purchase with discount
            payment_result = self.payment_manager.create_volume_payment(user_id, panel_id, volume_gb, final_price, applied_discount_code)
            
            if payment_result['success']:
                discount_message = ""
                if discount_amount > 0:
                    discount_message = f"\n🎁 **کد تخفیف:** {applied_discount_code}\n💵 **مبلغ تخفیف:** {discount_amount:,} تومان\n📌 **قیمت اصلی:** {original_amount:,} تومان\n"
                
                message = (
                    f"📊 **خرید حجم**\n\n"
                    f"📦 **حجم:** {volume_gb} گیگابایت{discount_message}"
                    f"💰 **قیمت:** {final_price:,} تومان\n\n"
                    f"برای تکمیل پرداخت روی دکمه زیر کلیک کنید:"
                )
                
                keyboard = [
                    [InlineKeyboardButton("💳 پرداخت آنلاین", url=payment_result['payment_link'])],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data=f"select_panel_{panel_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await query.edit_message_text(f"❌ {payment_result['message']}")
                
        except Exception as e:
            logger.error(f"Error handling gateway volume payment: {e}")
            await query.edit_message_text("❌ خطا در ایجاد لینک پرداخت.")
    
    async def handle_add_volume(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int):
        """Handle add volume request - show volume selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if user is admin
            is_admin = self.db.is_admin(user_id) or user_id == self.bot_config['admin_id']
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                if is_admin:
                    # Admin can see any service
                    cursor.execute('''
                        SELECT c.id, c.panel_id, c.total_gb, c.used_gb, c.client_name, p.name as panel_name, 
                               p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s
                    ''', (service_id,))
                else:
                    # Regular users can only see their own services
                    cursor.execute('''
                        SELECT c.id, c.panel_id, c.total_gb, c.used_gb, c.client_name, p.name as panel_name, 
                               p.price_per_gb
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.id = %s AND c.user_id = %s
                    ''', (service_id, user['id']))
                service_row = cursor.fetchone()
            
            if not service_row:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            service = {
                'id': service_row['id'],
                'panel_id': service_row['panel_id'],
                'total_gb': service_row['total_gb'] or 0,
                'used_gb': service_row['used_gb'] or 0,
                'client_name': service_row['client_name'],
                'panel_name': service_row['panel_name'] or 'نامشخص',
                'price_per_gb': service_row['price_per_gb'] or 0
            }
            
            # Calculate remaining volume
            remaining_gb = service['total_gb'] - service['used_gb']
            
            message = f"""
➕ **افزایش حجم سرویس**

🔗 **پنل:** {escape_markdown(service['panel_name'], version=1)}
🆔 **نام سرویس:** {escape_markdown(service['client_name'], version=1)}
📊 **حجم فعلی:** {service['total_gb']} گیگابایت
📈 **مصرف شده:** {service['used_gb']:.2f} گیگابایت
📉 **باقیمانده:** {remaining_gb:.2f} گیگابایت
💰 **نرخ:** {service['price_per_gb']:,} تومان به ازای هر گیگابایت

📦 حجم مورد نظر خود را انتخاب کنید:
            """
            
            # Create volume selection buttons with service_id
            from button_layout import ButtonLayout
            reply_markup = ButtonLayout.create_add_volume_plans(service['panel_id'], service_id)
            
            # Check if message has media
            is_media_message = query.message.photo or query.message.video or query.message.document
            
            if is_media_message:
                try:
                    await query.message.delete()
                except:
                    pass
                await query.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error handling add volume: {e}", exc_info=True)
            await query.edit_message_text("❌ خطا در نمایش گزینه‌های افزایش حجم.")
    
    async def handle_add_volume_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, panel_id: int, volume_gb: int):
        """Handle volume selection for adding to existing service"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get panel to retrieve actual price
            panel = self.db.get_panel(panel_id)
            if not panel:
                await query.edit_message_text("❌ پنل یافت نشد.")
                return
            
            # Calculate price using panel's price_per_gb
            price_per_gb = panel.get('price_per_gb', 1000) or 1000
            price = volume_gb * price_per_gb
            
            # Clear any previously applied discount code when volume changes
            # (discount was calculated for the old volume/price)
            context.user_data.pop('applied_discount_code', None)
            context.user_data.pop('discount_amount', None)
            context.user_data.pop('original_amount', None)
            context.user_data.pop('final_amount', None)
            
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Check if amount is below 10 GB (gateway restriction)
            if volume_gb < 10:
                # Force balance payment for small amounts
                await self.handle_add_volume_purchase_options(update, context, service_id, panel_id, volume_gb, price, force_balance=True)
            else:
                # Show payment options
                await self.handle_add_volume_purchase_options(update, context, service_id, panel_id, volume_gb, price)
                
        except Exception as e:
            logger.error(f"Error handling add volume selection: {e}", exc_info=True)
            await query.edit_message_text("❌ خطا در پردازش انتخاب حجم.")
    
    async def handle_add_volume_purchase_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, panel_id: int, volume_gb: int, price: int, force_balance: bool = False):
        """Handle add volume purchase payment options"""
        # Support both callback_query and message
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            user_id = query.from_user.id
            edit_message = query.edit_message_text
        elif update.message:
            user_id = update.message.from_user.id
            edit_message = None  # Will use reply_text
        else:
            user_id = update.effective_user.id
            edit_message = None
        
        try:
            user = self.db.get_user(user_id)
            
            if not user:
                if edit_message:
                    await edit_message("❌ کاربر یافت نشد.")
                else:
                    await update.message.reply_text("❌ کاربر یافت نشد.")
                return
            
            # Get discount info if applied
            applied_discount_code = context.user_data.get('applied_discount_code')
            discount_amount = context.user_data.get('discount_amount', 0)
            original_amount = context.user_data.get('original_amount', price)
            final_price = original_amount - discount_amount if discount_amount > 0 else price
            
            # Build message
            message = f"""
📊 **جزئیات افزایش حجم**

📦 **حجم اضافه:** {volume_gb} گیگابایت
💰 **قیمت:** {final_price:,} تومان"""
            
            if discount_amount > 0:
                message += f"\n🎁 **کد تخفیف:** {applied_discount_code}\n💵 **مبلغ تخفیف:** {discount_amount:,} تومان\n📌 **قیمت اصلی:** {original_amount:,} تومان"
            
            message += f"\n👤 **موجودی فعلی:** {user['balance']:,} تومان\n\n💳 **روش پرداخت:**"
            
            keyboard = []
            
            # Add discount code button
            keyboard.append([InlineKeyboardButton(
                "🏷️ وارد کردن کد تخفیف/هدیه",
                callback_data=f"enter_discount_code_add_volume_{service_id}_{panel_id}_{volume_gb}_{price}"
            )])
            
            # Balance payment option
            if user['balance'] >= final_price:
                keyboard.append([InlineKeyboardButton(
                    f"💰 پرداخت از موجودی ({final_price:,} تومان)",
                    callback_data=f"pay_balance_add_volume_{service_id}_{panel_id}_{volume_gb}_{final_price}"
                )])
            
            # Gateway payment option (minimum 10,000 Toman and not forced to balance)
            if not force_balance and final_price >= 10000:
                keyboard.append([InlineKeyboardButton(
                    f"💳 پرداخت آنلاین ({final_price:,} تومان)",
                    callback_data=f"pay_gateway_add_volume_{service_id}_{panel_id}_{volume_gb}_{final_price}"
                )])
            elif force_balance:
                message += "\n\n⚠️ برای حجم کمتر از 10 گیگابایت، فقط پرداخت از موجودی امکان‌پذیر است."
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data=f"add_volume_{service_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if edit_message:
                await edit_message(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error handling add volume purchase options: {e}", exc_info=True)
            if edit_message:
                await edit_message("❌ خطا در نمایش گزینه‌های پرداخت.")
            else:
                await update.message.reply_text("❌ خطا در نمایش گزینه‌های پرداخت.")
    
    async def handle_balance_add_volume_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, panel_id: int, volume_gb: int, price: int):
        """Handle balance payment for adding volume to existing service"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            user = self.db.get_user(user_id)
            
            if not user:
                await query.edit_message_text("❌ کاربر یافت نشد.")
                return
            
            # Get discount info if applied
            applied_discount_code = context.user_data.get('applied_discount_code')
            discount_amount = context.user_data.get('discount_amount', 0)
            original_amount = context.user_data.get('original_amount', price)
            final_price = original_amount - discount_amount if discount_amount > 0 else price
            
            if user['balance'] < final_price:
                await query.edit_message_text(
                    f"❌ موجودی کافی نیست.\n"
                    f"موجودی شما: {user['balance']:,} تومان\n"
                    f"مبلغ مورد نیاز: {final_price:,} تومان"
                )
                return
            
            # Get service details
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT id, inbound_id, client_uuid, total_gb, panel_id
                    FROM clients 
                    WHERE id = %s AND user_id = %s
                ''', (service_id, user['id']))
                service = cursor.fetchone()
            
            if not service:
                await query.edit_message_text("❌ سرویس یافت نشد.")
                return
            
            # Calculate new total GB
            current_total_gb = service.get('total_gb', 0) or 0
            new_total_gb = current_total_gb + volume_gb
            
            # Update volume in panel
            # Get appropriate panel manager
            pm = self.admin_manager.get_panel_manager(panel_id)
            if not pm:
                logger.error(f"Could not get panel manager for panel {panel_id}")
                await query.edit_message_text("❌ خطا در اتصال به پنل.")
                return

            result = pm.update_client_traffic(
                service['inbound_id'],
                service['client_uuid'],
                new_total_gb
            )
            
            if result:
                # Update database
                with self.db.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute('''
                        UPDATE clients 
                        SET total_gb = %s,
                            status = 'active',
                            is_active = 1,
                            notified_70_percent = 0,
                            notified_80_percent = 0,
                            exhausted_at = NULL
                        WHERE id = %s
                    ''', (new_total_gb, service_id))
                    conn.commit()
                
                # Deduct balance
                self.db.update_user_balance(
                    telegram_id=user_id,
                    amount=-final_price,
                    transaction_type='volume_purchase',
                    description=f'افزایش حجم {volume_gb}GB'
                )
                
                # Report volume addition to channel
                try:
                    if self.reporting_system:
                        panel = self.db.get_panel(panel_id)
                        volume_data = {
                            'service_name': service.get('client_name', 'سرویس'),
                            'volume_added': volume_gb,
                            'old_volume': current_total_gb,
                            'new_volume': new_total_gb,
                            'amount': final_price,
                            'panel_name': panel.get('name', 'نامشخص') if panel else 'نامشخص',
                            'payment_method': 'balance'
                        }
                        await self.reporting_system.report_volume_added(user, volume_data)
                except Exception as e:
                    logger.error(f"Failed to send volume addition report: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                
                # Record discount usage if applied
                if applied_discount_code and discount_amount > 0:
                    from discount_manager import DiscountCodeManager
                    discount_manager = DiscountCodeManager(self.db)
                    discount_code_obj = discount_manager.db.get_discount_code(applied_discount_code)
                    if discount_code_obj:
                        discount_manager.db.apply_discount_code(
                            discount_code_obj['id'], user_id, None, original_amount, discount_amount, final_price
                        )
                
                discount_message = ""
                if discount_amount > 0:
                    discount_message = f"\n🎁 **کد تخفیف:** {applied_discount_code}\n💵 **مبلغ تخفیف:** {discount_amount:,} تومان\n📌 **قیمت اصلی:** {original_amount:,} تومان\n"
                
                message = f"""
✅ **حجم با موفقیت اضافه شد!**

📊 **حجم اضافه شده:** {volume_gb} گیگابایت
📈 **حجم کل جدید:** {new_total_gb} گیگابایت{discount_message}💰 **مبلغ پرداخت شده:** {final_price:,} تومان

سرویس شما به‌روزرسانی شد و آماده استفاده است.
                """
                
                keyboard = [
                    [InlineKeyboardButton("🔧 مدیریت سرویس", callback_data=f"manage_service_{service_id}")],
                    [InlineKeyboardButton("📋 پنل کاربری", callback_data="user_panel")],
                    [InlineKeyboardButton("🏠 منو", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # Clear discount info
                context.user_data.pop('applied_discount_code', None)
                context.user_data.pop('discount_amount', None)
                context.user_data.pop('original_amount', None)
            else:
                await query.edit_message_text("❌ خطا در افزایش حجم. لطفاً دوباره تلاش کنید.")
                
        except Exception as e:
            logger.error(f"Error handling balance add volume payment: {e}", exc_info=True)
            await query.edit_message_text("❌ خطا در پردازش پرداخت.")
    
    async def handle_gateway_add_volume_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, service_id: int, panel_id: int, volume_gb: int, price: int):
        """Handle gateway payment for adding volume to existing service"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = query.from_user.id
            
            # Get discount info if applied
            applied_discount_code = context.user_data.get('applied_discount_code')
            discount_amount = context.user_data.get('discount_amount', 0)
            original_amount = context.user_data.get('original_amount', price)
            final_price = original_amount - discount_amount if discount_amount > 0 else price
            
            # Store service_id in context for payment callback
            context.user_data['add_volume_service_id'] = service_id
            context.user_data['add_volume_panel_id'] = panel_id
            context.user_data['add_volume_gb'] = volume_gb
            
            # Create payment link for adding volume
            payment_result = self.payment_manager.create_add_volume_payment(user_id, service_id, panel_id, volume_gb, final_price, applied_discount_code)
            
            if payment_result['success']:
                discount_message = ""
                if discount_amount > 0:
                    discount_message = f"\n🎁 **کد تخفیف:** {applied_discount_code}\n💵 **مبلغ تخفیف:** {discount_amount:,} تومان\n📌 **قیمت اصلی:** {original_amount:,} تومان\n"
                
                message = (
                    f"➕ **افزایش حجم سرویس**\n\n"
                    f"📦 **حجم اضافه:** {volume_gb} گیگابایت{discount_message}"
                    f"💰 **قیمت:** {final_price:,} تومان\n\n"
                    f"برای تکمیل پرداخت روی دکمه زیر کلیک کنید:"
                )
                
                keyboard = [
                    [InlineKeyboardButton("💳 پرداخت آنلاین", url=payment_result['payment_link'])],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data=f"add_volume_{service_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await query.edit_message_text(f"❌ {payment_result['message']}")
                
        except Exception as e:
            logger.error(f"Error handling gateway add volume payment: {e}", exc_info=True)
            await query.edit_message_text("❌ خطا در ایجاد لینک پرداخت.")
    
    # ==================== STATISTICS HANDLERS ====================
    
    async def handle_admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin statistics main menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_statistics_main_menu()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling admin stats: {e}")
            await query.edit_message_text("❌ خطا در نمایش آمار.")
    
    async def handle_stats_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user statistics"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_user_statistics()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling stats users: {e}")
            await query.edit_message_text("❌ خطا در نمایش آمار کاربران.")
    
    async def handle_stats_all_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated all users list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_all_users_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling all users list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست کاربران.")
    
    async def handle_stats_active_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated active users list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_active_users_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling active users list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست کاربران فعال.")
    
    async def handle_stats_services(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle services statistics"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_services_statistics()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling stats services: {e}")
            await query.edit_message_text("❌ خطا در نمایش آمار سرویس‌ها.")
    
    async def handle_stats_all_services(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated all services list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_all_services_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling all services list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست سرویس‌ها.")
    
    async def handle_stats_active_services(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated active services list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_active_services_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling active services list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست سرویس‌های فعال.")
    
    async def handle_stats_disabled_services(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated disabled services list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_disabled_services_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling disabled services list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست سرویس‌های غیرفعال.")
    
    async def handle_stats_payments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle payments statistics"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_payment_statistics()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling stats payments: {e}")
            await query.edit_message_text("❌ خطا در نمایش آمار پرداختی‌ها.")
    
    async def handle_stats_recent_payments(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated recent payments list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_recent_payments_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling recent payments list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست تراکنش‌ها.")
    
    async def handle_stats_revenue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle revenue statistics"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_revenue_statistics()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling stats revenue: {e}")
            await query.edit_message_text("❌ خطا در نمایش آمار درآمد.")
    
    async def handle_stats_recent_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated recent orders list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_recent_orders_list(page)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling recent orders list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست سفارشات.")
    
    async def handle_stats_online(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle online services statistics"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = await self.statistics_system.get_online_services()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling stats online: {e}")
            await query.edit_message_text("❌ خطا در نمایش سرویس‌های آنلاین.")
    
    async def handle_stats_lists(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle management lists menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            message, reply_markup = self.statistics_system.get_lists_menu()
            await query.edit_message_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling stats lists: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست‌ها.")
    
    async def handle_stats_new_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
        """Handle paginated new users list"""
        query = update.callback_query
        await query.answer()
        
        try:
            if not self.statistics_system:
                await query.edit_message_text("❌ سیستم آمار در دسترس نیست.")
                return
            
            # Get all users ordered by created_at
            all_users = self.db.get_all_users()
            # Get only new users (created within last 30 days)
            new_users = [u for u in all_users if u.get('created_at') and 
                        self.statistics_system._is_recent_date(u['created_at'], days=30)]
            
            # Pagination
            items_per_page = 10
            total_pages = (len(new_users) + items_per_page - 1) // items_per_page
            start_idx = (page - 1) * items_per_page
            end_idx = start_idx + items_per_page
            
            users_page = new_users[start_idx:end_idx]
            
            # Create buttons
            keyboard = []
            for user in users_page:
                user_id = user.get('telegram_id', 'N/A')
                username = user.get('username', 'بدون نام کاربری')
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"👤 {username} ({user_id})",
                        callback_data=f"user_detail_{user_id}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_new_users_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_new_users_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_users")])
            
            message = f"""🆕 **آخرین ثبت نام‌ها**

📊 **صفحه:** `{page}/{total_pages}`
👥 **کل ثبت نام‌های ۳۰ روز گذشته:** `{len(new_users):,} نفر`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling new users list: {e}")
            await query.edit_message_text("❌ خطا در نمایش لیست کاربران جدید.")
    
    # Discount Code Management Methods
    async def handle_admin_discount_codes_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show discount codes management menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            from discount_manager import DiscountCodeAdmin
            admin = DiscountCodeAdmin(self.db)
            
            discount_codes = admin.get_all_discount_codes()
            gift_codes = admin.get_all_gift_codes()
            
            active_discount = sum(1 for code in discount_codes if code.get('is_active'))
            active_gift = sum(1 for code in gift_codes if code.get('is_active'))
            
            message = f"""
🏷️ **مدیریت کدهای تخفیف و هدیه**

📊 **آمار کلی:**
• کدهای تخفیف: {len(discount_codes)} ({active_discount} فعال)
• کدهای هدیه: {len(gift_codes)} ({active_gift} فعال)

لطفاً گزینه مورد نظر را انتخاب کنید:
            """
            
            keyboard = [
                [InlineKeyboardButton("🏷️ کدهای تخفیف", callback_data="admin_discount_codes_list"), InlineKeyboardButton("🎁 کدهای هدیه", callback_data="admin_gift_codes_list")],
                [InlineKeyboardButton("➕ ایجاد کد تخفیف", callback_data="discount_create_percentage"), InlineKeyboardButton("➕ ایجاد کد هدیه", callback_data="gift_create_amount")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing discount codes menu: {e}")
            await query.edit_message_text("❌ خطا در نمایش منوی کدهای تخفیف.")
    
    async def handle_admin_discount_codes_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of discount codes"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            from discount_manager import DiscountCodeAdmin
            admin = DiscountCodeAdmin(self.db)
            
            codes = admin.get_all_discount_codes()
            
            if not codes:
                message = "📭 هیچ کد تخفیفی وجود ندارد.\n\nبرای ایجاد کد تخفیف جدید از دکمه زیر استفاده کنید:"
                keyboard = [
                    [InlineKeyboardButton("➕ ایجاد کد تخفیف", callback_data="discount_create_percentage")]
                ]
            else:
                message = f"🏷️ **لیست کدهای تخفیف**\n\n📊 تعداد کل: {len(codes)}\n\nبرای مشاهده جزئیات و مدیریت هر کد، روی دکمه مربوطه کلیک کنید:"
                keyboard = []
                
                for code in codes[:20]:  # Show first 20
                    status_icon = "✅" if code.get('is_active') else "❌"
                    discount_type_icon = "📊" if code.get('discount_type') == 'percentage' else "💰"
                    discount_value = code.get('discount_value', 0)
                    
                    if code.get('discount_type') == 'percentage':
                        discount_text = f"{discount_value}%"
                    else:
                        discount_text = f"{int(discount_value):,}ت"
                    
                    button_text = f"{status_icon} {code.get('code')} - {discount_type_icon} {discount_text}"
                    
                    # Truncate button text if too long (max 64 chars for Telegram)
                    if len(button_text) > 60:
                        button_text = button_text[:57] + "..."
                    
                    keyboard.append([
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"discount_view_{code['id']}"
                        )
                    ])
                
                keyboard.append([InlineKeyboardButton("➕ ایجاد کد جدید", callback_data="discount_create_percentage")])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_discount_codes")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing discount codes list: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در نمایش لیست کدهای تخفیف.")
    
    async def handle_view_discount_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_id: int):
        """View details of a discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            code = self.db.get_discount_code_by_id(code_id)
            if not code:
                await query.edit_message_text("❌ کد تخفیف یافت نشد.")
                return
            
            from discount_manager import DiscountCodeAdmin
            admin = DiscountCodeAdmin(self.db)
            stats = admin.get_discount_code_stats(code_id)
            
            status = "✅ فعال" if code.get('is_active') else "❌ غیرفعال"
            discount_type = "درصدی" if code.get('discount_type') == 'percentage' else "مبلغ ثابت"
            discount_value = code.get('discount_value', 0)
            
            if code.get('discount_type') == 'percentage':
                discount_text = f"{discount_value}%"
            else:
                discount_text = f"{int(discount_value):,} تومان"
            
            max_discount = code.get('max_discount_amount') or 'نامحدود'
            max_uses = code.get('max_uses', 0) if code.get('max_uses', 0) > 0 else '∞'
            
            message = f"""
🏷️ **جزئیات کد تخفیف**

**کد:** `{code.get('code')}`
**نوع:** {discount_type}
**مقدار:** {discount_text}
**وضعیت:** {status}

**محدودیت‌ها:**
• حداقل خرید: {code.get('min_purchase_amount', 0):,} تومان
• حداکثر تخفیف: {max_discount if isinstance(max_discount, str) else f'{max_discount:,} تومان'}
• تعداد استفاده: {code.get('used_count', 0)}/{max_uses}

**آمار:**
• تعداد استفاده: {stats.get('total_uses', 0) or 0}
• کاربران منحصر به فرد: {stats.get('unique_users', 0) or 0}
• کل تخفیف داده شده: {stats.get('total_discount', 0) or 0:,} تومان
• کل درآمد: {stats.get('total_revenue', 0) or 0:,} تومان
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("❌ حذف", callback_data=f"discount_delete_{code_id}"),
                    InlineKeyboardButton("🔄 تغییر وضعیت", callback_data=f"discount_toggle_{code_id}")
                ],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_discount_codes_list")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error viewing discount code: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در نمایش جزئیات کد تخفیف.")
    
    async def handle_create_discount_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_type: str):
        """Start creating a discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            context.user_data['creating_discount_code'] = True
            context.user_data['discount_code_type'] = code_type
            context.user_data['discount_code_step'] = 'code'
            
            message = """
➕ **ایجاد کد تخفیف جدید**

لطفاً کد تخفیف را وارد کنید (فقط حروف و اعداد، بدون فاصله):

مثال: `WELCOME2024` یا `DISCOUNT50`
            """
            
            keyboard = [[InlineKeyboardButton("❌ انصراف", callback_data="admin_discount_codes")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error starting discount code creation: {e}")
            await query.edit_message_text("❌ خطا در شروع ایجاد کد تخفیف.")
    
    async def handle_delete_discount_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_id: int):
        """Delete a discount code"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            code = self.db.get_discount_code_by_id(code_id)
            if not code:
                await query.edit_message_text("❌ کد تخفیف یافت نشد.")
                return
            
            if self.db.delete_discount_code(code_id):
                await query.edit_message_text(f"✅ کد تخفیف '{code.get('code')}' با موفقیت حذف شد.")
            else:
                await query.edit_message_text("❌ خطا در حذف کد تخفیف.")
                
        except Exception as e:
            logger.error(f"Error deleting discount code: {e}")
            await query.edit_message_text("❌ خطا در حذف کد تخفیف.")
    
    async def handle_toggle_discount_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_id: int):
        """Toggle discount code active status"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            code = self.db.get_discount_code_by_id(code_id)
            if not code:
                await query.edit_message_text("❌ کد تخفیف یافت نشد.")
                return
            
            new_status = not code.get('is_active', True)
            if self.db.update_discount_code(code_id, is_active=new_status):
                status_text = "فعال" if new_status else "غیرفعال"
                await query.edit_message_text(f"✅ کد تخفیف '{code.get('code')}' {status_text} شد.")
            else:
                await query.edit_message_text("❌ خطا در تغییر وضعیت کد تخفیف.")
                
        except Exception as e:
            logger.error(f"Error toggling discount code: {e}")
            await query.edit_message_text("❌ خطا در تغییر وضعیت کد تخفیف.")
    
    async def handle_admin_gift_codes_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of gift codes"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            from discount_manager import DiscountCodeAdmin
            admin = DiscountCodeAdmin(self.db)
            
            codes = admin.get_all_gift_codes()
            
            if not codes:
                message = "📭 هیچ کد هدیه‌ای وجود ندارد.\n\nبرای ایجاد کد هدیه جدید از دکمه زیر استفاده کنید:"
                keyboard = [
                    [InlineKeyboardButton("➕ ایجاد کد هدیه", callback_data="gift_create_amount")]
                ]
            else:
                message = f"🎁 **لیست کدهای هدیه**\n\n📊 تعداد کل: {len(codes)}\n\nبرای مشاهده جزئیات و مدیریت هر کد، روی دکمه مربوطه کلیک کنید:"
                keyboard = []
                
                for code in codes[:20]:  # Show first 20
                    status_icon = "✅" if code.get('is_active') else "❌"
                    amount = code.get('amount', 0)
                    
                    button_text = f"{status_icon} {code.get('code')} - 💰 {amount:,}ت"
                    
                    # Truncate button text if too long (max 64 chars for Telegram)
                    if len(button_text) > 60:
                        button_text = button_text[:57] + "..."
                    
                    keyboard.append([
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"gift_view_{code['id']}"
                        )
                    ])
                
                keyboard.append([InlineKeyboardButton("➕ ایجاد کد جدید", callback_data="gift_create_amount")])
            
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_discount_codes")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing gift codes list: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.edit_message_text("❌ خطا در نمایش لیست کدهای هدیه.")
    
    async def handle_view_gift_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_id: int):
        """View details of a gift code"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            code = self.db.get_gift_code_by_id(code_id)
            if not code:
                await query.edit_message_text("❌ کد هدیه یافت نشد.")
                return
            
            from discount_manager import DiscountCodeAdmin
            admin = DiscountCodeAdmin(self.db)
            stats = admin.get_gift_code_stats(code_id)
            
            status = "✅ فعال" if code.get('is_active') else "❌ غیرفعال"
            amount = code.get('amount', 0)
            max_uses = code.get('max_uses', 0) if code.get('max_uses', 0) > 0 else '∞'
            
            message = f"""
🎁 **جزئیات کد هدیه**

**کد:** `{code.get('code')}`
**مبلغ:** {amount:,} تومان
**وضعیت:** {status}

**محدودیت‌ها:**
• تعداد استفاده: {code.get('used_count', 0)}/{max_uses}

**آمار:**
• تعداد استفاده: {stats.get('total_uses', 0) or 0}
• کاربران منحصر به فرد: {stats.get('unique_users', 0) or 0}
• کل مبلغ داده شده: {stats.get('total_amount', 0) or 0:,} تومان
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("❌ حذف", callback_data=f"gift_delete_{code_id}"),
                    InlineKeyboardButton("🔄 تغییر وضعیت", callback_data=f"gift_toggle_{code_id}")
                ],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_gift_codes_list")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error viewing gift code: {e}")
            await query.edit_message_text("❌ خطا در نمایش جزئیات کد هدیه.")
    
    async def handle_create_gift_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, step: str):
        """Start creating a gift code"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            context.user_data['creating_gift_code'] = True
            context.user_data['gift_code_step'] = 'code'
            
            message = """
➕ **ایجاد کد هدیه جدید**

لطفاً کد هدیه را وارد کنید (فقط حروف و اعداد، بدون فاصله):

مثال: `GIFT2024` یا `BONUS50`
            """
            
            keyboard = [[InlineKeyboardButton("❌ انصراف", callback_data="admin_discount_codes")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error starting gift code creation: {e}")
            await query.edit_message_text("❌ خطا در شروع ایجاد کد هدیه.")
    
    async def handle_delete_gift_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_id: int):
        """Delete a gift code"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            code = self.db.get_gift_code_by_id(code_id)
            if not code:
                await query.edit_message_text("❌ کد هدیه یافت نشد.")
                return
            
            if self.db.delete_gift_code(code_id):
                await query.edit_message_text(f"✅ کد هدیه '{code.get('code')}' با موفقیت حذف شد.")
            else:
                await query.edit_message_text("❌ خطا در حذف کد هدیه.")
                
        except Exception as e:
            logger.error(f"Error deleting gift code: {e}")
            await query.edit_message_text("❌ خطا در حذف کد هدیه.")
    
    async def handle_toggle_gift_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code_id: int):
        """Toggle gift code active status"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            code = self.db.get_gift_code_by_id(code_id)
            if not code:
                await query.edit_message_text("❌ کد هدیه یافت نشد.")
                return
            
            new_status = not code.get('is_active', True)
            if self.db.update_gift_code(code_id, is_active=new_status):
                status_text = "فعال" if new_status else "غیرفعال"
                await query.edit_message_text(f"✅ کد هدیه '{code.get('code')}' {status_text} شد.")
            else:
                await query.edit_message_text("❌ خطا در تغییر وضعیت کد هدیه.")
                
        except Exception as e:
            logger.error(f"Error toggling gift code: {e}")
            await query.edit_message_text("❌ خطا در تغییر وضعیت کد هدیه.")
    
    async def handle_create_discount_code_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle discount code creation flow"""
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await update.message.reply_text("❌ دسترسی غیرمجاز.")
                context.user_data.clear()
                return
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                context.user_data.clear()
                return
            
            # Get current step
            step = context.user_data.get('discount_code_step', 'code')
            
            if step == 'code':
                # Validate code format
                code = text.strip().upper()
                if not code.isalnum() or len(code) < 3:
                    await update.message.reply_text("❌ کد تخفیف باید حداقل 3 کاراکتر و فقط حروف و اعداد باشد. لطفاً دوباره وارد کنید:")
                    return
                
                # Check if code already exists
                existing = self.db.get_discount_code(code)
                if existing:
                    await update.message.reply_text(f"❌ کد تخفیف '{code}' از قبل وجود دارد. لطفاً کد دیگری وارد کنید:")
                    return
                
                context.user_data['discount_code'] = code
                context.user_data['discount_code_step'] = 'type'
                
                await update.message.reply_text(f"""
✅ کد تخفیف '{code}' ثبت شد.

**مرحله بعد:** نوع تخفیف را انتخاب کنید:

1️⃣ درصدی (مثال: 20% تخفیف)
2️⃣ مبلغ ثابت (مثال: 5000 تومان تخفیف)

لطفاً عدد 1 یا 2 را وارد کنید:
                """, parse_mode='Markdown')
                
            elif step == 'type':
                if text not in ['1', '2']:
                    await update.message.reply_text("❌ لطفاً فقط عدد 1 یا 2 را وارد کنید:")
                    return
                
                discount_type = 'percentage' if text == '1' else 'fixed'
                context.user_data['discount_type'] = discount_type
                context.user_data['discount_code_step'] = 'value'
                
                type_text = "درصدی" if discount_type == 'percentage' else "مبلغ ثابت"
                await update.message.reply_text(f"""
✅ نوع تخفیف: {type_text}

**مرحله بعد:** مقدار تخفیف را وارد کنید:

{"اگر درصدی است، عدد بین 1 تا 100 را وارد کنید (مثال: 20 برای 20%)" if discount_type == 'percentage' else "مبلغ تخفیف را به تومان وارد کنید (مثال: 5000)"}
                """)
                
            elif step == 'value':
                try:
                    value = float(text)
                    if context.user_data.get('discount_type') == 'percentage':
                        if value < 1 or value > 100:
                            await update.message.reply_text("❌ درصد باید بین 1 تا 100 باشد. لطفاً دوباره وارد کنید:")
                            return
                    else:
                        if value < 1:
                            await update.message.reply_text("❌ مبلغ باید بیشتر از 0 باشد. لطفاً دوباره وارد کنید:")
                            return
                    
                    context.user_data['discount_value'] = value
                    
                    # Create discount code with default values
                    user_db = self.db.get_user(user_id)
                    code_id = self.db.create_discount_code(
                        code=context.user_data['discount_code'],
                        discount_type=context.user_data['discount_type'],
                        discount_value=value,
                        created_by=user_db['id'] if user_db else None
                    )
                    
                    if code_id:
                        await update.message.reply_text(f"""
✅ کد تخفیف '{context.user_data['discount_code']}' با موفقیت ایجاد شد!

🏷️ **کد:** `{context.user_data['discount_code']}`
{"📊 مقدار:** " + str(value) + "%" if context.user_data['discount_type'] == 'percentage' else "💰 مبلغ:** " + str(int(value)) + " تومان"}
**وضعیت:** ✅ فعال

برای مدیریت کدهای تخفیف از پنل مدیریت استفاده کنید.
                        """, parse_mode='Markdown')
                    else:
                        await update.message.reply_text("❌ خطا در ایجاد کد تخفیف.")
                    
                    context.user_data.clear()
                    
                except ValueError:
                    await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")
                    
        except Exception as e:
            logger.error(f"Error in discount code creation flow: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text("❌ خطا در ایجاد کد تخفیف.")
            context.user_data.clear()
    
    async def handle_create_gift_code_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle gift code creation flow"""
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await update.message.reply_text("❌ دسترسی غیرمجاز.")
                context.user_data.clear()
                return
            
            if text.lower() == '/cancel':
                await update.message.reply_text("❌ عملیات لغو شد.")
                context.user_data.clear()
                return
            
            # Get current step
            step = context.user_data.get('gift_code_step', 'code')
            
            if step == 'code':
                # Validate code format
                code = text.strip().upper()
                if not code.isalnum() or len(code) < 3:
                    await update.message.reply_text("❌ کد هدیه باید حداقل 3 کاراکتر و فقط حروف و اعداد باشد. لطفاً دوباره وارد کنید:")
                    return
                
                # Check if code already exists
                existing = self.db.get_gift_code(code)
                if existing:
                    await update.message.reply_text(f"❌ کد هدیه '{code}' از قبل وجود دارد. لطفاً کد دیگری وارد کنید:")
                    return
                
                context.user_data['gift_code'] = code
                context.user_data['gift_code_step'] = 'amount'
                
                await update.message.reply_text(f"""
✅ کد هدیه '{code}' ثبت شد.

**مرحله بعد:** مبلغ هدیه را به تومان وارد کنید:

مثال: `10000` برای 10,000 تومان
                """, parse_mode='Markdown')
                
            elif step == 'amount':
                try:
                    amount = int(text)
                    if amount < 1:
                        await update.message.reply_text("❌ مبلغ باید بیشتر از 0 باشد. لطفاً دوباره وارد کنید:")
                        return
                    
                    # Create gift code
                    user_db = self.db.get_user(user_id)
                    code_id = self.db.create_gift_code(
                        code=context.user_data['gift_code'],
                        amount=amount,
                        created_by=user_db['id'] if user_db else None
                    )
                    
                    if code_id:
                        await update.message.reply_text(f"""
✅ کد هدیه '{context.user_data['gift_code']}' با موفقیت ایجاد شد!

🎁 **کد:** `{context.user_data['gift_code']}`
💰 **مبلغ:** {amount:,} تومان
**وضعیت:** ✅ فعال

برای مدیریت کدهای هدیه از پنل مدیریت استفاده کنید.
                        """, parse_mode='Markdown')
                    else:
                        await update.message.reply_text("❌ خطا در ایجاد کد هدیه.")
                    
                    context.user_data.clear()
                    
                except ValueError:
                    await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")
                    
        except Exception as e:
            logger.error(f"Error in gift code creation flow: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text("❌ خطا در ایجاد کد هدیه.")
            context.user_data.clear()



    async def show_financial_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show financial management menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            message = """
👑 **پنل مدیریت**

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:
            """
            
            reply_markup = ButtonLayout.create_financial_management_menu()
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing financial management: {e}")
            await query.edit_message_text("❌ خطا در نمایش مدیریت مالی.")

    async def show_card_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show card settings menu"""
        query = update.callback_query
        await query.answer()
        
        try:
            user_id = update.effective_user.id
            if not self.db.is_admin(user_id):
                await query.edit_message_text("❌ دسترسی غیرمجاز.")
                return
            
            # Get current card info
            card_number = self.db.get_bot_text('card_number')
            card_owner = self.db.get_bot_text('card_owner')
            
            card_num_text = card_number['text_content'] if card_number else "تعیین نشده"
            card_owner_text = card_owner['text_content'] if card_owner else "تعیین نشده"
            
            message = f"""
💳 **تنظیمات کارت به کارت**

شماره کارت فعلی:
`{card_num_text}`

نام صاحب کارت:
`{card_owner_text}`

برای تغییر هر کدام روی دکمه مربوطه کلیک کنید.
            """
            
            keyboard = [
                [InlineKeyboardButton("✏️ تغییر شماره کارت", callback_data="set_card_number")],
                [InlineKeyboardButton("✏️ تغییر نام صاحب کارت", callback_data="set_card_owner")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="financial_management")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing card settings: {e}")
            await query.edit_message_text("❌ خطا در نمایش تنظیمات کارت.")

    async def prompt_card_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt admin to enter card number"""
        query = update.callback_query
        await query.answer()
        
        context.user_data['awaiting_card_number'] = True
        
        message = """
💳 **تغییر شماره کارت**

لطفاً شماره کارت جدید را وارد کنید (16 رقم):
        """
        
        keyboard = [[InlineKeyboardButton("❌ انصراف", callback_data="card_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def prompt_card_owner(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt admin to enter card owner name"""
        query = update.callback_query
        await query.answer()
        
        context.user_data['awaiting_card_owner'] = True
        
        message = """
👤 **تغییر نام صاحب کارت**

لطفاً نام صاحب کارت را وارد کنید:
        """
        
        keyboard = [[InlineKeyboardButton("❌ انصراف", callback_data="card_settings")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    async def handle_card_settings_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Handle input for card settings"""
        user_id = update.effective_user.id
        
        if context.user_data.get('awaiting_card_number'):
            # Validate card number (simple check)
            if not text.isdigit() or len(text) != 16:
                await update.message.reply_text("❌ شماره کارت باید 16 رقم باشد. لطفاً دوباره تلاش کنید:")
                return
            
            # Save card number
            self.db.create_bot_text(
                text_key='card_number',
                text_category='payment',
                text_content=text,
                description='شماره کارت جهت واریز وجه',
                updated_by=self.db.get_user(user_id)['id']
            )
            
            context.user_data['awaiting_card_number'] = False
            await update.message.reply_text("✅ شماره کارت با موفقیت ذخیره شد.")
            
            # Show settings again
            # We can't easily edit the previous message here, so we send a new one or just let them navigate back
            # Ideally we would show the menu again
            
        elif context.user_data.get('awaiting_card_owner'):
            # Save card owner
            self.db.create_bot_text(
                text_key='card_owner',
                text_category='payment',
                text_content=text,
                description='نام صاحب کارت جهت واریز وجه',
                updated_by=self.db.get_user(user_id)['id']
            )
            
            context.user_data['awaiting_card_owner'] = False
            await update.message.reply_text("✅ نام صاحب کارت با موفقیت ذخیره شد.")

    async def show_card_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: int):
        """Show card payment details and ask for receipt"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get invoice details
            invoice = self.db.get_invoice(invoice_id)
            if not invoice:
                await query.edit_message_text("❌ فاکتور یافت نشد.")
                return
            
            # Get card info
            card_number = self.db.get_bot_text('card_number')
            card_owner = self.db.get_bot_text('card_owner')
            
            if not card_number or not card_owner:
                await query.edit_message_text("❌ اطلاعات کارت تنظیم نشده است. لطفاً با پشتیبانی تماس بگیرید.")
                return
            
            card_num_text = card_number['text_content']
            card_owner_text = card_owner['text_content']
            amount = invoice['amount']
            
            message = f"""
💳 **پرداخت کارت به کارت**

لطفاً مبلغ **{amount:,} تومان** را به شماره کارت زیر واریز نمایید:

💳 شماره کارت:
`{card_num_text}`

👤 به نام: **{card_owner_text}**

⚠️ **نکته مهم:** پس از واریز، لطفاً عکس رسید پرداخت را همینجا ارسال کنید.
            """
            
            context.user_data['awaiting_receipt'] = True
            context.user_data['receipt_invoice_id'] = invoice_id
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"payment_methods_{invoice_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error showing card payment: {e}")
            await query.edit_message_text("❌ خطا در نمایش اطلاعات پرداخت.")

    async def handle_receipt_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle receipt image upload"""
        if not context.user_data.get('awaiting_receipt'):
            return
        
        try:
            photo = update.message.photo[-1]
            file_id = photo.file_id
            invoice_id = context.user_data.get('receipt_invoice_id')
            user = update.effective_user
            
            # Save receipt info (we store file_id for now, or could download it)
            # Ideally we should store it in DB. We added receipt_image column.
            
            # Update invoice status to 'pending_approval' (we might need to add this status if not exists, or use 'pending')
            # For now let's assume 'pending' is fine, but we note it's card payment
            
            # Send to receipts channel
            receipts_channel_id = self.bot_config.get('receipts_channel_id')
            if not receipts_channel_id:
                await update.message.reply_text("❌ خطای سیستم: کانال رسیدها تنظیم نشده است.")
                return
            
            caption = f"""
🧾 **رسید پرداخت جدید**

👤 کاربر: {user.first_name} (ID: {user.id})
💰 مبلغ فاکتور: {self.db.get_invoice(invoice_id)['amount']:,} تومان
🔢 شماره فاکتور: #{invoice_id}

جهت تایید یا رد پرداخت از دکمه‌های زیر استفاده کنید.
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"approve_receipt_{invoice_id}"),
                    InlineKeyboardButton("❌ رد پرداخت", callback_data=f"reject_receipt_{invoice_id}")
                ]
            ]
            
            # Send to channel
            await context.bot.send_photo(
                chat_id=receipts_channel_id,
                photo=file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Update invoice
            # We can store the file_id in receipt_image column
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE invoices SET receipt_image = %s, payment_method = 'card' WHERE id = %s", (file_id, invoice_id))
                conn.commit()
            
            await update.message.reply_text("✅ رسید شما دریافت شد و پس از تایید ادمین، موجودی شما افزایش می‌یابد/سرویس فعال می‌شود.")
            
            # Clear state
            context.user_data['awaiting_receipt'] = False
            context.user_data.pop('receipt_invoice_id', None)
            
        except Exception as e:
            logger.error(f"Error handling receipt upload: {e}")
            await update.message.reply_text("❌ خطا در دریافت رسید. لطفاً دوباره تلاش کنید.")

    async def handle_approve_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: int):
        """Approve a payment receipt"""
        query = update.callback_query
        
        try:
            # invoice_id is passed as argument
            invoice = self.db.get_invoice(invoice_id)
            
            if not invoice:
                await query.answer("❌ فاکتور یافت نشد.", show_alert=True)
                return
            
            if invoice['status'] == 'paid' or invoice['status'] == 'completed':
                await query.answer("⚠️ این فاکتور قبلاً پرداخت شده است.", show_alert=True)
                return
            
            # Process payment
            user_id = invoice['user_id']
            amount = invoice['amount']
            purchase_type = invoice.get('purchase_type', 'balance')
            
            # 1. Update invoice status to paid
            self.db.update_invoice_status(invoice_id, 'paid', payment_method='card', transaction_id=f"card_{invoice_id}")
            
            # 2. Fulfill order
            user = self.db.get_user_by_id(user_id)
            if not user:
                await query.answer("❌ کاربر یافت نشد.", show_alert=True)
                return

            if purchase_type == 'balance':
                # Just add balance
                self.db.update_user_balance(user['telegram_id'], amount, 'deposit', f"شارژ کیف پول (فاکتور #{invoice_id})")
                
                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=user['telegram_id'],
                        text=f"✅ پرداخت شما تایید شد.\n💰 مبلغ {amount:,} تومان به کیف پول شما اضافه شد."
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")
                    
            elif purchase_type in ['service', 'plan']:
                # Create service
                panel_id = invoice['panel_id']
                gb_amount = invoice['gb_amount']
                duration_days = invoice.get('duration_days', 30)
                product_id = invoice.get('product_id')
                
                # Format client name
                from username_formatter import UsernameFormatter
                client_name = UsernameFormatter.format_client_name(user['telegram_id'])
                
                # Create service
                success, message, client_data = self.admin_manager.create_client_on_all_panel_inbounds(
                    panel_id=panel_id,
                    client_name=client_name,
                    expire_days=duration_days,
                    total_gb=gb_amount
                )
                
                if success and client_data:
                    # Save to DB
                    inbounds = self.admin_manager.get_panel_inbounds(panel_id)
                    inbound_id = client_data.get('inbound_id', inbounds[0]['id'] if inbounds else 0)
                    
                    # Calculate expires_at
                    from datetime import datetime, timedelta
                    expires_at = datetime.now() + timedelta(days=duration_days) if duration_days > 0 else None
                    
                    client_id = self.db.add_client(
                        user_id=user_id,
                        panel_id=panel_id,
                        client_name=client_name,
                        client_uuid=client_data.get('id', ''),
                        inbound_id=inbound_id,
                        protocol=client_data.get('protocol', 'vless'),
                        expire_days=duration_days,
                        total_gb=gb_amount,
                        expires_at=expires_at.isoformat() if expires_at else None,
                        product_id=product_id
                    )
                    
                    if client_id > 0:
                        # Update invoice to completed
                        self.db.update_invoice_status(invoice_id, 'completed')
                        
                        # Notify user
                        sub_link = client_data.get('subscription_link') or client_data.get('subscription_url', '')
                        msg = f"""
✅ سرویس شما با موفقیت ایجاد شد!

👤 نام سرویس: `{client_name}`
📊 حجم: {gb_amount} گیگابایت
📅 مدت: {duration_days} روز

🔗 لینک اشتراک:
`{sub_link}`
"""
                        try:
                            await context.bot.send_message(
                                chat_id=user['telegram_id'],
                                text=msg,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id}: {e}")
                    else:
                        await context.bot.send_message(
                            chat_id=user['telegram_id'],
                            text=f"✅ پرداخت تایید شد اما خطا در ذخیره سرویس رخ داد. لطفاً با پشتیبانی تماس بگیرید.\nکد پیگیری: {invoice_id}"
                        )
                else:
                     # Failed to create on panel, but paid. Add to balance instead?
                     self.db.update_user_balance(user['telegram_id'], amount, 'deposit', f"برگشت وجه (خطا در ایجاد سرویس) - فاکتور #{invoice_id}")
                     await context.bot.send_message(
                        chat_id=user['telegram_id'],
                        text=f"✅ پرداخت تایید شد اما ایجاد سرویس با خطا مواجه شد.\n💰 مبلغ {amount:,} تومان به کیف پول شما برگشت داده شد.\nلطفاً مجدداً تلاش کنید."
                    )

            # Report service purchase
            if self.reporting_system:
                try:
                    service_data = {
                        'service_name': client_name,
                        'data_amount': product['volume_gb'] if purchase_type == 'plan' else gb_amount,
                        'amount': invoice['amount'],
                        'panel_name': panel['name'],
                        'purchase_type': 'plan' if purchase_type == 'plan' else 'gigabyte',
                        'payment_method': 'card'
                    }
                    await self.reporting_system.report_service_purchased(user_obj, service_data)
                except Exception as e:
                    logger.error(f"Failed to send service purchase report: {e}")

            # Update message in channel
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n✅ **تایید شد** توسط " + update.effective_user.first_name
            )
            
        except Exception as e:
            logger.error(f"Error approving receipt: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await query.answer("❌ خطا در تایید پرداخت.", show_alert=True)

    async def handle_reject_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: int):
        """Reject a payment receipt"""
        query = update.callback_query
        
        try:
            # invoice_id is passed as argument
            invoice = self.db.get_invoice(invoice_id)
            
            if not invoice:
                await query.answer("❌ فاکتور یافت نشد.", show_alert=True)
                return
                
            user_id = invoice['user_id']
            
            # Notify user
            try:
                user = self.db.get_user_by_id(user_id)
                if user and user.get('telegram_id'):
                    await context.bot.send_message(
                        chat_id=user['telegram_id'],
                        text=f"❌ پرداخت شما به مبلغ {invoice['amount']:,} تومان رد شد.\nدر صورت اشتباه، لطفاً با پشتیبانی تماس بگیرید."
                    )
                else:
                    logger.error(f"Could not notify user {user_id}: Telegram ID not found")
            except Exception as e:
                logger.error(f"Could not send notification to user {user_id}: {e}")
            
            # Update message in channel
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n❌ **رد شد** توسط " + update.effective_user.first_name
            )
            
        except Exception as e:
            logger.error(f"Error rejecting receipt: {e}")
            await query.answer("❌ خطا در رد پرداخت.", show_alert=True)


    async def handle_group_selection_for_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str):
        """Handle group selection for Pasargad panel"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Retrieve panel details from user_data
            panel_name = context.user_data.get('panel_name')
            panel_url = context.user_data.get('panel_url')
            panel_username = context.user_data.get('panel_username')
            panel_password = context.user_data.get('panel_password')
            panel_sub_url = context.user_data.get('panel_subscription_url')
            panel_price = context.user_data.get('panel_price')
            panel_type = context.user_data.get('panel_type')
            
            # Save to database
            extra_config = {'main_group': group_id}
            
            panel_id = self.db.add_panel(
                name=panel_name,
                url=panel_url,
                username=panel_username,
                password=panel_password,
                api_endpoint=panel_url,
                subscription_url=panel_sub_url,
                price_per_gb=panel_price,
                panel_type=panel_type,
                extra_config=extra_config
            )
            
            if panel_id:
                await query.edit_message_text(
                    f"✅ پنل **{panel_name}** با موفقیت اضافه شد!\n\n"
                    f"نوع: {panel_type}\n"
                    f"گروه اصلی: {group_id}",
                    reply_markup=ButtonLayout.create_back_button("manage_panels"),
                    parse_mode='Markdown'
                )
                context.user_data.clear()
            else:
                await query.edit_message_text(
                    "❌ خطا در ذخیره پنل در دیتابیس.",
                    reply_markup=ButtonLayout.create_back_button("manage_panels")
                )
                
        except Exception as e:
            logger.error(f"Error handling group selection: {e}")
            await query.edit_message_text("❌ خطا در پردازش درخواست.")



    async def handle_system_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system settings menu"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await query.edit_message_text("❌ دسترسی غیرمجاز.")
            return
            
        text = """
⚙️ **تنظیمات سیستم**

لطفاً گزینه مورد نظر را انتخاب کنید:

🔄 **آپدیت سیستم:** دریافت آخرین نسخه ربات و وب اپلیکیشن
💾 **بکاپ دیتابیس:** تهیه و ارسال فایل پشتیبان دیتابیس
🧹 **بهینه‌سازی:** بهینه‌سازی جداول و ایندکس‌های دیتابیس
📊 **وضعیت سیستم:** مشاهده منابع مصرفی سرور
🔄 **ریستارت:** راه‌اندازی مجدد سرویس‌ها
        """
        
        reply_markup = ButtonLayout.create_system_settings_menu()
        
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def handle_system_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """Handle system actions"""
        query = update.callback_query
        
        # Check admin
        user_id = update.effective_user.id
        if not self.db.is_admin(user_id):
            await query.answer("❌ دسترسی غیرمجاز.", show_alert=True)
            return

        if not self.system_manager:
            await query.answer("❌ مدیر سیستم فعال نیست.", show_alert=True)
            return

        # Handle actions
        if action == "update":
            await query.answer("⏳ در حال شروع آپدیت...", show_alert=True)
            success, msg = await self.system_manager.update_system()
            if success:
                await query.edit_message_text(msg)
            else:
                await query.message.reply_text(msg)
                
        elif action == "backup":
            await query.answer("⏳ در حال تهیه بکاپ...", show_alert=True)
            await query.edit_message_text("⏳ در حال تهیه و ارسال بکاپ دیتابیس...\nلطفاً صبر کنید.")
            success, msg = await self.system_manager.backup_database()
            # Return to menu
            reply_markup = ButtonLayout.create_back_button("system_settings")
            await query.edit_message_text(msg, reply_markup=reply_markup)
            
        elif action == "optimize":
            await query.answer("⏳ در حال بهینه‌سازی...", show_alert=True)
            await query.edit_message_text("⏳ در حال بهینه‌سازی دیتابیس...")
            success, msg = await self.system_manager.optimize_database()
            reply_markup = ButtonLayout.create_back_button("system_settings")
            await query.edit_message_text(msg, reply_markup=reply_markup)
            
        elif action == "status":
            await query.answer("⏳ دریافت وضعیت...", show_alert=True)
            status_text = await self.system_manager.get_system_status()
            reply_markup = ButtonLayout.create_back_button("system_settings")
            await query.edit_message_text(status_text, reply_markup=reply_markup, parse_mode='Markdown')
            
        elif action == "restart":
            await query.answer("⏳ در حال ریستارت...", show_alert=True)
            success, msg = await self.system_manager.restart_services()
            await query.edit_message_text(msg)
            
        elif action == "logs":
            await query.answer("⏳ دریافت لاگ‌ها...", show_alert=True)
            logs = await self.system_manager.get_system_logs(lines=50)
            
            # Send as file if too long
            if len(logs) > 4000:
                # Create temp file
                import io
                log_file = io.BytesIO(logs.encode('utf-8'))
                log_file.name = "system_logs.txt"
                await context.bot.send_document(
                    chat_id=user_id,
                    document=log_file,
                    caption="📋 لاگ‌های سیستم (50 خط آخر)"
                )
                await query.edit_message_text("✅ فایل لاگ ارسال شد.", reply_markup=ButtonLayout.create_back_button("system_settings"))
            else:
                # Format as code block
                log_text = f"📋 **لاگ‌های سیستم (50 خط آخر):**\n\n```\n{logs}\n```"
                reply_markup = ButtonLayout.create_back_button("system_settings")
                try:
                    await query.edit_message_text(log_text, reply_markup=reply_markup, parse_mode='Markdown')
                except Exception:
                    # Fallback if markdown fails (e.g. special chars)
                    await query.edit_message_text(f"📋 لاگ‌های سیستم:\n\n{logs}", reply_markup=reply_markup)

        else:
            await query.answer("❌ دستور نامعتبر.", show_alert=True)

class NoProxyRequest(HTTPXRequest):
    """Custom request class to disable system proxies"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client_kwargs['trust_env'] = False

def main():
    """Main function to run the bot"""
    # Create bot instance
    bot = VPNBot()
    
    # Initialize reporting system with bot_config
    from telegram import Bot
    
    # Use NoProxyRequest to avoid system proxy issues
    request = NoProxyRequest()
    
    telegram_bot = Bot(token=bot.bot_config['token'], request=request)
    # CRITICAL: Pass bot_config to ReportingSystem to ensure reports go to correct channel
    bot.reporting_system = ReportingSystem(telegram_bot, bot_config=bot.bot_config)
    bot.statistics_system = StatisticsSystem(bot.db, bot.admin_manager)
    bot.system_manager = SystemManager(telegram_bot, bot.db, bot.bot_config)
    
    # Create application
    application = Application.builder().token(BOT_CONFIG['token']).request(request).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("help", bot.help_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("myid", bot.myid_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CallbackQueryHandler(bot.handle_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, bot.handle_text_message))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, bot.handle_receipt_upload))
    
    # Add error handler
    async def error_handler(update, context):
        """Handle errors"""
        logger.error(f"Exception while handling an update: {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
    
    application.add_error_handler(error_handler)
    
    # Add startup handler for reporting
    async def post_init(application):
        """Post initialization tasks"""
        try:
            # Send bot start report
            if bot.reporting_system:
                await bot.reporting_system.report_bot_start()
        except Exception as e:
            logger.error(f"Failed to send bot start report: {e}")
    
    application.post_init = post_init
    
    # Start the bot
    print("🤖 Bot is starting...")
    print(f"📱 Bot username: @{BOT_CONFIG['bot_username']}")
    print(f"👤 Admin ID: {BOT_CONFIG['admin_id']}")
    print(f"🔗 Default Panel URL: {DEFAULT_PANEL_CONFIG['url']}")
    
    # Initialize traffic monitor
    # CRITICAL: Pass bot instance (VPNBot) so TrafficMonitor has access to reporting_system
    # TrafficMonitor will use bot.reporting_system for reports and application.bot for sending messages
    # For single bot mode, we need to set bot on VPNBot instance for TrafficMonitor
    bot.traffic_monitor = TrafficMonitor(bot.db, bot.admin_manager, application.bot)
    # Also set bot_instance on TrafficMonitor so it can access reporting_system
    bot.traffic_monitor.bot_instance = bot
    
    # Start traffic monitoring in background (for notifications and auto-disable)
    def start_traffic_monitoring():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot.traffic_monitor.start_monitoring())
    
    import threading
    traffic_monitoring_thread = threading.Thread(target=start_traffic_monitoring, daemon=True)
    traffic_monitoring_thread.start()
    
    # Start optimized monitoring in background (for database updates every 3 minutes)
    from optimized_monitor import OptimizedMonitor
    optimized_monitor = OptimizedMonitor(bot.db, bot.admin_manager, bot=None)
    
    def start_optimized_monitoring():
        logger.info("🚀 Starting OptimizedMonitor (updates every 10 minutes)")
        try:
            optimized_monitor.start_monitoring(interval_seconds=600)  # 10 minutes = 600 seconds
        except Exception as e:
            logger.error(f"❌ Error in OptimizedMonitor loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    optimized_monitoring_thread = threading.Thread(target=start_optimized_monitoring, daemon=True, name="OptimizedMonitor")
    optimized_monitoring_thread.start()
    logger.info("✅ OptimizedMonitor thread started successfully")
    
    application.run_polling()


if __name__ == '__main__':
    main()
