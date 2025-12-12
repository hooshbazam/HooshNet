"""
Professional Reporting System for VPN Bot
Sends comprehensive reports to a designated channel for each bot separately
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Bot
from telegram.error import TelegramError, TimedOut, NetworkError, BadRequest
from persian_datetime import PersianDateTime

logger = logging.getLogger(__name__)

class ReportingSystem:
    """
    Professional reporting system for bot events
    
    CRITICAL: Each bot must use its own ReportingSystem instance with its own bot_config
    to ensure reports are sent to the correct channel.
    """
    
    def __init__(self, bot: Bot, bot_config=None):
        """
        Initialize ReportingSystem with bot and bot_config
        
        Args:
            bot: Telegram Bot instance
            bot_config: Bot configuration dict (REQUIRED - must not be None)
                       Must contain 'reports_channel_id' for the specific bot
        """
        self.bot = bot
        
        # CRITICAL: bot_config is REQUIRED - each bot must have its own config
        if bot_config is None:
            # Try to get from config as fallback (single bot mode)
            try:
                from config import BOT_CONFIG
                bot_config = BOT_CONFIG
                logger.warning("⚠️ ReportingSystem initialized without bot_config - using global BOT_CONFIG. This should not happen in multi-bot mode!")
            except ImportError:
                logger.error("❌ CRITICAL: bot_config is required but not provided and BOT_CONFIG not available!")
                raise ValueError("bot_config is required for ReportingSystem")
        
        self.bot_config = bot_config
        self.channel_id = bot_config.get('reports_channel_id')
        self.bot_username = bot_config.get('bot_username', 'Unknown')
        self.bot_name = bot_config.get('bot_name', bot_config.get('bot_username', 'Unknown'))
        
        # Validate channel ID
        if not self.channel_id:
            logger.error(f"❌ CRITICAL: No reports_channel_id found in bot_config for bot '{self.bot_name}'")
            self.enabled = False
        elif self.channel_id == '-1001234567890' or self.channel_id == 0:
            logger.warning(f"⚠️ Invalid reports_channel_id for bot '{self.bot_name}': {self.channel_id}")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"✅ ReportingSystem initialized for bot '{self.bot_name}' with channel ID: {self.channel_id}")
        
        if not self.enabled:
            logger.warning(f"⚠️ Reporting system disabled for bot '{self.bot_name}' - no valid channel ID configured")
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special Markdown characters"""
        if not text:
            return ""
        # Characters that need escaping in Markdown
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    async def send_report(self, report_type: str, data: Dict, user_info: Optional[Dict] = None):
        """
        Send a report to the designated channel with retry logic
        
        CRITICAL: This method uses self.channel_id which is specific to this bot instance.
        Each bot must have its own ReportingSystem instance to ensure reports go to the correct channel.
        """
        if not self.enabled:
            logger.debug(f"Reporting system disabled for bot '{self.bot_name}' - skipping report: {report_type}")
            return
        
        # Log which bot and channel this report is being sent to
        logger.info(f"📤 Sending report '{report_type}' from bot '{self.bot_name}' to channel {self.channel_id}")
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                message = self._format_report(report_type, data, user_info)
                
                # Add bot identifier to report (except for bot_start which already has it)
                if report_type != "bot_start" and self.bot_name:
                    # Add bot name as header
                    bot_header = f"🤖 **ربات:** @{self.bot_username}\n\n"
                    message = bot_header + message
                
                # Try to send with Markdown first
                try:
                    await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    logger.info(f"✅ Report '{report_type}' sent successfully from bot '{self.bot_name}' to channel {self.channel_id}")
                    return
                except BadRequest as e:
                    # If Markdown parsing fails, try without Markdown
                    try:
                        # Remove markdown formatting for plain text
                        plain_message = message.replace('**', '').replace('_', '').replace('`', '')
                        await self.bot.send_message(
                            chat_id=self.channel_id,
                            text=plain_message
                        )
                        return
                    except Exception as e2:
                        logger.error(f"❌ Failed to send plain text report from bot '{self.bot_name}': {e2}")
                        raise
                        
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Network error sending report from bot '{self.bot_name}' (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"❌ Failed to send report after {max_retries} attempts from bot '{self.bot_name}': {report_type}. Error: {e}")
                    # Try to send a simplified error report
                    try:
                        error_message = f"⚠️ خطا در ارسال گزارش\n\n🤖 ربات: @{self.bot_username}\nنوع گزارش: {report_type}\nزمان: {PersianDateTime.format_full_datetime()}\n\nخطا: {str(e)[:200]}"
                        await self.bot.send_message(
                            chat_id=self.channel_id,
                            text=error_message
                        )
                    except:
                        pass
                    
            except TelegramError as e:
                logger.error(f"❌ Telegram error sending report from bot '{self.bot_name}': {report_type}. Error: {e}")
                logger.error(f"Bot: {self.bot_name}, Channel: {self.channel_id}, Report type: {report_type}, Data keys: {list(data.keys()) if data else 'None'}")
                # Try to send a simplified error report
                try:
                    error_message = f"⚠️ خطا در ارسال گزارش\n\n🤖 ربات: @{self.bot_username}\nنوع گزارش: {report_type}\nزمان: {PersianDateTime.format_full_datetime()}\n\nخطا: {str(e)[:200]}"
                    await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=error_message
                    )
                except:
                    pass
                break
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error in reporting system for bot '{self.bot_name}': {report_type}. Error: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Try to send a simplified error report
                try:
                    error_message = f"⚠️ خطا در ارسال گزارش\n\n🤖 ربات: @{self.bot_username}\nنوع گزارش: {report_type}\nزمان: {PersianDateTime.format_full_datetime()}\n\nخطا: {str(e)[:200]}"
                    await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=error_message
                    )
                except:
                    pass
                break
    
    def _format_report(self, report_type: str, data: Dict, user_info: Optional[Dict] = None) -> str:
        """Format report message based on type"""
        timestamp = PersianDateTime.format_full_datetime()
        
        if report_type == "bot_start":
            # Use bot_config instead of global BOT_CONFIG
            bot_username = self.bot_config.get('bot_username', 'Unknown')
            admin_id = self.bot_config.get('admin_id', 'Unknown')
            return f"""
🚀 **ربات VPN راه‌اندازی شد**

⏰ **زمان:** {timestamp}
🤖 **نام ربات:** @{bot_username}
👤 **آیدی ادمین:** {admin_id}
📢 **کانال گزارشات:** {self.channel_id if self.enabled else 'غیرفعال'}

✅ **وضعیت:** آماده به کار
            """
        
        elif report_type == "user_registration":
            referrer_info = ""
            if data.get('referrer_id'):
                ref_username = data.get('referrer_username', 'بدون نام کاربری')
                ref_name = data.get('referrer_name', 'نامشخص')
                ref_id = data.get('referrer_telegram_id', 'نامشخص')
                referrer_info = f"""
🎁 **اطلاعات معرف:**
   • نام: {ref_name}
   • یوزرنیم: @{ref_username}
   • آیدی عددی: {ref_id}
   • پاداش واریزی: {data.get('referral_reward', 0):,} تومان
"""
            else:
                referrer_info = "\n🎁 **معرف:** ثبت نام مستقیم (بدون معرف)\n"
            
            return f"""
👤 **ثبت‌نام کاربر جدید**

⏰ **زمان:** {timestamp}
🆔 **آیدی تلگرام:** {data.get('telegram_id', 'Unknown')}
👤 **نام کاربری:** @{data.get('username', 'بدون نام کاربری')}
📝 **نام:** {data.get('first_name', 'نامشخص')} {data.get('last_name', '')}
💰 **هدیه ثبت نام:** {data.get('welcome_bonus', 0):,} تومان
{referrer_info}
✅ **وضعیت:** ثبت‌نام موفق
            """
        
        elif report_type == "balance_added":
            # Format phone/username properly
            username_display = f"@{user_info.get('username')}" if user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص')
            if user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
