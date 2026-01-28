# main.py
import asyncio
import os
import sqlite3
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))

# укажите ID групп (получите их по инструкции ниже)
GROUPS = {
    "sales": int(os.getenv("GROUP_SALES_ID", "0")),
    "support": int(os.getenv("GROUP_SUPPORT_ID", "0")),
    "delivery": int(os.getenv("GROUP_DELIVERY_ID", "0")),
}

WORK_START = time(7, 30)
WORK_END = time(18, 0)

THEMES = {
    "sales": "Продажи",
    "support": "Поддержка",
    "delivery": "Доставка",
}

DB_PATH = os.getenv("DB_PATH", "db.sqlite3")

def now_msk() -> datetime:
    return datetime.now(tz=TZ)

def is_work_time(dt: datetime) -> bool:
    t = dt.timetz().replace(tzinfo=None)
    return WORK_START <= t <= WORK_END

def theme_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продажи", callback_data="theme:sales")],
        [InlineKeyboardButton(text="Поддержка", callback_data="theme:support")],
        [InlineKeyboardButton(text="Доставка", callback_data="theme:delivery")],
    ])

# ---------- DB ----------
def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db_conn()
    cur = conn.cursor()
    # tickets
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_no INTEGER UNIQUE,
        client_id INTEGER NOT NULL,
        client_name TEXT,
        client_username TEXT,
        theme TEXT,
        group_id INTEGER,
        status TEXT NOT NULL,
        assignee_id INTEGER,
        assignee_name TEXT,
        created_at TEXT NOT NULL,
        closed_at TEXT,
        group_message_id INTEGER
    )""")
    # messages
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        ticket_no INTEGER,
        sender_type TEXT, -- client/operator/system
        sender_id INTEGER,
        sender_name TEXT,
        text TEXT,
        created_at TEXT
    )""")
    # pending (when client wrote first message, waiting for theme choice)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending(
        client_id INTEGER PRIMARY KEY,
        first_text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    # operators
    cur.execute("""
    CREATE TABLE IF NOT EXISTS operators(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_user_id INTEGER UNIQUE,
        full_name TEXT,
        username TEXT,
        group_id INTEGER,
        active INTEGER DEFAULT 1,
        last_assigned_at TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

def get_active_ticket(client_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE client_id=? AND status IN ('OPEN','IN_PROGRESS') ORDER BY id DESC LIMIT 1",
                (client_id,))
    row = cur.fetchone()
    conn.close()
    return row

def next_ticket_no() -> int:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(ticket_no), 1000) + 1 FROM tickets")
    n = int(cur.fetchone()[0])
    conn.close()
    return n

def save_pending(client_id: int, text: str):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO pending(client_id, first_text, created_at) VALUES (?,?,?)",
                (client_id, text, now_msk().isoformat()))
    conn.commit()
    conn.close()

def get_pending(client_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending WHERE client_id=?", (client_id,))
    row = cur.fetchone()
    conn.close()
    return row

def clear_pending(client_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM pending WHERE client_id=?", (client_id,))
    conn.commit()
    conn.close()

def create_ticket_record(client, theme_key: str, first_text: str, group_message_id: int, assignee=None):
    ticket_no = next_ticket_no()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO tickets(ticket_no, client_id, client_name, client_username, theme, group_id, status, assignee_id, assignee_name, created_at, group_message_id)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ticket_no,
        client.from_user.id,
        client.from_user.full_name,
        client.from_user.username or "",
        theme_key,
        GROUPS[theme_key],
        "OPEN",
        assignee["tg_user_id"] if assignee else None,
        assignee["full_name"] if assignee else None,
        now_msk().isoformat(),
        group_message_id
    ))
    ticket_id = cur.lastrowid
    # save first message
    cur.execute("""
    INSERT INTO messages(ticket_id, ticket_no, sender_type, sender_id, sender_name, text, created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (ticket_id, ticket_no, "client", client.from_user.id, client.from_user.full_name, first_text, now_msk().isoformat()))
    conn.commit()
    conn.close()
    # update operator last_assigned_at if assigned
    if assignee:
        update_operator_assigned(assignee["tg_user_id"])
    return ticket_no

def set_status(ticket_no: int, status: str):
    conn = db_conn()
    cur = conn.cursor()
    if status == "CLOSED":
        cur.execute("UPDATE tickets SET status=?, closed_at=? WHERE ticket_no=?",
                    (status, now_msk().isoformat(), ticket_no))
    else:
        cur.execute("UPDATE tickets SET status=? WHERE ticket_no=?",
                    (status, ticket_no))
    conn.commit()
    conn.close()

def find_ticket_by_group_message(group_id: int, group_message_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE group_id=? AND group_message_id=? LIMIT 1",
                (group_id, group_message_id))
    row = cur.fetchone()
    conn.close()
    return row

def save_message(ticket_no: int, ticket_id: int, sender_type: str, sender_id: int, sender_name: str, text: str):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO messages(ticket_id, ticket_no, sender_type, sender_id, sender_name, text, created_at) VALUES (?,?,?,?,?,?,?)",
                (ticket_id, ticket_no, sender_type, sender_id, sender_name, text, now_msk().isoformat()))
    conn.commit()
    conn.close()

