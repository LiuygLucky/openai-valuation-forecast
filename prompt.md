# Cognitive Forecasting Agent V1 — 认知智能事件概率预测系统开发任务书

## 0. 你的角色与任务

你是一名资深 AI Agent 系统架构师、Python 工程师和认知智能研究工程师，具备以下能力：

- 熟练掌握 Python、LangGraph、LLM API、RAG、Pydantic、Streamlit。
- 熟悉 AI Agent 的规划、工具调用、状态管理与多步骤推理。
- 理解事件预测、概率推断、贝叶斯更新、因果推理和预测评估。
- 能够设计结构清晰、可扩展、可测试、可复现的 AI 系统。
- 能够优先实现实际可运行的功能，而不是堆积复杂技术概念。

你的任务是为研究生课程《认知智能前沿实践》设计并实现一个 **Cognitive Forecasting Agent V1**。

**注意：这不是一个传统金融量化预测项目，而是一个以认知智能为核心的复杂现实事件概率预测项目。**

金融估值只是应用场景。项目的重点是让 AI 系统具备：

1. 主动信息获取
2. 外部知识记忆
3. 证据整合与可信度判断
4. 多步骤认知推理
5. 因果机制分析
6. 概率预测与信念更新
7. 结果解释与预测记录

V1 应优先实现完整且可靠的认知预测闭环，而不是追求复杂的金融数学模型。

---

# 1. 项目背景与预测目标

## 1.1 应用场景

项目研究对象是：

**OpenAI 在 2026 年 12 月 31 日的私募市场估值。**

我们希望结合 OpenAI 经营表现、融资情况、重大新闻、行业竞争、宏观环境和私募二级市场信号，预测其未来估值所处区间的概率。

项目同时参考 Polymarket 上与 OpenAI 估值有关的真实预测合约。

## 1.2 必须说明预测任务

### Task：终点估值区间预测

预测 2026 年 12 月 31 日的估值位于各区间的概率：

P(V_T ∈ I_k | Information_t)

输出一个所有区间概率相加为 100% 的分布。

注意：真实 Polymarket 合约采用“截止日期前是否曾经达到某估值阈值”的规则，则预测：P(max(V_t) ≥ K | Information_t)，这是路径事件，与最终日期的估值不同。而我们的任务是预测终点估值区间，即 2026 年 12 月 31 日当天的估值区间。

**V1 必须能够支持终点估值区间预测**

## 1.3 结算规则

真实预测市场的合约规则优先于我们的主观理解。

需要核实：

- 使用 NPM、Forge，还是其他估值指标。
- 是否以最终日期估值结算，还是以期间最高估值结算。
- 估值统计口径和单位。
- 更新时间与时区。
- 数据缺失、延迟、IPO 等特殊结算规则。
- 合约各阈值与价格区间的边界定义。

**不得假定 Forge 和 NPM 数据等价。**

如果程序无法自动确认合约规则，必须允许通过配置文件手动指定并记录规则来源。

---

# 2. V1 的核心目标

系统运行后，用户输入一个预测问题，例如：

“预测 OpenAI 在 2026 年 12 月 31 日的私募估值区间概率。”

系统应完成以下过程：

1. 识别预测任务、日期、指标和目标区间。
2. 规划需要研究的关键因素。
3. 调用真实的外部搜索工具获取信息。
4. 对不同来源的信息进行整理、去重和可信度判断。
5. 将重要信息存入结构化证据库。
6. 检索与预测目标最相关的证据。
7. 分析重大事件及其可能的因果影响路径。
8. 发现关键的信息缺口，必要时进行补充搜索。
9. 结合基本估值锚点、证据和显式假设形成概率预测。
10. 输出各估值区间的概率及不确定性说明。
11. 生成结构化研究报告。
12. 保存当前预测，支持与后续预测比较。

这十二个步骤必须构成一个真实可运行的端到端流程。

不接受只有框架、没有实际搜索和概率输出的系统。

---

# 3. V1 技术架构

建议采用以下整体架构：

