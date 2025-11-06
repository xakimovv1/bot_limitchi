import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Aiogram importlari
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ChatMemberStatus, ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter 
from aiogram.utils.keyboard import InlineKeyboardBuilder 

# Xatolar uchun importlar (Flood Control uchun)
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter 

# Web server va HTTP so'rovlar uchun kutubxona (Render uchun)
from aiohttp import web, ClientSession 

# --- storage faylini import qilamiz ---
# Iltimos, ushbu fayl asosiy fayl bilan bir xil joyda ekanligiga ishonch hosil qiling.
try:
    from storage import (
        get_config, update_config, get_user_stats, update_user_stats,
        get_required_channels, add_channel, delete_channel, get_all_chat_configs,
        add_new_group
    )
except ImportError:
    print("❌ Xato: 'storage.py' fayli topilmadi. Ma'lumotlar bazasi mantig'i uchun bu fayl zarur.")
    exit()

load_dotenv()

# --- BOT INITS ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Adminlik faqat shu ID orqali beriladi! (Login/Parol olib tashlandi)
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", 0)) 
RENDER_URL_FOR_PING = os.getenv("RENDER_URL_FOR_PING") 
WEB_SERVER_PORT = int(os.getenv("PORT", 10000))

bot = None
dp = None

# --- ADMIN FSM HOLATLARI ---
class AdminStates(StatesGroup):
    MAIN_MENU = State()
    CONFIG_MENU = State()
    CHANGE_FREE_COUNT = State()
    CHANGE_INTERVAL = State()
    CHANGE_INVITE_LEVEL_1 = State()
    CHANGE_INVITE_LEVEL_2 = State()
    CHANGE_INVITE_LEVEL_MAX = State()
    CHANNELS_MENU = State()
    ADD_CHANNEL = State()
    DELETE_CHANNEL = State()
    
# --- RENDER PINGER MANTIQI ---
# (O'zgartirilmagan, avvalgidek qoldi)

async def handle_ping(request):
    """Render'dan kelgan soxta so'rovlarga javob beradi."""
    return web.Response(text="Bot is awake and polling!")

