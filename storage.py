import json
import os
import hashlib
from datetime import datetime # Xato bartaraf etildi: 'datetime' import qilindi

# Fayl nomlari
CONFIG_FILE = 'data/config.json'
USER_STATS_FILE = 'data/user_stats.json'
ADMIN_CREDS_FILE = 'data/admin_creds.json'
CHANNELS_FILE = 'data/channels.json'

# Ma'lumotlar saqlanadigan papka
DATA_DIR = 'data'

def _load_data(file_path, default_value=None):
    """Fayldan JSON ma'lumotlarni yuklash."""
    if default_value is None:
        default_value = {}
        
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    if not os.path.exists(file_path):
        _save_data(file_path, default_value)
        return default_value
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return default_value

def _save_data(file_path, data):
    """JSON ma'lumotlarni faylga saqlash."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# --- Guruh konfiguratsiyasi (Limit sozlamalari) ---

def get_config(chat_id):
    """Guruh konfiguratsiyasini yuklaydi, mavjud bo'lmasa standart qiymatlarni beradi."""
    configs = _load_data(CONFIG_FILE)
    chat_id_str = str(chat_id)
    
    if chat_id_str not in configs:
        # Standart sozlamalar
        configs[chat_id_str] = {
            'free_ad_count': 1,         # Bepul reklama soni
            'reset_interval_days': 30,  # Limit tiklanish muddati (kun)
            'invite_levels': {          # Keyingi reklamalar uchun takliflar soni
                "1": 5,                 # 1-reklama uchun 5 ta odam
                "2": 10,                # 2-reklama uchun 10 ta odam
                "max": 15               # Qolgan barchasi uchun 15 ta odam
            }
        }
        _save_data(CONFIG_FILE, configs)
        
    return configs[chat_id_str]

def update_config(chat_id, key, value):
    """Guruh konfiguratsiyasini yangilaydi."""
    configs = _load_data(CONFIG_FILE)
    chat_id_str = str(chat_id)
    
    if chat_id_str not in configs:
        get_config(chat_id) # Standart sozlamalarni yaratadi
        configs = _load_data(CONFIG_FILE) 
        
    configs[chat_id_str][key] = value
    _save_data(CONFIG_FILE, configs)
    
def get_all_chat_configs():
    """Barcha konfiguratsiya ID'larini (guruh ID'larini) qaytaradi."""
    configs = _load_data(CONFIG_FILE)
    return list(configs.keys())

def add_new_group(chat_id):
    """Yangi guruhni limit sozlamalariga qo'shadi (agar yo'q bo'lsa standart sozlamalarni yaratadi)."""
    get_config(chat_id) # Bu funksiya avtomatik ravishda mavjud bo'lmasa yaratadi


# --- Foydalanuvchi statistikasi ---

def get_user_stats(user_id, chat_id, config):
    """Foydalanuvchi statistikasini yuklaydi va kerak bo'lsa tiklaydi."""
    stats = _load_data(USER_STATS_FILE)
    user_id_str = str(user_id)
    chat_id_str = str(chat_id)
    
    if user_id_str not in stats:
        stats[user_id_str] = {}
        
    if chat_id_str not in stats[user_id_str]:
        stats[user_id_str][chat_id_str] = {
            'invited_members_count': 0, # Qo'shgan odamlar soni
            'ad_cycle_count': 0,        # Reklama yuborish soni (level)
            'last_reset_date': None     # Limit oxirgi tiklangan sana
        }
        _save_data(USER_STATS_FILE, stats)

    user_data = stats[user_id_str][chat_id_str]
    reset_interval = config.get('reset_interval_days', 30)
    
    # Tiklash mantiqi (Agar limit muddati tugagan bo'lsa)
    last_reset = user_data.get('last_reset_date')
    if last_reset:
        last_reset_dt = datetime.strptime(last_reset, "%Y-%m-%d")
        if (datetime.now() - last_reset_dt).days >= reset_interval:
            user_data['invited_members_count'] = 0
            user_data['ad_cycle_count'] = 0
            user_data['last_reset_date'] = datetime.now().strftime("%Y-%m-%d")
            _save_data(USER_STATS_FILE, stats)
            
    # Keyinchalik foydalanish uchun qulayroq kalit nomini beramiz
    user_data['current_ad_cycle_count'] = user_data.get('ad_cycle_count', 0)
            
    return user_data