用户预测任务
↓
Cognitive Controller（认知控制器）
↓
Research Planner（研究规划器）
↓
Search Tools（外部搜索工具）
↓
Evidence Processor（证据整理）
↓
Memory / RAG（外部知识记忆）
↓
Reasoning Engine（认知推理引擎）
↓
Evidence Critic（反证与可信度审查）
↓
Belief Updater（信念与概率更新）
↓
Forecast Generator（预测生成）
↓
Report Generator（可解释预测报告）
↓
Forecast History（预测历史记录）

其中 Cognitive Controller 使用 LangGraph 实现可追踪的状态流转。

整个系统应支持有限次数的循环研究：

Plan → Search → Analyze → Identify Gaps → Search Again → Forecast

必须设置搜索轮数、API 调用次数和 token 成本限制，避免无限循环。

---

# 4. V1 必须实现的核心模块

## Module 1：Cognitive State

系统需要维护明确的认知状态，不允许依赖 LLM 上下文隐式保存全部信息。

建议定义：

```python
class CognitiveState(BaseModel):
    question: str
    as_of: datetime
    target_date: datetime

    research_plan: list
    evidence_ids: list[str]

    hypotheses: list
    causal_relations: list

    information_gaps: list
    search_history: list

    belief_state: dict
    forecast: dict | None

    iteration_count: int
    warnings: list[str]
```

可以根据实际工程需求调整类型。

注意：

- LLM 结构化结果应经过 Pydantic 校验。
- 所有状态变化必须可以追踪。
- 状态应能够序列化和持久化。
- `as_of` 用于明确预测的信息截止时间。

## Module 2：Research Planner

输入：预测问题及当前证据状态。

输出：结构化研究计划。

例如：

- OpenAI 最新私募估值是多少？
- 是否有新的融资或股份交易？
- 最近有哪些重大收入与商业合作信息？
- OpenAI 当前主要竞争对手有哪些估值变化？
- 资本市场对 AI 企业的风险偏好如何？
- 哪些关键因素的不确定性最大？

研究计划必须包括：

- research_question
- rationale
- priority
- suggested_queries
- expected_information

V1 中可以由 LLM 生成研究计划，再通过简单规则控制优先级。

不要求精确实现信息价值的数学优化。

## Module 3：Search & Perception

至少实现一种真实可用的网络搜索工具。

推荐优先尝试：

- Tavily
- Exa
- Serper
- 其他可合法使用的搜索 API

使用环境变量配置密钥。

建议通过统一接口封装搜索服务，避免依赖某一家供应商。

每条搜索结果至少保存：

- title
- url
- source
- published_at（如可获得）
- retrieved_at
- content
- query

重要要求：

**必须获取真实外部信息，不能让 LLM 凭自身知识虚构新闻。**

如果搜索服务不可用，应该输出明确错误或进入离线测试模式，而不是静默使用编造的数据。

允许额外实现 Polymarket 官方 API 数据读取，但不是 V1 的硬性前提。

## Module 4：Evidence Processor

把搜索结果转换为结构化证据。

建议数据结构：

```python
class Evidence(BaseModel):
    evidence_id: str
    title: str
    source_url: str

    published_at: datetime | None
    retrieved_at: datetime

    claim: str
    category: str

    confidence: float
    relevance: float

    impact_direction: str
    reasoning: str
```

建议至少划分以下证据类别：

- valuation
- financing
- revenue
- profitability
- competition
- technology
- regulation
- macro
- other

要求：

1. 同一新闻被多家媒体转载时避免重复计权。
2. 区分官方公告、权威报道、分析师推测和社交媒体观点。
3. 区分已发生事实、传闻、预测和评论。
4. 保留原始 URL 和证据内容。
5. 对明显过时的数据给予标记。
6. 不得将来源可信度评分直接当作事件发生概率。

V1 可以采用规则 + LLM 的证据质量评分。

## Module 5：Memory / RAG

建立一个轻量级外部记忆系统。

建议使用：

- SQLite：结构化证据存储。
- FAISS 或 Chroma：文本向量检索。
- Embedding API 或本地轻量 Embedding 模型。

支持：

- 保存已检索文档。
- 按预测问题检索相关证据。
- 按事件类型检索。
- 按时间过滤。
- 根据 evidence_id 追溯来源。
- 避免重复保存相同内容。

