from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.send_core.account_pool import AccountPool, Account
from core.send_core.rate_limiter import RateLimiter
from core.send_core.content_risk import ContentRisk
from core.send_core.failure_retry import FailureCategory, FailureRetryPolicy
from core.send_core.ban_detector import BanDetector
from core.send_core.task_status import SendStatus, TaskStatusStore
from core.send_core.send_pipeline import SendPipeline


# ------------------------------------------------------------
# Mock Redis — 仅实现 pipeline 所需的最小 API
# ------------------------------------------------------------


@dataclass
class _MockRedis:
    data: dict = field(default_factory=dict)

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value, ex=None, *args, **kwargs):
        self.data[key] = str(value)

    def incr(self, key: str) -> int:
        cur = int(self.data.get(key) or 0) + 1
        self.data[key] = str(cur)
        return cur

    def expire(self, key: str, seconds: int):
        return True

    def pipeline(self):
        return _MockPipeline(self)


@dataclass
class _MockPipeline:
    client: _MockRedis
    calls: list = field(default_factory=list)

    def incr(self, key):
        self.calls.append(lambda c=key: self.client.incr(c))
        return self

    def set(self, key, value, ex=None):
        self.calls.append(lambda k=key, v=value: self.client.set(k, v))
        return self

    def expire(self, key, seconds):
        return self

    def execute(self):
        results = []
        for call in self.calls:
            try:
                results.append(call())
            except Exception as exc:
                results.append(exc)
        self.calls = []
        return results


def _make_rate(global_daily=10000, account_daily=10000, account_hourly=10000, user_gap=0):
    return RateLimiter(
        global_daily=global_daily, account_daily=account_daily,
        account_hourly=account_hourly, user_gap_seconds=user_gap,
        redis_client=_MockRedis(),
    )


def _make_status():
    return TaskStatusStore(ttl_seconds=300, redis_client=_MockRedis())


def _in_mem_accounts(channel="wechat", count=2):
    pool = AccountPool(default_quota=10000)
    for i in range(count):
        pool.register_account(Account(
            channel=channel, account_id=f"{channel}_{i}", token="t_{i}", daily_quota=10000,
        ))
    return pool


class _MockAlert:
    def __init__(self): self.calls = []
    def service_exception_sync(self, service_name, message, extra=None):
        self.calls.append(message)


# ------------------------------------------------------------
# 1. AccountPool
# ------------------------------------------------------------


def test_account_pool_picks_account_and_round_robin():
    pool = _in_mem_accounts("wechat", 2)
    picks = [pool.pick("wechat") for _ in range(4)]
    ids = [p.account_id for p in picks]
    assert ids.count("wechat_0") >= 1
    assert ids.count("wechat_1") >= 1


def test_account_pool_banned_account_skipped():
    pool = _in_mem_accounts("feishu", 2)
    pool.mark_banned("feishu", "feishu_0", reason="test")
    for _ in range(5):
        assert pool.pick("feishu").account_id == "feishu_1"


# ------------------------------------------------------------
# 2. RateLimiter
# ------------------------------------------------------------


def test_rate_limiter_allows_then_blocks():
    rate = _make_rate(global_daily=5)
    for _ in range(5):
        assert rate.check_and_increment(account_id="a1").allowed is True
    assert rate.check_and_increment(account_id="a1").allowed is False


def test_rate_limiter_user_gap_blocks():
    rate = _make_rate(user_gap=60)
    assert rate.check_and_increment(account_id="a1", user_id="u1").allowed is True
    res = rate.check_and_increment(account_id="a1", user_id="u1")
    assert res.allowed is False


# ------------------------------------------------------------
# 3. ContentRisk
# ------------------------------------------------------------


def test_content_risk_bad_keyword_blocks():
    risk = ContentRisk(pii_mask=None)
    res = risk.check_content("这是一条包含返利的宣传语", "13800000001")
    assert res.is_blocked is True


def test_content_risk_normal_content_passes():
    risk = ContentRisk(pii_mask=None)
    res = risk.check_content("我们提供服务器，欢迎咨询", "tom@example.com")
    assert res.is_blocked is False


# ------------------------------------------------------------
# 4. FailureRetryPolicy
# ------------------------------------------------------------


