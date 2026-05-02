"""
Home page - Judgment Analysis (Main page)
This is the primary feature of LegalEase AI

CHANGE: build_judgment_result_text now returns (plain_text, structured_dict).
        render_shareable_result_box accepts the tuple directly — no other changes needed.
"""

import streamlit as st
import logging

from core.app_utils import (
    get_client,
    extract_text_from_pdf,
    compress_text,
    english_leakage_detected,
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
    parse_summary_bullets,
    validate_pdf_metadata,
)

st.markdown(RETRO_STYLING, unsafe_allow_html=True)


def render_page():
    client = get_client()

    current_language = st.session_state.get("judgment_language", "English")
    ui = get_localized_ui_text(current_language, client)

    st.title("⚡ LegalEase AI")
    st.subheader(ui["app_subtitle"])
    st.markdown(ui["app_intro"])
    st.markdown("---")

    # Input section
    language = st.selectbox("🌐 Select your language", LANGUAGES)
    uploaded_file = st.file_uploader("📄 Upload Judgment PDF", type=["pdf"])
    
    # PDF Validation for size and page count
    is_valid_pdf, validation_msg, validation_level = validate_pdf_metadata(uploaded_file)
    if validation_msg:
        if validation_level == "error":
            st.error(validation_msg)
        else:
            st.warning(validation_msg)

    st.markdown("---")

    if uploaded_file and is_valid_pdf and st.button("🚀 Generate Summary", use_container_width=True):
        with st.spinner("Processing judgment…"):
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

                summary_raw = response.choices[0].message.content.strip()
                # Use a structured parser to ensure exactly 3 bullet points 
                # and remove any introductory text
                summary = parse_summary_bullets(summary_raw)

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
                    retry_summary_raw = response2.choices[0].message.content.strip()
                    if len(retry_summary_raw) > 0 and not english_leakage_detected(retry_summary_raw):
                        summary = parse_summary_bullets(retry_summary_raw)

                if not summary:
                    st.error(ui["empty_summary"])
                else:
                    remedies = {}

                    with st.spinner(ui["remedies_spinner"]):
                        try:
                            remedies = get_remedies_advice(raw_text, language, client) or {}
                        except Exception as e:
                            st.error(f"{ui['remedies_error']}: {str(e)}")

                    # build_judgment_result_text now returns (plain_text, structured_dict)
                    result = build_judgment_result_text(summary, remedies, ui)

                    # render_shareable_result_box accepts the tuple directly
                    render_shareable_result_box(result, ui)
                    st.success(ui["summary_success"])

                    # ===== ANALYTICS & TRACKING SECTION =====
                    st.markdown("---")
                    st.markdown(f"## {ui['track_title']}")
                    st.info(ui["track_info"])

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        if st.button(ui["view_analytics"], key="view_analytics"):
                            st.session_state.show_analytics = True

                    with col2:
                        if st.button(ui["estimate_chances"], key="estimate_chances"):
                            st.session_state.show_estimator = True

                    with col3:
                        if st.button(ui["report_outcome"], key="report_outcome"):
                            st.session_state.show_feedback = True

                    if st.session_state.get("show_analytics"):
                        st.subheader(ui["quick_analytics_preview"])
                        try:
                            from analytics_engine import AnalyticsAggregator
                            from database import SessionLocal

                            db = SessionLocal()
                            summary_data = AnalyticsAggregator.get_dashboard_summary(db)

                            if summary_data.get("total_cases_processed", 0) > 0:
                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric(ui["total_cases_tracked"], summary_data["total_cases_processed"])
                                with col2:
                                    trends = AnalyticsAggregator.get_regional_trends(db)
                                    success_rate = trends[0]['appeal_success_rate'] if trends else 'N/A'
                                    st.metric(ui["appeals_success_rate"], f"{success_rate}%")
                                with col3:
                                    st.metric(ui["appeals_filed"], summary_data.get("appeals_filed", 0))
                                st.write(f"📌 **{ui['analytics_link_text']}**")
                            else:
                                st.info(ui["analytics_empty"])

                            db.close()
                        except Exception as e:
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