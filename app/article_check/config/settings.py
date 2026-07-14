"""
全局配置管理 — 支持环境变量覆盖、.env 文件、JSON/YAML 配置
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# 自动加载 .env 文件（如果存在）
_env_path = Path(os.getcwd()) / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_path))
    except ImportError:
        # 回退：手动解析简单的 KEY=VALUE 文件
        try:
            with open(_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass


@dataclass
class DeepSeekConfig:
    """DeepSeek API 配置"""
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = "https://api.deepseek.com/v1"
    chat_model: str = "deepseek-chat"
    reasoner_model: str = "deepseek-reasoner"
    max_tokens: int = 8192
    temperature: float = 0.1
    top_p: float = 0.9
    timeout: int = 120


@dataclass
class DifyConfig:
    """Dify API 配置"""
    api_key: str = field(default_factory=lambda: os.getenv("DIFY_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("DIFY_BASE_URL", "http://localhost/v1"))
    app_type: str = field(default_factory=lambda: os.getenv("DIFY_APP_TYPE", "chat"))
    response_mode: str = field(default_factory=lambda: os.getenv("DIFY_RESPONSE_MODE", "blocking"))
    user: str = field(default_factory=lambda: os.getenv("DIFY_USER", "article-check-webdemo"))
    timeout: int = field(default_factory=lambda: int(os.getenv("DIFY_TIMEOUT", "180")))
    workflow_query_key: str = field(default_factory=lambda: os.getenv("DIFY_WORKFLOW_QUERY_KEY", "query"))
    inputs_json: str = field(default_factory=lambda: os.getenv("DIFY_INPUTS_JSON", "{}"))


@dataclass
class AIConfig:
    """AI Provider 配置"""
    provider: str = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_AI_PROVIDER", "dify").lower())


@dataclass
class CacheConfig:
    """缓存策略配置（Token 优化核心）"""
    enabled: bool = True
    # 系统提示词固定在前缀，利用 provider 缓存
    cache_prefix_system: bool = True
    # 语义缓存（embedding-based）
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.92
    # 缓存 TTL
    system_cache_ttl: int = 3600
    semantic_cache_ttl: int = 1800


@dataclass
class PipelineConfig:
    """流水线配置"""
    max_concurrent: int = 4  # 并行 worker 数
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout_per_worker: int = 300
    # 工作树隔离
    worktree_enabled: bool = True
    worktree_base_dir: str = ".worktrees"
    # 自适应审查
    adaptive_depth: bool = True
    triage_first: bool = True  # 先快速扫描再决定深度


@dataclass
class FormatConfig:
    """格式检查规则配置"""
    # LaTeX
    latex_rules_enabled: bool = True
    chktex_config: str = ".chktexrc"
    # Word
    docx_rules_enabled: bool = True
    docx_template: Optional[str] = None
    # 自定义规则
    custom_rules_dir: str = "rules"


@dataclass
class ParserConfig:
    """解析层配置"""
    grobid_enabled: bool = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_GROBID_ENABLED", "false").lower() == "true")
    grobid_base_url: str = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_GROBID_BASE_URL", "http://localhost:8070"))
    grobid_timeout: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_GROBID_TIMEOUT", "180")))
    grobid_consolidate_header: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_GROBID_CONSOLIDATE_HEADER", "1")))
    grobid_consolidate_citations: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_GROBID_CONSOLIDATE_CITATIONS", "1")))
    grobid_include_raw_citations: bool = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_GROBID_INCLUDE_RAW_CITATIONS", "true").lower() == "true")
    grobid_tei_coordinates: str = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_GROBID_TEI_COORDINATES", "persName,ref,biblStruct,figure,table,s,p,head"))


@dataclass
class ReferenceConfig:
    """文献审查配置"""
    semantic_scholar_api: str = "https://api.semanticscholar.org/graph/v1"
    crossref_api: str = "https://api.crossref.org"
    openalex_api: str = "https://api.openalex.org"
    verify_doi: bool = True
    check_citation_accuracy: bool = True
    max_refs_per_paper: int = 100
    identity_cache_path: str = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_IDENTITY_CACHE_PATH", ".article_check/reference_fast_cache.json"))
    offline_index_dir: str = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_OFFLINE_INDEX_DIR", ".article_check/offline_indices"))
    fast_verify_workers: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_FAST_VERIFY_WORKERS", "6")))
    online_lookup_rows: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_ONLINE_LOOKUP_ROWS", "3")))
    enable_offline_index: bool = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_ENABLE_OFFLINE_INDEX", "true").lower() == "true")
    enable_online_lookup: bool = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_ENABLE_ONLINE_LOOKUP", "true").lower() == "true")


@dataclass
class ClaimVerifyConfig:
    """论断核验配置"""
    max_support_critical_claims: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_MAX_SUPPORT_CRITICAL_CLAIMS", "6")))
    enable_nli: bool = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_ENABLE_NLI", "true").lower() == "true")
    enable_dify_handoff: bool = field(default_factory=lambda: os.getenv("ARTICLE_CHECK_ENABLE_DIFY_HANDOFF", "true").lower() == "true")
    abstract_snippet_chars: int = field(default_factory=lambda: int(os.getenv("ARTICLE_CHECK_ABSTRACT_SNIPPET_CHARS", "2400")))


@dataclass
class ReportConfig:
    """报告输出配置"""
    output_format: str = "markdown"  # markdown / html / pdf
    output_dir: str = "reports"
    include_suggestions: bool = True
    include_score: bool = True
    template_dir: str = "report/templates"


@dataclass
class AppConfig:
    """主配置"""
    project_root: str = field(
        default_factory=lambda: os.getcwd()
    )
    ai: AIConfig = field(default_factory=AIConfig)
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    dify: DifyConfig = field(default_factory=DifyConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    format: FormatConfig = field(default_factory=FormatConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    reference: ReferenceConfig = field(default_factory=ReferenceConfig)
    claim_verify: ClaimVerifyConfig = field(default_factory=ClaimVerifyConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

    def __post_init__(self):
        self.project_root = os.getenv(
            "ARTICLE_CHECK_ROOT",
            str(Path(self.project_root).resolve())
        )

    @classmethod
    def from_json(cls, path: str) -> "AppConfig":
        with open(path, "r") as f:
            data = json.load(f)
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


# 全局单例
config = AppConfig()
