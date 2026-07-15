# ArticleCheck 交付包

ArticleCheck 是一套面向高校论文送审前检查场景的 Web 系统，当前交付包已经收束为一条可部署、可回归、可移交的稳定主线：

- 前端：React
- 后端：FastAPI
- 审查主链：Dify 多工作流 + 本地回退
- 核心能力：上传论文、格式检查、参考文献核验、问题依据与定位、正式报告导出、报告追问

当前正式支持的文件类型：

- `docx`
- `pdf`
- `tex / ltx`

## 交付目录结构

```text
paper_check_agent/
├── app/                      # 实际部署目录
├── 镜像包/                   # 离线镜像说明与校验清单（tar 不入库）
├── 一键部署.ps1              # 在线 Docker 部署
├── 一键停止.ps1              # 停止服务
├── 一键导入离线镜像.ps1       # 导入离线镜像
├── 一键离线部署.ps1           # 离线 Docker 启动
├── 一键配置虚拟环境.ps1        # 本地 Python 启动
└── README.md                 # 当前文档
```

## 本次交付包含什么

这次交付已经包含：

- component-first 审查链路
- `component_classification` Dify 工作流接入
- FastAPI `classify/components -> review -> source-snippet` 全链路
- LaTeX 多余重复定位修正
- 参考文献 `Bibliography` 识别
- 前端问题定位刷新优化
- 正式报告展示优化
- 平台认证 `legacy_oauth` 默认配置
- 在线 / 离线 Docker 编排
- 前端已构建 `dist`

## 快速开始

### 方式一：在线 Docker 部署

适合目标机器能联网拉镜像、能访问 Dify 和认证网关的场景。

1. 进入 `app/`
2. 复制环境模板：

```powershell
Copy-Item .env.platform.example .env.platform
```

3. 按“环境变量说明”填写真实值
4. 在仓库根目录执行：

```powershell
.\一键部署.ps1
```

如果手动执行：

```powershell
cd app
docker compose -f docker-compose.platform.yml --env-file .env.platform up -d --build
```

### 方式二：离线 Docker 部署

适合目标机器无法访问外网，但可以提前导入镜像的场景。

