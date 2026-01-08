import asyncio
import logging
import re
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, 
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import aiosqlite

# ==================== КОНФИГУРАЦИЯ ====================
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен берется из переменной окружения
ADMIN_IDS = [8343231096]            # главный админ
ADMIN_GROUP_ID = -1003692051473     # ID группы админ-панели

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")


# Ссылки на ресурсы
RESOURCES_LINKS = {
    "chat": "https://t.me/+36dQ6mR6FcVjYTdi",
    "payments": "https://t.me/+T8U1uXPvrnw1Mzgy",
    "logs": "https://t.me/+KxYSRT3Ut4ZlNTcy",
    "updates": "https://t.me/+Wzf_xOx-CMk5M2Yy"
}

# ==================== НАСТРОЙКА ====================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# ==================== FSM STATES ====================
class ApplicationForm(StatesGroup):
    source = State()
    experience = State()
    time = State()
    why = State()
    confirm = State()

class ChangeNick(StatesGroup):
    waiting_nick = State()

class BindWallet(StatesGroup):
    waiting_wallet = State()

class AdminSearch(StatesGroup):
    waiting_search = State()

class AdminAddProfit(StatesGroup):
    waiting_amount = State()
    user_id = State()

class AdminRemoveProfit(StatesGroup):
    waiting_amount = State()
    user_id = State()

class AdminChangePercent(StatesGroup):
    waiting_percent = State()
    user_id = State()

class BroadcastAll(StatesGroup):
    waiting_message = State()

class BroadcastOne(StatesGroup):
    waiting_user = State()
    waiting_message = State()

class AddAdmin(StatesGroup):
    waiting_id = State()

class RemoveAdmin(StatesGroup):
    waiting_id = State()

# ==================== DATABASE ====================
DB_NAME = "team_bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                nickname TEXT,
                status TEXT DEFAULT 'pending',
                percent INTEGER DEFAULT 65,
                profits_count INTEGER DEFAULT 0,
                profits_sum REAL DEFAULT 0.0,
                wallet TEXT,
                application_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_ids TEXT,
                content_type TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def save_application(user_id: int, username: str, answers: dict):
    async with aiosqlite.connect(DB_NAME) as db:
        application_text = "\n".join([f"{k}: {v}" for k, v in answers.items()])
        await db.execute("""
            INSERT OR REPLACE INTO users (user_id, username, application_data, status)
            VALUES (?, ?, ?, 'pending')
        """, (user_id, username, application_text))
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "username": row[1],
                    "nickname": row[2],
                    "status": row[3],
                    "percent": row[4],
                    "profits_count": row[5],
                    "profits_sum": row[6],
                    "wallet": row[7],
                    "application_data": row[8]
                }
    return None

async def update_user_status(user_id: int, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET status = ? WHERE user_id = ?", (status, user_id)
        )
        await db.commit()

async def update_nickname(user_id: int, nickname: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id)
        )
        await db.commit()

async def update_wallet(user_id: int, wallet: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET wallet = ? WHERE user_id = ?", (wallet, user_id)
        )
        await db.commit()

async def add_profit(user_id: int, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE users 
            SET profits_sum = profits_sum + ?, 
                profits_count = profits_count + 1 
            WHERE user_id = ?
        """, (amount, user_id))
        await db.commit()

async def remove_profit(user_id: int, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE users 
            SET profits_sum = CASE 
                WHEN profits_sum - ? < 0 THEN 0 
                ELSE profits_sum - ? 
            END,
                profits_count = CASE 
                WHEN profits_count - 1 < 0 THEN 0 
                ELSE profits_count - 1 
            END
            WHERE user_id = ?
        """, (amount, amount, user_id))
        await db.commit()

async def update_percent(user_id: int, percent: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET percent = ? WHERE user_id = ?", (percent, user_id)
        )
        await db.commit()

async def find_user_by_username(username: str):
    username = username.lstrip('@')
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT * FROM users WHERE username LIKE ?", (f"%{username}%",)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "username": row[1],
                    "nickname": row[2],
                    "status": row[3],
                    "percent": row[4],
                    "profits_count": row[5],
                    "profits_sum": row[6],
                    "wallet": row[7]
                }
    return None

