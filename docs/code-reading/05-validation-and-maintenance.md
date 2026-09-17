# 05：验证、运行产物与修改影响

> 本文保存在线 Ramulator2 替代实施前的静态分析与方案；当前已实现代码、接口和运行配置见[在线后端说明](../ramulator-integration.md)。

## 1. 一个写请求如何走完

以Host在`shared_buffer+0x14`写四字节、第二字节屏蔽为例：

1. uncacheable映射让访问进入SystemXBar目标range，monitor保存Packet source/mask。
2. Gem5ToTlmBridge64生成payload；Demo conversion hook保存byteEnable与payloadDelay。
3. Master分配活跃ID，将地址拆为对齐4B单拍，发END_REQ，驱动AW(SIZE=2,LEN=0)和W(lane20..23、WSTRB[21]=0)。
4. Fabric把32个lane无损转WChannel；Axi2Flit保存AW路由，W继承RP，编码WriteReq/WriteData。
5. Packer检查该RP请求/数据credit，按5B粒度封包，adapter序列化为250B FDI。
6. UcieLink TX scatter为256B物理帧并加CRC；PHY可能损坏，RX正确按seq交付，否则NAK/replay，重复帧不二次交付。
7. AouTarget按RP将W数据组到对应WriteJob，释放已搬走的数据credit，整笔完成后提交SimpleMemRequest。
8. MemSimBackend抽有效lane为4B data/mask，以`addr-base`提交一个或多个native child；ss_mem_submit满则保留ID重试。
9. 所有child completion到达后返回SimpleMemResponse；target编码WriteResp，经reverse link回到B通道。
10. Master收到B设置TLM status，发BEGIN_RESP；bridge把响应送回原Packet；上游接受后END_RESP释放ID。被屏蔽字节应保留原值。

地址握手、credit释放、link ACK、memory完成、B握手和END_RESP是不同事件。将其中任一个提前当作最终完成会制造错误的延迟或数据可见性。

## 2. 一个NPU读请求如何反馈到RTL

1. RTL外部master完成AR握手，wrapper调用AsyncReadCallback。
2. 库判DDR窗口，对齐16B，issue callback交native ID/addr/size给gem5壳。
3. CoralNPU::issueRead建立sequence与ID退休队列，持久读buffer，发DMA。
4. DMA经主链路得到真实data response，readMemoryComplete只标记该sequence完成。
5. retireReadyReads只退休native ID队首已完成项，调用complete_read，库向wrapper注入AxiRData。
6. 下一NPU tick的真实RVALID/RREADY握手让RTL消费data；期间没有响应则RTL停等，后续计算可被内存延迟改变。

GPU core对应token issue/complete；GPU CP对应coroutine yield/resume。三者采用不同接缝实现同一个“不能提前completion”的原则。

## 3. 验证脚本逐文件职责

位于`gem5_axi/scripts`：

| 文件 | 独立证据与主要检查 | 输出/后继 |
|---|---|---|
| `check.py` | transactions+AXI events+protocol；重建byte scoreboard，burst geometry、WSTRB/lane/LAST/error、ID live区间、时序、drain | check_summary.json |
| `check_axi256.py` | 当前产物确为AXI256而非窄数据、截断或错误canonical信号 | 位宽专项结果 |
| `check_aou.py` | AXI与AoU结构化事件匹配、Flit/响应/重放和顺序 | aou_check_summary.json |
| `inspect_link.py` | 直接从两端raw Flit hex解CRC/physical scatter/AoU消息，关联AXI→帧→对端→返回 | axi_flit_path.csv、link检查与HTML |
| `check_memsim.py` | 将真实AXI/raw Flit path与mem child/DRAM命令/DFI/最终字节连接 | memsim_check.json、memsim_journeys.csv等 |
| `audit_wave.py` | VCD真实五通道握手、字段稳定性与CSV交叉核对 | wave_audit结果 |
| `check_cpu_timing.py` | CPU负载事务、运行退出与基线/延迟契约 | CPU专项验证 |
| `check_aou_negative.py` | 对复制产物制造AoU故障，验证checker能失败 | negative摘要 |
| `check_link_negative.py` | raw Flit/链路证据损坏后校验必须拒绝 | negative摘要 |
| `check_memsim_negative.py` | child/完成/内存证据篡改后校验必须拒绝 | negative摘要 |
| `trace_view.py` | AXI、AoU与事务事件→时间线HTML/data chunks | 全链路访问观察 |
| `memsim_view.py` | memory request/child/command/DFI→HTML/data chunks | 存储侧观察 |
| `view_assets.py` | viewer数据存储、分块与公共资源辅助 | 与view_store.js配合 |
| `view_store.js` | 浏览器按需fetch分块、缓存与索引访问 | 大量产物不一次灌进HTML |
| `report.py`、`summarize_aou.py` | 分用例摘要→汇总报告/表格 | 不取代数据checker |
| `run_tests.sh`、`run_aou_tests.sh`、`run_cpu_timing.sh` | 分层回归调度、独立输出目录 | env统一入口会复用部分 |
| `env.sh`、`setup.sh`、`build.sh`、`patch_gem5.py` | 兼容开发/安装/构建脚本 | 主仓库当前流程以env统一入口和直接维护源码为准 |

