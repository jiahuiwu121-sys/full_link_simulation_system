# 用户全链路配置

本目录给研究人员提供可复制、可校验、可直接运行的系统配置。入口模板为
[`full-link-research-template.json`](full-link-research-template.json)，完整机器可读约束位于
[`../../env/profile_schema.json`](../../env/profile_schema.json)。建议复制模板并修改 `name`，
保留原文件作为参数对照。

模板本身是标准JSON。每个真实模块之前都有一个`_<模块名>_module`说明块，固定包含
`模块说明`和`当前系统支持的可选选项`。研究人员先读说明块，再修改紧随其后的同名配置模块；
真实配置内不混入说明字段。编译后，原始`system_profile.json`保留这些说明便于交接，
`runtime_topology.json`和`topology_resolved.json`会自动移除全部下划线说明块及`$schema`。

## 快速使用

```bash
cp configs/user/full-link-research-template.json configs/user/my-experiment.json
# 按每个模块之前的说明块编辑真实参数；说明块可保留，也可以删除
bash env/build_profile.sh configs/user/my-experiment.json
bash env/run_system_profile.sh configs/user/my-experiment.json
# run_profile.sh保留为兼容别名
bash env/run_profile.sh configs/user/my-experiment.json
# 完整负载、只读和只写扫描
bash env/run_profile_sweep.sh configs/user/my-experiment.json
```

`run_system_profile.sh`会编译配置、检查连接和理论容量，根据`execution.mode`选择普通CPU或
XPU构建，并在构建签名不匹配时自动重建。随后它调用traffic/CPU路径或GPU/NPU路径，二者
使用同一套AXI、UCIe和Ramulator2配置。编译结果位于`build/system_profiles/<name>/`，并复制到每次结果目录的
`system_profile/`。其中 `system_profile.json` 是用户输入，`topology_resolved.json` 是解析后的
连接图，`frontend_plan.json`是真实设备启动计划，`protocol_profile.json`是协议档案，
`capacity_report.json`是理论容量检查，`run.env`是实际传给运行脚本的参数。

配置是默认参数来源；调用命令时显式设置的同名`SS_*`环境变量优先，可用于短期缩短请求数或
关闭浏览器。前端程序、参数、设备库和kernel始终由`execution`生成的启动计划决定，避免旧的
设备环境变量把一次CPU实验意外切换成GPU/NPU实验。

## 配置分区

|分区|可配置内容|约束或当前语义|
|---|---|---|
|`sources[]`|来源名称、`traffic/cpu/gpu/npu`标签及任意研究元数据|用于审计；真实设备由`execution`选择|
|`execution`|traffic、CPU、GPU、NPU及联合模式；程序、参数、环境、设备库和kernel|GPU/NPU仍由宿主CPU启动；Vortex至少需要2个CPU上下文|
|`workload`|压力负载、预热/测量/冷却请求数、请求大小、工作集、写比例、在途数|只在`execution.mode=traffic`时生效|
|`protocol`|协议档案、AXI地址/ID审计值、AoU帧参数、外层FIFO深度|当前线格式只支持`aou-format6-256`；FIFO深度可在运行时改变|
|`axi`|数据宽度、逻辑端口周期|宽度为256/512/1024bit，改变宽度会重编译|
|`axi_ports[]`|端口名称、目标UCIe链路、来源标签|多端口时数量必须为2的幂|
|`ucie_links[]`|lane、GT/s、NRZ/PAM4、目标内存节点|lane和速率为正数；最多64条链路|
|`memory_nodes[]`|HBM3/HBM3E/HBM4/LPDDR5/LPDDR6、controller数、自定义配置|controller数必须为正的2次幂|
|`routing`|`single/address_interleave`及条带大小|多端口必须交织；条带为2的幂且覆盖完整请求|
|`bridge`|Resource Plane、TLM在途槽、聚合器时钟比、`systemc/rtl`存储桥实现|RP为1..4；每条链路的AXI端口数必须等于时钟比；RTL接口见[桥接文档](../../docs/storage-bridge-rtl.md)|
|`backend`|controller队列、parent/child容量、提交宽度、响应保持、时钟缩放、功耗|时钟缩放仅用于自动生成的HBM4受控实验|
|`simulation`|最大tick、确定性AXI背压、UCIe重放注错|重放开启时使用可重复的2%物理Flit错误|
|`observability`|原生采样周期、HTML打开/服务、HTTP端口|最终快照始终输出，采样周期只影响时间序列粒度|
|`sweep`|混合负载点、方向饱和点、方向、混合写比例|负载范围为0到400%，不含0|
|`requirements`|最低有效带宽、最大桥延迟、最低链路利用率|闭环正确性与性能目标分别判定|

