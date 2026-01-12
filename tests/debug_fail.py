#!/usr/bin/env python3
import asyncio
import json
import os
import httpx
import sys

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")

async def test_query(question):
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
                    "thread_id": "debug-thread-456",
                }
            )
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Success Field: {data.get('success')}")
                print(f"Error Field: {data.get('error')}")
                if data.get('query'):
                    print("Generated Query:")
                    print(json.dumps(data.get('query'), indent=2))
                if data.get('results'):
                    print(f"Results Count: {len(data.get('results', {}).get('data', []))}")
                print("-" * 50)
            else:
                print(f"❌ HTTP FAILED: {response.text}")
                
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Give me the top 3 customers with highest sales"
    asyncio.run(test_query(q))