# ---------- operators ----------
def register_operator(tg_user_id: int, full_name: str, username: str, group_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO operators(tg_user_id, full_name, username, group_id, active, created_at)
    VALUES (?,?,?,?,?,?)
    """, (tg_user_id, full_name, username or "", group_id, 1, now_msk().isoformat()))
    conn.commit()
    conn.close()

def update_operator_assigned(tg_user_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE operators SET last_assigned_at=? WHERE tg_user_id=?", (now_msk().isoformat(), tg_user_id))
    conn.commit()
    conn.close()

def get_operator_for_group(group_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM operators WHERE group_id=? AND active=1
    ORDER BY 
      CASE WHEN last_assigned_at IS NULL THEN 0 ELSE 1 END,
      last_assigned_at ASC
    LIMIT 1
    """, (group_id,))
    row = cur.fetchone()
    conn.close()
    return row

def list_operators_for_group(group_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM operators WHERE group_id=? AND active=1", (group_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

# ---------- helpers ----------
def close_btn_kb(ticket_no: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Закрыть", callback_data=f"close:{ticket_no}")]
    ])

# ---------- Bot logic ----------
async def main():
    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    # start/help
    @dp.message(CommandStart())
    async def start(m: Message):
        await m.answer(
            "Здравствуйте! Напишите ваш вопрос одним сообщением.\n"
            "Мы работаем ежедневно с 07:30 до 18:00 (МСК).\n"
            "После сообщения выберите тему: Продажи / Поддержка / Доставка."
        )

    # helper command to get chat id (use in group)
    @dp.message(Command(commands=["chat_id"]))
    async def chat_id_cmd(m: Message):
        # returns chat id
        await m.reply(f"chat.id = {m.chat.id}")

    # client message in private
    @dp.message(F.chat.type == "private")
    async def client_message(m: Message):
        active = get_active_ticket(m.from_user.id)
        if active:
            # добавляем сообщение в текущую заявку: пересылаем в группу reply на карточку
            group_id = int(active["group_id"])
            group_msg_id = int(active["group_message_id"])
            # save to DB
            save_message(int(active["ticket_no"]), int(active["id"]), "client", m.from_user.id, m.from_user.full_name, m.text or "")
            await bot.send_message(
                group_id,
                f"Сообщение от клиента по заявке №{active['ticket_no']}:\n{m.text}",
                reply_to_message_id=group_msg_id
            )
            await m.answer(f"Добавил сообщение в заявку №{active['ticket_no']}. Оператор ответит в этом чате.")
            return

        # нет активной заявки -> просим выбрать тему
        save_pending(m.from_user.id, m.text or "")
        await m.answer("Выберите тему обращения:", reply_markup=theme_kb())

    # theme picked by client
    @dp.callback_query(F.data.startswith("theme:"))
    async def pick_theme(cq: CallbackQuery):
        theme_key = cq.data.split(":", 1)[1]
        if theme_key not in THEMES:
            await cq.answer("Неизвестная тема", show_alert=True)
            return

        pending = get_pending(cq.from_user.id)
        if not pending:
            await cq.message.answer("Пожалуйста, сначала напишите вопрос сообщением.")
            await cq.answer()
            return

        first_text = pending["first_text"]
        clear_pending(cq.from_user.id)

        dt = now_msk()
        work = is_work_time(dt)

        group_id = GROUPS[theme_key]
        if group_id == 0:
            await cq.message.answer("Бот не настроен: не указаны ID групп отделов.")
            await cq.answer()
            return

        # try to get operator for group (round-robin)
        operator = get_operator_for_group(group_id)
        assignee = None
        if operator:
            assignee = {"tg_user_id": operator["tg_user_id"], "full_name": operator["full_name"]}

        # send card to group
        card_text = (
            f"🆕 Заявка (создается...)\n"
            f"Тема: {THEMES[theme_key]}\n"
            f"Клиент: {cq.from_user.full_name} (@{cq.from_user.username or '-'}) | id:{cq.from_user.id}\n"
            f"Создано: {dt.strftime('%Y-%m-%d %H:%M')} МСК\n"
            f"Статус: OPEN\n"
            f"Ответственный: {assignee['full_name'] if assignee else 'не назначен'}\n"
            f"Текст: {first_text}"
        )
        card_msg = await bot.send_message(group_id, card_text)
        ticket_no = create_ticket_record(cq.message, theme_key, first_text, card_msg.message_id, assignee=assignee)

        # update card with ticket_no and close button
        card_text2 = card_text.replace("🆕 Заявка (создается...)", f"🆕 Заявка №{ticket_no}")
        await bot.edit_message_text(card_text2, chat_id=group_id, message_id=card_msg.message_id, reply_markup=close_btn_kb(ticket_no))

        # auto-reply to client
        if work:
            await cq.message.answer(f"Заявка №{ticket_no} принята. Мы ответим в ближайшее время.")
        else:
            await cq.message.answer(
                f"Заявка №{ticket_no} принята.\n"
                f"График работы: ежедневно 07:30–18:00 (МСК). Ответим в рабочее время."
            )

        await cq.answer("Принято")

    # close ticket (button)
    @dp.callback_query(F.data.startswith("close:"))
    async def close_ticket(cq: CallbackQuery):
        ticket_no = int(cq.data.split(":", 1)[1])
        if cq.message.chat.id not in set(GROUPS.values()):
            await cq.answer("Нельзя закрыть отсюда", show_alert=True)
            return

        set_status(ticket_no, "CLOSED")
        await cq.message.reply(f"✅ Заявка №{ticket_no} закрыта.")

        # notify client
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("SELECT client_id FROM tickets WHERE ticket_no=?", (ticket_no,))
        row = cur.fetchone()
        conn.close()
        if row:
            await bot.send_message(int(row["client_id"]), f"Заявка №{ticket_no} закрыта. Если появятся новые вопросы — напишите, и мы создадим новую заявку.")
        await cq.answer("Закрыто")

    # operator replies in group (must be reply to card)
    @dp.message(F.chat.id.in_(set(GROUPS.values())))
    async def operator_reply(m: Message):
        # register operator if not admin and not bot
        try:
            admins = await bot.get_chat_administrators(m.chat.id)
            admin_ids = {a.user.id for a in admins}
        except Exception:
            admin_ids = set()

        if m.from_user and (m.from_user.id not in admin_ids) and (not m.from_user.is_bot):
            # register as operator (auto)
            register_operator(m.from_user.id, m.from_user.full_name, m.from_user.username or "", m.chat.id)

        # operator must reply to a card
        if not m.reply_to_message:
            return
        t = find_ticket_by_group_message(m.chat.id, m.reply_to_message.message_id)
        if not t:
            return

        # send to client
        client_id = int(t["client_id"])
        text_to_client = f"{m.from_user.full_name}: {m.text}"
        await bot.send_message(client_id, text_to_client)

        # log message
        save_message(int(t["ticket_no"]), int(t["id"]), "operator", m.from_user.id, m.from_user.full_name, m.text or "")

        # set IN_PROGRESS if was OPEN
        if t["status"] == "OPEN":
            set_status(int(t["ticket_no"]), "IN_PROGRESS")

    # find command: /find <ticket_no> or /find @username or /find client_id
    @dp.message(Command(commands=["find"]))
    async def find_cmd(m: Message):
        args = m.text.split(maxsplit=1)
        if len(args) == 1:
            await m.reply("Использование: /find <ticket_no|@username|client_id>")
            return
        q = args[1].strip()
        conn = db_conn()
        cur = conn.cursor()
        if q.isdigit():
            cur.execute("SELECT * FROM tickets WHERE ticket_no=? LIMIT 1", (int(q),))
            row = cur.fetchone()
            if not row:
                await m.reply("Не найдено.")
            else:
                await m.reply(
                    f"Заявка №{row['ticket_no']}\nТема: {THEMES.get(row['theme'], row['theme'])}\n"
                    f"Статус: {row['status']}\nКлиент: {row['client_name']} @{row['client_username']} id:{row['client_id']}\n"
                    f"Ответственный: {row['assignee_name'] or '-'}\nСоздано: {row['created_at']}\n"
                )
        elif q.startswith("@"):
            username = q[1:]
            cur.execute("SELECT * FROM tickets WHERE client_username=? ORDER BY id DESC LIMIT 10", (username,))
            rows = cur.fetchall()
            if not rows:
                await m.reply("Не найдено.")
            else:
                resp = []
                for r in rows:
                    resp.append(f"№{r['ticket_no']} {r['status']} {r['created_at']}")
                await m.reply("\n".join(resp))
        else:
            # assume client_id
            try:
                cid = int(q)
                cur.execute("SELECT * FROM tickets WHERE client_id=? ORDER BY id DESC LIMIT 10", (cid,))
                rows = cur.fetchall()
                if not rows:
                    await m.reply("Не найдено.")
                else:
                    resp = [f"№{r['ticket_no']} {r['status']} {r['created_at']}" for r in rows]
                    await m.reply("\n".join(resp))
            except ValueError:
                await m.reply("Неверный аргумент.")
        conn.close()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
