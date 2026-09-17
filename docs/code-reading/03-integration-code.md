# 03：系统集成代码详细解读

> 本文保存在线 Ramulator2 替代实施前的静态分析与方案；当前已实现代码、接口和运行配置见[在线后端说明](../ramulator-integration.md)。

本章围绕执行路径解释类、关键函数、状态和上下游关系。路径均相对于仓库根目录；全仓索引另提供符号行号与依赖提示。

## 1. `env`：环境、构建和统一验收

### 1.1 `bootstrap.sh`

计算仓库和依赖根目录，准备 micromamba 2.3.3 下载缓存，校验 SHA256 后解压。`SS_OFFLINE=1` 时不允许为缺失缓存下载。随后依据 `conda-linux-64.lock` 创建统一工具链。

若工具链已存在，它比较锁文件 URL 集合和当前显式导出；相同则不重装，不同则要求新依赖目录。这个行为避免 bootstrap 重链正在参与编译的工具环境。它准备工具，不保证源码完整，也不保证后续 Bazel 构建离线。

### 1.2 `activate.sh`

设置 `SS_ROOT/SS_DEPS_ROOT/SS_PREFIX` 并激活工具链，然后定义 GEM5_HOME、CORALNPU_HOME、VORTEX_HOME、MEMSIM_HOME、各 build 路径、统一 C/C++/Python 和 `PYTHONPATH=gem5_new/tools`。统一 memsim 路径是根目录 `mem_sim`，不是 ramulator2。

它应被 source，因为环境变量必须留在调用 shell 中。没有已安装 Python 就失败。

### 1.3 `check_sources.py`

`LOCAL_SOURCES` 给每个普通目录定义必需标志文件，例如 gem5 原生 TLM bridge、CoralNPU wrapper、mem_sim 的 `integration/online.h`。`check_local()` 确认目录存在、没有内部 `.git`、属于主仓库、没有 gitlink、已纳入索引且标志文件齐全。

`check_external()` 对照 `sources.lock.json` 检查 Vortex HEAD 和递归子模块状态，只检查而不自动 checkout/reset。`--only` 可以选择特定模块；默认要求完整链路所需全部源码。当前默认检查会因 mem_sim 缺失和 Vortex 未初始化而失败。

### 1.4 `build.sh`

调用 activate、源检查、`install_devices.sh`；CMake/Ninja 构建 mem_sim `build-unified`；SCons 使用 X86 基础选项构建 `gem5/build/AXI/gem5.opt`，启用原生 SystemC，EXTRAS 指向 gem5_axi 和统一 monitor。

这个脚本没有把 AXI2Flit 作为另一个 SystemC 进程链接进去。AoU 源由 EXTRAS 的 SConscript 编入 gem5 的 SystemC 实现。

### 1.5 XPU 构建相关文件

| 文件 | 作用及后继 |
|---|---|
| `bootstrap_xpu.sh` | 先执行 CPU bootstrap；校验下载 Bazel/LZ4；安装私有 XPU runtime sysroot，准备 Vortex 编译器与 CMake dependency caches，构建原生 LZ4 |
| `xpu-artifacts.lock.json` | XPU 下载 URL/hash 锁定信息 |
| `fetch_vortex_tools.py` | 准备锁定工具链下载/解压，供 configure 使用 |
| `prepare_vortex_llvm.py` | 调整 Vortex LLVM 工具可用性，避免手选不一致工具版本 |
| `prepare_cmake_sources.py` | 准备 yaml-cpp、spdlog、argparse 等固定源码缓存，减少 CMake 构建时再 clone |
| `build_xpu.sh` | 安装 Vortex 外部适配和 CoralNPU 库源；configure/build SimX、runtime、vecadd；构建 Host workloads；Bazel 原生 C++ NPU 库与 ELF；cquery 选择实际 ELF 路径；最后调用 build.sh |
| `record_xpu.py` | 记录工具、库、kernel 等产物与可用性，供 XPU 验收审计 |

build_xpu 对 Host 编译器和 RISC-V kernel 编译器分开传参数；不会把 Host 的 CFLAGS/CXXFLAGS 盲目用于 RISC-V。Bazel 传 `storagestacked_native_cpp=1`，这是防止 NPU 共享库再链接另一套 SystemC 的关键。

### 1.6 运行与验收脚本

| 入口 | 配置/后端 | 主要用例 | 后续处理 |
|---|---|---|---|
| `run.sh` | RAM 与 AoU/simple | directed、CPU l3/l9、observer_off 等 | verify_run 比较观察透明性与反馈 |
| `run_memsim.sh` | run.py，AoU/memsim | directed、replay、shallow、held、3ns、CPU、CPU slow | 原生 ctest/API、AXI/AoU/link/memsim checker、HTML、negative、verify_memsim |
| `run_xpu.sh` | run_xpu.py，AoU/memsim | NPU、GPU、three、three_slow | 原生 ctest/API、数据与链路校验、trace validate、wave audit、verify_xpu |

所有统一入口要求新的结果目录，保留环境记录，gem5 启动明确 `--listener-mode=off`。验收不是只看可执行文件返回 0，而是检查 workload 自检、模拟退出原因、摘要和独立数据证据。

### 1.7 其余环境工具

