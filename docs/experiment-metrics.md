# 每次运行自动输出的实验指标

完整链路仍为 CPU/GPU/NPU → gem5 原生 TLM → AXI256 → AXI2Flit → UCIe → AouTarget → RamulatorBackend → 唯一 backing / Ramulator2 → 实际 DRAM 命令 → DRAMPower，并沿原路径返回。

`gem5_axi/configs/run.py` 和 `run_xpu.py` 自动注册统计收集器，无须另加开关。收集器在 gem5 的设备退出回调和最后一次 `stats.dump` **之后**执行，避免漏掉设备统计或日志末尾。运行中产生原始计数、时间序列和标记；退出后生成独立模块报告及整体报告。统计错误会使进程返回非零。崩溃、SIGKILL 或原生 fatal abort 不能保证执行 Python 退出回调；只有 `metrics.json.status=complete` 且独立校验通过的结果可用于实验。

## 运行

先构建更新后的模拟器与 Host 工作负载：

```bash
bash env/build.sh
# 首次设备构建使用 env/build_xpu.sh。已构建设备库时，仅更新 Host：
source env/activate.sh
make -C gem5_new/workloads/shared_buffer CC="$AXI_CC"
make -C gem5_new/workloads/three_source CXX="$AXI_CXX"

# 八种在线内存用例：定向、重放、浅队列、响应保持、AXI时钟、功耗关闭、CPU、慢DRAM
bash env/run_ramulator.sh results/my-memory-experiment
# NPU、GPU、三源、三源慢DRAM
bash env/run_xpu.sh results/my-xpu-experiment
```

两个验收入口都执行 `check_metrics.py`，并在批次目录生成 `metrics_batch.json` / `metrics_batch.md`。批次中的用例是不同实验，各自时间、能量与带宽不能相加。原来的 `summary.json` 和校验门槛保留。

两个入口未指定目录时，统一按 `results/YYYYMMDD-实验名-rNN/` 保存。日期使用 UTC；实验名默认 `baseline`，同一天、同一实验名的序号从已有最大序号递增，两个入口共享序号。目录创建会检查占用，避免并发运行覆盖。失败的运行也保留目录并占用序号。已有历史结果不改名。

```bash
bash env/run_ramulator.sh                         # 例如20260918-baseline-r01
bash env/run_ramulator.sh                         # 例如20260918-baseline-r02
SS_EXPERIMENT_LABEL=xpu-baseline bash env/run_xpu.sh
# 手动指定目录仍然支持，目录必须尚不存在：
bash env/run_ramulator.sh results/20260918-baseline-r03
```

`SS_EXPERIMENT_LABEL` 只设置批次名称，不改变模拟参数。完整验收批次内仍包含各自的浅队列、慢DRAM等用例。单独进行参数实验时，可在直接调用gem5的命令中使用 `-d results/20260918-queue1-r01` 并同时设置 `--ramulator-queue 1`，或使用 `-d results/20260918-dram-scale4-r01` 并同时设置 `--ramulator-scale 4`；目录名称不能替代实际配置记录。

直接执行 gem5 配置也会自动生成指标，例如：

```bash
source env/activate.sh
"$AXI_GEM5_BIN" --listener-mode=off -d results/my-directed \
  gem5_axi/configs/run.py --backend aou --memory-backend ramulator2 --mode tester \
  --metrics-sample-cycles 1000
"$AXI_PYTHON" gem5_axi/scripts/check_metrics.py results/my-directed
```

`--metrics-sample-cycles` 默认为 1000 个**原生 DRAM tick**，只控制原生队列/功耗时间序列的采样间隔，不改变精确逐周期队列积分与阻塞计数。开始和结束点始终输出。自定义 `--ramulator-config` 时，采样间隔由其根节点 `integration_statistics.sample_cycles` 决定（未设置则为 1000），命令行间隔不会重写自定义配置。缩小间隔可降低窗口边界估计误差，但增加采样和存储成本。

## 每个用例的输出

运行结束后自动生成在线图表，支持CPU、GPU、NPU单用例和三源联合运行。两个gem5配置的退出收集器先保存指标，再在独立Python进程中进行离线校验和页面生成；批次脚本复用既有校验流程，整批结束后打开批次页面。后处理不推进仿真时间，不修改原始波形、Flit、命令、数据和功耗证据。

