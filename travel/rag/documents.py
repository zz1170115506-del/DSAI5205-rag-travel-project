"""Approved paragraph evidence with BM25, optional local vectors and RRF."""
import json
import sqlite3
from functools import lru_cache

from travel.core.config import ROOT, RetrievalSettings
from travel.rag.embeddings import EmbeddingUnavailable, fingerprint, semantic_search, load_index
from travel.rag.knowledge import places, retrieval_query, tokens
from travel.rag.place_intent import matches_category

CHUNKS = ROOT / 'data/knowledge/chunks.jsonl'
INDEX = ROOT / 'data/indexes/document-embeddings.json'


@lru_cache(maxsize=2)
def _load(path, signature):
    del signature
    records=[]
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row=json.loads(line)
            if row.get('include_in_retrieval') is True and not row.get('review_required'):
                records.append({**row,'id':row['chunk_id'],'evidence_type':'document_paragraph'})
    for place in places():
        records.append({'id':'place-'+place['id'],'chunk_id':'place-'+place['id'],
            'document_id':'catalog-'+place['id'],'place_id':place['id'],
            'title':place['source_title'],'text':place['name']+' / '+place['en']+'\n'+place['summary']+'\n'+place['tip'],
            'source_url':place['source'],'page_number':None,'source_year':None,
            'temporal_note':'Curated snapshot; current arrangements require verification.',
            'evidence_type':'curated_place_record','checked':place['checked']})
    return records


def documents():
    signature=(CHUNKS.stat().st_mtime_ns,CHUNKS.stat().st_size) if CHUNKS.exists() else None
    return _load(CHUNKS,signature)


def document_retrieval_status():
    records=documents();settings=RetrievalSettings.from_env()
    try:
        load_index(records,settings.model_name,INDEX)
        ready,reason=True,None
    except EmbeddingUnavailable as exc:
        ready,reason=False,str(exc)
    return {'paragraph_count':sum(r['evidence_type']=='document_paragraph' for r in records),
            'curated_record_count':sum(r['evidence_type']=='curated_place_record' for r in records),
            'configured_mode':settings.mode,'index_ready':ready,'index_reason':reason}


@lru_cache(maxsize=2)
def _lexical_index(serialized):
    records=json.loads(serialized)
    db=sqlite3.connect(':memory:',check_same_thread=False)
    db.execute('CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, terms)')
    db.executemany('INSERT INTO docs VALUES (?,?)',[(r['id'],' '.join(tokens(r['text']+' '+(r.get('title') or '')))) for r in records])
    db.commit()
    return db


def retrieve_documents(query,place_ids=None,settings=None,limit=8,*,category=None):
    records=documents()
    settings=settings or RetrievalSettings.from_env()
    terms=set(tokens(retrieval_query(query)))
    eligible={p['id'] for p in places() if matches_category(p,category)}
    by_id={r['id']:r for r in records if (not place_ids or r['place_id'] in place_ids)
           and (not category or r['place_id'] in eligible)}
    serialized=json.dumps([{'id':r['id'],'text':r['text'],'title':r.get('title')} for r in records],ensure_ascii=False)
    expression=' OR '.join('"'+t.replace('"','""')+'"' for t in sorted(terms))
    lexical=[]
    if expression:
        # Apply the place constraint before limiting candidates, not after the global top-k.
        rows=_lexical_index(serialized).execute('SELECT id,bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)',(expression,))
        lexical=[key for key,_ in rows if key in by_id][:32]
    ranks=[lexical]
    meta={'mode':'bm25','embedding_used':False,'candidate_count':len(lexical)}
    if settings.mode=='hybrid':
        try:
            dense=semantic_search(query,records,settings,limit=len(records),index_path=INDEX)
            ranks.append([r['id'] for r in dense if r['id'] in by_id][:32])
            meta.update(mode='hybrid',embedding_used=True)
        except EmbeddingUnavailable as exc:
            meta['fallback_reason']=str(exc)
    scores={}
    for ranking in ranks:
        for rank,key in enumerate(ranking,1):
            scores[key]=scores.get(key,0)+1/(60+rank)
    output=[];counts={}
    for key in sorted(scores,key=lambda k:(-scores[k],k)):
        row=by_id[key];doc=row['document_id']
        if counts.get(doc,0)>=3:
            continue
        output.append({**row,'score':scores[key]});counts[doc]=counts.get(doc,0)+1
        if len(output)>=limit:
            break
    meta['corpus_sha256']=fingerprint(records)
    return output,meta
