"""
QwenPaw Plugin Templates — 4 种内置模板定义

每种模板包含完整的 plugin.json + plugin.py 骨架代码，
使用 string.Template 变量填充机制。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================
# 数据模型
# ============================================================

@dataclass
class TemplateFile:
    """模板中的单个文件"""
    relative_path: str          # 相对于插件根目录的路径
    content_template: str       # string.Template 格式的文件内容


@dataclass
class PluginTemplate:
    """插件模板定义"""
    id: str                     # 模板 ID（如 cron-job）
    name: str                   # 显示名称
    description: str            # 模板描述
    category: str               # 分类
    variables: List[str]        # 必填变量列表
    optional_variables: List[str] = field(default_factory=list)
    files: List[TemplateFile] = field(default_factory=list)

    def get_variable_defaults(self) -> Dict[str, str]:
        """返回变量的默认值提示"""
        defaults = {
            "PLUGIN_ID": "",
            "PLUGIN_NAME": "",
            "DESCRIPTION": "",
            "VERSION": "0.1.0",
            "AUTHOR": "Plugin Author",
            "LICENSE": "MIT",
            "CLASS_NAME": "",  # 从 PLUGIN_ID 推导
        }
        return {v: defaults.get(v, "") for v in self.variables}


# ============================================================
# 模板 #1: Cron Job — 定时任务插件
# ============================================================

TEMPLATE_CRON_JOB = PluginTemplate(
    id="cron-job",
    name="⏰ Cron 定时任务插件",
    description="通过 startup_hook 注册定时任务，支持 Cron 表达式配置。适用于需要定期执行的任务，如数据同步、报告生成、缓存清理等。",
    category="scheduling",
    variables=["PLUGIN_ID", "PLUGIN_NAME", "DESCRIPTION", "CRON_EXPRESSION", "TIMEZONE"],
    optional_variables=["VERSION", "AUTHOR", "TASK_NAME"],
    files=[
        TemplateFile(
            relative_path="plugin.json",
            content_template="""\
{
  "id": "${PLUGIN_ID}",
  "name": "${PLUGIN_NAME}",
  "version": "${VERSION:-0.1.0}",
  "description": "${DESCRIPTION}",
  "author": "${AUTHOR:-Plugin Author}",
  "license": "MIT",
  "entry_point": "plugin.py",
  "capabilities": ["cron_scheduling", "startup_hook", "control_command"],
  "config_schema": {
    "type": "object",
    "properties": {
      "schedule_enabled": {
        "type": "boolean",
        "default": true,
        "description": "是否启用定时调度"
      },
      "schedule_cron": {
        "type": "string",
        "default": "${CRON_EXPRESSION}",
        "description": "Cron 表达式"
      },
      "schedule_timezone": {
        "type": "string",
        "default": "${TIMEZONE}",
        "description": "时区"
      },
      "dry_run": {
        "type": "boolean",
        "default": false,
        "description": "模拟运行模式"
      }
    }
  },
  "permissions": ["hook:register", "command:register", "cron:register"],
  "dependencies": [],
  "hybrid_mode": true
}
""",
        ),
        TemplateFile(
            relative_path="plugin.py",
            content_template='''\
"""${PLUGIN_NAME} - QwenPaw Cron Job Plugin.

定时任务插件：在 QwenPaw 启动时注册周期性执行的后台任务。
支持 dry-run 模式和手动触发。

