# 独立 UCIe–MC RTL 桥

`ucie_mc_bridge` 与 `storage_bridge` 并列。这里的 RTL 独立实现 AoU256/FDI ↔ 新 MC HIF，
不引用、编译或链接 `storage_bridge/rtl`，不连接 RamulatorBackend。两者可以分别构建与维护。

```text
AXI2Flit → UCIe → 250 B FDI
                       ↕
             ucie_mc_bridge_top
      FDI解析 / AoU信用 / AW-W配对
      parent-child表 / 缓存 / 地址排序
      MC信用 / token / pointer调度
      读返回重组 / AoU响应 / FDI组帧
                       ↕
            新 MC HIF（裸引脚）
                       ↕
        未来 MC；验证时使用 tb 行为模型
```

## 当前实现

- 单时钟、AoU256 和 MC256，64 bit 前端地址经范围检查后转换为 40 bit 字节地址。
- 每 RP 每方向独立请求槽；W 可先于 AW；最多 4 KiB、INCR、按 SIZE 对齐且不跨 4 KiB 的请求。
- 数据块就绪后发 MC 命令；一/二个 32 B word；块间流水；部分 mask 使用 RMW。
- LPR/HPR/WR 独立信用、同周期归还与消费守恒，RMW 同时占 LPR 和 WR。
- 53 bit token；19 bit pointer；控制器 pointer 请求驱动写数据；写 stall 保持整拍。
- 无 ready 读返回的预留存储、不同 token 乱序、有效空洞、parent 内重组、同 ID 顺序。
- 相关地址 RAW/WAW 保护、读错误状态、FDI 双向跨帧、AoU信用、最终响应片段退休。
- 未确认 posted write 契约时，生产顶层默认拒绝写并返回 SLVERR，不向 MC 发写命令。
  验证模型显式采用 posted_accept：全部数据交付即承担后续写责任。

源文件、端口、时序与局限详见 [接口与架构](docs/architecture.md)。
本机用例与验证边界见 [验证记录](docs/validation.md)。

## 构建与验证

从主仓库根目录运行：

```bash
# 独立生产顶层 lint（无 testbench、无旧桥）
python3 env/test_ucie_mc_bridge.py --lint

# 全部独立接口/功能用例，测试专用 MC 行为模型
bash env/run_ucie_mc_bridge_validation.sh

# RP2 / RP4；每轮使用新的 results 日期目录
bash env/run_ucie_mc_bridge_validation.sh --planes 2
bash env/run_ucie_mc_bridge_validation.sh --planes 4

# 验证生产默认的 fail-closed 写策略
bash env/run_ucie_mc_bridge_validation.sh --posted-ack 0

# 导出真实顶层的 Verilator 头文件和静态库；不编译 MC 模型
bash env/build_ucie_mc_bridge.sh

# 从独立参数文件导出模型；只编译桥，不加入testbench
bash env/build_ucie_mc_bridge.sh --rtl-config ucie_mc_bridge/profiles/default-rtl.json
```

依赖 Python 3.9+、Verilator 5.x、C++ 编译器、make；不需要安装或链接另一个 SystemC。
`AXI_JOBS=4` 控制构建并行数。`make -C ucie_mc_bridge lint/test` 是同一入口。
实际构建、测试、离线审计与HTML生成器全部在本目录的`tools/`；env中的脚本仅是便利入口。
只交接本目录也可运行`python3 tools/run.py --lint`、`python3 tools/run.py`或
`python3 tools/run.py --build-only`，在父目录建立独立build/results。

生产构建默认 `POSTED_WRITE_ACK=0`。若已声明接收型写确认契约，可显式传 `--posted-ack 1`。
这不代表支持实际 DRAM 服务完成确认。`--case N` 可选定用例，`--output PATH` 指定一个全新结果目录。

构建在 `build/ucie-mc-bridge-*`，按源码、参数和工具版本隔离。结果在
`results/YYYYMMDD-mc-hif-rpN-ackN-rNN/`，日期使用 Asia/Shanghai。

每个用例保存 VCD、完整双向 FDI 帧日志、MC 握手事件、原始统计、离线校验和 `metrics.html`。
独立RTL测试和SystemC适配器均使用1fs时间精度，CSV时间列为time_fs；测试时钟周期为10ns。
根目录 `index.html` 列出本次用例。离线 Python 解码器独立检查帧长度、消息边界、
请求/终止响应守恒及打包 granule，测试台另做逐字节功能记分板和协议断言。
结果文件是当前独立验证入口的报告，尚未合并入原系统结果总索引。

## 未来 MC 接入

生产引脚位于 `rtl/ucie_mc_bridge_top.sv`；源码清单仅为 `rtl/files.f`。
直接替换 testbench 的 MC 一侧即可开始接口集成，不能把 `tb/mc_hif_model.sv` 放进综合网表。

`integration/systemc_fdi_endpoint.hh` 是表示转换适配器：FDI 使用现有 UCIe 的 `FdiFlit` FIFO，
MC 引脚使用 SystemC ports，事务管理全部在 RTL。须绑定所有 MC ports，使用 gem5 原生 SystemC、
统一 1 fs；在 MC 未连接时不能运行闭环，也不会退回 Ramulator。该适配器不自动修改现有
`StorageBridge` 选择器，当前原 CPU/GPU/NPU 运行命令继续使用原路径。
接线和编译方法见 [集成说明](integration/README.md)。

## 契约与验证边界

`profiles/waveform-demo.json` 记录截图/波形之外所采用的测试假设：长度 0/1 对应 1/2 word、
字节地址、mask=1 写、双位优先级 HPR=2，以及 posted write。它是说明性的测试契约，
并非真实 MC 兼容认证；实际 RTL 配置由顶层参数/构建参数决定。
`profiles/default-rtl.json` 是实际参数入口，`--rtl-config` 会校验字段、范围及交叉约束，
传入Verilator并记录到构建manifest。自定义资源、编码或策略可用于生产顶层构建/lint；
当前波形回归模型固定其余几何和编码，仅对RP与posted策略提供矩阵，其他配置须补充对应验证。

`cmd_latency=0`、autopre/criticality 关闭属于测试设置；WRECC 端口完整暴露但相关操作未实现。
真实 MC 仍须确认长度/地址/掩码/优先级/pointer复用/错误时序和写确认责任。
没有逐事务完成通知时，WR credit 或 pointer 返回不能作为实际 DRAM 写完成。

当前无 VPR、独占访问、CDC、热复位、PHY、ECC算法、MC时序/功耗、PPA结论。
RTL 为有界可综合风格；Verilator lint/功能验证不替代目标工艺的综合和 STA。
MC 行为模型只提供可复现的协议与功能验证，所有报告标记 `real_mc_verified=false`。
