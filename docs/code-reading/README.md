# 项目源码解读导航

本解读的初始静态扫描记录日期为 2026-09-17。目标是解释各部分的职责、前后接口、调用关系、数据与时间的所有权，以及整个系统可以研究什么。随后已按用户要求实现在线 Ramulator2 替代；当前代码、配置及运行入口以[在线后端说明](../ramulator-integration.md)为准。01—08 保留替代前的源码分析与方案，文件索引也保留初始扫描基线。

项目的核心是异构计算设备的存储访问联合仿真平台：CPU、Vortex SimX GPU、CoralNPU RTL 的目标访存通过 gem5 原生 TLM、真实 AXI256 五通道、AXI2Flit 和双向 UCIe 行为链路，交给在线内存后端，再把完成响应送回设备，使存储延迟能够影响设备后续执行。程序代码、CPU 栈等仍使用本地 gem5 主存。

## 解读范围与证据

本次索引覆盖 12,899 个主仓库条目，其中按扩展名与文件名规则识别 9,669 个源码文件，约 218 万行源码（不等于实际执行代码量）。gem5、CoralNPU、Ramulator2 包含大量上游实现、平台支持、测试和第三方代码。“全仓文件索引”覆盖本次扫描时主仓库索引中的全部文件；正文对系统集成链路作人工语义解读，对大型上游目录按子系统解释，并深入分析实际接入点。文件索引中的职责提示、符号与依赖是静态提取，不等于每个上游函数均已逐行人工审阅，也不构成完整程序的精确调用图。

本地 `integrate_doc/HANDOFF.md` 和 `integrate_doc/09_migration.md` 未分发，按根目录约定以已提交文档和源码为准。初始工作区没有 Git 修改。

初始扫描时的阅读边界（不代表替代实施后的运行状态）：

- `mem_sim/` 缺失，能够解释 `ss_mem_*` 调用端的契约，无法在本副本阅读内存后端内部实现。
- `vortex-gpu/vortex` 子模块未初始化，`git submodule status --recursive` 的条目以 `-` 开头。可以阅读系统内 Vortex 设备封装、trace tap 和 `simx_online.patch`，无法声称已读完整 Vortex 树。
- 部分 `gem5_new/docs` 与安装脚本注释描述旧离线方案、1 ps 基准或历史补丁流程，必须与当前入口实现区分。
- 初始扫描是静态分析和文档整理；后续替代实施已准备依赖、初始化锁定的 Vortex 子模块并完成构建。新的运行验证见在线后端说明，不能与初始扫描或历史 memsim 验收混用。

## 建议阅读顺序

1. [01：整体架构与运行模式](01-architecture.md)：先认识完整链路、旁路和各目录归属。
2. [02：接口、地址、时间与顺序契约](02-interfaces.md)：解决“上下游具体传什么、何时算完成”。
3. [03：系统集成代码详细解读](03-integration-code.md)：按入口、设备、TLM、AXI、AoU、UCIe、观察工具追踪实现。
4. [04：大型上游源码子系统解读](04-upstream-code.md)：gem5、CoralNPU、Ramulator2、DRAMPower 如何组织，哪些接入当前系统。
5. [05：验证、运行产物与修改影响](05-validation-and-maintenance.md)：证明链路正确的方法、当前限制和修改传播范围。
6. [06：Ramulator2 在线后端可行性评估](06-ramulator2-backend-feasibility.md)：DRAM 行为、功耗、真实数据、写完成语义及联合仿真接入方案。
7. [07：Ramulator2 端口与实施方案](07-ramulator2-port-integration-plan.md)：外侧FIFO、内侧C ABI、唯一backing、服务事件、有界反压、文件改动与跑通顺序。
8. [08：替代 mem_sim 的修改范围与验证思路](08-memsim-to-ramulator2-change-review.md)：必改代码、真实数据与完成语义、功耗口径、三组验证证据及对照方式。
9. [全仓可搜索文件索引](source-index.html)：按目录、职责提示、符号或依赖检索，包含行号。
10. [逐目录 Markdown 索引](inventory/README.md) 与 [CSV 索引](source-index.csv)：方便编辑器阅读和二次分析。

## 先建立五个概念

| 概念 | 在本项目中的含义 |
|---|---|
| Packet | gem5 访存请求/响应，包含地址、命令、数据、Request 属性和发送者状态 |
| TLM payload | SystemC 的事务表示；socket 的 `64` 是绑定类型参数，不限制数据长度，也不表示 AXI 为 64 bit |
| AXI beat | 一次数据通道握手；统一总线宽 32 字节，窄访问通过 SIZE 与 lane 表达 |
| AoU message / Flit | 多条 AXI 通道消息按 5 字节粒度装入 250 字节协议内容，再映射为 256 字节链路物理帧 |
| completion | 真实服务完成；不等同于请求被 FIFO 接收、AXI 地址握手或 TLM `END_REQ` |

一次原始访问可能变为多个 AXI burst、多个 AoU 消息、多个物理帧和多个内存子请求。这些层级的计数不能直接互相替代。
