"""
Professional Reporting System for VPN Bot
Sends comprehensive reports to a designated channel or group with topic support
Supports both channels (single thread) and groups (categorized topics)
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from telegram import Bot
from telegram.error import TelegramError, TimedOut, NetworkError, BadRequest
from persian_datetime import PersianDateTime

logger = logging.getLogger(__name__)

class ReportingSystem:
    """
    Professional reporting system for bot events with topic support
    
    Features:
    - Channel mode: All reports to single channel
    - Group mode: Reports categorized into topics (forums)
    """
    
    # Topic definitions for group mode
    TOPIC_CATEGORIES = {
        'users': {
            'name': '👥 کاربران',
            'icon': '👥',
            'report_types': ['user_registration', 'user_blocked', 'user_unblocked']
        },
        'sales': {
            'name': '🛒 فروش و خرید',
            'icon': '🛒',
            'report_types': ['service_purchased', 'service_renewed', 'volume_added', 'subscription_link_retrieved', 'test_account_created']
        },
        'finance': {
            'name': '💰 مالی',
            'icon': '💰',
            'report_types': ['balance_added', 'balance_recharged', 'payment_failed', 
                           'admin_balance_increase', 'admin_balance_decrease', 
                           'discount_code_used', 'gift_code_used', 'referral_reward']
        },
        'warnings': {
            'name': '⚠️ هشدارها',
            'icon': '⚠️',
            'report_types': ['service_volume_70_percent', 'service_volume_80_percent', 
                           'service_volume_exhausted', 'service_expired', 'service_expiring_soon']
        },
        'deletions': {
            'name': '🗑️ حذف و اتمام',
            'icon': '🗑️',
            'report_types': ['service_deleted', 'service_auto_deleted']
        },
        'panels': {
            'name': '🖥️ پنل‌ها',
            'icon': '🖥️',
            'report_types': ['panel_added', 'panel_deleted', 'panel_connection_failed', 'panel_change']
        },
        'admin': {
            'name': '👨‍💼 فعالیت ادمین',
            'icon': '👨‍💼',
            'report_types': ['admin_view_user_info', 'broadcast_message', 'broadcast_forward', 
                           'backup_created', 'backup_restored']
        },
        'errors': {
            'name': '🚨 خطاها',
            'icon': '🚨',
            'report_types': ['user_error', 'system_error']
        },
        'support': {
            'name': '🎫 پشتیبانی',
            'icon': '🎫',
            'report_types': ['ticket_created', 'ticket_replied', 'ticket_closed']
        },
        'system': {
            'name': '🤖 سیستم',
            'icon': '🤖',
            'report_types': ['bot_start', 'daily_summary', 'weekly_summary']
        }
    }
    
    def __init__(self, bot: Bot, bot_config=None, db_manager=None):
        """
        Initialize ReportingSystem with bot and bot_config
        
        Args:
            bot: Telegram Bot instance
            bot_config: Bot configuration dict
            db_manager: Database manager for storing topic IDs
        """
        self.bot = bot
        self.db_manager = db_manager
        self.topic_ids = {}  # Cache for topic IDs
        self.is_group = False
        self.topics_initialized = False
        
        # Get bot_config
        if bot_config is None:
            try:
                from config import BOT_CONFIG
                bot_config = BOT_CONFIG
                logger.warning("⚠️ ReportingSystem initialized without bot_config - using global BOT_CONFIG")
            except ImportError:
                logger.error("❌ CRITICAL: bot_config is required but not provided!")
                raise ValueError("bot_config is required for ReportingSystem")
        
        self.bot_config = bot_config
        
        # Get channel ID and ensure it's an integer if it looks like one
        raw_channel_id = bot_config.get('reports_channel_id')
        try:
            if isinstance(raw_channel_id, str) and (raw_channel_id.startswith('-') or raw_channel_id.isdigit()):
                self.channel_id = int(raw_channel_id)
            else:
                self.channel_id = raw_channel_id
        except (ValueError, TypeError):
            self.channel_id = raw_channel_id
            
        self.bot_username = bot_config.get('bot_username', 'Unknown')
        
        # Determine bot name with fallback
        self.bot_name = bot_config.get('bot_name')
        if not self.bot_name:
            self.bot_name = self.bot_username if self.bot_username != 'Unknown' else 'VPN Bot'
        
        # Validate channel ID
        if not self.channel_id:
            logger.error(f"❌ CRITICAL: No reports_channel_id found in bot_config for bot '{self.bot_name}'")
            self.enabled = False
        elif str(self.channel_id) == '-1001234567890' or str(self.channel_id) == '0':
            logger.warning(f"⚠️ Invalid reports_channel_id for bot '{self.bot_name}': {self.channel_id}")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"✅ ReportingSystem initialized for bot '{self.bot_name}' with channel ID: {self.channel_id} (Type: {type(self.channel_id)})")
        
        if not self.enabled:
            logger.warning(f"⚠️ Reporting system disabled for bot '{self.bot_name}'")
    
    async def _initialize_topics(self):
        """Initialize topics for group mode"""
        if self.topics_initialized or not self.enabled:
            return
            
        await self.initialize_topics_on_startup()
    
    async def _load_topic_ids(self):
        """Load saved topic IDs from database"""
        if not self.db_manager:
            return
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT setting_key, setting_value 
                    FROM settings 
                    WHERE setting_key LIKE 'report_topic_%'
                """)
                rows = cursor.fetchall()
                
                # Clear current cache to ensure fresh load
                self.topic_ids = {}
                
                for row in rows:
                    category = row['setting_key'].replace('report_topic_', '')
                    try:
                        self.topic_ids[category] = int(row['setting_value'])
                    except:
                        pass
                        
            logger.info(f"📋 Loaded {len(self.topic_ids)} topic IDs from database")
        except Exception as e:
            logger.warning(f"⚠️ Could not load topic IDs: {e}")
    
    async def _save_topic_id(self, category: str, topic_id: int):
        """Save topic ID to database"""
        if not self.db_manager:
            return
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO settings (setting_key, setting_value, setting_type, description)
                    VALUES (%s, %s, 'integer', %s)
                    ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """, (f'report_topic_{category}', str(topic_id), f'Topic ID for {category} reports'))
                conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ Could not save topic ID: {e}")
    
    async def _create_missing_topics(self):
        """Create missing forum topics (legacy method, redirected to verify)"""
        await self._verify_and_create_topics()
        
    async def _verify_and_create_topics(self):
        """Verify existing topics and create missing ones"""
        if not self.enabled or not self.is_group:
            return
            
        logger.info("🔍 Verifying reporting topics...")
        
        for category, info in self.TOPIC_CATEGORIES.items():
            topic_id = self.topic_ids.get(category)
            needs_creation = False
            
            if not topic_id:
                needs_creation = True
            else:
                # User requested to disable topic verification/recreation
                # If topic ID exists in DB, assume it's valid and don't check/recreate
                # This prevents deleted topics from reappearing
                pass
            
            if needs_creation:
                try:
                    # Create forum topic
                    result = await self.bot.create_forum_topic(
                        chat_id=self.channel_id,
                        name=info['name']
                    )
                    
                    self.topic_ids[category] = result.message_thread_id
                    await self._save_topic_id(category, result.message_thread_id)
                    
                    logger.info(f"✅ Created topic '{info['name']}' with ID {result.message_thread_id}")
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(1.0)
                except BadRequest as e:
                    if "not enough rights" in str(e).lower():
                        logger.error(f"❌ Bot does not have permission to create topics in '{self.channel_id}'")
                        logger.error("❌ Stopping topic creation due to lack of permissions.")
                        return
                except Exception as e:
                    logger.error(f"❌ Error creating topic '{info['name']}': {e}")

    async def initialize_topics_on_startup(self) -> Dict:
        """
        Initialize topics when bot starts.
        Returns a diagnostic dictionary.
        """
        diag = {
            'enabled': self.enabled,
            'channel_id': self.channel_id,
            'chat_type': 'unknown',
            'is_forum': False,
            'is_admin': False,
            'can_manage_topics': False,
            'is_group': False,
            'topics_count': 0,
            'errors': []
        }
        
        if not self.enabled:
            logger.info("📊 Reporting system disabled, skipping topic initialization")
            return diag
            
        logger.info(f"🔧 Starting topic initialization for channel ID: {self.channel_id}...")
        
        try:
            # Try to get chat info to determine if it's a group with topics
            chat = await self.bot.get_chat(self.channel_id)
            
            diag['chat_type'] = getattr(chat, 'type', 'unknown')
            diag['is_forum'] = getattr(chat, 'is_forum', False)
            chat_title = getattr(chat, 'title', 'No Title')
            
            logger.info(f"📊 Chat info: Title='{chat_title}', Type='{diag['chat_type']}', IsForum={diag['is_forum']}")
            
            # Check bot permissions if it's a group
            if diag['chat_type'] in ['supergroup', 'group']:
                try:
                    bot_me = await self.bot.get_me()
                    member = await self.bot.get_chat_member(self.channel_id, bot_me.id)
                    diag['can_manage_topics'] = getattr(member, 'can_manage_topics', False)
                    diag['is_admin'] = member.status in ['administrator', 'creator']
                    logger.info(f"🤖 Bot status in chat: Status='{member.status}', IsAdmin={diag['is_admin']}, CanManageTopics={diag['can_manage_topics']}")
                    
                    if not diag['is_admin']:
                        diag['errors'].append("ربات در این گروه ادمین نیست.")
                    elif not diag['can_manage_topics']:
                        diag['errors'].append("ربات دسترسی 'Manage Topics' را ندارد.")
                except Exception as pe:
                    logger.warning(f"⚠️ Could not check bot permissions: {pe}")
                    diag['errors'].append(f"خطا در بررسی دسترسی‌ها: {pe}")

                # We consider it a group mode if it's a forum OR if we can make it one
                if diag['is_forum']:
                    self.is_group = True
                    diag['is_group'] = True
                    logger.info(f"✅ Detected forum group: {chat_title}")
                else:
                    # Try a test topic to see if it's actually a forum (sometimes Telegram API is slow to update is_forum)
                    logger.info("🧪 Attempting to create a test topic to verify forum status...")
                    try:
                        test_topic = await self.bot.create_forum_topic(self.channel_id, "🔍 تست سیستم")
                        logger.info(f"🚀 Success! Group IS a forum despite is_forum=False. Topic ID: {test_topic.message_thread_id}")
                        self.is_group = True
                        diag['is_group'] = True
                        diag['is_forum'] = True # Correcting our diagnostic
                        # Delete the test topic if possible (PTB doesn't have delete_forum_topic yet in all versions, but we can close it)
                        try:
                            await self.bot.close_forum_topic(self.channel_id, test_topic.message_thread_id)
                        except: pass
                    except Exception as te:
                        logger.info(f"ℹ️ Test topic creation failed: {te}")
                        self.is_group = False
                        diag['is_group'] = False
                        diag['errors'].append(f"گروه قابلیت تاپیک ندارد یا ربات دسترسی ندارد: {te}")

                if self.is_group:
                    # Load existing topic IDs from database
                    await self._load_topic_ids()
                    
                    # Verify existing topics and create missing ones
                    await self._verify_and_create_topics()
                    
                    diag['topics_count'] = len(self.topic_ids)
                    logger.info(f"✅ Topic initialization complete. {diag['topics_count']} topics ready.")
            else:
                self.is_group = False
                diag['is_group'] = False
                logger.info(f"📺 Using channel mode for reporting: {chat_title}")
                
            self.topics_initialized = True
            
        except Exception as e:
            logger.error(f"❌ Topic initialization failed for ID {self.channel_id}: {e}")
            diag['errors'].append(f"خطای کلی در مقداردهی: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.is_group = False
            self.topics_initialized = True
            
        return diag
    
    def _get_topic_for_report(self, report_type: str) -> Optional[int]:
        """Get the topic ID for a specific report type"""
        if not self.is_group:
            return None
            
        for category, info in self.TOPIC_CATEGORIES.items():
            if report_type in info['report_types']:
                return self.topic_ids.get(category)
        
        # Default to system topic
        return self.topic_ids.get('system')
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special Markdown characters"""
        if not text:
            return ""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    async def send_report(self, report_type: str, data: Dict, user_info: Optional[Dict] = None):
        """
        Send a report to the designated channel/group with retry logic
        """
        if not self.enabled:
            logger.debug(f"Reporting system disabled - skipping report: {report_type}")
            return
        
        # Initialize topics on first report
        if not self.topics_initialized:
            await self._initialize_topics()
        
        logger.info(f"📤 Sending report '{report_type}' from bot '{self.bot_name}'")
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                message = self._format_report(report_type, data, user_info)
                
                # Add bot identifier (except for bot_start)
                if report_type != "bot_start" and self.bot_name:
                    bot_header = f"🤖 **ربات:** @{self.bot_username}\n\n"
                    message = bot_header + message
                
                # Get topic ID for group mode
                topic_id = self._get_topic_for_report(report_type)
                
                # Send message
                send_kwargs = {
                    'chat_id': self.channel_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }
                
                if topic_id and self.is_group:
                    send_kwargs['message_thread_id'] = topic_id
                
                try:
                    await self.bot.send_message(**send_kwargs)
                    logger.info(f"✅ Report '{report_type}' sent successfully")
                    return
                except BadRequest as e:
                    # If Markdown parsing fails, try without Markdown
                    if "can't parse" in str(e).lower():
                        send_kwargs['parse_mode'] = None
                        send_kwargs['text'] = message.replace('**', '').replace('`', '')
                        await self.bot.send_message(**send_kwargs)
                        return
                    raise
                        
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Network error (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"❌ Failed to send report after {max_retries} attempts: {report_type}")
                    
            except TelegramError as e:
                logger.error(f"❌ Telegram error sending report: {report_type}. Error: {e}")
                break
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error in reporting system: {report_type}. Error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                break
    
    def _format_report(self, report_type: str, data: Dict, user_info: Optional[Dict] = None) -> str:
        """Format report message based on type"""
        timestamp = PersianDateTime.format_full_datetime()
        
        # User display helpers
        def get_user_display(info):
            if not info:
                return "نامشخص", "بدون نام کاربری"
            name = info.get('first_name', 'نامشخص')
            if info.get('last_name'):
                name += f" {info.get('last_name')}"
            username = f"@{info.get('username')}" if info.get('username') else "بدون نام کاربری"
            return name, username
        
        user_name, user_username = get_user_display(user_info)
        user_id = user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'
        
        # ==================== REPORT FORMATTERS ====================
        
        if report_type == "bot_start":
            bot_username = self.bot_config.get('bot_username', 'Unknown')
            admin_id = self.bot_config.get('admin_id', 'Unknown')
            return f"""
🚀 ربات VPN راه‌اندازی شد

⏰ زمان: {timestamp}
🤖 نام ربات: @{bot_username}
👤 آیدی ادمین: {admin_id}
📢 کانال گزارشات: {self.channel_id if self.enabled else 'غیرفعال'}
🗂️ حالت گزارش: {'گروه با تاپیک' if self.is_group else 'کانال ساده'}

✅ وضعیت: آماده به کار
            """
        
        elif report_type == "user_registration":
            referrer_info = ""
            if data.get('referrer_id'):
                referrer_info = f"""
🎁 اطلاعات معرف:
   • نام: {data.get('referrer_name', 'نامشخص')}
   • یوزرنیم: @{data.get('referrer_username', 'بدون نام کاربری')}
   • آیدی: {data.get('referrer_telegram_id', 'نامشخص')}
   • پاداش: {data.get('referral_reward', 0):,} تومان
"""
            else:
                referrer_info = "\n🎁 معرف: ثبت نام مستقیم\n"
            
            return f"""
👤 ثبت‌نام کاربر جدید

⏰ زمان: {timestamp}
🆔 آیدی تلگرام: {data.get('telegram_id', 'Unknown')}
👤 نام کاربری: @{data.get('username', 'بدون نام کاربری')}
📝 نام: {data.get('first_name', 'نامشخص')} {data.get('last_name', '')}
💰 هدیه ثبت نام: {data.get('welcome_bonus', 0):,} تومان
{referrer_info}
✅ وضعیت: ثبت‌نام موفق
            """
        
        elif report_type == "user_blocked":
            target = data.get('target_user', {})
            target_name, target_username = get_user_display(target)
            return f"""
🚫 مسدود کردن کاربر

⏰ زمان: {timestamp}
👨‍💼 ادمین: {user_name} ({user_username})

👤 کاربر مسدود شده:
   • نام: {target_name}
   • یوزرنیم: {target_username}
   • آیدی: {target.get('telegram_id', 'نامشخص')}
📝 دلیل: {data.get('reason', 'نامشخص')}

🚫 وضعیت: کاربر مسدود شد
            """
        
        elif report_type == "user_unblocked":
            target = data.get('target_user', {})
            target_name, target_username = get_user_display(target)
            return f"""
✅ رفع مسدودیت کاربر

⏰ زمان: {timestamp}
👨‍💼 ادمین: {user_name} ({user_username})

👤 کاربر رفع مسدود شده:
   • نام: {target_name}
   • یوزرنیم: {target_username}
   • آیدی: {target.get('telegram_id', 'نامشخص')}

✅ وضعیت: مسدودیت کاربر برداشته شد
            """
        
        elif report_type == "test_account_created":
            return f"""
🧪 ایجاد اکانت تست

⏰ زمان: {timestamp}
👤 کاربر: {user_name} ({user_username})
🆔 آیدی: {user_id}
🖥️ پنل: {data.get('panel_name', 'نامشخص')}
📊 حجم: {data.get('volume_gb', 0)} گیگابایت
⏰ مدت: {data.get('duration_hours', 24)} ساعت

✅ وضعیت: اکانت تست ایجاد شد
            """
        
        elif report_type == "balance_added":
            return f"""
💰 افزایش موجودی

⏰ زمان: {timestamp}
👤 کاربر: {user_name} ({user_username})
🆔 آیدی: {user_id}
💵 مبلغ: {data.get('amount', 0):,} تومان
💳 موجودی جدید: {data.get('new_balance', 0):,} تومان
🔗 روش پرداخت: {data.get('payment_method', 'نامشخص')}

✅ وضعیت: موفق
            """
        
        elif report_type == "service_purchased":
            purchase_type = "📦 پلنی" if data.get('purchase_type') == 'plan' else "💾 گیگابایتی"
            payment_method = "💳 درگاه بانکی" if data.get('payment_method') == 'gateway' else "💰 موجودی"
            
            plan_info = ""
            if data.get('purchase_type') == 'plan':
                if data.get('product_name'):
                    plan_info = f"\n📦 نام پلن: {data.get('product_name')}"
                if data.get('duration_days', 0) > 0:
                    plan_info += f"\n⏰ مدت: {data.get('duration_days')} روز"
            
            return f"""
🛒 خرید سرویس جدید

⏰ زمان: {timestamp}
👤 کاربر: {user_name} ({user_username})
🆔 آیدی: {user_id}
🔧 نام سرویس: {data.get('service_name', 'نامشخص')}
📊 حجم: {data.get('data_amount', 0)} گیگابایت{plan_info}
💰 مبلغ: {data.get('amount', 0):,} تومان
🖥️ پنل: {data.get('panel_name', 'نامشخص')}
📋 نوع: {purchase_type}
💳 پرداخت: {payment_method}

✅ وضعیت: خرید موفق
            """
        
        elif report_type == "service_renewed":
            return f"""
🔄 تمدید سرویس

⏰ زمان: {timestamp}
👤 کاربر: {user_name} ({user_username})
🆔 آیدی: {user_id}
🔧 نام سرویس: {data.get('service_name', 'نامشخص')}
📊 حجم اضافه: {data.get('additional_data', 0)} گیگابایت
📈 حجم کل جدید: {data.get('total_data', 0)} گیگابایت
💰 مبلغ: {data.get('amount', 0):,} تومان

✅ وضعیت: تمدید موفق
            """
        
        elif report_type == "volume_added":
            payment_method = "💳 درگاه بانکی" if data.get('payment_method') == 'gateway' else "💰 موجودی"
            
            return f"""
📈 افزایش حجم سرویس

⏰ زمان: {timestamp}
👤 کاربر: {user_name} ({user_username})
🆔 آیدی: {user_id}
🔧 نام سرویس: {data.get('service_name', 'نامشخص')}
📊 حجم اضافه شده: {data.get('volume_added', 0)} گیگابایت
📈 حجم قبلی: {data.get('old_volume', 0):.2f} گیگابایت
📈 حجم جدید: {data.get('new_volume', 0):.2f} گیگابایت
💰 مبلغ: {data.get('amount', 0):,} تومان
🖥️ پنل: {data.get('panel_name', 'نامشخص')}
💳 پرداخت: {payment_method}

✅ وضعیت: افزایش حجم موفق
            """
        
        elif report_type == "service_volume_70_percent":
            return f"""
⚠️ **هشدار مصرف ۷۰ درصد**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📊 **مصرف:** {data.get('usage_percentage', 0):.1f}%
📦 **حجم کل:** {data.get('total_gb', 0):.2f} GB
♾ **باقی‌مانده:** {data.get('remaining_gb', 0):.2f} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}

⚠️ کاربر ۷۰ درصد حجم را مصرف کرده
            """
        
        elif report_type == "service_volume_80_percent":
            return f"""
🔶 **هشدار مصرف ۸۰ درصد**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📊 **مصرف:** {data.get('usage_percentage', 0):.1f}%
📦 **حجم کل:** {data.get('total_gb', 0):.2f} GB
♾ **باقی‌مانده:** {data.get('remaining_gb', 0):.2f} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}

🔶 کاربر ۸۰ درصد حجم را مصرف کرده - نزدیک به اتمام
            """
        
        elif report_type == "service_volume_exhausted":
            return f"""
🚫 **اتمام حجم سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📊 **مصرف:** ۱۰۰%
📦 **حجم کل:** {data.get('total_gb', 0):.2f} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}

🚫 **حجم تمام شد - سرویس غیرفعال**
⏰ مهلت تمدید: ۲۴ ساعت
            """
        
        elif report_type == "service_expired":
            return f"""
⏰ **اتمام زمان سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📅 **تاریخ انقضا:** {data.get('expires_at', 'نامشخص')}
📦 **حجم:** {data.get('total_gb', 0):.2f} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}

⏰ **زمان تمام شد - سرویس غیرفعال**
⏰ مهلت تمدید: ۲۴ ساعت
            """
        
        elif report_type == "service_expiring_soon":
            return f"""
⚠️ **هشدار انقضای نزدیک**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📅 **تاریخ انقضا:** {data.get('expires_at', 'نامشخص')}
⏳ **باقی‌مانده:** {data.get('remaining_days', 0)} روز
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}

⚠️ سرویس تا {data.get('remaining_days', 0)} روز دیگر منقضی می‌شود
            """
        
        elif report_type == "service_deleted":
            return f"""
🗑️ **حذف سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📊 **حجم:** {data.get('data_amount', 0)} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}
📝 **دلیل:** {data.get('reason', 'نامشخص')}

🗑️ **سرویس حذف شد**
            """
        
        elif report_type == "service_auto_deleted":
            reason = data.get('reason', 'عدم تمدید بعد از ۲۴ ساعت')
            if data.get('exhausted_at'):
                reason = 'اتمام حجم - عدم تمدید'
            elif data.get('expired_at'):
                reason = 'اتمام زمان - عدم تمدید'
            
            return f"""
🗑️ **حذف خودکار سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📦 **حجم:** {data.get('total_gb', 0):.2f} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}
📅 **زمان اتمام:** {data.get('exhausted_at') or data.get('expired_at', 'نامشخص')}
📝 **دلیل:** {reason}

🗑️ **سرویس به دلیل عدم تمدید حذف شد**
            """
        
        elif report_type == "panel_added":
            return f"""
➕ **اضافه شدن پنل جدید**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})
🖥️ **نام پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **آدرس:** {data.get('panel_url', 'نامشخص')}
👤 **نام کاربری:** {data.get('username', 'نامشخص')}
📋 **نوع:** {data.get('panel_type', 'نامشخص')}

✅ **پنل اضافه شد**
            """
        
        elif report_type == "panel_deleted":
            return f"""
➖ **حذف پنل**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})
🖥️ **نام پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **آدرس:** {data.get('panel_url', 'نامشخص')}
📝 **دلیل:** {data.get('reason', 'نامشخص')}

🗑️ **پنل حذف شد**
            """
        
        elif report_type == "panel_connection_failed":
            return f"""
🔌 **خطا در اتصال به پنل**

⏰ **زمان:** {timestamp}
🖥️ **نام پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **آدرس:** {data.get('panel_url', 'نامشخص')}
📝 **خطا:** {data.get('error_message', 'نامشخص')}
👤 **کاربر:** {user_name if user_info else 'سیستم'}

❌ **اتصال ناموفق**
            """
        
        elif report_type == "panel_change":
            old_inbound = f"\n🔌 **اینباند مبدا:** {data.get('old_inbound_name')}" if data.get('old_inbound_name') else ""
            new_inbound = f"\n🔌 **اینباند مقصد:** {data.get('new_inbound_name')}" if data.get('new_inbound_name') else ""
            
            return f"""
🌍 **تغییر لوکیشن/پنل**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📦 **حجم باقی‌مانده:** {data.get('remaining_gb', 0):.2f} GB
🖥️ **پنل مبدا:** {data.get('old_panel_name', 'نامشخص')}{old_inbound}
🖥️ **پنل مقصد:** {data.get('new_panel_name', 'نامشخص')}{new_inbound}

✅ **تغییر لوکیشن موفق**
            """
        
        elif report_type == "admin_balance_increase":
            target = data.get('target_user', {})
            target_name, target_username = get_user_display(target)
            
            return f"""
➕💰 **افزایش موجودی توسط ادمین**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})

👤 **کاربر هدف:** {target_name} ({target_username})
🆔 **آیدی:** {target.get('telegram_id', 'نامشخص')}

💰 **موجودی قبلی:** {data.get('old_balance', 0):,} تومان
➕ **مبلغ افزایش:** {data.get('amount', 0):,} تومان
💰 **موجودی جدید:** {data.get('new_balance', 0):,} تومان

✅ **افزایش موجودی موفق**
            """
        
        elif report_type == "admin_balance_decrease":
            target = data.get('target_user', {})
            target_name, target_username = get_user_display(target)
            
            return f"""
➖💰 **کاهش موجودی توسط ادمین**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})

👤 **کاربر هدف:** {target_name} ({target_username})
🆔 **آیدی:** {target.get('telegram_id', 'نامشخص')}

💰 **موجودی قبلی:** {data.get('old_balance', 0):,} تومان
➖ **مبلغ کاهش:** {data.get('amount', 0):,} تومان
💰 **موجودی جدید:** {data.get('new_balance', 0):,} تومان

✅ **کاهش موجودی موفق**
            """
        
        elif report_type == "broadcast_message":
            return f"""
📢 **ارسال پیام همگانی**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})

📊 **کل کاربران:** {data.get('total_users', 0):,}
✅ **موفق:** {data.get('success_count', 0):,}
❌ **ناموفق:** {data.get('failed_count', 0):,}
📈 **درصد موفقیت:** {data.get('success_rate', 0):.1f}%

📝 **پیش‌نمایش:**
{data.get('message_preview', 'پیام خالی')[:200]}...

✅ **ارسال پیام همگانی انجام شد**
            """
        
        elif report_type == "discount_code_used":
            return f"""
🏷️ **استفاده از کد تخفیف**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🎫 **کد:** {data.get('code', 'نامشخص')}
💰 **مبلغ قبل:** {data.get('amount_before', 0):,} تومان
💸 **تخفیف:** {data.get('discount_amount', 0):,} تومان
💰 **مبلغ نهایی:** {data.get('amount_after', 0):,} تومان

✅ **کد تخفیف اعمال شد**
            """
        
        elif report_type == "gift_code_used":
            return f"""
🎁 **استفاده از کد هدیه**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🎫 **کد:** {data.get('code', 'نامشخص')}
💰 **مبلغ:** {data.get('amount', 0):,} تومان
💳 **موجودی جدید:** {data.get('new_balance', 0):,} تومان

✅ **کد هدیه استفاده شد**
            """
        
        elif report_type == "referral_reward":
            referred = data.get('referred_user', {})
            referred_name, referred_username = get_user_display(referred)
            
            return f"""
🎁 **پاداش دعوت دوستان**

⏰ **زمان:** {timestamp}
👤 **معرف:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}

👥 **کاربر جدید:** {referred_name} ({referred_username})
💰 **پاداش:** {data.get('reward_amount', 0):,} تومان
💳 **موجودی جدید:** {data.get('new_balance', 0):,} تومان
📊 **کل معرفی‌ها:** {data.get('total_referrals', 0)}

✅ **پاداش واریز شد**
            """
        
        elif report_type == "ticket_created":
            return f"""
🎫 **تیکت جدید**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔢 **شماره تیکت:** #{data.get('ticket_id', 'نامشخص')}
📝 **موضوع:** {data.get('subject', 'نامشخص')}
⚡ **اولویت:** {data.get('priority', 'عادی')}

📨 **تیکت جدید ایجاد شد**
            """
        
        elif report_type == "ticket_replied":
            return f"""
💬 **پاسخ تیکت**

⏰ **زمان:** {timestamp}
👤 **پاسخ‌دهنده:** {user_name} ({user_username})
🔢 **شماره تیکت:** #{data.get('ticket_id', 'نامشخص')}
👤 **کاربر تیکت:** {data.get('ticket_user_name', 'نامشخص')}
📋 **نوع پاسخ:** {'ادمین' if data.get('is_admin_reply') else 'کاربر'}

💬 **پاسخ جدید ثبت شد**
            """
        
        elif report_type == "user_error":
            return f"""
❌ **خطای کاربر**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔴 **نوع خطا:** {data.get('error_type', 'نامشخص')}
📝 **پیام:** {data.get('error_message', 'نامشخص')}
🔧 **عملیات:** {data.get('action', 'نامشخص')}

❌ **خطا رخ داد**
            """
        
        elif report_type == "system_error":
            return f"""
🚨 **خطای سیستم**

⏰ **زمان:** {timestamp}
🔴 **نوع:** {data.get('error_type', 'نامشخص')}
📝 **پیام:** {data.get('error_message', 'نامشخص')}
🔧 **کامپوننت:** {data.get('component', 'نامشخص')}
📊 **سطح:** {data.get('severity', 'نامشخص')}

🚨 **خطای سیستم**
            """
        
        elif report_type == "payment_failed":
            return f"""
💳 **خطا در پرداخت**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
💰 **مبلغ:** {data.get('amount', 0):,} تومان
🔗 **روش پرداخت:** {data.get('payment_method', 'نامشخص')}
📝 **خطا:** {data.get('error_message', 'نامشخص')}
🆔 **شناسه تراکنش:** {data.get('transaction_id', 'نامشخص')}

❌ **پرداخت ناموفق**
            """
        
        elif report_type == "subscription_link_retrieved":
            return f"""
🔗 **دریافت لینک سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
🔧 **سرویس:** {data.get('service_name', 'نامشخص')}
📊 **حجم:** {data.get('total_gb', 0):.2f} GB
🖥️ **پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **پروتکل:** {data.get('protocol', 'نامشخص').upper()}

✅ **لینک دریافت شد**
            """
        
        elif report_type == "balance_recharged":
            payment_method = "💳 درگاه بانکی" if data.get('payment_method') == 'gateway' else "💰 روش دیگر"
            
            return f"""
💳 **شارژ حساب**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_name} ({user_username})
🆔 **آیدی:** {user_id}
💰 **مبلغ:** {data.get('amount', 0):,} تومان
💵 **موجودی قبلی:** {data.get('old_balance', 0):,} تومان
💵 **موجودی جدید:** {data.get('new_balance', 0):,} تومان
💳 **روش:** {payment_method}
🆔 **شناسه تراکنش:** {data.get('transaction_id', 'نامشخص')}

✅ **شارژ موفق**
            """
        
        elif report_type == "backup_created":
            return f"""
💾 **بکاپ ایجاد شد**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})
📁 **نام فایل:** {data.get('filename', 'نامشخص')}
📊 **حجم:** {data.get('size', 'نامشخص')}

✅ **بکاپ با موفقیت ایجاد شد**
            """
        
        elif report_type == "backup_restored":
            return f"""
📤 **بکاپ بازگردانی شد**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {user_name} ({user_username})
📁 **نام فایل:** {data.get('filename', 'نامشخص')}
📊 **رکوردها:** {data.get('records_restored', 0):,}

✅ **بکاپ با موفقیت بازگردانی شد**
            """
        
        else:
            return f"""
📋 **گزارش عمومی**

⏰ **زمان:** {timestamp}
🔧 **نوع:** {report_type}
📊 **اطلاعات:** {str(data)[:200]}
👤 **کاربر:** {user_name if user_info else 'سیستم'}

ℹ️ **گزارش ارسال شد**
            """
    
    # ==================== CONVENIENCE METHODS ====================
    
    async def report_bot_start(self):
        """Report bot startup"""
        await self.send_report("bot_start", {})
    
    async def report_user_registration(self, user_data: Dict, referrer_data: Dict = None):
        """Report new user registration"""
        report_data = user_data.copy()
        if referrer_data:
            report_data['referrer_id'] = referrer_data.get('id')
            report_data['referrer_telegram_id'] = referrer_data.get('telegram_id')
            report_data['referrer_username'] = referrer_data.get('username', 'بدون نام کاربری')
            report_data['referrer_name'] = referrer_data.get('first_name', 'نامشخص')
            if referrer_data.get('last_name'):
                report_data['referrer_name'] += f" {referrer_data.get('last_name')}"
        await self.send_report("user_registration", report_data)
    
    async def report_user_blocked(self, admin_data: Dict, target_user: Dict, reason: str = "نامشخص"):
        """Report user blocked by admin"""
        data = {'target_user': target_user, 'reason': reason}
        await self.send_report("user_blocked", data, admin_data)
    
    async def report_user_unblocked(self, admin_data: Dict, target_user: Dict):
        """Report user unblocked by admin"""
        data = {'target_user': target_user}
        await self.send_report("user_unblocked", data, admin_data)
    
    async def report_test_account_created(self, user_data: Dict, panel_name: str, volume_gb: float, duration_hours: int):
        """Report test account creation"""
        data = {'panel_name': panel_name, 'volume_gb': volume_gb, 'duration_hours': duration_hours}
        await self.send_report("test_account_created", data, user_data)
    
    async def report_balance_added(self, user_data: Dict, amount: int, new_balance: int, payment_method: str):
        """Report balance addition"""
        data = {'amount': amount, 'new_balance': new_balance, 'payment_method': payment_method}
        await self.send_report("balance_added", data, user_data)
    
    async def report_service_purchased(self, user_data: Dict, service_data: Dict):
        """Report service purchase"""
        await self.send_report("service_purchased", service_data, user_data)
    
    async def report_service_renewed(self, user_data: Dict, renewal_data: Dict):
        """Report service renewal"""
        await self.send_report("service_renewed", renewal_data, user_data)
    
    async def report_service_deleted(self, user_data: Dict, service_data: Dict, reason: str = "نامشخص"):
        """Report service deletion"""
        service_data['reason'] = reason
        await self.send_report("service_deleted", service_data, user_data)
    
    async def report_panel_added(self, admin_data: Dict, panel_data: Dict):
        """Report panel addition"""
        await self.send_report("panel_added", panel_data, admin_data)
    
    async def report_panel_deleted(self, admin_data: Dict, panel_data: Dict, reason: str = "نامشخص"):
        """Report panel deletion"""
        panel_data['reason'] = reason
        await self.send_report("panel_deleted", panel_data, admin_data)
    
    async def report_user_error(self, user_data: Dict, error_type: str, error_message: str, action: str):
        """Report user error"""
        data = {'user_id': user_data.get('telegram_id'), 'error_type': error_type, 
                'error_message': error_message, 'action': action}
        await self.send_report("user_error", data, user_data)
    
    async def report_system_error(self, error_type: str, error_message: str, component: str, severity: str = "متوسط"):
        """Report system error"""
        data = {'error_type': error_type, 'error_message': error_message, 
                'component': component, 'severity': severity}
        await self.send_report("system_error", data)
    
    async def report_payment_failed(self, user_data: Dict, amount: int, payment_method: str, error_message: str, transaction_id: str = None):
        """Report payment failure"""
        data = {'amount': amount, 'payment_method': payment_method, 
                'error_message': error_message, 'transaction_id': transaction_id}
        await self.send_report("payment_failed", data, user_data)
    
    async def report_panel_connection_failed(self, panel_data: Dict, error_message: str, user_data: Dict = None):
        """Report panel connection failure"""
        data = {'panel_name': panel_data.get('name', 'نامشخص'), 
                'panel_url': panel_data.get('url', 'نامشخص'), 'error_message': error_message}
        await self.send_report("panel_connection_failed", data, user_data)
    
    async def report_service_volume_70_percent(self, user_data: Dict, service_data: Dict):
        """Report service reaching 70% volume usage"""
        await self.send_report("service_volume_70_percent", service_data, user_data)
    
    async def report_service_volume_80_percent(self, user_data: Dict, service_data: Dict):
        """Report service reaching 80% volume usage"""
        await self.send_report("service_volume_80_percent", service_data, user_data)
    
    async def report_service_volume_exhausted(self, user_data: Dict, service_data: Dict):
        """Report service volume exhaustion"""
        await self.send_report("service_volume_exhausted", service_data, user_data)
    
    async def report_service_expired(self, user_data: Dict, service_data: Dict):
        """Report plan service expiration"""
        await self.send_report("service_expired", service_data, user_data)
    
    async def report_service_auto_deleted(self, user_data: Dict, service_data: Dict):
        """Report automatic service deletion"""
        await self.send_report("service_auto_deleted", service_data, user_data)
    
    async def report_service_expiring_soon(self, user_data: Dict, service_data: Dict):
        """Report service expiring soon"""
        await self.send_report("service_expiring_soon", service_data, user_data)
    
    async def report_panel_change(self, user_data: Dict, service_data: Dict):
        """Report panel/location change"""
        await self.send_report("panel_change", service_data, user_data)
    
    async def report_volume_added(self, user_data: Dict, volume_data: Dict):
        """Report volume addition to service"""
        await self.send_report("volume_added", volume_data, user_data)
    
    async def report_subscription_link_retrieved(self, user_data: Dict, service_data: Dict):
        """Report subscription link retrieval"""
        await self.send_report("subscription_link_retrieved", service_data, user_data)
    
    async def report_balance_recharged(self, user_data: Dict, recharge_data: Dict):
        """Report balance recharge"""
        await self.send_report("balance_recharged", recharge_data, user_data)
    
    async def report_discount_code_used(self, user_data: Dict, code: str, amount_before: int, discount_amount: int, amount_after: int):
        """Report discount code usage"""
        data = {'code': code, 'amount_before': amount_before, 
                'discount_amount': discount_amount, 'amount_after': amount_after}
        await self.send_report("discount_code_used", data, user_data)
    
    async def report_gift_code_used(self, user_data: Dict, code: str, amount: int, new_balance: int):
        """Report gift code usage"""
        data = {'code': code, 'amount': amount, 'new_balance': new_balance}
        await self.send_report("gift_code_used", data, user_data)
    
    async def report_referral_reward(self, user_data: Dict, referred_user: Dict, reward_amount: int, new_balance: int, total_referrals: int):
        """Report referral reward"""
        data = {'referred_user': referred_user, 'reward_amount': reward_amount, 
                'new_balance': new_balance, 'total_referrals': total_referrals}
        await self.send_report("referral_reward", data, user_data)
    
    async def report_ticket_created(self, user_data: Dict, ticket_id: int, subject: str, priority: str = "عادی"):
        """Report ticket creation"""
        data = {'ticket_id': ticket_id, 'subject': subject, 'priority': priority}
        await self.send_report("ticket_created", data, user_data)
    
    async def report_ticket_replied(self, user_data: Dict, ticket_id: int, ticket_user_name: str, is_admin_reply: bool):
        """Report ticket reply"""
        data = {'ticket_id': ticket_id, 'ticket_user_name': ticket_user_name, 'is_admin_reply': is_admin_reply}
        await self.send_report("ticket_replied", data, user_data)
    
    async def report_backup_created(self, admin_data: Dict, filename: str, size: str):
        """Report backup creation"""
        data = {'filename': filename, 'size': size}
        await self.send_report("backup_created", data, admin_data)
    
    async def report_backup_restored(self, admin_data: Dict, filename: str, records_restored: int):
        """Report backup restoration"""
        data = {'filename': filename, 'records_restored': records_restored}
        await self.send_report("backup_restored", data, admin_data)
    
    async def report_broadcast_message(self, admin_data: Dict, total_users: int, success_count: int, failed_count: int, message_preview: str):
        """Report broadcast message"""
        success_rate = (success_count / total_users * 100) if total_users > 0 else 0
        data = {'total_users': total_users, 'success_count': success_count, 
                'failed_count': failed_count, 'success_rate': success_rate, 
                'message_preview': message_preview}
        await self.send_report("broadcast_message", data, admin_data)
    
    async def report_admin_balance_increase(self, admin_data: Dict, target_user: Dict, old_balance: int, amount: int, new_balance: int):
        """Report admin balance increase"""
        data = {'target_user': target_user, 'old_balance': old_balance, 
                'amount': amount, 'new_balance': new_balance}
        await self.send_report("admin_balance_increase", data, admin_data)
    
    async def report_admin_balance_decrease(self, admin_data: Dict, target_user: Dict, old_balance: int, amount: int, new_balance: int):
        """Report admin balance decrease"""
        data = {'target_user': target_user, 'old_balance': old_balance, 
                'amount': amount, 'new_balance': new_balance}
        await self.send_report("admin_balance_decrease", data, admin_data)
