#!/usr/bin/env python3
"""
ARBTRADE Outreach Agent (Agent 3)
-----------------------------------
When a user approves a lead, this agent:
1. Finds the supplier's wholesale contact information
2. Drafts a personalized account opening email
3. Saves the outreach to the supplier CRM
4. Sets a follow-up reminder if no response in 48 hours

Triggered by: POST /leads/approve or manual from supplier CRM
"""

import logging
import json
import os
from datetime import datetime

log = logging.getLogger(__name__)

def build_contact_finder_prompt(product_name: str, source: str, categories: str) -> str:
    """Build prompt to find supplier contact info."""
    return (
        "You are an expert at finding wholesale supplier contact information.\n\n"
        "Find the wholesale/trade contact information for this supplier:\n"
        "Product: " + product_name + "\n"
        "Source/Platform: " + source + "\n"
        "Categories: " + categories + "\n\n"
        "Based on your knowledge, provide:\n"
        "1. The brand/supplier name\n"
        "2. Their wholesale application URL or contact method\n"
        "3. The typical wholesale email format (e.g. wholesale@brand.com)\n"
        "4. Whether they use Faire, RangeMe, or direct wholesale programs\n"
        "5. Any known minimum order requirements\n"
        "6. Whether they are known to be Amazon-friendly\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "supplier_name": "Brand Name",\n'
        '  "wholesale_url": "https://brand.com/wholesale",\n'
        '  "wholesale_email": "wholesale@brand.com",\n'
        '  "platform": "Faire",\n'
        '  "moq_estimate": "$300",\n'
        '  "amazon_friendly": true,\n'
        '  "notes": "Any relevant notes"\n'
        "}"
    )

def build_outreach_email_prompt(
    supplier_name: str,
    product_name: str,
    categories: str,
    platform: str,
    seller_name: str = "[Your Name]",
    business_name: str = "[Business Name]"
) -> str:
    """Build prompt to generate outreach email."""
    return (
        "Write a professional wholesale account opening email.\n\n"
        "Context:\n"
        "Supplier: " + supplier_name + "\n"
        "Product of interest: " + product_name + "\n"
        "Categories: " + categories + "\n"
        "Platform: " + platform + "\n"
        "Seller: " + seller_name + " at " + business_name + "\n\n"
        "Requirements:\n"
        "- Professional but warm tone\n"
        "- Mention specific product interest to show research\n"
        "- Reference Amazon FBA experience\n"
        "- Ask about wholesale pricing, MOQ, and payment terms\n"
        "- Express interest in long-term relationship\n"
        "- Under 200 words\n"
        "- End with clear call to action\n\n"
        "Return ONLY the email body text. No subject line. No JSON."
    )

def parse_contact_json(text: str) -> dict:
    """Extract JSON from contact finder response."""
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s == -1 or e == 0:
            return {}
        return json.loads(text[s:e])
    except:
        return {}

def find_supplier_contact(product_name: str, source: str, categories: str, ai_client) -> dict:
    """Use Claude to find supplier contact information."""
    try:
        prompt = build_contact_finder_prompt(product_name, source, categories)
        resp   = ai_client.messages.create(
            model      = "claude-sonnet-4-5",
            max_tokens = 400,
            messages   = [{"role": "user", "content": prompt}]
        )
        raw     = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        contact = parse_contact_json(raw)
        log.info("Found contact for " + product_name[:30] + ": " + contact.get("supplier_name","unknown"))
        return contact
    except Exception as e:
        log.error("Contact finder error: " + str(e))
        return {}

def generate_outreach_email(
    supplier_name: str,
    product_name: str,
    categories: str,
    platform: str,
    ai_client,
    seller_name: str = "[Your Name]",
    business_name: str = "[Business Name]"
) -> str:
    """Generate personalized outreach email using Claude."""
    try:
        prompt = build_outreach_email_prompt(
            supplier_name, product_name, categories,
            platform, seller_name, business_name
        )
        resp = ai_client.messages.create(
            model      = "claude-sonnet-4-5",
            max_tokens = 400,
            messages   = [{"role": "user", "content": prompt}]
        )
        email = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        log.info("Generated outreach email for " + supplier_name)
        return email
    except Exception as e:
        log.error("Email generation error: " + str(e))
        return ""

def run_outreach_for_lead(
    lead: dict,
    user_id: str,
    supabase_admin,
    ai_client,
    seller_name: str = "[Your Name]",
    business_name: str = "[Business Name]"
) -> dict:
    """
    Full outreach flow for an approved lead:
    1. Find supplier contact
    2. Generate email
    3. Save to supplier CRM
    4. Return outreach package
    """
    product_name = lead.get("name", "")
    source       = lead.get("source", "")
    lead_type    = lead.get("type", "wholesale")
    categories   = ", ".join(lead.get("categories", ["Health & Household"]))

    # Only run outreach for wholesale leads
    if lead_type != "wholesale":
        return {
            "success": False,
            "message": "Outreach only available for wholesale leads"
        }

    log.info("Running outreach for: " + product_name[:30])

    # Step 1 — Find supplier contact
    contact = find_supplier_contact(product_name, source, categories, ai_client)
    if not contact:
        return {
            "success": False,
            "message": "Could not find supplier contact information"
        }

    supplier_name  = contact.get("supplier_name", source)
    wholesale_url  = contact.get("wholesale_url", "")
    wholesale_email = contact.get("wholesale_email", "")
    platform       = contact.get("platform", source)
    moq_estimate   = contact.get("moq_estimate", "")
    notes          = contact.get("notes", "")

    # Step 2 — Generate outreach email
    email_body = generate_outreach_email(
        supplier_name, product_name, categories,
        platform, ai_client, seller_name, business_name
    )

    email_subject = "Wholesale Account Application — " + business_name

    # Step 3 — Save to supplier CRM (upsert)
    try:
        existing = supabase_admin.table("suppliers").select("id").eq("user_id", user_id).ilike("name", "%" + supplier_name[:20] + "%").limit(1).execute()

        supplier_data = {
            "user_id":       user_id,
            "name":          supplier_name,
            "platform":      platform,
            "website":       wholesale_url,
            "email":         wholesale_email,
            "moq":           moq_estimate,
            "status":        "prospect",
            "categories":    categories,
            "notes":         notes + ("\nAuto-added from lead: " + product_name[:50]),
            "updated_at":    datetime.now().isoformat(),
        }

        if existing.data:
            # Update existing supplier
            supabase_admin.table("suppliers").update(supplier_data).eq("id", existing.data[0]["id"]).execute()
            supplier_id = existing.data[0]["id"]
            log.info("Updated existing supplier: " + supplier_name)
        else:
            # Create new supplier
            supplier_data["created_at"] = datetime.now().isoformat()
            result = supabase_admin.table("suppliers").insert(supplier_data).execute()
            supplier_id = result.data[0]["id"] if result.data else None
            log.info("Created new supplier: " + supplier_name)

    except Exception as e:
        log.error("Supplier CRM error: " + str(e))
        supplier_id = None

    return {
        "success":        True,
        "supplier_name":  supplier_name,
        "supplier_id":    supplier_id,
        "wholesale_url":  wholesale_url,
        "wholesale_email": wholesale_email,
        "platform":       platform,
        "moq_estimate":   moq_estimate,
        "email_subject":  email_subject,
        "email_body":     email_body,
        "amazon_friendly": contact.get("amazon_friendly", True),
        "message":        "Outreach package ready for " + supplier_name
    }
