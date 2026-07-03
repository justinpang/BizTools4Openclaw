"""business/sales_task — T12 销售商机调度/自动分配/多级跟进提醒/逾期告警闭环。"""

from business.sales_task.assignment_engine import AssignmentEngine
from business.sales_task.funnel_engine import FunnelEngine
from business.sales_task.models import (
    FunnelStats,
    FollowUpRecord,
    Opportunity,
    OpportunityStatus,
    ReminderLevel,
    ReminderParams,
    SalesOperationLog,
    SalesTaskJobResult,
    Salesperson,
)
from business.sales_task.pipeline import SalesTaskPipeline
from business.sales_task.push_notifier import PushNotifier
from business.sales_task.registry import (
    add_tag,
    async_run,
    assign,
    get_funnel_stats,
    record_follow_up,
    remind,
    remove_tag,
    run_batch,
    transition,
)
from business.sales_task.reminder_engine import ReminderEngine
from business.sales_task.status_engine import StatusEngine
from business.sales_task.storage import SendStorage

__all__ = [
    # 入口
    "run_batch",
    "async_run",
    "assign",
    "remind",
    "get_funnel_stats",
    "transition",
    "add_tag",
    "remove_tag",
    "record_follow_up",
    # 引擎
    "SalesTaskPipeline",
    "AssignmentEngine",
    "ReminderEngine",
    "StatusEngine",
    "FunnelEngine",
    "PushNotifier",
    # 存储
    "SendStorage",
    # 模型
    "Salesperson",
    "Opportunity",
    "OpportunityStatus",
    "FollowUpRecord",
    "SalesOperationLog",
    "ReminderLevel",
    "ReminderParams",
    "FunnelStats",
    "SalesTaskJobResult",
]
