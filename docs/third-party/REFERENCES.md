# 参考代码与复用记录

## Ocean Watch

- 来源：https://github.com/westng/ocean-watch
- 固定 commit：9b05b3b51c1dba8a8f95937976e95162b5e748e3
- 版本：1.0.9+codex.20260924172936
- 许可证：MIT，原文见 ocean-watch-LICENSE
- 下载目录：references/ocean-watch/（完整浅克隆，忽略进主仓库）
- 锁定/重建：ecom_video/platforms/ocean_watch.lock.json、scripts/install_ocean_watch.py
- 复用方式：直接调用固定版预编译 CLI，运行前逐次验证二进制 SHA。参考其 qc-reports materials 的命令参数、响应字段和日期语义实现 Python 边界适配。
- 证据代码：runtime/ocean-watch-go/internal/cli/qianchuan_reports.go；internal/application/reports/qianchuan.go；internal/adapters/oceanengine/qianchuan_reports.go。
- 没有修改上游仓库，没有将热更新器或创建广告的写命令接入业务接口；未安装到全局 Codex 插件目录。

另三项参考 TiktokVideo、ClipForge、vidcraft 未在 P2 下载或集成。当前工作保留既有 FastAPI/静态前端/FFmpeg 实现；不声称已使用它们。
