"""
Security Utilities for VPN Bot
Provides rate limiting, input sanitization, and other security features
"""

import time
import hashlib
import hmac
import re
import html
import os
from functools import wraps
from typing import Dict, Optional, Callable, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
from flask import request, session, jsonify, g, Response
import logging

logger = logging.getLogger(__name__)

# Rate limiting storage (in production, use Redis)
_rate_limit_storage: Dict[str, list] = defaultdict(list)
_rate_limit_lock = {}

# IP blocking storage - tracks blocked IPs and their unblock time
_blocked_ips: Dict[str, float] = {}  # IP -> unblock timestamp

# Suspicious activity tracking - tracks suspicious activities per IP
_suspicious_activity: Dict[str, list] = defaultdict(list)  # IP -> list of (timestamp, activity_type, path)

# Attack pattern detection thresholds
MAX_SUSPICIOUS_ACTIVITIES = 3  # Block after 3 suspicious activities (more aggressive)
BLOCK_DURATION_HOURS = 48  # Block for 48 hours (longer block)
SUSPICIOUS_ACTIVITY_WINDOW = 300  # 5 minutes window

def clean_rate_limit_storage():
    """Clean old entries from rate limit storage"""
    current_time = time.time()
    keys_to_remove = []
    
    for key, timestamps in _rate_limit_storage.items():
        # Keep only entries from last hour
        _rate_limit_storage[key] = [ts for ts in timestamps if current_time - ts < 3600]
        if not _rate_limit_storage[key]:
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del _rate_limit_storage[key]

def rate_limit(max_requests: int = 10, window_seconds: int = 60, key_func: Optional[Callable] = None):
    """
    Rate limiting decorator for Flask routes
    
    Args:
        max_requests: Maximum number of requests allowed
        window_seconds: Time window in seconds
        key_func: Optional function to generate rate limit key (defaults to IP address)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate rate limit key
            if key_func:
                key = key_func()
            else:
                # Default: use IP address
                key = request.remote_addr or 'unknown'
            
            # Add route name to key for per-route limiting
            route_key = f"{key}:{request.endpoint}"
            
            current_time = time.time()
            
            # Clean old entries periodically
            if current_time % 60 < 1:  # Clean every minute
                clean_rate_limit_storage()
            
            # Get timestamps for this key
            timestamps = _rate_limit_storage[route_key]
            
            # Remove old timestamps outside the window
            timestamps[:] = [ts for ts in timestamps if current_time - ts < window_seconds]
            
            # Check if limit exceeded
            if len(timestamps) >= max_requests:
                logger.warning(f"Rate limit exceeded for {route_key}: {len(timestamps)} requests in {window_seconds}s")
                return jsonify({
                    'success': False,
                    'message': 'Too many requests. Please try again later.',
                    'retry_after': window_seconds
                }), 429
            
            # Add current timestamp
            timestamps.append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# CSRF protection removed - no longer needed

def sanitize_input(text: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize user input to prevent XSS and injection attacks
    
    Args:
        text: Input text to sanitize
        max_length: Maximum length (None for no limit)
    
    Returns:
        Sanitized text
    """
    if not isinstance(text, str):
        return ''
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    # HTML escape to prevent XSS
    text = html.escape(text)
    
    # Limit length
    if max_length:
        text = text[:max_length]
    
    return text.strip()

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks"""
    # Remove directory separators
    filename = filename.replace('/', '').replace('\\', '')
    
    # Remove null bytes
    filename = filename.replace('\x00', '')
    
    # Remove dangerous characters
    filename = re.sub(r'[<>:"|?*]', '', filename)
    
    # Limit length
    filename = filename[:255]
    
    return filename.strip()

def validate_telegram_id(telegram_id: any) -> Optional[int]:
    """Validate Telegram ID"""
    try:
        telegram_id = int(telegram_id)
        if telegram_id > 0:
            return telegram_id
    except (ValueError, TypeError):
        pass
    return None

def validate_amount(amount: any, min_amount: int = 0, max_amount: int = 100000000) -> Optional[int]:
    """Validate monetary amount"""
    try:
        amount = int(amount)
        if min_amount <= amount <= max_amount:
            return amount
    except (ValueError, TypeError):
        pass
    return None

def validate_positive_int(value: any, max_value: Optional[int] = None) -> Optional[int]:
    """Validate positive integer"""
    try:
        value = int(value)
        if value > 0:
            if max_value is None or value <= max_value:
                return value
    except (ValueError, TypeError):
        pass
    return None

def validate_panel_id(panel_id: any) -> Optional[int]:
    """Validate panel ID"""
    return validate_positive_int(panel_id)

def validate_client_name(name: str) -> bool:
    """Validate client name format"""
    if not name or not isinstance(name, str):
        return False
    
    # Check length
    if len(name) < 3 or len(name) > 50:
        return False
    
    # Allow alphanumeric, dash, underscore, and Persian characters
    if not re.match(r'^[a-zA-Z0-9_\-\u0600-\u06FF\s]+$', name):
        return False
    
    return True

def validate_discount_code(code: str) -> bool:
    """Validate discount code format"""
    if not code or not isinstance(code, str):
        return False
    
    # Check length
    if len(code) < 3 or len(code) > 50:
        return False
    
    # Allow alphanumeric and uppercase
    if not re.match(r'^[A-Z0-9]+$', code.upper()):
        return False
    
    return True

def validate_url(url: str) -> bool:
    """Validate URL format"""
    if not url or not isinstance(url, str):
        return False
    
    # Basic URL validation
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return bool(url_pattern.match(url))

def hash_password(password: str) -> str:
    """Hash password using SHA256 (for non-critical passwords)"""
    return hashlib.sha256(password.encode()).hexdigest()

def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks"""
    return hmac.compare_digest(a, b)

