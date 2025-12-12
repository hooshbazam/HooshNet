"""
Country Name Translator - English to Persian
Automatically translates country names from English to Persian
"""

COUNTRY_NAMES = {
    # Major countries
    'germany': 'آلمان',
    'usa': 'آمریکا',
    'united states': 'آمریکا',
    'uk': 'انگلستان',
    'united kingdom': 'انگلستان',
    'france': 'فرانسه',
    'canada': 'کانادا',
    'netherlands': 'هلند',
    'turkey': 'ترکیه',
    'iran': 'ایران',
    'russia': 'روسیه',
    'china': 'چین',
    'japan': 'ژاپن',
    'south korea': 'کره جنوبی',
    'india': 'هند',
    'singapore': 'سنگاپور',
    'australia': 'استرالیا',
    'brazil': 'برزیل',
    'sweden': 'سوئد',
    'switzerland': 'سوئیس',
    'spain': 'اسپانیا',
    'italy': 'ایتالیا',
    'poland': 'لهستان',
    'finland': 'فنلاند',
    'norway': 'نروژ',
    'denmark': 'دانمارک',
    'belgium': 'بلژیک',
    'austria': 'اتریش',
    'ireland': 'ایرلند',
    'czech republic': 'چک',
    'greece': 'یونان',
    'portugal': 'پرتغال',
    'romania': 'رومانی',
    'hungary': 'مجارستان',
    'bulgaria': 'بلغارستان',
    'ukraine': 'اوکراین',
    'israel': 'اسرائیل',
    'uae': 'امارات',
    'united arab emirates': 'امارات',
    'saudi arabia': 'عربستان',
    'qatar': 'قطر',
    'kuwait': 'کویت',
    'bahrain': 'بحرین',
    'oman': 'عمان',
    'iraq': 'عراق',
    'egypt': 'مصر',
    'south africa': 'آفریقای جنوبی',
    'morocco': 'مراکش',
    'algeria': 'الجزایر',
    'tunisia': 'تونس',
    'mexico': 'مکزیک',
    'argentina': 'آرژانتین',
    'chile': 'شیلی',
    'colombia': 'کلمبیا',
    'vietnam': 'ویتنام',
    'thailand': 'تایلند',
    'malaysia': 'مالزی',
    'indonesia': 'اندونزی',
    'philippines': 'فیلیپین',
    'pakistan': 'پاکستان',
    'bangladesh': 'بنگلادش',
    'kazakhstan': 'قزاقستان',
    'armenia': 'ارمنستان',
    'georgia': 'گرجستان',
    'azerbaijan': 'آذربایجان',
    'lithuania': 'لیتوانی',
    'latvia': 'لتونی',
    'estonia': 'استونی',
    'serbia': 'صربستان',
    'croatia': 'کرواسی',
    'slovenia': 'اسلوونی',
    'slovakia': 'اسلواکی',
    'moldova': 'مولداوی',
    'belarus': 'بلاروس',
    'iceland': 'ایسلند',
    'luxembourg': 'لوکزامبورگ',
    'malta': 'مالت',
    'cyprus': 'قبرس',
    'hong kong': 'هنگ کنگ',
    'taiwan': 'تایوان',
    'new zealand': 'نیوزیلند',
}


def translate_country(english_name: str) -> str:
    """
    Translate country name from English to Persian
    
    Args:
        english_name: Country name in English (case-insensitive)
        
    Returns:
        Persian name if found, otherwise returns original name
    """
    if not english_name:
        return 'نامشخص'
    
    # Convert to lowercase for matching
    name_lower = english_name.lower().strip()
    
    # Direct match
    if name_lower in COUNTRY_NAMES:
        return COUNTRY_NAMES[name_lower]
    
    # Partial match (for names like "Germany 1", "USA West", etc.)
    for eng, per in COUNTRY_NAMES.items():
        if eng in name_lower:
            return per
    
    # If no match found, return original name
    return english_name


def extract_country_from_panel_name(panel_name: str) -> str:
    """
    Extract and translate country name from panel name
    
    Args:
        panel_name: Panel name (e.g., "Germany 🇩🇪", "USA West", etc.)
        
    Returns:
        Persian country name
    """
    if not panel_name:
        return 'نامشخص'
    
    # Remove emojis and extra characters
    import re
    cleaned_name = re.sub(r'[^\w\s]', ' ', panel_name)
    
    # Try to translate
    return translate_country(cleaned_name)