def update_user_stats(user_id, chat_id, invited_count_change=0, ad_used=False, reset_invited=False):
    """Foydalanuvchi statistikasini yangilaydi (takliflar soni, reklama yuborish soni)."""
    stats = _load_data(USER_STATS_FILE)
    user_id_str = str(user_id)
    chat_id_str = str(chat_id)
    
    if user_id_str not in stats or chat_id_str not in stats[user_id_str]:
        # Agar statistika yo'q bo'lsa, avval standartini yaratamiz
        get_user_stats(user_id, chat_id, get_config(chat_id))
        stats = _load_data(USER_STATS_FILE)

    user_data = stats[user_id_str][chat_id_str]
    
    if invited_count_change != 0:
        user_data['invited_members_count'] = user_data.get('invited_members_count', 0) + invited_count_change

    if ad_used:
        user_data['ad_cycle_count'] = user_data.get('ad_cycle_count', 0) + 1
        # Reklama yuborilganini belgilaymiz, tiklash sanasini yangilaymiz (agar yangilanish kerak bo'lsa)
        if user_data.get('last_reset_date') is None:
             user_data['last_reset_date'] = datetime.now().strftime("%Y-%m-%d")
    
    if reset_invited:
        user_data['invited_members_count'] = 0

    _save_data(USER_STATS_FILE, stats)


# --- Admin ma'lumotlari ---

def hash_password(password):
    """Parolni himoyalash uchun SHA256 bilan hashlaydi."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_admin_data(user_id):
    """Admin ma'lumotlarini yuklaydi."""
    admin_data = _load_data(ADMIN_CREDS_FILE)
    user_id_str = str(user_id)
    
    if user_id_str not in admin_data:
         # Standart boshlang'ich adminni yaratish (keyinchalik o'zgartiriladi)
         admin_data[user_id_str] = {
             'username': 'admin',
             'password_hash': hash_password('admin')
         }
         _save_data(ADMIN_CREDS_FILE, admin_data)

    return admin_data[user_id_str]

def check_admin_credentials(login, password):
    """Login va parolni tekshiradi."""
    admin_data = _load_data(ADMIN_CREDS_FILE)
    target_hash = hash_password(password)
    
    # Ma'lumotlar bazasidagi har bir adminni tekshirish
    for user_id_str, data in admin_data.items():
        if data.get('username') == login and data.get('password_hash') == target_hash:
            return data
            
    return None

def set_admin_data(user_id, username=None, password_hash=None):
    """Admin login yoki parolini yangilaydi."""
    admin_data = _load_data(ADMIN_CREDS_FILE)
    user_id_str = str(user_id)
    
    if user_id_str not in admin_data:
        admin_data[user_id_str] = {}
        
    if username is not None:
        admin_data[user_id_str]['username'] = username
        
    if password_hash is not None:
        admin_data[user_id_str]['password_hash'] = hash_password(password_hash)

    _save_data(ADMIN_CREDS_FILE, admin_data)


# --- Majburiy obuna kanallari ---

def get_required_channels():
    """Majburiy obuna kanallari ro'yxatini yuklaydi."""
    return _load_data(CHANNELS_FILE, default_value=[])

def add_channel(username):
    """Kanalni ro'yxatga qo'shadi."""
    channels = get_required_channels()
    # Takrorlanmasligini tekshirish
    if not any(c['channel_username'] == username for c in channels):
        channels.append({'channel_username': username})
        _save_data(CHANNELS_FILE, channels)
        return True
    return False

def delete_channel(username):
    """Kanalni ro'yxatdan o'chiradi."""
    channels = get_required_channels()
    original_len = len(channels)
    
    channels = [c for c in channels if c['channel_username'] != username]
    
    if len(channels) < original_len:
        _save_data(CHANNELS_FILE, channels)
        return True
    return False
