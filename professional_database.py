"""
Professional Database Management System for VPN Bot
Robust, persistent, and scalable database with proper error handling and migrations
MySQL Version
"""

import mysql.connector
from mysql.connector import Error, pooling
import json
import os
import shutil
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from contextlib import contextmanager
import threading
from config import MYSQL_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProfessionalDatabaseManager:
    """Professional database manager with robust error handling and persistence using MySQL"""
    
    # Store connection pools per database name
    _connection_pools = {}  # {database_name: connection_pool}
    _pool_lock = threading.Lock()
    
    def __init__(self, db_config: dict = None):
        self.db_config = db_config or MYSQL_CONFIG.copy()
        self.database_name = self.db_config.get('database', 'vpn_bot')
        # Log database name to ensure it's correct
        logger.debug(f"📊 ProfessionalDatabaseManager initialized with database_name: '{self.database_name}'")
        self.backup_dir = "database_backups"
        self.lock = threading.Lock()
        
        # Log database name for debugging
        logger.info(f"🔧 Initializing ProfessionalDatabaseManager for database: '{self.database_name}'")
        
        # Ensure backup directory exists
        os.makedirs(self.backup_dir, exist_ok=True)
        
        # Ensure database exists BEFORE initializing connection pool
        self._ensure_database_exists()
        
        # Initialize connection pool for this specific database
        self._init_connection_pool()
        
        # Initialize database schema
        self.init_database()
        
        # Seed default texts
        try:
            from text_manager import TextManager
            text_manager = TextManager(self)
            count = text_manager.initialize_default_texts()
            if count > 0:
                logger.info(f"✅ Seeded {count} default bot texts")
        except Exception as e:
            logger.error(f"❌ Error seeding default texts: {e}")
        
        # Verify connection pool is using correct database
        pool = ProfessionalDatabaseManager._connection_pools.get(self.database_name)
        if pool:
            logger.info(f"✅ Connection pool verified for database '{self.database_name}'")
        else:
            logger.error(f"❌ Connection pool NOT found for database '{self.database_name}'")
        
        # Create database indexes for optimization
        try:
            from database_optimization import create_database_indexes
            create_database_indexes(self)
        except ImportError:
            logger.warning("Database optimization module not available, skipping index creation")
        except Exception as e:
            logger.warning(f"Could not create database indexes: {e}")
    
    def _init_connection_pool(self):
        """Initialize MySQL connection pool for this specific database"""
        # Use database name as key to ensure separate pools per database
        if self.database_name not in ProfessionalDatabaseManager._connection_pools:
            with ProfessionalDatabaseManager._pool_lock:
                # Double-check after acquiring lock
                if self.database_name not in ProfessionalDatabaseManager._connection_pools:
                    try:
                        pool_config = {
                            'pool_name': f'vpn_bot_pool_{self.database_name}',  # Unique pool name per database
                            'pool_size': min(self.db_config.get('pool_size', 5), 5),  # Max 5 connections per pool
                            'pool_reset_session': self.db_config.get('pool_reset_session', True),
                            'host': self.db_config['host'],
                            'port': self.db_config['port'],
                            'user': self.db_config['user'],
                            'password': self.db_config['password'],
                            'database': self.database_name,  # Use specific database
                            'charset': self.db_config.get('charset', 'utf8mb4'),
                            'collation': self.db_config.get('collation', 'utf8mb4_unicode_ci'),
                            'autocommit': self.db_config.get('autocommit', False),
                            'buffered': self.db_config.get('buffered', True),
                            'raise_on_warnings': False  # Disable warnings for MySQL 9.x compatibility
                        }
                        pool = pooling.MySQLConnectionPool(**pool_config)
                        ProfessionalDatabaseManager._connection_pools[self.database_name] = pool
                        logger.info(f"MySQL connection pool initialized for database '{self.database_name}'")
                    except Error as e:
                        logger.error(f"Error initializing MySQL connection pool for database '{self.database_name}': {e}")
                        raise
        else:
            logger.debug(f"Using existing connection pool for database '{self.database_name}'")
    
    def _ensure_database_exists(self):
        """Ensure the database exists, create if it doesn't"""
        try:
            # Connect without database to create it if needed
            temp_config = self.db_config.copy()
            database_name = self.database_name  # Use the instance's database_name
            temp_config.pop('database', None)  # Remove database from config for connection
            
            conn = mysql.connector.connect(**temp_config)
            cursor = conn.cursor(dictionary=True)
            
            # Create database if it doesn't exist
            # SECURITY: Validate database name to prevent SQL injection
            # Only allow alphanumeric, underscore, and dash characters
            import re
            if not re.match(r'^[a-zA-Z0-9_\-]+$', database_name):
                raise ValueError(f"Invalid database name: {database_name}")
            # Use parameterized query with identifier escaping
            cursor.execute("CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci".format(
                database_name.replace('`', '``')  # Escape backticks
            ))
            cursor.close()
            conn.close()
            
            logger.info(f"Database '{database_name}' ensured to exist")
        except Error as e:
            logger.error(f"Error ensuring database exists: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections with proper error handling"""
        conn = None
        try:
            # Get connection from the pool for this specific database
            pool = ProfessionalDatabaseManager._connection_pools.get(self.database_name)
            if not pool:
                # Try to initialize connection pool if it doesn't exist
                logger.warning(f"⚠️ Connection pool not found for '{self.database_name}', attempting to initialize...")
                try:
                    self._init_connection_pool()
                    pool = ProfessionalDatabaseManager._connection_pools.get(self.database_name)
                    if not pool:
                        raise Error(f"Failed to initialize connection pool for database '{self.database_name}'. Available pools: {list(ProfessionalDatabaseManager._connection_pools.keys())}")
                    logger.info(f"✅ Connection pool initialized for database '{self.database_name}'")
                except Exception as e:
                    logger.error(f"❌ Error initializing connection pool for '{self.database_name}': {e}")
                    raise Error(f"No connection pool found for database '{self.database_name}' and failed to initialize: {e}. Available pools: {list(ProfessionalDatabaseManager._connection_pools.keys())}")
            conn = pool.get_connection()
            # Verify connection is using correct database
            cursor = conn.cursor()
            cursor.execute("SELECT DATABASE() as db")
            result = cursor.fetchone()
            actual_db = result[0] if result else None
            cursor.close()
            if actual_db != self.database_name:
                logger.error(f"❌ CRITICAL: Connection pool for '{self.database_name}' is connected to wrong database '{actual_db}'!")
                raise Error(f"Connection pool mismatch: expected '{self.database_name}', got '{actual_db}'")
            yield conn
        except Error as e:
            logger.error(f"Database error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def init_database(self):
        """Initialize database with comprehensive schema"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Create users table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        telegram_id BIGINT UNIQUE NOT NULL,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        last_name VARCHAR(255),
                        balance INT DEFAULT 0,
                        is_admin TINYINT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        is_banned TINYINT DEFAULT 0,
                        referred_by INT,
                        referral_code VARCHAR(255) UNIQUE,
                        total_referrals INT DEFAULT 0,
                        total_referral_earnings INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        last_login TIMESTAMP NULL,
                        total_spent INT DEFAULT 0,
                        total_services INT DEFAULT 0,
                        notes TEXT,
                        FOREIGN KEY (referred_by) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_telegram_id (telegram_id),
                        INDEX idx_is_banned (is_banned)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Add is_banned column if it doesn't exist (for existing databases)
                try:
                    cursor.execute('ALTER TABLE users ADD COLUMN is_banned TINYINT DEFAULT 0')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_is_banned ON users(is_banned)')
                except Exception as e:
                    # Column might already exist, ignore error
                    pass
                
                # Add has_used_test_account column if it doesn't exist
                try:
                    cursor.execute('ALTER TABLE users ADD COLUMN has_used_test_account TINYINT DEFAULT 0')
                except Exception as e:
                    pass
                
                # Create panels table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS panels (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) UNIQUE NOT NULL,
                        panel_type VARCHAR(50) DEFAULT '3x-ui',
                        url TEXT NOT NULL,
                        username VARCHAR(255) NOT NULL,
                        password VARCHAR(255) NOT NULL,
                        api_endpoint TEXT NOT NULL,
                        default_inbound_id INT,
                        price_per_gb INT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        last_checked TIMESTAMP NULL,
                        status VARCHAR(50) DEFAULT 'unknown',
                        subscription_url TEXT,
                        default_protocol VARCHAR(50) DEFAULT 'vless',
                        sale_type VARCHAR(50) DEFAULT 'gigabyte',
                        delivery_method VARCHAR(50) DEFAULT 'subscription_link',
                        extra_config JSON,
                        notes TEXT
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Add delivery_method column if it doesn't exist (migration)
                try:
                    cursor.execute("SHOW COLUMNS FROM panels LIKE 'delivery_method'")
                    if not cursor.fetchone():
                        cursor.execute("ALTER TABLE panels ADD COLUMN delivery_method VARCHAR(50) DEFAULT 'subscription_link'")
                        logger.info("✅ Added delivery_method column to panels table")
                except Exception as e:
                    logger.warning(f"⚠️ Error checking/adding delivery_method column: {e}")
                
                # Create panel_inbounds table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS panel_inbounds (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        panel_id INT NOT NULL,
                        inbound_id INT NOT NULL,
                        inbound_name VARCHAR(255),
                        inbound_protocol VARCHAR(50),
                        inbound_port INT,
                        is_enabled TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        INDEX idx_panel_id (panel_id),
                        INDEX idx_inbound_id (inbound_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create clients table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS clients (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        panel_id INT NOT NULL,
                        client_name VARCHAR(255) NOT NULL,
                        client_uuid VARCHAR(255) UNIQUE NOT NULL,
                        inbound_id INT NOT NULL,
                        protocol VARCHAR(50) NOT NULL,
                        expire_days INT DEFAULT 0,
                        total_gb DOUBLE DEFAULT 0,
                        used_gb DOUBLE DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP NULL,
                        last_used TIMESTAMP NULL,
                        config_link TEXT,
                        sub_id VARCHAR(255),
                        product_id INT,
                        status VARCHAR(50) DEFAULT 'active',
                        notified_70_percent TINYINT DEFAULT 0,
                        notified_80_percent TINYINT DEFAULT 0,
                        exhausted_at TIMESTAMP NULL,
                        warned_70_percent TINYINT DEFAULT 0,
                        warned_expired TINYINT DEFAULT 0,
                        warned_one_week TINYINT DEFAULT 0,
                        expired_at TIMESTAMP NULL,
                        deletion_grace_period_end TIMESTAMP NULL,
                        cached_used_gb DOUBLE DEFAULT 0,
                        cached_last_activity BIGINT DEFAULT 0,
                        last_activity BIGINT DEFAULT 0,
                        cached_is_online TINYINT DEFAULT 0,
                        cached_remaining_days INT DEFAULT 0,
                        data_last_synced TIMESTAMP NULL,
                        invoice_id INT,
                        notes TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_panel_id (panel_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Add invoice_id column to clients if it doesn't exist (migration)
                try:
                    cursor.execute("SHOW COLUMNS FROM clients LIKE 'invoice_id'")
                    if not cursor.fetchone():
                        cursor.execute("ALTER TABLE clients ADD COLUMN invoice_id INT")
                        cursor.execute("CREATE INDEX idx_invoice_id ON clients(invoice_id)")
                        logger.info("✅ Added invoice_id column to clients table")
                except Exception as e:
                    logger.warning(f"⚠️ Error checking/adding invoice_id column to clients: {e}")
                
                # Create invoices table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS invoices (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        panel_id INT NOT NULL,
                        gb_amount DOUBLE NOT NULL,
                        amount INT NOT NULL,
                        status VARCHAR(50) DEFAULT 'pending',
                        payment_method VARCHAR(50),
                        payment_link TEXT,
                        order_id VARCHAR(255) UNIQUE,
                        transaction_id VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        paid_at TIMESTAMP NULL,
                        expires_at TIMESTAMP NULL,
                        discount_code_id INT,
                        discount_amount INT DEFAULT 0,
                        original_amount INT,
                        product_id INT,
                        duration_days INT DEFAULT 0,
                        purchase_type VARCHAR(50) DEFAULT 'gigabyte',
                        receipt_path VARCHAR(500),
                        receipt_status VARCHAR(50) DEFAULT 'pending',
                        receipt_uploaded_at TIMESTAMP NULL,
                        notes TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_order_id (order_id),
                        INDEX idx_receipt_status (receipt_status)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Add receipt columns if they don't exist
                try:
                    cursor.execute('ALTER TABLE invoices ADD COLUMN receipt_path VARCHAR(500)')
                except Exception:
                    pass
                try:
                    cursor.execute('ALTER TABLE invoices ADD COLUMN receipt_status VARCHAR(50) DEFAULT "pending"')
                except Exception:
                    pass
                try:
                    cursor.execute('ALTER TABLE invoices ADD COLUMN receipt_uploaded_at TIMESTAMP NULL')
                except Exception:
                    pass
                try:
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipt_status ON invoices(receipt_status)')
                except Exception:
                    pass
                
                # Update invoices.gb_amount to DOUBLE if it is INT
                try:
                    cursor.execute("SHOW COLUMNS FROM invoices LIKE 'gb_amount'")
                    column_info = cursor.fetchone()
                    if column_info and 'int' in str(column_info['Type']).lower():
                        cursor.execute("ALTER TABLE invoices MODIFY COLUMN gb_amount DOUBLE NOT NULL")
                        logger.info("✅ Updated invoices.gb_amount column to DOUBLE")
                except Exception as e:
                    logger.warning(f"⚠️ Error checking/updating invoices.gb_amount column: {e}")
                
                # Create balance_transactions table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS balance_transactions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        amount INT NOT NULL,
                        transaction_type VARCHAR(50) NOT NULL,
                        description TEXT,
                        reference_id VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create system_logs table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS system_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        level VARCHAR(50) NOT NULL,
                        message TEXT NOT NULL,
                        module VARCHAR(100),
                        user_id INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create referrals table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS referrals (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        referrer_id INT NOT NULL,
                        referred_id INT NOT NULL,
                        reward_amount INT DEFAULT 0,
                        reward_paid TINYINT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        paid_at TIMESTAMP NULL,
                        FOREIGN KEY (referrer_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (referred_id) REFERENCES users (id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create database_migrations table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS database_migrations (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        version VARCHAR(255) UNIQUE NOT NULL,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        description TEXT
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create discount_codes table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS discount_codes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code VARCHAR(255) UNIQUE NOT NULL,
                        code_type VARCHAR(50) NOT NULL DEFAULT 'discount',
                        discount_type VARCHAR(50) NOT NULL DEFAULT 'percentage',
                        discount_value DECIMAL(10,2) NOT NULL,
                        max_discount_amount INT,
                        min_purchase_amount INT DEFAULT 0,
                        max_uses INT DEFAULT 0,
                        used_count INT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        valid_from TIMESTAMP NULL,
                        valid_until TIMESTAMP NULL,
                        applicable_to VARCHAR(50) DEFAULT 'all',
                        created_by INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        description TEXT,
                        notes TEXT,
                        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_code (code),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create gift_codes table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS gift_codes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code VARCHAR(255) UNIQUE NOT NULL,
                        amount INT NOT NULL,
                        max_uses INT DEFAULT 1,
                        used_count INT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        valid_from TIMESTAMP NULL,
                        valid_until TIMESTAMP NULL,
                        created_by INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        description TEXT,
                        notes TEXT,
                        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_code (code),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create discount_code_usage table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS discount_code_usage (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code_id INT NOT NULL,
                        user_id INT NOT NULL,
                        invoice_id INT,
                        amount_before_discount INT NOT NULL,
                        discount_amount INT NOT NULL,
                        amount_after_discount INT NOT NULL,
                        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (code_id) REFERENCES discount_codes (id) ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE SET NULL,
                        INDEX idx_user_id (user_id),
                        INDEX idx_code_id (code_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create gift_code_usage table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS gift_code_usage (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code_id INT NOT NULL,
                        user_id INT NOT NULL,
                        amount INT NOT NULL,
                        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (code_id) REFERENCES gift_codes (id) ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_code_id (code_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Create wheel_settings table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_settings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        setting_key VARCHAR(255) UNIQUE NOT NULL,
                        setting_value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Create wheel_prizes table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_prizes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        type VARCHAR(50) NOT NULL,
                        value FLOAT DEFAULT 0,
                        probability FLOAT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        display_order INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create wheel_spins table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_spins (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        prize_type VARCHAR(50) NOT NULL,
                        prize_value INT DEFAULT 0,
                        prize_label VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create tickets table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tickets (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        subject VARCHAR(500) NOT NULL,
                        status VARCHAR(50) DEFAULT 'open',
                        priority VARCHAR(50) DEFAULT 'normal',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        closed_at TIMESTAMP NULL,
                        closed_by INT NULL,
                        last_reply_at TIMESTAMP NULL,
                        last_reply_by INT NULL,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (closed_by) REFERENCES users (id) ON DELETE SET NULL,
                        FOREIGN KEY (last_reply_by) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_user_id (user_id),
                        INDEX idx_status (status),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create ticket_replies table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ticket_replies (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        ticket_id INT NOT NULL,
                        user_id INT NOT NULL,
                        message TEXT NOT NULL,
                        is_admin_reply TINYINT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_ticket_id (ticket_id),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create bot_texts table for customizable message templates
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bot_texts (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        database_name VARCHAR(255) NOT NULL DEFAULT '',
                        text_key VARCHAR(255) NOT NULL,
                        text_category VARCHAR(100) NOT NULL,
                        text_content TEXT NOT NULL,
                        description TEXT,
                        available_variables TEXT,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        updated_by INT,
                        FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL,
                        UNIQUE KEY unique_text_per_database (database_name, text_key),
                        INDEX idx_database_name (database_name),
                        INDEX idx_text_key (text_key),
                        INDEX idx_category (text_category),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Create settings table for dynamic configuration
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        setting_key VARCHAR(255) UNIQUE NOT NULL,
                        setting_value TEXT,
                        setting_type VARCHAR(50) DEFAULT 'string',
                        description TEXT,
                        is_public TINYINT DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        updated_by INT,
                        FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_key (setting_key)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Migration: Add database_name column if it doesn't exist (for existing databases)
                try:
                    # Check if column exists
                    cursor.execute("""
                        SELECT COUNT(*) as col_count 
                        FROM INFORMATION_SCHEMA.COLUMNS 
                        WHERE TABLE_SCHEMA = DATABASE() 
                        AND TABLE_NAME = 'bot_texts' 
                        AND COLUMN_NAME = 'database_name'
                    """)
                    col_exists = cursor.fetchone()['col_count'] > 0
                    
                    if not col_exists:
                        cursor.execute('''
                            ALTER TABLE bot_texts 
                            ADD COLUMN database_name VARCHAR(255) NOT NULL DEFAULT '' AFTER id
                        ''')
                        conn.commit()
                        logger.info("✅ Added database_name column to bot_texts table")
                        
                        # DON'T update existing rows - they might belong to other databases
                        # Only update if database_name is empty or NULL (new rows)
                        cursor.execute('UPDATE bot_texts SET database_name = %s WHERE (database_name = "" OR database_name IS NULL)', (self.database_name,))
                        updated_rows = cursor.rowcount
                        conn.commit()
                        if updated_rows > 0:
                            logger.info(f"✅ Updated {updated_rows} existing bot_texts rows (with empty database_name) to: {self.database_name}")
                        else:
                            logger.debug(f"ℹ️ No bot_texts rows with empty database_name to update for: {self.database_name}")
                    else:
                        logger.debug("database_name column already exists")
                except Exception as e:
                    logger.warning(f"Migration check for database_name column: {e}")
                
                # Migration: Add unique constraint if it doesn't exist
                try:
                    # Check if constraint exists
                    cursor.execute("""
                        SELECT COUNT(*) as constraint_count 
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS 
                        WHERE TABLE_SCHEMA = DATABASE() 
                        AND TABLE_NAME = 'bot_texts' 
                        AND CONSTRAINT_NAME = 'unique_text_per_database'
                    """)
                    constraint_exists = cursor.fetchone()['constraint_count'] > 0
                    
                    if not constraint_exists:
                        # Drop old unique constraint on text_key if exists
                        try:
                            cursor.execute("SHOW INDEX FROM bot_texts WHERE Key_name = 'text_key'")
                            if cursor.fetchone():
                                cursor.execute('ALTER TABLE bot_texts DROP INDEX text_key')
                                logger.info("✅ Dropped old unique constraint on text_key")
                        except:
                            pass
                        
                        cursor.execute('''
                            ALTER TABLE bot_texts 
                            ADD UNIQUE KEY unique_text_per_database (database_name, text_key)
                        ''')
                        conn.commit()
                        logger.info("✅ Added unique constraint for database_name + text_key")
                    else:
                        logger.debug("unique_text_per_database constraint already exists")
                except Exception as e:
                    logger.warning(f"Migration check for unique constraint: {e}")
                
                # Create product_categories table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS product_categories (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        panel_id INT NOT NULL,
                        name VARCHAR(255) NOT NULL,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        UNIQUE KEY unique_panel_name (panel_id, name),
                        INDEX idx_panel_id (panel_id),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Create products table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        panel_id INT NOT NULL,
                        category_id INT,
                        name VARCHAR(255) NOT NULL,
                        volume_gb INT NOT NULL,
                        duration_days INT NOT NULL,
                        price INT NOT NULL,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        description TEXT,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        FOREIGN KEY (category_id) REFERENCES product_categories (id) ON DELETE SET NULL,
                        INDEX idx_panel_id (panel_id),
                        INDEX idx_category_id (category_id),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Check and add columns to invoices table if needed
                # MySQL: Check if columns exist using INFORMATION_SCHEMA
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'invoices'
                """)
                invoice_columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'discount_code_id' not in invoice_columns:
                    try:
                        cursor.execute('ALTER TABLE invoices ADD COLUMN discount_code_id INT')
                        cursor.execute('ALTER TABLE invoices ADD COLUMN discount_amount INT DEFAULT 0')
                        cursor.execute('ALTER TABLE invoices ADD COLUMN original_amount INT')
                    except Exception as e:
                        logger.warning(f"Could not add discount columns to invoices: {e}")
                
                if 'product_id' not in invoice_columns:
                    try:
                        cursor.execute('ALTER TABLE invoices ADD COLUMN product_id INT')
                        cursor.execute('ALTER TABLE invoices ADD COLUMN duration_days INT DEFAULT 0')
                        cursor.execute('ALTER TABLE invoices ADD COLUMN purchase_type VARCHAR(50) DEFAULT "gigabyte"')
                    except Exception as e:
                        logger.warning(f"Could not add product columns to invoices: {e}")
                
                # Check if products table exists
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'products'
                """)
                result = cursor.fetchone()
                products_table_exists = result['count'] > 0 if result else False
                
                # Add visibility columns to products table if they don't exist
                if products_table_exists:
                    try:
                        cursor.execute("SHOW COLUMNS FROM products LIKE 'is_visible_to_users'")
                        if not cursor.fetchone():
                            cursor.execute("ALTER TABLE products ADD COLUMN is_visible_to_users TINYINT DEFAULT 1")
                            logger.info("✅ Added is_visible_to_users column to products table")
                    except Exception as e:
                        logger.warning(f"⚠️ Error checking/adding is_visible_to_users column: {e}")
                        
                    try:
                        cursor.execute("SHOW COLUMNS FROM products LIKE 'is_visible_to_resellers'")
                        if not cursor.fetchone():
                            cursor.execute("ALTER TABLE products ADD COLUMN is_visible_to_resellers TINYINT DEFAULT 1")
                            logger.info("✅ Added is_visible_to_resellers column to products table")
                    except Exception as e:
                        logger.warning(f"⚠️ Error checking/adding is_visible_to_resellers column: {e}")
                
                # Create menu_buttons table if it doesn't exist
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'menu_buttons'
                """)
                result = cursor.fetchone()
                if result and result['count'] == 0:
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS menu_buttons (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            database_name VARCHAR(255) NOT NULL DEFAULT '',
                            button_key VARCHAR(255) NOT NULL,
                            button_text VARCHAR(255) NOT NULL,
                            callback_data VARCHAR(255) NOT NULL,
                            button_type VARCHAR(50) DEFAULT 'callback',
                            web_app_url TEXT,
                            row_position INT NOT NULL DEFAULT 0,
                            column_position INT NOT NULL DEFAULT 0,
                            is_active TINYINT DEFAULT 1,
                            is_visible_for_admin TINYINT DEFAULT 0,
                            is_visible_for_users TINYINT DEFAULT 1,
                            requires_webapp TINYINT DEFAULT 0,
                            display_order INT DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            UNIQUE KEY unique_button_per_database (database_name, button_key),
                            INDEX idx_database_name (database_name),
                            INDEX idx_button_key (button_key),
                            INDEX idx_is_active (is_active)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    ''')
                    
                    # Insert default buttons
                    default_buttons = [
                        ('buy_service', '🛒 خرید سرویس', 'buy_service', 'callback', None, 0, 0, 1, 0, 1, 0, 1),
                        ('user_panel', '📊 پنل کاربری', 'user_panel', 'callback', None, 0, 1, 1, 0, 1, 0, 2),
                        ('test_account', '🧪 اکانت تست', 'test_account', 'callback', None, 1, 0, 1, 0, 1, 0, 3),
                        ('account_balance', '💰 موجودی', 'account_balance', 'callback', None, 1, 1, 1, 0, 1, 0, 4),
                        ('wheel_of_fortune', '🎰 گردونه شانس', 'wheel_spin', 'callback', None, 2, 0, 1, 0, 1, 0, 5),
                        ('referral_system', '🎁 دعوت دوستان', 'referral_system', 'callback', None, 2, 1, 1, 0, 1, 0, 6),
                        ('help', '❓ راهنما و پشتیبانی', 'help', 'callback', None, 3, 0, 1, 0, 1, 0, 7),
                        ('webapp', '🌐 ورود به وب اپلیکیشن', 'webapp', 'webapp', None, 3, 1, 1, 0, 1, 1, 8),
                        ('admin_panel', '⚙️ پنل مدیریت', 'admin_panel', 'callback', None, 4, 0, 1, 1, 0, 0, 9),
                    ]
                    
                    cursor.executemany('''
                        INSERT INTO menu_buttons 
                        (database_name, button_key, button_text, callback_data, button_type, web_app_url, row_position, column_position, 
                         is_active, is_visible_for_admin, is_visible_for_users, requires_webapp, display_order)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', [(self.database_name, *btn) for btn in default_buttons])
                    logger.info("✅ Created menu_buttons table with default buttons")
                
                # Create reserved_services table if it doesn't exist
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'reserved_services'
                """)
                result = cursor.fetchone()
                if result and result['count'] == 0:
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS reserved_services (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            client_id INT NOT NULL,
                            product_id INT NOT NULL,
                            volume_gb INT NOT NULL,
                            duration_days INT NOT NULL,
                            reserved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            activated_at TIMESTAMP NULL,
                            status VARCHAR(50) DEFAULT 'reserved',
                            FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE,
                            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    ''')
                    logger.info("✅ Created reserved_services table")
                
                # Create wheel_settings table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_settings (
                        setting_key VARCHAR(255) PRIMARY KEY,
                        setting_value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Create wheel_prizes table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_prizes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        type VARCHAR(50) NOT NULL,
                        value FLOAT DEFAULT 0,
                        probability FLOAT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        display_order INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Create wheel_spins table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_spins (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        prize_type VARCHAR(50) NOT NULL,
                        prize_value FLOAT DEFAULT 0,
                        prize_label VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # Run migrations
                self._run_migrations(conn)
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def _run_migrations(self, conn):
        """Run database migrations"""
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Migration v7.0: Add test_volume_gb to product_categories table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v7.0_add_category_test_volume'")
            if not cursor.fetchone():
                try:
                    # Check column
                    cursor.execute("SHOW COLUMNS FROM product_categories LIKE 'test_volume_gb'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE product_categories ADD COLUMN test_volume_gb FLOAT DEFAULT 0')
                        logger.info("✅ Added test_volume_gb column to product_categories table")
                        
                    cursor.execute("INSERT INTO database_migrations (version, description) VALUES ('v7.0_add_category_test_volume', 'Add test_volume_gb to product_categories table')")
                    logger.info("Applied migration v7.0_add_category_test_volume")
                except Exception as e:
                    logger.error(f"Migration v7.0 failed: {e}")

            # Migration v7.1: Add test_duration_hours to product_categories table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v7.1_add_category_test_duration'")
            if not cursor.fetchone():
                try:
                    # Check column
                    cursor.execute("SHOW COLUMNS FROM product_categories LIKE 'test_duration_hours'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE product_categories ADD COLUMN test_duration_hours INT DEFAULT 24')
                        logger.info("✅ Added test_duration_hours column to product_categories table")
                    
                    cursor.execute("INSERT INTO database_migrations (version, description) VALUES ('v7.1_add_category_test_duration', 'Add test_duration_hours to product_categories table')")
                    logger.info("Applied migration v7.1_add_category_test_duration")
                except Exception as e:
                    logger.error(f"Migration v7.1 failed: {e}")

            # Migration 1: Add subscription_url to panels table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.0_add_subscription_url'")
            if not cursor.fetchone():
                try:
                    cursor.execute('ALTER TABLE panels ADD COLUMN subscription_url TEXT')
                    cursor.execute("INSERT INTO database_migrations (version, description) VALUES ('v1.0_add_subscription_url', 'Add subscription_url to panels')")
                    logger.info("Applied migration v1.0_add_subscription_url")
                except Exception as e:
                    logger.warning(f"Migration v1.0 failed: {e}")

            # Migration v6.0: Add panel settings (naming_method, naming_prefix, default_config)
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v6.0_add_panel_settings'")
            if not cursor.fetchone():
                try:
                    # Check columns individually to avoid errors if partially applied
                    cursor.execute("SHOW COLUMNS FROM panels LIKE 'naming_method'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE panels ADD COLUMN naming_method INT DEFAULT 1')
                    
                    cursor.execute("SHOW COLUMNS FROM panels LIKE 'naming_prefix'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE panels ADD COLUMN naming_prefix VARCHAR(50)')
                        
                    cursor.execute("SHOW COLUMNS FROM panels LIKE 'default_config'")
                    if not cursor.fetchone():
                        cursor.execute('ALTER TABLE panels ADD COLUMN default_config JSON')
                        
                    cursor.execute("INSERT INTO database_migrations (version, description) VALUES ('v6.0_add_panel_settings', 'Add naming_method, naming_prefix, default_config to panels')")
                    logger.info("Applied migration v6.0_add_panel_settings")
                except Exception as e:
                    logger.error(f"Migration v6.0 failed: {e}")
                logger.info("Running migration: Add subscription_url to panels table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'panels'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'subscription_url' not in columns:
                    cursor.execute('ALTER TABLE panels ADD COLUMN subscription_url TEXT')
                    logger.info("✅ Added subscription_url column to panels table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.0_add_subscription_url', 'Add subscription_url field to panels table for subscription link')
                ''')
                logger.info("✅ Migration v1.0_add_subscription_url completed")
            
            # Migration v1.5: Add additional warning flags
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.5_add_warning_flags'")
            if not cursor.fetchone():
                logger.info("Running migration: Add additional warning flags to clients table")
                
                columns_to_add = [
                    ('warned_one_day', 'TINYINT DEFAULT 0'),
                    ('warned_12_hours', 'TINYINT DEFAULT 0'),
                    ('warned_80_percent', 'TINYINT DEFAULT 0'),
                    ('warned_90_percent', 'TINYINT DEFAULT 0')
                ]
                
                # Check columns
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                existing_columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                for col_name, col_def in columns_to_add:
                    if col_name not in existing_columns:
                        try:
                            cursor.execute(f'ALTER TABLE clients ADD COLUMN {col_name} {col_def}')
                            logger.info(f"✅ Added {col_name} column to clients table")
                        except Exception as e:
                            logger.error(f"Failed to add column {col_name}: {e}")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.5_add_warning_flags', 'Add detailed warning flags for expiration and usage')
                ''')
                logger.info("✅ Migration v1.5_add_warning_flags completed")
            
            # Migration v1.6: Add more granular warning flags
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.6_add_more_warning_flags'")
            if not cursor.fetchone():
                logger.info("Running migration: Add more granular warning flags to clients table")
                
                columns_to_add = [
                    ('warned_95_percent', 'TINYINT DEFAULT 0'),
                    ('warned_98_percent', 'TINYINT DEFAULT 0'),
                    ('warned_6_hours', 'TINYINT DEFAULT 0'),
                    ('warned_7_days', 'TINYINT DEFAULT 0')
                ]
                
                # Check columns
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                existing_columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                for col_name, col_def in columns_to_add:
                    if col_name not in existing_columns:
                        try:
                            cursor.execute(f'ALTER TABLE clients ADD COLUMN {col_name} {col_def}')
                            logger.info(f"✅ Added {col_name} column to clients table")
                        except Exception as e:
                            logger.error(f"Failed to add column {col_name}: {e}")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.6_add_more_warning_flags', 'Add granular warning flags (95%, 98%, 6h, 7d)')
                ''')
                logger.info("✅ Migration v1.6_add_more_warning_flags completed")

            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.17_add_predelete_warning_flag'")
            if not cursor.fetchone():
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                existing_columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                if 'warned_3_hours_before_deletion' not in existing_columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN warned_3_hours_before_deletion TINYINT DEFAULT 0')
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.17_add_predelete_warning_flag', 'Add warned_3_hours_before_deletion flag for grace period deletion warning')
                ''')
                logger.info("✅ Migration v1.17_add_predelete_warning_flag completed")
            
            # Migration 2: Add sub_id to clients table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.1_add_client_sub_id'")
            if not cursor.fetchone():
                logger.info("Running migration: Add sub_id to clients table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'sub_id' not in columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN sub_id VARCHAR(255)')
                    logger.info("✅ Added sub_id column to clients table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.1_add_client_sub_id', 'Add sub_id field to clients table for subscription tracking')
                ''')
                logger.info("✅ Migration v1.1_add_client_sub_id completed")
            
            # Migration 3: Add panel_type to panels table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.2_add_panel_type'")
            if not cursor.fetchone():
                logger.info("Running migration: Add panel_type to panels table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'panels'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'panel_type' not in columns:
                    cursor.execute('ALTER TABLE panels ADD COLUMN panel_type VARCHAR(50) DEFAULT "3x-ui"')
                    logger.info("✅ Added panel_type column to panels table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.2_add_panel_type', 'Add panel_type field to panels table')
                ''')
                logger.info("✅ Migration v1.2_add_panel_type completed")
            
            # Migration 4: Create settings table if not exists (for existing installations)
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.3_create_settings_table'")
            if not cursor.fetchone():
                logger.info("Running migration: Create settings table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        setting_key VARCHAR(255) UNIQUE NOT NULL,
                        setting_value TEXT,
                        setting_type VARCHAR(50) DEFAULT 'string',
                        description TEXT,
                        is_public TINYINT DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        updated_by INT,
                        FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_key (setting_key)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.3_create_settings_table', 'Create settings table for dynamic configuration')
                ''')
                logger.info("✅ Migration v1.3_create_settings_table completed")
            
            # Migration 5: Add admin_role column to users table for multi-level admin support
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.4_add_admin_role'")
            if not cursor.fetchone():
                logger.info("Running migration: Add admin_role to users table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'users'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'admin_role' not in columns:
                    cursor.execute("ALTER TABLE users ADD COLUMN admin_role VARCHAR(50) DEFAULT 'admin'")
                    logger.info("✅ Added admin_role column to users table")
                    
                    # Update existing admins to have 'admin' role
                    cursor.execute("UPDATE users SET admin_role = 'admin' WHERE is_admin = 1")
                    logger.info("✅ Updated existing admins with 'admin' role")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.4_add_admin_role', 'Add admin_role field to users table for multi-level admin support (admin/seller/support)')
                ''')
                logger.info("✅ Migration v1.4_add_admin_role completed")

            # Migration 6: Create wheel_spins table for wheel of fortune
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v2.0_create_wheel_spins'")
            if not cursor.fetchone():
                logger.info("Running migration: Create wheel_spins table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wheel_spins (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        prize_type VARCHAR(50) NOT NULL,
                        prize_value INT DEFAULT 0,
                        prize_label VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_user_id (user_id),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v2.0_create_wheel_spins', 'Create wheel_spins table for wheel of fortune history')
                ''')
                logger.info("✅ Migration v2.0_create_wheel_spins completed")

            # Migration 7: Create lottery_draws table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v2.1_create_lottery_draws'")
            if not cursor.fetchone():
                logger.info("Running migration: Create lottery_draws table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS lottery_draws (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        prize_type VARCHAR(50) NOT NULL,
                        prize_value INT NOT NULL,
                        ticket_price INT DEFAULT 0,
                        max_tickets INT DEFAULT 0,
                        draw_date TIMESTAMP NOT NULL,
                        winner_user_id INT,
                        status VARCHAR(50) DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (winner_user_id) REFERENCES users (id) ON DELETE SET NULL,
                        INDEX idx_status (status),
                        INDEX idx_draw_date (draw_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v2.1_create_lottery_draws', 'Create lottery_draws table for lottery management')
                ''')
                logger.info("✅ Migration v2.1_create_lottery_draws completed")

            # Migration 8: Create lottery_tickets table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v2.2_create_lottery_tickets'")
            if not cursor.fetchone():
                logger.info("Running migration: Create lottery_tickets table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS lottery_tickets (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        draw_id INT NOT NULL,
                        user_id INT NOT NULL,
                        ticket_number VARCHAR(50) NOT NULL,
                        purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (draw_id) REFERENCES lottery_draws (id) ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        INDEX idx_draw_id (draw_id),
                        INDEX idx_user_id (user_id),
                        UNIQUE KEY unique_ticket (draw_id, ticket_number)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v2.2_create_lottery_tickets', 'Create lottery_tickets table for tracking participants')
                ''')
                logger.info("✅ Migration v2.2_create_lottery_tickets completed")

            # Migration 9: Create support_departments table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v3.0_create_support_departments'")
            if not cursor.fetchone():
                logger.info("Running migration: Create support_departments table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS support_departments (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        emoji VARCHAR(10) DEFAULT '🎧',
                        admin_ids TEXT,
                        display_order INT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v3.0_create_support_departments', 'Create support_departments table for ticket routing')
                ''')
                logger.info("✅ Migration v3.0_create_support_departments completed")

            # Migration 10: Add department_id to tickets table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v3.1_add_department_to_tickets'")
            if not cursor.fetchone():
                logger.info("Running migration: Add department_id to tickets")
                
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tickets'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'department_id' not in columns:
                    cursor.execute('ALTER TABLE tickets ADD COLUMN department_id INT')
                    cursor.execute('ALTER TABLE tickets ADD INDEX idx_department_id (department_id)')
                    logger.info("✅ Added department_id column to tickets table")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v3.1_add_department_to_tickets', 'Add department_id to tickets for routing')
                ''')
                logger.info("✅ Migration v3.1_add_department_to_tickets completed")

            # Migration 11: Create app_links table for download links management
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v4.0_create_app_links'")
            if not cursor.fetchone():
                logger.info("Running migration: Create app_links table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS app_links (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        platform VARCHAR(50) NOT NULL,
                        download_url TEXT NOT NULL,
                        icon_emoji VARCHAR(10) DEFAULT '📱',
                        display_order INT DEFAULT 0,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_platform (platform),
                        INDEX idx_is_active (is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Insert default app links
                default_apps = [
                    ('V2rayNG', 'کلاینت رسمی V2Ray برای اندروید', 'android', 'https://github.com/2dust/v2rayNG/releases', '📱'),
                    ('V2Box', 'کلاینت V2Ray برای iOS', 'ios', 'https://apps.apple.com/app/v2box-v2ray-client/id6446814690', '🍎'),
                    ('Hiddify', 'کلاینت چند پلتفرم', 'multi', 'https://github.com/hiddify/hiddify-next/releases', '🔐'),
                    ('Nekobox', 'کلاینت پیشرفته اندروید', 'android', 'https://github.com/MatsuriDayo/NekoBoxForAndroid/releases', '🐱'),
                    ('Clash Verge', 'کلاینت دسکتاپ', 'desktop', 'https://github.com/zzzgydi/clash-verge/releases', '💻'),
                ]
                
                for app in default_apps:
                    cursor.execute('''
                        INSERT INTO app_links (name, description, platform, download_url, icon_emoji)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', app)
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v4.0_create_app_links', 'Create app_links table for managing download links')
                ''')
                logger.info("✅ Migration v4.0_create_app_links completed")

            # Migration 12: Create required_channels table for multi-channel force join
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v5.0_create_required_channels'")
            if not cursor.fetchone():
                logger.info("Running migration: Create required_channels table")
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS required_channels (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        channel_id VARCHAR(100) NOT NULL,
                        channel_name VARCHAR(255) NOT NULL,
                        channel_url TEXT,
                        display_order INT DEFAULT 0,
                        is_required TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_channel_id (channel_id),
                        INDEX idx_is_required (is_required)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v5.0_create_required_channels', 'Create required_channels table for multi-channel force join')
                ''')
                logger.info("✅ Migration v5.0_create_required_channels completed")

            # Migration 13: Add naming_method and renewal_method to panels table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v5.1_add_panel_methods'")
            if not cursor.fetchone():
                logger.info("Running migration: Add naming/renewal methods to panels")
                
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'panels'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'naming_method' not in columns:
                    cursor.execute("ALTER TABLE panels ADD COLUMN naming_method INT DEFAULT 2")
                    cursor.execute("ALTER TABLE panels ADD COLUMN admin_prefix VARCHAR(50) DEFAULT 'VIP'")
                    logger.info("✅ Added naming_method and admin_prefix to panels")
                
                if 'renewal_method' not in columns:
                    cursor.execute("ALTER TABLE panels ADD COLUMN renewal_method INT DEFAULT 1")
                    logger.info("✅ Added renewal_method to panels")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v5.1_add_panel_methods', 'Add naming_method, renewal_method to panels table')
                ''')
                logger.info("✅ Migration v5.1_add_panel_methods completed")

            # Migration 14: Add user_limit to products table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v7.0_add_product_user_limit'")
            if not cursor.fetchone():
                logger.info("Running migration: Add user_limit to products")
                
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'user_limit' not in columns:
                    cursor.execute("ALTER TABLE products ADD COLUMN user_limit INT DEFAULT 0")
                    logger.info("✅ Added user_limit to products")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v7.0_add_product_user_limit', 'Add user_limit field to products table')
                ''')
                logger.info("✅ Migration v7.0_add_product_user_limit completed")

            # Migration 15: Add limit_ip to clients table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v7.1_add_client_limit_ip'")
            if not cursor.fetchone():
                logger.info("Running migration: Add limit_ip to clients")
                
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'clients'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'limit_ip' not in columns:
                    cursor.execute("ALTER TABLE clients ADD COLUMN limit_ip INT DEFAULT 0")
                    logger.info("✅ Added limit_ip to clients")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v7.1_add_client_limit_ip', 'Add limit_ip field to clients table')
                ''')
                logger.info("✅ Migration v7.1_add_client_limit_ip completed")

            # Migration 16: Add last_activity to clients table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v7.2_add_client_last_activity'")
            if not cursor.fetchone():
                logger.info("Running migration: Add last_activity to clients")
                
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'clients'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'last_activity' not in columns:
                    cursor.execute("ALTER TABLE clients ADD COLUMN last_activity BIGINT DEFAULT 0")
                    logger.info("✅ Added last_activity to clients")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v7.2_add_client_last_activity', 'Add last_activity field to clients table')
                ''')
                logger.info("✅ Migration v7.2_add_client_last_activity completed")

            # Migration 17: Add inbound_id to products table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v8.0_add_product_inbound_id'")
            if not cursor.fetchone():
                logger.info("Running migration: Add inbound_id to products")
                
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'inbound_id' not in columns:
                    cursor.execute("ALTER TABLE products ADD COLUMN inbound_id INT DEFAULT NULL")
                    logger.info("✅ Added inbound_id to products")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v8.0_add_product_inbound_id', 'Add inbound_id field to products table')
                ''')
                logger.info("✅ Migration v8.0_add_product_inbound_id completed")

        except Exception as e:
            logger.error(f"Migration error: {e}")
            # Don't raise, just log - we don't want to stop startup if a migration fails
            pass

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value from the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT setting_value, setting_type FROM settings WHERE setting_key = %s", (key,))
                result = cursor.fetchone()
                
                if result:
                    value = result['setting_value']
                    value_type = result['setting_type']
                    
                    # Type conversion
                    if value is None:
                        return default
                        
                    if value_type == 'int':
                        return int(value)
                    elif value_type == 'float':
                        return float(value)
                    elif value_type == 'bool':
                        return value.lower() in ('true', '1', 'yes', 'on')
                    elif value_type == 'json':
                        return json.loads(value)
                    else:
                        return value
                
                return default
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return default

    def set_setting(self, key: str, value: Any, description: str = None, user_id: int = None) -> bool:
        """Set a setting value in the database"""
        try:
            # Determine type
            value_type = 'string'
            if isinstance(value, bool):
                value_type = 'bool'
                value = str(value).lower()
            elif isinstance(value, int):
                value_type = 'int'
                value = str(value)
            elif isinstance(value, float):
                value_type = 'float'
                value = str(value)
            elif isinstance(value, (dict, list)):
                value_type = 'json'
                value = json.dumps(value)
            else:
                value = str(value)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                if description:
                    cursor.execute("""
                        INSERT INTO settings (setting_key, setting_value, setting_type, description, updated_by)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                            setting_value = VALUES(setting_value),
                            setting_type = VALUES(setting_type),
                            description = VALUES(description),
                            updated_by = VALUES(updated_by)
                    """, (key, value, value_type, description, user_id))
                else:
                    cursor.execute("""
                        INSERT INTO settings (setting_key, setting_value, setting_type, updated_by)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                            setting_value = VALUES(setting_value),
                            setting_type = VALUES(setting_type),
                            updated_by = VALUES(updated_by)
                    """, (key, value, value_type, user_id))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting setting {key}: {e}")
            return False
            # Migration 15: Add comprehensive warning tracking fields
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.15_add_comprehensive_warnings'")
            if not cursor.fetchone():
                logger.info("Running migration: Add comprehensive warning tracking fields")
                
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                client_columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'warned_100_percent' not in client_columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN warned_100_percent TINYINT DEFAULT 0')
                    logger.info("✅ Added warned_100_percent column to clients table")
                
                if 'warned_three_days' not in client_columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN warned_three_days TINYINT DEFAULT 0')
                    logger.info("✅ Added warned_three_days column to clients table")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.15_add_comprehensive_warnings', 'Add warned_100_percent and warned_three_days fields for comprehensive monitoring and warning tracking')
                ''')
                logger.info("✅ Migration v1.15_add_comprehensive_warnings completed")
                conn.commit()

            # Migration 16: Add extra_config to panels table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.16_add_extra_config'")
            if not cursor.fetchone():
                logger.info("Running migration: Add extra_config to panels table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'panels'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'extra_config' not in columns:
                    cursor.execute('ALTER TABLE panels ADD COLUMN extra_config JSON')
                    logger.info("✅ Added extra_config column to panels table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.16_add_extra_config', 'Add extra_config JSON field to panels table for custom panel settings')
                ''')
                logger.info("✅ Migration v1.16_add_extra_config completed")
                conn.commit()

            # Migration 17: Add last_activity to clients table (fix for missing column error)
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.17_add_last_activity_to_clients'")
            if not cursor.fetchone():
                logger.info("Running migration: Add last_activity to clients table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'last_activity' not in columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN last_activity BIGINT DEFAULT 0')
                    logger.info("✅ Added last_activity column to clients table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.17_add_last_activity_to_clients', 'Add last_activity field to clients table to fix missing column error')
                ''')
                logger.info("✅ Migration v1.17_add_last_activity_to_clients completed")
                conn.commit()

            # Migration 18: Add cached_remaining_days to clients table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.18_add_cached_remaining_days'")
            if not cursor.fetchone():
                logger.info("Running migration: Add cached_remaining_days to clients table")
                
                # Check if column already exists
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'cached_remaining_days' not in columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN cached_remaining_days INT DEFAULT 0')
                    logger.info("✅ Added cached_remaining_days column to clients table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.18_add_cached_remaining_days', 'Add cached_remaining_days field to clients table for caching remaining days')
                ''')
                logger.info("✅ Migration v1.18_add_cached_remaining_days completed")
                conn.commit()
            
            # Migration 19: Add test account settings to product_categories table
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v1.19_add_category_test_settings'")
            if not cursor.fetchone():
                logger.info("Running migration: Add test account settings to product_categories table")
                
                # Check columns
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'product_categories'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'test_account_volume_gb' not in columns:
                    cursor.execute('ALTER TABLE product_categories ADD COLUMN test_account_volume_gb FLOAT DEFAULT 0')
                    logger.info("✅ Added test_account_volume_gb column to product_categories table")
                    
                if 'test_account_duration_hours' not in columns:
                    cursor.execute('ALTER TABLE product_categories ADD COLUMN test_account_duration_hours INT DEFAULT 0')
                    logger.info("✅ Added test_account_duration_hours column to product_categories table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v1.19_add_category_test_settings', 'Add test account volume and duration to product_categories')
                ''')
                logger.info("✅ Migration v1.19_add_category_test_settings completed")
                conn.commit()

            # Migration 20: Add test_accounts_log and is_test_account to clients
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v2.0_multi_test_accounts'")
            if not cursor.fetchone():
                logger.info("Running migration: v2.0_multi_test_accounts")
                
                # Create test_accounts_log table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS test_accounts_log (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        panel_id INT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_uuid VARCHAR(255),
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        INDEX idx_user_panel (user_id, panel_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                logger.info("✅ Created test_accounts_log table")
                
                # Add is_test_account to clients
                cursor.execute("""
                    SELECT COLUMN_NAME 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'clients'
                """)
                columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
                
                if 'is_test_account' not in columns:
                    cursor.execute('ALTER TABLE clients ADD COLUMN is_test_account TINYINT DEFAULT 0')
                    logger.info("✅ Added is_test_account column to clients table")
                
                # Mark migration as applied
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v2.0_multi_test_accounts', 'Add support for multiple test accounts per panel')
                ''')
                logger.info("✅ Migration v2.0_multi_test_accounts completed")
                conn.commit()

            # Migration v2.1: Ensure test_account button exists
            cursor.execute("SELECT version FROM database_migrations WHERE version = 'v2.1_add_test_account_button'")
            if not cursor.fetchone():
                logger.info("Running migration: v2.1_add_test_account_button")
                
                # Check if button exists
                cursor.execute("SELECT id FROM menu_buttons WHERE button_key = 'test_account'")
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO menu_buttons 
                        (database_name, button_key, button_text, callback_data, button_type, row_position, column_position, is_active, is_visible_for_users, display_order)
                        VALUES (%s, 'test_account', '🧪 اکانت تست', 'test_account', 'callback', 1, 0, 1, 1, 3)
                    ''', (self.database_name,))
                    logger.info("✅ Added test_account button to menu_buttons")
                
                cursor.execute('''
                    INSERT INTO database_migrations (version, description)
                    VALUES ('v2.1_add_test_account_button', 'Ensure test account button exists in menu')
                ''')
                conn.commit()
            
        except Exception as e:
            logger.error(f"Error running migrations: {e}")
            raise
    
    def create_backup(self, backup_name: str = None):
        """Create a backup of the database"""
        try:
            if not backup_name:
                backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            backup_path = os.path.join(self.backup_dir, f"{backup_name}.sql")
            # For MySQL, we'll use mysqldump command
            import subprocess
            try:
                subprocess.run([
                    'mysqldump',
                    f'--host={self.db_config["host"]}',
                    f'--port={self.db_config["port"]}',
                    f'--user={self.db_config["user"]}',
                    f'--password={self.db_config["password"]}',
                    self.database_name
                ], stdout=open(backup_path, 'w', encoding='utf-8'), check=True)
                logger.info(f"MySQL database backup created: {backup_path}")
                return backup_path
            except Exception as e:
                logger.error(f"Failed to create MySQL backup using mysqldump: {e}")
                logger.info("Attempting manual backup...")
                # Manual backup - export all tables
                with self.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    # Get all tables
                    cursor.execute("""
                        SELECT TABLE_NAME 
                        FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_SCHEMA = DATABASE()
                    """)
                    tables = [row['TABLE_NAME'] for row in cursor.fetchall()]
                    
                    backup_sql = []
                    for table in tables:
                        # SECURITY: Validate table name to prevent SQL injection
                        import re
                        if not re.match(r'^[a-zA-Z0-9_\-]+$', table):
                            logger.warning(f"Skipping invalid table name: {table}")
                            continue
                        # SECURITY: Table name already validated above, just escape backticks
                        safe_table = table.replace('`', '``')
                        cursor.execute("SELECT * FROM `{}`".format(safe_table))
                        rows = cursor.fetchall()
                        if rows:
                            columns = list(rows[0].keys())
                            # SECURITY: Validate and escape column names
                            safe_columns = []
                            for c in columns:
                                if not re.match(r'^[a-zA-Z0-9_\-]+$', c):
                                    logger.warning(f"Skipping invalid column name: {c}")
                                    continue
                                safe_columns.append(f"`{c.replace('`', '``')}`")
                            if not safe_columns:
                                continue
                            backup_sql.append(f"INSERT INTO `{safe_table}` ({', '.join(safe_columns)}) VALUES")
                            for row in rows:
                                values = []
                                for col in columns:
                                    val = row[col]
                                    if val is None:
                                        values.append('NULL')
                                    elif isinstance(val, (int, float)):
                                        values.append(str(val))
                                    else:
                                        values.append(f"'{str(val).replace(chr(39), chr(39)+chr(39))}'")
                                backup_sql.append(f"({', '.join(values)}),")
                            backup_sql[-1] = backup_sql[-1].rstrip(',') + ';'
                    
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(backup_sql))
                    logger.info(f"MySQL database backup created (manual): {backup_path}")
                    return backup_path
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return None
    
    def restore_backup(self, backup_path: str):
        """Restore database from backup"""
        try:
            # For MySQL, restore from SQL file
            import subprocess
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
                
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    # Execute SQL statements
                    for statement in sql_content.split(';'):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    conn.commit()
                
                logger.info(f"MySQL database restored from: {backup_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to restore MySQL backup: {e}")
                return False
        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            return False
    
    def log_system_event(self, level: str, message: str, module: str = None, user_id: int = None):
        """Log system events to database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # If user_id is provided, verify it exists or try to get database id from telegram_id
                db_user_id = None
                if user_id is not None:
                    # First check if it's a valid database user id
                    cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
                    if cursor.fetchone():
                        db_user_id = user_id
                    else:
                        # Try to get database id from telegram_id
                        cursor.execute('SELECT id FROM users WHERE telegram_id = %s', (user_id,))
                        row = cursor.fetchone()
                        if row:
                            db_user_id = row[0]
                        # If still not found, leave it as None (allowed by FOREIGN KEY constraint)
                
                cursor.execute('''
                    INSERT INTO system_logs (level, message, module, user_id)
                    VALUES (%s, %s, %s, %s)
                ''', (level, message, module, db_user_id))
                conn.commit()
        except Exception as e:
            # Don't log system event errors to avoid infinite loops
            logger.error(f"Failed to log system event: {e}")
    
    # User Management Methods
    def add_user(self, telegram_id: int, username: str = None, 
                 first_name: str = None, last_name: str = None, 
                 is_admin: bool = False, referred_by: int = None, 
                 referral_code: str = None) -> int:
        """Add or update user information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Check if user exists
                cursor.execute('SELECT id FROM users WHERE telegram_id = %s', (telegram_id,))
                existing_user = cursor.fetchone()
                
                if existing_user:
                    # Update existing user
                    # If user doesn't have referral_code, generate one
                    if not referral_code:
                        # Check if user already has a referral code
                        cursor.execute('SELECT referral_code FROM users WHERE telegram_id = %s', (telegram_id,))
                        existing_code = cursor.fetchone()
                        if existing_code and existing_code.get('referral_code'):
                            referral_code = existing_code['referral_code']
                        else:
                            # Generate new referral code
                            referral_code = self.generate_referral_code()
                    
                    cursor.execute('''
                        UPDATE users SET 
                        username = COALESCE(%s, username),
                        first_name = COALESCE(%s, first_name),
                        last_name = COALESCE(%s, last_name),
                        referral_code = COALESCE(%s, referral_code),
                        last_activity = CURRENT_TIMESTAMP
                        WHERE telegram_id = %s
                    ''', (username, first_name, last_name, referral_code, telegram_id))
                    user_id = existing_user['id']
                else:
                    # Create new user
                    # If no referral_code provided, generate one
                    if not referral_code:
                        referral_code = self.generate_referral_code()
                    
                    cursor.execute('''
                        INSERT INTO users (telegram_id, username, first_name, last_name, is_admin, referred_by, referral_code)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (telegram_id, username, first_name, last_name, is_admin, referred_by, referral_code))
                    user_id = cursor.lastrowid
                
                conn.commit()
                self.log_system_event('INFO', f'User {telegram_id} processed', 'user_management', user_id)
                return user_id
                
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            self.log_system_event('ERROR', f'Failed to add user {telegram_id}: {e}', 'user_management')
            return 0
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by telegram ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM users WHERE telegram_id = %s', (telegram_id,))
                row = cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get user by internal database ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
                row = cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            return None
    
    def has_user_received_test_account(self, telegram_id: int) -> bool:
        """Check if user has already received a test account"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT has_used_test_account FROM users WHERE telegram_id = %s', (telegram_id,))
                result = cursor.fetchone()
                if result:
                    return bool(result['has_used_test_account'])
                return False
        except Exception as e:
            logger.error(f"Error checking test account usage: {e}")
            return False

    def mark_test_account_used(self, telegram_id: int) -> bool:
        """Mark user as having used the test account (Legacy: updates flag)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET has_used_test_account = 1 WHERE telegram_id = %s', (telegram_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error marking test account usage: {e}")
            return False

    def _ensure_test_accounts_table(self):
        """Ensure test_accounts_log table exists (Self-healing)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS test_accounts_log (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        panel_id INT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_uuid VARCHAR(255),
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (panel_id) REFERENCES panels (id) ON DELETE CASCADE,
                        INDEX idx_user_panel (user_id, panel_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # Check for is_test_account column in clients
                cursor.execute("SHOW COLUMNS FROM clients LIKE 'is_test_account'")
                if not cursor.fetchone():
                    cursor.execute('ALTER TABLE clients ADD COLUMN is_test_account TINYINT DEFAULT 0')
                
                conn.commit()
                logger.info("✅ Self-healed test_accounts_log table")
        except Exception as e:
            logger.error(f"Error self-healing test_accounts_log: {e}")

    def log_test_account_creation(self, user_id: int, panel_id: int, client_uuid: str = None) -> bool:
        """Log test account creation in the new log table"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO test_accounts_log (user_id, panel_id, client_uuid)
                    VALUES (%s, %s, %s)
                ''', (user_id, panel_id, client_uuid))
                conn.commit()
                return True
        except Exception as e:
            if "doesn't exist" in str(e) or "1146" in str(e):
                self._ensure_test_accounts_table()
                return self.log_test_account_creation(user_id, panel_id, client_uuid) # Retry
            logger.error(f"Error logging test account creation: {e}")
            return False

    def get_user_test_accounts_count(self, user_id: int) -> int:
        """Get total number of test accounts received by user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT COUNT(*) as count FROM test_accounts_log WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            if "doesn't exist" in str(e) or "1146" in str(e):
                self._ensure_test_accounts_table()
                return 0 # Treat as 0 after creating table
            logger.error(f"Error counting user test accounts: {e}")
            return 0

    def has_user_received_test_account_from_panel(self, user_id: int, panel_id: int) -> bool:
        """Check if user has received a test account from specific panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT id FROM test_accounts_log WHERE user_id = %s AND panel_id = %s', (user_id, panel_id))
                return bool(cursor.fetchone())
        except Exception as e:
            if "doesn't exist" in str(e) or "1146" in str(e):
                self._ensure_test_accounts_table()
                return False
            logger.error(f"Error checking panel test account: {e}")
            return False


    def update_user_balance(self, telegram_id: int, amount: int, transaction_type: str, description: str = None, notify_user: bool = True) -> bool:
        """Update user balance and log transaction"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Check if user exists
                cursor.execute('SELECT id FROM users WHERE telegram_id = %s', (telegram_id,))
                user_row = cursor.fetchone()
                
                if not user_row:
                    return False
                
                # Update balance atomically
                cursor.execute('UPDATE users SET balance = balance + %s WHERE telegram_id = %s', (amount, telegram_id))
                
                # Fetch new balance for notification
                cursor.execute('SELECT balance FROM users WHERE telegram_id = %s', (telegram_id,))
                row = cursor.fetchone()
                new_balance = row['balance'] if row else 0
                
                # Log transaction
                cursor.execute('''
                    INSERT INTO balance_transactions (user_id, amount, transaction_type, description)
                    VALUES (%s, %s, %s, %s)
                ''', (user_row['id'], amount, transaction_type, description))
                
                conn.commit()
                self.log_system_event('INFO', f'Balance updated for user {telegram_id}: {amount}', 'balance_management', telegram_id)
                
                # Send notification to user (if amount is not 0 and notifications enabled)
                if amount != 0 and notify_user:
                    try:
                        from telegram_helper import TelegramHelper
                        
                        emoji = "💰" if amount > 0 else "💸"
                        action_text = "افزایش" if amount > 0 else "کاهش"
                        
                        # Don't show negative sign in amount text
                        amount_abs = abs(amount)
                        
                        notification_text = f"""
{emoji} موجودی کیف پول شما تغییر کرد

💵 مبلغ: {amount_abs:,} تومان ({action_text})
💰 موجودی جدید: {new_balance:,} تومان
📝 بابت: {description or 'تغییر توسط سیستم'}

📅 تاریخ: {datetime.now().strftime('%Y/%m/%d %H:%M')}
"""
                        TelegramHelper.send_message_sync(telegram_id, notification_text)
                    except Exception as e:
                        logger.error(f"Error sending balance notification to {telegram_id}: {e}")
                
                return True
                
        except Exception as e:
            logger.error(f"Error updating user balance: {e}")
            return False

    def add_balance(self, user_id: int, amount: int, transaction_type: str, description: str = None) -> bool:
        """Add balance to user (using Internal ID)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Update balance
                cursor.execute('UPDATE users SET balance = balance + %s WHERE id = %s', (amount, user_id))
                
                # Log transaction
                cursor.execute('''
                    INSERT INTO balance_transactions (user_id, amount, transaction_type, description)
                    VALUES (%s, %s, %s, %s)
                ''', (user_id, amount, transaction_type, description))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding balance: {e}")
            return False
    
    def deduct_balance(self, user_id: int, amount: int, transaction_type: str, invoice_id: int = None, description: str = None) -> bool:
        """Deduct balance from user (using Internal ID)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Update balance (subtract)
                cursor.execute('UPDATE users SET balance = balance - %s WHERE id = %s', (amount, user_id))
                
                # Log transaction
                if not description:
                    description = f"Payment for invoice #{invoice_id}" if invoice_id else "Balance deduction"
                
                cursor.execute('''
                    INSERT INTO balance_transactions (user_id, amount, transaction_type, description)
                    VALUES (%s, %s, %s, %s)
                ''', (user_id, -amount, transaction_type, description))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error deducting balance: {e}")
            return False
    
    def get_user_balance(self, telegram_id: int) -> int:
        """Get user balance"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT balance FROM users WHERE telegram_id = %s', (telegram_id,))
                row = cursor.fetchone()
                return row['balance'] if row else 0
        except Exception as e:
            logger.error(f"Error getting user balance: {e}")
            return 0
    
    def update_user_info(self, telegram_id: int, username: str = None, 
                         first_name: str = None, last_name: str = None) -> bool:
        """Update user's profile information (username, first_name, last_name)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE users SET 
                    username = %s,
                    first_name = %s,
                    last_name = %s,
                    last_activity = CURRENT_TIMESTAMP
                    WHERE telegram_id = %s
                ''', (username, first_name, last_name, telegram_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating user info: {e}")
            return False
    
    def update_user_ban_status(self, telegram_id: int, is_banned: bool) -> bool:
        """Update user's ban status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE users 
                    SET is_banned = %s, last_activity = CURRENT_TIMESTAMP
                    WHERE telegram_id = %s
                ''', (1 if is_banned else 0, telegram_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating user ban status: {e}")
            return False
    
    def update_user_activity(self, telegram_id: int) -> bool:
        """Update user's last activity timestamp"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE users SET last_activity = CURRENT_TIMESTAMP 
                    WHERE telegram_id = %s
                ''', (telegram_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating user activity: {e}")
            return False
    
    # Panel Management Methods
    def add_panel(self, name: str, url: str, username: str, password: str, 
                  api_endpoint: str, default_inbound_id: int = None, price_per_gb: int = 0,
                  subscription_url: str = None, panel_type: str = '3x-ui', default_protocol: str = 'vless',
                  sale_type: str = 'gigabyte', extra_config: dict = None, delivery_method: str = 'subscription_link') -> int:
        """Add a new panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Serialize extra_config to JSON if provided
                extra_config_json = json.dumps(extra_config) if extra_config else None
                
                cursor.execute('''
                    INSERT INTO panels (name, panel_type, url, username, password, api_endpoint, default_inbound_id, price_per_gb, subscription_url, default_protocol, sale_type, extra_config, delivery_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (name, panel_type, url, username, password, api_endpoint, default_inbound_id, price_per_gb, subscription_url, default_protocol, sale_type, extra_config_json, delivery_method))
                
                panel_id = cursor.lastrowid
                conn.commit()
                self.log_system_event('INFO', f'Panel added: {name} (Type: {panel_type})', 'panel_management', panel_id)
                return panel_id
        except Exception as e:
            logger.error(f"Error adding panel: {e}")
            return 0
    
    def get_panel(self, panel_id: int) -> Optional[Dict]:
        """Get panel by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM panels WHERE id = %s', (panel_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting panel: {e}")
            return None
    
    def get_panels(self, active_only: bool = True) -> List[Dict]:
        """Get all panels"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM panels"
                if active_only:
                    query += " WHERE is_active = 1"
                query += " ORDER BY created_at DESC"
                
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting panels: {e}")
            return []

    def get_all_panels(self) -> List[Dict]:
        """Get all panels (active and inactive) - Alias for get_panels(active_only=False)"""
        return self.get_panels(active_only=False)
    
    def update_panel(self, panel_id: int, name: str = None, url: str = None,
                     username: str = None, password: str = None, 
                     api_endpoint: str = None, price_per_gb: int = None,
                     subscription_url: str = None, panel_type: str = None, default_protocol: str = None,
                     sale_type: str = None, default_inbound_id: int = None, extra_config: dict = None,
                     delivery_method: str = None) -> bool:
        """Update panel information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Build dynamic update query
                updates = []
                params = []
                
                if name is not None:
                    updates.append("name = %s")
                    params.append(name)
                if panel_type is not None:
                    updates.append("panel_type = %s")
                    params.append(panel_type)
                if url is not None:
                    updates.append("url = %s")
                    params.append(url)
                if username is not None:
                    updates.append("username = %s")
                    params.append(username)
                if extra_config is not None:
                    updates.append("extra_config = %s")
                    params.append(json.dumps(extra_config))
                if password is not None:
                    updates.append("password = %s")
                    params.append(password)
                if api_endpoint is not None:
                    updates.append("api_endpoint = %s")
                    params.append(api_endpoint)
                if price_per_gb is not None:
                    updates.append("price_per_gb = %s")
                    params.append(price_per_gb)
                if subscription_url is not None:
                    updates.append("subscription_url = %s")
                    params.append(subscription_url)
                if default_protocol is not None:
                    updates.append("default_protocol = %s")
                    params.append(default_protocol)
                if sale_type is not None:
                    updates.append("sale_type = %s")
                    params.append(sale_type)
                if default_inbound_id is not None:
                    updates.append("default_inbound_id = %s")
                    params.append(default_inbound_id)
                if delivery_method is not None:
                    updates.append("delivery_method = %s")
                    params.append(delivery_method)
                
                if not updates:
                    return True  # Nothing to update
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(panel_id)
                
                query = f"UPDATE panels SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                
                self.log_system_event('INFO', f'Panel updated: ID {panel_id}', 'panel_management')
                return True
        except Exception as e:
            logger.error(f"Error updating panel: {e}")
            return False
    
    def delete_panel(self, panel_id: int) -> bool:
        """Delete a panel completely from database (hard delete)
        This will also delete all related data due to CASCADE constraints:
        - All clients associated with this panel
        - All invoices for this panel
        - All products and categories for this panel
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # First check if panel exists
                cursor.execute('SELECT name FROM panels WHERE id = %s', (panel_id,))
                panel = cursor.fetchone()
                if not panel:
                    logger.warning(f"Panel {panel_id} not found")
                    return False
                
                panel_name = panel['name']
                
                # Hard delete - completely remove from database
                # CASCADE will automatically delete:
                # - clients (ON DELETE CASCADE)
                # - invoices (ON DELETE CASCADE)
                # - products (ON DELETE CASCADE)
                # - product_categories (ON DELETE CASCADE)
                cursor.execute('DELETE FROM panels WHERE id = %s', (panel_id,))
                conn.commit()
                
                self.log_system_event('INFO', f'Panel completely deleted: {panel_name} (ID: {panel_id})', 'panel_management')
                logger.info(f"Panel {panel_id} ({panel_name}) completely deleted from database")
                return True
        except Exception as e:
            logger.error(f"Error deleting panel: {e}", exc_info=True)
            return False
    
    def cleanup_deleted_panels(self) -> int:
        """Remove all previously soft-deleted panels (is_active=0) completely from database
        This is a cleanup function to remove old soft-deleted panels that were marked inactive
        Returns the number of panels deleted
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Find all inactive panels
                cursor.execute('SELECT id, name FROM panels WHERE is_active = 0')
                inactive_panels = cursor.fetchall()
                
                if not inactive_panels:
                    logger.info("No inactive panels found to cleanup")
                    return 0
                
                deleted_count = 0
                for panel in inactive_panels:
                    panel_id = panel['id']
                    panel_name = panel['name']
                    
                    try:
                        # Hard delete the panel (CASCADE will handle related data)
                        cursor.execute('DELETE FROM panels WHERE id = %s', (panel_id,))
                        deleted_count += 1
                        logger.info(f"Cleaned up inactive panel: {panel_name} (ID: {panel_id})")
                    except Exception as e:
                        logger.error(f"Error deleting inactive panel {panel_id}: {e}")
                        continue
                
                conn.commit()
                logger.info(f"✅ Cleanup completed: {deleted_count} inactive panel(s) removed from database")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Error cleaning up deleted panels: {e}", exc_info=True)
            return 0
    
    # Panel Inbound Management Methods
    def sync_panel_inbounds(self, panel_id: int, inbounds: List[Dict]) -> bool:
        """Sync inbounds for a panel - delete all old inbounds and insert new ones"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # First, delete all existing inbounds for this panel
                cursor.execute('''
                    DELETE FROM panel_inbounds 
                    WHERE panel_id = %s
                ''', (panel_id,))
                deleted_count = cursor.rowcount
                logger.info(f"🗑️ Deleted {deleted_count} old inbounds for panel {panel_id}")
                
                # Now insert all new inbounds
                for inbound in inbounds:
                    inbound_id = inbound.get('id')
                    inbound_name = inbound.get('remark', inbound.get('tag', f'Inbound {inbound_id}'))
                    inbound_protocol = inbound.get('protocol', 'unknown')
                    inbound_port = inbound.get('port', 0)
                    
                    # Insert new inbound (enabled by default)
                    cursor.execute('''
                        INSERT INTO panel_inbounds 
                        (panel_id, inbound_id, inbound_name, inbound_protocol, inbound_port, is_enabled)
                        VALUES (%s, %s, %s, %s, %s, 1)
                    ''', (panel_id, inbound_id, inbound_name, inbound_protocol, inbound_port))
                
                conn.commit()
                logger.info(f"✅ Synced {len(inbounds)} inbounds for panel {panel_id} (deleted {deleted_count} old ones)")
                return True
        except Exception as e:
            logger.error(f"Error syncing panel inbounds: {e}")
            return False
    
    def get_panel_inbounds_db(self, panel_id: int, enabled_only: bool = False) -> List[Dict]:
        """Get inbounds for a panel from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM panel_inbounds WHERE panel_id = %s"
                params = [panel_id]
                
                if enabled_only:
                    query += " AND is_enabled = 1"
                
                query += " ORDER BY inbound_id ASC"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting panel inbounds from database: {e}")
            return []
    
    def get_panel_inbound(self, panel_id: int, inbound_id: int) -> Optional[Dict]:
        """Get specific inbound for a panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT * FROM panel_inbounds 
                    WHERE panel_id = %s AND inbound_id = %s
                ''', (panel_id, inbound_id))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting panel inbound: {e}")
            return None
    
    def set_inbound_enabled(self, panel_id: int, inbound_id: int, is_enabled: bool) -> bool:
        """Enable or disable an inbound for a panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE panel_inbounds 
                    SET is_enabled = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE panel_id = %s AND inbound_id = %s
                ''', (1 if is_enabled else 0, panel_id, inbound_id))
                conn.commit()
                logger.info(f"✅ Set inbound {inbound_id} for panel {panel_id} to {'enabled' if is_enabled else 'disabled'}")
                return True
        except Exception as e:
            logger.error(f"Error setting inbound enabled status: {e}")
            return False
    
    def update_panel_default_inbound(self, panel_id: int, default_inbound_id: int) -> bool:
        """Update the default (main) inbound for a panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE panels 
                    SET default_inbound_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (default_inbound_id, panel_id))
                conn.commit()
                logger.info(f"✅ Updated default inbound for panel {panel_id} to {default_inbound_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating panel default inbound: {e}")
            return False

    def update_panel_naming_method(self, panel_id: int, method_id: int) -> bool:
        """Update panel naming method in extra_config"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get current config
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False
                    
                current_config = result['extra_config']
                if isinstance(current_config, str):
                    try:
                        config_dict = json.loads(current_config) if current_config else {}
                    except:
                        config_dict = {}
                else:
                    config_dict = current_config if current_config else {}
                    
                # Update method
                config_dict['naming_method'] = str(method_id)
                
                # Save back
                new_config = json.dumps(config_dict)
                cursor.execute('''
                    UPDATE panels 
                    SET extra_config = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (new_config, panel_id))
                conn.commit()
                
                # Verify update
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                verify_result = cursor.fetchone()
                if verify_result:
                    verify_config = json.loads(verify_result['extra_config']) if isinstance(verify_result['extra_config'], str) else verify_result['extra_config']
                    logger.info(f"🔍 DB Verification for panel {panel_id}: naming_method is now {verify_config.get('naming_method')}")
                
                self.log_system_event('INFO', f'Updated naming method for panel {panel_id} to {method_id}', 'panel_management')
                return True
        except Exception as e:
            logger.error(f"Error updating panel naming method: {e}")
            return False

    def update_panel_settings(self, panel_id: int, settings: Dict) -> bool:
        """Update arbitrary settings in panel extra_config"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get current config
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False
                    
                current_config = result['extra_config']
                if isinstance(current_config, str):
                    try:
                        config_dict = json.loads(current_config) if current_config else {}
                    except:
                        config_dict = {}
                else:
                    config_dict = current_config if current_config else {}
                    
                # Update settings
                for key, value in settings.items():
                    config_dict[key] = value
                
                # Save back
                new_config = json.dumps(config_dict)
                cursor.execute('''
                    UPDATE panels 
                    SET extra_config = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (new_config, panel_id))
                conn.commit()
                
                return True
        except Exception as e:
            logger.error(f"Error updating panel settings: {e}")
            return False
    
    def get_active_inbounds_for_change(self, exclude_panel_id: int = None, exclude_inbound_id: int = None, price_per_gb: int = None) -> List[Dict]:
        """Get all active inbounds from all panels for panel/inbound change feature
        Returns list with panel info and inbound info combined
        If price_per_gb is provided, only returns inbounds from panels with that price
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = '''
                    SELECT 
                        p.id as panel_id,
                        p.name as panel_name,
                        p.price_per_gb,
                        pi.inbound_id,
                        pi.inbound_name,
                        pi.inbound_protocol,
                        pi.inbound_port,
                        p.default_inbound_id,
                        CASE 
                            WHEN pi.inbound_id = p.default_inbound_id THEN 1 
                            ELSE 0 
                        END as is_main_inbound
                    FROM panel_inbounds pi
                    JOIN panels p ON pi.panel_id = p.id
                    WHERE pi.is_enabled = 1 AND p.is_active = 1
                '''
                params = []
                
                if price_per_gb is not None:
                    query += " AND p.price_per_gb = %s"
                    params.append(price_per_gb)
                
                if exclude_panel_id:
                    query += " AND p.id != %s"
                    params.append(exclude_panel_id)
                
                if exclude_inbound_id and exclude_panel_id:
                    query += " AND NOT (p.id = %s AND pi.inbound_id = %s)"
                    params.extend([exclude_panel_id, exclude_inbound_id])
                
                query += " ORDER BY p.name ASC, pi.inbound_id ASC"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting active inbounds for change: {e}")
            return []
    
    # Product Category Management Methods
    def add_category(self, panel_id: int, name: str) -> int:
        """Add a new product category"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    INSERT INTO product_categories (panel_id, name)
                    VALUES (%s, %s)
                ''', (panel_id, name))
                
                category_id = cursor.lastrowid
                conn.commit()
                self.log_system_event('INFO', f'Category added: {name} (Panel: {panel_id})', 'product_management')
                return category_id
        except Exception as e:
            logger.error(f"Error adding category: {e}")
            return 0
    
    def get_categories(self, panel_id: int, active_only: bool = True) -> List[Dict]:
        """Get all categories for a panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM product_categories WHERE panel_id = %s"
                if active_only:
                    query += " AND is_active = 1"
                query += " ORDER BY name ASC"
                
                cursor.execute(query, (panel_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting categories: {e}")
            return []
    
    def get_category(self, category_id: int) -> Optional[Dict]:
        """Get category by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM product_categories WHERE id = %s', (category_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting category: {e}")
            return None
    
    def update_category(self, category_id: int, **kwargs) -> bool:
        """Update category information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                updates = []
                params = []
                
                # Handle standard fields explicitly for backward compatibility if needed, 
                # but kwargs covers everything.
                
                allowed_fields = ['name', 'is_active', 'test_account_volume_gb', 'test_account_duration_hours']
                
                for field, value in kwargs.items():
                    if field in allowed_fields:
                        if field == 'is_active':
                            updates.append(f"{field} = %s")
                            params.append(1 if value else 0)
                        else:
                            updates.append(f"{field} = %s")
                            params.append(value)
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(category_id)
                
                query = f"UPDATE product_categories SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                
                self.log_system_event('INFO', f'Category updated: ID {category_id}', 'product_management')
                return True
        except Exception as e:
            logger.error(f"Error updating category: {e}")
            return False
    
    def delete_category(self, category_id: int) -> bool:
        """Delete a category (hard delete - permanently removes from database)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # First, set category_id to NULL for all products in this category
                cursor.execute('''
                    UPDATE products 
                    SET category_id = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE category_id = %s
                ''', (category_id,))
                
                # Then delete the category permanently
                cursor.execute('DELETE FROM product_categories WHERE id = %s', (category_id,))
                conn.commit()
                
                self.log_system_event('INFO', f'Category permanently deleted: ID {category_id}', 'product_management')
                return True
        except Exception as e:
            logger.error(f"Error deleting category: {e}")
            return False
    
    def has_products_without_category(self, panel_id: int) -> bool:
        """Check if panel has products without category"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT COUNT(*) as count FROM products WHERE panel_id = %s AND category_id IS NULL AND is_active = 1', (panel_id,))
                row = cursor.fetchone()
                return row['count'] > 0 if row else False
        except Exception as e:
            logger.error(f"Error checking products without category: {e}")
            return False
    
    def count_products_without_category(self, panel_id: int) -> int:
        """Count products without category"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT COUNT(*) as count FROM products WHERE panel_id = %s AND category_id IS NULL AND is_active = 1', (panel_id,))
                row = cursor.fetchone()
                return row['count'] if row else 0
        except Exception as e:
            logger.error(f"Error counting products without category: {e}")
            return 0
    
    # Product Management Methods
    def _get_product_name_column(self, cursor) -> str:
        """Helper method to get the correct name column (name or name_product)"""
        try:
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'products'
            """)
            columns = [row['COLUMN_NAME'] for row in cursor.fetchall()]
            
            # If name_product exists and name doesn't, use name_product
            if 'name_product' in columns and 'name' not in columns:
                return 'name_product'
            # If both exist, prefer name (newer standard)
            elif 'name' in columns:
                return 'name'
            # If only name_product exists
            elif 'name_product' in columns:
                return 'name_product'
            # Default to name
            return 'name'
        except:
            return 'name'
    
    def add_product(self, panel_id: int, name: str, volume_gb: int, duration_days: int,
                   price: int, category_id: int = None, description: str = None, inbound_id: int = None, user_limit: int = 1,
                   is_visible_to_users: bool = True, is_visible_to_resellers: bool = True) -> int:
        """Add a new product"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Check which columns exist to build proper INSERT statement (MySQL syntax)
                cursor.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, EXTRA
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'products'
                    ORDER BY ORDINAL_POSITION
                """)
                columns_info = cursor.fetchall()
                columns = [col['COLUMN_NAME'] for col in columns_info]
                
                # Check if name_product has NOT NULL constraint
                name_product_col = next((col for col in columns_info if col['COLUMN_NAME'] == 'name_product'), None)
                name_product_not_null = name_product_col and name_product_col['IS_NULLABLE'] == 'NO' if name_product_col else False
                
                # Determine which name column(s) to use
                use_name_product = False
                use_name = False
                
                if 'name_product' in columns:
                    if name_product_not_null:
                        # name_product has NOT NULL, must use it
                        use_name_product = True
                    elif 'name' not in columns:
                        # Only name_product exists
                        use_name_product = True
                
                if 'name' in columns:
                    use_name = True
                
                # If both exist and name_product is NOT NULL, use both
                if use_name_product and use_name:
                    # Use both columns
                    pass
                elif use_name_product:
                    # Only use name_product
                    use_name = False
                elif use_name:
                    # Only use name
                    use_name_product = False
                
                # Build column list dynamically based on what exists
                insert_columns = ['panel_id']
                insert_values = [panel_id]
                
                if 'category_id' in columns:
                    insert_columns.append('category_id')
                    insert_values.append(category_id)
                
                if 'inbound_id' in columns:
                    insert_columns.append('inbound_id')
                    insert_values.append(inbound_id)
                
                if 'user_limit' in columns:
                    insert_columns.append('user_limit')
                    insert_values.append(user_limit)

                if 'is_visible_to_users' in columns:
                    insert_columns.append('is_visible_to_users')
                    insert_values.append(1 if is_visible_to_users else 0)

                if 'is_visible_to_resellers' in columns:
                    insert_columns.append('is_visible_to_resellers')
                    insert_values.append(1 if is_visible_to_resellers else 0)
                
                # Add name column(s)
                if use_name_product:
                    insert_columns.append('name_product')
                    insert_values.append(name)
                
                if use_name:
                    insert_columns.append('name')
                    insert_values.append(name)
                
                # Check for other NOT NULL columns that might be missing
                for col_info in columns_info:
                    col_name = col_info['COLUMN_NAME']
                    is_not_null = col_info['IS_NULLABLE'] == 'NO'  # MySQL: 'NO' = NOT NULL, 'YES' = nullable
                    
                    # Skip columns we've already handled
                    if col_name in insert_columns:
                        continue
                    
                    # Skip primary key (auto-increment)
                    if col_info['COLUMN_KEY'] == 'PRI':  # MySQL: 'PRI' = primary key
                        continue
                    
                    # Skip columns with defaults
                    if col_info['COLUMN_DEFAULT'] is not None:  # MySQL: COLUMN_DEFAULT
                        continue
                    
                    # Skip auto-increment columns
                    if 'auto_increment' in col_info.get('EXTRA', '').lower():
                        continue
                    
                    # If column is NOT NULL and not in our list, add it with a default value
                    if is_not_null:
                        if col_name == 'code_product':
                            # Generate a code based on name
                            code_value = name[:20].replace(' ', '_').replace('گیگابایت', 'GB').upper() if name else 'PRODUCT'
                            insert_columns.append('code_product')
                            insert_values.append(code_value)
                            logger.info(f"Auto-added code_product with value: {code_value}")
                        elif col_name not in ['panel_id', 'name', 'name_product', 'volume_gb', 'duration_days', 'price', 'is_visible_to_users', 'is_visible_to_resellers']:
                            # For other NOT NULL columns, use a default based on type
                            col_type = col_info['DATA_TYPE'].upper()
                            if 'INT' in col_type or 'TINYINT' in col_type or 'SMALLINT' in col_type or 'MEDIUMINT' in col_type or 'BIGINT' in col_type:
                                insert_columns.append(col_name)
                                insert_values.append(0)
                            elif 'TEXT' in col_type or 'VARCHAR' in col_type or 'CHAR' in col_type:
                                insert_columns.append(col_name)
                                insert_values.append('')
                            elif 'BOOLEAN' in col_type or 'TINYINT' in col_type:
                                insert_columns.append(col_name)
                                insert_values.append(1)
                            else:
                                insert_columns.append(col_name)
                                insert_values.append('')
                            logger.info(f"Auto-added NOT NULL column {col_name} with default value")
                
                if 'volume_gb' in columns:
                    insert_columns.append('volume_gb')
                    insert_values.append(volume_gb)
                
                if 'duration_days' in columns:
                    insert_columns.append('duration_days')
                    insert_values.append(duration_days)
                
                if 'price' in columns:
                    insert_columns.append('price')
                    insert_values.append(price)
                
                if 'description' in columns:
                    insert_columns.append('description')
                    insert_values.append(description)
                
                # Always set is_active to 1 for new products
                if 'is_active' in columns:
                    insert_columns.append('is_active')
                    insert_values.append(1)
                
                # Build and execute INSERT statement
                placeholders = ', '.join(['%s'] * len(insert_values))
                columns_str = ', '.join(insert_columns)
                
                logger.info(f"Inserting product with columns: {columns_str}, values: {insert_values}")
                cursor.execute(f'''
                    INSERT INTO products ({columns_str})
                    VALUES ({placeholders})
                ''', tuple(insert_values))
                
                product_id = cursor.lastrowid
                conn.commit()
                self.log_system_event('INFO', f'Product added: {name} (Panel: {panel_id})', 'product_management')
                return product_id
        except Exception as e:
            logger.error(f"Error adding product: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0
    
    def get_products(self, panel_id: int, category_id: int = None, active_only: bool = True) -> List[Dict]:
        """Get all products for a panel, optionally filtered by category"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM products WHERE panel_id = %s"
                params = [panel_id]
                
                if category_id is False:  # Explicitly get products without category
                    query += " AND category_id IS NULL"
                elif category_id is not None:  # Get products for specific category
                    query += " AND category_id = %s"
                    params.append(category_id)
                # If category_id is None, don't filter by category (get all products)
                
                if active_only:
                    query += " AND is_active = 1"
                
                query += " ORDER BY price ASC"
                
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting products: {e}")
            return []
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        """Get product by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM products WHERE id = %s', (product_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting product: {e}")
            return None
    
    def activate_all_inactive_products(self, panel_id: int) -> int:
        """Activate all inactive products for a panel (useful for fixing products added before is_active was set)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE products 
                    SET is_active = 1 
                    WHERE panel_id = %s AND (is_active = 0 OR is_active IS NULL)
                ''', (panel_id,))
                affected_rows = cursor.rowcount
                conn.commit()
                if affected_rows > 0:
                    logger.info(f"Activated {affected_rows} inactive products for panel {panel_id}")
                return affected_rows
        except Exception as e:
            logger.error(f"Error activating inactive products: {e}")
            return 0
    
    def update_product(self, product_id: int, name: str = None, volume_gb: int = None,
                      duration_days: int = None, price: int = None, 
                      category_id: int = None, is_active: bool = None, description: str = None, inbound_id: int = None, user_limit: int = None,
                      is_visible_to_users: bool = None, is_visible_to_resellers: bool = None) -> bool:
        """Update product information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get correct column name
                name_column = self._get_product_name_column(cursor)
                
                updates = []
                params = []
                
                if name is not None:
                    updates.append(f"{name_column} = %s")
                    params.append(name)
                if volume_gb is not None:
                    updates.append("volume_gb = %s")
                    params.append(volume_gb)
                if duration_days is not None:
                    updates.append("duration_days = %s")
                    params.append(duration_days)
                if price is not None:
                    updates.append("price = %s")
                    params.append(price)
                if category_id is not None:
                    updates.append("category_id = %s")
                    params.append(category_id)
                if is_active is not None:
                    updates.append("is_active = %s")
                    params.append(1 if is_active else 0)
                if description is not None:
                    updates.append("description = %s")
                    params.append(description)
                if inbound_id is not None:
                    updates.append("inbound_id = %s")
                    params.append(inbound_id)
                if user_limit is not None:
                    updates.append("user_limit = %s")
                    params.append(user_limit)

                if is_visible_to_users is not None:
                    # Check if column exists first
                    cursor.execute("SHOW COLUMNS FROM products LIKE 'is_visible_to_users'")
                    if cursor.fetchone():
                        updates.append('is_visible_to_users = %s')
                        params.append(1 if is_visible_to_users else 0)

                if is_visible_to_resellers is not None:
                    # Check if column exists first
                    cursor.execute("SHOW COLUMNS FROM products LIKE 'is_visible_to_resellers'")
                    if cursor.fetchone():
                        updates.append('is_visible_to_resellers = %s')
                        params.append(1 if is_visible_to_resellers else 0)
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(product_id)
                
                query = f"UPDATE products SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                
                self.log_system_event('INFO', f'Product updated: ID {product_id}', 'product_management')
                return True
        except Exception as e:
            logger.error(f"Error updating product: {e}")
            return False
    
    def delete_product(self, product_id: int) -> bool:
        """Delete a product (hard delete - permanently removes from database)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Check if product is used in any active services
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM clients 
                    WHERE product_id = %s AND is_active = 1
                ''', (product_id,))
                result = cursor.fetchone()
                
                if result and result['count'] > 0:
                    logger.warning(f"Cannot delete product {product_id}: {result['count']} active services are using it")
                    return False
                
                # Delete the product permanently
                cursor.execute('DELETE FROM products WHERE id = %s', (product_id,))
                conn.commit()
                
                self.log_system_event('INFO', f'Product permanently deleted: ID {product_id}', 'product_management')
                return True
        except Exception as e:
            logger.error(f"Error deleting product: {e}")
            return False
    
    # Client Management Methods
    def add_client(self, user_id: int, panel_id: int, client_name: str, 
                   client_uuid: str, inbound_id: int, protocol: str,
                   expire_days: int = 0, total_gb: float = 0, config_link: str = None, 
                   sub_id: str = None, expires_at: str = None, product_id: int = None, limit_ip: int = 0, invoice_id: int = None) -> int:
        """Add client to database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Calculate expiry date if not provided
                if expires_at is None and expire_days > 0:
                    expires_at = datetime.now() + timedelta(days=expire_days)
                    expires_at = expires_at.isoformat()
                elif expires_at and isinstance(expires_at, datetime):
                    expires_at = expires_at.isoformat()
                
                cursor.execute('''
                    INSERT INTO clients (user_id, panel_id, client_name, client_uuid, 
                                      inbound_id, protocol, expire_days, total_gb, expires_at, config_link, sub_id, product_id, limit_ip, invoice_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (user_id, panel_id, client_name, client_uuid, 
                      inbound_id, protocol, expire_days, total_gb, expires_at, config_link, sub_id, product_id, limit_ip, invoice_id))
                
                client_id = cursor.lastrowid
                conn.commit()
                self.log_system_event('INFO', f'Client added: {client_name}', 'client_management', user_id)
                return client_id
        except Exception as e:
            # Check for unknown column error (MySQL 1054) regarding invoice_id
            if "Unknown column 'invoice_id'" in str(e):
                logger.warning("⚠️ invoice_id column missing in clients table, retrying without it...")
                try:
                    with self.get_connection() as conn:
                        cursor = conn.cursor(dictionary=True)
                        cursor.execute('''
                            INSERT INTO clients (user_id, panel_id, client_name, client_uuid, 
                                              inbound_id, protocol, expire_days, total_gb, expires_at, config_link, sub_id, product_id, limit_ip)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (user_id, panel_id, client_name, client_uuid, 
                              inbound_id, protocol, expire_days, total_gb, expires_at, config_link, sub_id, product_id, limit_ip))
                        client_id = cursor.lastrowid
                        conn.commit()
                        self.log_system_event('INFO', f'Client added (fallback mode): {client_name}', 'client_management', user_id)
                        return client_id
                except Exception as e2:
                    logger.error(f"Error adding client (fallback failed): {e2}")
                    return 0
            
            logger.error(f"Error adding client: {e}")
            return 0

    def get_clients_by_invoice(self, invoice_id: int) -> List[Dict]:
        """Get clients associated with an invoice"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, pi.inbound_name
                    FROM clients c
                    LEFT JOIN panels p ON c.panel_id = p.id
                    LEFT JOIN panel_inbounds pi ON c.panel_id = pi.panel_id AND c.inbound_id = pi.inbound_id
                    WHERE c.invoice_id = %s
                    ORDER BY c.created_at DESC
                ''', (invoice_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            if "Unknown column 'invoice_id'" in str(e):
                logger.warning("⚠️ invoice_id column missing in clients table, cannot match services to invoice")
                return []
            logger.error(f"Error getting clients by invoice: {e}")
            return []
    
    def update_client_config(self, client_id: int, config_link: str) -> bool:
        """Update client config link"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET config_link = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (config_link, client_id))
                conn.commit()
                logger.info(f"Updated config for client {client_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating client config: {e}")
            return False
    
    def update_client_cached_data(self, client_id: int, used_gb: float = None, 
                                   last_activity: int = None, is_online: bool = None,
                                   remaining_days: int = None) -> bool:
        """Update cached client data from panel sync"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                update_parts = []
                params = []
                
                if used_gb is not None:
                    update_parts.append("cached_used_gb = %s")
                    params.append(used_gb)
                
                if last_activity is not None:
                    # Ensure last_activity is within BIGINT range
                    # MySQL BIGINT range: -9223372036854775808 to 9223372036854775807
                    if last_activity > 9223372036854775807:
                        last_activity = 9223372036854775807
                    elif last_activity < -9223372036854775808:
                        last_activity = -9223372036854775808
                    
                    update_parts.append("cached_last_activity = %s")
                    params.append(last_activity)
                    # Also update last_activity column to keep in sync
                    update_parts.append("last_activity = %s")
                    params.append(last_activity)
                
                if is_online is not None:
                    update_parts.append("cached_is_online = %s")
                    params.append(1 if is_online else 0)
                
                if remaining_days is not None:
                    update_parts.append("cached_remaining_days = %s")
                    params.append(remaining_days)
                
                if update_parts:
                    update_parts.append("data_last_synced = CURRENT_TIMESTAMP")
                    params.append(client_id)
                    
                    query = f"UPDATE clients SET {', '.join(update_parts)} WHERE id = %s"
                    cursor.execute(query, params)
                    conn.commit()
                    
                    logger.debug(f"Updated cached data for client {client_id}")
                    return True
                
                return True
        except Exception as e:
            logger.error(f"Error updating client cached data: {e}")
            return False
    
    def update_client_status(self, client_id: int, is_active: bool = None, used_gb: float = None) -> bool:
        """Update client status and traffic usage from panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Build dynamic UPDATE query based on provided parameters
                update_parts = []
                params = []
                
                if is_active is not None:
                    update_parts.append("is_active = %s")
                    params.append(1 if is_active else 0)
                
                if used_gb is not None:
                    update_parts.append("used_gb = %s")
                    params.append(used_gb)
                
                if not update_parts:
                    return True  # Nothing to update
                
                update_parts.append("updated_at = CURRENT_TIMESTAMP")
                params.append(client_id)
                
                query = f"UPDATE clients SET {', '.join(update_parts)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                
                logger.info(f"Updated status for client {client_id}: active={is_active}, used_gb={used_gb}")
                return True
        except Exception as e:
            logger.error(f"Error updating client status: {e}")
            return False

    def bulk_update_client_status(self, updates: List[Dict]) -> bool:
        """
        Bulk update client status and traffic usage
        Args:
            updates: List of dicts with keys: 'id', 'used_gb' (optional), 'is_active' (optional)
        """
        if not updates:
            return True
            
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                monitoring_updates = []
                used_gb_updates = []
                for update in updates:
                    if not isinstance(update, dict) or 'id' not in update:
                        continue
                    if update.get('monitoring_update') is True:
                        monitoring_updates.append((
                            update.get('used_gb'),
                            update.get('cached_used_gb'),
                            update.get('cached_last_activity'),
                            update.get('last_activity'),
                            update.get('cached_is_online'),
                            update.get('cached_remaining_days'),
                            update.get('expires_at'),
                            update['id']
                        ))
                    elif 'used_gb' in update:
                        used_gb_updates.append((update.get('used_gb'), update['id']))
                
                if monitoring_updates:
                    query = """
                        UPDATE clients
                        SET used_gb = %s,
                            cached_used_gb = %s,
                            cached_last_activity = %s,
                            last_activity = %s,
                            cached_is_online = %s,
                            cached_remaining_days = %s,
                            expires_at = %s,
                            data_last_synced = NOW(),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """
                    cursor.executemany(query, monitoring_updates)
                    logger.info(f"⚡ Bulk updated monitoring data for {len(monitoring_updates)} clients")
                
                if used_gb_updates:
                    query = "UPDATE clients SET used_gb = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
                    cursor.executemany(query, used_gb_updates)
                    logger.info(f"⚡ Bulk updated used_gb for {len(used_gb_updates)} clients")
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error in bulk_update_client_status: {e}")
            return False
    
    def update_client_total_gb(self, client_id: int, new_total_gb: float) -> bool:
        """Update client's total GB allowance"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                cursor.execute('''
                    UPDATE clients 
                    SET total_gb = %s, 
                        status = 'active',
                        is_active = 1,
                        warned_70_percent = 0,
                        warned_100_percent = 0,
                        warned_expired = 0,
                        warned_three_days = 0,
                        warned_one_week = 0,
                        notified_70_percent = 0,
                        notified_80_percent = 0,
                        exhausted_at = NULL,
                        expired_at = NULL,
                        deletion_grace_period_end = NULL,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                ''', (new_total_gb, client_id))
                
                conn.commit()
                
                logger.info(f"Updated total_gb for client {client_id} to {new_total_gb}GB")
                return True
        except Exception as e:
            logger.error(f"Error updating client total_gb: {e}")
            return False
    
    def get_panels_with_same_price(self, price_per_gb: int, exclude_panel_id: int = None) -> List[Dict]:
        """Get all panels with the same price_per_gb (for location/panel change)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = '''
                    SELECT * FROM panels 
                    WHERE price_per_gb = %s AND is_active = 1
                '''
                params = [price_per_gb]
                
                if exclude_panel_id:
                    query += ' AND id != %s'
                    params.append(exclude_panel_id)
                
                query += ' ORDER BY name ASC'
                
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting panels with same price: {e}")
            return []
    
    def update_service_panel(self, service_id: int, new_panel_id: int, new_inbound_id: int, 
                            new_client_uuid: str, new_total_gb: float, config_link: str = None, 
                            sub_id: str = None) -> bool:
        """Update service panel information after location/panel change"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Build update query dynamically
                updates = []
                params = []
                
                updates.append("panel_id = %s")
                params.append(new_panel_id)
                
                updates.append("inbound_id = %s")
                params.append(new_inbound_id)
                
                updates.append("client_uuid = %s")
                params.append(new_client_uuid)
                
                updates.append("total_gb = %s")
                # Ensure total_gb is rounded to 2 decimal places
                params.append(round(float(new_total_gb), 2))
                
                updates.append("used_gb = 0")
                
                # Reset cached data since we're changing panels
                updates.append("cached_used_gb = 0")
                updates.append("cached_last_activity = 0")
                updates.append("cached_is_online = 0")
                updates.append("data_last_synced = NULL")
                
                # Update config_link if provided
                if config_link:
                    updates.append("config_link = %s")
                    params.append(config_link)
                
                # Update sub_id if provided
                if sub_id:
                    updates.append("sub_id = %s")
                    params.append(sub_id)
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                
                # Add service_id for WHERE clause
                params.append(service_id)
                
                query = f"UPDATE clients SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                
                conn.commit()
                
                logger.info(f"Updated service {service_id} panel: panel_id={new_panel_id}, total_gb={new_total_gb}, config_link={'updated' if config_link else 'not updated'}")
                return True
        except Exception as e:
            return False
    
    def update_panel_naming_method(self, panel_id: int, naming_method: int) -> bool:
        """Update panel naming method"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE panels 
                    SET naming_method = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (naming_method, panel_id))
                conn.commit()
                logger.info(f"Updated naming method for panel {panel_id} to {naming_method}")
                return True
        except Exception as e:
            logger.error(f"Error updating panel naming method: {e}")
            return False

    def update_panel_settings(self, panel_id: int, settings: Dict) -> bool:
        """Update panel settings (extra_config)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # First get existing config
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False
                    
                current_config = result['extra_config']
                if isinstance(current_config, str):
                    try:
                        current_config = json.loads(current_config)
                    except:
                        current_config = {}
                elif current_config is None:
                    current_config = {}
                    
                # Update config
                current_config.update(settings)
                
                # Also check if naming_method is in settings and update the column too
                if 'naming_method' in settings:
                    try:
                        naming_method = int(settings['naming_method'])
                        cursor.execute('UPDATE panels SET naming_method = %s WHERE id = %s', (naming_method, panel_id))
                    except:
                        pass
                
                cursor.execute('''
                    UPDATE panels 
                    SET extra_config = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (json.dumps(current_config), panel_id))
                conn.commit()
                logger.info(f"Updated settings for panel {panel_id}: {settings}")
                return True
        except Exception as e:
            logger.error(f"Error updating panel settings: {e}")
            return False

    def update_service_panel_simple(self, service_id: int, new_panel_id: int, new_inbound_id: int) -> bool:
        """
        Simple update of service panel_id and inbound_id without modifying client_uuid or traffic.
        Used for recovery when services need to be moved to a different panel but clients don't exist yet.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                cursor.execute(
                    '''UPDATE clients 
                       SET panel_id = %s, 
                           inbound_id = %s,
                           updated_at = CURRENT_TIMESTAMP 
                       WHERE id = %s''',
                    (new_panel_id, new_inbound_id, service_id)
                )
                
                conn.commit()
                
                logger.info(f"Updated service {service_id}: panel_id={new_panel_id}, inbound_id={new_inbound_id}")
                return True
        except Exception as e:
            logger.error(f"Error in update_service_panel_simple: {e}")
            return False
    
    def update_service_inbound_id(self, service_id: int, new_inbound_id: int) -> bool:
        """Update only the inbound_id for a service"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    'UPDATE clients SET inbound_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                    (new_inbound_id, service_id)
                )
                conn.commit()
                logger.info(f"Updated service {service_id} inbound_id to {new_inbound_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating service inbound_id: {e}")
            return False
    
    def get_all_user_services_for_volume(self, user_id: int) -> List[Dict]:
        """Get all user's services for volume addition - includes ALL non-deleted services"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, p.price_per_gb, pi.inbound_name
                    FROM clients c 
                    LEFT JOIN panels p ON c.panel_id = p.id 
                    LEFT JOIN panel_inbounds pi ON c.panel_id = pi.panel_id AND c.inbound_id = pi.inbound_id
                    WHERE c.user_id = %s 
                    ORDER BY c.created_at DESC
                ''', (user_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user services for volume: {e}")
            return []

    def get_user_services(self, user_id: int) -> List[Dict]:
        """Get user's services - includes active and disabled services in grace period"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, pi.inbound_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    LEFT JOIN panel_inbounds pi ON c.panel_id = pi.panel_id AND c.inbound_id = pi.inbound_id
                    WHERE c.user_id = %s 
                      AND (
                        ((c.is_active = 1 OR c.status = 'active' OR c.status IS NULL OR c.status = '')
                         AND COALESCE(c.status, '') NOT IN ('disabled', 'expired', 'exhausted'))
                       OR (c.status IN ('disabled', 'expired', 'exhausted')
                           AND ((c.exhausted_at IS NOT NULL 
                                 AND DATE_ADD(c.exhausted_at, INTERVAL 24 HOUR) > NOW())
                              OR (c.expired_at IS NOT NULL 
                                  AND DATE_ADD(c.expired_at, INTERVAL 24 HOUR) > NOW()))))
                    ORDER BY c.created_at DESC
                ''', (user_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user services: {e}")
            return []
    
    def get_user_clients(self, user_identifier: int) -> List[Dict]:
        """Get user's clients by telegram ID or internal user ID - includes active and grace-period services"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, pi.inbound_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    JOIN users u ON c.user_id = u.id
                    LEFT JOIN panel_inbounds pi ON c.panel_id = pi.panel_id AND c.inbound_id = pi.inbound_id
                    WHERE (u.telegram_id = %s OR u.id = %s)
                      AND (
                        (
                          (c.is_active = 1 OR c.status = 'active' OR c.status IS NULL OR c.status = '')
                          AND COALESCE(c.status, '') NOT IN ('disabled', 'expired', 'exhausted')
                        )
                        OR (
                          c.status IN ('disabled', 'expired', 'exhausted')
                          AND (
                            (c.exhausted_at IS NOT NULL AND DATE_ADD(c.exhausted_at, INTERVAL 24 HOUR) > NOW())
                            OR (c.expired_at IS NOT NULL AND DATE_ADD(c.expired_at, INTERVAL 24 HOUR) > NOW())
                          )
                        )
                      )
                    ORDER BY c.created_at DESC
                ''', (user_identifier, user_identifier))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user clients: {e}")
            return []
    
    def get_user_service(self, service_id: int, user_id: int) -> Optional[Dict]:
        """Get a specific user service by service ID and user ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, pi.inbound_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    LEFT JOIN panel_inbounds pi ON c.panel_id = pi.panel_id AND c.inbound_id = pi.inbound_id
                    WHERE c.id = %s AND c.user_id = %s
                ''', (service_id, user_id))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user service: {e}")
            return None

    def get_service_warning_flags(self, service_id: int) -> Dict[str, bool]:
        """Get warning flags for a service to prevent duplicate notifications"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT warned_70_percent, warned_100_percent, warned_expired, 
                           warned_three_days, warned_one_week,
                           warned_95_percent, warned_98_percent,
                           warned_6_hours, warned_7_days
                    FROM clients 
                    WHERE id = %s
                ''', (service_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'warned_70_percent': bool(row['warned_70_percent']),
                        'warned_100_percent': bool(row['warned_100_percent']),
                        'warned_expired': bool(row['warned_expired']),
                        'warned_three_days': bool(row['warned_three_days']),
                        'warned_one_week': bool(row.get('warned_one_week', False)),
                        'warned_95_percent': bool(row.get('warned_95_percent', False)),
                        'warned_98_percent': bool(row.get('warned_98_percent', False)),
                        'warned_6_hours': bool(row.get('warned_6_hours', False)),
                        'warned_7_days': bool(row.get('warned_7_days', False))
                    }
                return {}
        except Exception as e:
            logger.error(f"Error getting service warning flags: {e}")
            return {}
    
    def get_services_by_panel_id(self, panel_id: int, include_inactive: bool = False) -> List[Dict]:
        """Get all services for a specific panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if include_inactive:
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.panel_type, u.telegram_id
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        LEFT JOIN users u ON c.user_id = u.id
                        WHERE c.panel_id = %s
                        ORDER BY c.created_at DESC
                    ''', (panel_id,))
                else:
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.panel_type, u.telegram_id
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        LEFT JOIN users u ON c.user_id = u.id
                        WHERE c.panel_id = %s AND c.is_active = 1
                        ORDER BY c.created_at DESC
                    ''', (panel_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting services by panel_id: {e}")
            return []
    
    def find_service_by_client_uuid(self, client_uuid: str, panel_id: int = None) -> Optional[Dict]:
        """Find a service by client_uuid, optionally filtered by panel_id"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if panel_id:
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.panel_type
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.client_uuid = %s AND c.panel_id = %s
                        LIMIT 1
                    ''', (client_uuid, panel_id))
                else:
                    cursor.execute('''
                        SELECT c.*, p.name as panel_name, p.panel_type
                        FROM clients c 
                        JOIN panels p ON c.panel_id = p.id 
                        WHERE c.client_uuid = %s
                        LIMIT 1
                    ''', (client_uuid,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error finding service by client_uuid: {e}")
            return None
    
    def create_invoice(self, user_id: int, amount: int, description: str = None, 
                      payment_method: str = 'card', panel_id: int = None, 
                      purchase_type: str = 'balance') -> int:
        """
        Create an invoice (wrapper for add_invoice to support simplified calls)
        Handles finding a default panel if panel_id is not provided.
        Handles converting Telegram ID to Internal User ID.
        """
        try:
            internal_user_id = user_id
            
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Resolve User ID (Telegram ID -> Internal ID)
                # First check if user_id exists as telegram_id
                cursor.execute('SELECT id FROM users WHERE telegram_id = %s', (user_id,))
                user_row = cursor.fetchone()
                
                if user_row:
                    internal_user_id = user_row['id']
                else:
                    # Check if it exists as internal id
                    cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
                    if not cursor.fetchone():
                        logger.error(f"Cannot create invoice: User {user_id} not found")
                        return 0

                # If panel_id is not provided, try to find a default one
                if not panel_id:
                    # Try to get first active panel
                    cursor.execute('SELECT id FROM panels WHERE is_active = 1 LIMIT 1')
                    row = cursor.fetchone()
                    if row:
                        panel_id = row['id']
                    else:
                        # Fallback to any panel
                        cursor.execute('SELECT id FROM panels LIMIT 1')
                        row = cursor.fetchone()
                        if row:
                            panel_id = row['id']
                        else:
                            # Create a default system panel if no panels exist
                            logger.warning("No panels found. Creating default system panel for invoice creation.")
                            cursor.execute('''
                                INSERT INTO panels (name, url, username, password, api_endpoint, is_active)
                                VALUES ('System Default', 'http://localhost', 'admin', 'admin', '/api', 0)
                            ''')
                            panel_id = cursor.lastrowid
                            conn.commit()
                            logger.info(f"Created default system panel with ID {panel_id}")
            
            return self.add_invoice(
                user_id=internal_user_id,
                panel_id=panel_id,
                gb_amount=0,  # Default for balance/unspecified
                amount=amount,
                payment_method=payment_method,
                notes=description,
                purchase_type=purchase_type
            )
        except Exception as e:
            logger.error(f"Error in create_invoice: {e}")
            return 0


    def add_invoice(self, user_id: int, panel_id: int, gb_amount: float, 
                   amount: int, payment_method: str = None, status: str = 'pending',
                   discount_code_id: int = None, discount_amount: int = None, original_amount: int = None,
                   product_id: int = None, duration_days: int = None, purchase_type: str = 'gigabyte',
                   notes: str = None) -> int:
        """Add invoice to database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    INSERT INTO invoices (user_id, panel_id, gb_amount, amount, payment_method, status, 
                                        discount_code_id, discount_amount, original_amount, product_id, duration_days, purchase_type, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (user_id, panel_id, gb_amount, amount, payment_method, status, 
                      discount_code_id, discount_amount, original_amount, product_id, duration_days, purchase_type, notes))
                
                invoice_id = cursor.lastrowid
                conn.commit()
                return invoice_id
        except Exception as e:
            logger.error(f"Error adding invoice: {e}")
            return 0
    
    def update_invoice_product_info(self, invoice_id: int, product_id: int, duration_days: int) -> bool:
        """Update invoice with product information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE invoices SET product_id = %s, duration_days = %s, purchase_type = 'plan'
                    WHERE id = %s
                ''', (product_id, duration_days, invoice_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating invoice product info: {e}")
            return False
    
    def update_invoice_status(self, invoice_id: int, status: str, order_id: str = None, 
                             payment_method: str = None, transaction_id: str = None) -> bool:
        """Update invoice status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Build query dynamically or use COALESCE to avoid overwriting with NULL if not provided
                # However, for simplicity and since we usually want to set them if provided:
                
                query = '''
                    UPDATE invoices 
                    SET status = %s, 
                        paid_at = CURRENT_TIMESTAMP
                '''
                params = [status]
                
                if order_id:
                    query += ', order_id = %s'
                    params.append(order_id)
                    
                if payment_method:
                    query += ', payment_method = %s'
                    params.append(payment_method)
                    
                if transaction_id:
                    query += ', transaction_id = %s'
                    params.append(transaction_id)
                    
                query += ' WHERE id = %s'
                params.append(invoice_id)
                
                cursor.execute(query, tuple(params))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating invoice status: {e}")
            return False
    
    def get_invoice(self, invoice_id: int) -> Optional[Dict]:
        """Get invoice by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM invoices WHERE id = %s', (invoice_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting invoice: {e}")
            return None
    
    def update_invoice_payment_link(self, invoice_id: int, payment_link: str, order_id: str = None) -> bool:
        """Update invoice payment link and order ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if order_id:
                    cursor.execute('''
                        UPDATE invoices SET payment_link = %s, order_id = %s WHERE id = %s
                    ''', (payment_link, order_id, invoice_id))
                else:
                    cursor.execute('''
                        UPDATE invoices SET payment_link = %s WHERE id = %s
                    ''', (payment_link, invoice_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating invoice payment link: {e}")
            return False
    
    def process_payment(self, user_id: int, invoice_id: int, amount: int) -> bool:
        """Process payment and update balances"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Update user balance
                cursor.execute('UPDATE users SET balance = balance - %s WHERE id = %s', (amount, user_id))
                
                # Add balance transaction
                cursor.execute('''
                    INSERT INTO balance_transactions (user_id, amount, transaction_type, description)
                    VALUES (%s, %s, %s, %s)
                ''', (user_id, -amount, "debit", f"Payment for invoice {invoice_id}"))
                
                # Update invoice status
                cursor.execute('''
                    UPDATE invoices SET status = 'paid', paid_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (invoice_id,))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error processing payment: {e}")
            return False
    
    # Utility Methods
    def is_admin(self, telegram_id: int) -> bool:
        """Check if user is admin"""
        user = self.get_user(telegram_id)
        return user['is_admin'] if user else False
    
    def get_all_admins(self) -> List[Dict]:
        """Get all admin users"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT * FROM users 
                    WHERE is_admin = 1 
                    ORDER BY created_at DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all admins: {e}")
            return []
    
    def get_database_stats(self) -> Dict:
        """Get database statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                stats = {}
                
                # Count users
                cursor.execute('SELECT COUNT(*) as count FROM users')
                stats['users'] = cursor.fetchone()['count']
                
                # Count panels
                cursor.execute('SELECT COUNT(*) as count FROM panels WHERE is_active = 1')
                stats['panels'] = cursor.fetchone()['count']
                
                # Count clients
                cursor.execute('SELECT COUNT(*) as count FROM clients WHERE is_active = 1')
                stats['clients'] = cursor.fetchone()['count']
                
                # Count invoices
                cursor.execute('SELECT COUNT(*) as count FROM invoices')
                stats['invoices'] = cursor.fetchone()['count']
                
                # Total balance
                cursor.execute('SELECT SUM(balance) as total FROM users')
                stats['total_balance'] = cursor.fetchone()['total'] or 0
                
                return stats
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}
    
    def cleanup_old_logs(self, days: int = 30):
        """Clean up old system logs"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    DELETE FROM system_logs 
                    WHERE created_at < DATE_SUB(NOW(), INTERVAL {} DAY)
                '''.format(days))
                deleted = cursor.rowcount
                conn.commit()
                logger.info(f"Cleaned up {deleted} old log entries")
                return deleted
        except Exception as e:
            logger.error(f"Error cleaning up logs: {e}")
            return 0
    
    def get_all_active_services(self) -> List[Dict]:
        """Get all services for monitoring - includes active and recently disabled services in grace period"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Get all active services + disabled services in grace period (within last 25 hours)
                # Only include services from active panels (is_active = 1)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, p.default_inbound_id
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    WHERE p.is_active = 1
                      AND (
                        (c.is_active = 1 OR c.status = 'active' OR c.status IS NULL OR c.status = '')
                        OR (
                          c.status IN ('disabled', 'expired', 'exhausted')
                          AND (
                            (c.exhausted_at IS NOT NULL AND DATE_ADD(c.exhausted_at, INTERVAL 25 HOUR) > NOW())
                            OR (c.expired_at IS NOT NULL AND DATE_ADD(c.expired_at, INTERVAL 25 HOUR) > NOW())
                          )
                        )
                      )
                    ORDER BY c.created_at DESC
                ''')
                
                services = cursor.fetchall()
                logger.info(f"📋 Found {len(services)} services to monitor (active + recently disabled in grace period, only from active panels)")
                return services
        except Exception as e:
            logger.error(f"❌ Error getting active services: {e}", exc_info=True)
            return []
    
    def update_service_notification(self, service_id: int, notified_80_percent: bool = False):
        """Update service notification status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET notified_80_percent = %s 
                    WHERE id = %s
                ''', (notified_80_percent, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating service notification: {e}")
    
    def update_service_70_percent_notification(self, service_id: int, notified: bool = True):
        """Update 70% notification status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET notified_70_percent = %s 
                    WHERE id = %s
                ''', (notified, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 70% notification: {e}")
    
    def update_service_70_percent_warning(self, service_id: int, warned: bool = True):
        """Update 70% warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_70_percent = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 70% warning: {e}")
    
    def update_service_100_percent_warning(self, service_id: int, warned: bool = True):
        """Update 100% warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_100_percent = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 100% warning: {e}")

    def update_service_95_percent_warning(self, service_id: int, warned: bool = True):
        """Update 95% warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_95_percent = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 95% warning: {e}")

    def update_service_98_percent_warning(self, service_id: int, warned: bool = True):
        """Update 98% warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_98_percent = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 98% warning: {e}")

    
    def update_service_three_days_warning(self, service_id: int, warned: bool = True):
        """Update 3 days expiry warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_three_days = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 3 days warning: {e}")

    def update_service_7_days_warning(self, service_id: int, warned: bool = True):
        """Update 7 days expiry warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_7_days = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 7 days warning: {e}")

    def update_service_6_hours_warning(self, service_id: int, warned: bool = True):
        """Update 6 hours expiry warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_6_hours = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating 6 hours warning: {e}")


    def update_service_expired_warning(self, service_id: int, warned: bool = True):
        """Update expired warning status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET warned_expired = %s 
                    WHERE id = %s
                ''', (warned, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating expired warning: {e}")
    
    def update_service_status(self, service_id: int, status: str, is_active: int = None):
        """Update service status and optionally is_active flag"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if is_active is not None:
                    cursor.execute('''
                        UPDATE clients 
                        SET status = %s, is_active = %s
                        WHERE id = %s
                    ''', (status, is_active, service_id))
                else:
                    # If is_active not provided, set it based on status
                    is_active_value = 1 if status == 'active' else 0
                    cursor.execute('''
                        UPDATE clients 
                        SET status = %s, is_active = %s
                        WHERE id = %s
                    ''', (status, is_active_value, service_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating service status: {e}")
    
    def update_service_exhaustion_time(self, service_id: int):
        """Update service exhaustion time"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET exhausted_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                ''', (service_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating service exhaustion time: {e}")
    
    def update_service_expiration_time(self, service_id: int):
        """Update service expiration time"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET expired_at = CURRENT_TIMESTAMP 
                    WHERE id = %s
                ''', (service_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating service expiration time: {e}")
    
    def get_services_for_deletion(self) -> List[Dict]:
        """Get services that should be deleted after 24 hours"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Only include services from active panels
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, p.default_inbound_id
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    WHERE p.is_active = 1
                      AND c.status IN ('disabled', 'exhausted')
                      AND c.exhausted_at IS NOT NULL
                      AND DATE_ADD(c.exhausted_at, INTERVAL 24 HOUR) < NOW()
                    ORDER BY c.exhausted_at ASC
                ''')
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting services for deletion: {e}")
            return []
    
    def get_expired_plan_services_for_deletion(self) -> List[Dict]:
        """Get expired plan-based services that should be deleted after 24 hours grace period"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Only include plan-based services (with product_id) from active panels
                # that have expired and passed the grace period
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, p.default_inbound_id
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    WHERE p.is_active = 1
                      AND c.product_id IS NOT NULL
                      AND c.expired_at IS NOT NULL
                      AND c.status IN ('disabled', 'expired')
                      AND DATE_ADD(c.expired_at, INTERVAL 24 HOUR) < NOW()
                    ORDER BY c.expired_at ASC
                ''')
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting expired plan services for deletion: {e}")
            return []
    
    def delete_service(self, service_id: int):
        """Delete a service"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM clients WHERE id = %s', (service_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Error deleting service: {e}")
    
    # Referral System Methods
    def generate_referral_code(self) -> str:
        """Generate unique referral code"""
        import secrets
        import string
        while True:
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            # Check if code already exists
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT id FROM users WHERE referral_code = %s', (code,))
                if not cursor.fetchone():
                    return code
    
    def get_user_by_referral_code(self, referral_code: str):
        """Get user by referral code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM users WHERE referral_code = %s', (referral_code,))
                row = cursor.fetchone()
                # cursor(dictionary=True) already returns a dict, so just return it directly
                return row if row else None
        except Exception as e:
            logger.error(f"Error getting user by referral code: {e}")
            return None
    
    def add_referral(self, referrer_id: int, referred_id: int, reward_amount: int) -> int:
        """Add referral record and return referral id"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, reward_amount)
                    VALUES (%s, %s, %s)
                ''', (referrer_id, referred_id, reward_amount))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding referral: {e}")
            return 0
    
    def pay_referral_reward(self, referral_id: int) -> bool:
        """Mark referral reward as paid"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE referrals 
                    SET reward_paid = 1, paid_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (referral_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error paying referral reward: {e}")
            return False
    
    def get_user_referrals(self, user_id: int):
        """Get all referrals for a user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT r.*, u.first_name, u.username, u.created_at as user_created_at
                    FROM referrals r
                    JOIN users u ON r.referred_id = u.id
                    WHERE r.referrer_id = %s
                    ORDER BY r.created_at DESC
                ''', (user_id,))
                rows = cursor.fetchall()
                return [dict(zip([d[0] for d in cursor.description], row)) for row in rows]
        except Exception as e:
            logger.error(f"Error getting user referrals: {e}")
            return []
    
    def update_user_referral_stats(self, user_id: int, earnings: int = 0) -> bool:
        """Update user referral statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE users 
                    SET total_referrals = total_referrals + 1,
                        total_referral_earnings = total_referral_earnings + %s
                    WHERE id = %s
                ''', (earnings, user_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating referral stats: {e}")
            return False
    
    def get_all_users(self) -> List[Dict]:
        """Get all users with their details"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT u.*, 
                           COUNT(DISTINCT c.id) as total_services
                    FROM users u
                    LEFT JOIN clients c ON u.id = c.user_id AND c.is_active = 1
                    GROUP BY u.id
                    ORDER BY u.created_at DESC
                ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def get_all_users_telegram_ids(self) -> List[int]:
        """Get all user telegram IDs for broadcasting"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT telegram_id FROM users WHERE is_active = 1 ORDER BY created_at DESC')
                return [row['telegram_id'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        """Get user by telegram ID (alias for get_user)"""
        return self.get_user(telegram_id)
    
    def add_transaction_only(self, telegram_id: int, amount: int, transaction_type: str, description: str = None) -> bool:
        """Add a transaction record without changing balance (for gateway payments)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Get user database ID
                cursor.execute('SELECT id FROM users WHERE telegram_id = %s', (telegram_id,))
                user_row = cursor.fetchone()
                
                if not user_row:
                    return False
                
                # Log transaction only (no balance change)
                cursor.execute('''
                    INSERT INTO balance_transactions (user_id, amount, transaction_type, description)
                    VALUES (%s, %s, %s, %s)
                ''', (user_row['id'], amount, transaction_type, description))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding transaction: {e}")
            return False
    
    def get_user_transactions(self, telegram_id: int, limit: int = 10) -> List[Dict]:
        """Get user's transactions from balance_transactions and invoices, combined and sorted"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get user database ID
                cursor.execute('SELECT id FROM users WHERE telegram_id = %s', (telegram_id,))
                user_row = cursor.fetchone()
                if not user_row:
                    return []
                
                user_db_id = user_row['id']
                
                # Get balance transactions
                cursor.execute('''
                    SELECT bt.*, 'balance_transaction' as source
                    FROM balance_transactions bt
                    WHERE bt.user_id = %s
                    ORDER BY bt.created_at DESC
                    LIMIT %s
                ''', (user_db_id, limit * 2))  # Get more to combine with invoices
                balance_transactions = cursor.fetchall()
                
                # Get invoices (paid and completed)
                cursor.execute('''
                    SELECT 
                        i.id,
                        i.user_id,
                        i.panel_id,
                        i.gb_amount,
                        i.amount,
                        i.payment_method,
                        i.status,
                        i.created_at,
                        i.paid_at,
                        i.order_id,
                        p.name as panel_name,
                        pr.name as product_name,
                        i.purchase_type,
                        i.duration_days,
                        'invoice' as source
                    FROM invoices i
                    LEFT JOIN panels p ON i.panel_id = p.id
                    LEFT JOIN products pr ON i.product_id = pr.id
                    WHERE i.user_id = %s 
                    AND i.status IN ('paid', 'completed')
                    ORDER BY COALESCE(i.paid_at, i.created_at) DESC
                    LIMIT %s
                ''', (user_db_id, limit * 2))
                invoices = cursor.fetchall()
                
                # Combine and convert to unified format
                all_transactions = []
                
                # Add balance transactions
                for bt in balance_transactions:
                    all_transactions.append({
                        'id': bt['id'],
                        'user_id': bt['user_id'],
                        'amount': bt['amount'],
                        'transaction_type': bt['transaction_type'],
                        'description': bt.get('description', ''),
                        'created_at': bt['created_at'],
                        'source': 'balance_transaction'
                    })
                
                # Add invoices (only if not already in balance_transactions)
                invoice_ids_in_transactions = {bt.get('description', '') for bt in balance_transactions if 'فاکتور #' in str(bt.get('description', ''))}
                
                for inv in invoices:
                    invoice_id = inv['id']
                    # Check if this invoice is already represented in balance_transactions
                    invoice_desc_pattern = f'فاکتور #{invoice_id}'
                    if not any(invoice_desc_pattern in str(bt.get('description', '')) for bt in balance_transactions):
                        # Create transaction from invoice
                        panel_name = inv.get('panel_name', f'پنل {inv["panel_id"]}')
                        volume_gb = inv['gb_amount']
                        amount = -inv['amount']  # Negative for purchases
                        
                        if inv.get('purchase_type') == 'plan' and inv.get('product_name'):
                            product_name = inv['product_name']
                            duration_days = inv.get('duration_days', 0)
                            description = f'خرید پلن {product_name} - {volume_gb} گیگابایت ({duration_days} روز) - {panel_name} (فاکتور #{invoice_id})'
                        else:
                            description = f'خرید سرویس {volume_gb} گیگابایت - {panel_name} (فاکتور #{invoice_id})'
                        
                        all_transactions.append({
                            'id': invoice_id + 1000000,  # Offset to avoid conflicts
                            'user_id': inv['user_id'],
                            'amount': amount,
                            'transaction_type': 'service_purchase',
                            'description': description,
                            'created_at': inv.get('paid_at') or inv['created_at'],
                            'source': 'invoice'
                        })
                
                # Sort by created_at descending (newest first)
                all_transactions.sort(key=lambda x: x['created_at'], reverse=True)
                
                # Return limited results
                return all_transactions[:limit]
                
        except Exception as e:
            logger.error(f"Error getting user transactions: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def get_user_services_paginated(self, telegram_id: int, page: int = 1, per_page: int = 10) -> Tuple[List[Dict], int]:
        """Get user's services with pagination - includes active and disabled services in grace period"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get total count - includes services in grace period
                cursor.execute('''
                    SELECT COUNT(*) as total 
                    FROM clients c 
                    JOIN users u ON c.user_id = u.id
                    WHERE u.telegram_id = %s
                      AND (c.is_active = 1 
                       OR (c.status = 'disabled' 
                           AND ((c.exhausted_at IS NOT NULL 
                                 AND DATE_ADD(c.exhausted_at, INTERVAL 24 HOUR) > NOW())
                              OR (c.expired_at IS NOT NULL 
                                  AND DATE_ADD(c.expired_at, INTERVAL 24 HOUR) > NOW()))))
                ''', (telegram_id,))
                total = cursor.fetchone()['total']
                
                # Get paginated services - includes services in grace period
                offset = (page - 1) * per_page
                cursor.execute('''
                    SELECT c.*, p.name as panel_name 
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    JOIN users u ON c.user_id = u.id
                    WHERE u.telegram_id = %s
                      AND (c.is_active = 1 
                       OR (c.status = 'disabled' 
                           AND ((c.exhausted_at IS NOT NULL 
                                 AND DATE_ADD(c.exhausted_at, INTERVAL 24 HOUR) > NOW())
                              OR (c.expired_at IS NOT NULL 
                                  AND DATE_ADD(c.expired_at, INTERVAL 24 HOUR) > NOW()))))
                    ORDER BY c.created_at DESC
                    LIMIT %s OFFSET %s
                ''', (telegram_id, per_page, offset))
                
                services = [dict(row) for row in cursor.fetchall()]
                return services, total
        except Exception as e:
            logger.error(f"Error getting user services paginated: {e}")
            return [], 0
    
    def update_user_balance_direct(self, telegram_id: int, new_balance: int) -> bool:
        """Update user balance directly (for admin adjustments)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('UPDATE users SET balance = %s WHERE telegram_id = %s', (new_balance, telegram_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating user balance directly: {e}")
            return False
    
    # Discount Code Management Methods
    def create_discount_code(self, code: str, discount_type: str, discount_value: float,
                            max_discount_amount: int = None, min_purchase_amount: int = 0,
                            max_uses: int = 0, valid_from: datetime = None, valid_until: datetime = None,
                            applicable_to: str = 'all', created_by: int = None, description: str = None,
                            notes: str = None) -> int:
        """Create a new discount code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    INSERT INTO discount_codes 
                    (code, discount_type, discount_value, max_discount_amount, min_purchase_amount,
                     max_uses, valid_from, valid_until, applicable_to, created_by, description, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (code.upper(), discount_type, discount_value, max_discount_amount, min_purchase_amount,
                     max_uses, valid_from, valid_until, applicable_to, created_by, description, notes))
                code_id = cursor.lastrowid
                conn.commit()
                self.log_system_event('INFO', f'Discount code created: {code}', 'discount_system', created_by)
                return code_id
        except Exception as e:
            logger.error(f"Error creating discount code: {e}")
            return 0
    
    def get_discount_code(self, code: str) -> Optional[Dict]:
        """Get discount code by code string"""
        try:
            # Ensure code is a string before calling upper()
            if not isinstance(code, str):
                code = str(code)
            
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM discount_codes WHERE code = %s', (code.upper(),))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting discount code: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def get_discount_code_by_id(self, code_id: int) -> Optional[Dict]:
        """Get discount code by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM discount_codes WHERE id = %s', (code_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting discount code by ID: {e}")
            return None
    
    def validate_discount_code(self, code: str, user_id: int, amount: int) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Validate discount code for a user and amount"""
        try:
            discount_code = self.get_discount_code(code)
            if not discount_code:
                return False, "کد تخفیف یافت نشد", None
            
            if not discount_code['is_active']:
                return False, "کد تخفیف غیرفعال است", None
            
            # Check date validity
            now = datetime.now()
            if discount_code['valid_from']:
                valid_from = datetime.fromisoformat(discount_code['valid_from']) if isinstance(discount_code['valid_from'], str) else discount_code['valid_from']
                if now < valid_from:
                    return False, f"کد تخفیف از تاریخ {valid_from.strftime('%Y-%m-%d')} فعال می‌شود", None
            
            if discount_code['valid_until']:
                valid_until = datetime.fromisoformat(discount_code['valid_until']) if isinstance(discount_code['valid_until'], str) else discount_code['valid_until']
                if now > valid_until:
                    return False, "کد تخفیف منقضی شده است", None
            
            # Check max uses
            if discount_code['max_uses'] > 0 and discount_code['used_count'] >= discount_code['max_uses']:
                return False, "حداکثر تعداد استفاده از این کد تخفیف به پایان رسیده است", None
            
            # Check min purchase amount
            if discount_code['min_purchase_amount'] > 0 and amount < discount_code['min_purchase_amount']:
                return False, f"حداقل مبلغ خرید برای استفاده از این کد تخفیف {discount_code['min_purchase_amount']:,} تومان است", None
            
            # Check if user already used this code
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT COUNT(*) as count FROM discount_code_usage
                    WHERE code_id = %s AND user_id = %s
                ''', (discount_code['id'], user_id))
                usage_count = cursor.fetchone()['count']
            
            if usage_count > 0 and discount_code['max_uses'] == 1:
                return False, "شما قبلاً از این کد تخفیف استفاده کرده‌اید", None
            
            return True, None, discount_code
        except Exception as e:
            logger.error(f"Error validating discount code: {e}")
            return False, f"خطا در بررسی کد تخفیف: {str(e)}", None
    
    def apply_discount_code(self, code_id: int, user_id: int, invoice_id: int, 
                            amount_before: int, discount_amount: int, amount_after: int) -> bool:
        """Record discount code usage"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Record usage
                cursor.execute('''
                    INSERT INTO discount_code_usage
                    (code_id, user_id, invoice_id, amount_before_discount, discount_amount, amount_after_discount)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (code_id, user_id, invoice_id, amount_before, discount_amount, amount_after))
                
                # Update used count
                cursor.execute('''
                    UPDATE discount_codes SET used_count = used_count + 1
                    WHERE id = %s
                ''', (code_id,))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error applying discount code: {e}")
            return False
    
    def get_all_discount_codes(self, active_only: bool = False) -> List[Dict]:
        """Get all discount codes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM discount_codes"
                if active_only:
                    query += " WHERE is_active = 1"
                query += " ORDER BY created_at DESC"
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting discount codes: {e}")
            return []
    
    def update_discount_code(self, code_id: int, **kwargs) -> bool:
        """Update discount code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                updates = []
                params = []
                
                allowed_fields = ['code', 'discount_type', 'discount_value', 'max_discount_amount',
                                'min_purchase_amount', 'max_uses', 'is_active', 'valid_from',
                                'valid_until', 'applicable_to', 'description', 'notes']
                
                for key, value in kwargs.items():
                    if key in allowed_fields:
                        updates.append(f"{key} = %s")
                        params.append(value)
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(code_id)
                
                query = f"UPDATE discount_codes SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating discount code: {e}")
            return False
    
    def delete_discount_code(self, code_id: int) -> bool:
        """Delete discount code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM discount_codes WHERE id = %s', (code_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error deleting discount code: {e}")
            return False
    
    # Gift Code Management Methods
    def create_gift_code(self, code: str, amount: int, max_uses: int = 1,
                        valid_from: datetime = None, valid_until: datetime = None,
                        created_by: int = None, description: str = None, notes: str = None) -> int:
        """Create a new gift code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    INSERT INTO gift_codes 
                    (code, amount, max_uses, valid_from, valid_until, created_by, description, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (code.upper(), amount, max_uses, valid_from, valid_until, created_by, description, notes))
                code_id = cursor.lastrowid
                conn.commit()
                self.log_system_event('INFO', f'Gift code created: {code}', 'gift_system', created_by)
                return code_id
        except Exception as e:
            logger.error(f"Error creating gift code: {e}")
            return 0
    
    def get_gift_code(self, code: str) -> Optional[Dict]:
        """Get gift code by code string"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM gift_codes WHERE code = %s', (code.upper(),))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting gift code: {e}")
            return None
    
    def get_gift_code_by_id(self, code_id: int) -> Optional[Dict]:
        """Get gift code by ID"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM gift_codes WHERE id = %s', (code_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting gift code by ID: {e}")
            return None
    
    def validate_gift_code(self, code: str, user_id: int) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Validate gift code for a user"""
        try:
            gift_code = self.get_gift_code(code)
            if not gift_code:
                return False, "کد هدیه یافت نشد", None
            
            if not gift_code['is_active']:
                return False, "کد هدیه غیرفعال است", None
            
            # Check date validity
            now = datetime.now()
            if gift_code['valid_from']:
                valid_from = datetime.fromisoformat(gift_code['valid_from']) if isinstance(gift_code['valid_from'], str) else gift_code['valid_from']
                if now < valid_from:
                    return False, f"کد هدیه از تاریخ {valid_from.strftime('%Y-%m-%d')} فعال می‌شود", None
            
            if gift_code['valid_until']:
                valid_until = datetime.fromisoformat(gift_code['valid_until']) if isinstance(gift_code['valid_until'], str) else gift_code['valid_until']
                if now > valid_until:
                    return False, "کد هدیه منقضی شده است", None
            
            # Check max uses
            if gift_code['max_uses'] > 0 and gift_code['used_count'] >= gift_code['max_uses']:
                return False, "حداکثر تعداد استفاده از این کد هدیه به پایان رسیده است", None
            
            # Check if user already used this code
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT COUNT(*) as count FROM gift_code_usage
                    WHERE code_id = %s AND user_id = %s
                ''', (gift_code['id'], user_id))
                usage_count = cursor.fetchone()['count']
            
            if usage_count > 0 and gift_code['max_uses'] == 1:
                return False, "شما قبلاً از این کد هدیه استفاده کرده‌اید", None
            
            return True, None, gift_code
        except Exception as e:
            logger.error(f"Error validating gift code: {e}")
            return False, f"خطا در بررسی کد هدیه: {str(e)}", None
    
    def apply_gift_code(self, code_id: int, user_id: int, amount: int) -> bool:
        """Apply gift code and add balance to user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Record usage
                cursor.execute('''
                    INSERT INTO gift_code_usage (code_id, user_id, amount)
                    VALUES (%s, %s, %s)
                ''', (code_id, user_id, amount))
                
                # Update used count
                cursor.execute('''
                    UPDATE gift_codes SET used_count = used_count + 1
                    WHERE id = %s
                ''', (code_id,))
                
                # Add balance to user
                cursor.execute('''
                    UPDATE users SET balance = balance + %s
                    WHERE id = %s
                ''', (amount, user_id))
                
                # Log transaction
                cursor.execute('''
                    INSERT INTO balance_transactions (user_id, amount, transaction_type, description)
                    VALUES (%s, %s, %s, %s)
                ''', (user_id, amount, 'gift_code', f'Gift code redemption'))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error applying gift code: {e}")
            return False
    
    def get_all_gift_codes(self, active_only: bool = False) -> List[Dict]:
        """Get all gift codes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM gift_codes"
                if active_only:
                    query += " WHERE is_active = 1"
                query += " ORDER BY created_at DESC"
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting gift codes: {e}")
            return []
    
    def update_gift_code(self, code_id: int, **kwargs) -> bool:
        """Update gift code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                updates = []
                params = []
                
                allowed_fields = ['code', 'amount', 'max_uses', 'is_active', 'valid_from',
                                'valid_until', 'description', 'notes']
                
                for key, value in kwargs.items():
                    if key in allowed_fields:
                        updates.append(f"{key} = %s")
                        params.append(value)
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(code_id)
                
                query = f"UPDATE gift_codes SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating gift code: {e}")
            return False
    
    def delete_gift_code(self, code_id: int) -> bool:
        """Delete gift code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM gift_codes WHERE id = %s', (code_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error deleting gift code: {e}")
            return False
    
    def get_discount_code_statistics(self, code_id: int) -> Dict:
        """Get statistics for a discount code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_uses,
                        SUM(discount_amount) as total_discount,
                        SUM(amount_after_discount) as total_revenue
                    FROM discount_code_usage
                    WHERE code_id = %s
                ''', (code_id,))
                stats = dict(cursor.fetchone())
                
                cursor.execute('''
                    SELECT COUNT(DISTINCT user_id) as unique_users
                    FROM discount_code_usage
                    WHERE code_id = %s
                ''', (code_id,))
                stats.update(dict(cursor.fetchone()))
                
                return stats
        except Exception as e:
            logger.error(f"Error getting discount code statistics: {e}")
            return {}
    
    def get_gift_code_statistics(self, code_id: int) -> Dict:
        """Get statistics for a gift code"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_uses,
                        SUM(amount) as total_amount
                    FROM gift_code_usage
                    WHERE code_id = %s
                ''', (code_id,))
                stats = dict(cursor.fetchone())
                
                cursor.execute('''
                    SELECT COUNT(DISTINCT user_id) as unique_users
                    FROM gift_code_usage
                    WHERE code_id = %s
                ''', (code_id,))
                stats.update(dict(cursor.fetchone()))
                
                return stats
        except Exception as e:
            logger.error(f"Error getting gift code statistics: {e}")
            return {}
    
    # Reserved Services Management Methods
    def add_reserved_service(self, client_id: int, product_id: int, volume_gb: int, duration_days: int) -> int:
        """Add a reserved service for renewal"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    INSERT INTO reserved_services (client_id, product_id, volume_gb, duration_days, status)
                    VALUES (%s, %s, %s, %s, 'reserved')
                ''', (client_id, product_id, volume_gb, duration_days))
                conn.commit()
                reserved_id = cursor.lastrowid
                logger.info(f"✅ Reserved service added: ID {reserved_id} for client {client_id}")
                return reserved_id
        except Exception as e:
            logger.error(f"Error adding reserved service: {e}")
            return None
    
    def get_reserved_service(self, client_id: int) -> Optional[Dict]:
        """Get active reserved service for a client"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT rs.*, p.name as product_name
                    FROM reserved_services rs
                    JOIN products p ON rs.product_id = p.id
                    WHERE rs.client_id = %s AND rs.status = 'reserved'
                    ORDER BY rs.reserved_at DESC
                    LIMIT 1
                ''', (client_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting reserved service: {e}")
            return None
    
    def activate_reserved_service(self, reserved_id: int) -> bool:
        """Activate a reserved service"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                from datetime import datetime
                cursor.execute('''
                    UPDATE reserved_services
                    SET status = 'activated', activated_at = %s
                    WHERE id = %s
                ''', (datetime.now().isoformat(), reserved_id))
                conn.commit()
                logger.info(f"✅ Reserved service activated: ID {reserved_id}")
                return True
        except Exception as e:
            logger.error(f"Error activating reserved service: {e}")
            return False
    
    def delete_reserved_service(self, reserved_id: int) -> bool:
        """Delete a reserved service"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM reserved_services WHERE id = %s', (reserved_id,))
                conn.commit()
                logger.info(f"✅ Reserved service deleted: ID {reserved_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting reserved service: {e}")
            return False
    
    def update_panel_settings(self, panel_id: int, settings: Dict) -> bool:
        """Update panel settings"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                updates = []
                params = []
                
                # Map settings to database columns
                # This mapping depends on what settings are being updated and what columns exist
                # Based on usage: naming_method is stored in extra_config
                
                # First get current extra_config
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                row = cursor.fetchone()
                if not row:
                    return False
                    
                current_config = json.loads(row['extra_config']) if row['extra_config'] else {}
                
                # Update config with new settings
                config_changed = False
                for key, value in settings.items():
                    # Check if it's a direct column update or extra_config
                    if key in ['name', 'url', 'username', 'password', 'panel_type', 'price_per_gb', 'is_active']:
                        updates.append(f"{key} = %s")
                        params.append(value)
                    else:
                        # Assume it goes into extra_config
                        current_config[key] = value
                        config_changed = True
                
                if config_changed:
                    updates.append("extra_config = %s")
                    params.append(json.dumps(current_config))
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(panel_id)
                
                query = f"UPDATE panels SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating panel settings: {e}")
            return False

    # Menu Buttons Management Methods
    def get_menu_buttons(self, is_admin: bool = False) -> List[Dict]:
        """Get all menu buttons ordered by display_order for current database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if is_admin:
                    # Admin sees buttons visible for admin OR users
                    cursor.execute('''
                        SELECT * FROM menu_buttons 
                        WHERE database_name = %s 
                        AND is_active = 1 
                        AND (is_visible_for_admin = 1 OR is_visible_for_users = 1)
                        ORDER BY display_order ASC, row_position ASC, column_position ASC
                    ''', (self.database_name,))
                else:
                    # Regular users only see buttons visible for users
                    cursor.execute('''
                        SELECT * FROM menu_buttons 
                        WHERE database_name = %s 
                        AND is_active = 1 
                        AND is_visible_for_users = 1
                        ORDER BY display_order ASC, row_position ASC, column_position ASC
                    ''', (self.database_name,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting menu buttons: {e}")
            return []
    
    def get_all_menu_buttons(self) -> List[Dict]:
        """Get all menu buttons including inactive ones for current database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT * FROM menu_buttons 
                    WHERE database_name = %s
                    ORDER BY display_order ASC, row_position ASC, column_position ASC
                ''', (self.database_name,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all menu buttons: {e}")
            return []
    
    def get_menu_button(self, button_key: str) -> Optional[Dict]:
        """Get a specific menu button by key for current database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM menu_buttons WHERE database_name = %s AND button_key = %s', 
                              (self.database_name, button_key))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting menu button: {e}")
            return None
    
    def add_menu_button(self, button_key: str, button_text: str, callback_data: str,
                        button_type: str = 'callback', web_app_url: str = None,
                        row_position: int = 0, column_position: int = 0,
                        is_visible_for_admin: bool = False, is_visible_for_users: bool = True,
                        requires_webapp: bool = False, display_order: int = 0) -> int:
        """Add a new menu button for current database, or update if exists"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Check if button already exists
                existing_button = self.get_menu_button(button_key)
                
                if existing_button:
                    # Button exists, update it instead
                    self.update_menu_button(
                        button_key=button_key,
                        button_text=button_text,
                        callback_data=callback_data,
                        button_type=button_type,
                        web_app_url=web_app_url,
                        row_position=row_position,
                        column_position=column_position,
                        is_visible_for_admin=is_visible_for_admin,
                        is_visible_for_users=is_visible_for_users,
                        display_order=display_order
                    )
                    logger.info(f'Menu button updated (was existing): {button_key}')
                    return existing_button.get('id', 0)
                else:
                    # Button doesn't exist, insert new one
                    cursor.execute('''
                        INSERT INTO menu_buttons 
                        (database_name, button_key, button_text, callback_data, button_type, web_app_url, 
                         row_position, column_position, is_visible_for_admin, is_visible_for_users, 
                         requires_webapp, display_order)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (self.database_name, button_key, button_text, callback_data, button_type, web_app_url,
                         row_position, column_position, 1 if is_visible_for_admin else 0,
                         1 if is_visible_for_users else 0, 1 if requires_webapp else 0, display_order))
                    button_id = cursor.lastrowid
                    conn.commit()
                    self.log_system_event('INFO', f'Menu button added: {button_key}', 'menu_management')
                    return button_id
        except Exception as e:
            logger.error(f"Error adding menu button: {e}")
            return 0
    
    def update_menu_button(self, button_key: str, button_text: str = None,
                          callback_data: str = None, button_type: str = None,
                          web_app_url: str = None, row_position: int = None,
                          column_position: int = None, is_active: bool = None,
                          is_visible_for_admin: bool = None, is_visible_for_users: bool = None,
                          display_order: int = None) -> bool:
        """Update a menu button"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                updates = []
                params = []
                
                if button_text is not None:
                    updates.append("button_text = %s")
                    params.append(button_text)
                if callback_data is not None:
                    updates.append("callback_data = %s")
                    params.append(callback_data)
                if button_type is not None:
                    updates.append("button_type = %s")
                    params.append(button_type)
                if web_app_url is not None:
                    updates.append("web_app_url = %s")
                    params.append(web_app_url)
                if row_position is not None:
                    updates.append("row_position = %s")
                    params.append(row_position)
                if column_position is not None:
                    updates.append("column_position = %s")
                    params.append(column_position)
                if is_active is not None:
                    updates.append("is_active = %s")
                    params.append(1 if is_active else 0)
                if is_visible_for_admin is not None:
                    updates.append("is_visible_for_admin = %s")
                    params.append(1 if is_visible_for_admin else 0)
                if is_visible_for_users is not None:
                    updates.append("is_visible_for_users = %s")
                    params.append(1 if is_visible_for_users else 0)
                if display_order is not None:
                    updates.append("display_order = %s")
                    params.append(display_order)
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(self.database_name)
                params.append(button_key)
                
                query = f"UPDATE menu_buttons SET {', '.join(updates)} WHERE database_name = %s AND button_key = %s"
                cursor.execute(query, params)
                conn.commit()
                
                self.log_system_event('INFO', f'Menu button updated: {button_key}', 'menu_management')
                return True
        except Exception as e:
            logger.error(f"Error updating menu button: {e}")
            return False
    
    def delete_menu_button(self, button_key: str) -> bool:
        """Delete a menu button for current database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM menu_buttons WHERE database_name = %s AND button_key = %s', 
                              (self.database_name, button_key))
                conn.commit()
                self.log_system_event('INFO', f'Menu button deleted: {button_key}', 'menu_management')
                return True
        except Exception as e:
            logger.error(f"Error deleting menu button: {e}")
            return False
    
    def update_menu_button_positions(self, buttons_layout: List[Dict]) -> bool:
        """Update positions of multiple buttons at once for current database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                for button in buttons_layout:
                    cursor.execute('''
                        UPDATE menu_buttons 
                        SET row_position = %s, column_position = %s, display_order = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE database_name = %s AND button_key = %s
                    ''', (button.get('row_position', 0), button.get('column_position', 0),
                          button.get('display_order', 0), self.database_name, button.get('button_key')))
                conn.commit()
                self.log_system_event('INFO', f'Menu buttons layout updated: {len(buttons_layout)} buttons', 'menu_management')
                return True
        except Exception as e:
            logger.error(f"Error updating menu button positions: {e}")
            return False
    
    def toggle_menu_button(self, button_key: str) -> bool:
        """Toggle button active status for current database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE menu_buttons 
                    SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP
                    WHERE database_name = %s AND button_key = %s
                ''', (self.database_name, button_key))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error toggling menu button: {e}")
            return False

    def get_all_reserved_services(self, status: str = None) -> List[Dict]:
        """Get all reserved services, optionally filtered by status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if status:
                    cursor.execute('''
                        SELECT rs.*, p.name as product_name, c.user_id, c.client_name, c.client_uuid
                        FROM reserved_services rs
                        JOIN products p ON rs.product_id = p.id
                        JOIN clients c ON rs.client_id = c.id
                        WHERE rs.status = %s
                        ORDER BY rs.reserved_at DESC
                    ''', (status,))
                else:
                    cursor.execute('''
                        SELECT rs.*, p.name as product_name, c.user_id, c.client_name, c.client_uuid
                        FROM reserved_services rs
                        JOIN products p ON rs.product_id = p.id
                        JOIN clients c ON rs.client_id = c.id
                        ORDER BY rs.reserved_at DESC
                    ''')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting reserved services: {e}")
            return []
    
    def get_all_services_paginated(self, page: int = 1, per_page: int = 10, search: str = None) -> Tuple[List[Dict], int]:
        """Get all services with pagination and optional search"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Build query with optional search
                query = '''
                    SELECT c.*, p.name as panel_name, u.telegram_id, u.username, u.first_name, u.last_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    JOIN users u ON c.user_id = u.id
                '''
                
                where_clauses = []
                params = []
                
                if search:
                    # SECURITY: Sanitize and limit search input length
                    search = search.strip()[:100]  # Limit to 100 characters
                    if search:
                        search_pattern = f'%{search}%'
                        where_clauses.append('''
                            (c.client_name LIKE %s OR 
                             u.username LIKE %s OR 
                             CAST(u.telegram_id AS CHAR) LIKE %s OR
                             u.first_name LIKE %s OR
                             u.last_name LIKE %s OR
                             p.name LIKE %s)
                        ''')
                        params.extend([search_pattern] * 6)
                
                if where_clauses:
                    query += ' WHERE ' + ' AND '.join(where_clauses)
                
                # Get total count
                count_query = query.replace('SELECT c.*, p.name as panel_name, u.telegram_id, u.username, u.first_name, u.last_name', 'SELECT COUNT(*) as count')
                cursor.execute(count_query, params)
                result = cursor.fetchone()
                total = result['count'] if result else 0
                
                # Get paginated results
                query += ' ORDER BY c.created_at DESC LIMIT %s OFFSET %s'
                params.extend([per_page, (page - 1) * per_page])
                cursor.execute(query, params)
                
                services = [dict(row) for row in cursor.fetchall()]
                return services, total
        except Exception as e:
            logger.error(f"Error getting paginated services: {e}")
            return [], 0
    
    def get_gateway_invoices_paginated(self, page: int = 1, per_page: int = 10, search: str = None, status_filter: str = None) -> Tuple[List[Dict], int]:
        """Get gateway invoices with pagination and optional search"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Build query with optional search and status filter
                query = '''
                    SELECT i.*, u.telegram_id, u.username, u.first_name, u.last_name, p.name as panel_name
                    FROM invoices i 
                    JOIN users u ON i.user_id = u.id 
                    JOIN panels p ON i.panel_id = p.id
                    WHERE 1=1
                '''
                
                params = []
                
                # Status filter
                if status_filter:
                    if status_filter == 'successful':
                        query += " AND i.status IN ('paid', 'completed')"
                    elif status_filter == 'pending':
                        query += " AND i.status IN ('pending', 'pending_approval')"
                    elif status_filter == 'all':
                        pass  # Show all
                
                if search:
                    # SECURITY: Sanitize and limit search input length
                    search = search.strip()[:100]  # Limit to 100 characters
                    if search:
                        search_pattern = f'%{search}%'
                        query += ''' AND (
                            CAST(i.id AS CHAR) LIKE %s OR
                            i.order_id LIKE %s OR
                            i.transaction_id LIKE %s OR
                            CAST(i.amount AS CHAR) LIKE %s OR
                            u.username LIKE %s OR
                            CAST(u.telegram_id AS CHAR) LIKE %s OR
                            u.first_name LIKE %s OR
                            u.last_name LIKE %s OR
                            p.name LIKE %s
                        )'''
                        params.extend([search_pattern] * 9)
                
                # Get total count
                count_query = query.replace('SELECT i.*, u.telegram_id, u.username, u.first_name, u.last_name, p.name as panel_name', 'SELECT COUNT(*) as count')
                cursor.execute(count_query, params)
                result = cursor.fetchone()
                total = result['count'] if result else 0
                
                # Get paginated results
                query += ' ORDER BY i.created_at DESC LIMIT %s OFFSET %s'
                params.extend([per_page, (page - 1) * per_page])
                cursor.execute(query, params)
                
                invoices = [dict(row) for row in cursor.fetchall()]
                return invoices, total
        except Exception as e:
            logger.error(f"Error getting paginated gateway invoices: {e}")
            return [], 0
    
    def get_all_users_paginated(self, page: int = 1, per_page: int = 10, search: str = None) -> Tuple[List[Dict], int]:
        """Get all users with pagination and optional search, including service count"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Base query parts
                select_part = 'SELECT *, (SELECT COUNT(*) FROM clients WHERE clients.user_id = users.id) as total_clients'
                from_part = 'FROM users'
                where_part = ''
                params = []
                
                if search:
                    # SECURITY: Sanitize and limit search input length
                    search = search.strip()[:100]  # Limit to 100 characters
                    if search:
                        search_pattern = f'%{search}%'
                        where_part = ''' WHERE (
                            username LIKE %s OR
                            CAST(telegram_id AS CHAR) LIKE %s OR
                            first_name LIKE %s OR
                            last_name LIKE %s
                        )'''
                        params.extend([search_pattern] * 4)
                
                # Get total count
                count_query = f'SELECT COUNT(*) as count {from_part} {where_part}'
                cursor.execute(count_query, params)
                result = cursor.fetchone()
                total = result['count'] if result else 0
                
                # Get paginated results
                query = f'{select_part} {from_part} {where_part} ORDER BY created_at DESC LIMIT %s OFFSET %s'
                params.extend([per_page, (page - 1) * per_page])
                cursor.execute(query, params)
                
                users = [dict(row) for row in cursor.fetchall()]
                return users, total
        except Exception as e:
            logger.error(f"Error getting paginated users: {e}")
            return [], 0
    
    def get_client_by_id(self, client_id: int) -> Optional[Dict]:
        """Get client by ID with user and panel info"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT c.*, p.name as panel_name, u.telegram_id, u.username, u.first_name, u.last_name
                    FROM clients c 
                    JOIN panels p ON c.panel_id = p.id 
                    JOIN users u ON c.user_id = u.id
                    WHERE c.id = %s
                ''', (client_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting client by ID: {e}")
            return None
    
    def delete_client(self, client_id: int) -> bool:
        """Delete client from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('DELETE FROM clients WHERE id = %s', (client_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error deleting client: {e}")
            return False
    
    # ========== TICKET MANAGEMENT METHODS ==========
    
    def create_ticket(self, user_id: int, subject: str, message: str, priority: str = 'normal') -> Optional[int]:
        """Create a new ticket with initial message"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Create ticket
                cursor.execute('''
                    INSERT INTO tickets (user_id, subject, status, priority)
                    VALUES (%s, %s, 'open', %s)
                ''', (user_id, subject, priority))
                ticket_id = cursor.lastrowid
                
                # Add initial message
                cursor.execute('''
                    INSERT INTO ticket_replies (ticket_id, user_id, message, is_admin_reply)
                    VALUES (%s, %s, %s, 0)
                ''', (ticket_id, user_id, message))
                
                # Update ticket last_reply_at
                cursor.execute('''
                    UPDATE tickets 
                    SET last_reply_at = NOW(), last_reply_by = %s
                    WHERE id = %s
                ''', (user_id, ticket_id))
                
                conn.commit()
                return ticket_id
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return None
    
    def get_user_tickets(self, user_id: int, page: int = 1, per_page: int = 10) -> Tuple[List[Dict], int]:
        """Get all tickets for a user with pagination"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get total count
                cursor.execute('SELECT COUNT(*) as count FROM tickets WHERE user_id = %s', (user_id,))
                total = cursor.fetchone()['count']
                
                # Get paginated results
                cursor.execute('''
                    SELECT t.*, 
                           (SELECT COUNT(*) FROM ticket_replies tr WHERE tr.ticket_id = t.id) as reply_count,
                           (SELECT COUNT(*) FROM ticket_replies tr WHERE tr.ticket_id = t.id AND tr.is_admin_reply = 1) as admin_reply_count
                    FROM tickets t
                    WHERE t.user_id = %s
                    ORDER BY t.created_at DESC
                    LIMIT %s OFFSET %s
                ''', (user_id, per_page, (page - 1) * per_page))
                return [dict(row) for row in cursor.fetchall()], total
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}")
            return [], 0
    
    def get_ticket(self, ticket_id: int, user_id: int = None) -> Optional[Dict]:
        """Get ticket by ID, optionally filtered by user_id"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if user_id:
                    cursor.execute('''
                        SELECT t.*, u.telegram_id, u.username, u.first_name, u.last_name
                        FROM tickets t
                        JOIN users u ON t.user_id = u.id
                        WHERE t.id = %s AND t.user_id = %s
                    ''', (ticket_id, user_id))
                else:
                    cursor.execute('''
                        SELECT t.*, u.telegram_id, u.username, u.first_name, u.last_name
                        FROM tickets t
                        JOIN users u ON t.user_id = u.id
                        WHERE t.id = %s
                    ''', (ticket_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting ticket: {e}")
            return None
    
    def get_ticket_replies(self, ticket_id: int) -> List[Dict]:
        """Get all replies for a ticket"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT tr.*, u.telegram_id, u.username, u.first_name, u.last_name, u.is_admin
                    FROM ticket_replies tr
                    JOIN users u ON tr.user_id = u.id
                    WHERE tr.ticket_id = %s
                    ORDER BY tr.created_at ASC
                ''', (ticket_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting ticket replies: {e}")
            return []

    def check_duplicate_ticket(self, user_id: int, message_text: str, time_window_minutes: int = 5) -> bool:
        """Check if a similar ticket exists from the user within the time window"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    SELECT id FROM tickets 
                    WHERE user_id = %s 
                    AND message = %s 
                    AND created_at > NOW() - INTERVAL %s MINUTE
                    AND status != 'closed'
                ''', (user_id, message_text, time_window_minutes))
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"Error checking duplicate ticket: {e}")
            return False
    
    def add_ticket_reply(self, ticket_id: int, user_id: int, message: str, is_admin: bool = False) -> Optional[int]:
        """Add a reply to a ticket"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Add reply
                cursor.execute('''
                    INSERT INTO ticket_replies (ticket_id, user_id, message, is_admin_reply)
                    VALUES (%s, %s, %s, %s)
                ''', (ticket_id, user_id, message, 1 if is_admin else 0))
                reply_id = cursor.lastrowid
                
                # Update ticket
                cursor.execute('''
                    UPDATE tickets 
                    SET last_reply_at = NOW(), 
                        last_reply_by = %s,
                        updated_at = NOW()
                    WHERE id = %s
                ''', (user_id, ticket_id))
                
                conn.commit()
                return reply_id
        except Exception as e:
            logger.error(f"Error adding ticket reply: {e}")
            return None
    
    def close_ticket(self, ticket_id: int, closed_by: int) -> bool:
        """Close a ticket"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE tickets 
                    SET status = 'closed', 
                        closed_at = NOW(),
                        closed_by = %s,
                        updated_at = NOW()
                    WHERE id = %s
                ''', (closed_by, ticket_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            return False
    
    def reopen_ticket(self, ticket_id: int) -> bool:
        """Reopen a closed ticket"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE tickets 
                    SET status = 'open', 
                        closed_at = NULL,
                        closed_by = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                ''', (ticket_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error reopening ticket: {e}")
            return False
    
    def get_all_tickets(self, status: str = None, page: int = 1, per_page: int = 10, waiting_admin: bool = False) -> Tuple[List[Dict], int]:
        """Get all tickets with pagination, optionally filtered by status or waiting for admin reply"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                query = '''
                    SELECT t.*, u.telegram_id, u.username, u.first_name, u.last_name,
                           (SELECT COUNT(*) FROM ticket_replies tr WHERE tr.ticket_id = t.id) as reply_count
                    FROM tickets t
                    JOIN users u ON t.user_id = u.id
                '''
                params = []
                where_clauses = []
                
                if waiting_admin:
                    # Waiting for admin reply: ticket is open AND (no replies OR last reply is from user)
                    # Use last_reply_by field which is set when ticket/reply is created
                    # A ticket is waiting for admin reply if:
                    # 1. It's open
                    # 2. last_reply_by is NULL (no replies yet) OR last_reply_by equals user_id (last reply was from user)
                    where_clauses.append("t.status = 'open' AND (t.last_reply_by IS NULL OR t.last_reply_by = t.user_id)")
                elif status:
                    where_clauses.append('t.status = %s')
                    params.append(status)
                
                if where_clauses:
                    query += ' WHERE ' + ' AND '.join(where_clauses)
                
                # Get total count - use a simpler count query
                count_query = '''
                    SELECT COUNT(*) as count
                    FROM tickets t
                    JOIN users u ON t.user_id = u.id
                '''
                count_params = []
                if where_clauses:
                    count_query += ' WHERE ' + ' AND '.join(where_clauses)
                    count_params = params.copy()  # Use same params as main query
                
                try:
                    cursor.execute(count_query, count_params)
                    result = cursor.fetchone()
                    if result:
                        total = result.get('count', 0) if isinstance(result, dict) else (result[0] if isinstance(result, (list, tuple)) else 0)
                    else:
                        total = 0
                except Exception as e:
                    logger.error(f"Error executing count query: {e}", exc_info=True)
                    total = 0
                
                # Get paginated results
                # Order by: waiting tickets first (priority), then by created_at DESC
                if waiting_admin:
                    # When filtering for waiting tickets, show them ordered by created_at
                    query += ' ORDER BY t.created_at DESC LIMIT %s OFFSET %s'
                else:
                    # Show waiting tickets first, then others, all ordered by created_at DESC
                    query += ' ORDER BY CASE WHEN t.status = "open" AND (t.last_reply_by IS NULL OR t.last_reply_by = t.user_id) THEN 0 ELSE 1 END, t.created_at DESC LIMIT %s OFFSET %s'
                params.extend([per_page, (page - 1) * per_page])
                cursor.execute(query, params)
                
                tickets = [dict(row) for row in cursor.fetchall()]
                return tickets, total
        except Exception as e:
            logger.error(f"Error getting all tickets: {e}")
            return [], 0
    
    def get_ticket_stats(self) -> Dict:
        """Get ticket statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                stats = {}
                
                # Total tickets
                cursor.execute('SELECT COUNT(*) as count FROM tickets')
                result = cursor.fetchone()
                stats['total'] = result['count'] if result else 0
                
                # Open tickets
                cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status = 'open'")
                result = cursor.fetchone()
                stats['open'] = result['count'] if result else 0
                
                # Closed tickets
                cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status = 'closed'")
                result = cursor.fetchone()
                stats['closed'] = result['count'] if result else 0
                
                # Tickets waiting for admin reply: ticket is open AND (no replies OR last reply is from user)
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM tickets t
                    WHERE t.status = 'open' 
                    AND (t.last_reply_by IS NULL OR t.last_reply_by = t.user_id)
                ''')
                result = cursor.fetchone()
                stats['waiting_admin'] = result['count'] if result else 0
                
                return stats
        except Exception as e:
            logger.error(f"Error getting ticket stats: {e}")
            return {'total': 0, 'open': 0, 'closed': 0, 'waiting_admin': 0}
    
    # ========== BOT TEXT MANAGEMENT METHODS ==========
    
    def get_bot_text(self, text_key: str) -> Optional[Dict]:
        """Get bot text by key - always fresh from database, no cache"""
        try:
            # Force a fresh connection to ensure we get latest data
            with self.get_connection() as conn:
                # Use fresh connection, no caching
                cursor = conn.cursor(dictionary=True)
                # Force fresh read - query directly from database
                # Only get active texts for this specific database
                logger.info(f"🔍 Getting text '{text_key}' for database '{self.database_name}'")
                cursor.execute('''
                    SELECT * FROM bot_texts 
                    WHERE database_name = %s AND text_key = %s AND is_active = 1
                    LIMIT 1
                ''', (self.database_name, text_key))
                row = cursor.fetchone()
                result = dict(row) if row else None
                cursor.close()
                
                if result:
                    result_db_name = result.get('database_name', '')
                    if result_db_name == self.database_name:
                        logger.info(f"✅ Found active text '{text_key}' in database '{self.database_name}' (length: {len(result.get('text_content', ''))})")
                        logger.debug(f"   Text content preview: {result.get('text_content', '')[:50]}...")
                    else:
                        logger.warning(f"⚠️ CRITICAL: Text '{text_key}' found but database_name mismatch! Expected '{self.database_name}', got '{result_db_name}'. Returning None.")
                        # Don't return this result - it's from wrong database
                        result = None
                else:
                    # Check if text exists but is inactive or in different database
                    cursor2 = conn.cursor(dictionary=True)
                    cursor2.execute('SELECT is_active, database_name FROM bot_texts WHERE text_key = %s LIMIT 1', (text_key,))
                    inactive_check = cursor2.fetchone()
                    cursor2.close()
                    if inactive_check:
                        check_db_name = inactive_check.get('database_name', '')
                        if check_db_name != self.database_name:
                            logger.warning(f"⚠️ Text '{text_key}' exists in database '{check_db_name}' but not in '{self.database_name}'")
                        else:
                            logger.debug(f"ℹ️ Text '{text_key}' exists in database '{self.database_name}' but is inactive")
                    else:
                        logger.debug(f"ℹ️ Text '{text_key}' not found in any database")
                
                return result
        except Exception as e:
            logger.error(f"❌ Error getting bot text '{text_key}': {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_all_bot_texts(self, category: str = None, include_inactive: bool = False) -> List[Dict]:
        """Get all bot texts for this database, optionally filtered by category"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = 'SELECT * FROM bot_texts WHERE database_name = %s'
                params = [self.database_name]
                where_clauses = []
                
                if category:
                    where_clauses.append('text_category = %s')
                    params.append(category)
                
                if not include_inactive:
                    where_clauses.append('is_active = 1')
                
                if where_clauses:
                    query += ' AND ' + ' AND '.join(where_clauses)
                
                query += ' ORDER BY text_category, text_key'
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all bot texts: {e}")
            return []
    
    def create_bot_text(self, text_key: str, text_category: str, text_content: str, 
                       description: str = None, available_variables: str = None, 
                       updated_by: int = None) -> Optional[int]:
        """Create a new bot text (or update if exists)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Check if text already exists for this database
                logger.info(f"🔍 Creating/updating text '{text_key}' for database '{self.database_name}' (current db instance)")
                cursor.execute('SELECT id, database_name FROM bot_texts WHERE database_name = %s AND text_key = %s', (self.database_name, text_key))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing text instead of creating new one
                    logger.info(f"✅ Found existing text '{text_key}' in database '{self.database_name}' (ID: {existing.get('id')}), updating...")
                    updates = []
                    params = []
                    
                    if text_category:
                        updates.append('text_category = %s')
                        params.append(text_category)
                    if text_content:
                        updates.append('text_content = %s')
                        params.append(text_content)
                    if description is not None:
                        updates.append('description = %s')
                        params.append(description)
                    if available_variables is not None:
                        updates.append('available_variables = %s')
                        params.append(available_variables)
                    if updated_by is not None:
                        updates.append('updated_by = %s')
                        params.append(updated_by)
                    
                    updates.append('is_active = 1')
                    updates.append('updated_at = CURRENT_TIMESTAMP')
                    params.append(self.database_name)
                    params.append(text_key)
                    
                    query = f'UPDATE bot_texts SET {", ".join(updates)} WHERE database_name = %s AND text_key = %s'
                    logger.info(f"🔍 Executing UPDATE query: database_name='{self.database_name}', text_key='{text_key}'")
                    cursor.execute(query, params)
                    affected = cursor.rowcount
                    conn.commit()
                    if affected > 0:
                        logger.info(f"✅ Successfully updated text '{text_key}' for database '{self.database_name}' (affected rows: {affected})")
                    else:
                        logger.warning(f"⚠️ Update query executed but no rows affected for text '{text_key}' in database '{self.database_name}'")
                        # Check if text exists in different database
                        cursor_check = conn.cursor(dictionary=True)
                        cursor_check.execute('SELECT database_name FROM bot_texts WHERE text_key = %s LIMIT 1', (text_key,))
                        check_result = cursor_check.fetchone()
                        cursor_check.close()
                        if check_result:
                            logger.warning(f"⚠️ Text '{text_key}' exists in database '{check_result.get('database_name')}' but not in '{self.database_name}'")
                    return existing['id']
                else:
                    # Create new text with database_name
                    logger.info(f"✅ Creating new text '{text_key}' for database '{self.database_name}'")
                    cursor.execute('''
                        INSERT INTO bot_texts 
                        (database_name, text_key, text_category, text_content, description, available_variables, updated_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (self.database_name, text_key, text_category, text_content, description, available_variables, updated_by))
                    conn.commit()
                    logger.info(f"✅ Successfully created text '{text_key}' with ID {cursor.lastrowid} for database '{self.database_name}'")
                    return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating bot text: {e}")
            return None
    
    def update_bot_text(self, text_key: str, text_content: str = None, 
                       description: str = None, available_variables: str = None,
                       is_active: bool = None, updated_by: int = None) -> bool:
        """Update bot text"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                updates = []
                params = []
                
                if text_content is not None:
                    updates.append('text_content = %s')
                    params.append(text_content)
                
                if description is not None:
                    updates.append('description = %s')
                    params.append(description)
                
                if available_variables is not None:
                    updates.append('available_variables = %s')
                    params.append(available_variables)
                
                if is_active is not None:
                    updates.append('is_active = %s')
                    params.append(1 if is_active else 0)
                
                if updated_by is not None:
                    updates.append('updated_by = %s')
                    params.append(updated_by)
                
                if not updates:
                    return False
                
                updates.append('updated_at = CURRENT_TIMESTAMP')
                params.append(self.database_name)
                params.append(text_key)
                
                query = f'UPDATE bot_texts SET {", ".join(updates)} WHERE database_name = %s AND text_key = %s'
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating bot text: {e}")
            return False
    
    def delete_bot_text(self, text_key: str) -> bool:
        """Delete bot text (soft delete by setting is_active = 0)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # First check if text exists for this database
                cursor.execute('SELECT id, is_active FROM bot_texts WHERE database_name = %s AND text_key = %s', (self.database_name, text_key))
                existing = cursor.fetchone()
                
                if not existing:
                    logger.warning(f"Text '{text_key}' not found in database '{self.database_name}' for deletion")
                    return False
                
                # Update is_active to 0 (soft delete)
                cursor.execute('''
                    UPDATE bot_texts 
                    SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE database_name = %s AND text_key = %s
                ''', (self.database_name, text_key))
                conn.commit()
                
                affected_rows = cursor.rowcount
                if affected_rows > 0:
                    logger.info(f"✅ Text '{text_key}' deactivated successfully (soft delete)")
                    return True
                else:
                    logger.warning(f"⚠️ No rows updated for text '{text_key}'")
                    return False
        except Exception as e:
            logger.error(f"❌ Error deleting bot text '{text_key}': {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def get_bot_text_categories(self) -> List[str]:
        """Get all unique text categories for this database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT DISTINCT text_category FROM bot_texts WHERE database_name = %s ORDER BY text_category', (self.database_name,))
                return [row['text_category'] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting bot text categories: {e}")
            return []
    
    # System Settings Methods
    def get_system_setting(self, setting_key: str, default_value: str = None) -> Optional[str]:
        """Get a system setting value by key"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT setting_value FROM system_settings WHERE setting_key = %s', (setting_key,))
                result = cursor.fetchone()
                if result and result['setting_value']:
                    return result['setting_value']
                return default_value
        except Exception as e:
            logger.error(f"Error getting system setting '{setting_key}': {e}")
            return default_value
    
    def set_system_setting(self, setting_key: str, setting_value: str, description: str = None) -> bool:
        """Set or update a system setting"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Check if setting exists
                cursor.execute('SELECT id FROM system_settings WHERE setting_key = %s', (setting_key,))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing setting
                    if description:
                        cursor.execute('''
                            UPDATE system_settings 
                            SET setting_value = %s, description = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE setting_key = %s
                        ''', (setting_value, description, setting_key))
                    else:
                        cursor.execute('''
                            UPDATE system_settings 
                            SET setting_value = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE setting_key = %s
                        ''', (setting_value, setting_key))
                else:
                    # Insert new setting
                    cursor.execute('''
                        INSERT INTO system_settings (setting_key, setting_value, description)
                        VALUES (%s, %s, %s)
                    ''', (setting_key, setting_value, description))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting system setting '{setting_key}': {e}")
            return False
    
    def get_test_account_config(self, panel_id: int = None, category_id: int = None) -> Dict[str, Optional[int]]:
        """
        Get test account configuration.
        If category_id is provided, checks category-specific config first.
        If panel_id is provided, checks panel-specific config next.
        Falls back to global settings.
        """
        # Global defaults
        global_panel_id = self.get_setting('test_account_panel_id')
        global_inbound_id = self.get_setting('test_account_inbound_id')
        global_duration = self.get_setting('test_account_duration', 24)
        global_volume = self.get_setting('test_account_volume', 1)
        
        config = {
            'panel_id': int(global_panel_id) if global_panel_id and str(global_panel_id).isdigit() else None,
            'inbound_id': int(global_inbound_id) if global_inbound_id and str(global_inbound_id).isdigit() else None,
            'duration_hours': int(global_duration),
            'volume_gb': float(global_volume)
        }

        # 1. Check Category Config (Highest Priority for Volume/Duration)
        if category_id:
            category = self.get_category(category_id)
            if category:
                # Assuming get_category returns dict with test_volume_gb and test_duration_hours
                if category.get('test_volume_gb') is not None and category.get('test_volume_gb') > 0:
                    config['volume_gb'] = float(category['test_volume_gb'])
                
                if category.get('test_duration_hours') is not None and category.get('test_duration_hours') > 0:
                    config['duration_hours'] = int(category['test_duration_hours'])

        # 2. Check Panel Config (Override if not set by category or if category not provided)
        # Note: If category set volume, we might still want to check panel for inbound_id or other settings
        if panel_id:
            panel = self.get_panel(panel_id)
            if panel and panel.get('extra_config'):
                extra_config = panel['extra_config']
                if isinstance(extra_config, str):
                    try:
                        extra_config = json.loads(extra_config)
                    except:
                        extra_config = {}
                
                # Only override if NOT set by category (or if we want panel to override category? No, category is more specific)
                # But wait, logic above sets config. If category didn't set it, it's global default.
                # We need to know if category set it.
                # Actually, simple logic: Start with Global -> Override with Panel -> Override with Category
                
                # Let's restart logic slightly for clarity
                pass # Already initialized with global
                
                # Apply Panel Overrides
                if extra_config.get('test_duration_hours'):
                    config['duration_hours'] = int(extra_config['test_duration_hours'])
                if extra_config.get('test_volume_gb'):
                    config['volume_gb'] = float(extra_config['test_volume_gb'])
                if extra_config.get('test_inbound_id'):
                     config['inbound_id'] = int(extra_config['test_inbound_id'])

        # 3. Apply Category Overrides (Most specific)
        if category_id:
            category = self.get_category(category_id)
            if category:
                if category.get('test_volume_gb') is not None and category.get('test_volume_gb') > 0:
                    config['volume_gb'] = float(category['test_volume_gb'])
                
                if category.get('test_duration_hours') is not None and category.get('test_duration_hours') > 0:
                    config['duration_hours'] = int(category['test_duration_hours'])

        return config
    
    def set_panel_test_config(self, panel_id: int, duration_hours: int = None, volume_gb: float = None, inbound_id: int = None) -> bool:
        """Set test account configuration for a specific panel in extra_config"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # Get current config
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False
                    
                current_config = result['extra_config']
                if isinstance(current_config, str):
                    try:
                        config_dict = json.loads(current_config) if current_config else {}
                    except:
                        config_dict = {}
                else:
                    config_dict = current_config if current_config else {}
                    
                # Update settings
                if duration_hours is not None:
                    config_dict['test_duration_hours'] = duration_hours
                if volume_gb is not None:
                    config_dict['test_volume_gb'] = volume_gb
                if inbound_id is not None:
                    config_dict['test_inbound_id'] = inbound_id
                
                # Save back
                new_config = json.dumps(config_dict)
                cursor.execute('''
                    UPDATE panels 
                    SET extra_config = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (new_config, panel_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting panel test config: {e}")
            return False

    def set_panel_test_panel_settings(self, panel_id: int, enabled: bool = None, display_name: str = None) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT extra_config FROM panels WHERE id = %s', (panel_id,))
                result = cursor.fetchone()
                if not result:
                    return False

                current_config = result.get('extra_config')
                if isinstance(current_config, str):
                    try:
                        config_dict = json.loads(current_config) if current_config else {}
                    except Exception:
                        config_dict = {}
                elif isinstance(current_config, dict):
                    config_dict = current_config
                else:
                    config_dict = {}

                if enabled is not None:
                    config_dict['test_enabled'] = bool(enabled)
                if display_name is not None:
                    config_dict['test_display_name'] = str(display_name).strip()

                new_config = json.dumps(config_dict)
                cursor.execute('''
                    UPDATE panels
                    SET extra_config = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (new_config, panel_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting panel test panel settings: {e}")
            return False

    def get_test_panels(self, active_only: bool = True) -> List[Dict]:
        try:
            panels = self.get_panels(active_only=active_only)
            result = []
            for panel in panels:
                extra_config = panel.get('extra_config')
                if isinstance(extra_config, str):
                    try:
                        extra_config_dict = json.loads(extra_config) if extra_config else {}
                    except Exception:
                        extra_config_dict = {}
                elif isinstance(extra_config, dict):
                    extra_config_dict = extra_config
                else:
                    extra_config_dict = {}

                enabled = bool(extra_config_dict.get('test_enabled') or extra_config_dict.get('is_test_panel'))
                if not enabled:
                    continue

                display_name = extra_config_dict.get('test_display_name')
                if display_name:
                    panel['test_display_name'] = str(display_name)
                result.append(panel)
            return result
        except Exception as e:
            logger.error(f"Error getting test panels: {e}")
            return []

    def set_test_account_config(self, panel_id: int, inbound_id: int = None, duration_hours: int = 24, volume_gb: float = 1) -> bool:
        """Set test account configuration"""
        success = True
        success &= self.set_setting(
            'test_account_panel_id', 
            str(panel_id), 
            'Panel ID for test account purchases'
        )
        if inbound_id is not None:
            success &= self.set_setting(
                'test_account_inbound_id', 
                str(inbound_id), 
                'Inbound ID for test account purchases'
            )
            
        success &= self.set_setting('test_account_duration', str(duration_hours), 'Test account duration in hours')
        success &= self.set_setting('test_account_volume', str(volume_gb), 'Test account volume in GB')
        
        return success

    # Service Status and Exhaustion Management Methods
    def _update_client_field(self, client_id: int, field: str, value: Any) -> bool:
        """Helper to update a single field in clients table"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"UPDATE clients SET {field} = %s WHERE id = %s", (value, client_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating client field {field}: {e}")
            return False

    def update_service_warned_one_week(self, service_id: int, warned: bool = True) -> bool:
        """Update 3-day (one week) warning flag"""
        return self._update_client_field(service_id, 'warned_one_week', 1 if warned else 0)

    def update_service_warned_one_day(self, service_id: int, warned: bool = True) -> bool:
        """Update 1-day warning flag"""
        return self._update_client_field(service_id, 'warned_one_day', 1 if warned else 0)
        
    def update_service_warned_12_hours(self, service_id: int, warned: bool = True) -> bool:
        """Update 12-hours warning flag"""
        return self._update_client_field(service_id, 'warned_12_hours', 1 if warned else 0)

    def update_service_warned_3_hours_before_deletion(self, service_id: int, warned: bool = True) -> bool:
        return self._update_client_field(service_id, 'warned_3_hours_before_deletion', 1 if warned else 0)

    def update_service_70_percent_warning(self, service_id: int, warned: bool = True) -> bool:
        """Update 70% usage warning flag"""
        return self._update_client_field(service_id, 'warned_70_percent', 1 if warned else 0)

    def update_service_80_percent_warning(self, service_id: int, warned: bool = True) -> bool:
        """Update 80% usage warning flag"""
        return self._update_client_field(service_id, 'warned_80_percent', 1 if warned else 0)

    def update_service_90_percent_warning(self, service_id: int, warned: bool = True) -> bool:
        """Update 90% usage warning flag"""
        return self._update_client_field(service_id, 'warned_90_percent', 1 if warned else 0)
    
    def update_service_expired_warning(self, service_id: int, warned: bool = True) -> bool:
        """Update expired warning flag"""
        return self._update_client_field(service_id, 'warned_expired', 1 if warned else 0)

    def update_service_status(self, service_id: int, status: str) -> bool:
        """Update service status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT status, user_id, client_name FROM clients WHERE id = %s', (service_id,))
                row = cursor.fetchone() or {}
                old_status = str(row.get('status') or '')

                is_active_value = 1 if str(status or '') == 'active' else 0
                cursor.execute('''
                    UPDATE clients 
                    SET status = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (status, is_active_value, service_id))
                conn.commit()

                if old_status != str(status or ''):
                    client_name = row.get('client_name') or ''
                    msg = f"Service {service_id}{f' ({client_name})' if client_name else ''} status: {old_status or 'unknown'} -> {status or 'unknown'}"
                    self.log_system_event('INFO', msg, 'service_status', row.get('user_id'))
                return True
        except Exception as e:
            logger.error(f"Error updating service status: {e}")
            return False

    def update_service_exhaustion_time(self, service_id: int) -> bool:
        """Set service exhaustion time to NOW"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET exhausted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (service_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating service exhaustion time: {e}")
            return False

    def update_service_notified_exhausted(self, service_id: int, notified: bool = True) -> bool:
        """Update notified_exhausted flag"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET notified_exhausted = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (1 if notified else 0, service_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating service notified_exhausted: {e}")
            return False

    def reset_service_exhaustion(self, service_id: int) -> bool:
        """Reset service exhaustion flags (status, exhausted_at, notified_exhausted, warned_70_percent)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                    UPDATE clients 
                    SET status = 'active',
                        is_active = 1,
                        exhausted_at = NULL,
                        notified_exhausted = 0,
                        warned_70_percent = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (service_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error resetting service exhaustion: {e}")
            return False

    def update_client_panel(self, old_uuid: str, new_panel_id: int, new_client_data: Dict) -> bool:
        """Update client's panel and details after migration"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Update client record
                # We identify by old_uuid (which is stored in client_uuid)
                # We need to update: panel_id, inbound_id, client_uuid (if changed), sub_id (if changed)
                # Also update config_link if available
                
                new_uuid = new_client_data.get('id') or new_client_data.get('uuid')
                new_sub_id = new_client_data.get('sub_id')
                new_inbound_id = new_client_data.get('inbound_id', 0)
                new_config_link = new_client_data.get('subscription_url') or new_client_data.get('config_link')
                
                cursor.execute('''
                    UPDATE clients 
                    SET panel_id = %s,
                        inbound_id = %s,
                        client_uuid = %s,
                        sub_id = %s,
                        config_link = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE client_uuid = %s
                ''', (new_panel_id, new_inbound_id, new_uuid, new_sub_id, new_config_link, old_uuid))
                
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating client panel: {e}")
            return False

    # Panel Inbound Management
    def get_panel_inbound(self, panel_id: int, inbound_id: int) -> Optional[Dict]:
        """Get a specific inbound for a panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM panel_inbounds WHERE panel_id = %s AND inbound_id = %s', (panel_id, inbound_id))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting panel inbound: {e}")
            return None

    def add_panel_inbound(self, panel_id: int, inbound_id: int, name: str, protocol: str, port: int, is_enabled: bool = True) -> bool:
        """Add or update a panel inbound"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Check if exists
                cursor.execute('SELECT id FROM panel_inbounds WHERE panel_id = %s AND inbound_id = %s', (panel_id, inbound_id))
                existing = cursor.fetchone()
                
                if existing:
                    cursor.execute('''
                        UPDATE panel_inbounds 
                        SET inbound_name = %s, inbound_protocol = %s, inbound_port = %s, is_enabled = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    ''', (name, protocol, port, 1 if is_enabled else 0, existing['id']))
                else:
                    cursor.execute('''
                        INSERT INTO panel_inbounds (panel_id, inbound_id, inbound_name, inbound_protocol, inbound_port, is_enabled)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (panel_id, inbound_id, name, protocol, port, 1 if is_enabled else 0))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding/updating panel inbound: {e}")
            return False

    def get_stored_panel_inbounds(self, panel_id: int) -> List[Dict]:
        """Get all stored inbounds for a panel"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM panel_inbounds WHERE panel_id = %s ORDER BY inbound_id', (panel_id,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting stored panel inbounds: {e}")
            return []
            
    def update_panel_inbound_status(self, panel_id: int, inbound_id: int, is_enabled: bool) -> bool:
        """Update inbound enabled status"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('''
                ''', (1 if is_enabled else 0, panel_id, inbound_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating panel inbound status: {e}")
            return False

    # ==================== WHEEL OF FORTUNE METHODS ====================

    def get_wheel_settings(self) -> Dict[str, Any]:
        """Get all wheel of fortune settings"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute('SELECT * FROM wheel_settings')
                rows = cursor.fetchall()
                
                settings = {}
                for row in rows:
                    settings[row['setting_key']] = row['setting_value']
                
                return settings
        except Exception as e:
            logger.error(f"Error getting wheel settings: {e}")
            return {}

    def set_wheel_setting(self, key: str, value: str) -> bool:
        """Set a wheel of fortune setting"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO wheel_settings (setting_key, setting_value)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                ''', (key, str(value)))
                conn.commit()
                return True
        except Error as e:
            logger.error(f"Error setting wheel setting {key}: {e}")
            return False

    def get_prizes(self, active_only: bool = True) -> List[Dict]:
        """Get all wheel prizes"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                query = "SELECT * FROM wheel_prizes"
                if active_only:
                    cursor.execute('SELECT * FROM wheel_prizes WHERE is_active = 1 ORDER BY display_order ASC')
                else:
                    cursor.execute('SELECT * FROM wheel_prizes ORDER BY display_order ASC')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting prizes: {e}")
            return []

    def add_prize(self, name: str, type: str, value: float, probability: float, 
                 is_active: bool = True, display_order: int = 0) -> int:
        """Add a new prize"""
        try:
            logger.info(f"Adding prize to DB: name={name}, type={type}, val={value}, prob={probability}, active={is_active}")
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO wheel_prizes 
                    (name, type, value, probability, is_active, display_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (name, type, value, probability, 1 if is_active else 0, display_order))
                conn.commit()
                new_id = cursor.lastrowid
                logger.info(f"Prize added to DB with ID: {new_id}")
                return new_id
        except Error as e:
            logger.error(f"Error adding prize: {e}")
            return 0

    def update_prize(self, prize_id: int, **kwargs) -> bool:
        """Update a prize"""
        try:
            logger.info(f"Updating prize {prize_id} in DB with: {kwargs}")
            allowed_fields = ['name', 'type', 'value', 'probability', 'is_active', 'display_order']
            updates = []
            params = []
            
            for key, value in kwargs.items():
                if key in allowed_fields:
                    updates.append(f"{key} = %s")
                    params.append(value)
            
            if not updates:
                logger.warning(f"No valid fields to update for prize {prize_id}")
                return False
                
            params.append(prize_id)
            query = f"UPDATE wheel_prizes SET {', '.join(updates)} WHERE id = %s"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                logger.info(f"Prize {prize_id} updated in DB successfully")
                return True
        except Error as e:
            logger.error(f"Error updating prize {prize_id}: {e}")
            return False

    def delete_prize(self, prize_id: int) -> bool:
        """Delete a prize"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM wheel_prizes WHERE id = %s', (prize_id,))
                conn.commit()
                return True
        except Error as e:
            logger.error(f"Error deleting prize {prize_id}: {e}")
            return False

    def get_system_stats(self) -> Dict:
        """Unified, validated system statistics for dashboards and bot"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                try:
                    cursor.execute('SELECT COUNT(*) as count FROM users')
                    total_users = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('SELECT COUNT(*) as count FROM panels')
                    total_panels = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('SELECT COUNT(*) as count FROM panels WHERE is_active = 1')
                    active_panels = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('SELECT COUNT(*) as count FROM clients')
                    total_services = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM clients 
                        WHERE (is_active = 1 OR status = 'active' OR COALESCE(status, '') = '')
                          AND COALESCE(status, '') NOT IN ('disabled', 'expired', 'exhausted')
                    ''')
                    active_services = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM clients 
                        WHERE status IN ('disabled', 'expired', 'exhausted') OR is_active = 0
                    ''')
                    disabled_services = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM clients 
                        WHERE COALESCE(cached_is_online, 0) = 1
                          AND (is_active = 1 OR status = 'active' OR COALESCE(status, '') = '')
                          AND COALESCE(status, '') NOT IN ('disabled', 'expired', 'exhausted')
                    ''')
                    online_services = int((cursor.fetchone() or {}).get('count') or 0)
                    
                    cursor.execute('''
                        SELECT
                            COALESCE(SUM(COALESCE(total_gb, 0)), 0) AS total_volume,
                            COALESCE(SUM(COALESCE(used_gb, cached_used_gb, 0)), 0) AS used_volume
                        FROM clients
                    ''')
                    vol_row = cursor.fetchone() or {}
                    total_volume_gb = float(vol_row.get('total_volume') or 0.0)
                    used_volume_gb = float(vol_row.get('used_volume') or 0.0)
                    
                    cursor.execute('''
                        SELECT SUM(amount) as total FROM invoices 
                        WHERE status IN ('paid', 'completed')
                    ''')
                    total_revenue = int((cursor.fetchone() or {}).get('total') or 0)
                    
                    cursor.execute('''
                        SELECT SUM(amount) as total FROM invoices 
                        WHERE status IN ('paid', 'completed') 
                          AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    ''')
                    monthly_revenue = int((cursor.fetchone() or {}).get('total') or 0)
                    
                    cursor.execute('''
                        SELECT SUM(amount) as total FROM invoices 
                        WHERE status IN ('paid', 'completed') 
                          AND DATE(created_at) = CURDATE()
                    ''')
                    daily_revenue = int((cursor.fetchone() or {}).get('total') or 0)
                finally:
                    cursor.close()
            
            total_users = max(0, total_users)
            total_panels = max(0, total_panels)
            active_panels = max(0, min(active_panels, total_panels))
            total_services = max(0, total_services)
            active_services = max(0, min(active_services, total_services))
            disabled_services = max(0, disabled_services)
            online_services = max(0, min(online_services, active_services))
            total_volume_gb = max(0.0, total_volume_gb)
            used_volume_gb = max(0.0, min(used_volume_gb, total_volume_gb))
            
            return {
                'total_users': total_users,
                'total_panels': total_panels,
                'active_panels': active_panels,
                'total_services': total_services,
                'active_services': active_services,
                'disabled_services': disabled_services,
                'online_services': online_services,
                'total_volume_gb': total_volume_gb,
                'used_volume_gb': used_volume_gb,
                'total_revenue': total_revenue,
                'monthly_revenue': monthly_revenue,
                'daily_revenue': daily_revenue
            }
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return {
                'total_users': 0,
                'total_panels': 0,
                'active_panels': 0,
                'total_services': 0,
                'active_services': 0,
                'disabled_services': 0,
                'online_services': 0,
                'total_volume_gb': 0.0,
                'used_volume_gb': 0.0,
                'total_revenue': 0,
                'monthly_revenue': 0,
                'daily_revenue': 0
            }
