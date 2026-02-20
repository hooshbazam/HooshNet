"""
Optimized Monitoring System
Uses parallel processing, batching, and smart caching for maximum performance
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import threading
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from config import BOT_CONFIG

logger = logging.getLogger(__name__)

class OptimizedMonitor:
    """Highly optimized monitoring system with parallel processing"""
    
    def __init__(self, db, admin_manager, bot=None):
        self.db = db
        self.admin_manager = admin_manager
        self.bot = bot
        # Store bot token to create new instance in traffic monitor's event loop
        try:
            self.bot_token = bot.token if bot else None
        except (AttributeError, Exception):
            self.bot_token = BOT_CONFIG.get('token')
            
        self.monitoring = False
        
        # Thread pool for parallel API calls
        self.executor = ThreadPoolExecutor(max_workers=20)  # Process up to 20 panels in parallel
        
        # Cache for panel sessions (reuse connections)
        self.panel_sessions = {}  # {panel_id: panel_manager}
        self.session_lock = threading.Lock()
        
        # Cache for panel data (avoid redundant API calls)
        self.panel_data_cache = {}  # {panel_id: {'data': {...}, 'timestamp': ...}}
        self.cache_ttl = 30  # Cache for 30 seconds
        
        # Rate limiting for message sending
        self.message_queue = asyncio.Queue()
        self.message_semaphore = asyncio.Semaphore(5)
        self.last_message_time = {}
        self.min_message_interval = 1.0
        
    def get_panel_manager_cached(self, panel_id: int):
        """Get panel manager with session caching"""
        with self.session_lock:
            if panel_id in self.panel_sessions:
                return self.panel_sessions[panel_id]
            
            panel_manager = self.admin_manager.get_panel_manager(panel_id)
            if panel_manager:
                self.panel_sessions[panel_id] = panel_manager
            return panel_manager
    
    def get_all_clients_from_panel_batch(self, panel_id: int, panel_manager) -> Dict[str, Dict]:
        """
        Get ALL clients from a panel in ONE API call
        Returns: {client_uuid: client_details}
        """
        try:
            # Login once per panel
            if not panel_manager.login():
                logger.warning(f"⚠️ Could not login to panel {panel_id}")
                return {}
            
            # Get all inbounds in one call
            inbounds = panel_manager.get_inbounds()
            if not inbounds:
                return {}
            
            all_clients = {}
            
            # Extract all clients from all inbounds
            for inbound in inbounds:
                try:
                    # Ensure inbound is a dict
                    if not isinstance(inbound, dict) or inbound is None:
                        logger.debug(f"⚠️ Skipping non-dict or None inbound in panel {panel_id}")
                        continue
                    
                    inbound_id = inbound.get('id') if inbound else None
                    if not inbound_id:
                        continue
                    
                    # Get clients - check both direct clients and settings.clients (like get_client_details does)
                    clients = []
                    
                    # First check direct clients (most common in newer 3x-ui versions)
                    if 'clients' in inbound and isinstance(inbound['clients'], list):
                        clients = inbound['clients']
                    
                    # If no direct clients, check settings.clients
                    if not clients:
                        settings = inbound.get('settings', {})
                        if settings is None:
                            settings = {}
                        
                        if isinstance(settings, str):
                            import json
                            try:
                                settings = json.loads(settings)
                            except:
                                continue
                        
                        # Ensure settings is a dict after parsing
                        if isinstance(settings, dict) and 'clients' in settings:
                            clients = settings.get('clients', [])
                    
                    # Ensure clients is a list
                    if not isinstance(clients, list):
                        continue
                    
                    if len(clients) == 0:
                        continue  # Skip inbounds with no clients
                    
                    # Get clientStats for traffic data
                    client_stats = inbound.get('clientStats', [])
                    
                    # Process each client
                    for client in clients:
                        # Ensure client is a dict
                        if not isinstance(client, dict):
                            continue
                        
                        client_uuid = client.get('id')
                        if not client_uuid:
                            continue
                        
                        # Get traffic stats - try multiple sources
                        stat = None
                        used_traffic = 0
                        last_activity = 0
                        
                        # Priority 1: Get from clientStats - try multiple matching methods
                        if client_stats and isinstance(client_stats, list):
                            for stat_item in client_stats:
                                # Ensure stat_item is a dict
                                if not isinstance(stat_item, dict):
                                    continue
                                # Different 3x-ui versions use different field names
                                stat_id = stat_item.get('id', '')
                                stat_uuid = stat_item.get('uuid', '')
                                stat_email = stat_item.get('email', '')
                                
                                stat_id_str = str(stat_id) if stat_id else ''
                                stat_uuid_str = str(stat_uuid) if stat_uuid else ''

                                client_email = str(client.get('email', '') or '')
                                client_email_prefix = client_email.split('@')[0] if '@' in client_email else client_email
                                stat_email_str = str(stat_email) if stat_email is not None else ''
                                stat_email_prefix = stat_email_str.split('@')[0] if '@' in stat_email_str else stat_email_str

                                client_uuid_str = str(client_uuid)

                                if (
                                    stat_id_str == client_uuid_str or
                                    stat_uuid_str == client_uuid_str or
                                    (client_email and stat_email_str == client_email) or
                                    (client_email_prefix and stat_email_prefix == client_email_prefix)
                                ):
                                    stat = stat_item
                                    up_bytes = stat.get('up', 0) or 0
                                    down_bytes = stat.get('down', 0) or 0
                                    used_traffic = up_bytes + down_bytes
                                    last_activity = stat.get('lastOnline', 0) or 0
                                    break
                        
                        # Priority 2: Get from client object directly
                        if used_traffic == 0:
                            if 'up' in client and 'down' in client:
                                up_bytes = client.get('up', 0) or 0
                                down_bytes = client.get('down', 0) or 0
                                used_traffic = up_bytes + down_bytes
                            elif 'upload' in client and 'download' in client:
                                up_bytes = client.get('upload', 0) or 0
                                down_bytes = client.get('download', 0) or 0
                                used_traffic = up_bytes + down_bytes
                        
                        # Get last activity
                        if last_activity == 0:
                            last_activity = stat.get('lastOnline', 0) if stat else 0
                            if last_activity == 0:
                                last_activity = client.get('lastOnline', 0) or 0

                        try:
                            last_activity_num = int(float(last_activity)) if last_activity else 0
                        except Exception:
                            last_activity_num = 0
                        if 0 < last_activity_num < 1000000000000:
                            last_activity_num = last_activity_num * 1000
                        last_activity = last_activity_num
                        
                        # Get total traffic
                        total_traffic = client.get('totalGB', 0)
                        if total_traffic == 0:
                            total_traffic = client.get('total', 0) or client.get('totalGB', 0)
                        
                        client_details = {
                            'id': client_uuid,
                            'inbound_id': inbound_id,
                            'total_traffic': total_traffic,
                            'used_traffic': used_traffic,
                            'expiryTime': client.get('expiryTime', 0),
                            'enable': client.get('enable', True),
                            'last_activity': last_activity,
                            'email': client.get('email', 'Unknown')
                        }
                        
                        all_clients[str(client_uuid)] = client_details
                except Exception as e:
                    logger.debug(f"⚠️ Error processing inbound in panel {panel_id}: {e}")
                    continue
            
            return all_clients
            
        except Exception as e:
            logger.error(f"❌ Error getting batch clients from panel {panel_id}: {e}", exc_info=True)
            return {}
    
    def process_panel_clients(self, panel_id: int, db_clients: List[Dict]) -> Dict:
        """
        Process all clients for a single panel in parallel
        Returns: {'synced': count, 'errors': count, 'updates': [...], 'notifications': [...]}
        """
        result = {
            'synced': 0,
            'errors': 0,
            'updates': [],
            'notifications': []
        }
        
        try:
            # Get panel manager (cached)
            panel_manager = self.get_panel_manager_cached(panel_id)
            if not panel_manager:
                result['errors'] = len(db_clients)
                return result
            
            # Get ALL clients from panel in ONE API call
            panel_clients_map = self.get_all_clients_from_panel_batch(panel_id, panel_manager)
            
            # Process each database client
            now = datetime.now()
            batch_updates = []
            
            for db_client in db_clients:
                try:
                    client_uuid = str(db_client.get('client_uuid', ''))
                    if not client_uuid:
                        result['errors'] += 1
                        continue
                    
                    # Get client details from panel data
                    panel_client = panel_clients_map.get(client_uuid) if panel_clients_map else None
                    
                    # Check if client found in different inbound (from batch data)
                    if panel_client:
                        found_inbound_id = panel_client.get('inbound_id')
                        registered_inbound_id = db_client.get('inbound_id')
                        if found_inbound_id and found_inbound_id != registered_inbound_id:
                            try:
                                self.db.update_service_inbound_id(db_client.get('id'), found_inbound_id)
                            except Exception as e:
                                logger.error(f"❌ Failed to update inbound_id for service {db_client.get('id')}: {e}")
                    
                    # If not found in batch or batch was empty, get directly from panel
                    if not panel_client:
                        try:
                            # Create callback to update inbound_id if found in different inbound
                            def update_inbound_callback(service_id, new_inbound_id):
                                try:
                                    self.db.update_service_inbound_id(service_id, new_inbound_id)
                                except Exception as e:
                                    logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
                            
                            direct_client = panel_manager.get_client_details(
                                db_client.get('inbound_id'),
                                client_uuid,
                                update_inbound_callback=update_inbound_callback,
                                service_id=db_client.get('id')
                            )
                            if direct_client:
                                panel_client = {
                                    'used_traffic': direct_client.get('used_traffic', 0),
                                    'last_activity': direct_client.get('last_activity', 0),
                                    'expiryTime': direct_client.get('expiryTime', 0),
                                    'enable': direct_client.get('enable', True),
                                    'total_traffic': direct_client.get('total_traffic', 0)
                                }
                            else:
                                result['errors'] += 1
                                continue
                        except Exception as e:
                            result['errors'] += 1
                            continue
                    
                    # Extract data
                    used_traffic = panel_client.get('used_traffic', 0)
                    last_activity = panel_client.get('last_activity', 0)
                    total_traffic = panel_client.get('total_traffic', 0)
                    
                    # If used_traffic is 0, try to get it directly from panel (more accurate)
                    if used_traffic == 0:
                        try:
                            direct_client = panel_manager.get_client_details(
                                db_client.get('inbound_id'),
                                client_uuid
                            )
                            if direct_client:
                                direct_used_traffic = direct_client.get('used_traffic', 0)
                                if direct_used_traffic > 0:
                                    used_traffic = direct_used_traffic
                                    
                                direct_last_activity = direct_client.get('last_activity', 0)
                                if direct_last_activity > 0:
                                    last_activity = direct_last_activity
                        except:
                            pass
                    
                    # Convert bytes to GB
                    if used_traffic > 0:
                        used_gb = round(used_traffic / (1024**3), 4)
                    else:
                        used_gb = 0
                        
                    if total_traffic > 0:
                        total_gb = round(total_traffic / (1024**3), 4)
                    else:
                        total_gb = db_client.get('total_gb', 0)
                    
                    # Check if online (last activity < 2 minutes)
                    try:
                        last_activity_num = int(float(last_activity)) if last_activity else 0
                    except Exception:
                        last_activity_num = 0
                    last_activity_ms = last_activity_num if last_activity_num > 1000000000000 else (last_activity_num * 1000 if last_activity_num > 0 else 0)
                    enable = panel_client.get('enable', True)
                    enable_bool = bool(enable) if enable is not None else True

                    prev_used_gb = 0.0
                    try:
                        prev_used_gb = float(db_client.get('used_gb') or db_client.get('cached_used_gb') or 0)
                    except Exception:
                        prev_used_gb = 0.0
                    traffic_increased = (used_gb - prev_used_gb) > 0.0001
                    is_online = bool(enable_bool and traffic_increased)
                    
                    # Process expiry time
                    expiry_time = panel_client.get('expiryTime', 0)
                    remaining_days = None
                    expires_at = None
                    
                    if expiry_time and expiry_time > 0:
                        try:
                            if expiry_time > 1000000000000:  # Milliseconds
                                expiry_timestamp = expiry_time / 1000
                            else:  # Unix timestamp
                                expiry_timestamp = expiry_time
                            
                            expires_at_dt = datetime.fromtimestamp(expiry_timestamp)
                            expires_at = expires_at_dt
                            time_diff = expires_at_dt - now
                            remaining_days = max(0, int(time_diff.total_seconds() / 86400))
                        except:
                            pass
                    
                    # Prepare batch update
                    update_data = {
                        'client_id': int(db_client.get('id', 0)),
                        'used_gb': used_gb,
                        'last_activity': last_activity_ms,
                        'is_online': 1 if is_online else 0,
                        'remaining_days': remaining_days,
                        'expires_at': expires_at.isoformat() if expires_at else None
                    }
                    batch_updates.append(update_data)
                    result['synced'] += 1
                    
                    # --- NOTIFICATION LOGIC ---
                    
                    # Calculate usage percentage
                    usage_percentage = 0
                    if total_gb > 0:
                        usage_percentage = (used_gb / total_gb) * 100

                    current_status = str(db_client.get('status') or '').strip()
                    if total_gb > 0 and usage_percentage < 100:
                        if current_status in ('disabled', 'exhausted') and db_client.get('exhausted_at'):
                            self.db.reset_service_exhaustion(db_client['id'])
                    
                    # Check for 70% warning
                    if 70 <= usage_percentage < 100:
                        warned_70 = db_client.get('warned_70_percent', 0)
                        if not warned_70 and current_status not in ('disabled', 'expired', 'exhausted'):
                            result['notifications'].append({
                                'type': '70_percent',
                                'service': db_client,
                                'usage_percentage': usage_percentage,
                                'used_gb': used_gb,
                                'total_gb': total_gb,
                                'remaining_gb': max(0, total_gb - used_gb)
                            })
                    
                    # Check for 100% exhaustion
                    if usage_percentage >= 100:
                        notified_exhausted = db_client.get('notified_exhausted', 0)
                        exhausted_at = db_client.get('exhausted_at')
                        
                        # 1. Immediate Deletion Check (110% or +1GB)
                        should_delete_immediately = False
                        if usage_percentage > 110:
                            should_delete_immediately = True
                        if total_gb > 0 and (used_gb - total_gb) > 1.0:
                            should_delete_immediately = True
                            
                        if should_delete_immediately:
                            logger.warning(f"🚫 Deleting service {db_client['id']} immediately due to excessive usage ({usage_percentage:.1f}%)")
                            try:
                                if panel_manager.delete_client(db_client['inbound_id'], client_uuid):
                                    self.db.delete_client(db_client['id'])
                                    # Notify user about deletion
                                    result['notifications'].append({
                                        'type': 'deleted_excessive',
                                        'service': db_client,
                                        'reason': 'excessive_usage'
                                    })
                                    continue # Skip further processing for this client
                            except Exception as e:
                                logger.error(f"Failed to delete excessive usage service {db_client['id']}: {e}")

                        # 2. 24h Grace Period Deletion Check
                        if exhausted_at:
                            try:
                                exhausted_time = exhausted_at if isinstance(exhausted_at, datetime) else datetime.fromisoformat(str(exhausted_at))
                                if (now - exhausted_time).total_seconds() > 86400: # 24 hours
                                    logger.warning(f"🚫 Deleting service {db_client['id']} after 24h grace period")
                                    try:
                                        if panel_manager.delete_client(db_client['inbound_id'], client_uuid):
                                            self.db.delete_client(db_client['id'])
                                            # Notify user about deletion (optional, but good practice)
                                            result['notifications'].append({
                                                'type': 'deleted_expired',
                                                'service': db_client,
                                                'reason': 'expired_grace_period'
                                            })
                                            continue
                                    except Exception as e:
                                        logger.error(f"Failed to delete expired service {db_client['id']}: {e}")
                            except Exception as e:
                                logger.error(f"Error checking grace period for {db_client['id']}: {e}")

                        # 3. Standard Exhaustion Handling (Disable + Notify ONCE)
                        current_status = str(db_client.get('status', 'active') or 'active')
                        
                        # If not already disabled or not notified
                        if current_status not in ('disabled', 'exhausted') or not notified_exhausted:
                            # Disable if not disabled
                            if current_status not in ('disabled', 'exhausted'):
                                try:
                                    if panel_manager.disable_client(db_client['inbound_id'], client_uuid):
                                        self.db.update_service_status(db_client['id'], 'exhausted')
                                        self.db.update_service_exhaustion_time(db_client['id'])
                                except Exception as e:
                                    logger.error(f"Failed to disable exhausted service {db_client['id']}: {e}")
                            
                            # Send notification ONLY if not already notified
                            if not notified_exhausted:
                                result['notifications'].append({
                                    'type': 'exhausted',
                                    'service': db_client,
                                    'usage_percentage': usage_percentage,
                                    'used_gb': used_gb,
                                    'total_gb': total_gb
                                })
                                # Mark as notified immediately to prevent duplicates in next cycle
                                self.db.update_service_notified_exhausted(db_client['id'], True)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing client {db_client.get('id')}: {e}")
                    result['errors'] += 1
                    continue
            
            # Batch update database
            if batch_updates:
                self.batch_update_clients(batch_updates)
                result['updates'] = batch_updates
            
        except Exception as e:
            logger.error(f"❌ Error processing panel {panel_id}: {e}", exc_info=True)
            result['errors'] = len(db_clients)
        
        return result
    
    def batch_update_clients(self, updates: List[Dict]):
        """Batch update multiple clients in one database transaction"""
        if not updates:
            return
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    update_query = '''
                        UPDATE clients 
                        SET used_gb = %s,
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
                            update['used_gb'],
                            update['used_gb'],
                            update['last_activity'],
                            update['last_activity'],
                            update['is_online'],
                            update.get('remaining_days'),
                            update['expires_at'],
                            update['client_id']
                        )
                        for update in updates
                    ]
                    
                    cursor.executemany(update_query, values)
                    conn.commit()
                    
                except Exception as e:
                    conn.rollback()
                    logger.error(f"❌ Error in batch update: {e}")
                    raise
                finally:
                    cursor.close()
                    
        except Exception as e:
            logger.error(f"❌ Error in batch_update_clients: {e}", exc_info=True)
    
    async def send_notification(self, notification: Dict):
        """Send notification asynchronously"""
        try:
            if not self.bot:
                # Initialize bot if needed
                token = self.bot_token or BOT_CONFIG.get('token')
                if token:
                    self.bot = Bot(token=token)
                    await self.bot.initialize()
            
            if not self.bot:
                logger.warning("⚠️ No bot instance available for notifications")
                return

            notif_type = notification['type']
            service = notification['service']
            user = self.db.get_user_by_id(service['user_id'])
            
            if not user:
                return

            if notif_type == '70_percent':
                # Send 70% warning
                message = f"""⚠️ **هشدار مصرف حجم**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}
