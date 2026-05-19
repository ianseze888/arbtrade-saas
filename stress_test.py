#!/usr/bin/env python3
"""
ARBTRADE Platform Stress Test
--------------------------------
Simulates multiple concurrent users hitting the platform.
Tests: API response times, database queries, agent performance.
Run locally: python3 stress_test.py
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime

API = "https://arbtrade-saas-production.up.railway.app"
ADMIN_SECRET = "arbtrade-admin-2026"

async def test_endpoint(session, url, name, method="GET", data=None):
    """Test a single endpoint and return response time."""
    start = time.time()
    try:
        if method == "GET":
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                ms = int((time.time() - start) * 1000)
                return {"name": name, "status": resp.status, "ms": ms, "ok": resp.status < 400}
        else:
            async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                ms = int((time.time() - start) * 1000)
                return {"name": name, "status": resp.status, "ms": ms, "ok": resp.status < 400}
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        return {"name": name, "status": 0, "ms": ms, "ok": False, "error": str(e)}

async def run_stress_test(concurrent_users: int = 10):
    """Simulate concurrent users hitting the platform."""
    print("\n🔥 ARBTRADE STRESS TEST")
    print("=" * 50)
    print(f"Simulating {concurrent_users} concurrent users")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}\n")

    # Public endpoints to test
    endpoints = [
        (f"{API}/health", "Health Check"),
        (f"{API}/admin/stats?secret={ADMIN_SECRET}", "Admin Stats"),
        (f"{API}/health/full?secret={ADMIN_SECRET}", "Full Health Check"),
        (f"{API}/markets", "Markets List"),
        (f"{API}/owner/logs?secret={ADMIN_SECRET}", "Owner Logs"),
    ]

    all_results = []

    async with aiohttp.ClientSession() as session:
        # Test 1: Sequential baseline
        print("📊 Test 1: Sequential baseline")
        for url, name in endpoints:
            result = await test_endpoint(session, url, name)
            status = "✅" if result["ok"] else "❌"
            print(f"  {status} {name}: {result['ms']}ms (HTTP {result['status']})")
            all_results.append(result)

        print()

        # Test 2: Concurrent load
        print(f"📊 Test 2: {concurrent_users} concurrent requests to health endpoint")
        tasks = [test_endpoint(session, f"{API}/health", f"User {i+1}") for i in range(concurrent_users)]
        start = time.time()
        results = await asyncio.gather(*tasks)
        total_ms = int((time.time() - start) * 1000)
        success = sum(1 for r in results if r["ok"])
        avg_ms  = sum(r["ms"] for r in results) // len(results)
        max_ms  = max(r["ms"] for r in results)
        print(f"  ✅ {success}/{concurrent_users} successful")
        print(f"  ⏱  Average: {avg_ms}ms | Max: {max_ms}ms | Total wall time: {total_ms}ms")

        print()

        # Test 3: Rapid fire
        print("📊 Test 3: 20 rapid-fire requests")
        tasks2 = [test_endpoint(session, f"{API}/health", f"Req {i+1}") for i in range(20)]
        results2 = await asyncio.gather(*tasks2)
        success2 = sum(1 for r in results2 if r["ok"])
        avg_ms2  = sum(r["ms"] for r in results2) // len(results2)
        print(f"  ✅ {success2}/20 successful | Average: {avg_ms2}ms")

    print()
    print("=" * 50)
    print("📋 STRESS TEST SUMMARY")
    print("=" * 50)

    # Overall results
    total    = len(all_results)
    success  = sum(1 for r in all_results if r["ok"])
    avg      = sum(r["ms"] for r in all_results) // max(total,1)
    slow     = [r for r in all_results if r["ms"] > 2000]

    print(f"✅ Success rate: {success}/{total} ({int(success/max(total,1)*100)}%)")
    print(f"⏱  Average response: {avg}ms")
    if slow:
        print(f"⚠  Slow endpoints (>2s): {len(slow)}")
        for s in slow:
            print(f"   - {s['name']}: {s['ms']}ms")

    print()
    if success == total and avg < 1000:
        print("🟢 PLATFORM STATUS: HEALTHY — Ready for launch!")
    elif success >= total * 0.9 and avg < 2000:
        print("🟡 PLATFORM STATUS: ACCEPTABLE — Minor issues to address")
    else:
        print("🔴 PLATFORM STATUS: NEEDS ATTENTION before launch")

    print("=" * 50)

if __name__ == "__main__":
    import sys
    users = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(run_stress_test(users))
