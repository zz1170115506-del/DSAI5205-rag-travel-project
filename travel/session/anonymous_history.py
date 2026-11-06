"""Bounded, temporary conversation capabilities, separate from private archives."""
from collections import OrderedDict
import json
import time


class AnonymousHistory:
    def __init__(self, capacity=25, ttl=1800, protected=lambda: set()):
        self.capacity, self.ttl, self.protected = capacity, ttl, protected
        self.entries = OrderedDict()

    def prune(self):
        now, protected = time.monotonic(), self.protected()
        for cid, (updated, _) in list(self.entries.items()):
            if now-updated >= self.ttl and cid not in protected:
                del self.entries[cid]

    def get(self, cid):
        if time.monotonic()-self.entries[cid][0] >= self.ttl:
            del self.entries[cid]
            raise KeyError(cid)
        self.prune()
        _, payload = self.entries[cid]
        return json.loads(payload)

    def save(self, cid, turns, checkpoint, model, title):
        self.prune()
        payload = json.dumps({'id': cid, 'turns': turns[-20:], 'checkpoint': checkpoint,
                              'use_model': model, 'title': title[:60]}, ensure_ascii=False)
        if len(payload) > 2_000_000:
            raise ValueError('对话过大，请开始新对话。')
        if cid not in self.entries and len(self.entries) >= self.capacity:
            victim = next((key for key in self.entries if key not in self.protected()), None)
            if victim is None:
                raise ValueError('临时会话繁忙，请稍后重试。')
            del self.entries[victim]
        self.entries[cid] = (time.monotonic(), payload)
        self.entries.move_to_end(cid)
        return cid
