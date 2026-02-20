"""
Professional Statistics System
Provides comprehensive real-time statistics and analytics for VPN Bot
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from persian_datetime import PersianDateTime, TEHRAN_TZ
import pytz
from professional_database import ProfessionalDatabaseManager
from admin_manager import AdminManager

logger = logging.getLogger(__name__)

class StatisticsSystem:
    """Professional statistics and analytics system"""
    
    ITEMS_PER_PAGE = 10
    
    def __init__(self, db: ProfessionalDatabaseManager, admin_manager: AdminManager):
        self.db = db
        self.admin_manager = admin_manager
    
    def _current_tehran_datetime(self) -> datetime:
        """Get current datetime in Tehran timezone as naive datetime"""
        try:
            utc_now = datetime.now(pytz.UTC)
            tehran_now = utc_now.astimezone(TEHRAN_TZ)
            # Return naive datetime to match database format
            return tehran_now.replace(tzinfo=None)
        except Exception as e:
            logger.debug(f"Error getting Tehran datetime: {e}")
            return datetime.now()
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse datetime string from database to datetime object"""
        try:
            if not dt_str:
                return None
            # Use PersianDateTime parsing
            return PersianDateTime.parse_datetime(dt_str)
        except Exception as e:
            logger.debug(f"Error parsing datetime '{dt_str}': {e}")
            return None
    
    def _is_recent_date(self, dt_str: str, days: int) -> bool:
        """Check if date is within last N days"""
        try:
            parsed_dt = self._parse_datetime(dt_str)
            if not parsed_dt:
                return False
            diff = (self._current_tehran_datetime() - parsed_dt).days
            return 0 <= diff <= days
        except Exception as e:
            logger.debug(f"Error checking if recent date: {e}")
            return False
    
    def _is_today(self, dt_str: str) -> bool:
        """Check if date is today"""
        try:
            parsed_dt = self._parse_datetime(dt_str)
            if not parsed_dt:
                return False
            return parsed_dt.date() == self._current_tehran_datetime().date()
        except Exception as e:
            logger.debug(f"Error checking if today: {e}")
            return False
    
    def get_statistics_main_menu(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get main statistics menu"""
        message = """📊 **پنل آمار و گزارشات**

**دسته‌بندی گزارشات:**

لطفاً یکی از دسته‌بندی‌های زیر را انتخاب کنید:"""
        
        keyboard = [
            [InlineKeyboardButton("👥 آمار کاربران", callback_data="stats_users"), InlineKeyboardButton("🛒 آمار سفارشات", callback_data="stats_services")],
            [InlineKeyboardButton("💳 آمار پرداختی‌ها", callback_data="stats_payments"), InlineKeyboardButton("📈 آمار درآمد", callback_data="stats_revenue")],
            [InlineKeyboardButton("🔗 سرویس‌های آنلاین", callback_data="stats_online"), InlineKeyboardButton("📋 لیست‌های مدیریتی", callback_data="stats_lists")],
            [InlineKeyboardButton("◀️ بازگشت", callback_data="admin_panel")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        return message, reply_markup
    
    def get_user_statistics(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get detailed user statistics"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT COUNT(*) AS cnt FROM users")
                total_users = int((cursor.fetchone() or {}).get('cnt') or 0)
                
                cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE last_activity >= DATE_SUB(NOW(), INTERVAL 7 DAY)")
                active_count = int((cursor.fetchone() or {}).get('cnt') or 0)
                
                cursor.execute("""
                    SELECT COUNT(DISTINCT u.id) AS cnt
                    FROM users u
                    JOIN clients c ON c.user_id = u.id
                """)
                users_with_services_count = int((cursor.fetchone() or {}).get('cnt') or 0)
                
                cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE DATE(created_at) = CURDATE()")
                new_users_today_count = int((cursor.fetchone() or {}).get('cnt') or 0)
                
                cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)")
                new_users_week_count = int((cursor.fetchone() or {}).get('cnt') or 0)
                
                cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
                new_users_month_count = int((cursor.fetchone() or {}).get('cnt') or 0)
            
            # Format message
            message = f"""👥 **آمار کاربران**

📊 **کلی:**
• کل کاربران: `{total_users:,} نفر`
• کاربران فعال (۷ روز گذشته): `{active_count:,} نفر`
• کاربران با سرویس: `{users_with_services_count:,} نفر`
• کاربران بدون سرویس: `{total_users - users_with_services_count:,} نفر`

📈 **ثبت نام‌های جدید:**
• امروز: `{new_users_today_count} نفر`
• هفته گذشته: `{new_users_week_count} نفر`
• ماه گذشته: `{new_users_month_count} نفر`

⏰ **آخرین به‌روزرسانی:** {PersianDateTime.now().strftime('%H:%M:%S')}"""
            
            keyboard = [
                [InlineKeyboardButton("📋 کاربران فعال", callback_data="stats_active_users_1"), InlineKeyboardButton("🆕 ثبت نام‌های جدید", callback_data="stats_new_users_1")],
                [InlineKeyboardButton("👥 همه کاربران", callback_data="stats_all_users_1")],
                [InlineKeyboardButton("◀️ بازگشت به آمار", callback_data="admin_stats")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting user statistics: {e}")
            return "❌ خطا در دریافت آمار کاربران", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="admin_stats")]
            ])
    
    def get_all_users_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of all users"""
        try:
            all_users = self.db.get_all_users()
            
            # Pagination
            total_pages = (len(all_users) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE
            start_idx = (page - 1) * self.ITEMS_PER_PAGE
            end_idx = start_idx + self.ITEMS_PER_PAGE
            
            users_page = all_users[start_idx:end_idx]
            
            # Create buttons for users
            keyboard = []
            for user in users_page:
                user_id = user.get('telegram_id', 'N/A')
                username = user.get('username', 'بدون نام کاربری')
                services_count = user.get('total_services', 0)
                balance = user.get('balance', 0)
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"🆔 {user_id} | 💰 {balance:,} تومان",
                        callback_data=f"user_detail_{user_id}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_all_users_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_all_users_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_users")])
            
            message = f"""👥 **لیست همه کاربران**

📊 **صفحه:** `{page}/{total_pages}`
👥 **کل کاربران:** `{len(all_users):,} نفر`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting all users list: {e}")
            return "❌ خطا در دریافت لیست کاربران", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_users")]
            ])
    
    def get_active_users_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of active users (last 7 days)"""
        try:
            all_users = self.db.get_all_users()
            
            # Get active users (logged in within last 7 days)
            active_users = [u for u in all_users if u.get('last_activity') and 
                          self._is_recent_date(u['last_activity'], days=7)]
            
            # Pagination
            total_pages = (len(active_users) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE if active_users else 1
            start_idx = (page - 1) * self.ITEMS_PER_PAGE
            end_idx = start_idx + self.ITEMS_PER_PAGE
            
            users_page = active_users[start_idx:end_idx]
            
            # Create buttons for users
            keyboard = []
            for user in users_page:
                user_id = user.get('telegram_id', 'N/A')
                balance = user.get('balance', 0)
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"🆔 {user_id} | 💰 {balance:,} تومان",
                        callback_data=f"user_detail_{user_id}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_active_users_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_active_users_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_users")])
            
            message = f"""📋 **لیست کاربران فعال**

📊 **صفحه:** `{page}/{total_pages}`
👥 **کاربران فعال (۷ روز گذشته):** `{len(active_users):,} نفر`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting active users list: {e}")
            return "❌ خطا در دریافت لیست کاربران فعال", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_users")]
            ])
    
    def get_services_statistics(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get detailed services statistics"""
        try:
            stats = self.db.get_system_stats()
            total_services = int(stats.get('total_services', 0) or 0)
            active_services = int(stats.get('active_services', 0) or 0)
            disabled_services = int(stats.get('disabled_services', 0) or 0)
            total_volume = float(stats.get('total_volume_gb', 0.0) or 0.0)
            used_volume = float(stats.get('used_volume_gb', 0.0) or 0.0)

            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT p.name AS panel_name, COUNT(*) AS cnt
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    GROUP BY p.id
                    ORDER BY cnt DESC
                    LIMIT 5
                """)
                panel_rows = cursor.fetchall() or []
                services_by_panel_lines = [
                    f"• {r.get('panel_name', 'نامشخص')}: `{int(r.get('cnt') or 0)} عدد`"
                    for r in panel_rows
                ]
            
            # Format message
            message = f"""🛒 **آمار سفارشات و خدمات**

