import os
import json
import requests
import re
from datetime import datetime
from bs4 import BeautifulSoup

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")

DEVICES = {
    "R3": "https://www.uniden.info/download/index.cfm?s=R3",
    "R7": "https://www.uniden.info/download/index.cfm?s=R7",
    "R8": "https://www.uniden.info/download/index.cfm?s=R8",
}

USERS_FILE = "users.json"
STATE_FILE = "state.json"


# ================= STORAGE =================
def load_users():
    if os.path.exists(USERS_FILE):
        return json.load(open(USERS_FILE))
    return {}

def save_users(data):
    json.dump(data, open(USERS_FILE, "w"))


def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {d: {"firmware": None, "gps": None} for d in DEVICES}


def save_state(data):
    json.dump(data, open(STATE_FILE, "w"))


# ================= UI MENU =================
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["🚗 Модель", "📊 Статус"],
            ["🔄 Сменить", "🔔 Обновления"],
        ],
        resize_keyboard=True
    )


def device_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("R3", callback_data="set_R3")],
        [InlineKeyboardButton("R7", callback_data="set_R7")],
        [InlineKeyboardButton("R8", callback_data="set_R8")],
    ])


def change_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Сменить модель", callback_data="change")]
    ])


# ================= PARSER (Description + Release Date) =================
def parse_date(text):
    match = re.search(r"\d{2}/\d{2}/\d{4}", text)
    if match:
        return datetime.strptime(match.group(), "%m/%d/%Y")
    return None


def get_versions(url, device):
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        table = None
        headers = None

        # 1. находим таблицу
        for t in soup.find_all("table"):
            ths = [h.get_text(strip=True).lower() for h in t.find_all("th")]

            if "release" in " ".join(ths) and "description" in " ".join(ths):
                table = t
                headers = ths
                break

        if not table:
            return None, None

        # 2. индексы колонок
        cols = table.find_all("th")
        version_idx = None
        desc_idx = None
        date_idx = None

        for i, h in enumerate(cols):
            txt = h.get_text(strip=True).lower()

            if "version" in txt:
                version_idx = i
            if "description" in txt:
                desc_idx = i
            if "release" in txt or "date" in txt:
                date_idx = i

        items = []

        # 3. читаем строки
        for row in table.find_all("tr")[1:]:
            tds = row.find_all("td")
            if len(tds) <= max(version_idx, desc_idx, date_idx):
                continue

            version = tds[version_idx].get_text(strip=True)
            desc = tds[desc_idx].get_text(strip=True)
            date_text = tds[date_idx].get_text(strip=True)

            try:
                date = datetime.strptime(date_text, "%m/%d/%Y")
            except:
                continue

            items.append({
                "version": version,
                "desc": desc,
                "date": date
            })

        # 4. сортировка по Release Date
        items.sort(key=lambda x: x["date"], reverse=True)

        firmware = None
        gps = None

        # 5. ИМЕННО Description используем для логики
        for item in items:
            d = item["desc"].lower()

            if not firmware and "firmware update" in d:
                firmware = f"Firmware Update v{item['version']}"

            if not gps and "database update" in d:
                gps = f"Database Update {item['version']}"

            if firmware and gps:
                break

        return firmware, gps

    except Exception as e:
        print("parse error:", e)
        return None, None


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Добро пожаловать!\nВыбери действие:",
        reply_markup=main_menu()
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    state = load_state()

    uid = str(update.effective_user.id)

    if uid not in users:
        await update.message.reply_text("Сначала выбери модель → 🚗 Модель")
        return

    d = users[uid]

    await update.message.reply_text(
        f"🚗 {d}\n\n"
        f"🆕 Firmware: {state[d]['firmware']}\n"
        f"📡 GPS: {state[d]['gps']}"
    )


# ================= BUTTON CALLBACK =================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    users = load_users()
    uid = str(q.from_user.id)

    if q.data == "change":
        await q.message.reply_text("Выбери модель:", reply_markup=device_keyboard())
        return

    if q.data.startswith("set_"):
        device = q.data.split("_")[1]
        users[uid] = device
        save_users(users)

        state = load_state()
        fw, gps = get_versions(DEVICES[device], device)

        if fw:
            state[device]["firmware"] = fw
        if gps:
            state[device]["gps"] = gps

        save_state(state)

        await q.edit_message_text(
            f"✅ {device}\n\n🆕 {fw}\n📡 {gps}",
            reply_markup=change_keyboard()
        )


# ================= TEXT MENU =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    users = load_users()

    uid = str(update.effective_user.id)

    if text == "🚗 Модель":
        await update.message.reply_text("Выбери модель:", reply_markup=device_keyboard())

    elif text == "📊 Статус":
        await status(update, context)

    elif text == "🔄 Сменить":
        await update.message.reply_text("Смена модели:", reply_markup=device_keyboard())

    elif text == "🔔 Обновления":
        await update.message.reply_text("🔔 Уведомления включены")


# ================= BACKGROUND CHECK =================
async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    state = load_state()

    for device, url in DEVICES.items():
        fw, gps = get_versions(url, device)

        if fw and fw != state[device]["firmware"]:
            for uid, d in users.items():
                if d == device:
                    await context.bot.send_message(uid, f"🚗 Uniden {device}\n\n🆕 Firmware: {fw}\n📌 Обновление доступно")
            state[device]["firmware"] = fw

        if gps and gps != state[device]["gps"]:
            for uid, d in users.items():
                if d == device:
                    await context.bot.send_message(uid, f"🚗 Uniden {device}\n\n📡 GPS база обновлена\n📌 Рекомендуется обновить")
            state[device]["gps"] = gps

    save_state(state)


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.job_queue.run_repeating(check_updates, interval=3600, first=10)

    print("BOT STARTED")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()