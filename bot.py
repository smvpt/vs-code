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

# Хранение состояния диалога: {user_id: {"step": ..., ...}}
user_state = {}



class ReminderBase(ABC):
    """Абстрактный базовый класс для напоминаний."""

    def __init__(self, text: str, remind_at: str):
        self._text = text               # protected
        self.__remind_at = remind_at    # private — инкапсуляция

    @property
    def text(self):
        return self._text

    @property
    def remind_at(self):
        return self.__remind_at         # доступ только через property

    @abstractmethod
    def format_message(self) -> str:
        """Полиморфный метод — каждый подкласс форматирует по-своему."""
        ...

    def __str__(self):
        return f"[{self.__class__.__name__}] {self._text} @ {self.__remind_at}"


class SimpleReminder(ReminderBase):
    """Обычное напоминание."""

    def format_message(self) -> str:
        return f"🔔 {self._text}"


class UrgentReminder(ReminderBase):
    """Срочное напоминание — выделяется визуально."""

    def __init__(self, text: str, remind_at: str):
        super().__init__(f"❗ СРОЧНО: {text}", remind_at)

    def format_message(self) -> str:
        return f"🚨 *СРОЧНО* 🚨\n{self._text}"


def make_reminder_obj(text: str, remind_at: str) -> ReminderBase:
    """Фабричная функция: возвращает нужный подкласс по ключевым словам."""
    urgent_keywords = ("срочно", "важно", "немедленно", "asap", "urgent")
    if any(kw in text.lower() for kw in urgent_keywords):
        return UrgentReminder(text, remind_at)
    return SimpleReminder(text, remind_at)



