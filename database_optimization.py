"""
Database Query Optimization
Adds indexes and optimizes frequently used queries
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

def create_database_indexes(db_manager):
    """
    Create database indexes for better query performance
    
    This should be called once during database initialization
    """
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Indexes for users table
            indexes = [
                # Users table indexes
                "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)",
                "CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)",
                "CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)",
                "CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin)",
                "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)",
                
                # Clients table indexes
                "CREATE INDEX IF NOT EXISTS idx_clients_user_id ON clients(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_clients_panel_id ON clients(panel_id)",
                "CREATE INDEX IF NOT EXISTS idx_clients_is_active ON clients(is_active)",
                "CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status)",
                "CREATE INDEX IF NOT EXISTS idx_clients_created_at ON clients(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_clients_expires_at ON clients(expires_at)",
                
                # Invoices table indexes
                "CREATE INDEX IF NOT EXISTS idx_invoices_user_id ON invoices(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_panel_id ON invoices(panel_id)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_order_id ON invoices(order_id)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_created_at ON invoices(created_at)",
                
                # Panels table indexes
                "CREATE INDEX IF NOT EXISTS idx_panels_is_active ON panels(is_active)",
                "CREATE INDEX IF NOT EXISTS idx_panels_panel_type ON panels(panel_type)",
                
                # Products table indexes
                "CREATE INDEX IF NOT EXISTS idx_products_panel_id ON products(panel_id)",
                "CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id)",
                "CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active)",
                
                # Balance transactions indexes
                "CREATE INDEX IF NOT EXISTS idx_balance_transactions_user_id ON balance_transactions(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_balance_transactions_type ON balance_transactions(transaction_type)",
                "CREATE INDEX IF NOT EXISTS idx_balance_transactions_created_at ON balance_transactions(created_at)",
                
                # Discount codes indexes
                "CREATE INDEX IF NOT EXISTS idx_discount_codes_code ON discount_codes(code)",
                "CREATE INDEX IF NOT EXISTS idx_discount_codes_is_active ON discount_codes(is_active)",
                
                # Gift codes indexes
                "CREATE INDEX IF NOT EXISTS idx_gift_codes_code ON gift_codes(code)",
                "CREATE INDEX IF NOT EXISTS idx_gift_codes_is_active ON gift_codes(is_active)",
            ]
            
            for index_sql in indexes:
                try:
                    cursor.execute(index_sql)
                    logger.info(f"Created index: {index_sql[:50]}...")
                except Exception as e:
                    # Index might already exist, ignore error
                    logger.debug(f"Index creation skipped (might exist): {e}")
            
            conn.commit()
            logger.info("✅ Database indexes created successfully")
            
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")
        # Don't raise - indexes are optional optimizations

def optimize_user_query(db_manager, user_id: int) -> Optional[Dict]:
    """
    Optimized user query - returns only essential fields
    """
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT id, telegram_id, username, first_name, last_name, 
                       balance, is_admin, referral_code, created_at, last_activity
                FROM users 
                WHERE telegram_id = %s
                LIMIT 1
            ''', (user_id,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Error in optimized user query: {e}")
        return None

def optimize_services_query(db_manager, user_id: int, limit: Optional[int] = None) -> List[Dict]:
    """
    Optimized services query - returns only essential fields with JOIN
    """
    try:
        user = db_manager.get_user(user_id)
        if not user:
            return []
        
        db_user_id = user['id']
        
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            query = '''
                SELECT c.id, c.client_name, c.client_uuid, c.inbound_id, 
                       c.protocol, c.total_gb, c.expire_days, c.expires_at,
                       c.cached_used_gb as used_gb, c.cached_is_online as is_online,
                       c.cached_last_activity as last_activity, c.sub_id,
                       c.config_link, c.is_active, c.status,
                       p.name as panel_name, p.panel_type
                FROM clients c
                LEFT JOIN panels p ON c.panel_id = p.id
                WHERE c.user_id = %s AND c.is_active = 1
                ORDER BY c.created_at DESC
            '''
            # SECURITY: Validate and use parameterized query for LIMIT
            if limit:
                # Validate limit is a positive integer
                try:
                    limit_int = int(limit)
                    if limit_int > 0 and limit_int <= 1000:  # Max limit
                        query += ' LIMIT %s'
                        cursor.execute(query, (db_user_id, limit_int))
                    else:
                        cursor.execute(query, (db_user_id,))
                except (ValueError, TypeError):
                    cursor.execute(query, (db_user_id,))
            else:
                cursor.execute(query, (db_user_id,))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error in optimized services query: {e}")
        return []

