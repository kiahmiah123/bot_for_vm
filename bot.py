
import os
import logging
from datetime import datetime
from pytz import timezone
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

import gspread
from google.oauth2.service_account import Credentials

# ---------- Load env ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WELCOME_IMAGE_URL = os.getenv("WELCOME_IMAGE_URL")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
CHECKLIST_FAMILY = os.getenv("CHECKLIST_FAMILY", "https://t.me/yourchannel/1")
CHECKLIST_IT = os.getenv("CHECKLIST_IT", "https://t.me/yourchannel/2")
CHECKLIST_TOP_COMPLEXES = os.getenv("CHECKLIST_TOP_COMPLEXES", "https://drive.google.com/file/d/12aUi-WfJ3Ffs01QqTtj7zpAhkY3yssvZ/view?usp=drive_link")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")
if not SPREADSHEET_ID:
    raise RuntimeError("GOOGLE_SPREADSHEET_ID is not set in .env")
if not os.path.exists("service_account.json"):
    raise RuntimeError("service_account.json not found. Put your Google Service Account key file next to bot.py")

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Google Sheets init ----------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)

def ensure_worksheet(name: str, headers: list):
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=100, cols=20)
    row1 = ws.row_values(1)
    if not row1:
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws

ws_leads = ensure_worksheet("leads", [
    "timestamp", "user_id", "username", "full_name",
    "district", "rooms", "deadline", "purchase", "budget"
])
ws_questions = ensure_worksheet("questions", [
    "timestamp", "user_id", "username", "full_name", "question"
])

TZ = timezone("Europe/Kaliningrad")

def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %Z")

def safe_username(u: types.User):
    return f"@{u.username}" if u.username else ""

def append_lead(user: types.User, data: dict):
    ws_leads.append_row([
        now_str(),
        user.id,
        safe_username(user),
        f"{user.first_name or ''} {user.last_name or ''}".strip(),
        data.get("district", ""),
        data.get("rooms", ""),
        data.get("deadline", ""),
        data.get("purchase", ""),
        data.get("budget", ""),
    ], value_input_option="USER_ENTERED")

def append_question(user: types.User, question: str):
    ws_questions.append_row([
        now_str(),
        user.id,
        safe_username(user),
        f"{user.first_name or ''} {user.last_name or ''}".strip(),
        question,
    ], value_input_option="USER_ENTERED")

# ---------- Telegram bot ----------
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=MemoryStorage())

# States for lead form
class LeadForm(StatesGroup):
    district = State()
    rooms = State()
    deadline = State()
    purchase = State()
    budget = State()

class QuestionForm(StatesGroup):
    text = State()

def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🏠 Получить подборку", "❓ Задать вопрос", "📋 Чек-листы")
    return kb

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! 👋 Я помогу подобрать квартиру в Калининграде.\n\n"
        "Выберите действие из меню ниже:",
        reply_markup=main_menu()
    )
    if WELCOME_IMAGE_URL:
        try:
            await bot.send_photo(message.chat.id, WELCOME_IMAGE_URL)
        except Exception as e:
            logger.warning(f"Failed to send welcome image: {e}")

# ---------- Lead form ----------
@dp.message_handler(lambda m: m.text == "🏠 Получить подборку")
async def lead_start(message: types.Message, state: FSMContext):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Ленинградский", "Московский")
    kb.add("Центральный", "Не важно")
    kb.add("↩️ Назад")
    await message.answer("Выберите район:", reply_markup=kb)
    await LeadForm.district.set()

