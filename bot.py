"""
Bike Registration Checker Bot (Showroom use)
---------------------------------------------
Staff send a bike registration number, pick Punjab or KPK, and the bot
replies with the official government verification link (MTMIS Punjab /
KPK Excise) plus the Punjab SMS method.

Why links and not automatic data? MTMIS Punjab shows a CAPTCHA on its
search page, so no bot can legally/automatically pull owner data from it.
The bot formats the number correctly and gives a one-tap official link —
staff open it, type the number, solve the captcha, and get the record.

Setup:
  pip install -r requirements.txt
  set the environment variable BOT_TOKEN to your BotFather token
  (optional) set ALLOWED_IDS to comma-separated Telegram user IDs to
             restrict the bot to your own staff only
  python bot.py

Hosting note (Render free Web Service): the bot also starts a tiny HTTP
health server on $PORT so the platform accepts it as a web service.
"""

import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# Optional: restrict the bot to specific Telegram user IDs (staff only).
# Set ALLOWED_IDS="123456789,987654321" in the environment. Empty = open.
ALLOWED_IDS = {
    int(x) for x in os.environ.get("ALLOWED_IDS", "").replace(" ", "").split(",") if x
}

PUNJAB_URL = "https://mtmis.excise.punjab.gov.pk/"
KPK_URL = "https://www.kpexcise.gov.pk/mvrecords/"
PUNJAB_SMS = "8785"  # Send the registration number by SMS to this number (Punjab only)


# ---------------------------------------------------------------- health server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # keep logs quiet
        pass


def start_health_server() -> None:
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


# ---------------------------------------------------------------- helpers
def is_allowed(user_id: int) -> bool:
    return not ALLOWED_IDS or user_id in ALLOWED_IDS


def normalize_reg(text: str) -> str:
    """Turn 'lea 26 1234' / 'LEA1234' into a tidy display form 'LEA-1234'."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    m = re.match(r"^([A-Z]{2,4})(\d{2,4})$", cleaned)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^([A-Z]{2,4})(\d{2})(\d{3,4})$", cleaned)  # e.g. LEA261234
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return cleaned


def looks_like_reg(text: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text)
    return 5 <= len(cleaned) <= 10 and any(c.isdigit() for c in cleaned) and any(
        c.isalpha() for c in cleaned
    )


def province_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🟢 Punjab (MTMIS)", callback_data="prov:punjab"),
                InlineKeyboardButton("🔵 KPK (Excise)", callback_data="prov:kpk"),
            ]
        ]
    )


# ---------------------------------------------------------------- handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Ye bot sirf showroom staff ke liye hai.")
        return
    context.user_data.pop("province", None)
    await update.message.reply_text(
        "🏍️ *Bike Registration Checker*\n\n"
        "Assalam-o-Alaikum! Bike ka registration number check karne ke liye "
        "pehle province select karein:",
        parse_mode="Markdown",
        reply_markup=province_keyboard(),
    )


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🪪 Aap ki Telegram User ID: `{update.effective_user.id}`\n"
        "Staff restriction ke liye is ID ko ALLOWED_IDS mein shamil karein.",
        parse_mode="Markdown",
    )


async def province_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_allowed(query.from_user.id):
        await query.edit_message_text("⛔ Ye bot sirf showroom staff ke liye hai.")
        return
    province = query.data.split(":", 1)[1]
    context.user_data["province"] = province
    label = "Punjab" if province == "punjab" else "KPK"
    await query.edit_message_text(
        f"✅ Province: *{label}*\n\n"
        "Ab bike ka registration number bhejein.\n"
        "Example: `LEA-1234` ya `LEA 1234`",
        parse_mode="Markdown",
    )


async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Ye bot sirf showroom staff ke liye hai.")
        return
    text = (update.message.text or "").strip()
    province = context.user_data.get("province")

    if not province:
        await update.message.reply_text(
            "Pehle province select karein:", reply_markup=province_keyboard()
        )
        return

    if not looks_like_reg(text):
        await update.message.reply_text(
            "⚠️ Ye registration number nahi lagta. Sirf number bhejein, "
            "example: `LEA-1234`",
            parse_mode="Markdown",
        )
        return

    reg = normalize_reg(text)
    if province == "punjab":
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔎 MTMIS Punjab par check karein", url=PUNJAB_URL)]]
        )
        await update.message.reply_text(
            f"🏍️ *Bike Number:* `{reg}`\n"
            f"📍 *Province:* Punjab\n\n"
            "Neeche wale button se official MTMIS page kholein, number "
            f"`{reg}` likhein aur Search dabayein — owner ka naam, engine/chassis "
            "number aur token tax ki detail aa jayegi.\n\n"
            f"📩 *SMS tareeqa (bina internet):* number `{reg}` likh kar "
            f"*{PUNJAB_SMS}* par SMS karein, detail reply mein aa jayegi.\n\n"
            "Aglay number ke liye bas naya number bhej dein, ya /start se "
            "province badlein.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔎 KPK Excise par check karein", url=KPK_URL)]]
        )
        await update.message.reply_text(
            f"🏍️ *Bike Number:* `{reg}`\n"
            f"📍 *Province:* KPK\n\n"
            "Neeche wale button se official KPK Excise records page kholein, "
            "district select karke number "
            f"`{reg}` likhein aur Search dabayein — registration ki detail "
            "aa jayegi.\n\n"
            "Note: KPK ki website kabhi kabhi band hoti hai — aisi surat mein "
            "kuch dair baad dobara try karein.\n\n"
            "Aglay number ke liye bas naya number bhej dein, ya /start se "
            "province badlein.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


# ---------------------------------------------------------------- main
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN environment variable is not set. "
            "Get the token from @BotFather and set it before running."
        )

    threading.Thread(target=start_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(CallbackQueryHandler(province_chosen, pattern=r"^prov:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