📊 **مصرف فعلی:** {notification['usage_percentage']:.1f}%
📦 **حجم کل:** {notification['total_gb']:.2f} گیگابایت
📉 **حجم مصرف شده:** {notification['used_gb']:.2f} گیگابایت
♾ **حجم باقی‌مانده:** {notification['remaining_gb']:.2f} گیگابایت

⚠️ **توجه:** شما بیش از ۷۰ درصد حجم سرویس خود را مصرف کرده‌اید.

💡 **پیشنهاد:** برای ادامه استفاده بدون وقفه، حجم سرویس خود را افزایش دهید یا برای سرویس جدید اقدام کنید.

🔔 **یادآوری:** وقتی حجم به ۱۰۰ درصد برسد، سرویس غیرفعال شده و ۲۴ ساعت فرصت برای تمدید خواهید داشت."""

                keyboard = [
                    [InlineKeyboardButton("➕ افزایش حجم", callback_data=f"add_volume_{service['id']}")],
                    [InlineKeyboardButton("🛒 خرید سرویس جدید", callback_data="buy_service")],
                    [InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]
                ]
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Mark as warned
                self.db.update_service_70_percent_warning(service['id'], warned=True)
                
            elif notif_type == 'exhausted':
                # Send exhaustion notification
                message = f"""🚫 **حجم تمام شد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}
