# 当前工作区目录职责详解

本说明依据 2026-09-18 的实际目录、构建入口、系统配置和源码检查。与 [09：系统接口解读](09-current-system-walkthrough.md) 配套：09 沿请求解释文件和接口，本篇按目录解释职责、使用范围及维护位置。

扫描包含源码、隐藏配置、本地交接资料、构建与结果目录；不进入 `.git` 内部元数据，不展开目录符号链接，以免重复扫描外部 Bazel 缓存。全部实际目录见 [目录清单 CSV](directory-inventory.csv)，扫描口径见 [统计 JSON](directory-inventory-summary.json)。表中人工说明的目录用于清单匹配，其余深层目录标记为继承最近上级的职责，不宣称逐文件人工审阅。

`integrate_doc/HANDOFF.md`、`integrate_doc/09_migration.md` 在当前机器未分发，接手依据根 README、docs/development.md 和实际本地迁移备份。部分子工程文档保存历史 mem_sim/offline 工作流，不能代替当前 `configs/run_xpu.py`、`env/run_ramulator.sh` 和 `docs/ramulator-integration.md` 的在线系统事实。

## 1. 目录之间怎样配合

```text
env                     准备依赖、构建、运行、验证
 │
 ├─ gem5_new             设备接入真源、ABI、观察器、工作负载
 │   ├─ coralnpu         NPU Chisel/RTL → Verilator 设备库
 │   ├─ vortex-gpu       GPU SimX、runtime → 设备库及kernel
 │   └─ gem5             CPU、DMA、互连、事件队列、原生SystemC/TLM
 │         ↕
 └─ gem5_axi             整机配置、TLM→AXI256、链路装配和内存后端
           ↕
       axi2flit          AXI↔AoU消息↔Flit、credit、AouTarget
           ↕
       ucie-model        双向传输、序号、CRC、replay、反压
           ↕
       gem5_axi          RamulatorBackend + 唯一真实数据backing
           ↕
       ramulator2        实际DRAM调度/命令/服务 + DRAMPower

protocol/include         两端共同使用的AoU帧契约
build、各模块构建目录    上述源码生成的产物
results                  本次执行产生的证据与可视化
docs                     当前维护说明和源码解读
integrate_doc            本地备份、交接与迁移记录
.vscode                  编辑器配置
```

主运行链路的响应沿原路径返回。系统为一个进程、gem5 主事件队列、gem5 原生 SystemC、统一 1fs 时间轴。目录中的独立组件 Makefile/CLI/RTL 回归不自动成为这条链路的一部分。

## 2. 工作区与根文件

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `.vscode/` | VS Code 本地工作区设置；当前 settings.json 将 CMake 源目录指向 ramulator2 | 编辑器辅助，不驱动整机构建，不入 Git |
| `build/` | 系统级 native 库、测试和工作负载产物 | 构建输出，不维护源实现、不入 Git |
| `docs/` | 系统安装、维护、源码归属、后端契约和验收说明 | 文档 |
| `env/` | 统一依赖、构建、执行与验收入口 | 基础设施 |
| `integrate_doc/` | 本地迁移、备份及交接资料 | 保留，不入 Git |
| `results/` | 仿真用例、证据、波形及视图 | 执行输出，不入 Git |
| `protocol/` | 前后两端共享的协议定义 | 源码公共契约 |
| `axi2flit/` | AXI 和 AoU 消息/Flit 的转换 | 互连协议源码 |
| `ucie-model/` | UCIe 双向行为级传输模型 | 链路源码 |
| `gem5/` | CPU/内存/设备/事件/SystemC 仿真框架 | 普通主仓库源码 |
| `gem5_axi/` | 整机接线和 TLM/AXI/后端集成 | 普通主仓库源码 |
| `gem5_new/` | 异构设备接入与观察/工作负载 | 普通主仓库源码 |
| `coralnpu/` | NPU 硬件设计与 RTL 仿真工具 | 普通主仓库源码 |
| `ramulator2/` | DRAM 控制器/行为/功耗 | 普通主仓库源码 |
| `vortex-gpu/` | 外部 GPU 源码和单独构建目录的容器 | 只有其中 vortex 及其递归依赖是外部子模块 |

根目录 `.gitignore` 决定本地输出的排除规则，`.gitmodules` 登记 Vortex 外部子模块，`AGENTS.md` 保存维护约定，`README.md` 为系统说明入口；`.git/` 是主仓库内部版本元数据，不是仿真模块。本地 `.vscode` 的 CMake 操作仅针对所选组件，完整系统仍由 env/build*.sh 构建。

## 3. axi2flit：AXI/AoU协议层

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `axi2flit/doc/` | 技术规格、SoC侧/存储侧接口表及联合仿真设计资料 | 设计依据；历史描述须与当前实现核对 |
| `axi2flit/systemc/` | 转换器、帧编解码、流控和集成模块 | SystemC 实现，在整机内使用 gem5 原生 SystemC |
| `axi2flit/systemc/include/` | AXI类型、AoU消息、credit、RP顺序、流解码、SimpleMem FIFO契约 | 公共头文件；修改可能影响请求端和target端 |
| `axi2flit/systemc/src/` | AXI2Flit、FlitPacker、FlitUnpacker 的实现 | 五通道事务↔业务消息↔逻辑Flit |
| `axi2flit/systemc/integration/` | UcieAouAdapter、AouTarget、SimpleBurstMemory | 逻辑Flit↔FDI FIFO；Target↔完整burst FIFO |
| `axi2flit/systemc/tb/` | 独立模块testbench、激励及scoreboard | 组件验证，不等于实际CPU/GPU/NPU执行 |
| `axi2flit/systemc/scripts/` | 组件测试运行和分析脚本 | 开发辅助 |
| `axi2flit/systemc/doc/` | 组件实现与验证说明 | 文档 |

`integration/aou_target.h` 定义 AouTarget。它收帧后组装完整写 burst，通过 `mem_req` 输出到后端，并从 `mem_rsp` 获取响应再编码返回。它不负责DRAM调度，也不拥有持久目标字节。当前 AXI WDATA/RDATA=256bit、WSTRB=32bit；AoU逻辑帧250B并非250B用户数据，一帧与一笔内存请求也非一一对应。