不要在 V1 中引入过重的知识图谱数据库。

如果需要表示因果关系，可优先使用 NetworkX。

## Module 6：Reasoning Engine

这是 V1 最重要的研究模块之一。

系统不能只对新闻做摘要，而应分析：

“这条信息为什么可能影响最终估值？”

每个重要事件至少分析：

1. 事件是什么？
2. 哪些事实支持该事件？
3. 哪些关键事实仍不确定？
4. 它影响哪些中间变量？
5. 对 OpenAI 估值可能有什么方向性影响？
6. 这种影响是否可能已经被市场计价？
7. 有哪些相反解释？
8. 结论的主要不确定性是什么？

要求生成结构化的因果假设，例如：

```json
{
  "event": "大型企业合作",
  "mechanism": [
    "企业客户增长",
    "未来收入预期提高",
    "市场估值可能上升"
  ],
  "direction": "positive",
  "counterarguments": [
    "相关收入可能已被市场预期",
    "合作也可能增加算力成本"
  ],
  "evidence_ids": ["..."],
  "uncertainties": ["..."]
}
```

必须说明：

LLM 在这一阶段生成的是因果机制假设，不代表严格的因果识别已经成立。

V1 的目标是实现**可追溯的因果假设推理**，而不是声称已经获得无偏的因果效应估计。

## Module 7：Evidence Critic

建立一个独立的审查步骤。

它需要检查：

- 是否存在证据相互矛盾？
- 是否只检索到支持某个方向的新闻？
- 是否把媒体推测当作事实？
- 是否存在重复计权？
- 是否存在从相关性直接推导因果性的错误？
- 是否忽略重大负面因素？
- 是否有非常重要但未找到证据的变量？

输出：

- accepted_evidence
- disputed_evidence
- missing_information
- potential_biases
- recommended_followup_queries

V1 不必使用多个不同的大模型。

可以使用同一个 LLM、不同提示词和独立的状态步骤实现。

## Module 8：Belief Updater

这是整个项目的另一个核心。

必须维护显式的概率状态，而不是每次让 LLM 完全重新给出一个数字。

V1 可采用：

**基准估值分布 + 情景调整 + 事件证据更新**。

例如：

- 利用最新有来源的估值构建基准分布。
- 根据估值历史、融资和宏观市场信息设定合理的不确定性范围。
- 让推理模块提出带证据的情景变化假设。
- 使用受约束的数值更新规则生成新分布。

V1 不强制实现完整 PyMC 贝叶斯状态空间模型。

但概率必须有显式计算过程。

建议使用 NumPy / SciPy，通过蒙特卡洛采样生成估值终点分布。

必须记录：

- prior_assumptions
- baseline_valuation
- baseline_source
- event_adjustments
- scenario_assumptions
- posterior_distribution
- uncertainty_notes

特别要求：

**LLM 不得直接凭空生成最终各区间的概率作为唯一预测方法。**

LLM 可以辅助判断方向、提出合理情景和建议参数范围，但最终概率必须经过可复现的数值计算。

如果参数完全来自主观假设，应明确标注为启发式预测，不得伪装成经过数据校准的后验概率。

## Module 9：Forecast Generator

输出至少包括：

```json
{
  "question": "OpenAI valuation by 2026-12-31",
  "as_of": "...",
  "target_date": "2026-12-31",
  "valuation_metric": "...",
  "market_rules_source": "...",
  "forecast_type": "terminal_interval",
  "model_version": "v1.0",
  "probabilities": [
    {
      "interval": "...",
      "probability": 0.20
    }
  ],
  "median_valuation": 0,
  "confidence_interval_90": [0, 0],
  "key_evidence_ids": [],
  "main_assumptions": [],
  "limitations": []
}
```

约束：

- 所有区间概率非负。
- 区间必须无重叠、覆盖整个目标范围。
- 概率之和等于 1（允许数值误差）。
- 必须统一使用美元或明确的估值单位。
- 必须明确预测时点和目标日期。
- 必须提供最重要的证据来源。

实际估值区间应通过配置文件定义，不得将演示区间硬编码为正式合约规则。

## Module 10：Report Generator

