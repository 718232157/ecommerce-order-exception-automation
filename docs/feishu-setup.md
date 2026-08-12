# 飞书配置步骤

系统需要两类飞书能力：群机器人负责通知，多维表格负责异常台账。二者都可以不配置。

## 1. 群机器人 Webhook

1. 打开目标飞书群的设置。
2. 进入“群机器人”，添加“自定义机器人”。
3. 复制形如 `https://open.feishu.cn/open-apis/bot/v2/hook/...` 的 Webhook 地址。

## 2. 企业自建应用

1. 打开飞书开放平台，创建企业自建应用。
2. 在凭证页面复制 App ID 和 App Secret。
3. 为应用开通多维表格记录和字段的读取、写入权限。
4. 创建版本并发布应用。

## 3. 多维表格授权

1. 新建一个多维表格。
2. 在表格的协作者或“添加文档应用”中加入刚创建的应用，授予可管理权限。
3. 从浏览器地址复制 App Token 和 Table ID。地址通常包含 `/base/{AppToken}?table={TableId}`。

## 4. 运行配置向导

双击项目根目录的 `configure-feishu.cmd`，依次粘贴上述5项。向导会自动重启订单服务、验证凭证并创建台账字段。

日报和死信告警默认关闭。先确认机器人所在群无误，再编辑 `.env`：

```dotenv
ENABLE_DAILY_REPORTS=true
ENABLE_DEAD_LETTER_ALERTS=true
```

然后双击 `stop.cmd`、`start.cmd` 使配置生效。
