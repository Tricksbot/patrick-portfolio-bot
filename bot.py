import os
import asyncio
import logging
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
EMAIL_FROM = os.environ.get("EMAIL_FROM")      # your Gmail address
EMAIL_TO = os.environ.get("EMAIL_TO")          # where to send reports
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")  # Gmail app password

EST = pytz.timezone("America/New_York")

# ─── YOUR PORTFOLIO ────────────────────────────────────────────────────────────
HOLDINGS = {
    "RKLB": {"shares": 700,   "avg_cost": 6.73,   "name": "Rocket Lab USA"},
    "VTI":  {"shares": 112.17, "avg_cost": 233.36, "name": "Vanguard Total Market"},
    "ETH":  {"shares": 13.01,  "avg_cost": 2068.41,"name": "Ether"},
    "GD":   {"shares": 64.19,  "avg_cost": 252.17, "name": "General Dynamics"},
    "AMZN": {"shares": 78,     "avg_cost": 144.46, "name": "Amazon"},
    "GWRE": {"shares": 67,     "avg_cost": 160.57, "name": "Guidewire Software"},
    "MRSH": {"shares": 61.3,   "avg_cost": 178.30, "name": "Marsh McLennan"},
    "SOFI": {"shares": 300,    "avg_cost": 18.39,  "name": "SoFi Technologies"},
    "BTC":  {"shares": 0.03029,"avg_cost": 86490,  "name": "Bitcoin"},
}

CRYPTO_MAP = {"ETH": "ethereum", "BTC": "bitcoin"}

# ─── PRICE ALERTS ─────────────────────────────────────────────────────────────
PRICE_ALERTS = [
    {"ticker": "RKLB", "target": 100.00, "direction": "above", "action": "🔴 TRIM ALERT — RKLB hit $100. Trim 250 shares as planned. Net ~$17,900 after 30% tax. Keep 450 shares running."},
    {"ticker": "GWRE", "target": 158.00, "direction": "below", "action": "🟢 ADD OPPORTUNITY — GWRE at $158. Top up your position. Analyst avg target $266 (+65% upside)."},
    {"ticker": "PANW", "target": 160.00, "direction": "below", "action": "🟢 BUY ZONE — PANW hit $160. Start your position. Analyst avg target $210 (+31% upside)."},
    {"ticker": "WYNN", "target": 90.00,  "direction": "below", "action": "🟢 BUY ZONE — WYNN hit $90. Start a position. Analyst avg target $138 (+53% upside). UAE resort 2027 catalyst."},
]

# ─── RSI SETTINGS ─────────────────────────────────────────────────────────────
RSI_OVERSOLD = 30    # BUY signal
RSI_OVERBOUGHT = 70  # SELL signal
RSI_PERIOD = 14

# ─── MOVING AVERAGE SETTINGS ──────────────────────────────────────────────────
MA_SHORT = 20   # 20-day SMA
MA_LONG = 50    # 50-day SMA
MA_FAST = 12    # EMA for MACD
MA_SLOW = 26    # EMA for MACD
MA_SIGNAL = 9   # MACD signal line

# ─── NEWS TICKERS — all owned stocks + watchlist (AUR news only) ──────────────
NEWS_TICKERS = ["RKLB", "GWRE", "SOFI", "PANW", "AMZN", "GD", "BTC", "ETH", "WYNN", "EE", "MRSH", "VTI", "AUR"]
seen_news = set()
fired_alerts = {}

# ─── LANGUAGE FILTER HELPERS ──────────────────────────────────────────────────
NON_ENGLISH_SOURCES = [
    "larazon", "republica.com", "lanacion", "aristeguinoticias",
    "criptonoticias", "stern.de", "spiegel", "lemonde", "elpais",
    "lavanguardia", "clarin", "infobae", "telam", "univision",
    "telemundo", "expansion.mx", "milenio", "excelsior"
]

NON_ENGLISH_KEYWORDS = [
    " de ", " la ", " el ", " en ", " es ", " que ", " del ",
    " los ", " las ", " por ", " con ", " para ", " una ", " ein ",
    " der ", " die ", " das ", " und ", " von ", " le ", " les ",
    " des ", " sur ", " est ", " par "
]

def is_non_english(title, source="", url=""):
    if not title:
        return True
    non_english_chars = sum(1 for c in title if ord(c) > 127)
    if non_english_chars > len(title) * 0.05:
        return True
    source_lower = source.lower()
    url_lower = url.lower()
    if any(s in source_lower or s in url_lower for s in NON_ENGLISH_SOURCES):
        return True
    title_lower = title.lower()
    if any(kw in title_lower for kw in NON_ENGLISH_KEYWORDS):
        return True
    return False

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
        ticker_map = {"bitcoin": "BTC-USD", "ethereum": "ETH-USD"}
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

def calc_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 4)

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
        url = f"https://newsapi.org/v2/everything?q={ticker}&sortBy=publishedAt&pageSize=3&apiKey={NEWS_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            articles = []
            if data.get("articles"):
                for a in data["articles"][:3]:
                    article_id = a.get("url", "")
                    if article_id not in seen_news:
                        seen_news.add(article_id)
                        articles.append({
                            "title": a.get("title", ""),
                            "source": a.get("source", {}).get("name", ""),
                            "url": a.get("url", "")
                        })
            return articles
    except Exception as e:
        logger.error(f"News fetch error {ticker}: {e}")
    return []

