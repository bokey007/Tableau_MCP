#!/usr/bin/env python3
"""
Two-Phase Regression Test Suite

Phase 1: Collect - Run all questions through the app and save responses to Excel
Phase 2: Evaluate - Use LLM judge to evaluate all responses from Excel

This approach is more reliable and allows for manual inspection of raw data.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List
import httpx
from openai import AsyncOpenAI
import os
import pandas as pd

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JUDGE_MODEL = "gpt-5.2"

# Test questions organized by category
TEST_QUESTIONS = [
    # TOP N QUERIES
    ("top_n", "Who are the top 5 customers?"),
    ("top_n", "Show me the top 5 customers by sales"),
    ("top_n", "What are the best 5 customers based on revenue?"),
    ("top_n", "Top ten customers"),
    ("top_n", "Give me the top 3 customers with highest sales"),
    ("top_n", "bottom 5 customers by sales"),
    ("top_n", "Which customers have the lowest sales?"),
    
    # AGGREGATION QUERIES
    ("aggregation", "What is the total sales?"),
    ("aggregation", "Show me total revenue"),
    ("aggregation", "Calculate the sum of all sales"),
    ("aggregation", "What's the average profit?"),
    ("aggregation", "Average order value"),
    ("aggregation", "How many orders do we have?"),
    ("aggregation", "Count of customers"),
    ("aggregation", "What's the maximum profit?"),
    ("aggregation", "Minimum sales amount"),
    
    # DIMENSION BREAKDOWN QUERIES
    ("dimension", "Sales by region"),
    ("dimension", "Show sales breakdown by region"),
    ("dimension", "Revenue by category"),
    ("dimension", "Profit by product category"),
    ("dimension", "Sales by state"),
    ("dimension", "Orders by segment"),
    ("dimension", "Sales by sub-category"),
    
    # TIME SERIES QUERIES
    ("timeseries", "Sales trend since 2020"),
    ("timeseries", "Monthly sales trend"),
    ("timeseries", "Show me sales by year"),
    ("timeseries", "Quarterly profit trend"),
    ("timeseries", "Sales trend for the last 12 months"),
    ("timeseries", "Year over year sales comparison"),
    ("timeseries", "How have sales changed over time?"),
    
    # FILTER QUERIES
    ("filter", "Sales in the West region"),
    ("filter", "Top 5 customers in East"),
    ("filter", "Products with sales greater than 10000"),
    ("filter", "Orders from 2024"),
    ("filter", "Technology category sales"),
    ("filter", "Furniture sales by region"),
    ("filter", "Customers with profit > 5000"),
    
    # COMPLEX QUERIES
    ("complex", "Top 5 products by profit in each region"),
    ("complex", "Compare sales between Technology and Furniture"),
    ("complex", "Which region has the highest profit margin?"),
    ("complex", "Sales and profit by category"),
    ("complex", "Customer count and total sales by segment"),
    ("complex", "Average discount by category"),
    
    # CHAT QUERIES
    ("chat", "Hello"),
    ("chat", "Hi there!"),
    ("chat", "What can you do?"),
    ("chat", "Help me understand your capabilities"),
    ("chat", "Thanks!"),
    ("chat", "How are you?"),
    ("chat", "Who made you?"),
    ("chat", "What data sources do you have access to?"),
    
    # EDGE CASES
    ("edge_case", "sales"),
    ("edge_case", "show me everything"),
    ("edge_case", "what's the story with our data?"),
    ("edge_case", "Analyze the performance"),
    ("edge_case", "Give me insights"),
]


async def run_query(question: str, thread_id: str) -> Dict[str, Any]:
    """Send a query to the backend API."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        start = time.monotonic()
        try:
            response = await client.post(
                f"{BACKEND_URL}/query",
                json={
                    "question": question,
                    "username": "regression_test",
                    "thread_id": thread_id,
                }
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                data["response_time_ms"] = elapsed_ms
                data["http_status"] = 200
                return data
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                    "response_time_ms": elapsed_ms,
                    "http_status": response.status_code,
                }
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "success": False,
                "error": str(e),
                "response_time_ms": elapsed_ms,
                "http_status": 0,
            }


async def phase1_collect():
    """Phase 1: Collect all responses into a DataFrame."""
    print("=" * 70)
    print("📊 PHASE 1: COLLECTING RESPONSES")
    print("=" * 70)
    print(f"Total questions: {len(TEST_QUESTIONS)}")
    print(f"Backend: {BACKEND_URL}")
    print()
    
    results = []
    thread_id = str(uuid.uuid4())
    
    for i, (category, question) in enumerate(TEST_QUESTIONS, 1):
        print(f"[{i}/{len(TEST_QUESTIONS)}] {category}: {question[:50]}...", end="", flush=True)
        
        # Reset thread for every question to ensure independent testing
        # Context accumulation in long threads can cause performance issues
        thread_id = str(uuid.uuid4())
        
        response = await run_query(question, thread_id)
        
        # Extract data safely
        results_data = []
        row_count = 0
        if response.get("results") and isinstance(response["results"], dict):
            results_data = response["results"].get("data", [])[:10]  # First 10 rows
            row_count = len(response["results"].get("data", []))
        
        result = {
            "id": i,
            "category": category,
            "question": question,
            "success": response.get("success", False),
            "http_status": response.get("http_status", 0),
            "response_time_ms": response.get("response_time_ms", 0),
            "error": response.get("error", ""),
            "analysis": (response.get("analysis") or "")[:1000],  # Truncate for Excel
            "generated_query": json.dumps(response.get("query", {}))[:1000],
            "row_count": row_count,
            "sample_data": json.dumps(results_data)[:2000],
            "visualization": json.dumps(response.get("visualization", {})),
            # Evaluation columns (to be filled in Phase 2)
            "judge_score": None,
            "judge_reasoning": None,
        }
        
        results.append(result)
        
        # Print status
        status = "✅" if response.get("success") else "❌"
        time_s = response.get("response_time_ms", 0) / 1000
        print(f" {status} ({time_s:.1f}s, {row_count} rows)")
        
        # Large delay between requests to avoid Tableau rate limits
        await asyncio.sleep(15)
        
        # Extra pause every 15 questions to let rate limits reset
        if i % 15 == 0 and i < len(TEST_QUESTIONS):
            print(f"\n⏸️  Pausing 2 minutes to reset rate limits ({i}/{len(TEST_QUESTIONS)} done)...\n")
            await asyncio.sleep(120)
    
    # Save to Excel
    df = pd.DataFrame(results)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_file = f"regression_data_{timestamp}.xlsx"
    df.to_excel(excel_file, index=False, engine='openpyxl')
    
    print()
    print("=" * 70)
    print(f"✅ Phase 1 Complete! Data saved to: {excel_file}")
    print(f"   Total: {len(results)} questions")
    print(f"   Success: {sum(1 for r in results if r['success'])}")
    print(f"   Failed: {sum(1 for r in results if not r['success'])}")
    print("=" * 70)
    
    return excel_file


