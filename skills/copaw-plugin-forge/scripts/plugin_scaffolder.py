"""
Plugin Scaffolder — QwenPaw 插件脚手架生成器

从 Template 生成完整插件文件树，支持：
- 4 种内置模板（Cron/Channel/Provider/Tool）
- 自由模式（仅 plugin.json + 最小 plugin.py）
- 变量自动推导（CLASS_NAME 从 PLUGIN_ID 推导）
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional

from scripts.plugin_templates import (
    PluginTemplate,
    TemplateFile,
    get_template,
    list_templates,
)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ScaffoldResult:
    """脚手架生成结果"""
    success: bool
    plugin_id: str
    target_dir: Path
    files_created: List[str]
    errors: List[str] = None
    warnings: List[str] = None
    template_id: Optional[str] = None
    variables_used: Dict[str, str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "plugin_id": self.plugin_id,
            "target_dir": str(self.target_dir),
            "files_created": self.files_created,
            "errors": self.errors or [],
            "warnings": self.warnings or [],
            "template_id": self.template_id,
            "variables_used": self.variables_used or {},
        }


# ============================================================
# 核心类：PluginScaffolder
# ============================================================

class PluginScaffolder:
    """
    QwenPaw 插件脚手架生成器。

    用法:
        scaffolder = PluginScaffolder(base_plugins_dir=Path("~/.copaw/plugins"))
        result = scaffolder.scaffold(
            plugin_id="my-cron-task",
            template_id="cron-job",
            variables={
                "PLUGIN_NAME": "My Cron Task",
                "DESCRIPTION": "A custom cron job",
                "CRON_EXPRESSION": "0 */3 * * *",
                "TIMEZONE": "Asia/Shanghai",
            },
        )
    """

    # 默认变量推导规则
    ID_PATTERN = re.compile(r"^[a-z][a-z0-9_\-]*$")

    def __init__(
        self,
        base_plugins_dir: Optional[Path] = None,
        overwrite: bool = False,
    ):
        """
        Args:
            base_plugins_dir: 插件根目录，默认 ~/.copaw/plugins
            overwrite: 是否覆盖已存在的文件
        """
        self.base_plugins_dir = base_plugins_dir or self._default_plugins_dir()
        self.overwrite = overwrite
        self._results_history: List[ScaffoldResult] = []

    @staticmethod
    def _default_plugins_dir() -> Path:
        """检测默认插件目录（兼容 .copaw / .qwenpaw）"""
        home = Path.home()
        copaw_plugins = home / ".copaw" / "plugins"
        qwenpaw_plugins = home / ".qwenpaw" / "plugins"
        if copaw_plugins.exists():
            return copaw_plugins
        return qwenpaw_plugins

    # ==================================================================
    # 公开 API
    # ==================================================================

    def scaffold(
        self,
        plugin_id: str,
        template_id: Optional[str] = None,
        variables: Optional[Dict[str, str]] = None,
        output_dir: Optional[Path] = None,
    ) -> ScaffoldResult:
        """
        从模板生成插件。

        Args:
            plugin_id: 插件 ID（如 my-plugin）
            template_id: 模板 ID 或 None（自由模式）
            variables: 模板变量填充值
            output_dir: 自定义输出目录（默认 base_plugins_dir/plugin_id）

        Returns:
            ScaffoldResult 包含生成结果详情
        """
        errors = []
        warnings = []
        variables = dict(variables or {})

        # ---- 阶段 1：验证 plugin_id ----
        id_errors = self._validate_plugin_id(plugin_id)
        if id_errors:
            return ScaffoldResult(
                success=False,
                plugin_id=plugin_id,
                target_dir=output_dir or (self.base_plugins_dir / plugin_id),
                files_created=[],
                errors=id_errors,
            )

        # 确保 PLUGIN_ID 在变量中
        variables.setdefault("PLUGIN_ID", plugin_id)

        # 自动推导 CLASS_NAME
        if "CLASS_NAME" not in variables:
            variables["CLASS_NAME"] = self._derive_class_name(plugin_id)

        # ---- 阶段 2：加载模板 ----
        template = None
        if template_id:
            template = get_template(template_id)
            if not template:
                return ScaffoldResult(
                    success=False,
                    plugin_id=plugin_id,
                    target_dir=output_dir or (self.base_plugins_dir / plugin_id),
                    files_created=[],
                    errors=[f"Template '{template_id}' not found. "
                             f"Available: {list(TEMPLATE_IDS)}"],
                )
        else:
            template = self._get_freeform_template()

        # 检查必填变量是否齐全
        missing = [v for v in template.variables if not variables.get(v)]
        if missing:
            errors.append(f"Missing required variables: {', '.join(missing)}")
            # 尝试从已有信息推导默认值
            for var in list(missing):
                default = self._try_derive_variable(var, variables)
                if default is not None:
                    variables[var] = default
                    missing.remove(var)
                    warnings.append(f"Auto-derived {var} = '{default}'")
            if missing:
                return ScaffoldResult(
                    success=False,
                    plugin_id=plugin_id,
                    target_dir=output_dir or (self.base_plugins_dir / plugin_id),
                    files_created=[],
                    errors=errors,
                    warnings=warnings,
                    template_id=template.id,
                )

        # 处理可选变量的默认值
        for var in template.optional_variables:
            if var not in variables or not variables[var]:
                colon_idx = var.find(":-")
                if colon_idx > 0:
                    variables[var] = var[colon_idx + 2:]

        # ---- 阶段 3：确定输出目录并创建 ----
        target_dir = output_dir or (self.base_plugins_dir / plugin_id)

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ScaffoldResult(
                success=False,
                plugin_id=plugin_id,
                target_dir=target_dir,
                files_created=[],
                errors=[f"Cannot create directory {target_dir}: {e}"],
                template_id=template.id,
            )

        # ---- 阶段 4：逐文件生成 ----
        files_created = []
        for tmpl_file in template.files:
            file_path = target_dir / tmpl_file.relative_path

            if file_path.exists() and not self.overwrite:
                warnings.append(f"Skipped existing: {tmpl_file.relative_path}")
                continue

            try:
                content = self._render_template(tmpl_file.content_template, variables)
                file_path.write_text(content, encoding="utf-8", newline="\n")
                files_created.append(str(file_path))
            except Exception as e:
                errors.append(f"Failed to write {tmpl_file.relative_path}: {e}")

        # ---- 阶段 5：创建子目录和 __init__.py ----
        self._ensure_scripts_package(target_dir)

        result = ScaffoldResult(
            success=len(errors) == 0 and len(files_created) > 0,
            plugin_id=plugin_id,
            target_dir=target_dir,
            files_created=files_created,
            errors=errors or None,
            warnings=warnings or None,
            template_id=template.id,
            variables_used=dict(variables),
        )
        self._results_history.append(result)
        return result

    def scaffold_freeform(
        self,
        plugin_id: str,
        description: str = "",
        author: str = "Plugin Author",
        **extra_vars,
    ) -> ScaffoldResult:
        """
        自由模式生成 — 最小化插件骨架。

        只包含 plugin.json + 基础 plugin.py，无特定能力绑定。
        """
        variables = {
            "PLUGIN_ID": plugin_id,
            "PLUGIN_NAME": plugin_id.replace("-", " ").title(),
            "DESCRIPTION": description or f"A custom QwenPaw plugin: {plugin_id}",
            "AUTHOR": author,
            **extra_vars,
        }
        return self.scaffold(plugin_id=plugin_id, template_id=None, variables=variables)

    # ==================================================================
    # 内部方法
    # ==================================================================

    @staticmethod
    def _validate_plugin_id(plugin_id: str) -> List[str]:
        """验证 plugin_id 合法性"""
        errors = []
        if not plugin_id:
            errors.append("plugin_id cannot be empty")
        elif not PluginScaffolder.ID_PATTERN.match(plugin_id):
            errors.append(
                f"Invalid plugin_id '{plugin_id}': "
                f"must match [a-z][a-z0-9_-]*"
            )
        if len(plugin_id) > 64:
            errors.append(f"plugin_id too long ({len(plugin_id)} > 64)")
        return errors

    @staticmethod
    def _derive_class_name(plugin_id: str) -> str:
        """从 plugin_id 推导 Python 类名（PascalCase）"""
        parts = re.split(r'[_\-]+', plugin_id)
        return ''.join(p.title() for p in parts) + 'Plugin'

    @staticmethod
    def _try_derive_variable(var_name: str, existing: Dict[str, str]) -> Optional[str]:
        """尝试从已有信息推导变量默认值"""
        plugin_id = existing.get("PLUGIN_ID", "")
        name = existing.get("PLUGIN_NAME", "")

        derivation_rules = {
            "PLUGIN_NAME": lambda: plugin_id.replace("-", " ").title(),
            "DESCRIPTION": lambda: f"QwenPaw plugin: {plugin_id}",
            "AUTHOR": lambda: "Plugin Author",
            "VERSION": lambda: "0.1.0",
            "LICENSE": lambda: "MIT",
            "TASK_NAME": lambda: f"{plugin_id}_task",
            "CHANNEL_TYPE": lambda: "custom",
            "WEBHOOK_PATH": lambda: f"/webhook/{plugin_id}",
            "PROVIDER_ID": lambda: plugin_id,
            "BASE_URL": lambda: "https://api.example.com/v1",
            "MODEL_NAMES": lambda: '["model-default"]',
            "API_KEY_ENV": lambda: "",
            "CRON_EXPRESSION": lambda: "0 2 * * *",
            "TIMEZONE": lambda: "Asia/Shanghai",
            "TOOL_COUNT": lambda: "0",
        }

        handler = derivation_rules.get(var_name)
        return handler() if handler else None

    @staticmethod
    def _render_template(template_str: str, variables: Dict[str, str]) -> str:
        """
        渲染 string.Template，支持 ${VAR} 和 ${VAR:-default} 语法。
        """
        # 先处理 ${VAR:-default} 语法 → 转为普通 ${VAR}
        resolved_vars = {}
        for key, value in variables.items():
            resolved_vars[key] = value

        def replace_default(match):
            var_name = match.group(1)
            default_val = match.group(2) or ""
            return resolved_vars.get(var_name, default_val)

        # 替换 ${VAR:-default} 为实际值
        preprocessed = re.sub(
            r'\$\{([A-Z_][A-Z0-9_]*)[:-](.*?)\}',
            replace_default,
            template_str,
        )

        # 用标准 Template 渲染剩余的 ${VAR}
        tpl = Template(preprocessed)
        return tpl.safe_substitute(resolved_vars)

    @staticmethod
    def _ensure_scripts_package(target_dir: Path):
        """确保 scripts/ 目录存在且有 __init__.py"""
        scripts_dir = target_dir / "scripts"
        if scripts_dir.exists():
            init_file = scripts_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text(
                    '"""\n${PLUGIN_ID} scripts package\n"""\n'
                    .replace("${PLUGIN_ID}", target_dir.name),
                    encoding="utf-8",
                )

    @staticmethod
    def _get_freeform_template() -> PluginTemplate:
        """返回自由模式最小模板"""
        from scripts.plugin_templates import TemplateFile
        return PluginTemplate(
            id="freeform",
            name="📝 自定义插件",
            description="空白模板，包含最基本的 plugin.json 和 plugin.py。",
            category="custom",
            variables=["PLUGIN_ID"],
            optional_variables=[
                "PLUGIN_NAME", "DESCRIPTION", "AUTHOR", "VERSION", "LICENSE",
            ],
            files=[
                TemplateFile(
                    relative_path="plugin.json",
                    content_template="""\
{
  "id": "${PLUGIN_ID}",
  "name": "${PLUGIN_NAME:-${PLUGIN_ID}}",
  "version": "${VERSION:-0.1.0}",
  "description": "${DESCRIPTION:-Custom QwenPaw plugin}",
  "author": "${AUTHOR:-Plugin Author}",
  "license": "${LICENSE:-MIT}",
  "entry_point": "plugin.py",
  "capabilities": ["control_command", "startup_hook"],
  "permissions": ["command:register", "hook:register"],
  "dependencies": [],
  "hybrid_mode": true
}
""",
                ),
                TemplateFile(
                    relative_path="plugin.py",
                    content_template='''\
"""${PLUGIN_NAME:-${PLUGIN_ID}} - QwenPaw Plugin."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ${CLASS_NAME}Plugin:
    """
    ${PLUGIN_NAME:-${PLUGIN_ID}}
    """

    def __init__(self):
        self._api: Optional[Any] = None
        self._config: Dict[str, Any] = {}

    def register(self, api) -> None:
        """Plugin 入口点."""
        self._api = api
        logger.info("🔧 Registering %s...", self.__class__.__name__)

        plugin_config = getattr(api, "config", {}) or {}
        self._config.update(plugin_config)

        api.register_startup_hook(
            hook_name="${PLUGIN_ID}_init",
            callback=self._on_startup,
            priority=50,
        )

        api.register_shutdown_hook(
            hook_name="${PLUGIN_ID}_cleanup",
            callback=self._on_shutdown,
            priority=100,
        )

        logger.info("✅ %s registered", self.__class__.__name__)

    async def _on_startup(self):
        """启动钩子."""
        logger.info("[%s] 🚀 Ready", "${PLUGIN_ID}")

    async def _on_shutdown(self):
        """关闭钩子."""
        logger.info("[%s] 🔌 Shutdown", "${PLUGIN_ID}")

    def cmd_status(self) -> Dict[str, Any]:
        """查看状态。用法: /${PLUGIN_ID} status"""
        return {"plugin_id": "${PLUGIN_ID}", "config": self._config}


plugin = ${CLASS_NAME}Plugin()
''',
                ),
            ],
        )


# ============================================================
# 便捷函数
# ============================================================

TEMPLATE_IDS = [
    "cron-job",
    "channel-bridge",
    "provider-extender",
    "tool-extension",
]


def quick_scaffold(
    plugin_id: str,
    template_id: str = "freeform",
    **variables,
) -> ScaffoldResult:
    """快速生成插件的便捷函数。"""
    scaffolder = PluginScaffolder()
    return scaffolder.scaffold(
        plugin_id=plugin_id,
        template_id=template_id,
        variables=variables,
    )
