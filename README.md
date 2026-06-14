# Observability-Collapse Differential (OcDiff)

Artifact (code + data) for the paper *"上下文压缩对编码智能体长任务退化的因果效应"*
(On the causal effect of context compression on long-task degradation in coding agents).

Under a **fixed model and task**, OcDiff flips only the **context-compression operator** that a
coding-agent **harness** applies to the accumulating interaction history, and measures whether —
and how much — that compression *causally* drives long-task degradation. The model is held
constant (a control), not a competing cause: the question is the size of the
compression → degradation effect, and how it varies across harnesses.

## Layout

| Path | What it is |
|---|---|
| `ctx_compress_proxy.py`, `ctx_compress_anthropic_proxy.py` | the model-boundary **uniform compression operator** κ_θ — reverse proxies that keep `system + first task + last-K` messages and drop the middle (OpenAI `/v1/chat/completions` and Anthropic `/v1/messages` surfaces). `start_ctx_proxies.sh` launches the 8 instances (keep `0/12/6/3` × 2 surfaces). |
| `matrix_runner.py` | the differential matrix: the configured harnesses × {Full, keep0, keep12, keep6, keep3} × 10 tasks × N=10, driven through the harness runner. The reported causal analysis covers the **6 harnesses with a valid baseline** (NoOp completion ≥ 30%); harnesses below that pre-registered measurability threshold have no degradation headroom and are not included in the causal test. |
| `scoring.py` | harness-agnostic **ground-truth** scorer — reads the final sandbox **filesystem** (diffs + contents), not each harness's logs. |
| `probe_oracle.py`, `footprint_adapter.py` | the four-way **filesystem-state probe** (C constraint / E entity / P plan / D progress); the entity component is three-state — `correct`, `wrong` (= *forgetting*: reached the goal but used the wrong artifact), `never_reached` (= *goal-not-reached*: stopped before ever touching the goal). |
| `analyze_matrix.py`, `analyze_stats.py` | completion rate, aptitude `A^90` and unreliability `U = P90 − P10`, dose–response; paired **McNemar** + **BH–FDR**. |
| `scenarios/` | the 10 late-binding-anchor long-horizon tasks. |
| `results/matrix/` | **3998 raw run records** (the data behind every table). |
| `harness_images/` | Dockerfiles + entrypoints for the instrumented agent images. |

## Reproduce

1. **Set your model endpoint + key.** Secrets are redacted as `YOUR_ARK_API_KEY` / `YOUR_ARK_API_KEY_2` / `YOUR_BARK_KEY`; edit `UPSTREAM`/`ARK_KEYS` in `ctx_compress*_proxy.py` (and the Bark URL in the runners) to your own.
2. **Launch the compression proxies:** `bash start_ctx_proxies.sh`.
3. **Run the matrix:** `python matrix_runner.py` (`python matrix_runner.py smoke` for a quick check).
4. **Analyze:** `python analyze_matrix.py` and `python analyze_stats.py`.

Requires the harness runner and the agent docker images; the `ICSE` / `SRC` paths at the top of `matrix_runner.py` must point at your checkout.

## Key result

Fixed model (DeepSeek-V4-Flash), flip only the model-boundary compression operator κ_θ: of the **6 harnesses** with a valid baseline (NoOp completion ≥ 30%), **5 drop sharply** under aggressive compression — e.g. OpenHands 89% → 0% (paired McNemar, BH–FDR `q < 1e-7`) — while **Aider is unaffected**. The effect is robust to a 4× iteration budget, is dose-responsive in compression strength, and its magnitude varies by harness. So under a fixed model, **context compression is a causal driver of long-task degradation, with a large effect in most harnesses**: degradation cannot be attributed to model capability alone, and compression is a controllable cause. The observed degradation is mostly *goal-not-reached*. Single model — the model's own role and any model×harness interaction are not excluded.

## Note

API keys and push tokens have been redacted from this public copy. Set your own before running.
