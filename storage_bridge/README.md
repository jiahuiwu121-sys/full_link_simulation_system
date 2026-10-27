# StorageBridge

本目录保存 UCIe/AoU 到存储 HIF 的可综合 SystemVerilog 桥接实现。系统集成、
信号定义、数据所有权和验证方法见
[`docs/storage-bridge-rtl.md`](../docs/storage-bridge-rtl.md)。

`rtl/files.f` 列出综合顺序；`Makefile` 提供 256/512/1024 bit 参数化 lint。
生成代码位于 `build/storage_bridge-rtl-<width>-rp<planes>`，不提交 Git。位宽与
Resource Plane 数量各自占用独立构建目录，切换用户配置时不会复用参数不匹配的
Verilated 模型。
