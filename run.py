"""本机启动入口。禁止把此课程演示直接暴露到公网。"""
import argparse
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='港慢游本地旅行助手')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run('app:app', host='127.0.0.1', port=args.port, access_log=False)
