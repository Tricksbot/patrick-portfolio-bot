import os
import asyncio
import logging
import json
import aiohttp
import pytz
from datetime import datetime, time, timedelta
from telegram import Bot
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID")
POLYGON_API_KEY   = os.environ.get("POLYGON_API_KEY")
NEWS_API_KEY      = os.environ.get("NEWS_API_KEY")
EMAIL_FROM        = os.environ.get("EMAIL_FROM")
EMAIL_TO          = os.environ.get("EMAIL_TO")
EMAIL_PASSWORD    = os.environ.get("EMAIL_PASSWORD")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

EST = pytz.timezone("America/New_York")

HOLDINGS = {
    "RKLB": {"shares": 700,      "avg_cost": 6.73,    "name": "Rocket Lab USA"},
    "VTI":  {"shares": 113.17,   "avg_cost": 233.36,  "name": "Vanguard Total Market"},
    "ETH":  {"shares": 13.02,    "avg_cost": 2068.00, "name": "Ether"},
    "GD":   {"shares": 64.19,    "avg_cost": 252.17,  "name": "General Dynamics"},
    "AMZN": {"shares": 79,       "avg_cost": 144.46,  "name": "Amazon"},
    "GWRE": {"shares": 72,       "avg_cost": 157.18,  "name": "Guidewire Software"},
    "MRSH": {"shares": 61.3,     "avg_cost": 178.30,  "name": "Marsh McLennan"},
    "SOFI": {"shares": 430,      "avg_cost": 18.03,   "name": "SoFi Technologies"},
    "BTC":  {"shares": 0.032549, "avg_cost": 85400,   "name": "Bitcoin"},
    "AUR":  {"shares": 450,      "avg_cost": 6.10,    "name": "Aurora Innovation"},
    "LINK": {"shares": 409.36,   "avg_cost": 15.00,   "name": "Chainlink"},
}
CRYPTO_MAP = {"ETH": "ethereum", "BTC": "bitcoin", "LINK": "chainlink"}

ECONOMIC_CALENDAR = [
    {"date": "2026-04-01", "event": "ISM Manufacturing PMI",  "expected": "49.5",       "prior": "49.8",       "impact": "M"},
    {"date": "2026-04-03", "event": "ISM Services PMI",       "expected": "53.0",       "prior": "53.5",       "impact": "M"},
    {"date": "2026-04-04", "event": "Nonfarm Payrolls",       "expected": "+185K",      "prior": "+151K",      "impact": "H"},
    {"date": "2026-04-04", "event": "Unemployment Rate",      "expected": "4.1%",       "prior": "4.1%",       "impact": "H"},
    {"date": "2026-04-10", "event": "CPI (YoY)",              "expected": "2.6%",       "prior": "2.8%",       "impact": "H"},
    {"date": "2026-04-10", "event": "Core CPI (YoY)",         "expected": "3.0%",       "prior": "3.1%",       "impact": "H"},
    {"date": "2026-04-11", "event": "PPI (YoY)",              "expected": "3.2%",       "prior": "3.2%",       "impact": "M"},
    {"date": "2026-04-16", "event": "Retail Sales (MoM)",     "expected": "+0.3%",      "prior": "-0.9%",      "impact": "H"},
    {"date": "2026-04-17", "event": "Jobless Claims",         "expected": "220K",       "prior": "223K",       "impact": "M"},
    {"date": "2026-04-23", "event": "S&P Global PMI Flash",   "expected": "53.0",       "prior": "53.5",       "impact": "M"},
    {"date": "2026-04-25", "event": "PCE Price Index (YoY)",  "expected": "2.5%",       "prior": "2.5%",       "impact": "H"},
    {"date": "2026-04-30", "event": "GDP Advance Q1 2026",    "expected": "+2.1%",      "prior": "+2.3%",      "impact": "H"},
    {"date": "2026-04-30", "event": "FOMC Meeting Begins",    "expected": "—",          "prior": "—",          "impact": "H"},
    {"date": "2026-05-01", "event": "FOMC Rate Decision",     "expected": "4.25-4.50%", "prior": "4.25-4.50%", "impact": "H"},
    {"date": "2026-05-01", "event": "Fed Press Conference",   "expected": "—",          "prior": "—",          "impact": "H"},
    {"date": "2026-05-02", "event": "Nonfarm Payrolls",       "expected": "+175K",      "prior": "+185K",      "impact": "H"},
    {"date": "2026-05-02", "event": "Unemployment Rate",      "expected": "4.1%",       "prior": "4.1%",       "impact": "H"},
    {"date": "2026-05-13", "event": "CPI (YoY)",              "expected": "2.4%",       "prior": "2.6%",       "impact": "H"},
    {"date": "2026-05-13", "event": "Core CPI (YoY)",         "expected": "2.9%",       "prior": "3.0%",       "impact": "H"},
    {"date": "2026-05-15", "event": "Retail Sales (MoM)",     "expected": "+0.4%",      "prior": "+0.3%",      "impact": "H"},
    {"date": "2026-05-28", "event": "PCE Price Index (YoY)",  "expected": "2.4%",       "prior": "2.5%",       "impact": "H"},
    {"date": "2026-06-05", "event": "Nonfarm Payrolls",       "expected": "+170K",      "prior": "+175K",      "impact": "H"},
    {"date": "2026-06-05", "event": "Unemployment Rate",      "expected": "4.1%",       "prior": "4.1%",       "impact": "H"},
    {"date": "2026-06-10", "event": "CPI (YoY)",              "expected": "2.3%",       "prior": "2.4%",       "impact": "H"},
    {"date": "2026-06-10", "event": "Core CPI (YoY)",         "expected": "2.8%",       "prior": "2.9%",       "impact": "H"},
    {"date": "2026-06-16", "event": "FOMC Meeting Begins",    "expected": "—",          "prior": "—",          "impact": "H"},
    {"date": "2026-06-17", "event": "FOMC Rate Decision",     "expected": "4.25-4.50%", "prior": "4.25-4.50%", "impact": "H"},
    {"date": "2026-06-17", "event": "Fed Press Conference",   "expected": "—",          "prior": "—",          "impact": "H"},
    {"date": "2026-06-26", "event": "PCE Price Index (YoY)",  "expected": "2.3%",       "prior": "2.4%",       "impact": "H"},
]

def get_upcoming_econ_events(days_ahead=7):
    today = datetime.now(EST).date()
    upcoming = []
    for event in ECONOMIC_CALENDAR:
        try:
            ed = datetime.strptime(event["date"], "%Y-%m-%d").date()
            days_away = (ed - today).days
            if 0 <= days_away <= days_ahead:
                upcoming.append({**event, "days": days_away, "date_fmt": ed.strftime("%a %b %d")})
        except:
            continue
    return sorted(upcoming, key=lambda x: x["days"])

def econ_calendar_html(days_ahead=7):
    events = get_upcoming_econ_events(days_ahead)
    if not events:
        return '<div style="font-size:13px;color:#999;">No major economic events in this window.</div>'
    rows = ""
    for e in events:
        ic = "#b83232" if e["impact"] == "H" else "#a06a10"
        il = "HIGH IMPACT" if e["impact"] == "H" else "MEDIUM"
        dl = "Today" if e["days"] == 0 else ("Tomorrow" if e["days"] == 1 else f"In {e['days']} days")
        ex = f'<span style="color:#1a7a4a;font-weight:500;">{e["expected"]}</span>' if e["expected"] != "—" else "—"
        rows += (f'<tr>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:12px;color:#888;">{e["date_fmt"]}<br><span style="color:#e8a030;font-size:11px;">{dl}</span></td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;font-weight:500;">{e["event"]}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:12px;text-align:center;">{ex}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:12px;text-align:center;color:#555;">{e["prior"]}</td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;text-align:center;"><span style="background:{ic}22;color:{ic};font-size:10px;font-weight:600;padding:2px 7px;border-radius:3px;">{il}</span></td>'
                 f'</tr>')
    return ('<table width="100%" cellpadding="0" cellspacing="0"><tr style="background:#f8f8f8;">'
            '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Date</th>'
            '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Event</th>'
            '<th style="padding:7px 10px;text-align:center;font-size:11px;color:#999;font-weight:500;">Expected</th>'
            '<th style="padding:7px 10px;text-align:center;font-size:11px;color:#999;font-weight:500;">Prior</th>'
            '<th style="padding:7px 10px;text-align:center;font-size:11px;color:#999;font-weight:500;">Impact</th>'
            '</tr>' + rows + '</table>')

def econ_calendar_telegram(days_ahead=3):
    events = get_upcoming_econ_events(days_ahead)
    if not events:
        return ""
    lines = ["📅 *ECONOMIC CALENDAR*", "─" * 28]
    for e in events:
        flag = "🔴" if e["impact"] == "H" else "🟡"
        dl   = "Today" if e["days"] == 0 else ("Tomorrow" if e["days"] == 1 else f"In {e['days']}d")
        ex   = f" · exp {e['expected']}" if e["expected"] != "—" else ""
        lines.append(f"{flag} *{e['event']}* — {e['date_fmt']} ({dl}){ex} | prior {e['prior']}")
    return "\n".join(lines)

PRICE_ALERTS = [
    {"ticker": "RKLB", "target": 100.00, "direction": "above", "action": "🔴 TRIM ALERT — RKLB hit $100. Trim 250 shares as planned. Net ~$17,900 after 30% tax. Keep 450 shares running."},
    {"ticker": "GWRE", "target": 158.00, "direction": "below", "action": "🟢 ADD OPPORTUNITY — GWRE at $158. Top up your position."},
    {"ticker": "PANW", "target": 160.00, "direction": "below", "action": "🟢 BUY ZONE — PANW hit $160. Start your position. Analyst avg target $210 (+31% upside)."},
    {"ticker": "WYNN", "target": 90.00,  "direction": "below", "action": "🟢 BUY ZONE — WYNN hit $90. Start a position. Analyst avg target $138 (+53% upside)."},
]

RSI_OVERSOLD = 30; RSI_OVERBOUGHT = 70; RSI_PERIOD = 14
MA_SHORT = 20; MA_LONG = 50; MA_FAST = 12; MA_SLOW = 26; MA_SIGNAL = 9
TREASURY_ALERT_THRESHOLD = 4.5

NEWS_TICKERS = ["RKLB","GWRE","SOFI","PANW","AMZN","GD","BTC","ETH","WYNN","MRSH","VTI","AUR","LINK"]
seen_news = set(); fired_alerts = {}; daily_news_cache = []
market_gift_fired_today = None; insider_seen = set()
consider_buying_fired_today = set()

TRUSTED_SOURCES = ["reuters","bloomberg","cnbc","wsj","wall street journal","financial times",
    "marketwatch","seeking alpha","barron","forbes","yahoo finance","ap news","associated press",
    "business insider","coinmarketcap","cointelegraph","benzinga","the street","investopedia"]
NON_ENGLISH_KEYWORDS = [" de "," la "," el "," en "," es "," que "," del "," los "," las ",
    " por "," con "," para "," una "," ein "," der "," die "," das "," und "," von ",
    " le "," les "," des "," sur "," est "," par "]