## 4. ucie-model：双向可靠链路

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `ucie-model/src/` | FDI类型、帧编解码、CRC、UcieLink、行为PHY、standalone主程序及单元测试 | 整机主要复用头文件中的 link/PHY；standalone主程序不作为整机入口 |
| `ucie-model/scripts/` | 独立测试、参数扫描和验证 | 组件链路验证 |
| `ucie-model/tests/` | 外部payload输入、期望输出等固定测试数据 | 测试输入 |
| `ucie-model/results/` | 独立链路测试的输出位置，当前保存LINK_VALIDATION_REPORT.md | 不代表整机验收结果 |

上游/下游是四端 `sc_fifo<FdiFlit>`，两方向各有自己的序号、CRC、retry buffer和ACK/NAK。整机由 AouTarget 服务真实请求；standalone MemoryResponder 的echo/固定延迟只用于链路测试。行为PHY描述传输时间和误差，不是电路级UCIe功耗签核模型。

## 5. protocol：两端共享的帧布局

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `protocol/include/` | aou_format6.h 规定250B逻辑帧与256B物理帧之间的scatter/gather映射 | AXI2Flit与UCIe同时依赖；不能在两边各维护不同版本 |

这里保存跨模块协议契约，不是第三个协议转换器。消息字段主要在 axi2flit，物理帧、序号和CRC处理主要在 ucie-model。

## 6. gem5_axi：整机装配中心

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `gem5_axi/configs/` | run.py定向/CPU配置，run_xpu.py三源配置 | 对象实例化、地址路由、设备库、时钟和后端选择 |
| `gem5_axi/scripts/` | 公共数据/协议检查、Flit解码、backend验证、VCD审计、HTML生成 | 运行后证据分析；包含旧RAM/memsim分支工具 |
| `gem5_axi/tests/` | TargetBackingStore独立契约测试 | 零值、掩码、跨页、高地址及越界无部分写 |
| `gem5_axi/workloads/` | 实际CPU验收程序源码 | 编译成Host CPU执行的binary |
| `gem5_axi/build/` | CPU工作负载等生成binary | 本地构建产物 |
| `gem5_axi/patches/` | 历史masked-write/VCD适配记录 | 当前必要适配已纳入gem5源码，统一构建不再向内部模块应用这些基础补丁 |

大量核心文件直接位于 gem5_axi 根层：Gem5Axi.py/SConscript 定义SimObject和构建；axi_master.* 将TLM转换为真实五通道；aou_backend.*装配链路；ramulator_backend.*拆分、提交、服务和响应；target_backing_store.hh保存唯一真实字节；packet_tester.*产生定向Packet。axi_ram.*、memsim_backend.*保存兼容/历史后端，文件存在不代表当前配置使用它们。

`configs/run.py`为兼容测试默认ram/simple，在线运行必须显式aou/ramulator2；`configs/run_xpu.py`装配aou并默认ramulator2。TLM Bridge64名称不是AXI64bit声明。

## 7. gem5_new：异构接入真源与观察体系

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `gem5_new/gem5int/` | gem5设备、共享配置、观察器、安装和组件运行脚本 | 集成源码真源，不是第二份完整gem5 |
| `gem5_new/gem5int/src/` | 设备、trace和旧内存responder实现 | 源码 |
| `gem5_new/gem5int/src/dev/` | GPU/NPU gem5设备壳统一维护位置 | 修改此处，由install_devices.sh刷新gem5副本 |
| `gem5_new/gem5int/src/dev/coralnpu/` | NPU SimObject、PIO启动/状态、周期step、掩码DMA、延迟完成通知 | NPU ABI↔gem5 Packet |
| `gem5_new/gem5int/src/dev/vortex/` | GPU SimObject、PIO/CP、core token、DMA与完成通知 | SimX ABI↔gem5 Packet |
| `gem5_new/gem5int/src/hettrace/` | HetAxiMonitor，透明目标Packet观察并按requestor分类 | 不拥有数据、不驱动DRAM；输出SYNTH事务记录 |
| `gem5_new/gem5int/src/mem/unified_timing/` | 历史共享sparse功能responder | 当前在线run_xpu.py不实例化，真实目标字节在backing |
| `gem5_new/gem5int/configs/het/` | CPU/cache/device共用创建函数、地址和时钟常量、独立历史配置 | 当前run_xpu.py复用部分helpers，不能把独立main拓扑等同当前系统 |
| `gem5_new/gem5int/tests/` | 独立NPU、GPU、共享与三源运行脚本 | 当前完整验收优先env/run_xpu.sh |
| `gem5_new/gem5int/patches/` | 历史DmaPort byte-enable补丁依据 | 当前gem5已维护对应适配，不由构建重复应用 |
| `gem5_new/coralnpuint/` | CoralNPU C ABI真源、安装脚本及ddr_touch验收kernel | 刷新coralnpu/gem5int构建package |
| `gem5_new/coralnpuint/tests/` | dlopen/C ABI smoke测试 | 库层组件检查 |
| `gem5_new/coralnpuint/patches/` | 历史wrapper、async AXI、native C++规则等适配记录 | 当前CoralNPU源码已内置必要改动，不在构建重新打基础补丁 |
| `gem5_new/vortexint/` | 固定外部Vortex的安装与接入 | GPU适配入口 |
| `gem5_new/vortexint/patches/` | 保存SimX在线接口与runtime包含顺序等外部差异 | 外部必要补丁仍由install.sh幂等维护 |
| `gem5_new/libhettrace/` | C++ trace记录库 | CPU/设备/互连观察共享 |
| `gem5_new/libhettrace/include/hettrace/` | record/writer/addrmap头及格式 | binary trace ABI，不是存储后端 |
| `gem5_new/libhettrace/tests/` | 格式和writer测试 | 组件验证 |
| `gem5_new/tools/hettrace/` | 读取、校验、统计、合并、合成和转换CLI | 观察数据分析；convert memsim属于历史离线投影 |
| `gem5_new/tools/tests/` | trace CLI与工作流测试 | 工具验证 |
| `gem5_new/workloads/` | 异构设备任务与Host工作负载 | 应用/验证层 |
| `gem5_new/workloads/shared_buffer/` | Host↔NPU共享输入、计算、输出校验 | 当前NPU验收使用 |
| `gem5_new/workloads/three_source/` | Host同时协调GPU/NPU并检查结果 | 当前three/three_slow验收使用 |
| `gem5_new/workloads/vortex_smoke/` | GPU接入smoke工作负载 | 组件开发用例 |
| `gem5_new/workloads/llm_memory/` | 合成decoder-LLM-like访存trace与历史离线回放 | 不执行Transformer数值推理，不证明在线tokens/s |
| `gem5_new/storage_chain/` | 小型透明AXI/trace参考边界 | 独立RTL示例，未接入当前完整链路 |
| `gem5_new/storage_chain/rtl/` | AXI passthrough、参考master、subset checker、旁路trace monitor | 非UCIe/MC/DRAM实现 |
| `gem5_new/storage_chain/tb/` | BFM和RTL字段/计数scoreboard | BFM延迟不代表DRAM性能 |
| `gem5_new/scripts/` | 地址图生成、旧环境/preflight/upstream检查和离线回放 | 独立/历史辅助，当前入口为根env |
| `gem5_new/docs/` | 原模块架构、trace规范、设备集成及历史实验说明 | 保存历史设计；当前后端以根docs为准 |
| `gem5_new/docs/results/` | 已保存的历史memory-sweep JSON | 不是本次在线验收目录 |