符合 QwenPaw v1.1.0 Plugin API v1 规范。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ${CLASS_NAME}Plugin:
    """
    ${PLUGIN_NAME}

    通过 Startup Hook 初始化定时任务逻辑，
    并提供控制命令用于手动触发和状态查询。
    """

    def __init__(self):
        self._api: Optional[Any] = None
        self._config: Dict[str, Any] = {}
        self._last_run: Optional[str] = None
        self._run_count: int = 0
        self._dry_run: bool = False
        self._task_name: str = "${TASK_NAME:-${PLUGIN_ID}_task}"

    def register(self, api) -> None:
        """Plugin 入口点。由 PluginLoader 加载时调用。"""
        self._api = api
        logger.info("🔧 Registering %s...", self.__class__.__name__)

        # 读取配置
        plugin_config = getattr(api, "config", {}) or {}
        self._config.update(plugin_config)
        self._dry_run = plugin_config.get("dry_run", False)

        if plugin_config.get("task_name"):
            self._task_name = plugin_config["task_name"]

        # 注册启动钩子
        api.register_startup_hook(
            hook_name=f"{self._task_name}_init",
            callback=self._on_startup,
            priority=50,
        )

        # 注册关闭钩子
        api.register_shutdown_hook(
            hook_name=f"{self._task_name}_cleanup",
            callback=self._on_shutdown,
            priority=100,
        )

        logger.info("✅ %s registered (task=%s, dry_run=%s)",
                    self.__class__.__name__, self._task_name, self._dry_run)

    async def _on_startup(self):
        """启动钩子 — 记录初始化信息"""
        try:
            logger.info("[%s] 🚀 Initialized at %s",
                        self._task_name, datetime.now().isoformat())
            if self._api and hasattr(self._api, "runtime") and self._api.runtime:
                self._api.runtime.log_info(f"🔧 {self._task_name} ready")
        except Exception as e:
            logger.error("[%s] Startup failed: %s", self._task_name, e)

    async def _on_shutdown(self):
        """关闭钩子 — 清理资源"""
        logger.info("[%s] 🔌 Shutdown (total runs: %d)", self._task_name, self._run_count)

    # ------------------------------------------------------------------
    # 核心任务逻辑 — 子类或用户自定义此方法
    # ------------------------------------------------------------------

    async def execute_task(self) -> Dict[str, Any]:
        """
        执行定时任务的核心逻辑。

        Returns:
            包含执行结果的字典。
        """
        if self._dry_run:
            return {
                "status": "dry_run",
                "task": self._task_name,
                "message": f"[{self._task_name}] Dry-run mode — no side effects",
                "timestamp": datetime.now().isoformat(),
            }

        # ===== 在这里编写你的任务逻辑 =====
        result = {
            "status": "success",
            "task": self._task_name,
            "message": f"[{self._task_name}] Task executed successfully",
            "timestamp": datetime.now().isoformat(),
        }

        self._run_count += 1
        self._last_run = result["timestamp"]
        return result

    # ------------------------------------------------------------------
    # 控制命令
    # ------------------------------------------------------------------

    def cmd_status(self) -> Dict[str, Any]:
        """查询当前状态。用法: /${PLUGIN_ID} status"""
        return {
            "plugin_id": "${PLUGIN_ID}",
            "task_name": self._task_name,
            "last_run": self._last_run,
            "run_count": self._run_count,
            "dry_run": self._dry_run,
            "config": dict(self._config),
        }

    def cmd_run(self, **kwargs) -> Dict[str, Any]:
        """手动触发执行。用法: /${PLUGIN_ID} run [dry_run=true]"""
        import asyncio as aio

        was_dry = self._dry_run
        if kwargs.get("dry_run"):
            self._dry_run = True

        try:
            loop = aio.get_event_loop()
            if loop.is_running():
                # 如果已有事件循环在运行，创建 task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(asyncio.run, self.execute_task()).result()
            else:
                result = loop.run_until_complete(self.execute_task())
        except RuntimeError:
            result = asyncio.run(self.execute_task())

        self._dry_run = was_dry
        return result

    def cmd_config(self) -> Dict[str, Any]:
        """查看当前配置。用法: /${PLUGIN_ID} config"""
        return {"current": self._config}


