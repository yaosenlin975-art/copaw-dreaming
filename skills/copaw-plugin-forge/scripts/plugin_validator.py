"""
Plugin Validator — QwenPaw 插件静态验证器

四层验证：
  1. JSON 校验 — plugin.json 格式 + 必填字段 + schema 一致性
  2. AST 校验 — plugin.py 语法 + 导出对象 + register() 方法
  3. 安全扫描 — 危险导入、硬编码密钥、路径穿越
  4. API 合规性 — api.register_* 调用签名匹配
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 数据模型
# ============================================================


class Severity(Enum):
    """问题严重级别"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """单个验证问题"""
    severity: Severity
    category: str          # 分类：json / syntax / security / api_compliance
    message: str           # 描述
    file: str = ""         # 相关文件（相对路径）
    line: int = 0          # 行号（如果有）
    suggestion: str = ""   # 修复建议


@dataclass
class ValidationResult:
    """完整验证结果"""
    valid: bool
    plugin_id: str
    plugin_dir: Path
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_run: Dict[str, bool] = field(default_factory=dict)
    summary: Dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "plugin_id": self.plugin_id,
            "plugin_dir": str(self.plugin_dir),
            "issue_count": len(self.issues),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "checks_run": self.checks_run,
            "summary": {
                "error": len(self.errors),
                "warning": len(self.warnings),
                "info": len(self.issues) - len(self.errors) - len(self.warnings),
            },
            "issues": [
                {
                    "severity": i.severity.value,
                    "category": i.category,
                    "message": i.message,
                    "file": i.file,
                    "line": i.line,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }

    def to_report_markdown(self) -> str:
        """生成 Markdown 格式的验证报告"""
        lines = [
            f"# 🔍 Plugin 验证报告: `{self.plugin_id}`",
            f"",
            f"**状态**: {'✅ 通过' if self.valid else '❌ 不通过'}",
            f"**目录**: `{self.plugin_dir}`",
            f"**问题总数**: {len(self.issues)} "
            f"(🔴 {len(self.errors)} / 🟡 {len(self.warnings)} / "
            f"ℹ️ {len(self.issues) - len(self.errors) - len(self.warnings)})",
            f"",
        ]

        # 检查项概览
        lines.append("## 检查项")
        for check_name, passed in self.checks_run.items():
            status_icon = "✅" if passed else "⚠️"
            lines.append(f"- {status_icon} **{check_name}**")
        lines.append("")

        # 问题详情
        if self.issues:
            lines.append("## 问题详情")
            for issue in self.issues:
                icon = {"error": "🔴", "warning": "🟡", "info": "ℹ️"}.get(
                    issue.severity.value, "•"
                )
                loc = ""
                if issue.file:
                    loc = f"`{issue.file}"
                    if issue.line:
                        loc += f":{issue.issue.line}"
                    loc += "`"
                lines.append(f"### {icon} [{issue.severity.value.upper()}] {issue.message}")
                if loc:
                    lines.append(f"- **位置**: {loc}")
                if issue.suggestion:
                    lines.append(f"- **建议**: {issue.suggestion}")
                lines.append("")
        else:
            lines.append("## ✅ 无问题发现")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# 安全规则定义
# ============================================================

DANGEROUS_IMPORTS = {
    # 危险执行
    "os.system": "使用 subprocess.run() 替代，或添加输入校验",
    "os.popen": "使用 subprocess.Popen 并设置 shell=False",
    "subprocess.call": "确认参数不来自用户输入，优先用 subprocess.run",
    "subprocess.Popen": "确保 shell=False 且参数列表化",
    "eval(": "避免 eval，改用 ast.literal_eval 或 json.loads",
    "exec(": "避免 exec，改用显式代码路径",
    "compile(": "如必须使用，限制 globals/locals 范围",
    "__import__": "使用标准 import 语句",
    # 网络危险
    "pickle.load": "使用 json 替代 pickle（反序列化风险）",
    "pickle.loads": "同上",
    "marshal.load": "使用安全的数据序列化格式",
    "yaml.load(": "指定 Loader=yaml.SafeLoader",
}

SECRET_PATTERNS = [
    (re.compile(r'(?:api[_-]?key|apikey)["\s]*[:=]\s*["\'][a-zA-Z0-9]{20,}', re.I),
     "检测到疑似硬编码 API Key"),
    (re.compile(r'(?:secret|password|token)["\s]*[:=]\s*["\'][a-zA-Z0-9]{12,}', re.I),
     "检测到疑似硬编码密钥/密码/token"),
    (re.compile(r'[A-Za-z0-9+/]{40,}={0,2}'),
     "检测到疑似 Base64 编码的长字符串（可能为密钥）"),
]

PATH_TRAVERSAL_PATTERNS = [
    re.compile(r'\.\.[/\\]'),
    re.compile(r'Path\s*\(\s*["\'].*\.\.\/'),
]


# ============================================================
# 核心类：PluginValidator
# ============================================================

class PluginValidator:
    """
    QwenPaw 插件静态验证器。

    用法:
        validator = PluginValidator()
        result = validator.validate(plugin_dir=Path("~/.copaw/plugins/my-plugin"))
        print(result.to_report_markdown())
    """

    # JSON 必填字段
    JSON_REQUIRED_FIELDS = ["id", "name", "version", "description"]
    JSON_RECOMMENDED_FIELDS = ["author", "entry_point"]

    # Plugin API 合法方法名
    VALID_API_METHODS = frozenset({
        "register_provider",
        "register_startup_hook",
        "register_shutdown_hook",
        "register_control_command",
    })

    def __init__(self, strict_mode: bool = False):
        """
        Args:
            strict_mode: True 时 warning 也视为失败
        """
        self.strict_mode = strict_mode

    def validate(self, plugin_dir: Path) -> ValidationResult:
        """
        对插件目录执行完整的四层静态验证。

        Args:
            plugin_dir: 插件根目录路径

        Returns:
            ValidationResult 完整结果
        """
        plugin_dir = Path(plugin_dir).resolve()
        issues: List[ValidationIssue] = []
        checks: Dict[str, bool] = {}

        # ---- 阶段 1：JSON 校验 ----
        json_result = self._check_plugin_json(plugin_dir)
        issues.extend(json_result["issues"])
        checks["plugin.json"] = json_result["passed"]
        plugin_json_data = json_result.get("data")

        # ---- 阶段 2：AST 语法校验 ----
        ast_result = self._check_plugin_py(plugin_dir)
        issues.extend(ast_result["issues"])
        checks["plugin.py"] = ast_result["passed"]
        py_ast = ast_result.get("ast")  # type: Optional[ast.Module]

        # ---- 阶段 3：安全扫描 ----
        sec_result = self._security_scan(plugin_dir, py_ast)
        issues.extend(sec_result["issues"])
        checks["security_scan"] = sec_result["passed"]

        # ---- 阶段 4：API 合规性检查 ----
        api_result = self._check_api_compliance(py_ast, plugin_json_data)
        issues.extend(api_result["issues"])
        checks["api_compliance"] = api_result["passed"]

        # ---- 汇总 ----
        has_errors = any(i.severity == Severity.ERROR for i in issues)
        is_valid = not has_errors and all(checks.values())

        if self.strict_mode and issues:
            is_valid = False

        result = ValidationResult(
            valid=is_valid,
            plugin_id=(plugin_json_data or {}).get("id", plugin_dir.name),
            plugin_dir=plugin_dir,
            issues=issues,
            checks_run=checks,
            summary={
                "error": sum(1 for i in issues if i.severity == Severity.ERROR),
                "warning": sum(1 for i in issues if i.severity == Severity.WARNING),
                "info": sum(1 for i in issues if i.severity == Severity.INFO),
            },
        )
        return result

    # ==================================================================
    # 阶段 1: JSON 校验
    # ==================================================================

    def _check_plugin_json(self, plugin_dir: Path) -> Dict[str, Any]:
        """检查 plugin.json 的格式和内容"""
        issues = []
        json_path = plugin_dir / "plugin.json"

        if not json_path.exists():
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="json",
                message="缺少 plugin.json 文件",
                file="plugin.json",
                suggestion="创建包含 id/name/version/description 的 plugin.json",
            ))
            return {"issues": issues, "passed": False}

        # ---- 语法解析 ----
        try:
            raw_text = json_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="json",
                message=f"JSON 解析错误: {e}",
                file="plugin.json",
                line=e.lineno or 0,
                suggestion="检查 JSON 语法（括号、逗号、引号等）",
            ))
            return {"issues": issues, "passed": False}
        except Exception as e:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="json",
                message=f"无法读取文件: {e}",
                file="plugin.json",
            ))
            return {"issues": issues, "passed": False}

        # ---- 必填字段 ----
        for field_name in self.JSON_REQUIRED_FIELDS:
            if field_name not in data:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    category="json",
                    message=f"缺少必填字段 '{field_name}'",
                    file="plugin.json",
                    suggestion=f"在 plugin.json 中添加 \"{field_name}\": \"<value>\"",
                ))

        # ---- 推荐字段 ----
        for field_name in self.JSON_RECOMMENDED_FIELDS:
            if field_name not in data:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    category="json",
                    message=f"推荐添加字段 '{field_name}'",
                    file="plugin.json",
                    suggestion=f"可选地添加 \"{field_name}\": \"<value>\" 以提高可维护性",
                ))

        # ---- 字段值校验 ----
        pid = data.get("id", "")
        if pid and not re.match(r'^[a-z][a-z0-9_\-]*$', pid):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="json",
                message=f"无效的 id '{pid}': 应为小写字母开头，含字母/数字/连字符/下划线",
                file="plugin.json",
                suggestion='改为类似 "my-plugin" 或 "my_plugin"',
            ))

        version = data.get("version", "")
        if version and not re.match(r'^\d+\.\d+\.\d+', str(version)):
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                category="json",
                message=f"版本号 '{version}' 不是语义版本格式（推荐 MAJOR.MINOR.PATCH）",
                file="plugin.json",
                suggestion='使用 "0.1.0" 格式',
            ))

        # entry_point 默认值
        ep = data.get("entry_point", "")
        if ep and ep != "plugin.py":
            issues.append(ValidationIssue(
                severity=Severity.INFO,
                category="json",
                message=f"自定义入口文件 '{ep}'（默认为 plugin.py）",
                file="plugin.json",
            ))

        # capabilities 与 permissions 交叉检查
        caps = set(data.get("capabilities", []))
        perms = set(data.get("permissions", []))

        capability_perm_map = {
            "provider_extension": "provider:register",
            "cron_scheduling": "cron:register",
            "startup_hook": "hook:register",
            "shutdown_hook": "hook:register",
            "control_command": "command:register",
            "memory_consolidation": "memory:read",
        }
        for cap, expected_perm in capability_perm_map.items():
            if cap in caps and expected_perm not in perms:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    category="json",
                    message=f"声明了能力 '{cap}' 但未请求权限 '{expected_perm}'",
                    file="plugin.json",
                    suggestion=f"在 permissions 中添加 \"{expected_perm}\"",
                ))

        # dependencies 可空检查
        deps = data.get("dependencies")
        if deps is None:
            pass  # 缺失是 OK 的
        elif not isinstance(deps, list):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="json",
                message="'dependencies' 应为数组类型",
                file="plugin.json",
                suggestion='"dependencies": []',
            ))

        return {"issues": issues, "passed": not any(
            i.severity == Severity.ERROR for i in issues
        ), "data": data}

    # ==================================================================
    # 阶段 2: AST 语法校验
    # ==================================================================

    def _check_plugin_py(self, plugin_dir: Path) -> Dict[str, Any]:
        """检查 plugin.py 的 Python AST 结构"""
        issues = []
        py_path = plugin_dir / "plugin.json"
        # 先从 plugin.json 确认实际入口文件
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
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="syntax",
                message=f"缺少入口文件 '{entry_point}'",
                file=entry_point,
                suggestion=f"创建包含 register(api) 方法的 {entry_point}",
            ))
            return {"issues": issues, "passed": False}

        # ---- AST 解析 ----
        source = py_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_path))
        except SyntaxError as e:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="syntax",
                message=f"Python 语法错误: {e.msg}",
                file=entry_point,
                line=e.lineno or 0,
                suggestion="修正语法错误后重新验证",
            ))
            return {"issues": issues, "passed": False}

        # ---- 检查导出的 `plugin` 对象 ----
        module_level_assigns = [
            node for node in tree.body
            if isinstance(node, ast.Assign)
        ]
        plugin_names_found = []
        for assign_node in module_level_assigns:
            for target in assign_node.targets:
                if isinstance(target, ast.Name) and target.id == "plugin":
                    plugin_names_found.append("plugin")

        if not plugin_names_found:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="syntax",
                message="未找到模块级 'plugin' 对象赋值（PluginLoader 需要 plugin.register(api)）",
                file=entry_point,
                suggestion='在文件末尾添加: plugin = YourPluginClass()',
            ))

        # ---- 检查类中是否有 register 方法 ----
        classes_with_register = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if "register" in methods:
                    classes_with_register.append(node.name)

        if not classes_with_register:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                category="syntax",
                message="未找到包含 register() 方法的类",
                file=entry_point,
                suggestion='创建一个类并实现 def register(self, api): ... 方法',
            ))
        elif len(classes_with_register) > 1:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                category="syntax",
                message=f"多个类都有 register() 方法: {classes_with_register}",
                file=entry_point,
                suggestion="确认哪个类被实例化为 plugin 对象",
            ))

        # ---- 检查 register 方法签名 ----
        for class_node in ast.walk(tree):
            if isinstance(class_node, ast.ClassDef) and class_node.name in classes_with_register:
                for item in class_node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                       and item.name == "register":
                        args = item.args
                        arg_names = [a.arg for a in args.args]
                        if "api" not in arg_names and "self" not in arg_names:
                            issues.append(ValidationIssue(
                                severity=Severity.ERROR,
                                category="syntax",
                                message="register 方法签名异常（期望 register(self, api)）",
                                file=entry_point,
                                line=item.lineno,
                            ))

        # ---- 检查 imports 基本合理性 ----
        import_issues = self._check_imports(tree, entry_point)
        issues.extend(import_issues)

        return {
            "issues": issues,
            "passed": not any(i.severity == Severity.ERROR for i in issues),
            "ast": tree,
        }

    @staticmethod
    def _check_imports(tree: ast.AST, file_label: str) -> List[ValidationIssue]:
        """检查 import 语句的基本合理性"""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "." in node.module and node.module.startswith("."):
                    # 相对导入 — 在插件环境中需要 sys.path 设置
                    pass  # 这是正常的，PluginLoader 会处理

                # 检查是否使用了已废弃模块
                deprecated_modules = {
                    "optparse": "请使用 argparse",
                    "imp": "请使用 importlib",
                    "parser": "请使用 ast",
                }
                if node.module in deprecated_modules:
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        category="syntax",
                        message=f"使用了已废弃模块 '{node.module}': "
                               f"{deprecated_modules[node.module]}",
                        file=file_label,
                        line=node.lineno,
                    ))

        return issues

    # ==================================================================
    # 阶段 3: 安全扫描
    # ==================================================================

    def _security_scan(
        self, plugin_dir: Path, py_ast: Optional[ast.AST]
    ) -> Dict[str, Any]:
        """
        对插件所有 .py 文件执行安全扫描。
        """
        issues = []

        # ---- 扫描所有 .py 文件 ----
        py_files = list(plugin_dir.rglob("*.py"))
        for py_file in py_files:
            rel_path = py_file.relative_to(plugin_dir)
            rel_str = str(rel_path).replace("\\", "/")

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue  # 语法错误已在阶段 2 报告

            # 3a. 危险导入/调用检测（基于源码文本 + AST 结合）
            issues.extend(self._scan_dangerous_calls(source, rel_str, tree))

            # 3b. 硬编码密钥检测
            issues.extend(self._scan_secrets(source, rel_str))

            # 3c. 路径穿越检测
            issues.extend(self._scan_path_traversal(source, rel_str))

        # ---- scripts/ 目录权限提醒 ----
        scripts_dir = plugin_dir / "scripts"
        if scripts_dir.exists():
            for script_file in scripts_dir.rglob("*.py"):
                rel_script = str(script_file.relative_to(plugin_dir)).replace("\\", "/")
                src = script_file.read_text(encoding="utf-8")
                if "open(" in src and ("w" in src or "a" in src or "+" in src):
                    # 检测写入操作的目标
                    issues.append(ValidationIssue(
                        severity=Severity.INFO,
                        category="security",
                        message=f"{rel_script} 包含文件写入操作",
                        file=rel_script,
                        suggestion="确认写入路径受控且不会覆盖用户数据",
                    ))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return {"issues": issues, "passed": passed}

    @staticmethod
    def _scan_dangerous_calls(
        source: str, rel_str: str, tree: ast.AST
    ) -> List[ValidationIssue]:
        """扫描危险函数调用"""
        issues = []
        lines = source.splitlines()

        for pattern, suggestion in DANGEROUS_IMPORTS.items():
            # 文本级快速扫描
            for lineno, line in enumerate(lines, start=1):
                if pattern.rstrip("(") in line:
                    # 排除注释行
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        category="security",
                        message=f"检测到危险模式 '{pattern}': {suggestion}",
                        file=rel_str,
                        line=lineno,
                        suggestion=suggestion,
                    ))

        return issues

    @staticmethod
    def _scan_secrets(source: str, rel_str: str) -> List[ValidationIssue]:
        """扫描硬编码的密钥/密码/token"""
        issues = []
        for pattern, msg in SECRET_PATTERNS:
            for match in pattern.finditer(source):
                lineno = source[:match.start()].count("\n") + 1
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    category="security",
                    message=msg,
                    file=rel_str,
                    line=lineno,
                    suggestion="移除硬编码凭证，改用环境变量或配置文件",
                ))
        return issues

    @staticmethod
    def _scan_path_traversal(source: str, rel_str: str) -> List[ValidationIssue]:
        """扫描可能的路径穿越攻击"""
        issues = []
        for pattern in PATH_TRAVERSAL_PATTERNS:
            for match in pattern.finditer(source):
                lineno = source[:match.start()].count("\n") + 1
                context_line = source.splitlines()[max(0, lineno - 1)]
                # 排除注释中的 ".."
                stripped = context_line.lstrip()
                if stripped.startswith("#"):
                    continue
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    category="security",
                    message="检测到可能的路径穿越模式 '..'",
                    file=rel_str,
                    line=lineno,
                    suggestion="确保路径经过 sanitize 或使用 pathlib.Path.resolve() 限定范围",
                ))
        return issues

    # ==================================================================
    # 阶段 4: API 合规性检查
    # ==================================================================

    def _check_api_compliance(
        self, py_ast: Optional[ast.AST], plugin_json_data: Optional[Dict]
    ) -> Dict[str, Any]:
        """检查 plugin.py 中对 PluginApi 的调用是否符合规范"""
        issues = []

        if not py_ast:
            return {"issues": [], "passed": True}

        # ---- 收集 api.xxx() 调用 ----
        api_calls = []  # (method_name, line_no, is_async)
        for node in ast.walk(py_ast):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if func.value.id == "api":
                        method_name = func.attr
                        is_async = False
                        # 向上查找是否在 async 函数中
                        for parent in ast.walk(py_ast):
                            if parent is node:
                                break
                            if isinstance(parent, (ast.AsyncFunctionDef,)):
                                is_async = True
                        api_calls.append((method_name, node.lineno, is_async))

        # ---- 检查调用的方法是否合法 ----
        registered_apis = set()
        for method_name, lineno, is_async in api_calls:
            if method_name.startswith("_"):
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    category="api_compliance",
                    message=f"调用了私有 API 方法 'api.{method_name}()' "
                           f"(可能在未来版本移除)",
                    file="plugin.py",
                    line=lineno,
                    suggestion="仅使用官方文档中的公共 API",
                ))
            elif method_name not in self.VALID_API_METHODS:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    category="api_compliance",
                    message=f"未知 API 方法 'api.{method_name}()'",
                    file="plugin.py",
                    line=lineno,
                    suggestion=f"合法方法: {', '.join(sorted(self.VALID_API_METHODS))}",
                ))
            registered_apis.add(method_name)

        # ---- capabilities 与实际 API 调用一致性 ----
        if plugin_json_data:
            caps = set(plugin_json_data.get("capabilities", []))
            cap_api_map = {
                "provider_extension": "register_provider",
                "startup_hook": "register_startup_hook",
                "shutdown_hook": "register_shutdown_hook",
                "control_command": "register_control_command",
            }
            for cap, required_method in cap_api_map.items():
                if cap in caps and required_method not in registered_apis:
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        category="api_compliance",
                        message=f"声明了能力 '{cap}' 但未调用 "
                               f"'api.{required_method}()'",
                        file="plugin.py",
                        suggestion=f"在 register() 方法中添加 api.{required_method}(...) 调用",
                    ))

        # ---- hook priority 范围检查 ----
        for node in ast.walk(py_ast):
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Attribute)
                    and func.attr in ("register_startup_hook", "register_shutdown_hook")
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "api"):

                    # 查找 keyword argument 'priority'
                    for kw in node.keywords:
                        if kw.arg == "priority":
                            if isinstance(kw.value, ast.Constant):
                                val = kw.value.value
                                if not isinstance(val, int) or val < 0 or val > 100:
                                    issues.append(ValidationIssue(
                                        severity=Severity.WARNING,
                                        category="api_compliance",
                                        message=f"hook priority={val} 超出推荐范围 [0, 100]",
                                        file="plugin.py",
                                        line=node.lineno,
                                        suggestion="使用 0-100 的整数（数字越小越先执行）",
                                    ))

        passed = not any(i.severity == Severity.ERROR for i in issues)
        return {"issues": issues, "passed": passed}


# ============================================================
# 便捷函数
# ============================================================

def validate_plugin(plugin_dir: str | Path) -> ValidationResult:
    """对指定插件目录执行完整验证。"""
    validator = PluginValidator()
    return validator.validate(Path(plugin_dir))


def quick_validate_json(json_path: str | Path) -> List[ValidationIssue]:
    """只验证 plugin.json。"""
    from os.path import dirname
    validator = PluginValidator()
    return validator._check_plugin_json(Path(json_path).parent)["issues"]


def quick_validate_python(py_path: str | Path) -> List[ValidationIssue]:
    """只验证 plugin.py AST。"""
    from os.path import dirname
    validator = PluginValidator()
    return validator._check_plugin_py(Path(py_path).parent)["issues"]
