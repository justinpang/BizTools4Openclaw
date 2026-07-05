# T08 开发计划：多渠道消息发送风控底层核心底座

## 一、仓库研究结论

现有基建可直接复用：
- `infra/redis_client.py` → `RedisClient` 单例，提供连接池 + `acquire()` 获取原始 redis 客户端，支持 INCR/HINCR/EXPIRE/ZADD 等原语
- `infra/alerting.py` → `AlertService.service_exception_sync()`，支持钉钉/邮件告警，内置 debounce
- `core/compliance/sensitive_filter.py` → `SensitiveFilter.is_blocked()` 敏感词拦截，`filter_text()` 违规片段替换
- `core/compliance/pii_mask.py` → `PIIMask.auto_mask()` 手机号/微信/邮箱统一脱敏
- `core/compliance/compliance_checker.py` → `ComplianceChecker.check_for_outbound()` 合规预检
- `core/send_core/` 目录已存在但为空（占位 `__init__.py`），符合"不新增目录"约束

## 二、本次新增文件清单

| # | 文件路径 | 职责 |
|---|---|---|
| 1 | `core/send_core/account_pool.py` | 渠道账号池 + 负载均衡（轮询/带权轮询/健康跳过） |
| 2 | `core/send_core/rate_limiter.py` | 分层限流控制器（全局日/单账号日/小时频/单用户最小间隔） |
| 3 | `core/send_core/content_risk.py` | 内容风控校验（联动 T06 SensitiveFilter + PIIMask + 黑名单） |
| 4 | `core/send_core/failure_retry.py` | 失败分类（网络/封禁/违规）+ 差异化重试策略 |
| 5 | `core/send_core/ban_detector.py` | 渠道封禁检测：返回码/关键词判定 + 自动标记失效 |
| 6 | `core/send_core/task_status.py` | 统一消息任务状态机 + Redis 持久化（待发/发送中/成功/失败/拦截） |
| 7 | `core/send_core/send_pipeline.py` | 组合管线：校验 → 取号 → 限流 → 发送 → 失败重试 → 状态回写 → 告警 |
| 8 | `core/send_core/__init__.py` | 导出模块级单例：`account_pool` / `rate_limiter` / `content_risk` / `failure_retry` / `ban_detector` / `send_pipeline` |
| 9 | `tests/test_t08_infra.py` | 各模块独立 + 管线全流程单元测试（不少于 12 个用例） |

## 三、账号负载均衡分配策略

**账号池数据结构（从 .env 配置加载）：**

```
SEND_CHANNELS=wechat,feishu,email
SEND_WECHAT_ACCOUNTS=wx001:token001:50,wx002:token002:80   # id:token:日额度
SEND_FEISHU_ACCOUNTS=fs001:app_hook001:100,fs002:app_hook002:100
SEND_EMAIL_ACCOUNTS=mail001:smtp_pwd001:200
SEND_LB_STRATEGY=round_robin   # round_robin / weighted_random / least_loaded
```

**分配步骤：**
1. 根据 `channel` 拿到该渠道 `List[Account]`，每个 Account 含 `id / token / daily_quota / cooldown_until / banned / banned_reason`
2. 跳过 `banned==True`、跳过处于 cooldown 的账号
3. 根据 `SEND_LB_STRATEGY` 选择下一个账号
4. 若全渠道无可用账号 → 抛出 `SendException(SEND_NO_ACCOUNT)`，触发告警

**Redis 存储（负载相关）：**

```
send:lb:cursor:{channel}          STRING        round-robin 原子指针
send:account:meta:{account_id}    HASH          health / last_used_ts / banned_ts
send:account:banned               SET           已标记为失效的 account_id
```

## 四、限流计数器 Redis 存储结构

```
send:quota:global:{YYYYMMDD}          STRING(INT)    全局当日已发总量
send:quota:account:{acc_id}:{YYYYMMDD} STRING(INT)    单账号当日计数
send:freq:hour:{acc_id}:{HH}          STRING(INT)    单账号小时内计数
send:user:gap:{user_id_hash}          STRING(TS)     单用户上次发送时间戳
send:cooling:{acc_id}                 STRING(TS)     账号冷却释放时间

对应的 .env 控制：
  SEND_GLOBAL_DAILY_LIMIT=5000         全局日上限
  SEND_ACCOUNT_DAILY_LIMIT_DEFAULT=100 单账号默认日上限
  SEND_ACCOUNT_HOURLY_LIMIT=30         单账号小时上限
  SEND_USER_GAP_SECONDS=300            单用户最小间隔（秒）
  SEND_COOLDOWN_AFTER_BAN_SECONDS=600  账号封禁后的下一次冷却
  SEND_RATE_KEY_TTL_SECONDS=259200     计数器 TTL（3天，留对账窗口）
```

## 五、消息风控校验 + 封禁识别判断逻辑

