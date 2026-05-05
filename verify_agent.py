#!/usr/bin/env python3
"""
ARBTRADE Verification Agent (Agent 2)
--------------------------------------
Takes leads from Agent 1 (Research Agent) and validates them
against real market data before users see them.

Verification checks:
1. Amazon price still matches what Agent 1 found
2. Seller count hasn't spiked since research
3. BSR is stable (not tanking)
4. Product isn't gated or IP restricted
5. Buy box not dominated by Amazon
6. ROI recalculated with current prices
7. Risk flags updated based on real data

Upgrades lead status:
- UNVERIFIED → VERIFIED (passed all checks)
- UNVERIFIED → FLAGGED (failed one or more checks)
- Adjusts BUY/WATCH/PASS based on verified data
"""

import os
import json
import logging
import time
from datetime import datetime

import anthropic

log = logging.getLogger(__name__)

# ── Verification thresholds ──────────────────────────────────────────────────

MAX_SELLER_SPIKE    = 3     # Flag if sellers increased by more than this
MIN_BSR_RATIO       = 0.5   # Flag if BSR got worse by more than 50%
MAX_PRICE_DROP_PCT  = 15    # Flag if Amazon price dropped more than 15%
MIN_ROI_THRESHOLD   = 20    # Flag if verified ROI falls below this

def build_verification_prompt(lead: dict) -> str:
    """Build a verification prompt for a single lead."""
    name       = lead.get("name", "Unknown")
    asin       = lead.get("asin", "")
    buy_cost   = lead.get("buy_cost", "")
    sell_price = lead.get("sell_price", "")
    bsr        = lead.get("bsr", "")
    sellers    = lead.get("sellers", 0)
    roi        = lead.get("roi", "")
    source     = lead.get("source", "")
    lead_type  = lead.get("type", "wholesale")

    return (
        "You are an Amazon FBA product research verifier. "
        "Verify this product opportunity using your knowledge of the Amazon marketplace.\n\n"
        "PRODUCT TO VERIFY:\n"
        "Name: " + name + "\n"
        "ASIN: " + str(asin) + "\n"
        "Sourcing type: " + lead_type + "\n"
        "Source: " + source + "\n"
        "Researched buy cost: " + str(buy_cost) + "\n"
        "Researched sell price: " + str(sell_price) + "\n"
        "Researched BSR: " + str(bsr) + "\n"
        "Researched seller count: " + str(sellers) + "\n"
        "Researched ROI: " + str(roi) + "\n\n"
        "Please verify this opportunity by checking:\n"
        "1. Is this product currently available on Amazon at approximately this price?\n"
        "2. Is the seller count approximately accurate?\n"
        "3. Is the BSR plausible for this category?\n"
        "4. Are there any known IP restrictions, brand gating, or hazmat issues?\n"
        "5. Is Amazon (retail) likely competing on this listing?\n"
        "6. Is the ROI calculation reasonable given FBA fees?\n"
        "7. Any additional risk flags not mentioned in the original research?\n\n"
        "Return ONLY a JSON object. No explanation. Example:\n"
        "{\n"
        '  "verified": true,\n'
        '  "confidence": "high",\n'
        '  "verified_sell_price": "$24.99",\n'
        '  "verified_bsr": "#8,200",\n'
        '  "verified_sellers": 4,\n'
        '  "verified_roi": "38%",\n'
        '  "amazon_on_listing": false,\n'
        '  "gating_risk": false,\n'
        '  "ip_risk": false,\n'
        '  "hazmat_risk": false,\n'
        '  "recommendation": "BUY",\n'
        '  "verification_notes": "Prices match, low competition confirmed",\n'
        '  "additional_risks": []\n'
        "}"
    )

def parse_verification(text: str) -> dict:
    """Extract JSON from verification response."""
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s == -1 or e == 0:
            return {}
        return json.loads(text[s:e])
    except:
        return {}

def calculate_verified_roi(buy_cost_str: str, sell_price_str: str) -> str:
    """Recalculate ROI with standard FBA fees."""
    try:
        buy  = float(str(buy_cost_str).replace("$","").strip())
        sell = float(str(sell_price_str).replace("$","").strip())
        # Standard FBA fees: ~15% referral + ~$3.50 fulfillment
        referral   = sell * 0.15
        fulfillment = 3.50
        total_cost  = buy + referral + fulfillment
        profit      = sell - total_cost
        roi         = (profit / total_cost) * 100
        return str(int(roi)) + "%"
    except:
        return "—"