## 连接和容量规则

- 一个AXI端口只能连接一条UCIe链路；多个AXI端口可以聚合到同一条链路。
- 每条UCIe链路当前只连接一个独立memory node；同一memory node不能被多链路共享。
- 每条链路的AXI端口数必须等于`bridge.fabric_clock_ratio`，形成确定性时分gearbox。
- 多端口的`routing.stripe_bytes`必须是2的幂，并能被请求大小整除，避免请求跨端口。
- `bridge.tlm_slots`不能超过聚合后每端口分到的10-bit AXI ID空间。
- `backend.submit_width`不能超过`backend.child_slots`。
- `requirements.minimum_effective_bandwidth_GBps`超过AXI、gearbox、UCIe/AoU或内存理论上限时，
  配置编译会直接拒绝。

## 内存选择

自动配置支持：

|`standard`|自动预设|功耗说明|
|---|---|---|
|`HBM3`|HBM3 16Gb 8-Hi，6.4Gbps|公开HBM3E数据估算|
|`HBM3E`|HBM3E 24Gb 8-Hi，8.0Gbps|使用HBM3命令/状态实现，参数按速率缩放|
|`HBM4`|HBM4 32Gb 8-Hi，8.0Gbps|支持`clock_scale`受控时钟实验|
|`LPDDR5`|LPDDR5 16Gb x16，6400|公开参考参数估算|
|`LPDDR6`|LPDDR6 16Gb x12，10667 BL24|两个controller表示一个x24通道的两个subchannel|

若需要自定义Ramulator2时序，在每个`memory_nodes[]`项加入相对配置文件路径：

```json
"config": "../../ramulator2/example_configurations/your_external.yaml"
```

只要一个节点提供`config`，所有节点都必须提供。自定义External配置自行决定时序、通道和
功耗插件，不要再用模板中的`clock_scale`表达另一个时序实验。

## 前端边界

`execution.mode`现在会真实选择前端：`traffic`运行压力源，`cpu`运行独立X86程序，`gpu/npu`
及联合模式加载Vortex SimX或CoralNPU。GPU-only和NPU-only仍包含负责启动设备的宿主CPU；
这不是无CPU的裸设备仿真。`sources[].type`继续作为审计标签，不替代真实启动配置。

CPU模式省略`host.binary`时使用构建产生的`gem5_axi/build/ramulator_check`。XPU模式省略路径时
使用项目锁定版本的验收程序、设备库和kernel。用户路径按项目根目录解析；启动前统一入口会
检查所有文件，缺失的默认XPU产物会触发`env/build_xpu.sh`，构建后仍缺失则立即失败。

当前可用模式为：

|`execution.mode`|实际组成|底层配置|
|---|---|---|
|`traffic`|AxiPacketTester|`run.py --mode traffic`|
|`cpu`|1个X86TimingSimpleCPU|`run.py --mode cpu`|
|`gpu`/`cpu_gpu`|宿主CPU + Vortex SimX|`run_xpu.py`|
|`npu`/`cpu_npu`|宿主CPU + CoralNPU|`run_xpu.py`|
|`cpu_gpu_npu`|宿主CPU + Vortex + CoralNPU|`run_xpu.py`|

## 协议档案

当前支持`aou-format6-256`：AXI地址64bit、物理AXI ID 16bit、路由ID空间10bit、AoU物理帧
256B、逻辑载荷250B、最多4个Resource Plane。上述值必须作为一个已验证档案整体使用；配置
编译器会拒绝单独修改帧或载荷大小。`fdi_fifo_depth`和`memory_fifo_depth`不改变线上格式，已
作为SimObject运行参数接入，适合做缓存容量和背压实验。

仍未开放为任意数值的内部参数包括AxiMux每通道FIFO、AXI2Flit按RP信用深度、CRC散布位置和
4 RP上限。新增线格式时应在`env/protocol_profiles.py`增加完整档案，同时修改共享协议头、
两端实现和离线检查器，不能只修改JSON中的一个数字。
