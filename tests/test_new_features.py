#!/usr/bin/env python3
"""
Test suite for new Dashboard Agent features:
- Comparison Queries
- Anomaly Detection
- Storytelling
- Query History & Favorites API
- SSE Streaming
"""

import asyncio
import json
import httpx
import sys
from typing import Dict, Any

BASE_URL = "http://localhost:8000/api/v1"

# Test cases organized by feature
TEST_CASES = {
    "comparison": [
        {"question": "Compare Q1 vs Q2 sales", "expected_intent": "comparison"},
        {"question": "How does East region compare to West?", "expected_intent": "comparison"},
        {"question": "Year over year growth", "expected_intent": "comparison"},
    ],
    "anomaly": [
        {"question": "What's unusual in this data?", "expected_intent": "anomaly"},
        {"question": "Find any anomalies or outliers", "expected_intent": "anomaly"},
        {"question": "Are there any red flags?", "expected_intent": "anomaly"},
    ],
    "storytelling": [
        {"question": "Give me an executive summary", "expected_intent": "storytelling"},
        {"question": "Summarize this dashboard", "expected_intent": "storytelling"},
        {"question": "Tell me the story of this data", "expected_intent": "storytelling"},
    ],
    "data_query": [
        {"question": "Top 5 products by sales", "expected_intent": "data_query"},
        {"question": "Total revenue by region", "expected_intent": "data_query"},
    ],
}


async def test_intent_classification():
    """Test that new intents are correctly classified."""
    print("\n" + "="*60)
    print("TEST: Intent Classification for New Query Types")
    print("="*60)
    
    results = {"passed": 0, "failed": 0}
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for category, tests in TEST_CASES.items():
            print(f"\n--- {category.upper()} ---")
            
            for test in tests:
                question = test["question"]
                expected = test["expected_intent"]
                
                try:
                    response = await client.post(
                        f"{BASE_URL}/dashboard/query",
                        json={
                            "question": question,
                            "filters": [{"field": "Region", "value": "West"}],
                        }
                    )
                    
                    data = response.json()
                    actual_intent = data.get("intent", "unknown")
                    
                    if actual_intent == expected:
                        print(f"  ✅ '{question[:40]}...' → {actual_intent}")
                        results["passed"] += 1
                    else:
                        print(f"  ❌ '{question[:40]}...' → Expected {expected}, got {actual_intent}")
                        results["failed"] += 1
                        
                except Exception as e:
                    print(f"  ❌ Error: {e}")
                    results["failed"] += 1
    
    return results


async def test_history_api():
    """Test the query history API endpoints."""
    print("\n" + "="*60)
    print("TEST: Query History & Favorites API")
    print("="*60)
    
    results = {"passed": 0, "failed": 0}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test GET /history
        try:
            response = await client.get(f"{BASE_URL}/dashboard/history")
            data = response.json()
            
            if response.status_code == 200 and "items" in data:
                print("  ✅ GET /history - Endpoint working")
                results["passed"] += 1
            else:
                print(f"  ❌ GET /history - Unexpected response: {data}")
                results["failed"] += 1
        except Exception as e:
            print(f"  ❌ GET /history - Error: {e}")
            results["failed"] += 1
        
        # Test GET /favorites
        try:
            response = await client.get(f"{BASE_URL}/dashboard/favorites")
            data = response.json()
            
            if response.status_code == 200 and "items" in data:
                print("  ✅ GET /favorites - Endpoint working")
                results["passed"] += 1
            else:
                print(f"  ❌ GET /favorites - Unexpected response: {data}")
                results["failed"] += 1
        except Exception as e:
            print(f"  ❌ GET /favorites - Error: {e}")
            results["failed"] += 1
        
        # Test POST /favorites
        try:
            response = await client.post(
                f"{BASE_URL}/dashboard/favorites",
                json={"query_id": "test-123", "is_favorite": True, "label": "Test favorite"}
            )
            data = response.json()
            
            if response.status_code == 200 and data.get("success"):
                print("  ✅ POST /favorites - Toggle working")
                results["passed"] += 1
            else:
                print(f"  ❌ POST /favorites - Unexpected response: {data}")
                results["failed"] += 1
        except Exception as e:
            print(f"  ❌ POST /favorites - Error: {e}")
            results["failed"] += 1
    
    return results


