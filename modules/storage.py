"""
去重存储模块
管理已推送岗位记录，防止重复推送
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 默认已推送记录文件
DEFAULT_SEEN_FILE = "data/seen_jobs.json"

# 默认去重窗口
DEFAULT_DEDUP_DAYS = 30


def _load(filepath: str) -> dict:
    """加载已推送记录文件"""
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"读取 {filepath} 失败，使用空记录: {e}")
        return {}


def _save(data: dict, filepath: str):
    """保存已推送记录"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _job_key(job: dict) -> str:
    """为岗位生成去重 key：平台+岗位ID"""
    return f"{job.get('platform', 'unknown')}:{job.get('job_id', '')}"


def is_seen(job: dict, filepath: str = DEFAULT_SEEN_FILE, dedup_days: int = DEFAULT_DEDUP_DAYS) -> bool:
    """
    检查岗位是否已在去重窗口内推送过

    Args:
        job: 岗位字典，必须包含 platform 和 job_id
        filepath: 记录文件路径
        dedup_days: 去重窗口天数

    Returns:
        True 表示已推送过，应跳过
    """
    data = _load(filepath)
    key = _job_key(job)
    if key not in data:
        return False

    last_push = data[key]
    try:
        last_date = datetime.fromisoformat(last_push)
    except (ValueError, TypeError):
        return False

    cutoff = datetime.now() - timedelta(days=dedup_days)
    return last_date > cutoff


def mark_seen(job: dict, filepath: str = DEFAULT_SEEN_FILE):
    """标记岗位为已推送"""
    data = _load(filepath)
    key = _job_key(job)
    data[key] = datetime.now().isoformat()
    _save(data, filepath)


def filter_new_jobs(jobs: list[dict], filepath: str = DEFAULT_SEEN_FILE, dedup_days: int = DEFAULT_DEDUP_DAYS) -> list[dict]:
    """
    过滤掉已经推送过的岗位

    Returns:
        仅包含未推送岗位的列表
    """
    new_jobs = []
    skipped = 0
    for job in jobs:
        if is_seen(job, filepath, dedup_days):
            skipped += 1
        else:
            new_jobs.append(job)
    logger.info(f"去重: {len(jobs)} 个岗位中，跳过 {skipped} 个已推送，剩余 {len(new_jobs)} 个新岗位")
    return new_jobs


def mark_all_seen(jobs: list[dict], filepath: str = DEFAULT_SEEN_FILE):
    """批量标记岗位为已推送"""
    for job in jobs:
        mark_seen(job, filepath)


def get_stats(filepath: str = DEFAULT_SEEN_FILE) -> dict:
    """获取存储统计信息"""
    data = _load(filepath)
    return {
        "total_seen": len(data),
        "file": filepath,
    }
