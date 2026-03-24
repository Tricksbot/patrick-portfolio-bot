import os
import asyncio
import logging
import json
from datetime import datetime, time, timedelta
import pytz
import aiohttp
from telegram import Bot
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
POLYGON_API_KEY  = os.environ.get("POLYGON_API_KEY")
NEWS_API_KEY     = os.environ.get("NEWS_API_KEY")
EMAIL_FROM       = os.environ.get("EMAIL_FROM")
EMAIL_TO         = os.environ.get("EMAIL_TO")
EMAIL_PASSWORD   = os.environ.get("EMAIL_PASSWORD")

EST = pytz.timezone("America/New_York")

# ─── PORTFOLIO ────────────────────────────────────────────────────────────────
HOLDINGS = {
    "RKLB": {"shares": 700,     "avg_cost": 6.73,    "name": "Rocket Lab USA"},
    "VTI":  {"shares": 113.17,  "avg_cost": 233.36,  "name": "Vanguard Total Market"},
    "ETH":  {"shares": 13.02,   "avg_cost": 2068.00, "name": "Ether"},
    "GD":   {"shares": 64.19,   "avg_cost": 252.17,  "name": "General Dynamics"},
    "AMZN": {"shares": 78,      "avg_cost": 144.46,  "name": "Amazon"},
    "GWRE": {"shares": 72,      "avg_cost": 157.18,  "name": "Guidewire Software"},
    "MRSH": {"shares": 61.3,    "avg_cost": 178.30,  "name": "Marsh McLennan"},
    "SOFI": {"shares": 400,     "avg_cost": 18.03,   "name": "SoFi Technologies"},
    "BTC":  {"shares": 0.03029, "avg_cost": 86490,   "name": "Bitcoin"},
    "AUR":  {"shares": 450,     "avg_cost": 6.10,    "name": "Aurora Innovation"},
    "LINK": {"shares": 402.1,   "avg_cost": 15.00,   "name": "Chainlink"},
}
CRYPTO_MAP = {"ETH": "ethereum", "BTC": "bitcoin", "LINK": "chainlink"}

# ─── WATCHLIST ────────────────────────────────────────────────────────────────
WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Watchlist load error: {e}")
    return [
        {"ticker": "PANW", "target": 160.00, "note": "Cybersecurity leader"},
        {"ticker": "WYNN", "target": 90.00,  "note": "UAE resort 2027 catalyst"},
    ]

def save_watchlist(wl):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(wl, f)
    except Exception as e:
        logger.error(f"Watchlist save error: {e}")

# ─── PRICE ALERTS ─────────────────────────────────────────────────────────────
PRICE_ALERTS = [
    {"ticker": "RKLB", "target": 100.00, "direction": "above", "action": "🔴 TRIM ALERT — RKLB hit $100. Trim 250 shares as planned. Net ~$17,900 after 30% tax. Keep 450 shares running."},
    {"ticker": "GWRE", "target": 158.00, "direction": "below", "action": "🟢 ADD OPPORTUNITY — GWRE at $158. Top up your position. Analyst avg target $266 (+65% upside)."},
    {"ticker": "PANW", "target": 160.00, "direction": "below", "action": "🟢 BUY ZONE — PANW hit $160. Start your position. Analyst avg target $210 (+31% upside)."},
    {"ticker": "WYNN", "target": 90.00,  "direction": "below", "action": "🟢 BUY ZONE — WYNN hit $90. Start a position. Analyst avg target $138 (+53% upside)."},
]

# ─── SETTINGS ─────────────────────────────────────────────────────────────────
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
RSI_PERIOD     = 14
MA_SHORT = 20
MA_LONG  = 50
MA_FAST  = 12
MA_SLOW  = 26
MA_SIGNAL = 9
TREASURY_ALERT_THRESHOLD = 4.5

NEWS_TICKERS = ["RKLB", "GWRE", "SOFI", "PANW", "AMZN", "GD", "BTC", "ETH", "WYNN", "MRSH", "VTI", "AUR", "LINK"]
seen_news   = set()
fired_alerts = {}
daily_news_cache = []
market_gift_fired_today = None
insider_seen = set()

TRUSTED_SOURCES = [
    "reuters", "bloomberg", "cnbc", "wsj", "wall street journal",
    "financial times", "marketwatch", "seeking alpha", "barron",
    "forbes", "yahoo finance", "ap news", "associated press",
    "business insider", "coinmarketcap", "cointelegraph",
    "benzinga", "the street", "investopedia"
]
NON_ENGLISH_KEYWORDS = [
    " de ", " la ", " el ", " en ", " es ", " que ", " del ",
    " los ", " las ", " por ", " con ", " para ", " una ", " ein ",
    " der ", " die ", " das ", " und ", " von ", " le ", " les ",
    " des ", " sur ", " est ", " par "
]

