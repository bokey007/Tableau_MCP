# =============================================================================
# Query History Page
# =============================================================================
"""View and manage query history with feedback tracking."""

import streamlit as st
from datetime import datetime
import pandas as pd

# Import shared API client
import sys
sys.path.insert(0, '..')
from components.api_client import api_client as api

st.set_page_config(
    page_title="Query History - Tableau AI Agent",
    page_icon="📜",
    layout="wide",
)

# Custom CSS
st.markdown("""
<style>
    .query-card {
        background: linear-gradient(135deg, #1a1f2c 0%, #2d3748 100%);
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
        border-left: 3px solid #667eea;
    }
    .success-badge {
        background-color: #38a169;
        color: white;
        padding: 0.2rem 0.5rem;
        border-radius: 0.25rem;
        font-size: 0.8rem;
    }
    .failed-badge {
        background-color: #e53e3e;
        color: white;
        padding: 0.2rem 0.5rem;
        border-radius: 0.25rem;
        font-size: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


st.title("📜 Query History")
st.caption("View your past queries and their results")


# Session state
if "username" not in st.session_state:
    st.session_state.username = "default_user"

# Sidebar
with st.sidebar:
    st.subheader("🔍 Filters")
    
    username = st.text_input("Username", value=st.session_state.username)
    if username != st.session_state.username:
        st.session_state.username = username
    
    limit = st.slider("Number of queries", 10, 200, 50)
    
    status_filter = st.selectbox(
        "Status",
        ["All", "Success", "Failed", "Pending"],
        index=0,
    )
    
    st.divider()
    
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# Convert status filter
status_param = None
if status_filter == "Success":
    status_param = "success"
elif status_filter == "Failed":
    status_param = "failed"
elif status_filter == "Pending":
    status_param = "pending"

# Load history
history_response = api.get_query_history(
    username=st.session_state.username, 
    limit=limit,
    status=status_param
)

if history_response.get("error"):
    st.error(f"Failed to load history: {history_response['error']}")
else:
    queries = history_response.get("queries", [])
    
    if not queries:
        st.info("📭 No query history found. Start by asking a question on the home page!")
        st.page_link("app.py", label="Go to Home", icon="🏠")
    else:
        # Statistics
        col1, col2, col3, col4 = st.columns(4)
        
        total = len(queries)
        successful = sum(1 for q in queries if q.get("status") == "success")
        with_feedback = sum(1 for q in queries if q.get("has_feedback"))
        likes = sum(1 for q in queries if q.get("feedback_type") == "like")
        
        col1.metric("📊 Total Queries", total)
        col2.metric("✅ Successful", successful)
        col3.metric("💬 With Feedback", with_feedback)
        col4.metric("👍 Liked", likes)
        
        st.divider()
        
        # Query list
        for i, query in enumerate(queries):
            status = query.get("status", "unknown")
            status_icon = "✅" if status == "success" else "❌" if status == "failed" else "⏳"
            
            with st.expander(f"{status_icon} {query['question'][:80]}...", expanded=(i == 0)):
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.markdown(f"**Question:** {query['question']}")
                    st.caption(f"🔑 ID: `{query['id'][:8]}...`")
                    
                    if query.get("datasource_name"):
                        st.caption(f"📊 Datasource: {query['datasource_name']}")
                
                with col2:
                    if status == "success":
                        st.success(f"✅ SUCCESS")
                    elif status == "failed":
                        st.error(f"❌ FAILED")
                    else:
                        st.warning(f"⏳ {status.upper()}")
                
                with col3:
                    try:
                        created = datetime.fromisoformat(query["created_at"].replace('Z', '+00:00'))
                        st.caption(f"📅 {created.strftime('%Y-%m-%d %H:%M')}")
                    except:
                        st.caption(f"📅 {query.get('created_at', 'N/A')}")
                    
                    if query.get("execution_time_ms"):
                        st.caption(f"⏱️ {query['execution_time_ms']:.0f}ms")
                    
                    if query.get("row_count"):
                        st.caption(f"📊 {query['row_count']} rows")
                
                # Feedback section
                st.markdown("---")
                
                if query.get("has_feedback"):
                    fb_type = query.get("feedback_type", "neutral")
                    if fb_type == "like":
                        st.markdown("👍 **You liked this response**")
                    elif fb_type == "dislike":
                        st.markdown("👎 **You disliked this response**")
                    else:
                        st.markdown("😐 **Neutral feedback**")
                else:
                    col1, col2, col3 = st.columns([1, 1, 3])
                    
                    with col1:
                        if st.button("👍 Like", key=f"like_{query['id']}"):
                            result = api.submit_feedback(
                                query['id'], 
                                "like", 
                                username=st.session_state.username
                            )
                            if not result.get("error"):
                                st.success("Feedback submitted!")
                                st.rerun()
                            else:
                                st.error(result["error"])
                    
                    with col2:
                        if st.button("👎 Dislike", key=f"dislike_{query['id']}"):
                            result = api.submit_feedback(
                                query['id'], 
                                "dislike", 
                                username=st.session_state.username
                            )
                            if not result.get("error"):
                                st.success("Feedback submitted!")
                                st.rerun()
                            else:
                                st.error(result["error"])
                
                # View details button
                if st.button("📋 View Full Details", key=f"view_{query['id']}"):
                    detail = api.get_query_detail(query["id"])
                    
                    if detail.get("error"):
                        st.error(detail["error"])
                    else:
                        st.markdown("### 💡 Analysis")
                        st.markdown(detail.get("analysis") or "_No analysis available_")
                        
                        if detail.get("results") and detail["results"].get("data"):
                            st.markdown("### 📊 Data (first 10 rows)")
                            df = pd.DataFrame(detail["results"]["data"][:10])
                            st.dataframe(df, use_container_width=True)
                        
                        if detail.get("query"):
                            st.markdown("### 🔧 Generated Query")
                            st.json(detail["query"])
                        
                        if detail.get("error"):
                            st.markdown("### ❌ Error")
                            st.error(detail["error"])


# Footer
st.divider()
st.page_link("app.py", label="← Back to Home", icon="🏠")
