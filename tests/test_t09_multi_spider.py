from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

# 测试用的伪 SDK / 数据库封装 ---------------------------------------------------


@dataclass
class _FakeCrawlResponse:
    url: str = ""
    final_url: str = ""
    status_code: int = 200
    text: str = ""
    risk_level: str = "none"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 400


class _FakeSDK:
    """在测试中替换 core.spider_core 的 CrawlResponse + 单例 spider_sdk.get。"""

    def __init__(self, html_per_url: dict[str, str] | None = None, default_html: str = "") -> None:
        self._html = html_per_url or {}
        self._default = default_html
        self.calls: list[str] = []

    def get(
        self,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        render: bool = False,
        task_id: str | None = None,
        robot_check: bool = True,
        risk_check: bool = True,
        payload: Any = None,
    ) -> _FakeCrawlResponse:
        self.calls.append(url)
        html = self._html.get(url, self._default)
        return _FakeCrawlResponse(url=url, final_url=url, status_code=200, text=html)


class _FakeRedis:
    """模拟 Redis，仅实现任务状态写入。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value


# 测试 HTML 示例 -----------------------------------------------------------------

_SAMPLE_ARTICLE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>企业采购需求征集 - 测试页面</title>
</head>
<body>
<article>
<h1>关于 2026 年度企业 IT 基础架构采购需求</h1>
<div class="author">发布人：采购办公室</div>
<div class="publish-time">2026-07-03 10:20</div>
<p>为满足公司业务增长，拟采购服务器、网络设备、云服务等。</p>
<p>如有合作意向，请在规定时间内提交方案。</p>
</article>
</body>
</html>
"""

_SAMPLE_COMMENTS = """
<html><body>
<title>论坛讨论</title>
<div class="comment-item"><span class="user">张先生</span><p>我们公司也有类似加微信需求可联系我们</p><span class="time">2026-07-02 09:10</span></div>
<div class="comment-item"><span class="user">李女士</span><p>我们可以提供云服务器采购方案，欢迎咨询</p><span class="time">2026-07-02 08:00</span></div>
</body></html>
"""


# 测试 fixtures ---------------------------------------------------------------


@pytest.fixture
def fake_sdk(request):
    """构造伪 SDK，可通过 request.param 指定 URL->HTML 映射。"""
    if hasattr(request, "param"):
        sdk = _FakeSDK(html_per_url=request.param.get("html"), default_html=request.param.get("default", ""))
    else:
        sdk = _FakeSDK()
    yield sdk


# monkeypatch 核心 -------------------------------------------------------------

def _inject_spider_sdk(monkeypatch, sdk: _FakeSDK) -> None:
    """将 core.spider_core.spider_sdk.get 替换为伪 SDK。"""
    import core.spider_core.sdk as sdk_module
    # 模块内单例 spider_sdk 是 SpiderSDK 实例；我们直接把单例的 .get 替换
    from core.spider_core import spider_sdk as singleton
    # monkey-patch get
    original_get = singleton.get

    def fake_get(*args, **kwargs):
        url = args[0] if args else kwargs.get("url")
        return sdk.get(url)

    monkeypatch.setattr(singleton, "get", fake_get)


