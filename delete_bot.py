#!/usr/bin/env python3
"""
حذف ربات از سیستم چندرباتی
این اسکریپت یک ربات را از سیستم حذف می‌کند (soft delete - غیرفعال می‌کند)
"""

import os
import sys
import logging
from pathlib import Path

# Add bots directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bots.bot_config_manager import BotConfigManager

# Configure logging
logging.basicConfig(
    format='%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def delete_bot(bot_name: str, hard_delete: bool = False):
    """
    حذف یک ربات از سیستم
    
    Args:
        bot_name: نام ربات برای حذف
        hard_delete: اگر True باشد، ربات به طور کامل حذف می‌شود (نه فقط غیرفعال)
    """
    config_manager = BotConfigManager()
    
    # بررسی وجود ربات
    bot_config = config_manager.get_bot_config(bot_name)
    if not bot_config:
        print(f"❌ ربات '{bot_name}' یافت نشد!")
        return False
    
    print(f"\n{'=' * 60}")
    print(f"🗑️  حذف ربات: {bot_name}")
    print(f"{'=' * 60}\n")
    
    # نمایش اطلاعات ربات
    print(f"📱 نام کاربری ربات: @{bot_config.get('bot_username', 'N/A')}")
    print(f"💾 نام دیتابیس: {bot_config.get('database_name', 'N/A')}")
    print(f"🌐 URL وب‌اپ: {bot_config.get('webapp_url', 'N/A')}/{bot_name}/")
    print(f"📅 تاریخ ایجاد: {bot_config.get('created_at', 'N/A')}")
    print()
    
    # تایید حذف
    if hard_delete:
        print("⚠️  هشدار: شما در حال حذف کامل ربات هستید!")
        print("این عمل غیرقابل بازگشت است و تمام اطلاعات ربات حذف خواهد شد.")
        confirm = input(f"\nآیا مطمئن هستید که می‌خواهید ربات '{bot_name}' را به طور کامل حذف کنید؟ (yes/no): ")
    else:
        print("ℹ️  ربات به صورت soft delete حذف می‌شود (غیرفعال می‌شود).")
        print("می‌توانید بعداً دوباره آن را فعال کنید.")
        confirm = input(f"\nآیا مطمئن هستید که می‌خواهید ربات '{bot_name}' را غیرفعال کنید؟ (yes/no): ")
    
    if confirm.lower() not in ['yes', 'y', 'بله']:
        print("❌ عملیات لغو شد.")
        return False
    
    try:
        if hard_delete:
            # حذف کامل از config
            if 'bots' in config_manager.config and bot_name in config_manager.config['bots']:
                del config_manager.config['bots'][bot_name]
                config_manager._save_config()
                logger.info(f"Bot '{bot_name}' completely deleted from configuration")
                print(f"✅ ربات '{bot_name}' به طور کامل حذف شد.")
            else:
                print(f"❌ خطا: ربات '{bot_name}' در تنظیمات یافت نشد.")
                return False
        else:
            # Soft delete - فقط غیرفعال کردن
            success = config_manager.delete_bot(bot_name)
            if success:
                logger.info(f"Bot '{bot_name}' marked as inactive")
                print(f"✅ ربات '{bot_name}' غیرفعال شد.")
            else:
                print(f"❌ خطا در غیرفعال کردن ربات '{bot_name}'.")
                return False
        
        print(f"\n{'=' * 60}")
        print("✅ عملیات با موفقیت انجام شد!")
        print(f"{'=' * 60}\n")
        
        if not hard_delete:
            print("💡 برای فعال کردن مجدد ربات، می‌توانید از setup_bot.py استفاده کنید.")
            print("💡 برای حذف کامل ربات، از دستور زیر استفاده کنید:")
            print(f"   python delete_bot.py {bot_name} --hard-delete")
        
        return True
        
    except Exception as e:
        logger.error(f"Error deleting bot '{bot_name}': {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(f"❌ خطا در حذف ربات: {e}")
        return False

def list_bots():
    """لیست تمام ربات‌های موجود"""
    config_manager = BotConfigManager()
    all_bots = config_manager.get_all_bots()
    active_bots = config_manager.get_active_bots()
    
    if not all_bots:
        print("❌ هیچ رباتی یافت نشد!")
        return
    
    print(f"\n{'=' * 60}")
    print("📋 لیست ربات‌ها")
    print(f"{'=' * 60}\n")
    
    for bot_name, bot_config in all_bots.items():
        is_active = bot_config.get('is_active', True)
        status = "✅ فعال" if is_active else "❌ غیرفعال"
        print(f"{status} - {bot_name}")
        print(f"   📱 @{bot_config.get('bot_username', 'N/A')}")
        print(f"   💾 دیتابیس: {bot_config.get('database_name', 'N/A')}")
        print()

def main():
    """Main entry point"""
    print()
    print("=" * 60)
    print("🗑️  سیستم حذف ربات VPN Bot")
    print("=" * 60)
    print()
    
    if len(sys.argv) < 2:
        print("استفاده:")
        print("  python delete_bot.py <bot_name>              # غیرفعال کردن ربات (soft delete)")
        print("  python delete_bot.py <bot_name> --hard-delete  # حذف کامل ربات")
        print("  python delete_bot.py --list                 # نمایش لیست ربات‌ها")
        print()
        list_bots()
        return
    
    if sys.argv[1] == '--list':
        list_bots()
        return
    
    bot_name = sys.argv[1]
    hard_delete = '--hard-delete' in sys.argv
    
    delete_bot(bot_name, hard_delete)

if __name__ == '__main__':
    main()


