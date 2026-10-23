"""首次建环境，之后直接启动。只安装 requirements.txt 指定的公开 PyPI 包。"""
import os
import subprocess
import sys
import venv
import webbrowser
from pathlib import Path
from threading import Timer

ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('需要 Python 3.11 或更新版本，请先安装后重试。')
    env_dir = ROOT / '.venv'
    python = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    marker = env_dir / '.requirements-installed'
    if not python.exists():
        print('第一次启动：创建项目独立环境……', flush=True)
        venv.EnvBuilder(with_pip=True).create(env_dir)
    expected = (ROOT / 'requirements-lock.txt').read_text(encoding='utf-8')
    if not marker.exists() or marker.read_text() != expected:
        print('安装项目依赖，需要联网；不会修改系统 Python。', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'requirements-lock.txt')], check=True)
        marker.write_text(expected)
    print('启动港慢游：http://127.0.0.1:8765\n保留此终端窗口，按 Ctrl+C 停止。', flush=True)
    timer=Timer(2, lambda: webbrowser.open('http://127.0.0.1:8765'))
    timer.daemon=True
    timer.start()
    try:
        subprocess.run([str(python), str(ROOT/'run.py')], cwd=ROOT, check=True)
    except KeyboardInterrupt:
        print('\n港慢游已停止。')


if __name__=='__main__':
    main()
