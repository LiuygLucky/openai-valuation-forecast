# 开发与续接记录

原始要求：完整遵循 `prompt.md`，按 M1 → M2 → M3 → M4 实施。
环境：Windows / Python 3.12.7；项目内 `.venv`。
保密：不记录密钥；用户提供的 Tavily 与千问凭据已保存在被忽略的本地 `.env`。

## 最新结论：NPM 口径真实运行与独立复算通过（2026-11-04）
- 信念更新补充验证：合成锚点后新事实测试确认有正向机制时 `log_shift>0` 且概率改变；最终 84 pytest passed、ruff passed。此为机制测试，非真实新事件或回测。
- 2026-11-04 用户指出最新 v1.3 LIVE 全部 `log_shift=0`，认知推理没有改变概率。已确认属实：锚点前事实按已计价规则排除后，报告六个区间与基准完全相同。V1.4 新增对已接受、引句覆盖目标年、且有一致方向机制的未来 `forecast` 证据建模为零均值兑现风险，不把锚点前旧消息当成方向性新冲击。新报告展示各区间相对基准的百分点差异；旧 v1.3 算法按版本保留，原运行精确复算仍通过。用 `3b5d4780` 保存证据做零网络离线反事实：现金消耗预测被纳入，750–1000B 概率变化 +0.126 个百分点；移除该预测的消融测试回到基准。结果在 `reports/analysis/belief_update_v14_counterfactual.json`；详细方法和未校准限制见 `docs/BELIEF_UPDATING_V14.md`。83 pytest passed、ruff passed。未执行新的真实 LIVE；不能将离线对照称作新预测或已验证的准确率改善。
- 2026-11-04 新增面向零基础同学的 `docs/V1_从零到实现_同学讲解.md`，按当前源码解释需求、M1–M4、技术栈、LangGraph 数据流、各模块接口、NPM 锚点、概率模型、DEMO/LIVE、运行/续接和教学演示路线；README 已链接。此轮只改文档，未重跑真实 API。
- 2026-11-04 新 LIVE `3b5d47809dbb4830821e8fc36989a05f` 初次失败 `MissingAnchor`。根因：审查去重把不同观测日期的 NPM 官方数据因原始响应相似而归为同组，数值不同遂全部争议；实际官方新观测为 2026-11-02 `implied_valuation=1263746113857.92` USD。现不同日期 NPM 观测不按重复事件合并；经严格来源、状态、日期及同日数值一致性检查，最新官方观测保留为接受证据。新增回归测试；82 pytest passed、ruff passed。已沿用原预算/证据从 Critique 节点续跑同一 run_id，最终 `completed`，中位数 1262.3932846 USD billion，9 次 LLM、9 次搜索、2 次 Embedding，费用估计 1.588443 USD（非账单）。`scripts/verify_run.py` 全部检查通过，验证阶段零网络调用；报告 `reports/runs/live/3b5d47809dbb4830821e8fc36989a05f/report.md`。历史失败警告作为审计记录仍在报告中，不代表终态。
- 2026-11-04 用户新 LIVE `3fe1d5595eea46169bf54903daf624e3` 在搜索后证据抽取失败：千问两次返回 `claim_kind="reported claim"`，不在模式枚举中。`ExtractedClaim` 现将该特定模糊标签规范为 `unknown`，不擅自提升为已发生事实；来源/引句/估值数值校验不放宽。新增回归测试，81 pytest passed、ruff passed。已从 ProcessEvidence 检查点沿用原预算与搜索快照续跑同一 run_id，最终 `completed`，2 轮，9 次 LLM、9 次搜索、2 次 Embedding，费用估计 1.436164 USD（非账单）。报告 `reports/runs/live/3fe1d5595eea46169bf54903daf624e3/report.md`，中位数 1253.340713 USD billion，独立 verify_run 所有检查通过，无验证阶段网络调用。报告 limitations 保留最初失败信息作为续跑审计轨迹；该失败已解决，不能解读为最终状态。
- 用户指定 Nasdaq Private Market OpenAI 数据页作为结算指标。2026-11-04 浏览器实际页面显示 As of Oct 29, 2026、Valuation $1.255T、Price Per Share $1,015.13。其公开前端接口 `api-npm17-data-company-pricing-review-prod.k8s-prod-1.npmdev.net/api/public/companies/company-30839e0b-2730-4495-839f-1bf638fa9cca` 返回 `latest_npm_price.implied_valuation=1254731740680.9697` USD、`price=1015.13244833` USD/share、`date=2026-10-29`，2026-10-20 历史每股价格为 1006.33231227。页面与原始接口一致；没有把每股价格误当作十亿美元公司估值。
- 当前默认 `provider=NPM`、`valuation_metric=NPM_implied_equity_valuation`。LIVE 每轮单独抓 NPM 官方公开接口，预算计入搜索调用，原始 JSON、精确字段引句、抓取时间与观测日期保留；超过 14 天的观测不作新锚点。融资估值/Forge/其他平台不能替代。抽取版本 v1.5；全中性因果机制继续拒绝。研究计划优先级上限从 5 修正为 8，与最多 8 项计划一致。
- 新真实 run `56aab404e5dd43cfa34e9ea57e7892fc`：初次规划因旧优先级上限失败；修正后同 run_id 从持久化检查点续跑，预算累计未清零。最终 `completed`，报告 `reports/runs/live/56aab404e5dd43cfa34e9ea57e7892fc/report.md`；NPM 锚点 1254.7317406809698 USD billion，中位数 1253.3407280612837，90% 模型区间 [887.1720, 1776.4161] USD billion。各区间概率总和 1，独立 `scripts/verify_run.py` 全部检查通过、无验证阶段网络调用。2 轮研究，10 次 LLM、9 次搜索（含 NPM 官方接口）、2 次 Embedding，预算估计 1.232325 USD（非账单）。所有事件调整为 0，因为接受的经营/融资事件均早于 2026-10-29 NPM 锚点，按已计价规则处理；不是没有方向性假设，最终有 positive/negative 假设。模型漂移、波动、事件折扣均未历史校准。
- 本轮代码修改后 80 pytest passed、ruff passed；一个 Streamlit/NumPy 依赖弃用警告。旧融资代理和 Forge 过程记录只作历史，不代表当前默认口径。
- 2026-11-03 用户明确后续默认目标为 Forge Global 的 Forge Price Valuation。`config/market_rules.yaml` 已切换 `provider=Forge` 与专属指标；程序仅接受 Forge 官方、数值和观测日期均可核验、距信息截止不超过 60 天的 Forge Price Valuation，融资价/NPM/Premier 不代替。首轮搜索现在优先查 Forge；全中性因果假设会触发覆盖缺口；Forge 合成演示单独标记，旧融资代理历史保持原样。新报告模型版本 v1.3，抽取版本 v1.4。75 pytest passed、ruff passed；一个依赖弃用警告。
- 公开来源核查：Forge 官方方法说明 Forge Price 为按日衍生的指示性每股价格；公开旧文章显示 OpenAI 2026-09-21 约 894.33B 的 Forge 估值。Forge OpenAI 公司页当前将最新 Forge Price / Forge Price Valuation 隐藏为 `$--`，需登录；公开 2026-11 约 1.16T 的 Premier Alternatives 指示性估值不能冒充 Forge。用本地现有 Tavily 密钥实际做了三次 Forge 定向检索，未取得可解析的 OpenAI Forge 官方原文；直接 HTTP 访问 Forge 旧文章返回 403。未执行新的完整付费 LIVE，因为当前无可核验的最新 Forge 观测。用户被询问是否可提供带日期的 Forge 登录截图/导出/API；若没有，可进一步评估公开旧观测，但不能称其为 11-03 最新价格。
- 2026-11-03 用户对低估值提出异议后的审计：`5087a7cd...` 报告采用 `financing_proxy`，锚点为 2026-03-31 已完成融资 852B；未使用二级市场现价。该 run 仅生成 1 条 `neutral` 因果假设，所有事件 `log_shift=0`，因此 849.75B 中位数基本只是旧锚点的零漂移模拟。历史独立复算仅证明报告与代码一致，不能证明市场口径合适或预测已校准。公开可查的 Premier Alternatives 页面显示约 1.16T 的 2026-11 二级市场指示性估值，但页面未给出足以锁定 11-03 的逐笔成交时点；Forge 的 2026-09 指示性估值约 894.33B，不同平台口径有差异。需要明确目标平台/指标后修改锚点选择与来源规则，并对零方向假设设质量门槛；不能将 852B 融资代理结果当作二级市场年末报价预测。尚未因此重跑真实预测。
- 2026-11-03 LIVE 历史状态修复：用户新提交的 2 条任务停在 `running`。检查发现 Streamlit 原先在页面脚本内同步运行 LIVE，切换页面触发重运行断开执行，遗留运行中检查点。先将两条孤儿记录标为 `failed` 并保留证据和预算；其中 `5087a7cd7e9a4e759bef4c08302b18d6` 随后从检查点续跑至 `completed`，真实报告位于 `reports/runs/live/5087a7cd7e9a4e759bef4c08302b18d6/report.md`，独立离线核验全部项目通过。另一个 `634381d1576a4d0e861de6e0710475d8` 仍保留中断失败状态。
- LIVE 现通过独立 Python 子进程执行；历史页每 5 秒刷新，并对已退出进程的遗留 `running` 状态做失败收尾。任务配置快照与日志放在被忽略的 `data/jobs/`，密钥仍仅从本地 `.env` 读取。Windows 活跃进程判断已用实进程校验。新增后台作业测试；修改后 71 pytest passed、ruff passed。一个 Streamlit/NumPy 依赖弃用警告不影响结果。后台启动链路通过单元测试；本轮真实完整运行使用 CLI 检查点续跑，而非从更新后的页面新建付费任务。
- 2026-11-03 后续 LIVE 页面故障：用户点击运行后 `223fafd265044c58a96f69eec2cf89f4` 在 PlanResearch 调用千问时发生 ConnectError；1 次 LLM 请求已预留预算但供应商 token 0，搜索 0 次。受限执行环境访问已配置 LLM 地址失败；允许联网环境 GET 同一地址返回 HTTP 404，证明连接可达（未做付费重跑）。这是网络隔离，不是密钥/锚点错误。
- 已将网络连接错误与 JSON 校验错误分开，Streamlit 提示明确说明未开始搜索；可联网 Streamlit 现运行于 http://127.0.0.1:8502，健康检查 200 / ok。代码变更后 70 pytest passed、ruff passed。原 8501 页面可能仍是受限进程；用户需使用 8502 或在自己的 PowerShell 启动。
- 用户要求无需额外资料的功能已完成；当前无需新增密钥、GPU、Polymarket 合约或手工新闻材料。
- 最终真实 run：74b0c3df180549f899089a447fd0aa48；状态 completed；模型 v1.2；报告 reports/runs/live/74b0c3df180549f899089a447fd0aa48/report.md。
- 来源覆盖、正负因素、概率和、时间/模式隔离、原文支撑、预算、完整产物、精确数值重放全部通过，见同目录 verification.json。
- 最终真实研究两轮，7 次 LLM、7 次搜索、2 次 Embedding；成本估计 1.066516 USD（非账单）。历史失败调试与独立探针费用不包含在该数字中。
- 人工最终核对修复了 IPO 计划误判为完成上市、转载事件名差异造成重复调整；修复后不联网重新计算，旧报告归档 reports/revisions，原始证据和 SQLite 快照保留。
- 最新离线 run：805beacc6ea64ef0b2e5cce9211d69ce，DEMO/SYNTHETIC；完整运行与独立复算通过，无真实 API 调用。
- 最终验证：70 pytest passed；ruff passed；pip check passed；真实记录四页界面验证通过。Streamlit 127.0.0.1:8501 健康检查 200 / ok（沙箱内直连可能隔离；宿主联网执行已验证）。
- 已更新 README、docs/ACCEPTANCE.md、docs/PROMPT_GAP_AUDIT.md；旧审计留存 docs/history。
- 继续时先读本节与最终验收，不要将下方过程中的“正在运行/失败”误当当前最终状态。
- 后续限于 V2 优化或用户新需求：校准/回测/参数估计、具体报价平台。不要再次付费重复验收或覆盖本地 .env。

