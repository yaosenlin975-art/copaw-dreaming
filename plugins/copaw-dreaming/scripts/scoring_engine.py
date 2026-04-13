"""
copaw-dreaming - 六信号评分引擎

对记忆条目进行多维度评分，用于决定哪些记忆值得长期保留。
基于 SKILL.md 中定义的六维评分模型实现。

信号维度：
  1. relevance     - 与用户核心兴趣的匹配度（权重 0.30）
  2. frequency      - 记忆被召回/引用的次数（权重 0.24）
  3. query_diversity - 触发该记忆的不同查询数量（权重 0.15）
  4. recency        - 最后更新时间的新鲜度（权重 0.15）
  5. consolidation  - 已被引用/关联的程度（权重 0.10）
  6. concept_richness - 包含的概念密度（权重 0.06）
"""

from __future__ import annotations

import json
import logging
import re
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .dreaming_config import (
    DreamingConfig,
    WeightsConfig,
    ThresholdConfig,
    SleepPhase,
)

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MemorySignals:
    """单条记忆的六维信号值（归一化到 [0, 1]）"""
    relevance: float = 0.0       # 用户兴趣匹配度
    frequency: float = 0.0       # 召回频率
    query_diversity: float = 0.0 # 查询多样性
    recency: float = 0.0         # 时间新鲜度
    consolidation: float = 0.0   # 整合/被引用程度
    concept_richness: float = 0.0  # 概念密度

    def as_dict(self) -> Dict[str, float]:
        return {
            "relevance": round(self.relevance, 4),
            "frequency": round(self.frequency, 4),
            "query_diversity": round(self.query_diversity, 4),
            "recency": round(self.recency, 4),
            "consolidation": round(self.consolidation, 4),
            "concept_richness": round(self.concept_richness, 4),
        }


@dataclass
class MemoryCandidate:
    """待评分的记忆候选"""
    content: str                   # 记忆文本内容
    source_file: str               # 来源文件名（如 "2026-04-12.md"）
    source_date: Optional[datetime] = None  # 文件日期
    last_modified: Optional[datetime] = None  # 最后修改时间
    paragraph_index: int = 0      # 段落索引
    keywords: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    referenced_by: List[str] = field(default_factory=list)  # 被哪些文件引用

    # 从 state 文件加载的历史数据
    recall_count: int = 0         # 历史召回次数
    unique_queries: Set[str] = field(default_factory=set)  # 唯一查询集合

    # 计算后的分数
    signals: Optional[MemorySignals] = None
    weighted_score: float = 0.0   # 加权综合分
    passed_threshold: bool = False  # 是否通过三重门槛

    @property
    def preview(self, max_len: int = 120) -> str:
        """生成记忆预览摘要"""
        text = self.content.strip().replace("\n", " ")
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    @property
    def unique_query_count(self) -> int:
        return len(self.unique_queries)


@dataclass
class ScoringResult:
    """一次评分运行的结果"""
    candidates: List[MemoryCandidate] = field(default_factory=list)
    passed: List[MemoryCandidate] = field(default_factory=list)   # 通过门槛的
    failed: List[MemoryCandidate] = field(default_factory=list)   # 未通过的
    insights: List[str] = field(default_factory=list)
    timestamp: str = ""
    config_summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_scanned(self) -> int:
        return len(self.candidates)

    @property
    def pass_rate(self) -> float:
        if not self.candidates:
            return 0.0
        return len(self.passed) / len(self.candidates)

    def top_n(self, n: int = 5) -> List[MemoryCandidate]:
        """返回得分最高的 N 个通过门槛的记忆"""
        sorted_passed = sorted(
            self.passed, key=lambda c: c.weighted_score, reverse=True
        )
        return sorted_passed[:n]


# ============================================================
# 评分器核心
# ============================================================

