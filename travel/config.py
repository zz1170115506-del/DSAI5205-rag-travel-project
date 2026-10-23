import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    model_api_key: str = ''
    model_base_url: str = 'https://api.deepseek.com/v1'
    model_name: str = 'deepseek-flash'
    amap_api_key: str = ''
    amap_enabled: bool = True
    amap_key_present: bool = False

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
