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

class DatabaseBackupManager:
    """Automated database backup system"""
    
    def __init__(self, db_manager, bot: Bot = None, bot_config: Dict = None):
        """
        Initialize Database Backup Manager
        
        Args:
            db_manager: ProfessionalDatabaseManager instance
            bot: Telegram Bot instance (optional, for auto-backups)
            bot_config: Bot configuration dict (optional)
        """
        self.db_manager = db_manager
        self.db_config = db_manager.db_config
        self.bot = bot
        self.bot_config = bot_config or {}
        self.enabled = True
        self.bot_username = self.bot_config.get('bot_username') or 'Unknown'
        self.bot_name = self.bot_config.get('bot_name') or self.bot_username or 'Unknown'
        self.channel_id = None
        self._refresh_runtime_config()
        if not self.channel_id:
            logger.warning(f"⚠️ No reports_channel_id found for bot '{self.bot_name}'")
            self.enabled = False
        else:
            logger.info(f"✅ DatabaseBackupManager initialized for bot '{self.bot_name}' with channel ID: {self.channel_id}")

    def _refresh_runtime_config(self):
        bot_username = self.bot_config.get('bot_username')
        bot_name = self.bot_config.get('bot_name')
        if bot_username:
            self.bot_username = bot_username
        if bot_name:
            self.bot_name = bot_name
        elif bot_username:
            self.bot_name = bot_username

        channel_id = self.bot_config.get('reports_channel_id')
        if not channel_id:
            try:
                from settings_manager import SettingsManager
                settings_mgr = SettingsManager(self.db_manager)
                channel_id = settings_mgr.get_setting('reports_channel_id')
            except Exception:
                channel_id = None

        if channel_id in (None, '', 0, '0'):
            channel_id = None

        self.channel_id = channel_id
        self.enabled = bool(self.channel_id)
            
    async def ensure_backup_topic(self) -> int:
        """
        Ensure backup topic exists in reports channel
        Returns topic ID (message_thread_id)
        """
        if not self.channel_id or not self.enabled:
            return 0
            
        try:
            from settings_manager import SettingsManager
            from telegram_helper import TelegramHelper
            
            settings_mgr = SettingsManager(self.db_manager)
            topic_id = int(settings_mgr.get_setting('backup_topic_id', 0))
            
            if topic_id == 0:
                logger.info(f"Creating new backup topic for channel {self.channel_id}...")
                topic_id = await TelegramHelper.create_forum_topic(self.channel_id, "💾 Backups")
                
                if topic_id > 0:
                    settings_mgr.set_setting('backup_topic_id', topic_id, description="Backup Topic ID", updated_by=0)
                    logger.info(f"✅ Backup topic created with ID: {topic_id}")
                else:
                    logger.warning("⚠️ Failed to create backup topic, will send to main channel")
            
            return topic_id
        except Exception as e:
            logger.error(f"❌ Error ensuring backup topic: {e}")
            return 0
    
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

    def _find_mysql(self) -> Optional[str]:
        """Find mysql executable path"""
        # First try direct command (if in PATH)
        try:
            result = subprocess.run(['mysql', '--version'], 
                                  capture_output=True, 
                                  timeout=5)
            if result.returncode == 0:
                return 'mysql'
        except:
            pass
        
        # Try common Windows paths (same as mysqldump but replace mysqldump.exe with mysql.exe)
        if platform.system() == 'Windows':
            paths = [
                r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
                r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe",
                r"C:\xampp\mysql\bin\mysql.exe",
                r"D:\xampp\mysql\bin\mysql.exe",
                r"C:\wamp64\bin\mysql\mysql8.0.21\bin\mysql.exe"
            ]
            for path in paths:
                if os.path.exists(path):
                    return path
                    
        return None

    async def restore_database(self, backup_path: str) -> bool:
        """
        Restore database from backup file
        
        Args:
            backup_path: Path to .sql or .sql.gz file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🔄 Starting database restore from {backup_path}...")
            
            # 1. Determine if we need to unzip
            sql_file_path = backup_path
            is_gzipped = backup_path.endswith('.gz')
            temp_sql_file = None
            
            if is_gzipped:
                logger.info("📂 Decompressing backup file...")
                fd, temp_sql_file = tempfile.mkstemp(suffix='.sql')
                os.close(fd)
                
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_sql_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                sql_file_path = temp_sql_file
                
            # 2. Find mysql executable
            mysql_cmd = self._find_mysql()
            use_python_restore = False
            
            if not mysql_cmd:
                logger.warning("⚠️ 'mysql' command not found, will use Python restore...")
                use_python_restore = True
            
            if not use_python_restore:
                try:
                    # 3. Construct command
                    # mysql -h host -u user -p password dbname < file.sql
                    
                    env = os.environ.copy()
                    if self.db_config.get('password'):
                        env['MYSQL_PWD'] = self.db_config['password']
                        
                    cmd = []
                    cmd.append(mysql_cmd)
                        
                    if self.db_config.get('host'):
                        cmd.extend(['-h', self.db_config['host']])
                    if self.db_config.get('port'):
                        cmd.extend(['-P', str(self.db_config['port'])])
                    if self.db_config.get('user'):
                        cmd.extend(['-u', self.db_config['user']])
                    
                    # Add database name
                    cmd.append(self.db_config['database'])
                    
                    logger.info(f"🚀 Executing restore command...")
                    
                    # Run command with input redirection
                    with open(sql_file_path, 'r', encoding='utf-8') as f:
                        process = subprocess.Popen(
                            cmd,
                            stdin=f,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=env,
                            shell=False
                        )
                        stdout, stderr = process.communicate()
                        
                    if process.returncode != 0:
                        logger.error(f"❌ Restore failed with code {process.returncode}")
                        logger.error(f"Stderr: {stderr.decode('utf-8', errors='ignore')}")
                        # Fallback to Python restore on failure
                        use_python_restore = True
                    else:
                        logger.info("✅ Database restored successfully!")
                        return True
                        
                except FileNotFoundError:
                    logger.warning("⚠️ 'mysql' executable not found (FileNotFoundError). Switching to Python restore...")
                    use_python_restore = True
                except Exception as e:
                    logger.error(f"❌ Error executing mysql command: {e}")
                    use_python_restore = True
            
            if use_python_restore:
                logger.info("🔄 Using Python-based restore system (DatabaseRestoreManager)...")
                try:
                    # Import here to avoid circular dependencies
                    from database_restore_system import DatabaseRestoreManager
                    
                    # Run in executor to avoid blocking
                    def run_restore():
                        restore_manager = DatabaseRestoreManager(self.db_manager)
                        return restore_manager.restore_backup(sql_file_path)
                    
                    loop = asyncio.get_event_loop()
                    result_msg = await loop.run_in_executor(None, run_restore)
                    
                    if "❌" in result_msg:
                        logger.error(f"❌ Python restore failed: {result_msg}")
                        return False
                        
                    logger.info(f"✅ Python restore success: {result_msg}")
                    return True
                    
                except Exception as e:
                    logger.error(f"❌ Python restore error: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return False
            
        except Exception as e:
            logger.error(f"❌ Error restoring database: {e}")
            return False
        finally:
            # Cleanup temp file
            if temp_sql_file and os.path.exists(temp_sql_file):
                try:
                    os.remove(temp_sql_file)
                except:
                    pass
    
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
    
    async def send_backup_to_channel(self, backup_path: str) -> bool:
        """
        Send backup file to reports channel
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        self._refresh_runtime_config()
        if not self.enabled or not self.channel_id or not self.bot:
            logger.debug(f"Backup system not ready for bot '{self.bot_name}' (enabled={self.enabled}, channel_id={self.channel_id}, bot_set={bool(self.bot)}) - skipping backup send")
            return False
        
        success = False
        try:
            # Ensure topic exists
            topic_id = await self.ensure_backup_topic()
            kwargs = {}
            if topic_id > 0:
                kwargs['message_thread_id'] = topic_id
            
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
                    parse_mode='Markdown',
                    message_thread_id=kwargs.get('message_thread_id')
                )
            
            logger.info(f"✅ Backup sent successfully to channel {self.channel_id}")
            success = True
            
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
                    parse_mode='Markdown',
                    message_thread_id=kwargs.get('message_thread_id')
                )
            except:
                pass
            success = False
            
        except Exception as e:
            logger.error(f"❌ Error sending backup: {e}")
            import traceback
            logger.error(traceback.format_exc())
            success = False
            
        finally:
            # Clean up backup file regardless of success/failure
            try:
                if os.path.exists(backup_path):
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
                
        return success
    
    async def create_and_send_backup(self):
        """Create backup and send to channel"""
        self._refresh_runtime_config()
        if not self.enabled or not self.channel_id or not self.bot:
            return None
        
        logger.info(f"🔄 Starting automated backup for bot '{self.bot_name}'...")
        
        backup_path = await self.create_backup()
        if backup_path:
            sent = await self.send_backup_to_channel(backup_path)
            if sent:
                return backup_path
            else:
                logger.error(f"❌ Backup created but failed to send for bot '{self.bot_name}'")
                return None
        else:
            logger.error(f"❌ Failed to create backup for bot '{self.bot_name}'")
            # Send error notification
            try:
                bot_username_escaped = self.bot_username.replace('_', '\\_')
                error_msg = f"⚠️ خطا در ایجاد بکاپ\n\n🤖 ربات: @{bot_username_escaped}\n⏰ زمان: {PersianDateTime.format_full_datetime()}\n\n❌ بکاپ دیتابیس با خطا مواجه شد."
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=error_msg,
                    parse_mode='Markdown',
                    message_thread_id=await self.ensure_backup_topic() or None
                )
            except:
                pass
            return None
    
    async def start_auto_backup(self, interval_hours: int = 1):
        """
        Start automatic backup scheduler
        """
        logger.info(f"🚀 Starting automatic backup scheduler for bot '{self.bot_name}'")
        
        if not self.enabled:
            logger.warning(f"⚠️ Backup system disabled for bot '{self.bot_name}' (check reports_channel_id in .env)")
        
        from settings_manager import SettingsManager
        # Initialize SettingsManager with the existing db_manager
        settings_mgr = SettingsManager(self.db_manager)
        
        # Ensure backup topic exists at startup
        await self.ensure_backup_topic()
        
        # Log initial status
        enabled_setting = settings_mgr.get_setting('auto_backup_enabled', False)
        frequency_setting = settings_mgr.get_setting('auto_backup_frequency', 24)
        unit_setting = settings_mgr.get_setting('auto_backup_frequency_unit', 'hours')
        logger.info(f"📊 Auto backup status: {'Enabled' if enabled_setting else 'Disabled'} (Frequency: {frequency_setting} {unit_setting})")
        
        while True:
            try:
                self._refresh_runtime_config()
                # Reload settings
                enabled = settings_mgr.get_setting('auto_backup_enabled', False)
                frequency = settings_mgr.get_setting('auto_backup_frequency', 24)
                unit = settings_mgr.get_setting('auto_backup_frequency_unit', 'hours')
                last_backup_str = settings_mgr.get_setting('last_auto_backup_time')
                
                # Calculate required interval in seconds
                if unit == 'minutes':
                    interval_seconds = frequency * 60
                else:
                    interval_seconds = frequency * 3600
                
                if not enabled:
                    # Check every 10 minutes if enabled
                    await asyncio.sleep(600) 
                    continue

                if not self.channel_id or not self.bot:
                    await asyncio.sleep(600)
                    continue
                
                should_backup = False
                if not last_backup_str:
                    should_backup = True
                else:
                    try:
                        last_backup = datetime.fromisoformat(last_backup_str)
                        # Check if enough time has passed
                        if (datetime.now() - last_backup).total_seconds() >= interval_seconds:
                            should_backup = True
                    except:
                        should_backup = True
                
                if should_backup:
                    logger.info(f"⏰ Starting scheduled backup (Frequency: {frequency} {unit})...")
                    if await self.create_and_send_backup():
                        settings_mgr.set_setting('last_auto_backup_time', datetime.now().isoformat(), description="Last Auto Backup Time", updated_by=0)
                        logger.info("✅ Scheduled backup completed and time updated.")
                    else:
                        logger.warning("⚠️ Scheduled backup failed or not sent. Will retry next cycle.")
                
                # Dynamic sleep: check more frequently if interval is small
                sleep_time = 600  # Default 10 minutes
                if interval_seconds < 3600:
                    sleep_time = 60  # Check every minute for small intervals
                
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"❌ Error in backup scheduler: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Wait before retrying
                await asyncio.sleep(60)

