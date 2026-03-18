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

EST = pytz.timezone("America/New_York")

# ─── YOUR PORTFOLIO ────────────────────────────────────────────────────────────
HOLDINGS = {
    "RKLB": {"shares": 700,  "avg_cost": 6.73,   "name": "Rocket Lab USA"},
    "VTI":  {"shares": 112.17,"avg_cost": 233.36, "name": "Vanguard Total Market"},
    "ETH":  {"shares": 13.01, "avg_cost": 2068.41,"name": "Ether"},
    "GD":   {"shares": 64.19, "avg_cost": 252.17, "name": "General Dynamics"},
    "AMZN": {"shares": 78,    "avg_cost": 144.46, "name": "Amazon"},
    "GWRE": {"shares": 67,    "avg_cost": 160.57, "name": "Guidewire Software"},
    "MMC":  {"shares": 61.3,  "avg_cost": 178.30, "name": "Marsh & McLennan"},
    "SOFI": {"shares": 300,   "avg_cost": 18.39,  "name": "SoFi Technologies"},
    "BTC":  {"shares": 0.03029,"avg_cost": 86490, "name": "Bitcoin"},
    "AUR":  {"shares": 450,   "avg_cost": 6.10,   "name": "Aurora Innovation"},
}

CRYPTO_MAP = {"ETH": "ethereum", "BTC": "bitcoin"}

# ─── PRICE ALERTS ─────────────────────────────────────────────────────────────
PRICE_ALERTS = [
    {"ticker": "RKLB", "target": 100.00, "direction": "above", "action": "🔴 TRIM 250 shares at $100 — your planned exit. Net ~$17,900 after 30% tax."},
    {"ticker": "PANW", "target": 165.00, "direction": "below", "action": "🟢 BUY ZONE — deploy ~$7,000. Analyst avg target $210 (+27%)."},
    {"ticker": "PANW", "target": 155.00, "direction": "below", "action": "🟢 STRONG BUY — deep in your entry zone. Add full $7,000 position now."},
    {"ticker": "SOFI", "target": 15.00,  "direction": "below", "action": "🔴 STOP LOSS — exit all 300 shares. Muddy Waters risk too high below $15."},
    {"ticker": "GWRE", "target": 158.00, "direction": "below", "action": "🟢 ADD OPPORTUNITY — top up GWRE. Analyst avg $266 (+65% from here)."},
    {"ticker": "WYNN", "target": 97.00,  "direction": "below", "action": "🟡 WATCHLIST ENTRY — WYNN at target zone. $138 analyst avg (+42%)."},
    {"ticker": "MMC",  "target": 185.00, "direction": "above", "action": "🟡 CONSIDER SELLING MMC — only +2.5% gain, redeploy into PANW/GWRE."},
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

# ─── NEWS TICKERS ─────────────────────────────────────────────────────────────
NEWS_TICKERS = ["RKLB", "GWRE", "SOFI", "PANW", "AMZN", "GD", "BTC", "ETH", "WYNN", "EE", "MMC", "AUR", "VTI"]
seen_news = set()
fired_alerts = {}

# ─── PRICE FETCHING ───────────────────────────────────────────────────────────
async def get_stock_price(session, ticker):
    try:
        url = f"https://api.polygon.io/v2/last/trade/{ticker}?apiKey={POLYGON_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            if data.get("results"):
                return float(data["results"]["p"])
    except Exception as e:
        logger.error(f"Price fetch error {ticker}: {e}")
    return None

async def get_crypto_price(session, coin_id):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            return float(data[coin_id]["usd"])
    except Exception as e:
        logger.error(f"Crypto fetch error {coin_id}: {e}")
    return None

async def get_prev_close(session, ticker):
    try:
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            if data.get("results"):
                return float(data["results"][0]["c"])
    except Exception as e:
        logger.error(f"Prev close error {ticker}: {e}")
    return None

async def get_historical_prices(session, ticker, days=60):
    try:
        from datetime import timedelta
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}?adjusted=true&sort=asc&apiKey={POLYGON_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json()
            if data.get("results"):
                return [float(x["c"]) for x in data["results"]]
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
                cost = info["avg_cost"] * info["shares"]
                pl = value - cost
                pl_pct = (pl / cost) * 100
                total_value += value
                total_cost += cost

                arrow = "▲" if pl > 0 else "▼" if pl < 0 else "─"
                sign = "+" if pl > 0 else ""
                lines.append(
                    f"{arrow} *{ticker}* ${price:,.2f} | "
                    f"${value:,.0f} | {sign}{pl_pct:.1f}%"
                )

        total_pl = total_value - total_cost
        total_pl_pct = (total_pl / total_cost) * 100
        lines.append("─" * 32)
        lines.append(f"💼 *Invested Value:* ${total_value:,.0f}")
        lines.append(f"{'📈' if total_pl > 0 else '📉'} *Total P&L:* ${total_pl:+,.0f} ({total_pl_pct:+.1f}%)")
        lines.append("─" * 32)

        goal_current = 291554
        goal_target = 365000
        goal_pct = (goal_current / goal_target) * 100
        lines.append(f"🎯 *$365k Goal:* {goal_pct:.1f}% there")
        lines.append(f"   Gap remaining: ${goal_target - goal_current:,.0f}")
        lines.append("─" * 32)
        lines.append("⚡ _Alerts active: RKLB $100 trim · PANW $165 buy · SOFI $15 stop_")

        await send_message("\n".join(lines))

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

# ─── NEWS ALERT CHECKER ───────────────────────────────────────────────────────
async def check_news_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in NEWS_TICKERS:
            articles = await get_news(session, ticker)
            for article in articles:
                if article["title"]:
                    msg = (
                        f"📰 *NEWS — {ticker}*\n"
                        f"─────────────────────\n"
                        f"{article['title']}\n"
                        f"─────────────────────\n"
                        f"📡 Source: {article['source']}\n"
                        f"🔗 {article['url']}"
                    )
                    await send_message(msg)
                    await asyncio.sleep(2)

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

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
async def main():
    logger.info("Patrick's Portfolio Bot starting...")
    await send_message(
        "🤖 *Patrick's Portfolio Bot is LIVE*\n"
        "─────────────────────\n"
        "✅ Morning briefs: 9:30am EST\n"
        "✅ Price alerts: Active\n"
        "✅ RSI signals: Active (oversold ≤30, overbought ≥70)\n"
        "✅ Moving average alerts: Active\n"
        "✅ News alerts: Active\n"
        "─────────────────────\n"
        "Tracking: RKLB · VTI · ETH · GD · AMZN\n"
        "GWRE · MMC · SOFI · BTC · AUR\n"
        "─────────────────────\n"
        "🎯 Price targets set. Watching for your entries."
    )

    morning_brief_sent_today = None
    last_price_check = None
    last_rsi_check = None
    last_ma_check = None
    last_news_check = None

    while True:
        now = datetime.now(EST)
        today = now.date()

        # Morning brief at 9:30am EST on weekdays
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

        # News check every 30 minutes
        if not last_news_check or (now - last_news_check).seconds >= 1800:
            await check_news_alerts()
            last_news_check = now

        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
