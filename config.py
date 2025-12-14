"""
Configuration file for 3x-ui VPN Bot
Contains all bot settings and panel configurations
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
# SECURITY: All sensitive values must be in .env file
BOT_CONFIG = {
    'token': os.getenv('BOT_TOKEN'),  # REQUIRED: Set in .env
    'admin_id': int(os.getenv('ADMIN_ID', '0')),  # REQUIRED: Set in .env
    'bot_username': os.getenv('BOT_USERNAME', ''),
    'reports_channel_id': int(os.getenv('REPORTS_CHANNEL_ID', '0')),  # Channel for reports
    'receipts_channel_id': int(os.getenv('RECEIPTS_CHANNEL_ID', '0')),  # Channel for payment receipts
    'channel_id': os.getenv('CHANNEL_ID', '@YourChannel'),  # Channel username for forced join
    'channel_link': os.getenv('CHANNEL_LINK', 'https://t.me/YourChannel')  # Channel link
}

# Validate required config
if not BOT_CONFIG['token']:
    raise ValueError("BOT_TOKEN must be set in .env file")
if BOT_CONFIG['admin_id'] == 0:
    raise ValueError("ADMIN_ID must be set in .env file")

# Default 3x-ui Panel Configuration (for backward compatibility)
# SECURITY: These should be set per panel in database, not hardcoded here
DEFAULT_PANEL_CONFIG = {
    'url': os.getenv('DEFAULT_PANEL_URL', ''),
    'username': os.getenv('DEFAULT_PANEL_USERNAME', ''),
    'password': os.getenv('DEFAULT_PANEL_PASSWORD', ''),
    'api_endpoint': os.getenv('DEFAULT_PANEL_API_ENDPOINT', '')
}

# Payment Gateway Configuration
# Placeholder for future payment gateway
PAYMENT_CONFIG = {}

# Client Configuration Defaults
CLIENT_DEFAULTS = {
    'expire_time': 0,  # 0 = unlimited
    'total_traffic': 0,  # 0 = unlimited
    'enable': True,
    'protocols': ['vmess', 'vless', 'trojan', 'shadowsocks']
}

# Logging Configuration
LOGGING = {
    'level': 'INFO',
    'file': 'bot.log',
    'max_size': 10 * 1024 * 1024,  # 10MB
    'backup_count': 5
}

# Referral System Configuration
REFERRAL_CONFIG = {
    'enabled': True,
    'reward_amount': 3000,  # تومان - پاداش برای دعوت کننده
    'welcome_bonus': 1000,  # تومان - هدیه ثبت نام
    'min_withdrawal': 5000,  # حداقل برداشت
}

# Bot Messages Configuration
BOT_MESSAGES = {
    'welcome_bonus_notification': '🎁 تبریک! {amount:,} تومان به حساب شما اضافه شد.',
    'referral_reward_notification': '🎉 کاربر جدیدی از طریق لینک شما ثبت نام کرد!\n💰 {amount:,} تومان پاداش دریافت کردید.',
}

# Web Application Configuration
WEBAPP_CONFIG = {
    'enabled': True,
    'url': os.getenv('BOT_WEBAPP_URL', os.getenv('WEBAPP_URL', 'https://your-domain.com')),  # Can be ngrok or domain
    'port': 5000,
    'debug': False,  # Set to False in production - prevents memory leaks
}

# MySQL Database Configuration
# SECURITY: All database credentials must be in .env file
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD'),  # REQUIRED: Set in .env
    'database': os.getenv('MYSQL_DATABASE', 'vpn_bot'),
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'autocommit': False,
    'pool_size': 5,  # Reduced to prevent "too many connections" error
    'pool_reset_session': True,
    'buffered': True
}

# Validate required database config
if not MYSQL_CONFIG['password']:
    raise ValueError("MYSQL_PASSWORD must be set in .env file")