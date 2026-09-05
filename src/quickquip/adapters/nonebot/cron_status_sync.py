"""Cron 调度状态的跨进程共享。

调度器活在 bot 进程内存里，web-admin 是独立进程，无法直接读取。
仿 mcp_status.json：bot 进程定时把任务快照与最近执行结果原子落盘，
web 端 cron-dashboard 路由只读该文件。
"""

import json
import logging
from datetime import datetime

from quickquip.common.paths import CRON_JOBS_JSON_PATH

logger = logging.getLogger(__name__)

CRON_STATUS_SYNC_JOB_ID = "cron_status_sync"


def sync_cron_status_file(scheduler, job_results: dict) -> None:
    """把调度器任务快照写入共享状态文件（供 web-admin 跨进程读取）。Best-effort。"""
    if not scheduler:
        return
    try:
        jobs = []
        for job in scheduler.get_jobs():
            job_id = getattr(job, "id", None)
            if not job_id or job_id == CRON_STATUS_SYNC_JOB_ID:
                continue
            next_run = getattr(job, "next_run_time", None)
            result = job_results.get(job_id, {})
            jobs.append({
                "id": job_id,
                "name": getattr(job, "name", None) or job_id,
                "trigger": str(getattr(job, "trigger", "")),
                "next_run": next_run.isoformat() if next_run else None,
                "last_run": result.get("last_run"),
                "last_status": result.get("last_status"),
                "last_error": result.get("last_error"),
            })
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(),
            "jobs": jobs,
        }
        path = CRON_JOBS_JSON_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)
    except Exception:
        logger.warning("cron_status: failed to write status file", exc_info=True)


def load_job_results(path=None) -> dict[str, dict]:
    """从共享状态文件读回各任务的最近执行结果（bot 重启恢复，#200）。

    文件缺失 = 首次启动，静默返回空；损坏 = 告警返回空（不阻塞调度）。
    跳过「未执行」的行（last_run 为空）——尚未跑过的任务重启后仍是未执行；
    跳过 naive/无法解析的 last_run——时间语义保持带时区 ISO 8601。
    path 默认值在调用期解析，便于测试 monkeypatch CRON_JOBS_JSON_PATH。
    """
    file_path = path or CRON_JOBS_JSON_PATH
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        logger.warning("cron_status: failed to read status file for restore", exc_info=True)
        return {}
    results: dict[str, dict] = {}
    jobs = data.get("jobs") if isinstance(data, dict) else None
    for entry in jobs if isinstance(jobs, list) else []:
        if not isinstance(entry, dict):
            continue
        job_id = entry.get("id")
        last_run = entry.get("last_run")
        # last_run 必须是非空 str：fromisoformat 对 int 等真值抛 TypeError，
        # 会击穿调用侧（恢复块无兜底，中断 scheduler_plugin 模块导入）
        if not isinstance(job_id, str) or not isinstance(last_run, str) or not last_run:
            continue
        try:
            if datetime.fromisoformat(last_run).tzinfo is None:
                continue
        except ValueError:
            continue
        last_status = entry.get("last_status")
        last_error = entry.get("last_error")
        results[job_id] = {
            "last_run": last_run,
            # 状态/错误归一：本模块与 record_job_result 的取值域（ok|error|None；
            # str|None），手改文件灌入的其它类型不进内存表
            "last_status": last_status if last_status in ("ok", "error") else None,
            "last_error": last_error if isinstance(last_error, str) else None,
        }
    return results


def register_cron_status_sync(scheduler, job_results: dict) -> None:
    """注册定时落盘 job（每 30 秒），驱动 web-admin 定时任务页的数据源。"""
    scheduler.add_job(
        lambda: sync_cron_status_file(scheduler, job_results),
        "interval",
        seconds=30,
        id=CRON_STATUS_SYNC_JOB_ID,
        replace_existing=True,
    )
    logger.info("cron_status: sync job registered (every 30s)")
