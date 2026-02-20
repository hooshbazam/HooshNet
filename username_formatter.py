"""
Professional Username Formatter
Creates elegant, short, and professional usernames for the VPN bot
"""

import re
import time
import random
import string
from typing import Optional, Dict

class UsernameFormatter:
    """Professional username formatting system"""
    
    # Persian name patterns for better formatting
    PERSIAN_NAMES = {
        'amir': 'امیر',
        'ali': 'علی',
        'ahmad': 'احمد',
        'mohammad': 'محمد',
        'reza': 'رضا',
        'hassan': 'حسن',
        'hossein': 'حسین',
        'mahmoud': 'محمود',
        'saeed': 'سعید',
        'farhad': 'فرهاد',
        'kaveh': 'کاوه',
        'arshia': 'آرشیا',
        'danial': 'دانیال',
        'soroush': 'سروش',
        'pouya': 'پویا',
        'arya': 'آریا',
        'roozbeh': 'روزبه',
        'shayan': 'شایان',
        'taha': 'طاها',
        'yasin': 'یاسین'
    }
    
    # Professional suffixes
    SUFFIXES = {
        'pro': 'Pro',
        'vip': 'VIP',
        'premium': 'Premium',
        'elite': 'Elite',
        'gold': 'Gold',
        'silver': 'Silver',
        'bronze': 'Bronze',
        'plus': 'Plus',
        'max': 'Max',
        'ultra': 'Ultra'
    }
    
    @staticmethod
    def format_client_name(telegram_id: int, username: Optional[str] = None, 
                          first_name: Optional[str] = None, 
                          service_type: str = "VPN") -> str:
        """
        Create a professional random client name
        
        Args:
            telegram_id: User's Telegram ID
            username: User's Telegram username
            first_name: User's first name
            service_type: Type of service (VPN, Proxy, etc.)
        
        Returns:
            Formatted random client name
        """
        # Generate random prefix (4 letters)
        prefix = ''.join(random.choices(string.ascii_uppercase, k=4))
        
        # Generate random number (4 digits)
        number = ''.join(random.choices(string.digits, k=4))
        
        # Format: ABCD1234 (8 characters: 4 letters + 4 digits)
        client_name = f"{prefix}{number}"
        
        return client_name
    
    @staticmethod
    def format_display_name(username: Optional[str] = None, 
                           first_name: Optional[str] = None,
                           last_name: Optional[str] = None) -> str:
        """
        Format display name for UI
        
        Args:
            username: Telegram username
            first_name: First name
            last_name: Last name
        
        Returns:
            Formatted display name
        """
        # Priority: first_name + last_name > username > "کاربر"
        if first_name:
            display_name = first_name
            if last_name:
                display_name += f" {last_name}"
            return display_name[:20]  # Max 20 chars
        
        if username:
            # Clean username
            clean_username = re.sub(r'[^a-zA-Z0-9_\.]', '', username)
            return clean_username[:15]  # Max 15 chars
        
        return "کاربر"
    
    @staticmethod
    def format_service_name(service_id: int, user_name: str, 
                          data_amount: int, panel_name: str = "") -> str:
        """
        Format service name for display
        
        Args:
            service_id: Service ID
            user_name: User's display name
            data_amount: Data amount in GB
            panel_name: Panel name
        
        Returns:
            Formatted service name
        """
        # Clean user name
        clean_name = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', user_name)[:8]
        
        # Format: Name_DataGB_Panel
        service_name = f"{clean_name}_{data_amount}GB"
        
        if panel_name:
            panel_short = panel_name[:5]
            service_name += f"_{panel_short}"
        
        # Add service ID for uniqueness
        service_name += f"_{service_id}"
        
        return service_name[:30]  # Max 30 chars
    
    @staticmethod
    def format_panel_name(panel_name: str, location: str = "") -> str:
        """
        Format panel name professionally
        
        Args:
            panel_name: Original panel name
            location: Server location
        
        Returns:
            Formatted panel name
        """
        # Clean and format
        clean_name = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\s]', '', panel_name)
        clean_name = clean_name.strip()
        
        # Add location if provided
        if location:
            clean_name += f" ({location})"
        
        return clean_name[:25]  # Max 25 chars
    
    @staticmethod
    def format_balance(amount: int) -> str:
        """
        Format balance amount professionally
        
        Args:
            amount: Amount in Toman
        
        Returns:
            Formatted balance string
        """
        # Always show full number with thousand separator
        return f"{amount:,} تومان"
    
    @staticmethod
    def format_data_amount(gb: int) -> str:
        """
        Format data amount professionally
        
        Args:
            gb: Amount in GB
        
        Returns:
            Formatted data string
        """
        if gb >= 1000:
            return f"{gb // 1000}TB"
        elif gb >= 100:
            return f"{gb}GB"
        elif gb >= 1:
            return f"{gb}GB"
        else:
            return f"{gb * 1024}MB"
    
    @staticmethod
    def format_time_remaining(seconds: int) -> str:
        """
        Format time remaining professionally
        
        Args:
            seconds: Seconds remaining
        
        Returns:
            Formatted time string
        """
        if seconds <= 0:
            return "منقضی شده"
        
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        
        if days > 0:
            return f"{days} روز و {hours} ساعت"
        elif hours > 0:
            return f"{hours} ساعت و {minutes} دقیقه"
        else:
            return f"{minutes} دقیقه"
    
    @staticmethod
    def _extract_base_name(username: Optional[str], first_name: Optional[str]) -> str:
        """Extract base name from username or first name"""
        # Try first name first
        if first_name:
            # Clean and shorten first name
            clean_name = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', first_name)
            if len(clean_name) >= 3:
                return clean_name[:6].lower()
        
        # Try username
        if username:
            # Remove @ and clean
            clean_username = username.replace('@', '').lower()
            clean_username = re.sub(r'[^a-zA-Z0-9]', '', clean_username)
            if len(clean_username) >= 3:
                return clean_username[:6]
        
        # Fallback to generic
        return "user"
    
    @staticmethod
    def create_professional_email(telegram_id: int, panel_name: str) -> str:
        """
        Create professional random email for panel
        
        Args:
            telegram_id: User's Telegram ID
            panel_name: Panel name
        
        Returns:
            Professional random email address
        """
        # Generate random email prefix (6 alphanumeric chars)
        prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        
        # Clean panel name
        clean_panel = re.sub(r'[^a-zA-Z0-9]', '', panel_name).lower()[:8]
        
        # Create email: random@panelname
        email = f"{prefix}@{clean_panel}" if clean_panel else prefix
        
        return email[:40]  # Max 40 chars
    
    @staticmethod
    def format_status(status: str) -> str:
        """
        Format status with emoji
        
        Args:
            status: Status string
        
        Returns:
            Formatted status with emoji
        """
        if status is None:
            status = ''
        status_str = str(status).strip()
        if not status_str:
            status_str = 'active'

        status_map = {
            'active': '🟢 فعال',
            'inactive': '🔴 غیرفعال',
            'disabled': '🔴 غیرفعال',
            'expired': '⏰ منقضی شده',
            'exhausted': '🟠 حجم تمام شده',
            'suspended': '⏸️ معلق',
            'pending': '🟡 در انتظار',
            'connected': '🔗 متصل',
            'disconnected': '🔌 قطع',
            'online': '🟢 آنلاین',
            'offline': '🔴 آفلاین'
        }
        
        return status_map.get(status_str.lower(), f"⚪ {status_str}")
    
    @staticmethod
    def format_connection_status(is_online: bool, last_seen: int = 0) -> str:
        """
        Format connection status
        
        Args:
            is_online: Whether user is currently online
            last_seen: Last seen timestamp
        
        Returns:
            Formatted connection status
        """
        if is_online:
            return "🔗 متصل"
        
        if last_seen > 0:
            try:
                last_seen_int = int(float(last_seen))
            except Exception:
                last_seen_int = 0
            if last_seen_int > 1000000000000:
                last_seen_int = last_seen_int // 1000

            current_time = int(time.time())
            time_diff = current_time - last_seen_int
            
            if time_diff < 300:  # 5 minutes
                return "🟡 اخیراً متصل"
            elif time_diff < 3600:  # 1 hour
                return "🟡 کمتر از یک ساعت پیش"
            elif time_diff < 86400:  # 1 day
                return "🟡 کمتر از یک روز پیش"
            else:
                return "🔌 غیرمتصل"
        
        return "🔌 غیرمتصل"


