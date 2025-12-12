#!/usr/bin/env python3
"""
Bot Setup Script
Creates and configures a new bot instance
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Optional

# Add bots directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bots.bot_config_manager import BotConfigManager

def validate_bot_name(bot_name: str) -> bool:
    """Validate bot name (alphanumeric, underscore, dash only)"""
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', bot_name))

def get_input(prompt: str, required: bool = True, validator=None) -> str:
    """Get user input with validation"""
    while True:
        value = input(prompt).strip()
        if not value and required:
            print("❌ این فیلد الزامی است!")
            continue
        if validator and not validator(value):
            print(f"❌ مقدار وارد شده معتبر نیست!")
            continue
        return value

def get_int_input(prompt: str, required: bool = True) -> int:
    """Get integer input"""
    while True:
        value = input(prompt).strip()
        if not value and required:
            print("❌ این فیلد الزامی است!")
            continue
        try:
            return int(value)
        except ValueError:
            print("❌ لطفاً یک عدد وارد کنید!")

def setup_new_bot():
    """Interactive setup for a new bot"""
    print("=" * 60)
    print("🤖 راه‌اندازی ربات جدید")
    print("=" * 60)
    print()
    
    config_manager = BotConfigManager()
    
    # Get bot name
    while True:
        bot_name = get_input("📝 نام ربات (فقط حروف انگلیسی، اعداد، خط تیره و آندرلاین): ", 
                            validator=validate_bot_name)
        
        if bot_name in config_manager.get_all_bots():
            print(f"❌ ربات با نام '{bot_name}' از قبل وجود دارد!")
            continue
        break
    
    print()
    print("📋 لطفاً اطلاعات زیر را وارد کنید:")
    print()
    
    # Get bot configuration
    config = {}
    
    config['token'] = get_input("🔑 توکن ربات: ")
    config['admin_id'] = get_int_input("👤 شناسه عددی ادمین: ")
    config['bot_username'] = get_input("📱 یوزرنیم ربات (بدون @): ")
    config['reports_channel_id'] = get_int_input("📢 شناسه عددی کانال گزارشات: ")
    config['channel_id'] = get_input("🔗 یوزرنیم کانال اصلی (بدون @): ")
    config['channel_link'] = get_input("🔗 لینک کانال اصلی: ")
    config['starsefar_license'] = get_input("⭐ لایسنس StarsOffer: ")
    
    # Database name
    default_db_name = f"vpn_bot_{bot_name.lower()}"
    db_name = get_input(f"💾 نام دیتابیس (پیش‌فرض: {default_db_name}): ", required=False)
    if not db_name:
        db_name = default_db_name
    config['database_name'] = db_name
    
    # Webapp port (optional)
    print()
    port_input = get_input("🌐 پورت وب‌اپ (خالی بگذارید برای تخصیص خودکار): ", required=False)
    if port_input:
        try:
            config['webapp_port'] = int(port_input)
        except ValueError:
            print("⚠️ پورت نامعتبر، از پورت خودکار استفاده می‌شود")
    
    # Webapp URL (optional)
    webapp_url = get_input("🌐 آدرس وب‌اپ (خالی بگذارید برای استفاده از localhost): ", required=False)
    if webapp_url:
        config['webapp_url'] = webapp_url
    
    print()
    print("=" * 60)
    print("📋 خلاصه اطلاعات:")
    print("=" * 60)
    print(f"نام ربات: {bot_name}")
    print(f"یوزرنیم ربات: @{config['bot_username']}")
    print(f"شناسه ادمین: {config['admin_id']}")
    print(f"شناسه کانال گزارشات: {config['reports_channel_id']}")
    print(f"کانال اصلی: {config['channel_id']}")
    print(f"نام دیتابیس: {config['database_name']}")
    print(f"پورت وب‌اپ: {config.get('webapp_port', 'خودکار')}")
    print("=" * 60)
    print()
    
    confirm = input("✅ آیا اطلاعات درست است؟ (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ عملیات لغو شد.")
        return False
    
    # Register bot
    print()
    print("🔄 در حال ثبت ربات...")
    if config_manager.register_bot(bot_name, config):
        print(f"✅ ربات '{bot_name}' با موفقیت ثبت شد!")
        print()
        print("📝 مراحل بعدی:")
        print(f"   1. دیتابیس '{config['database_name']}' به صورت خودکار ایجاد می‌شود")
        print(f"   2. برای راه‌اندازی ربات از دستور زیر استفاده کنید:")
        print(f"      python run_all_bots.py")
        print()
        return True
    else:
        print("❌ خطا در ثبت ربات!")
        return False

def migrate_existing_bot():
    """Migrate existing bot (AzadJooNet) to new system"""
    print("=" * 60)
    print("🔄 انتقال ربات موجود (AzadJooNet)")
    print("=" * 60)
    print()
    
    # Check if .env exists
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ فایل .env یافت نشد!")
        return False
    
    # Read .env file
    env_vars = {}
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    
    # Get required values
    config = {}
    required_vars = {
        'BOT_TOKEN': 'token',
        'ADMIN_ID': 'admin_id',
        'BOT_USERNAME': 'bot_username',
        'REPORTS_CHANNEL_ID': 'reports_channel_id',
        'CHANNEL_ID': 'channel_id',
        'CHANNEL_LINK': 'channel_link',
        'STARSEFAR_LICENSE_KEY': 'starsefar_license',
        'MYSQL_DATABASE': 'database_name'
    }
    
    missing_vars = []
    for env_key, config_key in required_vars.items():
        if env_key in env_vars:
            value = env_vars[env_key]
            if config_key == 'admin_id' or config_key == 'reports_channel_id':
                config[config_key] = int(value)
            else:
                config[config_key] = value
        else:
            missing_vars.append(env_key)
    
    if missing_vars:
        print(f"❌ متغیرهای زیر در فایل .env یافت نشد:")
        for var in missing_vars:
            print(f"   - {var}")
        return False
    
    # Get webapp config
    webapp_url = env_vars.get('BOT_WEBAPP_URL') or env_vars.get('WEBAPP_URL', 'http://localhost:5000')
    config['webapp_url'] = webapp_url
    
    webapp_port = env_vars.get('WEBAPP_PORT', '5000')
    try:
        config['webapp_port'] = int(webapp_port)
    except:
        config['webapp_port'] = 5000
    
    bot_name = "AzadJooNet"
    
    print("📋 اطلاعات خوانده شده از .env:")
    print(f"   نام ربات: {bot_name}")
    print(f"   یوزرنیم: @{config['bot_username']}")
    print(f"   دیتابیس: {config['database_name']}")
    print()
    
    config_manager = BotConfigManager()
    
    # Check if already registered
    if bot_name in config_manager.get_all_bots():
        print(f"⚠️ ربات '{bot_name}' از قبل ثبت شده است!")
        overwrite = input("آیا می‌خواهید اطلاعات را به‌روزرسانی کنید؟ (y/n): ").strip().lower()
        if overwrite != 'y':
            print("❌ عملیات لغو شد.")
            return False
    
    # Register bot
    print()
    print("🔄 در حال ثبت ربات...")
    if config_manager.register_bot(bot_name, config):
        print(f"✅ ربات '{bot_name}' با موفقیت ثبت شد!")
        print()
        return True
    else:
        print("❌ خطا در ثبت ربات!")
        return False

if __name__ == '__main__':
    print()
    print("🤖 سیستم مدیریت چندرباتی VPN Bot")
    print()
    print("گزینه‌ها:")
    print("  1. ایجاد ربات جدید")
    print("  2. انتقال ربات موجود (AzadJooNet)")
    print()
    
    choice = input("لطفاً گزینه مورد نظر را انتخاب کنید (1 یا 2): ").strip()
    
    if choice == '1':
        setup_new_bot()
    elif choice == '2':
        migrate_existing_bot()
    else:
        print("❌ گزینه نامعتبر!")


