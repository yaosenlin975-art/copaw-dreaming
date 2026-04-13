"""
copaw-dreaming - 配置模型与默认值

定义 dreaming 系统的所有可配置参数，使用 dataclass + 验证。
同时支持 Skill 模式（直接导入）和 Plugin 模式（通过 plugin.json 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SleepPhase(str, Enum):
    """睡眠阶段枚举"""
    LIGHT_SLEEP = "light_sleep"
    REM_SLEEP = "rem_sleep"
    DEEP_SLEEP = "deep_sleep"


@dataclass
class WeightsConfig:
    """六信号权重配置"""
    relevance: float = 0.30
    frequency: float = 0.24
    query_diversity: float = 0.15
    recency: float = 0.15
    consolidation: float = 0.10
    concept_richness: float = 0.06

    def __post_init__(self):
        total = sum([
            self.relevance, self.frequency, self.query_diversity,
            self.recency, self.consolidation, self.concept_richness
        ])
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")

    def as_dict(self) -> Dict[str, float]:
        return {
            "relevance": self.relevance,
            "frequency": self.frequency,
            "query_diversity": self.query_diversity,
            "recency": self.recency,
            "consolidation": self.consolidation,
            "concept_richness": self.concept_richness,
        }


@dataclass
class LightSleepConfig:
    """浅睡阶段配置"""
    max_memory_age_days: int = 30          # 只处理 N 天内的记忆
    scan_batch_size: int = 50              # 每批扫描数量
    min_paragraph_length: int = 10         # 最小段落长度（字符）
    exclude_patterns: List[str] = field(default_factory=lambda: [
        r"^## .*",           # 标题行
        r"^---",             # 分隔线
        r"^\s*$",           # 空行
        r"^\|",             # 表格行
        r"^- \[x\]",       # 已完成 todo（纯操作记录）
    ])


@dataclass
class REMSleepConfig:
    """REM睡眠阶段配置"""
    max_candidates: int = 20               # REM 阶段最多处理候选数
    association_depth: int = 2             # 联想深度（跳数）
    min_insight_score: float = 0.6         # 生成洞察的最低关联分
    cross_topic_threshold: float = 0.4     # 跨主题连接阈值


@dataclass
class DeepSleepConfig:
    """深睡阶段配置"""
    archive_threshold_days: int = 90       # 超过此天数的记忆归档
    max_consolidations_per_run: int = 10   # 每次最多巩固条目数
    keep_recent_versions: int = 3          # 保留最近几个版本
    archive_compress: bool = True          # 是否压缩归档文件


@dataclass
class ScheduleConfig:
    """调度配置"""
    cron_expression: str = "0 2 * * *"     # 默认每天凌晨2点
    timezone: str = "Asia/Shanghai"
    enabled: bool = True


@dataclass
class ThresholdConfig:
    """三重门槛配置"""
    min_score: float = 0.8                 # 最低综合得分
    min_recall_count: int = 3              # 最少召回次数
    min_unique_queries: int = 3            # 最少独立查询数

    def check(self, score: float, recall_count: int, unique_queries: int) -> bool:
        """检查是否满足所有三个门槛"""
        return (
            score >= self.min_score
            and recall_count >= self.min_recall_count
            and unique_queries >= self.min_unique_queries
        )


@dataclass
class PathConfig:
    """路径配置（相对于 workspace root）"""
    memory_dir: str = ".workbuddy/memory"
    long_term_file: str = "MEMORY.md"
    archive_dir: str = ".workbuddy/memory/archive"
    state_file: str = ".workbuddy/memory/.dreaming_state.json"
    report_dir: str = ".workbuddy/memory/reports"

    def resolve(self, workspace_root: Path) -> "ResolvedPaths":
        """将相对路径解析为绝对路径"""
        base = workspace_root / self.memory_dir
        return ResolvedPaths(
            memory_dir=base,
            long_term_file=workspace_root / self.memory_dir / self.long_term_file,
            archive_dir=base / "archive",
            state_file=base / ".dreaming_state.json",
            report_dir=base / "reports",
        )


@dataclass
class ResolvedPaths:
    """解析后的绝对路径"""
    memory_dir: Path
    long_term_file: Path
    archive_dir: Path
    state_file: Path
    report_dir: Path

    def ensure_dirs(self):
        """确保所有目录存在"""
        for p in [self.memory_dir, self.archive_dir, self.report_dir]:
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class DreamingConfig:
    """Dreaming 系统总配置"""
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    weights: WeightsConfig = field(default_factory=WeightsConfig)
    light_sleep: LightSleepConfig = field(default_factory=LightSleepConfig)
    rem_sleep: REMSleepConfig = field(default_factory=REMSleepConfig)
    deep_sleep: DeepSleepConfig = field(default_factory=DeepSleepConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    dry_run: bool = False                     # 模拟运行模式
    debug: bool = False                       # 调试输出

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DreamingConfig":
        """从字典创建配置，用于 plugin.json 覆盖"""
        config = cls()

        if "thresholds" in data:
            t = data["thresholds"]
            config.thresholds = ThresholdConfig(
                min_score=t.get("min_score", config.thresholds.min_score),
                min_recall_count=t.get("min_recall_count", config.thresholds.min_recall_count),
                min_unique_queries=t.get("min_unique_queries", config.thresholds.min_unique_queries),
            )

        if "weights" in data:
            w = data["weights"]
            config.weights = WeightsConfig(
                relevance=w.get("relevance", config.weights.relevance),
                frequency=w.get("frequency", config.weights.frequency),
                query_diversity=w.get("query_diversity", config.weights.query_diversity),
                recency=w.get("recency", config.weights.recency),
                consolidation=w.get("consolidation", config.weights.consolidation),
                concept_richness=w.get("concept_richness", config.weights.concept_richness),
            )

        if "light_sleep" in data:
            ls = data["light_sleep"]
            config.light_sleep = LightSleepConfig(
                max_memory_age_days=ls.get("max_memory_age_days", config.light_sleep.max_memory_age_days),
                scan_batch_size=ls.get("scan_batch_size", config.light_sleep.scan_batch_size),
            )

        if "rem_sleep" in data:
            rs = data["rem_sleep"]
            config.rem_sleep = REMSleepConfig(
                max_candidates=rs.get("max_candidates", config.rem_sleep.max_candidates),
                association_depth=rs.get("association_depth", config.rem_sleep.association_depth),
            )

        if "deep_sleep" in data:
            ds = data["deep_sleep"]
            config.deep_sleep = DeepSleepConfig(
                archive_threshold_days=ds.get("archive_threshold_days", config.deep_sleep.archive_threshold_days),
                max_consolidations_per_run=ds.get("max_consolidations_per_run", config.deep_sleep.max_consolidations_per_run),
            )

        if "schedule" in data:
            s = data["schedule"]
            config.schedule = ScheduleConfig(
                cron_expression=s.get("cron_expression", config.schedule.cron_expression),
                timezone=s.get("timezone", config.schedule.timezone),
                enabled=s.get("enabled", config.schedule.enabled),
            )

        if "paths" in data:
            p = data["paths"]
            config.paths = PathConfig(
                memory_dir=p.get("memory_dir", config.paths.memory_dir),
                long_term_file=p.get("long_term_file", config.paths.long_term_file),
                archive_dir=p.get("archive_dir", config.paths.archive_dir),
                state_file=p.get("state_file", config.paths.state_file),
            )

        if "dry_run" in data:
            config.dry_run = data["dry_run"]

        if "debug" in data:
            config.debug = data["debug"]

        return config

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（序列化用）"""
        return {
            "thresholds": {
                "min_score": self.thresholds.min_score,
                "min_recall_count": self.thresholds.min_recall_count,
                "min_unique_queries": self.thresholds.min_unique_queries,
            },
            "weights": self.weights.as_dict(),
            "light_sleep": {
                "max_memory_age_days": self.light_sleep.max_memory_age_days,
                "scan_batch_size": self.light_sleep.scan_batch_size,
            },
            "rem_sleep": {
                "max_candidates": self.rem_sleep.max_candidates,
                "association_depth": self.rem_sleep.association_depth,
            },
            "deep_sleep": {
                "archive_threshold_days": self.deep_sleep.archive_threshold_days,
                "max_consolidations_per_run": self.deep_sleep.max_consolidations_per_run,
            },
            "schedule": {
                "cron_expression": self.schedule.cron_expression,
                "timezone": self.schedule.timezone,
                "enabled": self.schedule.enabled,
            },
            "paths": {
                "memory_dir": self.paths.memory_dir,
                "long_term_file": self.paths.long_term_file,
                "archive_dir": self.paths.archive_dir,
                "state_file": self.paths.state_file,
            },
            "dry_run": self.dry_run,
            "debug": self.debug,
        }


# ============================================================
# 便捷访问：默认配置单例
# ============================================================

DEFAULT_CONFIG = DreamingConfig()
