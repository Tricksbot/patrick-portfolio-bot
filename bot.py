import os
import asyncio
import logging
import json
from datetime import datetime, time
import pytz
import aiohttp
from telegram import Bot
from telegram.constants import ParseMode
import math

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

EST = pytz.timezone("America/New_York")

# ─── YOUR PORTFOLIO (stocks only) ─────────────────────────────────────────────
HOLDINGS = {
    "RKLB": {"shares": 700,    "avg_cost": 6.73,   "name": "Rocket Lab USA"},
    "VTI":  {"shares": 113.17, "avg_cost": 233.36, "name": "Vanguard Total Market"},
    "ETH":  {"shares": 13.02,  "avg_cost": 2068.00,"name": "Ether"},
    "GD":   {"shares": 64.19,  "avg_cost": 252.17, "name": "General Dynamics"},
    "AMZN": {"shares": 78,     "avg_cost": 144.46, "name": "Amazon"},
    "GWRE": {"shares": 72,     "avg_cost": 157.18, "name": "Guidewire Software"},
    "MRSH": {"shares": 61.3,   "avg_cost": 178.30, "name": "Marsh McLennan"},
    "SOFI": {"shares": 400,    "avg_cost": 18.03,  "name": "SoFi Technologies"},
    "BTC":  {"shares": 0.03029,"avg_cost": 86490,  "name": "Bitcoin"},
    "AUR":  {"shares": 450,    "avg_cost": 6.10,   "name": "Aurora Innovation"},
    "LINK": {"shares": 402.1,  "avg_cost": 15.00,  "name": "Chainlink"},
}

CRYPTO_MAP = {"ETH": "ethereum", "BTC": "bitcoin", "LINK": "chainlink"}

# ─── WATCHLIST (dynamic via /addwatch /removewatch) ───────────────────────────
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

def save_watchlist(watchlist):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f)
    except Exception as e:
        logger.error(f"Watchlist save error: {e}")

WATCHLIST = load_watchlist()

# ─── PRICE ALERTS ─────────────────────────────────────────────────────────────
PRICE_ALERTS = [
    {"ticker": "RKLB", "target": 100.00, "direction": "above", "action": "🔴 TRIM ALERT — RKLB hit $100. Trim 250 shares as planned. Net ~$17,900 after 30% tax. Keep 450 shares running."},
    {"ticker": "GWRE", "target": 158.00, "direction": "below", "action": "🟢 ADD OPPORTUNITY — GWRE at $158. Top up your position. Analyst avg target $266 (+65% upside)."},
    {"ticker": "PANW", "target": 160.00, "direction": "below", "action": "🟢 BUY ZONE — PANW hit $160. Start your position. Analyst avg target $210 (+31% upside)."},
    {"ticker": "WYNN", "target": 90.00,  "direction": "below", "action": "🟢 BUY ZONE — WYNN hit $90. Start a position. Analyst avg target $138 (+53% upside). UAE resort 2027 catalyst."},
]

# ─── RSI / MA SETTINGS ────────────────────────────────────────────────────────
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_PERIOD = 14
MA_SHORT = 20
MA_LONG = 50
MA_FAST = 12
MA_SLOW = 26
MA_SIGNAL = 9

# ─── NEWS TICKERS ─────────────────────────────────────────────────────────────
NEWS_TICKERS = ["RKLB", "GWRE", "SOFI", "PANW", "AMZN", "GD", "BTC", "ETH", "WYNN", "MRSH", "VTI", "AUR", "LINK"]
seen_news = set()
fired_alerts = {}

# ─── TRUSTED SOURCES WHITELIST ────────────────────────────────────────────────
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

def is_trusted_english(title, source="", url=""):
    if not title:
        return False
    non_english_chars = sum(1 for c in title if ord(c) > 127)
    if non_english_chars > len(title) * 0.05:
        return False
    title_lower = title.lower()
    if any(kw in title_lower for kw in NON_ENGLISH_KEYWORDS):
        return False
    source_lower = source.lower()
    url_lower = url.lower()
    return any(s in source_lower or s in url_lower for s in TRUSTED_SOURCES)

# ─── PRICE FETCHING ───────────────────────────────────────────────────────────
async def get_stock_price(session, ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=10) as r:
            data = await r.json()
            result = data["chart"]["result"][0]
            return float(result["meta"]["regularMarketPrice"])
    except Exception as e:
        logger.error(f"Price fetch error {ticker}: {e}")
    return None

async def get_crypto_price(session, coin_id):
    try:
        ticker_map = {"bitcoin": "BTC-USD", "ethereum": "ETH-USD", "chainlink": "LINK-USD"}
        ticker = ticker_map.get(coin_id, f"{coin_id.upper()}-USD")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=10) as r:
            data = await r.json()
            result = data["chart"]["result"][0]
            return float(result["meta"]["regularMarketPrice"])
    except Exception as e:
        logger.error(f"Crypto fetch error {coin_id}: {e}")
    return None

async def get_prev_close(session, ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=10) as r:
            data = await r.json()
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            return float(closes[-2]) if len(closes) >= 2 else None
    except Exception as e:
        logger.error(f"Prev close error {ticker}: {e}")
    return None

async def get_historical_prices(session, ticker, days=60):
    try:
        period = "3mo" if days <= 90 else "1y"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={period}"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=10) as r:
            data = await r.json()
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            return [float(c) for c in closes if c is not None]
    except Exception as e:
        logger.error(f"Historical prices error {ticker}: {e}")
    return None

# ─── INDICATORS ───────────────────────────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        return 100.0
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def calc_sma(prices, period):
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 2)

def calc_macd(prices):
    if len(prices) < MA_SLOW + MA_SIGNAL:
        return None, None, None
    ema_fast_vals = []
    ema_slow_vals = []
    k_fast = 2 / (MA_FAST + 1)
    k_slow = 2 / (MA_SLOW + 1)
    ema_f = sum(prices[:MA_FAST]) / MA_FAST
    ema_s = sum(prices[:MA_SLOW]) / MA_SLOW
    for i, price in enumerate(prices):
        if i >= MA_FAST:
            ema_f = price * k_fast + ema_f * (1 - k_fast)
            ema_fast_vals.append(ema_f)
        if i >= MA_SLOW:
            ema_s = price * k_slow + ema_s * (1 - k_slow)
            ema_slow_vals.append(ema_s)
    min_len = min(len(ema_fast_vals), len(ema_slow_vals))
    macd_line = [ema_fast_vals[-(min_len-i)] - ema_slow_vals[-(min_len-i)] for i in range(min_len)]
    if len(macd_line) < MA_SIGNAL:
        return None, None, None
    k_sig = 2 / (MA_SIGNAL + 1)
    sig = sum(macd_line[:MA_SIGNAL]) / MA_SIGNAL
    for val in macd_line[MA_SIGNAL:]:
        sig = val * k_sig + sig * (1 - k_sig)
    macd_val = macd_line[-1]
    hist = macd_val - sig
    return round(macd_val, 4), round(sig, 4), round(hist, 4)