💰 **افزایش موجودی**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص')}
💵 **مبلغ اضافه شده:** {data.get('amount', 0):,} تومان
💳 **موجودی جدید:** {data.get('new_balance', 0):,} تومان
🔗 **روش پرداخت:** {data.get('payment_method', 'نامشخص')}

✅ **وضعیت:** موفق
            """
        
        elif report_type == "service_purchased":
            # Format phone/username properly
            username_display = f"@{user_info.get('username')}" if user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص')
            if user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            # Determine purchase type and payment method
            purchase_type = data.get('purchase_type', 'gigabyte')
            payment_method = data.get('payment_method', 'نامشخص')
            
            purchase_type_text = "📦 پلنی" if purchase_type == 'plan' else "💾 گیگابایتی"
            payment_method_text = "💳 درگاه بانکی" if payment_method == 'gateway' else "💰 موجودی حساب"
            
            # Additional info for plan purchases
            plan_info = ""
            if purchase_type == 'plan':
                product_name = data.get('product_name', '')
                duration_days = data.get('duration_days') or 0
                # Ensure duration_days is an integer
                try:
                    duration_days = int(duration_days) if duration_days is not None else 0
                except (ValueError, TypeError):
                    duration_days = 0
                
                if product_name:
                    plan_info = f"\n📦 **نام پلن:** {product_name}"
                if duration_days and duration_days > 0:
                    plan_info += f"\n⏰ **مدت اعتبار:** {duration_days} روز"
            
            return f"""
