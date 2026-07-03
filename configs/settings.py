from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_MODE = Literal["dev", "test", "prod"]


class ProjectSettings(BaseSettings):
    """项目基础配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    PROJECT_NAME: str = "openclaw-business-tools"
    ENV: ENV_MODE = "dev"
    DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    API_PREFIX: str = "/api/v1"


class LogSettings(BaseSettings):
    """日志相关配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "./logs"
    LOG_ROTATION: str = "1 day"
    LOG_RETENTION: str = "30 days"
    LOG_CONSOLE_ENABLED: bool = True
    LOG_FILE_ENABLED: bool = True


class AlertSettings(BaseSettings):
    """告警相关配置（钉钉机器人 / SMTP 邮件）。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    ALERT_ENABLED: bool = False
    ALERT_ENV_PREFIX: str = "[openclaw-business-tools]"
    ALERT_MAX_BYTES: int = 10 * 1024  # 单条告警消息截断上限 10KB

    # 钉钉
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_SECRET: str = ""

    # 邮件
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TO: str = ""  # 多收件人逗号分隔
    SMTP_USE_SSL: bool = True

    # 三类告警场景开关
    ALERT_TASK_FAILURE_ENABLED: bool = True
    ALERT_SERVICE_EXCEPTION_ENABLED: bool = True
    ALERT_CRAWLER_RISK_ENABLED: bool = True


class QueueSettings(BaseSettings):
    """异步任务队列相关配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    QUEUE_REDIS_HOST: str = "127.0.0.1"
    QUEUE_REDIS_PORT: int = 6379
    QUEUE_REDIS_PASSWORD: str = ""
    QUEUE_REDIS_DB: int = 1
    QUEUE_PREFIX: str = "openclaw:queue"
    QUEUE_NAME: str = "default"
    QUEUE_POOL_SIZE: int = 10
    QUEUE_POOL_TIMEOUT: float = 30.0          # 连接池等待超时（秒）
    QUEUE_TASK_TIMEOUT: float = 300.0         # 单个任务执行超时（秒）
    QUEUE_MAX_RETRIES: int = 3
    QUEUE_RETRY_BACKOFF: float = 2.0          # 指数退避基数（秒）
    QUEUE_WORKER_CONCURRENCY: int = 4         # 同时消费的 worker 协程数
    QUEUE_BPOP_TIMEOUT: float = 5.0           # 单次 bpop 等待时间（秒）
    QUEUE_TASK_TTL: int = 7 * 24 * 3600       # 任务 meta/payload 过期（秒）


class SchedulerSettings(BaseSettings):
    """定时任务调度相关配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"
    SCHEDULER_MAX_CONCURRENT: int = 10
    SCHEDULER_MISFIRE_GRACE_TIME: int = 60
    SCHEDULER_COALESCE: bool = True
    SCHEDULER_JOBSTORES_REDIS: bool = False
    SCHEDULER_STORE_PREFIX: str = "openclaw:scheduler"


class DBSettings(BaseSettings):
    """数据库 / ORM / 加密 / 冷热分离配置。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "openclaw_biz"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    DB_ENCRYPTION_KEY: str = ""
    DB_ARCHIVE_DAYS: int = 90
    DB_ARCHIVE_HOT_THRESHOLD: float = 1000.0
    DB_SENSITIVE_MASK_ENABLED: bool = True
    DB_TABLE_PREFIX: str = ""

    def masked_repr(self) -> dict:
        """打印配置时替换敏感字段为 ***。"""
        data = self.model_dump()
        for key in ("DB_PASSWORD", "DB_ENCRYPTION_KEY"):
            if key in data:
                data[key] = "***"
        return data


class AppSettings(BaseSettings):
    """全局单例配置对象。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project: ProjectSettings = Field(default_factory=ProjectSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    alert: AlertSettings = Field(default_factory=AlertSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    db: DBSettings = Field(default_factory=DBSettings)
    spider: "SpiderSettings" = Field(default_factory=lambda: SpiderSettings())
    cleaning: "DataCleanSettings" = Field(default_factory=lambda: DataCleanSettings())
    customer_send: "CustomerSendSettings" = Field(default_factory=lambda: CustomerSendSettings())


# =====================
# T09 多源爬虫配置
# =====================


class SpiderSettings(BaseSettings):
    """多源爬虫配置（全部从 .env 读取，不硬编码链接/关键词）。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    SPIDER_MAX_PAGES_DEFAULT: int = 20
    SPIDER_MAX_ITEMS_PER_URL: int = 100
    SPIDER_BATCH_INSERT_SIZE: int = 200
    SPIDER_DEFAULT_RENDER_JS: bool = False
    SPIDER_DEFAULT_USE_PROXY: bool = True
    SPIDER_COUNTRY_DEFAULT: str = "CN"
    SPIDER_SENSITIVE_HIGH_THRESHOLD: int = 3
    SPIDER_COMPLIANCE_ENABLED: bool = True
    SPIDER_PII_MASK_ENABLED: bool = True
    SPIDER_SUMMARY_FIELDS_MASK: str = "phone,email,id_card,bank_card,license_plate,wechat,qq,name"

    # 渠道种子 / 搜索模板
    SPIDER_GENERIC_WEB_SEEDS: str = ""
    SPIDER_FORUM_SEEDS: str = ""
    SPIDER_DOUYIN_SEARCH_TEMPLATE: str = ""
    SPIDER_XHS_SEARCH_TEMPLATE: str = ""
    SPIDER_ZHIHU_SEARCH_TEMPLATE: str = ""
    SPIDER_BAIDU_QA_TEMPLATE: str = ""
    SPIDER_58_TEMPLATE: str = ""
    SPIDER_XIANYU_TEMPLATE: str = ""
    SPIDER_BID_SEARCH_TEMPLATE: str = ""
    SPIDER_GOV_SEARCH_TEMPLATE: str = ""
    SPIDER_PUBLIC_RESOURCE_TEMPLATE: str = ""
    SPIDER_QCC_SEARCH_TEMPLATE: str = ""
    SPIDER_TYC_SEARCH_TEMPLATE: str = ""

    # 渠道开关
    SPIDER_CHANNEL_GENERIC_ENABLED: bool = True
    SPIDER_CHANNEL_DOUYIN_XHS_ENABLED: bool = True
    SPIDER_CHANNEL_ZHIHU_BAIDU_ENABLED: bool = True
    SPIDER_CHANNEL_LOCAL_ENABLED: bool = True
    SPIDER_CHANNEL_BID_GOV_ENABLED: bool = True
    SPIDER_CHANNEL_ENTERPRISE_ENABLED: bool = True

    # 任务状态 Redis 前缀
    SPIDER_TASK_STATUS_PREFIX: str = "openclaw:spider:task:"
    SPIDER_TASK_STATUS_TTL_SECONDS: int = 86400

    def split_csv(self, value: str) -> list[str]:
        if not value:
            return []
        return [x.strip() for x in value.split(",") if x.strip()]


