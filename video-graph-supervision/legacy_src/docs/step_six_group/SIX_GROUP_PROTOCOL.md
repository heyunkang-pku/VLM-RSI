# Three-video STEP × VQS six-group engineering pilot

Scope: same frozen3 videos/40 STEP S1 keyframes; no new download, decoding, video selection, training, weights, reward, G_raw, or human prerequisites. All graph/QA versions preserved. Run entry `bash scripts/run.sh`, module `step_six.runner`, effective configuration `config/step_six.json`.

## Method sources and reconstruction boundaries

- STEP CVPR2025 main §3.1/3.2 and Supplement A.1/A.2 are method authority. Existing native multi-round FSG, sampled frequency/native visual checks, static merge/Motion/Reference retained. Original V0/V1 untouched.
- Clip Event descriptions: native clip holistic description, no whole-video Event JSON replacement. Boundary-anchor edge topology and prompt wording are undisclosed; explicitly reconstructed. Clip bounds are observations, never inferred precise action boundaries. Graph stays PARTIAL.
- S sampling follows main Q/A-frontier connected-pair initialization and expansion, max3 expansions; four preplanned trials/video, fixed seed. No solver feedback. The initial graph-to-QRA wording/template and tie-breaking are undisclosed assumptions. A text-only graph-path QRA call renders the explicit subquestion/answer path, followed by exact Supplement A.2 refinement prompt. Freeze only after refinement, including any native answer change.
- P adapter is OUR deterministic program interface, NOT STEP native generation. Same graph. Enumerate all attribute/relation/identity/motion diagnostic programs; preserve every abstention. Fixed8/type cap ordered by predeclared hash, never solver outcome. Motion requiring unresolved grounding abstains.
- Reuse prior common video input manifest: deterministic chronological ranks of ALREADY frozen source images, max32. No source frames sampled again. Keyframe/image vs video resolution and original input provenance retained. S0/P0 input is video+question ONLY.

## Six groups

S0/P0 use official Video-Zero v4 snapshot9b5f72f0afab975893cec22fcbff9e8619a2851f/v4. The10 pseudo-label rollouts and2048 output cap are documented in Video-Zero Appendix C.3. Temperature.7/top_p.9, fixed seeds, open-answer JSON wrapper and exact NFKC/lower/space/punctuation normalization are adaptation assumptions. Strict majority>5 of10 is a conservative adaptation, not paper argmax. All raw draws, invalid/truncated outputs, ties, failed denominators and abstentions retained. No semantic clustering of synonyms.

S1/P1 are immutable post-refinement / post-execution answers. S2/P2 only accept or abstain; candidate answers/graph never rewritten. Extra VQS ledgers are separate from native STEP construction verification.

## VQS video adaptation and completeness

Official VQS image code inspires program read-trace→atomic fact checks and all-YES acceptance (greedy4 token checker). This video adapter additionally checks time, identity, motion and referent resolution. No empty-claims passthrough.

P2 records the complete program value/parent/connection dependencies and scope-object lookup universe, including source semantic hashes and exact operations. Partial-graph uniqueness gets explicit visual checks instead of closed-world assumptions. S2 considers all question, answer, rationale, complete graph path and parent closure. A dependency compiler atomizes all compound claims, maps each to graph provenance and flags unmapped requirements. A separate full-question coverage audit checks referents/relations/identity/time, not only mentioned entities. Missing dependency/type/empty atoms/compiler failure→UNRESOLVED, never a guessed answer. Completeness is model-assisted evidence, not a logical proof or human truth.

Static atoms checked at the actual frozen source keyframe, temporal/identity atoms with the common frozen video and authoritative times. All atomic replies, model revisions, visual tensor hashes and cached reuse retained. Holistic event/motion facts with unresolved grounding cannot be accepted as precise action evidence. Every acceptance is a model self-check outcome, NOT an accuracy claim.

## Cost and failures

Request timeout1200s, no total GPU-time threshold. Actual attempted/completed/failed calls, tokens, device seconds and allocation wall time logged. Five cards used only if >40GB free and utilization<5%; never terminate others. Continue other questions on failures; process failures preserved in final state. All frozen file hashes checked after six groups. Human correctness/answerability metrics pending; blind Stage1 separated from sealed anonymous Stage2. Same-question answer agreement is not accuracy.

Primary sources: https://openaccess.thecvf.com/content/CVPR2025/papers/Qiu_STEP_Enhancing_Video-LLMs_Compositional_Reasoning_by_Spatio-Temporal_Graph-guided_Self-Training_CVPR_2025_paper.pdf ; https://openaccess.thecvf.com/content/CVPR2025/supplemental/Qiu_STEP_Enhancing_Video-LLMs_CVPR_2025_supplemental.pdf ; https://github.com/ahmedheakl/VQS/tree/ab15561aac354b26054d582de4561713c6a13273 ; https://arxiv.org/html/2605.14733v1#A3.SS3 ; https://github.com/Zzz99999/Video-Zero

The end-to-end controller can be launched while V2 recovery is in flight. It waits CPU-only for the explicit V2 final state (native verification AND temporal merge), then runs graph-event/QRA preparation and automatically dispatches v4 votes plus VQS checks to free A40 cards. This barrier is a data-integrity dependency, not a human-review prerequisite. Solver normalization and strict-majority rules are fixed before any solver response is read.

## Lossless structured-rationale recovery

The first real QRA initial generation returned R as nested subquestion/answer JSON. String-only input validation rejected it before Supplement A.2 refinement. Preserve this run and its full failed-candidate denominator. A child version accepts nonempty R strings, objects or arrays as rationale; structured R is passed to the same native refinement prompt using its exact raw JSON value span. Duplicate nested member text is preserved in that span rather than silently discarded by a dictionary parser. Duplicate top-level R/Q/A keys or non-string Q/A remain invalid. No initial generation is redrawn, no graph facts or P questions changed. Refine the original cached S generation, freeze afterwards, run only missing vote/VQS work, reuse original P outputs and their provenance. This is an interface correction, not outcome-based question selection.
