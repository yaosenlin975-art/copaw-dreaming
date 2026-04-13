---
name: copaw_dreaming
description: "梦境记忆整合 - 受 OpenClaw Dreaming 启发的三阶段记忆巩固系统。通过浅睡/REM/深睡流水线，自动评分、筛选、沉淀高价值记忆到长期存储。"
metadata:
  copaw:
    emoji: "🌙"
  skill_version: "0.1.0"
  author: "CoPaw Community"
  hybrid_mode: true          # 同时支持 Skill 和 Plugin 模式
  plugin_ready: true           # 已包含 Plugin 基础设施
  references:
    - "OpenClaw Dreaming System"
    - "QwenPaw Plugin API v1"
    - "ReMeLight Memory Manager"
---

# 🌙 梦境记忆整合 (Dreaming Memory Consolidation)

> **"不是所有记忆都值得保留，但重要的不该被遗忘。"**
>
> 灵感来自 OpenClaw 的 Dreaming 功能，为 CoPaw/QwenPaw 提供自动化的记忆巩固能力。

## 什么时候用

当用户提到以下意图时触发：

- "运行梦境"/"开始 dreaming"/"执行记忆整合"
- "帮我整理一下记忆"/"记忆太多了，精简一下"
- "哪些记忆是重要的"/"评估我的记忆价值"
- "把短期记忆沉淀到长期存储"
- "配置 dreaming"/"调整梦境参数"

## 核心概念

### 三阶段睡眠模型

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
```

### 六维评分信号

| 信号 | 权重 | 说明 |
|------|------|------|
| **相关性 (relevance)** | 0.30 | 与用户核心兴趣的匹配度 |
| **频率 (frequency)** | 0.24 | 记忆被召回的次数 |
| **查询多样性 (query_diversity)** | 0.15 | 触发该记忆的不同查询数量 |
| **时效性 (recency)** | 0.15 | 最后更新时间的新鲜度 |
| **整合度 (consolidation)** | 0.10 | 已被引用/关联的程度 |
| **概念丰富度 (concept_richness)** | 0.06 | 包含的概念密度 |

### 三重门槛

必须**同时满足**以下三个条件才能进入长期巩固：

- **综合得分** ≥ `min_score`（默认 0.8）
- **召回次数** ≥ `min_recall_count`（默认 3）
- **独立查询数** ≥ `min_unique_queries`（默认 3）

---

## 使用方式

### 方式一：Skill 模式（立即可用）

直接让 Agent 按照 SOP 执行：

> "帮我运行一次梦境记忆整合"

Agent 会：
1. 读取 `.workbuddy/memory/` 下所有日记文件
2. 运行六信号评分引擎
3. 按三阶段流程处理记忆
4. 生成整合报告
5. 更新 MEMORY.md

### 方式二：Plugin 模式（需要 QwenPaw）

将本 skill 目录部署为 QwenPaw 插件后获得：

- **后台守护进程**：定时自动执行 dreaming
- **Cron 集成**：通过 APScheduler 调度
- **控制命令**：`/dreaming status`、`/dreaming run`、`/dreaming config`
- **Hook 注入**：在 memory_search 时追踪召回次数
- **Startup Hook**：QwenPaw 启动时自动初始化 daemon

---

## 配置参数

### 默认配置 (`dreaming_config.py`)

```python
DREAMING_CONFIG = {
    # 三重门槛
    "min_score": 0.8,            # 最低综合得分
    "min_recall_count": 3,       # 最少召回次数
    "min_unique_queries": 3,     # 最少独立查询数

    # 阶段配置
    "light_sleep": {
        "max_memory_age_days": 30,   # 只处理30天内的记忆
        "scan_batch_size": 50,       # 每批扫描数量
    },
    "rem_sleep": {
        "max_candidates": 20,        # REM阶段最多处理候选
        "association_depth": 2,      # 联想深度
    },
    "deep_sleep": {
        "archive_threshold_days": 90,  # 超过此天数的记忆归档
        "max_consolidations_per_run": 10,  # 每次最多巩固数
    },

    # 调度
    "schedule": {
        "cron_expression": "0 2 * * *",  # 每天凌晨2点
        "timezone": "Asia/Shanghai",
        "enabled": True,
    },

    # 路径
    "memory_dir": ".workbuddy/memory",
    "long_term_file": "MEMORY.md",
    "archive_dir": ".workbuddy/memory/archive",
    "state_file": ".workbuddy/memory/.dreaming_state.json",

    # 信号权重
    "weights": {
        "relevance": 0.30,
        "frequency": 0.24,
        "query_diversity": 0.15,
        "recency": 0.15,
        "consolidation": 0.10,
        "concept_richness": 0.06,
    }
}
```

---

## Skill 模式 SOP（Agent 执行指南）

### 前置检查

1. **确认 memory 目录存在**：检查 `{workspace}/.workbuddy/memory/`
2. **确认有可处理的记忆**：至少存在一个日期文件或 MEMORY.md
3. **加载配置**：读取 `dreaming_config.py` 中的默认配置，允许用户覆盖

### Phase 0: 准备 (Preparation)

```
输入: workspace memory 目录
输出: 原始记忆列表 + 元数据
动作:
  1. 列出 memory/ 下所有 .md 文件
  2. 解析每个文件的时间戳、大小、段落数
  3. 读取 .dreaming_state.json（如果存在）获取历史状态
  4. 过滤掉超过 max_memory_age_days 的文件
  5. 输出: memory_inventory = [{file, date, size, paragraphs, last_modified}]