# 插件入口点
plugin = ${CLASS_NAME}Plugin()
''',
        ),
    ],
)


# ============================================================
# 模板 #2: Channel Bridge — 消息渠道桥接插件
# ============================================================

TEMPLATE_CHANNEL_BRIDGE = PluginTemplate(
    id="channel-bridge",
    name="📡 消息渠道桥接插件",
    description="桥接外部消息渠道到 QwenPaw 核心处理管道。适用于对接自定义 IM 平台、Webhook 接入、第三方通知系统等。",
    category="channel",
    variables=["PLUGIN_ID", "PLUGIN_NAME", "DESCRIPTION", "CHANNEL_TYPE", "WEBHOOK_PATH"],
    optional_variables=["VERSION", "AUTHOR"],
    files=[
        TemplateFile(
            relative_path="plugin.json",
            content_template="""\
{
  "id": "${PLUGIN_ID}",
  "name": "${PLUGIN_NAME}",
  "version": "${VERSION:-0.1.0}",
  "description": "${DESCRIPTION}",
  "author": "${AUTHOR:-Plugin Author}",
  "license": "MIT",
  "entry_point": "plugin.py",
  "capabilities": ["message_routing", "startup_hook", "control_command"],
  "config_schema": {
    "type": "object",
    "properties": {
      "channel_type": {
        "type": "string",
        "default": "${CHANNEL_TYPE}",
        "description": "渠道类型标识"
      },
      "webhook_path": {
        "type": "string",
        "default": "${WEBHOOK_PATH}",
        "description": "Webhook 接收路径"
      },
      "enabled": {
        "type": "boolean",
        "default": true,
        "description": "是否启用"
      },
      "allowed_senders": {
        "type": "array",
        "items": { "type": "string" },
        "default": [],
        "description": "允许的发送者白名单"
      }
    }
  },
  "permissions": ["hook:register", "command:register"],
  "dependencies": [],
  "hybrid_mode": true
}
""",
        ),
        TemplateFile(
            relative_path="plugin.py",
            content_template='''\
