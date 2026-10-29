# 本机验证记录

日期：2026-10-29（Asia/Shanghai）。工具：Verilator 5.020。桥时钟10ns，时间精度1fs。

## 主回归

入口：`bash env/run_ucie_mc_bridge_validation.sh`。
结果：`results/20261029-mc-hif-rp1-ack1-r09/`，18项全部通过。
每项保留VCD、事件、完整FDI日志、记分板结果和离线审计；报告入口index.html。

| case | 内容 |
|---|---|
| 0 | 完整写与读回 |
| 1 | 掩码写、RMW、未使能字节不修改 |
| 2 | W先于AW |
| 3 | 窄传输、lane映射、周边字节保护 |
| 4 | LPR/HPR、不同token乱序返回 |
| 5 | 4KiB parent、输入消息跨帧 |
| 6 | LOCK拒绝；ACK0配置下拒绝未确认posted写 |
| 7 | CRC错误返回SLVERR |
| 8 | MC地址错误返回DECERR |
| 9 | 未知pointer置协议错误bit2 |
| 10 | 混合读写响应 |
| 11 | 两笔同ID不同地址读，控制器乱序而上游保持事务顺序 |
| 12 | 同地址RAW保护 |
| 13 | pointer地址错误；与其他child最终W同时完成不丢计数 |
| 14 | 未知token置协议错误bit4 |
| 15 | 超40bit地址拒绝，未向MC截断发出 |
| 16 | 不可纠正ECC返回SLVERR |
| 100 | 独立TX跨帧、背压和最后片段tag退休 |

0..16用例全程断言命令stall稳定、WDATA stall稳定和FDI输出背压稳定。
正常用例检查parent排空、响应守恒、MC信用恢复；预期协议错误用例明确校验错误位图。
离线Python解析器从完整FDI日志重新检查消息边界、帧数、请求/终止响应及打包granule。

## 其他检查

- RP2定向读写、RMW、早到W、窄访问、乱序、4KiB通过。
- RP4的上述项目及同ID顺序、RAW、pointer错误通过：`results/20261029-mc-hif-rp4-ack1-r01/`。
- 生产默认ACK0拒绝写且无MC命令通过：`results/20261029-mc-hif-rp1-ack0-r02/`。
- 默认/RP4及另一组自定义参数RTL lint通过；参数范围、长度编码、存储对齐的负例拒绝通过。
- 仅复制新目录至临时目录，脱离主仓库env和旧桥，运行本目录tools/run.py --lint通过。
- 生产裸顶层Verilator静态库导出通过；SystemC wrapper对gem5原生SystemC头文件的C++17语法检查通过。
- 原storage_bridge lint通过；原桥RTL、gem5_axi及Ramulator运行入口没有修改。

额外RP/ACK记录为开发过程定向回归；精确源码与参数见各自manifest/结果，不将不同运行视为同条件性能对照。

## 结论边界

这是新桥对明确声明的MC HIF行为模型的功能与协议验证；没有真实MC、PHY、DRAM时序/功耗或目标工艺PPA验收。
SystemC适配器可供后续接线，但尚未切换原CPU/GPU/NPU默认运行入口或完成真实MC系统验收。
生产写需明确启用posted契约；实际服务完成确认仍需MC提供相应语义/信息。