# ==================== Username Generation Methods ====================

from enum import Enum


class NamingMethod(Enum):
    """8 different username generation methods (from mirza_pro)"""
    USERNAME_SEQUENTIAL = 1    # نام کاربری + عدد ترتیبی
    ID_RANDOM = 2              # آیدی عددی + رندوم
    USER_CUSTOM = 3            # نام دلخواه کاربر
    USER_CUSTOM_RANDOM = 4     # نام دلخواه + رندوم
    ADMIN_TEXT_RANDOM = 5      # متن ادمین + رندوم
    ADMIN_TEXT_SEQUENTIAL = 6  # متن ادمین + ترتیبی
    ID_SEQUENTIAL = 7          # آیدی + ترتیبی
    RESELLER_SEQUENTIAL = 8    # متن نماینده + ترتیبی


NAMING_METHOD_NAMES = {
    NamingMethod.USERNAME_SEQUENTIAL: '📝 نام کاربری + شماره ترتیبی',
    NamingMethod.ID_RANDOM: '🔢 آیدی عددی + رندوم',
    NamingMethod.USER_CUSTOM: '✏️ نام دلخواه کاربر',
    NamingMethod.USER_CUSTOM_RANDOM: '🎲 نام دلخواه + رندوم',
    NamingMethod.ADMIN_TEXT_RANDOM: '👤 متن ادمین + رندوم',
    NamingMethod.ADMIN_TEXT_SEQUENTIAL: '📊 متن ادمین + ترتیبی',
    NamingMethod.ID_SEQUENTIAL: '🔗 آیدی + ترتیبی',
    NamingMethod.RESELLER_SEQUENTIAL: '💼 متن نماینده + ترتیبی',
}


