# StorageBridge RTL 桥接实现

## 数据通路与职责

```text
CPU/GPU/NPU 或 gem5 Packet traffic
 → 原生 TLM → AXI → AXI2Flit → UCIe
 → StorageBridge
     ├─ systemc：AouTarget（参考实现）
     └─ rtl：RtlAouTarget 适配器 + storage_bridge_top
                 FDI RX → 消息解码 → RTL 描述符/写缓存/事务表
                      ↕ credit             ↓ HIF command/W
                 FDI TX ← 响应编码 ← HIF response
 → RamulatorBackend → Ramulator2 实际 DRAM 命令与 SERVICE
                         ↕ 唯一 backing 数据
                         ↓ DRAMPower
```

`gem5_axi/storage_bridge.cc` 是系统集成顶层，选择 endpoint 后连接同一个
RamulatorBackend。`storage_bridge/rtl/storage_bridge_top.sv` 是硬件协议桥顶层。
RamulatorBackend 和 Ramulator2 仍是仿真后端，不在 RTL 综合边界内。

RTL 保存的是在途事务与临时写缓存，不是第二份系统内存。读 backing 和提交写数据
均由实际 DRAM `SERVICE` 事件触发；命令 `ISSUE`、写 callback 或桥接握手不能
提前完成内存数据服务。全系统仍使用单进程、gem5 原生 SystemC 和 1 fs 时间基准。

本轮将写请求缓存、调度与事务 tag 所有权移入 RTL。C++ 只完成时钟驱动、字节序、
FIFO 和 `SimpleMemRequest/Response` 表示转换，不再决定四个写描述符的容量。
适配器暂存一个正在交付后端的 HIF 写突发；其所有 beat 都来自 RTL 写缓存。

## RTL 子模块

| 文件 | 输入→输出 | 职责 |
|---|---|---|
| `aou_fdi_rx.sv` | 250 B 帧→消息、头部 credit | 帧 FIFO、MsgStart 查找、跨帧拼接、到达周期；空/仅头部帧可每周期接收一帧 |
| `aou_request_decoder.sv` | AoU 消息→命令/W | 大端字段提取、DLENGTH/RP/SIZE、对齐与 4 KiB 边界检查 |
| `aou_transaction_manager.sv` | 命令/W→HIF，后端响应→已校验响应 | 每 RP 独立 AW/AR 描述符、AW/W 解耦 FIFO、写数据/掩码/USER 缓存、公平组间调度、ID/RP/方向事务表、读 LAST 校验、tag 退休 |
| `aou_credit_manager.sv` | 头部/Misc grant、资源释放→发送额度/返还 grant | 16 bit 计数；同周期增减守恒；TX 捕获和扣减同一份 grant，越界报错 |
| `aou_response_encoder.sv` | 已校验 HIF 响应→AoU RDATA/B | 校验下游 credit 后消费额度，按所选 AXI 位宽编码 |
| `aou_fdi_tx.sv` | 响应消息/grant→250 B 帧 | 双缓冲、跨帧拆分、有限等待封帧；将事务退休标记保留到最后片段被 FDI 接受 |
| `storage_bridge_top.sv` | FDI↔HIF | 连接上述模块，汇总错误、占用/阻塞/延迟计数和空闲状态 |

AW 与 W 是独立通道，线上 WDATA 允许先于 AW。每 RP 的独立 WDATA FIFO 先接收
它，并按同 RP 的 AW 次序配对，再写入该描述符的突发缓存。FIFO 容量按宣告的
granule 窗口和该位宽最小 WDATA 消息粒度计算；尚未配对的数据也必须计入 business_idle。
这样 WDATA 不会堵住同一 FDI 流后面的 AW 或响应 credit 维护。完整收齐后才调度
该写命令。组间使用轮询，
同组保持描述符先后顺序。当前 HIF 只有一条命令与一条写数据通路，写命令后连续
交付其 W beat；多个已发出的读写事务可在后端在途。

