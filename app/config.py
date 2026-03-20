import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_NAME: str = "workflow_service"

    POSTGRES_HOST: str = "wf_db"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "wf_user"
    POSTGRES_PASSWORD: str = "wf_pass"
    POSTGRES_DB: str = "wf_db"

    class Config:
        env_file = ".env"
        env_prefix = "WF_"
        case_sensitive = False


settings = Settings()

DATABASE_URL = os.getenv(
    "WORKFLOW_DATABASE_URL",
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}",
)
