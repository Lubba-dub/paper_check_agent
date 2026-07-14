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

## 说明

如果你是从交付包根目录进入，请优先查看：

- [../README.md](file:///e:/cocoon/projects/article_check/交付版/README.md)
