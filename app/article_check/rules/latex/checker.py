"""
格式规则引擎 — LaTeX 格式检查器（封装 chktex）

chktex 是一个语义性的 LaTeX 检查器，能检测 40+ 类格式问题。
此模块包装 chktex 为 Python 工具，并增强高级语义检查。

参考: chktex 规则列表 — https://man.archlinux.org/man/extra/texlive-doc/chktex.1.en
"""
from __future__ import annotations
import re
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LaTeXChecker:
    """
    LaTeX 格式检查器

    两层架构：
    1. chktex 本地规则引擎（40+ 规则，零 token）
    2. AI 辅助规则（仅在需要时调用 DeepSeek）

    使用方法:
        checker = LaTeXChecker()
        issues = checker.check("paper.tex")
    """

    # chktex 规则编号与描述映射
    CHKTEX_RULES = {
        1: "命令后缺少空格",
        2: "非断行空格使用不当",
        3: "引号未使用 `` 和 ''",
        4: "脚注在页码后",
        5: "居中环境问题",
        6: "在数学模式外使用数学命令",
        7: "在数学模式内使用文本命令",
        8: "花括号不匹配",
        9: "非法字号更改",
        # ... 共 40+ 条规则
    }

    # AI 辅助规则 — 需要 LLM 判断的复杂格式问题
    AI_RULES = [
        "figure_placement",   # 图表放置是否合适
        "table_format",       # 表格格式是否规范
        "equation_numbering", # 公式编号是否连续
        "citation_style",     # 引用格式是否一致
        "bibliography_style", # 参考文献格式
    ]
    IGNORED_MESSAGE_PATTERNS = [
        re.compile(r"line\s*break", re.IGNORECASE),
        re.compile(r"trailing\s*\\\\", re.IGNORECASE),
        re.compile(r"行尾.*换行", re.IGNORECASE),
        re.compile(r"多余换行", re.IGNORECASE),
    ]

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self._chktex_available = self._check_chktex()

    def check(self, file_path: str) -> List[Dict[str, Any]]:
        """执行完整的 LaTeX 格式检查"""
        issues = []

        # Layer 1: chktex 规则引擎
        if self._chktex_available:
            chktex_issues = self._run_chktex(file_path)
            issues.extend(chktex_issues)
            logger.info(f"chktex 发现 {len(chktex_issues)} 个格式问题")
        else:
            logger.warning("chktex 未安装，使用基础正则检查")
            basic_issues = self._basic_regex_check(file_path)
            issues.extend(basic_issues)

        return issues

    def _run_chktex(self, file_path: str) -> List[Dict[str, Any]]:
        """执行 chktex 命令并解析输出"""
        # 构建命令
        cmd = ["chktex", "-q", "--format", "%k:%n:%b:%c:%d:%e:%m\n"]
        if self.config_path:
            cmd.extend(["-l", self.config_path])
        cmd.append(file_path)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return self._parse_chktex_output(result.stdout)
        except FileNotFoundError:
            logger.warning("chktex 未安装")
            self._chktex_available = False
            return []
        except subprocess.TimeoutExpired:
            logger.error("chktex 执行超时")
            return []
        except Exception as e:
            logger.error(f"chktex 执行失败: {e}")
            return []

    def _parse_chktex_output(self, output: str) -> List[Dict[str, Any]]:
        """解析 chktex 的输出"""
        issues = []
        seen = set()
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(":")
            if len(parts) >= 5:
                issue = {
                    "type": "latex_format",
                    "rule_id": int(parts[0]) if parts[0].isdigit() else 0,
                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                    "column": int(parts[2]) if parts[2].isdigit() else 0,
                    "severity": "minor",
                    "description": parts[3] if len(parts) > 3 else "",
                    "suggestion": self.CHKTEX_RULES.get(int(parts[0]) if parts[0].isdigit() else 0, ""),
                }
                if self._should_ignore_issue(issue):
                    continue
                issue_key = (
                    issue.get("rule_id"),
                    issue.get("line"),
                    issue.get("column"),
                    issue.get("description"),
                )
                if issue_key in seen:
                    continue
                seen.add(issue_key)
                issues.append(issue)
        return issues

    def _basic_regex_check(self, file_path: str) -> List[Dict[str, Any]]:
        """基础正则检查（chktex 不可用时的降级方案）"""
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        issues = []

        checks = [
            (r"\$\$", "不要使用 $$，应使用 \\[ ... \\]", "minor"),
            (r"\\eqnarray", "避免使用 eqnarray，应使用 align", "minor"),
            (r"``[^']*''", "引号格式检查", "info"),
        ]

        seen = set()
        for pattern, msg, severity in checks:
            matches = re.finditer(pattern, text)
            for m in matches:
                issue = {
                    "type": "latex_basic",
                    "line": text[:m.start()].count("\n") + 1,
                    "description": msg,
                    "severity": severity,
                    "suggestion": msg,
                }
                if self._should_ignore_issue(issue):
                    continue
                issue_key = (issue.get("line"), issue.get("description"))
                if issue_key in seen:
                    continue
                seen.add(issue_key)
                issues.append(issue)

        return issues

    def _should_ignore_issue(self, issue: Dict[str, Any]) -> bool:
        text = " ".join(
            str(issue.get(key) or "")
            for key in ("description", "suggestion", "message")
        )
        return any(pattern.search(text) for pattern in self.IGNORED_MESSAGE_PATTERNS)

    def _check_chktex(self) -> bool:
        """检查 chktex 是否可用"""
        try:
            subprocess.run(
                ["chktex", "--version"],
                capture_output=True,
                timeout=5,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
