"""
3x-ui Panel Manager
Handles authentication and API communication with 3x-ui panel
"""

import requests
import json
import uuid
import secrets
import string
import time
import urllib3
import re
from typing import Dict, List, Optional, Tuple
from config import DEFAULT_PANEL_CONFIG

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class PanelManager:
    def __init__(self):
        self.base_url = DEFAULT_PANEL_CONFIG['api_endpoint']
        self.username = DEFAULT_PANEL_CONFIG['username']
        self.password = DEFAULT_PANEL_CONFIG['password']
        self.session = requests.Session()
        self.session.trust_env = False  # Ignore system proxies to prevent connection errors
        self.auth_token = None
        
    def login(self) -> bool:
        """Authenticate with the 3x-ui panel"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            login_data = {
                'username': self.username,
                'password': self.password
            }
            
            login_url = f"{self.base_url}/login"
            logger.debug(f"Attempting login to: {login_url}")
            
            # Use form data login (this works based on our test)
            response = self.session.post(
                login_url,
                data=login_data,
                verify=False,
                timeout=30
            )
            
            logger.debug(f"Login response status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get('success'):
                        logger.info(f"✅ Login successful to {self.base_url}")
                        return True
                    else:
                        logger.warning(f"Login returned success=False: {result}")
                except:
                    # If not JSON, check for success indicators
                    if 'success' in response.text.lower() or 'dashboard' in response.url:
                        logger.info(f"✅ Login successful (indirect check) to {self.base_url}")
                        return True
                    else:
                        logger.warning(f"Login response is not JSON and no success indicators found. Status: {response.status_code}, URL: {response.url}")
            else:
                # Log detailed error information
                logger.error(f"❌ Login failed with status code: {response.status_code}")
                logger.error(f"   URL: {login_url}")
                logger.error(f"   Response text (first 200 chars): {response.text[:200]}")
                logger.error(f"   Final URL: {response.url}")
                
                # Try to parse error from response
                try:
                    error_json = response.json()
                    logger.error(f"   Error JSON: {error_json}")
                except:
                    pass
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Connection error during login to {self.base_url}: {str(e)}")
            if "ProxyError" in str(e):
                logger.error("⚠️ ProxyError detected! This suggests a system proxy is interfering despite trust_env=False.")
            elif "WinError 10061" in str(e):
                logger.error("⚠️ Connection Refused (WinError 10061). Target machine actively refused connection. Check if panel is running and port is correct.")
            raise  # Re-raise to be caught by caller
        except requests.exceptions.Timeout as e:
            logger.error(f"❌ Timeout during login to {self.base_url}: {str(e)}")
            raise  # Re-raise to be caught by caller
        except Exception as e:
            logger.error(f"❌ Login error to {self.base_url}: {str(e)}", exc_info=True)
            raise  # Re-raise to be caught by caller
            
        return False
    
    def get_inbounds(self) -> List[Dict]:
        """Get list of all inbounds from the panel"""
        try:
            print("🔍 Attempting to connect to panel...")
            if not self.login():
                print("❌ Failed to login to panel")
                return []
            
            print("✅ Successfully logged in to panel")
            
            # Use the real API endpoint
            print("🔍 Getting inbounds from /panel/api/inbounds/list...")
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    print("✅ Got inbounds list successfully")
                    
                    if result.get('success') and 'obj' in result:
                        raw_inbounds = result['obj']
                        print(f"🎯 Found {len(raw_inbounds)} real inbounds from API!")
                        
                        # Parse the inbounds
                        parsed_inbounds = []
                        for inbound in raw_inbounds:
                            # Extract clients from settings
                            clients = []
                            if 'settings' in inbound and isinstance(inbound['settings'], dict):
                                if 'clients' in inbound['settings']:
                                    clients = inbound['settings']['clients']
                            
                            parsed_inbound = {
                                'id': inbound.get('id'),
                                'remark': inbound.get('remark', f"Inbound {inbound.get('id')}"),
                                'protocol': inbound.get('protocol', 'unknown'),
                                'port': inbound.get('port', 0),
                                'enable': inbound.get('enable', True),
                                'settings': inbound.get('settings', {}),
                                'streamSettings': inbound.get('streamSettings', {}),
                                'tag': f"inbound-{inbound.get('port')}",
                                'listen': inbound.get('listen', '0.0.0.0'),
                                'clients': clients
                            }
                            parsed_inbounds.append(parsed_inbound)
                            print(f"✅ Parsed inbound: {parsed_inbound['remark']} ({parsed_inbound['protocol']}:{parsed_inbound['port']}) - {len(clients)} clients")
                        
                        return parsed_inbounds
                    else:
                        print("❌ Invalid response format")
                        
                except json.JSONDecodeError as e:
                    print(f"❌ Failed to parse inbounds JSON: {e}")
            else:
                print(f"❌ Failed to get inbounds: {response.status_code}")
                    
        except Exception as e:
            print(f"❌ Error getting inbounds: {e}")
            
        return []
    
    def get_client_details(self, inbound_id: int, client_uuid: str,
                          update_inbound_callback=None, service_id=None, client_name=None) -> Optional[Dict]:
        """
        Get specific client details from panel
        
        Args:
            inbound_id: Inbound ID
            client_uuid: Client UUID
            update_inbound_callback: Optional callback (not used in 3x-ui)
            service_id: Optional service ID (not used in 3x-ui)
            client_name: Optional client name (used for fallback in Marzban)
        """
        try:
            if not self.login():
                return None
            
            # Get inbound details first
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            if not result.get('success') or 'obj' not in result:
                return None
            
            raw_inbounds = result['obj']
            for inbound in raw_inbounds:
                if inbound.get('id') == inbound_id:
                    # Check both settings.clients and direct clients
                    clients = []
                    
                    # First check direct clients (most common)
                    if 'clients' in inbound and isinstance(inbound['clients'], list):
                        clients = inbound['clients']
                    
                    # If no direct clients, check settings.clients
                    if not clients:
                        settings = inbound.get('settings', {})
                        # Parse settings if it's a string
                        if isinstance(settings, str):
                            try:
                                import json
                                settings = json.loads(settings)
                            except:
                                settings = {}
                        
                        if isinstance(settings, dict) and 'clients' in settings:
                            clients = settings['clients']
                    
                    if isinstance(clients, list):
                        for client in clients:
                            if isinstance(client, dict) and client.get('id') == client_uuid:
                                # Get real-time traffic stats from clientStats
                                used_traffic = 0
                                total_traffic = client.get('totalGB', 0)  # This is in bytes
                                last_activity = 0
                                
                                # Try to get real-time stats from clientStats (this is the accurate source)
                                client_stats = inbound.get('clientStats', [])
                                
                                if client_stats:
                                    for stat in client_stats:
                                        # Different 3x-ui versions use different field names
                                        # Try multiple fields: 'id', 'uuid', 'email' (might contain uuid)
                                        stat_id = stat.get('id', '')
                                        stat_uuid = stat.get('uuid', '')
                                        stat_email = stat.get('email', '')
                                        
                                        # Convert to string for comparison if needed
                                        stat_id_str = str(stat_id) if stat_id else ''
                                        stat_uuid_str = str(stat_uuid) if stat_uuid else ''
                                        
                                        # Extract UUID from email if it contains one (format: username@domain)
                                        email_uuid = ''
                                        if '@' in str(stat_email):
                                            # Email might be like: user@domain or uuid@domain
                                            email_parts = str(stat_email).split('@')[0]
                                            if len(email_parts) > 30:  # UUID-like length
                                                email_uuid = email_parts
                                        
                                        # Try to match with client_uuid (exact match or UUID match)
                                        if (stat_id_str == str(client_uuid) or 
                                            stat_uuid_str == str(client_uuid) or
                                            email_uuid == str(client_uuid)):
                                            # Get used traffic (up + down in bytes)
                                            up_bytes = stat.get('up', 0) or 0
                                            down_bytes = stat.get('down', 0) or 0
                                            used_traffic = up_bytes + down_bytes
                                            last_activity = stat.get('lastOnline', 0) or 0
                                            break
                                
                                # Fallback: if no match in clientStats, try to get from client data itself
                                # Sometimes the client object has direct traffic info
                                if used_traffic == 0 and 'up' in client and 'down' in client:
                                    up_bytes = client.get('up', 0) or 0
                                    down_bytes = client.get('down', 0) or 0
                                    used_traffic = up_bytes + down_bytes
                                
                                # Add some default values if missing
                                client_details = {
                                    'id': client.get('id', client_uuid),
                                    'email': client.get('email', 'Unknown'),
                                    'enable': client.get('enable', True),
                                    'total_traffic': total_traffic,
                                    'used_traffic': used_traffic,
                                    'expiryTime': client.get('expiryTime', 0),
                                    'created_at': client.get('created_at', 0),
                                    'updated_at': client.get('updated_at', 0),
                                    'last_activity': last_activity
                                }
                                return client_details
            return None
            
        except Exception as e:
            print(f"❌ Error getting client details: {e}")
            return None
    
    def _parse_inbounds(self, raw_inbounds: List[Dict]) -> List[Dict]:
        """Parse raw inbound data from API"""
        parsed_inbounds = []
        
        for i, inbound in enumerate(raw_inbounds):
            try:
                # Extract remark from settings if available
                remark = f"Inbound {i + 1}"
                if 'settings' in inbound and isinstance(inbound['settings'], dict):
                    if 'clients' in inbound['settings'] and inbound['settings']['clients']:
                        # Use first client's email as remark if available
                        first_client = inbound['settings']['clients'][0]
                        if 'email' in first_client:
                            remark = first_client['email']
                    elif 'accounts' in inbound['settings'] and inbound['settings']['accounts']:
                        # For protocols like shadowsocks
                        first_account = inbound['settings']['accounts'][0]
                        if 'user' in first_account:
                            remark = first_account['user']
                
                # Try to get remark from tag
                if 'tag' in inbound and inbound['tag']:
                    remark = inbound['tag']
                
                parsed_inbound = {
                    'id': inbound.get('id', i + 1),
                    'remark': remark,
                    'protocol': inbound.get('protocol', 'unknown'),
                    'port': inbound.get('port', 0),
                    'enable': inbound.get('enable', True),
                    'settings': inbound.get('settings', {}),
                    'streamSettings': inbound.get('streamSettings', {}),
                    'tag': inbound.get('tag', ''),
                    'listen': inbound.get('listen', '0.0.0.0')
                }
                parsed_inbounds.append(parsed_inbound)
                print(f"✅ Parsed inbound: {remark} ({parsed_inbound['protocol']}:{parsed_inbound['port']})")
            except Exception as e:
                print(f"Error parsing inbound {i}: {e}")
                continue
                
        return parsed_inbounds
    
    def _parse_html_inbounds(self, html_content: str) -> List[Dict]:
        """Parse inbounds from HTML content"""
        try:
            from bs4 import BeautifulSoup
            import re
            import json
            
            soup = BeautifulSoup(html_content, 'html.parser')
            inbounds = []
            
            # Look for JavaScript data that might contain inbound information
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    script_content = script.string
                    
                    # Look for inbound data patterns
                    patterns = [
                        r'inbounds\s*:\s*(\[.*?\])',
                        r'inboundList\s*:\s*(\[.*?\])',
                        r'data\s*:\s*(\[.*?\])',
                        r'obj\s*:\s*(\[.*?\])'
                    ]
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, script_content, re.DOTALL)
                        for match in matches:
                            try:
                                # Try to parse as JSON
                                data = json.loads(match)
                                if isinstance(data, list) and len(data) > 0:
                                    print(f"✅ Found inbound data in script: {len(data)} items")
                                    return self._parse_inbounds(data)
                            except json.JSONDecodeError:
                                continue
            
            # Look for table rows that might contain inbound data
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for i, row in enumerate(rows[1:], 1):  # Skip header row
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:  # At least 3 columns
                        try:
                            # Extract data from table cells
                            remark = cells[0].get_text(strip=True) if len(cells) > 0 else f"Inbound {i}"
                            protocol = cells[1].get_text(strip=True) if len(cells) > 1 else "unknown"
                            port_text = cells[2].get_text(strip=True) if len(cells) > 2 else "0"
                            
                            # Extract port number
                            port_match = re.search(r'(\d+)', port_text)
                            port = int(port_match.group(1)) if port_match else 0
                            
                            if remark and protocol and port > 0:
                                inbound = {
                                    'id': i,
                                    'remark': remark,
                                    'protocol': protocol.lower(),
                                    'port': port,
                                    'enable': True
                                }
                                inbounds.append(inbound)
                                print(f"✅ Found inbound: {remark} ({protocol}:{port})")
                        except Exception as e:
                            print(f"Error parsing table row {i}: {e}")
                            continue
            
            # Look for div elements that might contain inbound info
            divs = soup.find_all('div', class_=re.compile(r'inbound|port|protocol', re.I))
            for div in divs:
                text = div.get_text(strip=True)
                if any(keyword in text.lower() for keyword in ['vmess', 'vless', 'trojan', 'shadowsocks']):
                    print(f"Found potential inbound div: {text[:100]}...")
            
            print(f"✅ Parsed {len(inbounds)} inbounds from HTML")
            return inbounds
            
        except Exception as e:
            print(f"Error parsing HTML: {e}")
            return []
    
    def get_inbound_clients(self, inbound_id: int) -> List[Dict]:
        """Get clients for a specific inbound"""
        try:
            if not self.auth_token and not self.login():
                return []
                
            response = self.session.get(
                f"{self.base_url}/inbounds/{inbound_id}/clients",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    return result.get('obj', [])
                    
        except Exception as e:
            print(f"Error getting clients: {e}")
            
        return []
    
    def create_client(self, inbound_id: int, client_name: str, 
                     protocol: str = 'vmess', expire_days: int = 0, 
                     total_gb: int = 0, sub_id: str = None) -> Optional[Dict]:
        """Create a new client on specified inbound with comprehensive validation"""
        try:
            if not self.login():
                return None
            
            print(f"🔍 Creating client: {client_name}")
            print(f"   Expire Days: {expire_days if expire_days > 0 else 'Unlimited'}")
            print(f"   Total GB: {total_gb if total_gb > 0 else 'Unlimited'}")
            
            # Get the inbound details first
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print("❌ Failed to get inbounds list")
                return None
            
            result = response.json()
            if not result.get('success') or 'obj' not in result:
                print("❌ Invalid inbounds response")
                return None
            
            # Find the target inbound
            target_inbound = None
            for inbound in result['obj']:
                if inbound.get('id') == inbound_id:
                    target_inbound = inbound
                    break
            
            if not target_inbound:
                print(f"❌ Inbound {inbound_id} not found")
                return None
            
            # Validate inbound settings comprehensively
            validation = self._validate_inbound_settings(target_inbound)
            if not validation['valid']:
                print(f"❌ Inbound validation failed: {validation.get('error', 'Unknown error')}")
                return None
            
            if not validation['can_add_client']:
                print(f"❌ Cannot add more clients to this inbound")
                return None
            
            print(f"✅ Inbound validation passed!")
            
            # Convert days to milliseconds for expiry time
            expire_time = 0
            if expire_days > 0:
                expire_time = int(time.time() * 1000) + (expire_days * 24 * 60 * 60 * 1000)
            
            # Convert GB to bytes for total traffic
            total_traffic = 0
            if total_gb > 0:
                total_traffic = total_gb * 1024 * 1024 * 1024  # Convert GB to bytes
            
            # Generate client credentials
            client_uuid = str(uuid.uuid4())
            # Clean the inbound remark to avoid special characters in email
            inbound_remark = validation['inbound_remark']
            clean_remark = re.sub(r'[^\w\s-]', '', inbound_remark).strip()
            if not clean_remark:
                clean_remark = 'inbound'
            client_email = f"{client_name}@{clean_remark}"
            
            # Create new client with proper format
            current_time = int(time.time() * 1000)  # milliseconds
            # Use provided sub_id or generate a new one
            if not sub_id:
                sub_id = str(uuid.uuid4()).replace('-', '')[:16]  # 16 character subId
            
            new_client = {
                "comment": "",
                "created_at": current_time,
                "email": client_email,
                "enable": True,
                "expiryTime": expire_time,
                "flow": "",
                "id": client_uuid,
                "limitIp": 0,
                "reset": 0,
                "subId": sub_id,
                "tgId": "",
                "totalGB": total_traffic,
                "updated_at": current_time
            }
            
            # Add password for vless protocol
            if validation['inbound_protocol'] == 'vless':
                new_client["password"] = self._generate_password()
            
            # Add new client to existing clients
            current_settings = validation['settings'].copy()
            if 'clients' not in current_settings:
                current_settings['clients'] = []
            
            current_settings['clients'].append(new_client)
            
            # Prepare update data using validated inbound info
            update_data = {
                'up': target_inbound.get('up', 0),
                'down': target_inbound.get('down', 0),
                'total': target_inbound.get('total', 0),
                'remark': target_inbound.get('remark', ''),
                'enable': target_inbound.get('enable', True),
                'expiryTime': target_inbound.get('expiryTime', 0),
                'trafficReset': target_inbound.get('trafficReset', 0),
                'lastTrafficResetTime': target_inbound.get('lastTrafficResetTime', 0),
                'listen': target_inbound.get('listen', ''),
                'port': validation['inbound_port'],
                'protocol': validation['inbound_protocol'],
                'settings': json.dumps(current_settings, ensure_ascii=False, separators=(',', ':')),
                'streamSettings': target_inbound.get('streamSettings', '{}'),
                'sniffing': target_inbound.get('sniffing', '{}')
            }
            
            # Update the inbound with the new client
            print(f"🔍 Adding client to inbound using validated settings...")
            response = self.session.post(
                f"{self.base_url}/panel/api/inbounds/update/{inbound_id}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to update inbound: {response.status_code}")
                return None
            
            result = response.json()
            if not result.get('success'):
                print(f"❌ Failed to add client: {result.get('msg', 'Unknown error')}")
                return None
            
            print(f"✅ Successfully added client to panel!")
            
            # Return client info with validation details
            client = {
                'id': client_uuid,
                'name': client_name,
                'email': client_email,
                'protocol': validation['inbound_protocol'],
                'inbound_id': inbound_id,
                'inbound_tag': validation['inbound_remark'],
                'inbound_port': validation['inbound_port'],
                'server_host': validation['server_host'],
                'network_type': validation['network_type'],
                'security_type': validation['security_type'],
                'host_header': validation['host_header'],
                'path_value': validation['path_value'],
                'expire_days': expire_days,
                'total_gb': total_gb,
                'expire_time': expire_time,
                'total_traffic': total_traffic,
                'status': 'active',
                'uuid': client_uuid,
                'sub_id': sub_id,
                'created_at': int(time.time())
            }
            
            print(f"✅ Created client: {client_name}")
            print(f"   Email: {client_email}")
            print(f"   UUID: {client_uuid}")
            print(f"   Inbound: {validation['inbound_remark']}")
            print(f"   Server: {validation['server_host']}:{validation['inbound_port']}")
            print(f"   Network: {validation['network_type']} ({validation['security_type']})")
            if validation['host_header']:
                print(f"   Host Header: {validation['host_header']}")
            print(f"   Expire: {expire_days} days" if expire_days > 0 else "   Expire: Unlimited")
            print(f"   Traffic: {total_gb} GB" if total_gb > 0 else "   Traffic: Unlimited")
            
            return client
                    
        except Exception as e:
            print(f"Error creating client: {e}")
            
        return None
    
    def _generate_client_config(self, client_name: str, protocol: str) -> Dict:
        """Generate client configuration based on protocol"""
        config = {}
        
        if protocol == 'vmess':
            config = {
                'vmess': {
                    'name': client_name,
                    'uuid': str(uuid.uuid4()),
                    'alterId': 0
                }
            }
        elif protocol == 'vless':
            config = {
                'vless': {
                    'name': client_name,
                    'uuid': str(uuid.uuid4()),
                    'flow': ''
                }
            }
        elif protocol == 'trojan':
            config = {
                'trojan': {
                    'name': client_name,
                    'password': self._generate_password()
                }
            }
        elif protocol == 'shadowsocks':
            config = {
                'shadowsocks': {
                    'name': client_name,
                    'password': self._generate_password()
                }
            }
        else:
            # Default to vmess
            config = {
                'vmess': {
                    'name': client_name,
                    'uuid': str(uuid.uuid4()),
                    'alterId': 0
                }
            }
            
        return config
    
    def _generate_password(self, length: int = 16) -> str:
        """Generate a random password"""
        characters = string.ascii_letters + string.digits
        return ''.join(secrets.choice(characters) for _ in range(length))
    
    def _validate_inbound_settings(self, inbound_data: Dict) -> Dict:
        """Validate and extract inbound settings for proper client creation"""
        try:
            # Extract basic inbound info
            inbound_id = inbound_data.get('id')
            inbound_remark = inbound_data.get('remark', 'Unknown')
            inbound_protocol = inbound_data.get('protocol', 'vless')
            inbound_port = inbound_data.get('port', 443)
            
            # Parse settings
            settings_str = inbound_data.get('settings', '{}')
            try:
                settings = json.loads(settings_str) if isinstance(settings_str, str) else settings_str
            except:
                settings = {"clients": [], "decryption": "none", "encryption": "none"}
            
            # Parse stream settings
            stream_settings_str = inbound_data.get('streamSettings', '{}')
            try:
                stream_settings = json.loads(stream_settings_str) if isinstance(stream_settings_str, str) else stream_settings_str
            except:
                stream_settings = {}
            
            # Extract server details from stream settings
            server_host = "gr.astonnetwork.xyz"  # Default
            if 'externalProxy' in stream_settings and stream_settings['externalProxy']:
                proxy = stream_settings['externalProxy'][0]
                server_host = proxy.get('dest', server_host)
            
            # Extract network and security settings
            network_type = stream_settings.get('network', 'tcp')
            security_type = stream_settings.get('security', 'none')
            
            # Extract TCP settings for HTTP header
            host_header = ""
            path_value = "/"
            header_type = "none"
            
            if 'tcpSettings' in stream_settings and 'header' in stream_settings['tcpSettings']:
                header = stream_settings['tcpSettings']['header']
                header_type = header.get('type', 'none')
                if header_type == 'http' and 'request' in header:
                    request = header['request']
                    if 'headers' in request and 'Host' in request['headers']:
                        host_header = request['headers']['Host'][0] if request['headers']['Host'] else ""
                    if 'path' in request and request['path']:
                        path_value = request['path'][0] if request['path'] else "/"
            
            # Validate client capacity
            current_clients = len(settings.get('clients', []))
            max_clients = 1000  # Reasonable limit
            
            validation_result = {
                'valid': True,
                'inbound_id': inbound_id,
                'inbound_remark': inbound_remark,
                'inbound_protocol': inbound_protocol,
                'inbound_port': inbound_port,
                'server_host': server_host,
                'network_type': network_type,
                'security_type': security_type,
                'host_header': host_header,
                'path_value': path_value,
                'header_type': header_type,
                'current_clients': current_clients,
                'max_clients': max_clients,
                'can_add_client': current_clients < max_clients,
                'settings': settings,
                'stream_settings': stream_settings
            }
            
            # Check if we can add more clients
            if current_clients >= max_clients:
                validation_result['valid'] = False
                validation_result['error'] = f"Maximum client limit reached ({max_clients})"
            
            print(f"🔍 Inbound validation:")
            print(f"   ID: {inbound_id}")
            print(f"   Remark: {inbound_remark}")
            print(f"   Protocol: {inbound_protocol}")
            print(f"   Port: {inbound_port}")
            print(f"   Server: {server_host}")
            print(f"   Network: {network_type}")
            print(f"   Security: {security_type}")
            print(f"   Host Header: {host_header}")
            print(f"   Path: {path_value}")
            print(f"   Current Clients: {current_clients}/{max_clients}")
            print(f"   Can Add Client: {validation_result['can_add_client']}")
            
            return validation_result
            
        except Exception as e:
            print(f"❌ Error validating inbound settings: {e}")
            return {
                'valid': False,
                'error': f"Validation failed: {str(e)}"
            }
    
    def get_client_config_link(self, inbound_id: int, client_id: str, 
                              protocol: str) -> Optional[str]:
        """
        Generate configuration link for client
        NOTE: This returns direct config link. For subscription link, use get_subscription_link()
        """
        try:
            # Ensure we're logged in first
            if not self.login():
                print("❌ Failed to login for config generation")
                return None
            
            # Get inbound details from the real API
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print("❌ Failed to get inbounds list for config link")
                return None
            
            result = response.json()
            if not result.get('success') or 'obj' not in result:
                print("❌ Invalid inbounds response")
                return None
            
            # Find the target inbound
            target_inbound = None
            for inbound in result['obj']:
                if inbound.get('id') == inbound_id:
                    target_inbound = inbound
                    break
            
            if not target_inbound:
                print(f"❌ Inbound {inbound_id} not found for config link")
                return None
            
            # Validate inbound settings to get accurate configuration
            validation = self._validate_inbound_settings(target_inbound)
            if not validation['valid']:
                print(f"❌ Inbound validation failed for config: {validation.get('error', 'Unknown error')}")
                return None
            
            # Find the specific client in the inbound settings
            client_uuid = None
            client_password = None
            if 'clients' in validation['settings']:
                for client in validation['settings']['clients']:
                    if client.get('id') == client_id:
                        client_uuid = client.get('id')
                        client_password = client.get('password', '')
                        break
            
            if not client_uuid:
                print(f"❌ Client {client_id} not found in inbound settings")
                return None
            
            # Generate configuration using validated settings
            import urllib.parse
            clean_remark = urllib.parse.quote(validation['inbound_remark'])
            
            if validation['inbound_protocol'] == 'vless':
                # VLess configuration with validated settings
                if validation['network_type'] == 'tcp' and validation['security_type'] == 'none':
                    # TCP with HTTP header
                    if validation['host_header']:
                        config = f"vless://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}/?type=tcp&encryption=none&path={urllib.parse.quote(validation['path_value'])}&host={validation['host_header']}&headerType=http&security=none#{clean_remark}"
                    else:
                        config = f"vless://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}/?type=tcp&encryption=none&security=none#{clean_remark}"
                else:
                    # WebSocket or other configurations
                    config = f"vless://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}?encryption=none&security={validation['security_type']}&type={validation['network_type']}&host={validation['server_host']}&path={urllib.parse.quote(validation['path_value'])}#{clean_remark}"
            elif validation['inbound_protocol'] == 'vmess':
                # VMess configuration with validated settings
                vmess_config = {
                    "v": "2",
                    "ps": validation['inbound_remark'],
                    "add": validation['server_host'],
                    "port": str(validation['inbound_port']),
                    "id": client_uuid,
                    "aid": "0",
                    "scy": "auto",
                    "net": validation['network_type'],
                    "type": "http" if validation['network_type'] == 'tcp' and validation['host_header'] else "none",
                    "host": validation['host_header'] if validation['host_header'] else validation['server_host'],
                    "path": validation['path_value'],
                    "tls": validation['security_type'],
                    "sni": validation['server_host']
                }
                import base64
                config_json = json.dumps(vmess_config)
                config_b64 = base64.b64encode(config_json.encode()).decode()
                config = f"vmess://{config_b64}"
            elif validation['inbound_protocol'] == 'trojan':
                if validation['network_type'] == 'tcp' and validation['security_type'] == 'none':
                    config = f"trojan://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}/?type=tcp&security=none&path={urllib.parse.quote(validation['path_value'])}&host={validation['host_header']}&headerType=http#{clean_remark}"
                else:
                    config = f"trojan://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}?security={validation['security_type']}&type={validation['network_type']}&host={validation['server_host']}&path={urllib.parse.quote(validation['path_value'])}#{clean_remark}"
            elif validation['inbound_protocol'] == 'shadowsocks':
                config = f"ss://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}#{clean_remark}"
            else:
                # Default to VLess with validated settings
                if validation['network_type'] == 'tcp' and validation['security_type'] == 'none':
                    config = f"vless://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}/?type=tcp&encryption=none&path={urllib.parse.quote(validation['path_value'])}&host={validation['host_header']}&headerType=http&security=none#{clean_remark}"
                else:
                    config = f"vless://{client_uuid}@{validation['server_host']}:{validation['inbound_port']}?encryption=none&security={validation['security_type']}&type={validation['network_type']}&host={validation['server_host']}&path={urllib.parse.quote(validation['path_value'])}#{clean_remark}"
            
            print(f"✅ Generated {validation['inbound_protocol']} config using validated settings")
            print(f"   Server: {validation['server_host']}:{validation['inbound_port']}")
            print(f"   Network: {validation['network_type']} ({validation['security_type']})")
            if validation['host_header']:
                print(f"   Host Header: {validation['host_header']}")
            
            return config
                        
        except Exception as e:
            print(f"Error getting client config link: {e}")
            
        return None
    
    def update_client_traffic(self, inbound_id: int, client_uuid: str, new_total_gb: int) -> bool:
        """
        Update client traffic (for renewal)
        
        Args:
            inbound_id: The inbound ID (used as hint, will search all if not found)
            client_uuid: Client UUID
            new_total_gb: New total GB limit
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Login first
            if not self.login():
                print("❌ Failed to login to panel")
                return False
            
            # First, try the specified inbound
            print(f"🔍 Getting inbound {inbound_id} details...")
            inbound = None
            actual_inbound_id = inbound_id
            client_found = False
            
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/get/{inbound_id}",
                verify=False,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    inbound = result.get('obj')
                    if inbound:
                        # Parse settings and check if client exists
                        settings_str = inbound.get('settings', '{}')
                        if isinstance(settings_str, str):
                            settings = json.loads(settings_str)
                        else:
                            settings = settings_str
                        
                        clients = settings.get('clients', [])
                        for client in clients:
                            if client.get('id') == client_uuid:
                                client_found = True
                                break
            
            # If client not found in specified inbound, search all inbounds
            if not client_found:
                print(f"⚠️ Client {client_uuid} not found in inbound {inbound_id}, searching all inbounds...")
                # Get all inbounds
                response = self.session.get(
                    f"{self.base_url}/panel/api/inbounds/list",
                    verify=False,
                    timeout=30
                )
                
                if response.status_code != 200:
                    print(f"❌ Failed to get inbounds list: {response.status_code}")
                    return False
                
                result = response.json()
                if not result.get('success') or 'obj' not in result:
                    print("❌ Failed to get inbounds list")
                    return False
                
                # Search all inbounds for the client
                for inbound_item in result['obj']:
                    settings_str = inbound_item.get('settings', '{}')
                    if isinstance(settings_str, str):
                        settings = json.loads(settings_str)
                    else:
                        settings = settings_str
                    
                    clients = settings.get('clients', [])
                    for client in clients:
                        if client.get('id') == client_uuid:
                            inbound = inbound_item
                            actual_inbound_id = inbound_item.get('id')
                            client_found = True
                            print(f"✅ Found client in inbound {actual_inbound_id} ({inbound_item.get('remark', 'Unknown')})")
                            break
                    
                    if client_found:
                        break
            
            if not inbound or not client_found:
                print(f"❌ Client {client_uuid} not found in any inbound")
                return False
            
            # Parse settings (in case we found it in a different inbound)
            settings_str = inbound.get('settings', '{}')
            if isinstance(settings_str, str):
                settings = json.loads(settings_str)
            else:
                settings = settings_str
            
            # Find and update the client
            clients = settings.get('clients', [])
            
            for client in clients:
                if client.get('id') == client_uuid:
                    # Update totalGB
                    old_total = client.get('totalGB', 0)
                    client['totalGB'] = new_total_gb * 1024 * 1024 * 1024  # Convert GB to bytes
                    print(f"✅ Found client, updating traffic from {old_total / (1024**3):.2f}GB to {new_total_gb}GB")
                    break
            
            # Update settings
            settings['clients'] = clients
            
            # Prepare update data
            update_data = {
                'up': inbound.get('up', 0),
                'down': inbound.get('down', 0),
                'total': inbound.get('total', 0),
                'remark': inbound.get('remark', ''),
                'enable': inbound.get('enable', True),
                'expiryTime': inbound.get('expiryTime', 0),
                'trafficReset': inbound.get('trafficReset', 0),
                'lastTrafficResetTime': inbound.get('lastTrafficResetTime', 0),
                'listen': inbound.get('listen', ''),
                'port': inbound.get('port', 0),
                'protocol': inbound.get('protocol', ''),
                'settings': json.dumps(settings, ensure_ascii=False, separators=(',', ':')),
                'streamSettings': inbound.get('streamSettings', '{}'),
                'sniffing': inbound.get('sniffing', '{}')
            }
            
            # Update the inbound (use actual_inbound_id in case we found it in a different inbound)
            print(f"🔍 Updating inbound {actual_inbound_id} with new client traffic...")
            response = self.session.post(
                f"{self.base_url}/panel/api/inbounds/update/{actual_inbound_id}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to update inbound: {response.status_code}")
                return False
            
            result = response.json()
            if not result.get('success'):
                print(f"❌ Failed to update client traffic: {result.get('msg', 'Unknown error')}")
                return False
            
            print(f"✅ Successfully updated client traffic to {new_total_gb}GB")
            return True
            
        except Exception as e:
            print(f"❌ Error updating client traffic: {e}")
            return False
    
    def disable_client(self, inbound_id: int, client_uuid: str, client_name: str = None) -> bool:
        """Disable client on panel"""
        try:
            if not self.login():
                return False
            
            # Get current inbound settings
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                return False
            
            result = response.json()
            if not result.get('success') or 'obj' not in result:
                return False
            
            inbounds = result['obj']
            for inbound in inbounds:
                if inbound.get('id') == inbound_id:
                    # Parse settings
                    settings = inbound.get('settings', {})
                    if isinstance(settings, str):
                        try:
                            import json
                            settings = json.loads(settings)
                        except:
                            return False
                    
                    if isinstance(settings, dict) and 'clients' in settings:
                        clients = settings['clients']
                        # Find and disable the client
                        for client in clients:
                            if client.get('id') == client_uuid:
                                client['enable'] = False
                                break
                        
                        # Update settings
                        settings['clients'] = clients
                        
                        # Prepare update data
                        update_data = {
                            'up': inbound.get('up', 0),
                            'down': inbound.get('down', 0),
                            'total': inbound.get('total', 0),
                            'remark': inbound.get('remark', ''),
                            'enable': inbound.get('enable', True),
                            'expiryTime': inbound.get('expiryTime', 0),
                            'trafficReset': inbound.get('trafficReset', 0),
                            'lastTrafficResetTime': inbound.get('lastTrafficResetTime', 0),
                            'listen': inbound.get('listen', ''),
                            'port': inbound.get('port', 0),
                            'protocol': inbound.get('protocol', ''),
                            'settings': json.dumps(settings, ensure_ascii=False, separators=(',', ':')),
                            'streamSettings': inbound.get('streamSettings', '{}'),
                            'sniffing': inbound.get('sniffing', '{}')
                        }
                        
                        # Send update to panel
                        update_response = self.session.post(
                            f"{self.base_url}/panel/api/inbounds/update/{inbound_id}",
                            json=update_data,
                            verify=False,
                            timeout=30
                        )
                        
                        if update_response.status_code == 200:
                            result = update_response.json()
                            return result.get('success', False)
            return False
            
        except Exception as e:
            print(f"❌ Error disabling client: {e}")
            return False
    
    def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        """Delete client from panel completely"""
        try:
            if not self.login():
                print("❌ Failed to login to panel")
                return False
            
            # Get inbound details (use get instead of list for more complete data)
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/get/{inbound_id}",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to get inbound: {response.status_code}")
                return False
            
            result = response.json()
            if not result.get('success'):
                print(f"❌ Failed to get inbound: {result.get('msg', 'Unknown error')}")
                return False
            
            inbound = result.get('obj')
            if not inbound:
                print(f"❌ Inbound {inbound_id} not found")
                return False
            
            # Parse settings
            settings_str = inbound.get('settings', '{}')
            if isinstance(settings_str, str):
                try:
                    settings = json.loads(settings_str)
                except Exception as e:
                    print(f"❌ Error parsing settings: {e}")
                    return False
            else:
                settings = settings_str
            
            # Check if clients exist in settings
            if not isinstance(settings, dict) or 'clients' not in settings:
                print(f"❌ No clients found in inbound {inbound_id}")
                return False
            
            clients = settings.get('clients', [])
            original_count = len(clients)
            
            # Remove the client completely
            settings['clients'] = [client for client in clients if client.get('id') != client_uuid]
            
            if len(settings['clients']) == original_count:
                print(f"⚠️ Client {client_uuid} not found in inbound {inbound_id}")
                return False
            
            print(f"✅ Found and removing client {client_uuid} from inbound {inbound_id}")
            
            # Prepare complete update data (same format as update_client_traffic)
            update_data = {
                'up': inbound.get('up', 0),
                'down': inbound.get('down', 0),
                'total': inbound.get('total', 0),
                'remark': inbound.get('remark', ''),
                'enable': inbound.get('enable', True),
                'expiryTime': inbound.get('expiryTime', 0),
                'trafficReset': inbound.get('trafficReset', 0),
                'lastTrafficResetTime': inbound.get('lastTrafficResetTime', 0),
                'listen': inbound.get('listen', ''),
                'port': inbound.get('port', 0),
                'protocol': inbound.get('protocol', ''),
                'settings': json.dumps(settings, ensure_ascii=False, separators=(',', ':')),
                'streamSettings': inbound.get('streamSettings', '{}'),
                'sniffing': inbound.get('sniffing', '{}')
            }
            
            # Send update to panel
            print(f"🔍 Updating inbound to remove client completely...")
            update_response = self.session.post(
                f"{self.base_url}/panel/api/inbounds/update/{inbound_id}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if update_response.status_code != 200:
                print(f"❌ Failed to update inbound: {update_response.status_code}")
                return False
            
            update_result = update_response.json()
            if not update_result.get('success'):
                print(f"❌ Failed to delete client: {update_result.get('msg', 'Unknown error')}")
                return False
            
            print(f"✅ Successfully deleted client {client_uuid} from inbound {inbound_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error deleting client: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def reset_client_uuid(self, inbound_id: int, old_client_uuid: str) -> Optional[Dict]:
        """
        Reset client UUID without deleting and recreating the client.
        This changes only the UUID while preserving all other settings.
        
        Args:
            inbound_id: The inbound ID
            old_client_uuid: Current client UUID to be changed
            
        Returns:
            Dictionary with new client info if successful, None otherwise
        """
        try:
            if not self.login():
                print("❌ Failed to login to panel")
                return None
            
            print(f"🔍 Getting inbound {inbound_id} to reset client UUID...")
            
            # Get inbound details
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to get inbound list: {response.status_code}")
                return None
            
            result = response.json()
            if not result.get('success') or 'obj' not in result:
                print("❌ Invalid response from panel")
                return None
            
            # Find the target inbound
            target_inbound = None
            for inbound in result['obj']:
                if inbound.get('id') == inbound_id:
                    target_inbound = inbound
                    break
            
            if not target_inbound:
                print(f"❌ Inbound {inbound_id} not found")
                return None
            
            # Parse settings
            settings_str = target_inbound.get('settings', '{}')
            if isinstance(settings_str, str):
                settings = json.loads(settings_str)
            else:
                settings = settings_str
            
            # Find the client and update its UUID
            clients = settings.get('clients', [])
            client_found = False
            old_client_data = None
            new_uuid = str(uuid.uuid4())
            updated_sub_id = None
            
            for client in clients:
                if client.get('id') == old_client_uuid:
                    # Save old client data
                    old_client_data = client.copy()
                    
                    # Update UUID
                    client['id'] = new_uuid
                    
                    # Update timestamps
                    current_time = int(time.time() * 1000)
                    client['updated_at'] = current_time
                    
                    # Preserve existing subId or generate new one if not exists
                    if not client.get('subId'):
                        client['subId'] = str(uuid.uuid4()).replace('-', '')[:16]
                        print(f"🆕 Generated new subId: {client['subId']}")
                    else:
                        print(f"✅ Preserved existing subId: {client['subId']}")
                    
                    updated_sub_id = client['subId']
                    client_found = True
                    print(f"✅ Found client, updating UUID from {old_client_uuid[:8]}... to {new_uuid[:8]}...")
                    break
            
            if not client_found:
                print(f"❌ Client {old_client_uuid} not found in inbound {inbound_id}")
                return None
            
            # Update settings with new client UUID
            settings['clients'] = clients
            
            # Prepare update data
            update_data = {
                'up': target_inbound.get('up', 0),
                'down': target_inbound.get('down', 0),
                'total': target_inbound.get('total', 0),
                'remark': target_inbound.get('remark', ''),
                'enable': target_inbound.get('enable', True),
                'expiryTime': target_inbound.get('expiryTime', 0),
                'trafficReset': target_inbound.get('trafficReset', 0),
                'lastTrafficResetTime': target_inbound.get('lastTrafficResetTime', 0),
                'listen': target_inbound.get('listen', ''),
                'port': target_inbound.get('port', 0),
                'protocol': target_inbound.get('protocol', ''),
                'settings': json.dumps(settings, ensure_ascii=False, separators=(',', ':')),
                'streamSettings': target_inbound.get('streamSettings', '{}'),
                'sniffing': target_inbound.get('sniffing', '{}')
            }
            
            # Update the inbound
            print(f"🔍 Updating inbound with new client UUID...")
            response = self.session.post(
                f"{self.base_url}/panel/api/inbounds/update/{inbound_id}",
                json=update_data,
                verify=False,
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to update inbound: {response.status_code}")
                return None
            
            result = response.json()
            if not result.get('success'):
                print(f"❌ Failed to reset client UUID: {result.get('msg', 'Unknown error')}")
                return None
            
            print(f"✅ Successfully reset client UUID!")
            
            # Return new client info
            return {
                'old_uuid': old_client_uuid,
                'new_uuid': new_uuid,
                'sub_id': updated_sub_id,
                'email': old_client_data.get('email', 'Unknown'),
                'totalGB': old_client_data.get('totalGB', 0),
                'expiryTime': old_client_data.get('expiryTime', 0),
                'enable': old_client_data.get('enable', True)
            }
            
        except Exception as e:
            print(f"❌ Error resetting client UUID: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_all_clients(self) -> List[Dict]:
        """
        Get all clients from the panel with their details
        Used for migration
        """
        try:
            if not self.login():
                return []
            
            inbounds = self.get_inbounds()
            clients = []
            
            for inbound in inbounds:
                settings = inbound.get('settings', {})
                if isinstance(settings, str):
                    import json
                    try:
                        settings = json.loads(settings)
                    except:
                        settings = {}
                
                inbound_clients = settings.get('clients', [])
                client_stats = inbound.get('clientStats', [])
                stats_map = {str(stat.get('id') or stat.get('uuid', '')): stat for stat in client_stats if stat.get('id') or stat.get('uuid')}
                
                for client in inbound_clients:
                    try:
                        client_uuid = str(client.get('id', ''))
                        if not client_uuid:
                            continue
                        
                        stat = stats_map.get(client_uuid, {})
                        used_traffic = 0
                        if stat:
                            used_traffic = (stat.get('up', 0) or 0) + (stat.get('down', 0) or 0)
                        elif 'up' in client and 'down' in client:
                            used_traffic = (client.get('up', 0) or 0) + (client.get('down', 0) or 0)
                        
                        total_traffic = client.get('totalGB', 0)
                        expiry_time = client.get('expiryTime', 0)
                        
                        # Calculate remaining days
                        expire_days = 0
                        if expiry_time and expiry_time > 0:
                            import time
                            now = int(time.time() * 1000)
                            if expiry_time > now:
                                expire_days = int((expiry_time - now) / (1000 * 86400))
                        
                        clients.append({
                            'username': client.get('email', client_uuid),
                            'uuid': client_uuid,
                            'total_traffic': total_traffic,
                            'used_traffic': used_traffic,
                            'expire_timestamp': expiry_time,
                            'expire_days': expire_days,
                            'protocol': inbound.get('protocol', 'vmess'),
                            'status': 'active' if client.get('enable', True) else 'disabled',
                            'inbound_id': inbound.get('id')
                        })
                    except Exception as e:
                        print(f"Error parsing client {client.get('email')}: {e}")
                        continue
            
            return clients
            
        except Exception as e:
            print(f"Error getting all clients from 3x-ui: {e}")
            return []