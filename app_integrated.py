"""
LegalEase AI - Main Application Entry Point
Streamlit multi-page app with deadline notification system.

Run with: streamlit run app_integrated.py
"""

import streamlit as st
import logging
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==================== CONFIGURATION ====================
# FIX: layout="centered" for mobile-first users; sidebar collapsed so it
#      doesn't cover the screen on first load on narrow viewports.
st.set_page_config(
    page_title="LegalEase AI",
    page_icon="⚖",
    layout="centered",                 # was "wide" — broke mobile layouts
    initial_sidebar_state="collapsed", # was "expanded" — blocked mobile screen
)

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== DATABASE & SCHEDULER SETUP ====================
from database import init_db
from scheduler import start_scheduler

# Initialize database
try:
    init_db()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database: {str(e)}")

# ==================== Logging Setup ====================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# ==================== Import UI Modules ====================
try:
    from notifications_ui import (
        page_notification_preferences,
        page_manage_deadlines,
        page_notification_history,
    )
    # Import original app components
        get_client,
        get_remedies_advice,
        get_default_model,
        validate_pdf_metadata,
    )
    import core
    client = None
    all_features_available = True
except ImportError as e:
    logging.error(f"Failed to import UI modules: {e}")
    all_features_available = False
    client = None


# ==================== Main UI ====================
def main():
    # Sidebar navigation
    st.sidebar.markdown("# ⚖️ LegalEase AI")
    st.sidebar.markdown("**Convert Judgments to Simple Language**")
    st.sidebar.divider()
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        **Need Help?**
        - 📞 National Legal Services: 1800-180-8111
        - 🌐 nalsa.gov.in
        """
    )

    if all_features_available:
        page_options = [
            "Judgment Analysis",
            "Case Deadlines",
            "Notification History",
            "Preferences",
        ]
    else:
        page_options = ["Judgment Analysis"]
        st.sidebar.warning("Some modules failed to load. Showing Judgment Analysis only.")

    page = st.sidebar.radio("Navigate", page_options)
    
    # Route to appropriate page
    if page == "Judgment Analysis":
        show_judgment_analysis()
    elif page == "Case Deadlines":
        page_manage_deadlines()
    elif page == "Notification History":
        page_notification_history()
    elif page == "Preferences":
        page_notification_preferences()


def show_judgment_analysis():
    """Original app UI for judgment analysis"""
    
    st.markdown("""
    <style>
        .main {
            background-color: #0d0d0f;
        }
        .stButton>button {
            background: linear-gradient(90deg, #2d2dff, #8a2be2);
            border-radius: 8px;
            color: white;
            font-weight: 600;
            border: none;
            padding: 0.6rem 1.2rem;
        }
    </style>
    """, unsafe_allow_html=True)
    
    from app import get_client
    client = get_client()
    
    current_language = st.session_state.get("integrated_judgment_language", "English")
    ui = core.get_localized_ui_text(current_language, client)

    st.title("⚡ LegalEase AI")
    st.subheader(ui["app_subtitle"])

    st.markdown(ui["app_intro"])
    st.markdown("---")

    language = st.selectbox(ui["language_label"], core.LANGUAGES, key="integrated_judgment_language")
    ui = core.get_localized_ui_text(language, client)
    input_method = st.radio(
        ui["input_method"],
        [ui["upload_pdf"], ui["paste_text"]],
        horizontal=True,
    )

    is_valid_input = False
    uploaded_file = None
    pasted_text = None

    if input_method == ui["upload_pdf"]:
        uploaded_file = st.file_uploader(ui["upload_label"], type=["pdf"])
        if uploaded_file:
            is_valid_input = True
    else:
        pasted_text = st.text_area(
            ui.get("paste_text", "📋 Paste Text"),
            height=250,
        )
        if pasted_text and pasted_text.strip():
            is_valid_input = True

    st.markdown("---")

    if st.button(ui["generate_summary"], use_container_width=True):
        if not is_valid_input:
            st.error("Please upload a PDF or paste the judgment text to continue.")
        else:
            with st.spinner(ui["processing"]):
                try:
                    if not client:
                        st.error(f"❌ {ui['openrouter_not_configured']}")
                        return
                    ui = core.get_localized_ui_text(language, client)

                    if input_method == ui["upload_pdf"]:
                        raw_text = core.extract_text_from_pdf(uploaded_file)
                    else:
                        raw_text = pasted_text
                    
                    safe_text = core.compress_text(raw_text)

                    prompt = core.build_summary_prompt(safe_text, language)

                    # First attempt
                    response = client.chat.completions.create(
                        model=get_default_model(),
                        messages=[
                            {"role": "system", "content": f"You are an expert legal simplification engine. Output only in {language}."},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=280,
                        temperature=0.05,
                    )

                    summary = response.choices[0].message.content.strip()

                    # Retry if output is not in the selected language
                    if language.lower() != "english" and core.output_language_mismatch_detected(summary, language):
                        retry_prompt = core.build_retry_prompt(safe_text, language)
                        response2 = client.chat.completions.create(
                            model=get_default_model(),
                            messages=[
                                {"role": "system", "content": f"Strict multilingual rewriting engine. Output only in {language}."},
                                {"role": "user", "content": retry_prompt}
                            ],
                            max_tokens=260,
                            temperature=0.03,
                        )
                        retry_summary = response2.choices[0].message.content.strip()
                        if len(retry_summary) > 0 and not core.output_language_mismatch_detected(retry_summary, language):
                            summary = retry_summary

                    if not summary:
                        st.error(ui["empty_summary"])
                    else:
                        remedies = {}
                    
                        with st.spinner(ui["remedies_spinner"]):
                            try:
                                remedies = get_remedies_advice(raw_text, language, client) or {}
                            except Exception as e:
                                st.error(f"{ui['remedies_error']}: {str(e)}")

                        result_text = core.build_judgment_result_text(summary, remedies, ui)
                        core.render_shareable_result_box(result_text, ui)
                        st.success(ui["summary_success"])
                    
                except Exception as e:
                    err = str(e)
                    logger.error(f"Full error in judgment analysis: {err}", exc_info=True)
                    if "402" in err or "credits" in err.lower():
                        st.error(ui["not_enough_credits"])
                    elif "Connection" in err or "timeout" in err.lower():
                        st.error(ui["connection_error"].format(error=err))
                    else:
                        st.error(ui["generic_error"].format(error=err))


if __name__ == "__main__":
    main()