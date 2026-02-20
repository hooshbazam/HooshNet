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
📢 **عضویت الزامی در کانال**

دوست عزیز، برای استفاده از ربات {bot_name} لازم است ابتدا در کانال ما عضو شوید.

**🔹 چرا عضو شوم؟**
✅ دریافت آخرین اخبار و اطلاعیه‌ها
✅ دسترسی به کدهای تخفیف ویژه
✅ آموزش‌های اتصال و رفع مشکل
✅ اطلاع از وضعیت سرورها

**👇 مراحل فعال‌سازی:**
1️⃣ روی دکمه زیر کلیک کنید.
2️⃣ در کانال عضو شوید (Join).
3️⃣ به ربات برگردید و مجدداً **start** را بزنید.

🌐 **{bot_name} | دروازه‌ای به اینترنت آزاد**
        """,
        
        'main': """
🎉 **به {bot_name} خوش آمدید!**

خوشحالیم که ما را انتخاب کردید. 🌹
ما در تلاشیم تا تجربه‌ای امن، پرسرعت و پایدار از اینترنت آزاد را برای شما فراهم کنیم.

**🚀 ویژگی‌های سرویس ما:**
⚡️ سرعت و پایداری بالا
🛡 امنیت و حریم خصوصی تضمین‌شده
📞 پشتیبانی پاسخگو و حرفه‌ای
💰 تعرفه‌های منصفانه و اقتصادی

**👇 برای شروع، لطفاً از منوی زیر انتخاب کنید:**
        """,
        
        'admin': """
👑 پنل مدیریت {bot_name}

🔧 ابزارهای مدیریتی:
• مدیریت کاربران و سرویس‌ها
• پایش عملکرد سیستم
• تنظیمات پیشرفته
• گزارش‌گیری جامع

⚙️ دسترسی کامل به تمامی امکانات سیستم
        """,
        
        'returning_user': """
👋 **سلام مجدد! خوش برگشتی** 🌹

به {bot_name} خوش آمدید. امیدواریم از سرویس‌ها راضی باشید.

**📊 وضعیت حساب شما در یک نگاه:**
🔹 **سرویس‌های فعال:** {active_services} عدد
🔹 **موجودی کیف پول:** {balance} تومان
🔹 **آخرین بازدید:** {last_activity}

**👇 چه کاری می‌خواهید انجام دهید؟**
        """
    }
    
    # Service messages
    SERVICE_MESSAGES = {
        'purchase_success': """
✅ **خرید سرویس با موفقیت انجام شد!** 🎉

ممنون از اعتماد شما. سرویس شما آماده استفاده است.

**📋 جزئیات سفارش:**
🔗 **نام پنل:** {panel_name}
📊 **حجم ترافیک:** {data_amount} گیگابایت
💰 **مبلغ پرداختی:** {amount:,} تومان
⏰ **تاریخ فعال‌سازی:** {purchase_date}

**🚀 همین حالا متصل شوید!**
برای دریافت کانفیگ، به بخش **داشبورد کاربری** مراجعه کنید.
        """,
        
        'renewal_success': """
✅ **تمدید سرویس با موفقیت انجام شد!** 🔄

سرویس شما با موفقیت شارژ شد و می‌توانید به استفاده ادامه دهید.

**📋 جزئیات تمدید:**
🔗 **نام پنل:** {panel_name}
➕ **حجم افزوده شده:** {additional_data} گیگابایت
📈 **حجم کل جدید:** {total_data} گیگابایت
💰 **مبلغ پرداختی:** {amount:,} تومان

**🌹 از همراهی شما سپاسگزاریم!**
        """,
        
        'service_details': """
📋 جزئیات سرویس شما

🔧 نام سرویس: {service_name}
🔗 نام پنل: {panel_name}
📊 وضعیت: {status}
🌐 وضعیت اتصال: {connection_status}

📈 اطلاعات مصرف ترافیک:
• حجم کل: {total_data}
• مصرف شده: {used_data}
• باقی‌مانده: {remaining_data}

⏰ زمان باقی‌مانده: {time_remaining}

🎯 گزینه‌های مدیریت سرویس:
        """,
        
        'service_expired': """
⏰ هشدار: انقضای سرویس

🔴 مهلت استفاده از سرویس شما به پایان رسیده است:
• نام سرویس: {service_name}
• تاریخ انقضا: {expiry_date}
• حجم باقی‌مانده: {remaining_data}

🔄 لطفاً جهت ادامه استفاده، سرویس خود را تمدید کنید:
        """,
        
        'service_low_traffic': """