"""${PLUGIN_NAME} - QwenPaw Channel Bridge Plugin.

消息渠道桥接插件：将外部消息源接入 QwenPaw 处理管道。
支持 Webhook 消息接收和格式转换。

符合 QwenPaw v1.1.0 Plugin API v1 规范。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BridgeMessage:
    """桥接消息数据类"""
    sender_id: str
    sender_name: str = ""
    content: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    channel: str = "${CHANNEL_TYPE}"


class ${CLASS_NAME}Bridge:
    """
    ${PLUGIN_NAME}

    负责接收外部渠道消息、格式转换并转发给 QwenPaw Agent Core。
    """

    def __init__(self):
        self._api: Optional[Any] = None
        self._config: Dict[str, Any] = {}
        self._enabled: bool = True
        self._message_count: int = 0
        self._allowed_senders: List[str] = []

    def register(self, api) -> None:
        """Plugin 入口点。"""
        self._api = api
        logger.info("📡 Registering Channel Bridge: %s", self.__class__.__name__)

        plugin_config = getattr(api, "config", {}) or {}
        self._config.update(plugin_config)
        self._enabled = plugin_config.get("enabled", True)
        self._allowed_senders = plugin_config.get("allowed_senders", [])

        # 注册启动钩子
        api.register_startup_hook(
            hook_name="${PLUGIN_ID}_bridge_init",
            callback=self._on_startup,
            priority=40,
        )

        api.register_shutdown_hook(
            hook_name="${PLUGIN_ID}_bridge_stop",
            callback=self._on_shutdown,
            priority=100,
        )

        logger.info("✅ %s ready (channel=%s, enabled=%s)",
                    self.__class__.__name__, "${CHANNEL_TYPE}", self._enabled)

    async def _on_startup(self):
        """启动 — 初始化连接/监听"""
        try:
            # TODO: 在这里初始化你的渠道连接
            # 例如：启动 HTTP server 监听 webhook、建立 WebSocket 连接等
            logger.info("[${PLUGIN_ID}] 🚀 Bridge started at %s", datetime.now().isoformat())
            if self._has_runtime():
                self._api.runtime.log_info(f"📡 ${PLUGIN_ID} bridge active")
        except Exception as e:
            logger.error("[${PLUGIN_ID}] Startup error: %s", e)

    async def _on_shutdown(self):
        """关闭 — 清理连接"""
        logger.info("[${PLUGIN_ID}] 🔌 Bridge stopped (messages bridged: %d)", self._message_count)

    # ------------------------------------------------------------------
    # 消息处理流水线
    # ------------------------------------------------------------------

    def receive_raw_message(self, raw_data: bytes | str | Dict) -> Optional[BridgeMessage]:
        """
        接收原始消息并转换为标准格式。

        这是外部调用的入口点（如 HTTP handler、WebSocket callback）。

        Args:
            raw_data: 原始消息数据（bytes/str/dict 取决于渠道）

        Returns:
            BridgeMessage 或 None（如果被过滤）
        """
        if not self._enabled:
            logger.warning("[${PLUGIN_ID}] Bridge disabled, message dropped")
            return None

        # 1. 解析原始 payload
        try:
            payload = self._parse_payload(raw_data)
        except Exception as e:
            logger.error("[${PLUGIN_ID}] Parse error: %s", e)
            return None

        # 2. 构建标准消息
        msg = self._build_message(payload)
        if not msg:
            return None

        # 3. 发送者过滤
        if self._allowed_senders and msg.sender_id not in self._allowed_senders:
            logger.debug("[${PLUGIN_ID}] Blocked sender: %s", msg.sender_id)
            return None

        self._message_count += 1
        logger.info("[${PLUGIN_ID}] Message #%d from %s: %.80s...",
                    self._message_count, msg.sender_id, msg.content)

        return msg

    def forward_to_agent(self, message: BridgeMessage) -> bool:
        """
        将桥接消息转发给 Agent Core 处理。

        Args:
            message: 已解析的标准消息

        Returns:
            是否转发成功
        """
        # TODO: 实现与 Agent Core 的交互
        # 通常通过 api.runtime 或内部事件总线发送
        logger.info("[${PLUGIN_ID}] Forwarding to agent: [%s] %s",
                    message.sender_id, message.content[:100])
        return True

    # ------------------------------------------------------------------
    # 子类可覆盖的解析方法
    # ------------------------------------------------------------------

    def _parse_payload(self, raw_data: bytes | str | Dict) -> Dict[str, Any]:
        """解析原始 payload 为字典。根据实际渠道格式覆盖此方法。"""
        if isinstance(raw_data, dict):
            return raw_data
        elif isinstance(raw_data, (bytes, str)):
            text = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data
            return json.loads(text)
        else:
            raise ValueError(f"Unsupported raw_data type: {type(raw_data)}")

    def _build_message(self, payload: Dict[str, Any]) -> Optional[BridgeMessage]:
        """从解析后的 payload 构建 BridgeMessage。按需覆盖。"""
        # 默认实现：假设 payload 有这些字段
        return BridgeMessage(
            sender_id=payload.get("sender_id", "unknown"),
            sender_name=payload.get("sender_name", ""),
            content=payload.get("text", payload.get("content", "")),
            raw_payload=payload,
            channel="${CHANNEL_TYPE}",
        )

    def _has_runtime(self) -> bool:
        return bool(self._api and hasattr(self._api, "runtime") and self._api.runtime)

    # ------------------------------------------------------------------
    # 控制命令
    # ------------------------------------------------------------------

    def cmd_status(self) -> Dict[str, Any]:
        """查看桥接状态。用法: /${PLUGIN_ID} status"""
        return {
            "plugin_id": "${PLUGIN_ID}",
            "channel": "${CHANNEL_TYPE}",
            "enabled": self._enabled,
            "message_count": self._message_count,
            "allowed_senders": self._allowed_senders,
            "config": dict(self._config),
        }

    def cmd_toggle(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """切换启用状态。用法: /${PLUGIN_ID} toggle [true|false]"""
        if enabled is not None:
            self._enabled = enabled
        else:
            self._enabled = not self._enabled
        return {"enabled": self._enabled, "message": f"Bridge {'enabled' if self._enabled else 'disabled'}"}


# 插件入口点
plugin = ${CLASS_NAME}Bridge()
''',
        ),
    ],
)


# ============================================================
# 模板 #3: Provider Extender — LLM Provider 扩展插件
# ============================================================

TEMPLATE_PROVIDER_EXTENDER = PluginTemplate(
    id="provider-extender",
    name="🤖 LLM Provider 扩展插件",
    description="注册新的 LLM Provider 到 QwenPaw，扩展模型来源。适用于接入自托管模型、私有网关、API 代理等。",
    category="provider",
    variables=["PLUGIN_ID", "PLUGIN_NAME", "DESCRIPTION", "PROVIDER_ID", "BASE_URL", "MODEL_NAMES"],
    optional_variables=["VERSION", "AUTHOR", "API_KEY_ENV"],
    files=[
        TemplateFile(
            relative_path="plugin.json",
            content_template="""\
{
  "id": "${PLUGIN_ID}",
  "name": "${PLUGIN_NAME}",
  "version": "${VERSION:-0.1.0}",
  "description": "${DESCRIPTION}",
  "author": "${AUTHOR:-Plugin Author}",
  "license": "MIT",
  "entry_point": "plugin.py",
  "capabilities": ["provider_extension", "startup_hook", "control_command"],
  "config_schema": {
    "type": "object",
    "properties": {
      "provider_id": {
        "type": "string",
        "default": "${PROVIDER_ID}",
        "description": "Provider 唯一标识"
      },
      "base_url": {
        "type": "string",
        "default": "${BASE_URL}",
        "description": "API 基础 URL"
      },
      "models": {
        "type": "array",
        "items": { "type": "string" },
        "default": ${MODEL_NAMES},
        "description": "支持的模型列表"
      },
      "api_key_env": {
        "type": "string",
        "default": "${API_KEY_ENV:-}",
        "description": "API Key 环境变量名"
      }
    }
  },
  "permissions": ["provider:register", "hook:register", "command:register"],
  "dependencies": [],
  "hybrid_mode": true
}
""",
        ),
        TemplateFile(
            relative_path="plugin.py",
            content_template='''\
"""${PLUGIN_NAME} - QwenPaw Provider Extension Plugin.

