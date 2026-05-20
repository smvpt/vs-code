"""
Простой парсер времени на регулярках — без dateparser.
Понимает русский язык: "через 2 часа", "завтра в 14:00", "в пятницу в 18:30" и т.д.
"""
import re
from datetime import datetime, timedelta
from typing import Optional

import pytz

# ── Дни недели ────────────────────────────────────────────────────────────────
_WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2,
    "четверг": 3, "пятницу": 4, "пятница": 4,
    "субботу": 5, "суббота": 5, "воскресенье": 6, "воскресенья": 6,
}

_UNITS = {
    "минут": 1, "минуту": 1, "минуты": 1,
    "час": 60, "часа": 60, "часов": 60, "часу": 60,
    "день": 1440, "дня": 1440, "дней": 1440,
    "сутки": 1440, "суток": 1440,
}

# ── Паттерны времени ──────────────────────────────────────────────────────────
# "в 14:00" или "в 14.00"
_RE_CLOCK = re.compile(r"\bв\s+(\d{1,2})[.:](\d{2})\b", re.IGNORECASE)
# просто "14:00"
_RE_CLOCK_BARE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
# "через X минут/часов/дней"
_RE_DELTA = re.compile(
    r"\bчерез\s+(\d+)\s+(минут\w*|час\w*|ден\w*|дн\w*|сутк\w*)",
    re.IGNORECASE | re.UNICODE,
)
# "завтра", "послезавтра", "сегодня"
_RE_DAY_WORD = re.compile(r"\b(послезавтра|завтра|сегодня)\b", re.IGNORECASE | re.UNICODE)
# "в понедельник" и т.д.
_RE_WEEKDAY = re.compile(
    r"\bв\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b",
    re.IGNORECASE | re.UNICODE,
)
# "25.12.2025"
_RE_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def _extract_clock(text: str):
    """Возвращает (hour, minute) если нашли время, иначе None."""
    m = _RE_CLOCK.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _RE_CLOCK_BARE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _remove_time_parts(text: str) -> str:
    """Вырезает всё что относится ко времени, оставляет смысловой текст."""
    text = _RE_DELTA.sub("", text)
    text = _RE_DAY_WORD.sub("", text)
    text = _RE_WEEKDAY.sub("", text)
    text = _RE_DATE.sub("", text)
    text = _RE_CLOCK.sub("", text)
    text = _RE_CLOCK_BARE.sub("", text)
    # убираем одиночные предлоги и мусор
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"^\s*(в|на|о|об|и|,|\.)\s*", "", text, flags=re.IGNORECASE | re.UNICODE)
    text = re.sub(r"\s*(в|на|о|об|и|,|\.)\s*$", "", text, flags=re.IGNORECASE | re.UNICODE)
    return text.strip()


def parse_time_only(user_input: str, timezone: str) -> Optional[datetime]:
    """
    Парсит ТОЛЬКО время из короткого ввода.
    Используется на шаге уточнения когда текст напоминания уже известен.
    """
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    text = user_input.strip()

    return _parse_dt(text, tz, now)


def parse_reminder(user_input: str, timezone: str) -> dict:
    """
    Парсит свободный текст в напоминание.

    Возвращает dict:
      text         — текст напоминания (или None)
      datetime     — aware datetime или None
      raw_time     — найденная строка времени
      ambiguous    — True если время есть но текст пустой
      time_missing — True если время не распозналось
    """
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    text = user_input.strip()

    parsed_dt = _parse_dt(text, tz, now)
    reminder_text = _remove_time_parts(text) if parsed_dt else None

    if parsed_dt:
        raw_time = _find_raw_time(text)
        return {
            "text": reminder_text or None,
            "datetime": parsed_dt,
            "raw_time": raw_time or text,
            "ambiguous": not bool(reminder_text),
            "time_missing": False,
        }

    # Время не найдено
    return {
        "text": text,
        "datetime": None,
        "raw_time": None,
        "ambiguous": False,
        "time_missing": True,
    }


def _parse_dt(text: str, tz: pytz.BaseTzInfo, now: datetime) -> Optional[datetime]:
    """Основная логика: определяет дату и время из текста."""

    # 1. "через X минут/часов"
    m = _RE_DELTA.search(text)
    if m:
        amount = int(m.group(1))
        unit_str = m.group(2).lower()
        minutes = _match_unit(unit_str) * amount
        if minutes:
            return now + timedelta(minutes=minutes)

    # 2. Определяем базовую дату
    base_date = None

    m = _RE_DAY_WORD.search(text)
    if m:
        word = m.group(1).lower()
        if word == "сегодня":
            base_date = now.date()
        elif word == "завтра":
            base_date = (now + timedelta(days=1)).date()
        elif word == "послезавтра":
            base_date = (now + timedelta(days=2)).date()

    if base_date is None:
        m = _RE_WEEKDAY.search(text)
        if m:
            target_wd = _WEEKDAYS.get(m.group(1).lower())
            if target_wd is not None:
                current_wd = now.weekday()
                days_ahead = (target_wd - current_wd) % 7
                if days_ahead == 0:
                    days_ahead = 7  # следующая неделя
                base_date = (now + timedelta(days=days_ahead)).date()

    if base_date is None:
        m = _RE_DATE.search(text)
        if m:
            try:
                from datetime import date
                base_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

    # 3. Извлекаем время суток
    clock = _extract_clock(text)

    if base_date and clock:
        h, mi = clock
        if 0 <= h <= 23 and 0 <= mi <= 59:
            dt = tz.localize(datetime(base_date.year, base_date.month, base_date.day, h, mi))
            if dt > now:
                return dt

    # 4. Только дата без времени — ставим 09:00
    if base_date and not clock:
        dt = tz.localize(datetime(base_date.year, base_date.month, base_date.day, 9, 0))
        if dt <= now:
            dt = tz.localize(datetime(base_date.year, base_date.month, base_date.day, 12, 0))
        if dt > now:
            return dt

    # 5. Только время без даты — сегодня или завтра
    if clock and not base_date:
        h, mi = clock
        if 0 <= h <= 23 and 0 <= mi <= 59:
            candidate = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

    return None


def _match_unit(unit_str: str) -> int:
    """Возвращает количество минут для единицы времени."""
    for key, val in _UNITS.items():
        if unit_str.startswith(key[:4]):
            return val
    return 0


def _find_raw_time(text: str) -> Optional[str]:
    """Находит временну́ю подстроку для отображения пользователю."""
    for pattern in [_RE_DELTA, _RE_DAY_WORD, _RE_WEEKDAY, _RE_DATE]:
        m = pattern.search(text)
        if m:
            # Добавляем clock если есть рядом
            clock = _RE_CLOCK.search(text) or _RE_CLOCK_BARE.search(text)
            if clock:
                return f"{m.group(0).strip()} в {clock.group(0).replace('в ', '').strip()}"
            return m.group(0).strip()
    return None