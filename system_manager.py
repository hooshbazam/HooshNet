"""
Professional System Manager for VPN Bot
Handles system operations including updates, backups, optimization, and monitoring
"""

import logging
import subprocess
import os
import platform
try:
    import psutil
except ImportError:
    psutil = None
import shutil
from typing import Dict, Optional, Tuple
from telegram import Bot
from database_backup_system import DatabaseBackupSystem
from database_optimization import create_database_indexes
from professional_database import ProfessionalDatabaseManager

logger = logging.getLogger(__name__)

class SystemManager:
    def __init__(self, bot: Bot, db_manager: ProfessionalDatabaseManager, bot_config: Dict):
        """
        Initialize System Manager
        
        Args:
            bot: Telegram Bot instance
            db_manager: Database manager instance
            bot_config: Bot configuration dict
        """
        self.bot = bot
        self.db_manager = db_manager
        self.bot_config = bot_config
        self.backup_system = DatabaseBackupSystem(bot, bot_config, {}) # db_config not needed for create_and_send_backup if using db_manager internally? 
        # Actually DatabaseBackupSystem needs db_config to connect for mysqldump or python backup.
        # We'll pass empty dict for now and rely on it finding credentials from .env or we need to pass real config.
        # Let's check how DatabaseBackupSystem is initialized in telegram_bot.py.
        # It seems it's not initialized there in the snippet I saw, but it's used. 
        # Wait, I saw DatabaseBackupSystem in file list but not in telegram_bot.py main().
        # I'll try to load config from config.py if needed.
        from config import MYSQL_CONFIG
        self.backup_system = DatabaseBackupSystem(bot, bot_config, MYSQL_CONFIG)

    async def update_system(self) -> Tuple[bool, str]:
        """
        Trigger system update via update.sh
        
        Returns:
            Tuple (success, message)
        """
        try:
            script_path = os.path.abspath("update.sh")
            if not os.path.exists(script_path):
                return False, "❌ فایل آپدیت یافت نشد."
            
            # Run update script
            # We use subprocess.Popen to run it detached or wait?
            # Since it restarts services, the bot will die.
            # We should probably send a message first, then run it.
            
            # We'll return True and let the caller send the message, then trigger the script.
            # But we can't trigger it and expect to survive if it restarts us.
            # So we'll use Popen and return immediately.
            
            subprocess.Popen(['sudo', script_path], cwd=os.path.dirname(script_path))
            return True, "✅ سیستم در حال آپدیت است. ربات تا لحظاتی دیگر ریستارت می‌شود."
            
        except Exception as e:
            logger.error(f"Error updating system: {e}")
            return False, f"❌ خطا در آپدیت: {str(e)}"

    async def backup_database(self) -> Tuple[bool, str]:
        """
        Create and send database backup
        
        Returns:
            Tuple (success, message)
        """
        try:
            # Use existing backup system
            backup_path = await self.backup_system.create_and_send_backup()
            if backup_path:
                return True, "✅ بکاپ دیتابیس با موفقیت گرفته و ارسال شد."
            else:
                return False, "❌ خطا در ایجاد بکاپ."
        except Exception as e:
            logger.error(f"Error backing up database: {e}")
            return False, f"❌ خطا در بکاپ گیری: {str(e)}"

    async def optimize_database(self) -> Tuple[bool, str]:
        """
        Optimize database tables and indexes
        
        Returns:
            Tuple (success, message)
        """
        try:
            # Run optimization
            create_database_indexes(self.db_manager)
            return True, "✅ دیتابیس با موفقیت بهینه سازی شد."
        except Exception as e:
            logger.error(f"Error optimizing database: {e}")
            return False, f"❌ خطا در بهینه سازی: {str(e)}"

    async def get_system_status(self) -> str:
        """
        Get system resource usage and status
        
        Returns:
            Formatted status string
        """
        try:
            if not psutil:
                return "⚠️ ماژول psutil نصب نشده است.\nلطفاً از منوی تنظیمات، گزینه 'آپدیت سیستم' را انتخاب کنید تا وابستگی‌های جدید نصب شوند."

            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # RAM
            memory = psutil.virtual_memory()
            ram_used = memory.used / (1024 * 1024 * 1024)
            ram_total = memory.total / (1024 * 1024 * 1024)
            ram_percent = memory.percent
            
            # Disk
            disk = psutil.disk_usage('/')
            disk_used = disk.used / (1024 * 1024 * 1024)
            disk_total = disk.total / (1024 * 1024 * 1024)
            disk_percent = disk.percent
            
            # Services
            bot_active = self._check_service_active('vpn-bot')
            webapp_active = self._check_service_active('vpn-webapp')
            mysql_active = self._check_service_active('mysql')
            nginx_active = self._check_service_active('nginx')
            
            status_text = f"""
📊 **وضعیت سیستم**

💻 **منابع سرور:**
• پردازنده: {cpu_percent}%
• رم: {ram_used:.1f}GB / {ram_total:.1f}GB ({ram_percent}%)
• دیسک: {disk_used:.1f}GB / {disk_total:.1f}GB ({disk_percent}%)

⚙️ **سرویس‌ها:**
• ربات تلگرام: {'✅ فعال' if bot_active else '🔴 غیرفعال'}
• وب اپلیکیشن: {'✅ فعال' if webapp_active else '🔴 غیرفعال'}
• دیتابیس: {'✅ فعال' if mysql_active else '🔴 غیرفعال'}
• وب سرور: {'✅ فعال' if nginx_active else '🔴 غیرفعال'}
            """
            return status_text
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return "❌ خطا در دریافت وضعیت سیستم."

    async def get_system_logs(self, lines: int = 50) -> str:
        """
        Get recent system logs using journalctl
        
        Args:
            lines: Number of lines to retrieve
            
        Returns:
            Log content string
        """
        try:
            # Try to get logs from journalctl (for systemd service)
            cmd = ['journalctl', '-u', 'vpn-bot', '-n', str(lines), '--no-pager']
            
            # Check if running on Linux
            if platform.system() != 'Linux':
                return "⚠️ دریافت لاگ‌ها فقط در سرور لینوکس امکان‌پذیر است."
                
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if process.returncode == 0:
                logs = process.stdout
                if not logs:
                    return "📭 لاگ جدیدی یافت نشد."
                return logs
            else:
                return f"❌ خطا در دریافت لاگ‌ها: {process.stderr}"
                
        except Exception as e:
            logger.error(f"Error getting system logs: {e}")
            return f"❌ خطا در دریافت لاگ‌ها: {str(e)}"

    async def restart_services(self) -> Tuple[bool, str]:
        """
        Restart bot and webapp services
        
        Returns:
            Tuple (success, message)
        """
        try:
            # Restart services
            subprocess.Popen(['sudo', 'systemctl', 'restart', 'vpn-bot', 'vpn-webapp'])
            return True, "✅ دستور ریستارت ارسال شد. ربات تا لحظاتی دیگر مجدداً فعال می‌شود."
        except Exception as e:
            logger.error(f"Error restarting services: {e}")
            return False, f"❌ خطا در ریستارت: {str(e)}"

    def _check_service_active(self, service_name: str) -> bool:
        """Check if a systemd service is active"""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return result.stdout.strip() == 'active'
        except Exception:
            return False
