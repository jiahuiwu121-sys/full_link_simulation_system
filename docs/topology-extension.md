# 第二阶段：可配置拓扑扩展

第二阶段把原来的单条 `TLM → AXI256 → AXI2Flit → UCIe → AouTarget → Ramulator2`
扩展为可重复实例化的并行拓扑。一个模块包含一组完整且独立的 AXI、协议桥、UCIe 链路、
AoU 目标端和内存节点；模块之间通过 gem5 地址路由器按条带分流。每个地址只归属于一个
memory node，因此真实数据只有一个所有者，不会在多个 backing 中产生副本。
地址路由器采用非一致性交叉开关，宽度设置为 `AXI字节宽度 × 模块数`，内部路由延迟为零；
它只负责地址分流，不会在被研究的 AXI/UCIe 路径之前引入额外带宽瓶颈。

```text
CPU / GPU / NPU
        |
  gem5 SystemXBar
        |
  address-interleave NoncoherentXBar
   +----+-------------------+
   |                        |
TLM[0]                   TLM[N-1]
   |                        |
AXI[0]                   AXI[N-1]
   |                        |
AXI2Flit + UCIe[0]       AXI2Flit + UCIe[N-1]
   |                        |
AouTarget[0]             AouTarget[N-1]
   |                        |
Ramulator/backing[0]     Ramulator/backing[N-1]
```

## 配置契约

拓扑文件采用 `storagestacked.topology.v1` JSON。`module_count` 必须是 1、2、4、8……，
这是因为 gem5 地址范围用二进制交织位选择目标。`stripe_bytes` 必须是二次幂、至少一个
AXI beat，并且不能小于工作负载可能产生的单个目标请求，否则一个请求可能跨越两个目标
地址范围。受控 traffic 模式还要求请求大小整除条带大小；CPU/GPU/NPU 的目标请求必须由
场景配置保证不跨条带，独立拓扑验收会逐请求检查这一条件。

`axi.data_width_bits` 必须与构建位宽相同；单模块的 `routing.policy` 必须为 `single`，多模块
必须为 `address_interleave`。`modules` 数量、模块名唯一性和这些字段都会在 gem5 实例化前
校验，错误配置不会进入仿真。

每个 `modules[]` 项可配置：

- `ucie.lanes`：该物理模块的 lane 数；
- `ucie.rate_gtps`：每 lane 传输率；
- `ucie.modulation`：`NRZ` 或 `PAM4`；
- `memory.standard`：自动生成 External 配置的内存档案，可选 `HBM3`、`HBM3E`、`HBM4`、
  `LPDDR5`、`LPDDR6`；
- `memory.channels`：该节点自动生成配置中的 controller/subchannel 数，必须为正二次幂；
- `memory.config`：相对于拓扑文件的完整 Ramulator External 配置。可用它接入
  自定义时序；一旦任一节点指定，所有节点都必须指定，避免静默混用。

未提供 `memory.config` 时，`env/generate_ramulator_config.py` 会为每个 memory node 生成真正的
Ramulator2 `External` 配置、匹配的 DRAMPower memspec 和带哈希的配置元数据。HBM3 使用
`HBM3_16Gb_8hi / HBM3_6400Mbps`；HBM3E 使用
`HBM3E_24Gb_8Hi / HBM3E_8000Mbps`，并通过 Ramulator2 的 HBM3 命令/状态实现建模。
HBM3E 档案不是另一个原生 DRAM 类，实际实现名会以 `dram_implementation: HBM3` 写入配置
元数据。其 8Gbps 时序保持 HBM3 6.4Gbps 档案的物理时间，功耗参数从公开 HBM3E 参数按
速率缩放，均未经过具体器件标定。LPDDR5 使用
`LPDDR5_16Gb_x16 / LPDDR5_6400`，LPDDR6 使用
`LPDDR6_16Gb_x12 / LPDDR6_10667_BL24`；LPDDR6 的两个 controller 对应一个物理 x24
通道的两个 x12 subchannel。LPDDR 功耗使用仓库公开参考参数，绝对精度未作目标厂商标定，
这一限制会写入结果元数据。HBM3、HBM3E 和 LPDDR 不允许使用 HBM4 专用的
`--ramulator-scale`，避免伪造未验证的时序预设。

