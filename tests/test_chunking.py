import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from travel.rag.ingestion.chunking import build


def document(**changes):
    return dict({'document_id': 'sample', 'place_id': 'pmq', 'place_name': '元创方',
                 'source_url': 'https://example.org/source', 'include_in_retrieval': True,
                 'text': '第一段说明历史。\n\n第二段说明建筑。'}, **changes)


class ChunkTests(unittest.TestCase):
    def test_exact_provenance_length_and_coverage(self):
        text = ('A sentence about heritage. Another sentence about buildings.\n\n' * 70) + '末尾无标点'
        chunks, _ = build([document(text=text)], size=180, overlap=40)
        covered = set()
        for c in chunks:
            self.assertEqual(c['text'], text[c['char_start']:c['char_end']])
            self.assertLessEqual(len(c['text']), 180)
            covered.update(range(c['char_start'], c['char_end']))
        self.assertTrue(all(i in covered for i, ch in enumerate(text) if not ch.isspace()))
        self.assertEqual(len({c['chunk_id'] for c in chunks}), len(chunks))
        self.assertTrue(any(a['char_end'] > b['char_start'] for a, b in zip(chunks, chunks[1:])))

    def test_pages_sections_and_unknown_metadata(self):
        chunks, _ = build([document(text='[Page 1]\n## 历史\n建筑资料。\n[Page 2]\n另一页资料。')])
        self.assertEqual([c['page_number'] for c in chunks], [1, 2])
        self.assertEqual(chunks[0]['section_title'], '历史')
        self.assertIsNone(chunks[1]['section_title'])
        self.assertIsNone(build([document()])[0][0]['page_number'])

    def test_multi_place_and_time_metadata(self):
        chunks, report = build([document(associated_place_ids=['pmq', 'tai-kwun'], source_year=2022,
                                         temporal_note='历史资料')])
        self.assertIsNone(chunks[0]['place_id'])
        self.assertFalse(chunks[0]['include_in_retrieval'])
        self.assertEqual(chunks[0]['source_year'], 2022)
        self.assertEqual(chunks[0]['temporal_note'], '历史资料')
        self.assertEqual(report['review_required_count'], 1)

    def test_rejected_input_and_duplicate_reporting(self):
        chunks, report = build([document(include_in_retrieval=False)])
        self.assertFalse(chunks)
        self.assertEqual(report['excluded_document_count'], 1)
        with self.assertRaises(ValueError):
            build([document(), document()])
        _, report = build([document(), document(document_id='second')])
        self.assertEqual(len(report['duplicate_text_groups']), 1)
        with self.assertRaises(ValueError):
            build([document()], size=100, overlap=100)

    def test_hard_split_and_empty_pages(self):
        text = '[Page 1]\n\n[Page 2]\n' + '字' * 501
        chunks, _ = build([document(text=text)], size=100, overlap=20)
        self.assertEqual(''.join(c['text'] for c in chunks), '字' * 501)
        self.assertTrue(all(c['page_number'] == 2 for c in chunks))

    def test_portable_and_repeatable_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input.jsonl'
            # Local paths are deliberately not copied into deployable chunks.
            source.write_text(json.dumps(document(raw_file='/Users/someone/file.pdf')), encoding='utf-8')
            script = str(Path(__file__).resolve().parents[1] / 'scripts/knowledge/build_chunks.py')
            args = [sys.executable, script, '--input', str(source), '--output', str(root / 'export')]
            subprocess.run(args, check=True, capture_output=True, cwd=root)
            first = (root / 'export' / 'chunks.jsonl').read_bytes()
            subprocess.run(args, check=True, capture_output=True, cwd=root)
            self.assertEqual(first, (root / 'export' / 'chunks.jsonl').read_bytes())
            self.assertNotIn(b'/Users/', first)
            moved = root / 'moved'
            (root / 'export').rename(moved)
            source.unlink()
            self.assertEqual(json.loads((moved / 'chunks.jsonl').read_text())['document_id'], 'sample')


if __name__ == '__main__':
    unittest.main()