页面入口为：`results/index.html`（全部已有指标结果）、本次目录的 `index.html`（用例选择及全程指标对比）、每个用例的 `metrics.html`（指标卡片、各channel功率、队列、延迟、命令分布、窗口、模块报告）。旧结果可以执行 `python3 env/publish_results.py <结果目录> --skip-views` 补生成页面。总索引包含尚未独立校验或不完整的结果，并明确显示状态，不能将其混入有效实验。

单用例自动执行数据、AoU、Flit、DRAM和统计校验并生成链路及DRAM视图；执行日志为 `visualization.log`，成功记录为 `visualization_status.json`，后处理错误记录为 `visualization_error.json`。`visualization_data.json`、`dashboard.js`、`dashboard.css` 为页面配套资源；单用例索引使用 `run_index_data.json`，避免覆盖图表数据。

功率和队列图每条曲线最多均匀保留1000个采样点并保留首尾，可能遗漏采样点之间的瞬时峰值。新增带宽曲线采用完整时间区间聚合，不抽点：默认请求100ns区间，长运行自动放大到不超过1000个区间，区间内全部字节和占用时间均保留。窗口边界能量仍按已有采样插值口径显示。不同用例的时间、能量、吞吐和利用率不会相加。

默认自动启动/复用HTTP服务并打开浏览器。`SS_VISUALIZATION_OPEN=0` 可关闭自动打开而保留页面生成及服务；`SS_VIEW_PORT=8001` 可更换服务端口。浏览器或端口错误记录为 `visualization_server_error.json`，已生成的指标不会丢失。默认仅监听127.0.0.1，VS Code容器/远程环境使用浏览器桥接和端口转发。此功能是在每次运行结束后在线查看，不提供运行中实时曲线。直接调用gem5并输出到项目results之外时仍生成页面，自动HTTP查看限于项目results目录。

在VS Code Dev Container或远程环境中，浏览器与模拟器的localhost可能不同。推荐使用查看入口自动启动/复用HTTP服务，并通过环境的浏览器桥接打开报告：

```bash
python3 env/view_results.py results/20260918-cpu-baseline-r01/cpu
# 不传路径时打开results目录；端口占用时可指定--port 8001
```

服务仅监听容器/远程环境的127.0.0.1；VS Code负责端口转发。新启动的服务与查看命令分离，日志保存在 `build/results-view/http-端口.log`。工作区已配置8000端口的自动转发与浏览器打开。查看入口不修改实验数据。