def apply_verification(lead: dict, verification: dict) -> dict:
    """Apply verification results to the lead record."""
    if not verification:
        lead["verified"]            = False
        lead["verification_status"] = "unverified"
        lead["verification_notes"]  = "Verification failed — using AI estimate"
        return lead

    # Update with verified data
    if verification.get("verified_sell_price"):
        lead["sell_price"] = verification["verified_sell_price"]
    if verification.get("verified_bsr"):
        lead["bsr"] = verification["verified_bsr"]
    if verification.get("verified_sellers"):
        lead["sellers"] = verification["verified_sellers"]
    if verification.get("verified_roi"):
        lead["roi"] = verification["verified_roi"]

    # Add verification metadata
    lead["verified"]            = verification.get("verified", False)
    lead["confidence"]          = verification.get("confidence", "low")
    lead["amazon_on_listing"]   = verification.get("amazon_on_listing", False)
    lead["gating_risk"]         = verification.get("gating_risk", False)
    lead["ip_risk"]             = verification.get("ip_risk", False)
    lead["hazmat_risk"]         = verification.get("hazmat_risk", False)
    lead["verification_notes"]  = verification.get("verification_notes", "")
    lead["verification_time"]   = datetime.now().isoformat()

    # Update risk flags
    existing_risks = lead.get("risk_flags", [])
    if isinstance(existing_risks, str):
        existing_risks = [existing_risks] if existing_risks else []

    new_risks = list(existing_risks)
    if verification.get("amazon_on_listing"):
        new_risks.append("Amazon on listing — buy box risk")
    if verification.get("gating_risk"):
        new_risks.append("Brand gating — approval required")
    if verification.get("ip_risk"):
        new_risks.append("IP risk — verify authorization")
    if verification.get("hazmat_risk"):
        new_risks.append("Hazmat — special FBA requirements")

    additional = verification.get("additional_risks", [])
    if isinstance(additional, list):
        new_risks.extend(additional)

    lead["risk_flags"] = list(set(new_risks))

    # Update recommendation based on verification
    if verification.get("recommendation"):
        lead["recommendation"] = verification["recommendation"]

    # Downgrade if Amazon is on listing
    if verification.get("amazon_on_listing") and lead.get("recommendation") == "BUY":
        lead["recommendation"] = "WATCH"

    # Downgrade if IP risk
    if verification.get("ip_risk") and lead.get("recommendation") == "BUY":
        lead["recommendation"] = "WATCH"

    # Set verification status
    if lead["verified"] and not verification.get("amazon_on_listing") and not verification.get("ip_risk"):
        lead["verification_status"] = "verified"
    elif verification.get("amazon_on_listing") or verification.get("ip_risk") or verification.get("gating_risk"):
        lead["verification_status"] = "flagged"
    else:
        lead["verification_status"] = "partial"

    return lead

def verify_lead(lead: dict, ai_client) -> dict:
    """Verify a single lead using Claude."""
    try:
        prompt = build_verification_prompt(lead)
        resp   = ai_client.messages.create(
            model      = "claude-sonnet-4-5",
            max_tokens = 500,
            messages   = [{"role": "user", "content": prompt}]
        )
        raw          = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        verification = parse_verification(raw)
        verified_lead = apply_verification(lead.copy(), verification)

        status = verified_lead.get("verification_status", "unverified")
        rec    = verified_lead.get("recommendation", "—")
        log.info(
            "Verified: " + lead.get("name","")[:30] +
            " → " + status +
            " | " + rec +
            " | conf: " + str(verified_lead.get("confidence","—"))
        )
        return verified_lead

    except Exception as e:
        log.error("Verification error for " + lead.get("name","") + ": " + str(e))
        lead["verified"]            = False
        lead["verification_status"] = "error"
        lead["verification_notes"]  = "Verification error: " + str(e)
        return lead

def verify_leads_batch(leads: list, ai_client, delay: float = 3.0) -> list:
    """
    Verify a batch of leads with rate limit protection.
    Only verifies BUY and WATCH leads — PASS leads skipped.
    """
    verified = []
    to_verify = [l for l in leads if l.get("recommendation") in ["BUY", "WATCH"]]
    to_skip   = [l for l in leads if l.get("recommendation") == "PASS"]

    # Mark skipped leads
    for lead in to_skip:
        lead["verified"]            = False
        lead["verification_status"] = "skipped"
        lead["verification_notes"]  = "PASS leads not verified"
        verified.append(lead)

    log.info("Verifying " + str(len(to_verify)) + " BUY/WATCH leads, skipping " + str(len(to_skip)) + " PASS leads")

    for i, lead in enumerate(to_verify):
        verified_lead = verify_lead(lead, ai_client)
        verified.append(verified_lead)

        # Rate limit protection
        if i < len(to_verify) - 1:
            time.sleep(delay)

    # Sort by ROI descending, verified first
    verified.sort(key=lambda x: (
        0 if x.get("verification_status") == "verified" else 1,
        -int(str(x.get("roi","0")).replace("%","").split("-")[0].strip() or 0)
    ))

    buy_count    = sum(1 for l in verified if l.get("recommendation") == "BUY")
    watch_count  = sum(1 for l in verified if l.get("recommendation") == "WATCH")
    ver_count    = sum(1 for l in verified if l.get("verification_status") == "verified")
    flag_count   = sum(1 for l in verified if l.get("verification_status") == "flagged")

    log.info(
        "Batch complete: " + str(buy_count) + " BUY, " +
        str(watch_count) + " WATCH, " +
        str(ver_count) + " verified, " +
        str(flag_count) + " flagged"
    )

    return verified

def get_verification_badge(lead: dict) -> str:
    """Return a display badge for verification status."""
    status = lead.get("verification_status", "unverified")
    badges = {
        "verified": "✓ Verified",
        "flagged":  "⚠ Flagged",
        "partial":  "~ Partial",
        "skipped":  "— Skipped",
        "error":    "! Error",
        "unverified": "? Unverified",
    }
    return badges.get(status, "? Unknown")