📊 **وضعیت:** غیرفعال شده

⚠️ **توجه:** حجم سرویس شما به طور کامل تمام شده و سرویس غیرفعال شده است.

⏰ **مهلت:** شما ۲۴ ساعت فرصت دارید تا سرویس خود را تمدید کنید.
اگر تا ۲۴ ساعت تمدید نکنید، سرویس حذف خواهد شد.

⚠️ **هشدار:** اگر در این مدت بیش از ۱۱۰ درصد حجم یا ۱ گیگابایت بیشتر مصرف کنید، سرویس فوراً حذف خواهد شد.

برای تمدید سرویس، روی دکمه تمدید کلیک کنید."""

                keyboard = [
                    [InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_service_{service['id']}")],
                    [InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]
                ]
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif notif_type == 'deleted_excessive':
                # Send excessive usage deletion notification
                message = f"""🚫 **حذف سرویس به دلیل مصرف بیش از حد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}

⚠️ **توجه:** سرویس شما به دلیل مصرف بیش از حد مجاز (بیش از ۱۱۰ درصد یا ۱ گیگابایت اضافه پس از اتمام حجم) به صورت خودکار حذف شد.

❌ این عملیات غیرقابل بازگشت است."""

                keyboard = [[InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]]
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif notif_type == 'deleted_expired':
                # Send expired grace period deletion notification
                message = f"""🚫 **حذف سرویس به دلیل عدم تمدید**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}

