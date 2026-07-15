# 离线镜像包说明

本目录只保留离线镜像说明与校验清单，真正的 `.tar` 镜像包不随 GitHub 仓库提交。

## 默认需要的离线镜像

- `article-check_platform.tar`
- `nginx_alpine.tar`

如果本次部署还需要 PDF 增强解析，请额外准备：

- `grobid_grobid_0.9.0-crf.tar`

## 建议目录状态

正常交付时，本目录至少应包含：

- `README.md`
- `SHA256SUMS.json`
- 实际离线镜像 `.tar` 文件（通过线下介质单独提供）

## 校验方式

将镜像包放回当前目录后，可按 `SHA256SUMS.json` 中的 `file` 和 `sha256` 逐项校验。

PowerShell 示例：

```powershell
Get-FileHash ".\article-check_platform.tar" -Algorithm SHA256
Get-FileHash ".\nginx_alpine.tar" -Algorithm SHA256
```

## 导入与启动

导入镜像：

```powershell
.\一键导入离线镜像.ps1
```

启动离线部署：

```powershell
.\一键离线部署.ps1
```

## 注意事项

- `一键导入离线镜像.ps1` 会自动遍历本目录下所有 `.tar`
- 当前仓库默认不强制依赖 `grobid/grobid`
- 如果离线环境中使用了私有镜像标签，请同步修改 `app/docker-compose.offline.yml`
