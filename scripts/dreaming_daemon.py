"""
copaw-dreaming - 核心守护进程（三阶段流水线）

DreamingDaemon 编排完整的记忆巩固流程：
  Phase 0: Preparation  — 准备工作（目录检查、配置加载、状态读取）
  Phase 1: Light Sleep  — 浅睡（记忆扫描、信号收集、轻量过滤）
  Phase 2: REM Sleep     — REM睡眠（六信号评分、联想分析、门槛过滤）
  Phase 3: Deep Sleep    — 深睡（写入长期存储、归档过期记忆、状态更新）

支持两种运行模式：
  - Skill 模式: 直接调用 run_once() 同步执行
  - Plugin 模式: 通过 start_daemon() 启动定时守护
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dreaming_config import (
    DreamingConfig,
    ResolvedPaths,
    SleepPhase,
    DEFAULT_CONFIG,
)
from .scoring_engine import ScoringEngine, MemoryCandidate, ScoringResult

logger = logging.getLogger(__name__)


# ============================================================
# 运行状态
# ============================================================

@dataclass
class DreamingRunState:
    """单次 dreaming 运行的完整状态"""
    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    phase: str = ""
    status: str = "pending"  # pending | running | completed | error
    error: Optional[str] = None

    # 各阶段统计
    files_scanned: int = 0
    candidates_found: int = 0
    candidates_passed: int = 0
    consolidated: int = 0
    archived: int = 0
    insights_generated: int = 0

    # 输出文件路径
    report_path: Optional[str] = None


# ============================================================
# 守护进程核心
# ============================================================

class DreamingDaemon:
    """
    梦境守护进程。

    使用方法：

    # Skill 模式（同步执行一次）
    daemon = DreamingDaemon(workspace_dir=Path("."))
    result = daemon.run_once()

    # Plugin 模式（获取 startup hook 回调）
    daemon = DreamingDaemon(workspace_dir=Path("."), config=custom_config)
    await daemon.on_startup()   # 注册到 api.register_startup_hook
    """

    def __init__(
        self,
        workspace_dir: Path,
        config: Optional[DreamingConfig] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ):
        """
        初始化守护进程。

        Args:
            workspace_dir: 工作区根目录
            config: 自定义配置（默认使用 DEFAULT_CONFIG）
            user_profile: 用户画像（用于 relevance 信号）
            dry_run: 模拟运行模式（不实际写入任何文件）
        """
        self.workspace_dir = Path(workspace_dir).resolve()
        self.config = config or DEFAULT_CONFIG
        self.user_profile = user_profile or {}
        self.dry_run = dry_run or self.config.dry_run

        # 解析路径
        self.paths: ResolvedPaths = self.config.paths.resolve(self.workspace_dir)

        # 状态数据（从 state 文件加载）
        self.state_data: Dict[str, Any] = {}

        # 当前运行状态
        self.current_run: Optional[DreamingRunState] = None

    # ------------------------------------------------------------------
    # 公共 API — 执行入口
    # ------------------------------------------------------------------

    def run_once(self) -> Dict[str, Any]:
        """
        同步执行一次完整的梦境流程（Skill 模式入口）。
        
        Returns:
            包含执行结果的字典，可用于 Agent 报告
        """
        self.current_run = DreamingRunState(
            run_id=self._generate_run_id(),
            started_at=datetime.now(timezone.utc).isoformat(),
            status="running",
        )

        try:
            # Phase 0: 准备
            self._phase_preparation()

            # Phase 1: 浅睡 — 扫描
            candidates = self._phase_light_sleep()

            # Phase 2: REM — 评分
            scoring_result = self._phase_rem_sleep(candidates)

            # Phase 3: 深睡 — 写入
            consolidation_result = self._phase_deep_sleep(scoring_result)

            self.current_run.finished_at = datetime.now(timezone.utc).isoformat()
            self.current_run.status = "completed"
            self.current_run.phase = "done"

            return {
                "run_id": self.current_run.run_id,
                "status": "completed",
                **consolidation_result,
                "report_path": self.current_run.report_path,
                "dry_run": self.dry_run,
            }

        except Exception as e:
            self.current_run.status = "error"
            self.current_run.error = str(e)
            logger.error("Dreaming failed: %s", e, exc_info=True)
            return {
                "run_id": getattr(self.current_run, "run_id", "unknown"),
                "status": "error",
                "error": str(e),
                "dry_run": self.dry_run,
            }

    async def on_startup(self):
        """
        异步启动回调（Plugin 模式入口）。
        注册为 QwenPaw startup_hook 时使用。
        """
        logger.info("🌙 Dreaming Daemon starting up...")
        logger.info("  workspace: %s", self.workspace_dir)
        logger.info("  memory_dir: %s", self.paths.memory_dir)
        logger.info("  schedule: %s (enabled=%s)",
                     self.config.schedule.cron_expression,
                     self.config.schedule.enabled)
        if self.dry_run:
            logger.info("  ⚠️ DRY RUN MODE - no files will be written")

        # 确保目录存在
        if not self.dry_run:
            self.paths.ensure_dirs()

        # 加载历史状态
        self._load_state()

        logger.info("🌙 Dreaming Daemon ready.")

    def execute_dreaming(self) -> Dict[str, Any]:
        """
        被 Cron/控制命令调用的执行方法。
        包装 run_once() 并添加日志。
        """
        logger.info("🌙 === Dreaming execution started ===")
        result = self.run_once()
        logger.info(
            "🌙 === Dreaming execution finished: %s (passed=%d) ===",
            result.get("status", "?"),
            result.get("candidates_passed", 0),
        )
        return result

    # ------------------------------------------------------------------
    # Phase 0: Preparation
    # ------------------------------------------------------------------

    def _phase_preparation(self):
        """准备阶段：检查目录、加载配置和状态"""
        self.current_run.phase = "preparation"
        logger.info("Phase 0: Preparation...")

        # 检查 memory 目录
        if not self.paths.memory_dir.exists():
            logger.warning(
                "Memory directory does not exist: %s. Creating...",
                self.paths.memory_dir,
            )
            if not self.dry_run:
                self.paths.ensure_dirs()

        # 加载历史状态
        self._load_state()

        # 确保 output 目录存在
        if not self.dry_run:
            self.paths.ensure_dirs()

        logger.info("Phase 0 complete. State loaded with %d entries",
                     len(self.state_data.get("memory_recall", {})))

    # ------------------------------------------------------------------
    # Phase 1: Light Sleep — 记忆扫描
    # ------------------------------------------------------------------

    def _phase_light_sleep(self) -> List[MemoryCandidate]:
        """浅睡阶段：扫描记忆文件，提取候选"""
        self.current_run.phase = "light_sleep"
        logger.info("Phase 1: Light Sleep — scanning memory files...")

        engine = ScoringEngine(
            config=self.config,
            user_profile=self.user_profile,
            state_data=self.state_data,
        )

        candidates = engine.scan_memory_files(self.paths.memory_dir)

        self.current_run.files_scanned = len([
            f for f in self.paths.memory_dir.glob("*.md")
            if not f.name.startswith(".") and re.match(r"^\d{4}-\d{2}-\d{2}", f.name)
        ])
        self.current_run.candidates_found = len(candidates)

        logger.info(
            "Phase 1 complete: %d files scanned, %d candidates extracted",
            self.current_run.files_scanned,
            len(candidates),
        )

        return candidates

    # ------------------------------------------------------------------
    # Phase 2: REM Sleep — 评分与联想
    # ------------------------------------------------------------------

    def _phase_rem_sleep(self, candidates: List[MemoryCandidate]) -> ScoringResult:
        """REM 阶段：六信号评分 + 联想分析"""
        self.current_run.phase = "rem_sleep"
        logger.info("Phase 2: REM Sleep — scoring %d candidates...", len(candidates))

        engine = ScoringEngine(
            config=self.config,
            user_profile=self.user_profile,
            state_data=self.state_data,
        )

        result = engine.score_all(candidates)

        self.current_run.candidates_passed = len(result.passed)

        logger.info(
            "Phase 2 complete: %d passed (%.1f%%), %d failed",
            len(result.passed),
            result.pass_rate * 100,
            len(result.failed),
        )

        return result

    # ------------------------------------------------------------------
    # Phase 3: Deep Sleep — 巩固与归档
    # ------------------------------------------------------------------

    def _phase_deep_sleep(self, scoring_result: ScoringResult) -> Dict[str, Any]:
        """深睡阶段：写入长期记忆、归档、更新状态"""
        self.current_run.phase = "deep_sleep"
        logger.info("Phase 3: Deep Sleep — consolidating...")

        consolidated_count = 0
        archived_count = 0

        if not self.dry_run:
            # 3a. 将通过门槛的记忆写入/更新 MEMORY.md
            consolidated_count = self._consolidate_to_memory_md(
                scoring_result.passed
            )

            # 3b. 归档过时记忆
            archived_count = self._archive_old_memories()

            # 3c. 更新 dreaming state 文件
            self._update_state(scoring_result)
        else:
            logger.info("[DRY RUN] Skipping file writes")

        # 3d. 生成报告（无论 dry_run 都生成报告）
        report_content = self._generate_report(scoring_result)
        report_path = self._save_report(report_content)
        self.current_run.report_path = str(report_path) if report_path else None
        self.current_run.consolidated = consolidated_count
        self.current_run.archived = archived_count
        self.current_run.insights_generated = len(scoring_result.insights)

        logger.info(
            "Phase 3 complete: consolidated=%d, archived=%d, insights=%d",
            consolidated_count, archived_count,
            len(scoring_result.insights),
        )

        return {
            "files_scanned": self.current_run.files_scanned,
            "candidates_found": self.current_run.candidates_found,
            "candidates_passed": self.current_run.candidates_passed,
            "consolidated": consolidated_count,
            "archived": archived_count,
            "insights": scoring_result.insights,
            "top_scores": [
                {
                    "preview": m.preview(80),
                    "score": round(m.weighted_score, 3),
                    "source": m.source_file,
                }
                for m in scoring_result.top_n(5)
            ],
        }

    # ------------------------------------------------------------------
    # 深睡子操作
    # ------------------------------------------------------------------

    def _consolidate_to_memory_md(
        self, scored_memories: List[MemoryCandidate]
    ) -> int:
        """将通过门槛的高分记忆写入 MEMORY.md"""
        if not scored_memories:
            logger.info("No memories to consolidate")
            return 0

        lt_file = self.paths.long_term_file
        now = datetime.now(timezone.utc)
        max_consolidations = self.config.deep_sleep.max_consolidations_per_run
        to_consolidate = sorted(
            scored_memories,
            key=lambda m: m.weighted_score,
            reverse=True,
        )[:max_consolidations]

        # 构建新内容块
        new_sections: List[str] = []
        new_sections.append(f"\n\n## 🌙 Dreaming 巩固 — {now.strftime('%Y-%m-%d %H:%M UTC')}\n")

        for rank, mem in enumerate(to_consolidate, 1):
            sig_str = ""
            if mem.signals:
                sig_dict = mem.signals.as_dict()
                top_3 = sorted(sig_dict.items(), key=lambda x: x[1], reverse=True)[:3]
                sig_str = " | ".join(f"{k}={v:.2f}" for k, v in top_3)

            section = (
                f"### #{rank} [分数:{mem.weighted_score:.3f}] "
                f"(来源:`{mem.source_file}`)\n\n"
                f"{mem.content}\n"
            )
            if sig_str:
                section += f"\n> 信号: {sig_str}\n"

            new_sections.append(section)

        # 追加或创建 MEMORY.md
        if lt_file.exists():
            existing = lt_file.read_text(encoding="utf-8").rstrip()
            content = existing + "\n".join(new_sections) + "\n"
        else:
            header = "# 🧠 长期记忆 (MEMORY.md)\n\n"
            content = header + "".join(new_sections) + "\n"

        # 原子写入（写临时文件 + 重命名）
        temp_file = lt_file.with_suffix(".tmp")
        try:
            temp_file.write_text(content, encoding="utf-8")
            shutil.move(str(temp_file), str(lt_file))
            logger.info("Consolidated %d memories to %s", len(to_consolidate), lt_file)
        except Exception as e:
            logger.error("Failed to write MEMORY.md: %s", e)
            if temp_file.exists():
                temp_file.unlink()
            raise

        return len(to_consolidate)

    def _archive_old_memories(self) -> int:
        """归档超过 archive_threshold_days 的日记文件"""
        archive_dir = self.paths.archive_dir
        threshold_days = self.config.deep_sleep.archive_threshold_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        archived = 0

        if not self.paths.memory_dir.exists():
            return 0

        date_pattern = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
        for md_file in sorted(self.paths.memory_dir.iterdir()):
            if not md_file.is_file() or not date_pattern.match(md_file.name):
                continue
            if md_file.name.startswith("."):
                continue

            f_mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
            if f_mtime >= cutoff:
                continue

            # 移动到归档目录
            target = archive_dir / md_file.name
            if target.exists():
                # 归档中已存在，添加时间戳后缀
                stem = md_file.stem
                suffix = md_file.suffix
                target = archive_dir / f"{stem}_{now.strftime('%H%M%S')}{suffix}"

            try:
                shutil.move(str(md_file), str(target))
                archived += 1
                logger.info("Archived: %s → archive/%s", md_file.name, target.name)
            except Exception as e:
                logger.error("Failed to archive %s: %s", md_file.name, e)

        return archived

    def _update_state(self, scoring_result: ScoringResult):
        """更新 .dreaming_state.json"""
        now_iso = datetime.now(timezone.utc).isoformat()

        # 更新运行历史
        runs = self.state_data.get("runs", [])
        runs.append({
            "run_id": self.current_run.run_id,
            "timestamp": now_iso,
            "status": self.current_run.status,
            "candidates_total": scoring_result.total_scanned,
            "candidates_passed": len(scoring_result.passed),
            "consolidated": self.current_run.consolidated,
            "archived": self.current_run.archived,
            "insights": scoring_result.insights,
        })
        # 只保留最近 50 次运行记录
        self.state_data["runs"] = runs[-50:]

        # 更新记忆召回计数（对通过的记忆增加计数）
        recall_map = self.state_data.get("memory_recall", {})
        for mem in scoring_result.passed:
            key = f"{mem.source_file}:{mem.paragraph_index}"
            entry = recall_map.get(key, {
                "recall_count": 0,
                "unique_queries": [],
                "first_seen": now_iso,
                "last_seen": now_iso,
                "consolidation_count": 0,
            })
            entry["recall_count"] += 1
            entry["last_seen"] = now_iso
            entry["consolidation_count"] = entry.get("consolidation_count", 0) + 1
            recall_map[key] = entry
        self.state_data["memory_recall"] = recall_map

        # 更新元信息
        self.state_data["meta"] = {
            "version": "0.1.0",
            "last_run": now_iso,
            "total_runs": len(runs),
        }

        # 原子写入 state 文件
        self._atomic_write_json(self.paths.state_file, self.state_data)

    def _generate_report(self, scoring_result: ScoringResult) -> str:
        """生成梦境报告"""
        from .scoring_engine import ScoringEngine as SE
        engine = SE(config=self.config, user_profile=self.user_profile)
        return engine.generate_report(scoring_result)

    def _save_report(self, content: str) -> Optional[Path]:
        """保存报告文件"""
        report_dir = self.paths.report_dir
        if not self.dry_run:
            report_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"dreaming_report_{ts}.md"
        path = report_dir / filename

        try:
            path.write_text(content, encoding="utf-8")
            logger.info("Report saved: %s", path)
            return path
        except Exception as e:
            logger.error("Failed to save report: %s", e)
            return None

    # ------------------------------------------------------------------
    # 状态管理辅助
    # ------------------------------------------------------------------

    def _load_state(self):
        """从 state 文件加载历史状态"""
        state_file = self.paths.state_file
        if state_file.exists():
            try:
                self.state_data = json.loads(
                    state_file.read_text(encoding="utf-8")
                )
                logger.debug("Loaded state from %s (%d keys)",
                             state_file, len(self.state_data))
            except json.JSONDecodeError as e:
                logger.warning("Invalid state JSON at %s: %s. Starting fresh.",
                               state_file, e)
                self.state_data = {}
        else:
            self.state_data = {}
            logger.debug("No state file found, starting fresh")

    def _atomic_write_json(self, path: Path, data: Any):
        """原子写入 JSON 文件"""
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            shutil.move(str(temp), str(path))
        except Exception:
            if temp.exists():
                temp.unlink()
            raise

    @staticmethod
    def _generate_run_id() -> str:
        """生成唯一运行 ID"""
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + \
               f"{os.getpid()}"

    def get_status(self) -> Dict[str, Any]:
        """获取守护进程当前状态"""
        return {
            "workspace_dir": str(self.workspace_dir),
            "config": self.config.to_dict(),
            "paths": {
                "memory_dir": str(self.paths.memory_dir),
                "long_term_file": str(self.paths.long_term_file),
                "archive_dir": str(self.paths.archive_dir),
                "state_file": str(self.paths.state_file),
                "report_dir": str(self.paths.report_dir),
            },
            "current_run": {
                "run_id": self.current_run.run_id if self.current_run else "",
                "phase": self.current_run.phase if self.current_run else "",
                "status": self.current_run.status if self.current_run else "idle",
                "started_at": self.current_run.started_at if self.current_run else "",
            } if self.current_run else None,
            "state_summary": {
                "total_runs": len(self.state_data.get("runs", [])),
                "last_run": self.state_data.get("meta", {}).get("last_run", "never"),
                "tracked_memories": len(self.state_data.get("memory_recall", {})),
            },
            "dry_run": self.dry_run,
        }