| 文件 | 输入 → 输出 | 解决的问题 |
|---|---|---|
| `record.py` | 当前源码/工具 → environment manifest、差异快照 | 保存这次运行到底用了什么；生成的 patch 是记录，不是内部模块基础构建补丁 |
| `dependency_bundle.py` | pack/verify/install + 依赖目录 | 打包/校验/恢复缓存、外部源码；旧包兼容时不会把已内置目录恢复为子模块 |
| `native_tests.py` | native test plan 与结果 | 动态统计原生 ctest，通过项数不硬编码为历史常数 |
| `verify_run.py` | simple/RAM 的各结果 | HETTrace 字节数、ID wrap、观察开关逐文件相等、CPU latency 反馈 |
| `verify_memsim.py` | 在线 CPU/tester 各结果 | 原生/API/negative/wave 与 CPU slow 对照 |
| `verify_xpu.py` | 在线 XPU 四用例 | 来源集合、NPU/GPU 计算、Packet/trace 数量、scale4 时实际设备等待增长 |
| `compare_axi_width.py` | 旧/新总线结果 | 比较位宽迁移指标，不修改主数据通路 |
| `tests/test_source_layout.py` | 临时布局/脚本 | 防止普通源码与 gitlink/嵌套目录退化 |
| `internal_imports.json`、`vendored_sources.json`、`upload_sources.json` | 导入记录 | 溯源而非运行时调用关系；它们不能证明未来更新后的所有行为 |

## 2. `gem5_axi/configs`：把源码实例变成系统

### 2.1 `run.py`

解析 tester/CPU、backend、memory-backend、RP、replay、AXI period、slots、memsim capacities 等参数，并检查非法组合。先设置 `10^15` tick/s，再创建 System、Host SimpleMemory、AxiDemo、Gem5ToTlmBridge64。

`system.bridge.tlm = system.axi.tlm` 是 Packet/TLM 与 AXI wrapper 的关键连接。可选 HetAxiMonitor 插在 bridge 的 Packet 上游；tester 直接连 target port，CPU 模式则经 SystemXBar 路由 Host/target 内存。

Root 使用 SystemC_Kernel 管理 system，instantiate 后 CPU Process 映射 target 8KiB uncacheable。模拟结束调用 `axi.finish()`，对 tester 精确核对退出原因，对 CPU 检查最后线程正常退出及 code=0。

### 2.2 `run_xpu.py`

动态 import `het_system.py` 作为前端构造函数库。检查可执行文件/设备库/kernel 路径，并给 Vortex hosted runtime 至少两个 CPU 上下文。创建 1fs 原生 SystemC 系统、本地 Host 页池和完整 AoU/memsim AxiDemo。

目标 bridge ranges 是 shared_buffer、npu_work，启用 GPU 时再加入 Vortex BAR；monitor 只放在目标 bridge 上游，Host 页池和 PIO 不会经过这个 monitor。与旧 het_system 的“所有内存 responder 共同上游观察点”覆盖范围不同。

它复用 CPU cache、设备壳和映射函数；四个 CPU 上下文主要是为 SE clone/runtime worker 提供资源，不表示四条独立 AXI 信号总线。Host 进程退出和数据自检共同决定验收结果。

## 3. `gem5_axi`：原生 TLM、AXI 与完整链路装配

### 3.1 `Gem5Axi.py` 与 `SConscript`

`Gem5Axi.py` 定义 AxiDemo 的 Python 参数与 `TlmTargetSocket(64)`，对应 C++ `storage_axi::Demo`；`PyBindMethod('finish')` 让配置脚本能主动收尾。AxiPacketTester 定义系统 requestor、RequestPort 与响应 hold 参数。

`SConscript` 注册 SimObject/Source，加入公共 AoU、UCIe、HETTrace include，链接 `storagestacked_memsim` 和 RPATH。`aou_axi2flit.cc/aou_flit_packer.cc/aou_flit_unpacker.cc` 是仅几行的源码编译包装，include 真正的 axi2flit 实现，目的是在 gem5 原生 SystemC 下编译共享代码；不应在包装文件再维护一份算法。

### 3.2 `axi_signals.hh`

`DataBits/DataBytes/DataSize` 分别为 256/32/5。两个宏列举 Master→Slave 与 Slave→Master 字段，用同一份字段表生成 `Signals/MasterPorts/SlavePorts` 和 trace，降低端口方向与位宽失配风险。

Signals 是真实 sc_signal 集合；MasterPorts 和 SlavePorts 用 bind 接到同一 wires。虽然桥侧另有 AxChannel/WChannel 结构体，真正 AXI ready/valid 是独立 signal，不能用结构体中辅助 valid/ready 判握手。

### 3.3 `axi_demo.hh/.cc`：容器与观察边界

构造器创建 clock、resetn、Master、TlmTargetWrapper、wires，再根据 backend 实例化 Ram 或 AouBackend，设置 Master.functional callback。AoU 模式限制 outstanding 和 live ID 为 1023。

`reset()` 拉低 reset，等待三拍半，并等待 UCIe Active/Degraded 后释放 reset。`gem5_getPort('tlm')` 返回 target wrapper，使 Python 参数端口连接到 Master socket。

`sample()` 在每个 AXI 正沿断言 SystemC/gem5 同时钟，逐通道检查被阻塞的 VALID 与 payload 保持不变；握手后写 `axi_events.csv`。`channel()` 使用 held map 保存上拍反压数据；`row()` 记录宽数据十进制与其他字段。

`finish()` 幂等刷 CSV、调用 AoU finish，强制 gem5 TraceFile 同 tick 补当前信号再关闭 VCD，以免最后边沿漏写；随后写 accepted/completed/drained、频率、周期、位宽和五通道握手/stall 计数。

### 3.4 `axi_master.hh/.cc`：整笔请求的状态机

Master 核心状态：

| 成员 | 含义 |
|---|---|
| pending / pendingAt | 当前处于 BEGIN_REQ 排他阶段的 payload 及数据最早可用时间 |
| active[id] | 已 END_REQ、尚未 END_RESP 的整笔 TLM Txn |
| Txn.bursts / segment | 原访问拆出的多个合法 AXI burst，当前段序号 |
| awq / wq / arq | 三条请求通道的等待次序；W 维持 FIFO |
| wbeat / rbeat | 当前段数据拍进度 |
| responses / responding | 完成 AXI 后等待 TLM response、当前占用 response 排他的 payload |
| nextId / maxId / slots | ID 回绕、wire 范围和 bounded outstanding |