def interpret_ma_signals(prices, current_price):
    signals = []
    sma20 = calc_sma(prices, MA_SHORT)
    sma50 = calc_sma(prices, MA_LONG)
    macd, macd_sig, macd_hist = calc_macd(prices)
    if sma20 and sma50:
        if sma20 > sma50 and current_price > sma20:
            signals.append("📈 Golden cross — SMA20 above SMA50. *Bullish trend.*")
        elif sma20 < sma50 and current_price < sma20:
            signals.append("📉 Death cross — SMA20 below SMA50. *Bearish trend.*")
        elif current_price < sma20:
            signals.append(f"⚠️ Price below 20-day SMA (${sma20}). Short-term weakness.")
        elif current_price > sma50:
            signals.append(f"✅ Price above 50-day SMA (${sma50}). Uptrend intact.")
    if macd is not None and macd_sig is not None:
        if macd > macd_sig and macd_hist and macd_hist > 0:
            signals.append("📈 MACD bullish — momentum building.")
        elif macd < macd_sig and macd_hist and macd_hist < 0:
            signals.append("📉 MACD bearish — momentum shifting down.")
        else:
            signals.append("➡️ MACD neutral.")
    return signals, sma20, sma50, macd, macd_sig

# ─── NEWS FETCHING ────────────────────────────────────────────────────────────
async def get_news(session, ticker):
    try:
        url = f"https://newsapi.org/v2/everything?q={ticker}&sortBy=publishedAt&pageSize=10&apiKey={NEWS_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            articles = []
            if data.get("articles"):
                for a in data["articles"]:
                    title = a.get("title", "")
                    source = a.get("source", {}).get("name", "")
                    art_url = a.get("url", "")
                    if art_url in seen_news:
                        continue
                    if not is_trusted_english(title, source, art_url):
                        continue
                    seen_news.add(art_url)
                    articles.append({"title": title, "source": source, "url": art_url})
                    if len(articles) >= 2:
                        break
            return articles
    except Exception as e:
        logger.error(f"News fetch error {ticker}: {e}")
    return []

# ─── TELEGRAM SENDER ──────────────────────────────────────────────────────────
async def send_message(text):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)
        logger.info("Message sent successfully")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

# ─── EMAIL SENDER ─────────────────────────────────────────────────────────────
async def send_email(subject, html_body):
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logger.info(f"Email sent: {subject}")
    except Exception as e:
        logger.error(f"Email send error: {e}")

def build_email(title, sections):
    rows = ""
    for section in sections:
        rows += f"""
        <tr>
          <td style="padding:16px 24px;border-bottom:1px solid #f0f0f0;">
            <div style="font-size:11px;font-family:monospace;letter-spacing:0.1em;color:#999;text-transform:uppercase;margin-bottom:8px;">{section['label']}</div>
            <div style="font-size:14px;color:#1a1a1a;line-height:1.8;">{section['content']}</div>
          </td>
        </tr>"""
    return f"""
    <html><body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 16px;">
      <tr><td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <tr><td style="background:#0f0f14;padding:24px;text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#e8c96e;letter-spacing:-0.5px;">Patrick's Portfolio Bot</div>
            <div style="font-size:12px;color:#666;margin-top:4px;">{title}</div>
          </td></tr>
          {rows}
          <tr><td style="padding:16px 24px;background:#fafafa;text-align:center;">
            <div style="font-size:11px;color:#bbb;">Not financial advice · Patrick Portfolio Bot · {datetime.now(EST).strftime('%b %d, %Y')}</div>
          </td></tr>
        </table>
      </td></tr>
    </table>
    </body></html>"""

# ─── MORNING BRIEF ────────────────────────────────────────────────────────────
async def send_morning_brief():
    logger.info("Sending morning brief...")
    async with aiohttp.ClientSession() as session:
        lines = []
        total_value = 0
        lines.append("☀️ *PATRICK'S MORNING BRIEF*")
        lines.append(f"📅 {datetime.now(EST).strftime('%A, %b %d %Y · %I:%M %p EST')}")
        lines.append("─" * 32)
        for ticker, info in HOLDINGS.items():
            if ticker in CRYPTO_MAP:
                price = await get_crypto_price(session, CRYPTO_MAP[ticker])
            else:
                price = await get_stock_price(session, ticker)
                if not price:
                    price = await get_prev_close(session, ticker)
            if price:
                value = price * info["shares"]
                total_value += value
                lines.append(f"📌 *{ticker}* — ${price:,.2f} | ${value:,.0f}")
        lines.append("─" * 32)
        lines.append(f"💼 *Total Invested:* ${total_value:,.0f}")
        lines.append("─" * 32)
        lines.append("⚡ _Alerts: RKLB $100 · GWRE $158 · PANW $160 · WYNN $90_")
        await send_message("\n".join(lines))

        email_html = build_email(
            f"Morning Brief · {datetime.now(EST).strftime('%A, %b %d')}",
            [
                {"label": "Portfolio Prices", "content": "<br>".join(
                    l.replace("*","").replace("📌","") for l in lines if l.startswith("📌")
                )},
                {"label": "Total Invested", "content": next((l.replace("💼 *Total Invested:* ","") for l in lines if "Total Invested" in l), "—")},
                {"label": "Active Alerts", "content": "RKLB trim @ $100 &nbsp;·&nbsp; GWRE add @ $158 &nbsp;·&nbsp; PANW buy @ $160 &nbsp;·&nbsp; WYNN buy @ $90"},
            ]
        )
        await send_email(f"☀️ Morning Brief — {datetime.now(EST).strftime('%a %b %d')}", email_html)
        await asyncio.sleep(3)
        await send_sleeper_pick(session)

