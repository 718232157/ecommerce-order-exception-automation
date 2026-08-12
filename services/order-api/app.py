import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from psycopg.rows import dict_row
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

CN_TZ = timezone(timedelta(hours=8))
DATABASE_URL = os.getenv("DATABASE_URL") or make_conninfo(
    host=os.getenv("PGHOST", "postgres"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "order_automation"),
    user=os.getenv("PGUSER", "order_app"),
    password=os.environ["PGPASSWORD"],
)
FEISHU_API = "https://open.feishu.cn/open-apis"
TOKEN_CACHE = {"value": "", "expires_at": 0.0}
STOP_EVENT = threading.Event()
SEED_SAMPLE_DATA = os.getenv("SEED_SAMPLE_DATA", "true").lower() in {"1", "true", "yes"}

pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=False)


class Order(BaseModel):
    model_config = ConfigDict(extra="allow")
    orderId: str = Field(min_length=3, max_length=100)
    status: Literal["PAID", "SHIPPED", "REFUNDING", "COMPLETED", "CANCELLED"]
    paidAt: datetime | None = None
    shippedAt: datetime | None = None
    refundRequestedAt: datetime | None = None
    amount: float = Field(default=0, ge=0)
    quantity: int = Field(default=1, ge=1)
    stock: int = Field(default=0, ge=0)
    riskScore: int = Field(default=0, ge=0, le=100)
    duplicatePayment: bool = False
    customer: str | None = None
    eventId: str | None = Field(default=None, max_length=200)


class Review(BaseModel):
    status: str
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=1000)


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    severity: Literal["MEDIUM", "HIGH", "CRITICAL"] | None = None
    threshold: float | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    suggestion: str | None = Field(default=None, min_length=1, max_length=1000)


class OperationalNotification(BaseModel):
    eventId: str = Field(min_length=3, max_length=200)
    category: Literal["DAILY_REPORT", "DEAD_LETTER_ALERT"]
    message: str = Field(min_length=1, max_length=4000)


def now():
    return datetime.now(CN_TZ)