async def phase2_evaluate(excel_file: str):
    """Phase 2: Evaluate all responses using LLM judge."""
    print()
    print("=" * 70)
    print("🔍 PHASE 2: EVALUATING RESPONSES")
    print("=" * 70)
    print(f"Reading from: {excel_file}")
    print(f"Judge model: {JUDGE_MODEL}")
    print()
    
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY not set, skipping evaluation")
        return
    
    # Read Excel
    df = pd.read_excel(excel_file, engine='openpyxl')
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    for idx, row in df.iterrows():
        print(f"[{idx+1}/{len(df)}] Evaluating: {row['question'][:40]}...", end="", flush=True)
        
        # Build evaluation prompt
        prompt = f"""Evaluate this AI agent response for a Tableau data query system.

Question: "{row['question']}"
Category: {row['category']}

Response:
- Success: {row['success']}
- Error: {row['error'] if pd.notna(row['error']) else 'None'}
- Response Time: {row['response_time_ms']:.0f}ms
- Row Count: {row['row_count']}

Generated Query:
{str(row['generated_query'])[:500] if pd.notna(row['generated_query']) else 'None'}

Analysis:
{str(row['analysis'])[:500] if pd.notna(row['analysis']) else 'None'}

Sample Data:
{str(row['sample_data'])[:500] if pd.notna(row['sample_data']) else 'None'}

Scoring (1-10):
- For DATA queries: Is the query correct? Is the analysis helpful? Does data answer the question?
- For CHAT queries: Did it respond conversationally without unnecessary data queries?
- For EDGE CASES: Did it handle ambiguous input reasonably?

Score 8-10: Excellent - fully answers the question
Score 5-7: Acceptable - mostly works with minor issues
Score 1-4: Poor - wrong results or errors

Respond with JSON only:
{{"score": <1-10>, "reasoning": "<1-2 sentences>"}}
"""
        
        try:
            response = await client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=300,
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1].replace("json", "").strip()
            
            eval_result = json.loads(content)
            df.at[idx, 'judge_score'] = eval_result.get('score', 0)
            df.at[idx, 'judge_reasoning'] = eval_result.get('reasoning', '')[:500]
            
            score = eval_result.get('score', 0)
            status = "✅" if score >= 7 else "⚠️" if score >= 5 else "❌"
            print(f" {status} {score}/10")
            
        except Exception as e:
            print(f" ❌ Error: {str(e)[:30]}")
            df.at[idx, 'judge_score'] = 0
            df.at[idx, 'judge_reasoning'] = f"Evaluation error: {str(e)[:100]}"
        
        await asyncio.sleep(0.5)  # Rate limiting
    
    # Save updated Excel
    df.to_excel(excel_file, index=False, engine='openpyxl')
    
    # Print summary
    scores = df['judge_score'].dropna()
    print()
    print("=" * 70)
    print("📊 EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Average Score: {scores.mean():.2f}/10")
    print(f"Passed (≥7): {(scores >= 7).sum()}/{len(scores)}")
    print(f"Needs Work (5-6): {((scores >= 5) & (scores < 7)).sum()}/{len(scores)}")
    print(f"Failed (<5): {(scores < 5).sum()}/{len(scores)}")
    
    # By category
    print("\nBy Category:")
    for cat in df['category'].unique():
        cat_scores = df[df['category'] == cat]['judge_score'].dropna()
        if len(cat_scores) > 0:
            avg = cat_scores.mean()
            emoji = "✅" if avg >= 7 else "⚠️" if avg >= 5 else "❌"
            print(f"  {emoji} {cat}: {avg:.1f}/10 ({(cat_scores >= 7).sum()}/{len(cat_scores)} passed)")
    
    print()
    print(f"✅ Results saved to: {excel_file}")
    print("=" * 70)


async def main():
    """Main entry point."""
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "collect":
            await phase1_collect()
        elif sys.argv[1] == "evaluate" and len(sys.argv) > 2:
            await phase2_evaluate(sys.argv[2])
        else:
            print("Usage:")
            print("  python regression_excel.py collect          # Collect responses to Excel")
            print("  python regression_excel.py evaluate <file>  # Evaluate from Excel file")
    else:
        # Run both phases
        excel_file = await phase1_collect()
        await phase2_evaluate(excel_file)


if __name__ == "__main__":
    asyncio.run(main())