`gem5_new`名字不表示必须从这里启动另一套gem5。NPU原生AXI128请求经设备壳变成gem5 DMA，再由Master变成AXI256。GPU使用SimX，当前不是Vortex整机RTL。HetAxiMonitor默认16B投影beat与8bit合成ID不等于真实总线宽度或wire ID。

## 8. gem5：事件与计算仿真框架

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `gem5/src/` | 框架C++及Python源码 | 核心源码 |
| `gem5/src/arch/` | ISA指令、译码、寄存器及架构语义 | 当前Host选择X86，其他ISA源码不自动启用 |
| `gem5/src/base/` | 基础类型、日志、统计、时间和公共工具 | 框架公共层 |
| `gem5/src/cpu/` | CPU公共设施与多个CPU模型 | 当前主要用TimingSimpleCPU |
| `gem5/src/cpu/simple/` | 简单CPU取指、执行、timing访存等待 | 当前Host执行模型 |
| `gem5/src/cpu/o3/` | 乱序CPU模型 | 当前验收未选择 |
| `gem5/src/dev/` | 通用设备、PIO、DMA和平台设备 | 含构建刷新的CoralNPU/Vortex副本 |
| `gem5/src/dev/coralnpu/` | 从gem5_new刷新的NPU设备构建副本 | 真源在gem5_new/gem5int/src/dev/coralnpu |
| `gem5/src/dev/vortex/` | 从gem5_new刷新的GPU设备构建副本 | 真源在gem5_new/gem5int/src/dev/vortex |
| `gem5/src/mem/` | Request、Packet、port、XBar、内存与控制器 | 路由本地主存/PIO/目标窗口 |
| `gem5/src/mem/cache/` | cache、tags、替换和预取等 | Host cache层；共享target测试使用uncacheable窗口 |
| `gem5/src/mem/ruby/` | Ruby缓存一致性模型 | 当前统一构建RUBY=n，不提供当前跨设备一致性 |
| `gem5/src/mem/slicc/` | 一致性协议描述编译工具 | Ruby相关 |
| `gem5/src/mem/unified_timing/` | 旧shared responder的构建副本 | 当前online配置不实例化 |
| `gem5/src/sim/` | SimObject、事件、进程/SE、系统、序列化等框架 | 主事件队列与Host执行环境 |
| `gem5/src/python/` | m5对象、配置与运行支持 | 配置装配层 |
| `gem5/src/systemc/` | gem5原生SystemC/TLM实现及桥接 | 当前在线系统时间与process基础 |
| `gem5/src/systemc/core/` | kernel、scheduler、sc_time等 | SystemC调度并入gem5时间轴 |
| `gem5/src/systemc/channel/` | signal、FIFO等channel实现 | 原生SystemC通道 |
| `gem5/src/systemc/dt/` | SystemC数据类型 | 向量/数值类型 |
| `gem5/src/systemc/tlm_bridge/` | Packet↔TLM、四阶段及响应重试 | 目标访问进入Master的边界 |
| `gem5/src/systemc/tlm_core/` | TLM类型、接口和基础设施 | 原生TLM实现 |
| `gem5/src/systemc/tlm_utils/` | TLM便利socket与公共工具 | 原生TLM工具 |
| `gem5/src/systemc/tests/` | 原生SystemC测试 | 组件验证 |
| `gem5/src/gpu-compute/` | gem5上游GPU模型 | 当前GPU选择外部Vortex SimX，不自动使用此模型 |
| `gem5/src/kern/` | 各OS/内核相关支持 | 上游能力，当前主要SE |
| `gem5/src/proto/` | protobuf相关定义 | 上游trace/消息支持 |
| `gem5/src/sst/` | SST集成 | 当前统一入口未选择 |
| `gem5/src/test_objects/` | 框架测试对象 | 测试 |
| `gem5/src/learning_gem5/` | 教学对象示例 | 教学 |
| `gem5/src/doc/` | 源码级文档材料 | 文档 |
| `gem5/src/doxygen/` | API文档生成材料 | 文档 |
| `gem5/configs/` | 上游SE/FS、Ruby、网络等配置示例 | 当前整机入口在gem5_axi/configs |
| `gem5/build_opts/` | 各ISA/构建variant默认选项 | 当前AXI构建基于X86 |
| `gem5/build_tools/` | 代码/参数等构建生成工具 | 构建期 |
| `gem5/site_scons/` | SCons扩展、工具探测和构建辅助 | 构建期 |
| `gem5/build/` | gem5.opt、对象、自动生成参数/调试信息 | 构建产物 |
| `gem5/build/AXI/` | 当前单进程gem5.opt的具体构建variant | 运行binary；不能在生成参数副本修功能源码 |
| `gem5/ext/` | 外部依赖、可选内存/功耗/平台库及头 | 是否使用取决于构建，不按目录存在判断 |
| `gem5/ext/systemc/` | 上游外部SystemC相关内容 | 当前系统使用src/systemc原生实现，不链接第二套SystemC |
| `gem5/ext/drampower/` | gem5上游功耗依赖 | 当前在线功耗接在ramulator2/DRAMPower，不自动走此目录 |
| `gem5/include/gem5/` | 对外公共接口头 | 框架API |
| `gem5/tests/` | 框架、配置、Python与程序测试 | 当前验收不等于全部上游tests通过 |
| `gem5/util/` | m5工具、trace、checkpoint、系统/分析辅助 | 开发工具 |
| `gem5/system/` | 上游系统/平台启动支持 | 当前SE验收未启动完整OS |
| `gem5/docs/` | 上游gem5文档 | 文档 |
| `gem5/.github/` | 上游CI与issue模板 | 开发基础设施 |
| `gem5/.devcontainer/` | 上游开发容器 | 开发环境 |
| `gem5/.vscode/` | 上游编辑器设置 | 编辑器辅助 |

