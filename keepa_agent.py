#!/usr/bin/env python3
"""
ARBTRADE Keepa Integration
-----------------------------
Verifies leads using real Amazon data from Keepa API.
Replaces AI guessing with real market data:
- Real BSR and 90-day trend
- Real seller count
- Real buy box price and history
- Amazon on listing detection
- Price stability score
- Monthly sales estimate

Cost: 1 token per product lookup
Plan: Standard (60 tokens/min) = €129/month
Covers: ~500 subscribers comfortably
"""

import os
import json
import logging
import time
import requests
from datetime import datetime, timezone

log = logging.getLogger(__name__)

KEEPA_API_KEY  = os.getenv("KEEPA_API_KEY", "")
KEEPA_BASE_URL = "https://api.keepa.com"

# Amazon marketplace IDs
MARKETPLACE_IDS = {
    "US": 1,
    "CA": 6,
    "MX": 11,
    "UK": 3,
    "DE": 4,
    "JP": 5,
}

def get_keepa_headers() -> dict:
    return {"Content-Type": "application/json"}

def keepa_available() -> bool:
    """Check if Keepa API key is configured."""
    return bool(KEEPA_API_KEY and KEEPA_API_KEY != "")

def lookup_product(asin: str, marketplace: str = "US") -> dict:
    """
    Look up a single product on Keepa.
    Returns verified market data.
    Costs 1 Keepa token.
    """
    if not keepa_available():
        log.warning("Keepa API key not configured")
        return {}

    marketplace_id = MARKETPLACE_IDS.get(marketplace, 1)

    try:
        url = f"{KEEPA_BASE_URL}/product"
        params = {
            "key":       KEEPA_API_KEY,
            "domain":    marketplace_id,
            "asin":      asin,
            "stats":     90,        # 90-day statistics
            "offers":    20,        # Get offer data
            "history":   1,         # Price history
        }

        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("products"):
            log.warning("Keepa: No product found for ASIN " + asin)
            return {}

        product = data["products"][0]
        return parse_keepa_product(product, asin)

    except requests.exceptions.RequestException as e:
        log.error("Keepa API error for " + asin + ": " + str(e))
        return {}

def parse_keepa_product(product: dict, asin: str) -> dict:
    """Parse Keepa product data into ARBTRADE format."""
    try:
        # Basic product info
        title   = product.get("title", "")
        brand   = product.get("brand", "")

        # BSR data
        stats      = product.get("stats", {})
        bsr_current = None
        bsr_trend   = "unknown"

        # Get current BSR from stats
        sales_rank = product.get("salesRanks", {})
        if sales_rank:
            # Get the first category BSR
            for cat_id, ranks in sales_rank.items():
                if ranks and len(ranks) >= 2:
                    bsr_current = ranks[-1]  # Most recent
                    if len(ranks) >= 4:
                        bsr_30d = ranks[-3]
                        if bsr_30d and bsr_current:
                            if bsr_current < bsr_30d:
                                bsr_trend = "improving"  # Lower BSR = better
                            elif bsr_current > bsr_30d * 1.2:
                                bsr_trend = "declining"
                            else:
                                bsr_trend = "stable"
                    break

        # Price data (Keepa uses cents)
        csv = product.get("csv", [])
        buy_box_price = None
        amazon_price  = None

        # CSV index 0 = Amazon price, index 18 = Buy Box price
        try:
            if csv and len(csv) > 18 and csv[18]:
                recent = [x for x in csv[18][-20:] if x > 0]
                if recent:
                    buy_box_price = recent[-1] / 100  # Convert to dollars
        except:
            pass

        try:
            if csv and len(csv) > 0 and csv[0]:
                recent_amazon = [x for x in csv[0][-20:] if x > 0]
                if recent_amazon:
                    amazon_price = recent_amazon[-1] / 100
        except:
            pass

        # Seller count
        offers = product.get("offers", [])
        fba_sellers    = 0
        amazon_selling = False

        for offer in (offers or []):
            if offer.get("isFBA"):
                fba_sellers += 1
            if offer.get("isAmazon"):
                amazon_selling = True

        # If no offers data use stats
        if fba_sellers == 0 and stats:
            count = stats.get("current", {}).get("offerCountFBA", 0)
            fba_sellers = count or 0

        # Monthly sales estimate from 90-day stats
        monthly_sales = 0
        if stats and stats.get("current"):
            sold_30 = stats["current"].get("sold30", 0)
            if sold_30:
                monthly_sales = sold_30

        # Price stability (compare 90d avg vs current)
        price_stable = True
        if stats and stats.get("avg90", {}):
            avg90 = stats["avg90"].get("SALES", 0)
            if avg90 and buy_box_price:
                variance = abs(buy_box_price - avg90/100) / (avg90/100) if avg90 > 0 else 0
                price_stable = variance < 0.15  # Less than 15% variance = stable

        # Category
        categories = product.get("categories", [])
        category = categories[0] if categories else ""

        # Image
        images = product.get("imagesCSV", "")
        image_url = ""
        if images:
            first = images.split(",")[0]
            image_url = f"https://images-na.ssl-images-amazon.com/images/I/{first}"

        result = {
            "asin":            asin,
            "title":           title,
            "brand":           brand,
            "category":        str(category),
            "bsr_current":     bsr_current,
            "bsr_formatted":   "#" + "{:,}".format(bsr_current) if bsr_current else "—",
            "bsr_trend":       bsr_trend,
            "buy_box_price":   buy_box_price,
            "buy_box_formatted": "$" + "{:.2f}".format(buy_box_price) if buy_box_price else "—",
            "amazon_price":    amazon_price,
            "amazon_selling":  amazon_selling,
            "fba_sellers":     fba_sellers,
            "monthly_sales":   monthly_sales,
            "price_stable":    price_stable,
            "image_url":       image_url,
            "keepa_verified":  True,
            "verified_at":     datetime.now(timezone.utc).isoformat(),
            "amazon_url":      f"https://www.amazon.com/dp/{asin}",
        }

        log.info(
            "Keepa verified: " + asin +
            " | BSR: " + str(result["bsr_formatted"]) +
            " | Sellers: " + str(fba_sellers) +
            " | BB: " + str(result["buy_box_formatted"]) +
            " | Amazon: " + str(amazon_selling)
        )

        return result

    except Exception as e:
        log.error("Keepa parse error for " + asin + ": " + str(e))
        return {}

