import json
import py_compile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

py_compile.compile(str(ROOT / "services/order-api/app.py"), doraise=True)
for script in (ROOT / "scripts").glob("*.py"):
    py_compile.compile(str(script), doraise=True)

for script in (ROOT / "scripts").glob("*.ps1"):
    if not script.read_text(encoding="utf-8").strip():
        raise AssertionError(f"empty PowerShell script: {script.name}")

for launcher in ("setup.cmd", "start.cmd", "stop.cmd", "configure-feishu.cmd", "import-orders.cmd"):
    if not (ROOT / launcher).is_file():
        raise AssertionError(f"missing beginner launcher: {launcher}")

for launcher in ("setup.sh", "start.sh", "stop.sh", "configure-feishu.sh", "import-orders.sh"):
    if not (ROOT / launcher).is_file():
        raise AssertionError(f"missing macOS/Linux launcher: {launcher}")

for document in ("SECURITY.md", "docs/business-acceptance.md", "docs/operations-runbook.md"):
    if not (ROOT / document).is_file():
        raise AssertionError(f"missing operational document: {document}")

readme = (ROOT / "README.md").read_text(encoding="utf-8")
for image_path in re.findall(r"!\[[^\]]*\]\((docs/images/[^)]+)\)", readme):
    if not (ROOT / image_path).is_file():
        raise AssertionError(f"README image does not exist: {image_path}")

required_nodes = {
    "01-realtime-order-exception.json": {"接收订单", "鉴权与标准化", "是否发现异常", "是否紧急风险"},
    "02-batch-order-scan.json": {"每30分钟巡检", "汇总本轮巡检结果", "保存巡检审计", "是否存在紧急异常"},
    "03-manual-review.json": {"接收复核结论", "查询异常当前状态", "是否已经解决", "保存复核与审计日志"},
    "04-daily-operations-report.json": {"每天9点生成", "汇总当日异常数据", "生成运营日报文本", "受控发送飞书日报"},
    "05-dead-letter-monitor.json": {"每10分钟检查", "查询死信任务", "是否存在死信", "受控发送运维告警"},
}

for filename, expected in required_nodes.items():
    data = json.loads((ROOT / "workflows" / filename).read_text(encoding="utf-8"))
    actual = {node["name"] for node in data["nodes"]}
    missing = expected - actual
    if missing:
        raise AssertionError(f"{filename} missing nodes: {sorted(missing)}")
    if not data.get("connections"):
        raise AssertionError(f"{filename} has no connections")

batch = json.loads((ROOT / "workflows" / "02-batch-order-scan.json").read_text(encoding="utf-8"))
batch_reader = next(node for node in batch["nodes"] if node["name"] == "读取待巡检订单")
if not batch_reader["parameters"].get("sendHeaders"):
    raise AssertionError("batch order read must support protected read endpoints")
batch_event_builder = next(node for node in batch["nodes"] if node["name"] == "拆分并生成巡检事件")
batch_event_code = batch_event_builder["parameters"].get("jsCode", "")
for required_fragment in ("delete payload.eventId", "fingerprint(stable(payload))", "Math.floor(Date.now()/1800000)"):
    if required_fragment not in batch_event_code:
        raise AssertionError("batch scan event IDs must distinguish changed snapshots within one scan window")

review = json.loads((ROOT / "workflows" / "03-manual-review.json").read_text(encoding="utf-8"))
review_writer = next(node for node in review["nodes"] if node["name"] == "保存复核与审计日志")
if "expectedVersion" not in review_writer["parameters"].get("body", ""):
    raise AssertionError("manual review must send optimistic concurrency version")

compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
if "n8n:latest" in compose:
    raise AssertionError("n8n image must be pinned")

example_env = (ROOT / ".env.example").read_text(encoding="utf-8")
for name in ("READ_API_KEY", "PROTECT_READ_ENDPOINTS", "ENABLE_API_DOCS", "NOTIFY_SEVERITIES", "N8N_SECURE_COOKIE"):
    if f"{name}=" not in example_env:
        raise AssertionError(f"missing environment setting: {name}")
for tracked in ROOT.rglob("*"):
    if tracked.is_file() and ".git" not in tracked.parts and tracked.name != ".env":
        text = tracked.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"cli_[A-Za-z0-9]{12,}", text):
            raise AssertionError(f"possible Feishu app credential in {tracked.relative_to(ROOT)}")

print("PASS: code, workflows, one-click launchers, image pins and secret scan are valid")
