import streamlit as st
from openai import OpenAI
import PyPDF2
import re
import time

# -----------------------------
# App Config
# -----------------------------
st.set_page_config(
    page_title="LegalEase AI",
    page_icon="⚖",
    layout="centered"
)

# -----------------------------
# Load API Keys (OpenRouter)
# -----------------------------
client = OpenAI(
    api_key=st.secrets["OPENROUTER_API_KEY"],
    base_url=st.secrets["OPENROUTER_BASE_URL"]
)

# -----------------------------
# Retro Styling
# -----------------------------
st.markdown("""
<style>
    body {
        background-color: #0d0d0f;
        color: #e0e0e0;
        font-family: 'Inter', sans-serif;
    }
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
    .stSelectbox>div>div {
        background-color: #1a1a1d;
        color: #e0e0e0;
        border-radius: 6px;
    }
    .stTextArea>div>textarea {
        background-color: #121214;
        color: #e0e0e0;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------
# Helper: PDF to text
# -----------------------------
def extract_text_from_pdf(uploaded_pdf):
    reader = PyPDF2.PdfReader(uploaded_pdf)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text

# -----------------------------
# Compress text for token safety
# -----------------------------
def compress_text(text, limit=6000):
    if len(text) <= limit:
        return text
    head = text[:3000]
    tail = text[-3000:]
    return head + "\n\n... [TRUNCATED] ...\n\n" + tail

# -----------------------------
# Detect English leakage
# -----------------------------
def english_leakage_detected(output_text, threshold=5):
    common = [" the ", " and ", " of ", " to ", " in ", " is ", " that ", " it ", " for ", " on "]
    text_lower = " " + output_text.lower() + " "
    count = sum(1 for w in common if w in text_lower)
    return count >= threshold

# -----------------------------
# Build prompts
# -----------------------------
def build_prompt(safe_text, language):
    return f"""
You are LegalEase AI — an expert judicial-simplification and translation engine.

MISSION:
Convert the judgment text into a simple, citizen-friendly summary.

INSTRUCTIONS:
1. Extract ONLY the final judgment outcome.
2. Remove all legal jargon and case history.
3. Produce EXACTLY 3 bullet points.
4. Write ONLY in {language}. ZERO English allowed if language ≠ English.
5. Each bullet must be 1–2 very short sentences.
6. No extra headings. No disclaimers.

TEXT TO ANALYZE:
{safe_text}

OUTPUT REQUIRED:
- 3 bullet points in {language} only
"""

def build_retry_prompt(safe_text, language):
    return f"""
Your previous answer included English. Now STRICTLY produce the answer ONLY in {language}.

REQUIREMENTS:
- Exactly 3 bullet points
- VERY simple {language}
- No English at all
- No introductions, headings, or explanations

TEXT:
{safe_text}

OUTPUT NOW:
3 bullet points in {language} only.
"""

# -----------------------------
# Remedies Advisor Functions
# -----------------------------

def build_remedies_prompt(judgment_text, language):
    """
    Ask LLM to analyze what remedies are available
    based on the actual judgment content
    """
    return f"""
You are a Legal Rights Advisor. Read this judgment and answer these questions:

JUDGMENT:
{judgment_text}

Answer ONLY these questions in {language}. Be practical and direct.

1. WHAT HAPPENED?
   - Who won and who lost? (1 sentence)

2. CAN THE LOSER APPEAL?
   - Yes or No? Why/Why not? (1-2 sentences)

3. IF YES TO APPEAL:
   - How many days do they have? (Just the number)
   - Which court should they go to? (Court name only)
   - Rough cost in rupees? (e.g., 5000-15000)

4. WHAT SHOULD THEY DO FIRST?
   - What is the first action to take? (1 sentence)

5. IMPORTANT DATES:
   - What deadline should they remember? (1 sentence)

Format your answer clearly with each question number and answer.
"""


def parse_remedies_response(response_text):
    """
    Extract structured info from LLM response
    """
    remedies = {
        "what_happened": "",
        "can_appeal": "",
        "appeal_days": "",
        "appeal_court": "",
        "cost": "",
        "first_action": "",
        "deadline": ""
    }
    
    lines = response_text.split("\n")
    current_section = None
    current_answer = ""
    
    for line in lines:
        # Detect question headers
        if "1. WHAT HAPPENED" in line or "1. What happened" in line:
            if current_section and current_answer:
                remedies[current_section] = current_answer.strip()
            current_section = "what_happened"
            current_answer = ""
        elif "2. CAN THE LOSER" in line or "2. Can the" in line:
            if current_section and current_answer:
                remedies[current_section] = current_answer.strip()
            current_section = "can_appeal"
            current_answer = ""
        elif "3. IF YES" in line:
            if current_section and current_answer:
                remedies[current_section] = current_answer.strip()
            current_section = "appeal_details"
            current_answer = ""
        elif "4. WHAT SHOULD" in line:
            if current_section and current_answer:
                remedies[current_section] = current_answer.strip()
            current_section = "first_action"
            current_answer = ""
        elif "5. IMPORTANT" in line:
            if current_section and current_answer:
                remedies[current_section] = current_answer.strip()
            current_section = "deadline"
            current_answer = ""
        else:
            # Collect answer text
            if current_section and line.strip():
                current_answer += line + " "
    
    # Save last section
    if current_section and current_answer:
        remedies[current_section] = current_answer.strip()
    
    return remedies


def get_remedies_advice(judgment_text, language):
    """
    Call LLM to get remedies for this judgment
    """
    prompt = build_remedies_prompt(judgment_text, language)
    
    response = client.chat.completions.create(
        model="meta-llama/llama-3.1-8b-instruct",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful legal advisor. Answer questions about legal remedies in India."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        max_tokens=500,  # Longer for detailed answers
        temperature=0.1,  # Low temp = more consistent
    )
    
    response_text = response.choices[0].message.content.strip()
    remedies = parse_remedies_response(response_text)
    
    return remedies

# -----------------------------
# UI
# -----------------------------
st.title("⚡ LegalEase AI")
st.subheader("Legal Judgment Simplifier")

st.markdown("""
LegalEase AI breaks the Information Barrier in the Judiciary by converting
complex court judgments into clear, 3-point summaries in your chosen language.
""")
st.markdown("---")

language = st.selectbox("🌐 Select your language", ["English", "Hindi", "Bengali", "Urdu"])
uploaded_file = st.file_uploader("📄 Upload Judgment PDF", type=["pdf"])
st.markdown("---")

# -----------------------------
# Main Action
# -----------------------------
if uploaded_file and st.button("🚀 Generate Summary"):
    with st.spinner("Processing judgment…"):
        try:
            raw_text = extract_text_from_pdf(uploaded_file)
            safe_text = compress_text(raw_text)

            prompt = build_prompt(safe_text, language)

            # ⚡ Best multilingual model for Hindi/Bengali/Urdu
            model_id = "meta-llama/llama-3.1-8b-instruct"


            # -----------------------------
            # FIRST ATTEMPT
            # -----------------------------
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are an expert legal simplification engine."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=280,
                temperature=0.05,
            )

            summary = response.choices[0].message.content.strip()

            # -----------------------------
            # RETRY IF ENGLISH LEAKAGE
            # -----------------------------
            if language.lower() != "english" and english_leakage_detected(summary):
                retry_prompt = build_retry_prompt(safe_text, language)

                response2 = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": "Strict multilingual rewriting engine."},
                        {"role": "user", "content": retry_prompt}
                    ],
                    max_tokens=260,
                    temperature=0.03,
                )

                retry_summary = response2.choices[0].message.content.strip()

                if len(retry_summary) > 0 and not english_leakage_detected(retry_summary):
                    summary = retry_summary

            if not summary:
                st.error("The model returned an empty summary. Try a shorter file or switch to English.")
            else:
                st.markdown("## ✅ Simplified Judgment")
                st.write(summary)
                st.success("The judgment has been simplified successfully.")
                
                # ===== REMEDIES SECTION =====
                st.markdown("---")
                st.markdown("## ⚖️ What Can You Do Now?")
                
                with st.spinner("Analyzing your legal options..."):
                    try:
                        remedies = get_remedies_advice(raw_text, language)
                        
                        # Show each answer
                        if remedies.get("what_happened"):
                            st.subheader("What Happened?")
                            st.write(remedies["what_happened"])
                        
                        if remedies.get("can_appeal"):
                            st.subheader("Can You Appeal?")
                            st.write(remedies["can_appeal"])
                            
                            # Only show appeal details if they can appeal
                            if "yes" in remedies["can_appeal"].lower():
                                st.subheader("Appeal Details")
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    if remedies.get("appeal_days"):
                                        st.metric("Days to File Appeal", remedies["appeal_days"])
                                    if remedies.get("appeal_court"):
                                        st.write(f"**Appeal to:** {remedies['appeal_court']}")
                                
                                with col2:
                                    if remedies.get("cost"):
                                        st.write(f"**Estimated Cost:** {remedies['cost']}")
                        
                        if remedies.get("first_action"):
                            st.subheader("What Should You Do First?")
                            st.write(f"✅ {remedies['first_action']}")
                        
                        if remedies.get("deadline"):
                            st.subheader("⏰ Important Deadline")
                            st.write(remedies["deadline"])
                        
                    except Exception as e:
                        st.error(f"Could not get remedies advice: {str(e)}")
                
                # ===== FREE LEGAL HELP SECTION =====
                st.markdown("---")
                st.markdown("## 📞 Free Legal Help")
                
                help_options = """
                **You don't have to handle this alone. Here are free resources:**
                
                🔗 **National Legal Services (Free Lawyer)**
                - Phone: 1800-180-8111
                - Website: nalsa.gov.in
                - For: Everyone (especially poor citizens)
                
                🔗 **Bar Council of India (Find Verified Lawyers)**
                - Website: bci.org.in
                - For: Finding qualified lawyers in your area
                
                🔗 **Legal Clinics (Law Colleges)**
                - Most law colleges offer free consultation
                - Search: "[Your City] law college legal clinic"
                
                🔗 **NGOs for Specific Cases**
                - Family cases: National Commission for Women (1800-123-4344)
                - Criminal cases: Criminal Law Clinic (project39a.com)
                - Tenant rights: Housing rights organizations
                
                **Tip:** Start with National Legal Services. They are free and available.
                """
                
                st.info(help_options)

        except Exception as e:
            err = str(e)

            if "402" in err or "credits" in err.lower():
                st.error("❌ Not enough OpenRouter credits. Please top up.")
            else:
                st.error(f"An error occurred: {err}")