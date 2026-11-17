from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: str = ""
    groq_api_key: str = ""
    groq_api_keys: str = ""  # comma separated pool of (free-tier) keys; rotated automatically

    # LLM routing: providers are tried in order; Groq keys are round-robined and fall back to a smaller model.
    llm_route_order: str = "openai,groq"
    llm_model: str = "gpt-6-luna"
    llm_reasoning_effort: str = "low"
    llm_summary_effort: str = "high"
    llm_timeout_s: float = 2.5  # per attempt
    llm_total_timeout_s: float = 4.5  # across all fallbacks for one live turn
    groq_llm_model: str = "openai/gpt-oss-120b"
    groq_llm_fallback_model: str = "openai/gpt-oss-20b"

    # STT routing: groq (fast, free tier) -> openai -> local (offline last resort)
    stt_route_order: str = "groq,openai,local"
    stt_model: str = "gpt-transcribe"  # openai route
    stt_fallback_model: str = "whisper-1"
    groq_stt_model: str = "whisper-large-v3-turbo"
    local_stt_model: str = "base"  # faster-whisper size for the offline fallback (tiny/base/small)

    # abuse / resource limits
    max_concurrent_calls: int = 12
    max_calls_per_ip: int = 3
    max_audio_seconds: float = 30.0
    max_utterances_per_min: int = 30
    max_call_seconds: int = 900
    idle_timeout_s: int = 180
    turn_deadline_s: float = 25.0
    allowed_origins: str = ""  # comma separated extra origins; same-origin is always allowed
    app_env: str = "dev"  # dev | prod
    staff_token_ttl_s: int = 8 * 3600
    secret_key: str = ""  # signs staff tokens; generated per-process if empty

    tts_url: str = "http://tts:8880"
    tts_voice: str = "af_heart"
    tts_speed: float = 1.05
    tts_voice_hi: str = "hf_alpha"  # female Hindi voice, used for Hindi AND Urdu callers
    assistant_name_local: str = "हानिया"
    hospital_name_local: str = "प्रोटॉन्स डेमो हॉस्पिटल"

    hospital_name: str = "Protons Demo Hospital"
    assistant_name: str = "Hania"
    emergency_number: str = "1122"
    staff_pin: str = "1234"

    postgres_user: str = "triage"
    postgres_password: str = "triage"
    postgres_db: str = "triage"
    postgres_host: str = "db"

    emr_url: str = "http://mock-emr:9000"
    data_dir: str = "/data"
    knowledge_dir: str = "/app/knowledge"

    max_turns: int = 30
    filler_after_ms: int = 1400
    rag_min_score: float = 0.55
    # General, non-diagnostic first-line guidance (rest, fluids, when to get urgent help) from approved documents.
    # Medicines, doses, diagnosis, children and pregnancy ALWAYS go to staff. Needs clinician sign-off before real use.
    symptom_guidance: bool = True
    # Doctor-style conversation (follow-up questions + medical reference lookup + possible explanations). Needs a working LLM route.
    doctor_mode: bool = True
    tz: str = "Asia/Karachi"

    @property
    def groq_keys(self) -> list[str]:
        keys = [k.strip() for k in self.groq_api_keys.split(",") if k.strip()]
        if self.groq_api_key.strip() and self.groq_api_key.strip() not in keys:
            keys.insert(0, self.groq_api_key.strip())
        return keys

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:5432/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
