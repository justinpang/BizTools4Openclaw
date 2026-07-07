"""business/custom_spider — 采集方案管理模块。

核心能力：
  - 方案 CRUD + 版本管理（可回滚）
  - 测试运行（验证规则效果，不入库）
  - 自动采集（调用 T25 规则引擎 → 合规预检 → 入库 spider_raw_data）
  - 定时调度（对接 T03 TaskScheduler）
  - 批量导入导出（JSON 跨环境迁移）
  - 采集效果统计（运行次数、成功次数、总条目数、字段匹配率）

所有底层能力 100% 复用既有模块：
  - core.spider_core (T25)    → 规则引擎 / 页面智能解析 / PDF附件解析
  - infra.task_scheduler (T03) → 定时调度
  - infra.db_models (T04)     → 原始爬虫数据表
  - core.compliance (T06)     → 合规预检 / PII 脱敏
"""

from __future__ import annotations

from business.custom_spider.data_models import (
    CustomSpiderPlan,
    CustomSpiderPlanVersion,
    CustomSpiderRun,
    CustomSpiderOperationLog,
    create_tables,
)
from business.custom_spider.repository import (
    PlanRepository,
    VersionRepository,
    RunRepository,
    LogRepository,
)
from business.custom_spider.service import PlanService, execute_scheduled_plan

__all__ = [
    # ORM 模型
    "CustomSpiderPlan",
    "CustomSpiderPlanVersion",
    "CustomSpiderRun",
    "CustomSpiderOperationLog",
    # 数据库操作
    "PlanRepository",
    "VersionRepository",
    "RunRepository",
    "LogRepository",
    "create_tables",
    # 业务服务
    "PlanService",
    "execute_scheduled_plan",
]
