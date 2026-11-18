# STEP S1 / 单关键帧 S2：固定重实现假设与授权范围

用户2026-10-31批准paper-faithful reproduction的S1及有条件单帧S2；非核心未公开参数可固定并明确记录，不要求先找到全部作者原值。核心图算法不替换。

1. **范围**：只冻结清单首个video_7793（不根据旧预测结果选择），S1/S2均不扩至五段。新帧版本独立于旧GateB。
2. **Visual Splitting**：STEP正文§3.1先PySceneDetect。采用已安装0.6.7的ContentDetector，threshold27、min_scene_len15，输入按所有源帧依序缩到320×180。参数为固定工程选择，非作者原配置；优先CPU、保留源PTS。
3. **关键帧算法**：采用STEP所引Song等2016论文[42]§3.2的Keyframe Extraction，而不是任意均匀抽帧或新视觉编码器聚类。两层空间金字塔5区域、HSV各通道128bin、边缘方向/幅值各30bin，总2220维。特征实现移植Hecate hist_opencv.hpp固定63d1c91，使用Scharr、方向mod180、HSV/幅值0–256、每直方图L2归一，保留其空间区域顺序。
4. **聚类/子片段**：[42]§3.2给k为shot数；将STEP先行PySceneDetect的clip数用作shot数，整段视频特征kmeans后在每clip按连续cluster ID分subshot。固定seed20261031、kmeans++10次、最多100轮、epsilon1e-4。这些数值非作者STEP配置。单clip可能k=1，只保留真实退化，不为凑帧擅改k。
5. **代表帧**：[42]明确最静帧，而非聚类中心最近帧。逐源帧与前帧计算RGB平方差均值（同尺寸下与SSD的排序一致），每subshot取最小值、并列取较早源帧。首帧无前驱记不可比较（不是人为0）。这与Hecate具体双侧L2差值/首末0实现不同，选择paper-level SSD定义，明确记录差异。
6. **引用范围**：不运行[42]§3.3的thumbnail美学排序/随机森林；STEP只说明聚类关键帧，本轮取§3.2。未额外引入其整条低质过滤/内部shot重分割，STEP前置场景检测提供边界；这是明确的引用子流程范围，不声称bit-exact复现整个Hecate。
7. **S2关键帧预选**：按S1选出帧真实PTS升序第一张。模型调用前记录清单和hash，不根据是否出现手/动作或模型产量挑选。
8. **模型**：复用缓存Qwen3-VL-4B-Instruct revision ebb281ec70b05090aa6165b016eac8ec08e71b17，作为原生多轮提示链的backbone adaptation；不声称与论文VideoChat2*/VILA权重一致。不下载/训练新模型。
9. **模态**：叙述、实例区分、属性叙述、关系叙述仅看该关键帧；抽对象名/属性/三元组只看上一步文本；静动态判别按补充A.1实际video输入。静动态video上下文固定源clip内均匀16帧，**只是该分类调用的视频预处理，不是替代S1关键帧算法，也不产生其他帧FSG**。
10. **视觉/解码**：单图max200704像素、video帧max50176像素、factor32、PIL双三次；保存实际重采样PNG及tensor hash；greedy/temperature0、max512新token/调用、最多128调用。为资源选择，非作者原值。发生截断即停止，无额外重试/采样/惩罚调参。
11. **提示与图**：补充A.1提示任务/例子及链路保留；将INST及Image/Video占位符换为Qwen正式chat template，变量填真实叙述/对象。多实例用模型给出的实例名及区分属性指代。关系按补充每主体对其他对象分组叙述，再文本抽三元组。单帧对象节点、属性节点/属性连接、关系边独立表示；不引用旧Event/FSG schema。
12. **机械适配**：只读取明确文本/列表/伪JSON字段；保留重复属性键，解析失败记问题，不补事实。关系源/目标仅在已有节点有唯一文本匹配时连边；不识别同义词、不强配同描述实例，未解析/歧义claim原样保留。内部ID仅为溯源，不证明跨帧身份。
13. **原生核验**：n/频率阈值/事实等价及全类型视觉check政策未单独批准，故本轮NOT_RUN，实际check调用0。保存不变的precheck单帧FSG；postcheck只为NOT_EXECUTED描述符，verified_graph=null。**不伪造G_raw/G_step，不延后/关闭核验后继续Dynamic Merging**；本轮根本不进入S3。
14. **硬预算**：CPU S1上限规划1800s；S2单A40 worker890s+最多10s终止宽限，总GPU不超过900s=0.25GPUh。超时/截断/关键解析阻塞保留全部已获得证据并停止，不扩大次数/视频。
15. **不运行**：训练、Reward、原生QA、程序QA、B0–B4、S3–S6、五视频扩展。B2定义继续VQS-style question-conditioned atomic fact verification，不与STEP原生核验混用。

论文/补充的固定正文与源文件见reference_sources和已审计Gate0来源目录。新实现没有调用旧Event Parser，旧引擎仅复用generic runtime/hash/save/断言工具；所有旧代码与历史结果保持冻结。
