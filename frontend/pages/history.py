# =============================================================================
# Query History Page
# =============================================================================
"""View and manage query history with feedback tracking."""

import streamlit as st
from datetime import datetime
import pandas as pd

# Import shared API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import api_client as api
from components.styles import apply_custom_styles, render_header


st.set_page_config(
    page_title="Query History - Tableau AI Agent",
    page_icon="📜",
    layout="wide",
)

# Apply premium styles
apply_custom_styles()


# Session state
if "username" not in st.session_state:
    st.session_state.username = "default_user"

# Sidebar
with st.sidebar:
    st.markdown("# 🎯 <span class='gradient-text'>Tableau AI</span>", unsafe_allow_html=True)
    st.divider()
    
    st.subheader("🔍 Filters")
    
    username = st.text_input("Username", value=st.session_state.username)
    if username != st.session_state.username:
        st.session_state.username = username
    
    limit = st.slider("Max Records", 10, 200, 50)
    
    status_filter = st.selectbox(
        "Observation Status",
        ["All", "Success", "Failed", "Pending"],
        index=0,
    )
    
    st.divider()
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()
        
    st.page_link("app.py", label="Back to Explorer", icon="🏠")

# Convert status filter
status_param = None
if status_filter == "Success":
    status_param = "success"
elif status_filter == "Failed":
    status_param = "failed"
elif status_filter == "Pending":
    status_param = "pending"

# Header
render_header("Query History", "Review and audit previous data interactions")

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
        st.info("No records found for the current criteria.")
    else:
        # Statistics in modern cards
        col1, col2, col3, col4 = st.columns(4)
        
        total = len(queries)
        successful = sum(1 for q in queries if q.get("status") == "success")
        with_feedback = sum(1 for q in queries if q.get("has_feedback"))
        likes = sum(1 for q in queries if q.get("feedback_type") == "like")
        
        col1.metric("Lifetime Queries", total)
        col2.metric("Success Rate", f"{(successful/total*100) if total > 0 else 0:.1f}%")
        col3.metric("Feedback Coverage", f"{(with_feedback/total*100) if total > 0 else 0:.1f}%")
        col4.metric("User Approval", f"{(likes/with_feedback*100) if with_feedback > 0 else 0:.1f}%")
        
        st.divider()
        
        # Query list
        for i, query in enumerate(queries):
            status = query.get("status", "unknown")
            color = "#38a169" if status == "success" else "#e53e3e" if status == "failed" else "#ecc94b"
            
            with st.expander(f"📌 {query['question'][:100]}", expanded=(i == 0)):
                # Content within expander
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1:
                    st.markdown(f"**Question:** {query['question']}")
                    st.caption(f"ID: `{query['id']}`")
                with c2:
                    st.markdown(f"<span style='color: {color}; font-weight: bold;'>{status.upper()}</span>", unsafe_allow_html=True)
                    if query.get("datasource_name"):
                        st.caption(f"Asset: {query['datasource_name']}")
                with c3:
                    try:
                        created = datetime.fromisoformat(query["created_at"].replace('Z', '+00:00'))
                        st.caption(f"🕒 {created.strftime('%b %d, %H:%M')}")
                    except:
                        st.caption(f"🕒 {query.get('created_at', 'N/A')}")

                if st.button("🔍 View Full Details", key=f"det_{query['id']}", use_container_width=True):
                    detail = api.get_query_detail(query["id"])
                    if detail.get("error"):
                        st.error(f"Failed to load details: {detail['error']}")
                    else:
                        st.markdown("---")
                        
                        # Use 4 tabs for comprehensive view
                        tab_analysis, tab_query, tab_raw, tab_llm = st.tabs([
                            "💡 AI Analysis", 
                            "🔧 Generated Query", 
                            "📊 Raw Data (Tableau)", 
                            "🤖 Data Passed to LLM"
                        ])
                        
                        with tab_analysis:
                            analysis_text = detail.get("analysis", "No analysis recorded.")
                            st.markdown(analysis_text if analysis_text else "_No analysis available_")
                            
                            # Visualization config if present
                            if detail.get("visualization"):
                                st.markdown("**Visualization Recommendation:**")
                                st.json(detail["visualization"])
                        
                        with tab_query:
                            generated_query = detail.get("query")
                            if generated_query:
                                st.markdown("**VizQL Query sent to Tableau:**")
                                st.json(generated_query)
                            else:
                                st.info("No generated query recorded for this interaction.")
                            
                            # Metadata
                            st.markdown("---")
                            st.markdown("**Execution Metadata:**")
                            meta_cols = st.columns(3)
                            meta_cols[0].metric("Execution Time", f"{detail.get('execution_time_ms', 0):.0f} ms")
                            meta_cols[1].metric("Rows Returned", detail.get("row_count", 0))
                            meta_cols[2].metric("Datasource", detail.get("datasource_name", "N/A"))
                        
                        with tab_raw:
                            raw_results = detail.get("results")
                            if raw_results and raw_results.get("data"):
                                raw_data = raw_results["data"]
                                st.markdown(f"**Raw data returned from Tableau** ({len(raw_data)} rows)")
                                df_raw = pd.DataFrame(raw_data)
                                st.dataframe(df_raw, use_container_width=True, height=400)
                                
                                # Download button
                                csv_raw = df_raw.to_csv(index=False)
                                st.download_button(
                                    "📥 Download Raw Data (CSV)",
                                    csv_raw,
                                    f"raw_data_{query['id'][:8]}.csv",
                                    "text/csv",
                                    key=f"dl_raw_{query['id']}"
                                )
                            else:
                                st.info("No raw data was returned for this query.")
                        
                        with tab_llm:
                            analyzed_data = detail.get("analyzed_data")
                            if analyzed_data and analyzed_data.get("data"):
                                llm_data = analyzed_data["data"]
                                st.markdown(f"**Data passed to LLM for analysis** ({len(llm_data)} rows)")
                                
                                if analyzed_data.get("description"):
                                    st.caption(f"📝 {analyzed_data['description']}")
                                
                                df_llm = pd.DataFrame(llm_data)
                                st.dataframe(df_llm, use_container_width=True, height=400)
                                
                                # Download button
                                csv_llm = df_llm.to_csv(index=False)
                                st.download_button(
                                    "📥 Download LLM Data (CSV)",
                                    csv_llm,
                                    f"llm_data_{query['id'][:8]}.csv",
                                    "text/csv",
                                    key=f"dl_llm_{query['id']}"
                                )
                                
                                # Show difference if applicable
                                if raw_results and raw_results.get("data"):
                                    raw_count = len(raw_results["data"])
                                    llm_count = len(llm_data)
                                    if raw_count != llm_count:
                                        st.caption(f"⚠️ Note: {raw_count} rows from Tableau were processed to {llm_count} rows for LLM (aggregation/sampling may have occurred)")
                            else:
                                st.info("No processed LLM data available. The raw data was passed directly to the model.")
                        
                        # Error section if applicable
                        if detail.get("error"):
                            st.error(f"**Error encountered:** {detail['error']}")
                                
        st.divider()
        st.caption("Agent Audit Logs v1.3 | Full Query Traceability Enabled")