def merge_sort_reminders(reminders: list) -> list:
    """
    Сортирует напоминания по полю 'datetime' алгоритмом Merge Sort.
    Сложность: O(n log n) — эффективнее insertion sort O(n²) на больших данных.
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
        # ISO-строки datetime сравниваются лексикографически = хронологически
        if left[i]["datetime"] <= right[j]["datetime"]:
            result.append(left[i]); i += 1
        else:
            result.append(right[j]); j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result


# ─── Helpers ──────────────────────────────────────────────────────────────────

def log_query(user_id, username, text):
    """Сохраняет все запросы пользователей в БД для Django-админки."""
    try:
        db.save_user_query(user_id, username, text)
    except Exception as e:
        logger.error(f"Ошибка сохранения запроса: {e}")


def save_and_confirm(message, text, dt, tz_name):
    """Сохраняет напоминание и подтверждает пользователю."""
    user_id = message.from_user.id
    reminder_id = db.add_reminder(user_id, text, dt.isoformat())

    obj = make_reminder_obj(text, dt.isoformat())
    logger.info(str(obj))

    tz = pytz.timezone(tz_name)
    formatted = dt.astimezone(tz).strftime("%d.%m.%Y в %H:%M")
    bot.send_message(
        message.chat.id,
        f"✅ *Напоминание создано!*\n\n"
        f"📝 {text}\n"
        f"🗓 {formatted} ({tz_name})\n"
        f"🆔 ID: `{reminder_id}`",
        parse_mode="Markdown",
    )


def delete_keyboard(reminders):
    kb = types.InlineKeyboardMarkup()
    for r in reminders:
        short = r["text"][:35] + "…" if len(r["text"]) > 35 else r["text"]
        kb.add(types.InlineKeyboardButton(f"❌ #{r['id']} {short}", callback_data=f"del_{r['id']}"))
    return kb


def timezone_keyboard():
    zones = [
        ("🇷🇺 Москва",      "Europe/Moscow"),
        ("🇷🇺 Новосибирск", "Asia/Novosibirsk"),
        ("🇷🇺 Владивосток", "Asia/Vladivostok"),
        ("🇰🇿 Алматы",      "Asia/Almaty"),
        ("🇺🇦 Киев",        "Europe/Kiev"),
        ("🇧🇾 Минск",       "Europe/Minsk"),
        ("🇬🇧 Лондон",      "Europe/London"),
        ("🇩🇪 Берлин",      "Europe/Berlin"),
        ("🇺🇸 Нью-Йорк",    "America/New_York"),
    ]
    kb = types.InlineKeyboardMarkup(row_width=1)
    for label, tz in zones:
        kb.add(types.InlineKeyboardButton(label, callback_data=f"tz_{tz}"))
    return kb


# ─── /start ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def start(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/start")

    user = message.from_user
    db.add_user(user.id, user.first_name)
    tz = db.get_timezone(user.id)
    bot.send_message(
        message.chat.id,
        f"👋 Привет, *{user.first_name}*!\n\n"
        "Просто напишите что и когда — создам напоминание:\n\n"
        "• _стрим через 2 часа_\n"
        "• _встреча завтра в 15:00_\n"
        "• _позвонить маме в пятницу в 18:30_\n\n"
        "📋 /list — список напоминаний\n"
        "🔍 /find <слово> — поиск напоминаний\n"
        "🌤 /weather [город] — погода\n"
        "💱 /rates — курс валют\n"
        "🌍 /timezone — часовой пояс\n"
        "ℹ️ /help — помощь\n\n"
        f"🕐 Ваш часовой пояс: *{tz}*",
        parse_mode="Markdown",
    )


# ─── /help ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["help"])
def help_command(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/help")
    bot.send_message(
        message.chat.id,
        "📖 *Как создать напоминание*\n\n"
        "Напишите свободным текстом:\n\n"
        "⏱ *Относительное время:*\n"
        "  • `через 30 минут позвонить`\n"
        "  • `кофе через час`\n\n"
        "📅 *С датой и временем:*\n"
        "  • `завтра в 9:00 зарядка`\n"
        "  • `в пятницу в 18:00 встреча`\n"
        "  • `послезавтра в 12:30 обед`\n\n"
        "Если время непонятно — уточню.\n\n"
        "📋 /list — список напоминаний\n"
        "🔍 /find <слово> — поиск по напоминаниям\n"
        "🌤 /weather [город] — текущая погода\n"
        "💱 /rates — курс USD и EUR\n"
        "🌍 /timezone — изменить часовой пояс\n"
        "❌ /cancel — отменить текущее действие",
        parse_mode="Markdown",
    )


# ─── /list ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["list"])
def list_reminders(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    log_query(user_id, username, "/list")

    # ЛАБ 2_03: сортируем через Merge Sort O(n log n)
    reminders = merge_sort_reminders(db.get_reminders(user_id))

    if not reminders:
        bot.send_message(message.chat.id, "📭 Нет активных напоминаний.")
        return

    tz_name = db.get_timezone(user_id)
    tz = pytz.timezone(tz_name)
    text = f"📋 *Напоминания* ({len(reminders)}):\n\n"

    for r in reminders:
        dt = datetime.fromisoformat(r["datetime"]).astimezone(tz)
        short = r["text"][:40] + "…" if len(r["text"]) > 40 else r["text"]
        text += f"🔔 *{short}*\n   🗓 {dt.strftime('%d.%m.%Y %H:%M')}\n   🆔 `{r['id']}`\n\n"

    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=delete_keyboard(reminders))


# ─── /timezone ────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["timezone"])
def cmd_timezone(message):
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/timezone")
    bot.send_message(message.chat.id, "🌍 Выберите часовой пояс:", reply_markup=timezone_keyboard())


# ─── /cancel ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    user_state.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "❌ Отменено.")



@bot.message_handler(commands=["find"])
def find_reminders(message):
    """
    Ищет напоминания по ключевому слову или регулярному выражению.
    Пример: /find встреч  →  найдёт 'встреча', 'встречи', 'встречу'
    Пример: /find \\d{2}:\\d{2}  →  найдёт напоминания со временем вида 12:30
    """
    username = message.from_user.username or message.from_user.first_name
    user_id  = message.from_user.id
    log_query(user_id, username, message.text)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(
            message.chat.id,
            "🔍 Использование: `/find <ключевое слово или regex>`\n\n"
            "Примеры:\n"
            "• `/find встреч` — найдёт всё со словом встреча\n"
            "• `/find \\d{2}:\\d{2}` — напоминания со временем вида 12:30",
            parse_mode="Markdown",
        )
        return

    query = parts[1].strip()

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        bot.send_message(message.chat.id, "❌ Некорректное регулярное выражение.")
        return

    reminders = db.get_reminders(user_id)
    tz_name   = db.get_timezone(user_id)
    tz        = pytz.timezone(tz_name)

    found = []
    for r in reminders:
        dt_local = datetime.fromisoformat(r["datetime"]).astimezone(tz)
        # ищем по тексту И по дате/времени в формате пользователя
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
            f"🔍 По запросу `{query}` ничего не найдено.",
            parse_mode="Markdown",
        )
        return

    count  = len(found)
    ending = "е" if count == 1 else "я" if count in (2, 3, 4) else "й"
    lines  = [f"🔍 Найдено *{count}* напоминани{ending} по `{query}`:\n"]

    for r, dt in found:
        short      = r["text"][:50] + "…" if len(r["text"]) > 50 else r["text"]
        dt_str     = dt.strftime("%d.%m.%Y %H:%M")
        searchable = f"{r['text']} {dt_str}"
        matches    = pattern.findall(searchable)    # re.findall() — все совпадения
        lines.append(
            f"🔔 *{short}*\n"
            f"   🗓 {dt_str} | 🆔 `{r['id']}`\n"
            f"   🎯 Совпадений: {len(matches)}"
        )

    bot.send_message(
        message.chat.id,
        "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=delete_keyboard([r for r, _ in found]),
    )



@bot.message_handler(commands=["weather"])
def get_weather(message):
    """
    Получает погоду для любого города через OpenWeather API.
    Использование: /weather  или  /weather Astana
    """
    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, message.text)

    # Часть 4: параметры запроса через params
    parts = message.text.split(maxsplit=1)
    city  = parts[1].strip() if len(parts) > 1 else "Almaty"

    api_key = "4b5824b85143ae2fcacb616d6382baf3"    # Часть 5: API-ключ
    params  = {
        "q":     city,
        "appid": api_key,
        "units": "metric",
        "lang":  "ru",
    }

    try:
        # Часть 1: GET-запрос
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params=params,
            timeout=10,
        )

        # Часть 3: обработка ошибок HTTP
        if response.status_code == 401:
            bot.reply_to(message, "🔑 Неверный API-ключ OpenWeather (ошибка 401).")
            return
        if response.status_code == 404:
            bot.reply_to(message, f"🌍 Город *{city}* не найден.", parse_mode="Markdown")
            return
        response.raise_for_status()

        # Часть 2: работа с JSON — вложенные поля
        data        = response.json()
        temp        = data["main"]["temp"]
        feels_like  = data["main"]["feels_like"]
        humidity    = data["main"]["humidity"]
        wind_speed  = data["wind"]["speed"]
        cloudiness  = data["clouds"]["all"]
        description = data["weather"][0]["description"]
        country     = data["sys"]["country"]

        # Часть 6: краткий анализ данных
        comfort = "😌 Комфортно" if abs(temp - feels_like) < 3 else "🧥 Ощущается иначе"

        bot.reply_to(
            message,
            f"🌤 *Погода в {city}, {country}*\n\n"
            f"🌡 Температура: *{temp:.1f}°C* (ощущается {feels_like:.1f}°C)\n"
            f"🌥 {description.capitalize()}\n"
            f"💧 Влажность: {humidity}%\n"
            f"💨 Ветер: {wind_speed} м/с\n"
            f"☁️ Облачность: {cloudiness}%\n\n"
            f"{comfort}",
            parse_mode="Markdown",
        )

    except requests.exceptions.ConnectionError:
        bot.reply_to(message, "❌ Нет соединения с OpenWeather.")
    except requests.exceptions.Timeout:
        bot.reply_to(message, "⏱ Сервер погоды не отвечает.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")



@bot.message_handler(commands=["rates"])
def get_exchange_rates(message):
    """
    Получает курсы валют к тенге с сайта Национального банка РК (nationalbank.kz).
    Нацбанк отдаёт данные в XML — парсим через BeautifulSoup с xml-парсером.
    Показывает: USD, EUR, RUB, CNY.
    """
    import time

    username = message.from_user.username or message.from_user.first_name
    log_query(message.from_user.id, username, "/rates")

    try:
        today = datetime.now().strftime("%d.%m.%Y")
        url   = f"https://nationalbank.kz/rss/get_rates.cfm?fdate={today}"

        # Часть 1: GET-запрос
        response = requests.get(url, timeout=15)
        response.raise_for_status()     # Часть 3: обработка ошибок HTTP

        # Парсинг XML через BeautifulSoup
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
                    rates[code] = val / qty      # приводим к 1 единице
                except ValueError:
                    pass

        time.sleep(1)   # вежливая пауза между запросами

        if rates:
            emojis = {"USD": "🇺🇸", "EUR": "🇪🇺", "RUB": "🇷🇺", "CNY": "🇨🇳"}
            lines  = [f"💱 *Курсы Нацбанка РК на {today}*\n"]
            for code in ["USD", "EUR", "RUB", "CNY"]:
                if code in rates:
                    lines.append(f"{emojis[code]} *{code}* → `{rates[code]:.2f}` ₸")
            bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "⚠️ Нацбанк не вернул данные. Попробуйте позже.")

    except requests.exceptions.ConnectionError:
        bot.send_message(message.chat.id, "❌ Нет соединения с nationalbank.kz.")
    except requests.exceptions.Timeout:
        bot.send_message(message.chat.id, "⏱ Сервер Нацбанка не отвечает.")
    except requests.exceptions.HTTPError as e:
        bot.send_message(message.chat.id, f"❌ Ошибка сервера: {e}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Непредвиденная ошибка: {e}")


# ─── Inline callbacks ─────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def cb_delete(call):
    reminder_id = int(call.data[4:])
    success = db.delete_reminder(reminder_id, call.from_user.id)
    bot.answer_callback_query(call.id)
    if success:
        bot.edit_message_text(f"✅ Напоминание #{reminder_id} удалено.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Не найдено.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("tz_"))
def cb_timezone(call):
    tz_name = call.data[3:]
    db.set_timezone(call.from_user.id, tz_name)
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"✅ Часовой пояс: *{tz_name}*", call.message.chat.id, call.message.message_id, parse_mode="Markdown")


# ─── Умный ввод — NLP + диалог уточнения ─────────────────────────────────────

@bot.message_handler(func=lambda message: True)
def handle_smart_input(message):
    user_id  = message.from_user.id
    text     = message.text.strip()
    username = message.from_user.username or message.from_user.first_name
    tz_name  = db.get_timezone(user_id)
    state    = user_state.get(user_id)

    log_query(user_id, username, text)

    # Шаг уточнения: ждём время
    if state and state.get("step") == "waiting_time":
        dt = parse_time_only(text, tz_name)
        if dt:
            reminder_text = state["reminder_text"]
            user_state.pop(user_id, None)
            save_and_confirm(message, reminder_text, dt, tz_name)
        else:
            bot.send_message(
                message.chat.id,
                "❌ Не понял время. Попробуйте:\n_через 2 часа, завтра в 10:00, в пятницу в 18:00_",
                parse_mode="Markdown",
            )
        return

    # Шаг уточнения: ждём текст
    if state and state.get("step") == "waiting_text":
        dt = datetime.fromisoformat(state["datetime"])
        user_state.pop(user_id, None)
        save_and_confirm(message, text, dt, tz_name)
        return

    # NLP-парсинг
    result = parse_reminder(text, tz_name)

    if result["datetime"] and result["text"]:
        save_and_confirm(message, result["text"], result["datetime"], tz_name)

    elif result["datetime"] and result["ambiguous"]:
        user_state[user_id] = {"step": "waiting_text", "datetime": result["datetime"].isoformat()}
        bot.send_message(message.chat.id, "🕐 Время понял.\n\nО чём напомнить?")

    elif result["time_missing"]:
        user_state[user_id] = {"step": "waiting_time", "reminder_text": result["text"]}
        bot.send_message(
            message.chat.id,
            f"📝 Напомнить: *{result['text']}*\n\n"
            "⏰ Когда?\n_через 2 часа, завтра в 10:00, в пятницу в 18:00..._",
            parse_mode="Markdown",
        )
    else:
        bot.reply_to(message, "🤔 Не смог распознать. Попробуйте: _встреча завтра в 15:00_\nИли /help", parse_mode="Markdown")


# ─── Запуск ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t = threading.Thread(target=start_scheduler, args=(bot, db), daemon=True)
    t.start()
    logger.info("Бот на pyTelegramBotAPI запущен...")
    bot.infinity_polling()