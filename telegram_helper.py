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
    
    _bot_cache = {}
    
    @classmethod
    def _resolve_token(cls, token=None):
        if token:
            return token
        try:
            from flask import current_app
            if hasattr(current_app, 'config') and 'BOT_CONFIG' in current_app.config:
                bot_config = current_app.config.get('BOT_CONFIG') or {}
                if bot_config.get('token'):
                    return bot_config.get('token')
        except Exception:
            pass
        return BOT_CONFIG.get('token')
    
    @classmethod
    def get_bot(cls, new_instance=False, token=None):
        """
        Get or create Bot instance
        
        Args:
            new_instance: If True, always creates a new instance (useful for new event loops)
        """
        resolved_token = cls._resolve_token(token)
        if new_instance:
            from telegram.request import HTTPXRequest
            request = HTTPXRequest(connection_pool_size=8, read_timeout=20.0, write_timeout=20.0, connect_timeout=20.0)
            return Bot(token=resolved_token, request=request)
        
        if resolved_token not in cls._bot_cache:
            from telegram.request import HTTPXRequest
            request = HTTPXRequest(connection_pool_size=8, read_timeout=20.0, write_timeout=20.0, connect_timeout=20.0)
            cls._bot_cache[resolved_token] = Bot(token=resolved_token, request=request)
        
        return cls._bot_cache[resolved_token]
    
    @classmethod
    async def get_user_profile_photo_url(cls, user_id: int, bot=None) -> str:
        """
        Get user's profile photo URL
        
        Args:
            user_id: Telegram user ID
            bot: Optional Bot instance
            
        Returns:
            Photo URL or empty string if not available
        """
        try:
            if bot is None:
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
                        token = getattr(bot, 'token', None) or cls._resolve_token()
                        photo_url = f"https://api.telegram.org/file/bot{token}/{file.file_path}"
                    
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
            # Always create a new event loop to avoid interference
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create a FRESH bot instance for this loop
            bot = cls.get_bot(new_instance=True)
            
            # Run the async function
            result = loop.run_until_complete(cls.get_user_profile_photo_url(user_id, bot=bot))
            loop.close()
            return result
                
        except Exception as e:
            logger.error(f"Error in sync wrapper for user {user_id}: {e}")
            return ''
    
    @classmethod
    async def send_message(cls, chat_id: int, text: str, bot=None) -> bool:
        """
        Send a message to a user
        
        Args:
            chat_id: Telegram chat ID
            text: Message text
            bot: Optional Bot instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if bot is None:
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
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            
            if running_loop and running_loop.is_running():
                bot = cls.get_bot(new_instance=True)
                running_loop.create_task(cls.send_message(chat_id, text, bot=bot))
                return True
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            bot = cls.get_bot(new_instance=True)
            
            result = loop.run_until_complete(cls.send_message(chat_id, text, bot=bot))
            loop.close()
            return result
                
        except Exception as e:
            logger.error(f"Error in sync wrapper for sending message to {chat_id}: {e}")
            return False
            
    @classmethod
    async def send_broadcast(cls, user_ids: list, text: str, bot=None) -> tuple:
        """
        Send broadcast message to multiple users
        
        Args:
            user_ids: List of Telegram chat IDs
            text: Message text
            bot: Optional Bot instance
            
        Returns:
            Tuple (success_count, failed_count)
        """
        success_count = 0
        failed_count = 0
        
        try:
            if bot is None:
                bot = cls.get_bot()
            
            # Use semaphore to limit concurrency
            sem = asyncio.Semaphore(20)  # 20 concurrent requests
            
            async def send_one(chat_id):
                nonlocal success_count, failed_count
                async with sem:
                    try:
                        await bot.send_message(chat_id=chat_id, text=text)
                        return True
                    except Exception as e:
                        logger.error(f"Error broadcasting to {chat_id}: {e}")
                        return False
            
            # Create tasks
            tasks = [send_one(chat_id) for chat_id in user_ids]
            
            # Run all tasks
            results = await asyncio.gather(*tasks)
            
            success_count = results.count(True)
            failed_count = results.count(False)
                    
            return success_count, failed_count
        except Exception as e:
            logger.error(f"Error in broadcast loop: {e}")
            return success_count, failed_count
    
    @classmethod
    async def send_broadcast_forward(cls, user_ids: list, from_chat_id: int, message_id: int, as_copy: bool = False, bot=None) -> tuple:
        """
        Forward or copy a message to multiple users
        
        Args:
            user_ids: List of Telegram chat IDs
            from_chat_id: Source chat ID
            message_id: Source message ID
            as_copy: If True, copy message instead of forwarding
            bot: Optional Bot instance
            
        Returns:
            Tuple (success_count, failed_count)
        """
        success_count = 0
        failed_count = 0
        
        try:
            if bot is None:
                bot = cls.get_bot()
            
            sem = asyncio.Semaphore(20)
            
            async def send_one(chat_id):
                nonlocal success_count, failed_count
                async with sem:
                    try:
                        if as_copy:
                            await bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
                        else:
                            await bot.forward_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
                        return True
                    except Exception as e:
                        logger.error(f"Error broadcasting to {chat_id}: {e}")
                        return False
            
            tasks = [send_one(chat_id) for chat_id in user_ids]
            results = await asyncio.gather(*tasks)
            
            success_count = results.count(True)
            failed_count = results.count(False)
            
            return success_count, failed_count
        except Exception as e:
            logger.error(f"Error in broadcast forward loop: {e}")
            return success_count, failed_count

    @classmethod
    def send_broadcast_sync(cls, user_ids: list, text: str) -> tuple:
        """
        Synchronous wrapper for send_broadcast
        
        Args:
            user_ids: List of Telegram chat IDs
            text: Message text
            
        Returns:
            Tuple (success_count, failed_count)
        """
        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            
            if running_loop and running_loop.is_running():
                bot = cls.get_bot(new_instance=True)
                running_loop.create_task(cls.send_broadcast(user_ids, text, bot=bot))
                return 0, 0
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            bot = cls.get_bot(new_instance=True)
            
            result = loop.run_until_complete(cls.send_broadcast(user_ids, text, bot=bot))
            loop.close()
            return result
                
        except Exception as e:
            logger.error(f"Error in sync wrapper for broadcast: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0, len(user_ids)
    
    @classmethod
    def send_broadcast_forward_sync(cls, user_ids: list, from_chat_id: int, message_id: int, as_copy: bool = False) -> tuple:
        """
        Synchronous wrapper for send_broadcast_forward
        """
        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            
            if running_loop and running_loop.is_running():
                bot = cls.get_bot(new_instance=True)
                running_loop.create_task(cls.send_broadcast_forward(user_ids, from_chat_id, message_id, as_copy=as_copy, bot=bot))
                return 0, 0
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            bot = cls.get_bot(new_instance=True)
            
            result = loop.run_until_complete(cls.send_broadcast_forward(user_ids, from_chat_id, message_id, as_copy=as_copy, bot=bot))
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Error in sync wrapper for broadcast forward: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0, len(user_ids)
    
    @classmethod
    async def create_forum_topic(cls, chat_id: int, name: str) -> int:
        """
        Create a forum topic in a supergroup
        
        Args:
            chat_id: Telegram chat ID (must be a supergroup)
            name: Topic name
            
        Returns:
            Topic ID (message_thread_id) or 0 if failed
        """
        try:
            bot = cls.get_bot()
            topic = await bot.create_forum_topic(chat_id=chat_id, name=name)
            logger.info(f"✅ Created forum topic '{name}' (ID: {topic.message_thread_id}) in chat {chat_id}")
            return topic.message_thread_id
        except Exception as e:
            logger.error(f"❌ Error creating forum topic '{name}' in chat {chat_id}: {e}")
            return 0

