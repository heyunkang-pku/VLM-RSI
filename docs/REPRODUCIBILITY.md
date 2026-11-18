# 复现说明

## 1. 克隆后的 CPU 评分

Python 3.9+，仅标准库：

```bash
python3 scripts/score_v2.py
```

默认读取仓库内 `baseline/v2/` 的冻结题目和原投票对照表，与 `annotations/` 的原审核 CSV 按 review_id 对齐。输出写到被忽略的 `runs/v2-review/`，不覆盖历史 results/。

检查另一份同题审核表时，使用 `--review /path/to/review.csv --output runs/another-review`。脚本要求 26 个题号一一对应，检查冻结表每题分母为 10、票数合法及至少 6/10 的严格多数，不恢复裸字母失败响应。基础模式仅复算已有票型，标记 raw_samples_verified=false；逐条原始响应检查需完整 ZIP。

## 2. 完整 ZIP 与帧校验

原图、模型请求与 320 张帧需要获取 [完整数据附件](DATA.md)：

```bash
python3 scripts/score_v2.py --data artifacts/STEP_EVENT_MCQ_V2_DATA.zip --verify-frames
```

`--data` 也接受原包已解压目录。完整数据包含 VOTES.jsonl，脚本会先核对原始采样和冻结票型，标记 raw_samples_verified=true。只有这一路径能校验画面文件哈希；轻量仓库没有 frames/，单独加 --verify-frames 会得到获取附件的提示。

输出 input_sha256 标明实际读取文件的哈希。data_sha256 仅在输入为 ZIP 时填写；目录输入为 null，不假装已经验证原始压缩包。

## 3. 历史模型推理环境仍需迁移

legacy_src/scripts/run.sh 硬编码原 Python、依赖和缓存根目录，实际派发 four_group.event_mcq_v2。旧 STEP_CURRENT_ENTRY.md 的派发描述滞后，应以脚本及当次协议为准。

four_group/event_mcq.py、shared32.py 的 BASE 和配置中的原路径需定位并参数化。原运行器还依赖 ORX 环境变量、原媒体与模型缓存。请在新分支适配，保留历史快照以便追溯。

原快照报告 197 项 CPU 测试通过，这是历史记录；本次仓库整理未重跑旧 GPU 环境或声称新机器已能完整推理。

原环境定位线索（本次未访问服务器）：

- v2 根：`/scratch/haozhe/.cache/vlm-rsi/event-mcq-v2/673f0671-2c37-4873-a14b-90029a147d33`
- 公共帧/图根：`/scratch/haozhe/.cache/vlm-rsi/public32/2e2321e3-316b-447d-ad3f-57b47dfdaf22`
- Python 线索：`/scratch/haozhe/miniconda3/envs/llava/bin/python`

这些是历史服务器路径，不是可保证存在的下载地址。模型 revision 和采样配置见 HANDOFF 与完整原包 completed/effective_config.json。

## 4. 原材料边界

本仓库没有原始 MP4、模型权重、完整训练工程或完整 Python 环境。完整 v2 ZIP 有原 320 PNG；manifest 的 file 字段保留历史绝对路径，relative_path 用于在 ZIP 内解析。

source_graphs/ 保存完整 partial 图；completed/graph_inputs/ 保存图视图，formal/*/*/ACTUAL_GRAPH_VIEW.json 对应实际文字输入。v2 仅用 clip_observations 与 Motion 的文字投影出题，不能把完整图的其他结构视为已被使用。

reports/ 保留当次结论；results/README.md 说明后收回单人审核的状态。docs/history/HANDOFF_PACKAGE_VALIDATION.json 是 GitHub 建仓前的原交接包校验记录，不描述当前仓库是否已发布。
