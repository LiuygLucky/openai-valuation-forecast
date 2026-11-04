# Cognitive Forecasting Agent V1

给初次接触 Agent 开发的同学：[从零到当前 V1 的完整实现讲解](docs/V1_从零到实现_讲解.md)。
信念更新的最新修订、旧报告问题和离线对照见 [V1.4 信念更新说明](docs/BELIEF_UPDATING_V14.md)。

面向《认知智能前沿实践》的 OpenAI 终点估值区间预测系统。输入问题后，执行真实搜索、结构化证据整理、SQLite/FAISS 检索、因果机制假设、独立审查、有限补充研究、数值概率更新和报告保存。

**当前默认口径：Nasdaq Private Market（NPM）公布的 OpenAI 隐含公司估值。** [NPM 验收说明](docs/NPM_ACCEPTANCE.md)记录了本机真实运行；旧的[融资代理验收](docs/ACCEPTANCE.md)只作历史记录。预测参数仍为未校准假设。最新信念更新算法为 v1.4，84 项测试通过。

公开仓库只包含代码、配置样例、文档、合成演示和不含原始来源全文的离线对照摘要。本机 `.env`、SQLite、LIVE 原始状态/报告、日志及临时文件由 `.gitignore` 排除；文档中提到的 `reports/runs/...` 路径是本机运行产物，新克隆的仓库不会自带这些文件。

## 1. 安装与启动（Windows / Python 3.12）

在项目目录使用 PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python main.py --demo --as-of 2026-11-02T06:30:00+00:00
.venv\Scripts\python -m streamlit run app/streamlit_app.py
```

如果从受限的自动化环境启动页面，DEMO 仍可运行，但 LIVE 调用模型时可能出现 `ConnectError`。此时在你自己的 PowerShell 中用上面的命令启动 Streamlit；网络连接失败与密钥无效、证据不足是不同的故障。
本机已另外启动可联网页面 `http://127.0.0.1:8502`；旧的 8501 页面若仍在运行，可能继续受网络隔离影响。在自己的 PowerShell 启动时可加 `--server.port 8502` 选择该端口。

LIVE 点击“开始预测”后会在后台进程执行。可切换到“预测历史”并选择 live，状态每 5 秒自动刷新；`running` 表示任务仍在执行，结束后显示 `completed` 或 `failed`。页面切换不会中断后台任务。后台进程意外退出时，历史页会将遗留的 `running` 记录标为 `failed`，其诊断日志位于 `data/jobs/<run_id>/stderr.log`。新提交的任务会产生新 run_id；“载入所选记录”只查看已保存状态，不会启动或恢复任务。

本项目已在当前电脑创建 `.venv` 并安装依赖，可直接使用后两条命令。无需激活环境或更改 PowerShell 执行策略。首次下载依赖需要联网；默认演示、字符向量检索和数值模拟不需要网络或 GPU。

开发安装使用 `pyproject.toml` 的兼容范围；`requirements-lock.txt` 记录本次 Windows/Python 3.12 验证过的准确依赖版本。复现实验环境：

```powershell
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m pip install --no-deps -e .
```

## 2. 真实运行

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 在本地编辑 .env，填写密钥，不要把密钥提交到仓库。
.venv\Scripts\python main.py
```

`.env` 必须包含：

```dotenv
TAVILY_API_KEY=你的Tavily密钥
LLM_API_KEY=你的DeepSeek或Qwen密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

模型名称只是可修改的配置示例，请填写账号当前可用且支持 JSON 输出的模型。Qwen 可使用其 OpenAI-compatible endpoint（`.env.example` 提供示例）；不同地域账号的地址可能不同。优先采用百炼凭据导出文件中的 `openAiCompatible` 地址，业务空间专属地址不要替换为其他地域。接口通过 HTTP 调用 `/chat/completions`，`response_format=json_object`，返回值必须通过 Pydantic 校验。

