from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "llm_obs"
    openai_api_key: str = ""
    slack_webhook_url: str = ""
    eval_sample_rate: float = 0.1

    class Config:
        env_file = ".env"

settings = Settings()
