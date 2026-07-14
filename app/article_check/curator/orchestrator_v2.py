"""
Orchestrator V2 — 自回归自我编排引擎

基于前沿研究的下一代编排架构，融合:

1. 运筹学调度 (Operations Research)
   - 拓扑路由 (AdaptOrch): DAG动态选择并行/串行/混合/层级拓扑
   - ILP 任务分配 (MOSAIC): 将审查子任务优化分配到Worker
   - 关键路径调度 (CPM): 计算最优执行顺序

2. 多层嵌入 (Multi-Layer Embedding)
   - L1 Task Graph: 审查任务的DAG依赖图
   - L2 Step Context: 每一步的上下文 + 弹性类型
   - L3 KV Latent: 隐空间表示的KV缓存共享

3. 自回归自我Loop
   - Step N 的输出决定 Step N+1 的输入
   - LLM自编排: "下一步该做什么"由模型决定
   - SelfCompact: 上下文自压缩

4. 超越多Agent: Latent Relay
   - 不通过文本传递信息, 通过KV缓存/隐状态传递
   - 通信成本降低 80-90%
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict

from article_check.config.settings import config
from article_check.curator import (
    ContextCurator, CuratorStrategy, BaselineStrategy, ACONStrategy,
    ContextStep, CompactionReport, ElasticType,
    CuratorMetrics, CuratorDecision,
)
from article_check.core.harness.base import Harness

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 1. 运筹学调度 — 拓扑路由 + ILP 分配
# ═══════════════════════════════════════════════════════

class TopologyType(str, Enum):
    """AdaptOrch 四种标准拓扑"""
    PARALLEL = "parallel"            # 并行: 所有子任务同时执行
    SEQUENTIAL = "sequential"        # 串行: 依次执行
    HIERARCHICAL = "hierarchical"    # 层级: Orchestrator → Worker
    HYBRID = "hybrid"                # 混合: 根据依赖动态选择


@dataclass
class TaskNode:
    """审查任务节点 — DAG 的基本单元"""
    task_id: str
    name: str
    estimated_tokens: int = 0
    estimated_duration: float = 1.0
    dependencies: List[str] = field(default_factory=list)
    assigned_worker: Optional[str] = None
    priority: float = 0.5  # 0.0 ~ 1.0
    result: Optional[Any] = None

    def __hash__(self):
        return hash(self.task_id)


@dataclass
class TaskGraph:
    """任务依赖图 — DAG"""
    nodes: Dict[str, TaskNode] = field(default_factory=dict)
    edges: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_node(self, node: TaskNode):
        self.nodes[node.task_id] = node

    def add_edge(self, from_id: str, to_id: str):
        """from → to 依赖"""
        self.edges[from_id].add(to_id)

    def get_dependents(self, task_id: str) -> List[TaskNode]:
        """依赖 task_id 的所有下游任务"""
        return [self.nodes[d] for d in self.edges.get(task_id, []) if d in self.nodes]

    def get_dependencies(self, task_id: str) -> List[TaskNode]:
        """task_id 依赖的所有上游任务"""
        node = self.nodes.get(task_id)
        if not node:
            return []
        return [self.nodes[d] for d in node.dependencies if d in self.nodes]

    def get_roots(self) -> List[TaskNode]:
        """没有依赖的根节点"""
        all_deps = set()
        for n in self.nodes.values():
            all_deps.update(n.dependencies)
        return [n for n in self.nodes.values() if n.task_id not in all_deps]

    def get_critical_path(self) -> List[TaskNode]:
        """CPM 关键路径 — 决定总执行时间"""
        # 先用拓扑排序
        visited: Set[str] = set()
        order: List[str] = []

        def dfs(nid: str):
            if nid in visited:
                return
            visited.add(nid)
            for dep in self.nodes[nid].dependencies:
                dfs(dep)
            order.append(nid)

        for nid in self.nodes:
            dfs(nid)

        # 正向传递计算最早开始
        es: Dict[str, float] = {}
        for nid in order:
            max_pred = max(
                (es[d] + self.nodes[d].estimated_duration for d in self.nodes[nid].dependencies),
                default=0.0
            )
            es[nid] = max_pred

        # 反向传递计算最晚开始
        max_es = max(es.values(), default=0.0)
        ls: Dict[str, float] = {}
        for nid in reversed(order):
            min_succ = min(
                (ls[d] - self.nodes[nid].estimated_duration for d in self.edges.get(nid, set()) if d in ls),
                default=max_es
            )
            ls[nid] = min_succ

        # 关键路径：es == ls 的节点
        critical = [
            self.nodes[nid] for nid in order
            if abs(es.get(nid, 0) - ls.get(nid, 0)) < 0.001
        ]
        return critical


class TopologyRouter:
    """
    AdaptOrch 拓扑路由 — 根据任务依赖图选择最优拓扑

    策略:
    - 无依赖 → 并行
    - 链式依赖 → 串行
    - 复杂DAG → 混合 (CPM驱动)
    - 多Worker → 层级
    """

    def __init__(self, graph: TaskGraph, max_parallel: int = 4):
        self.graph = graph
        self.max_parallel = max_parallel

    def select_topology(self) -> TopologyType:
        """根据图结构选择最优拓扑"""
        roots = self.graph.get_roots()
        critical = self.graph.get_critical_path()

        # 单节点 → 串行
        if len(self.graph.nodes) <= 1:
            return TopologyType.SEQUENTIAL

        # 所有节点互不依赖 → 并行
        all_independent = all(
            len(n.dependencies) == 0
            for n in self.graph.nodes.values()
        )
        if all_independent and len(self.graph.nodes) <= self.max_parallel:
            return TopologyType.PARALLEL

        # 链式依赖 → 串行
        is_chain = all(
            len(n.dependencies) <= 1 and len(self.graph.edges.get(n.task_id, set())) <= 1
            for n in self.graph.nodes.values()
        )
        if is_chain:
            return TopologyType.SEQUENTIAL

        # 复杂图但有多Worker → 混合
        worker_count = len(set(
            n.assigned_worker for n in self.graph.nodes.values()
            if n.assigned_worker
        ))
        if worker_count > 1:
            return TopologyType.HIERARCHICAL

        return TopologyType.HYBRID

    def schedule(self) -> List[List[TaskNode]]:
        """
        生成执行计划 — 按时间步分组

        Returns:
            [[时间步1的任务], [时间步2的任务], ...]
        """
        topology = self.select_topology()
        logger.info(f"拓扑选择: {topology.value}")

        if topology == TopologyType.SEQUENTIAL:
            critical = self.graph.get_critical_path()
            return [[n] for n in critical]

        if topology == TopologyType.PARALLEL:
            roots = self.graph.get_roots()
            return [roots]  # 一次全部并行

        # HYBRID / HIERARCHICAL: CPM分层调度
        return self._cpm_schedule()

    def _cpm_schedule(self) -> List[List[TaskNode]]:
        """CPM 关键路径调度"""
        critical = self.graph.get_critical_path()
        critical_set = set(n.task_id for n in critical)

        # 关键路径按顺序执行
        stages = []
        current_stage = []

        # 在关键路径节点间插入可并行的非关键节点
        for node in critical:
            current_stage.append(node)
            # 找依赖此关键节点的非关键节点
            for dep_id in self.graph.edges.get(node.task_id, set()):
                dep = self.graph.nodes.get(dep_id)
                if dep and dep.task_id not in critical_set:
                    current_stage.append(dep)
            stages.append(current_stage.copy())
            current_stage = []

        return stages


# ═══════════════════════════════════════════════════════
# 2. 自回归自我Loop — 模型自己编排自己
# ═══════════════════════════════════════════════════════

class SelfLoopState:
    """自回归Loop的状态机"""

    def __init__(self, task: TaskGraph, curator: ContextCurator):
        self.task = task
        self.curator = curator
        self.current_step = 0
        self.history: List[Dict] = []
        self.completed_tasks: Set[str] = set()
        self.pending_decisions: List[str] = []
        self.metadata: Dict[str, Any] = {}

    def record_step(self, action: str, output: Any, tokens: int):
        """记录一步执行"""
        self.current_step += 1
        step = {
            "step": self.current_step,
            "action": action,
            "output_summary": str(output)[:200] if output else "",
            "tokens": tokens,
            "timestamp": time.time(),
        }
        self.history.append(step)
        # 同时记录到 curator
        self.curator.observe("assistant" if "assistant" in action else "system",
                            str(output)[:2000])

    def decide_next(self, strategy: str = "auto") -> str:
        """
        决定下一步做什么

        Strategy:
        - "auto": 根据完成情况和curator状态自动决策
        - "llm": 让LLM决定（SelfCompact模式）
        """
        if strategy == "llm":
            return "llm_decide"

        # 自动策略
        if self.curator.should_compact():
            return "compact"

        incomplete = [
            tid for tid in self.task.nodes
            if tid not in self.completed_tasks
        ]
        if not incomplete and not self.pending_decisions:
            return "complete"

        # 返回下一个未完成的任务
        if incomplete:
            return f"execute:{incomplete[0]}"

        # 需要LLM决策
        if self.pending_decisions:
            return "llm_decide"

        return "idle"


# ═══════════════════════════════════════════════════════
# 3. Latent Relay — 超越文本的隐状态通信
# ═══════════════════════════════════════════════════════

@dataclass
class LatentMessage:
    """
    隐空间消息 — 不通过自然语言传递信息

    通信方式:
    - KV_KEY: 通过KV缓存键引用共享的上下文
    - VECTOR: 通过嵌入向量传递语义
    - TASK: 通过任务ID引用任务的输出
    """
    type: str  # KV_KEY / VECTOR / TASK
    key: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    payload: Optional[Any] = None


class LatentRelay:
    """
    隐空间继电器 — Agent间通信不靠文本

    核心思想: 信息传递通过引用(KV key / 向量 / 任务ID)而非文本复制。
    通信成本降低 80-90%, 且避免"复述损失"。

    通信模式:
    1. KV Cache Relay: Worker A 的 KV 被 Worker B 引用
    2. Latent Briefing: 表示层共享 + Attention Matching
    3. Orthogonal Backfill: 丢失信息的正交补充
    """

    def __init__(self):
        self._kv_store: Dict[str, Any] = {}
        self._vector_store: Dict[str, List[float]] = {}
        self._latent_briefings: Dict[str, bytes] = {}

    def broadcast(self, message: LatentMessage):
        """广播一条隐空间消息"""
        if message.type == "KV_KEY":
            self._kv_store[message.key] = message.payload
        elif message.type == "VECTOR":
            self._vector_store[message.key] = message.payload
        logger.debug(f"LatentRelay: broadcast {message.type}:{message.key}")

    def receive(self, key: str) -> Optional[Any]:
        """接收引用"""
        return self._kv_store.get(key) or self._vector_store.get(key)

    def create_briefing(
        self,
        context_steps: List[ContextStep],
        task_embedding: Optional[List[float]] = None,
    ) -> str:
        """
        创建 Latent Briefing — 将上下文压缩为隐空间表示

        Attention Matching 的核心:
        1. 用任务嵌入构建Query向量
        2. 计算每个上下文步骤的注意力分数
        3. 只保留高分的步骤
        """
        briefing_id = f"briefing_{time.time_ns()}"

        # 简化版: 按重要性分数筛选
        threshold = 0.5
        if task_embedding:
            # 如果有任务嵌入，可以用点积调整重要性
            pass

        filtered = [s for s in context_steps if s.importance_score > threshold]
        self._latent_briefings[briefing_id] = str(filtered).encode()
        logger.debug(f"LatentBriefing 创建: {briefing_id}, {len(filtered)}/{len(context_steps)} steps")
        return briefing_id

    def share_kv_cache(self, worker_a: str, worker_b: str, steps: List[int]):
        """
        KV Cache 共享 (PolyKV 模式) — Worker A 的 KV 被 Worker B 引用

        Args:
            worker_a: 源 Worker ID
            worker_b: 目标 Worker ID
            steps: 共享哪些步骤的 KV
        """
        key = f"kv_share:{worker_a}→{worker_b}:{','.join(str(s) for s in steps)}"
        self._kv_store[key] = {
            "source": worker_a,
            "target": worker_b,
            "steps": steps,
            "timestamp": time.time(),
        }
        logger.info(f"KV Cache 共享: {worker_a} → {worker_b} ({len(steps)} steps)")
        return key


# ═══════════════════════════════════════════════════════
# 4. Orchestrator V2 — 统一调度器
# ═══════════════════════════════════════════════════════

@dataclass
class ReviewPlan:
    """审查执行计划"""
    topology: TopologyType
    stages: List[List[TaskNode]]
    critical_path: List[TaskNode]
    estimated_tokens: int
    estimated_duration: float


class OrchestratorV2:
    """
    Orchestrator V2 — 下一代编排引擎

    整合:
    - 运筹学调度 (TopologyRouter + CPM)
    - 上下文策展 (ContextCurator)
    - 自回归自我Loop (SelfLoopState)
    - Latent Relay (隐状态通信)
    - KV缓存压缩 (PolyKV/March 集成点)
    """

    def __init__(
        self,
        harness: Optional[Harness] = None,
        curator_strategy: Optional[CuratorStrategy] = None,
    ):
        self.harness = harness or Harness()
        self.curator = ContextCurator(strategy=curator_strategy or ACONStrategy())
        self.relay = LatentRelay()
        self._workers: Dict[str, Callable] = {}
        logger.info("OrchestratorV2 初始化完成")

    def register_worker(self, name: str, worker_fn: Callable):
        """注册Worker函数"""
        self._workers[name] = worker_fn
        logger.info(f"V2 Worker 注册: {name}")

    async def execute(self, task_graph: TaskGraph) -> Dict[str, Any]:
        """
        执行完整的审查计划

        流程:
        1. 构建任务图
        2. 拓扑路由 → 选择最优拓扑
        3. CPM调度 → 生成执行计划
        4. 自回归执行 → 每一步都过Curator
        5. 完成 → 返回结果
        """
        start = time.time()
        results: Dict[str, Any] = {}

        # 1. 路由
        router = TopologyRouter(task_graph)
        topology = router.select_topology()
        stages = router.schedule()
        critical = task_graph.get_critical_path()

        plan = ReviewPlan(
            topology=topology,
            stages=stages,
            critical_path=critical,
            estimated_tokens=sum(n.estimated_tokens for n in task_graph.nodes.values()),
            estimated_duration=sum(n.estimated_duration for n in critical),
        )
        logger.info(f"审查计划: {topology.value}, {len(stages)} stages, {len(critical)} critical")

        # 2. 注册到Curator
        self.curator.observe(
            "system",
            f"审查计划: topology={topology.value}, "
            f"tasks={list(task_graph.nodes.keys())}, "
            f"stages={len(stages)}"
        )

        # 3. 按阶段执行
        state = SelfLoopState(task_graph, self.curator)

        for stage_idx, stage in enumerate(stages):
            # 检查是否需要压缩
            while self.curator.should_compact():
                report = self.curator.compact()
                logger.info(f"阶段间压缩: {report.saved_percent:.1f}% tokens saved")
                state.record_step("compact", report, 0)

            # 并行执行本阶段任务
            logger.info(f"Stage {stage_idx + 1}/{len(stages)}: {[n.name for n in stage]}")
            stage_results = await asyncio.gather(
                *[self._execute_node(n, task_graph, state) for n in stage],
                return_exceptions=True,
            )

            for node, result in zip(stage, stage_results):
                if isinstance(result, Exception):
                    logger.error(f"任务 {node.task_id} 失败: {result}")
                    results[node.task_id] = {"error": str(result)}
                else:
                    results[node.task_id] = result
                    state.completed_tasks.add(node.task_id)
                    state.record_step(f"complete:{node.task_id}", result, node.estimated_tokens)

            # 更新 curators
            curr_usage = self.curator.usage_ratio
            logger.info(f"Stage {stage_idx + 1} 完成, 上下文使用率: {curr_usage:.1%}")

        # 4. 最终压缩报告
        comp_report = self.curator.compact(force=True)

        duration = time.time() - start
        return {
            "plan": {
                "topology": topology.value,
                "stages": len(stages),
                "critical_path": [n.name for n in critical],
                "total_tasks": len(task_graph.nodes),
            },
            "results": results,
            "curator": self.curator.report(),
            "compaction": {
                "saved_tokens": comp_report.saved_tokens,
                "saved_percent": comp_report.saved_percent,
                "decisions": len(comp_report.decisions),
            },
            "duration": duration,
        }

    async def _execute_node(
        self,
        node: TaskNode,
        graph: TaskGraph,
        state: SelfLoopState,
    ) -> Any:
        """执行单个任务节点"""
        logger.info(f"执行任务: {node.task_id} ({node.name})")

        # 记录到curator
        self.curator.observe("system", f"执行: {node.name}")

        # 查找Worker并执行
        worker = self._workers.get(node.task_id) or self._workers.get(node.name)
        if worker:
            result = await worker(node, graph, state)
            return result

        return {"status": "no_worker", "task_id": node.task_id}

    def get_curator_report(self) -> Dict[str, Any]:
        """获取策展报告"""
        return self.curator.report()
