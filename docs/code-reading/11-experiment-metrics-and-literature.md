# 全链路联合仿真的实验指标与公开文献依据

检索日期：2026-09-18。本篇保留研究时提出的实验观测方案，表中状态对应该研究阶段。随后落地的分模块/整体统计、来源关联、窗口与功耗输出见[实现说明](../experiment-metrics.md)，未落地项不记录为测量值。项目事实依据配置、源码和已保存结果；文献观点与本项目建议分别标明。研究范围为CPU/Vortex SimX/CoralNPU RTL→gem5原生TLM→AXI256→AXI2Flit→UCIe→AouTarget→RamulatorBackend→真实backing/Ramulator2/DRAMPower。

## 1. 文献为何要求跨层观测

| 公开资料 | 性质 | 与本项目相关的依据 |
|---|---|---|
| [Ramulator 2.0: A Modern, Modular, and Extensible DRAM Simulator](https://arxiv.org/abs/2308.11030)；[IEEE CAL出版页](https://doi.org/10.1109/LCA.2023.3333759) | 2023预印本、IEEE CAL论文 | DRAM状态/命令时序验证及模拟器效率；不能用集成smoke替代模型验证 |
| [Ramulator 2.1: A Composable Memory System Simulator for Modern DRAM Systems](https://arxiv.org/html/2606.13844v1) | 2026-06公开预印本，不在此假定已经同行评审发表 | 将细粒度约束/调度验证与延迟—吞吐曲线结合；采用流式负载和串行随机probe |
| [Different Perspectives of Memory System Simulation](https://arxiv.org/html/2604.16965v1) | 2026-04公开预印本 | 区分内存模型、CPU-memory接口、应用三个观测视角，指出接口/时钟会使应用与后端表现脱节 |
| [The gem5 Simulator: Version 20.0+](https://arxiv.org/abs/2007.03152) | 2020公开系统论文 | CPU、系统与异构模型的可配置仿真基础 |
| [gem5官方统计说明](https://www.gem5.org/documentation/learning_gem5/part1/gem5_stats/) | 官方文档 | stats/config输出、CPU与cache指标、模拟时间和宿主运行时间区分 |
| [Roofline: An Insightful Visual Performance Model for Multicore Architectures](https://doi.org/10.1145/1498765.1498785)；[作者稿](https://people.eecs.berkeley.edu/~kubitron/courses/cs252/handouts/papers/RooflineVyNoYellow.pdf) | CACM 2009论文；作者稿版本可能早于正式版 | 运算量、实际DRAM字节、可持续带宽与计算上限共同解释瓶颈 |
| [Stall-Time Fair Memory Access Scheduling for Chip Multiprocessors](https://www.microsoft.com/en-us/research/publication/stall-time-fair-memory-access-scheduling-for-chip-multiprocessors/)；[作者全文](https://users.ece.cmu.edu/~omutlu/pub/stfm_micro07.pdf) | MICRO 2007论文 | 总吞吐与各源slowdown、公平性需同时衡量 |
| [Improved Power Modeling of DDR SDRAMs](https://kgoossens.estue.nl/docs/research/2011-dsd-memory-controller.pdf) | DSD 2011论文 | 功耗依据实际命令间隔、状态持续时间及电气参数，不只按最小时序和访问次数估算 |
| [DRAMPower官方项目](https://github.com/tukl-msd/DRAMPower) | 官方实现/说明 | 命令驱动能量估计、memspec和模型文献；不能因此宣称本地HBM4参数已校准 |
| [UCIe Protocol Tutorial](https://hc2023.hotchips.org/assets/program/tutorials/ucie/UCIe%20Protocol.pdf)；[官方规格入口](https://www.uciexpress.org/specifications) | Hot Chips 2023官方教程、规格入口 | 协议/adapter分层、Flit格式、CRC/retry；本文不套用未经核对的最新版硬件性能目标 |
| [MLPerf Inference Benchmark](https://arxiv.org/abs/1911.02549)；[ISCA出版页](https://ieeexplore.ieee.org/document/9138989/) | 2019预印本、ISCA 2020论文 | 按场景衡量吞吐与尾延迟并维持正确性/质量；仅借鉴方法，不把当前用例称为MLPerf合规结果 |
| [DRAMsim3: A Cycle-Accurate, Thermal-Capable DRAM Simulator](https://user.eng.umd.edu/~blj/papers/cal2020.pdf) | IEEE CAL 2020论文 | 可作为匹配标准/参数条件下的独立模型参考；不是HBM4接入已经完成的证明 |
| [Vortex: Extending the RISC-V ISA for GPGPU and 3D-Graphics](https://arxiv.org/abs/2110.10857)；[官方项目](https://github.com/vortexgpgpu/vortex) | MICRO 2021论文、官方实现 | 计算模型、软件栈和GPU访存需一起考虑；本地具体配置为SimX |
| [HBM-Power官方研究artifact](https://github.com/CMU-SAFARI/HBM-Power) | 公开源码、数据与测量artifact；本文不假定其论文发表状态 | 展示实测HBM电气校准路径；HBM2/HBM3E数据不能直接替代当前HBM4参数 |

以下指标是对这些方法的项目化综合设计，并非任何一篇论文规定的完整清单。每个研究问题需要同时有结果指标、机制指标和可信性证据。

## 2. 统一统计口径

必须记录三种窗口：全程（配置启动到结束）、任务ROI（Host明确开始任务到校验完成）、设备kernel（实际启动到完成）。另为持续吞吐实验定义warmup、稳态和drain阶段。共享DRAM总能量按照共同窗口统计，各设备窗口不能各算一次再相加，重叠部分会重复。

所有原始时间为1fs tick，显示ns/us；各域cycle附带对应周期，不能混加CPU/GPU/NPU/AXI/DRAM周期。保留native统计结束tick和仿真结束tick差异。Host程序完成时间属于模拟时间；hostSeconds/墙钟属于运行模拟器的机器时间。

流量分层计数：原始Packet、TLM payload、AXI burst/beat、AoU消息/Flit、物理帧/重放、DRAM child/命令。字节分为成功完成的有效用户字节、AXI有效lane字节、native固定transaction字节、物理传输字节。写入按byte-enable/WSTRB计算，重复读写应重复计入流量，不等于唯一地址footprint。全零掩码请求应保留请求数但有效写字节为零；错误请求分开计数。

端到端分类至少为source(CPU/GPU/NPU/CP/控制)、读写、大小、区域、phase、状态、channel。native维护命令token=0独立保存。读写、不同大小和不同来源的分位数分别报告；没有样本的量输出null而不是0。

## 3. 整体输出指标

状态：已有=当前结果直接提供；可派生=已有原始记录可后处理，仍需新增报表；需补充=需要采样/事件/工作负载。已有全程量不等于已有ROI量。

| 指标 | 定义/单位 | 支持的问题 | 当前状态 |
|---|---|---|---|
| 任务makespan | ROI_end−ROI_start，us | 配置是否改善完整任务 | 退出时间已有；任务marker需补充 |
| GPU/NPU kernel时间 | 每设备start/end差，us，附cycle | 设备受内存拖慢多少 | 周期/完成日志已有，统一marker需补充 |
| 应用吞吐 | 成功任务/批次/元素数÷对应时间 | 性能是否提高 | 工作量定义及重复任务需补充 |
| CPU committed IPC/CPI | committed instructions÷cycles及其倒数 | Host执行表现 | 全程stats已有；ROI统计需补充 |
| 端到端访存分布 | 发起到设备完成，mean/P50/P95/P99/max ns | 是否有长尾和某源饥饿 | TLM/monitor边界可派生；完整设备边界需补充 |
| 按源goodput | 成功有效字节÷ROI时间，GB/s | 各源实际获得多少服务 | 有效字节可派生，ROI需补充 |
| 加速比 | T_baseline/T_candidate，同任务 | 优化收益 | 可派生，基线条件必须一致 |
| 共享slowdown | T_i_shared/T_i_alone，同源同工作量 | 三源争用代价 | 固定共同DRAM配置的alone/组合实验需补充 |
| 公平性 | 每源slowdown、最大slowdown；可选normalized-progress Jain指数 | 总吞吐改善是否牺牲某源 | 需补充 |
| DRAM能量/功率 | 每窗口E及E/T，J/W | 速度与存储能耗权衡 | 全程已有；ROI需补充 |
| DRAM能量/任务、有效byte | E_dram/成功任务或有效字节 | 单位工作存储成本 | 可派生，ROI需补充 |
| DRAM能量×任务延迟 | E_dram×T_task，J·s | 存储能量与任务性能联合目标 | 条件指标，不能称整机EDP |
| 正确性与排空 | 错字节、丢失/重复完成、违规、剩余请求 | 结果能否可信 | 已有 |
| 仿真成本 | 墙钟秒、峰值RSS、模拟秒/墙钟秒、trace大小 | 参数扫描是否可承受 | gem5部分已有，峰值/日志开销需补充 |

独立任务可借鉴weighted speedup=Σ(P_i_shared/P_i_alone)及harmonic speedup。固定工作量时P比可取T_alone/T_shared；CPU/GPU/NPU的周期和IPC不可直接相加。有依赖的流水任务以makespan/关键路径/每阶段时间为主，不能套独立多程序公平性评价。

## 4. 局部模块输出指标

### 4.1 设备、gem5互连、TLM

| 指标 | 用途 | 状态 / 采集位置 |
|---|---|---|
| CPU指令、IPC、cache命中/缺失/MPKI、miss等待 | 排除CPU/cache瓶颈 | stats.txt已有；target窗口uncacheable须单独解释 |
| GPU/NPU计算busy、外存wait、idle周期 | 区分计算受限和内存受限 | 需在SimX/RTL/设备壳定义状态；不能用总请求延迟求和替代 |
| GPU memory-level parallelism、在途token | 延迟隐藏能力 | 需采样SimX与gem5设备状态 |
| 设备DMA数、大小、mask密度、完成等待 | 原生请求→Packet转换开销 | 字节/请求部分可派生，设备级生命周期需补充 |
| PIO提交、轮询与同步时间 | Host控制开销是否掩盖kernel | 独立marker/控制计数需补充 |
| TLM begin→END_REQ、END_REQ→AXI完成、AXI完成→END_RESP | 接收排队、下游服务、响应退休 | transactions.csv可派生，注意AXI ID复用 |
| gem5请求/响应retry、阻塞时长 | 入口与出口反压 | 部分记录可派生，按原因持续时间需补充 |

GPU/NPU内部等待只在当前模型实际支持观测时报告；不虚构tensor占用等指标。不同阶段可以重叠，计算busy和访存wait的定义必须说明互斥与否。

### 4.2 AXI256

| 指标 | 用途 | 状态 / 采集位置 |
|---|---|---|
| 五通道握手数/速率 | 哪个通道限制流量 | axi_events.csv、VCD可派生 |
| AW/W/AR/R/B各自stall周期 | 前后向反压定位 | VCD可派生，分母为本通道VALID周期 |
| W/R beat利用率 | 数据总线实际忙碌比例 | VCD可派生 |
| WSTRB和窄读lane利用率 | 32B总线中多少有效字节 | CSV/VCD可派生，读按地址/SIZE关联合法lane |
| burst长度/SIZE分布、4KiB分割率 | 请求拆分与包效率 | transactions/AXI可派生 |
| Packet→burst、burst→child放大率 | 桥接开销 | 可派生，保留一对多映射 |
| AW/W到B、AR到首R/末R | 读写链路延迟与组装等待 | 可派生，写同时报告地址与最后W边界 |
| outstanding时间均值/峰值 | 并发是否不足 | AXI生命周期可派生 |
| 错误、稳定性、LAST/顺序违规 | 协议与数据可信性 | 已有checker和VCD审计 |

AXI_lane_eff_write=Σpopcount(WSTRB)/(32×成功W握手数)，含全零mask时分母仍计实际握手。总线上传输而最终错误的字节与成功goodput分开。VALID&&!READY周期可能在不同通道同时发生，不能把五通道stall相加称为总延迟。

### 4.3 AoU、UCIe、AouTarget

| 指标 | 用途 | 状态 / 采集位置 |
|---|---|---|
| 消息类型、消息/请求、Flit/请求分布 | 协议开销 | aou_messages、raw Flit可派生 |
| 帧装填、空/credit帧比例 | 包效率与credit流量 | 从解码业务granule可派生，不能把250B称为用户数据 |
| 每RP credit耗尽时间、最小credit、credit往返 | 是资源不足还是物理带宽不足 | 需要credit状态事件/采样 |
| Adapter和Target FIFO时间占用/峰值 | 缓冲配置和瓶颈 | 需补充 |
| Target写组装时间、等待缺失beat | 长burst和AW/W偏移代价 | 消息边界部分可派生，完整ready事件需补充 |
| 两方向唯一交付/新帧/重放帧与物理字节 | 请求、响应和重放分别消耗什么 | 原始双端Flit可派生，不能双端重复计传输 |
| CRC/序号失败、NAK、timeout、重复丢弃 | 可靠性与恢复机制 | 部分统计结构已有，整机需统一导出 |
| Replay tax | 重放字节/总物理字节，另报告重放/新帧 | 日志可派生，两种分母明确 |
| 错误→恢复交付的时间 | 重放对长尾的影响 | 可派生，复杂多帧恢复需关联表 |
| PHY忙碌时间、单向goodput、串行化时间 | 链路负载和上限 | 传输部分可派生，busy区间/反馈路径需补充 |
| retry buffer/full状态与占用CDF | BDP和回放缓存是否不足 | 结构部分已有，持续时间采样需补充 |
| training时间、不可服务状态时间 | 启动/故障恢复开销 | 部分状态记录可派生，统一窗口需补充 |

RP不是DRAM channel。ready/valid、credit、retry buffer和FDI FIFO会共同限制吞吐；只报告物理速率不能解释有效带宽。当前replay用例注入的是物理帧错误概率，不能把2%帧错误称为2% BER或实测可靠性。正确性检查以交付一次为准，重放帧不增加用户工作量。

### 4.4 RamulatorBackend、真实数据

| 指标 | 用途 | 状态 / 采集位置 |
|---|---|---|
| parent/child计数与有效bytes/固定transaction bytes | 请求拆分及DRAM访问放大 | summary/bridge可派生 |
| parent槽、child槽、hazard深度分布 | 桥接并发与同址序列化代价 | 生命周期部分可派生，unsent/hazard状态采样需补充 |
| child accept→submit、submit→终端issue、issue→SERVICE | 等待分解，区分桥接与DRAM | bridge可派生 |
| parent全部child完成→FIFO返回 | 全局FIFO/HOL和出口反压 | 最后SERVICE和return可派生；forced hold/FIFO原因需补充 |
| parent队首未完成且后方已完成的持续时间 | 量化global FIFO的HOL | 可派生部分生命周期；直接事件更可靠 |
| native拒收原因、child额度、hazard、响应hold/full各自时间 | 指明真正瓶颈 | 原计数已有但需拆原因/持续时间 |
| 数据读快照、masked write、最终image一致性 | 保证真实数据因果 | 已有独立scoreboard |
| backing已分配页、footprint、宿主内存 | 支撑大窗口的实现成本 | 页数已有；峰值及唯一触达统计可补充 |

当前hazard_stalls可在一个tick扫描多个descriptor时累加；submit_stalls合并child额度与native拒收；response_stalls合并人为hold与FIFO拒收。它们不是统一口径的等待周期，不能直接相加或乘period称为stall time。

### 4.5 DRAM模型

| 指标 | 用途 | 状态 / 采集位置 |
|---|---|---|
| 每channel读写数、吞吐、延迟 | 负载均衡与控制器服务 | ramulator_stats.yaml已有，全程均值可能被启动阶段稀释 |
| 读/写row hit/miss/conflict | 行局部性与映射/调度效果 | 已有；按首次调度分类口径保存，ROI/source需补充 |
| 读写/维护队列占用分布和峰值 | 排队是否主导 | 全程平均已有，CDF/peak/ROI需补充；现有queue_len不覆盖所有在途状态 |
| ACT/PRE/RD/WR/REF实际命令数及每有效KB代价 | 行冲突和刷新开销 | commands可派生，维护token=0分开 |
| bank状态时间与实际并行活动/服务 | bank/channel并行度 | 命令可重建部分状态；精确忙碌/可服务状态需采样或完整时序重建 |
| HBM行/列命令总线利用率 | HBM并行命令发射能力 | 命令可派生，不能假设每tick最多一条命令 |
| 数据总线占用/读写切换 | 数据通路是否饱和 | 命令+展开模型可重建，需清晰定义PC/channel共享边界 |
| 刷新次数、blocked-bank时间、遇刷新请求额外等待 | 刷新的性能影响 | 次数可派生，阻塞/归因需补充 |
| 按约束分类的不可发时间 | tRCD/tRP/tRAS/turnaround/refresh限制 | 需model采样；多个限制可重叠，不能相加 |
| 控制器饥饿、最大等待、调度选择理由 | FRFCFS是否牺牲某源 | 需source传播与调度事件 |
| command/state/timing违规及被检查次数 | 模型验证可信性 | 已有；检查次数不是硬件准确率 |

当前online.cpp提交Request时source_id固定0，所以read_row_hits_core_0不能解释为CPU专属行命中。需建立CPU/GPU/NPU→parent→child→channel关联；若原生调度要使用source/QoS，再扩展ABI契约与测试，而不是只对现有core_0字段改标签。

### 4.6 功耗

| 指标 | 用途 | 状态 / 采集位置 |
|---|---|---|
| ACT/PRE/RD/WR/REF/background分项能量 | 能量因何变化 | dram_power.json全程已有 |
| 每channel能量、分项比例 | 空闲通道代价和负载不均 | 可派生 |
| ROI/phase增量能量与平均功率 | 初始化与kernel分开 | native累计能量快照或命令状态回放需补充 |
| 分窗口功率P(t)、窗口峰值 | 负载变化及能耗峰值 | 需窗口统计；不是模拟电源瞬态峰值 |
| 动态访问项与背景/刷新各自归一化 | 区分工作量和运行时长 | 可派生，命名不要把刷新简单称零负载漏电 |
| memspec电压、电流、活动率及不确定性范围 | 参数敏感性、绝对精度边界 | metadata已有，参数扫描/校准需补充 |

维护/背景的共同能量没有天然单一source归属。source按服务次数分摊、按窗口分摊或按实测模型归因均须写出假设；不能将每源单跑能量相加冒充共享运行总能量，也不能只按token把ACT/PRE归为严格因果能量。

DRAMPower复用Ramulator2命令流，可验证能量汇总，不能提供独立第二套时序验证。backing真实字节尚未驱动逐bit DQ/TSV活动率，当前interface项为零也不证明真实IO功耗为零。整机功耗需另加CPU/GPU/NPU/controller/interconnect模型，并明确计数边界。

## 5. 逐层时间因果与跨层关联

建议事件字段：run_id、config_hash、phase_id、source_id、source_request_uid、Packet UID、TLM UID、AXI ID+使用代次、segment、RP、parent serial、child token、Flit seq+attempt、channel、组织坐标、tick_fs、event、状态、有效字节、native字节、stall_reason。

保留一对多关系表：Packet→payload→AXI burst→消息/Flit→parent→child。一个Flit可以装多个消息，同一消息也可能跨Flit；不能给Flit强行分配唯一source或把seq当请求ID。观察关联可用sidecar，协议字段保持原契约；如果机制本身需要source/QoS再正式扩展接口。

建议边界：设备产生/首次发送、Packet成功接受、TLM BEGIN_REQ/END_REQ、AXI地址及最后W握手、Target完整请求ready、backend accept、child提交成功、实际终端RD/WR、SERVICE、parent最后child服务、响应FIFO返回、AXI最终响应、TLM END_RESP、DMA完成、设备实际消费数据、kernel/任务开始结束。

child_delay=(submit−parent_accept)+(final_issue−submit)+(SERVICE−final_issue)。这是该child的分解；parent服务时刻=max(child SERVICE)，不能求和。parent last_service→return衡量HOL/出口等待，但要分离人为hold。TLM往返不是天然等于RTL load-to-use；设备实际消费数据的时刻需要在模型中单独观察。

整笔请求的分解采用因果路径上的连续、不重叠区间，write路径考虑AW和所有W是否均到齐。task关键路径从依赖图计算，不能将所有设备等待和请求延迟相加。稳态Little关系N≈λL只用于同一队列边界/请求单位/统计窗口，包含进入和退出的完整在途集合，并注明有限窗口/非稳态误差。

## 6. 当前结果说明为什么需要ROI

重新读取现有 results/acceptance-xpu-ramulator2-20260917/three 的dram_power.json，仅做统计分析，没有重跑仿真：全程3.4904515ms、DRAM能量3.3854597mJ、平均0.9699203W。其中background约59.9354%，refresh约39.7528%，合计99.6882%。该比例只描述当前短任务、所选模型与全程窗口，不能推成HBM4物理硬件的普遍结论。

因此目前全程功率可能主要解释Host准备时间与DRAM背景/刷新，不能直接解释kernel数据访问能量。需要输出full_run、initialization、kernel/共同ROI、drain窗口。窗口增量能量必须从同一持续状态模型取差，不能将ROI命令从空状态回放而丢弃开始时的bank状态。

## 7. 能支持论文问题的实验矩阵

| 研究问题 | 自变量/控制条件 | 整体结果 | 局部解释与图 |
|---|---|---|---|
| 是链路还是DRAM限制性能 | 链路速率/串行时间与native能力二维扫描 | makespan、goodput、P99 | PHY忙碌、credit、child等待、DRAM队列；吞吐热图 |
| outstanding/FIFO是否足够 | parent slots、child limit、FIFO/credit预算逐项扫描 | 延迟—吞吐曲线、任务时间 | 额度耗尽时间、时间占用CDF、HOL；饱和拐点图 |
| 窄/掩码请求是否浪费传输 | 1/2/4/8/16/32B、mask密度、对齐，固定有效工作量 | 有效goodput、DRAM能量/有效B | lane/帧装填、child放大、命令/KB |
| 地址映射怎样影响争用 | 同row、同bank换row、跨bank/channel、stride；容量固定 | 吞吐、尾延迟、能量 | row hit/conflict、ACT/PRE、channel热图 |
| 调度是否公平 | 各源alone、两两组合、三源，同一DRAM channel/容量配置 | 每源slowdown、makespan | source队列/服务/最长等待；公平性散点 |
| 链路错误有多少性能代价 | 固定帧错误模型、多个seed、相同工作量 | P99、goodput、任务时间 | replay tax、恢复时间、buffer满；错误率曲线 |
| 刷新影响是什么 | 合法刷新参数与任务相位；off仅为机制上界对照 | 延迟尾部、任务时间、刷新能量 | 遇刷新请求等待、bank阻塞；timeline |
| 计算/访存比例是否改变瓶颈 | 实际kernel规模、复用、流量强度、计算量 | kernel时间、ops/s、goodput | compute busy/memory wait、OI；Roofline |
| backend保守顺序代价 | 首先测量同址hazard/global FIFO；比较策略前保持同样数据语义 | makespan、P99 | HOL、hazard持续时间；关键路径分解 |
| 功耗与性能是否存在Pareto | 配套周期/timing/memspec、channel数量、合法策略 | DRAM E、task T、条件EDP | 背景/刷新/访问项；能量—延迟Pareto |
| 模型是否可信 | 微基准、原生/全链路层级比较、匹配独立模型或实测 | 无负载延迟、饱和带宽、latency—throughput | 指令/命令/状态合法性与差异报告 |
| 仿真可扩展性 | 工作量、channel数量、trace开关与采样粒度 | 墙钟、峰值RSS、日志量 | 各组件host profile；成本—观测精度图 |

读写比例、局部性、并发、大小至少作为基础维度；固定随机seed和地址分布。microbench应包括串行依赖读/指针追踪、流式读写、读写混合、固定bank冲突、掩码写、响应堵塞、刷新交叠。当前tester主要为正确性定向测试，GPU n=4是功能smoke，都不是可持续饱和带宽基准。

默认npu单跑2channel而gpu/three为8channel，不能直接计算公平slowdown；alone与shared必须保持共同后端组织、时钟、容量、地址映射和设备配置，仅移除干扰源。当前three_slow为配套时钟敏感性实验，CK刷新计数不变而墙钟刷新间隔改变；不能宣称只改变数据延迟。关闭refresh、旁路链路、无限资源仅作为消融参考，均明确改变模型。

CPU/GPU/NPU若有数据依赖，定义提交/同步/计算/返回的关键路径；现有three为Host协调分开缓冲区，不能称为一致性GPU→NPU模型流水线。LLM-like trace只能报告访存行为；真实ops/s、tokens/s、TTFT/TPOT需实际计算与有效任务定义。

## 8. 最小输出包和实现优先级

建议每个case输出manifest.json、markers.csv、request_map.csv、events.csv、metrics.json、latency_hist.csv、queue_occupancy.csv、stall_reasons.csv、power_windows.csv，保留原VCD、raw双端Flit、最终image和check报告。以上是建议新增文件名，当前不会自动全部生成。

metrics.json每项附value/unit/window/boundary/population/source/read_write/sample_count/model_scope/estimation_flag。manifest记录实际源码和库hash、模型组织、所有周期、展开配置/memspec hash、队列/credit/顺序策略、任务数据规模、随机种子、ROI、完整/截断状态和验证结果。不同配置的counter差异不自动等于性能收益。

P0：任务/设备markers，稳定来源关联，分层有效字节/流量，分源读写延迟分位数，parent/child时间分解，分项窗口功耗，保留正确性门槛。多数先从现有CSV派生；完整设备消费时刻和ROI需要新事件。

P1：FIFO/credit/队列时间占用及CDF、按原因stall持续时间、HOL/刷新等待、统一后端配置alone/组合实验、可调负载微基准。按模型周期或状态变化积分，不能只在请求到达时采样队列而声称时间均值。

P2：更丰富真实kernel、Roofline、合法策略比较、独立后端同条件对照、实测HBM校准、全系统功耗扩展。已有上游论文验证不替代当前导入版本与在线适配的验证；匹配时比较定义/单位/边界/波形/参数，不只比较一个均值。

确定性用例重复运行主要检查一致性，重复同一seed不产生统计置信度；错误/随机流量用多个独立seed报告分布与置信区间。分位数给出算法和样本量，几十个任务不应声称可靠P99；短kernel区分任务样本与其成千上万笔memory样本。稳态实验请求跨窗口时报告censored/inflight或完成队列的口径，不删除长尾未完成请求制造低延迟。

优先图：任务/设备时间、因果等待分解、分源latency CDF、吞吐—延迟曲线、队列/credit timeline、channel/bank热图、DRAM能量分项、alone/shared slowdown、E—T Pareto、正确性/模型一致性及仿真成本表。没有对应负载扫描时不画虚构曲线。
