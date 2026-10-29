# 端口、微架构与资源生命周期

## 独立源码与模块分工

新桥只编译 `ucie_mc_bridge/rtl/files.f`。wire format 与当前系统 AoU256 相同，RTL 是独立实现。
没有旧桥 package、include 或模块实例。第一版将 parent、child、缓存、拆分、排序与完成
集中在 `umcb_transaction_core`，这些状态均由硬件维护，不以空文件模拟模块拆分。

| 模块 | 输入 → 输出 | 职责 |
|---|---|---|
| umcb_pkg | package | 帧、消息、字段、信用、内部结构体 |
| umcb_fdi_rx | 2000 bit帧 → 320 bit消息 | 一帧缓存、跨帧拼接、MsgStart、头信用 |
| umcb_aou_decoder | 消息 → request_t / write_t | RP、SIZE、对齐、4 KiB、DLENGTH校验 |
| umcb_aou_credit_manager | 头/Misc信用、实际释放 → grant / response_allowed | 两类远端响应额度与三类本地接收额度 |
| umcb_mc_credit_manager | 归还脉冲、接受事件 → LPR/HPR/WR计数 | RMW双资源；每周期一次合并更新 |
| umcb_transaction_core | cmd/W ↔ 全部MC接口、response_t | 请求、AW/W解耦、缓存、child、token、pointer、排序、状态和退休 |
| umcb_aou_encoder | response_t → AoU消息 | USER/ID/RESP/LAST与大端数据映射 |
| umcb_fdi_tx | 消息/grant → FDI帧 | 48 granule聚合、跨帧、稳定输出、最终片段retire |
| ucie_mc_bridge_top | FDI ↔ MC HIF | 接线、统计和错误汇总 |

MC入口没有引用原 `hif_cmd_write/len/size` 接口，直接输出新命令编码与引脚。

## MC端口（方向相对桥）

| 端口 | 方向 | 位宽 | 解释 |
|---|---|---:|---|
| hif_cmd_valid | 出 | 1 | 命令有效，stall时保持 |
| hif_cmd_stall | 入 | 1 | 1阻塞；valid && !stall接受 |
| hif_cmd_type | 出 | 2 | 00写、01读、10 RMW；其他不发出 |
| hif_cmd_addr | 出 | 40 | 测试契约为32 B对齐字节地址，完整64 bit范围先检查 |
| hif_cmd_pri | 出 | 2 | LPR=0；QoS>=8的普通读映射到HPR_CODE，默认2 |
| hif_cmd_token | 出 | 53 | child关联，返回查表，不等于上游ID |
| hif_cmd_length | 出 | 1 | LENGTH_ONE/LENGTH_TWO，默认0/1 |
| hif_cmd_wdata_ptr | 出 | 19 | child写块关联标识，等控制器请求 |
| hif_cmd_autopre | 出 | 1 | AUTO_PRECHARGE，默认0 |
| hif_cmd_latency | 出 | 11 | COMMAND_LATENCY，默认0；不是测得延迟 |
| hif_lpr_credit/hif_hpr_credit/hif_wr_credit | 入 | 各1 | 本周期归还一项对应资源 |
| hif_wrecc_credit | 入 | 2 | 保留；没有依赖该资源的操作 |
| hif_rdata_valid | 入 | 1 | 无ready；每个有效周期必须捕获 |
| hif_rdata_end | 入 | 1 | 当前child最后word；与valid共同判定 |
| hif_rdata_token | 入 | 53 | 查找接受过的读child |
| hif_rdata | 入 | 256 | 每word32 B |
| hif_rdata_uncorr_ecc_err | 入 | 1 | 记录SLVERR |
| hif_rdata_addr_err | 入 | 1 | 记录DECERR，优先于SLVERR |
| hif_rdata_crc_err | 入 | 1 | 记录SLVERR，与UCIe链路CRC不同 |
| hif_wdata_valid | 出 | 1 | pointer请求队列非空时供数 |
| hif_wdata_stall | 入 | 1 | 阻塞时保持数据、mask和end |
| hif_wdata | 出 | 256 | pointer数据块当前word |
| hif_wdata_mask | 出 | 32 | 默认1写；MASK_ONE_WRITES可配置极性 |
| hif_wdata_end | 出 | 1 | 该child最后word；不是parent WLAST |
| hif_wdata_ptr_valid | 入 | 1 | 无ready的写数据请求 |
| hif_wdata_ptr | 入 | 19 | 查找接受过且尚未请求的写child |
| hif_wdata_ptr_addr_err | 入 | 1 | 与pointer_valid同拍；该child错误终止，后续不供数 |
| hif_go2critical_lpr/hpr/wr | 出 | 各1 | 当前关闭，固定0 |

