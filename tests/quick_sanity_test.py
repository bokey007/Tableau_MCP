#!/usr/bin/env python3
"""
Quick sanity test with just 3 questions to validate the test suite works.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict
import httpx
from openai import AsyncOpenAI
import os

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JUDGE_MODEL = "gpt-5.2"

# Just 3 test questions
TEST_QUESTIONS = [
    ("data_query", "Who are the top 5 customers?"),
    ("data_query", "Sales by region"),
    ("chat", "Hello, what can you do?"),
]


async def run_query(question: str) -> Dict[str, Any]:
    """Send a query to the backend API."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        start = time.monotonic()
        response = await client.post(
            f"{BACKEND_URL}/query",
            json={
                "question": question,
                "username": "sanity_test",
                "thread_id": str(uuid.uuid4()),
            }
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            data["response_time_ms"] = elapsed_ms
            return data
        else:
            return {"success": False, "error": f"HTTP {response.status_code}", "response_time_ms": elapsed_ms}


async def evaluate_with_judge(question: str, category: str, response: Dict) -> Dict:
    """Use GPT-4o to comprehensively evaluate the response."""
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    results_data = response.get('results', {}).get('data', [])[:5] if response.get('results') else []
    
    prompt = f"""You are an expert QA evaluator for an AI-powered Tableau data analysis agent.
Evaluate the agent's complete response pipeline.

═══════════════════════════════════════════════════════════════
ORIGINAL USER QUESTION
═══════════════════════════════════════════════════════════════
Category: {category}
Question: "{question}"

═══════════════════════════════════════════════════════════════
AGENT RESPONSE
═══════════════════════════════════════════════════════════════

1. SUCCESS: {response.get('success', False)}
2. ERROR: {response.get('error', 'None')}

3. GENERATED QUERY:
{json.dumps(response.get('query'), indent=2)[:500] if response.get('query') else 'None'}

4. EXTRACTED DATA ({len(results_data)} rows):
{json.dumps(results_data, indent=2)[:400] if results_data else 'None'}

5. LLM ANALYSIS:
{(response.get('analysis') or 'None')[:500]}

═══════════════════════════════════════════════════════════════
EVALUATION CRITERIA
═══════════════════════════════════════════════════════════════

For DATA queries evaluate:
1. Query Correctness: Right fields? Correct aggregation (SUM/COUNT/AVG)? Proper filters?
2. Data Relevance: Does data answer the question? Correct row count?
3. Analysis Quality: Does response answer the question accurately?

For CHAT queries evaluate:
- Did it respond conversationally without triggering data extraction?
- Was the response helpful and appropriate?

Score 8-10: Excellent - everything works correctly
Score 5-7: Acceptable - minor issues
Score 1-4: Poor - significant errors

Respond with JSON only:
{{"score": <1-10>, "reasoning": "<2-3 sentences explaining evaluation>"}}
"""
    
    try:
        resp = await client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=300,
        )
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1].replace("json", "").strip()
        return json.loads(content)
    except Exception as e:
        return {"score": 0, "reasoning": f"Evaluation error: {e}"}


async def main():
    print("=" * 60)
    print("🧪 QUICK SANITY TEST - 3 Questions")
    print("=" * 60)
    print(f"Backend: {BACKEND_URL}")
    print(f"Judge: {JUDGE_MODEL}")
    print()
    
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY not set")
        return
    
    results = []
    
    for category, question in TEST_QUESTIONS:
        print(f"\n📌 Testing: '{question}'")
        print(f"   Category: {category}")
        
        # Run query
        response = await run_query(question)
        print(f"   ✓ Response time: {response.get('response_time_ms', 0):.0f}ms")
        print(f"   ✓ Success: {response.get('success')}")
        
        if response.get('success'):
            print(f"   ✓ Results: {len(response.get('results', {}).get('data', [])) if response.get('results') else 0} rows")
        
        # Evaluate
        evaluation = await evaluate_with_judge(question, category, response)
        score = evaluation.get('score', 0)
        reasoning = evaluation.get('reasoning', 'No reasoning')
        
        status = "✅" if score >= 7 else "⚠️" if score >= 5 else "❌"
        print(f"   {status} Judge Score: {score}/10")
        print(f"   📝 Reasoning: {reasoning[:100]}...")
        
        results.append({
            "question": question,
            "category": category,
            "success": response.get('success'),
            "score": score,
            "reasoning": reasoning,
        })
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    avg_score = sum(r['score'] for r in results) / len(results)
    passed = sum(1 for r in results if r['score'] >= 7)
    print(f"✅ Passed: {passed}/{len(results)}")
    print(f"🎯 Average Score: {avg_score:.1f}/10")
    
    if avg_score >= 7:
        print("\n✅ Sanity test PASSED! Ready for full regression suite.")
    else:
        print("\n⚠️ Issues detected. Review before running full suite.")


if __name__ == "__main__":
    asyncio.run(main())
