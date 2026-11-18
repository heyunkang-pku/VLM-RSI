# 复现范围

## 本次确实执行

- 从当前文件取回 v2 原包、审核 CSV 与报告；核对源码快照。
- 按 review_id 连接并从原始样本重算严格多数与单人审核比较。
- 校验 320 张 PNG 的 SHA256。
- 提供标准库 CPU 评分脚本；没有重跑模型或训练。

## 可以立即重算

```bash
python3 scripts/score_v2.py --verify-frames
```

默认从 artifacts 中的原包读取，不解压、不联网。输出到 results。若检查新审核者，使用 --review 指定文件，保留原结果到独立 --output 目录。

## 尚不能在新机器直接重放模型

legacy_src/scripts/run.sh 硬编码原 Python/只读依赖/缓存根目录，并派发 four_group.event_mcq_v2。
旧 STEP_CURRENT_ENTRY.md 的派发描述滞后；不要用它替代实际 run.sh。
four_group/event_mcq.py 的 BASE、shared32.py 的 BASE，以及配置中的原路径需定位并参数化。
运行器依赖 ORX 环境与原始媒体/模型缓存。应在新分支适配，不篡改归档。
原快照自报 197 项 CPU 测试通过；这是历史报告，本次没有重跑旧环境测试或断言其在新环境也通过。

## 原环境定位线索（本次未访问服务器）

- v2 运行根：`/scratch/haozhe/.cache/vlm-rsi/event-mcq-v2/673f0671-2c37-4873-a14b-90029a147d33`
- 共享公共帧/图根：`/scratch/haozhe/.cache/vlm-rsi/public32/2e2321e3-316b-447d-ad3f-57b47dfdaf22`
- 原依赖线索：`/scratch/haozhe/miniconda3/envs/llava/bin/python`，详见实际 run.sh。
- 模型 revision 和采样配置见 HANDOFF 与原 completed/effective_config.json。

这些路径不是当前机器路径或可保证存在的下载地址。包中没有原始 MP4、权重、完整训练工程或全部 Python 环境；有原 320 PNG 与帧映射。
frame manifest 的 file 字段保留历史绝对路径，relative_path 字段用于在原 ZIP 中解析。

## 图文件与输入

原包 source_graphs/ 保存完整 partial 图；completed/graph_inputs/ 保存图视图，formal/*/*/ACTUAL_GRAPH_VIEW.json 对应本次实际文字输入。
v2 只用 clip_observations 与 Motion 的文字投影出题，不能把完整图的其他结构视为已被利用。
