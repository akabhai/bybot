import os
import uuid
from datetime import datetime
from flask import Flask, request
import telebot
from pymongo import MongoClient

# ===== ENV =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BLOGGER_PAGE = os.environ.get("BLOGGER_PAGE")
MONGO_URI = os.environ.get("MONGO_URI")

MAX_SIZE = 20 * 1024 * 1024  # 20MB

# ===== INIT =====
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

mongo = MongoClient(MONGO_URI)
db = mongo["tg_file_bot"]
files_col = db["files"]

# ===== HELPERS =====
def human_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024

# ===== COMMANDS =====
@bot.message_handler(commands=["start"])
def start_cmd(message):
    name = message.from_user.first_name
    bot.reply_to(
        message,
        f"👋 Hello {name}!\n\n"
        "Send me a file (max 20MB) and I will generate a download link.\n\n"
        "Commands:\n"
        "/myfiles – view your uploads\n"
        "/help – how to use\n"
    )

@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "📌 How it works:\n\n"
        "1️⃣ Send a file (≤20MB)\n"
        "2️⃣ Get a download link\n"
        "3️⃣ Share the link\n\n"
        "Commands:\n"
        "/myfiles – list your files\n"
        "/delete <id> – remove a file\n"
    )

# ===== FILE HANDLER =====
@bot.message_handler(content_types=["document"])
def handle_document(message):
    doc = message.document

    if doc.file_size > MAX_SIZE:
        bot.reply_to(message, "❌ File size must be under 20MB")
        return

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
        f"📦 Size: {human_size(doc.file_size)}\n\n"
        f"🔗 Download link:\n{final_link}\n\n"
        f"🆔 File ID: `{file_id}`",
        parse_mode="Markdown"
    )

# ===== MY FILES =====
@bot.message_handler(commands=["myfiles"])
def my_files(message):
    user_id = message.from_user.id
    files = files_col.find({"user_id": user_id}).sort("created_at", -1).limit(10)

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

# ===== DELETE FILE =====
@bot.message_handler(commands=["delete"])
def delete_file(message):
    try:
        file_id = message.text.split()[1]
    except:
        bot.reply_to(message, "❌ Usage: /delete <file_id>")
        return

    result = files_col.delete_one({
        "file_id": file_id,
        "user_id": message.from_user.id
    })

    if result.deleted_count:
        bot.reply_to(message, "✅ File deleted")
    else:
        bot.reply_to(message, "❌ File not found")

# ===== BLOGGER API =====
@app.route("/get")
def get_file():
    fid = request.args.get("id")
    file = files_col.find_one({"file_id": fid})

    if not file:
        return "Invalid or expired link"

    return file["tg_url"]

@app.route("/")
def home():
    return "Telegram File Bot is running"

# ===== START =====
if __name__ == "__main__":
    bot.infinity_polling()
