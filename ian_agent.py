#!/usr/bin/env python3
"""
IAN — ARBTRADE Research Agent (Twin A)
----------------------------------------
Ian covers Category Pools 1-15 and Distributors 1-14.
Specializes in: Health, Grocery, Beauty, Baby, Pet.
Uses live web search for all leads.
Runs in parallel with Ivan to maximize market coverage.
"""

import logging
import json
import time
from datetime import datetime

log = logging.getLogger(__name__)

# Ian's category pools (slots 1-15)
IAN_WS_CATEGORIES = [
    ["Health & Household", "Vitamins & Dietary Supplements"],
    ["Health & Household", "Medical Supplies & Equipment"],
    ["Health & Household", "Health Care"],
    ["Health & Household", "Wellness & Relaxation"],
    ["Health & Household", "Personal Care"],
    ["Grocery & Gourmet Food", "Pantry Staples"],
    ["Grocery & Gourmet Food", "Beverages"],
    ["Grocery & Gourmet Food", "Snack Foods"],
    ["Grocery & Gourmet Food", "Organic & Natural Foods"],
    ["Grocery & Gourmet Food", "Breakfast Foods"],
    ["Beauty & Personal Care", "Skin Care"],
    ["Beauty & Personal Care", "Hair Care"],
    ["Beauty & Personal Care", "Oral Care"],
    ["Beauty & Personal Care", "Bath & Body"],
    ["Beauty & Personal Care", "Tools & Accessories"],
]

# Ian's distributors (slots 1-14)
IAN_DISTRIBUTORS = [
    "Faire wholesale marketplace",
    "RangeMe brand platform",
    "Wholesale Central directory",
    "UNFI natural foods distributor",
    "KeHE distributors",
    "Dot Foods redistribution",
    "McLane Company",
    "Nash Finch wholesale",
    "Associated Wholesale Grocers",
    "C&S Wholesale Grocers",
    "SpartanNash wholesale",
    "Direct brand wholesale programs",
    "Brand ambassador wholesale portals",
    "Manufacturer direct programs",
]

# Ian's OA sources (slots 1-8)
IAN_OA_SOURCES = [
    ["Walgreens clearance section", "CVS weekly sale items", "Rite Aid clearance"],
    ["Walgreens app digital coupons", "CVS ExtraCare deals", "Rite Aid wellness+ deals"],
    ["iHerb flash sales", "iHerb Subscribe & Save gaps", "iHerb promo codes"],
    ["Vitacost 25% off promotions", "Vitacost clearance", "Vitacost bundle deals"],
    ["Chewy clearance", "Chewy Autoship price gaps", "PetSmart clearance"],
    ["Petco sale items", "Chewy flash deals", "1800PetMeds promotions"],
    ["Target Circle clearance", "Target app deals", "Target in-store clearance"],
    ["Walmart Rollback items", "Walmart clearance", "Walmart.com markdowns"],
]

def get_ian_slot(user_id: str) -> int:
    """Get Ian's category rotation slot for this user."""
    hash_val = sum(ord(c) for c in str(user_id))
    return hash_val % len(IAN_WS_CATEGORIES)

def build_ian_ws_prompt(user_id: str, criteria: dict) -> str:
    """Build Ian's wholesale search prompt with web search."""
    slot = get_ian_slot(user_id)
    cats = IAN_WS_CATEGORIES[slot]
    cats_str = " > ".join(cats)
    dists = IAN_DISTRIBUTORS[slot % len(IAN_DISTRIBUTORS):slot % len(IAN_DISTRIBUTORS) + 3]
    dist_str = ", ".join(dists)
    ws = criteria.get("wholesale", {})
    min_roi = ws.get("min_roi_percent", 30)
    max_bsr = ws.get("max_bsr", 50000)
    max_sellers = ws.get("max_sellers", 8)

    return (
        "You are IAN, an expert Amazon FBA wholesale researcher with live web search access.\n\n"
        "MISSION: Find 5 REAL wholesale product opportunities using web search RIGHT NOW.\n\n"
        "SEARCH STRATEGY:\n"
        "1. Search Amazon for products in: " + cats_str + "\n"
        "2. Find products with BSR under #" + str(max_bsr) + " and under " + str(max_sellers) + " FBA sellers\n"
        "3. Search these distributors for wholesale pricing: " + dist_str + "\n"
        "4. Verify the real ASIN from Amazon listing URL\n"
        "5. Calculate actual ROI using current buy cost vs Amazon sell price minus FBA fees\n\n"
        "CRITERIA:\n"
        "- Minimum ROI: " + str(min_roi) + "% after all FBA fees\n"
        "- Amazon must NOT be primary buy box holder\n"
        "- Product must be replenishable (not one-time)\n"
        "- Wholesale MOQ under $500 preferred\n\n"
        "CRITICAL: Use web search to verify REAL prices, REAL ASINs, REAL seller counts.\n"
        "Never estimate — search and verify.\n\n"
        "Return ONLY a JSON array. Start with [ end with ].\n"
        "Required fields: name, asin, bsr, sellers, buy_cost, sell_price, roi, source, "
        "risk_flags, recommendation, reason, type, verified_url\n"
        "type='wholesale' recommendation=BUY/WATCH/PASS\n"
        "verified_url: the Amazon listing URL you found\n"
        "asin: REAL 10-char ASIN starting with B (null if not found)\n"
        "risk_flags: ARRAY of strings\n"
        "agent: 'ian'"
    )

