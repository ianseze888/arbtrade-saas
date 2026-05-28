"""
ARBTRADE SaaS Backend
FastAPI server handling:
- User auth via Supabase
- Stripe subscription billing
- Research agent scheduler
- Lead storage and retrieval per user
- Usage limits and session management
"""

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
import os, json, asyncio, logging, schedule, time, threading, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
import anthropic
import stripe

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY")
STRIPE_SECRET_KEY    = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET= os.getenv("STRIPE_WEBHOOK_SECRET", "")

stripe.api_key = STRIPE_SECRET_KEY

# Supabase clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Anthropic client
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Stripe price IDs — update these after creating products in Stripe dashboard
STRIPE_PRICES = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", "price_starter"),
    "pro":     os.getenv("STRIPE_PRICE_PRO",     "price_pro"),
    "agency":  os.getenv("STRIPE_PRICE_AGENCY",  "price_agency"),
}

# Usage limits per tier
# Lead structure — designed to deliver value without over-delivering
# Trial gets 50% of paid volume — enough to see quality, not enough to run without paying
# Scan intervals: Starter 12hr, Pro 8hr, Agency 6hr
# Cost per lead: Starter $0.16, Pro $0.13, Agency $0.14
# vs VA cost: $1.60-2.13/lead — 10x better value
OWNER_EMAIL = "ianseze@gmail.com"

TIER_LIMITS = {
    "starter": {
        "manual_scans_per_day": 1,
        "max_leads": 5,           # 5 leads/cycle x 2 scans/day = 10/day, 300/month
        "categories": 2,
        "scan_interval_hours": 12, # Every 12 hours
        "leads_per_cycle": 5,
    },
    "pro": {
        "manual_scans_per_day": 2,
        "max_leads": 8,           # 8 leads/cycle x 3 scans/day = 24/day, 720/month
        "categories": 5,
        "scan_interval_hours": 8,  # Every 8 hours
        "leads_per_cycle": 8,
    },
    "agency": {
        "manual_scans_per_day": 3,
        "max_leads": 12,          # 12 leads/cycle x 4 scans/day = 48/day, 1440/month
        "categories": 999,
        "scan_interval_hours": 6,  # Every 6 hours
        "leads_per_cycle": 12,
    },
    "custom": {
        "manual_scans_per_day": 10,
        "max_leads": 25,          # Negotiated — contact for custom pricing
        "categories": 999,
        "scan_interval_hours": 4,
        "leads_per_cycle": 25,
    },
    "trial": {
        "manual_scans_per_day": 1,
        "max_leads": 3,           # 50% of starter — enough to see value
        "categories": 2,
        "scan_interval_hours": 12,
        "leads_per_cycle": 3,
    },
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="ARBTRADE API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ───────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class CriteriaUpdate(BaseModel):
    wholesale: dict
    online_arbitrage: dict

class CheckoutRequest(BaseModel):
    tier: str
    success_url: str
    cancel_url: str

# ── Auth helpers ─────────────────────────────────────────────────────────────

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    try:
        # Try with admin client first (more reliable)
        user = supabase_admin.auth.get_user(token)
        return user.user
    except Exception:
        try:
            # Fallback to anon client
            user = supabase.auth.get_user(token)
            return user.user
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_user_profile(user_id: str):
    try:
        result = supabase_admin.table("profiles").select("*").eq("id", user_id).single().execute()
        profile = result.data
        # Owner account always gets agency tier
        if profile and profile.get("email") == OWNER_EMAIL:
            profile["tier"] = "agency"
            profile["experience_level"] = "pro"
        return profile
    except Exception:
        return None

async def get_user_tier(user_id: str) -> str:
    profile = await get_user_profile(user_id)
    if not profile:
        return "trial"
    return profile.get("tier", "trial")

async def check_scan_limit(user_id: str) -> bool:
    """Returns True if user can run a manual scan."""
    tier = await get_user_tier(user_id)
    limit = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])["manual_scans_per_day"]
    today = datetime.now().date().isoformat()
    try:
        result = supabase_admin.table("scan_usage").select("count").eq("user_id", user_id).eq("date", today).execute()
        count = result.data[0]["count"] if result.data else 0
        return count < limit
    except Exception:
        return True

async def increment_scan_count(user_id: str):
    today = datetime.now().date().isoformat()
    try:
        existing = supabase_admin.table("scan_usage").select("*").eq("user_id", user_id).eq("date", today).execute()
        if existing.data:
            supabase_admin.table("scan_usage").update({"count": existing.data[0]["count"] + 1}).eq("user_id", user_id).eq("date", today).execute()
        else:
            supabase_admin.table("scan_usage").insert({"user_id": user_id, "date": today, "count": 1}).execute()
    except Exception as e:
        log.error(f"Failed to increment scan count: {e}")

# ── Research agent ───────────────────────────────────────────────────────────

def extract_json(text):
    s = text.find("["); e = text.rfind("]") + 1
    if s == -1 or e == 0: return None
    try: return json.loads(text[s:e])
    except: return None

def is_valid_asin(asin: str) -> bool:
    """Validate that an ASIN is real format - starts with B, exactly 10 chars."""
    if not asin or asin == "null" or asin == "None":
        return False
    asin = str(asin).strip()
    return len(asin) == 10 and asin.startswith("B") and asin[1:].isalnum()

def safe_asin(asin) -> str:
    """Return valid ASIN or empty string."""
    if is_valid_asin(str(asin or "")):
        return str(asin).strip()
    return ""

def safe_roi(val):
    try: return int(str(val).replace("%","").split("-")[0].strip() or 0)
    except: return 0

def normalize_lead(lead):
    for k in ["roi","bsr","buy_cost","sell_price"]:
        v = lead.get(k,0)
        if isinstance(v,(int,float)):
            if k == "roi": lead[k] = f"{int(v)}%"
            elif k == "bsr": lead[k] = f"#{int(v):,}"
            else: lead[k] = f"${v}"
    if isinstance(lead.get("risk_flags"), str):
        lead["risk_flags"] = [lead["risk_flags"]] if lead["risk_flags"] else []
    return lead

# Agent logic moved to agent_saas.py
from agent_saas import run_agent_for_user, get_lead_history_days, deduplicate_leads
from ian_agent import run_ian
from ivan_agent import run_ivan
from verify_agent import verify_leads_batch, get_verification_badge
from outreach_agent import run_outreach_for_lead

def run_agent_for_user_legacy(user_id: str, criteria: dict) -> list:
    ws = criteria.get("wholesale", {})
    oa = criteria.get("online_arbitrage", {})
    leads = []

    # Wholesale search
    try:
        cats = ", ".join(ws.get("categories", ["Health & Household"]))
        query = (
            f"You are an Amazon FBA wholesale expert. Generate 5 wholesale product leads "
            f"for categories: {cats}. "
            f"Criteria: BSR under #{ws.get('max_bsr',50000):,}, under {ws.get('max_sellers',8)} FBA sellers, "
            f"min {ws.get('min_monthly_sales',300)} monthly sales, min {ws.get('min_roi_percent',30)}% ROI. "
            f"Source from: Faire, RangeMe, Wholesale Central, or direct brands. "
            f"Return ONLY a JSON array. "
            f"Fields: name,asin,bsr,sellers,buy_cost,sell_price,roi,source,risk_flags,recommendation,reason,type. "
            f"type='wholesale'. recommendation=BUY/WATCH/PASS. Use string values eg roi='35%'."
        )
        resp = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role":"user","content":query}]
        )
        raw = "".join(b.text for b in resp.content if hasattr(b,"text"))
        ws_leads = extract_json(raw) or []
        for l in ws_leads:
            l["found_at"] = datetime.now().isoformat()
            l["user_id"] = user_id
            leads.append(normalize_lead(l))
        log.info(f"User {user_id}: {len(ws_leads)} wholesale leads")
    except Exception as e:
        log.error(f"Wholesale error for {user_id}: {e}")

    return leads

async def save_leads_for_user(user_id: str, leads: list, tier: str = "starter"):
    """Save leads to Supabase, keeping tier-based history window."""
    history_days = get_lead_history_days(tier)
    cutoff = (datetime.now() - timedelta(days=history_days)).isoformat()
    log.info("Saving " + str(len(leads)) + " leads for user " + str(user_id)[:8] + " tier=" + tier + " history=" + str(history_days) + "days")
    try:
        # Only delete leads older than history window - NEVER delete recent leads
        old_cutoff = (datetime.now() - timedelta(days=history_days)).isoformat()
        deleted = supabase_admin.table("leads").delete().eq("user_id", user_id).lt("found_at", old_cutoff).execute()
        log.info("Cleaned old leads for user " + str(user_id)[:8])
        # Insert new leads
        for lead in leads:
            supabase_admin.table("leads").insert({
                "user_id":        user_id,
                "name":           lead.get("name",""),
                "asin":           safe_asin(lead.get("asin","")),  # Only save real ASINs
                "data":           json.dumps(lead),
                "recommendation": lead.get("recommendation",""),
                "roi":            safe_roi(lead.get("roi",0)),
                "type":           lead.get("type","wholesale"),
                "found_at":       lead.get("found_at", datetime.now().isoformat()),
            }).execute()
    except Exception as e:
        log.error(f"Failed to save leads for {user_id}: {e}")

