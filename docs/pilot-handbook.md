# 企业内部试运行手册

本手册面向准备在隔离环境中验证订单异常处理流程的企业技术、运营和风控人员。目标是完成一次可停止、可追溯、不影响正式履约的小范围试运行，而不是直接替代企业现有订单系统。

## 1. 数据声明与使用边界

- 仓库不包含任何企业真实订单、客户身份或支付信息；
- 示例文件、README 截图和自动化测试均来自合成数据；
- 合成数据只证明流程在已定义场景下可以运行，不证明真实业务的识别准确率、节省工时或经济收益；
- 企业试运行应使用已获授权的脱敏订单，并在进入本系统前移除手机号、地址、支付凭证等非必要字段；
- 默认规则是可运行基线，不是适用于所有企业的行业标准。阈值、严重程度、SLA 和处理建议必须由业务负责人确认；
- 系统只建单、通知、复核和记录审计，不会自动退款、冻结、取消订单或修改正式履约状态。

## 2. 当前可支持的试运行

适合：由一名技术负责人带队，在独立主机、独立数据库和测试飞书群中，使用合成数据或小批量脱敏订单验证异常发现、去重、通知、人工复核、恢复和审计。

暂不适合：没有技术人员参与的业务自助部署、直接暴露到公网、直接承载生产高可用流量，或让工作流自动执行退款和冻结等不可逆动作。

当前人工复核入口是 n8n Webhook 或受保护的 API，飞书多维表格负责台账展示和状态同步；仓库暂未提供面向普通业务人员的独立运营后台。

## 3. 人员与职责

| 角色 | 至少一人 | 主要职责 |
|---|---:|---|
| 技术负责人 | 是 | 部署、密钥、数据映射、备份、监控和停止试运行 |
| 业务负责人 | 是 | 确认规则、阈值、SLA、通知范围和验收结论 |
| 复核人员 | 是 | 处理测试群和台账中的异常，填写复核意见 |
| 数据或安全负责人 | 建议 | 审核脱敏、权限、保留期限和数据清理 |

同一人可以兼任多个角色，但规则变更和高风险处置应保留审批记录。

## 4. 试运行前检查

- 安装并启动 Docker Desktop 或 Docker Engine；
- 准备一台隔离主机，默认端口 `5678` 和 `8080` 不向公网开放；
- 准备独立的飞书测试群和测试多维表格，不使用生产通知群；
- 确认试运行订单范围、负责人、起止时间、数据保留期限和退出条件；
- 选择接入方式：先用合成数据验收，再使用 CSV 或企业适配器接入脱敏订单；
- 禁止把 `.env`、机器人 Webhook、应用密钥和 API Key 提交到仓库或发送给普通业务用户。

推荐先选取 50～500 条覆盖正常、超时发货、高风险、库存不足、退款超时和重复支付的脱敏订单。不要用没有代表性的合成数据计算真实业务收益。

## 5. 安装与基础验收

Windows 双击：

```text
setup.cmd
```

macOS / Linux：

```bash
bash setup.sh
```

安装脚本会生成本地随机密钥、启动 PostgreSQL、FastAPI 和 n8n，导入并发布 5 条工作流，并验证实时 Webhook 能处理一条正常订单。

安装后检查：

```bash
docker compose ps
curl http://127.0.0.1:8080/health/ready
curl http://127.0.0.1:5678/healthz
```

预期结果：三个容器均为运行或健康状态，API 返回 `status=ready`，n8n 健康检查成功。

Windows 可继续执行完整冒烟验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
```

该脚本会提交合成高风险订单并完成一次人工复核。必须只在隔离测试环境执行。

## 6. 确认和调整业务规则

先查看当前规则：

```bash
curl http://127.0.0.1:8080/rules
```

默认包含超时未发货、高风险订单、库存不足、退款超时和重复支付。业务负责人应逐项确认启用状态、严重程度、阈值、处理建议和对应 SLA。

规则通过管理员接口修改并写入审计。例如把高风险阈值调整为 85：

```bash
set -a; source .env; set +a
curl -X PUT http://127.0.0.1:8080/rules/HIGH_RISK_ORDER \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"threshold":85,"severity":"CRITICAL"}'
```

Windows PowerShell：

```powershell
$config = @{}
Get-Content .env | Where-Object { $_ -match '^[A-Z0-9_]+=' } | ForEach-Object {
  $key, $value = $_.Split('=', 2); $config[$key] = $value
}
$body = @{ threshold = 85; severity = 'CRITICAL' } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:8080/rules/HIGH_RISK_ORDER' `
  -Headers @{ 'X-API-Key' = $config.ADMIN_API_KEY } -ContentType 'application/json' -Body $body
