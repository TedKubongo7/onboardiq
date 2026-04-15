from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    model: str = "claude-sonnet-4-20250514"
    max_file_size_mb: int = 20

    class Config:
        env_file = ".env"


settings = Settings()