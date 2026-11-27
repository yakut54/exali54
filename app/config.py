from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str = "botuser"
    POSTGRES_PASSWORD: str = "botpassword"
    POSTGRES_DB: str = "botdb"
    DATABASE_URL: str = "postgresql://botuser:botpassword@db:5432/botdb"

    MAX_API_URL: str = "https://platform-api2.max.ru"
    MAX_BOT_TOKEN: str = ""
    DEEPSEEK_API_KEY: str = ""


settings = Settings()
