# 高级部署与手动命令

## 手动启动

```bash
cp .env.example .env
# 替换全部 replace-with... 密钥
docker compose --env-file .env up -d --build
docker compose --env-file .env cp ./workflows n8n:/tmp/workflows
docker compose --env-file .env exec -T n8n n8n import:workflow --separate --input=/tmp/workflows
```

随后分别发布 `workflows/` 中5条工作流，或在 n8n 页面中检查后发布。

## 常用命令

```bash
docker compose ps
docker compose logs -f order-api
docker compose down
```

`docker compose down` 会保留数据。不要使用 `down -v`，除非已经确认要删除 PostgreSQL 和 n8n 数据卷。

## 数据库备份

```bash
docker compose exec -T postgres pg_dump -U order_app -d order_automation -Fc > backup.dump
```

恢复会覆盖目标数据库，应在已确认的环境执行：

```powershell
Get-Content backup.dump -AsByteStream | docker compose exec -T postgres pg_restore -U order_app -d order_automation --clean --if-exists
```

## 安全说明

n8n 节点需要读取 `INTERNAL_API_KEY`，本地 Compose 设置了 `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`。能够编辑工作流的人员可能读取容器变量，因此编辑权限只能授予可信管理员。生产环境建议使用 n8n Credentials、外部 Secret Store、HTTPS 网关、SSO、IP 限制、集中日志与监控。