# ─── TELEGRAM SENDER ──────────────────────────────────────────────────────────
async def send_message(text):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )
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
    {"ticker": "EE",    "name": "Excelerate Energy",    "sector": "LNG Infrastructure"},
    {"ticker": "CRWD",  "name": "CrowdStrike",          "sector": "Cybersecurity"},
    {"ticker": "TTD",   "name": "The Trade Desk",       "sector": "AdTech"},
    {"ticker": "SOFI",  "name": "SoFi Technologies",    "sector": "Fintech"},
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
                low_52w = min(prices)
                drawdown = ((high_52w - current) / high_52w) * 100
                rsi = calc_rsi(prices[-30:], 14)
                if drawdown >= 30 and rsi and rsi <= 35:
                    candidates.append({
                        "ticker": ticker,
                        "name": stock["name"],
                        "sector": stock["sector"],
                        "price": current,
                        "high_52w": high_52w,
                        "low_52w": low_52w,
                        "drawdown": drawdown,
                        "rsi": rsi,
                        "score": drawdown + (35 - rsi)
                    })
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Sleeper scan error {ticker}: {e}")
            continue

    if not candidates:
        await send_message(
            "🔍 *SLEEPER PICK — No strong candidates today*\n"
            "─────────────────────\n"
            "No stocks meet both criteria today.\n"
            "Market may be broadly elevated."
        )
        return

    best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]
    recovery_potential = ((best["high_52w"] - best["price"]) / best["price"]) * 100

    msg = (
        f"🔍 *SLEEPER PICK OF THE DAY*\n"
        f"─────────────────────────\n"
        f"📌 *{best['name']}* (${best['ticker']})\n"
        f"🏷 Sector: {best['sector']}\n"
        f"─────────────────────────\n"
        f"💲 *Price:* ${best['price']:,.2f}\n"
        f"📉 *Down from 52w high:* {best['drawdown']:.1f}% (was ${best['high_52w']:,.2f})\n"
        f"📊 *RSI:* {best['rsi']} — {'🔥 Very oversold' if best['rsi'] < 25 else '⚠️ Oversold'}\n"
        f"🎯 *Recovery potential:* +{recovery_potential:.1f}%\n"
        f"─────────────────────────\n"
        f"{'🟢 Strong setup' if best['drawdown'] >= 40 and best['rsi'] < 30 else '🟡 Worth watching'} — "
        f"Beaten down {best['drawdown']:.0f}% with oversold RSI.\n"
        f"Do your own research before acting.\n"
        f"─────────────────────────\n"
        f"⚡ _Daily scan · Not financial advice_"
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

            if ticker in CRYPTO_MAP:
                price = await get_crypto_price(session, CRYPTO_MAP[ticker])
            else:
                price = await get_stock_price(session, ticker)

            if not price:
                continue

            triggered = (
                (direction == "above" and price >= target) or
                (direction == "below" and price <= target)
            )

            last_fired = fired_alerts.get(alert_key)
            cooldown_hours = 4
            if last_fired:
                hours_since = (datetime.now() - last_fired).seconds / 3600
                if hours_since < cooldown_hours:
                    continue

            if triggered:
                fired_alerts[alert_key] = datetime.now()
                dir_symbol = "▲" if direction == "above" else "▼"
                msg = (
                    f"🚨 *PRICE ALERT — {ticker}*\n"
                    f"─────────────────────\n"
                    f"{dir_symbol} *Current price:* ${price:,.2f}\n"
                    f"🎯 *Target:* ${target:,.2f} ({direction})\n"
                    f"─────────────────────\n"
                    f"{alert['action']}"
                )
                await send_message(msg)
                logger.info(f"Price alert fired: {ticker} {direction} {target}")

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

            alert_key_ob = f"rsi_ob_{ticker}"
            alert_key_os = f"rsi_os_{ticker}"

            if rsi >= RSI_OVERBOUGHT:
                last_fired = fired_alerts.get(alert_key_ob)
                if not last_fired or (datetime.now() - last_fired).seconds > 14400:
                    fired_alerts[alert_key_ob] = datetime.now()
                    info = HOLDINGS[ticker]
                    msg = (
                        f"📊 *RSI ALERT — {ticker}*\n"
                        f"─────────────────────\n"
                        f"🔴 *RSI: {rsi}* — OVERBOUGHT (≥70)\n"
                        f"📌 *{info['name']}*\n"
                        f"─────────────────────\n"
                        f"⚠️ Stock may be overextended.\n"
                        f"Consider taking partial profits or\n"
                        f"tightening stop loss."
                    )
                    await send_message(msg)

            elif rsi <= RSI_OVERSOLD:
                last_fired = fired_alerts.get(alert_key_os)
                if not last_fired or (datetime.now() - last_fired).seconds > 14400:
                    fired_alerts[alert_key_os] = datetime.now()
                    info = HOLDINGS[ticker]
                    msg = (
                        f"📊 *RSI ALERT — {ticker}*\n"
                        f"─────────────────────\n"
                        f"🟢 *RSI: {rsi}* — OVERSOLD (≤30)\n"
                        f"📌 *{info['name']}*\n"
                        f"─────────────────────\n"
                        f"💡 Potential buying opportunity.\n"
                        f"Stock may be undervalued short-term.\n"
                        f"Check news before acting."
                    )
                    await send_message(msg)

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

            signals, sma20, sma50, macd, macd_sig = interpret_ma_signals(prices, current_price)
            prev_sma20 = calc_sma(prev_prices, MA_SHORT)
            prev_sma50 = calc_sma(prev_prices, MA_LONG)

            if not prev_sma20 or not prev_sma50 or not sma20 or not sma50:
                continue

            alert_key_golden = f"ma_golden_{ticker}"
            alert_key_death = f"ma_death_{ticker}"

            golden_cross_now = sma20 > sma50
            golden_cross_prev = prev_sma20 > prev_sma50

            if golden_cross_now and not golden_cross_prev:
                last_fired = fired_alerts.get(alert_key_golden)
                if not last_fired or (datetime.now() - last_fired).days >= 1:
                    fired_alerts[alert_key_golden] = datetime.now()
                    info = HOLDINGS[ticker]
                    msg = (
                        f"📈 *GOLDEN CROSS — {ticker}*\n"
                        f"─────────────────────\n"
                        f"✅ *SMA20 just crossed ABOVE SMA50*\n"
                        f"📌 *{info['name']}* @ ${current_price:,.2f}\n"
                        f"─────────────────────\n"
                        f"SMA20: ${sma20:,.2f}\n"
                        f"SMA50: ${sma50:,.2f}\n"
                        f"─────────────────────\n"
                        f"🟢 *Bullish signal.* Historically one\n"
                        f"of the strongest buy signals in\n"
                        f"technical analysis. Trend turning up."
                    )
                    await send_message(msg)

            elif not golden_cross_now and golden_cross_prev:
                last_fired = fired_alerts.get(alert_key_death)
                if not last_fired or (datetime.now() - last_fired).days >= 1:
                    fired_alerts[alert_key_death] = datetime.now()
                    info = HOLDINGS[ticker]
                    msg = (
                        f"📉 *DEATH CROSS — {ticker}*\n"
                        f"─────────────────────\n"
                        f"🔴 *SMA20 just crossed BELOW SMA50*\n"
                        f"📌 *{info['name']}* @ ${current_price:,.2f}\n"
                        f"─────────────────────\n"
                        f"SMA20: ${sma20:,.2f}\n"
                        f"SMA50: ${sma50:,.2f}\n"
                        f"─────────────────────\n"
                        f"⚠️ *Bearish signal.* Short-term trend\n"
                        f"now below long-term. Consider\n"
                        f"tightening stops or reducing position."
                    )
                    await send_message(msg)

# ─── NEWS COLLECTOR — Silently collects news all day for EOD report ─────────
daily_news_cache = []

async def collect_news():
    async with aiohttp.ClientSession() as session:
        for ticker in NEWS_TICKERS:
            if ticker in CRYPTO_MAP:
                current = await get_crypto_price(session, CRYPTO_MAP[ticker])
                prev = None
            else:
                current = await get_stock_price(session, ticker)
                prev = await get_prev_close(session, ticker)

            try:
                articles = await get_news(session, ticker)
                for article in articles:
                    title = article.get("title", "")
                    source = article.get("source", "")
                    url = article.get("url", "")

                    # ── English-only filter ──
                    if is_non_english(title, source, url):
                        continue

                    cache_key = url
                    if cache_key in [n.get("url") for n in daily_news_cache]:
                        continue

                    move_pct = 0
                    direction = ""
                    if current and prev:
                        move_pct = ((current - prev) / prev) * 100
                        direction = "📈" if move_pct > 0 else "📉"
                    daily_news_cache.append({
                        "ticker": ticker,
                        "title": title,
                        "source": source,
                        "url": url,
                        "move_pct": move_pct,
                        "direction": direction,
                        "price": current
                    })
            except Exception as e:
                logger.error(f"News collect error {ticker}: {e}")
            await asyncio.sleep(0.5)

# ─── END OF DAY REPORT — Sent at 4:30pm EST via email ────────────────────────
async def send_eod_report():
    logger.info("Sending end of day report...")
    async with aiohttp.ClientSession() as session:

        # Build prices section
        price_rows = ""
        total_value = 0
        for ticker, info in HOLDINGS.items():
            if ticker in CRYPTO_MAP:
                price = await get_crypto_price(session, CRYPTO_MAP[ticker])
                prev = None
            else:
                price = await get_stock_price(session, ticker)
                prev = await get_prev_close(session, ticker)
            if price:
                value = price * info["shares"]
                total_value += value
                if prev:
                    chg = ((price - prev) / prev) * 100
                    chg_str = f"+{chg:.1f}%" if chg > 0 else f"{chg:.1f}%"
                    color = "#1a7a4a" if chg > 0 else "#b83232"
                else:
                    chg_str = "—"
                    color = "#999"
                price_rows += f"""<tr>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-weight:500;">{ticker}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;">{info['name']}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;text-align:right;">${price:,.2f}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;text-align:right;color:{color};font-weight:500;">{chg_str}</td>
                </tr>"""

        prices_table = f"""<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">
            <tr style="background:#f8f8f8;">
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Ticker</th>
                <th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Name</th>
                <th style="padding:8px 12px;text-align:right;font-size:11px;color:#999;font-weight:500;">Price</th>
                <th style="padding:8px 12px;text-align:right;font-size:11px;color:#999;font-weight:500;">Day Chg</th>
            </tr>
            {price_rows}
        </table>"""

        # Build news section — English only, grouped by ticker
        news_html = ""
        if daily_news_cache:
            seen = set()
            for item in daily_news_cache[-20:]:
                key = item["url"]
                if key in seen:
                    continue
                seen.add(key)
                move_badge = ""
                if abs(item["move_pct"]) >= 3:
                    move_color = "#1a7a4a" if item["move_pct"] > 0 else "#b83232"
                    move_badge = f'<span style="background:{move_color};color:white;font-size:10px;padding:2px 6px;border-radius:3px;margin-left:6px;">{item["direction"]}{abs(item["move_pct"]):.1f}%</span>'
                news_html += f"""<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;">
                    <div style="font-size:12px;font-weight:600;color:#e8a030;margin-bottom:4px;">{item['ticker']}{move_badge}</div>
                    <div style="font-size:13px;color:#1a1a1a;margin-bottom:4px;">{item['title']}</div>
                    <div style="font-size:11px;color:#999;">{item['source']} &nbsp;·&nbsp; <a href="{item['url']}" style="color:#5b9cf6;">Read article</a></div>
                </div>"""
        else:
            news_html = "<div style='color:#999;font-size:13px;'>No significant news today.</div>"

        # Watchlist section
        watchlist_items = [("PANW", 160.00), ("WYNN", 90.00), ("EE", 34.00)]
        watch_html = ""
        for ticker, target in watchlist_items:
            price = await get_stock_price(session, ticker)
            if price:
                diff = price - target
                status_color = "#1a7a4a" if price <= target else "#666"
                status = "🟢 IN ENTRY ZONE" if price <= target else f"${abs(diff):.2f} above target"
                watch_html += f"""<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">
                    <span style="font-weight:500;">{ticker}</span>
                    <span>${price:,.2f}</span>
                    <span>Target ${target}</span>
                    <span style="color:{status_color};">{status}</span>
                </div>"""

        # Goal tracker
        goal_pct = min((total_value / 365000) * 100, 100)
        goal_bar_width = int(goal_pct)

        # Economy articles — fetch before building email
        eco_articles = await get_economy_articles()
        eco_html = ""
        if eco_articles:
            for art in eco_articles:
                eco_html += (
                    '<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;">'
                    '<div style="font-size:13px;color:#1a1a1a;font-weight:500;margin-bottom:4px;">' + art["title"] + '</div>'
                    '<div style="font-size:12px;color:#999;margin-bottom:3px;">' + art["description"] + '</div>'
                    '<div style="font-size:11px;color:#999;">' + art["source"] + ' &nbsp;·&nbsp; <a href="' + art["url"] + '" style="color:#5b9cf6;">Read article</a></div>'
                    '</div>'
                )
        else:
            eco_html = '<div style="color:#999;font-size:13px;">No economy articles today.</div>'

        # Build and send full email
        email_html = build_email(
            f"End of Day Report · {datetime.now(EST).strftime('%A, %b %d, %Y')}",
            [
                {"label": "Portfolio Close", "content": prices_table},
                {"label": "Watchlist Status", "content": watch_html},
                {"label": "Today's News (English only)", "content": news_html},
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

        await send_email(
            f"📊 EOD Report — {datetime.now(EST).strftime('%a %b %d')}",
            email_html
        )

        # Clear news cache for tomorrow
        daily_news_cache.clear()
        logger.info("EOD report sent, news cache cleared")

# ─── MARKET HOURS CHECK ───────────────────────────────────────────────────────
def is_market_open():
    now = datetime.now(EST)
    if now.weekday() >= 5:
        return False
    market_open = time(9, 30)
    market_close = time(16, 0)
    return market_open <= now.time() <= market_close

def is_morning_brief_time():
    now = datetime.now(EST)
    return (
        now.weekday() < 5 and
        now.hour == 9 and
        now.minute >= 30 and
        now.minute <= 35
    )

# ─── PHASE 1 COMMANDS — lightweight getUpdates polling ──────────────────────
last_update_id = 0

async def handle_commands():
    global last_update_id
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as r:
                data = await r.json()
                updates = data.get("result", [])
                for update in updates:
                    last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "").strip().lower()
                    if not text.startswith("/"):
                        continue
                    cmd = text.split()[0]
                    if cmd == "/brief":
                        await send_message("📊 Pulling your brief...")
                        await send_morning_brief()
                    elif cmd == "/prices":
                        async with aiohttp.ClientSession() as s:
                            lines = ["💲 *LIVE PRICES*", "─" * 24]
                            for ticker, info in HOLDINGS.items():
                                if ticker in CRYPTO_MAP:
                                    price = await get_crypto_price(s, CRYPTO_MAP[ticker])
                                else:
                                    price = await get_stock_price(s, ticker)
                                if price:
                                    lines.append(f"📌 *{ticker}* — ${price:,.2f}")
                            await send_message("\n".join(lines))
                    elif cmd == "/watchlist":
                        async with aiohttp.ClientSession() as s:
                            watchlist = [
                                ("PANW", 160.00),
                                ("WYNN", 90.00),
                                ("EE",   34.00),
                            ]
                            lines = ["👀 *WATCHLIST*", "─" * 24]
                            for ticker, target in watchlist:
                                price = await get_stock_price(s, ticker)
                                if price:
                                    diff = price - target
                                    status = "🟢 IN ZONE" if price <= target else f"${diff:+.2f} away"
                                    lines.append(f"📌 *{ticker}* — ${price:,.2f} | Target ${target} | {status}")
                            await send_message("\n".join(lines))
                    elif cmd == "/sleeper":
                        await send_message("🔍 Running sleeper scanner...")
                        async with aiohttp.ClientSession() as s:
                            await send_sleeper_pick(s)
                    elif cmd == "/rsi":
                        async with aiohttp.ClientSession() as s:
                            lines = ["📊 *RSI READINGS*", "─" * 24,
                                     "🟢 ≤30 Oversold · 🔴 ≥70 Overbought · ─ Neutral"]
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
                            "🤖 *COMMANDS*\n"
                            "─────────────────────\n"
                            "/brief — Morning brief on demand\n"
                            "/prices — Live prices now\n"
                            "/watchlist — PANW · WYNN · EE vs targets\n"
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
                rating = data["fear_and_greed"]["rating"]
                return {"score": score, "rating": rating}
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

            alerts = []
            for name, rate in yields.items():
                if rate >= TREASURY_ALERT_THRESHOLD:
                    alerts.append(f"{name} at {rate:.2f}% — worth considering locking in")
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
                result = data["chart"]["result"][0]
                closes = [c for c in result["indicators"]["quote"][0]["close"] if c]
                if len(closes) >= 2:
                    current = closes[-1]
                    prev = closes[-2]
                    drop = ((prev - current) / prev) * 100
                    if drop >= 2.0:
                        market_gift_fired_today = today
                        if drop >= 3.0:
                            verdict = "Significant fear-driven selloff"
                            emoji = "🎁🎁"
                        else:
                            verdict = "Minor fear-driven dip"
                            emoji = "🎁"
                        msg = (
                            f"{emoji} *MARKET GIFT ALERT*\n"
                            "─────────────────────\n"
                            f"📉 S&P 500 down *{drop:.1f}%* today\n"
                            "─────────────────────\n"
                            "This looks like *macro fear*, not fundamental weakness.\n"
                            "Quality stocks drop with the market for no reason.\n"
                            "─────────────────────\n"
                            "👀 *Check your watchlist:*\n"
                            "PANW · GWRE · WYNN · RKLB\n"
                            "─────────────────────\n"
                            f"⚡ {verdict} — DYOR before acting"
                        )
                        await send_message(msg)
    except Exception as e:
        logger.error(f"Market gift check error: {e}")

# ─── EARNINGS COUNTDOWN ───────────────────────────────────────────────────────
EARNINGS_CALENDAR = {
    "SOFI": "2026-05-04",
    "GWRE": "2026-05-21",
    "PANW": "2026-05-26",
    "RKLB": "2026-05-08",
    "AMZN": "2026-05-01",
    "GD":   "2026-04-23",
}

async def check_earnings_countdown():
    today = datetime.now(EST).date()
    alerts = []
    for ticker, date_str in EARNINGS_CALENDAR.items():
        try:
            earnings_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (earnings_date - today).days
            if days_away in [2, 1]:
                alerts.append({
                    "ticker": ticker,
                    "date": earnings_date.strftime("%b %d"),
                    "days": days_away
                })
        except:
            continue
    for alert in alerts:
        days_str = "tomorrow" if alert["days"] == 1 else "in 2 days"
        msg = (
            f"📅 *EARNINGS ALERT — {alert['ticker']}*\n"
            f"─────────────────────\n"
            f"Reports {days_str} — *{alert['date']}*\n"
            f"─────────────────────\n"
            f"⚠️ Be prepared for volatility.\n"
            f"Consider your position size\n"
            f"before the print drops."
        )
        await send_message(msg)

# ─── INSIDER TRADING MONITOR ─────────────────────────────────────────────────
insider_seen = set()

async def check_insider_trading():
    tickers = list(HOLDINGS.keys()) + ["PANW", "WYNN", "EE"]
    stock_tickers = [t for t in tickers if t not in CRYPTO_MAP]
    try:
        async with aiohttp.ClientSession() as session:
            for ticker in stock_tickers:
                if ticker in CRYPTO_MAP:
                    continue
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
                            trans_date = t.get("startDate", {}).get("fmt", "")
                            shares = t.get("shares", {}).get("fmt", "")
                            value = t.get("value", {}).get("fmt", "")
                            filer = t.get("filer", "")
                            relation = t.get("relation", "")
                            trans_type = t.get("transactionDescription", "")
                            is_buy = "Purchase" in trans_type or "Acquisition" in trans_type
                            if is_buy and trans_date:
                                insider_seen.add(trans_id)
                                msg = (
                                    f"🏛️ *INSIDER BUY — {ticker}*\n"
                                    f"─────────────────────\n"
                                    f"👤 {filer} ({relation})\n"
                                    f"📅 {trans_date}\n"
                                    f"📊 {shares} shares · {value}\n"
                                    f"─────────────────────\n"
                                    f"💡 Insiders buy for one reason —\n"
                                    f"they think the stock is going up."
                                )
                                await send_message(msg)
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
                url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize=5&language=en&apiKey={NEWS_API_KEY}"
                async with session.get(url, timeout=10) as r:
                    data = await r.json()
                    for a in data.get("articles", []):
                        title = a.get("title", "")
                        source = a.get("source", {}).get("name", "")
                        art_url = a.get("url", "")

                        # ── English-only filter ──
                        if is_non_english(title, source, art_url):
                            continue

                        articles.append({
                            "title": title,
                            "source": source,
                            "url": art_url,
                            "description": a.get("description", "")[:120] if a.get("description") else ""
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
        lines = []
        total_value = 0
        best = {"ticker": "", "pct": -999}
        worst = {"ticker": "", "pct": 999}

        for ticker, info in HOLDINGS.items():
            if ticker in CRYPTO_MAP:
                price = await get_crypto_price(session, CRYPTO_MAP[ticker])
            else:
                price = await get_stock_price(session, ticker)
            if price:
                value = price * info["shares"]
                total_value += value
                cost = info["avg_cost"] * info["shares"]
                pl_pct = ((value - cost) / cost) * 100
                if pl_pct > best["pct"]:
                    best = {"ticker": ticker, "pct": pl_pct, "price": price}
                if pl_pct < worst["pct"]:
                    worst = {"ticker": ticker, "pct": pl_pct, "price": price}

        goal_pct = (total_value / 365000) * 100
        on_track = total_value >= 291554 * (1 + 0.25 * (datetime.now(EST).month - 3) / 9)

        lines.append("📊 *WEEKLY REPORT*")
        lines.append(f"📅 {datetime.now(EST).strftime('%A, %b %d')}")
        lines.append("─" * 28)
        lines.append(f"💼 *Invested Value:* ${total_value:,.0f}")
        lines.append(f"🎯 *$365k Goal:* {goal_pct:.1f}%")
        lines.append(f"{'✅ On track' if on_track else '⚠️ Behind pace'}")
        lines.append("─" * 28)
        if best["ticker"]:
            lines.append(f"🏆 *Best:* {best['ticker']} @ ${best['price']:,.2f} ({best['pct']:+.1f}%)")
        if worst["ticker"]:
            lines.append(f"📉 *Weakest:* {worst['ticker']} @ ${worst['price']:,.2f} ({worst['pct']:+.1f}%)")
        lines.append("─" * 28)
        lines.append("⚡ _Have a great weekend Patrick_")
        await send_message("\n".join(lines))

# ─── MONDAY GOAL CHECK ────────────────────────────────────────────────────────
async def send_monday_goal_check():
    async with aiohttp.ClientSession() as session:
        total_value = 0
        for ticker, info in HOLDINGS.items():
            if ticker in CRYPTO_MAP:
                price = await get_crypto_price(session, CRYPTO_MAP[ticker])
            else:
                price = await get_stock_price(session, ticker)
            if price:
                total_value += price * info["shares"]

        goal_target = 365000
        gap = goal_target - total_value
        months_left = max(1, 12 - datetime.now(EST).month + 1)
        needed_per_month = gap / months_left
        goal_pct = (total_value / goal_target) * 100

        msg = (
            f"🎯 *MONDAY GOAL CHECK*\n"
            f"─────────────────────\n"
            f"💼 Current: ${total_value:,.0f}\n"
            f"🏁 Target: $365,000\n"
            f"📊 Progress: {goal_pct:.1f}%\n"
            f"─────────────────────\n"
            f"{'✅ On pace' if gap <= 0 else f'📍 Gap: ${gap:,.0f}'}\n"
            f"{'🎉 Goal reached!' if gap <= 0 else f'Need ~${needed_per_month:,.0f}/mo to close gap'}\n"
            f"─────────────────────\n"
            f"⚡ _Make it a great week_"
        )
        await send_message(msg)

# ─── PRE-MARKET BRIEFING — Sent at 8:00am EST via email ──────────────────────
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
                    meta = result["meta"]
                    current = float(meta.get("regularMarketPrice", closes[-1]))
                    prev = closes[-2] if len(closes) >= 2 else current
                    chg_pct = ((current - prev) / prev) * 100
                    high_30d = max(closes)
                    return {"price": current, "chg": chg_pct, "high_30d": high_30d, "closes": closes}
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
                score += 2
                flags.append("S&P above 20-day SMA ✅")
            else:
                score -= 2
                flags.append("S&P below 20-day SMA ⚠️")
            drawdown = ((sp500["high_30d"] - sp500["price"]) / sp500["high_30d"]) * 100
            if drawdown > 10:
                score -= 2
                flags.append(f"Down {drawdown:.1f}% from 30-day high ⚠️")
            elif drawdown < 3:
                score += 1
                flags.append(f"Near 30-day high ({drawdown:.1f}% below) ✅")

        if vix_d:
            v = vix_d["price"]
            if v < 15:
                score += 2; flags.append(f"VIX {v:.1f} — Very low fear ✅")
            elif v < 20:
                score += 1; flags.append(f"VIX {v:.1f} — Calm ✅")
            elif v < 25:
                score -= 1; flags.append(f"VIX {v:.1f} — Elevated ⚠️")
            elif v < 30:
                score -= 2; flags.append(f"VIX {v:.1f} — High fear 🔴")
            else:
                score -= 3; flags.append(f"VIX {v:.1f} — Extreme fear 🔴")

        if futures:
            fc = futures["chg"]
            if fc > 0.5:
                score += 1; flags.append(f"Futures up {fc:.2f}% ✅")
            elif fc < -0.5:
                score -= 1; flags.append(f"Futures down {fc:.2f}% ⚠️")

        if treasury:
            ty = treasury["price"]
            if ty > 4.5:
                score -= 1; flags.append(f"10yr yield {ty:.2f}% — Restrictive ⚠️")
            elif ty < 4.0:
                score += 1; flags.append(f"10yr yield {ty:.2f}% — Supportive ✅")

        if score >= 4:
            cond = "BULL"; c_color = "#1a7a4a"; c_bg = "#e8f5ee"; c_emoji = "🟢"
            rec = "Risk-on environment. Strong momentum. Good conditions for new entries on quality names. Your PANW and GWRE setups look favorable. Watch RKLB toward $100."
        elif score >= 1:
            cond = "NEUTRAL"; c_color = "#a06a10"; c_bg = "#fef6e4"; c_emoji = "🟡"
            rec = "Mixed signals. Proceed selectively. Focus on high-conviction names only. Keep some powder dry and wait for clearer setups before deploying capital."
        elif score >= -2:
            cond = "CAUTION"; c_color = "#b83232"; c_bg = "#fceaea"; c_emoji = "🔴"
            rec = "Risk-off conditions. Hold existing positions but pause new entries. Your cash allocation is a strength right now. Watch VIX for stabilization before acting."
        else:
            cond = "BEAR"; c_color = "#7a0000"; c_bg = "#ffe8e8"; c_emoji = "💀"
            rec = "Bear market conditions. Protect capital first. Consider trimming speculative positions. Cash is a position — hold it and wait for the dust to settle."

        def fmt_price(val):
            if val is None:
                return "N/A"
            return f"{val:,.2f}"

        def idx_row(name, data, invert=False):
            if not data:
                return f'<tr><td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;">{name}</td><td colspan="2" style="padding:8px 12px;color:#999;border-bottom:1px solid #f5f5f5;">Unavailable</td></tr>'
            chg = data["chg"]
            up_color = "#b83232" if invert else "#1a7a4a"
            dn_color = "#1a7a4a" if invert else "#b83232"
            color = up_color if chg >= 0 else dn_color
            arrow = "▲" if chg >= 0 else "▼"
            price_str = fmt_price(data["price"])
            return (
                '<tr>'
                '<td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-weight:500;font-size:13px;">' + name + '</td>'
                '<td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-size:13px;">' + price_str + '</td>'
                '<td style="padding:8px 12px;border-bottom:1px solid #f5f5f5;font-size:13px;font-weight:500;color:' + color + ';">' + arrow + ' ' + f"{abs(chg):.2f}%" + '</td>'
                '</tr>'
            )

        index_rows = (
            idx_row("S&P 500", sp500) +
            idx_row("Nasdaq", nasdaq) +
            idx_row("Dow Jones", dow) +
            idx_row("S&P 500 Futures", futures) +
            idx_row("VIX — Fear Index", vix_d, invert=True) +
            idx_row("10-yr Treasury", treasury, invert=True) +
            idx_row("Dollar Index (DXY)", dxy, invert=True)
        )

        index_table = (
            '<table width="100%" cellpadding="0" cellspacing="0">'
            '<tr style="background:#f8f8f8;">'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Index</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Level</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#999;font-weight:500;">Change</th>'
            '</tr>' + index_rows + '</table>'
        )

        flags_html = "".join(
            '<div style="padding:5px 0;border-bottom:1px solid #f5f5f5;font-size:13px;color:#444;">' + f + '</div>'
            for f in flags
        )

        score_sign = "+" + str(score) if score > 0 else str(score)
        date_str = datetime.now(EST).strftime("%A, %B %d, %Y")
        date_short = datetime.now(EST).strftime("%a %b %d")

        email_html = (
            '<html><body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">'
            '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 16px;">'
            '<tr><td align="center">'
            '<table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
            '<tr><td style="background:#0f0f14;padding:24px 28px;">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#666;text-transform:uppercase;margin-bottom:6px;">Pre-Market Intelligence</div>'
            '<div style="font-size:24px;font-weight:700;color:#e8c96e;letter-spacing:-0.5px;">Patrick Portfolio Bot</div>'
            '<div style="font-size:13px;color:#888;margin-top:4px;">' + date_str + ' · 8:00am EST</div>'
            '</td></tr>'
            '<tr><td style="background:' + c_bg + ';padding:20px 28px;border-bottom:3px solid ' + c_color + ';">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:' + c_color + ';text-transform:uppercase;margin-bottom:6px;">Market Condition</div>'
            '<div style="font-size:32px;font-weight:800;color:' + c_color + ';letter-spacing:-1px;">' + c_emoji + ' ' + cond + '</div>'
            '<div style="font-size:13px;color:' + c_color + ';margin-top:4px;opacity:0.8;">Score: ' + score_sign + ' based on ' + str(len(flags)) + ' signals</div>'
            '</td></tr>'
            '<tr><td style="padding:20px 28px 0;">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Index Snapshot</div>'
            + index_table +
            '</td></tr>'
            '<tr><td style="padding:20px 28px 0;">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Signal Breakdown</div>'
            + flags_html +
            '</td></tr>'
            '<tr><td style="padding:20px 28px;">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Recommendation</div>'
            '<div style="background:' + c_bg + ';border-left:4px solid ' + c_color + ';border-radius:0 8px 8px 0;padding:16px 18px;font-size:14px;color:#1a1a1a;line-height:1.7;">'
            + rec +
            '</div>'
            '</td></tr>'
            '<tr><td style="padding:0 28px 20px;">'
            '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Your Active Targets</div>'
            '<div>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;margin-right:6px;display:inline-block;margin-bottom:6px;">RKLB $100 TRIM</span>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;margin-right:6px;display:inline-block;margin-bottom:6px;">GWRE $158 ADD</span>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;margin-right:6px;display:inline-block;margin-bottom:6px;">PANW $160 BUY</span>'
            '<span style="background:#f0f0f0;padding:5px 10px;border-radius:4px;font-size:12px;font-family:monospace;display:inline-block;margin-bottom:6px;">WYNN $90 BUY</span>'
            '</div>'
            '</td></tr>'
            '<tr><td style="padding:16px 28px;background:#fafafa;border-top:1px solid #f0f0f0;text-align:center;">'
            '<div style="font-size:11px;color:#bbb;font-family:monospace;">Not financial advice · Patrick Portfolio Bot · ' + date_short + '</div>'
            '</td></tr>'
            '</table></td></tr></table>'
            '</body></html>'
        )

        # Fear & Greed
        fg = await get_fear_greed()
        fg_html = ""
        if fg:
            fg_score = fg["score"]
            fg_color = fear_greed_color(fg_score)
            fg_emoji = fear_greed_emoji(fg_score)
            fg_html = (
                '<tr><td style="padding:20px 28px 0;">'
                '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Fear & Greed Index</div>'
                '<div style="background:#f8f8f8;border-radius:8px;padding:16px;display:flex;align-items:center;gap:16px;">'
                '<div style="font-size:36px;font-weight:800;color:' + fg_color + ';">' + fg_emoji + ' ' + str(int(fg_score)) + '</div>'
                '<div>'
                '<div style="font-size:14px;font-weight:600;color:' + fg_color + ';">' + fg["rating"].title() + '</div>'
                '<div style="font-size:12px;color:#999;margin-top:2px;">0 = Extreme Fear · 100 = Extreme Greed</div>'
                '</div>'
                '</div>'
                '</td></tr>'
            )

        # Treasury yields
        yields, t_alerts = await check_treasury_yields()
        treasury_html = ""
        if yields:
            yield_rows = "".join(
                '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">'
                '<span style="font-weight:500;">' + k.upper() + ' Treasury</span>'
                '<span style="color:' + ("#b83232" if v >= TREASURY_ALERT_THRESHOLD else "#333") + ';font-weight:' + ("700" if v >= TREASURY_ALERT_THRESHOLD else "400") + ';">'
                + str(v) + '%' + (" ← Consider buying" if v >= TREASURY_ALERT_THRESHOLD else "") + '</span>'
                '</div>'
                for k, v in yields.items()
            )
            treasury_html = (
                '<tr><td style="padding:20px 28px 0;">'
                '<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:12px;">Treasury Yields</div>'
                + yield_rows +
                (''.join('<div style="margin-top:8px;background:#e8f5ee;border-left:3px solid #1a7a4a;padding:10px 12px;font-size:12px;color:#1a7a4a;border-radius:0 6px 6px 0;">💡 ' + a + '</div>' for a in t_alerts) if t_alerts else "") +
                '</td></tr>'
            )

        # Rebuild email with F&G and Treasury inserted
        email_html = email_html.replace(
            '<tr><td style="padding:0 28px 20px;">',
            fg_html + treasury_html + '<tr><td style="padding:0 28px 20px;">',
            1
        )

        await send_email(c_emoji + " Pre-Market Brief — " + cond + " · " + date_short, email_html)
        logger.info(f"Pre-market brief sent — condition: {cond} score: {score}")

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
async def main():
    logger.info("Patrick's Portfolio Bot starting...")
    await send_message(
        "🤖 *Patrick's Portfolio Bot is LIVE*\n"
        "─────────────────────\n"
        "✅ Pre-market briefing: 8:00am EST (email)\n"
        "✅ Morning briefs: 9:30am EST\n"
        "✅ Price alerts: Active (Yahoo Finance — real-time)\n"
        "✅ RSI signals: Active\n"
        "✅ MA crossover alerts: Active\n"
        "✅ News: Collected silently → EOD email report\n"
        "✅ Fear & Greed: Pre-market email daily\n"
        "✅ Treasury yields: Monitored · Flags compelling rates\n"
        "✅ Market Gift Alert: Telegram when S&P drops 2%+\n"
        "✅ Earnings countdown: 2-day heads up\n"
        "✅ Insider trading: SEC Form 4 monitor\n"
        "✅ Weekly report: Fridays 4pm\n"
        "✅ Monday goal check: Every Monday 9am\n"
        "✅ Daily sleeper pick: Active\n"
        "─────────────────────\n"
        "💬 Commands: /brief /prices /watchlist /sleeper /rsi /help\n"
        "─────────────────────\n"
        "Tracking: RKLB · VTI · ETH · GD · AMZN\n"
        "GWRE · MRSH · SOFI · BTC"
    )

    premarket_sent_today = None
    morning_brief_sent_today = None
    eod_sent_today = None
    weekly_report_sent = None
    monday_check_sent = None
    last_insider_check = None
    last_earnings_check = None
    last_gift_check = None
    last_price_check = None
    last_rsi_check = None
    last_ma_check = None
    last_news_collect = None

    while True:
            now = datetime.now(EST)
            today = now.date()

            # Pre-market briefing at 8:00am EST weekdays
            if (now.weekday() < 5 and now.hour == 8 and
                    now.minute >= 0 and now.minute <= 5 and
                    premarket_sent_today != today):
                await send_premarket_briefing()
                premarket_sent_today = today

            # Morning brief at 9:30am EST weekdays
            if is_morning_brief_time() and morning_brief_sent_today != today:
                await send_morning_brief()
                morning_brief_sent_today = today

            # Price alerts every 5 minutes during market hours
            if is_market_open():
                if not last_price_check or (now - last_price_check).seconds >= 300:
                    await check_price_alerts()
                    last_price_check = now

            # RSI check every 30 minutes during market hours
            if is_market_open():
                if not last_rsi_check or (now - last_rsi_check).seconds >= 1800:
                    await check_rsi_alerts()
                    last_rsi_check = now

            # MA crossover check every 60 minutes during market hours
            if is_market_open():
                if not last_ma_check or (now - last_ma_check).seconds >= 3600:
                    await check_ma_alerts()
                    last_ma_check = now

            # Collect news silently every 30 minutes during market hours
            if is_market_open():
                if not last_news_collect or (now - last_news_collect).seconds >= 1800:
                    await collect_news()
                    last_news_collect = now

            # EOD report at 4:30pm EST weekdays
            if (now.weekday() < 5 and now.hour == 16 and
                    now.minute >= 30 and now.minute <= 35 and
                    eod_sent_today != today):
                await send_eod_report()
                eod_sent_today = today

            # Weekly Friday report at 4:00pm
            if (now.weekday() == 4 and now.hour == 16 and
                    now.minute >= 0 and now.minute <= 5 and
                    weekly_report_sent != today):
                await send_weekly_report()
                weekly_report_sent = today

            # Monday goal check at 9:00am
            if (now.weekday() == 0 and now.hour == 9 and
                    now.minute >= 0 and now.minute <= 5 and
                    monday_check_sent != today):
                await send_monday_goal_check()
                monday_check_sent = today

            # Earnings countdown check once daily at 8:30am
            if (now.weekday() < 5 and now.hour == 8 and
                    now.minute >= 30 and now.minute <= 35 and
                    last_earnings_check != today):
                await check_earnings_countdown()
                last_earnings_check = today

            # Insider trading check every 4 hours during market hours
            if is_market_open():
                if not last_insider_check or (now - last_insider_check).seconds >= 14400:
                    await check_insider_trading()
                    last_insider_check = now

            # Market gift check every 30 minutes during market hours
            if is_market_open():
                if not last_gift_check or (now - last_gift_check).seconds >= 1800:
                    await check_market_gift()
                    last_gift_check = now

            # Check for commands every 3 seconds
            await handle_commands()
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
