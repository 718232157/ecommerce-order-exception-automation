import json
import py_compile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

py_compile.compile(str(ROOT / "services/order-api/app.py"), doraise=True)

for script in (ROOT / "scripts").glob("*.ps1"):
    if not script.read_text(encoding="utf-8").strip():
        raise AssertionError(f"empty PowerShell script: {script.name}")

for launcher in ("setup.cmd", "start.cmd", "stop.cmd", "configure-feishu.cmd", "import-orders.cmd"):
    if not (ROOT / launcher).is_file():
        raise AssertionError(f"missing beginner launcher: {launcher}")

for launcher in ("setup.sh", "start.sh", "stop.sh", "configure-feishu.sh", "import-orders.sh"):
    if not (ROOT / launcher).is_file():
        raise AssertionError(f"missing macOS/Linux launcher: {launcher}")

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

compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
if "n8n:latest" in compose:
    raise AssertionError("n8n image must be pinned")
for tracked in ROOT.rglob("*"):
    if tracked.is_file() and ".git" not in tracked.parts and tracked.name != ".env":
        text = tracked.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"cli_[A-Za-z0-9]{12,}", text):
            raise AssertionError(f"possible Feishu app credential in {tracked.relative_to(ROOT)}")

print("PASS: code, workflows, one-click launchers, image pins and secret scan are valid")
