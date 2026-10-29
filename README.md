# full_link_simulation_system

CPU / Vortex GPU / CoralNPU → 原生可配置宽度AXI → AXI2Flit → 可配置并行UCIe模块 → 在线Ramulator2 memory nodes + 唯一数据backing + DRAMPower的统一系统。

第二阶段拓扑扩展已经完成：支持 1/2/4/... 个独立 TLM、AXI、UCIe 和内存节点，按地址
条带路由；AXI 可在构建时选择 256/512/1024 bit，UCIe 的 lane、速率和调制可按模块配置。
`storagestacked.system.v2` 系统配置还支持多个 AXI 端口通过周期级仲裁和全局 ID 重映射共享
一条 AXI2Flit/UCIe/内存路径。配置编译器会检查连接、容量和构建位宽，并在必要时自动重编译。
每条路径均保留独立原始证据和统计，根目录聚合吞吐/延迟/功耗；在线页面显示逐链路利用率，
`check_topology.py` 校验地址归属及跨层守恒。配置格式、运行命令、输出证据和当前边界见
[拓扑扩展说明](docs/topology-extension.md)和[用户系统配置](docs/system-profiles.md)。

拓扑可用 `memory.standard` 直接生成 HBM3、HBM3E、HBM4、LPDDR5 或 LPDDR6 的 Ramulator2 External 配置
及匹配功耗输入。`env/run_configuration_matrix.sh` 验收 1/2/4/8 模块与 RP1/2/4 的组合，
`env/run_axi_width_matrix.sh` 重建并验收 AXI256/512/1024 后恢复默认位宽。

图中 4×AXI512、UCIe x64@32GT/s、单 HBM3 stack 的配置可直接运行：

```bash
bash env/run_system_profile.sh configs/system/llm8b-4axi512-ucie64-hbm3.json
```

研究人员可从[`configs/user/full-link-research-template.json`](configs/user/full-link-research-template.json)
复制一份完整用户配置。该模板同时暴露真实traffic/CPU/GPU/NPU前端、已验证协议档案、
AXI、聚合器、UCIe、内存、Ramulator2容量、功耗、采样、负载扫描和验收目标；统一入口为
`bash env/run_system_profile.sh <配置.json>`，`run_profile.sh`保留为兼容别名。字段说明与边界见
[`configs/user/README.md`](configs/user/README.md)。

同一配置的混合负载曲线与只读/只写饱和验收使用：

```bash
bash env/run_profile_sweep.sh configs/system/llm8b-4axi512-ucie64-hbm3.json
```

| 普通源码目录 | 职责 |
|---|---|
| gem5_new | 三源设备、观察器、工作负载及外部依赖适配 |
| gem5_axi | gem5原生TLM、可配置宽度AXI Master、在线内存桥及验证 |
| axi2flit | AXI与Flit转换 |
| ucie-model | UCIe链路、重放与观察接口 |
| gem5 | CPU、事件队列、原生SystemC/TLM及设备框架 |
| coralnpu | NPU硬件、RTL仿真与在线AXI适配 |
| protocol/include | 两端共享的AoU帧格式 |
| storage_bridge | 存储侧 AoU/FDI 到 HIF 的 RTL、描述符/写数据缓存、事务跟踪及独立回归 |
| ucie_mc_bridge | 独立的 FDI→新 MC HIF RTL 桥；token、pointer、MC信用、读返回重组及验证模型 |

独立内存模拟器位于 [`ramulator2/`](ramulator2/README.md)，包含 HBM3/HBM3E、HBM4、LPDDR5、LPDDR6 及 DRAMPower 功耗模型，其构建和使用说明见该目录 README。全链路默认在线后端为 `ramulator2`；接入契约、配置和验收见[在线后端说明](docs/ramulator-integration.md)。

面向另一个独立MC的新桥位于 [`ucie_mc_bridge/`](ucie_mc_bridge/README.md)，与现有
`storage_bridge` 并列且RTL源码/构建独立。`bash env/run_ucie_mc_bridge_validation.sh`
验证FDI↔新HIF模型，`bash env/build_ucie_mc_bridge.sh`导出裸接口顶层模型。
当前MC尚缺，报告明确标记模型验证，不代表真实MC兼容性、功耗或PPA；原Ramulator路径保持不变。

整体架构、核心文件职责、上下游接口及一次访存的完整路径见[当前系统解读](docs/code-reading/09-current-system-walkthrough.md)。[当前全文件清单](docs/code-reading/current-file-map.csv)包含主仓库与已初始化的 Vortex 递归依赖；核心文件人工说明与其余文件的静态目录分类分别标记。

源码、构建、结果和本地交接目录的职责与维护位置见[目录详解](docs/code-reading/10-directory-guide.md)；[全目录清单](docs/code-reading/directory-inventory.csv)覆盖当前工作区实体目录及目录符号链接。

每次运行自动输出各模块独立统计、全链路汇总、按源延迟分位数、请求关联和DRAM功耗时间序列；批次运行同时生成指标总索引。输出文件、原生指标兼容口径、任务/kernel窗口及功耗估计范围见[实验指标说明](docs/experiment-metrics.md)。

