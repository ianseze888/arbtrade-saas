#!/usr/bin/env python3
"""
ARBTRADE Daily Digest Email System
------------------------------------
Sends a beautiful daily email to each subscriber with their
top BUY leads and one-click APPROVE/SKIP buttons.

Setup:
  pip install sendgrid
  Add SENDGRID_API_KEY to Railway environment variables

Runs automatically - called from main.py scheduler
"""

import os
import json
import logging
from datetime import datetime, timedelta
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

log = logging.getLogger(__name__)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL       = os.getenv("DIGEST_FROM_EMAIL", "ianseze@gmail.com")
FROM_NAME        = os.getenv("DIGEST_FROM_NAME", "ARBTRADE Research Hub")
APP_URL          = os.getenv("APP_URL", "https://monumental-hamster-dd12a2.netlify.app")
API_URL          = os.getenv("API_URL", "https://arbtrade-saas-production.up.railway.app")

def get_roi_color(roi_str):
    try:
        roi = int(str(roi_str).replace("%","").split("-")[0].strip())
        if roi >= 40: return "#3ECFA0"
        if roi >= 30: return "#c8a96e"
        return "#FF5C5C"
    except:
        return "#c8a96e"

def build_lead_card(lead, index):
    roi = lead.get("roi", "—")
    roi_color = get_roi_color(roi)
    rec = lead.get("recommendation", "BUY")
    name = lead.get("name", "Unknown Product")
    source = lead.get("source", "—")
    buy_cost = lead.get("buy_cost", "—")
    sell_price = lead.get("sell_price", "—")
    bsr = lead.get("bsr", "—")
    sellers = lead.get("sellers", "—")
    reason = lead.get("reason", "")
    lead_type = lead.get("type", "wholesale")
    type_color = "#4A9EFF" if lead_type == "wholesale" else "#3ECFA0"
    type_label = "WS" if lead_type == "wholesale" else "OA"

    # Approve/Skip links (these hit the API)
    approve_url = f"{API_URL}/leads/approve?index={index}&name={name[:30].replace(' ','%20')}"
    skip_url    = f"{API_URL}/leads/skip?index={index}&name={name[:30].replace(' ','%20')}"

    return f"""
    <div style="background:#161719;border:1px solid rgba(255,255,255,0.08);border-radius:10px;
                padding:20px 24px;margin-bottom:16px;border-left:3px solid {type_color}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div style="flex:1">
          <div style="font-size:15px;font-weight:600;color:#f2efe8;margin-bottom:4px">{name}</div>
          <div style="font-size:11px;color:#888884;font-family:monospace;margin-bottom:10px">
            📍 {source}
            &nbsp;·&nbsp;
            <span style="color:{type_color};background:rgba(74,158,255,0.1);padding:2px 7px;border-radius:20px">{type_label}</span>
          </div>
          <div style="display:flex;gap:16px;font-size:12px;color:#888884;font-family:monospace;flex-wrap:wrap;margin-bottom:10px">
            <span>Buy: <strong style="color:#f2efe8">{buy_cost}</strong></span>
            <span>Sell: <strong style="color:#f2efe8">{sell_price}</strong></span>
            <span>BSR: <strong style="color:#f2efe8">{bsr}</strong></span>
            <span>Sellers: <strong style="color:#f2efe8">{sellers}</strong></span>
          </div>
          {f'<div style="font-size:11px;color:#888884;font-family:monospace;margin-bottom:12px">→ {reason}</div>' if reason else ''}
          <div style="display:flex;gap:10px">
            <a href="{approve_url}"
               style="background:#3ECFA0;color:#0a0a08;font-weight:700;font-size:12px;
                      padding:8px 20px;border-radius:6px;text-decoration:none;
                      font-family:sans-serif;letter-spacing:.04em">
              ✓ APPROVE
            </a>
            <a href="{skip_url}"
               style="background:rgba(255,255,255,0.06);color:#888884;font-size:12px;
                      padding:8px 20px;border-radius:6px;text-decoration:none;
                      font-family:sans-serif;border:1px solid rgba(255,255,255,0.1)">
              Skip
            </a>
          </div>
        </div>
        <div style="text-align:right;margin-left:20px;flex-shrink:0">
          <div style="font-size:32px;font-weight:700;color:{roi_color};font-family:sans-serif">{roi}</div>
          <div style="font-size:10px;color:#555552;font-family:monospace;letter-spacing:.06em">ROI</div>
          <div style="margin-top:8px;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;
                      background:rgba(62,207,160,0.12);color:#3ECFA0;font-family:monospace">{rec}</div>
        </div>
      </div>
    </div>
    """