async def periodic_pinger(url, interval_seconds=300):
    """Render serverni uyg'oq ushlab turadi."""
    if not url:
        print("❌ RENDER_URL_FOR_PING o'rnatilmagan. Pinger ishga tushmaydi.")
        return

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
    """Xabarni belgilangan vaqt o'tgach o'chiradi."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass

async def get_required_members(config, ad_cycle_count):
    """Foydalanuvchi reklama tashlash uchun qancha odam taklif qilishi kerakligini hisoblaydi."""

    if ad_cycle_count < config.get('free_ad_count', 1):
        return 0

    current_level = ad_cycle_count - config.get('free_ad_count', 1) + 1
    invite_levels = config.get('invite_levels', {})

    return invite_levels.get(str(current_level), invite_levels.get('max', 10))

# --- ADMIN PANEL INTERFEYSI (Qayta tiklandi) ---

def get_admin_main_menu(admin_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Guruh Sozlamalari", callback_data="config_menu")
    builder.button(text="➕ Majburiy Kanallar", callback_data="channels_menu")
    builder.button(text="👤 Admin Ma'lumotlari", callback_data="admin_credentials_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_config_menu(chat_id):
    config = get_config(chat_id)
    builder = InlineKeyboardBuilder()
    
    builder.button(text=f"Reklama soni: {config.get('free_ad_count', 1)}", callback_data="set_free_count")
    builder.button(text=f"Tiklanish (kun): {config.get('reset_interval_days', 30)}", callback_data="set_interval")
    builder.button(text="--- Taklif Level'lari ---", callback_data="empty")
    
    # Guruh IDlarini listlash
    chat_configs = get_all_chat_configs()
    current_index = chat_configs.index(str(chat_id))
    
    builder.button(text=f"Guruh: {current_index + 1}/{len(chat_configs)}", callback_data="empty")
    
    builder.button(text="⬅️ Oldingi", callback_data="config_prev")
    builder.button(text="Keyingi ➡️", callback_data="config_next")
    
    builder.button(text=f"1-xabar: {config['invite_levels'].get('1', 5)} odam", callback_data="set_level_1")
    builder.button(text=f"2-xabar: {config['invite_levels'].get('2', 7)} odam", callback_data="set_level_2")
    builder.button(text=f"Qolganlari: {config['invite_levels'].get('max', 10)} odam", callback_data="set_level_max")
    
    builder.button(text="↩️ Ortga", callback_data="main_menu")
    builder.adjust(2, 2, 1, 2, 2, 1)
    return builder.as_markup()

def get_channels_menu():
    channels = get_required_channels()
    builder = InlineKeyboardBuilder()
    
    if channels:
        for channel in channels:
            username = channel['channel_username']
            builder.button(text=f"❌ {username}", callback_data=f"del_channel_{username}")
        builder.adjust(1)
    
    builder.button(text="➕ Yangi kanal qo'shish", callback_data="add_channel")
    builder.button(text="↩️ Ortga", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_cancel_markup():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Bekor qilish", callback_data="cancel_action")
    return builder.as_markup()


# --- ADMIN CALLBACK HANDLERS (Qayta tiklandi) ---

async def handle_admin_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    current_data = await state.get_data()
    chat_id = current_data.get('current_chat_id') 

    await callback.message.delete()
    
    if callback.data == "main_menu":
        await state.set_state(AdminStates.MAIN_MENU)
        await callback.message.answer("🏠 **Boshqaruv Paneli**", reply_markup=get_admin_main_menu(user_id))
        return

    # Guruh sozlamalari menyusiga o'tish
    if callback.data == "config_menu":
        # Guruh IDsi yo'q bo'lsa yoki list bo'sh bo'lsa, birinchi guruh ID'sini olish
        if not chat_id:
            chat_id = str(get_all_chat_configs()[0]) if get_all_chat_configs() else "0"
        await state.update_data(current_chat_id=chat_id)
        
        await state.set_state(AdminStates.CONFIG_MENU)
        await callback.message.answer(f"⚙️ Guruh Sozlamalari (ID: {chat_id})", reply_markup=get_config_menu(chat_id))
        return

    # Guruh IDlarini almashtirish
    if callback.data in ["config_prev", "config_next"]:
        chat_configs = get_all_chat_configs()
        if not chat_configs:
            await callback.answer("Guruhlar topilmadi.")
            return

        current_id_str = str(current_data.get('current_chat_id'))
        
        try:
            current_index = chat_configs.index(current_id_str)
        except ValueError:
            current_index = 0

        if callback.data == "config_next":
            next_index = (current_index + 1) % len(chat_configs)
        else: # config_prev
            next_index = (current_index - 1 + len(chat_configs)) % len(chat_configs)
            
        new_chat_id = chat_configs[next_index]
        await state.update_data(current_chat_id=new_chat_id)
        
        # Menyuni yangilash
        await state.set_state(AdminStates.CONFIG_MENU)
        await callback.message.answer(f"⚙️ Guruh Sozlamalari (ID: {new_chat_id})", reply_markup=get_config_menu(new_chat_id))
        return

    # Konfiguratsiya qiymatini o'zgartirishni boshlash
    if callback.data.startswith("set_"):
        key = callback.data.replace("set_", "")
        await state.update_data(config_key=key)

        prompt = ""
        if key == 'free_count':
            prompt = "Bitta siklda bepul ruxsat etiladigan xabarlar sonini kiriting (faqat butun son):"
            await state.set_state(AdminStates.CHANGE_FREE_COUNT)
        elif key == 'interval':
            prompt = "Hisob tiklanish intervalini kunlarda kiriting (faqat butun son):"
            await state.set_state(AdminStates.CHANGE_INTERVAL)
        elif key == 'level_1':
            prompt = "1-xabar uchun taklif qilinishi kerak bo'lgan odamlar sonini kiriting:"
            await state.set_state(AdminStates.CHANGE_INVITE_LEVEL_1)
        elif key == 'level_2':
            prompt = "2-xabar uchun taklif qilinishi kerak bo'lgan odamlar sonini kiriting:"
            await state.set_state(AdminStates.CHANGE_INVITE_LEVEL_2)
        elif key == 'level_max':
            prompt = "3-chi va undan keyingi xabarlar uchun taklif qilinishi kerak bo'lgan odamlar sonini kiriting:"
            await state.set_state(AdminStates.CHANGE_INVITE_LEVEL_MAX)
        
        if prompt:
            await callback.message.answer(prompt, reply_markup=get_cancel_markup())
        return

    # Kanallar menyusiga o'tish
    if callback.data == "channels_menu":
        await state.set_state(AdminStates.CHANNELS_MENU)
        await callback.message.answer("➕ **Majburiy Kanallar Ro'yxati**", reply_markup=get_channels_menu())
        return

    # Yangi kanal qo'shish
    if callback.data == "add_channel":
        await state.set_state(AdminStates.ADD_CHANNEL)
        await callback.message.answer("Qo'shmoqchi bo'lgan kanalning **@username**'ini kiriting (Masalan, `@uzbek_coder`):", reply_markup=get_cancel_markup())
        return

    # Kanalni o'chirish
    if callback.data.startswith("del_channel_"):
        username = callback.data.replace("del_channel_", "")
        if delete_channel(username):
            await callback.answer(f"✅ Kanal ({username}) o'chirildi!", show_alert=True)
        else:
            await callback.answer(f"❌ Xato: Kanal ({username}) topilmadi.", show_alert=True)
            
        # Menyuni yangilash
        await state.set_state(AdminStates.CHANNELS_MENU)
        await callback.message.answer("➕ **Majburiy Kanallar Ro'yxati**", reply_markup=get_channels_menu())
        return
    
    # Bekor qilish
    if callback.data == "cancel_action":
        await state.set_state(AdminStates.MAIN_MENU)
        await callback.message.answer("❌ Harakat bekor qilindi.", reply_markup=get_admin_main_menu(user_id))
        return
    
    # Admin Credentials - Login/parolni o'zgartirish mantiqi olib tashlandi.
    if callback.data == "admin_credentials_menu":
        # Bu yerda faqat ogohlantirish qoldirildi, chunki admin ma'lumotlari storage.py'dan o'chirildi
        await callback.message.answer("⚠️ **Admin ma'lumotlarini o'zgartirish o'chirib qo'yilgan.** Faqat ADMIN_TELEGRAM_ID orqali boshqaring.", reply_markup=get_admin_main_menu(user_id))
        await state.set_state(AdminStates.MAIN_MENU)
        return


# --- ADMIN MESSAGE HANDLERS (Qayta tiklandi) ---

async def save_config_value(message: types.Message, state: FSMContext, is_invite_level=False):
    try:
        new_value = int(message.text.strip())
        if new_value < 0:
            raise ValueError
    except ValueError:
        await message.reply("❌ Xato: Faqat musbat butun son kiriting.")
        return

    data = await state.get_data()
    chat_id = data.get('current_chat_id')
    config_key = data.get('config_key')
    
    config = get_config(chat_id)

    if is_invite_level:
        # Level'larni o'zgartirish
        if 'invite_levels' not in config:
            config['invite_levels'] = {}
            
        key_map = {'level_1': '1', 'level_2': '2', 'level_max': 'max'}
        level_key = key_map.get(config_key)
        
        config['invite_levels'][level_key] = new_value
        update_config(chat_id, 'invite_levels', config['invite_levels'])
        
    else:
        # Oddiy kalitlarni o'zgartirish
        key_map = {'free_count': 'free_ad_count', 'interval': 'reset_interval_days'}
        real_key = key_map.get(config_key)
        
        update_config(chat_id, real_key, new_value)

    await state.set_state(AdminStates.CONFIG_MENU)
    await message.answer(f"✅ **Sozlama muvaffaqiyatli yangilandi!**\n\nID: {chat_id}", reply_markup=get_config_menu(chat_id))

# Config Handlers
async def change_free_count_handler(message: types.Message, state: FSMContext):
    await save_config_value(message, state, is_invite_level=False)

async def change_interval_handler(message: types.Message, state: FSMContext):
    await save_config_value(message, state, is_invite_level=False)

async def change_level_1_handler(message: types.Message, state: FSMContext):
    await save_config_value(message, state, is_invite_level=True)

async def change_level_2_handler(message: types.Message, state: FSMContext):
    await save_config_value(message, state, is_invite_level=True)

async def change_level_max_handler(message: types.Message, state: FSMContext):
    await save_config_value(message, state, is_invite_level=True)

# Channels Handler
async def add_channel_handler(message: types.Message, state: FSMContext):
    username = message.text.strip().replace('@', '')
    
    if not username:
        await message.reply("❌ Username bo'sh bo'lishi mumkin emas.")
        return

    if add_channel(username):
        await message.answer(f"✅ Kanal **@{username}** ro'yxatga qo'shildi.", reply_markup=get_channels_menu())
    else:
        await message.answer(f"❌ Kanal **@{username}** allaqachon ro'yxatda mavjud.", reply_markup=get_channels_menu())

    await state.set_state(AdminStates.CHANNELS_MENU)


# --- MESSAGE HANDLERS ---

async def handle_start(message: types.Message, state: FSMContext):
    """Botni /start buyrug'i bilan ishga tushirish (Admin kirish soddalashtirildi)."""
    user_id = message.from_user.id
    
    # 🛑 ADMIN KIRISH MANTIQI: Faqat ADMIN_TELEGRAM_ID orqali tekshirish
    if user_id == ADMIN_TELEGRAM_ID and message.chat.type == 'private':
        # Admin Boshqaruv Paneliga kirish
        await state.set_state(AdminStates.MAIN_MENU)
        await state.update_data(current_chat_id=get_all_chat_configs()[0] if get_all_chat_configs() else "0")
        await message.answer("🔑 **Admin Boshqaruv Paneli**", reply_markup=get_admin_main_menu(user_id))
        return
        
    if message.chat.type in ('group', 'supergroup'):
        # Guruhni faollashtirish uchun uni 'config.json' ga qo'shish
        add_new_group(message.chat.id) 
        await message.answer("✅ **Bot guruhda ishga tushirildi!** Endi foydalanuvchilar limit bo'yicha cheklanadi.\n\n"
                             "**Eslatma:** Guruh IDsi avtomatik ravishda limit sozlamalariga qo'shildi.")
        return
        
    await message.answer("👋 **Xush kelibsiz!** Bu bot guruhlarda a'zolik taklif qilish orqali reklama limitini boshqaradi.")


