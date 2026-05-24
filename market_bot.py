# ============================================================
#   INDIAN & GLOBAL MARKET NEWS BOT
#   Optimized for GitHub Actions — runs once per trigger
#   Fetches news → Gemini AI analysis → Telegram alert
# ============================================================

import feedparser
import requests
import json
import os
import hashlib
import re
from datetime import datetime
import pytz

# ============================================================
#   KEYS — loaded from GitHub Secrets (never hardcoded)
# ============================================================

GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
#   NEWS SOURCES — all free RSS feeds
# ============================================================

RSS_FEEDS = {
    "Economic Times" : "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol"   : "https://www.moneycontrol.com/rss/latestnews.xml",
    "Reuters India"  : "https://feeds.reuters.com/reuters/INbusinessNews",
    "Bloomberg"      : "https://feeds.bloomberg.com/markets/news.rss",
    "Investing.com"  : "https://in.investing.com/rss/news_25.rss",
}

# ============================================================
#   STEP 1 — FETCH NEWS
# ============================================================

def fetch_news():
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]:
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                # strip HTML tags from summary
                summary = re.sub(r"<[^>]+>", "", summary)[:250]
                link    = entry.get("link", "")
                uid     = hashlib.md5(title.encode()).hexdigest()
                if title:
                    articles.append({
                        "source" : source,
                        "title"  : title,
                        "summary": summary,
                        "link"   : link,
                        "uid"    : uid,
                    })
        except Exception as e:
            print(f"[WARN] Could not fetch {source}: {e}")

    print(f"[INFO] Fetched {len(articles)} articles total.")
    return articles

# ============================================================
#   STEP 2 — ANALYZE WITH GEMINI AI
# ============================================================

def analyze_with_gemini(articles):
    if not articles:
        return []

    news_text = ""
    for i, a in enumerate(articles, 1):
        news_text += f"{i}. [{a['source']}] {a['title']}\n   {a['summary']}\n\n"

    prompt = f"""You are a senior Indian stock market analyst. Analyze these news headlines 
for their impact on Nifty 50 and Indian financial markets.

For EACH headline, return a JSON array where each object has:
- id: number (matching headline number)
- impact: "HIGH" or "MEDIUM" or "LOW"
- direction: "BULLISH" or "BEARISH" or "NEUTRAL"
- analysis: one sharp sentence (max 20 words) on Nifty 50 impact
- skip: true if completely irrelevant to Indian or global markets, else false

Rules:
- HIGH = RBI policy, Fed decisions, war/geopolitical shock, major earnings miss/beat, FII data
- MEDIUM = crude oil moves, rupee moves, sector news, global market moves
- LOW = minor corporate news, irrelevant global news
- Only send skip:false for HIGH and MEDIUM items

Return ONLY the raw JSON array. No markdown. No backticks. No explanation.

NEWS:
{news_text}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1500}
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        raw  = resp.json()
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        results = json.loads(text)

        analyzed = []
        for r in results:
            idx = r.get("id", 0) - 1
            if 0 <= idx < len(articles):
                if not r.get("skip", False) and r.get("impact") in ("HIGH", "MEDIUM"):
                    articles[idx].update({
                        "impact"   : r["impact"],
                        "direction": r["direction"],
                        "analysis" : r["analysis"],
                    })
                    analyzed.append(articles[idx])

        print(f"[INFO] {len(analyzed)} HIGH/MEDIUM impact articles found.")
        return analyzed

    except Exception as e:
        print(f"[ERROR] Gemini API error: {e}")
        return []

# ============================================================
#   STEP 3 — SEND TO TELEGRAM
# ============================================================

EMOJI = {
    ("HIGH",   "BULLISH") : "🚀",
    ("HIGH",   "BEARISH") : "🔴",
    ("HIGH",   "NEUTRAL") : "⚠️",
    ("MEDIUM", "BULLISH") : "🟢",
    ("MEDIUM", "BEARISH") : "🟠",
    ("MEDIUM", "NEUTRAL") : "🔵",
}

def send_telegram(message):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id"                  : TELEGRAM_CHAT_ID,
        "text"                     : message,
        "parse_mode"               : "HTML",
        "disable_web_page_preview" : True,
    }
    resp = requests.post(url, data=data, timeout=15)
    if resp.status_code == 200:
        print("[INFO] Telegram message sent successfully.")
    else:
        print(f"[ERROR] Telegram failed: {resp.text}")

def format_and_send(articles):
    if not articles:
        print("[INFO] No HIGH/MEDIUM impact news this run. No message sent.")
        return

    ist = pytz.timezone("Asia/Kolkata")
    ts  = datetime.now(ist).strftime("%d %b %Y  %I:%M %p IST")

    msg  = f"<b>📊 Market Alert — {ts}</b>\n"
    msg += "━" * 28 + "\n\n"

    for a in articles:
        emoji = EMOJI.get((a["impact"], a["direction"]), "📌")
        msg  += f"{emoji} <b>{a['impact']} | {a['direction']}</b>\n"
        msg  += f"<b>{a['title']}</b>\n"
        msg  += f"<i>{a['analysis']}</i>\n"
        msg  += f"📰 <a href='{a['link']}'>{a['source']}</a>\n\n"

    msg += f"<i>Next check in ~10 min</i>"
    send_telegram(msg)

# ============================================================
#   MAIN
# ============================================================

if __name__ == "__main__":
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    print(f"[INFO] Bot running at {now.strftime('%d %b %Y %I:%M %p IST')}")

    # Validate keys
    if not GEMINI_API_KEY or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Missing API keys. Check your GitHub Secrets.")
        exit(1)

    articles = fetch_news()
    analyzed = analyze_with_gemini(articles)
    format_and_send(analyzed)
    print("[INFO] Run complete.")
