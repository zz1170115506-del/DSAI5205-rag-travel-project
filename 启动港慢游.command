#!/bin/zsh
cd -- "${0:A:h}" || exit 1
# 优先使用系统 Python；Codex 用户可使用随应用提供的 Python。
TRAVEL_PYTHON="$(command -v python3)"
TRAVEL_BUNDLED="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ -z "$TRAVEL_PYTHON" ]] || ! "$TRAVEL_PYTHON" -c 'import sys; assert sys.version_info >= (3,11)' 2>/dev/null; then
  TRAVEL_PYTHON="$TRAVEL_BUNDLED"
fi
if [[ ! -x "$TRAVEL_PYTHON" ]]; then
  print '未找到 Python 3.11+。请先安装 Python，再双击本文件。'
  read '?按回车退出。'
  exit 1
fi
"$TRAVEL_PYTHON" start.py
if [[ $? -ne 0 ]]; then
  print '\n启动未成功。请查看上面的提示；端口已使用时，可先打开 http://127.0.0.1:8765。'
  read '?按回车退出。'
fi