📊 **کلی:**
• کل سرویس‌ها: `{total_services} عدد`
• سرویس‌های فعال: `{active_services} عدد`
• سرویس‌های غیرفعال: `{disabled_services} عدد`

📦 **حجم:**
• حجم کل: `{total_volume:.2f} گیگابایت`
• حجم مصرفی: `{used_volume:.2f} گیگابایت`
• حجم باقی‌مانده: `{max(0, total_volume - used_volume):.2f} گیگابایت`

🔗 **توزیع سرویس‌ها بر اساس پنل:**
{chr(10).join(services_by_panel_lines) if services_by_panel_lines else '—'}

⏰ **آخرین به‌روزرسانی:** {PersianDateTime.now().strftime('%H:%M:%S')}"""
            
            keyboard = [
                [InlineKeyboardButton("📋 همه سرویس‌ها", callback_data="stats_all_services_1"), InlineKeyboardButton("🟢 سرویس‌های فعال", callback_data="stats_active_services_1")],
                [InlineKeyboardButton("🔴 سرویس‌های غیرفعال", callback_data="stats_disabled_services_1")],
                [InlineKeyboardButton("◀️ بازگشت به آمار", callback_data="admin_stats")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting services statistics: {e}")
            return "❌ خطا در دریافت آمار سرویس‌ها", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="admin_stats")]
            ])
    
    def get_all_services_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of all services"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                """)
                total_services = int((cursor.fetchone() or {}).get('cnt') or 0)

                total_pages = max(1, (total_services + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
                page = max(1, min(page, total_pages))
                offset = (page - 1) * self.ITEMS_PER_PAGE

                cursor.execute(f"""
                    SELECT
                        c.id, c.client_name, c.total_gb,
                        COALESCE(c.used_gb, c.cached_used_gb, 0) AS used_gb,
                        c.is_active, c.status
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    ORDER BY c.created_at DESC
                    LIMIT {self.ITEMS_PER_PAGE} OFFSET %s
                """, (offset,))
                services_page = cursor.fetchall() or []
            
            # Create buttons for services
            keyboard = []
            for service in services_page:
                service_name = service.get('client_name', 'نامشخص')
                volume = float(service.get('total_gb') or 0)
                used = float(service.get('used_gb') or 0)
                is_active = int(service.get('is_active') or 0)
                status_str = str(service.get('status') or '')
                if is_active == 1 and (status_str == 'active' or status_str == ''):
                    status_icon = "🟢"
                elif status_str == 'exhausted':
                    status_icon = "🟠"
                elif status_str == 'expired':
                    status_icon = "🟡"
                else:
                    status_icon = "🔴"
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"{status_icon} {service_name} | {used:.1f}GB/{volume:.1f}GB",
                        callback_data=f"service_detail_{service['id']}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_all_services_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_all_services_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_services")])
            
            message = f"""🛒 **لیست همه سرویس‌ها**

📊 **صفحه:** `{page}/{total_pages}`
📦 **کل سرویس‌ها:** `{total_services} عدد`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting all services list: {e}")
            return "❌ خطا در دریافت لیست سرویس‌ها", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_services")]
            ])
    
    async def get_online_services(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get real-time online services from all panels"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM clients
                    WHERE (is_active = 1 OR status = 'active' OR status IS NULL OR status = '')
                      AND COALESCE(status, '') NOT IN ('disabled', 'expired', 'exhausted')
                """)
                total_active = int((cursor.fetchone() or {}).get('cnt') or 0)

                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM clients
                    WHERE (is_active = 1 OR status = 'active' OR status IS NULL OR status = '')
                      AND COALESCE(status, '') NOT IN ('disabled', 'expired', 'exhausted')
                      AND COALESCE(cached_is_online, 0) = 1
                """)
                online_count = int((cursor.fetchone() or {}).get('cnt') or 0)

                cursor.execute("""
                    SELECT
                        c.id, c.client_name, c.total_gb,
                        COALESCE(c.used_gb, c.cached_used_gb, 0) AS used_gb,
                        p.name AS panel_name
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    WHERE c.is_active = 1
                      AND (c.status = 'active' OR c.status IS NULL OR c.status = '')
                      AND COALESCE(c.status, '') NOT IN ('disabled', 'expired', 'exhausted')
                      AND COALESCE(cached_is_online, 0) = 1
                    ORDER BY c.cached_last_activity DESC, c.created_at DESC
                    LIMIT 30
                """)
                online_services = cursor.fetchall() or []

            lines = []
            for s in online_services:
                name = s.get('client_name', 'سرویس')
                panel_name = s.get('panel_name', 'نامشخص')
                used = float(s.get('used_gb') or 0)
                total = float(s.get('total_gb') or 0)
                lines.append(f"• {name} ({panel_name}) — {used:.1f}/{total:.1f}GB")

            message = f"""🔗 **سرویس‌های آنلاین**