🛒 **خرید سرویس جدید**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص')}
🔧 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📊 **حجم:** {data.get('data_amount', 0)} گیگابایت
{plan_info}
💰 **مبلغ:** {data.get('amount', 0):,} تومان
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}
📋 **نوع خرید:** {purchase_type_text}
💳 **روش پرداخت:** {payment_method_text}

✅ **وضعیت:** خرید موفق
            """
        
        elif report_type == "service_renewed":
            # Format phone/username properly
            username_display = f"@{user_info.get('username')}" if user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص')
            if user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            # Escape special characters for Markdown
            user_display_name = user_display_name.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
            
            return f"""
🔄 تمدید سرویس

⏰ زمان: {timestamp}
👤 کاربر: {user_display_name} ({username_display})
🆔 آیدی عددی: {user_info.get('telegram_id', 'نامشخص')}
🔧 نام سرویس: {data.get('service_name', 'نامشخص')}
📊 حجم اضافه شده: {data.get('additional_data', 0)} گیگابایت
📈 حجم کل جدید: {data.get('total_data', 0)} گیگابایت
💰 مبلغ: {data.get('amount', 0):,} تومان

✅ وضعیت: تمدید موفق
            """
        
        elif report_type == "service_deleted":
            # Format phone/username properly
            username_display = f"@{user_info.get('username')}" if user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص')
            if user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
🗑️ **حذف سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص')}
🔧 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📊 **حجم:** {data.get('data_amount', 0)} گیگابایت
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}
📝 **دلیل:** {data.get('reason', 'نامشخص')}

⚠️ **وضعیت:** حذف شده
            """
        
        elif report_type == "panel_added":
            return f"""
➕ **اضافه شدن پنل جدید**

⏰ **زمان:** {timestamp}
👤 **ادمین:** {user_info.get('first_name', 'نامشخص')} (@{user_info.get('username', 'بدون نام کاربری')})
🔗 **نام پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **آدرس:** {data.get('panel_url', 'نامشخص')}
👤 **نام کاربری:** {data.get('username', 'نامشخص')}

✅ **وضعیت:** اضافه شد
            """
        
        elif report_type == "panel_deleted":
            return f"""
➖ **حذف پنل**

⏰ **زمان:** {timestamp}
👤 **ادمین:** {user_info.get('first_name', 'نامشخص')} (@{user_info.get('username', 'بدون نام کاربری')})
🔗 **نام پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **آدرس:** {data.get('panel_url', 'نامشخص')}
📝 **دلیل:** {data.get('reason', 'نامشخص')}

⚠️ **وضعیت:** حذف شد
            """
        
        elif report_type == "user_error":
            return f"""
❌ **خطای کاربر**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_info.get('first_name', 'نامشخص')} (@{user_info.get('username', 'بدون نام کاربری')})
🆔 **آیدی:** {data.get('user_id', 'نامشخص')}
🔴 **نوع خطا:** {data.get('error_type', 'نامشخص')}
📝 **پیام خطا:** {data.get('error_message', 'نامشخص')}
🔧 **عملیات:** {data.get('action', 'نامشخص')}

⚠️ **وضعیت:** خطا رخ داد
            """
        
        elif report_type == "system_error":
            return f"""
🚨 **خطای سیستم**

⏰ **زمان:** {timestamp}
🔴 **نوع خطا:** {data.get('error_type', 'نامشخص')}
📝 **پیام خطا:** {data.get('error_message', 'نامشخص')}
🔧 **کامپوننت:** {data.get('component', 'نامشخص')}
📊 **سطح خطا:** {data.get('severity', 'نامشخص')}

🚨 **وضعیت:** خطای سیستم
            """
        
        elif report_type == "payment_failed":
            return f"""
💳 **خطا در پرداخت**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_info.get('first_name', 'نامشخص')} (@{user_info.get('username', 'بدون نام کاربری')})
💰 **مبلغ:** {data.get('amount', 0):,} تومان
🔗 **روش پرداخت:** {data.get('payment_method', 'نامشخص')}
📝 **دلیل خطا:** {data.get('error_message', 'نامشخص')}
🆔 **شناسه تراکنش:** {data.get('transaction_id', 'نامشخص')}

❌ **وضعیت:** پرداخت ناموفق
            """
        
        elif report_type == "panel_connection_failed":
            return f"""
🔌 **خطا در اتصال به پنل**

⏰ **زمان:** {timestamp}
🔗 **نام پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **آدرس:** {data.get('panel_url', 'نامشخص')}
📝 **پیام خطا:** {data.get('error_message', 'نامشخص')}
👤 **کاربر:** {user_info.get('first_name', 'نامشخص') if user_info else 'سیستم'}

❌ **وضعیت:** اتصال ناموفق
            """
        
        elif report_type == "service_volume_70_percent":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
