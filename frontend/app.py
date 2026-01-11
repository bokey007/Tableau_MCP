# =============================================================================
# Streamlit Main Application
# =============================================================================
"""
Tableau MCP AI Agent - Streamlit Frontend

A modern, interactive UI for querying Tableau data using natural language.
"""

import streamlit as st
from datetime import datetime

# Import shared API client
from components.api_client import api_client as api

# Page config
st.set_page_config(
    page_title="Tableau AI Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    
    /* Response container */
    .response-container {
        background: linear-gradient(135deg, #1a1f2c 0%, #2d3748 100%);
        border-radius: 1rem;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #667eea;
    }
    
    /* Success/Error messages */
    .stSuccess, .stError, .stWarning, .stInfo {
        border-radius: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Session State Initialization
# =============================================================================

if "username" not in st.session_state:
    st.session_state.username = "default_user"
if "query_history" not in st.session_state:
    st.session_state.query_history = []
if "current_query_id" not in st.session_state:
    st.session_state.current_query_id = None
if "current_result" not in st.session_state:
    st.session_state.current_result = None
if "feedback_given" not in st.session_state:
    st.session_state.feedback_given = False
if "selected_datasource" not in st.session_state:
    st.session_state.selected_datasource = None
# LangGraph conversation thread
if "thread_id" not in st.session_state:
    import uuid
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []  # Chat history for display


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    # Logo/Title
    st.markdown("# 🎯 Tableau AI")
    st.caption("Intelligent Data Analysis")
    
    st.divider()
    
    # User identification
    st.subheader("👤 User")
    username = st.text_input(
        "Username", 
        value=st.session_state.username, 
        key="username_input",
        help="Enter your username to track your queries"
    )
    if username != st.session_state.username:
        st.session_state.username = username
    
    st.divider()
    
    # Health status
    st.subheader("🔌 Status")
    health = api.health_check()
    
    if health.get("status") == "healthy":
        st.success("✅ All Systems Go")
        with st.expander("Details"):
            st.caption(f"🗄️ Database: {'✅' if health.get('database_connected') else '❌'}")
            st.caption(f"🔗 MCP: {'✅' if health.get('mcp_connected') else '❌'}")
            st.caption(f"🤖 AI Config: {'✅' if health.get('checks', {}).get('openai_configured') else '❌'}")
    elif health.get("status") == "degraded":
        st.warning("⚠️ Degraded Mode")
        with st.expander("Details"):
            if not health.get("mcp_connected"):
                st.caption("❌ MCP server not connected")
            if not health.get("checks", {}).get("openai_configured"):
                st.caption("❌ OpenAI not configured")
    else:
        st.error("❌ Backend Unavailable")
        st.caption(health.get("error", "Check if backend is running"))
    
    st.divider()
    
    # Conversation controls
    st.subheader("💬 Conversation")
    st.caption(f"Thread: `{st.session_state.thread_id[:8]}...`")
    st.caption(f"Messages: {len(st.session_state.messages)}")
    
    if st.button("🔄 New Conversation", use_container_width=True):
        import uuid
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.current_result = None
        st.session_state.feedback_given = False
        st.rerun()
    
    st.divider()
    
    # Navigation
    st.subheader("📍 Navigation")
    st.page_link("app.py", label="Home", icon="🏠")
    st.page_link("pages/history.py", label="Query History", icon="📜")
    st.page_link("pages/analytics.py", label="Analytics", icon="📊")
    st.page_link("pages/datasources.py", label="Datasources", icon="🗄️")
    
    st.divider()
    
    # Footer
    st.caption("v1.0.0 | Powered by LangGraph")


# =============================================================================
# Main Content
# =============================================================================

# Header
st.title("📊 Ask Your Data")
st.caption("Use natural language to query and analyze your Tableau data")

# Datasource selector
st.subheader("1️⃣ Select Datasource (Optional)")

datasources_response = api.list_datasources()
datasources = datasources_response.get("datasources", [])

if datasources_response.get("error"):
    st.warning(f"⚠️ Could not load datasources: {datasources_response.get('error')}")
    st.info("You can still ask questions - the agent will try to auto-detect the right datasource.")
    selected_datasource_id = None
elif datasources:
    ds_options = ["🔍 Auto-detect (recommended)"] + [f"📊 {ds['name']}" for ds in datasources]
    ds_ids = [None] + [ds["id"] for ds in datasources]
    
    # Check if we have a pre-selected datasource from datasources page
    default_idx = 0
    if st.session_state.selected_datasource:
        try:
            default_idx = ds_ids.index(st.session_state.selected_datasource)
        except ValueError:
            default_idx = 0
    
    selected_idx = st.selectbox(
        "Choose a datasource or let AI auto-detect",
        range(len(ds_options)),
        index=default_idx,
        format_func=lambda x: ds_options[x],
        help="Auto-detect works best when your question references specific data concepts"
    )
    selected_datasource_id = ds_ids[selected_idx]
else:
    st.info("📭 No datasources available. Check your Tableau connection.")
    selected_datasource_id = None

st.divider()

# Query input
st.subheader("2️⃣ Ask Your Question")

question = st.text_area(
    "Enter your question about the data",
    placeholder="Examples:\n• What are the top 5 customers by total sales?\n• Show me monthly revenue trends for 2024\n• Which products have the highest profit margin?",
    height=120,
    key="question_input",
)

# Submit button
col1, col2, col3 = st.columns([1, 1, 3])
with col1:
    submit = st.button("🚀 Ask", type="primary", use_container_width=True, disabled=not question)
with col2:
    clear = st.button("🗑️ Clear", use_container_width=True)

if clear:
    st.session_state.current_result = None
    st.session_state.current_query_id = None
    st.session_state.feedback_given = False
    st.session_state.selected_datasource = None
    st.rerun()

# Process query
if submit and question:
    if len(question.strip()) < 3:
        st.error("❌ Question is too short. Please be more specific.")
    else:
        st.session_state.feedback_given = False
        
        # Add user message to chat history
        st.session_state.messages.append({
            "role": "user",
            "content": question,
            "timestamp": datetime.now().isoformat(),
        })
        
        with st.spinner("🤖 Analyzing your question..."):
            result = api.query(
                question=question,
                datasource_id=selected_datasource_id,
                username=st.session_state.username,
                thread_id=st.session_state.thread_id,  # LangGraph native memory
            )
            
            st.session_state.current_result = result
            st.session_state.current_query_id = result.get("query_id")
            
            # Add assistant message to chat history
            if result.get("success"):
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result.get("analysis", "No analysis available"),
                    "timestamp": datetime.now().isoformat(),
                    "query_id": result.get("query_id"),
                    "has_data": bool(result.get("results")),
                })
            else:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"❌ Error: {result.get('error', 'Unknown error')}",
                    "timestamp": datetime.now().isoformat(),
                    "is_error": True,
                })
            
            # Add to local history (for sidebar)
            st.session_state.query_history.insert(0, {
                "question": question,
                "query_id": result.get("query_id"),
                "success": result.get("success"),
                "timestamp": datetime.now().isoformat(),
            })

