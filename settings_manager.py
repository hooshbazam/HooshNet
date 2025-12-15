import logging
import json
from typing import Any, Dict, Optional
from professional_database import ProfessionalDatabaseManager
from config import BOT_CONFIG, REFERRAL_CONFIG, WEBAPP_CONFIG

logger = logging.getLogger(__name__)

class SettingsManager:
    """
    Manager for dynamic bot settings.
    Prioritizes database settings over config.py.
    Implements caching to reduce database hits.
    """
    
    _instance = None
    _cache = {}
    
    def __new__(cls, db_manager=None):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance.db = db_manager if db_manager else ProfessionalDatabaseManager()
            cls._instance._load_cache()
        return cls._instance

    def __init__(self, db_manager=None):
        pass
    
    def _load_cache(self):
        """Load all settings from database into cache"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT setting_key, setting_value, setting_type FROM settings")
                rows = cursor.fetchall()
                
                for row in rows:
                    key = row['setting_key']
                    value = row['setting_value']
                    value_type = row['setting_type']
                    
                    # Type conversion
                    if value_type == 'int':
                        self._cache[key] = int(value)
                    elif value_type == 'float':
                        self._cache[key] = float(value)
                    elif value_type == 'bool':
                        self._cache[key] = value.lower() in ('true', '1', 'yes', 'on')
                    elif value_type == 'json':
                        self._cache[key] = json.loads(value)
                    else:
                        self._cache[key] = value
                        
            logger.info(f"✅ Loaded {len(self._cache)} settings into cache")
        except Exception as e:
            logger.error(f"Error loading settings cache: {e}")

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get setting value.
        Priority:
        1. Cache (Database)
        2. config.py (if applicable mapping exists)
        3. Default value provided
        """
        # 1. Check Cache
        if key in self._cache:
            return self._cache[key]
        
        # 2. Check config.py mappings (Fallback)
        config_value = self._get_config_fallback(key)
        if config_value is not None:
            return config_value
            
        # 3. Return default
        return default

    def set_setting(self, key: str, value: Any, description: str = None, user_id: int = None, updated_by: int = None) -> bool:
        """Update setting in database and cache"""
        # Handle updated_by alias
        if user_id is None and updated_by is not None:
            user_id = updated_by
            
        # Resolve Telegram ID to Internal User ID if needed
        # Telegram IDs are usually large (> 32-bit int max value 2147483647)
        if user_id and isinstance(user_id, int) and user_id > 2147483647:
            try:
                user = self.db.get_user(user_id)
                if user:
                    user_id = user['id']
                else:
                    logger.warning(f"Could not resolve Telegram ID {user_id} to internal ID for setting {key}")
                    user_id = None
            except Exception as e:
                logger.error(f"Error resolving user ID: {e}")
                user_id = None
            
        success = self.db.set_setting(key, value, description, user_id)
        if success:
            self._cache[key] = value
            logger.info(f"Updated setting '{key}' to '{value}'")
        return success

    def _get_config_fallback(self, key: str) -> Any:
        """Map setting keys to config.py values for backward compatibility"""
        # Channel Configs
        if key == 'channel_id':
            return BOT_CONFIG.get('channel_id')
        elif key == 'channel_link':
            return BOT_CONFIG.get('channel_link')
        elif key == 'reports_channel_id':
            return BOT_CONFIG.get('reports_channel_id')
        elif key == 'receipts_channel_id':
            return BOT_CONFIG.get('receipts_channel_id')
            
        # Referral Configs
        elif key == 'referral_reward_amount':
            return REFERRAL_CONFIG.get('reward_amount')
        elif key == 'welcome_bonus_amount':
            return REFERRAL_CONFIG.get('welcome_bonus')
            
        # WebApp Configs
        elif key == 'webapp_url':
            return WEBAPP_CONFIG.get('url')
            
        return None

    # Helper properties for common settings
    @property
    def main_channel_id(self):
        return self.get_setting('channel_id')

    @property
    def main_channel_link(self):
        return self.get_setting('channel_link')

    @property
    def reports_channel_id(self):
        return self.get_setting('reports_channel_id')

    @property
    def receipts_channel_id(self):
        return self.get_setting('receipts_channel_id')

    @property
    def referral_reward(self):
        return self.get_setting('referral_reward_amount', 3000)

    @property
    def welcome_bonus(self):
        return self.get_setting('welcome_bonus_amount', 1000)

    @property
    def webapp_url(self):
        return self.get_setting('webapp_url')
