import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatMemberStatus, ContentType
from aiogram.fsm.context import FSMContext 
from aiogram.fsm.state import State, StatesGroup 
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter 
from aiogram.utils.keyboard import InlineKeyboardBuilder 
from aiogram.exceptions import TelegramBadRequest 

# Web server va HTTP so'rovlar uchun kutubxona
from aiohttp import web, ClientSession 

# --- storage faylini import qilamiz ---
from storage import (
    get_config, update_config, get_user_stats, update_user_stats, 
    check_admin_credentials, get_admin_data, set_admin_data,
    get_required_channels, add_channel, delete_channel, get_all_chat_configs,
    add_new_group
)

load_dotenv()

# --- BOT INITS ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID") 
try:
    ADMIN_TELEGRAM_ID = int(ADMIN_TELEGRAM_ID)
except:
    ADMIN_TELEGRAM_ID = None 
    print("⚠️ ADMIN_TELEGRAM_ID .env da topilmadi yoki raqam emas!")

bot = None 
dp = None

# --- RENDER PINGER MANTIQI ---

async def handle_ping(request):
    """Render'dan kelgan soxta so'rovlarga javob beradi (botni uyg'otib turish uchun)."""
    return web.Response(text="Bot is awake and polling!")

async def periodic_pinger(url, interval_seconds=10): # HAR 10 SEKUNDGA O'ZGARTIRILDI
    """Berilgan URL manzilga har 10 sekundda so'rov yuboradi (o'zini-o'zi uyg'otish)."""
    async with ClientSession() as session:
        while True:
            await asyncio.sleep(interval_seconds) 
            try:
                async with session.get(url) as response:
                    print(f"🤖 Ping yuborildi. Status: {response.status}") 
            except Exception as e:
                print(f"❌ Ping yuborishda xato: {e}")

# --- BOT YORDAMCHI FUNKSIYALARI ---

async def delete_message_later(chat_id, message_id, delay=330):
    """Xabarni belgilangan vaqt (sekund) o'tgach o'chiradi (5.5 daqiqa = 330 sekund)."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

async def notify_admin_about_error(chat_id, error_message, action_name):
    """Xatolik haqida adminni ogohlantiradi."""
    global ADMIN_TELEGRAM_ID, bot
    if ADMIN_TELEGRAM_ID and bot:
        message = (
            f"❌ **KRITIK GURUH XATOSI**\n"
            f"Guruh ID: <code>{chat_id}</code>\n"
            f"Amal: **{action_name}**\n"
            f"Xato: <code>{error_message}</code>\n\n"
            f"⚠️ **Yechim:** Botga guruhda Administrator ruxsatlari berilganligini tekshiring!"
        )
        try:
            await bot.send_message(ADMIN_TELEGRAM_ID, message, parse_mode="HTML")
        except Exception as e:
            print(f"❌ Adminni ogohlantirishda xato: {e}")

# --- FSM HOLATLARI ---
class AdminStates(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()
    in_admin_panel = State()
    
    waiting_for_free_ad_count = State()
    waiting_for_reset_interval = State()
    waiting_for_invite_level_name = State() 
    waiting_for_invite_level_value = State()
    
    waiting_for_new_chat_id = State() 
    
    waiting_for_new_channel_username = State() 
    
    waiting_for_new_admin_login = State()
    waiting_for_new_admin_password = State()


# --- FILTRLAR VA FUNKSIYALAR ---

async def get_required_members(config, ad_cycle_count):
    """Foydalanuvchi reklama tashlash uchun qancha odam taklif qilishi kerakligini hisoblaydi."""
    
    if ad_cycle_count < config.get('free_ad_count', 1): 
        return 0 
    
    current_level = ad_cycle_count - config.get('free_ad_count', 1) + 1 
    invite_levels = config.get('invite_levels', {})
    
    return invite_levels.get(str(current_level), invite_levels.get('max', 10))


# --- ADMIN PANEL INTERFEYSI (Tugmalar) ---

def get_admin_main_menu():
    """Asosiy admin menusi tugmalarini yaratadi."""
    builder = InlineKeyboardBuilder() 
    
    builder.button(text="📺 Kanallar", callback_data="admin_channels")
    builder.button(text="📊 Limit", callback_data="admin_settings_groups")
    builder.button(text="🔑 Login/Parol", callback_data="admin_credentials")
    builder.button(text="🚪 Chiqish (Logout)", callback_data="admin_logout")
    
    builder.adjust(1) 
    
    return builder.as_markup() 

async def get_group_list_keyboard():
    """Limit sozlamalari uchun Guruhlar va Kanallar ro'yxatini yuklaydi."""
    builder = InlineKeyboardBuilder()
    
    chat_ids = get_all_chat_configs()
    if chat_ids:
        for chat_id_str in chat_ids:
            chat_id = int(chat_id_str)
            button_text = f"⚙️ Guruh ID: {chat_id}"
            builder.button(text=button_text, callback_data=f"select_chat:{chat_id}")
            
    if not chat_ids:
         builder.button(text="❌ Guruhlar topilmadi.", callback_data="ignore")

    builder.button(text="➕ Guruh qo'shish", callback_data="add_new_group_for_limit") 
    builder.button(text="⬅️ Bosh Menyu", callback_data="admin_main_menu")
    
    builder.adjust(1) 
    
    return builder.as_markup()