def build_email_html(user_email, leads, tier):
    today = datetime.now().strftime("%B %d, %Y")
    buy_leads = [l for l in leads if l.get("recommendation") == "BUY"]
    watch_leads = [l for l in leads if l.get("recommendation") == "WATCH"]

    lead_cards = ""
    for i, lead in enumerate(buy_leads[:5]):
        lead_cards += build_lead_card(lead, i)

    watch_section = ""
    if watch_leads:
        watch_names = " · ".join([l.get("name","")[:30] for l in watch_leads[:3]])
        watch_section = f"""
        <div style="background:rgba(200,169,110,0.06);border:1px solid rgba(200,169,110,0.15);
                    border-radius:8px;padding:14px 18px;margin-top:8px">
          <div style="font-size:11px;color:#c8a96e;font-family:monospace;letter-spacing:.08em;margin-bottom:4px">
            WATCH LIST ({len(watch_leads)} products)
          </div>
          <div style="font-size:12px;color:#888884;font-family:monospace">{watch_names}</div>
          <a href="{APP_URL}/dashboard.html" style="font-size:11px;color:#c8a96e;font-family:monospace">
            View all in dashboard →
          </a>
        </div>
        """

    tier_badge_color = {"starter":"#c8a96e","pro":"#3ECFA0","agency":"#4A9EFF"}.get(tier,"#888884")

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a08;font-family:'Helvetica Neue',Arial,sans-serif">

  <!-- Header -->
  <div style="background:#0a0a08;padding:32px 40px 0">
    <div style="max-width:600px;margin:0 auto">
      <div style="display:flex;justify-content:space-between;align-items:center;
                  border-bottom:1px solid rgba(255,255,255,0.07);padding-bottom:20px">
        <div>
          <div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:3px">ARBTRADE</div>
          <div style="font-size:18px;font-weight:700;color:#f2efe8;letter-spacing:-.02em">Daily Research Digest</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:11px;color:#888884;font-family:monospace">{today}</div>
          <div style="font-size:10px;color:{tier_badge_color};font-family:monospace;
                      background:rgba(200,169,110,0.1);padding:2px 8px;border-radius:20px;margin-top:4px">
            {tier.upper()} PLAN
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Summary bar -->
  <div style="background:#0a0a08;padding:20px 40px">
    <div style="max-width:600px;margin:0 auto">
      <div style="background:#161719;border:1px solid rgba(255,255,255,0.07);border-radius:10px;
                  padding:16px 20px;display:flex;gap:32px">
        <div>
          <div style="font-size:10px;color:#888884;font-family:monospace;letter-spacing:.08em">BUY LEADS</div>
          <div style="font-size:28px;font-weight:700;color:#3ECFA0">{len(buy_leads)}</div>
        </div>
        <div>
          <div style="font-size:10px;color:#888884;font-family:monospace;letter-spacing:.08em">WATCH</div>
          <div style="font-size:28px;font-weight:700;color:#c8a96e">{len(watch_leads)}</div>
        </div>
        <div>
          <div style="font-size:10px;color:#888884;font-family:monospace;letter-spacing:.08em">BEST ROI</div>
          <div style="font-size:28px;font-weight:700;color:#3ECFA0">
            {max([int(str(l.get('roi','0')).replace('%','').split('-')[0].strip() or 0) for l in leads], default=0)}%
          </div>
        </div>
        <div style="margin-left:auto;display:flex;align-items:center">
          <a href="{APP_URL}/dashboard.html"
             style="background:#c8a96e;color:#0a0a08;font-weight:700;font-size:12px;
                    padding:10px 20px;border-radius:6px;text-decoration:none;
                    font-family:sans-serif;letter-spacing:.04em">
            Open Dashboard →
          </a>
        </div>
      </div>
    </div>
  </div>

  <!-- Lead cards -->
  <div style="background:#0a0a08;padding:0 40px">
    <div style="max-width:600px;margin:0 auto">
      <div style="font-size:13px;font-weight:600;color:#f2efe8;margin-bottom:14px;
                  display:flex;align-items:center;gap:8px">
        Top BUY Recommendations
        <span style="font-size:10px;color:#888884;font-family:monospace;font-weight:400">
          Click APPROVE to generate a purchase order
        </span>
      </div>
      {lead_cards if lead_cards else '<div style="color:#888884;font-family:monospace;font-size:12px;padding:20px 0">No BUY leads today. The agent scans every 4 hours — check back soon.</div>'}
      {watch_section}
    </div>
  </div>

  <!-- Footer -->
  <div style="background:#0a0a08;padding:32px 40px">
    <div style="max-width:600px;margin:0 auto;
                border-top:1px solid rgba(255,255,255,0.07);padding-top:20px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:11px;color:#555552;font-family:monospace">
          ARBTRADE · Amazon Research Hub<br>
          Sent to {user_email}
        </div>
        <div style="text-align:right">
          <a href="{APP_URL}/dashboard.html"
             style="font-size:11px;color:#c8a96e;font-family:monospace;text-decoration:none">
            Dashboard
          </a>
          &nbsp;·&nbsp;
          <a href="{APP_URL}/login.html"
             style="font-size:11px;color:#888884;font-family:monospace;text-decoration:none">
            Settings
          </a>
          &nbsp;·&nbsp;
          <a href="{API_URL}/unsubscribe?email={user_email}"
             style="font-size:11px;color:#555552;font-family:monospace;text-decoration:none">
            Unsubscribe
          </a>
        </div>
      </div>
      <div style="margin-top:12px;font-size:10px;color:#3a3832;font-family:monospace;line-height:1.6">
        This digest is sent daily based on your research criteria and plan settings.
        ROI estimates are based on AI analysis — always verify before ordering.
        ARBTRADE provides research data only, not financial advice.
      </div>
    </div>
  </div>

