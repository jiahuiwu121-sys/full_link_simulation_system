# 用 Ramulator2 替代 mem_sim：修改范围与验证思路

本文保存 2026-09-17 实施前的修改分析。随后已按该目标实现在线替代，实际接口、配置、构建与验收见[在线后端说明](../ramulator-integration.md)。[07 端口实施方案](07-ramulator2-port-integration-plan.md)保存 FIFO、原生 ABI、事件及队列的设计依据；本文重点是修改的原因、验证证据的独立性和功耗解释。

## 1. 替代边界

保留 CPU/GPU/NPU → gem5 原生 TLM → AXI256 → AXI2Flit → UCIe → AouTarget 的链路，替换 AouTarget 后面的在线内存服务。响应仍经过原链路返回，真实 DRAM 等待影响设备执行。固定请求轨迹离线回放只用于后端对照，不能替代在线联合仿真。

建议职责划分：

```text
AouTarget.mem_req / mem_rsp（现有事务FIFO）
                  ↕
RamulatorBackend（burst拆分、关联、反压、时间与顺序）
          ↙                           ↘
唯一目标地址 backing                  Ramulator2 原生实例
（实际字节、masked write）             （队列、调度、命令、状态、refresh）
          ↑                           ↓
          └── 实际 RD/WR 后的数据服务事件 ─┘
                                      ↓
                              命令观察器 / DRAMPower
                                      ↓
                            独立数据、时序、能量检查
```

backing 可以由 gem5 管理；不要求 Ramulator2 再保存一份完整 RAM。当前本地主存保存 CPU 程序、栈等，其范围不覆盖远端目标窗口，因此不能直接认为远端数据已经存在。TLM payload 中的临时数据指针也不是持久内存。

## 2. 为跑通系统必须修改的代码

| 位置 | 修改 | 为什么必须改 |
|---|---|---|
| 新 `gem5_axi/ramulator_backend.hh/.cc` | 实现现有 SimpleMemRequest/Response FIFO；burst 拆成 DRAM transaction；建立 parent/child/token；处理队满、完成和错误 | Ramulator2 请求不携带 AXI burst、WSTRB、RP 和真实数据，不能直接替换旧对象 |
| 新目标 backing 模块 | 64bit 地址、按页稀疏存储、掩码更新、读快照；只由目标数据服务访问 | GPU 窗口大；只保留一份权威数据，避免两端副本和绕过链路 |
| 新 `ramulator2/integration/` | 配置/生命周期、提交/重试、step、实际命令/未来完成事件、能力查询、drain 和统计导出 | 建立稳定嵌入边界，不伪造已缺失的 `ss_mem_*` 实现 |
| `ramulator2/src/ramulator/base/request.h`、External 前端 | 默认零的集成 token、带 token 的外部提交入口 | 将实际命令、数据服务、AXI 响应准确关联；AXI ID 可以重复使用，不能单独作为全局标识 |
| controller 只读状态和被动 observer | 获取待完成需求、在实际 `on_issue` 观察命令、生成未来数据服务事件 | posted-write callback 不是总线数据完成；排空还要考虑未来写完成事件 |
| `gem5_axi/aou_backend.cc` | 新显式 ramulator2 分支、FIFO 绑定、统一完成/错误统计、finish 分支 | 当前仅有 memsim/simple；第三分支必须同时修改收尾，避免访问空 simple 对象 |
| `Gem5Axi.py`、`configs/run.py/run_xpu.py` | 配置文件、backing 引用、父/子请求容量、显式选择后端 | XPU 当前固定 `memory_backend='memsim'`，只加 C++ 类不能切换 |
| `gem5_axi/axi_demo.cc` | 将“非 memsim 超过 UINT32_MAX 就失败”改为按后端实际地址能力检查 | 当前 GPU 远端窗口为 5.75GiB，新后端否则会在构造阶段失败 |
| Ramulator2 CMake、`gem5_axi/SConscript` | 构建原生适配库；memsim 源码/头/库变成所选后端的条件依赖 | 当前 SConscript 无条件链接已缺失的 mem_sim，构建仍然失败 |
| `env/activate.sh/bootstrap.sh/build.sh/build_xpu.sh/check_sources.py` | 后端和 CPU/XPU 构建配置；检查所选组件；固定依赖及库路径 | 默认源码检查还要求 mem_sim；CPU 构建也不能无条件要求未初始化的 GPU 子模块 |