脚本有历史兼容分支，精确文件名/输出字段以实际源码为准。不能只看存在某个JSON就认定检查执行并通过，要核对内容与上游输入。

## 4. check_memsim的跨层关联

它依赖先运行inspect_link产生raw帧解码的axi_flit_path。随后重建AXI请求：AW按W FIFO配对，AR按RID匹配各R，得到有效data/mask/returned bytes和forward/reverse frame journey。

将memsim_bridge事件按burst serial分组，submit/complete按mem_id对应，要求无丢失/重复；native命令RD/WR和DFI payload按同ID相连。现有定向套件明确要求每native child对应一个物理RD/WR，不允许把forward/coalesce悄悄当成等价结果。

时序必须满足：

```text
request最后一片UCIe交付
 ≤ backend accept
 ≤ child submit
 ≤ DRAM issued_cycle × period
 ≤ completion_cycle × period
 ≤ bridge收到child completion
 ≤ backend return
 ≤ response最早UCIe发送
 ≤ AXI B/R完成
 ≤ Packet最终响应消费
```

对于payload，检查AXI write bytes=bridge accept/submit=DFI write data，mask在DFI里按其“0允许/255屏蔽”语义转换；读DFI bytes=child complete=bridge return=AXI有效R lanes。最后使用独立写scoreboard核对存储字节。

这能检测“日志看似闭环，但数据实际从另一数组提前返回”的实现错误；它比只比较某个completion总数强。

## 5. 内存变慢如何证明有反馈

CPU/simple对照改变target latency，核对同指令/同访问序列，较慢每笔访问完成更迟；单outstanding测试CPU退出delta可与访问等待delta总和比较。

在线CPU对照改变memsim scale；XPU对照three/three_slow使native period×4，验证Host退出更晚、NPU/GPU执行cycle增加、设备roundtrip平均延迟增加，并核对计算结果不变。

GPU/NPU原始core访问计数可比较；Host/CP polling数可能变化，这是反馈改变执行流的合理结果，不能强制全trace条数恒等。旧离线重放则请求流固定，不适合用同样方法证明应用completion反馈。

verify_xpu要求NPU 64读+64写，统一NPU transactions=128；这个数字属于ddr_touch负载，不是NPU通用性能/容量规格。

## 6. 必须保留的观察产物

| 产物 | 观察层 | 用途 |
|---|---|---|
| `run.log`、`stats.txt`、`config.json` | 配置/应用/框架 | 确认退出、参数、指令与设备统计 |
| `transactions.csv` | TLM parent | begin/accepted/axi_done/end_resp与metadata |
| `packet_lifecycle.csv` | directed tester | 原Packet重试/接受/最终响应 |
| `axi_events.csv`、`axi_wave.vcd` | 真实AXI五通道 | 握手、WSTRB/lane、反压稳定与最后边沿 |
| `aou_events.csv`、`aou_summary.json` | AoU结构化边界 | 与宽数据转换/请求响应核对 |
| `ucie_flits.csv`、`ucie_soc.csv`、`ucie_mem.csv` | 两端FDI/physical Frame | 带时间戳完整hex、attempt、replay、seq与交付 |
| `axi_flit_path.csv` | 离线raw帧解码关联 | 业务消息到底穿过了哪些帧 |
| `memsim_bridge.csv`、`memsim_bridge_summary.json` | 在线burst/child桥 | submit反压、native完成、response保持 |
| `memsim_config/core/commands/dfi*` | 后端要求的产物 | 实际DRAM/DFI服务与字节；当前源码缺失，不能生成 |
| `hettrace/*.hettrace`、meta、validation.txt | Packet合成观察 | 分源字节、事务、时间、活动重叠 |
| 各viewer HTML、`*_data`、`view_store.js` | 浏览器观察 | 按需加载、交接查看 |
| environment manifest与测试摘要 | 复现 | 固定来源/工具/产物与实际通过证据 |

HETTrace不含真实数据，不能替代AXI/VCD/完整Flit日志。HTML需要复制整个case目录及data/公共脚本，推荐通过本地HTTP查看，file路径可能不能fetch分块。

## 7. 静态检查发现的能力边界

