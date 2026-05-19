#!/usr/bin/env python3
"""
ARBTRADE Market Intelligence Agent (Agent 5)
----------------------------------------------
Spots trends, seasonal opportunities, and market shifts.
Runs daily and delivers insights to Pro/Agency users.

Tracks:
1. Trending categories on Amazon
2. Seasonal product opportunities
3. Emerging niches with low competition
4. Price gap opportunities
5. Supply chain disruptions (opportunities)
6. Holiday/event driven demand spikes
"""

import logging
import json
from datetime import datetime

log = logging.getLogger(__name__)

# US Market intelligence prompts
US_INTEL_PROMPTS = [
    {
        "focus": "Seasonal Trends",
        "prompt": (
            "You are an Amazon FBA market intelligence analyst. "
            "Based on current date " + datetime.now().strftime("%B %Y") + ", identify:\n"
            "1. Top 5 product categories with RISING demand right now\n"
            "2. Seasonal products approaching peak selling period\n"
            "3. Products to AVOID buying now (going off-peak)\n"
            "4. Upcoming events/holidays driving demand in next 30-60 days\n\n"
            "Focus on wholesale-friendly categories: Health, Baby, Pet, Grocery, Beauty.\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "rising_categories": ["category1", "category2"],\n'
            '  "peak_products": [{"name": "product type", "reason": "why now", "urgency": "high"}],\n'
            '  "avoid_now": ["product type to avoid"],\n'
            '  "upcoming_events": [{"event": "name", "days_away": 30, "categories": ["cat1"]}],\n'
            '  "top_opportunity": "single best opportunity right now"\n'
            "}"
        )
    },
    {
        "focus": "Low Competition Niches",
        "prompt": (
            "You are an Amazon FBA market intelligence analyst for " + datetime.now().strftime("%B %Y") + ".\n"
            "Identify emerging product niches with:\n"
            "- Low seller count (under 10 FBA sellers)\n"
            "- Strong BSR (under 50,000 in main category)\n"
            "- No Amazon retail presence\n"
            "- Wholesale sourceable from US distributors\n"
            "- $15-50 price range\n"
            "- 30%+ ROI potential\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "niches": [\n'
            '    {"name": "niche name", "category": "Amazon category", "avg_bsr": "#10000", '
            '"avg_sellers": 5, "roi_potential": "35-45%", "source": "where to find", "urgency": "medium"}\n'
            '  ],\n'
            '  "best_niche": "single best niche to enter now"\n'
            "}"
        )
    },
    {
        "focus": "Price Gap Opportunities",
        "prompt": (
            "You are an Amazon FBA market intelligence analyst for " + datetime.now().strftime("%B %Y") + ".\n"
            "Identify price gap opportunities where:\n"
            "- Retail/drug store price is significantly higher than wholesale cost\n"
            "- Online stores have promotional pricing below Amazon FBA prices\n"
            "- Bundle opportunities exist (combine 2-3 products for higher margin)\n"
            "- Multi-pack arbitrage (buy singles, sell multipacks)\n\n"
            "Focus on: Health & Household, Beauty, Grocery, Pet, Baby\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "price_gaps": [\n'
            '    {"opportunity": "description", "type": "wholesale|oa|bundle|multipack", '
            '"estimated_roi": "40%", "source": "where to buy", "action": "what to do"}\n'
            '  ],\n'
            '  "best_opportunity": "single best price gap right now"\n'
            "}"
        )
    }
]

# International market prompts
INTL_INTEL_PROMPTS = {
    "CA": {
        "focus": "Canada Market Intelligence",
        "prompt": (
            "You are an Amazon Canada FBA market intelligence analyst for " + datetime.now().strftime("%B %Y") + ".\n"
            "Identify top opportunities for Amazon.ca:\n"
            "- Products with less competition than Amazon.com\n"
            "- Canadian-specific seasonal trends\n"
            "- Products that sell well in Canadian climate/culture\n"
            "- US brands available for resale in Canada\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "top_categories": ["category1", "category2"],\n'
            '  "seasonal": [{"product": "name", "peak": "month", "reason": "why"}],\n'
            '  "advantages_over_us": ["reason1", "reason2"],\n'
            '  "best_opportunity": "single best Canada opportunity"\n'
            "}"
        )
    },
    "MX": {
        "focus": "Mexico Market Intelligence",
        "prompt": (
            "You are an Amazon Mexico FBA market intelligence analyst for " + datetime.now().strftime("%B %Y") + ".\n"
            "Identify top opportunities for Amazon.com.mx:\n"
            "- Growing product categories in Mexico\n"
            "- Products with very low competition\n"
            "- US brands with strong Mexican demand\n"
            "- Cultural/seasonal events driving demand\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "top_categories": ["category1", "category2"],\n'
            '  "low_competition": [{"product": "name", "sellers": 3, "opportunity": "why"}],\n'
            '  "cultural_events": [{"event": "name", "month": "month", "products": ["product"]}],\n'
            '  "best_opportunity": "single best Mexico opportunity"\n'
            "}"
        )
    },
    "UK": {
        "focus": "UK Market Intelligence",
        "prompt": (
            "You are an Amazon UK FBA market intelligence analyst for " + datetime.now().strftime("%B %Y") + ".\n"
            "Identify top opportunities for Amazon.co.uk:\n"
            "- Products trending in UK health/wellness market\n"
            "- Post-Brexit import opportunities\n"
            "- UK-specific seasonal trends\n"
            "- Categories with less saturation than US\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "top_categories": ["category1", "category2"],\n'
            '  "trending": [{"product": "name", "trend": "why trending", "roi_potential": "35%"}],\n'
            '  "seasonal": [{"product": "name", "peak": "month"}],\n'
            '  "best_opportunity": "single best UK opportunity"\n'
            "}"
        )
    }
}