关键函数：

- `transport(BEGIN_REQ)`：acquire payload，保存 begin 与 payloadDelay，返回 ACCEPTED，不立即把它当作完成。
- `admit()`：有槽位且到达可用时钟沿时分配无冲突 ID；校验读写、data pointer、长度≤65536、地址溢出、streaming width 与 byte-enable。合法则 split/enqueue，不合法则把 error payload 排入响应队列；发送 END_REQ。
- `split()`：从 32B beat 开始缩小至可对齐且剩余长度足够，最多 256 beat，保证不跨 4KiB；保留原 payload offset。非对齐/尾字节可能拆成多个不同 SIZE 的段。
- `enqueueSegment()`：把当前段放入 AW/W 或 AR 队列；测试 stalls 时交替制造 AW leading/W leading，但 W 顺序不交错。
- `tick()`：采样五通道，握手后更新队列；R 根据 ID 找 Txn，恢复有效 lane 并尊重读 byte-enable；B/R error 改 payload status；段完成则继续下一段或排 response；最后 admit/drive/respond。
- `drive()`：输出队首地址/几何与原数据 lane、WSTRB；stall 模式对 BREADY/RREADY 做确定性节流。
- `respond()`：一次只发一个 BEGIN_RESP，直到 bridge 送来 END_RESP。
- `transport(END_RESP)`：写 transactions.csv、回收 active/ID、计 completed、release。
- `debug()/blocking()`：要求 drained 并调用 backend functional；RAM 可直接访问，AoU 则明确拒绝。`dmi()` 恒 false。

重要设计结果：一笔 TLM 的各段顺次推进，不是把所有段独立并发发出去；不同 TLM 请求可同时 active；wire ID 在 response 被上游接受前不重用。

### 3.5 `axi_ram.hh/.cc`：不经过链路的基线后端

Ram 保存本地 bytes，采集独立 AW/W/AR，对写按地址与 WSTRB 更新有效字节，按配置 latency/stall 产生 B/R。AW 与 W 可以不同先后到达，借助队列配对。`access()` 用于 drained debug/functional 基线访问。

它提供 AXI 转换单层基线，不模拟 DRAM bank、刷新或 PHY，也不会把数据送到 UCIe。数据落点只在选择 RAM backend 时使用。

### 3.6 `aou_backend.hh/.cc`：整个在线链路的接线中心

`AouBackend::Fabric` 包含：结构化 AXI signal、FlitTransfer、四个 FDI FIFO、内存请求/响应 FIFO，以及 Axi2Flit、UcieAouAdapter、UcieLink、AouTarget、SimpleBurstMemory 或 MemSimBackend。

构造器依次 bind：

```text
owner.Master AXI wires
 → Fabric comb() 转 AxChannel/WChannel
 → bridge 五通道
 → bridge tx/rx FlitTransfer
 → adapter
 → soc_tx/soc_rx
 → UcieLink
 → mem_rx/mem_tx
 → AouTarget
 → requests/responses
 → chosen memory backend
```

`config(replay)` 从桥共享速率生成 AoU Format6/NRZ 配置，关闭正常噪声、jitter、ISI 后项和 skew；replay 压力模式注入可复现 2% extra frame error。它是定向可靠性测试条件，不是宣称真实链路 BER 为 2%。

`comb()` 把真实 signal 转为结构化通道，逐字节复制 32 lanes，独立连接 valid/ready。它要求已收 AW 才给 W ready，用 writes cursor 队列解决 W 无 ID 的路由关联。

`address()` 采用测试策略 `qos = id % planes`，不是按照 CPU/GPU/NPU requestor 自动分配 RP。requestor/stream 仍主要保存在 TLM 事务 CSV。

`tick()` 记录结构化五通道，在 AW/AR 建 cursor，W/R 核对末拍和递增地址，计 TX/RX；`observe()` 对 UCIe TX_FDI/TX_FRAME/RX_FRAME/RX_FDI 写原始 bytes、fs/ns、delta、方向、seq8、attempt、replay/status，分别写 SOC 和 MEM 端日志。

`ready()` 读取 LinkState，Failed fatal，Active/Degraded 可用。`access()` 永远返回 command error，避免功能访问误落到已经断开的 RAM。`trace()` 同时导出桥 signal、宽数据、canonical `axi256.*` ready/valid/字段。`finish()` 检查 cursor 清空、顺序违规为零、收尾 memsim 和 AoU 摘要。

### 3.7 `memsim_backend.hh/.cc`：C ABI 到 SystemC 的桥

这里不实现 DRAM 调度器，不拥有最终内存字节；它只保存活跃请求与 response 重组数据。

`Burst` 保存请求、响应、连续 data/mask、长度、已提交 sent、未回收 pending、候选 child ID、准备返回时间和 error。`children` 是 `mem_id → Child{shared Burst,offset,bytes}`，保证原 burst 在子请求未完成时仍然存活。

构造器校验窗口/槽位，调用 `ss_mem_create('hbm4',channels,scale,queue,size,dir)`，查询 period_fs，启动 SC_THREAD。

`accept()` 校验 burst 结构；把各拍有效 lane 合为连续字节，检查范围、lock 和非法 strobe，读预建 response beats。错误请求不提交原生 children，但按正常返回路径生成 error response。

`run()` 每内存周期依次执行：

