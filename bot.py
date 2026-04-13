import os
import json
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


# ================= PARSER (Release Date-based) =================
def parse_date(text):
    match = re.search(r"\d{4}/\d{2}/\d{2}", text)
    if not match:
        return None
    return datetime.strptime(match.group(), "%Y/%m/%d")


def get_versions(url, device):
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        rows = soup.find_all("tr")

        items = []

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            version_text = cols[0].get_text(strip=True)
            date_text = cols[-1].get_text(strip=True)

            # парсим дату Release Date
            try:
                date = datetime.strptime(date_text, "%m/%d/%Y")
            except:
                continue

            items.append({
                "version": version_text,
                "date": date
            })

        if not items:
            return None, None

        # 🔥 SORT BY RELEASE DATE (DESC)
        items.sort(key=lambda x: x["date"], reverse=True)

        firmware = None
        gps = None

        for item in items:
            v = item["version"]
            d = item["date"]

            # -------------------------
            # FIRMWARE
            # -------------------------
            if "Firmware" in v or "Version" in v:
                match = re.search(r"\d+(\.\d+)+", v)
                if match:
                    firmware = f"Firmware {match.group()} ({d.strftime('%Y/%m/%d')})"
                    break

        for item in items:
            v = item["version"]
            d = item["date"]

            # -------------------------
            # GPS / DATABASE
            # -------------------------
            if "GPS" in v or "Database" in v:
                gps = f"{v} ({d.strftime('%Y/%m/%d')})"
                break

        return firmware, gps

    except Exception as e:
        print("parse error:", e)
        return None, None


# ================= UI =================
def keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("R3", callback_data="set_R3")],
        [InlineKeyboardButton("R7", callback_data="set_R7")],
        [InlineKeyboardButton("R8", callback_data="set_R8")],
    ])

def change_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Сменить модель", callback_data="change")]
    ])


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚗 Выбери радар:", reply_markup=keyboard())


async def change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Выбери модель:", reply_markup=keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    state = load_state()

    uid = str(update.effective_user.id)

    if uid not in users:
        await update.message.reply_text("Сначала /start")
        return

    d = users[uid]
    fw = state[d]["firmware"] or "нет данных"
    gps = state[d]["gps"] or "нет данных"

    await update.message.reply_text(
        f"🚗 {d}\n🆕 {fw}\n📡 {gps}"
    )


# ================= BUTTON =================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    users = load_users()
    uid = str(q.from_user.id)

    if q.data == "change":
        await q.message.reply_text("🔄 Выбери модель:", reply_markup=keyboard())
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
            f"✅ {device}\n🆕 {fw}\n📡 {gps}",
            reply_markup=change_kb()
        )


# ================= SAFE CHECKER (JobQueue) =================
async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    state = load_state()

    for device, url in DEVICES.items():
        fw, gps = get_versions(url, device)

        if fw and fw != state[device]["firmware"]:
            for uid, d in users.items():
                if d == device:
                    await context.bot.send_message(uid, f"🆕 {device}: {fw}")
            state[device]["firmware"] = fw

        if gps and gps != state[device]["gps"]:
            for uid, d in users.items():
                if d == device:
                    await context.bot.send_message(uid, f"📡 {device}: {gps}")
            state[device]["gps"] = gps

    save_state(state)


# ================= MAIN (NEEDLE-ROBUST) =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change", change))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button))

    # SAFE scheduler (NO asyncio chaos)
    app.job_queue.run_repeating(check_updates, interval=3600, first=10)

    print("BOT STARTED (stable mode)")
    app.run_polling(
        drop_pending_updates=True  # 🔥 убирает конфликты getUpdates
    )


if __name__ == "__main__":
    main()