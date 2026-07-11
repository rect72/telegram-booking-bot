import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import ClientTimeout, TCPConnector
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from config import BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

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

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отменить")]],
    resize_keyboard=True,
)

confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Подтвердить")],
        [KeyboardButton(text="Изменить")],
        [KeyboardButton(text="Отменить")],
    ],
    resize_keyboard=True,
)

SERVICES = ["Стрижка", "Консультация", "Диагностика", "Окрашивание", "Запись на звонок"]


def is_valid_phone(phone: str) -> bool:
    if not phone:
        return False

    digits = "".join(ch for ch in phone if ch.isdigit())

    if len(digits) < 10:
        return False

    if phone.startswith("+7"):
        return True

    if phone.startswith("8"):
        return True

    if len(digits) >= 10:
        return True

    return False


def is_valid_datetime_text(text: str) -> bool:
    if not text or not text.strip():
        return False

    t = text.strip()
    return bool(
        re.search(r"\d{1,2}\s*[^\d]*\d{1,2}:\d{2}", t, re.IGNORECASE)
        or re.search(r"\d{1,2}:\d{2}", t)
    )


class OrderForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_datetime = State()
    waiting_for_comment = State()
    waiting_for_confirmation = State()


@dp.message(CommandStart())
async def start_handler(message: Message):
    logging.info("Got /start")
    await message.answer(
        "Здравствуйте! Я помогу оставить заявку на услугу. Выберите услугу:",
        reply_markup=services_keyboard,
    )


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Действие отменено. Если хотите начать заново, нажмите /start.",
        reply_markup=services_keyboard,
    )


@dp.message(lambda m: m.text == "Отменить")
async def cancel_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Заявка отменена. Чтобы начать заново, нажмите /start.",
        reply_markup=services_keyboard,
    )


@dp.message(lambda message: message.text in SERVICES)
async def choose_service(message: Message, state: FSMContext):
    await state.update_data(service=message.text)
    await state.set_state(OrderForm.waiting_for_name)
    await message.answer("Введите ваше имя:", reply_markup=cancel_keyboard)


@dp.message(OrderForm.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя не должно быть пустым. Введите ваше имя:")
        return

    await state.update_data(name=name)
    await state.set_state(OrderForm.waiting_for_phone)
    await message.answer(
        "Введите ваш телефон. Например: +79991234567 или 89991234567",
        reply_markup=cancel_keyboard,
    )


@dp.message(OrderForm.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip()

    if not is_valid_phone(phone):
        await message.answer(
            "Телефон введён неверно.\n"
            "Введите телефон ещё раз.\n\n"
            "Примеры:\n"
            "+79991234567\n"
            "89991234567",
            reply_markup=cancel_keyboard,
        )
        return

    await state.update_data(phone=phone)
    await state.set_state(OrderForm.waiting_for_datetime)
    await message.answer(
        "Введите дату и время записи.\n"
        "Например: 5 июля в 15:00",
        reply_markup=cancel_keyboard,
    )


@dp.message(OrderForm.waiting_for_datetime)
async def process_datetime(message: Message, state: FSMContext):
    datetime_text = (message.text or "").strip()

    if not datetime_text:
        await message.answer(
            "Дата и время не должны быть пустыми.\n"
            "Например: 5 июля в 15:00",
            reply_markup=cancel_keyboard,
        )
        return

    if not is_valid_datetime_text(datetime_text):
        await message.answer(
            "Дата и время введены неверно.\n"
            "Например: 5 июля в 15:00",
            reply_markup=cancel_keyboard,
        )
        return

    await state.update_data(datetime=datetime_text)
    await state.set_state(OrderForm.waiting_for_comment)
    await message.answer(
        "Введите комментарий к заявке.\n"
        "Если комментария нет, напишите: Нет",
        reply_markup=cancel_keyboard,
    )


@dp.message(OrderForm.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext):
    comment = (message.text or "").strip()

    if not comment:
        comment = "Нет"
    elif comment.lower() in ("нет", "нет.", "no"):
        comment = "Нет"

    await state.update_data(comment=comment)
    data = await state.get_data()

    text = (
        "Проверьте заявку:\n"
        f"Услуга: {data.get('service')}\n"
        f"Имя: {data.get('name')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Дата/время: {data.get('datetime')}\n"
        f"Комментарий: {data.get('comment')}"
    )

    await state.set_state(OrderForm.waiting_for_confirmation)
    logging.info("STATE -> waiting_for_confirmation")

    await message.answer(text, reply_markup=confirm_keyboard)


@dp.message(OrderForm.waiting_for_confirmation)
async def process_confirmation(message: Message, state: FSMContext):
    logging.info("ENTER process_confirmation")
    answer = (message.text or "").strip()

    if answer == "Подтвердить":
        data = await state.get_data()

        await message.answer(
            "Заявка подтверждена. Спасибо!\n"
            "Мы свяжемся с вами в ближайшее время.",
        )

        print("Новая заявка:")
        print(data)

        await state.clear()
        return

    if answer == "Изменить":
        await state.set_state(OrderForm.waiting_for_name)
        await message.answer(
            "Хорошо, заполним заявку заново.\n"
            "Введите ваше имя:",
            reply_markup=cancel_keyboard,
        )
        return

    if answer == "Отменить":
        await state.clear()
        await message.answer(
            "Заявка отменена. Чтобы начать заново, нажмите /start.",
            reply_markup=services_keyboard,
        )
        return

    await message.answer(
        "Пожалуйста, выберите одну из кнопок:\n"
        "Подтвердить / Изменить / Отменить",
        reply_markup=confirm_keyboard,
    )


@dp.message()
async def fallback(message: Message):
    await message.answer(
        "Я пока понимаю только выбор услуги. Нажмите одну из кнопок ниже.",
        reply_markup=services_keyboard,
    )


async def precheck(bot: Bot):
    info = await bot.get_me()
    logging.info(f"Telegram reachable. Bot username: @{info.username}")


async def main():
    PROXY_URL = os.getenv("PROXY_URL", "").strip()

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
