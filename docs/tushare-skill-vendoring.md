# 官方 Tushare Skills vendor 说明

本仓库将 `waditu-tushare/skills` 作为主能力源，但不依赖 OpenClaw runtime。

当前接入方式：

- 官方 skill 内容以 vendor 方式放在 `vendor/tushare-skills/`
- 对话运行时仍使用本仓库的 `chat_service -> router -> executor -> Python/Tushare` 链路
- 部署时只需要：
  - 安装 Python 依赖
  - 配置 `TUSHARE_TOKEN`
  - 启动后端

不需要执行：

- `clawhub install`
- `npx skills add`
- 导入 zip skill 包

当前 vendor 内容：

- `vendor/tushare-skills/UPSTREAM.md`
- `vendor/tushare-skills/tushare/SKILL.md`
- `vendor/tushare-skills/tushare/references/README.md`

后续同步上游时，按以下原则进行：

1. 先核对上游 `waditu-tushare/skills` 是否有结构变更
2. 更新本仓库 vendor 元数据与 references 索引
3. 保持运行时执行层 API 与 feature flag 兼容
4. 不把 OpenClaw 专属运行时逻辑直接引入本仓库