1. 等 period 并核对原生 clock 与 gem5 tick。
2. 有 burst 槽时最多接收一笔 FIFO 请求。
3. 找最早尚未全部提交的 burst，按内存 granule 边界选一个 child，尝试 `ss_mem_submit`；0 保留 candidate ID 重试，成功插 children 并更新 sent/pending。每次循环最多提交一个 child，先完成前 burst 的全部提交再下一笔。
4. `ss_mem_step()` 推进一个原生周期。
5. 抽干 `ss_mem_pop()`，核对 child ID/size/time；把读数据恢复到对应 beat/lane，更新错误，回收 child/pending。
6. 只看 bursts.front；全部 children 回收且可选 response_hold 到期后尝试 nb_write response，否则保持槽位并计 response stall。

全局 response FIFO 简化重组与顺序，但它比 AXI 同 ID 顺序要求严格，可能造成完成侧队头等待。`finish()` 要求 bursts/children/请求 FIFO 清空，调用 ss_mem_finish 并写桥摘要。

### 3.8 `packet_tester.hh/.cc` 与 CPU workloads

tester 直接构造 uncached Packet，保存独立 golden bytes 和 expected read data，按阶段先写后读，覆盖掩码、非对齐、跨 4KiB 原访问、较大访问、错误地址和 response hold/retry。sendTimingReq false 时保留队列等待 retry；response 通过数据/错误核对才删除 Packet。

| workload | 主要作用 |
|---|---|
| `memory_check.c` | CPU 通过真实目标 load/store 校验数据与边界，供 simple latency 对照 |
| `memsim_check.c` | CPU 在线 memsim 自检，供内存 scale 对照 |
| `id_wrap_check.c` | 足量访问触发 ID/synthetic ID 循环复用，防止仅按 ID 全程唯一的错误 checker |

这些程序检查功能；CPU 访存次数、simInsts、时序与退出 tick 由验收进一步核对。

## 4. `gem5_new/gem5int`：设备壳与统一观察

### 4.1 安装与构建归属

`install_devices.sh` 把 `dev/coralnpu`、`dev/vortex` 和 `mem/unified_timing` 从真源复制到 gem5 构建树；`install.sh` 提供更完整的配置/观察器安装。各设备目录 `SConscript` 注册 Python SimObject 和 C++ implementation。

不要只改 `gem5/src/dev` 的副本，因为下一次统一 build 会覆盖它；必须在 `gem5_new/gem5int/src/dev` 真源维护并刷新。

### 4.2 `coralnpu_dev.hh/.cc` 与 `CoralNPU.py`

CoralNPU 是 DmaDevice：PIO 处理控制/状态，DMA 处理外存，EventFunctionWrapper 驱动设备时钟。构造器 dlopen 库并检查必需 ABI，create 返回不透明 device handle；trace ABI 可选。参数指定 library/kernel、clock、share_memory、auto_start、exit_on_complete、PIO 和诊断 tap。

`startup()` 设置 timing backend，打开可选 tap，load ELF 到 TCM；不 auto_start 时等待 Host CTRL。`loadAndStart()` 用 started_ 实现 one-shot，重复启动只告警，避免未验证的 halted core restart；调用库 start 后调下一设备周期。

`tick()` 每次只调用一个 `coralnpu_gem5_tick()`，仍运行则 schedule 下次 clockEdge；halted/wfi 后不再推进，host 读取结果，只有 standalone 的 exit_on_complete 才主动结束模拟。

访存路径：

```text
RTL AXI握手
 → timing callback
 → issueRead/issueWrite
 → 分配sequence / 复制data和byteEnable
 → dmaRead/dmaWrite(addr,16B,done,...,native_id,sequence)
 → 系统目标链路
 → readMemoryComplete/writeMemoryComplete(sequence)
 → 标记memoryDone
 → retireReadyReads/Writes(native_id)
 → ABI complete_read/write
 → RTL RVALID/BVALID
```

同 ID 可能有多个活跃请求，所以 readTxns/writeTxns 按 sequence 查；readOrderById/writeOrderById 保存退休顺序。即使较后 DMA 先完成，也等 ID 队首再注入 RTL。读写分开表。

写 byteEnable 根据 16bit strb 创建，直接 dmaWrite；不会用“先读旧值再拼写”的 RMW 额外制造访存。

PIO 寄存器：CTRL=0x00 bit0 start；STATUS=0x04 bit0 halted/bit1 wfi/bit2 ticking；ENTRY=0x08；EMITTED=0x0c；MAILBOX0..3=0x10..0x1c。Host little-endian 访问，device 声明一页但有定义的寄存器仅 0x20B。

### 4.3 `vortex_gpgpu_dev.hh/.cc` 与 `VortexGPGPU.py`

VortexGPGPU 同样继承 DmaDevice，封装 SimX/CP 动态库。参数中的 timing_memory 默认 false，但统一 build_vortex 强制 true；kernel 预加载 standalone 模式与 hosted timing 模式不可随意混用。

两条访存子路径：

**core**：issueCoreTiming 检查 device address、size 1..64、token 不超 uint32、没有活跃 token 重复；physical=pinAddr+device_addr；复制写数据和 byte-enable，DmaPort 提交；coreDmaComplete 按 token 找上下文，累计实际 latency，再调用库 complete_core_memory。

**CP**：CP ABI 原来具有同步 dram_read/write 外观。gem5 用 CpCoroutine 在 memoryRead/Write 中 enqueueCpTiming → startNextCpDma → yield；响应到达 dmaComplete 后恢复 continuation，给读 callback 真实 dmaData。等待期间它返回 gem5 主调度，不忙等推进时间。

cpDmaQueue 和 activeCpDma 让 CP DMA 串行服务；coreDmas 可保留多个 token。`resumeCpIfReady()` 和 `startVortexIfReady()` 确保 QMD/draw setup 的 CP reads 尚未完成时不让 GPU core 使用提前数据。

