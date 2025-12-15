import os
import uuid
import threading
from datetime import datetime

from flask import Flask, request
import telebot
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# ================== ENV VARIABLES ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
BLOGGER_PAGE = os.environ.get("BLOGGER_PAGE")
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not MONGO_URI or not BLOGGER_PAGE:
    raise RuntimeError("Missing required environment variables")

# ================== INIT ==================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

# ================== DATABASE ==================
try:
    mongo = MongoClient(MONGO_URI)
    db = mongo["tg_file_bot"]
    files_col = db["files"]
except PyMongoError as e:
    raise RuntimeError(f"MongoDB connection failed: {e}")

# ================== CONSTANTS ==================
MAX_SIZE = 20 * 1024 * 1024  # 20 MB

# ================== HELPERS ==================
def human_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}TB"

# ================== BOT COMMANDS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    name = message.from_user.first_name or "User"
    bot.reply_to(
        message,
        f"👋 Hello {name}!\n\n"
        "📤 Send me a file (max 20MB)\n"
        "🔗 I will generate a download link\n\n"
        "Commands:\n"
        "/myfiles – view your files\n"
        "/help – usage info"
    )

@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.reply_to(
        message,
        "ℹ️ How to use this bot:\n\n"
        "1️⃣ Send a file (≤20MB)\n"
        "2️⃣ Receive a Blogger download link\n"
        "3️⃣ Share it anywhere\n\n"
        "Commands:\n"
        "/myfiles – list your uploads\n"
        "/delete <id> – delete a file"
    )

# ================== FILE HANDLER ==================
@bot.message_handler(content_types=["document"])
def handle_document(message):
    doc = message.document

    if doc.file_size > MAX_SIZE:
        bot.reply_to(message, "❌ File must be under 20 MB")
        return

    try:
        file_info = bot.get_file(doc.file_id)
        tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        file_id = uuid.uuid4().hex[:10]

        files_col.insert_one({
            "file_id": file_id,
            "user_id": message.from_user.id,
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "tg_url": tg_url,
            "created_at": datetime.utcnow()
        })

        final_link = f"{BLOGGER_PAGE}?id={file_id}"

        bot.reply_to(
            message,
            f"✅ File uploaded!\n\n"
            f"📄 Name: {doc.file_name}\n"
            f"📦 Size: {human_size(doc.file_size)}\n"
            f"🆔 ID: `{file_id}`\n\n"
            f"🔗 Download link:\n{final_link}",
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.reply_to(message, "❌ Upload failed. Try again later.")
        print("ERROR:", e)

# ================== MY FILES ==================
@bot.message_handler(commands=["myfiles"])
def cmd_myfiles(message):
    user_id = message.from_user.id
    files = files_col.find(
        {"user_id": user_id}
    ).sort("created_at", -1).limit(10)

    text = "📂 Your files:\n\n"
    count = 0

    for f in files:
        count += 1
        text += (
            f"🆔 {f['file_id']}\n"
            f"📄 {f['file_name']}\n"
            f"📦 {human_size(f['file_size'])}\n\n"
        )

    if count == 0:
        text = "❌ You have no uploaded files."

    bot.reply_to(message, text)

# ================== DELETE FILE ==================
@bot.message_handler(commands=["delete"])
def cmd_delete(message):
    parts = message.text.split()

    if len(parts) != 2:
        bot.reply_to(message, "❌ Usage: /delete <file_id>")
        return

    file_id = parts[1]

    result = files_col.delete_one({
        "file_id": file_id,
        "user_id": message.from_user.id
    })

    if result.deleted_count:
        bot.reply_to(message, "✅ File deleted successfully")
    else:
        bot.reply_to(message, "❌ File not found")

# ================== BLOGGER API ==================
@app.route("/get")
def get_file():
    fid = request.args.get("id")
    if not fid:
        return "Invalid request"

    file = files_col.find_one({"file_id": fid})
    if not file:
        return "Invalid or expired link"

    return file["tg_url"]

@app.route("/")
def home():
    return "Telegram File Bot is running"

# ================== RUN SERVICES ==================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)

def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