地址命令已经采用 INCR 突发契约：SIZE 不超过总线宽度、地址按 SIZE 对齐、
突发不跨 4 KiB；一笔最多 256 beat 且实际传输不超过 4096 B。LOCK/PROT/CACHE/QOS
保留字段，不等于实现原子操作、独占监视器、QoS 优先调度或跨设备缓存一致性。

## 外部信号契约

### 时钟、FDI 与状态

| 信号 | 方向/宽度 | 含义 |
|---|---|---|
| `clk`、`rst_n` | 输入，各 1 bit | 当前与 AXI fabric 同步；低有效异步复位。运行中热复位由适配器拒绝 |
| `fdi_rx_valid/ready/data` | 入/出/入，1/1/2000 bit | UCIe → Bridge 的 250 B AoU 载荷；byte 0 在 `[7:0]` |
| `fdi_tx_valid/ready/data` | 出/入/出，1/1/2000 bit | Bridge → UCIe 的 250 B 载荷；链路再加入 6 B FH/CRC 形成 256 B 物理帧 |
| `business_idle` | 输出，1 bit | 无业务消息、描述符、在途 tag、业务响应片段；可保留已识别的 credit 维护 |
| `link_idle` | 输出，1 bit | 还要求帧缓冲、维护消息和待返还 credit 均排空；仅描述桥接边界，不代表 PHY/LTSSM 状态 |
| `protocol_error/error_code` | 输出，1/32 bit | 粘滞错误及原因；RX=1、decode=2、credit=4、transaction=8、TX=16、消息类型=32 |

所有通道仅在 `valid && ready` 的时钟沿传输；背压期间必须保持 valid 和有效
payload 稳定。FDI 是当前行为模型的协议载荷接口，不是完整 UCIe 3.0 标准 FDI
引脚集合；本项目尚无 PHY 电气模型、CDC、链路训练及低功耗状态机。

### HIF 命令与写数据

| 信号 | 方向/宽度 | 含义 |
|---|---|---|
| `hif_cmd_valid/ready` | 出/入，各 1 bit | 接受一笔完整读/写地址命令 |
| `hif_cmd_write/rp/id/user` | 输出，1/2/10/16 bit | 方向、RP、AoU 线上 AXI ID、USER |
| `hif_cmd_addr/len/size` | 输出，64/8/3 bit | 起始地址、beat 数减一、每 beat 传输字节数的 log2 |
| `hif_cmd_lock/prot/cache/qos` | 输出，1/3/4/4 bit | 原请求属性 |
| `hif_w_valid/ready` | 出/入，各 1 bit | 一个写数据 beat 握手 |
| `hif_w_rp/user` | 输出，2/16 bit | 当前写突发的 RP、当前 beat 的 USER |
| `hif_w_data/strb` | 输出，WIDTH / WIDTH÷8 bit | 数据与逐字节写使能；窄访问保留相应 AXI byte lane |
| `hif_w_last` | 输出，1 bit | 当前命令最后一个 W beat；与 `LEN+1` 一致 |

HIF 是本项目定义的 ready/valid 事务接口，不对应某一 MC 厂商编码。命令握手
代表描述符发出；最后一个 W 握手才代表整笔写已交给后端。对接真实 MC RTL 时需
在 HIF 后实现厂商命令、写数据、返回数据和背压适配。

### HIF 返回与观测

| 信号 | 方向/宽度 | 含义 |
|---|---|---|
| `hif_rsp_valid/ready` | 入/出，各 1 bit | 一个后端响应 beat 握手 |
| `hif_rsp_write/rp/id/user/status` | 输入，1/2/10/16/2 bit | 写响应或读数据、RP、ID、USER、AXI RESP |
| `hif_rsp_last/data` | 输入，1 / WIDTH bit | 读响应的 LAST/数据；写响应无数据，LAST 不参与写完成判断 |
| `response_tag/known` | 输出，6/1 bit | 当前响应匹配到的内部 tag，仅供适配器观测 |
| `response_retire_mask` | 输出，64 bit | 最后响应片段在本周期被 FDI FIFO 接受的 tag 集合；同帧可退休多笔写 |
| `hif_cmd_latency_cycles` | 输出，32 bit | 该命令首片段帧到达至当前 HIF 命令接受的周期差 |
| `config_*`、`stat_*` | 输出 | 实际综合参数、运行计数；适配器检查编译/运行容量一致 |

