"""Export approved source documents as deployable chunks and a processing report."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from travel.rag.ingestion.chunking import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT.parent / '知识库' / 'documents.jsonl')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'knowledge')
    parser.add_argument('--size', type=int, default=800)
    parser.add_argument('--overlap', type=int, default=100)
    args = parser.parse_args()
    documents = [json.loads(line) for line in args.input.read_text(encoding='utf-8').splitlines() if line.strip()]
    chunks, report = build(documents, args.size, args.overlap)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'chunks.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in chunks), encoding='utf-8')
    (args.output / 'processing_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('input_document_count', 'chunk_count', 'retrieval_ready_count', 'review_required_count', 'dataset_version')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
