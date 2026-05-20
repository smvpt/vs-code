import telebot
from telebot import types
import logging
import threading
from datetime import datetime
import pytz
import re
import requests
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup

from config import BOT_TOKEN, DEFAULT_TIMEZONE
from database import Database
from nlp_parser import parse_reminder, parse_time_only
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)
db = Database()

# Dialog state storage: {user_id: {"step": ..., ...}}
user_state = {}


class ReminderBase(ABC):
    """Abstract base class for reminders."""

    def __init__(self, text: str, remind_at: str):
        self._text = text               # protected
        self.__remind_at = remind_at    # private — encapsulation

    @property
    def text(self):
        return self._text

    @property
    def remind_at(self):
        return self.__remind_at         # access via property only

    @abstractmethod
    def format_message(self) -> str:
        """Polymorphic method — each subclass formats differently."""
        ...

    def __str__(self):
        return f"[{self.__class__.__name__}] {self._text} @ {self.__remind_at}"


class SimpleReminder(ReminderBase):
    """Regular reminder."""

    def format_message(self) -> str:
        return f"🔔 {self._text}"


class UrgentReminder(ReminderBase):
    """Urgent reminder — visually highlighted."""

    def __init__(self, text: str, remind_at: str):
        super().__init__(f"❗ URGENT: {text}", remind_at)

    def format_message(self) -> str:
        return f"🚨 *URGENT* 🚨\n{self._text}"


def make_reminder_obj(text: str, remind_at: str) -> ReminderBase:
    """Factory function: returns the appropriate subclass based on keywords."""
    urgent_keywords = ("срочно", "важно", "немедленно", "asap", "urgent", "important", "immediately")
    if any(kw in text.lower() for kw in urgent_keywords):
        return UrgentReminder(text, remind_at)
    return SimpleReminder(text, remind_at)


def merge_sort_reminders(reminders: list) -> list:
    """
    Sorts reminders by 'datetime' field using Merge Sort algorithm.
    Complexity: O(n log n)
    """
    if len(reminders) <= 1:
        return reminders

    mid = len(reminders) // 2
    left  = merge_sort_reminders(reminders[:mid])
    right = merge_sort_reminders(reminders[mid:])
    return _merge(left, right)


def _merge(left: list, right: list) -> list:
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        if left[i]["datetime"] <= right[j]["datetime"]:
            result.append(left[i]); i += 1
        else:
            result.append(right[j]); j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result


# ─── Helpers & Keyboards ──────────────────────────────────────────────────────

def log_query(user_id, username, text):
    """Saves all user queries to DB."""
    try:
        db.save_user_query(user_id, username, text)
    except Exception as e:
        logger.error(f"Error saving query: {e}")


def save_and_confirm(message, text, dt, tz_name):
    """Saves the reminder and sends a confirmation to the user."""
    user_id = message.from_user.id
    reminder_id = db.add_reminder(user_id, text, dt.isoformat())

    obj = make_reminder_obj(text, dt.isoformat())
    logger.info(str(obj))

    tz = pytz.timezone(tz_name)
    formatted = dt.astimezone(tz).strftime("%B %d, %Y at %H:%M")
    bot.send_message(
        message.chat.id,
        f"✅ *Reminder created!*\n\n"
        f"📝 {text}\n"
        f"🗓 {formatted} ({tz_name})\n"
        f"🆔 ID: `{reminder_id}`",
        parse_mode="Markdown",
    )


