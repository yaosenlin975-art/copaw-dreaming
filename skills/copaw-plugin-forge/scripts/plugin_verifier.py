"""
Plugin Verifier — QwenPaw 插件运行时验证器

两阶段验证：
  1. 模拟加载 — 用 importlib + MockApi 动态加载 plugin.py 并调用 register()
  2. 日志扫描 — 检查 QwenPaw 启动日志中插件加载状态
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# MockApi — 模拟 PluginApi，记录所有调用
# ============================================================

class MockApiCall:
    """记录一次 API 调用"""

    def __init__(self, method: str, args: tuple = (), kwargs: dict | None = None):
        self.method = method
        self.args = args
        self.kwargs = kwargs or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def __repr__(self) -> str:
        kw_str = ", ".join(f"{k}={v!r}" for k, v in self.kwargs.items())
        return f"MockApiCall({self.method}, {kw_str})"


class MockRuntimeHelper:
    """模拟 RuntimeHelpers"""
    _log: List[str] = []

    def log_info(self, msg: str) -> None:
        MockRuntimeHelper._log.append(f"[INFO] {msg}")

    def log_error(self, msg: str, **kwargs) -> None:
        MockRuntimeHelper._log.append(f"[ERROR] {msg}")

    def log_debug(self, msg: str) -> None:
        MockRuntimeHelper._log.append(f"[DEBUG] {msg}")


class MockApi:
    """
    模拟 PluginApi 对象。

    记录所有 register_* 调用，用于验证插件的 API 使用是否正确。
    """

    def __init__(self):
        self.calls: List[MockApiCall] = []
        self.runtime = MockRuntimeHelper()
        # 可选：设置 config 属性（从 plugin.json 的 meta 读取）
        self.config: Dict[str, Any] = {}

    def _record(self, method: str, *args, **kwargs) -> None:
        call = MockApiCall(method, args, kwargs)
        self.calls.append(call)

    # ---- 公共 API 方法 ----

    def register_provider(
        self,
        provider_id: str,
        provider_class,
        label: str = "",
        base_url: str = "",
        **metadata: Any,
    ) -> None:
        self._record("register_provider", provider_id=provider_id, label=label, base_url=base_url)

    def register_startup_hook(self, hook_name: str, callback, priority: int = 50) -> None:
        self._record("register_startup_hook", hook_name=hook_name, priority=priority)

    def register_shutdown_hook(self, hook_name: str, callback, priority: int = 100) -> None:
        self._record("register_shutdown_hook", hook_name=hook_name, priority=priority)

    def register_control_command(self, handler, priority_level: int = 0) -> None:
        handler_name = getattr(handler, "__name__", str(handler))
        self._record("register_control_command", handler=handler_name)


# ============================================================
# 数据模型
# ============================================================


@dataclass
class LoadResult:
    """模拟加载结果"""
    success: bool
    error: str = ""
    error_type: str = ""
    traceback_str: str = ""
    api_calls: List[MockApiCall] = field(default_factory=list)
    runtime_logs: List[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def registered_hooks(self) -> List[MockApiCall]:
        return [c for c in self.api_calls if "hook" in c.method]

    @property
    def registered_providers(self) -> List[MockApiCall]:
        return [c for c in self.api_calls if "provider" in c.method]

    @property
    def registered_commands(self) -> List[MockApiCall]:
        return [c for c in self.api_calls if "command" in c.method]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "error_type": self.error_type,
            "api_call_count": len(self.api_calls),
            "hooks_registered": len(self.registered_hooks),
            "providers_registered": len(self.registered_providers),
            "commands_registered": len(self.registered_commands),
            "api_calls": [
                {"method": c.method, "kwargs": c.kwargs} for c in self.api_calls
            ],
            "runtime_logs": self.runtime_logs[:20],  # 只取最近 20 条
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class LogScanResult:
    """日志扫描结果"""
    scanned: bool
    log_files_checked: int = 0
    log_dir: Path = field(default_factory=lambda: Path(""))
    plugin_found_in_log: bool = False
    errors_found: List[Dict[str, Any]] = field(default_factory=list)
    warnings_found: List[Dict[str, Any]] = field(default_factory=list)
    info_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanned": self.scanned,
            "log_files_checked": self.log_files_checked,
            "log_dir": str(self.log_dir),
            "plugin_found_in_log": self.plugin_found_in_log,
            "error_count": len(self.errors_found),
            "warning_count": len(self.warnings_found),
            "errors": self.errors_found,
            "warnings": self.warnings_found,
        }


@dataclass
class VerificationResult:
    """完整验证结果（静态+运行时）"""
    plugin_id: str
    load_result: LoadResult
    log_scan: LogScanResult
    overall_passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "overall_passed": self.overall_passed,
            "load": self.load_result.to_dict(),
            "log_scan": self.log_scan.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def to_report_markdown(self) -> str:
        lr = self.load_result
        ls = self.log_scan
        lines = [
            f"# 🧪 插件验证报告: `{self.plugin_id}`",
            f"",
            f"**总状态**: {'✅ 通过' if self.overall_passed else '❌ 不通过'}",
            f"",
            "---",
            f"",
            f"## 阶段 A: 模拟加载 (importlib)",
            f"",
            f"| 项目 | 结果 |",
            f"|------|------|",
            f"| 加载成功 | {'✅' if lr.success else '❌'} |",
            f"| 耗时 | {lr.duration_ms:.1f}ms |",
            f"| API 调用数 | {len(lr.api_calls)} |",
            f"| Hook 注册 | {len(lr.registered_hooks)} 个 |",
            f"| Provider 注册 | {len(lr.registered_providers)} 个 |",
            f"| Command 注册 | {len(lr.registered_commands)} 个 |",
            f"",
        ]

        if not lr.success:
            lines.extend([
                f"### ❌ 加载失败",
                f"- **错误类型**: {lr.error_type}",
                f"- **错误信息**: {lr.error}",
                f"",
                f"```",
                f"{lr.traceback_str[:2000]}",
                f"```",
                f"",
            ])

        if lr.api_calls:
            lines.append(f"### API 调用详情")
            for call in lr.api_calls:
                kw_str = ", ".join(f"`{k}`=`{v}`" for k, v in call.kwargs.items() if k != "callback")
                lines.append(f"- `api.{call.method}`({kw_str})")
            lines.append("")

        if lr.runtime_logs:
            lines.append(f"### Runtime 日志")
            for log_line in lr.runtime_logs[:10]:
                lines.append(f"- {log_line}")
            lines.append("")

        # ---- 日志扫描部分 ----
        lines.extend([
            f"---",
            f"",
            f"## 阶段 B: QwenPaw 日志扫描",
            f"",
            f"| 项目 | 结果 |",
            f"|------|------|",
            f"| 扫描执行 | {'✅' if ls.scanned else '⏭️'} |",
            f"| 日志文件数 | {ls.log_files_checked} |",
            f"| 插件被发现 | {'✅ 是' if ls.plugin_found_in_log else '❌ 否'} |",
            f"| 日志错误数 | {len(ls.errors_found)} |",
            f"| 日志警告数 | {len(ls.warnings_found)} |",
            f"",
        ])

        if ls.errors_found:
            lines.append(f"### 日志中的错误")
            for err in ls.errors_found[:5]:
                lines.append(f"- **{err.get('file', '?')}**:{err.get('line', '?')} "
                           f"— {err.get('message', '')}")
            lines.append("")

        if ls.warnings_found:
            lines.append(f"### 日志中的警告")
            for warn in ls.warnings_found[:5]:
                lines.append(f"- **{warn.get('file', '?')}**:{warn.get('line', '?')} "
                           f"— {warn.get('message', '')}")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# 核心类：PluginVerifier
# ============================================================

class PluginVerifier:
    """
    QwenPaw 插件运行时验证器。

    用法:
        verifier = PluginVerifier()
        result = verifier.verify(plugin_dir=Path("~/.copaw/plugins/my-plugin"))
        print(result.to_report_markdown())
    """

    # 日志搜索关键词
    LOG_KEYWORDS = {
        "plugin": ["plugin", "PluginLoader", "register"],
        "error": ["Error", "Exception", "Traceback", "FAILED"],
        "warning": ["Warning", "WARN"],
    }

    def __init__(self, qwenpaw_install_dir: Optional[Path] = None):
        """
        Args:
            qwenpaw_install_dir: QwenPaw 安装目录(用于查找日志目录)。
                               如果不提供，会尝试自动检测。
        """
        self.qwenpaw_dir = qwenpaw_install_dir
        self.logger = logging.getLogger(__name__)

    def verify(self, plugin_dir: Path, scan_log: bool = True) -> VerificationResult:
        """
        完整的运行时验证流程。

        Args:
            plugin_dir: 插件根目录
            scan_log: 是否扫描日志（需要 QwenPaw 已重启过）

        Returns:
            VerificationResult 完整结果
        """
        plugin_dir = Path(plugin_dir).resolve()

        # ---- 阶段 1：模拟加载 ----
        self.logger.info("[verify] Starting mock load of %s", plugin_dir)
        load_result = self._mock_load(plugin_dir)

        # ---- 确定 plugin_id ----
        pid = self._extract_plugin_id(plugin_dir)

        # ---- 阶段 2：日志扫描 ----
        if scan_log:
            log_scan = self._scan_logs(pid)
        else:
            log_scan = LogScanResult(scanned=False)

        # ---- 综合判断 ----
        overall = load_result.success and (
            not log_scan.scanned or len(log_scan.errors_found) == 0
        )

        return VerificationResult(
            plugin_id=pid,
            load_result=load_result,
            log_scan=log_scan,
            overall_passed=overall,
        )

    # ==================================================================
    # 阶段 1: 模拟加载
    # ==================================================================

    def _mock_load(self, plugin_dir: Path) -> LoadResult:
        """
        用 importlib 动态加载 plugin.py，构造 MockApi 并调用 register()。
        """
        import time
        start = time.perf_counter()

        # ---- 确定入口文件 ----
        json_path = plugin_dir / "plugin.json"
        entry_point = "plugin.py"
        if json_path.exists():
            try:
                jd = json.loads(json_path.read_text(encoding="utf-8"))
                entry_point = jd.get("entry_point", "plugin.py")
            except Exception:
                pass

        py_path = plugin_dir / entry_point

        if not py_path.exists():
            return LoadResult(
                success=False,
                error=f"入口文件 '{entry_point}' 不存在",
                error_type="FileNotFoundError",
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        # ---- 准备导入环境 ----
        # 将插件 scripts/ 目录加入 sys.path 以支持相对导入
        scripts_dir = plugin_dir / "scripts"
        original_path = list(sys.path)
        try:
            if scripts_dir.is_dir():
                sys.path.insert(0, str(scripts_dir))

            # 清除可能的残留模块缓存
            module_name = f"plugin_{plugin_dir.name}"
            if module_name in sys.modules:
                del sys.modules[module_name]

            # ---- 动态导入 ----
            import importlib.util
            spec = importlib.util.spec_from_file_location(module_name, str(py_path))
            if spec is None or spec.loader is None:
                return LoadResult(
                    success=False,
                    error="无法创建 module spec",
                    error_type="ImportError",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            module = importlib.util.module_from_spec(spec)

            # 注入到 sys.modules 让相对导入能工作
            sys.modules[module_name] = module

            # ---- 创建 MockApi ----
            mock_api = MockApi()
            # 将 mock_api 作为全局变量注入模块
            # （实际 QwenPaw 中是传参给 register，这里我们只做基本测试）
            # 我们需要在模块加载后找到 plugin 对象并调用其 register(mock_api)

            spec.loader.exec_module(module)

            # ---- 获取 plugin 对象并调用 register ----
            plugin_obj = getattr(module, "plugin", None)
            if plugin_obj is None:
                return LoadResult(
                    success=False,
                    error="模块中没有导出 'plugin' 对象",
                    error_type="AttributeError",
                    api_calls=[],
                    runtime_logs=MockRuntimeHelper._log.copy(),
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # 调用 register
            if hasattr(plugin_obj, "register"):
                plugin_obj.register(mock_api)
            elif callable(plugin_obj):
                # 如果 plugin 本身就是函数
                plugin_obj(mock_api)
            else:
                return LoadResult(
                    success=False,
                    error=f"'plugin' 对象没有可调用的 'register' 方法 "
                          f"(type={type(plugin_obj).__name__})",
                    error_type="AttributeError",
                    api_calls=[],
                    runtime_logs=MockRuntimeHelper._log.copy(),
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            return LoadResult(
                success=True,
                api_calls=mock_api.calls,
                runtime_logs=MockRuntimeHelper._log.copy(),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        except Exception as e:
            tb = traceback.format_exc()
            return LoadResult(
                success=False,
                error=str(e),
                error_type=type(e).__name__,
                traceback_str=tb,
                api_calls=[],
                runtime_logs=MockRuntimeHelper._log.copy(),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        finally:
            # 恢复 sys.path
            sys.path[:] = original_path
            MockRuntimeHelper._log.clear()

    @staticmethod
    def _extract_plugin_id(plugin_dir: Path) -> str:
        """尝试提取 plugin ID"""
        jpath = plugin_dir / "plugin.json"
        if jpath.exists():
            try:
                d = json.loads(jpath.read_text(encoding="utf-8"))
                return d.get("id", plugin_dir.name)
            except Exception:
                pass
        return plugin_dir.name

    # ==================================================================
    # 阶段 2: 日志扫描
    # ==================================================================

    def _detect_log_dirs(self) -> List[Path]:
        """
        自动检测 QwenPaw 日志目录。

        优先级：
          1. 构造器传入的路径
          2. 安装目录下的 logs/
          3. WORKING_DIR/logs/
        """
        candidates = []

        if self.qwenpaw_dir:
            candidates.append(self.qwenpaw_dir / "logs")

        # 尝试常见安装位置
        common_roots = [
            Path(r"D:\Program Files\QwenPaw\logs"),
            Path.home() / ".qwenpaw" / "logs",
            Path.home() / ".copaw" / "logs",
        ]
        candidates.extend(common_roots)

        return [c for c in candidates if c.is_dir()]

    def _scan_logs(self, plugin_id: str) -> LogScanResult:
        """
        扫描 QwenPaw 日志，检查指定插件的加载情况。
        """
        log_dirs = self._detect_log_dirs()
        result = LogScanResult(scanned=True)

        if not log_dirs:
            result.info_lines.append("未找到 QwenPaw 日志目录（可能未安装或路径不同）。"
                                     "请确认 QwenPaw 已重启。")
            return result

        for log_dir in log_dirs:
            result.log_dir = log_dir
            log_files = sorted(log_dir.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            # 只看最近的几个日志文件
            recent_logs = log_files[:5]
            result.log_files_checked += len(recent_logs)

            for log_file in recent_logs:
                try:
                    content = log_file.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines()
                except Exception:
                    continue

                for lineno, line in enumerate(lines, start=1):
                    line_lower = line.lower()

                    # 检查是否提到该插件
                    if plugin_id.lower() in line_lower:
                        result.plugin_found_in_log = True

                        # 分类日志级别
                        if any(kw in line for kw in self.LOG_KEYWORDS["error"]):
                            result.errors_found.append({
                                "file": log_file.name,
                                "line": lineno,
                                "message": line.strip()[:200],
                            })
                        elif any(kw in line for kw in self.LOG_KEYWORDS["warning"]):
                            result.warnings_found.append({
                                "file": log_file.name,
                                "line": lineno,
                                "message": line.strip()[:200],
                            })

        return result


# ============================================================
# 便捷函数
# ============================================================

def verify_plugin(plugin_dir: str | Path, **kwargs) -> VerificationResult:
    """对指定插件执行完整运行时验证。"""
    verifier = PluginVerifier(**kwargs)
    return verifier.verify(Path(plugin_dir))


def quick_load_test(plugin_dir: str | Path) -> LoadResult:
    """只做模拟加载测试。"""
    verifier = PluginVerifier()
    return verifier._mock_load(Path(plugin_dir))