async def test_sse_streaming():
    """Test the SSE streaming endpoint."""
    print("\n" + "="*60)
    print("TEST: SSE Streaming Endpoint")
    print("="*60)
    
    results = {"passed": 0, "failed": 0}
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            # SSE streaming test
            events_received = []
            
            async with client.stream(
                "POST",
                f"{BASE_URL}/dashboard/query/stream",
                json={"question": "Top 3 products", "filters": []},
                headers={"Accept": "text/event-stream"}
            ) as response:
                
                if response.status_code != 200:
                    print(f"  ❌ SSE endpoint returned {response.status_code}")
                    results["failed"] += 1
                    return results
                
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        if event.startswith("data: "):
                            try:
                                data = json.loads(event[6:])
                                events_received.append(data.get("event"))
                                print(f"    📡 Event: {data.get('event')} - {data.get('message', '')[:50]}")
                            except json.JSONDecodeError:
                                pass
            
            # Check we received expected events
            if "thinking" in events_received:
                print("  ✅ Received 'thinking' event")
                results["passed"] += 1
            else:
                print("  ❌ Missing 'thinking' event")
                results["failed"] += 1
            
            if "complete" in events_received or "error" in events_received:
                print("  ✅ Received final event (complete/error)")
                results["passed"] += 1
            else:
                print("  ❌ Missing final event")
                results["failed"] += 1
                
        except Exception as e:
            print(f"  ❌ SSE test failed: {e}")
            results["failed"] += 1
    
    return results


async def test_capabilities_endpoint():
    """Test that capabilities include new features."""
    print("\n" + "="*60)
    print("TEST: Capabilities Endpoint")
    print("="*60)
    
    results = {"passed": 0, "failed": 0}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{BASE_URL}/dashboard/capabilities")
            data = response.json()
            
            intents = [i["name"] for i in data.get("intents", [])]
            
            # Check for new intents
            for expected in ["comparison", "anomaly", "storytelling"]:
                if expected in intents:
                    print(f"  ✅ Intent '{expected}' in capabilities")
                    results["passed"] += 1
                else:
                    print(f"  ❌ Intent '{expected}' missing from capabilities")
                    results["failed"] += 1
            
            # Check features
            features = data.get("features", [])
            if any("history" in f.lower() for f in features):
                print("  ✅ Query history in features")
                results["passed"] += 1
            else:
                print("  ❌ Query history not in features")
                results["failed"] += 1
                
        except Exception as e:
            print(f"  ❌ Capabilities test failed: {e}")
            results["failed"] += 1
    
    return results


async def main():
    """Run all tests."""
    print("\n" + "#"*60)
    print("# DASHBOARD AGENT - NEW FEATURES TEST SUITE")
    print("#"*60)
    
    all_results = {"passed": 0, "failed": 0}
    
    # Run test suites
    for test_fn in [
        test_capabilities_endpoint,
        test_history_api,
        test_intent_classification,
        test_sse_streaming,
    ]:
        try:
            results = await test_fn()
            all_results["passed"] += results["passed"]
            all_results["failed"] += results["failed"]
        except Exception as e:
            print(f"\n❌ Test suite failed: {e}")
            all_results["failed"] += 1
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    total = all_results["passed"] + all_results["failed"]
    print(f"  Passed: {all_results['passed']}/{total}")
    print(f"  Failed: {all_results['failed']}/{total}")
    
    if all_results["failed"] == 0:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {all_results['failed']} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