⚠️ هشدار: اتمام حجم ترافیک

🟡 حجم ترافیک سرویس شما رو به اتمام است:
• نام سرویس: {service_name}
• ترافیک باقی‌مانده: {remaining_data}
• درصد مصرف: {usage_percentage}٪

🔄 لطفاً جهت ادامه استفاده، سرویس خود را تمدید کنید:
        """
    }
    
    # Payment messages
    PAYMENT_MESSAGES = {
        'payment_success': """
✅ **پرداخت با موفقیت انجام شد!** 💳

تراکنش شما تایید شد و مبلغ به حساب شما اضافه گردید.

**🧾 رسید تراکنش:**
💰 **مبلغ:** {amount:,} تومان
روش پرداخت: {payment_method}
🔢 شماره پیگیری: `{transaction_id}`
📅 زمان: {payment_date}

**🎉 موجودی کیف پول شما به‌روز شد.**
        """,
        
        'payment_failed': """
❌ **پرداخت ناموفق بود!**

متأسفانه عملیات پرداخت تکمیل نشد. 😔

**🔍 جزئیات خطا:**
💰 **مبلغ:** {amount:,} تومان
⚠️ **علت:** {error_message}

**🔄 پیشنهاد:**
لطفاً دقایقی دیگر مجدداً تلاش کنید یا در صورت کسر وجه، با پشتیبانی تماس بگیرید.
        """,
        
        'insufficient_balance': """
💰 **موجودی حساب کافی نیست!**

برای انجام این عملیات، نیاز به افزایش اعتبار دارید.

**📊 وضعیت اعتبار:**
🔸 **موجودی فعلی:** {current_balance:,} تومان
🔸 **مبلغ مورد نیاز:** {required_amount:,} تومان
🔻 **کسری:** {shortage:,} تومان

**💳 همین حالا موجودی خود را افزایش دهید:**
        """,
        
        'balance_added': """
💰 **افزایش موجودی موفق!** 🎉

حساب شما با موفقیت شارژ شد.

**📊 وضعیت جدید:**
➕ **مبلغ افزوده شده:** {amount:,} تومان
💰 **موجودی قبلی:** {old_balance:,} تومان
✅ **موجودی فعلی:** {new_balance:,} تومان

**🛍 حالا می‌توانید با خیال راحت خرید کنید!**
        """
    }
    
    # Error messages
    ERROR_MESSAGES = {
        'general_error': """
❌ خطای سیستمی

🔴 متأسفانه مشکلی پیش آمده است:
• پیام خطا: {error_message}
• کد خطا: {error_code}

🔄 لطفاً مجدداً تلاش کنید یا با پشتیبانی تماس بگیرید
        """,
        
        'service_not_found': """
🔍 سرویس یافت نشد

❌ اطلاعات سرویس مورد نظر در سیستم موجود نیست:
• شناسه سرویس: {service_id}
• وضعیت: ناموجود یا حذف شده

🔄 لطفاً لیست سرویس‌های خود را بررسی کنید
        """,
        
        'panel_connection_failed': """
🔌 خطا در برقراری ارتباط

❌ امکان اتصال به سرور پنل وجود ندارد:
• نام پنل: {panel_name}
• جزئیات خطا: {error_message}

🔄 لطفاً دقایقی دیگر مجدداً تلاش کنید
        """,
        
        'user_not_found': """
👤 کاربر ناشناس

❌ اطلاعات حساب کاربری یافت نشد:
• شناسه کاربر: {user_id}
• وضعیت: ناموجود یا حذف شده

🔄 لطفاً مجدداً وارد ربات شوید (Start/)
        """,
        
        'permission_denied': """
🚫 دسترسی غیرمجاز

❌ شما مجوز لازم برای انجام این عملیات را ندارید:
• نوع عملیات: {action}
• سطح دسترسی مورد نیاز: {required_level}

🔄 لطفاً با مدیریت سیستم تماس بگیرید
        """
    }
    
    # Success messages
    SUCCESS_MESSAGES = {
        'operation_success': """
✅ عملیات با موفقیت انجام شد

🎉 جزئیات عملیات:
• نوع عملیات: {operation}
• تاریخ و زمان: {date}
• وضعیت: موفق

🚀 درخواست شما با موفقیت ثبت شد
        """,
        
        'settings_updated': """
⚙️ تنظیمات به‌روزرسانی شد

✅ تغییرات با موفقیت اعمال شد:
• تنظیمات تغییر یافته: {settings}
• تاریخ و زمان: {date}
• وضعیت: فعال

