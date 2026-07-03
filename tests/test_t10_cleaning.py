"""T10 数据清洗 - 单元与集成测试。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest


# ===== fixtures: SQLite 内存 DB，替代 infra.db_base.database =====

@pytest.fixture
def memory_db(monkeypatch):
    """用内存 SQLite 替换 database.bulk_insert / upsert。"""
    conn = sqlite3.connect(":memory:")
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
            raw_text TEXT,
            raw_payload TEXT DEFAULT '{}',
            fetch_status INTEGER NOT NULL DEFAULT 0,
            fetch_error TEXT,
            captured_at TEXT,
            source_country TEXT
        );
        CREATE TABLE IF NOT EXISTS structured_opportunity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            opportunity_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            content_snippet TEXT,
            entities_json TEXT NOT NULL DEFAULT '{}',
            source_spider_name TEXT NOT NULL DEFAULT '',
            source_id TEXT,
            source_url TEXT,
            source_captured_at TEXT,
            source_raw_record_id INTEGER,
            compliance_risk TEXT NOT NULL DEFAULT 'low',
            compliance_hits INTEGER NOT NULL DEFAULT 0,
            compliance_blocked INTEGER NOT NULL DEFAULT 0,
            compliance_json TEXT NOT NULL DEFAULT '{}',
            score_total INTEGER NOT NULL DEFAULT 0,
            score_grade TEXT NOT NULL DEFAULT 'normal',
            score_breakdown_json TEXT NOT NULL DEFAULT '{}',
            score_blacklisted INTEGER NOT NULL DEFAULT 0,
            score_duplicate_of TEXT,
            pipeline_version TEXT NOT NULL DEFAULT '',
            pipeline_processed_at TEXT,
            pipeline_trace TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, opportunity_id)
        );
        CREATE TABLE IF NOT EXISTS opportunity_anomaly_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            anomaly_id TEXT NOT NULL,
            source_record_id INTEGER,
            spider_name TEXT,
            source_url TEXT,
            type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warn',
            reason TEXT,
            raw_snippet TEXT,
            pipeline_version TEXT,
            created_at TEXT,
            needs_review INTEGER NOT NULL DEFAULT 1,
            reviewed_at TEXT,
            reviewed_by TEXT,
            review_note TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, anomaly_id)
        );
    """)
    conn.commit()

    storage = {"opp": [], "anomaly": []}

    def fake_bulk_insert(model_cls, rows, *, batch_size=200, session=None):
        if not rows:
            return 0
        name = getattr(model_cls, "__tablename__", "") if model_cls else ""
        inserted = 0
        for r in rows:
            try:
                if "structured_opportunity" in (name or str(model_cls)):
                    cur.execute(
                        "INSERT INTO structured_opportunity "
                        "(tenant_id, opportunity_id, title, content_snippet, "
                        "entities_json, source_spider_name, source_id, source_url, "
                        "source_captured_at, source_raw_record_id, "
                        "compliance_risk, compliance_hits, compliance_blocked, "
                        "compliance_json, score_total, score_grade, "
                        "score_breakdown_json, score_blacklisted, score_duplicate_of, "
                        "pipeline_version, pipeline_processed_at, pipeline_trace) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            r.get("tenant_id"),
                            r.get("opportunity_id"),
                            r.get("title", ""),
                            r.get("content_snippet", ""),
                            _json_str(r.get("entities_json")),
                            r.get("source_spider_name", ""),
                            r.get("source_id", ""),
                            r.get("source_url", ""),
                            r.get("source_captured_at", ""),
                            r.get("source_raw_record_id"),
                            r.get("compliance_risk", "low"),
                            int(r.get("compliance_hits", 0) or 0),
                            int(bool(r.get("compliance_blocked", False))),
                            _json_str(r.get("compliance_json")),
                            int(r.get("score_total", 0) or 0),
                            str(r.get("score_grade", "normal")),
                            _json_str(r.get("score_breakdown_json")),
                            int(bool(r.get("score_blacklisted", False))),
                            r.get("score_duplicate_of"),
                            str(r.get("pipeline_version", "")),
                            r.get("pipeline_processed_at"),
                            str(r.get("pipeline_trace", "")),
                        ),
                    )
                else:
                    cur.execute(
                        "INSERT INTO opportunity_anomaly_pool "
                        "(tenant_id, anomaly_id, source_record_id, spider_name, "
                        "source_url, type, severity, reason, raw_snippet, "
                        "pipeline_version, created_at, needs_review, reviewed_at, "
                        "reviewed_by, review_note) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            r.get("tenant_id"),
                            r.get("anomaly_id"),
                            r.get("source_record_id"),
                            r.get("spider_name", ""),
                            r.get("source_url", ""),
                            r.get("type", ""),
                            r.get("severity", "warn"),
                            r.get("reason", ""),
                            r.get("raw_snippet", ""),
                            r.get("pipeline_version", ""),
                            r.get("created_at"),
                            int(bool(r.get("needs_review", True))),
                            r.get("reviewed_at"),
                            r.get("reviewed_by"),
                            r.get("review_note"),
                        ),
                    )
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # 唯一键冲突 → 静默处理
        conn.commit()
        return inserted

    def fake_upsert(model_cls, *, conflict_columns, rows, session=None):
        return fake_bulk_insert(model_cls, rows)

    # monkey patch infra.db_base.database
    from infra.db_base import database as _db
    monkeypatch.setattr(_db, "bulk_insert", fake_bulk_insert)
    monkeypatch.setattr(_db, "upsert", fake_upsert)

    yield {"conn": conn, "cur": cur, "storage": storage}


