# ============================================================
# MyTimes 6-File System — UI Components
# ============================================================
import streamlit as st
from config_styles import PREMIUM_CSS


def apply_page_config():
    st.set_page_config(
        page_title="MyTimes",
        page_icon="📘",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(PREMIUM_CSS, unsafe_allow_html=True)


def hero():
    st.markdown(
        """
        <div class="mytimes-hero">
            <div class="mytimes-kicker">Managing Your Teaching through Intelligent Matching and Equitable Scheduling</div>
            <div class="mytimes-title">MyTimes</div>
            <div class="mytimes-subtitle">
                Fair KS Distribution • Emergency Reallocation • Manual Fine Tuning • Academic Workload Optimization
            </div>
            <div class="mytimes-tag-row">
                <span class="mytimes-tag">Fair KS Distribution</span>
                <span class="mytimes-tag">Individual Min/Max KS</span>
                <span class="mytimes-tag">Emergency Log</span>
                <span class="mytimes-tag">Manual Fine Tuning</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title, note=""):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if note:
        st.markdown(f'<div class="section-note">{note}</div>', unsafe_allow_html=True)


def metric_card(label, value, note=""):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def soft_card_html(html):
    st.markdown(f'<div class="soft-card">{html}</div>', unsafe_allow_html=True)