EARNINGS_CALENDAR = {
    "SOFI": "2026-05-04", "GWRE": "2026-05-21", "PANW": "2026-05-26",
    "RKLB": "2026-05-08", "AMZN": "2026-05-01", "GD":   "2026-04-23",
    "MRSH": "2026-04-17", "AUR":  "2026-05-08",
}
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
    {"ticker": "NET",   "name": "Cloudflare",           "sector": "Cloud Security"},
    {"ticker": "PLTR",  "name": "Palantir",             "sector": "AI/Data Analytics"},
    {"ticker": "COIN",  "name": "Coinbase",             "sector": "Crypto Exchange"},
    {"ticker": "SHOP",  "name": "Shopify",              "sector": "E-commerce"},
    {"ticker": "ZS",    "name": "Zscaler",              "sector": "Cybersecurity"},
    {"ticker": "DDOG",  "name": "Datadog",              "sector": "Cloud Monitoring"},
]
CONSIDER_BUYING_UNIVERSE = [
    {"ticker": "PANW",  "name": "Palo Alto Networks",  "sector": "Cybersecurity"},
    {"ticker": "WYNN",  "name": "Wynn Resorts",         "sector": "Casino/Hospitality"},
    {"ticker": "CRWD",  "name": "CrowdStrike",          "sector": "Cybersecurity"},
    {"ticker": "AMZN",  "name": "Amazon",               "sector": "E-commerce/Cloud"},
    {"ticker": "GWRE",  "name": "Guidewire Software",   "sector": "InsurTech"},
    {"ticker": "SOFI",  "name": "SoFi Technologies",    "sector": "Fintech"},
    {"ticker": "RKLB",  "name": "Rocket Lab USA",       "sector": "Space"},
    {"ticker": "PLTR",  "name": "Palantir",             "sector": "AI/Analytics"},
    {"ticker": "COIN",  "name": "Coinbase",             "sector": "Crypto Exchange"},
    {"ticker": "NET",   "name": "Cloudflare",           "sector": "Cloud Security"},
    {"ticker": "SHOP",  "name": "Shopify",              "sector": "E-commerce"},
    {"ticker": "TTD",   "name": "The Trade Desk",       "sector": "AdTech"},
    {"ticker": "DDOG",  "name": "Datadog",              "sector": "Cloud Monitoring"},
    {"ticker": "UBER",  "name": "Uber",                 "sector": "Mobility"},
    {"ticker": "GD",    "name": "General Dynamics",     "sector": "Defense"},
]
# ─── MARKET MEMORY ────────────────────────────────────────────────────────────
MEMORY_FILE = "market_memory.json"

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Memory load error: {e}")
    return {"daily": [], "conviction_scores": {}}

def save_memory(memory):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f, indent=2)
    except Exception as e:
        logger.error(f"Memory save error: {e}")

def record_daily_verdict(cond, score, sp_chg, verdict_summary):
    memory = load_memory()
    today_str = datetime.now(EST).strftime("%Y-%m-%d")
    memory["daily"] = [d for d in memory["daily"] if d["date"] != today_str]
    memory["daily"].append({"date": today_str, "condition": cond, "score": score,
        "sp_change": round(sp_chg, 2), "verdict_summary": verdict_summary[:200], "outcome": None})
    memory["daily"] = memory["daily"][-30:]
    save_memory(memory)

def update_yesterday_outcome(sp_chg_today):
    memory = load_memory()
    if len(memory["daily"]) >= 2:
        yesterday = memory["daily"][-2]
        if yesterday.get("outcome") is None:
            yesterday["outcome"] = round(sp_chg_today, 2)
            yesterday["correct"] = (yesterday["condition"] in ["BULL","NEUTRAL"]) == (sp_chg_today >= 0)
            save_memory(memory)

def get_memory_context():
    memory = load_memory()
    daily = memory.get("daily", [])
    if not daily: return ""
    lines = ["Recent market history (last 5 days):"]
    for entry in daily[-5:]:
        outcome_str = ""
        if entry.get("outcome") is not None:
            correct = "✓ correct call" if entry.get("correct") else "✗ missed call"
            outcome_str = f" → S&P actually {entry['outcome']:+.2f}% ({correct})"
        lines.append(f"  {entry['date']}: {entry['condition']} (score {entry['score']}){outcome_str}")
    completed = [d for d in daily if d.get("outcome") is not None]
    if completed:
        correct_count = sum(1 for d in completed if d.get("correct"))
        lines.append(f"Recent accuracy: {correct_count}/{len(completed)} calls correct ({correct_count/len(completed)*100:.0f}%)")
    return "\n".join(lines)

def save_conviction_scores(scores_dict):
    memory = load_memory()
    today = datetime.now(EST).strftime("%Y-%m-%d")
    memory["conviction_scores"][today] = scores_dict
    keys = sorted(memory["conviction_scores"].keys())
    if len(keys) > 8:
        for old_key in keys[:-8]: del memory["conviction_scores"][old_key]
    save_memory(memory)

# ─── CLAUDE API ───────────────────────────────────────────────────────────────
async def ask_claude(prompt, system=None, max_tokens=600):
    if not ANTHROPIC_API_KEY: return None
    try:
        headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": "claude-haiku-4-5-20251001", "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system: body["system"] = system
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=30) as r:
                data = await r.json()
                if data.get("content"): return data["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Claude API error: {e}")
    return None

async def get_ai_morning_verdict(market_data):
    sp = market_data.get("sp500"); vix = market_data.get("vix_d")
    fut = market_data.get("futures"); tsy = market_data.get("treasury"); fg = market_data.get("fear_greed")
    sp_price  = f"${sp['price']:,.0f} ({sp['chg']:+.2f}%)" if sp else "unavailable"
    vix_val   = f"{vix['price']:.1f}" if vix else "unavailable"
    fut_chg   = f"{fut['chg']:+.2f}%" if fut else "unavailable"
    tsy_val   = f"{tsy['price']:.2f}%" if tsy else "unavailable"
    fg_val    = f"{int(fg['score'])} ({fg['rating']})" if fg else "unavailable"
    flags_str = "\n".join(f"- {t} {txt}" for t, txt in market_data.get("flags", []))
    holdings_str = ", ".join(f"{t} (avg ${i['avg_cost']})" for t, i in HOLDINGS.items() if t not in CRYPTO_MAP)
    todays_events = get_upcoming_econ_events(days_ahead=0)
    econ_str = ("Today's economic events: " + "; ".join(f"{e['event']} (exp {e['expected']}, prior {e['prior']})" for e in todays_events)) if todays_events else ""
    prompt = f"""You are a professional financial analyst writing a daily market outlook for Patrick, a private investor.
Today's data: S&P {sp_price} | VIX {vix_val} | Futures {fut_chg} | 10yr {tsy_val} | Fear&Greed {fg_val}
Condition: {market_data.get('cond','NEUTRAL')} (score {market_data.get('score',0)})
Signals:\n{flags_str}
{econ_str}
{get_memory_context()}
Holdings: {holdings_str}
Goal: $365,000 by end of 2026
Write a single paragraph (4-6 sentences) market outlook. Professional but conversational. Reference specific data. Mention 1-2 holdings if relevant. If important econ releases today, reference them. No bullets/headers/markdown. Don't say "Patrick" more than once. End with one clear actionable takeaway."""
    return await ask_claude(prompt, max_tokens=300)

async def get_ai_evening_wrap(market_data, prices_data, total_value, news_items):
    sp = market_data.get("sp500"); vix = market_data.get("vix_d")
    sp_chg = sp["chg"] if sp else 0; vix_v = vix["price"] if vix else 0
    movers = [f"{t} {((p-pv)/pv*100):+.1f}%" for t,i,p,pv in prices_data if p and pv and abs((p-pv)/pv*100) >= 1.5]
    headlines_str = "\n".join(f"- {n['title']}" for n in (news_items or [])[:5]) or "- No major headlines"
    tmrw = [e for e in get_upcoming_econ_events(days_ahead=1) if e["days"] == 1]
    tmrw_str = ("Tomorrow's events: " + "; ".join(f"{e['event']} (exp {e['expected']})" for e in tmrw)) if tmrw else ""
    prompt = f"""Evening market wrap for Patrick. Be his trusted advisor — direct, insightful, forward-looking.
S&P: {sp_chg:+.2f}% | Condition: {market_data.get('cond','NEUTRAL')} | VIX: {vix_v:.1f}
Portfolio movers: {', '.join(movers) if movers else 'No major moves'} | Total: ${total_value:,.0f} (goal $365k)
Headlines:\n{headlines_str}
{tmrw_str}
{get_memory_context()}
Write 2 short paragraphs:
1. What happened today — the story, what drove markets, what mattered for Patrick's portfolio.
2. What to watch tomorrow — 1-2 things. If econ releases tomorrow, name them with expected numbers.
No bullets, no headers, no markdown."""
    return await ask_claude(prompt, max_tokens=350)

async def get_ai_conviction_scores(prices_data, market_data):
    cond = market_data.get("cond","NEUTRAL"); score = market_data.get("score",0)
    lines = []
    for t, i, p, pv in prices_data:
        if not p: continue
        pl = ((p*i["shares"] - i["avg_cost"]*i["shares"]) / (i["avg_cost"]*i["shares"])) * 100
        dc = ((p-pv)/pv*100) if pv else 0
        lines.append(f"  {t} ({i['name']}): ${p:,.2f} | {pl:+.1f}% P&L | {dc:+.1f}% today")
    prompt = f"""Score each of Patrick's holdings 1-10 on conviction.
Market: {cond} (score {score})
Holdings:\n{chr(10).join(lines)}
8-10=Strong Hold/Add, 5-7=Neutral/Monitor, 1-4=Consider Reducing
Format (one per line, nothing else): TICKER|SCORE|One sentence reasoning"""
    result = await ask_claude(prompt, max_tokens=400)
    if not result: return {}
    scores = {}
    for line in result.strip().split("\n"):
        parts = line.strip().split("|")
        if len(parts) == 3:
            try: scores[parts[0].strip().upper()] = {"score": int(parts[1].strip()), "reasoning": parts[2].strip()}
            except: continue
    return scores

async def get_ai_portfolio_coaching(prices_data, total_value, market_data, period="weekly"):
    cond = market_data.get("cond","NEUTRAL"); score = market_data.get("score",0)
    lines = []; total_cost = 0
    for t, i, p, pv in prices_data:
        if not p: continue
        cost = i["avg_cost"]*i["shares"]; value = p*i["shares"]; total_cost += cost
        lines.append(f"  {t}: ${p:,.2f} | {((value-cost)/cost*100):+.1f}% P&L | ${value:,.0f}")
    total_pl = ((total_value-total_cost)/total_cost*100) if total_cost > 0 else 0
    gap = max(365000-total_value, 0); months_left = max(1, 12-datetime.now(EST).month+1)
    timing = "week ahead" if period == "monday" else "week in review"
    tone = "Set the tone for the week. Be motivating but honest." if period == "monday" else "Reflect on what happened. Be direct about what worked and what didn't."
    prompt = f"""Patrick's portfolio coach writing a {timing} assessment.
Portfolio:\n{chr(10).join(lines)}
Total: ${total_value:,.0f} | P&L: {total_pl:+.1f}% | Goal gap: ${gap:,.0f} | Months left: {months_left}
Market: {cond} (score {score})
{get_memory_context()}
Write 4-5 sentences: assess portfolio health honestly, call out 1-2 positions needing attention, give clear conservative/aggressive guidance, tie to $365k goal.
{tone} Conversational, no bullets, no markdown."""
    return await ask_claude(prompt, max_tokens=300)

async def get_ai_consider_buying(ticker, name, sector, price, rsi, drawdown, sma20, sma50, macd_signal, news_headlines, insider_buy=False):
    headlines_str = "\n".join(f"- {h}" for h in news_headlines) or "- No recent headlines"
    prompt = f"""Evaluate whether {name} ({ticker}) — {sector} is worth buying now.
Price: ${price:,.2f} | RSI: {rsi} | Down {drawdown:.1f}% from 52w high
vs SMA20: {'above' if price > sma20 else 'below'} (${sma20:,.2f}) | vs SMA50: {'above' if price > sma50 else 'below'} (${sma50:,.2f})
MACD: {macd_signal} | Insider buying: {'Yes' if insider_buy else 'No'}
News:\n{headlines_str}
Write 3-4 sentence "Consider Buying" alert for Patrick. Direct — why compelling, what's the risk, what price matters. End with: LOW, MEDIUM, or HIGH conviction."""
    return await ask_claude(prompt, max_tokens=250)

