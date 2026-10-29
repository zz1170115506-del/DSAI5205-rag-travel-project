import os
import math
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class RetrievalSettings:
    mode: str = 'bm25'
    model_name: str = 'BAAI/bge-small-zh-v1.5'
    min_score: float = 0.5

    def __post_init__(self):
        if self.mode not in {'bm25', 'hybrid'}:
            raise ValueError('RETRIEVAL_MODE 须为 bm25 或 hybrid。')
        if not self.model_name or not math.isfinite(self.min_score) or not 0 <= self.min_score <= 1:
            raise ValueError('Embedding 模型名或相似度阈值无效。')

    @classmethod
    def from_env(cls):
        # Read only retrieval options; do not export model/map keys into MCP's environment.
        values = dotenv_values(ROOT / '.env')
        def read(name, default):
            return str(os.environ.get(name, values.get(name) or default)).strip()
        return cls(mode=read('RETRIEVAL_MODE', 'bm25'),
                   model_name=read('LOCAL_EMBEDDING_MODEL',
                       read('EMBEDDING_MODEL', 'BAAI/bge-small-zh-v1.5')
                       if not read('MODEL_MODE', '') else 'BAAI/bge-small-zh-v1.5'),
                   min_score=float(read('EMBEDDING_MIN_SCORE', '0.5')))


@dataclass(frozen=True)
class Settings:
    model_api_key: str = ''
    model_base_url: str = 'https://api.deepseek.com/v1'
    model_name: str = 'deepseek-flash'
    amap_api_key: str = ''
    amap_enabled: bool = True
    amap_key_present: bool = False
    response_language: str = 'zh'

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / '.env', override=False)
        return cls(
            model_api_key=os.getenv('MODEL_API_KEY', '').strip(),
            model_base_url=os.getenv('MODEL_BASE_URL', 'https://api.deepseek.com/v1').strip().rstrip('/'),
            model_name=os.getenv('MODEL_NAME', 'deepseek-flash').strip(),
            amap_api_key=(os.getenv('AMAP_API_KEY', '').strip()
                          if os.getenv('AMAP_ENABLED', 'true').strip().lower() not in {'false','0','no'} else ''),
            amap_enabled=os.getenv('AMAP_ENABLED', 'true').strip().lower() not in {'false','0','no'},
            amap_key_present=bool(os.getenv('AMAP_API_KEY', '').strip()),
        )
