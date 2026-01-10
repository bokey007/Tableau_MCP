# =============================================================================
# Datasources Page
# =============================================================================
"""Browse and explore available Tableau datasources."""

import streamlit as st

# Import shared API client
import sys
sys.path.insert(0, '..')
from components.api_client import api_client as api

st.set_page_config(
    page_title="Datasources - Tableau AI Agent",
    page_icon="🗄️",
    layout="wide",
)

st.title("🗄️ Datasources")
st.caption("Browse available Tableau datasources and their schemas")


# Sidebar
with st.sidebar:
    st.subheader("🔍 Search")
    search_filter = st.text_input("Filter datasources", placeholder="Enter name...")
    
    st.divider()
    
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# Load datasources
response = api.list_datasources(filter=search_filter if search_filter else None)

if response.get("error"):
    st.error(f"Failed to load datasources: {response['error']}")
    st.info("Make sure the backend and MCP server are running.")
else:
    datasources = response.get("datasources", [])
    
    if not datasources:
        st.warning("📭 No datasources available.")
        st.info("""
        This could mean:
        - The MCP server is not connected to Tableau
        - Your Tableau credentials need to be configured
        - There are no published datasources on your Tableau site
        """)
    else:
        st.success(f"🎉 Found {len(datasources)} datasource(s)")
        
        # Datasource grid
        for ds in datasources:
            with st.expander(f"📊 {ds['name']}", expanded=False):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown(f"**ID:** `{ds['id']}`")
                    
                    if ds.get("description"):
                        st.markdown(f"**Description:** {ds['description']}")
                    else:
                        st.caption("_No description available_")
                    
                    if ds.get("project_name"):
                        st.caption(f"📁 Project: {ds['project_name']}")
                
                with col2:
                    # Quick actions
                    if st.button("🔍 Query This", key=f"query_{ds['id']}", use_container_width=True):
                        st.session_state.selected_datasource = ds['id']
                        st.session_state.selected_datasource_name = ds['name']
                        st.switch_page("app.py")
                
                # Schema section
                st.markdown("---")
                
                if st.button("📋 View Schema", key=f"schema_{ds['id']}", use_container_width=True):
                    with st.spinner("Loading schema..."):
                        metadata = api.get_datasource_metadata(ds["id"])
                        
                        if metadata.get("error"):
                            st.error(f"Failed to load schema: {metadata['error']}")
                        else:
                            # Stats
                            col1, col2, col3 = st.columns(3)
                            col1.metric("📏 Dimensions", metadata.get("dimension_count", 0))
                            col2.metric("📊 Measures", metadata.get("measure_count", 0))
                            col3.metric("📋 Total Fields", len(metadata.get("fields", [])))
                            
                            # Fields table
                            fields = metadata.get("fields", [])
                            
                            if fields:
                                # Categorize fields
                                dimensions = [f for f in fields if f.get("role") == "DIMENSION"]
                                measures = [f for f in fields if f.get("role") == "MEASURE"]
                                others = [f for f in fields if f.get("role") not in ["DIMENSION", "MEASURE"]]
                                
                                if dimensions:
                                    st.markdown("**📏 Dimensions**")
                                    for f in dimensions:
                                        desc = f" _{f['description']}_" if f.get("description") else ""
                                        st.markdown(f"- `{f['name']}` ({f['data_type']}){desc}")
                                
                                if measures:
                                    st.markdown("**📊 Measures**")
                                    for f in measures:
                                        agg = f" [{f['default_aggregation']}]" if f.get("default_aggregation") else ""
                                        desc = f" _{f['description']}_" if f.get("description") else ""
                                        st.markdown(f"- `{f['name']}` ({f['data_type']}){agg}{desc}")
                                
                                if others:
                                    with st.expander("Other Fields"):
                                        for f in others:
                                            st.markdown(f"- `{f['name']}` ({f['data_type']})")
                            else:
                                st.info("No field information available")
                            
                            # Raw schema for copying
                            with st.expander("📄 Schema Description (for AI)"):
                                st.code(metadata.get("schema_description", "N/A"))
                            
                            # Copy button for schema
                            st.markdown("---")
                            st.caption("💡 Use the schema description above when crafting complex queries")


# Tips section
st.divider()

with st.expander("💡 Tips for querying datasources"):
    st.markdown("""
    ### How to get the best results:
    
    1. **Be specific**: Instead of "show me sales", try "show total sales by region for 2024"
    
    2. **Reference field names**: Use the actual field names from the schema when possible
    
    3. **Include aggregations**: Specify SUM, AVG, COUNT when asking about measures
    
    4. **Add filters**: Mention specific values like dates, categories, or regions
    
    5. **Limit results**: Use "top 10" or "first 5" to get focused results
    
    ### Example queries:
    - "What are the top 10 customers by total sales amount?"
    - "Show me monthly revenue trends for the last 12 months"
    - "Compare sales vs profit by product category"
    - "Which regions have profit margin below 10%?"
    """)

# Footer
st.divider()
st.page_link("app.py", label="← Back to Home", icon="🏠")