LLM Provider 扩展插件：向 QwenPaw 注册自定义 LLM Provider，
使其能使用自托管模型、私有网关或其他兼容 OpenAI API 的服务。

符合 QwenPaw v1.1.0 Plugin API v1 规范。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ${CLASS_NAME}Provider:
    """
    ${PLUGIN_NAME}

    自定义 LLM Provider 定义。
    通过 api.register_provider() 注册到 QwenPaw 的 Provider 系统。
    """

    # ---- 配置（从 plugin.json config_schema 读取）----
    PROVIDER_ID: str = "${PROVIDER_ID}"
    BASE_URL: str = "${BASE_URL}"
    MODELS: List[str] = ${MODEL_NAMES}
    API_KEY_ENV: str = "${API_KEY_ENV:-}"
    LABEL: str = "${PLUGIN_NAME}"

    def __init__(self):
        self._api: Optional[Any] = None
        self._registered: bool = False
        self._config: Dict[str, Any] = {}

    def register(self, api) -> None:
        """Plugin 入口点。注册自定义 Provider 到 QwenPaw。"""
        self._api = api
        logger.info("🤖 Registering Provider: %s (%s)", self.LABEL, self.PROVIDER_ID)

        # 读取配置
        plugin_config = getattr(api, "config", {}) or {}
        self._config.update(plugin_config)

        # 从配置覆盖默认值
        provider_id = plugin_config.get("provider_id", self.PROVIDER_ID)
        base_url = plugin_config.get("base_url", self.BASE_URL)
        models = plugin_config.get("models", self.MODELS)
        label = self.LABEL

        # 注册 Provider
        try:
            api.register_provider(
                provider_id=provider_id,
                provider_class=self,           # 传入自身作为 Provider 类引用
                label=label,
                base_url=base_url,
                models=models,
            )
            self._registered = True
            logger.info("✅ Provider '%s' registered with %d model(s): %s",
                        provider_id, len(models), ", ".join(models))
        except Exception as e:
            logger.error("❌ Failed to register provider: %s", e)
            self._registered = False

        # 注册控制命令
        api.register_startup_hook(
            hook_name="${PLUGIN_ID}_provider_init",
            callback=self._on_startup,
            priority=30,
        )

    async def _on_startup(self):
        """启动钩子 — 验证 Provider 连接"""
        if not self._registered:
            logger.warning("[${PROVIDER_ID}] Provider not registered, skipping health check")
            return

        try:
            # TODO: 实现健康检查（如调用 /models 端点）
            if self._has_runtime():
                self._api.runtime.log_info(
                    f"🤖 Provider '${PROVIDER_ID}' ready ({len(self.MODELS)} models)"
                )
        except Exception as e:
            logger.error("[${PROVIDER_ID}] Health check failed: %s", e)

    # ------------------------------------------------------------------
    # Provider 接口方法（由 QwenPaw 运行时调用）
    # ------------------------------------------------------------------
    # 注意：以下方法的签名需要匹配 QwenPaw 的 Provider 协议。
    # 具体协议请参考 qwenpaw/providers/ 目录下的现有实现。
    # 这里提供的是通用骨架。

    def list_models(self) -> List[Dict[str, str]]:
        """返回可用模型列表。"""
        return [
            {"id": m, "name": m, "owned_by": self.PROVIDER_ID}
            for m in self.MODELS
        ]

    def get_api_key(self) -> Optional[str]:
        """从环境变量获取 API Key。"""
        import os
        env_name = self._config.get("api_key_env", self.API_KEY_ENV)
        if env_name:
            return os.environ.get(env_name)
        return None

    # ------------------------------------------------------------------
    # 控制命令
    # ------------------------------------------------------------------

    def cmd_status(self) -> Dict[str, Any]:
        """查看 Provider 状态。用法: /${PLUGIN_ID} status"""
        has_key = bool(self.get_api_key())
        return {
            "provider_id": self.PROVIDER_ID,
            "label": self.LABEL,
            "base_url": self.BASE_URL,
            "registered": self._registered,
            "models": self.MODELS,
            "model_count": len(self.MODELS),
            "api_key_set": has_key,
            "config": dict(self._config),
        }

    def cmd_list_models(self) -> Dict[str, Any]:
        """列出所有可用模型。用法: /${PLUGIN_ID} models"""
        return {"models": self.list_models()}

    def _has_runtime(self) -> bool:
        return bool(self._api and hasattr(self._api, "runtime") and self._api.runtime)


