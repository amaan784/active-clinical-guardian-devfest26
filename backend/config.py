"""
Synapse 2.0 Configuration
Central configuration management using Pydantic Settings
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Dedalus Labs Configuration (Agent Orchestration)
    dedalus_api_key: str = ""
    dedalus_environment: str = "production"  # or "development"

    # K2 Think Configuration (OpenAI-compatible API)
    # Can be self-hosted vLLM or hosted endpoint
    k2_api_key: str = ""
    k2_base_url: str = "http://localhost:8080/v1"  # vLLM endpoint
    k2_model: str = "LLM360/K2-Think-V2"

    # Snowflake Configuration
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_database: str = "SYNAPSE_DB"
    snowflake_schema: str = "PUBLIC"
    snowflake_warehouse: str = "COMPUTE_WH"

    # ElevenLabs Configuration
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Default: Rachel

    # Flowglad Configuration
    flowglad_api_key: str = ""
    flowglad_api_url: str = "https://api.flowglad.com/v1"

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # Safety Check Interval (seconds)
    safety_check_interval: float = 5.0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()
