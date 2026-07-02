# T02 基建工具使用说明

> 本模块提供**全局日志、统一异常、消息告警、统一响应**四类底层能力。
> 所有能力仅依赖 `infra/` 与 `configs/`，不侵入业务模块。

## 1. 统一 API 响应

### 1.1 成功

```python
from infra.response import ok

@app.get("/ping")
def ping():
    return ok({"ping": "pong"})
```

输出：

```json
{"code":0,"msg":"ok","data":{"ping":"pong"},"timestamp":1783000000}
```

### 1.2 失败

```python
from infra.response import fail
from infra.exceptions import ErrorCode

@app.get("/boom")
def boom():
    body, http = fail(ErrorCode.BIZ_ERROR, "参数缺失", data={"field": "id"})
    return body, http
```

## 2. 统一异常体系

### 2.1 业务异常便捷函数

```python
from infra.exceptions import (
    BizException,
    BizWarning,
    raise_biz_error,
    raise_task_failure,
    raise_service_exception,
    raise_crawler_risk,
)

# 普通业务异常，不触发告警
raise_biz_error("参数无效", http_status=400)

# 任务失败（触发任务失败告警）
raise_task_failure("抓取任务超时", data={"task_id": 1})

# 服务异常（触发服务异常告警）
raise_service_exception("数据库连接失败")

# 爬虫风控（触发风控告警）
raise_crawler_risk("触发平台反爬")
```

### 2.2 错误码表

| 码值 | 含义 |
|------|------|
| 0 | 成功 |
| 10000 / 10001 / 10002 / 10003 / 10004 | 业务通用 / 警告 / 参数 / 未找到 / 冲突 |
| 20001 / 20002 / 20003 | 任务失败 / 服务异常 / 爬虫风控 |
| 40000 / 40100 / 40300 / 40400 / 42200 / 42900 | HTTP 客户端错误 |
| 50000 / 50001 / 50300 | 服务端内部错误 |

## 3. 全局日志

```python
from infra.logger_setup import get_logger

logger = get_logger(__name__)
logger.info("starting...")
logger.error("boom")
```

- 控制台 + 文件双通道
- 按天切割 `{time:YYYY-MM-DD}.log`
- ERROR 级别单独落盘 `error_{time:YYYY-MM-DD}.log`
- 所有参数可通过 `.env` 或环境变量覆盖

日志相关环境变量：

```
LOG_LEVEL=INFO
LOG_DIR=./logs
LOG_ROTATION=1 day
LOG_RETENTION=30 days
LOG_CONSOLE_ENABLED=true
LOG_FILE_ENABLED=true
```

## 4. 消息告警

```python
from infra.alerting import alert_service, AlertType

# 直接调用场景化 API
alert_service.task_failure("任务失败", "task_id=1\n耗时=60s")
alert_service.service_exception("API 报错", "POST /api/v1/x failed: timeout")
alert_service.crawler_risk("触发反爬", "proxy=...")

# 或通用 API
alert_service.send_sync(AlertType.TASK_FAILURE, "title", "body")
```

告警相关环境变量：

```
ALERT_ENABLED=true

# 钉钉机器人
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=SECxxxxxx

# 邮件
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USER=noreply@example.com
SMTP_PASSWORD=xxxx
SMTP_FROM=noreply@example.com
SMTP_TO=ops@example.com,dev@example.com

# 三类告警场景开关
ALERT_TASK_FAILURE_ENABLED=true
ALERT_SERVICE_EXCEPTION_ENABLED=true
ALERT_CRAWLER_RISK_ENABLED=true
```

## 5. FastAPI 全局异常捕获

```python
from fastapi import FastAPI
from infra.exception_handler import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
```

会自动处理：

- `RequestValidationError`（Pydantic 参数校验）→ 422
- `HTTPException`（FastAPI 自带）→ 透传 status_code + 按 code 映射
- `BizException`（自定义）→ 自动触发告警
- `Exception`（兜底）→ 500 + 完整堆栈打印到日志 + 服务异常告警

## 6. 配置

所有配置集中在 [configs/settings.py](../configs/settings.py)。
优先级：`.env` 文件 → 系统环境变量 → 默认值。