生成可读的 Markdown 研究报告。

报告至少包含：

1. 预测问题和结算口径。
2. 当前关键事实。
3. 主要正面因素。
4. 主要负面因素。
5. 关键因果假设。
6. 最重要的信息缺口。
7. 估值区间概率表。
8. 概率分布图。
9. 当前结论。
10. 预测局限性与数据来源。

报告应做到：其他人即使不阅读代码，也能理解为什么系统得到这一预测。

每条重要事实都必须能够追溯到相应证据来源。

## Module 11：Forecast History

每次预测应保存：

- run_id
- model_version
- as_of
- generated_at
- forecast
- evidence_ids
- assumptions
- search_queries
- token_usage（如果可获得）
- run_cost（如果可获得）

支持比较不同日期的预测结果。

例如：

2026-11-02 → 概率分布 A

2026-11-09 → 概率分布 B

系统应能够解释主要概率变化来自哪些新证据或假设变化。

---

# 5. 认知控制器工作流

请优先使用 LangGraph 实现。

推荐最小状态图：

START
→ ParseQuestion
→ PlanResearch
→ Search
→ ProcessEvidence
→ RetrieveMemory
→ Reason
→ Critique
→ CheckInformationSufficiency
→ (必要时返回 Search)
→ UpdateBelief
→ GenerateForecast
→ GenerateReport
→ SaveRun
→ END

## 循环控制

需要实现以下限制：

- 最大研究迭代数，例如 2—3 次。
- 每轮最大搜索查询数。
- 单次任务的最大 LLM 调用数。
- 单次任务成本上限或预算估计。
- 搜索服务失败后的重试与降级。
- 未获得足够证据时允许拒绝输出高置信度预测。

V1 的策略应当简洁、可控、易于调试。

不要一开始实现复杂的自主进化、多层级多智能体辩论或无限递归研究。

---

# 6. 技术栈要求

优先采用：

创建本地虚拟环境

语言：
Python 3.12

Agent 工作流：
LangGraph

LLM：
支持 deepseek API，允许灵活切换 Qwen 等模型。

结构化输出：
Pydantic

数据分析与模拟：
NumPy、Pandas、SciPy

数据库：
SQLite

RAG：
FAISS 或 Chroma

Embedding：
可配置的 Embedding 模型

网络搜索：
至少一种真实搜索 API

可视化：
Streamlit + Plotly

配置：
.env + YAML

日志：
Python logging 或 structlog

测试：
pytest

代码质量：
ruff（推荐）

开发环境：
优先提供 uv 或 requirements.txt 方式安装。

## 算力限制

优先设计为：

- 普通 Windows 电脑可运行。
- 推荐内存 16GB。
- 不要求独立 GPU，若性能需要，可申请单卡 4090 服务器
- LLM 通过云端 API 调用。
- 不进行大型模型训练或微调。

如果使用本地 Embedding 模型，应选择能够在 CPU 上运行的轻量模型。

---

# 7. 推荐目录结构

```text
openai_valuation_forecast/
├── app/
│   └── streamlit_app.py
├── core/
│   ├── schemas.py
│   ├── state.py
│   ├── controller.py
│   └── config.py
├── perception/
│   ├── search_client.py
│   ├── research_planner.py
│   └── evidence_extractor.py
├── memory/
│   ├── evidence_store.py
│   └── vector_store.py
├── reasoning/
│   ├── causal_reasoner.py
│   ├── critic.py
│   └── gap_detector.py
├── belief/
│   ├── baseline.py
│   ├── scenario_updater.py
│   └── distribution.py
├── forecasting/
│   ├── forecast.py
│   ├── intervals.py
│   └── report.py
├── evaluation/
│   ├── metrics.py
│   └── history.py
├── data/
├── reports/
├── tests/
├── config/
│   ├── settings.yaml
│   └── market_rules.yaml
├── main.py
├── .env.example
├── pyproject.toml
└── README.md
```

可以根据工程需要适当精简，但职责划分必须清晰。

---

# 8. V1 界面要求

建议实现一个简洁的 Streamlit Dashboard。

至少包含：

### 页面一：预测任务