# Display conversation history (show all but latest exchange)
if len(st.session_state.messages) > 2:
    st.divider()
    st.subheader("💬 Conversation History")
    
    # Show previous messages (excluding the latest pair)
    for i, msg in enumerate(st.session_state.messages[:-2]):
        if msg["role"] == "user":
            st.markdown(f"**🧑 You:** {msg['content']}")
        else:
            # Truncate long assistant messages
            content = msg['content']
            if len(content) > 300:
                content = content[:300] + "..."
            st.markdown(f"**🤖 Assistant:** {content}")
    
    st.caption(f"Showing {len(st.session_state.messages) - 2} previous messages")

# Display results
if st.session_state.current_result:
    result = st.session_state.current_result
    
    st.divider()
    st.subheader("3️⃣ Results")
    
    if result.get("success"):
        # Analysis
        st.markdown("### 💡 Analysis")
        analysis_text = result.get('analysis', 'No analysis available.')
        st.markdown(analysis_text)
        
        # Execution info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            row_count = result.get("results", {}).get("row_count", 0) if result.get("results") else 0
            st.metric("📊 Rows", row_count)
        with col2:
            exec_time = result.get("execution_time_ms", 0)
            st.metric("⏱️ Time", f"{exec_time:.0f}ms" if exec_time else "N/A")
        with col3:
            datasource = result.get("datasource", {})
            ds_name = datasource.get("name", "Auto-detected")[:20] if datasource else "N/A"
            st.metric("🗄️ Datasource", ds_name)
        with col4:
            query_id = result.get("query_id", "N/A")
            st.metric("🔑 Query ID", query_id[:8] + "..." if query_id and len(query_id) > 8 else query_id)
        
        # Data table
        if result.get("results") and result["results"].get("data"):
            st.markdown("### 📋 Data")
            import pandas as pd
            
            df = pd.DataFrame(result["results"]["data"])
            st.dataframe(df, use_container_width=True, height=400)
            
            # Download button
            col1, col2 = st.columns([1, 4])
            with col1:
                csv = df.to_csv(index=False)
                st.download_button(
                    "📥 Download CSV",
                    csv,
                    "query_results.csv",
                    "text/csv",
                    use_container_width=True,
                )
        
        # Visualization rendering
        if result.get("visualization") and result["visualization"].get("chart_type") not in [None, "none", "table"]:
            viz = result["visualization"]
            st.markdown("### 📈 Visualization")
            
            # Only render if we have data
            if result.get("results") and result["results"].get("data"):
                import plotly.express as px
                
                chart_type = viz.get("chart_type", "bar")
                x_axis = viz.get("x_axis")
                y_axis = viz.get("y_axis")
                
                # Validate axes exist in data
                columns = list(df.columns)
                
                # Find best matching columns if exact match not found
                def find_column(target, cols):
                    if not target:
                        return None
                    target_lower = target.lower()
                    for col in cols:
                        if col.lower() == target_lower:
                            return col
                    for col in cols:
                        if target_lower in col.lower() or col.lower() in target_lower:
                            return col
                    return None
                
                x_col = find_column(x_axis, columns)
                y_col = find_column(y_axis, columns)
                
                # Fallback: use first string column as x, first numeric as y
                if not x_col or not y_col:
                    for col in columns:
                        if df[col].dtype == 'object' and not x_col:
                            x_col = col
                        elif df[col].dtype in ['int64', 'float64'] and not y_col:
                            y_col = col
                
                try:
                    fig = None
                    plot_df = df.copy()
                    
                    # For line charts with time series, aggregate the data
                    if chart_type == "line" and x_col and y_col:
                        # Check if x_col looks like a date
                        try:
                            plot_df[x_col] = pd.to_datetime(plot_df[x_col])
                            # Aggregate by date - sum the y values
                            plot_df = plot_df.groupby(x_col)[y_col].sum().reset_index()
                            plot_df = plot_df.sort_values(x_col)
                        except:
                            pass  # Not a date column, proceed as-is
                        
                        fig = px.line(
                            plot_df, x=x_col, y=y_col,
                            title=f"{y_col} over {x_col}",
                            markers=True,
                            color_discrete_sequence=["#667eea"]
                        )
                    elif chart_type == "bar" and x_col and y_col:
                        # For bar charts, aggregate if there are duplicates in x
                        if plot_df[x_col].duplicated().any():
                            plot_df = plot_df.groupby(x_col)[y_col].sum().reset_index()
                            plot_df = plot_df.sort_values(y_col, ascending=False).head(20)  # Top 20
                        
                        fig = px.bar(
                            plot_df, x=x_col, y=y_col,
                            title=f"{y_col} by {x_col}",
                            color_discrete_sequence=["#667eea"]
                        )
                    elif chart_type == "scatter" and x_col and y_col:
                        fig = px.scatter(
                            plot_df, x=x_col, y=y_col,
                            title=f"{y_col} vs {x_col}",
                            color_discrete_sequence=["#667eea"]
                        )
                    elif chart_type == "pie" and x_col and y_col:
                        # Aggregate for pie charts
                        plot_df = plot_df.groupby(x_col)[y_col].sum().reset_index()
                        plot_df = plot_df.nlargest(10, y_col)  # Top 10 for readability
                        
                        fig = px.pie(
                            plot_df, names=x_col, values=y_col,
                            title=f"Distribution of {y_col} by {x_col}"
                        )
                    elif x_col and y_col:
                        # Default to bar chart with aggregation
                        if plot_df[x_col].duplicated().any():
                            plot_df = plot_df.groupby(x_col)[y_col].sum().reset_index()
                            plot_df = plot_df.sort_values(y_col, ascending=False).head(20)
                        
                        fig = px.bar(
                            plot_df, x=x_col, y=y_col,
                            title=f"{y_col} by {x_col}",
                            color_discrete_sequence=["#667eea"]
                        )
                    
                    if fig:
                        # Apply dark theme styling
                        fig.update_layout(
                            template="plotly_dark",
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#e2e8f0"),
                            title_font_size=16,
                            margin=dict(t=50, l=50, r=50, b=50),
                            xaxis_title=x_col,
                            yaxis_title=y_col,
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        
                        # Show chart info
                        st.caption(f"💡 {viz.get('reason', 'Auto-generated visualization')}")
                    else:
                        st.info(f"📊 Recommended: {chart_type.title()} chart with {x_col} and {y_col}")
                        
                except Exception as e:
                    st.warning(f"Could not render {chart_type} chart: {str(e)}")
                    st.info(f"📊 Recommended: {chart_type.title()} chart | X: {x_axis} | Y: {y_axis}")
            else:
                st.info(f"📊 Recommended: {viz.get('chart_type', 'table').title()} chart")
        
        # Debug Panel (collapsible)
        with st.expander("🔧 Debug Information", expanded=False):
            st.markdown("#### Generated VizQL Query")
            if result.get("query"):
                import json
                st.code(json.dumps(result["query"], indent=2), language="json")
            else:
                st.caption("No query generated")
            
            st.markdown("#### Data Analysis Details")
            if result.get("analyzed_data"):
                analyzed = result["analyzed_data"]
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Original Rows", analyzed.get("original_row_count", "N/A"))
                with col2:
                    st.metric("Analyzed Rows", analyzed.get("row_count", "N/A"))
                
                st.caption(f"📊 {analyzed.get('description', 'No description')}")
                
                st.markdown("**Data the LLM Analyzed:**")
                if analyzed.get("data"):
                    import pandas as pd
                    analyzed_df = pd.DataFrame(analyzed["data"])
                    st.dataframe(analyzed_df, use_container_width=True)
            else:
                st.caption("No analyzed data available (pre-aggregation may have been skipped)")
            
            # Additional debug info
            st.markdown("#### Response Details")
            st.json({
                "query_id": result.get("query_id"),
                "datasource": result.get("datasource"),
                "execution_time_ms": result.get("execution_time_ms"),
                "raw_row_count": result.get("results", {}).get("row_count") if result.get("results") else None,
            })
        
        # Feedback section
        st.divider()
        st.markdown("### 👍 Was this helpful?")
        
        if not st.session_state.feedback_given:
            col1, col2, col3 = st.columns([1, 1, 4])
            
            with col1:
                if st.button("👍 Yes", key="like_btn", use_container_width=True):
                    response = api.submit_feedback(
                        query_id=st.session_state.current_query_id,
                        feedback_type="like",
                        username=st.session_state.username,
                    )
                    if not response.get("error"):
                        st.session_state.feedback_given = True
                        st.success("Thanks for your feedback! 🎉")
                        st.rerun()
                    else:
                        st.error(response["error"])
            
            with col2:
                if st.button("👎 No", key="dislike_btn", use_container_width=True):
                    response = api.submit_feedback(
                        query_id=st.session_state.current_query_id,
                        feedback_type="dislike",
                        username=st.session_state.username,
                    )
                    if not response.get("error"):
                        st.session_state.feedback_given = True
                        st.warning("Thanks for letting us know! 🔧")
                        st.rerun()
                    else:
                        st.error(response["error"])
            
            # Detailed feedback
            with st.expander("📝 Provide detailed feedback"):
                rating = st.slider("Overall rating", 1, 5, 3)
                comment = st.text_area("Comments (optional)", placeholder="Tell us how we can improve...")
                
                if st.button("Submit Detailed Feedback"):
                    response = api.submit_feedback(
                        query_id=st.session_state.current_query_id,
                        feedback_type="like" if rating >= 3 else "dislike",
                        rating=rating,
                        comment=comment,
                        username=st.session_state.username,
                    )
                    if not response.get("error"):
                        st.session_state.feedback_given = True
                        st.success("Thank you for your detailed feedback! 🙏")
                        st.rerun()
                    else:
                        st.error(response["error"])
        else:
            st.success("✅ Feedback recorded. Thank you!")
    
    else:
        # Error display
        error_msg = result.get('error', 'Unknown error occurred')
        error_type = result.get('error_type', 'unknown')
        
        st.error(f"❌ Query failed: {error_msg}")
        
        # Provide helpful suggestions based on error type
        if error_type == "configuration_error":
            st.info("""
            **Configuration Issue**
            - The AI service needs to be configured by an administrator
            - Please contact support if this issue persists
            """)
        elif error_type == "connection_error":
            st.info("""
            **Connection Issue**
            - The data service is temporarily unavailable
            - Please try again in a few moments
            """)
        elif error_type == "ai_error":
            st.info("""
            **AI Service Unavailable**
            - The AI service is temporarily busy
            - Please try again in a moment
            """)
        else:
            st.info("""
            **Troubleshooting tips:**
            - Make sure your question is clear and specific
            - Try selecting a specific datasource instead of auto-detect
            - Check if the backend and MCP server are running
            """)
        
        # Still allow feedback on failures
        if st.session_state.current_query_id and not st.session_state.feedback_given:
            if st.button("📝 Report this issue"):
                response = api.submit_feedback(
                    query_id=st.session_state.current_query_id,
                    feedback_type="dislike",
                    comment=f"Query failed: {error_msg}",
                    username=st.session_state.username,
                )
                if not response.get("error"):
                    st.session_state.feedback_given = True
                    st.info("Issue reported. Thank you for helping us improve!")


# =============================================================================
# Footer
# =============================================================================

st.divider()
st.caption("© 2024 Tableau MCP AI Agent | Powered by LangGraph & OpenAI")