`cpTick()` 每逻辑 CP 周期建立/恢复 coroutine，完成一个 ABI cp_tick 后再决定 schedule；`vortexTick()` 推一个 SimX 周期，hosted 完成后唤醒 CP 退休 launch，standalone 则 exit；PIO 写调用 maybeWakeCp。

`getAddrRanges()` 总是声明 CP，但 timing_memory=true 时不声明 BAR PIO，因为 BAR 已归外部内存 responder 所有；read/write 若误收到 BAR PIO 就 panic，防止两个数据真源。

### 4.4 `het_axi_monitor.hh/.cc` 与 `HetAxiMonitor.py`

这是透明 Packet monitor，不是 native AXI signal bridge，也不拥有内存。cpu_side_port 为 ResponsePort，mem_side_port 为 RequestPort。

`classify()` 匹配 requestor 名，先 CoralNPU 再 Vortex，其余 Host；Vortex 带 stream 时归 core 语义，不带则带 DMA flag。新增设备必须修改分类，否则会落为 Host。

`makeTraceState()` 保存源、Request 元数据、原始掩码并按 bus width、对齐、4KiB 和 256 拍拆投影 burst。统一记录全带 SYNTH。

`recvTimingReq()` 先附 sender state，尝试转发；拒绝则恢复状态且不记 begin；成功才 emitBegin。`recvTimingResp()` 上游接受后才 emitComplete；拒绝继续持 state。req/resp retry 原样传递。

`unique_packet_ids=true` 按每源当前活跃 Packet 分配 synthetic ID，允许原 requestor/stream 相同而返回乱序；退休时释放 ID。在在线配置启用，但默认投影位宽仍是 axi_data_bytes=16、id_bits=8，与真实 AXI256 wire 不相同。

`startup()` 把 addrmap 的 ps 周期换算为当前频率，打开各源文件。atomic 兼容路径将未来 completion 按 tick 排队，避免 curTick 不变时写出未来完成记录导致时间倒退；这不表示 AoU memory backend 支持 atomic。

### 4.5 `UnifiedTimingMemory`

用于旧功能路径的 sparse responder：ranges 无重叠检查，4KiB 页按需创建，未分配读零，byte-enable 写只更新使能字节。access 处理普通读写和部分 gem5 命令；timing 路径用 busy、带宽 release event、response packetQueue 和 retryEvent 约束执行。

它提供真实字节共享和基础 latency/bandwidth，不是校准 DRAM controller。在线 run_xpu 没有实例化它。

## 5. `gem5_new/coralnpuint`：NPU 的 C ABI 接缝

### 5.1 `coralnpu_gem5.h`

对外只暴露不透明 handle 与 C 函数，不暴露 CoreMiniAxiWrapper/VerilatedContext/absl 类型。ABI 分为 create/destroy/build_info、同步或 timing memory backend、load_elf/start/tick/status、mailbox、trace。

timing callbacks issue 请求但不立即返回 R/B；complete_read/write 由 gem5 DMA completion 之后调用。运行调用串行且不可重入，设备库不自行驱动一个独立全局时钟。

### 5.2 `coralnpu_gem5.cc`

内部 Device 持有 context、wrapper、callbacks、可选 tap、私有 DDR 指针、启动状态和缓存统计。create 注册 wrapper 的 AsyncRead/Write callbacks，再 Reset。

Async callback 判地址是否在 `[0x80000000,0xC0000000)`：DDR 且 timing backend 启用就发 gem5 callback，不注入完成；非 DDR 或兼容后端用同步 Read/WriteCallback 后立即 Complete。非 DDR master 访问按库语义访问 mailbox。

DDR callback 对齐为 16B 窗口；同步写逐 strobe 字节修改；默认私有 DDR 惰性 calloc 256MiB，仅兼容/standalone 使用。DDR 解码窗口是 1GiB，但私有数组只覆盖其中 256MiB，不能混淆。

load_elf 使用 mmap/LoadElf，把 ELF 段通过 wrapper.Write 写 TCM，初始化阶段可能内部 Step；正式 timed execution 不应调用这个阻塞装载。

当前 **start 实现已是非阻塞**：保存 startAddress/startStage；tick 分三阶段 enqueue PC、CTRL=1、CTRL=0，每次只 wrapper.Step 一周期。头文件及部分注释仍有“start 内部推进时钟”的旧描述，应以 .cc 实现为准。

complete_read 组 AxiRData 并注入 wrapper，最多复制 16B；complete_write 注入 AxiWResp。trace_close 幂等摘 tap、缓存计数再销毁，保证退出摘要不依赖 SimObject 析构。

### 5.3 构建、测试和 trace

| 文件 | 作用 |
|---|---|
| `BUILD.bazel` | 普通/RVV 两个库目标，alwayslink 保留 C 导出，依赖 native wrapper 和 ELF；测试 kernel 独立 target |
| `coralnpu_gem5.map` | 限制共享库导出面；库内 C++ 类型不作为公共 ABI |
| `install.sh` | 仓库内 CoralNPU 快速分支只复制 package/头；外部旧树兼容分支仍含历史 patch 逻辑，不是统一主路径 |
| `ddr_touch.cc` | 读 64 个 shared input，写 `2*x+1` 到 output，mailbox 带完成 tag 与 checksum |
| `coralnpu_trace.h` | standalone 原生 seam 诊断，记录外 DDR 子集，拒绝把多拍等异常静默当合法 |
| `tests/smoke_dlopen.c`、`run_smoke.sh` | 脱离 gem5 检查库符号、创建/销毁与可加载性 |

BUILD 的历史注释曾描述隔离第二套 SystemC；统一构建实际使用原生 C++，不能因旧注释把“再链接并隐藏第二套 SystemC”作为当前设计要求。

