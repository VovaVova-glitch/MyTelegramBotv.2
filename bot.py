import asyncio
import sqlite3
import re
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import random
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand
)
from aiogram.filters import Command

from config import TOKEN

bot = Bot(token=TOKEN, timeout=30)
dp = Dispatcher()

user_state = {}
    
# ---------- UI ----------
reminders_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Включить", callback_data="reminders_on"),
        InlineKeyboardButton(text="❌ Выключить", callback_data="reminders_off")
    ]
])
reset_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Да", callback_data="reset_yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="reset_no")
    ]
])
suggest_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text = "✅ Сделал", callback_data="save_suggest")
    ]
])
async def check_missed_days():
    db = get_db()
    cur = db.cursor()
    
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    
    cur.execute("""
        SELECT DISTINCT u.user_id FROM users u 
        JOIN workouts w ON u.user_id = w.user_id 
        WHERE w.date >= ? AND u.reminders_enabled = 1
    """, ((datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),))
    
    users = [row[0] for row in cur.fetchall()]
    
    for uid in users:
        cur.execute("SELECT 1 FROM workouts WHERE user_id=? AND date=?", (uid, yesterday))
        if not cur.fetchone():
            messages = [
                "💪 Вчера пропустил тренировку?\nСегодня новый день! 🔥 /suggest",
                "😴 Отдохнул вчера? Вернись в строй! /today", 
                "⚡ Быстрый тест: /suggest → ✅ Сделал!"
            ]
            await bot.send_message(uid, random.choice(messages))
    
    db.close()
    print("✅ Проверка пропусков завершена")

# ---------- DB ----------
def get_db():
    return sqlite3.connect("sportbot.db")


def init_db():
    db = get_db()
    cur = db.cursor()

    # Создаем users БЕЗ reminders_enabled сначала
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        height INTEGER,
        gender TEXT,
        goal TEXT,
        weekly_goal INTEGER,
        current_weight REAL DEFAULT 0
    )
    """)

    # ПРОВЕРЯЕМ и добавляем колонку ТОЛЬКО если её нет
    cur.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cur.fetchall()]
    
    if 'reminders_enabled' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN reminders_enabled INTEGER DEFAULT 1")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS weights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        weight REAL,
        date TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        date TEXT
    )
    """)

    db.commit()
    db.close()

# ---------- UTILS ----------
def calc_calories(text: str) -> int:
    text = text.lower()

    m = re.search(r'(\d+)\s*(мин|минут)', text)
    if m:
        return int(m.group(1)) * 8  # ~8 ккал в минуту

    if 'x' in text or 'х' in text:
        return 30

    return 0


def calculate_streak(dates):
    used = set(dates)
    streak = 0
    today = datetime.now().date()

    while True:
        day = today - timedelta(days=streak)
        if day.strftime("%Y-%m-%d") in used:
            streak += 1
        else:
            break
    return streak

# ---------- RESET ----------
@dp.message(Command("reset"))
async def reset_profile(message: Message):
    await message.answer(
        "Удалить профиль и все данные?",
        reply_markup=reset_kb
    )


@dp.callback_query(lambda c: c.data == "reset_yes")
async def reset_yes(callback: CallbackQuery):
    uid = callback.from_user.id
    db = get_db()
    cur = db.cursor()

    cur.execute("DELETE FROM workouts WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM weights WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM users WHERE user_id=?", (uid,))

    db.commit()
    db.close()

    await callback.message.edit_text("Профиль полностью удалён.")


@dp.callback_query(lambda c: c.data == "reset_no")
async def reset_no(callback: CallbackQuery):
    await callback.message.edit_text("Отмена.")

# ---------- COMMANDS ----------
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "SportBot\n\n"
        "/profile — профиль\n"
        "/edit_profile — изменить профиль\n"
        "/workout — записать тренировку\n"
        "/today — сегодня\n"
        "/stats — статистика\n"
        "/weight — вес\n"
        "/reset — удалить всё\n"
        "/weight_stats — статистика веса\n"
        "/suggest — предложить тренировку\n"
        "/set_goal — установить цель на неделю\n"
        "/reminders — напоминания\n"
        "/goal — показать цель на неделю"
    )