- 预测问题
- 目标日期
- 信息截止日期
- 预测区间配置
- 开始预测按钮

### 页面二：认知研究过程

展示：

- 研究计划
- 搜索查询
- 获取的证据
- 证据来源
- 主要因果假设
- 反方审查结果
- 搜索迭代次数

### 页面三：预测结果

展示：

- 各区间概率柱状图
- 估值分布图
- 估值中位数及区间
- 最重要的影响因素
- 主要风险
- 可下载 Markdown/JSON 报告

### 页面四：预测历史

展示：

- 历次预测时间
- 各次预测概率
- 主要预测变化
- 模型版本

界面不需要华丽，但必须能够真实运行和演示。

---

# 9. 严格的数据与研究规范

这是本项目非常重要的一部分。

## 9.1 禁止编造数据

不得伪造：

- OpenAI 私募估值
- Forge / NPM 报价
- 融资事件
- 财务数据
- 新闻来源
- 历史预测结果
- 模型回测成绩

所有真实数据必须有来源。

允许使用模拟数据进行单元测试，但必须明确标记为 DEMO / SYNTHETIC，不可混入正式预测。

## 9.2 防止时间信息泄漏

每次预测都有 `as_of` 时间。

必须区分：

- 事件发生时间
- 信息公开时间
- 系统检索时间

对于历史回测，只允许使用预测时点已经公开且当时可获得的信息。

注意：普通实时网络搜索不能天然保证历史时间隔离。如果无法验证信息在历史时点可获得，必须将该回测标记为不合格或仅供演示。

## 9.3 正确处理概率

不得把：

- LLM 的自信程度
- 新闻来源可信度
- 模型推理分数

直接视为最终预测事件概率。

必须通过明确的数值方法生成概率分布。

## 9.4 明确区分事实和推断

所有重要结论尽量区分：

- Verified Fact
- Reported Claim
- Model Inference
- Assumption
- Unknown

## 9.5 对缺失数据保持诚实

如果不能获取 Forge 或 NPM 的有效报价：

- 可以使用有来源的融资估值作为代理锚点。
- 必须注明它并非二级市场结算价格。
- 应增加不确定性并明确解释。
- 如果连最低限度的可靠锚点都没有，系统可以拒绝生成正式概率，或仅输出明确标记的探索性预测。

---

# 10. V1 需要的测试

至少实现以下自动测试：

1. 模型结构化输出是否符合 Pydantic Schema。
2. 外部搜索失败后是否正常处理。
3. 重复新闻是否能被识别。
4. 证据来源是否完整保存。
5. 研究循环是否在最大次数后停止。
6. 最终概率是否相加为 1。
7. 预测区间是否存在重叠或遗漏。
8. 模拟结果在固定随机种子下是否可复现。
9. 预测记录是否能够保存与读取。
10. 给定不同信息截止日期时，是否正确过滤已知发布时间之后的本地证据。

同时提供一个无需真实 API Key 的测试模式，使用少量明确标记的合成数据测试完整工作流。

真实预测模式必须使用真实外部数据。

---

# 11. V1 完成标准

以下指标都满足，才认为 V1 完成。

## 功能验收

- [ ] 输入预测问题后，系统能够自动制定研究计划。
- [ ] 能够调用真实搜索 API。
- [ ] 能够保存并检索结构化证据。
- [ ] 能够生成有来源的因果机制分析。
- [ ] 能够主动发现至少一个信息缺口，并决定是否补充搜索。
- [ ] 能够执行反方证据检查。
- [ ] 能够调用确定性的数值计算模块输出概率分布。
- [ ] 能够解释主要概率依据。
- [ ] 能够生成 Markdown 和 JSON 报告。
- [ ] 能够保存预测历史。
- [ ] Streamlit 界面可以完整运行。
- [ ] pytest 核心测试通过。

## 结果验收

至少完成一次 OpenAI 2026 年末估值预测的完整真实数据运行。

最终报告应包含：

- 有时间戳的研究任务
- 多个不同来源的有效证据
- 至少三类重要影响因素
- 正反两方面的分析
- 可追踪的因果假设
- 完整的概率分布
- 数值计算假设
- 对预测不确定性的说明

