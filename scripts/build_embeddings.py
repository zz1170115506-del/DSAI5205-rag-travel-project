"""Build the local place-vector index. Only --download permits model downloads."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from travel.config import RetrievalSettings
from travel.embeddings import EmbeddingUnavailable, build_index
from travel.knowledge import places


def main():
    parser = argparse.ArgumentParser(description='建立本地旅游资料 Embedding 索引')
    parser.add_argument('--download', action='store_true', help='允许首次从模型仓库下载权重')
    args = parser.parse_args()
    settings = RetrievalSettings.from_env()
    try:
        result = build_index(places(), settings.model_name, download=args.download)
    except EmbeddingUnavailable as exc:
        print(json.dumps({'ok': False, 'reason': str(exc),
                          'next_step': '安装 requirements-embedding.txt；首次构建使用 --download。'}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
