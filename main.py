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
from fastapi.responses import JSONResponse
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
ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Stripe price IDs — update these after creating products in Stripe dashboard
STRIPE_PRICES = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", "price_starter"),
    "pro":     os.getenv("STRIPE_PRICE_PRO",     "price_pro"),
    "agency":  os.getenv("STRIPE_PRICE_AGENCY",  "price_agency"),
}

# Usage limits per tier
TIER_LIMITS = {
    "starter": {"manual_scans_per_day": 1,  "max_leads": 20,  "categories": 2},
    "pro":     {"manual_scans_per_day": 3,  "max_leads": 50,  "categories": 5},
    "agency":  {"manual_scans_per_day": 10, "max_leads": 100, "categories": 999},
    "trial":   {"manual_scans_per_day": 1,  "max_leads": 10,  "categories": 1},
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
        user = supabase.auth.get_user(token)
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_user_profile(user_id: str):
    try:
        result = supabase_admin.table("profiles").select("*").eq("id", user_id).single().execute()
        return result.data
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

def run_agent_for_user(user_id: str, criteria: dict) -> list:
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
        resp = ai_client.messages.create(
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

async def save_leads_for_user(user_id: str, leads: list):
    """Save leads to Supabase, keeping 48h window."""
    cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
    try:
        # Delete old leads
        supabase_admin.table("leads").delete().eq("user_id", user_id).lt("found_at", cutoff).execute()
        # Insert new leads
        for lead in leads:
            supabase_admin.table("leads").insert({
                "user_id":        user_id,
                "name":           lead.get("name",""),
                "asin":           lead.get("asin",""),
                "data":           json.dumps(lead),
                "recommendation": lead.get("recommendation",""),
                "roi":            safe_roi(lead.get("roi",0)),
                "type":           lead.get("type","wholesale"),
                "found_at":       lead.get("found_at", datetime.now().isoformat()),
            }).execute()
    except Exception as e:
        log.error(f"Failed to save leads for {user_id}: {e}")

# ── Scheduled global scan ────────────────────────────────────────────────────

def run_scheduled_scan():
    """Runs every 4 hours for ALL active subscribers."""
    log.info("Running scheduled scan for all users...")
    try:
        users = supabase_admin.table("profiles").select("id,criteria,tier").neq("tier","cancelled").execute()
        for profile in (users.data or []):
            user_id = profile["id"]
            criteria = profile.get("criteria") or {}
            if isinstance(criteria, str):
                criteria = json.loads(criteria)
            if not criteria:
                criteria = {"wholesale":{"categories":["Health & Household"],"max_bsr":50000,"max_sellers":8,"min_monthly_sales":300,"min_roi_percent":30},"online_arbitrage":{"categories":["Health & Household"],"max_bsr":75000,"max_sellers":12,"min_monthly_sales":200,"min_roi_percent":35,"min_price_spread":8,"max_buy_cost":35}}
            leads = run_agent_for_user(user_id, criteria)
            if leads:
                import asyncio
                asyncio.run(save_leads_for_user(user_id, leads))
            time.sleep(3)
        log.info("Scheduled scan complete")
    except Exception as e:
        log.error(f"Scheduled scan error: {e}")

def start_scheduler():
    schedule.every(4).hours.do(run_scheduled_scan)
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in background thread
scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
scheduler_thread.start()

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
        return {"user": result.user, "session": result.session, "access_token": result.session.access_token}
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
    max_leads = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])["max_leads"]
    cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
    try:
        query = supabase_admin.table("leads").select("*").eq("user_id", user.id).gte("found_at", cutoff).order("roi", desc=True).limit(max_leads)
        if filter == "wholesale": query = query.eq("type","wholesale")
        elif filter == "oa": query = query.eq("type","oa")
        elif filter == "BUY": query = query.eq("recommendation","BUY")
        result = query.execute()
        leads = [json.loads(r["data"]) for r in (result.data or [])]
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
            "max_leads": max_leads
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
        leads = run_agent_for_user(user.id, criteria)
        if leads: await save_leads_for_user(user.id, leads)

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
            supabase_admin.table("profiles").update({
                "tier": tier,
                "stripe_customer_id": customer_id,
                "subscribed_at": datetime.now().isoformat()
            }).eq("id", user_id).execute()
            log.info(f"User {user_id} upgraded to {tier}")

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
        result = supabase_admin.table("scan_usage").select("count").eq("user_id", user.id).eq("date", today).execute()
        scans_today = result.data[0]["count"] if result.data else 0
    except: scans_today = 0
    return {
        "tier": tier,
        "scans_today": scans_today,
        "scans_limit": limits["manual_scans_per_day"],
        "max_leads": limits["max_leads"],
        "categories_limit": limits["categories"]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
