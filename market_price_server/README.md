# 坊市价格中心服务示例

用于接收 `astrbot_plugin_xiuxian` 上传的坊市价格，并向其他用户公开读取。

```bash
pip install fastapi uvicorn
export MARKET_WRITE_TOKEN="改成强密钥"
uvicorn server:app --host 0.0.0.0 --port 8808
```

公开读取：`GET /api/prices/latest`

上传价格：`POST /api/prices/bulk`，请求头必须带 `X-API-Key: MARKET_WRITE_TOKEN`。
