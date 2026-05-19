#!/usr/bin/env python3
"""
IVAN — ARBTRADE Research Agent (Twin B)
-----------------------------------------
Ivan covers Category Pools 16-30 and Distributors 15-29.
Specializes in: Home, Sports, Office, Baby, Specialty.
Uses live web search for all leads.
Runs in parallel with Ian to maximize market coverage.
"""

import logging
import json
import time
from datetime import datetime

log = logging.getLogger(__name__)

# Ivan's category pools (slots 16-30)
IVAN_WS_CATEGORIES = [
    ["Baby", "Diapering & Potty Training"],
    ["Baby", "Feeding"],
    ["Baby", "Baby Care"],
    ["Pet Supplies", "Dog Supplies"],
    ["Pet Supplies", "Cat Supplies"],
    ["Home & Kitchen", "Kitchen & Dining"],
    ["Home & Kitchen", "Cleaning Supplies"],
    ["Home & Kitchen", "Bedding"],
    ["Home & Kitchen", "Storage & Organization"],
    ["Home & Kitchen", "Bath"],
    ["Sports & Outdoors", "Exercise & Fitness"],
    ["Sports & Outdoors", "Outdoor Recreation"],
    ["Sports & Outdoors", "Sports Nutrition"],
    ["Office Products", "Office & School Supplies"],
    ["Office Products", "Technology Accessories"],
]

# Ivan's distributors (slots 15-29)
IVAN_DISTRIBUTORS = [
    "Expo West trade show brands",
    "ASD Market Week suppliers",
    "Specialty Food Association members",
    "Natural Products Expo brands",
    "NY Now trade show",
    "National Hardware Show brands",
    "Tundra wholesale marketplace",
    "Abound wholesale platform",
    "Creoate wholesale marketplace",
    "SeeBiz wholesale directory",
    "Global Sources wholesale",
    "Faire exclusive brands",
    "RangeMe emerging brands",
    "Direct factory wholesale programs",
    "Regional distributor networks",
]

# Ivan's OA sources (slots 9-15)
IVAN_OA_SOURCES = [
    ["Costco.com overstock", "BJs Wholesale deals", "Sams Club clearance"],
    ["brand liquidation portals", "Direct brand overstock sales", "manufacturer closeouts"],
    ["Groupon Goods deals", "Woot daily deals", "Zulily flash sales"],
    ["Home Depot clearance", "Lowes clearance", "Office Depot rebates"],
    ["Kohl's clearance", "Bed Bath Beyond liquidation", "Tuesday Morning deals"],
    ["Thrive Market deals", "Grove Collaborative promotions", "Natural Grocers online"],
    ["6pm.com clearance", "Overstock.com deals", "Jet.com promotions"],
]

def get_ivan_slot(user_id: str) -> int:
    """Get Ivan's category rotation slot — offset from Ian's."""
    hash_val = sum(ord(c) for c in str(user_id)) + 7  # Offset so they hit different categories
    return hash_val % len(IVAN_WS_CATEGORIES)

def build_ivan_ws_prompt(user_id: str, criteria: dict) -> str:
    """Build Ivan's wholesale search prompt with web search."""
    slot = get_ivan_slot(user_id)
    cats = IVAN_WS_CATEGORIES[slot]
    cats_str = " > ".join(cats)
    dists = IVAN_DISTRIBUTORS[slot % len(IVAN_DISTRIBUTORS):slot % len(IVAN_DISTRIBUTORS) + 3]
    dist_str = ", ".join(dists)
    ws = criteria.get("wholesale", {})
    min_roi = ws.get("min_roi_percent", 30)
    max_bsr = ws.get("max_bsr", 50000)
    max_sellers = ws.get("max_sellers", 8)

    return (
        "You are IVAN, an expert Amazon FBA wholesale researcher with live web search access.\n\n"
        "MISSION: Find 5 REAL wholesale product opportunities using web search RIGHT NOW.\n\n"
        "SEARCH STRATEGY:\n"
        "1. Search Amazon for products in: " + cats_str + "\n"
        "2. Find products with BSR under #" + str(max_bsr) + " and under " + str(max_sellers) + " FBA sellers\n"
        "3. Search these distributors for wholesale pricing: " + dist_str + "\n"
        "4. Verify the real ASIN from Amazon listing URL\n"
        "5. Calculate ROI using current buy cost vs Amazon sell price minus FBA fees\n\n"
        "CRITERIA:\n"
        "- Minimum ROI: " + str(min_roi) + "% after all FBA fees\n"
        "- Amazon must NOT be primary buy box holder\n"
        "- Product must be replenishable\n"
        "- Wholesale MOQ under $500 preferred\n\n"
        "IMPORTANT: You and your twin Ian are covering different categories simultaneously.\n"
        "You cover: " + cats_str + "\n"
        "Focus exclusively on your assigned categories for maximum coverage.\n\n"
        "CRITICAL: Use web search to verify REAL prices, REAL ASINs, REAL seller counts.\n\n"
        "Return ONLY a JSON array. Start with [ end with ].\n"
        "Required fields: name, asin, bsr, sellers, buy_cost, sell_price, roi, source, "
        "risk_flags, recommendation, reason, type, verified_url\n"
        "type='wholesale' recommendation=BUY/WATCH/PASS\n"
        "verified_url: the Amazon listing URL you found\n"
        "asin: REAL 10-char ASIN starting with B (null if not found)\n"
        "risk_flags: ARRAY of strings\n"
        "agent: 'ivan'"
    )