@dp.message(Command("profile"))
async def profile(message: Message):
    uid = message.from_user.id
    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT height, gender, goal, current_weight FROM users WHERE user_id=?",
        (uid,)
    )
    profile_row = cur.fetchone()
    db.close()

    if not profile_row or not profile_row[0]:
        user_state[uid] = "profile"
        await message.answer(
            "Введи профиль:\n"
            "Рост, пол, цель\n"
            "Пример: 165, м, набрать массу"
        )
        return

    h, g, goal, current_weight = profile_row  # ← 4 переменные!
    weight_text = f"{current_weight:.1f} кг" if current_weight and current_weight > 0 else "не указан"

    await message.answer(
        f"👤 Профиль\n"
        f"Рост: {h} см\n"
        f"Пол: {g}\n"
        f"Вес: {weight_text}\n"
        f"Цель: {goal}"
    )


@dp.message(Command("edit_profile")) 
async def edit_profile(message: Message):
    user_state[message.from_user.id] = "profile"
    await message.answer(
        "Рост, пол, цель\n"
        "Пример: 170, ж, похудеть"
    )

@dp.message(Command("set_goal"))
async def set_goal(message: Message):
    user_state[message.from_user.id] = "weekly_goal"
    await message.answer(
        "Введи цель на неделю (сколько дней тренировок)\n"
        "Пример: 4"
    )

@dp.message(Command("goal"))
async def goal(message: Message):
    uid = message.from_user.id
    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT weekly_goal FROM users WHERE user_id=?",
        (uid,)
    )
    row = cur.fetchone()

    if not row or not row[0] or row[0] < 1:
        db.close()
        await message.answer("Цель не задана. Используй /set_goal")
        return

    weekly_goal = int(row[0])

    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    cur.execute(
        "SELECT COUNT(DISTINCT date) FROM workouts WHERE user_id=? AND date>=?",
        (uid, week_ago)
    )
    done = cur.fetchone()[0] or 0
    db.close()

    progress = min(int(done / weekly_goal * 100), 100)

    blocks_total = 10
    blocks_done = int(progress / 10)
    bar = "█" * blocks_done + "░" * (blocks_total - blocks_done)

    status = "🔥 Отлично" if done >= weekly_goal else "⏳ Продолжай"

    await message.answer(
        f"🎯 Цель недели: {weekly_goal}\n"
        f"✅ Выполнено: {done}\n"
        f"Прогресс: {progress}% {bar}\n"
        f"{status}"
    )

@dp.message(Command("reminders"))
async def reminders(message: Message):
    uid = message.from_user.id
    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT reminders_enabled FROM users WHERE user_id=?",
        (uid,))
    row = cur.fetchone()
    status = bool(row[0]) if row else True

    status_text = "🔔 Включены" if status else "🔕 Выключены"
    

    await message.answer(
        f"Напоминания при пропуске дня:\n\n"
        f"Статус: {status_text}\n"
        f"Выбери действие:",
        reply_markup=reminders_kb
    )
    db.close()

@dp.callback_query(lambda c: c.data == "reminders_on")
async def reminders_on(callback: CallbackQuery):
    uid = callback.from_user.id
    db = get_db()
    cur = db.cursor()
    
    cur.execute(
        "UPDATE users SET reminders_enabled=1 WHERE user_id=?",
        (uid,)
    )
    db.commit()
    db.close()
    
    await callback.message.edit_text(
        "🔔 Напоминания ВКЛЮЧЕНЫ!\n\n"
        "Получать мотивацию каждый день при пропуске тренировки? 💪"
    )
    await callback.answer("Включено!")

@dp.callback_query(lambda c: c.data == "reminders_off")
async def reminders_off(callback: CallbackQuery):
    uid = callback.from_user.id
    db = get_db()
    cur = db.cursor()
    
    cur.execute(
        "UPDATE users SET reminders_enabled=0 WHERE user_id=?",
        (uid,)
    )
    db.commit()
    db.close()
    
    await callback.message.edit_text(
        "🔕 Напоминания ВЫКЛЮЧЕНЫ\n\n"
        "Ты босс, тренируйся по настроению! 😎"
    )
    await callback.answer("Выключено!")
