import os
import uuid
from datetime import datetime
from flask import Flask, request, render_template
import telebot
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import traceback

# ================== ENV VARIABLES ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "6722458132"))  # Your Telegram ID
MAX_SIZE = 50 * 1024 * 1024  # 50 MB

# ================== INIT ==================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__, template_folder="templates")

# ================== DATABASE ==================
try:
    mongo = MongoClient(MONGO_URI)
    db = mongo["tg_file_bot"]
    files_col = db["files"]
except PyMongoError as e:
    raise RuntimeError(f"MongoDB connection failed: {e}")

# ================== HELPERS ==================
def human_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}TB"

def report_issue(error_msg, context=""):
    """Send error to admin"""
    try:
        text = f"🚨 <b>Bot Issue Detected</b>\n\n"
        if context:
            text += f"📌 Context: {context}\n"
        text += f"📝 Error:\n<pre>{error_msg}</pre>"
        bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        print("Failed to report issue:", e)

# ================== BOT HANDLERS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    try:
        name = message.from_user.first_name or "User"
        bot.reply_to(message,
            f"👋 Hello {name}!\nSend any file (max 50MB) or forward from groups.\n\n"
            "Commands:\n/myfiles - your uploads\n/delete <id> - delete file\n/help - usage info")
    except Exception:
        report_issue(traceback.format_exc(), "/start command")

@bot.message_handler(commands=["help"])
def cmd_help(message):
    try:
        bot.reply_to(message,
            "ℹ️ How to use:\n1️⃣ Send or forward a file ≤50MB\n2️⃣ Receive a download link\n"
            "3️⃣ Click the link to download or stream\n\n"
            "Commands:\n/myfiles - list files\n/delete <id> - delete file")
    except Exception:
        report_issue(traceback.format_exc(), "/help command")

@bot.message_handler(commands=["myfiles"])
def cmd_myfiles(message):
    try:
        user_id = message.from_user.id
        files = files_col.find({"user_id": user_id}).sort("created_at", -1).limit(10)
        if files.count() == 0:
            bot.reply_to(message, "❌ You have no uploaded files.")
            return
        text = "📂 Your files:\n\n"
        for f in files:
            text += f"🆔 {f['file_id']}\n📄 {f['file_name']}\n📦 {human_size(f['file_size'])}\n\n"
        bot.reply_to(message, text)
    except Exception:
        report_issue(traceback.format_exc(), "/myfiles command")

@bot.message_handler(commands=["delete"])
def cmd_delete(message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ Usage: /delete <file_id>")
            return
        file_id = parts[1]
        result = files_col.delete_one({"file_id": file_id, "user_id": message.from_user.id})
        if result.deleted_count:
            bot.reply_to(message, "✅ File deleted successfully")
        else:
            bot.reply_to(message, "❌ File not found")
    except Exception:
        report_issue(traceback.format_exc(), "/delete command")

# ================== FILE UPLOAD HANDLER ==================
@bot.message_handler(content_types=["document", "video", "audio", "photo"])
def handle_file(message):
    try:
        if message.content_type == "photo":
            file_obj = message.photo[-1]
            file_name = f"photo_{file_obj.file_id}.jpg"
            file_size = file_obj.file_size
        else:
            doc = message.document if message.content_type=="document" else message.video if message.content_type=="video" else message.audio
            file_obj = doc
            file_name = getattr(doc, "file_name", f"{doc.file_id}.dat")
            file_size = getattr(doc, "file_size", 0)

        if file_size > MAX_SIZE:
            bot.reply_to(message, "❌ File exceeds 50MB limit")
            return

        file_info = bot.get_file(file_obj.file_id)
        tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        file_id = uuid.uuid4().hex[:10]

        files_col.insert_one({
            "file_id": file_id,
            "user_id": message.from_user.id,
            "file_name": file_name,
            "file_size": file_size,
            "tg_url": tg_url,
            "created_at": datetime.utcnow()
        })

        final_link = f"{WEBHOOK_URL}/get?id={file_id}"
        bot.reply_to(message,
            f"✅ File uploaded!\n📄 {file_name}\n📦 {human_size(file_size)}\n🔗 <a href='{final_link}'>Download / Stream</a>")
    except Exception:
        report_issue(traceback.format_exc(), "handle_file")
        bot.reply_to(message, "❌ Upload failed. Admin notified.")

# ================== FLASK ROUTES ==================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/get")
def download_page():
    fid = request.args.get("id")
    if not fid:
        return "Invalid request"
    file = files_col.find_one({"file_id": fid})
    if not file:
        return "File not found"
    return render_template("download.html", file=file, human_size=human_size)

# ================== WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    except Exception:
        report_issue(traceback.format_exc(), "/webhook route")
        return "error", 500

# ================== SET WEBHOOK ==================
bot.remove_webhook()
bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

