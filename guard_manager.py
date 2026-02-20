"""
Guard Panel Manager
Handles authentication and API communication with Guard (GuardCore) panel
Documentation: Based on OpenAPI specification
"""

import requests
import json
import time
import urllib3
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class GuardPanelManager:
    # Guard (GuardCore) Panel Manager
    def __init__(self):
        self.session = requests.Session()
        self.base_url = ""
        self.username = ""
        self.password = ""  # API Key or Password
        self.auth_token = None
        self.token_expiry = 0
        self.api_prefix = '/api'
        self._services_cache = []
        self._services_cache_time = 0
        self._cache_ttl = 300  # 5 minutes

    def _detect_api_prefix(self):
        """Detect the correct API prefix"""
        prefixes = ['/api', '', '/v1', '/api/v1', '/guard/api', '/backend', '/server', '/core']
        
        for prefix in prefixes:
            try:
                # Construct URL carefully
                if prefix:
                    url = f"{self.base_url}{prefix}/nodes"
                else:
                    url = f"{self.base_url}/nodes"
                
                logger.info(f"🔍 Probing API prefix: '{prefix}' -> {url}")
                # Try with current auth method (API Key or Bearer Token if we had one, but here we are just probing)
                # We use the password as API key for probing if available, or just check 401
                headers = {'Accept': 'application/json'}
                if self.password and not self.username: # API Key mode
                     headers['X-API-Key'] = self.password
                
                response = self.session.get(
                    url, 
                    headers=headers, 
                    verify=False, 
                    timeout=5
                )
                
                # Check status AND content type
                content_type = response.headers.get('Content-Type', '')
                if response.status_code != 404 and 'application/json' in content_type:
                    logger.info(f"✅ Detected API prefix: '{prefix}' (Status: {response.status_code}, Type: {content_type})")
                    self.api_prefix = prefix
                    return
                elif response.status_code == 200:
                    logger.debug(f"⚠️ Probe '{prefix}' returned 200 but content-type is '{content_type}' (likely HTML)")
                elif response.status_code == 401:
                     # 401 means endpoint exists but we are unauthorized - VALID PREFIX
                     logger.info(f"✅ Detected API prefix (via 401): '{prefix}'")
                     self.api_prefix = prefix
                     return
            except Exception as e:
                logger.debug(f"⚠️ Probe failed for {prefix}: {e}")
        
        logger.warning("⚠️ Could not detect API prefix, defaulting to /api")
        self.api_prefix = '/api'

    def login(self):
        """Login to Guard panel using API Key"""
        try:
            # Detect API prefix first
            self._detect_api_prefix()
            
            # API Key is stored in self.password
            api_key = self.password
            if not api_key:
                logger.error("❌ No API Key provided for Guard panel")
                return False
                
            logger.info(f"🔐 Verifying Guard API Key on {self.base_url}...")
            
            try:
                # Verify key by fetching current admin info (more reliable than /nodes)
                # Guard uses X-API-Key header
                headers = {
                    'X-API-Key': api_key, 
                    'Accept': 'application/json'
                }
                
                response = self.session.get(
                    f"{self.base_url}{self.api_prefix}/admins/current",
                    headers=headers,
                    verify=False,
                    timeout=10
                )
                
                if response.status_code == 200:
                    ct = response.headers.get('Content-Type', '')
                    if 'application/json' in ct:
                        admin_data = response.json()
                        admin_username = admin_data.get('username', 'unknown')
                        logger.info(f"✅ Guard API Key verified successfully (Admin: {admin_username})")
                        self.auth_token = api_key
                        # Set header for future requests
                        self.session.headers.update({'X-API-Key': api_key})
                        self.token_expiry = time.time() + 86400 * 30 # Long expiry for API Key
                        return True
                    else:
                        logger.error(f"❌ Guard returned 200 but not JSON: {ct}")
                        return False
                elif response.status_code == 401 or response.status_code == 403:
                    logger.error(f"❌ Guard API Key invalid: {response.status_code}")
                    return False
                else:
                    logger.error(f"❌ Guard API Key verification failed: {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"❌ Error verifying Guard API Key: {e}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in Guard login: {e}")
            return False

    def ensure_logged_in(self) -> bool:
        # Ensure we have a valid session
        if self.auth_token:
            return True
            
        return self.login()

    def get_services(self) -> List[Dict]:
        # Get list of all services from Guard panel
        try:
            if not self.ensure_logged_in():
                return []
            # Check cache
            if self._services_cache and (time.time() - self._services_cache_time) < self._cache_ttl:
                return self._services_cache
            
            response = self.session.get(
                f"{self.base_url}{self.api_prefix}/services",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                # Check content type
                ct = response.headers.get('Content-Type', '')
                if 'application/json' not in ct:
                    logger.error(f"❌ Guard returned 200 OK but content is not JSON: {ct}")
                    return []

                result = response.json()
                logger.debug(f"🔍 Guard services response type: {type(result)}")
                
                # Handle different response formats
                services = []
                if isinstance(result, list):
                    services = result
                elif isinstance(result, dict):
                    # Check if it's wrapped in a data/items key
                    services = result.get('data', result.get('items', result.get('services', [])))
                    if not isinstance(services, list):
                        logger.warning(f"⚠️ Services data is not a list: {type(services)}")
                        services = []
                else:
                    logger.warning(f"⚠️ Unexpected services response format: {type(result)}")
                    return []
                
                # Validate each service item
                valid_services = []
                for s in services:
                    if isinstance(s, dict):
                        valid_services.append(s)
                    else:
                        logger.warning(f"⚠️ Invalid service item type: {type(s)}")
                
                self._services_cache = valid_services
                self._services_cache_time = time.time()
                logger.info(f"✅ Got {len(valid_services)} services from Guard")
                return valid_services
            else:
                logger.error(f"❌ Failed to get services: {response.status_code}")
                try:
                    logger.error(f"   Response: {response.text[:200]}")
                except:
                    pass
                return []
        except Exception as e:
            logger.error(f"❌ Error getting services: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_inbounds(self) -> List[Dict]:
        # Get inbounds (services) from Guard panel.
        # In Guard, Services are equivalent to Inbounds in other panels.
        # We map services to the expected inbound format for compatibility.
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login to Guard panel")
                return []
            
            logger.info("🔍 Getting inbounds (services) from Guard...")
            
            services = self.get_services()
            
            if not services:
                # Return a default service if none found
                logger.warning("⚠️ No services found, creating default inbound")
                return [{
                    'id': 1,
                    'tag': 'DEFAULT_SERVICE',
                    'protocol': 'vless',
                    'remark': 'Default Guard Service',
                    'port': 443,
                    'enable': True,
                    'settings': {}
                }]
            
            # Parse services as inbounds
            parsed_inbounds = []
            for service in services:
                # Validate service is a dictionary
                if not isinstance(service, dict):
                    logger.warning(f"⚠️ Skipping invalid service item: {type(service)}")
                    continue
                    
                parsed_inbound = {
                    'id': service.get('id', 0),
                    'tag': service.get('remark', f"service-{service.get('id')}"),
                    'protocol': 'vless',  # Guard doesn't specify protocol per service
                    'remark': service.get('remark', f"Service {service.get('id')}"),
                    'port': 443,  # Default port
                    'enable': True,
                    'settings': {},
                    'node_ids': service.get('node_ids', []),
                    'users_count': service.get('users_count', 0)
                }
                parsed_inbounds.append(parsed_inbound)
                logger.info(f"✅ Parsed Guard service: {parsed_inbound['remark']} (ID: {parsed_inbound['id']})")
            
            return parsed_inbounds
                    
        except Exception as e:
            logger.error(f"❌ Error getting Guard inbounds: {e}")
            import traceback
            traceback.print_exc()
            return [{
                'id': 1,
                'tag': 'DEFAULT_SERVICE',
                'protocol': 'vless',
                'remark': 'Default Guard Service',
                'port': 443,
                'enable': True,
                'settings': {}
            }]
    
    def get_nodes(self) -> List[Dict]:
        # Get list of all nodes from Guard panel
        try:
            if not self.ensure_logged_in():
                return []
            
            response = self.session.get(
                f"{self.base_url}{self.api_prefix}/nodes",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                nodes = []
                
                # Handle various response formats
                if isinstance(result, list):
                    nodes = result
                elif isinstance(result, dict):
                    nodes = result.get('data', result.get('items', result.get('nodes', [])))
                
                if isinstance(nodes, list):
                    logger.info(f"✅ Got {len(nodes)} nodes from Guard")
                    return nodes
                    
            return []
        except Exception as e:
            logger.error(f"❌ Error getting nodes: {e}")
            return []
    
    def create_client(self, inbound_id: int, client_name: str, 
                     protocol: str = 'vless', expire_days: int = 0, 
                     total_gb: int = 0, sub_id: str = None) -> Optional[Dict]:
        # Create a new subscription on Guard panel
        # 
        # Args:
        #     inbound_id: Service ID to associate with
        #     client_name: Username for the subscription
        #     protocol: Protocol (not used in Guard, kept for compatibility)
        #     expire_days: Days until expiry (0 for unlimited)
        #     total_gb: Total GB limit (0 for unlimited)
        #     sub_id: Subscription ID (not used in Guard)
        #     
        # Returns:
        #     Dictionary with client info if successful, None otherwise
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login to Guard panel")
                return None
            
            logger.info(f"🔍 Creating Guard subscription: {client_name}")
            logger.info(f"   Expire Days: {expire_days if expire_days > 0 else 'Unlimited'}")
            logger.info(f"   Total GB: {total_gb if total_gb > 0 else 'Unlimited'}")
            
            # Sanitize username for Guard (lowercase, alphanumeric only, 3-30 chars)
            import re
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', client_name)
            clean_name = clean_name.lower()
            if len(clean_name) < 3:
                clean_name = clean_name + 'usr'  # Ensure minimum length
            clean_name = clean_name[:30]  # Max 30 chars
            
            if clean_name != client_name:
                logger.info(f"   Sanitized username: {client_name} -> {clean_name}")
                client_name = clean_name
            
            # Get services to find valid service IDs
            services = self.get_services()
            service_ids = []
            
            if inbound_id and inbound_id > 0:
                # Check if the provided inbound_id is a valid service
                valid_service = any(s.get('id') == inbound_id for s in services)
                if valid_service:
                    service_ids = [inbound_id]
                else:
                    # Use first available service
                    if services:
                        service_ids = [services[0]['id']]
            else:
                # Use first available service
                if services:
                    service_ids = [services[0]['id']]
            
            if not service_ids:
                logger.warning("⚠️ No valid services found. Using fallback service ID [1] as requested.")
                service_ids = [1]
            
            # Calculate data limit in bytes
            data_limit = 0
            if total_gb > 0:
                data_limit = total_gb * 1024 * 1024 * 1024  # GB to bytes
            
            # Calculate expiry in seconds from now
            expire_seconds = 0
            if expire_days > 0:
                expire_seconds = expire_days * 24 * 60 * 60
            
            # Prepare subscription data (Guard accepts array)
            subscription_data = [{
                "username": client_name,
                "limit_usage": data_limit,
                "limit_expire": expire_seconds,
                "service_ids": service_ids
            }]
            
            logger.info(f"🔍 Creating subscription with data: {json.dumps(subscription_data, indent=2)}")
            
            response = self.session.post(
                f"{self.base_url}{self.api_prefix}/subscriptions",
                json=subscription_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                
                # Guard returns an array of created subscriptions
                if isinstance(result, list) and len(result) > 0:
                    sub_data = result[0]
                else:
                    sub_data = result
                
                logger.info(f"✅ Successfully created Guard subscription!")
                
                # Extract subscription link
                subscription_link = sub_data.get('link', '')
                access_key = sub_data.get('access_key', '')
                
                # If link is relative, add base URL
                if subscription_link and subscription_link.startswith('/'):
                    subscription_link = f"{self.base_url}{subscription_link}"
                
                # Construct link if not provided
                if not subscription_link and access_key:
                    subscription_link = f"{self.base_url}/guards/{access_key}"
                
                # Calculate expiry timestamp
                expire_timestamp = 0
                if expire_days > 0:
                    expire_timestamp = int(time.time()) + (expire_days * 86400)
                
                # Return client info in standard format
                client = {
                    'id': sub_data.get('id', client_name),
                    'name': client_name,
                    'email': f"{client_name}@guard",
                    'protocol': protocol,
                    'inbound_id': inbound_id or (service_ids[0] if service_ids else 0),
                    'expire_days': expire_days,
                    'total_gb': total_gb,
                    'expire_time': expire_timestamp,
                    'total_traffic': data_limit,
                    'status': 'active',
                    'uuid': client_name,  # Store username as UUID for compatibility
                    'sub_id': access_key,
                    'subscription_url': subscription_link,
                    'access_key': access_key,
                    'created_at': int(time.time())
                }
                
                logger.info(f"✅ Created Guard subscription: {client_name}")
                logger.info(f"   Subscription Link: {subscription_link}")
                
                return client
            else:
                error_msg = response.text
                logger.error(f"❌ Failed to create Guard subscription: {response.status_code}")
                logger.error(f"   Error: {error_msg}")
                return {'error': error_msg}
                    
        except Exception as e:
            logger.error(f"❌ Error creating Guard subscription: {e}")
            import traceback
            traceback.print_exc()
            return {'error': str(e)}
    
    def get_client_details(self, inbound_id: int, client_uuid: str,
                          update_inbound_callback=None, service_id=None, client_name=None) -> Optional[Dict]:
        # Get specific subscription details from Guard panel
        # 
        # Args:
        #     inbound_id: Not used in Guard, kept for compatibility
        #     client_uuid: Username of the subscription
        #     update_inbound_callback: Optional callback (not used)
        #     service_id: Optional service ID (not used)
        #     client_name: Optional client name for fallback
        #     
        # Returns:
        #     Dictionary with client details if found, None otherwise
        try:
            if not self.ensure_logged_in():
                return None
            
            # In Guard, client_uuid should be the username
            username = client_uuid
            if client_name and client_name != client_uuid:
                username = client_name
            
            # Sanitize username to lowercase (Guard requirement)
            username = username.lower()
            
            response = self.session.get(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                sub_data = response.json()
                
                # Parse subscription data
                limit_usage = sub_data.get('limit_usage', 0)
                current_usage = sub_data.get('current_usage', 0)
                total_usage = sub_data.get('total_usage', 0)
                reset_usage = sub_data.get('reset_usage', 0)
                
                # Get online status
                is_online = sub_data.get('is_online', False)
                online_at = sub_data.get('online_at')
                
                # Parse online_at timestamp
                last_activity_timestamp = 0
                if online_at:
                    try:
                        if 'Z' in online_at or '+' in online_at:
                            dt = datetime.fromisoformat(online_at.replace('Z', '+00:00'))
                        else:
                            from datetime import timezone
                            dt = datetime.fromisoformat(online_at).replace(tzinfo=timezone.utc)
                        last_activity_timestamp = int(dt.timestamp() * 1000)
                    except Exception as e:
                        logger.warning(f"⚠️ Could not parse online_at '{online_at}': {e}")
                
                # Get expiry info
                limit_expire = sub_data.get('limit_expire', 0)
                created_at = sub_data.get('created_at', '')
                
                # Calculate expiry timestamp
                expiry_time = 0
                if limit_expire > 0 and created_at:
                    try:
                        if 'Z' in created_at or '+' in created_at:
                            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        else:
                            created_dt = datetime.fromisoformat(created_at)
                        expiry_time = int(created_dt.timestamp()) + limit_expire
                    except:
                        pass
                
                client_details = {
                    'id': sub_data.get('id', username),
                    'email': f"{username}@guard",
                    'enable': sub_data.get('enabled', True) and sub_data.get('is_active', True),
                    'total_traffic': limit_usage,
                    'used_traffic': current_usage,
                    'expiryTime': expiry_time * 1000 if expiry_time else 0,  # Convert to ms
                    'created_at': sub_data.get('created_at', ''),
                    'updated_at': sub_data.get('updated_at', ''),
                    'last_activity': last_activity_timestamp,
                    'is_online': is_online,
                    'access_key': sub_data.get('access_key', ''),
                    'link': sub_data.get('link', ''),
                    'service_ids': sub_data.get('service_ids', []),
                    'status': 'active' if sub_data.get('is_active', True) else 'disabled'
                }
                
                logger.info(f"✅ Got Guard subscription details for: {username}")
                return client_details
                
            elif response.status_code == 404:
                logger.warning(f"⚠️ Subscription not found: {username}")
                return None
            else:
                logger.error(f"❌ Failed to get subscription: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting Guard subscription details: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_client_config_link(self, inbound_id: int, client_id: str, 
                              protocol: str = None) -> Optional[str]:
        # Get configuration/subscription link for Guard subscription
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_id: Username of the subscription
        #     protocol: Not used in Guard
        #     
        # Returns:
        #     Subscription link if found, None otherwise
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login for config generation")
                return None
            
            username = client_id
            
            response = self.session.get(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                sub_data = response.json()
                
                # Get the link from response
                subscription_link = sub_data.get('link', '')
                access_key = sub_data.get('access_key', '')
                
                # Fix relative paths
                if subscription_link and subscription_link.startswith('/'):
                    subscription_link = f"{self.base_url}{subscription_link}"
                
                # Construct link if not provided
                if not subscription_link and access_key:
                    subscription_link = f"{self.base_url}/guards/{access_key}"
                
                if subscription_link:
                    logger.info(f"✅ Got Guard subscription link: {subscription_link}")
                    return subscription_link
                
                # Last resort: construct manually
                subscription_link = f"{self.base_url}/guards/{username}"
                logger.warning(f"⚠️ Constructed manual subscription link: {subscription_link}")
                return subscription_link
            else:
                logger.error(f"❌ Failed to get subscription details: {response.status_code}")
                return None
                        
        except Exception as e:
            logger.error(f"❌ Error getting Guard subscription link: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_subscription_link(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[str]:
        # Alias for get_client_config_link - for compatibility
        return self.get_client_config_link(inbound_id, client_uuid)
    
    def update_client_traffic(self, inbound_id: int, client_uuid: str, new_total_gb: int, client_name: str = None) -> bool:
        # Update subscription traffic limit (for volume increase/renewal)
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     new_total_gb: New total GB limit
        #     client_name: Optional client name
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login to Guard panel")
                return False
            
            username = client_uuid
            
            # Calculate new data limit in bytes
            new_data_limit = new_total_gb * 1024 * 1024 * 1024
            
            update_data = {
                "limit_usage": new_data_limit
            }
            
            logger.info(f"🔍 Updating Guard subscription traffic: {username} -> {new_total_gb}GB")
            
            response = self.session.put(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully updated Guard subscription traffic to {new_total_gb}GB")
                return True
            else:
                logger.error(f"❌ Failed to update subscription: {response.status_code}")
                try:
                    logger.error(f"   Response: {response.text}")
                except:
                    pass
                return False
            
        except Exception as e:
            logger.error(f"❌ Error updating Guard subscription traffic: {e}")
            return False
    
    def update_client_expiration(self, inbound_id: int, client_uuid: str, expiry_timestamp: int, client_name: str = None) -> bool:
        """
        Update client expiration (for renewal) in Guard
        
        Args:
            inbound_id: Not used
            client_uuid: Username
            expiry_timestamp: New expiration timestamp (Unix timestamp in seconds)
            client_name: Optional client name
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login to Guard panel")
                return False
            
            username = client_uuid
            
            # Guard uses duration in seconds for limit_expire
            # We need to calculate remaining seconds from now to expiry_timestamp
            
            if not expiry_timestamp or expiry_timestamp <= 0:
                new_expire_seconds = 0 # 0 means unlimited
            else:
                import time
                now = int(time.time())
                new_expire_seconds = max(0, expiry_timestamp - now)
            
            update_data = {
                "limit_expire": new_expire_seconds
            }
            
            logger.info(f"🔍 Updating Guard subscription expiry: {username} -> {new_expire_seconds} seconds remaining")
            
            response = self.session.put(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully updated Guard subscription expiry")
                return True
            else:
                logger.error(f"❌ Failed to update Guard subscription: {response.status_code}")
                try:
                    logger.error(f"   Response: {response.text}")
                except:
                    pass
                return False
                
        except Exception as e:
            logger.error(f"❌ Error updating Guard subscription expiry: {e}")
            return False

    def update_client_expire(self, inbound_id: int, client_uuid: str, new_expire_days: int) -> bool:
        # Update subscription expiry time
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     new_expire_days: New expiry in days from creation
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login to Guard panel")
                return False
            
            username = client_uuid
            
            # Calculate new expiry in seconds
            new_expire_seconds = new_expire_days * 24 * 60 * 60
            
            update_data = {
                "limit_expire": new_expire_seconds
            }
            
            logger.info(f"🔍 Updating Guard subscription expiry: {username} -> {new_expire_days} days")
            
            response = self.session.put(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully updated Guard subscription expiry to {new_expire_days} days")
                return True
            else:
                logger.error(f"❌ Failed to update subscription: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error updating Guard subscription expiry: {e}")
            return False
    
    def extend_client_expire(self, inbound_id: int, client_uuid: str, additional_days: int, client_name: str = None) -> bool:
        # Extend subscription expiry by additional days
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     additional_days: Days to add to current expiry
        #     client_name: Optional client name for fallback
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid if not client_name else client_name
            
            # First get current subscription details
            response = self.session.get(
                f"{self.base_url}/api/subscriptions/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Failed to get subscription for extension: {response.status_code}")
                return False
            
            sub_data = response.json()
            current_expire = sub_data.get('limit_expire', 0)
            
            # Add additional days in seconds
            additional_seconds = additional_days * 24 * 60 * 60
            new_expire = current_expire + additional_seconds
            
            update_data = {
                "limit_expire": new_expire
            }
            
            logger.info(f"🔍 Extending Guard subscription: {username} by {additional_days} days")
            
            response = self.session.put(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully extended Guard subscription by {additional_days} days")
                return True
            else:
                logger.error(f"❌ Failed to extend subscription: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error extending Guard subscription: {e}")
            return False
    
    def update_client_expiration(self, inbound_id: int, client_uuid: str, expiration_timestamp: int, client_name: str = None) -> bool:
        # Update subscription with absolute expiration timestamp
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     expiration_timestamp: Unix timestamp for expiry
        #     client_name: Optional client name
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid if not client_name else client_name
            
            # First get subscription to find creation time
            response = self.session.get(
                f"{self.base_url}{self.api_prefix}/subscriptions/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
            
            sub_data = response.json()
            created_at = sub_data.get('created_at', '')
            
            # Calculate limit_expire as seconds from creation to target timestamp
            limit_expire = 0
            if created_at:
                try:
                    if 'Z' in created_at or '+' in created_at:
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    else:
                        created_dt = datetime.fromisoformat(created_at)
                    created_ts = int(created_dt.timestamp())
                    limit_expire = expiration_timestamp - created_ts
                    if limit_expire < 0:
                        limit_expire = 0
                except:
                    # Fallback: calculate from now
                    limit_expire = expiration_timestamp - int(time.time())
                    if limit_expire < 0:
                        limit_expire = 0
            else:
                limit_expire = expiration_timestamp - int(time.time())
                if limit_expire < 0:
                    limit_expire = 0
            
            update_data = {
                "limit_expire": limit_expire
            }
            
            response = self.session.put(
                f"{self.base_url}/api/subscriptions/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully updated Guard subscription expiration")
                return True
            else:
                logger.error(f"❌ Failed to update subscription expiration: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error updating Guard subscription expiration: {e}")
            return False
    
    def disable_client(self, inbound_id: int, client_uuid: str, client_name: str = None) -> bool:
        # Disable subscription on Guard panel
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     client_name: Optional client name
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid if not client_name else client_name
            
            # Guard uses bulk disable endpoint
            disable_data = {
                "usernames": [username]
            }
            
            response = self.session.post(
                f"{self.base_url}/api/subscriptions/disable",
                json=disable_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully disabled Guard subscription: {username}")
                return True
            else:
                logger.error(f"❌ Failed to disable subscription: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error disabling Guard subscription: {e}")
            return False
    
    def enable_client(self, inbound_id: int, client_uuid: str, client_name: str = None) -> bool:
        # Enable subscription on Guard panel
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     client_name: Optional client name
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid if not client_name else client_name
            
            # Guard uses bulk enable endpoint
            enable_data = {
                "usernames": [username]
            }
            
            response = self.session.post(
                f"{self.base_url}/api/subscriptions/enable",
                json=enable_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully enabled Guard subscription: {username}")
                return True
            else:
                logger.error(f"❌ Failed to enable subscription: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error enabling Guard subscription: {e}")
            return False
    
    def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        # Delete subscription from Guard panel
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid
            
            # Guard uses bulk delete endpoint with body
            delete_data = {
                "usernames": [username]
            }
            
            response = self.session.delete(
                f"{self.base_url}/api/subscriptions",
                json=delete_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in [200, 204]:
                logger.info(f"✅ Successfully deleted Guard subscription: {username}")
                return True
            else:
                logger.error(f"❌ Failed to delete subscription: {response.status_code}")
                return False
            
            
            # Guard uses bulk revoke endpoint
            revoke_data = {
                "usernames": [username]
            }
            
            response = self.session.post(
                f"{self.base_url}/api/subscriptions/revoke",
                json=revoke_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Get updated subscription info
                if isinstance(result, list) and len(result) > 0:
                    sub_data = result[0]
                else:
                    # Fetch fresh subscription data
                    details = self.get_client_details(inbound_id, username)
                    if details:
                        sub_data = details
                    else:
                        sub_data = result
                
                # Get new subscription link
                new_link = sub_data.get('link', '')
                new_access_key = sub_data.get('access_key', '')
                
                if new_link and new_link.startswith('/'):
                    new_link = f"{self.base_url}{new_link}"
                
                if not new_link and new_access_key:
                    new_link = f"{self.base_url}/guards/{new_access_key}"
                
                new_client = {
                    'id': sub_data.get('id', username),
                    'uuid': username,
                    'name': username,
                    'subscription_url': new_link,
                    'access_key': new_access_key,
                    'link': new_link
                }
                
                logger.info(f"✅ Successfully reset Guard subscription link: {username}")
                logger.info(f"   New link: {new_link}")
                
                return new_client
            else:
                logger.error(f"❌ Failed to revoke subscription: {response.status_code}")
                return None
            
        except Exception as e:
            logger.error(f"❌ Error resetting Guard subscription: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def reset_client_traffic(self, inbound_id: int, client_uuid: str) -> bool:
        # Reset subscription traffic usage
        # 
        # Args:
        #     inbound_id: Not used in Guard
        #     client_uuid: Username of the subscription
        #     
        # Returns:
        #     True if successful, False otherwise
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid
            
            # Guard uses bulk reset endpoint
            reset_data = {
                "usernames": [username]
            }
            
            response = self.session.post(
                f"{self.base_url}/api/subscriptions/reset",
                json=reset_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully reset Guard subscription traffic: {username}")
                return True
            else:
                logger.error(f"❌ Failed to reset subscription traffic: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error resetting Guard subscription traffic: {e}")
            return False
    
    def reset_client_uuid(self, inbound_id: int, client_uuid: str, client_name: str = None) -> dict:
        """Reset/regenerate subscription access key (UUID)
        
        Args:
            inbound_id: Not used in Guard
            client_uuid: Username of the subscription
            client_name: Optional client name for fallback
            
        Returns:
            Dictionary with new client info if successful, None otherwise
        """
        try:
            if not self.ensure_logged_in():
                return None
            
            # Use client_name if provided, otherwise use client_uuid
            username = client_name if client_name else client_uuid
            # Sanitize username to lowercase (Guard requirement)
            username = username.lower()
            
            logger.info(f"🔄 Revoking Guard subscription key for: {username}")
            
            # Guard uses bulk revoke endpoint
            revoke_data = {
                "usernames": [username]
            }
            
            response = self.session.post(
                f"{self.base_url}{self.api_prefix}/subscriptions/revoke",
                json=revoke_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Guard returns array of updated subscriptions
                if isinstance(result, list) and len(result) > 0:
                    sub_data = result[0]
                else:
                    sub_data = result
                
                new_access_key = sub_data.get('access_key', '')
                new_link = sub_data.get('link', '')
                
                # Construct link if not provided
                if not new_link and new_access_key:
                    new_link = f"{self.base_url}/guards/{new_access_key}"
                
                logger.info(f"✅ Successfully revoked Guard subscription key: {username}")
                logger.info(f"   New access key: {new_access_key}")
                
                return {
                    'uuid': new_access_key,
                    'sub_id': new_access_key,
                    'access_key': new_access_key,
                    'subscription_url': new_link,
                    'link': new_link,
                    'name': username
                }
            else:
                logger.error(f"❌ Failed to revoke subscription key: {response.status_code}")
                try:
                    logger.error(f"   Response: {response.text[:200]}")
                except:
                    pass
                return None
            
        except Exception as e:
            logger.error(f"❌ Error revoking Guard subscription key: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def test_connection(self) -> Dict:
        # Test connection to Guard panel
        start_time = time.time()
        try:
            # First try the base endpoint
            response = self.session.get(
                f"{self.base_url}/",
                verify=False,
                timeout=10
            )
            
            latency = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                # Try to login to verify credentials
                if self.login():
                    logger.info("✅ Guard panel connection and authentication successful")
                    return {
                        'success': True,
                        'latency': int(latency),
                        'message': '✅ اتصال برقرار است'
                    }
                else:
                    logger.warning("⚠️ Guard panel reachable but authentication failed")
                    return {
                        'success': False,
                        'latency': int(latency),
                        'message': '❌ خطا در احراز هویت (نام کاربری/رمز عبور اشتباه است)'
                    }
            else:
                logger.error(f"❌ Guard panel not reachable: {response.status_code}")
                return {
                    'success': False,
                    'latency': int(latency),
                    'message': f'❌ خطا در اتصال: {response.status_code}'
                }
                
        except requests.exceptions.ConnectionError:
            latency = (time.time() - start_time) * 1000
            logger.error(f"❌ Cannot connect to Guard panel at {self.base_url}")
            return {
                'success': False,
                'latency': int(latency),
                'message': '❌ خطا در برقراری ارتباط با سرور'
            }
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"❌ Error testing Guard panel connection: {e}")
            return {
                'success': False,
                'latency': int(latency),
                'message': f'❌ خطا در تست اتصال: {str(e)}'
            }

    def get_system_stats(self) -> Optional[Dict]:
        # Get system statistics from Guard panel
        try:
            if not self.ensure_logged_in():
                return None
            
            response = self.session.get(
                f"{self.base_url}{self.api_prefix}/stats/subscriptions",
                verify=False,
                timeout=30
            )
            
            stats = {}
            
            if response.status_code == 200:
                sub_stats = response.json()
                stats['total_users'] = sub_stats.get('total', 0)
                stats['active_users'] = sub_stats.get('active', 0)
                stats['inactive_users'] = sub_stats.get('inactive', 0)
                stats['disabled_users'] = sub_stats.get('disabled', 0)
                stats['expired_users'] = sub_stats.get('expired', 0)
                stats['limited_users'] = sub_stats.get('limited', 0)
                stats['total_usage'] = sub_stats.get('total_usage', 0)
            
            # Get status stats if available
            try:
                status_response = self.session.get(
                    f"{self.base_url}{self.api_prefix}/stats/subscriptions/status",
                    verify=False,
                    timeout=30
                )
                
                if status_response.status_code == 200:
                    status_stats = status_response.json()
                    stats['online_users'] = status_stats.get('online', 0)
                    stats['offline_users'] = status_stats.get('offline', 0)
            except:
                pass
            
            # Get node stats
            try:
                nodes_response = self.session.get(
                    f"{self.base_url}{self.api_prefix}/nodes/stats",
                    verify=False,
                    timeout=30
                )
                
                if nodes_response.status_code == 200:
                    node_stats = nodes_response.json()
                    stats['total_nodes'] = node_stats.get('total_nodes', 0)
                    stats['active_nodes'] = node_stats.get('active_nodes', 0)
            except:
                pass
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Error getting Guard system stats: {e}")
            return None
    
    def get_inbound_tags(self) -> Dict[str, List[str]]:
        # Get inbound tags from Guard
        # Returns a dictionary mapping protocol to list of inbound tags
        try:
            services = self.get_services()
            inbound_tags = {'vless': []}
            
            for service in services:
                if not isinstance(service, dict):
                    continue
                    
                # Use remark or ID as tag
                tag = service.get('remark', f"service-{service.get('id')}")
                if tag:
                    inbound_tags['vless'].append(str(tag))
            
            return inbound_tags
        except Exception as e:
            logger.error(f"❌ Error getting inbound tags: {e}")
            return {}

    def get_users(self) -> List[Dict]:
        # Get all subscriptions for sync/migration
        try:
            if not self.ensure_logged_in():
                return []
            
            # Use get_all_subscriptions logic here if needed, or return empty for now
            # since get_all_subscriptions was removed or not implemented fully
            return []
            
        except Exception as e:
            logger.error(f"❌ Error getting all Guard clients: {e}")
            return []

    def get_client_config(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[str]:
        # Alias for get_client_config_link - for compatibility
        return self.get_client_config_link(inbound_id, client_uuid, client_name)