# ─── SLEEPER STOCK SCANNER ────────────────────────────────────────────────────
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
    logger.info("Running sleeper stock scanner...")
    candidates = []
    for stock in SLEEPER_WATCHLIST:
        ticker = stock["ticker"]
        try:
            from datetime import timedelta
            from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            to_date = datetime.now().strftime("%Y-%m-%d")
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}?adjusted=true&sort=asc&limit=365&apiKey={POLYGON_API_KEY}"
            async with session.get(url, timeout=10) as r:
                data = await r.json()
                if not data.get("results") or len(data["results"]) < 30:
                    continue
                prices = [float(x["c"]) for x in data["results"]]
                current = prices[-1]
                high_52w = max(prices)
                drawdown = ((high_52w - current) / high_52w) * 100
                rsi = calc_rsi(prices[-30:], 14)
                if drawdown >= 30 and rsi and rsi <= 35:
                    candidates.append({
                        "ticker": ticker, "name": stock["name"], "sector": stock["sector"],
                        "price": current, "high_52w": high_52w, "drawdown": drawdown,
                        "rsi": rsi, "score": drawdown + (35 - rsi)
                    })
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Sleeper scan error {ticker}: {e}")

    if not candidates:
        await send_message("🔍 *SLEEPER PICK — No strong candidates today*\n─────────────────────\nNo stocks meet both criteria today.\nMarket may be broadly elevated.")
        return

    best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]
    recovery_potential = ((best["high_52w"] - best["price"]) / best["price"]) * 100
    msg = (
        f"🔍 *SLEEPER PICK OF THE DAY*\n─────────────────────────\n"
        f"📌 *{best['name']}* (${best['ticker']})\n🏷 Sector: {best['sector']}\n"
        f"─────────────────────────\n"
        f"💲 *Price:* ${best['price']:,.2f}\n"
        f"📉 *Down from 52w high:* {best['drawdown']:.1f}% (was ${best['high_52w']:,.2f})\n"
        f"📊 *RSI:* {best['rsi']} — {'🔥 Very oversold' if best['rsi'] < 25 else '⚠️ Oversold'}\n"
        f"🎯 *Recovery potential:* +{recovery_potential:.1f}%\n"
        f"─────────────────────────\n"
        f"{'🟢 Strong setup' if best['drawdown'] >= 40 and best['rsi'] < 30 else '🟡 Worth watching'} — "
        f"Beaten down {best['drawdown']:.0f}% with oversold RSI.\n"
        f"─────────────────────────\n⚡ _Daily scan · Not financial advice_"
    )
    await send_message(msg)

# ─── PRICE ALERT CHECKER ──────────────────────────────────────────────────────
async def check_price_alerts():
    async with aiohttp.ClientSession() as session:
        for alert in PRICE_ALERTS:
            ticker = alert["ticker"]
            target = alert["target"]
            direction = alert["direction"]
            alert_key = f"{ticker}_{target}_{direction}"
            price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            if not price:
                continue
            triggered = (direction == "above" and price >= target) or (direction == "below" and price <= target)
            last_fired = fired_alerts.get(alert_key)
            if last_fired and (datetime.now() - last_fired).seconds / 3600 < 4:
                continue
            if triggered:
                fired_alerts[alert_key] = datetime.now()
                dir_symbol = "▲" if direction == "above" else "▼"
                await send_message(f"🚨 *PRICE ALERT — {ticker}*\n─────────────────────\n{dir_symbol} *Current price:* ${price:,.2f}\n🎯 *Target:* ${target:,.2f} ({direction})\n─────────────────────\n{alert['action']}")

# ─── RSI ALERT CHECKER ────────────────────────────────────────────────────────
async def check_rsi_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in HOLDINGS:
            if ticker in CRYPTO_MAP:
                continue
            prices = await get_historical_prices(session, ticker, days=60)
            if not prices or len(prices) < RSI_PERIOD + 1:
                continue
            rsi = calc_rsi(prices, RSI_PERIOD)
            if not rsi:
                continue
            for condition, key, emoji, label, advice in [
                (rsi >= RSI_OVERBOUGHT, f"rsi_ob_{ticker}", "🔴", f"OVERBOUGHT (≥70)", "Consider taking partial profits or tightening stop loss."),
                (rsi <= RSI_OVERSOLD,   f"rsi_os_{ticker}", "🟢", f"OVERSOLD (≤30)",   "Potential buying opportunity. Check news before acting.")
            ]:
                if condition:
                    last_fired = fired_alerts.get(key)
                    if not last_fired or (datetime.now() - last_fired).seconds > 14400:
                        fired_alerts[key] = datetime.now()
                        await send_message(f"📊 *RSI ALERT — {ticker}*\n─────────────────────\n{emoji} *RSI: {rsi}* — {label}\n📌 *{HOLDINGS[ticker]['name']}*\n─────────────────────\n{advice}")

# ─── MOVING AVERAGE ALERT CHECKER ─────────────────────────────────────────────
async def check_ma_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in HOLDINGS:
            if ticker in CRYPTO_MAP:
                continue
            prices = await get_historical_prices(session, ticker, days=90)
            if not prices or len(prices) < MA_LONG:
                continue
            current_price = prices[-1]
            prev_prices = prices[:-1]
            _, sma20, sma50, _, _ = interpret_ma_signals(prices, current_price)
            prev_sma20 = calc_sma(prev_prices, MA_SHORT)
            prev_sma50 = calc_sma(prev_prices, MA_LONG)
            if not all([prev_sma20, prev_sma50, sma20, sma50]):
                continue
            golden_now = sma20 > sma50
            golden_prev = prev_sma20 > prev_sma50
            if golden_now and not golden_prev:
                key = f"ma_golden_{ticker}"
                last_fired = fired_alerts.get(key)
                if not last_fired or (datetime.now() - last_fired).days >= 1:
                    fired_alerts[key] = datetime.now()
                    await send_message(f"📈 *GOLDEN CROSS — {ticker}*\n─────────────────────\n✅ *SMA20 just crossed ABOVE SMA50*\n📌 *{HOLDINGS[ticker]['name']}* @ ${current_price:,.2f}\nSMA20: ${sma20:,.2f} · SMA50: ${sma50:,.2f}\n─────────────────────\n🟢 *Bullish signal.* Trend turning up.")
            elif not golden_now and golden_prev:
                key = f"ma_death_{ticker}"
                last_fired = fired_alerts.get(key)
                if not last_fired or (datetime.now() - last_fired).days >= 1:
                    fired_alerts[key] = datetime.now()
                    await send_message(f"📉 *DEATH CROSS — {ticker}*\n─────────────────────\n🔴 *SMA20 just crossed BELOW SMA50*\n📌 *{HOLDINGS[ticker]['name']}* @ ${current_price:,.2f}\nSMA20: ${sma20:,.2f} · SMA50: ${sma50:,.2f}\n─────────────────────\n⚠️ *Bearish signal.* Consider tightening stops.")