def run_market_intel(ai_client, markets: list = ["US"]) -> dict:
    """
    Run market intelligence for specified markets.
    markets: list of market codes ["US", "CA", "MX", "UK"]
    """
    results = {}

    # US Market Intelligence
    if "US" in markets:
        us_intel = {}
        log.info("Running US market intelligence...")
        for intel in US_INTEL_PROMPTS:
            try:
                resp = ai_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=600,
                    messages=[{"role": "user", "content": intel["prompt"]}]
                )
                raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
                s = raw.find("{")
                e = raw.rfind("}") + 1
                if s > -1:
                    us_intel[intel["focus"]] = json.loads(raw[s:e])
                    log.info("US intel: " + intel["focus"] + " complete")
            except Exception as ex:
                log.error("US intel error " + intel["focus"] + ": " + str(ex))

        results["US"] = us_intel

    # International Markets
    for market in markets:
        if market in INTL_INTEL_PROMPTS and market != "US":
            log.info("Running " + market + " market intelligence...")
            try:
                intel = INTL_INTEL_PROMPTS[market]
                resp = ai_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=500,
                    messages=[{"role": "user", "content": intel["prompt"]}]
                )
                raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
                s = raw.find("{")
                e = raw.rfind("}") + 1
                if s > -1:
                    results[market] = json.loads(raw[s:e])
                    log.info(market + " intel complete")
            except Exception as ex:
                log.error(market + " intel error: " + str(ex))

    return results

def format_intel_for_digest(intel: dict) -> str:
    """Format market intelligence for daily digest email."""
    html = ""

    us = intel.get("US", {})

    # Best opportunity
    seasonal = us.get("Seasonal Trends", {})
    if seasonal.get("top_opportunity"):
        html += (
            '<div style="background:rgba(62,207,160,0.06);border:1px solid rgba(62,207,160,0.2);'
            'border-radius:8px;padding:14px 16px;margin-bottom:12px">'
            '<div style="font-size:11px;font-family:monospace;color:#3ECFA0;margin-bottom:6px">🎯 TOP OPPORTUNITY</div>'
            '<div style="font-size:13px;color:#f2efe8">' + seasonal["top_opportunity"] + '</div>'
            '</div>'
        )

    # Rising categories
    if seasonal.get("rising_categories"):
        cats = ", ".join(seasonal["rising_categories"][:3])
        html += (
            '<div style="margin-bottom:10px">'
            '<div style="font-size:11px;font-family:monospace;color:#888884;margin-bottom:4px">📈 RISING CATEGORIES</div>'
            '<div style="font-size:12px;color:#f2efe8">' + cats + '</div>'
            '</div>'
        )

    # Low competition niches
    niches = us.get("Low Competition Niches", {})
    if niches.get("best_niche"):
        html += (
            '<div style="margin-bottom:10px">'
            '<div style="font-size:11px;font-family:monospace;color:#888884;margin-bottom:4px">🔍 BEST NICHE RIGHT NOW</div>'
            '<div style="font-size:12px;color:#f2efe8">' + niches["best_niche"] + '</div>'
            '</div>'
        )

    # Price gap
    gaps = us.get("Price Gap Opportunities", {})
    if gaps.get("best_opportunity"):
        html += (
            '<div style="margin-bottom:10px">'
            '<div style="font-size:11px;font-family:monospace;color:#888884;margin-bottom:4px">💰 BEST PRICE GAP</div>'
            '<div style="font-size:12px;color:#f2efe8">' + gaps["best_opportunity"] + '</div>'
            '</div>'
        )

    return html

def save_intel_to_db(intel: dict, supabase_admin):
    """Save market intelligence report to database."""
    try:
        supabase_admin.table("health_logs").insert({
            "check_type": "market_intel",
            "status":     "ok",
            "message":    json.dumps(intel)[:2000],
            "checked_at": datetime.now().isoformat()
        }).execute()
        log.info("Market intel saved to DB")
    except Exception as e:
        log.error("Save intel error: " + str(e))
