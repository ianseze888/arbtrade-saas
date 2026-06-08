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
from datetime import datetime, timezone
import random

log = logging.getLogger(__name__)

# Agent Ivan's category pools (slots 16-30)
AGENT_IVAN_WS_CATEGORIES = [
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

# Agent Ivan's distributors (slots 15-29)
AGENT_IVAN_DISTRIBUTORS = [
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

# Agent Agent Ivan's OA sources (slots 9-15)
AGENT_IVAN_OA_SOURCES = [
    ["Costco.com overstock", "BJs Wholesale deals", "Sams Club clearance"],
    ["brand liquidation portals", "Direct brand overstock sales", "manufacturer closeouts"],
    ["Groupon Goods deals", "Woot daily deals", "Zulily flash sales"],
    ["Home Depot clearance", "Lowes clearance", "Office Depot rebates"],
    ["Kohl's clearance", "Bed Bath Beyond liquidation", "Tuesday Morning deals"],
    ["Thrive Market deals", "Grove Collaborative promotions", "Natural Grocers online"],
    ["6pm.com clearance", "Overstock.com deals", "Jet.com promotions"],
]

def get_ivan_slot(user_id: str) -> int:
    """Get Agent Ivan's category rotation slot — offset from Ian's."""
    hash_val = sum(ord(c) for c in str(user_id)) + 7  # Offset so they hit different categories
    return hash_val % len(AGENT_IVAN_WS_CATEGORIES)

def build_ivan_ws_prompt(user_id: str, criteria: dict, scan_num: int = 1) -> str:
    """Build Agent Ivan's wholesale search prompt with web search."""
    slot = get_ivan_slot(user_id)
    # Offset slot for scan 2 to get different categories
    effective_slot = (slot + scan_num - 1) % len(AGENT_IVAN_WS_CATEGORIES)
    cats = AGENT_IVAN_WS_CATEGORIES[effective_slot]
    cats_str = " > ".join(cats)
    dists = AGENT_IVAN_DISTRIBUTORS[slot % len(AGENT_IVAN_DISTRIBUTORS):slot % len(AGENT_IVAN_DISTRIBUTORS) + 3]
    dist_str = ", ".join(dists)
    ws = criteria.get("wholesale", {})
    min_roi = ws.get("min_roi_percent", 30)
    max_bsr = ws.get("max_bsr", 50000)
    max_sellers = ws.get("max_sellers", 8)

    return (
        "You are AGENT IVAN, an expert Amazon FBA wholesale researcher with live web search access.\n\n"
        "MISSION: Find 6 real wholesale product opportunities. Use web search to verify prices and ASINs.\n\n"
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
    """Build Agent Ivan's OA search prompt with web search."""
    slot = get_ivan_slot(user_id)
    sources = AGENT_IVAN_OA_SOURCES[slot % len(AGENT_IVAN_OA_SOURCES)]
    sources_str = ", ".join(sources)
    oa = criteria.get("online_arbitrage", {})
    min_roi = oa.get("min_roi_percent", 35)
    max_buy = oa.get("max_buy_cost", 35)

    return (
        "You are AGENT IVAN, an expert Amazon FBA online arbitrage researcher with live web search.\n\n"
        "MISSION: Find 6 real OA deals. Use web search to verify current prices where possible.\n\n"
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
                    item["agent"]    = "Agent Ivan"
                    item["verified"] = True
                return items
        except Exception as je:
            log.error("Agent Ivan JSON parse error: " + str(je))
        return []

    # Agent Ivan's wholesale scan
    ws_enabled = criteria.get("wholesale", {}).get("enabled", True)
    if ws_enabled:
        try:
            ws_prompt = build_ivan_ws_prompt(user_id, criteria)
            log.info("Agent Ivan: Running wholesale scan for user " + str(user_id)[:8])
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
            log.info("Agent Ivan: Found " + str(len(ws_leads)) + " wholesale leads")
        except Exception as e:
            log.error("Agent Ivan wholesale error: " + str(e))

    # Agent Ivan's OA scan
    oa_enabled = criteria.get("online_arbitrage", {}).get("enabled", True)
    if oa_enabled:
        try:
            # Second wholesale scan - different categories
            try:
                ws_prompt2 = build_ivan_ws_prompt(user_id, criteria, scan_num=2)
                log.info("Agent Ivan: Running wholesale scan 2 for user " + str(user_id)[:8])
                time.sleep(random.uniform(1, 3))
                resp_ws2 = ai_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": ws_prompt2}]
                )
                ws2_text = extract_text(resp_ws2.content)
                ws2_leads = parse_leads(ws2_text, user_id, "wholesale", now, "Ivan")
                leads.extend(ws2_leads)
                log.info("Agent Ivan: Found " + str(len(ws2_leads)) + " wholesale leads (scan 2)")
            except Exception as e:
                log.error("Agent Ivan WS scan 2 error: " + str(e))

            oa_prompt = build_ivan_oa_prompt(user_id, criteria)
            log.info("Agent Ivan: Running OA scan for user " + str(user_id)[:8])
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
            log.info("Agent Ivan: Found " + str(len(oa_leads)) + " OA leads")
        except Exception as e:
            log.error("Agent Ivan OA error: " + str(e))

    log.info("Agent Ivan complete: " + str(len(leads)) + " total leads for user " + str(user_id)[:8])
    return leads
