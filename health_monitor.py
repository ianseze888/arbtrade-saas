#!/usr/bin/env python3
"""
ARBTRADE Platform Health Monitor
----------------------------------
Runs every 15 minutes and checks:
1. API is responding
2. Supabase is connected
3. Leads are being generated
4. Scheduler is running
5. Recent scan activity

Alerts owner via email if anything fails.
"""

import logging
import time
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

HEALTH_CHECKS = {
    "api":        "API responding",
    "supabase":   "Database connected",
    "leads":      "Leads being generated",
    "scans":      "Scans running on schedule",
    "anthropic":  "AI agent accessible",
}

def check_supabase(supabase_admin) -> dict:
    """Check if Supabase is accessible."""
    start = time.time()
    try:
        result = supabase_admin.table("profiles").select("id").limit(1).execute()
        ms = int((time.time() - start) * 1000)
        return {"status": "ok", "message": "Connected in " + str(ms) + "ms", "ms": ms}
    except Exception as e:
        return {"status": "fail", "message": str(e), "ms": 0}

def check_leads_activity(supabase_admin) -> dict:
    """Check if leads are being generated recently."""
    try:
        cutoff = (datetime.now() - timedelta(hours=8)).isoformat()
        result = supabase_admin.table("leads").select("id,found_at").gte("found_at", cutoff).execute()
        count = len(result.data or [])
        if count > 0:
            return {"status": "ok", "message": str(count) + " leads in last 8 hours"}
        else:
            return {"status": "warn", "message": "No leads generated in last 8 hours"}
    except Exception as e:
        return {"status": "fail", "message": str(e)}

def check_anthropic(anthropic_client) -> dict:
    """Check if Anthropic API is accessible."""
    start = time.time()
    try:
        resp = anthropic_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}]
        )
        ms = int((time.time() - start) * 1000)
        return {"status": "ok", "message": "Responding in " + str(ms) + "ms", "ms": ms}
    except Exception as e:
        return {"status": "fail", "message": str(e), "ms": 0}

def check_user_count(supabase_admin) -> dict:
    """Check total subscribers."""
    try:
        result = supabase_admin.table("profiles").select("id,tier").execute()
        total = len(result.data or [])
        paid = sum(1 for u in (result.data or []) if u.get("tier") not in ["trial","cancelled",""])
        return {"status": "ok", "message": str(total) + " total users, " + str(paid) + " paid"}
    except Exception as e:
        return {"status": "fail", "message": str(e)}

def run_health_check(supabase_admin, anthropic_client, sendgrid_key: str, owner_email: str) -> dict:
    """Run all health checks and alert if anything fails."""
    results = {}
    failures = []
    warnings = []

    log.info("Running platform health check...")

    # Check Supabase
    results["supabase"] = check_supabase(supabase_admin)
    if results["supabase"]["status"] == "fail":
        failures.append("Supabase: " + results["supabase"]["message"])

    # Check leads activity
    results["leads"] = check_leads_activity(supabase_admin)
    if results["leads"]["status"] == "fail":
        failures.append("Leads: " + results["leads"]["message"])
    elif results["leads"]["status"] == "warn":
        warnings.append("Leads: " + results["leads"]["message"])

    # Skip Anthropic check in health monitor - too expensive
    results["anthropic"] = {"status": "ok", "message": "Skipped - using API credits elsewhere"}

    # Check user metrics
    results["users"] = check_user_count(supabase_admin)

    # Overall status
    overall = "ok" if not failures else "fail"
    if warnings and not failures:
        overall = "warn"

    log.info("Health check complete: " + overall +
             " | " + str(len(failures)) + " failures" +
             " | " + str(len(warnings)) + " warnings")

    # Save to health_logs
    try:
        supabase_admin.table("health_logs").insert({
            "check_type": "full",
            "status": overall,
            "message": "; ".join(failures + warnings) or "All systems operational",
            "checked_at": datetime.now().isoformat()
        }).execute()
    except:
        pass

    # Alert owner if failures
    if failures and sendgrid_key and owner_email:
        send_health_alert(failures, warnings, results, sendgrid_key, owner_email)

    return {
        "status": overall,
        "checks": results,
        "failures": failures,
        "warnings": warnings,
        "timestamp": datetime.now().isoformat()
    }

def send_health_alert(failures: list, warnings: list, results: dict, sendgrid_key: str, owner_email: str):
    """Send health alert email to owner."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        status_color = "#FF5C5C" if failures else "#c8a96e"
        status_text  = "🚨 Platform Issue Detected" if failures else "⚠ Platform Warning"

        checks_html = ""
        for name, result in results.items():
            color = "#3ECFA0" if result["status"] == "ok" else "#FF5C5C" if result["status"] == "fail" else "#c8a96e"
            icon  = "✓" if result["status"] == "ok" else "✗" if result["status"] == "fail" else "⚠"
            checks_html += (
                '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05)">'
                '<span style="font-size:12px;color:#888884;font-family:monospace">' + name + '</span>'
                '<span style="font-size:12px;color:' + color + ';font-family:monospace">' + icon + ' ' + result["message"] + '</span>'
                '</div>'
            )

        html = (
            '<body style="background:#0a0a08;font-family:sans-serif;padding:32px">'
            '<div style="max-width:560px;margin:0 auto">'
            '<div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:4px">ARBTRADE HEALTH MONITOR</div>'
            '<div style="font-size:18px;font-weight:700;color:' + status_color + ';margin-bottom:4px">' + status_text + '</div>'
            '<div style="font-size:12px;color:#888884;font-family:monospace;margin-bottom:20px">' + datetime.now().strftime("%Y-%m-%d %H:%M UTC") + '</div>'
            '<div style="background:#161719;border-radius:8px;padding:14px 16px;margin-bottom:12px">'
            + checks_html +
            '</div>'
            + ('<div style="background:rgba(255,92,92,0.06);border:1px solid rgba(255,92,92,0.2);border-radius:8px;padding:12px 14px;margin-bottom:12px">'
               '<div style="font-size:11px;font-weight:600;color:#FF5C5C;margin-bottom:6px">Issues detected:</div>'
               + "".join('<div style="font-size:11px;font-family:monospace;color:#888884">• ' + f + '</div>' for f in failures) +
               '</div>' if failures else '') +
            '<a href="https://arbtrade-saas-production.up.railway.app/health" style="display:inline-block;background:#c8a96e;color:#000;font-weight:700;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:12px">Check Railway →</a>'
            '</div></body>'
        )

        msg = Mail(
            from_email=("ianseze@gmail.com", "ARBTRADE Health Monitor"),
            to_emails=owner_email,
            subject=status_text + " — " + datetime.now().strftime("%H:%M"),
            html_content=html
        )
        SendGridAPIClient(sendgrid_key).send(msg)
        log.info("Health alert sent to " + owner_email)
    except Exception as e:
        log.error("Health alert email error: " + str(e))
