from __future__ import annotations

import asyncio

from quickquip.tieba.errors import TiebaServiceError
from quickquip.tieba.service import tieba_service


async def _main() -> int:
    try:
        await tieba_service.interactive_login()
    except TiebaServiceError as exc:
        print(f"贴吧登录准备失败：{exc}")
        return 1
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