# --- GURUH HANDLERS (O'zgartirilmagan) ---

async def handle_new_member(message: types.Message):
    # Oldingi koddagi mantiq joyida qoldi
    # ... (kod juda uzunligi sababli to'liq takrorlanmadi) ...
    # ...

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
                    f"🎉 **{inviter_link}**, siz **{current_invited}** ta odam qo'shdingiz!\n"
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
        except Exception:
            print(f"❌ SISTEM XABARINI O'CHIRISHDA XATO: {message.chat.id}")


async def handle_group_messages(message: types.Message):
    # Oldingi koddagi mantiq joyida qoldi
    # ... (kod juda uzunligi sababli to'liq takrorlanmadi) ...
    # ...

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
        print(f"❌ LIMIT BUZILGANDA XABARNI O'CHIRISHDA XATO: {e}")
        pass

    user_link = f"[{message.from_user.full_name}](tg://user?id={user_id})"

    message_text = (
        f"❌ **{user_link}**, siz xabar yuborish qoidalarini buzdingiz! (Limit)\n\n"
        f"Keyingi xabar uchun yana **{missing}** ta odam qo'shing. \n"
        f"Sizning joriy hisobingiz: {current_invited} ta odam.\n\n"
    )
    
    # 🛑 FLOOD CONTROL NI HAL QILISH UCHUN TRY-EXCEPT BLOKI
    try:
        sent_message = await bot.send_message(
            chat_id,
            message_text,
            parse_mode="Markdown"
        )
        asyncio.create_task(delete_message_later(sent_message.chat.id, sent_message.message_id, delay=330))

    except TelegramRetryAfter as e:
        # Telegram Flood Control'ni so'radi. So'ralgan vaqtcha kutamiz.
        print(f"⚠️ Flood Control: {e.retry_after} soniya kutilyapti...")
        await asyncio.sleep(e.retry_after) 
        
        # Kutib bo'lgach, xabarni qayta yuborishga urinish
        try:
            sent_message = await bot.send_message(
                chat_id,
                message_text,
                parse_mode="Markdown"
            )
            asyncio.create_task(delete_message_later(sent_message.chat.id, sent_message.message_id, delay=330))

        except Exception as retry_e:
            print(f"❌ LIMIT OGOHLANTIRISHI YUBORISHDA XATO (Qayta urinish): {retry_e}")

    except Exception as e:
        # Boshqa noma'lum xatolar
        print(f"❌ LIMIT OGOHLANTIRISHI YUBORISHDA NOMA'LUM XATO: {e}")