| 事项 | 当前源码证据 | 解读结论 |
|---|---|---|
| 完整在线构建 | check_sources/build/SConscript要求mem_sim | 当前缺源，不能完整构建/运行 |
| Vortex来源 | 锁文件与未初始化gitlink | 当前只能解读系统壳/patch，GPU全树不可读 |
| 旧文档open-loop | gem5_new旧het_system/build_memories | 仍保留离线方案，与在线run_xpu区别 |
| 1ps/1fs | addrmap默认1ps；run_xpu设1fs；monitor换算 | 用实际header/配置频率，不能机械套注释 |
| 原始NPU宽度 | timing seam固定16B | 统一AXI256由Master转换产生 |
| HETTrace宽度 | default projection16B；AXI DataBits256 | 记录层与真实signal层不能混称 |
| 设备source→RP | Fabric qos=id%planes | 资源平面是当前测试策略，不是设备一源一plane |
| 元数据线上保真 | RequestAttributes保存在CSV；FDI metadata侧带 | 不能把所有requestor/token当作实际物理帧字段 |
| functional/atomic/DMI | AoU access拒绝；DMI false | 不支持通用功能旁路和atomic |
| checkpoint/缓存一致性 | 缺在线状态序列化/一致性契约；共享uncached | 不宣称支持 |
| reset与restart | target hot reset拒绝；NPU started_不清 | 非通用热复位，NPU每仿真一次启动 |
| NPU start | .cc enqueueWriteWord三阶段 | 当前非阻塞实现，部分头注释滞后 |
| 完整错误传播 | Master映TLM/Packet；NPU complete固定RESP0 | CPU/tester可验error，XPU错误码传播能力有限 |
| 性能真实性 | GPU SimX、behavioral UCIe、后端provisional HBM | 适用于建模/对照，非所有硅片时序的校准真值 |
| LLM负载 | 生成合成访存形状 | 不是完整模型数值计算 |

这些是当前实现和证据范围，不是对历史验收的否定。本次没有修改功能源或宣称修复它们。

## 8. 修改某一项会影响哪些代码

| 目标修改 | 需要联动的文件/层 | 必要验证 |
|---|---|---|
| 统一AXI数据宽 | axi_signals、axi_if/aou_types、message长度/credit预算、Fabric static_assert/lane、mem backends、trace/checker | 窄/full/partial/跨界、golden、wave与真实字节 |
| AoU message格式 | MsgBuilder/Decoder、aou_types、stream decoder、packer/unpacker/target、inspect_link | 固定golden vectors+双向解码+negative |
| 物理scatter布局 | protocol公共头、UCIe CRC/build/check、raw解码工具 | 独立offset/CRC向量、两端250↔256往返 |
| lane/rate/NRZ/PAM4 | link_config、make/require_aou_config、capacity预算、PHY、测试pacing | config mismatch拒绝、利用率、误码/重放 |
| 活跃ID或RP | wire mask、Master maxId/slots、order guard、target ticket、credit matrix、checker | 回绕、同ID顺序、跨RP违规、response hold |
| 共享/BAR地址 | addrmap.json与生成物、het_system常量、run_xpu ranges/backing size、runtime driver、kernel/workload | data交接、权限/越界、high-address-no-alias |
| 新设备 | 库C ABI、DmaDevice壳、事件/PIO/DMA、source分类、config、工具与验收 | 独立库→单设备→原回归→多源+反馈 |
| 在线内存换后端 | 匹配data/mask/step/pop/error ABI或新增adapter，更新build/bootstrap/checker | 真字节、反压、child顺序、完整往返，不只是链接成功 |
| NPU多次启动 | 壳started/reset、库/RTL、活跃DMA清理、mailbox/trace寿命 | 前一次drain、reset后数据、重复启动独立回归 |
| HETTrace格式 | record.h、writer、reader Struct、validator/merge/convert、所有tap | 版本/布局、截断、兼容、计数语义 |
| Ramulator DRAM时序 | Python DSL/preset、codegen生成物、controller、DRAMPower memspec | device timing、controller schedule、power strict validation |

## 9. 阅读/运行建议与本次验证口径

先读配置了解实例，再读真源头文件了解状态，再沿issue到complete追实现。优先找实际bind/send/complete，而不是根据README目录名画链路。每层要追四项：谁拥有buffer、何时接受、何时退休、队列满怎么办。

本次新增的是解读和文件索引，因此验证以文档路径、索引覆盖与提取格式、Git diff和静态证据复核为主；没有为文档改动新增镜像实现的测试，也没有运行会失败于缺源的全链路构建。

若需要重新验收，先补齐匹配mem_sim和锁定Vortex子模块及依赖，再按根env入口用独立结果目录执行。现存`docs/handoff-validation.md`记录的是此前机器/源码齐全状态，不是当前缺源副本的可运行证明。
