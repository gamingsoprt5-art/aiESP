    llm_provider: str = "openrouter"

    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-2.5-flash"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "z-ai/glm-5.2:free"

    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/paas/v4/"
    zai_model: str = "glm-4.5-flash"

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"

    rate_limit: str = "20/minute"
    max_prompt_chars: int = 4000
    max_history_messages: int = 20
    max_request_bytes: int = 200_000

    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def online_provider_chain(self) -> list[dict]:
        candidates = [
            {"kind": "gemini", "name": "gemini", "base_url": self.gemini_base_url,
             "api_key": self.gemini_api_key, "model": self.gemini_model},
            {"kind": "openai", "name": "openrouter", "base_url": self.openrouter_base_url,
             "api_key": self.openrouter_api_key, "model": self.openrouter_model},
            {"kind": "openai", "name": "zai", "base_url": self.zai_base_url,
             "api_key": self.zai_api_key, "model": self.zai_model},
            {"kind": "openai", "name": "nvidia", "base_url": self.nvidia_base_url,
             "api_key": self.nvidia_api_key, "model": self.nvidia_model},
        ]
        return [c for c in candidates if c["api_key"]]