上游提供checkpoint、atomic等框架源码，不意味着当前远端backend已经支持相应整机功能。内部gem5必要适配直接维护源码，不建立内部git仓库、不由构建重复打基础补丁。

## 9. coralnpu：NPU硬件与RTL设备库

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `coralnpu/hdl/` | NPU硬件设计 | 硬件源码 |
| `coralnpu/hdl/chisel/` | Chisel/Scala硬件设计入口 | 经Bazel/firtool生成RTL |
| `coralnpu/hdl/chisel/src/bus/` | AXI等总线结构和公共逻辑 | 硬件互连 |
| `coralnpu/hdl/chisel/src/common/` | 通用硬件模块 | 公共硬件层 |
| `coralnpu/hdl/chisel/src/coralnpu/` | NPU core、AXI桥、TCM和计算集成 | CoreMiniAxi等顶层来源 |
| `coralnpu/hdl/chisel/src/coralnpu/scalar/` | 标量指令和执行模块 | 核内计算 |
| `coralnpu/hdl/chisel/src/coralnpu/float/` | 浮点运算相关模块 | 核内计算 |
| `coralnpu/hdl/chisel/src/coralnpu/rvv/` | RISC-V向量扩展相关设计 | 是否启用由所选顶层参数确定 |
| `coralnpu/hdl/chisel/src/coralnpu/prod/` | 产品/生产配置相关硬件设计 | 顶层配置决定参与范围 |
| `coralnpu/hdl/chisel/src/peripherals/` | 外围设备硬件 | SoC/平台相关 |
| `coralnpu/hdl/chisel/src/soc/` | SoC顶层集成 | 当前设备库不等于完整独立SoC执行 |
| `coralnpu/hdl/verilog/` | 手写/引入Verilog设计 | RTL源码 |
| `coralnpu/hdl/verilog/rvv/` | 向量RTL实现 | 按构建选择 |
| `coralnpu/hw_sim/` | CoreMiniAxi wrapper、AXI/clock primitives、ELF与硬件仿真辅助 | 延迟gem5完成后才向RTL注入R/B |
| `coralnpu/gem5int/` | Bazel的C ABI package及验收kernel规则 | ABI副本由gem5_new/coralnpuint刷新 |
| `coralnpu/gem5int/hettrace/` | 安装的共享trace头副本 | 构建副本 |
| `coralnpu/rules/` | Chisel、Verilator、Cocotb、VCS、链接、依赖等Bazel规则 | 构建工具，不是设备周期逻辑 |
| `coralnpu/rules/lint/` | lint规则和资源 | 静态检查 |
| `coralnpu/toolchain/` | 目标工具链规则、启动代码和包装工具 | NPU工作负载构建 |
| `coralnpu/toolchain/crt/` | bare-metal启动/运行时基础 | kernel入口支持 |
| `coralnpu/toolchain/build_scripts/` | 工具链构建脚本 | 构建辅助 |
| `coralnpu/toolchain/host_clang/` | host clang选择/规则 | 构建辅助 |
| `coralnpu/toolchain/wrappers/` | 编译工具包装 | 构建辅助 |
| `coralnpu/platforms/` | Bazel目标平台约束 | 编译平台选择 |
| `coralnpu/platforms/cpu/` | CPU平台约束 | 构建期 |
| `coralnpu/platforms/os/` | OS平台约束 | 构建期 |
| `coralnpu/lib/` | Chisel Scala依赖聚合及外部RTL资源打包规则 | 当前目录是BUILD规则，不是NPU动态库输出目录 |
| `coralnpu/sw/` | 模型软件接口、优化算子与加载辅助 | 软件层 |
| `coralnpu/sw/coralnpu_sim/` | Python模拟器binding及工具 | 独立开发能力，当前gem5加载C ABI设备库 |
| `coralnpu/sw/opt/` | RVV/ML算子优化 | 算子软件源码 |
| `coralnpu/sw/opt/litert-micro/` | 卷积、全连接、池化等LiteRT Micro优化实现 | 独立算子能力，当前ddr_touch不是完整模型推理 |
| `coralnpu/sw/utils/` | 软件加载辅助 | 开发工具 |
| `coralnpu/examples/` | bare-metal示例工作负载 | 示例 |
| `coralnpu/utils/` | SoC loader等开发辅助 | 工具 |
| `coralnpu/utils/coralnpu_soc_loader/` | SoC加载工具 | 独立平台工具 |
| `coralnpu/coralnpu_test_utils/` | 测试公共设施 | 测试 |
| `coralnpu/tests/` | 多种NPU验证框架 | 组件验证 |
| `coralnpu/tests/cocotb/` | Python驱动RTL验证 | 独立测试 |
| `coralnpu/tests/uvm/` | UVM环境 | 独立验证 |
| `coralnpu/tests/vcs_sim/` | VCS仿真环境 | 独立验证 |
| `coralnpu/tests/verilator_sim/` | Verilator独立仿真与测试 | 当前设备库也使用Verilator生成模型 |
| `coralnpu/tests/systemc/` | 上游独立SystemC测试 | 不向整机引入第二套SystemC |
| `coralnpu/tests/npusim_examples/` | NPU模拟器示例测试 | 独立测试 |
| `coralnpu/third_party/` | RTL、RISC-V、仿真、编译、OS和ML依赖的Bazel规则/资源/补丁 | 许多目录是声明/资源，不等于依赖全源码或整机已启用 |
| `coralnpu/third_party/systemc/` | 上游可选SystemC依赖规则 | 当前native_cpp设备库不链接另一套SystemC |
| `coralnpu/third_party/patches/` | 上游第三方依赖补丁 | 与内部CoralNPU基础适配区分 |
| `coralnpu/third_party/python/` | Python依赖声明与规则 | 构建/测试辅助 |
| `coralnpu/fpga/` | 独立FPGA演示和平台工程 | 当前gem5联合仿真未走此路径 |
| `coralnpu/fpga/ip/` | FPGA IP集成资源 | 独立平台 |
| `coralnpu/fpga/nexus/` | Nexus FPGA平台工程 | 独立平台 |
| `coralnpu/fpga/rtl/` | FPGA平台RTL | 独立平台 |
| `coralnpu/fpga/sw/` | FPGA软件 | 独立平台 |
| `coralnpu/doc/` | 微架构、软件、外设、教程和图片 | 文档 |
| `coralnpu/.github/` | 上游CI | 开发基础设施 |
| `coralnpu/.githooks/` | 开发Git hooks | 开发基础设施 |
| `coralnpu/bazel-bin/` | 指向Bazel生成binary的符号链接 | 当前C ABI库和kernel输出位置 |
| `coralnpu/bazel-out/` | 指向Bazel全部构建输出的符号链接 | 外部缓存，不递归扫描 |
| `coralnpu/bazel-testlogs/` | 指向Bazel测试日志的符号链接 | 外部缓存，不递归扫描 |
| `coralnpu/bazel-coralnpu/` | 指向Bazel execroot的符号链接 | 执行根/外部依赖树，不递归扫描 |

