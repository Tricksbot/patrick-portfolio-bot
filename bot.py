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
    "MMC":  {"shares": 61.3,   "avg_cost": 178.30, "name": "Marsh & McLennan"},
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
NEWS_TICKERS = ["RKLB", "GWRE", "SOFI", "PANW", "AMZN", "GD", "BTC", "ETH", "WYNN", "EE", "MMC", "VTI", "AUR"]
seen_news = set()
fired_alerts = {}

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
        # Map coin_id to Yahoo Finance ticker
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
        total_cost = 0

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

        # Also send morning brief as HTML email
        holdings_html = "".join(
            f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f5f5f5;">'
            f'<span style="font-weight:500;">{line.replace("📌 *","").replace("* —","")[:30]}</span>'
            f'</div>'
            for line in lines if line.startswith("📌")
        )
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

        # Send sleeper pick right after morning brief
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
                    # Filter non-English articles
                    if not title:
                        continue
                    non_english_chars = sum(1 for c in title if ord(c) > 127)
                    if non_english_chars > len(title) * 0.2:
                        continue
                    cache_key = article.get("url", "")
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
                        "source": article.get("source", ""),
                        "url": article.get("url", ""),
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

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
async def main():
    logger.info("Patrick's Portfolio Bot starting...")
    await send_message(
        "🤖 *Patrick's Portfolio Bot is LIVE*\n"
        "─────────────────────\n"
        "✅ Morning briefs: 9:30am EST\n"
        "✅ Price alerts: Active (Yahoo Finance — real-time)\n"
        "✅ RSI signals: Active\n"
        "✅ MA crossover alerts: Active\n"
        "✅ News: Collected silently → EOD email report\n"
        "✅ Daily sleeper pick: Active\n"
        "─────────────────────\n"
        "💬 Commands: /brief /prices /watchlist /sleeper /rsi /help\n"
        "─────────────────────\n"
        "Tracking: RKLB · VTI · ETH · GD · AMZN\n"
        "GWRE · MMC · SOFI · BTC"
    )

    morning_brief_sent_today = None
    eod_sent_today = None
    last_price_check = None
    last_rsi_check = None
    last_ma_check = None
    last_news_collect = None

    while True:
            now = datetime.now(EST)
            today = now.date()

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

            # Check for commands every 3 seconds
            await handle_commands()
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
