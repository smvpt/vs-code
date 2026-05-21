"""
Advanced time parser using regular expressions — no dateparser required.
Supports English: "in 2 hours", "after 30 mins", "next friday at 18:30", "in a week", etc.
"""
import re
from datetime import datetime, timedelta
from typing import Optional

import pytz

# ── Weekdays ──────────────────────────────────────────────────────────────────
_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_UNITS = {
    "min": 1, "minute": 1,
    "hour": 60, "hr": 60,
    "day": 1440,
    "week": 10080,
    "month": 43200,
}

# ── Time Patterns ─────────────────────────────────────────────────────────────
# "at 14:00" or "at 14.00"
_RE_CLOCK = re.compile(r"\bat\s+(\d{1,2})[.:](\d{2})\b", re.IGNORECASE)
# bare time "14:00"
_RE_CLOCK_BARE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# "in X minutes", "after 2 hours", "in a week", "after a month"
_RE_DELTA = re.compile(
    r"\b(in|after)\s+(\d+|a)\s+(min\w*|hour\w*|hr\w*|day\w*|week\w*|month\w*)",
    re.IGNORECASE,
)

# "today", "tomorrow", "day after tomorrow"
_RE_DAY_WORD = re.compile(
    r"\b(day after tomorrow|tomorrow|today)\b", 
    re.IGNORECASE
)

# "on friday", "on mon", etc.
_RE_WEEKDAY = re.compile(
    r"\bon\s+(monday|mon|tuesday|tue|wednesday|wed|thursday|thu|friday|fri|saturday|sat|sunday|sun)\b",
    re.IGNORECASE,
)

# "next friday", "next monday", etc.
_RE_NEXT_WEEKDAY = re.compile(
    r"\bnext\s+(monday|mon|tuesday|tue|wednesday|wed|thursday|thu|friday|fri|saturday|sat|sunday|sun)\b",
    re.IGNORECASE,
)

# "25.12.2026" or "25/12/2026"
_RE_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")


def _extract_clock(text: str):
    """Returns (hour, minute) if clock pattern is found, otherwise None."""
    m = _RE_CLOCK.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _RE_CLOCK_BARE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _remove_time_parts(text: str) -> str:
    """Removes all time-related substrings, leaving only the prompt text."""
    text = _RE_DELTA.sub("", text)
    text = _RE_DAY_WORD.sub("", text)
    text = _RE_WEEKDAY.sub("", text)
    text = _RE_NEXT_WEEKDAY.sub("", text)
    text = _RE_DATE.sub("", text)
    text = _RE_CLOCK.sub("", text)
    text = _RE_CLOCK_BARE.sub("", text)
    
    # Clean up remaining prepositions and extra spaces
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"^\s*(at|on|in|after|and|,|\.)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(at|on|in|after|and|,|\.)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_time_only(user_input: str, timezone: str) -> Optional[datetime]:
    """
    Parses ONLY time from a short input string.
    Used during clarification step when the reminder text is already known.
    """
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    text = user_input.strip()

    return _parse_dt(text, tz, now)


def parse_reminder(user_input: str, timezone: str) -> dict:
    """
    Parses free text into a reminder dict.
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

    return {
        "text": text,
        "datetime": None,
        "raw_time": None,
        "ambiguous": False,
        "time_missing": True,
    }


def _parse_dt(text: str, tz: pytz.BaseTzInfo, now: datetime) -> Optional[datetime]:
    """Core logic: determines date and time from text."""

    # 1. Relative delta: "in X hours", "after 30 mins", "in a week"
    m = _RE_DELTA.search(text)
    if m:
        amount_str = m.group(2).lower()
        amount = 1 if amount_str == "a" else int(amount_str)
        
        unit_str = m.group(3).lower()
        minutes = _match_unit(unit_str) * amount
        if minutes:
            return now + timedelta(minutes=minutes)

    # 2. Determine base date
    base_date = None

    # 2.1 Fixed day words (today, tomorrow)
    m = _RE_DAY_WORD.search(text)
    if m:
        word = m.group(1).lower()
        if word == "today":
            base_date = now.date()
        elif word == "tomorrow":
            base_date = (now + timedelta(days=1)).date()
        elif word == "day after tomorrow":
            base_date = (now + timedelta(days=2)).date()

    # 2.2 Next weekday: "next monday" (strictly next week)
    if base_date is None:
        m = _RE_NEXT_WEEKDAY.search(text)
        if m:
            target_wd = _WEEKDAYS.get(m.group(1).lower())
            if target_wd is not None:
                current_wd = now.weekday()
                days_ahead = (target_wd - current_wd) % 7
                if days_ahead == 0:
                    days_ahead = 7
                base_date = (now + timedelta(days=days_ahead + 7)).date()

    # 2.3 Current week day: "on friday"
    if base_date is None:
        m = _RE_WEEKDAY.search(text)
        if m:
            target_wd = _WEEKDAYS.get(m.group(1).lower())
            if target_wd is not None:
                current_wd = now.weekday()
                days_ahead = (target_wd - current_wd) % 7
                if days_ahead == 0:
                    days_ahead = 7  # Interpret as next friday if today is already friday
                base_date = (now + timedelta(days=days_ahead)).date()

    # 2.4 Calendar date: "25.12.2026"
    if base_date is None:
        m = _RE_DATE.search(text)
        if m:
            try:
                from datetime import date
                base_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

    # 3. Extract time of day (clock)
    clock = _extract_clock(text)

    if base_date and clock:
        h, mi = clock
        if 0 <= h <= 23 and 0 <= mi <= 59:
            dt = tz.localize(datetime(base_date.year, base_date.month, base_date.day, h, mi))
            if dt > now:
                return dt

    # 4. Only date provided without time — set default to morning/afternoon
    if base_date and not clock:
        dt = tz.localize(datetime(base_date.year, base_date.month, base_date.day, 9, 0))
        if dt <= now:
            dt = tz.localize(datetime(base_date.year, base_date.month, base_date.day, 12, 0))
        if dt > now:
            return dt

    # 5. Only clock provided without date — today or tomorrow
    if clock and not base_date:
        h, mi = clock
        if 0 <= h <= 23 and 0 <= mi <= 59:
            candidate = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

    return None


def _match_unit(unit_str: str) -> int:
    """Returns number of minutes for a given time unit prefix."""
    for key, val in _UNITS.items():
        if unit_str.startswith(key[:3]):
            return val
    return 0


def _find_raw_time(text: str) -> Optional[str]:
    """Finds the raw time substring to display to the user."""
    for pattern in [_RE_DELTA, _RE_DAY_WORD, _RE_NEXT_WEEKDAY, _RE_WEEKDAY, _RE_DATE]:
        m = pattern.search(text)
        if m:
            clock = _RE_CLOCK.search(text) or _RE_CLOCK_BARE.search(text)
            if clock:
                return f"{m.group(0).strip()} at {clock.group(0).replace('at ', '').strip()}"
            return m.group(0).strip()
    return None