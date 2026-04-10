import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Anthropic — required
    anthropic_api_key: str
    anthropic_model: str
    anthropic_fallback_model: str

    # Ollama — optional, local
    ollama_base_url: str
    ollama_models: list[str]

    # OpenAI — optional
    openai_api_key: str
    openai_model: str

    # Google — optional
    google_api_key: str
    google_model: str

    # Market verification
    github_search_enabled: bool
    github_search_max_results: int
    tavily_api_key: str

    # Session
    max_tokens_per_call: int
    output_dir: str
    log_level: str


def load_settings() -> Settings:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required but not set in .env")

    ollama_models_raw = os.getenv("OLLAMA_MODELS", "")
    if ollama_models_raw:
        ollama_models = [m.strip() for m in ollama_models_raw.split(",") if m.strip()]
    else:
        ollama_models = []

    return Settings(
        anthropic_api_key=api_key,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        anthropic_fallback_model=os.getenv(
            "ANTHROPIC_FALLBACK_MODEL", "claude-haiku-4-5"
        ),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_models=ollama_models,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_model=os.getenv("GOOGLE_MODEL", "gemini-2.0-flash"),
        github_search_enabled=os.getenv("GITHUB_SEARCH_ENABLED", "true").lower()
        == "true",
        github_search_max_results=int(os.getenv("GITHUB_SEARCH_MAX_RESULTS", "10")),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        max_tokens_per_call=int(os.getenv("MAX_TOKENS_PER_CALL", "2048")),
        output_dir=os.getenv("OUTPUT_DIR", "output"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
