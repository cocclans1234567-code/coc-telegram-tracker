import telegram
from telegram.ext import Updater, CommandHandler
import requests
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
COC_API_TOKEN = os.getenv("COC_API_TOKEN")

def start(update, context):
    update.message.reply_text("Hello! CoC Tracker Bot is now active!")

def clan(update, context):
    tag = "".join(context.args)
    headers = {
        "Authorization": f"Bearer {COC_API_TOKEN}"
    }
    url = f"https://api.clashofclans.com/v1/clans/%23{tag}"

    r = requests.get(url, headers=headers)

    if r.status_code == 200:
        data = r.json()
        name = data['name']
        level = data['clanLevel']
        points = data['clanPoints']

        msg = f"🏆 Clan Info\n\nName: {name}\nLevel: {level}\nPoints: {points}"
        update.message.reply_text(msg)
    else:
        update.message.reply_text("Clan not found or invalid tag.")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("clan", clan))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
