#!/usr/bin/env python3
"""
ARBTRADE Support Agent (Agent 4)
----------------------------------
Handles user support tickets automatically using Claude.
Responds within 60 seconds. Escalates to owner if needed.

Categories handled:
- no_leads: User sees no leads
- billing: Billing and subscription questions  
- sourcing: How to source products
- technical: Technical issues
- upgrade: Plan upgrade questions
- general: Everything else
"""

import logging
import json
from datetime import datetime

log = logging.getLogger(__name__)

# Issues the agent can resolve automatically
AUTO_RESOLVE_PATTERNS = [
    "no leads", "not seeing leads", "leads disappeared", "where are my leads",
    "how do i source", "how to source", "what is wholesale", "what is oa",
    "how does it work", "when does it scan", "how often",
    "upgrade", "change plan", "cancel", "billing", "charge", "payment",
    "password", "login", "sign in", "account",
    "what is bsr", "what is roi", "buy box", "fba fees",
]

def build_support_prompt(ticket: dict, user_data: dict) -> str:
    """Build a support response prompt with full user context."""
    category    = ticket.get("category", "general")
    message     = ticket.get("message", "")
    tier        = user_data.get("tier", "trial")
    lead_count  = user_data.get("lead_count", 0)
    last_scan   = user_data.get("last_scan", "unknown")
    email       = user_data.get("email", "")

    tier_info = {
        "trial":   "7-day free trial, 5 leads/cycle, every 12 hours",
        "starter": "$47/month, 5 leads/cycle, every 12 hours, 7-day history",
        "pro":     "$97/month, 8 leads/cycle, every 8 hours, 30-day history",
        "agency":  "$197/month, 12 leads/cycle, every 6 hours, 90-day history",
    }.get(tier, "trial plan")

    next_scan_hours = {'trial':12,'starter':12,'pro':8,'agency':6,'custom':4}.get(tier, 12)
    scan_status = 'Scans are running — last lead found at ' + str(last_scan) if last_scan and 'No scan' not in str(last_scan) else 'No scans recorded yet'

    return (
        "You are ARBTRADE's AI support agent. You help Amazon FBA sellers using the ARBTRADE platform.\n\n"
        "ARBTRADE automatically finds wholesale and OA leads for Amazon sellers on a set schedule.\n\n"
        "USER ACCOUNT INFO:\n"
        "Email: " + email + "\n"
        "Plan: " + tier + " (" + tier_info + ")\n"
        "Leads in dashboard: " + str(lead_count) + "\n"
        "Scan status: " + scan_status + "\n"
        "Scan frequency: every " + str(next_scan_hours) + " hours automatically\n"
        "CRITICAL: If scan status shows a timestamp, scans ARE working. Never say no scans occurred.\n\n"
        "SUPPORT TICKET:\n"
        "Category: " + category + "\n"
        "Message: " + message + "\n\n"
        "INSTRUCTIONS:\n"
        "1. Respond warmly and professionally\n"
        "2. Address their specific issue directly\n"
        "3. Use their account data to give personalized help\n"
        "4. For no leads issues: explain their scan schedule and when next scan runs\n"
        "5. For billing: explain their plan details and direct to dashboard billing tab\n"
        "6. For sourcing: explain WS vs OA and link to their onboarding guide\n"
        "7. For technical issues: acknowledge and say the team is looking into it\n"
        "8. Always end with an offer to help further\n"
        "9. Keep response under 200 words\n"
        "10. Be human, warm, and genuinely helpful\n\n"
        "At the end of your response add on a new line:\n"
        "ESCALATE: YES or NO (YES only if this needs human intervention)\n"
        "RESOLVED: YES or NO (YES if this fully resolves their issue)"
    )

def parse_support_response(text: str) -> dict:
    """Parse the AI response and extract escalation flags."""
    lines = text.strip().split('\n')
    escalate = False
    resolved = True
    response_lines = []

    for line in lines:
        if line.startswith("ESCALATE:"):
            escalate = "YES" in line.upper()
        elif line.startswith("RESOLVED:"):
            resolved = "YES" in line.upper()
        else:
            response_lines.append(line)

    return {
        "response": "\n".join(response_lines).strip(),
        "escalate": escalate,
        "resolved": resolved
    }