⚠️ **هشدار مصرف ۷۰ درصد حجم**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔗 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📊 **مصرف فعلی:** {data.get('usage_percentage', 0):.2f}%
📦 **حجم کل:** {data.get('total_gb', 0):.2f} گیگابایت
♾ **حجم باقی‌مانده:** {data.get('remaining_gb', 0):.2f} گیگابایت
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}

⚠️ **وضعیت:** کاربر ۷۰ درصد حجم خود را مصرف کرده است
            """
        
        elif report_type == "service_volume_exhausted":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
🚫 **تمام شدن حجم سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔗 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📊 **مصرف:** {data.get('usage_percentage', 100):.2f}%
📦 **حجم کل:** {data.get('total_gb', 0):.2f} گیگابایت
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}

🚫 **وضعیت:** حجم سرویس تمام شده و سرویس غیرفعال شد
⏰ **مهلت:** ۲۴ ساعت برای تمدید
            """
        
        elif report_type == "service_auto_deleted":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            reason = data.get('reason', 'عدم تمدید بعد از ۲۴ ساعت')
            if 'exhausted_at' in data:
                reason = 'تمام شدن حجم - عدم تمدید بعد از ۲۴ ساعت'
            elif 'expired_at' in data:
                reason = 'تمام شدن زمان - عدم تمدید بعد از ۲۴ ساعت'
            
            return f"""
🗑️ **حذف خودکار سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔗 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📦 **حجم:** {data.get('total_gb', 0):.2f} گیگابایت
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}
📅 **زمان اتمام:** {data.get('exhausted_at') or data.get('expired_at', 'نامشخص')}
📝 **دلیل:** {reason}

⚠️ **وضعیت:** سرویس به دلیل عدم تمدید بعد از ۲۴ ساعت حذف شد
            """
        
        elif report_type == "service_expired":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