def verify_lead_with_keepa(lead: dict, marketplace: str = "US") -> dict:
    """
    Verify a single lead using Keepa data.
    Updates lead with real market data.
    Returns enriched lead.
    """
    asin = lead.get("asin", "")

    # Validate ASIN format
    if not asin or len(str(asin)) != 10 or not str(asin).startswith("B"):
        lead["keepa_verified"]  = False
        lead["keepa_skip_reason"] = "Invalid ASIN"
        return lead

    keepa_data = lookup_product(asin, marketplace)

    if not keepa_data:
        lead["keepa_verified"]    = False
        lead["keepa_skip_reason"] = "Product not found in Keepa"
        return lead

    # Update lead with verified Keepa data
    if keepa_data.get("bsr_formatted"):
        lead["bsr"] = keepa_data["bsr_formatted"]
    if keepa_data.get("buy_box_formatted"):
        lead["sell_price"] = keepa_data["buy_box_formatted"]
    if keepa_data.get("fba_sellers") is not None:
        lead["sellers"] = keepa_data["fba_sellers"]
    if keepa_data.get("monthly_sales"):
        lead["monthly_sales"] = keepa_data["monthly_sales"]

    # Add Keepa enrichment
    lead["keepa_verified"]   = True
    lead["bsr_trend"]        = keepa_data.get("bsr_trend", "unknown")
    lead["amazon_selling"]   = keepa_data.get("amazon_selling", False)
    lead["price_stable"]     = keepa_data.get("price_stable", True)
    lead["amazon_url"]       = keepa_data.get("amazon_url", "")
    lead["keepa_brand"]      = keepa_data.get("brand", "")
    lead["keepa_category"]   = keepa_data.get("category", "")

    # Recalculate recommendation based on real data
    if keepa_data.get("amazon_selling"):
        lead["recommendation"] = "WATCH"
        risks = lead.get("risk_flags", [])
        if isinstance(risks, list) and "Amazon on listing" not in str(risks):
            risks.append("Amazon on listing — buy box risk")
        lead["risk_flags"] = risks

    if keepa_data.get("fba_sellers", 0) > 10:
        if lead.get("recommendation") == "BUY":
            lead["recommendation"] = "WATCH"

    if keepa_data.get("bsr_trend") == "declining":
        risks = lead.get("risk_flags", [])
        if isinstance(risks, list):
            risks.append("BSR declining — demand may be dropping")
        lead["risk_flags"] = risks

    # Recalculate ROI with verified sell price
    try:
        buy_cost   = float(str(lead.get("buy_cost","0")).replace("$","").strip())
        sell_price = keepa_data.get("buy_box_price", 0) or float(str(lead.get("sell_price","0")).replace("$","").strip())
        if buy_cost > 0 and sell_price > 0:
            referral    = sell_price * 0.15
            fulfillment = 3.50
            total_cost  = buy_cost + referral + fulfillment
            profit      = sell_price - total_cost
            roi         = (profit / total_cost) * 100
            lead["roi"] = str(int(roi)) + "%"
            lead["roi_verified"] = True
    except:
        pass

    return lead

def verify_leads_batch_keepa(leads: list, marketplace: str = "US", delay: float = 1.0) -> list:
    """
    Verify a batch of leads with Keepa.
    Only verifies BUY and WATCH leads with valid ASINs.
    Respects rate limits with delay between calls.
    """
    if not keepa_available():
        log.info("Keepa not configured — skipping verification")
        return leads

    to_verify  = [l for l in leads if l.get("recommendation") in ["BUY","WATCH"] and l.get("asin") and len(str(l.get("asin",""))) == 10]
    to_skip    = [l for l in leads if l not in to_verify]

    log.info("Keepa: Verifying " + str(len(to_verify)) + " leads, skipping " + str(len(to_skip)))

    verified = list(to_skip)

    for i, lead in enumerate(to_verify):
        enriched = verify_lead_with_keepa(lead.copy(), marketplace)
        verified.append(enriched)
        if i < len(to_verify) - 1:
            time.sleep(delay)

    # Sort: BUY first, then by ROI
    verified.sort(key=lambda x: (
        0 if x.get("recommendation") == "BUY" else 1,
        -int(str(x.get("roi","0")).replace("%","").split("-")[0].strip() or 0)
    ))

    keepa_verified = sum(1 for l in verified if l.get("keepa_verified"))
    log.info("Keepa batch complete: " + str(keepa_verified) + "/" + str(len(leads)) + " verified")

    return verified

def get_token_usage() -> dict:
    """Check remaining Keepa tokens."""
    if not keepa_available():
        return {"available": False}
    try:
        resp = requests.get(
            KEEPA_BASE_URL + "/token",
            params={"key": KEEPA_API_KEY},
            timeout=10
        )
        data = resp.json()
        return {
            "available":     True,
            "tokens_left":   data.get("tokensLeft", 0),
            "tokens_minute": data.get("tokensPerMinute", 0),
            "refill_rate":   data.get("refillRate", 0),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
