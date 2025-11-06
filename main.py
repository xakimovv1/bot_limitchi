import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Aiogram importlari
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatMemberStatus, ContentType
# FSM importlari olib tashlandi
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command 
# InlineKeyboardBuilder qoldi, chunki u get_required_members uchun kerak
from aiogram.utils.keyboard import InlineKeyboardBuilder 

# Xatolar uchun importlar (Flood Control uchun)
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter 

# Web server va HTTP so'rovlar uchun kutubxona (Render uchun)
from aiohttp import web, ClientSession 

# --- storage faylini import qilamiz ---
try:
    from storage import (
        get_config, update_config, get_user_stats, update_user_stats,
        # Admin funksiyalari olib tashlandi
        get_required_channels, add_channel, delete_channel, get_all_chat_configs,
        add_new_group
    )
except ImportError:
    print("❌ Xato: 'storage.py' fayli topilmadi. Ma'lumotlar bazasi mantig'i uchun bu fayl zarur.")
    exit()

load_dotenv()

# --- BOT INITS ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
# ADMIN_TELEGRAM_ID olib tashlandi
# Renderda o'z-o'zini ping qilish uchun URL (.env da o'rnatilishi kerak)
RENDER_URL_FOR_PING = os.getenv("RENDER_URL_FOR_PING") 
WEB_SERVER_PORT = int(os.getenv("PORT", 10000))

bot = None
dp = None

# --- RENDER PINGER MANTIQI (Render serverni uyg'oq ushlab turish uchun) ---

async def handle_ping(request):
    """Render'dan kelgan soxta so'rovlarga javob beradi (botni uyg'otib turish uchun)."""
    return web.Response(text="Bot is awake and polling!")

async def periodic_pinger(url, interval_seconds=300): # Har 5 daqiqada (300 soniya)
    """Berilgan URL manzilga har 5 daqiqada so'rov yuboradi (o'zini-o'zi uyg'otish)."""
    if not url:
        print("❌ RENDER_URL_FOR_PING o'rnatilmagan. Pinger ishga tushmaydi.")
        return

    async with ClientSession() as session:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                # O'z-o'ziga soxta GET so'rovini yuborish
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

# notify_admin_about_error olib tashlandi

# --- FSM HOLATLARI (AdminStates to'plami olib tashlandi) ---


# --- FILTRLAR VA FUNKSIYALARI ---

async def get_required_members(config, ad_cycle_count):
    """Foydalanuvchi reklama tashlash uchun qancha odam taklif qilishi kerakligini hisoblaydi."""

    if ad_cycle_count < config.get('free_ad_count', 1):
        return 0

    current_level = ad_cycle_count - config.get('free_ad_count', 1) + 1
    invite_levels = config.get('invite_levels', {})

    return invite_levels.get(str(current_level), invite_levels.get('max', 10))


# --- ADMIN PANEL INTERFEYSI (Butunlay olib tashlandi) ---


# --- MESSAGE HANDLERS ---

async def handle_start(message: types.Message):
    """Botni /start buyrug'i bilan ishga tushirish (oddiy foydalanuvchi mantiqi)."""
    
    if message.chat.type in ('group', 'supergroup'):
        # Guruhni faollashtirish uchun uni 'config.json' ga qo'shish
        add_new_group(message.chat.id) 
        await message.answer("✅ **Bot guruhda ishga tushirildi!** Endi foydalanuvchilar limit bo'yicha cheklanadi.\n\n"
                             "**Eslatma:** Guruh IDsi avtomatik ravishda limit sozlamalariga qo'shildi. Sozlamalarni faqat `config.json` faylidan o'zgartirish mumkin.")
        return
        
    await message.answer("👋 **Xush kelibsiz!** Bu bot guruhlarda a'zolik taklif qilish orqali reklama limitini boshqaradi.")


# Barcha admin FSM handlerlari olib tashlandi

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
    """Guruhdagi oddiy xabarlarni limit bo'yicha cheklaydi (Flood Control to'g'irlangan)."""
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

    # MESSAGE HANDLERS
    dp.message.register(handle_start, Command("start"))
    dp.message.register(handle_my_id_command, Command("myid"))

    # FSM HANDLERS (Olib tashlandi)

    # GURUH HANDLERS (Limit mantiqi)
    dp.message.register(
        handle_new_member,
        lambda message: message.chat.type in ('group', 'supergroup') and message.content_type == ContentType.NEW_CHAT_MEMBERS
    )
    dp.message.register(
        handle_group_messages,
        lambda message: message.chat.type in ('group', 'supergroup') 
        and message.content_type in (ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.AUDIO, ContentType.DOCUMENT)
    )

    # CALLBACK HANDLER (Olib tashlandi)


async def start_polling():
    """Botning Telegram serveri bilan ulanishini boshlaydi."""
    global bot, dp
    print("🚀 Bot Polling (Telegram so'rovlari) ishga tushdi.")
    await dp.start_polling(bot)

async def start_server():
    """Veb-serverni ishga tushiradi (Renderning 'always on' bo'lishi uchun)."""
    global WEB_SERVER_PORT

    app = web.Application()
    # /ping yo'lini handle_ping funksiyasiga ulaymiz
    app.add_routes([web.get('/ping', handle_ping)])

    runner = web.AppRunner(app)
    await runner.setup()

    # Render muhiti uchun 0.0.0.0 host va PORT muhit o'zgaruvchisidan olingan port ishlatiladi
    site = web.TCPSite(runner, host='0.0.0.0', port=WEB_SERVER_PORT)
    await site.start()

    print(f"🌐 Veb-server {WEB_SERVER_PORT}-portda ishga tushdi.")


async def main():
    global bot, dp

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN .env faylida topilmadi!")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    setup_handlers(dp) # Handlers ni sozlaymiz

    # 1. Veb-serverni ishga tushiramiz (Render kirish so'rovlarini qabul qilish uchun)
    await start_server()

    # 2. Render pingerini ishga tushiramiz (Botni uxlab qolishdan saqlash uchun)
    if RENDER_URL_FOR_PING:
        # Pinger vazifasini alohida task sifatida boshlaymiz
        asyncio.create_task(periodic_pinger(RENDER_URL_FOR_PING))

    # 3. Bot Pollingni ishga tushiramiz (Telegramdan xabarlarni qabul qilish uchun)
    await start_polling()


if __name__ == "__main__":
    try:
        # Barcha asinxron funksiyalarni ishga tushirish
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot o'chirildi.")
    except Exception as e:
        print(f"Kritik xato: {e}")