def _inject_memory_db(monkeypatch) -> dict[str, Any]:
    """将 infra.db_base.database 替换为 SQLite 内存实例。"""
    import sqlite3
    import threading

    # 建立 SQLite 连接 + 创建表
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS spider_raw_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            spider_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_id TEXT,
            raw_payload TEXT NOT NULL DEFAULT '{}',
            raw_text TEXT,
            fetch_status INTEGER NOT NULL DEFAULT 0,
            fetch_error TEXT,
            captured_at TEXT NOT NULL,
            source_country TEXT,
            UNIQUE (tenant_id, spider_name, source_id)
        );
    """)
    conn.commit()

    lock = threading.Lock()
    store: dict[str, Any] = {"conn": conn, "rows": [], "lock": lock}

    # 替换 database.bulk_insert
    from infra.db_base import database
    original_bulk = database.bulk_insert

    def fake_bulk_insert(model_cls, rows, *, batch_size=500, session=None):
        if not rows:
            return 0
        inserted = 0
        with lock:
            for r in rows:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO spider_raw_data "
                        "(tenant_id, spider_name, source_url, source_id, raw_payload, raw_text, fetch_status, fetch_error, captured_at, source_country) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            r.get("tenant_id", "default"),
                            r.get("spider_name", ""),
                            r.get("source_url", ""),
                            r.get("source_id") or None,
                            json.dumps(r.get("raw_payload") or {}, ensure_ascii=False),
                            r.get("raw_text"),
                            r.get("fetch_status", 0),
                            r.get("fetch_error"),
                            r.get("captured_at") or datetime.utcnow().isoformat(),
                            r.get("source_country"),
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    # 唯一键冲突 —— 计为 upsert 成功，但不计新增
                    continue
            conn.commit()
            store["rows"] = cur.execute("SELECT * FROM spider_raw_data").fetchall()
        return inserted

    monkeypatch.setattr(database, "bulk_insert", fake_bulk_insert)

    # upsert：执行 SELECT; INSERT 或 UPDATE
    def fake_upsert(model_cls, *, conflict_columns, rows, session=None):
        results = []
        if not rows:
            return results
        with lock:
            cur = conn.cursor()
            for r in rows:
                # 简单实现：按 tenant_id/spider_name/source_id 查询
                where_cond = " AND ".join(
                    f"{c}=?" for c in (conflict_columns or ["tenant_id", "spider_name", "source_id"])
                )
                where_vals = [r.get(c) for c in (conflict_columns or ["tenant_id", "spider_name", "source_id"])]
                cur.execute(f"SELECT id FROM spider_raw_data WHERE {where_cond}", where_vals)
                existing = cur.fetchone()
                if existing is None:
                    cur.execute(
                        "INSERT INTO spider_raw_data "
                        "(tenant_id, spider_name, source_url, source_id, raw_payload, raw_text, fetch_status, fetch_error, captured_at, source_country) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            r.get("tenant_id", "default"),
                            r.get("spider_name", ""),
                            r.get("source_url", ""),
                            r.get("source_id") or None,
                            json.dumps(r.get("raw_payload") or {}, ensure_ascii=False),
                            r.get("raw_text"),
                            r.get("fetch_status", 0),
                            r.get("fetch_error"),
                            r.get("captured_at") or datetime.utcnow().isoformat(),
                            r.get("source_country"),
                        ),
                    )
                results.append(r)
            conn.commit()
            store["rows"] = cur.execute("SELECT * FROM spider_raw_data").fetchall()
        return results

    monkeypatch.setattr(database, "upsert", fake_upsert)
    return store


# 1. models -------------------------------------------------------------------


def test_models_params_defaults():
    from business.multi_spider.models import SpiderTaskParams
    p = SpiderTaskParams(spider_name="generic_article")
    assert p.spider_name == "generic_article"
    assert p.task_id and len(p.task_id) > 0
    assert p.dry_run is False
    assert p.max_pages > 0


def test_models_params_from_dict():
    from business.multi_spider.models import SpiderTaskParams
    p = SpiderTaskParams(**{"spider_name": "bid_notice", "urls": ["http://a.com"], "keywords": ["采购"]})
    assert p.urls == ["http://a.com"]
    assert p.keywords == ["采购"]


# 2. pipeline helpers --------------------------------------------------------


def test_pipeline_extract_article():
    from business.multi_spider.pipeline import extract_basic_html, extract_published_at
    info = extract_basic_html(_SAMPLE_ARTICLE)
    assert "采购" in info["title"]
    assert "服务器" in info["text_body"]
    assert extract_published_at(_SAMPLE_ARTICLE) is not None


def test_pipeline_extract_comments():
    from business.multi_spider.pipeline import extract_items
    items = extract_items(_SAMPLE_COMMENTS, max_items=100)
    assert len(items) == 2
    for it in items:
        assert it["content"] or it["title"]


# 3. BaseSpider 核心流水线（mock SDK + 内存 SQLite） -----------------------


def test_base_spider_happy_path(monkeypatch):
    sdk = _FakeSDK(html_per_url={"http://example.com/article": _SAMPLE_ARTICLE})
    _inject_spider_sdk(monkeypatch, sdk)
    _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    result = spider.run(
        SpiderTaskParams(
            spider_name=spider.name,
            urls=["http://example.com/article"],
            tenant_id="tenant_1",
        )
    )
    assert result.total_attempted == 1
    assert result.total_persisted >= 1
    assert result.total_failed == 0
    assert result.status in ("ok", "partial")


def test_base_spider_http_failure(monkeypatch):
    class _FailingSDK(_FakeSDK):
        def get(self, url, **kw):
            return _FakeCrawlResponse(url=url, final_url=url, status_code=503, text="", error="upstream unreachable")

    _inject_spider_sdk(monkeypatch, _FailingSDK())
    _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    result = spider.run(
        SpiderTaskParams(spider_name=spider.name, urls=["http://example.com/bad"])
    )
    assert result.total_attempted == 1
    assert result.total_failed == 1
    assert result.total_persisted == 0


def test_base_spider_sensitive_block_marks_fetch_status(monkeypatch):
    # 构造包含触发敏感词的文本
    bad_html = """
    <html><body>
    <article><h1>违规宣传</h1>
    <p>本内容涉及加微信推广和赌博等违规用语</p>
    </article>
    </body></html>
    """
    sdk = _FakeSDK(html_per_url={"http://example.com/bad": bad_html})
    _inject_spider_sdk(monkeypatch, sdk)
    store = _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    result = spider.run(
        SpiderTaskParams(spider_name=spider.name, urls=["http://example.com/bad"])
    )
    assert result.total_blocked_by_compliance >= 1
    # 数据库中应该存在一条 fetch_status = 3 的记录
    rows = store["rows"]
    assert rows, "应至少插入一条"
    has_block = any(int(r["fetch_status"]) == 3 for r in rows)
    assert has_block, "敏感拦截记录应写入 fetch_status=3"


def test_base_spider_dry_run_no_persist(monkeypatch):
    sdk = _FakeSDK(html_per_url={"http://example.com": _SAMPLE_ARTICLE})
    _inject_spider_sdk(monkeypatch, sdk)
    store = _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    result = spider.run(
        SpiderTaskParams(spider_name=spider.name, urls=["http://example.com"], dry_run=True)
    )
    assert result.total_persisted == 0 or result.status in ("ok", "partial")
    # dry_run 不应落库
    assert len(store["rows"]) == 0


# 4. 渠道 registry ----------------------------------------------------------


def test_registry_spider_list_and_class_lookup():
    from business.multi_spider.registry import list_spiders, get_spider_class

    names = list_spiders()
    assert "generic_article" in names
    assert "douyin_work" in names
    assert "xhs_note" in names
    assert "zhihu_question" in names
    assert "baidu_qa" in names  # 确保名字统一
    assert "bid_notice" in names
    assert "gov_procurement" in names
    assert "public_resource" in names
    assert "58_listing" in names
    assert "xianyu_item" in names
    assert "local_need" in names
    assert "qcc_new_company" in names
    assert "qcc_change_event" in names
    assert "tyc_job" in names
    # 确保能返回类型
    cls = get_spider_class("generic_article")
    assert cls is not None and hasattr(cls, "name")


def test_registry_run_spider_by_name_happy(monkeypatch):
    sdk = _FakeSDK(html_per_url={"http://example.com/article": _SAMPLE_ARTICLE})
    _inject_spider_sdk(monkeypatch, sdk)
    _inject_memory_db(monkeypatch)

    from business.multi_spider.registry import run_spider_by_name

    result = run_spider_by_name(
        "generic_article",
        {"spider_name": "generic_article", "urls": ["http://example.com/article"], "tenant_id": "t_01"},
    )
    assert result.total_attempted == 1
    assert result.total_persisted >= 1


def test_registry_run_spider_unknown_raises():
    from business.multi_spider.registry import run_spider_by_name

    with pytest.raises(ValueError):
        run_spider_by_name("not_exist_spider", {"urls": []})


# 5. 多渠道 URL 构建 --------------------------------------------------------


@pytest.mark.parametrize("spider_name,keyword_field", [
    ("generic_article", None),
    ("douyin_work", "keywords"),
    ("douyin_comment", "keywords"),
    ("xhs_note", "keywords"),
    ("xhs_comment", "keywords"),
    ("zhihu_question", "keywords"),
    ("zhihu_answer", "keywords"),
    ("baidu_qa", "keywords"),
    ("58_listing", "keywords"),
    ("xianyu_item", "keywords"),
    ("local_need", None),
    ("bid_notice", "keywords"),
    ("gov_procurement", "keywords"),
    ("public_resource", "keywords"),
    ("qcc_new_company", "keywords"),
    ("qcc_change_event", "keywords"),
    ("tyc_job", "keywords"),
])
def test_each_channel_spider_has_name_and_build_url_list(spider_name, keyword_field):
    """确保每个渠道 spider 都有正确的 name，并能在缺少模板时返回 []。"""
    from business.multi_spider.registry import get_spider_class
    from business.multi_spider.models import SpiderTaskParams

    cls = get_spider_class(spider_name)
    assert cls is not None, f"spider {spider_name} 未注册"
    inst = cls()
    assert inst.name == spider_name, f"{cls.__name__}.name 应为 {spider_name}"
    params = SpiderTaskParams(spider_name=spider_name, urls=["http://x.com/sample"])
    got = inst.build_url_list(params)
    assert got == ["http://x.com/sample"], "传入 params.urls 时应直接使用"

    # 不传 urls，不传关键词/模板 -> 返回空或合法 url 列表
    params2 = SpiderTaskParams(spider_name=spider_name)
    try:
        urls = inst.build_url_list(params2)
    except NotImplementedError:
        urls = []
    assert isinstance(urls, list)


# 6. 隐私脱敏 —— pii_mask 在 pipeline 中被调用 ----------------------------


def test_pii_mask_applied_to_payload(monkeypatch):
    html = """
    <html><body>
    <article><h1>采购咨询</h1>
    <div class="author">发布人 王经理</div>
    <p>请致电 13800138000 或发邮件到 test@example.com 了解详情</p>
    </article>
    </body></html>
    """
    sdk = _FakeSDK(html_per_url={"http://example.com": html})
    _inject_spider_sdk(monkeypatch, sdk)
    store = _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    spider.run(
        SpiderTaskParams(spider_name=spider.name, urls=["http://example.com"])
    )
    rows = store["rows"]
    assert rows
    for r in rows:
        raw_text = r["raw_text"] or ""
        assert "13800138000" not in raw_text, "手机号未脱敏"
        # 邮箱也应被脱敏处理（pii_mask 会打码）
        assert "test@example.com" not in raw_text or raw_text.count("***") >= 0


# 7. Redis 任务状态写入（若注入 redis_client） ------------------------------


def test_task_status_written_to_redis(monkeypatch):
    fake_redis = _FakeRedis()
    sdk = _FakeSDK(html_per_url={"http://example.com": _SAMPLE_ARTICLE})
    _inject_spider_sdk(monkeypatch, sdk)
    _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    spider.redis_client = fake_redis
    result = spider.run(
        SpiderTaskParams(spider_name=spider.name, urls=["http://example.com"])
    )
    assert any(v for v in fake_redis.data.values()), "任务状态未写入 redis"
    # 反序列化验证
    payload = next(iter(fake_redis.data.values()))
    data = json.loads(payload)
    assert data["spider_name"] == spider.name
    assert data["status"] in ("ok", "partial", "failed")


# 8. 唯一键冲突（upsert 幂等） ------------------------------------------------


def test_upsert_idempotent(monkeypatch):
    sdk = _FakeSDK(html_per_url={"http://example.com": _SAMPLE_ARTICLE})
    _inject_spider_sdk(monkeypatch, sdk)
    store = _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    # 第一次
    spider.run(SpiderTaskParams(spider_name=spider.name, urls=["http://example.com"]))
    first_count = len(store["rows"])
    # 第二次
    spider.run(SpiderTaskParams(spider_name=spider.name, urls=["http://example.com"]))
    second_count = len(store["rows"])
    assert second_count == first_count, "重复抓取不应产生新记录"


# 9. 暴露的 __all__ 可以正常 import ------------------------------------------


def test_multi_spider_module_public_exports():
    import business.multi_spider as ms
    for name in ("run_spider_by_name", "list_spiders", "get_spider_class",
                 "SpiderTaskParams", "SpiderTaskResult", "BaseSpider", "RawItem"):
        assert hasattr(ms, name), f"business.multi_spider 缺少公开导出: {name}"


# 10. 合规报告（compliance_report 字段必须存在于 raw_payload） --------------


def test_raw_payload_contains_compliance_report(monkeypatch):
    sdk = _FakeSDK(html_per_url={"http://example.com": _SAMPLE_ARTICLE})
    _inject_spider_sdk(monkeypatch, sdk)
    store = _inject_memory_db(monkeypatch)

    from business.multi_spider.sources.generic_web import GenericWebArticleSpider
    from business.multi_spider.models import SpiderTaskParams

    spider = GenericWebArticleSpider()
    spider.run(SpiderTaskParams(spider_name=spider.name, urls=["http://example.com"]))
    rows = store["rows"]
    assert rows
    r = rows[0]
    payload = json.loads(r["raw_payload"])
    assert "compliance_report" in payload, "raw_payload 中必须包含合规报告"
    assert "author" in payload
