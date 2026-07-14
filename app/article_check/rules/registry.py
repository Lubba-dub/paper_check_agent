"""
模板注册表 — 管理所有格式模板的注册与查询

支持:
- 注册新模板
- 按名称/类别搜索模板
- 自动匹配模板（根据论文元信息）
- 用户提供模板 → 直接注册生效
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from article_check.rules.template import (
    FormatTemplate,
    IEEE_TEMPLATE,
    ELSEVIER_TEMPLATE,
    ACM_TEMPLATE,
    LNCS_TEMPLATE,
)

logger = logging.getLogger(__name__)


class TemplateRegistry:
    """
    格式模板注册表

    注册的模板会立即被格式检查引擎使用。
    用户随时添加新模板，无需重启。
    """

    def __init__(self):
        self._templates: Dict[str, FormatTemplate] = {}
        self._categories: Dict[str, List[str]] = {}

        # 注册内置模板
        self._init_builtin_templates()

    def _init_builtin_templates(self):
        """初始化内置模板"""
        builtins = [
            IEEE_TEMPLATE,
            ELSEVIER_TEMPLATE,
            ACM_TEMPLATE,
            LNCS_TEMPLATE,
        ]
        for tpl in builtins:
            self.register(tpl)
        logger.info(f"已加载 {len(builtins)} 个内置模板")

    def register(self, template: FormatTemplate):
        """注册一个格式模板"""
        key = template.name.lower().replace(" ", "_")
        self._templates[key] = template
        cat = template.category
        if cat not in self._categories:
            self._categories[cat] = []
        if key not in self._categories[cat]:
            self._categories[cat].append(key)
        logger.info(f"模板注册: [{template.category}] {template.name}")

    def register_user_template(
        self,
        name: str,
        spec: Dict[str, Any],
    ) -> FormatTemplate:
        """
        用户提供的模板 → 直接注册

        Args:
            name: 模板名称
            spec: 格式规范字典，可以是部分覆盖

        Returns:
            注册后的 FormatTemplate 对象
        """
        from dataclasses import dataclass

        # 从默认模板合并用户配置
        template = FormatTemplate(name=name, **{
            k: v for k, v in spec.items()
            if k in FormatTemplate.__dataclass_fields__
        })
        self.register(template)
        logger.info(f"用户模板 '{name}' 已注册: {spec.get('description', '')}")
        return template

    def get(self, name: str) -> Optional[FormatTemplate]:
        """按名称获取模板"""
        key = name.lower().replace(" ", "_")
        return self._templates.get(key)

    def search(self, query: str) -> List[FormatTemplate]:
        """搜索模板（名称/描述模糊匹配）"""
        query = query.lower()
        results = []
        for tpl in self._templates.values():
            if query in tpl.name.lower() or query in tpl.description.lower():
                results.append(tpl)
        return results

    def list_by_category(self, category: str) -> List[FormatTemplate]:
        """按类别列出模板"""
        return [
            self._templates[k] for k in self._categories.get(category, [])
        ]

    def list_all(self) -> List[FormatTemplate]:
        """列出所有模板"""
        return list(self._templates.values())

    def detect_matching_template(
        self,
        latex_class: Optional[str] = None,
        packages: Optional[List[str]] = None,
        text_sample: Optional[str] = None,
    ) -> Optional[FormatTemplate]:
        """
        根据论文元信息自动匹配模板

        Args:
            latex_class: LaTeX 文档类名（如 IEEEtran）
            packages: 使用的宏包列表
            text_sample: 文本样本（用于关键词匹配）

        Returns:
            匹配的模板，或 None
        """
        # 1. 优先匹配 LaTeX 文档类
        if latex_class:
            for tpl in self._templates.values():
                if tpl.latex_class and latex_class.lower() == tpl.latex_class.lower():
                    return tpl

        # 2. 匹配宏包
        if packages:
            for tpl in self._templates.values():
                if tpl.latex_packages:
                    overlap = set(p.lower() for p in packages) & \
                             set(p.lower() for p in tpl.latex_packages)
                    if len(overlap) >= 2:
                        return tpl

        # 3. 文本关键字匹配
        if text_sample:
            text_lower = text_sample.lower()
            for tpl in self._templates.values():
                keywords = [tpl.name.lower()] + tpl.name.lower().split()
                if any(kw in text_lower for kw in keywords):
                    return tpl

        return None

    @property
    def count(self) -> int:
        return len(self._templates)


# 全局单例
template_registry = TemplateRegistry()
