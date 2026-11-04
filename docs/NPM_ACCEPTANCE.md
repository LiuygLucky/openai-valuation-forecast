# NPM 口径真实运行验收（2026-11-04）

当前默认目标是 OpenAI 在 2026-12-31 美国东部时间当日结束时的 NPM 隐含公司估值区间（USD billion）。研究终点与 Polymarket 部分“期间触及阈值”合约不同。

## 官方锚点

- [NPM OpenAI 数据页](https://fe.secondmarket.com/companies/company-30839e0b-2730-4495-839f-1bf638fa9cca/data)在 2026-11-04 浏览器中显示 2026-10-29 整体 Valuation 约 $1.255T、Price Per Share $1,015.13。
- 该页公开接口原始字段为 `latest_npm_price.date=2026-10-29`、`implied_valuation=1254731740680.9697` USD、`price=1015.13244833` USD/share。LIVE 保存整份原始响应和字段引句，抓取时间作为可用性代理，不伪称精确发布时间。
- $1,006.33 是 2026-10-20 的每股价格，不是十亿美元整体估值。公开接口 `npm_prices` 历史值为 1006.33231227 USD/share。

## 真实运行

- run_id：`56aab404e5dd43cfa34e9ea57e7892fc`；`completed`。初次研究规划校验失败，修正规则后从同一记录续跑，累计预算未清零。
- [报告](../reports/runs/live/56aab404e5dd43cfa34e9ea57e7892fc/report.md)、[完整状态](../reports/runs/live/56aab404e5dd43cfa34e9ea57e7892fc/state.json)、[独立复算](../reports/runs/live/56aab404e5dd43cfa34e9ea57e7892fc/verification.json)。复算验证来源支撑、时间/模式隔离、预算、概率和、完整产物与精确数值重放，均通过。
- 基准 1254.7317406809698 USD billion；中位数 1253.3407280612837 USD billion；90% 模型区间 887.1720–1776.4161 USD billion。
- 2 轮研究，10 次 LLM、9 次搜索（其中 NPM 官方接口 2 次）、2 次 Embedding；估计预算 1.232325 USD，非账单金额。最终 80 项 pytest 与 ruff 通过。

## 解释与限制

NPM 的 10 月 29 日整体估值取代了旧的 3 月融资估值作为中心锚点。最终接受的经营和融资事件日期均早于该观测日，数值更新规则视其已被锚点吸收，事件对数调整总和为零；因果推理仍记录正向与负向机制。波动率、事件幅度、已计价判断和情景权重未经历史回测校准；可复算不等于预测准确。若 NPM 停止更新或观测超出 14 天，LIVE 应拒绝给出新的概率。
