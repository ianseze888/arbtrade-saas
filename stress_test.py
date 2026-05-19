#!/usr/bin/env python3
"""
ARBTRADE Platform Stress Test
--------------------------------
Uses requests library (more reliable on Mac than aiohttp)
Run: python3 stress_test.py
"""

import concurrent.futures
import requests
import time
from datetime import datetime

API           = "https://arbtrade-saas-production.up.railway.app"
ADMIN_SECRET  = "arbtrade-admin-2026"

# Disable SSL warnings for testing
requests.packages.urllib3.disable_warnings()

def test_endpoint(args):
    """Test a single endpoint."""
    url, name = args
    start = time.time()
    try:
        resp = requests.get(url, timeout=15, verify=True)
        ms   = int((time.time() - start) * 1000)
        return {"name": name, "status": resp.status_code, "ms": ms, "ok": resp.status_code < 400}
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        return {"name": name, "status": 0, "ms": ms, "ok": False, "error": str(e)[:80]}

def run_stress_test(concurrent_users: int = 10):
    print("\n🔥 ARBTRADE STRESS TEST")
    print("=" * 55)
    print("Target:  " + API)
    print("Users:   " + str(concurrent_users))
    print("Time:    " + datetime.now().strftime('%H:%M:%S'))
    print()

    endpoints = [
        (API + "/health",                                 "Health Check"),
        (API + "/admin/stats?secret=" + ADMIN_SECRET,    "Admin Stats"),
        (API + "/markets",                                "Markets List"),
        (API + "/owner/logs?secret=" + ADMIN_SECRET,     "Owner Logs"),
        (API + "/owner/raw-leads?secret=" + ADMIN_SECRET,"Raw Leads"),
    ]

    # Test 1: Sequential baseline
    print("📊 Test 1: Sequential baseline")
    baseline = []
    for url, name in endpoints:
        r = test_endpoint((url, name))
        icon = "✅" if r["ok"] else "❌"
        extra = " — " + r.get("error","") if not r["ok"] else ""
        print("  " + icon + " " + name + ": " + str(r["ms"]) + "ms" + extra)
        baseline.append(r)
    print()

    # Test 2: Concurrent load
    print("📊 Test 2: " + str(concurrent_users) + " concurrent users")
    health_tasks = [(API + "/health", "User " + str(i+1)) for i in range(concurrent_users)]
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as ex:
        results = list(ex.map(test_endpoint, health_tasks))
    wall = int((time.time() - start) * 1000)
    ok   = sum(1 for r in results if r["ok"])
    avg  = sum(r["ms"] for r in results) // len(results)
    peak = max(r["ms"] for r in results)
    print("  " + str(ok) + "/" + str(concurrent_users) + " successful")
    print("  Avg: " + str(avg) + "ms | Peak: " + str(peak) + "ms | Wall time: " + str(wall) + "ms")
    print()

    # Test 3: 30-request burst
    print("📊 Test 3: 30-request burst")
    burst_tasks = [(API + "/health", "Burst " + str(i+1)) for i in range(30)]
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        results2 = list(ex.map(test_endpoint, burst_tasks))
    wall2 = int((time.time() - start) * 1000)
    ok2   = sum(1 for r in results2 if r["ok"])
    avg2  = sum(r["ms"] for r in results2) // len(results2)
    print("  " + str(ok2) + "/30 successful | Avg: " + str(avg2) + "ms | Wall: " + str(wall2) + "ms")
    print()

    # Test 4: Mixed endpoint load
    print("📊 Test 4: Mixed endpoint load (" + str(len(endpoints)*3) + " requests)")
    mixed = []
    for _ in range(3):
        mixed.extend(endpoints)
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        results3 = list(ex.map(test_endpoint, mixed))
    wall3 = int((time.time() - start) * 1000)
    ok3   = sum(1 for r in results3 if r["ok"])
    avg3  = sum(r["ms"] for r in results3) // len(results3)
    print("  " + str(ok3) + "/" + str(len(results3)) + " successful | Avg: " + str(avg3) + "ms | Wall: " + str(wall3) + "ms")

    # Summary
    print()
    print("=" * 55)
    print("📋 STRESS TEST RESULTS")
    print("=" * 55)
    total   = len(baseline)
    success = sum(1 for r in baseline if r["ok"])
    avg_all = sum(r["ms"] for r in baseline) // max(total, 1)

    print("Baseline success:   " + str(success) + "/" + str(total))
    print("Concurrent success: " + str(ok) + "/" + str(concurrent_users))
    print("Burst success:      " + str(ok2) + "/30")
    print("Avg response time:  " + str(avg_all) + "ms")
    print()

    if success == total and ok == concurrent_users and avg_all < 500:
        print("🟢 PLATFORM: EXCELLENT — Ready for 100+ subscribers!")
    elif success == total and ok >= concurrent_users * 0.9 and avg_all < 1000:
        print("🟢 PLATFORM: HEALTHY — Good to launch")
    elif success >= total * 0.8:
        print("🟡 PLATFORM: ACCEPTABLE — Monitor after launch")
    else:
        print("🔴 PLATFORM: CONNECTION ISSUE")
        print()
        print("Troubleshooting:")
        print("1. Check Railway is online: https://arbtrade-saas-production.up.railway.app/health")
        print("2. Try: curl https://arbtrade-saas-production.up.railway.app/health")
        print("3. Check if VPN is blocking Railway")
    print("=" * 55)

if __name__ == "__main__":
    import sys
    # First verify basic connectivity
    print("Checking connectivity...")
    try:
        r = requests.get(API + "/health", timeout=10)
        print("✅ Railway is reachable! Status: " + str(r.status_code))
        print()
        users = int(sys.argv[1]) if len(sys.argv) > 1 else 10
        run_stress_test(users)
    except Exception as e:
        print("❌ Cannot reach Railway: " + str(e))
        print()
        print("The platform itself may be fine — this could be:")
        print("• Your local network blocking Railway")
        print("• VPN interference")
        print("• DNS resolution issue")
        print()
        print("Verify in browser: https://arbtrade-saas-production.up.railway.app/health")