# ── Scheduled global scan ────────────────────────────────────────────────────

# ── Ian & Ivan: Twin Agent Runner ────────────────────────────────────────────

# Track API calls to prevent runaway spending
_api_call_count = {"count": 0, "reset_time": 0}

def check_api_rate_limit() -> bool:
    """Return True if OK to make API call, False if rate limited."""
    import time as _t
    now = _t.time()
    if now - _api_call_count["reset_time"] > 3600:  # Reset every hour
        _api_call_count["count"] = 0
        _api_call_count["reset_time"] = now
    _api_call_count["count"] += 1
    if _api_call_count["count"] > 50:  # Max 50 API calls per hour
        log.warning("API rate limit reached — skipping scan to protect credits")
        return False
    return True

def run_twin_agents(user_id: str, criteria: dict, ai_client, max_leads: int = 12) -> list:
    """
    Run Agent Ian and Agent Ivan with staggered start to avoid rate limits.
    Ian starts first, Ivan starts 15 seconds later.
    Both use live web search. Results merged and deduplicated.
    """
    import threading
    ian_results  = []
    ivan_results = []

    def run_ian_thread():
        try:
            results = run_ian(user_id, criteria, ai_client)
            ian_results.extend(results)
        except Exception as e:
            log.error("Agent Ian thread error: " + str(e))

    def run_ivan_thread():
        try:
            time.sleep(15)  # Stagger Ivan by 15 seconds to avoid rate limits
            results = run_ivan(user_id, criteria, ai_client)
            ivan_results.extend(results)
        except Exception as e:
            log.error("Agent Ivan thread error: " + str(e))

    # Launch both agents - Ivan starts 15s after Ian
    ian_thread  = threading.Thread(target=run_ian_thread,  daemon=True)
    ivan_thread = threading.Thread(target=run_ivan_thread, daemon=True)

    if not check_api_rate_limit():
        log.warning("Skipping scan - API rate limit reached")
        return []
    log.info("Launching Agent Ian and Agent Ivan for user " + str(user_id)[:8])
    ian_thread.start()
    ivan_thread.start()

    # Wait for both to complete (max 180 seconds)
    ian_thread.join(timeout=180)
    ivan_thread.join(timeout=180)

    # Merge results
    all_leads = ian_results + ivan_results
    log.info(
        "Agent Ian + Agent Ivan complete: Ian=" + str(len(ian_results)) +
        " Agent Ivan=" + str(len(ivan_results)) +
        " Total=" + str(len(all_leads))
    )

    # Deduplicate by name
    seen  = set()
    unique = []
    for lead in all_leads:
        key = (lead.get("name","") + lead.get("asin","")).lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(lead)

    # Sort by ROI descending
    def get_roi(lead):
        try: return float(str(lead.get("roi","0")).replace("%","").strip())
        except: return 0
    unique.sort(key=get_roi, reverse=True)

    # Trim to max leads
    return unique[:max_leads]

# ── Tier-based scan intervals ────────────────────────────────────────────────
# Starter: every 12 hours | Pro: every 8 hours | Agency: every 6 hours
# Each user gets scanned on their own interval based on their tier

import asyncio as _asyncio

def default_criteria():
    return {
        "wholesale": {
            "categories": ["Health & Household"],
            "max_bsr": 50000,
            "max_sellers": 8,
            "min_monthly_sales": 300,
            "min_roi_percent": 30,
            "enabled": True
        },
        "online_arbitrage": {
            "categories": ["Health & Household"],
            "max_bsr": 75000,
            "max_sellers": 12,
            "min_monthly_sales": 200,
            "min_roi_percent": 35,
            "min_price_spread": 8,
            "max_buy_cost": 35,
            "enabled": True
        }
    }

def scan_users_for_tier(tier: str):
    """Scan all users of a specific tier."""
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["starter"])
    max_leads = limits["leads_per_cycle"]
    log.info("Running " + tier + " tier scan (max " + str(max_leads) + " leads/user)...")
    try:
        users = supabase_admin.table("profiles").select("id,criteria,tier,email").eq("tier", tier).execute()
        scanned = 0
        for profile in (users.data or []):
            user_id  = profile["id"]
            criteria = profile.get("criteria") or {}
            if isinstance(criteria, str):
                try: criteria = json.loads(criteria)
                except: criteria = {}
            if not criteria:
                criteria = default_criteria()

            # Check for owner custom leads per cycle
            email = profile.get("email","")
            if email == OWNER_EMAIL:
                owner_cfg = criteria.get("owner_config", {})
                custom_leads = owner_cfg.get("custom_leads_per_cycle")
                if custom_leads and isinstance(custom_leads, int):
                    max_leads = custom_leads
                    log.info("Owner custom leads per cycle: " + str(max_leads))

            try:
                # Run Ian and Ivan in parallel for real verified leads
                leads = run_twin_agents(user_id, criteria, anthropic_client, max_leads)
                if leads:
                    loop = _asyncio.new_event_loop()
                    loop.run_until_complete(save_leads_for_user(user_id, leads, tier))
                    loop.close()
                scanned += 1
                log.info(tier + " scan: user " + str(user_id or "")[:8] + " got " + str(len(leads)) + " leads")
                # Log scan to scan_usage so support agent knows scans ran
                try:
                    today = datetime.now().date().isoformat()
                    existing = supabase_admin.table("scan_usage").select("*").eq("user_id", user_id).eq("date", today).execute()
                    if existing.data:
                        supabase_admin.table("scan_usage").update({
                            "count": existing.data[0]["count"] + 1
                        }).eq("user_id", user_id).eq("date", today).execute()
                    else:
                        supabase_admin.table("scan_usage").insert({
                            "user_id": user_id,
                            "date": today,
                            "count": 1
                        }).execute()
                except Exception as log_err:
                    log.error("Scan usage log error: " + str(log_err))
            except Exception as e:
                log.error("Scan error for user " + user_id[:8] + ": " + str(e))

            time.sleep(5)  # Rate limit protection between users

        log.info(tier + " scan complete — " + str(scanned) + " users scanned")
    except Exception as e:
        log.error(tier + " scan error: " + str(e))

def scan_trial_and_starter():
    """Runs every 12 hours — trial and starter users."""
    scan_users_for_tier("trial")
    scan_users_for_tier("starter")

def scan_pro():
    """Runs every 8 hours — pro users."""
    scan_users_for_tier("pro")

def scan_agency():
    """Runs every 6 hours — agency users."""
    scan_users_for_tier("agency")

def scan_custom():
    """Runs every 4 hours — custom plan users."""
    scan_users_for_tier("custom")

def start_scheduler():
    """Start the tier-based scan scheduler."""
    # Tier-based scan intervals
    schedule.every(12).hours.do(scan_trial_and_starter)
    schedule.every(8).hours.do(scan_pro)
    schedule.every(6).hours.do(scan_agency)
    schedule.every(4).hours.do(scan_custom)

    log.info("Scheduler started — Starter:12hr | Pro:8hr | Agency:6hr | Custom:4hr")

    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in background thread
scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
scheduler_thread.start()

# Startup scan disabled - scheduler handles all scanning
# Removing to prevent double-scanning on redeploy

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ARBTRADE API running", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

# Auth
@app.post("/auth/signup")
async def signup(req: SignupRequest):
    try:
        result = supabase.auth.sign_up({"email": req.email, "password": req.password})
        if result.user:
            # Create profile
            supabase_admin.table("profiles").insert({
                "id":    result.user.id,
                "email": req.email,
                "tier":  "trial",
                "criteria": json.dumps({}),
                "created_at": datetime.now().isoformat()
            }).execute()
        return {"user": result.user, "session": result.session}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
