import logging
import json
from datetime import datetime
from professional_database import ProfessionalDatabaseManager

logger = logging.getLogger(__name__)

class ResellerManager:
    """
    Manager for Reseller and Affiliate system.
    Handles database operations for resellers, plans, commissions, and payouts.
    """
    
    def __init__(self, db: ProfessionalDatabaseManager):
        self.db = db
        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Ensure necessary tables for the reseller system exist."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                # 1. Reseller Profiles (Extends users)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reseller_profiles (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL UNIQUE,
                        level VARCHAR(50) DEFAULT 'standard', -- standard, silver, gold, diamond
                        status VARCHAR(50) DEFAULT 'active',
                        credit_balance BIGINT DEFAULT 0,
                        total_earnings BIGINT DEFAULT 0,
                        commission_rate DECIMAL(5,2) DEFAULT 10.00, -- Default 10%
                        discount_rate DECIMAL(5,2) DEFAULT 0.00,    -- Default 0% discount on purchases
                        parent_reseller_id INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        notes TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (parent_reseller_id) REFERENCES users (id) ON DELETE SET NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # 2. Reseller Plans (Custom pricing for resellers)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reseller_plans (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        min_deposit BIGINT DEFAULT 0,
                        commission_percent DECIMAL(5,2) DEFAULT 10.00,
                        discount_percent DECIMAL(5,2) DEFAULT 5.00,
                        is_active TINYINT DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # 3. Commissions (Track earnings)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reseller_commissions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        reseller_id INT NOT NULL,
                        source_user_id INT, -- The user who made the purchase
                        amount BIGINT NOT NULL,
                        description VARCHAR(255),
                        status VARCHAR(50) DEFAULT 'pending', -- pending, approved, paid, rejected
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processed_at TIMESTAMP NULL,
                        FOREIGN KEY (reseller_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (source_user_id) REFERENCES users (id) ON DELETE SET NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')

                # 4. Payouts (Withdrawals)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reseller_payouts (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        reseller_id INT NOT NULL,
                        amount BIGINT NOT NULL,
                        method VARCHAR(50) DEFAULT 'card',
                        details TEXT, -- Card number, etc.
                        status VARCHAR(50) DEFAULT 'pending', -- pending, paid, rejected
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processed_at TIMESTAMP NULL,
                        transaction_ref VARCHAR(255),
                        FOREIGN KEY (reseller_id) REFERENCES users (id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                conn.commit()
        except Exception as e:
            logger.error(f"Error initializing reseller tables: {e}")

    # --- Reseller Management ---

    def get_all_resellers(self):
        """Get all resellers with their user details."""
        query = """
            SELECT r.*, u.first_name, u.last_name, u.username, u.telegram_id 
            FROM reseller_profiles r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.created_at DESC
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting resellers: {e}")
            return []

    def get_reseller_by_user_id(self, user_id):
        """Get reseller profile by user ID."""
        query = "SELECT * FROM reseller_profiles WHERE user_id = %s"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, (user_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting reseller: {e}")
            return None

    def create_or_update_reseller(self, user_id, level='standard', commission_rate=10.0, discount_rate=0.0, status='active'):
        """Create or update a reseller profile."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Check if exists
                cursor.execute("SELECT id FROM reseller_profiles WHERE user_id = %s", (user_id,))
                exists = cursor.fetchone()
                
                if exists:
                    query = """
                        UPDATE reseller_profiles 
                        SET level=%s, commission_rate=%s, discount_rate=%s, status=%s, updated_at=NOW()
                        WHERE user_id=%s
                    """
                    cursor.execute(query, (level, commission_rate, discount_rate, status, user_id))
                else:
                    query = """
                        INSERT INTO reseller_profiles (user_id, level, commission_rate, discount_rate, status)
                        VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(query, (user_id, level, commission_rate, discount_rate, status))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving reseller: {e}")
            return False

    # --- Stats & Charts ---

    def get_total_stats(self):
        """Get total stats for dashboard."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                stats = {
                    'total_resellers': 0,
                    'total_earnings': 0,
                    'pending_payouts': 0,
                    'total_sales_volume': 0
                }
                
                # Total Resellers
                cursor.execute("SELECT COUNT(*) as count FROM reseller_profiles WHERE status='active'")
                res = cursor.fetchone()
                if res: stats['total_resellers'] = res['count']
                
                # Total Earnings (Commissions)
                cursor.execute("SELECT SUM(amount) as total FROM reseller_commissions WHERE status='approved'")
                res = cursor.fetchone()
                if res and res['total']: stats['total_earnings'] = res['total']
                
                # Pending Payouts
                cursor.execute("SELECT COUNT(*) as count FROM reseller_payouts WHERE status='pending'")
                res = cursor.fetchone()
                if res: stats['pending_payouts'] = res['count']
                
                # Total Sales Volume (from invoices linked to resellers - complex query, simplifying for now)
                # Assuming we track sales volume in reseller_profiles for simplicity or aggregate later
                cursor.execute("SELECT SUM(total_earnings) as total FROM reseller_profiles")
                res = cursor.fetchone()
                if res and res['total']: stats['total_sales_volume'] = res['total'] # This is actually total earnings, but used as placeholder
                
                return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def get_chart_data(self, days=30):
        """Get chart data for the last N days."""
        # This would typically aggregate commissions/sales by date
        # Returning mock structure for now to be implemented with real data
        dates = []
        earnings = []
        sales = []
        
        # TODO: Implement real aggregation query
        
        return {
            'dates': dates,
            'earnings': earnings,
            'sales': sales
        }

    def delete_reseller(self, user_id):
        """Delete a reseller profile."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM reseller_profiles WHERE user_id = %s", (user_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting reseller: {e}")
            return False

    def get_reseller_by_telegram_id(self, telegram_id):
        """Get reseller profile by Telegram ID."""
        query = """
            SELECT r.*, u.first_name, u.last_name, u.username, u.telegram_id 
            FROM reseller_profiles r
            JOIN users u ON r.user_id = u.id
            WHERE u.telegram_id = %s AND r.status = 'active'
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, (telegram_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting reseller by telegram_id: {e}")
            return None

    def calculate_discounted_price(self, original_price, telegram_id):
        """
        Calculate discounted price for a reseller.
        Returns (discounted_price, discount_rate, is_reseller)
        """
        reseller = self.get_reseller_by_telegram_id(telegram_id)
        if reseller:
            discount_rate = float(reseller.get('discount_rate', 0) or 0)
            if discount_rate > 0:
                discount_amount = original_price * (discount_rate / 100)
                discounted_price = int(original_price - discount_amount)
                return discounted_price, discount_rate, True
            else:
                # User is a reseller but has 0% discount
                return original_price, 0, True
        return original_price, 0, False

    def is_reseller(self, telegram_id):
        """Check if user is an active reseller."""
        return self.get_reseller_by_telegram_id(telegram_id) is not None