⚠️ **توجه:** مهلت ۲۴ ساعته تمدید سرویس شما به پایان رسید و سرویس به صورت خودکار حذف شد.

❌ این عملیات غیرقابل بازگشت است."""

                keyboard = [[InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]]
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        except Exception as e:
            logger.error(f"❌ Error sending notification: {e}")

    def sync_all_clients_optimized(self):
        """
        Optimized sync: Groups clients by panel and processes panels in parallel
        """
        start_time = time.time()
        logger.info("🚀 Starting optimized sync of all clients...")
        
        try:
            # Ensure connection pool exists
            from professional_database import ProfessionalDatabaseManager
            if self.db.database_name not in ProfessionalDatabaseManager._connection_pools:
                self.db._init_connection_pool()
            
            # Get all active panels
            active_panels = self.db.get_panels(active_only=True)
            if not active_panels:
                return
            
            # Group clients by panel_id
            clients_by_panel = defaultdict(list)
            for panel in active_panels:
                panel_id = panel['id']
                with self.db.get_connection() as conn:
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
            
            # Process panels in parallel
            futures = {}
            for panel_id, clients in clients_by_panel.items():
                future = self.executor.submit(self.process_panel_clients, panel_id, clients)
                futures[future] = panel_id
            
            # Collect results
            total_synced = 0
            total_errors = 0
            all_notifications = []
            
            for future in as_completed(futures):
                panel_id = futures[future]
                try:
                    result = future.result(timeout=60)
                    total_synced += result['synced']
                    total_errors += result['errors']
                    if result.get('notifications'):
                        all_notifications.extend(result['notifications'])
                except Exception as e:
                    logger.error(f"❌ Error processing panel {panel_id}: {e}")
            
            # Send notifications asynchronously
            if all_notifications:
                logger.info(f"📢 Sending {len(all_notifications)} notifications...")
                async def send_all():
                    for notif in all_notifications:
                        await self.send_notification(notif)
                
                try:
                    asyncio.run(send_all())
                except Exception as e:
                    logger.error(f"❌ Error sending notifications: {e}")
            
            duration = time.time() - start_time
            logger.info(f"✅ Sync completed in {duration:.2f}s: {total_synced} synced, {total_errors} errors")
            
        except Exception as e:
            logger.error(f"❌ Error in optimized sync: {e}", exc_info=True)
    
    def start_monitoring(self, interval_seconds: int = 180):
        """Start monitoring loop"""
        self.monitoring = True
        logger.info(f"🚀 Optimized monitoring started (interval: {interval_seconds}s)")
        
        while self.monitoring:
            try:
                cycle_start = time.time()
                
                self.sync_all_clients_optimized()
                
                cycle_duration = time.time() - cycle_start
                wait_time = max(0, interval_seconds - cycle_duration)
                
                if wait_time > 0:
                    time.sleep(wait_time)
                else:
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"❌ Error in monitoring loop: {e}", exc_info=True)
                time.sleep(60)
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring = False
        self.executor.shutdown(wait=True)
        logger.info("🛑 Monitoring stopped")

