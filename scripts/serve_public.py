"""Single-process cloud demo entry point; requires explicit public configuration."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import uvicorn
from travel.web_access import WebAccess


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    access = WebAccess.from_env()
    if not access.public:
        raise SystemExit('此入口需要 PUBLIC_DEMO=true 和固定 HTTPS 网址；本机请使用 run.py。')
    port = int(os.getenv('PORT', '10000'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT 无效。')
    uvicorn.run('app:app', host='0.0.0.0', port=port, workers=1,
                access_log=False, proxy_headers=False)


if __name__ == '__main__':
    main()
