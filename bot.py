import asyncio
from aiogram import F
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
main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📅 Today", callback_data="today"),
        InlineKeyboardButton(text="🎯 Цель", callback_data="goal"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    ]
])
reminders_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Увімкнути", callback_data="reminders_on"),
        InlineKeyboardButton(text="❌ Вимкнути", callback_data="reminders_off")
    ]
])
reset_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Так", callback_data="reset_yes"),
        InlineKeyboardButton(text="❌ Ні", callback_data="reset_no")
    ]
])
suggest_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text = "✅ Виконав", callback_data="suggest_done"),
        InlineKeyboardButton(text="🔁 Інша", callback_data="suggest_retry")
    ]
])
def generate_workout(goal: str) -> str:
    if "наб" in goal:
        return random.choice([
            "💪 Тренування на набір маси:\n"
            "• Відтискування 4x15–20\n"
            "• Присідання 4x25\n"
            "• Випади 3x12\n"
            "• Планка 3x40 сек",

            "💪 Тренування на набір маси:\n"
            "• Відтискування вузькі 4x12\n"
            "• Присідання з паузою 4x20\n"
            "• Ягодичний міст 3x20\n"
            "• Планка 3x45 сек"
        ])

    elif "схуд" in goal or "дієт" in goal:
        return random.choice([
            "🔥 Тренування на спалювання жиру:\n"
            "• Біг 20–30 хвилин\n"
            "• Бьорпі 3x12\n"
            "• Стрибки 3x40 сек\n"
            "• Планка 3x30 сек",

            "🔥 Тренування на спалювання жиру:\n"
            "• Jumping Jack 4x40 сек\n"
            "• Альпініст 3x30 сек\n"
            "• Присідання 3x25\n"
            "• Планка 3x35 сек"
        ])

    else:
        return random.choice([
            "🏋️ Універсальне тренування:\n"
            "• Відтискування 3x15\n"
            "• Присідання 3x20\n"
            "• Планка 3x30 сек",

            "🏋️ Універсальне тренування:\n"
            "• Відтискування 3x12\n"
            "• Випади 3x12\n"
            "• Велосипед 3x30 сек\n"
            "• Планка 3x40 сек"        
        ])
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
        await message.answer("Мета не задана. Використовуй /set_goal")
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

    status = "🔥 Чудово" if done >= weekly_goal else "⏳ Продовжуй"

    await message.answer(
        f"🎯 Мета тижня: {weekly_goal}\n"
        f"✅ Виконано: {done}\n"
        f"Прогрес: {progress}% {bar}\n"
        f"{status}"
    )    
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
        await message.answer("Сьогодні тренувань немає.")
        return

    total_cal = sum(calc_calories(r[0]) for r in rows)
    text = "\n".join(f"• {r[0]}" for r in rows)

    await message.answer(
        f"🏋️ Сьогодні:\n{text}\n\n🔥 ~{total_cal} ккал"
    )

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
            "Введи профіль:\n"
            "Зріст, стать, мета\n"
            "Приклад: 165, ч, набрати масу"
        )
        return

    h, g, goal, current_weight = profile_row  # ← 4 змінні!
    weight_text = f"{current_weight:.1f} кг" if current_weight and current_weight > 0 else "не вказана"

    await message.answer(
        f"👤 Профіль\n"
        f"Зріст: {h} см\n"
        f"Стать: {g}\n"
        f"Вага: {weight_text}\n"
        f"Мета: {goal}"
    )


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
                "💪 Вчора пропустив тренування?\nСьогодні новий день! 🔥 /suggest",
                "😴 Відпочив вчора? Повертайся до строю! /today", 
                "⚡ Швидкий тест: /suggest → ✅ Виконав!"
            ]
            await bot.send_message(uid, random.choice(messages))
    
    db.close()
    print("✅Перевірка пропущених днів виконана.")

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

    m = re.search(r'(\d+)\s*(хв|хвилин)', text)
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
        "Видалити профіль і всі дані?",
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

    await callback.message.edit_text("Профіль повністю видалено.")


@dp.callback_query(lambda c: c.data == "reset_no")
async def reset_no(callback: CallbackQuery):
    await callback.message.edit_text("Скасування.")

# ---------- COMMANDS ----------
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Выбери действие 👇",
        reply_markup=main_menu
    )

@dp.message(Command("edit_profile")) 
async def edit_profile(message: Message):
    user_state[message.from_user.id] = "profile"
    await message.answer(
        "Зріст, стать, мета\n"
        "Приклад: 170, ж, схуднути"
    )

@dp.message(Command("set_goal"))
async def set_goal(message: Message):
    user_state[message.from_user.id] = "weekly_goal"
    await message.answer(
        "Введи мету на тиждень (кількість днів тренувань)\n"
        "Приклад: 4"
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

    status_text = "🔔 Увімкнені" if status else "🔕 Вимкнені"
    

    await message.answer(
        f"Нагадування при пропуску дня:\n\n"
        f"Статус: {status_text}\n"
        f"Виберіть дію:",
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
        "🔔 Нагадування УВІМКНЕНІ!\n\n"
        "Отримувати мотивацію щодня при пропуску тренування? 💪"
    )
    await callback.answer("Увімкнено!")

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
        "🔕 Нагадування ВИМКНЕНІ\n\n"
        "Ти босс, тренуйся за настроєм! 😎"
    )
    await callback.answer("Вимкнено!")