当前native_cpp库使用Verilator C++模型。NPU原生AXI为128bit，整机统一AXI为256bit。NPU内部TCM保留自身内部数据，不是远端target的另一份完整RAM；外存timing请求最终进入同一个backing。当前设备接入尚无重复启动支持。

## 10. ramulator2：时序和功耗后端

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `ramulator2/integration/` | online.h/online.cpp/online.map及check_online.py | 当前ssr_*在线ABI、ISSUE/SERVICE事件和库契约测试 |
| `ramulator2/src/` | 原生C++实现 | 源码 |
| `ramulator2/src/ramulator/base/` | Request、配置、factory、组件、日志和统计 | 所有模型共用基础 |
| `ramulator2/src/ramulator/frontend/` | 外部请求或独立trace/CPU前端 | 当前选External，不在此生成第二个设备执行模型 |
| `ramulator2/src/ramulator/memory_system/` | GenericDRAM、多个channel/controller、send/tick和统计 | 外部child→通道控制器 |
| `ramulator2/src/ramulator/memory_system/channel_mapper/` | 按transaction选择channel及通道内地址 | 默认CacheLineInterleave |
| `ramulator2/src/ramulator/controller/` | 队列、候选选择、实际发命令、完成和plugin观察 | DRAM调度中心 |
| `ramulator2/src/ramulator/controller/impl/` | HBM34及LPDDR控制器实现 | 当前默认HBM34控制器 |
| `ramulator2/src/ramulator/controller/addr_mapper/` | 通道内地址映射为组织坐标 | 与全局channel mapper分层 |
| `ramulator2/src/ramulator/controller/scheduler/` | 调度策略 | 当前FRFCFSRowHit |
| `ramulator2/src/ramulator/controller/refresh/` | 刷新管理 | 当前HBM34PerBankRefresh |
| `ramulator2/src/ramulator/controller/rowpolicy/` | 行开启/关闭策略 | 当前Open |
| `ramulator2/src/ramulator/controller/plugin/` | 实际命令观察与扩展plugin | 包含DRAMPower reporter |
| `ramulator2/src/ramulator/controller/plugin/impl/` | DRAMPower等plugin实现 | 实际issue→功耗统计，不另行调度 |
| `ramulator2/src/ramulator/dram/` | spec/device/node、bank/row状态、ready time及issue更新 | 行为级DRAM状态与约束 |
| `ramulator2/src/ramulator/dram/impl/` | HBM3、HBM4、LPDDR5、LPDDR6编译后标准定义 | 当前默认HBM4，换标准须核对组织/控制器/功耗能力 |
| `ramulator2/src/ramulator/dram/commands/` | 命令相关框架和定义支持 | DRAM命令层 |
| `ramulator2/src/ramulator/translation/` | 可选地址翻译层 | 当前NoTranslation能力；不是gem5页表 |
| `ramulator2/src/ramulator/python/` | C++/Python绑定支持 | 当前在线构建Python bindings关闭 |
| `ramulator2/python/ramulator/` | Python对象、配置、DRAM DSL、codegen、CLI和power.py | 构建/配置能力；power.py是文件 |
| `ramulator2/python/ramulator/dram/` | HBM/LPDDR组织和timing preset/DSL | 生成展开配置和匹配memspec |
| `ramulator2/python/ramulator/controller/` | 控制器Python包装 | 配置层 |
| `ramulator2/python/ramulator/controller_plugin/` | plugin Python包装 | 配置DRAMPower等能力 |
| `ramulator2/python/ramulator/addr_mapper/` | 控制器地址映射配置 | 配置层 |
| `ramulator2/python/ramulator/channel_mapper/` | channel映射配置 | 配置层 |
| `ramulator2/python/ramulator/frontend/` | 前端配置 | 当前External |
| `ramulator2/python/ramulator/memory_system/` | 多通道系统配置 | 当前GenericDRAM |
| `ramulator2/python/ramulator/refresh_manager/` | 刷新配置 | 配置层 |
| `ramulator2/python/ramulator/row_policy/` | 行策略配置 | 配置层 |
| `ramulator2/python/ramulator/scheduler/` | 调度配置 | 配置层 |
| `ramulator2/python/ramulator/translation/` | 翻译配置 | 配置层 |
| `ramulator2/DRAMPower/` | vendored DRAMPower功耗库 | 当前在线DRAM功耗实现 |
| `ramulator2/DRAMPower/src/DRAMPower/` | 各标准memspec、命令状态、core/interface计算 | 当前HBM34对应实现 |
| `ramulator2/DRAMPower/src/cli/` | 功耗库独立CLI | 整机不通过CLI驱动响应 |
| `ramulator2/DRAMPower/lib/` | 功耗库依赖支持 | 库构建 |
| `ramulator2/DRAMPower/cmake/` | CMake辅助 | 构建期 |
| `ramulator2/DRAMPower/tests/` | 功耗库自身测试 | 独立测试 |
| `ramulator2/DRAMPower/examples/` | 独立示例 | 示例 |
| `ramulator2/DRAMPower/benches/` | 性能benchmark | 开发测试 |
| `ramulator2/DRAMPower/docs/` | 库文档 | 文档 |
| `ramulator2/DRAMPower/.github/` | 库CI | 开发基础设施 |
| `ramulator2/ext/` | 原生依赖辅助/缓存位置，如fmt与yaml-cpp | 当前统一构建实际使用锁定用户缓存，不能以此判断实际依赖版本 |
| `ramulator2/examples/` | standalone配置、程序、trace和power spec | 独立示例，不是当前三源系统入口 |
| `ramulator2/examples/bin/` | standalone示例程序资源 | 示例 |
| `ramulator2/examples/traces/` | 示例访存trace | 固定输入 |
| `ramulator2/examples/power_specs/` | 功耗memspec示例 | 在线配置优先生成matching memspec |
| `ramulator2/tests/` | DRAM组件、控制器、吞吐和功耗测试 | 原生/独立验证 |
| `ramulator2/tests/controller_scheduling/` | 控制器调度测试 | 组件验证 |
| `ramulator2/tests/device_timings/` | DRAM命令timing测试 | 组件验证 |
| `ramulator2/tests/latency_throughput/` | 延迟和吞吐实验 | 模型验证 |
| `ramulator2/tests/power/` | 功耗集成测试 | 模型验证 |
| `ramulator2/tests/smoke/` | 快速smoke | 组件验证 |
| `ramulator2/tests/unit_tests/` | 单元测试 | 组件验证 |
| `ramulator2/tests/utils/` | 公共测试工具 | 测试辅助 |
| `ramulator2/resources/gem5_wrappers/` | 上游参考直接接入gem5的wrapper | 当前使用FIFO+ssr_*接入，不用它绕过AXI/UCIe |
| `ramulator2/visualizer/` | Nuxt/WebGL独立trace可视化 | 当前整机静态HTML由gem5_axi/scripts生成 |
| `ramulator2/visualizer/app/` | 页面、组件、store、worker和renderer | 独立前端 |
| `ramulator2/visualizer/server/` | trace加载/live streaming API | 独立服务 |
| `ramulator2/visualizer/public/` | 静态资源 | 独立前端 |
| `ramulator2/.devcontainer/` | 独立开发容器 | 开发环境 |

