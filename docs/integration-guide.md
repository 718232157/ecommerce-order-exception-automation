# 真实订单系统接入

最简单的接入方式是把企业订单字段转换为本项目的标准 JSON，然后调用：

```text
POST /v1/orders/ingest
```

## 标准订单字段

```json
{
  "eventId": "erp-order-updated-90001-v3",
  "orderId": "ORD-90001",
  "status": "PAID",
  "paidAt": "2026-08-10T09:30:00+08:00",
  "shippedAt": null,
  "refundRequestedAt": null,
  "amount": 1299,
  "quantity": 2,
  "stock": 8,
  "riskScore": 86,
  "duplicatePayment": false,
  "customer": "脱敏客户标识"
}
```

`status` 支持 `PAID / SHIPPED / REFUNDING / COMPLETED / CANCELLED`。`eventId` 在同一次平台重试中必须保持相同，订单产生新变化时应使用新的事件版本。

## 请求签名

```text
X-Timestamp: Unix 秒
X-Signature: hex(HMAC-SHA256(INBOUND_WEBHOOK_SECRET, timestamp + "." + 原始请求体))
```

仓库提供两份可直接改造的客户端：

- [单条 JSON 发送脚本](../scripts/send_signed_order.py)
- [批量 CSV 适配器](../scripts/import_orders_csv.py)

企业适配器还应负责平台回调验签、状态映射、分页或游标、平台限流、客户信息脱敏和失败补偿。淘宝、京东、抖店等正式接口需要企业自行提供开放平台授权，本仓库不包含或伪造这些凭证。

## 服务器部署

默认端口只监听 `127.0.0.1`，其他电脑不能访问。部署到企业服务器时，应通过 Nginx、Caddy 或 API Gateway 暴露 HTTPS 域名，不建议直接将 8080 端口公开到互联网。
