# Phase A/B 重构前基线记录

> 自动生成说明：备份分支已创建；推送成功后请在本文件补全「手工冒烟」勾选。

## Git 快照

| 项 | 值 |
|----|-----|
| 备份分支 | `backup/pre-refactor-2026-05-28` |
| 基线标签 | `v0-before-phase-ab` |
| 提交 SHA | `fcfa3bb`（以 `git rev-parse HEAD` 在备份分支上为准） |
| 远程仓库 | https://github.com/even9277/Finance-agent-Skills |
| 重构工作分支（本地） | `refactor/phase-ab-chat-report-split` |

## 备份范围说明

- **已纳入**：backend、frontend、Financial-MCP-Agent、`tests/`、migrations、`docs/`（含 Phase-A-B 计划）等 304 个文件变更。
- **未纳入（刻意排除）**：
  - `backend/.env`、`Financial-MCP-Agent/.env`（已在 `.gitignore`，含密钥）
  - `Reference/cc-haha`、`Reference/hermes-agent`、`Reference/openclaw`（嵌套独立 Git 仓库，推送只会变成空指针；需各自仓库单独备份）

## 推送命令（若需在本机重推）

HTTPS 若失败，可用 SSH：

```bash
cd /root/Finance
git push git@github.com:even9277/Finance-agent-Skills.git backup/pre-refactor-2026-05-28
git push git@github.com:even9277/Finance-agent-Skills.git v0-before-phase-ab
```

## 自动化验收（重构前跑一遍，结果贴到下方）

```bash
cd /root/Finance
python -m pytest tests/ -q --tb=short
python -m compileall backend/services -q
```

**结果**：（待填写：通过 / 失败数 / 跳过原因）

## 手工冒烟（§6.2，重构前勾选）

- [ ] 1. 登录
- [ ] 2. 对话首句
- [ ] 3. 对话续句
- [ ] 4. 流式 WS
- [ ] 5. SOP 技能（若开启）
- [ ] 6. skill_confirm
- [ ] 7. 报告全流程
- [ ] 8. 记忆侧栏

## 回滚方式

```bash
git checkout backup/pre-refactor-2026-05-28
# 或
git checkout v0-before-phase-ab
```
