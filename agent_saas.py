#!/usr/bin/env python3
"""
ARBTRADE SaaS Research Agent
- Category rotation per user (prevents lead overlap)
- Expanded wholesale and OA source prompts
- User-specific lead deduplication
- Runs as part of main.py scheduler
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# ── Expanded category pools ──────────────────────────────────────────────────

WS_CATEGORIES = [
    ["Health & Household", "Vitamins & Dietary Supplements"],
    ["Grocery & Gourmet Food", "Pantry Staples"],
    ["Baby", "Diapering & Potty Training"],
    ["Pet Supplies", "Dog Supplies"],
    ["Beauty & Personal Care", "Skin Care"],
    ["Sports & Outdoors", "Exercise & Fitness"],
    ["Home & Kitchen", "Kitchen & Dining"],
    ["Office Products", "Office & School Supplies"],
    ["Health & Household", "Medical Supplies"],
    ["Grocery & Gourmet Food", "Beverages"],
    ["Pet Supplies", "Cat Supplies"],
    ["Beauty & Personal Care", "Hair Care"],
    ["Sports & Outdoors", "Outdoor Recreation"],
    ["Home & Kitchen", "Cleaning Supplies"],
    ["Baby", "Feeding"],
]

OA_SOURCES_POOL = [
    # Tier 1 — highest margin
    ["Walgreens clearance", "CVS weekly sales", "iHerb flash sales"],
    ["Vitacost promotions", "Chewy clearance", "brand liquidation portals"],
    ["Rite Aid clearance", "CVS app deals", "Walgreens app coupons"],
    ["iHerb subscribe and save gaps", "Chewy Autoship deals", "Vitacost 25% off sales"],
    # Tier 2 — good deals
    ["Target Circle clearance", "Walmart Rollback", "Staples rebates"],
    ["Kohl's clearance", "Home Depot B2B", "Costco.com overstock"],
    ["Target app clearance", "Walmart.com clearance", "BJs Wholesale"],
    ["Office Depot rebates", "Best Buy open box", "Bed Bath Beyond liquidation"],
    # Tier 3 — supplementary
    ["Amazon Warehouse deals", "Overstock.com", "Wayfair clearance"],
    ["Groupon Goods", "Zulily flash sales", "Woot deals"],
]

WS_DISTRIBUTORS = [
    "Faire wholesale marketplace",
    "RangeMe brand platform", 
    "Wholesale Central directory",
    "UNFI natural foods distributor",
    "KeHE distributors",
    "Dot Foods redistribution",
    "McLane Company",
    "Nash Finch wholesale",
    "Associated Wholesale Grocers",
    "Direct brand wholesale programs",
    "Expo West trade show brands",
    "ASD Market Week suppliers",
    "Specialty Food Association members",
    "Natural Products Expo brands",
]

def get_user_rotation(user_id: str, pool_size: int) -> int:
    """
    Deterministically assign a rotation slot to a user based on their ID.
    Same user always gets same slot — no randomness, fully consistent.
    """
    hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
    return hash_val % pool_size

def get_user_categories(user_id: str, custom_categories: list = None) -> list:
    """Get categories for this user — custom if set, otherwise rotated."""
    if custom_categories and len(custom_categories) > 0:
        return custom_categories
    slot = get_user_rotation(user_id, len(WS_CATEGORIES))
    return WS_CATEGORIES[slot]

def get_user_oa_sources(user_id: str, custom_sources: list = None) -> list:
    """Get OA sources for this user — custom if set, otherwise rotated."""
    if custom_sources and len(custom_sources) > 0:
        return custom_sources[:4]
    slot = get_user_rotation(user_id, len(OA_SOURCES_POOL))
    return OA_SOURCES_POOL[slot]

def get_user_distributors(user_id: str) -> list:
    """Get a varied distributor list per user."""
    slot = get_user_rotation(user_id, 3)
    # Rotate which distributors are emphasized
    if slot == 0:
        return WS_DISTRIBUTORS[:5]
    elif slot == 1:
        return WS_DISTRIBUTORS[3:8]
    else:
        return WS_DISTRIBUTORS[6:11]

def extract_json(text):
    s = text.find("["); e = text.rfind("]") + 1
    if s == -1 or e == 0: return None
    try: return json.loads(text[s:e])
    except: return None

def safe_roi(val):
    try: return int(str(val).replace("%","").split("-")[0].strip() or 0)
    except: return 0

def normalize_lead(lead):
    for k in ["roi","bsr","buy_cost","sell_price"]:
        v = lead.get(k, 0)
        if isinstance(v, (int, float)):
            if k == "roi": lead[k] = str(int(v)) + "%"
            elif k == "bsr": lead[k] = "#" + str(int(v)) + ",000"
            else: lead[k] = "$" + str(v)
    if isinstance(lead.get("risk_flags"), str):
        lead["risk_flags"] = [lead["risk_flags"]] if lead["risk_flags"] else []
    return lead

def build_ws_prompt(user_id: str, criteria: dict) -> str:
    ws = criteria.get("wholesale", {})
    categories = get_user_categories(user_id, ws.get("categories", []))
    distributors = get_user_distributors(user_id)
    cats_str = ", ".join(categories) if isinstance(categories[0], str) else ", ".join(categories)
    dist_str = ", ".join(distributors[:4])
    min_roi = ws.get("min_roi_percent", 30)
    max_bsr = ws.get("max_bsr", 50000)
    max_sellers = ws.get("max_sellers", 8)
    min_sales = ws.get("min_monthly_sales", 300)

    return (
        "You are an expert Amazon FBA wholesale product researcher with deep knowledge of "
        "distributor networks and brand wholesale programs.\n\n"
        "Find 5 specific wholesale product opportunities for an Amazon FBA seller.\n\n"
        "REQUIRED CRITERIA (all must be met):\n"
        "- Categories: " + cats_str + "\n"
        "- Minimum monthly sales: " + str(min_sales) + " units\n"
        "- Minimum ROI after all FBA fees: " + str(min_roi) + "%\n"
        "- Maximum FBA sellers on listing: " + str(max_sellers) + "\n"
        "- Maximum Best Seller Rank: #" + str(max_bsr) + "\n"
        "- Amazon must NOT be the primary buy box holder\n"
        "- Product must be sourceable from: " + dist_str + "\n\n"
        "ADDITIONAL SOURCING NOTES:\n"
        "- Prioritize established brands with MAP policies (protects margins)\n"
        "- Favor replenishable products over seasonal\n"
        "- Include mix of fast-moving consumables and higher-margin items\n"
        "- Check for brand authorization requirements\n"
        "- Prefer net-30 payment terms available\n\n"
        "Return ONLY a JSON array. No explanation. Start with [ end with ].\n"
        "Required fields: name, asin, bsr, sellers, buy_cost, sell_price, roi, source, "
        "risk_flags, recommendation, reason, type\n"
        "type='wholesale' recommendation=BUY/WATCH/PASS\n"
        "Use STRING values: roi='35%' bsr='#12,450' buy_cost='$8.50' sell_price='$24.99'\n"
        "risk_flags must be an ARRAY of strings, never a single string.\n"
        "Example: [{\"name\":\"Product Name\",\"asin\":\"B00XXXXX\",\"bsr\":\"#8,200\","
        "\"sellers\":4,\"buy_cost\":\"$9.50\",\"sell_price\":\"$24.99\",\"roi\":\"38%\","
        "\"source\":\"Faire\",\"risk_flags\":[\"Expiration dating required\"],"
        "\"recommendation\":\"BUY\",\"reason\":\"Strong velocity, low competition\","
        "\"type\":\"wholesale\"}]"
    )

def build_oa_prompt(user_id: str, criteria: dict) -> str:
    oa = criteria.get("online_arbitrage", {})
    sources = get_user_oa_sources(user_id, oa.get("active_sources", []))
    categories = get_user_categories(user_id, oa.get("categories", []))
    cats_str = ", ".join(categories) if isinstance(categories, list) else categories
    sources_str = ", ".join(sources)
    min_roi = oa.get("min_roi_percent", 35)
    max_buy = oa.get("max_buy_cost", 35)
    min_spread = oa.get("min_price_spread", 8)
    max_sellers = oa.get("max_sellers", 12)

    return (
        "You are an expert Amazon FBA online arbitrage researcher with knowledge of "
        "current retail sales, clearance events, and price gaps.\n\n"
        "Find 5 specific online arbitrage deals available RIGHT NOW.\n\n"
        "SCAN THESE SOURCES for current sales and clearance: " + sources_str + "\n\n"
        "REQUIRED CRITERIA:\n"
        "- Categories: " + cats_str + "\n"
        "- Maximum retail buy cost: $" + str(max_buy) + " per unit\n"
        "- Minimum price spread (buy vs Amazon sell): $" + str(min_spread) + "\n"
        "- Minimum ROI after FBA fees (~$4-6/unit): " + str(min_roi) + "%\n"
        "- Maximum FBA sellers: " + str(max_sellers) + "\n"
        "- Prioritize REPLENISHABLE deals (recurring sales not one-time)\n\n"
        "ADDITIONAL NOTES:\n"
        "- Include cashback stacking opportunities (Rakuten, Ibotta)\n"
        "- Flag subscribe-and-save price gaps\n"
        "- Note coupon stacking potential\n"
        "- Verify product is not IP restricted\n"
        "- Check for Hazmat restrictions\n\n"
        "Return ONLY a JSON array. No explanation. Start with [ end with ].\n"
        "Required fields: name, asin, source, buy_cost, sell_price, bsr, sellers, "
        "monthly_sales, roi, replenishable, risk_flags, recommendation, reason, type\n"
        "type='oa' recommendation=BUY/WATCH/PASS replenishable=true/false\n"
        "Use STRING values for prices and BSR.\n"
        "risk_flags must be an ARRAY of strings.\n"
        "Example: [{\"name\":\"Product\",\"asin\":\"B00XXXXX\",\"source\":\"Walgreens clearance\","
        "\"buy_cost\":\"$4.99\",\"sell_price\":\"$16.49\",\"bsr\":\"#6,800\","
        "\"sellers\":4,\"monthly_sales\":280,\"roi\":\"52%\",\"replenishable\":true,"
        "\"risk_flags\":[],\"recommendation\":\"BUY\","
        "\"reason\":\"Recurring CVS cycle, strong margins\",\"type\":\"oa\"}]"
    )

def run_agent_for_user(user_id: str, criteria: dict, ai_client) -> list:
    """Run both WS and OA searches for a specific user with their rotation."""
    leads = []
    now = datetime.now().isoformat()

    # Wholesale search
    try:
        ws_prompt = build_ws_prompt(user_id, criteria)
        resp = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": ws_prompt}]
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        ws_leads = extract_json(raw) or []
        for l in ws_leads:
            l["found_at"] = now
            l["user_id"] = user_id
            leads.append(normalize_lead(l))
        log.info("User " + user_id[:8] + ": " + str(len(ws_leads)) + " wholesale leads (slot " + str(get_user_rotation(user_id, len(WS_CATEGORIES))) + ")")
    except Exception as e:
        log.error("WS error for " + user_id[:8] + ": " + str(e))

    # Brief pause between calls
    time.sleep(5)

    # OA search (only if enabled)
    oa_cfg = criteria.get("online_arbitrage", {})
    if oa_cfg.get("enabled", True):
        try:
            oa_prompt = build_oa_prompt(user_id, criteria)
            resp2 = ai_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1500,
                messages=[{"role": "user", "content": oa_prompt}]
            )
            raw2 = "".join(b.text for b in resp2.content if hasattr(b, "text")).strip()
            oa_leads = extract_json(raw2) or []
            for l in oa_leads:
                l["found_at"] = now
                l["user_id"] = user_id
                leads.append(normalize_lead(l))
            log.info("User " + user_id[:8] + ": " + str(len(oa_leads)) + " OA leads (slot " + str(get_user_rotation(user_id, len(OA_SOURCES_POOL))) + ")")
        except Exception as e:
            log.error("OA error for " + user_id[:8] + ": " + str(e))

    return leads

def get_lead_history_days(tier: str) -> int:
    """Lead history window per tier."""
    return {
        "trial":   3,    # Trial gets 3 days — enough to evaluate
        "starter": 7,    # 7-day rolling window
        "pro":     30,   # 30-day trend analysis
        "agency":  90,   # Full quarter of data
        "custom":  90,   # Custom gets agency-level history
    }.get(tier, 7)

def get_leads_per_cycle(tier: str) -> int:
    """How many leads to generate per scan cycle."""
    return {
        "trial":   3,    # 50% of starter
        "starter": 5,    # 5 x 2 scans/day = 10/day, ~300/month
        "pro":     8,    # 8 x 3 scans/day = 24/day, ~720/month
        "agency":  12,   # 12 x 4 scans/day = 48/day, ~1440/month
        "custom":  25,   # Negotiated
    }.get(tier, 5)

def get_scan_interval(tier: str) -> int:
    """Scan interval in hours per tier."""
    return {
        "trial":   12,
        "starter": 12,
        "pro":     8,
        "agency":  6,
        "custom":  4,
    }.get(tier, 12)

def deduplicate_leads(leads: list) -> list:
    """Remove duplicate leads by ASIN."""
    seen = set()
    unique = []
    for l in leads:
        key = l.get("asin") or l.get("name", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(l)
    return unique
