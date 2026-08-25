"""Resolves a trip's real calendar start date from the free-text prompt --
in real Python, never by asking the LLM to do date arithmetic (CLAUDE.md
architecture principle #6). This exists purely to unlock per-day weather
forecasts (weather_service.py needs a real date per itinerary day); it has
nothing to do with trip *length* (`day_number`/`total_days`), which
llm_service.py already infers separately.

Deliberately conservative: returns None whenever nothing in the prompt is
clearly date-like, rather than guessing. A missed date just means the
weather feature doesn't activate for that trip (see principle #7 -- no
data shown beats a wrong one). In particular, this never hands the whole
free-text prompt to dateutil's fuzzy parser across the full sentence --
prompts routinely contain unrelated bare numbers ("5 days in Reykjavik,
budget is 500 USD") that a whole-sentence fuzzy parse can and will pull in
as a stray day/year (confirmed while building this: "September 3rd" inside
"5 days in Paris starting September 3rd" got misread as 2003-09-05, the
"5" and "3rd" bleeding into the wrong fields). Instead, a small regex first
extracts just the date-shaped *substring* (a month name + day, an ISO
date, or a numeric MM/DD[/YY]), and only that substring -- never the rest
of the prompt -- is handed to dateutil.
"""
import re
from datetime import date, datetime, timedelta

from dateutil import parser as dateutil_parser

_MONTH_RE = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_MONTH_THEN_DAY_RE = re.compile(
    rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE,
)
_DAY_THEN_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE,
)

_RELATIVE_PATTERNS = [
    # "in N days"/"in N weeks" are handled separately in resolve_trip_start_date
    # (they need the matched number, not just a fixed offset).
    (re.compile(r"\btoday\b", re.IGNORECASE), lambda today: today),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), lambda today: today + timedelta(days=1)),
    (re.compile(r"\bthis weekend\b", re.IGNORECASE), lambda today: _this_weekend(today)),
    (re.compile(r"\bnext weekend\b", re.IGNORECASE), lambda today: _next_weekday(today, 5)),
]


def _next_weekday(from_date: date, weekday: int) -> date:
    """Next occurrence of `weekday` (Mon=0..Sun=6) strictly after `from_date`."""
    days_ahead = (weekday - from_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return from_date + timedelta(days=days_ahead)


def _this_weekend(from_date: date) -> date:
    """The nearest Saturday, including today if today already is the weekend."""
    weekday = from_date.weekday()
    if weekday in (5, 6):  # already Sat/Sun
        return from_date
    return from_date + timedelta(days=(5 - weekday) % 7)


def _extract_explicit_date_substring(prompt: str) -> str | None:
    """Finds the smallest date-shaped chunk of the prompt, if any -- never
    the whole prompt, so unrelated numbers elsewhere (trip length, budget)
    can't leak into the parse."""
    for pattern in (_ISO_DATE_RE, _NUMERIC_DATE_RE, _MONTH_THEN_DAY_RE, _DAY_THEN_MONTH_RE):
        match = pattern.search(prompt)
        if match:
            return match.group(0)
    return None


def resolve_trip_start_date(prompt: str, current_date: date | None = None) -> date | None:
    """Best-effort, deterministic extraction of a trip's start date from
    free text. Returns None (never a guess) when nothing date-like is
    found."""
    today = current_date or date.today()

    # "in N days" and "N days from now/today" are the same thing said two
    # ways -- confirmed live that only the first form was handled, so "4
    # days from now" silently resolved to None (no weather activated, and
    # the model correctly said it had no data rather than guessing -- the
    # anti-fabrication path worked, but the feature should have fired).
    days_match = re.search(r"\bin (\d+) days?\b", prompt, re.IGNORECASE) or re.search(
        r"\b(\d+) days? from (?:now|today)\b", prompt, re.IGNORECASE,
    )
    if days_match:
        return today + timedelta(days=int(days_match.group(1)))

    weeks_match = re.search(r"\bin (\d+) weeks?\b", prompt, re.IGNORECASE) or re.search(
        r"\b(\d+) weeks? from (?:now|today)\b", prompt, re.IGNORECASE,
    )
    if weeks_match:
        return today + timedelta(weeks=int(weeks_match.group(1)))

    for pattern, resolver in _RELATIVE_PATTERNS:
        if pattern.search(prompt):
            return resolver(today)

    date_substring = _extract_explicit_date_substring(prompt)
    if date_substring:
        try:
            parsed = dateutil_parser.parse(date_substring, default=_default_anchor(today))
            return parsed.date()
        except (ValueError, OverflowError):
            return None

    return None


def _default_anchor(today: date) -> datetime:
    return datetime(today.year, today.month, today.day)