AXI 数据宽度可选 256、512、1024 bit，但 SystemC 端口类型在 C++ 编译时固定，所以必须先：

```bash
SS_AXI_DATA_WIDTH=512 bash env/build.sh
```

运行时再传 `--axi-data-width 512`。程序会校验它与构建值一致。UCIe lane 数、速率、调制
和模块数量是运行期参数。

仓库提供以下拓扑样例：

- `configs/topology/single-hbm4.json`：原单模块基线；
- `configs/topology/single-hbm3.json`：HBM3 6.4Gbps 单模块模板；
- `configs/topology/single-hbm3e.json`：HBM3E 8.0Gbps 单模块模板；
- `configs/topology/dual-ucie-hbm4.json`：两个 16-lane、32 GT/s 模块；
- `configs/topology/quad-ucie-hbm4.json`：四模块聚合；
- `configs/topology/octal-ucie-hbm4.json`：八模块聚合；
- `configs/topology/dual-ucie-lpddr.json`：自动生成 LPDDR5 External 配置的双模块模板；
- `configs/topology/dual-ucie-lpddr6.json`：自动生成 LPDDR6 External 配置的双模块模板；
- `configs/topology/single-hbm4-axi512.json` 和 `single-hbm4-axi1024.json`：匹配宽 AXI
  原始峰值的 32-lane/64-lane、24 GT/s UCIe 模板。

## 运行示例

推荐使用统一入口。它创建不覆盖旧结果的新目录、运行受控流量、逐链路验收并生成可视化：

```bash
SS_EXPERIMENT_LABEL=dual-hbm4 bash env/run_topology.sh

# HBM3/HBM3E 使用相同链路参数，便于和 HBM4 对照内存模型差异
bash env/run_topology.sh results/hbm3-check configs/topology/single-hbm3.json
bash env/run_topology.sh results/hbm3e-check configs/topology/single-hbm3e.json

# 显式结果目录和配置
bash env/run_topology.sh results/20261008-dual-hbm4-r01 \
  configs/topology/dual-ucie-hbm4.json
```

压力参数可用 `SS_TRAFFIC_LOAD_PERCENT`、`SS_TRAFFIC_WARMUP`、
`SS_TRAFFIC_MEASURE`、`SS_TRAFFIC_COOLDOWN`、`SS_TRAFFIC_SIZE`、
`SS_TRAFFIC_WORKING_SET`、`SS_TRAFFIC_WRITE_PERCENT` 和
`SS_TRAFFIC_MAX_INFLIGHT` 覆盖。链路和后端可用 `SS_RESOURCE_PLANES`、`SS_AXI_PERIOD`、
`SS_AXI_NO_STALLS`、`SS_RAMULATOR_STANDARD`、`SS_RAMULATOR_CHANNELS`、
`SS_RAMULATOR_QUEUE`、`SS_RAMULATOR_SLOTS`、`SS_RAMULATOR_CHILDREN`、
`SS_RAMULATOR_SUBMIT_WIDTH`、`SS_RAMULATOR_RESPONSE_HOLD`、`SS_RAMULATOR_SCALE`、
`SS_RAMULATOR_NO_POWER` 和 `SS_METRICS_SAMPLE_CYCLES` 覆盖。拓扑文件中的
`memory.standard` 优先于统一标准，显式 `SS_RAMULATOR_CHANNELS` 则覆盖各节点的
`memory.channels`。下面是等价的手动命令：

```bash
source env/activate.sh
gem5/build/AXI/gem5.opt --listener-mode=off -d results/manual-dual \
  gem5_axi/configs/run.py --backend aou --memory-backend ramulator2 \
  --mode traffic --topology-config configs/topology/dual-ucie-hbm4.json \
  --traffic-warmup 128 --traffic-measure 1024 --traffic-cooldown 128 \
  --traffic-size 256 --traffic-working-set 1048576
```

