import httpx

from idea_council.config.settings import Settings
from idea_council.providers.adapter import (
    AnthropicAdapter,
    GoogleAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    ProviderAdapter,
)


def _get_available_ollama_models(base_url: str) -> list[str]:
    """
    Calls the Ollama /api/tags endpoint and returns the list of model names
    that are pulled and ready. Returns an empty list if Ollama is unreachable.
    """
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        if response.status_code != 200:
            return []
        data = response.json()
        return [model["name"] for model in data.get("models", [])]
    except Exception:
        return []


def build_debaters(settings: Settings) -> list[ProviderAdapter]:
    """
    Returns the list of active debater adapters based on what is configured
    and available. Anthropic is always included if the key is present.
    Ollama adapters are only added for models that are actually pulled and
    ready - configured-but-missing models are skipped with a warning.
    OpenAI and Google are included if their keys are set.
    """
    debaters = []

    # Anthropic debater
    debaters.append(
        AnthropicAdapter(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
        )
    )

    # Ollama debaters - check which models are actually available
    if settings.ollama_models:
        available = _get_available_ollama_models(settings.ollama_base_url)

        if not available:
            print(
                f"[warning] Ollama not reachable at {settings.ollama_base_url} - skipping local models"
            )
        else:
            for model in settings.ollama_models:
                # Ollama model names can be stored with or without the :tag suffix
                is_available = any(
                    available_model == model or available_model.startswith(model + ":")
                    for available_model in available
                )
                if is_available:
                    debaters.append(
                        OllamaAdapter(
                            model=model,
                            base_url=settings.ollama_base_url,
                        )
                    )
                else:
                    print(
                        f"[warning] Ollama model '{model}' is not pulled - skipping. Run: ollama pull {model}"
                    )

    # OpenAI debater
    if settings.openai_api_key:
        debaters.append(
            OpenAIAdapter(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
            )
        )

    # Google debater
    if settings.google_api_key:
        debaters.append(
            GoogleAdapter(
                model=settings.google_model,
                api_key=settings.google_api_key,
            )
        )

    return debaters


def build_synthesizer(settings: Settings) -> ProviderAdapter:
    """
    The synthesizer is always Anthropic. It is a separate adapter instance
    from the debater - same provider, distinct invocation and system prompt.
    """
    return AnthropicAdapter(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
    )


def build_fallback(settings: Settings) -> ProviderAdapter:
    """
    Fallback adapter used when a debater call fails. Always Anthropic haiku
    so it is fast and cheap.
    """
    return AnthropicAdapter(
        model=settings.anthropic_fallback_model,
        api_key=settings.anthropic_api_key,
    )
