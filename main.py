import os
import uuid
from datetime import datetime
from flask import Flask, request
import telebot
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import traceback

# ================== ENV VARIABLES ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 10000))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # Telegram ID to receive errors
MAX_SIZE = 20 * 1024 * 1024  # 20 MB limit

# ================== INIT ==================
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

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
    """Send error details to admin"""
    try:
        text = f"🚨 *Bot Issue Detected*\n\n"
        if context:
            text += f"📌 Context: {context}\n"
        text += f"📝 Error:\n```\n{error_msg}\n```"
        bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
    except Exception as e:
        print("Failed to report issue:", e)

# ================== BOT HANDLERS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    try:
        name = message.from_user.first_name or "User"
        bot.reply_to(
            message,
            f"👋 Hello {name}!\nSend a file (max 20MB) to get a download link.\n\n"
            "Commands:\n"
            "/myfiles – your files\n"
            "/delete <id> – delete a file\n"
            "/help – usage info"
        )
    except Exception:
        report_issue(traceback.format_exc(), context="/start command")

@bot.message_handler(commands=["help"])
def cmd_help(message):
    try:
        bot.reply_to(
            message,
            "ℹ️ How to use:\n"
            "1️⃣ Send a file ≤20MB\n"
            "2️⃣ Get a download link\n"
            "3️⃣ Share it anywhere\n\n"
            "Commands:\n"
            "/myfiles – list uploads\n"
            "/delete <id> – delete a file"
        )
    except Exception:
        report_issue(traceback.format_exc(), context="/help command")

@bot.message_handler(commands=["myfiles"])
def cmd_myfiles(message):
    try:
        user_id = message.from_user.id
        files = files_col.find({"user_id": user_id}).sort("created_at", -1).limit(10)
        if not files.count():
            bot.reply_to(message, "❌ You have no uploaded files.")
            return

        text = "📂 Your files:\n\n"
        for f in files:
            text += (
                f"🆔 {f['file_id']}\n"
                f"📄 {f['file_name']}\n"
                f"📦 {human_size(f['file_size'])}\n\n"
            )
        bot.reply_to(message, text)
    except Exception:
        report_issue(traceback.format_exc(), context="/myfiles command")

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
        report_issue(traceback.format_exc(), context="/delete command")

@bot.message_handler(content_types=["document"])
def handle_document(message):
    try:
        doc = message.document
        if doc.file_size > MAX_SIZE:
            bot.reply_to(message, "❌ File must be under 20 MB")
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

        final_link = f"{WEBHOOK_URL}/get?id={file_id}"

        bot.reply_to(
            message,
            f"✅ File uploaded!\n\n"
            f"📄 Name: {doc.file_name}\n"
            f"📦 Size: {human_size(doc.file_size)}\n"
            f"🆔 ID: `{file_id}`\n\n"
            f"🔗 Download link:\n{final_link}",
            parse_mode="Markdown"
        )
    except Exception:
        report_issue(traceback.format_exc(), context="handle_document")
        bot.reply_to(message, "❌ Upload failed. Admin has been notified.")

# ================== DOWNLOAD PAGE ==================
@app.route("/get")
def get_file():
    try:
        fid = request.args.get("id")
        if not fid:
            return "Invalid request"

        file = files_col.find_one({"file_id": fid})
        if not file:
            return "File not found or expired"

        file_name = file["file_name"]
        file_size = human_size(file["file_size"])
        tg_url = file["tg_url"]

        # HTML page with 10-second countdown
        return f'''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Download {file_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f9f9f9; }}
                .container {{ background: #fff; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); display: inline-block; }}
                button {{ padding: 15px 25px; font-size: 18px; cursor: pointer; border: none; border-radius: 5px; background: #28a745; color: white; }}
                button:disabled {{ background: #aaa; cursor: not-allowed; }}
                #timer {{ font-size: 24px; margin: 20px 0; color: #555; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Download Your File</h2>
                <p><strong>File:</strong> {file_name}</p>
                <p><strong>Size:</strong> {file_size}</p>
                <p id="timer">Please wait 10 seconds...</p>
                <a id="downloadLink" href="{tg_url}" target="_blank" style="display:none;">
                    <button>Download File</button>
                </a>
            </div>

            <script>
                let seconds = 10;
                const timerEl = document.getElementById('timer');
                const downloadLink = document.getElementById('downloadLink');

                const countdown = setInterval(() => {{
                    seconds--;
                    timerEl.innerText = "Please wait " + seconds + " seconds...";
                    if(seconds <= 0) {{
                        clearInterval(countdown);
                        timerEl.style.display = "none";
                        downloadLink.style.display = "inline-block";
                    }}
                }}, 1000);
            </script>
        </body>
        </html>
        '''
    except Exception:
        report_issue(traceback.format_exc(), context="/get route")
        return "Internal server error"

# ================== HOME ==================
@app.route("/")
def home():
    return "Telegram File Bot is running"

# ================== WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    except Exception:
        report_issue(traceback.format_exc(), context="/webhook route")
        return "error", 500

# ================== SET WEBHOOK ==================
bot.remove_webhook()
bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")

# ================== RUN FLASK ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
