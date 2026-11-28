from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_USER: str = "botuser"
    POSTGRES_PASSWORD: str = "botpassword"
    POSTGRES_DB: str = "botdb"
    DATABASE_URL: str = "postgresql://botuser:botpassword@db:5432/botdb"

    MAX_API_URL: str = "https://platform-api2." + "max.ru"
    MAX_BOT_TOKEN: str = ""
    MAX_WEBHOOK_URL: str = "https://exali54.ru" + "/webhook"
    MAX_WEBHOOK_SECRET: str = ""
    DEEPSEEK_API_URL: str = "https://api." + "proxyapi.ru" + "/v1/chat/completions"
    DEEPSEEK_API_KEY: str = ""
    DADATA_API_KEY: str = ""
    DADATA_INN_URL: str = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    MAX_BOT_USERNAME: str = ""
    TTN_STORAGE_DIR: str = "/data/ttn"

    ADMIN_USER_ID: int = 68300606
    DAILY_CALC_LIMIT: int = 50
    DAILY_INN_LIMIT: int = 20


settings = Settings()