真实模式不会自动切换到合成模式。缺密钥、搜索失败、模型返回无效 JSON、预算耗尽、找不到有日期且可靠的估值锚点，均会报错并保存失败状态。单条估值证据的引句或单位校验不通过时，将整条证据隔离并记录来源与原因，其他合格证据可继续处理。当前 NPM 口径从 [NPM 官方 OpenAI 数据页](https://fe.secondmarket.com/companies/company-30839e0b-2730-4495-839f-1bf638fa9cca/data)所用公开接口读取公司整体 `implied_valuation` 与每股 `price`，保存原始响应、观测日期与抓取时间。若接口不可达或最新观测超过 14 天，不会使用融资后估值或其他平台价格替代。

Tavily 默认 `search_topic=auto`：成本/现金消耗问题使用通用搜索，其余使用新闻搜索；也可固定 `news` 或 `general`。`site:` 被明确转成 API 的域名过滤。通用搜索遇到相关路透社文章无日期时，至多补查一次新闻元数据；调用计入预算并记录实际查询。日期优先使用搜索服务公开时间；路透社日期型文章 URL 与正文明确日期一致时，可使用保守的 UTC 当日末代理并记录依据，不假称精确发布时间。其他缺时间来源保留供审查，但不能参与概率更新。融资代理锚点须来自可靠来源，美元金额必须明确对应整体估值，不能使用融资额或股东持股价值。

## 3. 任务与结算定义

默认问题：OpenAI 在 **2026-12-31 当日结束时** 的 NPM 隐含公司估值区间。Polymarket 仅提供预测题目，区间由本研究定义，不复现其“期间曾触及阈值”的路径合约。

平台已选 Nasdaq Private Market。NPM 公司数据页标明每天美东时间 13:00 更新；非交易日或价格不变时可能沿用上一观测值。目标日暂按 `America/New_York` 当日 23:59:59 定义，取该目标日对应的最后可用 NPM 公司估值观测；原始观测日期与实际抓取时间分别记录。2026-10-29 官方数据为约 1.255 万亿美元公司估值和 1,015.13 美元每股价格，二者不能混用。

`config/market_rules.yaml` 明确记录：

- `forecast_type=terminal_interval`：终点区间；不支持将“截止日期前是否曾达到阈值”的路径事件当作此结果。
- 单位 `USD_billion`：十亿美元；500 表示 5000 亿美元。
- `[lower, upper)` 左闭右开；从 0 连续覆盖至无穷；最后的 `upper: null` 表示无上界。
- 默认区间为 `<500B`、`500–750B`、`750–1000B`、`1000–1250B`、`1250–1500B`、`≥1500B`。中央区间按 250B 等宽，两端保留开放尾部，避免将所有超过 1000B 的结果合并。它们是可修改的展示分组，不代表置信区间或实证校准的最优分箱。
- `provider=NPM`：只用 NPM 官方公开接口的 `implied_valuation`（美元）换算成 `USD_billion` 作锚点，`price`（美元/股）另存。超过 14 天的观测拒绝作为最新锚点；NPM Price 是指示性估计，并非成交保证。
- 规则来源、状态、时区、数据缺失、更新、IPO 规则均可手动修改并随每次预测保存。

无需提供 Polymarket 合约链接。若找不到可审计的近期 NPM 公司整体估值，本系统应保存失败状态，不生成 NPM 概率。已完成 IPO / 指标失效的可靠证据会触发拒绝；潜在 IPO 仍属于不确定因素。历史报告保留各自运行时的配置。

CLI 支持 `--settings 路径 --rules 路径 --question 问题`。TaskSpec 从问题识别目标日期、年底、融资代理/NPM/Forge 与显式区间边界；问题明确指定的字段覆盖 YAML 默认值，并记录字段出处。示例：`OpenAI 2027年底估值，区间边界（十亿美元）：500,750,1000,1250,1500`。多个日期、混用平台、缺区间单位和路径事件会被拒绝。Dashboard 的日期与区间编辑框须与问题一致，冲突时会在联网前提示。

## 4. 工作流与模块接口

```text
ParseQuestion → PlanResearch → Search → ProcessEvidence → RetrieveMemory
                                     ↑                         ↓
                                     └─ 检查缺口 ← Critique ← Reason
                                            ↓
UpdateBelief → GenerateForecast → GenerateReport → SaveRun
```

| 模块 | 输入 → 输出 | 实现 |
|---|---|---|
| 控制器 | 问题、Settings、MarketRules → CognitiveState | LangGraph；每节点 SQLite 快照、JSON 检查点 |
| 规划 | 问题、规则 → ResearchPlan | 优先级、理由、搜索查询、期望信息 |
| 感知 | 查询 → SearchResult[] | Tavily HTTP；有限重试；检索时间与原始正文 |
| 证据处理 | SearchResult[] → Evidence[] | 引句、数值单位检查；来源规则；事实/报道/推断区分 |
| 记忆 | 时间过滤后证据、问题 → Evidence[] | SQLite 原始证据；FAISS 余弦检索；保留最新锚点 |
| 推理 | 证据 → Hypothesis[] | 中间变量、方向、计价、反向解释、不确定性 |
| 审查 | 证据、假设 → Critique | 独立 LLM 步骤 + 去重、日期、冲突硬规则 |
| 信念更新 | 可接受证据、假设、参数 → belief_state | 固定随机种子；显式参数；受限事件调整 |
| 输出 | 状态 → Forecast、报告 | Pydantic；JSON、Markdown、SVG、Plotly HTML |
| 历史 | 两次状态 → 差异 | 区间概率变化、新证据、锚点/参数/事件变化 |

`core/schemas.py` 定义所有跨模块对象。核心 `CognitiveState` 包含 `run_id/question/as_of/target_date/mode/research_plan/search_results/evidence_ids/retrieved_evidence/hypotheses/causal_relations/critique/information_gaps/search_history/belief_state/forecast/iteration_count/warnings/trace/usage/status`。

LLM 不允许提供最终区间概率。其输出引用的证据 ID 必须存在。因果机制仅为可追溯的模型假设，并非因果识别结果。

## 5. 数值计算与可复现性

基准为对数正态终点估值：

```text
origin = anchor.event_at or anchor.published_at
T = (target_date - origin) / (365.25 * 86400 seconds)
age = (as_of - origin) / (365.25 * 86400 seconds)
log(V_baseline) = log(anchor) + annual_log_drift*T
                  + sqrt(annual_log_volatility²*T + proxy_extra_log_sigma²
                         + anchor_age_log_sigma²*age + unknown_date_sigma²)*Z
Z ~ N(0, 1)
```

`annual_log_drift` 是**对数估值漂移**，不是算术增长率，因而这里不再减 `0.5*vol²*T`。融资代理的额外不确定性为独立对数误差项；切换到匹配的报价商口径时不加该代理误差。旧锚点从事件日期传播；日期未知时仅允许可靠官方公告时间代理，另加日期误差。180 天是过时提示而非拒绝阈值；最大锚点年龄 1095 天，额外陈旧性误差系数 0.15/平方根年，未知日期误差 0.10，均为未校准假设，不把旧交易声称为当前报价。

事件更新规则：

1. 相同事件/转载内容归组；同一事件只计一次。互相冲突的报价整体列为争议。
2. 锚点本身和锚点公开前的信息不再产生额外事件调整。
3. 锚点后的可接受独立事件，根据可追溯方向赋予 `±event_log_shift`；已计价折扣分别为 `likely=0`、`possible=0.5`、`unlikely=1`、`unknown=0.25`，再乘 `exp(-公告年龄天数/365.25)`。已知发生在锚点前的旧事件不因新报道重复计入；传闻/评论/性质未知的内容不参与数值调整。
4. 总对数调整被限制在 `±max_total_log_shift`。
5. 采用“无事件效应 / 中央效应 / 双倍效应”三情景，倍率 `[0,1,2]`，主观权重 `[0.25,0.5,0.25]`；再次应用总调整上限。
6. `V_posterior = V_baseline * exp(clipped_shift)`。默认 50,000 次样本，区间概率为样本频率。基准与更新模型共享基准随机数，降低比较噪声。

**所有波动率、漂移、事件幅度、计价折扣和情景权重均为未校准假设。** “posterior” 是代码中更新后分布的名字，不意味着严格的贝叶斯后验。来源可信度用于筛选，不被当作事件概率。90% 区间是模型区间，不代表实际覆盖率经过验证。

报告保留锚点 URL、证据 ID、每项事件调整、先验、情景、随机种子、采样数、完整规则及配置快照。演示数据并不支持任何预测准确率结论。`evaluation/metrics.py` 提供未来有真实结算结果后使用的 Brier score 函数，当前没有伪造回测成绩。

## 6. 预算与研究限制

默认最多 2 轮研究、每轮 3 个查询、9 次搜索请求（含重试）、16 次 LLM 调用、20 次 Embedding 调用、350,000 个合计保守预留 token、2 USD 单次运行估计预算。成本费率是可配置的保守假设，不是供应商现行报价或账单。必须根据实际账号计费调整。

每次网络调用前预留预算；LLM 用 UTF-8 字节上界估算输入 token，加最大输出 token。实际使用量在供应商返回时记录。搜索失败允许有限重试；部分查询失败会记录警告，若已有足够有效证据可继续，否则失败。LLM 结构错误最多重新请求一次，重试也计入预算；仍无效则失败，不用自编结果顶替。

每轮最多处理 6 个新文档，每文档送给 LLM 的摘录上限 5,000 字符；原始搜索正文（Tavily 适配器上限 12,000 字符）留在状态/证据中。按研究查询轮询选择，优先可信来源。未处理部分和截断风险须纳入信息不足判断。大任务可提高这些值与预算。同版本重复内容不会再次调用抽取模型。

正式输出须通过硬验收：至少两个来源域名、三类重要因素、有来源的正负因素及可引用因果机制；同时须有合格的已完成交易锚点。首轮保留融资、收入、成本三个方向的来源限定查询，第二轮针对缺口补充。此覆盖检查不等同全面研究或统计独立性保证。

## 7. 时间隔离与记忆

- 分开保存事件时间（未知可空）、公开时间、检索时间；不由 LLM 填造发布时间。
- 本地查询要求 `retrieved_at <= as_of`，且已知 `published_at <= as_of`。
- 相同文档版本只保留首次观察快照；原始内容或公开时间变化视作新版本。
- 抽取版本也纳入证据 ID，避免旧未经新规则校验的记录覆盖新结果。最近 7 天内的真实原始搜索快照可重新处理，保留原检索时间，不伪称重新搜索。
- LIVE 模式只允许当前研究，信息截止时点随采集推进，最后冻结于研究采集结束。CLI 的自定义 `--as-of` 只用于合成演示，真实历史实时搜索会被拒绝。
- 本地时间过滤只能验证本系统记录，不能证明更早的互联网历史可获得性；本项目没有宣称实现合格的历史回测。
- `mode` 分离真实和合成证据、报告与历史比较。

真实模式默认 `api:text-embedding-v4`，通过兼容 `/embeddings` 接口生成 1024 维语义向量并用 FAISS 检索；按内容和模型缓存到 SQLite，每批不超过 10 条。默认复用千问的 LLM 凭据，独立端点可配置 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY`。DeepSeek 聊天端点不能假定提供该向量模型，需另外配置向量端点或改用本地模型。调用失败明确报错，不静默降级。2026-11-03 真实语义探针结果保存在 `reports/embedding_validation.json`。

离线 demo 固定使用无需下载的 `hashing-char-1024`，它是字符特征而非神经语义模型。也可选择本地 SentenceTransformers：

```powershell
.venv\Scripts\python -m pip install -e ".[embedding]"
```

然后把 `embedding_model` 改为可用的 SentenceTransformers 模型名称或本地路径；在 CPU 上运行。首次使用在线模型名称需要下载文件。V1 对时间筛选后的少量证据重建内存索引，以避免跨时间/跨模式检索污染。

## 8. 输出、界面与历史

- `reports/runs/<mode>/<run_id>/report.md`：研究报告。
- 同目录 `forecast.json`、`state.json`、`probabilities.svg`、`probabilities.html`、`terminal_distribution.html`：结构化预测、完整状态与静态/交互图。
- `reports/runs/<run_id>.state.json`：可审计的完整最新状态。
- `data/forecast.sqlite`：证据、运行历史、每一步状态快照。
- `reports/demo/`：本次交付归档的合成演示报告。

Dashboard 包含预测任务、研究过程、预测结果、预测历史四页；支持下载 Markdown / JSON / 完整状态、切换历史记录、显示概率差异。只比较同模式、同目标、同指标、同边界与规则的记录。历史解释关联证据来源、锚点与参数变化，并将概率变化算术分解为基准差和事件调整分量差，不声称严格因果归因。

Markdown 下载后的图片需要同目录 `probabilities.svg`；完整本地报告目录已包含该文件。Plotly HTML 内嵌脚本，打开归档图不需要 CDN。

## 9. 测试与验收

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python main.py --minimal --demo --as-of 2026-11-02T06:30:00+00:00
.venv\Scripts\python scripts/verify_run.py reports/runs/demo/805beacc6ea64ef0b2e5cce9211d69ce/state.json
```

自动测试覆盖任务书的 10 项要求，以及估值引句/单位、恶意域名、缺锚点、冲突报价、未知证据引用、IPO 失效、预算前置阻断、失败持久化、不可比历史拒绝和 Streamlit 完整演示流程。HTTP 成功/失败测试使用测试替身，不是实际供应商验收。

pytest 使用项目内 `data/test_tmp/<随机ID>`，避免共享 Windows TEMP 目录的权限冲突。

本机密钥已配置。重新部署时需按上文设置。真实数据验收检查：多个来源、至少三类因素、正反证据、有效估值锚点、完整概率分布、参数披露与公开时间；当前结果见 `docs/ACCEPTANCE.md`。缺证据时保留失败记录，不声称验收通过。

## 10. 分阶段交付与后续扩展

已实现：M1 最小 CLI 闭环；M2 规划/记忆/推理/独立审查/有限研究；M3 可复现概率及报告；M4 Dashboard、历史、测试、环境及文档。真实研究、概率报告与无网络数值复算已通过；仍保留未校准参数及数据覆盖限制。

V2 可替换接口：SearchClient 搜索供应商、JsonLLM 模型、VectorMemory 向量模型、update_belief 数值模型；可增加历史参数估计、严格回测、概率校准、因果图、模型融合、市场共识和信息价值研究。V1 不含训练、交易、下注或复杂多智能体系统。

工程续接请先读 `PROGRESS.md`。源码、报告、SQLite 快照会保留；聊天中断后从记录继续开发。运行中断可执行 `.venv\Scripts\python main.py --resume <run_id>`，演示任务加 `--demo`。从最后完成节点继续，累计 API 预算不清零；尚未完成的网络调用可能重做，不能保证供应商侧恰好执行一次。重启时使用本地配置并在最终状态保存计算快照；不要通过增大预算绕过原限制。修复抽取逻辑后，可加 `--resume-from ProcessEvidence` 显式重新处理保存的真实来源；不会重新搜索或清零预算。Windows 检查点替换支持短暂文件占用的有限重试。

## 官方接口参考

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)
- [千问兼容 Embedding 接口](https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai)