```

### Phase 1: 浅睡 (Light Sleep) — 记忆扫描

```
输入: memory_inventory
输出: 候选记忆列表 + 初始信号收集
动作:
  1. 逐文件读取内容
  2. 对每个记忆段落提取:
     - 关键词/实体
     - 时间标记
     - 引用关系（提到其他记忆）
     - 概念标签
  3. 计算初始分数:
     - recency 分数（基于日期衰减）
     - concept_richness 分数（关键词密度）
  4. 过滤: 排除明显低价值的条目（纯操作日志等）
  5. 输出: candidates = [{content, signals, initial_score}]
```

### Phase 2: REM Sleep — 评分与联想

```
输入: candidates + weights
_output: 排序后的高分记忆 + 洞察
动作:
  1. 运行完整六信号评分:
     - relevance: 与用户画像/核心兴趣匹配度（需用户上下文）
     - frequency: 从 state 文件读历史召回计数
     - query_diversity: 不同查询触发的次数
     - consolidation: 被其他记忆引用的次数
  2. 加权求和得到 final_score
  3. 应用三重门槛过滤
  4. 对通过的记忆进行跨主题联想:
     - 找出语义相近但不直接关联的记忆对
     - 生成"洞察"（insights）
  5. 排序并截断到 max_candidates
  6. 输出: scored_memories = [...], insights = [...]
```

### Phase 3: 深睡 (Deep Sleep) — 巩固与归档

```
输入: scored_memories (通过门槛的)
输出: 更新后的 MEMORY.md + 归档报告
动作:
  1. 将高分记忆写入/更新到 MEMORY.md:
     - 去重合并
     - 保持结构化格式
     - 标记最后巩固时间
  2. 归档过时记忆:
     - 移动超过 archive_threshold_days 的条目到 archive/
     - 在源文件中保留指针
  3. 更新 .dreaming_state.json:
     - 更新召回计数
     - 记录本次执行时间戳
     - 保存 insights
  4. 清理: 删除空文件、修复孤立引用
  5. 输出: consolidation_report
```

### 最终产出

生成以下结构的报告：

```markdown
# 🌙 梦境报告 - {timestamp}

## 概览
- 处理记忆总数: N
- 通过门槛: M
- 已巩固: K
- 已归档: L
- 生成洞察: P

## 高分记忆 TOP 5
| 排名 | 记忆摘要 | 综合分 | 主要信号 |
|------|---------|--------|----------|
| 1 | ... | 0.92 | relevance↑ frequency↑ |
| ... | ... | ... | ... |

## 新生洞察
1. ...
2. ...

## 归档清单
- [2026-01-15.md] → archive/ (超期90天)
- ...

## 下次建议
- 关注领域 X 的记忆积累
- 条目 Y 即将达到归档阈值
```

---

## 文件结构

```
copaw-dreaming/
├── SKILL.md                  # ← 本文件，Skill 定义
├── README.md                 # 架构说明与使用文档
├── plugin.json               # QwenPaw 插件清单
├── plugin.py                 # Plugin 入口 (register(api))
├── scripts/
│   ├── __init__.py
│   ├── dreaming_config.py    # 配置模型与默认值
│   ├── scoring_engine.py     # 六信号评分引擎
│   ├── dreaming_daemon.py    # 核心守护进程 (三阶段流水线)
│   ├── memory_scanner.py     # 记忆扫描器 (浅睡)
│   ├── insight_generator.py  # 洞察生成器 (REM)
│   └── consolidator.py       # 巩固器 (深睡)
└── tests/
    ├── test_scoring_engine.py
    └── test_dreaming_pipeline.py
```

---

## 从 Skill 到 Plugin 的迁移路径

| 能力 | Skill 模式 | Plugin 模式 | 差异 |
|------|-----------|------------|------|
| 触发方式 | 用户指令 | 定时 + 手动 | Cron 集成 |
| 执行者 | Agent 本身 | 后台守护进程 | 异步非阻塞 |
| 召回追踪 | 估算值 | Hook 实时统计 | 精确计数 |
| 状态持久化 | JSON 文件 | JSON + Registry | 可被其他插件查询 |
| 控制接口 | 自然语言 | `/dreaming` 命令 | 结构化交互 |

### 升级步骤

1. ✅ 完成 Skill MVP（当前阶段）
2. ✅ 包含 `plugin.json` + `plugin.py`（已就绪）
3. 复制到 `~/.qwenpaw/plugins/copaw-dreaming/`
4. 重启 QwenPaw，Plugin 自动加载
5. Daemon 通过 `register_startup_hook()` 启动

---

## 安全边界

### 写入规则
- **MEMORY.md**: 仅追加/更新，不删除未归档条目
- **日记文件**: 只读，不修改原始记录
- **Archive**: 移动而非删除
- **State file**: 原子写入（write-to-temp + rename）

### 默认只读
- 生成诊断报告和评分分析
- 列出即将归档的记忆
- 模拟运行（dry-run 模式）

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0 | 2026-04-12 | 初始版本，混合模式（Skill + Plugin 底子） |
