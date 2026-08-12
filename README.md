# 电商订单异常处理自动化系统

把订单交给系统，它会自动识别超时未发货、高风险订单、库存不足、退款超时和重复支付，并完成异常台账、飞书通知、人工复核、日报和失败监控。

无需购买服务器，也无需先配置飞书。下载后可以先在自己电脑上完整体验，确认适合后再接入真实业务。

## Windows：三步运行

### 1. 准备 Docker

安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。已经安装过可跳过。

### 2. 下载项目

点击 GitHub 页面右上角 `Code → Download ZIP`，解压到任意文件夹。

### 3. 双击安装

双击项目中的：

```text
setup.cmd
```

脚本会自动完成：

- 检查 Docker；
- 生成数据库密码和接口密钥；
- 启动 PostgreSQL、订单服务和 n8n；
- 导入并发布全部 5 条工作流；
- 打开 n8n 页面。

首次打开只需创建一个自己的 n8n 管理员账号。完成后即可看到所有工作流。

> 以后使用：双击 `start.cmd` 启动，双击 `stop.cmd` 停止。停止不会删除订单和工作流。

## 先试一下

进入 n8n，打开 `02-定时批量订单巡检`，点击底部 `Execute workflow`。系统内置了脱敏样例订单，可以直接看到巡检、异常分级、汇总和审计结果。

本机查看地址：

- n8n 工作流：<http://127.0.0.1:5678>
- 异常记录：<http://127.0.0.1:8080/exceptions>
- 统计结果：<http://127.0.0.1:8080/stats>
- 接口文档：<http://127.0.0.1:8080/docs>

`127.0.0.1` 表示当前电脑。其他人安装后使用相同地址，看到的是他自己电脑上的系统。

## 导入自己的订单

不需要电商开放平台账号也能使用 CSV：

1. 复制 [订单模板](samples/orders-template.csv) 并填写自己的订单；
2. 把 CSV 文件拖到 `import-orders.cmd` 上；
3. 脚本会自动导入、识别异常并显示结果。

CSV 至少填写 `orderId` 和 `status`。客户信息建议先脱敏。

如果公司已有 ERP、电商开放平台或消息系统，可按 [真实系统接入说明](docs/integration-guide.md) 调用签名接口。

## 接入飞书（可选）

没有飞书配置时系统仍可正常识别和保存异常。需要群通知和多维表格时，双击：

```text
configure-feishu.cmd
```

按提示粘贴机器人 Webhook、应用 ID/Secret、多维表格 Token 和 Table ID，脚本会自动重启服务并创建台账字段。获取这些信息的方法见 [飞书配置图文步骤](docs/feishu-setup.md)。

日报和死信告警默认关闭，避免测试消息进入真实群。确认目标群后再在 `.env` 中开启：

```dotenv
ENABLE_DAILY_REPORTS=true
ENABLE_DEAD_LETTER_ALERTS=true
```

## 包含哪些工作流

| 工作流 | 作用 |
|---|---|
| 01 实时订单异常识别 | 接收单条订单，识别异常并按紧急程度响应 |
| 02 定时批量订单巡检 | 每30分钟巡检订单并汇总本轮结果 |
| 03 高风险人工复核 | 防止重复复核，保存处理人、意见和审计记录 |
| 04 每日异常运营报告 | 汇总新增、待处理、已解决和风险分布 |
| 05 失败任务与死信监控 | 检查投递失败任务并生成运维告警 |

## 真实业务能力

系统包含 PostgreSQL 事务、HMAC 验签、防重放、幂等业务编号、动态规则、Transactional Outbox、指数退避、死信、飞书最终一致性和审计记录。技术设计、验证方法及生产边界见 [架构设计](docs/architecture.md) 和 [上线检查清单](docs/production-checklist.md)。

默认输入方式为标准订单接口和 CSV。连接淘宝、京东、抖店等生产平台时，需要配置企业正式授权的平台适配器，并落实 HTTPS、权限控制和数据合规措施。

## macOS：三步运行

1. 安装并启动 [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)；下载时按电脑型号选择 Apple 芯片或 Intel 芯片版本；
2. 下载并解压项目，在“终端”中输入 `cd `（注意后面有一个空格），把项目文件夹拖进终端窗口，然后按回车；
3. 复制下面这条命令并按回车：

```bash
bash setup.sh
```

该脚本与 Windows 一键安装完成相同工作：自动生成密钥、启动服务、导入并发布 5 条工作流，最后打开浏览器。Apple 芯片和 Intel 芯片均支持，不需要自行安装 Python、Node.js、PostgreSQL 或 n8n。

以后启动和停止：

```bash
bash start.sh
bash stop.sh
```

接入飞书：

```bash
bash configure-feishu.sh
```

导入订单 CSV（无需本机安装 Python）：

```bash
bash import-orders.sh /Users/你的名字/Desktop/orders.csv
```

Linux 用户也可使用这些 `.sh` 脚本；无桌面浏览器的服务器请访问 [高级部署说明](docs/advanced-deployment.md)。

## License

[MIT](LICENSE)
