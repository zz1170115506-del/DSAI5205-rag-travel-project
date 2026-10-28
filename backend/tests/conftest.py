import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.config import ROOT, Settings
from app.core.db import database
from app.models import Base
from app.rag.ingestion.pipeline import ingest, read_bundle
from app.rag.retrieval.search import build_index, SearchEngine


@pytest.fixture
def stack(tmp_path):
    # Optional real MySQL run must target an explicitly disposable *_test database.
    url = os.getenv('TEST_DATABASE_URL', f'sqlite:///{tmp_path}/test.db')
    if not url.startswith('sqlite') and not make_url(url).database.endswith('_test'):
        raise ValueError('TEST_DATABASE_URL must use a disposable *_test database')
    settings = Settings(_env_file=None, database_url=url, data_root=tmp_path,
                        mock_token_delay=0, model_mode='mock')
    engine, factory = database(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    bundle = read_bundle(ROOT / 'data/demo/bundle.json')
    ingest(factory, bundle, 'demo-v1', tmp_path)
    asyncio.run(build_index(factory, settings))
    search = SearchEngine(factory, settings)
    search.load()
    yield settings, factory, search, bundle
    Base.metadata.drop_all(engine)
    engine.dispose()