class ScoringEngine:
    """
    六信号评分引擎。

    使用方法：
        engine = ScoringEngine(config, user_profile)
        candidates = engine.scan_memory_files(memory_dir)
        result = engine.score_all(candidates)
        report = engine.generate_report(result)
    """

    def __init__(
        self,
        config: Optional[DreamingConfig] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        state_data: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化评分引擎。

        Args:
            config: DreamingConfig 配置实例（默认使用 DEFAULT_CONFIG）
            user_profile: 用户画像/兴趣关键词，用于 relevance 计算
            state_data: 从 .dreaming_state.json 加载的历史状态数据
        """
        self.config = config or DreamingConfig()
        self.user_profile = user_profile or {}
        self.state_data = state_data or {}

        # 从用户画像提取兴趣关键词
        self.interest_keywords: List[str] = self._extract_interests()

        # 编译排除模式（正则）
        self.exclude_patterns = [
            re.compile(p) for p in self.config.light_sleep.exclude_patterns
        ]

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def scan_memory_files(self, memory_dir: Path) -> List[MemoryCandidate]:
        """
        Phase 1: 浅睡 — 扫描记忆目录中的所有日记文件。

        Args:
            memory_dir: memory 目录路径

        Returns:
            MemoryCandidate 列表
        """
        candidates: List[MemoryCandidate] = []
        max_age = timedelta(days=self.config.light_sleep.max_memory_age_days)
        cutoff = datetime.now(timezone.utc) - max_age

        if not memory_dir.exists():
            logger.warning("Memory directory does not exist: %s", memory_dir)
            return candidates

        # 找出所有日期文件（YYYY-MM-DD.md），排除状态文件和报告
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
        md_files = sorted([
            f for f in memory_dir.iterdir()
            if f.is_file() and date_pattern.match(f.name)
            and not f.name.startswith(".")
        ])

        for md_file in md_files:
            # 检查文件年龄
            f_stat = md_file.stat()
            f_mtime = datetime.fromtimestamp(f_stat.st_mtime, tz=timezone.utc)

            if f_mtime < cutoff:
                logger.debug(
                    "Skipping old file: %s (mtime=%s)",
                    md_file.name, f_mtime.isoformat(),
                )
                continue

            # 解析文件日期
            file_date = self._parse_date_from_filename(md_file.name)

            # 读取内容并分段
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.error("Failed to read %s: %s", md_file.name, e)
                continue

            paragraphs = self._split_into_paragraphs(content)

            for idx, paragraph in enumerate(paragraphs):
                # 应用排除模式
                if self._should_exclude(paragraph):
                    continue

                candidate = MemoryCandidate(
                    content=paragraph,
                    source_file=md_file.name,
                    source_date=file_date,
                    last_modified=f_mtime,
                    paragraph_index=idx,
                )

                # 提取特征
                candidate.keywords = self._extract_keywords(paragraph)
                candidate.entities = self._extract_entities(paragraph)
                candidate.concepts = self._extract_concepts(paragraph)

                # 加载历史召回数据
                self._load_history(candidate)

                candidates.append(candidate)

        logger.info(
            "Scanned %d files, extracted %d memory candidates",
            len(md_files), len(candidates),
        )
        return candidates

    def score_all(
        self,
        candidates: List[MemoryCandidate],
    ) -> ScoringResult:
        """
        Phase 2: REM — 对所有候选记忆进行完整六信号评分。

        Args:
            candidates: 来自 scan_memory_files 的候选列表

        Returns:
            ScoringResult 包含评分结果、通过/未通过分组、洞察
        """
        result = ScoringResult(
            candidates=candidates,
            timestamp=datetime.now(timezone.utc).isoformat(),
            config_summary={
                "thresholds": {
                    "min_score": self.config.thresholds.min_score,
                    "min_recall_count": self.config.thresholds.min_recall_count,
                    "min_unique_queries": self.config.thresholds.min_unique_queries,
                },
                "weights": self.config.weights.as_dict(),
            },
        )

        weights = self.config.weights

        for candidate in candidates:
            # 计算六维信号
            signals = MemorySignals(
                relevance=self._score_relevance(candidate),
                frequency=self._score_frequency(candidate),
                query_diversity=self._score_query_diversity(candidate),
                recency=self._score_recency(candidate),
                consolidation=self._score_consolidation(candidate),
                concept_richness=self._score_concept_richness(candidate),
            )
            candidate.signals = signals

            # 加权求和
            candidate.weighted_score = (
                signals.relevance * weights.relevance
                + signals.frequency * weights.frequency
                + signals.query_diversity * weights.query_diversity
                + signals.recency * weights.recency
                + signals.consolidation * weights.consolidation
                + signals.concept_richness * weights.concept_richness
            )

            # 三重门槛检查
            candidate.passed_threshold = self.config.thresholds.check(
                score=candidate.weighted_score,
                recall_count=candidate.recall_count,
                unique_queries=candidate.unique_query_count,
            )

            if candidate.passed_threshold:
                result.passed.append(candidate)
            else:
                result.failed.append(candidate)

        # 排序：按加权分数降序
        result.passed.sort(key=lambda c: c.weighted_score, reverse=True)
        result.failed.sort(key=lambda c: c.weighted_score, reverse=True)

        # 生成洞察
        result.insights = self._generate_insights(result)

        logger.info(
            "Scoring complete: %d total, %d passed (%.1f%%), %d failed",
            len(candidates), len(result.passed),
            result.pass_rate * 100, len(result.failed),
        )

        return result

    def generate_report(self, result: ScoringResult) -> str:
        """
        生成 Markdown 格式的梦境报告。

        Args:
            result: score_all() 的返回值

        Returns:
            Markdown 报告字符串
        """
        lines: List[str] = []

        lines.append(f"# 🌙 梦境报告 - {result.timestamp}")
        lines.append("")
        lines.append("## 概览")
        lines.append("")
        lines.append(f"- 处理记忆总数: **{result.total_scanned}**")
        lines.append(f"- 通过门槛: **{len(result.passed)}** ({result.pass_rate:.1%})")
        lines.append(f"- 未通过: **{len(result.failed)}**")
        lines.append(f"- 生成洞察: **{len(result.insights)}**")
        lines.append("")

        # 高分记忆 TOP 5
        top_memories = result.top_n(5)
        if top_memories:
            lines.append("## 高分记忆 TOP 5")
            lines.append("")
            lines.append("| 排名 | 来源 | 记忆摘要 | 综合分 | 主要信号 |")
            lines.append("|------|------|---------|--------|----------|")

            for rank, mem in enumerate(top_memories, 1):
                sig = mem.signals.as_dict() if mem.signals else {}
                top_signals = self._get_top_signals(sig, n=3)
                lines.append(
                    f"| {rank} | `{mem.source_file}` | "
                    f"{mem.preview(80)} | "
                    f"**{mem.weighted_score:.3f**} | "
                    f"{top_signals} |"
                )
            lines.append("")

        # 新生洞察
        if result.insights:
            lines.append("## 新生洞察")
            lines.append("")
            for i, insight in enumerate(result.insights, 1):
                lines.append(f"{i}. {insight}")
            lines.append("")

        # 信号分布统计
        lines.append("## 信号分布统计")
        lines.append("")
        if result.passed:
            avg_scores = self._compute_avg_signals(result.passed)
            lines.append("| 信号 | 平均分 | 最高 | 最低 |")
            lines.append("|------|--------|------|------|")
            for sig_name, avg_val in avg_scores.items():
                values = [
                    (m.signals or getattr(MemorySignals(), sig_name.lower(), 0))
                    for m in result.passed
                ]
                hi = max(values) if values else 0
                lo = min(values) if values else 0
                lines.append(
                    f"| {sig_name} | {avg_val:.3f} | {hi:.3f} | {lo:.3f} |"
                )
            lines.append("")

        # 未通过的高潜记忆（接近门槛）
        near_misses = [
            m for m in result.failed
            if m.weighted_score >= self.config.thresholds.min_score * 0.9
        ][:5]
        if near_misses:
            lines.append("## 接近门槛（下次可能通过）")
            lines.append("")
            for mem in near_misses:
                gap = self.config.thresholds.min_score - mem.weighted_score
                lines.append(f"- `{mem.source_file}` | 分数: {mem.weighted_score:.3f} | 差距: {gap:.3f}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 六维评分函数
    # ------------------------------------------------------------------

    def _score_relevance(self, candidate: MemoryCandidate) -> float:
        """
        信号 1: 相关性 (weight=0.30)

        匹配用户画像中的兴趣关键词。考虑：
        - 关键词命中数 / 总词数
        - 实体匹配
        - 主题标签重叠度
        """
        if not self.interest_keywords:
            # 无用户画像时，基于内容自身质量估算
            return self._estimate_content_quality(candidate.content)

        content_lower = candidate.content.lower()
        hits = 0
        total_keywords = len(self.interest_keywords)

        for kw in self.interest_keywords:
            kw_lower = kw.lower()
            if kw_lower in content_lower:
                hits += 1
                # 频率加成：出现多次的关键词权重更高
                count = content_lower.count(kw_lower)
                if count > 1:
                    hits += min(count - 1, 2) * 0.3  # 每次额外加 0.3，最多加 0.6

        base_score = hits / max(total_keywords, 1)

        # 实体加成
        entity_bonus = 0.0
        for entity in candidate.entities:
            for kw in self.interest_keywords:
                if kw.lower() in entity.lower():
                    entity_bonus += 0.05
        entity_bonus = min(entity_bonus, 0.2)

        return min(base_score + entity_bonus, 1.0)

    def _score_frequency(self, candidate: MemoryCandidate) -> float:
        """
        信号 2: 频率 (weight=0.24)

        基于历史召回次数的对数缩放。
        无历史数据时默认低分。
        """
        count = candidate.recall_count
        if count == 0:
            return 0.1  # 新记忆给一个基础分

        # 对数缩放：log10(count+1) 归一化到 [0, 1]
        # 10次 → ~1.0, 3次 → ~0.6, 1次 → ~0.3
        raw = math.log10(count + 1) / math.log10(max(self.config.thresholds.min_recall_count * 3, 10))
        return min(raw, 1.0)

    def _score_query_diversity(self, candidate: MemoryCandidate) -> float:
        """
        信号 3: 查询多样性 (weight=0.15)

        不同独立查询触发该记忆的数量。
        反映该记忆在多个上下文中都有用。
        """
        uq = candidate.unique_query_count
        if uq == 0:
            return 0.05

        # 类似 frequency 的对数缩放
        raw = math.log10(uq + 1) / math.log10(max(self.config.thresholds.min_unique_queries * 2, 8))
        return min(raw, 1.0)

    def _score_recency(self, candidate: MemoryCandidate) -> float:
        """
        信号 4: 时效性 (weight=0.15)

        基于最后修改时间的指数衰减。
        越新的记忆分数越高。
        """
        ref_time = candidate.last_modified or candidate.source_date or datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = max((now - ref_time).total_seconds() / 86400, 0)

        # 半衰期 30 天：30 天后衰减为 0.5
        half_life = 30.0
        decay = math.pow(2.0, -age_days / half_life)

        # 给近期记忆一个保底分数
        if age_days < 7:
            decay = max(decay, 0.9)
        elif age_days < 30:
            decay = max(decay, 0.5)

        return decay

    def _score_consolidation(self, candidate: MemoryCandidate) -> float:
        """
        信号 5: 整合度 (weight=0.10)

        该记忆被其他记忆引用/关联的程度。
        """
        ref_count = len(candidate.referenced_by)
        if ref_count == 0:
            return 0.05

        # 线性映射：1次引用→0.2, 5次→1.0
        raw = min(ref_count / 5.0, 1.0)
        return max(raw, 0.2)

    def _score_concept_richness(self, candidate: MemoryCandidate) -> float:
        """
        信号 6: 概念丰富度 (weight=0.06)

        记忆中包含的概念/技术术语密度。
        """
        concept_count = len(candidate.concepts)
        keyword_count = len(candidate.keywords)

        # 综合概念密度
        total = concept_count + keyword_count
        if total == 0:
            return 0.05

        content_len = max(len(candidate.content), 1)
        density = min(total / max(content_len / 50, 1), 1.0)  # 每50字符一个概念为满分

        return density

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _extract_interests(self) -> List[str]:
        """从用户画像提取兴趣关键词列表"""
        interests = []

        # 直接关键词
        if "interests" in self.user_profile:
            interests.extend(self.user_profile["interests"])

        # 从工作背景提取
        if "work_context" in self.user_profile:
            ctx = self.user_profile["work_context"]
            if isinstance(ctx, str):
                # 简单分词
                interests.extend(re.findall(r'[\w\u4e00-\u9fff]{2,}', ctx))

        # 从 MEMORY.md 主题提取（如果有）
        if "memory_topics" in self.user_profile:
            interests.extend(self.user_profile["memory_topics"])

        # 去重
        seen = set()
        unique = []
        for kw in interests:
            kwl = kw.lower().strip()
            if kwl and kwl not in seen and len(kwl) >= 2:
                seen.add(kwl)
                unique.append(kw)

        return unique

    def _parse_date_from_filename(self, filename: str) -> Optional[datetime]:
        """从 YYYY-MM-DD.md 文件名解析日期"""
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})\.md$", filename)
        if match:
            try:
                return datetime(
                    int(match.group(1)), int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                pass
        return None

    def _split_into_paragraphs(self, content: str) -> List[str]:
        """将 Markdown 内容分割为有意义的段落"""
        # 先按双换行分割
        blocks = re.split(r"\n\s*\n", content)
        paragraphs = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue
            # 过滤纯标题行（单独的 ## 标题）
            if re.match(r"^#{1,6}\s+.+$", block):
                continue
            # 过滤分隔线
            if re.match(r"^---+\s*$", block):
                continue
            # 过滤过短的内容（可能是标题或元数据）
            if len(block) < self.config.light_sleep.min_paragraph_length:
                continue

            paragraphs.append(block)

        return paragraphs

    def _should_exclude(self, text: str) -> bool:
        """检查文本是否应被排除"""
        for pattern in self.exclude_patterns:
            if pattern.search(text):
                return True
        return False

    def _extract_keywords(self, text: str) -> List[str]:
        """简单关键词提取（中文+英文混合）"""
        # 中文词汇（2-4字）
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        # 英文单词（3字母以上）
        en_words = re.findall(r'[A-Za-z]{3,}', text)
        # 合并去重
        all_words = list(set(cn_words + en_words))

        # 过滤常见停用词
        stopwords = {
            "the", "and", "for", "are", "but", "not", "you",
            "all", "can", "had", "her", "was", "one", "our", "out",
            "这个", "那个", "什么", "如何", "因为", "所以", "然后",
            "可以", "已经", "需要", "应该", "如果", "就是", "也是",
        }
        return [w for w in all_words if w.lower() not in stopwords]

    def _extract_entities(self, text: str) -> List[str]:
        """提取可能的实体名称（人名、产品名、项目名等）"""
        entities = []

        # 大写英文实体（如 Ollama, RTX, QwenPaw）
        entities.extend(re.findall(r'\b[A-Z][A-Za-z0-9]{2,}\b', text))

        # 书名/文章名《》
        entities.extend(re.findall(r'《([^》]+)》', text))

        # 引号中的专有名词
        entities.extend(re.findall(r'"([^"]{2,20})"', text))

        # 版本号
        entities.extend(re.findall(r'\bv?\d+\.\d+(?:\.\d+)?(?:-[a-z]+)?\b', text))

        return list(set(entities))

    def _extract_concepts(self, text: str) -> List[str]:
        """提取概念性术语（技术概念、领域术语等）"""
        concepts = []

        # 技术模式
        tech_patterns = [
            r'[A-Za-z_]+(?:API|SDK|MCP|CLI|LLM|GPU|VRAM|Docker)\b',  # 技术缩写
            r'(?:量化|推理|微调|训练|部署|插件|技能|守护进程|流水线)',  # 中文技术词
            r'(?:Python|JSON|Markdown|YAML|Cron|Async|Plugin)',           # 技术/格式
        ]
        for pattern in tech_patterns:
            concepts.extend(re.findall(pattern, text))

        return list(set(concepts))

    def _load_history(self, candidate: MemoryCandidate):
        """从 state 数据加载历史召回信息"""
        key = f"{candidate.source_file}:{candidate.paragraph_index}"
        entry = self.state_data.get("memory_recall", {}).get(key, {})

        candidate.recall_count = entry.get("recall_count", 0)
        queries = entry.get("unique_queries", [])
        candidate.unique_queries = set(queries) if queries else set()

        referenced = entry.get("referenced_by", [])
        candidate.referenced_by = referenced if referenced else []

    def _estimate_content_quality(self, content: str) -> float:
        """无用户画像时的内容质量估算"""
        score = 0.3  # 基础分

        length = len(content)
        if length > 100:
            score += 0.1  # 有一定长度
        if length > 300:
            score += 0.1  # 较长内容

        # 包含具体信息（数字、版本号等）
        if re.search(r'\d+', content):
            score += 0.1
        # 包含结构性标记（列表项等）
        if re.search(r'^[-*]', content, re.MULTILINE):
            score += 0.1

        return min(score, 0.8)

    def _generate_insights(self, result: ScoringResult) -> List[str]:
        """从评分结果中生成洞察"""
        insights = []

        if not result.passed:
            return ["本次没有记忆通过三重门槛。建议继续积累更多交互记录。"]

        # 主题聚类
        topic_counts: Dict[str, int] = {}
        for mem in result.passed:
            for kw in mem.keywords[:3]:  # 取前3个关键词
                topic_counts[kw] = topic_counts.get(kw, 0) + 1

        top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_topics:
            topics_str = "、".join(f"`{t[0]}`({t[1]}条)" for t in top_topics if t[1] >= 2)
            if topics_str:
                insights.append(f"高频主题: {topics_str}")

        # 时间分布
        recent = sum(1 for m in result.passed if m.signals and m.signals.recency > 0.7)
        older = sum(1 for m in result.passed if m.signals and m.signals.recency < 0.3)
        if recent > 0 and older > 0:
            insights.append(
                f"时间分布: {recent} 条近期活跃 + {older} 条历史沉淀记忆"
            )

        # 高频记忆
        high_freq = [m for m in result.passed if m.recall_count >= 5]
        if high_freq:
            names = [m.preview(50) for m in high_freq[:3]]
            insights.append(
                f"高召回记忆 Top3: {'; '.join(names)}"
            )

        # 即将归档提示
        near_archive = [
            m for m in result.passed
            if m.signals and m.signals.recency < 0.15
        ]
        if near_archive:
            insights.append(
                f"⚠️ {len(near_archive)} 条高分记忆即将达到归档阈值 "
                f"(时效性 < 0.15)，建议尽快巩固"
            )

        return insights

    def _get_top_signals(self, signals: Dict[str, float], n: int = 3) -> str:
        """获取最高的 N 个信号名称"""
        sorted_sigs = sorted(signals.items(), key=lambda x: x[1], reverse=True)[:n]
        parts = []
        for name, val in sorted_sigs:
            short_name = {
                "relevance": "相关性",
                "frequency": "频率↑",
                "query_diversity": "多样↑",
                "recency": "时效",
                "consolidation": "整合",
                "concept_richness": "概念",
            }.get(name, name)
            arrow = "↑" if val > 0.6 else ("→" if val > 0.3 else "↓")
            parts.append(f"{short_name}{arrow}")
        return " ".join(parts)

    def _compute_avg_signals(self, memories: List[MemoryCandidate]) -> Dict[str, float]:
        """计算平均信号值"""
        if not memories:
            return {}

        sums: Dict[str, float] = {}
        count = len(memories)

        for mem in memories:
            if not mem.signals:
                continue
            for name, val in mem.signals.as_dict().items():
                sums[name] = sums.get(name, 0) + val

        return {k: v / count for k, v in sums.items()}