🎯 تنظیمات جدید هم‌اکنون در سیستم فعال است
        """,
        
        'data_updated': """
📊 اطلاعات به‌روزرسانی شد

✅ داده‌ها با موفقیت ذخیره شدند:
• نوع داده: {data_type}
• تاریخ و زمان: {date}
• وضعیت: موفق

🔄 اطلاعات جدید هم‌اکنون در دسترس است
        """
    }
    
    # Information messages
    INFO_MESSAGES = {
        'help_main': """
❓ مرکز راهنما

📚 راهنمای استفاده از خدمات:

🛒 خرید سرویس:
• انتخاب پنل و حجم مورد نظر
• انتخاب روش پرداخت
• دریافت آنی کانفیگ سرویس

📊 مدیریت سرویس‌ها:
• مشاهده جزئیات و وضعیت سرویس
• تمدید و ارتقای سرویس
• دریافت لینک اتصال جدید

💰 مدیریت مالی:
• مشاهده موجودی کیف پول
• افزایش اعتبار
• مشاهده تاریخچه تراکنش‌ها

🔧 پشتیبانی:
• ارتباط با واحد پشتیبانی
• گزارش مشکلات فنی
• ارسال پیشنهادات و انتقادات

💡 نکات مهم:
• سرویس‌ها در تاریخ مقرر منقضی می‌شوند
• لینک‌های اتصال اختصاصی هستند
• از اشتراک‌گذاری سرویس خودداری کنید
        """,
        
        'balance_info': """
💰 اطلاعات مالی

💳 وضعیت کیف پول:
• موجودی فعلی: {balance:,} تومان
• مجموع پرداختی‌ها: {total_payments:,} تومان
• آخرین تراکنش: {last_transaction}

📊 آمار تراکنش‌ها:
• تراکنش‌های موفق: {successful_payments}
• تراکنش‌های ناموفق: {failed_payments}
• مجموع تراکنش‌ها: {total_transactions}

💡 راهنما:
• موجودی کیف پول غیرقابل انتقال است
• امکان استرداد وجه شارژ شده وجود ندارد
• برای خرید سرویس از موجودی خود استفاده کنید
        """,
        
        'service_info': """
🔧 اطلاعات سرویس

📋 مشخصات سرویس:
• نام سرویس: {service_name}
• سرور میزبان: {panel_name}
• وضعیت فعلی: {status}
• تاریخ فعال‌سازی: {created_date}

📊 مصرف ترافیک:
• حجم کل: {total_data}
• مصرف شده: {used_data}
• باقی‌مانده: {remaining_data}
• درصد مصرف: {usage_percentage}٪

⏰ وضعیت زمانی:
• تاریخ انقضا: {expiry_date}
• زمان باقی‌مانده: {time_remaining}
• آخرین اتصال: {last_activity}

🔗 وضعیت شبکه:
• اتصال: {connection_status}
• سرعت دانلود: {speed}
• تاخیر شبکه (Ping): {ping}
        """
    }
    
    # Notification messages
    NOTIFICATION_MESSAGES = {
        'service_expiring_soon': """
⏰ هشدار: انقضای سرویس

🟡 سرویس شما به زودی منقضی خواهد شد:
• نام سرویس: {service_name}
• زمان باقی‌مانده: {time_remaining}
• تاریخ انقضا: {expiry_date}

🔄 لطفاً جهت ادامه استفاده، نسبت به تمدید سرویس اقدام کنید:
        """,
        
        'traffic_80_percent': """
⚠️ هشدار مصرف ترافیک

🟡 ۸۰٪ از حجم سرویس شما مصرف شده است:
• نام سرویس: {service_name}
• ترافیک باقی‌مانده: {remaining_data}
• وضعیت مصرف: ۸۰٪

🔄 لطفاً جهت جلوگیری از قطع سرویس، آن را تمدید کنید:
        """,
        
        'traffic_95_percent': """
🚨 هشدار مهم: اتمام حجم

🔴 ۹۵٪ از حجم سرویس شما مصرف شده است:
• نام سرویس: {service_name}
• ترافیک باقی‌مانده: {remaining_data}
• وضعیت مصرف: ۹۵٪

🔄 لطفاً هرچه سریع‌تر نسبت به تمدید سرویس اقدام کنید:
        """,
        
        'new_service_available': """
🆕 سرویس جدید فعال شد

🎉 مشخصات سرویس جدید شما:
• نام سرویس: {service_name}
• حجم ترافیک: {data_amount}
• سرور میزبان: {panel_name}

🚀 سرویس شما هم‌اکنون آماده استفاده است
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

