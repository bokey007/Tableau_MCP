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
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import api_client as api
from components.styles import apply_custom_styles, render_header

st.set_page_config(
    page_title="AI Insights - Tableau AI Agent",
    page_icon="📈",
    layout="wide",
)


# Apply premium styles
apply_custom_styles()

# Header
render_header("AI Insights", "Monitor system performance, user satisfaction, and agent accuracy")

# Sidebar
with st.sidebar:
    st.markdown("# 🎯 <span class='gradient-text'>Tableau AI</span>", unsafe_allow_html=True)
    st.divider()
    
    st.subheader("📅 Observation Window")
    days = st.selectbox(
        "Period",
        [7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"Past {x} Days",
    )
    
    st.divider()
    
    if st.button("🔄 Reload Metrics", use_container_width=True):
        st.rerun()
    
    st.page_link("app.py", label="Back to Explorer", icon="🏠")

# Load data
stats = api.get_dashboard_stats(days=days)

if stats.get("error"):
    st.error(f"Intelligence feed unavailable: {stats['error']}")
else:
    # High-level metrics
    queries = stats.get("queries", {})
    feedback = stats.get("feedback", {})
    users = stats.get("users", {})
    
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Requests", f"{queries.get('total', 0):,}")
    with m2:
        sr = queries.get("success_rate", 0) * 100
        st.metric("Agent Success", f"{sr:.1f}%")
    with m3:
        sat = feedback.get("satisfaction_rate", 0) * 100
        st.metric("User CSAT", f"{sat:.1f}%")
    with m4:
        st.metric("Unique Analysts", users.get("active", 0))

    st.divider()
    
    # Trends and Breakdown
    col_left, col_right = st.columns([2, 1])
    
    with col_left:
        st.subheader("📊 Request Volume Trends")
        daily = queries.get("daily", [])
        if daily:
            df = pd.DataFrame(daily)
            df["date"] = pd.to_datetime(df["date"])
            fig = px.area(df, x="date", y="count", template="plotly_dark")
            fig.update_traces(line_color="#764ba2", fillcolor="rgba(118, 75, 162, 0.2)")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for trend analysis.")

    with col_right:
        st.subheader("👍 Satisfaction")
        likes = feedback.get("likes", 0)
        dislikes = feedback.get("dislikes", 0)
        if likes + dislikes > 0:
            fig = px.pie(
                values=[likes, dislikes], 
                names=["Helpful", "Ineffective"],
                color_discrete_sequence=["#38a169", "#e53e3e"],
                template="plotly_dark",
                hole=0.6
            )
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Awaiting user feedback collection.")

    st.divider()
    
    st.subheader("⚡ Technical Performance & Latency")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            avg_time = queries.get("avg_execution_time_ms", 0)
            st.metric("Avg Latency", f"{avg_time:.0f}ms")
            st.caption("Execution & Analysis")
    with c2:
        with st.container(border=True):
            st.metric("Successful Flows", queries.get("successful", 0))
            st.caption("Completed without error")
    with c3:
        with st.container(border=True):
            st.metric("Rating Score", f"{feedback.get('avg_rating', 0):.1f}/5.0")
            st.caption("Based on explicit ratings")

    # Activity breakdown
    st.divider()
    st.subheader("📋 System Utilization")
    activity = api.get_activity_counts(days=days)
    counts = activity.get("counts", {})
    if counts:
        df_act = pd.DataFrame([{"Activity": k.replace("_", " ").title(), "Count": v} for k, v in counts.items()])
        fig_act = px.bar(df_act, x="Activity", y="Count", template="plotly_dark", color="Count", color_continuous_scale="Viridis")
        fig_act.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_act, use_container_width=True)

st.divider()
st.caption("Internal Analytics Engine v1.2 | Updates every 15 minutes")
