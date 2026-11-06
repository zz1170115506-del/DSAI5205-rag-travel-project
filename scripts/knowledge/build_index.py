"""Build the paragraph vector index; model downloading requires --download."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from travel.core.config import RetrievalSettings
from travel.rag.documents import INDEX, documents
from travel.rag.embeddings import build_index


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true')
    args=parser.parse_args()
    print(json.dumps(build_index(documents(),RetrievalSettings.from_env().model_name,
                                 download=args.download,index_path=INDEX),ensure_ascii=False))
