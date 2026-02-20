
import psutil
import time
import os
import platform
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SystemMonitor:
    """
    Advanced System Monitor for tracking server health and performance
    """
    
    @staticmethod
    def get_system_stats():
        """
        Get comprehensive system statistics with raw values for frontend processing
        """
        try:
            # CPU Stats
            cpu_percent = psutil.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count()
            
            # Memory Stats
            virtual_mem = psutil.virtual_memory()
            swap_mem = psutil.swap_memory()
            
            # Disk Stats
            disk_usage = psutil.disk_usage('/')
            
            # Network Stats
            net_io = psutil.net_io_counters()
            
            # Boot Time
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            
            # Calculate uptime string
            uptime_dt = datetime.now() - datetime.fromtimestamp(boot_time)
            days = uptime_dt.days
            hours, remainder = divmod(uptime_dt.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{days}d {hours}h {minutes}m"
            
            return {
                'cpu': {
                    'percent': cpu_percent,
                    'cores': cpu_count,
                    'frequency': psutil.cpu_freq().current if psutil.cpu_freq() else 0
                },
                'memory': {
                    'total': virtual_mem.total,
                    'available': virtual_mem.available,
                    'used': virtual_mem.used,
                    'percent': virtual_mem.percent,
                    'swap_percent': swap_mem.percent,
                    'formatted': {
                        'total': SystemMonitor._format_bytes(virtual_mem.total),
                        'used': SystemMonitor._format_bytes(virtual_mem.used)
                    }
                },
                'disk': {
                    'total': disk_usage.total,
                    'used': disk_usage.used,
                    'free': disk_usage.free,
                    'percent': disk_usage.percent,
                    'formatted': {
                        'total': SystemMonitor._format_bytes(disk_usage.total),
                        'used': SystemMonitor._format_bytes(disk_usage.used)
                    }
                },
                'network': {
                    'bytes_sent': net_io.bytes_sent,
                    'bytes_recv': net_io.bytes_recv,
                    'packets_sent': net_io.packets_sent,
                    'packets_recv': net_io.packets_recv,
                    'formatted': {
                        'sent': SystemMonitor._format_bytes(net_io.bytes_sent),
                        'recv': SystemMonitor._format_bytes(net_io.bytes_recv)
                    }
                },
                'uptime': uptime_seconds, # Raw seconds for frontend
                'system': {
                    'os': platform.system(),
                    'release': platform.release(),
                    'uptime_str': uptime_str,
                    'boot_time': datetime.fromtimestamp(boot_time).strftime('%Y-%m-%d %H:%M:%S')
                },
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return None

    @staticmethod
    def _format_bytes(size):
        """Format bytes to human readable string"""
        power = 2**10
        n = 0
        power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
        while size > power:
            size /= power
            n += 1
        return f"{size:.2f} {power_labels.get(n, '')}B"
