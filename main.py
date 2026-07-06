import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import ClientTimeout, TCPConnector

from config import BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# aiohttp/aiogram logs
logging.getLogger("aiohttp").setLevel(logging.INFO)
logging.getLogger("aiogram").setLevel(logging.INFO)

dp = Dispatcher()

services_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Стрижка")],
        [KeyboardButton(text="Консультация")],
        [KeyboardButton(text="Диагностика")],
        [KeyboardButton(text="Окрашивание")],
        [KeyboardButton(text="Запись на звонок")],
    ],
    resize_keyboard=True,
)


@dp.message(CommandStart())
async def start_handler(message: Message):
    logging.info("Got /start")
    await message.answer(
        "Здравствуйте! Я помогу оставить заявку на услугу. Выберите услугу:",
        reply_markup=services_keyboard,
    )


@dp.message(F.text.in_(["Стрижка", "Консультация", "Диагностика", "Окрашивание", "Запись на звонок"]))
async def service_handler(message: Message):
    logging.info(f"Got service: {message.text}")
    await message.answer(f"Вы выбрали услугу: {message.text}")


@dp.message()
async def any_message(message: Message):
    logging.info(f"Got message: {message.text!r}")
    await message.answer("Я получил сообщение. Нажмите /start или выберите услугу.")

@dp.message()
async def unknown_message_handler(message: Message):
    await message.answer(
        "Я пока понимаю только выбор услуги. Нажмите одну из кнопок ниже.",
        reply_markup=services_keyboard
    )

async def precheck(bot: Bot):
    info = await bot.get_me()
    logging.info(f"Telegram reachable. Bot username: @{info.username}")


async def main():
    # УКАЖИТЕ ПРОКСИ ИЗ HAPP (если есть), в формате:
    # http://USER:PASS@HOST:PORT
    # или socks5://USER:PASS@HOST:PORT
    # или socks5h://USER:PASS@HOST:PORT
    PROXY_URL = os.getenv("PROXY_URL", "").strip()  # можно вручную заменить строкой

    timeout = ClientTimeout(total=120, connect=60, sock_connect=60, sock_read=60)

    connector = TCPConnector(
        limit=0,
        limit_per_host=0,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )

    bot_kwargs = dict(token=BOT_TOKEN, timeout=timeout, connector=connector)
    if PROXY_URL:
        bot_kwargs["proxy"] = PROXY_URL

    bot = Bot(**bot_kwargs)

    # простые ретраи вокруг polling
    while True:
        try:
            logging.info("Precheck: calling getMe()...")
            await precheck(bot)
            logging.info("Starting polling...")
            await dp.start_polling(bot)
        except Exception as e:
            logging.exception(f"Polling loop error: {type(e).__name__}: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
