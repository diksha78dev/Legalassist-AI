import streamlit as st
import logging

from core.app_utils import get_client, RETRO_STYLING
from core.rag_engine import LegalRAG

# Apply the same styling as other pages
st.markdown(RETRO_STYLING, unsafe_allow_html=True)

# Cache the RAG engine so we don't reload the embedding model on every interaction
@st.cache_resource
def get_rag_engine():
    return LegalRAG()

def render_page():
    st.title("💬 Chat with Judgment")
    
    # Ensure there is a document to chat with
    if "judgment_raw_text" not in st.session_state or not st.session_state.judgment_raw_text:
        st.warning("No judgment document found. Please go back to the Home page and upload a document first.")
        if st.button("⬅️ Back to Home"):
            st.switch_page("pages/0_Home.py")
        return

    # Sidebar language preference
    language = st.session_state.get("judgment_language", "English")
    st.sidebar.markdown(f"**Chat Language:** {language}")
    st.sidebar.info("You can change the language on the Home page.")

    # Initialize RAG Engine
    rag_engine = get_rag_engine()
    
    if "rag_initialized" not in st.session_state or not st.session_state.rag_initialized:
        with st.spinner("Initializing interactive chat... (this may take a moment to process the document)"):
            success = rag_engine.initialize_vector_store(st.session_state.judgment_raw_text)
            if success:
                st.session_state.rag_initialized = True
            else:
                st.error("Failed to initialize chat engine.")
                return

    # Ensure chat history exists
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
        
    st.markdown("Ask any specific questions about the uploaded judgment. The AI will answer strictly based on the document's contents.")
    st.markdown("---")

    # Display chat messages from history on app rerun
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # React to user input (text or audio)
    audio_val = st.audio_input("🎤 Or speak your question...")
    
    user_question = None

    if prompt := st.chat_input("Ask a question about the judgment..."):
        user_question = prompt
    elif audio_val is not None:
        # Check if we already processed this exact audio file
        audio_id = hash(audio_val.getvalue())
        if st.session_state.get("last_processed_audio_id") != audio_id:
            with st.spinner("Transcribing audio..."):
                from core.audio_utils import transcribe_audio
                transcribed_text = transcribe_audio(audio_val.getvalue())
                if transcribed_text:
                    user_question = transcribed_text
                    st.session_state["last_processed_audio_id"] = audio_id
                else:
                    st.error("Failed to transcribe audio.")

    if user_question:
        # Display user message in chat message container
        st.chat_message("user").markdown(user_question)
        
        # Add user message to chat history
        st.session_state.chat_history.append({"role": "user", "content": user_question})

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Get the configured OpenAI/OpenRouter client
                    client = get_client()
                    
                    # Query the RAG engine
                    response = rag_engine.query(
                        question=user_question, 
                        language=language, 
                        openai_client=client
                    )
                    
                    st.markdown(response)
                    
                    # Add assistant response to chat history
                    st.session_state.chat_history.append({"role": "assistant", "content": response})
                except Exception as e:
                    st.error(f"Error communicating with AI: {str(e)}")

if __name__ == "__main__":
    render_page()