native库为 libstoragestacked_ramulator2.so，只导出ssr_*，与Vortex旧libramulator.so隔离。ssr_submit不传用户字节；WR callback不直接等于数据完成。实际RD/WR加数据延迟产生SERVICE，gem5_axi的backend在SERVICE读写backing。功耗使用实际命令和状态时间，目前电气参数/活动率为估算，未校准绝对精度，也不统计整机逻辑功耗。

## 11. vortex-gpu：外部GPU模型和构建树

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `vortex-gpu/vortex/` | 固定revision的外部Vortex子模块 | 不擅自更新/reset，必要差异保存于gem5_new/vortexint/patches |
| `vortex-gpu/vxbuild/` | configure生成的独立构建和运行树 | 编译产物和实例化Makefile，不是第二份维护源码 |
| `vortex-gpu/vxbuild/sim/` | 编译后的模拟器库 | 当前sim/simx/libvortex-gem5.so |
| `vortex-gpu/vxbuild/sw/` | runtime及生成配置产物 | 当前Host运行依赖 |
| `vortex-gpu/vxbuild/tests/` | Host示例与device kernel构建产物 | 当前regression/vecadd |
| `vortex-gpu/vortex/sim/` | 多种GPU仿真器 | 当前选择SimX |
| `vortex-gpu/vortex/sim/simx/` | 周期近似C++ GPU模型、core/LSU/cache/访存 | 当前GPU计算执行 |
| `vortex-gpu/vortex/sim/simx/gem5/` | GPU C ABI和在线timing seam | gem5设备壳↔SimX |
| `vortex-gpu/vortex/sim/simx/mem/` | SimX cache/外存边界 | timing callback发出请求，完成后生成MemRsp |
| `vortex-gpu/vortex/sim/simx/hettrace/` | 安装的共享trace头 | 适配构建支持 |
| `vortex-gpu/vortex/sim/common/` | 多模拟器共用CP、ELF、地址/内存等设施 | SimX等复用 |
| `vortex-gpu/vortex/sim/rtlsim/` | Verilator处理器RTL模拟器 | 当前GPU配置未选择 |
| `vortex-gpu/vortex/sim/opaesim/` | OPAE AFU RTL模拟器 | 独立平台 |
| `vortex-gpu/vortex/sim/xrtsim/` | XRT AFU RTL模拟器 | 独立平台 |
| `vortex-gpu/vortex/sw/` | Host runtime、device kernel和共享ABI | 软件栈 |
| `vortex-gpu/vortex/sw/runtime/` | Host API及多种driver backend | 当前使用stub/gem5相关库 |
| `vortex-gpu/vortex/sw/runtime/gem5/` | gem5环境Host driver backend | Host提交GPU任务、PIO/CP控制 |
| `vortex-gpu/vortex/sw/runtime/stub/` | 动态backend分发 | runtime加载 |
| `vortex-gpu/vortex/sw/runtime/common/` | runtime公共内存/管理逻辑 | Host软件层 |
| `vortex-gpu/vortex/sw/runtime/include/` | 公共driver头 | Host API |
| `vortex-gpu/vortex/sw/kernel/` | device端启动、kernel API和intrinsics | kernel构建与执行 |
| `vortex-gpu/vortex/sw/common/` | GPU内部共享ABI和公共工具 | 跨runtime/model共享，非系统AoU格式 |
| `vortex-gpu/vortex/sw/gfx/` | 图形软件emitters | 当前vecadd未使用 |
| `vortex-gpu/vortex/hw/` | GPU RTL、DPI、综合和硬件单元测试 | 当前整机GPU选择SimX，非全RTL |
| `vortex-gpu/vortex/hw/rtl/core/` | GPU core流水线 | 硬件设计 |
| `vortex-gpu/vortex/hw/rtl/cache/` | cache银行、MSHR、flush等 | 硬件设计 |
| `vortex-gpu/vortex/hw/rtl/mem/` | arbiter、adapter和local memory | 硬件设计 |
| `vortex-gpu/vortex/hw/rtl/cp/` | command processor | 硬件设计 |
| `vortex-gpu/vortex/hw/rtl/fpu/` | 浮点单元 | 硬件设计 |
| `vortex-gpu/vortex/hw/rtl/tcu/` | tensor core | 可选硬件能力 |
| `vortex-gpu/vortex/hw/rtl/dxa/` | 异步数据搬运加速器 | 可选硬件能力 |
| `vortex-gpu/vortex/hw/rtl/rtu/` | ray tracing单元 | 可选硬件能力 |
| `vortex-gpu/vortex/hw/rtl/gfx/` | 公共图形逻辑 | 图形能力 |
| `vortex-gpu/vortex/hw/rtl/raster/` | 光栅化 | 图形能力 |
| `vortex-gpu/vortex/hw/rtl/tex/` | 纹理单元 | 图形能力 |
| `vortex-gpu/vortex/hw/rtl/om/` | output merger | 图形能力 |
| `vortex-gpu/vortex/hw/rtl/afu/` | FPGA AFU壳 | 独立平台 |
| `vortex-gpu/vortex/hw/rtl/interfaces/` | 模块间SV接口 | RTL契约 |
| `vortex-gpu/vortex/hw/rtl/libs/` | queue、arbiter、crossbar等通用模块 | RTL公共层 |
| `vortex-gpu/vortex/hw/dpi/` | DPI公共仿真模型 | RTL仿真 |
| `vortex-gpu/vortex/hw/scripts/` | RTL预处理和构建工具 | 开发工具 |
| `vortex-gpu/vortex/hw/syn/` | Quartus/Vivado/Synopsys/Yosys等综合流程 | 独立PPA/平台流程 |
| `vortex-gpu/vortex/hw/unittest/` | 单个RTL模块回归 | 硬件组件测试 |
| `vortex-gpu/vortex/tests/` | kernel、runtime、ISA、应用和图形测试 | 当前整机只运行所选工作负载 |
| `vortex-gpu/vortex/tests/regression/` | Host+kernel回归 | 当前vecadd来源 |
| `vortex-gpu/vortex/tests/regression/vecadd/` | 向量加法Host程序和kernel源码 | 当前GPU/三源验收 |
| `vortex-gpu/vortex/tests/riscv/` | ISA与RISC-V benchmark | 独立测试 |
| `vortex-gpu/vortex/tests/kernel/` | device kernel测试 | 独立测试 |
| `vortex-gpu/vortex/tests/runtime/` | Host driver API测试 | 独立测试 |
| `vortex-gpu/vortex/tests/unittest/` | Host组件测试 | 独立测试 |
| `vortex-gpu/vortex/tests/opencl/` | OpenCL应用/benchmark | 独立能力 |
| `vortex-gpu/vortex/tests/hip/` | HIP应用 | 独立能力 |
| `vortex-gpu/vortex/tests/mpi/` | 多进程应用 | 独立能力 |
| `vortex-gpu/vortex/tests/vulkan/` | Vulkan应用 | 独立能力 |
| `vortex-gpu/vortex/tests/graphics/` | 图形pipeline测试 | 独立能力 |
| `vortex-gpu/vortex/tests/raytracing/` | ray tracing回归 | 独立能力 |
| `vortex-gpu/vortex/third_party/` | 固定外部依赖和本地依赖构建 | 按递归版本锁维护 |
| `vortex-gpu/vortex/third_party/ramulator/` | SimX历史Ramulator依赖 | 不等于根ramulator2在线后端，不能因替代而删除 |
| `vortex-gpu/vortex/third_party/cvfpu/` | 浮点RTL依赖 | 外部依赖 |
| `vortex-gpu/vortex/third_party/hardfloat/` | 浮点RTL库 | 外部依赖 |
| `vortex-gpu/vortex/third_party/softfloat/` | 软件浮点库 | 外部依赖/资源 |
| `vortex-gpu/vortex/third_party/cocogfx/` | 图形公共库 | 外部依赖 |
| `vortex-gpu/vortex/ci/` | configure/build、blackbox、regression和测试目录 | 开发基础设施 |
| `vortex-gpu/vortex/ci/testcases/` | YAML测试catalog | 独立回归 |
| `vortex-gpu/vortex/ci/perf/` | 性能gate与baseline | 不手改golden来掩盖性能变化 |
| `vortex-gpu/vortex/perf/` | 性能分析资源 | 独立分析 |
| `vortex-gpu/vortex/docs/` | 上游架构和开发文档 | 文档 |
| `vortex-gpu/vortex/miscs/` | 杂项资源 | 开发辅助 |
| `vortex-gpu/vortex/trace/` | 当前保存旧Ramulator的ch0/ch1日志 | 独立GPU依赖的调试输出，不是根results内的在线后端命令日志 |
| `vortex-gpu/vortex/.github/` | 上游CI | 开发基础设施 |

