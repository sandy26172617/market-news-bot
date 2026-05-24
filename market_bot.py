import feedparser
import requests
import json
import os
import hashlib
import re
from datetime import datetime
import pytz

GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

IST = pytz.timezone("Asia/Kolkata")

RSS_FEEDS = {
    "Economic Times" : "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol"   : "https://www.moneycontrol.com/rss/latestnews.xml",
    "Reuters India"  : "https://feeds.reuters.com/reuters/INbusinessNews",
    "Bloomberg"      : "https://feeds.bloomberg.com/markets/news.rss",
    "Investing.com"  : "https://in.investing.com/rss/news_25.rss",
    "Reuters Global" : "https://feeds.reuters.com/reuters/businessNews",
}

def fetch_news():
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title   = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", ""))).strip()[:300]
                link    = entry.get("link", "")
                uid     = hashlib.md5(title.encode()).hexdigest()
                if title:
                    articles.append({"source": source, "title": title, "summary": summary, "link": link, "uid": uid})
        except Exception as e:
            print(f"[WARN] {source}: {e}")
    print(f"[INFO] Fetched {len(articles)} articles.")
    return articles[:15]

def now_ist():
    return datetime.now(IST)

def is_market_hours():
    now = now_ist()
    h = now.hour + now.minute / 60
    return 9.25 <= h <= 15.5

def is_morning_briefing():
    now = now_ist()
    return now.hour == 8 and now.minute < 15

def gemini(prompt, model="gemini-2.0-flash"):
    models = [model, "gemini-1.5-pro", "gemini-3.1-flash-lite"]
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000}}
        try:
            resp = requests.post(url, json=payload, timeout=30).json()
            if "error" in resp:
                print(f"[WARN] {m}: {resp['error'].get('message','')[:80]}")
                continue
            text = resp["candidates"][0]["content"]["parts"][0]["text"]
            return text.replace("```json","").replace("```","").strip()
        except Exception as e:
            print(f"[WARN] {m}: {e}")
    return None

def analyze_news(articles):
    if not articles:
        return []
    news_text = "\n".join([f"{i+1}. [{a['source']}] {a['title']}" for i, a in enumerate(articles)])

    prompt = f"""You are a senior NSE market analyst. Analyze these headlines for Nifty 50 impact.

Return ONLY a JSON array. Each object:
- id: number
- impact: "HIGH" or "MEDIUM" or "LOW"
- skip: true if irrelevant to Indian/global markets
- direction: "STRONGLY BULLISH" or "BULLISH" or "MEDIUM BULLISH" or "SIDEWAYS" or "MEDIUM BEARISH" or "BEARISH" or "STRONGLY BEARISH"
- one_liner: one sharp sentence max 20 words explaining Nifty impact (e.g. "FII selling increased — Nifty bearish pressure likely to continue")
- category: one of: FII_DII | CRUDE | GOLD | GEOPOLITICAL | RBI_POLICY | FED_POLICY | INDIA_MACRO | US_MACRO | CHINA_MARKETS | VIX | PUT_CALL | EARNINGS | CURRENCY | GENERAL

Only include HIGH and MEDIUM impact items with skip:false.

NEWS:
{news_text}"""

    raw = gemini(prompt)
    if not raw:
        return []
    try:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        results = json.loads(match.group(0) if match else raw)
        analyzed = []
        for r in results:
            idx = r.get("id", 0) - 1
            if 0 <= idx < len(articles) and not r.get("skip", True) and r.get("impact") in ("HIGH", "MEDIUM"):
                articles[idx].update({
                    "impact"    : r["impact"],
                    "direction" : r.get("direction", "SIDEWAYS"),
                    "one_liner" : r.get("one_liner", ""),
                    "category"  : r.get("category", "GENERAL"),
                })
                analyzed.append(articles[idx])
        print(f"[INFO] {len(analyzed)} HIGH/MEDIUM items found.")
        return analyzed
    except Exception as e:
        print(f"[ERROR] Parse failed: {e}")
        return []

def get_intraday_picks():
    prompt = """You are an expert NSE intraday trader. Based on current Indian market conditions, suggest 5 Nifty 50 stocks for intraday trading today.

Return ONLY a JSON array. Each object:
- stock: stock symbol (e.g. RELIANCE, HDFCBANK, TCS)
- action: "BUY" or "SELL"
- reason: one line max 15 words (e.g. "Strong FII buying + breakout above 200 DMA")
- target: percentage move expected (e.g. "+1.2%")
- stoploss: percentage stoploss (e.g. "-0.5%")

Pick stocks with high probability setups based on recent news, sector momentum, and technicals."""

    raw = gemini(prompt)
    if not raw:
        return []
    try:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        return json.loads(match.group(0) if match else raw)
    except:
        return []

def get_morning_briefing():
    prompt = """You are a market analyst giving a morning briefing for Indian traders.

Provide a morning market briefing covering:
1. US markets overnight (S&P 500, Nasdaq, Dow — up/down and why)
2. Asian markets (Nikkei, Hang Seng, Shanghai)
3. Gift Nifty indication for today's opening
4. Crude oil current level and direction
5. Gold current level and direction
6. USD/INR level
7. India VIX — fear/greed reading
8. Overall Nifty 50 opening outlook: GAP UP / GAP DOWN / FLAT and expected range

Return ONLY a JSON object with these keys:
- us_markets: string (1 line)
- asian_markets: string (1 line)
- gift_nifty: string (1 line, e.g. "Gift Nifty at 24,350 — indicating 80 pt gap up open")
- crude: string (1 line)
- gold: string (1 line)
- usdinr: string (1 line)
- india_vix: string (1 line)
- outlook: string (1 line summary)
- direction: "GAP UP" or "GAP DOWN" or "FLAT""""

    raw = gemini(prompt)
    if not raw:
        return None
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group(0) if match else raw)
    except:
        return None