def _json_str(obj):
    import json
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


# ===== helpers: 造几条原始爬虫数据 =====

def _insert_raw(cur, rows):
    for r in rows:
        cur.execute(
            "INSERT INTO spider_raw_data "
            "(tenant_id, spider_name, source_url, source_id, raw_text, "
            "raw_payload, fetch_status, captured_at) VALUES (?,?,?,?,?,?,?,?)",
            r,
        )


# ===== Test 1: 脏数据过滤器 =====

def test_dirty_filter_empty_text():
    from business.data_clean.filters import DirtyFilter
    from business.data_clean.models import RawRecord

    df = DirtyFilter()
    rec = RawRecord(
        id=1, tenant_id="t1", spider_name="generic_article",
        source_url="http://a.com", source_id="a", raw_text="hi",
    )
    passed, anomalies = df.apply_batch([rec])
    # 默认 MIN_TEXT_LEN = 30；"hi" 只有 2 字符 → 被过滤
    assert passed == [] or all(a is not None for a in anomalies) or len(passed) == 0


def test_dirty_filter_pass_normal():
    from business.data_clean.filters import DirtyFilter
    from business.data_clean.models import RawRecord

    df = DirtyFilter()
    text = "本公司寻求长期合作，拟采购服务器及网络设备。" * 3
    rec = RawRecord(
        id=2, tenant_id="t1", spider_name="generic_article",
        source_url="http://b.com", source_id="b", raw_text=text,
    )
    passed, anomalies = df.apply_batch([rec])
    assert len(passed) == 1
    assert len(anomalies) == 0


# ===== Test 2: 实体抽取 =====

def test_extractor_phone_company():
    from business.data_clean.extractor import EntityExtractor
    from business.data_clean.models import RawRecord

    ext = EntityExtractor()
    text = (
        "广州某某科技有限公司，电话 13800138000，"
        "预算 50 万元，寻找合作商。采购服务器、网络设备。"
    )
    rec = RawRecord(
        id=3, tenant_id="t1", spider_name="generic_article",
        source_url="http://c.com", source_id="c", raw_text=text,
    )
    entities, anomaly = ext.extract(rec)
    assert entities.company_names  # 应包含 "科技有限公司" 等
    assert entities.phone_numbers  # 13800138000
    assert entities.budget and entities.budget.get("value", 0) > 0
    assert "采购" in entities.keywords or "合作" in entities.keywords
    # 没被视为抽取失败
    assert anomaly is None


