"""
Monaco Daily News Bot
Fetches Monaco news from RSS feeds, generates engaging posts via Claude,
and publishes them to a Telegram channel.
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import anthropic
import requests

# ── Configuration ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

MAX_POSTS_PER_DAY = 3          # How many posts to publish per run
SEEN_ITEMS_FILE = "seen_items.json"   # Tracks already-published stories

NEWS_SOURCES = [
    # English
    "https://www.monacotribune.com/feed/",
    "https://www.monacolife.net/feed/",
    # French
    "https://www.monacomatin.mc/arc/outboundfeeds/rss/?outputType=xml",
    # Sports / Events (lots of Monaco content)
    "https://www.formula1.com/content/fom-website/en/latest/all.xml",
]

SYSTEM_PROMPT = """You are the editor of Monaco Daily, a Telegram channel for Monaco residents and expats.
Your job is to write punchy, engaging news posts in English.

Rules:
- 2-4 short paragraphs maximum
- Start with the most interesting fact or hook — no boring intros
- Use simple, clear language — your readers are international professionals
- Add 3-5 relevant hashtags at the end (e.g. #Monaco #GrandPrix #MonteCarlo)
- Never use clickbait or sensationalism
- If the story is local/practical (traffic, events, regulations), highlight the impact on daily life
- Tone: friendly, informed, slightly witty — like a knowledgeable neighbour
- Do NOT add a title/headline — Telegram posts don't need one
- Maximum 280 words
"""

# ── Helpers ──────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_seen_items() -> set:
    if Path(SEEN_ITEMS_FILE).exists():
        with open(SEEN_ITEMS_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_items(seen: set) -> None:
    with open(SEEN_ITEMS_FILE, "w") as f:
        json.dump(list(seen), f)


def item_id(entry) -> str:
    key = getattr(entry, "id", None) or entry.get("link", "") or entry.get("title", "")
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def fetch_fresh_items(seen: set) -> list[dict]:
    """Collect unseen news items from all RSS feeds."""
    items = []
    for url in NEWS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                eid = item_id(entry)
                if eid in seen:
                    continue
                items.append({
                    "id": eid,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:800],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", url),
                })
        except Exception as e:
            log.warning(f"Failed to fetch {url}: {e}")
    return items


def is_monaco_relevant(item: dict) -> bool:
    """Basic keyword filter — keeps only Monaco-related stories."""
    text = (item["title"] + " " + item["summary"]).lower()
    keywords = [
        "monaco", "monte carlo", "monte-carlo", "montecarlo",
        "principality", "grimaldi", "albert ii", "rainier",
        "formula e monaco", "grand prix", "circuit de monaco",
    ]
    return any(kw in text for kw in keywords)


def generate_post(item: dict, client: anthropic.Anthropic) -> str:
    """Ask Claude to write a Telegram post from the raw news item."""
    user_message = f"""Write a Telegram post about this news story for Monaco residents.

Source: {item['source']}
Title: {item['title']}
Summary: {item['summary']}
URL: {item['link']}

Include the URL as a plain link at the very end of the post (after the hashtags), on its own line.
"""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()


def post_to_telegram(text: str) -> bool:
    """Send a message to the Telegram channel. Returns True on success."""
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
    else:
        log.error(f"Telegram error {r.status_code}: {r.text}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info(f"Monaco News Bot starting — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    seen = load_seen_items()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    items = fetch_fresh_items(seen)
    log.info(f"Fetched {len(items)} new items from RSS feeds")

    # Filter to Monaco-relevant stories
    relevant = [i for i in items if is_monaco_relevant(i)]
    log.info(f"{len(relevant)} Monaco-relevant items found")

    published = 0
    for item in relevant:
        if published >= MAX_POSTS_PER_DAY:
            break
        try:
            post_text = generate_post(item, client)
            if post_to_telegram(post_text):
                seen.add(item["id"])
                published += 1
        except Exception as e:
            log.error(f"Error processing item '{item['title']}': {e}")

    save_seen_items(seen)
    log.info(f"Done. Published {published} post(s).")


if __name__ == "__main__":
    main()
