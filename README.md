# full_link_simulation_system

CPU / Vortex GPU / CoralNPU → 原生AXI256 → AXI2Flit → UCIe → 在线Ramulator2 + 真实数据backing + DRAMPower的统一系统。

| 普通源码目录 | 职责 |
|---|---|
| gem5_new | 三源设备、观察器、工作负载及外部依赖适配 |
| gem5_axi | gem5原生TLM、AXI256 Master、在线内存桥及验证 |
| axi2flit | AXI与Flit转换 |
| ucie-model | UCIe链路、重放与观察接口 |
| gem5 | CPU、事件队列、原生SystemC/TLM及设备框架 |
| coralnpu | NPU硬件、RTL仿真与在线AXI适配 |
| protocol/include | 两端共享的AoU帧格式 |

独立内存模拟器位于 [`ramulator2/`](ramulator2/README.md)，包含 HBM3、HBM4、LPDDR5、LPDDR6 及 DRAMPower 功耗模型，其构建和使用说明见该目录 README。全链路默认在线后端为 `ramulator2`；接入契约、配置和验收见[在线后端说明](docs/ramulator-integration.md)。

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
[开发说明](docs/development.md)。Vortex外部版本在env/sources.lock.json，内部导入来源在
[env/internal_imports.json](env/internal_imports.json)。

历史 memsim 交接验收见[验收记录](docs/handoff-validation.md)：
完整构建、19项原生测试、7组在线内存、4组GPU/NPU、旧链路/RAM兼容，以及新目录恢复构建和闭环验证通过。
旧AXI256与monorepo报告继续保留；HTML交接请复制整个用例目录。
结果/构建产物和integrate_doc本地交接资料不入库。原/mnt/d/storagestacked保留。
运行结果不随Git克隆分发，需要在本机运行生成。HTML查看方式见配置指引；推荐通过本机HTTP服务打开。
主仓库：https://github.com/jiahuiwu121-sys/full_link_simulation_system 。新提交说明使用中文。

本次导入的源码版本见 [env/upload_sources.json](env/upload_sources.json)；两部分原始 Git 历史均已保留。