## 6. `gem5_new/vortexint`：GPU 上游差异

当前完整上游树不可读，但 `patches/simx_online.patch` 保存明确适配：

- `sim/simx/gem5/vortex_gpgpu.{cpp,h}` 增加 memory backend、core timing issue/complete C ABI 与 trace 接入。
- `sim/simx/mem/memory.{cpp,h}` 保存 token→ExternalPending、external_completed queue；外部 hook 返回 false 时保留源请求并施加反压；completion 才产生 MemRsp/回传读块。
- `processor.{cpp,h}` 与 `processor_impl.h` 把 timing hook 透传到内存模型。

install.sh 检查反向 dry-run 判断已应用，保持幂等；只修改外部 SimX/ABI，不把系统内 gem5 device 的源码变成外部补丁。`vortex_trace.h` 是独立 post-LLC 观察 tap，主配置关闭以避免和统一 monitor 重复记录。

这说明 core completion 的闭环接点确实存在；仍不能仅凭补丁断言所有 GPU 内部单元/全部配置已经过系统测试。

## 7. `axi2flit/systemc`：AXI 消息化与流控

### 7.1 数据契约头文件

| 文件 | 核心职责 | 相连代码 |
|---|---|---|
| `axi_if.h` | Ax/W/B/R 结构、可配置数据宽、ID/USER mask、trace 支持 | Master Fabric、MsgBuilder/Decoder |
| `aou_types.h` | message/type/DLENGTH/granule、AouFlit pack_fragment、BitWriter/Reader、FIFO 容量预算 | 所有桥模块 |
| `link_config.h` | 16 lane/24GT/s/NRZ/credit round-trip 预算共同常量 | 容量计算与 UCIe config |
| `axi_contract.h` | 对齐/INCR/4KiB/size/WLAST 检查 | bridge、target、memory backends |
| `simple_mem_if.h` | 整笔 burst 的 request/response 类型 | target→memory |
| `aou_wire.h` | Protocol Header 和 payload 固定 250B serialize/deserialize | adapter/target |
| `aou_stream_decoder.h` | MsgStart 扫描、G0 carry 重组与完整校验 | unpacker/target |
| `rp_order_guard.h` | 同方向同 ID 活跃事务绑定 RP、计违例 | AXI begin/最后 response |

### 7.2 `msg_builder.h` 与 `msg_decoder.h`

builder 是 AXI字段→线上消息的唯一编码中心；decoder 反向恢复字段。request 固定 120bit，数据类 DLENGTH 与本端总线宽一致才可解码。全 strobe WriteDataFull 节省一个 5B granule。

decoder 将 request burst 恢复 INCR，write data 不恢复 WLAST，因为消息本身没有它；target 用 AWLEN 组装。保留位、非法数据长度、起点落在消息中间等都需要显式拒绝。

### 7.3 `axi2flit.h/.cpp`

Axi2Flit 是 initiator 的 AXI slave：请求进、响应出。构造器为每 RP 创建 rreq/wreq/wdata/rdata/wresp FIFO，并把 packer/unpacker 与 credit update/return FIFO 接起来。

五个 thread 处理五通道：AW 校验并原子入 WriteReq 和 WriteRoute；W 按 AW route FIFO 配 RP 与剩余拍，检查 WLAST 后编码；AR 直接编码 ReadReq；B/R 在各 RP 间轮转取 response，保持 valid/payload 到 ready，握手后归 credit，最后一拍再 retire order guard。

reset_queues_and_order 显式抽干 sc_fifo，因为 FIFO 本身没有 reset 端口；这只是本地状态清理，不能单靠局部 reset 丢弃远端在途完成。

### 7.4 `flit_packer.h/.cpp`

packing_thread 每拍收 credit、处理已发帧握手、装 staging slots、先续 spill 再仲裁新消息。按 RP 分离 staging，发送前检查/扣整消息 credit，维护 next_rp 公平轮转；发帧后保持 FlitTransfer 至下游接受。

priority 选择由 select_candidate 实现，RREQ 先于 WREQ，再考虑 WDATA；请求不同类别不是完全等价公平。低利用率帧由 flush timeout 推出，空闲待归 credit 由 dedicated grant timeout 推出，避免双方等业务帧捎带 credit 导致死锁。

flush_flit 可以把 header credit 捎上业务帧；dedicated CrdtGrant 不重复发相同 header grant。跨帧消息起始只在第一片设 MsgStart，spill 的后续从 G0 续传。

### 7.5 `flit_unpacker.h/.cpp`

接收 holding frame 后先用 stream decoder 完整校验，再产生 pending credit/events，按 type 分流 RDATA/WRESP。输出 FIFO 满时保留 pending_index，hold 尚未全部落地就不给新的 flit ready。

这层不会因为目标 response 队列满就丢帧，也不会把上游传来的 used_granules 当解析长度。unpack 每拍分发数受 `UNPACK_MSGS_PER_CYCLE` 约束，反压不能靠无限缓存隐藏。

### 7.6 `credit_manager.h`

CreditMatrix 为 RP×五个业务类别：ReadReq、WriteReq、WriteData、ReadData、WriteResp。Manager 分 tx_available、rx_capacity、rx_pending_return；consume、add_tx_credit、return_rx_credit、publish_initial_capacity、take_header_grant/take_misc_grants 管流控。

线上不是任意整数 credit 字段，而是受位宽限制的编码；encode_credit_amount 选择不超过 pending 的合法量，余数继续待发，不能四舍五入多发容量。header 每次对一个 RP 给 credit，Misc 给多 RP 矩阵。

### 7.7 `integration/ucie_aou_adapter.h`

