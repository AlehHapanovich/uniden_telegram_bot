import os
import json
import asyncio
import requests
import re
from datetime import datetime
from bs4 import BeautifulSoup

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

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
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {d: {"firmware": None, "gps": None} for d in DEVICES}


def save_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


# ================= HELPERS =================
def extract_date(line):
    match = re.search(r"\d{4}/\d{2}/\d{2}", line)
    if match:
        try:
            return datetime.strptime(match.group(), "%Y/%m/%d")
        except:
            return None
    return None


def days_ago(date_string):
    date = extract_date(date_string)
    if not date:
        return None
    return (datetime.now() - date).days


def format_with_days(text):
    if not text:
        return "неизвестно"

    days = days_ago(text)
    if days is not None:
        return f"{text} (обновлено {days} дн. назад)"
    return text


# ================= PARSER =================
def get_versions(url, device):
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        rows = soup.find_all("tr")

        firmware_items = []
        gps_items = []

        for row in rows:
            cols = row.find_all("td")

            if len(cols) < 3:
                continue

            name = cols[0].get_text(strip=True)
            date_text = cols[-1].get_text(strip=True)

            # пробуем распарсить дату
            try:
                date = datetime.strptime(date_text, "%m/%d/%Y")
            except:
                continue

            # firmware
            if device in name and ("Firmware" in name or "Version" in name):
                firmware_items.append((date, name))

            # gps
            if "Database" in name or "GPS" in name:
                gps_items.append((date, name))

        firmware = max(firmware_items, key=lambda x: x[0])[1] if firmware_items else None
        gps = max(gps_items, key=lambda x: x[0])[1] if gps_items else None

        return firmware, gps

    except Exception as e:
        print("Parse error:", e)
        return None, None


# ================= UI =================
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


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Выбери свой радар:",
        reply_markup=device_keyboard()
    )


async def change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 Выбери новую модель:",
        reply_markup=device_keyboard()
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    state = load_state()

    uid = str(update.effective_user.id)

    if uid not in users:
        await update.message.reply_text("❗ Сначала выбери модель через /start")
        return

    device = users[uid]

    firmware = format_with_days(state[device]["firmware"])
    gps = format_with_days(state[device]["gps"])

    await update.message.reply_text(
        f"🚗 {device}\n"
        f"🆕 Firmware: {firmware}\n"
        f"📡 GPS: {gps}"
    )


# ================= BUTTON =================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    users = load_users()
    uid = str(query.from_user.id)

    if query.data == "change":
        await query.message.reply_text(
            "🔄 Выбери новую модель:",
            reply_markup=device_keyboard()
        )
        return

    if query.data.startswith("set_"):
        device = query.data.split("_")[1]
        users[uid] = device
        save_users(users)

        state = load_state()
        firmware = state[device]["firmware"]
        gps = state[device]["gps"]

        if not firmware or not gps:
            f, g = get_versions(DEVICES[device], device)
            if f:
                firmware = f
                state[device]["firmware"] = f
            if g:
                gps = g
                state[device]["gps"] = g
            save_state(state)

        firmware = format_with_days(firmware)
        gps = format_with_days(gps)

        await query.edit_message_text(
            f"✅ Вы выбрали: {device}\n\n"
            f"🆕 Firmware: {firmware}\n"
            f"📡 GPS: {gps}",
            reply_markup=change_keyboard()
        )


# ================= CHECKER =================
async def checker(app):
    while True:
        users = load_users()
        state = load_state()

        for device, url in DEVICES.items():
            firmware, gps = get_versions(url, device)

            # firmware update
            if firmware and firmware != state[device]["firmware"]:
                for uid, dev in users.items():
                    if dev == device:
                        await app.bot.send_message(
                            chat_id=uid,
                            text=f"🆕 {device} прошивка:\n{firmware}"
                        )
                state[device]["firmware"] = firmware

            # gps update
            if gps and gps != state[device]["gps"]:
                for uid, dev in users.items():
                    if dev == device:
                        await app.bot.send_message(
                            chat_id=uid,
                            text=f"📡 {device} GPS база:\n{gps}"
                        )
                state[device]["gps"] = gps

        save_state(state)
        await asyncio.sleep(3600)


# ================= INIT =================
def init_versions():
    state = load_state()

    for device, url in DEVICES.items():
        f, g = get_versions(url, device)
        if f:
            state[device]["firmware"] = f
        if g:
            state[device]["gps"] = g

    save_state(state)


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change", change))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button))

    init_versions()

    loop = asyncio.get_event_loop()
    loop.create_task(checker(app))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()