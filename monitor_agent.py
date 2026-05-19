#!/usr/bin/env python3
"""
ARBTRADE Monitor Agent (Agent 4)
----------------------------------
Watches active SKUs for market changes:
1. Buy box ownership changes
2. Competitor stock levels
3. Price competitiveness
4. New seller entries
5. BSR movement
6. Reorder triggers

Runs every 6 hours alongside the scan scheduler.
Alerts users via email when action is needed.
"""

import logging
import json
from datetime import datetime

log = logging.getLogger(__name__)

def build_monitor_prompt(sku: dict) -> str:
    """Build monitoring prompt for a single SKU."""
    return (
        "You are an Amazon FBA market monitor. Analyze this active SKU for market changes.\n\n"
        "SKU DATA:\n"
        "Product: " + sku.get("product_name","") + "\n"
        "ASIN: " + sku.get("asin","") + "\n"
        "Supplier: " + sku.get("supplier_name","") + "\n"
        "Units in stock: " + str(sku.get("units_in_stock",0)) + "\n"
        "Daily velocity: " + str(sku.get("daily_sales_velocity",0)) + "/day\n"
        "Unit cost: " + str(sku.get("unit_cost","")) + "\n\n"
        "Please analyze this product on Amazon and check:\n"
        "1. Is Amazon retail currently on this listing? (kills buy box)\n"
        "2. Approximately how many active sellers are there?\n"
        "3. What is the current buy box price range?\n"
        "4. Is the BSR trending up (bad) or down (good)?\n"
        "5. Any new brand authorization requirements?\n"
        "6. Is this a seasonal product approaching peak or off-peak?\n"
        "7. Any IP complaints or listing issues known?\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "amazon_on_listing": false,\n'
        '  "seller_count": 4,\n'
        '  "buy_box_price": "$24.99",\n'
        '  "bsr_trend": "stable",\n'
        '  "bsr_estimate": "#8500",\n'
        '  "seasonal_alert": false,\n'
        '  "seasonal_note": "",\n'
        '  "ip_risk": false,\n'
        '  "action_needed": false,\n'
        '  "action": "HOLD",\n'
        '  "alerts": [],\n'
        '  "opportunity": "",\n'
        '  "confidence": "medium"\n'
        "}"
    )

def parse_monitor_response(text: str) -> dict:
    """Parse monitoring response JSON."""
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s == -1 or e == 0:
            return {}
        return json.loads(text[s:e])
    except:
        return {}

def monitor_sku(sku: dict, ai_client) -> dict:
    """Monitor a single SKU for market changes."""
    try:
        prompt = build_monitor_prompt(sku)
        resp = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        data = parse_monitor_response(raw)

        if not data:
            return {"sku_id": sku.get("id"), "error": "Parse failed"}

        # Build alert list
        alerts = data.get("alerts", [])

        if data.get("amazon_on_listing"):
            alerts.append("⚠ Amazon is on this listing — buy box at risk")

        if data.get("ip_risk"):
            alerts.append("⚠ IP risk detected — verify authorization")

        if data.get("seasonal_alert") and data.get("seasonal_note"):
            alerts.append("📅 " + data["seasonal_note"])

        # Calculate days of stock
        velocity = sku.get("daily_sales_velocity", 0)
        stock    = sku.get("units_in_stock", 0)
        days_remaining = round(stock / velocity) if velocity and velocity > 0 else None

        if days_remaining and days_remaining <= 14:
            alerts.append("🔴 Only " + str(days_remaining) + " days of stock remaining — reorder NOW")
        elif days_remaining and days_remaining <= 30:
            alerts.append("🟡 " + str(days_remaining) + " days of stock — plan reorder soon")

        result = {
            "sku_id":           sku.get("id"),
            "product_name":     sku.get("product_name",""),
            "asin":             sku.get("asin",""),
            "amazon_on_listing": data.get("amazon_on_listing", False),
            "seller_count":     data.get("seller_count", 0),
            "buy_box_price":    data.get("buy_box_price",""),
            "bsr_trend":        data.get("bsr_trend","stable"),
            "bsr_estimate":     data.get("bsr_estimate",""),
            "seasonal_alert":   data.get("seasonal_alert", False),
            "ip_risk":          data.get("ip_risk", False),
            "action":           data.get("action","HOLD"),
            "alerts":           alerts,
            "opportunity":      data.get("opportunity",""),
            "days_remaining":   days_remaining,
            "confidence":       data.get("confidence","medium"),
            "checked_at":       datetime.now().isoformat(),
        }

        log.info(
            "Monitored: " + sku.get("product_name","")[:30] +
            " | action=" + result["action"] +
            " | alerts=" + str(len(alerts))
        )
        return result

    except Exception as e:
        log.error("Monitor error for " + sku.get("product_name","") + ": " + str(e))
        return {"sku_id": sku.get("id"), "error": str(e)}

