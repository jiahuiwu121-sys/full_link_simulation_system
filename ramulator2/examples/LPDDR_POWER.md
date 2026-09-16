# LPDDR5/LPDDR6 可配置仿真及功耗模型

## 运行

在项目根目录运行：

```bash
PYTHONPATH=python ramulator2-venv/bin/python examples/LPDDR5_example_config.py
PYTHONPATH=python ramulator2-venv/bin/python examples/LPDDR6_example_config.py
```

| 默认配置 | LPDDR5 | LPDDR6 |
| --- | --- | --- |
| 组织预设 | `LPDDR5_16Gb_x16` | `LPDDR6_16Gb_x12` |
| 时序预设 | `LPDDR5_6400` | `LPDDR6_10667_BL24` |
| 引脚速率 | 6.4 Gbps | 10.667 Gbps |
| 物理接口 | 2 个 x16 通道 | 1 个 x24 接口，拆成 2 个 x12 子通道 |
| 独立控制器 | 2 个 LPDDR5 控制器 | 2 个 LPDDR6 控制器 |
| 有效事务 | BL16，32 B | BL24，32 B有效数据/36 B线上传输 |
| 当前模型容量 | 4 GiB | 4 GiB（每个子通道16 Gb） |
| 每控制器队列 | 读32项，写32项 | 读32项，写32项 |
| 默认前端 | 单核、128项窗口、16项MSHR | 相同 |
| 默认目标 | 50000条前端指令 | 相同 |

这些是可复现实验配置，不是完整厂商封装的数字孪生。LPDDR6的16 Gb
预设表示每个建模子通道容量，不能误认为整个双子通道器件只有16 Gb。

## 修改入口

直接修改 Python 配置顶部的变量：

- `TRACE_FILES`：每项对应一个 SimpleO3 核心的 trace。地址路径默认不依赖当前目录。
- `ORG_PRESET`、`TIMING_PRESET`、`DRAM_OVERRIDES`：DRAM组织和CK周期单位的时序。
- `PHYSICAL_CHANNELS`：通道数量；LPDDR6控制器数量为其两倍。
- `READ_QUEUE_DEPTH`、`WRITE_QUEUE_DEPTH`：每控制器请求项数，不是字节数。
- `WR_LOW_WATERMARK`、`WR_HIGH_WATERMARK`：写排空水位，保持 `0 <= low < high <= 1`。
- `SCHEDULER`：`FRFCFS` 或 `FRFCFSRowHit`，是两种控制器均可使用的公共调度组件。
- `ROW_POLICY`：`Open` 或 `ClosedCAP`；`ROW_CAP`设置限次关行策略上限。
- `REFRESH_POLICY`：默认 `AllBank`；LPDDR5可选 `PerBank`。`NoRefresh`仅用于诊断实验。
- `WCK_SYNC_MODE`：`need_sync` 或 `always_on`，同步给控制器与功耗配置。
- `INST_WINDOW_DEPTH`、`MSHR_PER_CORE`、`NUM_EXPECTED_INSTS`：前端并发度和停止目标。
- `READ_TOGGLE_RATE`、`WRITE_TOGGLE_RATE`：假定数据翻转率，不是读写比例。
- `POWER_OVERRIDES`、`IMPEDANCE_OVERRIDES`：未来有实测电流、电压和接口参数时的持久修改入口。

目前代码只有上述一个LPDDR5速率预设及一个LPDDR6速率预设；LPDDR5还支持
`LPDDR5_8Gb_x16`。更换速率应新增完整时序预设，不能只覆盖 `rate`。
生成器会检查 `rate`、`tCK_ps` 和Burst时长对应的WCK:CK关系。
更换速率后保留前端/内存时钟比例不变，并不意味着固定CPU的绝对频率。

`CacheLineInterleave`要求控制器数量为2的幂。当前生成器只支持LPDDR5 x16、
LPDDR6 x12及4 BG x 4 Bank，不会把未支持的组织静默映射成别的Bank模式。
容量从有效载荷组织计算，不需要另手工设置地址上限。

SimpleO3循环回放trace；停止目标不是精确的DRAM请求数。写请求经过LLC，
缓存中的写只有产生脏行驱逐后才可能表现为DRAM写，因此trace读写比例不一定
等于最终DRAM读写比例。

## 自动同步关系

```text
make_dram()解析组织和时序
    → LPDDRPowerModel生成对应JSON
    → 每控制器创建独立DRAMPower插件
    → LPDDR5/6自己的控制器发送实际命令
    → finalize后输出性能、能量和平均功率
```