| 文件 | 内容 |
|---|---|
| `metrics_summary.md` | 人可读入口，链接每个模块及整体报告 |
| `metrics.html` | 按需加载独立模块报告，展示各窗口请求/能量/功率；已有链路/DRAM页面也链接此入口 |
| `metrics.json` | 全部模块、整体结果、按源/读写/阶段的延迟统计 |
| `metrics/overall.json` | 总耗时、请求/有效字节、吞吐、各源、流量放大、窗口统计、DRAM能耗及一致性检查 |
| `metrics/cpu.json` | gem5原生CPU统计（指令、周期、IPC、cache等实际配置已有字段），CPU目标访问及延迟 |
| `metrics/gpu.json` | Vortex核心/CP周期、核心/CP读写、完成数、延迟及kernel区间，GPU目标访问 |
| `metrics/npu.json` | CoralNPU RTL周期、读写、延迟积分/最大值、最大在途数、kernel区间，NPU目标访问 |
| `metrics/gem5_interconnect.json` | gem5互连/监控原生统计；本地主存与PIO流量也可能包含在互连统计中 |
| `metrics/tlm.json` | 请求、错误、在途峰值；入口等待、AXI服务、响应保持延迟 |
| `metrics/axi.json` | AXI五通道握手、阻塞周期/时长/比例、占用率、256bit数据槽字节、有效字节效率 |
| `metrics/axi2flit.json` | 打包Flit/5字节粒度/利用率；各RP、各消息类型的队列积分/平均/峰值；请求侧credit等待周期 |
| `metrics/ucie.json` | 双向FDI/物理帧/重传字节与时延，ACK/NAK、CRC、序号/重复、重试缓冲、PHY计数、两端FIFO |
| `metrics/aou_target.json` | 请求、读写beat、错误、完成数、请求/响应FIFO占用 |
| `metrics/ramulator_backend.json` | 保留原统计；父/子在途积分/平均/峰值、独立阻塞原因、入队/提交/服务/返回延迟 |
| `metrics/backing.json` | 实际SERVICE驱动的读/写次数、读字节、WSTRB有效写字节、容量/已分配页、最终数据镜像 |
| `metrics/ramulator2.json` | 完整原生统计和新增派生指标：行命中/冲突比例、fs延迟、每channel与按源DRAM命令、物理事务字节、队列统计 |
| `metrics/dram_power.json` | 完整原功耗统计、分项能量/占比、各窗口能量与平均功率、模型范围与启用状态 |
| `request_metadata.csv` / `request_segments.csv` | 单调UID、来源、原Packet ID、有效byte、AXI分段身份 |
| `request_map.csv` | UID → AXI ID/segment → 后端burst → 原生token，以及accept/submit/实际RD或WR/SERVICE/return时间 |
| `request_flit_map.csv` / `axi_flit_path.csv` / `aou_messages.csv` | UID与原Packet → AXI握手 → AoU消息 → 双向Flit序号区间及两端时间；同一Flit可包含不同请求 |
| `metrics_events.csv` | 带UID/来源的TLM与后端阶段事件，时间升序 |
| `latency_summary.csv` / `latency_hist.csv` | 按源、读写、阶段的样本数、均值、P50/P95/P99/最大值及2的幂次区间直方图 |
| `link_diagnostics.json` | 各段容量来源、各窗口带宽/利用率、在途请求、固定时间分箱、按大小延迟、CDF、阻塞及统计边界 |
| `bandwidth_timeseries.csv` | 每个完整时间区间内各资源的交付字节、带宽、占用率、占用时间和事件带宽/峰值比 |
| `request_latency_partition.csv` | 每个UID沿最后完成DRAM子请求构造的互斥全延迟分段；各段之和严格等于该TLM请求总延迟 |
| `protocol_latency_samples.csv` | AXI首拍/完成/传输/写响应以及UCIe已记录发送到交付的逐样本延迟 |
| `dram_data_bursts.csv` | 由实际RD/WR命令、CL/CWL、nBL及原生周期解析的每个DRAM数据总线占用区间 |
| `backend_queue_metrics.json` / `fabric_metrics.json` | 精确周期采样的队列积分、采样峰值、阻塞周期、credit及原生UCIe计数 |
| `ramulator_queue_metrics.json` | 每channel读/写/维护/active/pending-read队列的逐周期积分、峰值、非空周期 |
| `ramulator_timeseries.csv` | 每channel周期性队列状态和同一DRAMPower实例的累计分项能量 |
| `queue_occupancy.csv` / `queue_hist.csv` | 独立队列时间序列、采样深度直方图和保持上次采样值的占用时长估计；精确积分仍在各队列JSON中 |
| `power_intervals.csv` | 相邻累计快照差分的能量与平均功率，可用于绘制随时间变化的功率；各channel区间和等于原全程能量 |
| `power_windows.csv` | 全程、Host任务、目标活动、设备kernel窗口的能量/功率和边界估计方法 |
| `application_markers.csv` / `markers.csv` | 原始Host标记；收集器汇总的所有区间 |
| `stall_reasons.csv` | 新增周期口径的后端及AXI阻塞原因和持续时长 |
| `metrics_manifest.json` / `metrics_run.json` | 版本、单位、分位数定义、实参、退出状态及关键配置/报告SHA256 |
| `metrics_check.json` | 独立统计契约校验结果 |

原有 `stats.txt`、`ramulator_stats.yaml`、`dram_power.json`、协议/后端summary、AXI五通道VCD、两端完整Flit日志和离线数据/DRAM时序校验全部保留。`ramulator_stats.json` 是同一注册统计树的JSON副本，字段、值与单位匹配原生YAML，不重新计算原生统计。旧 `transactions.csv` 的格式保持不变，新增身份信息使用独立文件。

## 指标口径

### 请求与流量

- 单调UID是TLM请求的集成身份；AXI ID是可重用线上的标识。Packet ID保留用于关联已有HetTrace，不能用AXI ID代替UID。
- 一个TLM请求可拆成多个AXI segment，一个后端父burst可拆成多个固定大小的DRAM child。各层请求数不要求相等，通过 `request_map.csv` 验证一对多关系。
- 有效字节按**成功TLM请求的byte-enable**统计。AXI数据槽按每个W/R握手32B计数；DRAM按原生固定transaction大小×实际SERVICE次数计数；UCIe只在TX_FRAME计算物理传输字节，包含重传，不把RX再计算一次。错误请求不计入有效字节。
- backing读字节是实际服务的字节，可能包含TLM屏蔽的读byte；写字节按SERVICE中来自WSTRB的mask统计。统计代码不维护第二份数据。
- 吞吐默认有效B/s，原生 `*_throughput_MBps` 仍为原有十进制MB/s。全程吞吐与目标活动/任务/kernel区间吞吐分别输出，不混用分母。
- 延迟分位数采用最近秩（nearest rank），每组带样本数。没有样本时分位数与均值为null，少量请求的P99不能作为稳定尾延迟结论。

