from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Common interface every LLM backend implements, so agents never know
    whether they're talking to OpenAI, Anthropic, Ollama, or the offline Mock.
    """

    @abstractmethod
    async def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        """Return a plain-text completion for the given system+user prompt."""
        raise NotImplementedError