@dp.message(Command("suggest"))
async def suggest(message: Message):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT goal FROM users WHERE user_id=?",
        (message.from_user.id,)
    )
    row = cur.fetchone()
    db.close()
    if not row or not row[0]:
        await message.answer("Сначала установи цель в профиле (/profile).")
        return
    goal = row[0].lower()
    if "наб" in goal:
        text = (
            "💪 Тренировка на набор:\n"
            "• Отжимания 4x15–20\n"
            "• Приседания 4x25\n"
            "• Выпады 3x12\n"
            "• Планка 3x40 сек"
        )
    elif "похуд" in goal or "суш" in goal:
        text = (
            "🔥 Тренировка на жиросжигание:\n"
            "• Бег 20–30 минут\n"
            "• Бёрпи 3x12\n"
            "• Прыжки 3x40 сек\n"
            "• Планка 3x30 сек"
        )
    else:
        text = (
            "🏋️ Универсальная тренировка:\n"
            "• Отжимания 3x15\n"
            "• Приседания 3x20\n"
            "• Планка 3x30 сек"
        )

    await message.answer(text, reply_markup=suggest_kb)
@dp.callback_query(lambda c: c.data == "save_suggest")
async def save_suggest(callback: CallbackQuery):
    uid = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    workout_text = callback.message.text.split("\n", 1)[1]

    db = get_db()
    cur = db.cursor()

    # если сегодня уже есть тренировка — не дублируем
    cur.execute(
        "SELECT 1 FROM workouts WHERE user_id=? AND date=? LIMIT 1",
        (uid, today)
    )
    exists = cur.fetchone()

    if not exists:
        for line in workout_text.split("\n"):
            if line.startswith("•"):
                cur.execute(
                    "INSERT INTO workouts (user_id, text, date) VALUES (?, ?, ?)",
                    (uid, line[2:], today)
                )

        db.commit()
        text = "✅ Тренировка сохранена\n🎯 День засчитан"
    else:
        text = "ℹ️ Сегодня тренировка уже была засчитана"

    db.close()

    await callback.message.edit_text(
        callback.message.text + "\n\n" + text
    )


@dp.message(Command("workout"))
async def workout(message: Message):
    user_state[message.from_user.id] = "workout"
    await message.answer(
        "Введи тренировку.\n"
        "Можно через запятую:\n"
        "Бег 30 минут, Отжимания 4x20"
    )


@dp.message(Command("weight"))
async def weight(message: Message):
    user_state[message.from_user.id] = "weight"
    await message.answer("Введи вес (кг)")


@dp.message(Command("weight_stats"))
async def weight_stats(message: Message):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT weight, date FROM weights WHERE user_id=? ORDER BY date DESC LIMIT 7",
        (message.from_user.id,)
    )
    rows = cur.fetchall()
    db.close()

    if not rows:
        await message.answer("Вес ещё не записывался.")
        return

    text = "⚖️ Вес (последние записи):\n"
    for w, d in rows:
        text += f"{d}: {w} кг\n"

    await message.answer(text)

# ---------- TODAY ----------
@dp.message(Command("today"))
async def today(message: Message):
    db = get_db()
    cur = db.cursor()

    today_date = datetime.now().strftime("%Y-%m-%d")
    cur.execute(
        "SELECT text FROM workouts WHERE user_id=? AND date=?",
        (message.from_user.id, today_date)
    )
    rows = cur.fetchall()
    db.close()

    if not rows:
        await message.answer("Сегодня тренировок нет.")
        return

    total_cal = sum(calc_calories(r[0]) for r in rows)
    text = "\n".join(f"• {r[0]}" for r in rows)

    await message.answer(
        f"🏋️ Сегодня:\n{text}\n\n🔥 ~{total_cal} ккал"
    )
@dp.message(Command("test_miss"))
async def test_miss(message: Message):
    await check_missed_days()
    await message.answer("🧪 Тест пропусков запущен!")