📊 **وضعیت:**
• سرویس‌های آنلاین: `{online_count} عدد`
• سرویس‌های آفلاین: `{max(0, total_active - online_count)} عدد`
• کل سرویس‌های فعال: `{total_active} عدد`

📋 **نمایش (حداکثر ۳۰ مورد):**
{chr(10).join(lines) if lines else '—'}

⏰ **آخرین به‌روزرسانی:** {PersianDateTime.now().strftime('%H:%M:%S')}"""

            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 بروزرسانی", callback_data="stats_online")],
                [InlineKeyboardButton("◀️ بازگشت به آمار", callback_data="admin_stats")]
            ])
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting online services: {e}")
            return "❌ خطا در دریافت سرویس‌های آنلاین", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="admin_stats")]
            ])
    
    def get_payment_statistics(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get payment statistics"""
        try:
            # Use invoices with statuses 'paid' and 'completed' for consistency with web panel revenue
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                cursor.execute("""
                    SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                      AND DATE(created_at) = CURDATE()
                """)
                row_today = cursor.fetchone() or {}
                payment_count_today = int(row_today.get('cnt') or 0)
                total_today = int(row_today.get('total') or 0)
                
                cursor.execute("""
                    SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                """)
                row_week = cursor.fetchone() or {}
                payment_count_week = int(row_week.get('cnt') or 0)
                total_week = int(row_week.get('total') or 0)
                
                cursor.execute("""
                    SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """)
                row_month = cursor.fetchone() or {}
                payment_count_month = int(row_month.get('cnt') or 0)
                total_month = int(row_month.get('total') or 0)
            
            # Format message
            message = f"""💳 **آمار پرداختی‌ها**

📊 **امروز:**
• تعداد: `{payment_count_today} تراکنش`
• مبلغ: `{total_today:,} تومان`

📈 **هفته گذشته:**
• تعداد: `{payment_count_week} تراکنش`
• مبلغ: `{total_week:,} تومان`

📊 **ماه گذشته:**
• تعداد: `{payment_count_month} تراکنش`
• مبلغ: `{total_month:,} تومان`

⏰ **آخرین به‌روزرسانی:** {PersianDateTime.now().strftime('%H:%M:%S')}"""
            
            keyboard = [
                [InlineKeyboardButton("📋 آخرین تراکنش‌ها", callback_data="stats_recent_payments_1")],
                [InlineKeyboardButton("◀️ بازگشت به آمار", callback_data="admin_stats")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting payment statistics: {e}")
            return "❌ خطا در دریافت آمار پرداختی‌ها", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="admin_stats")]
            ])
    
    def get_recent_payments_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of recent payments"""
        try:
            # Get recent payment transactions (only positive amounts from balance additions)
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT bt.*, u.telegram_id, u.username, u.first_name 
                    FROM balance_transactions bt
                    JOIN users u ON bt.user_id = u.id
                    WHERE bt.amount > 0 
                    AND bt.transaction_type IN ('balance_add', 'payment_callback', 'gateway', 'balance_recharge', 'gift', 'referral_reward')
                    ORDER BY bt.created_at DESC
                ''')
                transactions = cursor.fetchall() or []
            
            # Pagination
            total_pages = max(1, (len(transactions) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
            start_idx = (page - 1) * self.ITEMS_PER_PAGE
            end_idx = start_idx + self.ITEMS_PER_PAGE
            
            transactions_page = transactions[start_idx:end_idx]
            
            # Create buttons for transactions (3 inline buttons per row as requested)
            keyboard = []
            for txn in transactions_page:
                user_id = txn.get('telegram_id', 'N/A')
                amount = txn.get('amount', 0)
                description = txn.get('description', '')
                
                # Determine payment type from description
                if 'callback' in description.lower() and 'order' in description.lower():
                    payment_type = 'شارژ حساب'
                elif 'service' in description.lower() or 'purchase' in description.lower():
                    payment_type = 'خرید سرویس'
                else:
                    payment_type = 'پرداخت'
                
                # Three inline buttons side by side as requested
                keyboard.append([
                    InlineKeyboardButton(f"👤 {user_id}", callback_data=f"user_detail_{user_id}"),
                    InlineKeyboardButton(f"💰 {amount:,}ت", callback_data=f"payment_detail_{txn['id']}"),
                    InlineKeyboardButton(f"📦 {payment_type}", callback_data=f"payment_detail_{txn['id']}")
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_recent_payments_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_recent_payments_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_payments")])
            
            message = f"""💳 **آخرین تراکنش‌ها**

