# =============================================================================
# Streamlit Main Application
# =============================================================================
"""
Tableau MCP AI Agent - Streamlit Frontend

A modern, interactive UI for querying Tableau data using natural language.
"""

import streamlit as st
import pandas as pd
import uuid
import plotly.express as px
from datetime import datetime

# Import shared UI components
from components.api_client import api_client as api
from components.styles import (
    apply_custom_styles, 
    render_chat_header, 
    render_centered_container_start, 
    render_centered_container_end
)

# Page configuration
st.set_page_config(
    page_title="Tableau AI Explorer",
    page_icon="🎯",
    layout="wide",
)

# Apply sleek ChatGPT-like styles
apply_custom_styles()

# =============================================================================
# Session State Initialization
# =============================================================================

if "username" not in st.session_state:
    st.session_state.username = "default_user"
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

# =============================================================================
# Sidebar (Minimalist)
# =============================================================================

with st.sidebar:
    st.markdown("### 🛠️ Workspace")
    
    st.page_link("app.py", label="New Chat", icon="➕")
    st.page_link("pages/history.py", label="Past Conversations", icon="📜")
    st.page_link("pages/analytics.py", label="Usage Analytics", icon="📈")
    st.page_link("pages/datasources.py", label="Data Catalog", icon="🗄️")
    
    st.divider()
    
    with st.expander("👤 Identity Settings"):
        st.session_state.username = st.text_input("Username", value=st.session_state.username)
        st.caption(f"Thread ID: `{st.session_state.thread_id[:8]}...`")
    
    if st.button("🗑️ Clear Current Chat", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.chat_messages = []
        st.rerun()

# =============================================================================
# Main Chat Interface (Centered ChatGPT Flow)
# =============================================================================

# 1. Top Navigation
render_chat_header()

# 2. Centered Chat Content
render_centered_container_start()

# Display Welcome if no messages
if not st.session_state.chat_messages:
    st.markdown("""
        <div style="text-align: center; padding: 100px 20px;">
            <h1 style="font-size: 2.5rem; margin-bottom: 10px;">How can I help you with <span class="gradient-text">Tableau</span>?</h1>
            <p style="color: #94a3b8; font-size: 1.1rem;">I can analyze datasets, create visualizations, and answer complex business questions from your published datasources.</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Quick suggestion tiles
    cols = st.columns(2)
    suggestions = [
        "📦 Who are the top 5 customers?",
        "📈 Show profit trends for 2024",
        "🗺️ Sales distribution by region",
        "⚠️ Which products are losing money?"
    ]
    for i, suggestion in enumerate(suggestions):
        with cols[i % 2]:
            if st.button(suggestion, use_container_width=True):
                # Auto-inject the suggestion as a prompt
                st.session_state.chat_messages.append({"role": "user", "content": suggestion})
                st.rerun()

# Display the conversation
for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        
        # If it's an assistant message with data results, render the interactive card
        if msg["role"] == "assistant" and "result" in msg:
            result = msg["result"]
            
            # Safely get results data (may be None for chat responses)
            results_data = result.get("results") or {}
            data = results_data.get("data", []) if isinstance(results_data, dict) else []
            
            # Only show data card if there's actual data (not for chat responses)
            if data:
                with st.container():
                    st.markdown('<div class="result-card">', unsafe_allow_html=True)
                    
                    # Tabbed results for a cleaner look within the bubble
                    tab_viz, tab_data = st.tabs(["📊 Visualization", "📄 Data Table"])
                    
                    with tab_viz:
                        # Logic to render plotly (same as before but compact)
                        if result.get("visualization"):
                            viz = result["visualization"]
                            df = pd.DataFrame(data)
                            fig = None
                            try:
                                if viz.get("chart_type") == "bar":
                                    fig = px.bar(df, x=viz.get("x_axis"), y=viz.get("y_axis"), template="plotly_dark")
                                elif viz.get("chart_type") == "line":
                                    fig = px.line(df, x=viz.get("x_axis"), y=viz.get("y_axis"), template="plotly_dark")
                                
                                if fig:
                                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=300, margin=dict(t=10, b=10))
                                    st.plotly_chart(fig, use_container_width=True)
                            except:
                                st.caption("Visual rendering issue. Check Data tab.")
                        else:
                            st.caption("No visualization recommended.")
                    
                    with tab_data:
                        df = pd.DataFrame(data)
                        st.dataframe(df.head(10), use_container_width=True)
                        st.caption(f"Showing 10 of {len(df)} rows.")
                    
                    st.markdown('</div>', unsafe_allow_html=True)

# 3. Handle Input
if prompt := st.chat_input("Ask anything about your data..."):
    # Add User Message
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    
    # Process immediately
    with st.chat_message("assistant"):
        with st.spinner(""):
            res = api.query(
                question=prompt,
                username=st.session_state.username,
                thread_id=st.session_state.thread_id
            )
            
            if res.get("success"):
                analysis = res.get("analysis", "Here is my analysis.")
                st.markdown(analysis)
                # Store result in state so it persists on rerun
                st.session_state.chat_messages.append({
                    "role": "assistant", 
                    "content": analysis,
                    "result": res
                })
            else:
                error_msg = f"I encountered an error: {res.get('error', 'Unknown issue')}"
                st.markdown(error_msg)
                st.session_state.chat_messages.append({
                    "role": "assistant", 
                    "content": error_msg
                })
    
    st.rerun()

render_centered_container_end()
