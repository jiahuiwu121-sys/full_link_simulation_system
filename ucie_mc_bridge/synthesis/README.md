# 综合边界

源码入口为 `../rtl/files.f`，顶层为 `ucie_mc_bridge_top`。不要加入tb/或SystemC wrapper。
需使用支持SystemVerilog package、结构体及静态数组的工具，指定真实工艺库和存储器映射。

`constraints.sdc` 的1ns只是占位模板，不能作为项目已达到1GHz的证据。接入MC后必须补齐
输入输出延迟、时钟不确定度、复位同步/恢复移除约束和RAM时序，再报告面积/Fmax/功耗。
当前环境验证为Verilator lint/仿真，没有目标工艺综合或PPA结果。
