import requests
import json
import time
import uuid as uuid_lib
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class PasargadPanelManager:
    def __init__(self):
        self.base_url = None
        self.username = None
        self.password = None
        self.session = requests.Session()
        self.session.trust_env = False  # Ignore system proxies
        self.auth_token = None
        self.token_expiry = None
        self.main_group = None # Store the main group for this panel instance

    def _clean_username(self, client_uuid: str, client_name: str = None) -> str:
        """Clean username by removing @pasargad suffix if present"""
        username = client_name if client_name else client_uuid
        if username and '@' in username:
            username = username.split('@')[0]
        return username

    def _get_api_url_variations(self, url: str) -> list:
        """Generate possible API base URLs from the given URL"""
        from urllib.parse import urlparse, urlunparse
        
        parsed = urlparse(url.rstrip('/'))
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        
        variations = []
        
        # 1. Try the exact URL provided (without path segments that look like dashboard paths)
        if parsed.path:
            # Remove common dashboard/panel path segments
            path_segments = parsed.path.strip('/').split('/')
            
            # If path contains dashboard-like segments, try without them
            if path_segments:
                # Try the full provided URL first
                variations.append(url.rstrip('/'))
                
                # Try base domain only (most common for Marzban/PasarGuard)
                if base_domain not in variations:
                    variations.append(base_domain)
                
                # Try removing the last segment (often dashboard name)
                for i in range(len(path_segments), 0, -1):
                    partial_path = '/'.join(path_segments[:i-1])
                    if partial_path:
                        candidate = f"{base_domain}/{partial_path}"
                    else:
                        candidate = base_domain
                    if candidate not in variations:
                        variations.append(candidate)
        else:
            # No path in URL, just use base domain
            variations.append(base_domain)
        
        return variations

    def login(self) -> bool:
        """Login to Pasargad panel and get access token - with smart URL detection"""
        if not self.base_url or not self.username or not self.password:
            logger.error("Pasargad login failed: Missing base_url, username or password")
            return False

        # Check if token is still valid (with 60s buffer)
        if self.auth_token and self.token_expiry and time.time() < (self.token_expiry - 60):
            return True

        try:
            # Pasargad (Marzban fork) uses OAuth2 password flow
            login_data = {
                'username': self.username,
                'password': self.password,
                'grant_type': 'password'
            }
            
            headers = {
                'accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # Get all possible API URL variations
            url_variations = self._get_api_url_variations(self.base_url)
            logger.info(f"🔐 Trying Pasargad login with URL variations: {url_variations}")
            
            for base_url in url_variations:
                login_url = f"{base_url}/api/admin/token"
                logger.info(f"🔐 Attempting Pasargad login to {login_url}")
                
                try:
                    response = self.session.post(
                        login_url,
                        data=login_data,
                        headers=headers,
                        verify=False,
                        timeout=15
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        self.auth_token = result.get('access_token')
                        expires_in = 86400 
                        self.token_expiry = time.time() + expires_in
                        
                        self.session.headers.update({
                            'Authorization': f'Bearer {self.auth_token}',
                            'accept': 'application/json'
                        })
                        
                        # Update base_url to the working one for future requests
                        self.base_url = base_url
                        logger.info(f"✅ Pasargad login successful! Using API URL: {base_url}")
                        return True
                    elif response.status_code == 401:
                        # Auth error means URL is correct but credentials are wrong
                        logger.error(f"❌ Authentication failed (401): Wrong username or password")
                        return False
                    else:
                        logger.debug(f"URL {login_url} returned {response.status_code}")
                        continue
                        
                except Exception as e:
                    logger.debug(f"URL {login_url} failed with error: {e}")
                    continue
            
            # All variations failed
            logger.error(f"❌ Pasargad login failed: Could not find working API URL. Tried: {url_variations}")
            return False

        except Exception as e:
            logger.error(f"Error logging into Pasargad panel: {e}")
            return False
            return False

    def get_groups(self) -> list:
        """Fetch available groups from Pasargad panel"""
        if not self.login():
            logger.error("❌ Cannot fetch groups: Login failed")
            return []
            
        try:
            groups_url = f"{self.base_url}/api/groups"
            logger.info(f"📂 Fetching groups from: {groups_url}")
            
            response = self.session.get(
                groups_url,
                verify=False,
                timeout=30
            )
            
            logger.info(f"📂 Groups API response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📂 Groups API data: {data}")
                
                # PasarGuard returns: {groups: [...], total: X}
                if isinstance(data, dict) and 'groups' in data:
                    groups_list = data.get('groups', [])
                    result = []
                    for g in groups_list:
                        if isinstance(g, dict):
                            result.append({
                                'id': g.get('id', g.get('name')),
                                'name': g.get('name', str(g.get('id', 'Unknown')))
                            })
                    logger.info(f"✅ Found {len(result)} groups: {result}")
                    return result
                
                # Direct list response (legacy Marzban style)
                elif isinstance(data, list):
                    if data and isinstance(data[0], str):
                        result = [{'id': name, 'name': name} for name in data]
                    elif data and isinstance(data[0], dict):
                        result = [{'id': g.get('id', g.get('name')), 'name': g.get('name')} for g in data if g.get('name')]
                    else:
                        result = []
                    logger.info(f"✅ Found {len(result)} groups (list format): {result}")
                    return result
                
                logger.warning(f"⚠️ Unexpected groups response format: {type(data)}")
                return []
            else:
                logger.error(f"❌ Failed to get groups: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"❌ Error getting groups: {e}")
            return []

    def get_inbounds(self) -> List[Dict]:
        """
        Get inbounds/groups. 
        For Pasargad, we treat 'groups' as 'inbounds' for compatibility with the rest of the system.
        """
        if not self.login():
            return []

        try:
            # We fetch groups and format them as 'inbounds'
            # This allows the existing frontend to select a 'default inbound' which will be the 'Main Group'
            groups = self.get_groups()
            
            inbounds = []
            for i, group in enumerate(groups):
                group_name = group['name']
                inbounds.append({
                    'id': i + 1, # Fake ID
                    'tag': group_name, # Use group name as tag
                    'protocol': 'pasargad',
                    'remark': group_name,
                    'port': 443, # Dummy port
                    'enable': True,
                    'settings': {'group_name': group_name}
                })
                
            if not inbounds:
                # Return a default if no groups found, to avoid errors
                return [{
                    'id': 1,
                    'tag': 'default',
                    'protocol': 'pasargad',
                    'remark': 'Default Group',
                    'port': 443,
                    'enable': True,
                    'settings': {'group_name': 'default'}
                }]
                
            return inbounds

        except Exception as e:
            logger.error(f"Error getting inbounds (groups): {e}")
            return []

    def create_client(self, inbound_id: int, client_name: str,
                      protocol: str = 'vless', expire_days: int = 0,
                      total_gb: int = 0, sub_id: str = None, 
                      extra_config: dict = None) -> Optional[Dict]:
        """
        Create a new user in Pasargad panel.
        
        Args:
            inbound_id: Ignored, we use self.main_group or extra_config
            client_name: Username
            protocol: Ignored
            expire_days: 0 for unlimited
            total_gb: 0 for unlimited
            sub_id: Subscription ID (usually same as username)
            extra_config: May contain 'main_group'
        """
        if not self.login():
            return None

        try:
            # Determine group_id from panel's extra_config
            group_id = None
            
            # First try from main_group attribute
            if self.main_group:
                # main_group could be ID (int/str) or name
                try:
                    group_id = int(self.main_group)
                except (ValueError, TypeError):
                    # It's a name, need to find the ID
                    groups = self.get_groups()
                    for g in groups:
                        if g.get('name') == self.main_group or str(g.get('id')) == str(self.main_group):
                            group_id = g.get('id')
                            break
            
            # Try from extra_config if passed
            if not group_id and extra_config and 'main_group' in extra_config:
                main_group_val = extra_config['main_group']
                try:
                    group_id = int(main_group_val)
                except (ValueError, TypeError):
                    # It's a name, find the ID
                    groups = self.get_groups()
                    for g in groups:
                        if g.get('name') == main_group_val or str(g.get('id')) == str(main_group_val):
                            group_id = g.get('id')
                            break
            
            # If still no group, try to get first available
            if not group_id:
                groups = self.get_groups()
                if groups:
                    group_id = groups[0].get('id')
                    logger.info(f"Using first available group: {group_id}")
                else:
                    logger.error("No groups available to assign user to")
                    return None

            logger.info(f"📂 Creating user with group_id: {group_id}")

            # Calculate limits
            data_limit = total_gb * 1024 * 1024 * 1024 if total_gb > 0 else 0
            expire_timestamp = None
            if expire_days > 0:
                expire_timestamp = int(time.time()) + (expire_days * 86400)

            # Prepare user data - PasarGuard uses group_ids (list of integers)
            user_data = {
                "username": client_name,
                "group_ids": [int(group_id)] if group_id else [],
                "data_limit": data_limit,
                "expire": expire_timestamp,
                "status": "active"
            }
            
            logger.info(f"📤 Creating user with data: {user_data}")
            
            response = self.session.post(
                f"{self.base_url}/api/user",
                json=user_data,
                verify=False,
                timeout=30
            )

            if response.status_code in (200, 201):
                result = response.json()
                # Construct subscription link
                # User said: "Ensure the full login URL provided by the admin for Pasargad panels is used directly without modification."
                # Usually subscription link is base_url/sub/token
                # But we need to check how Pasargad handles it. 
                # Marzban returns 'subscription_url' in response usually.
                
                subscription_link = result.get('subscription_url', '')
                if not subscription_link and self.base_url:
                     # Fallback construction if not provided
                     # Assuming standard Marzban-like sub path
                     subscription_link = f"{self.base_url}/sub/{result.get('token', '')}"

                client = {
                    'id': client_name,
                    'name': client_name,
                    'email': f"{client_name}@pasargad",
                    'protocol': protocol,
                    'inbound_id': inbound_id,
                    'expire_days': expire_days,
                    'total_gb': total_gb,
                    'expire_time': expire_timestamp,
                    'total_traffic': data_limit,
                    'status': 'active',
                    'uuid': client_name, 
                    'sub_id': client_name,
                    'subscription_url': subscription_link,
                    'created_at': int(time.time()),
                    'pasargad_group': group_id
                }
                return client
            else:
                logger.error(f"Failed to create client: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating client: {e}")
            return None

    def get_client_details(self, inbound_id: int, client_uuid: str,
                          update_inbound_callback=None, service_id=None, client_name=None) -> Optional[Dict]:
        """Get client details by username"""
        if not self.login():
            return None

        try:
            # Clean username (remove @pasargad suffix if present)
            username = self._clean_username(client_uuid, client_name)
            
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )

            if response.status_code == 200:
                user_data = response.json()
                
                used_traffic = (user_data.get('used_traffic', 0) or 0)
                total_traffic = user_data.get('data_limit', 0) or 0
                
                # Calculate online status/last activity
                # Pasargad might have 'online_at' or similar
                last_activity = user_data.get('online_at')
                last_activity_timestamp = 0
                
                if last_activity:
                    try:
                        if isinstance(last_activity, str):
                            # Parse ISO format
                            dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                            last_activity_timestamp = int(dt.timestamp() * 1000)
                        elif isinstance(last_activity, (int, float)):
                            last_activity_timestamp = int(last_activity * 1000)
                    except:
                        pass

                return {
                    'id': username,
                    'email': f"{username}@pasargad",
                    'enable': user_data.get('status') == 'active',
                    'total_traffic': total_traffic,
                    'used_traffic': used_traffic,
                    'expiryTime': user_data.get('expire', 0) if user_data.get('expire') else 0,
                    'created_at': user_data.get('created_at', 0),
                    'updated_at': int(time.time()),
                    'last_activity': last_activity_timestamp,
                    'sub_id': username
                }
            else:
                return None

        except Exception as e:
            logger.error(f"Error getting client details: {e}")
            return None

    def update_client_traffic(self, inbound_id: int, client_uuid: str, new_total_gb: int) -> bool:
        """Update client traffic limit"""
        if not self.login():
            return False

        try:
            username = client_uuid
            
            # First get current user data to preserve other fields
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
                
            current_user = response.json()
            
            new_data_limit = new_total_gb * 1024 * 1024 * 1024 if new_total_gb > 0 else 0
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "data_limit": new_data_limit,
                "group_ids": current_user.get('group_ids', []),
                "expire": current_user.get('expire'),
                "status": current_user.get('status', 'active')
            }
            
            logger.info(f"📤 Updating traffic for {username}: {update_data}")
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                logger.info(f"✅ Traffic updated for {username}")
                return True
            else:
                logger.error(f"❌ Failed to update traffic: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error updating client traffic: {e}")
            return False

    def reset_client_traffic(self, inbound_id: int, client_uuid: str) -> bool:
        """Reset client traffic usage"""
        if not self.login():
            return False
            
        try:
            username = client_uuid
            # Usually DELETE /api/user/{username}/usage or similar
            # For Marzban it is POST /api/user/{username}/reset
            
            response = self.session.post(
                f"{self.base_url}/api/user/{username}/reset",
                verify=False,
                timeout=30
            )
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error resetting traffic: {e}")
            return False

    def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        """Delete client"""
        if not self.login():
            return False

        try:
            username = client_uuid
            response = self.session.delete(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error deleting client: {e}")
            return False

    def disable_client(self, inbound_id: int, client_uuid: str, client_name: str = None) -> bool:
        """Disable client"""
        if not self.login():
            return False

        try:
            username = client_name if client_name else client_uuid
            
            # Get current data
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
                
            current_user = response.json()
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "status": "disabled",
                "group_ids": current_user.get('group_ids', []),
                "expire": current_user.get('expire'),
                "data_limit": current_user.get('data_limit')
            }
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            return response.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Error disabling client: {e}")
            return False

    def enable_client(self, inbound_id: int, client_uuid: str, client_name: str = None) -> bool:
        """Enable client"""
        if not self.login():
            return False

        try:
            username = client_name if client_name else client_uuid
            
            # Get current data
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
                
            current_user = response.json()
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "status": "active",
                "group_ids": current_user.get('group_ids', []),
                "expire": current_user.get('expire'),
                "data_limit": current_user.get('data_limit')
            }
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            return response.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Error enabling client: {e}")
            return False

    def get_client_config(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[str]:
        """Get client subscription link"""
        if not self.login():
            return None

        try:
            # Use client_name if provided, otherwise client_uuid
            # Remove @pasargad suffix if present
            username = client_name if client_name else client_uuid
            if '@' in username:
                username = username.split('@')[0]
            
            logger.info(f"📱 Getting config link for user: {username}")
            
            # Get user data which contains subscription_url
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )

            if response.status_code == 200:
                user_data = response.json()
                subscription_url = user_data.get('subscription_url', '')
                
                if subscription_url:
                    return subscription_url
                
                # Try to construct link from user data if subscription_url is missing
                proxy_settings = user_data.get('proxy_settings', {})
                if proxy_settings:
                    # Return first available proxy config
                    for proto, settings in proxy_settings.items():
                        if 'id' in settings:
                            return f"{proto}://{settings['id']}@{self.base_url.replace('https://', '').replace('http://', '')}"
                
                return None
            else:
                logger.error(f"Failed to get user for config: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting client config: {e}")
            return None

    def update_client_expire(self, inbound_id: int, client_uuid: str, new_expire_days: int) -> bool:
        """Update client expiration time"""
        if not self.login():
            return False

        try:
            username = client_uuid
            
            # Get current user data
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get user for expire update: {response.status_code}")
                return False
                
            current_user = response.json()
            
            # Calculate new expire timestamp
            if new_expire_days > 0:
                new_expire = int(time.time()) + (new_expire_days * 86400)
            else:
                new_expire = None  # Unlimited
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "expire": new_expire,
                "group_ids": current_user.get('group_ids', []),
                "status": current_user.get('status', 'active'),
                "data_limit": current_user.get('data_limit')
            }
            
            logger.info(f"📤 Updating expire for {username}: {update_data}")
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                logger.info(f"✅ Expire updated for {username}")
                return True
            else:
                logger.error(f"❌ Failed to update expire: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error updating client expire: {e}")
            return False

    def update_client_expiration(self, inbound_id: int, client_uuid: str, expiration_timestamp: int, client_name: str = None) -> bool:
        """Update client expiration time with absolute timestamp"""
        if not self.login():
            return False

        try:
            # For Pasargad, client_uuid is typically the username
            username = client_name if client_name else client_uuid
            # Clean username if needed
            if username.endswith('@pasargad'):
                username = username[:-9]
            
            # Get current user data
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get user for expiration update: {response.status_code}")
                return False
                
            current_user = response.json()
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "expire": expiration_timestamp,
                "group_ids": current_user.get('group_ids', []),
                "status": current_user.get('status', 'active'),
                "data_limit": current_user.get('data_limit')
            }
            
            logger.info(f"📤 Updating expiration for {username} to {expiration_timestamp}")
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                logger.info(f"✅ Expiration updated for {username}")
                return True
            else:
                logger.error(f"❌ Failed to update expiration: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error updating client expiration: {e}")
            return False

    def get_client_config_link(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[str]:
        """Alias for get_client_config - for compatibility with telegram_bot.py"""
        return self.get_client_config(inbound_id, client_uuid, client_name)

    def reset_client_uuid(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[Dict]:
        """
        Reset client subscription (revoke and regenerate).
        In PasarGuard this is done via POST /api/user/{username}/revoke_sub
        """
        if not self.login():
            return None

        try:
            # Use client_name if provided, otherwise client_uuid
            # Remove @pasargad suffix if present
            username = client_name if client_name else client_uuid
            if '@' in username:
                username = username.split('@')[0]
            
            # Revoke subscription - generates new subscription token
            response = self.session.post(
                f"{self.base_url}/api/user/{username}/revoke_sub",
                verify=False,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                result = response.json()
                logger.info(f"✅ Subscription revoked/reset for {username}")
                
                # Get new subscription URL from result
                new_sub_url = result.get('subscription_url', '')
                
                # Return new client info with 'new_uuid' key as expected by telegram_bot.py
                return {
                    'id': username,
                    'name': username,
                    'email': f"{username}@pasargad",
                    'uuid': username,
                    'new_uuid': username,  # Bot expects this key
                    'sub_id': username,
                    'subscription_url': new_sub_url,
                    'status': result.get('status', 'active')
                }
            else:
                logger.error(f"❌ Failed to reset subscription: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error resetting client UUID: {e}")
            return None

    def add_traffic_to_client(self, inbound_id: int, client_uuid: str, additional_gb: int, client_name: str = None) -> bool:
        """Add traffic to existing client"""
        if not self.login():
            return False

        try:
            username = client_name if client_name else client_uuid
            
            # Get current user data
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get user for adding traffic: {response.status_code}")
                return False
                
            current_user = response.json()
            
            # Calculate new data limit
            current_limit = current_user.get('data_limit', 0) or 0
            additional_bytes = additional_gb * 1024 * 1024 * 1024
            new_limit = current_limit + additional_bytes
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "data_limit": new_limit,
                "group_ids": current_user.get('group_ids', []),
                "expire": current_user.get('expire'),
                "status": current_user.get('status', 'active')
            }
            
            logger.info(f"📤 Adding {additional_gb}GB to {username}. New limit: {new_limit}")
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                logger.info(f"✅ Traffic added for {username}")
                return True
            else:
                logger.error(f"❌ Failed to add traffic: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error adding traffic to client: {e}")
            return False

    def extend_client_expire(self, inbound_id: int, client_uuid: str, additional_days: int, client_name: str = None) -> bool:
        """Extend client expiration time by additional days"""
        if not self.login():
            return False

        try:
            username = client_name if client_name else client_uuid
            
            # Get current user data
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get user for extending expire: {response.status_code}")
                return False
                
            current_user = response.json()
            
            # Calculate new expire timestamp
            current_expire = current_user.get('expire')
            additional_seconds = additional_days * 86400
            
            if current_expire and current_expire > 0:
                # Extend from current expire
                new_expire = current_expire + additional_seconds
            else:
                # Start from now
                new_expire = int(time.time()) + additional_seconds
            
            # PasarGuard uses group_ids not groups
            update_data = {
                "expire": new_expire,
                "group_ids": current_user.get('group_ids', []),
                "status": current_user.get('status', 'active'),
                "data_limit": current_user.get('data_limit')
            }
            
            logger.info(f"📤 Extending expire for {username} by {additional_days} days. New expire: {new_expire}")
            
            response = self.session.put(
                f"{self.base_url}/api/user/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in (200, 201):
                logger.info(f"✅ Expire extended for {username}")
                return True
            else:
                logger.error(f"❌ Failed to extend expire: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error extending client expire: {e}")
            return False



    def get_client_config_link(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[str]:
        """Alias for get_client_config - for compatibility with telegram_bot.py"""
        return self.get_client_config(inbound_id, client_uuid, client_name)



    def get_subscription_link(self, inbound_id: int, client_uuid: str, client_name: str = None) -> Optional[str]:
        """Get subscription link for a client"""
        if not self.login():
            return None

        try:
            username = client_name if client_name else client_uuid
            
            response = self.session.get(
                f"{self.base_url}/api/user/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                user_data = response.json()
                return user_data.get('subscription_url', '')
            else:
                logger.error(f"Failed to get subscription link: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting subscription link: {e}")
            return None