def monitor_all_skus(user_id: str, supabase_admin, ai_client) -> list:
    """Monitor all active SKUs for a user."""
    try:
        result = supabase_admin.table("active_skus").select("*").eq("user_id", user_id).execute()
        skus = result.data or []

        if not skus:
            return []

        log.info("Monitoring " + str(len(skus)) + " SKUs for user " + str(user_id)[:8])
        monitored = []

        for sku in skus:
            data = monitor_sku(sku, ai_client)
            monitored.append(data)

            # Update SKU with latest market data
            if not data.get("error"):
                try:
                    supabase_admin.table("active_skus").update({
                        "updated_at": datetime.now().isoformat(),
                    }).eq("id", sku["id"]).execute()
                except:
                    pass

        return monitored

    except Exception as e:
        log.error("Monitor all SKUs error: " + str(e))
        return []

def send_monitor_alert(email: str, alerts: list, sendgrid_key: str):
    """Send monitoring alerts via email."""
    if not sendgrid_key or not alerts:
        return
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        items_html = ""
        for a in alerts:
            product = a.get("product_name","")[:40]
            action  = a.get("action","HOLD")
            action_color = {
                "BUY": "#3ECFA0",
                "SELL": "#FF5C5C",
                "HOLD": "#c8a96e",
                "REORDER": "#4A9EFF"
            }.get(action, "#888884")

            alert_items = "".join(
                '<div style="font-size:11px;color:#888884;font-family:monospace;margin-top:3px">• ' + al + '</div>'
                for al in a.get("alerts",[])
            )

            items_html += (
                '<div style="background:#161719;border:1px solid rgba(255,255,255,0.07);'
                'border-radius:8px;padding:14px 16px;margin-bottom:10px;'
                'border-left:3px solid ' + action_color + '">'
                '<div style="display:flex;justify-content:space-between;margin-bottom:6px">'
                '<span style="font-size:13px;font-weight:600;color:#f2efe8">' + product + '</span>'
                '<span style="font-size:11px;font-family:monospace;color:' + action_color + '">' + action + '</span>'
                '</div>'
                + alert_items +
                (('<div style="font-size:11px;color:#3ECFA0;margin-top:6px">💡 ' + a.get("opportunity","") + '</div>') if a.get("opportunity") else '') +
                '</div>'
            )

        html = (
            '<body style="background:#0a0a08;font-family:sans-serif;padding:32px">'
            '<div style="max-width:560px;margin:0 auto">'
            '<div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:4px">ARBTRADE MONITOR</div>'
            '<div style="font-size:18px;font-weight:700;color:#f2efe8;margin-bottom:4px">📊 Market Monitor Report</div>'
            '<div style="font-size:12px;color:#888884;font-family:monospace;margin-bottom:20px">'
            + datetime.now().strftime("%B %d, %Y · %H:%M UTC") +
            '</div>'
            + items_html +
            '<a href="https://getarbtrade.com/inventory.html" '
            'style="display:inline-block;background:#c8a96e;color:#000;font-weight:700;'
            'padding:10px 20px;border-radius:6px;text-decoration:none;margin-top:16px;font-size:12px">'
            'View Inventory Monitor →</a>'
            '</div></body>'
        )

        msg = Mail(
            from_email=("ianseze@gmail.com", "ARBTRADE Monitor"),
            to_emails=email,
            subject="📊 ARBTRADE Market Monitor — " + str(len(alerts)) + " SKU update(s)",
            html_content=html
        )
        SendGridAPIClient(sendgrid_key).send(msg)
        log.info("Monitor alert sent to " + email)
    except Exception as e:
        log.error("Monitor alert email error: " + str(e))
