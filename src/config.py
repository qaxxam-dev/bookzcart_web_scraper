from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    OPENROUTER_API_KEY: str
    DEEPINFRA_API_KEY: str
    DATABASE: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    PORT: int
    DATABASE_NAME: str

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"{self.DATABASE}+asyncpg://{self.DATABASE_USER}:"
            f"{self.DATABASE_PASSWORD}@localhost:{self.PORT}/"
            f"{self.DATABASE_NAME}"
        )


settings = Settings()
