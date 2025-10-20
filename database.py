import os
import json
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# --- Supabase sozlamalari ---
SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")

supabase: Client = None


# --- Asosiy ishga tushirish funksiyasi ---
async def init_db():
    """Supabase client'ni yaratadi va adminni tekshiradi/kiritadi."""
    global supabase

    if not all([SUPABASE_URL, SUPABASE_KEY]):
        print("⚠️ SUPABASE_URL yoki SUPABASE_KEY topilmadi (.env ni tekshiring).")
        return False

    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase client ulandi.")
        await create_tables_and_init_admin()
        return True
    except Exception as e:
        print(f"❌ Supabase ulanish xatosi: {e}")
        return False


# --- Foydali yordamchi ---
async def run_query(func):
    """Supabase so‘rovlarini async muhitda xavfsiz bajaradi."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func)


# --- Admin bilan bog‘liq funksiyalar ---
async def create_tables_and_init_admin():
    """Boshlang‘ich adminni tekshiradi yoki yaratadi."""
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD_HASH")

    if not username or not password:
        print("⚠️ ADMIN_USERNAME yoki ADMIN_PASSWORD_HASH topilmadi.")
        return

    try:
        response = await run_query(lambda: supabase.table('admins')
                                   .select('admin_id')
                                   .eq('username', username)
                                   .execute())

        if not getattr(response, "data", None):
            await run_query(lambda: supabase.table('admins').insert({
                'username': username,
                'password_hash': password,
                'is_active': True
            }).execute())
            print("✅ Dastlabki admin yaratildi.")
        else:
            print("✅ Admin mavjud.")
    except Exception as e:
        print(f"❌ Admin yaratishda xato: {e}")


async def check_admin_credentials(username, password_hash):
    try:
        response = await run_query(lambda: supabase.table('admins')
                                   .select('*')
                                   .eq('username', username)
                                   .eq('password_hash', password_hash)
                                   .execute())
        data = getattr(response, "data", None)
        return data[0] if data else None
    except Exception as e:
        print(f"⚠️ Admin credential tekshirishda xato: {e}")
        return None


async def link_admin_telegram_id(username=None, telegram_user_id=None):
    try:
        if username:
            await run_query(lambda: supabase.table('admins')
                           .update({'telegram_user_id': telegram_user_id})
                           .eq('username', username)
                           .execute())
        elif telegram_user_id:
            await run_query(lambda: supabase.table('admins')
                           .update({'telegram_user_id': None})
                           .eq('telegram_user_id', telegram_user_id)
                           .execute())
    except Exception as e:
        print(f"⚠️ Telegram ID ulashda xato: {e}")


async def get_admin_by_telegram_id(telegram_user_id):
    try:
        response = await run_query(lambda: supabase.table('admins')
                                   .select('*')
                                   .eq('telegram_user_id', telegram_user_id)
                                   .execute())
        data = getattr(response, "data", None)
        return data[0] if data else None
    except Exception as e:
        print(f"⚠️ Adminni topishda xato: {e}")
        return None


async def update_admin_credentials(admin_id, login=None, password_hash=None):
    updates = {}
    if login:
        updates['username'] = login
    if password_hash:
        updates['password_hash'] = password_hash

    if not updates:
        return

    try:
        await run_query(lambda: supabase.table('admins')
                       .update(updates)
                       .eq('admin_id', admin_id)
                       .execute())
    except Exception as e:
        print(f"⚠️ Admin credential yangilashda xato: {e}")


# --- Guruh konfiguratsiyasi ---
async def get_all_chat_configs():
    try:
        response = await run_query(lambda: supabase.table('chat_config')
                                   .select('chat_id')
                                   .execute())
        return getattr(response, "data", [])
    except Exception as e:
        print(f"⚠️ Chat konfiguratsiyalarini olishda xato: {e}")
        return []


async def get_config(chat_id):
    try:
        response = await run_query(lambda: supabase.table('chat_config')
                                   .select('*')
                                   .eq('chat_id', chat_id)
                                   .execute())

        if getattr(response, "data", None):
            config = response.data[0]
            if isinstance(config.get('invite_levels'), str):
                config['invite_levels'] = json.loads(config['invite_levels'])
            return config

        default_config = {
            'chat_id': chat_id,
            'free_ad_count': 1,
            'reset_interval_days': 30,
            'invite_levels': json.dumps({"1": 2, "2": 5, "max": 10})
        }

        await run_query(lambda: supabase.table('chat_config').insert(default_config).execute())
        default_config['invite_levels'] = json.loads(default_config['invite_levels'])
        return default_config

    except Exception as e:
        print(f"⚠️ Chat konfiguratsiyasini olishda xato: {e}")
        return None


async def update_chat_config(chat_id, key, value):
    updates = {key: json.dumps(value) if isinstance(value, dict) else value}
    try:
        await run_query(lambda: supabase.table('chat_config')
                       .update(updates)
                       .eq('chat_id', chat_id)
                       .execute())
    except Exception as e:
        print(f"⚠️ Chat konfiguratsiyasini yangilashda xato: {e}")


# --- Foydalanuvchi statistikasi ---
async def get_user_stats(user_id, chat_id, config):
    try:
        response = await run_query(lambda: supabase.table('user_stats')
                                   .select('*')
                                   .eq('user_id', user_id)
                                   .eq('chat_id', chat_id)
                                   .execute())
        data = getattr(response, "data", None)

        if not data:
            new_stats = {
                'user_id': user_id,
                'chat_id': chat_id,
                'last_ad_timestamp': datetime.now().isoformat(),
                'current_ad_cycle_count': 0,
                'invited_members_count': 0
            }
            await run_query(lambda: supabase.table('user_stats').insert(new_stats).execute())
            return new_stats

        stats = data[0]
        last_ad_ts = stats.get('last_ad_timestamp')
        if last_ad_ts:
            last_ad_dt = datetime.fromisoformat(last_ad_ts.replace('Z', '+00:00'))
        else:
            last_ad_dt = datetime.now()

        reset_date = last_ad_dt + timedelta(days=config['reset_interval_days'])
        if datetime.now() > reset_date:
            reset_data = {
                'current_ad_cycle_count': 0,
                'invited_members_count': 0,
                'last_ad_timestamp': datetime.now().isoformat()
            }
            await run_query(lambda: supabase.table('user_stats')
                           .update(reset_data)
                           .eq('user_id', user_id)
                           .eq('chat_id', chat_id)
                           .execute())
            stats.update(reset_data)

        return stats

    except Exception as e:
        print(f"⚠️ User stats olishda xato: {e}")
        return None


async def update_user_stats(user_id, chat_id, ad_used=False, invited_count_change=0, reset_invited=False):
    updates = {}

    try:
        if ad_used:
            response = await run_query(lambda: supabase.table('user_stats')
                                       .select('current_ad_cycle_count')
                                       .eq('user_id', user_id)
                                       .eq('chat_id', chat_id)
                                       .single()
                                       .execute())
            current = getattr(response, "data", {}).get('current_ad_cycle_count', 0)
            updates['current_ad_cycle_count'] = current + 1
            updates['last_ad_timestamp'] = datetime.now().isoformat()

        if invited_count_change:
            response = await run_query(lambda: supabase.table('user_stats')
                                       .select('invited_members_count')
                                       .eq('user_id', user_id)
                                       .eq('chat_id', chat_id)
                                       .single()
                                       .execute())
            current_inv = getattr(response, "data", {}).get('invited_members_count', 0)
            updates['invited_members_count'] = current_inv + invited_count_change

        if reset_invited:
            updates['invited_members_count'] = 0

        if updates:
            await run_query(lambda: supabase.table('user_stats')
                           .update(updates)
                           .eq('user_id', user_id)
                           .eq('chat_id', chat_id)
                           .execute())
    except Exception as e:
        print(f"⚠️ User stats yangilashda xato: {e}")


# --- Kanallar bilan ishlash ---
async def get_required_channels():
    try:
        response = await run_query(lambda: supabase.table('required_channels').select('*').execute())
        return getattr(response, "data", [])
    except Exception as e:
        print(f"⚠️ Kanallarni olishda xato: {e}")
        return []


async def get_all_channels_for_settings():
    try:
        response = await run_query(lambda: supabase.table('required_channels')
                                   .select('channel_username')
                                   .execute())
        return getattr(response, "data", [])
    except Exception as e:
        print(f"⚠️ Kanallar sozlamalarini olishda xato: {e}")
        return []


async def add_channel(username):
    try:
        response = await run_query(lambda: supabase.table('required_channels')
                                   .insert({'channel_username': username, 'is_active': True})
                                   .execute())
        return getattr(response, "data", None)
    except Exception as e:
        print(f"⚠️ Kanal qo‘shishda xato: {e}")
        return None


async def delete_channel(channel_id):
    try:
        await run_query(lambda: supabase.table('required_channels')
                       .delete()
                       .eq('channel_id', channel_id)
                       .execute())
    except Exception as e:
        print(f"⚠️ Kanalni o‘chirishda xato: {e}")