按方向、RP、ID 匹配最早未完成的事务，允许不同 ID 乱序响应；同 ID 需保持后端
返回顺序。读响应每一 beat 的 LAST 都与 LEN 核对。响应未知 ID、重复结束、提前
LAST、缺少 LAST、无效 tag 退休均报错。tag 直到最后响应片段离开 Bridge 才释放，
因此已被后端接受但尚未发往链路的响应仍计入在途事务。

## 容量与信用释放

| 用户字段 `bridge.rtl.*` | 默认/范围 | 对 RTL 的作用 |
|---|---|---|
| `request_slots` | 4；1..16 | 每 RP、每读写方向的描述符槽数；初始 WREQ/RREQ 各为 `3×slots` granule |
| `max_outstanding` | 8；1..64 | 后端命令至 FDI 响应交付之间的 tag 总数 |
| `wdata_granules` | 64；30..4096 | 写数据协议接收额度，1 granule=5 B；决定解耦 FIFO 容量，不是 backing 大小 |
| `frame_fifo_depth` | 2；1..16 | RX 与 TX 各自的帧 FIFO 深度；拼接/封帧寄存器另计 |
| `tx_flush_cycles` | 2；1..64 | 部分载荷无新消息后的封帧等待；credit 无法搭载业务时最多等待内部固定 8 周期，外加输出背压 |
| `trace` | false；true/false | 是否输出 RTL VCD；仅运行时选择 |

AXI WIDTH 支持 256/512/1024 bit，RP 支持 1..4。前五个容量参数、WIDTH 和 RP
参与构建签名；改变后必须重建。每个写描述符逻辑上存 4096 B 数据、4096 个掩码
位与 256×16 bit USER，默认 RP1/4 槽约 20 KiB 突发写缓存，另有按 credit 窗口
分配的 WDATA 解耦 FIFO、描述符与帧寄存器。实际 RAM 推断、资源面积和时序必须用目标综合工具确认。

信用释放点与真实资源严格对应：RREQ 在 HIF 读命令握手后释放，WREQ 在最后
一个 HIF W beat 握手后释放，WDATA 在 beat 从解耦 FIFO 配对进入描述符写缓存后释放，
不在单纯接收进 FIFO 时提前返还。
这避免了早返 WREQ 后，第五笔 AW 占住流头、四笔旧写又等不到 WDATA 的死锁。
TX 同一时钟沿封存 grant 并扣减同一份数值，避免 grant 在一个周期内变化时漏返。

TX 可将一条响应分到相邻帧，首片段设置 MsgStart，续片不再设置。最后片段携带
完成标记；FDI 背压时帧与标记保持不变。填充粒度为 5 B，帧有效区域 240 B。

## 用户配置与运行

在 `configs/user/full-link-research-template.json` 的副本中选择：

```json
"bridge": {
  "resource_planes": 4,
  "tlm_slots": 64,
  "fabric_clock_ratio": 4,
  "implementation": "rtl",
  "rtl": {
    "request_slots": 4,
    "max_outstanding": 8,
    "wdata_granules": 64,
    "frame_fifo_depth": 2,
    "tx_flush_cycles": 2,
    "trace": true
  }
}
```

保持复制配置中 AXI 端口和 fabric 比例等其他约束一致，执行统一入口：

```bash
bash env/run_system_profile.sh configs/user/你的配置.json
```

可直接运行已配置为 RTL 的单链路示例：

```bash
bash env/run_system_profile.sh configs/system/storage-bridge-rtl-hbm4.json
```

仍保留 SystemC 参考实现和原默认选项；选择 `rtl` 才运行硬件桥。直接构建/验收：