# 插件入口点
plugin = ${CLASS_NAME}Provider()
''',
        ),
    ],
)


# ============================================================
# 模板 #4: Tool Extension — 工具扩展插件
# ============================================================

TEMPLATE_TOOL_EXTENSION = PluginTemplate(
    id="tool-extension",
    name="🔧 工具扩展插件",
    description="为 QwenPaw Agent 注册自定义工具和命令。适用于添加专用功能，如数据库操作、外部 API 调用、文件格式转换等。",
    category="tool",
    variables=["PLUGIN_ID", "PLUGIN_NAME", "DESCRIPTION"],
    optional_variables=["VERSION", "AUTHOR", "TOOL_COUNT"],
    files=[
        TemplateFile(
            relative_path="plugin.json",
            content_template="""\
{
  "id": "${PLUGIN_ID}",
  "name": "${PLUGIN_NAME}",
  "version": "${VERSION:-0.1.0}",
  "description": "${DESCRIPTION}",
  "author": "${AUTHOR:-Plugin Author}",
  "license": "MIT",
  "entry_point": "plugin.py",
  "capabilities": ["tool_extension", "control_command", "startup_hook"],
  "config_schema": {
    "type": "object",
    "properties": {
      "tools_enabled": {
        "type": "boolean",
        "default": true,
        "description": "是否启用工具注册"
      },
      "dry_run": {
        "type": "boolean",
        "default": false,
        "description": "模拟运行模式"
      }
    }
  },
  "permissions": ["command:register", "hook:register"],
  "dependencies": [],
  "hybrid_mode": true
}
""",
        ),
        TemplateFile(
            relative_path="plugin.py",
            content_template='''\