📊 **صفحه:** `{page}/{total_pages}`
💰 **کل تراکنش‌ها:** `{len(transactions)} عدد`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting recent payments list: {e}")
            return "❌ خطا در دریافت لیست تراکنش‌ها", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_payments")]
            ])
    
    def get_revenue_statistics(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get revenue statistics"""
        try:
            # Use SQL-based aggregation to avoid datetime parsing issues
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                cursor.execute("""
                    SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                      AND DATE(created_at) = CURDATE()
                """)
                row_today = cursor.fetchone() or {}
                orders_today = int(row_today.get('cnt') or 0)
                revenue_today = int(row_today.get('total') or 0)
                
                cursor.execute("""
                    SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                """)
                row_week = cursor.fetchone() or {}
                orders_week = int(row_week.get('cnt') or 0)
                revenue_week = int(row_week.get('total') or 0)
                
                cursor.execute("""
                    SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """)
                row_month = cursor.fetchone() or {}
                orders_month = int(row_month.get('cnt') or 0)
                revenue_month = int(row_month.get('total') or 0)
                
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) AS total
                    FROM invoices
                    WHERE status IN ('paid', 'completed')
                """)
                revenue_total = int((cursor.fetchone() or {}).get('total') or 0)
            
            # Format message
            message = f"""📈 **آمار درآمد**

💰 **درآمد امروز:**
• تعداد سفارش: `{orders_today} عدد`
• مبلغ کل: `{revenue_today:,} تومان`

📊 **درآمد هفته گذشته:**
• تعداد سفارش: `{orders_week} عدد`
• مبلغ کل: `{revenue_week:,} تومان`

📈 **درآمد ماه گذشته:**
• تعداد سفارش: `{orders_month} عدد`
• مبلغ کل: `{revenue_month:,} تومان`

🏆 **درآمد کل:**
• مبلغ کل: `{revenue_total:,} تومان`

⏰ **آخرین به‌روزرسانی:** {PersianDateTime.now().strftime('%H:%M:%S')}"""
            
            keyboard = [
                [InlineKeyboardButton("📋 آخرین سفارشات", callback_data="stats_recent_orders_1")],
                [InlineKeyboardButton("◀️ بازگشت به آمار", callback_data="admin_stats")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting revenue statistics: {e}")
            return "❌ خطا در دریافت آمار درآمد", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="admin_stats")]
            ])
    
    def get_recent_orders_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of recent orders"""
        try:
            # Get recent invoices
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT i.*, u.telegram_id, u.username, u.first_name 
                    FROM invoices i
                    JOIN users u ON i.user_id = u.id
                    ORDER BY i.created_at DESC
                ''')
                invoices = cursor.fetchall() or []
            
            # Pagination
            total_pages = max(1, (len(invoices) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
            start_idx = (page - 1) * self.ITEMS_PER_PAGE
            end_idx = start_idx + self.ITEMS_PER_PAGE
            
            invoices_page = invoices[start_idx:end_idx]
            
            # Create buttons for invoices
            keyboard = []
            for inv in invoices_page:
                user_id = inv.get('telegram_id', 'N/A')
                amount = inv.get('amount', 0)
                volume = inv.get('gb_amount', 0)
                status_emoji = "✅" if inv.get('status', '') in ['completed', 'paid'] else "⏳"
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"{status_emoji} 👤 {user_id} | {volume}GB | 💰 {amount:,} تومان",
                        callback_data=f"order_detail_{inv['id']}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_recent_orders_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_recent_orders_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_revenue")])
            
            message = f"""📋 **آخرین سفارشات**

