#!/usr/bin/env python3
"""
ARBTRADE Daily Digest Email System
"""

import os
import json
import logging
from datetime import datetime, timedelta

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

def get_best_roi(leads):
    best = 0
    for l in leads:
        try:
            v = int(str(l.get("roi","0")).replace("%","").split("-")[0].strip() or 0)
            if v > best:
                best = v
        except:
            pass
    return best

def build_lead_card(lead, index):
    roi        = lead.get("roi", "—")
    roi_color  = get_roi_color(roi)
    rec        = lead.get("recommendation", "BUY")
    name       = lead.get("name", "Unknown Product")
    source     = lead.get("source", "—")
    buy_cost   = lead.get("buy_cost", "—")
    sell_price = lead.get("sell_price", "—")
    bsr        = lead.get("bsr", "—")
    sellers    = lead.get("sellers", "—")
    reason     = lead.get("reason", "")
    lead_type  = lead.get("type", "wholesale")
    type_color = "#4A9EFF" if lead_type == "wholesale" else "#3ECFA0"
    type_label = "WS" if lead_type == "wholesale" else "OA"

    name_short   = name[:30].replace(" ", "%20")
    approve_url  = API_URL + "/leads/approve?index=" + str(index) + "&name=" + name_short
    skip_url     = API_URL + "/leads/skip?index="    + str(index) + "&name=" + name_short

    reason_html = ""
    if reason:
        reason_html = '<div style="font-size:11px;color:#888884;font-family:monospace;margin-bottom:12px">&#8594; ' + reason + '</div>'

    return (
        '<div style="background:#161719;border:1px solid rgba(255,255,255,0.08);border-radius:10px;'
        'padding:20px 24px;margin-bottom:16px;border-left:3px solid ' + type_color + '">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td style="vertical-align:top">'
        '<div style="font-size:15px;font-weight:600;color:#f2efe8;margin-bottom:4px">' + name + '</div>'
        '<div style="font-size:11px;color:#888884;font-family:monospace;margin-bottom:10px">'
        '&#128205; ' + source + ' &nbsp;&middot;&nbsp; '
        '<span style="color:' + type_color + ';background:rgba(74,158,255,0.1);padding:2px 7px;border-radius:20px">' + type_label + '</span>'
        '</div>'
        '<div style="font-size:12px;color:#888884;font-family:monospace;margin-bottom:10px">'
        'Buy: <strong style="color:#f2efe8">' + str(buy_cost) + '</strong> &nbsp; '
        'Sell: <strong style="color:#f2efe8">' + str(sell_price) + '</strong> &nbsp; '
        'BSR: <strong style="color:#f2efe8">' + str(bsr) + '</strong> &nbsp; '
        'Sellers: <strong style="color:#f2efe8">' + str(sellers) + '</strong>'
        '</div>'
        + reason_html +
        '<table cellpadding="0" cellspacing="0"><tr>'
        '<td style="padding-right:10px">'
        '<a href="' + approve_url + '" style="background:#3ECFA0;color:#0a0a08;font-weight:700;font-size:12px;'
        'padding:8px 20px;border-radius:6px;text-decoration:none;font-family:sans-serif;'
        'letter-spacing:.04em;display:inline-block;white-space:nowrap">&#10003; APPROVE</a>'
        '</td>'
        '<td>'
        '<a href="' + skip_url + '" style="background:rgba(255,255,255,0.06);color:#888884;font-size:12px;'
        'padding:8px 20px;border-radius:6px;text-decoration:none;font-family:sans-serif;'
        'border:1px solid rgba(255,255,255,0.1);display:inline-block;white-space:nowrap">Skip</a>'
        '</td>'
        '</tr></table>'
        '</td>'
        '<td style="text-align:right;vertical-align:top;padding-left:20px;white-space:nowrap">'
        '<div style="font-size:32px;font-weight:700;color:' + roi_color + ';font-family:sans-serif">' + str(roi) + '</div>'
        '<div style="font-size:10px;color:#555552;font-family:monospace;letter-spacing:.06em">ROI</div>'
        '<div style="margin-top:8px;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;'
        'background:rgba(62,207,160,0.12);color:#3ECFA0;font-family:monospace;display:inline-block">' + rec + '</div>'
        '</td>'
        '</tr></table>'
        '</div>'
    )