def send_escalation_email(ticket: dict, ai_response: str, sendgrid_key: str, owner_email: str):
    """Email the owner when a ticket needs human attention."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        html = (
            '<body style="background:#0a0a08;font-family:sans-serif;padding:32px">'
            '<div style="max-width:560px;margin:0 auto">'
            '<div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:4px">ARBTRADE SUPPORT</div>'
            '<div style="font-size:18px;font-weight:700;color:#FF5C5C;margin-bottom:4px">⚠ Ticket needs your attention</div>'
            '<div style="background:#161719;border-radius:8px;padding:14px 16px;margin-bottom:12px">'
            '<div style="font-size:11px;font-family:monospace;color:#888884;margin-bottom:8px">'
            'From: ' + ticket.get("email","") + ' · Plan: ' + ticket.get("tier","") + ' · Category: ' + ticket.get("category","") +
            '</div>'
            '<div style="font-size:13px;color:#f2efe8">' + ticket.get("message","") + '</div>'
            '</div>'
            '<div style="font-size:11px;color:#888884;font-family:monospace;margin-bottom:8px">AI Response sent:</div>'
            '<div style="background:#161719;border-radius:8px;padding:14px 16px;font-size:12px;color:#888884;font-family:monospace">'
            + ai_response.replace('\n','<br>') +
            '</div>'
            '</div></body>'
        )

        msg = Mail(
            from_email=("ianseze@gmail.com", "ARBTRADE Support"),
            to_emails=owner_email,
            subject="⚠ Support ticket needs attention — " + ticket.get("category","general"),
            html_content=html
        )
        SendGridAPIClient(sendgrid_key).send(msg)
        log.info("Escalation email sent for ticket " + str(ticket.get("id","")))
    except Exception as e:
        log.error("Escalation email error: " + str(e))

def send_response_email(ticket: dict, response: str, sendgrid_key: str):
    """Send the AI response back to the user via email."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        html = (
            '<body style="background:#0a0a08;font-family:sans-serif;padding:32px">'
            '<div style="max-width:560px;margin:0 auto">'
            '<div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:4px">ARBTRADE SUPPORT</div>'
            '<div style="font-size:18px;font-weight:700;color:#f2efe8;margin-bottom:4px">Re: Your support request</div>'
            '<div style="font-size:12px;color:#888884;font-family:monospace;margin-bottom:20px">'
            'Category: ' + ticket.get("category","general") +
            '</div>'
            '<div style="background:#161719;border-radius:8px;padding:16px 18px;font-size:13px;color:#f2efe8;line-height:1.8">'
            + response.replace('\n','<br>') +
            '</div>'
            '<div style="margin-top:20px;font-size:11px;color:#555552;font-family:monospace">'
            'Reply to this email or submit a new ticket from your dashboard.<br>'
            '<a href="https://getarbtrade.com/dashboard.html" style="color:#c8a96e">Open Dashboard →</a>'
            '</div>'
            '</div></body>'
        )

        msg = Mail(
            from_email=("ianseze@gmail.com", "ARBTRADE Support"),
            to_emails=ticket.get("email",""),
            subject="Re: Your ARBTRADE support request",
            html_content=html
        )
        SendGridAPIClient(sendgrid_key).send(msg)
        log.info("Support response sent to " + ticket.get("email",""))
    except Exception as e:
        log.error("Support email error: " + str(e))

def process_ticket(ticket: dict, user_data: dict, ai_client, sendgrid_key: str, owner_email: str) -> dict:
    """
    Full ticket processing flow:
    1. Build context-aware prompt
    2. Get AI response
    3. Send response to user
    4. Escalate if needed
    """
    try:
        prompt = build_support_prompt(ticket, user_data)
        resp = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        parsed = parse_support_response(raw)

        # Send response email to user
        if sendgrid_key and ticket.get("email"):
            send_response_email(ticket, parsed["response"], sendgrid_key)

        # Escalate if needed
        if parsed["escalate"] and sendgrid_key:
            ticket["tier"] = user_data.get("tier", "unknown")
            send_escalation_email(ticket, parsed["response"], sendgrid_key, owner_email)

        log.info(
            "Ticket processed: " + str(ticket.get("id",""))[:8] +
            " | escalate=" + str(parsed["escalate"]) +
            " | resolved=" + str(parsed["resolved"])
        )

        return {
            "success": True,
            "response": parsed["response"],
            "escalate": parsed["escalate"],
            "resolved": parsed["resolved"]
        }

    except Exception as e:
        log.error("Support agent error: " + str(e))
        return {
            "success": False,
            "response": "Thank you for reaching out. Our team will get back to you shortly.",
            "escalate": True,
            "resolved": False
        }