def build_ivan_oa_prompt(user_id: str, criteria: dict) -> str:
    """Build Ivan's OA search prompt with web search."""
    slot = get_ivan_slot(user_id)
    sources = IVAN_OA_SOURCES[slot % len(IVAN_OA_SOURCES)]
    sources_str = ", ".join(sources)
    oa = criteria.get("online_arbitrage", {})
    min_roi = oa.get("min_roi_percent", 35)
    max_buy = oa.get("max_buy_cost", 35)

    return (
        "You are IVAN, an expert Amazon FBA online arbitrage researcher with live web search.\n\n"
        "MISSION: Find 5 REAL OA deals using web search RIGHT NOW.\n\n"
        "SEARCH STRATEGY:\n"
        "1. Search these sources for current sales/clearance: " + sources_str + "\n"
        "2. For each deal found, search Amazon to verify the ASIN and current buy box price\n"
        "3. Confirm the price gap creates real profit after FBA fees\n"
        "4. Check if product is available to buy online right now\n\n"
        "CRITERIA:\n"
        "- Buy cost: under $" + str(max_buy) + "\n"
        "- Minimum ROI: " + str(min_roi) + "% after FBA fees\n"
        "- Must be purchasable online right now\n"
        "- No hazmat, no oversized\n\n"
        "IMPORTANT: Your twin Ian is covering different OA sources.\n"
        "You focus exclusively on: " + sources_str + "\n\n"
        "CRITICAL: Only return deals you VERIFIED via web search.\n\n"
        "Return ONLY a JSON array. Start with [ end with ].\n"
        "Required fields: name, asin, source, source_url, buy_cost, sell_price, roi, "
        "bsr, sellers, replenishable, risk_flags, recommendation, reason, type, verified_url\n"
        "type='oa' replenishable=true/false\n"
        "source_url: actual URL where deal was found\n"
        "verified_url: Amazon listing URL\n"
        "asin: REAL 10-char ASIN starting with B (null if not found)\n"
        "agent: 'ivan'"
    )

def run_ivan(user_id: str, criteria: dict, ai_client) -> list:
    """Run Ivan's research scan — returns real verified leads."""
    leads = []
    now = datetime.now().isoformat()

    # Ivan's wholesale scan
    try:
        ws_prompt = build_ivan_ws_prompt(user_id, criteria)
        ws_enabled = criteria.get("wholesale", {}).get("enabled", True)

        if ws_enabled:
            log.info("Ivan: Running wholesale scan for user " + str(user_id)[:8])
            resp = ai_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": ws_prompt}]
            )
            raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

            s = raw.find("[")
            e = raw.rfind("]") + 1
            if s > -1 and e > 0:
                ws_leads = json.loads(raw[s:e])
                for lead in ws_leads:
                    lead["found_at"] = now
                    lead["type"]     = "wholesale"
                    lead["agent"]    = "ivan"
                    lead["verified"] = True
                leads.extend(ws_leads)
                log.info("Ivan: Found " + str(len(ws_leads)) + " wholesale leads")
    except Exception as e:
        log.error("Ivan wholesale error: " + str(e))

    # Ivan's OA scan
    try:
        oa_prompt = build_ivan_oa_prompt(user_id, criteria)
        oa_enabled = criteria.get("online_arbitrage", {}).get("enabled", True)

        if oa_enabled:
            log.info("Ivan: Running OA scan for user " + str(user_id)[:8])
            resp2 = ai_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": oa_prompt}]
            )
            raw2 = "".join(b.text for b in resp2.content if hasattr(b, "text")).strip()

            s = raw2.find("[")
            e = raw2.rfind("]") + 1
            if s > -1 and e > 0:
                oa_leads = json.loads(raw2[s:e])
                for lead in oa_leads:
                    lead["found_at"] = now
                    lead["type"]     = "oa"
                    lead["agent"]    = "ivan"
                    lead["verified"] = True
                leads.extend(oa_leads)
                log.info("Ivan: Found " + str(len(oa_leads)) + " OA leads")
    except Exception as e:
        log.error("Ivan OA error: " + str(e))

    log.info("Ivan complete: " + str(len(leads)) + " total leads for user " + str(user_id)[:8])
    return leads