def build_email_html(user_email, leads, tier):
    today      = datetime.now().strftime("%B %d, %Y")
    buy_leads  = [l for l in leads if l.get("recommendation") == "BUY"]
    watch_leads= [l for l in leads if l.get("recommendation") == "WATCH"]
    best_roi   = get_best_roi(leads)

    tier_color = {"starter":"#c8a96e","pro":"#3ECFA0","agency":"#4A9EFF"}.get(tier,"#888884")

    lead_cards = ""
    for i, lead in enumerate(buy_leads[:5]):
        lead_cards += build_lead_card(lead, i)

    if not lead_cards:
        lead_cards = '<div style="color:#888884;font-family:monospace;font-size:12px;padding:20px 0">No BUY leads today. The agent scans every 4 hours.</div>'

    watch_html = ""
    if watch_leads:
        watch_names = " &middot; ".join([l.get("name","")[:25] for l in watch_leads[:3]])
        watch_html = (
            '<div style="background:rgba(200,169,110,0.06);border:1px solid rgba(200,169,110,0.15);'
            'border-radius:8px;padding:14px 18px;margin-top:8px">'
            '<div style="font-size:11px;color:#c8a96e;font-family:monospace;letter-spacing:.08em;margin-bottom:4px">'
            'WATCH LIST (' + str(len(watch_leads)) + ' products)</div>'
            '<div style="font-size:12px;color:#888884;font-family:monospace;margin-bottom:6px">' + watch_names + '</div>'
            '<a href="' + APP_URL + '/dashboard.html" style="font-size:11px;color:#c8a96e;font-family:monospace;text-decoration:none">'
            'View all in dashboard &#8594;</a>'
            '</div>'
        )

    html = (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        '</head>'
        '<body bgcolor="#0a0a08" style="margin:0;padding:0;background:#0a0a08;font-family:Helvetica Neue,Arial,sans-serif">'

        # Header
        '<table width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="background:#0a0a08;padding:32px 40px 0">'
        '<table width="600" align="center" cellpadding="0" cellspacing="0">'
        '<tr><td style="border-bottom:1px solid rgba(255,255,255,0.07);padding-bottom:20px">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td>'
        '<div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:3px">ARBTRADE</div>'
        '<div style="font-size:18px;font-weight:700;color:#f2efe8;letter-spacing:-.02em">Daily Research Digest</div>'
        '</td>'
        '<td style="text-align:right">'
        '<div style="font-size:11px;color:#888884;font-family:monospace">' + today + '</div>'
        '<div style="font-size:10px;color:' + tier_color + ';font-family:monospace;background:rgba(200,169,110,0.1);'
        'padding:2px 8px;border-radius:20px;display:inline-block;margin-top:4px">' + tier.upper() + ' PLAN</div>'
        '</td>'
        '</tr></table>'
        '</td></tr></table>'
        '</td></tr></table>'

        # Summary
        '<table width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="background:#0a0a08;padding:20px 40px">'
        '<table width="600" align="center" cellpadding="0" cellspacing="0">'
        '<tr><td style="background:#161719;border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:16px 20px">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td style="padding-right:24px">'
        '<div style="font-size:10px;color:#888884;font-family:monospace;letter-spacing:.08em">BUY LEADS</div>'
        '<div style="font-size:28px;font-weight:700;color:#3ECFA0;font-family:sans-serif">' + str(len(buy_leads)) + '</div>'
        '</td>'
        '<td style="padding-right:24px">'
        '<div style="font-size:10px;color:#888884;font-family:monospace;letter-spacing:.08em">WATCH</div>'
        '<div style="font-size:28px;font-weight:700;color:#c8a96e;font-family:sans-serif">' + str(len(watch_leads)) + '</div>'
        '</td>'
        '<td style="padding-right:24px">'
        '<div style="font-size:10px;color:#888884;font-family:monospace;letter-spacing:.08em">BEST ROI</div>'
        '<div style="font-size:28px;font-weight:700;color:#3ECFA0;font-family:sans-serif">' + str(best_roi) + '%</div>'
        '</td>'
        '<td style="text-align:right">'
        '<a href="' + APP_URL + '/dashboard.html" style="background:#c8a96e;color:#0a0a08;font-weight:700;font-size:12px;'
        'padding:10px 20px;border-radius:6px;text-decoration:none;font-family:sans-serif;'
        'letter-spacing:.04em;display:inline-block;white-space:nowrap">Open Dashboard &#8594;</a>'
        '</td>'
        '</tr></table>'
        '</td></tr></table>'
        '</td></tr></table>'

        # Leads
        '<table width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="background:#0a0a08;padding:0 40px">'
        '<table width="600" align="center" cellpadding="0" cellspacing="0">'
        '<tr><td>'
        '<div style="font-size:13px;font-weight:600;color:#f2efe8;margin-bottom:14px">'
        'Top BUY Recommendations '
        '<span style="font-size:10px;color:#888884;font-family:monospace;font-weight:400">'
        '&#8212; Click APPROVE to generate a purchase order</span>'
        '</div>'
        + lead_cards + watch_html +
        '</td></tr></table>'
        '</td></tr></table>'

        # Footer
        '<table width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="background:#0a0a08;padding:32px 40px">'
        '<table width="600" align="center" cellpadding="0" cellspacing="0">'
        '<tr><td style="border-top:1px solid rgba(255,255,255,0.07);padding-top:20px">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td><div style="font-size:11px;color:#555552;font-family:monospace">'
        'ARBTRADE &middot; Amazon Research Hub<br>Sent to ' + user_email + '</div></td>'
        '<td style="text-align:right">'
        '<a href="' + APP_URL + '/dashboard.html" style="font-size:11px;color:#c8a96e;font-family:monospace;text-decoration:none">Dashboard</a>'
        ' &nbsp;&middot;&nbsp; '
        '<a href="' + API_URL + '/unsubscribe?email=' + user_email + '" style="font-size:11px;color:#555552;font-family:monospace;text-decoration:none">Unsubscribe</a>'
        '</td>'
        '</tr></table>'
        '<div style="margin-top:12px;font-size:10px;color:#3a3832;font-family:monospace;line-height:1.6">'
        'ROI estimates are based on AI analysis. Always verify before ordering. '
        'ARBTRADE provides research data only, not financial advice.'
        '</div>'
        '</td></tr></table>'
        '</td></tr></table>'

        '</body></html>'
    )
    return html

