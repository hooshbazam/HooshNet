"""
Database Restore System for VPN Bot
Handles COMPLETE restoration of backups from HooshNet and Mirza Pro
Restores ALL tables: users, panels, clients, invoices, transactions, codes, tickets, settings
"""

import logging
import os
import gzip
import shutil
import re
import mysql.connector
from mysql.connector import Error
from typing import Optional, Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseRestoreManager:
    """Manager for restoring database backups - COMPLETE restore of all tables"""
    
    # All HooshNet tables in dependency order
    HOOSHNET_TABLES = [
        'users',
        'panels', 
        'panel_inbounds',
        'clients',
        'products',
        'invoices',
        'balance_transactions',
        'discount_codes',
        'gift_codes',
        'discount_code_usage',
        'gift_code_usage',
        'referrals',
        'tickets',
        'ticket_replies',
        'settings',
        'bot_texts',
        'system_logs',
        'database_migrations'
    ]
    
    # Mirza Pro to HooshNet table mapping
    MIRZA_TABLE_MAPPING = {
        'user': 'users',
        'marzban_panel': 'panels',
        'product': 'products',
        'invoice': 'invoices',
        'Payment_report': 'balance_transactions',
        'Discount': 'discount_codes',
        'Giftcodeconsumed': 'gift_code_usage'
    }
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.db_config = db_manager.db_config
        self.main_db_name = self.db_config.get('database', 'vpn_bot')
        self.restore_stats = {}
        
    def _decompress_if_needed(self, backup_path: str) -> Optional[str]:
        """Decompress gzipped backup if needed, returns path to SQL file"""
        if backup_path.endswith('.gz'):
            sql_path = backup_path[:-3]
            try:
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(sql_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                return sql_path
            except Exception as e:
                logger.error(f"❌ Error decompressing backup: {e}")
                return None
        return backup_path

    def _detect_schema_from_file(self, sql_path: str) -> str:
        """Detect schema type by reading the SQL file"""
        try:
            with open(sql_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(100000).lower()
                
                # Check for HooshNet tables
                if '`users`' in content and '`panels`' in content and '`telegram_id`' in content:
                    return 'hooshnet'
                elif 'users' in content and 'panels' in content and 'telegram_id' in content:
                    return 'hooshnet'
                    
                # Check for WizWiz tables
                elif '`server_plans`' in content and '`server_config`' in content:
                    return 'wizwiz'
                elif 'server_plans' in content and 'server_config' in content and '`pays`' in content:
                    return 'wizwiz'
                
                # Check for Mirza tables
                elif '`user`' in content and '`marzban_panel`' in content:
                    return 'mirza'
                elif 'payment_report' in content and 'paysetting' in content:
                    return 'mirza'
                elif ' user ' in content and 'marzban_panel' in content:
                    return 'mirza'
                
                return 'unknown'
        except Exception as e:
            logger.error(f"❌ Error detecting schema: {e}")
            return 'error'

    def _extract_table_data(self, sql_content: str, table_name: str) -> List[Dict]:
        """Extract all INSERT data for a specific table from SQL content"""
        records = []
        
        # Pattern to match INSERT statements
        # Handles: INSERT INTO `table`, INSERT INTO table, INSERT IGNORE, etc.
        patterns = [
            rf"INSERT\s+(?:IGNORE\s+)?INTO\s+`?{table_name}`?\s*\(([^)]+)\)\s*VALUES\s*([^;]+);",
            rf"INSERT\s+(?:IGNORE\s+)?INTO\s+`?{table_name}`?\s+VALUES\s*([^;]+);"
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, sql_content, re.IGNORECASE | re.DOTALL)
            
            for match in matches:
                try:
                    if match.lastindex == 2:
                        # Has column names
                        columns = [c.strip().strip('`').strip("'").strip('"') for c in match.group(1).split(',')]
                        values_str = match.group(2)
                    else:
                        # No column names - skip for safety
                        continue
                    
                    # Parse multiple value sets
                    value_sets = self._parse_value_sets(values_str)
                    
                    for values in value_sets:
                        if len(values) == len(columns):
                            record = dict(zip(columns, values))
                            records.append(record)
                except Exception as e:
                    logger.debug(f"Error parsing INSERT for {table_name}: {e}")
                    continue
                        
        return records

    def _parse_value_sets(self, values_str: str) -> List[List]:
        """Parse multiple value sets from VALUES clause"""
        value_sets = []
        current_set = []
        current_value = ''
        in_quotes = False
        quote_char = None
        paren_depth = 0
        escaped = False
        
        i = 0
        while i < len(values_str):
            char = values_str[i]
            
            if escaped:
                current_value += char
                escaped = False
                i += 1
                continue
                
            if char == '\\':
                escaped = True
                current_value += char
                i += 1
                continue
            
            if char in ["'", '"'] and not in_quotes:
                in_quotes = True
                quote_char = char
                current_value += char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
                current_value += char
            elif char == '(' and not in_quotes:
                if paren_depth == 0:
                    current_set = []
                    current_value = ''
                else:
                    current_value += char
                paren_depth += 1
            elif char == ')' and not in_quotes:
                paren_depth -= 1
                if paren_depth == 0:
                    if current_value.strip():
                        current_set.append(self._clean_value(current_value.strip()))
                    if current_set:
                        value_sets.append(current_set)
                    current_set = []
                    current_value = ''
                else:
                    current_value += char
            elif char == ',' and not in_quotes:
                if paren_depth == 1:
                    current_set.append(self._clean_value(current_value.strip()))
                    current_value = ''
                elif paren_depth > 1:
                    current_value += char
            else:
                if paren_depth > 0:
                    current_value += char
            
            i += 1
        
        return value_sets

    def _clean_value(self, value: str):
        """Clean and convert a parsed value"""
        if not value:
            return None
        if value.upper() == 'NULL':
            return None
        # Remove quotes
        if (value.startswith("'") and value.endswith("'")) or \
           (value.startswith('"') and value.endswith('"')):
            return value[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\r", "\r")
        # Try numeric
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except:
            return value

    def _restore_table(self, cursor, table_name: str, records: List[Dict], column_mapping: Dict = None) -> int:
        """Restore records to a table with INSERT IGNORE"""
        if not records:
            return 0
            
        count = 0
        for record in records:
            try:
                # Apply column mapping if provided
                if column_mapping:
                    mapped_record = {}
                    for old_col, new_col in column_mapping.items():
                        if old_col in record:
                            mapped_record[new_col] = record[old_col]
                    record = mapped_record
                
                if not record:
                    continue
                
                columns = list(record.keys())
                values = list(record.values())
                
                # Build INSERT IGNORE query
                placeholders = ', '.join(['%s'] * len(columns))
                columns_str = ', '.join([f'`{c}`' for c in columns])
                
                query = f"INSERT IGNORE INTO `{table_name}` ({columns_str}) VALUES ({placeholders})"
                
                cursor.execute(query, values)
                if cursor.rowcount > 0:
                    count += 1
                    
            except Exception as e:
                logger.debug(f"Skip record in {table_name}: {e}")
                continue
                
        return count

    def _restore_hooshnet(self, sql_content: str) -> Tuple[bool, str]:
        """Restore HooshNet backup - ALL tables"""
        try:
            self.restore_stats = {}
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Disable foreign key checks temporarily
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                
                for table_name in self.HOOSHNET_TABLES:
                    try:
                        records = self._extract_table_data(sql_content, table_name)
                        if records:
                            count = self._restore_table(cursor, table_name, records)
                            self.restore_stats[table_name] = count
                            logger.info(f"✅ Restored {count} records to {table_name}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not restore {table_name}: {e}")
                        self.restore_stats[table_name] = 0
                
                # Re-enable foreign key checks
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                
                conn.commit()
            
            # Build result message
            return True, self._build_result_message("هوش‌نت")
            
        except Exception as e:
            logger.error(f"❌ Error restoring HooshNet: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"❌ خطا در بازگردانی: {str(e)}"

    def _restore_mirza(self, sql_content: str) -> Tuple[bool, str]:
        """Restore Mirza Pro backup with schema migration"""
        try:
            self.restore_stats = {}
            
            # Column mappings for Mirza -> HooshNet
            user_mapping = {
                'id': 'telegram_id',
                'username': 'username',
                'Balance': 'balance',
                'User_Status': 'is_active'
            }
            
            panel_mapping = {
                'name_panel': 'name',
                'url_panel': 'url',
                'username_panel': 'username',
                'password_panel': 'password',
                'type': 'panel_type'
            }
            
            product_mapping = {
                'name_product': 'name',
                'price_product': 'price',
                'Volume_constraint': 'volume_gb',
                'Service_time': 'duration_days'
            }
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                
                # Restore users
                users = self._extract_table_data(sql_content, 'user')
                for user in users:
                    user_id = user.get('id')
                    if user_id and str(user_id).isdigit():
                        user['id'] = int(user_id)
                count = self._restore_table(cursor, 'users', users, user_mapping)
                self.restore_stats['users'] = count
                
                # Restore panels
                panels = self._extract_table_data(sql_content, 'marzban_panel')
                for panel in panels:
                    panel['api_endpoint'] = panel.get('url_panel', '')
                    panel['is_active'] = 1
                count = self._restore_table(cursor, 'panels', panels, panel_mapping)
                self.restore_stats['panels'] = count
                
                # Restore products
                products = self._extract_table_data(sql_content, 'product')
                for product in products:
                    product['is_active'] = 1
                    product['panel_id'] = 1  # Default panel
                    product['is_visible_to_users'] = 1
                    product['is_visible_to_resellers'] = 1
                count = self._restore_table(cursor, 'products', products, product_mapping)
                self.restore_stats['products'] = count
                
                # Restore invoices
                invoices = self._extract_table_data(sql_content, 'invoice')
                invoice_mapping = {
                    'id_user': 'user_id',
                    'Amount': 'amount',
                    'status': 'status'
                }
                count = self._restore_table(cursor, 'invoices', invoices, invoice_mapping)
                self.restore_stats['invoices'] = count
                
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                conn.commit()
            
            return True, self._build_result_message("میرزا پرو")
            
        except Exception as e:
            logger.error(f"❌ Error restoring Mirza: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"❌ خطا در مهاجرت: {str(e)}"

    def _restore_wizwiz(self, sql_content: str) -> Tuple[bool, str]:
        """Restore WizWiz backup with schema migration"""
        try:
            self.restore_stats = {}
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                
                # === USERS ===
                # WizWiz users table: userid (telegram_id), name, username, wallet (balance), refcode, date, phone, refered_by
                users = self._extract_table_data(sql_content, 'users')
                user_count = 0
                for user in users:
                    try:
                        telegram_id = user.get('userid')
                        if not telegram_id or not str(telegram_id).isdigit():
                            continue
                        
                        # Map WizWiz fields to HooshNet
                        name = user.get('name', '') or ''
                        first_name = name.split()[0] if name else ''
                        last_name = ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''
                        
                        cursor.execute("""
                            INSERT IGNORE INTO users 
                            (telegram_id, username, first_name, last_name, balance, is_active, created_at)
                            VALUES (%s, %s, %s, %s, %s, 1, NOW())
                        """, (
                            int(telegram_id),
                            user.get('username', ''),
                            first_name,
                            last_name,
                            int(user.get('wallet', 0) or 0)
                        ))
                        if cursor.rowcount > 0:
                            user_count += 1
                    except Exception as e:
                        logger.debug(f"Skip WizWiz user: {e}")
                        continue
                
                self.restore_stats['users'] = user_count
                logger.info(f"✅ Restored {user_count} WizWiz users")
                
                # === PAYMENTS (pays table) -> balance_transactions ===
                # WizWiz pays: hash_id, user_id, type, price, tron_price, request_date, state
                pays = self._extract_table_data(sql_content, 'pays')
                pay_count = 0
                for pay in pays:
                    try:
                        user_id = pay.get('user_id')
                        if not user_id:
                            continue
                        
                        # Get internal user id from telegram_id
                        cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (int(user_id),))
                        result = cursor.fetchone()
                        if not result:
                            continue
                        
                        internal_user_id = result[0]
                        amount = int(pay.get('price', 0) or 0)
                        pay_type = pay.get('type', 'payment')
                        state = pay.get('state', 'pending')
                        
                        # Only import paid transactions
                        if state and state.lower() in ['paid', 'success', 'completed']:
                            cursor.execute("""
                                INSERT IGNORE INTO balance_transactions 
                                (user_id, amount, transaction_type, description, reference_id, created_at)
                                VALUES (%s, %s, %s, %s, %s, NOW())
                            """, (
                                internal_user_id,
                                amount,
                                'deposit' if amount > 0 else 'purchase',
                                f'مهاجرت از WizWiz - نوع: {pay_type}',
                                pay.get('hash_id', '')
                            ))
                            if cursor.rowcount > 0:
                                pay_count += 1
                    except Exception as e:
                        logger.debug(f"Skip WizWiz pay: {e}")
                        continue
                
                self.restore_stats['balance_transactions'] = pay_count
                logger.info(f"✅ Restored {pay_count} WizWiz payments")
                
                # === PANELS (server_config) ===
                # WizWiz server_config: panel_url, username, password, type
                server_configs = self._extract_table_data(sql_content, 'server_config')
                panel_count = 0
                for config in server_configs:
                    try:
                        panel_url = config.get('panel_url', '')
                        if not panel_url:
                            continue
                        
                        cursor.execute("""
                            INSERT IGNORE INTO panels 
                            (name, url, api_endpoint, username, password, panel_type, is_active, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, 1, NOW())
                        """, (
                            config.get('type', 'پنل WizWiz'),
                            panel_url,
                            panel_url,
                            config.get('username', ''),
                            config.get('password', ''),
                            config.get('type', '3x-ui')
                        ))
                        if cursor.rowcount > 0:
                            panel_count += 1
                    except Exception as e:
                        logger.debug(f"Skip WizWiz panel: {e}")
                        continue
                
                self.restore_stats['panels'] = panel_count
                logger.info(f"✅ Restored {panel_count} WizWiz panels")
                
                # === PRODUCTS (server_plans) ===
                # WizWiz server_plans: title, price, days, volume, protocol, server_id
                plans = self._extract_table_data(sql_content, 'server_plans')
                product_count = 0
                for plan in plans:
                    try:
                        title = plan.get('title', '')
                        price = int(plan.get('price', 0) or 0)
                        if not title or price <= 0:
                            continue
                        
                        # Get first panel id or use 1
                        cursor.execute("SELECT id FROM panels ORDER BY id LIMIT 1")
                        result = cursor.fetchone()
                        panel_id = result[0] if result else 1
                        
                        cursor.execute("""
                            INSERT IGNORE INTO products 
                            (panel_id, name, volume_gb, duration_days, price, is_active, created_at, is_visible_to_users, is_visible_to_resellers)
                            VALUES (%s, %s, %s, %s, %s, 1, NOW(), 1, 1)
                        """, (
                            panel_id,
                            title,
                            int(float(plan.get('volume', 0) or 0)),
                            int(float(plan.get('days', 30) or 30)),
                            price
                        ))
                        if cursor.rowcount > 0:
                            product_count += 1
                    except Exception as e:
                        logger.debug(f"Skip WizWiz plan: {e}")
                        continue
                
                self.restore_stats['products'] = product_count
                logger.info(f"✅ Restored {product_count} WizWiz products")
                
                # === DISCOUNTS ===
                # WizWiz discounts: hash_id, type, amount, expire_date, expire_count
                discounts = self._extract_table_data(sql_content, 'discounts')
                discount_count = 0
                for discount in discounts:
                    try:
                        code = discount.get('hash_id', '')
                        if not code:
                            continue
                        
                        discount_type = discount.get('type', 'percentage')
                        amount = int(discount.get('amount', 0) or 0)
                        
                        cursor.execute("""
                            INSERT IGNORE INTO discount_codes 
                            (code, code_type, discount_type, discount_value, max_uses, is_active, created_at)
                            VALUES (%s, 'discount', %s, %s, %s, 1, NOW())
                        """, (
                            code,
                            'percentage' if discount_type == 'percent' else 'fixed',
                            amount,
                            int(discount.get('expire_count', 0) or 0)
                        ))
                        if cursor.rowcount > 0:
                            discount_count += 1
                    except Exception as e:
                        logger.debug(f"Skip WizWiz discount: {e}")
                        continue
                
                self.restore_stats['discount_codes'] = discount_count
                logger.info(f"✅ Restored {discount_count} WizWiz discounts")
                
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                conn.commit()
            
            return True, self._build_result_message("ویزویز")
            
        except Exception as e:
            logger.error(f"❌ Error restoring WizWiz: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"❌ خطا در مهاجرت WizWiz: {str(e)}"

    def _build_result_message(self, source_name: str) -> str:
        """Build a detailed result message"""
        total = sum(self.restore_stats.values())
        
        msg = f"✅ **بازگردانی {source_name} کامل شد**\n\n"
        msg += f"📊 **آمار کل:** {total:,} رکورد\n\n"
        msg += "📋 **جزئیات:**\n"
        
        # Group stats by category
        categories = {
            '👥 کاربران': ['users', 'referrals'],
            '🖥️ پنل‌ها': ['panels', 'panel_inbounds'],
            '🔌 سرویس‌ها': ['clients', 'products'],
            '💰 مالی': ['invoices', 'balance_transactions'],
            '🎁 کدها': ['discount_codes', 'gift_codes', 'discount_code_usage', 'gift_code_usage'],
            '🎫 تیکت‌ها': ['tickets', 'ticket_replies'],
            '⚙️ تنظیمات': ['settings', 'bot_texts']
        }
        
        for category, tables in categories.items():
            cat_total = sum(self.restore_stats.get(t, 0) for t in tables)
            if cat_total > 0:
                msg += f"\n{category}: {cat_total:,}\n"
                for t in tables:
                    count = self.restore_stats.get(t, 0)
                    if count > 0:
                        msg += f"  • {t}: {count:,}\n"
        
        return msg

    def restore_backup(self, file_path: str) -> str:
        """Main restore function - COMPLETE restore of all data"""
        sql_path = None
        is_decompressed = False
        
        try:
            # Decompress if needed
            sql_path = self._decompress_if_needed(file_path)
            if not sql_path:
                return "❌ خطا در خواندن فایل بکاپ."
            
            is_decompressed = sql_path != file_path
            
            # Read entire SQL content
            with open(sql_path, 'r', encoding='utf-8', errors='ignore') as f:
                sql_content = f.read()
            
            # Detect Schema
            schema_type = self._detect_schema_from_file(sql_path)
            logger.info(f"🔍 Detected schema: {schema_type}")
            
            if schema_type == 'hooshnet':
                success, msg = self._restore_hooshnet(sql_content)
            elif schema_type == 'mirza':
                success, msg = self._restore_mirza(sql_content)
            elif schema_type == 'wizwiz':
                success, msg = self._restore_wizwiz(sql_content)
            elif schema_type == 'unknown':
                return "❌ ساختار دیتابیس ناشناخته است.\n\nفایل باید شامل جداول:\n• users/panels (هوش‌نت)\n• user/marzban_panel (میرزا پرو)\n• server_plans/server_config (ویزویز)\n\nباشد."
            else:
                return "❌ خطا در تشخیص ساختار دیتابیس."
            
            return msg
            
        except Exception as e:
            logger.error(f"❌ Restore error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"❌ خطا در عملیات بازگردانی: {str(e)}"
        finally:
            # Clean up decompressed file
            if is_decompressed and sql_path and os.path.exists(sql_path):
                try:
                    os.remove(sql_path)
                except:
                    pass
