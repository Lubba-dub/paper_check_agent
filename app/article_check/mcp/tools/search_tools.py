"""
Web 搜索工具 — 在审查过程中搜索领域最新信息

用于验证文献时效性、检查前沿进展、查找缺失引用。
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def web_search(
    query: str,
    num_results: int = 5,
) -> List[Dict[str, str]]:
    """
    Web 搜索 — 获取领域最新信息

    用于验证文献时效性、查找领域前沿进展。

    Args:
        query: 搜索关键词
        num_results: 返回结果数

    Returns:
        搜索结果列表
    """
    logger.info(f"web_search: '{query}' (n={num_results})")
    # TODO: 使用 search API (serper / bing / google)
    return [
        {
            "title": "搜索结果示例 — 需要配置搜索 API",
            "url": "https://example.com",
            "snippet": "请配置搜索 API 以启用此功能",
        }
    ]


def search_arxiv(
    query: str,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    在 arXiv 搜索相关论文

    arXiv API 是免费的，无需认证。

    Args:
        query: 搜索关键词
        max_results: 最大结果数

    Returns:
        论文列表
    """
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET

    logger.info(f"search_arxiv: '{query}' (max={max_results})")

    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })

    url = f"http://export.arxiv.org/api/query?{params}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8")

        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        papers = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            link = entry.find("atom:id", ns)

            authors = []
            for author in entry.findall("atom:author", ns):
                name = author.find("atom:name", ns)
                if name is not None:
                    authors.append(name.text)

            papers.append({
                "title": title.text.strip().replace("\n", " ") if title is not None else "",
                "summary": summary.text.strip().replace("\n", " ")[:300] if summary is not None else "",
                "url": link.text.strip() if link is not None else "",
                "authors": ", ".join(authors[:5]),
            })

        logger.info(f"arXiv 搜索返回 {len(papers)} 篇论文")
        return papers

    except Exception as e:
        logger.error(f"arXiv 搜索失败: {e}")
        return []
