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

SEEN_ITEMS_FILE = "seen_items.json"   # Tracks already-published stories

NEWS_SOURCES = [
    # English — Monaco-specific
    "https://www.monacotribune.com/feed/",
    "https://www.monacolife.net/feed/",
    "https://www.hellomonaco.com/feed/",
    # French
    "https://www.monacomatin.mc/arc/outboundfeeds/rss/?outputType=xml",
    # Sports / Events
    "https://www.formula1.com/content/fom-website/en/latest/all.xml",
    # Official Monaco Government news
    "https://www.gouv.mc/en/rss",
    # Monaco Yacht Show
    "https://www.monacoyachtshow.com/en/rss",
    # Top Marques Monaco
    "https://www.topmarquesmonaco.com/feed/",
    # Google News — broad world coverage filtered to Monaco
    "https://news.google.com/rss/search?q=Monaco+principality&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Monte+Carlo&hl=en-US&gl=US&ceid=US:en",
]

SYSTEM_PROMPT = """You are the editor of Monaco Digest, a premium Telegram channel for Monaco residents, expats, and professionals.

Your daily output is ONE post: the Morning Brief — a curated digest of 3–7 short updates.

FORMAT (follow exactly):
🇲🇨 Monaco Digest — Daily Brief

1. [One-line update, max 15 words.]
2. [One-line update, max 15 words.]
3. [One-line update, max 15 words.]
... (up to 7 items, only include if genuinely newsworthy)

More tomorrow.

TONE & STYLE:
- Bloomberg meets luxury lifestyle — informed, dry, no hype
- Each line reads like insider intel, not a press release
- No exclamation marks. No clickbait. No filler words.
- Emoji: only the flag at the top, nowhere else
- Whitespace matters — keep it clean and scannable
- Reader is reading between meetings, in a car, on a yacht

CONTENT PRIORITY (in order):
1. Business, finance, real estate, wealth
2. Events, hospitality, openings (Top Marques, galas, private clubs)
3. Formula 1, yacht season, sports
4. Local regulations, infrastructure, practical updates
5. International news only if directly relevant to Monaco residents

DO NOT include hashtags, URLs, or source attribution. Just the brief.
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
    """Collect unseen news items from all RSS feeds, max 5 per source to ensure diversity."""
    per_source = []
    for url in NEWS_SOURCES:
        try:
            feed = feedparser.parse(url)
            source_items = []
            for entry in feed.entries:
                eid = item_id(entry)
                if eid in seen:
                    continue
                source_items.append({
                    "id": eid,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:800],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", url),
                })
                if len(source_items) >= 5:  # max 5 per source
                    break
            per_source.append(source_items)
            log.info(f"Fetched {len(source_items)} items from {url.split('/')[2]}")
        except Exception as e:
            log.warning(f"Failed to fetch {url}: {e}")

    # Interleave sources so no single source dominates
    items = []
    for i in range(max((len(s) for s in per_source), default=0)):
        for source in per_source:
            if i < len(source):
                items.append(source[i])
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


def generate_digest(items: list[dict], client: anthropic.Anthropic) -> str:
    """Ask Claude to compile a Morning Brief digest from multiple news items."""
    news_block = "\n\n".join(
        f"- {item['title']}\n  {item['summary'][:300]}"
        for item in items[:20]  # send up to 20 headlines as raw material
    )
    user_message = f"""Here are today's Monaco-related news headlines and summaries.
Compile them into the Morning Brief digest following your format instructions.
Pick only the most relevant and interesting 3–7 items.

RAW NEWS:
{news_block}
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

    if not relevant:
        log.info("No relevant items found today — skipping post.")
        save_seen_items(seen)
        return

    try:
        digest = generate_digest(relevant, client)
        if post_to_telegram(digest):
            for item in relevant:
                seen.add(item["id"])
            log.info("Morning Brief published ✓")
        else:
            log.error("Failed to post digest to Telegram.")
    except Exception as e:
        log.error(f"Error generating digest: {e}")

    save_seen_items(seen)
    log.info("Done.")


if __name__ == "__main__":
    main()