async def login(req: LoginRequest):
    try:
        result = supabase.auth.sign_in_with_password({"email": req.email, "password": req.password})
        return {
            "user":          result.user,
            "access_token":  result.session.access_token,
            "refresh_token": result.session.refresh_token,
            "expires_in":    result.session.expires_in,
            "session": {
                "access_token":  result.session.access_token,
                "refresh_token": result.session.refresh_token,
                "expires_in":    result.session.expires_in,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/auth/logout")
async def logout(user=Depends(get_current_user)):
    supabase.auth.sign_out()
    return {"message": "Logged out"}

# Profile
@app.get("/profile")
async def get_profile(user=Depends(get_current_user)):
    profile = await get_user_profile(user.id)
    tier = profile.get("tier","trial") if profile else "trial"
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
    return {"user": user, "profile": profile, "tier": tier, "limits": limits}

# Criteria
@app.get("/criteria")
async def get_criteria(user=Depends(get_current_user)):
    profile = await get_user_profile(user.id)
    criteria = profile.get("criteria", {}) if profile else {}
    if isinstance(criteria, str): criteria = json.loads(criteria)
    return {"criteria": criteria}

@app.put("/criteria")
async def update_criteria(req: CriteriaUpdate, user=Depends(get_current_user)):
    try:
        supabase_admin.table("profiles").update({
            "criteria": json.dumps({"wholesale": req.wholesale, "online_arbitrage": req.online_arbitrage})
        }).eq("id", user.id).execute()
        return {"message": "Criteria updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Leads
@app.get("/leads")
async def get_leads(user=Depends(get_current_user), filter: str = "all"):
    tier = await get_user_tier(user.id)
    # Use tier-based history window NOT leads_per_cycle
    # Trial gets SAME history as their selected plan - no reduced experience
    history_map = {
        "trial":   7,   # Same as starter - trial is just no-charge period
        "starter": 7,
        "pro":     30,
        "agency":  90,
        "custom":  90,
    }
    # Display limit — how many to show in dashboard
    display_limit_map = {
        "trial":   50,
        "starter": 200,
        "pro":     500,
        "agency":  1000,
        "custom":  2000,
    }
    history_days = history_map.get(tier, 7)
    display_limit = display_limit_map.get(tier, 200)
    cutoff = (datetime.now() - timedelta(days=history_days)).isoformat()
    try:
        query = supabase_admin.table("leads").select("*").eq("user_id", user.id).gte("found_at", cutoff).order("found_at", desc=True).limit(display_limit)
        if filter == "wholesale": query = query.eq("type","wholesale")
        elif filter == "oa": query = query.eq("type","oa")
        elif filter == "BUY": query = query.eq("recommendation","BUY")
        result = query.execute()
        raw_leads = [json.loads(r["data"]) for r in (result.data or [])]
        # Clean fake ASINs before returning to dashboard
        for l in raw_leads:
            asin = str(l.get("asin","") or "")
            if not (len(asin)==10 and asin.startswith("B") and asin[1:].isalnum() 
                    and asin not in ["B00XXXXX","B0EXAMPLE","B0XXXXXXXX"]):
                l["asin"] = ""  # Strip fake ASIN — dashboard will use name search
        leads = raw_leads
        ws_count = sum(1 for l in leads if l.get("type")=="wholesale")
        oa_count = sum(1 for l in leads if l.get("type")=="oa")
        best_roi = max((safe_roi(l.get("roi",0)) for l in leads), default=0)
        return {
            "leads": leads,
            "total_leads": len(leads),
            "wholesale_count": ws_count,
            "oa_count": oa_count,
            "best_roi": best_roi,
            "last_run": datetime.now().isoformat(),
            "tier": tier,
            "history_days": history_days,
            "display_limit": display_limit
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Manual scan
@app.post("/scan")
async def manual_scan(background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    can_scan = await check_scan_limit(user.id)
    if not can_scan:
        tier = await get_user_tier(user.id)
        limit = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])["manual_scans_per_day"]
        raise HTTPException(status_code=429, detail=f"Daily scan limit reached ({limit}/day on your plan). Upgrade for more scans.")
    await increment_scan_count(user.id)
    profile = await get_user_profile(user.id)
    criteria = profile.get("criteria", {}) if profile else {}
    if isinstance(criteria, str): criteria = json.loads(criteria)

    async def do_scan():
        try:
            tier = profile.get("tier", "starter") if profile else "starter"
            max_leads = TIER_LIMITS.get(tier, TIER_LIMITS["starter"])["leads_per_cycle"]
            leads = run_twin_agents(user.id, criteria, anthropic_client, max_leads)
            if leads:
                await save_leads_for_user(user.id, leads, tier)
        except Exception as e:
            log.error("Manual scan error for user " + str(user.id)[:8] + ": " + str(e))
            import traceback
            log.error(traceback.format_exc())
            # Manual scan error: " + str(e))

    background_tasks.add_task(do_scan)
    return {"message": "Scan started — check back in 30 seconds for results"}

# Stripe billing
@app.post("/billing/checkout")
async def create_checkout(req: CheckoutRequest, user=Depends(get_current_user)):
    price_id = STRIPE_PRICES.get(req.tier)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid tier")
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            subscription_data={
                "trial_period_days": 7,
                "metadata": {"tier": req.tier, "user_id": user.id}
            },
            success_url=req.success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=req.cancel_url,
            metadata={"user_id": user.id, "tier": req.tier},
            client_reference_id=user.id,
        )
        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/billing/portal")
async def billing_portal(user=Depends(get_current_user)):
    profile = await get_user_profile(user.id)
    customer_id = profile.get("stripe_customer_id") if profile else None
    if not customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")
    try:
        session = stripe.billing_portal.Session.create(customer=customer_id, return_url="https://arbtrade-saas-production.up.railway.app/dashboard.html")
        return {"portal_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/billing/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        tier = session.get("metadata", {}).get("tier", "starter")
        customer_id = session.get("customer")
        if user_id:
            # Check if this is a trial
            sub_status = "trialing" if session.get("subscription") else "active"
            try:
                # Get subscription status from Stripe
                if session.get("subscription"):
                    sub = stripe.Subscription.retrieve(session["subscription"])
                    sub_status = sub.status
            except: pass
            supabase_admin.table("profiles").update({
                "tier":                tier,
                "stripe_customer_id":  customer_id,
                "subscription_status": sub_status,
                "subscribed_at":       datetime.now().isoformat()
            }).eq("id", user_id).execute()
            log.info(f"User {user_id} upgraded to {tier} ({sub_status})")

    elif event["type"] in ["customer.subscription.deleted", "customer.subscription.paused"]:
        customer_id = event["data"]["object"].get("customer")
        if customer_id:
            supabase_admin.table("profiles").update({"tier": "cancelled"}).eq("stripe_customer_id", customer_id).execute()

    return {"status": "ok"}

# Usage stats
@app.get("/usage")
async def get_usage(user=Depends(get_current_user)):
    tier = await get_user_tier(user.id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
    today = datetime.now().date().isoformat()
    try:
        # Clean old usage records (auto daily reset)
        supabase_admin.table("scan_usage").delete().eq("user_id", user.id).lt("date", today).execute()
    except: pass
    try:
        result = supabase_admin.table("scan_usage").select("count").eq("user_id", user.id).eq("date", today).execute()
        scans_today = result.data[0]["count"] if result.data else 0
    except: scans_today = 0
    return {
        "tier": tier,
        "scans_today": scans_today,
        "scans_limit": limits["manual_scans_per_day"],
        "max_leads": limits["max_leads"],
        "categories_limit": limits["categories"],
        "date": today
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

# ── Daily Digest Integration ─────────────────────────────────────────────────

from digest import send_digest, send_all_digests

@app.get("/leads/approve")
async def approve_lead(index: int, name: str, user_id: str = "", request: Request = None):
    """One-click approve from email — records approval."""
    # Log the approval
    if user_id:
        try:
            supabase_admin.table("leads").update({
                "approved": True,
                "approved_at": datetime.now().isoformat()
            }).eq("user_id", user_id).ilike("name", "%" + name[:20] + "%").execute()
        except:
            pass
    return HTMLResponse(content="""
    <!DOCTYPE html><html>
    <head><meta charset="UTF-8">
    <style>
    body{{background:#0a0a08;color:#f2efe8;font-family:sans-serif;display:flex;align-items:center;
         justify-content:center;min-height:100vh;margin:0}}
    .card{{background:#161719;border:1px solid rgba(62,207,160,0.3);border-radius:12px;
           padding:40px;text-align:center;max-width:400px}}
    .icon{{font-size:48px;margin-bottom:16px}}
    h2{{color:#3ECFA0;margin-bottom:8px}}
    p{{color:#888884;font-size:14px;line-height:1.6}}
    a{{color:#c8a96e;text-decoration:none;font-size:13px}}
    </style></head>
    <body><div class="card">
    <div class="icon">✓</div>
    <h2>Lead Approved!</h2>
    <p><strong style="color:#f2efe8">{name}</strong><br><br>
    Your approval has been recorded. A purchase order will be prepared shortly.<br><br>
    Check your dashboard for next steps.</p>
    <br><a href="{os.getenv('APP_URL','https://monumental-hamster-dd12a2.netlify.app')}/dashboard.html">
    Open Dashboard →</a>
    </div></body></html>
    """, status_code=200)

@app.get("/leads/skip")
async def skip_lead(index: int, name: str):
    """One-click skip from email."""
    return HTMLResponse(content=f"""
    <!DOCTYPE html><html>
    <head><meta charset="UTF-8">
    <style>
    body{{background:#0a0a08;color:#f2efe8;font-family:sans-serif;display:flex;align-items:center;
         justify-content:center;min-height:100vh;margin:0}}
    .card{{background:#161719;border:1px solid rgba(255,255,255,0.08);border-radius:12px;
           padding:40px;text-align:center;max-width:400px}}
    .icon{{font-size:48px;margin-bottom:16px}}
    h2{{color:#888884;margin-bottom:8px}}
    p{{color:#888884;font-size:14px;line-height:1.6}}
    a{{color:#c8a96e;text-decoration:none;font-size:13px}}
    </style></head>
    <body><div class="card">
    <div class="icon">○</div>
    <h2>Lead Skipped</h2>
    <p><strong style="color:#f2efe8">{name}</strong><br><br>
    Got it — this lead has been skipped.<br><br>
    Your agent will continue finding new opportunities every 4 hours.</p>
    <br><a href="{os.getenv('APP_URL','https://monumental-hamster-dd12a2.netlify.app')}/dashboard.html">
    Open Dashboard →</a>
    </div></body></html>
    """, status_code=200)

@app.get("/unsubscribe")
async def unsubscribe(email: str):
    """Unsubscribe from digest emails."""
    try:
        supabase_admin.table("profiles").update({"digest_enabled": False}).eq("email", email).execute()
    except: pass
    return HTMLResponse(content=f"""
    <!DOCTYPE html><html>
    <head><meta charset="UTF-8">
    <style>
    body{{background:#0a0a08;color:#f2efe8;font-family:sans-serif;display:flex;align-items:center;
         justify-content:center;min-height:100vh;margin:0}}
    .card{{background:#161719;border:1px solid rgba(255,255,255,0.08);border-radius:12px;
           padding:40px;text-align:center;max-width:400px}}
    </style></head>
    <body><div class="card">
    <h2 style="color:#c8a96e">Unsubscribed</h2>
    <p style="color:#888884">You've been unsubscribed from ARBTRADE daily digests.<br><br>
    You can re-enable them anytime from your dashboard settings.</p>
    <br><a href="{os.getenv('APP_URL','')}/dashboard.html" style="color:#c8a96e;text-decoration:none">
    Back to Dashboard →</a>
    </div></body></html>
    """, status_code=200)

@app.post("/digest/send-test")
async def send_test_digest(user=Depends(get_current_user)):
    """Send a test digest to the logged-in user."""
    try:
        result = supabase_admin.table("leads").select("data").eq("user_id", user.id).limit(5).execute()
        leads = [json.loads(r["data"]) for r in (result.data or [])]
        profile = await get_user_profile(user.id)
        tier = profile.get("tier","trial") if profile else "trial"
        success = send_digest(user.email, leads, tier, anthropic_client)
        if success:
            return {"message": f"Test digest sent to {user.email}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send digest")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def send_daily_digests_job():
    """Scheduled job — sends digest to all subscribers once per day."""
    log.info("Running daily digest job...")
    try:
        users = supabase_admin.table("profiles").select("id,email,tier").neq("tier","cancelled").neq("tier","trial").execute()
        import asyncio
        for profile in (users.data or []):
            user_id = profile["id"]
            email = profile.get("email","")
            tier = profile.get("tier","starter")
            cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
            result = supabase_admin.table("leads").select("data,recommendation,roi").eq("user_id",user_id).gte("found_at",cutoff).order("roi",desc=True).limit(10).execute()
            leads = [json.loads(r["data"]) for r in (result.data or [])]
            if email and leads:
                send_digest(email, leads, tier, anthropic_client)
                time.sleep(1)
        log.info("Daily digest job complete")
    except Exception as e:
        log.error(f"Daily digest job error: {e}")

# Schedule daily digest at 8 AM

# ── Experience Level ─────────────────────────────────────────────────────────

class ExperienceUpdate(BaseModel):
    experience_level: str  # "new", "mid", "pro"

@app.post("/profile/experience")
async def update_experience(req: ExperienceUpdate, user=Depends(get_current_user)):
    try:
        supabase_admin.table("profiles").update({
            "experience_level": req.experience_level
        }).eq("id", user.id).execute()
        return {"message": "Experience level saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/profile/experience")
async def get_experience(user=Depends(get_current_user)):
    profile = await get_user_profile(user.id)
    return {"experience_level": profile.get("experience_level","new") if profile else "new"}

# ── Supplier CRM ─────────────────────────────────────────────────────────────

class SupplierCreate(BaseModel):
    name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    platform: str = ""        # Faire, RangeMe, Direct, etc
    status: str = "prospect"  # prospect, applied, approved, active, paused
    moq: str = ""             # Minimum order quantity
    payment_terms: str = ""   # Net 30, Net 60, COD, etc
    lead_time_days: int = 0
    notes: str = ""
    categories: str = ""

class SupplierUpdate(BaseModel):
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    platform: str = ""
    status: str = ""
    moq: str = ""
    payment_terms: str = ""
    lead_time_days: int = 0
    notes: str = ""
    categories: str = ""

@app.get("/suppliers")
async def get_suppliers(user=Depends(get_current_user)):
    """Get all suppliers for the current user."""
    try:
        result = supabase_admin.table("suppliers").select("*").eq("user_id", user.id).order("name").execute()
        return {"suppliers": result.data or []}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/suppliers")
async def create_supplier(req: SupplierCreate, user=Depends(get_current_user)):
    """Add a new supplier."""
    try:
        data = {
            "user_id":       user.id,
            "name":          req.name,
            "contact_name":  req.contact_name,
            "email":         req.email,
            "phone":         req.phone,
            "website":       req.website,
            "platform":      req.platform,
            "status":        req.status,
            "moq":           req.moq,
            "payment_terms": req.payment_terms,
            "lead_time_days":req.lead_time_days,
            "notes":         req.notes,
            "categories":    req.categories,
            "created_at":    datetime.now().isoformat(),
            "updated_at":    datetime.now().isoformat(),
        }
        result = supabase_admin.table("suppliers").insert(data).execute()
        return {"supplier": result.data[0] if result.data else {}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, req: SupplierUpdate, user=Depends(get_current_user)):
    """Update a supplier."""
    try:
        update_data = {k: v for k, v in req.dict().items() if v}
        update_data["updated_at"] = datetime.now().isoformat()
        supabase_admin.table("suppliers").update(update_data).eq("id", supplier_id).eq("user_id", user.id).execute()
        return {"message": "Supplier updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str, user=Depends(get_current_user)):
    """Delete a supplier."""
    try:
        supabase_admin.table("suppliers").delete().eq("id", supplier_id).eq("user_id", user.id).execute()
        return {"message": "Supplier deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/suppliers/{supplier_id}/generate-email")
async def generate_outreach_email(supplier_id: str, user=Depends(get_current_user)):
    """Generate a professional account opening email for a supplier."""
    try:
        result = supabase_admin.table("suppliers").select("*").eq("id", supplier_id).eq("user_id", user.id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Supplier not found")

        supplier = result.data[0]
        profile  = await get_user_profile(user.id)

        prompt = (
            "Write a professional wholesale account opening email to a supplier.\n\n"
            "Supplier: " + supplier.get("name","") + "\n"
            "Platform: " + supplier.get("platform","") + "\n"
            "Categories: " + supplier.get("categories","Health and Wellness") + "\n"
            "Seller business: Amazon FBA seller focused on " + supplier.get("categories","Health & Household") + "\n\n"
            "The email should:\n"
            "- Be professional but warm\n"
            "- Mention Amazon FBA experience\n"
            "- Ask about wholesale pricing, MOQ, and payment terms\n"
            "- Express genuine interest in a long-term relationship\n"
            "- Be concise (under 200 words)\n"
            "- Include placeholders for [Business Name] and [Your Name]\n\n"
            "Return ONLY the email body, no subject line."
        )

        resp = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            messages=[{"role":"user","content":prompt}]
        )
        email_body = "".join(b.text for b in resp.content if hasattr(b,"text")).strip()

        return {
            "subject": "Wholesale Account Application — [Business Name]",
            "body": email_body,
            "supplier": supplier.get("name","")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Purchase Order Generation ─────────────────────────────────────────────────

class PORequest(BaseModel):
    lead_name: str
    asin: str = ""
    supplier_name: str = ""
    quantity: int = 0
    unit_cost: str = ""
    notes: str = ""

@app.post("/orders/generate")
async def generate_po(req: PORequest, user=Depends(get_current_user)):
    """Generate a purchase order for an approved lead."""
    try:
        profile = await get_user_profile(user.id)
        today   = datetime.now().strftime("%B %d, %Y")
        po_num  = "PO-" + datetime.now().strftime("%Y%m%d") + "-" + str(int(datetime.now().timestamp()))[-4:]

        # Calculate total
        total = ""
        try:
            price = float(str(req.unit_cost).replace("$","").strip())
            total = "$" + str(round(price * req.quantity, 2))
        except:
            total = "—"

        po_text = (
            "PURCHASE ORDER\n"
            "══════════════════════════════════\n"
            "PO Number: " + po_num + "\n"
            "Date: " + today + "\n\n"
            "FROM:\n"
            "[Your Business Name]\n"
            "[Your Address]\n"
            "[City, State, ZIP]\n\n"
            "TO:\n"
            + (req.supplier_name or "[Supplier Name]") + "\n\n"
            "SHIP TO:\n"
            "[Your 3PL Name]\n"
            "[3PL Address]\n"
            "[City, State, ZIP]\n\n"
            "══════════════════════════════════\n"
            "ITEM DETAILS\n"
            "══════════════════════════════════\n"
            "Product: " + req.lead_name + "\n"
            "ASIN: " + (req.asin or "—") + "\n"
            "Quantity: " + str(req.quantity) + " units\n"
            "Unit Cost: " + (req.unit_cost or "—") + "\n"
            "Total: " + total + "\n\n"
            "══════════════════════════════════\n"
            "SPECIAL INSTRUCTIONS\n"
            "══════════════════════════════════\n"
            "- Please include packing slip with order\n"
            "- Do NOT include retail pricing on boxes\n"
            "- Ship to 3PL address above (not Amazon directly)\n"
            + (("- Notes: " + req.notes + "\n") if req.notes else "") +
            "\nPayment terms: Net 30\n"
            "Please confirm receipt of this PO.\n\n"
            "Thank you,\n"
            "[Your Name]\n"
            "[Your Business Name]"
        )

        # Save order to database
        order_data = {
            "user_id":      user.id,
            "po_number":    po_num,
            "product_name": req.lead_name,
            "asin":         req.asin,
            "quantity":     req.quantity,
            "unit_cost":    req.unit_cost,
            "total_cost":   total,
            "status":       "draft",
            "notes":        req.notes,
            "created_at":   datetime.now().isoformat(),
            "updated_at":   datetime.now().isoformat(),
        }

        # Try to match supplier
        if req.supplier_name:
            supplier_result = supabase_admin.table("suppliers").select("id").eq("user_id", user.id).ilike("name", "%" + req.supplier_name + "%").limit(1).execute()
            if supplier_result.data:
                order_data["supplier_id"] = supplier_result.data[0]["id"]

        supabase_admin.table("orders").insert(order_data).execute()

        return {
            "po_number":  po_num,
            "po_text":    po_text,
            "total":      total,
            "message":    "Purchase order generated successfully"
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/orders")
async def get_orders(user=Depends(get_current_user)):
    """Get all orders for the current user."""
    try:
        result = supabase_admin.table("orders").select("*").eq("user_id", user.id).order("created_at", desc=True).execute()
        return {"orders": result.data or []}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, status: str, user=Depends(get_current_user)):
    """Update order status: draft, sent, confirmed, shipped, received."""
    try:
        supabase_admin.table("orders").update({
            "status":     status,
            "updated_at": datetime.now().isoformat()
        }).eq("id", order_id).eq("user_id", user.id).execute()
        return {"message": "Order status updated to " + status}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Reorder Trigger System ────────────────────────────────────────────────────

class ActiveSKU(BaseModel):
    asin: str
    product_name: str
    supplier_name: str = ""
    units_in_stock: int = 0
    daily_sales_velocity: float = 0.0
    reorder_point_days: int = 30
    reorder_quantity: int = 0
    unit_cost: str = ""
    notes: str = ""

@app.get("/skus")
async def get_skus(user=Depends(get_current_user)):
    """Get all active SKUs being monitored."""
    try:
        result = supabase_admin.table("active_skus").select("*").eq("user_id", user.id).order("product_name").execute()
        skus = result.data or []
        # Calculate days of stock remaining for each SKU
        for sku in skus:
            velocity = sku.get("daily_sales_velocity", 0)
            stock    = sku.get("units_in_stock", 0)
            if velocity and velocity > 0:
                sku["days_remaining"] = round(stock / velocity)
                sku["reorder_needed"] = sku["days_remaining"] <= sku.get("reorder_point_days", 30)
            else:
                sku["days_remaining"] = None
                sku["reorder_needed"] = False
        return {"skus": skus}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/skus")
async def add_sku(req: ActiveSKU, user=Depends(get_current_user)):
    """Add a SKU to monitor for reorder triggers."""
    try:
        data = {
            "user_id":              user.id,
            "asin":                 req.asin,
            "product_name":         req.product_name,
            "supplier_name":        req.supplier_name,
            "units_in_stock":       req.units_in_stock,
            "daily_sales_velocity": req.daily_sales_velocity,
            "reorder_point_days":   req.reorder_point_days,
            "reorder_quantity":     req.reorder_quantity,
            "unit_cost":            req.unit_cost,
            "notes":                req.notes,
            "created_at":           datetime.now().isoformat(),
            "updated_at":           datetime.now().isoformat(),
        }
        result = supabase_admin.table("active_skus").insert(data).execute()
        return {"sku": result.data[0] if result.data else {}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/skus/{sku_id}")
async def update_sku(sku_id: str, req: ActiveSKU, user=Depends(get_current_user)):
    """Update a SKU's stock level and settings."""
    try:
        update_data = {k:v for k,v in req.dict().items() if v}
        update_data["updated_at"] = datetime.now().isoformat()
        supabase_admin.table("active_skus").update(update_data).eq("id", sku_id).eq("user_id", user.id).execute()
        return {"message": "SKU updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/skus/{sku_id}")
async def delete_sku(sku_id: str, user=Depends(get_current_user)):
    """Remove a SKU from monitoring."""
    try:
        supabase_admin.table("active_skus").delete().eq("id", sku_id).eq("user_id", user.id).execute()
        return {"message": "SKU removed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/skus/alerts")
async def get_reorder_alerts(user=Depends(get_current_user)):
    """Get SKUs that need reordering now."""
    try:
        result = supabase_admin.table("active_skus").select("*").eq("user_id", user.id).execute()
        alerts = []
        for sku in (result.data or []):
            velocity = sku.get("daily_sales_velocity", 0)
            stock    = sku.get("units_in_stock", 0)
            if velocity and velocity > 0:
                days_remaining = round(stock / velocity)
                if days_remaining <= sku.get("reorder_point_days", 30):
                    sku["days_remaining"] = days_remaining
                    sku["urgency"] = "critical" if days_remaining <= 14 else "warning"
                    alerts.append(sku)
        alerts.sort(key=lambda x: x.get("days_remaining", 999))
        return {"alerts": alerts, "count": len(alerts)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def check_reorder_alerts_job():
    """Scheduled job — checks all users' SKUs for reorder triggers daily."""
    log.info("Running reorder alert check...")
    try:
        users = supabase_admin.table("profiles").select("id,email,tier").neq("tier","cancelled").execute()
        for profile in (users.data or []):
            user_id = profile["id"]
            email   = profile.get("email","")
            result  = supabase_admin.table("active_skus").select("*").eq("user_id", user_id).execute()
            alerts  = []
            for sku in (result.data or []):
                velocity = sku.get("daily_sales_velocity", 0)
                stock    = sku.get("units_in_stock", 0)
                if velocity and velocity > 0:
                    days = round(stock / velocity)
                    if days <= sku.get("reorder_point_days", 30):
                        sku["days_remaining"] = days
                        alerts.append(sku)
            if alerts and email:
                send_reorder_alert(email, alerts)
        log.info("Reorder alert check complete")
    except Exception as e:
        log.error("Reorder alert error: " + str(e))

def send_reorder_alert(email: str, alerts: list):
    """Send reorder alert email via SendGrid."""
    if not SENDGRID_API_KEY:
        return
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        items = ""
        for a in alerts:
            days = a.get("days_remaining", 0)
            urgency_color = "#FF5C5C" if days <= 14 else "#c8a96e"
            items += (
                '<div style="background:#161719;border:1px solid rgba(255,255,255,0.08);'
                'border-radius:8px;padding:14px 16px;margin-bottom:10px;'
                'border-left:3px solid ' + urgency_color + '">'
                '<div style="font-size:14px;font-weight:600;color:#f2efe8;margin-bottom:4px">' + a.get("product_name","") + '</div>'
                '<div style="font-size:12px;font-family:monospace;color:#888884">'
                'Days remaining: <strong style="color:' + urgency_color + '">' + str(days) + ' days</strong> &nbsp;·&nbsp; '
                'Units in stock: <strong style="color:#f2efe8">' + str(a.get("units_in_stock","")) + '</strong> &nbsp;·&nbsp; '
                'Velocity: <strong style="color:#f2efe8">' + str(a.get("daily_sales_velocity","")) + '/day</strong>'
                '</div>'
                '</div>'
            )
        html = (
            '<body style="background:#0a0a08;font-family:sans-serif;padding:32px">'
            '<div style="max-width:560px;margin:0 auto">'
            '<div style="font-size:10px;color:#c8a96e;font-family:monospace;letter-spacing:.15em;margin-bottom:4px">ARBTRADE</div>'
            '<div style="font-size:18px;font-weight:700;color:#f2efe8;margin-bottom:4px">⚠ Reorder Alert</div>'
            '<div style="font-size:12px;color:#888884;font-family:monospace;margin-bottom:20px">'
            + str(len(alerts)) + ' SKU(s) need reordering now</div>'
            + items +
            '<a href="https://monumental-hamster-dd12a2.netlify.app/dashboard.html" '
            'style="display:inline-block;background:#c8a96e;color:#000;font-weight:700;'
            'padding:10px 20px;border-radius:6px;text-decoration:none;margin-top:16px;font-size:12px">'
            'Open Dashboard →</a>'
            '</div></body>'
        )
        msg = Mail(
            from_email=(FROM_EMAIL, FROM_NAME),
            to_emails=email,
            subject="⚠ ARBTRADE Reorder Alert — " + str(len(alerts)) + " SKU(s) need attention",
            html_content=html
        )
        SendGridAPIClient(SENDGRID_API_KEY).send(msg)
        log.info("Reorder alert sent to " + email)
    except Exception as e:
        log.error("Reorder alert email error: " + str(e))

# Schedule reorder check daily at 9 AM

# ── Outreach Agent ────────────────────────────────────────────────────────────

class OutreachRequest(BaseModel):
    lead_name: str
    lead_source: str = ""
    lead_type: str = "wholesale"
    seller_name: str = ""
    business_name: str = ""

@app.post("/outreach/generate")
async def generate_outreach(req: OutreachRequest, user=Depends(get_current_user)):
    """Run Agent 3 - generate outreach package for an approved wholesale lead."""
    try:
        profile = await get_user_profile(user.id)
        tier    = profile.get("tier","starter") if profile else "starter"

        # Only Pro and Agency get outreach agent
        if tier not in ["pro","agency","custom"]:
            raise HTTPException(
                status_code=403,
                detail="Outreach agent available on Pro and Agency plans"
            )

        lead = {
            "name":   req.lead_name,
            "source": req.lead_source,
            "type":   req.lead_type,
        }

        result = run_outreach_for_lead(
            lead        = lead,
            user_id     = user.id,
            supabase_admin = supabase_admin,
            ai_client   = anthropic_client,
            seller_name = req.seller_name or user.email,
            business_name = req.business_name or "Amazon FBA Business"
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Admin Stats ───────────────────────────────────────────────────────────────

@app.get("/admin/stats")
async def get_admin_stats(secret: str = ""):
    """Admin dashboard — platform metrics overview."""
    admin_secret = os.getenv("ADMIN_SECRET", "arbtrade-admin-2026")
    if secret != admin_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
    try:
        # Users
        users     = supabase_admin.table("profiles").select("id,tier,created_at").execute()
        all_users = users.data or []
        tiers     = {}
        for u in all_users:
            t = u.get("tier","trial")
            tiers[t] = tiers.get(t, 0) + 1

        # Leads
        leads_result = supabase_admin.table("leads").select("id,type,recommendation,found_at").execute()
        all_leads    = leads_result.data or []
        today        = datetime.now().date().isoformat()
        leads_today  = [l for l in all_leads if l.get("found_at","").startswith(today)]

        # Suppliers
        suppliers = supabase_admin.table("suppliers").select("id").execute()

        # Orders
        orders = supabase_admin.table("orders").select("id,status").execute()

        # Revenue estimate
        tier_prices = {"starter":47,"pro":97,"agency":197,"custom":497}
        mrr = sum(tier_prices.get(u.get("tier",""),0) for u in all_users if u.get("tier") not in ["trial","cancelled",""])

        return {
            "users": {
                "total":       len(all_users),
                "by_tier":     tiers,
                "paid":        sum(1 for u in all_users if u.get("tier") not in ["trial","cancelled",""]),
            },
            "leads": {
                "total":       len(all_leads),
                "today":       len(leads_today),
                "buy":         sum(1 for l in all_leads if l.get("recommendation")=="BUY"),
                "wholesale":   sum(1 for l in all_leads if l.get("type")=="wholesale"),
                "oa":          sum(1 for l in all_leads if l.get("type")=="oa"),
            },
            "suppliers":       len(suppliers.data or []),
            "orders":          len(orders.data or []),
            "mrr_estimate":    "$" + str(mrr),
            "timestamp":       datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Password Reset ────────────────────────────────────────────────────────────

class ResetPasswordRequest(BaseModel):
    email: str

class UpdatePasswordRequest(BaseModel):
    password: str
    access_token: str

@app.post("/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """Send password reset email via Supabase."""
    try:
        supabase_admin.auth.reset_password_email(
            req.email,
            options={"redirect_to": "https://getarbtrade.com/reset-password.html"}
        )
        return {"message": "Reset link sent"}
    except Exception as e:
        # Don't reveal if email exists or not
        return {"message": "If that email exists, a reset link has been sent"}

@app.post("/auth/update-password")
async def update_password(req: UpdatePasswordRequest):
    """Update password after reset."""
    try:
        supabase_admin.auth.admin.update_user_by_id(
            req.access_token,
            {"password": req.password}
        )
        return {"message": "Password updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Owner debug endpoint ──────────────────────────────────────────────────────

@app.get("/owner/scan-now")
async def owner_scan_now(secret: str = ""):
    """Owner-only endpoint to trigger immediate scan bypassing limits."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        import threading
        def run():
            log.info("Owner triggered manual scan...")
            scan_agency()
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return {"message": "Agency scan triggered — check logs in 60-90 seconds"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/owner/logs")
async def owner_logs(secret: str = ""):
    """Check recent scan activity."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        # Check leads created in last hour
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
        result = supabase_admin.table("leads").select("id,name,type,found_at").gte("found_at", cutoff).execute()
        return {
            "leads_last_hour": len(result.data or []),
            "recent_leads": result.data[:5] if result.data else [],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/owner/test-agent")
async def test_agent(secret: str = ""):
    """Test the agent directly and return results."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        # Test 1: Can we reach Anthropic?
        test_resp = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say OK"}]
        )
        anthropic_ok = test_resp.content[0].text if test_resp.content else "no response"

        # Test 2: Can we reach Supabase?
        users = supabase_admin.table("profiles").select("id,tier").limit(1).execute()
        supabase_ok = "yes - " + str(len(users.data or [])) + " users found"

        # Test 3: Run Ian and Ivan twin agents
        test_criteria = {
            "wholesale": {
                "categories": ["Health & Household"],
                "max_bsr": 50000,
                "max_sellers": 8,
                "min_monthly_sales": 300,
                "min_roi_percent": 30,
                "enabled": True
            },
            "online_arbitrage": {
                "categories": ["Health & Household"],
                "min_roi_percent": 35,
                "max_buy_cost": 35,
                "enabled": True
            }
        }

        # Get first user's ID for test
        if users.data:
            test_user_id = users.data[0]["id"]
            leads = run_twin_agents(test_user_id, test_criteria, anthropic_client, 6)
            leads_found = len(leads)
            lead_names = [l.get("name","?") + " [" + l.get("agent","?") + "]" for l in leads[:3]]
        else:
            leads_found = 0
            lead_names = []
            test_user_id = "no users"

        return {
            "anthropic": anthropic_ok,
            "supabase": supabase_ok,
            "test_user_id": str(test_user_id)[:20],
            "leads_found": leads_found,
            "sample_leads": lead_names,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/owner/raw-leads")
async def raw_leads(secret: str = ""):
    """Get raw leads directly from database for debugging."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        result = supabase_admin.table("leads").select("id,name,type,recommendation,roi,found_at,user_id").order("found_at", desc=True).limit(20).execute()
        leads = result.data or []
        # Try parsing data column
        parsed = []
        for l in leads:
            parsed.append({
                "name": l.get("name"), 
                "type": l.get("type"), 
                "rec": l.get("recommendation"),
                "found_at": l.get("found_at","")[:16],
                "user_id": str(l.get("user_id",""))[:8]
            })
        return {"total_in_db": len(leads), "sample": parsed}
    except Exception as e:
        return {"error": str(e)}

# ── Support Ticket System ─────────────────────────────────────────────────────

from support_agent import process_ticket

class TicketRequest(BaseModel):
    category: str = "general"
    subject: str = ""
    message: str

@app.post("/support/ticket")
async def submit_ticket(req: TicketRequest, user=Depends(get_current_user)):
    """Submit a support ticket — AI responds within 60 seconds."""
    try:
        profile = await get_user_profile(user.id)
        tier = profile.get("tier", "trial") if profile else "trial"

        # Get user's lead count for context
        lead_result = supabase_admin.table("leads").select("id").eq("user_id", user.id).execute()
        lead_count = len(lead_result.data or [])

        # Get last scan time from leads table (more accurate than scan_usage)
        last_lead = supabase_admin.table("leads").select("found_at").eq("user_id", str(user.id)).order("found_at", desc=True).limit(1).execute()
        if last_lead.data:
            from datetime import timezone
            last_scan_dt = last_lead.data[0]["found_at"][:16].replace("T", " ")
            last_scan = last_scan_dt + " UTC"
        else:
            scan_result = supabase_admin.table("scan_usage").select("date,count").eq("user_id", str(user.id)).order("date", desc=True).limit(1).execute()
            last_scan = scan_result.data[0]["date"] if scan_result.data else "No scans recorded yet"

        # Get email safely
        user_email = getattr(user, 'email', '') or profile.get("email","") if profile else ""

        # Save ticket to database - wrapped in try/except so failure doesn't block response
        ticket_data = {
            "user_id":    str(user.id),
            "email":      user_email,
            "category":   req.category,
            "subject":    req.subject or req.category,
            "message":    req.message,
            "status":     "open",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        try:
            ticket_result = supabase_admin.table("support_tickets").insert(ticket_data).execute()
            ticket = ticket_result.data[0] if ticket_result.data else ticket_data
        except Exception as db_err:
            log.error("Ticket DB save error: " + str(db_err))
            ticket = ticket_data
        ticket["email"] = user_email

        # Build user context
        user_data = {
            "email":      user.email,
            "tier":       tier,
            "lead_count": lead_count,
            "last_scan":  last_scan,
        }

        # Process with AI agent
        sendgrid_key = os.getenv("SENDGRID_API_KEY","")
        owner_email  = os.getenv("OWNER_EMAIL", "ianseze@gmail.com")

        result = process_ticket(ticket, user_data, anthropic_client, sendgrid_key, owner_email)

        # Update ticket with AI response
        if ticket.get("id"):
            supabase_admin.table("support_tickets").update({
                "ai_response":     result["response"],
                "ai_responded_at": datetime.now().isoformat(),
                "status":          "resolved" if result["resolved"] else "escalated",
                "escalated":       result["escalate"],
                "updated_at":      datetime.now().isoformat(),
            }).eq("id", ticket["id"]).execute()

        return {
            "ticket_id": str(ticket.get("id",""))[:8],
            "response":  result["response"],
            "resolved":  result["resolved"],
            "escalated": result["escalate"],
            "message":   "Support response sent to your email"
        }

    except Exception as e:
        log.error("Ticket error: " + str(e))
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/support/tickets")
async def get_tickets(user=Depends(get_current_user)):
    """Get user's support ticket history."""
    try:
        result = supabase_admin.table("support_tickets").select("*").eq("user_id", str(user.id)).order("created_at", desc=True).limit(10).execute()
        return {"tickets": result.data or []}
    except Exception as e:
        log.error("Get tickets error: " + str(e))
        return {"tickets": []}

# ── Platform Health Monitor ───────────────────────────────────────────────────

from health_monitor import run_health_check

@app.get("/health/full")
async def full_health_check(secret: str = ""):
    """Run full platform health check."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    sendgrid_key = os.getenv("SENDGRID_API_KEY", "")
    owner_email  = os.getenv("OWNER_EMAIL", "ianseze@gmail.com")
    result = run_health_check(supabase_admin, anthropic_client, sendgrid_key, owner_email)
    return result

def health_monitor_job():
    """Runs every 15 minutes — checks platform health."""
    try:
        sendgrid_key = os.getenv("SENDGRID_API_KEY", "")
        owner_email  = os.getenv("OWNER_EMAIL", "ianseze@gmail.com")
        run_health_check(supabase_admin, anthropic_client, sendgrid_key, owner_email)
    except Exception as e:
        log.error("Health monitor error: " + str(e))

# Schedule health check every 15 minutes
schedule.every(2).hours.do(health_monitor_job)  # Reduced from 15min to save API credits

# ── Agent 4: Monitor Agent ────────────────────────────────────────────────────
from monitor_agent import monitor_all_skus, send_monitor_alert

@app.get("/monitor/run")
async def run_monitor(user=Depends(get_current_user)):
    """Run market monitor for user's active SKUs."""
    try:
        profile = await get_user_profile(user.id)
        tier    = profile.get("tier","starter") if profile else "starter"
        if tier not in ["pro","agency","custom"]:
            raise HTTPException(status_code=403, detail="Monitor available on Pro and Agency plans")
        results = monitor_all_skus(str(user.id), supabase_admin, anthropic_client)
        return {"monitored": len(results), "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def run_monitor_job():
    """Scheduled job — monitors all Pro/Agency users' SKUs every 6 hours."""
    log.info("Running market monitor job...")
    try:
        for tier in ["pro","agency","custom"]:
            users = supabase_admin.table("profiles").select("id,email,tier").eq("tier", tier).execute()
            for profile in (users.data or []):
                user_id = profile["id"]
                email   = profile.get("email","")
                results = monitor_all_skus(user_id, supabase_admin, anthropic_client)
                alerts  = [r for r in results if r.get("alerts")]
                if alerts and email:
                    sendgrid_key = os.getenv("SENDGRID_API_KEY","")
                    send_monitor_alert(email, alerts, sendgrid_key)
        log.info("Market monitor job complete")
    except Exception as e:
        log.error("Monitor job error: " + str(e))

schedule.every(6).hours.do(run_monitor_job)

# ── Agent 5: Market Intelligence ──────────────────────────────────────────────
from market_intel_agent import run_market_intel, format_intel_for_digest, save_intel_to_db

@app.get("/intel/report")
async def get_market_intel(market: str = "US", user=Depends(get_current_user)):
    """Get market intelligence report for specified market."""
    try:
        profile = await get_user_profile(user.id)
        tier    = profile.get("tier","starter") if profile else "starter"
        if tier not in ["pro","agency","custom"]:
            raise HTTPException(status_code=403, detail="Market intelligence available on Pro and Agency plans")
        markets = [m.strip().upper() for m in market.split(",")]
        intel   = run_market_intel(anthropic_client, markets)
        save_intel_to_db(intel, supabase_admin)
        return {"intel": intel, "markets": markets, "generated_at": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def run_intel_job():
    """Scheduled job — runs market intelligence daily at 7 AM."""
    log.info("Running market intelligence job...")
    try:
        intel = run_market_intel(anthropic_client, ["US"])
        save_intel_to_db(intel, supabase_admin)
        log.info("Market intelligence complete")
    except Exception as e:
        log.error("Intel job error: " + str(e))

# Intel job disabled temporarily - re-enable when API credits stable
# schedule.every().day.at("07:00").do(run_intel_job)

# ── International Market Support ──────────────────────────────────────────────

SUPPORTED_MARKETS = {
    "US": {"name": "United States", "domain": "amazon.com",    "currency": "USD", "status": "live"},
    "CA": {"name": "Canada",        "domain": "amazon.ca",     "currency": "CAD", "status": "beta"},
    "MX": {"name": "Mexico",        "domain": "amazon.com.mx", "currency": "MXN", "status": "beta"},
    "UK": {"name": "United Kingdom","domain": "amazon.co.uk",  "currency": "GBP", "status": "coming_soon"},
    "DE": {"name": "Germany",       "domain": "amazon.de",     "currency": "EUR", "status": "coming_soon"},
    "JP": {"name": "Japan",         "domain": "amazon.co.jp",  "currency": "JPY", "status": "coming_soon"},
}

@app.get("/markets")
async def get_markets():
    """Get all supported and upcoming markets."""
    return {"markets": SUPPORTED_MARKETS}

@app.get("/markets/{market_code}/intel")
async def get_market_intel_by_code(market_code: str, user=Depends(get_current_user)):
    """Get market intelligence for a specific market."""
    try:
        code = market_code.upper()
        if code not in SUPPORTED_MARKETS:
            raise HTTPException(status_code=404, detail="Market not supported")
        market = SUPPORTED_MARKETS[code]
        if market["status"] == "coming_soon":
            return {"market": market, "status": "coming_soon", "message": "This market is coming soon!"}
        intel = run_market_intel(anthropic_client, [code])
        return {"market": market, "intel": intel, "generated_at": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Owner Analytics ───────────────────────────────────────────────────────────

@app.get("/owner/analytics")
async def owner_analytics(secret: str = ""):
    """Owner analytics — Agent Ian vs Ivan performance comparison."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        # Get all leads with agent data
        result = supabase_admin.table("leads").select(
            "id,name,type,recommendation,roi,data,found_at"
        ).order("found_at", desc=True).limit(500).execute()

        leads = []
        for r in (result.data or []):
            try:
                d = json.loads(r.get("data","{}"))
                d["found_at"] = r.get("found_at","")
                d["db_recommendation"] = r.get("recommendation","")
                leads.append(d)
            except:
                pass

        # Agent stats
        def agent_stats(agent_name: str) -> dict:
            agent_leads = [l for l in leads if l.get("agent") == agent_name]
            if not agent_leads:
                return {"count": 0, "avg_roi": 0, "buy_rate": 0, "ws_count": 0, "oa_count": 0, "top_leads": []}

            rois = []
            for l in agent_leads:
                try:
                    roi = float(str(l.get("roi","0")).replace("%","").strip())
                    rois.append(roi)
                except:
                    rois.append(0)

            buy_count = sum(1 for l in agent_leads if l.get("recommendation") == "BUY")
            ws_count  = sum(1 for l in agent_leads if l.get("type") == "wholesale")
            oa_count  = sum(1 for l in agent_leads if l.get("type") == "oa")
            avg_roi   = round(sum(rois) / len(rois), 1) if rois else 0
            buy_rate  = round((buy_count / len(agent_leads)) * 100) if agent_leads else 0

            # Top 3 leads by ROI
            sorted_leads = sorted(agent_leads, key=lambda x: float(str(x.get("roi","0")).replace("%","") or 0), reverse=True)
            top_leads = [{"name": l.get("name","")[:40], "roi": l.get("roi",""), "type": l.get("type",""), "rec": l.get("recommendation","")} for l in sorted_leads[:3]]

            return {
                "count":     len(agent_leads),
                "avg_roi":   avg_roi,
                "buy_count": buy_count,
                "buy_rate":  buy_rate,
                "ws_count":  ws_count,
                "oa_count":  oa_count,
                "top_leads": top_leads,
            }

        ian_stats  = agent_stats("Agent Ian")
        ivan_stats = agent_stats("Agent Ivan")

        # Overall platform stats
        total_leads = len(leads)
        buy_leads   = sum(1 for l in leads if l.get("recommendation") == "BUY")
        all_rois    = []
        for l in leads:
            try: all_rois.append(float(str(l.get("roi","0")).replace("%","") or 0))
            except: pass
        avg_roi_all = round(sum(all_rois) / len(all_rois), 1) if all_rois else 0

        # Winner
        winner = "Agent Ian" if ian_stats["avg_roi"] > ivan_stats["avg_roi"] else "Agent Ivan"
        if ian_stats["avg_roi"] == ivan_stats["avg_roi"]:
            winner = "Tied"

        return {
            "agent_ian":    ian_stats,
            "agent_ivan":   ivan_stats,
            "winner":       winner,
            "total_leads":  total_leads,
            "buy_leads":    buy_leads,
            "avg_roi":      avg_roi_all,
            "timestamp":    datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Keepa Integration ─────────────────────────────────────────────────────────

from keepa_agent import verify_leads_batch_keepa, get_token_usage, keepa_available

@app.get("/keepa/status")
async def keepa_status(secret: str = ""):
    """Check Keepa API token status."""
    if secret != os.getenv("ADMIN_SECRET", "arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return get_token_usage()

@app.post("/keepa/verify/{lead_id}")
async def verify_single_lead(lead_id: str, user=Depends(get_current_user)):
    """Verify a single lead with Keepa on demand."""
    try:
        profile = await get_user_profile(user.id)
        tier    = profile.get("tier","starter") if profile else "starter"
        if tier not in ["pro","agency","custom"]:
            raise HTTPException(status_code=403, detail="Keepa verification available on Pro and Agency plans")

        # Get lead from database
        result = supabase_admin.table("leads").select("*").eq("id", lead_id).eq("user_id", str(user.id)).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Lead not found")

        lead = json.loads(result.data[0].get("data","{}"))
        verified_lead = verify_leads_batch_keepa([lead], "US", delay=0)

        if verified_lead:
            # Update in database
            supabase_admin.table("leads").update({
                "data":       json.dumps(verified_lead[0]),
                "updated_at": datetime.now().isoformat()
            }).eq("id", lead_id).execute()

        return {"lead": verified_lead[0] if verified_lead else lead}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── Public Status Endpoint ────────────────────────────────────────────────────

@app.get("/status")
async def public_status():
    """Public status endpoint for status.getarbtrade.com"""
    try:
        # Check database
        db_ok = False
        lead_count = 0
        try:
            result = supabase_admin.table("profiles").select("id").limit(1).execute()
            db_ok = True
            leads = supabase_admin.table("leads").select("id").limit(1).execute()
            lead_count = 1 if leads.data else 0
        except:
            pass

        return {
            "status":          "operational" if db_ok else "degraded",
            "api":             "operational",
            "database":        "operational" if db_ok else "degraded",
            "agents":          "operational",
            "email":           "operational",
            "billing":         "operational",
            "keepa":           "operational" if keepa_available() else "not_configured",
            "timestamp":       datetime.now().isoformat(),
            "version":         "2.0.0"
        }
    except Exception as e:
        return {
            "status":    "degraded",
            "error":     str(e),
            "timestamp": datetime.now().isoformat()
        }

# ── Owner Settings & Control Panel ───────────────────────────────────────────

class OwnerSettings(BaseModel):
    custom_leads_per_cycle: int = None
    custom_scan_interval:   int = None
    min_roi_filter:         int = None
    blacklist_asins:        list = []
    blacklist_brands:       list = []
    priority_categories:    list = []
    auto_approve_threshold: int = None

@app.get("/owner/settings")
async def get_owner_settings(secret: str = ""):
    """Get current owner settings."""
    if secret != os.getenv("ADMIN_SECRET","arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        result = supabase_admin.table("profiles").select("*").eq("email", OWNER_EMAIL).execute()
        if not result.data:
            return {"settings": {}}
        profile = result.data[0]
        criteria = profile.get("criteria") or {}
        if isinstance(criteria, str):
            try: criteria = json.loads(criteria)
            except: criteria = {}
        owner_cfg = criteria.get("owner_config", {})
        return {
            "settings": {
                "custom_leads_per_cycle": owner_cfg.get("custom_leads_per_cycle", 12),
                "custom_scan_interval":   owner_cfg.get("custom_scan_interval", 6),
                "min_roi_filter":         owner_cfg.get("min_roi_filter", 0),
                "blacklist_asins":        owner_cfg.get("blacklist_asins", []),
                "blacklist_brands":       owner_cfg.get("blacklist_brands", []),
                "priority_categories":    owner_cfg.get("priority_categories", []),
                "auto_approve_threshold": owner_cfg.get("auto_approve_threshold", None),
            },
            "tier_default": 12,
            "current_api_calls": _api_call_count.get("count", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/owner/settings")
async def update_owner_settings(settings: OwnerSettings, secret: str = ""):
    """Update owner settings — custom leads, filters, blacklists."""
    if secret != os.getenv("ADMIN_SECRET","arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        result = supabase_admin.table("profiles").select("*").eq("email", OWNER_EMAIL).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Owner profile not found")

        profile  = result.data[0]
        criteria = profile.get("criteria") or {}
        if isinstance(criteria, str):
            try: criteria = json.loads(criteria)
            except: criteria = {}

        # Update owner config
        owner_cfg = {
            "custom_leads_per_cycle": settings.custom_leads_per_cycle or 12,
            "custom_scan_interval":   settings.custom_scan_interval or 6,
            "min_roi_filter":         settings.min_roi_filter or 0,
            "blacklist_asins":        settings.blacklist_asins or [],
            "blacklist_brands":       settings.blacklist_brands or [],
            "priority_categories":    settings.priority_categories or [],
            "auto_approve_threshold": settings.auto_approve_threshold,
        }
        criteria["owner_config"] = owner_cfg

        supabase_admin.table("profiles").update({
            "criteria": json.dumps(criteria)
        }).eq("email", OWNER_EMAIL).execute()

        log.info("Owner settings updated: " + str(owner_cfg))
        return {"success": True, "settings": owner_cfg}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/owner/scan-custom")
async def owner_custom_scan(secret: str = "", leads: int = 20):
    """Run a custom scan with specified lead count — owner only."""
    if secret != os.getenv("ADMIN_SECRET","arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        if not check_api_rate_limit():
            return {"error": "API rate limit reached", "calls_used": _api_call_count.get("count",0)}
        result   = supabase_admin.table("profiles").select("*").eq("email", OWNER_EMAIL).execute()
        profile  = result.data[0] if result.data else {}
        criteria = profile.get("criteria") or {}
        if isinstance(criteria, str):
            try: criteria = json.loads(criteria)
            except: criteria = {}
        user_id  = profile.get("id","")
        max_l    = min(leads, 50)  # Cap at 50 per scan for cost control
        results  = run_twin_agents(user_id, criteria, anthropic_client, max_l)
        saved    = 0
        for lead in results:
            try:
                asin = safe_asin(lead.get("asin",""))
                supabase_admin.table("leads").insert({
                    "user_id":        user_id,
                    "name":           (lead.get("name","")[:200]),
                    "asin":           asin,
                    "data":           json.dumps(lead),
                    "recommendation": lead.get("recommendation","WATCH"),
                    "roi":            safe_roi(lead.get("roi",0)),
                    "type":           lead.get("type","wholesale"),
                    "source":         (lead.get("source","")[:100]),
                    "found_at":       datetime.now().isoformat(),
                    "verified":       lead.get("verified", False),
                }).execute()
                saved += 1
            except Exception as ex:
                log.error("Owner custom scan save error: " + str(ex))
        return {"success": True, "requested": leads, "found": len(results), "saved": saved}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/owner/reset-api-counter")
async def reset_api_counter(secret: str = ""):
    """Reset the API call rate limiter — owner only."""
    if secret != os.getenv("ADMIN_SECRET","arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    _api_call_count["count"] = 0
    _api_call_count["reset_time"] = 0
    return {"success": True, "message": "API counter reset"}

@app.delete("/owner/leads/clear-old")
async def clear_old_leads(secret: str = "", days: int = 90):
    """Clear leads older than X days — owner only."""
    if secret != os.getenv("ADMIN_SECRET","arbtrade-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        result = supabase_admin.table("leads").delete().lt("found_at", cutoff).execute()
        return {"success": True, "message": f"Cleared leads older than {days} days"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