# ─── NEWS COLLECTOR ───────────────────────────────────────────────────────────
daily_news_cache = []

async def collect_news():
    async with aiohttp.ClientSession() as session:
        for ticker in NEWS_TICKERS:
            current = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            prev = None if ticker in CRYPTO_MAP else await get_prev_close(session, ticker)
            try:
                articles = await get_news(session, ticker)
                for article in articles:
                    if article["url"] in [n.get("url") for n in daily_news_cache]:
                        continue
                    move_pct = ((current - prev) / prev) * 100 if current and prev else 0
                    daily_news_cache.append({
                        "ticker": ticker, "title": article["title"], "source": article["source"],
                        "url": article["url"], "move_pct": move_pct,
                        "direction": "📈" if move_pct > 0 else "📉", "price": current
                    })
            except Exception as e:
                logger.error(f"News collect error {ticker}: {e}")
            await asyncio.sleep(0.5)

# ─── END OF DAY REPORT ────────────────────────────────────────────────────────
async def send_eod_report():
    logger.info("Sending end of day report...")
    async with aiohttp.ClientSession() as session:

        price_rows = ""
        total_value = 0
        for ticker, info in HOLDINGS.items():
            price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            prev = None if ticker in CRYPTO_MAP else await get_prev_close(session, ticker)
            if price:
                value = price * info["shares"]
                total_value += value
                chg_str, color = ("—", "#999")
                if prev:
                    chg = ((price - prev) / prev) * 100
                    chg_str = f"+{chg:.1f}%" if chg > 0 else f"{chg:.1f}%"
                    color = "#1a7a4a" if chg > 0 else "#b83232"
                cost = info["avg_cost"] * info["shares"]
                total_pl = ((value - cost) / cost) * 100
                pl_color = "#1a7a4a" if total_pl > 0 else "#b83232"
                price_rows += f"""<tr>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-weight:500;">{ticker}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;">{info['name']}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;text-align:right;">${price:,.2f}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;text-align:right;color:{color};font-weight:500;">{chg_str}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;text-align:right;color:{pl_color};">{total_pl:+.1f}%</td>
                </tr>"""

        prices_table = f"""<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">
            <tr style="background:#f8f8f8;">
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Ticker</th>
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Name</th>
                <th style="padding:8px 12px;text-align:right;font-size:11px;color:#999;font-weight:500;">Price</th>
                <th style="padding:8px 12px;text-align:right;font-size:11px;color:#999;font-weight:500;">Day</th>
                <th style="padding:8px 12px;text-align:right;font-size:11px;color:#999;font-weight:500;">Total P&L</th>
            </tr>{price_rows}</table>"""

        # News — max 5 trusted articles
        news_html = ""
        if daily_news_cache:
            seen = set()
            count = 0
            for item in daily_news_cache:
                if count >= 5:
                    break
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                count += 1
                move_badge = ""
                if abs(item["move_pct"]) >= 3:
                    mc = "#1a7a4a" if item["move_pct"] > 0 else "#b83232"
                    move_badge = f'<span style="background:{mc};color:white;font-size:10px;padding:2px 6px;border-radius:3px;margin-left:6px;">{item["direction"]}{abs(item["move_pct"]):.1f}%</span>'
                news_html += f"""<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;">
                    <div style="font-size:12px;font-weight:600;color:#e8a030;margin-bottom:4px;">{item['ticker']}{move_badge}</div>
                    <div style="font-size:13px;color:#1a1a1a;margin-bottom:4px;">{item['title']}</div>
                    <div style="font-size:11px;color:#999;">{item['source']} &nbsp;·&nbsp; <a href="{item['url']}" style="color:#5b9cf6;">Read article</a></div>
                </div>"""
        else:
            news_html = "<div style='color:#999;font-size:13px;'>No significant news today.</div>"

        # Watchlist
        watch_html = ""
        for item in load_watchlist():
            price = await get_stock_price(session, item["ticker"])
            if price:
                diff = price - item["target"]
                sc = "#1a7a4a" if price <= item["target"] else "#666"
                status = "🟢 IN ENTRY ZONE" if price <= item["target"] else f"${abs(diff):.2f} above target"
                watch_html += f"""<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">
                    <span style="font-weight:500;">{item['ticker']}</span><span>${price:,.2f}</span>
                    <span>Target ${item['target']}</span><span style="color:{sc};">{status}</span></div>"""

        goal_pct = min((total_value / 365000) * 100, 100)
        goal_bar_width = int(goal_pct)

        eco_articles = await get_economy_articles()
        eco_html = ""
        if eco_articles:
            for art in eco_articles:
                eco_html += (
                    '<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;">'
                    f'<div style="font-size:13px;color:#1a1a1a;font-weight:500;margin-bottom:4px;">{art["title"]}</div>'
                    f'<div style="font-size:12px;color:#999;margin-bottom:3px;">{art["description"]}</div>'
                    f'<div style="font-size:11px;color:#999;">{art["source"]} &nbsp;·&nbsp; <a href="{art["url"]}" style="color:#5b9cf6;">Read article</a></div>'
                    '</div>'
                )
        else:
            eco_html = '<div style="color:#999;font-size:13px;">No economy articles today.</div>'

        email_html = build_email(
            f"End of Day Report · {datetime.now(EST).strftime('%A, %b %d, %Y')}",
            [
                {"label": "Portfolio Close", "content": prices_table},
                {"label": "Watchlist Status", "content": watch_html},
                {"label": "Today's News (Trusted Sources Only)", "content": news_html},
                {"label": "$365k Goal Progress", "content": f"""
                    <div style="font-size:22px;font-weight:700;color:#e8a030;">{goal_pct:.1f}%</div>
                    <div style="background:#f0f0f0;border-radius:4px;height:10px;margin:10px 0;overflow:hidden;">
                        <div style="background:#e8a030;height:100%;width:{goal_bar_width}%;border-radius:4px;"></div>
                    </div>
                    <div style="font-size:13px;color:#666;">Invested value: ${total_value:,.0f} · Gap to $365k: ${max(365000-total_value,0):,.0f}</div>
                """},
                {"label": "Economy & Macro", "content": eco_html},
            ]
        )

        await send_email(f"📊 EOD Report — {datetime.now(EST).strftime('%a %b %d')}", email_html)
        daily_news_cache.clear()
        logger.info("EOD report sent, news cache cleared")

