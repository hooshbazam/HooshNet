"""
Marzneshin Panel Manager
Handles authentication and API communication with Marzneshin panel
Documentation: https://github.com/marzneshin/marzneshin
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

class MarzneshinPanelManager:
    def __init__(self):
        self.base_url = None
        self.username = None
        self.password = None
        self.session = requests.Session()
        self.session.trust_env = False  # Ignore system proxies to prevent connection errors
        self.auth_token = None
        self.token_expiry = None
        
    def login(self) -> bool:
        """Authenticate with the Marzneshin panel"""
        try:
            logger.info(f"🔐 Attempting Marzneshin login to {self.base_url} with username: {self.username}")
            
            # Marzneshin uses OAuth2 form-urlencoded format
            login_data = {
                'username': self.username,
                'password': self.password,
                'grant_type': 'password'
            }
            
            # Important: Marzneshin expects application/x-www-form-urlencoded
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'accept': 'application/json'
            }
            
            response = self.session.post(
                f"{self.base_url}/api/admins/token",
                data=login_data,
                headers=headers,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                self.auth_token = result.get('access_token')
                
                if self.auth_token:
                    # Set authorization header for future requests
                    self.session.headers.update({
                        'Authorization': f'Bearer {self.auth_token}',
                        'accept': 'application/json'
                    })
                    
                    # Token typically expires in 1 hour
                    self.token_expiry = time.time() + 3600
                    
                    logger.info(f"✅ Marzneshin login successful")
                    return True
                else:
                    logger.error(f"❌ No access token in response")
                    return False
            else:
                logger.error(f"❌ Marzneshin login failed: {response.status_code}")
                try:
                    error_detail = response.json()
                    logger.error(f"   Error detail: {error_detail}")
                except:
                    logger.error(f"   Response text: {response.text[:200]}")
                return False
                    
        except requests.exceptions.ConnectionError as e:
            # Suppress full stack trace for connection errors
            logger.error(f"⚠️ Connection failed to {self.base_url}: Connection refused or unreachable")
            return False
        except requests.exceptions.Timeout as e:
            logger.error(f"⚠️ Connection timeout to {self.base_url}")
            return False
        except Exception as e:
            # Only log the error message, not full stack trace
            logger.error(f"⚠️ Marzneshin login error: {str(e)}")
            return False
    
    def ensure_logged_in(self) -> bool:
        """Ensure we have a valid authentication token"""
        if not self.auth_token or (self.token_expiry and time.time() > self.token_expiry):
            return self.login()
        return True
    
    def get_hosts(self) -> List[Dict]:
        """Get list of hosts/inbounds from Marzneshin"""
        try:
            if not self.ensure_logged_in():
                return []
            
            response = self.session.get(
                f"{self.base_url}/api/hosts",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                hosts = response.json()
                print(f"✅ Got {len(hosts)} hosts from Marzneshin")
                return hosts
            else:
                print(f"⚠️ Failed to get hosts: {response.status_code}")
                return []
        except Exception as e:
            print(f"⚠️ Error getting hosts: {e}")
            return []
    
    def get_inbounds(self) -> List[Dict]:
        """Get list of all inbounds from the Marzneshin panel"""
        try:
            if not self.ensure_logged_in():
                print("❌ Failed to login to Marzneshin panel")
                return []
            
            print("🔍 Getting inbounds from Marzneshin...")
            
            # Try to get system stats which includes inbounds info
            # Some Marzneshin versions use /api/inbounds, others use /api/core/config
            endpoints_to_try = [
                '/api/inbounds',
                '/api/core/config',
                '/api/system'
            ]
            
            inbounds_data = None
            for endpoint in endpoints_to_try:
                try:
                    response = self.session.get(
                        f"{self.base_url}{endpoint}",
                        verify=False,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        # Check if we got inbounds data
                        if isinstance(data, list):
                            inbounds_data = data
                            print(f"✅ Got inbounds from {endpoint}")
                            break
                        elif isinstance(data, dict) and 'inbounds' in data:
                            inbounds_data = data['inbounds']
                            print(f"✅ Got inbounds from {endpoint}")
                            break
                except Exception as e:
                    print(f"   Endpoint {endpoint} failed: {e}")
                    continue
            
            if not inbounds_data:
                # If no inbounds found, create a default one
                print("⚠️ No inbounds API found, creating default inbound list")
                return [{
                    'id': 1,
                    'tag': 'VLESS_INBOUND',
                    'protocol': 'vless',
                    'remark': 'Default Marzneshin Inbound',
                    'port': 443,
                    'enable': True,
                    'settings': {}
                }]
            
            # Parse the inbounds
            parsed_inbounds = []
            for idx, inbound in enumerate(inbounds_data, 1):
                parsed_inbound = {
                    'id': inbound.get('id', idx),  # Use actual ID if available, else fallback to index
                    'tag': inbound.get('tag', f"inbound-{idx}"),
                    'protocol': inbound.get('protocol', 'vless'),
                    'remark': inbound.get('tag', f"Inbound {idx}"),
                    'port': inbound.get('port', 0),
                    'enable': True,
                    'settings': inbound.get('settings', {})
                }
                parsed_inbounds.append(parsed_inbound)
                print(f"✅ Parsed Marzneshin inbound: {parsed_inbound['remark']} ({parsed_inbound['protocol']})")
            
            # If parsing resulted in empty list, return default inbound
            if not parsed_inbounds:
                print("⚠️ Parsed inbounds list is empty, creating default inbound list")
                return [{
                    'id': 1,
                    'tag': 'VLESS_INBOUND',
                    'protocol': 'vless',
                    'remark': 'Default Marzneshin Inbound',
                    'port': 443,
                    'enable': True,
                    'settings': {}
                }]
            
            return parsed_inbounds
                    
        except Exception as e:
            print(f"❌ Error getting Marzneshin inbounds: {e}")
            import traceback
            traceback.print_exc()
            # Return default inbound instead of empty list to allow panel addition
            print("⚠️ Returning default inbound due to error")
            return [{
                'id': 1,
                'tag': 'VLESS_INBOUND',
                'protocol': 'vless',
                'remark': 'Default Marzneshin Inbound',
                'port': 443,
                'enable': True,
                'settings': {}
            }]
    
    def get_services(self) -> List[Dict]:
        """Get list of available services from Marzneshin"""
        try:
            if not self.ensure_logged_in():
                return []
            
            response = self.session.get(
                f"{self.base_url}/api/services",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                # Marzneshin pagination response structure
                if isinstance(data, dict) and 'items' in data:
                    return data['items']
                elif isinstance(data, list):
                    return data
            return []
        except Exception as e:
            print(f"❌ Error getting services: {e}")
            return []

    def create_client(self, inbound_id: int, client_name: str, 
                     protocol: str = 'vless', expire_days: int = 0, 
                     total_gb: int = 0, sub_id: str = None) -> Optional[Dict]:
        """
        Create a new user on Marzneshin panel
        """
        try:
            if not self.ensure_logged_in():
                print("❌ Failed to login to Marzneshin panel")
                return None
            
            print(f"🔍 Creating Marzneshin user: {client_name}")
            print(f"   Expire Days: {expire_days if expire_days > 0 else 'Unlimited'}")
            print(f"   Total GB: {total_gb if total_gb > 0 else 'Unlimited'}")
            
            # 1. Get Services
            services = self.get_services()
            if not services:
                print("❌ No services found in Marzneshin")
                # Try to proceed? No, we need a service ID.
                return None
                
            # 2. Find suitable service
            # We need to check inbounds of each service to find one matching the protocol
            all_inbounds = self.get_inbounds()
            inbound_map = {i['id']: i for i in all_inbounds}
            
            selected_service_id = None
            protocol_lower = protocol.lower()
            
            print(f"🔍 Looking for service supporting protocol: {protocol_lower}")
            
            for service in services:
                # Check if service has inbounds with matching protocol
                for i_id in service.get('inbound_ids', []):
                    inbound = inbound_map.get(i_id)
                    if inbound and inbound.get('protocol', '').lower() == protocol_lower:
                        selected_service_id = service['id']
                        print(f"✅ Found matching service: {service['name']} (ID: {selected_service_id})")
                        break
                if selected_service_id:
                    break
            
            if not selected_service_id:
                # Fallback: use the first service if no specific protocol match found
                if services:
                    selected_service_id = services[0]['id']
                    print(f"⚠️ No service found for {protocol}, using first available service: {services[0]['name']}")
            
            if not selected_service_id:
                print("❌ No suitable service found")
                return None

            # 3. Prepare User Data
            # Calculate expiry
            expire_date_str = None
            expire_strategy = "never"
            
            if expire_days > 0:
                # Use UTC for consistency
                expire_dt = datetime.utcnow() + timedelta(days=expire_days)
                # Marzneshin expects ISO 8601 string
                expire_date_str = expire_dt.strftime('%Y-%m-%dT%H:%M:%S')
                expire_strategy = "fixed_date"
            
            # Calculate data limit
            data_limit = 0
            if total_gb > 0:
                data_limit = total_gb * 1024 * 1024 * 1024  # GB to bytes
            
            # Generate UUID for reference (though Marzneshin generates its own keys)
            import uuid as uuid_lib
            client_uuid = str(uuid_lib.uuid4())
            
            user_data = {
                "username": client_name,
                "expire_strategy": expire_strategy,
                "expire_date": expire_date_str,
                "data_limit": data_limit,
                "data_limit_reset_strategy": "no_reset",
                "service_ids": [selected_service_id],
                "status": "active"
            }
            
            print(f"🔍 Creating user with data: {json.dumps(user_data, indent=2)}")
            
            # 4. Create User
            response = self.session.post(
                f"{self.base_url}/api/users",
                json=user_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                print(f"✅ Successfully created Marzneshin user!")
                
                # Get subscription link
                subscription_link = result.get('subscription_url', '')
                
                # If it's a relative path, add base URL
                if subscription_link and subscription_link.startswith('/'):
                    subscription_link = f"{self.base_url}{subscription_link}"
                
                # Try links array if subscription_url not available
                if not subscription_link and 'links' in result:
                    links = result['links']
                    if links:
                        subscription_link = links[0] if isinstance(links, list) else str(links)
                        # Add base URL if it's relative
                        if subscription_link and subscription_link.startswith('/'):
                            subscription_link = f"{self.base_url}{subscription_link}"
                
                # If still no subscription link, get user details
                if not subscription_link:
                    # Get user details to get the actual subscription link
                    user_response = self.session.get(
                        f"{self.base_url}/api/users/{client_name}",
                        verify=False,
                        timeout=30
                    )
                    
                    if user_response.status_code == 200:
                        user_data = user_response.json()
                        subscription_link = user_data.get('subscription_url', '')
                        
                        if subscription_link and subscription_link.startswith('/'):
                            subscription_link = f"{self.base_url}{subscription_link}"
                    
                    # Last resort: construct it manually
                    if not subscription_link:
                        key = user_data.get('key', '')
                        if key:
                            subscription_link = f"{self.base_url}/sub/{client_name}/{key}"
                        else:
                            subscription_link = f"{self.base_url}/sub/{client_name}"
                
                # Return client info
                client = {
                    'id': client_name,  # Use username as ID for Marzneshin
                    'name': client_name,
                    'email': f"{client_name}@marzneshin",
                    'protocol': protocol,
                    'inbound_id': inbound_id,
                    'expire_days': expire_days,
                    'total_gb': total_gb,
                    'expire_time': int(datetime.utcnow().timestamp()) + (expire_days * 86400) if expire_days > 0 else 0,
                    'total_traffic': data_limit,
                    'status': 'active',
                    'uuid': client_name,  # Store username as UUID for compatibility
                    'sub_id': client_name,  # Username for subscription
                    'subscription_url': subscription_link,
                    'created_at': int(time.time()),
                    'marzban_uuid': client_uuid  # Store generated UUID for reference
                }
                
                print(f"✅ Created Marzneshin user: {client_name}")
                print(f"   Subscription: {subscription_link}")
                
                return client
            else:
                error_msg = response.text
                print(f"❌ Failed to create Marzneshin user: {response.status_code}")
                print(f"   Error: {error_msg}")
                return None
                    
        except Exception as e:
            print(f"Error creating Marzneshin user: {e}")
            import traceback
            traceback.print_exc()
            
        return None
    
    def get_client_details(self, inbound_id: int, client_uuid: str,
                          update_inbound_callback=None, service_id=None, client_name=None) -> Optional[Dict]:
        """
        Get specific client details from Marzneshin panel
        
        For Marzneshin, client_uuid might be either:
        1. The actual username (preferred)
        2. A UUID that we need to find the username for
        
        Note: inbound_id is not used in Marzneshin, but kept for compatibility
        """
        try:
            if not self.ensure_logged_in():
                return None
            
            # Strategy 1: Try direct lookup with client_uuid (assuming it's a username)
            username = client_uuid
            
            response = self.session.get(
                f"{self.base_url}/api/users/{username}",
                verify=False,
                timeout=30
            )
            
            # Strategy 2: If failed and client_name provided, try with client_name
            if response.status_code == 404 and client_name and client_name != username:
                print(f"⚠️ User {username} not found, trying with client_name: {client_name}")
                username = client_name
                response = self.session.get(
                    f"{self.base_url}/api/users/{username}",
                    verify=False,
                    timeout=30
                )
            
            # Strategy 3: If still not found and looks like a UUID, search all users
            if response.status_code == 404 and '-' in client_uuid:
                print(f"⚠️ User {username} not found, searching by UUID...")
                
                # Get all users and find by UUID in proxies
                users_response = self.session.get(
                    f"{self.base_url}/api/users",
                    verify=False,
                    timeout=30
                )
                
                if users_response.status_code == 200:
                    users_data = users_response.json()
                    users_list = users_data.get('users', []) if isinstance(users_data, dict) else users_data
                    
                    # Search for user with matching UUID in proxies
                    found = False
                    for user in users_list:
                        proxies = user.get('proxies', {})
                        for protocol, settings in proxies.items():
                            if isinstance(settings, dict) and settings.get('id') == client_uuid:
                                # Found the user!
                                username = user.get('username')
                                print(f"✅ Found user by UUID: {username}")
                                user_data = user
                                found = True
                                break
                        if found:
                            break
                    
                    if not found:
                        print(f"❌ Could not find user with UUID {client_uuid}")
                        return None
                else:
                    return None
            elif response.status_code == 200:
                user_data = response.json()
            else:
                print(f"❌ Failed to get user: {response.status_code}")
                return None
            
            # Get usage statistics
            used_traffic = user_data.get('used_traffic', 0)
            total_traffic = user_data.get('data_limit', 0)
            
            # Get online_at for connection status
            # Marzneshin returns online_at as ISO 8601 datetime string or None
            online_at = user_data.get('online_at')
            last_activity_timestamp = 0
            
            if online_at:
                try:
                    # Parse ISO format datetime string
                    # Example: "2025-01-15T10:30:45.123456Z" or "2025-01-15T10:30:45"
                    # Marzneshin usually returns datetime without timezone, assume UTC
                    if 'Z' in online_at or '+' in online_at:
                        # Has timezone info
                        dt = datetime.fromisoformat(online_at.replace('Z', '+00:00'))
                    else:
                        # No timezone, assume UTC
                        from datetime import timezone
                        dt = datetime.fromisoformat(online_at).replace(tzinfo=timezone.utc)
                    
                    # Convert to milliseconds timestamp
                    last_activity_timestamp = int(dt.timestamp() * 1000)
                except Exception as e:
                    print(f"⚠️ Could not parse online_at '{online_at}': {e}")
                    import traceback
                    traceback.print_exc()
                    last_activity_timestamp = 0
            
            client_details = {
                'id': username,
                'email': f"{username}@marzneshin",
                'enable': user_data.get('status') == 'active',
                'total_traffic': total_traffic,
                'used_traffic': used_traffic,
                'expiryTime': user_data.get('expire', 0) if user_data.get('expire') else 0,
                'created_at': user_data.get('created_at', 0),
                'updated_at': int(time.time()),
                'last_activity': last_activity_timestamp,
                'online_at_raw': online_at  # Keep raw value for debugging
            }
            return client_details
            
        except Exception as e:
            print(f"❌ Error getting Marzneshin user details: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_client_config_link(self, inbound_id: int, client_id: str, 
                              protocol: str) -> Optional[str]:
        """
        Get configuration link for Marzneshin user
        In Marzneshin, we return the subscription link instead of individual config
        """
        try:
            if not self.ensure_logged_in():
                print("❌ Failed to login for config generation")
                return None
            
            # In Marzneshin, client_id is the username
            username = client_id
            
            # Get user details which includes subscription URL
            response = self.session.get(
                f"{self.base_url}/api/users/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                user_data = response.json()
                try:
                    with open('debug_user_data.json', 'w', encoding='utf-8') as f:
                        json.dump(user_data, f, indent=2)
                except:
                    pass
                print(f"🔍 DEBUG: Marzneshin user data: {json.dumps(user_data, indent=2)}")
                subscription_url = user_data.get('subscription_url', '')
                
                # Fix relative paths
                if subscription_url and subscription_url.startswith('/'):
                    subscription_url = f"{self.base_url}{subscription_url}"
                
                if subscription_url:
                    print(f"✅ Got Marzneshin subscription link: {subscription_url}")
                    return subscription_url
                
                # Alternative: construct subscription URL manually
                if 'links' in user_data and user_data['links']:
                    link = user_data['links'][0] if isinstance(user_data['links'], list) else str(user_data['links'])
                    # Fix relative paths
                    if link.startswith('/'):
                        link = f"{self.base_url}{link}"
                    print(f"✅ Got Marzneshin link from links array: {link}")
                    return link
                
                # Last resort: construct it manually
                key = user_data.get('key', '')
                if key:
                    subscription_url = f"{self.base_url}/sub/{username}/{key}"
                else:
                    subscription_url = f"{self.base_url}/sub/{username}"
                print(f"⚠️ Constructed manual subscription link: {subscription_url}")
                return subscription_url
            else:
                print(f"❌ Failed to get user details: {response.status_code}")
            
            return None
                        
        except Exception as e:
            print(f"Error getting Marzneshin client config link: {e}")
            import traceback
            traceback.print_exc()
            
        return None
    
    def update_client_traffic(self, inbound_id: int, client_uuid: str, new_total_gb: int) -> bool:
        """
        Update client traffic (for renewal) in Marzneshin
        
        Args:
            inbound_id: Not used in Marzneshin
            client_uuid: Username
            new_total_gb: New total GB limit
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.ensure_logged_in():
                logger.error("❌ Failed to login to Marzneshin panel")
                return False
            
            username = client_uuid
            
            # Get current user data
            response = self.session.get(
                f"{self.base_url}/api/users/{username}",
                verify=False,
                timeout=30
            )
            
            # If not found and looks like a UUID, search for the user
            if response.status_code == 404 and '-' in str(client_uuid):
                logger.info(f"⚠️ User {username} not found, searching by UUID...")
                
                # Get users with search parameter to avoid fetching all users
                users_response = self.session.get(
                    f"{self.base_url}/api/users",
                    params={'search': client_uuid},
                    verify=False,
                    timeout=30
                )
                
                if users_response.status_code == 200:
                    users_data = users_response.json()
                    users_list = users_data.get('users', []) if isinstance(users_data, dict) else users_data
                    
                    found = False
                    for user in users_list:
                        proxies = user.get('proxies', {})
                        for protocol, settings in proxies.items():
                            if isinstance(settings, dict) and settings.get('id') == client_uuid:
                                username = user.get('username')
                                logger.info(f"✅ Found user by UUID: {username}")
                                response = self.session.get(
                                    f"{self.base_url}/api/users/{username}",
                                    verify=False,
                                    timeout=30
                                )
                                found = True
                                break
                        if found:
                            break
            
            if response.status_code != 200:
                logger.error(f"❌ Failed to get user: {response.status_code}")
                return False
            
            current_user = response.json()
            
            # Update data limit
            new_data_limit = new_total_gb * 1024 * 1024 * 1024  # GB to bytes
            
            update_data = {
                "username": username,  # Required field
                "data_limit": new_data_limit,
                "proxies": current_user.get('proxies', {}),
                "expire": current_user.get('expire'),
                "data_limit_reset_strategy": current_user.get('data_limit_reset_strategy', 'no_reset'),
                "status": "active"
            }
            
            # Update user
            response = self.session.put(
                f"{self.base_url}/api/users/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully updated Marzneshin user traffic to {new_total_gb}GB")
                return True
            else:
                logger.error(f"❌ Failed to update Marzneshin user: {response.status_code}")
                try:
                    logger.error(f"   Response: {response.text}")
                except:
                    pass
                return False
            
        except Exception as e:
            logger.error(f"❌ Error updating Marzneshin user traffic: {e}")
            return False
    
    def disable_client(self, inbound_id: int, client_uuid: str, client_name: str = None) -> bool:
        """Disable user on Marzneshin panel"""
        try:
            if not self.ensure_logged_in():
                return False
            
            # Marzneshin uses username for identification, not UUID
            # If client_name is provided, use it. Otherwise fall back to client_uuid (which might be the username)
            username = client_name if client_name else client_uuid
            
            # Get current user data
            response = self.session.get(
                f"{self.base_url}/api/users/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
            
            current_user = response.json()
            
            # Update user status to disabled
            update_data = {
                "status": "disabled",
                "proxies": current_user.get('proxies', {}),
                "expire": current_user.get('expire'),
                "data_limit": current_user.get('data_limit'),
                "data_limit_reset_strategy": current_user.get('data_limit_reset_strategy', 'no_reset')
            }
            
            # Update user
            response = self.session.put(
                f"{self.base_url}/api/users/{username}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"✅ Successfully disabled Marzneshin user: {username}")
                return True
            else:
                print(f"❌ Failed to disable Marzneshin user: {response.status_code}")
                return False
            
        except Exception as e:
            print(f"❌ Error disabling Marzneshin user: {e}")
            return False
    
    def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        """Delete user from Marzneshin panel"""
        try:
            if not self.ensure_logged_in():
                return False
            
            username = client_uuid
            
            response = self.session.delete(
                f"{self.base_url}/api/users/{username}",
                verify=False,
                timeout=30
            )
            
            if response.status_code in [200, 204]:
                print(f"✅ Successfully deleted Marzneshin user: {username}")
                return True
            else:
                print(f"❌ Failed to delete Marzneshin user: {response.status_code}")
                return False
            
        except Exception as e:
            print(f"❌ Error deleting Marzneshin user: {e}")
            return False
    
    def reset_client_uuid(self, inbound_id: int, old_client_uuid: str) -> Optional[Dict]:
        """
        Reset user subscription (similar to UUID reset in 3x-ui)
        In Marzneshin, we revoke and regenerate the subscription link
        
        Args:
            inbound_id: Not used in Marzneshin
            old_client_uuid: Username
            
        Returns:
            Dictionary with new client info if successful, None otherwise
        """
        try:
            if not self.ensure_logged_in():
                print("❌ Failed to login to Marzneshin panel")
                return None
            
            username = old_client_uuid
            
            # Revoke current subscription
            response = self.session.post(
                f"{self.base_url}/api/users/{username}/revoke_sub",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Get new subscription URL
                new_subscription_url = result.get('subscription_url', '')
                
                # Fix relative paths by adding base_url
                if new_subscription_url and new_subscription_url.startswith('/'):
                    new_subscription_url = f"{self.base_url}{new_subscription_url}"
                
                # If still no subscription URL, construct it manually
                if not new_subscription_url:
                    # Get user details to get the actual subscription link
                    user_response = self.session.get(
                        f"{self.base_url}/api/users/{username}",
                        verify=False,
                        timeout=30
                    )
                    
                    if user_response.status_code == 200:
                        user_data = user_response.json()
                        new_subscription_url = user_data.get('subscription_url', '')
                        
                        if new_subscription_url and new_subscription_url.startswith('/'):
                            new_subscription_url = f"{self.base_url}{new_subscription_url}"
                    
                    # Last resort: construct manually
                    if not new_subscription_url:
                        new_subscription_url = f"{self.base_url}/sub/{username}"
                
                print(f"✅ Successfully reset Marzneshin user subscription!")
                print(f"   New subscription URL: {new_subscription_url}")
                
                return {
                    'old_uuid': old_client_uuid,
                    'new_uuid': username,  # Username stays the same
                    'sub_id': username,
                    'email': f"{username}@marzneshin",
                    'subscription_url': new_subscription_url
                }
            else:
                print(f"❌ Failed to reset Marzneshin subscription: {response.status_code}")
                print(f"   Response: {response.text}")
                return None
            
        except Exception as e:
            print(f"❌ Error resetting Marzneshin subscription: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_system_stats(self) -> Optional[Dict]:
        """Get system statistics from Marzneshin panel"""
        try:
            if not self.ensure_logged_in():
                return None
            
            response = self.session.get(
                f"{self.base_url}/api/system",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            
            return None
            
        except Exception as e:
            print(f"❌ Error getting Marzneshin system stats: {e}")
            return None
    
    def get_inbound_tags(self) -> Dict[str, List[str]]:
        """
        Get inbound tags from Marzneshin
        Returns a dictionary mapping protocol to list of inbound tags
        
        This tries multiple methods:
        1. From /api/inbound (new method)
        2. From node settings
        3. From hosts API  
        4. From core config
        5. From nodes API
        6. Empty dict (let Marzneshin use all available)
        """
        try:
            if not self.ensure_logged_in():
                print("❌ Not logged in")
                return {}
            
            # Method 0: Try to get from /api/inbounds (most direct method - with s!)
            try:
                response = self.session.get(
                    f"{self.base_url}/api/inbounds",
                    verify=False,
                    timeout=30
                )
                
                if response.status_code == 200:
                    inbounds_data = response.json()
                    inbound_tags = {}
                    
                    # The response is a dict like: {"vless": [...], "vmess": [...], "trojan": [...]}
                    if isinstance(inbounds_data, dict):
                        for protocol, inbound_list in inbounds_data.items():
                            protocol_lower = protocol.lower()
                            if isinstance(inbound_list, list):
                                inbound_tags[protocol_lower] = []
                                for inbound in inbound_list:
                                    tag = inbound.get('tag', '')
                                    if tag and tag not in inbound_tags[protocol_lower]:
                                        inbound_tags[protocol_lower].append(tag)
                        
                        if inbound_tags:
                            print(f"✅ Got inbound tags from /api/inbounds: {inbound_tags}")
                            return inbound_tags
            except Exception as e:
                print(f"⚠️ Could not get tags from /api/inbounds: {e}")
            
            # Method 1: Try to get from node settings
            try:
                response = self.session.get(
                    f"{self.base_url}/api/node/settings",
                    verify=False,
                    timeout=30
                )
                
                if response.status_code == 200:
                    settings = response.json()
                    if 'inbounds' in settings:
                        inbound_tags = {}
                        for inbound in settings['inbounds']:
                            protocol = inbound.get('protocol', 'vless').lower()
                            tag = inbound.get('tag', '')
                            
                            if tag:
                                if protocol not in inbound_tags:
                                    inbound_tags[protocol] = []
                                if tag not in inbound_tags[protocol]:
                                    inbound_tags[protocol].append(tag)
                        
                        if inbound_tags:
                            print(f"✅ Got inbound tags from node settings: {inbound_tags}")
                            return inbound_tags
            except Exception as e:
                print(f"⚠️ Could not get tags from node settings: {e}")
            
            # Method 2: Try to get from nodes list
            try:
                response = self.session.get(
                    f"{self.base_url}/api/nodes",
                    verify=False,
                    timeout=30
                )
                
                if response.status_code == 200:
                    nodes = response.json()
                    inbound_tags = {}
                    
                    for node in nodes:
                        if 'inbounds' in node:
                            for inbound in node['inbounds']:
                                protocol = inbound.get('protocol', 'vless')
                                tag = inbound.get('tag', '')
                                
                                if tag:
                                    if protocol not in inbound_tags:
                                        inbound_tags[protocol] = []
                                    if tag not in inbound_tags[protocol]:
                                        inbound_tags[protocol].append(tag)
                    
                    if inbound_tags:
                        print(f"✅ Got inbound tags from nodes: {inbound_tags}")
                        return inbound_tags
            except Exception as e:
                print(f"⚠️ Could not get tags from nodes: {e}")
            
            # Method 3: Try to get from hosts
            try:
                hosts = self.get_hosts()
                if hosts:
                    inbound_tags = {}
                    for host in hosts:
                        if 'inbound' in host:
                            inbound = host['inbound']
                            protocol = inbound.get('protocol', 'vless')
                            tag = inbound.get('tag', '')
                            
                            if tag:
                                if protocol not in inbound_tags:
                                    inbound_tags[protocol] = []
                                if tag not in inbound_tags[protocol]:
                                    inbound_tags[protocol].append(tag)
                    
                    if inbound_tags:
                        print(f"✅ Got inbound tags from hosts: {inbound_tags}")
                        return inbound_tags
            except Exception as e:
                print(f"⚠️ Could not get tags from hosts: {e}")
            
            # Method 4: Try to get from core config
            try:
                response = self.session.get(
                    f"{self.base_url}/api/core",
                    verify=False,
                    timeout=30
                )
                
                if response.status_code == 200:
                    core_config = response.json()
                    if 'inbounds' in core_config:
                        inbound_tags = {}
                        for inbound in core_config['inbounds']:
                            protocol = inbound.get('protocol', 'vless')
                            tag = inbound.get('tag', '')
                            
                            if tag:
                                if protocol not in inbound_tags:
                                    inbound_tags[protocol] = []
                                if tag not in inbound_tags[protocol]:
                                    inbound_tags[protocol].append(tag)
                        
                        if inbound_tags:
                            print(f"✅ Got inbound tags from core: {inbound_tags}")
                            return inbound_tags
            except Exception as e:
                print(f"⚠️ Could not get tags from core: {e}")
            
            # Method 5: Try to get from get_inbounds() as last resort
            print("⚠️ Could not get inbound tags from API, trying get_inbounds()...")
            try:
                inbounds = self.get_inbounds()
                if inbounds:
                    inbound_tags = {}
                    for inbound in inbounds:
                        protocol = inbound.get('protocol', 'vless').lower()
                        tag = inbound.get('tag', '')
                        
                        if tag:
                            if protocol not in inbound_tags:
                                inbound_tags[protocol] = []
                            if tag not in inbound_tags[protocol]:
                                inbound_tags[protocol].append(tag)
                    
                    if inbound_tags:
                        print(f"✅ Got inbound tags from get_inbounds(): {inbound_tags}")
                        return inbound_tags
            except Exception as e:
                print(f"⚠️ Could not get tags from get_inbounds(): {e}")
            
            # Method 6: Return empty dict - let Marzneshin handle it
            # This tells Marzneshin to use all available inbounds
            print("⚠️ Could not get inbound tags, using empty dict (Marzneshin will use all available)")
            return {}
            
        except Exception as e:
            print(f"❌ Error getting inbound tags: {e}")
            return {}


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
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to get users from Marzneshin: {response.status_code}")
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
                    print(f"Error parsing user {user.get('username')}: {e}")
                    continue
            
            return clients
            
        except Exception as e:
            print(f"Error getting all clients from Marzneshin: {e}")
            return []
