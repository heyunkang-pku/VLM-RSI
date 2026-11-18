# pilot-v1：Gate A 可执行合约与未来集成边界

这是新独立 git 仓库，不修改或 import EvoVid/Video-Zero 旧工程。CPU 内核无第三方依赖；可选 jsonschema 检查依赖单独固定。`adapters.py` 只有 Protocol 和明确拒绝启动的函数，没有隐藏的 GPU 入口。

## 1. 图 Schema

四份 Draft2020-12 JSON Schema 在 `schemas/`。`core.validate_graph()` 追加引用、时钟、依赖闭包、全局ID、循环等跨字段约束；外部 JSON 必须**同时**经过 JSON Schema 和语义校验，不能认为 JSON Schema 能判断视觉真假。示例只在 `tests/fixtures/SYNTHETIC…` 对应的合成测试文件，不是实际视频结果。

- `video`：video_id/source_video_id/path/hash/source/split/license_status、容器 duration、有理 avg_fps/time_base/start_pts。每帧保存原始整数 PTS、精确转换后的秒、内容hash和文件引用；VFR 按 PTS，不按 `index/fps`。duration 不等于最后一帧PTS，二者都保留。
- `clips`：场景区间、frameIDs、split_method。每帧必须在所属clip及其frame列表中。场景检测器未实现；clip实际归属不可捏造。
- `facts` 统一存放六种全局可寻址事实：object、attribute、relation（FSG）；event、motion、identity（TSG/STSG）。object 有 static/dynamic/unknown；attribute 有 subject 与 attribute_value；relation 有 subject/object；motion有主体、谓词和区间；identity 有两个局部实体端点、显式 known/unknown。所有 facts 都有支持帧、clip集合、parserrun、频率采样来源和额外 depends_on。
- identity 同clip表示跨帧关联，多clip表示 reference edge；不是另开一个没有factID的隐式边。即使原始图宣称 known，B2也必须核验该fact。
- 时间区间为 `start_sec_range=[earliest,latest]`、`end_sec_range=[earliest,latest]`。严格先后只在 `A.latest_end < B.earliest_start` 或反方向成立时可答；重叠、接触、未知身份均弃答。反向输出 no 代表明确 B 在 A 前，不用“没有 A”推出 no。
- 图中没有的对象／事件保持 open-world：无 COUNT/NOT_EXISTS/CAUSE；不存在全视频覆盖证明，不生成全局否定标签。

`required_fact_ids` = 两事件＋显式身份fact＋全部 subject/object/depends_on 的传递闭包。不能调用者只提供一个方便的子集。跨 clip 合成测试读取 event/motion、identity 和两个实体共5facts；这证明内核行为，不证明真实桥接识别有效。

## 2. 候选冻结与三路输出

`candidates.generate_candidates(raw_graph, seed, cap)` 只接受 raw graph 与固定超参数，枚举有身份端点支持的事件对及 BEFORE/WHICH_FIRST，拒绝文字无法区分的同名事件，按 seed+program digest 固定排序后取最多5题。保存结构候选数、预声明cap损耗、拒绝原因和整个问题集 hash。程序执行是否有答案、B2是否接受、B0是否正确，均不作为选题条件。

`freeze_question` 从固定模板产生文本、答案类型、AST、依赖、模型输入图hash、程序hash、seed、模板版本、跨clip标记、逻辑hop及question_id，再冻结整行hash。模板逻辑为「身份关联＋严格时间比较」2步；事实读取数量另存，**逻辑2步不等于真实模型困难**。未实现独立1-hop或3-hop模板，不会报告这些桶的测量值。暂不做含义未明确的 TWO_HOP_RELATION，符合只做2–3种模板的要求。

`execute(g,q)` 先复核所有hash和完整依赖，再执行纯函数。B2 必须同一图hash＋逐fact ledger全部yes且频率达阈值；missing/no/uncertain/过期/非法ledger → ABSTAIN；不能更换图、重写题、修补事实。已读facts及比较过程写入 trace。修改原图任何字段都会使旧题和ledger失效。没有 LLM fallback。

B0 K8严格多数，合法答案归一（yes/true、选项符号）不接收任何B1答案参数；投票分母固定8，格式非法保留并计数；4:4、2valid+6invalid都弃答。输出保留原8条文本及标准化结果，vote_label弃答时为null，vote_fraction记录最高票占8比例。K8与更短输出上限是本试验设计，不能包装成官方greedy评测。

