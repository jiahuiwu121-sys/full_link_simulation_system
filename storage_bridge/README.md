# StorageBridge

本目录保存 UCIe/AoU 到存储 HIF 的可综合 SystemVerilog 桥接实现。系统集成、
信号定义、数据所有权和验证方法见
[`docs/storage-bridge-rtl.md`](../docs/storage-bridge-rtl.md)。

`rtl/files.f` 列出综合顺序；`Makefile` 提供 256/512/1024 bit 参数化 lint。
`tests/` 保存 credit 守恒、RX 帧间隔、跨帧 TX、写描述符生命周期和非法响应回归。
执行 `python3 env/test_storage_bridge.py --matrix` 可覆盖三种位宽与 RP1/2/3/4。

生成代码目录由 `env/storage_bridge_config.py --build-dir` 给出，默认形如
`build/storage_bridge-rtl-256-rp1-v2-r4-o8-w64-f2-t2`，不提交 Git。位宽、RP、
描述符数、tag 数和 FIFO/封帧参数参与目录与构建签名；运行记录还核对源码及
库文件 SHA256。`synthesis/` 提供工艺库约束下的综合交接模板，当前不包含 PPA 结论。
