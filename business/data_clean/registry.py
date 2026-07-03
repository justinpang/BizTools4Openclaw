from __future__ import annotations

from business.data_clean.models import CleanRunResult, CleanTaskParams
from business.data_clean.pipeline import DataCleanPipeline


def run_cleaning(params, *, raw_records=None):
    if isinstance(params, dict):
        p = CleanTaskParams(**params)
    else:
        p = params
    pipeline = DataCleanPipeline()
    return pipeline.run(p, raw_records=raw_records)


def list_runs() -> list[str]:
    """（预留）列出已完成的清洗任务 —— 目前返回空列表。"""
    return []


__all__ = ["run_cleaning", "list_runs"]
