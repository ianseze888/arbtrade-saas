#!/usr/bin/env python3
"""
ARBTRADE Agent 3 — Supplier Outreach Agent
-------------------------------------------
Triggered when a user approves a lead.
Finds the real supplier contact and drafts
a professional outreach email.

Flow:
1. Receive approved lead + user business profile
2. Search for supplier contact (website, email, application URL)
3. Draft personalized outreach email
4. Auto-add supplier to user's CRM
5. Return supplier details + email draft
"""

import logging
import json
import time
from datetime import datetime

log = logging.getLogger(__name__)

# Known wholesale marketplace URLs and contact approaches
KNOWN_SOURCES = {
    'faire':       {'url': 'https://www.faire.com/search?q=', 'apply': 'faire.com/brand/', 'contact': 'Apply via Faire marketplace'},
    'rangeme':     {'url': 'https://www.rangeme.com/products?q=', 'apply': 'rangeme.com', 'contact': 'Apply via RangeMe'},
    'tundra':      {'url': 'https://www.tundra.com/search?q=', 'apply': 'tundra.com', 'contact': 'Apply via Tundra'},
    'abound':      {'url': 'https://www.abound.com/search?q=', 'apply': 'abound.com', 'contact': 'Apply via Abound'},
    'unfi':        {'url': 'https://www.unfi.com', 'apply': 'unfi.com/become-a-customer', 'contact': 'customerservice@unfi.com'},
    'kehe':        {'url': 'https://www.kehe.com', 'apply': 'kehe.com/become-a-customer', 'contact': 'customerservice@kehe.com'},
    'mclane':      {'url': 'https://www.mclaneco.com', 'apply': 'mclaneco.com/contact', 'contact': 'Contact via McLane website'},
    'dot foods':   {'url': 'https://www.dotfoods.com', 'apply': 'dotfoods.com/contact', 'contact': 'Contact via Dot Foods website'},
    'wholesale central': {'url': 'https://www.wholesalecentral.com', 'apply': 'wholesalecentral.com', 'contact': 'Search Wholesale Central directory'},
}

def get_known_source(source: str) -> dict:
    """Check if source matches a known wholesale marketplace."""
    source_lower = source.lower()
    for key, data in KNOWN_SOURCES.items():
        if key in source_lower:
            return data
    return {}

def build_supplier_search_prompt(lead: dict, business_profile: dict) -> str:
    """Build prompt for Agent 3 to find supplier contact."""
    name     = lead.get("name", "")
    source   = lead.get("source", "")
    asin     = lead.get("asin", "")
    brand    = name.split()[0] if name else ""

    return (
        "You are Agent 3, an expert at finding wholesale supplier contacts for Amazon FBA sellers.\n\n"
        "TASK: Find the wholesale supplier contact for this product:\n"
        "Product: " + name + "\n"
        "Brand: " + brand + "\n"
        "Source: " + source + "\n"
        "ASIN: " + asin + "\n\n"
        "Use web search to find:\n"
        "1. The brand's official website\n"
        "2. Their wholesale/trade account application page\n"
        "3. A wholesale contact email if available\n"
        "4. Any authorized distributors for this brand\n"
        "5. Minimum order requirements if findable\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "brand_name": "exact brand name",\n'
        '  "brand_website": "https://...",\n'
        '  "wholesale_url": "https://... (direct link to wholesale page)",\n'
        '  "contact_email": "wholesale@brand.com or null",\n'
        '  "distributor": "distributor name if not direct",\n'
        '  "distributor_url": "https://...",\n'
        '  "moq": "minimum order amount or null",\n'
        '  "notes": "any relevant notes about getting approved",\n'
        '  "confidence": "high/medium/low"\n'
        "}"
    )