@dp.message_handler(lambda m: m.text == "↩️ Назад", state="*")
async def go_back(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Вы в главном меню.", reply_markup=main_menu())

@dp.message_handler(state=LeadForm.district)
async def lead_district(message: types.Message, state: FSMContext):
    if message.text == "↩️ Назад":
        return await go_back(message, state)
    await state.update_data(district=message.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1", "1+", "2")
    kb.add("2+", "3", "3+")
    kb.add("↩️ Назад")
    await message.answer("Сколько комнат нужно?", reply_markup=kb)
    await LeadForm.rooms.set()

@dp.message_handler(state=LeadForm.rooms)
async def lead_rooms(message: types.Message, state: FSMContext):
    if message.text == "↩️ Назад":
        return await go_back(message, state)
    await state.update_data(rooms=message.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Сдан", "В этом году")
    kb.add("1-2 года", "3-4 года")
    kb.add("Неважно", "↩️ Назад")
    await message.answer("Какой срок сдачи интересует?", reply_markup=kb)
    await LeadForm.deadline.set()

@dp.message_handler(state=LeadForm.deadline)
async def lead_deadline(message: types.Message, state: FSMContext):
    if message.text == "↩️ Назад":
        return await go_back(message, state)
    await state.update_data(deadline=message.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Ипотека", "Льготные программы")
    kb.add("Рассрочка", "Наличные")
    kb.add("↩️ Назад")
    await message.answer("Какой способ покупки?", reply_markup=kb)
    await LeadForm.purchase.set()

@dp.message_handler(state=LeadForm.purchase)
async def lead_purchase(message: types.Message, state: FSMContext):
    if message.text == "↩️ Назад":
        return await go_back(message, state)
    await state.update_data(purchase=message.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("До 5 млн", "5 - 7 млн")
    kb.add("7 - 9 млн", "9 - 12 млн")
    kb.add("Более 12 млн", "↩️ Назад")
    await message.answer("Какой бюджет рассматриваете?", reply_markup=kb)
    await LeadForm.budget.set()

@dp.message_handler(state=LeadForm.budget)
async def lead_finish(message: types.Message, state: FSMContext):
    if message.text == "↩️ Назад":
        return await go_back(message, state)
    await state.update_data(budget=message.text)
    data = await state.get_data()
    await state.finish()

    # Confirm to user
    await message.answer("✅ Ваш запрос принят, уже обрабатываем его!", reply_markup=main_menu())

    # Send to admin
    summary = (
        "<b>Новый запрос на подборку</b>\n"
        f"Район: {data.get('district')}\n"
        f"Комнаты: {data.get('rooms')}\n"
        f"Срок сдачи: {data.get('deadline')}\n"
        f"Способ покупки: {data.get('purchase')}\n"
        f"Бюджет: {data.get('budget')}\n"
        f"От: {safe_username(message.from_user)} (ID: {message.from_user.id})"
    )
    try:
        await bot.send_message(ADMIN_ID, summary)
    except Exception as e:
        logger.error(f"Failed to send admin message: {e}")

    # Save to Google Sheets
    try:
        append_lead(message.from_user, data)
    except Exception as e:
        logger.error(f"Failed to append to Google Sheets (leads): {e}")
        try:
            await bot.send_message(ADMIN_ID, f"⚠️ Ошибка записи в Google Sheets (leads): {e}")
        except Exception:
            pass

# ---------- Ask a Question ----------
@dp.message_handler(lambda m: m.text == "❓ Задать вопрос")
async def ask_question(message: types.Message, state: FSMContext):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("↩️ Назад")
    await message.answer("Опишите ваш вопрос в одном сообщении. Я передам его специалисту.", reply_markup=kb)
    await QuestionForm.text.set()

@dp.message_handler(state=QuestionForm.text, content_types=types.ContentTypes.TEXT)
async def receive_question(message: types.Message, state: FSMContext):
    if message.text == "↩️ Назад":
        await state.finish()
        return await message.answer("Вы в главном меню.", reply_markup=main_menu())

    question = message.text.strip()
    await state.finish()

    # Notify user
    await message.answer("✅ Спасибо! Ваш вопрос передан. Я свяжусь с вами в ближайшее время.", reply_markup=main_menu())

    # Send to admin
    summary = (
        "<b>Новый вопрос</b>\n"
        f"{question}\n\n"
        f"От: {safe_username(message.from_user)} (ID: {message.from_user.id})"
    )
    try:
        await bot.send_message(ADMIN_ID, summary)
    except Exception as e:
        logger.error(f"Failed to send admin question: {e}")

    # Save to Google Sheets
    try:
        append_question(message.from_user, question)
    except Exception as e:
        logger.error(f"Failed to append to Google Sheets (questions): {e}")
        try:
            await bot.send_message(ADMIN_ID, f"⚠️ Ошибка записи в Google Sheets (questions): {e}")
        except Exception:
            pass

# ---------- Checklists ----------
@dp.message_handler(lambda m: m.text == "📋 Чек-листы")
async def checklists(message: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Как получить семейную ипотеку")
    kb.add("Как получить IT-ипотеку")
    kb.add("Лучшие ЖК Калининграда")
    kb.add("↩️ Назад")
    await message.answer("Выберите чек-лист:", reply_markup=kb)

@dp.message_handler(lambda m: m.text in ["Как получить семейную ипотеку", "Как получить IT-ипотеку", "Лучшие ЖК Калининграда"])
async def checklist_links(message: types.Message):
    mapping = {
        "Как получить семейную ипотеку": CHECKLIST_FAMILY,
        "Как получить IT-ипотеку": CHECKLIST_IT,
        "Лучшие ЖК Калининграда": CHECKLIST_TOP_COMPLEXES,
    }
    link = mapping.get(message.text)
    await message.answer(f"Вот ваш чек-лист: {link}", disable_web_page_preview=False)

# Fallback: unknown text -> show menu
@dp.message_handler(content_types=types.ContentTypes.ANY)
async def fallback(message: types.Message):
    await message.answer("Выберите действие из меню 👇", reply_markup=main_menu())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
