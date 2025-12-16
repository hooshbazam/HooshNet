"""
Admin Manager
Manages interactions with different types of VPN panels (3x-ui, Marzban, Rebecca)
Acts as a factory to return the appropriate panel manager instance
"""

import logging
from typing import Dict, List, Optional, Tuple, Union
from professional_database import ProfessionalDatabaseManager
from panel_manager import PanelManager
from marzban_manager import MarzbanPanelManager
from rebecca_manager import RebeccaPanelManager
from pasargad_manager import PasargadPanelManager
from marzneshin_manager import MarzneshinPanelManager

logger = logging.getLogger(__name__)

class AdminManager:
    def __init__(self, db: ProfessionalDatabaseManager):
        self.db = db
        
    def get_panel_manager(self, panel_id: int) -> Optional[Union[PanelManager, MarzbanPanelManager, RebeccaPanelManager, PasargadPanelManager, MarzneshinPanelManager]]:
        """
        Factory method to get the appropriate panel manager based on panel type
        """
        try:
            # Get panel details from database
            panel = self.db.get_panel(panel_id)
            if not panel:
                logger.error(f"Panel {panel_id} not found")
                return None
            
            panel_type = panel.get('panel_type', '3x-ui')
            
            # Instantiate appropriate manager
            manager = None
            if panel_type == 'marzban':
                manager = MarzbanPanelManager()
            elif panel_type == 'rebecca':
                manager = RebeccaPanelManager()
            elif panel_type == 'pasargad':
                manager = PasargadPanelManager()
            elif panel_type == 'marzneshin':
                manager = MarzneshinPanelManager()
            else:
                # Default to 3x-ui
                manager = PanelManager()
            
            # Configure manager with credentials
            manager.base_url = panel.get('api_endpoint') or panel.get('url')
            manager.username = panel.get('username')
            manager.password = panel.get('password')
            
            # For Rebecca/Marzban, we might need subscription_url if available
            if hasattr(manager, 'subscription_url'):
                manager.subscription_url = panel.get('subscription_url')
            
            # For Pasargad, set main group if available
            if isinstance(manager, PasargadPanelManager) and panel.get('extra_config'):
                try:
                    extra_config = json.loads(panel.get('extra_config')) if isinstance(panel.get('extra_config'), str) else panel.get('extra_config')
                    if extra_config and 'main_group' in extra_config:
                        manager.main_group = extra_config['main_group']
                except:
                    pass
                
            return manager
            
        except Exception as e:
            logger.error(f"Error getting panel manager for panel {panel_id}: {e}")
            return None

    def get_panel_details(self, panel_id: int, sync_inbounds: bool = False) -> Optional[Dict]:
        """Get panel details from database, optionally syncing inbounds"""
        panel = self.db.get_panel(panel_id)
        if not panel:
            return None
            
        if sync_inbounds:
            self.sync_panel_inbounds_to_db(panel_id)
            
        # Enrich with inbound info
        inbounds = self.db.get_stored_panel_inbounds(panel_id)
        panel['inbounds_count'] = len(inbounds)
        
        # Add main inbound details
        if panel.get('default_inbound_id'):
            main_inbound = self.db.get_panel_inbound(panel_id, panel['default_inbound_id'])
            if main_inbound:
                panel['main_inbound'] = {
                    'name': main_inbound['inbound_name'],
                    'protocol': main_inbound['inbound_protocol'],
                    'port': main_inbound['inbound_port']
                }
                
        return panel

    def test_panel_connection(self, panel_id: int) -> Tuple[bool, str]:
        """Test connection to a panel"""
        try:
            manager = self.get_panel_manager(panel_id)
            if not manager:
                return False, "Panel manager could not be initialized"
            
            if manager.login():
                return True, "✅ اتصال با موفقیت برقرار شد"
            else:
                return False, "❌ خطا در اتصال به پنل (نام کاربری/رمز عبور یا آدرس اشتباه است)"
                
        except Exception as e:
            logger.error(f"Error testing panel connection: {e}")
            return False, f"❌ خطای سیستمی: {str(e)}"

    def get_panel_inbounds(self, panel_id: int) -> List[Dict]:
        """Get inbounds for a panel"""
        try:
            manager = self.get_panel_manager(panel_id)
            if not manager:
                return []
            
            if not manager.login():
                return []
            
            return manager.get_inbounds()
            
        except Exception as e:
            logger.error(f"Error getting panel inbounds: {e}")
            return []
            
    def get_all_panels(self) -> List[Dict]:
        """Get all panels from database"""
        return self.db.get_all_panels()

    def create_client_on_panel(self, panel_id: int, inbound_id: int, client_name: str, 
                             protocol: str = 'vless', expire_days: int = 0, 
                             total_gb: int = 0) -> Tuple[bool, str, Optional[Dict]]:
        """
        Create a client on a specific inbound of a panel.
        """
        try:
            manager = self.get_panel_manager(panel_id)
            if not manager:
                return False, "Panel manager could not be initialized", None
            
            if not manager.login():
                return False, "Login failed", None
            
            # Create client on the specified inbound
            client = manager.create_client(
                inbound_id=inbound_id,
                client_name=client_name,
                protocol=protocol,
                expire_days=expire_days,
                total_gb=total_gb
            )
            
            if client:
                return True, "Client created successfully", client
            else:
                return False, "Failed to create client on panel", None
                
        except Exception as e:
            logger.error(f"Error in create_client_on_panel: {e}")
            return False, f"System error: {str(e)}", None

    def create_client_on_all_panel_inbounds(self, panel_id: int, client_name: str, 
                                          protocol: str = 'vless', expire_days: int = 0, 
                                          total_gb: int = 0) -> Tuple[bool, str, Optional[Dict]]:
        """
        Create a client on the specified panel.
        For Marzban/Rebecca: Creates a user with access to all inbounds of the specified protocol.
        For 3x-ui: Creates a client on the first available/matching inbound.
        """
        try:
            manager = self.get_panel_manager(panel_id)
            if not manager:
                return False, "Panel manager could not be initialized", None
            
            if not manager.login():
                return False, "Login failed", None
            
            # Determine panel type and handle accordingly
            if isinstance(manager, (MarzbanPanelManager, RebeccaPanelManager, MarzneshinPanelManager)):
                # For Rebecca/Marzban/Marzneshin, we should use the Main Service (default_inbound_id)
                # Fetch panel details to get default_inbound_id
                panel = self.db.get_panel(panel_id)
                main_service_id = panel.get('default_inbound_id') if panel else 0
                
                if isinstance(manager, RebeccaPanelManager) and not main_service_id:
                    logger.warning(f"⚠️ No Main Service (default_inbound_id) selected for Rebecca panel {panel_id}. Client might be created without specific service.")

                client = manager.create_client(
                    inbound_id=main_service_id,  # Pass Main Service ID
                    client_name=client_name,
                    protocol=protocol,
                    expire_days=expire_days,
                    total_gb=total_gb
                )
                if client:
                    # Add extra info for consistency
                    client['created_on_inbounds'] = 1 # Simplified
                    return True, "Client created successfully", client
                else:
                    return False, "Failed to create client on panel", None
            
            else:
                # 3x-ui Panel
                # We need to find a suitable inbound since one wasn't specified
                inbounds = manager.get_inbounds()
                if not inbounds:
                    return False, "No inbounds found on panel", None
                
                target_inbound = None
                
                # 1. Try to find inbound matching requested protocol
                for inbound in inbounds:
                    if inbound.get('enable', True) and inbound.get('protocol') == protocol:
                        target_inbound = inbound
                        break
                
                # 2. If not found, try to find any vless inbound (preferred)
                if not target_inbound and protocol != 'vless':
                    for inbound in inbounds:
                        if inbound.get('enable', True) and inbound.get('protocol') == 'vless':
                            target_inbound = inbound
                            break
                            
                # 3. If still not found, just pick the first enabled inbound
                if not target_inbound:
                    for inbound in inbounds:
                        if inbound.get('enable', True):
                            target_inbound = inbound
                            break
                            
                if not target_inbound:
                    return False, "No active inbounds found on panel", None
                
                # Create client on the selected inbound
                client = manager.create_client(
                    inbound_id=target_inbound['id'],
                    client_name=client_name,
                    protocol=target_inbound['protocol'], # Use inbound's actual protocol
                    expire_days=expire_days,
                    total_gb=total_gb
                )
                
                if client:
                    client['created_on_inbounds'] = 1
                    return True, "Client created successfully", client
                else:
                    return False, "Failed to create client on 3x-ui panel", None
                    
        except Exception as e:
            logger.error(f"Error in create_client_on_all_panel_inbounds: {e}")
            return False, f"System error: {str(e)}", None

    def migrate_panel(self, source_panel_id: int, dest_panel_id: int, delete_source: bool) -> Tuple[bool, str, Dict]:
        """
        Migrate all clients from a source panel to a destination panel.
        """
        try:
            source_panel_mgr = self.get_panel_manager(source_panel_id)
            dest_panel_mgr = self.get_panel_manager(dest_panel_id)

            if not source_panel_mgr:
                return False, f"Source panel manager not found for ID {source_panel_id}", {}
            if not dest_panel_mgr:
                return False, f"Destination panel manager not found for ID {dest_panel_id}", {}

            # Get all clients from the source panel
            source_clients = source_panel_mgr.get_all_clients()
            if source_clients is None: # Check for None explicitly, as empty list is valid
                return False, "Failed to retrieve clients from source panel.", {}

            success_count = 0
            failed_count = 0
            skipped_count = 0
            deleted_source_count = 0
            migration_details = []

            for client in source_clients:
                try:
                    client_name = client.get('username')
                    client_uuid = client.get('uuid') or client_name # Fallback to username if uuid is missing (Marzban)
                    protocol = client.get('protocol', 'vless')
                    
                    # Calculate remaining volume
                    total_bytes = client.get('total_traffic', 0)
                    used_bytes = client.get('used_traffic', 0)
                    remaining_bytes = max(0, total_bytes - used_bytes)
                    remaining_gb = remaining_bytes / (1024 * 1024 * 1024)
                    
                    # Get remaining days
                    expire_days = client.get('expire_days', 0)
                    
                    if not client_name:
                        skipped_count += 1
                        migration_details.append(f"Skipped client with no identifiable name.")
                        continue

                    # Create client on the destination panel
                    # We use remaining volume and duration
                    created_client = dest_panel_mgr.create_client(
                        inbound_id=0, # Placeholder for panels that don't use inbound_id directly
                        client_name=client_name,
                        protocol=protocol,
                        expire_days=expire_days,
                        total_gb=remaining_gb,
                        sub_id=client.get('sub_id') # Pass sub_id if available
                    )

                    if created_client:
                        success_count += 1
                        migration_details.append(f"Migrated {client_name} ({protocol}) successfully. Remaining: {remaining_gb:.2f}GB, {expire_days} days.")

                        # Update database
                        if self.db:
                            self.db.update_client_panel(client_uuid, dest_panel_id, created_client)

                        # If migration is successful and delete_source is true, delete from source
                        if delete_source:
                            inbound_id = client.get('inbound_id', 0)
                            # Use source_panel_mgr to delete!
                            if source_panel_mgr.delete_client(inbound_id, client_uuid):
                                deleted_source_count += 1
                                migration_details.append(f"Deleted {client_name} from source panel.")
                            else:
                                migration_details.append(f"Failed to delete {client_name} from source panel.")
                    else:
                        failed_count += 1
                        migration_details.append(f"Failed to migrate {client_name} ({protocol}).")

                except Exception as e:
                    failed_count += 1
                    migration_details.append(f"Error migrating client {client.get('username', 'Unknown')}: {str(e)}")

            stats = {
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "deleted_source": deleted_source_count,
                "details": migration_details
            }

            message = f"Migration complete. Success: {success_count}, Failed: {failed_count}, Skipped: {skipped_count}"
            return True, message, stats

        except Exception as e:
            logger.error(f"Error during panel migration: {e}")
            return False, f"An error occurred during migration: {str(e)}", {}

    def sync_panel_inbounds_to_db(self, panel_id: int) -> Tuple[bool, str]:
        """Sync inbounds from panel API to database"""
        try:
            manager = self.get_panel_manager(panel_id)
            if not manager:
                return False, "Panel manager could not be initialized"
            
            if not manager.login():
                return False, "Login failed"
            
            inbounds = manager.get_inbounds()
            if not inbounds:
                return False, "No inbounds found on panel"
            
            count = 0
            for inbound in inbounds:
                # Extract details based on panel type structure
                # 3x-ui structure: {'id': 1, 'remark': 'name', 'protocol': 'vless', 'port': 443, 'enable': True}
                inbound_id = inbound.get('id')
                name = inbound.get('remark') or inbound.get('tag') or f"Inbound {inbound_id}"
                protocol = inbound.get('protocol')
                port = inbound.get('port')
                is_enabled = inbound.get('enable', True)
                
                if self.db.add_panel_inbound(panel_id, inbound_id, name, protocol, port, is_enabled):
                    count += 1
            
            return True, f"Successfully synced {count} inbounds"
            
        except Exception as e:
            logger.error(f"Error syncing inbounds: {e}")
            return False, f"Error syncing inbounds: {str(e)}"

    def get_panel_inbounds_with_status(self, panel_id: int) -> List[Dict]:
        """Get inbounds with their DB status"""
        # First try to get from DB
        stored_inbounds = self.db.get_stored_panel_inbounds(panel_id)
        
        # If empty, try to sync first
        if not stored_inbounds:
            self.sync_panel_inbounds_to_db(panel_id)
            stored_inbounds = self.db.get_stored_panel_inbounds(panel_id)
            
        # Format for display
        result = []
        panel = self.db.get_panel(panel_id)
        default_inbound_id = panel.get('default_inbound_id') if panel else 0
        
        for inbound in stored_inbounds:
            result.append({
                'id': inbound['inbound_id'],
                'name': inbound['inbound_name'],
                'protocol': inbound['inbound_protocol'],
                'port': inbound['inbound_port'],
                'is_enabled': inbound['is_enabled'] == 1,
                'is_main': inbound['inbound_id'] == default_inbound_id
            })
            
        return result

    def set_inbound_enabled_status(self, panel_id: int, inbound_id: int, is_enabled: bool) -> Tuple[bool, str]:
        """Set inbound enabled status in DB"""
        if self.db.update_panel_inbound_status(panel_id, inbound_id, is_enabled):
            status_str = "enabled" if is_enabled else "disabled"
            return True, f"Inbound {status_str} successfully"
        return False, "Failed to update inbound status"

    def change_panel_main_inbound(self, panel_id: int, inbound_id: int) -> Tuple[bool, str]:
        """Change the main inbound for a panel"""
        try:
            # Verify inbound exists and is enabled
            inbound = self.db.get_panel_inbound(panel_id, inbound_id)
            if not inbound:
                return False, "Inbound not found"
            
            if not inbound['is_enabled']:
                return False, "Cannot set disabled inbound as main"
            
            # Update panel
            if self.db.update_panel(panel_id, default_inbound_id=inbound_id):
                return True, "Main inbound updated successfully"
            return False, "Failed to update panel"
            
        except Exception as e:
            logger.error(f"Error changing main inbound: {e}")
            return False, f"Error: {str(e)}"


    def add_panel(self, name: str, url: str, username: str, password: str, 
                  api_endpoint: str, default_inbound_id: int = None, price_per_gb: int = 0,
                  subscription_url: str = None, panel_type: str = '3x-ui', default_protocol: str = 'vless',
                  sale_type: str = 'gigabyte', extra_config: dict = None) -> Tuple[bool, str]:
        """Add a new panel"""
        try:
            # Test connection first
            manager = None
            if panel_type == 'marzban':
                manager = MarzbanPanelManager()
            elif panel_type == 'rebecca':
                manager = RebeccaPanelManager()
            elif panel_type == 'pasargad':
                manager = PasargadPanelManager()
            elif panel_type == 'marzneshin':
                manager = MarzneshinPanelManager()
            else:
                manager = PanelManager()
                
            manager.base_url = api_endpoint or url
            manager.username = username
            manager.password = password
            
            if not manager.login():
                return False, "❌ خطا در اتصال به پنل (نام کاربری/رمز عبور یا آدرس اشتباه است)"
                
            # Add to database
            panel_id = self.db.add_panel(
                name=name,
                url=url,
                username=username,
                password=password,
                api_endpoint=api_endpoint,
                default_inbound_id=default_inbound_id,
                price_per_gb=price_per_gb,
                subscription_url=subscription_url,
                panel_type=panel_type,
                default_protocol=default_protocol,
                sale_type=sale_type,
                extra_config=extra_config
            )
            
            if panel_id:
                # Sync inbounds
                self.sync_panel_inbounds_to_db(panel_id)
                return True, "✅ پنل با موفقیت اضافه شد"
            else:
                return False, "❌ خطا در ذخیره پنل در دیتابیس"
                
        except Exception as e:
            logger.error(f"Error adding panel: {e}")
            return False, f"❌ خطای سیستمی: {str(e)}"

    def update_panel(self, panel_id: int, name: str = None, url: str = None,
                     username: str = None, password: str = None, 
                     api_endpoint: str = None, price_per_gb: int = None,
                     subscription_url: str = None, panel_type: str = None, default_protocol: str = None,
                     sale_type: str = None, default_inbound_id: int = None, extra_config: dict = None) -> Tuple[bool, str]:
        """Update panel information"""
        try:
            # If credentials changing, test connection
            if url or username or password:
                # Get current details to merge
                current_panel = self.db.get_panel(panel_id)
                if not current_panel:
                    return False, "Panel not found"
                    
                test_url = api_endpoint or url or current_panel.get('api_endpoint') or current_panel.get('url')
                test_username = username or current_panel.get('username')
                test_password = password or current_panel.get('password')
                test_type = panel_type or current_panel.get('panel_type', '3x-ui')
                
                manager = None
                if test_type == 'marzban':
                    manager = MarzbanPanelManager()
                elif test_type == 'rebecca':
                    manager = RebeccaPanelManager()
                elif test_type == 'pasargad':
                    manager = PasargadPanelManager()
                elif test_type == 'marzneshin':
                    manager = MarzneshinPanelManager()
                else:
                    manager = PanelManager()
                    
                manager.base_url = test_url
                manager.username = test_username
                manager.password = test_password
                
                if not manager.login():
                    return False, "❌ خطا در اتصال به پنل با مشخصات جدید"

            if self.db.update_panel(
                panel_id=panel_id,
                name=name,
                url=url,
                username=username,
                password=password,
                api_endpoint=api_endpoint,
                price_per_gb=price_per_gb,
                subscription_url=subscription_url,
                panel_type=panel_type,
                default_protocol=default_protocol,
                sale_type=sale_type,
                default_inbound_id=default_inbound_id,
                extra_config=extra_config
            ):
                return True, "✅ پنل با موفقیت ویرایش شد"
            else:
                return False, "❌ خطا در ویرایش پنل"
                
        except Exception as e:
            logger.error(f"Error updating panel: {e}")
            return False, f"❌ خطای سیستمی: {str(e)}"
