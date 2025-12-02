import os
import time
import asyncio
import logging
from typing import Dict
import requests
from telegram import __version__ as ptb_version
from telegram import constants
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackContext
from telegram import Update

# Logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Read environment variables (set these in Render / hosting)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
COC_API_KEY = os.getenv("COC_API_KEY")
CLAN_TAG = os.getenv("CLAN_TAG")  # allow with or without leading '#'
CHAT_ID = os.getenv("CHAT_ID")    # group or user chat id (e.g. -5004546651)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))  # seconds between checks

# Basic validations
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is missing in environment variables")
if not COC_API_KEY:
    raise RuntimeError("COC_API_KEY is missing in environment variables")
if not CLAN_TAG:
    raise RuntimeError("CLAN_TAG is missing in environment variables")
if not CHAT_ID:
    raise RuntimeError("CHAT_ID is missing in environment variables")

# Normalize
if CLAN_TAG.startswith("#"):
    CLAN_TAG = CLAN_TAG[1:]

try:
    CHAT_ID_INT = int(CHAT_ID)
except Exception:
    raise RuntimeError("CHAT_ID must be an integer (group id or user id)")

API_BASE = "https://api.clashofclans.com/v1"
CLAN_MEMBERS_URL = f"{API_BASE}/clans/%23{CLAN_TAG}/members"
HEADERS = {"Authorization": f"Bearer {COC_API_KEY}", "Accept": "application/json"}

# In-memory store of members (tag -> name). For persistence you can add DB later.
known_members: Dict[str, str] = {}

# Helper: fetch current clan members (blocking requests; will be called in thread)
def fetch_clan_members_sync():
    try:
        resp = requests.get(CLAN_MEMBERS_URL, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning("CoC API returned %s: %s", resp.status_code, resp.text)
            return None, resp.status_code
        data = resp.json()
        items = data.get("items", [])
        members = {item.get("tag"): item.get("name") for item in items}
        return members, 200
    except Exception as e:
        logger.exception("Error calling CoC API: %s", e)
        return None, None

# Background task: monitor clan and notify join/leave
async def monitor_clan(app):
    global known_members
    bot: Bot = app.bot
    logger.info("Starting clan monitor for tag #%s (interval=%ss)", CLAN_TAG, POLL_INTERVAL)

    while True:
        # Run blocking HTTP call in thread to avoid blocking event loop
        members, status = await asyncio.to_thread(fetch_clan_members_sync)

        if members is None:
            # API failed — log and notify admin occasionally
            logger.warning("Failed to fetch clan members (status=%s). Retrying in %s seconds.", status, POLL_INTERVAL)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        # detect joins
        joined = {t: n for t, n in members.items() if t not in known_members}
        # detect leaves
        left = {t: n for t, n in known_members.items() if t not in members}

        # send notifications
        for tag, name in joined.items():
            text = f"🟢 *JOINED:* {name} (`{tag}`)\nClan: #{CLAN_TAG}"
            try:
                await bot.send_message(chat_id=CHAT_ID_INT, text=text, parse_mode=constants.ParseMode.MARKDOWN)
                logger.info("Notified join: %s %s", tag, name)
            except Exception as e:
                logger.exception("Failed to send join message: %s", e)

        for tag, name in left.items():
            text = f"🔴 *LEFT:* {name} (`{tag}`)\nClan: #{CLAN_TAG}"
            try:
                await bot.send_message(chat_id=CHAT_ID_INT, text=text, parse_mode=constants.ParseMode.MARKDOWN)
                logger.info("Notified leave: %s %s", tag, name)
            except Exception as e:
                logger.exception("Failed to send leave message: %s", e)

        # update known_members
        known_members = members

        await asyncio.sleep(POLL_INTERVAL)

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 CoC Tracker Bot running. I will notify this chat about joins/leaves.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Monitoring clan: #{CLAN_TAG}\nMembers stored: {len(known_members)}\nPoll interval: {POLL_INTERVAL}s")

async def members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not known_members:
        await update.message.reply_text("No member data yet — try again in a minute.")
        return
    lines = [f"{name} — `{tag}`" for tag, name in sorted(known_members.items(), key=lambda x: x[1])]
    text = "Clan members:\n\n" + "\n".join(lines[:200])  # limit length
    await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)

# Entrypoint
def main():
    logger.info("python-telegram-bot version: %s", ptb_version)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("members", members_command))

    # schedule background monitor after app starts
    async def on_startup(app):
        # populate initial known_members (so first loop won't spam joins)
        members, status = await asyncio.to_thread(fetch_clan_members_sync)
        if members:
            global known_members
            known_members = members
            logger.info("Initial members loaded: %d", len(known_members))
        # start monitor task
        app.create_task(monitor_clan(app))

    app.post_init = on_startup

    logger.info("Starting bot polling...")
    app.run_polling(stop_signals=None)  # let Render handle lifecycle

if __name__ == "__main__":
    main()