原生适配只使用 C++，不创建第二套 SystemC、第二个主事件循环或墙钟工作线程；时间推进由 gem5 原生 SystemC 驱动，统一 1fs。优先最小化 Ramulator2 调度器和 DRAM 标准模型改动，保持模型自身行为，便于对照验证。

这些参数是能力契约的一部分：目标范围和 DRAM 组织容量、transaction 大小、有效时钟、读写终端延迟、队列容量。以现有源码解析的示例 HBM4 配置为例，transaction=32B，内部 tick=250ps；每 controller 可映射 1GiB，2 controller 可以覆盖当前 CPU/NPU 的 768MiB 目标窗口，而保留 GPU 地址孔洞时需要能够覆盖 5.75GiB 的配置。具体推导和配置见 07 §11.1；这只是静态解析结果。

## 3. 完成、真实数据与功耗的关键契约

FIFO 接受表示进入后端，不表示访问完成。正确事件顺序是请求接受 → child 提交 → 实际 RD/WR 发出 → 数据服务 → 数据更新/快照 → parent 全部完成 → 响应返回。

当前 ControllerBase 在 WR 退休时执行写 callback，并且同地址写可能合并、读可能从待写队列转发。因此，不能直接把 callback 翻译成 AXI B，或把每个 callback 都计成一次 DRAM WR。建议由实际终端命令驱动服务事件：RD issue + 解析后的 read_latency，WR issue + write_latency；不把 nWR 写恢复约束当作写数据完成延迟。

第一版可对同一 DRAM transaction 串行化 child，以避免转发/合并改变字节语义；不同 transaction 仍可并发。这个保守策略会影响性能，必须记录为桥接策略。以后放开时，需要明确映射转发/合并事件并重新验证，不能仅删除一个锁。

masked write 在服务时更新 backing；读在服务时保存快照，后续响应阻塞不能改变已经完成的读结果。完整验证一个 burst 后再提交任何会修改数据的 child，避免越界请求造成部分写入。队列必须有界、满时保留原请求并重试，不能丢弃，也不能每次重试产生新 token。

功耗从实际命令和状态时间计算，不从 AXI 请求次数或 callback 次数推算。ACT/PRE/RD/WR/REF、bank 状态驻留、维护命令和统计截止时间都要进入功耗模型；无业务请求时也可能有背景和 refresh 能量。

第一版可使用现有 HBM34PowerModel 的固定活动率估算。当前 `dqRate/tsvRate=0.5`，模型元数据为 `absoluteAccuracyValidated=False`，并含估算电流参数；HBM34 的 `doInterfaceCommandImpl` 为空。因此仅把真实数据传入请求，不会自动得到逐数据位精确的 HBM 接口能耗。

以后如要数据相关功耗，应在实际数据服务顺序上生成 DQ/TSV 活动信息，并匹配预充、突发、掩码和模型能量口径。单次“旧单元值 XOR 新单元值”或 WSTRB 有效字节比例不能直接代表整个总线的翻转与总能量。模型若已经把读写外部链路电流计入 IDD4，再叠加同一部分接口能量会重复计费。

报告应分别给能量 E、共同时间窗口 T、平均功率 E/T、各 channel 及不重叠的能量分项，并记录参数来源。DRAMPower 的相关接口项不等于完整内存控制器逻辑功耗，也不覆盖 CPU/GPU/NPU、AXI 和 UCIe 整个系统。

## 4. 为验证目的必须同步修改的工具

| 位置 | 修改和验证目标 |
|---|---|
| 新 `env/run_ramulator.sh` 与后端 checker | 独立结果目录；真实字节、token 因果链、实际命令、服务事件、drain、功耗产物 |
| `env/run_xpu.sh/verify_xpu.py` | 去掉选择 ramulator2 时无条件执行的 memsim API/ctest；保留设备结果、完整链路、等待反馈验证 |
| 新/调整 `verify_ramulator.py` | 原生 ABI、队满重试、掩码、跨粒度、同址依赖、高地址、响应堵塞、refresh、结束时未来事件 |
| `env/record.py/record_xpu.py` | 记录实际 Ramulator2/DRAMPower/DRAMUtils、库哈希、展开配置、memspec、工具链与真实加载依赖；不要求缺失 mem_sim |
| viewer 与统一汇总 | 显示实际命令和 backing 服务；保留 AXI 五通道 VCD 和两端带时间戳的完整 raw Flit |

