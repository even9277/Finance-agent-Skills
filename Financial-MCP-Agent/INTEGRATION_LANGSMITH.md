# LangSmith 集成指南

## 1. 注册并获取API Key

1. 访问 https://smith.langchain.com/
2. 注册账号（免费额度：5000 traces/月）
3. 在 Settings → API Keys 创建新的API Key

## 2. 配置环境变量

在 `.env` 文件中添加：

```bash
# LangSmith配置
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
LANGCHAIN_API_KEY="your-langsmith-api-key"
LANGCHAIN_PROJECT="finance-agent-system"  # 项目名称
```

## 3. 零代码集成（自动追踪）

LangSmith会自动追踪所有LangChain组件：
- ✅ LangGraph工作流
- ✅ ChatOpenAI调用
- ✅ Agent执行
- ✅ Tool调用

**无需修改任何代码！**启动应用后访问 https://smith.langchain.com/ 查看追踪数据。

## 4. 高级功能：自定义追踪

如果需要添加自定义元数据或评估，可以使用以下代码：

```python
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

# 装饰器模式
@traceable(name="custom_analysis", run_type="chain")
async def custom_analysis_with_tracing(data: dict):
    """自动追踪的自定义分析函数"""
    # 添加自定义标签
    run_tree = get_current_run_tree()
    if run_tree:
        run_tree.add_tags(["production", "stock_analysis"])
        run_tree.add_metadata({
            "stock_code": data.get("stock_code"),
            "company_name": data.get("company_name")
        })
    
    # 你的业务逻辑
    result = await some_analysis(data)
    return result
```

## 5. 查看监控数据

访问 LangSmith Dashboard：
- **Traces**：查看每次执行的完整链路
- **Runs**：每个Agent/LLM调用的详细记录
- **Latency**：延迟分布图
- **Token Usage**：Token消耗统计
- **Cost**：成本分析（支持多种模型定价）

## 6. 评估功能（可选）

```python
from langsmith import Client
from langsmith.evaluation import evaluate

client = Client()

# 定义评估函数
def accuracy_evaluator(run, example):
    """自定义评估器"""
    prediction = run.outputs.get("final_report")
    expected = example.outputs.get("expected_report")
    # 你的评估逻辑
    return {"score": similarity_score(prediction, expected)}

# 运行评估
results = evaluate(
    lambda inputs: your_agent.run(inputs),
    data=client.list_examples(dataset_name="test_stocks"),
    evaluators=[accuracy_evaluator],
    experiment_prefix="finance-agent-v1"
)
```

## 优势总结

✅ **零代码集成**：只需配置环境变量
✅ **原生支持**：与LangGraph完美集成
✅ **实时监控**：即时查看执行链路
✅ **成本追踪**：自动计算Token成本
✅ **团队协作**：支持多人查看和分析
