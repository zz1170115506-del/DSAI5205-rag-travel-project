"""Inspect actual retrieval; --use-model explicitly enables a cloud generation call."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from travel.answers import rag_answer
from travel.config import Settings
from travel.retrieval import retrieve


def main():
    parser = argparse.ArgumentParser(description='检查检索结果或运行一次 RAG 问答')
    parser.add_argument('--query', default='想了解香港历史建筑和艺术，有什么地方推荐？')
    parser.add_argument('--use-model', action='store_true', help='向 .env 中配置的云端模型发送问题和检索资料，产生实际用量')
    args = parser.parse_args()
    settings = Settings.from_env() if args.use_model else Settings()
    if args.use_model and not settings.model_api_key:
        print('请先在本地 .env 填写 MODEL_API_KEY；未发出模型请求。')
        return 1
    result = retrieve(args.query, 5)
    answer = asyncio.run(rag_answer(args.query, result['results'], settings))
    output = {'query': args.query, 'retrieval': result['retrieval'],
              'retrieved': [{key: p.get(key) for key in ('id', 'name', 'score', 'semantic_score', 'match_reason')} for p in result['results']],
              'answer': answer}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not args.use_model or answer['mode'] == 'model' else 1


if __name__ == '__main__':
    raise SystemExit(main())
