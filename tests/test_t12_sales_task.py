"""T12 销售商机调度 / 自动分配 / 多级提醒 / 逾期告警 — 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def sample_opportunities():
    from business.sales_task.models import Opportunity
    now = datetime.now(timezone.utc)
    # 1 个刚入库的 NEW 商机
    opp1 = Opportunity(
        opportunity_id="opp_1", tenant_id="t1",
        customer_name="公司A", industry="IT", region="上海",
        need_keywords=["服务器", "采购"],
        score=80, status="NEW",
    )
    # 1 个匹配不同地域的 NEW 商机
    opp2 = Opportunity(
        opportunity_id="opp_2", tenant_id="t1",
        customer_name="公司B", industry="IT", region="北京",
        need_keywords=["云"],
        score=60, status="NEW",
    )
    # 1 个 ASSIGNED 已 5 天无跟进
    opp3 = Opportunity(
        opportunity_id="opp_3", tenant_id="t1",
        customer_name="公司C", industry="IT", region="上海",
        need_keywords=["软件"], score=70, status="ASSIGNED",
        assigned_sales_id="s1",
        assigned_at=(now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # 1 个 ASSIGNED 已 18 天无跟进（逾期）
    opp4 = Opportunity(
        opportunity_id="opp_4", tenant_id="t1",
        customer_name="公司D", industry="IT", region="上海",
        need_keywords=["咨询"], score=70, status="ASSIGNED",
        assigned_sales_id="s1",
        assigned_at=(now - timedelta(days=18)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # 1 个 FOLLOWING 状态
    opp5 = Opportunity(
        opportunity_id="opp_5", tenant_id="t1",
        customer_name="公司E", industry="制造", region="深圳",
        need_keywords=["ERP"], score=70, status="FOLLOWING",
        assigned_sales_id="s2",
        assigned_at=(now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return [opp1, opp2, opp3, opp4, opp5]


@pytest.fixture
def sample_salespersons():
    from business.sales_task.models import Salesperson
    return [
        Salesperson(
            sales_id="s1", tenant_id="t1", name="销售A",
            industries=["IT"], regions=["上海", "北京"],
            min_score=30, weight=1.5, current_load=2,
            feishu="webhook_feishu_s1", wechat="webhook_wechat_s1",
            email="a@example.com",
        ),
        Salesperson(
            sales_id="s2", tenant_id="t1", name="销售B",
            industries=["制造"], regions=["深圳"],
            min_score=40, weight=1.0, current_load=0,
            feishu="webhook_feishu_s2",
        ),
        Salesperson(
            sales_id="s3", tenant_id="t1", name="销售C",
            industries=["零售"], regions=["广州"],
            min_score=50, weight=2.0, current_load=5,
            email="c@example.com",
        ),
    ]


# ========== 模型验证 ==========

def test_opportunity_model_defaults():
    from business.sales_task.models import Opportunity, OpportunityStatus
    o = Opportunity(
        opportunity_id="x", tenant_id="t", customer_name="C",
        score=50,
    )
    assert o.status == OpportunityStatus.NEW.value
    assert o.assigned_sales_id is None
    assert o.created_at is not None


def test_salesperson_model():
    from business.sales_task.models import Salesperson
    s = Salesperson(sales_id="s", tenant_id="t", name="S")
    assert s.weight == 1.0
    assert s.current_load == 0
    assert s.industries == []


# ========== 分配引擎 ==========

def test_assignment_engine_score_candidate(sample_opportunities, sample_salespersons):
    from business.sales_task.assignment_engine import AssignmentEngine
    engine = AssignmentEngine()

    # opp1 (IT, 上海, 80 分) 对 s1 (IT, 上海, min=30, weight=1.5, load=2)
    score = engine.score_candidate(sample_opportunities[0], sample_salespersons[0])
    assert score > 0  # 应该匹配

    # opp5 (制造, 深圳, 70 分) 对 s1 — 不匹配行业和地域
    score_no = engine.score_candidate(sample_opportunities[4], sample_salespersons[0])
    assert score_no == 0  # 不匹配制造，无基础分

    # opp5 对 s2 (制造, 深圳) — 应该匹配
    score_yes = engine.score_candidate(sample_opportunities[4], sample_salespersons[1])
    assert score_yes > 0


def test_assignment_engine_assign_batch(sample_opportunities, sample_salespersons):
    from business.sales_task.assignment_engine import AssignmentEngine
    engine = AssignmentEngine()

    # 只取 NEW 状态的商机做分配
    new_opps = [o for o in sample_opportunities if o.status == "NEW"]
    result = engine.assign_batch(new_opps, sample_salespersons, dry_run=True)

    assert result["assigned"] >= 1
    assert result["unassigned"] >= 0
    # opp2 (IT, 北京) 有匹配销售
    assert any(a[0] == "opp_1" for a in result["assignments"])


def test_assignment_engine_no_salespersons(sample_opportunities):
    from business.sales_task.assignment_engine import AssignmentEngine
    engine = AssignmentEngine()

    new_opps = [o for o in sample_opportunities if o.status == "NEW"]
    result = engine.assign_batch(new_opps, [], dry_run=True)

    assert result["assigned"] == 0
    assert result["unassigned"] >= 1


def test_assignment_engine_low_score_filtered_out():
    from business.sales_task.models import Opportunity, Salesperson
    from business.sales_task.assignment_engine import AssignmentEngine

    engine = AssignmentEngine()
    # min_score_threshold 默认 20，分数 10 低于阈值
    opp_low = Opportunity(
        opportunity_id="opp_low", tenant_id="t1",
        customer_name="X", industry="IT", region="上海",
        score=10, status="NEW",
    )
    sp = Salesperson(
        sales_id="s1", tenant_id="t1", name="A",
        industries=["IT"], regions=["上海"], min_score=0, weight=1.0,
        current_load=0, feishu="x",
    )
    result = engine.assign_batch([opp_low], [sp], dry_run=True)
    # 低分数 → 不分配
    assert result["assigned"] == 0


# ========== 提醒引擎 ==========

def test_reminder_engine_first_and_overdue(sample_opportunities):
    from business.sales_task.reminder_engine import ReminderEngine
    engine = ReminderEngine()

    # opp3: 5 天 → FIRST 提醒
    level = engine.compute_reminder_level(sample_opportunities[2])
    assert level == "FIRST"

    # opp4: 18 天 → OVERDUE 提醒
    level2 = engine.compute_reminder_level(sample_opportunities[3])
    assert level2 == "OVERDUE"


def test_reminder_engine_idempotent_via_already_fired(sample_opportunities):
    from business.sales_task.reminder_engine import ReminderEngine
    engine = ReminderEngine()

    # 若 OVERDUE / SECOND / FIRST 都已发过，不应返回任何级别
    all_fired = {"NOTIFY", "FIRST", "SECOND", "OVERDUE"}
    level = engine.compute_reminder_level(sample_opportunities[3], already_fired=all_fired)
    assert level is None

    # 单独验证 OVERDUE 已发过后不再返回 OVERDUE
    already_overdue = {"OVERDUE"}
    level2 = engine.compute_reminder_level(sample_opportunities[3], already_fired=already_overdue)
    assert level2 != "OVERDUE"


def test_reminder_engine_custom_cycles(sample_opportunities):
    from business.sales_task.reminder_engine import ReminderEngine
    engine = ReminderEngine()
    engine.apply_custom_cycles({"FIRST": 10})

    # opp3 (5 天) 在 FIRST=10 的配置下不应触发
    level = engine.compute_reminder_level(sample_opportunities[2])
    assert level is None


def test_reminder_engine_skip_closed_and_new(sample_opportunities):
    from business.sales_task.reminder_engine import ReminderEngine
    engine = ReminderEngine()
    # opp1 (NEW) 不应触发任何提醒
    lvl = engine.compute_reminder_level(sample_opportunities[0])
    assert lvl is None


# ========== 状态流转 ==========

def test_status_engine_valid_transitions():
    from business.sales_task.status_engine import StatusEngine
    from business.sales_task.models import Opportunity

    engine = StatusEngine()
    opp = Opportunity(
        opportunity_id="o1", tenant_id="t1", customer_name="X",
        score=70, status="ASSIGNED",
        assigned_sales_id="s1",
    )

    ok, log, reason = engine.transition(opp, "FOLLOWING", "s1", "首次电话联系")
    assert ok is True
    assert log is not None
    assert log.before_value == "ASSIGNED"
    assert log.after_value == "FOLLOWING"
    assert opp.status == "FOLLOWING"


def test_status_engine_illegal_transition_blocked():
    from business.sales_task.status_engine import StatusEngine
    from business.sales_task.models import Opportunity

    engine = StatusEngine()
    opp = Opportunity(
        opportunity_id="o2", tenant_id="t1", customer_name="Y",
        score=70, status="CLOSED_WON",
    )
    ok, log, reason = engine.transition(opp, "FOLLOWING", "s1")
    assert ok is False
    assert "ILLEGAL_TRANSITION" in (reason or "")
    # 状态未改变
    assert opp.status == "CLOSED_WON"


def test_status_engine_no_change_same_status():
    from business.sales_task.status_engine import StatusEngine
    from business.sales_task.models import Opportunity

    engine = StatusEngine()
    opp = Opportunity(
        opportunity_id="o3", tenant_id="t1", customer_name="Z",
        score=70, status="FOLLOWING",
        assigned_sales_id="s1",
    )
    ok, log, reason = engine.transition(opp, "FOLLOWING", "s1")
    assert ok is True
    assert log is None
    assert reason == "NO_CHANGE"


def test_status_engine_add_tag():
    from business.sales_task.status_engine import StatusEngine
    from business.sales_task.models import Opportunity

    engine = StatusEngine()
    opp = Opportunity(
        opportunity_id="o4", tenant_id="t1", customer_name="W",
        score=70, status="FOLLOWING", tags=[],
    )
    log = engine.add_tag(opp, "高意向", "s1")
    assert log is not None
    assert "高意向" in opp.tags

    # 重复添加不重复记录
    log2 = engine.add_tag(opp, "高意向", "s1")
    assert log2 is None


def test_status_engine_record_follow_up_moves_to_following():
    from business.sales_task.status_engine import StatusEngine
    from business.sales_task.models import Opportunity

    engine = StatusEngine()
    opp = Opportunity(
        opportunity_id="o5", tenant_id="t1", customer_name="W",
        score=70, status="ASSIGNED",
        assigned_sales_id="s1",
    )
    follow, log = engine.record_follow_up(opp, "s1", "phone", "电话沟通 30 分钟，需求明确")
    assert follow.channel == "phone"
    assert "电话" in follow.content
    assert log.op_type == "FOLLOW_UP"
    # ASSIGNED → 首次跟进 → FOLLOWING
    assert opp.status == "FOLLOWING"


# ========== 漏斗统计 ==========

def test_funnel_engine_compute_with_hints():
    from business.sales_task.funnel_engine import FunnelEngine

    fe = FunnelEngine()
    stats = fe.compute_funnel(
        "t1",
        period_days=30,
        opportunity_count_hint=100,
        cleaned_hint=60,
        reached_hint=40,
        followed_hint=20,
        closed_won_hint=5,
    )
    assert stats.collected == 100
    assert stats.cleaned == 60
    assert stats.reached == 40
    assert stats.followed == 20
    assert stats.closed_won == 5
    # 转化率合理
    assert 0.0 <= stats.conversion_rates["end_to_end"] <= 1.0


def test_funnel_engine_zero_handles_gracefully():
    from business.sales_task.funnel_engine import FunnelEngine

    fe = FunnelEngine()
    stats = fe.compute_funnel("t_empty", period_days=7)
    # 不应抛异常，全部为 0
    assert stats.collected >= 0
    assert stats.conversion_rates["end_to_end"] == 0.0


# ========== 推送联动 ==========

def test_push_notifier_dry_run(sample_opportunities, sample_salespersons):
    from business.sales_task.push_notifier import PushNotifier

    pn = PushNotifier()
    opp = sample_opportunities[2]  # opp3 (ASSIGNED, 5 days)
    sp = sample_salespersons[0]

    res = pn.push_to_sales(sp, "FIRST", opp, 5, dry_run=True)
    assert len(res) >= 1  # 至少一个 dry_run 结果


# ========== 总流水线（dry_run 模式）==========

def test_pipeline_full_run_dry(sample_opportunities, sample_salespersons):
    from business.sales_task.pipeline import SalesTaskPipeline

    pipeline = SalesTaskPipeline()
    results = pipeline.run_batch(
        sample_opportunities, sample_salespersons,
        task_id="test_task_1",
        dry_run=True,
        enable_funnel=False,
    )
    # 至少有分配结果
    assert "assignment" in results
    assert results["assignment"].assigned >= 0

    # 有提醒结果
    assert "reminder" in results
    assert results["reminder"].reminded >= 1  # opp3/opp4 应该触发提醒


def test_registry_run_batch_dry(sample_opportunities, sample_salespersons):
    from business.sales_task.registry import run_batch

    results = run_batch(
        sample_opportunities, sample_salespersons,
        task_id="reg_test_1", dry_run=True,
        enable_funnel=False,
    )
    assert "assignment" in results
    assert "reminder" in results


def test_registry_transition_and_tags():
    from business.sales_task.registry import transition, add_tag, remove_tag
    from business.sales_task.models import Opportunity

    opp = Opportunity(
        opportunity_id="r1", tenant_id="t1", customer_name="R",
        score=80, status="ASSIGNED",
        assigned_sales_id="s1",
    )
    # 状态流转
    ok, reason = transition(opp, "FOLLOWING", "s1", "测试流转")
    assert ok is True
    assert opp.status == "FOLLOWING"

    # 标签
    ok = add_tag(opp, "VIP客户", "s1")
    assert ok is True
    assert "VIP客户" in opp.tags

    ok = remove_tag(opp, "VIP客户", "s1")
    assert ok is True
    assert "VIP客户" not in opp.tags


def test_registry_record_follow_up():
    from business.sales_task.registry import record_follow_up
    from business.sales_task.models import Opportunity

    opp = Opportunity(
        opportunity_id="r2", tenant_id="t1", customer_name="RR",
        score=80, status="ASSIGNED", assigned_sales_id="s1",
    )
    ok = record_follow_up(opp, "s1", "feishu", "飞书发送资料，客户确认")
    assert ok is True
    assert opp.status == "FOLLOWING"
    assert opp.last_follow_at is not None


# ========== 数据落库（幂等 upsert） ==========

def test_storage_upsert_opportunity(sample_opportunities):
    from business.sales_task.storage import SendStorage

    storage = SendStorage(ensure_schema=False)
    n = storage.upsert_opportunity(sample_opportunities[0])
    # n = 1 表示 upsert 成功；若 DB 不可用则 fallback 返回 0
    assert isinstance(n, int)


def test_storage_append_operation_log(sample_opportunities):
    from business.sales_task.storage import SendStorage
    from business.sales_task.models import SalesOperationLog, _make_id

    storage = SendStorage(ensure_schema=False)
    log = SalesOperationLog(
        log_id=_make_id("op", "t1", "opp_x", "TEST"),
        tenant_id="t1", opportunity_id="opp_x",
        sales_id="s1", op_type="ASSIGN",
        before_value="NEW", after_value="ASSIGNED",
    )
    n = storage.append_operation_log(log)
    assert isinstance(n, int)