**内容风控（content_risk.py）：**
1. 先对 `recipient / contact_info` 字段调用 `PIIMask.auto_mask()` 做脱敏拷贝（告警与日志只存脱敏版）
2. 对消息正文 `content` 调用 `SensitiveFilter.is_blocked()`：返回 True → 状态 `CONTENT_BLOCKED`，不再发送
3. 对消息正文调用 `ComplianceChecker.check_for_outbound()`：`result.blocked` → 状态 `CONTENT_BLOCKED`
4. 可选词库校验：读取 `SENDRISK_EXTRA_BANNED_WORDS_FILE`（每行一个词）叠加命中判断
5. 命中时记录违规片段（`matches`）→ 写日志 → 调用 `alert_service.service_exception_sync()` 推送告警

**账号封禁检测（ban_detector.py）：**

```
规则：若发送返回值出现以下任一项，视为封禁：
1. 显式 status_code == "BANNED" 或 "FORBIDDEN" 或 包含 "rate_limit" 字眼
2. response_text 命中风控关键词（从 SEND_BAN_KEYWORDS_FILE 或默认词库）
   - "账号被限制" "消息拒收" "请勿频繁发送" "内容违规" "rate limited"
3. 连续 N 次（SEND_BAN_CONSECUTIVE_FAIL=3）NETWORK_ERROR 视为隐性封禁

动作：
- 将 account_id 写入 send:account:banned（SET）
- 在 send:account:meta:{id} HASH 中写入 banned_ts / reason
- 若全渠道可用账号 < 1 → 触发 SEND_ALL_BANNED 告警
- 自动切换：下次分配时跳过被 ban 账号，从备用池里选
- 冷却恢复：SEND_BAN_COOLDOWN_SECONDS=3600 后自动从 banned 集合移除（由 rate_limiter.cleanup 周期清理）
```

## 六、失败重试分级处理规则

```
分类                       重试次数   间隔（秒）   指数退避   触发告警
NETWORK_ERROR              3         10          ✅         第3次失败后
CHANNEL_BAN / FORBIDDEN    0          -          -           立即
CONTENT_BLOCKED            0          -          -           立即（但不消耗额度）
ACCOUNT_BANNED             0          -          -           立即
RATE_LIMITED               2         30          ✅         -

枚举：SendFailureCategory.NETWORK / BAN / CONTENT / QUOTA
```

重试通过 `infra/task_queue.py` 的 `enqueue()` 异步投递；同步流程中若 3 次失败则落 `TASK_FAILED` 并触发告警。

## 七、分步执行开发流程

1. **Step 1**：`account_pool.py` — 解析 `.env` 账号配置 + Account 数据类 + 三种 LB 策略；编写基础测试
2. **Step 2**：`rate_limiter.py` — 四层限流（全局日/单账号日/小时/用户间隔）；用 Redis INCR + TTL 做原子限流；编写独立测试
3. **Step 3**：`content_risk.py` — 封装 T06 SensitiveFilter + PIIMask + ComplianceChecker 调用链；输出 BlockResult；编写测试
4. **Step 4**：`ban_detector.py` — 关键词匹配 + 连续失败计数；banned 集合管理；编写测试
5. **Step 5**：`failure_retry.py` — 分类枚举 + 重试策略；从配置读取次数/间隔；编写测试
6. **Step 6**：`task_status.py` — 状态枚举（PENDING/SENDING/SUCCESS/FAILED/CONTENT_BLOCKED）+ 统一 Redis 读写；提供 `get_status()`/`set_status()`；编写测试
7. **Step 7**：`send_pipeline.py` — 组合步骤3 → 步骤2 → 步骤1 → 调用方发送钩子 → 步骤4/步骤5 → 步骤6；统一 `process_message(task_id, channel, content, recipient_info, sender_fn)` 入口；编写全流程测试
8. **Step 8**：`__init__.py` — 导出各模块单例，暴露统一入口 `send_pipeline.process_message(...)`
9. **Step 9**：`tests/test_t08_infra.py` — 12+ 单元测试，确保各模块独立可测，管线端到端正常，告警触发，失败重试，限流拦截
10. **Step 10**：运行全量测试（`python -m pytest tests/ -v --tb=short`），确保 T01-T08 不破坏；最后提交仓库

## 八、依赖与风险处理

- **Redis 不可用降级**：限流计数器回退到进程内 `threading.Lock + defaultdict(int)`；发送继续执行但降级为"无严格计数"模式，并触发告警
- **合规工具调用失败**：降级为"只做 PIIMask + 关键词最小词库"，避免发送链路阻塞
- **账号全部被 ban**：阻塞后续请求、返回统一 `SendException(SEND_ALL_BANNED)`，触发高级别告警
- **告警去抖**：复用 `infra/alerting.py` debounce；对 `CONTENT_BLOCKED` 做批量告警（单小时命中 ≥ SEND_ALERT_BATCH=5 只推 1 条）
- **并发安全**：所有写 Redis 的操作使用 Lua 脚本或 `INCR + expire` 单步；进程内状态用 `threading.RLock` 保护
- **配置默认值**：所有 `SEND_*` 配置都有默认值，防止缺失时崩溃；加载异常时记录 warning 并使用默认值
