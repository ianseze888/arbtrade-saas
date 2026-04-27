#!/usr/bin/env python3
"""
Amazon Wholesale & OA Research Agent — Final Version
- Wholesale: no web search (fast, no rate limit)
- OA: web search with 3 min delay after wholesale
- 48 hour lead accumulation with deduplication
- Timestamps on every lead
"""

import json, os, time, subprocess, schedule, logging
from datetime import datetime, timedelta
from pathlib import Path
import anthropic

BASE_DIR = Path(__file__).parent
CRITERIA = BASE_DIR / "criteria.json"
RESULTS  = BASE_DIR / "results.json"
LOG_FILE = BASE_DIR / "agent.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

def get_api_key() -> str:
    try:
        r = subprocess.run(
            ["security","find-generic-password","-a",os.environ.get("USER",""),
             "-s","ANTHROPIC_API_KEY","-w"],
            capture_output=True, text=True
        )
        k = r.stdout.strip()
        if k: log.info("API key loaded from Mac Keychain ✓"); return k
    except: pass
    return os.environ.get("ANTHROPIC_API_KEY","").strip()

def load_criteria():
    with open(CRITERIA) as f: return json.load(f)

def extract_json(text):
    s = text.find("["); e = text.rfind("]") + 1
    if s == -1 or e == 0: return None
    try: return json.loads(text[s:e])
    except: return None

def safe_roi(val):
    try: return int(str(val).replace("%","").split("-")[0].strip() or 0)
    except: return 0

def normalize_lead(lead):
    """Ensure all fields are strings for dashboard compatibility."""
    roi = lead.get("roi", 0)
    bsr = lead.get("bsr", 0)
    buy = lead.get("buy_cost", 0)
    sell = lead.get("sell_price", 0)
    if isinstance(roi, (int, float)): lead["roi"] = f"{int(roi)}%"
    if isinstance(bsr, (int, float)): lead["bsr"] = f"#{int(bsr):,}"
    if isinstance(buy, (int, float)): lead["buy_cost"] = f"${buy}"
    if isinstance(sell, (int, float)): lead["sell_price"] = f"${sell}"
    return lead

def load_existing_leads():
    """Load leads from last 48 hours, dropping anything older."""
    if not RESULTS.exists(): return []
    try:
        with open(RESULTS) as f: data = json.load(f)
        cutoff = datetime.now() - timedelta(hours=48)
        kept = []
        for l in data.get("leads", []):
            found_at = l.get("found_at", "")
            try:
                if datetime.fromisoformat(found_at) > cutoff:
                    kept.append(l)
            except: pass
        log.info(f"Loaded {len(kept)} existing leads from last 48h")
        return kept
    except: return []

def deduplicate(leads):
    """Remove duplicate leads by ASIN or name."""
    seen = set(); unique = []
    for l in leads:
        key = l.get("asin") or l.get("name","")
        if key and key not in seen:
            seen.add(key); unique.append(l)
    return unique

def save_results(leads):
    leads = deduplicate(leads)
    leads.sort(key=lambda l: (
        0 if l.get("recommendation") == "BUY" else 1,
        -safe_roi(l.get("roi", 0))
    ))
    data = {
        "last_run": datetime.now().isoformat(),
        "total_leads": len(leads),
        "wholesale_count": sum(1 for l in leads if l.get("type") == "wholesale"),
        "oa_count": sum(1 for l in leads if l.get("type") == "oa"),
        "best_roi": max((safe_roi(l.get("roi",0)) for l in leads), default=0),
        "window_hours": 48,
        "leads": leads
    }
    with open(RESULTS, "w") as f: json.dump(data, f, indent=2)
    log.info(f"Saved {len(leads)} total leads (48h window) → {RESULTS}")

def run_wholesale(client, cfg):
    ws = cfg["wholesale"]
    cats = ", ".join(ws["categories"])
    log.info("Running Wholesale search...")

    query = (
        f"You are an Amazon FBA wholesale expert. Generate 5 wholesale product leads "
        f"for categories: {cats}. "
        f"Criteria: BSR under #{ws['max_bsr']:,}, under {ws['max_sellers']} FBA sellers, "
        f"min {ws['min_monthly_sales']} monthly sales, min {ws['min_roi_percent']}% ROI. "
        f"Source from: Faire, RangeMe, Wholesale Central, or direct brands. "
        f"Return ONLY a JSON array [ ]. "
        f"Fields: name, asin, bsr, sellers, buy_cost, sell_price, roi, source, "
        f"risk_flags, recommendation, reason, type. "
        f"type='wholesale'. recommendation=BUY/WATCH/PASS. "
        f"Use string values: roi='35%', bsr='#12000', buy_cost='$8.50', sell_price='$15.99'."
    )

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": query}]
        )
        raw = "".join(b.text for b in resp.content if hasattr(b,"text")).strip()
        leads = extract_json(raw)
        if not leads: log.error(f"  Wholesale: No JSON found. Raw: {raw[:200]}"); return []
        leads = [normalize_lead(l) for l in leads]
        log.info(f"  Wholesale: {len(leads)} leads found ✓")
        return leads
    except Exception as e:
        log.error(f"  Wholesale: Error — {e}"); return []