@dp.message(Command("suggest"))
async def suggest(message: Message):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT goal FROM users WHERE user_id=?", (message.from_user.id,))
    row = cur.fetchone()
    db.close()

    if not row or not row[0]:
        await message.answer("Спочатку задай мету в профілі (/profile).")
        return

    text = generate_workout(row[0])
    await message.answer(text, reply_markup=suggest_kb)
@dp.callback_query(F.data == "suggest_retry")
async def suggest_retry(callback: CallbackQuery):
    await callback.message.delete()
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT goal FROM users WHERE user_id=?", (callback.from_user.id,))
    row = cur.fetchone()
    db.close()

    if not row or not row[0]:
        await callback.answer("Немає мети", show_alert=True)
        return

    text = generate_workout(row[0])
    
    await callback.message.answer(text, reply_markup=suggest_kb)
    await callback.answer()



@dp.callback_query(F.data == "suggest_done")
async def suggest_done(callback: CallbackQuery):
    await callback.message.delete()
    uid = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    workout_text = callback.message.text.split("\n", 1)[1]

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT 1 FROM workouts WHERE user_id=? AND date=?",
        (uid, today)
    )
    if cur.fetchone():
        db.close()
        await callback.answer("Сьогодні вже зараховано")
        return

    for line in workout_text.split("\n"):
        if line.startswith("•"):
            cur.execute(
                "INSERT INTO workouts (user_id, text, date) VALUES (?, ?, ?)",
                (uid, line[2:], today)
            )

    db.commit()
    db.close()

    await callback.message.edit_text(
        callback.message.text + "\n\n✅ Тренування збережено"
    )



@dp.message(Command("workout"))
async def workout(message: Message):
    user_state[message.from_user.id] = "workout"
    await message.answer(
        "Введи тренування.\n"
        "Можна через кому:\n"
        "Біг 30 хвилин, Відтискування 4x20"
    )


@dp.message(Command("weight"))
async def weight(message: Message):
    user_state[message.from_user.id] = "weight"
    await message.answer("Введи вагу (кг)")


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
        await message.answer("Вага ще не записувалася.")
        return

    text = "⚖️ Вага (останні записи):\n"
    for w, d in rows:
        text += f"{d}: {w} кг\n"

    await message.answer(text)

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
        await message.answer("Тренувань немає.")
        return

    dates = [d for d, _ in rows]
    streak = calculate_streak(dates)

    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

    total_cal = sum(calc_calories(t) for _, t in rows)
    week_cal = sum(calc_calories(t) for d, t in rows if d >= week_ago)

    text = (
        f"📊 Статистика\n"
        f"Днів тренування: {len(set(dates))}\n"
        f"Серія: {streak}\n"
        f"🔥 Калорій всього: ~{total_cal}\n"
        f"🔥 За 7 днів: ~{week_cal}\n\n"
        f"Останні:\n"
    )

    for d, t in rows[:5]:
        text += f"{d}: {t}\n"

    await message.answer(text)
@dp.callback_query(F.data == "today")
async def cb_today(call: CallbackQuery):
    await call.message.delete()
    await today(call.message)

@dp.callback_query(F.data == "goal")
async def cb_goal(call: CallbackQuery):
    await call.message.delete()
    await goal(call.message)

@dp.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    await call.message.delete()
    await profile(call.message)

# ---------- INPUT ----------
@dp.message()
async def handle_input(message: Message):

    uid = message.from_user.id
    state = user_state.get(uid)

    if state == "weekly_goal":
        try:
            goal = int(message.text)

            db = get_db()
            cur = db.cursor()

            cur.execute(
                """
                INSERT INTO users (user_id, weekly_goal)
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET weekly_goal=excluded.weekly_goal
                """,
                (uid, goal)
            )

            db.commit()
            db.close()

            await message.answer("Мета тижня збережена.")
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

            await message.answer("Вагу збережено.")
            user_state.pop(uid)
        except:
            await message.answer("Введи число.")
        return

    # PROFILE
    if state == "profile":
        try:
            h, g, goal = map(str.strip, message.text.split(",", 2))
            h = int(h)
            if g.lower() == "ч" or g.lower() == "ч":
                g += "оловік👨"
            elif g.lower() == "ж" or g.lower() == "ж":
                g += "інка👩"
            db = get_db()
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO users (user_id, height, gender, goal)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET
                    height = excluded.height,
                    gender = excluded.gender,
                    goal = excluded.goal

                """,
                (uid, h, g.lower(), goal)
            )
            db.commit()
            db.close()

            await message.answer("Профіль збережено.")
            user_state.pop(uid)
        except:
            await message.answer("Формат: 165, ч, мета")


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

        await message.answer(f"Збережено: {len(exercises)}")
        user_state.pop(uid)


# ---------- RUN ----------
async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_missed_days, 'cron', hour=9, minute=0)  # 9:00 кожноденно
    scheduler.start()
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск"),
        BotCommand(command="profile", description="Профіль"),
        BotCommand(command="edit_profile", description="Змінити профіль"),
        BotCommand(command="workout", description="Тренування"),
        BotCommand(command="today", description="Сьогодні"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="weight", description="Вага"),
        BotCommand(command="reset", description="Видалити все"),
        BotCommand(command="weight_stats", description="Статистика ваги"),
        BotCommand(command="suggest", description="Запропонувати тренування"),
        BotCommand(command="set_goal", description="Встановити мету на тиждень"),
        BotCommand(command="goal", description="Показати мету на тиждень"),
        BotCommand(command="reminders", description="Нагадування")
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
