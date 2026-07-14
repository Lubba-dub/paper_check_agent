"""
Agent 注册表 — 管理所有可用的 Agent 类型和实例工厂
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Type

from article_check.core.agent.base import Agent, AgentConfig

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Agent 注册表 — 工厂模式创建 Agent 实例。

    支持:
    - 按角色注册 Agent 类
    - 根据审查任务动态组配合适 Agent
    """

    def __init__(self):
        self._registry: Dict[str, Type[Agent]] = {}
        self._default_configs: Dict[str, AgentConfig] = {}

    def register(
        self,
        role: str,
        agent_class: Type[Agent],
        default_config: Optional[AgentConfig] = None,
    ):
        """注册一个 Agent 类型"""
        self._registry[role] = agent_class
        if default_config:
            self._default_configs[role] = default_config
        logger.info(f"注册 Agent: {role} -> {agent_class.__name__}")

    def create(
        self,
        role: str,
        config_override: Optional[AgentConfig] = None,
        **kwargs,
    ) -> Agent:
        """创建指定角色的 Agent 实例"""
        if role not in self._registry:
            raise KeyError(f"未注册的 Agent 角色: {role}。可用: {list(self._registry.keys())}")

        config = self._default_configs.get(role)
        if config_override:
            # 合并配置
            import copy
            config = copy.deepcopy(config)
            for k, v in config_override.__dict__.items():
                if v is not None:
                    setattr(config, k, v)

        agent_class = self._registry[role]
        return agent_class(config=config, **kwargs)

    def list_roles(self) -> List[str]:
        return list(self._registry.keys())

    def get_config(self, role: str) -> Optional[AgentConfig]:
        return self._default_configs.get(role)


# 全局注册表
registry = AgentRegistry()
