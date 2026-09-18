# 在线 Ramulator2 联合仿真

系统默认使用显式在线 Ramulator2 后端。CPU / Vortex SimX GPU / CoralNPU RTL 的目标请求经过 gem5 原生 TLM、AXI256、AXI2Flit、双向 UCIe 和 AouTarget，交给 RamulatorBackend；完成响应沿原链路返回。程序、栈和普通 CPU 页面仍在本地主存。

```text
CPU / Vortex GPU / CoralNPU
            ↕ gem5 Packet / 原生 TLM
         AXI256 五通道
            ↕ AXI2Flit / 双向 UCIe
          AouTarget
            ↕ SimpleMemRequest / SimpleMemResponse FIFO
       RamulatorBackend
        ↙              ↘ ssr_* C ABI
唯一真实数据 backing    Ramulator2 队列 / 调度 / DRAM 状态
        ↑              ↓ 实际 ACT / PRE / RD / WR / REF
        └── RD/WR 数据服务事件          DRAMPower
```

## 实际代码与接口

| 代码 | 职责与连接 |
|---|---|
| [`aou_target.h`](../axi2flit/systemc/integration/aou_target.h) | `AouTarget` 的定义；恢复 AXI burst，发送 `mem_req`，从 `mem_rsp` 构造返回 AoU 消息 |
| [`simple_mem_if.h`](../axi2flit/systemc/include/simple_mem_if.h) | 保留的 FIFO 事务类型；请求含 AXI 地址属性、RP、写 beat/掩码，响应含 ID/RP、状态、读 beat |
| [`aou_backend.cc`](../gem5_axi/aou_backend.cc) | 装配两端 AXI2Flit/UCIe、AouTarget 和 FIFO；显式选择新 backend，并在结束时汇总、排空 |
| [`ramulator_backend.hh`](../gem5_axi/ramulator_backend.hh)、[`.cc`](../gem5_axi/ramulator_backend.cc) | SystemC 桥；验证 parent、拆分 child、保留 token、反压重试、hazard 排序、定时推进与响应 |
| [`target_backing_store.hh`](../gem5_axi/target_backing_store.hh) | 唯一目标数据存储；64bit 相对地址、零初始化稀疏页、masked write 和最终内存导出 |
| [`online.h`](../ramulator2/integration/online.h)、[`online.cpp`](../ramulator2/integration/online.cpp) | 稳定 C ABI；模型能力查询、带 token 的原生提交、真实命令 observer、未来数据服务与功耗导出 |
| [`controller_base.cpp`](../ramulator2/src/ramulator/controller/controller_base.cpp) | 在原生实际 issue 后调用被动 observer；只读检查需求是否排空，调度算法继续由原生模型执行 |
| [`generate_ramulator_config.py`](../env/generate_ramulator_config.py) | CPU/XPU 共用的配置生成与参数检查，输出匹配的 DRAM timing 和 power memspec |
| [`check_ramulator.py`](../gem5_axi/scripts/check_ramulator.py) | 从 AXI/Flit、服务和命令证据独立校验数据、因果、时序与功耗口径 |

原生 ABI 的 `ssr_create/get_info/submit/step/poll_event/is_idle/finish/destroy` 分别管理实例、查询能力、提交 child、推进一个 native tick、取事件、查询排空、导出最终统计和销毁。`submit` 返回 1 表示已接收、0 表示反压、-1 表示错误；错误说明通过 `ssr_error` 获取。每次 step 后必须 poll 完全部事件再推进，ISSUE 事件表示真实命令，SERVICE 事件表示数据可以更新/读取；维护命令的 token 为 0。External 前端用于模型生命周期和统计连接，带 token 请求直接交给 memory system，不更改其既有前端接口。

## 构建和运行