### 带宽和利用率

页面把“交付事件带宽”“接口占用率”和“数据效率”分开。交付事件带宽是某层在统计窗口内记录的字节除以窗口时间；接口占用率使用该接口自身的容量/时钟口径；数据效率表示已经占用的数据槽或Flit空间中有多少是成功有效数据。三者不能互相替代。

- AXI W/R分别使用256bit数据宽度和实际AXI周期计算单方向峰值；利用率为复位释放后该窗口的成功握手数除以时钟机会数。AW/AR/B只报告状态与握手，不冒充256bit数据带宽。四种状态 `VALID&&READY`、`VALID&&!READY`、`!VALID&&READY`、`!VALID&&!READY` 的周期数必须守恒。
- UCIe FWD/REV分别使用运行时导出的lane/速率/调制、256B物理帧和SystemC量化后的序列化时间计算容量。利用率是TX_FRAME序列化区间的并集占比，包含重放占用，不把传播延迟算成发送总线占用，也不把RX字节重复累计。
- 当前HBM3/HBM4按实际模型导出的transaction bytes、`nBL`、原生周期和PseudoChannel数计算每条数据总线及controller容量。利用率按实际RD/WR命令加CL/CWL后的数据突发区间并集计算；跨伪通道以独立总线容量归一化。其他DRAM类型如果没有已验证的总线容量推导，峰值和利用率保持null。
- TLM按读写及来源输出成功有效字节速率，但没有脱离工作负载的单一峰值，因此不输出伪造的TLM利用率。全链路也不把各层百分比取平均；瓶颈要结合每层占用、背压、在途请求和数据效率判断。

`SS_METRICS_BIN_NS` 可在运行前指定带宽曲线期望分箱宽度，默认100ns，必须为有限正数。为限制报告大小，实际宽度为请求值与“全程/1000”中的较大者；每个区间重新聚合完整事件，不对已有曲线抽样。时间分箱使用左闭右开区间，最后一个仿真tick只计一次；命名窗口中的TLM完成事件沿用原统计的闭合END_RESP边界，以包含定义 `target_activity` 终点的请求。很短区间的“事件带宽/峰值比”可能因事件记账落在边界而超过1，接口利用率仍由占用区间或时钟机会计算并限制在0到1。

### 延迟分解

AXI协议延迟区分AR到首个R、AR到最后R、首R到末R，以及AW和全部W都已接收后到B。UCIe的 `logged_fdi_delivery` 从链路模型记录的首次发送到RX_FDI交付，包含重放后的完成等待；TX_FDI日志已经是发送端取出数据的时刻，因此不包含此前适配FIFO排队。

后端延迟分解为每个父UID选择最后完成SERVICE的DRAM子请求，形成从BEGIN_REQ到END_RESP互不重叠的八段。这样，同组各阶段的**平均值**可以相加并恢复平均总延迟；前缀/返回段仍包含其他AXI分段及并行子请求，不能称为纯UCIe时间。各阶段来自不同请求的P95/P99不能相加。未关联到DRAM子请求的错误请求不进入这张分解表，但仍保留在TLM全延迟统计中。

刷新阻塞时间、读写切换的纯等待时间和按UID归因的阻塞原因当前没有足够事件证据，页面明确列为未统计。刷新命令数量不会被当成刷新阻塞时间，全局阻塞计数也不会被强行归因给某个长尾请求。

### 队列与阻塞

AXI统计的分母是reset释放后的AXI上升沿；Fabric/FIFO/RP统计包含reset阶段，分母独立记录。Ramulator精确队列统计在原有 `tick_prologue` 的**完成读退休之前**采样，read/write/priority积分与原生 `*_queue_len` 相匹配，active和pending-read单独输出。后端父/子队列在SERVICE处理后、返回/接收入队之前采样。各处峰值是该采样位置上的峰值，不能宣称捕获delta-cycle间的瞬时峰值。