生成文件分别为：

- `examples/power_specs/LPDDR5_example_config.generated.json`
- `examples/power_specs/LPDDR6_example_config.generated.json`

`DRAMPower/examples/lpddr5/`和`lpddr6/`下的静态文件仅提供电气/接口参考参数，
生成器覆盖活动组织和时序，不会修改静态文件。默认电流不按容量任意缩放；
改变速率时仅以一阶线性模型缩放IDD4中高于IDD3N的动态部分。

**仅修改trace即可运行新的功耗统计，无需手改后端JSON。** 但trace变化不会改变
器件电流、电压、容量或翻转率；同一器件使用不同trace时，生成的器件参数可以
完全相同，能量变化来自命令数量和状态持续时间。

输出与HBM公共报告对齐，包括带宽、活动通道利用率、读写ticks/ns延迟、
行命中/未命中/冲突、队列占用、ACT/PRE/RD/WR/REF/RFM/背景/接口能量、
总能量、统计时间、平均功率、求和校验和命令覆盖计数。
写延迟口径为控制器接收写请求到建模写数据Burst结束，不是CPU存储指令的
退休延迟，也不是额外等待tWR完成。

LPDDR6同时显示原始DQ线带宽及32/36有效载荷峰值；利用率以活动子通道的
有效载荷峰值作为分母，避免把元数据线传输计入可用数据带宽。

## 公开依据与适用范围

1. [Micron LPDDR5官方产品资料](https://www.micron.com/products/memory/lpddr-components/lpddr5)
   公开给出6400 Mb/s速率，支持本例速率选择。完整时序使用项目现有
   JESD209-5B实现，不把产品页当作完整时序/IDD表。
2. [JEDEC于2025-07-09发布的LPDDR6声明（Business Wire转载）](https://markets.financialcontent.com/pentictonherald/article/bizwire-2025-7-9-jedec-releases-new-lpddr6-standard-to-enhance-mobile-and-ai-memory-performance)
   明确双子通道、每子通道12 DQ、32B/64B访问及隔周期命令输入。项目当前
   功耗耦合只支持32B/BL24路径，不支持BL48功耗；尝试长Burst会报错而不是低估。
3. [Samsung 2026-01-08公开LPDDR6说明](https://news.samsungsemiconductor.com/global/ces-innovation-awards-2026-honoree-lpddr6-worlds-first-next-gen-lpddr-optimized-for-high-performing-on-device-ai/)
   给出约10.7 Gbps产品速率，支持选择项目现有10667档。该页面没有可直接用于
   命令级模型的完整IDD表，不能从其节能百分比反推出ACT/RD/WR电流。
4. [Steiner等，DRAMPower 5，RAPIDO 2025，DOI:10.1145/3721848.3721850](https://doi.org/10.1145/3721848.3721850)
   提供电流差分、Bank状态持续时间和独立接口功耗建模依据，支持LPDDR5。
   本项目LPDDR6是仓库内扩展，不能将这篇LPDDR5论文称作LPDDR6绝对精度验证。

**科学依据支持协议和统计框架，不代表当前占位电气参数已经科学校准。**
静态LPDDR参考文件使用有效1.2 V电流域、其他域零电流及1 pJ接口转换能量等
探索性数值，缺少目标厂商/型号/温度校准。生成JSON和运行结果均标记
`absoluteAccuracyValidated=false`。不要把这些值当作厂商规范电压或实测功耗。
需要绝对功耗预测时，应以实测或厂商IDD/接口数据替换参考参数。

当前耦合忽略CAS同步命令的独立接口能量，WCK模式的模型同步不等于完整模拟
所有同步活动；也不包含SoC PHY、控制器、PMIC及未建模的DVFS/低功耗状态。
RFM不在当前LPDDR请求路径中，零RFM能量不代表真实器件无需安全管理。

仅使用全Bank刷新的LPDDR6配置将未支持的RFCdb设为0；后端已避免没有REFDB
命令时的零除NaN，若真正发出REFDB而没有正时序则明确报错。

## 验证

```bash
PYTHONPATH=python ramulator2-venv/bin/python -m pytest \
  tests/unit_tests/test_lpddr_power.py \
  tests/unit_tests/test_reporting.py \
  tests/power/test_drampower_integration.py -q
```

检查 `Energy sum check: PASS`、`Unsupported DRAM commands: 0`及有限功率值。
求和校验检查数值记账，不验证真实器件精度。C++后端变动后使用
`cmake --build build --parallel 2`重新编译。
