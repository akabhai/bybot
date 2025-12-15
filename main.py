from flask import Flask, render_template
import telebot
from pymongo import MongoClient
import os
from threading import Thread
import traceback

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
    """Convert bytes to human-readable format"""
    for unit in ['B','KB','MB','GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

# ---------------- TELEGRAM HANDLERS ------------

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        bot.send_message(
            message.chat.id,
            f"👋 Hello {message.from_user.first_name}!\n\n"
            "Welcome to the File Bot.\n"
            "You can upload files (documents, videos, audio) up to 20MB here.\n"
            "After upload, you'll receive a direct download link and the files appear on the homepage."
        )
    except Exception as e:
        print("Welcome message error:", e)

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

        file_size = getattr(file_obj, "file_size", 0)
        if file_size > MAX_FILE_SIZE:
            bot.reply_to(message, "⚠ File exceeds 20MB limit.")
            return

        file_info = bot.get_file(file_obj.file_id)
        tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        file_name = getattr(file_obj, "file_name", file_info.file_path.split("/")[-1])

        # Save metadata to MongoDB
        files_collection.update_one(
            {"file_id": file_obj.file_id},
            {"$set": {
                "file_name": file_name,
                "tg_url": tg_url,
                "file_size": file_size
            }},
            upsert=True
        )

        # Send direct link to user
        bot.reply_to(
            message,
            f"✅ File uploaded successfully!\n\n"
            f"📥 Direct Download Link:\n{tg_url}\n\n"
            f"🌐 Visit homepage to stream/download: https://yourwebsite.com/"
        )

    except Exception as e:
        bot.reply_to(message, f"⚠ Error occurred: {str(e)}")
        print("File handler error:", e)
        print(traceback.format_exc())

# ---------------- FLASK ROUTES ------------------

@app.route("/")
def index():
    try:
        files = list(files_collection.find())
        return render_template("index.html", files=files, human_size=human_size)
    except Exception as e:
        print("Flask route error:", e)
        return "<h2>⚠ Error loading files. Check server logs.</h2>"

# ---------------- RUN BOT & FLASK -------------
def run_bot():
    try:
        # Delete webhook to avoid 409 error
        bot.delete_webhook()
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print("Bot runtime error:", e)
        print(traceback.format_exc())

if __name__ == "__main__":
    # Run Telegram bot in a separate thread
    Thread(target=run_bot).start()
    # Run Flask app for homepage
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
