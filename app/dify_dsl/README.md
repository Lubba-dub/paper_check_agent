# ArticleCheck Dify DSL

本目录只保留项目主线所需的 Dify 工作流资产，不再附带大批社区调研样例或外部仓库镜像。

## 当前保留文件

- `articlecheck_document_read_workflow.yml`
- `articlecheck_component_classification_workflow.yml`
- `articlecheck_format_review_workflow.yml`
- `articlecheck_reference_verify_workflow.yml`
- `articlecheck_hallucination_review_workflow.yml`
- `articlecheck_report_generation_workflow.yml`
- `articlecheck_report_qa_workflow.yml`
- `文本情感分析工作流.yml`

说明：

- `文本情感分析工作流.yml` 是当前实例导出的母版样例，用于约束节点结构和导入兼容性。
- 其余 `articlecheck_*` 文件是本项目正在使用或维护的论文审查工作流。

## 推荐导入顺序

1. `文本情感分析工作流.yml`
2. `articlecheck_document_read_workflow.yml`
3. `articlecheck_component_classification_workflow.yml`
4. `articlecheck_format_review_workflow.yml`
5. `articlecheck_reference_verify_workflow.yml`
6. `articlecheck_hallucination_review_workflow.yml`
7. `articlecheck_report_generation_workflow.yml`
8. `articlecheck_report_qa_workflow.yml`

## 配置要求

导入后请按你的 Dify 实例完成以下绑定：

- 切换为实例内可用模型
- 校对输入输出变量名
- 绑定知识库、HTTP 节点或工具节点
- 将真实工作流 `API Key / Base URL / Workflow ID` 写入仓库根目录下的本地 `dify_api.md`

模板文件请使用：

- `../dify_api.example.md`

## 与系统主链的对应关系

- `document_read`：抽取章节、结构、证据索引和轨道上下文
- `component_classification`：先识别封面、声明页、摘要、关键词、目录、正文、参考文献等部件边界，并给出置信度
- `format_review`：基于部件边界归纳格式问题，并融合本地规则引擎证据
- `reference_verify`：归纳参考文献核验结果
- `hallucination_review`：分析引文、事实和结构风险
- `report_generation`：生成结构化报告与正式报告素材
- `report_qa`：围绕报告做问答

## 推荐的新主线

对于北师大本科/研究生论文，建议将原来的“先规则检查、后语义补充”改成：

1. `document_read`
2. `component_classification`
3. 本地确定性格式 / 文献快核验
4. `format_review`
5. `reference_verify`
6. `hallucination_review`
7. `report_generation`

这样可以把封面、声明页、摘要、参考文献等边界识别前置，减少规则引擎直接误扫全文导致的误报。
