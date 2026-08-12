# Security

## 支持范围

该仓库默认用于本地验证和受控内网部署。`compose.yaml` 只把 API 与 n8n 绑定到 `127.0.0.1`。公开部署必须增加 HTTPS 网关、身份认证、限流、请求体限制、集中日志和网络访问控制。

## 身份边界

- 外部订单入口：HMAC + 五分钟时间窗；
- n8n 内部调用：`INTERNAL_API_KEY`；
- 人工复核：`REVIEW_API_KEY` + 乐观并发版本；
- 规则、飞书初始化和死信重试：`ADMIN_API_KEY`；
- 生产读取接口：`PROTECT_READ_ENDPOINTS=true` + `READ_API_KEY`。

HTTPS 部署同时设置 `ENABLE_API_DOCS=false` 和 `N8N_SECURE_COOKIE=true`；如需内部 API 文档，应由网关单独授权，而不是公开 FastAPI 文档端点。

不同用途必须使用不同随机密钥。不得把 `INTERNAL_API_KEY` 发给外部平台或普通业务用户。

## 数据处理

- 客户标识在进入系统前脱敏；
- 日志和通知不写入地址、手机号、支付凭证等敏感字段；
- 按企业政策设置数据库、审计和备份保留期限；
- 测试环境不得连接生产飞书群或生产数据库；
- 仓库中的样例和生成器只产生合成数据。

## 报告漏洞

请通过仓库 Security Advisory 私下报告安全问题。报告应包含受影响版本、复现条件、潜在影响和建议修复方式。不要在公开 Issue 中提交密钥、客户数据或可利用细节。
