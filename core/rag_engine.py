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

    def query(self, question: str, language: str, openai_client) -> str:
        """Query the document and generate an answer using the provided LLM client."""
        if not self.vector_store:
            return "Please wait for the document to finish processing before asking questions."
            
        try:
            LOGGER.info(f"Retrieving context for question: {question}")
            # Retrieve relevant chunks
            retriever = self.vector_store.as_retriever(search_kwargs={"k": 4})
            relevant_docs = retriever.invoke(question)
            
            if not relevant_docs:
                return "I couldn't find relevant information in the document to answer your question."
                
            context = "\n\n---\n\n".join([doc.page_content for doc in relevant_docs])
            
            # Construct the prompt
            prompt = f"""
You are LegalEase AI, an expert judicial assistant.
Answer the user's question strictly based on the provided context from the legal document.
Do not use outside knowledge. If the answer is not in the context, clearly state: "I cannot find the answer to this in the document."

STRICT REQUIREMENT: Provide your final answer ONLY in the {language} language.

CONTEXT FROM DOCUMENT:
{context}

USER QUESTION:
{question}

ANSWER IN {language}:
"""
            
            LOGGER.info("Generating response from LLM...")
            # Call LLM
            response = openai_client.chat.completions.create(
                model="meta-llama/llama-3.1-8b-instruct",
                messages=[
                    {"role": "system", "content": f"You are a helpful legal assistant. Output only in {language}."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.1,
            )
            
            answer = response.choices[0].message.content.strip()
            return answer
            
        except Exception as e:
            LOGGER.error(f"Error querying RAG engine: {e}")
            return f"An error occurred while trying to answer your question: {str(e)}"
