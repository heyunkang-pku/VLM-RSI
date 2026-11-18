# 当前有效规范

本分支当前入口与分组见 [STEP_CURRENT_ENTRY.md](STEP_CURRENT_ENTRY.md) 及 `config/step_next.json`。B1=STEP核验后G_step程序答案；B2=同图同题追加VQS核验；无G_raw、无GPU总时长预算门槛。下方为旧阶段的历史工程说明，不是当前生效实验定义。

---

# Gate B: five-video STEP-style STSG feasibility study

Independent inference-only baseline. Original EvoVid/Video-Zero engineering is not present on this new baseline branch and is not imported or edited. Approved Gate A source: `797fc6ae6b201a83c40aa139083fbcf1a69aae31`.

Fixed run contract: `bash scripts/run.sh`. Frozen inputs: `config/frozen_videos.json`; actual active settings: `config/gate_b.json`. `config/experiment.json` retains the Gate A proposal for provenance and is not the runtime config.

Pipeline: bounded PyAV + PySceneDetect → shared cached frames → four parses per clip → first structurally valid raw sample → conservative exact fact matching → deterministic raw-only candidate universe → global freeze barrier → K8 B0 / deterministic B1 / B2 Selective Verification. Shared tracked nodes need no redundant identity edge, but their object-track claim must span both events and be visually checked for SAME physical identity. Distinct nodes still require an explicit verified identity fact.

B2 only accepts an existing B1 answer or abstains. B1-Random and B1-Frequency select from unchanged B1 labels at the exact B2 accepted count with zero model calls. No independent gold exists; precision/correct yield remain null.

CPU tests: `python -m unittest discover -s tests -v`; optional JSON Schema checks require jsonschema4.25.1. Recorded local Gate B tests use an isolated environment; runtime tests run before any model load.

Budget: exactly five frozen Perception Test train videos, at most2 A40s ×4h=8GPUh, at most10GiB new outputs, no weights/video downloads, no training/reward changes, no30-video expansion. A one-request decode/encode/model preflight precedes full workflow. Every failure, truncated response and unexecuted question is retained.

A new venv imports existing compatible third-party packages via a read-only `.pth` path, then installs only additional pinned utilities into the new venv. The original environment is not modified; this is read-only dependency reuse, not a claim of fully independent wheel installation. Actual package versions and checkpoint config fingerprints are logged. All model operations are offline.

Durable run output: `/scratch/haozhe/.cache/vlm-rsi/stsg-gate-b/<run_id>/`; mirrored into project artifacts after completion. Per-video raw graphs, losses, locked questions, B0/B1/B2 rows and checker ledgers remain separately traceable. Runtime allocation time, model-device request wall seconds, token counts and peak CUDA memory are reported as distinct cost measurements.

## Purpose-separated parser variant

The frozen parent protocol completed20 parses but generated zero candidate questions. This child preserves that negative result and the exact five media files/144 cached observations. It tests STEP-style purpose-separated FSG parsing and temporal-event parsing (K4 per evidence group) with compact explicit ALL visibility claims and actual-PTS frame boundaries. The artificial per-array3/4 admission limits are removed; the hard total64fact budget remains. No selected question is rewritten based on verification: each variant has its own explicitly versioned raw graph and pre-evaluation locked cohort. This is engineering interface hardening, not a new label-supervision algorithm.

Prior GPU allocations0.396524GPUh are included; this child has at most13680s on2cards, keeping aggregate under8GPUh. Cache-only CPU FSG admission replay and67 CPU tests pass before launch.

## Final cached-FSG temporal-window variant

The purpose-separated parent produced3 real FSG graphs but no selected event pairs. This final engineering variant preserves the parent, reuses all20 of its FSG replies, and normalizes a scalar field only when it is an EXACT known frame ID. A real-cache CPU replay validates cached FSGs for4 of the same5 videos; the remaining video is retained as failure, not replaced.

Local event parsing uses4 fixed disjoint windows over the same observations, K4 per window. These windows are not scene cuts and do not claim real cross-clip bridging. Parser-run groups preserve window evidence sets; frequencies never count occurrences across windows. Shared global object-track claims remain mandatory B2 identity dependencies. The first structurally valid event parse per window is retained even if empty; no graph selection from B0/Checker/gold.

70 CPU tests passed, including cache replay, shared-track identity, actual-PTS ranges and unchanged B1 labels. Previous allocations0.698147GPUh are included; this final run has at most13133s on2cards, keeping total below8GPUh. No further automatic parser variant or video expansion follows.