"""${PLUGIN_NAME} - QwenPaw Tool Extension Plugin.

工具扩展插件：为 QwenPaw Agent 注册自定义工具和交互式命令。
Agent 可通过自然语言描述意图来调用这些工具。

符合 QwenPaw v1.1.0 Plugin API v1 规范。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str                       # 工具名称（唯一标识）
    display_name: str               # 显示名称
    description: str                # 功能描述（用于 Agent 理解何时调用）
    parameters: Dict[str, Any]      # 参数 schema（JSON Schema 格式）
    handler: Callable               # 执行函数
    requires_approval: bool = False # 是否需要用户确认才能执行
    dangerous: bool = False         # 是否标记为危险操作


class ${CLASS_NAME}Toolkit:
    """
    ${PLUGIN_NAME}

    工具集管理器：注册、管理和执行自定义工具。
    """

    def __init__(self):
        self._api: Optional[Any] = None
        self._tools: Dict[str, ToolDefinition] = {}
        self._config: Dict[str, Any] = {}
        self._execution_log: List[Dict[str, Any]] = []
        self._dry_run: bool = False

    def register(self, api) -> None:
        """Plugin 入口点。注册工具集和生命周期钩子。"""
        self._api = api
        logger.info("🔧 Initializing Tool Toolkit: %s", self.__class__.__name__)

        plugin_config = getattr(api, "config", {}) or {}
        self._config.update(plugin_config)
        self._dry_run = plugin_config.get("dry_run", False)

        # 注册内置工具
        self._register_builtin_tools()

        # 注册生命周期钩子
        api.register_startup_hook(
            hook_name="${PLUGIN_ID}_tools_init",
            callback=self._on_startup,
            priority=50,
        )

        api.register_shutdown_hook(
            hook_name="${PLUGIN_ID}_tools_cleanup",
            callback=self._on_shutdown,
            priority=100,
        )

        logger.info("✅ %s loaded with %d tool(s)",
                    self.__class__.__name__, len(self._tools))

    # ==================================================================
    # 工具注册
    # ==================================================================

    def _register_builtin_tools(self):
        """注册内置工具。在此处添加你的自定义工具。"""

        # ----- 示例工具 1：echo -----
        @self.tool(name="echo", display_name="Echo 回显",
                   description="将输入文本原样回显。用于测试工具链是否正常工作。",
                   parameters={"type": "object", "properties": {
                       "text": {"type": "string", "description": "要回显的文本"}
                   }, "required": ["text"]})
        def echo_tool(text: str) -> Dict[str, Any]:
            return {"result": text, "tool": "echo"}

        # ===== 在下方添加你自己的工具 =====
        #
        # @self.tool(name="my_tool", display_name="我的工具",
        #            description="工具描述...",
        #            parameters={"type": "object", "properties": {...}})
        # def my_tool_handler(param1: str, param2: int = 10) -> Dict[str, Any]:
        #     # 你的逻辑
        #     return {"result": ...}
        #

    def tool(self, name: str, display_name: str, description: str,
             parameters: Dict[str, Any],
             requires_approval: bool = False,
             dangerous: bool = False):
        """
        工具注册装饰器。

        用法:
            @self.tool(name="hello", display_name="Hello World",
                      description="打招呼",
                      parameters={"type":"object","properties":{
                          "name":{"type":"string"}
                      },"required":["name"]})
            def hello(name: str) -> dict:
                return {"greeting": f"Hello, {name}!"}
        """
        def decorator(func: Callable) -> Callable:
            definition = ToolDefinition(
                name=name,
                display_name=display_name,
                description=description,
                parameters=parameters,
                handler=func,
                requires_approval=requires_approval,
                dangerous=dangerous,
            )
            self._tools[name] = definition
            logger.debug("  Registered tool: %s (%s)", name, display_name)
            return func
        return decorator

    # ==================================================================
    # 工具执行
    # ==================================================================

    def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        执行指定工具。

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            执行结果字典
        """
        tool_def = self._tools.get(tool_name)
        if not tool_def:
            return {"error": f"Tool '{tool_name}' not found",
                    "available": list(self._tools.keys())}

        if self._dry_run:
            return {
                "dry_run": True,
                "tool": tool_name,
                "would_execute": True,
                "parameters": kwargs,
                "message": f"Dry-run: would call {tool_def.display_name}",
            }

        try:
            result = tool_def.handler(**kwargs)
            entry = {
                "tool": tool_name,
                "params": kwargs,
                "success": True,
                "timestamp": datetime.now().isoformat(),
            }
            self._execution_log.append(entry)
            return result
        except Exception as e:
            entry = {
                "tool": tool_name,
                "params": kwargs,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
            self._execution_log.append(entry)
            logger.error("[${PLUGIN_ID}] Tool '%s' error: %s", tool_name, e)
            return {"error": str(e), "tool": tool_name}

    # ==================================================================
    # 生命周期
    # ==================================================================

    async def _on_startup(self):
        """启动"""
        logger.info("[${PLUGIN_ID}] 🔧 Toolkit ready: %s", list(self._tools.keys()))
        if self._has_runtime():
            self._api.runtime.log_info(
                f"🔧 ${PLUGIN_ID}: {len(self._tools)} tools available"
            )

    async def _on_shutdown(self):
        """关闭"""
        total = len(self._execution_log)
        logger.info("[${PLUGIN_ID}] 🔌 Toolkit shutdown (executions: %d)", total)

    # ==================================================================
    # 控制命令
    # ==================================================================

    def cmd_list_tools(self) -> Dict[str, Any]:
        """列出所有已注册工具。用法: /${PLUGIN_ID} list"""
        tools_info = []
        for name, t in self._tools.items():
            tools_info.append({
                "name": name,
                "display_name": t.display_name,
                "description": t.description[:80],
                "dangerous": t.dangerous,
                "needs_approval": t.requires_approval,
            })
        return {"tools": tools_info, "count": len(tools_info)}

    def cmd_status(self) -> Dict[str, Any]:
        """查看工具集状态。用法: /${PLUGIN_ID} status"""
        return {
            "plugin_id": "${PLUGIN_ID}",
            "tool_count": len(self._tools),
            "tool_names": list(self._tools.keys()),
            "total_executions": len(self._execution_log),
            "dry_run": self._dry_run,
        }

    def cmd_history(self, limit: int = 20) -> Dict[str, Any]:
        """查看执行历史。用法: /${PLUGIN_ID} history [limit=N]"""
        return {"history": self._execution_log[-limit:]}

    def _has_runtime(self) -> bool:
        return bool(self._api and hasattr(self._api, "runtime") and self._api.runtime)


# 插件入口点
plugin = ${CLASS_NAME}Toolkit()
''',
        ),
    ],
)


# ============================================================
# 模板注册表
# ============================================================

TEMPLATE_REGISTRY: Dict[str, PluginTemplate] = {
    TEMPLATE_CRON_JOB.id: TEMPLATE_CRON_JOB,
    TEMPLATE_CHANNEL_BRIDGE.id: TEMPLATE_CHANNEL_BRIDGE,
    TEMPLATE_PROVIDER_EXTENDER.id: TEMPLATE_PROVIDER_EXTENDER,
    TEMPLATE_TOOL_EXTENSION.id: TEMPLATE_TOOL_EXTENSION,
}


def get_template(template_id: str) -> Optional[PluginTemplate]:
    """根据 ID 获取模板。"""
    return TEMPLATE_REGISTRY.get(template_id)


def list_templates() -> List[Dict[str, str]]:
    """列出所有可用模板的信息摘要。"""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "variables": t.variables,
            "optional_variables": t.optional_variables,
            "file_count": len(t.files),
        }
        for t in TEMPLATE_REGISTRY.values()
    ]