def now_iso():
    return now().replace(microsecond=0).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS business_sequences (
  sequence_date date PRIMARY KEY,
  last_value integer NOT NULL CHECK(last_value > 0)
);
CREATE TABLE IF NOT EXISTS orders (
  order_id varchar(100) PRIMARY KEY,
  payload jsonb NOT NULL,
  source varchar(50) NOT NULL DEFAULT 'API',
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS inbound_events (
  event_id varchar(200) PRIMARY KEY,
  order_id varchar(100) NOT NULL,
  payload_hash char(64) NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS exception_rules (
  rule_code varchar(50) PRIMARY KEY,
  enabled boolean NOT NULL DEFAULT true,
  severity varchar(20) NOT NULL,
  threshold numeric,
  description text NOT NULL,
  suggestion text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS exceptions (
  id bigserial PRIMARY KEY,
  exception_no varchar(40) UNIQUE NOT NULL,
  idempotency_key varchar(250) UNIQUE NOT NULL,
  order_id varchar(100) NOT NULL,
  exception_type varchar(50) NOT NULL,
  severity varchar(20) NOT NULL,
  reason text NOT NULL,
  suggestion text NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'PENDING_REVIEW',
  reviewer varchar(100),
  review_note text,
  feishu_record_id varchar(100),
  first_detected_at timestamptz NOT NULL DEFAULT now(),
  last_detected_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  version integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  event_type varchar(50) NOT NULL,
  entity_type varchar(30) NOT NULL,
  entity_id varchar(100) NOT NULL,
  actor varchar(100) NOT NULL,
  detail jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outbox (
  id bigserial PRIMARY KEY,
  event_key varchar(250) UNIQUE NOT NULL,
  event_type varchar(50) NOT NULL,
  aggregate_id bigint NOT NULL,
  payload jsonb NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'PENDING',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(status,next_attempt_at);
"""

RULES = [
    ("SHIPMENT_TIMEOUT", "HIGH", 48, "付款后超时未发货", "立即核查仓库与承运状态；超过 SLA 时联系客户并补偿"),
    ("HIGH_RISK_ORDER", "CRITICAL", 80, "订单风控评分超过阈值", "暂停自动履约，由风控人员核验账号、地址与支付信息"),
    ("INVENTORY_SHORTAGE", "HIGH", 0, "购买数量超过可用库存", "锁定订单，协调调拨或联系客户变更/退款"),
    ("REFUND_TIMEOUT", "MEDIUM", 24, "退款申请处理超时", "检查退款通道并在人工确认后重新发起"),
    ("DUPLICATE_PAYMENT", "CRITICAL", 0, "检测到重复支付", "冻结重复款项的后续处理，人工核对后原路退款"),
]


def init_database():
    with pool.connection() as conn:
        # Multiple Uvicorn workers may start simultaneously. A PostgreSQL
        # advisory lock serialises schema bootstrap without a separate tool.
        conn.execute("SELECT pg_advisory_lock(724031908)")
        try:
            conn.execute(SCHEMA)
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO exception_rules(rule_code,severity,threshold,description,suggestion)
                       VALUES(%s,%s,%s,%s,%s) ON CONFLICT(rule_code) DO NOTHING""",
                    RULES,
                )
            conn.commit()
        finally:
            conn.execute("SELECT pg_advisory_unlock(724031908)")


def seed_orders():
    with pool.connection() as conn:
        if conn.execute("SELECT count(*) count FROM orders").fetchone()["count"]:
            return
        stamp = now()
        samples = [
            {"orderId":"ORD-20260812-001","status":"PAID","paidAt":(stamp-timedelta(hours=72)).isoformat(),"shippedAt":None,"amount":1299,"quantity":1,"stock":8,"riskScore":23,"refundRequestedAt":None,"duplicatePayment":False,"customer":"张*"},
            {"orderId":"ORD-20260812-002","status":"PAID","paidAt":(stamp-timedelta(hours=3)).isoformat(),"shippedAt":None,"amount":8999,"quantity":1,"stock":5,"riskScore":91,"refundRequestedAt":None,"duplicatePayment":False,"customer":"李*"},
            {"orderId":"ORD-20260812-003","status":"PAID","paidAt":(stamp-timedelta(hours=5)).isoformat(),"shippedAt":None,"amount":299,"quantity":6,"stock":2,"riskScore":35,"refundRequestedAt":None,"duplicatePayment":False,"customer":"王*"},
            {"orderId":"ORD-20260812-004","status":"REFUNDING","paidAt":(stamp-timedelta(days=3)).isoformat(),"shippedAt":None,"amount":599,"quantity":1,"stock":9,"riskScore":18,"refundRequestedAt":(stamp-timedelta(hours=31)).isoformat(),"duplicatePayment":False,"customer":"赵*"},
            {"orderId":"ORD-20260812-005","status":"PAID","paidAt":(stamp-timedelta(hours=2)).isoformat(),"shippedAt":None,"amount":199,"quantity":1,"stock":20,"riskScore":9,"refundRequestedAt":None,"duplicatePayment":True,"customer":"陈*"},
            {"orderId":"ORD-20260812-006","status":"SHIPPED","paidAt":(stamp-timedelta(hours=16)).isoformat(),"shippedAt":(stamp-timedelta(hours=4)).isoformat(),"amount":399,"quantity":1,"stock":12,"riskScore":12,"refundRequestedAt":None,"duplicatePayment":False,"customer":"周*"},
        ]
        for item in samples:
            conn.execute(
                """INSERT INTO orders(order_id,payload,source)
                   VALUES(%s,%s::jsonb,'SEED') ON CONFLICT(order_id) DO NOTHING""",
                (item["orderId"], json.dumps(item, ensure_ascii=False)),
            )
        conn.commit()


def business_number(conn):
    day = now().date()
    row = conn.execute(
        """INSERT INTO business_sequences(sequence_date,last_value) VALUES(%s,1)
           ON CONFLICT(sequence_date) DO UPDATE SET last_value=business_sequences.last_value+1
           RETURNING last_value""", (day,)
    ).fetchone()
    return f"EXC-{day:%Y%m%d}-{row['last_value']:06d}"


def hours_since(value: datetime | None):
    if not value:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=CN_TZ)
    return (now() - value.astimezone(CN_TZ)).total_seconds() / 3600


def active_rules(conn):
    return {row["rule_code"]: row for row in conn.execute("SELECT * FROM exception_rules WHERE enabled")}


def evaluate_order(order: Order, rules: dict[str, dict[str, Any]]):
    found = []
    def add(code, reason):
        rule = rules[code]
        found.append({"orderId":order.orderId,"exceptionType":code,"severity":rule["severity"],"reason":reason,"suggestion":rule["suggestion"],"idempotencyKey":f"{order.orderId}:{code}"})
    if "SHIPMENT_TIMEOUT" in rules and order.status == "PAID" and not order.shippedAt and hours_since(order.paidAt) > float(rules["SHIPMENT_TIMEOUT"]["threshold"]):
        add("SHIPMENT_TIMEOUT", f"付款后 {int(hours_since(order.paidAt))} 小时仍未发货")
    if "HIGH_RISK_ORDER" in rules and order.riskScore >= int(rules["HIGH_RISK_ORDER"]["threshold"]):
        add("HIGH_RISK_ORDER", f"风控评分 {order.riskScore}，超过阈值 {int(rules['HIGH_RISK_ORDER']['threshold'])}")
    if "INVENTORY_SHORTAGE" in rules and order.quantity > order.stock:
        add("INVENTORY_SHORTAGE", f"购买数量 {order.quantity} 超过可用库存 {order.stock}")
    if "REFUND_TIMEOUT" in rules and order.status == "REFUNDING" and hours_since(order.refundRequestedAt) > float(rules["REFUND_TIMEOUT"]["threshold"]):
        add("REFUND_TIMEOUT", f"退款申请已等待 {int(hours_since(order.refundRequestedAt))} 小时")
    if "DUPLICATE_PAYMENT" in rules and order.duplicatePayment:
        add("DUPLICATE_PAYMENT", "检测到同一订单重复支付标记")
    return found


def exception_upsert_in_transaction(conn, payload: dict, actor="SYSTEM"):
    key = payload.get("idempotencyKey") or f"{payload['orderId']}:{payload['exceptionType']}"
    existing = conn.execute("SELECT * FROM exceptions WHERE idempotency_key=%s FOR UPDATE", (key,)).fetchone()
    if existing:
        reopened = existing["status"] in {"RESOLVED", "REJECTED"}
        item = conn.execute(
            """UPDATE exceptions SET severity=%s,reason=%s,suggestion=%s,last_detected_at=now(),
               status=CASE WHEN %s THEN 'PENDING_REVIEW' ELSE status END,
               reviewer=CASE WHEN %s THEN NULL ELSE reviewer END,
               review_note=CASE WHEN %s THEN NULL ELSE review_note END,
               resolved_at=CASE WHEN %s THEN NULL ELSE resolved_at END,version=version+1
               WHERE id=%s RETURNING *""",
            (payload["severity"],payload["reason"],payload["suggestion"],reopened,reopened,reopened,reopened,existing["id"]),
        ).fetchone()
        is_new = False
    else:
        reopened = False
        number = business_number(conn)
        item = conn.execute(
            """INSERT INTO exceptions(exception_no,idempotency_key,order_id,exception_type,severity,reason,suggestion)
               VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (number,key,payload["orderId"],payload["exceptionType"],payload["severity"],payload["reason"],payload["suggestion"]),
        ).fetchone()
        is_new = True
    conn.execute("INSERT INTO audit_log(event_type,entity_type,entity_id,actor,detail) VALUES('EXCEPTION_UPSERT','EXCEPTION',%s,%s,%s::jsonb)", (item["exception_no"],actor,json.dumps(payload,ensure_ascii=False)))
    enqueue(conn, f"BITABLE:{item['id']}:{item['version']}", "BITABLE_UPSERT", item["id"], {})
    result = serialize(item)
    result["_isNew"] = is_new
    result["_reopened"] = reopened
    result["_shouldNotify"] = is_new or reopened
    return result


def exception_upsert(payload: dict, actor="SYSTEM"):
    with pool.connection() as conn, conn.transaction():
        return exception_upsert_in_transaction(conn, payload, actor)


def enqueue(conn, event_key, event_type, aggregate_id, payload):
    conn.execute(
        """INSERT INTO outbox(event_key,event_type,aggregate_id,payload) VALUES(%s,%s,%s,%s::jsonb)
           ON CONFLICT(event_key) DO NOTHING""",
        (event_key,event_type,aggregate_id,json.dumps(payload,ensure_ascii=False)),
    )


def serialize(row):
    if row is None: return None
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, (datetime,)): result[key] = value.isoformat()
    return result


def feishu_config():
    keys = ("FEISHU_APP_ID","FEISHU_APP_SECRET","FEISHU_BITABLE_APP_TOKEN","FEISHU_BITABLE_TABLE_ID")
    return {key:os.getenv(key,"").strip() for key in keys}


def http_json(method, url, payload=None, headers=None):
    body = None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
    req = urllib.request.Request(url,data=body,headers={"Content-Type":"application/json; charset=utf-8",**(headers or {})},method=method)
    try:
        with urllib.request.urlopen(req,timeout=15) as response: result=json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    if result.get("code",0) != 0: raise RuntimeError(f"Feishu {result.get('code')}: {result.get('msg')}")
    return result


def token():
    if TOKEN_CACHE["value"] and time.time() < TOKEN_CACHE["expires_at"]: return TOKEN_CACHE["value"]
    cfg=feishu_config(); result=http_json("POST",f"{FEISHU_API}/auth/v3/tenant_access_token/internal/",{"app_id":cfg["FEISHU_APP_ID"],"app_secret":cfg["FEISHU_APP_SECRET"]})
    TOKEN_CACHE.update(value=result["tenant_access_token"],expires_at=time.time()+int(result.get("expire",7200))-300)
    return TOKEN_CACHE["value"]


def bitable(method, suffix, payload=None):
    cfg=feishu_config(); base=f"{FEISHU_API}/bitable/v1/apps/{cfg['FEISHU_BITABLE_APP_TOKEN']}/tables/{cfg['FEISHU_BITABLE_TABLE_ID']}"
    return http_json(method,base+suffix,payload,{"Authorization":f"Bearer {token()}"})


FIELDS=[("异常编号",1),("订单编号",1),("异常类型",3),("风险等级",3),("异常原因",1),("处理建议",1),("当前状态",3),("负责人",1),("复核意见",1),("首次发现时间",1),("最后发现时间",1)]


def bootstrap_bitable():
    if not all(feishu_config().values()): return {"configured":False}
    items=bitable("GET","/fields?page_size=100").get("data",{}).get("items",[]); names={x["field_name"] for x in items}; primary=next((x for x in items if x.get("is_primary")),None)
    if primary and primary["field_name"]!="异常编号": bitable("PUT",f"/fields/{primary['field_id']}",{"field_name":"异常编号","type":1})
    created=[]
    for name,typ in FIELDS[1:]:
        if name not in names: bitable("POST","/fields",{"field_name":name,"type":typ}); created.append(name)
    return {"configured":True,"createdFields":created}


def bitable_fields(item):
    return {"异常编号":item["exception_no"],"订单编号":item["order_id"],"异常类型":item["exception_type"],"风险等级":item["severity"],"异常原因":item["reason"],"处理建议":item["suggestion"],"当前状态":item["status"],"负责人":item.get("reviewer") or "待分配","复核意见":item.get("review_note") or "","首次发现时间":item["first_detected_at"].isoformat(),"最后发现时间":item["last_detected_at"].isoformat()}


def find_bitable_record(exception_no):
    page_token=""
    while True:
        suffix="/records?page_size=500" + (f"&page_token={page_token}" if page_token else "")
        data=bitable("GET",suffix).get("data",{})
        for record in data.get("items",[]):
            if record.get("fields",{}).get("异常编号")==exception_no: return record["record_id"]
        if not data.get("has_more"): return None
        page_token=data.get("page_token","")


def deliver(event):
    if event["event_type"]=="FEISHU_TEXT":
        webhook=os.getenv("FEISHU_WEBHOOK_URL","").strip()
        if not webhook: return "SKIPPED"
        http_json("POST",webhook,{"msg_type":"text","content":{"text":event["payload"]["message"]}})
        return "DONE"
    with pool.connection() as conn:
        item=conn.execute("SELECT * FROM exceptions WHERE id=%s",(event["aggregate_id"],)).fetchone()
    if not item: return
    if event["event_type"]=="BITABLE_UPSERT":
        if not all(feishu_config().values()): return "SKIPPED"
        bootstrap_bitable()
        record_id=item["feishu_record_id"] or find_bitable_record(item["exception_no"])
        if record_id:
            bitable("PUT",f"/records/{record_id}",{"fields":bitable_fields(item)})
            if not item["feishu_record_id"]:
                with pool.connection() as conn: conn.execute("UPDATE exceptions SET feishu_record_id=%s WHERE id=%s",(record_id,item["id"])); conn.commit()
        else:
            record_id=bitable("POST","/records",{"fields":bitable_fields(item)})["data"]["record"]["record_id"]
            with pool.connection() as conn: conn.execute("UPDATE exceptions SET feishu_record_id=%s WHERE id=%s",(record_id,item["id"])); conn.commit()
    elif event["event_type"]=="FEISHU_NOTIFY":
        webhook=os.getenv("FEISHU_WEBHOOK_URL","").strip()
        if not webhook: return "SKIPPED"
        text=f"【{item['severity']}】{item['exception_no']}｜订单 {item['order_id']}\n{item['reason']}\n建议：{item['suggestion']}"
        http_json("POST",webhook,{"msg_type":"text","content":{"text":text}})
    return "DONE"


def process_outbox():
    while not STOP_EVENT.wait(1):
        event=None
        with pool.connection() as conn, conn.transaction():
            event=conn.execute("""SELECT * FROM outbox WHERE status IN ('PENDING','RETRY','PROCESSING') AND next_attempt_at<=now()
              ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
            if event: conn.execute("UPDATE outbox SET status='PROCESSING',attempts=attempts+1,next_attempt_at=now()+interval '60 seconds' WHERE id=%s",(event["id"],))
        if not event: continue
        try:
            status=deliver(event)
            with pool.connection() as conn: conn.execute("UPDATE outbox SET status=%s,processed_at=now(),last_error=NULL WHERE id=%s",(status,event["id"])); conn.commit()
        except Exception as exc:
            attempts=event["attempts"]+1; status="DEAD" if attempts>=8 else "RETRY"; delay=min(3600,2**attempts)
            with pool.connection() as conn: conn.execute("UPDATE outbox SET status=%s,next_attempt_at=now()+(%s||' seconds')::interval,last_error=%s WHERE id=%s",(status,delay,str(exc)[:2000],event["id"])); conn.commit()


def verify_signature(body, timestamp, signature):
    secret=os.getenv("INBOUND_WEBHOOK_SECRET","").encode()
    if not secret or not timestamp or not signature: return False
    try:
        if abs(time.time()-int(timestamp))>300: return False
    except ValueError: return False
    expected=hmac.new(secret,timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)


def require_api_key(value: str | None, env_name: str):
    expected=os.getenv(env_name,"")
    if not expected or not value or not hmac.compare_digest(expected,value):
        raise HTTPException(401,f"invalid {env_name.lower()}")


def process_order(order: Order, event_id: str, payload_hash: str, source: str):
    payload=order.model_dump(mode="json")
    results=[]
    with pool.connection() as conn, conn.transaction():
        previous=conn.execute("SELECT payload_hash FROM inbound_events WHERE event_id=%s",(event_id,)).fetchone()
        if previous:
            if previous["payload_hash"]!=payload_hash: raise HTTPException(409,"eventId reused with different payload")
            return {"accepted":True,"duplicate":True,"eventId":event_id}
        conn.execute("INSERT INTO inbound_events(event_id,order_id,payload_hash) VALUES(%s,%s,%s)",(event_id,order.orderId,payload_hash))
        conn.execute("""INSERT INTO orders(order_id,payload,source) VALUES(%s,%s::jsonb,%s)
          ON CONFLICT(order_id) DO UPDATE SET payload=excluded.payload,source=excluded.source,updated_at=now()""",(order.orderId,json.dumps(payload,ensure_ascii=False),source))
        rules=active_rules(conn)
        for finding in evaluate_order(order,rules):
            item=exception_upsert_in_transaction(conn,finding,source)
            if item["_shouldNotify"]:
                enqueue(conn,f"NOTIFY:{item['id']}:{item['version']}","FEISHU_NOTIFY",item["id"],{})
            results.append(item)
    return {"accepted":True,"duplicate":False,"eventId":event_id,"exceptions":results}


@asynccontextmanager
async def lifespan(app):
    pool.open(); init_database()
    if SEED_SAMPLE_DATA: seed_orders()
    STOP_EVENT.clear(); worker=threading.Thread(target=process_outbox,daemon=True); worker.start()
    yield
    STOP_EVENT.set(); worker.join(timeout=3); pool.close()


app=FastAPI(title="Order Exception Automation API",version="2.0.0",lifespan=lifespan)


@app.get("/health")
@app.get("/health/live")
def health(): return {"status":"ok","time":now_iso(),"version":"2.0.0"}


@app.get("/health/ready")
def ready():
    with pool.connection() as conn: conn.execute("SELECT 1")
    return {"status":"ready","database":"postgresql"}


@app.get("/orders")
def orders():
    with pool.connection() as conn: return [row["payload"] for row in conn.execute("SELECT payload FROM orders ORDER BY order_id")]


@app.post("/v1/orders/ingest")
async def ingest(request:Request,x_timestamp:str|None=Header(None),x_signature:str|None=Header(None)):
    body=await request.body()
    if not verify_signature(body,x_timestamp,x_signature): raise HTTPException(401,"invalid or expired signature")
    order=Order.model_validate_json(body); payload_hash=hashlib.sha256(body).hexdigest(); event_id=order.eventId or f"{order.orderId}:{payload_hash}"
    return process_order(order,event_id,payload_hash,"SIGNED_WEBHOOK")


@app.post("/internal/orders/ingest")
def internal_ingest(order:Order,x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    payload=order.model_dump(mode="json"); body=json.dumps(payload,sort_keys=True,separators=(",", ":")).encode(); payload_hash=hashlib.sha256(body).hexdigest()
    event_id=order.eventId or f"{order.orderId}:{payload_hash}"
    return process_order(order,event_id,payload_hash,"N8N_INTERNAL")


@app.post("/exceptions/upsert")
def upsert(payload:dict,x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    return exception_upsert(payload,"N8N_LEGACY")


@app.post("/notifications")
def notify(payload:dict,x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    if payload.get("_shouldNotify", payload.get("_isNew")):
        with pool.connection() as conn:
            enqueue(conn,f"NOTIFY:{payload['id']}:{payload.get('version', 1)}","FEISHU_NOTIFY",payload["id"],{});conn.commit()
        return {"channel":"feishu","accepted":True,"queued":True,"sent":False}
    return {"channel":"suppressed","accepted":True,"queued":False,"sent":False}


@app.get("/exceptions")
def list_exceptions():
    with pool.connection() as conn: return [serialize(x) for x in conn.execute("SELECT * FROM exceptions ORDER BY first_detected_at,id")]


@app.get("/exceptions/{exception_id}")
def get_exception(exception_id:int):
    with pool.connection() as conn: item=conn.execute("SELECT * FROM exceptions WHERE id=%s",(exception_id,)).fetchone()
    if not item: raise HTTPException(404,"exception not found")
    return serialize(item)


@app.post("/exceptions/{exception_id}/review")
def review(exception_id:int,review:Review,x_api_key:str|None=Header(None,alias="X-API-Key")):
    require_api_key(x_api_key,"REVIEW_API_KEY")
    if review.status not in {"APPROVED","REJECTED","RESOLVED"}: raise HTTPException(400,"invalid status")
    with pool.connection() as conn, conn.transaction():
        item=conn.execute("""UPDATE exceptions SET status=%s,reviewer=%s,review_note=%s,resolved_at=CASE WHEN %s='RESOLVED' THEN now() ELSE resolved_at END,version=version+1
          WHERE id=%s RETURNING *""",(review.status,review.reviewer,review.note,review.status,exception_id)).fetchone()
        if not item: raise HTTPException(404,"exception not found")
        conn.execute("INSERT INTO audit_log(event_type,entity_type,entity_id,actor,detail) VALUES('MANUAL_REVIEW','EXCEPTION',%s,%s,%s::jsonb)",(item["exception_no"],review.reviewer,review.model_dump_json()))
        enqueue(conn,f"BITABLE:{item['id']}:{item['version']}","BITABLE_UPSERT",item["id"],{})
    result=serialize(item); result["_feishu"]={"queued":True,"synced":False,"recordId":item["feishu_record_id"]}; return result


@app.post("/feishu/bootstrap")
def bootstrap(x_api_key:str|None=Header(None,alias="X-API-Key")):
    require_api_key(x_api_key,"ADMIN_API_KEY")
    return bootstrap_bitable()


@app.get("/feishu/status")
def feishu_status():
    cfg=feishu_config(); return {"webhookConfigured":bool(os.getenv("FEISHU_WEBHOOK_URL","")),"bitableConfigured":all(cfg.values())}


@app.get("/rules")
def list_rules():
    with pool.connection() as conn: return [serialize(x) for x in conn.execute("SELECT * FROM exception_rules ORDER BY rule_code")]


@app.put("/rules/{rule_code}")
def update_rule(rule_code:str,payload:RuleUpdate,x_api_key:str|None=Header(None,alias="X-API-Key")):
    require_api_key(x_api_key,"ADMIN_API_KEY")
    values=payload.model_dump(exclude_unset=True,exclude_none=True)
    if not values: raise HTTPException(400,"no supported rule fields")
    clauses=[]; params=[]
    for key,value in values.items(): clauses.append(f"{key}=%s"); params.append(value)
    params.append(rule_code)
    with pool.connection() as conn:
        item=conn.execute(f"UPDATE exception_rules SET {','.join(clauses)},updated_at=now() WHERE rule_code=%s RETURNING *",params).fetchone()
        if not item: raise HTTPException(404,"rule not found")
        conn.execute("INSERT INTO audit_log(event_type,entity_type,entity_id,actor,detail) VALUES('RULE_UPDATED','RULE',%s,'ADMIN_API',%s::jsonb)",(rule_code,json.dumps(values,ensure_ascii=False))); conn.commit()
    return serialize(item)


@app.get("/stats")
def stats():
    with pool.connection() as conn:
        return {"totalExceptions":conn.execute("SELECT count(*) count FROM exceptions").fetchone()["count"],"pendingReview":conn.execute("SELECT count(*) count FROM exceptions WHERE status='PENDING_REVIEW'").fetchone()["count"],"outbox":list(conn.execute("SELECT status,count(*) count FROM outbox GROUP BY status ORDER BY status"))}


@app.get("/events")
def events():
    with pool.connection() as conn: return [serialize(x) for x in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100")]


@app.post("/internal/scan-runs")
def save_scan_run(payload:dict,x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    run_id=str(payload.get("runId") or f"scan-{int(time.time())}")[:100]
    with pool.connection() as conn:
        conn.execute("INSERT INTO audit_log(event_type,entity_type,entity_id,actor,detail) VALUES('SCAN_COMPLETED','SCAN_RUN',%s,'N8N',%s::jsonb)",(run_id,json.dumps(payload,ensure_ascii=False))); conn.commit()
    return {"saved":True,"runId":run_id,**payload}


@app.get("/internal/reports/daily")
def daily_report(x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    with pool.connection() as conn:
        total=conn.execute("SELECT count(*) count FROM exceptions WHERE first_detected_at::date=CURRENT_DATE").fetchone()["count"]
        pending=conn.execute("SELECT count(*) count FROM exceptions WHERE status='PENDING_REVIEW'").fetchone()["count"]
        severity={row["severity"]:row["count"] for row in conn.execute("SELECT severity,count(*) count FROM exceptions WHERE first_detected_at::date=CURRENT_DATE GROUP BY severity")}
        types={row["exception_type"]:row["count"] for row in conn.execute("SELECT exception_type,count(*) count FROM exceptions WHERE first_detected_at::date=CURRENT_DATE GROUP BY exception_type ORDER BY count(*) DESC")}
        resolved=conn.execute("SELECT count(*) count FROM exceptions WHERE resolved_at::date=CURRENT_DATE").fetchone()["count"]
    return {"date":f"{now():%Y-%m-%d}","newExceptions":total,"pendingReview":pending,"resolvedToday":resolved,"bySeverity":severity,"byType":types}


@app.get("/internal/outbox/dead")
def dead_outbox(x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    with pool.connection() as conn: items=[serialize(x) for x in conn.execute("SELECT * FROM outbox WHERE status='DEAD' ORDER BY id LIMIT 100")]
    return {"count":len(items),"items":items}


@app.post("/internal/notifications/text")
def operational_notification(payload:OperationalNotification,x_internal_key:str|None=Header(None,alias="X-Internal-Key")):
    require_api_key(x_internal_key,"INTERNAL_API_KEY")
    enabled = os.getenv("ENABLE_DAILY_REPORTS","false").lower() in {"1","true","yes"} if payload.category=="DAILY_REPORT" else os.getenv("ENABLE_DEAD_LETTER_ALERTS","false").lower() in {"1","true","yes"}
    if not enabled: return {"accepted":True,"queued":False,"reason":f"{payload.category} disabled"}
    with pool.connection() as conn:
        enqueue(conn,f"OPS:{payload.category}:{payload.eventId}","FEISHU_TEXT",0,{"message":payload.message,"category":payload.category}); conn.commit()
    return {"accepted":True,"queued":True,"eventId":payload.eventId}


@app.post("/outbox/{event_id}/retry")
def retry_outbox(event_id:int,x_api_key:str|None=Header(None,alias="X-API-Key")):
    require_api_key(x_api_key,"ADMIN_API_KEY")
    with pool.connection() as conn:
        item=conn.execute("UPDATE outbox SET status='RETRY',next_attempt_at=now(),last_error=NULL WHERE id=%s AND status IN ('DEAD','SKIPPED') RETURNING *",(event_id,)).fetchone()
        if not item: raise HTTPException(404,"dead or skipped outbox event not found")
        conn.commit()
    return serialize(item)
