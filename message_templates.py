"""
Professional Message Templates
Beautiful, consistent, and professional messages for the VPN bot
Supports customizable texts via TextManager
"""

from typing import Dict, List, Optional
from username_formatter import UsernameFormatter
import threading

class MessageTemplates:
    # Class-level TextManager instance (optional)
    _text_manager = None
    # Class-level database_name (for bot instances)
    _database_name = None
    # Thread-local storage for bot-specific database names
    _thread_local = threading.local()
    
    @classmethod
    def set_text_manager(cls, text_manager):
        """Set TextManager instance for custom texts"""
        cls._text_manager = text_manager
        # Also store database_name from the TextManager's db instance
        if text_manager and hasattr(text_manager, 'db') and hasattr(text_manager.db, 'database_name'):
            cls._database_name = text_manager.db.database_name
            # Store in thread-local storage for this bot instance
            cls._thread_local.database_name = text_manager.db.database_name
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"✅ MessageTemplates: Set database_name to '{cls._database_name}' from TextManager (thread-local: {getattr(cls._thread_local, 'database_name', None)})")
    
    @classmethod
    def set_database_name(cls, database_name: str):
        """Set database name for current thread (bot instance)"""
        cls._thread_local.database_name = database_name
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"🔍 MessageTemplates: Set thread-local database_name to '{database_name}'")
    
    @classmethod
    def _get_text(cls, text_key: str, variables: Dict = None) -> str:
        """Get text from TextManager if available, otherwise use default"""
        import logging
        logger = logging.getLogger(__name__)
        
        # Always try to get from database first - create TextManager on the fly if needed
        text_content = None
        
        try:
            # Try to get database and TextManager
            from professional_database import ProfessionalDatabaseManager
            from config import MYSQL_CONFIG
            from text_manager import TextManager
            
            # Priority 1: Try to get database_name from Flask request context (webapp)
            db_name = None
            try:
                from flask import g
                if hasattr(g, 'bot_config') and g.bot_config:
                    db_name = g.bot_config.get('database_name')
                    if db_name:
                        logger.debug(f"🔍 MessageTemplates: Got database_name '{db_name}' from Flask g.bot_config")
            except:
                pass
            
            # Priority 2: Use thread-local database_name (set by current bot instance)
            if not db_name:
                try:
                    db_name = getattr(cls._thread_local, 'database_name', None)
                    if db_name:
                        logger.debug(f"🔍 MessageTemplates: Using thread-local database_name '{db_name}'")
                except:
                    pass
            
            # Priority 3: Use class-level database_name (fallback, but may be wrong in multi-bot)
            if not db_name and cls._database_name:
                db_name = cls._database_name
                logger.warning(f"⚠️ MessageTemplates: Using class-level database_name '{db_name}' (may be incorrect in multi-bot mode)")
            
            # Create database instance with correct database_name
            if db_name:
                mysql_config = MYSQL_CONFIG.copy()
                mysql_config['database'] = db_name
                db = ProfessionalDatabaseManager(db_config=mysql_config)
                logger.debug(f"🔍 MessageTemplates: Created DB instance for database '{db_name}'")
            else:
                db = ProfessionalDatabaseManager(db_config=MYSQL_CONFIG)
                logger.warning(f"⚠️ MessageTemplates: No database_name found, using default database '{db.database_name}'")
            
            # Create a fresh TextManager instance (no cache, always reads from DB)
            text_manager = TextManager(db)
            
            # Get text directly from database
            text_content = text_manager.get_text(text_key, variables, use_default_if_missing=False)
            
            if text_content:
                logger.info(f"✅ Loaded text '{text_key}' from database '{db.database_name}' (length: {len(text_content)})")
                return text_content
            else:
                logger.debug(f"ℹ️ Text '{text_key}' not found in database '{db.database_name}', will use default")
                
        except Exception as e:
            logger.warning(f"⚠️ Error getting text '{text_key}' from database: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Priority 3: If we have a class-level TextManager, use it directly (it's already configured with correct database)
        if not text_content and cls._text_manager:
            try:
                text_content = cls._text_manager.get_text(text_key, variables, use_default_if_missing=True)
                if text_content:
                    db_name_used = getattr(cls._text_manager.db, 'database_name', 'unknown') if hasattr(cls._text_manager, 'db') else 'unknown'
                    logger.info(f"✅ Got text '{text_key}' from class TextManager (database: '{db_name_used}', length: {len(text_content)})")
                    return text_content
            except Exception as e:
                logger.warning(f"⚠️ Error getting text from class TextManager: {e}")
        
        # Fallback to default
        logger.debug(f"ℹ️ Using default text for '{text_key}'")
        return None
    """Professional message templates with consistent styling"""
    
    # Welcome messages
    WELCOME_MESSAGES = {
        'force_join': """
📢 *برای استفاده از ربات {bot_name}، لطفاً ابتدا در کانال ما عضو شوید*

🔹 *چرا عضویت در کانال؟*
• دریافت آخرین اخبار و به‌روزرسانی‌ها
• اطلاع از تخفیف‌ها و پیشنهادات ویژه
• آموزش‌های رایگان و نکات کاربردی
• پشتیبانی سریع‌تر و اولویت‌دار

✅ *مراحل فعال‌سازی:*
۱. روی دکمه زیر کلیک کنید
۲. وارد کانال شوید و عضو شوید
۳. به ربات برگردید و دوباره /start را بزنید

🌐 *{bot_name} | دریچه‌ای به دنیای آزاد*
        """,
        
        'main': """
🎉 *به {bot_name} خوش آمدید*

🔐 *دریچه‌ای به دنیای آزاد اینترنت*
• سرویس‌های VPN با کیفیت بالا و سرعت استثنایی
• سرورهای پرسرعت و پایدار در سراسر جهان
• پشتیبانی ۲۴ ساعته و تخصصی
• قیمت‌های عادلانه و رقابتی

🚀 *برای شروع، یکی از گزینه‌های زیر را انتخاب کنید:*
        """,
        
        'admin': """
👑 *پنل مدیریت {bot_name} - خوش آمدید*

🔧 *ابزارهای مدیریتی در دسترس:*
• مدیریت کاربران و سرویس‌ها
• نظارت بر عملکرد سیستم
• تنظیمات پیشرفته
• گزارش‌گیری جامع

⚙️ *دسترسی کامل به تمامی امکانات*
        """,
        
        'returning_user': """
👋 *سلام! به {bot_name} خوش برگشتید*

📊 *وضعیت حساب شما:*
• سرویس‌های فعال: {active_services}
• موجودی: {balance}
• آخرین فعالیت: {last_activity}

🎯 *چه کاری می‌خواهید انجام دهید؟*
        """
    }
    
    # Service messages
    SERVICE_MESSAGES = {
        'purchase_success': """
✅ *خرید سرویس با موفقیت انجام شد!*

🎉 *جزئیات سرویس جدید:*
🔗 پنل: {panel_name}
📊 حجم: {data_amount} گیگابایت
💰 مبلغ پرداخت: {amount:,} تومان
⏰ تاریخ خرید: {purchase_date}

🚀 *سرویس شما آماده استفاده است!*
        """,
        
        'renewal_success': """
✅ *تمدید سرویس با موفقیت انجام شد!*

🔄 *جزئیات تمدید:*
🔗 پنل: {panel_name}
📊 حجم اضافه شده: {additional_data} گیگابایت
📈 حجم کل جدید: {total_data} گیگابایت
💰 مبلغ پرداخت: {amount:,} تومان

🎯 *سرویس شما تمدید شد و آماده استفاده است!*
        """,
        
        'service_details': """
📋 *جزئیات سرویس شما*

🔧 نام سرویس: {service_name}
🔗 پنل: {panel_name}
📊 وضعیت: {status}
🌐 وضعیت اتصال: {connection_status}

📈 *اطلاعات ترافیک:*
• حجم کل: {total_data}
• مصرف شده: {used_data}
• باقی‌مانده: {remaining_data}

⏰ زمان باقی‌مانده: {time_remaining}

🎯 *مدیریت سرویس:*
        """,
        
        'service_expired': """
⏰ *هشدار: سرویس منقضی شده*

🔴 *سرویس شما منقضی شده است:*
• نام سرویس: {service_name}
• تاریخ انقضا: {expiry_date}
• حجم باقی‌مانده: {remaining_data}

🔄 *برای ادامه استفاده، سرویس را تمدید کنید:*
        """,
        
        'service_low_traffic': """
⚠️ *هشدار: ترافیک کم*

🟡 *ترافیک سرویس شما کم است:*
• نام سرویس: {service_name}
• ترافیک باقی‌مانده: {remaining_data}
• درصد مصرف: {usage_percentage}%

🔄 *برای ادامه استفاده، سرویس را تمدید کنید:*
        """
    }
    
    # Payment messages
    PAYMENT_MESSAGES = {
        'payment_success': """
✅ *پرداخت با موفقیت انجام شد!*

💰 *جزئیات پرداخت:*
• مبلغ: {amount:,} تومان
• روش پرداخت: {payment_method}
• شماره تراکنش: {transaction_id}
• تاریخ: {payment_date}

🎉 *موجودی شما به‌روزرسانی شد!*
        """,
        
        'payment_failed': """
❌ *پرداخت ناموفق*

🔴 *خطا در پردازش پرداخت:*
• مبلغ: {amount:,} تومان
• خطا: {error_message}

🔄 *لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.*
        """,
        
        'insufficient_balance': """
💰 *موجودی ناکافی*

🔴 *موجودی شما کافی نیست:*
• موجودی فعلی: {current_balance:,} تومان
• مبلغ مورد نیاز: {required_amount:,} تومان
• کمبود: {shortage:,} تومان

💳 *لطفاً موجودی خود را افزایش دهید:*
        """,
        
        'balance_added': """
💰 *موجودی اضافه شد!*

✅ *موجودی شما افزایش یافت:*
• مبلغ اضافه شده: {amount:,} تومان
• موجودی قبلی: {old_balance:,} تومان
• موجودی جدید: {new_balance:,} تومان

🎉 *حالا می‌توانید سرویس خریداری کنید!*
        """
    }
    
    # Error messages
    ERROR_MESSAGES = {
        'general_error': """
❌ *خطا در سیستم*

🔴 *متأسفانه خطایی رخ داده است:*
• پیام خطا: {error_message}
• کد خطا: {error_code}

🔄 *لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.*
        """,
        
        'service_not_found': """
🔍 *سرویس یافت نشد*

❌ *سرویس مورد نظر یافت نشد:*
• شناسه سرویس: {service_id}
• وضعیت: ناموجود یا حذف شده

🔄 *لطفاً سرویس‌های خود را بررسی کنید.*
        """,
        
        'panel_connection_failed': """
🔌 *خطا در اتصال به پنل*

❌ *امکان اتصال به پنل وجود ندارد:*
• نام پنل: {panel_name}
• خطا: {error_message}

🔄 *لطفاً بعداً دوباره تلاش کنید.*
        """,
        
        'user_not_found': """
👤 *کاربر یافت نشد*

❌ *اطلاعات کاربر یافت نشد:*
• شناسه کاربر: {user_id}
• وضعیت: ناموجود یا حذف شده

🔄 *لطفاً دوباره وارد شوید.*
        """,
        
        'permission_denied': """
🚫 *دسترسی غیرمجاز*

❌ *شما دسترسی لازم را ندارید:*
• عملیات: {action}
• سطح دسترسی مورد نیاز: {required_level}

🔄 *لطفاً با مدیر سیستم تماس بگیرید.*
        """
    }
    
    # Success messages
    SUCCESS_MESSAGES = {
        'operation_success': """
✅ *عملیات با موفقیت انجام شد!*

🎉 *جزئیات عملیات:*
• نوع عملیات: {operation}
• تاریخ: {date}
• وضعیت: موفق

🚀 *همه چیز آماده است!*
        """,
        
        'settings_updated': """
⚙️ *تنظیمات به‌روزرسانی شد*

✅ *تغییرات اعمال شد:*
• تنظیمات: {settings}
• تاریخ: {date}
• وضعیت: فعال

🎯 *تنظیمات جدید از همین لحظه اعمال می‌شود.*
        """,
        
        'data_updated': """
📊 *اطلاعات به‌روزرسانی شد*

✅ *داده‌ها به‌روزرسانی شدند:*
• نوع داده: {data_type}
• تاریخ: {date}
• وضعیت: موفق

🔄 *اطلاعات جدید در دسترس است.*
        """
    }
    
    # Information messages
    INFO_MESSAGES = {
        'help_main': """
❓ *مرکز راهنما*

📚 *راهنمای استفاده از ربات:*

🛒 *خرید سرویس:*
• انتخاب پنل و حجم مورد نظر
• انتخاب روش پرداخت
• دریافت کانفیگ سرویس

📊 *مدیریت سرویس‌ها:*
• مشاهده جزئیات سرویس
• تمدید و ارتقا سرویس
• دریافت کانفیگ جدید

💰 *مدیریت موجودی:*
• مشاهده موجودی
• افزایش موجودی
• تاریخچه پرداخت‌ها

🔧 *پشتیبانی:*
• تماس با پشتیبانی
• گزارش مشکل
• پیشنهادات

💡 *نکات مهم:*
• سرویس‌ها خودکار منقضی می‌شوند
• کانفیگ‌ها قابل اشتراک‌گذاری نیستند
• از سرویس‌های خود محافظت کنید
        """,
        
        'balance_info': """
💰 *اطلاعات موجودی*

💳 *وضعیت حساب شما:*
• موجودی فعلی: {balance:,} تومان
• کل پرداخت‌ها: {total_payments:,} تومان
• آخرین تراکنش: {last_transaction}

📊 *تاریخچه تراکنش‌ها:*
• پرداخت‌های موفق: {successful_payments}
• پرداخت‌های ناموفق: {failed_payments}
• کل تراکنش‌ها: {total_transactions}

💡 *نکات:*
• موجودی قابل انتقال نیست
• تراکنش‌ها قابل بازگشت نیستند
• از موجودی خود محافظت کنید
        """,
        
        'service_info': """
🔧 *اطلاعات سرویس*

📋 *جزئیات کامل سرویس:*
• نام: {service_name}
• پنل: {panel_name}
• وضعیت: {status}
• تاریخ ایجاد: {created_date}

📊 *آمار ترافیک:*
• حجم کل: {total_data}
• مصرف شده: {used_data}
• باقی‌مانده: {remaining_data}
• درصد مصرف: {usage_percentage}%

⏰ *زمان‌بندی:*
• تاریخ انقضا: {expiry_date}
• زمان باقی‌مانده: {time_remaining}
• آخرین فعالیت: {last_activity}

🔗 *وضعیت اتصال:*
• وضعیت: {connection_status}
• سرعت: {speed}
• پینگ: {ping}
        """
    }
    
    # Notification messages
    NOTIFICATION_MESSAGES = {
        'service_expiring_soon': """
⏰ *هشدار: سرویس به زودی منقضی می‌شود*

🟡 *سرویس شما به زودی منقضی می‌شود:*
• نام سرویس: {service_name}
• زمان باقی‌مانده: {time_remaining}
• تاریخ انقضا: {expiry_date}

🔄 *برای ادامه استفاده، سرویس را تمدید کنید:*
        """,
        
        'traffic_80_percent': """
⚠️ *هشدار: ۸۰٪ ترافیک مصرف شده*

🟡 *ترافیک سرویس شما کم است:*
• نام سرویس: {service_name}
• ترافیک باقی‌مانده: {remaining_data}
• درصد مصرف: ۸۰٪

🔄 *برای ادامه استفاده، سرویس را تمدید کنید:*
        """,
        
        'traffic_95_percent': """
🚨 *هشدار: ۹۵٪ ترافیک مصرف شده*

🔴 *ترافیک سرویس شما بسیار کم است:*
• نام سرویس: {service_name}
• ترافیک باقی‌مانده: {remaining_data}
• درصد مصرف: ۹۵٪

🔄 *فوری: سرویس را تمدید کنید:*
        """,
        
        'new_service_available': """
🆕 *سرویس جدید در دسترس*

🎉 *سرویس جدیدی برای شما فعال شد:*
• نام سرویس: {service_name}
• حجم: {data_amount}
• پنل: {panel_name}

🚀 *سرویس شما آماده استفاده است!*
        """
    }
    
    @staticmethod
    def format_welcome_message(user_data: Dict, is_admin: bool = False, bot_name: str = "AzadJooNet") -> str:
        """Format welcome message based on user data"""
        import logging
        logger = logging.getLogger(__name__)
        
        variables = {'bot_name': bot_name}
        
        if is_admin:
            text = MessageTemplates._get_text('welcome.admin', variables)
            if text:
                logger.info("✅ Using customized text for 'welcome.admin'")
                return text
            logger.info("📝 Using default text for 'welcome.admin'")
            return MessageTemplates.WELCOME_MESSAGES['admin'].format(**variables)
        
        # Handle None user_data
        if user_data is None:
            user_data = {}
        
        # Check if returning user
        if user_data.get('total_services', 0) > 0:
            variables.update({
                'active_services': user_data.get('total_services', 0),
                'balance': UsernameFormatter.format_balance(user_data.get('balance', 0)),
                'last_activity': user_data.get('last_activity', 'نامشخص')
            })
            text = MessageTemplates._get_text('welcome.returning_user', variables)
            if text:
                logger.info("✅ Using customized text for 'welcome.returning_user'")
                return text
            logger.info("📝 Using default text for 'welcome.returning_user'")
            return MessageTemplates.WELCOME_MESSAGES['returning_user'].format(**variables)
        
        text = MessageTemplates._get_text('welcome.main', variables)
        if text:
            logger.info("✅ Using customized text for 'welcome.main'")
            return text
        logger.info("📝 Using default text for 'welcome.main'")
        return MessageTemplates.WELCOME_MESSAGES['main'].format(**variables)
    
    @staticmethod
    def format_service_success_message(service_data: Dict, payment_data: Dict) -> str:
        """Format service purchase success message"""
        variables = {
            'panel_name': service_data.get('panel_name', 'نامشخص'),
            'data_amount': service_data.get('data_amount', 0),
            'amount': payment_data.get('amount', 0),
            'purchase_date': service_data.get('created_at', 'نامشخص')
        }
        text = MessageTemplates._get_text('service.purchase_success', variables)
        if text:
            return text
        return MessageTemplates.SERVICE_MESSAGES['purchase_success'].format(**variables)
    
    @staticmethod
    def format_renewal_success_message(renewal_data: Dict) -> str:
        """Format service renewal success message"""
        variables = {
            'panel_name': renewal_data.get('panel_name', 'نامشخص'),
            'additional_data': renewal_data.get('additional_data', 0),
            'total_data': renewal_data.get('total_data', 0),
            'amount': renewal_data.get('amount', 0)
        }
        text = MessageTemplates._get_text('service.renewal_success', variables)
        if text:
            return text
        return MessageTemplates.SERVICE_MESSAGES['renewal_success'].format(**variables)
    
    @staticmethod
    def format_error_message(error_type: str, **kwargs) -> str:
        """Format error message"""
        text_key = f'error.{error_type}'
        text = MessageTemplates._get_text(text_key, kwargs)
        if text:
            return text
        template = MessageTemplates.ERROR_MESSAGES.get(error_type, MessageTemplates.ERROR_MESSAGES['general_error'])
        return template.format(**kwargs)
    
    @staticmethod
    def format_success_message(success_type: str, **kwargs) -> str:
        """Format success message"""
        text_key = f'success.{success_type}'
        text = MessageTemplates._get_text(text_key, kwargs)
        if text:
            return text
        template = MessageTemplates.SUCCESS_MESSAGES.get(success_type, MessageTemplates.SUCCESS_MESSAGES['operation_success'])
        return template.format(**kwargs)
    
    @staticmethod
    def format_notification_message(notification_type: str, **kwargs) -> str:
        """Format notification message"""
        text_key = f'notification.{notification_type}'
        text = MessageTemplates._get_text(text_key, kwargs)
        if text:
            return text
        template = MessageTemplates.NOTIFICATION_MESSAGES.get(notification_type)
        if template:
            return template.format(**kwargs)
        return "🔔 اعلان جدید"
    
    @staticmethod
    def format_help_message(help_type: str = 'main') -> str:
        """Format help message"""
        text_key = f'info.help_{help_type}'
        text = MessageTemplates._get_text(text_key)
        if text:
            return text
        return MessageTemplates.INFO_MESSAGES.get(help_type, MessageTemplates.INFO_MESSAGES['help_main'])
    
    @staticmethod
    def format_balance_message(user_data: Dict) -> str:
        """Format balance information message"""
        variables = {
            'balance': user_data.get('balance', 0),
            'total_payments': user_data.get('total_spent', 0),
            'last_transaction': user_data.get('last_activity', 'نامشخص'),
            'successful_payments': 0,  # TODO: Add to database
            'failed_payments': 0,      # TODO: Add to database
            'total_transactions': 0    # TODO: Add to database
        }
        text = MessageTemplates._get_text('info.balance_info', variables)
        if text:
            return text
        return MessageTemplates.INFO_MESSAGES['balance_info'].format(**variables)
    
    @staticmethod
    def format_service_details_message(service_data: Dict) -> str:
        """Format service details message"""
        variables = {
            'service_name': service_data.get('client_name', 'نامشخص'),
            'panel_name': service_data.get('panel_name', 'نامشخص'),
            'status': UsernameFormatter.format_status(service_data.get('status', 'نامشخص')),
            'created_date': service_data.get('created_at', 'نامشخص'),
            'total_data': UsernameFormatter.format_data_amount(service_data.get('total_gb', 0)),
            'used_data': UsernameFormatter.format_data_amount(service_data.get('used_gb', 0)),
            'remaining_data': UsernameFormatter.format_data_amount(service_data.get('remaining_gb', 0)),
            'usage_percentage': service_data.get('usage_percentage', 0),
            'expiry_date': service_data.get('expiry_date', 'نامشخص'),
            'time_remaining': UsernameFormatter.format_time_remaining(service_data.get('time_remaining', 0)),
            'last_activity': service_data.get('last_activity', 'نامشخص'),
            'connection_status': UsernameFormatter.format_connection_status(
                service_data.get('is_online', False),
                service_data.get('last_seen', 0)
            ),
            'speed': service_data.get('speed', 'نامشخص'),
            'ping': service_data.get('ping', 'نامشخص')
        }
        text = MessageTemplates._get_text('info.service_info', variables)
        if text:
            return text
        return MessageTemplates.INFO_MESSAGES['service_info'].format(**variables)