```bash
SS_STORAGE_BRIDGE_IMPL=rtl SS_RESOURCE_PLANES=1 bash env/build.sh
python3 env/test_storage_bridge.py --matrix
SS_STORAGE_BRIDGE_IMPL=rtl bash env/run_configuration_matrix.sh
SS_STORAGE_BRIDGE_IMPL=rtl SS_RESOURCE_PLANES=1 bash env/run_axi_width_matrix.sh
bash env/run_storage_bridge_validation.sh
```

最后一项重建 AXI256/RP1 的 RTL 配置，执行定向、CPU、256/1024/4096 B×读/混合/写
九组压力测试，并与 SystemC 的 1 KiB 混合负载比较最终 backing 和事务结果。
这是有界的功能/压力回归，不代替长时间稳态饱和扫描。

构建模型位于 `env/storage_bridge_config.py --build-dir` 给出的目录，文件名带全部
硬件容量参数。模型 manifest 保存源码及静态库 SHA256；统一入口根据签名自动
重建，手动绕过构建的运行入口则会拒绝过期库。硬件同时输出 config 参数供适配器
核对。Verilator 生成普通 C++ 模型（`VM_SC=0`），不得链接第二套 SystemC。

## 独立统计与测量边界

每条 RTL 链路增加下列输出，根目录及在线页面保留逐链路报告：

| 文件 | 内容 |
|---|---|
| `storage_bridge_summary.json` | 实际参数、时钟、帧/消息数、四类背压周期、描述符/在途/WDATA队列峰值与积分、跨帧/credit-only 帧、两类延迟及空闲状态 |
| `storage_bridge_events.csv` | fs 时间戳的 FDI RX/TX、HIF command/W/R、最终响应 FDI commit |
| `metrics/storage_bridge.json` | 统一独立模块报告；多模块时逐链路保留，不把延迟分位数直接相加 |
| `link_diagnostics.json` / `metrics.html` | HIF W/R 结构上限与实测带宽、Bridge 状态/阻塞/延迟 |
| `storage_bridge_rtl.vcd` | trace=true 时的内部控制/接口波形；与原 AXI 五通道及双端 Flit 日志同时保留 |

`request_frame_to_hif_command` 从请求首片段帧被 RTL RX 接受到 HIF 命令握手，包含
RX 排队、解码、写数据收齐与调度等待。`backend_response_to_fdi_commit` 从匹配
后端响应首次 valid 到该事务最后片段被 FDI FIFO 接受，包含响应排队、credit、
封帧和输出等待。这两项不能简单相加作为端到端延迟，也不能直接当作桥接固有延迟。
单独证明 20 ns 需要明确的无竞争测量条件和分项时序。

`check_metrics.py` 独立重算事件分位数、完成数、HIF/AXI beat 守恒、描述符/tag
上界和队列积分；`check_metrics_negative.py` 注入删事件、伪造延迟、溢出峰值等
错误验证校验器拒绝。AXI/AoU/VCD、UCIe 精确交付、Ramulator 命令/服务/backing
与 DRAMPower 原有独立校验继续保留。

仿真结束要求 business_idle；link_idle=false 只允许已经识别的完整 credit 维护。
适配器对剩余外部帧重新解码，拒绝业务、未知或未完成跨帧消息，不再清空任意输入。
内部维护状态仍保留在统计/VCD中。仅有维护未排空不等于丢失业务。

HIF 的 `WIDTH/8/period` 只是结构带宽上界。RX 每消息处理、HIF 写调度、credit
往返和 tag 窗口仍可能限制持续吞吐。配置报告中的容量平衡不证明达到 90%；RTL
运行将平衡状态标记为 `bridge_service_unverified`，需独立稳态扫描得出结论。

## 验证与后续硬件交接

独立 RTL 回归覆盖信用快照守恒、每周期空帧接收、TX 跨帧/背压/精确退休、
AW 满槽时禁止提前返还、W先于AW时的缓存/配对、WDATA/USER/选通及HIF写背压稳定性、未知 ID/错误 LAST，以及
WIDTH256/512/1024 × RP1/2/3/4。系统级再验证模块数1/2/4/8 × RP1/2/4、三种位宽、
CPU 与大粒度压力流量。每次在新的 results 日期/标签目录保留证据。

