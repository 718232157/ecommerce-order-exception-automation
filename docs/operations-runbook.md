# 运维手册

## 每日检查

1. `/health/ready` 返回数据库就绪；
2. `/stats` 中 `outbox` 不持续积压 `RETRY/PROCESSING`；
3. 检查待复核数量和最长等待时间；
4. 检查飞书机器人和多维表格负责人是否仍有效；
5. 查看最近100条 `/events` 审计记录是否存在异常峰值。

服务器模式启用 `PROTECT_READ_ENDPOINTS=true` 后，读取接口需要 `X-API-Key: READ_API_KEY`，n8n 内部读取使用 `X-Internal-Key`。

## 通知原则

- `CRITICAL` 默认即时发送；
- `HIGH/MEDIUM` 默认只进入台账和日报；
- 同一未关闭异常重复命中只更新台账；
- 批量验收必须使用测试群；
- 修改 `NOTIFY_SEVERITIES` 前由业务负责人确认群消息容量和处理值班安排。

## Outbox 处置

1. 查询 `/internal/outbox/dead`；
2. 根据 `last_error` 判断凭证、限流、网络或字段问题；
3. 先修复外部依赖；
4. 管理员调用 `POST /outbox/{id}/retry`；
5. 验证状态变为 `DONE`，并检查飞书记录；
6. 在事故记录中保留影响范围、开始/恢复时间和根因。

不要在依赖仍故障时批量重试，避免进一步触发限流。

## 备份

```bash
docker compose exec -T postgres pg_dump -U order_app -d order_automation -Fc > backup.dump
```

至少定期抽样恢复到隔离数据库，确认备份可用。恢复命令见 [高级部署](advanced-deployment.md)。

## 密钥轮换

1. 在 Secret Manager 或受控配置中生成新密钥；
2. 更新调用方和服务端；
3. 重启受影响服务并执行健康检查；
4. 吊销旧密钥；
5. 记录轮换人、时间和验证结果。

本地 `.env` 不提交仓库。飞书应用遵循最小权限，并将工作流编辑权限限制给可信管理员。
