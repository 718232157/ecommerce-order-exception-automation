# 电商订单异常处理自动化

[![validate](https://github.com/718232157/ecommerce-order-exception-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/718232157/ecommerce-order-exception-automation/actions/workflows/ci.yml)

企业通常不是完全看不到异常，而是异常标记留在订单、仓储或退款系统的页面里，仍要运营人员反复查找；发现以后，谁处理、是否重复通知、订单恢复后是否关闭也容易断链。

这个项目提供一层独立的订单异常处置流程，不替代 ERP 或 OMS。订单快照从 ERP、平台适配器或 CSV 进入后，系统自动识别和分级：紧急异常立即通知飞书群，其他异常进入台账并可按需汇总日报；后续复核、恢复和外部同步均可追踪。

> **一句话说明**：不用运营人员持续翻查订单页面，系统自动筛出需要处理的订单；紧急事件主动找人，普通事件集中沉淀，并持续跟踪到解决。

`n8n + FastAPI + PostgreSQL + 飞书`，本地 Docker 可完整运行。

> **数据与适用范围**：仓库不包含任何企业真实订单或个人信息。示例、截图和自动化验收均使用可复现的合成数据，用于验证流程、接口和故障边界，不代表真实企业的订单分布或业务收益。系统按真实订单异常处置链路设计；企业接入时仍需使用授权后的脱敏数据校准规则，并由业务负责人确认 SLA 和处置策略。

## 一眼看懂流程

```mermaid
flowchart LR
    A1["ERP / OMS"] --> B["标准订单快照"]
    A2["平台适配器"] --> B
    A3["CSV"] --> B
    B --> C["异常识别与分级"]
    C -- "正常" --> D["不打扰"]
    C -- "异常" --> E["工单、台账与审计"]
    E --> F["CRITICAL 立即通知飞书"]
    E --> G["HIGH / MEDIUM 进入台账 / 可选日报"]
    F --> H["人工复核"]
    G --> H
    B -. "恢复快照" .-> I["自动解决异常"]
    H --> J["状态回写"]
    I --> J

    classDef input fill:#eef2ff,stroke:#6366f1,color:#1e1b4b;
    classDef core fill:#fff7ed,stroke:#f97316,color:#7c2d12;
    classDef action fill:#ecfdf5,stroke:#10b981,color:#064e3b;
    class A1,A2,A3,B input;
    class C,E core;
    class D,F,G,H,I,J action;
```

实时 Webhook 负责快速响应，定时巡检负责补偿；订单、异常、审计和 Outbox 在同一 PostgreSQL 事务中提交。

## 不只是把订单标红

成熟的 ERP、OMS 或电商平台通常已经能标记一部分风险。本项目的价值不是再画一个红色标签，而是把标签之后容易断掉的处置过程补齐。

| 常见的异常标记 | 这套流程继续完成 |
|---|---|
| 异常停留在系统页面，等待人查看 | 实时接收与每 30 分钟巡检主动发现，无需持续翻页 |
| 所有异常混在一起或一律发群 | `CRITICAL` 立即通知，`HIGH/MEDIUM` 进入台账并可按需汇总日报 |
| 只显示“有风险” | 建立工单，保存原因、处理建议、负责人、意见和状态 |
| 重复扫描产生重复工单或刷屏 | 对事件、未关闭异常和通知分别防重 |
| 多人处理时结论互相覆盖 | 复核使用版本校验，过期操作返回 `409` |
| 订单恢复后标记仍然挂着 | 新快照恢复正常时自动解决，并保留完整审计 |
| 飞书调用失败后消息丢失 | Outbox 异步重试，耗尽后进入死信监控 |

它更适合订单来源不止一个、团队主要在飞书协作，或者现有系统只有异常标记但缺少处置闭环的场景。如果企业现有平台已经完整覆盖统一识别、分级通知、负责人、复核、防重、恢复和审计，应优先复用现有能力。

## 5 分钟运行

### Windows

1. 安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)；
2. 下载并解压仓库；
3. 双击 `setup.cmd`。

### macOS / Linux

```bash
bash setup.sh
```

脚本会生成本地密钥、启动 PostgreSQL、API 和 n8n，并导入发布 5 条工作流。首次进入 n8n 时创建本地管理员账号，然后打开 `02-定时批量订单巡检`，点击 `Execute workflow`。

如果准备在企业内部小范围试运行，请不要直接连接生产订单和业务群，先按照 [企业内部试运行手册](docs/pilot-handbook.md) 完成角色分工、隔离部署、规则确认、验收和退出检查。

| 入口 | 地址 |
|---|---|
| n8n | <http://127.0.0.1:5678> |
| 异常台账 API | <http://127.0.0.1:8080/exceptions> |
| 运营统计 | <http://127.0.0.1:8080/stats> |
| OpenAPI 文档 | <http://127.0.0.1:8080/docs> |

停止服务使用 `stop.cmd` 或 `bash stop.sh`，数据卷会保留。本地端口只监听 `127.0.0.1`。

## 能识别哪些异常

| 异常 | 判断依据 | 默认处理 |
|---|---|---|
| 超时未发货 | 付款后超过规则时限仍未发货 | 建单，建议核查仓库和承运状态 |
| 高风险订单 | 风控评分超过阈值 | 标记 `CRITICAL`，暂停自动履约并请求复核 |
| 库存不足 | 购买数量超过可用库存 | 建单，建议锁单并协调库存 |
| 退款超时 | 退款申请超过处理时限 | 建单，建议核查退款通道 |
| 重复支付 | 上游快照标记重复款项 | 建单，建议冻结重复款项后续处理 |

规则是可运行基线，正式接入时应由业务负责人确认阈值和处置策略。系统只生成建议和复核任务，不会自动退款、冻结或取消订单。

## 好不好用：关键保障

| 保障 | 实际效果 |
|---|---|
| 幂等接入 | 同一 `eventId` 和正文重放不会重复处理；同 ID 不同正文返回 `409` |
| 异常防重 | 同一订单、同一异常类型只保留一张未解决工单 |
| 并发安全 | 复核携带 `expectedVersion`，防止后提交的人覆盖先提交的结果 |
| 自动恢复 | 最新快照恢复正常后自动解决；异常复发时重新打开原工单 |
| 通知降噪 | 默认只即时通知 `CRITICAL`，重复命中只更新台账 |
| 失败恢复 | 飞书调用异步重试，耗尽后进入 `DEAD`，支持管理员重试 |
| 全程可追溯 | 识别、复核、解决、复发和外部同步均记录审计 |

## 5 条 n8n 工作流

| 工作流 | 触发方式 | 职责 |
|---|---|---|
| 01 实时订单异常识别 | Webhook | 单条订单接入、规则判断、异常分级和响应 |
| 02 定时批量订单巡检 | 每 30 分钟 / 手动 | 扫描存量订单、补偿检测、汇总和审计 |
| 03 高风险人工复核 | Webhook | 校验当前状态和版本，保存复核结论 |
| 04 每日异常运营报告 | 每天 9 点 / 手动 | 汇总新增、待处理、解决和风险分布 |
| 05 失败任务与死信监控 | 每 10 分钟 / 手动 | 检查死信并生成受控运维告警 |

<details>
<summary><strong>查看 5 条工作流画布</strong></summary>

### 01 实时订单异常识别

![实时订单异常识别与通知工作流](docs/images/workflow-01-realtime.png)

### 02 定时批量订单巡检

![定时批量订单巡检工作流](docs/images/workflow-02-batch-scan.png)

### 03 高风险人工复核

![高风险异常人工复核工作流](docs/images/workflow-03-manual-review.png)

### 04 每日异常运营报告

![每日异常运营报告工作流](docs/images/workflow-04-daily-report.png)

### 05 失败任务与死信监控

![失败任务与死信监控工作流](docs/images/workflow-05-dead-letter.png)

</details>

## 接入订单数据

### 企业系统

标准入口接收订单完整快照：

```text
POST /v1/orders/ingest
X-Timestamp: Unix 秒
X-Signature: hex(HMAC-SHA256(secret, timestamp + "." + 原始请求体))
```

平台适配器负责上游验签、状态映射、分页或游标、限流、脱敏和稳定事件版本。字段契约与签名示例见 [真实系统接入说明](docs/integration-guide.md)。

### CSV 或合成数据

```bash
python scripts/generate_synthetic_orders.py --count 1000 --output work/synthetic-orders.csv
bash import-orders.sh work/synthetic-orders.csv
```

Windows 也可以把 CSV 拖到 `import-orders.cmd`。生成数据带验收标签但不包含企业客户数据，场景说明见 [业务验收方案](docs/business-acceptance.md)。

## 接入飞书

双击 `configure-feishu.cmd` 或运行 `bash configure-feishu.sh`，按提示填写群机器人 Webhook、飞书应用凭证和多维表格信息。系统会创建缺失字段，后续使用保存的 Record ID 更新同一条异常记录。

```dotenv
NOTIFY_SEVERITIES=CRITICAL
ENABLE_DAILY_REPORTS=false
ENABLE_DEAD_LETTER_ALERTS=false
```

日报和死信告警默认关闭，确认目标群和消息量后再启用。完整步骤见 [飞书接入说明](docs/feishu-setup.md)。

## 如何证明它能工作

GitHub Actions 每次提交都会在隔离环境中：

1. 校验 Python、5 条 n8n 工作流、Compose、镜像版本和凭证泄漏；
2. 启动真实 PostgreSQL 与 FastAPI；
3. 验证签名、防重放、事件冲突和 20 单并发编号；
4. 验证复核版本冲突、异常复发、自动恢复和运维端点；
5. 导入并发布 n8n 工作流，实际调用订单 Webhook；
6. 销毁隔离数据卷。

```bash
python scripts/validate_project.py
python scripts/integration_test.py  # 需要已启动的隔离环境
```

集成测试检测到真实飞书配置时会拒绝运行，避免测试消息进入业务群。

## 上线前需要知道

- 仓库提供订单异常处理底座，不包含企业正式平台授权和专有字段映射。
- 本地 Docker Compose 用于体验和验收，不是高可用部署方案。
- 服务器部署时应启用读取鉴权、关闭 API 文档并开启 n8n 安全 Cookie。
- 生产接入前请完成 [上线检查清单](docs/production-checklist.md) 和 [安全说明](SECURITY.md)。

进一步阅读：[企业内部试运行手册](docs/pilot-handbook.md) · [架构设计](docs/architecture.md) · [运维手册](docs/operations-runbook.md) · [高级部署](docs/advanced-deployment.md)

## License

[MIT](LICENSE)