⏰ **تمام شدن زمان سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔗 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📅 **تاریخ انقضا:** {data.get('expires_at', 'نامشخص')}
📦 **حجم:** {data.get('total_gb', 0):.2f} گیگابایت
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}

⚠️ **وضعیت:** زمان سرویس تمام شده و سرویس غیرفعال شد
⏰ **مهلت:** ۲۴ ساعت برای تمدید
            """
        
        elif report_type == "service_expiring_soon":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
⚠️ **هشدار انقضای سرویس (۳ روز)**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔗 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📅 **تاریخ انقضا:** {data.get('expires_at', 'نامشخص')}
⏰ **زمان باقی‌مانده:** {data.get('remaining_days', 0)} روز
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}

⚠️ **وضعیت:** زمان سرویس تا ۳ روز دیگر به پایان می‌رسد
            """
        
        elif report_type == "panel_change":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            # Add inbound information
            old_inbound_info = ""
            new_inbound_info = ""
            if data.get('old_inbound_name'):
                old_inbound_info = f"\n🔌 **اینباند مبدا:** {data.get('old_inbound_name', 'نامشخص')}"
            if data.get('new_inbound_name'):
                new_inbound_info = f"\n🔌 **اینباند مقصد:** {data.get('new_inbound_name', 'نامشخص')}"
            
            return f"""
🌍 **تغییر لوکیشن/پنل سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔗 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📦 **حجم باقیمانده:** {data.get('remaining_gb', 0):.2f} گیگابایت
🔗 **پنل مبدا:** {data.get('old_panel_name', 'نامشخص')}{old_inbound_info}
🔗 **پنل مقصد:** {data.get('new_panel_name', 'نامشخص')}{new_inbound_info}

✅ **وضعیت:** تغییر لوکیشن با موفقیت انجام شد
            """
        
        elif report_type == "admin_balance_increase":
            admin_name = user_info.get('first_name', 'نامشخص') if user_info else 'ادمین'
            admin_username = f"@{user_info.get('username')}" if user_info and user_info.get('username') else 'بدون نام کاربری'
            
            target_user = data.get('target_user', {})
            target_name = target_user.get('first_name', 'نامشخص')
            target_username = f"@{target_user.get('username')}" if target_user.get('username') else 'بدون نام کاربری'
            target_id = target_user.get('telegram_id', 'نامشخص')
            
            return f"""
➕💰 **افزایش موجودی توسط ادمین**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {admin_name} ({admin_username})

👤 **کاربر هدف:** {target_name} ({target_username})
🆔 **آیدی کاربر:** {target_id}

💰 **موجودی قبلی:** {data.get('old_balance', 0):,} تومان
➕ **مبلغ افزایش:** {data.get('amount', 0):,} تومان
💰 **موجودی جدید:** {data.get('new_balance', 0):,} تومان

✅ **وضعیت:** افزایش موجودی موفق
            """
        
        elif report_type == "admin_balance_decrease":
            admin_name = user_info.get('first_name', 'نامشخص') if user_info else 'ادمین'
            admin_username = f"@{user_info.get('username')}" if user_info and user_info.get('username') else 'بدون نام کاربری'
            
            target_user = data.get('target_user', {})
            target_name = target_user.get('first_name', 'نامشخص')
            target_username = f"@{target_user.get('username')}" if target_user.get('username') else 'بدون نام کاربری'
            target_id = target_user.get('telegram_id', 'نامشخص')
            
            return f"""
➖💰 **کاهش موجودی توسط ادمین**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {admin_name} ({admin_username})

👤 **کاربر هدف:** {target_name} ({target_username})
🆔 **آیدی کاربر:** {target_id}

💰 **موجودی قبلی:** {data.get('old_balance', 0):,} تومان
➖ **مبلغ کاهش:** {data.get('amount', 0):,} تومان
💰 **موجودی جدید:** {data.get('new_balance', 0):,} تومان

✅ **وضعیت:** کاهش موجودی موفق
            """
        
        elif report_type == "broadcast_message":
            admin_name = user_info.get('first_name', 'نامشخص') if user_info else 'ادمین'
            admin_username = f"@{user_info.get('username')}" if user_info and user_info.get('username') else 'بدون نام کاربری'
            
            return f"""
📢 **ارسال پیام همگانی**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {admin_name} ({admin_username})

📊 **تعداد کل کاربران:** {data.get('total_users', 0):,}
✅ **ارسال موفق:** {data.get('success_count', 0):,}
❌ **ارسال ناموفق:** {data.get('failed_count', 0):,}
📈 **درصد موفقیت:** {data.get('success_rate', 0):.1f}%

📝 **متن پیام:**
{data.get('message_preview', 'پیام خالی')[:200]}...

✅ **وضعیت:** ارسال پیام همگانی انجام شد
            """
        
        elif report_type == "broadcast_forward":
            admin_name = user_info.get('first_name', 'نامشخص') if user_info else 'ادمین'
            admin_username = f"@{user_info.get('username')}" if user_info and user_info.get('username') else 'بدون نام کاربری'
            
            return f"""
📤 **فوروارد همگانی**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {admin_name} ({admin_username})

📊 **تعداد کل کاربران:** {data.get('total_users', 0):,}
✅ **فوروارد موفق:** {data.get('success_count', 0):,}
❌ **فوروارد ناموفق:** {data.get('failed_count', 0):,}
📈 **درصد موفقیت:** {data.get('success_rate', 0):.1f}%

✅ **وضعیت:** فوروارد همگانی انجام شد
            """
        
        elif report_type == "admin_view_user_info":
            admin_name = user_info.get('first_name', 'نامشخص') if user_info else 'ادمین'
            admin_username = f"@{user_info.get('username')}" if user_info and user_info.get('username') else 'بدون نام کاربری'
            
            target_user = data.get('target_user', {})
            target_name = target_user.get('first_name', 'نامشخص')
            target_username = f"@{target_user.get('username')}" if target_user.get('username') else 'بدون نام کاربری'
            
            return f"""
👁️ **مشاهده اطلاعات کاربر توسط ادمین**

⏰ **زمان:** {timestamp}
👨‍💼 **ادمین:** {admin_name} ({admin_username})

👤 **کاربر مشاهده شده:** {target_name} ({target_username})
🆔 **آیدی:** {target_user.get('telegram_id', 'نامشخص')}
💰 **موجودی:** {target_user.get('balance', 0):,} تومان
🔧 **تعداد سرویس‌ها:** {target_user.get('total_services', 0)}

📊 **وضعیت:** مشاهده انجام شد
            """
        
        elif report_type == "volume_added":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            payment_method = data.get('payment_method', 'نامشخص')
            payment_method_text = "💳 درگاه بانکی" if payment_method == 'gateway' else "💰 موجودی حساب"
            
            return f"""
📈 **افزایش حجم سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔧 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📊 **حجم اضافه شده:** {data.get('volume_added', 0)} گیگابایت
📈 **حجم قبلی:** {data.get('old_volume', 0):.2f} گیگابایت
📈 **حجم جدید:** {data.get('new_volume', 0):.2f} گیگابایت
💰 **مبلغ:** {data.get('amount', 0):,} تومان
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}
💳 **روش پرداخت:** {payment_method_text}

✅ **وضعیت:** افزایش حجم موفق
            """
        
        elif report_type == "subscription_link_retrieved":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            return f"""
🔗 **دریافت لینک جدید سرویس**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
🔧 **نام سرویس:** {data.get('service_name', 'نامشخص')}
📊 **حجم:** {data.get('total_gb', 0):.2f} گیگابایت
🔗 **پنل:** {data.get('panel_name', 'نامشخص')}
🌐 **پروتکل:** {data.get('protocol', 'نامشخص').upper()}

✅ **وضعیت:** لینک سرویس دریافت شد
            """
        
        elif report_type == "balance_recharged":
            username_display = f"@{user_info.get('username')}" if user_info and user_info.get('username') else "بدون نام کاربری"
            user_display_name = user_info.get('first_name', 'نامشخص') if user_info else 'نامشخص'
            if user_info and user_info.get('last_name'):
                user_display_name += f" {user_info.get('last_name')}"
            
            payment_method = data.get('payment_method', 'gateway')
            payment_method_text = "💳 درگاه بانکی" if payment_method == 'gateway' else "💰 روش دیگر"
            
            return f"""
💳 **شارژ حساب کاربری**

⏰ **زمان:** {timestamp}
👤 **کاربر:** {user_display_name} ({username_display})
🆔 **آیدی عددی:** {user_info.get('telegram_id', 'نامشخص') if user_info else 'نامشخص'}
💰 **مبلغ شارژ:** {data.get('amount', 0):,} تومان
💵 **موجودی قبلی:** {data.get('old_balance', 0):,} تومان
💵 **موجودی جدید:** {data.get('new_balance', 0):,} تومان
💳 **روش پرداخت:** {payment_method_text}
🆔 **شناسه تراکنش:** {data.get('transaction_id', 'نامشخص')}

✅ **وضعیت:** شارژ موفق
            """
        
        else:
            return f"""
📋 **گزارش عمومی**

⏰ **زمان:** {timestamp}
🔧 **نوع گزارش:** {report_type}
📊 **اطلاعات:** {data}
👤 **کاربر:** {user_info.get('first_name', 'نامشخص') if user_info else 'سیستم'}

ℹ️ **وضعیت:** گزارش ارسال شد
            """
    
    # Convenience methods for different report types
    async def report_bot_start(self):
        """Report bot startup"""
        await self.send_report("bot_start", {})
    
    async def report_user_registration(self, user_data: Dict, referrer_data: Dict = None):
        """Report new user registration with referrer info"""
        report_data = user_data.copy()
        if referrer_data:
            report_data['referrer_id'] = referrer_data.get('id')
            report_data['referrer_telegram_id'] = referrer_data.get('telegram_id')
            report_data['referrer_username'] = referrer_data.get('username', 'بدون نام کاربری')
            report_data['referrer_name'] = referrer_data.get('first_name', 'نامشخص')
            if referrer_data.get('last_name'):
                report_data['referrer_name'] += f" {referrer_data.get('last_name')}"
        await self.send_report("user_registration", report_data)
    
    async def report_balance_added(self, user_data: Dict, amount: int, new_balance: int, payment_method: str):
        """Report balance addition"""
        data = {
            'amount': amount,
            'new_balance': new_balance,
            'payment_method': payment_method
        }
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
        data = {
            'user_id': user_data.get('telegram_id'),
            'error_type': error_type,
            'error_message': error_message,
            'action': action
        }
        await self.send_report("user_error", data, user_data)
    
    async def report_system_error(self, error_type: str, error_message: str, component: str, severity: str = "متوسط"):
        """Report system error"""
        data = {
            'error_type': error_type,
            'error_message': error_message,
            'component': component,
            'severity': severity
        }
        await self.send_report("system_error", data)
    
    async def report_payment_failed(self, user_data: Dict, amount: int, payment_method: str, error_message: str, transaction_id: str = None):
        """Report payment failure"""
        data = {
            'amount': amount,
            'payment_method': payment_method,
            'error_message': error_message,
            'transaction_id': transaction_id
        }
        await self.send_report("payment_failed", data, user_data)
    
    async def report_panel_connection_failed(self, panel_data: Dict, error_message: str, user_data: Dict = None):
        """Report panel connection failure"""
        data = {
            'panel_name': panel_data.get('name', 'نامشخص'),
            'panel_url': panel_data.get('url', 'نامشخص'),
            'error_message': error_message
        }
        await self.send_report("panel_connection_failed", data, user_data)
    
    async def report_service_volume_70_percent(self, user_data: Dict, service_data: Dict):
        """Report service reaching 70% volume usage"""
        await self.send_report("service_volume_70_percent", service_data, user_data)
    
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
        """Report service expiring soon (3 days warning)"""
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