async def get_ai_ask_response(question, market_data, portfolio_prices):
    total_value = 0; lines = []
    for t, i, p, pv in portfolio_prices:
        if p:
            v = p*i["shares"]; total_value += v; cost = i["avg_cost"]*i["shares"]
            lines.append(f"  {t}: ${p:,.2f} | {((v-cost)/cost*100):+.1f}% P&L | ${v:,.0f}")
    sp = market_data.get("sp500"); vix = market_data.get("vix_d")
    system = "You are Patrick's personal AI investment advisor. Give direct, honest, actionable answers. Conversational but professional. No generic disclaimers — real analysis. 3-5 sentences max. Always factor in his specific holdings and $365k goal."
    prompt = f"""Patrick's question: "{question}"
Market: {market_data.get('cond','NEUTRAL')} (score {market_data.get('score',0)}) | S&P: {"${:,.0f} ({:+.2f}%)".format(sp['price'],sp['chg']) if sp else "n/a"} | VIX: {f"{vix['price']:.1f}" if vix else "n/a"}
Date: {datetime.now(EST).strftime('%A, %B %d, %Y')}
Portfolio (total ~${total_value:,.0f}):\n{chr(10).join(lines)}
Goal: $365,000 by end of 2026 — gap: ${max(365000-total_value,0):,.0f}
{get_memory_context()}
Answer his question directly."""
    return await ask_claude(prompt, system=system, max_tokens=400)

async def get_ai_move_explanation(ticker, name, move_pct, direction, news_headlines, market_chg):
    headlines_str = "\n".join(f"- {h}" for h in news_headlines) or "- No headlines found"
    prompt = f"""Explain in 2-3 sentences why {name} ({ticker}) is {'up' if move_pct > 0 else 'down'} {abs(move_pct):.1f}% today.
S&P 500 is {market_chg:+.2f}% today. This move is {'with' if (move_pct>0)==(market_chg>0) else 'against'} the market.
News: {headlines_str}
Be direct. If no specific catalyst, say so clearly. No bullets."""
    return await ask_claude(prompt, max_tokens=150)
# ─── HELPERS & PRICE FETCHING ─────────────────────────────────────────────────
def is_trusted_english(title, source="", url=""):
    if not title: return False
    if sum(1 for c in title if ord(c) > 127) > len(title) * 0.05: return False
    if any(kw in title.lower() for kw in NON_ENGLISH_KEYWORDS): return False
    src, u = source.lower(), url.lower()
    return any(s in src or s in u for s in TRUSTED_SOURCES)

def is_market_open():
    now = datetime.now(EST)
    return now.weekday() < 5 and time(9, 30) <= now.time() <= time(16, 0)

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
        period = "3mo" if days <= 90 else "6mo" if days <= 180 else "1y"
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
            return {"price": current, "chg": ((current-prev)/prev)*100, "high_30d": max(closes), "closes": closes}
    except Exception as e:
        logger.error(f"Index fetch error {ticker}: {e}")
    return None

# ─── INDICATORS ───────────────────────────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period+1: return None
    deltas = [prices[i+1]-prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]; losses = [-d if d < 0 else 0 for d in deltas]
    ag = sum(gains[:period])/period; al = sum(losses[:period])/period
    if al == 0: return 100.0
    for i in range(period, len(deltas)):
        ag = (ag*(period-1)+gains[i])/period; al = (al*(period-1)+losses[i])/period
    return round(100-(100/(1+ag/al)), 1) if al != 0 else 100.0

def calc_sma(prices, period):
    if len(prices) < period: return None
    return round(sum(prices[-period:])/period, 2)

def calc_macd(prices):
    if len(prices) < MA_SLOW+MA_SIGNAL: return None, None, None
    kf, ks = 2/(MA_FAST+1), 2/(MA_SLOW+1)
    ef = sum(prices[:MA_FAST])/MA_FAST; es = sum(prices[:MA_SLOW])/MA_SLOW
    fv, sv = [], []
    for i, p in enumerate(prices):
        if i >= MA_FAST: ef = p*kf+ef*(1-kf); fv.append(ef)
        if i >= MA_SLOW: es = p*ks+es*(1-ks); sv.append(es)
    ml = min(len(fv), len(sv))
    macd_line = [fv[-(ml-i)]-sv[-(ml-i)] for i in range(ml)]
    if len(macd_line) < MA_SIGNAL: return None, None, None
    ks2 = 2/(MA_SIGNAL+1); sig = sum(macd_line[:MA_SIGNAL])/MA_SIGNAL
    for v in macd_line[MA_SIGNAL:]: sig = v*ks2+sig*(1-ks2)
    mv = macd_line[-1]
    return round(mv,4), round(sig,4), round(mv-sig,4)

async def get_market_score(session):
    sp500=await fetch_index(session,"^GSPC"); nasdaq=await fetch_index(session,"^IXIC")
    dow=await fetch_index(session,"^DJI"); vix_d=await fetch_index(session,"^VIX")
    treasury=await fetch_index(session,"^TNX"); dxy=await fetch_index(session,"DX-Y.NYB")
    futures=await fetch_index(session,"ES=F")
    await asyncio.sleep(0.5)
    score=0; flags=[]
    if sp500 and len(sp500["closes"]) >= 20:
        sma20 = sum(sp500["closes"][-20:])/20
        if sp500["price"] > sma20: score+=2; flags.append(("✅","S&P 500 above its 20-day moving average — uptrend intact"))
        else: score-=2; flags.append(("⚠️","S&P 500 below its 20-day moving average — short-term trend broken"))
        drawdown = ((sp500["high_30d"]-sp500["price"])/sp500["high_30d"])*100
        if drawdown > 10: score-=2; flags.append(("⚠️",f"S&P is {drawdown:.1f}% off its 30-day high — meaningful pullback"))
        elif drawdown < 3: score+=1; flags.append(("✅",f"S&P within {drawdown:.1f}% of 30-day high — strength confirmed"))
    if vix_d:
        v=vix_d["price"]
        if v < 15: score+=2; flags.append(("✅",f"VIX {v:.1f} — very low fear, calm conditions"))
        elif v < 20: score+=1; flags.append(("✅",f"VIX {v:.1f} — normal trading environment"))
        elif v < 25: score-=1; flags.append(("⚠️",f"VIX {v:.1f} — elevated volatility, traders cautious"))
        elif v < 30: score-=2; flags.append(("🔴",f"VIX {v:.1f} — high fear, proceed carefully"))
        else: score-=3; flags.append(("🔴",f"VIX {v:.1f} — extreme fear, risk-off environment"))
    if futures:
        fc=futures["chg"]
        if fc > 0.5: score+=1; flags.append(("✅",f"Futures up {fc:.2f}% — positive overnight sentiment"))
        elif fc < -0.5: score-=1; flags.append(("⚠️",f"Futures down {fc:.2f}% — overnight selling pressure"))
        else: flags.append(("➡️",f"Futures flat ({fc:+.2f}%) — no strong directional bias"))
    if treasury:
        ty=treasury["price"]
        if ty > 4.5: score-=1; flags.append(("⚠️",f"10yr yield {ty:.2f}% — elevated rates pressuring equities"))
        elif ty < 4.0: score+=1; flags.append(("✅",f"10yr yield {ty:.2f}% — rates supportive for equities"))
        else: flags.append(("➡️",f"10yr yield {ty:.2f}% — rates neutral"))
    if score>=4: cond,c_color,c_bg,c_emoji="BULL","#1a7a4a","#e8f5ee","🟢"
    elif score>=1: cond,c_color,c_bg,c_emoji="NEUTRAL","#a06a10","#fef6e4","🟡"
    elif score>=-2: cond,c_color,c_bg,c_emoji="CAUTION","#b83232","#fceaea","🔴"
    else: cond,c_color,c_bg,c_emoji="BEAR","#7a0000","#ffe8e8","💀"
    return {"score":score,"flags":flags,"cond":cond,"c_color":c_color,"c_bg":c_bg,"c_emoji":c_emoji,
            "sp500":sp500,"nasdaq":nasdaq,"dow":dow,"vix_d":vix_d,"treasury":treasury,"dxy":dxy,"futures":futures}

async def get_fear_greed():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                             headers={"User-Agent":"Mozilla/5.0"}, timeout=10) as r:
                data = await r.json()
                return {"score": float(data["fear_and_greed"]["score"]), "rating": data["fear_and_greed"]["rating"]}
    except Exception as e: logger.error(f"Fear & Greed error: {e}")
    return None

def fg_emoji(s):
    return "💀" if s<=25 else "😨" if s<=45 else "😐" if s<=55 else "😊" if s<=75 else "🤑"
def fg_color(s):
    return "#7a0000" if s<=25 else "#b83232" if s<=45 else "#a06a10" if s<=55 else "#1a7a4a" if s<=75 else "#0d5c38"
def fg_plain_english(score, rating):
    if score<=25: return f"Extreme Fear ({int(score)}/100) — investors are panic-selling. Historically a contrarian opportunity, but confirm with your own signals first."
    elif score<=45: return f"Fear ({int(score)}/100) — sentiment is negative, cautious money is on the sidelines."
    elif score<=55: return f"Neutral ({int(score)}/100) — market isn't strongly leaning either way."
    elif score<=75: return f"Greed ({int(score)}/100) — optimism is building. Be selective about chasing here."
    else: return f"Extreme Greed ({int(score)}/100) — euphoria in the air. This level historically precedes pullbacks."