# ─── MARKET HOURS CHECK ───────────────────────────────────────────────────────
def is_market_open():
    now = datetime.now(EST)
    if now.weekday() >= 5:
        return False
    return time(9, 30) <= now.time() <= time(16, 0)

def is_morning_brief_time():
    now = datetime.now(EST)
    return now.weekday() < 5 and now.hour == 9 and 30 <= now.minute <= 35

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
last_update_id = 0

async def handle_commands():
    global last_update_id, WATCHLIST
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as r:
                data = await r.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "").strip()
                    if not text.startswith("/"):
                        continue
                    parts = text.split()
                    cmd = parts[0].lower()

                    if cmd == "/brief":
                        await send_message("📊 Pulling your brief...")
                        await send_morning_brief()

                    elif cmd == "/prices":
                        async with aiohttp.ClientSession() as s:
                            lines = ["💲 *LIVE PRICES*", "─" * 24]
                            for ticker, info in HOLDINGS.items():
                                price = await get_crypto_price(s, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(s, ticker)
                                if price:
                                    lines.append(f"📌 *{ticker}* — ${price:,.2f}")
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
                                new_ticker = parts[1].upper()
                                new_target = float(parts[2])
                                wl = load_watchlist()
                                if new_ticker in [w["ticker"] for w in wl]:
                                    await send_message(f"⚠️ *{new_ticker}* is already on your watchlist.")
                                else:
                                    wl.append({"ticker": new_ticker, "target": new_target, "note": ""})
                                    save_watchlist(wl)
                                    WATCHLIST = wl
                                    await send_message(f"✅ *{new_ticker}* added to watchlist · Target ${new_target:,.2f}")
                            except:
                                await send_message("⚠️ Usage: /addwatch TICKER 150.00")
                        else:
                            await send_message("⚠️ Usage: /addwatch TICKER 150.00")

                    elif cmd == "/removewatch":
                        if len(parts) >= 2:
                            rem_ticker = parts[1].upper()
                            wl = load_watchlist()
                            new_wl = [w for w in wl if w["ticker"] != rem_ticker]
                            if len(new_wl) == len(wl):
                                await send_message(f"⚠️ *{rem_ticker}* not found on watchlist.")
                            else:
                                save_watchlist(new_wl)
                                WATCHLIST = new_wl
                                await send_message(f"✅ *{rem_ticker}* removed from watchlist.")
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
                                if ticker in CRYPTO_MAP:
                                    continue
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

# ─── FEAR & GREED INDEX ───────────────────────────────────────────────────────
async def get_fear_greed():
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(url, headers=headers, timeout=10) as r:
                data = await r.json()
                score = float(data["fear_and_greed"]["score"])
                return {"score": score, "rating": data["fear_and_greed"]["rating"]}
    except Exception as e:
        logger.error(f"Fear & Greed error: {e}")
        return None

def fear_greed_emoji(score):
    if score <= 25: return "💀"
    elif score <= 45: return "😨"
    elif score <= 55: return "😐"
    elif score <= 75: return "😊"
    else: return "🤑"

def fear_greed_color(score):
    if score <= 25: return "#7a0000"
    elif score <= 45: return "#b83232"
    elif score <= 55: return "#a06a10"
    elif score <= 75: return "#1a7a4a"
    else: return "#0d5c38"

# ─── TREASURY YIELD MONITOR ───────────────────────────────────────────────────
TREASURY_ALERT_THRESHOLD = 4.5

async def check_treasury_yields():
    try:
        async with aiohttp.ClientSession() as session:
            tickers = {"2yr": "^IRX", "5yr": "^FVX", "10yr": "^TNX", "30yr": "^TYX"}
            yields = {}
            for name, ticker in tickers.items():
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
                headers = {"User-Agent": "Mozilla/5.0"}
                async with session.get(url, headers=headers, timeout=10) as r:
                    data = await r.json()
                    result = data["chart"]["result"][0]
                    closes = [c for c in result["indicators"]["quote"][0]["close"] if c]
                    if closes:
                        yields[name] = round(closes[-1], 3)
                await asyncio.sleep(0.3)
            alerts = [f"{n} at {r:.2f}% — worth considering locking in" for n, r in yields.items() if r >= TREASURY_ALERT_THRESHOLD]
            return yields, alerts
    except Exception as e:
        logger.error(f"Treasury yield error: {e}")
        return {}, []

# ─── MARKET GIFT ALERT ────────────────────────────────────────────────────────
market_gift_fired_today = None

async def check_market_gift():
    global market_gift_fired_today
    today = datetime.now(EST).date()
    if market_gift_fired_today == today:
        return
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=5d"
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(url, headers=headers, timeout=10) as r:
                data = await r.json()
                closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    drop = ((closes[-2] - closes[-1]) / closes[-2]) * 100
                    if drop >= 2.0:
                        market_gift_fired_today = today
                        emoji = "🎁🎁" if drop >= 3.0 else "🎁"
                        verdict = "Significant fear-driven selloff" if drop >= 3.0 else "Minor fear-driven dip"
                        await send_message(f"{emoji} *MARKET GIFT ALERT*\n─────────────────────\n📉 S&P 500 down *{drop:.1f}%* today\n─────────────────────\nThis looks like *macro fear*, not fundamental weakness.\n─────────────────────\n👀 *Check your watchlist:* PANW · GWRE · WYNN · RKLB\n─────────────────────\n⚡ {verdict} — DYOR before acting")
    except Exception as e:
        logger.error(f"Market gift check error: {e}")

# ─── EARNINGS COUNTDOWN ───────────────────────────────────────────────────────
EARNINGS_CALENDAR = {
    "SOFI": "2026-05-04", "GWRE": "2026-05-21", "PANW": "2026-05-26",
    "RKLB": "2026-05-08", "AMZN": "2026-05-01", "GD":   "2026-04-23",
    "MRSH": "2026-04-17", "AUR":  "2026-05-08",
}

async def check_earnings_countdown():
    today = datetime.now(EST).date()
    for ticker, date_str in EARNINGS_CALENDAR.items():
        try:
            earnings_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (earnings_date - today).days
            if days_away in [2, 1]:
                days_str = "tomorrow" if days_away == 1 else "in 2 days"
                await send_message(f"📅 *EARNINGS ALERT — {ticker}*\n─────────────────────\nReports {days_str} — *{earnings_date.strftime('%b %d')}*\n─────────────────────\n⚠️ Be prepared for volatility.\nConsider your position size before the print.")
        except:
            continue

# ─── INSIDER TRADING MONITOR ─────────────────────────────────────────────────
insider_seen = set()

async def check_insider_trading():
    stock_tickers = [t for t in list(HOLDINGS.keys()) + ["PANW", "WYNN"] if t not in CRYPTO_MAP]
    try:
        async with aiohttp.ClientSession() as session:
            for ticker in stock_tickers:
                url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=insiderTransactions"
                headers = {"User-Agent": "Mozilla/5.0"}
                async with session.get(url, headers=headers, timeout=10) as r:
                    data = await r.json()
                    try:
                        transactions = data["quoteSummary"]["result"][0]["insiderTransactions"]["transactions"]
                        for t in transactions[:3]:
                            trans_id = f"{ticker}_{t.get('startDate', {}).get('raw', 0)}_{t.get('filer', '')}"
                            if trans_id in insider_seen:
                                continue
                            trans_type = t.get("transactionDescription", "")
                            is_buy = "Purchase" in trans_type or "Acquisition" in trans_type
                            trans_date = t.get("startDate", {}).get("fmt", "")
                            if is_buy and trans_date:
                                insider_seen.add(trans_id)
                                await send_message(
                                    f"🏛️ *INSIDER BUY — {ticker}*\n─────────────────────\n"
                                    f"👤 {t.get('filer', '')} ({t.get('relation', '')})\n"
                                    f"📅 {trans_date}\n"
                                    f"📊 {t.get('shares', {}).get('fmt', '')} shares · {t.get('value', {}).get('fmt', '')}\n"
                                    f"─────────────────────\n💡 Insiders buy for one reason — they think the stock is going up."
                                )
                    except:
                        pass
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"Insider trading error: {e}")

