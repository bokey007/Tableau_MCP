# =============================================================================
# UI Styles and Components
# =============================================================================
"""Shared UI styles and utility components for the Tableau AI Agent."""

import streamlit as st

def apply_custom_styles():
    """Apply modern, premium CSS to the Streamlit app."""
    st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Main background */
    .stApp {
        background: radial-gradient(circle at 10% 20%, rgba(26, 31, 44, 1) 0%, rgba(15, 18, 26, 1) 90%);
        color: #e2e8f0;
    }

    /* Gradient text for headers */
    .gradient-text {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
    }

    /* Glassmorphism cards */
    .glass-card {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 1rem;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }

    /* ChatGPT-inspired Chat Layout */
    .stChatMessageContainer {
        padding-bottom: 120px; /* Room for the fixed input */
    }

    /* Centered Chat Area */
    .chat-inner-container {
        max-width: 800px;
        margin: 0 auto;
    }

    /* Sleek Message Bubbles */
    .stChatMessage {
        background-color: transparent !important;
        border: none !important;
        padding: 1.5rem 0 !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
    }
    
    .stChatMessage[data-testid="stChatMessageUser"] {
        background-color: transparent !important;
    }
    
    .stChatMessage[data-testid="stChatMessageAssistant"] {
        background-color: rgba(255, 255, 255, 0.02) !important;
    }

    .stChatMessage .stMarkdown {
        font-size: 1.05rem;
        line-height: 1.6;
        color: #ececf1;
    }

    /* Floating Bottom Input Area */
    [data-testid="stChatInput"] {
        background-color: #1a1f2c !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.4) !important;
        padding: 10px !important;
        max-width: 800px !important;
        margin: 0 auto !important;
    }

    /* Fixed Header Styling */
    .fixed-top-header {
        position: sticky;
        top: 0;
        background: rgba(15, 18, 26, 0.8);
        backdrop-filter: blur(12px);
        z-index: 1000;
        padding: 1rem 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        margin-bottom: 2rem;
    }

    /* Result Card within Chat */
    .result-card {
        background: #2d3748;
        border-radius: 12px;
        padding: 1rem;
        margin-top: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }

    /* Sidebar Refinement */
    [data-testid="stSidebar"] {
        background-color: #0f121a !important;
    }

    /* Button Polish */
    .stButton > button {
        background: #3e3355 !important;
        border: none !important;
        color: white !important;
        font-weight: 500 !important;
    }
    
    .stButton > button:hover {
        background: #4e4365 !important;
    }

    /* Hide redundant elements */
    [data-testid="stHeader"] {
        background: transparent !important;
    }
</style>
""", unsafe_allow_html=True)

def render_chat_header():
    """Render a modern fixed top navigation/header similar to ChatGPT."""
    st.markdown("""
        <div class="fixed-top-header">
            <div style="max-width: 800px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; padding: 0 1rem;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.5rem;">🎯</span>
                    <span style="font-weight: 700; font-size: 1.2rem; color: #f8fafc;">Tableau Intelligence <span class="gradient-text">Agent</span></span>
                </div>
                <div style="font-size: 0.8rem; color: #94a3b8; background: rgba(255,255,255,0.05); padding: 4px 12px; border-radius: 20px;">
                    v1.5.0 • GPT-4o Powered
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

def render_centered_container_start():
    """Start a centered container for the chat flow."""
    st.markdown('<div class="chat-inner-container">', unsafe_allow_html=True)

def render_centered_container_end():
    """End the centered container."""
    st.markdown('</div>', unsafe_allow_html=True)

def render_header(title, subtitle):
    """Render a consistent header with gradient text for non-chat pages."""
    st.markdown(f"""
        <div style="margin-bottom: 2rem;">
            <h1 style="display: inline-block; margin-bottom: 0;">
                <span class="gradient-text">{title}</span>
            </h1>
            <p style="color: #94a3b8; font-size: 1.1rem; margin-top: 0.5rem;">{subtitle}</p>
        </div>
    """, unsafe_allow_html=True)

def render_card(title, content):
    """Render a glassmorphism card."""
    st.markdown(f"""
        <div class="glass-card">
            <h3 style="margin-top: 0; color: #f8fafc;">{title}</h3>
            <div>{content}</div>
        </div>
    """, unsafe_allow_html=True)
