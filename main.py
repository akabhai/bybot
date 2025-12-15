from flask import Flask, render_template
import telebot
from pymongo import MongoClient
import os
from threading import Thread

# ---------------- ENV VARIABLES -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Telegram bot token
MONGO_URI = os.getenv("MONGO_URI")  # MongoDB connection string
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB limit

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client["telegram_bot_db"]
files_collection = db["files"]

app = Flask(__name__)

# ---------------- UTILITY ----------------------
def human_size(size):
    for unit in ['B','KB','MB','GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

# ---------------- TELEGRAM HANDLERS ------------
# Welcome message
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id,
        f"👋 Hello {message.from_user.first_name}!\n\n"
        "Welcome to the File Bot.\n"
        "You can upload files (docs, videos, audio) up to 20MB here.\n"
        "After upload, download/stream links appear on the homepage."
    )

# Handle uploaded files
@bot.message_handler(content_types=['document','video','audio'])
def handle_file(message):
    try:
        # Determine file object
        if message.content_type == 'document':
            file_obj = message.document
        elif message.content_type == 'video':
            file_obj = message.video
        elif message.content_type == 'audio':
            file_obj = message.audio
        else:
            bot.reply_to(message, "⚠ Unsupported file type.")
            return

        # Check file size
        file_size = getattr(file_obj, "file_size", 0)
        if file_size > MAX_FILE_SIZE:
            bot.reply_to(message, "⚠ File exceeds 20MB limit. Upload a smaller file.")
            return

        file_id = file_obj.file_id
        file_info = bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        # File name
        if hasattr(file_obj, "file_name") and file_obj.file_name:
            file_name = file_obj.file_name
        else:
            file_name = file_info.file_path.split("/")[-1]

        # Save in MongoDB
        files_collection.update_one(
            {"file_id": file_id},
            {"$set": {"file_name": file_name, "tg_url": tg_url, "file_size": file_size}},
            upsert=True
        )

        bot.reply_to(message, "✅ File uploaded successfully!\nVisit the homepage to download or stream.")

    except Exception as e:
        bot.reply_to(message, f"⚠ Error occurred: {str(e)}")

# ---------------- FLASK ROUTES ------------------
@app.route("/")
def index():
    files = list(files_collection.find())
    return render_template("index.html", files=files, human_size=human_size)

# ---------------- RUN BOT & FLASK -------------
def run_bot():
    try:
        bot.delete_webhook()  # prevent 409 error
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print("Bot Error:", e)

if __name__ == "__main__":
    # Run bot in a separate thread
    Thread(target=run_bot).start()
    # Run Flask app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