📊 **صفحه:** `{page}/{total_pages}`
🛒 **کل سفارشات:** `{len(invoices)} عدد`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting recent orders list: {e}")
            return "❌ خطا در دریافت لیست سفارشات", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_revenue")]
            ])
    
    def get_lists_menu(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Get management lists menu"""
        message = """📋 **لیست‌های مدیریتی**

لطفاً یکی از لیست‌های زیر را انتخاب کنید:"""
        
        keyboard = [
            [InlineKeyboardButton("📋 آخرین سفارشات", callback_data="stats_recent_orders_1"), InlineKeyboardButton("💳 آخرین تراکنش‌ها", callback_data="stats_recent_payments_1")],
            [InlineKeyboardButton("🆕 آخرین ثبت نام‌ها", callback_data="stats_new_users_1")],
            [InlineKeyboardButton("◀️ بازگشت به آمار", callback_data="admin_stats")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        return message, reply_markup
    
    def get_active_services_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of active services"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    WHERE (c.is_active = 1 OR c.status = 'active' OR c.status IS NULL OR c.status = '')
                      AND COALESCE(c.status, '') NOT IN ('disabled', 'expired', 'exhausted')
                """)
                total_services = int((cursor.fetchone() or {}).get('cnt') or 0)

                total_pages = max(1, (total_services + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
                page = max(1, min(page, total_pages))
                offset = (page - 1) * self.ITEMS_PER_PAGE

                cursor.execute(f"""
                    SELECT
                        c.id, c.client_name, c.total_gb,
                        COALESCE(c.used_gb, c.cached_used_gb, 0) AS used_gb
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    WHERE (c.is_active = 1 OR c.status = 'active' OR c.status IS NULL OR c.status = '')
                      AND COALESCE(c.status, '') NOT IN ('disabled', 'expired', 'exhausted')
                    ORDER BY c.created_at DESC
                    LIMIT {self.ITEMS_PER_PAGE} OFFSET %s
                """, (offset,))
                services_page = cursor.fetchall() or []
            
            # Create buttons for services
            keyboard = []
            for service in services_page:
                service_name = service.get('client_name', 'نامشخص')
                volume = float(service.get('total_gb') or 0)
                used = float(service.get('used_gb') or 0)
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"🟢 {service_name} | {used:.1f}GB/{volume:.1f}GB",
                        callback_data=f"service_detail_{service['id']}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_active_services_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_active_services_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_services")])
            
            message = f"""🟢 **لیست سرویس‌های فعال**

📊 **صفحه:** `{page}/{total_pages}`
📦 **سرویس‌های فعال:** `{total_services} عدد`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting active services list: {e}")
            return "❌ خطا در دریافت لیست سرویس‌های فعال", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_services")]
            ])
    
    def get_disabled_services_list(self, page: int) -> Tuple[str, InlineKeyboardMarkup]:
        """Get paginated list of disabled services"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    WHERE c.is_active = 0 OR c.status IN ('disabled', 'expired', 'exhausted')
                """)
                total_services = int((cursor.fetchone() or {}).get('cnt') or 0)

                total_pages = max(1, (total_services + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
                page = max(1, min(page, total_pages))
                offset = (page - 1) * self.ITEMS_PER_PAGE

                cursor.execute(f"""
                    SELECT
                        c.id, c.client_name, c.total_gb,
                        COALESCE(c.used_gb, c.cached_used_gb, 0) AS used_gb,
                        c.status
                    FROM clients c
                    JOIN panels p ON c.panel_id = p.id
                    WHERE c.is_active = 0 OR c.status IN ('disabled', 'expired', 'exhausted')
                    ORDER BY c.created_at DESC
                    LIMIT {self.ITEMS_PER_PAGE} OFFSET %s
                """, (offset,))
                services_page = cursor.fetchall() or []
            
            # Create buttons for services
            keyboard = []
            for service in services_page:
                service_name = service.get('client_name', 'نامشخص')
                volume = float(service.get('total_gb') or 0)
                used = float(service.get('used_gb') or 0)
                status_str = str(service.get('status') or '')
                if status_str == 'exhausted':
                    status_icon = "🟠"
                elif status_str == 'expired':
                    status_icon = "🟡"
                else:
                    status_icon = "🔴"
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"{status_icon} {service_name} | {used:.1f}GB/{volume:.1f}GB",
                        callback_data=f"service_detail_{service['id']}"
                    )
                ])
            
            # Pagination buttons
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"stats_disabled_services_{page - 1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="page_info"))
            
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("▶️ بعدی", callback_data=f"stats_disabled_services_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="stats_services")])
            
            message = f"""🔴 **لیست سرویس‌های غیرفعال**

📊 **صفحه:** `{page}/{total_pages}`
📦 **سرویس‌های غیرفعال:** `{total_services} عدد`"""
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            return message, reply_markup
            
        except Exception as e:
            logger.error(f"Error getting disabled services list: {e}")
            return "❌ خطا در دریافت لیست سرویس‌های غیرفعال", InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت", callback_data="stats_services")]
            ])

