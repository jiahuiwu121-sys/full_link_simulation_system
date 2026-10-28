# 目标工艺综合交接

`dc.tcl` 是待在有许可证和目标库的 Design Compiler 环境执行的模板，当前工作区
未执行此流程，不能据此宣称已综合、满足 20 ns 或获得 28 nm PPA。

调用方式：`dc_shell -f storage_bridge/synthesis/dc.tcl`。调用前必须配置：

| 环境变量 | 要求 |
|---|---|
| `BRIDGE_TARGET_LIBS` | Tcl 列表形式的有效 `.db` 绝对路径；明确 process/voltage/temperature corner |
| `BRIDGE_CLOCK_NS` | 目标桥接时钟周期 |
| `BRIDGE_INPUT_DELAY_NS` / `BRIDGE_OUTPUT_DELAY_NS` | 根据两端真实接口预算分配的输入/输出延迟 |
| `BRIDGE_CLOCK_UNCERTAINTY_NS` | 目标时钟不确定度 |
| `BRIDGE_LOAD_PF` | 输出负载，须与库单位一致 |

模板假设库时间单位 ns、电容单位 pF；其他单位必须先修改约束。硬件参数可通过
`BRIDGE_AXI_DATA_WIDTH`、`BRIDGE_RESOURCE_PLANES`、`BRIDGE_REQUEST_SLOTS`、
`BRIDGE_MAX_OUTSTANDING`、`BRIDGE_WDATA_GRANULES`、`BRIDGE_FRAME_FIFO_DEPTH`、
`BRIDGE_TX_FLUSH_CYCLES` 指定；默认值与 RTL 顶层相同。独立于仿真构建，交接时
必须核对其与 `storage_bridge_summary.json` 的实际参数完全一致。

模板输出网表、SDC、面积/时序/约束/资源报告至 `build/storage_bridge-synthesis`。
固定输出目录只用于单次交接，多场景请先保存各次报告，并记录源码 SHA256、工具
版本、库版本与参数。检查 RAM 是否按预期推断；当前 byte/mask/USER 数组可能被
展开成寄存器与多路选择器，正式实现应加入 SRAM 宏封装及等价验证。

该脚本约束正常工作模式并将复位保持为释放态；还需单独进行复位、CDC、DFT、
跨工艺角时序和布局布线验证。报告有负 slack 或约束违例时不能宣称目标达成。
功耗应使用覆盖全部缓存活动的 SAIF/VCD 及目标网表/宏功耗模型进行分析；当前
默认 RTL VCD 的大数组裁剪使其不足以直接做完整缓存功耗统计。DRAMPower 的
结果继续只代表 DRAM，本模板不生成虚构的桥接能量值。