# ─── ECONOMY ARTICLES ─────────────────────────────────────────────────────────
async def get_economy_articles():
    try:
        async with aiohttp.ClientSession() as session:
            queries = ["economy federal reserve", "stock market outlook"]
            articles = []
            for query in queries:
                url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize=10&language=en&apiKey={NEWS_API_KEY}"
                async with session.get(url, timeout=10) as r:
                    data = await r.json()
                    for a in data.get("articles", []):
                        title = a.get("title", "")
                        source = a.get("source", {}).get("name", "")
                        art_url = a.get("url", "")
                        if not is_trusted_english(title, source, art_url):
                            continue
                        articles.append({
                            "title": title, "source": source, "url": art_url,
                            "description": (a.get("description", "") or "")[:120]
                        })
                        if len(articles) >= 2:
                            break
                if len(articles) >= 2:
                    break
                await asyncio.sleep(0.5)
            return articles[:2]
    except Exception as e:
        logger.error(f"Economy articles error: {e}")
        return []

# ─── WEEKLY FRIDAY REPORT ─────────────────────────────────────────────────────
async def send_weekly_report():
    logger.info("Sending weekly Friday report...")
    async with aiohttp.ClientSession() as session:
        total_value = 0
        best = {"ticker": "", "pct": -999}
        worst = {"ticker": "", "pct": 999}
        for ticker, info in HOLDINGS.items():
            price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            if price:
                value = price * info["shares"]
                total_value += value
                pl_pct = ((value - info["avg_cost"] * info["shares"]) / (info["avg_cost"] * info["shares"])) * 100
                if pl_pct > best["pct"]:
                    best = {"ticker": ticker, "pct": pl_pct, "price": price}
                if pl_pct < worst["pct"]:
                    worst = {"ticker": ticker, "pct": pl_pct, "price": price}

        goal_pct = (total_value / 365000) * 100
        lines = [
            "📊 *WEEKLY REPORT*", f"📅 {datetime.now(EST).strftime('%A, %b %d')}", "─" * 28,
            f"💼 *Invested Value:* ${total_value:,.0f}", f"🎯 *$365k Goal:* {goal_pct:.1f}%", "─" * 28,
        ]
        if best["ticker"]:
            lines.append(f"🏆 *Best:* {best['ticker']} @ ${best['price']:,.2f} ({best['pct']:+.1f}%)")
        if worst["ticker"]:
            lines.append(f"📉 *Weakest:* {worst['ticker']} @ ${worst['price']:,.2f} ({worst['pct']:+.1f}%)")
        lines += ["─" * 28, "⚡ _Have a great weekend Patrick_"]
        await send_message("\n".join(lines))

# ─── MONDAY GOAL CHECK ────────────────────────────────────────────────────────
async def send_monday_goal_check():
    async with aiohttp.ClientSession() as session:
        total_value = 0
        for ticker, info in HOLDINGS.items():
            price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            if price:
                total_value += price * info["shares"]
        gap = 365000 - total_value
        months_left = max(1, 12 - datetime.now(EST).month + 1)
        goal_pct = (total_value / 365000) * 100
        await send_message(
            f"🎯 *MONDAY GOAL CHECK*\n─────────────────────\n"
            f"💼 Current: ${total_value:,.0f}\n🏁 Target: $365,000\n📊 Progress: {goal_pct:.1f}%\n"
            f"─────────────────────\n"
            f"{'✅ On pace' if gap <= 0 else f'📍 Gap: ${gap:,.0f}'}\n"
            f"{'🎉 Goal reached!' if gap <= 0 else f'Need ~${gap/months_left:,.0f}/mo to close gap'}\n"
            f"─────────────────────\n⚡ _Make it a great week_"
        )

