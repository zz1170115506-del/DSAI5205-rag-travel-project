import argparse
import asyncio
import json
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import ROOT, get_settings
from app.core.db import database
from app.rag.ingestion.pipeline import ingest, read_bundle
from app.rag.retrieval.search import build_index, SearchEngine


def migrate():
    command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')


async def main():
    parser = argparse.ArgumentParser(description='Travel RAG data / migration / evaluation tools')
    parser.add_argument('command', choices=['migrate', 'bootstrap', 'ingest', 'validate-data', 'build-index', 'evaluate'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--version', default='demo-v1')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--split', choices=['dev', 'test'], default='dev')
    parser.add_argument('--channels', default='vector,bm25,entity,graph')
    args = parser.parse_args()
    settings = get_settings()
    settings.data_root.mkdir(parents=True, exist_ok=True)
    engine, factory = database(settings.database_url)
    try:
        if args.command == 'migrate':
            migrate()
        elif args.command in {'bootstrap', 'ingest', 'validate-data'}:
            if args.command == 'bootstrap':
                migrate()
            path = ROOT / 'data/demo/bundle.json' if args.demo else args.input
            if path is None:
                parser.error('--input FILE_OR_CSV_DIRECTORY or --demo is required')
            bundle = read_bundle(path)
            if args.command == 'validate-data':
                # Use a disposable relational DB to run exactly the same validator, without mutating target.
                from app.models import Base
                validation_engine, vf = database('sqlite://')
                Base.metadata.create_all(validation_engine)
                ingest(vf, bundle, args.version, settings.data_root)
                validation_engine.dispose()
                print('Data fields and relationships validated (SQLite preflight; MySQL integration is separate).')
            else:
                ingest(factory, bundle, args.version, settings.data_root)
                print('Imported dataset:', args.version)
                if args.command == 'bootstrap':
                    m = await build_index(factory, settings)
                    print('Built index:', m['index_version'], 'mode:', settings.model_mode)
        elif args.command == 'build-index':
            print(json.dumps(await build_index(factory, settings), ensure_ascii=False, indent=2))
        elif args.command == 'evaluate':
            from app.evaluation.runner import evaluate
            if not args.input or not args.output:
                parser.error('--input DATASET.jsonl and --output DIRECTORY are required')
            search = SearchEngine(factory, settings)
            search.load()
            print(json.dumps(await evaluate(search, args.input, args.output, args.split,
                                           args.channels.split(',')), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
