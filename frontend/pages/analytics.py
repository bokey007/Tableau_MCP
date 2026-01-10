# =============================================================================
# Analytics Dashboard Page
# =============================================================================
"""Analytics and usage reporting dashboard."""

import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# Import shared API client
import sys
sys.path.insert(0, '..')
from components.api_client import api_client as api

st.set_page_config(
    page_title="Analytics - Tableau AI Agent",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Analytics Dashboard")
st.caption("Usage statistics and performance metrics")


# Sidebar
with st.sidebar:
    st.subheader("📅 Time Period")
    days = st.selectbox(
        "Select period",
        [7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"Last {x} days",
    )
    
    st.divider()
    
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# Load data
stats = api.get_dashboard_stats(days=days)

if stats.get("error"):
    st.error(f"Failed to load analytics: {stats['error']}")
    st.info("Make sure the backend is running and accessible.")
else:
    # Overview metrics
    st.subheader("📈 Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    queries = stats.get("queries", {})
    feedback = stats.get("feedback", {})
    users = stats.get("users", {})
    
    with col1:
        st.metric(
            "Total Queries",
            queries.get("total", 0),
            help="Total queries in the selected period"
        )
    
    with col2:
        success_rate = queries.get("success_rate", 0) * 100
        st.metric(
            "Success Rate",
            f"{success_rate:.1f}%",
            help="Percentage of successful queries"
        )
    
    with col3:
        satisfaction = feedback.get("satisfaction_rate", 0) * 100
        st.metric(
            "Satisfaction",
            f"{satisfaction:.1f}%",
            help="Percentage of liked responses"
        )
    
    with col4:
        st.metric(
            "Active Users",
            users.get("active", 0),
            help="Users who made queries in this period"
        )
    
    st.divider()
    
    # Charts row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 Daily Query Volume")
        
        daily = queries.get("daily", [])
        if daily:
            df = pd.DataFrame(daily)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            
            fig = px.area(
                df,
                x="date",
                y="count",
                title="Queries per Day",
            )
            fig.update_layout(
                xaxis_title="Date",
                yaxis_title="Queries",
                showlegend=False,
                height=350,
            )
            fig.update_traces(
                fill='tozeroy',
                line_color='#667eea',
                fillcolor='rgba(102, 126, 234, 0.3)',
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No daily data available")
    
    with col2:
        st.subheader("👍 Feedback Distribution")
        
        likes = feedback.get("likes", 0)
        dislikes = feedback.get("dislikes", 0)
        neutral = feedback.get("neutral", 0)
        
        if likes + dislikes + neutral > 0:
            fig = go.Figure(data=[go.Pie(
                labels=["👍 Likes", "👎 Dislikes", "😐 Neutral"],
                values=[likes, dislikes, neutral],
                hole=0.4,
                marker_colors=["#38a169", "#e53e3e", "#a0aec0"],
            )])
            fig.update_layout(
                title="Feedback Breakdown",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No feedback data available yet")
            st.caption("Users haven't provided feedback on queries")
    
    st.divider()
    
    # Second row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🗄️ Top Datasources")
        
        top_ds = stats.get("top_datasources", [])
        if top_ds:
            df = pd.DataFrame(top_ds)
            
            fig = px.bar(
                df,
                x="query_count",
                y="datasource_name",
                orientation="h",
                title="Most Queried Datasources",
            )
            fig.update_layout(
                xaxis_title="Query Count",
                yaxis_title="",
                showlegend=False,
                height=300,
            )
            fig.update_traces(marker_color="#667eea")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No datasource usage data")
    
    with col2:
        st.subheader("⚡ Performance")
        
        col_a, col_b = st.columns(2)
        
        with col_a:
            avg_time = queries.get("avg_execution_time_ms")
            st.metric(
                "Avg Execution Time",
                f"{avg_time:.0f}ms" if avg_time else "N/A",
            )
            st.metric("Successful Queries", queries.get("successful", 0))
        
        with col_b:
            st.metric("Failed Queries", queries.get("failed", 0))
            
            avg_rating = feedback.get("avg_rating")
            st.metric(
                "Avg Rating",
                f"{avg_rating:.1f}/5" if avg_rating else "N/A",
            )
    
    st.divider()
    
    # User statistics
    st.subheader("👥 User Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("Total Users", users.get("total", 0))
    col2.metric("Active Users", users.get("active", 0))
    col3.metric("New Users", users.get("new", 0))
    col4.metric("Total Sessions", users.get("sessions", 0))
    
    # Activity breakdown
    st.divider()
    st.subheader("📋 Activity Breakdown")
    
    activity = api.get_activity_counts(days=days)
    counts = activity.get("counts", {})
    
    if counts:
        # Create bar chart for activity types
        df = pd.DataFrame([
            {"Activity": k.replace("_", " ").title(), "Count": v} 
            for k, v in counts.items()
        ])
        
        fig = px.bar(df, x="Activity", y="Count", title="Activity by Type")
        fig.update_traces(marker_color="#667eea")
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No activity data for this period")
    
    # Download report
    st.divider()
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("📥 Download Report", use_container_width=True):
            report = api.get_usage_report()
            if not report.get("error"):
                import json
                st.download_button(
                    "💾 Save JSON Report",
                    json.dumps(report, indent=2),
                    "usage_report.json",
                    "application/json",
                )
            else:
                st.error("Failed to generate report")

# Footer
st.divider()
st.page_link("app.py", label="← Back to Home", icon="🏠")