每次运行结束后自动生成在线可视化：结果总索引 `results/index.html`、本次运行 `index.html` 和各用例 `metrics.html`，包含逐段带宽/利用率、延迟CDF与互斥分解、阻塞、功率、队列及DRAM命令图表。直接调用两个gem5配置的单用例也会自动完成链路/DRAM页面生成和独立统计校验。本地HTTP服务自动启动，VS Code容器环境通过浏览器桥接打开；设置 `SS_VISUALIZATION_OPEN=0` 可关闭自动打开浏览器，`SS_METRICS_BIN_NS` 可配置带宽曲线的期望时间分箱。

默认 AXI256 周期为 666667fs，单方向载荷容量约 48GB/s，与默认 16lane×24GT/s NRZ UCIe 裸容量匹配；RamulatorBackend 默认每个 250ps native tick 最多尝试提交 8 个独立 child。使用受控稳态压力扫描研究饱和点和排队延迟：

```bash
SS_EXPERIMENT_LABEL=bandwidth-sweep bash env/run_bandwidth_sweep.sh
```

该入口运行 10%、25%、50%、75%、100%、125% 六档供给负载，输出 `bandwidth_sweep.json/csv/md` 和包含吞吐—延迟曲线的 `index.html`。普通正确性程序仍用于功能验证，不能替代压力扫描。

2026-09-17 已完成在线替代后的构建与验收：八组 CPU/定向、四组 GPU/NPU、旧 RAM/simple 兼容链路均通过，包含真实数据、实际命令、DRAMPower 和独立 VCD 审计。[本机结果与时序反馈](docs/ramulator-integration.md#2026-09-17-本机验收)记录配置、报告位置及估算功耗边界。

gem5和coralnpu已转为主仓库普通源码，直接打开gem5/src、coralnpu/hdl和coralnpu/hw_sim，
不再使用Git子模块链接或重复嵌套的gem5/gem5、coralnpu/coralnpu目录。
只有vortex-gpu/vortex及其递归依赖保留为外部子模块。
这次本地快照导入的来源及版本核实边界见env/vendored_sources.json；历史内部模块导入见env/internal_imports.json。
目录维护与依赖包兼容见[内置源码说明](docs/source-layout.md)。

mem_sim目录已移除；其历史分支保留为可选构建，使用前需要取得匹配源码。默认构建不再依赖mem_sim。单独检查内置源码可执行：

```bash
python3 env/check_sources.py --only gem5 coralnpu
```

```bash
git clone --recurse-submodules https://github.com/jiahuiwu121-sys/full_link_simulation_system.git
cd full_link_simulation_system
bash env/bootstrap_xpu.sh
bash env/build_xpu.sh
bash env/run_ramulator.sh results/acceptance-ramulator2
bash env/run_xpu.sh results/acceptance-xpu
```

新机器先按[主机条件](docs/setup.md#1-主机条件)安装基础工具。bootstrap_xpu/build_xpu
包含CPU基础环境与构建；GCC、Python等版本由锁文件指定，无需手动选择编译器。
仅验证CPU时可以使用env/bootstrap.sh、env/build.sh、env/run_ramulator.sh。

首次安装、依赖包恢复和无依赖包配置见[配置与交接指引](docs/setup.md)。
环境版本与操作见[env/README.md](env/README.md)，分支协作、历史追溯、源码归属见
[开发说明](docs/development.md)，存储侧可综合桥接的信号与验证方法见
[StorageBridge RTL](docs/storage-bridge-rtl.md)。Vortex外部版本在env/sources.lock.json，内部导入来源在
[env/internal_imports.json](env/internal_imports.json)。

存储侧 RTL 桥的可运行示例为
[`configs/system/storage-bridge-rtl-hbm4.json`](configs/system/storage-bridge-rtl-hbm4.json)，
使用 `bash env/run_system_profile.sh configs/system/storage-bridge-rtl-hbm4.json` 运行。
桥内描述符/写缓存/事务表、跨帧响应和credit由RTL维护；
`bash env/run_storage_bridge_validation.sh` 验证定向、CPU、大粒度压力与SystemC参考差分。
独立报告新增 `storage_bridge_summary.json`、事件CSV与可选RTL VCD；当前不包含桥接PPA结论。

历史 memsim 交接验收见[验收记录](docs/handoff-validation.md)：
完整构建、19项原生测试、7组在线内存、4组GPU/NPU、旧链路/RAM兼容，以及新目录恢复构建和闭环验证通过。
旧AXI256与monorepo报告继续保留；HTML交接请复制整个用例目录。
结果/构建产物和integrate_doc本地交接资料不入库。原/mnt/d/storagestacked保留。
运行结果不随Git克隆分发，需要在本机运行生成。HTML查看方式见配置指引；推荐通过本机HTTP服务打开。
主仓库：https://github.com/jiahuiwu121-sys/full_link_simulation_system 。新提交说明使用中文。

本次导入的源码版本见 [env/upload_sources.json](env/upload_sources.json)；两部分原始 Git 历史均已保留。