B0 payload只含视频帧/PTS、题目、答案类型、格式提示。Checker payload只含单个事实、必要指代描述、该事实支持帧和时间范围，无候选问题、AST、程序答案和gold。它核验的是原子视觉断言，不是「B1答案是否正确」。未来接口也须保存未截断原回复，严格yes/no/uncertain格式解析，非法回复记uncertain，不能 substring('yes') 放行。

`not_run_rows()` 仅提供输出合约：同题ID三种方法、NOT_RUN与ABSTAIN分开。Gate A 未把它写成真实 predictions 文件，未生成真实raw/verified图。

## 3. 频率与核验记录

每个 parser_run 固定 revision、prompt hash、seed、实际看到的frameIDs与 sample_group。频率 = 同证据组中支持同事实的唯一解析run数 / 该组总解析run数，不是事实在多少帧出现。重复runID、不同证据帧不可混算。保留原解析文本与实体对应表的持久化**尚未实现**；Gate B需实现保守实体对齐及精确事实签名归并，不能由自己填写相同ID假造频率。

ledger 与 raw graph 分开存储：factID、facthash、rawgraphhash、frequency与匹配规则、checker revision/run、看到的帧、原始回复、verdict、原因、token/GPU秒、independence=none。ledger接受不是独立gold。事实可共享核验以降低成本，但所有实际读取的节点与边必须有完整记录。

当前frequency与ledger的CPU数学/检查器 implemented；**四次真实解析、节点归并、运动识别、真实视觉核验均未运行也未实现运行适配器**。主组拟同一个冻结 Base4B，避免给B2换更强模型；其系统误差相关必须报告。

## 4. Gate B 数据流（待批准及实现）

1. 从媒体元数据抽取并冻结视频名单/源组/许可状态；随机种子20261030。同源分组与场景计数分层只能在无模型答题输出时制定；失败视频不换，输出损耗。
2. CPU PySceneDetect＋有界解码，最多共享32帧；保留实际PTS/hash，统一可见信息。场景聚类用均匀PTS近似，丢弃场景记录；不能将没看见当没发生。
3. 每clip固定4次联合JSON解析，最多4clip；相邻clip对最多4次桥接采样。第一结构有效原样本确定raw事实，不使用Checker挑更好的图。生成链需在整图一致ID下确定性装配；超64facts拒绝该图，不截掉程序依赖以凑题。
4. raw-only题集先冻结，再独立运行B0和B2。所有角色使用同一媒体帧集合上限；Parser/Checker允许只读其中子集；额外私有帧禁止。同一事实反复看同一帧计入成本。
5. 适配已有Qwen视频张量/processor协议，显式给出真实PTS，记录任何模型内部平均fps时钟差异。`sample_pts` 是可测CPU时间采样策略，**不声称与官方index均匀抽帧相同**；真实输入一致性在Gate B验证。
6. 每次模型调用必须记 `role/video_id/source_video_id/fact_id或qid/model_revision/prompt_hash/frame hashes/PTS/seed/request_id/start/end/input/output tokens/latency/GPU ID/peak VRAM/status`，包括失败、拒绝、冷启动。共享Parser开销分摊与各方法边际成本都报告。CPU worker上限2，不保留全视频RGB；内存软限16GiB；每卡先单进程，实测显存后再提并发。
7. 真正blind gold仅进入 reviews 与指标分析路径；不作Parser输入、训练目标或阈值选择。gold接口与模型接口无数据传递；schema阻止误传label字段，但不能替代运行时数据流审计。低confidence/ambiguous不硬填答案。

## 5. 指标与结论边界

N为所有锁定候选；coverage=accepted/N。未完成推理不报0%覆盖，返回NOT_RUN/INCOMPLETE与null。Precision分母只取 accepted且独立有效 high/medium gold；列出缺失、低confidence及无效状态。missing gold不当错，也不把已观察正确数当全体 Correct Yield。完整审核时可报合格gold中的正确标签产量；部分分层审核需要设计权重，当前简单统计器明确只给 unweighted reviewed-subset precision，不冒充母体估计。

程序骨架不实现最终 bootstrap / 逆概率估计或 Precision–Coverage绘图。Gate D再实现：同一审核样本、共同可达到coverage范围、预定阈值网格；按 source_video_id 聚类区间。独立seed的额外8rollouts提供 hardness，0–4/8正确预设为hard；需要独立gold，不把hop或低投票稳定性当真困难。不得按gold选择阈值或题集。

没有真实视频标签、独立gold和实测成本，因此现在不能作科学GO/NO-GO。此原型只使之后的比较可审计、可拒答。