async def get_treasury_yields():
    try:
        async with aiohttp.ClientSession() as s:
            tickers = {"2yr":"^IRX","5yr":"^FVX","10yr":"^TNX","30yr":"^TYX"}
            yields = {}
            for name, ticker in tickers.items():
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
                async with s.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10) as r:
                    data = await r.json()
                    closes = [c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                    if closes: yields[name] = round(closes[-1], 3)
                await asyncio.sleep(0.2)
            return yields
    except Exception as e: logger.error(f"Treasury yields error: {e}")
    return {}

def treasury_plain_english(yields):
    lines = []; t10=yields.get("10yr"); t2=yields.get("2yr")
    if t10:
        if t10>4.5: lines.append(f"The 10-year Treasury is at {t10:.2f}% — elevated, keeping pressure on growth stocks.")
        elif t10<4.0: lines.append(f"The 10-year yield sits at {t10:.2f}% — supportive for equities and growth names.")
        else: lines.append(f"The 10-year yield is at {t10:.2f}% — neutral, not a major headwind or tailwind.")
    if t2 and t10:
        if t10-t2 < 0: lines.append(f"Yield curve inverted (2yr {t2:.2f}% vs 10yr {t10:.2f}%) — historical recession signal.")
        else: lines.append(f"Yield curve positively sloped (2yr {t2:.2f}% vs 10yr {t10:.2f}%) — healthier signal.")
    return " ".join(lines)

async def get_news(session, query, max_articles=3):
    try:
        url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize=10&language=en&apiKey={NEWS_API_KEY}"
        async with session.get(url, timeout=10) as r:
            data = await r.json(); articles = []
            for a in data.get("articles", []):
                title=a.get("title",""); source=a.get("source",{}).get("name",""); url_a=a.get("url","")
                if url_a in seen_news: continue
                if not is_trusted_english(title, source, url_a): continue
                seen_news.add(url_a)
                articles.append({"title":title,"source":source,"url":url_a,"description":(a.get("description") or "")[:120]})
                if len(articles) >= max_articles: break
            return articles
    except Exception as e: logger.error(f"News fetch error {query}: {e}")
    return []

async def collect_news():
    async with aiohttp.ClientSession() as session:
        for ticker in NEWS_TICKERS:
            current = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            prev = None if ticker in CRYPTO_MAP else await get_prev_close(session, ticker)
            articles = await get_news(session, ticker, max_articles=2)
            for a in articles:
                if a["url"] in [n["url"] for n in daily_news_cache]: continue
                move_pct = ((current-prev)/prev*100) if current and prev else 0
                daily_news_cache.append({"ticker":ticker,"title":a["title"],"source":a["source"],
                    "url":a["url"],"move_pct":move_pct,"direction":"📈" if move_pct>0 else "📉"})
            await asyncio.sleep(0.5)

def get_upcoming_earnings(days_ahead=7):
    today = datetime.now(EST).date(); upcoming = []
    for ticker, date_str in EARNINGS_CALENDAR.items():
        try:
            ed = datetime.strptime(date_str, "%Y-%m-%d").date(); days_away = (ed-today).days
            if 0 <= days_away <= days_ahead:
                upcoming.append({"ticker":ticker,"date":ed.strftime("%b %d"),"days":days_away})
        except: continue
    return sorted(upcoming, key=lambda x: x["days"])

async def get_all_prices(session):
    prices_data=[]; total_value=0
    for ticker, info in HOLDINGS.items():
        price = await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
        prev = None if ticker in CRYPTO_MAP else await get_prev_close(session, ticker)
        if price: total_value += price*info["shares"]
        prices_data.append((ticker, info, price, prev))
    return prices_data, total_value
# ─── TELEGRAM & EMAIL ─────────────────────────────────────────────────────────
async def send_message(text):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.error(f"Telegram send error: {e}")

async def send_email(subject, html_body):
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative"); msg["Subject"]=subject; msg["From"]=EMAIL_FROM; msg["To"]=EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD); server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logger.info(f"Email sent: {subject}")
    except Exception as e: logger.error(f"Email send error: {e}")

def email_header(title, subtitle):
    return (f'<tr><td style="background:#0f0f14;padding:24px 32px;">'
            f'<div style="font-size:11px;font-family:monospace;letter-spacing:0.15em;color:#555;text-transform:uppercase;margin-bottom:5px;">Patrick Portfolio Bot</div>'
            f'<div style="font-size:22px;font-weight:700;color:#e8c96e;letter-spacing:-0.3px;">{title}</div>'
            f'<div style="font-size:13px;color:#666;margin-top:4px;">{subtitle}</div></td></tr>')

def email_section(label, content, bg="#ffffff"):
    return (f'<tr><td style="background:{bg};padding:20px 32px;border-bottom:1px solid #f0f0f0;">'
            f'<div style="font-size:10px;font-family:monospace;letter-spacing:0.12em;color:#aaa;text-transform:uppercase;margin-bottom:10px;">{label}</div>'
            f'<div style="font-size:14px;color:#1a1a1a;line-height:1.8;">{content}</div></td></tr>')

def email_footer(note=""):
    return (f'<tr><td style="background:#fafafa;padding:14px 32px;text-align:center;border-top:1px solid #f0f0f0;">'
            f'<div style="font-size:11px;color:#bbb;font-family:monospace;">Not financial advice · Patrick Portfolio Bot · {datetime.now(EST).strftime("%b %d, %Y")}{" · "+note if note else ""}</div></td></tr>')

def wrap_email(rows):
    return (f'<html><body style="margin:0;padding:0;background:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;padding:28px 16px;"><tr><td align="center">'
            f'<table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1);">'
            f'{rows}</table></td></tr></table></body></html>')

def idx_row_html(name, data, invert=False):
    if not data: return f'<tr><td colspan="3" style="padding:7px 10px;font-size:12px;color:#999;">{name} — unavailable</td></tr>'
    chg=data["chg"]; color=("#b83232" if chg>=0 else "#1a7a4a") if invert else ("#1a7a4a" if chg>=0 else "#b83232")
    arrow="▲" if chg>=0 else "▼"
    return (f'<tr><td style="padding:7px 10px;font-size:13px;font-weight:500;border-bottom:1px solid #f5f5f5;">{name}</td>'
            f'<td style="padding:7px 10px;font-size:13px;border-bottom:1px solid #f5f5f5;">{data["price"]:,.2f}</td>'
            f'<td style="padding:7px 10px;font-size:13px;font-weight:500;color:{color};border-bottom:1px solid #f5f5f5;">{arrow} {abs(chg):.2f}%</td></tr>')

def index_table_html(ms):
    hdr=('<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;"><tr style="background:#f8f8f8;">'
         '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Index</th>'
         '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Level</th>'
         '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Change</th></tr>')
    rows=(idx_row_html("S&P 500",ms["sp500"])+idx_row_html("Nasdaq",ms["nasdaq"])+idx_row_html("Dow Jones",ms["dow"])+
          idx_row_html("S&P Futures",ms["futures"])+idx_row_html("VIX",ms["vix_d"],invert=True)+
          idx_row_html("10-yr Treasury",ms["treasury"],invert=True)+idx_row_html("Dollar (DXY)",ms["dxy"],invert=True))
    return hdr+rows+"</table>"

def portfolio_table_html(prices_data):
    rows=""
    for ticker, info, price, prev in prices_data:
        if not price: continue
        value=price*info["shares"]; cost=info["avg_cost"]*info["shares"]
        total_pl=((value-cost)/cost)*100; pl_color="#1a7a4a" if total_pl>=0 else "#b83232"
        if prev:
            dc=((price-prev)/prev)*100; day_str=f"+{dc:.1f}%" if dc>=0 else f"{dc:.1f}%"; day_col="#1a7a4a" if dc>=0 else "#b83232"
        else: day_str,day_col="—","#999"
        rows+=(f'<tr><td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-weight:600;font-size:13px;">{ticker}</td>'
               f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:12px;color:#666;">{info["name"]}</td>'
               f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;text-align:right;">${price:,.2f}</td>'
               f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;text-align:right;color:{day_col};font-weight:500;">{day_str}</td>'
               f'<td style="padding:8px 10px;border-bottom:1px solid #f5f5f5;font-size:13px;text-align:right;color:{pl_color};">{total_pl:+.1f}%</td></tr>')
    return ('<table width="100%" cellpadding="0" cellspacing="0"><tr style="background:#f8f8f8;">'
            '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Ticker</th>'
            '<th style="padding:7px 10px;text-align:left;font-size:11px;color:#999;font-weight:500;">Name</th>'
            '<th style="padding:7px 10px;text-align:right;font-size:11px;color:#999;font-weight:500;">Price</th>'
            '<th style="padding:7px 10px;text-align:right;font-size:11px;color:#999;font-weight:500;">Day</th>'
            '<th style="padding:7px 10px;text-align:right;font-size:11px;color:#999;font-weight:500;">Total P&L</th></tr>'+rows+'</table>')

def conviction_scores_html(scores):
    if not scores: return '<div style="color:#999;font-size:13px;">Conviction scores unavailable today.</div>'
    rows=""
    for ticker, data in scores.items():
        s=data["score"]
        if s>=8: sc,sb,sl="#166534","#f0fff4","Strong Hold/Add"
        elif s>=6: sc,sb,sl="#a06a10","#fef6e4","Neutral/Monitor"
        elif s>=4: sc,sb,sl="#b83232","#fff0f0","Watch Closely"
        else: sc,sb,sl="#7a0000","#ffe8e8","Consider Reducing"
        rows+=(f'<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;">'
               f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
               f'<span style="font-weight:600;font-size:13px;">{ticker}</span>'
               f'<span style="background:{sb};color:{sc};font-size:12px;font-weight:700;padding:3px 10px;border-radius:4px;">{s}/10 — {sl}</span></div>'
               f'<div style="background:#f0f0f0;border-radius:3px;height:4px;margin-bottom:6px;overflow:hidden;">'
               f'<div style="background:{sc};height:100%;width:{s*10}%;border-radius:3px;"></div></div>'
               f'<div style="font-size:12px;color:#555;line-height:1.5;">{data["reasoning"]}</div></div>')
    return rows or '<div style="color:#999;font-size:13px;">No scores available.</div>'

def goal_bar_html(total_value, goal=365000):
    pct=min((total_value/goal)*100, 100); gap=max(goal-total_value, 0)
    return (f'<div style="font-size:24px;font-weight:700;color:#e8a030;">${total_value:,.0f}</div>'
            f'<div style="font-size:13px;color:#888;margin-bottom:8px;">{pct:.1f}% of $365k goal</div>'
            f'<div style="background:#f0f0f0;border-radius:4px;height:8px;overflow:hidden;margin-bottom:8px;">'
            f'<div style="background:#e8a030;height:100%;width:{int(pct)}%;border-radius:4px;"></div></div>'
            f'<div style="font-size:12px;color:#999;">Gap to goal: ${gap:,.0f}</div>')

def news_html_block(items, max_items=5):
    if not items: return '<div style="color:#999;font-size:13px;font-style:italic;">No relevant news from trusted sources today.</div>'
    html=""; seen=set(); count=0
    for item in items:
        if count>=max_items: break
        if item["url"] in seen: continue
        seen.add(item["url"]); count+=1
        badge=""
        if abs(item.get("move_pct",0)) >= 3:
            mc="#1a7a4a" if item["move_pct"]>0 else "#b83232"
            badge=f'<span style="background:{mc};color:#fff;font-size:10px;padding:2px 7px;border-radius:3px;margin-left:6px;">{item["direction"]}{abs(item["move_pct"]):.1f}%</span>'
        tl=f'<span style="font-size:11px;font-weight:700;color:#e8a030;">{item.get("ticker","")}</span>{badge}' if item.get("ticker") else ""
        html+=(f'<div style="padding:10px 0;border-bottom:1px solid #f5f5f5;"><div style="margin-bottom:4px;">{tl}</div>'
               f'<div style="font-size:13px;color:#1a1a1a;margin-bottom:4px;line-height:1.5;">{item["title"]}</div>'
               f'<div style="font-size:11px;color:#999;">{item["source"]} &nbsp;·&nbsp; <a href="{item["url"]}" style="color:#5b9cf6;text-decoration:none;">Read →</a></div></div>')
    return html
# ─── MORNING EMAIL ────────────────────────────────────────────────────────────
async def send_morning_email():
    logger.info("Sending morning market outlook email...")
    async with aiohttp.ClientSession() as session:
        ms=await get_market_score(session); fg=await get_fear_greed(); yields=await get_treasury_yields()
        ms["fear_greed"]=fg
        overnight_news=await get_news(session, "stock market economy", max_articles=4)
        holdings_news=[]
        for ticker in ["RKLB","AMZN","GWRE","SOFI","GD"]:
            for a in await get_news(session, ticker, max_articles=1):
                a["ticker"]=ticker; holdings_news.append(a)
        ai_verdict=await get_ai_morning_verdict(ms)
        fallback={"BULL":"Market conditions look constructive heading into today's session. Momentum is on the side of the bulls — trend intact, volatility contained, no major macro pressure.",
                  "NEUTRAL":"The market is sending mixed signals today. Focus on your highest-conviction ideas only and keep position sizing in check.",
                  "CAUTION":"Conditions have shifted to cautious today. Hold existing positions and resist the urge to add until the market shows stabilization.",
                  "BEAR":"This is a risk-off day. Multiple signals are flashing red. Capital preservation takes priority."}
        verdict_text=ai_verdict if ai_verdict else fallback.get(ms["cond"],"")
        sp_chg=ms["sp500"]["chg"] if ms["sp500"] else 0
        record_daily_verdict(ms["cond"], ms["score"], sp_chg, verdict_text[:200])
        verdict_html=(f'<div style="background:{ms["c_bg"]};border-left:4px solid {ms["c_color"]};border-radius:0 8px 8px 0;padding:16px 18px;font-size:14px;color:#1a1a1a;line-height:1.8;">{verdict_text}</div>')
        if ai_verdict: verdict_html+='<div style="font-size:11px;color:#bbb;margin-top:6px;font-family:monospace;">✦ AI-generated outlook</div>'
        date_str=datetime.now(EST).strftime("%A, %B %d, %Y"); date_short=datetime.now(EST).strftime("%a %b %d"); time_str=datetime.now(EST).strftime("%I:%M %p EST")
        condition_banner=(f'<tr><td style="background:{ms["c_bg"]};padding:18px 32px;border-bottom:3px solid {ms["c_color"]};">'
            f'<div style="font-size:10px;font-family:monospace;letter-spacing:0.12em;color:{ms["c_color"]};text-transform:uppercase;margin-bottom:5px;">Today\'s Market Condition</div>'
            f'<div style="font-size:28px;font-weight:800;color:{ms["c_color"]};letter-spacing:-0.5px;">{ms["c_emoji"]} {ms["cond"]}</div>'
            f'<div style="font-size:12px;color:{ms["c_color"]};margin-top:3px;opacity:0.8;">Score: {"+" if ms["score"]>0 else ""}{ms["score"]} · {len(ms["flags"])} signals</div></td></tr>')
        signals_html="".join(f'<div style="padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;color:#333;"><span style="margin-right:8px;">{icon}</span>{text}</div>' for icon,text in ms["flags"])
        fg_html=""
        if fg:
            fgc=fg_color(fg["score"])
            fg_html=(f'<div style="display:flex;align-items:center;gap:16px;background:#f8f8f8;border-radius:8px;padding:14px 16px;">'
                     f'<div style="font-size:32px;font-weight:800;color:{fgc};">{fg_emoji(fg["score"])} {int(fg["score"])}</div>'
                     f'<div style="font-size:13px;color:#333;line-height:1.6;">{fg_plain_english(fg["score"],fg["rating"])}</div></div>')
        treasury_text=treasury_plain_english(yields)
        treasury_html=f'<div style="font-size:13px;color:#333;line-height:1.8;margin-bottom:10px;">{treasury_text}</div>'
        if yields:
            treasury_html+='<div style="margin-top:6px;">'+''.join(
                f'<span style="display:inline-block;background:#f0f0f0;border-radius:4px;padding:4px 10px;font-size:12px;font-family:monospace;margin:3px 4px 3px 0;color:{"#b83232" if v>=TREASURY_ALERT_THRESHOLD else "#333"};">{k.upper()} {v:.2f}%</span>'
                for k,v in yields.items())+'</div>'
        upcoming=get_upcoming_earnings(days_ahead=5)
        if upcoming:
            def _days_label(d): return "Today" if d==0 else "Tomorrow" if d==1 else f"In {d} days"
            earnings_html="".join(f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f5f5f5;font-size:13px;"><span style="font-weight:600;">{e["ticker"]}</span><span style="color:#555;">{e["date"]}</span><span style="color:#e8a030;">{_days_label(e["days"])}</span></div>' for e in upcoming)
        else: earnings_html='<div style="font-size:13px;color:#999;">No earnings from your holdings this week.</div>'
        targets_html=('<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            '<span style="background:#fff0f0;color:#b83232;border:0.5px solid #fca5a5;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">RKLB $100 TRIM</span>'
            '<span style="background:#f0fff4;color:#166534;border:0.5px solid #86efac;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">GWRE $158 ADD</span>'
            '<span style="background:#f0fff4;color:#166534;border:0.5px solid #86efac;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">PANW $160 BUY</span>'
            '<span style="background:#f0fff4;color:#166534;border:0.5px solid #86efac;border-radius:5px;padding:5px 10px;font-size:12px;font-family:monospace;">WYNN $90 BUY</span></div>')
        rows=(email_header(f"{ms['c_emoji']} Daily Market Outlook",f"{date_str} · {time_str}")+condition_banner+
              email_section("Today's Verdict",verdict_html)+email_section("Signal Breakdown",signals_html)+
              email_section("Market Indices",index_table_html(ms))+email_section("Sentiment — Fear & Greed",fg_html)+
              email_section("Treasury Yields",treasury_html)+
              email_section("Economic Calendar — Next 7 Days",econ_calendar_html(days_ahead=7))+
              email_section("Earnings This Week",earnings_html)+
              (email_section("Overnight & Morning News",news_html_block([{**a,"ticker":""} for a in overnight_news])) if overnight_news else "")+
              (email_section("News on Your Holdings",news_html_block(holdings_news)) if holdings_news else "")+
              email_section("Your Active Targets",targets_html,bg="#fafafa")+email_footer())
        await send_email(f"{ms['c_emoji']} Market Outlook — {ms['cond']} · {date_short}", wrap_email(rows))
        logger.info(f"Morning email sent — {ms['cond']} {'(AI)' if ai_verdict else '(fallback)'}")
        await send_morning_brief_telegram(ms)

async def send_morning_brief_telegram(ms=None):
    async with aiohttp.ClientSession() as session:
        lines=["☀️ *MORNING BRIEF*",f"📅 {datetime.now(EST).strftime('%A, %b %d · %I:%M %p EST')}","─"*30]
        total_value=0
        for ticker, info in HOLDINGS.items():
            price=await get_crypto_price(session, CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session, ticker)
            if price:
                value=price*info["shares"]; total_value+=value
                lines.append(f"📌 *{ticker}* — ${price:,.2f} | ${value:,.0f}")
        lines+=["─"*30,f"💼 *Portfolio:* ${total_value:,.0f}"]
        if ms: lines.append(f"📊 *Market:* {ms['c_emoji']} {ms['cond']}")
        lines+=["─"*30,"⚡ _RKLB $100 · GWRE $158 · PANW $160 · WYNN $90_"]
        econ_block=econ_calendar_telegram(days_ahead=2)
        if econ_block: lines+=["─"*30, econ_block]
        await send_message("\n".join(lines))
        await asyncio.sleep(3)
        await send_sleeper_pick(session)

# ─── EVENING EMAIL ────────────────────────────────────────────────────────────
async def send_evening_email():
    logger.info("Sending evening wrap email...")
    async with aiohttp.ClientSession() as session:
        prices_data,total_value=await get_all_prices(session)
        ms=await get_market_score(session); yields=await get_treasury_yields()
        sp_chg=ms["sp500"]["chg"] if ms["sp500"] else 0
        update_yesterday_outcome(sp_chg)
        tom_str=(datetime.now(EST)+timedelta(days=1)).strftime("%A, %B %d")
        tom_earnings=[e for e in get_upcoming_earnings(days_ahead=3) if e["days"]<=2]
        date_str=datetime.now(EST).strftime("%A, %B %d, %Y"); date_short=datetime.now(EST).strftime("%a %b %d")
        ai_wrap=await get_ai_evening_wrap(ms, prices_data, total_value, daily_news_cache[:10])
        if ai_wrap:
            paragraphs=ai_wrap.split("\n\n")
            if len(paragraphs)>=2:
                day_review_html=(f'<div style="font-size:14px;color:#333;line-height:1.8;margin-bottom:12px;">{paragraphs[0]}</div>'
                    f'<div style="font-size:14px;color:#555;line-height:1.8;background:#f8f8f8;border-radius:8px;padding:14px 16px;border-left:3px solid #e8a030;">'
                    f'<div style="font-size:10px;font-family:monospace;color:#aaa;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">What to watch tomorrow</div>'
                    f'{paragraphs[1]}</div><div style="font-size:11px;color:#bbb;margin-top:6px;font-family:monospace;">✦ AI-generated wrap</div>')
            else: day_review_html=f'<div style="font-size:14px;color:#333;line-height:1.8;">{ai_wrap}</div><div style="font-size:11px;color:#bbb;margin-top:6px;font-family:monospace;">✦ AI-generated wrap</div>'
        else:
            if sp_chg>=1.0: fb=f"A solid session — the S&P finished up {sp_chg:.2f}%, bulls maintained control."
            elif sp_chg>=0: fb=f"A quiet, slightly positive session. The S&P edged up {sp_chg:.2f}%."
            elif sp_chg>=-1.0: fb=f"A modestly negative day — the S&P slipped {abs(sp_chg):.2f}%. Nothing alarming."
            else: fb=f"A rough session — the S&P sold off {abs(sp_chg):.2f}%. Worth monitoring overnight sentiment."
            day_review_html=f'<div style="font-size:14px;color:#333;line-height:1.8;">{fb}</div>'
        conv_scores=await get_ai_conviction_scores(prices_data, ms)
        if conv_scores: save_conviction_scores(conv_scores)
        conv_html=conviction_scores_html(conv_scores)
        tom_html=f'<div style="font-size:13px;color:#333;line-height:1.8;margin-bottom:12px;">On the radar for <strong>{tom_str}</strong>:</div>'
        if tom_earnings:
            tom_html+='<div style="font-size:12px;font-weight:600;color:#e8a030;margin-bottom:6px;">EARNINGS</div>'
            for e in tom_earnings:
                tom_html+=(f'<div style="padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;display:flex;justify-content:space-between;">'
                           f'<span style="font-weight:600;">{e["ticker"]}</span><span style="color:#888;">{e["date"]}</span>'
                           f'<span style="color:#e8a030;">{"Tomorrow" if e["days"]==1 else "In 2 days"}</span></div>')
        tom_html+='<div style="font-size:12px;font-weight:600;color:#888;margin:12px 0 6px;">ECONOMIC DATA</div>'+econ_calendar_html(days_ahead=2)
        rows=(email_header("📊 Evening Market Wrap",f"{date_str} · 5:00pm EST")+email_section("Day in Review",day_review_html)+
              email_section("Closing Indices",index_table_html(ms))+email_section("Your Portfolio — Close",portfolio_table_html(prices_data))+
              email_section("Conviction Scores — All Holdings",conv_html)+email_section("Goal Progress",goal_bar_html(total_value))+
              email_section("Today's News",news_html_block(daily_news_cache, max_items=5))+email_section("Looking Ahead",tom_html)+email_footer())
        await send_email(f"📊 Evening Wrap — {date_short}", wrap_email(rows))
        daily_news_cache.clear()
        logger.info(f"Evening email sent {'(AI wrap)' if ai_wrap else '(fallback wrap)'}")
# ─── MONDAY EMAIL ────────────────────────────────────────────────────────────
async def send_monday_email():
    logger.info("Sending Monday week ahead email...")
    async with aiohttp.ClientSession() as session:
        ms=await get_market_score(session); fg=await get_fear_greed(); yields=await get_treasury_yields()
        prices_data,total_value=await get_all_prices(session)
        date_str=datetime.now(EST).strftime("%A, %B %d, %Y"); date_short=datetime.now(EST).strftime("%a %b %d")
        score=ms["score"]
        if score>=3: wo="The week is setting up constructively. Momentum heading into Monday is positive and the macro backdrop isn't throwing up major red flags."
        elif score>=0: wo="The week ahead looks mixed. Discipline matters more than ever — stick to your plan, focus on names where the setup is clear."
        else: wo="Heading into this week with some caution warranted. Let price action confirm before committing capital. Don't force entries."
        ai_coaching=await get_ai_portfolio_coaching(prices_data, total_value, ms, period="monday")
        coaching_html=(f'<div style="background:#f8f8f8;border-left:4px solid #e8a030;border-radius:0 8px 8px 0;padding:16px 18px;font-size:14px;color:#1a1a1a;line-height:1.8;">{ai_coaching}</div>'
                       f'<div style="font-size:11px;color:#bbb;margin-top:6px;font-family:monospace;">✦ AI portfolio coach</div>') if ai_coaching else '<div style="color:#999;font-size:13px;">Portfolio coaching unavailable today.</div>'
        indicators_html=""
        if ms["sp500"] and len(ms["sp500"]["closes"])>=50:
            closes=ms["sp500"]["closes"]; sma20=sum(closes[-20:])/20; sma50=sum(closes[-50:])/50; rsi_val=calc_rsi(closes[-30:])
            indicators_html+=(f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;">'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:12px;text-align:center;"><div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">S&P SMA20</div>'
                f'<div style="font-size:16px;font-weight:600;color:{"#1a7a4a" if ms["sp500"]["price"]>sma20 else "#b83232"};">${sma20:,.0f}</div>'
                f'<div style="font-size:11px;color:#999;">{"Above ✅" if ms["sp500"]["price"]>sma20 else "Below ⚠️"}</div></div>'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:12px;text-align:center;"><div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">S&P SMA50</div>'
                f'<div style="font-size:16px;font-weight:600;color:{"#1a7a4a" if ms["sp500"]["price"]>sma50 else "#b83232"};">${sma50:,.0f}</div>'
                f'<div style="font-size:11px;color:#999;">{"Above ✅" if ms["sp500"]["price"]>sma50 else "Below ⚠️"}</div></div>'
                f'<div style="background:#f8f8f8;border-radius:8px;padding:12px;text-align:center;"><div style="font-size:10px;color:#999;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;">S&P RSI (14)</div>'
                f'<div style="font-size:16px;font-weight:600;color:{"#b83232" if rsi_val and rsi_val>=70 else "#1a7a4a" if rsi_val and rsi_val<=30 else "#333"};">{rsi_val if rsi_val else "—"}</div>'
                f'<div style="font-size:11px;color:#999;">{"Overbought ⚠️" if rsi_val and rsi_val>=70 else "Oversold 🟢" if rsi_val and rsi_val<=30 else "Neutral"}</div></div></div>')
        if fg:
            fgc=fg_color(fg["score"])
            indicators_html+=(f'<div style="background:#f8f8f8;border-radius:8px;padding:14px;display:flex;align-items:center;gap:14px;margin-bottom:10px;">'
                               f'<div style="font-size:28px;font-weight:800;color:{fgc};">{fg_emoji(fg["score"])} {int(fg["score"])}</div>'
                               f'<div style="font-size:13px;color:#333;line-height:1.6;">{fg_plain_english(fg["score"],fg["rating"])}</div></div>')
        indicators_html+=f'<div style="font-size:13px;color:#555;line-height:1.8;">{treasury_plain_english(yields)}</div>'
        holdings_news=[]
        for ticker in list(HOLDINGS.keys())[:6]:
            if ticker in CRYPTO_MAP: continue
            for a in await get_news(session, ticker, max_articles=1):
                a["ticker"]=ticker; holdings_news.append(a)
            await asyncio.sleep(0.3)
        week_earnings=get_upcoming_earnings(days_ahead=7)
        if week_earnings:
            earnings_html="".join(f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f5f5f5;font-size:13px;"><span style="font-weight:600;">{e["ticker"]}</span><span style="color:#555;">{e["date"]}</span><span style="color:#e8a030;">In {e["days"]} day{"s" if e["days"]!=1 else ""}</span></div>' for e in week_earnings)
        else: earnings_html='<div style="font-size:13px;color:#999;">No earnings from your holdings this week.</div>'
        gap=365000-total_value; months_left=max(1,12-datetime.now(EST).month+1)
        goal_html=(goal_bar_html(total_value)+f'<div style="font-size:13px;color:#555;margin-top:10px;line-height:1.7;">'+
                   (f"Gap to $365k: ${gap:,.0f}. With {months_left} months left, that's roughly ${gap/months_left:,.0f}/month needed." if gap>0 else "You're on track — great position heading into the week.")+
                   '</div>')
        rows=(email_header("📅 Week Ahead Outlook",f"{date_str} · Monday Morning")+
              f'<tr><td style="background:{ms["c_bg"]};padding:16px 32px;border-bottom:3px solid {ms["c_color"]};">'
              f'<div style="font-size:12px;font-family:monospace;letter-spacing:0.1em;color:{ms["c_color"]};text-transform:uppercase;margin-bottom:4px;">Market Condition Heading In</div>'
              f'<div style="font-size:24px;font-weight:800;color:{ms["c_color"]};">{ms["c_emoji"]} {ms["cond"]}</div></td></tr>'+
              email_section("Weekly Outlook",f'<div style="font-size:14px;color:#333;line-height:1.8;">{wo}</div>')+
              email_section("Portfolio Coaching",coaching_html)+email_section("Market Indicators Deep Dive",indicators_html)+
              email_section("Indices Snapshot",index_table_html(ms))+
              email_section("Economic Calendar — This Week",econ_calendar_html(days_ahead=7))+
              email_section("Earnings This Week",earnings_html)+
              (email_section("News on Your Holdings",news_html_block(holdings_news)) if holdings_news else "")+
              email_section("Portfolio — Current State",portfolio_table_html(prices_data))+
              email_section("Goal Progress",goal_html)+email_footer("Have a great week"))
        await send_email(f"📅 Week Ahead — {date_short}", wrap_email(rows))
        logger.info(f"Monday email sent {'(AI coaching)' if ai_coaching else '(no coaching)'}")

# ─── FRIDAY EMAIL ─────────────────────────────────────────────────────────────
async def send_friday_email():
    logger.info("Sending Friday week recap email...")
    async with aiohttp.ClientSession() as session:
        prices_data,total_value=await get_all_prices(session); ms=await get_market_score(session)
        date_str=datetime.now(EST).strftime("%A, %B %d, %Y"); date_short=datetime.now(EST).strftime("%a %b %d")
        best={"ticker":"","pct":-999,"price":0,"name":""}; worst={"ticker":"","pct":999,"price":0,"name":""}
        for ticker,info,price,prev in prices_data:
            if not price: continue
            pl=((price*info["shares"]-info["avg_cost"]*info["shares"])/(info["avg_cost"]*info["shares"]))*100
            if pl>best["pct"]: best={"ticker":ticker,"pct":pl,"price":price,"name":info["name"]}
            if pl<worst["pct"]: worst={"ticker":ticker,"pct":pl,"price":price,"name":info["name"]}
        sp_chg=ms["sp500"]["chg"] if ms["sp500"] else 0
        if sp_chg>=1.5: wr=f"Strong finish to the week — the S&P wrapped up with a {sp_chg:.2f}% gain."
        elif sp_chg>=0: wr=f"The market closed quietly positive on Friday, up {sp_chg:.2f}%. A steady week."
        elif sp_chg>=-1.0: wr=f"A soft close to the week — the S&P dipped {abs(sp_chg):.2f}%. Markets heading into the weekend with some unresolved questions."
        else: wr=f"A rough end to the week. The S&P sold off {abs(sp_chg):.2f}% on Friday. Use the weekend to reassess with fresh eyes."
        perf_html=""
        if best["ticker"]:
            perf_html+=(f'<div style="background:#f0fff4;border-left:3px solid #1a7a4a;border-radius:0 8px 8px 0;padding:12px 14px;margin-bottom:10px;">'
                        f'<div style="font-size:11px;color:#166534;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Best Performer</div>'
                        f'<div style="font-size:15px;font-weight:600;color:#166534;">{best["ticker"]} — {best["pct"]:+.1f}% total return · ${best["price"]:,.2f}</div>'
                        f'<div style="font-size:12px;color:#888;margin-top:2px;">{best["name"]}</div></div>')
        if worst["ticker"]:
            perf_html+=(f'<div style="background:#fff0f0;border-left:3px solid #b83232;border-radius:0 8px 8px 0;padding:12px 14px;">'
                        f'<div style="font-size:11px;color:#b83232;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Most Pressure</div>'
                        f'<div style="font-size:15px;font-weight:600;color:#b83232;">{worst["ticker"]} — {worst["pct"]:+.1f}% total return · ${worst["price"]:,.2f}</div>'
                        f'<div style="font-size:12px;color:#888;margin-top:2px;">{worst["name"]}</div></div>')
        ai_coaching=await get_ai_portfolio_coaching(prices_data, total_value, ms, period="friday")
        coaching_html=(f'<div style="background:#f8f8f8;border-left:4px solid #e8a030;border-radius:0 8px 8px 0;padding:16px 18px;font-size:14px;color:#1a1a1a;line-height:1.8;">{ai_coaching}</div>'
                       f'<div style="font-size:11px;color:#bbb;margin-top:6px;font-family:monospace;">✦ AI portfolio coach</div>') if ai_coaching else ""
        memory=load_memory(); completed=[d for d in memory.get("daily",[]) if d.get("outcome") is not None]
        memory_html=""
        if completed:
            correct_count=sum(1 for d in completed if d.get("correct")); accuracy=correct_count/len(completed)*100
            memory_html=(f'<div style="display:flex;align-items:center;gap:16px;background:#f8f8f8;border-radius:8px;padding:14px 16px;margin-bottom:12px;">'
                         f'<div style="text-align:center;"><div style="font-size:28px;font-weight:800;color:{"#1a7a4a" if accuracy>=60 else "#b83232"};">{accuracy:.0f}%</div>'
                         f'<div style="font-size:11px;color:#999;margin-top:2px;">accuracy</div></div>'
                         f'<div><div style="font-size:13px;font-weight:500;color:#333;margin-bottom:4px;">{correct_count}/{len(completed)} calls correct this week</div>'
                         f'<div style="font-size:12px;color:#666;line-height:1.6;">{"Market is tracking our predictions well." if accuracy>=60 else "Conditions have been unpredictable — staying flexible matters."}</div></div></div>'
                         f'<div style="display:flex;gap:6px;flex-wrap:wrap;">')
            for entry in completed[-5:]:
                if entry.get("correct") is not None:
                    pc="#f0fff4" if entry["correct"] else "#fff0f0"; tc="#166534" if entry["correct"] else "#b83232"; ch="✓" if entry["correct"] else "✗"
                    memory_html+=f'<span style="background:{pc};color:{tc};font-size:11px;padding:3px 9px;border-radius:4px;font-family:monospace;">{ch} {entry["date"]} {entry["condition"]}</span>'
            memory_html+='</div>'
        weekend_reads=await get_news(session, "investing economy market outlook weekend", max_articles=4)
        suggestions=[]
        for ticker,info,price,prev in prices_data:
            if not price: continue
            pl=((price*info["shares"]-info["avg_cost"]*info["shares"])/(info["avg_cost"]*info["shares"]))*100
            if ticker=="RKLB" and price>=90: suggestions.append(f"<strong>RKLB</strong> is at ${price:,.2f} — getting close to your $100 trim target. Start thinking about your exit plan.")
            if pl<-20: suggestions.append(f"<strong>{ticker}</strong> is down {abs(pl):.1f}% from your cost basis. Worth reviewing the thesis over the weekend.")
            if pl>50 and ticker not in ["VTI","BTC","ETH"]: suggestions.append(f"<strong>{ticker}</strong> is up {pl:.1f}% — consider whether position sizing still makes sense.")
        if not suggestions: suggestions.append("Portfolio looks clean heading into the weekend — no major flags to address.")
        notes_html="".join(f'<div style="padding:7px 0;border-bottom:1px solid #f5f5f5;font-size:13px;color:#333;line-height:1.6;">{s}</div>' for s in suggestions)
        nw_earnings=[e for e in get_upcoming_earnings(days_ahead=10) if e["days"]>1]
        next_html=""
        if nw_earnings:
            next_html+='<div style="font-size:12px;font-weight:600;color:#e8a030;margin-bottom:8px;">EARNINGS COMING UP</div>'
            for e in nw_earnings[:4]:
                next_html+=f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;"><span style="font-weight:600;">{e["ticker"]}</span><span style="color:#888;">{e["date"]}</span><span style="color:#555;">In {e["days"]} days</span></div>'
        next_week_econ=[e for e in get_upcoming_econ_events(days_ahead=10) if e["days"]>1]
        if next_week_econ:
            next_html+='<div style="font-size:12px;font-weight:600;color:#888;margin:12px 0 6px;">ECONOMIC EVENTS NEXT WEEK</div>'
            for e in next_week_econ[:5]:
                ic="#b83232" if e["impact"]=="H" else "#a06a10"
                next_html+=f'<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #f5f5f5;font-size:13px;"><span style="color:#555;">{e["date_fmt"]}</span><span style="font-weight:500;">{e["event"]}</span><span style="color:{ic};font-size:11px;font-weight:600;">{"🔴 HIGH" if e["impact"]=="H" else "🟡 MED"}</span></div>'
        next_html+='<div style="font-size:13px;color:#555;line-height:1.8;margin-top:12px;">Monday morning brings a full week-ahead briefing with updated indicators and market outlook.</div>'
        rows=(email_header("📋 Week in Review",f"{date_str} · Friday Close")+
              email_section("This Week's Story",f'<div style="font-size:14px;color:#333;line-height:1.8;">{wr}</div>')+
              email_section("Closing Indices",index_table_html(ms))+
              email_section("Portfolio Performance",perf_html+"<br>"+portfolio_table_html(prices_data))+
              email_section("Goal Progress",goal_bar_html(total_value))+
              (email_section("Portfolio Coaching",coaching_html) if ai_coaching else "")+
              (email_section("Bot Accuracy This Week",memory_html) if memory_html else "")+
              email_section("Notes & Suggestions",notes_html)+
              email_section("Weekend Reading",news_html_block([{**a,"ticker":""} for a in weekend_reads], max_items=4))+
              email_section("Looking Ahead to Next Week",next_html)+
              email_footer("Have a great weekend Patrick"))
        await send_email(f"📋 Week in Review — {date_short}", wrap_email(rows))
        logger.info(f"Friday email sent {'(AI coaching)' if ai_coaching else ''}")
# ─── CONSIDER BUYING SCANNER ──────────────────────────────────────────────────
async def run_consider_buying_scan():
    global consider_buying_fired_today
    today=datetime.now(EST).date()
    logger.info("Running Consider Buying scan...")
    async with aiohttp.ClientSession() as session:
        for stock in CONSIDER_BUYING_UNIVERSE:
            ticker=stock["ticker"]; key=f"{ticker}_{today}"
            if key in consider_buying_fired_today: continue
            try:
                # 365 days for full 52-week high/low picture
                prices=await get_historical_prices(session, ticker, days=365)
                if not prices or len(prices)<50: continue
                current=prices[-1]; high_52w=max(prices)
                drawdown=((high_52w-current)/high_52w)*100
                rsi=calc_rsi(prices[-30:], 14)
                sma20=calc_sma(prices, MA_SHORT); sma50=calc_sma(prices, MA_LONG)
                macd,macd_sig,_=calc_macd(prices[-90:])
                if not rsi or not sma20 or not sma50: continue
                cs=0
                if rsi<=35: cs+=3
                elif rsi<=45: cs+=1
                if drawdown>=25: cs+=2
                elif drawdown>=15: cs+=1
                if current>sma20: cs+=1
                if macd and macd_sig and macd>macd_sig: cs+=1
                if cs<4: continue
                articles=await get_news(session, ticker, max_articles=3)
                headlines=[a["title"] for a in articles]
                macd_desc="bullish crossover" if (macd and macd_sig and macd>macd_sig) else "bearish — caution" if (macd and macd_sig) else "insufficient data"
                ai_alert=await get_ai_consider_buying(ticker=ticker,name=stock["name"],sector=stock["sector"],
                    price=current,rsi=rsi,drawdown=drawdown,sma20=sma20,sma50=sma50,macd_signal=macd_desc,news_headlines=headlines)
                if not ai_alert: continue
                cl="HIGH" if "HIGH" in ai_alert.upper().split()[-10:] else "LOW" if "LOW" in ai_alert.upper().split()[-10:] else "MEDIUM"
                ce={"HIGH":"🔥","MEDIUM":"🟡","LOW":"⚪"}.get(cl,"🟡")
                await send_message(f"💡 *CONSIDER BUYING — {stock['name']}* ({ticker})\n─────────────────────────\n"
                    f"🏷 {stock['sector']} · ${current:,.2f}\n📉 Down {drawdown:.1f}% from 52w high · RSI {rsi}\n─────────────────────────\n"
                    f"{ai_alert}\n─────────────────────────\n{ce} Conviction: *{cl}*\n⚡ _Not financial advice_")
                consider_buying_fired_today.add(key)
                await asyncio.sleep(2)
            except Exception as e: logger.error(f"Consider Buying scan error {ticker}: {e}")
            await asyncio.sleep(0.5)

# ─── WHY DID THIS MOVE ────────────────────────────────────────────────────────
async def check_why_did_this_move():
    async with aiohttp.ClientSession() as session:
        sp500=await fetch_index(session,"^GSPC"); market_chg=sp500["chg"] if sp500 else 0
        for ticker,info in HOLDINGS.items():
            if ticker in CRYPTO_MAP: continue
            try:
                price=await get_stock_price(session,ticker); prev=await get_prev_close(session,ticker)
                if not price or not prev: continue
                move_pct=((price-prev)/prev)*100
                if abs(move_pct)<3.0: continue
                alert_key=f"move_{ticker}_{datetime.now(EST).date()}"
                if fired_alerts.get(alert_key): continue
                if abs(move_pct)-abs(market_chg)<1.5: continue
                fired_alerts[alert_key]=datetime.now()
                articles=await get_news(session,ticker,max_articles=3)
                explanation=await get_ai_move_explanation(ticker=ticker,name=info["name"],move_pct=move_pct,
                    direction="up" if move_pct>0 else "down",news_headlines=[a["title"] for a in articles],market_chg=market_chg)
                if not explanation: explanation="No specific catalyst found — may be moving with broader sector trends or on low volume."
                de="📈" if move_pct>0 else "📉"
                await send_message(f"{de} *WHY IS {ticker} MOVING?*\n─────────────────────\n"
                    f"*{info['name']}* is {'+' if move_pct>0 else ''}{move_pct:.1f}% today\n"
                    f"Market (S&P): {'+' if market_chg>0 else ''}{market_chg:.2f}%\n─────────────────────\n"
                    f"{explanation}\n─────────────────────\n⚡ _AI-powered · Not financial advice_")
            except Exception as e: logger.error(f"Move check error {ticker}: {e}")
            await asyncio.sleep(0.3)

# ─── SLEEPER SCANNER ──────────────────────────────────────────────────────────
async def send_sleeper_pick(session):
    candidates=[]
    for stock in SLEEPER_WATCHLIST:
        ticker=stock["ticker"]
        try:
            from_date=(datetime.now()-timedelta(days=365)).strftime("%Y-%m-%d"); to_date=datetime.now().strftime("%Y-%m-%d")
            url=f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}?adjusted=true&sort=asc&limit=365&apiKey={POLYGON_API_KEY}"
            async with session.get(url, timeout=10) as r:
                data=await r.json()
                if not data.get("results") or len(data["results"])<30: continue
                prices=[float(x["c"]) for x in data["results"]]; current=prices[-1]; high_52w=max(prices)
                drawdown=((high_52w-current)/high_52w)*100; rsi=calc_rsi(prices[-30:],14)
                if drawdown>=30 and rsi and rsi<=35:
                    candidates.append({"ticker":ticker,"name":stock["name"],"sector":stock["sector"],
                        "price":current,"high_52w":high_52w,"drawdown":drawdown,"rsi":rsi,"score":drawdown+(35-rsi)})
            await asyncio.sleep(0.5)
        except Exception as e: logger.error(f"Sleeper scan error {ticker}: {e}")
    if not candidates:
        await send_message("🔍 *SLEEPER PICK* — No strong candidates today. Market may be broadly elevated.")
        return
    best=sorted(candidates, key=lambda x: x["score"], reverse=True)[0]
    recovery=((best["high_52w"]-best["price"])/best["price"])*100
    await send_message(f"🔍 *SLEEPER PICK — {best['name']}* (${best['ticker']})\n─────────────────────────\n"
        f"🏷 {best['sector']}\n💲 *${best['price']:,.2f}* — down {best['drawdown']:.1f}% from 52w high\n"
        f"📊 *RSI {best['rsi']}* — {'🔥 Very oversold' if best['rsi']<25 else '⚠️ Oversold'}\n"
        f"🎯 Recovery potential: +{recovery:.1f}%\n─────────────────────────\n"
        f"{'🟢 Strong setup' if best['drawdown']>=40 and best['rsi']<30 else '🟡 Worth watching'}\n⚡ _Not financial advice_")

# ─── STANDARD ALERT CHECKERS ──────────────────────────────────────────────────
async def check_price_alerts():
    async with aiohttp.ClientSession() as session:
        for alert in PRICE_ALERTS:
            ticker=alert["ticker"]
            price=await get_crypto_price(session,CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(session,ticker)
            if not price: continue
            triggered=(alert["direction"]=="above" and price>=alert["target"]) or (alert["direction"]=="below" and price<=alert["target"])
            key=f"{ticker}_{alert['target']}_{alert['direction']}"; last=fired_alerts.get(key)
            if last and (datetime.now()-last).seconds/3600<4: continue
            if triggered:
                fired_alerts[key]=datetime.now()
                sym="▲" if alert["direction"]=="above" else "▼"
                await send_message(f"🚨 *PRICE ALERT — {ticker}*\n─────────────────────\n{sym} *${price:,.2f}* vs target ${alert['target']:,.2f}\n─────────────────────\n{alert['action']}")

async def check_rsi_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in HOLDINGS:
            if ticker in CRYPTO_MAP: continue
            prices=await get_historical_prices(session,ticker,days=60)
            if not prices or len(prices)<RSI_PERIOD+1: continue
            rsi=calc_rsi(prices,RSI_PERIOD)
            if not rsi: continue
            for condition,key,emoji,label,advice in [
                (rsi>=RSI_OVERBOUGHT,f"rsi_ob_{ticker}","🔴","OVERBOUGHT (≥70)","Consider taking partial profits or tightening your stop."),
                (rsi<=RSI_OVERSOLD,f"rsi_os_{ticker}","🟢","OVERSOLD (≤30)","Could be a buying opportunity — check the news first.")]:
                if condition:
                    last=fired_alerts.get(key)
                    if not last or (datetime.now()-last).seconds>14400:
                        fired_alerts[key]=datetime.now()
                        await send_message(f"📊 *RSI ALERT — {ticker}*\n─────────────────────\n{emoji} *RSI: {rsi}* — {label}\n📌 *{HOLDINGS[ticker]['name']}*\n─────────────────────\n{advice}")

async def check_ma_alerts():
    async with aiohttp.ClientSession() as session:
        for ticker in HOLDINGS:
            if ticker in CRYPTO_MAP: continue
            prices=await get_historical_prices(session,ticker,days=90)
            if not prices or len(prices)<MA_LONG: continue
            cp=prices[-1]; pp=prices[:-1]
            sma20=calc_sma(prices,MA_SHORT); sma50=calc_sma(prices,MA_LONG)
            psma20=calc_sma(pp,MA_SHORT); psma50=calc_sma(pp,MA_LONG)
            if not all([sma20,sma50,psma20,psma50]): continue
            gn=sma20>sma50; gp=psma20>psma50
            if gn and not gp:
                key=f"ma_golden_{ticker}"; last=fired_alerts.get(key)
                if not last or (datetime.now()-last).days>=1:
                    fired_alerts[key]=datetime.now()
                    await send_message(f"📈 *GOLDEN CROSS — {ticker}*\n─────────────────────\n✅ SMA20 crossed ABOVE SMA50\n📌 *{HOLDINGS[ticker]['name']}* @ ${cp:,.2f}\n─────────────────────\n🟢 *Bullish signal* — trend turning up.")
            elif not gn and gp:
                key=f"ma_death_{ticker}"; last=fired_alerts.get(key)
                if not last or (datetime.now()-last).days>=1:
                    fired_alerts[key]=datetime.now()
                    await send_message(f"📉 *DEATH CROSS — {ticker}*\n─────────────────────\n🔴 SMA20 crossed BELOW SMA50\n📌 *{HOLDINGS[ticker]['name']}* @ ${cp:,.2f}\n─────────────────────\n⚠️ *Bearish signal* — consider tightening stops.")

async def check_market_gift():
    global market_gift_fired_today
    today=datetime.now(EST).date()
    if market_gift_fired_today==today: return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=5d",
                                   headers={"User-Agent":"Mozilla/5.0"}, timeout=10) as r:
                data=await r.json()
                closes=[c for c in data["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
                if len(closes)>=2:
                    drop=((closes[-2]-closes[-1])/closes[-2])*100
                    if drop>=2.0:
                        market_gift_fired_today=today
                        emoji="🎁🎁" if drop>=3.0 else "🎁"
                        verdict="Significant fear-driven selloff" if drop>=3.0 else "Minor fear-driven dip"
                        await send_message(f"{emoji} *MARKET GIFT ALERT*\n─────────────────────\n📉 S&P 500 down *{drop:.1f}%* today\nThis looks like macro fear, not fundamental weakness.\n─────────────────────\n👀 PANW · GWRE · WYNN · RKLB\n⚡ {verdict} — DYOR before acting")
    except Exception as e: logger.error(f"Market gift check error: {e}")

async def check_earnings_countdown():
    today=datetime.now(EST).date()
    for ticker,date_str in EARNINGS_CALENDAR.items():
        try:
            ed=datetime.strptime(date_str,"%Y-%m-%d").date(); days_away=(ed-today).days
            if days_away in [2,1]:
                await send_message(f"📅 *EARNINGS — {ticker}*\n─────────────────────\nReports {'tomorrow' if days_away==1 else 'in 2 days'} — *{ed.strftime('%b %d')}*\n⚠️ Be ready for volatility.")
        except: continue

async def check_insider_trading():
    stock_tickers=[t for t in list(HOLDINGS.keys())+["PANW","WYNN"] if t not in CRYPTO_MAP]
    try:
        async with aiohttp.ClientSession() as session:
            for ticker in stock_tickers:
                url=f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=insiderTransactions"
                async with session.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10) as r:
                    data=await r.json()
                    try:
                        txns=data["quoteSummary"]["result"][0]["insiderTransactions"]["transactions"]
                        for t in txns[:3]:
                            tid=f"{ticker}_{t.get('startDate',{}).get('raw',0)}_{t.get('filer','')}"
                            if tid in insider_seen: continue
                            tt=t.get("transactionDescription","")
                            if ("Purchase" in tt or "Acquisition" in tt) and t.get("startDate",{}).get("fmt"):
                                insider_seen.add(tid)
                                await send_message(f"🏛️ *INSIDER BUY — {ticker}*\n─────────────────────\n"
                                    f"👤 {t.get('filer','')} ({t.get('relation','')})\n📅 {t.get('startDate',{}).get('fmt','')}\n"
                                    f"📊 {t.get('shares',{}).get('fmt','')} shares · {t.get('value',{}).get('fmt','')}\n"
                                    f"─────────────────────\n💡 Insiders buy for one reason — they think it's going up.")
                    except: pass
                await asyncio.sleep(0.5)
    except Exception as e: logger.error(f"Insider trading error: {e}")
# ─── TELEGRAM COMMANDS ────────────────────────────────────────────────────────
last_update_id=0

async def handle_commands():
    global last_update_id
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as r:
                data=await r.json()
                for update in data.get("result",[]):
                    last_update_id=update["update_id"]
                    text=update.get("message",{}).get("text","").strip()
                    if not text.startswith("/"): continue
                    parts=text.split(); cmd=parts[0].lower()

                    if cmd=="/brief":
                        await send_message("📊 Pulling your brief..."); await send_morning_brief_telegram()

                    elif cmd=="/ask":
                        if len(parts)>=2:
                            question=" ".join(parts[1:]); await send_message("🤔 Thinking...")
                            async with aiohttp.ClientSession() as s:
                                ms=await get_market_score(s); prices_data,_=await get_all_prices(s)
                            answer=await get_ai_ask_response(question,ms,prices_data)
                            if answer:
                                await send_message(f"💬 *ASK THE BOT*\n─────────────────────\n*Q: {question}*\n─────────────────────\n{answer}\n─────────────────────\n⚡ _AI-powered · Not financial advice_")
                            else: await send_message("⚠️ Couldn't get an answer right now. Try again in a moment.")
                        else: await send_message("⚠️ Usage: /ask should I buy PANW today?")

                    elif cmd=="/scores":
                        memory=load_memory()
                        if memory.get("conviction_scores"):
                            latest_date=max(memory["conviction_scores"].keys()); scores=memory["conviction_scores"][latest_date]
                            lines=[f"📊 *CONVICTION SCORES* ({latest_date})","─"*28]
                            for ticker,data in scores.items():
                                s=data["score"]; icon="🔥" if s>=8 else "🟡" if s>=6 else "🔴"
                                lines.append(f"{icon} *{ticker}* — {s}/10 · {data['reasoning'][:60]}...")
                            await send_message("\n".join(lines))
                        else: await send_message("⚠️ No conviction scores yet. Check back after tonight's evening email.")

                    elif cmd=="/memory":
                        memory=load_memory(); daily=memory.get("daily",[]); completed=[d for d in daily if d.get("outcome") is not None]
                        if completed:
                            correct=sum(1 for d in completed if d.get("correct")); acc=correct/len(completed)*100
                            lines=[f"🧠 *MARKET MEMORY*",f"Accuracy: {correct}/{len(completed)} calls ({acc:.0f}%)","─"*28]
                            for entry in daily[-7:]:
                                if entry.get("outcome") is not None:
                                    ch="✓" if entry.get("correct") else "✗"
                                    lines.append(f"{ch} {entry['date']} — {entry['condition']} | S&P {entry['outcome']:+.2f}%")
                            await send_message("\n".join(lines))
                        else: await send_message("🧠 *MARKET MEMORY* — Building history. Check back after a few days of trading.")

                    elif cmd=="/prices":
                        async with aiohttp.ClientSession() as s:
                            lines=["💲 *LIVE PRICES*","─"*24]
                            for ticker,info in HOLDINGS.items():
                                price=await get_crypto_price(s,CRYPTO_MAP[ticker]) if ticker in CRYPTO_MAP else await get_stock_price(s,ticker)
                                if price: lines.append(f"📌 *{ticker}* — ${price:,.2f}")
                            await send_message("\n".join(lines))

                    elif cmd=="/econ":
                        days=int(parts[1]) if len(parts)>=2 and parts[1].isdigit() else 7
                        econ_block=econ_calendar_telegram(days_ahead=days)
                        await send_message(econ_block if econ_block else f"📅 No major economic events in the next {days} days.")

                    elif cmd=="/sleeper":
                        await send_message("🔍 Running sleeper scanner...")
                        async with aiohttp.ClientSession() as s:
                            await send_sleeper_pick(s)

                    elif cmd=="/rsi":
                        async with aiohttp.ClientSession() as s:
                            lines=["📊 *RSI READINGS*","─"*24,"🟢 ≤30 Oversold · 🔴 ≥70 Overbought · ─ Neutral"]
                            for ticker in HOLDINGS:
                                if ticker in CRYPTO_MAP: continue
                                prices=await get_historical_prices(s,ticker,days=60)
                                if prices and len(prices)>14:
                                    rsi=calc_rsi(prices,14)
                                    if rsi:
                                        icon="🟢" if rsi<=30 else "🔴" if rsi>=70 else "─"
                                        lines.append(f"{icon} *{ticker}* — RSI {rsi}")
                            await send_message("\n".join(lines))

                    elif cmd=="/help":
                        await send_message("🤖 *COMMANDS*\n─────────────────────\n"
                            "/ask [question] — Ask the AI anything\n"
                            "/scores — Latest conviction scores per holding\n"
                            "/memory — Bot's market call accuracy\n"
                            "/brief — Morning brief on demand\n"
                            "/prices — Live prices now\n"
                            "/econ [days] — Upcoming economic events (default: 7 days)\n"
                            "/sleeper — Run sleeper scanner\n"
                            "/rsi — RSI for all holdings\n"
                            "/help — This menu")
    except Exception as e: logger.error(f"Command handler error: {e}")

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
async def main():
    logger.info("Patrick's Portfolio Bot — Phase C starting...")
    ai_status="✅ Claude API connected — all AI features active" if ANTHROPIC_API_KEY else "⚠️ Claude API not found — running in standard mode"
    await send_message(f"🤖 *Patrick's Portfolio Bot — Phase C*\n─────────────────────\n{ai_status}\n─────────────────────\n"
        f"🔄 *Phase B→C Changes Applied:*\n"
        f"  ✦ Morning email now fires at 9:00am EST\n"
        f"  ✦ Economic calendar added (CPI/NFP/Fed/PCE)\n"
        f"  ✦ Watchlist removed — all references cleared\n"
        f"  ✦ Consider Buying scanner upgraded to 365-day history\n"
        f"  ✦ Portfolio updated (MRSH kept, SOFI 430, AMZN 79, BTC/LINK updated)\n"
        f"─────────────────────\n"
        f"📧 Mon 7:45am · Daily 9:00am · Daily 5pm · Fri 6pm\n"
        f"💬 /ask /scores /memory /brief /prices /econ /sleeper /rsi /help")

    morning_sent_today=evening_sent_today=monday_sent_today=friday_sent_today=None
    earnings_check_today=None
    last_price_check=last_rsi_check=last_ma_check=None
    last_news_collect=last_insider_check=last_gift_check=None
    last_move_check=last_consider_buying=None

    while True:
        now=datetime.now(EST); today=now.date(); wd=now.weekday()

        if wd==0 and now.hour==7 and 45<=now.minute<=50 and monday_sent_today!=today:
            await send_monday_email(); monday_sent_today=today

        # Morning email at 9:00am
        if wd<5 and now.hour==9 and 0<=now.minute<=5 and morning_sent_today!=today:
            await send_morning_email(); morning_sent_today=today

        if wd<5 and now.hour==17 and 0<=now.minute<=5 and evening_sent_today!=today:
            await send_evening_email(); evening_sent_today=today

        if wd==4 and now.hour==18 and 0<=now.minute<=5 and friday_sent_today!=today:
            await send_friday_email(); friday_sent_today=today

        if wd<5 and now.hour==8 and 30<=now.minute<=35 and earnings_check_today!=today:
            await check_earnings_countdown(); earnings_check_today=today

        if is_market_open():
            if not last_price_check or (now-last_price_check).seconds>=300:
                await check_price_alerts(); last_price_check=now
            if not last_rsi_check or (now-last_rsi_check).seconds>=1800:
                await check_rsi_alerts(); last_rsi_check=now
            if not last_ma_check or (now-last_ma_check).seconds>=3600:
                await check_ma_alerts(); last_ma_check=now
            if not last_news_collect or (now-last_news_collect).seconds>=1800:
                await collect_news(); last_news_collect=now
            if not last_insider_check or (now-last_insider_check).seconds>=14400:
                await check_insider_trading(); last_insider_check=now
            if not last_gift_check or (now-last_gift_check).seconds>=1800:
                await check_market_gift(); last_gift_check=now
            if not last_move_check or (now-last_move_check).seconds>=900:
                await check_why_did_this_move(); last_move_check=now
            if now.hour==10 and 30<=now.minute<=35 and last_consider_buying!=today:
                await run_consider_buying_scan(); last_consider_buying=today

        await handle_commands()
        await asyncio.sleep(3)

if __name__=="__main__":
    asyncio.run(main())
