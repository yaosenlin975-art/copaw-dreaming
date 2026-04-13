# 🌙 copaw-dreaming — Dreaming Memory Consolidation

> 💡 Switch language: [中文](./README.md)

> *"Not all memories deserve to be kept, but the important ones shouldn't be forgotten."*

Inspired by [OpenClaw](https://github.com/openclaw)'s Dreaming feature, this plugin provides automated memory consolidation for **QwenPaw / CoPaw** personal AI assistant workstations.

## ✨ Features

- **Three-Phase Sleep Model**: Light Sleep (scan) → REM (score+associate) → Deep Sleep (write+archive)
- **Six-Signal Scoring Engine**: Relevance, Frequency, Query Diversity, Recency, Consolidation, Concept Richness
- **Triple Threshold Filtering**: Must pass all three (score/recall count/unique queries) to consolidate
- **Hybrid Mode**: Works as both Skill (Agent executes directly) and Plugin (background daemon)
- **Atomic Write Safety**: Temp file + rename to prevent corruption
- **Dry-run Mode**: Simulate execution without modifying files

## 📁 File Structure

```
copaw-dreaming/
├── SKILL.md                  # Skill definition & SOP documentation
├── README.md                 # 中文文档
├── README.en.md              # ← This file
├── plugin.json               # QwenPaw plugin manifest
├── plugin.py                 # Plugin entry (register(api))
├── scripts/
│   ├── __init__.py           # Package init
│   ├── dreaming_config.py    # Configuration model
│   ├── scoring_engine.py     # Six-signal scoring engine
│   └── dreaming_daemon.py    # Core daemon (three-phase pipeline)
└── tests/                    # Test cases (TODO)
```

## 🚀 Quick Start

### Option 1: Skill Mode (Ready to Use)

No installation needed. Just tell the Agent to read `SKILL.md` and follow the SOP:

> "Run a dreaming memory consolidation for me"

The Agent will:
1. Read all daily notes under `.workbuddy/memory/`
2. Run the six-signal scoring engine
3. Process through the three-phase pipeline
4. Update MEMORY.md
5. Generate a consolidation report

### Option 2: Plugin Mode (Requires QwenPaw v1.1.0+)

Deploy this directory as a QwenPaw plugin:

```bash
# 1. Copy plugin to QwenPaw plugins directory
cp -r copaw-dreaming ~/.qwenpaw/plugins/copaw-dreaming/

# 2. Restart QwenPaw (or use CLI to reload)
qwenpaw restart

# Plugin auto-loads and registers startup hook
```

Available control commands:
```
/dreaming status         # View status
/dreaming run            # Manual execution
/dreaming config show    # View configuration
```

## ⚙️ Configuration

### Default Configuration (Can be overridden via plugin.json)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `thresholds.min_score` | 0.8 | Minimum composite score |
| `thresholds.min_recall_count` | 3 | Minimum recall count |
| `thresholds.min_unique_queries` | 3 | Minimum unique queries |
| `schedule.cron_expression` | `0 2 * * *` | Cron expression (2 AM daily) |
| `schedule.timezone` | `Asia/Shanghai` | Timezone |
| `light_sleep.max_memory_age_days` | 30 | Only process memories within N days |
| `deep_sleep.archive_threshold_days` | 90 | Archive after N days |
| `dry_run` | false | Simulation mode |

### Signal Weights

| Signal | Weight | Description |
|--------|--------|-------------|
| relevance | 0.30 | Match with user's core interests |
| frequency | 0.24 | Number of times memory was recalled |
| query_diversity | 0.15 | Different queries that triggered this memory |
| recency | 0.15 | Freshness of last update |
| consolidation | 0.10 | Degree of being referenced/linked |
| concept_richness | 0.06 | Concept density within content |

## 🔧 Architecture

### Three-Phase Pipeline

```
┌──────────┐    ┌──────────┐    ┌──────────┐
│   Light  │ →  │   REM    │ →  │   Deep   │
│   Sleep  │    │   Sleep  │    │   Sleep  │
├──────────┤    ├──────────┤    ├──────────┤
│  Scan    │    │ Score+   │    │  Write+  │
│  memory  │    │ Associate│    │  Archive │
│  collect │    │ generate │    │  cleanup │
│  signals │    │ insights │    │  rebuild │
└──────────┘    └──────────┘    └──────────┘
   Phase 1        Phase 2         Phase 3
```

### Data Flow

```
memory/YYYY-MM-DD.md ──→ ScoringEngine ──→ Pass threshold?
        ↓                      ↓              ↓
  Parse/extract            Six-dimension    ├─ Yes → MEMORY.md (append)
  features                 scoring          └─ No → archive/ (archive)
                                                    ↓
                                          .dreaming_state.json (update)
                                                    ↓
                                          reports/dreaming_report_*.md
```

## 🔌 Plugin API Integration

Based on QwenPaw v1.1.0 actual scan verification:

| API Method | Purpose |
|------------|---------|
| `api.register_startup_hook()` | Initialize daemon on startup |
| `api.register_shutdown_hook()` | Cleanup resources on shutdown |
| `api.runtime.log_info/error/debug()` | Log output |

## 🛡️ Security Boundaries

- **MEMORY.md**: Append/update only, never delete non-archived entries
- **Daily notes**: Read-only, don't modify original records
- **Archive**: Move instead of delete (shutil.move)
- **State file**: Atomic write (write-to-temp + rename)
- **Default read-only**: dry_run=true only analyzes, doesn't write

## 📄 License

MIT License

## 🙏 Acknowledgments

- [OpenClaw](https://github.com/openclaw) — Inspiration for the Dreaming system
- [QwenPaw](https://github.com) — Plugin system infrastructure
