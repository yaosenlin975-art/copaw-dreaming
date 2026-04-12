# 🔨 copaw-plugin-forge

> **QwenPaw 插件锻造厂** — 让 Agent 自主创建、验证、部署插件

[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/...)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-yellow)](https://python.org)

## 它是什么？

`copaw-plugin-forge` 是一个 **QwenPaw Skill + Plugin 双模式技能**，赋予 QwenPaw AI Agent 完整的插件工程能力：

| 能力 | 说明 |
|------|------|
| 🏗️ **从模板生成** | 4 种内置模板（Cron / Channel / Provider / Tool），填参数即出完整插件 |
| 🔍 **静态四层校验** | JSON 格式 → Python AST → 安全扫描 → API 合规性，层层把关 |
| 🧪 **运行时验证** | importlib 模拟加载 + MockApi 调用追踪 + QwenPaw 日志扫描 |
| 📋 **状态管理** | 已安装插件列表、一键验证报告 |

## 快速开始

### 前提条件

- QwenPaw v1.1.0+ (或 CoPaw 兼容版本)
- Python 3.10+

### 安装部署

本技能已包含在 `skill_pool` 和 `plugins` 目录中。确保：

```
~/.copaw/plugins/copaw-plugin-forge/
├── plugin.json
├── plugin.py
└── scripts/
    └── ...

~/.copaw/skill_pool/copaw-plugin-forge/
├── SKILL.md
└── scripts/ ...
```

重启 QwenPaw 后生效。

### 使用示例

#### 创建定时任务插件

```bash
/forge create cron-job \
  --id=daily-backup \
  --name="每日备份" \
  --desc="每天凌晨3点执行工作区备份" \
  --schedule="0 3 * * *" \
  --task-text="备份 ~/.copaw/workspaces/default/ 到 backup/"
```

#### 验证插件

```bash
# 静态校验
/forge validate daily-backup

# 运行时全链路验证（需先重启 QwenPaw）
/forge verify daily-backup
```

#### 列出可用模板和已安装插件

```bash
/forge list-templates
/forge status
```

## 架构设计

```
┌─────────────────────────────────────────────┐
│              用户 / Agent 输入               │
│         "帮我做一个 XX 插件"                 │
└─────────────┬───────────────────────────────┘
              │ 触发 SKILL.md SOP
              ▼
┌─────────────────────────────────────────────┐
│          Phase 1: FORGE (锻造)              │
│                                             │
│  PluginScaffolder                           │
│  ├─ 选择模板 (4种 + free)                   │
│  ├─ 填充变量 (${PLUGIN_ID}, ${NAME} ...)     │
│  └─ 写入 plugins/<id>/                      │
└─────────────┬───────────────────────────────┘
              │ 自动进入 Phase 2
              ▼
┌─────────────────────────────────────────────┐
│        Phase 2: VALIDATE (静态校验)          │
│                                             │
│  PluginValidator                            │
│  ├─ Layer 1: JSON 校验 (格式+字段+schema)   │
│  ├─ Layer 2: AST 校验 (语法+结构)           │
│  ├─ Layer 3: 安全扫描 (危险代码/密钥/路径)   │
│  └─ Layer 4: API 合规 (调用签名+一致性)      │
└─────────────┬───────────────────────────────┘
              │ 可选 Phase 3
              ▼
┌─────────────────────────────────────────────┐
│       Phase 3: VERIFY (运行时验证)           │
│                                             │
│  PluginVerifier                             │
│  ├─ Step A: importlib 模拟加载              │
│  │   ├─ MockApi 记录所有 api.*() 调用       │
│  │   └─ 确认无异常崩溃                       │
│  ├─ Step B: 目录发现检查                    │
│  └─ Step C: 日志扫描 (errors/warnings)      │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│            📋 Markdown 报告                  │
│   验证通过 ✅ 或 问题清单 + 修复建议 ❌       │
└─────────────────────────────────────────────┘
```

## 四种模板详解

### `cron-job` 定时任务

最适合：自动化运维场景。

生成的 plugin.py 会注册 `startup_hook` 并在回调中通过 CronManager 创建定时任务。

**默认配置**：
- Schedule: `0 2 * * *`（凌晨2点）
- Task type: `agent`
- Priority: 中等

### `channel-bridge` 渠道桥接

最适合：接入新的 IM/通知渠道。

生成的 plugin.py 注册 `startup_hook`，初始化渠道适配器。

**扩展点**: 需要实现消息收发、格式转换逻辑。

### `provider-extender` Provider 扩展

最适合：对接私有 LLM 服务。

生成的文件包含完整的 Provider 类骨架和 `register_provider()` 调用。

**扩展点**: 需要实现 chat/completion/embedding 接口。

### `tool-extension` 工具扩展

最适合：为 Agent 添加新能力。

生成的文件包含工具处理器骨架和 `register_control_command()` 调用。

**扩展点**: 工具的具体执行逻辑。

## 文件说明

| 文件 | 大小 | 用途 |
|------|------|------|
| **SKILL.md** | ~8KB | Skill 定义文档（SOP + 模板说明 + 使用指南）|
| **plugin.json** | ~1KB | QwenPaw Plugin 清单 |
| **plugin.py** | ~7KB | Plugin 入口（命令分发器 + /forge 命令）|
| **scripts/plugin_templates.py** | ~20KB | 4 种模板定义 + Template 数据类 |
| **scripts/plugin_scaffolder.py** | ~12KB | 脚手架生成引擎 |
| **scripts/plugin_validator.py** | ~28KB | 四层静态验证器 |
| **scripts/plugin_verifier.py** | ~18KB | 运行时验证器 |

## 安全模型

### 静态安全扫描规则

| 类别 | 检测内容 | 默认级别 |
|------|---------|---------|
| 危险函数 | os.system, eval, exec, subprocess.call 等 | WARNING |
| 硬编码凭证 | API Key, password, token, Base64 长串 | ERROR |
| 路径穿越 | `../` 模式 | WARNING |
| 废弃模块 | optparse, imp, parser | WARNING |

### 写入策略

- 所有写入操作前会确认目标目录为 `plugins/` 下
- 生成的文件不会覆盖已有文件（除非用户明确要求）
- 验证阶段只读不写

## 开发指南

### 扩展模板

编辑 `scripts/plugin_templates.py`:

1. 定义 `PluginTemplate` 实例
2. 实现 `render(params)` 方法返回 `{filename: content}`
3. 注册到 `TEMPLATE_REGISTRY` 字典

### 扩展安全规则

编辑 `scripts/plugin_validator.py`:
- `DANGEROUS_IMPORTS`: 添加危险导入检测模式
- `SECRET_PATTERNS`: 添加密钥匹配正则
- `PATH_TRAVERSAL_PATTERNS`: 添加路径穿越模式

### 扩展 API 合规检查

编辑 `PluginValidator.VALID_API_METHODS` 集合和 `_check_api_compliance()` 方法。

## License

MIT