GPU device地址通过适配转换到系统目标物理窗口；timing模式BAR由目标后端拥有，PIO负责控制。SimX core可通过token保留多个请求，CP同步式callback由gem5设备壳coroutine等待DMA。不要直接修改vxbuild生成副本代替外部源码与保存补丁。

## 12. env：可重复构建、运行和验收

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `env/tests/` | 源码归属、锁和布局规则测试 | 开发验证 |
| `env/__pycache__/` | Python生成的bytecode缓存 | 自动生成，不维护/提交 |

env多数文件直接在根层：activate.sh选择工具/库/源码路径；bootstrap.sh/bootstrap_xpu.sh准备锁定依赖；build.sh/build_xpu.sh构建native库、设备库和gem5；run_ramulator.sh跑八组CPU/定向，run_xpu.sh跑四组设备/三源；verify_*.py做整组验收；record*.py记录实际库和源码证据；generate_ramulator_config.py生成展开HBM4配置和matching memspec；prepare_*.py/fetch_*.py处理固定依赖；dependency_bundle.py支持打包和恢复。

sources.lock.json锁定外部源码，vendored_sources.json记录gem5/CoralNPU导入来源，ramulator-artifacts.lock.json锁定native依赖，xpu-artifacts.lock.json和xpu-runtime-linux-64.lock锁定设备工具，conda-linux-64.lock锁定基础环境。工具链和Bazel缓存主要位于用户SS_DEPS_ROOT，不因工作区没有toolchains目录而缺失。

run.sh保留RAM/simple兼容验收，run_memsim.sh保存历史可选后端。当前不静默回退memsim；必须取得匹配源码才能选该分支。SS_OFFLINE=1只约束bootstrap下载，不自动证明Bazel离线。