桥的 signal handshake 与 UcieLink FIFO seam 之间的双向桥。发送兑现上一拍 ready 容量预约，把 250B AoU bytes 写成 FdiFlit；接收最多持一帧，直到 bridge 的 rx_ready 接受。

训练期间不给新 tx_ready，不消费正常 rx；Active/Degraded 可服务。validate config 防止 AoU 帧格式或速率/调制与桥编译常量不一致。

### 7.8 `integration/aou_target.h`

target 是 responder，不能当成同一个 initiator Axi2Flit 的镜像 AXI signal slave。它直接从 MEM FDI 收 bytes，然后 `receive → collect → assemble → submit → transmit`。

每 RP 四个读槽、四个写槽、64 WDATA granule；最大八个已提交尚未序列化完 response 的请求。WriteJob 预留完整 write_beats vector，assemble 每 RP 每拍至多搬一个 W beat并释放 data credit，支持超过短 data 窗口的长 burst。

submit 在 RP/读写之间轮询，每拍最多提交一笔完整请求；建 ticket 保存 write/RP/ID/beats。collect 用最早匹配 ticket 检查 response 拍数。next_message 写响应优先，再各 RP 的读响应，发送前扣对端 RDATA/WRESP credit。

transmit 先 spill 再新消息，只有最后 response 的全部片段写进 link_tx 才释放 outstanding；并不等于 Host 已经消费 B/R。hot reset 在 run 中拒绝，要求全链路重建。

### 7.9 `integration/simple_burst_memory.h`

在线 simple backend 顺次读取整笔 request，检查所有地址/lane/lock 后等待 access+per_beat×beats，再修改 bytes或返回各读拍，阻塞写 response FIFO。任一写结构错误先整体拒绝，避免部分修改。

它是定延迟功能模型，适合分层验证；没有 bank/row/refresh/DFI 真实实现。

### 7.10 standalone testbench

| 文件 | 分层目的 |
|---|---|
| `tb_axi2flit.cpp` | bridge 五通道、credit、队列、反压等功能回归 |
| `tb_axi2flit_perf.cpp` | 消息打包利用率与速率/调度压力 |
| `tb_golden_vectors.cpp` | 固定线上字节的编码/解码，避免两端犯同样错误而互相通过 |
| `tb_aou_wire.cpp` | 250B wire 与 MsgStart/跨帧解析契约 |
| `tb_ucie_adapter.cpp` | ready/FIFO/训练门控 seam |
| `tb_preintegration.cpp` | 协议桥与内存侧契约提前对接 |
| `tb_full_link.cpp` | 真实双向 UCIe、target 与 simple memory 联合 |
| `tb_common.h` | 测试公共 BFM、配置和辅助断言 |
| `scripts/full_link_wave.py` | 从独立 full-link 产物生成波形观察 |
| `Makefile` | 256/512/1024 等 standalone 组合、boundary、golden、negative、link 回归 |

standalone 可用独立安装的 libsystemc 运行；它和 gem5 原生统一运行是分开的测试 executable，不能在统一 gem5 进程再链接该库。

## 8. `ucie-model/src`：可靠双向传输

### 8.1 `ucie_common.h`

Config 定义帧格式、lane、rate/modulation、FIFO/retry buffer、UI pipeline、training、噪声/jitter/ISI/skew、CDR、NAK suppression、seed/watchdog。derived functions 给 flit_bytes/payload_bytes/serialize_ui/ui_fs；require_valid_config 检查有限正速率与 retry buffer 1..127 等约束。

build_flit 填 seq8/replay FH并散布 payload、计算格式对应 CRC；check_flit 还原 seq8/replay并校 CRC。LinkStats/Stats 提供方向统计与 observer，日志观察从链路实现直接触发。

### 8.2 `ucie_fdi.h`

这是唯一公共传输边界：FdiFlit、BusinessKind 和 LinkState。内部 Frame/FbMsg 不跨公共 FDI 端口。上游只需满足 payload 大小和 bounded FIFO 语义，不需知道 ACK/NAK 内部结构。

### 8.3 `ucie_link.h` 的五种组件

| 类 | 状态/主要函数 | 上下游与作用 |
|---|---|---|
| TxAdapter | retry_buffer、next_seq、replay cursor/end；sender/feedback/send_one | 收 FDI，保存未 ACK 帧，序列化发送，ACK 回收，NAK/timeout 重放 |
| PhyChannel | pending arrival queue；ingress/egress | 调 BehavioralPhy 损坏 bytes，按 tx/channel/skew/rx pipeline 延迟交对端 |
| RxAdapter | expected_seq、NoRetry/RetryInProgress；run | CRC+seq 验证，交 FDI并 ACK；重复丢弃；错误 NAK |
| FeedbackPath | pending feedback queue；ingress/egress | 对 ACK/NAK 加 feedback UI 延迟，不混作业务 response |
| UcieLink | forward/reverse 两套上述组件；status_thread/fail | 接四个 FDI端口，训练/Active/Degraded/Failed状态 |

Tx sender 优先处理 replay，再新 FDI；retry buffer 满就不给继续吸收。send_one 发 TX_FDI（新帧）、TX_FRAME，等待串行化后写 PHY。ACK 是累计 seq 回收，NAK 从所需 seq 到当前 buffer 尾部重放；无进展 timeout 重发。

Rx 用线 seq8 与 expected_seq 的模 256 差值区分正常、重复和未来帧；retry window≤127避免回绕歧义。只有 CRC 正确且恰为 expected 时才交业务 payload；重复帧不造成重复内存写。

正/反向是两个独立可靠业务通道，reverse seed 变化避免随机流完全一致；feedback 为方向内部 side path。status_thread 在训练结束设 Active，历史 CDR/skew 故障可置 Degraded，watchdog/fail 置 Failed；它不是完整硅片 LTSSM。