若使用自备 LPDDR 配置，可在拓扑的两个 module 中分别写入：

```json
"memory": {"config": "../../ramulator2/example_configurations/LPDDR5_6400.yaml"}
```

具体路径和配置名称应以本地 Ramulator2 已验证配置为准。拓扑层不会把 HBM 参数改名成
LPDDR；内存标准、组织、时序和 DRAMPower 模型始终来自实际 External 配置。

仓库提供两套自动回归。模块/RP 矩阵使用当前 AXI256 构建运行 12 个完整用例：

```bash
bash env/run_configuration_matrix.sh
# 1/2/4/8 modules × Resource Plane 1/2/4
```

位宽矩阵会依次重建和运行 256/512/1024 bit，最后恢复默认 256 bit：

```bash
bash env/run_axi_width_matrix.sh
# 可用 SS_RESTORE_AXI_DATA_WIDTH=512 指定回归后保留的构建位宽
```

每个矩阵目录包含 `matrix_plan.json`、`matrix_summary.json`、`matrix_summary.csv` 和
`matrix_summary.md`。汇总器重新读取每个用例的 `metrics.json`、`metrics_run.json`、
`topology_resolved.json` 和多模块 `topology_check.json`，检查成功请求、错误数、实际 AXI
位宽、模块数和 Resource Plane，不会只根据进程退出码判定。位宽宏只附着在依赖 AXI 类型
的源码单元上，切换位宽仍需要链接新的 gem5，但不再使全部 gem5 源码无条件重编译。

## 输出与判定

单模块继续在用例根目录生成原文件。多模块新增：

```text
case/
  topology_resolved.json       # 完全展开、可复现实验的输入
  topology_summary.json        # 全局流量和每个模块结果路径
  topology_check.json          # 地址归属、逐链路与聚合守恒的独立验收
  protocol_summary.json        # 所有 TLM 请求的汇总
  transactions.csv             # 带 module 列的全局请求表
  metrics.json                 # 全局吞吐、延迟、各节点能量之和
  links/link0/                 # 模块0全部原始证据与独立统计
  links/link1/                 # 模块1全部原始证据与独立统计
```

每个 `links/linkN` 保留 AXI 五通道 VCD、两端带时间戳 Flit 日志、Ramulator 命令、backing
最终映像、队列统计和 DRAMPower。全局 UID 的高 8 bit 是模块号，低 56 bit 是模块内序号，
因此不同端口复用相同 AXI ID 时仍可唯一关联。

可视化页面在“并行拓扑与各物理路径”中逐模块显示请求数、有效吞吐、AXI 读写利用率、
UCIe 双向物理利用率、后端 burst/子事务、DRAM 命令、能量和功率。发布已有结果时会自动
对每条链路执行 AXI 数据、VCD、Flit、Ramulator 命令/数据/功耗校验，再检查根目录合并表、
地址条带归属、全局 UID 和能量求和：

```bash
python3 env/publish_results.py results/manual-dual --no-open --no-serve
# 或只运行独立拓扑校验
python3 gem5_axi/scripts/check_topology.py results/manual-dual
```

全局平均带宽按所有成功完成的有效字节除以同一仿真时间计算；并行内存节点的 DRAM 能量
可以相加，平均功率用总能量除以全程时间。不同模块的延迟样本保留为逐请求分布。利用率
必须在各自物理资源的容量上计算，不能把各链路百分比直接相加。

## 完成边界

本阶段已经完成多个 TLM/AXI/UCIe/内存节点、地址交织、独立数据所有权、全局事务身份、
AXI 构建期宽度、UCIe 运行期几何、逐模块证据和整体统计。当前拓扑是一个 UCIe 模块对应
一个独立 memory node/stack。多个 UCIe 模块共同进入同一个 Ramulator controller、跨 CPU
缓存一致性、动态热插拔和任意非二次幂路由属于后续互连/一致性阶段。