`ramulator_timeseries.csv` 的周期性队列状态是在原生tick结束后、外部poll/submit之前采样，和上述pre-service精确队列积分的采样位置不同。`native_global_inflight` 是全局pending子事务数，在每channel行中重复，不能跨channel求和。

原有 `submit_stalls/hazard_stalls/response_stalls` 保留原计数口径（调用/尝试/扫描次数）。新增后端 `stall_cycles` 区分父容量满、child limit、原生拒绝、同事务地址依赖、强制response hold、response FIFO满、父FIFO HOL。地址依赖每周期至多计一次；不同原因可能重叠，不能相加为互斥执行时间。credit等待是在请求侧staging slot有消息且credit不足时采样，不等同于全方向全部credit事件。

`address_hazard` 表示扫描到被依赖阻塞的未提交子事务，同周期仍可能提交其他子事务；`child_limit` 是提交检查时子容量满的周期，即使所有已知子事务都已提交也会计数。`parent_fifo_hol` 只统计队首数据尚未完成、而更年轻的父请求已完成的周期。它们是各原因/状态的观测，不直接等于CPU停顿时间。

外部frontend原生 `source_id` 仍为0，因此 `read_row_hits_core_0` **不表示CPU行命中数**。报告保留这些原名并明确说明；新增按源命令统计通过UID/token关联实现，不伪造源级行命中或能量归因。

### 窗口与能耗

全程窗口从0到gem5退出tick；DRAM模型最后一个native tick可能比gem5退出早不到一个native周期，功耗报告明确输出原生覆盖的结束时间，保留原生全程能量/功率分母。

`target_activity` 是首个目标BEGIN_REQ到最后目标END_RESP，仅用于访问链路分析，**不是任务ROI**。CPU的ramulator_check、共享缓冲Host及三源Host分别写显式任务标记（0x70000000独立PIO控制页，1=开始，2=成功校验及收尾完成）。新运行配置将该页映射为uncacheable，控制写不进入DRAM链路。Hosted程序仅在配置设置 `SS_METRICS_MARKERS=1` 时写入，不影响旧配置；任意外部程序如果没有写标记，其任务ROI标为unavailable。GPU上游vecadd不改外部源码，仍提供真实GPU kernel窗口及目标活动窗口。

GPU/NPU窗口来自实际设备启动/完成事件。多个窗口可能重叠，不能把窗口能量求和当作全系统能量。每窗口流量按END_RESP落在区间内计数，并输出跨边界请求数及按源统计。

区间能量来自同一在线DRAMPower实例的累计能量差，不从冷态重放ROI。采样边界上的区间差分与全程总值严格守恒；任意Host/kernel边界位于采样点之间时，采用累计能量线性插值，明确标为estimate，并给出最大采样间隔。缩小间隔增加边界精度，不能替代物理功耗校准。

启用功耗时保留原分项：core/interface、ACT/PRE/RD/WR、REF/RFM、background、controller/dram interface。关闭DRAMPower时原文件中的0保持兼容，但新派生能量/功率为null并标disabled。零interface能量不意味着真实接口不耗电。

实际DRAM命令驱动core能耗；接口部分沿用现有插件的翻转率/占空比等参数估计，尚未把backing数据的逐位翻转传给原生功耗模型。真实数据正确性与基于实际电流/IO翻转的功耗校准是不同验证项。

当前只有DRAM有能量模型。CPU/GPU/NPU/AXI/UCIe/控制器逻辑功耗未实现，整体报告不能冒称包含这些部分。背景/刷新共享能量不按请求来源强行分摊，按源DRAM命令统计可供后续归因研究。

## 维护与校验

实现入口：`gem5_axi/scripts/collect_metrics.py`。设备统计真实源码位于 `gem5_new/gem5int/src/dev`，构建时刷新gem5副本。原生采样实现位于 `ramulator2/integration/online.cpp`；现有9个C ABI函数及ABI版本保持不变。

```bash
python3 gem5_axi/tests/metrics_contract_test.py
python3 gem5_axi/scripts/check_metrics.py <用例目录>
python3 gem5_axi/scripts/check_metrics_negative.py <已通过的定向用例>
python3 ramulator2/integration/check_metrics_sampling.py <在线库.so> <新采样验收目录>
# 在所有用例已有metrics_check.json之后生成批次索引
python3 env/summarize_metrics.py <批次目录>
```

