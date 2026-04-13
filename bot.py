import os
import json
import asyncio
import requests
from bs4 import BeautifulSoup

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =====================
# CONFIG
# =====================
TOKEN = os.getenv("BOT_TOKEN")

DEVICES = {
    "R3": "https://www.uniden.info/download/index.cfm?s=R3",
    "R7": "https://www.uniden.info/download/index.cfm?s=R7",
    "R8": "https://www.uniden.info/download/index.cfm?s=R8",
}

USERS_FILE = "users.json"
STATE_FILE = "state.json"


# =====================
# STORAGE
# =====================
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


# =====================
# PARSER
# =====================
def get_versions(url, device):
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text("\n")

        firmware = None
        gps = None

        for line in text.split("\n"):
            line = line.strip()

            if "Firmware" in line or "Version" in line:
                if device in line or "R" in line:
                    firmware = line

            if "Database" in line or "GPS" in line:
                gps = line

        return firmware, gps

    except Exception as e:
        print("Parse error:", e)
        return None, None


# =====================
# KEYBOARDS
# =====================
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


# =====================
# COMMANDS
# =====================
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


# =====================
# CALLBACKS
# =====================
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

        await query.edit_message_text(
            f"✅ Вы выбрали: {device}",
            reply_markup=change_keyboard()
        )


# =====================
# CHECK LOOP
# =====================
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


# =====================
# MAIN
# =====================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change", change))
    app.add_handler(CallbackQueryHandler(button))

    # background task
    loop = asyncio.get_event_loop()
    loop.create_task(checker(app))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()