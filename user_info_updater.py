"""
User Information Auto-Update System
Automatically updates user information from Telegram on every interaction
"""

import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from typing import Callable

logger = logging.getLogger(__name__)


def get_fresh_user_info(update: Update) -> dict:
    """
    Extract fresh user information from Telegram update object
    
    Returns:
        dict: User information including telegram_id, username, first_name, last_name
    """
    try:
        user = update.effective_user
        if not user:
            return None
        
        return {
            'telegram_id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }
    except Exception as e:
        logger.error(f"Error extracting user info: {e}")
        return None


def auto_update_user_info(func: Callable) -> Callable:
    """
    Decorator that automatically updates user information before executing handler
    
    Usage:
        @auto_update_user_info
        async def my_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            # Your handler code here
            pass
    """
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            # Get fresh user info from Telegram
            user_info = get_fresh_user_info(update)
            
            if user_info and hasattr(self, 'db'):
                # Update user info in database
                self.db.update_user_info(
                    telegram_id=user_info['telegram_id'],
                    username=user_info['username'],
                    first_name=user_info['first_name'],
                    last_name=user_info['last_name']
                )
                logger.debug(f"Updated user info for {user_info['telegram_id']}")
        except Exception as e:
            # Don't fail the handler if update fails, just log it
            logger.error(f"Error in auto_update_user_info: {e}")
        
        # Execute the original handler
        return await func(self, update, context, *args, **kwargs)
    
    return wrapper


class UserInfoSync:
    """
    Helper class for syncing user information
    """
    
    def __init__(self, db_manager):
        """
        Initialize with database manager
        
        Args:
            db_manager: ProfessionalDatabaseManager instance
        """
        self.db = db_manager
    
    def sync_user_from_update(self, update: Update) -> bool:
        """
        Synchronize user information from Telegram update to database
        
        Args:
            update: Telegram Update object
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            user_info = get_fresh_user_info(update)
            
            if not user_info:
                return False
            
            return self.db.update_user_info(
                telegram_id=user_info['telegram_id'],
                username=user_info['username'],
                first_name=user_info['first_name'],
                last_name=user_info['last_name']
            )
        except Exception as e:
            logger.error(f"Error syncing user info: {e}")
            return False
    
    def get_updated_user(self, update: Update) -> dict:
        """
        Get user info from database after syncing with Telegram
        
        Args:
            update: Telegram Update object
            
        Returns:
            dict: User information from database (updated)
        """
        try:
            # First sync
            self.sync_user_from_update(update)
            
            # Then get from database
            user = update.effective_user
            if user:
                return self.db.get_user(user.id)
            
            return None
        except Exception as e:
            logger.error(f"Error getting updated user: {e}")
            return None


def ensure_user_updated(db_manager, update: Update) -> dict:
    """
    Standalone function to ensure user info is updated and return it
    
    Args:
        db_manager: ProfessionalDatabaseManager instance
        update: Telegram Update object
        
    Returns:
        dict: Updated user information from database
    """
    try:
        user_info = get_fresh_user_info(update)
        
        if not user_info:
            return None
        
        # Update in database
        db_manager.update_user_info(
            telegram_id=user_info['telegram_id'],
            username=user_info['username'],
            first_name=user_info['first_name'],
            last_name=user_info['last_name']
        )
        
        # Return updated info from database
        return db_manager.get_user(user_info['telegram_id'])
    except Exception as e:
        logger.error(f"Error ensuring user updated: {e}")
        return None


