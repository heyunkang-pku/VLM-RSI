# 归档评分结果

此目录保存 2026-11-18 交接时对原 v2 完整数据 ZIP 的复算结果。输入是 26 道冻结题和 `annotator1` 审核表；报告不是多审核者裁决或留出测试成绩。

- [V2_SINGLE_REVIEW_SUMMARY.json](V2_SINGLE_REVIEW_SUMMARY.json)：分母、计数和输入 ZIP/审核表哈希。
- [V2_REVIEW_JOINED.csv](V2_REVIEW_JOINED.csv)：按稳定 `review_id` 对齐的逐题答案、可答性及票型。

可评分定义：审核者给出合法选项，且 `answerable_on_public32=yes`、`unique_answer=yes`。17 题满足条件，其中 16 题两边都给出答案。共同题：都对 7、仅图对 1、仅多数票对 3、都错 5。

原 [模型侧报告](../reports/STEP_EVENT_MCQ_V2_REPORT.md) 写“等待独立答案”，对应当时的交付状态；本目录记录之后收回的一份单人审核，不覆盖历史报告。

新运行默认写入 `runs/v2-review/`，保持本目录归档不变。默认目录输入仅核查仓库内的题目和冻结投票统计，raw_samples_verified=false；使用完整 ZIP 才能逐条核查原始采样，raw_samples_verified=true；再加 `--verify-frames` 会新增 `verified_frame_hashes=320`。目录输入没有 ZIP 哈希，输出的 `data_sha256` 为 null，逐文件哈希保存在 `input_sha256`。
