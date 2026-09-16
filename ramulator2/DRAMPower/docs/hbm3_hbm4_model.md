# HBM3/HBM4 功耗模型

本扩展在 DRAMPower 6.3.1 的 HBM2 命令统计与电流模型上增加 HBM3 和 HBM4。它可用于比较架构、命令流和数据活动率产生的相对功耗差异。公开资料没有给出完整的 HBM3/HBM4 厂商 IDD 表，因此随仓库提供的参数文件属于估算模型，不能替代芯片厂商的实测功耗数据。

## 数据来源和适用范围

- HBM3 电流取自 [CMU-SAFARI/HBM-Power 的 6.4 Gbps HBM3E 参数](https://github.com/CMU-SAFARI/HBM-Power/blob/artifact/sources/figure16/configs/HBM3_6400_power_datapattern.json)：每伪通道、全零数据条件下，VDD=1.1 V，IDD0=44.6 mA、IDD2N=38.3 mA、IDD3N1=34.6 mA、IDD4R=630.4 mA、IDD4W=505.1 mA。
- 数据活动修正使用同一开源模型的相对形式：`2.759 + 1.192*T_DQ + 1.331*T_TSV + 0.720*T_BG` pJ/bit。HBM3 示例保持公开配置的 `DQ=0.5、TSV=0.5、BG=0`；HBM4 示例使用其预测文档中的随机数据条件 `0.5/0.5/0.5`。
- HBM4 使用 [HBM-Power 的公开外推方法](https://github.com/CMU-SAFARI/HBM-Power/blob/artifact/sources/drampower/docs/hbm4_power_prediction.md)：VDDC=1.05 V、VDDQ=0.9 V，阵列电流沿用 HBM3E，读写动态电流相对 IDD3N 随速率线性变化。8.0 Gbps 示例由此得到 IDD4R=779.35 mA、IDD4W=622.725 mA。
- `hbm4_16000_estimated.json` 对应本工作区额外提供的 `HBM4_16000Mbps` 时序。16.0 Gbps 超出上述公开模型的 4.8–8.0 Gbps 范围，因此文件内标为 `out_of_range_extrapolated`，只适合敏感性分析。
- HBM4 的 2048-bit 接口和产品级能效只能用于整体量级检查。Micron 的[公开产品页](https://www.micron.com/products/memory/hbm/hbm4)给出了 2048 I/O、超过 11 Gbps 和相对 HBM3E 约 20% 的 pJ/bit 改善，但没有足够的命令级电流，不能直接生成完整 IDD 表。
- 组织和时序取自本工作区 Ramulator2 的 `python/ramulator/dram/hbm3.py` 与 `hbm4.py`。随附模型表示一个 Ramulator2 HBM 通道，即两个 32-bit 伪通道；完整堆栈的能量应汇总所有通道实例。

## 模型结构

地址按以下层级展开：

```text
Channel → PseudoChannel → SID → BankGroup → Bank → Row → Column
```

当前命令状态机支持 `ACT`、`PREpb`、`PREab`、`RD`、`WR`、`RDA`、`WRA`、`REFab`、`REFpb`、`RFMab` 和 `RFMpb`。CSV 的 HBM 扩展坐标格式是：

```text
timestamp,command,channel,pseudo_channel,sid,bank_group,bank,row,column[,data]
```

时间戳以半个 CK 为单位，与本项目 HBM3/HBM4 的 `tick_multiplier=2` 一致。JSON 中的时序仍按完整 CK 填写，解析器会乘 `ticksPerCK` 转换为内部时间戳。例如 HBM3-6400 的 CK 为 625 ps，一个时间戳单位为 312.5 ps；HBM4-8000 的 CK 为 500 ps，一个时间戳单位为 250 ps。

## 能量方程

核心能量沿用 HBM2 分解，所有电压、电流和时间采用 SI 单位，结果为焦耳。设 `B` 为每伪通道的 bank 总数，`Ttick=tCK/ticksPerCK`：

```text
E_ACT = V * max(Iθ - I3N, 0) * tRAS * N_ACT
E_PRE = V * max(Iβ - I2N, 0) * tRP  * N_PRE
E_RD  = Vpattern(read) * max(I4R - IB, 0) * tBURST * N_RD
E_WR  = V * patternScale(write) * max(I4W - IB, 0) * tBURST * N_WR
E_REFab = V * max(I5AB - IB, 0) * tRFC / B * N_REFab_per_bank
E_REFpb = V * max(I5PB - I3N, 0) * tRFCpb * N_REFpb
```

`Iρ`、`IB` 和 `Iθ` 使用原 HBM2 的 bank-wise 背景功耗构造。数据模式使用相对比例，因而不会引入未公开的绝对校准常数。HBM4 读能量把 DQ 项施加在 VDDQ 上，把 floor、TSV 和 BG 项施加在 VDDC 上；写能量按公开预测方法仍使用 VDDC。

公开参数没有 IDD5 和 RFM 电流。示例配置明确采用以下可替换估算：`I5AB=I5PB=IDD0`，RFM 动态电流默认等于对应刷新动态电流。若获得实测值，可在 `mempowerspec` 中设置 `idd5ab`、`idd5pb`、`iddrfmab` 和 `iddrfmpb`；也可以用 `rfmAbPowerRatio` 与 `rfmPbPowerRatio` 调整 RFM 相对刷新动态功耗。

可选的 `interfacepowerspec.readEnergyPerBit` 和 `writeEnergyPerBit` 用于加入封装外部链路能量。示例把二者设为零，因为所用 IDD4 被视为已校准的读写总电流，重复加入接口项会造成双计数。

## 构建和运行

```bash
cd /workspaces/ramulator2/DRAMPower
cmake -S . -B build -DDRAMPOWER_BUILD_CLI=ON
cmake --build build --parallel

./build/bin/cli \
  -c examples/hbm34/cli_config.json \
  -t examples/hbm34/example_trace.csv \
  -m examples/hbm34/hbm3_6400_estimated.json \
  -j hbm3_result.json

./build/bin/cli \
  -c examples/hbm34/cli_config.json \
  -t examples/hbm34/example_trace.csv \
  -m examples/hbm34/hbm4_8000_estimated.json \
  -j hbm4_result.json
```

HBM3/HBM4 的 JSON 输出额外包含 `SimulationDurationSeconds`、`AveragePowerWatts` 和 `Model`。`Model.AbsoluteAccuracyValidated=false` 是有意保留的标记；在得到厂商 IDD5/RFM/温度/工艺参数或板级实测数据后，应先替换估算参数并做校准，再用于绝对功耗结论。

平均功耗的观察窗口由最后一个命令的时间戳决定。实际轨迹应以 `END` 结束，并把它放在最后一项读写、刷新或 RFM 完成之后。

## 参数修改入口

- 组织：`memarchitecturespec`，必须与产生轨迹的 Ramulator2 organization 对应。
- 时序：`memtimingspec`，值按完整 CK；`tCK` 使用秒。
- 电流：`mempowerspec`，使用安培；电压使用伏特。
- 数据活动：`datapattern`，三个 rate 的范围为 0 到 1。HBM-Power 文档指出随机数据 0.5 可视为偏保守上界；带 DBI/扰码的实际有效活动率通常应通过轨迹或实测校准。
- 模型可信度：`modelMetadata`，替换参数时同步记录来源、范围和验证状态。
