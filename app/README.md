# ArticleCheck App

`app/` 是交付包中的实际运行目录。无论是在线 Docker、离线 Docker，还是 Python 虚拟环境方式启动，应用代码和配置都从这里读取。

## 目录结构

```text
app/
├── article_check/               # 主应用代码
├── dify_dsl/                    # Dify 工作流 DSL
├── 北师大论文格式要求/            # 审查规则资产
├── nginx/                       # Nginx 配置
├── Dockerfile                   # 应用镜像构建文件
├── docker-compose.yml           # 本地调试编排
├── docker-compose.platform.yml  # 在线部署编排
├── docker-compose.offline.yml   # 离线部署编排
├── .dockerignore                # Docker 构建上下文控制
├── .env.example                 # 本地运行模板
├── .env.docker                  # 本地 Docker 模板
├── .env.platform.example        # 平台部署模板
├── .env.platform                # 部署时本地生成，不随仓库提交
├── pyproject.toml               # Python 包元数据
├── requirements.txt             # Python 依赖
├── dify_api.example.md          # Dify 配置模板
└── README.md                    # 当前文档
```

## 关键入口

最常用的几个入口文件如下：

- `article_check/web/server.py`
  FastAPI 主入口，上传、审查、报告、定位、问答、认证配置都从这里出去。
- `article_check/dify_review.py`
  Dify 多工作流主链，包括工作流绑定、规则注入、审查串联和容错回退。
- `article_check/runtime.py`
  本地运行时主入口，用于不依赖 Dify 或 Dify 回退时的装配逻辑。
- `article_check/web/frontend/`
  React 前端目录，当前交付版已经同步为最新页面版本。

## 前端目录

```text
article_check/web/frontend/
├── src/       # 前端源码
├── public/    # 静态文件与 auth.js
├── dist/      # 构建后的静态产物
└── package.json
```

<br />

## 后端核心接口

最常用的后端接口：

- `POST /api/upload`
- `POST /api/review`
- `POST /api/review/deep`
- `POST /api/review/batch-stream`
- `POST /api/report/dialogue`
- `POST /api/report/source-snippet`
- `GET /api/report/file`
- `GET /api/status`
- `GET /api/health`
- `GET /api/platform-auth-config`
- `GET /api/auth/session`

## Dify 相关文件

- `dify_dsl/`
  当前交付版内置了 Dify 工作流 DSL 文件。
- `dify_api.example.md`
  用于登记和说明 Dify 相关配置的模板文件。
- `.env.platform.example`
  平台部署模板。实际部署时请先复制生成 `.env.platform`，再填写真实变量。

## 本地构建参考

后端：

```powershell
pip install -r requirements.txt
python -m article_check.web.server
```

前端：

```powershell
cd article_check/web/frontend
npm install
npm run build
```

Docker：

```powershell
docker compose -f docker-compose.platform.yml --env-file .env.platform up -d --build
```

## 平台认证与后端授权

当前交付版已经把平台认证从“仅前端登录”补齐为“前后端联动授权”：

- 前端认证脚本位于 `article_check/web/frontend/public/auth.js`
- 后端认证校验入口位于 `article_check/web/server.py`
- 当前配置下，前端会给 `/api/*` 和 `/prod-api/*` 请求附加认证头
- 后端会在 `ARTICLE_CHECK_PLATFORM_AUTH_ENABLED=true` 且 `ARTICLE_CHECK_PLATFORM_AUTH_ENFORCE_API=true` 时校验业务接口令牌

常用平台认证变量：

- `ARTICLE_CHECK_PLATFORM_AUTH_ENABLED`
- `ARTICLE_CHECK_PLATFORM_AUTH_MODE`
- `ARTICLE_CHECK_PLATFORM_AUTH_API_BASE`
- `ARTICLE_CHECK_PLATFORM_AUTH_HOST`
- `ARTICLE_CHECK_PLATFORM_AUTH_CALLBACK_PATH`
- `ARTICLE_CHECK_PLATFORM_AUTH_STORAGE_PREFIX`
- `PLATFORM_AUTH_PROXY_TARGET`
- `PLATFORM_AUTH_PROXY_HOST_HEADER`

可选高级变量：

- `ARTICLE_CHECK_PLATFORM_AUTH_ENFORCE_API`
- `ARTICLE_CHECK_PLATFORM_AUTH_GATEWAY_BASE_URL`
- `ARTICLE_CHECK_PLATFORM_AUTH_CACHE_TTL_SECONDS`
- `ARTICLE_CHECK_PLATFORM_AUTH_TIMEOUT_SECONDS`

建议联调时先检查：

1. `GET /api/platform-auth-config`
2. `GET /api/auth/session`
3. `POST /api/review`

## 说明

如果你是从交付包根目录进入，请优先查看：

- [../README.md](file:///e:/cocoon/projects/article_check/交付版/README.md)