async def get_all_approved_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, username, nickname FROM users WHERE status = 'approved' ORDER BY username"
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"user_id": r[0], "username": r[1], "nickname": r[2]} for r in rows]

async def add_admin_to_db(admin_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (admin_id,))
        await db.commit()

async def remove_admin_from_db(admin_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM admins WHERE admin_id = ?", (admin_id,))
        await db.commit()

async def get_all_admins():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()
        async with db.execute("SELECT admin_id FROM admins") as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    admins = await get_all_admins()
    return user_id in admins

async def save_broadcast(message_ids: list, content_type: str, content: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO broadcasts (message_ids, content_type, content)
            VALUES (?, ?, ?)
        """, (json.dumps(message_ids), content_type, content))
        await db.commit()

async def get_all_broadcasts():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, message_ids, content_type, content, created_at FROM broadcasts ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [{
                "id": r[0],
                "message_ids": json.loads(r[1]),
                "content_type": r[2],
                "content": r[3],
                "created_at": r[4]
            } for r in rows]

async def delete_broadcast_by_id(broadcast_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM broadcasts WHERE id = ?", (broadcast_id,))
        await db.commit()

async def delete_all_broadcasts():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM broadcasts")
        await db.commit()

# ==================== KEYBOARDS ====================
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подать заявку", callback_data="apply")]
    ])

def get_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить", callback_data="submit")],
        [InlineKeyboardButton(text="Заполнить заново", callback_data="restart")]
    ])

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мой профиль")],
            [KeyboardButton(text="Ресурсы")]
        ],
        resize_keyboard=True
    )

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить ник", callback_data="change_nick")],
        [InlineKeyboardButton(text="Привязать кошелек", callback_data="bind_wallet")]
    ])

def get_resources_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Общий чат", url=RESOURCES_LINKS["chat"])],
        [InlineKeyboardButton(text="Выплаты", url=RESOURCES_LINKS["payments"])],
        [InlineKeyboardButton(text="Логи", url=RESOURCES_LINKS["logs"])],
        [InlineKeyboardButton(text="Обновления", url=RESOURCES_LINKS["updates"])]
    ])

def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_to_profile")]
    ])

def get_admin_application_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{user_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")]
    ])

def get_admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_search")],
        [InlineKeyboardButton(text="📢 Рассылки", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🛡️ Управление админами", callback_data="admin_manage_admins")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])

def get_broadcast_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Всем участникам", callback_data="broadcast_all")],
        [InlineKeyboardButton(text="👤 Одному пользователю", callback_data="broadcast_one")],
        [InlineKeyboardButton(text="🗑 Удалить рассылку", callback_data="delete_broadcast_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

def get_delete_broadcast_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Удалить одну рассылку", callback_data="delete_one_broadcast")],
        [InlineKeyboardButton(text="🗑 Удалить все рассылки", callback_data="delete_all_broadcasts_confirm")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_broadcast")]
    ])

def get_admin_manage_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="remove_admin")],
        [InlineKeyboardButton(text="👥 Список админов", callback_data="list_admins")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

def get_admin_user_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Забанить", callback_data=f"ban_{user_id}")],
        [InlineKeyboardButton(text="📊 Изменить процент", callback_data=f"change_percent_{user_id}")],
        [InlineKeyboardButton(text="➕ Начислить профит", callback_data=f"add_profit_{user_id}")],
        [InlineKeyboardButton(text="➖ Удалить профит", callback_data=f"remove_profit_{user_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

# ==================== HELPERS ====================
def validate_ton_wallet(address: str) -> bool:
    pattern1 = r'^[UE][Qf][a-zA-Z0-9_-]{46}$'
    pattern2 = r'^0:[a-fA-F0-9]{64}$'
    return bool(re.match(pattern1, address)) or bool(re.match(pattern2, address))

async def delete_messages(chat_id: int, message_ids: list):
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id, msg_id)
        except:
            pass

# ==================== USER HANDLERS ====================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    
    if user:
        if user["status"] == "rejected":
            await message.answer("К сожалению, ваша заявка была отклонена. Повторная подача невозможна.")
            return
        elif user["status"] == "banned":
            await message.answer("Вы были забанены администратором.")
            return
        elif user["status"] == "approved":
            await message.answer("Добро пожаловать!", reply_markup=get_main_menu())
            return
        elif user["status"] == "pending":
            await message.answer("Ваша заявка уже находится на рассмотрении.")
            return
    
    await message.answer(
        "Приветствую! Чтобы вступить в команду, необходимо подать заявку",
        reply_markup=get_start_keyboard()
    )

@router.callback_query(F.data == "apply")
async def start_application(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Откуда вы узнали о команде?")
    await state.set_state(ApplicationForm.source)
    await state.update_data(messages=[callback.message.message_id])

@router.message(ApplicationForm.source)
async def process_source(message: Message, state: FSMContext):
    data = await state.get_data()
    messages = data.get("messages", [])
    messages.extend([message.message_id])
    
    await state.update_data(source=message.text, messages=messages)
    msg = await message.answer("Какой у вас опыт в данной сфере?")
    messages.append(msg.message_id)
    await state.update_data(messages=messages)
    await state.set_state(ApplicationForm.experience)

@router.message(ApplicationForm.experience)
async def process_experience(message: Message, state: FSMContext):
    data = await state.get_data()
    messages = data.get("messages", [])
    messages.append(message.message_id)
    
    await state.update_data(experience=message.text, messages=messages)
    msg = await message.answer("Сколько времени вы готовы уделять работе?")
    messages.append(msg.message_id)
    await state.update_data(messages=messages)
    await state.set_state(ApplicationForm.time)

@router.message(ApplicationForm.time)
async def process_time(message: Message, state: FSMContext):
    data = await state.get_data()
    messages = data.get("messages", [])
    messages.append(message.message_id)
    
    await state.update_data(time=message.text, messages=messages)
    msg = await message.answer("Почему мы должны взять вас в команду?")
    messages.append(msg.message_id)
    await state.update_data(messages=messages)
    await state.set_state(ApplicationForm.why)

@router.message(ApplicationForm.why)
async def process_why(message: Message, state: FSMContext):
    data = await state.get_data()
    messages = data.get("messages", [])
    messages.append(message.message_id)
    
    await state.update_data(why=message.text, messages=messages)
    
    summary = f"""Откуда вы узнали о команде
 └ {data['source']}

Какой у вас опыт в данной сфере
 └ {data['experience']}

Сколько времени вы готовы уделять работе
 └ {data['time']}

Почему мы должны взять вас в команду
 └ {message.text}"""
    
    msg = await message.answer(summary, reply_markup=get_confirm_keyboard())
    messages.append(msg.message_id)
    await state.update_data(messages=messages)
    await state.set_state(ApplicationForm.confirm)

@router.callback_query(F.data == "submit", ApplicationForm.confirm)
async def submit_application(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    messages = data.get("messages", [])
    
    await delete_messages(callback.message.chat.id, messages)
    
    answers = {
        "Откуда вы узнали о команде": data["source"],
        "Какой у вас опыт в данной сфере": data["experience"],
        "Сколько времени вы готовы уделять работе": data["time"],
        "Почему мы должны взять вас в команду": data["why"]
    }
    
    await save_application(
        callback.from_user.id,
        callback.from_user.username or "",
        answers
    )
    
    application_text = f"""📨 НОВАЯ ЗАЯВКА

👤 Пользователь: @{callback.from_user.username or 'no_username'}
🆔 ID: {callback.from_user.id}

━━━━━━━━━━━━━━━━
Откуда вы узнали о команде: {data['source']}
Какой у вас опыт в данной сфере: {data['experience']}
Сколько времени вы готовы уделять работе: {data['time']}
Почему мы должны взять вас в команду: {data['why']}"""
    
    await bot.send_message(
        ADMIN_GROUP_ID,
        application_text,
        reply_markup=get_admin_application_keyboard(callback.from_user.id)
    )
    
    await callback.message.answer("Ваша заявка отправлена на рассмотрение!")
    await state.clear()

@router.callback_query(F.data == "restart", ApplicationForm.confirm)
async def restart_application(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    messages = data.get("messages", [])
    await delete_messages(callback.message.chat.id, messages)
    
    msg = await callback.message.answer("Откуда вы узнали о команде?")
    await state.set_state(ApplicationForm.source)
    await state.update_data(messages=[msg.message_id])

@router.message(F.text == "Мой профиль")
async def show_profile(message: Message):
    user = await get_user(message.from_user.id)
    
    if not user or user["status"] != "approved":
        await message.answer("У вас нет доступа к этому разделу.")
        return
    
    profile_text = f"""🗃️ Информация
 └ ID: {user['user_id']}
 └ Ник: {user['nickname'] or 'не установлен'}
 └ Процент: {user['percent']}%

📋 Статистика
 └ Профитов: {user['profits_count']}
 └ Сумма Профитов: {user['profits_sum']}$

💰 Кошелек для выплат
 └ {user['wallet'] or 'не привязан'}"""
    
    await message.answer(profile_text, reply_markup=get_profile_keyboard())

@router.callback_query(F.data == "change_nick")
async def change_nick(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришлите новый ник")
    await state.set_state(ChangeNick.waiting_nick)
    await state.update_data(profile_msg_id=callback.message.message_id)

@router.message(ChangeNick.waiting_nick)
async def process_new_nick(message: Message, state: FSMContext):
    await update_nickname(message.from_user.id, message.text)
    
    data = await state.get_data()
    await delete_messages(message.chat.id, [data.get("profile_msg_id"), message.message_id])
    
    await state.clear()
    await show_profile(message)

@router.callback_query(F.data == "bind_wallet")
async def bind_wallet(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Пришлите свой кошелек в сети TON",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BindWallet.waiting_wallet)

@router.message(BindWallet.waiting_wallet)
async def process_wallet(message: Message, state: FSMContext):
    if not validate_ton_wallet(message.text):
        await message.answer(
            "Неверный формат TON кошелька. Попробуйте снова.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await update_wallet(message.from_user.id, message.text)
    await message.answer("Кошелек успешно привязан", reply_markup=get_back_keyboard())
    await state.clear()

@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer("Отменено")

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    await callback.message.delete()
    user = await get_user(callback.from_user.id)
    
    profile_text = f"""🗃️ Информация
 └ ID: {user['user_id']}
 └ Ник: {user['nickname'] or 'не установлен'}
 └ Процент: {user['percent']}%

📋 Статистика
 └ Профитов: {user['profits_count']}
 └ Сумма Профитов: {user['profits_sum']}$

💰 Кошелек для выплат
 └ {user['wallet'] or 'не привязан'}"""
    
    await callback.message.answer(profile_text, reply_markup=get_profile_keyboard())

@router.message(F.text == "Ресурсы")
async def show_resources(message: Message):
    user = await get_user(message.from_user.id)
    
    if not user or user["status"] != "approved":
        await message.answer("У вас нет доступа к этому разделу.")
        return
    
    await message.answer("Ресурсы команды", reply_markup=get_resources_keyboard())

# ==================== ADMIN HANDLERS ====================
@router.message(Command("admin"))
async def admin_panel_cmd(message: Message):
    if not await is_admin(message.from_user.id):
        return
    
    try:
        await message.delete()
    except:
        pass
    
    await bot.send_message(
        message.chat.id,
        "🎛 АДМИН-ПАНЕЛЬ\n\nВыберите действие:",
        reply_markup=get_admin_panel_keyboard()
    )

@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    await callback.message.edit_text(
        "🎛 АДМИН-ПАНЕЛЬ\n\nВыберите действие:",
        reply_markup=get_admin_panel_keyboard()
    )

@router.callback_query(F.data == "admin_search")
async def admin_search_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    await callback.message.edit_text(
        "🔍 Поиск пользователя\n\nОтправьте username (с @ или без) или user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
        ])
    )
    await state.set_state(AdminSearch.waiting_search)

@router.message(AdminSearch.waiting_search)
async def admin_search_process(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    search_term = message.text.strip()
    
    if search_term.isdigit():
        user = await get_user(int(search_term))
    else:
        user = await find_user_by_username(search_term)
    
    if not user:
        await message.answer(
            "❌ Пользователь не найден",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
        return
    
    status_emoji = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌",
        "banned": "🚫"
    }
    
    user_info = f"""👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ

🆔 ID: {user['user_id']}
👤 Username: @{user['username'] or 'не установлен'}
✏️ Ник: {user['nickname'] or 'не установлен'}
{status_emoji.get(user['status'], '❓')} Статус: {user['status']}
📊 Процент: {user['percent']}%
📈 Профитов: {user['profits_count']}
💰 Сумма: {user['profits_sum']}$
💳 Кошелек: {user['wallet'] or 'не привязан'}"""
    
    await message.answer(
        user_info,
        reply_markup=get_admin_user_keyboard(user['user_id'])
    )
    await state.clear()

# ==================== BROADCAST ====================
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    await callback.message.edit_text(
        "📢 РАССЫЛКИ\n\nВыберите тип рассылки:",
        reply_markup=get_broadcast_keyboard()
    )

@router.callback_query(F.data == "broadcast_all")
async def broadcast_all_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    await callback.message.edit_text(
        "📣 РАССЫЛКА ВСЕМ УЧАСТНИКАМ\n\n"
        "Отправьте сообщение для рассылки.\n"
        "Можно отправить текст, фото, видео или документ.\n\n"
        "💡 Если отправите медиа, добавьте подпись к нему.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_broadcast")]
        ])
    )
    await state.set_state(BroadcastAll.waiting_message)

@router.message(BroadcastAll.waiting_message)
async def broadcast_all_process(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    users = await get_all_approved_users()
    
    if not users:
        await message.answer("❌ Нет пользователей для рассылки")
        await state.clear()
        return
    
    success = 0
    failed = 0
    sent_message_ids = []
    content_type = "text"
    content = message.text or message.caption or ""
    
    status_msg = await message.answer(f"📤 Отправка... 0/{len(users)}")
    
    for i, user in enumerate(users, 1):
        try:
            sent_msg = None
            if message.text:
                content_type = "text"
                sent_msg = await bot.send_message(user['user_id'], message.text)
            elif message.photo:
                content_type = "photo"
                sent_msg = await bot.send_photo(
                    user['user_id'],
                    message.photo[-1].file_id,
                    caption=message.caption
                )
            elif message.video:
                content_type = "video"
                sent_msg = await bot.send_video(
                    user['user_id'],
                    message.video.file_id,
                    caption=message.caption
                )
            elif message.document:
                content_type = "document"
                sent_msg = await bot.send_document(
                    user['user_id'],
                    message.document.file_id,
                    caption=message.caption
                )
            
            if sent_msg:
                sent_message_ids.append(f"{user['user_id']}:{sent_msg.message_id}")
            success += 1
        except:
            failed += 1
        
        if i % 10 == 0:
            await status_msg.edit_text(f"📤 Отправка... {i}/{len(users)}")
        
        await asyncio.sleep(0.05)
    
    if sent_message_ids:
        await save_broadcast(sent_message_ids, content_type, content[:200])
    
    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}",
        reply_markup=get_admin_panel_keyboard()
    )
    await state.clear()

@router.callback_query(F.data == "broadcast_one")
async def broadcast_one_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    await callback.message.edit_text(
        "👤 РАССЫЛКА ОДНОМУ ПОЛЬЗОВАТЕЛЮ\n\n"
        "Отправьте username (с @ или без) или user_id пользователя:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_broadcast")]
        ])
    )
    await state.set_state(BroadcastOne.waiting_user)

@router.message(BroadcastOne.waiting_user)
async def broadcast_one_user(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    search_term = message.text.strip()
    
    if search_term.isdigit():
        user = await get_user(int(search_term))
    else:
        user = await find_user_by_username(search_term)
    
    if not user:
        await message.answer(
            "❌ Пользователь не найден",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
        return
    
    await state.update_data(target_user_id=user['user_id'])
    await message.answer(
        f"✅ Найден: @{user['username']} (ID: {user['user_id']})\n\n"
        f"Теперь отправьте сообщение для этого пользователя.\n"
        f"Можно отправить текст, фото, видео или документ.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_broadcast")]
        ])
    )
    await state.set_state(BroadcastOne.waiting_message)

@router.message(BroadcastOne.waiting_message)
async def broadcast_one_send(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    try:
        if message.text:
            await bot.send_message(target_user_id, message.text)
        elif message.photo:
            await bot.send_photo(
                target_user_id,
                message.photo[-1].file_id,
                caption=message.caption
            )
        elif message.video:
            await bot.send_video(
                target_user_id,
                message.video.file_id,
                caption=message.caption
            )
        elif message.document:
            await bot.send_document(
                target_user_id,
                message.document.file_id,
                caption=message.caption
            )
        
        await message.answer(
            "✅ Сообщение успешно отправлено!",
            reply_markup=get_admin_panel_keyboard()
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка отправки: {str(e)}",
            reply_markup=get_admin_panel_keyboard()
        )
    
    await state.clear()

# ==================== DELETE BROADCASTS ====================
@router.callback_query(F.data == "delete_broadcast_menu")
async def delete_broadcast_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    await callback.message.edit_text(
        "🗑 УДАЛЕНИЕ РАССЫЛОК\n\nВыберите действие:",
        reply_markup=get_delete_broadcast_keyboard()
    )

@router.callback_query(F.data == "delete_one_broadcast")
async def delete_one_broadcast_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    broadcasts = await get_all_broadcasts()
    
    if not broadcasts:
        await callback.answer("📭 Нет сохранённых рассылок", show_alert=True)
        return
    
    keyboard = []
    for broadcast in broadcasts[:10]:
        preview = broadcast['content'][:30] + "..." if len(broadcast['content']) > 30 else broadcast['content']
        date = broadcast['created_at'][:16]
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"📅 {date} | {broadcast['content_type']} | {preview}",
                callback_data=f"delete_br_{broadcast['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="delete_broadcast_menu")])
    
    await callback.message.edit_text(
        "📋 ВЫБЕРИТЕ РАССЫЛКУ ДЛЯ УДАЛЕНИЯ\n\n"
        "Нажмите на рассылку, чтобы удалить её сообщения у всех пользователей:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("delete_br_"))
async def delete_broadcast_confirm(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    broadcast_id = int(callback.data.split("_")[2])
    broadcasts = await get_all_broadcasts()
    broadcast = next((b for b in broadcasts if b['id'] == broadcast_id), None)
    
    if not broadcast:
        await callback.answer("❌ Рассылка не найдена", show_alert=True)
        return
    
    deleted = 0
    failed = 0
    
    status_msg = await callback.message.edit_text(
        f"🗑 Удаление рассылки...\n\nОбработано: 0/{len(broadcast['message_ids'])}"
    )
    
    for i, msg_data in enumerate(broadcast['message_ids'], 1):
        try:
            user_id, msg_id = map(int, msg_data.split(':'))
            await bot.delete_message(user_id, msg_id)
            deleted += 1
        except:
            failed += 1
        
        if i % 10 == 0:
            await status_msg.edit_text(
                f"🗑 Удаление рассылки...\n\nОбработано: {i}/{len(broadcast['message_ids'])}"
            )
        
        await asyncio.sleep(0.05)
    
    await delete_broadcast_by_id(broadcast_id)
    
    await status_msg.edit_text(
        f"✅ Рассылка удалена!\n\n"
        f"✅ Удалено: {deleted}\n"
        f"❌ Ошибок: {failed}",
        reply_markup=get_admin_panel_keyboard()
    )

@router.callback_query(F.data == "delete_all_broadcasts_confirm")
async def delete_all_broadcasts_confirm(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    broadcasts = await get_all_broadcasts()
    
    if not broadcasts:
        await callback.answer("📭 Нет рассылок для удаления", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить все", callback_data="confirm_delete_all")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="delete_broadcast_menu")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ ПОДТВЕРЖДЕНИЕ\n\n"
        f"Вы уверены, что хотите удалить ВСЕ рассылки?\n\n"
        f"📊 Будет удалено рассылок: {len(broadcasts)}\n"
        f"📬 Сообщений: {sum(len(b['message_ids']) for b in broadcasts)}\n\n"
        f"⚠️ Это действие нельзя отменить!",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "confirm_delete_all")
async def delete_all_broadcasts_process(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    broadcasts = await get_all_broadcasts()
    
    total_messages = sum(len(b['message_ids']) for b in broadcasts)
    deleted = 0
    failed = 0
    
    status_msg = await callback.message.edit_text(
        f"🗑 Удаление всех рассылок...\n\nОбработано: 0/{total_messages}"
    )
    
    processed = 0
    for broadcast in broadcasts:
        for msg_data in broadcast['message_ids']:
            try:
                user_id, msg_id = map(int, msg_data.split(':'))
                await bot.delete_message(user_id, msg_id)
                deleted += 1
            except:
                failed += 1
            
            processed += 1
            if processed % 20 == 0:
                await status_msg.edit_text(
                    f"🗑 Удаление всех рассылок...\n\nОбработано: {processed}/{total_messages}"
                )
            
            await asyncio.sleep(0.05)
    
    await delete_all_broadcasts()
    
    await status_msg.edit_text(
        f"✅ Все рассылки удалены!\n\n"
        f"📊 Удалено рассылок: {len(broadcasts)}\n"
        f"✅ Удалено сообщений: {deleted}\n"
        f"❌ Ошибок: {failed}",
        reply_markup=get_admin_panel_keyboard()
    )

# ==================== ADMIN MANAGEMENT ====================
@router.callback_query(F.data == "admin_manage_admins")
async def admin_manage_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Только главный админ может управлять админами!")
        return
    
    await callback.message.edit_text(
        "🛡️ УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ\n\nВыберите действие:",
        reply_markup=get_admin_manage_keyboard()
    )

@router.callback_query(F.data == "add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Только главный админ может добавлять админов!")
        return
    
    await callback.message.edit_text(
        "➕ ДОБАВИТЬ АДМИНИСТРАТОРА\n\nОтправьте user_id нового администратора:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_manage_admins")]
        ])
    )
    await state.set_state(AddAdmin.waiting_id)

@router.message(AddAdmin.waiting_id)
async def add_admin_process(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        admin_id = int(message.text.strip())
        
        if admin_id in ADMIN_IDS:
            await message.answer("❌ Этот пользователь уже главный админ")
            await state.clear()
            return
        
        admins = await get_all_admins()
        if admin_id in admins:
            await message.answer("❌ Этот пользователь уже является админом")
            await state.clear()
            return
        
        await add_admin_to_db(admin_id)
        
        try:
            await bot.send_message(
                admin_id,
                "🛡️ Вы назначены администратором бота!\n\n"
                "Теперь у вас есть доступ к админ-панели.\n"
                "Используйте команду /admin для управления."
            )
        except:
            pass
        
        await message.answer(
            f"✅ Администратор добавлен!\nID: {admin_id}",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат ID. Отправьте числовой ID пользователя.")

@router.callback_query(F.data == "remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Только главный админ может удалять админов!")
        return
    
    await callback.message.edit_text(
        "➖ УДАЛИТЬ АДМИНИСТРАТОРА\n\nОтправьте user_id администратора для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_manage_admins")]
        ])
    )
    await state.set_state(RemoveAdmin.waiting_id)

@router.message(RemoveAdmin.waiting_id)
async def remove_admin_process(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        admin_id = int(message.text.strip())
        
        if admin_id in ADMIN_IDS:
            await message.answer("❌ Нельзя удалить главного админа")
            await state.clear()
            return
        
        admins = await get_all_admins()
        if admin_id not in admins:
            await message.answer("❌ Этот пользователь не является админом")
            await state.clear()
            return
        
        await remove_admin_from_db(admin_id)
        
        try:
            await bot.send_message(admin_id, "⚠️ Вы сняты с должности администратора.")
        except:
            pass
        
        await message.answer(
            f"✅ Администратор удалён!\nID: {admin_id}",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат ID. Отправьте числовой ID пользователя.")

@router.callback_query(F.data == "list_admins")
async def list_admins(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔️ Только главный админ может видеть список админов!")
        return
    
    admins = await get_all_admins()
    
    admin_text = "👥 СПИСОК АДМИНИСТРАТОРОВ\n\n"
    admin_text += "🔴 Главные администраторы:\n"
    for admin_id in ADMIN_IDS:
        admin_text += f"  └ ID: {admin_id}\n"
    
    if admins:
        admin_text += "\n🟢 Дополнительные администраторы:\n"
        for admin_id in admins:
            if admin_id not in ADMIN_IDS:
                admin_text += f"  └ ID: {admin_id}\n"
    else:
        admin_text += "\n🟢 Дополнительных админов нет"
    
    await callback.message.edit_text(
        admin_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_manage_admins")]
        ])
    )

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE status = 'pending'") as cursor:
            pending = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE status = 'approved'") as cursor:
            approved = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE status = 'rejected'") as cursor:
            rejected = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE status = 'banned'") as cursor:
            banned = (await cursor.fetchone())[0]
        async with db.execute("SELECT SUM(profits_sum) FROM users WHERE status = 'approved'") as cursor:
            total_profits = (await cursor.fetchone())[0] or 0
    
    stats_text = f"""📊 СТАТИСТИКА

⏳ Ожидают: {pending}
✅ Одобрено: {approved}
❌ Отклонено: {rejected}
🚫 Забанено: {banned}

💰 Общая сумма профитов: {total_profits}$"""
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
        ])
    )

@router.callback_query(F.data.startswith("approve_"))
async def approve_application(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    user_id = int(callback.data.split("_")[1])
    await update_user_status(user_id, "approved")
    
    await bot.send_message(user_id, "Поздравляю! Ваша заявка принята", reply_markup=get_main_menu())
    await callback.message.edit_text(callback.message.text + "\n\n✅ ОДОБРЕНО")
    await callback.answer("Заявка одобрена")

@router.callback_query(F.data.startswith("reject_"))
async def reject_application(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    user_id = int(callback.data.split("_")[1])
    await update_user_status(user_id, "rejected")
    
    await bot.send_message(user_id, "К сожалению, ваша заявка отклонена")
    await callback.message.edit_text(callback.message.text + "\n\n❌ ОТКЛОНЕНО")
    await callback.answer("Заявка отклонена")

@router.callback_query(F.data.startswith("ban_"))
async def ban_user(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    user_id = int(callback.data.split("_")[1])
    await update_user_status(user_id, "banned")
    
    try:
        await bot.send_message(user_id, "Вы были забанены администратором.")
    except:
        pass
    
    await callback.answer("✅ Пользователь забанен", show_alert=True)
    await callback.message.edit_text(callback.message.text + "\n\n🚫 ЗАБАНЕН")

@router.callback_query(F.data.startswith("change_percent_"))
async def change_percent_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    user_id = int(callback.data.split("_")[2])
    await callback.message.answer("📊 Введите новый процент (число от 0 до 100):")
    await state.set_state(AdminChangePercent.waiting_percent)
    await state.update_data(target_user_id=user_id)

@router.message(AdminChangePercent.waiting_percent)
async def process_percent(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    try:
        percent = int(message.text)
        if percent < 0 or percent > 100:
            await message.answer("❌ Процент должен быть от 0 до 100")
            return
        
        data = await state.get_data()
        target_user_id = data["target_user_id"]
        
        await update_percent(target_user_id, percent)
        
        try:
            await bot.send_message(
                target_user_id,
                f"🌪 Поздравляем! Ваш процент поднят\n └ Процент: {percent}%"
            )
        except:
            pass
        
        await message.answer(
            f"✅ Процент изменен на {percent}%",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.callback_query(F.data.startswith("add_profit_"))
async def add_profit_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    user_id = int(callback.data.split("_")[2])
    await callback.message.answer("➕ Введите сумму профита ($):")
    await state.set_state(AdminAddProfit.waiting_amount)
    await state.update_data(target_user_id=user_id)

@router.message(AdminAddProfit.waiting_amount)
async def process_add_profit(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной")
            return
        
        data = await state.get_data()
        target_user_id = data["target_user_id"]
        
        await add_profit(target_user_id, amount)
        
        try:
            await bot.send_message(
                target_user_id,
                f"🌪 Поздравляем! Вы совершили профит\n └ Сумма: {amount}$"
            )
        except:
            pass
        
        await message.answer(
            f"✅ Профит ${amount} начислен",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректную сумму")

@router.callback_query(F.data.startswith("remove_profit_"))
async def remove_profit_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!")
        return
    
    user_id = int(callback.data.split("_")[2])
    await callback.message.answer("➖ Введите сумму для удаления ($):")
    await state.set_state(AdminRemoveProfit.waiting_amount)
    await state.update_data(target_user_id=user_id)

@router.message(AdminRemoveProfit.waiting_amount)
async def process_remove_profit(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной")
            return
        
        data = await state.get_data()
        await remove_profit(data["target_user_id"], amount)
        await message.answer(
            f"✅ Профит ${amount} удален",
            reply_markup=get_admin_panel_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректную сумму")

# ==================== MAIN ====================
async def main():
    await init_db()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