## 13. build和各处生成目录

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `build/ramulator2/` | CMake/Ninja在线native模型构建目录 | 配置、对象、库、CTest和依赖产物 |
| `build/ramulator2/lib/` | 在线native库输出 | libstoragestacked_ramulator2.so |
| `build/ramulator2/CMakeFiles/` | CMake/Ninja生成信息与对象 | 构建产物 |
| `build/ramulator2/_deps/` | FetchContent依赖子构建和生成信息 | 构建产物，实际源码可来自用户锁定缓存 |
| `build/ramulator2/DRAMPower/` | 功耗库子构建 | 构建产物 |
| `build/ramulator2/Testing/` | CTest执行日志 | 测试输出 |
| `build/ramulator2/native-contract/` | 原生ABI契约测试产生的配置与日志 | 测试输出 |
| `build/ramulator2/src/` | 原生源码对应的构建产物 | 非维护真源 |
| `build/ramulator-config-smoke/` | 配置生成smoke的YAML、memspec、metadata | 开发验证输出 |
| `build/xpu/` | 为整机运行暂存NPU kernel | 当前ddr_touch.elf |

其他生成位置包括gem5/build/AXI、gem5_axi/build、vortex-gpu/vxbuild、CoralNPU的Bazel symlink输出，部分第三方构建还位于其自身目录。生成目录不与源码混淆，当前任务未清理任何产物或备份。

## 14. results：证据目录怎样阅读

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `results/acceptance-ramulator2-20260917/` | 已保存八组CPU/定向正式验收 | 不是源码 |
| `results/acceptance-xpu-ramulator2-20260917/` | 已保存NPU/GPU/three/three_slow验收 | 不是源码 |
| `results/acceptance-compat-20260917/` | 原RAM/simple、CPU反馈及observer透明性验收 | 兼容证据 |
| `results/example-directed-20260918-PVEQkB/` | 上一轮实际运行的单源定向示例 | 单源HetTrace显式诊断 |
| `results/ramulator-native-development/` | native模型开发矩阵 | 开发证据，不能直接当正式整组summary |
| `results/ramulator-dual-library-development/` | 新旧Ramulator库共存开发验证 | 符号/模型隔离证据 |
| `results/ramulator2-20260918T015736Z/` | 本机再次通过run_ramulator入口生成的CPU/定向结果目录 | 是否完整通过以目录summary和日志为准 |
| `results/xpu-20260918T015919Z/` | 本机再次通过run_xpu入口生成的设备结果目录 | 是否完整通过以目录summary和日志为准 |

常见子目录名：directed/replay/shallow/held/period_3ns/power_off/cpu/cpu_slow为CPU组；npu/gpu/three/three_slow为设备组；api保存ABI矩阵，environment保存源码/工具/实际库证据，wave_audit保存独立VCD握手审计。每个用例的hettrace保存来源记录，ramulator_data保存DRAM视图分页数据，trace_flits_data/trace_paths_data保存链路视图分块。详细子目录已逐项列入全目录CSV。

每个用例里的run.log/stats.txt看执行，axi_wave.vcd看真实五通道，ucie_soc.csv/ucie_mem.csv看两端完整Flit，ramulator_commands.csv看实际命令，ramulator_bridge.csv看关联与服务，ramulator_final_image.csv看字节，dram_power.json看能量，*_check*.json看校验。HTML必须连同对应_data目录及view_store.js一起复制，优先通过HTTP浏览。

## 15. docs与integrate_doc：当前说明和本地追溯

| 目录 | 职责 | 参与范围 / 维护方式 |
|---|---|---|
| `docs/code-reading/` | 架构、接口、源码职责、文件与目录索引 | 09为当前系统，10为当前目录解读，01—08保留此前分析 |
| `docs/code-reading/inventory/` | 初始静态扫描的symbols/includes等索引 | 静态材料，不是完整运行调用图 |
| `integrate_doc/vendor-migration-20260917T011043Z/` | gem5/CoralNPU普通源码迁移备份、原tar、git指针、inventory和verification | 本地追溯，不分发于Git |
| `integrate_doc/vendor-migration-20260917T011043Z/adaptation-backups/` | 迁移时必要适配的备份 | 保留，不作为构建时自动补丁来源 |

docs/setup.md解释主机与依赖，development.md解释维护与来源，source-layout.md解释内置/外部边界，ramulator-integration.md解释当前后端与验收，handoff-validation.md保存历史memsim验收。integrate_doc根层PROJECT_ANALYSIS_20260917.md是本地分析，current-vendor-migration.txt指向当前迁移备份。提交文档不依赖读者拥有这些本地文件。

## 16. 修改问题应该去哪里

| 目标 | 主要维护位置 | 必须一起核对 |
|---|---|---|
| 增减设备/修改地址/时钟/装配 | gem5_axi/configs、gem5_new/gem5int/configs/het | 路由、backing范围、native容量与工作负载地址 |
| 修改GPU/NPU gem5接入 | gem5_new/gem5int/src/dev | 安装刷新、ABI完成语义、byte-enable和retry |
| 修改NPU C ABI | gem5_new/coralnpuint | coralnpu/gem5int生成副本、wrapper与RTL响应 |
| 修改NPU硬件 | coralnpu/hdl、hw_sim | 顶层参数、Verilator重建、ABI与工作负载 |
| 修改GPU模型接入 | 固定Vortex源码及gem5_new/vortexint/patches | 外部版本、SimX与RTL对应行为、runtime ABI |
| 修改TLM/AXI转换 | gem5_axi/axi_master.* | 合法burst、4KiB边界、五通道、响应和高位掩码 |
| 修改AoU消息/credit/Target | axi2flit/systemc | 双端编解码、RP顺序、FIFO背压 |
| 修改物理帧布局 | protocol/include | AXI2Flit和UCIe两端同时一致 |
| 修改链路时间/replay | ucie-model/src | 两方向、CRC、序号和完整Flit日志 |
| 修改native接入/服务/数据 | gem5_axi/ramulator_backend.*、target_backing_store.hh、ramulator2/integration | token、hazard、SERVICE、读快照、排空 |
| 修改DRAM参数/调度/功耗 | env/generate_ramulator_config.py、ramulator2模型/DRAMPower | 展开配置、matching memspec、实际命令、统计窗口 |
| 修改验收和可视化 | env/verify_*.py、gem5_axi/scripts、gem5_new/tools | 不能通过删检查来掩盖错误；来源投影不是真实AXI波形 |

大型上游内部的ISA、独立平台、测试用例和缓存目录通过全目录CSV继续查找。目录存在不表示当前配置启用该能力；应沿config→构建目标→实例化对象→实际调用追踪。
