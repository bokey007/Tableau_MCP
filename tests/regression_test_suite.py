#!/usr/bin/env python3
"""
Comprehensive Regression Test Suite with LLM-as-Judge Evaluation

This script runs exhaustive regression tests against the Tableau MCP Agent
and uses GPT-4o as a judge to evaluate correctness, robustness, and reliability.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict, field
import httpx
from openai import AsyncOpenAI
import os

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JUDGE_MODEL = "gpt-5.2"  # Using GPT-5.2 as judge

# Test question categories with variations
TEST_QUESTIONS = {
    # ================================================================
    # DATA QUERIES - Top N
    # ================================================================
    "top_n_queries": [
        "Who are the top 5 customers?",
        "Show me the top 5 customers by sales",
        "What are the best 5 customers based on revenue?",
        "Top ten customers",
        "Give me the top 3 customers with highest sales",
        "bottom 5 customers by sales",
        "Which customers have the lowest sales?",
    ],
    
    # ================================================================
    # DATA QUERIES - Aggregations
    # ================================================================
    "aggregation_queries": [
        "What is the total sales?",
        "Show me total revenue",
        "Calculate the sum of all sales",
        "What's the average profit?",
        "Average order value",
        "How many orders do we have?",
        "Count of customers",
        "What's the maximum profit?",
        "Minimum sales amount",
    ],
    
    # ================================================================
    # DATA QUERIES - By Dimension
    # ================================================================
    "dimension_breakdown_queries": [
        "Sales by region",
        "Show sales breakdown by region",
        "Revenue by category",
        "Profit by product category",
        "Sales by state",
        "Orders by segment",
        "Sales by sub-category",
    ],
    
    # ================================================================
    # DATA QUERIES - Time Series / Trends
    # ================================================================
    "time_series_queries": [
        "Sales trend since 2020",
        "Monthly sales trend",
        "Show me sales by year",
        "Quarterly profit trend",
        "Sales trend for the last 12 months",
        "Year over year sales comparison",
        "How have sales changed over time?",
    ],
    
    # ================================================================
    # DATA QUERIES - Filters
    # ================================================================
    "filter_queries": [
        "Sales in the West region",
        "Top 5 customers in East",
        "Products with sales greater than 10000",
        "Orders from 2024",
        "Technology category sales",
        "Furniture sales by region",
        "Customers with profit > 5000",
    ],
    
    # ================================================================
    # DATA QUERIES - Complex / Multi-dimensional
    # ================================================================
    "complex_queries": [
        "Top 5 products by profit in each region",
        "Compare sales between Technology and Furniture",
        "Which region has the highest profit margin?",
        "Sales and profit by category",
        "Customer count and total sales by segment",
        "Average discount by category",
    ],
    
    # ================================================================
    # CHAT / NON-DATA QUERIES
    # ================================================================
    "chat_queries": [
        "Hello",
        "Hi there!",
        "What can you do?",
        "Help me understand your capabilities",
        "Thanks!",
        "How are you?",
        "Who made you?",
        "What data sources do you have access to?",
    ],
    
    # ================================================================
    # EDGE CASES / AMBIGUOUS
    # ================================================================
    "edge_cases": [
        "sales",
        "show me everything",
        "what's the story with our data?",
        "Analyze the performance",
        "Give me insights",
    ],
}


@dataclass
class TestResult:
    """Single test result with evaluation."""
    question: str
    category: str
    iteration: int
    
    # Response data
    success: bool
    response_time_ms: float
    analysis: Optional[str]
    generated_query: Optional[Dict]
    results_row_count: int
    visualization: Optional[Dict]
    error: Optional[str]
    
    # Judge evaluation
    judge_overall_score: float
    judge_query_correctness: float
    judge_analysis_quality: float
    judge_data_relevance: float
    judge_reasoning: str
    judge_issues: List[str] = field(default_factory=list)


@dataclass
class TestSummary:
    """Overall test summary."""
    total_tests: int
    passed_tests: int
    failed_tests: int
    avg_response_time_ms: float
    avg_judge_score: float
    by_category: Dict[str, Dict]
    issues_found: List[str]
    recommendations: List[str]


class RegressionTestRunner:
    """Runs regression tests and evaluates with LLM judge."""
    
    def __init__(self, backend_url: str, openai_api_key: str):
        self.backend_url = backend_url.rstrip("/")
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)
        self.results: List[TestResult] = []
        self.thread_id = str(uuid.uuid4())
        
    async def run_query(self, question: str, username: str = "regression_test") -> Dict[str, Any]:
        """Send a query to the backend API."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            start = time.monotonic()
            try:
                response = await client.post(
                    f"{self.backend_url}/query",  # No trailing slash
                    json={
                        "question": question,
                        "username": username,
                        "thread_id": self.thread_id,
                    }
                )
                elapsed_ms = (time.monotonic() - start) * 1000
                
                if response.status_code == 200:
                    data = response.json()
                    data["response_time_ms"] = elapsed_ms
                    return data
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text[:200]}",
                        "response_time_ms": elapsed_ms,
                    }
            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                return {
                    "success": False,
                    "error": str(e),
                    "response_time_ms": elapsed_ms,
                }
    
    async def evaluate_with_judge(
        self, 
        question: str, 
        category: str,
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use GPT-4o as judge to comprehensively evaluate the response."""
        
        # Extract data safely
        results_data = []
        if response.get("results") and isinstance(response["results"], dict):
            results_data = response["results"].get("data", [])[:5]
        
        # Comprehensive evaluation prompt
        judge_prompt = f"""You are an expert QA evaluator for an AI-powered Tableau data analysis agent. 
Your task is to rigorously evaluate the agent's complete response pipeline.

═══════════════════════════════════════════════════════════════
ORIGINAL USER QUESTION
═══════════════════════════════════════════════════════════════
Category: {category}
Question: "{question}"

═══════════════════════════════════════════════════════════════
AGENT RESPONSE TO EVALUATE
═══════════════════════════════════════════════════════════════

1. EXECUTION STATUS:
   - Success: {response.get('success', False)}
   - Error: {response.get('error', 'None')}

2. GENERATED VIZQL QUERY:
{json.dumps(response.get('query'), indent=2)[:600] if response.get('query') else 'None (no query generated)'}

3. EXTRACTED DATA FROM TABLEAU:
   - Row count: {len(results_data)} rows
   - Sample rows:
{json.dumps(results_data, indent=2)[:500] if results_data else 'None (no data extracted)'}

4. LLM ANALYSIS/RESPONSE:
{(response.get('analysis') or 'None')[:600]}

5. VISUALIZATION CONFIG:
{json.dumps(response.get('visualization'), indent=2) if response.get('visualization') else 'None'}

═══════════════════════════════════════════════════════════════
EVALUATION CRITERIA (Score each 1-10)
═══════════════════════════════════════════════════════════════

**1. QUESTION UNDERSTANDING (query_correctness)**
For DATA queries, evaluate the generated VizQL query:
- Does it correctly interpret what the user is asking?
- Are the right fields/columns selected (e.g., "Customer Name", "Sales")?
- Is the aggregation correct (SUM for totals, COUNT for counts, AVG for averages)?
- Are filters appropriate (TOP N filters, date filters, region filters)?
- Is sorting correct for ranking questions?
- Score 1-4 if query is wrong or missing key elements
- Score 5-7 if query is mostly correct with minor issues
- Score 8-10 if query perfectly captures the user's intent

For CHAT queries (greetings, help requests):
- Score 5 (N/A) since no query is expected

**2. DATA EXTRACTION & RELEVANCE (data_relevance)**
- Does the extracted data answer the question asked?
- Is the row count appropriate (e.g., 5 rows for "top 5")?
- Are the values reasonable and consistent with the query?
- For CHAT queries: Score 5 (N/A)
- Score 1-4 if wrong data or irrelevant results
- Score 5-7 if data is partially relevant
- Score 8-10 if data perfectly matches the question

**3. ANALYSIS QUALITY & ACCURACY (analysis_quality)**
- Does the LLM response directly answer the original question?
- Are the insights accurate based on the data shown?
- Is the analysis clear, professional, and actionable?
- For CHAT queries: Is the conversational response appropriate and helpful?
- Score 1-4 if analysis is wrong, unclear, or doesn't answer the question
- Score 5-7 if analysis is acceptable but could be better
- Score 8-10 if analysis is excellent and accurately answers the question

**4. OVERALL SCORE (overall_score)**
Holistic evaluation considering:
- Did the full pipeline work correctly?
- Would a business user be satisfied with this response?
- Are there any critical errors or misleading information?

═══════════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════════
Respond with ONLY valid JSON (no markdown, no extra text):
{{
    "overall_score": <float 1-10>,
    "query_correctness": <float 1-10>,
    "analysis_quality": <float 1-10>,
    "data_relevance": <float 1-10>,
    "reasoning": "<2-3 sentences explaining your evaluation>",
    "issues": ["<specific issue 1>", "<specific issue 2>"]
}}

If no issues found, use empty array: "issues": []
"""
        
        try:
            judge_response = await self.openai_client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0.1,
                max_completion_tokens=600,
            )
            
            content = judge_response.choices[0].message.content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:].strip()
            
            return json.loads(content)
            
        except Exception as e:
            print(f"  ⚠️  Judge error: {str(e)[:50]}")
            return {
                "overall_score": 0.0,
                "query_correctness": 0.0,
                "analysis_quality": 0.0,
                "data_relevance": 0.0,
                "reasoning": f"Evaluation failed: {e}",
                "issues": ["Judge evaluation error"],
            }
    
    async def run_single_test(
        self, 
        question: str, 
        category: str, 
        iteration: int
    ) -> TestResult:
        """Run a single test and evaluate."""
        print(f"  Testing: '{question[:45]}...' (iter {iteration + 1})", end="", flush=True)
        
        # Run the query
        response = await self.run_query(question)
        
        # Evaluate with judge
        evaluation = await self.evaluate_with_judge(question, category, response)
        
        # Get results count
        results_count = 0
        if response.get("results") and isinstance(response["results"], dict):
            results_count = len(response["results"].get("data", []))
        
        result = TestResult(
            question=question,
            category=category,
            iteration=iteration,
            success=response.get("success", False),
            response_time_ms=response.get("response_time_ms", 0),
            analysis=response.get("analysis"),
            generated_query=response.get("query"),
            results_row_count=results_count,
            visualization=response.get("visualization"),
            error=response.get("error"),
            judge_overall_score=evaluation.get("overall_score", 0),
            judge_query_correctness=evaluation.get("query_correctness", 0),
            judge_analysis_quality=evaluation.get("analysis_quality", 0),
            judge_data_relevance=evaluation.get("data_relevance", 0),
            judge_reasoning=evaluation.get("reasoning", ""),
            judge_issues=evaluation.get("issues", []),
        )
        
        self.results.append(result)
        
        # Print quick status
        score = result.judge_overall_score
        status = "✅" if result.success and score >= 7 else "⚠️" if result.success else "❌"
        print(f" {status} {score:.1f}/10 ({result.response_time_ms:.0f}ms)")
        
        return result
    
    async def run_all_tests(self, iterations: int = 1) -> TestSummary:
        """Run all tests with specified iterations."""
        print("=" * 60)
        print("🧪 REGRESSION TEST SUITE - LLM-as-Judge Evaluation")
        print("=" * 60)
        print(f"Judge Model: {JUDGE_MODEL}")
        print(f"Iterations per question: {iterations}")
        print(f"Backend URL: {self.backend_url}")
        print()
        
        total_questions = sum(len(q) for q in TEST_QUESTIONS.values())
        print(f"📝 Total unique questions: {total_questions}")
        print(f"📝 Total tests to run: {total_questions * iterations}")
        print()
        
        # Run tests by category
        for category, questions in TEST_QUESTIONS.items():
            print(f"\n📂 {category.upper().replace('_', ' ')}")
            print("-" * 45)
            
            # Reset thread for each category
            self.thread_id = str(uuid.uuid4())
            
            for question in questions:
                for iteration in range(iterations):
                    await self.run_single_test(question, category, iteration)
                    await asyncio.sleep(2)  # Increased delay to reduce backend load
        
        return self.generate_summary()
    
    def generate_summary(self) -> TestSummary:
        """Generate test summary."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.success and r.judge_overall_score >= 7)
        failed = total - passed
        
        avg_time = sum(r.response_time_ms for r in self.results) / total if total else 0
        avg_score = sum(r.judge_overall_score for r in self.results) / total if total else 0
        
        # By category
        by_category = {}
        for category in TEST_QUESTIONS.keys():
            cat_results = [r for r in self.results if r.category == category]
            if cat_results:
                by_category[category] = {
                    "total": len(cat_results),
                    "passed": sum(1 for r in cat_results if r.success and r.judge_overall_score >= 7),
                    "avg_score": sum(r.judge_overall_score for r in cat_results) / len(cat_results),
                    "avg_time_ms": sum(r.response_time_ms for r in cat_results) / len(cat_results),
                }
        
        # Collect issues
        all_issues = []
        for r in self.results:
            for issue in r.judge_issues:
                if issue and issue not in all_issues:
                    all_issues.append(issue)
        
        # Recommendations
        recommendations = []
        slow_queries = [r for r in self.results if r.response_time_ms > 20000]
        if slow_queries:
            recommendations.append(f"Performance: {len(slow_queries)} queries took >20s")
        
        for cat, stats in by_category.items():
            if stats["avg_score"] < 7:
                recommendations.append(f"Quality: '{cat}' avg score {stats['avg_score']:.1f}/10")
        
        error_results = [r for r in self.results if not r.success]
        if error_results:
            recommendations.append(f"Reliability: {len(error_results)} queries failed")
        
        return TestSummary(
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            avg_response_time_ms=avg_time,
            avg_judge_score=avg_score,
            by_category=by_category,
            issues_found=all_issues[:20],
            recommendations=recommendations,
        )
    
    def print_report(self, summary: TestSummary):
        """Print detailed test report."""
        print("\n")
        print("=" * 60)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        pass_rate = (summary.passed_tests / summary.total_tests * 100) if summary.total_tests else 0
        print(f"\n✅ Passed: {summary.passed_tests}/{summary.total_tests} ({pass_rate:.1f}%)")
        print(f"❌ Failed: {summary.failed_tests}")
        print(f"⏱️  Avg Response Time: {summary.avg_response_time_ms:.0f}ms")
        print(f"🎯 Avg Judge Score: {summary.avg_judge_score:.2f}/10")
        
        print("\n📂 RESULTS BY CATEGORY")
        print("-" * 50)
        for category, stats in summary.by_category.items():
            emoji = "✅" if stats["avg_score"] >= 7 else "⚠️" if stats["avg_score"] >= 5 else "❌"
            print(f"  {emoji} {category}: {stats['passed']}/{stats['total']} passed, avg {stats['avg_score']:.1f}/10")
        
        if summary.issues_found:
            print("\n⚠️  TOP ISSUES")
            print("-" * 50)
            for issue in summary.issues_found[:10]:
                print(f"  • {issue[:80]}")
        
        if summary.recommendations:
            print("\n💡 RECOMMENDATIONS")
            print("-" * 50)
            for rec in summary.recommendations:
                print(f"  → {rec}")
        
        # Show failed tests
        failed = [r for r in self.results if not r.success or r.judge_overall_score < 5]
        if failed:
            print(f"\n❌ LOW-SCORING TESTS ({len(failed)} total)")
            print("-" * 50)
            for r in failed[:5]:
                print(f"  '{r.question[:40]}...' - Score: {r.judge_overall_score}/10")
                if r.error:
                    print(f"    Error: {r.error[:60]}")
        
        print("\n" + "=" * 60)
    
    def save_results(self, summary: TestSummary, filename: str = None):
        """Save detailed results to JSON."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"regression_results_{timestamp}.json"
        
        output = {
            "summary": asdict(summary),
            "results": [asdict(r) for r in self.results],
            "timestamp": datetime.now().isoformat(),
            "judge_model": JUDGE_MODEL,
            "backend_url": self.backend_url,
        }
        
        with open(filename, "w") as f:
            json.dump(output, f, indent=2, default=str)
        
        print(f"📁 Results saved to: {filename}")
        return filename


async def main():
    """Main entry point."""
    if not OPENAI_API_KEY:
        print("❌ Error: OPENAI_API_KEY not set")
        return
    
    runner = RegressionTestRunner(BACKEND_URL, OPENAI_API_KEY)
    
    # Run with 1 iteration (faster) - increase to 2+ for reliability testing
    summary = await runner.run_all_tests(iterations=1)
    
    runner.print_report(summary)
    runner.save_results(summary)
    
    pass_rate = summary.passed_tests / summary.total_tests if summary.total_tests else 0
    if pass_rate >= 0.8:
        print(f"\n✅ PASSED with {pass_rate:.1%} success rate!")
    else:
        print(f"\n⚠️ Below 80% threshold: {pass_rate:.1%}")


if __name__ == "__main__":
    asyncio.run(main())
