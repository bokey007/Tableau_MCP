#!/usr/bin/env python3
"""
Quick debug script to test a single query and see full response.
"""

import asyncio
import json
import os
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")


async def test_single_query():
    """Test a single query and print full response."""
    question = "Who are the top 5 customers?"
    
    print(f"Testing: '{question}'")
    print(f"Backend: {BACKEND_URL}")
    print("-" * 50)
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/query",
                json={
                    "question": question,
                    "username": "debug_test",
                    "thread_id": "debug-thread-123",
                }
            )
            
            print(f"Status: {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            print()
            
            if response.status_code == 200:
                data = response.json()
                print("✅ SUCCESS")
                print()
                print("=== Full Response ===")
                print(json.dumps(data, indent=2, default=str)[:2000])
                print()
                print("=== Key Fields ===")
                print(f"Success: {data.get('success')}")
                print(f"Analysis (first 200 chars): {data.get('analysis', 'None')[:200]}")
                print(f"Query: {json.dumps(data.get('query'), indent=2)[:500] if data.get('query') else 'None'}")
                print(f"Results count: {len(data.get('results', {}).get('data', [])) if data.get('results') else 0}")
                print(f"Viz: {data.get('visualization')}")
            else:
                print(f"❌ FAILED: {response.text}")
                
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_single_query())