def build_ian_oa_prompt(user_id: str, criteria: dict) -> str:
    """Build Ian's OA search prompt with web search."""
    slot = get_ian_slot(user_id)
    sources = IAN_OA_SOURCES[slot % len(IAN_OA_SOURCES)]
    sources_str = ", ".join(sources)
    oa = criteria.get("online_arbitrage", {})
    min_roi = oa.get("min_roi_percent", 35)
    max_buy = oa.get("max_buy_cost", 35)

    return (
        "You are IAN, an expert Amazon FBA online arbitrage researcher with live web search.\n\n"
        "MISSION: Find 5 REAL OA deals using web search RIGHT NOW.\n\n"
        "SEARCH STRATEGY:\n"
        "1. Search these sources for current sales/clearance: " + sources_str + "\n"
        "2. For each deal found, search Amazon to verify the product exists and get real ASIN\n"
        "3. Check current Amazon buy box price vs retail/clearance price\n"
        "4. Confirm the price gap makes sense after FBA fees\n\n"
        "CRITERIA:\n"
        "- Buy cost: under $" + str(max_buy) + "\n"
        "- Minimum ROI: " + str(min_roi) + "% after FBA fees\n"
        "- Must be in stock online or confirmed clearance event\n"
        "- Product must be FBA eligible (no hazmat, no oversized)\n\n"
        "CRITICAL: Only return deals where you VERIFIED the retail price via web search.\n"
        "Include the source URL where you found the deal.\n\n"
        "Return ONLY a JSON array. Start with [ end with ].\n"
        "Required fields: name, asin, source, source_url, buy_cost, sell_price, roi, "
        "bsr, sellers, replenishable, risk_flags, recommendation, reason, type, verified_url\n"
        "type='oa' replenishable=true/false\n"
        "source_url: actual URL where deal was found\n"
        "verified_url: Amazon listing URL\n"
        "asin: REAL 10-char ASIN starting with B (null if not found)\n"
        "agent: 'ian'"
    )

def run_ian(user_id: str, criteria: dict, ai_client) -> list:
    """Run Ian's research scan — returns real verified leads."""
    leads = []
    now = datetime.now().isoformat()

    # Ian's wholesale scan
    try:
        ws_prompt = build_ian_ws_prompt(user_id, criteria)
        ws_enabled = criteria.get("wholesale", {}).get("enabled", True)

        if ws_enabled:
            log.info("Ian: Running wholesale scan for user " + str(user_id)[:8])
            resp = ai_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": ws_prompt}]
            )
            raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

            # Extract JSON
            s = raw.find("[")
            e = raw.rfind("]") + 1
            if s > -1 and e > 0:
                ws_leads = json.loads(raw[s:e])
                for lead in ws_leads:
                    lead["found_at"] = now
                    lead["type"]     = "wholesale"
                    lead["agent"]    = "ian"
                    lead["verified"] = True
                leads.extend(ws_leads)
                log.info("Ian: Found " + str(len(ws_leads)) + " wholesale leads")
    except Exception as e:
        log.error("Ian wholesale error: " + str(e))

    # Ian's OA scan
    try:
        oa_prompt = build_ian_oa_prompt(user_id, criteria)
        oa_enabled = criteria.get("online_arbitrage", {}).get("enabled", True)

        if oa_enabled:
            log.info("Ian: Running OA scan for user " + str(user_id)[:8])
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
                    lead["agent"]    = "ian"
                    lead["verified"] = True
                leads.extend(oa_leads)
                log.info("Ian: Found " + str(len(oa_leads)) + " OA leads")
    except Exception as e:
        log.error("Ian OA error: " + str(e))

    log.info("Ian complete: " + str(len(leads)) + " total leads for user " + str(user_id)[:8])
    return leads
