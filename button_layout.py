from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from typing import List, Dict, Optional, Tuple
from webapp_helper import get_webapp_url
"""
Professional Button Layout System for VPN Bot
Provides consistent, beautiful, and professional button arrangements
"""


class ProfessionalButtonLayout:
    """Professional button layout system with consistent design principles"""
    
    # Professional emoji system
    EMOJIS = {
        # Core Actions
        'buy': '🛒',
        'dashboard': '📊',
        'admin': '⚙️',
        'help': '❓',
        'home': '🏠',
        'back': '◀️',
        'close': '❌',
        'confirm': '✅',
        'cancel': '🚫',
        
        # Navigation
        'next': '▶️',
        'previous': '◀️',
        'refresh': '🔄',
        'search': '🔍',
        'filter': '🔽',
        'sort': '📊',
        
        # User Interface
        'user': '👤',
        'users': '👥',
        'settings': '⚙️',
        'info': 'ℹ️',
        'warning': '⚠️',
        'error': '❌',
        'success': '✅',
        'loading': '⏳',
        
        # Financial
        'balance': '💰',
        'payment': '💳',
        'wallet': '💼',
        'money': '💵',
        'coin': '🪙',
        
        # Services & Products
        'service': '🔧',
        'services': '🔧',
        'vpn': '🔒',
        'server': '🖥️',
        'network': '🌐',
        'connection': '🔗',
        'speed': '⚡',
        'security': '🛡️',
        
        # Data & Storage
        'data': '📊',
        'storage': '💾',
        'download': '📥',
        'upload': '📤',
        'traffic': '📈',
        'bandwidth': '📊',
        'gb': '💾',
        'mb': '💿',
        
        # Status & States
        'active': '🟢',
        'inactive': '🔴',
        'pending': '🟡',
        'online': '🟢',
        'offline': '🔴',
        'connected': '🔗',
        'disconnected': '🔌',
        'enabled': '✅',
        'disabled': '❌',
        
        # Actions
        'add': '➕',
        'edit': '✏️',
        'delete': '🗑️',
        'copy': '📋',
        'share': '📤',
        'download': '📥',
        'upload': '📤',
        'save': '💾',
        'load': '📂',
        'send': '📤',
        'receive': '📥',
        
        # Time & Date
        'time': '🕐',
        'date': '📅',
        'calendar': '📅',
        'clock': '⏰',
        'timer': '⏲️',
        'expire': '⏰',
        'renew': '🔄',
        
        # Communication
        'message': '💬',
        'chat': '💬',
        'call': '📞',
        'email': '📧',
        'notification': '🔔',
        'alert': '🚨',
        
        # Technical
        'config': '⚙️',
        'settings': '⚙️',
        'tools': '🛠️',
        'gear': '⚙️',
        'wrench': '🔧',
        'screwdriver': '🪛',
        'hammer': '🔨',
        'key': '🔑',
        'lock': '🔒',
        'unlock': '🔓',
        
        # Quality & Rating
        'star': '⭐',
        'stars': '⭐⭐⭐',
        'excellent': '⭐',
        'good': '👍',
        'bad': '👎',
        'like': '👍',
        'dislike': '👎',
        'heart': '❤️',
        'fire': '🔥',
        'rocket': '🚀',
        
        # Geographic
        'location': '📍',
        'map': '🗺️',
        'globe': '🌍',
        'world': '🌍',
        'country': '🏳️',
        'city': '🏙️',
        'home': '🏠',
        'building': '🏢',
        
        # Special
        'new': '🆕',
        'hot': '🔥',
        'sale': '🏷️',
        'discount': '💰',
        'gift': '🎁',
        'trophy': '🏆',
        'medal': '🏅',
        'crown': '👑',
        'diamond': '💎',
        'gem': '💎',
        'crystal': '💎',
        'pearl': '🪸',
        'gold': '🥇',
        'silver': '🥈',
        'bronze': '🥉'
    }
    
    # Professional text templates with consistent styling
    TEXT_TEMPLATES = {
        # Main Navigation
        'buy_service': '🛒 خرید سرویس جدید',
        'user_dashboard': '📊 پنل کاربری',
        'admin_panel': '⚙️ پنل مدیریت',
        'help_center': '❓ مرکز راهنما',
        'main_menu': '🏠 صفحه اصلی',
        
        # User Actions
        'my_services': '🌟 سرویس‌های من',
        'my_balance': '💰 موجودی من',
        'my_profile': '👤 پروفایل من',
        'my_settings': '⚙️ تنظیمات من',
        
        # Service Management
        'new_service': '➕ خرید سرویس',
        'renew_service': '🔄 افزایش حجم',
        'upgrade_service': '⬆️ ارتقا به پلن بالاتر',
        'manage_service': '📱 مدیریت سرویس',
        'service_details': '📋 جزئیات و مشخصات',
        'service_config': '🔐 دریافت کانفیگ',
        'service_stats': '📊 آمار مصرف',
        
        # Payment & Balance
        'add_balance': '💰 افزایش موجودی',
        'payment_history': '📋 تاریخچه پرداخت',
        'payment_methods': '💳 روش‌های پرداخت',
        'balance_transfer': '💸 انتقال موجودی',
        
        # Admin Functions
        'manage_users': '👥 مدیریت کاربران',
        'manage_panels': '🖥️ مدیریت پنل‌ها',
        'system_stats': '📊 آمار سیستم',
        'system_logs': '📋 لاگ‌های سیستم',
        'system_settings': '⚙️ تنظیمات سیستم',
        
        # Common Actions
        'back': '◀️ بازگشت',
        'close': '❌ بستن',
        'cancel': '🚫 لغو',
        'confirm': '✅ تأیید',
        'save': '💾 ذخیره',
        'edit': '✏️ ویرایش',
        'delete': '🗑️ حذف',
        'refresh': '🔄 بروزرسانی',
        'search': '🔍 جستجو',
        'filter': '🔽 فیلتر',
        'sort': '📊 مرتب‌سازی',
        'export': '📤 خروجی',
        'import': '📥 ورودی',
        
        # Status Messages
        'active': '🟢 فعال',
        'inactive': '🔴 غیرفعال',
        'pending': '🟡 در انتظار',
        'expired': '⏰ منقضی شده',
        'suspended': '⏸️ معلق',
        'connected': '🔗 متصل',
        'disconnected': '🔌 قطع',
        
        # Data & Storage
        'unlimited': '♾️ نامحدود',
        'gb': 'گیگابایت',
        'mb': 'مگابایت',
        'tb': 'ترابایت',
        'traffic': 'ترافیک',
        'bandwidth': 'پهنای باند',
        'data_usage': 'مصرف داده',
        'remaining': 'باقی‌مانده',
        'used': 'مصرف شده',
        'total': 'کل',
        
        # Time & Duration
        'days': 'روز',
        'hours': 'ساعت',
        'minutes': 'دقیقه',
        'seconds': 'ثانیه',
        'expires_in': 'منقضی می‌شود در',
        'created_at': 'ایجاد شده در',
        'updated_at': 'به‌روزرسانی شده در',
        'last_activity': 'آخرین فعالیت',
        
        # Quality & Rating
        'excellent': '⭐ عالی',
        'good': '👍 خوب',
        'average': '😐 متوسط',
        'poor': '👎 ضعیف',
        'rating': 'امتیاز',
        'review': 'نظر',
        'feedback': 'بازخورد',
        
        # Special Offers
        'new': '🆕 جدید',
        'hot': '🔥 داغ',
        'sale': '🏷️ تخفیف',
        'discount': '💰 تخفیف',
        'offer': '🎁 پیشنهاد',
        'promotion': '📢 تبلیغ',
        'special': '⭐ ویژه',
        'premium': '💎 پریمیوم',
        'vip': '👑 VIP',
        'pro': '🚀 حرفه‌ای'
    }
    
    # Professional color coding system
    COLORS = {
        'primary': '🔵',      # Main actions
        'secondary': '⚪',     # Secondary actions
        'success': '🟢',       # Success states
        'warning': '🟡',       # Warning states
        'error': '🔴',         # Error states
        'info': '🔵',          # Information
        'neutral': '⚪',       # Neutral states
        'accent': '🟣',        # Accent actions
        'highlight': '🟠'      # Highlighted items
    }
    
    @staticmethod
    def create_main_menu(is_admin: bool = False, user_balance: int = 0, user_id: int = None, webapp_url: str = None, bot_name: str = None, db=None) -> ReplyKeyboardMarkup:
        """Create professional main menu with user context (Reply Keyboard)
        
        Args:
            is_admin: Whether user is admin
            user_balance: User balance
            user_id: User telegram ID
            webapp_url: Base webapp URL
            bot_name: Bot name for route prefix
            db: Database instance (optional, will create default if not provided)
        """
        keyboard = []
        
        # Try to load from database first
        try:
            if db is None:
                from professional_database import ProfessionalDatabaseManager
                db = ProfessionalDatabaseManager()
            menu_buttons = db.get_menu_buttons(is_admin=is_admin)
            
            if menu_buttons and len(menu_buttons) > 0:
                # Group buttons by row
                rows = {}
                for button in menu_buttons:
                    row_pos = button.get('row_position', 0)
                    if row_pos not in rows:
                        rows[row_pos] = []
                    rows[row_pos].append(button)
                
                # Sort rows and build keyboard
                for row_pos in sorted(rows.keys()):
                    row_buttons = []
                    # Sort buttons in row by column position
                    sorted_buttons = sorted(rows[row_pos], key=lambda b: b.get('column_position', 0))
                    
                    for button in sorted_buttons:
                        button_type = button.get('button_type', 'callback')
                        
                        # Skip webapp buttons in main menu (they are handled separately)
                        if button_type == 'webapp':
                            continue
                            
                        # For Reply Keyboard, we only use text
                        row_buttons.append(
                            KeyboardButton(
                                button.get('button_text', '')
                            )
                        )
                    
                    if row_buttons:
                        keyboard.append(row_buttons)
                
                if keyboard:
                    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        except Exception as e:
            # Fallback to default if database fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to load menu from database: {e}, using default layout")
        
        # Fallback to default layout
        # Primary actions row (2 columns for visual balance)
        keyboard.append([
            KeyboardButton("🛒 خرید سرویس"),
            KeyboardButton("📊 پنل کاربری")
        ])
        
        # Test account and quick actions row (2 columns)
        keyboard.append([
            KeyboardButton("🧪 اکانت تست"),
            KeyboardButton("💰 موجودی")
        ])
        
        # Quick actions row (2 columns)
        keyboard.append([
            KeyboardButton("🎁 دعوت دوستان"),
            KeyboardButton("❓ راهنما و پشتیبانی")
        ])
        
        # Admin panel (only for admins)
        if is_admin:
            keyboard.append([
                KeyboardButton("⚙️ پنل مدیریت")
            ])
        
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    @staticmethod
    def create_webapp_keyboard(webapp_url: str = None, bot_name: str = None) -> InlineKeyboardMarkup:
        """Create inline keyboard with ONLY the Web App button"""
        keyboard = []
        
        # Web App for all users
        if not webapp_url:
            import os
            webapp_url = os.getenv('BOT_WEBAPP_URL') or get_webapp_url()
        
        # Add bot_name prefix if provided
        if webapp_url and bot_name:
            base_url = webapp_url.rstrip('/')
            webapp_url = f"{base_url}/{bot_name}"
        
        if webapp_url:
            keyboard.append([
                InlineKeyboardButton("🌐 ورود به وب اپلیکیشن", web_app=WebAppInfo(url=webapp_url))
            ])
            
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_user_dashboard(services: List[Dict] = None, user_balance: int = 0) -> InlineKeyboardMarkup:
        """Create professional user dashboard"""
        keyboard = []
        
        # Services section
        if services and len(services) > 0:
            keyboard.append([InlineKeyboardButton(
                f"🌟 سرویس‌های من ({len(services)} سرویس)",
                callback_data="my_services"
            )])
            
            # Show first 3 services as quick access
            for i, service in enumerate(services[:3]):
                service_name = ProfessionalButtonLayout._format_service_name(service)
                keyboard.append([InlineKeyboardButton(
                    service_name,
                    callback_data=f"manage_service_{service['id']}"
                )])
            
            if len(services) > 3:
                keyboard.append([InlineKeyboardButton(
                    f"📋 مشاهده همه سرویس‌ها",
                    callback_data="all_services"
                )])
        else:
            keyboard.append([InlineKeyboardButton(
                "➕ خرید اولین سرویس خود",
                callback_data="buy_service"
            )])
        
        # Quick actions (2 columns)
        keyboard.append([
            InlineKeyboardButton(f"💰 موجودی: {user_balance:,} تومان", callback_data="account_balance"),
        ])
        keyboard.append([
            InlineKeyboardButton("🛒 خرید سرویس جدید", callback_data="buy_service")
        ])
        
        # Navigation
        keyboard.append([InlineKeyboardButton(
            "◀️ بازگشت به منو اصلی",
            callback_data="main_menu"
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_service_management(service: Dict, is_admin: bool = False, admin_user_id: int = None) -> InlineKeyboardMarkup:
        """Create service management buttons"""
        keyboard = []
        
        # Primary actions - Config and QR Code (2 columns)
        keyboard.append([
            InlineKeyboardButton("📋 دریافت کانفیگ", callback_data=f"get_config_{service['id']}"),
            InlineKeyboardButton("📱 دریافت QR Code", callback_data=f"get_qr_code_{service['id']}")
        ])
        
        # Link management and renewal (2 columns)
        # Link management and renewal (2 columns)
        renewal_text = "🔄 تمدید سرویس" if service.get('product_id') else "➕ افزایش حجم"
        renewal_callback = f"renew_service_{service['id']}" if service.get('product_id') else f"add_volume_{service['id']}"
        
        keyboard.append([
            InlineKeyboardButton(renewal_text, callback_data=renewal_callback),
            InlineKeyboardButton("🔗 دریافت لینک جدید", callback_data=f"reset_service_link_{service['id']}")
        ])
        
        # Location/Panel change button (full width)
        keyboard.append([
            InlineKeyboardButton("🌍 تغییر لوکیشن/پنل", callback_data=f"change_panel_{service['id']}")
        ])
        
        # Delete service (full width)
        keyboard.append([
            InlineKeyboardButton("🗑️ حذف سرویس", callback_data=f"delete_service_{service['id']}")
        ])
        
        # Navigation - different for admin and user
        if is_admin and admin_user_id:
            keyboard.append([
                InlineKeyboardButton("◀️ بازگشت به سرویس‌ها", callback_data=f"user_services_{admin_user_id}_1")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("◀️ بازگشت", callback_data="user_panel")
            ])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_payment_methods(invoice_id: int, user_balance: int, total_amount: int) -> InlineKeyboardMarkup:
        """Create professional payment method selection"""
        keyboard = []
        
        # Balance payment (if sufficient)
        if user_balance >= total_amount:
            keyboard.append([InlineKeyboardButton(
                f"💰 پرداخت از موجودی (موجودی: {user_balance:,} تومان)", 
                callback_data=f"pay_balance_{invoice_id}"
            )])
        else:
            shortage = total_amount - user_balance
            keyboard.append([InlineKeyboardButton(
                f"💰 موجودی کافی نیست (کمبود: {shortage:,} تومان)", 
                callback_data="add_balance"
            )])
        
        # Gateway payment (if amount >= minimum)
        if total_amount >= 10000:
            keyboard.append([InlineKeyboardButton(
                "💳 پرداخت آنلاین (درگاه امن)",
                callback_data=f"pay_gateway_{invoice_id}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                "💳 پرداخت آنلاین (حداقل مبلغ: 10,000 تومان)", 
                callback_data="payment_minimum_error"
            )])
        
        # Card to Card payment
        keyboard.append([InlineKeyboardButton(
            "💳 کارت به کارت",
            callback_data=f"pay_card_{invoice_id}"
        )])
        
        # Navigation
        keyboard.append([InlineKeyboardButton(
            "◀️ بازگشت",
            callback_data="buy_service"
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_data_plans(panel_id: int) -> InlineKeyboardMarkup:
        """Create professional data plan selection"""
        # Professional data plans with pricing
        plans = [
            {"gb": 1, "price": 5000, "popular": False},
            {"gb": 5, "price": 20000, "popular": False},
            {"gb": 10, "price": 35000, "popular": True},
            {"gb": 25, "price": 80000, "popular": False},
            {"gb": 50, "price": 150000, "popular": False},
            {"gb": 100, "price": 280000, "popular": True},
            {"gb": 250, "price": 650000, "popular": False},
            {"gb": 500, "price": 1200000, "popular": False},
            {"gb": 1000, "price": 2200000, "popular": False}
        ]
        
        keyboard = []
        
        # Create rows of 3 buttons each
        for i in range(0, len(plans), 3):
            row = []
            for j in range(3):
                if i + j < len(plans):
                    plan = plans[i + j]
                    popular_badge = " 🔥" if plan['popular'] else ""
                    button_text = f"{plan['gb']} GB{popular_badge}\n{plan['price']:,} تومان"
                    row.append(InlineKeyboardButton(
                        button_text,
                        callback_data=f"select_gb_{panel_id}_{plan['gb']}"
                    ))
            keyboard.append(row)
        
        # Custom volume option
        keyboard.append([InlineKeyboardButton("✏️ حجم دلخواه", callback_data=f"custom_renew_volume_{panel_id}")])
        
        # Navigation
        keyboard.append([InlineKeyboardButton(
            "◀️ بازگشت",
            callback_data="buy_service"
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_add_volume_plans(panel_id: int, service_id: int) -> InlineKeyboardMarkup:
        """Create professional data plan selection for adding volume to existing service"""
        # Professional data plans with pricing
        plans = [
            {"gb": 1, "price": 5000, "popular": False},
            {"gb": 5, "price": 20000, "popular": False},
            {"gb": 10, "price": 35000, "popular": True},
            {"gb": 25, "price": 80000, "popular": False},
            {"gb": 50, "price": 150000, "popular": False},
            {"gb": 100, "price": 280000, "popular": True},
            {"gb": 250, "price": 650000, "popular": False},
            {"gb": 500, "price": 1200000, "popular": False},
            {"gb": 1000, "price": 2200000, "popular": False}
        ]
        
        keyboard = []
        
        # Create rows of 3 buttons each
        for i in range(0, len(plans), 3):
            row = []
            for j in range(3):
                if i + j < len(plans):
                    plan = plans[i + j]
                    popular_badge = " 🔥" if plan['popular'] else ""
                    button_text = f"{plan['gb']} GB{popular_badge}\n{plan['price']:,} تومان"
                    row.append(InlineKeyboardButton(
                        button_text,
                        callback_data=f"add_volume_select_{service_id}_{panel_id}_{plan['gb']}"
                    ))
            keyboard.append(row)
        
        # Custom volume option
        keyboard.append([InlineKeyboardButton("✏️ حجم دلخواه", callback_data=f"custom_add_volume_{service_id}_{panel_id}")])
        
        # Navigation
        keyboard.append([InlineKeyboardButton(
            "◀️ بازگشت",
            callback_data=f"manage_service_{service_id}"
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_admin_panel(webapp_url: str = None, bot_name: str = None) -> InlineKeyboardMarkup:
        """Create professional admin panel
        
        Args:
            webapp_url: Base URL for webapp (e.g., https://astonnetwork.xyz)
            bot_name: Bot name for route prefix (e.g., 'unlim' or 'AzadJooNet')
        """
        keyboard = []
        
        # Web App (if URL provided) - Full width for prominence
        # Using WebAppInfo for direct integration
        if not webapp_url:
            import os
            # Priority: 1. BOT_WEBAPP_URL (domain), 2. database (ngrok)
            webapp_url = os.getenv('BOT_WEBAPP_URL') or get_webapp_url()
        
        if webapp_url:
            # Add bot_name prefix to webapp URL if provided
            base_url = webapp_url.rstrip('/')
            if bot_name:
                user_webapp_url = f"{base_url}/{bot_name}"
            else:
                user_webapp_url = base_url
            
            keyboard.append([
                InlineKeyboardButton(
                    "🌐 ورود به وب اپلیکیشن",
                    web_app=WebAppInfo(url=user_webapp_url)
                )
            ])
            # Add web admin panel button with bot_name prefix
            if bot_name:
                admin_webapp_url = f"{base_url}/{bot_name}/admin"
            else:
                admin_webapp_url = f"{base_url}/admin"
            keyboard.append([
                InlineKeyboardButton(
                    "👑 ورود به پنل مدیریت وب",
                    web_app=WebAppInfo(url=admin_webapp_url)
                )
            ])
        
        # --- Core Management Section ---
        # Grouping core entities: Users, Panels, Products
        keyboard.append([
            InlineKeyboardButton("👥 مدیریت کاربران", callback_data="manage_users"),
            InlineKeyboardButton("🖥️ مدیریت پنل‌ها", callback_data="manage_panels")
        ])
        keyboard.append([
            InlineKeyboardButton("📦 مدیریت محصولات", callback_data="manage_products")
        ])

        # --- Financial & System Section ---
        # Grouping financial and system stats
        keyboard.append([
            InlineKeyboardButton("💰 مدیریت مالی", callback_data="financial_management"),
            InlineKeyboardButton("📊 آمار و گزارشات", callback_data="admin_stats")
        ])

        # --- Settings & Logs Section ---
        # Grouping configuration and logs
        keyboard.append([
            InlineKeyboardButton("⚙️ تنظیمات سیستم", callback_data="system_settings"),
            InlineKeyboardButton("🤖 تنظیمات اطلاعات ربات", callback_data="bot_info_settings")
        ])
        keyboard.append([
            InlineKeyboardButton("📋 لاگ‌های سیستم", callback_data="system_logs")
        ])
        
        # --- Navigation ---
        keyboard.append([InlineKeyboardButton(
            "🔙 بازگشت به منو اصلی",
            callback_data="main_menu"
        )])
        
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def create_financial_management_menu() -> InlineKeyboardMarkup:
        """Create financial management menu"""
        keyboard = [
            [InlineKeyboardButton("💳 ثبت شماره کارت", callback_data="card_settings")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_confirmation(action: str, item_name: str = "") -> InlineKeyboardMarkup:
        """Create professional confirmation dialog"""
        keyboard = [
            [InlineKeyboardButton(
                "✅ تأیید",
                callback_data=f"confirm_{action}"
            )],
            [InlineKeyboardButton(
                "🚫 لغو",
                callback_data=f"cancel_{action}"
            )]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_navigation(prev_callback: str = None, next_callback: str = None, 
                                back_callback: str = "main_menu") -> InlineKeyboardMarkup:
        """Create professional navigation buttons"""
        keyboard = []
        
        # Navigation row
        nav_buttons = []
        if prev_callback:
            nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=prev_callback))
        if next_callback:
            nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=next_callback))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # Back button
        keyboard.append([InlineKeyboardButton(
            "◀️ بازگشت",
            callback_data=back_callback
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_quick_actions(actions: List[Dict], back_callback: str = "main_menu") -> InlineKeyboardMarkup:
        """Create quick action buttons"""
        keyboard = []
        
        # Add action buttons
        for action in actions:
            keyboard.append([InlineKeyboardButton(
                action['text'], 
                callback_data=action['callback_data']
            )])
        
        # Back button
        keyboard.append([InlineKeyboardButton(
            "◀️ بازگشت",
            callback_data=back_callback
            )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_balance_management_buttons() -> InlineKeyboardMarkup:
        """Create balance management buttons"""
        keyboard = [
            [InlineKeyboardButton(
                "💰 افزایش موجودی",
                callback_data="add_balance"
            )],
            [InlineKeyboardButton(
                "📋 تاریخچه تراکنش‌ها",
                callback_data="payment_history"
            )],
            [InlineKeyboardButton(
                "◀️ بازگشت به پنل",
                callback_data="user_panel"
            )]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_balance_suggestions() -> InlineKeyboardMarkup:
        """Create balance amount suggestions with custom option - beautiful and compact layout"""
        keyboard = [
            # First row: Small amounts (2 columns)
            [
                InlineKeyboardButton("💰 10,000 Toman", callback_data="add_balance_10000"),
                InlineKeyboardButton("💰 25,000 Toman", callback_data="add_balance_25000")
            ],
            # Second row: Medium amounts (2 columns)
            [
                InlineKeyboardButton("💰 50,000 Toman", callback_data="add_balance_50000"),
                InlineKeyboardButton("💰 100,000 Toman", callback_data="add_balance_100000")
            ],
            # Third row: Large amounts (2 columns)
            [
                InlineKeyboardButton("💰 250,000 Toman", callback_data="add_balance_250000"),
                InlineKeyboardButton("💰 500,000 Toman", callback_data="add_balance_500000")
            ],
            # Fourth row: Custom option (full width)
            [InlineKeyboardButton("✏️ مبلغ دلخواه", callback_data="custom_balance")],
            # Fifth row: Back button (full width)
            [InlineKeyboardButton("🔙 بازگشت", callback_data="user_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_system_settings_menu() -> InlineKeyboardMarkup:
        """Create professional system settings menu"""
        keyboard = [
            # Row 1: Backup & Status
            [
                InlineKeyboardButton("💾 بکاپ دیتابیس", callback_data="sys_backup"),
                InlineKeyboardButton("📊 وضعیت سیستم", callback_data="sys_status")
            ],
            # Row 2: Logs
            [
                InlineKeyboardButton("📋 لاگ‌های سیستم", callback_data="sys_logs")
            ],
            # Row 3: Restart (Full width for safety)
            [
                InlineKeyboardButton("🔄 ریستارت سرویس‌ها", callback_data="sys_restart")
            ],
            # Row 4: Back
            [
                InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def create_volume_suggestions(panel_id: int, price_per_gb: int = 1000) -> InlineKeyboardMarkup:
        """Create volume suggestions with custom option - professional and dynamic layout"""
        
        # Define volume packages
        volumes = [1, 5, 10, 25, 50, 100]
        
        keyboard = []
        
        # Create rows of 2 buttons each
        for i in range(0, len(volumes), 2):
            row = []
            for j in range(2):
                if i + j < len(volumes):
                    vol = volumes[i + j]
                    price = vol * price_per_gb
                    
                    # Format price with thousand separators
                    price_formatted = f"{price:,}"
                    
                    # Create clean button text without box emoji
                    button_text = f"{vol}GB • {price_formatted}"
                    row.append(InlineKeyboardButton(
                        button_text, 
                        callback_data=f"select_volume_{panel_id}_{vol}"
                    ))
            keyboard.append(row)
        
        # Custom volume option
        keyboard.append([InlineKeyboardButton(
            "✏️ حجم دلخواه", 
            callback_data=f"custom_volume_{panel_id}"
        )])
        
        # Back button
        keyboard.append([InlineKeyboardButton(
            "🔙 بازگشت به لیست سرورها", 
            callback_data="buy_service"
        )])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_user_panel_buttons(services: List[Dict] = None) -> InlineKeyboardMarkup:
        """Create user panel buttons (legacy compatibility)"""
        keyboard = []
        
        # Add service buttons if available
        if services:
            for service in services:
                keyboard.append([InlineKeyboardButton(
                    f"🔧 {service['client_name']} • {service['total_gb']} GB", 
                    callback_data=f"manage_service_{service['id']}"
                )])
        
        # Add main buttons (2 columns)
        keyboard.append([
            InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy_service"),
            InlineKeyboardButton("🧪 اکانت تست", callback_data="test_account")
        ])
        
        keyboard.append([
            InlineKeyboardButton("💰 موجودی", callback_data="account_balance"),
        ])
        
        keyboard.append([
            InlineKeyboardButton("◀️ بازگشت", callback_data="main_menu")
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_gb_selection_buttons(panel_id: int) -> InlineKeyboardMarkup:
        """Create GB selection buttons (legacy compatibility)"""
        gb_options = [1, 5, 10, 25, 50, 100, 250, 500, 1000]
        keyboard = []
        
        # Create rows of 3 buttons each
        for i in range(0, len(gb_options), 3):
            row = []
            for j in range(3):
                if i + j < len(gb_options):
                    gb = gb_options[i + j]
                    row.append(InlineKeyboardButton(
                        f"{gb} گیگابایت", 
                        callback_data=f"select_gb_{panel_id}_{gb}"
                    ))
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="buy_service")])
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_payment_method_buttons(invoice_id: int, user_balance: int, total_amount: int) -> InlineKeyboardMarkup:
        """Create payment method buttons with smart options"""
        keyboard = []
        
        # Add balance payment if user has enough balance
        if user_balance >= total_amount:
            keyboard.append([InlineKeyboardButton(
                f"💰 پرداخت از موجودی ({total_amount:,} ت)", 
                callback_data=f"pay_balance_{invoice_id}"
            )])
        else:
            # If balance is insufficient, show charge button
            shortage = total_amount - user_balance
            keyboard.append([InlineKeyboardButton(
                f"💳 شارژ حساب (کمبود: {shortage:,} ت)", 
                callback_data="add_balance"
            )])
        
        # Add gateway payment only if amount is >= 10,000 Toman (Starsefar minimum)
        if total_amount >= 10000:
            keyboard.append([InlineKeyboardButton(
                "💳 پرداخت آنلاین", 
                callback_data=f"pay_gateway_{invoice_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="buy_service")])
        
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _format_service_name(service: Dict) -> str:
        """Format service name professionally"""
        # Extract relevant info
        name = service.get('client_name', 'Unknown')
        gb = service.get('total_gb', 0)
        status = service.get('status', 'unknown')
        
        # Format name (max 12 chars for shorter display)
        if len(name) > 12:
            name = name[:12]
        
        # Status emoji
        status_emoji = {
            'active': '🟢',
            'inactive': '🔴',
            'expired': '⏰',
            'suspended': '⏸️'
        }.get(status, '⚪')
        
        # Format: [Status] Name • GB
        return f"{status_emoji} {name} • {gb}G"
    
    @staticmethod
    def create_back_button(callback_data: str) -> InlineKeyboardMarkup:
        """Create simple back button"""
        keyboard = [[InlineKeyboardButton(
            "◀️ بازگشت",
            callback_data=callback_data
        )]]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_loading_button() -> InlineKeyboardMarkup:
        """Create loading state button"""
        keyboard = [[InlineKeyboardButton(
            "⏳ در حال پردازش...",
            callback_data="loading"
        )]]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def create_panel_type_selection() -> InlineKeyboardMarkup:
        """Create panel type selection buttons"""
        keyboard = [
            [
                InlineKeyboardButton("🔵 3x-ui", callback_data="panel_type_3x-ui"),
                InlineKeyboardButton("🟢 Marzban", callback_data="panel_type_marzban")
            ],
            [
                InlineKeyboardButton("🟣 Rebecca", callback_data="panel_type_rebecca"),
                InlineKeyboardButton("🟠 Pasargad", callback_data="panel_type_pasargad")
            ],
            [InlineKeyboardButton("❌ لغو", callback_data="manage_panels")]
        ]
        return InlineKeyboardMarkup(keyboard)


# Legacy compatibility
class ButtonLayout(ProfessionalButtonLayout):
    """Legacy compatibility class"""
    pass