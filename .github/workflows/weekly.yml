"""
Monaco Digest — Weekly Posts
Monday: Weather forecast for the week
Thursday: Weekend events guide
"""

import os
import sys
import logging
from datetime import datetime, timezone

import anthropic
import requests
import feedparser

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Monaco coordinates
LAT, LON = 43.7384, 7.4246

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EVENT_SOURCES = [
    "https://www.hellomonaco.com/feed/",
    "https://www.monacolife.net/feed/",
    "https://www.monacotribune.com/feed/",
    "https://news.google.com/rss/search?q=Monaco+event+2026&hl=en-US&gl=US&ceid=US:en",
]


# ── Weather ───────────────────────────────────────────────────────────────────

def fetch_weather() -> dict:
    """Fetch 7-day forecast from Open-Meteo (no API key needed)."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
        "&timezone=Europe/Paris"
        "&forecast_days=7"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def weathercode_to_desc(code: int) -> str:
    mapping = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Foggy", 51: "Light drizzle", 53: "Drizzle",
        55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers",
        81: "Rain showers", 82: "Heavy showers", 95: "Thunderstorm",
        96: "Thunderstorm", 99: "Thunderstorm",
    }
    return mapping.get(code, "Variable")


def build_weather_post() -> str:
    data = fetch_weather()
    daily = data["daily"]
    days = daily["time"]
    max_temps = daily["temperature_2m_max"]
    min_temps = daily["temperature_2m_min"]
    precip = daily["precipitation_sum"]
    codes = daily["weathercode"]

    lines = []
    for i in range(7):
        date = datetime.strptime(days[i], "%Y-%m-%d")
        day_name = date.strftime("%A")
        desc = weathercode_to_desc(codes[i])
        rain = f" · {precip[i]:.0f}mm rain" if precip[i] > 1 else ""
        lines.append(f"{day_name}: {desc}, {min_temps[i]:.0f}–{max_temps[i]:.0f}°C{rain}")

    forecast_text = "\n".join(lines)

    post = f"""🇲🇨 Monaco Digest — Weekly Weather

{forecast_text}

Plan accordingly."""
    return post


# ── Weekend Events ────────────────────────────────────────────────────────────

def fetch_event_items() -> list[dict]:
    items = []
    for url in EVENT_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))[:500]
                text = (title + " " + summary).lower()
                # Keep only event/weekend relevant content
                if any(kw in text for kw in [
                    "event", "gala", "festival", "exhibition", "concert",
                    "race", "grand prix", "yacht", "show", "opening",
                    "weekend", "saturday", "sunday", "monaco", "monte carlo"
                ]):
                    items.append({
                        "title": title,
                        "summary": summary,
                        "link": entry.get("link", ""),
                    })
        except Exception as e:
            log.warning(f"Failed to fetch {url}: {e}")
    return items[:25]


EVENTS_SYSTEM_PROMPT = """You are the editor of Monaco Digest, a premium Telegram channel for Monaco residents and expats.

Every Thursday you publish a Weekend Guide — a curated list of things happening in and around Monaco this weekend.

FORMAT (follow exactly):
🇲🇨 Monaco Digest — Weekend Guide

What's on this weekend:

1. [Event name — max 8 words]
[One sentence: what, where, when.] [One sentence: why it's worth going or who it's for.]
Source: [URL]

2. [Event name — max 8 words]
...

(3 to 7 events)

Have a great weekend.

RULES:
- Only include events happening THIS weekend or very soon
- If no clear events found, include the most interesting Monaco social happenings
- Tone: insider, warm but not cheesy — like a well-connected friend
- No exclamation marks. No hashtags. No emoji except the flag at the top.
- Two sentences per event max. Keep it tight.
"""


def build_events_post(client: anthropic.Anthropic) -> str:
    items = fetch_event_items()
    if not items:
        return ""

    news_block = "\n\n".join(
        f"- {i['title']}\n  {i['summary']}\n  URL: {i['link']}"
        for i in items
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=EVENTS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Here are recent Monaco news and events. Compile the Weekend Guide.\n\nSOURCES:\n{news_block}"}],
    )
    return response.content[0].text.strip()


# ── Telegram ──────────────────────────────────────────────────────────────────

def post_to_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, json=payload, timeout=15)
    if r.ok:
        log.info("Posted to Telegram ✓")
        return True
    log.error(f"Telegram error {r.status_code}: {r.text}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Determine what to post based on day of week
    # Monday=0, Thursday=3
    weekday = datetime.now(timezone.utc).weekday()
    mode = os.environ.get("MODE", "")  # allow manual override via env var

    log.info(f"Weekly bot starting — weekday={weekday}, mode={mode or 'auto'}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if mode == "weather" or (not mode and weekday == 0):
        log.info("Posting weather forecast...")
        post = build_weather_post()
        post_to_telegram(post)

    elif mode == "events" or (not mode and weekday == 3):
        log.info("Posting weekend events guide...")
        post = build_events_post(client)
        if post:
            post_to_telegram(post)
        else:
            log.info("No events found — skipping.")

    else:
        log.info(f"Nothing scheduled for weekday {weekday} — exiting.")


if __name__ == "__main__":
    main()