1. 按 [镜像包/README.md](file:///e:/cocoon/projects/article_check/.publish_tmp/paper_check_agent_latest_20260715/镜像包/README.md) 准备 `.tar`
2. 把镜像文件放入 `镜像包/`
3. 运行：

```powershell
.\一键导入离线镜像.ps1
.\一键离线部署.ps1
```

离线手动执行：

```powershell
cd app
docker compose -f docker-compose.offline.yml --env-file .env.platform up -d
```

### 方式三：Python 虚拟环境部署

适合只想快速本地起服务，不走 Docker 的场景。

```powershell
.\一键配置虚拟环境.ps1
```

或者手动执行：

```powershell
cd app
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m article_check.web.server
```

前端开发模式：

```powershell
cd app\article_check\web\frontend
npm install
npm run dev
```

## 环境变量说明

### 原则

- 仓库中只保留模板，不保留真实密钥
- 真实 `API Key` 与部署环境变量请放到仓库外部单独保管
- 建议参考外部模板：
  [交付版外部环境模板](file:///e:/cocoon/projects/article_check/交付版/外部环境文件/paper_check_agent_env.secrets.template)

### 最少需要填写的变量

部署 `app/.env.platform` 时，至少应确认这些值：

- `ARTICLE_CHECK_AI_PROVIDER`
- `DIFY_BASE_URL`
- `DIFY_API_KEY`
- `ARTICLE_CHECK_DIFY_DOCUMENT_READ_API_KEY`
- `ARTICLE_CHECK_DIFY_COMPONENT_CLASSIFICATION_API_KEY`
- `ARTICLE_CHECK_DIFY_FORMAT_REVIEW_API_KEY`
- `ARTICLE_CHECK_DIFY_REFERENCE_VERIFY_API_KEY`
- `ARTICLE_CHECK_DIFY_HALLUCINATION_REVIEW_API_KEY`
- `ARTICLE_CHECK_DIFY_REPORT_GENERATION_API_KEY`
- `ARTICLE_CHECK_DIFY_REPORT_QA_API_KEY`
- `DEEPSEEK_API_KEY`（如启用深审兜底）
- `ARTICLE_CHECK_PLATFORM_AUTH_ENABLED`
- `ARTICLE_CHECK_PLATFORM_AUTH_MODE`
- `ARTICLE_CHECK_PLATFORM_AUTH_HOST`
- `PLATFORM_AUTH_PROXY_TARGET`
- `PLATFORM_AUTH_PROXY_HOST_HEADER`

### Dify 工作流对应关系

当前交付版使用以下工作流：

- 文档读取：`dbvfR3MQYfPPlHkJ`
- 部件识别：`SNjqCn9fZbIzG81x`
- 格式审查：`qqiz0GZOcbetK35r`
- 参考文献核验：`xOFCPi2VzmpI6fv1`
- 幻觉审查：`nVRkoJaJkj4MeQQT`
- 报告生成：`Skfvt4amRApAvTTX`
- 报告问答：`Jmem7t2HPs6j4xA3`

## 功能使用说明

### 1. 上传论文

入口：前端“开始检查”页面。

支持上传：

- `docx`
- `pdf`
- `tex / ltx`

上传后可以：

- 删除已选文件
- 直接开始单篇检查
- 连续检查多篇
- 选择是否开启更细致的内容与表达检查

### 2. 启动审查

系统默认通过 `/api/review` 发起统一审查。

审查链路为：

1. 解析证据包
2. 本地确定性审计
3. 分层核验
4. Dify 文档读取
5. Dify 部件识别
6. Dify 格式/文献/幻觉审查
7. Dify 报告生成

当 Dify 某个环节异常时，系统会保留本地回退结果，不会让主接口直接中断。

### 3. 查看问题依据与定位

结果页支持：

- 按严重程度查看问题
- 点击“定位原文”
- 查看对应片段
- 查看 evidence card 高亮状态
- 对当前问题继续追问

LaTeX、DOCX、PDF 都会尽量返回结构化定位信息；结构缺失类问题通常会定位到章节级，行级问题会定位到具体焦点行。

### 4. 正式报告预览与导出

系统会生成正式报告 HTML，可用于：

- 页面预览
- 打印
- 导出 PDF

当前正式报告已经做过这些优化：

- 文件名代替任务 ID
- 严重级别按 `critical -> major -> minor -> info`
- 不再显示空定位提示
- 审查耗时会截断格式化

### 5. 报告问答

围绕当前报告，可以继续向系统追问：

- 哪些问题最影响送审
- 应该先改哪几项
- 某条证据为什么被判定为问题
- 参考文献最先该补什么

## 核心接口

最常用接口如下：

- `POST /api/upload`
- `POST /api/review`
- `POST /api/review/deep`
- `POST /api/review/batch-stream`
- `POST /api/classify/components`
- `POST /api/parse/evidence-bundle`
- `POST /api/audit/deterministic`
- `POST /api/verify/layered`
- `POST /api/report/source-snippet`
- `POST /api/report/dialogue`
- `GET /api/report/file`
- `GET /api/platform-auth-config`
- `GET /api/auth/session`
- `GET /api/status`

## 平台认证说明

当前交付版默认按项目方认证方式运行：

- 模式：`legacy_oauth`
- 网关：`http://124.71.226.114:8444`
- 前端认证脚本：`app/article_check/web/frontend/public/auth.js`
- 后端认证入口：`app/article_check/web/server.py`

Nginx 会转发：

- `/api/*` -> FastAPI
- `/prod-api/*` -> 平台认证网关

对应模板文件：

- [app/nginx/default.conf.template](file:///e:/cocoon/projects/article_check/.publish_tmp/paper_check_agent_latest_20260715/app/nginx/default.conf.template)

## 镜像包与 Nginx 检查结论

### 镜像包

当前仓库中的 `镜像包/` 目录状态正常：

- 已保留说明文档
- 已保留哈希清单
- 没有把大体积 `.tar` 镜像误提交进 Git

### Nginx

当前 `app/nginx/default.conf.template` 已覆盖这些能力：

- `/api/` 反代 FastAPI
- `/prod-api/` 反代平台认证网关
- SPA 路由回落到 `index.html`
- 静态资源缓存
- 基础安全响应头

## 发布前检查

建议发布前至少执行这些检查：

```powershell
python -m py_compile app/article_check/dify_review.py app/article_check/runtime.py app/article_check/web/server.py
docker compose -f app/docker-compose.platform.yml --env-file app/.env.platform config
```

如果要重新构建前端：

```powershell
cd app/article_check/web/frontend
npm install
npm run build
```

## 安全说明

当前 Git 仓库不会提交：

- 真实 `app/.env.platform`
- 真实 Dify / DeepSeek 密钥
- 离线镜像 `.tar`
- 本地缓存、`node_modules`、`__pycache__`

## 维护建议

1. 真实密钥只保存在仓库外部
2. 交付部署优先使用 `app/`
3. 在线部署优先 `docker-compose.platform.yml`
4. 离线部署优先 `docker-compose.offline.yml`
5. 接口排查优先查看 `app/article_check/web/server.py`

## 许可证

MIT
