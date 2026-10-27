# StorageBridge RTL 桥接实现

## 1. 边界与数据所有权

存储侧现在有两个可切换实现，二者使用相同外部边界：

```text
UcieLink.mem_rx_out
       │ 250 B AoU FDI frame
       ▼
StorageBridge
  ├─ systemc: AouTarget
  └─ rtl: storage_bridge_top + RtlAouTarget transactor
       │ SimpleMemRequest / SimpleMemResponse
       ▼
RamulatorBackend ── ssr_submit/ssr_step/ssr_poll_event ── Ramulator2
       │
       └─ SparseMemory backing（唯一真实数据副本）
```

RTL 不保存系统内存，也不把 Ramulator2 伪装成 RTL。写数据只在
Ramulator2 `SERVICE` 事件到达后写入 backing；读数据也在 `SERVICE` 后从
backing 取出。`ISSUE` 事件只记录实际 DRAM 命令，不能提前完成数据事务。

用户配置项 `bridge.implementation` 取值为 `systemc` 或 `rtl`。该值、AXI
位宽和 Resource Plane 数量均进入构建签名；配置改变时统一运行入口会自动
重建对应的 Verilated 模型。

## 2. RTL 顶层接口

顶层为 `storage_bridge/rtl/storage_bridge_top.sv`，参数为：

这里的 FDI 是当前 UCIe 行为模型交付的 250 B AoU 协议载荷流，不是 PHY
电气引脚级接口；HIF 是本项目为连接内存控制器/仿真后端定义的三组 ready/valid
事务通道，不宣称复现某一厂商 HIF 的逐位编码。以后替换为真实 MC RTL 时，只需
在这三组通道之后增加命令/数据适配器，AoU 解析与 credit 逻辑无需搬入后端。

| 参数 | 取值 | 作用 |
|---|---:|---|
| `AXI_DATA_WIDTH` | 256/512/1024 | 决定一个 W/R beat 的数据和选通信号宽度，也决定 AoU `DLENGTH` |
| `RESOURCE_PLANES` | 1..4 | 启用的独立协议资源平面数量 |
| `REQUEST_SLOTS` | 默认 4 | 每个 RP 可接收的 AW、AR 容量，用于初始 credit |
| `WDATA_GRANULES` | 默认 64 | 每个 RP 的写数据接收容量，单位为 5 B granule |

### 2.1 时钟与复位

| 信号 | 方向 | 含义 |
|---|---|---|
| `clk` | 输入 | 桥接逻辑时钟；当前由 gem5 AXI 时钟的上升沿驱动 |
| `rst_n` | 输入 | 低有效同步运行复位；释放后发布初始接收 credit |
| `protocol_error` | 输出 | 粘滞协议错误汇总，仿真适配器将其升级为 fatal，防止错误被静默吞掉 |

### 2.2 UCIe/FDI 侧

| 信号 | 方向 | 宽度 | 含义 |
|---|---|---:|---|
| `fdi_rx_valid` | 输入 | 1 | UCIe 模型提供一个有效 AoU 逻辑帧 |
| `fdi_rx_ready` | 输出 | 1 | RTL 有空间接收该帧 |
| `fdi_rx_data` | 输入 | 2000 | 250 B AoU PLP；byte 0 位于 `[7:0]` |
| `fdi_tx_valid` | 输出 | 1 | RTL 已生成一个返回帧 |
| `fdi_tx_ready` | 输入 | 1 | UCIe 返回 FIFO 可接受帧 |
| `fdi_tx_data` | 输出 | 2000 | 250 B AoU PLP；链路模型再加入 6 B FH/CRC 形成 256 B 物理帧 |

FDI 两个方向都遵守 `valid && ready` 才传输。事务 ID、VC、方向和时间戳是
当前 UCIe TLM 模型的旁带观测信息，由 `RtlAouTarget` 在边界补充，不进入
AoU RTL 协议状态。

### 2.3 内存 HIF 命令通道

| 信号 | 方向 | 含义 |
|---|---|---|
| `hif_cmd_valid/ready` | 出/入 | 地址命令握手 |
| `hif_cmd_write` | 输出 | 1 为写请求，0 为读请求 |
| `hif_cmd_rp` | 输出 | Resource Plane，宽度 2 bit |
| `hif_cmd_id` | 输出 | AoU 线上 10 bit AXI ID |
| `hif_cmd_user` | 输出 | 16 bit USER 字段 |
| `hif_cmd_addr` | 输出 | 64 bit 起始地址 |
| `hif_cmd_len` | 输出 | AXI `LEN`，实际 beat 数为 `LEN+1` |
| `hif_cmd_size` | 输出 | 每 beat 有效字节数的 `log2` |
| `hif_cmd_lock/prot/cache/qos` | 输出 | 原 AXI 请求属性 |

命令通道等价于已解码的 AW/AR。`RtlAouTarget` 将读命令直接构造成
`SimpleMemRequest`，将写命令放入每 RP 写突发槽，等待相应数据 beat。

### 2.4 内存 HIF 写数据通道

| 信号 | 方向 | 含义 |
|---|---|---|
| `hif_w_valid/ready` | 出/入 | 一个写数据 beat 的握手 |
| `hif_w_rp` | 输出 | 该数据所属 Resource Plane；在同一 RP 内按命令顺序配对 |
| `hif_w_user` | 输出 | 16 bit WUSER |
| `hif_w_data` | 输出 | 256/512/1024 bit 数据，低字节 lane 位于低位 |
| `hif_w_strb` | 输出 | 每数据字节 1 bit；`WriteDataFull` 解码为全 1 |