差分验证必须使用相同配置、流量和种子，比较成功请求、有效字节、读回值、最终
backing 和 DRAM SERVICE 关联。不同调度实现可以产生不同延迟、命令次序与 DRAM
能量；这些差异应分析而非强制二进制相同。

`synthesis/` 提供带工艺库/时钟/IO约束的综合交接模板。当前环境未提供目标工艺
库和综合/布局布线工具，尚未产出面积、关键路径或桥接功耗。默认 VCD 排除超过
512 项的数组，不能用其直接推算全部 SRAM 活动功耗。DRAMPower 仍仅覆盖 DRAM。
多时钟 CDC、链路训练/低功耗、ECC/RAS、原子/一致性、SRAM 宏映射、DFT 与物理
实现仍属后续工作，不能由本轮功能回归替代。

## 2026-10-28 本机功能与压力验收

最终压力批次保存在 `results/20261028-storage-bridge-validation-r03/`，通过统一
后处理输出独立统计、波形、完整 Flit 日志、Ramulator 命令/数据与可视化。
`directed` 的 17 笔前端请求覆盖掩码、边界与预期错误；CPU 程序的 452 笔请求
全部完成，包括 194 读、258 写，未发生数据错误、CRC 错误或重放。

九组压力用例均为 AXI256/RP1、16 lane×24 GT/s NRZ、2 个 HBM4 controller，
64 个前端在途请求、RTL 4 个描述符槽/方向、8 个 tag、64 granule WDATA 窗口。
每组 16 笔预热、256 笔测量、16 笔冷却，共 288 笔，全部通过独立数据与统计校验。
下表为测量 cohort 的有效带宽；短批次用于回归，不代表充分收敛的饱和带宽。

| 请求大小 | 只读 GB/s | 50%写 GB/s | 只写 GB/s |
|---|---:|---:|---:|
| 256 B | 12.043 | 9.970 | 7.284 |
| 1 KiB | 20.991 | 12.328 | 9.235 |
| 4 KiB | 20.412 | 14.053 | 9.672 |

这组配置没有证明 90% 利用率。应继续对 credit 窗口、在途 tag、后端队列、请求
大小和供给负载做独立稳态扫描；不能只根据接口结构峰值推定业务吞吐。

`differential_check.json` 核对 RTL 与 SystemC 的 1 KiB 混合流量：288 笔请求的
结果、读写 beat、DRAM 提交/服务计数与 9,216 个最终 backing 数据块一致。
两个实现的延迟、调度次序和能量允许不同。RTL 独立回归的16项均通过，包含
三种位宽与 RP1/2/3/4；严格 lint 覆盖三种位宽的 RP4。

统一入口另通过了 `configs/system/storage-bridge-rtl-hbm4.json` 的 288 笔示例，
以及 `request_slots=2 / max_outstanding=3 / wdata_granules=30 /
frame_fifo_depth=1 / tx_flush_cycles=1` 的20笔小容量测试。后者实际报告的配置与
目标一致，tag 峰值为3，验证硬件容量变化触发重编而非只改变页面文本。结果位于
`results/20261028-storage-bridge-small-capacity-r01/`，归档配置在其 `system_profile/`。

最终源码的系统矩阵均通过：

| 矩阵 | 结果目录 | 结果 |
|---|---|---|
| 1/2/4/8模块 × RP1/2/4 | `results/20261028-storage-bridge-topology-r03/` | 12/12 |
| AXI256/512/1024完整链路 | `results/20261028-storage-bridge-width-r03/` | 3/3 |

HIF 利用率以实际握手 beat 数除以有效时钟机会数，不能套用没有 busy interval 的
通用区间资源算法。本批派生统计与页面已据原始事件重新生成，并在
`metrics_refresh.json` 记录分析脚本 SHA256；原始仿真不重放、不改写。