```

不要把真实密钥粘贴到工单、截图或聊天记录中。规则变更后应记录变更人、原因、原值、新值和回滚值，并重新运行对应验收场景。

## 7. 接入试运行订单

### 方案 A：合成数据验证流程

```bash
python scripts/generate_synthetic_orders.py --count 100 --seed 20260812 --output work/synthetic-orders.csv
bash import-orders.sh work/synthetic-orders.csv
```

Windows 可将 CSV 拖到 `import-orders.cmd`。这一步只验证系统链路，不用于评估真实准确率。

### 方案 B：企业 CSV 小批量导入

1. 复制 `samples/orders-template.csv`；
2. 只填写标准契约需要的脱敏字段；
3. 在隔离环境先导入 5 条并核对结果；
4. 再逐步扩大到确认过的试运行范围。

### 方案 C：企业系统持续接入

使用带 HMAC 签名的 `POST /v1/orders/ingest`。适配器需要负责平台验签、字段映射、稳定 `eventId`、限流和错误补偿，具体见 [真实订单系统接入](integration-guide.md)。仓库不内置淘宝、京东、抖店等平台的正式授权凭证。

## 8. 配置飞书

Windows 双击 `configure-feishu.cmd`，macOS / Linux 运行：

```bash
bash configure-feishu.sh
```

配置向导会验证机器人和多维表格配置，并创建缺失字段。建议顺序：

1. 先只配置测试多维表格，确认异常能持续更新同一记录；
2. 再配置测试群机器人；
3. 保持 `NOTIFY_SEVERITIES=CRITICAL`，确认值班能力后再扩大通知范围；
4. 日报和死信群告警默认关闭，确认接收人后再启用。

详细权限和字段配置见 [飞书接入说明](feishu-setup.md)。

## 9. 业务验收

至少验证以下闭环：

| 场景 | 验收结果 |
|---|---|
| 正常订单 | 不建异常工单，不发送紧急通知 |
| 首次异常 | 建立对应异常，写入审计和飞书台账 |
| 重复事件 | 不重复建单、不重复即时通知 |
| 高风险订单 | 标记 `CRITICAL` 并进入人工复核 |
| 两人并发复核 | 旧版本提交返回 `409`，不覆盖新结论 |
| 恢复快照 | 原异常自动解决并同步台账 |
| 飞书临时失败 | 订单事务保留，Outbox 重试并可被监控 |

完整输入和期望结果见 [业务验收方案](business-acceptance.md)。验收记录至少包含代码版本、规则版本、数据来源、样本量、执行人、失败项和最终结论。

## 10. 日常操作 SOP

### 开始值班

1. 检查 `GET /health/ready`；
2. 查看 `GET /stats` 中待复核数量和 Outbox 状态；
3. 确认飞书测试群、台账和当班负责人可用；
4. 检查最近 `GET /events` 是否存在异常峰值或连续失败。

### 人工复核

复核人员先读取异常最新状态和 `version`，核对订单证据后再提交 `APPROVED`、`REJECTED` 或 `RESOLVED`。通过 n8n 复核 Webhook 的示例：

```bash
set -a; source .env; set +a
curl -X POST http://127.0.0.1:5678/webhook/exception-review \
  -H "X-API-Key: $REVIEW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"exceptionId":1,"status":"APPROVED","reviewer":"张三","note":"已核对支付和收货信息"}'
```

收到 `409` 表示异常已被其他人员或自动流程更新，应重新读取并人工判断，不能自动覆盖。业务判断依据和证据应写入 `note`，不要填写客户敏感信息。

### 结束值班

1. 确认紧急异常已分配或交接；
2. 检查 Outbox 没有持续积压的 `RETRY`、`PROCESSING` 或 `DEAD`；
3. 记录误报、漏报、规则争议和故障；
4. 未解决事项明确下一班负责人和完成时间。

故障定位、死信重试和密钥轮换见 [运维手册](operations-runbook.md)。

## 11. 试运行指标和通过条件

试运行开始前由业务负责人给出目标，不要结束后再选择有利指标。至少记录：

- 接入成功率和异常识别一致率；
- 重复工单数和重复即时通知数；
- 待复核数量、首次响应时间和处理完成时间；
- 自动恢复数量、人工解决数量和版本冲突次数；
- Outbox 成功、重试和死信数量；
- 人工确认的误报、漏报及原因。

只有使用企业授权的脱敏样本并由业务人员复核后，才能描述该企业试运行的准确率和效率。合成数据结果只能写为“场景验收通过”。

## 12. 暂停、回滚和清理

暂停接入的顺序：停止上游发送或定时任务，确认在途事件处理完成，再停止服务。

```bash
bash stop.sh
```

Windows 双击 `stop.cmd`。停止服务会保留 PostgreSQL 和 n8n 数据卷，重新启动后可继续检查。

规则回滚：使用管理员接口恢复变更前的字段值，并核对 `GET /events` 中的 `RULE_UPDATED` 审计。应用版本回滚前先执行数据库备份，恢复方法见 [高级部署](advanced-deployment.md)。

只有在确认环境属于本次隔离试运行、备份已完成且数据保留期结束后，才能删除数据卷：

```bash
docker compose down -v
```

该命令会永久删除本项目的 PostgreSQL 和 n8n 本地数据，不能恢复；不要在路径、项目或环境不明确时执行。

## 13. 从试运行到正式使用

试运行通过不等于可以直接上线。正式使用前至少需要完成：高可用 PostgreSQL、HTTPS 网关、SSO 或统一认证、Secret Manager、网络访问控制、集中日志监控、备份恢复演练、容量测试、数据保留策略和平台正式授权。逐项检查 [上线检查清单](production-checklist.md) 与 [安全说明](../SECURITY.md)。