# ─── PRE-MARKET BRIEFING ──────────────────────────────────────────────────────
async def send_premarket_briefing():
    logger.info("Sending pre-market briefing...")
    async with aiohttp.ClientSession() as session:

        async def yf(ticker):
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
                headers = {"User-Agent": "Mozilla/5.0"}
                async with session.get(url, headers=headers, timeout=10) as r:
                    data = await r.json()
                    result = data["chart"]["result"][0]
                    closes = [c for c in result["indicators"]["quote"][0]["close"] if c]
                    current = float(result["meta"].get("regularMarketPrice", closes[-1]))
                    prev = closes[-2] if len(closes) >= 2 else current
                    return {"price": current, "chg": ((current - prev) / prev) * 100, "high_30d": max(closes), "closes": closes}
            except Exception as e:
                logger.error(f"Pre-market fetch error {ticker}: {e}")
                return None

        sp500   = await yf("^GSPC")
        nasdaq  = await yf("^IXIC")
        dow     = await yf("^DJI")
        vix_d   = await yf("^VIX")
        treasury= await yf("^TNX")
        dxy     = await yf("DX-Y.NYB")
        futures = await yf("ES=F")
        await asyncio.sleep(1)

        score = 0
        flags = []

        if sp500 and len(sp500["closes"]) >= 20:
            sma20 = sum(sp500["closes"][-20:]) / 20
            if sp500["price"] > sma20:
                score += 2; flags.append("S&P above 20-day SMA ✅")
            else:
                score -= 2; flags.append("S&P below 20-day SMA ⚠️")
            drawdown = ((sp500["high_30d"] - sp500["price"]) / sp500["high_30d"]) * 100
            if drawdown > 10:
                score -= 2; flags.append(f"Down {drawdown:.1f}% from 30-day high ⚠️")
            elif drawdown < 3:
                score += 1; flags.append(f"Near 30-day high ({drawdown:.1f}% below) ✅")

        if vix_d:
            v = vix_d["price"]
            if v < 15:   score += 2; flags.append(f"VIX {v:.1f} — Very low fear ✅")
            elif v < 20: score += 1; flags.append(f"VIX {v:.1f} — Calm ✅")
            elif v < 25: score -= 1; flags.append(f"VIX {v:.1f} — Elevated ⚠️")
            elif v < 30: score -= 2; flags.append(f"VIX {v:.1f} — High fear 🔴")
            else:        score -= 3; flags.append(f"VIX {v:.1f} — Extreme fear 🔴")

        if futures:
            fc = futures["chg"]
            if fc > 0.5:   score += 1; flags.append(f"Futures up {fc:.2f}% ✅")
            elif fc < -0.5: score -= 1; flags.append(f"Futures down {fc:.2f}% ⚠️")

        if treasury:
            ty = treasury["price"]
            if ty > 4.5:  score -= 1; flags.append(f"10yr yield {ty:.2f}% — Restrictive ⚠️")
            elif ty < 4.0: score += 1; flags.append(f"10yr yield {ty:.2f}% — Supportive ✅")

        if score >= 4:    cond, c_color, c_bg, c_emoji = "BULL",    "#1a7a4a", "#e8f5ee", "🟢"; rec = "Risk-on environment. Strong momentum. Good conditions for new entries on quality names. PANW and GWRE setups look favorable. Watch RKLB toward $100."
        elif score >= 1:  cond, c_color, c_bg, c_emoji = "NEUTRAL", "#a06a10", "#fef6e4", "🟡"; rec = "Mixed signals. Proceed selectively. Focus on high-conviction names only. Keep powder dry and wait for clearer setups before deploying capital."
        elif score >= -2: cond, c_color, c_bg, c_emoji = "CAUTION", "#b83232", "#fceaea", "🔴"; rec = "Risk-off conditions. Hold existing positions but pause new entries. Cash allocation is a strength right now. Watch VIX for stabilization before acting."
        else:             cond, c_color, c_bg, c_emoji = "BEAR",    "#7a0000", "#ffe8e8", "💀"; rec = "Bear market conditions. Protect capital first. Consider trimming speculative positions. Cash is a position — hold it and wait for the dust to settle."

        def idx_row(name, data, invert=False):
            if not data:
                return f'<tr><td colspan="3" style="padding:8px 12px;border-bottom:1px solid #f5f5f5;color:#999;">{name} — Unavailable</td></tr>'
            chg = data["chg"]
            color = ("#b83232" if chg >= 0 else "#1a7a4a") if invert else ("#1a7a4a" if chg >= 0 else "#b83232")
            arrow = "▲" if chg >= 0 else "▼"
            return (f'<tr><td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-weight:500;font-size:13px;">{name}</td>'
                    f'<td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-size:13px;">{data["price"]:,.2f}</td>'
                    f'<td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-size:13px;font-weight:500;color:{color};">{arrow} {abs(chg):.2f}%</td></tr>')

        index_table = (
            '<table width="100%" cellpadding="0" cellspacing="0">'
            '<tr style="background:#f8f8f8;"><th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Index</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Level</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Change</th></tr>' +
            idx_row("S&P 500", sp500) + idx_row("Nasdaq", nasdaq) + idx_row("Dow Jones", dow) +
            idx_row("S&P 500 Futures", futures) + idx_row("VIX — Fear Index", vix_d, True) +
            idx_row("10-yr Treasury", treasury, True) + idx_row("Dollar Index (DXY)", dxy, True) +
            '</table>'
        )

        flags_html = "".join(f'<div style="padding:5px 0;border-bottom:1px solid #f5f5f5;font-size:13px;color:#444;">{f}</div>' for f in flags)
        score_sign = f"+{score}" if score > 0 else str(score)
        date_str = datetime.now(EST).strftime("%A, %B %d, %Y")
        date_short = datetime.now(EST).strftime("%a %b %d")

        email_html = (
            '<html><body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">'
            '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 16px;"><tr><td align="center">'
            '<table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
            '<tr><td style="background:#0f0f14;padding:24px 28px;">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#666;text-transform:uppercase;margin-bottom:6px;">Pre-Market Intelligence</div>'
            '<div style="font-size:24px;font-weight:700;color:#e8c96e;letter-spacing:-0.5px;">Patrick Portfolio Bot</div>'
            f'<div style="font-size:13px;color:#888;margin-top:4px;">{date_str} · 8:00am EST</div></td></tr>'
            f'<tr><td style="background:{c_bg};padding:20px 28px;border-bottom:3px solid {c_color};">'
            f'<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:{c_color};text-transform:uppercase;margin-bottom:6px;">Market Condition</div>'
            f'<div style="font-size:32px;font-weight:800;color:{c_color};letter-spacing:-1px;">{c_emoji} {cond}</div>'
            f'<div style="font-size:13px;color:{c_color};margin-top:4px;opacity:0.8;">Score: {score_sign} · {len(flags)} signals</div></td></tr>'
            '<tr><td style="padding:20px 28px 0;"><div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Index Snapshot</div>'
            + index_table + '</td></tr>'
            '<tr><td style="padding:20px 28px 0;"><div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Signal Breakdown</div>'
            + flags_html + '</td></tr>'
            '<tr><td style="padding:20px 28px;"><div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Recommendation</div>'
            f'<div style="background:{c_bg};border-left:4px solid {c_color};border-radius:0 8px 8px 0;padding:16px 18px;font-size:14px;color:#1a1a1a;line-height:1.7;">{rec}</div></td></tr>'
            '<tr><td style="padding:0 28px 20px;"><div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Your Active Targets</div><div>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;margin-right:6px;display:inline-block;margin-bottom:6px;">RKLB $100 TRIM</span>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;margin-right:6px;display:inline-block;margin-bottom:6px;">GWRE $158 ADD</span>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;margin-right:6px;display:inline-block;margin-bottom:6px;">PANW $160 BUY</span>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;display:inline-block;margin-bottom:6px;">WYNN $90 BUY</span>'
            '</div></td></tr>'
            f'<tr><td style="padding:16px 28px;background:#fafafa;border-top:1px solid #f0f0f0;text-align:center;">'
            f'<div style="font-size:11px;color:#bbb;font-family:monospace;">Not financial advice · Patrick Portfolio Bot · {date_short}</div>'
            '</td></tr></table></td></tr></table></body></html>'
        )

        fg = await get_fear_greed()
        fg_html = ""
        if fg:
            fg_color = fear_greed_color(fg["score"])
            fg_html = (
                '<tr><td style="padding:20px 28px 0;"><div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Fear & Greed Index</div>'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:16px;display:flex;align-items:center;gap:16px;">'
                f'<div style="font-size:36px;font-weight:800;color:{fg_color};">{fear_greed_emoji(fg["score"])} {int(fg["score"])}</div>'
                f'<div><div style="font-size:14px;font-weight:600;color:{fg_color};">{fg["rating"].title()}</div>'
                '<div style="font-size:12px;color:#999;margin-top:2px;">0 = Extreme Fear · 100 = Extreme Greed</div></div></div></td></tr>'
            )

        yields, t_alerts = await check_treasury_yields()
        treasury_html = ""
        if yields:
            yield_rows = "".join(
                f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">'
                f'<span style="font-weight:500;">{k.upper()} Treasury</span>'
                f'<span style="color:{"#b83232" if v >= TREASURY_ALERT_THRESHOLD else "#333"};font-weight:{"700" if v >= TREASURY_ALERT_THRESHOLD else "400"};">'
                f'{v}%{" ← Consider buying" if v >= TREASURY_ALERT_THRESHOLD else ""}</span></div>'
                for k, v in yields.items()
            )
            treasury_html = (
                '<tr><td style="padding:20px 28px 0;"><div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Treasury Yields</div>'
                + yield_rows +
                (''.join(f'<div style="margin-top:8px;background:#e8f5ee;border-left:3px solid #1a7a4a;padding:10px 12px;font-size:12px;color:#1a7a4a;border-radius:0 6px 6px 0;">💡 {a}</div>' for a in t_alerts) if t_alerts else "")
                + '</td></tr>'
            )

        email_html = email_html.replace('<tr><td style="padding:0 28px 20px;">', fg_html + treasury_html + '<tr><td style="padding:0 28px 20px;">', 1)
        await send_email(f"{c_emoji} Pre-Market Brief — {cond} · {date_short}", email_html)
        logger.info(f"Pre-market brief sent — condition: {cond} score: {score}")

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
async def main():
    logger.info("Patrick's Portfolio Bot starting...")
    await send_message(
        "🤖 *Patrick's Portfolio Bot is LIVE*\n"
        "─────────────────────\n"
        "✅ Pre-market briefing: 8:00am EST (email)\n"
        "✅ Morning briefs: 9:30am EST (Telegram + email)\n"
        "✅ Price alerts: RKLB · GWRE · PANW · WYNN\n"
        "✅ RSI + MA crossover alerts: Active\n"
        "✅ News: Trusted sources only · Max 5 articles\n"
        "✅ Fear & Greed · Treasury yields · Market Gift Alert\n"
        "✅ Earnings countdown · Insider trading monitor\n"
        "✅ Weekly Friday report · Monday goal check\n"
        "✅ Daily sleeper pick · Dynamic watchlist\n"
        "─────────────────────\n"
        "💬 /brief /prices /watchlist /addwatch /removewatch /sleeper /rsi /help\n"
        "─────────────────────\n"
        "📊 RKLB · VTI · ETH · GD · AMZN · GWRE · MRSH · SOFI · BTC · AUR · LINK"
    )

    premarket_sent_today = morning_brief_sent_today = eod_sent_today = None
    weekly_report_sent = monday_check_sent = None
    last_insider_check = last_earnings_check = last_gift_check = None
    last_price_check = last_rsi_check = last_ma_check = last_news_collect = None

    while True:
        now = datetime.now(EST)
        today = now.date()

        if now.weekday() < 5 and now.hour == 8 and 0 <= now.minute <= 5 and premarket_sent_today != today:
            await send_premarket_briefing(); premarket_sent_today = today

        if is_morning_brief_time() and morning_brief_sent_today != today:
            await send_morning_brief(); morning_brief_sent_today = today

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

        if now.weekday() < 5 and now.hour == 16 and 30 <= now.minute <= 35 and eod_sent_today != today:
            await send_eod_report(); eod_sent_today = today

        if now.weekday() == 4 and now.hour == 16 and 0 <= now.minute <= 5 and weekly_report_sent != today:
            await send_weekly_report(); weekly_report_sent = today

        if now.weekday() == 0 and now.hour == 9 and 0 <= now.minute <= 5 and monday_check_sent != today:
            await send_monday_goal_check(); monday_check_sent = today

        if now.weekday() < 5 and now.hour == 8 and 30 <= now.minute <= 35 and last_earnings_check != today:
            await check_earnings_countdown(); last_earnings_check = today

        await handle_commands()
        await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
