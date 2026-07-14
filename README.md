# ArticleCheck 交付包

这是用于部署和交接的最小可运行交付目录，只包括部署所需的应用代码、环境模板、Docker 编排文件和一键脚本。

## 目录结构

```text
交付版/
├── app/                    # 主应用目录
├── 镜像包/                 # 离线镜像说明目录（tar 包不随 Git 仓库提交）
├── 一键部署.ps1            # 在线 Docker 部署
├── 一键停止.ps1            # 停止 Docker 服务
├── 一键导入离线镜像.ps1     # 导入离线镜像包
├── 一键离线部署.ps1         # 离线 Docker 部署
├── 一键配置虚拟环境.ps1      # 本地 Python 虚拟环境部署
└── README.md               # 当前文档
```

## 系统说明

ArticleCheck 是一个面向高校论文送审前审查与修改场景的 Web 系统，适合论文作者、导师和审改人员使用。系统当前收束为一条稳定主线：

- 前端：React Web 页面
- 后端：FastAPI
- 审查主链：Dify 多工作流编排 + 本地回退能力
- 主要能力：上传论文、论文审查、参考文献风险识别、证据定位、正式报告导出、报告问答

当前正式支持的论文文件类型：

- `docx`
- `pdf`
- `tex / ltx`

## 推荐部署方式

### 1. 在线 Docker 部署

适合目标机器可以联网并允许在线构建镜像的场景。

执行顺序：

1. 进入 `app/`
2. 从 `app/.env.platform.example` 复制生成 `app/.env.platform`
3. 填写真实环境变量
4. 在交付版根目录运行 `一键部署.ps1`

如果手动执行，可使用：

```powershell
cd app
docker compose -f docker-compose.platform.yml --env-file .env.platform up -d --build
```

### 2. 离线 Docker 部署

适合目标机器无法访问外网，但允许提前导入镜像包的场景。

执行顺序：

1. 先按 `镜像包/README.md` 准备所需 `.tar`
2. 将镜像文件放入 `镜像包/`
3. 在交付版根目录运行 `一键导入离线镜像.ps1`
4. 再运行 `一键离线部署.ps1`

如果手动执行，可使用：

```powershell
cd app
docker compose -f docker-compose.offline.yml --env-file .env.platform up -d
```

### 3. Python 虚拟环境部署

适合暂时无法使用 Docker，只需要在本机快速启动服务的场景。

执行顺序：

1. 在交付版根目录运行 `一键配置虚拟环境.ps1`
2. 进入 `app/`
3. 复制环境模板并补齐变量
4. 启动后端与前端

手动执行参考：

```powershell
cd app
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m article_check.web.server
```

前端本地开发：

```powershell
cd app\article_check\web\frontend
npm install
npm run dev
```

## 运行所需关键文件

部署时最重要的是 `app/` 目录。关键文件如下：

- `app/Dockerfile`
- `app/docker-compose.yml`
- `app/docker-compose.platform.yml`
- `app/docker-compose.offline.yml`
- `app/.env.example`
- `app/.env.docker`
- `app/.env.platform.example`
- `app/nginx/`
- `app/article_check/`
- `app/dify_dsl/`
- `app/北师大论文格式要求/`

说明：

- `app/.env.platform.example` 是平台部署模板
- `app/.env.platform` 需要部署前从模板复制生成，不随 GitHub 仓库提交
- `app/dify_dsl/` 是 Dify 工作流定义
- `app/北师大论文格式要求/` 是审查规则资产

## 部署前需要检查的环境变量

至少确认以下变量已经正确填写到本地 `app/.env.platform`：

- `ARTICLE_CHECK_AI_PROVIDER`
- `DIFY_BASE_URL`
- `DIFY_API_KEY`
- `DIFY_APP_TYPE`
- `DIFY_RESPONSE_MODE`
- `ARTICLE_CHECK_PLATFORM_AUTH_ENABLED`
- `ARTICLE_CHECK_PLATFORM_AUTH_MODE`
- `ARTICLE_CHECK_PLATFORM_AUTH_API_BASE`
- `ARTICLE_CHECK_PLATFORM_AUTH_HOST`
- `ARTICLE_CHECK_PLATFORM_AUTH_CALLBACK_PATH`
- `ARTICLE_CHECK_PLATFORM_AUTH_STORAGE_PREFIX`
- `PLATFORM_AUTH_PROXY_TARGET`
- `PLATFORM_AUTH_PROXY_HOST_HEADER`