## 2026-11-03 开发调试历史（以下为过程记录，最新结论见上方）
- **当前最新检查点**：68 项 pytest 与 ruff 通过；完整离线 run 7f58d08bebd049308ace59f03bf491c1 精确复算通过。真实 run 74b0c3df 前缀正在运行（shell session 10457），此前 45fca141 在累计预算耗尽后停止，尚无真实概率成功报告。
- 关键筛选修复：主题匹配→可靠来源→日期已知→OpenAI 主体→新近日期，不再让无关官方页面或堆叠关键词的低可信转载挤占成本报道。已用本地快照确认有日期的 Reuters 成本报道排在前列。新增 processing_history 记录实际送入抽取的文档。
- 自动通用→新闻元数据补查已实测成功，reports/cost_date_probe.json 保留路透社 2026-09-18T22:42:32Z 来源；每次补查计入预算和搜索历史。类别同义词仅按明确映射规范化，未知类别仍拒绝；格式重试明确展示允许枚举。
- --resume 支持续跑；--resume-from ProcessEvidence 可显式重试保存的原始文档，累计预算不重置。max_llm_calls 为 16，350000 预留 tokens 和 2 USD 估计上限保持。不要对耗尽预算的运行盲目续跑。
- 最新：65 项测试通过。新增 --resume 从 SQLite 最后完成节点恢复，预算累计不清零；Windows 原子检查点替换增加文件占用有限重试。fdc3c789 首次因 Windows 文件锁在 Reason 节点后失败，现已从 Critique 续跑（shell session 74764）。
- 用单次通用搜索定位路透社现金消耗报道，保存 reports/cost_source_probe.json。根因之一是新闻搜索漏检历史成本报道，默认 search_topic 改为 auto；成本查询用 general。通用搜索无发布时间时，仅在路透社日期型 URL 与正文完整日期一致时记录保守 UTC 当日末代理，并保留 published_time_basis。
- 追加检查点：6e8ecc4d、2a7b0af5 两次真实运行未通过来源覆盖，均保存失败状态，没有概率。官方 852B 锚点现可由原文已完成交易语句解析；另发现 LLM 将微软 135B 持股误当整体估值，已加入独立持股/融资金额校验，抽取版本升为 v1.3，版本纳入证据 ID 防止覆盖旧审计记录。
- 已实现 7 天内原始搜索快照复用（保留原检索时间），按因素类别而非查询个数分配文档。新测试涵盖快照时间/模式隔离、域名过滤、金额类型。最近一次新增测试前 61 passed；当前 62 项中一个测试样本缺 OpenAI 名称已修正，待重跑。
- 正在执行 fdc3c789 前缀的新真实运行；若中断，先读对应 reports/runs/*.state.json 及 SQLite，不要把运行中当作通过。
- 最新检查点：语义 API 实测通过（reports/embedding_validation.json，1 次调用、30 tokens）；新增测试后一度 57 passed。之后增加 LLM 单次格式修复与域名过滤，相关测试正在更新重跑。
- 真实运行 01e96abc731e4e9a831ec15f6c74c176 失败：首轮有效来源不足，第二轮抽取 JSON 校验失败；保留失败状态。已修正 Tavily include_domains、优先三类来源查询及锚点补查顺序，禁止把融资代理缺少 Forge 报价当作必要缺口。
- 新版离线完整运行 0fcc03622e3d4d51aeaf662bb554d560 完成，报告在 reports/runs/demo 对应目录。scripts/verify_run.py 可不联网重放数值计算并核验报告、来源与隔离。
- 第二次修复后真实验收正在运行，最终结果未确认，不得提前计为通过。
- 用户已授权继续完成无需额外资料的功能，并重新进行真实验收。
- 已实现旧锚点从事件日/公告代理日至目标日传播，额外记录锚点年龄和未知日期误差；保留 stale 标记而非 180 天硬拒绝。
- 已增加原文支撑引句、事件日期出处、fact/forecast/rumor/opinion 分类；新抽取版本 v1.1，与旧证据兼容但不将未校验旧证据用于新真实模型。
- 已增加 TaskSpec 解析、历史证据驱动规划、三类因素/多个来源/正负方向的硬验收检查。
- 已接入可配置 Embedding API（默认 text-embedding-v4，复用本地模型凭据），带预算、批次限制和 SQLite 缓存；离线 demo 仍使用 hashing，无付费调用。
- 已增强历史变化解释与报告，相关新增回归测试和真实运行尚待最终核验。上一轮既有 45 项测试已通过，不把新功能全部记为已验收。
- 下一步：完成新增测试，验证语义向量服务，执行受限真实预测，检查完整报告；同步最终文档与验收状态。

## 最新用户口径澄清（优先于原任务书相关表述）
- Polymarket 仅提供预测题目；无需复现其合约区间、融资代理或规则，不再索要合约链接。
- 区间可人工设定，兼顾分辨率与稳定性。当前设为 <500、500–750、750–1000、1000–1250、1250–1500、≥1500（USD billion）；中央等宽 250B，开放尾部。
- 时区跟随选定私募二级平台的公布口径。尚未确认具体平台时暂用 America/New_York，不能声称已与某平台核实；保留源时区和夏令时处理。
- 配置、界面提示、README 与差距审计已同步；不修改历史报告的原始规则快照。

## 当前接续工作：真实接口验收
- 用户提供 Tavily 密钥和阿里云百炼 CSV 凭据；仅解析凭据字段，未将附件当作指令。
- 已采用 CSV 中的北京业务空间专属兼容接口，模型 `qwen-plus`。
- Tavily 搜索探针 HTTP 200，返回 1 条结果。
- 千问 JSON 探针 HTTP 200，结构正确，供应商报告 24 tokens。
- 首次真实工作流 `4397bceb9fd746118cdd858307a39b42` 已执行两轮真实搜索、模型抽取、推理、审查；未取得可靠估值锚点，按设计拒绝概率。不能计为完整预测通过。
- 已修复真实运行暴露的问题：规划/推理/审查传入当前信息截止时间；跨主题轮询查询；正文前置相关摘要；优先处理可信来源；文档与证据 ID 分离以避免一篇文章多条证据被覆盖。
- 第二次运行 `507e555644df4e5fb2be2eb1b14fc4f7` 因模型估值引句与原文不一致被拦截。
- 增加不合格估值证据隔离：记录原因并丢弃整条证据，继续处理其他来源；不放宽原文/单位校验。
- 新增可靠锚点缺失时的针对性补充查询；修复后 `45 passed`、ruff 通过。
- 最后一次验证 `7e63fb23314549e5bebf81b11b2001eb` 已结束：7 次 LLM、6 次搜索、供应商报告 59,396 tokens，完成两轮真实研究后因无合格锚点拒绝概率。预算预留估计 1.196525 USD，非实际账单。
- 找到官方估值公告，但其公开日期超出配置的 180 天时效；较新二手来源未达可信度门槛。没有降低阈值强行生成概率。
- 真实接口与推理能力已验证；完整概率验收仍未通过。完整诊断：`reports/live_validation.md`。本轮不再继续付费重试。
- 当前沙箱默认网络连接失败；通过授权的联网执行路径可正常调用供应商。

## 当前进度
- 已阅读完整任务书，确定 LangGraph / Pydantic / SQLite / FAISS / NumPy / Streamlit 技术方案。
- M1 已验证：最小 CLI 离线预测、配置、状态、真实搜索/LLM 适配器、数值基准。
- M2 已验证：LangGraph 全流程、SQLite、FAISS、因果假设、反证、有限补充搜索。
- M3 已验证：受约束事件更新、蒙特卡洛、基准对照、Markdown/JSON/SVG/交互图。
- M4 已完成代码和离线验收：四页 Dashboard、历史比较、README、45 项测试、依赖锁文件、离线报告归档。
- 最新测试 `45 passed in 6.97s`；ruff 通过；初始依赖检查和 compileall 通过。最初代理限制已通过允许的网络安装路径解决。
- pytest 临时目录位于 `data/test_tmp/<随机ID>`，避免系统 TEMP 的 ACL 冲突。
- 已运行完整离线 CLI 并生成报告；真实搜索与千问推理已接通，详细记录见上方真实接口验收。

## 最终交付（2026-11-02）
- `README.md`：安装、真实/离线模式、架构、公式、预算、时间隔离、运行与限制。
- `reports/demo/report.md`：固定截止时间 2026-11-02T06:30:00Z 的 SYNTHETIC 报告。
- 同目录含 `forecast.json`、`state.json`、`probabilities.svg`、`probabilities.html`。
- 演示两轮研究，50,000 次采样，概率和 1.0000000000；真实 API 调用数 0。
- `scripts/export_demo.py` 可重新生成归档演示报告。
- Streamlit 已启动：`http://127.0.0.1:8501`，健康检查 200 / ok。若进程已退出，按 README 重启。
- AppTest 验证点击预测和四页导航；测试替身验证 HTTP 适配器，不等同真实供应商验证。
- `AGENTS.md` 写入后续聊天的项目续接要求。

## 尚未完成的真实验收与代码差距
密钥缺口已解决，真实千问推理可用。目前仍需获得满足来源与日期约束的可靠估值锚点，才能生成合格的真实概率报告。
不应把代码交付与合成测试通过表述成任务书的真实运行验收已通过。
现有本地 `.env` 已可用，不要覆盖。继续时先读 `reports/live_validation.md`。后续可寻找近期可靠成交来源，或另行设计旧锚点的时间传播与额外不确定性模型；不要仅放宽日期过滤伪装成新报价。
若无可靠锚点或服务失败，保留失败状态并查明缺口；不得编造来源或静默替换合成数据。

2026-11-02 对照 prompt 完成更严格代码审计：`docs/PROMPT_GAP_AUDIT.md`。
纠正先前“只缺外部数据”的概括：180 天时效硬拒绝是实现选择；旧锚点时间传播、事件时间提取、研究覆盖验收、完整任务解析和可读历史变化解释仍需补强。语义 Embedding 分支存在但未启用验证。按最新用户澄清，不再把 Polymarket 合约核实作为缺项。
用户已有密钥足以继续这些开发工作；无需把代码差距都作为新的用户资源需求。

## 已知设计限制
- 默认结算规则和区间是研究定义，不是已核实的 Polymarket 合约。
- 默认字符向量 + FAISS；可切换 CPU SentenceTransformers。未宣称默认向量是神经语义模型。
- 参数是未校准启发式假设，无真实准确率或回测成绩。
- 运行快照可追溯，但不支持精确恢复中断的外部调用；失败任务重新启动新 run_id。

## 续接方法
1. 先读本文件、`prompt.md` 和 `README.md`（如存在）。
2. 查看现有实现，运行 `.venv\Scripts\python -m pytest -q`。
3. 从未完成里程碑继续，不覆盖用户配置，不伪称真实 API 验收完成。
4. 每阶段更新本记录；真实数据运行需要本地 `.env` 中有效密钥。

## 已核对技术文档
- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.tavily.com/documentation/api-reference/endpoint/search
- https://api-docs.deepseek.com/guides/json_mode/
