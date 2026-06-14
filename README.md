# Observability-Collapse Differential (OcDiff)

Artifact (code + data) for the paper *"长任务退化是模型通病还是 harness 之过？一个把上下文管理策略当可控算子的差分诊断协议"*.

OcDiff treats a coding-agent **harness**'s context-management policy as a *controllable operator* and, by flipping only that operator under a fixed model and task, causally attributes long-task degradation to the harness rather than the model.

## Layout

| Path | What it is |
|---|---|
| `ctx_compress_proxy.py`, `ctx_compress_anthropic_proxy.py` | the model-boundary **uniform compression operator** — reverse proxies that keep `system + first task + last-K` messages and drop the middle (OpenAI `/v1/chat/completions` and Anthropic `/v1/messages` surfaces). `start_ctx_proxies.sh` launches the 8 strength instances (`keep 0/12/6/3` per surface). |
| `matrix_runner.py` | the differential matrix: 8 harnesses × {FULL, keep0, keep12, keep6, keep3} × 10 tasks × N=10, driven through the ICSE harness runner. |
| `scoring.py` | harness-agnostic **ground-truth** scorer — reads the kept sandbox filesystem instead of each harness's logs. |
| `probe_oracle.py`, `footprint_adapter.py` | the four-way OS-footprint probe (C constraint / E entity / P plan / D progress); entity is three-state (`correct` / `wrong` / `never_reached`). |
| `analyze_matrix.py`, `analyze_stats.py` | completion rate, aptitude `A^90` and unreliability `U=P90−P10`, dose-response; paired **McNemar** + **BH–FDR**. |
| `scenarios/` | the 10 late-binding-anchor long-horizon tasks. |
| `results/matrix/` | **3998 raw run records** (the data behind every table). |
| `harness_images/` | Dockerfiles + entrypoints for the OCD-instrumented agent images. |

## Reproduce

1. **Set your model endpoint + key.** Secrets are redacted as `YOUR_ARK_API_KEY` / `YOUR_ARK_API_KEY_2` / `YOUR_BARK_KEY`; edit `UPSTREAM`/`ARK_KEYS` in `ctx_compress*_proxy.py` (and the Bark URL in the runners) to your own.
2. **Launch the compression proxies:** `bash start_ctx_proxies.sh`.
3. **Run the matrix:** `python matrix_runner.py` (`python matrix_runner.py smoke` for a quick check).
4. **Analyze:** `python analyze_matrix.py` and `python analyze_stats.py`.

Requires the ICSE harness runner and the agent docker images (`emnlp/*`); the `ICSE` / `SRC` paths at the top of `matrix_runner.py` must point at your checkout.

## Key result

Fixed model (DeepSeek-V4-Flash), flip only the context operator: of 6 harnesses with a valid (>30%) baseline, **5 collapse** under aggressive compression (paired McNemar, BH–FDR `q < 1e-7`) while **aider is immune** — long-task degradation is **harness-dependent, not model-inherent**.

## Note

API keys and push tokens have been redacted from this public copy. Set your own before running.
