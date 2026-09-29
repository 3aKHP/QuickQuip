"""GitHub 导入：仓库 URL 解析与 codeload zip 下载。

只放行 github.com / codeload.github.com：URL 各段过 ``^[A-Za-z0-9_.-]+$``
校验后由本模块自行构造 codeload 下载地址（``HEAD`` 免 API 查默认分支），
不跟随重定向，宿主机不会被诱导访问其他域名。流式硬上限与摄取护栏共用
``skill_import.MAX_IMPORT_TOTAL_BYTES``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from quickquip.app.web.skill_import import MAX_IMPORT_TOTAL_BYTES

_GITHUB_TIMEOUT_SECONDS = 20.0
_GITHUB_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_HOSTS = {"github.com", "www.github.com"}


@dataclass(frozen=True, slots=True)
class GithubTarget:
    """GitHub 导入目标；``ref`` 为空表示默认分支（下载时用 HEAD）。"""

    owner: str
    repo: str
    ref: str = ""
    subpath: str = ""


def parse_github_url(url: str) -> GithubTarget:
    """解析 ``https://github.com/<owner>/<repo>[/tree/<ref>[/<subpath>]]``。

    各段必须匹配 ``^[A-Za-z0-9_.-]+$``；``/blob/`` 形态拒绝并引导改用
    仓库或目录链接。非 github.com 域名一律 422。
    """
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.hostname not in _GITHUB_HOSTS:
        raise HTTPException(
            status_code=422,
            detail="only https://github.com/<owner>/<repo>[/tree/<ref>[/<subpath>]] "
            "URLs are supported",
        )
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        raise HTTPException(status_code=422, detail="github URL must include owner and repository")
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    ref = ""
    subpath = ""
    rest = segments[2:]
    if rest:
        marker = rest[0]
        if marker == "blob":
            raise HTTPException(
                status_code=422,
                detail="blob URLs point to a single file; use the repository or tree URL instead",
            )
        if marker != "tree" or len(rest) < 2:
            raise HTTPException(
                status_code=422,
                detail="unsupported github URL; use "
                "https://github.com/<owner>/<repo>[/tree/<ref>[/<subpath>]]",
            )
        ref = rest[1]
        subpath = "/".join(rest[2:])
    check_segments = [owner, repo]
    if rest:
        check_segments.extend(rest[1:])
    for segment in check_segments:
        if not _GITHUB_SEGMENT_RE.fullmatch(segment):
            raise HTTPException(
                status_code=422, detail=f"github URL contains an invalid segment: {segment}"
            )
    return GithubTarget(owner=owner, repo=repo, ref=ref, subpath=subpath)


def download_github_zip(target: GithubTarget) -> bytes:
    """经 codeload.github.com 下载仓库 zip（流式硬上限 32MiB，超时 20s）。

    失败文案区分网络不可达/超时（提示部署机出境连通性）、仓库不存在（404）、
    其他上游状态与超限（422）。
    """
    ref = target.ref or "HEAD"
    url = f"https://codeload.github.com/{target.owner}/{target.repo}/zip/{ref}"
    try:
        with httpx.Client(timeout=_GITHUB_TIMEOUT_SECONDS, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    raise HTTPException(
                        status_code=502,
                        detail="unexpected redirect from github; refusing to follow",
                    )
                if response.status_code == 404:
                    raise HTTPException(
                        status_code=502,
                        detail="repository or ref not found on github.com "
                        "(private repositories are not supported)",
                    )
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=f"github download failed with status {response.status_code}",
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_IMPORT_TOTAL_BYTES:
                        raise HTTPException(
                            status_code=422,
                            detail=f"repository archive exceeds the "
                            f"{MAX_IMPORT_TOTAL_BYTES}-byte download limit",
                        )
                    chunks.append(chunk)
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=502,
            detail="timed out reaching github.com; check outbound network "
            "connectivity from the deployment host",
        ) from None
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="cannot reach github.com; check outbound network "
            "connectivity from the deployment host",
        ) from None
    return b"".join(chunks)
