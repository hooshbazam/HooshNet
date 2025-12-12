"""
Caching Utilities for VPN Bot
Provides in-memory caching for frequently accessed data
For production, consider using Redis
"""

import time
import threading
from typing import Dict, Optional, Any, Callable
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class CacheEntry:
    """Cache entry with expiration"""
    def __init__(self, value: Any, ttl: int):
        self.value = value
        self.expires_at = time.time() + ttl
        self.created_at = time.time()
        self.access_count = 0
        self.last_accessed = time.time()
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired"""
        return time.time() > self.expires_at
    
    def access(self):
        """Record access"""
        self.access_count += 1
        self.last_accessed = time.time()

class SimpleCache:
    """Simple in-memory cache with TTL support"""
    
    def __init__(self, default_ttl: int = 300, max_size: int = 1000):
        """
        Initialize cache
        
        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
            max_size: Maximum number of entries (default: 1000)
        """
        self.cache: Dict[str, CacheEntry] = {}
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.lock = threading.RLock()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0,
            'evictions': 0
        }
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self.lock:
            if key not in self.cache:
                self.stats['misses'] += 1
                return None
            
            entry = self.cache[key]
            
            if entry.is_expired():
                del self.cache[key]
                self.stats['misses'] += 1
                return None
            
            entry.access()
            self.stats['hits'] += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache"""
        with self.lock:
            # Check if we need to evict
            if len(self.cache) >= self.max_size and key not in self.cache:
                self._evict_lru()
            
            ttl = ttl or self.default_ttl
            self.cache[key] = CacheEntry(value, ttl)
            self.stats['sets'] += 1
            return True
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.stats['deletes'] += 1
                return True
            return False
    
    def clear(self):
        """Clear all cache"""
        with self.lock:
            self.cache.clear()
            self.stats = {
                'hits': 0,
                'misses': 0,
                'sets': 0,
                'deletes': 0,
                'evictions': 0
            }
    
    def cleanup_expired(self):
        """Remove expired entries"""
        with self.lock:
            expired_keys = [
                key for key, entry in self.cache.items()
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self.cache[key]
            return len(expired_keys)
    
    def _evict_lru(self):
        """Evict least recently used entry"""
        if not self.cache:
            return
        
        lru_key = min(
            self.cache.keys(),
            key=lambda k: self.cache[k].last_accessed
        )
        del self.cache[lru_key]
        self.stats['evictions'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                **self.stats,
                'size': len(self.cache),
                'max_size': self.max_size,
                'hit_rate': round(hit_rate, 2)
            }
    
    def get_or_set(self, key: str, func: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        """
        Get value from cache, or compute and set if not exists
        
        Args:
            key: Cache key
            func: Function to compute value if not in cache
            ttl: Time-to-live in seconds
        
        Returns:
            Cached or computed value
        """
        value = self.get(key)
        if value is not None:
            return value
        
        value = func()
        self.set(key, value, ttl)
        return value

# Global cache instance
cache = SimpleCache(default_ttl=300, max_size=1000)

# Cache key prefixes
CACHE_PREFIX_USER = "user:"
CACHE_PREFIX_PANEL = "panel:"
CACHE_PREFIX_PRODUCT = "product:"
CACHE_PREFIX_SERVICE = "service:"
CACHE_PREFIX_STATS = "stats:"

def _get_bot_prefix() -> str:
    """Get bot prefix for cache keys (for multi-bot isolation)"""
    try:
        from flask import g, current_app
        # Try Flask g first
        if hasattr(g, 'bot_name') and g.bot_name:
            return f"bot:{g.bot_name}:"
        # Try app config
        if hasattr(current_app, 'config') and 'BOT_NAME' in current_app.config:
            bot_name = current_app.config.get('BOT_NAME')
            if bot_name:
                return f"bot:{bot_name}:"
        # Try database name from config
        if hasattr(current_app, 'config') and 'BOT_CONFIG' in current_app.config:
            db_name = current_app.config.get('BOT_CONFIG', {}).get('database_name')
            if db_name:
                return f"db:{db_name}:"
    except:
        pass
    # No bot prefix in single-bot mode
    return ""

def cache_key_user(user_id: int) -> str:
    """Generate cache key for user"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}{CACHE_PREFIX_USER}{user_id}"

def cache_key_panel(panel_id: int) -> str:
    """Generate cache key for panel"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}{CACHE_PREFIX_PANEL}{panel_id}"

def cache_key_product(product_id: int) -> str:
    """Generate cache key for product"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}{CACHE_PREFIX_PRODUCT}{product_id}"

def cache_key_user_services(user_id: int) -> str:
    """Generate cache key for user services"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}{CACHE_PREFIX_SERVICE}user:{user_id}"

def cache_key_stats(user_id: int) -> str:
    """Generate cache key for user stats"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}{CACHE_PREFIX_STATS}user:{user_id}"

def cache_key_panels_active() -> str:
    """Generate cache key for active panels list"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}panels:active"

def cache_key_products_panel(panel_id: int) -> str:
    """Generate cache key for products of a panel"""
    bot_prefix = _get_bot_prefix()
    return f"{bot_prefix}products:panel:{panel_id}"

def invalidate_user_cache(user_id: int):
    """Invalidate all cache entries for a user"""
    bot_prefix = _get_bot_prefix()
    cache.delete(cache_key_user(user_id))
    cache.delete(cache_key_user_services(user_id))
    cache.delete(cache_key_stats(user_id))

def invalidate_panel_cache(panel_id: int):
    """Invalidate all cache entries for a panel"""
    cache.delete(cache_key_panel(panel_id))
    # Also invalidate related products
    # Note: This is a simple implementation, for production use Redis with pattern matching

def invalidate_product_cache(product_id: int):
    """Invalidate cache entry for a product"""
    cache.delete(cache_key_product(product_id))

# Background cleanup thread
def cleanup_cache_periodically():
    """Periodically clean up expired cache entries"""
    import time
    while True:
        try:
            time.sleep(60)  # Clean every minute
            cleaned = cache.cleanup_expired()
            if cleaned > 0:
                logger.debug(f"Cleaned {cleaned} expired cache entries")
        except Exception as e:
            logger.error(f"Error in cache cleanup: {e}")

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_cache_periodically, daemon=True)
cleanup_thread.start()

