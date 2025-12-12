"""
Rebecca Panel Manager
Handles authentication and API communication with Rebecca panel
Inherits from MarzbanPanelManager as Rebecca is a fork of Marzban
"""

import logging
from typing import Dict, List, Optional
from marzban_manager import MarzbanPanelManager

logger = logging.getLogger(__name__)

class RebeccaPanelManager(MarzbanPanelManager):
    """
    Rebecca Panel Manager
    
    Since Rebecca is a fork of Marzban, we inherit most functionality.
    We can override specific methods if the API differs.
    """
    
    def __init__(self):
        super().__init__()
        # Cache for user lists to improve performance
        self._users_cache = None
        self._cache_timestamp = 0
        self._cache_ttl = 300  # Cache TTL in seconds (5 minutes for better performance)
        self.subscription_url = None

    def _fetch_users_cached(self) -> List[Dict]:
        """
        Fetch users list from Rebecca with aggressive caching
        This method is shared by get_client_details and get_client_config_link
        to minimize API calls and improve performance
        """
        import time
        current_time = time.time()
        
        # Check if we have a valid cache
        if self._users_cache and (current_time - self._cache_timestamp) < self._cache_ttl:
            logger.info(f"✅ Using cached users list ({len(self._users_cache)} users, age: {int(current_time - self._cache_timestamp)}s)")
            return self._users_cache
        
        # Cache miss or expired - fetch from API
        try:
            response = self.session.get(
                f"{self.base_url}/api/users",
                verify=False,
                timeout=60
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Failed to get users list: {response.status_code}")
                # Return stale cache if available rather than nothing
                return self._users_cache if self._users_cache else []
            
            data = response.json()
            users_list = data.get('users', []) if isinstance(data, dict) else data
            
            if not users_list:
                logger.warning(f"⚠️ No users found in Rebecca panel")
                return []
            
            # Update cache
            self._users_cache = users_list
            self._cache_timestamp = current_time
            logger.info(f"🔄 Fetched and cached {len(users_list)} users from Rebecca")
            return users_list
            
        except Exception as e:
            logger.error(f"❌ Error fetching users from Rebecca: {e}")
            # Return stale cache if available
            return self._users_cache if self._users_cache else []
    
    def get_all_clients(self) -> List[Dict]:
        """
        Get all clients from the panel with their details
        Used for migration
        """
        try:
            if not self.ensure_logged_in():
                return []
            
            # Get all users
            response = self.session.get(
                f"{self.base_url}/api/users",
                verify=False,
                timeout=60
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get users from Rebecca: {response.status_code}")
                return []
            
            users_data = response.json()
            users_list = users_data.get('users', []) if isinstance(users_data, dict) else users_data
            
            clients = []
            for user in users_list:
                try:
                    # Calculate remaining traffic
                    total_traffic = user.get('data_limit', 0)
                    used_traffic = user.get('used_traffic', 0)
                    
                    # Calculate remaining days
                    expire_timestamp = user.get('expire')
                    expire_days = 0
                    if expire_timestamp:
                        import time
                        now = time.time()
                        if expire_timestamp > now:
                            expire_days = int((expire_timestamp - now) / 86400)
                    
                    # Get protocol info from proxies
                    proxies = user.get('proxies', {})
                    protocol = 'vless' # Default
                    if proxies:
                        protocol = list(proxies.keys())[0]
                    
                    clients.append({
                        'username': user.get('username'),
                        'total_traffic': total_traffic,
                        'used_traffic': used_traffic,
                        'expire_timestamp': expire_timestamp,
                        'expire_days': expire_days,
                        'protocol': protocol,
                        'status': user.get('status', 'active'),
                        'data_limit_reset_strategy': user.get('data_limit_reset_strategy', 'no_reset')
                    })
                except Exception as e:
                    logger.error(f"Error parsing user {user.get('username')}: {e}")
                    continue
            
            return clients
            
        except Exception as e:
            logger.error(f"Error getting all clients from Rebecca: {e}")
            return []

    def login(self) -> bool:
        """
        Authenticate with the Rebecca panel
        Overrides Marzban method to use _get_token which supports both Form and JSON
        """
        try:
            logger.info(f"🔐 Attempting Rebecca login to {self.base_url} with username: {self.username}")
            token = self._get_token()
            if token:
                self.auth_token = token
                # Set authorization header for future requests
                self.session.headers.update({
                    'Authorization': f'Bearer {self.auth_token}',
                    'accept': 'application/json'
                })
                
                # Token typically expires in 1 hour
                import time
                self.token_expiry = time.time() + 3600
                logger.info("✅ Rebecca login successful")
                return True
            logger.error("❌ Rebecca login failed: No token received")
            return False
        except Exception as e:
            logger.error(f"❌ Error logging into Rebecca panel: {e}")
            return False

    def _get_token(self) -> Optional[str]:
        """
        Get authentication token from Rebecca panel
        Overrides Marzban method to add logging
        """
        try:
            # Prepare login data
            data = {
                'username': self.username,
                'password': self.password
            }
            
            logger.info(f"🔐 Attempting login to Rebecca panel at {self.base_url}")
            
            # Send login request (try form data first)
            try:
                response = self.session.post(
                    f"{self.base_url}/api/admin/token",
                    data=data,
                    verify=False,
                    timeout=30
                )
                
                logger.info(f"📥 Rebecca login response (form): {response.status_code}")
                
                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data.get('access_token')
                    if access_token:
                        logger.info("✅ Rebecca login successful (form)")
                        return access_token
                    else:
                        logger.error(f"❌ No access token in response (form): {token_data}")
                else:
                    logger.error(f"❌ Rebecca form login failed: {response.text}")
            except Exception as e:
                logger.warning(f"⚠️ Rebecca form login failed: {e}")

            # Try JSON login if form failed or didn't return a token
            try:
                logger.info("🔄 Attempting Rebecca login with JSON...")
                response = self.session.post(
                    f"{self.base_url}/api/admin/token",
                    json=data,
                    verify=False,
                    timeout=30
                )
                
                logger.info(f"📥 Rebecca login response (JSON): {response.status_code}")
                
                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data.get('access_token')
                    if access_token:
                        logger.info("✅ Rebecca login successful (JSON)")
                        return access_token
                    else:
                        logger.error(f"❌ No access token in response (JSON): {token_data}")
                else:
                    logger.error(f"❌ Rebecca JSON login failed: {response.text}")
            except Exception as e:
                logger.error(f"❌ Rebecca JSON login failed: {e}")
                
            return None
            
        except Exception as e:
            logger.error(f"❌ Error logging into Rebecca panel: {e}")
            return None

    def get_services(self) -> List[Dict]:
        """
        Get all services from the panel
        Tries multiple endpoints to find services/inbounds
        """
        try:
            if not self.ensure_logged_in():
                return []
            
            endpoints = [
                '/api/services',
                '/api/nodes',
                '/api/inbounds',
                '/api/core/config',
                '/api/system'
            ]
            
            for endpoint in endpoints:
                try:
                    logger.info(f"Trying endpoint: {endpoint}")
                    print(f"DEBUG: Trying endpoint {endpoint}")
                    
                    response = self.session.get(
                        f"{self.base_url}{endpoint}",
                        verify=False,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        print(f"DEBUG: Endpoint {endpoint} returned {type(data)}")
                        
                        # Case 1: List of items
                        if isinstance(data, list):
                            logger.info(f"✅ Found list at {endpoint}")
                            return data
                            
                        # Case 2: Dict with specific keys
                        if isinstance(data, dict):
                            print(f"DEBUG: Dict keys: {list(data.keys())}")
                            
                            if 'services' in data:
                                return data['services']
                            if 'inbounds' in data:
                                return data['inbounds']
                            if 'nodes' in data:
                                return data['nodes']
                            if 'hosts' in data:
                                return data['hosts']
                                
                            # If it's a dict but no known key, maybe the values are the list?
                            # (Unlikely for these APIs but possible)
                            
                            logger.warning(f"Unexpected dict keys at {endpoint}: {list(data.keys())}")
                            # Continue to next endpoint if this one didn't have what we wanted
                    else:
                        logger.warning(f"Endpoint {endpoint} returned {response.status_code}")
                        
                except Exception as e:
                    logger.warning(f"Error calling {endpoint}: {e}")
            
            logger.error("❌ All endpoints failed to return services/inbounds")
            return []
                
        except Exception as e:
            logger.error(f"Error getting services from Rebecca: {e}")
            return []

    def get_inbounds(self) -> List[Dict]:
        """
        Override get_inbounds to return Services as Inbounds
        This allows the existing system to treat Rebecca Services as Inbounds
        """
        try:
            services = self.get_services()
            inbounds = []
            
            for service in services:
                # Map Service fields to Inbound fields
                inbounds.append({
                    'id': service.get('id'),
                    'up': 0, # Not available for service
                    'down': 0, # Not available for service
                    'total': 0, # Not available for service
                    'remark': service.get('name', f"Service {service.get('id')}"),
                    'enable': True,
                    'expiryTime': 0,
                    'clientStats': [],
                    'listen': '',
                    'port': 0,
                    'protocol': 'rebecca', # Custom protocol identifier
                    'settings': '{}',
                    'streamSettings': '{}',
                    'tag': service.get('name', f"Service {service.get('id')}"),
                    'sniffing': '{}'
                })
            
            return inbounds
        except Exception as e:
            logger.error(f"Error getting inbounds (services) from Rebecca: {e}")
            return []

    def _join_url(self, base: str, path: str) -> str:
        """Helper to join base URL and path, avoiding duplicate slashes and /sub segments"""
        if not base or not path:
            return base or path
            
        base = base.rstrip('/')
        path = path.lstrip('/')
        
        # Check for duplicate 'sub' segment
        # Case 1: base ends with /sub and path starts with sub/
        if base.endswith('/sub') and path.startswith('sub/'):
            path = path[4:]
        
        return f"{base}/{path}"

    def create_client(self, inbound_id: int, client_name: str, protocol: str = 'vless', expire_days: int = 0, total_gb: int = 0, sub_id: str = None) -> Optional[Dict]:
        """
        Create a new client in the panel
        Overrides Marzban method to ensure correct subscription link generation
        
        Args:
            inbound_id: Service ID (treated as inbound_id)
            client_name: Username for the client
            protocol: Protocol to use (vless, vmess, trojan, shadowsocks). Default: vless
            expire_days: Days until expiration (0 for unlimited)
            total_gb: Total traffic in GB (0 for unlimited)
            sub_id: Subscription ID (not used in Rebecca)
        """
        try:
            if not self.ensure_logged_in():
                return None
            
            # Map arguments to Rebecca expected format
            username = client_name
            
            # Generate UUID
            import uuid
            client_uuid = str(uuid.uuid4())
            
            # Calculate expiry timestamp
            import time
            expiry_timestamp = 0
            if expire_days > 0:
                expiry_timestamp = int(time.time()) + (expire_days * 86400)
                
            # Calculate data limit
            data_limit = 0
            if total_gb > 0:
                data_limit = total_gb * 1024 * 1024 * 1024
            
            # Prepare proxies based on requested protocol
            # Only include the requested protocol to avoid "protocol disabled" errors
            protocol = protocol.lower() if protocol else "vless"
            
            proxies = {}
            if protocol == "vless":
                proxies["vless"] = {
                    "flow": "xtls-rprx-vision",
                    "id": client_uuid
                }
            elif protocol == "vmess":
                proxies["vmess"] = {
                    "id": client_uuid
                }
            elif protocol == "trojan":
                proxies["trojan"] = {
                    "password": client_uuid
                }
            elif protocol == "shadowsocks":
                proxies["shadowsocks"] = {
                    "method": "chacha20-ietf-poly1305",
                    "password": client_uuid
                }
            else:
                # Default to vless if unknown protocol
                logger.warning(f"Unknown protocol '{protocol}', defaulting to vless")
                proxies["vless"] = {
                    "flow": "xtls-rprx-vision",
                    "id": client_uuid
                }
            
            data = {
                "username": username,
                "proxies": proxies,
                "expire": expiry_timestamp,
                "data_limit": data_limit,
                "data_limit_reset_strategy": "no_reset",
                "status": "active",
                "note": "Created by VPN Bot",
                "on_hold_timeout": None,
                "on_hold_expire_duration": None
            }

            # Force Service Selection Logic
            # 1. Fetch available services/nodes to ensure we have a valid ID
            available_services = self.get_services()
            selected_service_id = None
            
            if available_services:
                # DEBUG: Log the first service structure to understand what we are dealing with
                logger.info(f"🔍 DEBUG: First service/node structure: {available_services[0]}")
                
                # Check if the requested inbound_id is valid
                if inbound_id:
                    for s in available_services:
                        if str(s.get('id')) == str(inbound_id):
                            selected_service_id = inbound_id
                            logger.info(f"✅ Verified requested service ID {inbound_id} exists")
                            break
                
                # If not found or not provided, pick the first one (or random)
                if not selected_service_id:
                    if inbound_id:
                        logger.warning(f"⚠️ Requested service ID {inbound_id} not found in available services. Falling back to default.")
                    
                    # Pick the first available service
                    first_service = available_services[0]
                    selected_service_id = first_service.get('id')
                    service_name = first_service.get('name') or first_service.get('tag')
                    logger.info(f"🔄 Forced selection of service: {service_name} (ID: {selected_service_id})")
            else:
                logger.error("❌ No services/nodes found in Rebecca panel! Cannot assign service.")
            
            # Get actual inbound tags and assign ALL of them to the client
            # This ensures the client can connect to all available servers/services
            inbounds_dict = self.get_inbound_tags()
            
            if inbounds_dict:
                # Assign ALL inbounds so user can connect to all servers
                data["inbounds"] = inbounds_dict
                logger.info(f"🔗 Assigning ALL inbounds to client: {inbounds_dict}")
            else:
                logger.warning("⚠️ Could not fetch inbound tags, Rebecca will use defaults")
                
            # 2. Apply the selected service ID to the payload
            # CRITICAL FIX: Rebecca/Marzban forks distinguish between "Services" and "Nodes".
            # If we fetched from /api/nodes, we MUST NOT send "service_id", as the backend will try to look up a Service and fail with 404.
            # We should only send "node_ids" or "nodes".
            
            if selected_service_id:
                # We know available_services came from get_services() which calls /api/nodes (since /api/services failed)
                # So selected_service_id is a NODE ID.
                
                # Do NOT send service_id or services for Nodes
                # data["service_id"] = selected_service_id
                # data["services"] = [selected_service_id]
                
                # Send as Node ID
                # Try multiple formats as different forks expect different keys
                data["node_id"] = selected_service_id
                data["nodes"] = [selected_service_id]
                data["node_ids"] = [selected_service_id] 
                
                # Also try casting to int just in case
                try:
                    int_id = int(selected_service_id)
                    data["node_ids"] = [int_id]
                except:
                    pass
                    
                logger.info(f"🔗 Assigning Node ID {selected_service_id} to client {username} (omitting service_id)")
            else:
                logger.warning("⚠️ Proceeding without service/node assignment (no nodes found)")
            
            logger.debug(f"📤 Creating client with payload: {data}")
            
            # Send request
            response = self.session.post(
                f"{self.base_url}/api/user",
                json=data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                user_data = response.json()
                logger.info(f"✅ Client {username} created successfully in Rebecca")
                
                # Use the generated UUID if the panel doesn't return one (or returns a different one, though we sent one)
                # Rebecca might overwrite it or accept it. We should check what came back.
                
                uuid_value = ''
                if protocol == 'vless':
                    uuid_value = user_data.get('proxies', {}).get('vless', {}).get('id', '')
                elif protocol == 'vmess':
                    uuid_value = user_data.get('proxies', {}).get('vmess', {}).get('id', '')
                elif protocol == 'trojan':
                    uuid_value = user_data.get('proxies', {}).get('trojan', {}).get('password', '')
                elif protocol == 'shadowsocks':
                    uuid_value = user_data.get('proxies', {}).get('shadowsocks', {}).get('password', '')
                
                # Fallback to vless if UUID not found
                if not uuid_value:
                    uuid_value = user_data.get('proxies', {}).get('vless', {}).get('id', '') or user_data.get('proxies', {}).get('vmess', {}).get('id', '')
                
                # If still no UUID from panel, use the one we generated
                if not uuid_value:
                    uuid_value = client_uuid
                    logger.info(f"⚠️ Panel didn't return UUID, using generated one: {uuid_value}")
                
                # Try to get subscription URL from response first
                # The panel usually returns the correct link with the correct token (which might differ from UUID)
                sub_url = user_data.get('subscription_url', '')
                
                # If relative path, prepend base URL
                if sub_url and sub_url.startswith('/'):
                    base = self.subscription_url if self.subscription_url else self.base_url
                    sub_url = self._join_url(base, sub_url)
                
                # If not in response, check links array
                if not sub_url and 'links' in user_data:
                    links = user_data['links']
                    if links:
                        link = links[0] if isinstance(links, list) else str(links)
                        if link:
                            if link.startswith('/'):
                                base = self.subscription_url if self.subscription_url else self.base_url
                                sub_url = self._join_url(base, link)
                            else:
                                sub_url = link

                # Fallback to manual construction if still no URL
                if not sub_url:
                    # ALWAYS construct subscription URL with UUID without dashes
                    # Rebecca requires the token to be UUID without dashes
                    token = uuid_value.replace('-', '') if uuid_value else username
                    
                    base = self.subscription_url if self.subscription_url else self.base_url
                    
                    # Use _join_url to handle /sub correctly
                    if base.rstrip('/').endswith('/sub'):
                        sub_url = self._join_url(base, token)
                    else:
                        sub_url = self._join_url(base, f"sub/{token}")
                    
                    logger.warning(f"⚠️ Panel didn't return subscription_url, constructed manually: {sub_url}")
                
                # CRITICAL FIX: Ensure the link ALWAYS uses dash-less UUID
                # Even if the panel returned a link, we must verify it doesn't contain dashes in the token part
                # The user reported that links with dashes don't work
                if sub_url:
                    try:
                        # Extract the token part (last part of the URL)
                        parts = sub_url.rstrip('/').split('/')
                        token = parts[-1]
                        
                        # If token looks like a UUID with dashes, remove them
                        if '-' in token and len(token) > 20: # simple heuristic
                            clean_token = token.replace('-', '')
                            # Reconstruct URL
                            base_part = sub_url.rstrip('/').rsplit('/', 1)[0]
                            sub_url = f"{base_part}/{clean_token}"
                            logger.info(f"🔧 Sanitized subscription URL (removed dashes): {sub_url}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to sanitize subscription URL: {e}")
                
                logger.info(f"📎 Subscription URL: {sub_url}")
                
                # Invalidate cache so new client is immediately visible
                self._users_cache = None
                self._cache_timestamp = 0
                logger.info(f"🔄 Cache invalidated after creating client {username}")
                
                # Return client info with 'id' key which is required by telegram_bot.py
                return {
                    'id': uuid_value,          # CRITICAL: This is what telegram_bot uses for client_uuid
                    'uuid': uuid_value,        # Keep for compatibility
                    'username': username,
                    'client_name': username,   # Add for consistency
                    'protocol': protocol,
                    'subscription_url': sub_url,
                    'sub_id': uuid_value,      # Use UUID as sub_id
                    'raw_data': user_data
                }
            else:
                logger.error(f"❌ Failed to create client in Rebecca (Status {response.status_code}): {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error creating client in Rebecca: {e}")
            return None

    def get_client_details(self, inbound_id: int, client_uuid: str,
                           update_inbound_callback=None, service_id=None, client_name=None) -> Optional[Dict]:
        """
        Get specific client details from Rebecca panel
        
        Rebecca uses /api/users (plural) to list all users, not /api/user/{username}.
        We need to fetch all users and find the specific one by username or UUID.
        """
        try:
            if not self.ensure_logged_in():
                return None
            
            logger.info(f"🔍 Getting client details for UUID: {client_uuid[:8] if len(client_uuid) >= 8 else client_uuid}...")
            
            # Optimization: Try to fetch user directly if username is available
            # This avoids fetching ALL users which is slow and prone to timeouts
            target_username = client_name
            if not target_username and client_uuid and not '-' in client_uuid:
                # If uuid has no dashes, it might be the username
                target_username = client_uuid
            
            if target_username:
                try:
                    logger.info(f"🚀 Optimistically fetching user directly: {target_username}")
                    response = self.session.get(
                        f"{self.base_url}/api/user/{target_username}",
                        verify=False,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        user_data = response.json()
                        # Verify it's the correct user (case-insensitive)
                        api_username = user_data.get('username', '')
                        if str(api_username).lower() == str(target_username).lower():
                            logger.info(f"✅ Successfully fetched user directly: {target_username}")
                            return self._process_user_data(user_data, target_username)
                            
                except Exception as e:
                    logger.warning(f"⚠️ Direct fetch failed for {target_username}: {e}")
            
            # If we had a target username and it returned 404, it's likely the user doesn't exist
            # We should try lowercase just in case
            if target_username and client_name:
                # Try lowercase if different
                if target_username != target_username.lower():
                    lower_username = target_username.lower()
                    try:
                        logger.info(f"🔄 Retrying direct fetch with lowercase: {lower_username}")
                        response = self.session.get(
                            f"{self.base_url}/api/user/{lower_username}",
                            verify=False,
                            timeout=30
                        )
                        if response.status_code == 200:
                            user_data = response.json()
                            api_username = user_data.get('username', '')
                            if str(api_username).lower() == lower_username:
                                logger.info(f"✅ Successfully fetched user directly (lowercase): {lower_username}")
                                return self._process_user_data(user_data, lower_username)
                                
                    except Exception as e:
                        logger.warning(f"⚠️ Lowercase direct fetch failed: {e}")

                # If we are here, it means direct fetch (and lowercase retry) failed/404'd.
                
                # OPTIMIZATION: Try to search by UUID or Username using the search endpoint
                # This is much faster than fetching all users
                found_user_data = None
                
                # 1. Search by UUID
                if client_uuid:
                    try:
                        logger.info(f"🔍 Searching by UUID: {client_uuid}")
                        search_response = self.session.get(
                            f"{self.base_url}/api/users",
                            params={'search': client_uuid},
                            verify=False,
                            timeout=30
                        )
                        
                        if search_response.status_code == 200:
                            search_results = search_response.json()
                            users = search_results.get('users', []) if isinstance(search_results, dict) else search_results
                            
                            # Verify UUID match in proxies
                            for user in users:
                                proxies = user.get('proxies', {})
                                for protocol, settings in proxies.items():
                                    if isinstance(settings, dict) and str(settings.get('id')) == str(client_uuid):
                                        logger.info(f"✅ Found user by UUID search: {user.get('username')}")
                                        found_user_data = user
                                        break
                                if found_user_data:
                                    break
                    except Exception as e:
                        logger.warning(f"⚠️ Search by UUID failed: {e}")
                
                # 2. Search by Username (if UUID search failed)
                if not found_user_data and target_username:
                    try:
                        logger.info(f"🔍 Searching by Username: {target_username}")
                        search_response = self.session.get(
                            f"{self.base_url}/api/users",
                            params={'search': target_username},
                            verify=False,
                            timeout=30
                        )
                        
                        if search_response.status_code == 200:
                            search_results = search_response.json()
                            users = search_results.get('users', []) if isinstance(search_results, dict) else search_results
                            
                            for user in users:
                                if str(user.get('username')).lower() == str(target_username).lower():
                                    logger.info(f"✅ Found user by Username search: {user.get('username')}")
                                    found_user_data = user
                                    break
                    except Exception as e:
                        logger.warning(f"⚠️ Search by Username failed: {e}")
                
                # If found via search, process and return
                if found_user_data:
                    return self._process_user_data(found_user_data, found_user_data.get('username'))

                # STOP HERE: Do NOT fallback to full list fetch
                # Fetching all users is extremely slow and causes timeouts.
                logger.warning(f"❌ User {target_username} not found via direct fetch or search. Skipping full list fetch to avoid timeout.")
                return None

            # Fallback to searching by UUID only if no client_name was provided
            # This uses the SEARCH endpoint, not full list fetch
            if client_uuid:
                 try:
                    logger.info(f"🔍 Searching by UUID (no username provided): {client_uuid}")
                    search_response = self.session.get(
                        f"{self.base_url}/api/users",
                        params={'search': client_uuid},
                        verify=False,
                        timeout=30
                    )
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        users = search_results.get('users', []) if isinstance(search_results, dict) else search_results
                        
                        for user in users:
                            proxies = user.get('proxies', {})
                            for protocol, settings in proxies.items():
                                if isinstance(settings, dict) and str(settings.get('id')) == str(client_uuid):
                                    logger.info(f"✅ Found user by UUID search: {user.get('username')}")
                                    return self._process_user_data(user, user.get('username'))
                 except Exception as e:
                    logger.warning(f"⚠️ Search by UUID failed: {e}")

            logger.warning(f"⚠️ User not found: {client_uuid}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting Rebecca user details: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_user_data(self, user_data: Dict, username: str) -> Dict:
        """Helper to process user data and return standardized client details"""
        import time
        
        # Extract usage statistics
        used_traffic = user_data.get('used_traffic', 0)
        total_traffic = user_data.get('data_limit', 0)
        
        # Get online_at for connection status
        online_at = user_data.get('online_at')
        last_activity_timestamp = 0
        
        if online_at:
            try:
                from datetime import datetime, timezone
                if 'Z' in online_at or '+' in online_at:
                    dt = datetime.fromisoformat(online_at.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(online_at).replace(tzinfo=timezone.utc)
                last_activity_timestamp = int(dt.timestamp() * 1000)
            except Exception as e:
                logger.warning(f"⚠️ Could not parse online_at '{online_at}': {e}")
                last_activity_timestamp = 0
        
        # Extract subscription URL
        sub_url = user_data.get('subscription_url', '')
        if sub_url and sub_url.startswith('/'):
            base = self.subscription_url if self.subscription_url else self.base_url
            sub_url = self._join_url(base, sub_url)
            
        # CRITICAL FIX: Ensure the link ALWAYS uses dash-less UUID
        if sub_url:
            try:
                # Extract the token part (last part of the URL)
                parts = sub_url.rstrip('/').split('/')
                token = parts[-1]
                
                # If token looks like a UUID with dashes, remove them
                if '-' in token and len(token) > 20: # simple heuristic
                    clean_token = token.replace('-', '')
                    # Reconstruct URL
                    base_part = sub_url.rstrip('/').rsplit('/', 1)[0]
                    sub_url = f"{base_part}/{clean_token}"
            except Exception as e:
                pass
        
        return {
            'id': username,
            'email': f"{username}@rebecca",
            'enable': user_data.get('status') == 'active',
            'total_traffic': total_traffic if total_traffic else 0,
            'used_traffic': used_traffic if used_traffic else 0,
            'expiryTime': user_data.get('expire', 0) if user_data.get('expire') else 0,
            'created_at': 0,
            'updated_at': int(time.time()),
            'last_activity': last_activity_timestamp,
            'online_at_raw': online_at,
            'subscription_url': sub_url
        }
            


    def reset_client_uuid(self, inbound_id: int, old_client_uuid: str) -> Optional[Dict]:
        """
        Reset user subscription
        Overrides Marzban method to ensure correct link generation and handle UUID vs Username
        """
        try:
            if not self.ensure_logged_in():
                return None
            
            username = old_client_uuid
            
            # Try to revoke using the provided identifier (assuming it's a username)
            response = self.session.post(
                f"{self.base_url}/api/user/{username}/revoke_sub",
                verify=False,
                timeout=60
            )
            
            # If 404, it might be because we passed a UUID instead of a username
            if response.status_code == 404:
                logger.warning(f"⚠️ User {username} not found for reset, searching by UUID...")
                
                # Fetch using search endpoint instead of full list
                found_user = False
                try:
                    search_response = self.session.get(
                        f"{self.base_url}/api/users",
                        params={'search': old_client_uuid},
                        verify=False,
                        timeout=30
                    )
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        users_list = search_results.get('users', []) if isinstance(search_results, dict) else search_results
                        
                        for user in users_list:
                            # Check proxies for the UUID
                            proxies = user.get('proxies', {})
                            uid = ''
                            if 'vless' in proxies: uid = proxies['vless'].get('id', '')
                            elif 'vmess' in proxies: uid = proxies['vmess'].get('id', '')
                            elif 'trojan' in proxies: uid = proxies['trojan'].get('password', '')
                            
                            if uid == old_client_uuid:
                                username = user.get('username')
                                logger.info(f"✅ Found username {username} for UUID {old_client_uuid}")
                                found_user = True
                                break
                except Exception as e:
                    logger.warning(f"⚠️ Search by UUID failed during reset: {e}")
                
                if found_user:
                    # Retry revoke with the correct username
                    response = self.session.post(
                        f"{self.base_url}/api/user/{username}/revoke_sub",
                        verify=False,
                        timeout=60
                    )
            
            if response.status_code == 200:
                # Try to get subscription URL directly from revoke response
                result = response.json()
                new_subscription_url = result.get('subscription_url', '')
                
                # Fix relative paths
                if new_subscription_url and new_subscription_url.startswith('/'):
                    base = self.subscription_url if self.subscription_url else self.base_url
                    new_subscription_url = self._join_url(base, new_subscription_url)
                
                # CRITICAL FIX: Ensure the link ALWAYS uses dash-less UUID
                if new_subscription_url:
                    try:
                        parts = new_subscription_url.rstrip('/').split('/')
                        token = parts[-1]
                        if '-' in token and len(token) > 20:
                            clean_token = token.replace('-', '')
                            base_part = new_subscription_url.rstrip('/').rsplit('/', 1)[0]
                            new_subscription_url = f"{base_part}/{clean_token}"
                            logger.info(f"🔧 Sanitized reset subscription URL: {new_subscription_url}")
                    except:
                        pass
                
                # If we got the URL, we are done
                if new_subscription_url:
                    logger.info(f"✅ Successfully reset Rebecca user subscription: {new_subscription_url}")
                    return {
                        'old_uuid': old_client_uuid,
                        'new_uuid': username,
                        'sub_id': username,
                        'email': f"{username}@rebecca",
                        'subscription_url': new_subscription_url
                    }

                # If not in response, fetch user details to extract it
                # Use direct fetch instead of full list
                user_response = self.session.get(
                    f"{self.base_url}/api/user/{username}",
                    verify=False,
                    timeout=30
                )
                
                if user_response.status_code == 200:
                    found_user_data = user_response.json()
                    
                    if found_user_data:
                        # Try to get subscription_url from user data
                        new_subscription_url = found_user_data.get('subscription_url', '')
                        
                        if new_subscription_url:
                            if new_subscription_url.startswith('/'):
                                base = self.subscription_url if self.subscription_url else self.base_url
                                new_subscription_url = self._join_url(base, new_subscription_url)
                        else:
                            # Fallback to extracting UUID from proxies and constructing manually
                            proxies = found_user_data.get('proxies', {})
                            uuid_value = ''
                            if 'vless' in proxies: uuid_value = proxies['vless'].get('id', '')
                            elif 'vmess' in proxies: uuid_value = proxies['vmess'].get('id', '')
                            elif 'trojan' in proxies: uuid_value = proxies['trojan'].get('password', '')
                            
                            if uuid_value:
                                token = uuid_value.replace('-', '')
                                base = self.subscription_url if self.subscription_url else self.base_url
                                if base.rstrip('/').endswith('/sub'):
                                    new_subscription_url = self._join_url(base, token)
                                else:
                                    new_subscription_url = self._join_url(base, f"sub/{token}")
                            else:
                                # Last resort: use username
                                base = self.subscription_url if self.subscription_url else self.base_url
                                new_subscription_url = self._join_url(base, f"sub/{username}")

                        logger.info(f"✅ Successfully reset Rebecca user subscription: {new_subscription_url}")
                        
                        return {
                            'old_uuid': old_client_uuid,
                            'new_uuid': username,
                            'sub_id': username,
                            'email': f"{username}@rebecca",
                            'subscription_url': new_subscription_url
                        }
                    else:
                        logger.error(f"❌ User {username} not found after reset")
                        return None
                else:
                    logger.error(f"❌ Failed to get user details: {user_response.status_code}")
                    return None
            else:
                logger.error(f"❌ Failed to reset Rebecca subscription: {response.status_code} - {response.text}")
                return None
            
        except Exception as e:
            logger.error(f"❌ Error resetting Rebecca subscription: {e}")
            return None

    def get_client_config_link(self, inbound_id: int, client_id: str, protocol: str) -> Optional[str]:
        """
        Get configuration link for Rebecca user
        
        CRITICAL: Rebecca's subscription_url field contains the CORRECT token,
        which may differ from the proxy UUID. Always prioritize the API-provided URL.
        """
        try:
            if not self.ensure_logged_in():
                return None
            
            # Use search endpoint instead of full list fetch
            user_data = None
            
            # 1. Try direct fetch if client_id looks like a username (no dashes)
            if client_id and '-' not in client_id:
                try:
                    response = self.session.get(
                        f"{self.base_url}/api/user/{client_id}",
                        verify=False,
                        timeout=30
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if str(data.get('username')).lower() == str(client_id).lower():
                            user_data = data
                            logger.info(f"✅ Found user by direct fetch: {client_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Direct fetch failed in config link: {e}")
            
            # 2. If not found, try search by UUID or Username
            if not user_data:
                try:
                    search_response = self.session.get(
                        f"{self.base_url}/api/users",
                        params={'search': client_id},
                        verify=False,
                        timeout=30
                    )
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        users = search_results.get('users', []) if isinstance(search_results, dict) else search_results
                        
                        for user in users:
                            # Check username match
                            if str(user.get('username')).lower() == str(client_id).lower():
                                user_data = user
                                break
                            
                            # Check UUID match in proxies
                            proxies = user.get('proxies', {})
                            for protocol_name, settings in proxies.items():
                                if isinstance(settings, dict):
                                    if str(settings.get('id')) == str(client_id) or str(settings.get('password')) == str(client_id):
                                        user_data = user
                                        break
                            if user_data:
                                break
                except Exception as e:
                    logger.warning(f"⚠️ Search failed in config link: {e}")
            
            if not user_data:
                logger.warning(f"⚠️ User not found for config link: {client_id}")
                return None
            
            # CRITICAL: Prioritize Rebecca's subscription_url field
            # This field contains the CORRECT token that Rebecca expects
            sub_url = user_data.get('subscription_url', '')
            
            if sub_url:
                # Rebecca provided a subscription URL - use it!
                if sub_url.startswith('/'):
                    # Relative path - prepend base URL
                    base = self.subscription_url if self.subscription_url else self.base_url
                    sub_url = self._join_url(base, sub_url)
                
                logger.info(f"✅ Using Rebecca's subscription_url: {sub_url}")
                
                # CRITICAL FIX: Ensure the link ALWAYS uses dash-less UUID
                try:
                    parts = sub_url.rstrip('/').split('/')
                    token = parts[-1]
                    if '-' in token and len(token) > 20:
                        clean_token = token.replace('-', '')
                        base_part = sub_url.rstrip('/').rsplit('/', 1)[0]
                        sub_url = f"{base_part}/{clean_token}"
                        logger.info(f"🔧 Sanitized config link: {sub_url}")
                except:
                    pass
                    
                return sub_url
            
            # Fallback: If Rebecca doesn't provide subscription_url, construct manually
            # This should rarely happen with Rebecca
            logger.warning(f"⚠️ No subscription_url from Rebecca API, constructing manually")
            
            # Extract UUID from proxies
            proxies = user_data.get('proxies', {})
            uuid_value = ''
            
            # Try to get UUID from the requested protocol first
            if protocol and protocol.lower() in proxies:
                settings = proxies[protocol.lower()]
                if isinstance(settings, dict):
                    uuid_value = settings.get('id') or settings.get('password', '')
            
            # Fallback to any available protocol
            if not uuid_value:
                for protocol_name, settings in proxies.items():
                    if isinstance(settings, dict):
                        uuid_value = settings.get('id') or settings.get('password', '')
                        if uuid_value:
                            break
            
            if not uuid_value:
                logger.error(f"❌ Could not extract UUID from user {user_data.get('username')}")
                return None
            
            # Remove dashes to create token
            token = uuid_value.replace('-', '')
            
            # Construct subscription URL
            base = self.subscription_url if self.subscription_url else self.base_url
            
            # Use _join_url to handle /sub correctly
            if base.rstrip('/').endswith('/sub'):
                sub_url = self._join_url(base, token)
            else:
                sub_url = self._join_url(base, f"sub/{token}")
            
            logger.info(f"✅ Manually constructed subscription link: {sub_url}")
            return sub_url
            
        except Exception as e:
            logger.error(f"Error getting Rebecca config link: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
