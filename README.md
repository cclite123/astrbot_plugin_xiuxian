# 修仙辅助与坊市监控大一统插件

[![AstrBot Plugin](https://img.shields.io/badge/AstrBot-Plugin-blue.svg)](https://github.com/Soulter/AstrBot)
[![Version](https://img.shields.io/badge/version-3.2.6-green.svg)](./metadata.yaml)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

一款功能齐全的 AstrBot 修仙辅助插件，集成悬赏令解析、秘境/灵田提醒、坊市价格采集、稀有物品监控、一键上架/炼金、猜成语等能力。

---

## 功能介绍

### 1. 悬赏令助手
- 自动解析官方 bot 发送的悬赏令列表
- 智能计算每条悬赏令的**坊市价值**、**炼金价值**与**修为收益**
- 接取成功后自动接管倒计时，到期 @ 提醒
- 支持私聊通知（`开启悬赏私聊` / `关闭悬赏私聊`）
- 同时兼容新版与旧版悬赏令文本格式

### 2. 秘境探索提醒
- 自动识别秘境/万妖之域/东玄域等探索类消息
- 解析探索耗时并设置提醒
- 支持私聊通知

### 3. 灵田收取提醒
- 识别灵药丰收/收获药材确认消息
- 自动设置 47 小时后提醒收取

### 4. 猜成语
- 基于 DeepSeek API 的智能猜成语
- 识别包含「题目」的成语消息，自动回复四字答案

### 5. 炼金 / 一键上架
- 解析背包物品列表
- 自动匹配坊市价格或炼金价格
- 生成一键上架/炼金指令，附带总价值估算
- 自动去重，避免官方 bot 重复回显导致数量翻倍

### 6. 坊市定时爬虫
- 每天定时（3:00 / 9:00 / 15:00 / 21:00）自动采集坊市价格
- 支持手动触发 `采集坊市`
- 分类采集：技能、丹药、装备、药材、道具
- 数据落盘到 `market_data.json`（已被 `.gitignore` 排除）

### 7. 坊市稀有物品监控
- 按配置定时探测指定分类坊市
- 命中监控物品后自动广播通知
- 支持配置监控指令、监控物品、通知群

### 8. 坊市价格网络共享
- 本地导出 `data/xiao_xiuxian_market_prices.json`
- 可选上传至远程价格中心服务
- 配套提供 [market_price_server](./market_price_server) FastAPI 服务端示例

### 9. 黑名单与群开关
- 支持按 QQ 号拉黑，拉黑用户的数据会被自动清理
- 支持按群开启/关闭提醒功能（`开启本群提醒` / `关闭本群提醒`）

---

## 安装方法

### 方式一：从 GitHub 安装（推荐）

在 AstrBot 插件市场中选择「通过 Git 链接安装」，填入：

```
https://github.com/cclite123/astrbot_plugin_xiuxian
```

### 方式二：手动安装

1. 克隆仓库到 AstrBot 插件目录：

```bash
cd /opt/astrbot/data/plugins
git clone https://github.com/cclite123/astrbot_plugin_xiuxian.git
```

2. 重启 AstrBot 加载插件。

3. 复制配置文件模板并修改：

```bash
cp astrbot_plugin_xiuxian/config.example.json astrbot_plugin_xiuxian/config.json
```

---

## 配置文件说明

首次启动会自动生成 `config.json`。若未生成，请复制 `config.example.json` 并修改：

| 配置项 | 说明 |
|--------|------|
| `admin_qq` | 管理员 QQ 号，拥有所有管理指令权限 |
| `official_bot_qq` | 官方修仙 bot 的 QQ 号 |
| `test_mode` | 测试模式开关，开启后管理员可模拟官方 bot 文本进行干运行测试 |
| `deepseek.api_key` | DeepSeek API 密钥，用于猜成语功能 |
| `modules` | 子模块开关：修仙/炼金/爬虫/监控 |
| `target_group` | 坊市爬虫主群 |
| `spider_settings` | 爬虫调度与延迟设置 |
| `network_market` | 坊市价格网络上传配置 |
| `alchemy_target_items` | 炼金目标丹药列表 |
| `alchemy_prices` | 炼金价格表 |
| `monitor_enabled` | 稀有物品监控总开关 |
| `monitor_trigger_group` | 监控探测指令发送群 |
| `monitor_notify_groups` | 命中后通知的群列表 |
| `monitor_items` | 监控物品列表 |
| `monitor_cmds` | 监控探测指令列表 |
| `group_reminder_enabled` | 各群提醒开关 |
| `blacklist_qq` | 黑名单 QQ 列表 |

---

## 管理指令

> 以下指令仅限管理员使用。

### 通用
- `修仙菜单` — 查看管理员菜单
- `开启测试模式` / `关闭测试模式` — 切换测试模式
- `查看所有提醒` — 查看当前运行中的提醒任务

### 模块控制
- `模块状态` — 查看各模块开关
- `开启模块 修仙` / `关闭模块 修仙` — 模块别名：修仙/炼金/上架/爬虫/监控

### 坊市采集
- `开启自动坊市` — 绑定当前群为坊市采集主群
- `采集坊市` — 立即触发全量采集
- `上传坊市价格` — 手动上传价格到网络中心
- `坊市网络状态` — 查看网络上传配置与最近结果
- `开启坊市网络` / `关闭坊市网络`
- `设置坊市上传地址 <URL>`
- `设置坊市上传密钥 <密钥>`

### 坊市监控
- `开启监控坊市` / `关闭监控坊市`
- `设置监控触发群` — 将当前群设为探测指令发送群
- `开启此群通知` — 将当前群加入通知广播列表
- `添加监控指令 <指令>`
- `删除监控指令 <指令>`
- `添加监控物品 <物品名>`
- `删除监控物品 <物品名>`

### 提醒设置
- `开启悬赏私聊` / `关闭悬赏私聊`
- `开启秘境私聊` / `关闭秘境私聊`
- `开启灵田私聊` / `关闭灵田私聊`
- `开启本群提醒` / `关闭本群提醒`

### 价格配置
- `设置炼金价格 <物品名> <价格>万`

### 黑名单
- `加黑QQ号 <QQ号>`

---

## 依赖说明

- Python >= 3.9
- `openai>=1.0.0`（用于猜成语功能）
- AstrBot 框架本体（自带 `aiocqhttp` 等依赖）

安装依赖：

```bash
pip install -r requirements.txt
```

---

## 项目结构

```
.
├── main.py                      # 插件主入口
├── metadata.yaml                # 插件元数据
├── config.example.json          # 配置模板
├── requirements.txt             # 依赖声明
├── README.md                    # 本文件
├── .gitignore                   # Git 排除规则
└── market_price_server/         # 坊市价格中心服务端示例
    ├── server.py
    ├── uploader_example.py
    └── README.md
```

---

## 注意事项

1. **不要直接修改 `config.json` 后提交 Git**，该文件已被 `.gitignore` 排除。请修改 `config.example.json` 作为模板。
2. 运行时生成的 `pm_prefs.json`、`tasks.json`、`market_data.json`、`data/` 目录均不会被 Git 跟踪。
3. 服务器部署时建议使用 `scp` 上传源码文件，保留服务器上的运行时 JSON 数据不被覆盖。
4. 开启 `test_mode` 后，管理员发送的类官方 bot 文本会以干运行方式进入处理器，不会写入正式数据或创建正式任务。

---

## 开源协议

MIT License

---

## 更新日志

### v3.2.6
- 统一插件版本号
- 完善 `metadata.yaml`、`requirements.txt`、`.gitignore`
- 补充 README 文档
- 优化 JSON 加载/保存的异常日志
- 清理 `config.example.json` 中的真实密钥与账号
