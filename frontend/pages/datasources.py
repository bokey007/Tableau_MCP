# =============================================================================
# Datasources Page
# =============================================================================
"""Browse and explore available Tableau datasources."""

import streamlit as st

# Import shared API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from components.api_client import api_client as api
from components.styles import apply_custom_styles, render_header

st.set_page_config(
    page_title="Data Assets - Tableau AI Agent",
    page_icon="🗄️",
    layout="wide",
)


# Apply premium styles
apply_custom_styles()

# Header
render_header("Data Assets", "Explore and understand your connected Tableau data catalogs")

# Sidebar
with st.sidebar:
    st.markdown("# 🎯 <span class='gradient-text'>Tableau AI</span>", unsafe_allow_html=True)
    st.divider()
    
    st.subheader("🔍 Discovery")
    search_filter = st.text_input("Search catalog", placeholder="Enter asset name...")
    
    st.divider()
    
    if st.button("🔄 Refresh Catalog", use_container_width=True):
        st.rerun()
    
    st.page_link("app.py", label="Back to Explorer", icon="🏠")

# Load datasources
response = api.list_datasources(filter=search_filter if search_filter else None)

if response.get("error"):
    st.error(f"Catalog synchronization failed: {response['error']}")
else:
    datasources = response.get("datasources", [])
    
    if not datasources:
        st.info("No data assets matching your criteria were found.")
    else:
        # Asset statistics
        col1, col2, col3 = st.columns(3)
        col1.metric("Available Assets", len(datasources))
        col2.metric("System Connections", "Live")
        col3.metric("Auto-Index Status", "Active")
        
        st.divider()
        
        # Grid layout for assets (using columns for a modern look)
        cols = st.columns(2)
        for i, ds in enumerate(datasources):
            with cols[i % 2]:
                with st.container(border=True):
                    st.markdown(f"### 📊 {ds['name']}")
                    st.caption(f"Asset ID: `{ds['id'][:12]}...` | Project: {ds.get('project_name', 'Default')}")
                    
                    if ds.get("description"):
                        st.write(ds["description"])
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("🔌 Connect & Query", key=f"q_{ds['id']}", use_container_width=True):
                            st.session_state.selected_datasource = ds['id']
                            st.switch_page("app.py")
                    with c2:
                        if st.button("📋 Inspect Schema", key=f"s_{ds['id']}", use_container_width=True):
                            # In-place expansion or modal simulation
                            metadata = api.get_datasource_metadata(ds["id"])
                            if not metadata.get("error"):
                                st.session_state[f"meta_{ds['id']}"] = metadata
                    
                    # Display metadata if requested
                    if f"meta_{ds['id']}" in st.session_state:
                        meta = st.session_state[f"meta_{ds['id']}"]
                        with st.status("Schema Details", expanded=True):
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Dims", meta.get("dimension_count", 0))
                            m2.metric("Measures", meta.get("measure_count", 0))
                            m3.metric("Total", len(meta.get("fields", [])))
                            
                            st.markdown("**Field Sample:**")
                            fields = meta.get("fields", [])[:10]
                            for f in fields:
                                st.caption(f"- {f['name']} ({f['data_type']})")
                            if len(meta.get("fields", [])) > 10:
                                st.caption(f"... and {len(meta.get('fields', [])) - 10} more")
        
st.divider()

# Proactive Tips
with st.container(border=True):
    st.markdown("### 💡 Expert Deployment Tips")
    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown("**Clarity is King**")
        st.caption("Reference specific field names from the 'Inspect Schema' view for 100% accuracy.")
    with t2:
        st.markdown("**Temporal Intelligence**")
        st.caption("Mention 'This Year', 'Q3', or 'Previous Month' for smart time-series filtering.")
    with t3:
        st.markdown("**Visualization Hints**")
        st.caption("Ask for a 'Pie chart' or 'Trend line' to influence how results are rendered.")

st.caption("Data Catalog Synchronized: Recently | Powered by Tableau Metadata API")
