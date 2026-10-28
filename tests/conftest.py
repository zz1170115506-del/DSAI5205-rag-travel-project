"""所有网页测试固定使用空配置；本机即使填了 Key，也不会意外调用真实付费服务。"""
import pytest
from travel.config import Settings

@pytest.fixture(autouse=True)
def local_only_web_settings(monkeypatch):
    # Ordinary regression never loads local embedding models or downloads weights.
    # Dedicated hybrid tests override this explicitly, including MCP subprocesses.
    monkeypatch.setenv('RETRIEVAL_MODE', 'bm25')
    import app
    monkeypatch.setattr(app,'settings',Settings())
