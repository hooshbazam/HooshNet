"""
Professional Text Manager for VPN Bot
Manages customizable bot texts with variable substitution support
"""

import logging
from typing import Dict, List, Optional, Any
from message_templates import MessageTemplates
from professional_database import ProfessionalDatabaseManager

logger = logging.getLogger(__name__)

class TextManager:
    """
    Professional text manager that handles:
    - Loading texts from database with fallback to defaults
    - Variable substitution in texts
    - Text formatting and validation
    """
    
    # Define all available text keys and their default values from MessageTemplates
    TEXT_DEFINITIONS = {
        # Welcome messages
        'welcome.force_join': {
            'category': 'welcome',
            'default': MessageTemplates.WELCOME_MESSAGES['force_join'],
            'variables': ['bot_name'],
            'description': 'پیام اجباری برای عضویت در کانال'
        },
        'welcome.main': {
            'category': 'welcome',
            'default': MessageTemplates.WELCOME_MESSAGES['main'],
            'variables': ['bot_name'],
            'description': 'پیام خوش‌آمدگویی اصلی'
        },
        'welcome.admin': {
            'category': 'welcome',
            'default': MessageTemplates.WELCOME_MESSAGES['admin'],
            'variables': ['bot_name'],
            'description': 'پیام خوش‌آمدگویی برای ادمین'
        },
        'welcome.returning_user': {
            'category': 'welcome',
            'default': MessageTemplates.WELCOME_MESSAGES['returning_user'],
            'variables': ['bot_name', 'active_services', 'balance', 'last_activity'],
            'description': 'پیام خوش‌آمدگویی برای کاربر بازگشتی'
        },
        
        # Service messages
        'service.purchase_success': {
            'category': 'service',
            'default': MessageTemplates.SERVICE_MESSAGES['purchase_success'],
            'variables': ['panel_name', 'data_amount', 'amount', 'purchase_date'],
            'description': 'پیام موفقیت خرید سرویس'
        },
        'service.renewal_success': {
            'category': 'service',
            'default': MessageTemplates.SERVICE_MESSAGES['renewal_success'],
            'variables': ['panel_name', 'additional_data', 'total_data', 'amount'],
            'description': 'پیام موفقیت تمدید سرویس'
        },
        'service.service_details': {
            'category': 'service',
            'default': MessageTemplates.SERVICE_MESSAGES['service_details'],
            'variables': ['service_name', 'panel_name', 'status', 'connection_status', 
                         'total_data', 'used_data', 'remaining_data', 'time_remaining'],
            'description': 'جزئیات سرویس'
        },
        'service.service_expired': {
            'category': 'service',
            'default': MessageTemplates.SERVICE_MESSAGES['service_expired'],
            'variables': ['service_name', 'expiry_date', 'remaining_data'],
            'description': 'پیام انقضای سرویس'
        },
        'service.service_low_traffic': {
            'category': 'service',
            'default': MessageTemplates.SERVICE_MESSAGES['service_low_traffic'],
            'variables': ['service_name', 'remaining_data', 'usage_percentage'],
            'description': 'پیام هشدار ترافیک کم'
        },
        
        # Payment messages
        'payment.payment_success': {
            'category': 'payment',
            'default': MessageTemplates.PAYMENT_MESSAGES['payment_success'],
            'variables': ['amount', 'payment_method', 'transaction_id', 'payment_date'],
            'description': 'پیام موفقیت پرداخت'
        },
        'payment.payment_failed': {
            'category': 'payment',
            'default': MessageTemplates.PAYMENT_MESSAGES['payment_failed'],
            'variables': ['amount', 'error_message'],
            'description': 'پیام خطای پرداخت'
        },
        'payment.insufficient_balance': {
            'category': 'payment',
            'default': MessageTemplates.PAYMENT_MESSAGES['insufficient_balance'],
            'variables': ['current_balance', 'required_amount', 'shortage'],
            'description': 'پیام موجودی ناکافی'
        },
        'payment.balance_added': {
            'category': 'payment',
            'default': MessageTemplates.PAYMENT_MESSAGES['balance_added'],
            'variables': ['amount', 'old_balance', 'new_balance'],
            'description': 'پیام اضافه شدن موجودی'
        },
        
        # Error messages
        'error.general_error': {
            'category': 'error',
            'default': MessageTemplates.ERROR_MESSAGES['general_error'],
            'variables': ['error_message', 'error_code'],
            'description': 'خطای عمومی'
        },
        'error.service_not_found': {
            'category': 'error',
            'default': MessageTemplates.ERROR_MESSAGES['service_not_found'],
            'variables': ['service_id'],
            'description': 'سرویس یافت نشد'
        },
        'error.panel_connection_failed': {
            'category': 'error',
            'default': MessageTemplates.ERROR_MESSAGES['panel_connection_failed'],
            'variables': ['panel_name', 'error_message'],
            'description': 'خطا در اتصال به پنل'
        },
        'error.user_not_found': {
            'category': 'error',
            'default': MessageTemplates.ERROR_MESSAGES['user_not_found'],
            'variables': ['user_id'],
            'description': 'کاربر یافت نشد'
        },
        'error.permission_denied': {
            'category': 'error',
            'default': MessageTemplates.ERROR_MESSAGES['permission_denied'],
            'variables': ['action', 'required_level'],
            'description': 'دسترسی غیرمجاز'
        },
        
        # Success messages
        'success.operation_success': {
            'category': 'success',
            'default': MessageTemplates.SUCCESS_MESSAGES['operation_success'],
            'variables': ['operation', 'date'],
            'description': 'عملیات موفق'
        },
        'success.settings_updated': {
            'category': 'success',
            'default': MessageTemplates.SUCCESS_MESSAGES['settings_updated'],
            'variables': ['settings', 'date'],
            'description': 'تنظیمات به‌روزرسانی شد'
        },
        'success.data_updated': {
            'category': 'success',
            'default': MessageTemplates.SUCCESS_MESSAGES['data_updated'],
            'variables': ['data_type', 'date'],
            'description': 'اطلاعات به‌روزرسانی شد'
        },
        
        # Info messages
        'info.help_main': {
            'category': 'info',
            'default': MessageTemplates.INFO_MESSAGES['help_main'],
            'variables': [],
            'description': 'راهنمای اصلی'
        },
        'info.balance_info': {
            'category': 'info',
            'default': MessageTemplates.INFO_MESSAGES['balance_info'],
            'variables': ['balance', 'total_payments', 'last_transaction', 
                         'successful_payments', 'failed_payments', 'total_transactions'],
            'description': 'اطلاعات موجودی'
        },
        'info.service_info': {
            'category': 'info',
            'default': MessageTemplates.INFO_MESSAGES['service_info'],
            'variables': ['service_name', 'panel_name', 'status', 'created_date',
                         'total_data', 'used_data', 'remaining_data', 'usage_percentage',
                         'expiry_date', 'time_remaining', 'last_activity',
                         'connection_status', 'speed', 'ping'],
            'description': 'اطلاعات سرویس'
        },
        
        # Notification messages
        'notification.service_expiring_soon': {
            'category': 'notification',
            'default': MessageTemplates.NOTIFICATION_MESSAGES['service_expiring_soon'],
            'variables': ['service_name', 'time_remaining', 'expiry_date'],
            'description': 'هشدار انقضای نزدیک سرویس'
        },
        'notification.traffic_80_percent': {
            'category': 'notification',
            'default': MessageTemplates.NOTIFICATION_MESSAGES['traffic_80_percent'],
            'variables': ['service_name', 'remaining_data'],
            'description': 'هشدار مصرف ۸۰٪ ترافیک'
        },
        'notification.traffic_95_percent': {
            'category': 'notification',
            'default': MessageTemplates.NOTIFICATION_MESSAGES['traffic_95_percent'],
            'variables': ['service_name', 'remaining_data'],
            'description': 'هشدار مصرف ۹۵٪ ترافیک'
        },
        'notification.new_service_available': {
            'category': 'notification',
            'default': MessageTemplates.NOTIFICATION_MESSAGES['new_service_available'],
            'variables': ['service_name', 'data_amount', 'panel_name'],
            'description': 'اعلان سرویس جدید'
        },
    }
    
    def __init__(self, db: ProfessionalDatabaseManager = None):
        """Initialize TextManager with database connection"""
        self.db = db
        self._text_cache = {}  # Cache for loaded texts
        self._cache_enabled = False  # Disable cache for real-time updates
    
    def get_text(self, text_key: str, variables: Dict[str, Any] = None, 
                 use_default_if_missing: bool = True) -> str:
        """
        Get text by key with variable substitution
        Always gets fresh from database - no caching for real-time updates
        
        Args:
            text_key: The key of the text (e.g., 'welcome.main')
            variables: Dictionary of variables to substitute in the text
            use_default_if_missing: If True, use default text if not found in database
        
        Returns:
            Formatted text string
        """
        # Always get fresh text content from database (cache disabled)
        text_content = self._get_text_content(text_key, use_default_if_missing)
        
        if not text_content:
            logger.warning(f"Text not found: {text_key}")
            return f"[Text not found: {text_key}]"
        
        # Substitute variables if provided
        if variables:
            try:
                text_content = text_content.format(**variables)
            except KeyError as e:
                logger.warning(f"Missing variable {e} in text {text_key}")
                # Try to continue with available variables
                try:
                    # Only use variables that exist in the text
                    available_vars = {k: v for k, v in variables.items() 
                                     if f'{{{k}}}' in text_content}
                    text_content = text_content.format(**available_vars)
                except Exception as e2:
                    logger.error(f"Error formatting text {text_key}: {e2}")
            except Exception as e:
                logger.error(f"Error formatting text {text_key}: {e}")
        
        return text_content
    
    def _get_text_content(self, text_key: str, use_default: bool = True) -> Optional[str]:
        """Get text content from database or default - ALWAYS reads fresh from database"""
        # Always get fresh from database (cache disabled for real-time updates)
        text_content = None
        
        # Try to get from database - always fresh, no cache, force database read
        if self.db:
            try:
                # Force fresh query by getting directly from database
                # Use a fresh connection to ensure we get the latest data
                db_text = self.db.get_bot_text(text_key)
                if db_text:
                    if db_text.get('text_content'):
                        text_content = db_text['text_content']
                        logger.info(f"✅ Loaded text '{text_key}' from database (length: {len(text_content)}, active: {db_text.get('is_active', 1)})")
                    else:
                        logger.warning(f"⚠️ Text '{text_key}' found in database but text_content is empty")
                else:
                    logger.debug(f"ℹ️ Text '{text_key}' not found in database, will use default if available")
            except Exception as e:
                logger.error(f"❌ Error getting text '{text_key}' from database: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Fallback to default if not found in database
        if not text_content and use_default:
            text_def = self.TEXT_DEFINITIONS.get(text_key)
            if text_def:
                text_content = text_def['default']
                logger.debug(f"📝 Using default text for '{text_key}' (not customized in database)")
            else:
                logger.warning(f"⚠️ No default text definition found for '{text_key}'")
        
        return text_content
    
    def get_text_definition(self, text_key: str) -> Optional[Dict]:
        """Get text definition including available variables"""
        return self.TEXT_DEFINITIONS.get(text_key)
    
    def get_all_text_definitions(self, category: str = None) -> Dict[str, Dict]:
        """Get all text definitions, optionally filtered by category"""
        if category:
            return {k: v for k, v in self.TEXT_DEFINITIONS.items() 
                   if v.get('category') == category}
        return self.TEXT_DEFINITIONS.copy()
    
    def initialize_default_texts(self, db: ProfessionalDatabaseManager = None) -> int:
        """
        Initialize database with default texts if they don't exist
        Returns number of texts initialized
        """
        if not db:
            db = self.db
        
        if not db:
            logger.error("No database connection provided")
            return 0
        
        initialized_count = 0
        
        for text_key, text_def in self.TEXT_DEFINITIONS.items():
            # Check if text already exists
            existing = db.get_bot_text(text_key)
            if existing:
                continue
            
            # Create text in database
            available_vars = ','.join(text_def.get('variables', []))
            text_id = db.create_bot_text(
                text_key=text_key,
                text_category=text_def['category'],
                text_content=text_def['default'],
                description=text_def.get('description'),
                available_variables=available_vars if available_vars else None
            )
            
            if text_id:
                initialized_count += 1
                logger.info(f"Initialized default text: {text_key}")
        
        # Clear cache after initialization
        self._text_cache.clear()
        
        return initialized_count
    
    def clear_cache(self):
        """Clear text cache"""
        self._text_cache.clear()
    
    def format_text_with_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """
        Format text with variables (standalone function)
        Handles missing variables gracefully
        """
        try:
            return text.format(**variables)
        except KeyError as e:
            # Try with only available variables
            available_vars = {k: v for k, v in variables.items() 
                            if f'{{{k}}}' in text}
            try:
                return text.format(**available_vars)
            except Exception:
                logger.error(f"Error formatting text with variables: {e}")
                return text
        except Exception as e:
            logger.error(f"Error formatting text: {e}")
            return text

