#!/usr/bin/env python3
"""
Daily Newsletter Agent
----------------------
Fetches recent headlines on Cybersecurity, AI, and Finance from RSS feeds,
asks Claude to write them up into a ~4-page newsletter, and emails the
result via Gmail SMTP.

Required environment variables (set as GitHub Actions secrets, or in a
local .env file if running manually):
    OPENROUTER_API_KEY   - your OpenRouter API key (starts with sk-or-v1-)
    GMAIL_ADDRESS        - the Gmail account to send FROM
    GMAIL_APP_PASSWORD   - a Gmail "App Password" (not your normal password)
    TO_EMAIL             - the email address to send the newsletter TO
"""

import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import requests

# ---------------------------------------------------------------------------
# 1. CONFIG — edit these lists to add/remove sources
# ---------------------------------------------------------------------------

FEEDS = {
    "Cybersecurity": [
        "https://krebsonsecurity.com/feed/",
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.bleepingcomputer.com/feed/",
    ],
    "AI": [
        "https://www.technologyreview.com/feed/",
        "https://www.artificialintelligence-news.com/feed/",
        "https://venturebeat.com/category/ai/feed/",
    ],
    "Finance": [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "https://www.investing.com/rss/news.rss",
    ],
}

MAX_ITEMS_PER_FEED = 8          # how many items to pull from each feed
LOOKBACK_HOURS = 30             # only include items published within this window
MODEL = "openrouter/free"   # OpenRouter model slug used to write the newsletter

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ["TO_EMAIL"]


# ---------------------------------------------------------------------------
# 2. FETCH NEWS FROM RSS FEEDS
# ---------------------------------------------------------------------------

def fetch_category_items(category: str, feed_urls: list[str]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items = []

    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"  [warn] failed to parse {url}: {e}")
            continue

        for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            link = entry.get("link", "")

            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue

            if title:
                items.append({"title": title, "summary": summary, "link": link, "source": url})

    return items


def fetch_all_news() -> dict[str, list[dict]]:
    all_items = {}
    for category, urls in FEEDS.items():
        print(f"Fetching {category} feeds...")
        all_items[category] = fetch_category_items(category, urls)
        print(f"  -> {len(all_items[category])} items")
    return all_items


# ---------------------------------------------------------------------------
# 3. ASK CLAUDE TO WRITE THE NEWSLETTER
# ---------------------------------------------------------------------------

def build_prompt(news: dict[str, list[dict]]) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")

    raw_material = ""
    for category, items in news.items():
        raw_material += f"\n## {category}\n"
        if not items:
            raw_material += "(No fresh items found today.)\n"
        for it in items:
            raw_material += f"- {it['title']}: {it['summary'][:300]}\n"

    prompt = f"""You are the editor of a daily newsletter called "The Daily Signal" covering
Cybersecurity, AI, and Finance. Today's date is {today}.

Below is raw material pulled from news feeds. Write a polished, well-organized
newsletter edition from it. Requirements:

- Output clean HTML (a full <html> document with inline CSS styling — no external
  stylesheets or images). It should look professional, like a real newsletter,
  with a masthead/header, section headings for Cybersecurity, AI, and Finance,
  and a short "Today in Brief" summary at the top.
- Target length: approximately 1,800-2,200 words total (roughly 4 printed pages).
- For each category, pick the most important/interesting stories from the raw
  material and write short original paragraphs (do not just copy the raw text
  verbatim) explaining what happened and why it matters.
- If a category has no fresh items, say so briefly rather than inventing news.
- End with a short "Why this matters" closing thought.
- Do not include markdown code fences — output raw HTML only, starting with <html>.

RAW MATERIAL:
{raw_material}
"""
    return prompt


def generate_newsletter_html(news: dict[str, list[dict]]) -> str:
    prompt = build_prompt(news)

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    html = data["choices"][0]["message"]["content"].strip()

    if html.startswith("```"):
        html = html.strip("`")
        if html.lower().startswith("html"):
            html = html[4:]

    return html


# ---------------------------------------------------------------------------
# 4. SEND THE EMAIL
# ---------------------------------------------------------------------------

def send_email(html_body: str):
    today = datetime.now().strftime("%B %d, %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"The Daily Signal — {today}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = TO_EMAIL

    msg.attach(MIMEText("Please view this email in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, TO_EMAIL, msg.as_string())

    print(f"Newsletter sent to {TO_EMAIL}")


# ---------------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------------

def main():
    news = fetch_all_news()
    html = generate_newsletter_html(news)
    send_email(html)


if __name__ == "__main__":
    main()