def send_digest(user_email, leads, tier):
    if not SENDGRID_API_KEY:
        log.error("SENDGRID_API_KEY not set")
        return False
    if not leads:
        log.info("No leads for " + user_email + " — skipping")
        return True
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        html      = build_email_html(user_email, leads, tier)
        buy_count = sum(1 for l in leads if l.get("recommendation") == "BUY")
        best_roi  = get_best_roi(leads)
        subject   = "ARBTRADE Daily Digest — " + str(buy_count) + " BUY leads, best ROI " + str(best_roi) + "%"
        message   = Mail(
            from_email=(FROM_EMAIL, FROM_NAME),
            to_emails=user_email,
            subject=subject,
            html_content=html
        )
        sg       = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        log.info("Digest sent to " + user_email + " — status " + str(response.status_code))
        return response.status_code in [200, 201, 202]
    except Exception as e:
        log.error("Failed to send digest to " + user_email + ": " + str(e))
        return False

def send_all_digests(supabase_admin, leads_by_user):
    try:
        users = supabase_admin.table("profiles").select("id,email,tier").neq("tier","cancelled").neq("tier","trial").execute()
        sent  = 0
        for profile in (users.data or []):
            user_id = profile["id"]
            email   = profile.get("email","")
            tier    = profile.get("tier","starter")
            leads   = leads_by_user.get(user_id, [])
            if email and send_digest(email, leads, tier):
                sent += 1
        log.info("Daily digest sent to " + str(sent) + " subscribers")
    except Exception as e:
        log.error("Digest send error: " + str(e))
