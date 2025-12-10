"""
Core configuration for VeriSynth Research OS.

Supports Google Cloud Run, Secret Manager, and local development.
"""
import os
from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with Cloud Run and Secret Manager support."""

    # Application
    app_name: str = "VeriSynth Research OS"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", description="Environment: development, staging, production")
    debug: bool = Field(default=False, description="Debug mode")

    # API Configuration
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="CORS allowed origins"
    )

    # Google Cloud
    gcp_project_id: str = Field(default="", description="Google Cloud Project ID")
    gcp_region: str = Field(default="us-central1", description="GCP region")
    
    # Firestore
    firestore_database: str = Field(default="(default)", description="Firestore database name")
    
    # Vertex AI
    vertex_ai_location: str = Field(default="us-central1", description="Vertex AI location")
    vertex_ai_matching_engine_index: str = Field(default="", description="Matching Engine index ID")
    vertex_ai_matching_engine_endpoint: str = Field(default="", description="Matching Engine endpoint ID")
    
    # LLM Configuration
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    grok_api_key: str = Field(default="", description="Grok API key")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama base URL")
    
    default_llm_provider: str = Field(default="openai", description="Default LLM provider")
    default_llm_model: str = Field(default="gpt-4-turbo-preview", description="Default LLM model")
    
    # MAKER Configuration
    maker_k_value: int = Field(default=2, description="MAKER k value for first_to_ahead_by_k")
    maker_timeout_seconds: int = Field(default=300, description="MAKER timeout in seconds")
    maker_max_concurrent: int = Field(default=10, description="Max concurrent MAKER evaluations")
    maker_red_flag_threshold: float = Field(default=0.3, description="Red flag confidence threshold")
    
    # Memory Configuration
    memory_max_results: int = Field(default=10, description="Max memory search results")
    memory_similarity_threshold: float = Field(default=0.7, description="Memory similarity threshold")
    
    # Security
    secret_key: str = Field(default="", description="Secret key for JWT tokens")
    access_token_expire_minutes: int = Field(default=30, description="Access token expiration")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"
    
    def is_cloud_run(self) -> bool:
        """Check if running in Google Cloud Run."""
        return os.getenv("K_SERVICE") is not None


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