def get_chat_settings_keyboard(chat_id, config):
    """Guruhning joriy sozlamalarini ko'rsatuvchi tugmalar menyusi."""
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=f"Bepul reklama soni: {config.get('free_ad_count', 1)} 🔄", 
        callback_data=f"set_ad_count:{chat_id}"
    )
    builder.button(
        text=f"Limit tiklash: {config.get('reset_interval_days', 30)} kun 📅", 
        callback_data=f"set_reset_interval:{chat_id}"
    )
    builder.button(
        text="Taklif Level'larini sozlash 🎯", 
        callback_data=f"set_invite_levels:{chat_id}"
    )
    builder.button(text="⬅️ Guruhlar ro'yxatiga", callback_data="admin_settings_groups")
    
    builder.adjust(1) 
    return builder.as_markup()

def get_invite_levels_keyboard(chat_id, invite_levels: dict):
    """Taklif level'larini ko'rsatish va ularni o'zgartirish uchun tugmalar menyusi."""
    builder = InlineKeyboardBuilder()
    
    sorted_keys = [k for k in invite_levels if k != 'max']
    try:
        sorted_keys.sort(key=int)
    except ValueError:
        pass 
        
    if 'max' in invite_levels:
        sorted_keys.append('max')

    for level_key in sorted_keys:
        value = invite_levels[level_key]
        text = f"Level {level_key}: {value} ta odam ✏️"
        
        builder.button(text=text, callback_data=f"edit_level:{chat_id}:{level_key}")
        
        if level_key != 'max':
             builder.button(text="❌", callback_data=f"delete_level:{chat_id}:{level_key}")
        else:
             builder.button(text="  ", callback_data="ignore") 

    builder.button(text="➕ Yangi Level qo'shish", callback_data=f"add_new_level:{chat_id}")
    builder.button(text="⬅️ Guruh sozlamalariga", callback_data=f"select_chat:{chat_id}")
    
    builder.adjust(2, repeat=True) 
    
    return builder.as_markup()

def get_admin_credentials_keyboard(admin_data):
    """Login/parol sozlamalari menyusi."""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="✏️ Loginni o'zgartirish", callback_data="change_login")
    builder.button(text="🔒 Parolni o'zgartirish", callback_data="change_password")
    builder.button(text="⬅️ Bosh Menyu", callback_data="admin_main_menu")
    
    builder.adjust(1)
    return builder.as_markup()

async def get_channels_keyboard(channels):
    """Kanallar ro'yxati va Qo'shish/O'chirish tugmalari."""
    builder = InlineKeyboardBuilder()
    
    if channels:
        for channel in channels:
            username = channel['channel_username']
            builder.button(
                text=f"❌ @{username}", 
                callback_data=f"delete_channel:{username}" 
            )
    
    builder.button(text="➕ Kanal qo'shish", callback_data="add_new_channel")
    builder.button(text="⬅️ Bosh Menyu", callback_data="admin_main_menu")
    
    builder.adjust(1)
    return builder.as_markup()


# --- MESSAGE HANDLERS (Login/Parol va FSM) ---