def main_menu_keyboard():
    """Creates a persistent reply keyboard with main commands."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📋 List"),
        types.KeyboardButton("🔍 Find"),
        types.KeyboardButton("🌤 Weather"),
        types.KeyboardButton("💱 Rates"),
        types.KeyboardButton("🌍 Timezone"),
        types.KeyboardButton("ℹ️ Help")
    )
    return kb


def delete_keyboard(reminders):
    kb = types.InlineKeyboardMarkup()
    for r in reminders:
        short = r["text"][:35] + "…" if len(r["text"]) > 35 else r["text"]
        kb.add(types.InlineKeyboardButton(f"❌ #{r['id']} {short}", callback_data=f"del_{r['id']}"))
    return kb


def timezone_keyboard():
    zones = [
        ("🇬🇧 London",      "Europe/London"),
        ("🇩🇪 Berlin",      "Europe/Berlin"),
        ("🇺🇸 New York",    "America/New_York"),
        ("🇷🇺 Moscow",      "Europe/Moscow"),
        ("🇰🇿 Almaty",      "Asia/Almaty"),
        ("🇺🇦 Kyiv",        "Europe/Kyiv"),
        ("🇧🇾 Minsk",       "Europe/Minsk"),
        ("🇷🇺 Novosibirsk", "Asia/Novosibirsk"),
        ("🇷🇺 Vladivostok", "Asia/Vladivostok"),
    ]
    kb = types.InlineKeyboardMarkup(row_width=1)
    for label, tz in zones:
        kb.add(types.InlineKeyboardButton(label, callback_data=f"tz_{tz}"))
    return kb


# ─── Command Logic Functions ──────────────────────────────────────────────────

def show_start(message):
    user = message.from_user
    db.add_user(user.id, user.first_name)
    tz = db.get_timezone(user.id)
    
    bot.send_message(
        message.chat.id,
        f"👋 Hello, *{user.first_name}*!\n\n"
        "Just type what and when you want to be reminded of, and I'll handle it:\n\n"
        "• _stream in 2 hours_\n"
        "• _meeting tomorrow at 15:00_\n"
        "• _call mom on Friday at 18:30_\n\n"
        "Use the menu buttons below to manage your reminders and tools.\n\n"
        f"🕐 Your current timezone: *{tz}*",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


def show_help(message):
    bot.send_message(
        message.chat.id,
        "📖 *How to create a reminder*\n\n"
        "Type your reminder using natural language:\n\n"
        "⏱ *Relative time:*\n"
        "  • `call in 30 minutes`\n"
        "  • `coffee in an hour`\n\n"
        "📅 *With date and time:*\n"
        "  • `tomorrow at 9:00 workout`\n"
        "  • `friday at 18:00 meeting`\n\n"
        "If the time is unclear, I will ask you to clarify.\n\n"
        "👇 Use the menu buttons below to navigate quickly.",
        parse_mode="Markdown"
    )


def show_list(message):
    user_id = message.from_user.id
    reminders = merge_sort_reminders(db.get_reminders(user_id))

    if not reminders:
        bot.send_message(message.chat.id, "📭 You have no active reminders.")
        return

    tz_name = db.get_timezone(user_id)
    tz = pytz.timezone(tz_name)
    text = f"📋 *Your Reminders* ({len(reminders)}):\n\n"

    for r in reminders:
        dt = datetime.fromisoformat(r["datetime"]).astimezone(tz)
        short = r["text"][:40] + "…" if len(r["text"]) > 40 else r["text"]
        text += f"🔔 *{short}*\n   🗓 {dt.strftime('%d.%m.%Y %H:%M')}\n   🆔 `{r['id']}`\n\n"

    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=delete_keyboard(reminders))


def show_timezone(message):
    bot.send_message(message.chat.id, "🌍 Select your timezone:", reply_markup=timezone_keyboard())


def initiate_find(message):
    bot.send_message(
        message.chat.id,
        "🔍 Please type `/find <keyword or regex>` to search.\n\n"
        "Examples:\n"
        "• `/find meeting` — finds everything containing 'meeting'\n"
        "• `/find \\d{2}:\\d{2}` — finds reminders with timestamps like 12:30",
        parse_mode="Markdown"
    )


def initiate_weather(message):
    bot.send_message(
        message.chat.id,
        "🌤 Please type `/weather <city name>` to check the weather.\n"
        "Example: `/weather London` or `/weather Almaty`",
        parse_mode="Markdown"
    )


# ─── Telegram Command Handlers ────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/start")
    show_start(message)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/help")
    show_help(message)


@bot.message_handler(commands=["list"])
def cmd_list(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/list")
    show_list(message)


@bot.message_handler(commands=["timezone"])
def cmd_timezone(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/timezone")
    show_timezone(message)


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    user_state.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "❌ Action canceled.", reply_markup=main_menu_keyboard())


@bot.message_handler(commands=["find"])
def find_reminders(message):
    username = message.from_user.username or message.from_user.first_name
    user_id  = message.from_user.id
    log_query(user_id, username, message.text)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        initiate_find(message)
        return

    query = parts[1].strip()

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        bot.send_message(message.chat.id, "❌ Invalid regular expression.")
        return

    reminders = db.get_reminders(user_id)
    tz_name   = db.get_timezone(user_id)
    tz        = pytz.timezone(tz_name)

    found = []
    for r in reminders:
        dt_local = datetime.fromisoformat(r["datetime"]).astimezone(tz)
        searchable = (
            f"{r['text']} "
            f"{dt_local.strftime('%d.%m.%Y')} "
            f"{dt_local.strftime('%H:%M')} "
            f"{dt_local.strftime('%d.%m.%Y %H:%M')}"
        )
        if pattern.search(searchable):
            found.append((r, dt_local))

    if not found:
        bot.send_message(
            message.chat.id,
            f"🔍 No reminders found for `{query}`.",
            parse_mode="Markdown",
        )
        return

    count = len(found)
    ending = "s" if count > 1 else ""
    lines  = [f"🔍 Found *{count}* reminder{ending} for `{query}`:\n"]

    for r, dt in found:
        short      = r["text"][:50] + "…" if len(r["text"]) > 50 else r["text"]
        dt_str     = dt.strftime("%d.%m.%Y %H:%M")
        searchable = f"{r['text']} {dt_str}"
        matches    = pattern.findall(searchable)
        lines.append(
            f"🔔 *{short}*\n"
            f"   🗓 {dt_str} | 🆔 `{r['id']}`\n"
            f"   🎯 Matches: {len(matches)}"
        )

    bot.send_message(
        message.chat.id,
        "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=delete_keyboard([r for r, _ in found]),
    )


@bot.message_handler(commands=["weather"])
def get_weather(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, message.text)

    parts = message.text.split(maxsplit=1)
    city  = parts[1].strip() if len(parts) > 1 else "Almaty"

    api_key = "4b5824b85143ae2fcacb616d6382baf3"
    params  = {
        "q":     city,
        "appid": api_key,
        "units": "metric",
        "lang":  "en",
    }

    try:
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params=params,
            timeout=10,
        )

        if response.status_code == 401:
            bot.reply_to(message, "🔑 Invalid OpenWeather API key (Error 401).")
            return
        if response.status_code == 404:
            bot.reply_to(message, f"🌍 City *{city}* not found.", parse_mode="Markdown")
            return
        response.raise_for_status()

        data        = response.json()
        temp        = data["main"]["temp"]
        feels_like  = data["main"]["feels_like"]
        humidity    = data["main"]["humidity"]
        wind_speed  = data["wind"]["speed"]
        cloudiness  = data["clouds"]["all"]
        description = data["weather"][0]["description"]
        country     = data["sys"]["country"]

        comfort = "😌 Comfortable" if abs(temp - feels_like) < 3 else "🧥 Feels different"

        bot.reply_to(
            message,
            f"🌤 *Weather in {city}, {country}*\n\n"
            f"🌡 Temperature: *{temp:.1f}°C* (Feels like {feels_like:.1f}°C)\n"
            f"🌥 {description.capitalize()}\n"
            f"💧 Humidity: {humidity}%\n"
            f"💨 Wind: {wind_speed} m/s\n"
            f"☁️ Cloudiness: {cloudiness}%\n\n"
            f"{comfort}",
            parse_mode="Markdown",
        )

    except requests.exceptions.ConnectionError:
        bot.reply_to(message, "❌ Connection to OpenWeather failed.")
    except requests.exceptions.Timeout:
        bot.reply_to(message, "⏱ Weather server timed out.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["rates"])
def get_exchange_rates(message):
    import time

    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/rates")

    try:
        today = datetime.now().strftime("%d.%m.%Y")
        url   = f"https://nationalbank.kz/rss/get_rates.cfm?fdate={today}"

        response = requests.get(url, timeout=15)
        response.raise_for_status()

        soup  = BeautifulSoup(response.content, "xml")
        items = soup.find_all("item")

        target = {"USD", "EUR", "RUB", "CNY"}
        rates  = {}

        for item in items:
            title = item.find("title")
            desc  = item.find("description")
            quant = item.find("quant")
            if not (title and desc):
                continue
            code = title.get_text(strip=True)
            if code in target:
                try:
                    qty = int(quant.get_text(strip=True)) if quant else 1
                    val = float(desc.get_text(strip=True))
                    rates[code] = val / qty
                except ValueError:
                    pass

        time.sleep(1)

        if rates:
            emojis = {"USD": "🇺🇸", "EUR": "🇪🇺", "RUB": "🇷🇺", "CNY": "🇨🇳"}
            lines  = [f"💱 *NBK Exchange Rates for {today}*\n"]
            for code in ["USD", "EUR", "RUB", "CNY"]:
                if code in rates:
                    lines.append(f"{emojis[code]} *{code}* → `{rates[code]:.2f}` ₸")
            bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "⚠️ National Bank returned no data. Please try again later.")

    except requests.exceptions.ConnectionError:
        bot.send_message(message.chat.id, "❌ Connection to nationalbank.kz failed.")
    except requests.exceptions.Timeout:
        bot.send_message(message.chat.id, "⏱ National Bank server timed out.")
    except requests.exceptions.HTTPError as e:
        bot.send_message(message.chat.id, f"❌ Server error: {e}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Unexpected error: {e}")


# ─── Inline callbacks ─────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def cb_delete(call):
    reminder_id = int(call.data[4:])
    success = db.delete_reminder(reminder_id, call.from_user.id)
    bot.answer_callback_query(call.id)
    if success:
        bot.edit_message_text(f"✅ Reminder #{reminder_id} deleted.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Not found.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("tz_"))
def cb_timezone(call):
    tz_name = call.data[3:]
    db.set_timezone(call.from_user.id, tz_name)
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"✅ Timezone set to: *{tz_name}*", call.message.chat.id, call.message.message_id, parse_mode="Markdown")


# ─── Smart Input / Menu Buttons Processing ────────────────────────────────────

@bot.message_handler(func=lambda message: True)
def handle_smart_input(message):
    user_id  = message.from_user.id
    text     = message.text.strip()
    username = message.from_user.username or message.from_user.first_name
    tz_name  = db.get_timezone(user_id)
    state    = user_state.get(user_id)

    log_query(user_id, username, text)

    # 1. Check if user clicked a menu button
    if text == "📋 List":
        show_list(message)
        return
    elif text == "🔍 Find":
        initiate_find(message)
        return
    elif text == "🌤 Weather":
        initiate_weather(message)
        return
    elif text == "💱 Rates":
        get_exchange_rates(message)
        return
    elif text == "🌍 Timezone":
        show_timezone(message)
        return
    elif text == "ℹ️ Help":
        show_help(message)
        return

    # 2. Handle conversation steps
    if state and state.get("step") == "waiting_time":
        dt = parse_time_only(text, tz_name)
        if dt:
            reminder_text = state["reminder_text"]
            user_state.pop(user_id, None)
            save_and_confirm(message, reminder_text, dt, tz_name)
        else:
            bot.send_message(
                message.chat.id,
                "❌ Could not understand the time. Try:\n_in 2 hours, tomorrow at 10:00, Friday at 18:00_",
                parse_mode="Markdown",
            )
        return

    if state and state.get("step") == "waiting_text":
        dt = datetime.fromisoformat(state["datetime"])
        user_state.pop(user_id, None)
        save_and_confirm(message, text, dt, tz_name)
        return

    # 3. NLP Parsing
    result = parse_reminder(text, tz_name)

    if result["datetime"] and result["text"]:
        save_and_confirm(message, result["text"], result["datetime"], tz_name)

    elif result["datetime"] and result["ambiguous"]:
        user_state[user_id] = {"step": "waiting_text", "datetime": result["datetime"].isoformat()}
        bot.send_message(message.chat.id, "🕐 Time understood.\n\nWhat should I remind you about?")

    elif result["time_missing"]:
        user_state[user_id] = {"step": "waiting_time", "reminder_text": result["text"]}
        bot.send_message(
            message.chat.id,
            f"📝 Remind you to: *{result['text']}*\n\n"
            "⏰ When?\n_in 2 hours, tomorrow at 10:00, Friday at 18:00..._",
            parse_mode="Markdown",
        )
    else:
        bot.reply_to(message, "🤔 I couldn't recognize that. Try: _meeting tomorrow at 15:00_\nOr use ℹ️ Help", parse_mode="Markdown")


# ─── Bot Startup ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t = threading.Thread(target=start_scheduler, args=(bot, db), daemon=True)
    t.start()
    logger.info("Bot on pyTelegramBotAPI started...")
    bot.infinity_polling()