原 `check_memsim.py` 要求 memsim 文件、behavioral PHY 和 DFI 数据，不能通过把 Ramulator 输出改名让它“通过”。原 `verify_xpu.py` 固定读 `memsim_check/memsim_core`，且慢用例检查 memsim period×4，这些应改成所选后端的真实能力和统计。

`check.py`、`check_aou.py`、`inspect_link.py`、波形审计承担的公共链路验证继续保留；修改后端摘要契约时审查对应断言。新 checker 使用模型实际提供的命令/服务证据，不宣称具有原 DFI pin 级验证粒度。

记录文件不能只保存 preset 名称：要保存展开组织、timing、地址映射、调度/refresh/row policy、桥接顺序、统计窗口和能耗假设。若库通过 dlopen 加载，主程序 ldd 不一定列出它，应单独审计适配库，确认没有引入第二套 SystemC。

## 5. “不同角度辅助验证”应建立三组证据

**功能证据**：独立 scoreboard 从 AXI 有效 WDATA/WSTRB 和初始内存重建期望字节，比较请求 Flit 解码、写服务日志、读响应和设备计算结果。scoreboard 不调用 backing 的相同读写实现，否则相同错误可能相互抵消。

**时序证据**：从实际已发命令独立检查 bank 状态和配置中相关时序约束，再检查各层因果时间及在途请求守恒。检查器不能只是调用同一调度器的可发命令函数。改变 DRAM timing/queue 后，观察 AXI 等待、设备停顿和任务完成时间，证明闭环反馈。

**能耗证据**：检查命令数量/驻留时间与能耗分项解释是否对应；每 channel 汇总一致，E/T 使用相同窗口，维护和背景能量未遗漏。用可手工解释的小用例检查：空闲窗口、同行连续访问、换行访问、固定读写模式。模型参数合理性及绝对值需要外部数据校准，不能靠内部守恒证明。

这三组证据不全部独立：DRAMPower 消费 Ramulator2 的实际命令，因此它能帮助发现命令漏记、能量重复计数和时间口径错误，但不能单独证明 Ramulator2 的时序规则正确。即使功耗计算自身正确，错误命令轨迹也可能产生看似合理的功耗。

开启/关闭 observer 和 power 应使相同确定性用例的 AXI、Flit、命令顺序与退出 tick 一致；观察模块只增加报告，不改变调度。为检查器加入有针对性的负例，如篡改一个 mask、删除一次完成事件、违反一个命令间隔、重复计入一项能量，确认它能发现对应错误。

## 6. 与原后端比较以及实施顺序

比较分成两层。固定归一化请求流用于隔离后端差异：明确有效地址、大小、到达时间、组织、映射和策略，比较命令、延迟、吞吐及能量。完整在线用例则比较应用结果、等待和端到端性能；后端变慢会改变 CPU polling、设备交错和后续请求到达，不应要求全部轨迹、命令数量或退出时间完全一致。

同名 HBM4 不代表相同参数和控制器。若只有历史 memsim 结果而缺少匹配源码/配置，只能分析可追溯部分，不能称为严格同条件双模型验收。慢内存也不必使所有用例平均功率或总能量单调变化：命令数、背景时长、频率与活动率都可能变。

建议依次完成：

1. 原生适配和命令/服务/功耗小用例，验证 ABI、时间和排空。
2. 新 backend 的字节/掩码/同址/反压测试，接入 AoU 定向用例并保留公共链路审计。
3. CPU 正确性及慢内存反馈，再接 NPU、GPU 高地址和三源在线用例。
4. 固定流后端对照、功耗参数敏感性和观察器透明性；最后再优化同址并发或数据活动模型。

第一阶段交付标准是在线运行、真实数据、实际命令和可解释估算能耗均能追溯。第二阶段再提高活动率模型和参数校准精度。本文中的“当前”“建议”描述实施前状态；后续实际实现采用直接向 memory system 提交带 token 的请求，未修改 External 前端接口，运行证据见在线后端说明。
