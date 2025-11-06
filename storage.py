import json
import os
from datetime import datetime, timedelta

# Fayl yo'llari (Renderda saqlash uchun)
CONFIG_FILE = 'config.json'
STATS_FILE = 'stats.json'
# ADMINS_FILE olib tashlandi
CHANNELS_FILE = 'channels.json' # Majburiy kanallar mantiqi saqlanib qoldi

# --- Yordamchi Funksiyalar ---

def _load_data(file_path, default_value=None):
    """JSON fayldan ma'lumot yuklaydi."""
    if default_value is None:
        default_value = {}
        
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            _save_data(file_path, default_value)
            return default_value
    except (json.JSONDecodeError, FileNotFoundError):
        return default_value

def _save_data(file_path, data):
    """JSON faylga ma'lumot saqlaydi."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- Guruh Sozlamalari (config.json) ---

def get_config(chat_id):
    """Berilgan chat ID uchun sozlamalarni oladi yoki standart sozlamalarni qaytaradi."""
    chat_id_str = str(chat_id)
    data = _load_data(CONFIG_FILE)
    
    # Standart sozlamalar
    if chat_id_str not in data:
        data[chat_id_str] = {
            'free_ad_count': 1,             # Nechta xabar bepul ruxsat etiladi
            'reset_interval_days': 30,      # Hisob necha kunda tiklanadi
            'invite_levels': {'1': 5, '2': 7, 'max': 10} # 1-xabar uchun 5, 2-xabar uchun 7, qolganlariga 10
        }
        _save_data(CONFIG_FILE, data)
        
    return data[chat_id_str]

def update_config(chat_id, key, value):
    """Guruh sozlamalarini yangilaydi."""
    chat_id_str = str(chat_id)
    data = _load_data(CONFIG_FILE)
    
    if chat_id_str not in data:
        get_config(chat_id)

    data[chat_id_str][key] = value
    _save_data(CONFIG_FILE, data)

def get_all_chat_configs():
    """Barcha sozlamalar o'rnatilgan guruh IDlarini qaytaradi."""
    return list(_load_data(CONFIG_FILE).keys())

def add_new_group(chat_id):
    """Yangi guruhni standart sozlamalar bilan qo'shadi."""
    get_config(chat_id)

def delete_group(chat_id):
    """Guruh sozlamalarini va unga tegishli statistikani o'chiradi."""
    chat_id_str = str(chat_id)
    config_data = _load_data(CONFIG_FILE)
    stats_data = _load_data(STATS_FILE)
    
    if chat_id_str in config_data:
        del config_data[chat_id_str]
        _save_data(CONFIG_FILE, config_data)
        
    stats_data = {
        user_id: stats for user_id, stats in stats_data.items() 
        if chat_id_str not in stats
    }
    _save_data(STATS_FILE, stats_data)
    
# --- Foydalanuvchi Statistikasi (stats.json) ---

def _check_and_reset_stats(user_id, chat_id, user_stats, config):
    """Limit tiklanish vaqti kelganini tekshiradi va tiklaydi."""
    reset_interval_days = config.get('reset_interval_days', 30)
    
    if 'last_reset_date' not in user_stats or not user_stats['last_reset_date']:
        return user_stats

    last_reset = datetime.strptime(user_stats['last_reset_date'], '%Y-%m-%d')
    if datetime.now() >= last_reset + timedelta(days=reset_interval_days):
        user_stats['current_ad_cycle_count'] = 0
        user_stats['invited_members_count'] = 0
        user_stats['last_reset_date'] = datetime.now().strftime('%Y-%m-%d')
    
    return user_stats

def get_user_stats(user_id, chat_id, config):
    """Foydalanuvchi statistikasini oladi va kerak bo'lsa tiklaydi."""
    user_id_str = str(user_id)
    chat_id_str = str(chat_id)
    data = _load_data(STATS_FILE)
    
    if user_id_str not in data:
        data[user_id_str] = {}
        
    if chat_id_str not in data[user_id_str]:
        data[user_id_str][chat_id_str] = {
            'current_ad_cycle_count': 0, # Joriy tsiklda yuborilgan xabarlar soni
            'invited_members_count': 0,  # Qo'shilgan odamlar soni
            'last_reset_date': datetime.now().strftime('%Y-%m-%d')
        }

    # Tiklanishni tekshirish
    data[user_id_str][chat_id_str] = _check_and_reset_stats(
        user_id_str, chat_id_str, data[user_id_str][chat_id_str], config
    )
    
    _save_data(STATS_FILE, data)
    return data[user_id_str][chat_id_str]

def update_user_stats(user_id, chat_id, invited_count_change=0, ad_used=False, reset_invited=False):
    """Foydalanuvchi statistikasini yangilaydi."""
    user_id_str = str(user_id)
    chat_id_str = str(chat_id)
    data = _load_data(STATS_FILE)
    
    if user_id_str not in data: data[user_id_str] = {}
    
    stats = data.get(user_id_str, {}).get(chat_id_str, {})
    if not stats:
        return 

    if invited_count_change != 0:
        stats['invited_members_count'] += invited_count_change
        
    if ad_used:
        stats['current_ad_cycle_count'] += 1
        
    if reset_invited:
        stats['invited_members_count'] = 0
        
    data[user_id_str][chat_id_str] = stats
    _save_data(STATS_FILE, data)


# --- Majburiy Kanallar (channels.json) ---

def get_required_channels():
    """Majburiy kanallar ro'yxatini oladi."""
    return _load_data(CHANNELS_FILE, default_value=[])

def add_channel(username):
    """Yangi majburiy kanal qo'shadi."""
    data = _load_data(CHANNELS_FILE, default_value=[])
    
    if not any(c.get('channel_username') == username for c in data):
        data.append({'channel_username': username})
        _save_data(CHANNELS_FILE, data)
        return True
    return False

def delete_channel(username):
    """Majburiy kanalni ro'yxatdan o'chiradi."""
    data = _load_data(CHANNELS_FILE, default_value=[])
    
    initial_length = len(data)
    data = [c for c in data if c.get('channel_username') != username]
    
    if len(data) < initial_length:
        _save_data(CHANNELS_FILE, data)
        return True
    return False