def get_client_ip() -> str:
    """Get client IP address from request, handling proxies"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr or 'unknown'

def record_suspicious_activity(ip: str, activity: str, path: str):
    """Record suspicious activity from an IP and auto-block if threshold exceeded"""
    current_time = time.time()
    
    # Clean old activities
    if ip in _suspicious_activity:
        _suspicious_activity[ip] = [
            (ts, act, p) for ts, act, p in _suspicious_activity[ip]
            if current_time - ts < SUSPICIOUS_ACTIVITY_WINDOW
        ]
    
    # Record new activity
    _suspicious_activity[ip].append((current_time, activity, path))
    
    # Enhanced security logging with more details
    user_agent = request.headers.get('User-Agent', 'Unknown') if hasattr(request, 'headers') else 'Unknown'
    referer = request.headers.get('Referer', 'None') if hasattr(request, 'headers') else 'None'
    method = request.method if hasattr(request, 'method') else 'Unknown'
    
    logger.warning(
        f"⚠️ SUSPICIOUS ACTIVITY from {ip}: {activity} - "
        f"Path: {path} - Method: {method} - "
        f"User-Agent: {user_agent[:100]} - Referer: {referer[:100]}"
    )
    
    # Check if threshold exceeded
    recent_activities = [a for a in _suspicious_activity[ip] if current_time - a[0] < SUSPICIOUS_ACTIVITY_WINDOW]
    if len(recent_activities) >= MAX_SUSPICIOUS_ACTIVITIES:
        block_ip(ip, BLOCK_DURATION_HOURS)
        logger.error(
            f"🚫 AUTO-BLOCKED IP {ip} after {len(recent_activities)} suspicious activities "
            f"in {SUSPICIOUS_ACTIVITY_WINDOW}s. Activities: {[a[1] for a in recent_activities]}"
        )

def block_ip(ip: str, duration_hours: int = 24):
    """Block an IP address for specified duration"""
    unblock_time = time.time() + (duration_hours * 3600)
    _blocked_ips[ip] = unblock_time
    logger.error(f"🚫 BLOCKED IP: {ip} for {duration_hours} hours (until {datetime.fromtimestamp(unblock_time)})")

def is_ip_blocked(ip: str) -> bool:
    """Check if an IP is currently blocked"""
    if ip not in _blocked_ips:
        return False
    
    unblock_time = _blocked_ips[ip]
    current_time = time.time()
    
    # If block expired, remove it
    if current_time >= unblock_time:
        del _blocked_ips[ip]
        return False
    
    return True

def clean_blocked_ips():
    """Clean expired IP blocks"""
    current_time = time.time()
    expired_ips = [ip for ip, unblock_time in _blocked_ips.items() if current_time >= unblock_time]
    for ip in expired_ips:
        del _blocked_ips[ip]
        logger.info(f"✅ Unblocked IP: {ip} (block expired)")

def get_suspicious_activity_count(ip: str, window_seconds: int = SUSPICIOUS_ACTIVITY_WINDOW) -> int:
    """Get count of suspicious activities for an IP in the last window_seconds"""
    current_time = time.time()
    if ip not in _suspicious_activity:
        return 0
    
    recent = [a for a in _suspicious_activity[ip] if current_time - a[0] < window_seconds]
    return len(recent)

def sanitize_error_message(error: Exception, include_details: bool = False) -> str:
    """Sanitize error messages to prevent information disclosure"""
    if not include_details:
        error_msg = str(error).lower()
        if 'database' in error_msg or 'sql' in error_msg:
            return 'خطا در ارتباط با پایگاه داده'
        elif 'connection' in error_msg or 'timeout' in error_msg:
            return 'خطا در برقراری ارتباط'
        elif 'permission' in error_msg or 'access' in error_msg:
            return 'عدم دسترسی'
        elif 'not found' in error_msg:
            return 'یافت نشد'
        elif 'invalid' in error_msg or 'validation' in error_msg:
            return 'اطلاعات نامعتبر'
        else:
            return 'خطای سیستمی - لطفاً دوباره تلاش کنید'
    return str(error)

def get_security_headers() -> Dict[str, str]:
    """Get comprehensive security headers - ALLOWING FONTS AND ICONS"""
    return {
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        # IMPORTANT: Allow fonts and icons from CDNs
        'Content-Security-Policy': (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://telegram.org https://cdn.telegram.org https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.telegram.org; "
            "frame-src 'self' https://telegram.org; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none';"
        ),
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains; preload',
        'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
    }

def apply_security_headers(response: Response) -> Response:
    """Apply security headers to response"""
    headers = get_security_headers()
    for key, value in headers.items():
        response.headers[key] = value
    # Remove server information
    response.headers.pop('Server', None)
    response.headers.pop('X-Powered-By', None)
    return response

def detect_path_traversal(path: str) -> bool:
    """Detect path traversal attacks (../, ..\\, encoded versions)"""
    path_lower = path.lower()
    
    # Check for common path traversal patterns
    traversal_patterns = [
        '../', '..\\', '%2e%2e%2f', '%2e%2e%5c',  # Basic traversal
        '....//', '....\\\\',  # Double encoding attempts
        '%252e%252e%252f',  # Double URL encoding
        '..%2f', '..%5c',  # Mixed encoding
        '/../', '\\..\\',  # With separators
    ]
    
    # Check for excessive directory separators (potential traversal)
    if path.count('../') > 3 or path.count('..\\') > 3:
        return True
    
    # Check for encoded traversal
    if any(pattern in path_lower for pattern in traversal_patterns):
        return True
    
    # Check for absolute paths on Windows/Linux
    if path.startswith('/etc/') or path.startswith('/proc/') or path.startswith('/sys/'):
        return True
    if re.match(r'^[a-z]:\\', path_lower):  # Windows drive letters
        return True
    
    return False

def detect_malformed_request() -> bool:
    """Detect malformed HTTP requests (binary data, invalid characters)"""
    try:
        # Check request path for binary/null bytes
        if request.path:
            try:
                request.path.encode('utf-8')
            except UnicodeEncodeError:
                return True
            
            # Check for null bytes
            if '\x00' in request.path:
                return True
        
        # Check query string
        if request.query_string:
            try:
                request.query_string.decode('utf-8')
            except UnicodeDecodeError:
                return True
            
            # Check for null bytes
            if b'\x00' in request.query_string:
                return True
        
        # Check headers for suspicious content
        for header_name, header_value in request.headers.items():
            if header_value:
                try:
                    header_value.encode('utf-8')
                except UnicodeEncodeError:
                    return True
                
                # Check for null bytes
                if '\x00' in header_value:
                    return True
        
        # Check for suspicious HTTP methods
        if request.method not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']:
            return True
        
    except Exception as e:
        logger.warning(f"Error checking request format: {e}")
        return True  # If we can't validate, treat as suspicious
    
    return False

def detect_attack_patterns(path: str) -> Tuple[bool, str]:
    """Detect common attack patterns and return (is_attack, attack_type)"""
    path_lower = path.lower()
    
    # Path traversal
    if detect_path_traversal(path):
        return True, 'path_traversal'
    
    # PHP exploitation attempts (from logs: phpinfo, config.php, etc.)
    php_attack_patterns = [
        'phpunit', 'eval-stdin', 'phpinfo', 'php://', 'phar://',
        'vendor/phpunit', 'composer.json', 'composer.lock',
        'config.php', 'pinfo.php', 'test.php', 'info.php',
        '?phpinfo', 'phpinfo=-1', 'phpinfo()'
    ]
    if any(pattern in path_lower for pattern in php_attack_patterns):
        return True, 'php_exploitation'
    
    # WordPress scanning
    wp_patterns = [
        'wp-admin', 'wp-includes', 'wp-content', 'xmlrpc.php',
        'wlwmanifest.xml', 'wp-config.php', 'wp-login.php'
    ]
    if any(pattern in path_lower for pattern in wp_patterns):
        return True, 'wordpress_scanning'
    
    # Sensitive file access (from logs: .env, .git, robots.txt, etc.)
    sensitive_patterns = [
        '.env', '.git', '.svn', '.hg', '.bzr',  # Version control
        '.sql', '.db', '.sqlite', '.sqlite3',  # Databases
        'config.yaml', 'config.yml', 'docker-compose',  # Config files
        'credentials', 'secrets', 'private', 'backup',  # Sensitive names
        '.pem', '.key', '.crt', '.p12', '.pfx',  # Certificates
        'phpinfo', 'info.php', 'test.php',  # Info disclosure
        'admin.php', 'login.php', 'config.php',  # Admin files
        'robots.txt',  # Common scanning target
        'client_secrets.json',  # OAuth secrets
        'appsettings.json',  # .NET config
    ]
    if any(pattern in path_lower for pattern in sensitive_patterns):
        return True, 'sensitive_file_access'
    
    # CGI/Shell access attempts (from logs: /cgi-bin/luci/)
    cgi_patterns = [
        '/cgi-bin/', '/bin/sh', '/bin/bash', '/usr/bin/env',
        'cmd.exe', 'powershell.exe', 'wmic.exe',
        'cgi-bin/luci', 'cgi-bin/', '/locale'
    ]
    if any(pattern in path_lower for pattern in cgi_patterns):
        return True, 'shell_access_attempt'
    
    # Cisco router exploits
    if '/+csco' in path_lower or '/+csce' in path_lower:
        return True, 'cisco_exploit'
    
    # Laravel/Symfony exploits (from logs: app_dev.php, _profiler/)
    laravel_patterns = [
        '/.env', '/app_dev.php', '/_profiler/', '/debug/',
        '/api/.env', '/laravel/.env', '/backend/.env',
        '/misc/.env', '/content/.env', '/docker/.env',
        '/env/.env', '/Dev/.env', '/cron/.env',
        '/localhost/.env', '/.gitlab-ci/.env',
        '/laravel/.env.production', '/local/.env.prod',
        '/public/.env', '/frontend/.env', '/locally/.env',
        '/v2/.env', '/lab/.env', '/.vscode/.env',
        '/.env.backup', '/.env.example'
    ]
    if any(pattern in path_lower for pattern in laravel_patterns):
        return True, 'framework_exploit'
    
    # Java exploitation (from logs: actuator/gateway/routes)
    java_patterns = [
        'actuator', '/gateway/routes', '.jar',
        'spring-boot-actuator', '/actuator/'
    ]
    if any(pattern in path_lower for pattern in java_patterns):
        return True, 'java_exploit'
    
    # XDEBUG exploitation attempts (from logs: ?XDEBUG_SESSION_START=phpstorm)
    if 'xdebug' in path_lower or 'xdebug_session' in path_lower:
        return True, 'xdebug_exploit'
    
    # Development server scanning (from logs: developmentserver/metadatauploader)
    dev_patterns = [
        'developmentserver', 'metadatauploader', 'dev.php',
        'development', 'staging', 'test.php'
    ]
    if any(pattern in path_lower for pattern in dev_patterns):
        return True, 'dev_server_scanning'
    
    # HTTP/2.0 protocol attacks (from logs: PRI * HTTP/2.0)
    if 'http/2.0' in path_lower or 'pri *' in path_lower:
        return True, 'http2_protocol_attack'
    
    return False, ''

def secure_before_request():
    """Comprehensive security check before every request"""
    # Clean expired blocks periodically
    if time.time() % 60 < 1:  # Every minute
        clean_blocked_ips()
    
    # Get client IP
    client_ip = get_client_ip()
    
    # Check if IP is blocked
    if is_ip_blocked(client_ip):
        logger.warning(f"🚫 Blocked IP {client_ip} attempted access to {request.path}")
        return Response('Access Denied', status=403, mimetype='text/plain')
    
    # Check for malformed requests
    if detect_malformed_request():
        record_suspicious_activity(client_ip, 'malformed_request', request.path)
        return Response('Bad Request', status=400, mimetype='text/plain')
    
    # Check for attack patterns
    path_lower = request.path.lower()
    
    # Allow legitimate static files
    allowed_static_extensions = ['.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.svg', 
                                 '.woff', '.woff2', '.ttf', '.eot', '.ico', '.webp']
    is_static_file = (path_lower.endswith(tuple(allowed_static_extensions)) or 
                     '/static/' in path_lower or 
                     '/css/' in path_lower or 
                     '/js/' in path_lower or 
                     '/images/' in path_lower)
    
    # Only check for attacks if not a legitimate static file
    if not is_static_file:
        is_attack, attack_type = detect_attack_patterns(request.path)
        if is_attack:
            record_suspicious_activity(client_ip, attack_type, request.path)
            return Response('Not Found', status=404, mimetype='text/plain')
    
    # Additional rate limiting for suspicious IPs
    suspicious_count = get_suspicious_activity_count(client_ip, 60)  # Last minute
    if suspicious_count > 0:
        # Apply stricter rate limiting for suspicious IPs
        route_key = f"{client_ip}:{request.endpoint}"
        current_time = time.time()
        
        if route_key in _rate_limit_storage:
            timestamps = _rate_limit_storage[route_key]
            timestamps[:] = [ts for ts in timestamps if current_time - ts < 60]
            
            # Limit to 2 requests per minute for suspicious IPs
            if len(timestamps) >= 2:
                logger.warning(f"Rate limit exceeded for suspicious IP {client_ip} on {request.endpoint}")
                return Response('Too Many Requests', status=429, mimetype='text/plain')
            
            timestamps.append(current_time)
    
    return None  # Continue with request

def secure_after_request(response: Response) -> Response:
    """Apply security headers after request"""
    return apply_security_headers(response)

# Import os for urandom
import os