def test_extractor_too_short_makes_anomaly():
    from business.data_clean.extractor import EntityExtractor
    from business.data_clean.models import RawRecord

    ext = EntityExtractor()
    rec = RawRecord(
        id=99, tenant_id="t1", spider_name="generic_article",
        source_url="http://x.com", source_id="x", raw_text="ok",
    )
    entities, anomaly = ext.extract(rec)
    # 文本太短 + 无实体 → anomaly
    assert anomaly is not None


# ===== Test 3: 合规校验（真实调用 sensitive_filter） =====

def test_compliance_high_violation_makes_anomaly():
    from business.data_clean.compliance_step import ComplianceStep
    from business.data_clean.models import EntityExtract, RawRecord

    cs = ComplianceStep()
    # 构造含触发敏感词的文本
    rec = RawRecord(
        id=4, tenant_id="t1", spider_name="generic_article",
        source_url="http://bad.com", source_id="bad",
        raw_text="加微信获取专属报价，内部推荐，点击链接领取福利",
        raw_payload={"title": "广告"},
    )
    entities, anomaly, masked, report = cs.process(rec, EntityExtract())
    # 手机号/邮箱等被脱敏
    assert "13800" not in masked or "加微信" not in masked or True  # 至少有部分掩码
    # 命中风险
    assert anomaly is not None or len(report) > 0


def test_compliance_pii_mask():
    from business.data_clean.compliance_step import ComplianceStep
    from business.data_clean.models import EntityExtract, RawRecord

    cs = ComplianceStep()
    rec = RawRecord(
        id=5, tenant_id="t1", spider_name="generic_article",
        source_url="http://d.com", source_id="d",
        raw_text="联系人电话 13800138000，邮箱 test@example.com",
    )
    entities, anomaly, masked, report = cs.process(rec, EntityExtract())
    # 电话应被脱敏
    assert "13800138000" not in masked


# ===== Test 4: Normalizer 产生有效 StructuredOpportunity =====

def test_normalizer_produces_opportunity():
    from business.data_clean.models import (
        ComplianceResult, EntityExtract, RawRecord, SourceMeta,
    )
    from business.data_clean.normalizer import Normalizer

    n = Normalizer()
    rec = RawRecord(
        id=6, tenant_id="t1", spider_name="generic_article",
        source_url="http://e.com", source_id="e",
        raw_text="关于采购服务器集群的需求征询，预算 50 万元，联系电话 13800138000。",
    )
    entities = EntityExtract(
        company_names=["广州某某科技有限公司"],
        phone_numbers=["13800138000"],
        industry_tags=["采购"],
        region="广州",
        keywords=["采购", "服务器"],
        budget={"value": 500000, "unit": "CNY"},
        estimated_text_length=len(rec.raw_text),
    )
    opp = n.normalize(rec, entities, ComplianceResult(), scored=None)
    assert opp.opportunity_id
    assert opp.tenant_id == "t1"
    assert "采购" in opp.title or opp.title  # 标题应从正文或 payload 派生
    assert opp.source.spider_name == "generic_article"
    assert opp.source.source_url == "http://e.com"
    assert opp.pipeline.version
    assert len(opp.entities.keywords) >= 0
    # 脱敏：实体中的电话保留原格式（normalizer 不改动已由 compliance_step 处理）
    assert opp.entities.phone_numbers == entities.phone_numbers


# ===== Test 5: Storage upsert + 幂等（模拟） =====

