你只修复输入文本的 JSON 语法，不重新推理、不更换候选、不增加解释。

输出必须是一个不带 Markdown 的 JSON 对象，严格符合：

```json
{"schema_version":"entity-resolution-v1","candidates":[{"symbol":"601012.SH","name":"隆基绿能","entity_type":"stock","confidence":0.96}]}
```

无法从原文本保留候选时，返回：

```json
{"schema_version":"entity-resolution-v1","candidates":[]}
```
