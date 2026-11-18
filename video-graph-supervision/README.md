# Video Graph Supervision

真实视频时空图 → 有证据的 QA / 伪标签 → 同题多数投票比较 → 训练验证。

**状态（2026-11-18）：已跑通推理与数据交付，尚未证明图标签胜过多数票，尚未训练新方法。**

## 从这里开始

1. 阅读 [合作交接](docs/HANDOFF.md)：目标、历史、真实结果、失败类型、接手任务。
2. 阅读 [最新 v2 报告](reports/STEP_EVENT_MCQ_V2_REPORT.md)。
3. 运行 `python3 scripts/score_v2.py --verify-frames`，离线复算单人审核对比并校验原 320 帧。
4. 阅读 [下一阶段](docs/NEXT_PHASE.md) 与 [复现边界](docs/REPRODUCIBILITY.md)，开始定位错误和改善监督。

## 当前数字

| 项目 | 结果 |
|---|---:|
| 视频 / 原公共帧 | 10 / 320 |
| v2 冻结 QA / Solver 样本 | 26 / 260 |
| 有唯一人工参考答案 | 17/26 |
| 双方作答的共同题 | 16 |
| 共同题图标签正确 | 8/16 |
| 共同题多数票正确 | 10/16 |

以上是开发集、单人审核；48% 的图票一致率不是准确率。

## 内容

- `docs/`：交接、下一阶段、拟议 v3、仓库准备和资产索引。
- `legacy_src/`：原 `SOURCE_20d5065.zip` 的源码快照，保持历史内容；有旧配置与硬编码路径。
- `baseline/v2/`：小型冻结题目、对照、问题质量标记及帧清单。
- `annotations/`：已有一位审核者的原始 CSV。
- `results/`：当前可复算结果。
- `scripts/score_v2.py`：仅标准库，无模型/GPU。
- `artifacts/`：随交接包提供的两个原始 ZIP，默认不进入 Git。

`artifacts/STEP_EVENT_MCQ_V2_DATA.zip` 含图、帧、证据、原始模型调用与票型。
发给独立审核者时，只发 `artifacts/STEP_EVENT_MCQ_V2_BLIND_REVIEW.zip`，以免答案污染。

## GitHub

本目录是仓库初始内容，不是已经创建/推送的 GitHub 仓库。按 [REPO_SETUP.md](docs/REPO_SETUP.md) 操作。
建议先建合作用私有仓库；数据与第三方源码的公开授权另行核对，不为原资产新增许可。
若从 Git 克隆而非接收完整交接包，需要另行取得上述两个 artifacts ZIP，并核对 [来源与哈希](docs/SOURCE_PROVENANCE.json)。

## 当前工作范围

先改善建图与出题，独立验证质量/覆盖，再尝试训练。教师 harness 路由与可学习增量不属于本次必须实现范围。