def send_telegram(message):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    resp = requests.post(url, data=data, timeout=15)
    if resp.status_code == 200:
        print("[INFO] Telegram sent.")
    else:
        print(f"[ERROR] Telegram: {resp.text}")

DIRECTION_EMOJI = {
    "STRONGLY BULLISH" : "🚀🚀",
    "BULLISH"          : "🟢",
    "MEDIUM BULLISH"   : "🟢📈",
    "SIDEWAYS"         : "↔️",
    "MEDIUM BEARISH"   : "🟠📉",
    "BEARISH"          : "🔴",
    "STRONGLY BEARISH" : "🔴🔴",
}

CATEGORY_LABEL = {
    "FII_DII"     : "FII/DII Flow",
    "CRUDE"       : "Crude Oil",
    "GOLD"        : "Gold",
    "GEOPOLITICAL": "Geopolitical",
    "RBI_POLICY"  : "RBI Policy",
    "FED_POLICY"  : "US Fed",
    "INDIA_MACRO" : "India Macro",
    "US_MACRO"    : "US Macro",
    "CHINA_MARKETS": "China Markets",
    "VIX"         : "India VIX",
    "PUT_CALL"    : "Put/Call Ratio",
    "EARNINGS"    : "Earnings",
    "CURRENCY"    : "Currency",
    "GENERAL"     : "Market News",
}

def send_morning_briefing():
    print("[INFO] Generating morning briefing...")
    briefing = get_morning_briefing()
    ts = now_ist().strftime("%d %b %Y")

    if not briefing:
        send_telegram(f"<b>🌅 Morning Briefing — {ts}</b>\n\nUnable to fetch briefing data. Markets open at 9:15 AM IST.")
        return

    direction_emoji = "🚀" if briefing.get("direction") == "GAP UP" else ("🔻" if briefing.get("direction") == "GAP DOWN" else "↔️")

    msg  = f"<b>🌅 Morning Market Briefing — {ts}</b>\n"
    msg += "━" * 28 + "\n\n"
    msg += f"<b>🇺🇸 US Markets</b>\n{briefing.get('us_markets','—')}\n\n"
    msg += f"<b>🌏 Asian Markets</b>\n{briefing.get('asian_markets','—')}\n\n"
    msg += f"<b>📊 Gift Nifty</b>\n{briefing.get('gift_nifty','—')}\n\n"
    msg += f"<b>🛢 Crude Oil</b>\n{briefing.get('crude','—')}\n\n"
    msg += f"<b>🥇 Gold</b>\n{briefing.get('gold','—')}\n\n"
    msg += f"<b>💵 USD/INR</b>\n{briefing.get('usdinr','—')}\n\n"
    msg += f"<b>😨 India VIX</b>\n{briefing.get('india_vix','—')}\n\n"
    msg += "━" * 28 + "\n"
    msg += f"{direction_emoji} <b>Today's Outlook: {briefing.get('direction','—')}</b>\n"
    msg += f"<i>{briefing.get('outlook','—')}</i>\n\n"
    msg += "<i>Market opens at 9:15 AM IST. Good luck! 🎯</i>"

    send_telegram(msg)

def send_news_alerts(articles):
    if not articles:
        print("[INFO] No HIGH/MEDIUM news. No alert sent.")
        return

    ts  = now_ist().strftime("%d %b %Y  %I:%M %p IST")
    msg = f"<b>📊 Market Alert — {ts}</b>\n"
    msg += "━" * 28 + "\n\n"

    for a in articles:
        emoji = DIRECTION_EMOJI.get(a["direction"], "📌")
        cat   = CATEGORY_LABEL.get(a["category"], "News")
        impact_badge = "🔥" if a["impact"] == "HIGH" else "•"
        msg += f"{impact_badge} <b>[{cat}]</b> {emoji} <b>{a['direction']}</b>\n"
        msg += f"<i>{a['one_liner']}</i>\n"
        msg += f"📰 <a href='{a['link']}'>{a['source']}</a>\n\n"

    send_telegram(msg)

def send_intraday_picks():
    print("[INFO] Generating intraday picks...")
    picks = get_intraday_picks()
    if not picks:
        return

    ts  = now_ist().strftime("%d %b %Y")
    msg = f"<b>🎯 Intraday Stock Picks — {ts}</b>\n"
    msg += "━" * 28 + "\n\n"

    for p in picks[:5]:
        action_emoji = "📈" if p.get("action") == "BUY" else "📉"
        action_color = "BUY 🟢" if p.get("action") == "BUY" else "SELL 🔴"
        msg += f"{action_emoji} <b>{p.get('stock','—')}</b> — {action_color}\n"
        msg += f"<i>{p.get('reason','—')}</i>\n"
        msg += f"Target: <b>{p.get('target','—')}</b>  |  Stop: <b>{p.get('stoploss','—')}</b>\n\n"

    msg += "<i>⚠️ For educational purposes only. Do your own research before trading.</i>"
    send_telegram(msg)

if __name__ == "__main__":
    now = now_ist()
    print(f"[INFO] Bot running at {now.strftime('%d %b %Y %I:%M %p IST')}")

    if not GEMINI_API_KEY or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Missing API keys.")
        exit(1)

    # Morning briefing at 8 AM
    if is_morning_briefing():
        send_morning_briefing()

    # Intraday picks at 9:15 AM (market open)
    if now.hour == 9 and 15 <= now.minute < 30:
        send_intraday_picks()

    # News alerts always
    articles = fetch_news()
    analyzed = analyze_news(articles)
    send_news_alerts(analyzed)

    print("[INFO] Run complete.")