如果本次部署不启用平台官方认证，可根据实际场景关闭或调整对应认证变量。

如需显式控制后端授权行为，还可以按需补充以下可选变量：

- `ARTICLE_CHECK_PLATFORM_AUTH_ENFORCE_API`
- `ARTICLE_CHECK_PLATFORM_AUTH_GATEWAY_BASE_URL`
- `ARTICLE_CHECK_PLATFORM_AUTH_CACHE_TTL_SECONDS`
- `ARTICLE_CHECK_PLATFORM_AUTH_TIMEOUT_SECONDS`

## 安全说明

当前 GitHub 交付仓不会包含以下内容：

- 真实的 `app/.env.platform`
- Dify / DeepSeek / 平台认证密钥
- 离线镜像 `.tar` 大文件

这些内容需要在实际部署环境中单独准备。

## 默认访问方式

在线或离线 Docker 启动后，默认访问方式如下：

- 前端入口：`http://localhost:3000`
- 后端健康检查：`http://localhost:3000/api/health`
- 系统状态：`http://localhost:3000/api/status`

如果修改了端口映射，请以 `app/docker-compose*.yml` 和环境变量中的端口为准。

## 核心接口

当前交付版最常用的接口如下：

### 1. 上传论文

- `POST /api/upload`

用途：

- 上传 `docx / pdf / tex` 文件，返回服务端存储路径

### 2. 启动审查

- `POST /api/review`

用途：

- 对单篇论文执行完整审查，返回统一审查结果

常见请求字段：

- `paper_path`
- `template`
- `depth`
- `with_deep_review`
- `review_focus`
- `report_focus`

### 3. 深度审查

- `POST /api/review/deep`

用途：

- 对已上传论文执行更细致的深度审查

### 4. 批量流式审查

- `POST /api/review/batch-stream`

用途：

- 对多篇论文连续审查并返回流式结果

### 5. 报告问答

- `POST /api/report/dialogue`

用途：

- 围绕当前审查报告继续追问重点问题、证据依据和修改建议

### 6. 原文定位片段

- `POST /api/report/source-snippet`

用途：

- 根据 `evidence_id` 返回对应原文片段、锚点信息和定位摘要

### 7. 正式报告文件

- `GET /api/report/file`

用途：

- 读取正式报告 HTML 文件，供浏览器预览、打印和导出 PDF

### 8. 平台认证配置

- `GET /api/platform-auth-config`

用途：

- 返回前端认证脚本所需的平台认证配置

### 9. 当前认证会话

- `GET /api/auth/session`

用途：

- 返回当前请求关联的平台认证状态，便于部署联调时确认后端是否已经识别并校验用户令牌

## 平台认证说明

当前交付版已按项目方官方认证脚本的接入方式完成联动：

- 前端 `public/auth.js` 会在平台登录成功后自动为 `/prod-api/*` 和本系统 `/api/*` 请求附加认证头
- 后端 `article_check/web/server.py` 在启用平台认证时会对业务接口执行令牌校验
- `GET /api/health`、`GET /api/status`、`GET /api/platform-auth-config`、`GET /api/report/file` 默认保留为可直接访问接口，便于健康检查、状态查看和报告预览

若部署时希望后端不拦截业务接口，可将 `ARTICLE_CHECK_PLATFORM_AUTH_ENFORCE_API=false`。

## 启动后建议做的最小检查

部署完成后，建议至少检查以下项目：

1. 打开首页是否正常显示
2. `GET /api/health` 是否返回健康状态
3. `GET /api/status` 是否能看到 Dify 注册状态
4. 登录平台后访问 `GET /api/auth/session`，确认 `validated` 为 `true`
5. 上传一篇论文后，`/api/review` 是否能返回审查结果
6. 报告页中证据定位和报告问答是否正常

## 停止服务

可直接运行：

```powershell
.\一键停止.ps1
```

或手动执行：

```powershell
cd app
docker compose -f docker-compose.platform.yml --env-file .env.platform down
```

## 应用目录补充说明

更详细的应用目录和文件说明，见：

- [app/README.md](file:///e:/cocoon/projects/article_check/交付版/app/README.md)
