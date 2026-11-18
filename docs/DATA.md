# 数据获取与文件角色

## 克隆后即可使用

`baseline/v2/` 已包含 26 道冻结题、原投票统计、对照表、质量标记和帧清单。`annotations/` 包含一位审核者的原表。

```bash
python3 scripts/score_v2.py
```

这一步核对题号、冻结票型、严格多数阈值和审核统计，不读取原始请求日志或视频画面。输出 `raw_samples_verified=false`，260 个采样槽位是按冻结对照表的每题固定 10 槽汇总；不声称已逐条检查原始采样。

## 视觉复核需要另行取得的附件

截至 2026-11-18 本次仓库检查，GitHub Releases 尚无数据附件。请向项目维护者获取以下两个原始 ZIP，放入仓库根目录的 `artifacts/`；后续也可由维护者上传到 [仓库 Releases](https://github.com/heyunkang-pku/VLM-RSI/releases)。

| 文件 | 大小（字节） | 用途 |
|---|---:|---|
| `STEP_EVENT_MCQ_V2_DATA.zip` | 30,989,945 | 原图、320 张公共帧、图证据、原始调用、投票与源码 |
| `STEP_EVENT_MCQ_V2_BLIND_REVIEW.zip` | 20,123,471 | 无答案离线审核页面与配套内容 |

SHA256：

```text
57281a22f82d3134d2c2dc14dfe0a91e3b43831c0778a741753fafa43995504e  STEP_EVENT_MCQ_V2_DATA.zip
b3e7769ef9398c99b33962f60bb2efe673eb8950f58d95ebf37cd75f01e20fba  STEP_EVENT_MCQ_V2_BLIND_REVIEW.zip
```

取得完整数据后，可逐条核对 260 次原始采样并校验画面：

```bash
python3 scripts/score_v2.py --data artifacts/STEP_EVENT_MCQ_V2_DATA.zip --verify-frames
```

脚本也接受已解压数据目录：`--data /path/to/extracted_v2`。数据目录内应直接含 `QA_FROZEN.jsonl`、`COMPARISON.jsonl`；若含 `VOTES.jsonl` 则同时逐条校验原始采样。校验帧还需原 manifest 和 `frames/`。

## 各文件的证据角色

- `QA_FROZEN.jsonl`：题面、选项、图标签和来源引用，标签仍是未核验伪标签。
- 完整 ZIP 的 `VOTES.jsonl`：原始采样槽位、响应和输入指纹；未新增到公开 Git 文件中，不是独立参考答案。
- `COMPARISON.jsonl`：按原解析规则得到的冻结投票对照。
- `annotations/`：单人审核参考，歧义题仍需复核。
- 完整 ZIP 的 `source_graphs/`：图事实及 registry；`completed/formal/` 包含实际 Questioner 输入与生成记录。
- 完整 ZIP 的 `frames/`：当时 Solver 实际可见的 32 帧/视频。原始 MP4 和模型权重不在其中。

独立审核者只接收无答案盲审 ZIP；含图标签和投票的完整包用于研究分析。

## 来源索引

[ARTIFACT_INDEX.csv](ARTIFACT_INDEX.csv) 与 [SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json) 记录原交接文件的名称、用途、相对路径及校验值。`in_git` 表示当前是否随仓库提供；`included` 对应原交接包的收录状态。被 Git 忽略的完整附件须向维护者获取，或在其发布 Release 后下载。
