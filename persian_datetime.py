"""
Persian DateTime Utilities
Provides functions for working with Persian (Jalali) calendar and Tehran timezone
"""

import jdatetime
import pytz
from datetime import datetime
from typing import Optional

# Tehran timezone
TEHRAN_TZ = pytz.timezone('Asia/Tehran')

class PersianDateTime:
    """Helper class for Persian datetime operations"""
    
    @staticmethod
    def now() -> jdatetime.datetime:
        """Get current datetime in Tehran timezone as Jalali"""
        utc_now = datetime.now(pytz.UTC)
        tehran_now = utc_now.astimezone(TEHRAN_TZ)
        return jdatetime.datetime.fromgregorian(datetime=tehran_now)
    
    @staticmethod
    def now_gregorian() -> datetime:
        """Get current datetime in Tehran timezone as Gregorian"""
        utc_now = datetime.now(pytz.UTC)
        return utc_now.astimezone(TEHRAN_TZ)
    
    @staticmethod
    def format_datetime(dt: Optional[datetime] = None, include_time: bool = True) -> str:
        """
        Format datetime to Persian string
        
        Args:
            dt: datetime object (if None, uses current time)
            include_time: whether to include time in output
            
        Returns:
            Formatted Persian datetime string
        """
        if dt is None:
            jalali_dt = PersianDateTime.now()
        else:
            # Convert to Tehran timezone if it has timezone info
            if dt.tzinfo is not None:
                dt = dt.astimezone(TEHRAN_TZ)
            else:
                # Assume it's UTC and convert
                dt = pytz.UTC.localize(dt).astimezone(TEHRAN_TZ)
            
            jalali_dt = jdatetime.datetime.fromgregorian(datetime=dt)
        
        if include_time:
            return jalali_dt.strftime('%Y/%m/%d %H:%M:%S')
        else:
            return jalali_dt.strftime('%Y/%m/%d')
    
    @staticmethod
    def format_date_persian(dt: Optional[datetime] = None) -> str:
        """
        Format date to Persian with month names
        
        Args:
            dt: datetime object (if None, uses current time)
            
        Returns:
            Formatted Persian date string with month name
        """
        if dt is None:
            jalali_dt = PersianDateTime.now()
        else:
            # Convert to Tehran timezone if it has timezone info
            if dt.tzinfo is not None:
                dt = dt.astimezone(TEHRAN_TZ)
            else:
                # Assume it's UTC and convert
                dt = pytz.UTC.localize(dt).astimezone(TEHRAN_TZ)
            
            jalali_dt = jdatetime.datetime.fromgregorian(datetime=dt)
        
        # Persian month names
        month_names = {
            1: 'فروردین',
            2: 'اردیبهشت',
            3: 'خرداد',
            4: 'تیر',
            5: 'مرداد',
            6: 'شهریور',
            7: 'مهر',
            8: 'آبان',
            9: 'آذر',
            10: 'دی',
            11: 'بهمن',
            12: 'اسفند'
        }
        
        return f"{jalali_dt.day} {month_names[jalali_dt.month]} {jalali_dt.year}"
    
    @staticmethod
    def format_time(dt: Optional[datetime] = None) -> str:
        """
        Format time only
        
        Args:
            dt: datetime object (if None, uses current time)
            
        Returns:
            Formatted time string
        """
        if dt is None:
            tehran_dt = PersianDateTime.now_gregorian()
        else:
            # Convert to Tehran timezone if it has timezone info
            if dt.tzinfo is not None:
                tehran_dt = dt.astimezone(TEHRAN_TZ)
            else:
                # Assume it's UTC and convert
                tehran_dt = pytz.UTC.localize(dt).astimezone(TEHRAN_TZ)
        
        return tehran_dt.strftime('%H:%M:%S')
    
    @staticmethod
    def parse_datetime(datetime_str: str) -> Optional[datetime]:
        """
        Parse datetime string to datetime object
        
        Args:
            datetime_str: datetime string from database
            
        Returns:
            datetime object or None
        """
        try:
            if not datetime_str:
                return None
            # Try parsing common formats
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y/%m/%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%SZ',
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(datetime_str, fmt)
                    # Return naive datetime to match database format
                    return dt
                except ValueError:
                    continue
            
            return None
        except Exception:
            return None
    
    @staticmethod
    def get_persian_weekday(dt: Optional[datetime] = None) -> str:
        """
        Get Persian weekday name
        
        Args:
            dt: datetime object (if None, uses current time)
            
        Returns:
            Persian weekday name
        """
        if dt is None:
            dt = PersianDateTime.now_gregorian()
        elif dt.tzinfo is None:
            dt = TEHRAN_TZ.localize(dt)
        else:
            dt = dt.astimezone(TEHRAN_TZ)
        
        weekday_names = {
            0: 'شنبه',
            1: 'یکشنبه',
            2: 'دوشنبه',
            3: 'سه‌شنبه',
            4: 'چهارشنبه',
            5: 'پنج‌شنبه',
            6: 'جمعه'
        }
        
        # Python's weekday: Monday is 0, Sunday is 6
        # Persian week: Saturday is 0, Friday is 6
        python_weekday = dt.weekday()
        persian_weekday = (python_weekday + 2) % 7
        
        return weekday_names[persian_weekday]
    
    @staticmethod
    def format_full_datetime(dt: Optional[datetime] = None) -> str:
        """
        Format full datetime with weekday
        
        Args:
            dt: datetime object (if None, uses current time)
            
        Returns:
            Full formatted Persian datetime string
        """
        weekday = PersianDateTime.get_persian_weekday(dt)
        date = PersianDateTime.format_date_persian(dt)
        time = PersianDateTime.format_time(dt)
        
        return f"{weekday}، {date} - ساعت {time}"


# Convenience functions
def now_persian() -> str:
    """Get current datetime as Persian string"""
    return PersianDateTime.format_datetime()

def now_persian_date() -> str:
    """Get current date as Persian string"""
    return PersianDateTime.format_date_persian()

def now_persian_time() -> str:
    """Get current time as Persian string"""
    return PersianDateTime.format_time()

def format_db_datetime(datetime_str: str) -> str:
    """Format database datetime string to Persian"""
    dt = PersianDateTime.parse_datetime(datetime_str)
    if dt:
        return PersianDateTime.format_datetime(dt)
    return datetime_str

def format_db_date(datetime_str: str) -> str:
    """Format database datetime string to Persian date only"""
    dt = PersianDateTime.parse_datetime(datetime_str)
    if dt:
        return PersianDateTime.format_date_persian(dt)
    return datetime_str