AoU 写数据消息没有 WLAST。适配器依据先前命令的 `LEN+1` 重建突发边界，
收齐后才向 `RamulatorBackend` 提交整笔写请求。

### 2.5 内存 HIF 响应通道

| 信号 | 方向 | 含义 |
|---|---|---|
| `hif_rsp_valid/ready` | 入/出 | 一个 B 响应或一个 R beat 的握手 |
| `hif_rsp_write` | 输入 | 1 表示 B，0 表示 R |
| `hif_rsp_rp/id/user` | 输入 | 与原请求匹配的 RP、ID、USER |
| `hif_rsp_status` | 输入 | AXI BRESP/RRESP，两位 |
| `hif_rsp_last` | 输入 | 读突发最后一个 beat；写响应忽略 |
| `hif_rsp_data` | 输入 | 读数据；写响应时忽略 |

RTL 只有在对端已经授予足够 `ReadData` 或 `WriteResp` granule credit 时才拉高
`hif_rsp_ready`。因此后端响应 FIFO 的背压会一直传到 RamulatorBackend，响应
不会因桥接实现切换而丢失。

## 3. RTL 子模块

| 子模块 | 上游接口 | 下游接口 | 职责 |
|---|---|---|---|
| `aou_fdi_rx` | FDI RX 帧 | 通用 AoU message 流、header credit | 还原 48 bit MsgStart，逐消息扫描，检查保留位和消息内部起点，重组跨帧消息 |
| `aou_request_decoder` | message 流 | HIF command、HIF W | 精确恢复 AW/AR/W 字段；完成 HIF 握手后归还相应接收 credit |
| `aou_credit_manager` | header/Misc credit、接收空间释放、响应消费 | 可发送判断、返回 header credit | 为 4 RP×5 类消息维护 granule 计数；发布初始 WREQ/RREQ/WDATA 容量 |
| `aou_response_encoder` | HIF response | ReadData/WriteResp message | 按 AXI 位宽选择 DLENGTH，恢复 ID/RESP/LAST，按 AoU 字节序编码数据 |
| `aou_fdi_tx` | response message、返回 credit | FDI TX 帧 | 在一个 48-granule 载荷中聚合多条响应；装不下或输入出现空隙时封帧 |
| `storage_bridge_top` | FDI RX、HIF response | FDI TX、HIF command/W | 结构连接、消息类型路由及协议错误汇总 |
| `RtlAouTarget` | SystemC `FdiFlit` FIFO、RTL HIF | `SimpleMemRequest/Response` FIFO | 驱动 Verilator 时钟，转换宽总线字节序，重建写突发并补充 UCIe TLM 旁带元数据 |
| `StorageBridge` | UCIe FDI FIFO | RamulatorBackend | 运行时选择参考或 RTL endpoint，并保持后端与统计边界一致 |

## 4. 构建与运行

RTL lint 覆盖三种支持位宽：

```bash
make -C storage_bridge lint WIDTH=256 PLANES=4
make -C storage_bridge lint WIDTH=512 PLANES=4
make -C storage_bridge lint WIDTH=1024 PLANES=4
```

统一配置中选择 RTL：

```json
"bridge": {
  "resource_planes": 4,
  "tlm_slots": 64,
  "fabric_clock_ratio": 4,
  "implementation": "rtl"
}
```

随后仍使用统一入口：

```bash
bash env/run_system_profile.sh configs/user/full-link-research-template.json \
  results/$(date +%Y%m%d)-rtl-bridge-r01
```

`aou_summary.json` 的 `storage_bridge_implementation` 明确记录实际运行实现。
`environment/manifest.json` 进一步记录 AXI 位宽、RP 数、Verilator 版本和所链接
RTL 静态库的 SHA256，并在运行前拒绝包含外部 SystemC 符号的模型。
构建脚本只生成普通 Verilator C++ 模型，不启用 Verilator SystemC wrapper，因而
进程中仍只有 gem5 自带的一套 SystemC 和统一 1 fs 时间基准。

## 5. 验证要求

RTL 与 SystemC 模式应使用相同的流量种子、内存配置和拓扑分别运行。至少比较：

1. 请求、读写、beat、后端完成和错误计数；
2. `ramulator_final_image.csv` 与离线数据校验结果；
3. Ramulator2 命令序列和 SERVICE 数；
4. AXI 五通道 VCD、双端完整 Flit 日志；
5. 端到端字节数、延迟分位数和各层带宽利用率。

两个实现的周期数可以不同，因为 RTL 解码器逐消息工作；功能、排序、数据和
完成语义必须一致。综合后的面积、时序和桥接功耗需要后续用目标工艺库完成，
当前 Verilator 执行结果不能替代 28 nm 前端/后端实现报告。

RTL 解码速度与 FDI FIFO 深度组合可能令接收端背压超过 UCIe ACK 窗口，从而
在无误码链路上触发 timeout replay。这类重放只有在 CRC/NAK/序号错误均为 0、
每个重放都被接收端识别为重复帧且完整 Flit 审计通过时才允许；它反映真实的
可靠性与缓冲压力，不能计作第二次业务消息交付。