async def handle_my_id_command(message: types.Message):
    """Foydalanuvchi va chat ID'sini ko'rsatuvchi buyruq."""
    if message.chat.type in ('group', 'supergroup', 'private'):
        await message.reply(f"Sizning ID raqamingiz:\n`{message.from_user.id}`\n\n"
                            f"Agar guruhda yozgan bo'lsangiz, guruh IDsi:\n`{message.chat.id}`", parse_mode="Markdown")

# --- ISHGA TUSHIRISH MANTIQI (aiogram 3.x) ---

def setup_handlers(dp: Dispatcher):

    # MESSAGE HANDLERS (Admin va oddiy)
    dp.message.register(handle_start, Command("start"))
    dp.message.register(handle_my_id_command, Command("myid"))

    # ADMIN FSM HANDLERS (Faqat StateFilter orqali)
    dp.callback_query.register(handle_admin_callback, StateFilter(AdminStates))
    
    # Guruh sozlamalarini yangilash
    dp.message.register(change_free_count_handler, StateFilter(AdminStates.CHANGE_FREE_COUNT), F.text)
    dp.message.register(change_interval_handler, StateFilter(AdminStates.CHANGE_INTERVAL), F.text)
    dp.message.register(change_level_1_handler, StateFilter(AdminStates.CHANGE_INVITE_LEVEL_1), F.text)
    dp.message.register(change_level_2_handler, StateFilter(AdminStates.CHANGE_INVITE_LEVEL_2), F.text)
    dp.message.register(change_level_max_handler, StateFilter(AdminStates.CHANGE_INVITE_LEVEL_MAX), F.text)

    # Kanal qo'shish
    dp.message.register(add_channel_handler, StateFilter(AdminStates.ADD_CHANNEL), F.text)
    
    # GURUH HANDLERS (Limit mantiqi)
    dp.message.register(
        handle_new_member,
        lambda message: message.chat.type in ('group', 'supergroup') and message.content_type == ContentType.NEW_CHAT_MEMBERS
    )
    dp.message.register(
        handle_group_messages,
        lambda message: message.chat.type in ('group', 'supergroup') 
        and message.content_type in (ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.AUDIO, ContentType.DOCUMENT, ContentType.ANIMATION, ContentType.STICKER)
    )


async def start_polling():
    """Botning Telegram serveri bilan ulanishini boshlaydi."""
    global bot, dp
    print("🚀 Bot Polling (Telegram so'rovlari) ishga tushdi.")
    await dp.start_polling(bot)

async def start_server():
    """Veb-serverni ishga tushiradi (Renderning 'always on' bo'lishi uchun)."""
    global WEB_SERVER_PORT

    app = web.Application()
    app.add_routes([web.get('/ping', handle_ping)])

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host='0.0.0.0', port=WEB_SERVER_PORT)
    await site.start()

    print(f"🌐 Veb-server {WEB_SERVER_PORT}-portda ishga tushdi.")


async def main():
    global bot, dp

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN .env faylida topilmadi!")
        return
        
    if not ADMIN_TELEGRAM_ID:
        print("⚠️ ADMIN_TELEGRAM_ID .env faylida o'rnatilmagan. Admin paneli ishlamaydi!")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    setup_handlers(dp) # Handlers ni sozlaymiz

    await start_server()
    if RENDER_URL_FOR_PING:
        asyncio.create_task(periodic_pinger(RENDER_URL_FOR_PING))

    await start_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot o'chirildi.")
    except Exception as e:
        print(f"Kritik xato: {e}")