不能仅仅输出大段自然语言分析。

必须真正输出概率，并能追溯概率的产生过程。

## 性能验收

不要求 V1 一开始优于 Polymarket 市场共识。

但必须提供至少一个可比较的预测基准，例如：

- 最近有效估值 + 假设波动率
- 不使用新闻的基础概率模型

V1 的目标是完整性、真实性和可复现性。

预测准确率与概率校准将在后续版本优化。

---

# 12. V1 明确不做的功能

为了避免过度设计，第一版暂时不做：

- 大模型预训练或微调
- 复杂金融因子库
- 大规模量化回测平台
- 多层级 Agent 自主进化
- 大型图数据库
- 完整结构因果模型参数识别
- 大规模贝叶斯 MCMC
- 实盘预测市场交易
- 自动下注与交易执行
- 复杂分布式部署
- 微服务架构
- 实时高频数据处理

如果某项功能会显著影响 V1 的可交付性，优先保留简单但完整、可验证的实现。

---

# 13. 为 V2 预留的扩展能力

V1 在代码架构中应预留以下接口：

1. 引入更多独立研究 Agent。
2. 用真实历史数据估计事件影响。
3. 引入因果图、结构因果模型和反事实分析。
4. 引入贝叶斯动态状态空间模型。
5. 引入多个金融估值模型。
6. 引入多模型概率融合。
7. 增加 Polymarket 历史价格作为市场共识基准。
8. 引入信息价值驱动的主动搜索。
9. 进行时间滚动回测与概率校准。
10. 对认知模块开展消融实验。

要求模块间低耦合，便于替换实现。

---

# 14. 实施顺序

请不要同时开发所有模块。

按照以下顺序完成：

### Milestone 1：最小预测闭环

实现：

- 项目初始化
- 配置管理
- CognitiveState
- 基础搜索
- 单次 LLM 信息分析
- 基准概率模型
- 结果保存

要求：命令行能够输出一次结构化概率预测。

### Milestone 2：认知能力扩展

增加：

- Research Planner
- Evidence Processor
- Memory / RAG
- Reasoning Engine
- Evidence Critic
- 有限次数的补充搜索

要求：能够执行完整认知研究流程。

### Milestone 3：概率与可解释性

增加：

- 基准估值分布
- 事件情景调整
- 蒙特卡洛模拟
- 概率区间映射
- 报告生成

要求：正式概率有明确的可复现数值计算过程。

### Milestone 4：系统集成

增加：

- Streamlit Dashboard
- 预测历史
- 测试
- README
- 配置示例
- 完整演示

要求：其他同事能够通过 README 独立运行项目。

---

# 15. 对你的工作方式的要求

请先分析需求并给出：

1. 你理解的系统总体架构。
2. V1 的核心技术选择与理由。
3. 各模块之间的数据接口。
4. 关键状态 Schema。
5. 分阶段开发计划。
6. 最主要的工程风险及应对方式。

然后开始实际编写项目代码。

要求：

- 以可运行代码为核心交付。
- 不是只生成设计文档或伪代码。
- 不要只创建空文件和 TODO。
- 每完成一个 Milestone，运行相关测试并修复问题。
- 不要假装已经调用外部 API 或完成测试。
- API Key 缺失时明确给出配置方法。
- 关键模块提供类型注解和必要注释。
- 优先使用成熟框架，不重复造轮子。
- 避免过度抽象。
- 保持模块化与可维护性。
- 如果现有仓库已有代码，先检查现有实现，再做增量开发，不要盲目覆盖文件。

最终交付：

- 完整 Python 项目源码
- 可运行的认知预测工作流
- Streamlit 可视化页面
- `.env.example`
- `README.md`
- 核心测试
- 至少一份真实数据预测报告（如具备 API 和可靠数据）
- 一份明确标记的离线测试报告
- V1 已完成能力与 V2 待优化能力清单

**项目最终目标：构建一个能够自主研究现实事件、基于可信证据开展可解释推理、形成可复现概率预测，并随着新信息更新判断的认知智能系统。**

从现在开始，以实现 V1 为目标，优先保证端到端运行、真实数据、概率输出和证据可追溯性。