def run_oa(client, cfg):
    oa = cfg["online_arbitrage"]
    sources = ", ".join(oa["active_sources"][:3])
    cats = ", ".join(oa["categories"])
    log.info("Running Online Arbitrage search (with web search)...")

    search_query = (
        f"Search for current online arbitrage deals at {sources} "
        f"in categories: {cats}. "
        f"Find products under ${oa['max_buy_cost']} retail that sell for "
        f"at least ${oa['min_price_spread']} more on Amazon right now. "
        f"Find 5 specific real products with actual current sale prices."
    )

    fmt_instruction = (
        f"From those search results, list 5 OA deals with {oa['min_roi_percent']}%+ ROI "
        f"after Amazon FBA fees of approximately $4-6 per unit. "
        f"Return ONLY a JSON array [ ]. No other text. "
        f"Fields: name, asin, source, buy_cost, sell_price, bsr, sellers, "
        f"monthly_sales, roi, replenishable, risk_flags, recommendation, reason, type. "
        f"type='oa'. recommendation=BUY/WATCH/PASS. replenishable=true/false. "
        f"Use string values: roi='45%', bsr='#8000', buy_cost='$5.99', sell_price='$18.99'."
    )

    try:
        msgs = [{"role": "user", "content": search_query}]
        r1 = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=msgs
        )
        msgs.append({"role": "assistant", "content": r1.content})
        msgs.append({"role": "user", "content": fmt_instruction})
        r2 = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=msgs
        )
        raw = "".join(b.text for b in r2.content if hasattr(b,"text")).strip()
        leads = extract_json(raw)
        if not leads: log.error(f"  OA: No JSON found. Raw: {raw[:200]}"); return []
        leads = [normalize_lead(l) for l in leads]
        log.info(f"  OA: {len(leads)} leads found ✓")
        return leads
    except Exception as e:
        log.error(f"  OA: Error — {e}"); return []

def run_scan(client):
    log.info("=" * 60)
    log.info("Starting scan...")
    cfg = load_criteria()

    # Load existing 48h leads
    existing = load_existing_leads()
    new_leads = []
    now = datetime.now().isoformat()

    # Wholesale — no web search, fast
    if cfg["wholesale"]["enabled"]:
        ws_leads = run_wholesale(client, cfg)
        for l in ws_leads: l["found_at"] = now
        new_leads.extend(ws_leads)

    # Wait 3 minutes before OA to reset token counter
    if cfg["online_arbitrage"]["enabled"]:
        log.info("Waiting 3 minutes before OA search to reset rate limits...")
        time.sleep(180)
        oa_leads = run_oa(client, cfg)
        for l in oa_leads: l["found_at"] = now
        new_leads.extend(oa_leads)

    # Merge new + existing, deduplicate, save
    all_leads = new_leads + existing
    save_results(all_leads)

    total = len(deduplicate(all_leads))
    new_count = len(new_leads)
    log.info(f"Scan complete — {new_count} new leads, {total} total in 48h window.")
    log.info("=" * 60)

def main():
    api_key = get_api_key()
    if not api_key:
        log.error("No API key found. Check Keychain — item name must be ANTHROPIC_API_KEY")
        return

    client = anthropic.Anthropic(api_key=api_key)
    cfg = load_criteria()
    interval = cfg["agent"]["scan_interval_hours"]

    log.info("━" * 60)
    log.info("Amazon Research Agent — Final Version")
    log.info(f"Scan interval : every {interval} hours")
    log.info(f"Lead window   : 48 hours (rolling)")
    log.info(f"Wholesale     : {'enabled' if cfg['wholesale']['enabled'] else 'disabled'} (no web search)")
    log.info(f"OA            : {'enabled' if cfg['online_arbitrage']['enabled'] else 'disabled'} (web search, 3min delay)")
    log.info("━" * 60)

    run_scan(client)
    schedule.every(interval).hours.do(run_scan, client)
    log.info(f"Next scan in {interval} hours. Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
