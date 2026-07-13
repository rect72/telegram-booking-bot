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

from pathlib import Path


from config import BOT_TOKEN

from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logging.getLogger("aiohttp").setLevel(logging.INFO)
logging.getLogger("aiogram").setLevel(logging.INFO)

dp = Dispatcher()

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()


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

BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = str(BASE_DIR / "заявки.xlsx")
EXCEL_SHEET = "Заявки"
EXCEL_HEADERS = ["timestamp", "service", "name", "phone", "datetime_text", "comment"]

def save_order_to_excel(data: dict) -> None:
    """
    Сохраняет заявку в Excel.
    Не падает: любые ошибки логируются, бот продолжает работу.
    """
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Если Excel не существует — создаём
        try:
            wb = load_workbook(EXCEL_PATH)
        except FileNotFoundError:
            wb = Workbook()
        except InvalidFileException:
            # файл есть, но он битый/не Excel
            wb = Workbook()
        except PermissionError as e:
            logging.error(f"Excel недоступен (PermissionError): {e}")
            return
        except OSError as e:
            logging.error(f"Excel недоступен (OSError): {e}")
            return

        # Лист
        if EXCEL_SHEET in wb.sheetnames:
            ws = wb[EXCEL_SHEET]
        else:
            ws = wb.create_sheet(EXCEL_SHEET)
            ws.append(EXCEL_HEADERS)

        # На случай пустого нового файла
        if ws.max_row == 0 or (ws.max_row == 1 and ws.cell(1, 1).value is None):
            ws.append(EXCEL_HEADERS)

        ws.append([
            ts,
            data.get("service"),
            data.get("name"),
            data.get("phone"),
            data.get("datetime"),
            data.get("comment", "Нет"),
        ])

        # Сохранение
        try:
            wb.save(EXCEL_PATH)
        except PermissionError as e:
            logging.error(f"Не удалось сохранить Excel (PermissionError): {e}")
            return
        except OSError as e:
            logging.error(f"Не удалось сохранить Excel (OSError): {e}")
            return

    except Exception:
        # важно: бот не ломаем
        logging.exception("save_order_to_excel: неожиданная ошибка, заявка не сохранена")

async def notify_admin(bot: Bot, text: str) -> None:
    if not ADMIN_CHAT_ID:
        return
    try:
        await bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text)
    except Exception:
        logging.exception("Не удалось отправить заявку админу (бот не падает)")



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

def has_empty_required_fields(data: dict) -> tuple[bool, str]:
    required = ["service", "name", "phone", "datetime", "comment"]
    for key in required:
        v = data.get(key)
        if v is None:
            return True, f"Поле '{key}' пустое."
        if isinstance(v, str) and not v.strip():
            return True, f"Поле '{key}' пустое."
    return False, ""



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
    is_empty, err_text = has_empty_required_fields(data)
    if is_empty:
        await state.set_state(OrderForm.waiting_for_name)
        await message.answer(
            f"Не все обязательные поля заполнены: {err_text}\n"
            "Введите ваше имя:",
            reply_markup=cancel_keyboard
        )
        return

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
async def process_confirmation(message: Message, state: FSMContext, bot: Bot):
    logging.info("ENTER process_confirmation")
    answer = (message.text or "").strip()

    if answer == "Подтвердить":
        data = await state.get_data()

        await message.answer(
            "Заявка подтверждена. Спасибо!\n"
            "Мы свяжемся с вами в ближайшее время.",
        )

        text_to_admin = (
            "Новая заявка:\n"
            f"Услуга: {data.get('service')}\n"
            f"Имя: {data.get('name')}\n"
            f"Телефон: {data.get('phone')}\n"
            f"Дата/время: {data.get('datetime')}\n"
            f"Комментарий: {data.get('comment')}"
        )

        try:
            await notify_admin(bot, text_to_admin)
        except Exception:
            logging.exception("Ошибка при отправке заявки админу, бот не падает")

        try:
            save_order_to_excel(data)
        except Exception:
            logging.exception("Ошибка при сохранении заявки (обёртка), бот не падает")

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
            logging.info(f"Excel path: {EXCEL_PATH}")
            logging.info("Precheck: calling getMe()...")
            await precheck(bot)
            logging.info("Starting polling...")
            await dp.start_polling(bot)
        except Exception as e:
            logging.exception(f"Polling loop error: {type(e).__name__}: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