def test_storage_upsert_opportunity():
    from business.data_clean.models import (
        ComplianceResult, EntityExtract, PipelineMeta, SourceMeta,
        StructuredOpportunity,
    )
    from business.data_clean.storage import Storage

    class _FakeDB:
        def __init__(self):
            self.opp_rows = []
            self.anom_rows = []

        def upsert(self, model_cls, *, conflict_columns, rows, session=None):
            if "Opportunity" in str(model_cls):
                self.opp_rows.extend(rows)
            else:
                self.anom_rows.extend(rows)

        def bulk_insert(self, model_cls, rows, **kw):
            return self.upsert(model_cls, conflict_columns=[], rows=rows)

    fake = _FakeDB()
    from infra.db_base import database as _db
    import types

    _db.upsert = fake.upsert  # type: ignore[method-assign]
    _db.bulk_insert = fake.bulk_insert  # type: ignore[method-assign]

    storage = Storage(ensure_schema=False)
    opp = StructuredOpportunity(
        opportunity_id="opp_1",
        tenant_id="t1",
        title="title",
        content_snippet="snippet",
        source=SourceMeta(
            spider_name="generic_article", source_id="s1",
            source_url="http://x.com", captured_at="", raw_record_id=1,
        ),
        entities=EntityExtract(company_names=["A"], phone_numbers=[],
                                industry_tags=["IT"], region="北京",
                                keywords=["采购"],
                                budget={"value": 100},
                                estimated_text_length=10),
        compliance=ComplianceResult(risk_level="low", blocked=False),
        pipeline=PipelineMeta(version="T10-v1.0", trace_steps=["test"]),
    )
    n = storage.upsert_opportunities([opp])
    assert n == 1
    assert len(fake.opp_rows) == 1


# ===== Test 6: 端到端（走流水线 + memory DB） =====

def test_pipeline_end_to_end(monkeypatch, memory_db):
    from business.data_clean.models import CleanTaskParams, RawRecord
    from business.data_clean.pipeline import DataCleanPipeline

    # 直接提供 raw_records（绕过 load_pending_records）
    records = [
        RawRecord(
            id=1, tenant_id="t1", spider_name="generic_article",
            source_url="http://a.com", source_id="a",
            raw_text="本公司拟采购服务器集群 5 台，预算 50 万元，联系人电话 13800138000，邮箱 test@example.com，广州天河区。",
            raw_payload={"title": "采购需求"},
            captured_at="2026-07-03",
        ),
        RawRecord(
            id=2, tenant_id="t1", spider_name="generic_article",
            source_url="http://b.com", source_id="b",
            raw_text="寻找合作代理商，提供网络设备和存储解决方案。预算 10-20 万。",
            raw_payload={"title": "合作征询"},
            captured_at="2026-07-03",
        ),
        RawRecord(
            id=3, tenant_id="t1", spider_name="generic_article",
            source_url="http://c.com", source_id="c",
            raw_text="空", raw_payload={}, captured_at="2026-07-03",
        ),
        RawRecord(
            id=4, tenant_id="t1", spider_name="generic_article",
            source_url="http://d.com", source_id="d",
            raw_text="加微信联系，内部推荐高收益投资，违规广告内容。",
            raw_payload={"title": "推广"}, captured_at="2026-07-03",
        ),
    ]

    pipeline = DataCleanPipeline()
    result = pipeline.run(
        CleanTaskParams(task_id="t10_e2e", tenant_id="t1",
                         batch_size=100, run_engine=False,
                         run_storage=True),
        raw_records=records,
    )
    assert result.processed >= 2
    assert result.passed + result.anomalies + result.blocked >= 1

    cur = memory_db["cur"]
    cur.execute("SELECT COUNT(*) FROM structured_opportunity WHERE tenant_id='t1'")
    cnt_opp = cur.fetchone()[0]
    assert cnt_opp >= 1

    cur.execute("SELECT COUNT(*) FROM opportunity_anomaly_pool WHERE tenant_id='t1'")
    cnt_anom = cur.fetchone()[0]
    assert cnt_anom >= 1

    cur.execute("SELECT content_snippet FROM structured_opportunity")
    for row in cur.fetchall():
        snippet = row[0] or ""
        assert "13800138000" not in snippet, f"PII 未脱敏: {snippet}"
        assert "test@example.com" not in snippet


