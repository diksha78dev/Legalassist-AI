import logging
from typing import List, Optional
import chromadb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

LOGGER = logging.getLogger(__name__)

class LegalRAG:
    def __init__(self, embedding_model_name: str = "all-MiniLM-L6-v2"):
        """Initialize the RAG engine with a specific embedding model."""
        LOGGER.info(f"Initializing LegalRAG with embedding model: {embedding_model_name}")
        try:
            self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)
        except Exception as e:
            LOGGER.error(f"Failed to load embedding model: {e}")
            raise
            
        self.vector_store = None
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", " ", ""]
        )

    def initialize_vector_store(self, text: str) -> bool:
        """Chunk the document and load it into an ephemeral vector store."""
        if not text or not text.strip():
            LOGGER.warning("Empty text provided to LegalRAG.")
            return False
            
        try:
            LOGGER.info("Chunking document text...")
            chunks = self.text_splitter.split_text(text)
            LOGGER.info(f"Split document into {len(chunks)} chunks.")
            
            # Create vector store in memory using EphemeralClient
            chroma_client = chromadb.EphemeralClient()
            self.vector_store = Chroma.from_texts(
                texts=chunks,
                embedding=self.embeddings,
                client=chroma_client,
                collection_name="judgment_chat"
            )
            LOGGER.info("Successfully initialized vector store.")
            return True
        except Exception as e:
            LOGGER.error(f"Error initializing vector store: {e}")
            return False

    def query(self, question: str, language: str, openai_client, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
        """
        Query the document and generate an answer using the provided LLM client.
        Supports chat history for context-aware follow-up questions.
        """
        if not self.vector_store:
            return "Please wait for the document to finish processing before asking questions."
            
        try:
            LOGGER.info(f"Retrieving context for question: {question}")
            # Retrieve relevant chunks
            retriever = self.vector_store.as_retriever(search_kwargs={"k": 5})
            relevant_docs = retriever.invoke(question)
            
            if not relevant_docs:
                return "I couldn't find relevant information in the document to answer your question."
                
            context = "\n\n---\n\n".join([doc.page_content for doc in relevant_docs])
            
            # Format chat history for the prompt
            history_str = ""
            if chat_history:
                # Only take the last 4-6 messages to keep the prompt size manageable
                recent_history = chat_history[-6:]
                history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in recent_history])

            # Construct the prompt
            prompt = f"""
You are LegalEase AI, an expert judicial researcher. 
Your goal is to provide accurate, context-grounded answers to user questions about a specific legal document.

STRICT GUIDELINES:
1. Answer ONLY based on the provided CONTEXT. If the answer is not in the context, say "I cannot find the answer to this in the document."
2. CITATIONS: Whenever possible, quote specific sentences or phrases from the document to support your answer.
3. CONVERSATION: Use the RECENT CHAT HISTORY to understand follow-up questions (e.g., "What about the other person?").
4. LANGUAGE: Provide your final answer ONLY in the {language} language.

RECENT CHAT HISTORY:
{history_str}

CONEXT FROM DOCUMENT:
{context}

USER QUESTION:
{question}

ANSWER IN {language} (include citations if possible):
"""
            
            LOGGER.info("Generating response from LLM...")
            # Call LLM using safe_llm_call for robust error handling and retries
            from core.app_utils import safe_llm_call
            answer, error = safe_llm_call(
                client=openai_client,
                model="meta-llama/llama-3.1-8b-instruct",
                messages=[
                    {"role": "system", "content": f"You are a helpful legal researcher. Output only in {language}."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.1,
            )
            
            if error:
                return f"AI Service Error: {error}"
            
            return answer
            
        except Exception as e:
            LOGGER.error(f"Error querying RAG engine: {e}")
            return f"An error occurred while trying to answer your question: {str(e)}"
