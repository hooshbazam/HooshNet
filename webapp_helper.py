"""
کمک‌کننده برای دریافت URL وب‌اپ از دیتابیس
"""
import sqlite3
import requests
import time
from pathlib import Path

def get_webapp_url():
    """دریافت URL وب‌اپ از دیتابیس (legacy function - returns None for multi-bot mode)"""
    # This function is deprecated in multi-bot mode
    # webapp_url should come from bot_config['webapp_url']
    try:
        # Try to get from environment variable first
        import os
        webapp_url = os.getenv('BOT_WEBAPP_URL') or os.getenv('WEBAPP_URL')
        if webapp_url:
            return webapp_url
        
        # Legacy SQLite support (for backward compatibility)
        db_path = Path(__file__).parent / "vpn_bot_professional.db"
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT ngrok_url FROM webapp_settings WHERE id = 1')
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
            except sqlite3.OperationalError:
                # Table doesn't exist - this is OK in multi-bot mode
                pass
            finally:
                conn.close()
        return None
    except Exception as e:
        # Silently fail - this is expected in multi-bot mode
        return None

def save_ngrok_url():
    """دریافت و ذخیره URL ngrok"""
    try:
        # چند تلاش برای دریافت URL
        for i in range(10):
            try:
                response = requests.get('http://localhost:4040/api/tunnels', timeout=3)
                data = response.json()
                
                if data.get('tunnels'):
                    for tunnel in data['tunnels']:
                        if tunnel.get('proto') == 'https':
                            url = tunnel.get('public_url')
                            
                            # ذخیره در دیتابیس
                            db_path = Path(__file__).parent / "vpn_bot_professional.db"
                            conn = sqlite3.connect(db_path)
                            cursor = conn.cursor()
                            
                            cursor.execute('''
                                CREATE TABLE IF NOT EXISTS webapp_settings (
                                    id INTEGER PRIMARY KEY,
                                    ngrok_url TEXT,
                                    flask_port INTEGER DEFAULT 5000,
                                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                )
                            ''')
                            
                            cursor.execute('INSERT OR REPLACE INTO webapp_settings (id, ngrok_url) VALUES (1, ?)', (url,))
                            conn.commit()
                            conn.close()
                            
                            print(f"✓ URL ذخیره شد: {url}")
                            print(f"\nدسترسی‌ها:")
                            print(f"  وب‌اپ:  {url}")
                            print(f"  Flask:  http://localhost:5000")
                            print(f"  ngrok:  http://localhost:4040")
                            return url
                
                time.sleep(2)
            except:
                time.sleep(2)
        
        print("✗ نتوانستم URL را دریافت کنم")
        return None
    except Exception as e:
        print(f"خطا: {e}")
        return None

# برای استفاده در فایل‌های دیگر
WEBAPP_URL = get_webapp_url()

if __name__ == '__main__':
    save_ngrok_url()
