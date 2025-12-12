#!/usr/bin/env python3
"""
اسکریپت اجرای ربات مدیریتی
این اسکریپت ربات مدیریتی را برای مدیریت ربات‌های VPN راه‌اندازی می‌کند
"""

import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from admin_bot import AdminBot
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('admin_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    """Main entry point"""
    print()
    print("=" * 60)
    print("🤖 سیستم مدیریت ربات‌های VPN")
    print("=" * 60)
    print()
    
    # Load environment variables
    load_dotenv()
    
    # Get admin bot token and admin IDs from environment
    admin_bot_token = os.getenv('ADMIN_BOT_TOKEN')
    admin_ids_str = os.getenv('ADMIN_BOT_ADMIN_IDS', '')
    
    if not admin_bot_token:
        logger.error("❌ ADMIN_BOT_TOKEN باید در فایل .env تنظیم شود!")
        print("❌ خطا: ADMIN_BOT_TOKEN باید در فایل .env تنظیم شود!")
        print()
        print("لطفاً فایل .env را ویرایش کنید و موارد زیر را اضافه کنید:")
        print("  ADMIN_BOT_TOKEN=your_bot_token_here")
        print("  ADMIN_BOT_ADMIN_IDS=your_telegram_user_id")
        print()
        return
    
    # Parse admin IDs
    admin_ids = []
    if admin_ids_str:
        for admin_id_str in admin_ids_str.split(','):
            try:
                admin_ids.append(int(admin_id_str.strip()))
            except ValueError:
                logger.warning(f"⚠️ شناسه ادمین نامعتبر: {admin_id_str}")
    
    if not admin_ids:
        logger.error("❌ ADMIN_BOT_ADMIN_IDS باید در فایل .env تنظیم شود!")
        print("❌ خطا: ADMIN_BOT_ADMIN_IDS باید در فایل .env تنظیم شود!")
        print()
        print("لطفاً فایل .env را ویرایش کنید و شناسه تلگرام خود را اضافه کنید:")
        print("  ADMIN_BOT_ADMIN_IDS=your_telegram_user_id")
        print()
        print("💡 برای دریافت شناسه تلگرام خود، از ربات @userinfobot استفاده کنید.")
        print()
        return
    
    print(f"✅ توکن ربات مدیریتی یافت شد")
    print(f"✅ {len(admin_ids)} ادمین شناسایی شد")
    print()
    print("🔄 در حال راه‌اندازی ربات مدیریتی...")
    print()
    
    try:
        # Create and run bot
        bot = AdminBot(admin_bot_token, admin_ids)
        logger.info("✅ ربات مدیریتی با موفقیت راه‌اندازی شد")
        print("✅ ربات مدیریتی با موفقیت راه‌اندازی شد!")
        print()
        print("💡 برای استفاده از ربات، دستور /start را در ربات مدیریتی ارسال کنید.")
        print()
        bot.run()
    except KeyboardInterrupt:
        logger.info("ربات مدیریتی متوقف شد")
        print()
        print("🛑 ربات مدیریتی متوقف شد.")
    except Exception as e:
        logger.error(f"❌ خطا در راه‌اندازی ربات: {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(f"❌ خطا در راه‌اندازی ربات: {e}")
        print()
        print("لطفاً لاگ‌ها را بررسی کنید: admin_bot.log")

if __name__ == '__main__':
    main()