# =====================
# T10 数据清洗配置
# =====================


class DataCleanSettings(BaseSettings):
    """数据清洗配置（全部从 .env 读取，关键词库不硬编码）。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # 基础参数
    CLEAN_BATCH_SIZE: int = 200
    CLEAN_MIN_TEXT_LEN: int = 30
    CLEAN_PIPELINE_VERSION: str = "T10-v1.0"

    # 实体抽取开关
    CLEAN_COMPANY_ENABLED: bool = True
    CLEAN_PHONE_ENABLED: bool = True
    CLEAN_WECHAT_ENABLED: bool = True
    CLEAN_BUDGET_ENABLED: bool = True

    # 关键词库（逗号分隔）
    CLEAN_INDUSTRY_KEYWORDS: str = "IT,制造业,采购,批发,零售,教育,医疗,建筑,金融,物流"
    CLEAN_REGION_KEYWORDS: str = "北京,上海,广州,深圳,杭州,南京,武汉,成都,重庆,西安"
    CLEAN_NEED_KEYWORDS: str = "采购,合作,代理,招聘,外包,加盟,招商,寻求,需求,寻找,招标,投标"
    CLEAN_COMPANY_SUFFIXES: str = "公司,有限公司,工作室,集团,科技,厂,中心,部,工作室"
    CLEAN_KEYWORDS_TOPK: int = 8

    # 违规/高风险判定阈值
    CLEAN_HIGH_VIOLATION_RISK: str = "high"
    CLEAN_HIGH_VIOLATION_HITS: int = 3
    CLEAN_AD_JUNK_PATTERNS: str = ""
    CLEAN_BLACKLIST_DOMAINS: str = ""

    # 告警
    CLEAN_ANOMALY_ALERT_RATIO: float = 0.05
    CLEAN_BLOCKED_ALERT_COUNT: int = 10

    # 任务状态
    CLEAN_REDIS_STATUS_PREFIX: str = "openclaw:clean:task:"
    CLEAN_REDIS_STATUS_TTL: int = 86400

    def split_csv(self, value: str) -> list[str]:
        if not value:
            return []
        return [x.strip() for x in str(value).split(",") if x.strip()]


# =====================
# T11 多渠道商机触达配置
# =====================


class CustomerSendSettings(BaseSettings):
    """多渠道触达配置（全部从 .env 读取，密钥/域名零硬编码）。"""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # 渠道开关
    CUSTOMER_SEND_EMAIL_ENABLED: bool = True
    CUSTOMER_SEND_WECHAT_ENABLED: bool = True
    CUSTOMER_SEND_FEISHU_ENABLED: bool = True
    CUSTOMER_SEND_H5_ENABLED: bool = False

    # H5 对外短链域名
    CUSTOMER_SEND_H5_BASE_URL: str = "https://claw.example.com"

    # 批量大小默认值（仅对调用者节流，真正限流仍走 core.send_core.RateLimiter）
    CUSTOMER_SEND_BATCH_SIZE_DEFAULT: int = 50

    # 告警阈值（占比）
    CUSTOMER_SEND_BLOCKED_ALERT_RATIO: float = 0.1
    CUSTOMER_SEND_FAILED_ALERT_RATIO: float = 0.2

    # 模板文件目录（相对项目根）
    CUSTOMER_SEND_TEMPLATE_DIR: str = "configs/templates"

    # 版本标识
    CUSTOMER_SEND_VERSION: str = "T11-v1.0"

    # SMTP 全局回退（当 channel account token == "smtp_fallback" 时使用）
    CUSTOMER_SEND_SMTP_HOST: str = ""
    CUSTOMER_SEND_SMTP_PORT: int = 465
    CUSTOMER_SEND_SMTP_USER: str = ""
    CUSTOMER_SEND_SMTP_PASSWORD: str = ""
    CUSTOMER_SEND_SMTP_USE_SSL: bool = True
    CUSTOMER_SEND_SMTP_FROM: str = ""

    def split_csv(self, value: str) -> list[str]:
        if not value:
            return []
        return [x.strip() for x in str(value).split(",") if x.strip()]


# 全局单例，跨模块统一使用 `from configs.settings import settings`
settings = AppSettings()

__all__ = [
    "settings",
    "AppSettings",
    "ProjectSettings",
    "LogSettings",
    "AlertSettings",
    "QueueSettings",
    "SchedulerSettings",
    "DBSettings",
]