EARNINGS_CALENDAR = {
    "SOFI": "2026-05-04", "GWRE": "2026-05-21", "PANW": "2026-05-26",
    "RKLB": "2026-05-08", "AMZN": "2026-05-01", "GD":   "2026-04-23",
    "MRSH": "2026-04-17", "AUR":  "2026-05-08",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def is_trusted_english(title, source="", url=""):
    if not title:
        return False
    if sum(1 for c in title if ord(c) > 127) > len(title) * 0.05:
        return False
    if any(kw in title.lower() for kw in NON_ENGLISH_KEYWORDS):
        return False
    src, u = source.lower(), url.lower()
    return any(s in src or s in u for s in TRUSTED_SOURCES)

def is_market_open():
    now = datetime.now(EST)
    return now.weekday() < 5 and time(9, 30) <= now.time() <= time(16, 0)

def is_weekday():
    return datetime.now(EST).weekday() < 5

# ─── PRICE FETCHING ───────────────────────────────────────────────────────────
async def get_stock_price(session, ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
            data = await r.json()
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception as e:
        logger.error(f"Price fetch error {ticker}: {e}")
    return None

async def get_crypto_price(session, coin_id):
    try:
        tmap = {"bitcoin": "BTC-USD", "ethereum": "ETH-USD", "chainlink": "LINK-USD"}
        ticker = tmap.get(coin_id, f"{coin_id.upper()}-USD")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
            data = await r.json()
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception as e:
        logger.error(f"Crypto fetch error {coin_id}: {e}")
    return None

async def get_prev_close(session, ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
            data = await r.json()
            closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
            return float(closes[-2]) if len(closes) >= 2 else None
    except Exception as e:
        logger.error(f"Prev close error {ticker}: {e}")
    return None

async def get_historical_prices(session, ticker, days=60):
    try:
        period = "3mo" if days <= 90 else "1y"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={period}"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
            data = await r.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [float(c) for c in closes if c is not None]
    except Exception as e:
        logger.error(f"Historical prices error {ticker}: {e}")
    return None

async def fetch_index(session, ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
            data = await r.json()
            result = data["chart"]["result"][0]
            closes = [c for c in result["indicators"]["quote"][0]["close"] if c]
            current = float(result["meta"].get("regularMarketPrice", closes[-1]))
            prev = closes[-2] if len(closes) >= 2 else current
            return {"price": current, "chg": ((current - prev) / prev) * 100, "high_30d": max(closes), "closes": closes}
    except Exception as e:
        logger.error(f"Index fetch error {ticker}: {e}")
    return None

# ─── INDICATORS ───────────────────────────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    if al == 0: return 100.0
    for i in range(period, len(deltas)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0: return 100.0
    return round(100 - (100 / (1 + ag / al)), 1)

def calc_sma(prices, period):
    if len(prices) < period: return None
    return round(sum(prices[-period:]) / period, 2)

def calc_macd(prices):
    if len(prices) < MA_SLOW + MA_SIGNAL:
        return None, None, None
    kf, ks = 2/(MA_FAST+1), 2/(MA_SLOW+1)
    ef = sum(prices[:MA_FAST]) / MA_FAST
    es = sum(prices[:MA_SLOW]) / MA_SLOW
    fv, sv = [], []
    for i, p in enumerate(prices):
        if i >= MA_FAST: ef = p*kf + ef*(1-kf); fv.append(ef)
        if i >= MA_SLOW: es = p*ks + es*(1-ks); sv.append(es)
    ml = min(len(fv), len(sv))
    macd_line = [fv[-(ml-i)] - sv[-(ml-i)] for i in range(ml)]
    if len(macd_line) < MA_SIGNAL: return None, None, None
    ks2 = 2/(MA_SIGNAL+1)
    sig = sum(macd_line[:MA_SIGNAL]) / MA_SIGNAL
    for v in macd_line[MA_SIGNAL:]: sig = v*ks2 + sig*(1-ks2)
    mv = macd_line[-1]
    return round(mv, 4), round(sig, 4), round(mv - sig, 4)

# ─── MARKET SCORING ───────────────────────────────────────────────────────────
async def get_market_score(session):
    sp500   = await fetch_index(session, "^GSPC")
    nasdaq  = await fetch_index(session, "^IXIC")
    dow     = await fetch_index(session, "^DJI")
    vix_d   = await fetch_index(session, "^VIX")
    treasury= await fetch_index(session, "^TNX")
    dxy     = await fetch_index(session, "DX-Y.NYB")
    futures = await fetch_index(session, "ES=F")
    await asyncio.sleep(0.5)

    score = 0
    flags = []

    if sp500 and len(sp500["closes"]) >= 20:
        sma20 = sum(sp500["closes"][-20:]) / 20
        if sp500["price"] > sma20:
            score += 2; flags.append(("✅", "S&P 500 is trading above its 20-day moving average — uptrend intact"))
        else:
            score -= 2; flags.append(("⚠️", "S&P 500 is below its 20-day moving average — short-term trend has broken down"))
        drawdown = ((sp500["high_30d"] - sp500["price"]) / sp500["high_30d"]) * 100
        if drawdown > 10:
            score -= 2; flags.append(("⚠️", f"S&P is {drawdown:.1f}% off its 30-day high — meaningful pullback in progress"))
        elif drawdown < 3:
            score += 1; flags.append(("✅", f"S&P is within {drawdown:.1f}% of its 30-day high — strength confirmed"))

    if vix_d:
        v = vix_d["price"]
        if v < 15:   score += 2; flags.append(("✅", f"VIX at {v:.1f} — very low fear, markets are complacent"))
        elif v < 20: score += 1; flags.append(("✅", f"VIX at {v:.1f} — calm conditions, normal trading environment"))
        elif v < 25: score -= 1; flags.append(("⚠️", f"VIX at {v:.1f} — volatility is elevated, traders are cautious"))
        elif v < 30: score -= 2; flags.append(("🔴", f"VIX at {v:.1f} — high fear in the market, proceed carefully"))
        else:        score -= 3; flags.append(("🔴", f"VIX at {v:.1f} — extreme fear, this is a risk-off environment"))

    if futures:
        fc = futures["chg"]
        if fc > 0.5:    score += 1; flags.append(("✅", f"Futures are up {fc:.2f}% — overnight sentiment is positive"))
        elif fc < -0.5: score -= 1; flags.append(("⚠️", f"Futures are down {fc:.2f}% — overnight selling pressure"))
        else:           flags.append(("➡️", f"Futures are flat ({fc:+.2f}%) — no strong directional bias overnight"))

    if treasury:
        ty = treasury["price"]
        if ty > 4.5:   score -= 1; flags.append(("⚠️", f"10-year yield at {ty:.2f}% — elevated rates adding pressure to equities"))
        elif ty < 4.0: score += 1; flags.append(("✅", f"10-year yield at {ty:.2f}% — rates supportive for equity valuations"))
        else:          flags.append(("➡️", f"10-year yield at {ty:.2f}% — rates are neutral"))

    if score >= 4:
        cond, c_color, c_bg, c_emoji = "BULL",    "#1a7a4a", "#e8f5ee", "🟢"
        verdict = (
            "Market conditions look constructive heading into today's session. "
            "Momentum is on the side of the bulls — the trend is intact, volatility is contained, "
            "and there's no major macro pressure from rates or futures. This is an environment "
            "where quality setups are worth acting on. Keep your watchlist ready and don't over-think entries "
            "on names you've already done the work on."
        )
    elif score >= 1:
        cond, c_color, c_bg, c_emoji = "NEUTRAL", "#a06a10", "#fef6e4", "🟡"
        verdict = (
            "The market is sending mixed signals today — some constructive, some cautionary. "
            "This isn't a day to be aggressive, but it's also not a day to be defensive. "
            "Focus on your highest-conviction ideas only and keep position sizing in check. "
            "If a trade doesn't look clean, it probably isn't. Patience is the edge in a choppy market."
        )
    elif score >= -2:
        cond, c_color, c_bg, c_emoji = "CAUTION", "#b83232", "#fceaea", "🔴"
        verdict = (
            "Conditions have shifted to cautious today. The risk/reward on new entries isn't favorable right now — "
            "there's enough weakness in the signals to suggest sitting on your hands is the smart play. "
            "Hold your existing positions, but resist the urge to add. "
            "Let the market show you stabilization before deploying capital. Your cash is working for you right now."
        )
    else:
        cond, c_color, c_bg, c_emoji = "BEAR",    "#7a0000", "#ffe8e8", "💀"
        verdict = (
            "This is a risk-off day. Multiple signals are flashing red and the weight of evidence points to "
            "continued near-term weakness. Capital preservation takes priority — now is not the time to be a hero. "
            "If you have speculative positions that are underwater, it's worth asking whether you'd buy them today. "
            "If the answer is no, consider whether holding still makes sense."
        )

    return {
        "score": score, "flags": flags, "cond": cond,
        "c_color": c_color, "c_bg": c_bg, "c_emoji": c_emoji,
        "verdict": verdict,
        "sp500": sp500, "nasdaq": nasdaq, "dow": dow,
        "vix_d": vix_d, "treasury": treasury, "dxy": dxy, "futures": futures
    }

# ─── FEAR & GREED ─────────────────────────────────────────────────────────────
async def get_fear_greed():
    try:
        async with aiohttp.ClientSession() as s:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
                data = await r.json()
                score = float(data["fear_and_greed"]["score"])
                return {"score": score, "rating": data["fear_and_greed"]["rating"]}
    except Exception as e:
        logger.error(f"Fear & Greed error: {e}")
    return None

def fg_emoji(score):
    if score <= 25: return "💀"
    elif score <= 45: return "😨"
    elif score <= 55: return "😐"
    elif score <= 75: return "😊"
    else: return "🤑"

def fg_color(score):
    if score <= 25: return "#7a0000"
    elif score <= 45: return "#b83232"
    elif score <= 55: return "#a06a10"
    elif score <= 75: return "#1a7a4a"
    else: return "#0d5c38"

def fg_plain_english(score, rating):
    if score <= 25:
        return f"Extreme Fear ({int(score)}/100) — investors are panic-selling. Historically a contrarian buying opportunity, but confirm with your own signals before acting."
    elif score <= 45:
        return f"Fear ({int(score)}/100) — sentiment is negative and cautious money is on the sidelines. Worth watching for signs of a turn."
    elif score <= 55:
        return f"Neutral ({int(score)}/100) — the market isn't strongly leaning either way. No strong sentiment edge today."
    elif score <= 75:
        return f"Greed ({int(score)}/100) — optimism is building. Markets can stay greedy for a while, but be selective about chasing."
    else:
        return f"Extreme Greed ({int(score)}/100) — euphoria is in the air. This level of greed historically precedes pullbacks. Tighten up on speculative positions."

# ─── TREASURY YIELDS ──────────────────────────────────────────────────────────
async def get_treasury_yields():
    try:
        async with aiohttp.ClientSession() as s:
            tickers = {"2yr": "^IRX", "5yr": "^FVX", "10yr": "^TNX", "30yr": "^TYX"}
            yields = {}
            for name, ticker in tickers.items():
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
                async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
                    data = await r.json()
                    closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                    if closes: yields[name] = round(closes[-1], 3)
                await asyncio.sleep(0.2)
            return yields
    except Exception as e:
        logger.error(f"Treasury yields error: {e}")
    return {}

def treasury_plain_english(yields):
    lines = []
    t10 = yields.get("10yr")
    t2  = yields.get("2yr")
    if t10:
        if t10 > 4.5:
            lines.append(f"The 10-year Treasury is at {t10:.2f}% — still elevated, which keeps pressure on growth stocks and borrowing costs.")
        elif t10 < 4.0:
            lines.append(f"The 10-year Treasury sits at {t10:.2f}% — relatively supportive for equities and growth names.")
        else:
            lines.append(f"The 10-year yield is at {t10:.2f}% — in a neutral range, not a major headwind or tailwind for stocks right now.")
    if t2 and t10:
        spread = t10 - t2
        if spread < 0:
            lines.append(f"The yield curve remains inverted (2yr: {t2:.2f}% vs 10yr: {t10:.2f}%) — a historically reliable recession signal, though timing is always uncertain.")
        else:
            lines.append(f"The yield curve is positively sloped (2yr: {t2:.2f}% vs 10yr: {t10:.2f}%) — a healthier economic signal.")
    return " ".join(lines)

# ─── NEWS FETCHING ────────────────────────────────────────────────────────────
async def get_news(session, query, max_articles=3):
    try:
        url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize=10&language=en&apiKey={NEWS_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            articles = []
            for a in data.get("articles", []):
                title  = a.get("title", "")
                source = a.get("source", {}).get("name", "")
                url_a  = a.get("url", "")
                if url_a in seen_news: continue
                if not is_trusted_english(title, source, url_a): continue
                seen_news.add(url_a)
                articles.append({"title": title, "source": source, "url": url_a,
                                  "description": (a.get("description") or "")[:120]})
                if len(articles) >= max_articles: break
            return articles
    except Exception as e:
        logger.error(f"News fetch error {query}: {e}")
    return []

async def collect_news():
    async with aiohttp.ClientSession() as session:
        for ticker in NEWS_TICKERS:
            current = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            prev    = None if ticker in CRYPTO_MAP else await get_prev_close(session, ticker)
            articles = await get_news(session, ticker, max_articles=2)
            for a in articles:
                if a["url"] in [n["url"] for n in daily_news_cache]: continue
                move_pct = ((current - prev) / prev) * 100 if current and prev else 0
                daily_news_cache.append({
                    "ticker": ticker, "title": a["title"], "source": a["source"],
                    "url": a["url"], "move_pct": move_pct,
                    "direction": "📈" if move_pct > 0 else "📉"
                })
            await asyncio.sleep(0.5)

# ─── EARNINGS CALENDAR LOOKUPS ────────────────────────────────────────────────
def get_upcoming_earnings(days_ahead=7):
    today = datetime.now(EST).date()
    upcoming = []
    for ticker, date_str in EARNINGS_CALENDAR.items():
        try:
            ed = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (ed - today).days
            if 0 <= days_away <= days_ahead:
                upcoming.append({"ticker": ticker, "date": ed.strftime("%b %d"), "days": days_away})
        except: continue
    return sorted(upcoming, key=lambda x: x["days"])

# ─── TELEGRAM SENDER ──────────────────────────────────────────────────────────
async def send_message(text):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

# ─── EMAIL BUILDER ────────────────────────────────────────────────────────────
async def send_email(subject, html_body):
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logger.info(f"Email sent: {subject}")
    except Exception as e:
        logger.error(f"Email send error: {e}")

def email_header(title, subtitle):
    return f"""
    <tr><td style="background:#0f0f14;padding:24px 32px;">
        <div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#555;text-transform:uppercase;margin-bottom:5px;">Patrick Portfolio Bot</div>
        <div style="font-size:22px;font-weight:700;color:#e8c96e;letter-spacing:-0.3px;">{title}</div>
        <div style="font-size:13px;color:#666;margin-top:4px;">{subtitle}</div>
    </td></tr>"""

def email_section(label, content, bg="#ffffff"):
    return f"""
    <tr><td style="background:{bg};padding:20px 32px;border-bottom:1px solid #f0f0f0;">
        <div style="font-size:10px;font-family:monospace;letter-spacing:0.12em;color:#aaa;text-transform:uppercase;margin-bottom:10px;">{label}</div>
        <div style="font-size:14px;color:#1a1a1a;line-height:1.8;">{content}</div>
    </td></tr>"""

def email_footer(note=""):
    date_short = datetime.now(EST).strftime("%b %d, %Y")
    return f"""
    <tr><td style="background:#fafafa;padding:14px 32px;text-align:center;border-top:1px solid #f0f0f0;">
        <div style="font-size:11px;color:#bbb;font-family:monospace;">Not financial advice · Patrick Portfolio Bot · {date_short}{' · ' + note if note else ''}</div>
    </td></tr>"""

def wrap_email(rows):
    return f"""
    <html><body style="margin:0;padding:0;background:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;padding:28px 16px;">
    <tr><td align="center">
    <table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1);">
    {rows}
    </table>
    </td></tr></table>
    </body></html>"""

def idx_row_html(name, data, invert=False):
    if not data:
        return f'<tr><td colspan="3" style="padding:7px 10px;font-size:12px;color:#999;">{name} — unavailable</td></tr>'
    chg   = data["chg"]
    color = ("#b83232" if chg >= 0 else "#1a7a4a") if invert else ("#1a7a4a" if chg >= 0 else "#b83232")
    arrow = "▲" if chg >= 0 else "▼"
    return (f'<tr><td style="padding:7px 10px;font-size:13px;font-weight:500;border-bottom:1px solid #f5f5f5;">{name}</td>'
            f'<td style="padding:7px 10px;font-size:13px;border-bottom:1px solid #f5f5f5;">{data["price"]:,.2f}</td>'
            f'<td style="padding:7px 10px;font-size:13px;font-weight:500;color:{color};border-bottom:1px solid #f5f5f5;">{arrow} {abs(chg):.2f}%</td></tr>')

def index_table_html(ms):
    header = ('<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">'
              '<tr style="background:#f8f8f8;"><th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Index</th>'
              '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Level</th>'
              '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Change</th></tr>')
    rows = (idx_row_html("S&P 500", ms["sp500"]) +
            idx_row_html("Nasdaq", ms["nasdaq"]) +
            idx_row_html("Dow Jones", ms["dow"]) +
            idx_row_html("S&P Futures", ms["futures"]) +
            idx_row_html("VIX", ms["vix_d"], invert=True) +
            idx_row_html("10-yr Treasury", ms["treasury"], invert=True) +
            idx_row_html("Dollar (DXY)", ms["dxy"], invert=True))
    return header + rows + "</table>"

def portfolio_table_html(prices_data):
    rows = ""
    for ticker, info, price, prev in prices_data:
        if not price: continue
        value = price * info["shares"]
        cost  = info["avg_cost"] * info["shares"]
        total_pl = ((value - cost) / cost) * 100
        pl_color = "#1a7a4a" if total_pl >= 0 else "#b83232"
        if prev:
            day_chg = ((price - prev) / prev) * 100
            day_str = f"+{day_chg:.1f}%" if day_chg >= 0 else f"{day_chg:.1f}%"
            day_col = "#1a7a4a" if day_chg >= 0 else "#b83232"
        else:
            day_str, day_col = "—", "#999"
        rows += (f'<tr><td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-weight:600;font-size:13px;">{ticker}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:12px;color:#666;">{info["name"]}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;text-align:right;">${price:,.2f}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;text-align:right;color:{day_col};font-weight:500;">{day_str}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;text-align:right;color:{pl_color};">{total_pl:+.1f}%</td></tr>')
    return ('<table width="100%" cellpadding="0" cellspacing="0">'
            '<tr style="background:#f8f8f8;">'
            '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Ticker</th>'
            '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Name</th>'
            '<th style="padding:7px 10px;text-align:right;font-size:11px;color:#999;font-weight:500;">Price</th>'
            '<th style="padding:7px 10px;text-align:right;font-size:11px;color:#999;font-weight:500;">Day</th>'
            '<th style="padding:7px 10px;text-align:right;font-size:11px;color:#999;font-weight:500;">Total P&L</th></tr>'
            + rows + '</table>')

def goal_bar_html(total_value, goal=365000):
    pct = min((total_value / goal) * 100, 100)
    bar = int(pct)
    gap = max(goal - total_value, 0)
    return (f'<div style="font-size:24px;font-weight:700;color:#e8a030;">${total_value:,.0f}</div>'
            f'<div style="font-size:13px;color:#888;margin-bottom:8px;">{pct:.1f}% of $365k goal</div>'
            f'<div style="background:#f0f0f0;border-radius:4px;height:8px;overflow:hidden;margin-bottom:8px;">'
            f'<div style="background:#e8a030;height:100%;width:{bar}%;border-radius:4px;"></div></div>'
            f'<div style="font-size:12px;color:#999;">Gap to goal: ${gap:,.0f}</div>')

def news_html_block(items, max_items=5):
    if not items:
        return '<div style="color:#999;font-size:13px;font-style:italic;">No relevant news from trusted sources today.</div>'
    html = ""
    seen = set()
    count = 0
    for item in items:
        if count >= max_items: break
        if item["url"] in seen: continue
        seen.add(item["url"])
        count += 1
        badge = ""
        if abs(item.get("move_pct", 0)) >= 3:
            mc = "#1a7a4a" if item["move_pct"] > 0 else "#b83232"
            badge = f'<span style="background:{mc};color:#fff;font-size:10px;padding:2px 7px;border-radius:3px;margin-left:6px;">{item["direction"]}{abs(item["move_pct"]):.1f}%</span>'
        ticker_label = f'<span style="font-size:11px;font-weight:700;color:#e8a030;">{item.get("ticker","")}</span>{badge}' if item.get("ticker") else ""
        html += (f'<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;">'
                 f'<div style="margin-bottom:4px;">{ticker_label}</div>'
                 f'<div style="font-size:13px;color:#1a1a1a;margin-bottom:4px;line-height:1.5;">{item["title"]}</div>'
                 f'<div style="font-size:11px;color:#999;">{item["source"]} &nbsp;·&nbsp; <a href="{item["url"]}" style="color:#5b9cf6;text-decoration:none;">Read →</a></div>'
                 f'</div>')
    return html

# ─── PORTFOLIO DATA HELPER ────────────────────────────────────────────────────
async def get_all_prices(session):
    prices_data = []
    total_value = 0
    for ticker, info in HOLDINGS.items():
        price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
        prev  = None if ticker in CRYPTO_MAP else await get_prev_close(session, ticker)
        if price:
            total_value += price * info["shares"]
        prices_data.append((ticker, info, price, prev))
    return prices_data, total_value

# ═══════════════════════════════════════════════════════════════════════════════
# ─── MORNING EMAIL — Daily Market Outlook (9:30am) ────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
async def send_morning_email():
    logger.info("Sending morning market outlook email...")
    async with aiohttp.ClientSession() as session:

        ms     = await get_market_score(session)
        fg     = await get_fear_greed()
        yields = await get_treasury_yields()

        # Overnight news
        overnight_news = await get_news(session, "stock market economy", max_articles=4)
        holdings_news  = []
        for ticker in ["RKLB", "AMZN", "GWRE", "SOFI", "GD"]:
            articles = await get_news(session, ticker, max_articles=1)
            for a in articles:
                a["ticker"] = ticker
                holdings_news.append(a)

        date_str   = datetime.now(EST).strftime("%A, %B %d, %Y")
        date_short = datetime.now(EST).strftime("%a %b %d")
        time_str   = datetime.now(EST).strftime("%I:%M %p EST")

        # Condition banner
        condition_banner = (
            f'<tr><td style="background:{ms["c_bg"]};padding:18px 32px;border-bottom:3px solid {ms["c_color"]};">'
            f'<div style="font-size:10px;font-family:monospace;letter-spacing:0.12em;color:{ms["c_color"]};text-transform:uppercase;margin-bottom:5px;">Today\'s Market Condition</div>'
            f'<div style="font-size:28px;font-weight:800;color:{ms["c_color"]};letter-spacing:-0.5px;">{ms["c_emoji"]} {ms["cond"]}</div>'
            f'<div style="font-size:12px;color:{ms["c_color"]};margin-top:3px;opacity:0.8;">Score: {"+" if ms["score"] > 0 else ""}{ms["score"]} · {len(ms["flags"])} signals evaluated</div>'
            f'</td></tr>'
        )

        # Verdict paragraph
        verdict_html = (
            f'<div style="background:{ms["c_bg"]};border-left:4px solid {ms["c_color"]};'
            f'border-radius:0 8px 8px 0;padding:16px 18px;font-size:14px;color:#1a1a1a;line-height:1.8;">'
            f'{ms["verdict"]}</div>'
        )

        # Signals list
        signals_html = "".join(
            f'<div style="padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;color:#333;">'
            f'<span style="margin-right:8px;">{icon}</span>{text}</div>'
            for icon, text in ms["flags"]
        )

        # Fear & Greed
        fg_html = ""
        if fg:
            fgc = fg_color(fg["score"])
            fg_html = (
                f'<div style="display:flex;align-items:center;gap:16px;background:#f8f8f8;border-radius:8px;padding:14px 16px;margin-bottom:10px;">'
                f'<div style="font-size:32px;font-weight:800;color:{fgc};">{fg_emoji(fg["score"])} {int(fg["score"])}</div>'
                f'<div style="font-size:13px;color:#333;line-height:1.6;">{fg_plain_english(fg["score"], fg["rating"])}</div>'
                f'</div>'
            )

        # Treasuries
        treasury_text = treasury_plain_english(yields) if yields else ""
        treasury_html = f'<div style="font-size:13px;color:#333;line-height:1.8;margin-bottom:10px;">{treasury_text}</div>'
        if yields:
            yield_pills = "".join(
                f'<span style="display:inline-block;background:#f0f0f0;border-radius:4px;padding:4px 10px;'
                f'font-size:12px;font-family:monospace;margin:3px 4px 3px 0;'
                f'color:{"#b83232" if v >= TREASURY_ALERT_THRESHOLD else "#333"};">'
                f'{k.upper()} {v:.2f}%</span>'
                for k, v in yields.items()
            )
            treasury_html += f'<div style="margin-top:6px;">{yield_pills}</div>'

        # Stocks to watch today
        watchlist_html = ""
        wl = load_watchlist()
        for item in wl:
            price = await get_stock_price(session, item["ticker"])
            if price:
                diff   = price - item["target"]
                sc     = "#1a7a4a" if price <= item["target"] else "#888"
                status = "🟢 In buy zone" if price <= item["target"] else f"${abs(diff):.2f} above target"
                watchlist_html += (
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:9px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">'
                    f'<span style="font-weight:600;">{item["ticker"]}</span>'
                    f'<span style="color:#555;">${price:,.2f}</span>'
                    f'<span style="color:#aaa;">Target ${item["target"]}</span>'
                    f'<span style="color:{sc};">{status}</span></div>'
                )

        # Earnings this week
        upcoming = get_upcoming_earnings(days_ahead=5)
        earnings_html = ""
        if upcoming:
            for e in upcoming:
                days_label = "Today" if e["days"] == 0 else ("Tomorrow" if e["days"] == 1 else f"In {e['days']} days")
                earnings_html += (
                    f'<div style="display:flex;justify-content:space-between;padding:7px 0;'
                    f'border-bottom:1px solid #f5f5f5;font-size:13px;">'
                    f'<span style="font-weight:600;">{e["ticker"]}</span>'
                    f'<span style="color:#555;">{e["date"]}</span>'
                    f'<span style="color:#e8a030;">{days_label}</span></div>'
                )
        else:
            earnings_html = '<div style="font-size:13px;color:#999;">No earnings from your holdings this week.</div>'

        # Active targets
        targets_html = (
            '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            '<span style="background:#fff0f0;color:#b83232;border:0.5px solid #fca5a5;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">RKLB $100 TRIM</span>'
            '<span style="background:#f0fff4;color:#166534;border:0.5px solid #86efac;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">GWRE $158 ADD</span>'
            '<span style="background:#f0fff4;color:#166534;border:0.5px solid #86efac;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">PANW $160 BUY</span>'
            '<span style="background:#f0fff4;color:#166534;border:0.5px solid #86efac;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">WYNN $90 BUY</span>'
            '</div>'
        )

        rows = (
            email_header(f"{ms['c_emoji']} Daily Market Outlook", f"{date_str} · {time_str}") +
            condition_banner +
            email_section("Today's Verdict", verdict_html) +
            email_section("Signal Breakdown", signals_html) +
            email_section("Market Indices", index_table_html(ms)) +
            email_section("Sentiment — Fear & Greed", fg_html) +
            email_section("Treasury Yields", treasury_html) +
            email_section("Watchlist — Stocks to Watch", watchlist_html if watchlist_html else '<div style="color:#999;font-size:13px;">No watchlist items in buy zone today.</div>') +
            email_section("Earnings This Week", earnings_html) +
            (email_section("Overnight & Morning News", news_html_block([{**a, "ticker": ""} for a in overnight_news])) if overnight_news else "") +
            (email_section("News on Your Holdings", news_html_block(holdings_news)) if holdings_news else "") +
            email_section("Your Active Targets", targets_html, bg="#fafafa") +
            email_footer()
        )

        await send_email(f"{ms['c_emoji']} Market Outlook — {ms['cond']} · {date_short}", wrap_email(rows))
        logger.info(f"Morning email sent — {ms['cond']}")

        # Also send Telegram morning brief
        await send_morning_brief_telegram(ms)

# ─── TELEGRAM MORNING BRIEF ───────────────────────────────────────────────────
async def send_morning_brief_telegram(ms=None):
    async with aiohttp.ClientSession() as session:
        lines = ["☀️ *MORNING BRIEF*", f"📅 {datetime.now(EST).strftime('%A, %b %d · %I:%M %p EST')}", "─" * 30]
        total_value = 0
        for ticker, info in HOLDINGS.items():
            price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            if price:
                value = price * info["shares"]
                total_value += value
                lines.append(f"📌 *{ticker}* — ${price:,.2f} | ${value:,.0f}")
        lines.append("─" * 30)
        lines.append(f"💼 *Portfolio:* ${total_value:,.0f}")
        if ms:
            lines.append(f"📊 *Market:* {ms['c_emoji']} {ms['cond']}")
        lines.append("─" * 30)
        lines.append("⚡ _RKLB $100 · GWRE $158 · PANW $160 · WYNN $90_")
        await send_message("\n".join(lines))

        await asyncio.sleep(3)
        await send_sleeper_pick(session)

# ═══════════════════════════════════════════════════════════════════════════════
# ─── EVENING EMAIL — Market Wrap + Portfolio Review (5:00pm) ──────────────────
# ═══════════════════════════════════════════════════════════════════════════════
async def send_evening_email():
    logger.info("Sending evening wrap email...")
    async with aiohttp.ClientSession() as session:

        prices_data, total_value = await get_all_prices(session)
        ms     = await get_market_score(session)
        yields = await get_treasury_yields()

        # Tomorrow's prep
        tomorrow = datetime.now(EST) + timedelta(days=1)
        tom_str  = tomorrow.strftime("%A, %B %d")
        upcoming = get_upcoming_earnings(days_ahead=3)
        tom_earnings = [e for e in upcoming if e["days"] <= 2]

        # Govt data calendar (static — update as needed)
        govt_events = [
            {"date": "Mon Mar 25", "event": "Durable Goods Orders"},
            {"date": "Wed Mar 26", "event": "GDP Final Q4"},
            {"date": "Thu Mar 27", "event": "Jobless Claims · PCE Inflation"},
            {"date": "Fri Mar 28", "event": "Personal Income & Spending"},
        ]

        date_str   = datetime.now(EST).strftime("%A, %B %d, %Y")
        date_short = datetime.now(EST).strftime("%a %b %d")

        # Day wrap verdict
        sp_chg = ms["sp500"]["chg"] if ms["sp500"] else 0
        if sp_chg >= 1.0:
            day_wrap = f"A solid session — the S&P finished up {sp_chg:.2f}%, with broad participation across sectors. The bulls maintained control throughout the day."
        elif sp_chg >= 0:
            day_wrap = f"A quiet, slightly positive session. The S&P edged up {sp_chg:.2f}%, nothing dramatic but the path of least resistance remains upward."
        elif sp_chg >= -1.0:
            day_wrap = f"A modestly negative day — the S&P slipped {abs(sp_chg):.2f}%. Nothing alarming, but the market gave back some ground without a clear catalyst."
        else:
            day_wrap = f"A rough session — the S&P sold off {abs(sp_chg):.2f}%. Broad weakness with few places to hide. Worth monitoring overnight sentiment before tomorrow's open."

        # Tomorrow section
        tom_html = f'<div style="font-size:13px;color:#333;line-height:1.8;margin-bottom:12px;">Here\'s what\'s on the radar for <strong>{tom_str}</strong>:</div>'

        if tom_earnings:
            tom_html += '<div style="font-size:12px;font-weight:600;color:#e8a030;margin-bottom:6px;">EARNINGS</div>'
            for e in tom_earnings:
                label = "Tomorrow" if e["days"] == 1 else "In 2 days"
                tom_html += (f'<div style="padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;display:flex;justify-content:space-between;">'
                             f'<span style="font-weight:600;">{e["ticker"]}</span><span style="color:#888;">{e["date"]}</span>'
                             f'<span style="color:#e8a030;">{label}</span></div>')

        tom_html += '<div style="font-size:12px;font-weight:600;color:#888;margin:12px 0 6px;">ECONOMIC DATA THIS WEEK</div>'
        for event in govt_events[:3]:
            tom_html += (f'<div style="padding:5px 0;border-bottom:1px solid #f5f5f5;font-size:13px;display:flex;justify-content:space-between;">'
                         f'<span style="color:#555;">{event["date"]}</span><span style="color:#333;">{event["event"]}</span></div>')

        # Watchlist
        watchlist_html = ""
        for item in load_watchlist():
            price = await get_stock_price(session, item["ticker"])
            if price:
                diff = price - item["target"]
                sc   = "#1a7a4a" if price <= item["target"] else "#888"
                stat = "🟢 In buy zone" if price <= item["target"] else f"${abs(diff):.2f} above target"
                watchlist_html += (f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">'
                                   f'<span style="font-weight:600;">{item["ticker"]}</span><span>${price:,.2f}</span>'
                                   f'<span style="color:#aaa;">Target ${item["target"]}</span><span style="color:{sc};">{stat}</span></div>')

        rows = (
            email_header("📊 Evening Market Wrap", f"{date_str} · 5:00pm EST") +
            email_section("Day in Review", f'<div style="font-size:14px;color:#333;line-height:1.8;">{day_wrap}</div>') +
            email_section("Closing Indices", index_table_html(ms)) +
            email_section("Your Portfolio — Close", portfolio_table_html(prices_data)) +
            email_section("Goal Progress", goal_bar_html(total_value)) +
            email_section("Watchlist Check", watchlist_html if watchlist_html else '<div style="color:#999;font-size:13px;">No items on watchlist.</div>') +
            email_section("Today's News", news_html_block(daily_news_cache, max_items=5)) +
            email_section("Looking Ahead — Tomorrow & This Week", tom_html) +
            email_footer()
        )

        await send_email(f"📊 Evening Wrap — {date_short}", wrap_email(rows))

        daily_news_cache.clear()
        logger.info("Evening email sent, news cache cleared")

# ═══════════════════════════════════════════════════════════════════════════════
# ─── MONDAY EMAIL — Week Ahead Outlook (7:45am) ───────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
async def send_monday_email():
    logger.info("Sending Monday week ahead email...")
    async with aiohttp.ClientSession() as session:

        ms     = await get_market_score(session)
        fg     = await get_fear_greed()
        yields = await get_treasury_yields()
        prices_data, total_value = await get_all_prices(session)

        date_str   = datetime.now(EST).strftime("%A, %B %d, %Y")
        date_short = datetime.now(EST).strftime("%a %b %d")

        # Weekly outlook narrative
        score = ms["score"]
        if score >= 3:
            weekly_outlook = (
                "The week is setting up constructively. Momentum heading into Monday is positive, "
                "and the macro backdrop isn't throwing up major red flags. This is a week where "
                "staying patient on your watchlist names could pay off — be ready to act if entries line up. "
                "Keep an eye on how the market digests any economic data mid-week."
            )
        elif score >= 0:
            weekly_outlook = (
                "The week ahead looks mixed. There's no clear catalyst driving the market strongly "
                "in either direction, which means discipline matters more than ever. "
                "Stick to your plan, focus on names where the setup is clear, "
                "and don't let FOMO push you into marginal trades. "
                "A flat week where you protect capital is a good week."
            )
        else:
            weekly_outlook = (
                "Heading into this week with some caution warranted. The weight of the signals suggests "
                "the market needs to prove itself before adding new risk. "
                "Keep your watchlist ready, but let price action confirm before committing capital. "
                "Defensive positioning makes sense until conditions improve."
            )

        # Indicators deep dive
        indicators_html = ""
        if ms["sp500"] and len(ms["sp500"]["closes"]) >= 50:
            closes  = ms["sp500"]["closes"]
            sma20   = sum(closes[-20:]) / 20
            sma50   = sum(closes[-50:]) / 50
            rsi_val = calc_rsi(closes[-30:])
            indicators_html += (
                f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;">'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">S&P SMA20</div>'
                f'<div style="font-size:16px;font-weight:600;color:{"#1a7a4a" if ms["sp500"]["price"] > sma20 else "#b83232"};">${sma20:,.0f}</div>'
                f'<div style="font-size:11px;color:#999;">{"Price above ✅" if ms["sp500"]["price"] > sma20 else "Price below ⚠️"}</div></div>'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">S&P SMA50</div>'
                f'<div style="font-size:16px;font-weight:600;color:{"#1a7a4a" if ms["sp500"]["price"] > sma50 else "#b83232"};">${sma50:,.0f}</div>'
                f'<div style="font-size:11px;color:#999;">{"Price above ✅" if ms["sp500"]["price"] > sma50 else "Price below ⚠️"}</div></div>'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:12px;text-align:center;">'
                f'<div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">S&P RSI (14)</div>'
                f'<div style="font-size:16px;font-weight:600;color:{"#b83232" if rsi_val and rsi_val >= 70 else "#1a7a4a" if rsi_val and rsi_val <= 30 else "#333"};">{rsi_val if rsi_val else "—"}</div>'
                f'<div style="font-size:11px;color:#999;">{"Overbought ⚠️" if rsi_val and rsi_val >= 70 else "Oversold 🟢" if rsi_val and rsi_val <= 30 else "Neutral"}</div></div>'
                f'</div>'
            )

        if fg:
            fgc = fg_color(fg["score"])
            indicators_html += (
                f'<div style="background:#f8f8f8;border-radius:8px;padding:14px;display:flex;align-items:center;gap:14px;margin-bottom:10px;">'
                f'<div style="font-size:28px;font-weight:800;color:{fgc};">{fg_emoji(fg["score"])} {int(fg["score"])}</div>'
                f'<div style="font-size:13px;color:#333;line-height:1.6;">{fg_plain_english(fg["score"], fg["rating"])}</div></div>'
            )

        indicators_html += f'<div style="font-size:13px;color:#555;line-height:1.8;">{treasury_plain_english(yields)}</div>'

        # Holdings news this week
        holdings_news = []
        for ticker in list(HOLDINGS.keys())[:6]:
            if ticker in CRYPTO_MAP: continue
            articles = await get_news(session, ticker, max_articles=1)
            for a in articles:
                a["ticker"] = ticker
                holdings_news.append(a)
            await asyncio.sleep(0.3)

        # Earnings this week
        week_earnings = get_upcoming_earnings(days_ahead=7)
        earnings_html = ""
        if week_earnings:
            for e in week_earnings:
                earnings_html += (f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">'
                                  f'<span style="font-weight:600;">{e["ticker"]}</span><span style="color:#555;">{e["date"]}</span>'
                                  f'<span style="color:#e8a030;">In {e["days"]} day{"s" if e["days"] != 1 else ""}</span></div>')
        else:
            earnings_html = '<div style="font-size:13px;color:#999;">No earnings from your holdings this week.</div>'

        # Goal check
        gap = 365000 - total_value
        months_left = max(1, 12 - datetime.now(EST).month + 1)
        goal_html = (goal_bar_html(total_value) +
                     f'<div style="font-size:13px;color:#555;margin-top:10px;line-height:1.7;">'
                     f'{"You\'re on track — great position heading into the week." if gap <= 0 else f"Gap to $365k: ${gap:,.0f}. With {months_left} months left, that\'s roughly ${gap/months_left:,.0f}/month needed."}'
                     f'</div>')

        rows = (
            email_header("📅 Week Ahead Outlook", f"{date_str} · Monday Morning") +
            f'<tr><td style="background:{ms["c_bg"]};padding:16px 32px;border-bottom:3px solid {ms["c_color"]};">'
            f'<div style="font-size:12px;font-family:monospace;letter-spacing:0.1em;color:{ms["c_color"]};text-transform:uppercase;margin-bottom:4px;">Market Condition Heading In</div>'
            f'<div style="font-size:24px;font-weight:800;color:{ms["c_color"]};">{ms["c_emoji"]} {ms["cond"]}</div></td></tr>' +
            email_section("Weekly Outlook", f'<div style="font-size:14px;color:#333;line-height:1.8;">{weekly_outlook}</div>') +
            email_section("Market Indicators Deep Dive", indicators_html) +
            email_section("Indices Snapshot", index_table_html(ms)) +
            email_section("Earnings This Week", earnings_html) +
            (email_section("News on Your Holdings", news_html_block(holdings_news)) if holdings_news else "") +
            email_section("Portfolio — Current State", portfolio_table_html(prices_data)) +
            email_section("Goal Progress", goal_html) +
            email_footer("Have a great week")
        )

        await send_email(f"📅 Week Ahead — {date_short}", wrap_email(rows))
        logger.info("Monday email sent")

# ═══════════════════════════════════════════════════════════════════════════════
# ─── FRIDAY EMAIL — Week in Review (6:00pm) ───────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
async def send_friday_email():
    logger.info("Sending Friday week recap email...")
    async with aiohttp.ClientSession() as session:

        prices_data, total_value = await get_all_prices(session)
        ms = await get_market_score(session)

        date_str   = datetime.now(EST).strftime("%A, %B %d, %Y")
        date_short = datetime.now(EST).strftime("%a %b %d")

        # Performance analysis
        best   = {"ticker": "", "pct": -999, "price": 0}
        worst  = {"ticker": "", "pct": 999,  "price": 0}
        gainers, losers = [], []
        for ticker, info, price, prev in prices_data:
            if not price: continue
            cost    = info["avg_cost"] * info["shares"]
            value   = price * info["shares"]
            pl_pct  = ((value - cost) / cost) * 100
            if pl_pct > best["pct"]:
                best = {"ticker": ticker, "pct": pl_pct, "price": price, "name": info["name"]}
            if pl_pct < worst["pct"]:
                worst = {"ticker": ticker, "pct": pl_pct, "price": price, "name": info["name"]}
            if pl_pct > 0: gainers.append(ticker)
            else: losers.append(ticker)

        # Narrative
        sp_chg = ms["sp500"]["chg"] if ms["sp500"] else 0
        if sp_chg >= 1.5:
            week_recap = f"Strong finish to the week — the S&P wrapped up with a {sp_chg:.2f}% gain on the day, capping what looks like a constructive week overall. Momentum is heading into the weekend on solid footing."
        elif sp_chg >= 0:
            week_recap = f"The market closed quietly positive on Friday, up {sp_chg:.2f}%. Nothing dramatic, but the bulls maintained their edge through the close. A steady week."
        elif sp_chg >= -1.0:
            week_recap = f"A soft close to the week — the S&P dipped {abs(sp_chg):.2f}% on Friday. Markets are heading into the weekend with some unresolved questions, so the weekend news cycle is worth monitoring."
        else:
            week_recap = f"A rough end to the week. The S&P sold off {abs(sp_chg):.2f}% on Friday, leaving the market in a defensive posture. Use the weekend to reassess your positions with fresh eyes."

        perf_html = ""
        if best["ticker"]:
            perf_html += (f'<div style="background:#f0fff4;border-left:3px solid #1a7a4a;border-radius:0 8px 8px 0;padding:12px 14px;margin-bottom:10px;">'
                          f'<div style="font-size:11px;color:#166534;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Best Performer</div>'
                          f'<div style="font-size:15px;font-weight:600;color:#166534;">{best["ticker"]} — {best["pct"]:+.1f}% total return · ${best["price"]:,.2f}</div>'
                          f'<div style="font-size:12px;color:#888;margin-top:2px;">{best["name"]}</div></div>')
        if worst["ticker"]:
            perf_html += (f'<div style="background:#fff0f0;border-left:3px solid #b83232;border-radius:0 8px 8px 0;padding:12px 14px;">'
                          f'<div style="font-size:11px;color:#b83232;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Most Pressure</div>'
                          f'<div style="font-size:15px;font-weight:600;color:#b83232;">{worst["ticker"]} — {worst["pct"]:+.1f}% total return · ${worst["price"]:,.2f}</div>'
                          f'<div style="font-size:12px;color:#888;margin-top:2px;">{worst["name"]}</div></div>')

        # Weekend reads
        weekend_reads = await get_news(session, "investing economy market outlook weekend", max_articles=4)
        reads_html = news_html_block([{**a, "ticker": ""} for a in weekend_reads], max_items=4)

        # Notes / suggestions
        suggestions = []
        for ticker, info, price, prev in prices_data:
            if not price: continue
            cost   = info["avg_cost"] * info["shares"]
            value  = price * info["shares"]
            pl_pct = ((value - cost) / cost) * 100
            if ticker == "RKLB" and price >= 90:
                suggestions.append(f"<strong>RKLB</strong> is at ${price:,.2f} — getting close to your $100 trim target. Start thinking about your exit plan.")
            if pl_pct < -20:
                suggestions.append(f"<strong>{ticker}</strong> is down {abs(pl_pct):.1f}% from your cost basis. Worth reviewing your thesis over the weekend.")
            if pl_pct > 50 and ticker not in ["VTI", "BTC", "ETH"]:
                suggestions.append(f"<strong>{ticker}</strong> is up {pl_pct:.1f}% — consider whether your position sizing still makes sense at this level.")

        if not suggestions:
            suggestions.append("Portfolio looks clean heading into the weekend — no major flags to address.")

        notes_html = "".join(f'<div style="padding:7px 0;border-bottom:1px solid #f5f5f5;font-size:13px;color:#333;line-height:1.6;">{s}</div>' for s in suggestions)

        # Next week preview
        next_week_earnings = get_upcoming_earnings(days_ahead=10)
        nw_earnings = [e for e in next_week_earnings if e["days"] > 1]
        next_html = ""
        if nw_earnings:
            next_html += '<div style="font-size:12px;font-weight:600;color:#e8a030;margin-bottom:8px;">EARNINGS COMING UP</div>'
            for e in nw_earnings[:4]:
                next_html += (f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">'
                              f'<span style="font-weight:600;">{e["ticker"]}</span><span style="color:#888;">{e["date"]}</span>'
                              f'<span style="color:#555;">In {e["days"]} days</span></div>')

        next_html += (f'<div style="font-size:13px;color:#555;line-height:1.8;margin-top:12px;">'
                      f'Come back Monday morning for a full week-ahead briefing with updated indicators and market outlook.</div>')

        rows = (
            email_header("📋 Week in Review", f"{date_str} · Friday Close") +
            email_section("This Week's Story", f'<div style="font-size:14px;color:#333;line-height:1.8;">{week_recap}</div>') +
            email_section("Closing Indices", index_table_html(ms)) +
            email_section("Portfolio Performance", perf_html + "<br>" + portfolio_table_html(prices_data)) +
            email_section("Goal Progress", goal_bar_html(total_value)) +
            email_section("Notes & Suggestions", notes_html) +
            email_section("Weekend Reading", reads_html) +
            email_section("Looking Ahead to Next Week", next_html) +
            email_footer("Have a great weekend Patrick")
        )

        await send_email(f"📋 Week in Review — {date_short}", wrap_email(rows))
        logger.info("Friday email sent")

# ═══════════════════════════════════════════════════════════════════════════════
# ─── SLEEPER STOCK SCANNER ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
SLEEPER_WATCHLIST = [
    {"ticker": "PANW",  "name": "Palo Alto Networks",  "sector": "Cybersecurity"},
    {"ticker": "WYNN",  "name": "Wynn Resorts",         "sector": "Casino/Hospitality"},
    {"ticker": "CRWD",  "name": "CrowdStrike",          "sector": "Cybersecurity"},
    {"ticker": "TTD",   "name": "The Trade Desk",       "sector": "AdTech"},
    {"ticker": "ASTS",  "name": "AST SpaceMobile",      "sector": "Space Broadband"},
    {"ticker": "OKLO",  "name": "Oklo Inc",             "sector": "Micro Nuclear"},
    {"ticker": "LUNR",  "name": "Intuitive Machines",   "sector": "Space/NASA"},
    {"ticker": "UBER",  "name": "Uber",                 "sector": "Mobility/AV"},
    {"ticker": "MELI",  "name": "MercadoLibre",         "sector": "LatAm E-commerce"},
    {"ticker": "DUOL",  "name": "Duolingo",             "sector": "EdTech"},
    {"ticker": "NET",   "name": "Cloudflare",           "sector": "Cloud Security"},
    {"ticker": "PLTR",  "name": "Palantir",             "sector": "AI/Data Analytics"},
    {"ticker": "COIN",  "name": "Coinbase",             "sector": "Crypto Exchange"},
    {"ticker": "SQ",    "name": "Block Inc",            "sector": "Fintech"},
    {"ticker": "SHOP",  "name": "Shopify",              "sector": "E-commerce"},
    {"ticker": "ZS",    "name": "Zscaler",              "sector": "Cybersecurity"},
    {"ticker": "DDOG",  "name": "Datadog",              "sector": "Cloud Monitoring"},
]

async def send_sleeper_pick(session):
    candidates = []
    for stock in SLEEPER_WATCHLIST:
        ticker = stock["ticker"]
        try:
            from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            to_date   = datetime.now().strftime("%Y-%m-%d")
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}?adjusted=true&sort=asc&limit=365&apiKey={POLYGON_API_KEY}"
            async with session.get(url, timeout=10) as r:
                data = await r.json()
                if not data.get("results") or len(data["results"]) < 30: continue
                prices   = [float(x["c"]) for x in data["results"]]
                current  = prices[-1]
                high_52w = max(prices)
                drawdown = ((high_52w - current) / high_52w) * 100
                rsi      = calc_rsi(prices[-30:], 14)
                if drawdown >= 30 and rsi and rsi <= 35:
                    candidates.append({"ticker": ticker, "name": stock["name"], "sector": stock["sector"],
                                       "price": current, "high_52w": high_52w, "drawdown": drawdown,
                                       "rsi": rsi, "score": drawdown + (35 - rsi)})
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Sleeper scan error {ticker}: {e}")

    if not candidates:
        await send_message("🔍 *SLEEPER PICK* — No strong candidates today. Market may be broadly elevated.")
        return

    best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]
    recovery = ((best["high_52w"] - best["price"]) / best["price"]) * 100
    await send_message(
        f"🔍 *SLEEPER PICK — {best['name']}* (${best['ticker']})\n"
        f"─────────────────────────\n"
        f"🏷 {best['sector']}\n"
        f"💲 *${best['price']:,.2f}* — down {best['drawdown']:.1f}% from 52w high\n"
        f"📊 *RSI {best['rsi']}* — {'🔥 Very oversold' if best['rsi'] < 25 else '⚠️ Oversold'}\n"
        f"🎯 Recovery potential: +{recovery:.1f}%\n"
        f"─────────────────────────\n"
        f"{'🟢 Strong setup' if best['drawdown'] >= 40 and best['rsi'] < 30 else '🟡 Worth watching'}\n"
        f"⚡ _Not financial advice_"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# ─── ALERT CHECKERS ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
async def check_price_alerts():
    async with aiohttp.ClientSession() as session:
        for alert in PRICE_ALERTS:
            ticker = alert["ticker"]
            price  = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            if not price: continue
            triggered = (alert["direction"] == "above" and price >= alert["target"]) or \
                        (alert["direction"] == "below" and price <= alert["target"])
            key = f"{ticker}_{alert['target']}_{alert['direction']}"
            last = fired_alerts.get(key)
            if last and (datetime.now() - last).seconds / 3600 < 4: continue
            if triggered:
                fired_alerts[key] = datetime.now()
                sym = "▲" if alert["direction"] == "above" else "▼"
                await send_message(f"🚨 *PRICE ALERT — {ticker}*\n─────────────────────\n{sym} *${price:,.2f}* vs target ${alert['target']:,.2f}\n─────────────────────\n{alert['action']}")

async def check_rsi_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in HOLDINGS:
            if ticker in CRYPTO_MAP: continue
            prices = await get_historical_prices(session, ticker, days=60)
            if not prices or len(prices) < RSI_PERIOD + 1: continue
            rsi = calc_rsi(prices, RSI_PERIOD)
            if not rsi: continue
            for condition, key, emoji, label, advice in [
                (rsi >= RSI_OVERBOUGHT, f"rsi_ob_{ticker}", "🔴", "OVERBOUGHT (≥70)", "Consider taking partial profits or tightening your stop."),
                (rsi <= RSI_OVERSOLD,   f"rsi_os_{ticker}", "🟢", "OVERSOLD (≤30)",   "Could be a buying opportunity — check the news first.")
            ]:
                if condition:
                    last = fired_alerts.get(key)
                    if not last or (datetime.now() - last).seconds > 14400:
                        fired_alerts[key] = datetime.now()
                        await send_message(f"📊 *RSI ALERT — {ticker}*\n─────────────────────\n{emoji} *RSI: {rsi}* — {label}\n📌 *{HOLDINGS[ticker]['name']}*\n─────────────────────\n{advice}")

async def check_ma_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in HOLDINGS:
            if ticker in CRYPTO_MAP: continue
            prices = await get_historical_prices(session, ticker, days=90)
            if not prices or len(prices) < MA_LONG: continue
            cp = prices[-1]; pp = prices[:-1]
            sma20 = calc_sma(prices, MA_SHORT); sma50 = calc_sma(prices, MA_LONG)
            psma20 = calc_sma(pp, MA_SHORT);    psma50 = calc_sma(pp, MA_LONG)
            if not all([sma20, sma50, psma20, psma50]): continue
            gn = sma20 > sma50; gp = psma20 > psma50
            if gn and not gp:
                key = f"ma_golden_{ticker}"
                last = fired_alerts.get(key)
                if not last or (datetime.now() - last).days >= 1:
                    fired_alerts[key] = datetime.now()
                    await send_message(f"📈 *GOLDEN CROSS — {ticker}*\n─────────────────────\n✅ SMA20 crossed ABOVE SMA50\n📌 *{HOLDINGS[ticker]['name']}* @ ${cp:,.2f}\nSMA20: ${sma20:,.2f} · SMA50: ${sma50:,.2f}\n─────────────────────\n🟢 *Bullish signal* — trend turning up.")
            elif not gn and gp:
                key = f"ma_death_{ticker}"
                last = fired_alerts.get(key)
                if not last or (datetime.now() - last).days >= 1:
                    fired_alerts[key] = datetime.now()
                    await send_message(f"📉 *DEATH CROSS — {ticker}*\n─────────────────────\n🔴 SMA20 crossed BELOW SMA50\n📌 *{HOLDINGS[ticker]['name']}* @ ${cp:,.2f}\nSMA20: ${sma20:,.2f} · SMA50: ${sma50:,.2f}\n─────────────────────\n⚠️ *Bearish signal* — consider tightening stops.")

async def check_market_gift():
    global market_gift_fired_today
    today = datetime.now(EST).date()
    if market_gift_fired_today == today: return
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=5d"
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
                data  = await r.json()
                closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    drop = ((closes[-2] - closes[-1]) / closes[-2]) * 100
                    if drop >= 2.0:
                        market_gift_fired_today = today
                        emoji   = "🎁🎁" if drop >= 3.0 else "🎁"
                        verdict = "Significant fear-driven selloff" if drop >= 3.0 else "Minor fear-driven dip"
                        await send_message(f"{emoji} *MARKET GIFT ALERT*\n─────────────────────\n📉 S&P 500 down *{drop:.1f}%* today\nThis looks like macro fear, not fundamental weakness.\n─────────────────────\n👀 Check your watchlist: PANW · GWRE · WYNN · RKLB\n⚡ {verdict} — DYOR before acting")
    except Exception as e:
        logger.error(f"Market gift check error: {e}")

async def check_earnings_countdown():
    today = datetime.now(EST).date()
    for ticker, date_str in EARNINGS_CALENDAR.items():
        try:
            ed = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (ed - today).days
            if days_away in [2, 1]:
                days_str = "tomorrow" if days_away == 1 else "in 2 days"
                await send_message(f"📅 *EARNINGS — {ticker}*\n─────────────────────\nReports {days_str} — *{ed.strftime('%b %d')}*\n⚠️ Be ready for volatility. Check your position size before the print.")
        except: continue

async def check_insider_trading():
    stock_tickers = [t for t in list(HOLDINGS.keys()) + ["PANW", "WYNN"] if t not in CRYPTO_MAP]
    try:
        async with aiohttp.ClientSession() as session:
            for ticker in stock_tickers:
                url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=insiderTransactions"
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10) as r:
                    data = await r.json()
                    try:
                        txns = data["quoteSummary"]["result"][0]["insiderTransactions"]["transactions"]
                        for t in txns[:3]:
                            tid = f"{ticker}_{t.get('startDate',{}).get('raw',0)}_{t.get('filer','')}"
                            if tid in insider_seen: continue
                            tt = t.get("transactionDescription", "")
                            if ("Purchase" in tt or "Acquisition" in tt) and t.get("startDate", {}).get("fmt"):
                                insider_seen.add(tid)
                                await send_message(
                                    f"🏛️ *INSIDER BUY — {ticker}*\n─────────────────────\n"
                                    f"👤 {t.get('filer','')} ({t.get('relation','')})\n"
                                    f"📅 {t.get('startDate',{}).get('fmt','')}\n"
                                    f"📊 {t.get('shares',{}).get('fmt','')} shares · {t.get('value',{}).get('fmt','')}\n"
                                    f"─────────────────────\n💡 Insiders buy for one reason — they think it's going up."
                                )
                    except: pass
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"Insider trading error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# ─── TELEGRAM COMMANDS ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
last_update_id = 0
WATCHLIST = load_watchlist()

async def handle_commands():
    global last_update_id, WATCHLIST
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as r:
                data = await r.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    text = update.get("message", {}).get("text", "").strip()
                    if not text.startswith("/"): continue
                    parts = text.split()
                    cmd   = parts[0].lower()

                    if cmd == "/brief":
                        await send_message("📊 Pulling your brief...")
                        await send_morning_brief_telegram()

                    elif cmd == "/prices":
                        async with aiohttp.ClientSession() as s:
                            lines = ["💲 *LIVE PRICES*", "─" * 24]
                            for ticker, info in HOLDINGS.items():
                                price = await get_crypto_price(s, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(s, ticker)
                                if price: lines.append(f"📌 *{ticker}* — ${price:,.2f}")
                            await send_message("\n".join(lines))

                    elif cmd == "/watchlist":
                        async with aiohttp.ClientSession() as s:
                            lines = ["👀 *WATCHLIST*", "─" * 24]
                            for item in load_watchlist():
                                price = await get_stock_price(s, item["ticker"])
                                if price:
                                    diff = price - item["target"]
                                    status = "🟢 IN ZONE" if price <= item["target"] else f"${diff:+.2f} away"
                                    lines.append(f"📌 *{item['ticker']}* — ${price:,.2f} | Target ${item['target']} | {status}")
                            await send_message("\n".join(lines))

                    elif cmd == "/addwatch":
                        if len(parts) >= 3:
                            try:
                                nt, np = parts[1].upper(), float(parts[2])
                                wl = load_watchlist()
                                if nt in [w["ticker"] for w in wl]:
                                    await send_message(f"⚠️ *{nt}* is already on your watchlist.")
                                else:
                                    wl.append({"ticker": nt, "target": np, "note": ""})
                                    save_watchlist(wl); WATCHLIST = wl
                                    await send_message(f"✅ *{nt}* added to watchlist · Target ${np:,.2f}")
                            except:
                                await send_message("⚠️ Usage: /addwatch TICKER 150.00")
                        else:
                            await send_message("⚠️ Usage: /addwatch TICKER 150.00")

                    elif cmd == "/removewatch":
                        if len(parts) >= 2:
                            rt = parts[1].upper()
                            wl = load_watchlist()
                            nwl = [w for w in wl if w["ticker"] != rt]
                            if len(nwl) == len(wl):
                                await send_message(f"⚠️ *{rt}* not found on watchlist.")
                            else:
                                save_watchlist(nwl); WATCHLIST = nwl
                                await send_message(f"✅ *{rt}* removed from watchlist.")
                        else:
                            await send_message("⚠️ Usage: /removewatch TICKER")

                    elif cmd == "/sleeper":
                        await send_message("🔍 Running sleeper scanner...")
                        async with aiohttp.ClientSession() as s:
                            await send_sleeper_pick(s)

                    elif cmd == "/rsi":
                        async with aiohttp.ClientSession() as s:
                            lines = ["📊 *RSI READINGS*", "─" * 24, "🟢 ≤30 Oversold · 🔴 ≥70 Overbought · ─ Neutral"]
                            for ticker in HOLDINGS:
                                if ticker in CRYPTO_MAP: continue
                                prices = await get_historical_prices(s, ticker, days=60)
                                if prices and len(prices) > 14:
                                    rsi = calc_rsi(prices, 14)
                                    if rsi:
                                        icon = "🟢" if rsi <= 30 else "🔴" if rsi >= 70 else "─"
                                        lines.append(f"{icon} *{ticker}* — RSI {rsi}")
                            await send_message("\n".join(lines))

                    elif cmd == "/help":
                        await send_message(
                            "🤖 *COMMANDS*\n─────────────────────\n"
                            "/brief — Morning brief on demand\n"
                            "/prices — Live prices now\n"
                            "/watchlist — View watchlist vs targets\n"
                            "/addwatch TICKER PRICE — Add to watchlist\n"
                            "/removewatch TICKER — Remove from watchlist\n"
                            "/sleeper — Run sleeper scanner\n"
                            "/rsi — RSI for all holdings\n"
                            "/help — This menu"
                        )
    except Exception as e:
        logger.error(f"Command handler error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
async def main():
    logger.info("Patrick's Portfolio Bot — Phase A starting...")
    await send_message(
        "🤖 *Patrick's Portfolio Bot — Phase A LIVE*\n"
        "─────────────────────\n"
        "📧 *Email Schedule:*\n"
        "  Mon 7:45am — Week Ahead Outlook\n"
        "  Daily 9:30am — Morning Market Outlook\n"
        "  Daily 5:00pm — Evening Market Wrap\n"
        "  Fri 6:00pm — Week in Review\n"
        "─────────────────────\n"
        "📱 *Telegram Alerts:*\n"
        "  Price, RSI, MA crossover alerts\n"
        "  Market Gift Alert · Earnings countdown\n"
        "  Insider trading · Daily sleeper pick\n"
        "─────────────────────\n"
        "💬 /brief /prices /watchlist /addwatch /removewatch /sleeper /rsi /help\n"
        "─────────────────────\n"
        "📊 RKLB · VTI · ETH · GD · AMZN · GWRE · MRSH · SOFI · BTC · AUR · LINK"
    )

    morning_sent_today  = None
    evening_sent_today  = None
    monday_sent_today   = None
    friday_sent_today   = None
    earnings_check_today = None
    last_price_check = last_rsi_check = last_ma_check = None
    last_news_collect = last_insider_check = last_gift_check = None

    while True:
        now   = datetime.now(EST)
        today = now.date()
        wd    = now.weekday()  # 0=Mon, 4=Fri

        # Monday 7:45am — Week Ahead
        if wd == 0 and now.hour == 7 and 45 <= now.minute <= 50 and monday_sent_today != today:
            await send_monday_email(); monday_sent_today = today

        # Daily 9:30am — Morning Outlook (weekdays)
        if wd < 5 and now.hour == 9 and 30 <= now.minute <= 35 and morning_sent_today != today:
            await send_morning_email(); morning_sent_today = today

        # Daily 5:00pm — Evening Wrap (weekdays)
        if wd < 5 and now.hour == 17 and 0 <= now.minute <= 5 and evening_sent_today != today:
            await send_evening_email(); evening_sent_today = today

        # Friday 6:00pm — Week in Review
        if wd == 4 and now.hour == 18 and 0 <= now.minute <= 5 and friday_sent_today != today:
            await send_friday_email(); friday_sent_today = today

        # Earnings countdown 8:30am weekdays
        if wd < 5 and now.hour == 8 and 30 <= now.minute <= 35 and earnings_check_today != today:
            await check_earnings_countdown(); earnings_check_today = today

        # Intraday checks during market hours
        if is_market_open():
            if not last_price_check or (now - last_price_check).seconds >= 300:
                await check_price_alerts(); last_price_check = now
            if not last_rsi_check or (now - last_rsi_check).seconds >= 1800:
                await check_rsi_alerts(); last_rsi_check = now
            if not last_ma_check or (now - last_ma_check).seconds >= 3600:
                await check_ma_alerts(); last_ma_check = now
            if not last_news_collect or (now - last_news_collect).seconds >= 1800:
                await collect_news(); last_news_collect = now
            if not last_insider_check or (now - last_insider_check).seconds >= 14400:
                await check_insider_trading(); last_insider_check = now
            if not last_gift_check or (now - last_gift_check).seconds >= 1800:
                await check_market_gift(); last_gift_check = now

        await handle_commands()
        await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
