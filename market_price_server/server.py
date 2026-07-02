# -*- coding: utf-8 -*-
"""坊市价格中心服务示例。

运行：
    pip install fastapi uvicorn
    export MARKET_WRITE_TOKEN="改成强密钥"
    uvicorn server:app --host 0.0.0.0 --port 8808

接口：
    GET  /api/prices/latest  公开读取最新价格
    POST /api/prices/bulk    上传/合并价格，需要 Header: X-API-Key
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = Path(os.environ.get("MARKET_DATA_PATH", APP_DIR / "market_prices.json"))
WRITE_TOKEN = os.environ.get("MARKET_WRITE_TOKEN", "change-me")

app = FastAPI(title="Xiao Xiuxian Market Price Center", version="1.0.0")


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "")).strip()


def load_data() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        return {"schema_version": 1, "updated_at": 0, "items": {}}
    try:
        with DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"schema_version": 1, "updated_at": 0, "items": {}}
        if not isinstance(data.get("items"), dict):
            data["items"] = {}
        return data
    except Exception:
        return {"schema_version": 1, "updated_at": 0, "items": {}}


def atomic_save(data: Dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".market_prices.", suffix=".tmp", dir=str(DATA_PATH.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, DATA_PATH)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def parse_price(raw: Any) -> float:
    if isinstance(raw, dict):
        raw = raw.get("price", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


@app.get("/api/prices/latest")
def latest_prices() -> Dict[str, Any]:
    return load_data()


@app.post("/api/prices/bulk")
def upload_prices(payload: Dict[str, Any], x_api_key: str = Header(default="")) -> Dict[str, Any]:
    if not WRITE_TOKEN or WRITE_TOKEN == "change-me":
        raise HTTPException(status_code=500, detail="server write token is not configured")
    if x_api_key != WRITE_TOKEN:
        raise HTTPException(status_code=401, detail="invalid api key")

    incoming = payload.get("items", {})
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="items must be an object")

    now_ts = time.time()
    source = str(payload.get("source") or payload.get("plugin") or "unknown")
    data = load_data()
    items = data.setdefault("items", {})

    accepted = 0
    for raw_name, raw_info in incoming.items():
        name = normalize_name(raw_name)
        if not name:
            continue
        price = parse_price(raw_info)
        if price <= 0:
            continue

        if isinstance(raw_info, dict):
            category = raw_info.get("category", "")
            unit = raw_info.get("unit", payload.get("unit", "万"))
            updated_at = float(raw_info.get("updated_at", now_ts) or now_ts)
            last_seen_at = raw_info.get("last_seen_at", "")
        else:
            category = ""
            unit = payload.get("unit", "万")
            updated_at = now_ts
            last_seen_at = ""

        old = items.get(name, {}) if isinstance(items.get(name), dict) else {}
        old_updated = float(old.get("updated_at", 0) or 0)
        # 新数据比旧数据更旧时，不覆盖。
        if old_updated and updated_at < old_updated:
            continue

        items[name] = {
            "price": price,
            "unit": unit,
            "category": category,
            "source": source,
            "updated_at": updated_at,
            "last_seen_at": last_seen_at,
        }
        accepted += 1

    data["schema_version"] = 1
    data["updated_at"] = now_ts
    data["count"] = len(items)
    atomic_save(data)
    return {"ok": True, "accepted": accepted, "total": len(items), "updated_at": now_ts}
