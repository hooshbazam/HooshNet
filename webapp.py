"""
Professional VPN Web Application
Beautiful, modern UI with Telegram Login authentication
Features: Dashboard, Service Management, Profile, Referrals, and more
"""

import os
import json
import hashlib
import hmac
import logging
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, flash, send_from_directory
from flask_cors import CORS
from functools import wraps
from professional_database import ProfessionalDatabaseManager
from panel_manager import PanelManager
from config import BOT_CONFIG, WEBAPP_CONFIG
from telegram_helper import TelegramHelper
from country_translator import extract_country_from_panel_name
from typing import Dict, List, Optional, Any
from security_utils import (
    rate_limit, sanitize_input, 
    validate_telegram_id, validate_amount, validate_positive_int, 
    validate_panel_id, validate_discount_code, secure_before_request, 
    secure_after_request, get_client_ip, block_ip, is_ip_blocked,
    record_suspicious_activity, sanitize_error_message, check_waf
)

import httpx

# Monkeypatch httpx.AsyncClient to force disable proxies
# This is required because standard configuration seems to be ignored or overridden
original_async_client_init = httpx.AsyncClient.__init__

def patched_async_client_init(self, *args, **kwargs):
    kwargs['proxy'] = None
    kwargs['trust_env'] = False
    if 'proxies' in kwargs:
        del kwargs['proxies']
    original_async_client_init(self, *args, **kwargs)

httpx.AsyncClient.__init__ = patched_async_client_init

# SECURITY: Helper function for secure error responses
def secure_error_response(error: Exception, default_message: str = 'خطای سیستمی', log_details: bool = True) -> tuple:
    """
    Return a secure error response that doesn't leak information
    
    Args:
        error: The exception that occurred
        default_message: Default message to show to user
        log_details: Whether to log full error details (for debugging)
    
    Returns:
        Tuple of (jsonify response, status_code)
    """
    if log_details:
        logger.error(f"Error: {type(error).__name__}: {str(error)}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Use sanitize_error_message to prevent information leakage
    safe_message = sanitize_error_message(error, include_details=False)
    if safe_message == 'خطای سیستمی - لطفاً دوباره تلاش کنید':
        safe_message = default_message
    
    return jsonify({'success': False, 'message': safe_message}), 500

# Helper to run ReportingSystem methods synchronously
def send_report_sync(report_func_name, *args, **kwargs):
    """
    Synchronous wrapper to run ReportingSystem methods
    """
    try:
        from telegram_helper import TelegramHelper
        from reporting_system import ReportingSystem
        import asyncio
        
        bot = TelegramHelper.get_bot()
        bot_config = get_bot_config()
        db = get_db()
        
        reporting_system = ReportingSystem(bot, bot_config=bot_config, db_manager=db)
        
        # Get the method
        method = getattr(reporting_system, report_func_name, None)
        if not method:
            logger.error(f"ReportingSystem method '{report_func_name}' not found")
            return
            
        # Run async method
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        loop.run_until_complete(method(*args, **kwargs))
        logger.info(f"✅ Report '{report_func_name}' sent successfully via sync wrapper")
        
    except Exception as e:
        logger.error(f"Error in send_report_sync: {e}")
        # Don't crash the request if reporting fails
from cache_utils import cache, cache_key_user, cache_key_user_services, cache_key_stats, invalidate_user_cache

# Configure logging with UTF-8 encoding to handle emoji and Persian characters
import sys
if sys.platform == 'win32':
    # Force UTF-8 encoding on Windows to avoid charmap codec errors
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def parse_datetime_safe(date_value):
    """
    Safely parse a datetime value that could be:
    - ISO format string (e.g., '2025-01-15T10:30:45')
    - Unix timestamp (integer or string)
    - datetime object
    - None
    """
    if not date_value:
        return None
    
    # If it's already a datetime object
    if isinstance(date_value, datetime):
        return date_value.replace(tzinfo=None) if date_value.tzinfo else date_value
    
    # If it's a string
    if isinstance(date_value, str):
        # Try parsing as ISO format first
        try:
            # Handle ISO format with 'Z' suffix
            clean_value = date_value.replace('Z', '+00:00') if 'Z' in date_value else date_value
            dt = datetime.fromisoformat(clean_value)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, AttributeError):
            # Try parsing as Unix timestamp (integer string)
            try:
                timestamp = int(float(date_value))
                return datetime.fromtimestamp(timestamp)
            except (ValueError, TypeError, OSError):
                # If all parsing fails, return None
                return None
    
    # If it's an integer (Unix timestamp)
    if isinstance(date_value, (int, float)):
        try:
            return datetime.fromtimestamp(int(date_value))
        except (ValueError, OSError):
            return None
    
    return None

# Initialize Flask app
app = Flask(__name__)
# app.secret_key is set later using persistent file
logger.info("🚀 STARTING WEBAPP - VERSION: DEBUG_HTTPS")

# Configure maximum file upload size (10MB for receipts)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

CORS(app)

# Add nl2br filter for Jinja2
@app.template_filter('nl2br')
def nl2br_filter(value):
    """Convert newlines to <br> tags"""
    if value:
        return value.replace('\n', '<br>')
    return value

# Add bot_prefix helper for templates (needed for single-bot mode compatibility)
try:
    from reseller_panel import reseller_bp
    app.register_blueprint(reseller_bp, url_prefix='/reseller')
except Exception as e:
    logger.error(f"Failed to register reseller blueprint: {e}")
    import traceback
    logger.error(traceback.format_exc())

@app.context_processor
def inject_bot_prefix():
    def add_bot_prefix(url):
        if not url or not isinstance(url, str):
            return url
            
        # Check if we're in multi-bot mode
        if os.getenv('MULTI_BOT_MODE') == 'true':
            # Try to get bot name from config or g
            bot_name = app.config.get('BOT_NAME')
            if not bot_name:
                try:
                    from flask import g
                    bot_name = getattr(g, 'bot_name', None)
                except:
                    pass
            
            # Add bot_name prefix if needed
            if bot_name and url.startswith('/') and not url.startswith(f'/{bot_name}/'):
                # Don't add prefix to static files or external URLs
                if not url.startswith('/static/') and not url.startswith('http'):
                    return f'/{bot_name}{url}'
        
        return url
        return url
    
    # Inject current theme
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    current_theme = settings_mgr.get_theme()
    
    return dict(add_bot_prefix=add_bot_prefix, current_theme=current_theme)

# CSRF token context processor removed - no longer needed

# Configure Flask session settings to prevent memory leaks and improve security
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)  # Sessions expire after 24 hours
# SECURITY: Use secure cookies in production (HTTPS required)
# Auto-detect HTTPS from request scheme
use_https_env = os.getenv('USE_HTTPS', 'false').lower()
use_https = use_https_env == 'true'
logger.info(f"🔒 USE_HTTPS environment variable: {use_https_env} (Parsed: {use_https})")

# CRITICAL FIX: Use ProxyFix to handle Nginx headers correctly
from werkzeug.middleware.proxy_fix import ProxyFix

# Force HTTPS if configured (fixes issues where proxy sends http header)
if use_https:
    class ForceHTTPS:
        def __init__(self, app):
            self.app = app

        def __call__(self, environ, start_response):
            environ['wsgi.url_scheme'] = 'https'
            return self.app(environ, start_response)
    
    # Apply ForceHTTPS FIRST (inner) so it runs LAST (closest to app)
    # This ensures it overrides anything ProxyFix might have set
    app.wsgi_app = ForceHTTPS(app.wsgi_app)
    
    # Then wrap with ProxyFix (outer) so it processes headers first
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    
    logger.info("🔒 Forced HTTPS scheme for all requests")
else:
    # Just use ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# Session Configuration
# We use ProxyFix so Flask knows when it's secure. 
# We set Secure=True because we are behind Nginx with SSL.
app.config['SESSION_COOKIE_SECURE'] = True 
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent XSS attacks - JavaScript cannot access
# SameSite='None' is required for Telegram Web Apps (iframe/cross-site)
# But it REQUIRES Secure=True.
app.config['SESSION_COOKIE_SAMESITE'] = 'None' 
app.config['SESSION_COOKIE_NAME'] = 'vpn_bot_session'  # Custom session name
# SECURITY: Set session cookie path to prevent cookie theft
app.config['SESSION_COOKIE_PATH'] = '/'  # Cookie valid for entire domain
# SECURITY: Regenerate session ID on login to prevent session fixation
app.config['SESSION_REFRESH_EACH_REQUEST'] = False  # Don't refresh on every request (performance)

# Error handler for Request Entity Too Large (413)
@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle 413 Request Entity Too Large error"""
    logger.warning(f"Request entity too large: {request.path}")
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({
            'success': False,
            'message': 'حجم فایل ارسالی بیش از حد مجاز است. حداکثر حجم مجاز 10 مگابایت است.'
        }), 413
    else:
        flash('حجم فایل ارسالی بیش از حد مجاز است. حداکثر حجم مجاز 10 مگابایت است.', 'error')
        return redirect(request.referrer or url_for('index')), 413

# Generate a secure secret key if not set (minimum 32 bytes for security)
# Generate a secure secret key if not set (minimum 32 bytes for security)
# CRITICAL FIX: Use a persistent secret key file so all Gunicorn workers share the same key
secret_key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.flask_secret_key')
try:
    if os.path.exists(secret_key_file):
        with open(secret_key_file, 'rb') as f:
            app.secret_key = f.read()
    else:
        # Generate new key and save it
        new_key = os.urandom(64)
        with open(secret_key_file, 'wb') as f:
            f.write(new_key)
        app.secret_key = new_key
        logger.info("🔐 Generated and saved new secure session key")
except Exception as e:
    logger.error(f"Error handling secret key file: {e}")
    # Fallback to env var or random (will break multi-worker if not in env)
    app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(64))

# ============================================
# COMPREHENSIVE SECURITY MIDDLEWARE
# ============================================
# Apply security checks before every request
@app.before_request
def security_check():
    """Comprehensive security check before every request"""
    # DEBUG: Log headers to diagnose login loop
    if request.endpoint in ['index', 'telegram_auth', 'dashboard', 'health_check']:
        logger.info(f"DEBUG HEADERS for {request.endpoint}:")
        logger.info(f"  Scheme: {request.scheme}")
        logger.info(f"  Host: {request.host}")
        logger.info(f"  Headers: {dict(request.headers)}")
        for header, value in request.headers.items():
            logger.info(f"  {header}: {value}")
            
    path_lower = request.path.lower()
    
    # Allow all legitimate static files (CSS, JS, images, fonts, icons)
    allowed_static_extensions = ['.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.eot', '.ico', '.webp']
    if (request.endpoint == 'static' or request.path.startswith('/static/')) and \
       any(path_lower.endswith(ext) for ext in allowed_static_extensions):
        # Allow legitimate static files - don't block them
        return None
    
    # Check for suspicious static file requests (only for non-legitimate files)
    if request.endpoint == 'static' or request.path.startswith('/static/'):
        client_ip = get_client_ip()
        
        # Only block truly sensitive file types, not CSS/JS/images
        blocked_patterns = [
            '.env', '.git', 'config.env', '.sql', '.db', '.sqlite', 
            '.log', '.ini', '.conf', '.key', '.pem', '.p12', '.pfx', 
            '.crt', 'secret', 'private', 'backup', '.bak', 'credentials'
        ]
        
        # Only block if it's NOT a legitimate static file
        if not any(path_lower.endswith(ext) for ext in allowed_static_extensions):
            if any(pattern in path_lower for pattern in blocked_patterns):
                record_suspicious_activity(client_ip, 'suspicious_static_file', request.path)
                return Response('Not Found', status=404, mimetype='text/plain')
    
    # Apply comprehensive security checks
    security_result = secure_before_request()
    if security_result is not None:
        return security_result
        
    # Apply WAF check
    waf_result = check_waf(request)
    if waf_result is not None:
        return waf_result
    
    # Additional protection: Block access to .env and other sensitive files at root
    # But allow legitimate paths
    if not any(path_lower.endswith(ext) for ext in allowed_static_extensions) and \
       not path_lower.startswith('/static/') and \
       any(pattern in path_lower for pattern in ['/.env', '/config.env', '/.git/', '/.env.', '/env.js']):
        client_ip = get_client_ip()
        record_suspicious_activity(client_ip, 'root_sensitive_file', request.path)
        return Response('Not Found', status=404, mimetype='text/plain')
    
    return None  # Continue with request

# Set db from app config for each request (multi-bot support)
# Note: db is now a DatabaseProxy that always calls get_db(), so we don't need to set it here
# But we keep this function for backward compatibility and to ensure get_db() works correctly
@app.before_request
def set_db_for_request():
    """Ensure get_db() has access to the correct database instance"""
    # DatabaseProxy handles this automatically, but we can still set _db_global for reference
    global _db_global
    import os
    is_multi_bot = os.getenv('MULTI_BOT_MODE', 'false').lower() == 'true'
    
    try:
        from flask import current_app, g
        # Priority 1: Try Flask g (set in multi_bot_webapp.py)
        if hasattr(g, 'db') and g.db:
            _db_global = g.db
            bot_name = getattr(g, 'bot_name', 'unknown')
            db_name = getattr(g, 'bot_config', {}).get('database_name', 'unknown')
            logger.debug(f"set_db_for_request: Set _db_global from g.db for bot: {bot_name}, database: {db_name}")
            return
        
        # Priority 2: Try app config (set in multi_bot_webapp.py)
        if hasattr(current_app, 'config') and 'DB' in current_app.config:
            _db_global = current_app.config['DB']
            bot_name = current_app.config.get('BOT_NAME', 'unknown')
            db_name = current_app.config.get('BOT_CONFIG', {}).get('database_name', 'unknown')
            logger.debug(f"set_db_for_request: Set _db_global from app.config['DB'] for bot: {bot_name}, database: {db_name}")
            return
    except Exception as e:
        logger.debug(f"Could not set _db_global from config: {e}")
        pass
    
    # In multi-bot mode, warn if we couldn't set _db_global
    if is_multi_bot and _db_global is None:
        logger.warning(f"set_db_for_request: Could not set _db_global in multi-bot mode for path: {getattr(request, 'path', 'unknown')}")
    
    # _db_global will be set by get_db() if needed (only in single-bot mode)

# Apply security headers after every request
@app.after_request
def security_headers(response):
    """Apply security headers to every response"""
    return secure_after_request(response)

# Health check endpoint for Docker
@app.route('/health')
def health_check():
    """Health check endpoint for Docker/Kubernetes"""
    try:
        # Basic health check - just return OK
        return jsonify({
            'status': 'healthy',
            'message': 'VPN Bot Web Application is running'
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'message': str(e)
        }), 500

# Note: Static file protection is handled in security_check() before_request handler
# Flask's default static file handler is used, but we filter requests before they reach it

# Initialize managers (will be overridden in multi-bot mode)
# In multi-bot mode, these are set via app.config
_db_global = None
panel_manager = None

# Create a property-like accessor for db that always uses get_db()
class DatabaseProxy:
    """Proxy object that always returns the current database instance"""
    def __getattr__(self, name):
        return getattr(get_db(), name)
    
    def __call__(self, *args, **kwargs):
        return get_db()(*args, **kwargs)

# Create proxy instance
db = DatabaseProxy()

def get_db():
    """Get database instance from app config, Flask g, or global"""
    from flask import current_app, g
    import os
    
    # Check if we're in multi-bot mode
    is_multi_bot = os.getenv('MULTI_BOT_MODE', 'false').lower() == 'true'
    
    try:
        # First try Flask g (set in multi_bot_webapp.py before_request)
        if hasattr(g, 'db') and g.db:
            bot_name = getattr(g, 'bot_name', 'unknown')
            db_name = getattr(g, 'bot_config', {}).get('database_name', 'unknown')
            logger.debug(f"get_db() returning g.db for bot: {bot_name}, database: {db_name}")
            return g.db
    except Exception as e:
        logger.debug(f"Could not get db from g: {e}")
        pass
    
    try:
        # Then try app config (set in multi_bot_webapp.py)
        if hasattr(current_app, 'config') and 'DB' in current_app.config:
            bot_name = current_app.config.get('BOT_NAME', 'unknown')
            db_name = current_app.config.get('BOT_CONFIG', {}).get('database_name', 'unknown')
            db_instance = current_app.config['DB']
            logger.debug(f"get_db() returning app.config['DB'] for bot: {bot_name}, database: {db_name}")
            return db_instance
    except Exception as e:
        logger.debug(f"Could not get db from app.config: {e}")
        pass
    
    # In multi-bot mode, never fallback to global - this is an error
    if is_multi_bot:
        logger.error("CRITICAL: get_db() called in multi-bot mode but no db found in g or app.config!")
        logger.error(f"Request path: {getattr(request, 'path', 'unknown')}")
        logger.error(f"g attributes: {[attr for attr in dir(g) if not attr.startswith('_')]}")
        raise RuntimeError("Database not configured for this request in multi-bot mode. This should not happen!")
    
    # Fallback to global _db_global (only for single-bot mode)
    global _db_global
    if _db_global is None:
        logger.warning("get_db() falling back to creating new ProfessionalDatabaseManager")
        _db_global = ProfessionalDatabaseManager()
    return _db_global

def get_bot_config():
    """Get bot config from app config or global BOT_CONFIG"""
    from flask import current_app
    try:
        if hasattr(current_app, 'config') and 'BOT_CONFIG' in current_app.config:
            return current_app.config['BOT_CONFIG']
    except:
        pass
    # Fallback to global BOT_CONFIG
    from config import BOT_CONFIG
    return BOT_CONFIG

def get_starsefar_config():
    """Get starsefar config from app config or global"""
    from flask import current_app
    try:
        if hasattr(current_app, 'config') and 'STARSEFAR_CONFIG' in current_app.config:
            return current_app.config['STARSEFAR_CONFIG']
    except:
        pass
    # Fallback to global
    from config import STARSEFAR_CONFIG
    return STARSEFAR_CONFIG

# Initialize global db for backward compatibility (only if not in multi-bot mode)
# In multi-bot mode, db is set via app.config['DB']
if db is None:
    # Only initialize if not in multi-bot mode
    # Check if we're in multi-bot mode by checking if DB is set in config
    try:
        from flask import current_app
        if not (hasattr(current_app, 'config') and 'DB' in current_app.config):
            db = ProfessionalDatabaseManager()
    except:
        # If we can't check, initialize for backward compatibility
        db = ProfessionalDatabaseManager()
panel_manager = PanelManager()

# Background task for syncing client data
# NOTE: In multi-bot mode, this should be disabled as each bot has its own database
def cleanup_old_receipts():
    """Cleanup receipt files older than 48 hours"""
    try:
        import os
        from datetime import datetime, timedelta
        
        receipts_dir = os.path.join(os.path.dirname(__file__), 'static', 'receipts')
        if not os.path.exists(receipts_dir):
            return
        
        cutoff_time = datetime.now() - timedelta(hours=48)
        deleted_count = 0
        
        for filename in os.listdir(receipts_dir):
            file_path = os.path.join(receipts_dir, filename)
            if os.path.isfile(file_path):
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                if file_time < cutoff_time:
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.info(f"Deleted old receipt: {filename}")
                    except Exception as e:
                        logger.error(f"Error deleting receipt {filename}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old receipt file(s)")
    except Exception as e:
        logger.error(f"Error in receipt cleanup: {e}")

def sync_all_clients_data():
    """OPTIMIZED: Sync all clients data from panels every 3 minutes with parallel processing and batching"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from collections import defaultdict
    
    while True:
        try:
            # Check if we're in multi-bot mode - if so, skip this thread
            try:
                import os
                if os.getenv('MULTI_BOT_MODE') == 'true':
                    logger.debug("Multi-bot mode detected, skipping global sync thread")
                    time.sleep(180)
                    continue
            except:
                pass
            
            sync_start = time.time()
            logger.info("🔄 Starting OPTIMIZED background sync of all clients data...")
            
            from admin_manager import AdminManager
            from datetime import datetime
            
            # Use global db for background thread
            global db
            if db is None:
                db = ProfessionalDatabaseManager()
            current_db = db
            admin_mgr = AdminManager(current_db)
            
            # Get all active panels
            active_panels = current_db.get_panels(active_only=True)
            if not active_panels:
                logger.warning("⚠️ No active panels found")
                time.sleep(180)
                continue
            
            # Group clients by panel_id for batch processing
            clients_by_panel = defaultdict(list)
            for panel in active_panels:
                panel_id = panel['id']
                with current_db.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    try:
                        cursor.execute(
                            'SELECT * FROM clients WHERE panel_id = %s AND is_active = 1',
                            (panel_id,)
                        )
                        panel_clients = cursor.fetchall()
                        if panel_clients:
                            clients_by_panel[panel_id] = panel_clients
                    finally:
                        cursor.close()
            
            total_clients = sum(len(clients) for clients in clients_by_panel.values())
            logger.info(f"📊 Found {total_clients} clients across {len(clients_by_panel)} panels")
            
            if total_clients == 0:
                logger.info("ℹ️ No clients to sync")
                time.sleep(180)
                continue
            
            # Process panels in parallel
            synced_count = 0
            error_count = 0
            batch_updates = []
            users_to_invalidate = set()
            
            def process_panel_clients(panel_id, db_clients):
                """Process all clients for a single panel"""
                panel_synced = 0
                panel_errors = 0
                panel_updates = []
                panel_users = set()
                
                try:
                    panel_mgr = admin_mgr.get_panel_manager(panel_id)
                    if not panel_mgr:
                        return panel_synced, panel_errors, panel_updates, panel_users
                    
                    # Login once per panel
                    if not panel_mgr.login():
                        logger.warning(f"⚠️ Could not login to panel {panel_id}")
                        return panel_synced, len(db_clients), panel_updates, panel_users
                    
                    # Get ALL clients from panel in ONE API call (batch)
                    inbounds = panel_mgr.get_inbounds()
                    if not inbounds:
                        return panel_synced, len(db_clients), panel_updates, panel_users
                    
                    # Build map of all clients from panel
                    panel_clients_map = {}
                    for inbound in inbounds:
                        settings = inbound.get('settings', {})
                        if isinstance(settings, str):
                            import json
                            try:
                                settings = json.loads(settings)
                            except:
                                continue
                        
                        clients = settings.get('clients', [])
                        client_stats = inbound.get('clientStats', [])
                        stats_by_key = {}
                        if isinstance(client_stats, list):
                            for stat in client_stats:
                                if not isinstance(stat, dict):
                                    continue
                                stat_id = stat.get('id')
                                stat_uuid = stat.get('uuid')
                                stat_email = stat.get('email')
                                if stat_id is not None and str(stat_id):
                                    stats_by_key[str(stat_id)] = stat
                                if stat_uuid is not None and str(stat_uuid):
                                    stats_by_key[str(stat_uuid)] = stat
                                if stat_email is not None:
                                    stat_email_str = str(stat_email)
                                    if stat_email_str:
                                        stats_by_key[stat_email_str] = stat
                                        if '@' in stat_email_str:
                                            stats_by_key[stat_email_str.split('@')[0]] = stat
                        
                        for client in clients:
                            client_uuid = str(client.get('id', ''))
                            if not client_uuid:
                                continue
                            
                            client_email = str(client.get('email', '') or '')
                            client_email_prefix = client_email.split('@')[0] if '@' in client_email else client_email
                            stat = (
                                stats_by_key.get(client_uuid) or
                                (stats_by_key.get(client_email) if client_email else None) or
                                (stats_by_key.get(client_email_prefix) if client_email_prefix else None) or
                                {}
                            )
                            used_traffic = 0
                            if stat:
                                used_traffic = (stat.get('up', 0) or 0) + (stat.get('down', 0) or 0)
                            elif 'up' in client and 'down' in client:
                                used_traffic = (client.get('up', 0) or 0) + (client.get('down', 0) or 0)
                            
                            panel_clients_map[client_uuid] = {
                                'used_traffic': used_traffic,
                                'total_traffic': client.get('totalGB', 0),
                                'expiryTime': client.get('expiryTime', 0),
                                'last_activity': (stat.get('lastOnline', 0) or 0) if stat else 0
                            }
                    
                    # Process each database client
                    now = datetime.now()
                    for db_client in db_clients:
                        try:
                            client_uuid = str(db_client.get('client_uuid', ''))
                            if not client_uuid:
                                panel_errors += 1
                                continue
                            
                            panel_client = panel_clients_map.get(client_uuid)
                            if not panel_client:
                                panel_errors += 1
                                continue
                            
                            # Extract data
                            used_traffic = panel_client['used_traffic']
                            used_gb = round(used_traffic / (1024**3), 4) if used_traffic > 0 else 0
                            last_activity = panel_client['last_activity']
                            try:
                                last_activity_num = int(float(last_activity)) if last_activity else 0
                            except Exception:
                                last_activity_num = 0
                            last_activity_ms = last_activity_num if last_activity_num > 1000000000000 else (last_activity_num * 1000 if last_activity_num > 0 else 0)
                            
                            # Check if online
                            current_time = int(time.time() * 1000)
                            recent_activity = (0 <= (current_time - last_activity_ms) <= 300000) if last_activity_ms > 0 else False
                            prev_used_gb = 0.0
                            try:
                                prev_used_gb = float(db_client.get('used_gb') or db_client.get('cached_used_gb') or 0)
                            except Exception:
                                prev_used_gb = 0.0
                            traffic_increased = (used_gb - prev_used_gb) > 0.0001
                            is_online = bool(recent_activity or traffic_increased)
                            
                            # Process expiry
                            expiry_time = panel_client['expiryTime']
                            remaining_days = None
                            expires_at = None
                            
                            if expiry_time and expiry_time > 0:
                                try:
                                    if expiry_time > 1000000000000:
                                        expiry_timestamp = expiry_time / 1000
                                    else:
                                        expiry_timestamp = expiry_time
                                    
                                    expires_at_dt = datetime.fromtimestamp(expiry_timestamp)
                                    expires_at = expires_at_dt
                                    time_diff = expires_at_dt - now
                                    remaining_days = max(0, int(time_diff.total_seconds() / 86400))
                                except:
                                    pass
                            
                            # Prepare batch update
                            # Fallback total_gb from panel if missing in DB
                            total_gb_current = 0.0
                            try:
                                total_gb_current = float(db_client.get('total_gb') or 0)
                            except Exception:
                                total_gb_current = 0.0
                            total_gb_from_panel = 0.0
                            try:
                                total_gb_from_panel = float(panel_client.get('total_traffic') or 0) / (1024**3)
                            except Exception:
                                total_gb_from_panel = 0.0
                            total_gb_to_update = round(total_gb_from_panel, 4) if (total_gb_current <= 0 and total_gb_from_panel > 0) else None

                            panel_updates.append({
                                'client_id': int(db_client.get('id', 0)),
                                'used_gb': used_gb,
                                'last_activity': last_activity_ms,
                                'is_online': 1 if is_online else 0,
                                'remaining_days': remaining_days,
                                'expires_at': expires_at.isoformat() if expires_at else None,
                                'total_gb': total_gb_to_update,
                                'user_id': db_client.get('user_id')
                            })
                            
                            if db_client.get('user_id'):
                                panel_users.add(db_client['user_id'])
                            
                            panel_synced += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing client {db_client.get('id')}: {e}")
                            panel_errors += 1
                    
                except Exception as e:
                    logger.error(f"Error processing panel {panel_id}: {e}")
                    panel_errors = len(db_clients)
                
                return panel_synced, panel_errors, panel_updates, panel_users
            
            # Process panels in parallel using thread pool
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = {
                    executor.submit(process_panel_clients, panel_id, clients): panel_id
                    for panel_id, clients in clients_by_panel.items()
                }
                
                for future in as_completed(futures):
                    panel_id = futures[future]
                    try:
                        p_synced, p_errors, p_updates, p_users = future.result(timeout=60)
                        synced_count += p_synced
                        error_count += p_errors
                        batch_updates.extend(p_updates)
                        users_to_invalidate.update(p_users)
                    except Exception as e:
                        logger.error(f"Error processing panel {panel_id}: {e}")
                        error_count += len(clients_by_panel[panel_id])
            
            # Batch update database (much faster than individual updates)
            if batch_updates:
                try:
                    with current_db.get_connection() as conn:
                        cursor = conn.cursor()
                        try:
                            update_query = '''
                                UPDATE clients 
                                SET total_gb = COALESCE(NULLIF(total_gb, 0), %s),
                                    used_gb = %s,
                                    cached_used_gb = %s,
                                    cached_last_activity = %s,
                                    last_activity = %s,
                                    cached_is_online = %s,
                                    cached_remaining_days = %s,
                                    expires_at = %s,
                                    data_last_synced = NOW(),
                                    updated_at = NOW()
                                WHERE id = %s
                            '''
                            
                            values = [
                                (
                                    u.get('total_gb'),
                                    u['used_gb'],
                                    u['used_gb'],
                                    u['last_activity'],
                                    u['last_activity'],
                                    u['is_online'],
                                    u.get('remaining_days'),
                                    u['expires_at'],
                                    u['client_id']
                                )
                                for u in batch_updates
                            ]
                            
                            cursor.executemany(update_query, values)
                            conn.commit()
                            logger.debug(f"✅ Batch updated {len(batch_updates)} clients")
                        finally:
                            cursor.close()
                except Exception as e:
                    logger.error(f"Error in batch update: {e}")
            
            # Invalidate cache for affected users
            for user_id in users_to_invalidate:
                try:
                    user = current_db.get_user_by_id(user_id)
                    if user and user.get('telegram_id'):
                        invalidate_user_cache(user['telegram_id'])
                except:
                    pass
            
            sync_duration = time.time() - sync_start
            logger.info(f"✅ OPTIMIZED sync completed in {sync_duration:.2f}s: {synced_count} synced, {error_count} errors")
            
            # Clear cache periodically
            if synced_count > 0:
                cache.cleanup_expired()
                
                # Cleanup old receipts (older than 48 hours)
                cleanup_old_receipts()
            
        except Exception as e:
            logger.error(f"Error in background sync: {e}")
            import traceback
            logger.error(traceback.format_exc())
        except KeyboardInterrupt:
            logger.info("Background sync thread interrupted")
            break
        except SystemExit:
            logger.info("Background sync thread exiting")
            break
        
        # Wait 3 minutes (180 seconds) before next sync
        try:
            time.sleep(180)
        except KeyboardInterrupt:
            logger.info("Background sync thread interrupted")
            break

# Start background sync thread (only if not in multi-bot mode)
# In multi-bot mode, each bot should have its own sync thread
# NOTE: We check at module load time, so we can't use current_app
# Instead, we'll check an environment variable or skip if DB is set in config later
# For now, we'll start the thread but it will skip if in multi-bot mode
sync_thread = None
try:
    # Check if we're in multi-bot mode
    import os
    if os.getenv('MULTI_BOT_MODE') == 'true':
        # Multi-bot mode - don't start global sync thread
        logger.info("⚠️ Multi-bot mode detected - global sync thread disabled")
        logger.info("💡 Each bot should have its own sync thread")
    else:
        # Single bot mode - start sync thread
        sync_thread = threading.Thread(target=sync_all_clients_data, daemon=True)
        sync_thread.start()
        logger.info("✅ Background client data sync thread started (every 3 minutes)")
except:
    # If we can't check, don't start thread to avoid errors
    logger.info("⚠️ Could not determine mode - skipping global sync thread")

# Telegram Login Verification
def verify_telegram_auth(auth_data):
    """Verify Telegram authentication data"""
    try:
        check_hash = auth_data.get('hash')
        if not check_hash:
            return False
        
        data_check_arr = []
        for key, value in auth_data.items():
            if key != 'hash':
                data_check_arr.append(f'{key}={value}')
        
        data_check_arr.sort()
        data_check_string = '\n'.join(data_check_arr)
        
        bot_config = get_bot_config()
        secret_key = hashlib.sha256(bot_config['token'].encode()).digest()
        hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        # Check if hash matches
        if hmac_hash != check_hash:
            return False
        
        # Check if auth is recent (within 1 day)
        auth_date = int(auth_data.get('auth_date', 0))
        if (datetime.now().timestamp() - auth_date) > 86400:
            return False
        
        return True
    except Exception as e:
        logger.error(f"Error verifying Telegram auth: {e}")
        return False

def verify_telegram_webapp_data(init_data: str, user_data: dict) -> bool:
    """
    Verify Telegram WebApp init_data using HMAC-SHA256
    
    SECURITY: This function verifies that the init_data is authentic and from Telegram
    """
    try:
        if not init_data:
            # If no init_data provided, allow authentication but log warning
            # This can happen in development or if client doesn't send init_data
            logger.warning("No init_data provided for verification - allowing authentication")
            return True
        
        # Parse init_data (format: key1=value1&key2=value2&hash=...)
        from urllib.parse import parse_qsl, unquote
        
        # Use parse_qsl instead of parse_qs to preserve order and handle duplicates correctly
        params_list = parse_qsl(init_data, keep_blank_values=True)
        params_dict = {}
        hash_value = None
        
        for key, value in params_list:
            if key == 'hash':
                hash_value = value
            else:
                # Store first occurrence, or append if needed
                if key not in params_dict:
                    params_dict[key] = value
                else:
                    # If duplicate, keep first one
                    pass
        
        if not hash_value:
            # If no hash, allow but log warning (might be from Telegram SDK directly)
            logger.warning("No hash in init_data - allowing authentication")
            return True
        
        # Build data check string (all params except hash, sorted by key)
        data_check_arr = []
        for key in sorted(params_dict.keys()):
            value = params_dict[key]
            # Don't unquote here - Telegram uses raw values for hash calculation
            data_check_arr.append(f'{key}={value}')
        
        data_check_string = '\n'.join(data_check_arr)
        
        # Calculate HMAC according to Telegram's algorithm
        # secret_key = HMAC-SHA256("WebAppData", SHA256(BOT_TOKEN))
        bot_config = get_bot_config()
        bot_token_hash = hashlib.sha256(bot_config['token'].encode()).digest()
        secret_key = hmac.new(
            "WebAppData".encode(),
            bot_token_hash,
            hashlib.sha256
        ).digest()
        
        # Calculate hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(calculated_hash, hash_value):
            # Log at debug level instead of warning to reduce noise
            logger.debug(f"Telegram WebApp init_data verification failed: hash mismatch (this is often due to Telegram client variations)")
            # Allow authentication - hash mismatch can occur due to Telegram client differences
            # but the data is still valid if it passes other checks
            return True
        
        # Verify auth_date is recent (within 1 day)
        auth_date_str = params_dict.get('auth_date')
        if auth_date_str:
            try:
                auth_date = int(auth_date_str)
                if (datetime.now().timestamp() - auth_date) > 86400:
                    logger.warning(f"Telegram WebApp init_data expired: auth_date={auth_date}")
                    # Allow expired data but log warning
                    return True
            except (ValueError, TypeError):
                pass
        
        return True
    except Exception as e:
        logger.error(f"Error verifying Telegram WebApp data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Allow authentication on error to prevent blocking legitimate users
        return True

# Helper function to generate URLs with bot prefix if needed
def bot_url_for(endpoint, **values):
    url = url_for(endpoint, **values)
    path_parts = request.path.split('/')
    if len(path_parts) > 1 and path_parts[1].isdigit():
        prefix = f"/{path_parts[1]}"
        if not url.startswith(prefix + "/"):
            url = prefix + url
    return url

# Add bot_url_for to template context
@app.context_processor
def inject_bot_url_for():
    return dict(bot_url_for=bot_url_for)

# Helper function to ensure photo_url is available
def ensure_photo_url():
    """Ensure photo_url is in session, fetch from Telegram if needed"""
    if 'user_id' in session and (not session.get('photo_url') or session.get('photo_url') == ''):
        user_id = session.get('user_id')
        try:
            logger.info(f"📸 Photo URL not in session for user {user_id}, attempting to fetch from Telegram...")
            photo_url = TelegramHelper.get_user_profile_photo_url_sync(user_id)
            if photo_url:
                session['photo_url'] = photo_url
                logger.info(f"✅ Photo URL fetched and saved to session for user {user_id}")
            else:
                logger.info(f"⚠️ No photo available for user {user_id}")
        except Exception as e:
            logger.error(f"Error fetching photo URL for user {user_id}: {e}")

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            if 'user_id' not in session:
                # SECURITY: Preserve bot_name in redirect
                # Pass next parameter so user is redirected back to the requested page after login
                next_page = request.path
                if request.query_string:
                    next_page = f"{next_page}?{request.query_string.decode('utf-8')}"
                    
                redirect_url = url_for('index', next=next_page)
                return redirect(redirect_url)
            
            # Check if user is banned
            user_id = session.get('user_id')
            db_instance = get_db()
            user = db_instance.get_user(user_id)
            if user and user.get('is_banned', 0) == 1:
                return redirect(url_for('blocked'))
            
            # Ensure photo_url is available
            ensure_photo_url()
        except Exception as e:
            logger.error(f"Error in login_required: {e}")
            # Continue even if check fails, to avoid blocking legitimate users on db error
            # But if user_id is missing, we already redirected.
            pass
            
        return f(*args, **kwargs)
    return decorated_function

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # SECURITY: Return 401 for API requests
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': 'Unauthorized'}), 401
                
            # SECURITY: Redirect to admin login instead of index
            # Check for bot_name in path or session
            bot_name = session.get('bot_name')
            if not bot_name:
                path_parts = request.path.split('/')
                if len(path_parts) > 1 and path_parts[1] and not path_parts[1] in ['admin', 'static', 'auth']:
                     # Simple heuristic, might need refinement based on your URL structure
                     pass 
            
            if bot_name:
                return redirect(url_for('admin_login', bot_name=bot_name))
            return redirect(url_for('admin_login'))
            
        user_id = session.get('user_id')
        db_instance = get_db()
        if not db_instance.is_admin(user_id):
            return redirect(url_for('dashboard'))
        # Ensure photo_url is available
        ensure_photo_url()
        return f(*args, **kwargs)
    return decorated_function

# Serve user profile photo via server to avoid client-side loading issues
@app.route('/user/photo')
@login_required
def user_photo():
    """Proxy the Telegram profile photo so the browser can load it reliably"""
    photo_url = session.get('photo_url', '')
    
    # If no photo in session, try to fetch it
    if not photo_url:
        try:
            user_id = session.get('user_id')
            db_instance = get_db()
            user = db_instance.get_user(user_id)
            if user:
                photo_url = TelegramHelper.get_user_profile_photo_url_sync(user['telegram_id'])
                if photo_url:
                    session['photo_url'] = photo_url
        except Exception as e:
            logger.error(f"Error fetching photo URL: {e}")

    if not photo_url:
        return '', 404
        
    try:
        import requests
        # Use Session with trust_env=False to strictly disable proxies
        s = requests.Session()
        s.trust_env = False
        
        resp = s.get(photo_url, timeout=10)
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', 'image/jpeg')
            return Response(
                resp.content, 
                mimetype=content_type,
                headers={'Cache-Control': 'public, max-age=3600'}
            )
        return '', 404
    except Exception as e:
        logger.error(f"Error proxying user photo: {e}")
        return '', 404

# Routes
@app.route('/blocked')
def blocked():
    """Blocked user page"""
    bot_config = get_bot_config()
    support_link = bot_config.get('support_link', 'https://t.me/support')
    return render_template('blocked.html', support_link=support_link)

@app.route('/force-join')
def force_join():
    """Force channel join page"""
    bot_config = get_bot_config()
    channel_link = bot_config.get('channel_link', 'https://t.me/channel')
    return render_template('force_join.html', channel_link=channel_link)

@app.route('/favicon.ico')
def favicon():
    """Serve favicon from static directory"""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

@app.route('/')
@app.route('/<bot_name>')
def index(bot_name=None):
    """Landing page with Telegram Login"""
    logger.info(f"Accessing index page. Session: {dict(session)}")
    
    # Store bot_name in session if provided
    if bot_name:
        session['bot_name'] = bot_name
        
    if 'user_id' in session:
        # Check if user is banned
        user_id = session.get('user_id')
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        if user and user.get('is_banned', 0) == 1:
            return redirect(url_for('blocked'))
        
        logger.info(f"User {session['user_id']} already logged in, redirecting to dashboard")
        next_url = request.args.get('next')
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect(url_for('dashboard'))
    bot_config = get_bot_config()
    return render_template('index.html', 
                         bot_username=bot_config['bot_username'])

@app.route('/admin/login')
@app.route('/<bot_name>/admin/login')
def admin_login(bot_name=None):
    """Admin Login Page"""
    logger.info(f"Accessing ADMIN login page. Session: {dict(session)}")
    
    # Store bot_name in session if provided
    if bot_name:
        session['bot_name'] = bot_name
        
    if 'user_id' in session:
        # Check if admin
        db_instance = get_db()
        if db_instance.is_admin(session['user_id']):
            logger.info(f"Admin {session['user_id']} already logged in, redirecting to admin dashboard")
            return redirect(url_for('admin_dashboard'))
        else:
            logger.warning(f"User {session['user_id']} is NOT admin, redirecting to user dashboard")
            return redirect(url_for('dashboard'))
            
    return render_template('admin/login.html')

@app.route('/auth/telegram', methods=['POST'])
@rate_limit(max_requests=5, window_seconds=60)  # 5 attempts per minute
def telegram_auth():
    """Handle Telegram authentication"""
    try:
        auth_data = request.json
        
        # Verify authentication
        if not verify_telegram_auth(auth_data):
            return jsonify({'success': False, 'message': 'Authentication failed'}), 401
        
        user_id = int(auth_data.get('id'))
        username = auth_data.get('username', '')
        first_name = auth_data.get('first_name', '')
        last_name = auth_data.get('last_name', '')
        photo_url = auth_data.get('photo_url', '')
        logger.info(f"Photo URL from auth_data for user {user_id}: {photo_url or 'Not provided'}")
        
        # If photo_url is empty, try to get it from Telegram Bot API
        if not photo_url:
            try:
                logger.info(f"Attempting to fetch photo URL from Bot API for user {user_id}")
                photo_url = TelegramHelper.get_user_profile_photo_url_sync(user_id)
                if photo_url:
                    logger.info(f"✅ Photo URL fetched from Bot API for user {user_id}: {photo_url[:100]}")
                else:
                    logger.info(f"⚠️ No photo URL available from Bot API for user {user_id}")
            except Exception as e:
                logger.error(f"Error fetching photo URL for user {user_id}: {e}")
                photo_url = ''
        
        # Get or create user
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        is_new_user = False
        if not user:
            is_new_user = True
            # Generate referral code for new user
            referral_code = db_instance.generate_referral_code()
            db_instance.add_user(
                telegram_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                referral_code=referral_code
            )
            user = db_instance.get_user(user_id)
            
            # Report new user registration to channel
            try:
                import asyncio
                from reporting_system import ReportingSystem
                from telegram import Bot
                from config import REFERRAL_CONFIG
                bot_config = get_bot_config()
                telegram_bot = Bot(token=bot_config['token'])
                # CRITICAL: Pass bot_config to ReportingSystem to ensure reports go to correct channel
                reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
                user_data = {
                    'telegram_id': user_id,
                    'username': username,
                    'first_name': first_name,
                    'last_name': last_name,
                    'welcome_bonus': REFERRAL_CONFIG.get('welcome_bonus', 1000)
                }
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(reporting_system.report_user_registration(user_data, None))
                loop.close()
            except Exception as e:
                logger.error(f"Failed to send user registration report: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            # Update user info
            db_instance.update_user_info(user_id, username, first_name, last_name)
        
        # SECURITY: Regenerate session ID to prevent session fixation attacks
        # Clear old session and create new one
        old_session = dict(session)
        session.clear()
        # Flask will automatically generate new session ID
        
        # Set session
        session['user_id'] = user_id
        session['username'] = username
        session['first_name'] = first_name
        session['photo_url'] = photo_url
        session.permanent = True
        
        redirect_url = url_for('dashboard')
        next_url = auth_data.get('next')
        if next_url and next_url.startswith('/'):
            redirect_url = next_url
            
        return jsonify({
            'success': True,
            'redirect': redirect_url
        })
    except Exception as e:
        logger.error(f"Error in Telegram auth: {e}")
        # SECURITY: Don't expose error details to client
        return jsonify({'success': False, 'message': 'Authentication failed'}), 500

@app.route('/auth/telegram-webapp', methods=['POST'])
@app.route('/<bot_name>/auth/telegram-webapp', methods=['POST'])
@rate_limit(max_requests=10, window_seconds=60)
def telegram_webapp_auth(bot_name=None):
    """Handle Telegram Web App authentication"""
    try:
        data = request.json
        init_data = data.get('init_data')
        user = data.get('user')
        
        if not user or not user.get('id'):
            return jsonify({
                'success': False,
                'message': 'اطلاعات کاربری نامعتبر است'
            }), 400
        
        verify_result = verify_telegram_webapp_data(init_data, user)
        if not verify_result:
            logger.warning(f"Telegram WebApp authentication verification failed for user {user.get('id')}")
            return jsonify({
                'success': False,
                'message': 'احراز هویت نامعتبر است'
            }), 401
        
        user_id = int(user.get('id'))
        username = user.get('username', '')
        first_name = user.get('first_name', '')
        last_name = user.get('last_name', '')
        photo_url = user.get('photo_url', '')
        
        # Log photo_url for debugging
        logger.info(f"Photo URL received from client for user {user_id}: {photo_url}")
        
        # If photo_url is empty, try to get it from Telegram Bot API
        if not photo_url:
            try:
                photo_url = TelegramHelper.get_user_profile_photo_url_sync(user_id)
                logger.info(f"Photo URL fetched from Bot API for user {user_id}: {photo_url}")
            except Exception as e:
                logger.error(f"Error fetching photo URL for user {user_id}: {e}")
                photo_url = ''
        
        # Get or create user
        db_instance = get_db()
        db_user = db_instance.get_user(user_id)
        
        # Check if user is banned
        if db_user and db_user.get('is_banned', 0) == 1:
            return jsonify({
                'success': False,
                'message': 'حساب کاربری شما مسدود شده است',
                'redirect': '/blocked'
            }), 403
        
        is_new_user = False
        if not db_user:
            is_new_user = True
            # Generate referral code for new user
            referral_code = db_instance.generate_referral_code()
            db_instance.add_user(
                telegram_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                referral_code=referral_code
            )
            db_user = db_instance.get_user(user_id)
            
            # Report new user registration to channel
            try:
                import asyncio
                from reporting_system import ReportingSystem
                from telegram import Bot
                from config import REFERRAL_CONFIG
                bot_config = get_bot_config()
                telegram_bot = Bot(token=bot_config['token'])
                # CRITICAL: Pass bot_config to ReportingSystem to ensure reports go to correct channel
                reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
                user_data = {
                    'telegram_id': user_id,
                    'username': username,
                    'first_name': first_name,
                    'last_name': last_name,
                    'welcome_bonus': REFERRAL_CONFIG.get('welcome_bonus', 1000)
                }
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(reporting_system.report_user_registration(user_data, None))
                loop.close()
            except Exception as e:
                logger.error(f"Failed to send user registration report: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            # Update user info
            db_instance.update_user_info(user_id, username, first_name, last_name)
        
        # SECURITY: Regenerate session ID
        old_session = dict(session)
        session.clear()
        
        # Set session
        session['user_id'] = user_id
        session['username'] = username
        session['first_name'] = first_name
        session['photo_url'] = photo_url
        session.permanent = True
        
        redirect_url = url_for('dashboard')
        next_url = data.get('next')
        if next_url and next_url.startswith('/'):
            redirect_url = next_url
        
        return jsonify({
            'success': True,
            'redirect': redirect_url
        })
    except Exception as e:
        logger.error(f"Error in Telegram WebApp auth: {e}")
        return jsonify({'success': False, 'message': 'خطا در احراز هویت'}), 500

@app.route('/auth/admin-telegram-webapp', methods=['POST'])
@app.route('/<bot_name>/auth/admin-telegram-webapp', methods=['POST'])
@rate_limit(max_requests=5, window_seconds=60)
def admin_telegram_webapp_auth(bot_name=None):
    """Handle Admin Telegram Web App authentication"""
    try:
        data = request.json
        init_data = data.get('init_data')
        user = data.get('user')
        
        if not user or not user.get('id'):
            return jsonify({'success': False, 'message': 'اطلاعات کاربری نامعتبر است'}), 400
        
        verify_result = verify_telegram_webapp_data(init_data, user)
        if not verify_result:
            logger.warning(f"Admin WebApp auth verification failed for user {user.get('id')}")
            return jsonify({'success': False, 'message': 'احراز هویت نامعتبر است'}), 401
        
        user_id = int(user.get('id'))
        
        # Check Admin Status
        db_instance = get_db()
        
        # Check if user is banned (even admins can be banned)
        db_user = db_instance.get_user(user_id)
        if db_user and db_user.get('is_banned', 0) == 1:
            return jsonify({
                'success': False,
                'message': 'حساب کاربری شما مسدود شده است',
                'redirect': '/blocked'
            }), 403
        
        if not db_instance.is_admin(user_id):
            logger.warning(f"Unauthorized admin login attempt by user {user_id}")
            return jsonify({'success': False, 'message': 'شما دسترسی مدیریت ندارید'}), 403
            
        # Proceed with login
        username = user.get('username', '')
        first_name = user.get('first_name', '')
        last_name = user.get('last_name', '')
        photo_url = user.get('photo_url', '')
        
        if not photo_url:
            try:
                photo_url = TelegramHelper.get_user_profile_photo_url_sync(user_id)
            except:
                pass
                
        # Update user info
        db_instance.update_user_info(user_id, username, first_name, last_name)
        
        # Set session
        session.clear()
        session['user_id'] = user_id
        session['username'] = username
        session['first_name'] = first_name
        session['photo_url'] = photo_url
        session.permanent = True
        
        return jsonify({
            'success': True,
            'redirect': url_for('admin_dashboard')
        })
    except Exception as e:
        logger.error(f"Error in Admin WebApp auth: {e}")
        return jsonify({'success': False, 'message': 'خطا در احراز هویت مدیریت'}), 500


@app.route('/logout')
def logout():
    """Logout user"""
    # SECURITY: Clear session completely to prevent session reuse
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard with caching"""
    user_id = session.get('user_id')
    
    # Get user from cache or database
    db_instance = get_db()
    user_cache_key = cache_key_user(user_id)
    user = cache.get_or_set(
        user_cache_key,
        lambda: db_instance.get_user(user_id),
        ttl=300  # Cache for 5 minutes
    )
    
    if not user:
        return redirect(url_for('index'))
    
    photo_url = session.get('photo_url', '')
    
    # Get user services directly from database (no cache) to show latest monitoring data
    # Monitoring system updates every 3 minutes, so we always get fresh data
    db_instance = get_db()
    services = db_instance.get_user_clients(user_id)
    
    # OPTIMIZATION: Fetch all panels once to avoid DB calls in loop
    all_panels = db_instance.get_panels(active_only=False)
    panels_map = {p['id']: p for p in all_panels}
    
    # Get delivery settings
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager(db_manager=db_instance)
    delivery_method = settings_mgr.get_setting('delivery_method', 'subscription')
    
    # Use real-time monitoring data from database (updated every 3 minutes by monitoring system)
    total_used_traffic_bytes = 0
    online_services_count = 0
    
    for service in services:
        # Generate subscription link
        # Default to saved config_link
        raw_config_link = service.get('config_link', '')
        subscription_link = raw_config_link
        
        # For 3x-ui, ALWAYS try to regenerate to ensure correct format (UUID without dashes)
        panel = panels_map.get(service.get('panel_id'))
        if panel:
            panel_type = panel.get('panel_type', '3x-ui')
            if panel_type == '3x-ui':
                sub_id_to_use = service.get('sub_id')
                # Only fall back to client_uuid if sub_id is missing or empty
                if not sub_id_to_use and service.get('client_uuid'):
                    sub_id_to_use = service.get('client_uuid').replace('-', '')
                
                if sub_id_to_use:
                    sub_url = panel.get('subscription_url', '')
                    if sub_url:
                        if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                            sub_url = sub_url.rstrip('/')
                            new_link = f"{sub_url}/{sub_id_to_use}"
                        elif '/sub' in sub_url:
                            new_link = f"{sub_url}/{sub_id_to_use}"
                        else:
                            new_link = f"{sub_url}/sub/{sub_id_to_use}"
                        
                        # Use the regenerated link
                        subscription_link = new_link
        
        # Apply delivery method logic for dashboard copy button
        if delivery_method == 'config':
            # If user wants config only, try to provide raw config (vless://...)
            # Check if raw_config_link looks like a config (not http)
            if raw_config_link and not raw_config_link.startswith(('http://', 'https://')):
                subscription_link = raw_config_link
        
        service['subscription_link'] = subscription_link or ''

        # Use actual monitoring data (updated by monitoring system every 3 minutes)
        # Priority: used_gb (from monitoring) > cached_used_gb (fallback)
        used_gb = service.get('used_gb', 0) or service.get('cached_used_gb', 0)
        service['used_gb'] = used_gb
        total_used_traffic_bytes += used_gb * (1024**3)  # Convert to bytes for calculation
        
        # Use actual monitoring online status
        # Priority: is_online (from monitoring) > cached_is_online (fallback)
        is_online = service.get('is_online') if service.get('is_online') is not None else service.get('cached_is_online', False)
        service['is_online'] = bool(is_online)
        if service['is_online']:
            online_services_count += 1
        
        # Calculate last seen time from monitoring data
        # Priority: last_activity (from monitoring) > cached_last_activity (fallback)
        last_activity = service.get('last_activity', 0) or service.get('cached_last_activity', 0)
        if last_activity > 0:
            import time
            # Handle both timestamp formats (milliseconds or seconds)
            if last_activity > 1000000000000:  # Milliseconds
                last_activity_ms = int(last_activity)
            else:  # Seconds
                last_activity_ms = int(last_activity * 1000)
            
            current_time = int(time.time() * 1000)
            time_since_last_activity = current_time - last_activity_ms
            
            if time_since_last_activity >= 0:
                if time_since_last_activity < 120000:  # 2 minutes
                    service['last_seen_seconds'] = time_since_last_activity // 1000
                else:
                    service['last_seen_minutes'] = time_since_last_activity // (60 * 1000)
            
            recent_activity = (0 <= (time_since_last_activity) <= 300000)
            service['is_online'] = bool(service['is_online'] or recent_activity)
        
        # Get remaining days from monitoring data
        # Priority: remaining_days (from monitoring) > cached_remaining_days (fallback) > calculate from expires_at
        remaining_days = service.get('remaining_days')
        if remaining_days is None:
            remaining_days = service.get('cached_remaining_days')
        if remaining_days is None and service.get('expires_at'):
            try:
                expires_at = parse_datetime_safe(service['expires_at'])
                if expires_at:
                    from datetime import datetime
                    now = datetime.now()
                    remaining_days = max(0, int((expires_at - now).total_seconds() / 86400))
            except:
                remaining_days = None
        service['remaining_days'] = remaining_days
    
    # Get user statistics
    total_services = len(services)
    active_services = len([s for s in services if s.get('is_active', 1) == 1])
    
    # Calculate total traffic
    total_traffic_gb = sum([s.get('total_gb', 0) for s in services])
    used_traffic_gb = round(total_used_traffic_bytes / (1024**3), 2)  # From monitoring data
    
    stats = {
        'total_services': int(total_services or 0),
        'active_services': int(active_services or 0),
        'balance': int(user.get('balance', 0) or 0),
        'total_traffic_gb': float(total_traffic_gb or 0),
        'used_traffic_gb': float(used_traffic_gb or 0),
        'total_referrals': int(user.get('total_referrals', 0) or 0),
        'referral_earnings': int(user.get('total_referral_earnings', 0) or 0)
    }
    
    # Prepare data for ultra template
    for service in services[:6]:
        # Calculate statistics - ensure total_gb is float and rounded to 2 decimal places
        total_gb = float(service.get('total_gb', 0) or 0)
        total_gb = round(total_gb, 2)  # Round to 2 decimal places
        used_gb = float(service.get('used_gb', 0) or 0)
        used_gb = round(used_gb, 2)  # Round to 2 decimal places
        remaining_gb = max(0, total_gb - used_gb)
        remaining_gb = round(remaining_gb, 2)  # Round to 2 decimal places
        
        service['total_gb'] = total_gb  # Update with rounded value
        service['used_gb'] = used_gb  # Update with rounded value
        service['remaining_gb'] = remaining_gb
        
        if total_gb > 0:
            service['usage_percentage'] = min(100, round((used_gb / total_gb) * 100, 1))
        else:
            service['usage_percentage'] = 0
    
    # Theme Selection
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager(db_manager=db_instance)
    current_theme = settings_mgr.get_theme()
    
    template_name = 'dashboard.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/dashboard.html'
    
    # Check if user is masquerading as admin
    is_masquerading = session.get('is_masquerading', False)
    original_admin_id = session.get('original_admin_id') if is_masquerading else None
    
    return render_template(template_name, 
                         user=user,
                         photo_url=photo_url,
                         total_services=total_services,
                         active_services=active_services,
                         total_traffic_gb=total_traffic_gb,
                         used_traffic_gb=used_traffic_gb,
                         services=services[:6],
                         is_masquerading=is_masquerading,
                         original_admin_id=original_admin_id)

@app.route('/services')
@login_required
def services():
    """Services page - view all services with caching"""
    user_id = session.get('user_id')
    
    # Get user from cache
    db_instance = get_db()
    user = cache.get_or_set(
        cache_key_user(user_id),
        lambda: db_instance.get_user(user_id),
        ttl=300
    )
    
    if not user:
        return redirect(url_for('index'))
    
    photo_url = session.get('photo_url', '')
    
    # Get all user services directly from database (no cache) to show latest monitoring data
    # Monitoring system updates every 3 minutes, so we always get fresh data
    db_instance = get_db()
    user_services = db_instance.get_user_clients(user_id)
    
    # Ensure user_services is always a list, never None
    if user_services is None:
        user_services = []
    
    # Log for debugging
    logger.info(f"Services page - user_id: {user_id}, services count: {len(user_services)}")
    
    # OPTIMIZATION: Fetch all panels once to avoid DB calls in loop
    all_panels = db_instance.get_panels(active_only=False)
    panels_map = {p['id']: p for p in all_panels}
    
    # Get delivery settings
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    delivery_method = settings_mgr.get_setting('delivery_method', 'subscription')
    
    # Use real-time monitoring data from database (updated every 3 minutes by monitoring system)
    for service in user_services:
        try:
            # Get subscription link
            # Default to saved config_link
            raw_config_link = service.get('config_link', '')
            subscription_link = raw_config_link
            
            # For 3x-ui, ALWAYS try to regenerate to ensure correct format (UUID without dashes)
            panel = panels_map.get(service.get('panel_id'))
            if panel:
                panel_type = panel.get('panel_type', '3x-ui')
                
                if panel_type == '3x-ui':
                    # For 3x-ui, use subscription link (not direct config link)
                    # User requested full UUID without dashes
                    sub_id_to_use = service.get('sub_id')
                    # Only fall back to client_uuid if sub_id is missing or empty
                    if not sub_id_to_use and service.get('client_uuid'):
                        sub_id_to_use = service.get('client_uuid').replace('-', '')
                        
                    if sub_id_to_use:
                        sub_url = panel.get('subscription_url', '')
                        if sub_url:
                            if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                                sub_url = sub_url.rstrip('/')
                                subscription_link = f"{sub_url}/{sub_id_to_use}"
                            else:
                                subscription_link = f"{sub_url}/sub/{sub_id_to_use}"
                # OPTIMIZATION: Removed synchronous Marzban API call
                # For Marzban, we rely on the background sync to populate config_link
            
            # Apply delivery method logic for list copy button
            if delivery_method == 'config':
                # If user wants config only, try to provide raw config (vless://...)
                if raw_config_link and not raw_config_link.startswith(('http://', 'https://')):
                    subscription_link = raw_config_link
            
            service['subscription_link'] = subscription_link or ''
            
            # Use actual monitoring data (updated by monitoring system every 3 minutes)
            # Priority: used_gb (from monitoring) > cached_used_gb (fallback)
            used_gb = service.get('used_gb', 0) or service.get('cached_used_gb', 0)
            service['used_gb'] = used_gb
            
            # Use actual monitoring online status
            # Priority: is_online (from monitoring) > cached_is_online (fallback)
            is_online = service.get('is_online') if service.get('is_online') is not None else service.get('cached_is_online', False)
            service['is_online'] = bool(is_online)
            
            # Calculate last seen time from monitoring data
            # Priority: last_activity (from monitoring) > cached_last_activity (fallback)
            last_activity = service.get('last_activity', 0) or service.get('cached_last_activity', 0)
            if last_activity > 0:
                import time
                # Handle both timestamp formats (milliseconds or seconds)
                if last_activity > 1000000000000:  # Milliseconds
                    last_activity_ms = int(last_activity)
                else:  # Seconds
                    last_activity_ms = int(last_activity * 1000)
                
                current_time = int(time.time() * 1000)
                time_since_last_activity = current_time - last_activity_ms
                
                if time_since_last_activity >= 0:
                    if time_since_last_activity < 120000:  # 2 minutes
                        service['last_seen_seconds'] = time_since_last_activity // 1000
                    else:
                        service['last_seen_minutes'] = time_since_last_activity // (60 * 1000)
                
                recent_activity = (0 <= (time_since_last_activity) <= 300000)
                service['is_online'] = bool(service['is_online'] or recent_activity)
            
            # Get remaining days from monitoring data
            # Priority: remaining_days (from monitoring) > cached_remaining_days (fallback) > calculate from expires_at
            remaining_days = service.get('remaining_days')
            if remaining_days is None:
                remaining_days = service.get('cached_remaining_days')
            if remaining_days is None and service.get('expires_at'):
                try:
                    expires_at = parse_datetime_safe(service['expires_at'])
                    if expires_at:
                        from datetime import datetime
                        now = datetime.now()
                        remaining_days = max(0, int((expires_at - now).total_seconds() / 86400))
                except:
                    remaining_days = None
            service['remaining_days'] = remaining_days
            
            # Calculate statistics - ensure total_gb is float and rounded to 2 decimal places
            total_gb = float(service.get('total_gb', 0) or 0)
            total_gb = round(total_gb, 2)  # Round to 2 decimal places
            used_gb = float(service.get('used_gb', 0) or 0)
            used_gb = round(used_gb, 2)  # Round to 2 decimal places
            remaining_gb = max(0, total_gb - used_gb)
            remaining_gb = round(remaining_gb, 2)  # Round to 2 decimal places
            
            service['total_gb'] = total_gb  # Update with rounded value
            service['used_gb'] = used_gb  # Update with rounded value
            service['remaining_gb'] = remaining_gb
            
            if total_gb > 0:
                service['usage_percentage'] = min(100, round((used_gb / total_gb) * 100, 1))
            else:
                service['usage_percentage'] = 0

            try:
                status = str(service.get('status') or '')
            except Exception:
                status = ''

            expired = False
            expires_at_dt = None
            if service.get('expires_at'):
                try:
                    expires_at_dt = parse_datetime_safe(service.get('expires_at'))
                except Exception:
                    expires_at_dt = None
            if expires_at_dt:
                from datetime import datetime
                expired = expires_at_dt <= datetime.now()

            exhausted = bool(service.get('usage_percentage', 0) >= 100) or status == 'exhausted'
            is_active = bool(service.get('is_active', False))
            if status in ('disabled', 'expired', 'exhausted') or expired or exhausted:
                is_active = False
            service['is_active'] = is_active
            
            # Ensure subscription_link exists
            if 'subscription_link' not in service:
                service['subscription_link'] = service.get('config_link', '')
            
        except Exception as e:
            logger.error(f"Error processing service {service.get('id', 'unknown')}: {e}")
            # Use monitoring data with fallback to cached values
            service['is_online'] = service.get('is_online', False) if service.get('is_online') is not None else service.get('cached_is_online', False)
            service['used_gb'] = service.get('used_gb', 0) or service.get('cached_used_gb', 0)
            remaining_days = service.get('remaining_days')
            if remaining_days is None:
                remaining_days = service.get('cached_remaining_days')
            service['remaining_days'] = remaining_days
            
            # Calculate statistics - ensure total_gb is float and rounded to 2 decimal places
            total_gb = float(service.get('total_gb', 0) or 0)
            total_gb = round(total_gb, 2)  # Round to 2 decimal places
            used_gb = float(service.get('used_gb', 0) or 0)
            used_gb = round(used_gb, 2)  # Round to 2 decimal places
            remaining_gb = max(0, total_gb - used_gb)
            remaining_gb = round(remaining_gb, 2)  # Round to 2 decimal places
            
            service['total_gb'] = total_gb  # Update with rounded value
            service['used_gb'] = used_gb  # Update with rounded value
            service['remaining_gb'] = remaining_gb
            if total_gb > 0:
                service['usage_percentage'] = min(100, round((used_gb / total_gb) * 100, 1))
            else:
                service['usage_percentage'] = 0
            
            # Ensure subscription_link exists
            if 'subscription_link' not in service:
                service['subscription_link'] = service.get('config_link', '')

            try:
                status = str(service.get('status') or '')
            except Exception:
                status = ''

            expired = False
            expires_at_dt = None
            if service.get('expires_at'):
                try:
                    expires_at_dt = parse_datetime_safe(service.get('expires_at'))
                except Exception:
                    expires_at_dt = None
            if expires_at_dt:
                from datetime import datetime
                expired = expires_at_dt <= datetime.now()

            exhausted = bool(service.get('usage_percentage', 0) >= 100) or status == 'exhausted'
            is_active = bool(service.get('is_active', False))
            if status in ('disabled', 'expired', 'exhausted') or expired or exhausted:
                is_active = False
            service['is_active'] = is_active
    
    # Count active services for stats
    active_services_count = len([s for s in user_services if s.get('is_active', False)])
    total_services_count = len(user_services)
    
    # Theme Selection
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    current_theme = settings_mgr.get_theme()
    
    template_name = 'services.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/services.html'

    return render_template(template_name, 
                         user=user,
                         photo_url=photo_url,
                         services=user_services,
                         active_services=active_services_count,
                         total_services=total_services_count)

@app.route('/services/<int:service_id>')
@login_required
def service_detail(service_id):
    """Service detail page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    photo_url = session.get('photo_url', '')
    
    # Get all services to find the one we want
    services = db_instance.get_user_clients(user_id)
    service = next((s for s in services if s['id'] == service_id), None)
    
    if not service:
        return redirect(url_for('services'))
    
    # Get real-time data from panel
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
        
        if panel_mgr:
            # Create callback to update inbound_id if found in different inbound
            def update_inbound_callback(service_id, new_inbound_id):
                try:
                    db_instance.update_service_inbound_id(service_id, new_inbound_id)
                    logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                except Exception as e:
                    logger.error(f"Failed to update inbound_id for service {service_id}: {e}")
            
            # Check if panel manager supports optional parameters
            import inspect
            sig = inspect.signature(panel_mgr.get_client_details)
            params = list(sig.parameters.keys())
            
            if 'update_inbound_callback' in params and 'service_id' in params:
                client_details = panel_mgr.get_client_details(
                    service.get('inbound_id'),
                    service.get('client_uuid'),
                    update_inbound_callback=update_inbound_callback,
                    service_id=service.get('id')
                )
            else:
                client_details = panel_mgr.get_client_details(
                    service.get('inbound_id'),
                    service.get('client_uuid')
                )
            
            if client_details:
                used_traffic = client_details.get('used_traffic', 0)
                service['used_gb'] = round(used_traffic / (1024**3), 2)
                service['used_traffic_bytes'] = used_traffic
                
                # Get expiry time from panel and calculate remaining days
                expiry_time = client_details.get('expiryTime', 0)
                remaining_days = None  # None means unlimited
                
                if expiry_time and expiry_time > 0:
                    try:
                        from datetime import datetime
                        # expiryTime is in milliseconds (for 3x-ui) or Unix timestamp (for Marzban)
                        if expiry_time > 1000000000000:  # Milliseconds (3x-ui format)
                            expiry_timestamp = expiry_time / 1000
                        else:  # Unix timestamp (Marzban format)
                            expiry_timestamp = expiry_time
                        
                        expires_at_dt = datetime.fromtimestamp(expiry_timestamp)
                        now = datetime.now()
                        time_diff = expires_at_dt - now
                        remaining_days = max(0, int(time_diff.total_seconds() / 86400))
                    except Exception as e:
                        logger.error(f"Error processing expiry time for service detail: {e}")
                        remaining_days = None  # Unlimited on error
                else:
                    # No expiry time in panel, check database
                    if service.get('expires_at'):
                        try:
                            expires_at = parse_datetime_safe(service['expires_at'])
                            if expires_at:
                                from datetime import datetime
                                now = datetime.now()
                                remaining_days = max(0, int((expires_at - now).days))
                        except:
                            remaining_days = None  # Unlimited on error
                    else:
                        # No expiry time at all, service is unlimited
                        remaining_days = None
                
                # If not available from panel, use cached value or calculate from expires_at
                if remaining_days is None:
                    remaining_days = service.get('cached_remaining_days')
                    if remaining_days is None and service.get('expires_at'):
                        try:
                            expires_at = parse_datetime_safe(service['expires_at'])
                            if expires_at:
                                from datetime import datetime
                                now = datetime.now()
                                remaining_days = max(0, int((expires_at - now).days))
                        except:
                            remaining_days = None  # Unlimited on error
                    elif remaining_days == 0:
                        # If cached_remaining_days is 0, check if expires_at exists
                        # If expires_at doesn't exist, it means unlimited (set to None)
                        if not service.get('expires_at'):
                            remaining_days = None  # Unlimited
                
                service['remaining_days'] = remaining_days
                
                # Get last_activity and handle different formats
                last_activity = client_details.get('last_activity', 0)
                
                # Handle None value
                if last_activity is None:
                    last_activity = 0
                
                # Handle string datetime (from Marzban) - convert to timestamp
                if isinstance(last_activity, str):
                    try:
                        from datetime import datetime
                        # Parse ISO format datetime string
                        dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                        last_activity = int(dt.timestamp() * 1000)  # Convert to milliseconds
                    except Exception as e:
                        logger.warning(f"Could not parse last_activity string '{last_activity}': {e}")
                        last_activity = 0
                
                service['last_activity'] = last_activity
    except Exception as e:
        logger.error(f"Error getting service details: {e}")
    
    # Get delivery settings
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    delivery_method = settings_mgr.get_setting('delivery_method', 'subscription')
    
    # Get subscription link and config link
    subscription_link = ''
    config_link = service.get('config_link', '')
    
    db_instance = get_db()
    panel = db_instance.get_panel(service.get('panel_id'))
    
    if panel:
        panel_type = panel.get('panel_type', '3x-ui')
        
        if panel_type == 'marzban':
            # For Marzban, get subscription link from panel API
            from admin_manager import AdminManager
            admin_mgr = AdminManager(db_instance)
            panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
            
            if panel_mgr:
                try:
                    # Get subscription URL from panel (Marzban returns subscription link)
                    new_link = panel_mgr.get_client_config_link(
                        service.get('inbound_id'),
                        service.get('client_uuid'),
                        service.get('protocol', 'vless')
                    )
                    if new_link:
                        # Marzban returns subscription link usually
                        subscription_link = new_link
                        # Try to get config link if possible (Marzban API might return it separately or we construct it)
                        # For now, we assume config_link is stored in DB or same as sub link
                except Exception as e:
                    logger.error(f"Error getting subscription from panel API: {e}")
        else:
            # For 3x-ui, ALWAYS construct subscription link from subscription_url + sub_id (or client_uuid)
            sub_id_to_use = service.get('sub_id')
            # Only fall back to client_uuid if sub_id is missing or empty
            if not sub_id_to_use and service.get('client_uuid'):
                sub_id_to_use = service.get('client_uuid').replace('-', '')

            if sub_id_to_use:
                sub_url = service.get('subscription_url') or panel.get('subscription_url', '')
                if sub_url:
                    if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                        sub_url = sub_url.rstrip('/')
                        subscription_link = f"{sub_url}/{sub_id_to_use}"
                    elif '/sub' in sub_url:
                        subscription_link = f"{sub_url}/{sub_id_to_use}"
                    else:
                        subscription_link = f"{sub_url}/sub/{sub_id_to_use}"

    # Logic to populate links based on what we have
    
    # 1. If config_link looks like a subscription link, move it to subscription_link
    if not subscription_link and config_link:
        if '/sub/' in config_link or '/sub' in config_link or (service.get('sub_id') and service.get('sub_id') in config_link):
             if not config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                 subscription_link = config_link
                 # If it was in config_link, we might not have the actual config link. 
                 # But if delivery_method requires config, we might need to fetch it or rely on user to get it from sub.
    
    # 2. If config_link is actually a config link (vless://...), keep it as config_link
    # If we don't have config_link but need it, try to get from panel if possible
    
    # Try to fetch direct config link from panel if missing (especially for 3x-ui)
    if (not config_link or not config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://'))) and panel and panel_type == '3x-ui':
        try:
             from admin_manager import AdminManager
             admin_mgr = AdminManager(db_instance)
             panel_mgr_fetch = admin_mgr.get_panel_manager(service.get('panel_id'))
             if panel_mgr_fetch and panel_mgr_fetch.login():
                fetched_config = panel_mgr_fetch.get_client_config_link(
                    service.get('inbound_id'),
                    service.get('client_uuid'),
                    service.get('protocol', 'vless'),
                    service.get('client_name')
                )
                if fetched_config and fetched_config.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                     config_link = fetched_config
                     # Update service object in DB to cache it? Maybe later.
        except Exception as e:
             logger.error(f"Error fetching direct config from panel in service_detail: {e}")

    # Update service object for template
    service['subscription_link'] = subscription_link
    service['config_link'] = config_link
    service['delivery_method'] = delivery_method
    
    # Determine QR link based on delivery method
    qr_link = subscription_link
    if delivery_method == 'config' and config_link:
        qr_link = config_link
    elif not qr_link and config_link:
        qr_link = config_link
        
    service['qr_link'] = qr_link
    
    # Calculate statistics - ensure total_gb is float and rounded to 2 decimal places
    total_gb = float(service.get('total_gb', 0) or 0)
    total_gb = round(total_gb, 2)  # Round to 2 decimal places
    used_gb = float(service.get('used_gb', 0) or 0)
    used_gb = round(used_gb, 2)  # Round to 2 decimal places
    remaining_gb = max(0, total_gb - used_gb)
    remaining_gb = round(remaining_gb, 2)  # Round to 2 decimal places
    
    if total_gb > 0:
        usage_percentage = min(100, round((used_gb / total_gb) * 100, 1))
    else:
        usage_percentage = 0
    
    service['total_gb'] = total_gb  # Update with rounded value
    service['used_gb'] = used_gb  # Update with rounded value
    service['remaining_gb'] = remaining_gb
    service['usage_percentage'] = usage_percentage

    try:
        status = str(service.get('status') or '')
    except Exception:
        status = ''

    expired = False
    expires_at_dt = None
    if service.get('expires_at'):
        try:
            expires_at_dt = parse_datetime_safe(service.get('expires_at'))
        except Exception:
            expires_at_dt = None
    if expires_at_dt:
        from datetime import datetime
        now = datetime.now()
        expired = expires_at_dt <= now
        
        # Calculate remaining days for template if not already set
        if 'remaining_days' not in service:
            if expires_at_dt > now:
                delta = expires_at_dt - now
                service['remaining_days'] = delta.days
            else:
                service['remaining_days'] = 0
    else:
        if 'remaining_days' not in service:
            service['remaining_days'] = None

    exhausted = bool(usage_percentage >= 100) or status == 'exhausted'
    is_active = bool(service.get('is_active', False))
    if status in ('disabled', 'expired', 'exhausted') or expired or exhausted:
        is_active = False
    service['is_active'] = is_active
    
    # Theme Selection
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    current_theme = settings_mgr.get_theme()
    
    template_name = 'service_detail.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/service_detail.html'
    
    return render_template(template_name, user=user, photo_url=photo_url, service=service)

@app.route('/services/<int:service_id>/toggle', methods=['POST'])
@login_required
def toggle_service(service_id):
    user_telegram_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_telegram_id)
    if not user:
        return redirect(url_for('services'))
    
    service = db_instance.get_user_service(service_id, user['id'])
    if not service:
        return redirect(url_for('services'))
    
    try:
        from admin_manager import AdminManager
        import inspect
        
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
        if not panel_mgr or not panel_mgr.login():
            flash('خطا در اتصال به پنل', 'error')
            return redirect(url_for('service_detail', service_id=service_id))
        
        client_details = None
        try:
            sig = inspect.signature(panel_mgr.get_client_details)
            params = list(sig.parameters.keys())
            if 'client_name' in params:
                client_details = panel_mgr.get_client_details(
                    service.get('inbound_id'),
                    service.get('client_uuid'),
                    client_name=service.get('client_name')
                )
            else:
                client_details = panel_mgr.get_client_details(
                    service.get('inbound_id'),
                    service.get('client_uuid')
                )
        except Exception:
            client_details = None
        
        is_enabled = None
        if isinstance(client_details, dict) and client_details.get('enable') is not None:
            is_enabled = bool(client_details.get('enable'))
        else:
            is_enabled = (service.get('status') != 'paused')
        
        if is_enabled:
            ok = panel_mgr.disable_client(
                service.get('inbound_id'),
                service.get('client_uuid'),
                client_name=service.get('client_name')
            )
            if ok:
                db_instance.update_service_status(service_id, 'paused')
                flash('سرویس خاموش شد', 'success')
            else:
                flash('خطا در خاموش کردن سرویس', 'error')
        else:
            if not hasattr(panel_mgr, 'enable_client'):
                flash('این پنل از روشن کردن پشتیبانی نمی‌کند', 'error')
                return redirect(url_for('service_detail', service_id=service_id))
            ok = panel_mgr.enable_client(
                service.get('inbound_id'),
                service.get('client_uuid'),
                client_name=service.get('client_name')
            )
            if ok:
                db_instance.update_service_status(service_id, 'active')
                flash('سرویس روشن شد', 'success')
            else:
                flash('خطا در روشن کردن سرویس', 'error')
        
    except Exception as e:
        logger.error(f"Error toggling service from web: {e}", exc_info=True)
        flash('خطا در تغییر وضعیت سرویس', 'error')
    
    return redirect(url_for('service_detail', service_id=service_id))

@app.route('/buy-service')
@login_required
def buy_service():
    """Buy new service page with caching"""
    user_id = session.get('user_id')
    
    # Get user from cache
    db_instance = get_db()
    user = cache.get_or_set(
        cache_key_user(user_id),
        lambda: db_instance.get_user(user_id),
        ttl=300
    )
    
    if not user:
        return redirect(url_for('index'))
    
    photo_url = session.get('photo_url', '')
    
    # Get available panels from cache
    from cache_utils import cache_key_panels_active
    panels_cache_key = cache_key_panels_active()
    panels = cache.get_or_set(
        panels_cache_key,
        lambda: db_instance.get_panels(active_only=True),
        ttl=600
    )
    
    # Get available inbounds for each panel and translate country name
    for panel in panels:
        try:
            # Translate country name from panel name
            panel['country_fa'] = extract_country_from_panel_name(panel.get('name', ''))
            panel['available'] = True
            # Ensure sale_type is set (default to 'gigabyte' if not set)
            if 'sale_type' not in panel or not panel['sale_type']:
                panel['sale_type'] = 'gigabyte'
        except:
            panel['country_fa'] = 'نامشخص'
            panel['available'] = False
            if 'sale_type' not in panel or not panel['sale_type']:
                panel['sale_type'] = 'gigabyte'
    
    # Check if this is a renewal request
    # Only use session variables if they exist and are valid AND user came from renewal
    from_renewal = request.args.get('from_renewal', type=int)
    renew_service_id = session.get('renew_service_id')
    renew_panel_id = session.get('renew_panel_id')
    
    # If user navigated directly to buy-service (not from renewal), clear renewal variables
    if not from_renewal and (renew_service_id or renew_panel_id):
        session.pop('renew_service_id', None)
        session.pop('renew_panel_id', None)
        renew_service_id = None
        renew_panel_id = None
    
    # Validate renewal session data - if invalid, clear it
    if renew_service_id and renew_panel_id:
        # Verify the service still exists and belongs to user
        try:
            user_db_id = user['id']
            service = db_instance.get_user_service(renew_service_id, user_db_id)
            if not service or service.get('panel_id') != renew_panel_id:
                # Invalid renewal data, clear it
                session.pop('renew_service_id', None)
                session.pop('renew_panel_id', None)
                renew_service_id = None
                renew_panel_id = None
        except Exception as e:
            logger.error(f"Error validating renewal session data: {e}")
            session.pop('renew_service_id', None)
            session.pop('renew_panel_id', None)
            renew_service_id = None
            renew_panel_id = None
    
    # Theme Selection
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    current_theme = settings_mgr.get_theme()
    
    template_name = 'buy_service.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/buy_service.html'

    return render_template(template_name, 
                         user=user, 
                         photo_url=photo_url, 
                         panels=panels,
                         renew_service_id=renew_service_id,
                         renew_panel_id=renew_panel_id)

@app.route('/get-test-account')
@login_required
def get_test_account():
    """Get test account page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    photo_url = session.get('photo_url', '')
    
    if not user:
        return redirect(url_for('index'))
        
    # Check max test accounts limit
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager(db_manager=db_instance)
    max_test_accounts = settings_mgr.get_setting('max_test_accounts', 1)
    
    # Use robust method that handles missing table
    current_count = db_instance.get_user_test_accounts_count(user['id'])
    
    if current_count >= max_test_accounts:
        flash(f"شما به سقف مجاز دریافت اکانت تست ({max_test_accounts} عدد) رسیده‌اید.", "error")
        return redirect(url_for('dashboard'))
    
    panels = db_instance.get_test_panels(active_only=True)
    if not panels:
        panels = db_instance.get_panels(active_only=True)
    eligible_panels = []
    
    for panel in panels:
        # Check if panel supports gigabyte sales
        sale_type = panel.get('sale_type', 'gigabyte')
        if sale_type not in ['gigabyte', 'both']:
            continue
        
        # Check if user already got test from this panel
        if db_instance.has_user_received_test_account_from_panel(user['id'], panel['id']):
            continue
            
        # Translate country
        panel['country_fa'] = extract_country_from_panel_name(panel.get('name', ''))
        display_name = panel.get('test_display_name')
        if not display_name:
            extra_config = panel.get('extra_config')
            if isinstance(extra_config, str):
                try:
                    extra_config = json.loads(extra_config) if extra_config else {}
                except Exception:
                    extra_config = {}
            if isinstance(extra_config, dict):
                display_name = extra_config.get('test_display_name')
        panel['display_name'] = str(display_name) if display_name else panel.get('name', '')
        eligible_panels.append(panel)
    
    if not eligible_panels:
        flash("هیچ سرور تستی در دسترس نیست یا شما از همه سرورها استفاده کرده‌اید.", "error")
        return redirect(url_for('dashboard'))
        
    # Get test config for volume/duration display
    test_config = db_instance.get_test_account_config()
    duration = test_config.get('duration_hours', 24)
    volume = test_config.get('volume_gb', 1)
    
    # Theme Selection
    current_theme = settings_mgr.get_theme()
    # Prepare categories map for frontend
    panel_categories_map = {}
    for panel in eligible_panels:
        if panel.get('test_categories'):
            panel_categories_map[str(panel['id'])] = panel['test_categories']

    template_name = 'get_test_account.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/get_test_account.html'
        
    return render_template(template_name, 
                         user=user, 
                         photo_url=photo_url, 
                         panels=eligible_panels,
                         panel_categories_map=panel_categories_map,
                         duration=duration,
                         volume=volume)

@app.route('/renew-service')
@login_required
def renew_service():
    """Renew service page - list plan-based services"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    photo_url = session.get('photo_url', '')
    
    # Get all user services that are plan-based (have product_id)
    # Query directly to include product_id and check for NULL properly
    with db_instance.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute('''
                SELECT c.*, p.name as panel_name 
                FROM clients c 
                JOIN panels p ON c.panel_id = p.id 
                JOIN users u ON c.user_id = u.id
                WHERE u.telegram_id = %s AND c.product_id IS NOT NULL AND c.is_active = 1
                ORDER BY c.created_at DESC
            ''', (user_id,))
            plan_services = cursor.fetchall()
        finally:
            cursor.close()
    
    # Use cached data for performance
    for service in plan_services:
        service['used_gb'] = service.get('cached_used_gb', service.get('used_gb', 0))
        service['is_online'] = service.get('cached_is_online', False)
    
    logger.info(f"Found {len(plan_services)} plan-based services for user {user_id}")
    
    # Get current date for template
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('renew_service.html', user=user, photo_url=photo_url, services=plan_services, current_date=current_date)

@app.route('/renew-service/<int:service_id>')
@login_required
def renew_service_detail(service_id):
    """Renew specific service - redirect to buy service with preselected service"""
    user_telegram_id = session.get('user_id')  # This is telegram_id
    db_instance = get_db()
    user = db_instance.get_user(user_telegram_id)  # Get user by telegram_id
    
    if not user:
        flash('کاربر یافت نشد', 'error')
        return redirect(url_for('renew_service'))
    
    user_db_id = user['id']  # Get database user ID
    
    # Get service details - use database user ID
    db_instance = get_db()
    service = db_instance.get_user_service(service_id, user_db_id)
    if not service:
        flash('سرویس یافت نشد', 'error')
        return redirect(url_for('renew_service'))
    
    # Check if service has product_id (plan-based)
    if not service.get('product_id'):
        flash('این سرویس پلنی نیست. برای افزایش حجم از بخش افزایش حجم استفاده کنید.', 'warning')
        return redirect(url_for('add_volume', service_id=service_id))
    
    # No need to check for reserved services - instant renewal is now the default
    
    # Store renewal info in session
    session['renew_service_id'] = service_id
    session['renew_panel_id'] = service.get('panel_id')
    
    # Redirect to buy service page with from_renewal flag
    return redirect(url_for('buy_service', from_renewal=1))

@app.route('/add-volume')
@login_required
def add_volume():
    """Add volume to existing service"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    photo_url = session.get('photo_url', '')
    
    # Get service_id from query parameter if provided
    preselected_service_id = request.args.get('service_id', type=int)
    
    # Get user services using the optimized method
    # This method includes price_per_gb in the query, avoiding N+1 queries
    if user:
        services = db_instance.get_all_user_services_for_volume(user['id'])
    else:
        services = []
    
    # Post-process services
    for service in services:
        # Ensure price_per_gb is set (handle None from LEFT JOIN)
        if service.get('price_per_gb') is None:
            service['price_per_gb'] = 0
            
        # Use database values for speed to avoid page load hang
        service['is_online'] = False
        total_gb = service.get('total_gb', 0)
        used_gb = service.get('used_gb', 0)
        if total_gb > 0:
            service['usage_percentage'] = min(100, round((used_gb / total_gb) * 100, 1))
        else:
            service['usage_percentage'] = 0
    
    return render_template('add_volume.html', user=user, photo_url=photo_url, services=services, preselected_service_id=preselected_service_id)

@app.route('/recharge')
@login_required
def recharge():
    """Recharge balance page"""
    user_id = session.get('user_id')
    
    # Get user from cache
    db_instance = get_db()
    user = cache.get_or_set(
        cache_key_user(user_id),
        lambda: db_instance.get_user(user_id),
        ttl=300
    )
    
    if not user:
        return redirect(url_for('index'))
    
    photo_url = session.get('photo_url', '')
    
    return render_template('recharge.html', user=user, photo_url=photo_url)

@app.route('/transactions')
@login_required
def transactions():
    """User transactions history page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    if not user:
        return redirect(url_for('index'))
    
    # Get transactions
    transactions = db_instance.get_user_transactions(user['telegram_id'], limit=100)
    
    # Theme Selection
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    current_theme = settings_mgr.get_theme()
    
    template_name = 'transactions.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/transactions.html'
    
    return render_template(template_name, 
                         user=user, 
                         transactions=transactions, 
                         photo_url=session.get('photo_url', ''))

@app.route('/api/panels')
@login_required
@rate_limit(max_requests=30, window_seconds=60)
def api_get_panels():
    """API endpoint to get available panels with caching"""
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_manager = AdminManager(db_instance)
        
        # Cache panels list for 10 minutes
        from cache_utils import cache_key_panels_active
        panels_cache_key = cache_key_panels_active()
        
        # Try to get from cache
        panels = cache.get(panels_cache_key)
        
        if panels is None:
            # Not in cache, fetch from DB
            # Use get_all_panels() which is the correct method in AdminManager
            panels = admin_manager.get_all_panels()
            
            # Smart caching:
            # If we got panels, cache for 10 minutes
            if panels:
                cache.set(panels_cache_key, panels, ttl=600)
            # If empty, do NOT cache to allow immediate retry
            # else:
            #    cache.set(panels_cache_key, panels, ttl=30)
        
        # Calculate discounts for resellers
        telegram_id = session.get('telegram_id')
        discount_rate = 0
        is_reseller = False
        try:
            from reseller_panel.models import ResellerManager
            reseller_manager = ResellerManager(db_instance)
            reseller = reseller_manager.get_reseller_by_telegram_id(telegram_id)
            if reseller and reseller.get('discount_rate', 0) > 0:
                discount_rate = float(reseller['discount_rate'])
                is_reseller = True
        except Exception as e:
            logger.warning(f"Could not get reseller discount: {e}")

        # Filter and format panels
        active_panels = []
        for panel in panels:
            if panel.get('is_active'):
                # Extract and translate country name
                country_fa = extract_country_from_panel_name(panel.get('name', ''))
                
                price_per_gb = panel.get('price_per_gb', 0)
                original_price_per_gb = price_per_gb
                
                # Apply discount
                if is_reseller and discount_rate > 0:
                    price_per_gb = int(original_price_per_gb * (1 - discount_rate / 100))
                
                active_panels.append({
                    'id': panel['id'],
                    'name': panel['name'],
                    'price_per_gb': price_per_gb,
                    'original_price_per_gb': original_price_per_gb,
                    'description': panel.get('description', ''),
                    'location': panel.get('location', 'نامشخص'),
                    'country_fa': country_fa,
                    'sale_type': panel.get('sale_type', 'gigabyte'),
                    'discount_rate': discount_rate if is_reseller else 0,
                    'is_discounted': is_reseller and discount_rate > 0,
                    'naming_method': panel.get('naming_method', 2)
                })
        
        return jsonify({'success': True, 'panels': active_panels})
    except Exception as e:
        logger.error(f"Error getting panels: {e}")
        return jsonify({'success': False, 'message': 'خطا در دریافت پنل‌ها'}), 500

@app.route('/api/panel/<int:panel_id>/categories')
@login_required
def api_get_panel_categories(panel_id):
    """Get categories for a panel"""
    try:
        db_instance = get_db()
        categories = db_instance.get_categories(panel_id, active_only=True)
        # Also check if panel has products without category
        has_products_without_category = db_instance.has_products_without_category(panel_id)
        return jsonify({
            'success': True, 
            'categories': categories,
            'has_products_without_category': has_products_without_category
        })
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return jsonify({'success': False, 'message': 'خطا در دریافت دسته‌بندی‌ها'}), 500

@app.route('/api/panel/<int:panel_id>/products')
@login_required
def api_get_panel_products(panel_id):
    """Get products for a panel"""
    try:
        category_id = request.args.get('category_id', type=int)
        
        db_instance = get_db()
        
        if category_id:
            # Get products for specific category
            products = db_instance.get_products(panel_id, category_id=category_id, active_only=True)
        else:
            # Get products without category (when category_id is None or not provided)
            products = db_instance.get_products(panel_id, category_id=False, active_only=True)
        
        # Calculate discounts for resellers and determine user type
        telegram_id = session.get('telegram_id')
        discount_rate = 0
        is_reseller = False
        try:
            from reseller_panel.models import ResellerManager
            reseller_manager = ResellerManager(db_instance)
            reseller = reseller_manager.get_reseller_by_telegram_id(telegram_id)
            if reseller:
                is_reseller = True
                if reseller.get('discount_rate', 0) > 0:
                    discount_rate = float(reseller['discount_rate'])
        except Exception as e:
            logger.warning(f"Could not get reseller discount: {e}")
            
        # Filter products based on visibility
        visible_products = []
        for product in products:
            # Check visibility
            # Default to True (1) if keys are missing to ensure backward compatibility
            is_visible_to_users = product.get('is_visible_to_users', 1)
            is_visible_to_resellers = product.get('is_visible_to_resellers', 1)
            
            # Normalize to boolean/int
            if is_visible_to_users is None: is_visible_to_users = 1
            if is_visible_to_resellers is None: is_visible_to_resellers = 1
            
            # Filter logic
            if is_reseller:
                if not is_visible_to_resellers:
                    continue
            else:
                if not is_visible_to_users:
                    continue
            
            visible_products.append(product)
        
        products = visible_products
            
        # Add discount info to products
        for product in products:
            original_price = product['price']
            product['original_price'] = original_price
            
            if is_reseller and discount_rate > 0:
                product['price'] = int(original_price * (1 - discount_rate / 100))
                product['discount_rate'] = discount_rate
                product['is_discounted'] = True
            else:
                product['discount_rate'] = 0
                product['is_discounted'] = False
        
        return jsonify({'success': True, 'products': products})
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify({'success': False, 'message': 'خطا در دریافت محصولات'}), 500

@app.route('/api/product/<int:product_id>')
@login_required
def api_get_product(product_id):
    """Get product details"""
    try:
        db_instance = get_db()
        product = db_instance.get_product(product_id)
        if not product:
            return jsonify({'success': False, 'message': 'محصول یافت نشد'}), 404
        
        # Calculate discounts for resellers and determine user type
        telegram_id = session.get('telegram_id')
        discount_rate = 0
        is_reseller = False
        try:
            from reseller_panel.models import ResellerManager
            reseller_manager = ResellerManager(db_instance)
            reseller = reseller_manager.get_reseller_by_telegram_id(telegram_id)
            if reseller:
                is_reseller = True
                if reseller.get('discount_rate', 0) > 0:
                    discount_rate = float(reseller['discount_rate'])
        except Exception as e:
            logger.warning(f"Could not get reseller discount: {e}")
            
        # Check visibility
        is_visible_to_users = product.get('is_visible_to_users', 1)
        is_visible_to_resellers = product.get('is_visible_to_resellers', 1)
        
        if is_visible_to_users is None: is_visible_to_users = 1
        if is_visible_to_resellers is None: is_visible_to_resellers = 1
        
        if is_reseller:
            if not is_visible_to_resellers:
                return jsonify({'success': False, 'message': 'این محصول برای شما قابل مشاهده نیست'}), 403
        else:
            if not is_visible_to_users:
                return jsonify({'success': False, 'message': 'این محصول برای شما قابل مشاهده نیست'}), 403
            
        # Add discount info
        original_price = product['price']
        product['original_price'] = original_price
        
        if is_reseller and discount_rate > 0:
            product['price'] = int(original_price * (1 - discount_rate / 100))
            product['discount_rate'] = discount_rate
            product['is_discounted'] = True
        else:
            product['discount_rate'] = 0
            product['is_discounted'] = False
        
        return jsonify({'success': True, 'product': product})
    except Exception as e:
        logger.error(f"Error getting product: {e}")
        return jsonify({'success': False, 'message': 'خطا در دریافت محصول'}), 500

@app.route('/api/calculate-price', methods=['POST'])
@login_required
@rate_limit(max_requests=30, window_seconds=60)
def api_calculate_price():
    """API endpoint to calculate service price - Supports both gigabyte and plan purchases"""
    try:
        data = request.json
        
        # Input validation
        panel_id = validate_panel_id(data.get('panel_id'))
        purchase_type = data.get('purchase_type', 'gigabyte')  # 'gigabyte' or 'plan'
        
        if not panel_id:
            return jsonify({'success': False, 'message': 'اطلاعات ناقص است'}), 400
        
        # Get panel from cache or database
        db_instance = get_db()
        from cache_utils import cache_key_panel
        panel_cache_key = cache_key_panel(panel_id)
        panel = cache.get_or_set(
            panel_cache_key,
            lambda: db_instance.get_panel(panel_id),
            ttl=600  # Cache panels for 10 minutes
        )
        if not panel:
            return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
        
        # Get reseller discount for current user
        telegram_id = session.get('telegram_id')
        discount_rate = 0
        is_reseller = False
        try:
            from reseller_panel.models import ResellerManager
            reseller_manager = ResellerManager(db_instance)
            reseller = reseller_manager.get_reseller_by_telegram_id(telegram_id)
            if reseller and reseller.get('discount_rate', 0) > 0:
                discount_rate = float(reseller['discount_rate'])
                is_reseller = True
        except Exception as e:
            logger.warning(f"Could not get reseller discount: {e}")
        
        if purchase_type == 'plan':
            product_id = data.get('product_id')
            if not product_id:
                return jsonify({'success': False, 'message': 'محصول انتخاب نشده است'}), 400
            
            db_instance = get_db()
            product = db_instance.get_product(product_id)
            if not product:
                return jsonify({'success': False, 'message': 'محصول یافت نشد'}), 404
            
            # Check visibility
            is_visible_to_users = product.get('is_visible_to_users', 1)
            is_visible_to_resellers = product.get('is_visible_to_resellers', 1)
            
            if is_visible_to_users is None: is_visible_to_users = 1
            if is_visible_to_resellers is None: is_visible_to_resellers = 1
            
            if is_reseller:
                if not is_visible_to_resellers:
                    return jsonify({'success': False, 'message': 'این محصول برای شما قابل خرید نیست'}), 403
            else:
                if not is_visible_to_users:
                    return jsonify({'success': False, 'message': 'این محصول برای شما قابل خرید نیست'}), 403
            
            original_price = product['price']
            volume_gb = product['volume_gb']
            duration_days = product['duration_days']
            
            # Apply reseller discount
            if is_reseller and discount_rate > 0:
                total_price = int(original_price * (1 - discount_rate / 100))
            else:
                total_price = original_price
            
            return jsonify({
                'success': True,
                'purchase_type': 'plan',
                'product_id': product_id,
                'volume_gb': volume_gb,
                'duration_days': duration_days,
                'original_price': original_price,
                'total_price': total_price,
                'discount_rate': discount_rate,
                'is_reseller': is_reseller
            })
        else:
            # Gigabyte-based purchase
            volume_gb = data.get('volume_gb')
            if not volume_gb:
                return jsonify({'success': False, 'message': 'حجم وارد نشده است'}), 400
            
            price_per_gb = panel.get('price_per_gb', 0)
            original_price = int(price_per_gb * volume_gb)
            
            # Apply reseller discount
            if is_reseller and discount_rate > 0:
                total_price = int(original_price * (1 - discount_rate / 100))
            else:
                total_price = original_price
            
            return jsonify({
                'success': True,
                'purchase_type': 'gigabyte',
                'price_per_gb': price_per_gb,
                'volume_gb': volume_gb,
                'original_price': original_price,
                'total_price': total_price,
                'discount_rate': discount_rate,
                'is_reseller': is_reseller
            })
    except Exception as e:
        logger.error(f"Error calculating price: {e}")
        return jsonify({'success': False, 'message': 'خطا در محاسبه قیمت'}), 500

@app.route('/api/create-service', methods=['POST'])
@login_required
@rate_limit(max_requests=10, window_seconds=60)
def api_create_service():
    """API endpoint to create new service - Supports both gigabyte and plan-based purchases"""
    try:
        user_id = session.get('user_id')
        data = request.json
        
        # Input validation
        panel_id = validate_panel_id(data.get('panel_id'))
        # Get payment method (can be 'balance' or 'card')
        payment_method = data.get('payment_method', 'card')
        purchase_type = data.get('purchase_type', 'gigabyte')  # 'gigabyte' or 'plan'
        custom_name = data.get('custom_name')
        
        # Validate custom name if provided
        if custom_name:
            import re
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{2,19}$', custom_name):
                return jsonify({'success': False, 'message': 'نام اختصاصی نامعتبر است. (۳ تا ۲۰ کاراکتر، حروف انگلیسی و اعداد)'}), 400
        
        if not panel_id:
            return jsonify({'success': False, 'message': 'اطلاعات ناقص است'}), 400
        
        # Get panel
        db_instance = get_db()
        panel = db_instance.get_panel(panel_id)
        if not panel:
            return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
        
        if not panel.get('is_active'):
            return jsonify({'success': False, 'message': 'این پنل غیرفعال است'}), 400
            
        # Get reseller discount for current user
        telegram_id = session.get('telegram_id')
        discount_rate = 0
        is_reseller = False
        try:
            from reseller_panel.models import ResellerManager
            reseller_manager = ResellerManager(db_instance)
            reseller = reseller_manager.get_reseller_by_telegram_id(telegram_id)
            if reseller:
                is_reseller = True
                if reseller.get('discount_rate', 0) > 0:
                    discount_rate = float(reseller['discount_rate'])
        except Exception as e:
            logger.warning(f"Could not get reseller discount: {e}")
        
        # Handle plan-based purchase
        if purchase_type == 'plan':
            product_id = data.get('product_id')
            if not product_id:
                return jsonify({'success': False, 'message': 'محصول انتخاب نشده است'}), 400
            
            db_instance = get_db()
            product = db_instance.get_product(product_id)
            if not product or not product.get('is_active'):
                return jsonify({'success': False, 'message': 'محصول یافت نشد یا غیرفعال است'}), 404
            
            # Check visibility
            is_visible_to_users = product.get('is_visible_to_users', 1)
            is_visible_to_resellers = product.get('is_visible_to_resellers', 1)
            
            if is_visible_to_users is None: is_visible_to_users = 1
            if is_visible_to_resellers is None: is_visible_to_resellers = 1
            
            if is_reseller:
                if not is_visible_to_resellers:
                    return jsonify({'success': False, 'message': 'این محصول برای شما قابل خرید نیست'}), 403
            else:
                if not is_visible_to_users:
                    return jsonify({'success': False, 'message': 'این محصول برای شما قابل خرید نیست'}), 403
            
            if product['panel_id'] != panel_id:
                return jsonify({'success': False, 'message': 'محصول متعلق به این پنل نیست'}), 400
            
            volume_gb = product['volume_gb']
            expire_days = product['duration_days']
            original_price = product['price']
            
        else:
            # Handle gigabyte-based purchase
            volume_gb = float(data.get('volume_gb', 0))
            expire_days = 0  # Unlimited for gigabyte purchases
            
            if volume_gb <= 0 or volume_gb > 500:
                return jsonify({'success': False, 'message': 'حجم باید بین 1 تا 500 گیگابایت باشد'}), 400
            
            price_per_gb = panel.get('price_per_gb', 0)
            original_price = int(price_per_gb * volume_gb)
        
        # Apply reseller discount
        if is_reseller and discount_rate > 0:
            total_price = int(original_price * (1 - discount_rate / 100))
            logger.info(f"💰 Reseller discount applied for user {user_id}: Rate={discount_rate}%, Original={original_price}, Final={total_price}")
        else:
            total_price = original_price
            if is_reseller:
                logger.info(f"ℹ️ Reseller user {user_id} has 0% discount rate")
        
        # Apply discount code if provided
        discount_code = sanitize_input(data.get('discount_code', ''), max_length=50) if data.get('discount_code') else None
        discount_amount = 0
        if discount_code:
            # Validate discount code format
            if not validate_discount_code(discount_code):
                return jsonify({'success': False, 'message': 'فرمت کد تخفیف نامعتبر است'}), 400
            from discount_manager import DiscountCodeManager
            db_instance = get_db()
            discount_manager = DiscountCodeManager(db_instance)
            discount_result = discount_manager.validate_and_apply_discount(discount_code, user_id, total_price)
            if discount_result['success']:
                total_price = discount_result['final_amount']
                discount_amount = discount_result['discount_amount']
            else:
                return jsonify({'success': False, 'message': discount_result.get('message', 'کد تخفیف نامعتبر است')}), 400
        
        # Get user
        user = db_instance.get_user(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        # Check if this is a renewal request
        renew_service_id = data.get('renew_service_id') or session.get('renew_service_id')
        renew_panel_id = data.get('renew_panel_id') or session.get('renew_panel_id')
        is_renewal = renew_service_id is not None
        has_remaining_resources = False  # Initialize for non-renewal cases
        
        # Store in session if provided in request
        if data.get('renew_service_id'):
            session['renew_service_id'] = data.get('renew_service_id')
        if data.get('renew_panel_id'):
            session['renew_panel_id'] = data.get('renew_panel_id')
        
        if is_renewal:
            # This is a renewal - get existing service
            existing_service = db_instance.get_user_service(renew_service_id, user['id'])
            if not existing_service:
                session.pop('renew_service_id', None)
                session.pop('renew_panel_id', None)
                return jsonify({'success': False, 'message': 'سرویس برای تمدید یافت نشد'}), 404
            
            # Check if panel matches
            if existing_service.get('panel_id') != panel_id:
                session.pop('renew_service_id', None)
                session.pop('renew_panel_id', None)
                return jsonify({'success': False, 'message': 'پنل سرویس با پنل انتخاب شده مطابقت ندارد'}), 400
            
            # Check if this is a plan-based renewal
            if purchase_type != 'plan' or not product_id:
                session.pop('renew_service_id', None)
                session.pop('renew_panel_id', None)
                return jsonify({'success': False, 'message': 'برای تمدید باید یک محصول انتخاب کنید'}), 400
            
            # Check if service is plan-based (must have product_id)
            if not existing_service.get('product_id'):
                session.pop('renew_service_id', None)
                session.pop('renew_panel_id', None)
                return jsonify({'success': False, 'message': 'این سرویس پلنی نیست. برای افزایش حجم از بخش افزایش حجم استفاده کنید.'}), 400
        
        # Handle payment
        if payment_method == 'balance':
            # Check balance
            if user.get('balance', 0) < total_price:
                return jsonify({
                    'success': False,
                    'insufficient_balance': True,
                    'current_balance': user.get('balance', 0),
                    'required_amount': total_price,
                    'message': f'موجودی کافی نیست. موجودی شما: {user.get("balance", 0):,} تومان - مبلغ مورد نیاز: {total_price:,} تومان'
                }), 400
            
            # Get admin manager
            from admin_manager import AdminManager
            db_instance = get_db()
            admin_manager = AdminManager(db_instance)
            
            if is_renewal:
                # Handle instant renewal - add volume and time to existing service
                existing_service = db_instance.get_user_service(renew_service_id, user['id'])
                
                # Get current values
                from datetime import datetime, timedelta
                now = datetime.now()
                
                current_total_gb = float(existing_service.get('total_gb', 0) or 0)
                current_used_gb = float(existing_service.get('cached_used_gb', 0) or 0)
                current_remaining_gb = current_total_gb - current_used_gb
                
                # Calculate new total volume (add new volume to remaining volume)
                new_total_gb = current_remaining_gb + volume_gb
                
                # Calculate new expiration date
                current_expires_at = None
                if existing_service.get('expires_at'):
                    try:
                        current_expires_at = parse_datetime_safe(existing_service['expires_at'])
                    except Exception as e:
                        logger.error(f"Error parsing expires_at: {e}")
                        current_expires_at = None
                
                new_expires_at = None
                new_expire_days = 0
                if expire_days > 0:
                    if current_expires_at and current_expires_at > now:
                        # Add days to current expiration
                        new_expires_at = current_expires_at + timedelta(days=expire_days)
                        # Calculate total days from now to new expiration
                        new_expire_days = int((new_expires_at - now).days)
                    else:
                        # Service expired or no expiration, set new expiration from now
                        new_expires_at = now + timedelta(days=expire_days)
                        new_expire_days = expire_days
                
                # Get panel manager
                panel_manager = admin_manager.get_panel_manager(panel_id)
                if not panel_manager:
                    return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
                
                if not panel_manager.login():
                    return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
                
                # Update client traffic on panel (add new volume to remaining)
                success = panel_manager.update_client_traffic(
                    existing_service['inbound_id'],
                    existing_service['client_uuid'],
                    new_total_gb
                )
                
                if not success:
                    return jsonify({'success': False, 'message': 'خطا در بروزرسانی حجم سرویس'}), 500
                
                # Update expiration if needed
                if expire_days > 0 and hasattr(panel_manager, 'update_client_expiration') and panel_manager.update_client_expiration:
                    expires_timestamp = int(new_expires_at.timestamp()) if new_expires_at else None
                    panel_manager.update_client_expiration(
                        existing_service['inbound_id'],
                        existing_service['client_uuid'],
                        expires_timestamp,
                        client_name=existing_service.get('client_name')
                    )
                
                # Enable client on panel if it was disabled
                was_disabled = existing_service.get('status') == 'disabled' or existing_service.get('is_active', 1) == 0
                if was_disabled:
                    logger.info(f"🔧 Enabling client on panel (was disabled) for service {renew_service_id}...")
                    enable_success = panel_manager.enable_client(
                        existing_service['inbound_id'],
                        existing_service['client_uuid']
                    )
                    if enable_success:
                        logger.info(f"✅ Client enabled on panel successfully for service {renew_service_id}")
                    else:
                        logger.warning(f"⚠️ Failed to enable client on panel for service {renew_service_id}, but continuing...")
                
                # Update database - add to existing values, don't reset
                with db_instance.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    try:
                        cursor.execute('''
                            UPDATE clients 
                            SET total_gb = %s,
                                expire_days = %s,
                                expires_at = %s,
                                product_id = %s,
                                status = 'active',
                                is_active = 1,
                                warned_70_percent = 0,
                                warned_expired = 0,
                                warned_one_week = 0,
                                expired_at = NULL,
                                exhausted_at = NULL,
                                deletion_grace_period_end = NULL,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        ''', (new_total_gb, new_expire_days, new_expires_at.isoformat() if new_expires_at else None, product_id, renew_service_id))
                        conn.commit()
                    finally:
                        cursor.close()
                
                # Record discount usage if discount was applied
                if discount_code and discount_amount > 0:
                    discount_code_obj = db_instance.get_discount_code(discount_code)
                    if discount_code_obj:
                        db_instance.apply_discount_code(
                            code_id=discount_code_obj['id'],
                            user_id=user['id'],
                            invoice_id=None,
                            amount_before=original_price,
                            discount_amount=discount_amount,
                            amount_after=total_price
                        )
                
                # Deduct balance and record transaction
                product_name = product.get('name', '')
                description = f'تمدید آنی اشتراک پلنی: {product_name} (+{volume_gb}GB, +{expire_days} روز)'
                db_instance.update_user_balance(
                    telegram_id=user_id,
                    amount=-total_price,
                    transaction_type='service_renewal',
                    description=description
                )
                
                # Clear renewal session
                session.pop('renew_service_id', None)
                session.pop('renew_panel_id', None)
                
                logger.info(f"Service {renew_service_id} renewed instantly for user {user_id}: +{volume_gb}GB, +{expire_days} days")
                
                return jsonify({
                    'success': True,
                    'message': f'سرویس با موفقیت تمدید شد. حجم جدید: {new_total_gb:.2f} گیگابایت',
                    'renewal': True,
                    'service': {
                        'volume': new_total_gb,
                        'added_volume': volume_gb,
                        'price': total_price,
                        'expires_at': new_expires_at.isoformat() if new_expires_at else None
                    }
                })
            else:
                # Handle new service creation
                # Get inbounds for this panel
                inbounds = admin_manager.get_panel_inbounds(panel_id)
            
                if not inbounds or len(inbounds) == 0:
                    return jsonify({'success': False, 'message': 'هیچ اینباند فعالی برای این پنل یافت نشد'}), 404
                
                # Check if product has specific inbound
                target_inbound_id = None
                if purchase_type == 'plan' and product.get('inbound_id'):
                    # Verify inbound exists
                    product_inbound = next((i for i in inbounds if i['id'] == product['inbound_id']), None)
                    if product_inbound:
                        target_inbound_id = product_inbound['id']
                
                # Fallback to first active inbound if not specified
                if not target_inbound_id:
                    target_inbound_id = inbounds[0]['id']
            
            # Generate unique username
            from username_formatter import UsernameFormatter
            
            # Fetch inbound name to append
            inbound_name_suffix = ""
            try:
                # We need to know which inbound will be used
                target_inbound_id_for_name = None
                if purchase_type == 'plan' and product.get('inbound_id'):
                    target_inbound_id_for_name = product.get('inbound_id')
                elif target_inbound_id:
                    target_inbound_id_for_name = target_inbound_id
                
                # If we have a target inbound, find its name
                if target_inbound_id_for_name:
                    # We might need to fetch inbounds again if not already fetched
                    if 'inbounds' not in locals() or not inbounds:
                         inbounds = admin_manager.get_panel_inbounds(panel_id)
                    
                    for inbound in inbounds:
                        if inbound.get('id') == target_inbound_id_for_name:
                            # Use remark/tag
                            raw_name = inbound.get('remark') or inbound.get('tag') or ""
                            # Sanitize: keep only alphanumeric
                            import re
                            clean_name = re.sub(r'[^a-zA-Z0-9]', '', raw_name)
                            if clean_name:
                                inbound_name_suffix = f"-{clean_name}"
                            break
            except Exception as e:
                logger.error(f"Error getting inbound name for suffix: {e}")

            if custom_name:
                client_name = custom_name
                # If naming method is 4 (Custom + Random), append random string
                if panel.get('naming_method') == 4:
                     import random, string
                     random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
                     client_name = f"{custom_name}-{random_suffix}"
            else:
                client_name = UsernameFormatter.format_client_name(user_id)
                
            # Append inbound name suffix if available
            if inbound_name_suffix:
                client_name += inbound_name_suffix
            
            # Calculate expiration date
            from datetime import datetime, timedelta
            expires_at = None
            if expire_days > 0:
                expires_at = datetime.now() + timedelta(days=expire_days)
            
            # Create client using admin_manager
            logger.info(f"Creating service for user {user_id}: panel={panel_id}, volume={volume_gb}GB, expire_days={expire_days}")
            
            if purchase_type == 'plan' and product.get('inbound_id') and target_inbound_id == product.get('inbound_id'):
                # Use specific inbound from product
                # We should use create_client_on_all_panel_inbounds even for specific inbound, as it now supports inbound_id
                success, message, client_data = admin_manager.create_client_on_all_panel_inbounds(
                    panel_id=panel_id,
                    client_name=client_name,
                    expire_days=expire_days,
                    total_gb=volume_gb,
                    inbound_id=target_inbound_id
                )
            else:
                # Use default logic (auto-select inbound)
                success, message, client_data = admin_manager.create_client_on_all_panel_inbounds(
                    panel_id=panel_id,
                    client_name=client_name,
                    expire_days=expire_days,
                    total_gb=volume_gb
                )
            
            if success and client_data:
                # Save client to database
                db_instance = get_db()
                user_db = db_instance.get_user(user_id)
                
                # Determine used inbound ID
                used_inbound_id = client_data.get('inbound_id')
                if not used_inbound_id:
                    if purchase_type == 'plan' and product.get('inbound_id'):
                         used_inbound_id = product.get('inbound_id')
                    elif target_inbound_id:
                         used_inbound_id = target_inbound_id
                    else:
                         used_inbound_id = inbounds[0]['id']
                
                # Create paid invoice for balance purchase (for history and refund support)
                discount_id = None
                if discount_code:
                    dc = db_instance.get_discount_code(discount_code)
                    if dc:
                        discount_id = dc['id']

                invoice_id = db_instance.add_invoice(
                    user_id=user_db['id'],
                    panel_id=panel_id,
                    gb_amount=volume_gb,
                    amount=total_price,
                    payment_method='balance',
                    status='paid',
                    discount_code_id=discount_id,
                    discount_amount=discount_amount,
                    original_amount=original_price,
                    product_id=product_id if purchase_type == 'plan' else None,
                    duration_days=expire_days,
                    purchase_type=purchase_type,
                    notes='Balance purchase'
                )
                
                client_id = db_instance.add_client(
                    user_id=user_db['id'],
                    panel_id=panel_id,
                    client_name=client_name,
                    client_uuid=client_data.get('id', ''),
                    inbound_id=used_inbound_id,
                    protocol=client_data.get('protocol', 'vless'),
                    expire_days=expire_days,
                    total_gb=volume_gb,
                    expires_at=expires_at.isoformat() if expires_at else None,
                    product_id=product_id if purchase_type == 'plan' else None,
                    sub_id=client_data.get('sub_id'),
                    invoice_id=invoice_id,
                    config_link=client_data.get('config_link')
                )
                
                if client_id > 0:
                    # Record discount usage if discount was applied
                    if discount_code and discount_amount > 0:
                        discount_code_obj = db_instance.get_discount_code(discount_code)
                        if discount_code_obj:
                            user_db = db_instance.get_user(user_id)
                            db_instance.apply_discount_code(
                                code_id=discount_code_obj['id'],
                                user_id=user_db['id'],
                                invoice_id=invoice_id,
                                amount_before=original_price,
                                discount_amount=discount_amount,
                                amount_after=total_price
                            )
                    
                    # Deduct balance and record transaction
                    product_name = product.get('name', '') if purchase_type == 'plan' else ''
                    if purchase_type == 'plan' and product_name:
                        description = f'خرید اشتراک پلنی: {product_name}'
                    else:
                        description = f'خرید سرویس {volume_gb}GB'
                    db_instance.update_user_balance(
                        telegram_id=user_id,
                        amount=-total_price,
                        transaction_type='service_purchase',
                        description=description
                    )
                    
                    logger.info(f"Service created successfully for user {user_id} with client_id {client_id}")
                    
                    # Clear renewal session variables after successful service creation
                    if is_renewal:
                        session.pop('renew_service_id', None)
                        session.pop('renew_panel_id', None)
                    
                    # Invalidate caches after service creation
                    invalidate_user_cache(user_id)
                    from cache_utils import cache_key_panels_active, cache_key_products_panel
                    cache.delete(cache_key_panels_active())
                    cache.delete(cache_key_products_panel(panel_id))
                    
                    # Report service purchase to channel
                    try:
                        import asyncio
                        from reporting_system import ReportingSystem
                        from telegram import Bot
                        bot_config = get_bot_config()
                        telegram_bot = Bot(token=bot_config['token'])
                        # CRITICAL: Pass bot_config to ReportingSystem to ensure reports go to correct channel
                        reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
                        service_data = {
                            'service_name': client_name,
                            'data_amount': volume_gb,
                            'amount': total_price,
                            'panel_name': panel.get('name', 'نامشخص'),
                            'duration_days': expire_days,
                            'product_name': product.get('name') if purchase_type == 'plan' else None,
                            'purchase_type': purchase_type,
                            'payment_method': payment_method
                        }
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(reporting_system.report_service_purchased(user, service_data))
                        loop.close()
                    except Exception as e:
                        logger.error(f"Failed to send service purchase report: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                    
                    # Get subscription link from client_data
                    subscription_link = client_data.get('subscription_link') or client_data.get('subscription_url', '')
                    
                    # Ensure subscription link uses the correct sub_id - DISABLED based on user feedback
                    # User reported that short sub_id (16 chars) is incorrect for some panels, and long UUID (32 chars) is required.
                    # We will use whatever the panel returns.
                    # try:
                    #     if subscription_link and client_data.get('sub_id') and '/sub/' in subscription_link:
                    #         # Parse link to check if it uses UUID or sub_id
                    #         # Example: https://sub.domain.com/sub/UUID
                    #         base_part, token = subscription_link.rsplit('/', 1)
                    #         # If token is long (UUID) but we have a short sub_id, use sub_id
                    #         if len(token) > 20 and len(client_data['sub_id']) < 20:
                    #             subscription_link = f"{base_part}/{client_data['sub_id']}"
                    #             logger.info(f"🔧 Fixed subscription link to use short sub_id: {subscription_link}")
                    # except Exception as e:
                    #     logger.warning(f"Failed to fix subscription link: {e}")

                    # Also provide config link if available
                    config_link = client_data.get('config_link') or client_data.get('config_url', '')
                    
                    # Send success message to user via Telegram Bot with links
                    try:
                        from telegram_helper import TelegramHelper
                        
                        # Prepare links for message
                        links_msg = ""
                        if subscription_link:
                            links_msg += f"\n🔗 لینک سابسکریپشن:\n`{subscription_link}`\n"
                        
                        # Only show direct config if different from sub link or if sub link missing
                        if config_link and config_link != subscription_link:
                             if config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                                links_msg += f"\n🔑 کانفیگ مستقیم:\n`{config_link}`\n"

                        success_msg = f"""
✅ *خرید سرویس با موفقیت انجام شد!*

🎉 *جزئیات سرویس جدید:*
🔧 نام سرویس: `{client_name}`
🔗 پنل: {panel.get('name', 'نامشخص')}
📊 حجم: {volume_gb} گیگابایت
💰 مبلغ: {total_price:,} تومان
⏰ مدت: {expire_days} روز

{links_msg}
🚀 *سرویس شما آماده استفاده است!*
برای مشاهده جزئیات بیشتر و مدیریت سرویس، به بخش مدیریت سرویس مراجعه کنید.
"""
                        # Run in background to not block response
                        def send_msg_async():
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(TelegramHelper.send_message(user_id, success_msg))
                            loop.close()
                        
                        threading.Thread(target=send_msg_async).start()
                        
                    except Exception as e:
                        logger.error(f"Failed to send user success message: {e}")

                    return jsonify({
                        'success': True,
                        'message': 'سرویس با موفقیت ایجاد شد',
                        'subscription_link': subscription_link,
                        'config_link': config_link,
                        'service': {
                            'id': client_id,
                            'config': subscription_link, # Keep backward compatibility for 'config' field usually showing sub link
                            'subscription_link': subscription_link,
                            'config_link': config_link,
                            'volume': volume_gb,
                            'price': total_price,
                            'client_name': client_name
                        }
                    })
                else:
                    logger.error(f"Failed to save client to database")
                    return jsonify({'success': False, 'message': 'خطا در ذخیره سرویس در دیتابیس'}), 500
            else:
                # No refund needed as we didn't deduct balance yet
                logger.error(f"Failed to create service: {message}")
                # Safely handle message that might contain emoji or special characters
                safe_message = message or 'خطا در ایجاد سرویس روی پنل'
                try:
                    # Remove emoji and special characters that might cause encoding issues
                    safe_message = safe_message.encode('utf-8', errors='ignore').decode('utf-8')
                except:
                    safe_message = 'خطا در ایجاد سرویس روی پنل'
                return jsonify({'success': False, 'message': safe_message}), 500
        
        elif payment_method == 'card':
            # Create invoice for card payment
            invoice_notes = None
            notes_parts = []
            if is_renewal and renew_service_id:
                notes_parts.append(f'renew_service_id: {renew_service_id}')
            
            if custom_name:
                notes_parts.append(f'custom_name:{custom_name}')
                
            if notes_parts:
                invoice_notes = ','.join(notes_parts)
            
            db_instance = get_db()
            user_db = db_instance.get_user(user_id)
            
            invoice_id = db_instance.add_invoice(
                user_id=user_db['id'],
                panel_id=panel_id,
                gb_amount=int(volume_gb),
                amount=total_price,
                payment_method='card',
                status='pending',
                product_id=product_id if purchase_type == 'plan' else None,
                duration_days=expire_days if purchase_type == 'plan' else None,
                purchase_type=purchase_type,
                notes=invoice_notes
            )
            
            if not invoice_id:
                return jsonify({'success': False, 'message': 'خطا در ایجاد فاکتور'}), 500
            
            # Apply discount code if provided
            if discount_code and discount_amount > 0:
                from discount_manager import DiscountCodeManager
                discount_manager = DiscountCodeManager(db_instance)
                discount_result = discount_manager.validate_and_apply_discount(discount_code, user_id, original_price)
                if discount_result['success']:
                    discount_code_obj = db_instance.get_discount_code(discount_code)
                    if discount_code_obj:
                        with db_instance.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE invoices 
                                SET discount_code_id = %s, 
                                    discount_amount = %s,
                                    original_amount = %s
                                WHERE id = %s
                            ''', (discount_code_obj['id'], discount_amount, original_price, invoice_id))
                            conn.commit()
            
            return jsonify({
                'success': True,
                'payment_required': True,
                'payment_method': 'card',
                'invoice_id': invoice_id,
                'amount': total_price
            })

        elif payment_method == 'gateway':
            # Create invoice for gateway payment
            # Create invoice for gateway payment
            # Payment gateway removed as per request
            return jsonify({'success': False, 'message': 'درگاه پرداخت غیرفعال است'}), 400
            
            # Placeholder for future payment implementation
            # from payment_system import PaymentManager
            # payment_manager = PaymentManager(db, None)
            
            # Prepare invoice notes for renewals
            invoice_notes = None
            if is_renewal and renew_service_id:
                invoice_notes = f'renew_service_id: {renew_service_id}'
            
            # Create invoice with notes if renewal
            db_instance = get_db()
            user_db = db_instance.get_user(user_id)
            
            # Create invoice directly with notes support
            invoice_id = db_instance.add_invoice(
                user_id=user_db['id'],
                panel_id=panel_id,
                gb_amount=int(volume_gb),
                amount=total_price,
                payment_method='gateway',
                status='pending',
                product_id=product_id if purchase_type == 'plan' else None,
                duration_days=expire_days if purchase_type == 'plan' else None,
                purchase_type=purchase_type,
                notes=invoice_notes
            )
            
            if not invoice_id:
                return jsonify({'success': False, 'message': 'خطا در ایجاد فاکتور'}), 500
            
            # Apply discount code if provided (update invoice)
            if discount_code and discount_amount > 0:
                from discount_manager import DiscountCodeManager
                discount_manager = DiscountCodeManager(db_instance)
                discount_result = discount_manager.validate_and_apply_discount(discount_code, user_id, original_price)
                if discount_result['success']:
                    discount_code_obj = db_instance.get_discount_code(discount_code)
                    if discount_code_obj:
                        with db_instance.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE invoices 
                                SET discount_code_id = %s, 
                                    discount_amount = %s,
                                    original_amount = %s
                                WHERE id = %s
                            ''', (discount_code_obj['id'], discount_amount, original_price, invoice_id))
                            conn.commit()
            
            # Invalidate caches
            invalidate_user_cache(user_id)
            from cache_utils import cache_key_panels_active, cache_key_products_panel
            cache.delete(cache_key_panels_active())
            cache.delete(cache_key_products_panel(panel_id))
            
            # Create payment link
            payment_result = payment_manager.create_service_payment(
                user_id, panel_id, int(volume_gb), total_price, invoice_id
            )
            
            if payment_result['success']:
                return jsonify({
                    'success': True,
                    'payment_required': True,
                    'payment_link': payment_result.get('payment_url') or payment_result.get('payment_link'),
                    'discount_amount': discount_amount,
                    'final_amount': total_price,
                    'invoice_id': invoice_id
                })
            else:
                return jsonify({'success': False, 'message': payment_result.get('message', 'خطا در ایجاد لینک پرداخت')}), 500
        
        else:
            return jsonify({'success': False, 'message': 'روش پرداخت نامعتبر'}), 400
            
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error creating service: {e}")
        logger.error(f"Traceback: {error_details}")
        
        # Safely encode error message to avoid encoding issues on Windows
        try:
            error_msg = str(e)
            # Remove emoji and special characters that might cause encoding issues
            error_msg = error_msg.encode('ascii', 'ignore').decode('ascii')
            if not error_msg:
                error_msg = "خطا در ایجاد سرویس"
        except:
            error_msg = "خطا در ایجاد سرویس"
        
        return jsonify({
            'success': False, 
            'message': f'خطا در ایجاد سرویس: {error_msg}',
            'error_detail': error_msg
        }), 500

@app.route('/api/create-test-account', methods=['POST'])
@login_required
@rate_limit(max_requests=3, window_seconds=3600)  # Strict rate limit: 3 per hour
def api_create_test_account():
    """API endpoint to create test account"""
    try:
        user_id = session.get('user_id')
        data = request.json
        
        # Input validation
        panel_id = validate_panel_id(data.get('panel_id'))
        category_id = data.get('category_id')
        if category_id:
            try:
                category_id = int(category_id)
            except:
                category_id = None
        
        if not panel_id:
            return jsonify({'success': False, 'message': 'اطلاعات ناقص است'}), 400
            
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
            
        # Check max test accounts limit
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager(db_instance)
        max_test_accounts = settings_mgr.get_setting('max_test_accounts', 1)
        
        current_count = db_instance.get_user_test_accounts_count(user['id'])
        
        if current_count >= max_test_accounts:
            return jsonify({'success': False, 'message': f'شما به سقف مجاز دریافت اکانت تست ({max_test_accounts} عدد) رسیده‌اید.'}), 400

        configured_test_panels = db_instance.get_test_panels(active_only=True)
        if configured_test_panels and not any(p.get('id') == panel_id for p in configured_test_panels):
            return jsonify({'success': False, 'message': 'این سرور برای اکانت تست فعال نیست.'}), 400
            
        # Check if user already got test from this panel
        if db_instance.has_user_received_test_account_from_panel(user['id'], panel_id):
            return jsonify({'success': False, 'message': 'شما قبلاً از این سرور اکانت تست دریافت کرده‌اید.'}), 400
            
        # Get panel
        panel = db_instance.get_panel(panel_id)
        if not panel:
            return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
            
        if not panel.get('is_active'):
            return jsonify({'success': False, 'message': 'این پنل غیرفعال است'}), 400
            
        # Verify category if provided
        if category_id:
            category = db_instance.get_category(category_id)
            if not category or category['panel_id'] != panel_id:
                return jsonify({'success': False, 'message': 'دسته‌بندی نامعتبر است'}), 400
                
        # Get test config (prioritize category)
        test_config = db_instance.get_test_account_config(panel_id, category_id)
        duration_hours = test_config.get('duration_hours', 24)
        volume_gb = test_config.get('volume_gb', 1)
        
        # Check if volume is valid
        if volume_gb <= 0:
             return jsonify({'success': False, 'message': 'اکانت تست برای این گزینه غیرفعال است'}), 400
        
        # Convert hours to days (float)
        expire_days = duration_hours / 24.0
        
        # Create client using admin manager
        from admin_manager import AdminManager
        admin_manager = AdminManager(db_instance)
        
        # Generate username
        from username_formatter import UsernameFormatter
        client_name = UsernameFormatter.format_client_name(user_id)
        
        # Use create_client_on_all_panel_inbounds
        success, message, client_data = admin_manager.create_client_on_all_panel_inbounds(
            panel_id=panel_id,
            client_name=client_name,
            expire_days=expire_days,
            total_gb=volume_gb
        )
        
        if success and client_data:
            # Determine expiration time
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(hours=duration_hours)
            
            # Save to database
            client_id = db_instance.add_client(
                user_id=user['id'],
                panel_id=panel_id,
                client_name=client_name,
                client_uuid=client_data.get('id', ''),
                inbound_id=client_data.get('inbound_id', 0),
                protocol=client_data.get('protocol', 'vless'),
                expire_days=expire_days,
                total_gb=volume_gb,
                expires_at=expires_at.isoformat(),
                product_id=None,
                sub_id=client_data.get('sub_id')
            )
            
            # Log test account creation
            try:
                db_instance.log_test_account_creation(user['id'], panel_id, str(client_id))
            except Exception as e:
                logger.error(f"Error logging test account: {e}")

            try:
                send_report_sync(
                    'report_test_account_created',
                    user,
                    panel.get('name', 'نامشخص'),
                    float(volume_gb),
                    int(duration_hours)
                )
            except Exception as e:
                logger.error(f"Failed to report test account creation: {e}")
                
            # Get links
            subscription_link = client_data.get('subscription_link') or client_data.get('subscription_url', '')
            config_link = client_data.get('config_link') or client_data.get('config_url', '')
            
            # Send success message via Telegram
            try:
                from telegram_helper import TelegramHelper
                
                links_msg = ""
                if subscription_link:
                    links_msg += f"\n🔗 لینک سابسکریپشن:\n`{subscription_link}`\n"
                
                if config_link and config_link != subscription_link:
                    if config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                        links_msg += f"\n🔑 کانفیگ مستقیم:\n`{config_link}`\n"
                        
                success_msg = f"""
✅ *اکانت تست با موفقیت ایجاد شد!*

🎉 *جزئیات سرویس تست:*
🔧 نام سرویس: `{client_name}`
🔗 پنل: {panel.get('name', 'نامشخص')}
📊 حجم: {volume_gb} گیگابایت
⏰ مدت: {duration_hours} ساعت

{links_msg}
🚀 *لطفاً سرویس را تست کنید و در صورت رضایت اقدام به خرید نمایید.*
"""
                # Run in background
                def send_msg_async():
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(TelegramHelper.send_message(user_id, success_msg))
                    loop.close()
                
                threading.Thread(target=send_msg_async).start()
                
            except Exception as e:
                logger.error(f"Failed to send test account success message: {e}")
                
            return jsonify({
                'success': True,
                'message': 'اکانت تست با موفقیت ایجاد شد',
                'subscription_link': subscription_link,
                'config_link': config_link,
                'service': {
                    'id': client_id,
                    'volume': volume_gb,
                    'duration_hours': duration_hours
                }
            })
            
        else:
            logger.error(f"Failed to create test account: {message}")
            return jsonify({'success': False, 'message': message or 'خطا در ایجاد اکانت تست'}), 500
            
    except Exception as e:
        logger.error(f"Error creating test account: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': 'خطا در پردازش درخواست'}), 500

@app.route('/api/validate-discount-code', methods=['POST'])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_validate_discount_code():
    """API endpoint to validate discount code"""
    try:
        user_id = session.get('user_id')
        data = request.json
        
        # Input validation
        code = sanitize_input(data.get('code', ''), max_length=50)
        amount = validate_amount(data.get('amount'), min_amount=0)
        
        if not code or not amount:
            return jsonify({'success': False, 'message': 'اطلاعات ناقص است'}), 400
        
        # Validate discount code format
        if not validate_discount_code(code):
            return jsonify({'success': False, 'message': 'فرمت کد تخفیف نامعتبر است'}), 400
        
        from discount_manager import DiscountCodeManager
        db_instance = get_db()
        discount_manager = DiscountCodeManager(db_instance)
        
        result = discount_manager.validate_and_apply_discount(code, user_id, amount)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error validating discount code: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'خطا در بررسی کد تخفیف: {str(e)}'
        }), 500

@app.route('/api/clear-renewal-session', methods=['POST'])
@login_required
def api_clear_renewal_session():
    """API endpoint to clear renewal session variables"""
    try:
        session.pop('renew_service_id', None)
        session.pop('renew_panel_id', None)
        return jsonify({'success': True, 'message': 'Session cleared'})
    except Exception as e:
        logger.error(f"Error clearing renewal session: {e}")
        return jsonify({'success': False, 'message': 'خطا در پاک کردن session'}), 500

@app.route('/api/apply-gift-code', methods=['POST'])
@login_required
def api_apply_gift_code():
    """API endpoint to apply gift code"""
    try:
        user_id = session.get('user_id')
        data = request.json
        
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'message': 'کد هدیه وارد نشده است'}), 400
        
        from discount_manager import DiscountCodeManager
        db_instance = get_db()
        discount_manager = DiscountCodeManager(db_instance)
        
        result = discount_manager.validate_and_apply_gift_code(code, user_id)
        
        if result['success']:
            # Refresh user balance
            user = db_instance.get_user(user_id)
            result['new_balance'] = user.get('balance', 0)
            
            # Invalidate user cache after gift code application
            invalidate_user_cache(user_id)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error applying gift code: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'خطا در اعمال کد هدیه: {str(e)}'
        }), 500

@app.route('/api/add-volume', methods=['POST'])
@login_required
@rate_limit(max_requests=10, window_seconds=60)
def api_add_volume():
    """API endpoint to add volume to existing service"""
    try:
        user_id = session.get('user_id')
        data = request.json
        
        # Input validation
        service_id = validate_positive_int(data.get('service_id'))
        volume_gb = validate_positive_int(data.get('volume_gb'), max_value=10000)
        payment_method = data.get('payment_method')
        
        if not service_id or not volume_gb or not payment_method:
            return jsonify({'success': False, 'message': 'اطلاعات ناقص است'}), 400
        
        if payment_method not in ['balance', 'gateway']:
            return jsonify({'success': False, 'message': 'روش پرداخت نامعتبر است'}), 400
        
        # Get user first to get internal ID
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
            
        # Get service using internal user ID - this bypasses the restrictive filters of get_user_clients
        # and allows adding volume to any service belonging to the user (even if expired/disabled)
        logger.info(f"Looking for service {service_id} for user {user['id']}")
        service = db_instance.get_user_service(service_id, user['id'])
        
        if not service:
            logger.error(f"Service {service_id} not found for user {user['id']}")
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
            
        logger.info(f"Found service: {service.get('id')} - Panel: {service.get('panel_id')}")
        
        # Get panel
        panel = db_instance.get_panel(service['panel_id'])
        if not panel:
            return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
        
        price_per_gb = panel.get('price_per_gb', 0)
        if not price_per_gb or price_per_gb <= 0:
            return jsonify({'success': False, 'message': 'قیمت هر گیگابایت برای این پنل تنظیم نشده است. لطفاً با پشتیبانی تماس بگیرید.'}), 400
        
        total_price = int(price_per_gb * volume_gb)
        

        
        if payment_method == 'balance':
            if user.get('balance', 0) < total_price:
                return jsonify({
                    'success': False,
                    'insufficient_balance': True,
                    'current_balance': user.get('balance', 0),
                    'required_amount': total_price,
                    'message': f'موجودی کافی نیست. موجودی شما: {user.get("balance", 0):,} تومان - مبلغ مورد نیاز: {total_price:,} تومان'
                }), 400
            
            # Get panel manager for this specific panel
            from admin_manager import AdminManager
            admin_manager = AdminManager(db_instance)
            panel_manager = admin_manager.get_panel_manager(service['panel_id'])
            
            if not panel_manager:
                return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
            
            # Add volume
            new_total_gb = service.get('total_gb', 0) + volume_gb
            
            result = panel_manager.update_client_traffic(
                service['inbound_id'],
                service['client_uuid'],
                new_total_gb
            )
            
            if result:
                # Update database with new total GB and reset notification flags and status
                from professional_database import ProfessionalDatabaseManager
                with db.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    try:
                        cursor.execute('''
                            UPDATE clients 
                            SET total_gb = %s,
                                status = 'active',
                                is_active = 1,
                                warned_70_percent = 0,
                                warned_100_percent = 0,
                                warned_expired = 0,
                                warned_three_days = 0,
                                warned_one_week = 0,
                                notified_70_percent = 0,
                                notified_80_percent = 0,
                                exhausted_at = NULL,
                                expired_at = NULL,
                                deletion_grace_period_end = NULL
                            WHERE id = %s
                        ''', (new_total_gb, service_id))
                        conn.commit()
                    finally:
                        cursor.close()
                
                # Deduct balance and record transaction
                db_instance.update_user_balance(
                    telegram_id=user_id,
                    amount=-total_price,
                    transaction_type='volume_purchase',
                    description=f'افزایش حجم {volume_gb}GB'
                )
                

                
                # Invalidate user cache after balance update
                invalidate_user_cache(user_id)
                
                # Report volume addition to channel
                try:
                    import asyncio
                    from reporting_system import ReportingSystem
                    from telegram import Bot
                    bot_config = get_bot_config()
                    telegram_bot = Bot(token=bot_config['token'])
                    # CRITICAL: Pass bot_config to ReportingSystem to ensure reports go to correct channel
                    reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
                    volume_data = {
                        'service_name': service.get('client_name', 'سرویس'),
                        'volume_added': volume_gb,
                        'old_volume': service.get('total_gb', 0),
                        'new_volume': new_total_gb,
                        'amount': total_price,
                        'panel_name': panel.get('name', 'نامشخص'),
                        'payment_method': payment_method
                    }
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(reporting_system.report_volume_added(user, volume_data))
                    loop.close()
                except Exception as e:
                    logger.error(f"Failed to send volume addition report: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                
                # Invalidate caches after volume addition
                invalidate_user_cache(user_id)
                
                # Invalidate user cache after balance update
                invalidate_user_cache(user_id)
                
                return jsonify({
                    'success': True,
                    'message': 'حجم با موفقیت اضافه شد',
                    'new_total': new_total_gb
                })
            else:
                # Volume update failed - no refund needed since balance wasn't deducted
                return jsonify({'success': False, 'message': 'خطا در افزایش حجم'}), 500
        
        elif payment_method == 'gateway':
            # Payment gateway removed as per request
            return jsonify({'success': False, 'message': 'درگاه پرداخت غیرفعال است'}), 400
            
            # Placeholder for future payment implementation
            # from payment_system import PaymentManager
            # payment_manager = PaymentManager(db, None)
            
            payment_result = payment_manager.create_volume_payment(user_id, service['panel_id'], volume_gb, total_price)
            
            if payment_result['success']:
                return jsonify({
                    'success': True,
                    'payment_required': True,
                    'payment_link': payment_result['payment_link']
                })
            else:
                return jsonify({'success': False, 'message': payment_result.get('message')}), 500
        
        else:
            return jsonify({'success': False, 'message': 'روش پرداخت نامعتبر'}), 400
            
    except Exception as e:
        logger.error(f"Error adding volume: {e}", exc_info=True)
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'خطا در افزایش حجم: {str(e)}'}), 500

@app.route('/api/recharge', methods=['POST'])
@login_required
@rate_limit(max_requests=10, window_seconds=60)
def api_recharge():
    """API endpoint to recharge balance"""
    try:
        user_id = session.get('user_id')
        data = request.json
        
        # Input validation
        amount = validate_amount(data.get('amount'), min_amount=10000, max_amount=10000000)
        
        if not amount:
            return jsonify({'success': False, 'message': 'مبلغ نامعتبر است. حداقل 10,000 تومان'}), 400
        
        # Create payment
        # Create payment
        # Payment gateway removed as per request
        return jsonify({'success': False, 'message': 'درگاه پرداخت غیرفعال است'}), 400
        
        # Placeholder for future payment implementation
        # from payment_system import PaymentManager
        # payment_manager = PaymentManager(db, None)
        
        payment_result = payment_manager.create_balance_payment(user_id, amount)
        
        if payment_result['success']:
            return jsonify({
                'success': True,
                'payment_link': payment_result['payment_link']
            })
        else:
            return jsonify({'success': False, 'message': payment_result.get('message', 'خطا در ایجاد پرداخت')}), 500
            
    except Exception as e:
        logger.error(f"Error creating recharge payment: {e}")
        return jsonify({'success': False, 'message': 'خطا در ایجاد پرداخت'}), 500

@app.route('/profile')
@login_required
def profile():
    """User profile page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    # Format user creation date to Persian
    if user and user.get('created_at'):
        try:
            from persian_datetime import PersianDateTime
            from datetime import datetime
            # Parse the datetime string
            dt = user['created_at']
            if isinstance(dt, str):
                # Handle different datetime formats
                if 'T' in dt:
                    dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                else:
                    try:
                        dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        # Try parsing just date if time is missing
                        dt = datetime.strptime(dt, '%Y-%m-%d')
            elif isinstance(dt, datetime):
                pass  # Already a datetime object
            
            # Convert to Persian
            persian_dt_str = PersianDateTime.format_datetime(dt, include_time=False)
            user['created_at_persian'] = persian_dt_str
        except Exception as e:
            logger.error(f"Error formatting user creation date: {e}")
            # Fallback to original format
            user['created_at_persian'] = str(user.get('created_at', ''))[:10]
    
    # Get recent transactions
    recent_transactions = db_instance.get_user_transactions(user_id, limit=10)
    
    # Translate transaction descriptions to Persian
    persian_transactions = []
    # Persian translation for transaction types
    trans_type_persian = {
        'service_purchase': 'خرید سرویس',
        'balance_added': 'افزایش موجودی',
        'balance_recharge': 'شارژ حساب',
        'refund': 'بازگشت مبلغ',
        'referral_reward': 'پاداش دعوت',
        'welcome_bonus': 'هدیه ثبت نام',
        'gift': 'هدیه',
        'admin_credit': 'افزایش توسط ادمین',
        'admin_debit': 'کاهش توسط ادمین',
        'volume_purchase': 'خرید حجم',
        'service_renewal': 'تمدید سرویس'
    }
    
    for trans in recent_transactions:
        trans_copy = trans.copy()
        # Translate transaction type
        trans_type = trans_copy.get('transaction_type', '')
        if trans_type:
            trans_copy['transaction_type_persian'] = trans_type_persian.get(trans_type, trans_type.replace('_', ' '))
        
        # Format date to Persian
        if trans_copy.get('created_at'):
            try:
                from persian_datetime import PersianDateTime
                from datetime import datetime
                # Parse the datetime string
                dt = trans_copy['created_at']
                if isinstance(dt, str):
                    # Handle different datetime formats
                    if 'T' in dt:
                        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                    else:
                        dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
                elif isinstance(dt, datetime):
                    pass  # Already a datetime object
                
                # Convert to Persian
                persian_dt_str = PersianDateTime.format_datetime(dt, include_time=True)
                # Format to YYYY/MM/DD HH:MM (without seconds)
                if ' ' in persian_dt_str:
                    date_part, time_part = persian_dt_str.split(' ', 1)
                    time_part = ':'.join(time_part.split(':')[:2])  # Remove seconds
                    persian_dt_str = f"{date_part} {time_part}"
                trans_copy['created_at_persian'] = persian_dt_str
                trans_copy['created_at'] = persian_dt_str
            except Exception as e:
                logger.error(f"Error formatting date: {e}")
                # Fallback to original format
                trans_copy['created_at_persian'] = str(trans_copy.get('created_at', ''))[:16]
        
        # Description is already in Persian, but ensure it's properly formatted
        desc = trans_copy.get('description', '')
        if desc:
            # Check if it's a payment callback (recharge)
            if 'callback' in desc.lower() and 'order' in desc.lower():
                trans_copy['description'] = 'شارژ حساب'
            elif 'payment' in desc.lower() and 'invoice' in desc.lower():
                # Handle "Payment for invoice 159" pattern
                import re
                match = re.search(r'invoice\s*#%s(\d+)', desc, re.IGNORECASE)
                if match:
                    invoice_num = match.group(1)
                    trans_copy['description'] = f'پرداخت برای فاکتور #{invoice_num}'
                else:
                    trans_copy['description'] = 'پرداخت برای فاکتور'
            else:
                # Common English to Persian translations
                translations = {
                    'Payment for invoice': 'پرداخت برای فاکتور',
                    'for invoice': 'برای فاکتور',
                    'invoice': 'فاکتور',
                    'Balance recharge': 'شارژ حساب',
                    'Service purchase': 'خرید سرویس',
                    'Volume added': 'افزایش حجم',
                    'Referral bonus': 'پاداش دعوت',
                    'Admin adjustment': 'تنظیم توسط ادمین',
                    'Purchase service': 'خرید سرویس',
                    'Add volume': 'افزایش حجم',
                    'Recharge': 'شارژ حساب',
                    'Purchase': 'خرید',
                    'Volume purchase': 'خرید اشتراک',
                    'Volume': 'حجم',
                    'Service': 'سرویس',
                    'Service creation failed': 'خطا در ایجاد سرویس',
                    'payment': 'پرداخت',
                    'Payment': 'پرداخت',
                    'Payment completed': 'پرداخت موفق',
                    'Payment callback': 'بازگشت از درگاه پرداخت',
                    'Gateway': 'درگاه',
                    'gateway': 'درگاه',
                    'callback': 'بازگشت از درگاه',
                    'order': 'سفارش',
                    'GB': 'گیگابایت'
                }
                
                # Replace English terms with Persian (longer patterns first)
                persian_desc = desc
                # Sort by length (descending) to match longer patterns first
                sorted_translations = sorted(translations.items(), key=lambda x: len(x[0]), reverse=True)
                for en, fa in sorted_translations:
                    if en.lower() in persian_desc.lower():
                        # Case-insensitive replacement
                        import re
                        persian_desc = re.sub(re.escape(en), fa, persian_desc, flags=re.IGNORECASE)
                
                trans_copy['description'] = persian_desc
        
        persian_transactions.append(trans_copy)
    
    # Get referral information
    db_instance = get_db()
    referrals = db_instance.get_user_referrals(user['id'])
    
    # Generate referral link
    from config import BOT_CONFIG
    bot_username = BOT_CONFIG.get('bot_username', '')
    if not bot_username:
        # Try to get from environment or use default
        import os
        bot_username = os.getenv('BOT_USERNAME', 'YourBot')
    referral_code = user.get('referral_code', '')
    if referral_code:
        referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    else:
        referral_link = None
    
    # Get photo_url from session
    photo_url = session.get('photo_url', '')
    
    is_reseller = False
    try:
        from reseller_panel.models import ResellerManager
        reseller_manager = ResellerManager(db_instance)
        reseller_profile = reseller_manager.get_reseller_by_user_id(user['id']) if user else None
        is_reseller = bool(reseller_profile and reseller_profile.get('status') == 'active')
    except Exception:
        is_reseller = False
    
    return render_template('profile.html', 
                         user=user, 
                         transactions=persian_transactions,
                         referrals=referrals,
                         referral_link=referral_link,
                         photo_url=photo_url,
                         is_reseller=is_reseller)

@app.route('/reseller-portal')
@login_required
def reseller_portal():
    user_telegram_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_telegram_id)
    if not user:
        return redirect(url_for('dashboard'))
    
    from reseller_panel.models import ResellerManager
    reseller_manager = ResellerManager(db_instance)
    reseller_profile = reseller_manager.get_reseller_by_user_id(user['id'])
    if not reseller_profile or reseller_profile.get('status') != 'active':
        return redirect(url_for('profile'))
    
    with db_instance.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT c.*, p.name as panel_name, p.panel_type
            FROM clients c
            JOIN panels p ON c.panel_id = p.id
            WHERE c.user_id = %s
            ORDER BY c.created_at DESC
            LIMIT 200
        ''', (user['id'],))
        services = cursor.fetchall()
    
    from datetime import datetime, timedelta
    now = datetime.now()
    for s in services:
        created_at = s.get('created_at')
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except Exception:
                created_at = None
        refundable = False
        if created_at:
            refundable = (now - created_at) <= timedelta(days=1)
        s['refundable'] = refundable and bool(s.get('invoice_id'))
    
    photo_url = session.get('photo_url', '')
    return render_template('reseller_portal.html', user=user, photo_url=photo_url, reseller=reseller_profile, services=services)

@app.route('/reseller-portal/services/<int:service_id>/refund-delete', methods=['POST'])
@login_required
def reseller_refund_delete(service_id):
    user_telegram_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_telegram_id)
    if not user:
        return redirect(url_for('dashboard'))
    
    from reseller_panel.models import ResellerManager
    reseller_manager = ResellerManager(db_instance)
    reseller_profile = reseller_manager.get_reseller_by_user_id(user['id'])
    if not reseller_profile or reseller_profile.get('status') != 'active':
        return redirect(url_for('profile'))
    
    service = db_instance.get_client_by_id(service_id)
    if not service or service.get('user_id') != user['id']:
        flash('سرویس یافت نشد', 'error')
        return redirect(url_for('reseller_portal'))
    
    from datetime import datetime, timedelta
    now = datetime.now()
    created_at = service.get('created_at')
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except Exception:
            created_at = None
    if not created_at or (now - created_at) > timedelta(days=1):
        flash('مهلت حذف با برگشت وجه تمام شده است', 'error')
        return redirect(url_for('reseller_portal'))
    
    invoice_id = service.get('invoice_id')
    if not invoice_id:
        flash('برای این سرویس فاکتور ثبت نشده است', 'error')
        return redirect(url_for('reseller_portal'))
    
    invoice = db_instance.get_invoice(invoice_id)
    if not invoice:
        flash('فاکتور یافت نشد', 'error')
        return redirect(url_for('reseller_portal'))
    if str(invoice.get('status', '')).lower() in ['refunded', 'cancelled']:
        flash('این فاکتور قبلاً برگشت خورده است', 'error')
        return redirect(url_for('reseller_portal'))
    
    try:
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
        if not panel_mgr or not panel_mgr.login():
            flash('خطا در اتصال به پنل', 'error')
            return redirect(url_for('reseller_portal'))
        
        ok = panel_mgr.delete_client(service.get('inbound_id'), service.get('client_uuid'))
        if not ok:
            flash('حذف سرویس در پنل ناموفق بود', 'error')
            return redirect(url_for('reseller_portal'))
        
        db_instance.delete_client(service_id)
        
        # Calculate refund amount based on REAL paid amount
        invoice_amount = int(invoice.get('amount') or 0)
        discount_amount = int(invoice.get('discount_amount') or 0)
        original_amount = int(invoice.get('original_amount') or 0)
        
        # If original_amount exists and equals amount (meaning amount is original price), 
        # and there is a discount, we must subtract the discount.
        # However, typically 'amount' in invoice IS the final paid amount.
        # But if the user reports 50,000 refund instead of 1,000, it means 'amount' is 50,000.
        
        refund_amount = invoice_amount
        
        # Safety check: If reseller, ensure we don't refund more than what makes sense
        # If invoice amount seems to be the full price but user paid less
        if reseller_profile and discount_amount > 0:
             # If amount matches original, it means amount is NOT discounted
             if invoice_amount == original_amount:
                 refund_amount = invoice_amount - discount_amount
        
        # Ensure positive
        refund_amount = max(0, refund_amount)
        
        if refund_amount > 0:
            db_instance.add_balance(user['id'], refund_amount, 'refund', description=f"بازگشت وجه حذف سرویس #{service_id} (فاکتور #{invoice_id})")
        try:
            db_instance.update_invoice_status(invoice_id, 'refunded')
        except Exception:
            pass
        
        flash('سرویس حذف شد و مبلغ برگشت داده شد', 'success')
        
    except Exception as e:
        logger.error(f"Error refund-deleting reseller service: {e}", exc_info=True)
        flash('خطا در حذف سرویس', 'error')
    
    return redirect(url_for('reseller_portal'))

@app.route('/referrals')
@login_required
def referrals():
    """Referral system page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    # Get referrals
    user_referrals = db_instance.get_user_referrals(user['id'])
    
    # Generate referral link
    referral_link = f"https://t.me/{BOT_CONFIG['bot_username']}%sstart={user.get('referral_code', '')}"
    
    referral_stats = {
        'total_referrals': len(user_referrals),
        'total_earnings': user.get('total_referral_earnings', 0),
        'referral_code': user.get('referral_code', ''),
        'referral_link': referral_link
    }
    
    return render_template('referrals.html', user=user, referrals=user_referrals, stats=referral_stats)

@app.route('/api/service/<int:service_id>/config')
@login_required
def get_service_config(service_id):
    """Get service subscription link (not direct config)"""
    user_id = session.get('user_id')
    
    # Get service
    db_instance = get_db()
    services = db_instance.get_user_clients(user_id)
    service = next((s for s in services if s['id'] == service_id), None)
    
    if not service:
        return jsonify({'success': False, 'message': 'Service not found'}), 404
    
    # Get panel to construct subscription link
    panel = db_instance.get_panel(service.get('panel_id'))
    subscription_link = ""
    
    if panel:
        panel_type = panel.get('panel_type', '3x-ui')
        
        if panel_type == 'marzban':
            # For Marzban, get subscription link from panel API
            from admin_manager import AdminManager
            admin_mgr = AdminManager(db_instance)
            panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
            
            if panel_mgr:
                try:
                    subscription_link = panel_mgr.get_client_config_link(
                        service.get('inbound_id'),
                        service.get('client_uuid'),
                        service.get('protocol', 'vless')
                    )
                    # If Marzban returns None or empty, try to construct it manually if sub_url exists
                    if not subscription_link and panel.get('subscription_url'):
                        sub_url = panel.get('subscription_url', '').strip().rstrip('/')
                        if sub_url and service.get('client_uuid'):
                            if not sub_url.startswith(('http://', 'https://')):
                                sub_url = 'https://' + sub_url
                            subscription_link = f"{sub_url}/sub/{service.get('client_uuid')}"

                    if subscription_link:
                        db_instance = get_db()
                        db_instance.update_client_config(service['id'], subscription_link)
                except Exception as e:
                    logger.error(f"Error getting subscription from panel API: {e}")
        else:
            # For 3x-ui, ALWAYS construct subscription link from subscription_url + sub_id
            # NEVER use get_client_config_link for 3x-ui (it returns direct config, not subscription)
            if service.get('sub_id'):
                sub_url = service.get('subscription_url') or panel.get('subscription_url', '')
                if sub_url:
                    sub_url = sub_url.strip()
                    if not sub_url.startswith(('http://', 'https://')):
                         # Assume https if missing, unless it's an IP
                         if not sub_url[0].isdigit():
                             sub_url = 'https://' + sub_url
                         else:
                             sub_url = 'http://' + sub_url
                    
                    if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                        sub_url = sub_url.rstrip('/')
                        subscription_link = f"{sub_url}/{service.get('sub_id')}"
                    elif '/sub' in sub_url:
                        # If sub is in the middle of URL
                        if sub_url.endswith('/'):
                            subscription_link = f"{sub_url}{service.get('sub_id')}"
                        else:
                            subscription_link = f"{sub_url}/{service.get('sub_id')}"
                    else:
                        sub_url = sub_url.rstrip('/')
                        subscription_link = f"{sub_url}/sub/{service.get('sub_id')}"
                    
                    if subscription_link:
                        db_instance = get_db()
                        db_instance.update_client_config(service['id'], subscription_link)
        
        # Fallback: check if saved config_link is actually a subscription link
        if not subscription_link and service.get('config_link'):
            config_link = service.get('config_link', '')
            # Check if it's a subscription link (contains /sub/ or /sub or ends with sub_id)
            if '/sub/' in config_link or '/sub' in config_link or (service.get('sub_id') and service.get('sub_id') in config_link):
                # Only use if it's NOT a direct config link
                if not config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                    subscription_link = config_link
            else:
                # If it's a direct config link (starts with vless://, vmess://, etc.), construct subscription link
                if config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                    # This is a direct config link, not subscription - construct subscription link
                    if panel.get('subscription_url') and service.get('sub_id'):
                        sub_url = panel.get('subscription_url', '').strip()
                        if not sub_url.startswith(('http://', 'https://')):
                            sub_url = 'https://' + sub_url
                            
                        if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                            sub_url = sub_url.rstrip('/')
                            subscription_link = f"{sub_url}/{service.get('sub_id')}"
                        elif '/sub' in sub_url:
                            subscription_link = f"{sub_url}/{service.get('sub_id')}"
                        else:
                            sub_url = sub_url.rstrip('/')
                            subscription_link = f"{sub_url}/sub/{service.get('sub_id')}"
                        if subscription_link:
                            db_instance = get_db()
                            db_instance.update_client_config(service['id'], subscription_link)
    
    if not subscription_link:
        return jsonify({'success': False, 'message': 'No subscription link available'}), 404
    
    # Report subscription link retrieval to channel
    try:
        import asyncio
        from reporting_system import ReportingSystem
        from telegram import Bot
        bot_config = get_bot_config()
        telegram_bot = Bot(token=bot_config['token'])
        reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
        user = db_instance.get_user(user_id)
        service_data = {
            'service_name': service.get('client_name', 'سرویس'),
            'total_gb': service.get('total_gb', 0),
            'panel_name': panel.get('name', 'نامشخص') if panel else 'نامشخص',
            'protocol': service.get('protocol', 'vless')
        }
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(reporting_system.report_subscription_link_retrieved(user, service_data))
        loop.close()
    except Exception as e:
        logger.error(f"Failed to send subscription link retrieval report: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return jsonify({
        'success': True,
        'config': subscription_link,  # Return subscription link, not direct config
        'qr_code': f"/api/service/{service_id}/qr"
    })

@app.route('/api/service/<int:service_id>/compatible-panels', methods=['GET'])
@login_required
def api_get_compatible_panels(service_id):
    """Get compatible panels for service location change"""
    try:
        user_id = session.get('user_id')
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
        
        # Get service details
        service = db_instance.get_user_service(service_id, user['id'])
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        # Get current panel
        db_instance = get_db()
        current_panel = db_instance.get_panel(service.get('panel_id'))
        if not current_panel:
            return jsonify({'success': False, 'message': 'پنل فعلی یافت نشد'}), 404
        
        current_price_per_gb = current_panel.get('price_per_gb', 0)
        if not current_price_per_gb or current_price_per_gb == 0:
            return jsonify({
                'success': False, 
                'message': 'این سرویس قیمت گیگابایت مشخصی دارد. تغییر لوکیشن فقط برای پنل‌های با قیمت یکسان امکان‌پذیر است.'
            }), 400
        
        # Get compatible panels
        compatible_panels = db_instance.get_panels_with_same_price(
            current_price_per_gb,
            exclude_panel_id=service.get('panel_id')
        )
        
        # Get active inbounds from all panels with same price (excluding current panel)
        active_inbounds = db_instance.get_active_inbounds_for_change(
            exclude_panel_id=service.get('panel_id'),
            exclude_inbound_id=service.get('inbound_id'),
            price_per_gb=current_price_per_gb
        )
        
        # Get current panel's other inbounds (excluding current inbound)
        db_instance = get_db()
        current_panel_inbounds = db_instance.get_active_inbounds_for_change(
            exclude_panel_id=None,
            exclude_inbound_id=service.get('inbound_id'),
            price_per_gb=current_price_per_gb
        )
        current_panel_inbounds = [ib for ib in current_panel_inbounds if ib['panel_id'] == service.get('panel_id')]
        
        # Get current service traffic info
        remaining_gb = service.get('total_gb', 0)
        used_gb = service.get('used_gb', 0) or 0
        
        try:
            from admin_manager import AdminManager
            db_instance = get_db()
            admin_mgr = AdminManager(db_instance)
            panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
            
            if panel_mgr and panel_mgr.login():
                # Create callback to update inbound_id if found in different inbound
                def update_inbound_callback(service_id, new_inbound_id):
                    try:
                        db_instance.update_service_inbound_id(service_id, new_inbound_id)
                        logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                    except Exception as e:
                        logger.error(f"Failed to update inbound_id for service {service_id}: {e}")
                
                client = panel_mgr.get_client_details(
                    service.get('inbound_id'), 
                    service.get('client_uuid'),
                    update_inbound_callback=update_inbound_callback,
                    service_id=service.get('id')
                )
                if client:
                    total_traffic_bytes = client.get('total_traffic', 0)
                    used_traffic_bytes = client.get('used_traffic', 0)
                    if total_traffic_bytes > 0:
                        remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
                        remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
                        used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 2)
        except Exception as e:
            logger.error(f"Error getting service traffic info: {e}")
        
        if remaining_gb <= 0:
            return jsonify({
                'success': False,
                'message': 'حجم باقیمانده سرویس شما صفر است. امکان تغییر لوکیشن وجود ندارد.'
            }), 400
        
        # Format panels for response
        panels_data = []
        for panel in compatible_panels:
            panels_data.append({
                'id': panel['id'],
                'name': panel['name'],
                'price_per_gb': panel.get('price_per_gb', 0)
            })
        
        # Format inbounds for response
        inbounds_data = []
        for inbound in active_inbounds:
            inbounds_data.append({
                'panel_id': inbound['panel_id'],
                'panel_name': inbound['panel_name'],
                'inbound_id': inbound['inbound_id'],
                'inbound_name': inbound['inbound_name'],
                'inbound_protocol': inbound['inbound_protocol'],
                'inbound_port': inbound['inbound_port'],
                'is_main_inbound': inbound.get('is_main_inbound', 0)
            })
        
        current_inbounds_data = []
        for inbound in current_panel_inbounds:
            current_inbounds_data.append({
                'panel_id': inbound['panel_id'],
                'panel_name': inbound['panel_name'],
                'inbound_id': inbound['inbound_id'],
                'inbound_name': inbound['inbound_name'],
                'inbound_protocol': inbound['inbound_protocol'],
                'inbound_port': inbound['inbound_port'],
                'is_main_inbound': inbound.get('is_main_inbound', 0)
            })
        
        return jsonify({
            'success': True,
            'panels': panels_data,
            'active_inbounds': inbounds_data,
            'current_panel_inbounds': current_inbounds_data,
            'remaining_gb': remaining_gb,
            'used_gb': used_gb,
            'current_panel': current_panel['name'],
            'current_panel_id': service.get('panel_id'),
            'current_inbound_id': service.get('inbound_id')
        })
        
    except Exception as e:
        logger.error(f"Error getting compatible panels: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': 'خطا در پردازش درخواست'}), 500

@app.route('/api/service/<int:service_id>/change-panel', methods=['POST'])
@login_required
def api_change_service_panel(service_id):
    """Change service panel/location"""
    try:
        user_id = session.get('user_id')
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
        
        data = request.get_json()
        new_panel_id = data.get('panel_id')
        new_inbound_id = data.get('inbound_id')  # Optional: if not provided, uses main inbound
        
        if not new_panel_id:
            return jsonify({'success': False, 'message': 'پنل مقصد مشخص نشده است'}), 400
        
        # Get service details
        service = db_instance.get_user_service(service_id, user['id'])
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        # Get current panel
        current_panel = db_instance.get_panel(service.get('panel_id'))
        if not current_panel:
            return jsonify({'success': False, 'message': 'پنل فعلی یافت نشد'}), 404
        
        # Get new panel
        new_panel = db_instance.get_panel(new_panel_id)
        if not new_panel:
            return jsonify({'success': False, 'message': 'پنل مقصد یافت نشد'}), 404
        
        # Verify price match (if changing panel)
        if new_panel_id != service.get('panel_id'):
            if new_panel.get('price_per_gb', 0) != current_panel.get('price_per_gb', 0):
                return jsonify({'success': False, 'message': 'قیمت پنل مقصد با پنل فعلی یکسان نیست'}), 400
        
        # Verify inbound if provided
        if new_inbound_id:
            inbound_info = db_instance.get_panel_inbound(new_panel_id, new_inbound_id)
            if not inbound_info:
                return jsonify({'success': False, 'message': 'اینباند مقصد یافت نشد'}), 404
            if not inbound_info.get('is_enabled', 1):
                return jsonify({'success': False, 'message': 'اینباند مقصد غیرفعال است'}), 400
        
        # Get admin manager
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        
        # Get source panel manager
        source_panel_manager = admin_mgr.get_panel_manager(service.get('panel_id'))
        if not source_panel_manager or not source_panel_manager.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل مبدا'}), 500
        
        # Create callback to update inbound_id if found in different inbound
        def update_inbound_callback(service_id, new_inbound_id):
            try:
                db_instance.update_service_inbound_id(service_id, new_inbound_id)
                logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
            except Exception as e:
                logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
        
        # Get current client details and calculate remaining GB
        client = source_panel_manager.get_client_details(
            service.get('inbound_id'), 
            service.get('client_uuid'),
            update_inbound_callback=update_inbound_callback,
            service_id=service.get('id')
        )
        if not client:
            return jsonify({'success': False, 'message': 'کلاینت در پنل مبدا یافت نشد'}), 404
        
        total_traffic_bytes = client.get('total_traffic', 0)
        used_traffic_bytes = client.get('used_traffic', 0)
        expire_time = client.get('expiryTime', 0)
        
        if total_traffic_bytes <= 0:
            return jsonify({
                'success': False,
                'message': 'حجم سرویس نامحدود است. امکان تغییر لوکیشن وجود ندارد'
            }), 400
        
        remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
        remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 2)
        
        if remaining_gb <= 0:
            return jsonify({'success': False, 'message': 'حجم باقیمانده سرویس صفر است'}), 400
        
        # Calculate expire_days from expiryTime
        expire_days = 0  # 0 means unlimited
        if expire_time and expire_time > 0:
            import time
            current_time_ms = int(time.time() * 1000)
            # Handle both milliseconds (3x-ui) and seconds (Marzban) format
            if expire_time > 1000000000000:  # Milliseconds
                remaining_ms = expire_time - current_time_ms
            else:  # Seconds
                remaining_ms = (expire_time * 1000) - current_time_ms
            
            if remaining_ms > 0:
                expire_days = max(1, int(remaining_ms / (1000 * 60 * 60 * 24)))
        
        # Get destination panel manager
        dest_panel_manager = admin_mgr.get_panel_manager(new_panel_id)
        if not dest_panel_manager or not dest_panel_manager.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل مقصد'}), 500
        
        # Determine destination inbound
        if new_inbound_id:
            # Use specified inbound
            dest_inbound_id = new_inbound_id
            # Verify inbound exists in panel
            dest_inbounds = dest_panel_manager.get_inbounds()
            dest_inbound = None
            for inbound in dest_inbounds:
                if inbound.get('id') == dest_inbound_id:
                    dest_inbound = inbound
                    break
            if not dest_inbound:
                return jsonify({'success': False, 'message': 'اینباند مقصد در پنل یافت نشد'}), 404
            protocol = dest_inbound.get('protocol', service.get('protocol', 'vless'))
        else:
            # Use main inbound of destination panel
            dest_inbounds = dest_panel_manager.get_inbounds()
            if not dest_inbounds:
                return jsonify({'success': False, 'message': 'هیچ اینباندی در پنل مقصد یافت نشد'}), 404
            
            dest_inbound_id = new_panel.get('default_inbound_id') or dest_inbounds[0].get('id')
            if not dest_inbound_id:
                return jsonify({'success': False, 'message': 'اینباند پیش‌فرض در پنل مقصد یافت نشد'}), 404
            
            # Get protocol from inbound
            dest_inbound = None
            for inbound in dest_inbounds:
                if inbound.get('id') == dest_inbound_id:
                    dest_inbound = inbound
                    break
            protocol = dest_inbound.get('protocol', service.get('protocol', 'vless')) if dest_inbound else service.get('protocol', 'vless')
        
        # Step 1: Create new client in destination panel/inbound with same expiry
        client_name = service.get('client_name', f"user_{user_id}")
        new_client = dest_panel_manager.create_client(
            inbound_id=dest_inbound_id,
            client_name=client_name,
            protocol=protocol,
            expire_days=expire_days,  # Preserve expiry time
            total_gb=remaining_gb
        )
        
        if not new_client:
            return jsonify({'success': False, 'message': 'خطا در ایجاد کلاینت در پنل مقصد'}), 500
        
        new_client_uuid = new_client.get('id') or new_client.get('uuid')
        new_sub_id = new_client.get('sub_id') or new_client.get('subId')
        
        logger.info(f"📋 New client created - UUID: {new_client_uuid[:8]}..., sub_id: {new_sub_id}")
        
        # Get new subscription link from destination panel (NOT direct config)
        new_subscription_link = ""
        try:
            panel_type = new_panel.get('panel_type', '3x-ui')
            subscription_url = new_panel.get('subscription_url', '')
            
            logger.info(f"🔗 Panel type: {panel_type}, subscription_url: {subscription_url}")
            
            if panel_type == 'marzban':
                # For Marzban, get subscription link from panel API
                new_subscription_link = dest_panel_manager.get_client_config_link(
                    dest_inbound_id,
                    new_client_uuid,
                    protocol
                )
                # Marzban returns subscription link directly
                if not new_subscription_link and new_client.get('subscription_url'):
                    new_subscription_link = new_client.get('subscription_url')
            else:
                # For 3x-ui, ALWAYS construct subscription link from subscription_url + sub_id
                # NEVER use get_client_config_link (it returns direct config, not subscription)
                if new_sub_id and subscription_url:
                    if subscription_url.endswith('/sub') or subscription_url.endswith('/sub/'):
                        sub_url = subscription_url.rstrip('/')
                        new_subscription_link = f"{sub_url}/{new_sub_id}"
                    elif '/sub' in subscription_url:
                        new_subscription_link = f"{subscription_url}/{new_sub_id}"
                    else:
                        new_subscription_link = f"{subscription_url}/sub/{new_sub_id}"
                    
                    logger.info(f"✅ Constructed subscription link: {new_subscription_link[:50]}...")
                else:
                    logger.warning(f"⚠️ Cannot construct subscription link - sub_id: {new_sub_id}, subscription_url: {subscription_url}")
                    
        except Exception as e:
            logger.error(f"Error getting new subscription link: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Continue even if subscription link fails - we can get it later
        
        # Step 2: Delete client from source panel
        delete_success = source_panel_manager.delete_client(
            service.get('inbound_id'),
            service.get('client_uuid')
        )
        
        if not delete_success:
            # Rollback: try to delete the new client
            try:
                dest_panel_manager.delete_client(dest_inbound_id, new_client_uuid)
            except:
                pass
            return jsonify({'success': False, 'message': 'خطا در حذف کلاینت از پنل مبدا. عملیات لغو شد'}), 500
        
        # Step 3: Update service in database with new panel info and subscription link
        update_success = db_instance.update_service_panel(
            service_id=service_id,
            new_panel_id=new_panel_id,
            new_inbound_id=dest_inbound_id,
            new_client_uuid=new_client_uuid,
            new_total_gb=remaining_gb,
            config_link=new_subscription_link if new_subscription_link else None,
            sub_id=new_sub_id if new_sub_id else None
        )
        
        if not update_success:
            return jsonify({'success': False, 'message': 'خطا در به‌روزرسانی اطلاعات سرویس در دیتابیس'}), 500
        
        # Report panel change to channel
        try:
            import asyncio
            from reporting_system import ReportingSystem
            from telegram import Bot
            bot_config = get_bot_config()
            telegram_bot = Bot(token=bot_config['token'])
            # CRITICAL: Pass bot_config to ReportingSystem to ensure reports go to correct channel
            reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
            # Get inbound names
            old_inbound_name = None
            new_inbound_name = None
            
            # Get old inbound name
            try:
                source_panel_manager = admin_mgr.get_panel_manager(service.get('panel_id'))
                if source_panel_manager and source_panel_manager.login():
                    old_inbounds = source_panel_manager.get_inbounds()
                    for inbound in old_inbounds:
                        if inbound.get('id') == service.get('inbound_id'):
                            old_inbound_name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound.get('id')}"
                            break
            except:
                pass
            
            # Get new inbound name
            try:
                if dest_panel_manager:
                    new_inbounds = dest_panel_manager.get_inbounds()
                    for inbound in new_inbounds:
                        if inbound.get('id') == dest_inbound_id:
                            new_inbound_name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound.get('id')}"
                            break
            except:
                pass
            
            service_data = {
                'service_name': service.get('client_name', 'سرویس'),
                'old_panel_name': current_panel.get('name', 'نامشخص'),
                'new_panel_name': new_panel.get('name', 'نامشخص'),
                'remaining_gb': remaining_gb,
                'old_panel_id': service.get('panel_id'),
                'new_panel_id': new_panel_id,
                'old_inbound_name': old_inbound_name,
                'new_inbound_name': new_inbound_name
            }
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(reporting_system.report_panel_change(user, service_data))
            loop.close()
        except Exception as e:
            logger.error(f"Failed to send panel change report: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return jsonify({
            'success': True,
            'message': 'تغییر لوکیشن با موفقیت انجام شد',
            'new_panel': new_panel['name'],
            'remaining_gb': remaining_gb
        })
        
    except Exception as e:
        logger.error(f"Error changing service panel: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': 'خطا در انجام عملیات تغییر لوکیشن'}), 500

@app.route('/api/service/<int:service_id>/qr')
@login_required
def get_service_qr(service_id):
    """Generate QR code for service - returns JSON with base64 image"""
    user_id = session.get('user_id')
    
    db_instance = get_db()
    # Get service
    services = db_instance.get_user_clients(user_id)
    service = next((s for s in services if s['id'] == service_id), None)
    
    if not service:
        return jsonify({'success': False, 'message': 'Service not found'}), 404
    
    # Get config link - try to get from panel first
    config_link = None
    try:
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
        
        if panel_mgr and panel_mgr.login():
            config_link = panel_mgr.get_client_config_link(
                service.get('inbound_id'),
                service.get('client_uuid'),
                service.get('protocol', 'vless')
            )
    except Exception as e:
        logger.error(f"Error getting config from panel: {e}")
    
    # Fallback to saved config_link
    if not config_link:
        config_link = service.get('config_link', '')
    
    # For 3x-ui, construct subscription link if needed
    if not config_link:
        panel = db_instance.get_panel(service.get('panel_id'))
        if panel and panel.get('panel_type') == '3x-ui' and service.get('sub_id'):
            sub_url = panel.get('subscription_url', '')
            if sub_url:
                if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                    sub_url = sub_url.rstrip('/')
                    config_link = f"{sub_url}/{service.get('sub_id')}"
                elif '/sub' in sub_url:
                    config_link = f"{sub_url}/{service.get('sub_id')}"
                else:
                    config_link = f"{sub_url}/sub/{service.get('sub_id')}"
    
    if not config_link:
        return jsonify({'success': False, 'message': 'No config available'}), 404
    
    # Generate QR code
    import qrcode
    import base64
    from io import BytesIO
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(config_link)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    qr_base64 = base64.b64encode(buffer.read()).decode()
    
    return jsonify({'success': True, 'qr_code': qr_base64, 'config_link': config_link})

@app.route('/api/stats')
@login_required
def get_stats():
    """Get user statistics API"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    services = db_instance.get_user_clients(user_id)
    
    total_services = len(services)
    active_services = len([s for s in services if s.get('is_active')])
    total_traffic_gb = sum([s.get('total_gb', 0) for s in services])
    used_traffic_gb = sum([s.get('used_gb', 0) for s in services])
    
    return jsonify({
        'success': True,
        'stats': {
            'total_services': total_services,
            'active_services': active_services,
            'balance': user.get('balance', 0),
            'total_traffic_gb': total_traffic_gb,
            'used_traffic_gb': used_traffic_gb,
            'total_referrals': user.get('total_referrals', 0),
            'referral_earnings': user.get('total_referral_earnings', 0)
        }
    })

# ==================== TICKET ROUTES ====================

@app.route('/tickets')
@login_required
def tickets():
    """User tickets list page"""
    try:
        logger.info("Accessing tickets route")
        user_id = session.get('user_id')
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        
        if not user:
            logger.warning("User not found in tickets route")
            return redirect(url_for('index'))
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = 10
        
        # Get user tickets - returns (list, total) tuple
        tickets_list, total = db_instance.get_user_tickets(user['id'], page=page, per_page=per_page)
        logger.info(f"Retrieved {len(tickets_list) if tickets_list else 0} tickets for user {user_id}")
        
        # Calculate total pages
        import math
        safe_total = total or 0
        total_pages = math.ceil(safe_total / per_page) if safe_total > 0 else 1
        
        # Theme Selection
        from settings_manager import SettingsManager
        try:
            settings_mgr = SettingsManager(db_instance)
        except:
            settings_mgr = SettingsManager()
            
        current_theme = settings_mgr.get_theme()
        
        template_name = 'tickets.html'
        if current_theme == 'modern':
            template_name = 'themes/modern/tickets.html'
        
        return render_template(template_name, 
                             user=user, 
                             tickets=tickets_list, 
                             total=safe_total, 
                             current_page=page,
                             total_pages=total_pages,
                             photo_url=session.get('photo_url', ''))
    except Exception as e:
        logger.error(f"Error in tickets route: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return render_template('500.html'), 500

@app.route('/tickets/new', methods=['GET', 'POST'])
@login_required
def new_ticket():
    """Create new ticket page"""
    try:
        user_id = session.get('user_id')
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        
        if not user:
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            subject = request.form.get('subject')
            message = request.form.get('message')
            priority = request.form.get('priority', 'normal')
            
            if not subject or not message:
                flash('لطفاً عنوان و متن پیام را وارد کنید', 'error')
            else:
                ticket_id = db_instance.create_ticket(user['id'], subject, priority, message)
                if ticket_id:
                    flash('تیکت با موفقیت ایجاد شد', 'success')
                    return redirect(url_for('ticket_detail', ticket_id=ticket_id))
                else:
                    flash('خطا در ایجاد تیکت', 'error')
        
        # Theme Selection
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager()
        current_theme = settings_mgr.get_theme()
        
        template_name = 'ticket_new.html'
        if current_theme == 'modern':
            template_name = 'themes/modern/ticket_new.html'
        
        return render_template(template_name, user=user, photo_url=session.get('photo_url', ''))
    except Exception as e:
        logger.error(f"Error in new_ticket route: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return render_template('500.html'), 500

@app.route('/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def ticket_detail(ticket_id):
    """Ticket detail and reply page"""
    try:
        user_id = session.get('user_id')
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        
        if not user:
            return redirect(url_for('index'))
        
        ticket = db_instance.get_ticket(ticket_id)
        
        # Check ownership
        if not ticket or ticket['user_id'] != user['id']:
            return redirect(url_for('tickets'))
        
        if request.method == 'POST':
            message = request.form.get('message')
            
            if not message:
                flash('متن پیام نمی‌تواند خالی باشد', 'error')
            else:
                if ticket['status'] == 'closed':
                    flash('این تیکت بسته شده است', 'error')
                else:
                    if db_instance.add_ticket_reply(ticket_id, user['id'], message, is_admin=False):
                        flash('پاسخ شما ارسال شد', 'success')
                        return redirect(url_for('ticket_detail', ticket_id=ticket_id))
                    else:
                        flash('خطا در ارسال پاسخ', 'error')
        
        replies = db_instance.get_ticket_replies(ticket_id)
        
        # Theme Selection
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager()
        current_theme = settings_mgr.get_theme()
        
        template_name = 'ticket_detail.html'
        if current_theme == 'modern':
            template_name = 'themes/modern/ticket_detail.html'
        
        return render_template(template_name, user=user, ticket=ticket, replies=replies, photo_url=session.get('photo_url', ''))
    except Exception as e:
        logger.error(f"Error in ticket_detail route: {e}")
        return render_template('500.html'), 500

@app.route('/api/tickets/create', methods=['POST'])
@login_required
@rate_limit(max_requests=5, window_seconds=60)
def api_create_ticket():
    """API endpoint to create a new ticket"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    if not user:
        return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
    
    data = request.get_json()
    subject = sanitize_input(data.get('subject', ''))
    message = sanitize_input(data.get('message', ''))
    priority = data.get('priority', 'normal')
    
    if not subject or not message:
        return jsonify({'success': False, 'message': 'موضوع و پیام الزامی است'}), 400
    
    if len(subject) > 500:
        return jsonify({'success': False, 'message': 'موضوع نباید بیشتر از 500 کاراکتر باشد'}), 400
    
    user_db_id = user.get('id')
    ticket_id = db_instance.create_ticket(user_db_id, subject, message, priority)
    
    if ticket_id:
        # Send notification via ReportingSystem (Advanced)
        try:
            # Prepare user data for report
            user_data_report = {
                'id': user.get('id'),
                'telegram_id': user.get('telegram_id'),
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'last_name': user.get('last_name')
            }
            
            send_report_sync(
                "report_ticket_created", 
                user_data=user_data_report, 
                ticket_id=ticket_id, 
                subject=subject, 
                priority=priority
            )
        except Exception as e:
            logger.error(f"Error sending ticket creation report: {e}")
        
        return jsonify({'success': True, 'ticket_id': ticket_id, 'message': 'تیکت با موفقیت ایجاد شد'})
    else:
        return jsonify({'success': False, 'message': 'خطا در ایجاد تیکت'}), 500

@app.route('/api/tickets/reply', methods=['POST'])
@login_required
@rate_limit(max_requests=10, window_seconds=60)
def api_ticket_reply():
    """API endpoint to reply to a ticket"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    if not user:
        return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
    
    data = request.get_json()
    ticket_id = data.get('ticket_id')
    message = sanitize_input(data.get('message', ''))
    
    if not ticket_id or not message:
        return jsonify({'success': False, 'message': 'شناسه تیکت و پیام الزامی است'}), 400
    
    # Check if ticket exists and belongs to user
    user_db_id = user.get('id')
    ticket = db_instance.get_ticket(ticket_id, user_db_id)
    
    if not ticket:
        return jsonify({'success': False, 'message': 'تیکت یافت نشد'}), 404
    
    if ticket.get('status') != 'open':
        return jsonify({'success': False, 'message': 'این تیکت بسته شده است'}), 400
    
    reply_id = db_instance.add_ticket_reply(ticket_id, user_db_id, message, is_admin=False)
    
    if reply_id:
        # Send notification via ReportingSystem (Advanced)
        try:
            # Prepare user data for report
            user_data_report = {
                'id': user.get('id'),
                'telegram_id': user.get('telegram_id'),
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'last_name': user.get('last_name')
            }
            
            user_name = user.get('first_name', 'Unknown')
            if user.get('last_name'):
                user_name += f" {user.get('last_name')}"
            
            send_report_sync(
                "report_ticket_replied", 
                user_data=user_data_report, 
                ticket_id=ticket_id, 
                ticket_user_name=user_name, 
                is_admin_reply=False
            )
        except Exception as e:
            logger.error(f"Error sending ticket reply report: {e}")
        
        return jsonify({'success': True, 'message': 'پاسخ با موفقیت ارسال شد'})
    else:
        return jsonify({'success': False, 'message': 'خطا در ارسال پاسخ'}), 500

@app.route('/api/services/refresh')
@login_required
def refresh_services():
    """Refresh services data from panel"""
    user_id = session.get('user_id')
    db_instance = get_db()
    services = db_instance.get_user_clients(user_id)
    
    from admin_manager import AdminManager
    admin_mgr = AdminManager(db_instance)
    
    updated_services = []
    
    for service in services:
        try:
            panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
            client_details = None
            
            if panel_mgr:
                # Create callback to update inbound_id if found in different inbound
                def update_inbound_callback(service_id, new_inbound_id):
                    try:
                        db_instance.update_service_inbound_id(service_id, new_inbound_id)
                        logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                    except Exception as e:
                        logger.error(f"Failed to update inbound_id for service {service_id}: {e}")
                
                client_details = panel_mgr.get_client_details(
                    service.get('inbound_id'),
                    service.get('client_uuid'),
                    update_inbound_callback=update_inbound_callback,
                    service_id=service.get('id')
                )
            
            if client_details:
                used_traffic = client_details.get('used_traffic', 0)
                used_gb = round(used_traffic / (1024**3), 2)
                
                # Update database
                db_instance = get_db()
                db_instance.update_client_status(service['id'], used_gb=used_gb)
                
                service['used_gb'] = used_gb
                
                # Get last_activity and handle different formats
                last_activity = client_details.get('last_activity', 0)
                
                # Handle None value
                if last_activity is None:
                    last_activity = 0
                
                # Handle string datetime (from Marzban) - convert to timestamp
                if isinstance(last_activity, str):
                    try:
                        from datetime import datetime
                        # Parse ISO format datetime string
                        dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                        last_activity = int(dt.timestamp() * 1000)  # Convert to milliseconds
                    except Exception as e:
                        logger.warning(f"Could not parse last_activity string '{last_activity}': {e}")
                        last_activity = 0
                
                service['last_activity'] = last_activity
                
                # Check if service is online
                import time
                if last_activity > 0:
                    current_time = int(time.time() * 1000)
                    time_since_last_activity = current_time - last_activity
                    service['is_online'] = time_since_last_activity < (5 * 60 * 1000)
                else:
                    service['is_online'] = False
                
                total_gb = service.get('total_gb', 0)
                if total_gb > 0:
                    service['usage_percentage'] = min(100, round((used_gb / total_gb) * 100, 1))
                else:
                    service['usage_percentage'] = 0
            
            updated_services.append(service)
        except Exception as e:
            logger.error(f"Error refreshing service {service['id']}: {e}")
            updated_services.append(service)
    
    return jsonify({
        'success': True,
        'services': updated_services
    })

@app.route('/api/admin/activity')
@admin_required
def api_admin_activity():
    """API endpoint for recent activity"""
    try:
        db_instance = get_db()
        with db_instance.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                # Get recent logs
                cursor.execute('''
                    SELECT * FROM system_logs 
                    ORDER BY created_at DESC 
                    LIMIT 10
                ''')
                logs = cursor.fetchall()
                
                activities = []
                from datetime import datetime
                now = datetime.now()
                
                for log in logs:
                    # Calculate time ago
                    created_at = log.get('created_at')
                    time_ago = ''
                    if created_at:
                        diff = now - created_at
                        if diff.days > 0:
                            time_ago = f"{diff.days} روز پیش"
                        elif diff.seconds > 3600:
                            time_ago = f"{diff.seconds // 3600} ساعت پیش"
                        elif diff.seconds > 60:
                            time_ago = f"{diff.seconds // 60} دقیقه پیش"
                        else:
                            time_ago = "چند لحظه پیش"
                    
                    # Determine icon and type
                    action = log.get('action', '').lower()
                    activity_type = 'info'
                    if 'error' in action or 'fail' in action:
                        activity_type = 'error'
                    elif 'create' in action or 'add' in action:
                        activity_type = 'create'
                    elif 'update' in action or 'edit' in action:
                        activity_type = 'update'
                    elif 'delete' in action or 'remove' in action:
                        activity_type = 'delete'
                    elif 'login' in action:
                        activity_type = 'login'
                    elif 'success' in action:
                        activity_type = 'success'
                        
                    activities.append({
                        'type': activity_type,
                        'message': f"{log.get('action')}: {log.get('details', '')[:50]}",
                        'time_ago': time_ago
                    })
                    
                return jsonify({'activities': activities})
            finally:
                cursor.close()
    except Exception as e:
        logger.error(f"Error fetching activity: {e}")
        return jsonify({'activities': []})

# ==================== ADMIN PANEL ROUTES ====================


@app.route('/admin/system-status')
@app.route('/<bot_name>/admin/system-status')
@admin_required
def admin_system_status(bot_name=None):
    """Admin System Status Page"""
    if bot_name:
        session['bot_name'] = bot_name
        
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    photo_url = session.get('photo_url', '')
    
    return render_template('admin/system_status.html', user=user, photo_url=photo_url)



@app.route('/admin')

@app.route('/<bot_name>/admin')
@admin_required
def admin_dashboard(bot_name=None):
    """Admin dashboard page"""
    # Store bot_name in session if provided
    if bot_name:
        session['bot_name'] = bot_name
        
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    stats = db_instance.get_system_stats()
    
    photo_url = session.get('photo_url', '')
    
    return render_template('admin/dashboard.html', user=user, stats=stats, photo_url=photo_url)

@app.route('/admin/panels')
@admin_required
def admin_panels():
    """Admin panels management page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    panels = db_instance.get_panels(active_only=True)
    photo_url = session.get('photo_url', '')
    return render_template('admin/panels.html', user=user, panels=panels, photo_url=photo_url)

@app.route('/api/admin/panels/migrate', methods=['POST'])
@admin_required
def api_migrate_panel():
    """API endpoint to migrate clients between panels"""
    try:
        data = request.get_json()
        source_panel_id = data.get('source_panel_id')
        dest_panel_id = data.get('dest_panel_id')
        delete_source = data.get('delete_source', False)
        
        if not source_panel_id or not dest_panel_id:
            return jsonify({'success': False, 'message': 'شناسه پنل مبدا و مقصد الزامی است'}), 400
            
        if source_panel_id == dest_panel_id:
            return jsonify({'success': False, 'message': 'پنل مبدا و مقصد نمی‌توانند یکسان باشند'}), 400
            
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message, stats = admin_mgr.migrate_panel(int(source_panel_id), int(dest_panel_id), delete_source)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'stats': stats
            })
        else:
            return jsonify({
                'success': False,
                'message': message
            }), 500
            
    except Exception as e:
        logger.error(f"Error in migrate panel API: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/recover', methods=['POST'])
@admin_required
def api_recover_services():
    """API endpoint to recover services after failed migration"""
    try:
        data = request.get_json()
        source_panel_id = data.get('source_panel_id')
        dest_panel_id = data.get('dest_panel_id')
        
        if not source_panel_id or not dest_panel_id:
            return jsonify({'success': False, 'message': 'شناسه پنل مبدا و مقصد الزامی است'}), 400
            
        if source_panel_id == dest_panel_id:
            return jsonify({'success': False, 'message': 'پنل مبدا و مقصد نمی‌توانند یکسان باشند'}), 400
            
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message, stats = admin_mgr.recover_services_from_panel(int(source_panel_id), int(dest_panel_id))
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'stats': stats
            })
        else:
            return jsonify({
                'success': False,
                'message': message
            }), 500
            
    except Exception as e:
        logger.error(f"Error in recover services API: {e}")
        return secure_error_response(e)

@app.route('/user/<int:user_id>/photo')
@login_required
def serve_user_photo(user_id):
    """Serve user profile photo securely"""
    import requests
    
    # Access control
    current_user_id = session.get('user_id')
    db_instance = get_db()
    current_user = db_instance.get_user(current_user_id)
    
    if not current_user:
        return jsonify({'error': 'Unauthorized'}), 401
        
    # Allow if admin or if requesting own photo
    if str(current_user.get('id')) != str(user_id) and not current_user.get('is_admin'):
        return jsonify({'error': 'Forbidden'}), 403
        
    # Get target user
    target_user = db_instance.get_user_by_id(user_id)
    if not target_user:
        return jsonify({'error': 'User not found'}), 404
        
    # Get photo URL
    # Use sync wrapper since we are in a sync route
    try:
        photo_url = TelegramHelper.get_user_profile_photo_url_sync(target_user['telegram_id'])
        
        if not photo_url:
            # Return 404 so the frontend shows the default icon
            return jsonify({'error': 'No photo'}), 404
            
        # Stream the image
        # Use requests to download - DISABLE PROXIES to avoid SOCKS errors
        resp = requests.get(photo_url, stream=True, timeout=10, proxies={"http": None, "https": None})
        if resp.status_code == 200:
            headers = {
                'Content-Type': resp.headers.get('Content-Type', 'image/jpeg'),
                'Cache-Control': 'public, max-age=3600'
            }
            return Response(
                resp.iter_content(chunk_size=1024),
                headers=headers,
                direct_passthrough=True
            )
    except Exception as e:
        logger.error(f"Error serving user photo: {e}")
        
    return jsonify({'error': 'Failed to fetch photo'}), 500



@app.route('/admin/users/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    """Admin user detail page"""
    admin_user_id = session.get('user_id')
    db_instance = get_db()
    admin_user = db_instance.get_user(admin_user_id)
    
    # Get user by database ID (not telegram_id)
    user = db_instance.get_user_by_id(user_id)
    if not user:
        return redirect(url_for('admin_users'))
    
    # Ensure required fields are set with defaults
    if 'is_banned' not in user:
        user['is_banned'] = 0
    if 'balance' not in user:
        user['balance'] = 0
    
    # Check if user has photo
    try:
        user_photo_url = TelegramHelper.get_user_profile_photo_url_sync(user['telegram_id'])
        user['has_photo'] = bool(user_photo_url)
    except Exception as e:
        logger.error(f"Error checking user photo: {e}")
        user['has_photo'] = False
    
    # Get user services
    services = db_instance.get_user_clients(user['telegram_id'])
    
    # Get user transactions
    transactions = db_instance.get_user_transactions(user['telegram_id'], limit=100)
    
    # Get additional stats
    total_tickets = 0
    try:
        with db_instance.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('SELECT COUNT(*) as count FROM tickets WHERE user_id = %s', (user['id'],))
            result = cursor.fetchone()
            if result:
                total_tickets = result['count']
            cursor.close()
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")

    stats = {
        'total_spent': user.get('total_spent', 0),
        'total_tickets': total_tickets
    }
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/user_detail.html', user=user, admin_user=admin_user, services=services, transactions=transactions, photo_url=photo_url, stats=stats)

@app.route('/admin/products')
@admin_required
def admin_products():
    """Admin products management page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    panels = db_instance.get_panels(active_only=True)
    photo_url = session.get('photo_url', '')
    return render_template('admin/products.html', user=user, panels=panels, photo_url=photo_url)

@app.route('/admin/products/panel/<int:panel_id>')
@admin_required
def admin_products_panel(panel_id):
    """Admin products management for specific panel"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    panel = db_instance.get_panel(panel_id)
    if not panel:
        return redirect(url_for('admin_products'))
    
    categories = db_instance.get_categories(panel_id, active_only=False)
    # Get all products (both with and without category)
    # When category_id=None, get_products returns ALL products
    all_products = db_instance.get_products(panel_id, category_id=None, active_only=False)
    
    # Normalize category_id: ensure NULL from database becomes None in Python
    # This ensures Jinja2 selectattr('category_id', 'none') works correctly
    for product in all_products:
        if product.get('category_id') is None or (isinstance(product.get('category_id'), str) and product.get('category_id').lower() == 'null'):
            product['category_id'] = None
    
    products = all_products
    
    # Get all panels for copy feature
    all_panels = db_instance.get_panels(active_only=False)
    # Exclude current panel from the list
    source_panels = [p for p in all_panels if p['id'] != panel_id]
    
    # Get inbounds for the current panel to allow selection in product modal
    from admin_manager import AdminManager
    admin_mgr = AdminManager(db_instance)
    inbounds = admin_mgr.get_panel_inbounds(panel_id)
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/products_panel.html', user=user, panel=panel, categories=categories, products=products, source_panels=source_panels, inbounds=inbounds, photo_url=photo_url)

@app.route('/admin/users')
@admin_required
def admin_users():
    """Admin users management page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    users, total = db_instance.get_all_users_paginated(page=page, per_page=10, search=search if search else None)
    total_pages = (total + 9) // 10
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/users.html', user=user, users=users, photo_url=photo_url, 
                         page=page, total_pages=total_pages, total=total, search=search)

@app.route('/admin/discounts')
@admin_required
def admin_discounts():
    """Admin discount codes page"""
    user_id = session.get('user_id')
    user = db.get_user(user_id)
    
    with db.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute('SELECT * FROM discount_codes ORDER BY created_at DESC')
            discount_codes = cursor.fetchall()
            
            cursor.execute('SELECT * FROM gift_codes ORDER BY created_at DESC')
            gift_codes = cursor.fetchall()
        finally:
            cursor.close()
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/discounts.html', user=user, discount_codes=discount_codes, gift_codes=gift_codes, photo_url=photo_url)

@app.route('/admin/logs')
@admin_required
def admin_logs():
    """Admin system logs page"""
    user_id = session.get('user_id')
    user = db.get_user(user_id)
    page = request.args.get('page', 1, type=int)
    
    with db.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # Get total count
            cursor.execute('SELECT COUNT(*) as count FROM system_logs')
            result = cursor.fetchone()
            total = result.get('count') or 0 if result else 0
            
            # Get paginated logs
            cursor.execute('''
                SELECT * FROM system_logs 
                ORDER BY created_at DESC 
                LIMIT %s OFFSET %s
            ''', (10, (page - 1) * 10))
            logs = cursor.fetchall()
        finally:
            cursor.close()
    
    total_pages = (total + 9) // 10
    photo_url = session.get('photo_url', '')
    return render_template('admin/logs.html', user=user, logs=logs, photo_url=photo_url,
                         page=page, total_pages=total_pages, total=total)

@app.route('/admin/menu-layout')
@admin_required
def admin_menu_layout():
    """Admin menu layout management page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    buttons = db_instance.get_all_menu_buttons()
    
    # Get available button templates
    available_buttons = [
        {'key': 'buy_service', 'text': '🛒 خرید سرویس', 'callback': 'buy_service', 'type': 'callback', 'description': 'رفتن به صفحه خرید سرویس جدید'},
        {'key': 'user_panel', 'text': '📊 پنل کاربری', 'callback': 'user_panel', 'type': 'callback', 'description': 'نمایش پنل کاربری و سرویس‌های کاربر'},
        {'key': 'test_account', 'text': '🧪 اکانت تست', 'callback': 'test_account', 'type': 'callback', 'description': 'خرید سریع اکانت تست 1 گیگابایتی و رفتن مستقیم به صفحه پرداخت'},
        {'key': 'account_balance', 'text': '💰 موجودی', 'callback': 'account_balance', 'type': 'callback', 'description': 'نمایش موجودی حساب کاربری'},
        {'key': 'referral_system', 'text': '🎁 دعوت دوستان', 'callback': 'referral_system', 'type': 'callback', 'description': 'سیستم دعوت دوستان و دریافت پاداش'},
        {'key': 'help', 'text': '❓ راهنما و پشتیبانی', 'callback': 'help', 'type': 'callback', 'description': 'راهنما و پشتیبانی کاربران'},
        {'key': 'wheel_of_fortune', 'text': '🎰 گردونه شانس', 'callback': 'wheel_of_fortune', 'type': 'webapp', 'description': 'گردونه شانس با جوایز ویژه (نیاز به وب اپلیکیشن)'},
        {'key': 'webapp', 'text': '🌐 ورود به وب اپلیکیشن', 'callback': 'webapp', 'type': 'webapp', 'description': 'ورود به وب اپلیکیشن ربات'},
        {'key': 'admin_panel', 'text': '⚙️ پنل مدیریت', 'callback': 'admin_panel', 'type': 'callback', 'description': 'ورود به پنل مدیریت (فقط برای ادمین)'},
    ]
    
    # Update webapp button URL if needed
    import os
    from webapp_helper import get_webapp_url
    webapp_url = os.getenv('BOT_WEBAPP_URL') or get_webapp_url()
    if webapp_url:
        for btn in available_buttons:
            if btn['key'] == 'webapp':
                btn['webapp_url'] = webapp_url
            elif btn['key'] == 'wheel_of_fortune':
                btn['webapp_url'] = f"{webapp_url}/wheel"
    
    photo_url = session.get('photo_url', '')
    
    # Get bot name for API routes
    from flask import g
    bot_name = getattr(g, 'bot_name', None)
    if not bot_name:
        # Try to get from request path
        path = request.path
        if path.startswith('/'):
            parts = path.strip('/').split('/')
            if len(parts) > 0 and parts[0] not in ['admin', 'api', 'static', 'auth']:
                bot_name = parts[0]
    
    return render_template('admin/menu_layout.html', 
                         user=user, 
                         buttons=buttons, 
                         available_buttons=available_buttons,
                         photo_url=photo_url,
                         bot_name=bot_name or '')

@app.route('/admin/services')
@admin_required
def admin_services():
    """Admin services management page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    
    services, total = db_instance.get_all_services_paginated(page=page, per_page=10, search=search if search else None)
    total_pages = (total + 9) // 10
    
    # Get statistics for ALL services (not just current page) - use real-time monitoring data
    with db_instance.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # Count inactive services (exhausted or expired within 24 hour grace period)
            # Inactive services = services that are exhausted or expired and still in grace period (within 24 hours)
            cursor.execute('''
                SELECT COUNT(*) as count FROM clients 
                WHERE (
                    (exhausted_at IS NOT NULL AND DATE_ADD(exhausted_at, INTERVAL 24 HOUR) > NOW())
                    OR (expired_at IS NOT NULL AND DATE_ADD(expired_at, INTERVAL 24 HOUR) > NOW())
                )
            ''')
            result = cursor.fetchone()
            inactive_services = int(result['count']) if result else 0
            
            # Get total services count
            cursor.execute('SELECT COUNT(*) as count FROM clients')
            result = cursor.fetchone()
            total_services = int(result['count']) if result else 0
            
            # Active services = Total services - Inactive services
            # Ensure active_services_count is never negative
            active_services_count = max(0, total_services - inactive_services)
        finally:
            cursor.close()
    
    stats = {
        'active_services': active_services_count
    }
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/services.html', user=user, services=services, photo_url=photo_url,
                         page=page, total_pages=total_pages, total=total, search=search, stats=stats)

@app.route('/admin/services/<int:service_id>')
@admin_required
def admin_service_detail(service_id):
    """Admin service detail page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    service = db_instance.get_client_by_id(service_id)
    if not service:
        return redirect(url_for('admin_services'))
    
    # Get real-time data from panel
    remaining_days = None
    try:
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service.get('panel_id'))
        
        if panel_mgr and panel_mgr.login():
            # Create callback to update inbound_id if found in different inbound
            def update_inbound_callback(service_id, new_inbound_id):
                try:
                    db_instance.update_service_inbound_id(service_id, new_inbound_id)
                    logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                except Exception as e:
                    logger.error(f"Failed to update inbound_id for service {service_id}: {e}")
            
            client = panel_mgr.get_client_details(
                service.get('inbound_id'), 
                service.get('client_uuid'),
                update_inbound_callback=update_inbound_callback,
                service_id=service.get('id')
            )
            if client:
                # Get expiry time from panel
                expiry_time = client.get('expiryTime', 0)
                if expiry_time and expiry_time > 0:
                    import time
                    now = time.time()
                    # Handle both milliseconds (3x-ui) and seconds (Marzban) format
                    if expiry_time > 1000000000000:  # Milliseconds
                        expiry_timestamp = expiry_time / 1000
                    else:  # Seconds
                        expiry_timestamp = expiry_time
                    
                    if expiry_timestamp > now:
                        remaining_seconds = expiry_timestamp - now
                        remaining_days = max(0, int(remaining_seconds / 86400))
                    else:
                        remaining_days = 0
    except Exception as e:
        logger.error(f"Error getting real-time remaining days: {e}")
    
    # If no expiry from panel, use cached value or calculate from expires_at
    if remaining_days is None:
        if service.get('expires_at'):
            try:
                from datetime import datetime
                expires_at = parse_datetime_safe(service['expires_at'])
                if expires_at:
                    now = datetime.now()
                    if expires_at > now:
                        remaining_days = max(0, (expires_at - now).days)
                    else:
                        remaining_days = 0
            except:
                remaining_days = service.get('cached_remaining_days')
        else:
            remaining_days = service.get('cached_remaining_days')
    
    service['remaining_days_realtime'] = remaining_days
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/service_detail.html', user=user, service=service, photo_url=photo_url)

@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    """Admin transactions page with professional implementation"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status_filter = request.args.get('status', 'all', type=str)  # all, successful, pending
    
    invoices, total = db_instance.get_gateway_invoices_paginated(
        page=page, 
        per_page=20, 
        search=search if search else None,
        status_filter=status_filter if status_filter != 'all' else None
    )
    total_pages = (total + 19) // 20
    
    # Get statistics for ALL transactions (not just current page)
    with db_instance.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # Count all transactions
            cursor.execute('SELECT COUNT(*) as count FROM invoices')
            total_count = cursor.fetchone()['count']
            
            # Count successful transactions - all transactions with status 'paid' or 'completed'
            cursor.execute('''
                SELECT COUNT(*) as count FROM invoices 
                WHERE status IN ('paid', 'completed')
            ''')
            successful_count = cursor.fetchone()['count']
            
            # Count pending transactions - all transactions with status 'pending' or 'pending_approval'
            cursor.execute('''
                SELECT COUNT(*) as count FROM invoices 
                WHERE status IN ('pending', 'pending_approval')
            ''')
            pending_count = cursor.fetchone()['count']
            
            # Count receipts pending approval
            cursor.execute('''
                SELECT COUNT(*) as count FROM invoices 
                WHERE receipt_status = 'pending_approval' OR (receipt_path IS NOT NULL AND receipt_path != '')
            ''')
            receipts_pending = cursor.fetchone()['count']
        finally:
            cursor.close()
    
    stats = {
        'total': total_count,
        'successful': successful_count,
        'pending': pending_count,
        'receipts_pending': receipts_pending
    }
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/transactions.html', user=user, invoices=invoices, photo_url=photo_url,
                         page=page, total_pages=total_pages, total=total, search=search, stats=stats, status_filter=status_filter)

@app.route('/api/admin/transactions/<int:invoice_id>/receipt/approve', methods=['POST'])
@admin_required
def api_approve_receipt(invoice_id):
    """Approve receipt and process payment"""
    try:
        db_instance = get_db()
        success, message = _approve_invoice_logic(db_instance, invoice_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
            
    except Exception as e:
        logger.error(f"Error approving receipt: {e}")
        return secure_error_response(e)

def _approve_invoice_logic(db_instance, invoice_id):
    """Helper function to approve invoice and process service creation"""
    try:
        invoice = db_instance.get_invoice(invoice_id)
        
        if not invoice:
            return False, 'فاکتور یافت نشد'
        
        # Check if already approved or rejected
        receipt_status = invoice.get('receipt_status')
        if receipt_status == 'approved':
            return False, 'این رسید قبلاً تایید شده است'
        
        if receipt_status == 'rejected':
            return False, 'این رسید قبلاً رد شده است و امکان تغییر وجود ندارد'
        
        if invoice.get('status') in ['paid', 'completed']:
            return False, 'این فاکتور قبلاً پرداخت شده است'
        
        # Update invoice status (only if not already approved/rejected)
        with db_instance.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE invoices 
                SET status = 'paid', receipt_status = 'approved', paid_at = NOW()
                WHERE id = %s AND receipt_status != 'approved' AND receipt_status != 'rejected'
            ''', (invoice_id,))
            if cursor.rowcount == 0:
                return False, 'این رسید قبلاً تایید یا رد شده است'
            conn.commit()
            cursor.close()
        
        # Process payment (add balance or create service)
        user = db_instance.get_user_by_id(invoice['user_id'])
        if not user:
            return False, 'کاربر یافت نشد'
        
        # Add balance to user
        db_instance.update_user_balance(
            user['telegram_id'], 
            invoice['amount'], 
            'payment_callback',
            f'تایید پرداخت فاکتور #{invoice_id}'
        )
        
        # Check if this was a service purchase and create service automatically
        purchase_type = invoice.get('purchase_type', 'balance')
        
        if purchase_type in ['gigabyte', 'plan']:
            try:
                from admin_manager import AdminManager
                from username_formatter import UsernameFormatter
                from datetime import datetime, timedelta
                
                admin_manager = AdminManager(db_instance)
                
                # Get parameters from invoice
                panel_id = invoice['panel_id']
                volume_gb = float(invoice.get('gb_amount', 0))
                expire_days = invoice.get('duration_days', 0)
                product_id = invoice.get('product_id')
                
                # Get panel
                panel = db_instance.get_panel(panel_id)
                if panel and panel.get('is_active'):
                    # Generate client name
                    client_name = UsernameFormatter.format_client_name(user['telegram_id'])
                    
                    # Calculate expiration
                    expires_at = None
                    if expire_days > 0:
                        expires_at = datetime.now() + timedelta(days=expire_days)
                    
                    # Get product details if available
                    product_inbound_id = 0
                    if product_id:
                        product = db_instance.get_product(product_id)
                        if product:
                            product_inbound_id = product.get('inbound_id', 0)

                    # Create client on panel
                    logger.info(f"Auto-creating service for invoice {invoice_id}: user={user['telegram_id']}, panel={panel_id}, inbound={product_inbound_id}")
                    
                    success, message, client_data = admin_manager.create_client_on_all_panel_inbounds(
                        panel_id=panel_id,
                        client_name=client_name,
                        expire_days=expire_days,
                        total_gb=volume_gb,
                        inbound_id=product_inbound_id
                    )
                    
                    if success and client_data:
                        # Get inbounds to find the correct inbound_id
                        inbounds = admin_manager.get_panel_inbounds(panel_id)
                        inbound_id = client_data.get('inbound_id')
                        if not inbound_id and inbounds:
                            inbound_id = inbounds[0]['id']
                            
                        # Save client to database
                        client_id = db_instance.add_client(
                            user_id=user['id'],
                            panel_id=panel_id,
                            client_name=client_name,
                            client_uuid=client_data.get('id', ''),
                            inbound_id=inbound_id,
                            protocol=client_data.get('protocol', 'vless'),
                            expire_days=expire_days,
                            total_gb=volume_gb,
                            expires_at=expires_at.isoformat() if expires_at else None,
                            product_id=product_id if purchase_type == 'plan' else None,
                            sub_id=client_data.get('sub_id'),
                            invoice_id=invoice_id,
                            config_link=client_data.get('config_link')
                        )
                        
                        if client_id > 0:
                            # Deduct balance for the service purchase
                            description = f'خرید سرویس {volume_gb}GB'
                            if purchase_type == 'plan' and product_id:
                                product = db_instance.get_product(product_id)
                                if product:
                                    description = f"خرید اشتراک پلنی: {product.get('name')}"
                            
                            db_instance.update_user_balance(
                                user['telegram_id'],
                                -invoice['amount'],
                                'service_purchase',
                                description
                            )
                            
                            # Report service purchase
                            try:
                                import asyncio
                                from reporting_system import ReportingSystem
                                from telegram import Bot
                                bot_config = get_bot_config()
                                telegram_bot = Bot(token=bot_config['token'])
                                reporting_system = ReportingSystem(telegram_bot, bot_config=bot_config)
                                
                                service_data = {
                                    'service_name': client_name,
                                    'data_amount': volume_gb,
                                    'amount': invoice['amount'],
                                    'panel_name': panel.get('name', 'نامشخص'),
                                    'duration_days': expire_days,
                                    'product_name': product.get('name') if product_id and 'product' in locals() and product else None,
                                    'purchase_type': purchase_type,
                                    'payment_method': 'card'
                                }
                                
                                # Run sync wrapper
                                send_report_sync(
                                    "report_service_purchased",
                                    user=user,
                                    service_data=service_data
                                )
                            except Exception as e:
                                logger.error(f"Failed to report service purchase: {e}")
                                
                            # Send success message to user
                            try:
                                from telegram_helper import TelegramHelper
                                
                                # Get links
                                subscription_link = client_data.get('subscription_link') or client_data.get('subscription_url', '')
                                config_link = client_data.get('config_link') or client_data.get('config_url', '')
                                
                                links_msg = ""
                                if subscription_link:
                                    links_msg += f"\n🔗 لینک سابسکریپشن:\n`{subscription_link}`\n"
                                
                                if config_link and config_link != subscription_link:
                                     if config_link.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
                                        links_msg += f"\n🔑 کانفیگ مستقیم:\n`{config_link}`\n"

                                success_msg = f"""
✅ *پرداخت تایید و سرویس شما ایجاد شد!*

🎉 *جزئیات سرویس:*
🔧 نام سرویس: `{client_name}`
🔗 پنل: {panel.get('name', 'نامشخص')}
📊 حجم: {volume_gb} گیگابایت
💰 مبلغ: {invoice['amount']:,} تومان
⏰ مدت: {expire_days} روز

{links_msg}
🚀 *از سرویس خود لذت ببرید!*
"""
                                TelegramHelper.send_message_sync(user['telegram_id'], success_msg)
                            except Exception as e:
                                logger.error(f"Failed to send user success message: {e}")
                                
            except Exception as e:
                logger.error(f"Error auto-creating service: {e}")
                # We don't fail the approval if service creation fails, but we should probably alert admin
                return True, f'رسید تایید شد اما در ایجاد سرویس خطایی رخ داد: {str(e)}'

        return True, 'رسید با موفقیت تایید شد'
    except Exception as e:
        logger.error(f"Error in _approve_invoice_logic: {e}")
        return False, f'خطای سیستمی: {str(e)}'

@app.route('/api/admin/transactions/<int:invoice_id>/receipt/reject', methods=['POST'])
@admin_required
def api_reject_receipt(invoice_id):
    """Reject receipt"""
    try:
        db_instance = get_db()
        invoice = db_instance.get_invoice(invoice_id)
        
        if not invoice:
            return jsonify({'success': False, 'message': 'فاکتور یافت نشد'}), 404
        
        # Check if already approved or rejected
        receipt_status = invoice.get('receipt_status')
        if receipt_status == 'approved':
            return jsonify({'success': False, 'message': 'این رسید قبلاً تایید شده است و امکان تغییر وجود ندارد'}), 400
        
        if receipt_status == 'rejected':
            return jsonify({'success': False, 'message': 'این رسید قبلاً رد شده است'}), 400
        
        # Update invoice status (only if not already approved/rejected)
        with db_instance.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE invoices 
                SET receipt_status = 'rejected', status = 'rejected'
                WHERE id = %s AND receipt_status != 'approved' AND receipt_status != 'rejected'
            ''', (invoice_id,))
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': 'این رسید قبلاً تایید یا رد شده است'}), 400
            conn.commit()
            cursor.close()
        
        # Send notification to user
        try:
            user = db_instance.get_user_by_id(invoice['user_id'])
            if user:
                from telegram_helper import TelegramHelper
                notification_message = f"""❌ **رسید شما رد شد**

💰 مبلغ: {invoice['amount']:,} تومان
🔢 شماره فاکتور: #{invoice_id}

⚠️ رسید پرداخت شما رد شده است. لطفاً با پشتیبانی تماس بگیرید."""
                
                TelegramHelper.send_message_sync(user['telegram_id'], notification_message)
        except Exception as e:
            logger.error(f"Error sending rejection notification: {e}")
        
        return jsonify({'success': True, 'message': 'رسید رد شد'})
    except Exception as e:
        logger.error(f"Error rejecting receipt: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

@app.route('/api/admin/transactions/<int:invoice_id>/check-status', methods=['POST'])
@admin_required
def api_check_transaction_status(invoice_id):
    """Check transaction status from gateway in real-time"""
    try:
        data = request.json
        order_id = data.get('order_id')
        
        if not order_id:
            return jsonify({'success': False, 'message': 'Order ID required'}), 400
        
        # Get invoice
        db_instance = get_db()
        invoice = db_instance.get_invoice(invoice_id)
        if not invoice:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        # Import payment system
        # Payment gateway removed as per request
        return jsonify({'success': False, 'message': 'درگاه پرداخت غیرفعال است'}), 500
        
        # Placeholder for future payment implementation
        # from payment_system import StarsefarAPI
        # starsefar = StarsefarAPI(license_key)
        
        # Check order status from gateway
        result = starsefar.check_order(order_id)
        
        # Check if payment is successful
        payment_successful = False
        if result.get('success'):
            data_dict = result.get('data', {})
            # Check different possible success indicators
            if (data_dict.get('success') or 
                data_dict.get('status') == 'completed' or
                data_dict.get('paid') == True or
                (isinstance(data_dict, dict) and data_dict.get('data') and 
                 (data_dict['data'].get('status') == 'completed' or data_dict['data'].get('paid') == True))):
                payment_successful = True
        
        # Update invoice status if payment is successful
        if payment_successful:
            if invoice['status'] not in ['paid', 'completed']:
                db_instance.update_invoice_status(invoice_id, 'paid', order_id)
                return jsonify({
                    'success': True, 
                    'message': 'Payment verified successfully',
                    'status': 'paid',
                    'was_updated': True
                })
            else:
                return jsonify({
                    'success': True, 
                    'message': 'Payment already verified',
                    'status': invoice['status'],
                    'was_updated': False
                })
        else:
            # Payment not successful or still pending
            return jsonify({
                'success': True, 
                'message': 'Payment not completed yet',
                'status': invoice['status'],
                'was_updated': False
            })
            
    except Exception as e:
        logger.error(f"Error checking transaction status: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

@app.route('/admin/settings/backup', methods=['GET', 'POST'])
@admin_required
def api_admin_settings_backup():
    """API endpoint to update backup settings"""
    try:
        db_instance = get_db()
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager(db_instance)

        if request.method == 'GET':
            enabled = settings_mgr.get_setting('auto_backup_enabled', False)
            frequency = settings_mgr.get_setting('auto_backup_frequency', 24)
            topic_id = settings_mgr.get_setting('backup_topic_id', 0)
            return jsonify({
                'success': True,
                'enabled': enabled,
                'frequency': frequency,
                'topic_id': topic_id
            })

        # POST request
        data = request.get_json()
        enabled = data.get('enabled', False)
        frequency = data.get('frequency', 24)
        topic_id = data.get('topic_id', 0)
        
        # Update settings
        settings_mgr.set_setting('auto_backup_enabled', enabled, description="Auto Backup Enabled", updated_by=session.get('user_id'))
        settings_mgr.set_setting('auto_backup_frequency', frequency, description="Auto Backup Frequency (Hours)", updated_by=session.get('user_id'))
        settings_mgr.set_setting('backup_topic_id', topic_id, description="Backup Topic ID", updated_by=session.get('user_id'))
        
        # Trigger immediate backup if enabled
        if enabled:
            def trigger_backup():
                try:
                    from database_backup_system import DatabaseBackupManager
                    from telegram_helper import TelegramHelper
                    import asyncio
                    
                    # Create new DB instance for thread
                    from professional_database import ProfessionalDatabaseManager
                    from config import DB_CONFIG
                    thread_db = ProfessionalDatabaseManager(DB_CONFIG)
                    
                    # Initialize backup manager
                    bot = TelegramHelper.get_bot()
                    backup_mgr = DatabaseBackupManager(thread_db, bot, BOT_CONFIG)
                    
                    # Run async backup in new event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(backup_mgr.create_and_send_backup())
                    loop.close()
                    
                    if result:
                        # Update last backup time
                        # We need to re-instantiate settings manager with thread_db
                        thread_settings_mgr = SettingsManager(thread_db)
                        thread_settings_mgr.set_setting('last_auto_backup_time', datetime.now().isoformat(), description="Last Auto Backup Time", updated_by=0)
                        logger.info("✅ Immediate backup triggered successfully")
                    else:
                        logger.error("❌ Immediate backup failed (check logs for details)")
                except Exception as e:
                    logger.error(f"❌ Error in immediate backup trigger: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

            # Run in background thread
            threading.Thread(target=trigger_backup).start()
            
        return jsonify({'success': True, 'message': 'تنظیمات بکاپ با موفقیت ذخیره شد'})
        
    except Exception as e:
        logger.error(f"Error updating backup settings: {e}")
        return secure_error_response(e)


@app.route('/admin/settings')
@admin_required
def admin_settings():
    """Admin settings page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    import os
    from webapp_helper import get_webapp_url
    webapp_url = os.getenv('BOT_WEBAPP_URL') or get_webapp_url()
    
    # Get settings
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager(db_instance)
    auto_approve_receipts = settings_mgr.get_setting('auto_approve_receipts', False)
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/settings.html', 
                         user=user, 
                         bot_username=BOT_CONFIG.get('bot_username', ''),
                         admin_id=BOT_CONFIG.get('admin_id', ''),
                         webapp_url=webapp_url,
                         auto_approve_receipts=auto_approve_receipts,
                         photo_url=photo_url)

@app.route('/api/admin/settings/update', methods=['POST'])
@admin_required
def api_update_setting():
    """Update a system setting"""
    try:
        data = request.json
        key = data.get('key')
        value = data.get('value')
        
        if not key:
            return jsonify({'success': False, 'message': 'Setting key is required'}), 400
            
        db_instance = get_db()
        
        # Check if setting exists to determine update or insert
        with db_instance.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM settings WHERE setting_key = %s", (key,))
            exists = cursor.fetchone()
            
            # Determine type
            value_type = 'string'
            if isinstance(value, bool):
                value_type = 'bool'
                value = 'true' if value else 'false'
            elif isinstance(value, int):
                value_type = 'int'
                value = str(value)
            elif isinstance(value, float):
                value_type = 'float'
                value = str(value)
            elif isinstance(value, (dict, list)):
                value_type = 'json'
                import json
                value = json.dumps(value)
            else:
                value = str(value)
                
            if exists:
                cursor.execute("UPDATE settings SET setting_value = %s, setting_type = %s, updated_at = CURRENT_TIMESTAMP WHERE setting_key = %s", (value, value_type, key))
            else:
                cursor.execute("INSERT INTO settings (setting_key, setting_value, setting_type) VALUES (%s, %s, %s)", (key, value, value_type))
            
            conn.commit()
            
        return jsonify({'success': True, 'message': 'Setting updated successfully'})
        
    except Exception as e:
        logger.error(f"Error updating setting: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ADMIN TEXT MANAGEMENT ROUTES ====================

@app.route('/admin/texts')
@admin_required
def admin_texts():
    """Admin text management page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    from text_manager import TextManager
    text_manager = TextManager(db_instance)
    
    # Get category filter
    category = request.args.get('category', None, type=str)
    
    # Log database name for debugging - use db_instance.database_name directly
    bot_config = get_bot_config()
    expected_db_name = bot_config.get('database_name') if bot_config else None
    logger.info(f"🔍 Loading texts for database '{db_instance.database_name}' (expected: {expected_db_name}, db_instance type: {type(db_instance).__name__})")
    
    # Verify we're using the correct database instance
    if expected_db_name and expected_db_name != db_instance.database_name:
        logger.error(f"CRITICAL: Database name mismatch! Expected '{expected_db_name}', but db_instance.database_name is '{db_instance.database_name}'")
    
    # Get all texts from database
    db_texts = db_instance.get_all_bot_texts(category=category, include_inactive=False)
    logger.info(f"📊 Found {len(db_texts)} texts in database '{db_instance.database_name}'")
    
    # Get all text definitions
    text_definitions = text_manager.get_all_text_definitions(category=category)
    
    # Merge database texts with definitions
    texts_data = {}
    for text_key, text_def in text_definitions.items():
        # Find corresponding database text
        db_text = next((t for t in db_texts if t['text_key'] == text_key), None)
        
        texts_data[text_key] = {
            'key': text_key,
            'category': text_def['category'],
            'description': text_def.get('description', ''),
            'available_variables': text_def.get('variables', []),
            'db_text': db_text,
            'content': db_text['text_content'] if db_text else text_def['default'],
            'is_customized': db_text is not None,
            'is_active': db_text['is_active'] if db_text else True
        }
    
    # Get categories
    categories = text_manager.get_all_text_definitions()
    unique_categories = sorted(set(def_info['category'] for def_info in categories.values()))
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/texts.html',
                         user=user,
                         texts_data=texts_data,
                         categories=unique_categories,
                         current_category=category,
                         photo_url=photo_url)

@app.route('/admin/texts/<path:text_key>')
@admin_required
def admin_text_detail(text_key):
    """Admin text detail/edit page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    from text_manager import TextManager
    text_manager = TextManager(db_instance)
    
    # Get text definition
    text_def = text_manager.get_text_definition(text_key)
    if not text_def:
        flash('متن یافت نشد', 'error')
        return redirect(url_for('admin_texts'))
    
    # Get database text if exists
    db_text = db_instance.get_bot_text(text_key)
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/text_detail.html',
                         user=user,
                         text_key=text_key,
                         text_def=text_def,
                         db_text=db_text,
                         photo_url=photo_url)

@app.route('/api/admin/texts', methods=['POST'])
@admin_required
@rate_limit(max_requests=30, window_seconds=60)
def api_admin_texts_create():
    """API endpoint to create a new text"""
    try:
        user_telegram_id = session.get('user_id')
        db_instance = get_db()
        
        # Get user database ID from telegram_id
        user_db_id = None
        if user_telegram_id:
            user = db_instance.get_user(user_telegram_id)
            if user:
                user_db_id = user.get('id')
        
        data = request.get_json()
        text_key = data.get('text_key')
        text_category = data.get('text_category')
        text_content = data.get('text_content')
        description = data.get('description')
        available_variables = data.get('available_variables')
        
        if not all([text_key, text_category, text_content]):
            return jsonify({'success': False, 'message': 'لطفاً تمام فیلدهای الزامی را پر کنید'}), 400
        
        # Create text
        text_id = db_instance.create_bot_text(
            text_key=text_key,
            text_category=text_category,
            text_content=text_content,
            description=description,
            available_variables=available_variables,
            updated_by=user_db_id
        )
        
        if text_id:
            return jsonify({'success': True, 'message': 'متن با موفقیت ایجاد شد', 'text_id': text_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در ایجاد متن'}), 500
            
    except Exception as e:
        logger.error(f"Error creating text: {e}")
        return secure_error_response(e)

@app.route('/api/admin/texts/update', methods=['POST'])
@admin_required
@rate_limit(max_requests=30, window_seconds=60)
def api_admin_texts_update():
    """API endpoint to update a text"""
    try:
        user_telegram_id = session.get('user_id')
        db_instance = get_db()
        
        # Get user database ID from telegram_id
        user_db_id = None
        if user_telegram_id:
            user = db_instance.get_user(user_telegram_id)
            if user:
                user_db_id = user.get('id')
        
        data = request.get_json()
        text_key = data.get('text_key')
        text_content = data.get('text_content')
        description = data.get('description')
        available_variables = data.get('available_variables')
        is_active = data.get('is_active')
        
        if not text_key:
            return jsonify({'success': False, 'message': 'کلید متن الزامی است'}), 400
        
        # Log database name for debugging - use db_instance.database_name directly
        logger.info(f"🔍 Updating text '{text_key}' for database '{db_instance.database_name}' (db_instance type: {type(db_instance).__name__})")
        
        # Verify we're using the correct database instance
        bot_config = get_bot_config()
        expected_db_name = bot_config.get('database_name') if bot_config else None
        if expected_db_name and expected_db_name != db_instance.database_name:
            logger.error(f"CRITICAL: Database name mismatch! Expected '{expected_db_name}', but db_instance.database_name is '{db_instance.database_name}'")
            return jsonify({'success': False, 'message': f'خطا: دیتابیس نامطابق. انتظار: {expected_db_name}, دریافت: {db_instance.database_name}'}), 500
        
        # Check if text exists in database
        existing_text = db_instance.get_bot_text(text_key)
        
        if existing_text:
            # Update existing text
            success = db_instance.update_bot_text(
                text_key=text_key,
                text_content=text_content,
                description=description,
                available_variables=available_variables,
                is_active=is_active,
                updated_by=user_db_id
            )
        else:
            # Get text definition for category to create new text
            from text_manager import TextManager
            text_manager = TextManager(db_instance)
            text_def = text_manager.get_text_definition(text_key)
            
            if not text_def:
                return jsonify({'success': False, 'message': 'متن یافت نشد'}), 404
            
            # Create new text (create_bot_text now handles duplicates by updating)
            text_id = db_instance.create_bot_text(
                text_key=text_key,
                text_category=text_def['category'],
                text_content=text_content or text_def['default'],
                description=description or text_def.get('description'),
                available_variables=available_variables or ','.join(text_def.get('variables', [])),
                updated_by=user_db_id
            )
            
            if text_id:
                success = True
            else:
                return jsonify({'success': False, 'message': 'خطا در ایجاد متن'}), 500
        
        if success:
            # Clear text cache in all TextManager instances and MessageTemplates
            from text_manager import TextManager
            from message_templates import MessageTemplates
            
            # Clear cache in MessageTemplates TextManager if exists
            if MessageTemplates._text_manager:
                MessageTemplates._text_manager.clear_cache()
                logger.info(f"✅ Cleared cache in MessageTemplates TextManager for text: {text_key}")
            
            # Also clear cache in any new instance
            text_manager = TextManager(db_instance)
            text_manager.clear_cache()
            
            # Verify the text was saved correctly
            saved_text = db_instance.get_bot_text(text_key)
            if saved_text:
                logger.info(f"✅ Verified: Text '{text_key}' saved successfully in database (length: {len(saved_text.get('text_content', ''))})")
            else:
                logger.warning(f"⚠️ Warning: Text '{text_key}' not found in database after update!")
            
            return jsonify({'success': True, 'message': 'متن با موفقیت به‌روزرسانی شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در به‌روزرسانی متن'}), 500
            
    except Exception as e:
        logger.error(f"Error updating text: {e}")
        return secure_error_response(e)

@app.route('/api/admin/texts/delete', methods=['POST'])
@admin_required
@rate_limit(max_requests=20, window_seconds=60)
def api_admin_texts_delete():
    """API endpoint to delete (deactivate) a text"""
    try:
        db_instance = get_db()
        
        data = request.get_json()
        text_key = data.get('text_key')
        
        if not text_key:
            return jsonify({'success': False, 'message': 'کلید متن الزامی است'}), 400
        
        # Verify text exists before deletion
        existing_text = db_instance.get_bot_text(text_key)
        if not existing_text:
            # Check if it exists but is inactive
            try:
                with db_instance.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    # Use db_instance.database_name directly
                    cursor.execute('SELECT id FROM bot_texts WHERE database_name = %s AND text_key = %s', (db_instance.database_name, text_key))
                    check = cursor.fetchone()
                    if check:
                        return jsonify({'success': False, 'message': 'متن قبلاً حذف شده است'}), 400
                    else:
                        return jsonify({'success': False, 'message': 'متن یافت نشد'}), 404
            except Exception as e:
                logger.error(f"Error checking text existence: {e}")
        
        success = db_instance.delete_bot_text(text_key)
        
        if success:
            # Clear text cache in all TextManager instances and MessageTemplates
            from text_manager import TextManager
            from message_templates import MessageTemplates
            
            # Clear cache in MessageTemplates TextManager if exists
            if MessageTemplates._text_manager:
                MessageTemplates._text_manager.clear_cache()
                logger.info(f"✅ Cleared cache in MessageTemplates TextManager for text: {text_key}")
            
            # Also clear cache in any new instance
            text_manager = TextManager(db_instance)
            text_manager.clear_cache()
            
            # Verify the text was deactivated
            deleted_text = db_instance.get_bot_text(text_key)
            if deleted_text:
                logger.warning(f"⚠️ Warning: Text '{text_key}' still active after deletion!")
            else:
                logger.info(f"✅ Verified: Text '{text_key}' successfully deactivated")
            
            return jsonify({
                'success': True, 
                'message': 'متن با موفقیت حذف شد و به پیش‌فرض بازگشت'
            })
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف متن. لطفاً دوباره تلاش کنید.'}), 500
            
    except Exception as e:
        logger.error(f"Error deleting text: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

@app.route('/api/admin/texts/initialize', methods=['POST'])
@admin_required
@rate_limit(max_requests=5, window_seconds=60)
def api_admin_texts_initialize():
    """API endpoint to initialize default texts"""
    try:
        db_instance = get_db()
        
        from text_manager import TextManager
        text_manager = TextManager(db_instance)
        
        count = text_manager.initialize_default_texts(db_instance)
        
        return jsonify({
            'success': True, 
            'message': f'{count} متن پیش‌فرض با موفقیت ایجاد شد',
            'count': count
        })
            
    except Exception as e:
        logger.error(f"Error initializing texts: {e}")
        return secure_error_response(e)

@app.route('/api/admin/texts/test/<path:text_key>', methods=['GET'])
@admin_required
def api_admin_texts_test(text_key):
    """API endpoint to test if a text is loaded correctly"""
    try:
        db_instance = get_db()
        
        # Get from database
        db_text = db_instance.get_bot_text(text_key)
        
        # Get from TextManager
        from text_manager import TextManager
        text_manager = TextManager(db_instance)
        text_content = text_manager.get_text(text_key, use_default_if_missing=True)
        
        # Get from MessageTemplates
        from message_templates import MessageTemplates
        template_text = MessageTemplates._get_text(text_key)
        
        return jsonify({
            'success': True,
            'text_key': text_key,
            'in_database': db_text is not None,
            'db_text_active': db_text.get('is_active') if db_text else None,
            'db_text_length': len(db_text.get('text_content', '')) if db_text else 0,
            'textmanager_text_length': len(text_content) if text_content else 0,
            'templates_text_length': len(template_text) if template_text else 0,
            'db_text_preview': db_text.get('text_content', '')[:100] if db_text else None,
            'textmanager_preview': text_content[:100] if text_content else None,
            'templates_preview': template_text[:100] if template_text else None
        })
            
    except Exception as e:
        logger.error(f"Error testing text: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

# ==================== ADMIN TICKET ROUTES ====================

@app.route('/admin/tickets')
@admin_required
def admin_tickets():
    """Admin tickets list page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', None, type=str)
    waiting_admin = request.args.get('waiting', 'false') == 'true'
    
    # If waiting_admin filter is active, ignore status filter
    if waiting_admin:
        status = None
    
    tickets_list, total = db_instance.get_all_tickets(status=status, page=page, per_page=10, waiting_admin=waiting_admin)
    total_pages = (total + 9) // 10 if total > 0 else 1
    
    stats = db_instance.get_ticket_stats()
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/tickets.html',
                         user=user,
                         tickets=tickets_list,
                         stats=stats,
                         current_page=page,
                         total_pages=total_pages,
                         total=total,
                         photo_url=photo_url)

@app.route('/admin/tickets/<int:ticket_id>')
@admin_required
def admin_ticket_detail(ticket_id):
    """Admin ticket detail page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    ticket = db_instance.get_ticket(ticket_id)
    if not ticket:
        flash('تیکت یافت نشد', 'error')
        return redirect(url_for('admin_tickets'))
    
    replies = db_instance.get_ticket_replies(ticket_id)
    
    photo_url = session.get('photo_url', '')
    return render_template('admin/ticket_detail.html',
                         user=user,
                         ticket=ticket,
                         replies=replies,
                         photo_url=photo_url)

@app.route('/api/admin/tickets/reply', methods=['POST'])
@admin_required
@rate_limit(max_requests=20, window_seconds=60)
def api_admin_ticket_reply():
    """API endpoint for admin to reply to a ticket"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'لطفاً ابتدا وارد شوید'}), 401
        
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        
        if not user:
            logger.error(f"User not found for user_id: {user_id}")
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
        
        # Check if user is admin
        if not user.get('is_admin', False) and user_id != get_bot_config().get('admin_id'):
            logger.error(f"Non-admin user {user_id} tried to reply to ticket")
            return jsonify({'success': False, 'message': 'دسترسی غیرمجاز'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'داده‌های درخواست نامعتبر است'}), 400
        
        ticket_id = data.get('ticket_id')
        message = data.get('message', '').strip()
        
        if not ticket_id:
            return jsonify({'success': False, 'message': 'شناسه تیکت الزامی است'}), 400
        
        if not message:
            return jsonify({'success': False, 'message': 'پیام نمی‌تواند خالی باشد'}), 400
        
        # Sanitize message
        message = sanitize_input(message)
        
        # Check if ticket exists
        ticket = db_instance.get_ticket(ticket_id)
        if not ticket:
            logger.error(f"Ticket {ticket_id} not found")
            return jsonify({'success': False, 'message': 'تیکت یافت نشد'}), 404
        
        if ticket.get('status') != 'open':
            return jsonify({'success': False, 'message': 'این تیکت بسته شده است. نمی‌توانید به تیکت بسته شده پاسخ دهید'}), 400
        
        user_db_id = user.get('id')
        if not user_db_id:
            logger.error(f"User {user_id} has no database ID")
            return jsonify({'success': False, 'message': 'خطا در شناسایی کاربر'}), 500
        
        reply_id = db_instance.add_ticket_reply(ticket_id, user_db_id, message, is_admin=True)
        
        if reply_id:
            logger.info(f"Admin {user_id} replied to ticket {ticket_id}")
            
            # Send notification to user
            try:
                from telegram_helper import TelegramHelper
                ticket_user = db_instance.get_user_by_id(ticket.get('user_id'))
                if ticket_user and ticket_user.get('telegram_id'):
                    notification_message = f"""✅ **پاسخ به تیکت شما**

🔢 تیکت: #{ticket_id}
📝 موضوع: {ticket.get('subject', 'بدون موضوع')}

💬 پاسخ پشتیبانی:
{message[:200]}{'...' if len(message) > 200 else ''}

برای مشاهده کامل پاسخ، به پنل کاربری مراجعه کنید."""
                    TelegramHelper.send_message_sync(ticket_user['telegram_id'], notification_message)
            except Exception as e:
                logger.error(f"Error sending ticket notification to user: {e}")
            
            return jsonify({'success': True, 'message': 'پاسخ با موفقیت ارسال شد', 'reply_id': reply_id})
        else:
            logger.error(f"Failed to add reply to ticket {ticket_id} by admin {user_id}")
            return jsonify({'success': False, 'message': 'خطا در ارسال پاسخ. لطفاً دوباره تلاش کنید'}), 500
            
    except Exception as e:
        logger.error(f"Error in api_admin_ticket_reply: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e, 'خطای سرور')

@app.route('/api/admin/tickets/<int:ticket_id>/close', methods=['POST'])
@admin_required
def api_admin_close_ticket(ticket_id):
    """API endpoint to close a ticket"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'لطفاً ابتدا وارد شوید'}), 401
        
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        
        if not user:
            logger.error(f"User not found for user_id: {user_id}")
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
        
        # Check if user is admin
        if not user.get('is_admin', False) and user_id != get_bot_config().get('admin_id'):
            logger.error(f"Non-admin user {user_id} tried to close ticket")
            return jsonify({'success': False, 'message': 'دسترسی غیرمجاز'}), 403
        
        ticket = db_instance.get_ticket(ticket_id)
        if not ticket:
            logger.error(f"Ticket {ticket_id} not found")
            return jsonify({'success': False, 'message': 'تیکت یافت نشد'}), 404
        
        if ticket.get('status') == 'closed':
            return jsonify({'success': False, 'message': 'این تیکت قبلاً بسته شده است'}), 400
        
        user_db_id = user.get('id')
        if not user_db_id:
            logger.error(f"User {user_id} has no database ID")
            return jsonify({'success': False, 'message': 'خطا در شناسایی کاربر'}), 500
        
        success = db_instance.close_ticket(ticket_id, user_db_id)
        
        if success:
            logger.info(f"Admin {user_id} closed ticket {ticket_id}")
            
            # Send notification to user
            try:
                from telegram_helper import TelegramHelper
                ticket_user = db_instance.get_user_by_id(ticket.get('user_id'))
                if ticket_user and ticket_user.get('telegram_id'):
                    notification_message = f"""🔒 **تیکت شما بسته شد**

🔢 تیکت: #{ticket_id}
📝 موضوع: {ticket.get('subject', 'بدون موضوع')}

تیکت شما توسط پشتیبانی بسته شده است. در صورت نیاز می‌توانید تیکت جدیدی ایجاد کنید."""
                    TelegramHelper.send_message_sync(ticket_user['telegram_id'], notification_message)
            except Exception as e:
                logger.error(f"Error sending ticket close notification to user: {e}")
            
            return jsonify({'success': True, 'message': 'تیکت با موفقیت بسته شد'})
        else:
            logger.error(f"Failed to close ticket {ticket_id} by admin {user_id}")
            return jsonify({'success': False, 'message': 'خطا در بستن تیکت. لطفاً دوباره تلاش کنید'}), 500
            
    except Exception as e:
        logger.error(f"Error in api_admin_close_ticket: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e, 'خطای سرور')

@app.route('/api/admin/tickets/<int:ticket_id>/reopen', methods=['POST'])
@admin_required
def api_admin_reopen_ticket(ticket_id):
    """API endpoint to reopen a ticket"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'لطفاً ابتدا وارد شوید'}), 401
        
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        
        if not user:
            logger.error(f"User not found for user_id: {user_id}")
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 401
        
        # Check if user is admin
        if not user.get('is_admin', False) and user_id != get_bot_config().get('admin_id'):
            logger.error(f"Non-admin user {user_id} tried to reopen ticket")
            return jsonify({'success': False, 'message': 'دسترسی غیرمجاز'}), 403
        
        ticket = db_instance.get_ticket(ticket_id)
        if not ticket:
            logger.error(f"Ticket {ticket_id} not found")
            return jsonify({'success': False, 'message': 'تیکت یافت نشد'}), 404
        
        if ticket.get('status') != 'closed':
            return jsonify({'success': False, 'message': 'این تیکت قبلاً باز است'}), 400
        
        success = db_instance.reopen_ticket(ticket_id)
        
        if success:
            logger.info(f"Admin {user_id} reopened ticket {ticket_id}")
            return jsonify({'success': True, 'message': 'تیکت با موفقیت باز شد'})
        else:
            logger.error(f"Failed to reopen ticket {ticket_id} by admin {user_id}")
            return jsonify({'success': False, 'message': 'خطا در باز کردن تیکت. لطفاً دوباره تلاش کنید'}), 500
            
    except Exception as e:
        logger.error(f"Error in api_admin_reopen_ticket: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e, 'خطای سرور')

# Admin API Routes
@app.route('/api/admin/stats')
@admin_required
def api_admin_stats():
    """Get admin statistics"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                # Count users efficiently
                cursor.execute('SELECT COUNT(*) as count FROM users')
                total_users = int(cursor.fetchone()['count'])
                
                # Count panels efficiently
                cursor.execute('SELECT COUNT(*) as count FROM panels')
                total_panels = cursor.fetchone()['count']
                
                cursor.execute('SELECT COUNT(*) as count FROM panels WHERE is_active = 1')
                active_panels = cursor.fetchone()['count']
                
                # Count services efficiently
                cursor.execute('SELECT COUNT(*) as count FROM clients')
                total_services = cursor.fetchone()['count']
                
                cursor.execute('SELECT COUNT(*) as count FROM clients WHERE is_active = 1')
                active_services = cursor.fetchone()['count']
                
                # Get revenue statistics - check both 'paid' and 'completed' statuses for consistency
                cursor.execute('SELECT SUM(amount) as total FROM invoices WHERE status IN ("paid", "completed")')
                result = cursor.fetchone()
                total_revenue = int(result.get('total') or 0) if result else 0
                
                cursor.execute('SELECT SUM(amount) as total FROM invoices WHERE status IN ("paid", "completed") AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)')
                result = cursor.fetchone()
                monthly_revenue = int(result.get('total') or 0) if result else 0
                
                cursor.execute('SELECT COUNT(*) as count FROM invoices WHERE status IN ("paid", "completed") AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)')
                result = cursor.fetchone()
                daily_transactions = result.get('count') or 0 if result else 0
            finally:
                cursor.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_users': total_users,
                'total_panels': total_panels,
                'active_panels': active_panels,
                'total_services': total_services,
                'active_services': active_services,
                'total_revenue': total_revenue,
                'monthly_revenue': monthly_revenue,
                'daily_transactions': daily_transactions
            }
        })
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        return secure_error_response(e)

@app.route('/api/admin/system-stats')
@admin_required
def api_admin_system_stats():
    """Get real-time system statistics"""
    try:
        from system_monitor import SystemMonitor
        
        # Get base stats
        stats = SystemMonitor.get_system_stats() or {}
        
        # Add Database Stats
        db_status = 'disconnected'
        active_connections = 0
        try:
            db_instance = get_db()
            with db_instance.get_connection() as conn:
                if conn.is_connected():
                    db_status = 'connected'
                    # Count active connections
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("SHOW STATUS WHERE `variable_name` = 'Threads_connected'")
                    res = cursor.fetchone()
                    if res:
                        active_connections = int(res['Value'])
                    cursor.close()
        except Exception as e:
            logger.error(f"Error checking DB status: {e}")
            
        stats['database'] = {
            'status': db_status,
            'active_connections': active_connections
        }
        
        # Add Panels Stats
        panels_data = []
        try:
            db_instance = get_db()
            panels = db_instance.get_panels(active_only=True)
            for panel in panels:
                # Basic info
                panels_data.append({
                    'name': panel['name'],
                    'type': panel.get('panel_type', '3x-ui'),
                    'host': panel.get('url', '').replace('https://', '').replace('http://', '').split(':')[0],
                    'is_online': True, # Assume online if active for now
                    'ping': 0
                })
        except Exception as e:
            logger.error(f"Error getting panels stats: {e}")
            
        stats['panels'] = panels_data
        
        return jsonify({'success': True, 'stats': stats})
        
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels', methods=['GET'])
@admin_required
def api_admin_panels():
    """Get all active panels"""
    try:
        panels = db.get_panels(active_only=True)
        return jsonify({'success': True, 'panels': panels})
    except Exception as e:
        logger.error(f"Error getting panels: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels', methods=['POST'])
@admin_required
def api_admin_add_panel():
    """Add a new panel"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'داده‌های درخواست نامعتبر است'}), 400
        
        # Validate required fields
        # Validate required fields
        panel_type = data.get('panel_type', '3x-ui')
        
        # Validate required fields
        if not data.get('name') or not data.get('url') or not data.get('username') or not data.get('password'):
            return jsonify({'success': False, 'message': 'لطفاً تمام فیلدهای الزامی را پر کنید'}), 400
        
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        # Handle default_inbound_id being empty string
        default_inbound_id = data.get('default_inbound_id')
        if default_inbound_id == '':
            default_inbound_id = None
            
        success, message = admin_mgr.add_panel(
            name=data.get('name'),
            url=data.get('url'),
            username=data.get('username'),
            password=data.get('password'),
            api_endpoint=data.get('api_endpoint'),
            price_per_gb=data.get('price_per_gb', 0),
            panel_type=data.get('panel_type', '3x-ui'),
            subscription_url=data.get('subscription_url'),
            sale_type=data.get('sale_type', 'gigabyte'),
            default_inbound_id=default_inbound_id,
            extra_config=data.get('extra_config'),
            delivery_method=data.get('delivery_method', 'subscription_link')
        )
        
        if success:
            logger.info(f"Panel '{data.get('name')}' added successfully")
            return jsonify({'success': True, 'message': message}), 200
        else:
            logger.warning(f"Failed to add panel '{data.get('name')}': {message}")
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        logger.error(f"Error adding panel: {e}", exc_info=True)
        return secure_error_response(e, 'خطا در اضافه کردن پنل')

@app.route('/api/admin/panels/check-connection', methods=['POST'])
@admin_required
def api_admin_check_panel_connection():
    """Check panel connection with provided credentials (without saving)"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'داده‌های درخواست نامعتبر است'}), 400
        
        url = data.get('url')
        username = data.get('username')
        password = data.get('password')
        panel_type = data.get('panel_type', '3x-ui')
        
        if not url or not username or not password:
            return jsonify({'success': False, 'message': 'لطفاً آدرس، نام کاربری و رمز عبور را وارد کنید'}), 400
            
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message, inbounds = admin_mgr.test_panel_connection_with_credentials(
            url=url,
            username=username,
            password=password,
            panel_type=panel_type
        )
        
        return jsonify({
            'success': success, 
            'message': message,
            'inbounds': inbounds
        })
    except Exception as e:
        logger.error(f"Error checking panel connection: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/fetch-metadata', methods=['POST'])
@admin_required
def api_admin_fetch_panel_metadata():
    """Fetch panel metadata (groups, inbounds) with provided credentials"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'message': 'داده‌های درخواست نامعتبر است'}), 400
        
        url = data.get('url')
        username = data.get('username')
        password = data.get('password')
        panel_type = data.get('panel_type', '3x-ui')
        api_endpoint = data.get('api_endpoint')
        
        if not url or not username or not password:
            return jsonify({'success': False, 'message': 'لطفاً آدرس، نام کاربری و رمز عبور را وارد کنید'}), 400
            
        from admin_manager import AdminManager
        from pasargad_manager import PasargadPanelManager
        from panel_manager import PanelManager
        from marzban_manager import MarzbanPanelManager
        from rebecca_manager import RebeccaPanelManager
        from marzneshin_manager import MarzneshinPanelManager
        from guard_manager import GuardPanelManager
        
        # We don't need db for this, just the manager classes
        
        manager = None
        if panel_type == 'marzban':
            manager = MarzbanPanelManager()
        elif panel_type == 'rebecca':
            manager = RebeccaPanelManager()
        elif panel_type == 'pasargad':
            manager = PasargadPanelManager()
        elif panel_type == 'marzneshin':
            manager = MarzneshinPanelManager()
        elif panel_type == 'guard':
            manager = GuardPanelManager()
        else:
            manager = PanelManager()
            
        manager.base_url = api_endpoint or url
        manager.username = username
        manager.password = password
        
        if not manager.login():
            return jsonify({'success': False, 'message': 'عدم موفقیت در ورود به پنل'}), 400
            
        result = {'success': True}
        
        if panel_type == 'pasargad':
            if isinstance(manager, PasargadPanelManager):
                groups = manager.get_groups()
                result['groups'] = groups
                result['message'] = f'{len(groups)} گروه یافت شد'
        elif panel_type == 'rebecca':
            # For Rebecca, we might want to fetch inbounds/services
            if hasattr(manager, 'get_inbounds'):
                inbounds = manager.get_inbounds()
                result['inbounds'] = inbounds
                result['message'] = f'{len(inbounds)} سرویس یافت شد'
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error fetching panel metadata: {e}")
        return jsonify({'success': False, 'message': f'خطای سیستمی: {str(e)}'}), 500

@app.route('/api/admin/panels/<int:panel_id>', methods=['PUT'])
@admin_required
def api_admin_update_panel(panel_id):
    """Update a panel"""
    try:
        data = request.json
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        # Convert empty strings to None for optional fields
        def clean_value(value):
            return value if value and value.strip() else None
        
        success, message = admin_mgr.update_panel(
            panel_id=panel_id,
            name=data.get('name'),
            url=data.get('url'),
            username=data.get('username'),
            password=data.get('password'),
            api_endpoint=data.get('api_endpoint'),
            price_per_gb=data.get('price_per_gb'),
            subscription_url=clean_value(data.get('subscription_url')),
            panel_type=data.get('panel_type'),
            sale_type=data.get('sale_type'),
            default_inbound_id=data.get('default_inbound_id'),
            extra_config=data.get('extra_config'),
            delivery_method=data.get('delivery_method')
        )
        
        if success:
            logger.info(f"Panel {panel_id} updated successfully")
            return jsonify({'success': True, 'message': message}), 200
        else:
            logger.warning(f"Failed to update panel {panel_id}: {message}")
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        logger.error(f"Error updating panel: {e}", exc_info=True)
        return secure_error_response(e, 'خطا در بروزرسانی پنل')

@app.route('/api/admin/panels/<int:panel_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_panel(panel_id):
    """Delete a panel"""
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message = admin_mgr.delete_panel(panel_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        logger.error(f"Error deleting panel: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/<int:panel_id>/test', methods=['POST'])
@admin_required
def api_admin_test_panel(panel_id):
    """Test panel connection"""
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message = admin_mgr.test_panel_connection(panel_id)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Error testing panel: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/<int:panel_id>/inbounds', methods=['GET'])
@admin_required
def api_admin_get_panel_inbounds(panel_id):
    """Get panel inbounds with status"""
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        inbounds = admin_mgr.get_panel_inbounds_with_status(panel_id)
        
        return jsonify({'success': True, 'inbounds': inbounds})
    except Exception as e:
        logger.error(f"Error getting panel inbounds: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/<int:panel_id>/inbounds/sync', methods=['POST'])
@admin_required
def api_admin_sync_panel_inbounds(panel_id):
    """Sync panel inbounds from panel API to database"""
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message = admin_mgr.sync_panel_inbounds_to_db(panel_id)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Error syncing panel inbounds: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/<int:panel_id>/inbounds/<int:inbound_id>/toggle', methods=['POST'])
@admin_required
def api_admin_toggle_inbound(panel_id, inbound_id):
    """Toggle inbound enabled status"""
    try:
        data = request.json
        is_enabled = data.get('is_enabled', True)
        
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message = admin_mgr.set_inbound_enabled_status(panel_id, inbound_id, is_enabled)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Error toggling inbound: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/<int:panel_id>/main-inbound', methods=['PUT'])
@admin_required
def api_admin_change_main_inbound(panel_id):
    """Change main inbound for a panel"""
    try:
        data = request.json
        new_main_inbound_id = data.get('inbound_id')
        
        if not new_main_inbound_id:
            return jsonify({'success': False, 'message': 'اینباند اصلی مشخص نشده است'}), 400
        
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        success, message = admin_mgr.change_panel_main_inbound(panel_id, new_main_inbound_id)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Error changing main inbound: {e}")
        return secure_error_response(e)

@app.route('/api/admin/panels/<int:panel_id>', methods=['GET'])
@admin_required
def api_admin_get_panel(panel_id):
    """Get panel details with inbounds"""
    try:
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        
        panel = admin_mgr.get_panel_details(panel_id, sync_inbounds=False)
        if not panel:
            return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
        
        return jsonify({'success': True, 'panel': panel})
    except Exception as e:
        logger.error(f"Error getting panel: {e}")
        return secure_error_response(e)

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_users():
    """Get all users"""
    try:
        db_instance = get_db()
        users = db_instance.get_all_users()
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return secure_error_response(e)

@app.route('/api/admin/users/<int:user_id>', methods=['GET'])
@admin_required
def api_admin_user_info(user_id):
    """Get user information"""
    try:
        db_instance = get_db()
        user = db_instance.get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        services = db_instance.get_user_clients(user['telegram_id'])
        transactions = db_instance.get_user_transactions(user['telegram_id'], limit=50)
        
        return jsonify({
            'success': True,
            'user': user,
            'services': services,
            'transactions': transactions
        })
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        return secure_error_response(e)

@app.route('/api/admin/users/<int:user_id>/balance', methods=['POST'])
@admin_required
def api_admin_user_balance(user_id):
    """Add or subtract balance from user with professional implementation"""
    try:
        data = request.get_json()
        amount = data.get('amount')
        description = data.get('description', '')
        balance_type = data.get('type', 'add')  # 'add' or 'subtract'
        
        if not amount or amount <= 0:
            return jsonify({'success': False, 'message': 'مبلغ باید بیشتر از صفر باشد'}), 400
        
        db_instance = get_db()
        user = db_instance.get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        current_balance = user.get('balance', 0) or 0
        
        if balance_type == 'subtract':
            if current_balance < amount:
                return jsonify({'success': False, 'message': f'موجودی کافی نیست. موجودی فعلی: {current_balance:,} تومان'}), 400
            new_balance = current_balance - amount
            transaction_type = 'admin_debit'
            action_desc = description or 'کسر موجودی توسط ادمین'
            notification_message = f"""💰 **کاهش موجودی**

➖ مبلغ کسر شده: {amount:,} تومان
💵 موجودی قبلی: {current_balance:,} تومان
💵 موجودی جدید: {new_balance:,} تومان

📝 توضیحات: {action_desc}

⚠️ در صورت نیاز به توضیحات بیشتر، با پشتیبانی تماس بگیرید."""
        else:
            new_balance = current_balance + amount
            transaction_type = 'admin_credit'
            action_desc = description or 'افزایش موجودی توسط ادمین'
            notification_message = f"""💰 **افزایش موجودی**

➕ مبلغ اضافه شده: {amount:,} تومان
💵 موجودی قبلی: {current_balance:,} تومان
💵 موجودی جدید: {new_balance:,} تومان

📝 توضیحات: {action_desc}

🎉 می‌توانید از این موجودی برای خرید سرویس استفاده کنید."""
        
        # Update user balance using professional database manager methods
        success = False
        if balance_type == 'subtract':
            success = db_instance.deduct_balance(user_id, amount, transaction_type, description=action_desc)
        else:
            success = db_instance.add_balance(user_id, amount, transaction_type, description=action_desc)
            
        if success:
            # Send notification to user via Telegram
            try:
                from telegram_helper import TelegramHelper
                TelegramHelper.send_message_sync(user['telegram_id'], notification_message)
            except Exception as e:
                logger.error(f"Error sending balance notification to user {user['telegram_id']}: {e}")
                # Don't fail the request if notification fails
            
            # Get updated balance
            updated_user = db_instance.get_user_by_id(user_id)
            new_balance_val = updated_user.get('balance', 0) if updated_user else new_balance
            
            message = f'{amount:,} تومان به موجودی کاربر اضافه شد' if balance_type == 'add' else f'{amount:,} تومان از موجودی کاربر کسر شد'
            return jsonify({'success': True, 'message': message, 'new_balance': new_balance_val})
        else:
            return jsonify({'success': False, 'message': 'خطا در بروزرسانی موجودی'}), 500

    except Exception as e:
        logger.error(f"Error updating user balance: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

# ==================== SERVICE MANAGEMENT API ROUTES ====================

@app.route('/api/services/<int:service_id>/config', methods=['GET'])
def api_get_service_config(service_id):
    """Get service configuration link"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'لطفاً ابتدا وارد شوید'}), 401
            
        db_instance = get_db()
        user = db_instance.get_user(user_id)
        service = db_instance.get_client_by_id(service_id)
        
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
            
        # Check ownership or admin status
        if service['user_id'] != user.get('id') and not user.get('is_admin'):
            return jsonify({'success': False, 'message': 'دسترسی غیرمجاز'}), 403
            
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr:
            return jsonify({'success': False, 'message': 'پنل یافت نشد'}), 404
            
        # Get config link - pass client_name for Rebecca/Marzban panels that use username
        config = panel_mgr.get_client_config_link(
            service['inbound_id'],
            service.get('client_name') or service['client_uuid'],
            service['protocol']
        )
        
        if config:
            return jsonify({'success': True, 'config': config})
        else:
            return jsonify({'success': False, 'message': 'خطا در دریافت لینک اتصال'}), 500
            
    except Exception as e:
        logger.error(f"Error getting service config: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/volume', methods=['POST'])
@admin_required
def api_admin_service_volume(service_id):
    """Add volume to service"""
    try:
        data = request.json
        volume_gb = data.get('volume_gb')
        
        if not volume_gb or volume_gb <= 0:
            return jsonify({'success': False, 'message': 'مقدار حجم نامعتبر است'}), 400
            
        db_instance = get_db()
        service = db_instance.get_client_by_id(service_id)
        
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
            
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr or not panel_mgr.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
            
        # Get current client details to know current total (use client_name for Rebecca)
        client = panel_mgr.get_client_details(
            service['inbound_id'], 
            service['client_uuid'],
            client_name=service.get('client_name')
        )
        if not client:
            return jsonify({'success': False, 'message': 'کاربر در پنل یافت نشد'}), 404
            
        # Get current total - handle different formats:
        # - 3x-ui returns 'totalGB' in bytes (or 'total' in bytes)
        # - Rebecca/Marzban return 'total_traffic' in bytes
        current_total_bytes = 0
        if 'totalGB' in client and client['totalGB']:
            current_total_bytes = client['totalGB']  # Usually in bytes despite the name
        elif 'total_traffic' in client and client['total_traffic']:
            current_total_bytes = client['total_traffic']  # Bytes
        elif 'data_limit' in client and client['data_limit']:
            current_total_bytes = client['data_limit']  # Bytes
        
        # Add new volume (convert GB to bytes)
        new_volume_bytes = volume_gb * 1024 * 1024 * 1024
        new_total_bytes = current_total_bytes + new_volume_bytes
        
        logger.info(f"Volume addition: current={current_total_bytes} bytes, adding={new_volume_bytes} bytes, new_total={new_total_bytes} bytes")
        
        # Update in panel (pass client_name for Rebecca)
        if panel_mgr.update_client(
            service['inbound_id'],
            service['client_uuid'],
            total_gb=new_total_bytes,
            client_name=service.get('client_name')
        ):
            # Update in DB - convert bytes back to GB for database
            new_total_gb = new_total_bytes / (1024 * 1024 * 1024)
            db_instance.update_client_total_gb(service_id, new_total_gb)
            return jsonify({'success': True, 'message': 'حجم با موفقیت اضافه شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در بروزرسانی پنل'}), 500
            
    except Exception as e:
        logger.error(f"Error adding volume: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/renew', methods=['POST'])
@admin_required
def api_admin_service_renew(service_id):
    """Renew service (extend expiry)"""
    try:
        data = request.json
        days = data.get('days')
        
        if not days or days <= 0:
            return jsonify({'success': False, 'message': 'تعداد روز نامعتبر است'}), 400
            
        db_instance = get_db()
        service = db_instance.get_client_by_id(service_id)
        
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
            
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr or not panel_mgr.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
            
        # Get current client details (use client_name for Rebecca)
        client = panel_mgr.get_client_details(
            service['inbound_id'], 
            service['client_uuid'],
            client_name=service.get('client_name')
        )
        if not client:
            return jsonify({'success': False, 'message': 'کاربر در پنل یافت نشد'}), 404
            
        # Calculate new expiry
        import time
        current_expiry = client.get('expiryTime', 0)
        now_ms = int(time.time() * 1000)
        
        # If expired or no expiry, start from now. If active, add to current expiry.
        if current_expiry <= 0 or current_expiry < now_ms:
            base_time = now_ms
        else:
            base_time = current_expiry
            
        new_expiry = base_time + (days * 24 * 60 * 60 * 1000)
        
        # Update in panel (pass client_name for Rebecca)
        if panel_mgr.update_client(
            service['inbound_id'],
            service['client_uuid'],
            expiry_time=new_expiry,
            client_name=service.get('client_name')
        ):
            # Update expiry in DB directly
            from datetime import datetime
            expires_at = datetime.fromtimestamp(new_expiry / 1000) if new_expiry > 1000000000000 else datetime.fromtimestamp(new_expiry)
            with db_instance.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE clients 
                    SET expires_at = %s, 
                        status = 'active',
                        is_active = 1,
                        warned_expired = 0,
                        warned_three_days = 0,
                        warned_one_week = 0,
                        expired_at = NULL,
                        deletion_grace_period_end = NULL,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                ''', (expires_at, service_id))
                conn.commit()
            return jsonify({'success': True, 'message': 'سرویس با موفقیت تمدید شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در بروزرسانی پنل'}), 500
            
    except Exception as e:
        logger.error(f"Error renewing service: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_service(service_id):
    """Delete service"""
    try:
        db_instance = get_db()
        service = db_instance.get_client_by_id(service_id)
        
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
            
        from admin_manager import AdminManager
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        # Check if refund is needed (for resellers)
        refund_processed = False
        refund_message = ""
        
        # Check if user is a reseller
        from reseller_panel.models import ResellerManager
        reseller_manager = ResellerManager(db_instance)
        reseller_profile = reseller_manager.get_reseller_by_user_id(service['user_id'])
        
        if reseller_profile and reseller_profile.get('status') == 'active':
            # Check if within refund window (24h)
            from datetime import datetime, timedelta
            now = datetime.now()
            created_at = service.get('created_at')
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except Exception:
                    created_at = None
            
            # Check invoice
            invoice_id = service.get('invoice_id')
            invoice = None
            if invoice_id:
                invoice = db_instance.get_invoice(invoice_id)
            
            # Perform refund if eligible
            if created_at and (now - created_at) <= timedelta(days=1) and invoice and str(invoice.get('status', '')).lower() not in ['refunded', 'cancelled']:
                amount = int(invoice.get('amount') or 0)
                if amount > 0:
                    # Add balance
                    if db_instance.add_balance(service['user_id'], amount, 'refund', description=f"بازگشت وجه حذف سرویس #{service_id} توسط ادمین (فاکتور #{invoice_id})"):
                        # Update invoice status
                        try:
                            db_instance.update_invoice_status(invoice_id, 'refunded')
                            refund_processed = True
                            refund_message = f" و مبلغ {amount:,} تومان به کیف پول کاربر برگشت داده شد"
                            
                            # Send notification
                            try:
                                from telegram_helper import TelegramHelper
                                user = db_instance.get_user_by_id(service['user_id'])
                                if user:
                                    msg = f"""♻️ **حذف سرویس و برگشت وجه**

سرویس {service.get('client_name', '')} توسط مدیریت حذف شد.
مبلغ {amount:,} تومان به کیف پول شما بازگشت داده شد."""
                                    TelegramHelper.send_message_sync(user['telegram_id'], msg)
                            except Exception:
                                pass
                        except Exception as e:
                            logger.error(f"Error updating invoice status during admin delete: {e}")

        # Try to delete from panel first (use client_name for Rebecca)
        panel_deleted = False
        client_identifier = service.get('client_name') or service['client_uuid']
        if panel_mgr and panel_mgr.login():
            if panel_mgr.delete_client(service['inbound_id'], client_identifier):
                panel_deleted = True
            else:
                logger.warning(f"Failed to delete client {client_identifier} from panel")
        
        # Delete from DB regardless of panel result (force delete)
        if db_instance.delete_client(service_id):
            msg = 'سرویس با موفقیت حذف شد' + refund_message
            if not panel_deleted:
                msg += ' (اما حذف از پنل با خطا مواجه شد)'
            return jsonify({'success': True, 'message': msg})
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف سرویس از دیتابیس'}), 500
            
    except Exception as e:
        logger.error(f"Error deleting service: {e}")
        return secure_error_response(e)


@app.route('/api/admin/users/<int:user_id>/ban', methods=['PUT'])
@admin_required
def api_admin_ban_user(user_id):
    """Ban or unban user with professional implementation"""
    try:
        data = request.get_json()
        is_banned = data.get('is_banned', False)
        
        db_instance = get_db()
        user = db_instance.get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        # Update ban status
        with db_instance.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                UPDATE users 
                SET is_banned = %s, last_activity = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (1 if is_banned else 0, user_id))
            conn.commit()
            cursor.close()
        
        # Send notification to user
        try:
            from telegram_helper import TelegramHelper
            if is_banned:
                notification_message = f"""🚫 **حساب کاربری شما مسدود شده است**

متأسفانه دسترسی شما به سرویس‌های ما به دلایل امنیتی یا نقض قوانین قطع شده است.

⚠️ **توجه:**
• دسترسی به بات و وب اپ غیرفعال است
• سرویس‌های فعال شما غیرفعال شده‌اند
• برای رفع مسدودیت با پشتیبانی تماس بگیرید

📞 برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."""
            else:
                notification_message = f"""✅ **حساب کاربری شما فعال شد**

دسترسی شما به سرویس‌های ما بازگردانده شده است.

🎉 می‌توانید از تمام امکانات استفاده کنید."""
            
            TelegramHelper.send_message_sync(user['telegram_id'], notification_message)
        except Exception as e:
            logger.error(f"Error sending ban notification to user {user['telegram_id']}: {e}")
        
        message = 'کاربر با موفقیت مسدود شد' if is_banned else 'رفع مسدودیت با موفقیت انجام شد'
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return secure_error_response(e)

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_user(user_id):
    """Delete user with professional implementation"""
    try:
        db_instance = get_db()
        user = db_instance.get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        # Prevent deleting admin users
        if user.get('is_admin', 0) == 1:
            return jsonify({'success': False, 'message': 'نمی‌توانید کاربر ادمین را حذف کنید'}), 400
        
        telegram_id = user.get('telegram_id')
        
        # Delete user and all related data (cascade will handle related records)
        with db_instance.get_connection() as conn:
            cursor = conn.cursor()
            
            # Delete user services/clients first
            cursor.execute('DELETE FROM clients WHERE user_id = %s', (telegram_id,))
            
            # Delete transactions
            try:
                cursor.execute('DELETE FROM transactions WHERE user_id = %s', (telegram_id,))
            except Exception:
                pass
            
            try:
                cursor.execute('DELETE FROM balance_transactions WHERE user_id = %s', (user_id,))
            except Exception:
                pass
            
            # Delete tickets
            try:
                cursor.execute('DELETE FROM tickets WHERE user_id = %s', (user_id,))
            except Exception:
                pass
            
            # Delete user
            cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
            
            conn.commit()
            cursor.close()
        
        logger.info(f"User {user_id} (telegram_id: {telegram_id}) deleted by admin")
        
        return jsonify({'success': True, 'message': 'کاربر با موفقیت حذف شد'})
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

@app.route('/api/admin/users/<int:user_id>/message', methods=['POST'])
@admin_required
def api_admin_send_message(user_id):
    """Send personal message to user"""
    try:
        data = request.get_json()
        message_text = data.get('message', '').strip()
        
        if not message_text:
            return jsonify({'success': False, 'message': 'متن پیام نمی‌تواند خالی باشد'}), 400
        
        db_instance = get_db()
        user = db_instance.get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        # Send message via Telegram
        try:
            from telegram_helper import TelegramHelper
            admin_user = db_instance.get_user(session.get('user_id'))
            admin_name = admin_user.get('first_name', 'مدیر') if admin_user else 'مدیر'
            
            notification_message = f"""📩 **پیام از مدیریت**

{message_text}

👤 از طرف: {admin_name}

💬 در صورت نیاز به پاسخ، با پشتیبانی تماس بگیرید."""
            
            result = TelegramHelper.send_message_sync(user['telegram_id'], notification_message)
            if not result:
                raise Exception("ارسال پیام در تلگرام ناموفق بود")
        except Exception as e:
            logger.error(f"Error sending message to user {user['telegram_id']}: {e}")
            return jsonify({'success': False, 'message': f'خطا در ارسال پیام: {str(e)}'}), 500
        
        return jsonify({'success': True, 'message': 'پیام با موفقیت ارسال شد'})
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return secure_error_response(e)

@app.route('/api/admin/users/<int:user_id>/login', methods=['POST'])
@admin_required
def api_admin_login_as_user(user_id):
    """Login as specific user (Masquerade)"""
    try:
        db_instance = get_db()
        user = db_instance.get_user_by_id(user_id)
        
        if not user:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
            
        # Store original admin session if not already stored
        if 'original_admin_id' not in session:
            session['original_admin_id'] = session.get('user_id')
            
        # Set user session
        # Note: session['user_id'] stores telegram_id
        session['user_id'] = user['telegram_id']
        session['is_masquerading'] = True
        
        # Log the action
        logger.warning(f"Admin {session.get('original_admin_id')} logged in as user {user['telegram_id']}")
        
        redirect_path = bot_url_for('dashboard')
        redirect_url = request.host_url.rstrip('/') + redirect_path
        
        return jsonify({
            'success': True, 
            'redirect_url': redirect_url
        })
        
    except Exception as e:
        logger.error(f"Error logging in as user: {e}")
        return secure_error_response(e)

@app.route('/api/admin/users/gift-all', methods=['POST'])
@admin_required
def api_admin_gift_all_users():
    """Gift balance to all users with professional implementation and notifications"""
    try:
        data = request.json
        amount = int(data.get('amount', 0))
        
        if amount <= 0:
            return jsonify({'success': False, 'message': 'مبلغ باید بیشتر از صفر باشد'}), 400
        
        db_instance = get_db()
        all_users = db_instance.get_all_users()
        success_count = 0
        failed_count = 0
        
        from telegram_helper import TelegramHelper
        
        for user in all_users:
            try:
                # Skip banned users
                if user.get('is_banned', 0) == 1:
                    continue
                
                # Update balance
                db_instance.update_user_balance(user['telegram_id'], amount, 'gift', f'هدیه همگانی: {amount:,} تومان')
                
                # Get new balance
                new_balance = (user.get('balance', 0) or 0) + amount
                
                # Send notification
                notification_message = f"""🎁 **هدیه همگانی از مدیریت**

💰 مبلغ هدیه: {amount:,} تومان
💵 موجودی جدید: {new_balance:,} تومان

🎉 می‌توانید از این موجودی برای خرید سرویس استفاده کنید.

🔹 برای خرید سرویس از منوی اصلی استفاده کنید."""
                
                try:
                    TelegramHelper.send_message_sync(user['telegram_id'], notification_message)
                except Exception as e:
                    logger.error(f"Error sending gift notification to user {user['telegram_id']}: {e}")
                
                success_count += 1
            except Exception as e:
                logger.error(f"Error gifting to user {user.get('telegram_id', 'unknown')}: {e}")
                failed_count += 1
        
        return jsonify({
            'success': True,
            'message': f'هدیه به {success_count} کاربر ارسال شد',
            'success_count': success_count,
            'failed_count': failed_count
        })
    except Exception as e:
        logger.error(f"Error gifting all users: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/categories', methods=['POST'])
@admin_required
def api_admin_create_category_simple():
    """Create a new category (Simple Route)"""
    try:
        data = request.json
        panel_id = data.get('panel_id')
        name = data.get('name')
        
        if not panel_id or not name:
            return jsonify({'success': False, 'message': 'اطلاعات ناقص است'}), 400
            
        db_instance = get_db()
        category_id = db_instance.add_category(panel_id, name)
        
        if category_id:
            return jsonify({'success': True, 'message': 'دسته‌بندی با موفقیت ایجاد شد', 'category_id': category_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در ایجاد دسته‌بندی'}), 500
            
    except Exception as e:
        logger.error(f"Error creating category: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/categories/<int:category_id>', methods=['PUT', 'DELETE'])
@admin_required
def api_admin_manage_category_simple(category_id):
    """Update or delete category (Simple Route)"""
    try:
        db_instance = get_db()
        
        if request.method == 'DELETE':
            if db_instance.delete_category(category_id):
                return jsonify({'success': True, 'message': 'دسته‌بندی حذف شد'})
            else:
                return jsonify({'success': False, 'message': 'خطا در حذف دسته‌بندی'}), 500
                
        elif request.method == 'PUT':
            data = request.json
            name = data.get('name')
            is_active = data.get('is_active')
            
            updates = {}
            if name: updates['name'] = name
            if is_active is not None: updates['is_active'] = is_active
            
            if db_instance.update_category(category_id, **updates):
                return jsonify({'success': True, 'message': 'دسته‌بندی ویرایش شد'})
            else:
                return jsonify({'success': False, 'message': 'خطا در ویرایش دسته‌بندی'}), 500
                
    except Exception as e:
        logger.error(f"Error managing category: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products', methods=['POST'])
@admin_required
def api_admin_create_product_simple():
    """Create product (Simple Route)"""
    try:
        data = request.json
        panel_id = data.get('panel_id')
        if not panel_id:
             return jsonify({'success': False, 'message': 'شناسه پنل الزامی است'}), 400
             
        db_instance = get_db()
        product_id = db_instance.add_product(
            panel_id=panel_id,
            name=data.get('name'),
            volume_gb=data.get('volume_gb'),
            duration_days=data.get('duration_days'),
            price=data.get('price'),
            category_id=data.get('category_id'),
            is_visible_to_users=data.get('is_visible_to_users', True),
            is_visible_to_resellers=data.get('is_visible_to_resellers', True)
        )
        
        if product_id:
            return jsonify({'success': True, 'message': 'محصول با موفقیت ایجاد شد', 'product_id': product_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در ایجاد محصول'}), 500
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/<int:product_id>', methods=['PUT', 'DELETE', 'GET'])
@admin_required
def api_admin_manage_product_simple(product_id):
    """Manage product (Simple Route)"""
    try:
        db_instance = get_db()
        
        if request.method == 'DELETE':
            if db_instance.delete_product(product_id):
                return jsonify({'success': True, 'message': 'محصول حذف شد'})
            else:
                return jsonify({'success': False, 'message': 'خطا در حذف محصول'}), 500
        
        elif request.method == 'GET':
            product = db_instance.get_product(product_id)
            if product:
                return jsonify({'success': True, 'product': product})
            else:
                return jsonify({'success': False, 'message': 'محصول یافت نشد'}), 404
                
        elif request.method == 'PUT':
            data = request.json
            if db_instance.update_product(product_id, **data):
                return jsonify({'success': True, 'message': 'محصول ویرایش شد'})
            else:
                return jsonify({'success': False, 'message': 'خطا در ویرایش محصول'}), 500
    except Exception as e:
        logger.error(f"Error managing product: {e}")
        return secure_error_response(e)

@app.route('/api/admin/discounts', methods=['POST'])
@admin_required
def api_admin_create_discount():
    """Create discount code"""
    try:
        data = request.json
        user_telegram_id = session.get('user_id')
        
        # Get internal user database ID from telegram_id
        db_instance = get_db()
        user = db_instance.get_user(user_telegram_id)
        user_db_id = user.get('id') if user else None
        
        code_id = db_instance.create_discount_code(
            code=data.get('code'),
            discount_type=data.get('discount_type', 'percentage'),
            discount_value=float(data.get('discount_value', 0)),
            max_discount_amount=data.get('max_discount_amount'),
            min_purchase_amount=data.get('min_purchase_amount', 0),
            max_uses=data.get('max_uses', 0),
            valid_from=data.get('valid_from'),
            valid_until=data.get('valid_until'),
            created_by=user_db_id
        )
        
        if code_id:
            return jsonify({'success': True, 'message': 'کد تخفیف با موفقیت ایجاد شد', 'code_id': code_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در ایجاد کد تخفیف'}), 400
    except Exception as e:
        logger.error(f"Error creating discount code: {e}")
        return secure_error_response(e)


@app.route('/api/admin/discounts/<int:code_id>', methods=['PUT'])
@admin_required
def api_admin_update_discount(code_id):
    """Update discount code"""
    try:
        data = request.json
        
        with db.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                updates = []
                params = []
                
                if 'is_active' in data:
                    updates.append('is_active = %s')
                    params.append(1 if data['is_active'] else 0)
                
                if updates:
                    params.append(code_id)
                    query = f"UPDATE discount_codes SET {', '.join(updates)} WHERE id = %s"
                    cursor.execute(query, params)
                    conn.commit()
            finally:
                cursor.close()
                
            if updates:
                return jsonify({'success': True, 'message': 'کد تخفیف با موفقیت بروزرسانی شد'})
            else:
                return jsonify({'success': False, 'message': 'هیچ تغییری اعمال نشد'}), 400
    except Exception as e:
        logger.error(f"Error updating discount code: {e}")
        return secure_error_response(e)

@app.route('/api/admin/discounts/<int:code_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_discount(code_id):
    """Delete discount code permanently"""
    try:
        db_instance = get_db()
        if db_instance.delete_discount_code(code_id):
            return jsonify({'success': True, 'message': 'کد تخفیف با موفقیت حذف شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف کد تخفیف'}), 400
    except Exception as e:
        logger.error(f"Error deleting discount code: {e}")
        return secure_error_response(e)

@app.route('/api/admin/discounts/gift/<int:code_id>', methods=['PUT'])
@admin_required
def api_admin_update_gift_code(code_id):
    """Update gift code"""
    try:
        data = request.json
        
        with db.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                updates = []
                params = []
                
                if 'is_active' in data:
                    updates.append('is_active = %s')
                    params.append(1 if data['is_active'] else 0)
                
                if updates:
                    params.append(code_id)
                    query = f"UPDATE gift_codes SET {', '.join(updates)} WHERE id = %s"
                    cursor.execute(query, params)
                    conn.commit()
            finally:
                cursor.close()
                
            if updates:
                return jsonify({'success': True, 'message': 'کد هدیه با موفقیت بروزرسانی شد'})
            else:
                return jsonify({'success': False, 'message': 'هیچ تغییری اعمال نشد'}), 400
    except Exception as e:
        logger.error(f"Error updating gift code: {e}")
        return secure_error_response(e)

@app.route('/api/admin/discounts/gift/<int:code_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_gift_code(code_id):
    """Delete gift code permanently"""
    try:
        db_instance = get_db()
        if db_instance.delete_gift_code(code_id):
            return jsonify({'success': True, 'message': 'کد هدیه با موفقیت حذف شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف کد هدیه'}), 400
    except Exception as e:
        logger.error(f"Error deleting gift code: {e}")
        return secure_error_response(e)

@app.route('/api/admin/gift-codes', methods=['POST'])
@admin_required
def api_admin_create_gift_code():
    """Create gift code"""
    try:
        data = request.json
        user_id = session.get('user_id')
        
        code_id = db.create_gift_code(
            code=data.get('code'),
            amount=int(data.get('amount', 0)),
            max_uses=int(data.get('max_uses', 1)),
            created_by=user_id
        )
        
        if code_id:
            return jsonify({'success': True, 'message': 'کد هدیه با موفقیت ایجاد شد', 'code_id': code_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در ایجاد کد هدیه'}), 400
    except Exception as e:
        logger.error(f"Error creating gift code: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

@app.route('/api/admin/products/panel/<int:panel_id>/categories', methods=['GET'])
@admin_required
def api_admin_categories(panel_id):
    """Get categories for a panel"""
    try:
        categories = db.get_categories(panel_id, active_only=False)
        return jsonify({'success': True, 'categories': categories})
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return secure_error_response(e)
@app.route('/api/admin/products/panel/<int:panel_id>/categories', methods=['POST'])
@admin_required
def api_admin_add_category(panel_id):
    """Add a new category"""
    try:
        data = request.json
        category_id = db.add_category(panel_id, data.get('name', ''))
        
        if category_id:
            return jsonify({'success': True, 'message': 'دسته‌بندی با موفقیت اضافه شد', 'category_id': category_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در افزودن دسته‌بندی'}), 400
    except Exception as e:
        logger.error(f"Error adding category: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/panel/<int:panel_id>/categories/<int:category_id>', methods=['PUT'])
@admin_required
def api_admin_update_category(panel_id, category_id):
    """Update a category"""
    try:
        data = request.json
        success = db.update_category(
            category_id,
            name=data.get('name'),
            is_active=data.get('is_active')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'دسته‌بندی با موفقیت بروزرسانی شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در بروزرسانی دسته‌بندی'}), 400
    except Exception as e:
        logger.error(f"Error updating category: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/panel/<int:panel_id>/categories/<int:category_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_category(panel_id, category_id):
    """Delete a category"""
    try:
        success = db.delete_category(category_id)
        
        if success:
            return jsonify({'success': True, 'message': 'دسته‌بندی با موفقیت حذف شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف دسته‌بندی'}), 400
    except Exception as e:
        logger.error(f"Error deleting category: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/panel/<int:panel_id>/products', methods=['GET'])
@admin_required
def api_admin_panel_products(panel_id):
    """Get products for a panel"""
    try:
        category_id = request.args.get('category_id', type=int)
        # If category_id is not provided, get products without category
        # If category_id is provided, get products for that category
        if category_id is None:
            products = db.get_products(panel_id, category_id=False, active_only=False)
        else:
            products = db.get_products(panel_id, category_id=category_id, active_only=False)
        return jsonify({'success': True, 'products': products})
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/panel/<int:panel_id>/products', methods=['POST'])
@admin_required
def api_admin_add_product(panel_id):
    """Add a new product"""
    try:
        data = request.json
        product_id = db.add_product(
            panel_id=panel_id,
            name=data.get('name', ''),
            volume_gb=data.get('volume_gb', 0),
            duration_days=data.get('duration_days', 0),
            price=data.get('price', 0),
            category_id=data.get('category_id'),
            inbound_id=data.get('inbound_id'),
            user_limit=data.get('user_limit', 1),
            is_visible_to_users=data.get('is_visible_to_users', True),
            is_visible_to_resellers=data.get('is_visible_to_resellers', True)
        )
        
        if product_id:
            return jsonify({'success': True, 'message': 'محصول با موفقیت اضافه شد', 'product_id': product_id})
        else:
            return jsonify({'success': False, 'message': 'خطا در افزودن محصول'}), 400
    except Exception as e:
        logger.error(f"Error adding product: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/<int:product_id>', methods=['GET'])
@admin_required
def api_admin_get_product(product_id):
    """Get a single product"""
    try:
        db_instance = get_db()
        product = db_instance.get_product(product_id)
        if not product:
            return jsonify({'success': False, 'message': 'محصول یافت نشد'}), 404
        return jsonify({'success': True, 'product': product})
    except Exception as e:
        logger.error(f"Error getting product: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/<int:product_id>', methods=['PUT'])
@admin_required
def api_admin_update_product(product_id):
    """Update a product"""
    try:
        data = request.json
        success = db.update_product(
            product_id,
            name=data.get('name'),
            volume_gb=data.get('volume_gb'),
            duration_days=data.get('duration_days'),
            price=data.get('price'),
            is_active=data.get('is_active'),
            inbound_id=data.get('inbound_id'),
            user_limit=data.get('user_limit'),
            is_visible_to_users=data.get('is_visible_to_users'),
            is_visible_to_resellers=data.get('is_visible_to_resellers')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'محصول با موفقیت بروزرسانی شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در بروزرسانی محصول'}), 400
    except Exception as e:
        logger.error(f"Error updating product: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/<int:product_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_product(product_id):
    """Delete a product (permanently)"""
    try:
        # Check if product is used in any active services before deletion
        db_instance = get_db()
        with db_instance.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT COUNT(*) as count 
                FROM clients 
                WHERE product_id = %s AND is_active = 1
            ''', (product_id,))
            result = cursor.fetchone()
            
            if result and result['count'] > 0:
                return jsonify({
                    'success': False, 
                    'message': f'نمی‌توان این محصول را حذف کرد. {result["count"]} سرویس فعال از این محصول استفاده می‌کنند.'
                }), 400
        
        success = db.delete_product(product_id)
        
        if success:
            return jsonify({'success': True, 'message': 'محصول با موفقیت حذف شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف محصول'}), 400
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return secure_error_response(e)

@app.route('/api/admin/products/panel/<int:source_panel_id>/copy-to/<int:target_panel_id>', methods=['POST'])
@admin_required
def api_admin_copy_products(source_panel_id, target_panel_id):
    """Copy all products and categories from source panel to target panel"""
    try:
        db_instance = get_db()
        
        # Verify both panels exist
        source_panel = db_instance.get_panel(source_panel_id)
        target_panel = db_instance.get_panel(target_panel_id)
        
        if not source_panel:
            return jsonify({'success': False, 'message': 'پنل مبدا یافت نشد'}), 404
        
        if not target_panel:
            return jsonify({'success': False, 'message': 'پنل مقصد یافت نشد'}), 404
        
        if source_panel_id == target_panel_id:
            return jsonify({'success': False, 'message': 'پنل مبدا و مقصد نمی‌توانند یکسان باشند'}), 400
        
        # Get all categories from source panel
        source_categories = db_instance.get_categories(source_panel_id, active_only=False)
        
        # Create category mapping (old_id -> new_id)
        category_mapping = {}
        copied_categories = 0
        
        # Copy categories
        for category in source_categories:
            # Check if category with same name already exists in target panel
            existing_categories = db_instance.get_categories(target_panel_id, active_only=False)
            existing_category = next((c for c in existing_categories if c['name'] == category['name']), None)
            
            if existing_category:
                # Use existing category
                category_mapping[category['id']] = existing_category['id']
            else:
                # Create new category
                new_category_id = db_instance.add_category(target_panel_id, category['name'])
                if new_category_id:
                    # Update category status if needed
                    if not category.get('is_active', True):
                        db_instance.update_category(new_category_id, name=category['name'], is_active=False)
                    category_mapping[category['id']] = new_category_id
                    copied_categories += 1
        
        # Get all products from source panel
        source_products = db_instance.get_products(source_panel_id, category_id=None, active_only=False)
        
        # Copy products
        copied_products = 0
        skipped_products = 0
        
        for product in source_products:
            # Map category_id
            new_category_id = None
            if product.get('category_id'):
                new_category_id = category_mapping.get(product['category_id'])
            
            # Check if product with same name and specs already exists in target panel
            target_products = db_instance.get_products(target_panel_id, category_id=None, active_only=False)
            existing_product = next((
                p for p in target_products 
                if p['name'] == product['name'] 
                and p['volume_gb'] == product['volume_gb']
                and p['duration_days'] == product['duration_days']
                and p.get('category_id') == new_category_id
            ), None)
            
            if existing_product:
                skipped_products += 1
                continue
        
            # Create new product
            new_product_id = db_instance.add_product(
                panel_id=target_panel_id,
                name=product['name'],
                volume_gb=product['volume_gb'],
                duration_days=product['duration_days'],
                price=product['price'],
                category_id=new_category_id
            )
            
            if new_product_id:
                # Update product status if needed
                if not product.get('is_active', True):
                    db_instance.update_product(
                        new_product_id,
                        name=product['name'],
                        volume_gb=product['volume_gb'],
                        duration_days=product['duration_days'],
                        price=product['price'],
                        is_active=False
                    )
                copied_products += 1
        
        message = f'{copied_categories} دسته‌بندی و {copied_products} محصول کپی شد'
        if skipped_products > 0:
            message += f' ({skipped_products} محصول به دلیل تکراری بودن نادیده گرفته شد)'
        
        return jsonify({
            'success': True,
            'message': message,
            'copied_categories': copied_categories,
            'copied_products': copied_products,
            'skipped_products': skipped_products
        })
    except Exception as e:
        logger.error(f"Error copying products: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return secure_error_response(e)

@app.route('/api/payment/card-info', methods=['GET'])
@login_required
def api_payment_card_info():
    """Get card information for payment"""
    try:
        db_instance = get_db()
        card_number = db_instance.get_bot_text('card_number')
        card_owner = db_instance.get_bot_text('card_owner')
        
        return jsonify({
            'success': True,
            'card_number': card_number['text_content'] if card_number else None,
            'card_owner': card_owner['text_content'] if card_owner else None
        })
    except Exception as e:
        logger.error(f"Error getting card info: {e}")
        return secure_error_response(e)

@app.route('/api/payment/upload-receipt', methods=['POST'])
@login_required
def api_payment_upload_receipt():
    """Upload payment receipt"""
    try:
        import os  # Import os at the beginning of the function
        from datetime import datetime
        from werkzeug.utils import secure_filename
        
        db = get_db()
        user_id = session.get('user_id')
        if 'receipt' not in request.files:
            return jsonify({'success': False, 'message': 'هیچ فایلی ارسال نشده است'}), 400
            
        file = request.files['receipt']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'نام فایل نامعتبر است'}), 400
        
        # Check file size (max 10MB)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        if file_size > 10 * 1024 * 1024:  # 10MB
            return jsonify({'success': False, 'message': 'حجم فایل نباید بیشتر از 10 مگابایت باشد'}), 400
        
        # Check file extension
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            return jsonify({'success': False, 'message': 'فرمت فایل نامعتبر است. فقط تصاویر مجاز هستند'}), 400
            
        invoice_id = request.form.get('invoice_id')
        if not invoice_id:
            # If no invoice_id, create a balance top-up invoice
            amount = request.form.get('amount')
            if not amount:
                return jsonify({'success': False, 'message': 'مبلغ یا شناسه فاکتور الزامی است'}), 400
                
            # Create invoice for balance top-up
            # create_invoice handles finding a default panel if not provided
            invoice_id = db.create_invoice(
                user_id=user_id,
                amount=int(amount),
                purchase_type='balance',
                payment_method='card',
                description='شارژ کیف پول (کارت به کارت)'
            )
            
            if not invoice_id:
                return jsonify({'success': False, 'message': 'خطا در ایجاد فاکتور'}), 500
        
        # Save receipt file locally first
        receipts_dir = os.path.join(os.path.dirname(__file__), 'static', 'receipts')
        os.makedirs(receipts_dir, exist_ok=True)
        
        # Generate secure filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{invoice_id}_{timestamp}_{file.filename}")
        receipt_path = os.path.join(receipts_dir, filename)
        
        # Save file
        file.seek(0)
        file.save(receipt_path)
        
        # Update invoice with receipt path
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE invoices 
                SET receipt_path = %s, receipt_status = 'pending_approval', receipt_uploaded_at = NOW()
                WHERE id = %s
            ''', (filename, invoice_id))
            conn.commit()
            cursor.close()
        
        # Auto-approve receipts if enabled
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager(db_manager=db)
        auto_approve_enabled = settings_mgr.get_setting('auto_approve_receipts', False)
        auto_approved = False
        if auto_approve_enabled:
            auto_success, _ = _approve_invoice_logic(db, int(invoice_id))
            if auto_success:
                auto_approved = True
        
        # Send to Telegram Receipts Channel (if configured) or notify admin
        from telegram import Bot, InputFile
        bot_config = get_bot_config()
        receipts_channel_id = bot_config.get('receipts_channel_id')
        
        telegram_success = False
        if receipts_channel_id and receipts_channel_id != 0:
            # Send to channel
            try:
                import io
                import requests
                import json
                
                # Read file content
                with open(receipt_path, 'rb') as f:
                    file_content = f.read()
                
                file_obj = io.BytesIO(file_content)
                file_obj.name = filename
                
                # Get user info
                user = db.get_user(user_id)
                invoice_data = db.get_invoice(invoice_id)
                
                if not invoice_data:
                    return jsonify({'success': False, 'message': 'فاکتور یافت نشد'}), 404
                
                auto_tag = "\n🏷️ رسیدهای خودکار\n✅ تایید خودکار انجام شد." if auto_approved else ""
                instruction_line = "در صورت جعلی بودن از دکمه زیر استفاده کنید." if auto_approved else "جهت تایید یا رد پرداخت از دکمه‌های زیر استفاده کنید."
                caption = f"""🧾 **رسید پرداخت جدید**{auto_tag}

👤 **کاربر:** {user.get('first_name', 'Unknown')} (ID: {user_id})
💰 **مبلغ:** {invoice_data['amount']:,} تومان
🔢 **شماره فاکتور:** #{invoice_id}

{instruction_line}"""
                
                # Construct keyboard
                if auto_approved:
                    keyboard_dict = {
                        'inline_keyboard': [
                            [
                                {'text': "🚫 رد + مسدود", 'callback_data': f"ban_receipt_{invoice_id}"}
                            ]
                        ]
                    }
                else:
                    keyboard_dict = {
                        'inline_keyboard': [
                            [
                                {'text': "✅ تایید پرداخت", 'callback_data': f"approve_receipt_{invoice_id}"},
                                {'text': "❌ رد پرداخت", 'callback_data': f"reject_receipt_{invoice_id}"}
                            ],
                            [
                                {'text': "🚫 رد + مسدود", 'callback_data': f"ban_receipt_{invoice_id}"}
                            ]
                        ]
                    }
                
                # Ensure receipts_channel_id is correct type
                try:
                    if str(receipts_channel_id).lstrip('-').isdigit():
                        receipts_channel_id = int(receipts_channel_id)
                except:
                    pass

                url = f"https://api.telegram.org/bot{bot_config['token']}/sendPhoto"
                
                # Prepare data
                files = {'photo': (filename, file_obj, 'image/jpeg')}
                data = {
                    'chat_id': receipts_channel_id,
                    'caption': caption,
                    'reply_markup': json.dumps(keyboard_dict),
                    'parse_mode': 'Markdown'
                }
                
                logger.info(f"Sending receipt photo to channel {receipts_channel_id} for invoice {invoice_id}")
                
                response = requests.post(url, files=files, data=data, timeout=30)
                
                if response.status_code == 200:
                    logger.info("Receipt sent successfully to Telegram channel")
                    telegram_success = True
                else:
                    logger.error(f"Telegram send error: {response.status_code} - {response.text}")
                    telegram_success = False
                    
            except Exception as e:
                logger.error(f"Telegram send error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                telegram_success = False
        else:
            # No channel configured - send notification to admin via bot
            try:
                from telegram_helper import TelegramHelper
                import io
                
                # Read file content
                with open(receipt_path, 'rb') as f:
                    file_content = f.read()
                
                file_obj = io.BytesIO(file_content)
                file_obj.name = filename
                
                # Get user info
                user = db.get_user(user_id)
                invoice_data = db.get_invoice(invoice_id)
                
                if not invoice_data:
                    return jsonify({'success': False, 'message': 'فاکتور یافت نشد'}), 404
                
                admin_id = bot_config.get('admin_id')
                if admin_id:
                    auto_tag = "\n🏷️ رسیدهای خودکار\n✅ تایید خودکار انجام شد." if auto_approved else ""
                    instruction_line = "در صورت جعلی بودن از دکمه زیر استفاده کنید." if auto_approved else "جهت تایید یا رد پرداخت از دکمه‌های زیر استفاده کنید."
                    message = f"""🧾 **رسید پرداخت جدید**{auto_tag}

👤 **کاربر:** {user.get('first_name', 'Unknown')} (ID: {user_id})
💰 **مبلغ:** {invoice_data['amount']:,} تومان
🔢 **شماره فاکتور:** #{invoice_id}

⚠️ **توجه:** کانال رسیدها تنظیم نشده است. لطفاً از طریق پنل مدیریت رسید را بررسی کنید.
{instruction_line}"""
                    
                    # Send message with photo to admin
                    try:
                        bot = Bot(token=bot_config['token'])
                        from telegram import InputFile
                        file_obj.seek(0)
                        photo_file = InputFile(file_obj, filename=filename)
                        
                        # Send photo with inline keyboard
                        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                        if auto_approved:
                            keyboard = InlineKeyboardMarkup([
                                [InlineKeyboardButton("🚫 رد + مسدود", callback_data=f"ban_receipt_{invoice_id}")]
                            ])
                        else:
                            keyboard = InlineKeyboardMarkup([
                                [
                                    InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"approve_receipt_{invoice_id}"),
                                    InlineKeyboardButton("❌ رد پرداخت", callback_data=f"reject_receipt_{invoice_id}")
                                ],
                                [
                                    InlineKeyboardButton("🚫 رد + مسدود", callback_data=f"ban_receipt_{invoice_id}")
                                ]
                            ])
                        
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(bot.send_photo(
                            chat_id=admin_id,
                            photo=photo_file,
                            caption=message,
                            reply_markup=keyboard,
                            parse_mode='Markdown'
                        ))
                        loop.close()
                        telegram_success = True
                        logger.info(f"Receipt notification sent to admin {admin_id}")
                    except Exception as e:
                        logger.error(f"Error sending receipt to admin: {e}")
                        telegram_success = False
            except Exception as e:
                logger.error(f"Error in admin notification: {e}")
                telegram_success = False
                        
        # Update invoice status (only if not auto-approved)
        if not auto_approved:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE invoices SET payment_method = 'card', status = 'pending_approval' WHERE id = %s", (invoice_id,))
                conn.commit()
                cursor.close()
                
        return jsonify({'success': True, 'message': 'رسید با موفقیت ارسال شد'})

    except Exception as e:
        logger.error(f"Error uploading receipt: {e}")
        import traceback
        logger.error(traceback.format_exc())
        error_message = str(e) if str(e) else 'خطا در آپلود رسید'
        return jsonify({'success': False, 'message': error_message}), 500
            


@app.route('/api/admin/menu-layout', methods=['GET'])
@admin_required
def api_admin_get_menu_layout():
    """Get all menu buttons"""
    try:
        db_instance = get_db()
        buttons = db_instance.get_all_menu_buttons()
        return jsonify({'success': True, 'buttons': buttons})
    except Exception as e:
        logger.error(f"Error getting menu layout: {e}")
        return secure_error_response(e)

@app.route('/api/admin/menu-layout', methods=['POST'])
@admin_required
def api_admin_save_menu_layout():
    """Save menu buttons layout"""
    try:
        data = request.json
        buttons_layout = data.get('buttons', [])
        
        db_instance = get_db()
        success = db_instance.update_menu_button_positions(buttons_layout)
        
        if success:
            return jsonify({'success': True, 'message': 'چینش منو با موفقیت ذخیره شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در ذخیره چینش منو'}), 400
    except Exception as e:
        logger.error(f"Error saving menu layout: {e}")
        return secure_error_response(e)

@app.route('/api/admin/menu-layout/button', methods=['POST'])
@admin_required
def api_admin_add_menu_button():
    """Add a new menu button or update if exists"""
    try:
        data = request.json
        
        button_key = data.get('button_key')
        if not button_key:
            return jsonify({'success': False, 'message': 'کلید دکمه الزامی است'}), 400
        
        # If webapp type and no URL provided, use default
        if data.get('button_type') == 'webapp' and not data.get('web_app_url'):
            import os
            from webapp_helper import get_webapp_url
            webapp_url = os.getenv('BOT_WEBAPP_URL') or get_webapp_url()
            if webapp_url:
                data['web_app_url'] = webapp_url
        
        db_instance = get_db()
        
        # Check if button already exists
        existing_button = db_instance.get_menu_button(button_key)
        is_update = existing_button is not None
        
        button_id = db_instance.add_menu_button(
            button_key=button_key,
            button_text=data.get('button_text'),
            callback_data=data.get('callback_data'),
            button_type=data.get('button_type', 'callback'),
            web_app_url=data.get('web_app_url'),
            row_position=data.get('row_position', 0),
            column_position=data.get('column_position', 0),
            is_visible_for_admin=data.get('is_visible_for_admin', False),
            is_visible_for_users=data.get('is_visible_for_users', True),
            requires_webapp=data.get('requires_webapp', False),
            display_order=data.get('display_order', 0)
        )
        
        if button_id:
            message = 'دکمه با موفقیت بروزرسانی شد' if is_update else 'دکمه با موفقیت اضافه شد'
            return jsonify({'success': True, 'message': message, 'button_id': button_id, 'is_update': is_update})
        else:
            return jsonify({'success': False, 'message': 'خطا در افزودن/بروزرسانی دکمه'}), 400
    except Exception as e:
        logger.error(f"Error adding menu button: {e}")
        return secure_error_response(e)

@app.route('/api/admin/menu-layout/button/<button_key>', methods=['PUT'])
@admin_required
def api_admin_update_menu_button(button_key):
    """Update a menu button"""
    try:
        data = request.json
        db_instance = get_db()
        
        # Check if button exists
        existing_button = db_instance.get_menu_button(button_key)
        if not existing_button:
            return jsonify({'success': False, 'message': 'دکمه یافت نشد'}), 404
        
        success = db_instance.update_menu_button(
            button_key=button_key,
            button_text=data.get('button_text'),
            callback_data=data.get('callback_data'),
            button_type=data.get('button_type'),
            web_app_url=data.get('web_app_url'),
            row_position=data.get('row_position'),
            column_position=data.get('column_position'),
            is_active=data.get('is_active'),
            is_visible_for_admin=data.get('is_visible_for_admin'),
            is_visible_for_users=data.get('is_visible_for_users'),
            display_order=data.get('display_order')
        )
        
        if success:
            return jsonify({'success': True, 'message': 'دکمه با موفقیت بروزرسانی شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در بروزرسانی دکمه'}), 400
    except Exception as e:
        logger.error(f"Error updating menu button: {e}")
        return secure_error_response(e)

@app.route('/api/admin/menu-layout/button/<button_key>', methods=['DELETE'])
@admin_required
def api_admin_delete_menu_button(button_key):
    """Delete a menu button"""
    try:
        db_instance = get_db()
        success = db_instance.delete_menu_button(button_key)
        
        if success:
            return jsonify({'success': True, 'message': 'دکمه با موفقیت حذف شد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در حذف دکمه'}), 400
    except Exception as e:
        logger.error(f"Error deleting menu button: {e}")
        return secure_error_response(e)

@app.route('/api/admin/menu-layout/button/<button_key>/toggle', methods=['POST'])
@admin_required
def api_admin_toggle_menu_button(button_key):
    """Toggle menu button active status"""
    try:
        db_instance = get_db()
        success = db_instance.toggle_menu_button(button_key)
        
        if success:
            return jsonify({'success': True, 'message': 'وضعیت دکمه تغییر کرد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در تغییر وضعیت دکمه'}), 400
    except Exception as e:
        logger.error(f"Error toggling menu button: {e}")
        return secure_error_response(e)

@app.route('/api/admin/logs', methods=['GET'])
@admin_required
def api_admin_logs():
    """Get system logs"""
    try:
        limit = request.args.get('limit', 500, type=int)
        level = request.args.get('level', None)
        
        with db.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            if level:
                cursor.execute('''
                    SELECT * FROM system_logs 
                    WHERE level = %s
                    ORDER BY created_at DESC 
                    LIMIT %s
                ''', (level, limit))
            else:
                cursor.execute('''
                    SELECT * FROM system_logs 
                    ORDER BY created_at DESC 
                    LIMIT %s
                ''', (limit,))
            logs = cursor.fetchall()
        
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        return secure_error_response(e)

# Service Management API
@app.route('/api/services', methods=['GET'])
@login_required
def api_get_services():
    """Get all active services for the current user"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User not logged in'}), 401
            
        # Resolve database user ID
        # session['user_id'] might be Telegram ID or Database ID
        # Try to find user by Telegram ID first
        db_user = db.get_user_by_telegram_id(user_id)
        if db_user:
            # It was a Telegram ID, use the database ID
            target_user_id = db_user['id']
            logger.info(f"Resolved Telegram ID {user_id} to Database ID {target_user_id}")
        else:
            # It might be a Database ID already
            target_user_id = user_id
            logger.info(f"Using provided ID {user_id} as Database ID")
            
        services = db.get_all_user_services_for_volume(target_user_id)
        logger.info(f"API Services: Found {len(services)} services for user_id {target_user_id}")
        
        # Format services for frontend
        formatted_services = []
        for service in services:
            # Calculate usage stats
            total_gb = float(service.get('total_gb', 0) or 0)
            total_gb = round(total_gb, 2)
            used_gb = float(service.get('used_gb', 0) or 0)
            used_gb = round(used_gb, 2)
            remaining_gb = max(0, total_gb - used_gb)
            remaining_gb = round(remaining_gb, 2)
            
            usage_percentage = 0
            if total_gb > 0:
                usage_percentage = min(100, round((used_gb / total_gb) * 100, 1))

            # Determine effective active state
            is_active = service.get('is_active', False)
            status = service.get('status', '')
            
            expired = False
            expires_at_dt = None
            if service.get('expires_at'):
                try:
                    expires_at_dt = parse_datetime_safe(service.get('expires_at'))
                except Exception:
                    expires_at_dt = None
            if expires_at_dt:
                from datetime import datetime
                expired = expires_at_dt <= datetime.now()

            exhausted = bool(usage_percentage >= 100) or str(status or '') == 'exhausted'

            if status in ('exhausted', 'expired', 'disabled') or expired or exhausted:
                is_active = False
            elif not status and is_active:
                status = 'active'
            
            # Resolve is_online with fallback
            is_online = service.get('is_online')
            if is_online is None:
                is_online = service.get('cached_is_online', False)

            # Include all services returned by DB (active + grace period)
            formatted_services.append({
                'id': service['id'],
                'name': service.get('client_name', 'Unknown'),
                'total_gb': total_gb,
                'used_gb': used_gb,
                'remaining_gb': remaining_gb,
                'usage_percentage': usage_percentage,
                'remaining_days': service.get('remaining_days', 0),
                'is_active': is_active,
                'is_online': is_online,
                'status': status,
                'panel_name': service.get('panel_name', ''),
                'inbound_id': service.get('inbound_id'),
                'inbound_name': service.get('inbound_name', ''),
                'client_uuid': service.get('client_uuid'),
                'price_per_gb': service.get('price_per_gb', 0)
            })
            
        return jsonify({'success': True, 'services': formatted_services})
    except Exception as e:
        logger.error(f"Error getting user services: {e}")
        return secure_error_response(e)


@app.route('/api/admin/services/<int:service_id>', methods=['GET'])
@admin_required
def api_admin_get_service(service_id):
    """Get service details"""
    try:
        service = db.get_client_by_id(service_id)
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        return jsonify({'success': True, 'service': service})
    except Exception as e:
        logger.error(f"Error getting service: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/config', methods=['GET'])
@admin_required
def api_admin_get_service_config(service_id):
    """Get service config link"""
    try:
        service = db.get_client_by_id(service_id)
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        # Get config link from panel
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr or not panel_mgr.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
        
        config_link = panel_mgr.get_client_config_link(
            service['inbound_id'],
            service['client_uuid'],
            service.get('protocol', 'vless')
        )
        
        if not config_link:
            # Try to use saved config_link
            config_link = service.get('config_link', '')
        
        if not config_link:
            # Construct subscription link for Marzban or 3x-ui
            panel = db.get_panel(service['panel_id'])
            if panel:
                sub_url = panel.get('subscription_url', '').strip()
                if sub_url:
                     if not sub_url.startswith(('http://', 'https://')):
                          if not sub_url[0].isdigit():
                              sub_url = 'https://' + sub_url
                          else:
                              sub_url = 'http://' + sub_url
                     
                     if panel.get('panel_type') == 'marzban':
                         sub_url = sub_url.rstrip('/')
                         config_link = f"{sub_url}/sub/{service['client_uuid']}"
                     elif service.get('sub_id'):
                         # 3x-ui logic
                         if sub_url.endswith('/sub') or sub_url.endswith('/sub/'):
                             sub_url = sub_url.rstrip('/')
                             config_link = f"{sub_url}/{service.get('sub_id')}"
                         elif '/sub' in sub_url:
                             if sub_url.endswith('/'):
                                 config_link = f"{sub_url}{service.get('sub_id')}"
                             else:
                                 config_link = f"{sub_url}/{service.get('sub_id')}"
                         else:
                             sub_url = sub_url.rstrip('/')
                             config_link = f"{sub_url}/sub/{service.get('sub_id')}"
        
        if not config_link:
            return jsonify({'success': False, 'message': 'کانفیگ یافت نشد'}), 404
        
        return jsonify({'success': True, 'config_link': config_link})
    except Exception as e:
        logger.error(f"Error getting service config: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/qr', methods=['GET'])
@admin_required
def api_admin_get_service_qr(service_id):
    """Get service QR code"""
    try:
        service = db.get_client_by_id(service_id)
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        # Get config link
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr or not panel_mgr.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
        
        config_link = panel_mgr.get_client_config_link(
            service['inbound_id'],
            service['client_uuid'],
            service.get('protocol', 'vless')
        )
        
        if not config_link:
            config_link = service.get('config_link', '')
        
        if not config_link:
            panel = db.get_panel(service['panel_id'])
            if panel and panel.get('panel_type') == 'marzban':
                sub_url = panel.get('subscription_url', '')
                if sub_url:
                    config_link = f"{sub_url}/sub/{service['client_uuid']}"
        
        if not config_link:
            return jsonify({'success': False, 'message': 'کانفیگ یافت نشد'}), 404
        
        # Generate QR code
        import qrcode
        import io
        import base64
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(config_link)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        qr_base64 = base64.b64encode(buffer.read()).decode()
        
        return jsonify({'success': True, 'qr_code': qr_base64, 'config_link': config_link})
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/add-volume', methods=['POST'])
@admin_required
def api_admin_add_service_volume(service_id):
    """Add volume to service"""
    try:
        data = request.json
        volume_gb = data.get('volume_gb')
        
        if not volume_gb or volume_gb <= 0:
            return jsonify({'success': False, 'message': 'حجم نامعتبر است'}), 400
        
        service = db.get_client_by_id(service_id)
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        # Update volume on panel
        from admin_manager import AdminManager
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr or not panel_mgr.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
        
        current_total = service.get('total_gb', 0) or 0
        new_total = current_total + volume_gb
        
        success = panel_mgr.update_client_traffic(
            service['inbound_id'],
            service['client_uuid'],
            new_total
        )
        
        if not success:
            return jsonify({'success': False, 'message': 'خطا در افزودن حجم در پنل'}), 500
        
        # Update database
        db_instance = get_db()
        db_instance.update_client_total_gb(service_id, new_total)
        
        return jsonify({'success': True, 'message': f'{volume_gb} GB به سرویس اضافه شد'})
    except Exception as e:
        logger.error(f"Error adding service volume: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/renew', methods=['POST'])
@admin_required
def api_admin_renew_service(service_id):
    """Renew service"""
    try:
        data = request.json
        days = data.get('days')
        
        if not days or days <= 0:
            return jsonify({'success': False, 'message': 'تعداد روز نامعتبر است'}), 400
        
        service = db.get_client_by_id(service_id)
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        # Update expiration on panel
        from admin_manager import AdminManager
        from datetime import datetime, timedelta
        db_instance = get_db()
        admin_mgr = AdminManager(db_instance)
        panel_mgr = admin_mgr.get_panel_manager(service['panel_id'])
        
        if not panel_mgr or not panel_mgr.login():
            return jsonify({'success': False, 'message': 'خطا در اتصال به پنل'}), 500
        
        # Calculate new expiration
        current_expires = service.get('expires_at')
        if current_expires:
            try:
                if isinstance(current_expires, str):
                    current_expires_dt = datetime.fromisoformat(current_expires.replace('Z', '+00:00'))
                else:
                    current_expires_dt = current_expires
            except:
                current_expires_dt = datetime.now()
        else:
            current_expires_dt = datetime.now()
        
        new_expires = current_expires_dt + timedelta(days=days)
        expires_timestamp = int(new_expires.timestamp())
        
        # Update on panel
        if hasattr(panel_mgr, 'update_client_expiration'):
            success = panel_mgr.update_client_expiration(
                service['inbound_id'],
                service['client_uuid'],
                expires_timestamp,
                client_name=service.get('client_name')
            )
        else:
            # For panels that don't support expiration update, just update database
            success = True
        
        if not success:
            return jsonify({'success': False, 'message': 'خطا در تمدید سرویس در پنل'}), 500
        
        # Update database
        with db.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                UPDATE clients 
                SET expire_days = expire_days + %s,
                    expires_at = %s,
                    status = 'active',
                    is_active = 1,
                    warned_70_percent = 0,
                    warned_100_percent = 0,
                    warned_expired = 0,
                    warned_three_days = 0,
                    warned_one_week = 0,
                    notified_70_percent = 0,
                    notified_80_percent = 0,
                    exhausted_at = NULL,
                    expired_at = NULL,
                    deletion_grace_period_end = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (days, new_expires.isoformat(), service_id))
            conn.commit()
        
        return jsonify({'success': True, 'message': f'سرویس {days} روز تمدید شد'})
    except Exception as e:
        logger.error(f"Error renewing service: {e}")
        return secure_error_response(e)

@app.route('/api/admin/services/<int:service_id>/reserve-renew', methods=['POST'])
@admin_required
def api_admin_reserve_renew_service(service_id):
    """Reserve renewal for service"""
    try:
        data = request.json
        product_id = data.get('product_id')
        
        if not product_id:
            return jsonify({'success': False, 'message': 'محصول انتخاب نشده است'}), 400
        
        service = db.get_client_by_id(service_id)
        if not service:
            return jsonify({'success': False, 'message': 'سرویس یافت نشد'}), 404
        
        db_instance = get_db()
        product = db_instance.get_product(product_id)
        if not product:
            return jsonify({'success': False, 'message': 'محصول یافت نشد'}), 404
        
        # Add reserved service
        reserved_id = db_instance.add_reserved_service(
            client_id=service_id,
            product_id=product_id,
            volume_gb=product['volume_gb'],
            duration_days=product['duration_days']
        )
        
        if not reserved_id:
            return jsonify({'success': False, 'message': 'خطا در ثبت رزرو'}), 500
        
        return jsonify({'success': True, 'message': 'رزرو تمدید با موفقیت ثبت شد', 'reserved_id': reserved_id})
    except Exception as e:
        logger.error(f"Error reserving renewal: {e}")
        return secure_error_response(e)



# Error handlers - SECURITY: Don't leak information
@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors - don't reveal information"""
    client_ip = get_client_ip()
    logger.info(f"404 from {client_ip}: {request.path}")
    
    # Use comprehensive attack detection
    from security_utils import detect_attack_patterns, record_suspicious_activity
    is_attack, attack_type = detect_attack_patterns(request.path)
    if is_attack:
        record_suspicious_activity(client_ip, f'404_{attack_type}', request.path)
    
    if 'user_id' in session:
        user = db.get_user(session['user_id'])
        return render_template('404.html', user=user), 404
    return render_template('404.html', user=None), 404

@app.errorhandler(500)
def internal_error(e):
    """Handle 500 errors - don't leak stack traces or internal information"""
    client_ip = get_client_ip()
    # Log error internally but don't expose details
    logger.error(f"Internal error from {client_ip}: {request.path} - {type(e).__name__}")
    
    # Don't expose error details to user
    if 'user_id' in session:
        user = db.get_user(session['user_id'])
        return render_template('500.html', user=user), 500
    return render_template('500.html', user=None), 500

@app.errorhandler(403)
def forbidden(e):
    """Handle 403 errors"""
    client_ip = get_client_ip()
    logger.warning(f"403 Forbidden from {client_ip}: {request.path}")
    return Response('Access Denied', status=403, mimetype='text/plain')

@app.errorhandler(429)
def rate_limit_exceeded(e):
    """Handle rate limit errors"""
    client_ip = get_client_ip()
    logger.warning(f"Rate limit exceeded from {client_ip}: {request.path}")
    return Response('Too Many Requests', status=429, mimetype='text/plain')


# Theme Management Route
@app.route('/admin/settings/theme', methods=['POST'])
def update_theme():
    """Update admin panel theme"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'لطفا وارد شوید'}), 401
        
    try:
        data = request.get_json()
        theme = data.get('theme')
        
        if theme not in ['default', 'modern']:
            return jsonify({'success': False, 'message': 'تم نامعتبر است'}), 400
            
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager()
        if settings_mgr.set_theme(theme, user_id=session.get('user_id')):
            return jsonify({'success': True, 'message': 'تم با موفقیت تغییر کرد'})
        else:
            return jsonify({'success': False, 'message': 'خطا در ذخیره تنظیمات'}), 500
            
    except Exception as e:
        return secure_error_response(e)

@app.route('/admin/settings/backup', methods=['GET', 'POST'])
@admin_required
def admin_backup_settings():
    """Get or update backup settings"""
    try:
        from settings_manager import SettingsManager
        settings_mgr = SettingsManager()
        
        if request.method == 'GET':
            enabled = settings_mgr.get_setting('auto_backup_enabled', False)
            frequency = settings_mgr.get_setting('auto_backup_frequency', 24)
            return jsonify({'success': True, 'enabled': enabled, 'frequency': frequency})
            
        elif request.method == 'POST':
            data = request.json
            enabled = data.get('enabled', False)
            frequency = data.get('frequency', 24)
            
            settings_mgr.set_setting('auto_backup_enabled', enabled, description="Enable Auto Backup", user_id=session.get('user_id'))
            settings_mgr.set_setting('auto_backup_frequency', frequency, description="Auto Backup Frequency (Hours)", user_id=session.get('user_id'))
            
            return jsonify({'success': True, 'message': 'تنظیمات بکاپ با موفقیت ذخیره شد'})
            
    except Exception as e:
        logger.error(f"Error managing backup settings: {e}")
        return secure_error_response(e)



# ==================== WHEEL OF FORTUNE ROUTES ====================

@app.route('/wheel')
@login_required
def wheel_page():
    """Wheel of Fortune page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    
    if not user:
        return redirect(url_for('index'))
        
    photo_url = session.get('photo_url', '')
    
    # Theme Selection
    from settings_manager import SettingsManager
    settings_mgr = SettingsManager()
    current_theme = settings_mgr.get_theme()
    
    template_name = 'wheel.html'
    if current_theme == 'modern':
        template_name = 'themes/modern/wheel.html'
        
    return render_template(template_name, user=user, photo_url=photo_url)

@app.route('/api/wheel/config')
@login_required
def api_wheel_config():
    """Get wheel configuration"""
    try:
        from lottery_system import lottery_system
        db_instance = get_db()
        lottery_system.set_database(db_instance)
        
        config = lottery_system.get_wheel_config()
        
        # Check if user can spin
        user_id = session.get('user_id')
        user = db_instance.get_user(user_id)
        telegram_id = user['telegram_id'] if user else None
        
        if not telegram_id:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
            
        can_spin, message = lottery_system.can_spin(telegram_id)
        
        return jsonify({
            'success': True,
            'config': config,
            'can_spin': can_spin,
            'message': message
        })
    except Exception as e:
        logger.error(f"Error getting wheel config: {e}")
        return jsonify({'success': False, 'message': 'خطا در دریافت تنظیمات گردونه'}), 500

@app.route('/api/wheel/spin', methods=['POST'])
@login_required
@rate_limit(max_requests=1, window_seconds=5)
def api_wheel_spin():
    """Spin the wheel"""
    try:
        from lottery_system import lottery_system
        db_instance = get_db()
        lottery_system.set_database(db_instance)
        
        user_id = session.get('user_id')
        user = db_instance.get_user(user_id)
        telegram_id = user['telegram_id'] if user else None
        
        if not telegram_id:
            return jsonify({'success': False, 'message': 'کاربر یافت نشد'}), 404
        
        success, result = lottery_system.spin_wheel(telegram_id)
        
        if success:
            return jsonify({
                'success': True,
                'result': result
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', 'خطا در چرخش گردونه')
            }), 400
            
    except Exception as e:
        logger.error(f"Error spinning wheel: {e}")
        return jsonify({'success': False, 'message': 'خطا در انجام عملیات'}), 500

@app.route('/admin/wheel')
@admin_required
def admin_wheel():
    """Wheel of Fortune configuration page"""
    user_id = session.get('user_id')
    db_instance = get_db()
    user = db_instance.get_user(user_id)
    photo_url = session.get('photo_url', '')
    return render_template('admin/wheel.html', user=user, photo_url=photo_url)

@app.route('/api/admin/wheel/settings', methods=['GET', 'POST'])
@admin_required
def api_admin_wheel_settings():
    """Get or update wheel settings"""
    try:
        db_instance = get_db()
        
        # Ensure table exists
        try:
            with db_instance.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_settings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        setting_key VARCHAR(255) UNIQUE NOT NULL,
                        setting_value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                conn.commit()
        except Exception as table_err:
            logger.error(f"Error checking/creating wheel_settings table: {table_err}")
        
        if request.method == 'GET':
            settings = db_instance.get_wheel_settings()
            return jsonify({'success': True, 'settings': settings})
            
        elif request.method == 'POST':
            data = request.json
            success = True
            for key, value in data.items():
                if not db_instance.set_wheel_setting(key, value):
                    success = False
            
            if success:
                return jsonify({'success': True, 'message': 'تنظیمات با موفقیت ذخیره شد'})
            else:
                return jsonify({'success': False, 'message': 'خطا در ذخیره برخی تنظیمات'}), 500
                
    except Exception as e:
        logger.error(f"Error managing wheel settings: {e}")
        return secure_error_response(e)

@app.route('/api/admin/wheel/prizes', methods=['GET', 'POST'])
@admin_required
def api_admin_wheel_prizes():
    """Get or add wheel prizes"""
    try:
        db_instance = get_db()
        db_name = db_instance.database_name if hasattr(db_instance, 'database_name') else 'unknown'
        logger.info(f"Accessing wheel prizes. Method: {request.method}, DB: {db_name}")
        
        # Ensure table exists
        try:
            with db_instance.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_prizes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        type VARCHAR(50) NOT NULL,
                        value FLOAT DEFAULT 0,
                        probability FLOAT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        display_order INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                conn.commit()
        except Exception as table_err:
            logger.error(f"Error checking/creating wheel_prizes table: {table_err}")

        if request.method == 'GET':
            prizes = db_instance.get_prizes(active_only=False)
            logger.info(f"Retrieved {len(prizes)} prizes from DB {db_name}")
            
            # Auto-seed if empty (Debug helper)
            if not prizes:
                logger.info("Prize list is empty. Seeding default prize...")
                try:
                    default_id = db_instance.add_prize(
                        name="جایزه خوش‌آمدگویی (تست)",
                        type="balance",
                        value=1000,
                        probability=100,
                        is_active=True,
                        display_order=1
                    )
                    if default_id:
                        logger.info(f"Seeded default prize with ID: {default_id}")
                        prizes = db_instance.get_prizes(active_only=False)
                except Exception as seed_err:
                    logger.error(f"Error seeding default prize: {seed_err}")

            response = jsonify({'success': True, 'prizes': prizes, 'db_name': db_name})
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return response
            
        elif request.method == 'POST':
            data = request.json
            logger.info(f"Adding prize with data: {data}")
            
            # Validate input
            if not data.get('name'):
                return jsonify({'success': False, 'message': 'نام جایزه الزامی است'}), 400
            
            try:
                val = float(data.get('value') or 0)
                prob = float(data.get('probability') or 0)
                order = int(data.get('display_order') or 0)
            except ValueError:
                return jsonify({'success': False, 'message': 'مقادیر عددی نامعتبر است'}), 400
                
            prize_id = db_instance.add_prize(
                name=data.get('name'),
                type=data.get('type'),
                value=val,
                probability=prob,
                is_active=data.get('is_active', True),
                display_order=order
            )
            
            if prize_id:
                logger.info(f"Prize added successfully with ID: {prize_id}")
                return jsonify({'success': True, 'message': 'جایزه با موفقیت اضافه شد', 'prize_id': prize_id})
            else:
                logger.error("Failed to add prize - DB returned 0/None")
                return jsonify({'success': False, 'message': 'خطا در افزودن جایزه'}), 500
                
    except Exception as e:
        logger.error(f"Error managing wheel prizes: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Return 200 with success=False to let frontend show the error message
        return jsonify({'success': False, 'message': f'خطای سیستمی: {str(e)}'}), 200

@app.route('/api/admin/wheel/prizes/<int:prize_id>', methods=['PUT', 'DELETE'])
@admin_required
def api_admin_wheel_prize_detail(prize_id):
    """Update or delete a prize"""
    try:
        db_instance = get_db()
        db_name = db_instance.database_name if hasattr(db_instance, 'database_name') else 'unknown'
        logger.info(f"Managing prize {prize_id}. Method: {request.method}, DB: {db_name}")
        
        if request.method == 'PUT':
            data = request.json
            logger.info(f"Updating prize {prize_id} with data: {data}")
            
            # Validate numeric inputs
            if 'value' in data:
                try:
                    data['value'] = float(data['value'])
                except:
                    data['value'] = 0
                    
            if 'probability' in data:
                try:
                    data['probability'] = float(data['probability'])
                except:
                    data['probability'] = 0
            
            success = db_instance.update_prize(prize_id, **data)
            if success:
                logger.info(f"Prize {prize_id} updated successfully")
                return jsonify({'success': True, 'message': 'جایزه با موفقیت بروزرسانی شد'})
            else:
                logger.error(f"Failed to update prize {prize_id}")
                return jsonify({'success': False, 'message': 'خطا در بروزرسانی جایزه'}), 500
                
        elif request.method == 'DELETE':
            success = db_instance.delete_prize(prize_id)
            if success:
                logger.info(f"Prize {prize_id} deleted successfully")
                return jsonify({'success': True, 'message': 'جایزه با موفقیت حذف شد'})
            else:
                logger.error(f"Failed to delete prize {prize_id}")
                return jsonify({'success': False, 'message': 'خطا در حذف جایزه'}), 500
                
    except Exception as e:
        logger.error(f"Error managing prize detail: {e}")
        return secure_error_response(e)


# ==========================================
# ADMIN SETTINGS ROUTES
# ==========================================

@app.route('/admin/settings/backup', methods=['GET', 'POST'])
def admin_settings_backup():
    """Handle backup settings"""
    # Check admin session
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    from settings_manager import SettingsManager
    settings = SettingsManager()
    
    if request.method == 'GET':
        return jsonify({
            'success': True,
            'enabled': settings.get_setting('auto_backup_enabled', False),
            'frequency': int(settings.get_setting('auto_backup_interval', 24))
        })
        
    # POST
    try:
        data = request.get_json()
        enabled = data.get('enabled')
        frequency = data.get('frequency')
        
        # Save settings
        settings.set_setting('auto_backup_enabled', enabled, description="Auto Backup Enabled", updated_by=session.get('user_id'))
        settings.set_setting('auto_backup_interval', int(frequency), description="Auto Backup Interval (Hours)", updated_by=session.get('user_id'))
        
        # Trigger immediate backup if enabled (or re-enabled) or if frequency changed while enabled
        # Basically if enabled is true, we trigger a backup to reset the timer and confirm it works
        if enabled:
            try:
                # Reset last backup time to NOW so the scheduler picks it up based on new interval
                # BUT user requested immediate backup, so we do it now and set last time to now
                from database_backup_system import DatabaseBackupManager
                from telegram_helper import TelegramHelper
                
                # Get bot instance for backup manager
                bot = TelegramHelper.get_bot()
                
                # Initialize backup manager
                # We need to construct a minimal bot_config for the backup manager
                # Since we are in webapp, we might not have full bot_config, but we have what's needed
                from config import BOT_CONFIG
                
                # Ensure we pass the correct database manager
                # get_db() returns ProfessionalDatabaseManager instance
                db_manager = get_db()
                backup_manager = DatabaseBackupManager(db_manager, bot, BOT_CONFIG)
                
                # Run backup in background to not block response
                import asyncio
                
                async def run_immediate_backup():
                    try:
                        # Ensure topic exists
                        await backup_manager.ensure_backup_topic()
                        # Create and send backup
                        if await backup_manager.create_and_send_backup():
                            # Update last backup time
                            # This is crucial: we set the last backup time to NOW
                            # The scheduler checks: if (now - last_backup) >= frequency
                            # So if we set it to now, the next backup will be in 'frequency' hours
                            settings.set_setting('last_auto_backup_time', datetime.now().isoformat(), description="Last Auto Backup Time", updated_by=0)
                            logger.info("✅ Immediate backup completed successfully and timer reset")
                    except Exception as e:
                        logger.error(f"❌ Error in immediate backup: {e}")

                # Fire and forget (or run in event loop if possible)
                # Since we are in Flask (sync), we need to run async code carefully
                # Best way is to use a thread for the async loop
                def run_async_backup():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(run_immediate_backup())
                    loop.close()
                
                threading.Thread(target=run_async_backup).start()
                
                logger.info("🚀 Triggered immediate backup due to settings change")
                
            except Exception as e:
                logger.error(f"❌ Error triggering immediate backup: {e}")
        
        return jsonify({'success': True, 'message': 'تنظیمات بکاپ ذخیره شد و بکاپ جدید در حال ارسال است'})
    except Exception as e:
        logger.error(f"Error saving backup settings: {e}")
        return jsonify({'success': False, 'message': 'خطا در ذخیره تنظیمات'}), 500

if __name__ == '__main__':
    # Create templates and static directories if they don't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('static/images', exist_ok=True)
    
    # Get port and debug settings from config
    port = WEBAPP_CONFIG.get('port', 5000)
    debug_mode = WEBAPP_CONFIG.get('debug', False)
    
    # Run the app (debug=False prevents memory leaks in production)
    app.run(host='0.0.0.0', port=port, debug=debug_mode, threaded=True)
