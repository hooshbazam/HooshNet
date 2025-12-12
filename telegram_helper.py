"""
Helper functions for Telegram Bot API
Used by webapp to get user profile photos
"""

import logging
import asyncio
from telegram import Bot
from config import BOT_CONFIG

logger = logging.getLogger(__name__)


class TelegramHelper:
    """Helper class for Telegram Bot API operations"""
    
    _bot = None
    
    @classmethod
    def get_bot(cls):
        """Get or create Bot instance"""
        if cls._bot is None:
            from telegram.request import HTTPXRequest
            request = HTTPXRequest(connection_pool_size=8, read_timeout=20.0, write_timeout=20.0, connect_timeout=20.0)
            # Hack to force trust_env=False for httpx
            # Since HTTPXRequest doesn't expose trust_env directly in constructor in some versions,
            # we might need to rely on the fact that we are not passing proxy_url.
            # But wait, python-telegram-bot's HTTPXRequest might pick up env vars.
            # Let's try to pass an empty proxy dictionary if possible, or use a custom request class if defined in telegram_bot.py
            
            # Better approach: Import NoProxyRequest from telegram_bot if available, or define a local one
            try:
                from telegram_bot import NoProxyRequest
                request = NoProxyRequest()
            except ImportError:
                # Fallback if cannot import
                request = HTTPXRequest()
            
            cls._bot = Bot(token=BOT_CONFIG['token'], request=request)
        return cls._bot
    
    @classmethod
    async def get_user_profile_photo_url(cls, user_id: int) -> str:
        """
        Get user's profile photo URL
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Photo URL or empty string if not available
        """
        try:
            bot = cls.get_bot()
            
            # Get user profile photos
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            
            if photos.total_count > 0 and len(photos.photos) > 0:
                # Get the first (largest) size of the first photo
                photo = photos.photos[0][0]
                
                # Get file info
                file = await bot.get_file(photo.file_id)
                
                # Build complete URL for the photo
                if file.file_path:
                    # Check if file_path is already a complete URL
                    if file.file_path.startswith('http://') or file.file_path.startswith('https://'):
                        photo_url = file.file_path
                    else:
                        # file.file_path is relative, make it absolute
                        photo_url = f"https://api.telegram.org/file/bot{BOT_CONFIG['token']}/{file.file_path}"
                    
                    logger.info(f"Profile photo URL for user {user_id}: {photo_url}")
                    return photo_url
            
            return ''
            
        except Exception as e:
            logger.error(f"Error getting profile photo for user {user_id}: {e}")
            return ''
    
    @classmethod
    def get_user_profile_photo_url_sync(cls, user_id: int) -> str:
        """
        Synchronous wrapper for get_user_profile_photo_url
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Photo URL or empty string if not available
        """
        try:
            # Try to get existing event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                # Create a new event loop if none exists or is closed
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the async function
            result = loop.run_until_complete(cls.get_user_profile_photo_url(user_id))
            return result
                
        except Exception as e:
            logger.error(f"Error in sync wrapper for user {user_id}: {e}")
            return ''
    
    @classmethod
    async def send_message(cls, chat_id: int, text: str) -> bool:
        """
        Send a message to a user
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            
        Returns:
            True if successful, False otherwise
        """
        try:
            bot = cls.get_bot()
            await bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            logger.error(f"Error sending message to user {chat_id}: {e}")
            return False
    
    @classmethod
    def send_message_sync(cls, chat_id: int, text: str) -> bool:
        """
        Synchronous wrapper for send_message
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Try to get existing event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                # Create a new event loop if none exists or is closed
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the async function
            result = loop.run_until_complete(cls.send_message(chat_id, text))
            return result
                
        except Exception as e:
            logger.error(f"Error in sync wrapper for sending message to {chat_id}: {e}")
            return False

