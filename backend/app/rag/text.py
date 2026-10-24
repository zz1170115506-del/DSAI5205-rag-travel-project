import hashlib
import re

import jieba
from opencc import OpenCC

_converter = OpenCC('t2s')
TOKENIZER_VERSION = 'jieba-0.42.1-opencc-0.1.7-v1'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def normalize(text):
    return ' '.join(_converter.convert(text).lower().split())


def tokens(text):
    return [t for t in jieba.lcut(normalize(text)) if re.search(r'[\w\u4e00-\u9fff]', t)]


def split_text(text, size=500, overlap=80):
    for start in range(0, len(text), size - overlap):
        end = min(start + size, len(text))
        yield start, end, text[start:end]
        if end == len(text):
            break
