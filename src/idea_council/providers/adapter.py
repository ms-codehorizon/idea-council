import anthropic
import openai


class ProviderAdapter:
    """Base class for all provider adapters. Each adapter wraps one model."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model

    def call(self, system: str, user: str, max_tokens: int = 2048) -> str:
        raise NotImplementedError


class AnthropicAdapter(ProviderAdapter):

    def __init__(self, model: str, api_key: str):
        super().__init__("anthropic", model)
        self.client = anthropic.Anthropic(api_key=api_key)

    def call(self, system: str, user: str, max_tokens: int = 2048) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


class OllamaAdapter(ProviderAdapter):
    """Uses the OpenAI-compatible API that Ollama exposes at /v1."""

    def __init__(self, model: str, base_url: str):
        super().__init__("ollama", model)
        self.client = openai.OpenAI(
            base_url=f"{base_url}/v1",
            api_key="ollama",  # required by the client but ignored by Ollama
        )

    def call(self, system: str, user: str, max_tokens: int = 2048) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content


class OpenAIAdapter(ProviderAdapter):

    def __init__(self, model: str, api_key: str):
        super().__init__("openai", model)
        self.client = openai.OpenAI(api_key=api_key)

    def call(self, system: str, user: str, max_tokens: int = 2048) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content


class GoogleAdapter(ProviderAdapter):
    """Google exposes an OpenAI-compatible endpoint."""

    def __init__(self, model: str, api_key: str):
        super().__init__("google", model)
        self.client = openai.OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=api_key,
        )

    def call(self, system: str, user: str, max_tokens: int = 2048) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content
