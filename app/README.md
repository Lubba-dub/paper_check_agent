# ArticleCheck 应用目录说明

`app/` 是交付仓中真正用于部署的主目录。无论你走在线 Docker、离线 Docker，还是 Python 虚拟环境，最终都以这里的文件为准。

## 目录结构

```text
app/
├── article_check/                  # 后端代码、前端源码、规则与编排主目录
├── dify_dsl/                       # Dify 工作流 DSL
├── nginx/                          # Nginx 模板
├── 北师大论文格式要求/             # 规则资产
├── Dockerfile                      # 应用镜像构建文件
├── docker-compose.yml              # 本地调试编排
├── docker-compose.platform.yml     # 在线平台部署
├── docker-compose.offline.yml      # 离线部署
├── .env.example                    # 本地环境模板
├── .env.docker                     # Docker 调试模板
├── .env.platform.example           # 平台部署模板
├── requirements.txt                # Python 依赖
└── README.md                       # 当前文档
```

## 先看哪几个文件

如果你是第一次接手，建议按这个顺序看：

1. `docker-compose.platform.yml`
2. `.env.platform.example`
3. `article_check/web/server.py`
4. `article_check/dify_review.py`
5. `nginx/default.conf.template`

## 当前主链说明

系统当前已经收束为 component-first 审查链路：

1. 解析证据包
2. 本地确定性审计
3. 分层核验
4. Dify 文档读取
5. Dify 部件识别
6. Dify 格式 / 文献 / 幻觉审查
7. Dify 报告生成

即使 Dify 某一环节暂时不可用，后端也会保留本地回退，不会让主接口直接失效。

## 部署方式

### 在线 Docker

```powershell
Copy-Item .env.platform.example .env.platform
docker compose -f docker-compose.platform.yml --env-file .env.platform up -d --build
```

### 离线 Docker

先把镜像 `.tar` 放到仓库根目录的 `镜像包/`，再执行：

```powershell
docker compose -f docker-compose.offline.yml --env-file .env.platform up -d
```

### Python 虚拟环境

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m article_check.web.server
```

## 环境变量原则

- 仓库模板不带真实密钥
- 真实值请单独保管在仓库外部
- 部署时再复制到 `.env.platform`

建议至少填写这些值：

- `DIFY_API_KEY`
- `ARTICLE_CHECK_DIFY_DOCUMENT_READ_API_KEY`
- `ARTICLE_CHECK_DIFY_COMPONENT_CLASSIFICATION_API_KEY`
- `ARTICLE_CHECK_DIFY_FORMAT_REVIEW_API_KEY`
- `ARTICLE_CHECK_DIFY_REFERENCE_VERIFY_API_KEY`
- `ARTICLE_CHECK_DIFY_HALLUCINATION_REVIEW_API_KEY`
- `ARTICLE_CHECK_DIFY_REPORT_GENERATION_API_KEY`
- `ARTICLE_CHECK_DIFY_REPORT_QA_API_KEY`
- `DEEPSEEK_API_KEY`
- `ARTICLE_CHECK_PLATFORM_AUTH_HOST`

## 功能入口

最常用功能如下：

- 上传论文
- 启动审查
- 深度审查
- 查看问题依据与定位
- 预览正式报告
- 基于当前报告继续追问

对应接口：

- `POST /api/upload`
- `POST /api/review`
- `POST /api/review/deep`
- `POST /api/classify/components`
- `POST /api/report/source-snippet`
- `POST /api/report/dialogue`
- `GET /api/report/file`

## 认证与 Nginx

当前默认认证模式：

- `legacy_oauth`
- 认证网关：`http://124.71.226.114:8444`

Nginx 模板负责：

- `/api/*` -> FastAPI
- `/prod-api/*` -> 平台认证网关
- SPA 路由回退
- 静态资源缓存

模板文件：

- `nginx/default.conf.template`

## 发布前自检

建议至少运行：

```powershell
python -m py_compile article_check/dify_review.py article_check/runtime.py article_check/web/server.py
docker compose -f docker-compose.platform.yml --env-file .env.platform config
```

如果前端有更新：

```powershell
cd article_check/web/frontend
npm install
npm run build
```

## 注意事项

不要提交以下内容：

- 真实 `.env.platform`
- Dify / DeepSeek 真实密钥
- 离线镜像 `.tar`
- `node_modules`
- `__pycache__`

## 许可证

MIT
