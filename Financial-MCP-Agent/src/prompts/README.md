# src/prompts — 提示词集中管理目录

## 目录说明

本目录统一存放所有对话链路中用到的提示词（Prompt）文本，
方便版本追踪、A/B 对比测试和后续评测。

## 文件清单

| 文件 | 说明 | 使用模块 |
|------|------|---------|
| `query_rewrite.py` | 查询改写阶段的4条提示词 | `src/agents/query_rewriter.py` |
| `skill_routing.py` | 技能路由提示词 | `src/agents/skill_router_node.py` |
| `routing.py` | Stage1 路由提示词（动态构建函数） | `src/agents/route_stage1.py` |
| `memory.py` | 短期记忆压缩提示词（STM） | `src/agents/stm_nodes.py` |
| `ltm_memory.py` | 长期记忆提取/更新提示词（LTM） | `src/memory/mem0_prompts.py` |

## 版本规范

每个文件顶部必须包含：
```python
"""
模块名 提示词 · 版本 vX.Y
最后修改：YYYY-MM-DD
修改记录：...
"""
PROMPT_VERSION = "vX.Y"
```

## 修改规范

1. 修改提示词后必须同步更新 `PROMPT_VERSION`（小版本 +0.1，大改 +1.0）
2. 旧版本注释保留在文件内（方便 diff 和回滚对比）
3. 修改后运行对应 pytest 测试确认无回归