def test_failure_retry_network_three_times():
    policy = FailureRetryPolicy(max_network_attempts=3, network_base_delay=0.001)
    for n in range(3):
        assert policy.decide(FailureCategory.NETWORK, n).should_retry is True
    assert policy.decide(FailureCategory.NETWORK, 3).should_retry is False


def test_failure_retry_ban_no_retry():
    policy = FailureRetryPolicy(max_network_attempts=3)
    assert policy.decide(FailureCategory.BAN, 0).should_retry is False
    assert policy.decide(FailureCategory.CONTENT, 0).should_retry is False


def test_failure_retry_classify_from_response():
    policy = FailureRetryPolicy()
    assert policy.classify(status_code=429) == FailureCategory.RATE_LIMITED
    assert policy.classify(status_code=500) == FailureCategory.NETWORK
    assert policy.classify(status_code="BANNED") == FailureCategory.BAN
    assert policy.classify(response_text="内容违规") == FailureCategory.CONTENT


# ------------------------------------------------------------
# 5. BanDetector
# ------------------------------------------------------------


def test_ban_detector_keyword_match():
    bd = BanDetector()
    res = bd.detect_from_response(status_code=403, response_text="账号被限制，请联系客服")
    assert res.is_ban is True


def test_ban_detector_consecutive_network_failure():
    bd = BanDetector(consecutive_fail=2)
    assert bd.record_network_failure("acc1") is False  # 计数 1
    assert bd.record_network_failure("acc1") is True   # 计数 2，达到阈值


# ------------------------------------------------------------
# 6. TaskStatusStore
# ------------------------------------------------------------


def test_task_status_store_crud():
    store = _make_status()
    store.mark_sending("task_1", channel="wechat", account_id="wx_a")
    store.mark_success("task_1", channel="wechat", account_id="wx_a")
    got = store.get_status("task_1")
    assert got is not None
    assert got.status == SendStatus.SUCCESS.value


# ------------------------------------------------------------
# 7. SendPipeline 端到端
# ------------------------------------------------------------


def test_pipeline_success_case():
    pipeline = SendPipeline(
        account_pool=_in_mem_accounts("wechat", 2),
        rate_limiter=_make_rate(),
        content_risk=ContentRisk(pii_mask=None),
        failure_retry=FailureRetryPolicy(max_network_attempts=3, network_base_delay=0.001),
        ban_detector=BanDetector(consecutive_fail=5),
        task_status=_make_status(),
        alert_service=_MockAlert(),
        max_total_attempts=3,
    )
    res = pipeline.send(
        task_id="t1", channel="wechat", content="这是一条普通消息",
        recipient="user@example.com",
        sender_fn=lambda **kw: (True, "200", "sent"),
    )
    assert res.success is True
    assert res.final_status == "SUCCESS"


def test_pipeline_content_block_case():
    pipeline = SendPipeline(
        account_pool=_in_mem_accounts("wechat", 2),
        rate_limiter=_make_rate(),
        content_risk=ContentRisk(pii_mask=None),
        failure_retry=FailureRetryPolicy(max_network_attempts=2),
        ban_detector=BanDetector(consecutive_fail=5),
        task_status=_make_status(),
        alert_service=_MockAlert(),
        max_total_attempts=2,
    )
    res = pipeline.send(
        task_id="t2", channel="wechat", content="这是一条包含返利的宣传语",
        recipient="user@example.com",
        sender_fn=lambda **kw: (True, "200", "never_called"),
    )
    assert res.success is False
    assert res.final_status == "CONTENT_BLOCKED"


def test_pipeline_network_retry_then_fail():
    attempts_left = {"n": 3}
    def fail_sender(**kw):
        attempts_left["n"] -= 1
        return (False, "NETWORK_ERROR", "timeout")

    pipeline = SendPipeline(
        account_pool=_in_mem_accounts("wechat", 2),
        rate_limiter=_make_rate(),
        content_risk=ContentRisk(pii_mask=None),
        failure_retry=FailureRetryPolicy(max_network_attempts=3, network_base_delay=0.001),
        ban_detector=BanDetector(consecutive_fail=10),
        task_status=_make_status(),
        alert_service=_MockAlert(),
        max_total_attempts=3,
    )
    res = pipeline.send(
        task_id="t3", channel="wechat", content="正常内容",
        recipient="user@example.com", sender_fn=fail_sender,
    )
    assert res.success is False
    assert res.attempts >= 3
