# -*- coding: utf-8 -*-
"""独立上传示例。真实插件内已集成上传逻辑，本文件仅用于测试中心服务。"""
from __future__ import annotations

import json
import time
import urllib.request


def upload_prices(upload_url: str, api_key: str, prices: dict, source: str = "manual") -> str:
    payload = {
        "schema_version": 1,
        "source": source,
        "updated_at": time.time(),
        "unit": "万",
        "items": {
            str(name): {"price": float(price), "unit": "万", "source": source, "updated_at": time.time()}
            for name, price in prices.items()
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read().decode("utf-8", errors="replace")


if __name__ == "__main__":
    print(upload_prices(
        upload_url="http://127.0.0.1:8808/api/prices/bulk",
        api_key="改成你的上传密钥",
        prices={"五指拳心剑": 888888, "真龙九变": 1200000},
        source="uploader_example",
    ))
