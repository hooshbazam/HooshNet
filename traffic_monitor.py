"""
Traffic Monitoring System
Monitors user traffic usage and handles notifications and auto-disable
Checks every 3 minutes for 70% and 100% usage thresholds
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
from professional_database import ProfessionalDatabaseManager
from admin_manager import AdminManager
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from config import BOT_CONFIG

class NoProxyRequest(HTTPXRequest):
    """Custom request class to disable system proxies"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client_kwargs['trust_env'] = False

logger = logging.getLogger(__name__)

class TrafficMonitor:
    def __init__(self, db: ProfessionalDatabaseManager, admin_manager: AdminManager, bot: Bot):
        """
        Initialize TrafficMonitor
        
        Args:
            db: Database manager
            admin_manager: Admin manager
            bot: Telegram Bot instance for sending messages
        """
        self.db = db
        self.admin_manager = admin_manager
        self.bot = bot  # Telegram Bot instance for sending messages
        # Store bot token to create new instance in traffic monitor's event loop
        # This avoids event loop conflicts when bot is used in a different thread
        try:
            self.bot_token = bot.token
        except (AttributeError, Exception):
            self.bot_token = BOT_CONFIG.get('token')
        self.bot_instance = None  # VPNBot instance - will be set separately if available (for reporting_system access)
        self.monitoring = False
        # Rate limiting for message sending (avoid Telegram flood control)
        self.message_queue = asyncio.Queue()
        self.message_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent messages
        self.last_message_time = {}  # Track last message time per user
        self.min_message_interval = 1.0  # Minimum 1 second between messages to same user
        self.pending_updates = []  # Store updates for bulk commit
        
    async def start_monitoring(self):
        """Start traffic monitoring - checks every 3 minutes (exactly 180 seconds)"""
        # Create a new Bot instance bound to this event loop to avoid event loop conflicts
        # This is necessary because the original bot was created in a different event loop
        try:
            # Get token - try bot_instance first (for multi-bot scenarios), then stored token, then config
            token = None
            if self.bot_instance and hasattr(self.bot_instance, 'bot_config'):
                token = self.bot_instance.bot_config.get('token')
            if not token:
                token = self.bot_token
            if not token:
                token = BOT_CONFIG.get('token')
            
            if token:
                # Create new bot instance in this event loop
                # Use NoProxyRequest to avoid system proxy issues
                request = NoProxyRequest()
                self.bot = Bot(token=token, request=request)
                # Initialize the bot in the current event loop
                # Initialize the bot in the current event loop
                await self.bot.initialize()
                logger.info("✅ Bot reinitialized in traffic monitor event loop")
            else:
                logger.warning("Could not get bot token, using original bot instance (may cause event loop issues)")
        except Exception as e:
            logger.warning(f"Could not reinitialize bot in traffic monitor event loop: {e}. Using original bot instance.")
            import traceback
            logger.debug(traceback.format_exc())
        
        self.monitoring = True
        logger.info("🚀 Traffic monitoring started")
        
        # Start message queue processor in background for rate-limited messaging
        asyncio.create_task(self._process_message_queue())
        
        while self.monitoring:
            try:
                import time
                check_start_time = time.time()
                
                # Check all services for volume usage
                await self.check_all_services()
                
                # Check for services that need to be deleted after 24 hours
                await self.check_for_deletion()
                
                check_duration = time.time() - check_start_time
                
                # Wait exactly 3 minutes (180 seconds) before next check
                # Subtract the time spent checking to maintain precise 3-minute intervals
                wait_time = max(0, 180 - check_duration)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning(f"⚠️ Check cycle took {check_duration:.2f} seconds (>180s)")
                    await asyncio.sleep(0.1)  # Small delay to prevent busy loop
                    
            except Exception as e:
                logger.error(f"❌ Error in traffic monitoring: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute on error before retry
    
    def stop_monitoring(self):
        """Stop traffic monitoring"""
        self.monitoring = False
    
    async def _cleanup_bot(self):
        """Clean up bot instance when monitoring stops"""
        try:
            if self.bot and hasattr(self.bot, 'shutdown'):
                await self.bot.shutdown()
        except Exception as e:
            logger.debug(f"Error shutting down bot: {e}")
    
    async def _process_message_queue(self):
        """Process message queue with rate limiting to avoid Telegram flood control"""
        while self.monitoring:
            try:
                # Get message from queue (wait max 1 second)
                try:
                    chat_id, message, reply_markup = await asyncio.wait_for(
                        self.message_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Rate limiting: check if we need to wait before sending to this user
                now = asyncio.get_event_loop().time()
                last_time = self.last_message_time.get(chat_id, 0)
                time_since_last = now - last_time
                
                if time_since_last < self.min_message_interval:
                    await asyncio.sleep(self.min_message_interval - time_since_last)
                
                # Send message with semaphore (limit concurrent sends)
                async with self.message_semaphore:
                    try:
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode='Markdown',
                            reply_markup=reply_markup
                        )
                        self.last_message_time[chat_id] = asyncio.get_event_loop().time()
                    except Exception as e:
                        # Log but don't spam - user might have blocked bot
                        if "blocked" not in str(e).lower() and "forbidden" not in str(e).lower():
                            logger.debug(f"Error sending message to {chat_id}: {e}")
                
                self.message_queue.task_done()
                
            except Exception as e:
                logger.debug(f"Error in message queue processor: {e}")
                await asyncio.sleep(0.1)
    
    async def _send_message_safe(self, chat_id: int, message: str, reply_markup=None):
        """Send message safely with rate limiting"""
        try:
            await self.message_queue.put((chat_id, message, reply_markup))
        except Exception as e:
            logger.debug(f"Error queuing message: {e}")

    async def flush_updates(self):
        """Flush pending updates to database"""
        if not self.pending_updates:
            return
            
        # Create a copy and clear the list immediately to avoid race conditions
        # (though we are in a single-threaded event loop, this is good practice)
        updates_to_process = list(self.pending_updates)
        self.pending_updates = []
        
        if not updates_to_process:
            return

        try:
            # Run in thread to avoid blocking event loop during DB operation
            await asyncio.to_thread(self.db.bulk_update_client_status, updates_to_process)
            logger.info(f"💾 Flushed {len(updates_to_process)} updates to database")
        except Exception as e:
            logger.error(f"❌ Error flushing updates: {e}")
    
    async def check_all_services(self):
        """Check all active services - OPTIMIZED with batch data for maximum speed"""
        try:
            import time
            check_start = time.time()
            
            # Get all active services
            services = self.db.get_all_active_services()
            
            # Clear pending updates at start of cycle
            self.pending_updates = []

            
            if not services:
                return
            
            # Group services by panel_id for parallel processing
            from collections import defaultdict
            services_by_panel = defaultdict(list)
            for service in services:
                panel_id = service.get('panel_id')
                if panel_id:
                    services_by_panel[panel_id].append(service)
            
            # Process panels in parallel
            tasks = []
            for panel_id, panel_services in services_by_panel.items():
                task = self.check_panel_services_parallel(panel_id, panel_services)
                tasks.append(task)
            
            # Wait for all panels to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # Flush any pending updates to database in bulk
            await self.flush_updates()

            
            check_duration = time.time() - check_start
            logger.info(f"✅ Checked {len(services)} services in {check_duration:.2f}s ({len(services)/max(check_duration, 0.1):.1f} services/sec)")
                
        except Exception as e:
            logger.error(f"❌ Error in check_all_services: {e}", exc_info=True)
    
    async def check_panel_services_parallel(self, panel_id: int, services: List[Dict]):
        """Check all services for a single panel - OPTIMIZED with batch data for maximum speed"""
        try:
            # Get panel manager once
            panel_manager = self.admin_manager.get_panel_manager(panel_id)
            if not panel_manager:
                return
            
            # Login once per panel
            try:
                if not panel_manager.login():
                    return
            except Exception as e:
                return
            
            # Get ALL clients from panel in ONE API call (batch) - MUCH FASTER
            all_panel_clients = self.get_all_clients_from_panel_batch(panel_manager)
            
            if not all_panel_clients:
                # Fallback: if batch fails, try individual calls (slower)
                logger.debug(f"⚠️ Batch data not available for panel {panel_id}, using individual calls")
                tasks = [self.check_service_traffic(service) for service in services]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                return
            
            # Process services in parallel using batch data - VERY FAST
            # Use semaphore to limit concurrent operations (avoid overwhelming panel)
            # INCREASED CONCURRENCY: Database bottleneck removed, can handle more parallel checks
            semaphore = asyncio.Semaphore(200)  # Max 200 concurrent operations per panel (was 50)

            
            async def check_service_with_semaphore(service):
                async with semaphore:
                    return await self.check_service_traffic_optimized(service, panel_manager, all_panel_clients)
            
            tasks = [check_service_with_semaphore(service) for service in services]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"❌ Error checking panel {panel_id} services: {e}", exc_info=True)
    
    def get_all_clients_from_panel_batch(self, panel_manager) -> Dict[str, Dict]:
        """
        Get ALL clients from a panel in ONE API call
        Returns: {client_uuid: client_details}
        """
        try:
            # Get all inbounds in one call
            inbounds = panel_manager.get_inbounds()
            if not inbounds:
                return {}
            
            all_clients = {}
            
            # Extract all clients from all inbounds
            for inbound in inbounds:
                inbound_id = inbound.get('id')
                if not inbound_id:
                    continue
                
                # Get clients - check both direct clients and settings.clients
                clients = []
                
                # First check direct clients (newer 3x-ui versions)
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
                    
                    if isinstance(settings, dict) and 'clients' in settings:
                        clients = settings.get('clients', [])
                
                # Ensure clients is a list
                if not isinstance(clients, list) or len(clients) == 0:
                    continue
                
                # Get clientStats for traffic data - use advanced matching like optimized_monitor
                client_stats = inbound.get('clientStats', [])
                
                # Process each client
                for client in clients:
                    client_uuid = client.get('id')
                    if not client_uuid:
                        continue
                    
                    # Get traffic stats - try multiple matching methods (like optimized_monitor)
                    stat = None
                    used_traffic = 0
                    last_activity = 0
                    
                    # Priority 1: Match from clientStats using multiple methods
                    if client_stats and isinstance(client_stats, list):
                        for stat_item in client_stats:
                            if not isinstance(stat_item, dict):
                                continue
                            
                            # Try multiple field names for matching
                            stat_id = stat_item.get('id', '')
                            stat_uuid = stat_item.get('uuid', '')
                            stat_email = stat_item.get('email', '')
                            
                            stat_id_str = str(stat_id) if stat_id else ''
                            stat_uuid_str = str(stat_uuid) if stat_uuid else ''
                            
                            # Extract UUID from email if present
                            email_uuid = ''
                            if '@' in str(stat_email):
                                email_parts = str(stat_email).split('@')[0]
                                if len(email_parts) > 30:  # UUID-like length
                                    email_uuid = email_parts
                            
                            # Match using multiple methods
                            if (stat_id_str == str(client_uuid) or 
                                stat_uuid_str == str(client_uuid) or
                                email_uuid == str(client_uuid)):
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
                    
                    # Get total traffic
                    total_traffic = client.get('totalGB', 0)
                    if total_traffic == 0:
                        total_traffic = client.get('total', 0)  # Alternative field name
                    
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
            
            return all_clients
            
        except Exception as e:
            logger.error(f"❌ Error getting batch clients from panel: {e}")
            return {}
    
    async def check_service_traffic_optimized(self, service: Dict, panel_manager, all_panel_clients: Dict):
        """Check traffic for a service using cached panel data"""
        try:
            service_id = service.get('id')
            client_uuid = str(service.get('client_uuid', ''))
            
            if not client_uuid:
                return
            
            # Get client details from batch data
            client_details = all_panel_clients.get(client_uuid)
            
            # If batch data has no traffic or missing, try direct API call for accuracy
            if not client_details or client_details.get('used_traffic', 0) == 0:
                # Fallback: Get real-time data directly from panel API
                try:
                    import inspect
                    sig = inspect.signature(panel_manager.get_client_details)
                    params = list(sig.parameters.keys())
                    
                    # Check if panel manager supports optional parameters (Marzban does, PanelManager doesn't)
                    # Check if panel manager supports optional parameters (Marzban does, PanelManager doesn't)
                    if 'update_inbound_callback' in params and 'service_id' in params:
                        # MarzbanPanelManager - supports callback and client_name
                        kwargs = {
                            'update_inbound_callback': None,
                            'service_id': service_id
                        }
                        if 'client_name' in params:
                            kwargs['client_name'] = service.get('client_name')
                            
                        direct_details = panel_manager.get_client_details(
                            service.get('inbound_id'),
                            client_uuid,
                            **kwargs
                        )
                    else:
                        # PanelManager - only accepts inbound_id and client_uuid
                        # Note: We updated PanelManager to accept these, but check just in case
                        if 'client_name' in params:
                             direct_details = panel_manager.get_client_details(
                                service.get('inbound_id'),
                                client_uuid,
                                client_name=service.get('client_name')
                            )
                        else:
                            direct_details = panel_manager.get_client_details(
                                service.get('inbound_id'),
                                client_uuid
                            )
                    
                    # Use direct data if available and has traffic, otherwise use batch data
                    if direct_details and direct_details.get('used_traffic', 0) > 0:
                        client_details = direct_details
                    elif not client_details:
                        client_details = direct_details
                except:
                    pass  # Use batch data if direct call fails
                
                if not client_details:
                    return
            
            await self.process_client_traffic(service, client_details)
                    
        except Exception as e:
            logger.error(f"❌ Error checking service {service.get('id')}: {e}", exc_info=True)
    
    async def check_service_traffic(self, service: Dict):
        """Check traffic usage for a specific service - REAL-TIME from panel API"""
        try:
            service_id = service.get('id')
            panel_id = service.get('panel_id')
            client_uuid = service.get('client_uuid', '')
            
            if not client_uuid:
                logger.warning(f"⚠️ Service {service_id} has no client_uuid")
                return
            
            panel_manager = self.admin_manager.get_panel_manager(panel_id)
            if not panel_manager:
                logger.warning(f"⚠️ Panel manager not found for panel {panel_id} (service {service_id})")
                return
            
            # Login to panel (will reuse session if already logged in)
            try:
                if not panel_manager.login():
                    logger.warning(f"⚠️ Could not login to panel {panel_id} for service {service_id}")
                    return
            except Exception as e:
                logger.warning(f"⚠️ Error connecting to panel {panel_id} for service {service_id}: {str(e)}")
                return
            
            # Create callback to update inbound_id if client is found in different inbound
            def update_inbound_callback(service_id, new_inbound_id):
                try:
                    self.db.update_service_inbound_id(service_id, new_inbound_id)
                    logger.info(f"✅ Updated service {service_id} inbound_id to {new_inbound_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to update inbound_id for service {service_id}: {e}")
            
            # Get client details DIRECTLY from panel API - REAL-TIME data
            # This ensures we get the most accurate traffic statistics
            # Check if panel manager supports optional parameters (Marzban does, PanelManager doesn't)
            import inspect
            sig = inspect.signature(panel_manager.get_client_details)
            params = list(sig.parameters.keys())
            
            if 'update_inbound_callback' in params and 'service_id' in params:
                # MarzbanPanelManager - supports callback
                kwargs = {
                    'update_inbound_callback': update_inbound_callback,
                    'service_id': service_id
                }
                if 'client_name' in params:
                    kwargs['client_name'] = service.get('client_name')
                
                client_details = panel_manager.get_client_details(
                    service.get('inbound_id'),
                    client_uuid,
                    **kwargs
                )
            else:
                # PanelManager - only accepts inbound_id and client_uuid
                if 'client_name' in params:
                    client_details = panel_manager.get_client_details(
                        service.get('inbound_id'),
                        client_uuid,
                        client_name=service.get('client_name')
                    )
                else:
                    client_details = panel_manager.get_client_details(
                        service.get('inbound_id'),
                        client_uuid,
                        client_name=service.get('client_name')
                    )
            
            if not client_details:
                logger.warning(f"⚠️ Could not get client details for service {service_id} (client_uuid: {client_uuid})")
                return
            
            # Verify we got traffic data (minimal logging for performance)
            
            await self.process_client_traffic(service, client_details)
                    
        except Exception as e:
            logger.error(f"❌ Error checking service {service.get('id')}: {e}", exc_info=True)
            import traceback
            logger.debug(traceback.format_exc())
    
    async def process_client_traffic(self, service: Dict, client: Dict):
        """Process traffic data for a client - REAL-TIME from panel API"""
        try:
            service_id = service.get('id')
            client_name = service.get('client_name', 'Unknown')
            
            # Check expiration for plan-based services first
            is_plan_service = service.get('product_id') is not None
            if is_plan_service:
                await self.check_plan_expiration(service, client)
            
            # Get traffic data from client details (REAL-TIME from panel API)
            # These values are in BYTES
            total_traffic_bytes = client.get('total_traffic', 0)
            used_traffic_bytes = client.get('used_traffic', 0)
            
            # Also check alternative field names (for compatibility)
            if total_traffic_bytes == 0:
                total_traffic_bytes = client.get('totalGB', 0)
            if used_traffic_bytes == 0:
                # Try to get from up/down if available
                up_bytes = client.get('up', 0) or 0
                down_bytes = client.get('down', 0) or 0
                if up_bytes > 0 or down_bytes > 0:
                    used_traffic_bytes = up_bytes + down_bytes
            
            # Ensure values are numeric (handle None/string cases)
            try:
                total_traffic_bytes = float(total_traffic_bytes) if total_traffic_bytes else 0
                used_traffic_bytes = float(used_traffic_bytes) if used_traffic_bytes else 0
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Service {service_id}: Invalid traffic data - total={total_traffic_bytes}, used={used_traffic_bytes}")
                total_traffic_bytes = 0
                used_traffic_bytes = 0
            
            # Convert to GB for logging and calculations (with high precision)
            used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 4) if used_traffic_bytes > 0 else 0
            total_gb = round(total_traffic_bytes / (1024 * 1024 * 1024), 4) if total_traffic_bytes > 0 else 0
            
            # Reduced logging for performance - only log important cases
            
            # Update used_gb in database - CRITICAL: This updates the database with real-time data
            # OPTIMIZATION: Queue update for bulk commit instead of individual DB call
            self.pending_updates.append({
                'id': service_id,
                'used_gb': used_gb
            })
            # self.db.update_client_status(service_id, used_gb=used_gb)

            
            # Skip if unlimited traffic (total_traffic_bytes <= 0 means unlimited)
            if total_traffic_bytes <= 0:
                return
            
            # Calculate usage percentage with high precision
            usage_percentage = (used_traffic_bytes / total_traffic_bytes) * 100 if total_traffic_bytes > 0 else 0
            remaining_bytes = max(0, total_traffic_bytes - used_traffic_bytes)
            remaining_gb = round(remaining_bytes / (1024 * 1024 * 1024), 4)
            
            # Check for 70% usage warning (only for active services, send once)
            if usage_percentage >= 70 and usage_percentage < 100:
                warned_70_percent = service.get('warned_70_percent', 0)
                if not warned_70_percent and service.get('status') != 'disabled':
                    logger.warning(f"⚠️ Service {service_id} ({client_name}) reached 70% usage: {usage_percentage:.2f}% ({used_gb:.2f}GB / {total_gb:.2f}GB, remaining: {remaining_gb:.2f}GB) - sending warning")
                    await self.send_70_percent_warning(service, usage_percentage, used_gb, total_gb, remaining_gb)
                    self.db.update_service_70_percent_warning(service_id, warned=True)
            
            # Note: Services in grace period are handled by check_for_deletion
            # They get 24 hours to renew before deletion
            
            # Check if 100% usage reached (even if already disabled, we should check for overage)
            if usage_percentage >= 100:
                current_status = service.get('status', 'active')
                if current_status != 'disabled':
                    logger.warning(f"🚫 Service {service_id} ({client_name}) reached 100% usage: {usage_percentage:.2f}% ({used_gb:.2f}GB / {total_gb:.2f}GB) - disabling immediately")
                    await self.handle_traffic_exhausted(service)
                else:
                    # Service is already disabled, check for overage during grace period
                    logger.debug(f"🔍 Service {service_id} already disabled at {usage_percentage:.2f}% - checking for overage")
                    await self.check_disabled_service_overage(service, usage_percentage, used_gb, total_gb)
            
        except Exception as e:
            logger.error(f"❌ Error processing client traffic for service {service.get('id')}: {e}", exc_info=True)
    
    async def check_disabled_service_overage(self, service: Dict, usage_percentage: float, used_gb: float, total_gb: float):
        """Check if disabled service has exceeded limits (110% or 1GB overage)"""
        try:
            service_id = service.get('id')
            exhausted_at = service.get('exhausted_at')
            
            # Only check services in grace period (disabled within last 24 hours)
            if not exhausted_at:
                return
            
            from datetime import datetime, timedelta
            if isinstance(exhausted_at, str):
                exhausted_time = datetime.fromisoformat(exhausted_at.replace('Z', '+00:00'))
            else:
                exhausted_time = exhausted_at
            
            now = datetime.now()
            if exhausted_time.tzinfo:
                now = now.replace(tzinfo=exhausted_time.tzinfo)
            
            # Check if still in grace period (less than 24 hours)
            time_diff = now - exhausted_time
            if time_diff.total_seconds() > 24 * 3600:
                return  # Grace period passed, will be handled by check_for_deletion
            
            # Check for overage: 110% or 1GB over
            total_gb_bytes = total_gb * (1024 * 1024 * 1024) if total_gb > 0 else 0
            used_gb_bytes = used_gb * (1024 * 1024 * 1024) if used_gb > 0 else 0
            overage_bytes = used_gb_bytes - total_gb_bytes if used_gb_bytes > total_gb_bytes else 0
            overage_gb = overage_bytes / (1024 * 1024 * 1024)
            
            # Check if exceeded limits
            if usage_percentage >= 110 or overage_gb >= 1.0:
                logger.warning(f"🚫 Service {service_id} exceeded limits during grace period ({usage_percentage:.2f}% or {overage_gb:.2f}GB over) - deleting immediately")
                await self.delete_service_for_overage(service, usage_percentage, overage_gb)
                
        except Exception as e:
            logger.error(f"Error checking disabled service overage for service {service.get('id')}: {e}")
    
    async def handle_traffic_exhausted(self, service: Dict):
        """Handle traffic exhaustion - disable service and set grace period"""
        try:
            # Check if already disabled
            if service.get('status') == 'disabled':
                return
            
            # Disable service on panel
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if panel_manager and panel_manager.login():
                success = panel_manager.disable_client(service['inbound_id'], service['client_uuid'], client_name=service.get('client_name'))
                if success:
                    # Update database - set status to disabled but keep is_active=True during grace period
                    self.db.update_service_status(service['id'], 'disabled')
                    self.db.update_service_exhaustion_time(service['id'])
                    # Note: We do NOT set is_active=False here - service remains visible during 24h grace period
                    # is_active will be set to False only when service is actually deleted after 24 hours
                    
                    # Send notification
                    await self.send_exhaustion_notification(service)
                    
                else:
                    logger.error(f"Failed to disable service {service['id']} on panel")
            else:
                logger.error(f"Could not connect to panel to disable service {service['id']}")
            
        except Exception as e:
            logger.error(f"Error handling traffic exhaustion for service {service['id']}: {e}")
    
    async def send_exhaustion_notification(self, service: Dict):
        """Send traffic exhaustion notification with grace period warning"""
        try:
            user = self.db.get_user_by_id(service['user_id'])
            if not user:
                return
            
            # Check if already warned - FORCE CHECK FROM DB to prevent race conditions
            flags = self.db.get_service_warning_flags(service['id'])
            if flags.get('warned_100_percent'):
                logger.info(f"⚠️ Service {service['id']} already warned about exhaustion (DB check), skipping notification")
                return
            
            # Determine service type (Plan vs Gig) based on expiration date
            # If it has an expiration date, it's a plan service (Renew)
            # If it doesn't have an expiration date, it's a gig service (Add Volume)
            is_plan_service = service.get('expires_at') is not None
            
            if is_plan_service:
                action_text = "تمدید"
                action_callback = f"renew_service_{service['id']}"
                button_text = "🔄 تمدید سرویس"
            else:
                action_text = "افزایش حجم"
                action_callback = f"add_volume_{service['id']}"
                button_text = "➕ افزایش حجم"

            message = f"""🚫 **حجم تمام شد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}
📊 **وضعیت:** غیرفعال شده

⚠️ **توجه:** حجم سرویس شما به طور کامل تمام شده و سرویس غیرفعال شده است.

⏰ **مهلت:** شما ۲۴ ساعت فرصت دارید تا {action_text} انجام دهید.
اگر تا ۲۴ ساعت اقدام نکنید، سرویس حذف خواهد شد.

⚠️ **هشدار:** اگر در این مدت بیش از ۱۱۰ درصد حجم یا ۱ گیگابایت بیشتر مصرف کنید، سرویس فوراً حذف خواهد شد.

برای {action_text}، روی دکمه زیر کلیک کنید."""
            
            # Create inline keyboard with contextual button
            keyboard = [
                [
                    InlineKeyboardButton(button_text, callback_data=action_callback),
                ],
                [
                    InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Use rate-limited message sending to avoid flood control
            await self._send_message_safe(
                user['telegram_id'],
                message,
                reply_markup
            )
            
            
            # Update warning status
            self.db.update_service_100_percent_warning(service['id'], True)
            
            # Report to channel
            try:
                # CRITICAL: Use bot_instance.reporting_system (VPNBot) instead of bot.reporting_system (Telegram Bot)
                reporting_system = None
                if self.bot_instance and hasattr(self.bot_instance, 'reporting_system'):
                    reporting_system = self.bot_instance.reporting_system
                elif hasattr(self.bot, 'reporting_system'):
                    reporting_system = self.bot.reporting_system
                
                if reporting_system:
                    service_data = {
                        'service_name': service.get('client_name', 'سرویس'),
                        'usage_percentage': 100.0,
                        'total_gb': service.get('total_gb', 0),
                        'panel_name': service.get('panel_name', 'نامشخص')
                    }
                    await reporting_system.report_service_volume_exhausted(user, service_data)
            except Exception as e:
                logger.error(f"Failed to send exhaustion report to channel: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error sending exhaustion notification: {e}")
    
    async def send_70_percent_warning(self, service: Dict, usage_percentage: float, used_gb: float, total_gb: float, remaining_gb: float):
        """Send 70% volume usage warning to user"""
        try:
            user = self.db.get_user_by_id(service['user_id'])
            if not user:
                return
            
            # Check if already warned - FORCE CHECK FROM DB to prevent race conditions
            flags = self.db.get_service_warning_flags(service['id'])
            if flags.get('warned_70_percent'):
                logger.info(f"⚠️ Service {service['id']} already warned about 70% usage (DB check), skipping notification")
                return

            # Determine service type (Plan vs Gig) based on expiration date
            is_plan_service = service.get('expires_at') is not None
            
            if is_plan_service:
                suggestion_text = "برای ادامه استفاده بدون وقفه، سرویس خود را تمدید کنید."
                action_callback = f"renew_service_{service['id']}"
                button_text = "🔄 تمدید سرویس"
            else:
                suggestion_text = "برای ادامه استفاده بدون وقفه، حجم سرویس خود را افزایش دهید."
                action_callback = f"add_volume_{service['id']}"
                button_text = "➕ افزایش حجم"

            message = f"""⚠️ **هشدار مصرف حجم**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}
📊 **مصرف فعلی:** {usage_percentage:.1f}%
📦 **حجم کل:** {total_gb:.2f} گیگابایت
📉 **حجم مصرف شده:** {used_gb:.2f} گیگابایت
♾ **حجم باقی‌مانده:** {remaining_gb:.2f} گیگابایت

⚠️ **توجه:** شما بیش از ۷۰ درصد حجم سرویس خود را مصرف کرده‌اید.

💡 **پیشنهاد:** {suggestion_text}

🔔 **یادآوری:** وقتی حجم به ۱۰۰ درصد برسد، سرویس غیرفعال شده و ۲۴ ساعت فرصت برای اقدام خواهید داشت."""
            
            # Create inline keyboard with contextual button
            keyboard = [
                [
                    InlineKeyboardButton(button_text, callback_data=action_callback),
                ],
                [
                    InlineKeyboardButton("🛒 خرید سرویس جدید", callback_data="buy_service"),
                ],
                [
                    InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Use rate-limited message sending to avoid flood control
            await self._send_message_safe(
                user['telegram_id'],
                message,
                reply_markup
            )
            
            # Report to channel
            try:
                # CRITICAL: Use bot_instance.reporting_system (VPNBot) instead of bot.reporting_system (Telegram Bot)
                reporting_system = None
                if self.bot_instance and hasattr(self.bot_instance, 'reporting_system'):
                    reporting_system = self.bot_instance.reporting_system
                elif hasattr(self.bot, 'reporting_system'):
                    reporting_system = self.bot.reporting_system
                
                if reporting_system:
                    service_data = {
                        'service_name': service.get('client_name', 'سرویس'),
                        'usage_percentage': usage_percentage,
                        'total_gb': total_gb,
                        'remaining_gb': remaining_gb,
                        'used_gb': used_gb,
                        'panel_name': service.get('panel_name', 'نامشخص')
                    }
                    await reporting_system.report_service_volume_70_percent(user, service_data)
            except Exception as e:
                logger.error(f"Failed to send 70% warning report to channel: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error sending 70% warning: {e}")
    
    async def delete_service_for_overage(self, service: Dict, usage_percentage: float, overage_gb: float):
        """Delete service immediately due to overage during grace period"""
        try:
            service_id = service.get('id')
            
            # Delete from panel first
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if panel_manager and panel_manager.login():
                success = panel_manager.delete_client(service['inbound_id'], service['client_uuid'])
                if not success:
                    logger.warning(f"Failed to delete overage service {service_id} from panel")
            else:
                logger.warning(f"Could not connect to panel to delete overage service {service_id}")
            
            # Delete from database
            self.db.delete_service(service_id)
            
            # Send notification to user
            user = self.db.get_user_by_id(service['user_id'])
            if user:
                message = f"""🗑️ **سرویس حذف شد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}

⚠️ **توجه:** سرویس شما به دلیل استفاده بیش از حد حذف شده است.

📊 **مصرف:** {usage_percentage:.1f}% ({overage_gb:.2f} گیگابایت بیشتر از حجم مجاز)

سرویس شما در دوره مهلت ۲۴ ساعته بیش از ۱۱۰ درصد حجم یا ۱ گیگابایت بیشتر مصرف کرده است.

برای خرید سرویس جدید، روی دکمه صفحه اصلی کلیک کنید."""
                
                keyboard = [[InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            
            # Report to channel
            if user:
                try:
                    # CRITICAL: Use bot_instance.reporting_system (VPNBot) instead of bot.reporting_system (Telegram Bot)
                    reporting_system = None
                    if self.bot_instance and hasattr(self.bot_instance, 'reporting_system'):
                        reporting_system = self.bot_instance.reporting_system
                    elif hasattr(self.bot, 'reporting_system'):
                        reporting_system = self.bot.reporting_system
                    
                    if reporting_system:
                        service_data = {
                            'service_name': service.get('client_name', 'سرویس'),
                            'total_gb': service.get('total_gb', 0),
                            'panel_name': service.get('panel_name', 'نامشخص'),
                            'usage_percentage': usage_percentage,
                            'overage_gb': overage_gb
                        }
                        await reporting_system.report_service_auto_deleted(user, service_data)
                except Exception as e:
                    logger.error(f"Failed to send overage deletion report to channel: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error deleting service for overage {service_id}: {e}")
    
    async def check_for_deletion(self):
        """Check for services that should be deleted after 24 hours"""
        try:
            # Get services that were exhausted more than 24 hours ago
            services_to_delete = self.db.get_services_for_deletion()
            
            for service in services_to_delete:
                await self.delete_exhausted_service(service)
            
            # Check for expired plan services that need deletion
            expired_plan_services = self.db.get_expired_plan_services_for_deletion()
            for service in expired_plan_services:
                await self.delete_expired_plan_service(service)
                
        except Exception as e:
            logger.error(f"Error checking for deletion: {e}")
    
    async def delete_exhausted_service(self, service: Dict):
        """Delete an exhausted service after 24 hours grace period"""
        try:
            # Delete from panel first
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if panel_manager and panel_manager.login():
                success = panel_manager.delete_client(service['inbound_id'], service['client_uuid'])
                if not success:
                    logger.warning(f"Failed to delete service {service['id']} from panel")
            else:
                logger.warning(f"Could not connect to panel to delete service {service['id']}")
            
            # Delete from database
            self.db.delete_service(service['id'])
            
            # Send final notification to user
            user = self.db.get_user_by_id(service['user_id'])
            if user:
                message = f"""🗑️ **سرویس حذف شد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}

⚠️ **توجه:** سرویس شما به دلیل عدم تمدید بعد از ۲۴ ساعت حذف شده است.

برای خرید سرویس جدید، روی دکمه صفحه اصلی کلیک کنید."""
                
                keyboard = [[InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            
            
            # Report to channel
            if user:
                try:
                    # CRITICAL: Use bot_instance.reporting_system (VPNBot) instead of bot.reporting_system (Telegram Bot)
                    reporting_system = None
                    if self.bot_instance and hasattr(self.bot_instance, 'reporting_system'):
                        reporting_system = self.bot_instance.reporting_system
                    elif hasattr(self.bot, 'reporting_system'):
                        reporting_system = self.bot.reporting_system
                    
                    if reporting_system:
                        from datetime import datetime
                        service_data = {
                            'service_name': service.get('client_name', 'سرویس'),
                            'total_gb': service.get('total_gb', 0),
                            'panel_name': service.get('panel_name', 'نامشخص'),
                            'exhausted_at': service.get('exhausted_at', 'نامشخص')
                        }
                        await reporting_system.report_service_auto_deleted(user, service_data)
                except Exception as e:
                    logger.error(f"Failed to send auto-deletion report to channel: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error deleting exhausted service {service['id']}: {e}")
    
    async def check_plan_expiration(self, service: Dict, client: Dict = None):
        """Check if a plan-based service has expired or is about to expire"""
        try:
            service_id = service.get('id')
            expires_at = service.get('expires_at')
            product_id = service.get('product_id')
            
            # Only check plan services with expiration dates
            if not product_id or not expires_at:
                return
            
            # Parse expiration date
            try:
                from datetime import datetime, timedelta
                if isinstance(expires_at, str):
                    exp_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                else:
                    exp_date = expires_at
                
                now = datetime.now()
                if exp_date.tzinfo:
                    now = now.replace(tzinfo=exp_date.tzinfo)
                
                # Calculate remaining days
                time_diff = exp_date - now
                remaining_days = time_diff.days
                
                # Check for 3 days warning (only once)
                warned_three_days = service.get('warned_one_week', False)  # Reuse this field for 3 days warning
                if remaining_days <= 3 and remaining_days > 0 and not warned_three_days:
                    logger.warning(f"⚠️ Plan service {service_id} expires in {remaining_days} days - sending 3-day warning")
                    await self.send_three_days_expiration_warning(service, remaining_days)
                    self.db.update_service_warned_one_week(service_id, warned=True)
                
                # Check if expired
                if exp_date <= now:
                    # Service has expired
                    current_status = service.get('status', 'active')
                    expired_at = service.get('expired_at')
                    
                    # If not already disabled, disable it and send notification
                    if current_status != 'disabled':
                        logger.warning(f"⏰ Plan service {service_id} expired - disabling")
                        await self.handle_plan_expiration(service)
                    # If already disabled, check for overage during grace period
                    elif expired_at and client:
                        # Check for overage during grace period
                        total_traffic_bytes = client.get('total_traffic', 0) or client.get('totalGB', 0)
                        used_traffic_bytes = client.get('used_traffic', 0)
                        
                        if total_traffic_bytes > 0:
                            used_gb = round(used_traffic_bytes / (1024 * 1024 * 1024), 4) if used_traffic_bytes > 0 else 0
                            total_gb = round(total_traffic_bytes / (1024 * 1024 * 1024), 4) if total_traffic_bytes > 0 else 0
                            usage_percentage = (used_traffic_bytes / total_traffic_bytes) * 100 if total_traffic_bytes > 0 else 0
                            
                            await self.check_expired_service_overage(service, usage_percentage, used_gb, total_gb)
                
            except Exception as e:
                logger.error(f"Error parsing expiration date for service {service_id}: {e}")
                
        except Exception as e:
            logger.error(f"Error checking plan expiration for service {service.get('id')}: {e}")
    
    async def check_expired_service_overage(self, service: Dict, usage_percentage: float, used_gb: float, total_gb: float):
        """Check if expired service has exceeded limits (110% or 1GB overage) during grace period"""
        try:
            service_id = service.get('id')
            expired_at = service.get('expired_at')
            
            # Only check services in grace period (expired within last 24 hours)
            if not expired_at:
                return
            
            from datetime import datetime
            if isinstance(expired_at, str):
                expired_time = datetime.fromisoformat(expired_at.replace('Z', '+00:00'))
            else:
                expired_time = expired_at
            
            now = datetime.now()
            if expired_time.tzinfo:
                now = now.replace(tzinfo=expired_time.tzinfo)
            
            # Check if still in grace period (less than 24 hours)
            time_diff = now - expired_time
            if time_diff.total_seconds() > 24 * 3600:
                return  # Grace period passed, will be handled by check_for_deletion
            
            # Check for overage: 110% or 1GB over
            total_gb_bytes = total_gb * (1024 * 1024 * 1024) if total_gb > 0 else 0
            used_gb_bytes = used_gb * (1024 * 1024 * 1024) if used_gb > 0 else 0
            overage_bytes = used_gb_bytes - total_gb_bytes if used_gb_bytes > total_gb_bytes else 0
            overage_gb = overage_bytes / (1024 * 1024 * 1024)
            
            # Check if exceeded limits
            if usage_percentage >= 110 or overage_gb >= 1.0:
                logger.warning(f"🚫 Expired service {service_id} exceeded limits during grace period ({usage_percentage:.2f}% or {overage_gb:.2f}GB over) - deleting immediately")
                await self.delete_service_for_overage(service, usage_percentage, overage_gb)
                
        except Exception as e:
            logger.error(f"Error checking expired service overage for service {service.get('id')}: {e}")
    
    async def handle_plan_expiration(self, service: Dict):
        """Handle plan service expiration - disable service and set grace period"""
        try:
            service_id = service.get('id')
            
            # Disable service on panel
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if panel_manager and panel_manager.login():
                success = panel_manager.disable_client(service['inbound_id'], service['client_uuid'])
                if success:
                    # Update database - set status to disabled but keep is_active=True during grace period
                    self.db.update_service_status(service_id, 'disabled')
                    self.db.update_service_expiration_time(service_id)
                    # Note: We do NOT set is_active=False here - service remains visible during 24h grace period
                    # is_active will be set to False only when service is actually deleted after 24 hours
                    
                    # Send notification
                    await self.send_plan_expiration_notification(service)
                else:
                    logger.error(f"Failed to disable expired plan service {service_id} on panel")
            else:
                logger.error(f"Could not connect to panel to disable expired plan service {service_id}")
            
        except Exception as e:
            logger.error(f"Error handling plan expiration for service {service['id']}: {e}")
    
    async def send_three_days_expiration_warning(self, service: Dict, remaining_days: int):
        """Send 3 days expiration warning for plan services"""
        try:
            user = self.db.get_user_by_id(service['user_id'])
            if not user:
                return
            
            expires_at = service.get('expires_at')
            exp_date_str = "نامشخص"
            if expires_at:
                try:
                    from datetime import datetime
                    if isinstance(expires_at, str):
                        exp_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    else:
                        exp_date = expires_at
                    exp_date_str = exp_date.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            message = f"""⚠️ **هشدار انقضای سرویس**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}
📅 **تاریخ انقضا:** {exp_date_str}
⏰ **زمان باقی‌مانده:** {remaining_days} روز

⚠️ **توجه:** زمان سرویس پلنی شما تا {remaining_days} روز دیگر به پایان می‌رسد.

برای تمدید سرویس و جلوگیری از قطع شدن، روی دکمه تمدید کلیک کنید."""
            
            # Create inline keyboard with renew button and main menu button
            keyboard = [
                [
                    InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_service_{service['id']}"),
                ],
                [
                    InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Use rate-limited message sending to avoid flood control
            await self._send_message_safe(
                user['telegram_id'],
                message,
                reply_markup
            )
            
            # Report to channel
            try:
                # CRITICAL: Use bot_instance.reporting_system (VPNBot) instead of bot.reporting_system (Telegram Bot)
                reporting_system = None
                if self.bot_instance and hasattr(self.bot_instance, 'reporting_system'):
                    reporting_system = self.bot_instance.reporting_system
                elif hasattr(self.bot, 'reporting_system'):
                    reporting_system = self.bot.reporting_system
                
                if reporting_system:
                    service_data = {
                        'service_name': service.get('client_name', 'سرویس'),
                        'expires_at': exp_date_str,
                        'remaining_days': remaining_days,
                        'panel_name': service.get('panel_name', 'نامشخص')
                    }
                    await reporting_system.report_service_expiring_soon(user, service_data)
            except Exception as e:
                logger.error(f"Failed to send 3-day warning report to channel: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error sending 3-day expiration warning: {e}")
    
    async def send_plan_expiration_notification(self, service: Dict):
        """Send plan expiration notification with grace period warning"""
        try:
            user = self.db.get_user_by_id(service['user_id'])
            if not user:
                return
            
            # Check if already warned - FORCE CHECK FROM DB to prevent race conditions
            flags = self.db.get_service_warning_flags(service['id'])
            if flags.get('warned_expired'):
                logger.info(f"⚠️ Service {service['id']} already warned about expiration (DB check), skipping notification")
                return
            
            expires_at = service.get('expires_at')
            exp_date_str = "نامشخص"
            if expires_at:
                try:
                    from datetime import datetime
                    if isinstance(expires_at, str):
                        exp_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    else:
                        exp_date = expires_at
                    exp_date_str = exp_date.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            message = f"""⏰ **زمان سرویس تمام شد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}
📅 **تاریخ انقضا:** {exp_date_str}
📊 **وضعیت:** غیرفعال شده

⚠️ **توجه:** زمان سرویس پلنی شما به پایان رسیده و سرویس غیرفعال شده است.

⏰ **مهلت:** شما ۲۴ ساعت فرصت دارید تا سرویس خود را تمدید کنید.
اگر تا ۲۴ ساعت تمدید نکنید، سرویس حذف خواهد شد.

⚠️ **هشدار:** اگر در این مدت بیش از ۱۱۰ درصد حجم یا ۱ گیگابایت بیشتر مصرف کنید، سرویس فوراً حذف خواهد شد.

برای تمدید سرویس، روی دکمه تمدید کلیک کنید."""
            
            # Create inline keyboard with renew button and main menu button
            keyboard = [
                [
                    InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_service_{service['id']}"),
                ],
                [
                    InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Use rate-limited message sending to avoid flood control
            await self._send_message_safe(
                user['telegram_id'],
                message,
                reply_markup
            )
            
            # Update warning status
            self.db.update_service_expired_warning(service['id'], True)
            
            # Report to channel
            try:
                # CRITICAL: Use bot_instance.reporting_system (VPNBot) instead of bot.reporting_system (Telegram Bot)
                reporting_system = None
                if self.bot_instance and hasattr(self.bot_instance, 'reporting_system'):
                    reporting_system = self.bot_instance.reporting_system
                elif hasattr(self.bot, 'reporting_system'):
                    reporting_system = self.bot.reporting_system
                
                if reporting_system:
                    service_data = {
                        'service_name': service.get('client_name', 'سرویس'),
                        'expires_at': exp_date_str,
                        'panel_name': service.get('panel_name', 'نامشخص')
                    }
                    await reporting_system.report_service_expired(user, service_data)
            except Exception as e:
                logger.error(f"Failed to send expiration report to channel: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error sending plan expiration notification: {e}")
    
    async def delete_expired_plan_service(self, service: Dict):
        """Delete an expired plan service after 24 hours grace period"""
        try:
            # Delete from panel first
            panel_manager = self.admin_manager.get_panel_manager(service['panel_id'])
            if panel_manager and panel_manager.login():
                success = panel_manager.delete_client(service['inbound_id'], service['client_uuid'])
                if not success:
                    logger.warning(f"Failed to delete expired plan service {service['id']} from panel")
            else:
                logger.warning(f"Could not connect to panel to delete expired plan service {service['id']}")
            
            # Delete from database
            self.db.delete_service(service['id'])
            
            # Send final notification to user
            user = self.db.get_user_by_id(service['user_id'])
            if user:
                message = f"""🗑️ **سرویس حذف شد**

🔗 **سرویس:** {service.get('client_name', 'سرویس')}

⚠️ **توجه:** سرویس پلنی شما به دلیل عدم تمدید بعد از ۲۴ ساعت حذف شده است.

برای خرید سرویس جدید، روی دکمه صفحه اصلی کلیک کنید."""
                
                keyboard = [[InlineKeyboardButton("🏠 صفحه اصلی", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            
            # Report to channel
            if user:
                try:
                    if hasattr(self.bot, 'reporting_system') and self.bot.reporting_system:
                        from datetime import datetime
                        service_data = {
                            'service_name': service.get('client_name', 'سرویس'),
                            'total_gb': service.get('total_gb', 0),
                            'panel_name': service.get('panel_name', 'نامشخص'),
                            'expired_at': service.get('expired_at', 'نامشخص')
                        }
                        await self.bot.reporting_system.report_service_auto_deleted(user, service_data)
                except Exception as e:
                    logger.error(f"Failed to send auto-deletion report to channel: {e}")
            
        except Exception as e:
            logger.error(f"Error deleting expired plan service {service['id']}: {e}")
    