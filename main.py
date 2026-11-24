"""程序入口：默认启动图形界面，带 --cli 参数时跑批处理（等价原 run.py）。"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.cli import main as cli_main  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    if "--cli" in argv:
        return cli_main([a for a in argv if a != "--cli"])
    from app.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