def build_outreach_email(lead: dict, supplier: dict, business_profile: dict) -> str:
    """Build personalized outreach email template."""
    biz_name     = business_profile.get("business_name", "our Amazon FBA business")
    contact_name = business_profile.get("contact_name", "")
    amazon_store = business_profile.get("amazon_store", "")
    budget       = business_profile.get("monthly_budget", "")
    years        = business_profile.get("years_selling", "")
    location     = business_profile.get("location", "")
    biz_email    = business_profile.get("business_email", "")

    product_name  = lead.get("name", "")
    brand_name    = supplier.get("brand_name", product_name.split()[0])
    supplier_name = supplier.get("distributor") or brand_name

    years_line    = f" We have been selling on Amazon for {years}." if years else ""
    budget_line   = f" Our monthly purchasing budget is {budget}." if budget else ""
    store_line    = f" Our Amazon store is '{amazon_store}'." if amazon_store else ""
    location_line = f" We are based in {location}." if location else ""

    subject = f"Wholesale Account Application — {biz_name}"

    body = f"""Subject: {subject}

Dear {supplier_name} Wholesale Team,

My name is {contact_name or 'the owner'} and I represent {biz_name}, an established Amazon FBA seller.{years_line}{location_line}

We recently identified {brand_name} products as an excellent fit for our Amazon storefront and would like to apply for a wholesale account.{store_line}{budget_line}

We are specifically interested in:
• {product_name}
• Any additional products in your catalog suitable for Amazon FBA

As an Amazon FBA seller we maintain high standards for product quality and compliance, and we are committed to proper MAP pricing and brand representation.

Could you please send us:
1. Your wholesale price list and catalog
2. Minimum order requirements
3. Account application form
4. Any brand authorization requirements for Amazon sellers

We look forward to building a long-term relationship with {brand_name}.

Best regards,
{contact_name or biz_name}
{biz_name}
{biz_email}
"""
    return body

def run_agent3(lead: dict, business_profile: dict, ai_client) -> dict:
    """
    Run Agent 3 to find supplier contact and draft outreach email.
    Returns supplier details and email draft.
    """
    result = {
        "lead_name":       lead.get("name", ""),
        "supplier_found":  False,
        "supplier":        {},
        "outreach_email":  "",
        "apply_url":       "",
        "timestamp":       datetime.now().isoformat()
    }

    try:
        # Check known sources first (no API call needed)
        source = lead.get("source", "")
        known  = get_known_source(source)

        if known:
            log.info("Agent 3: Known source found for " + source[:30])
            supplier = {
                "brand_name":    lead.get("name", "").split()[0],
                "brand_website": known.get("url", ""),
                "wholesale_url": known.get("apply", ""),
                "contact_email": known.get("contact", ""),
                "confidence":    "high"
            }
            result["supplier"]        = supplier
            result["supplier_found"]  = True
            result["apply_url"]       = known.get("apply", "")
            result["outreach_email"]  = build_outreach_email(lead, supplier, business_profile)
            return result

        # Use web search to find supplier
        prompt = build_supplier_search_prompt(lead, business_profile)
        log.info("Agent 3: Searching for supplier for " + lead.get("name", "")[:30])

        resp = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract response
        raw = ""
        for block in resp.content:
            if hasattr(block, "text") and block.text:
                raw += block.text
        raw = raw.strip()

        # Parse JSON
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s > -1 and e > 0:
            supplier = json.loads(raw[s:e])
            result["supplier"]       = supplier
            result["supplier_found"] = bool(supplier.get("brand_website"))
            result["apply_url"]      = supplier.get("wholesale_url") or supplier.get("brand_website", "")
            result["outreach_email"] = build_outreach_email(lead, supplier, business_profile)
            log.info("Agent 3: Found supplier for " + lead.get("name","")[:30] + " confidence=" + supplier.get("confidence","?"))
        else:
            log.warning("Agent 3: Could not parse supplier response")
            # Fallback
            brand = lead.get("name","").split()[0]
            result["apply_url"]     = f"https://www.google.com/search?q={brand}+wholesale+account+application"
            result["outreach_email"] = build_outreach_email(lead, {"brand_name": brand}, business_profile)

    except Exception as e:
        log.error("Agent 3 error: " + str(e))
        brand = lead.get("name","").split()[0]
        result["outreach_email"] = build_outreach_email(lead, {"brand_name": brand}, business_profile)

    return result

def add_to_supplier_crm(user_id: str, lead: dict, supplier: dict, supabase_admin) -> bool:
    """Auto-add found supplier to user's CRM."""
    try:
        brand_name = supplier.get("brand_name") or lead.get("name","").split()[0]

        # Check if already exists
        existing = supabase_admin.table("suppliers").select("id").eq(
            "user_id", user_id
        ).eq("name", brand_name).execute()

        if existing.data:
            log.info("Supplier already in CRM: " + brand_name)
            return True

        # Add new supplier
        supabase_admin.table("suppliers").insert({
            "user_id":  user_id,
            "name":     brand_name,
            "website":  supplier.get("brand_website", ""),
            "email":    supplier.get("contact_email", ""),
            "status":   "prospect",
            "notes":    "Auto-added by Agent 3 from approved lead: " + lead.get("name","")[:100],
        }).execute()

        log.info("Agent 3: Added " + brand_name + " to supplier CRM")
        return True

    except Exception as e:
        log.error("Agent 3 CRM error: " + str(e))
        return False