clk/rst_n是桥时钟/低有效异步复位。外部负责同步释放复位及两端共同初始化。
名称差异（如波形中的 hif_cmd_len、hif_wdata_ptr_err）应在实际MC wrapper中转换。
截图未给出parity端口，本模块没有自行扩展parity信号。

## 参数

顶层数据接口固定AoU256/MC256。RESOURCE_PLANES=1..4；REQUEST_SLOTS每RP每方向4，
parent总数=2*RP*REQUEST_SLOTS，必须<=64。CHILD_SLOTS默认32、范围1..256。
MAX_BURST_BYTES默认4096，32的倍数且<=4096。WDATA_GRANULES默认64，8..4096。
TX_FLUSH_CYCLES默认2；验证台使用8，实际配置在每次结果中记录。

INITIAL_LPR/HPR/WR默认24/8/32，这是波形测试值，真实MC必须重新确认。
TWO_WORD_COMMANDS可关闭；LENGTH_ONE/TWO必须不同。POSTED_WRITE_ACK默认0；显式为1才向MC发写。
其他参数对应上表。结构参数改变必须重编，不能只修改说明性JSON后认为硬件已改变。

## 内部存储与预留

每parent保存请求字段、顺序号、输入拍数、下一个待拆word、完成word数、返回拍号和错误。
每parent有MAX_BURST_BYTES的字节存储及mask位图：写parent临时保存数据，读parent预留返回存储。
RAM不整体复位，元数据阻止未初始化数据被作为有效业务读取。

每RP独立W FIFO，容量floor(WDATA_GRANULES/7)拍，同时按实际7/8 granule约束使用量。
W可先于AW，按同RP最早未收齐AW配对。搬入已预留parent缓存才返还WDATA额度。
第一版请求槽/parent记录保持至最终响应FDI握手，之后返还AW/AR信用。

child窗口是有限表，不要求一次分配整笔4 KiB的全部child。每child最多两个word；
写块就绪后发命令。token为单调53 bit序号，pointer使用其低19 bit，分配前检查活动pointer碰撞。
实际MC必须确认该指针编码与释放后不再出现旧请求的保证。

pointer请求队列深度=CHILD_SLOTS，每个写child至多请求一次。未知/重复请求报错。
返回数据无ready，每个有效周期捕获一个word；返回空间在parent接收时已经预留。
不同token可乱序、有空洞；所有child结束后按原始SIZE/LEN恢复上游R拍。
同RP/ID/方向的parent按顺序返回；不同ID可独立准备。写相关的地址重叠等待较早parent内存侧交付完成。

## 完成、错误与复位

POSTED_WRITE_ACK=1时，B含义是全部子命令/数据已被MC接受，并非实际DRAM SERVICE完成。
MC必须接管后续写责任、相关访问排序和错误报告。默认0时写请求被消费并返回SLVERR，
不发MC写命令。当前没有service_complete模式，也没有借用Ramulator事件伪造完成。

地址超40 bit返回DECERR，LOCK和本地容量不支持返回SLVERR。写拒绝仍消耗其全部W。
ECC/CRC/地址错误聚合到parent状态。pointer地址错误按该child已失败处理，credit仍须MC正确归还。
同时pointer错误和其他child最后数据拍可累加完成，避免丢计数。

error_code低位：0=越界WSTRB，1=无MC额度却接受，2=未知/重复pointer，3=pointer请求队列溢出，
4=未知token，5=读END错误，6=非法parent退休，7=越界退休位。16=FDI格式，17=AoU请求，
18=AoU信用，19=MC信用。均为粘滞诊断；不是通用错误恢复协议。

父事务最终响应消息的最后片段被FDI接受后才退休。MC credit归还、pointer请求、数据接受、
父事务响应和tag退休是不同事件。运行中不支持单边热复位或撤销已接受的MC操作。

## 性能与物理实现边界

该版RX一次解析一个完整消息，TX有消息暂存和组帧阶段，单命令发出也有寄存阶段；
不能从256 bit接口宽度直接推导持续满带宽。所有时间均应由事件/VCD测得。
独立测试时钟为10 ns，不是MC工作频率承诺。

尚未做目标工艺综合、SRAM映射、CDC、STA或PPA；字节存储与动态选择逻辑需要在具体工具中检查。
无真实MC时也没有MC内部RMW命令或DRAM功耗证据。行为模型只检查协议与功能。
