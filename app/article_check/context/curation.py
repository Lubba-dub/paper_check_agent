"""ContextCurator 适配层。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from article_check.curator import ContextCurator


class CuratedContextBuilder:
    """把现有 ContextCurator 适配为统一上下文接口。"""

    def __init__(self, curator: Optional[ContextCurator] = None):
        self.curator = curator or ContextCurator()

    def observe_system(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.curator.observe("system", content, metadata)

    def observe_user(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.curator.observe("user", content, metadata)

    def observe_tool(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.curator.observe("tool", content, metadata)

    def observe_assistant(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.curator.observe("assistant", content, metadata)

    def build_messages(self) -> List[Dict[str, str]]:
        if self.curator.should_compact():
            self.curator.compact()
        return self.curator.get_messages()

    def report(self) -> Dict[str, Any]:
        return self.curator.report()