# ---------- STATS ----------
@dp.message(Command("stats"))
async def stats(message: Message):
    db = get_db()
    cur = db.cursor()
    uid = message.from_user.id

    cur.execute(
        "SELECT date, text FROM workouts WHERE user_id=? ORDER BY date DESC",
        (uid,)
    )
    rows = cur.fetchall()
    db.close()

    if not rows:
        await message.answer("Тренировок нет.")
        return

    dates = [d for d, _ in rows]
    streak = calculate_streak(dates)

    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

    total_cal = sum(calc_calories(t) for _, t in rows)
    week_cal = sum(calc_calories(t) for d, t in rows if d >= week_ago)

    text = (
        f"📊 Статистика\n"
        f"Тренировочных дней: {len(set(dates))}\n"
        f"Серия: {streak}\n"
        f"🔥 Калорий всего: ~{total_cal}\n"
        f"🔥 За 7 дней: ~{week_cal}\n\n"
        f"Последние:\n"
    )

    for d, t in rows[:5]:
        text += f"{d}: {t}\n"

    await message.answer(text)

# ---------- INPUT ----------
@dp.message()
async def handle_input(message: Message):
    if message.text.startswith("/"):
        return

    uid = message.from_user.id
    state = user_state.get(uid)

    if state == "weekly_goal":
        try:
            goal = int(message.text)
            db = get_db()
            cur = db.cursor()
            cur.execute(
                "UPDATE users SET weekly_goal=? WHERE user_id=?",
                (goal, uid)
            )
            db.commit()
            db.close()

            await message.answer("Цель недели сохранена.")
            user_state.pop(uid)
        except:
            await message.answer("Введи число.")
        return

    # WEIGHT
    if state == "weight":
        try:
            w = float(message.text)
            db = get_db()
            cur = db.cursor()
            cur.execute(
                "INSERT INTO weights (user_id, weight, date) VALUES (?, ?, ?)",
                (uid, w, datetime.now().strftime("%Y-%m-%d"))
            )

            cur.execute(
            "UPDATE users SET current_weight = ? WHERE user_id = ?",
            (w, uid)
            )
            db.commit()
            db.close()

            await message.answer("Вес сохранён.")
            user_state.pop(uid)
        except:
            await message.answer("Введи число.")
        return

    # PROFILE
    if state == "profile":
        try:
            h, g, goal = map(str.strip, message.text.split(",", 2))
            h = int(h)
            if g.lower() == "м":
                g += "ужской👨"
            elif g.lower() == "ж":
                g += "енский👩"
            db = get_db()
            cur = db.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO users (user_id, height, gender, goal)
                VALUES (?, ?, ?, ?)
                """,
                (uid, h, g.lower(), goal)
            )
            db.commit()
            db.close()

            await message.answer("Профиль сохранён.")
            user_state.pop(uid)
        except:
            await message.answer("Формат: 165, м, цель")


    # WORKOUT
    if state == "workout":
        exercises = [x.strip() for x in message.text.split(",") if x.strip()]
        db = get_db()
        cur = db.cursor()

        for ex in exercises:
            cur.execute(
                "INSERT INTO workouts (user_id, text, date) VALUES (?, ?, ?)",
                (uid, ex, datetime.now().strftime("%Y-%m-%d"))
            )

        db.commit()
        db.close()

        await message.answer(f"Сохранено: {len(exercises)}")
        user_state.pop(uid)


# ---------- RUN ----------
async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_missed_days, 'cron', hour=9, minute=0)  # 9:00 ежедневно
    scheduler.start()
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="edit_profile", description="Изменить профиль"),
        BotCommand(command="workout", description="Тренировка"),
        BotCommand(command="today", description="Сегодня"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="weight", description="Вес"),
        BotCommand(command="reset", description="Удалить всё"),
        BotCommand(command="weight_stats", description="Статистика веса"),
        BotCommand(command="suggest", description="Предложить трениовку"),
        BotCommand(command="set_goal", description="Установить цель на неделю"),
        BotCommand(command="goal", description="Показать цель на неделю"),
        BotCommand(command="reminders", description="Напоминания")
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