### 8.4 `ucie_phy.h`

BehavioralPhy 是普通 C++ 信道函数，由 SystemC PhyChannel 驱动。stripe_bytes 把 byte i 轮转分配到 lane i%lanes，字节内部 MSB-first；NRZ ±1，PAM4 Gray mapping -3/-1/+1/+3。每符号叠 ISI FIR、AWGN和 jitter-induced term，threshold decision后 destripe 回 bytes。

skew 随机抽样，超 deskew depth会制造损坏；extra_flit_error_rate额外翻 bit；统计 symbol/bit errors。observe 以连续坏帧达到阈值触发 CDR lock loss与 relock窗口。这些是行为近似，未模拟模拟电路或真正串行 pin waveform。

### 8.5 独立入口和验证

`ucie_systemc_main.cpp` 创建独立 workload/响应生成、link、watchdog和结果；其固定 memory_delay 是 standalone testbench，不是在线 mem_sim。`ucie_unit_tests.cpp` 验字节、CRC、lane、FDI、状态等组件；scripts/run_tests/run_sweep/run_validation 跑正常、压力、参数扫描和验收记录。

## 9. HETTrace、离线工具和参考 RTL

### 9.1 `libhettrace/include/hettrace`

record.h 定义 64B FileHeader、56B Record、AW/W/B/AR/R、LAST/SYNTH/DMA等flags；不保存 WDATA/RDATA。addrmap.h 从 addrmap.json生成源/区域/时间常量；writer.h header-only，供 SCons/Bazel/Make 各自 include。

TraceWriter Open读取 HETTRACE_DIR/FILTER/FORMAT，写真实 header；BeginWrite输出 AW+W，CompleteWrite输出 B；BeginRead输出 AR，CompleteRead输出 R；Emit/EmitBurst供设备级 W/R投影。Push维护源内 seq、单调时间和统计；Close刷新缓冲并写 meta。

格式有 AXI字段不等于每份记录都是 native signal采样。统一 monitor调用 Open(...,synth=true)，其记录明确是 Packet投影。

### 9.2 `tools/hettrace` 每个文件

| 文件 | 输入/输出及作用 |
|---|---|
| `reader.py` | binary/text → Header/Record流；检查magic/version/record_size、短读/截断，读取meta与discover |
| `addrmap.py` | 生成常量与RegionOf/IsDram/IsTraced/accessors辅助，C++对应为addrmap.h |
| `merge.py` | 多源排序流 → 统一流；key=(tick,src_id,seq)，稳定heap归并 |
| `validate.py` | trace目录 → Issue/SourceSummary；校验时间、seq、地址权限、burst/LAST/ID、meta、观察层和跨源交接 |
| `stats.py` | trace目录 → 带宽窗口、footprint、读写/region、重叠统计；只把W/R算数据 |
| `convert.py` | Records → readwrite/loadstore/memsim等格式；写从W保留mask，读从AR展开保留issue时间；产mapping |
| `cli.py` | argparse → validate/merge/stats/dump/convert；负责filters、ticks-per-cycle、异常退出 |
| `synth.py` | 受控场景 → 合法/故障trace，测试乱序/截断/序号等checker |
| `__main__.py` | `python -m hettrace`入口 |
| `__init__.py` | package声明，不是独立仿真层 |
| `tools/tests/test_tools.py` | reader/merge/stats/validate等工具行为回归 |
| `tools/tests/test_workflow.py` | 地址/源码/转换及离线流程契约回归 |

memsim转换的data/expect零值只表达size占位，HETTrace没有真实payload，所以这条离线路径无法从文件恢复完整写内容。

### 9.3 地址生成与旧配置

`scripts/gen_addrmap.py` 校验源ID、region非重叠、时钟可整数换算、accessor可寻址性、Coral DDR窗口，再同时生成C++与Python。改JSON后须运行生成/--check；`het_system.py`还保留手写常量，也需同步核对。

`vortex_only.py/coralnpu_only.py`用于单设备bring-up；`gem5int/tests/run_*`覆盖host、共享、three_source和negative；`scripts/native_env/native_preflight/upstreams/replay_trace`用于独立开发环境、源检查与旧离线重放，统一部署以根env为准。

### 9.4 workloads

shared_buffer/host_main.c写NPU input、output初值，CTRL启动、轮询状态，核对2*x+1和mailbox checksum；three_source/host_main.cpp使用Vortex2 async队列发上传/launch/read，再启动NPU，最后分别收结果，刻意制造设备时间重叠。

vortex_smoke/kernel.S是裸机小型设备访存；llm_memory/generate_trace.py合成decoder权重/KV/activation等访存形状，run.sh转换并重放，compare_results核对mapping/response和实验指标。它不执行Transformer数值推理，不能报告真实tokens/s。

### 9.5 `storage_chain` 每个源文件

| 文件 | 职责及连接 |
|---|---|
| `rtl/xpu_axi_master.sv` | command→单outstanding AXI4 master，供BFM测试 |
| `rtl/storage_chain_top.sv` | 各AXI字段透明assign，旁接checker与monitor |
| `rtl/axi_subset_checker.sv` | 五通道VALID/payload在READY低时稳定 |
| `rtl/axi_hettrace_monitor.sv` | native握手→HETTrace事件字段，无payload存储 |
| `tb/tb_storage_chain.sv` | memory BFM+scoreboard，覆盖来源、部分WSTRB、ID/LAST/RESP与反压 |
| `Makefile` | Icarus仿真与Verilator lint；不接入gem5执行 |

该目录没有UCIe/controller/DFI实现，monitor还限制单读/单写outstanding与每周期至多一个通道握手，不能将它描述为完整生产链路或AXI VIP。
