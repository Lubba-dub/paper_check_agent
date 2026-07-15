# Dify API 对接示例

请复制本文件为 `dify_api.md`，再填入你自己的 Dify 工作流地址与 API Key。

## 规则来源

当前论文格式审查默认以工作区内以下北京师范大学规则文档为权威来源：

| 规则类型 | 文件路径 | 用途 |
| --- | --- | --- |
| 本科规范 | `北师大论文格式要求/北京师范大学本科生学术论文规范.pdf` | 本科论文格式、结构、摘要、目录、正文、参考文献等要求 |
| 研究生规范 | `北师大论文格式要求/1. 北京师范大学研究生学位论文编写规则（2026版）.pdf` | 研究生论文封面、题名页、摘要、目录、图表、参考文献等要求 |

## 结构化规则 JSON

| JSON 文件 | 对应输入变量 | 适用场景 |
| --- | --- | --- |
| `北师大论文格式要求/bnu_undergraduate_template_rule_profile.json` | `template_bundle_json` | 北师大本科论文 |
| `北师大论文格式要求/bnu_graduate_requirement_rule_profile.json` | `requirement_bundle_json` | 北师大研究生学位论文 |

## DSL / API 填写表

| 序号 | DSL 文件 | 工作流用途 | Dify 应用名称 | 线上 App ID / Workflow ID | API Key | Base URL | 触发接口路径 | 执行模式 | 主要输入变量 | 主要输出变量 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `dify_dsl/articlecheck_document_read_workflow.yml` | 文档读取与上下文归一化 | ArticleCheck_Document_Read |  |  |  |  | `workflow` | `paper_bundle_json`, `template_bundle_json`, `requirement_bundle_json`, `detailed_mode`, `review_focus`, `institution`, `template_name`, `review_goal`, `strictness_level` | `document_read_standard_result`, `document_read_detailed_result` | 二选一分支输出，FastAPI 侧统一归一化 |
| 2 | `dify_dsl/articlecheck_component_classification_workflow.yml` | 部件识别与边界分类 | ArticleCheck_Component_Classification |  |  |  |  | `workflow` | `paper_profile_json`, `review_context_json`, `evidence_index_json`, `template_rule_profile_json`, `requirement_rule_profile_json`, `font_profile_json`, `file_type`, `review_track` | `component_map_json` | 建议与 `/api/classify/components` 对齐 |
| 3 | `dify_dsl/articlecheck_format_review_workflow.yml` | 格式审查 | ArticleCheck_Format_Review |  |  |  |  | `workflow` | `paper_profile_json`, `template_rule_profile_json`, `requirement_rule_profile_json`, `review_context_json`, `format_policy_json`, `section_digest_json`, `evidence_index_json`, `risk_hints_json`, `detailed_mode`, `review_focus`, `component_map_json`, `font_profile_json` | `format_review_json` | 强格式建议优先由本地规则引擎与解析器提供 |
| 4 | `dify_dsl/articlecheck_reference_verify_workflow.yml` | 参考文献核验归纳 | ArticleCheck_Reference_Verify |  |  |  |  | `workflow` | `paper_profile_json`, `reference_verify_json`, `review_context_json`, `section_digest_json`, `evidence_index_json`, `detailed_mode`, `review_focus` | `reference_review_json` | 先由 FastAPI 做 DOI / 题名 / 作者 / 年份核验，再送 Dify 归纳 |
| 5 | `dify_dsl/articlecheck_hallucination_review_workflow.yml` | 幻觉审查 | ArticleCheck_Hallucination_Review |  |  |  |  | `workflow` | `paper_profile_json`, `review_context_json`, `reference_verify_json`, `hallucination_policy_json`, `section_digest_json`, `evidence_index_json`, `format_review_json`, `reference_review_json`, `detailed_mode`, `review_focus` | `hallucination_review_json` | 依赖格式审查与参考文献核验先验结果 |
| 6 | `dify_dsl/articlecheck_report_generation_workflow.yml` | 报告生成 | ArticleCheck_Report_Generation |  |  |  |  | `workflow` | `paper_profile_json`, `format_review_json`, `hallucination_review_json`, `review_context_json`, `reference_review_json`, `section_digest_json`, `evidence_index_json`, `detailed_mode`, `report_focus` | `report_generation_json` | 建议作为主报告产出入口 |
| 7 | `dify_dsl/articlecheck_report_qa_workflow.yml` | 报告问答 | ArticleCheck_Report_QA |  |  |  |  | `workflow` | `report_payload_json`, `user_question`, `question_scope`, `answer_style` | `answer` | 作为报告问答交互层工作流 |

## FastAPI 侧建议映射

| 阶段 | FastAPI 建议动作 | 对应 Dify 工作流 | 说明 |
| --- | --- | --- | --- |
| 1 | 解析论文 PDF / DOCX / TEX | 无 | 生成 `paper_bundle_json` |
| 2 | 解析北师大本科 / 研究生规范 PDF | 无 | 生成 `template_bundle_json` / `requirement_bundle_json` |
| 3 | 执行归一化 | `articlecheck_document_read_workflow.yml` | 产出统一上下文 |
| 4 | 执行部件识别 | `articlecheck_component_classification_workflow.yml` | 先识别封面、声明页、摘要、目录、正文、参考文献等部件边界 |
| 5 | 执行格式审查 | `articlecheck_format_review_workflow.yml` | 结合本地规则引擎结果做归纳 |
| 6 | 执行文献核验 | `articlecheck_reference_verify_workflow.yml` | 可先完成 DOI / Crossref / OpenAlex 核验 |
| 7 | 执行幻觉审查 | `articlecheck_hallucination_review_workflow.yml` | 融合格式与引文核验结果 |
| 8 | 生成最终报告 | `articlecheck_report_generation_workflow.yml` | 汇总 findings / evidence / actions |
| 9 | 承接用户追问 | `articlecheck_report_qa_workflow.yml` | 单独作为交互层 |
