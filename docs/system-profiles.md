# 用户系统配置与自动匹配

`storagestacked.system.v2` 把用户需求写成一张可执行系统图。配置编译器先检查端点、链路、
内存和容量，再生成构建参数、运行参数、理论容量报告和验收计划。运行入口会比较构建签名；
AXI 位宽或后端发生变化时自动重编译，运行参数变化不触发无意义的重编译。

## 当前可执行图

```text
traffic / CPU / GPU / NPU
          |
 gem5 address interleave
   |      |      |      |
 TLM0   TLM1   TLM2   TLM3
   |      |      |      |
 AXI0   AXI1   AXI2   AXI3       每端口独立事务日志与五通道 VCD
   +------+--+---+------+
             |
      AxiMux（每端口FIFO、整写突发调度、全局ID重映射）
             |
       AXI2Flit → UCIe → AouTarget
             |
       RamulatorBackend
          /         \
 唯一 backing      Ramulator2 → DRAMPower
```

一条 UCIe 链路可以接一个或多个 AXI 端口；每条 UCIe 链路仍只接一个 memory node。多条
UCIe 链路可以各自接独立 memory node。端口数必须是二次幂，因为 gem5 使用地址位交织；
条带必须是二次幂且至少覆盖一个 AXI beat。当前没有实现多条 UCIe 链路共同进入同一个
Ramulator2 实例。

## 配置字段

- `axi.data_width_bits`：`256/512/1024`，属于构建期参数；
- `axi.clock_period`：运行期 AXI 周期；
- `axi_ports[]`：端口名、目标 UCIe link、来源标签；
- `ucie_links[]`：lane 数、GT/s、`NRZ/PAM4`、目标 memory node；
- `memory_nodes[]`：`HBM3/HBM3E/HBM4/LPDDR5/LPDDR6`、controller 数或完整 External 配置；
- `routing.stripe_bytes`：地址交织粒度；
- `bridge.resource_planes`：`1..4`；`bridge.tlm_slots`：每个端口的最大在途事务；
- `bridge.fabric_clock_ratio`：聚合器内部时钟相对输入端口时钟的整数倍。每条物理链路必须
  正好连接该数量的 AXI 端口；端口分配到不同内部相位，从而保留每端口 1 GHz 的握手机会；
- `backend.queue/parent_slots/child_slots/submit_width`：Ramulator 后端容量与每 tick 提交宽度；
- `requirements`：理论带宽、链路利用率和桥延迟目标，写入容量报告及验收计划。

`sources` 和 `axi_ports[].sources` 目前用于配置审计与实验说明。traffic 模式通过地址条带把
同一流量源分到多个端口；CPU/GPU/NPU 模式仍共用 gem5 目标总线。按设备身份强制路由到
不同 AXI 端口尚未启用，不能仅靠更改来源标签声称完成了隔离或 QoS。

## 4×AXI512 + UCIe x64 + HBM3

仓库样例为 `configs/system/llm8b-4axi512-ucie64-hbm3.json`：

- 4 个 512-bit AXI 端口，1 GHz，单向输入聚合原始峰值 256 GB/s；
- AXI 聚合器采用 4:1 确定性时分，内部 4 GHz、512-bit 输出原始峰值 256 GB/s；
- 1 条 UCIe x64、32 GT/s、NRZ 链路，单向原始峰值 256 GB/s；
- AoU 每 256-byte 传输单元最多承载 250-byte 消息，载荷上限 250 GB/s；
- 1 个 HBM3 memory node，16 个 controller，容量模型 16 GiB、理论峰值 819.2 GB/s；
- 配置层原始载荷容量上界 250 GB/s，瓶颈为 UCIe/AoU；通过该链路时 HBM3 理论利用率上限
  为 30.52%。因此 `90%` 目标只能解释为链路利用率，不能解释成 HBM3 峰值利用率。

这些数值只检查位宽、时钟和裸链路容量，不扣除工作负载相关的 AXI/AoU 消息、credit、
排队和 DRAM 命令时序，不能当作应用有效带宽。实际结果必须查看稳态窗口的有效带宽、
物理链路利用率、延迟分位数、队列和阻塞。聚合器用独立输入 FIFO 收集每个 1 GHz
端口的 AW/W/AR，并在 4 GHz 输出侧保持 AXI 背压稳定；写事务等整段 W 数据到齐后连续发送，
B/R 由每端口响应 FIFO 降速返回。

## 构建和运行

只生成配置并构建匹配二进制：

```bash
bash env/build_profile.sh configs/system/llm8b-4axi512-ucie64-hbm3.json
```

自动生成配置、按需构建、运行压力流量、校验并发布可视化：

```bash
bash env/run_profile.sh configs/system/llm8b-4axi512-ucie64-hbm3.json
```

运行完整负载曲线以及只读/只写方向饱和验证：

```bash
bash env/run_profile_sweep.sh configs/system/llm8b-4axi512-ucie64-hbm3.json
```

默认混合流量覆盖 `10/25/50/75/90/100/110/125%`，只读与只写覆盖 `100/125%`。
根目录生成 `profile_sweep.json/csv/md`；`passed` 表示所有闭环和排空检查通过，
`requirements_met` 单独表示带宽、链路利用率和桥延迟目标是否达到。短自动化检查可用
`SS_PROFILE_SWEEP_LOADS`、`SS_PROFILE_SWEEP_SATURATION_LOADS` 和已有的
`SS_TRAFFIC_WARMUP/MEASURE/COOLDOWN` 缩小矩阵。

指定结果目录和较短验证窗口：

```bash
SS_TRAFFIC_WARMUP=4 SS_TRAFFIC_MEASURE=32 SS_TRAFFIC_COOLDOWN=4 \
SS_TRAFFIC_MAX_INFLIGHT=32 SS_VISUALIZATION_OPEN=0 \
bash env/run_profile.sh configs/system/llm8b-4axi512-ucie64-hbm3.json \
  results/20261015-profile-smoke-r01
```

编译产物位于 `build/system_profiles/<name>/`，包含：

- `system_profile.json`：用户原始输入；
- `runtime_topology.json`：可直接交给 gem5 的输入；
- `topology_resolved.json`：名称解析成数字 ID 后的系统图；
- `capacity_report.json/md`：接口容量、瓶颈和理论可行性；
- `build.env/run.env` 与 `build_signature.json`；
- `validation_plan.json`：建议负载扫描和验收项目。

这些文件会复制到每个结果目录的 `system_profile/`。结果根目录的
`axi_aggregator.json` 记录每端口 ID 区间、AW/W/B/AR/R 数量、等待周期和五类 FIFO 峰值；
`ports/portN/` 保留聚合前的 VCD 与请求证据；根目录原有 VCD、Flit、Ramulator、backing
和 DRAMPower 文件表示聚合后的唯一物理链路。离线检查仍按全局 ID 将响应、Flit、后端
parent/child、DRAM 命令和数据映像关联到原请求。
