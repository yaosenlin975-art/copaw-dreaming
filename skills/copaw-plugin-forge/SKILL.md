---
name: copaw-plugin-forge
description: "QwenPaw 插件锻造厂 - 从零创建、验证、部署 QwenPaw 插件的完整工具链"
metadata: {
  "copaw": {
    "emoji": "🔨",
    "requires": {}
  },
  "skill_version": "1.0.0"
}
---

# 🔨 Plugin Forge — QwenPaw 插件锻造厂

> **版本**: 1.0.0 | **许可**: MIT

让 QwenPaw 内部的 AI Agent（或人类用户）从零创建、验证、部署 QwenPaw 插件的完整工具链。

## 核心能力

| 能力 | 说明 |
|------|------|
| 🔧 **脚手架生成** | 从 4 种模板一键生成完整插件骨架 |
| 🔍 **静态四层校验** | JSON 格式 + Python AST + 安全扫描 + API 合规性 |
| 🧪 **运行时验证** | importlib 模拟加载 + MockApi 调用 + 日志扫描 |
| 📋 **状态管理** | 查看已安装插件列表和详情 |

## 快速开始

### 1. 创建插件（从模板）

```
/forge create cron-job --id=my-timer --name="定时清理" --desc="每天凌晨3点清理缓存"
/forge create tool-extension --id=my-tool --name="自定义工具"
/forge create free --id=custom --name="自由模式" --desc="完全自定义"
```

### 2. 验证插件

```bash
# 静态校验（JSON + AST + 安全 + API）
/forge validate my-plugin

# 运行时全链路验证（模拟加载 + 日志）
/forge verify my-plugin
```

### 3. 查看状态

```bash
/forge list-templates    # 列出可用模板
/forge status            # 已安装插件概览
/forge help              # 帮助信息
```

---

## 四种内置模板

### 1. `cron-job` — 定时任务插件

**用途**: 注册 Cron 定时任务，按计划执行 Agent 命令。

**生成的文件**:
```
<plugin-id>/
├── plugin.json    # capabilities: ["cron_scheduling", "startup_hook"]
└── plugin.py      # register_startup_hook → CronManager.create_or_replace_job()
```

**关键参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--schedule` | `"0 2 * * *"` | Cron 表达式 |
| `--task-type` | `"agent"` | 任务类型 |
| `--task-text` | (空) | 执行的命令文本 |

**适用场景**: 自动备份、定期报告、缓存清理、数据同步。

---

### 2. `channel-bridge` — 消息渠道桥接插件

**用途**: 将 QwenPaw 连接到新的消息渠道，处理消息格式转换。

**生成的文件**:
```
<plugin-id>/
├── plugin.json    # capabilities: ["startup_hook"]
└── plugin.py      # register_startup_hook → 渠道适配器初始化
```

**关键参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--channel-name` | (必填) | 目标渠道名 |
| `--message-format` | `"text"` | 支持的消息格式 |

**适用场景**: 自定义 IM 接入、企业内部系统通知、IoT 设备通信。

---

### 3. `provider-extender` — LLM Provider 扩展插件

**用途**: 注册新的 LLM Provider，扩展模型来源（如本地模型、私有 API）。

**生成的文件**:
```
<plugin-id>/
├── plugin.json    # capabilities: ["provider_extension"]
├── plugin.py      # register_provider() → 自定义 Provider 类
└── scripts/
    └── provider_impl.py  # Provider 实现细节
```

**关键参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | (空) | API 端点 |
| `--model-list` | `"[]"` | 可用模型列表 JSON |

**适用场景**: 私有化部署 LLM、本地 Ollama/vLLM 对接、多模型路由。

---

### 4. `tool-extension` — 工具扩展插件

**用途**: 为 QwenPaw Agent 注册新的工具或自定义控制命令。

**生成的文件**:
```
<plugin-id>/
├── plugin.json    # capabilities: ["control_command"]
├── plugin.py      # register_control_command → 工具处理器
└── scripts/
    └── tools.py   # 工具实现
```

**关键参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--command-name` | (必填) | 工具/命令名称 |
| `--requires-perms` | `"[]"` | 权限声明 |

**适用场景**: 自定义搜索、API 调用封装、数据库查询、文件处理工具。

---

### 5. `free` — 空白模板

不包含任何预设逻辑，只提供最基础的 plugin.json 和 plugin.py 骨架。
适合高级用户完全从零构建。

---

## 验证流程详解

### Phase 1: FORGE（锻造）

```
Agent 描述需求
       ↓
