from __future__ import annotations

import asyncio

from quickquip.tieba.errors import TiebaServiceError
from quickquip.tieba.service import TiebaService


async def _main() -> int:
    # 独立 CLI 进程：自行构造实例并显式加载帖子池（interactive_login 末尾会 save，
    # 不先 load 会把 pool.json 覆盖成空池）
    service = TiebaService()
    service.load()
    try:
        await service.interactive_login()
    except TiebaServiceError as exc:
        print(f"贴吧登录准备失败：{exc}")
        return 1
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