独立检查重算有效字节/延迟、UID与原请求对应关系、子事务因果、原生YAML/JSON数值、队列积分约束、阻塞口径、功耗区间守恒及关闭语义；同时检查带宽分箱字节守恒、运行时容量来源、AXI四状态周期守恒、利用率范围和每个UID互斥延迟分段。负向检查还会篡改链路容量、删除带宽分箱、破坏延迟分段，要求全部被拒绝。`metrics.json` 的一致性检查与原有离线字节/DRAM时序校验互补，不能代替它们。

## 2026-09-18 本机验证

两个完整验收入口已运行并通过：

- `results/acceptance-metrics-ramulator2-20260918-v2`：8组内存/CPU用例，原生2项CTest、在线API、独立数据/Flit/DRAM时序、AXI五通道VCD审计及各用例新统计契约均通过。
- `results/acceptance-metrics-xpu-20260918-v2`：NPU/GPU/三源/三源慢DRAM共4组，设备计算、数据链路、真实来源、VCD及新统计契约均通过。
- `results/acceptance-metrics-one-channel-20260918`：单channel与每native tick采样的新报告通过，覆盖原生单controller字典结构。
- 1/1000/100000tick采样得到完全相同的原生ISSUE/SERVICE事件、完整原生统计及总能量；6种统计篡改均被独立检查拒绝；最终版5项统计契约单测通过。

三源示例输出13份模块报告及整体报告。9739个TLM请求关联9739个父burst和9949个原生child：CPU9362、GPU249、NPU128。全程3.4925975ms的DRAM能量为3.387497774mJ，平均0.969907862W；显式Host任务ROI为1.0969855ms，对应DRAM能量约1.071332960mJ（非采样点边界使用插值估计）。

慢配置保持同一计算并产生真实延迟反馈：CPU完成时间增加14.662us；三源NPU周期4908→7067、GPU周期626→1214、Host完成增加160.701us。新任务标记及Host编译使启动相位不同，不能把本批次的设备周期与2026-09-17批次混作同一运行。

这些是本机功能/统计契约验收，不是硬件绝对性能/功耗校准或多种子统计显著性结论。运行结果不提交Git；报告入口是各用例的metrics.html和批次metrics_batch.md。

## 2026-09-21 带宽与延迟诊断验收

- `results/20260918-bandwidth-latency-r01`：定向/replay/浅队列/响应保持/3ns AXI/关闭功耗/CPU/CPU慢内存共8组通过；最终派生统计重新收集后，9种统计篡改全部被拒绝。
- `results/20260921-bandwidth-latency-xpu-r01`：NPU、GPU、三源、三源慢内存共4组通过，包含设备计算、数据、Flit、DRAM命令时序、HetTrace、AXI五通道VCD、带宽分箱及延迟分解检查。
- `results/20260921-bandwidth-final-smoke-r01`：用最终代码从gem5退出收集器自动执行后处理、独立校验和页面生成，17个定向请求全部通过。
- 6项统计契约单测、Python编译、shell/JavaScript语法、Git差异检查通过；真实Chromium页面验证覆盖利用率表/曲线、延迟CDF、关键请求分解、阻塞表、批次P99对比，以及三源CPU/GPU/NPU筛选，未出现JavaScript错误。

定向用例的AXI写/读占用率约18.35%/16.99%，UCIe正向/反向序列化占用率约72.37%/80.07%，说明小请求封包及返回流量会使物理链路占用显著高于AXI有效数据槽。CPU正确性用例只有480B成功有效数据，其AXI写/读占用率约0.478%/0.360%，不能用于推断系统饱和带宽。这些数值是本项目当前模型和工作负载的功能验收结果，不是硬件标称性能。

在线可视化改造另在 `results/20260918-visualization-{directed,cpu,npu,gpu,three}-r01/` 验证了退出后自动校验、三类页面、HTTP服务和索引生成；完整八组入口位于 `results/20260918-visualization-memory-batch-r01/`，验收通过。CPU与原基准的请求、AXI、两端Flit、后端事件、DRAM命令、最终数据、原生统计及功耗共9项原始输出逐字节一致。无头浏览器验证了图表、队列/模块切换、批次对比、搜索、功耗关闭、总索引，以及三源Flit交互和DRAM分页，无JavaScript错误。浏览器验收工具及依赖只放在build目录，页面运行不依赖这些工具或外部CDN。

公开文献依据与更广的实验设计见 [指标与文献](code-reading/11-experiment-metrics-and-literature.md)。该研究文档列出的硬件校准、完整设备等待状态、连续稳态负载、多种子置信区间等是后续实验工作，不把未实现项记录为测量值。
