from pathlib import Path
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    app_env: str = 'development'
    model_mode: str = 'mock'
    database_url: str = 'sqlite:///./travel.db'
    mysql_database: str = 'travel'
    mysql_user: str = 'travel'
    mysql_password: str = ''
    mysql_host: str = 'mysql'
    data_root: Path = ROOT / 'data'
    allowed_origins: str = 'http://localhost:8080,http://127.0.0.1:8080'
    cookie_secure: bool = False
    llm_base_url: str = ''
    llm_api_key: str = ''
    llm_model: str = ''
    embedding_base_url: str = ''
    embedding_api_key: str = ''
    embedding_model: str = ''
    embedding_dim: int = Field(256, ge=8)
    enable_graph: bool = True
    enable_memory: bool = True
    max_tool_calls: int = Field(6, ge=1, le=20)
    run_timeout_seconds: float = Field(60, gt=0)
    model_timeout_seconds: float = Field(30, gt=0)
    mock_token_delay: float = Field(.015, ge=0)
    max_active_runs: int = Field(8, ge=1)

    @model_validator(mode='after')
    def validate_mode(self):
        if self.model_mode not in {'mock', 'remote'}:
            raise ValueError('MODEL_MODE must be mock or remote')
        if self.model_mode == 'remote' and not all([
            self.llm_base_url, self.llm_api_key, self.llm_model,
            self.embedding_base_url, self.embedding_api_key, self.embedding_model,
        ]):
            raise ValueError('remote mode requires all LLM_* and EMBEDDING_* settings')
        if self.database_url == 'mysql':
            self.database_url = URL.create(
                'mysql+pymysql', username=self.mysql_user, password=self.mysql_password,
                host=self.mysql_host, database=self.mysql_database,
                query={'charset': 'utf8mb4'},
            ).render_as_string(hide_password=False)
        return self


@lru_cache
def get_settings():
    return Settings()
