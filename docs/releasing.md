# 发布 Linux Release

流程参考 [STRM-Generator-GO 的发布工作流](https://github.com/kentinya/STRM-Generator-GO/blob/4d16846722f31aa9615494b90df715cf4b5bb6df/.github/workflows/release.yml)：
推送 `v*` 标签，构建两个 Linux 架构的压缩包，生成 SHA256 校验清单并自动创建 GitHub Release。

JellyfinProxy 使用 PyInstaller，两个架构分别在原生 Ubuntu 22.04 runner 上构建，
Python 版本为 3.11；每个架构都运行全部 pytest 回归，以及冻结二进制的版本、启动和 HTTP
响应检查。只有两个构建均成功后才发布，不将交叉编译标作 ARM64 运行验证。

## 产物

- `JellyfinProxy_v<版本>_linux_amd64.tar.gz`
- `JellyfinProxy_v<版本>_linux_arm64.tar.gz`
- `SHA256SUMS.txt`

每个压缩包仅包含 `JellyfinProxy` 和示例配置 `JellyfinProxy.toml`。二进制需要对应
架构的 glibc Linux，构建基线为 Ubuntu 22.04；不用于 Alpine / musl 或其他操作系统。
原生 runner 验证不等于全部 Linux 发行版或真实 Jellyfin 客户端兼容认证。

## 发布步骤

1. 确认当前准备发布的实现、配置、版本与变更记录；未实施草案不记作已交付修复。
2. 若需要新产品版本，先更新唯一版本来源 `version.py` 及 `CHANGELOG.md`。
   发布已有版本时不因发布设施或流程文档的变化自动升级版本号。
3. 运行 `.venv/bin/python -m pytest` 和 `git diff --check`。
4. 按当前机器架构本地验证打包，例如：

   ```bash
   .venv/bin/python scripts/build_release.py --tag v1.0.0 --arch amd64
   ```

5. 提交并推送明确属于发布的文件，然后对该提交创建与 `version.py` 一致的标签：

   ```bash
   git tag v1.0.0 <完整发布提交SHA>
   git push origin refs/tags/v1.0.0
   ```

6. 检查 `Build and Publish Release` 工作流成功，核对 Release 页面上两个压缩包和
   `SHA256SUMS.txt` 均存在。失败时先修正原因；不移动已有发布标签或覆盖已交付版本。

## 下载后运行

下载所需架构压缩包和校验清单，核对相应包的 SHA256 后解压。编辑配置中的上游地址、
监听设置及客户端策略，再运行：

```bash
./JellyfinProxy --version
./JellyfinProxy --config ./JellyfinProxy.toml
```