选择模板 (cron-job / channel-bridge / provider-extender / tool-extension / free)
       ↓
Scaffolder.fill_template(template_id, params)
       ↓
写入 ~/.copaw/plugins/<plugin-id>/
       ↓
[可选] auto_validate_after_create=True 时自动进入 Phase 2
```

### Phase 2: VALIDATE（静态校验）

四层检查：

| 层级 | 检查内容 | 失败级别 |
|------|---------|---------|
| **JSON 校验** | plugin.json 语法、必填字段、id 格式、version 格式、capabilities/permissions 一致性 | ERROR |
| **AST 校验** | plugin.py 语法、导出 `plugin` 对象、类含 `register()` 方法、方法签名 | ERROR |
| **安全扫描** | 危险导入 (os.system/eval/exec)、硬编码密钥、路径穿越模式 | ERROR/WARNING |
| **API 合规** | api.register_* 方法合法性、hook priority 范围 [0,100]、capabilities 与实际调用一致性 | WARNING |

### Phase 3: VERIFY（运行时验证）

```
Step A: 模拟加载
  ├─ importlib 动态导入 plugin.py
  ├─ 创建 MockApi（记录所有调用）
  ├─ 调用 plugin.register(mock_api)
  └─ 确认：无异常 + api_calls 非空 + runtime_logs 无 error

Step B: 目录发现
  └─ 确认 PluginLoader.discover_plugins() 能找到该目录

Step C: 日志扫描
  ├─ 自动检测 QwenPaw logs/ 目录
  ├─ 搜索 <plugin_id> 相关日志行
  └─ 统计 errors / warnings 数量
```

---

## 文件架构

```
copaw-plugin-forge/
├── SKILL.md                        # 本文件 — Skill 定义 + 使用文档
├── README.md                       # README（GitHub/文档用）
├── plugin.json                     # Plugin 清单
├── plugin.py                       # Plugin 入口 (/forge 命令注册)
└── scripts/
    ├── __init__.py                 # 包标记
    ├── plugin_templates.py         # ★ 4 种模板定义 + Template 数据结构
    ├── plugin_scaffolder.py        # ★ 脚手架生成器（模板填充 → 写入文件）
    ├── plugin_validator.py         # ★ 静态验证器（四层校验）
    └── plugin_verifier.py          # ★ 运行时验证器（模拟加载 + 日志扫描）
```

---

## 在 Agent 对话中使用

当 Agent 收到以下指令时会触发本技能：

> "帮我创建一个 QwenPaw 插件"
> "做一个定时任务插件"
> "我想对接一个新的 LLM 服务商"
> "写一个自定义工具插件"
> "验证一下这个插件能不能用"

**Agent SOP 流程**:

1. **理解需求** → 选择合适模板（或 free）
2. **收集参数** → id/name/description/version/模板特有参数
3. **调用 Scaffolder** → 生成文件到 plugins/
4. **自动 Validate** → 检查四层校验结果
5. **修复问题** → 如有 ERROR 则修复后重新 validate
6. **Verify（可选）** → 模拟加载测试
7. **汇报结果** → 向用户展示创建摘要 + 验证报告

---

## 开发与扩展

### 添加新模板

在 `scripts/plugin_templates.py` 中添加新的 `PluginTemplate` 实例并注册到 `TEMPLATE_REGISTRY`：

```python
from scripts.plugin_templates import PluginTemplate, TEMPLATE_REGISTRY

my_template = PluginTemplate(
    template_id="my-template",
    name="My Template",
    description="描述...",
    category="custom",
    default_capabilities=["startup_hook"],
    files_generated=["plugin.json", "plugin.py"],
)

def _render_my_template(params: Dict[str, Any]) -> Dict[str, str]:
    return {
        "plugin.json": json.dumps({...}, indent=2),
        "plugin.py": '''...${PLUGIN_ID}...''',
    }

my_template.render = _render_my_template
TEMPLATE_REGISTRY["my-template"] = my_template
```

### 自定义安全规则

在 `scripts/plugin_validator.py` 的 `DANGEROUS_IMPORTS` / `SECRET_PATTERNS` 字典中添加规则即可。安全规则是可配置的。

---

## 许可证

MIT License — 自由使用、修改、分发。
