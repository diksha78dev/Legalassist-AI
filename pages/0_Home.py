"""
Home page - Judgment Analysis (Main page)
This is the primary feature of LegalEase AI
"""

import streamlit as st
import logging

st.set_page_config(
    page_title="LegalEase AI — Judgment Simplifier",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from core.app_utils import (
    get_client,
    extract_text_from_pdf,
    compress_text,
    output_language_mismatch_detected,
    build_prompt,
    build_retry_prompt,
    get_remedies_advice,
    extract_appeal_info,
    get_localized_ui_text,
    localize_yes_no,
    build_judgment_result_text,
    render_shareable_result_box,
    RETRO_STYLING,
    LANGUAGES,
)

st.markdown(RETRO_STYLING, unsafe_allow_html=True)

# FIX: DevTools revealed the winning rule is:
#   .st-emotion-cache-za2i0z h1 { font-size: 2.75rem }
# We cannot hardcode that hash (it changes between Streamlit versions/builds).
# Solution: use st.markdown() to inject a completely custom <div> that is NOT
# an <h1> at all — Streamlit's h1 rules never touch it. We style it ourselves
# with clamp() so it scales with viewport width.
# subheader (h2) has the same problem, so we replace that too.

MOBILE_HEADER_CSS = """
<style>
  .app-title {
    font-size: clamp(1.0rem, 5.5vw, 1.5rem);
    font-weight: 700;
    line-height: 1.2;
    margin: 0.4rem 0 0.1rem;
    color: inherit;
    white-space: nowrap;
  }
  .app-subtitle {
    font-size: clamp(0.85rem, 3.8vw, 1.25rem);
    font-weight: 600;
    line-height: 1.3;
    margin: 0.2rem 0 0.6rem;
    color: inherit;
    white-space: nowrap;
  }
  /* Samsung Galaxy S and similarly narrow devices (360px) */
  @media (max-width: 380px) {
    .app-title    { font-size: 1.05rem !important; }
    .app-subtitle { font-size: 0.85rem !important; }
    /* Reduce Streamlit's default side padding to reclaim horizontal space */
    .block-container,
    div[data-testid="stAppViewBlockContainer"] {
      padding-left: 0.6rem !important;
      padding-right: 0.6rem !important;
    }
  }
  @media (max-width: 340px) {
    .app-title    { font-size: 0.95rem !important; white-space: normal; word-break: keep-all; }
    .app-subtitle { font-size: 0.8rem  !important; white-space: normal; word-break: keep-all; }
  }
</style>
"""


def render_page():
    client = get_client()

    current_language = st.session_state.get("judgment_language", "English")
    ui = get_localized_ui_text(current_language, client)

    # Inject CSS once
    st.markdown(MOBILE_HEADER_CSS, unsafe_allow_html=True)

    # Custom title + subtitle — plain divs, Streamlit h1/h2 rules never apply
    st.markdown(
        f'<div class="app-title">⚡ LegalEase AI</div>'
        f'<div class="app-subtitle">{ui["app_subtitle"]}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(ui["app_intro"])
    st.markdown("---")

    language = st.selectbox(ui["language_label"], LANGUAGES, key="judgment_language")
    ui = get_localized_ui_text(language, client)

    # Re-render subtitle in selected language if it changed
    if language != current_language:
        st.markdown(
            f'<div class="app-subtitle">{ui["app_subtitle"]}</div>',
            unsafe_allow_html=True,
        )

    uploaded_file = st.file_uploader(ui["upload_label"], type=["pdf"])
    st.markdown("---")

    if uploaded_file and st.button(ui["generate_summary"], use_container_width=True):
        with st.spinner(ui["processing"]):
            try:
                try:
                    client = get_client()
                    ui = get_localized_ui_text(language, client)
                except Exception as e:
                    st.error(f"❌ {ui['api_client_failed']}: {str(e)}")
                    return

                raw_text = extract_text_from_pdf(uploaded_file)
                safe_text = compress_text(raw_text)

                prompt = build_prompt(safe_text, language)
                model_id = "meta-llama/llama-3.1-8b-instruct"

                response = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": f"You are an expert legal simplification engine. Output only in {language}."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=280,
                    temperature=0.05,
                )

                summary = response.choices[0].message.content.strip()

                if language.lower() != "english" and output_language_mismatch_detected(summary, language):
                    retry_prompt = build_retry_prompt(safe_text, language)
                    response2 = client.chat.completions.create(
                        model=model_id,
                        messages=[
                            {"role": "system", "content": f"Strict multilingual rewriting engine. Output only in {language}."},
                            {"role": "user", "content": retry_prompt},
                        ],
                        max_tokens=260,
                        temperature=0.03,
                    )
                    retry_summary = response2.choices[0].message.content.strip()
                    if len(retry_summary) > 0 and not output_language_mismatch_detected(retry_summary, language):
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

                    result = build_judgment_result_text(summary, remedies, ui)
                    render_shareable_result_box(result, ui)
                    st.success(ui["summary_success"])

                    st.markdown("---")
                    st.markdown(f"## {ui['track_title']}")
                    st.info(ui["track_info"])

                    if st.button(ui["view_analytics"], key="view_analytics", use_container_width=True):
                        st.session_state.show_analytics = True
                    if st.button(ui["estimate_chances"], key="estimate_chances", use_container_width=True):
                        st.session_state.show_estimator = True
                    if st.button(ui["report_outcome"], key="report_outcome", use_container_width=True):
                        st.session_state.show_feedback = True

                    if st.session_state.get("show_analytics"):
                        st.subheader(ui["quick_analytics_preview"])
                        try:
                            from analytics_engine import AnalyticsAggregator
                            from database import SessionLocal

                            db = SessionLocal()
                            summary_data = AnalyticsAggregator.get_dashboard_summary(db)

                            if summary_data.get("total_cases_processed", 0) > 0:
                                st.metric(ui["total_cases_tracked"], summary_data["total_cases_processed"])
                                trends = AnalyticsAggregator.get_regional_trends(db)
                                success_rate = trends[0]['appeal_success_rate'] if trends else 'N/A'
                                st.metric(ui["appeals_success_rate"], f"{success_rate}%")
                                st.metric(ui["appeals_filed"], summary_data.get("appeals_filed", 0))
                                st.write(f"📌 **{ui['analytics_link_text']}**")
                            else:
                                st.info(ui["analytics_empty"])

                            db.close()
                        except Exception:
                            st.info(ui["analytics_not_ready"])

            except Exception as e:
                err = str(e)
                if "402" in err or "credits" in err.lower():
                    st.error(ui["not_enough_credits"])
                else:
                    st.error(ui["generic_error"].format(error=err))
                    logging.error(f"Error in judgment analysis: {err}")


if __name__ == "__main__":
    render_page()