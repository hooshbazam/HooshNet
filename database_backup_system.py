"""
Database Backup System for VPN Bot
Automatically creates and sends database backups to reports channel every hour
"""

import logging
import asyncio
import os
import gzip
import base64
import platform
from datetime import datetime
from typing import Dict, Optional
from telegram import Bot
from telegram.error import TelegramError
from persian_datetime import PersianDateTime
import subprocess
import tempfile
import shutil

logger = logging.getLogger(__name__)

class DatabaseBackupSystem:
    """Automated database backup system"""
    
    def __init__(self, bot: Bot, bot_config: Dict, db_config: Dict):
        """
        Initialize Database Backup System
        
        Args:
            bot: Telegram Bot instance
            bot_config: Bot configuration dict (must contain 'reports_channel_id')
            db_config: Database configuration dict (must contain connection details)
        """
        self.bot = bot
        self.bot_config = bot_config
        self.db_config = db_config
        self.channel_id = bot_config.get('reports_channel_id')
        self.bot_username = bot_config.get('bot_username', 'Unknown')
        self.bot_name = bot_config.get('bot_name', bot_config.get('bot_username', 'Unknown'))
        
        if not self.channel_id:
            logger.error(f"❌ CRITICAL: No reports_channel_id found in bot_config for bot '{self.bot_name}'")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"✅ DatabaseBackupSystem initialized for bot '{self.bot_name}' with channel ID: {self.channel_id}")
    
    def _find_mysqldump(self) -> Optional[str]:
        """Find mysqldump executable path"""
        # First try direct command (if in PATH)
        try:
            result = subprocess.run(['mysqldump', '--version'], 
                                  capture_output=True, 
                                  timeout=5)
            if result.returncode == 0:
                return 'mysqldump'
        except:
            pass
        
        # Try common Windows paths
        if platform.system() == 'Windows':
            common_paths = [
                r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe',
                r'C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe',
                r'C:\Program Files (x86)\MySQL\MySQL Server 8.0\bin\mysqldump.exe',
                r'C:\Program Files (x86)\MySQL\MySQL Server 8.4\bin\mysqldump.exe',
                r'C:\xampp\mysql\bin\mysqldump.exe',
                r'C:\wamp\bin\mysql\mysql*\bin\mysqldump.exe',
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    logger.info(f"✅ Found mysqldump at: {path}")
                    return path
                
                # Try wildcard expansion for wamp
                if '*' in path:
                    import glob
                    matches = glob.glob(path)
                    if matches:
                        logger.info(f"✅ Found mysqldump at: {matches[0]}")
                        return matches[0]
        
        return None
    
    async def _create_backup_with_python(self, db_host: str, db_port: int, db_user: str, 
                                        db_password: str, db_name: str, backup_path: str) -> bool:
        """Create backup using Python MySQL connector"""
        try:
            import mysql.connector
            from mysql.connector import Error
            
            logger.info(f"Using Python MySQL connector for backup...")
            
            connection = None
            try:
                connection = mysql.connector.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_password,
                    database=db_name
                )
                
                cursor = connection.cursor()
                
                # Get all tables
                cursor.execute("SHOW TABLES")
                tables = [table[0] for table in cursor.fetchall()]
                
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(f"-- MySQL Backup\n")
                    f.write(f"-- Database: {db_name}\n")
                    f.write(f"-- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"SET FOREIGN_KEY_CHECKS=0;\n\n")
                    
                    # Dump each table
                    for table in tables:
                        logger.debug(f"Dumping table: {table}")
                        f.write(f"\n-- Table: {table}\n")
                        f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                        
                        # Get CREATE TABLE statement
                        cursor.execute(f"SHOW CREATE TABLE `{table}`")
                        create_table = cursor.fetchone()[1]
                        f.write(f"{create_table};\n\n")
                        
                        # Get table data
                        cursor.execute(f"SELECT * FROM `{table}`")
                        rows = cursor.fetchall()
                        
                        if rows:
                            # Get column names
                            cursor.execute(f"DESCRIBE `{table}`")
                            columns = [col[0] for col in cursor.fetchall()]
                            
                            f.write(f"LOCK TABLES `{table}` WRITE;\n")
                            for row in rows:
                                values = []
                                for val in row:
                                    if val is None:
                                        values.append('NULL')
                                    elif isinstance(val, bool):
                                        values.append('1' if val else '0')
                                    elif isinstance(val, (int, float)):
                                        values.append(str(val))
                                    elif isinstance(val, datetime):
                                        values.append(f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'")
                                    else:
                                        # Escape string values properly
                                        val_str = str(val)
                                        # Escape backslashes first, then single quotes
                                        val_str = val_str.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
                                        values.append(f"'{val_str}'")
                                
                                f.write(f"INSERT INTO `{table}` (`{'`, `'.join(columns)}`) VALUES ({', '.join(values)});\n")
                            f.write(f"UNLOCK TABLES;\n\n")
                    
                    f.write(f"SET FOREIGN_KEY_CHECKS=1;\n")
                
                cursor.close()
                return True
                
            except Error as e:
                logger.error(f"❌ MySQL error: {e}")
                return False
            finally:
                if connection and connection.is_connected():
                    connection.close()
                    
        except ImportError:
            logger.error("❌ mysql-connector-python not installed. Install it with: pip install mysql-connector-python")
            return False
        except Exception as e:
            logger.error(f"❌ Error creating backup with Python: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def create_backup(self) -> Optional[str]:
        """
        Create a complete database backup
        
        Returns:
            Path to backup file or None if failed
        """
        temp_dir = None
        try:
            # Get database connection details
            db_host = self.db_config.get('host', 'localhost')
            db_port = self.db_config.get('port', 3306)
            db_user = self.db_config.get('user', 'root')
            db_password = self.db_config.get('password', '')
            db_name = self.db_config.get('database', 'vpn_bot')
            
            # Create temporary directory for backup
            temp_dir = tempfile.mkdtemp()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"backup_{db_name}_{timestamp}.sql"
            backup_path = os.path.join(temp_dir, backup_filename)
            
            logger.info(f"Creating database backup for {db_name}...")
            
            # Try to find mysqldump
            mysqldump_path = self._find_mysqldump()
            
            if mysqldump_path:
                # Use mysqldump if available
                env = os.environ.copy()
                env['MYSQL_PWD'] = db_password
                
                cmd = [
                    mysqldump_path,
                    f'--host={db_host}',
                    f'--port={db_port}',
                    f'--user={db_user}',
                    '--single-transaction',
                    '--routines',
                    '--triggers',
                    '--events',
                    '--quick',
                    '--lock-tables=false',
                    db_name
                ]
                
                # Execute mysqldump
                with open(backup_path, 'wb') as f:
                    result = subprocess.run(
                        cmd,
                        env=env,
                        stdout=f,
                        stderr=subprocess.PIPE,
                        timeout=300  # 5 minutes timeout
                    )
                
                if result.returncode != 0:
                    error_msg = result.stderr.decode('utf-8', errors='ignore')
                    logger.error(f"❌ mysqldump failed: {error_msg}")
                    logger.info("⚠️ Falling back to Python-based backup...")
                    # Fall back to Python method
                    if not await self._create_backup_with_python(db_host, db_port, db_user, db_password, db_name, backup_path):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return None
                else:
                    logger.info("✅ Backup created using mysqldump")
            else:
                # Use Python-based backup
                logger.info("⚠️ mysqldump not found, using Python-based backup...")
                if not await self._create_backup_with_python(db_host, db_port, db_user, db_password, db_name, backup_path):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return None
            
            # Compress backup
            compressed_path = f"{backup_path}.gz"
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove uncompressed file
            os.remove(backup_path)
            
            # Get file size
            file_size = os.path.getsize(compressed_path)
            logger.info(f"✅ Backup created successfully: {compressed_path} ({file_size / 1024 / 1024:.2f} MB)")
            
            return compressed_path
            
        except subprocess.TimeoutExpired:
            logger.error("❌ Backup creation timed out")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        except Exception as e:
            logger.error(f"❌ Error creating backup: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return None
    
    async def send_backup_to_channel(self, backup_path: str):
        """
        Send backup file to reports channel
        
        Args:
            backup_path: Path to backup file
        """
        if not self.enabled:
            logger.debug(f"Backup system disabled for bot '{self.bot_name}' - skipping backup send")
            return
        
        try:
            timestamp = PersianDateTime.format_full_datetime()
            file_size = os.path.getsize(backup_path)
            file_size_mb = file_size / 1024 / 1024
            
            # Escape special characters for Markdown
            db_name = self.db_config.get('database', 'نامشخص')
            # Escape underscores and other special chars in database name
            db_name_escaped = db_name.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
            bot_username_escaped = self.bot_username.replace('_', '\\_')
            
            # Create caption with escaped special characters
            caption = f"""💾 بکاپ کامل دیتابیس

⏰ زمان: {timestamp}
🤖 ربات: @{bot_username_escaped}
📊 نام دیتابیس: `{db_name_escaped}`
📦 حجم فایل: {file_size_mb:.2f} MB
📅 تاریخ بکاپ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ وضعیت: بکاپ با موفقیت ایجاد شد"""
            
            # Send file to channel
            with open(backup_path, 'rb') as f:
                await self.bot.send_document(
                    chat_id=self.channel_id,
                    document=f,
                    filename=os.path.basename(backup_path),
                    caption=caption,
                    parse_mode='Markdown'
                )
            
            logger.info(f"✅ Backup sent successfully to channel {self.channel_id}")
            
            # Clean up backup file
            try:
                os.remove(backup_path)
                # Remove parent directory if empty
                backup_dir = os.path.dirname(backup_path)
                if os.path.exists(backup_dir):
                    try:
                        os.rmdir(backup_dir)
                    except:
                        pass  # Directory not empty, ignore
            except Exception as e:
                logger.warning(f"⚠️ Failed to clean up backup file: {e}")
                
        except TelegramError as e:
            logger.error(f"❌ Telegram error sending backup: {e}")
            # Try to send error message
            try:
                error_text = str(e)[:200].replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
                bot_username_escaped = self.bot_username.replace('_', '\\_')
                error_msg = f"⚠️ خطا در ارسال بکاپ\n\n🤖 ربات: @{bot_username_escaped}\n⏰ زمان: {PersianDateTime.format_full_datetime()}\n\nخطا: {error_text}"
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=error_msg,
                    parse_mode='Markdown'
                )
            except:
                pass
        except Exception as e:
            logger.error(f"❌ Error sending backup: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def create_and_send_backup(self):
        """Create backup and send to channel"""
        if not self.enabled:
            return None
        
        logger.info(f"🔄 Starting automated backup for bot '{self.bot_name}'...")
        
        backup_path = await self.create_backup()
        if backup_path:
            await self.send_backup_to_channel(backup_path)
            return backup_path
        else:
            logger.error(f"❌ Failed to create backup for bot '{self.bot_name}'")
            # Send error notification
            try:
                bot_username_escaped = self.bot_username.replace('_', '\\_')
                error_msg = f"⚠️ خطا در ایجاد بکاپ\n\n🤖 ربات: @{bot_username_escaped}\n⏰ زمان: {PersianDateTime.format_full_datetime()}\n\n❌ بکاپ دیتابیس با خطا مواجه شد."
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=error_msg,
                    parse_mode='Markdown'
                )
            except:
                pass
            return None
    
    async def start_auto_backup(self, interval_hours: int = 1):
        """
        Start automatic backup scheduler
        
        Args:
            interval_hours: Hours between backups (default: 1)
        """
        if not self.enabled:
            logger.warning(f"⚠️ Backup system disabled for bot '{self.bot_name}' - not starting scheduler")
            return
        
        logger.info(f"🚀 Starting automatic backup scheduler for bot '{self.bot_name}' (interval: {interval_hours} hours)")
        
        interval_seconds = interval_hours * 3600
        
        while True:
            try:
                await self.create_and_send_backup()
                logger.info(f"⏰ Next backup scheduled in {interval_hours} hour(s)")
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"❌ Error in backup scheduler: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Wait before retrying
                await asyncio.sleep(60)  # Wait 1 minute before retrying

