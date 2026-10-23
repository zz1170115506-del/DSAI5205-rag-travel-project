"""Single-machine conversation persistence. No credentials or live session tokens."""
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT


class HistoryStore:
    def __init__(self, path=None, capacity=25):
        self.path = Path(path or ROOT / 'work' / 'user-data' / 'conversations.sqlite3')
        self.capacity = capacity

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        self.path.chmod(0o600)
        db.execute('CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,updated TEXT NOT NULL,payload TEXT NOT NULL)')
        # Add metadata in place; older archives keep their IDs and original payloads.
        db.execute('BEGIN IMMEDIATE')
        columns={row[1] for row in db.execute('PRAGMA table_info(conversations)')}
        for name in ('favorite','pinned','title_is_custom'):
            if name not in columns:
                db.execute(f'ALTER TABLE conversations ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
        db.commit()
        return db

    def list(self):
        with self.connect() as db:
            return [{'id':r[0],'title':r[1],'updated':r[2],'favorite':bool(r[3]),'pinned':bool(r[4])} for r in db.execute('SELECT id,title,updated,favorite,pinned FROM conversations ORDER BY pinned DESC,updated DESC,id LIMIT ?', (self.capacity,))]

    def get(self, cid):
        with self.connect() as db:
            row = db.execute('SELECT payload,favorite,pinned,title,title_is_custom FROM conversations WHERE id=?', (cid,)).fetchone()
        if not row:
            raise KeyError('conversation not found')
        return {**json.loads(row[0]),'favorite':bool(row[1]),'pinned':bool(row[2]),'title':row[3],'title_is_custom':bool(row[4])}

    def rename(self,cid,title):
        title=title.strip()
        if not 1<=len(title)<=60 or any(ord(c)<32 or ord(c)==127 for c in title):raise ValueError('名称须为 1–60 字，不能包含换行或控制字符。')
        with self.connect() as db:
            result=db.execute('UPDATE conversations SET title=?,title_is_custom=1 WHERE id=?',(title,cid))
            if not result.rowcount:raise KeyError('conversation not found')
        return {'id':cid,'title':title}

    def update_flags(self,cid,*,favorite=None,pinned=None):
        changes={name:int(value) for name,value in {'favorite':favorite,'pinned':pinned}.items() if value is not None}
        if not changes:raise ValueError('请选择收藏或置顶操作。')
        with self.connect() as db:
            result=db.execute('UPDATE conversations SET '+','.join(name+'=?' for name in changes)+' WHERE id=?',(*changes.values(),cid))
            if not result.rowcount:raise KeyError('conversation not found')
        return self.get(cid)

    def save(self, cid, turns, checkpoint, model, title):
        cid = cid or secrets.token_hex(16)
        # Bounded archive; never silently evict another conversation.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            exists = db.execute('SELECT 1 FROM conversations WHERE id=?', (cid,)).fetchone()
            if not exists and db.execute('SELECT count(*) FROM conversations').fetchone()[0] >= self.capacity:
                raise ValueError('历史已达 25 段，请删除一段后再开始新对话。')
            value = {'id': cid, 'turns': turns[-20:], 'checkpoint': checkpoint, 'use_model': model, 'title': title[:60]}
            encoded = json.dumps(value, ensure_ascii=False)
            if len(encoded) > 2_000_000:
                raise ValueError('对话记录过大，请开始新对话。')
            # Continuing a conversation must not erase its favorite/pinned state.
            db.execute('INSERT INTO conversations(id,title,updated,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=CASE WHEN conversations.title_is_custom=1 THEN conversations.title ELSE excluded.title END,updated=excluded.updated,payload=excluded.payload',
                       (cid, title[:60], datetime.now(timezone.utc).isoformat(), encoded))
        return cid

    def delete(self, cid):
        with self.connect() as db:
            # secure_delete removes the row content from ordinary free pages as well.
            db.execute('PRAGMA secure_delete=ON')
            db.execute('DELETE FROM conversations WHERE id=?', (cid,))
