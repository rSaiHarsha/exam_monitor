import os
from pathlib import Path
from typing import List
from openai import OpenAI
from dotenv import load_dotenv

# Prioritize api_key.env fallback mapping
# Look for .env in current dir, or parent, or parent's parent
env_paths = [Path(".env"), Path("api_key.env"), Path("../.env"), Path("../../.env"), Path("../api_key.env")]
for p in env_paths:
    if p.exists():
        load_dotenv(p)
        break

class LLMManager:
    def __init__(self, model_name="nvidia/llama-3.3-nemotron-super-49b-v1.5", rag_model_name="nvidia/llama-3.3-nemotron-super-49b-v1.5", analysis_model_name="nvidia/llama-3.3-nemotron-super-49b-v1.5"):
        # Check Streamlit secrets first, fallback to environment variable
        api_key = None
        try:
            import streamlit as st
            api_key = st.secrets["API_KEY"]
        except Exception:
            pass
        
        if not api_key:
            api_key = os.getenv("NVIDIA_API_KEY")
            
        if not api_key:
            api_key = "mock-key"
            
        self.client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key
        )
        self.model_name = model_name
        self.rag_model_name = rag_model_name
        self.analysis_model_name = analysis_model_name
        self.embedding_model = "nvidia/nv-embedqa-e5-v5"
        self.retries = 3

    def _retry_api_call(self, api_func, *args, **kwargs):
        """Helper to execute API functions with transient failure retry logic using exponential backoff."""
        retries = getattr(self, "retries", 3)

        import time
        last_exception = None
        for attempt in range(retries + 1):
            try:
                return api_func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < retries:
                    wait_time = 2 ** attempt
                    print(f"[LLMManager] API call failed: {e}. Retrying {attempt+1}/{retries} in {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                else:
                    print(f"[LLMManager] API call failed after {retries} retries: {e}", flush=True)
                    raise last_exception

    def get_response(self, messages, stream=True, model=None):
        # Keep a sliding window of the last 10 messages to avoid token limit issues
        trimmed_messages = messages[-10:]
        
        # Use specific model if provided, otherwise default to self.model_name
        target_model = model if model else self.model_name
        
        def call_and_validate():
            response = self.client.chat.completions.create(
                model=target_model,
                messages=trimmed_messages,
                temperature=0.0,
                top_p=0.01,
                seed=42,
                max_tokens=8192,
                stream=stream
            )
            if not stream:
                if not response or not response.choices:
                    raise ValueError("LLM returned an empty response (no choices).")
                content = response.choices[0].message.content
                if content is None or content.strip() == "":
                    raise ValueError("LLM returned empty or null content.")
            return response

        return self._retry_api_call(call_and_validate)

    def get_embedding(self, text: str):
        """Generates contextual float embeddings using the NVIDIA NIM footprint"""
        response = self._retry_api_call(
            self.client.embeddings.create,
            input=[text],
            model=self.embedding_model,
            encoding_format="float",
            extra_body={"input_type": "query", "truncate": "END"}
        )
        return response.data[0].embedding

    def get_embeddings_batch(self, texts: List[str]):
        """Generates embeddings for a list of strings in a single batch API call."""
        if not texts:
            return []
        response = self._retry_api_call(
            self.client.embeddings.create,
            input=texts,
            model=self.embedding_model,
            encoding_format="float",
            extra_body={"input_type": "passage", "truncate": "END"}
        )
        # Ensure correct ordering by sorting on the index property
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