class UsernameGenerator:
    """
    Advanced username generation system with 8 different methods
    Based on mirza_pro implementation
    """
    
    def __init__(self, db=None):
        self.db = db
        self._sequence_counter = {}
    
    def set_database(self, db):
        """Set database instance"""
        self.db = db
    
    def generate(self, method: NamingMethod, telegram_id: int, username: str = None,
                 first_name: str = None, custom_name: str = None,
                 admin_prefix: str = None, reseller_prefix: str = None,
                 panel_id: int = None) -> str:
        """
        Generate username based on selected method
        
        Args:
            method: NamingMethod enum
            telegram_id: User's Telegram ID
            username: Telegram username
            first_name: User's first name
            custom_name: Custom name provided by user (for USER_CUSTOM methods)
            admin_prefix: Admin-defined prefix text
            reseller_prefix: Reseller-defined prefix text
            panel_id: Panel ID for sequence tracking
            
        Returns:
            Generated username string
        """
        if method == NamingMethod.USERNAME_SEQUENTIAL:
            return self._username_sequential(username, first_name, telegram_id, panel_id)
        
        elif method == NamingMethod.ID_RANDOM:
            return self._id_random(telegram_id)
        
        elif method == NamingMethod.USER_CUSTOM:
            return self._user_custom(custom_name, telegram_id)
        
        elif method == NamingMethod.USER_CUSTOM_RANDOM:
            return self._user_custom_random(custom_name, telegram_id)
        
        elif method == NamingMethod.ADMIN_TEXT_RANDOM:
            return self._admin_text_random(admin_prefix, telegram_id)
        
        elif method == NamingMethod.ADMIN_TEXT_SEQUENTIAL:
            return self._admin_text_sequential(admin_prefix, panel_id)
        
        elif method == NamingMethod.ID_SEQUENTIAL:
            return self._id_sequential(telegram_id, panel_id)
        
        elif method == NamingMethod.RESELLER_SEQUENTIAL:
            return self._reseller_sequential(reseller_prefix, panel_id)
        
        else:
            # Fallback to random
            return self._id_random(telegram_id)
    
    def _username_sequential(self, username: str, first_name: str, 
                             telegram_id: int, panel_id: int = None) -> str:
        """Method 1: Username + Sequential number"""
        base = self._clean_name(username or first_name or 'user')[:8]
        seq = self._get_next_sequence(f"user_{panel_id or 0}")
        return f"{base}{seq}"
    
    def _id_random(self, telegram_id: int) -> str:
        """Method 2: ID + Random string"""
        id_short = str(telegram_id)[-4:]
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"{id_short}{random_part}"
    
    def _user_custom(self, custom_name: str, telegram_id: int) -> str:
        """Method 3: User custom name (cleaned)"""
        if not custom_name:
            return self._id_random(telegram_id)
        
        clean = self._clean_name(custom_name)[:12]
        # Add short id if name is too short
        if len(clean) < 4:
            clean += str(telegram_id)[-4:]
        return clean
    
    def _user_custom_random(self, custom_name: str, telegram_id: int) -> str:
        """Method 4: User custom name + Random"""
        if not custom_name:
            return self._id_random(telegram_id)
        
        clean = self._clean_name(custom_name)[:6]
        random_part = ''.join(random.choices(string.digits, k=4))
        return f"{clean}{random_part}"
    
    def _admin_text_random(self, admin_prefix: str, telegram_id: int) -> str:
        """Method 5: Admin text + Random"""
        prefix = self._clean_name(admin_prefix or 'VIP')[:4]
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"{prefix}{random_part}"
    
    def _admin_text_sequential(self, admin_prefix: str, panel_id: int = None) -> str:
        """Method 6: Admin text + Sequential"""
        prefix = self._clean_name(admin_prefix or 'VIP')[:4]
        seq = self._get_next_sequence(f"admin_{panel_id or 0}")
        return f"{prefix}{seq:04d}"
    
    def _id_sequential(self, telegram_id: int, panel_id: int = None) -> str:
        """Method 7: Telegram ID + Sequential"""
        id_short = str(telegram_id)[-4:]
        seq = self._get_next_sequence(f"id_{panel_id or 0}")
        return f"{id_short}{seq:04d}"
    
    def _reseller_sequential(self, reseller_prefix: str, panel_id: int = None) -> str:
        """Method 8: Reseller prefix + Sequential"""
        prefix = self._clean_name(reseller_prefix or 'RS')[:3]
        seq = self._get_next_sequence(f"reseller_{panel_id or 0}")
        return f"{prefix}{seq:05d}"
    
    def _clean_name(self, name: str) -> str:
        """Clean name for username (only alphanumeric)"""
        if not name:
            return ""
        # Remove all non-alphanumeric characters (allow underscore)
        clean = re.sub(r'[^a-zA-Z0-9_]', '', name)
        return clean.upper() if clean else ""
    
    def _get_next_sequence(self, key: str) -> int:
        """Get next sequence number for a key"""
        if not self.db:
            # In-memory fallback
            if key not in self._sequence_counter:
                self._sequence_counter[key] = 0
            self._sequence_counter[key] += 1
            return self._sequence_counter[key]
        
        try:
            # Use database settings for persistence
            setting_key = f"username_seq_{key}"
            current = self.db.get_setting(setting_key, 0)
            next_val = int(current) + 1
            self.db.set_setting(setting_key, str(next_val))
            return next_val
        except Exception:
            # Fallback to in-memory
            if key not in self._sequence_counter:
                self._sequence_counter[key] = 0
            self._sequence_counter[key] += 1
            return self._sequence_counter[key]
    
    @staticmethod
    def get_method_name(method: NamingMethod) -> str:
        """Get Persian name for a naming method"""
        return NAMING_METHOD_NAMES.get(method, 'نامشخص')
    
    @staticmethod
    def get_all_methods() -> list:
        """Get list of all naming methods"""
        return list(NamingMethod)
    
    @staticmethod
    def method_from_value(value: int) -> NamingMethod:
        """Convert integer to NamingMethod"""
        try:
            return NamingMethod(value)
        except ValueError:
            return NamingMethod.ID_RANDOM


# Global instance
username_generator = UsernameGenerator()

