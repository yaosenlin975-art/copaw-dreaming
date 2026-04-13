# 🌙 copaw-dreaming — 梦境记忆整合插件

> **"不是所有记忆都值得保留，但重要的不该被遗忘。"**

受 [OpenClaw](https://github.com/openclaw) Dreaming 功能启发，为 **QwenPaw / CoPaw** 个人 AI 助手工作站提供自动化的记忆巩固能力。

## ✨ 特性

- **三阶段睡眠模型**：浅睡（扫描）→ REM（评分+联想）→ 深睡（写入+归档）
- **六信号评分引擎**：相关性、频率、查询多样性、时效性、整合度、概念丰富度
- **三重门槛过滤**：同时满足分数/召回次数/独立查询数才通过
- **混合模式**：既可作为 Skill（Agent 直接执行），也可作为 Plugin（后台守护进程）
- **原子写入安全**：临时文件 + 重命名，避免写一半损坏
- **dry-run 模式**：模拟运行，不修改任何文件

## 📁 文件结构

```
copaw-dreaming/
├── SKILL.md                  # Skill 定义与 SOP 文档
├── README.md                 # ← 本文件
├── plugin.json               # QwenPaw 插件清单
├── plugin.py                 # Plugin 入口 (register(api))
├── scripts/
│   ├── __init__.py           # 包初始化
│   ├── dreaming_config.py    # 配置模型（dataclass + 验证）
│   ├── scoring_engine.py     # 六信号评分引擎
│   └── dreaming_daemon.py    # 核心守护进程（三阶段流水线）
└── tests/                    # 测试用例（TODO）
```

## 🚀 快速开始

### 方式一：Skill 模式（立即可用）

无需安装任何东西。直接让 Agent 读取 `SKILL.md` 并按 SOP 执行：

> "帮我运行一次梦境记忆整合"

Agent 会：
1. 读取 `.workbuddy/memory/` 下所有日记文件
2. 运行六信号评分引擎
3. 按三阶段流程处理记忆
4. 更新 MEMORY.md
5. 生成整合报告

### 方式二：Plugin 模式（需要 QwenPaw v1.1.0+）

将本目录部署为 QwenPaw 插件：

```bash
# 1. 复制插件到 QwenPaw 插件目录
cp -r copaw-dreaming ~/.qwenpaw/plugins/copaw-dreaming/

# 2. 重启 QwenPaw（或使用 CLI 重新加载）
qwenpaw restart

# 插件会自动加载并注册 startup hook
```

部署后可用控制命令：
```
/dreaming status    # 查看状态
/dreaming run       # 手动执行一次
/dreaming config show  # 查看配置
```

## ⚙️ 配置参数

### 默认配置（可通过 plugin.json 覆盖）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `thresholds.min_score` | 0.8 | 最低综合得分 |
| `thresholds.min_recall_count` | 3 | 最少召回次数 |
| `thresholds.min_unique_queries` | 3 | 最少独立查询数 |
| `schedule.cron_expression` | `0 2 * * *` | Cron 表达式（凌晨2点） |
| `schedule.timezone` | `Asia/Shanghai` | 时区 |
| `light_sleep.max_memory_age_days` | 30 | 只处理 N 天内的记忆 |
| `deep_sleep.archive_threshold_days` | 90 | 超过 N 天归档 |
| `dry_run` | false | 模拟运行模式 |

### 权重配置

| 信号 | 权重 | 说明 |
|------|------|------|
| relevance | 0.30 | 与用户核心兴趣的匹配度 |
| frequency | 0.24 | 记忆被召回的次数 |
| query_diversity | 0.15 | 触发该记忆的不同查询数量 |
| recency | 0.15 | 最后更新时间的新鲜度 |
| consolidation | 0.10 | 已被引用/关联的程度 |
| concept_richness | 0.06 | 包含的概念密度 |

## 🔧 架构设计

### 三阶段流水线

```
┌──────────┐    ┌──────────┐    ┌──────────┐
│ 浅睡      │ →  │ REM      │ →  │ 深睡      │
│ Light     │    │ Sleep    │    │ Deep     │
│ Sleep     │    │          │    │ Sleep    │
├──────────┤    ├──────────┤    ├──────────┤
│ 扫描记忆  │    │ 评分+联想  │    │ 写入+清理  │
│ 收集信号  │    │ 生成洞察  │    │ 归档过期  │
│ 轻量过滤  │    │ 跨主题连接 │    │ 索引重建  │
└──────────┘    └──────────┘    └──────────┘
   Phase 1         Phase 2          Phase 3
```

### 数据流

```
memory/YYYY-MM-DD.md ──→ ScoringEngine ──→ 通过门槛？
        ↓                      ↓              ↓
  解析段落/提取特征         六维评分      ├─ 是 → MEMORY.md (追加)
                                       └─ 否 → archive/ (归档)
                                                    ↓
                                          .dreaming_state.json (更新)
                                                    ↓
                                          reports/dreaming_report_*.md
```

## 🔌 Plugin API 集成

基于 QwenPaw v1.1.0 实际扫描验证的 Plugin API：

| API 方法 | 用途 |
|----------|------|
| `api.register_startup_hook()` | 启动时初始化 daemon |
| `api.register_shutdown_hook()` | 关闭时清理资源 |
| `api.runtime.log_info/error/debug()` | 日志输出 |

### plugin.json 格式

```json
{
  "id": "copaw-dreaming",
  "name": "🌙 Dreaming 记忆整合",
  "version": "0.1.0",
  "entry_point": "plugin.py",
  "capabilities": [
    "memory_consolidation",
    "cron_scheduling",
    "control_command",
    "startup_hook"
  ],
  "config_schema": { ... },
  "permissions": ["memory:read", "memory:write"]
}
```

## 📊 报告样例

每次执行后生成 Markdown 报告：

```markdown
# 🌙 梦境报告 - 2026-04-12T14:30:00Z

## 概览
- 处理记忆总数: **15**
- 通过门槛: **4** (26.7%)
- 未通过: **11**
- 生成洞察: **2**

## 高分记忆 TOP 5
| 排名 | 来源 | 记忆摘要 | 综合分 | 主要信号 |
|------|------|---------|--------|----------|
| 1 | 2026-04-10.md | 用户偏好 Ollama Q4_K_M... | **0.892** | 相关性↑ 频率↑ 时效→ |
...
```

## 🛡️ 安全边界

- **MEMORY.md**: 仅追加/更新，不删除未归档条目
- **日记文件**: 只读，不修改原始记录
- **Archive**: 移动而非删除（shutil.move）
- **State file**: 原子写入（write-to-temp + rename）
- **默认只读**: dry_run=true 时仅分析不写入

## 📋 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0 | 2026-04-12 | 初始版本：三阶段流水线 + 六信号评分 + Plugin API v1 |

## 📄 许可证

MIT License

## 🙏 致谢

- [OpenClaw](https://github.com/openclaw) — Dreaming 系统灵感来源
- [QwenPaw](https://github.com) — 插件系统基础架构