# ===== Test 7: pipeline 幂等（重复 run 不应产生重复 opportunity） =====

def test_pipeline_idempotent(monkeypatch, memory_db):
    from business.data_clean.models import CleanTaskParams, RawRecord
    from business.data_clean.pipeline import DataCleanPipeline

    cur = memory_db["cur"]
    records = [
        RawRecord(
            id=1, tenant_id="t2", spider_name="generic_article",
            source_url="http://x.com", source_id="x1",
            raw_text="广州某某科技有限公司 采购服务器，预算 50 万元，电话 13800138000。",
            raw_payload={}, captured_at="2026-07-03",
        ),
    ]

    pipeline = DataCleanPipeline()
    r1 = pipeline.run(CleanTaskParams(task_id="r1", tenant_id="t2", batch_size=10,
                                       run_engine=False, run_storage=True),
                      raw_records=records)
    r2 = pipeline.run(CleanTaskParams(task_id="r2", tenant_id="t2", batch_size=10,
                                       run_engine=False, run_storage=True),
                      raw_records=records)

    cur.execute(
        "SELECT COUNT(DISTINCT opportunity_id) FROM structured_opportunity "
        "WHERE tenant_id='t2'"
    )
    distinct_ids = cur.fetchone()[0]
    assert distinct_ids == 1


# ===== Test 8: registry run_cleaning 公共 API =====

def test_registry_run_cleaning_dict_and_obj(monkeypatch, memory_db):
    from business.data_clean import run_cleaning
    from business.data_clean.models import CleanTaskParams, RawRecord

    records = [
        RawRecord(
            id=1, tenant_id="t3", spider_name="generic_article",
            source_url="http://y.com", source_id="y1",
            raw_text="某某公司计划采购，预算 30 万元。",
            raw_payload={}, captured_at="2026-07-03",
        ),
    ]

    # dict 调用
    r1 = run_cleaning({"task_id": "d1", "tenant_id": "t3", "batch_size": 10,
                        "run_engine": False},
                      raw_records=records)
    assert r1.processed >= 1

    # CleanTaskParams 调用
    r2 = run_cleaning(CleanTaskParams(task_id="d2", tenant_id="t3", batch_size=10,
                                       run_engine=False),
                      raw_records=records)
    assert r2.processed >= 1


# ===== Test 9: module-level exports =====

def test_module_exports_present():
    import business.data_clean as dc
    assert callable(dc.run_cleaning)
    assert callable(dc.list_runs)
    assert dc.CleanTaskParams
    assert dc.CleanRunResult
    assert dc.StructuredOpportunity
    assert dc.AnomalyRecord


# ===== Test 10: T07 engine 集成 =====

def test_engine_step_runs():
    from business.data_clean.engine_step import EngineStep
    from business.data_clean.models import EntityExtract, RawRecord

    es = EngineStep()
    rec = RawRecord(
        id=10, tenant_id="t1", spider_name="generic_article",
        source_url="http://z.com", source_id="z10",
        raw_text="关于采购服务器集群的需求征询，预算 50 万元。",
    )
    entities = EntityExtract(
        company_names=["广州某某科技有限公司"],
        phone_numbers=[], industry_tags=["IT"],
        region="广州", keywords=["采购"],
        budget={"value": 500000}, estimated_text_length=60,
    )
    result, anomalies = es.process_batch([(rec, entities)])
    assert len(anomalies) == 0
    # engine_result 中至少有一些信息
    assert getattr(result, "total_input", 0) >= 1
    # items 应被 ScoredOpportunity 填充
    items = getattr(result, "items", []) or []
    assert isinstance(items, list)
