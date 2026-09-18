# OpsPilot 200-case evaluation report

## Run metadata

- Timestamp: 2026-09-15T17:18:29+08:00
- Dataset: `opspilot_eval_200` v1.0.0
- Dataset type: curated synthetic offline regression cases
- Runtime: Docker Compose, OpsPilot API, ChromaDB, Nginx
- LLM: `deepseek-v4-flash` through the DeepSeek Anthropic-compatible endpoint
- Automated tests before evaluation: 16/16 passed
- Raw report: `data/eval/opspilot_baseline.json` (generated locally and ignored by Git)

The dataset contains no production tickets and must not be described as real enterprise traffic.

## Dataset composition

| Section | Cases | Purpose |
| --- | ---: | --- |
| Intent and clarification | 100 | Six-class intent, low-confidence clarification |
| Agent routing | 50 | Primary and secondary Agent selection |
| RAG retrieval | 25 | Recall@4 and first relevant rank |
| End-to-end dialog | 25 | Retrieval, routing, Agent execution and LLM Judge |
| Total | 200 | Stratified offline regression |

## Observed metrics

| Metric | Result |
| --- | ---: |
| Overall case pass rate | 196/200 (98.0%) |
| Intent accuracy / Macro-F1 | 100.0% / 100.0% |
| Clarification F1 | 100.0% |
| Routing primary accuracy | 100.0% |
| Routing exact match | 94.0% |
| Secondary Agent precision / recall / F1 | 94.74% / 90.0% / 92.31% |
| RAG Recall@4 / MRR | 100.0% / 100.0% |
| End-to-end primary Agent accuracy | 96.0% |
| Agent execution success | 100.0% |
| LLM Judge success | 100.0% |
| End-to-end Judge quality mean | 93.30% |
| Relevance / accuracy / completeness / actionability | 96.0% / 93.56% / 91.60% / 92.04% |
| End-to-end latency P50 / P95 | 8.27 s / 10.43 s |

## Failure audit

All four failures remain in the score:

1. `routing_22`: security was the correct primary, with an extra identity/access secondary.
2. `routing_30`: network was the correct primary, but the expected device secondary was missing.
3. `routing_38`: identity/access was the correct primary, but the expected security secondary was missing.
4. `dialog_16`: the blue-screen case selected software as primary and device as secondary; the expected primary was device. The answer still received a Judge quality score of 0.925.

## Resume-safe wording

搭建 200 条自建合成离线评测集（Intent 100 / Routing 50 / RAG 25 / E2E 25），基于 `deepseek-v4-flash` 实测 Intent Macro-F1 100%、主辅 Agent 路由 Exact Match 94.0%、辅 Agent F1 92.31%、RAG Recall@4 100%；端到端主 Agent 命中率 96.0%，LLM-as-a-Judge 质量均分 93.3%，P95 延迟 10.43 s。

## Claim boundary

- The Intent and RAG scores describe this fixed, in-domain synthetic dataset only.
- The retrieval corpus currently contains seven built-in SOP or incident documents, so Recall@4 does not establish large-scale retrieval quality.
- LLM-as-a-Judge is a model-based proxy, not a human acceptance score.
- Production claims require a separate, de-identified real-ticket evaluation set.