async def handle_start(message: types.Message, state: FSMContext):
    """Botni /start buyrug'i bilan ishga tushirish (admin tekshiruvi)."""
    if message.from_user.id == ADMIN_TELEGRAM_ID:
        await message.answer("✅ **Xush kelibsiz!** Admin panelga kirdingiz.", reply_markup=get_admin_main_menu())
        await state.set_state(AdminStates.in_admin_panel)
        return
        
    admin = get_admin_data(message.from_user.id)
    if admin.get('username') and admin.get('password_hash'):
        await message.answer("✅ **Xush kelibsiz!** Admin panelga kirdingiz.", reply_markup=get_admin_main_menu())
        await state.set_state(AdminStates.in_admin_panel)
        return

    await message.answer("🔑 **Admin Panelga kirish**\nIltimos, o'z loginingizni kiriting:")
    await state.set_state(AdminStates.waiting_for_login)

async def process_login(message: types.Message, state: FSMContext):
    await state.update_data(temp_login=message.text)
    await message.answer("🔒 Parolingizni kiriting:")
    await state.set_state(AdminStates.waiting_for_password)

async def process_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    login = data.get('temp_login')
    password = message.text
    user_id = message.from_user.id
    
    admin_data = check_admin_credentials(login, password)
    
    if admin_data:
        set_admin_data(user_id, login, password)
        await message.answer("✅ **Xush kelibsiz!** Admin panelga kirdingiz.", reply_markup=get_admin_main_menu())
        await state.set_state(AdminStates.in_admin_panel)
    else:
        await message.answer("❌ Login yoki parol noto'g'ri. Qayta urinib ko'ring:")
        await state.set_state(AdminStates.waiting_for_login)

