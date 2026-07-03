"""修仙辅助与坊市监控大一统插件 (AstrBot Plugin)

功能模块：
- 悬赏令：解析、收益计算、倒计时提醒、私聊通知
- 秘境探索：自动识别并设置倒计时提醒
- 灵田收取：自动识别收获确认并设置 47 小时后提醒
- 猜成语：基于 DeepSeek API 的智能成语回答
- 炼金/上架：背包物品估价、一键生成上架/炼金指令
- 坊市爬虫：定时自动采集坊市价格并落盘
- 坊市监控：定时探测稀有物品出现并广播通知
- 坊市价格网络共享：本地导出 + 远程上传价格数据
- 黑名单：QQ 级别的屏蔽与数据清理
"""

import os
import json
import re
import time
import asyncio
import uuid
import tempfile
import copy
import datetime
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.core.message.components import Plain, At
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

logger = logging.getLogger("astrbot")

__plugin_name__ = "astrbot_plugin_xiuxian"
__plugin_version__ = "3.2.6"
__plugin_author__ = "时光"
__plugin_desc__ = "修仙辅助与坊市监控大一统插件"


DEFAULT_CONFIG = {
    "admin_qq": "1060359551",
    "official_bot_qq": "3889001741",
    "test_mode": False,
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "timeout": 8.0,
    },
    "modules": {
        "xiuxian": True,
        "alchemy": True,
        "market_spider": True,
        "market_monitor": True
    },
    "target_group": "",
    "spider_settings": {"enable_schedule": True, "delay_seconds": 4},
    "network_market": {
        "enabled": False,
        "upload_url": "https://你的域名.example.com/api/prices/bulk",
        "api_key": "",
        "timeout_sec": 8.0,
        "min_interval_sec": 300,
        "upload_after_full_scrape": True,
        "upload_monitor_items": False,
        "local_export_enabled": True,
        "local_export_path": "data/xiao_xiuxian_market_prices.json",
        "source": "astrbot_plugin_xiuxian"
    },
    "alchemy_target_items": [
        "回元丹", "生骨丹", "化瘀丹", "培元丹", "固元丹",
        "回春丹", "养元丹", "太元真丹", "九阳真丹",
        "归臧灵丹", "归藏灵丹", "天命血凝丹"
    ],
    "alchemy_prices": {
        "生骨丹": 30, "化瘀丹": 30, "培元丹": 90, "固元丹": 120,
        "回春丹": 210, "养元丹": 240, "太元真丹": 270, "九阳真丹": 300,
        "归藏灵丹": 330, "归臧灵丹": 330, "天命血凝丹": 360,
        "化劫丹": 260, "太上玄门丹": 290, "幻心玄丹": 240, "鬼面炼心丹": 270,
        "少阴清灵丹": 300, "天命炼心丹": 330, "斩我丹": 360, "苦茶子": 390,
        "渡厄丹": 80, "养气丹": 150, "九转丹": 180, "摄魂鬼丸": 120,
        "素心真丸": 180, "静禅魔丸": 240, "地仙玄丸": 270, "消冰宝丸": 300,
        "化煞魔丸": 150, "灭神古丸": 210, "无涯鬼丸": 330, "太一仙丸": 360
    },
    "monitor_enabled": False,
    "monitor_trigger_group": "942102660",
    "monitor_notify_groups": ["942102660", "709886837"],
    "monitor_items": ["太虚乾元诀", "真龙九变"],
    "monitor_cmds": ["坊市查看技能3"],
    "group_reminder_enabled": {},
    "blacklist_qq": []
}

HIGH_VALUE_ITEMS = ["五指拳心剑", "真龙九变", "坐忘论", "无瑕七绝剑"]
PM_KEY_MAP = {"悬赏": "bounty", "秘境": "mijing", "灵田": "harvest"}
BOUNTY_NUM_MAP = {"壹": "1", "贰": "2", "叁": "3", "1": "1", "2": "2", "3": "3"}

MARKET_CATEGORIES = ['技能', '丹药', '装备', '药材', '道具']
MARKET_TARGET_HOURS = [3, 9, 15, 21]
HISTORY_LIMIT = 20

INVISIBLE_CHAR_PATTERN = re.compile(r'[\u200b-\u200f\u2028-\u202f\u205f-\u206f\ufeff]')
BAG_ITEM_PATTERN = re.compile(r'([^\n]+)\n[^\n]*?拥有数量[::]?\s*(\d+)')
BRACKET_NAME_PATTERN = re.compile(r'\[([^\]]+)\]')
PRICE_PATTERN = re.compile(r'价格:(\d+(?:\.\d+)?)(万|亿)\s*\[?([^\]\n\(]+)')
PILL_REWARD_PATTERN = re.compile(r'成功领取到丹药[：:]\s*([^\s\d!！]+?)\s*(\d+)\s*枚')
HERB_REWARD_PATTERN = re.compile(r'(?:收获药材|成功收获药材)[：:]\s*([^\s\d!！]+?)\s*(\d+)\s*个')


