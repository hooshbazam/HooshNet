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
        status_map = {
            'active': '🟢 فعال',
            'inactive': '🔴 غیرفعال',
            'expired': '⏰ منقضی شده',
            'suspended': '⏸️ معلق',
            'pending': '🟡 در انتظار',
            'connected': '🔗 متصل',
            'disconnected': '🔌 قطع',
            'online': '🟢 آنلاین',
            'offline': '🔴 آفلاین'
        }
        
        return status_map.get(status.lower(), f"⚪ {status}")
    
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
            return "🟢 آنلاین"
        
        if last_seen > 0:
            current_time = int(time.time())
            time_diff = current_time - last_seen
            
            if time_diff < 300:  # 5 minutes
                return "🟡 اخیراً آنلاین"
            elif time_diff < 3600:  # 1 hour
                return "🟡 کمتر از یک ساعت پیش"
            elif time_diff < 86400:  # 1 day
                return "🟡 کمتر از یک روز پیش"
            else:
                return "🔴 آفلاین"
        
        return "🔴 آفلاین"