async def process_new_free_ad_count(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format. Iltimos, faqat **to'liq son** kiriting.")
        return

    new_count = int(message.text)
    data = await state.get_data()
    chat_id = data.get('current_chat_id')
    config = get_config(chat_id)

    update_config(chat_id, 'free_ad_count', new_count) 
    config['free_ad_count'] = new_count
    await state.update_data(current_config=config)
    
    await state.set_state(AdminStates.in_admin_panel)
    
    await message.answer(
        f"✅ **Sozlama saqlandi!** Reklama soni endi **{new_count}** ga o'rnatildi.",
        reply_markup=get_chat_settings_keyboard(chat_id, config)
    )

async def process_new_reset_interval(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format. Iltimos, faqat **to'liq kun sonini** kiriting.")
        return

    new_days = int(message.text)
    if new_days < 1:
        await message.answer("❌ Kunlar soni kamida 1 bo'lishi kerak.")
        return
        
    data = await state.get_data()
    chat_id = data.get('current_chat_id')
    config = get_config(chat_id)

    update_config(chat_id, 'reset_interval_days', new_days)
    config['reset_interval_days'] = new_days
    await state.update_data(current_config=config)

    await state.set_state(AdminStates.in_admin_panel)
    
    await message.answer(
        f"✅ **Sozlama saqlandi!** Limit endi har **{new_days}** kunda tiklanadi.",
        reply_markup=get_chat_settings_keyboard(chat_id, config)
    )

async def process_invite_level_name(message: types.Message, state: FSMContext):
    level_name = message.text.strip().lower()
    
    if not (level_name.isdigit() and int(level_name) > 0) and level_name != 'max':
        await message.answer("❌ Noto'g'ri level nomi. Iltimos, faqat musbat son (1, 2, 3...) yoki **max** so'zini kiriting.")
        return
    
    await state.update_data(temp_level_name=level_name)
    await message.answer(f"🔢 Level **{level_name}** uchun nechta odam taklif qilish kerak? (Son kiriting):")
    await state.set_state(AdminStates.waiting_for_invite_level_value)

async def process_invite_level_value(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format. Iltimos, faqat **to'liq son** kiriting.")
        return
        
    level_value = int(message.text)
    data = await state.get_data()
    chat_id = data.get('current_chat_id')
    level_name = data.get('temp_level_name')
    config = get_config(chat_id)
    
    invite_levels = config.get('invite_levels', {})
    invite_levels[level_name] = level_value 
    
    update_config(chat_id, 'invite_levels', invite_levels)
    config['invite_levels'] = invite_levels 
    await state.update_data(current_config=config)
    
    await state.set_state(AdminStates.in_admin_panel)
    
    await message.answer(
        f"✅ **Level {level_name}** uchun takliflar soni **{level_value}** ga o'rnatildi.",
        reply_markup=get_invite_levels_keyboard(chat_id, invite_levels)
    )

async def process_new_chat_id_for_limit(message: types.Message, state: FSMContext):
    global bot
    chat_input = message.text.strip()
    
    match = re.search(r'(?:t\.me/|@)(\w+)$', chat_input)
    
    if match:
        chat_identifier = f"@{match.group(1)}" 
    elif chat_input.startswith('-100') and chat_input[1:].isdigit():
        chat_identifier = chat_input 
    else:
        await message.answer("❌ Noto'g'ri format. Iltimos, guruhning **@username**'ini, **to'liq linkini** yoki **ID raqamini** kiriting.")
        return
    
    try:
        chat_info = await bot.get_chat(chat_identifier)
        new_chat_id = chat_info.id
        chat_name = chat_info.title
        
        if new_chat_id > 0:
             await message.answer("❌ Bu username/link guruhga emas. Guruh yoki Superguruh linkini kiriting.")
             return
             
        add_new_group(new_chat_id) 
        config = get_config(new_chat_id)
        
        try:
            member_status = await bot.get_chat_member(new_chat_id, bot.id)
            if member_status.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                 status_text = "✅ Bot guruhda **admin** sifatida mavjud."
            else:
                 status_text = "⚠️ Bot guruhda admin emas. Iltimos, botni guruhga **admin sifatida** qo'shing."
        except Exception:
             status_text = "⚠️ Bot bu guruhda topilmadi. Iltimos, botni guruhga **admin sifatida** qo'shing."
             
        await state.set_state(AdminStates.in_admin_panel)
        
        await state.update_data(current_chat_id=new_chat_id, current_config=config)
        
        await message.answer(
            f"✅ Guruh **«{chat_name}»** limit sozlamalariga qo'shildi.\nID: <code>{new_chat_id}</code>\n{status_text}",
            reply_markup=get_chat_settings_keyboard(new_chat_id, config),
            parse_mode="HTML"
        )
        
    except Exception as e:
        await message.answer(f"❌ Guruh topilmadi yoki bot u yerdan ma'lumot ololmaydi. To'liq username/link va bot admin ekanligini tekshiring.\n\nXato: {e}")

async def process_new_channel_username(message: types.Message, state: FSMContext):
    username = message.text.lstrip('@')
    
    if not username or len(username) < 5:
        await message.answer("❌ Noto'g'ri kanal user name. Iltimos, @siz yoki @bilan kiriting.")
        return
        
    add_channel(username) 
    channels = get_required_channels()
    
    await state.set_state(AdminStates.in_admin_panel)
    await message.answer(
        f"✅ Kanal **@{username}** muvaffaqiyatli qo'shildi.",
        reply_markup=await get_channels_keyboard(channels)
    )

async def process_new_admin_login(message: types.Message, state: FSMContext):
    new_login = message.text.strip()
    admin_id = message.from_user.id 
    
    admin_data = get_admin_data(admin_id) 
    
    set_admin_data(admin_id, username=new_login, password_hash=admin_data.get('password_hash'))
    
    await state.set_state(AdminStates.in_admin_panel)
    admin_data = get_admin_data(message.from_user.id)
    
    await message.answer(
        f"✅ Login muvaffaqiyatli **{new_login}** ga o'zgartirildi.",
        reply_markup=get_admin_credentials_keyboard(admin_data)
    )

async def process_new_admin_password(message: types.Message, state: FSMContext):
    new_password = message.text.strip()
    admin_id = message.from_user.id
    
    admin_data = get_admin_data(admin_id)
    
    set_admin_data(admin_id, username=admin_data.get('username'), password_hash=new_password)
    
    await state.set_state(AdminStates.in_admin_panel)
    admin_data = get_admin_data(message.from_user.id) 
    
    await message.answer(
        f"✅ Parol muvaffaqiyatli o'zgartirildi.",
        reply_markup=get_admin_credentials_keyboard(admin_data)
    )

# --- CALLBACK QUERY HANDLER ---

async def handle_admin_callbacks(call: types.CallbackQuery, state: FSMContext):
    data = call.data
    admin = get_admin_data(call.from_user.id) or {} 

    if data == "admin_main_menu":
        await state.set_state(AdminStates.in_admin_panel)
        await call.message.edit_text("✅ **Admin Panel**", reply_markup=get_admin_main_menu())
        await call.answer()
    elif data == "admin_logout":
        await state.clear()
        await call.message.edit_text("🚪 Tizimdan chiqdingiz. Qayta kirish uchun /start ni bosing.")
        await call.answer("Chiqish amalga oshirildi.", show_alert=True)
    elif data == "admin_settings_groups":
        await call.message.edit_text(
            "📊 **Limit Sozlamalari**\nIltimos, sozlamoqchi bo'lgan guruhni tanlang:",
            reply_markup=await get_group_list_keyboard(), 
            parse_mode="HTML"
        )
        await call.answer()
    elif data == "add_new_group_for_limit":
        await call.message.edit_text("➕ **Yangi Guruh Qo'shish**\n\n"
                                     "Iltimos, guruhning **@username**'ini, **linkini** (t.me/...) yoki **ID raqamini** (`-100...`) kiriting.")
        await state.set_state(AdminStates.waiting_for_new_chat_id)
        await call.answer()
    elif data.startswith("select_chat:"):
        chat_id = int(data.split(":")[1])
        config = get_config(chat_id) 
        
        await state.update_data(current_chat_id=chat_id, current_config=config)
        
        await call.message.edit_text(
            f"🛠 **Guruh ID: {chat_id} Limit Sozlamalari**",
            reply_markup=get_chat_settings_keyboard(chat_id, config),
            parse_mode="HTML"
        )
        await call.answer(f"Guruh {chat_id} tanlandi.")
    elif data.startswith("set_ad_count:") or data.startswith("set_reset_interval:"):
        await state.update_data(current_chat_id=int(data.split(":")[1]))
        if data.startswith("set_ad_count:"):
            await call.message.edit_text("🔢 **Qancha bepul reklama ruxsat etilsin?** (Son kiriting)", parse_mode="HTML")
            await state.set_state(AdminStates.waiting_for_free_ad_count)
        elif data.startswith("set_reset_interval:"):
            await call.message.edit_text("⏳ **Limit qancha kunda tiklansin?** (Kun sonini kiriting)", parse_mode="HTML")
            await state.set_state(AdminStates.waiting_for_reset_interval)
        
        # TelegramBadRequest xatosini oldini olish uchun faqat text tahrirlanayotganini tekshiramiz:
        await call.answer()
        
    elif data.startswith("set_invite_levels:"):
        chat_id = int(data.split(":")[1])
        config = get_config(chat_id)
        
        await state.update_data(current_chat_id=chat_id, current_config=config)
        
        await call.message.edit_text(
            f"📈 **Guruh ID: {chat_id} Taklif Level'lari**\n\n"
            f"Bepul reklama soni tugagandan keyin, har bir keyingi xabar uchun qancha odam taklif qilinishi kerakligini belgilang. (`max` - barcha level'lar tugagandan keyingi qiymat).",
            reply_markup=get_invite_levels_keyboard(chat_id, config['invite_levels']),
            parse_mode="HTML"
        )
        await call.answer()
    elif data.startswith("add_new_level:"):
        chat_id = int(data.split(":")[1])
        await state.update_data(current_chat_id=chat_id)
        await call.message.edit_text("✏️ **Yangi Level nomi**ni kiriting (Masalan: `1`, `2`, yoki `max`):")
        await state.set_state(AdminStates.waiting_for_invite_level_name)
        await call.answer()
    elif data.startswith("edit_level:"):
        _, chat_id_str, level_name = data.split(":")
        chat_id = int(chat_id_str)
        config = get_config(chat_id)
        await state.update_data(current_chat_id=chat_id, current_config=config, temp_level_name=level_name)
        
        await call.message.edit_text(
            f"✏️ Level **{level_name}** uchun **yangi taklif sonini** kiriting. "
            f"(Hozirgi qiymat: {config['invite_levels'].get(level_name)}):"
        )
        await state.set_state(AdminStates.waiting_for_invite_level_value)
        await call.answer()
    elif data.startswith("delete_level:"):
        _, chat_id_str, level_name = data.split(":")
        chat_id = int(chat_id_str)
        config = get_config(chat_id)
        
        if level_name in config['invite_levels']:
            del config['invite_levels'][level_name]
            update_config(chat_id, 'invite_levels', config['invite_levels'])
            
            await call.message.edit_text(
                f"✅ Level **{level_name}** muvaffaqiyatli o'chirildi.",
                reply_markup=get_invite_levels_keyboard(chat_id, config['invite_levels'])
            )
            await call.answer(f"Level {level_name} o'chirildi.")
        else:
            await call.answer("Xato: Level topilmadi.", show_alert=True)
    elif data == "admin_channels":
        channels = get_required_channels()
        text = "📺 **Majburiy a'zolik Kanallari**\n"
        if not channels:
            text += "Hozircha hech qanday kanal qo'shilmagan."
            
        await call.message.edit_text(text, reply_markup=await get_channels_keyboard(channels), parse_mode="HTML")
        await call.answer()
    elif data == "add_new_channel":
        await call.message.edit_text("➕ **Kanal qo'shish**\nIltimos, kanalning **@username**'ni kiriting:")
        await state.set_state(AdminStates.waiting_for_new_channel_username)
        await call.answer()
    elif data.startswith("delete_channel:"):
        channel_username = data.split(":")[1]
        
        if delete_channel(channel_username):
            await call.answer(f"@{channel_username} kanali o'chirildi.", show_alert=True)
        else:
            await call.answer("Kanal topilmadi.", show_alert=True)
            
        channels = get_required_channels()
        await call.message.edit_text("✅ Kanallar ro'yxati yangilandi.", reply_markup=await get_channels_keyboard(channels))

    elif data == "admin_credentials":
        text = f"🔑 **Login/Parol Sozlamalari**\n\n" \
               f"👤 Hozirgi login: <code>{admin.get('username', 'Noma\'lum')}</code>\n" \
               f"🔒 Parol: ********* (Ko'rsatilmaydi)"
               
        await call.message.edit_text(text, reply_markup=get_admin_credentials_keyboard(admin), parse_mode="HTML")
        await call.answer()
    elif data == "change_login":
        await state.update_data(admin_id=call.from_user.id)
        await call.message.edit_text("✏️ **Yangi loginni kiriting:**")
        await state.set_state(AdminStates.waiting_for_new_admin_login)
        await call.answer()
    elif data == "change_password":
        await state.update_data(admin_id=call.from_user.id)
        await call.message.edit_text("🔒 **Yangi parolni kiriting:**")
        await state.set_state(AdminStates.waiting_for_new_admin_password)
        await call.answer()
    else:
        # call.answer() ni har qanday Callback oxirida chaqirish shart
        await call.answer("Boshqa buyruq topilmadi.", show_alert=False)


# --- GURUH HANDLERS ---

async def handle_new_member(message: types.Message):
    """Guruhga qo'shilgan yangi a'zolarni qutlaydi, takliflarni hisoblaydi va avtomatik limitni yechadi."""
    global bot
    
    chat_id = message.chat.id
    
    if message.new_chat_members:
        inviter_user_id = message.from_user.id
        inviter_full_name = message.from_user.full_name
        
        bot_id = (await bot.get_me()).id
        
        member_links = []
        real_new_members_count = 0 
        for member in message.new_chat_members:
            if member.id == bot_id:
                continue
            real_new_members_count += 1
            member_links.append(f"[{member.full_name}](tg://user?id={member.id})")

        if not member_links:
            try:
                await message.delete() 
            except Exception:
                pass
            return 

        if len(member_links) == 1:
            welcome_text = f"👋 **Salom, {member_links[0]}!** Guruhimizga xush kelibsiz."
        else:
            welcome_text = f"👋 **Salom!** Guruhimizga xush kelibsiz: {', '.join(member_links)}."
        
        welcome_text += "\n\nBu guruhda xabar yuborish uchun siz ham do'stlaringizni taklif qilishingiz kerak!" 
        
        is_limit_released = False 
        
        if inviter_user_id != bot_id: 
            
            update_user_stats(
                user_id=inviter_user_id, 
                chat_id=chat_id, 
                invited_count_change=real_new_members_count
            )
            
            config = get_config(chat_id) 
            updated_stats = get_user_stats(inviter_user_id, chat_id, config)
            
            required_members = await get_required_members(config, updated_stats['current_ad_cycle_count'])
            current_invited = updated_stats.get('invited_members_count', 0)
            
            if required_members > 0 and current_invited >= required_members:
                
                remaining_members = current_invited - required_members
                
                update_user_stats(inviter_user_id, chat_id, ad_used=True, reset_invited=True)
                if remaining_members > 0:
                    update_user_stats(inviter_user_id, chat_id, invited_count_change=remaining_members)

                is_limit_released = True
                
                inviter_link = f"[{inviter_full_name}](tg://user?id={inviter_user_id})"
                success_text = (
                    f"🎉 **{inviter_link}**, siz **{current_invited}** ta odam qo'shdingiz! "
                    f"Talab qilingan miqdor **({required_members})** bajarildi.\n\n"
                    f"Sizning xabar yuborish cheklovingiz olib tashlandi. Xabar yuborishingiz mumkin!"
                )
                try:
                    await bot.send_message(chat_id, success_text, parse_mode="Markdown")
                except Exception as e:
                     print(f"❌ SUCCESS XABAR YUBORISHDA XATO: {e}")

            if not is_limit_released and inviter_user_id != bot_id:
                 inviter_link = f"[{inviter_full_name}](tg://user?id={inviter_user_id})"
                 welcome_text += f"\n\n**{inviter_link}**, siz **{real_new_members_count}** ta odam qo'shganingiz uchun rahmat! 😊"


        try:
            sent_message = await message.answer(welcome_text, parse_mode="Markdown")
            asyncio.create_task(delete_message_later(sent_message.chat.id, sent_message.message_id, delay=330))
        except Exception as e:
             print(f"❌ SALOMLASHISH XABAR YUBORISHDA XATO: {e}")
             
        
        try:
            await message.delete() 
        except Exception as e:
            await notify_admin_about_error(chat_id, str(e), "Salomlashish (sistem xabarini o'chirish)")


async def handle_group_messages(message: types.Message):
    """Guruhdagi oddiy xabarlarni limit bo'yicha cheklaydi."""
    global bot
    
    if message.chat.type not in ('group', 'supergroup') or message.from_user.id == (await bot.get_me()).id: 
        return 

    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in [ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR]: 
            return 
    except Exception:
        pass

    config = get_config(chat_id) 
    user_stats = get_user_stats(user_id, chat_id, config)
    
    required_members = await get_required_members(config, user_stats['current_ad_cycle_count'])
    
    if required_members == 0:
        update_user_stats(user_id, chat_id, ad_used=True) 
        return 

    current_invited = user_stats.get('invited_members_count', 0)
    
    if current_invited >= required_members:
        remaining_members = current_invited - required_members
        
        update_user_stats(user_id, chat_id, ad_used=True, reset_invited=True)
        if remaining_members > 0:
            update_user_stats(user_id, chat_id, invited_count_change=remaining_members) 

        return 
        
    missing = required_members - current_invited
    
    try:
        await message.delete() 
    except Exception as e:
        await notify_admin_about_error(chat_id, str(e), "Limit buzilganda xabarni o'chirish")
        pass 
    
    user_link = f"[{message.from_user.full_name}](tg://user?id={user_id})"

    message_text = (
        f"❌ **{user_link}**, siz xabar yuborish qoidalarini buzdingiz! (Limit)\n\n"
        f"Keyingi xabar uchun yana **{missing}** ta odam qo'shing. \n"
        f"Sizning joriy hisobingiz: {current_invited} ta odam.\n\n"
    )
    
    try:
        sent_message = await bot.send_message(
            chat_id,
            message_text,
            parse_mode="Markdown"
        )
        asyncio.create_task(delete_message_later(sent_message.chat.id, sent_message.message_id, delay=330))
    except Exception as e:
        print(f"❌ LIMIT OGOHLANTIRISHI YUBORISHDA XATO: {e}")


async def handle_my_id_command(message: types.Message):
    """Foydalanuvchi va chat ID'sini ko'rsatuvchi buyruq."""
    if message.chat.type in ('group', 'supergroup', 'private'):
        await message.reply(f"Sizning ID raqamingiz:\n`{message.from_user.id}`\n\n"
                            f"Agar guruhda yozgan bo'lsangiz, guruh IDsi:\n`{message.chat.id}`", parse_mode="Markdown")

# --- ISHGA TUSHIRISH MANTIQI (aiogram 3.x) ---

def setup_handlers(dp: Dispatcher):
    
    # MESSAGE HANDLERS
    dp.message.register(handle_start, Command("start")) 
    dp.message.register(handle_my_id_command, Command("myid"))
    dp.message.register(process_login, StateFilter(AdminStates.waiting_for_login))
    dp.message.register(process_password, StateFilter(AdminStates.waiting_for_password))
    
    # FSM HANDLERS
    dp.message.register(process_new_free_ad_count, StateFilter(AdminStates.waiting_for_free_ad_count))
    dp.message.register(process_new_reset_interval, StateFilter(AdminStates.waiting_for_reset_interval))
    dp.message.register(process_invite_level_name, StateFilter(AdminStates.waiting_for_invite_level_name))
    dp.message.register(process_invite_level_value, StateFilter(AdminStates.waiting_for_invite_level_value))
    dp.message.register(process_new_chat_id_for_limit, StateFilter(AdminStates.waiting_for_new_chat_id))
    dp.message.register(process_new_channel_username, StateFilter(AdminStates.waiting_for_new_channel_username))
    dp.message.register(process_new_admin_login, StateFilter(AdminStates.waiting_for_new_admin_login))
    dp.message.register(process_new_admin_password, StateFilter(AdminStates.waiting_for_new_admin_password))

    # GURUH HANDLERS (Limit mantiqi)
    dp.message.register(
        handle_group_messages, 
        lambda message: message.chat.type in ('group', 'supergroup') 
        and message.content_type in (ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.STICKER, ContentType.ANIMATION, ContentType.DOCUMENT) 
    )
    
    # GURUH HANDLERS (Salomlashish mantiqi)
    dp.message.register(
        handle_new_member, 
        lambda message: message.chat.type in ('group', 'supergroup') 
        and message.content_type == ContentType.NEW_CHAT_MEMBERS
    ) 

    # CALLBACK QUERY HANDLER
    dp.callback_query.register(handle_admin_callbacks, StateFilter(AdminStates.in_admin_panel)) 
    
    

async def start_bot():
    global bot, dp
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi. Bot ishga tushmaydi.")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) 
    dp = Dispatcher()
    
    setup_handlers(dp)

    print("🚀 Bot ishga tushdi (To'liq funksiyalilik + Ping mantiqi)...")

    # Render uchun maxsus mantiq: Web serverni yaratish
    app = web.Application()
    app.add_routes([web.get('/', handle_ping)]) 
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render avtomatik beradigan PORT ni olish
    PORT = int(os.getenv("PORT", 8080))  
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    print(f"🌐 HTTP Server ishga tushdi: 0.0.0.0:{PORT}")

    # 1. Pollingni alohida Task sifatida ishga tushiramiz
    polling_task = asyncio.create_task(dp.start_polling(bot))

    # 2. Web Serverni ishga tushiramiz
    await site.start()
    
    # 3. O'z-o'ziga ping yuborish mantiqini ishga tushiramiz
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL") 
    if RENDER_EXTERNAL_URL:
        pinger_task = asyncio.create_task(periodic_pinger(RENDER_EXTERNAL_URL))
        print(f"✅ O'z-o'zini ping qilish (har 10 sekund) ishga tushdi: {RENDER_EXTERNAL_URL}")
    else:
        print("⚠️ RENDER_EXTERNAL_URL topilmadi. Bot uxlab qolishi mumkin.")

    # Polling Task tugashini kutamiz (server doim ishlashi uchun)
    await polling_task


if __name__ == '__main__':
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("Bot o'chirildi.")
    except Exception as e:
        print(f"🛑 KRITIK XATO: {e}")