@register("astrbot_plugin_xiuxian", "时光", "修仙辅助与坊市监控大一统插件", "3.2.6")
class XiuxianAllInOnePlugin(Star):

    MODULE_ALIASES = {
        "修仙": "xiuxian", "xiuxian": "xiuxian",
        "炼金": "alchemy", "上架": "alchemy", "alchemy": "alchemy",
        "爬虫": "market_spider", "坊市爬虫": "market_spider", "market_spider": "market_spider",
        "监控": "market_monitor", "坊市监控": "market_monitor", "market_monitor": "market_monitor",
    }

    def __init__(self, context: Context):
        super().__init__(context)
        self.plugin_dir = Path(__file__).resolve().parent
        self.config_path = self.plugin_dir / "config.json"
        self.data_path = self.plugin_dir / "pm_prefs.json"
        self.tasks_path = self.plugin_dir / "tasks.json"
        self.market_path = self.plugin_dir / "market_data.json"

        self.config = self._load_config()
        self.admin_qq = str(self.config.get("admin_qq"))
        self.official_bot_qq = str(self.config.get("official_bot_qq"))

        deepseek_config = self.config.get("deepseek", {})
        self.deepseek_model = str(deepseek_config.get("model"))
        try:
            self.deepseek_timeout = max(1.0, float(deepseek_config.get("timeout", 8)))
        except (TypeError, ValueError):
            self.deepseek_timeout = 8.0

        self.pending_accepts: Dict[str, List[Dict[str, Any]]] = {}
        self.menu_cache: Dict[str, Dict[str, Any]] = {}
        self.pending_harvests: Dict[str, List[Dict[str, Any]]] = {}
        self.market_query_hints: Dict[str, Dict[str, Any]] = {}
        self.pm_prefs = self._load_prefs()
        self.active_tasks: Dict[str, Dict[str, Any]] = self._load_tasks()

        self.task_key_index: Dict[str, str] = {}
        self.task_runners: Dict[str, Any] = {}
        self._task_storage_dirty = self._rebuild_task_index()

        self.market_data = self._load_market_data()
        self.is_scraping = False
        self.current_category_idx = 0
        self.current_page = 1
        self.current_scrape_time = ''
        self.retry_count = 0
        self.timeout_task = None
        self.client = None
        self.target_group = str(self.config.get('target_group', ''))

        self.last_market_upload_ts: float = 0.0
        self.last_market_upload_ok: bool = False
        self.last_market_upload_msg: str = "尚未上传"
        self.last_market_upload_count: int = 0

        self.tasks_recovered = False
        self.recover_lock = asyncio.Lock()
        self.task_lock = asyncio.Lock()
        self.pref_lock = asyncio.Lock()
        self.file_lock = asyncio.Lock()
        self.send_semaphore = asyncio.Semaphore(5)

        deepseek_api_key = str(deepseek_config.get("api_key"))
        if deepseek_api_key:
            self.client_ai = AsyncOpenAI(
                api_key=deepseek_api_key,
                base_url=str(deepseek_config.get("base_url")),
            )
        else:
            self.client_ai = None

        self.bg_task = asyncio.create_task(self._market_schedule_loop())
        self.monitor_task = asyncio.create_task(self._market_monitor_loop())


    def _load_json(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """安全加载 JSON 文件，失败时返回默认值。"""
        if not path.exists():
            return copy.deepcopy(default)
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else copy.deepcopy(default)
        except Exception as e:
            logger.warning("[大一统] JSON 加载失败 %s: %s", path, e)
            return copy.deepcopy(default)

    def _save_json_atomic(self, path: Path, data: Dict[str, Any]) -> None:
        """原子写入 JSON 文件（先写临时文件再 rename，防止写入中断导致数据损坏）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception as e:
            logger.error("[大一统] JSON 写入失败 %s: %s", path, e)
            try: os.unlink(tmp_name)
            except OSError: pass
            raise

    async def _save_json_atomic_async(self, path: Path, data: Dict[str, Any]) -> None:
        async with self.file_lock:
            await asyncio.to_thread(self._save_json_atomic, path, data)

    def _load_config(self) -> Dict[str, Any]:
        config = self._load_json(self.config_path, DEFAULT_CONFIG)
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value

        if not isinstance(config.get("deepseek"), dict):
            config["deepseek"] = copy.deepcopy(DEFAULT_CONFIG["deepseek"])

        spider_settings = dict(DEFAULT_CONFIG['spider_settings'])
        spider_settings.update(config.get('spider_settings', {}))
        config['spider_settings'] = spider_settings

        network_market = dict(DEFAULT_CONFIG['network_market'])
        user_network_market = config.get('network_market', {})
        if isinstance(user_network_market, dict):
            network_market.update(user_network_market)
        config['network_market'] = network_market

        if not isinstance(config.get('alchemy_target_items'), list):
            config['alchemy_target_items'] = copy.deepcopy(DEFAULT_CONFIG['alchemy_target_items'])

        default_prices = DEFAULT_CONFIG['alchemy_prices']
        user_prices = config.get('alchemy_prices', {})
        if isinstance(user_prices, dict):
            merged_prices = dict(default_prices)
            merged_prices.update(user_prices)
            config['alchemy_prices'] = merged_prices
        else:
            config['alchemy_prices'] = copy.deepcopy(default_prices)

        if "monitor_cmd" in config and isinstance(config.get("monitor_cmd"), str):
            if "monitor_cmds" not in config:
                config["monitor_cmds"] = [config["monitor_cmd"]]
            del config["monitor_cmd"]

        for k in ['monitor_notify_groups', 'monitor_items', 'monitor_cmds']:
            if not isinstance(config.get(k), list):
                config[k] = copy.deepcopy(DEFAULT_CONFIG[k])

        if not isinstance(config.get('group_reminder_enabled'), dict):
            config['group_reminder_enabled'] = {}

        if not isinstance(config.get('blacklist_qq'), list):
            config['blacklist_qq'] = []
        config['blacklist_qq'] = list(dict.fromkeys(str(x).strip() for x in config.get('blacklist_qq', []) if str(x).strip()))

        default_modules = DEFAULT_CONFIG["modules"]
        user_modules = config.get("modules", {})
        if not isinstance(user_modules, dict):
            user_modules = {}
        merged_modules = dict(default_modules)
        merged_modules.update(user_modules)
        config["modules"] = merged_modules

        if not self.config_path.exists():
            self._save_json_atomic(self.config_path, config)
        return config

    async def _save_config_async(self) -> None:
        await self._save_json_atomic_async(self.config_path, self.config)

    def _load_tasks(self) -> Dict[str, Dict[str, Any]]:
        return self._load_json(self.tasks_path, {})

    async def _save_tasks_async_locked(self) -> None:
        await self._save_json_atomic_async(self.tasks_path, copy.deepcopy(self.active_tasks))

    def _load_prefs(self) -> Dict[str, List[str]]:
        default = {"bounty": [], "mijing": [], "harvest": []}
        data = self._load_json(self.data_path, default)
        for key in default:
            value = data.get(key)
            data[key] = value if isinstance(value, list) else []
        return data

    async def _save_prefs_async_locked(self) -> None:
        await self._save_json_atomic_async(self.data_path, copy.deepcopy(self.pm_prefs))

    def _load_market_data(self) -> Dict[str, Dict[str, Any]]:
        default = {cat: {} for cat in MARKET_CATEGORIES}
        loaded = self._load_json(self.market_path, default)
        for cat in MARKET_CATEGORIES:
            loaded.setdefault(cat, {})
        return loaded

    async def _save_market_data_async(self) -> None:
        await self._save_json_atomic_async(self.market_path, self.market_data)

    def _network_market_cfg(self) -> Dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG.get("network_market", {}))
        user_cfg = self.config.get("network_market", {})
        if isinstance(user_cfg, dict):
            cfg.update(user_cfg)
        return cfg

    def _resolve_plugin_path(self, raw_path: str) -> Path:
        path = Path(str(raw_path or "").strip())
        if path.is_absolute():
            return path
        return (self.plugin_dir / path).resolve()

    @staticmethod
    def _normalize_market_item_name(name: str) -> str:
        text = str(name or "")
        text = INVISIBLE_CHAR_PATTERN.sub("", text)
        text = re.sub(r"\s+", "", text)
        return text.strip()

    def _flatten_market_prices(self, categories: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        cfg = self._network_market_cfg()
        source = str(cfg.get("source") or "astrbot_plugin_xiuxian")
        now_ts = time.time()
        allow_categories = set(categories or MARKET_CATEGORIES)
        items: Dict[str, Dict[str, Any]] = {}

        for cat in MARKET_CATEGORIES:
            if cat not in allow_categories:
                continue
            cat_data = self.market_data.get(cat, {})
            if not isinstance(cat_data, dict):
                continue

            for raw_name, raw_node in cat_data.items():
                name = self._normalize_market_item_name(raw_name)
                if not name:
                    continue

                latest_price = 0.0
                last_seen_at = self.current_scrape_time or ""
                history: Dict[str, Any] = {}

                if isinstance(raw_node, dict):
                    try:
                        latest_price = float(raw_node.get("latest_price", 0) or 0)
                    except (TypeError, ValueError):
                        latest_price = 0.0
                    if isinstance(raw_node.get("history"), dict):
                        history = raw_node.get("history") or {}
                        if history:
                            try:
                                last_seen_at = sorted(history.keys())[-1]
                            except Exception:
                                pass
                else:
                    try:
                        latest_price = float(raw_node or 0)
                    except (TypeError, ValueError):
                        latest_price = 0.0

                if latest_price <= 0:
                    continue

                old = items.get(name)
                if old and float(old.get("price", 0) or 0) >= latest_price:
                    continue

                items[name] = {
                    "price": latest_price,
                    "unit": "万",
                    "category": cat,
                    "source": source,
                    "updated_at": now_ts,
                    "last_seen_at": last_seen_at,
                }

        return items

    def _build_network_market_payload(self) -> Dict[str, Any]:
        cfg = self._network_market_cfg()
        items = self._flatten_market_prices()
        now_ts = time.time()
        return {
            "schema_version": 1,
            "source": str(cfg.get("source") or "astrbot_plugin_xiuxian"),
            "plugin": __plugin_name__,
            "plugin_version": __plugin_version__,
            "updated_at": now_ts,
            "unit": "万",
            "items": items,
        }

    async def _export_market_prices_local(self, payload: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        cfg = self._network_market_cfg()
        if not bool(cfg.get("local_export_enabled", True)):
            return None
        export_path = self._resolve_plugin_path(str(cfg.get("local_export_path") or "data/xiao_xiuxian_market_prices.json"))
        data = payload if payload is not None else self._build_network_market_payload()
        await self._save_json_atomic_async(export_path, data)
        return export_path

    def _post_json_sync(self, url: str, payload: Dict[str, Any], api_key: str, timeout: float) -> Tuple[bool, str]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"{__plugin_name__}/{__plugin_version__}",
        }
        if api_key:
            headers["X-API-Key"] = api_key

        req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, float(timeout))) as resp:
                status = int(getattr(resp, "status", 0) or 0)
                raw = resp.read(4096).decode("utf-8", errors="replace")
            if 200 <= status < 300:
                return True, raw or f"HTTP {status}"
            return False, f"HTTP {status}: {raw}"
        except urllib.error.HTTPError as e:
            try:
                raw = e.read(4096).decode("utf-8", errors="replace")
            except Exception:
                raw = str(e)
            return False, f"HTTP {e.code}: {raw}"
        except Exception as e:
            return False, str(e)

    async def _upload_market_prices_network(self, force: bool = False) -> Tuple[bool, str, int]:
        cfg = self._network_market_cfg()
        payload = self._build_network_market_payload()
        count = len(payload.get("items", {}) or {})

        try:
            await self._export_market_prices_local(payload)
        except Exception as e:
            logger.warning("[大一统] 本地导出坊市价格失败:%s", e)

        if not bool(cfg.get("enabled", False)):
            self.last_market_upload_ts = time.time()
            self.last_market_upload_ok = False
            self.last_market_upload_msg = "网络上传未启用，仅已尝试本地导出"
            self.last_market_upload_count = count
            return False, self.last_market_upload_msg, count

        upload_url = str(cfg.get("upload_url") or "").strip()
        if not upload_url or "你的域名" in upload_url:
            self.last_market_upload_ts = time.time()
            self.last_market_upload_ok = False
            self.last_market_upload_msg = "未配置有效 upload_url"
            self.last_market_upload_count = count
            return False, self.last_market_upload_msg, count

        if count <= 0:
            self.last_market_upload_ts = time.time()
            self.last_market_upload_ok = False
            self.last_market_upload_msg = "没有可上传的坊市价格"
            self.last_market_upload_count = 0
            return False, self.last_market_upload_msg, 0

        min_interval = max(0, int(float(cfg.get("min_interval_sec", 300) or 0)))
        now = time.time()
        if not force and self.last_market_upload_ts > 0 and now - self.last_market_upload_ts < min_interval:
            remain = int(min_interval - (now - self.last_market_upload_ts))
            msg = f"距离上次上传过近，{remain}秒后再上传"
            return self.last_market_upload_ok, msg, count

        api_key = str(cfg.get("api_key") or "").strip()
        timeout = float(cfg.get("timeout_sec", 8.0) or 8.0)
        ok, msg = await asyncio.to_thread(self._post_json_sync, upload_url, payload, api_key, timeout)

        self.last_market_upload_ts = time.time()
        self.last_market_upload_ok = ok
        self.last_market_upload_msg = msg[:300]
        self.last_market_upload_count = count

        if ok:
            logger.info("[大一统] 坊市价格已上传:%s 条", count)
        else:
            logger.warning("[大一统] 坊市价格上传失败:%s", msg)
        return ok, self.last_market_upload_msg, count

    async def _upload_market_prices_background(self, reason: str = "") -> None:
        try:
            ok, msg, count = await self._upload_market_prices_network(force=False)
            logger.info("[大一统] 坊市价格后台上传结果:ok=%s count=%s reason=%s msg=%s", ok, count, reason, msg)
        except Exception as e:
            logger.exception("[大一统] 坊市价格后台上传异常:%s", e)

    def _format_upload_ts(self, ts: float) -> str:
        if not ts:
            return "尚未上传"
        tz_bj = datetime.timezone(datetime.timedelta(hours=8))
        dt = datetime.datetime.fromtimestamp(float(ts), tz_bj)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


    def _is_admin(self, event: AstrMessageEvent) -> bool:
        return str(event.get_sender_id()) == self.admin_qq

    def _is_official_bot(self, event: AstrMessageEvent) -> bool:
        return str(event.get_sender_id()) == self.official_bot_qq

    def _is_test_admin_source(self, event: AstrMessageEvent) -> bool:
        return bool(self.config.get("test_mode", False)) and self._is_admin(event)

    def _is_test_dry_run(self, event: AstrMessageEvent) -> bool:
        return self._is_test_admin_source(event)

    def _is_official_like_source(self, event: AstrMessageEvent) -> bool:
        return self._is_official_bot(event) or self._is_test_admin_source(event)

    def _is_value_calc_source(self, event: AstrMessageEvent) -> bool:
        return self._is_official_like_source(event)

    def _module_enabled(self, name: str) -> bool:
        return bool(self.config.get("modules", {}).get(name, True))

    def _blacklist_set(self) -> set:
        raw = self.config.get("blacklist_qq", [])
        if not isinstance(raw, list):
            return set()
        return set(str(x).strip() for x in raw if str(x).strip())

    def _is_blacklisted_qq(self, uid: Optional[Any]) -> bool:
        if uid in (None, "", "None"):
            return False
        return str(uid).strip() in self._blacklist_set()

    def _message_to_plain_for_blacklist(self, message: Any) -> str:
        parts = []
        def walk(obj: Any) -> None:
            if obj is None:
                return
            if isinstance(obj, str):
                parts.append(obj)
                return
            if isinstance(obj, (list, tuple)):
                for x in obj:
                    walk(x)
                return
            if isinstance(obj, dict):
                data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                for key in ("text", "qq", "id"):
                    val = data.get(key)
                    if val is not None:
                        parts.append(str(val))
                for key in ("text", "raw_message", "message"):
                    val = obj.get(key)
                    if val is not None and val is not obj:
                        walk(val)
                return
            for attr in ("text", "qq"):
                val = getattr(obj, attr, None)
                if val is not None:
                    parts.append(str(val))
        walk(message)
        return "\n".join(parts)

    def _text_mentions_blacklisted_qq(self, text: str) -> bool:
        msg = str(text or "")
        if not msg:
            return False
        for uid in self._blacklist_set():
            if re.search(rf"(?:qq=|tinyid=|at_tinyid=|QQ[:：]?\s*){re.escape(uid)}(?!\d)", msg):
                return True
            if re.search(rf"(?<!\d){re.escape(uid)}(?!\d)", msg):
                return True
        return False

    def _event_mentions_blacklisted_qq(self, event: AstrMessageEvent, text: Optional[str] = None) -> bool:
        if self._is_blacklisted_qq(event.get_sender_id()):
            return True
        chunks = []
        if text is not None:
            chunks.append(str(text))
        try:
            chunks.append(str(event.message_str or ""))
        except Exception:
            pass
        try:
            msg_obj = getattr(event, "message_obj", None)
            comps = getattr(msg_obj, "message", None) if msg_obj is not None else None
            chunks.append(self._message_to_plain_for_blacklist(comps))
            raw = getattr(msg_obj, "raw_message", None) if msg_obj is not None else None
            chunks.append(self._message_to_plain_for_blacklist(raw))
        except Exception:
            pass
        return self._text_mentions_blacklisted_qq("\n".join(chunks))

    def _blacklist_blocks_event(self, event: AstrMessageEvent, text: Optional[str] = None) -> bool:
        if self._is_blacklisted_qq(event.get_sender_id()):
            return True
        if self._is_official_like_source(event) and self._event_mentions_blacklisted_qq(event, text):
            return True
        return False

    def _outgoing_mentions_blacklisted_qq(self, message: Any) -> bool:
        return self._text_mentions_blacklisted_qq(self._message_to_plain_for_blacklist(message))

    async def _purge_blacklisted_user_data(self, uid: str) -> None:
        uid = str(uid).strip()
        if not uid:
            return
        async with self.pref_lock:
            changed = False
            for key in list(self.pm_prefs.keys()):
                if isinstance(self.pm_prefs.get(key), list) and uid in self.pm_prefs[key]:
                    self.pm_prefs[key] = [x for x in self.pm_prefs[key] if str(x) != uid]
                    changed = True
            if changed:
                await self._save_prefs_async_locked()
        async with self.task_lock:
            remove_ids = [tid for tid, task in self.active_tasks.items() if isinstance(task, dict) and str(task.get("uid", "")) == uid]
            for tid in remove_ids:
                task = self.active_tasks.pop(tid, None)
                if isinstance(task, dict):
                    self.task_key_index.pop(self._task_unique_key(str(task.get("uid", "")), str(task.get("type", "")), task.get("gid")), None)
                runner = self.task_runners.pop(tid, None)
                if runner and not runner.done():
                    runner.cancel()
            if remove_ids:
                await self._save_tasks_async_locked()

    def _group_id_reminder_enabled(self, gid: Optional[str]) -> bool:
        if not gid or str(gid) == "None":
            return True
        group_cfg = self.config.get("group_reminder_enabled", {})
        if not isinstance(group_cfg, dict):
            return True
        return bool(group_cfg.get(str(gid), True))

    def _group_reminder_enabled(self, event: AstrMessageEvent) -> bool:
        return self._group_id_reminder_enabled(event.get_group_id())

    def _extract_message_id(self, result: Optional[Dict[str, Any]]) -> Optional[Any]:
        if not result: return None
        return result.get("message_id") or result.get("msg_id") or result.get("data", {}).get("message_id")

    async def _delay_del(self, client, mid: Any, delay_seconds: int) -> None:
        await asyncio.sleep(delay_seconds)
        try:
            await client.delete_msg(message_id=int(mid))
        except Exception:
            pass

    async def _safe_send_group_msg(self, client, gid: Optional[str], message: Any, recall_delay: int = 0) -> Optional[Dict[str, Any]]:
        if not gid or str(gid) == "None": return None
        if self._outgoing_mentions_blacklisted_qq(message): return None
        try:
            async with self.send_semaphore:
                res = await client.send_group_msg(group_id=int(gid), message=message)
            if recall_delay > 0:
                mid = self._extract_message_id(res)
                if mid: asyncio.create_task(self._delay_del(client, mid, recall_delay))
            return res
        except Exception as e:
            logger.error(f"发送群消息失败: gid={gid} {e}")
            return None

    async def _safe_send_private_msg(self, client, uid: str, message: Any, recall_delay: int = 0) -> Optional[Dict[str, Any]]:
        if self._is_blacklisted_qq(uid): return None
        if self._outgoing_mentions_blacklisted_qq(message): return None
        try:
            async with self.send_semaphore:
                res = await client.send_private_msg(user_id=int(uid), message=message)
            if recall_delay > 0:
                mid = self._extract_message_id(res)
                if mid: asyncio.create_task(self._delay_del(client, mid, recall_delay))
            return res
        except Exception as e:
            logger.error(f"发送私聊失败: uid={uid} {e}")
            return None

    async def _send_quote_reply(self, event: AstrMessageEvent, text: str, recall_delay: int = 30, stop_event: bool = True) -> None:
        if self._is_blacklisted_qq(event.get_sender_id()): return
        client = event.bot
        gid = event.get_group_id()
        uid = event.get_sender_id()
        mid = getattr(event.message_obj, "message_id", None)
        if gid:
            msg_chain = []
            if mid: msg_chain.append({"type": "reply", "data": {"id": str(mid)}})
            msg_chain.append({"type": "text", "data": {"text": text}})
            await self._safe_send_group_msg(client, str(gid), msg_chain, recall_delay=recall_delay)
        else:
            await self._safe_send_private_msg(client, str(uid), text, recall_delay=recall_delay)
        if stop_event:
            event.stop_event()

    async def _send_and_recall_universal(self, event: Optional[AstrMessageEvent], text: str, delay: int = 30) -> None:
        if event is not None and self._is_blacklisted_qq(event.get_sender_id()): return
        if event is None:
            if self.client and self.target_group:
                await self._safe_send_group_msg(self.client, self.target_group, text, recall_delay=delay)
            return
        gid = event.get_group_id()
        if gid:
            await self._safe_send_group_msg(event.bot, str(gid), text, recall_delay=delay)
        else:
            await self._safe_send_private_msg(event.bot, str(event.get_sender_id()), text, recall_delay=delay)

    def _stop_event(self, event: AstrMessageEvent) -> None:
        event.set_result('')
        event.stop_event()

    @filter.regex(r"(?s).*")
    async def cache_runtime_client(self, event: AstrMessageEvent):
        bot = getattr(event, "bot", None)
        if bot is not None:
            self.client = bot


    def _clean_message(self, message: str) -> str:
        return INVISIBLE_CHAR_PATTERN.sub('', message)

    def _get_pure_plain_text(self, event: AstrMessageEvent) -> str:
        """【翻倍Bug修复】仅提取消息链中的 Plain 组件文本，剔除 Reply 引用文本以避免数量翻倍。"""
        pure_text = ""
        try:
            msg_obj = getattr(event, "message_obj", None)
            comps = getattr(msg_obj, "message", None) if msg_obj is not None else None
            if comps:
                for comp in comps:
                    if isinstance(comp, Plain):
                        pure_text += comp.text or ""
        except Exception:
            pure_text = ""
        if not pure_text:
            pure_text = event.message_str or ""
        return self._clean_message(pure_text)


    def _get_price_by_tier(self, tier_str: str, item_name: str) -> float:
        for special_item in HIGH_VALUE_ITEMS:
            if special_item in item_name: return 9999.0
        if "吞天魔功" in item_name: return 440.0
        if "天罪" in item_name: return 650.0

        herbs = {"一品": 50.0, "二品": 110.0, "三品": 140.0, "四品": 170.0, "五品": 200.0,
                 "六品": 230.0, "七品": 260.0, "八品": 290.0, "九品": 320.0}
        for k, v in herbs.items():
            if k in tier_str: return v

        tiers = {"人阶下品": 50.0, "人阶上品": 100.0, "黄阶下品": 130.0, "黄阶上品": 160.0,
                 "玄阶下品": 190.0, "玄阶上品": 220.0, "地阶下品": 250.0, "地阶上品": 280.0,
                 "天阶下品": 310.0, "天阶上品": 340.0, "仙阶下品": 340.0, "仙阶上品": 380.0,
                 "仙阶极品": 400.0, "无上功法": 650.0, "无上仙器": 470.0}
        for k, v in tiers.items():
            if k in tier_str or k in item_name: return v

        if "无上" in tier_str:
            return 470.0 if ("器" in tier_str or "法宝" in tier_str) else 650.0
        return 0.0

    def _parse_time(self, text: str, default_value: int = 60, default_unit: str = "分钟") -> Tuple[int, str]:
        match = re.search(r"(\d+)\s*(分钟|分|小时|时|秒)", text)
        if not match: return default_value, default_unit
        return int(match.group(1)), match.group(2)

    def _format_exp(self, exp: int) -> str:
        if exp >= 100000000: return f"{exp / 100000000:.2f}亿"
        return f"{exp / 10000:.2f}万"

    def _parse_new_bounties(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        新版悬赏解析。
        - 修为：保持原翻倍/成功率逻辑不变。
        - 坊市价值：通过 _find_fuzzy_item_price 查询 market_data.json。
        - 炼金价值：沿用旧版 _get_price_by_tier 按品级硬编码规则。
        - 耗时：兼容“预计需10分钟”位于“基础报酬xxx修为”之后的新版回执。
        """
        parsed = {}
        pattern = r"(\d+)、(.*?),完成几率(\d+)(.*?)基础报酬(\d+)修为(.*?)可能额外获得：(.*?):([^!！\n]+)"
        for match in re.finditer(pattern, raw_text):
            bounty_id = int(match.group(1))
            prob = int(match.group(3))
            mid_text = f"{match.group(4)}{match.group(6)}"
            base_exp = int(match.group(5))
            tier = match.group(7).strip()
            name = match.group(8).strip()
            time_val, time_unit = self._parse_time(mid_text)


            market_price, _matched = self._find_fuzzy_item_price(name)

            alchemy_price = self._get_price_by_tier(tier, name)

            parsed[bounty_id] = {
                "prob": prob,
                "exp": base_exp * 2 if prob >= 100 else base_exp,
                "market_price": market_price,
                "alchemy_price": alchemy_price,
                "tier": tier,
                "name": name,
                "time_val": time_val,
                "time_unit": time_unit,
                "is_doubled": prob >= 100,
            }
        return [parsed[key] for key in sorted(parsed.keys())]

    def _parse_old_bounties(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        旧版悬赏解析。修为逻辑保持原样；坊市价值取实际坊市价，炼金价值沿用旧版按品级规则。
        """
        parsed = []
        bounty_blocks = re.findall(r"(悬赏[壹贰叁].*?)(?=悬赏[壹贰叁]|━━━━━━|$)", raw_text, re.DOTALL)
        for block in bounty_blocks:
            title_match = re.search(r"(悬赏[壹贰叁]·.*?)\n", block)
            exp_match = re.search(r"基础奖励(\d+)修为", block)
            prob_match = re.search(r"成功率：(\d+)%", block)
            item_match = re.search(r"额外机缘：(.*?)「(.*?)」", block)
            time_val, time_unit = self._parse_time(block)

            if not title_match or not exp_match:
                continue
            base_exp = int(exp_match.group(1))
            prob = int(prob_match.group(1)) if prob_match else 0

            if item_match:
                tier = item_match.group(1).strip()
                name = item_match.group(2).strip()
                market_price, _matched = self._find_fuzzy_item_price(name)
                alchemy_price = self._get_price_by_tier(tier, name)
            else:
                tier = ""
                name = "无"
                market_price = 0.0
                alchemy_price = 0.0

            parsed.append({
                "prob": prob,
                "exp": base_exp * 2 if prob >= 100 else base_exp,
                "market_price": market_price,
                "alchemy_price": alchemy_price,
                "tier": tier,
                "name": name,
                "time_val": time_val,
                "time_unit": time_unit,
                "is_doubled": prob >= 100,
            })
        return parsed

    def _format_bounty_reply(self, parsed_bounties: List[Dict[str, Any]]) -> str:
        lines = []
        for index, bounty in enumerate(parsed_bounties, start=1):
            exp_str = self._format_exp(int(bounty["exp"]))
            display_name = f"{index}"
            bounty["exp_str"] = exp_str
            bounty["display_name"] = display_name
            double_tag = " (已翻倍🚀)" if bounty["is_doubled"] else ""

            market_price = float(bounty.get("market_price", 0) or 0)
            alchemy_price = float(bounty.get("alchemy_price", 0) or 0)


            if market_price >= 9999.0:
                market_text = "无价之宝"
            elif market_price > 0:
                market_text = f"{self._format_wan_value(market_price)}"
            else:
                market_text = "暂无坊市价"


            if alchemy_price >= 9999.0:
                alchemy_text = "无价之宝"
            elif alchemy_price > 0:
                alchemy_text = f"{alchemy_price}万"
            else:
                alchemy_text = "暂无炼金价"

            lines.append(f"{display_name} 奖励：{bounty['name']}")
            lines.append(f"💵坊市价值:{market_text}")
            lines.append(f"⚗️炼金价值:{alchemy_text}")
            lines.append(
                f"✨修为:{exp_str}{double_tag} "
                f"(成功率:{bounty['prob']}%, 耗时:{bounty['time_val']}{bounty['time_unit']})\n"
            )


        best_exp = max(parsed_bounties, key=lambda item: item["exp"])
        best_exp_tag = " (已翻倍🚀)" if best_exp["is_doubled"] else ""


        best_item = max(parsed_bounties, key=lambda item: float(item.get("market_price", 0) or 0))
        best_market = float(best_item.get("market_price", 0) or 0)
        best_alchemy = float(best_item.get("alchemy_price", 0) or 0)

        if best_market >= 9999.0:
            best_market_text = "无价之宝"
        elif best_market > 0:
            best_market_text = f"{self._format_wan_value(best_market)}"
        else:
            best_market_text = "暂无坊市价"

        if best_alchemy >= 9999.0:
            best_alchemy_text = "无价之宝"
        elif best_alchemy > 0:
            best_alchemy_text = f"{best_alchemy}万"
        else:
            best_alchemy_text = "暂无炼金价"

        lines.append("━━━━━━━━━━━━━━━")

        lines.append(
            f"🐉最高修为：{best_exp['display_name']} "
            f"({best_exp['exp_str']}{best_exp_tag}, "
            f"成功率:{best_exp['prob']}%, 耗时:{best_exp['time_val']}{best_exp['time_unit']})"
        )
        lines.append(
            f"💰最高价格：{best_item['display_name']} "
            f"(坊市价值:{best_market_text} / 炼金价值:{best_alchemy_text}, "
            f"成功率:{best_item['prob']}%, 耗时:{best_item['time_val']}{best_item['time_unit']})"
        )
        return "\n".join(lines)


    def _task_queue_id(self, gid: Optional[str]) -> str:
        gid_str = str(gid).strip() if gid not in (None, "", "None") else ""
        return f"group:{gid_str}" if gid_str else "private"

    def _task_unique_key(self, uid: str, task_type: str, gid: Optional[str]) -> str:
        return f"{self._task_queue_id(gid)}|{str(uid)}|{str(task_type)}"

    def _rebuild_task_index(self) -> bool:
        self.task_key_index.clear()
        changed = False

        ordered_tasks = sorted(
            list(self.active_tasks.items()),
            key=lambda item: (float((item[1] or {}).get("expire", 0)), item[0]),
        )

        for task_id, raw_task in ordered_tasks:
            if not isinstance(raw_task, dict):
                self.active_tasks.pop(task_id, None)
                changed = True
                continue

            uid = str(raw_task.get("uid", "")).strip()
            task_type = str(raw_task.get("type", "")).strip()
            if not uid or not task_type:
                self.active_tasks.pop(task_id, None)
                changed = True
                continue

            gid = raw_task.get("gid")
            key = self._task_unique_key(uid, task_type, gid)
            existing_task_id = self.task_key_index.get(key)
            if existing_task_id:
                self.active_tasks.pop(task_id, None)
                changed = True
                continue

            raw_task["uid"] = uid
            raw_task["type"] = task_type
            raw_task["gid"] = str(gid) if gid not in (None, "", "None") else None
            self.task_key_index[key] = task_id

        return changed

    def _find_existing_task_locked(
        self, uid: str, task_type: str, gid: Optional[str],
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        key = self._task_unique_key(uid, task_type, gid)
        task_id = self.task_key_index.get(key)
        if task_id:
            task = self.active_tasks.get(task_id)
            if isinstance(task, dict):
                return task_id, task
            self.task_key_index.pop(key, None)

        for candidate_id, candidate in self.active_tasks.items():
            if not isinstance(candidate, dict):
                continue
            if self._task_unique_key(
                str(candidate.get("uid", "")),
                str(candidate.get("type", "")),
                candidate.get("gid"),
            ) == key:
                self.task_key_index[key] = candidate_id
                return candidate_id, candidate

        return None, None

    async def _add_task(
        self, uid: str, task_type: str, total_seconds: float, gid: Optional[str], extra: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any], bool]:
        uid = str(uid).strip()
        task_type = str(task_type).strip()
        normalized_gid = str(gid) if gid not in (None, "", "None") else None

        async with self.task_lock:
            existing_id, existing_task = self._find_existing_task_locked(uid, task_type, normalized_gid)
            if existing_id and existing_task:
                return existing_id, existing_task, False

            task_id = f"{task_type}_{uid}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            task = {
                "uid": uid,
                "type": task_type,
                "expire": time.time() + max(0, float(total_seconds)),
                "gid": normalized_gid,
                "extra": extra or {},
            }
            self.active_tasks[task_id] = task
            self.task_key_index[self._task_unique_key(uid, task_type, normalized_gid)] = task_id
            await self._save_tasks_async_locked()

        return task_id, task, True

    def _start_task_timer(self, client, task_id: str, task: Dict[str, Any], initial_delay: float = 0.0) -> bool:
        runner = self.task_runners.get(task_id)
        if runner and not runner.done(): return False
        self.task_runners[task_id] = asyncio.create_task(self._run_task_timer(client, task_id, task, initial_delay))
        return True

    async def _run_task_timer(self, client, task_id: str, task: Dict[str, Any], initial_delay: float = 0.0) -> None:
        try:
            if initial_delay > 0:
                await asyncio.sleep(initial_delay)
            remaining = max(0, float(task.get("expire", 0)) - time.time())
            if remaining > 0:
                await asyncio.sleep(remaining)

            async with self.task_lock:
                current_task = self.active_tasks.get(task_id)
                if not isinstance(current_task, dict): return
                key = self._task_unique_key(str(current_task.get("uid", "")), str(current_task.get("type", "")), current_task.get("gid"))
                if self.task_key_index.get(key) != task_id: return
                del self.active_tasks[task_id]
                self.task_key_index.pop(key, None)
                await self._save_tasks_async_locked()
                task = current_task

            await self._send_task_reminder(client, task)

        except asyncio.CancelledError: raise
        except Exception: logger.exception("提醒任务执行失败: task_id=%s", task_id)
        finally:
            current_runner = self.task_runners.get(task_id)
            if current_runner is asyncio.current_task():
                self.task_runners.pop(task_id, None)

    async def _send_task_reminder(self, client, task: Dict[str, Any]) -> None:
        uid = str(task.get("uid", ""))
        if self._is_blacklisted_qq(uid): return
        gid = task.get("gid")
        ttype = task.get("type")
        extra = task.get("extra") or {}
        if not uid: return
        if gid and not self._group_id_reminder_enabled(gid): return

        if ttype == "悬赏":
            await self._safe_send_group_msg(client, gid, [{"type": "at", "data": {"qq": uid}}, {"type": "text", "data": {"text": " 🌠 叮！您的悬赏令已完成！快去查收机缘吧！"}}])
            if uid in self.pm_prefs.get("bounty", []):
                await self._safe_send_private_msg(client, uid, "🌠 叮！您的悬赏令已完成！快去群里查收机缘吧！")
        elif ttype == "秘境":
            tv, tu = extra.get("time_value", ""), extra.get("time_unit", "")
            g_msg = f"[CQ:at,qq={uid}] 道友，秘境探索已完成（历时{tv}{tu}），速速查看造化！"
            if gid: await self._safe_send_group_msg(client, gid, g_msg)
            else: await self._safe_send_private_msg(client, uid, g_msg)
            if uid in self.pm_prefs.get("mijing", []) and gid:
                await self._safe_send_private_msg(client, uid, f"道友，秘境探索已完成（历时{tv}{tu}），速去群内查看！")
        elif ttype == "灵田":
            await self._safe_send_group_msg(client, gid, [{"type": "at", "data": {"qq": uid}}, {"type": "text", "data": {"text": " 🌾 叮！灵田已成熟，快去收取天材地宝吧！"}}])
            if uid in self.pm_prefs.get("harvest", []):
                await self._safe_send_private_msg(client, uid, "🌾 叮！灵田已成熟，快去群里收取天材地宝吧！")

    async def _ensure_recovered(self, client) -> None:
        if self.tasks_recovered: return
        async with self.recover_lock:
            if self.tasks_recovered: return
            async with self.task_lock:
                if self._task_storage_dirty:
                    await self._save_tasks_async_locked()
                    self._task_storage_dirty = False
                recovered_tasks = list(self.active_tasks.items())

            now = time.time()
            expired_index = 0
            for task_id, task in recovered_tasks:
                initial_delay = 0.0
                if float(task.get("expire", 0)) <= now:
                    initial_delay = expired_index * 0.2
                    expired_index += 1
                self._start_task_timer(client, task_id, task, initial_delay)
            self.tasks_recovered = True
            logger.info("已恢复修仙提醒任务数量: %s", len(recovered_tasks))

    @filter.regex(r"^\s*查看(所有)?提醒\s*$")
    async def view_active_tasks(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        await self._ensure_recovered(event.bot)
        if not self._is_admin(event): return
        if not self.active_tasks:
            yield event.plain_result("📭 当前没有任何正在运行的提醒任务。")
            return
        now = time.time()
        lines = ["📊 当前运行中的提醒任务："]
        sorted_tasks = sorted(self.active_tasks.values(), key=lambda i: float(i.get("expire", 0)))
        for index, task in enumerate(sorted_tasks, start=1):
            remain = max(0, int(float(task.get("expire", 0)) - now))
            h, rem = divmod(remain, 3600)
            m, s = divmod(rem, 60)
            tstr = ""
            if h > 0: tstr += f"{h}小时"
            if m > 0: tstr += f"{m}分"
            tstr += f"{s}秒"
            lines.append(f"{index}. [{task.get('type', '未知')}] QQ:{task.get('uid', '未知')} 剩余 {tstr}")
        yield event.plain_result("\n".join(lines))

    @filter.regex(r"^\s*开启(悬赏|秘境|灵田)私聊\s*$")
    async def enable_pm_notify(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        match = re.search(r"开启(悬赏|秘境|灵田)私聊", event.message_str)
        if not match: return
        mod_name = match.group(1)
        key = PM_KEY_MAP[mod_name]
        uid = str(event.get_sender_id())
        async with self.pref_lock:
            if uid not in self.pm_prefs[key]:
                self.pm_prefs[key].append(uid)
                await self._save_prefs_async_locked()
        await self._send_quote_reply(event, f"✅ 已为您开启【{mod_name}】私聊通知！到期时将通过私聊同步提醒您。")

    @filter.regex(r"^\s*关闭(悬赏|秘境|灵田)私聊\s*$")
    async def disable_pm_notify(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        match = re.search(r"关闭(悬赏|秘境|灵田)私聊", event.message_str)
        if not match: return
        mod_name = match.group(1)
        key = PM_KEY_MAP[mod_name]
        uid = str(event.get_sender_id())
        async with self.pref_lock:
            if uid in self.pm_prefs[key]:
                self.pm_prefs[key].remove(uid)
                await self._save_prefs_async_locked()
        await self._send_quote_reply(event, f"❌ 已为您关闭【{mod_name}】私聊通知。")

    @filter.regex(r"(?s).*悬赏令.*")
    async def analyze_bounty(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        if re.search(r"接取|接成功", msg): return
        pb = self._parse_new_bounties(msg)
        if not pb: pb = self._parse_old_bounties(msg)
        if pb: yield event.plain_result(self._format_bounty_reply(pb))

    @filter.on_decorating_result(priority=10)
    async def on_recall(self, event: AiocqhttpMessageEvent):
        if self._blacklist_blocks_event(event): return
        result = event.get_result()
        if not result or not result.chain: return
        text_str = "".join(seg.text for seg in result.chain if isinstance(seg, Plain))
        if "坊市价值" not in text_str and "已为您接管倒计时" not in text_str: return

        chain = result.chain
        obmsg = await event._parse_onebot_json(MessageChain(chain=chain))
        gid = event.get_group_id()
        send_result = None
        if gid: send_result = await self._safe_send_group_msg(event.bot, str(gid), obmsg)
        else: send_result = await self._safe_send_private_msg(event.bot, str(event.get_sender_id()), obmsg)

        mid = self._extract_message_id(send_result)
        if mid: asyncio.create_task(self._delay_del(event.bot, mid, 30))
        chain.clear()
        event.stop_event()

    @filter.regex(r"(?s).*悬赏令.*")
    async def on_bounty_menu(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        if not self._is_official_like_source(event): return
        gid = str(event.get_group_id())
        if not gid or gid == "None": return
        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        tasks = {}
        for m in re.finditer(r"(?s)(\d+)[、\]].*?预计需\s*(\d+(?:\.\d+)?)\s*分钟", msg):
            tasks[m.group(1)] = float(m.group(2))
        for m in re.finditer(r"(?s)悬赏(壹|贰|叁|肆|伍|陆|[1-6]).*?耗时[：:\s]*(\d+(?:\.\d+)?)\s*分钟", msg):
            tn = BOUNTY_NUM_MAP.get(m.group(1))
            if tn: tasks[tn] = float(m.group(2))
        if tasks:
            uid = self._extract_target_qq_from_text(msg)
            if self._is_blacklisted_qq(uid): return
            if self._is_test_dry_run(event):
                task_text = "、".join(f"{k}:{v:g}分钟" for k, v in sorted(tasks.items(), key=lambda x: x[0]))
                await self._send_quote_reply(
                    event,
                    f"🧪 测试模式反馈：已识别悬赏菜单时间。\n"
                    f"目标QQ：{uid or '未识别'}\n"
                    f"悬赏耗时：{task_text}\n"
                    f"本次仅做解析反馈，不写入正式悬赏菜单缓存。",
                    recall_delay=30,
                    stop_event=True,
                )
                return
            self.menu_cache.setdefault(gid, {})
            if uid: self.menu_cache[gid][uid] = tasks
            self.menu_cache[gid]["last"] = tasks

    @filter.regex(r"(?s).*悬赏令接取\s*(\d+).*")
    async def on_user_accept(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        gid = str(event.get_group_id())
        sender = str(event.get_sender_id())
        if self._is_blacklisted_qq(sender): return
        if not gid or gid == "None" or sender == self.official_bot_qq: return
        match = re.search(r"悬赏令接取\s*(\d+)", event.message_str)
        if match:
            self.pending_accepts.setdefault(gid, []).append({
                "uid": sender, "task_id": match.group(1), "timestamp": time.time()
            })

    def _extract_target_qq_from_text(self, text: str) -> Optional[str]:
        for p in [r"(?:at_)?tinyid=(\d+)", r"\[CQ:at,qq=(\d+)\]", r"\[At:(\d+)\]"]:
            m = re.search(p, text)
            if m: return m.group(1)
        return None

    def _extract_bounty_task_id_from_text(self, text: str) -> Optional[str]:
        for p in [r"悬赏令(?:接取)?\s*(\d+)", r"悬赏\s*(壹|贰|叁|肆|伍|陆|[1-6])"]:
            m = re.search(p, text)
            if m: return BOUNTY_NUM_MAP.get(m.group(1), m.group(1))
        return None

    @filter.regex(r"(?s).*接取.*成功.*")
    async def on_official_confirm(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        if not self._is_official_like_source(event): return
        gid = str(event.get_group_id())
        if not gid or gid == "None": return

        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        now = time.time()
        pl = [i for i in self.pending_accepts.get(gid, []) if now - float(i.get("timestamp", 0)) <= 60]
        tq = self._extract_target_qq_from_text(msg)
        if self._is_blacklisted_qq(tq): return
        tid = self._extract_bounty_task_id_from_text(msg)

        sidx = None
        selected = None
        if pl:
            if tq and tid: sidx = next((i for i, v in enumerate(pl) if v.get("uid") == tq and v.get("task_id") == tid), None)
            if sidx is None and tq: sidx = next((i for i, v in enumerate(pl) if v.get("uid") == tq), None)
            if sidx is None and tid: sidx = next((i for i, v in enumerate(pl) if v.get("task_id") == tid), None)
            if sidx is None: sidx = 0
            if self._is_test_dry_run(event):
                selected = pl[sidx]
            else:
                selected = pl.pop(sidx)
                self.pending_accepts[gid] = pl

        if selected:
            uid = selected.get("uid") or tq or self.admin_qq
            sel_tid = selected.get("task_id") or tid or "未知"
        elif self._is_test_dry_run(event):
            uid = tq or self.admin_qq
            sel_tid = tid or "未知"
        else:
            return

        mins = None
        m_time = re.search(r"预计.*?(\d+(?:\.\d+)?)\s*分钟", msg)
        if m_time:
            mins = float(m_time.group(1))
        else:
            c_tasks = self.menu_cache.get(gid, {}).get(str(uid)) or self.menu_cache.get(gid, {}).get("last", {})
            mins = c_tasks.get(str(sel_tid)) if isinstance(c_tasks, dict) else None

        if mins is None: return
        dm = int(mins) if float(mins).is_integer() else mins

        if self._is_test_dry_run(event):
            await self._send_quote_reply(
                event,
                f"🧪 测试模式反馈：已识别悬赏接取成功，目标QQ:{uid}，{sel_tid}，耗时{dm}分钟。\n"
                f"本次仅做解析反馈，不写入正式提醒任务，也不会到点 @。",
                recall_delay=30,
                stop_event=False,
            )
            return

        t_saved, tk, created = await self._add_task(str(uid), "悬赏", mins * 60 + 30, gid)
        if not created: return
        self._start_task_timer(event.bot, t_saved, tk)

        yield event.chain_result([At(qq=str(uid)), Plain(f"  🌠 叮！悬赏令小助手已接管倒计时，{dm} 分钟后将自动 @ 您！")])

    @filter.regex(r"(?s).*题目.*")
    async def handle_idiom(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        await self._ensure_recovered(event.bot)
        msg = event.message_str
        if self._blacklist_blocks_event(event, msg): return
        if "题目" not in msg: return
        if not self.client_ai:
            logger.warning("DeepSeek API 未配置，跳过猜成语")
            return
        try:
            resp = await asyncio.wait_for(
                self.client_ai.chat.completions.create(
                    model=self.deepseek_model,
                    messages=[
                        {"role": "system", "content": "你是猜成语助手。请根据题目推断一个四字成语，只回复4个汉字，不要标点解释。"},
                        {"role": "user", "content": msg},
                    ], stream=False
                ), timeout=self.deepseek_timeout
            )
            ans = "".join(c for c in resp.choices[0].message.content.strip() if "\u4e00" <= c <= "\u9fa5")
            if len(ans) == 4: yield event.plain_result(ans)
        except Exception as e:
            logger.error(f"猜成语失败: {e}")

    @filter.regex(r"(?s).*(秘境|万妖之域|东玄域|西玄域|狐鸣山|云梦泽|黑水湖|乱魔海).*")
    async def handle_mijing(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        if not self._is_official_like_source(event): return
        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        tq = self._extract_target_qq_from_text(msg)
        if self._is_blacklisted_qq(tq): return
        t_m = re.search(r"([\d.]+)\s*(?:\(原.*?\)|（原.*?）)?\s*(分钟|分|秒钟|秒)", msg)
        if not tq or not t_m: return

        tv_f = float(t_m.group(1))
        tvd = int(tv_f) if tv_f.is_integer() else tv_f
        tu = t_m.group(2)
        ts = int(tv_f * 60) if "分" in tu else int(tv_f)
        ts += 30
        gid = event.get_group_id()

        if self._is_test_dry_run(event):
            await self._send_quote_reply(
                event,
                f"🧪 测试模式反馈：已识别秘境/探索提醒，目标QQ:{tq}，耗时{tvd}{tu}。\n"
                f"本次仅做解析反馈，不写入正式提醒任务，也不会到点提醒。",
                recall_delay=30,
                stop_event=True,
            )
            return

        t_saved, tk, created = await self._add_task(tq, "秘境", ts, str(gid) if gid else None, {"time_value": tvd, "time_unit": tu})
        if not created: return
        self._start_task_timer(event.bot, t_saved, tk)

        if gid: await self._safe_send_group_msg(event.bot, str(gid), f"[CQ:at,qq={tq}] 已设置秘境提醒，{tvd}{tu}后见！", recall_delay=30)
        else: await self._safe_send_private_msg(event.bot, tq, f"已为您设置秘境提醒，{tvd}{tu}后见！")

    @filter.regex(r"(?s).*(灵田收取|灵田结算).*")
    async def on_user_harvest(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        gid = str(event.get_group_id())
        sender = str(event.get_sender_id())
        if self._is_blacklisted_qq(sender): return
        if not gid or gid == "None" or sender == self.official_bot_qq: return
        now = time.time()
        pl = [i for i in self.pending_harvests.get(gid, []) if now - float(i.get("timestamp", 0)) <= 30]
        pl.append({"uid": sender, "timestamp": now})
        self.pending_harvests[gid] = pl

    @filter.regex(r"(?s).*(灵药丰收|收获药材|成功收获药材).*")
    async def on_official_harvest_confirm(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("xiuxian"): return
        if not self._group_reminder_enabled(event): return
        await self._ensure_recovered(event.bot)
        if not self._is_official_like_source(event): return
        gid = str(event.get_group_id())
        if not gid or gid == "None": return
        msg = self._get_pure_plain_text(event)
        now = time.time()
        pl = [i for i in self.pending_harvests.get(gid, []) if now - float(i.get("timestamp", 0)) <= 30]

        tq = self._extract_target_qq_from_text(msg)
        if self._is_blacklisted_qq(tq): return
        sel = None
        if pl:
            sidx = next((i for i, v in enumerate(pl) if v.get("uid") == tq), 0) if tq else 0
            if self._is_test_dry_run(event):
                sel = pl[sidx]
            else:
                sel = pl.pop(sidx)
                if pl: self.pending_harvests[gid] = pl
                else: self.pending_harvests.pop(gid, None)

        if sel:
            uid = sel.get("uid") or tq or self.admin_qq
        elif self._is_test_dry_run(event):
            uid = tq or self.admin_qq
        else:
            return

        if self._is_test_dry_run(event):
            await self._send_quote_reply(
                event,
                f"🧪 测试模式反馈：已识别灵田收获确认，目标QQ:{uid}，应设置47小时后收取提醒。\n"
                f"本次仅做解析反馈，不写入正式提醒任务，也不会到点提醒。",
                recall_delay=30,
                stop_event=False,
            )
            return

        t_saved, tk, created = await self._add_task(uid, "灵田", 169260 + 30, gid)
        if not created: return
        self._start_task_timer(event.bot, t_saved, tk)
        yield event.chain_result([At(qq=uid), Plain("  🌾 叮！灵田助手已接管倒计时，47小时后提醒收取！")])


    def _find_item_price(self, target_name: str) -> float:
        for cat in MARKET_CATEGORIES:
            node = self.market_data.get(cat, {}).get(target_name)
            if node: return float(node.get('latest_price', 0)) if isinstance(node, dict) else float(node)
        return 0.0

    def _find_fuzzy_item_price(self, item_name: str) -> Tuple[float, str]:
        exact = self._find_item_price(item_name)
        if exact > 0: return exact, item_name
        cands = []
        for cat in MARKET_CATEGORIES:
            for db_name in self.market_data.get(cat, {}):
                if item_name in db_name or db_name in item_name: cands.append(db_name)
        if not cands: return 0.0, item_name
        best = max(cands, key=len)
        return self._find_item_price(best), best

    def _get_alchemy_price(self, item_name: str) -> float:
        prices = self.config.get('alchemy_prices', {})
        if item_name in prices: return float(prices[item_name])
        for name in sorted(prices.keys(), key=len, reverse=True):
            if name in item_name or item_name in name: return float(prices[name])
        return 0.0

    def _parse_reward_items(self, message: str, pattern: re.Pattern) -> List[Tuple[str, int]]:
        items: List[Tuple[str, int]] = []
        for match in pattern.finditer(message):
            name = match.group(1).strip()
            try:
                count = int(match.group(2))
            except (TypeError, ValueError):
                continue
            if name and count > 0:
                items.append((name, count))
        return items

    def _dedupe_repeated_items(self, items: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        """
        【官方bot重复回显修复】检测物品列表是否为同一子列表连续重复 K 次（K>=2），
        如果是，只保留第一段，避免数量与估价被成倍放大。
        """
        n = len(items)
        if n < 2:
            return items


        for k in range(2, n + 1):
            if n % k != 0:
                continue
            block_len = n // k
            block = items[:block_len]

            if all(items[i * block_len:(i + 1) * block_len] == block for i in range(1, k)):
                logger.info(f"[去重] 官方bot重复回显已合并: {n} → {block_len}")
                return block

        return items

    def _format_wan_value(self, value_wan: float) -> str:
        try:
            value = float(value_wan)
        except (TypeError, ValueError):
            value = 0.0

        if value >= 10000:
            num = value / 10000
            return f"{num:.2f}".rstrip('0').rstrip('.') + "亿"
        return f"{value:.2f}".rstrip('0').rstrip('.') + "万"

    def _get_market_listing_fee_rate(self, price_wan: float) -> float:
        try:
            price = float(price_wan)
        except (TypeError, ValueError):
            price = 0.0

        if price < 500:
            return 0.05
        if price < 1000:
            return 0.10
        if price < 1500:
            return 0.15
        if price < 2000:
            return 0.20
        return 0.30

    def _calc_market_listing_fee(self, price_wan: float, count: int = 1) -> float:
        try:
            price = float(price_wan)
            num = int(count)
        except (TypeError, ValueError):
            return 0.0
        if price <= 0 or num <= 0:
            return 0.0
        return price * self._get_market_listing_fee_rate(price) * num

    def _calc_herb_reward_value(self, message: str) -> Tuple[int, float, float, List[str]]:
        items = self._parse_reward_items(message, HERB_REWARD_PATTERN)
        items = self._dedupe_repeated_items(items)
        total_count = 0
        total_value = 0.0
        total_fee = 0.0
        missing: List[str] = []

        for name, count in items:
            total_count += count
            price, matched_name = self._find_fuzzy_item_price(name)
            if price > 0:
                total_value += price * count
                total_fee += self._calc_market_listing_fee(price, count)
            else:
                missing.append(name)

        return total_count, total_value, total_fee, missing

    def _calc_pill_reward_value(self, message: str) -> Tuple[int, float, List[str]]:
        items = self._parse_reward_items(message, PILL_REWARD_PATTERN)
        items = self._dedupe_repeated_items(items)
        total_count = 0
        total_value = 0.0
        missing: List[str] = []

        for name, count in items:
            total_count += count
            price = self._get_alchemy_price(name)
            if price > 0:
                total_value += price * count
            else:
                missing.append(name)

        return total_count, total_value, missing

    async def _notify_admin_missing_prices(self, event: AstrMessageEvent, item_type: str, missing: List[str]) -> None:
        if not missing:
            return

        unique_missing = list(dict.fromkeys(str(x).strip() for x in missing if str(x).strip()))
        if not unique_missing:
            return

        gid = event.get_group_id()
        tip = (
            f"⚠️ 修仙估价提醒：本次{item_type}收获存在价格缺失，已在群内按0计入。\n"
            f"群号：{gid if gid else '私聊'}\n"
            f"缺失{item_type}：{'、'.join(unique_missing)}\n"
            f"请先完成坊市采集，或手动补充 market_data.json 后重载插件。"
        )
        await self._safe_send_private_msg(event.bot, self.admin_qq, tip)

    def _get_alchemy_match_pool(self) -> List[str]:
        names = set()
        for cat in MARKET_CATEGORIES:
            for k in self.market_data.get(cat, {}).keys(): names.add(k.strip())
        names.update(self.config.get('alchemy_target_items', []))
        names.update(self.config.get('alchemy_prices', {}).keys())
        return sorted([n for n in names if n], key=len, reverse=True)

    def _extract_bag_items(self, message: str) -> List[Tuple[str, int]]:
        """
        解析背包物品。
        官方 bot 在部分客户端会同时回显 markdown 链接版与纯文本版，
        导致同一物品出现两遍；这里按清洗后的物品名去重，避免一键上架/炼金重复生成。
        """
        res: List[Tuple[str, int]] = []
        seen_names = set()

        for match in BAG_ITEM_PATTERN.finditer(message):
            block = match.group(0)
            if '已装备' in block:
                continue

            name = match.group(1).strip()
            if name.startswith('['):
                nm = BRACKET_NAME_PATTERN.search(name)
                if nm:
                    name = nm.group(1)

            name = name.replace('名字:', '').replace('名字：', '').strip()
            name_key = re.sub(r'\s+', '', name)

            if '☆' in name or '---' in name or not name_key:
                continue
            if name_key in seen_names:
                continue

            try:
                count = int(match.group(2))
            except (TypeError, ValueError):
                continue

            seen_names.add(name_key)
            res.append((name, count))

        return res

    async def _get_full_message_text(self, event: AstrMessageEvent) -> str:
        base_text = self._clean_message(event.message_str or "")
        raw_event = getattr(event.message_obj, "raw_message", {}) or {}
        if not isinstance(raw_event, dict): raw_event = getattr(raw_event, "__dict__", {}) or {}
        reply_id = None
        for seg in raw_event.get("message", []):
            if isinstance(seg, dict) and seg.get("type") == "reply":
                reply_id = seg.get("data", {}).get("id")
                break
        if not reply_id: return base_text
        try:
            bot = getattr(event, "bot", None) or self.client
            quoted = await bot.call_action("get_msg", message_id=int(reply_id))
            if isinstance(quoted, dict):
                qdata = quoted.get("data", quoted)
                qtext = qdata.get("raw_message") or qdata.get("message") or ""
                if isinstance(qtext, list):
                    qtext = "\n".join(s.get("data",{}).get("text","") for s in qtext if isinstance(s, dict) and s.get("type")=="text")
                return f"{self._clean_message(str(qtext))}\n{base_text}"
        except Exception: pass
        return base_text


    @filter.regex(r'(?s).*成功领取到丹药[：:].*')
    async def on_official_pill_reward_value(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("alchemy"):
            return
        if not self._group_reminder_enabled(event):
            return
        await self._ensure_recovered(event.bot)
        if not self._is_value_calc_source(event):
            return

        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        total_count, total_value, missing = self._calc_pill_reward_value(msg)
        if total_count <= 0:
            return

        if missing:
            logger.warning("丹药炼金估价缺少价格，已按0计入: %s", "、".join(missing))

        reply = (
            f"经过卡比的计算，道友本次成功领取{total_count}颗丹药，"
            f"炼金总价值{self._format_wan_value(total_value)}！恭喜🎉"
        )
        await self._send_quote_reply(event, reply, recall_delay=30, stop_event=False)

    @filter.regex(r'(?s).*(灵药丰收|收获药材|成功收获药材).*')
    async def on_official_herb_reward_value(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("alchemy"):
            return
        if not self._group_reminder_enabled(event):
            return
        await self._ensure_recovered(event.bot)
        if not self._is_value_calc_source(event):
            return

        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        total_count, total_value, total_fee, missing = self._calc_herb_reward_value(msg)
        if total_count <= 0:
            return

        if missing:
            logger.warning("药材坊市估价缺少价格，已按0计入: %s", "、".join(missing))
            asyncio.create_task(self._notify_admin_missing_prices(event, "药材", missing))

        fee_text = self._format_wan_value(total_fee)
        reply = (
            f"经过卡比的计算，道友本次成功收取{total_count}株灵药，"
            f"坊市总价值{self._format_wan_value(total_value)}（含手续费{fee_text}）！恭喜🎉"
        )
        await self._send_quote_reply(event, reply, recall_delay=30, stop_event=False)


    @filter.regex(r'(?s)上架')
    async def on_user_listing_backpack(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("alchemy"): return
        if not self._group_reminder_enabled(event): return
        if self._is_official_bot(event): return
        text = await self._get_full_message_text(event)
        if self._text_mentions_blacklisted_qq(text): return
        if '上架' not in text: return
        items = self._extract_bag_items(text)
        if not items: return

        tv, tp, tf = 0.0, 0.0, 0.0
        cmds = []
        listed_seen = set()
        for name, cnt in items:
            pr, m_name = self._find_fuzzy_item_price(name)
            if pr <= 0:
                continue


            list_key = re.sub(r'\s+', '', str(m_name or name))
            if list_key in listed_seen:
                continue
            listed_seen.add(list_key)

            fee = self._calc_market_listing_fee(pr, 1)
            net = pr - fee
            tv += pr * cnt; tp += net * cnt; tf += fee * cnt
            cmds.append(f'确认坊市上架{m_name} {int(pr*10000)} {cnt}')

        if not cmds: return
        reply = f"📊 【背包资产总览】\n💰 总市值: {tv:.2f}万\n📉 总扣税: {tf:.2f}万\n💸 净收益: {tp:.2f}万\n━━━━━━━━━━━━━━━\n👇 一键上架指令 👇\n" + "\n".join(cmds)
        asyncio.create_task(self._send_and_recall_universal(event, reply, 30))
        self._stop_event(event)

    @filter.regex(r'(?s)炼金')
    async def on_alchemy_backpack(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._module_enabled("alchemy"): return
        if not self._group_reminder_enabled(event): return
        if self._is_official_bot(event): return
        text = await self._get_full_message_text(event)
        if self._text_mentions_blacklisted_qq(text): return
        if '炼金' not in text: return
        match_pool = self._get_alchemy_match_pool()
        items = self._extract_bag_items(text)
        if not items or not match_pool: return

        cmds, details, miss = [], [], []
        tv = 0.0
        seen = set()

        for name, cnt in items:
            m_name = next((x for x in match_pool if x == name), None)
            if not m_name:
                m_name = next((x for x in match_pool if x in name or name in x), None)
            if not m_name or m_name in seen: continue
            seen.add(m_name)
            cmds.append(f"炼金 {m_name} {cnt}")
            pr = self._get_alchemy_price(m_name)
            if pr > 0:
                sub = pr * cnt
                tv += sub
                details.append(f"{m_name} {cnt} 总价:{int(sub)}万")
            else:
                miss.append(m_name)

        if not cmds: return
        val_str = f"{tv/10000:.2f} 亿" if tv >= 10000 else f"{tv:.2f} 万"
        reply = f"💰 总价值：{val_str}\n━━━━━━━━━━━━━━━\n" + "\n".join(cmds)
        if details: reply += "\n━━━━━━━━━━━━━━━\n" + "\n".join(details)
        if miss: reply += f"\n━━━━━━━━━━━━━━━\n⚠️ 价格缺失: {'、'.join(miss)}\n可用『设置炼金价格 物品名 xxx万』补全"
        asyncio.create_task(self._send_and_recall_universal(event, reply, 30))
        self._stop_event(event)


    async def _market_schedule_loop(self):
        while True:
            try:
                if not self._module_enabled("market_spider"):
                    await asyncio.sleep(10)
                    continue
                st = self.config.get('spider_settings', {})
                if not st.get('enable_schedule', True):
                    await asyncio.sleep(10)
                    continue
                tz_bj = datetime.timezone(datetime.timedelta(hours=8))
                now = datetime.datetime.now(tz_bj)
                if now.hour in MARKET_TARGET_HOURS and now.minute == 0 and now.second < 10:
                    if not self.is_scraping and self.target_group and self.client:
                        logger.info('[大一统] 启动坊市全自动采集')
                        await self._start_scraping()
                        await asyncio.sleep(60)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f'爬虫时钟异常 {e}')
                await asyncio.sleep(5)

    def _bj_now(self) -> datetime.datetime:
        tz_bj = datetime.timezone(datetime.timedelta(hours=8))
        return datetime.datetime.now(tz_bj)

    def _calc_next_monitor_run(self, now: Optional[datetime.datetime] = None) -> datetime.datetime:
        now = now or self._bj_now()
        tz = now.tzinfo

        seven_zero = now.replace(hour=7, minute=0, second=0, microsecond=0)
        seven_one = now.replace(hour=7, minute=1, second=0, microsecond=0)
        day_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        if now <= seven_zero:
            candidate = now.replace(minute=0, second=0, microsecond=0)
            if candidate < now:
                candidate += datetime.timedelta(hours=1)
            if candidate <= seven_zero:
                return candidate
            return seven_one

        if now <= seven_one:
            return seven_one

        if now <= day_end:
            elapsed_seconds = int((now - seven_one).total_seconds())
            steps = (elapsed_seconds + 359) // 360
            candidate = seven_one + datetime.timedelta(seconds=steps * 360)
            if candidate <= day_end:
                return candidate

        return (now + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=tz
        )

    async def _send_monitor_probe_once(self) -> bool:
        tg = str(self.config.get('monitor_trigger_group') or '').strip()
        cmds = self.config.get('monitor_cmds') or ["坊市查看技能3"]
        cmds = [str(cmd).strip() for cmd in cmds if str(cmd).strip()]

        if not tg or tg == "None":
            logger.warning('[大一统] 坊市监控未发送：monitor_trigger_group 未配置')
            return False
        if not cmds:
            logger.warning('[大一统] 坊市监控未发送：monitor_cmds 为空')
            return False
        if not self.client:
            logger.warning('[大一统] 坊市监控等待中：尚未获取 bot client')
            return False

        sent_any = False
        for cmd in cmds:
            chain = [
                {'type': 'at', 'data': {'qq': self.official_bot_qq}},
                {'type': 'text', 'data': {'text': f' {cmd}'}},
            ]
            res = await self._safe_send_group_msg(self.client, tg, chain)
            sent_any = sent_any or bool(res)
            await asyncio.sleep(2)
        return sent_any

    async def _market_monitor_loop(self):
        await asyncio.sleep(10)
        next_run: Optional[datetime.datetime] = None

        while True:
            try:
                if not self._module_enabled("market_monitor"):
                    next_run = None
                    await asyncio.sleep(10)
                    continue

                if not self.config.get('monitor_enabled', False):
                    next_run = None
                    await asyncio.sleep(10)
                    continue

                if self.is_scraping:
                    await asyncio.sleep(10)
                    continue

                now = self._bj_now()
                if next_run is None:
                    next_run = self._calc_next_monitor_run(now)
                    logger.info('[大一统] 坊市监控下一次触发时间：%s', next_run.strftime('%Y-%m-%d %H:%M:%S'))

                if now >= next_run:
                    success = await self._send_monitor_probe_once()

                    if success:
                        logger.info('[大一统] 坊市监控已触发：%s', next_run.strftime('%Y-%m-%d %H:%M:%S'))
                        next_run = self._calc_next_monitor_run(next_run + datetime.timedelta(seconds=1))
                        logger.info('[大一统] 坊市监控下一次触发时间：%s', next_run.strftime('%Y-%m-%d %H:%M:%S'))
                    else:
                        next_run = now + datetime.timedelta(seconds=30)

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception('[大一统] 坊市监控循环异常：%s', e)
                await asyncio.sleep(60)

    async def _start_scraping(self):
        self.is_scraping = True
        self.current_category_idx = 0
        self.current_page = 1
        tz_bj = datetime.timezone(datetime.timedelta(hours=8))
        self.current_scrape_time = datetime.datetime.now(tz_bj).strftime('%Y-%m-%d %H:%M:%S')
        await self._send_next_request()

    async def _send_next_request(self):
        if not self.client or not self.target_group or not self.is_scraping: return
        if self.current_category_idx >= len(MARKET_CATEGORIES):
            self.is_scraping = False
            await self._save_market_data_async()
            cfg = self._network_market_cfg()
            if bool(cfg.get("local_export_enabled", True)) or (bool(cfg.get("enabled", False)) and bool(cfg.get("upload_after_full_scrape", True))):
                asyncio.create_task(self._upload_market_prices_background("full_scrape_done"))
            asyncio.create_task(self._send_and_recall_universal(None, f"🎉 坊市采集完成并落盘! \n🕒 {self.current_scrape_time}", 0))
            return
        cat = MARKET_CATEGORIES[self.current_category_idx]
        chain = [{'type': 'at', 'data': {'qq': self.official_bot_qq}}, {'type': 'text', 'data': {'text': f' 坊市查看{cat}{self.current_page}'}}]
        await self._safe_send_group_msg(self.client, self.target_group, chain)

    def _infer_market_category_from_text(self, text: str) -> Optional[str]:
        """从坊市回执文本中尽量推断分类；推断失败时返回 None。"""
        msg = str(text or "")
        for cat in MARKET_CATEGORIES:
            if re.search(rf"坊市\s*(?:查看)?\s*{re.escape(cat)}", msg):
                return cat
            if re.search(rf"{re.escape(cat)}\s*(?:坊市|列表|第\d+页)", msg):
                return cat
        return None

    def _find_existing_market_category(self, item_name: str) -> Optional[str]:
        name = self._normalize_market_item_name(item_name)
        if not name:
            return None
        for cat in MARKET_CATEGORIES:
            cat_data = self.market_data.get(cat, {})
            if name in cat_data:
                return cat
            for db_name in cat_data.keys():
                if self._normalize_market_item_name(db_name) == name:
                    return cat
        return None

    async def _upsert_market_price_items(
        self,
        items: List[Tuple[str, float]],
        source_text: str = "",
        category_override: Optional[str] = None,
        seen_at: Optional[str] = None,
    ) -> int:
        """把任意官方坊市价格页写入 market_data。用于手动刷新、监控探测和自动采集。"""
        if not items:
            return 0

        inferred_cat = category_override or self._infer_market_category_from_text(source_text)
        if inferred_cat not in MARKET_CATEGORIES:
            inferred_cat = None

        if not seen_at:
            seen_at = self._bj_now().strftime('%Y-%m-%d %H:%M:%S')

        updated = 0
        seen_names = set()
        for raw_name, raw_price in items:
            name = self._normalize_market_item_name(raw_name)
            if not name or name in seen_names:
                continue
            seen_names.add(name)

            try:
                price_wan = float(raw_price)
            except (TypeError, ValueError):
                continue
            if price_wan <= 0:
                continue

            cat = inferred_cat or self._find_existing_market_category(name) or "道具"
            self.market_data.setdefault(cat, {})
            node = self.market_data[cat].setdefault(name, {'latest_price': 0, 'history': {}})
            if not isinstance(node, dict):
                node = {'latest_price': float(node or 0), 'history': {}}
                self.market_data[cat][name] = node
            node.setdefault('history', {})
            node['latest_price'] = price_wan
            node['history'][seen_at] = price_wan
            updated += 1

        if updated > 0:
            await self._save_market_data_async()
        return updated

    async def _after_market_price_items_updated(self, reason: str = "") -> None:
        """价格被任意坊市页面更新后，刷新本地导出；按配置选择是否后台上传。"""
        cfg = self._network_market_cfg()
        if bool(cfg.get("local_export_enabled", True)):
            try:
                await self._export_market_prices_local()
            except Exception as e:
                logger.warning("[大一统] 坊市价格更新后本地导出失败:%s", e)
        if bool(cfg.get("enabled", False)) and bool(cfg.get("upload_monitor_items", False)):
            asyncio.create_task(self._upload_market_prices_background(reason or "market_price_items_updated"))

    @filter.regex(r'(?s).*坊市查看\s*(技能|丹药|装备|药材|道具)\s*\d+.*')
    async def cache_manual_market_query_hint(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        """记录任意群成员最近一次手动坊市查看分类，供随后官方价格页归类使用。"""
        gid = str(event.get_group_id())
        if not gid or gid == "None":
            return
        if self._is_official_bot(event):
            return
        m = re.search(r'坊市查看\s*(技能|丹药|装备|药材|道具)\s*\d+', event.message_str or "")
        if not m:
            return
        self.market_query_hints[gid] = {"category": m.group(1), "timestamp": time.time()}


    @filter.regex(r'(?s).*(没有那么多页|价格:).*')
    async def on_market_spider_intercept(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        await self._ensure_recovered(event.bot)
        if not self.client: self.client = event.bot
        if not self._is_official_like_source(event): return

        msg = self._get_pure_plain_text(event)
        if self._blacklist_blocks_event(event, msg): return
        gid = str(event.get_group_id())

        items = []
        if '价格:' in msg:
            for m in PRICE_PATTERN.finditer(msg):
                price_wan = float(m.group(1)) * (10000 if m.group(2) == '亿' else 1)
                items.append((m.group(3).strip(), price_wan))

        if self._is_test_dry_run(event):
            if '没有那么多页' in msg:
                await self._send_quote_reply(
                    event,
                    "🧪 测试模式反馈：已识别『没有那么多页』分页结束提示。\n"
                    "本次仅做解析反馈，不推进正式坊市采集进度，也不写入任何正式数据。",
                    recall_delay=30,
                    stop_event=True,
                )
                return

            if items:
                targets = set(self.config.get('monitor_items', []))
                founds = [name for name, _ in items if name in targets]
                preview_lines = [f"{idx}. {name}：{self._format_wan_value(price)}" for idx, (name, price) in enumerate(items[:15], start=1)]
                more = f"\n……另有 {len(items) - 15} 条未展示" if len(items) > 15 else ""
                hit_text = f"\n监控命中：{'、'.join(dict.fromkeys(founds))}" if founds else "\n监控命中：无"
                await self._send_quote_reply(
                    event,
                    "🧪 测试模式反馈：已识别坊市价格文本。\n"
                    f"解析数量：{len(items)} 条\n"
                    + "\n".join(preview_lines)
                    + more
                    + hit_text
                    + "\n本次不写入 market_data.json，不更新正式价格历史，也不向监控通知群广播。",
                    recall_delay=30,
                    stop_event=True,
                )
                return

        is_spider = (gid == self.target_group)
        is_monitor = (gid == self.config.get('monitor_trigger_group'))

        if is_spider and not self._module_enabled("market_spider"): is_spider = False
        if is_monitor and not self._module_enabled("market_monitor"): is_monitor = False


        if not (is_spider or is_monitor or items): return

        if '没有那么多页' in msg and self.is_scraping and is_spider:
            self.current_category_idx += 1
            self.current_page = 1
            await self._send_next_request()
            self._stop_event(event)
            return

        if items:
            active_spider_page = bool(self.is_scraping and is_spider and self.current_category_idx < len(MARKET_CATEGORIES))
            manual_hint_cat = None
            hint = self.market_query_hints.get(gid)
            if isinstance(hint, dict) and time.time() - float(hint.get("timestamp", 0) or 0) <= 90:
                raw_hint_cat = str(hint.get("category") or "").strip()
                if raw_hint_cat in MARKET_CATEGORIES:
                    manual_hint_cat = raw_hint_cat
            cat_override = MARKET_CATEGORIES[self.current_category_idx] if active_spider_page else manual_hint_cat
            seen_at = self.current_scrape_time if active_spider_page else None

            updated_count = await self._upsert_market_price_items(
                items,
                source_text=msg,
                category_override=cat_override,
                seen_at=seen_at,
            )
            if updated_count > 0:
                asyncio.create_task(self._after_market_price_items_updated("market_price_page_seen"))

            if self._module_enabled("market_monitor") and self.config.get('monitor_enabled') and items:
                targets = self.config.get('monitor_items', [])
                founds = set(n for n, _ in items if n in targets)
                if founds:
                    txt = "\n".join([f"发现 {n} 出现在坊市，有缘者得之！" for n in founds] * 3)
                    n_gid = str(self.config.get('monitor_trigger_group') or '').strip()
                    if n_gid and n_gid != "None":
                        asyncio.create_task(self._safe_send_group_msg(self.client, n_gid, txt))

            if active_spider_page:
                self.current_page += 1
                await self._send_next_request()
                self._stop_event(event)


    @filter.regex(r'^\s*修仙菜单\s*$')
    async def show_xiuxian_menu(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        menu_text = """📚 【修仙插件管理员菜单】
[模块控制]
- 开启模块/关闭模块 <修仙|炼金|爬虫|监控>
- 模块状态
- 开启测试模式 / 关闭测试模式

[坊市采集]
- 开启自动坊市 (绑定当前群)
- 采集坊市 (立即触发)
- 上传坊市价格 (手动上传到中心价格服务)
- 坊市网络状态 (查看上传配置与最近结果)
- 开启/关闭坊市网络
- 设置坊市上传地址 <URL>
- 设置坊市上传密钥 <密钥>
- 设置炼金价格 <物品名> <价格>万

[坊市监控]
- 开启/关闭监控坊市
- 设置监控触发群 (当前群设为主群)
- 开启此群通知 (接收稀有物品播报)
- 添加/删除监控指令 <指令>
- 添加/删除监控物品 <物品名>

[提醒服务]
- 查看所有提醒
- 开启/关闭<悬赏|秘境|灵田>私聊"""
        asyncio.create_task(self._send_and_recall_universal(event, menu_text, 60))
        self._stop_event(event)


    @filter.regex(r'^\s*加黑QQ号\s*(\d+)\s*$')
    async def add_blacklist_qq_cmd(self, event: AstrMessageEvent):
        if not self._is_admin(event): return
        m = re.match(r'^\s*加黑QQ号\s*(\d+)\s*$', event.message_str.strip())
        if not m:
            self._stop_event(event)
            return
        uid = m.group(1).strip()
        bl = self.config.setdefault('blacklist_qq', [])
        bl = [str(x).strip() for x in bl if str(x).strip()]
        if uid not in bl:
            bl.append(uid)
        self.config['blacklist_qq'] = list(dict.fromkeys(bl))
        await self._save_config_async()
        await self._purge_blacklisted_user_data(uid)
        asyncio.create_task(self._send_and_recall_universal(event, '✅ 已加入黑名单，本插件将不再处理该账号相关功能。', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*(开启本群提醒|关闭本群提醒)\s*$')
    async def toggle_group_reminder_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        gid = event.get_group_id()
        if not gid:
            asyncio.create_task(self._send_and_recall_universal(event, '❌ 本指令仅支持在群聊中使用。', 30))
            self._stop_event(event)
            return
        enable = event.message_str.strip() == '开启本群提醒'
        self.config.setdefault('group_reminder_enabled', {})[str(gid)] = enable
        await self._save_config_async()
        text = (
            f"{'✅' if enable else '🛑'} 本群提醒功能已{'开启' if enable else '关闭'}。\n"
            f"影响范围：悬赏解析、悬赏倒计时、秘境提醒、灵田提醒、私聊提醒、丹药估价、药材估价、一键上架、一键炼金。"
        )
        asyncio.create_task(self._send_and_recall_universal(event, text, 30))
        self._stop_event(event)


    @filter.regex(r'^\s*(开启测试模式|关闭测试模式)\s*$')
    async def toggle_test_mode_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event):
            return

        enable = event.message_str.strip() == "开启测试模式"
        self.config["test_mode"] = enable
        await self._save_config_async()

        status = "开启" if enable else "关闭"
        tip = (
            f"✅ 测试模式已{status}。\n"
            f"当前测试QQ：{self.admin_qq}\n"
            f"说明：开启后，超级管理员发送类官方 bot 文本，会以干运行方式进入各类官方消息处理器。\n"
            f"干运行不会写入正式价格数据、不会创建正式提醒任务、不会广播正式监控提醒。"
        )
        asyncio.create_task(self._send_and_recall_universal(event, tip, 30))
        self._stop_event(event)


    @filter.regex(r'^\s*添加监控指令\s+(.+)$')
    async def add_monitor_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        cmd = event.message_str.replace('添加监控指令', '').strip()
        cmds = self.config.setdefault('monitor_cmds', [])
        if cmd not in cmds:
            cmds.append(cmd)
            await self._save_config_async()
            asyncio.create_task(self._send_and_recall_universal(event, f'✅ 已添加监控指令：{cmd}', 30))
        else:
            asyncio.create_task(self._send_and_recall_universal(event, f'⚠️ 该指令已在监控列表中', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*删除监控指令\s+(.+)$')
    async def del_monitor_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        cmd = event.message_str.replace('删除监控指令', '').strip()
        cmds = self.config.setdefault('monitor_cmds', [])
        if cmd in cmds:
            cmds.remove(cmd)
            await self._save_config_async()
            asyncio.create_task(self._send_and_recall_universal(event, f'✅ 已删除监控指令：{cmd}', 30))
        else:
            asyncio.create_task(self._send_and_recall_universal(event, f'⚠️ 指令不存在列表中', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*添加监控物品\s+(.+)$')
    async def add_monitor_items(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        raw_items = event.message_str.replace('添加监控物品', '').strip()
        items_to_add = [x.strip() for x in raw_items.split() if x.strip()]

        exist_items = self.config.setdefault('monitor_items', [])
        added = []
        for item in items_to_add:
            if item not in exist_items:
                exist_items.append(item)
                added.append(item)
        await self._save_config_async()
        if added:
            asyncio.create_task(self._send_and_recall_universal(event, f'✅ 已添加监控物品：{", ".join(added)}', 30))
        else:
            asyncio.create_task(self._send_and_recall_universal(event, f'⚠️ 您添加的物品已经在监控列表中了', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*删除监控物品\s+(.+)$')
    async def del_monitor_items(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        raw_items = event.message_str.replace('删除监控物品', '').strip()
        items_to_del = [x.strip() for x in raw_items.split() if x.strip()]

        exist_items = self.config.setdefault('monitor_items', [])
        removed = []
        for item in items_to_del:
            if item in exist_items:
                exist_items.remove(item)
                removed.append(item)
        await self._save_config_async()
        if removed:
            asyncio.create_task(self._send_and_recall_universal(event, f'✅ 已删除监控物品：{", ".join(removed)}', 30))
        else:
            asyncio.create_task(self._send_and_recall_universal(event, f'⚠️ 这些物品原本就不在监控列表中', 30))
        self._stop_event(event)


    @filter.regex(r'^\s*设置炼金价格\s+\S+\s+\d+(?:\.\d+)?\s*万?\s*$')
    async def set_alchemy_price_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        m = re.match(r'^\s*设置炼金价格\s+(\S+)\s+(\d+(?:\.\d+)?)\s*万?\s*$', event.message_str.strip())
        if m:
            self.config['alchemy_prices'][m.group(1)] = float(m.group(2))
            await self._save_config_async()
            asyncio.create_task(self._send_and_recall_universal(event, f"✅ 已设置【{m.group(1)}】炼金价格 {m.group(2)} 万", 30))
        self._stop_event(event)

    @filter.regex(r'^\s*(开启监控坊市|关闭监控坊市)\s*$')
    async def toggle_monitor_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        enable = "开启" in event.message_str
        self.config['monitor_enabled'] = enable
        self.config.setdefault('modules', {})['market_monitor'] = enable
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(
            event, f"✅ 监控已{'开启' if enable else '关闭'}。模块【market_monitor】已同步{'开启' if enable else '关闭'}。", 30))
        self._stop_event(event)

    @filter.regex(r'^\s*开启此群通知\s*$')
    async def enable_notify_group(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        gid = str(event.get_group_id())
        groups = self.config.setdefault('monitor_notify_groups', [])
        if gid not in groups:
            groups.append(gid)
            await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(event, '✅ 已将本群加入坊市监控通知广播列表。', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*设置监控触发群\s*$')
    async def set_trigger_group(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        self.config['monitor_trigger_group'] = str(event.get_group_id())
        self.client = event.bot
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(event, '✅ 已将本群设置为监控探测指令的主发送群。', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*开启自动坊市\s*$')
    async def bind_market_group(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        self.target_group = str(event.get_group_id())
        self.client = event.bot
        self.config['target_group'] = self.target_group
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(event, '✅ 成功绑定本群为坊市爬虫主群!', 30))
        self._stop_event(event)

    @filter.regex(r'^\s*采集坊市\s*$')
    async def trigger_now(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        self.target_group = str(event.get_group_id())
        self.client = event.bot
        self.config['target_group'] = self.target_group
        await self._save_config_async()
        if self.is_scraping:
            asyncio.create_task(self._send_and_recall_universal(event, '⚠️ 爬虫已在运行中。', 30))
        else:
            asyncio.create_task(self._send_and_recall_universal(event, '🚀 立刻启动全自动采集...', 30))
            asyncio.create_task(self._start_scraping())
        self._stop_event(event)

    @filter.regex(r'^\s*(坊市网络状态|价格上传状态|坊市上传状态)\s*$')
    async def network_market_status_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        cfg = self._network_market_cfg()
        payload = self._build_network_market_payload()
        export_path = self._resolve_plugin_path(str(cfg.get("local_export_path") or "data/xiao_xiuxian_market_prices.json"))
        api_key_text = "已配置" if str(cfg.get("api_key") or "").strip() else "未配置"
        lines = [
            "🌐 【坊市价格网络共享状态】",
            f"网络上传：{'✅开启' if cfg.get('enabled') else '🛑关闭'}",
            f"上传地址：{cfg.get('upload_url')}",
            f"上传密钥：{api_key_text}",
            f"本地导出：{'✅开启' if cfg.get('local_export_enabled', True) else '🛑关闭'}",
            f"导出路径：{export_path}",
            f"当前可上传价格：{len(payload.get('items', {}) or {})} 条",
            f"最近上传时间：{self._format_upload_ts(self.last_market_upload_ts)}",
            f"最近上传结果：{'成功' if self.last_market_upload_ok else '未成功'}",
            f"最近上传数量：{self.last_market_upload_count} 条",
            f"最近返回：{self.last_market_upload_msg}",
            "",
            "用法：",
            "开启坊市网络 / 关闭坊市网络",
            "设置坊市上传地址 https://example.com/api/prices/bulk",
            "设置坊市上传密钥 你的上传密钥",
            "上传坊市价格",
        ]
        asyncio.create_task(self._send_and_recall_universal(event, "\n".join(lines), 60))
        self._stop_event(event)

    @filter.regex(r'^\s*(开启坊市网络|关闭坊市网络)\s*$')
    async def toggle_network_market_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        enable = event.message_str.strip() == "开启坊市网络"
        self.config.setdefault("network_market", {})["enabled"] = enable
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(
            event, f"{'✅' if enable else '🛑'} 坊市价格网络上传已{'开启' if enable else '关闭'}。", 30))
        self._stop_event(event)

    @filter.regex(r'^\s*设置坊市上传地址\s+(.+)$')
    async def set_network_market_url_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        url = event.message_str.replace("设置坊市上传地址", "", 1).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            asyncio.create_task(self._send_and_recall_universal(event, "❌ 上传地址必须以 http:// 或 https:// 开头。", 30))
            self._stop_event(event)
            return
        self.config.setdefault("network_market", {})["upload_url"] = url
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(event, f"✅ 已设置坊市上传地址：{url}", 30))
        self._stop_event(event)

    @filter.regex(r'^\s*设置坊市上传密钥\s+(.+)$')
    async def set_network_market_key_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        api_key = event.message_str.replace("设置坊市上传密钥", "", 1).strip()
        self.config.setdefault("network_market", {})["api_key"] = api_key
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(event, "✅ 已设置坊市上传密钥。为避免泄露，状态页只显示是否已配置。", 30))
        self._stop_event(event)

    @filter.regex(r'^\s*(上传坊市价格|手动上传坊市价格)\s*$')
    async def upload_market_prices_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        await self._send_and_recall_universal(event, "⏳ 正在上传坊市价格...", 10)
        ok, msg, count = await self._upload_market_prices_network(force=True)
        status = "✅ 上传成功" if ok else "⚠️ 上传未成功"
        tip = (
            f"{status}\n"
            f"价格数量：{count} 条\n"
            f"返回信息：{msg}"
        )
        asyncio.create_task(self._send_and_recall_universal(event, tip, 60))
        self._stop_event(event)


    @filter.regex(r"^\s*(开启模块|关闭模块)\s+(\S+)\s*$")
    async def toggle_module_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        m = re.match(r"^\s*(开启模块|关闭模块)\s+(\S+)\s*$", event.message_str.strip())
        if not m:
            self._stop_event(event)
            return
        action = m.group(1)
        raw_alias = m.group(2).strip()
        key = self.MODULE_ALIASES.get(raw_alias.lower()) or self.MODULE_ALIASES.get(raw_alias)
        if not key:
            valid = "、".join(sorted(set(self.MODULE_ALIASES.values())))
            asyncio.create_task(self._send_and_recall_universal(
                event, f"❌ 未知模块『{raw_alias}』\n可用模块：{valid}\n别名：修仙/炼金/上架/爬虫/监控", 30))
            self._stop_event(event)
            return
        enable = (action == "开启模块")
        self.config.setdefault("modules", {})[key] = enable
        await self._save_config_async()
        asyncio.create_task(self._send_and_recall_universal(
            event, f"{'✅' if enable else '🛑'} 模块【{key}】已{'开启' if enable else '关闭'}", 30))
        self._stop_event(event)

    @filter.regex(r"^\s*模块状态\s*$")
    async def module_status_cmd(self, event: AstrMessageEvent):
        if self._blacklist_blocks_event(event): return
        if not self._is_admin(event): return
        modules = self.config.get("modules", {})
        labels = {
            "xiuxian": "修仙(悬赏/秘境/灵田/猜成语)",
            "alchemy": "炼金/一键上架",
            "market_spider": "坊市定时爬虫",
            "market_monitor": "坊市稀有物品监控",
        }
        lines = ["📊 子模块开关状态："]
        for key, label in labels.items():
            state = "✅开启" if modules.get(key, True) else "🛑关闭"
            lines.append(f"• {label}: {state}")
        lines.append("")
        lines.append("💡 用法：")
        lines.append("  开启模块 修仙 / 关闭模块 监控")
        lines.append("  支持别名: 修仙/炼金/上架/爬虫/监控")
        asyncio.create_task(self._send_and_recall_universal(event, "\n".join(lines), 30))
        self._stop_event(event)

    async def terminate(self):
        """插件卸载/重载时取消后台任务，避免重复定时循环。"""
        tasks = []
        for task in [getattr(self, 'bg_task', None), getattr(self, 'monitor_task', None), getattr(self, 'timeout_task', None)]:
            if task and not task.done():
                task.cancel()
                tasks.append(task)

        for task in list(getattr(self, 'task_runners', {}).values()):
            if task and not task.done():
                task.cancel()
                tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info('[大一统] 插件后台任务已清理')
