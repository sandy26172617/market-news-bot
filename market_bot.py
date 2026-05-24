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
#   KEYS — loaded from GitHub Secrets
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

    # Only send top 10 to keep prompt small
    articles = articles[:10]

    news_text = ""
    for i, a in enumerate(articles, 1):
        news_text += f"{i}. [{a['source']}] {a['title']}\n\n"

    prompt = f"""Analyze these news headlines for impact on Nifty 50 / Indian stock market.

Return ONLY a valid JSON array. Each object must have exactly these fields:
- id: number
- impact: "HIGH" or "MEDIUM" or "LOW"
- direction: "BULLISH" or "BEARISH" or "NEUTRAL"  
- analysis: string (max 15 words about Nifty impact)
- skip: boolean

No markdown. No explanation. Just the JSON array starting with [ and ending with ]

NEWS:
{news_text}"""

    # Try gemini-1.5-flash first, fallback to gemini-pro
    models = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro"
    ]

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1000
            }
        }

        try:
            print(f"[INFO] Trying model: {model}")
            resp = requests.post(url, json=payload, timeout=30)
            raw  = resp.json()
            print(f"[DEBUG] Response keys: {list(raw.keys())}")

            if "error" in raw:
                print(f"[WARN] Model {model} error: {raw['error'].get('message', raw['error'])}")
                continue

            if "candidates" not in raw:
                print(f"[WARN] No candidates in response: {json.dumps(raw)[:300]}")
                continue

            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            text = text.replace("```json", "").replace("```", "").strip()

            # Extract JSON array if buried in text
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                text = match.group(0)

            results = json.loads(text)
            print(f"[INFO] Gemini analysis successful with {model}.")

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
            print(f"[WARN] Model {model} failed: {e}")
            continue

    print("[ERROR] All Gemini models failed. Sending raw headlines instead.")
    return []

# ============================================================
#   FALLBACK — send top headlines without AI if Gemini fails
# ============================================================

def send_raw_headlines(articles):
    ist = pytz.timezone("Asia/Kolkata")
    ts  = datetime.now(ist).strftime("%d %b %Y  %I:%M %p IST")

    msg  = f"<b>📰 Market Headlines — {ts}</b>\n"
    msg += "━" * 28 + "\n\n"
    msg += "<i>(AI analysis unavailable — showing raw headlines)</i>\n\n"

    for a in articles[:8]:
        msg += f"• <b>{a['title']}</b>\n"
        msg += f"  📰 {a['source']}\n\n"

    send_telegram(msg)

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
        print("[INFO] No HIGH/MEDIUM impact news. No message sent.")
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

    msg += "<i>Next check in ~10 min</i>"
    send_telegram(msg)

# ============================================================
#   MAIN
# ============================================================

if __name__ == "__main__":
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    print(f"[INFO] Bot running at {now.strftime('%d %b %Y %I:%M %p IST')}")

    if not GEMINI_API_KEY or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Missing API keys. Check your GitHub Secrets.")
        exit(1)

    articles = fetch_news()
    analyzed = analyze_with_gemini(articles)

    if analyzed:
        format_and_send(analyzed)
    else:
        # Fallback: send raw headlines so you still get something
        print("[INFO] Falling back to raw headlines.")
        send_raw_headlines(articles)

    print("[INFO] Run complete.")
