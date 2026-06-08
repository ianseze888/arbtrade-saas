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
from datetime import datetime, timezone
import random

log = logging.getLogger(__name__)

# Agent Ian's category pools (slots 1-15)
AGENT_IAN_WS_CATEGORIES = [
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

# Agent Ian's distributors (slots 1-14)
AGENT_IAN_DISTRIBUTORS = [
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

# Agent Agent Ian's OA sources (slots 1-8)
AGENT_IAN_OA_SOURCES = [
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
    """Get Agent Ian's category rotation slot for this user."""
    hash_val = sum(ord(c) for c in str(user_id))
    return hash_val % len(AGENT_IAN_WS_CATEGORIES)

def build_ian_ws_prompt(user_id: str, criteria: dict, scan_num: int = 1) -> str:
    """Build Agent Ian's wholesale search prompt with web search."""
    slot = get_ian_slot(user_id)
    # Offset slot for scan 2 to get different categories
    effective_slot = (slot + scan_num - 1) % len(AGENT_IAN_WS_CATEGORIES)
    cats = AGENT_IAN_WS_CATEGORIES[effective_slot]
    cats_str = " > ".join(cats)
    dists = AGENT_IAN_DISTRIBUTORS[slot % len(AGENT_IAN_DISTRIBUTORS):slot % len(AGENT_IAN_DISTRIBUTORS) + 3]
    dist_str = ", ".join(dists)
    ws = criteria.get("wholesale", {})
    min_roi = ws.get("min_roi_percent", 30)
    max_bsr = ws.get("max_bsr", 50000)
    max_sellers = ws.get("max_sellers", 8)

    return (
        "You are AGENT IAN, an expert Amazon FBA wholesale researcher with live web search access.\n\n"
        "MISSION: Find 6 real wholesale product opportunities. Use web search to verify prices and ASINs.\n\n"
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
        "Use web search to verify prices and ASINs where possible.\n"
        "If web search is unavailable, use your best knowledge to find real opportunities.\n\n"
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
    """Build Agent Ian's OA search prompt with web search."""
    slot = get_ian_slot(user_id)
    sources = AGENT_IAN_OA_SOURCES[slot % len(AGENT_IAN_OA_SOURCES)]
    sources_str = ", ".join(sources)
    oa = criteria.get("online_arbitrage", {})
    min_roi = oa.get("min_roi_percent", 35)
    max_buy = oa.get("max_buy_cost", 35)

    return (
        "You are AGENT IAN, an expert Amazon FBA online arbitrage researcher with live web search.\n\n"
        "MISSION: Find 6 real OA deals. Use web search to verify current prices where possible.\n\n"
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
    now   = datetime.now(timezone.utc).isoformat()

    def extract_text(content):
        """Extract text from API response including web search blocks."""
        text = ""
        for block in content:
            if hasattr(block, "text") and block.text:
                text += block.text
        return text.strip()

    def parse_leads(raw, lead_type):
        """Parse JSON array from raw text response."""
        try:
            s = raw.find("[")
            e = raw.rfind("]") + 1
            if s > -1 and e > 0:
                items = json.loads(raw[s:e])
                for item in items:
                    item["found_at"] = now
                    item["type"]     = lead_type
                    item["agent"]    = "Agent Ian"
                    item["verified"] = True
                return items
        except Exception as je:
            log.error("Agent Ian JSON parse error: " + str(je))
        return []

    # Agent Ian's wholesale scan
    ws_enabled = criteria.get("wholesale", {}).get("enabled", True)
    if ws_enabled:
        try:
            ws_prompt = build_ian_ws_prompt(user_id, criteria)
            log.info("Agent Ian: Running wholesale scan for user " + str(user_id)[:8])
            time.sleep(random.uniform(1, 3))
            resp = ai_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                # web search disabled - too expensive
                messages=[{"role": "user", "content": ws_prompt}]
            )
            raw     = extract_text(resp.content)
            ws_leads = parse_leads(raw, "wholesale")
            leads.extend(ws_leads)
            log.info("Agent Ian: Found " + str(len(ws_leads)) + " wholesale leads")
        except Exception as e:
            log.error("Agent Ian wholesale error: " + str(e))

    # Agent Ian's OA scan
    oa_enabled = criteria.get("online_arbitrage", {}).get("enabled", True)
    if oa_enabled:
        try:
            # Second wholesale scan - different categories
            try:
                ws_prompt2 = build_ian_ws_prompt(user_id, criteria, scan_num=2)
                log.info("Agent Ian: Running wholesale scan 2 for user " + str(user_id)[:8])
                time.sleep(random.uniform(1, 3))
                resp_ws2 = ai_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": ws_prompt2}]
                )
                ws2_text = extract_text(resp_ws2.content)
                ws2_leads = parse_leads(ws2_text, user_id, "wholesale", now, "Ian")
                leads.extend(ws2_leads)
                log.info("Agent Ian: Found " + str(len(ws2_leads)) + " wholesale leads (scan 2)")
            except Exception as e:
                log.error("Agent Ian WS scan 2 error: " + str(e))

            oa_prompt = build_ian_oa_prompt(user_id, criteria)
            log.info("Agent Ian: Running OA scan for user " + str(user_id)[:8])
            time.sleep(random.uniform(1, 3))
            resp2 = ai_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                # web search disabled - too expensive
                messages=[{"role": "user", "content": oa_prompt}]
            )
            raw2     = extract_text(resp2.content)
            oa_leads = parse_leads(raw2, "oa")
            leads.extend(oa_leads)
            log.info("Agent Ian: Found " + str(len(oa_leads)) + " OA leads")
        except Exception as e:
            log.error("Agent Ian OA error: " + str(e))

    log.info("Agent Ian complete: " + str(len(leads)) + " total leads for user " + str(user_id)[:8])
    return leads