</body>
</html>
"""

def send_digest(user_email: str, leads: list, tier: str) -> bool:
    """Send daily digest email to a single user."""
    if not SENDGRID_API_KEY:
        log.error("SENDGRID_API_KEY not set — cannot send digest")
        return False

    if not leads:
        log.info(f"No leads for {user_email} — skipping digest")
        return True

    try:
        html = build_email_html(user_email, leads, tier)
        buy_count = sum(1 for l in leads if l.get("recommendation") == "BUY")
        best_roi = max(
            [int(str(l.get("roi","0")).replace("%","").split("-")[0].strip() or 0) for l in leads],
            default=0
        )

        message = Mail(
            from_email=(FROM_EMAIL, FROM_NAME),
            to_emails=user_email,
            subject=f"🔍 ARBTRADE Daily Digest — {buy_count} BUY leads, best ROI {best_roi}%",
            html_content=html
        )

        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        log.info(f"Digest sent to {user_email} — status {response.status_code}")
        return response.status_code in [200, 201, 202]

    except Exception as e:
        log.error(f"Failed to send digest to {user_email}: {e}")
        return False

def send_all_digests(supabase_admin, leads_by_user: dict):
    """Send digest to all active subscribers."""
    try:
        users = supabase_admin.table("profiles").select("id,email,tier").neq("tier","cancelled").neq("tier","trial").execute()
        sent = 0
        for profile in (users.data or []):
            user_id = profile["id"]
            email = profile.get("email","")
            tier = profile.get("tier","starter")
            leads = leads_by_user.get(user_id, [])
            if email and send_digest(email, leads, tier):
                sent += 1
        log.info(f"Daily digest sent to {sent} subscribers")
    except Exception as e:
        log.error(f"Digest send error: {e}")
