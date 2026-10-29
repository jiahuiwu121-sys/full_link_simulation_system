# FDI / 原生 SystemC 接线

裸RTL集成：读取 `../rtl/files.f`，顶层 `ucie_mc_bridge_top`，将全部HIF端口接到新MC。
顶层只有桥RTL，不引用旧桥或内存后端。没有MC时仅可进行构建/展开，不能凭空完成访存。

仿真集成：`systemc_fdi_endpoint.hh` 是header-only表示适配器。FDI对象使用
`ucie-model/src/ucie_fdi.h` 的 `FdiFlit`，不依赖旧桥。MC端每个引脚为sc_in/sc_out。

```cpp
ucie_mc_bridge::SystemCFdiEndpoint endpoint("mc_endpoint", result_dir, true);
endpoint.clk(fabric_clk);
endpoint.rst_n(reset_n);
endpoint.link_rx(ucie_to_mc_fifo);
endpoint.link_tx(mc_to_ucie_fifo);
// 必须逐一绑定所有endpoint.hif_* 到对应MC信号；不可悬空后声称闭环。
```

MC驱动/采样遵守同步端口规则：输入在采样沿前稳定；适配器两边沿推进RTL，输出在后续采样沿前发布。
MC独立时钟必须先实现CDC，不能直接接异步信号。复位运行后不支持单边热复位。

构建 `bash env/build_ucie_mc_bridge.sh` 后，从打印目录获取 `Vucie_mc_bridge_top.h` 与
`Vucie_mc_bridge_top__ALL.a`。将wrapper作为新编译单元接入现有gem5原生SystemC构建，
include路径包括gem5/src/systemc/ext、ucie-model/src、Verilator include和模型目录。
链接模型库及同一份Verilator runtime/trace runtime；绝不能添加另一套libsystemc。
适配器使用VerilatedContext和1fs时间，完整记录双向FDI。

目前wrapper已做原生gem5 SystemC头文件的C++语法检查，尚未作为旧系统默认endpoint运行。
独立回归已覆盖新RTL的FDI↔MC模型闭环；不将它表述为CPU/GPU/NPU通过真实MC的系统验收。
原有运行脚本和后端选择器保持原语义，使用新桥需显式在调用侧实例化本endpoint或裸RTL。