先安装 [主机基础工具](setup.md#1-主机条件)。仅 CPU 与定向测试：

```bash
bash env/bootstrap.sh
bash env/build.sh
bash env/run_ramulator.sh results/acceptance-ramulator2
```

GPU / NPU / 三源：

```bash
git submodule update --init --recursive vortex-gpu/vortex
bash env/bootstrap_xpu.sh
bash env/build_xpu.sh
bash env/run_xpu.sh results/acceptance-xpu-ramulator2
```

结果目录必须尚不存在。运行脚本显式关闭 GDB listener，保留 AXI 五通道 VCD、两端带时间戳的完整 raw Flit、数据检查及原生验收报告。`summary.json` 只有在整组验证成功后才生成。

`SS_MEMORY_BACKEND` 默认 `ramulator2`。历史 `memsim` 分支需要另行取得匹配源码，设置 `SS_MEMORY_BACKEND=memsim` 构建后才可选择；未构建或配置错误时失败，不自动退回 simple。`env/run.sh` 保留旧 RAM/simple 兼容验收，`env/run_memsim.sh` 是历史 memsim 专用入口。

主工具链由 explicit lock 固定。原生模型用 C++20，gem5 通过 C ABI 调用；全系统只使用 gem5 原生 SystemC、主事件队列和 1fs。`env/ramulator-artifacts.lock.json` 固定 yaml-cpp 0.9.0、fmt 10.2.1、DRAMUtils 1.16.0 和 nlohmann_json 3.11.3 的源码压缩包 SHA256；bootstrap 准备缓存，build 不下载这些依赖。`SS_OFFLINE=1` 约束 bootstrap；Bazel 离线性需要单独确认。

在线原生库为 `build/ramulator2/lib/libstoragestacked_ramulator2.so`，只导出 `ssr_*`。它与 Vortex 内部另一版 `libramulator.so` 使用不同 SONAME，隐藏 C++ 符号以避免同一进程内模型冲突。Vortex 内部模型和锁定版本不因本次替代而更新。

本次还修复了首次 XPU 构建遇到的主机适配问题：现代主机的 Vortex LLVM 使用配套的主机 loader/libc，避免私有 glibc 与主机 libm 混用；Vortex host runtime 与 vecadd 显式使用锁定的 GCC；`runtime_assert_header.patch` 调整 `<cassert>` 的包含顺序，避免上游工具头的宏与锁定 sysroot 冲突。外部适配保存为系统内补丁，子模块 revision 保持锁文件版本。这些改动用于构建兼容，不修改 DRAM 时序或设备计算算法。

## 配置

定向与 CPU 配置仍保留历史 ram/simple 默认值，以兼容原脚本。在线访问必须显式选择：

```bash
source env/activate.sh
mkdir -p results/custom-ramulator2
"$AXI_GEM5_BIN" --listener-mode=off -d results/custom-ramulator2 \
  gem5_axi/configs/run.py --mode tester --backend aou --memory-backend ramulator2
```

XPU 配置默认选择 ramulator2。两种配置共用参数：

| 参数 | 默认/含义 |
|---|---|
| `--ramulator-config` | 可选完整展开的 External 配置；未提供时生成 HBM4 |
| `--ramulator-channels` | CPU/NPU 默认 2，启用 GPU 默认 8；必须是 2 的幂 |
| `--ramulator-queue` | 每 controller read/write queue 各 8，生成配置时使用 |
| `--ramulator-slots` | 8 个已接收 AXI parent burst |
| `--ramulator-children` | 32 个在途 DRAM child |
| `--ramulator-response-hold` | 0；可增加响应等待 tick，测试反压 |
| `--ramulator-scale` | 1；生成配套慢时钟/timing/memspec 的受控实验，验收使用 4 |
| `--ramulator-no-power` | 不创建功耗 plugin，验证观察透明性 |

默认 HBM4_32Gb_8Hi / HBM4_8000Mbps 配置使用 32B transaction、250ps 内部 tick、FRFCFSRowHit、Open row policy、HBM34PerBankRefresh、RoBaRaCoCh 和 CacheLineInterleave。单 controller 可映射 1GiB；运行时验证组织容量覆盖完整目标窗口。`run.py` 的定向/独立 CPU 后端窗口为 8KiB，bridge 的 16KiB 路由范围包含越界测试地址；`run_xpu.py` 未启用 GPU 时后端窗口为 768MiB，启用 GPU 时连同地址孔洞为 5.75GiB。

自定义配置要完整展开，External 和 memory_system clock_ratio 必须为 1；当前嵌入能力要求 CacheLineInterleave、同容量/周期/transaction/数据延迟的 ControllerBase 控制器及有效 read/write_latency。自定义配置决定通道、功耗与时序，不叠加自动 scale/no-power/channels。原生库查询实际参数，不根据 preset 名称猜测容量和延迟。

当前嵌入 transaction 必须是 2 的幂，目标 base/size 必须按 transaction 对齐；不满足能力契约的其他标准配置会明确拒绝，需要单独适配映射与窗口。

也可独立生成配置：

```bash
source env/activate.sh
"$AXI_PYTHON" env/generate_ramulator_config.py build/custom-hbm4 --channels 8 --queue 8
```

生成的是原生 YAML parser 可读的 JSON 配置，避免路径引号歧义。同目录保存 memspec 和配置哈希。scale 保留 CK 计数并修改周期/速率，配套重新生成 memspec；这是可重复的时钟敏感性实验，并非经独立校准的新 JEDEC preset。

## 数据和完成语义

`AouTarget.mem_req/mem_rsp` 的现有 SimpleMemRequest/Response FIFO 不变。RamulatorBackend 验证完整 AXI burst，再按 transaction 边界拆分；parent 保存有效字节与 WSTRB，child 携带唯一 token 和对齐后的相对地址。原生实例不保存用户字节。

目标 backing 使用 64 位相对地址和零初始化稀疏 4KiB 页面，是唯一持久字节副本；不会接入额外 RequestPort 或允许设备绕过链路。临时 burst 与读快照有界。

DRAM 队列接受不是完成。被动 observer 观察真实 `on_issue`，RD/WR 分别在实际命令之后加模型 read/write_latency 才产生服务事件；写服务执行 masked write，读服务保存快照。posted-write callback 不直接变成 AXI B。完整 parent 完成后才进入响应 FIFO。

本机定向验收的实例：token=1 在 cycle 283 发出实际 WR，cycle 307 才执行数据服务，间隔为 24×250ps=6ns；token=92 的 RD 从 cycle 11147 到数据服务 cycle 11191，间隔为 44×250ps=11ns。桥接日志保留 parent、token 和物理地址，命令日志保留实际组织坐标，因此可以追溯从 AXI burst 到 DRAM 命令再到返回响应的全过程。

首版按 DRAM transaction 保留访问顺序，并在 parent 接受时预留所有 child，防止更年轻请求越过尚未提交的早期 child。同址串行化避免原生写合并和读转发改变字节语义；不同 transaction 可并发。parent 响应使用全局 FIFO 顺序，强于同 ID 顺序要求。这些策略应纳入性能结果解释。

原生模型持续按自身周期推进，响应阻塞期间仍统计状态时间与刷新；没有独立线程或私自推进全局时间。finish 要求 FIFO、parent、child、hazard 和未来数据服务事件全部排空，不在 finish 内额外 tick。

## 验证与结果

每次运行自动输出分模块统计、全链路汇总、请求/Flit来源关联和DRAM功耗时间序列，保留原生统计名称/单位。文件与窗口口径见[实验指标说明](experiment-metrics.md)。

| 产物 | 内容 |
|---|---|
| `ramulator_bridge.csv` | 接受、提交/重试、issue、服务、返回；AXI ID/RP、parent/token、字节和 mask |
| `ramulator_commands.csv` | 实际命令、cycle/1fs tick、地址和组织坐标；维护 token=0 |
| `ramulator_final_image.csv` | backing 已分配页面的最终字节；未分配部分为零 |
| `ramulator_config.yaml`、`ramulator_model.json` | 原始展开配置、运行时实际组织与命令时序规则 |
| `ramulator_stats.yaml` | 原生性能统计 |
| `dram_power.json` | 每 channel、汇总能量、时间与平均功率 |
| `ramulator_*_summary.json`、`ramulator_check.json` | 计数守恒、排空、数据、时序和能量检查 |
| `ramulator.html`、`ramulator_data/` | 按页加载的命令、服务和最终内存视图 |

公共 AXI/TLM、AoU、raw Flit 解码与 VCD 审计继续执行。新 checker 独立重建字节 reference，检查服务快照、最终内存、各层时间因果、实际命令状态/约束和能量汇总；没有调用原生调度器判断时序。负例验证掩码、未知服务、提前响应、读字节、命令时间、最终内存、重复能量和 ACT→RD 非法间隔能被拒绝。

原生 CTest 包含 online_contract 和 target_backing_contract：实际命令与读写服务延迟、容量/队满、结束排空、刷新、功耗开关透明性、慢时钟严格 timebase、稀疏零值/掩码/跨页/高地址不 alias。CPU 套件运行定向、replay、浅队列、响应保留、异步 3ns AXI、功耗关闭、CPU 与慢内存八组；XPU 套件运行 NPU、GPU、三源与慢内存四组。

通过本机 HTTP 服务查看 HTML，例如 `python3 -m http.server 8000 --directory results`。交接复制整个用例目录，包含各视图数据目录和 view_store.js。

## 模型范围

DRAMPower 从真实命令和状态时间计算估算能耗，包含背景和 refresh。HBM 电气参数有估算项和固定活动率，absoluteAccuracyValidated=False；真实 backing 数据不会自动转化为逐位精确 DQ/TSV 活动。结果不包含 XPU、AXI/UCIe、完整控制器逻辑功耗，也不提供 DFI pin 波形。

功耗窗口为时间零至最后一个完整 native tick，使用该窗口的 E/T。backend 摘要同时记录 native_end_tick_fs 和 simulation_end_tick_fs；最后不足一个 native 周期的时间未纳入功耗，checker 验证差值小于周期。每 channel 的原始 memspec 另存为 ramulator_memspec_channel_N.json，便于追溯估算参数。

DRAMPower 消费同一命令流，可以检查能量和时间口径，不构成独立第二套时序模拟器。通用 functional/atomic、checkpoint、跨设备缓存一致性、NPU 重复启动仍未实现。历史 memsim 数值不能在缺少匹配源码、配置和模型参数时当作严格同条件基准。

## 2026-09-17 本机验收

本次重新完成 gem5/XPU 构建并执行在线替代后的仿真，三个入口均正常退出，汇总 `passed=true`：

| 入口与本机报告 | 实际通过范围 |
|---|---|
| [`run_ramulator.sh`](../env/run_ramulator.sh) / [CPU 汇总](../results/acceptance-ramulator2-20260917/summary.json) | 八组定向/CPU 用例、两项原生 CTest、API 矩阵、八个后端负例、AXI256/Flit 检查与八组独立 VCD 审计 |
| [`run_xpu.sh`](../env/run_xpu.sh) / [XPU 汇总](../results/acceptance-xpu-ramulator2-20260917/summary.json) | NPU、GPU、三源、慢三源四组；设备结果、真实数据、命令时序、功耗、来源轨迹与四组独立 VCD 审计 |
| [`run.sh`](../env/run.sh) / [兼容汇总](../results/acceptance-compat-20260917/summary.json) | 原 AXI RAM 与 AoU/simple 链路、ID 复用、replay、观察透明性及 CPU 延迟反馈 |

两项 CTest 为 `target_backing_contract` 和 `online_contract`，均通过。原生库仅导出九个 `ssr_*` 符号，SystemC 审计通过；Vortex revision 保持 `d76b7f24e658867ab57e3942d7c648c3e6af072d`。依赖锁、实际源码/库/可执行文件哈希和加载依赖保存在各结果根目录的 `environment/`。

慢配置使用配套 timing/memspec，将 native 周期从 250ps 改为 1ns。独立 CPU 的 452 次目标访问及指令数一致，退出时间从 107.8855µs 增至 122.5475µs。三源的 NPU 访问序列及 GPU core 读写计数一致，设备结果保持正确，反馈如下：

| 三源指标 | 正常配置 | 慢配置 |
|---|---:|---:|
| NPU 执行周期 | 5010 | 6451 |
| GPU 执行周期 | 654 | 1146 |
| NPU 平均目标访存往返时间 | 63.434ns | 85.855ns |
| GPU 平均目标访存往返时间 | 127.303ns | 147.751ns |
| 主机任务完成时间 | 3490.4515µs | 3651.7825µs |

四组 XPU 的实际 DRAM 功耗导出与独立汇总检查均通过：

| 用例 | AXI parent / DRAM child | DRAM 估算能量 | 平均功率 |
|---|---:|---:|---:|
| NPU | 320 / 320 | 0.045452mJ | 0.243616W |
| GPU | 9459 / 9673 | 3.402465mJ | 0.969817W |
| 三源 | 9739 / 9949 | 3.385460mJ | 0.969920W |
| 慢三源 | 9739 / 9949 | 3.541857mJ | 0.969898W |

功耗窗口包含主机准备阶段的 DRAM 背景与 refresh，不能当作只含设备 kernel 的动态能量。正常三源与慢三源分别完成 934,695 和 296,028 次实际命令时序比较；刷新次数会随受控时钟实验变化，能量或平均功率不要求按 scale 成比例变化。

功耗关闭用例与正常定向用例的 AXI、AoU、两端 UCIe、命令、服务、最终内存及退出时间完全一致。生成的 `ramulator.html` 与分页 JSON 已通过本机 HTTP 加载检查。本机结果与构建产物不入 Git，新机器按上述入口运行生成新的独立目录；这里的数字不是历史 memsim 对照或绝对功耗校准结果。
