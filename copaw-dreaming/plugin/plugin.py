"""
copaw-dreaming - QwenPaw Plugin 入口

本文件是 QwenPaw 插件系统的入口点（entry_point）。
PluginLoader 加载后：
  1. 动态导入本模块
  2. 查找 `plugin` 对象
  3. 调用 plugin.register(api)

符合 QwenPaw v1.1.0 Plugin API v1 规范。
参考：qwenpaw/plugins/loader.py
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

# 导入核心模块
from scripts.dreaming_config import DreamingConfig, DEFAULT_CONFIG
from scripts.dreaming_daemon import DreamingDaemon

logger = logging.getLogger(__name__)


class DreamingPlugin:
    """
    🌙 Dreaming 记忆整合插件

    为 QwenPaw 提供自动化的记忆巩固能力：
    - 通过 startup_hook 初始化守护进程
    - 可选注册控制命令 (/dreaming status, /dreaming run)
    - 支持通过 Cron 系统定时执行
    """

    def __init__(self):
        self._daemon: Optional[DreamingDaemon] = None
        self._api: Optional[Any] = None
        self._config: DreamingConfig = DEFAULT_CONFIG

    def register(self, api) -> None:
        """
        Plugin 入口点 — 由 PluginLoader 在加载时调用。

        Args:
            api: PluginApi 实例，提供 register_provider/hook/command 方法
                以及 runtime 属性访问 RuntimeHelpers
        """
        self._api = api
        logger.info("🌙 Registering Dreaming Plugin...")

        # 1. 从 plugin.json meta 或 config 合并配置
        plugin_config = api.config if hasattr(api, 'config') else {}
        if plugin_config:
            self._config = DreamingConfig.from_dict(plugin_config)
            logger.info("  Custom config loaded from plugin.json config")

        # 2. 确定工作区目录（从 runtime 或环境变量）
        workspace_dir = self._resolve_workspace_dir(api)

        # 3. 创建守护进程实例
        dry_run = plugin_config.get("dry_run", False)
        self._daemon = DreamingDaemon(
            workspace_dir=workspace_dir,
            config=self._config,
            dry_run=dry_run,
        )

        # 4. 注册 Startup Hook — QwenPaw 启动时初始化 daemon
        api.register_startup_hook(
            hook_name="dreaming_init",
            callback=self._on_startup,
            priority=50,  # 中等优先级（让其他基础 hook 先跑）
        )

        # 5. 注册 Shutdown Hook — QwenPaw 关闭时清理
        api.register_shutdown_hook(
            hook_name="dreaming_cleanup",
            callback=self._on_shutdown,
            priority=100,
        )

        logger.info(
            "🌙 Dreaming Plugin registered successfully "
            "(workspace=%s, dry_run=%s)",
            workspace_dir, dry_run,
        )

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def _on_startup(self):
        """启动钩子 — 初始化守护进程"""
        try:
            await self._daemon.on_startup()
            if self._api and self._api.runtime:
                self._api.runtime.log_info(
                    "🌙 Dreaming Daemon initialized"
                )
        except Exception as e:
            logger.error("Dreaming startup hook failed: %s", e, exc_info=True)
            if self._api and self._api.runtime:
                self._api.runtime.log_error(
                    f"Dreaming startup failed: {e}", exc_info=True
                )

    async def _on_shutdown(self):
        """关闭钩子 — 清理资源"""
        logger.info("🌙 Dreaming Plugin shutting down...")
        # 当前没有需要清理的持久连接或线程
        # 预留扩展空间：停止后台任务、刷新状态等

    # ------------------------------------------------------------------
    # 控制命令（可通过 /dreaming 触发）
    # ------------------------------------------------------------------

    def cmd_status(self) -> Dict[str, Any]:
        """
        查询 dreaming 当前状态。

        用法: /dreaming status
        """
        if not self._daemon:
            return {"error": "Daemon not initialized"}

        return self._daemon.get_status()

    def cmd_run(self, **kwargs) -> Dict[str, Any]:
        """
        手动触发一次 dreaming 执行。

        用法: /dreaming run [dry_run=true]
        """
        if not self._daemon:
            return {"error": "Daemon not initialized"}

        # 支持临时覆盖 dry_run
        if kwargs.get("dry_run"):
            original = self._daemon.dry_run
            self._daemon.dry_run = True
            result = self._daemon.execute_dreaming()
            self._daemon.dry_run = original
            result["_override_dry_run"] = True
        else:
            result = self._daemon.execute_dreaming()

        return result

    def cmd_config(self, action: str = "show", **kwargs) -> Dict[str, Any]:
        """
        查看/修改 dreaming 配置。

        用法:
          /dreaming config show       # 显示当前配置
          /dreaming config set key=val  # 修改单个配置项
        """
        if action == "show":
            return {
                "current": self._config.to_dict(),
                "defaults": DEFAULT_CONFIG.to_dict(),
            }
        elif action == "set":
            # 简单的键值设置（不完整实现）
            key = kwargs.get("key")
            value = kwargs.get("value")
            if key and value is not None:
                return {"note": f"Config update for {key}={value} (requires restart)"}
            return {"error": "Usage: config set key=value"}
        else:
            return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_workspace_dir(api) -> Path:
        """解析工作区目录"""
        # 尝试从 runtime 获取
        if api.runtime and hasattr(api.runtime, 'get_provider'):
            pass  # runtime helpers 不直接提供 workspace 路径

        # 尝试环境变量
        import os
        env_paths = [
            os.environ.get("QWENPAW_WORKSPACE"),
            os.environ.get("WORKSPACE_DIR"),
            os.environ.get("COPAW_WORKSPACE"),
        ]
        for p in env_paths:
            if p:
                return Path(p).resolve()

        # 默认使用当前工作目录
        return Path.cwd()


# ============================================================
# 插件入口点 — 必须导出名为 `plugin` 的对象
# ============================================================

plugin = DreamingPlugin()
