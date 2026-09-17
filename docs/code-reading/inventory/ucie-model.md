# ucie-model 文件索引

共 20 条；源码 9 条、2,333 行。符号展示最多 12 个，依赖展示最多 8 个；HTML/CSV 保留更多提取项。

[索引说明与模块统计](README.md) · [系统集成语义解读](../03-integration-code.md) · [上游子系统解读](../04-upstream-code.md)

| 文件 | 类型 / 行数 | 职责提示（自动归类） | 候选符号及行号 | 静态依赖提示 |
|---|---|---|---|---|
| [ucie-model/.gitignore](../../../ucie-model/.gitignore) | config / 21 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/INTERFACE.md](../../../ucie-model/INTERFACE.md) | documentation / 97 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/MODELING_AND_VERIFICATION.md](../../../ucie-model/MODELING_AND_VERIFICATION.md) | documentation / 1261 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/Makefile](../../../ucie-model/Makefile) | build / 47 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/README.md](../../../ucie-model/README.md) | documentation / 202 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/TEST_PLAN.md](../../../ucie-model/TEST_PLAN.md) | documentation / 59 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/results/.gitignore](../../../ucie-model/results/.gitignore) | config / 4 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/results/LINK_VALIDATION_REPORT.md](../../../ucie-model/results/LINK_VALIDATION_REPORT.md) | documentation / 27 | 双向UCIe路径、训练状态与observer连接 |  |  |
| [ucie-model/scripts/run_sweep.sh](../../../ucie-model/scripts/run_sweep.sh) | source / 61 | UCIe行为链路接口、编码或原生测试 | metric@11 (shell function)；row@16 (shell function) |  |
| [ucie-model/scripts/run_tests.sh](../../../ucie-model/scripts/run_tests.sh) | source / 199 | UCIe行为链路接口、编码或原生测试 | metric@14 (shell function)；check@16 (shell function) |  |
| [ucie-model/scripts/run_validation.sh](../../../ucie-model/scripts/run_validation.sh) | source / 53 | UCIe行为链路接口、编码或原生测试 | metric@11 (shell function) |  |
| [ucie-model/src/README.md](../../../ucie-model/src/README.md) | documentation / 176 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/src/ucie_common.h](../../../ucie-model/src/ucie_common.h) | source / 395 | UCIe行为链路接口、编码或原生测试 | Modulation@16 (class/type)；FlitFormat@17 (class/type)；Config@22 (class/type)；bits_per_ui@76 (C/C++ function candidate)；flit_bytes@79 (C/C++ function candidate)；payload_bytes@82 (C/C++ function candidate)；flit_bits@88 (C/C++ function candidate)；serialize_ui@89 (C/C++ function candidate)；ui_fs@93 (C/C++ function candidate)；flit_efficiency@94 (C/C++ function candidate)；require_valid_config@98 (C/C++ function candidate)；print_help@115 (C/C++ function candidate) … | algorithm；cstdint；cstdlib；iostream；stdexcept；string；vector；aou_format6.h … |
| [ucie-model/src/ucie_fdi.h](../../../ucie-model/src/ucie_fdi.h) | source / 55 | UCIe行为链路接口、编码或原生测试 | BusinessKind@10 (class/type)；LinkState@16 (class/type)；to_string@17 (C/C++ function candidate)；to_string@21 (C/C++ function candidate)；FdiFlit@41 (class/type) | systemc.h；cstddef；cstdint；ostream；vector |
| [ucie-model/src/ucie_link.h](../../../ucie-model/src/ucie_link.h) | source / 498 | 双向UCIe路径、训练状态与observer连接 | require_valid_fdi@21 (C/C++ function candidate)；Frame@31 (class/type)；FbMsg@46 (class/type)；unpack_fdi@55 (C/C++ function candidate)；TxState@85 (class/type)；sc_module@91 (C/C++ function candidate)；sender@97 (C/C++ function candidate)；feedback@153 (C/C++ function candidate)；Entry@185 (class/type)；send_one@186 (C/C++ function candidate)；sc_module@230 (C/C++ function candidate)；ingress@234 (C/C++ function candidate) … | systemc.h；algorithm；cstdint；deque；map；string；utility；vector … |
| [ucie-model/src/ucie_phy.h](../../../ucie-model/src/ucie_phy.h) | source / 210 | 行为PHY串行化、调制、噪声、lane与CDR | PhyResult@12 (class/type)；BehavioralPhy@23 (class/type)；BehavioralPhy@27 (C/C++ function candidate)；transmit@37 (C/C++ function candidate)；observe@97 (C/C++ function candidate)；is_cdr_locked@113 (C/C++ function candidate)；lock_loss_count@115 (C/C++ function candidate)；stripe_bytes@116 (C/C++ function candidate)；destripe_bytes@138 (C/C++ function candidate)；pam4_encode@171 (C/C++ function candidate)；pam4_decide@179 (C/C++ function candidate)；nrz_decide@191 (C/C++ function candidate) … | algorithm；array；random；vector；ucie_common.h |
| [ucie-model/src/ucie_systemc_main.cpp](../../../ucie-model/src/ucie_systemc_main.cpp) | source / 677 | UCIe行为链路接口、编码或原生测试 | WorkloadItem@37 (class/type)；trim@54 (C/C++ function candidate)；split_csv_line@60 (C/C++ function candidate)；parse_uint@68 (C/C++ function candidate)；make_workload@120 (C/C++ function candidate)；payload_to_hex@185 (C/C++ function candidate)；sc_module@207 (C/C++ function candidate)；run@210 (C/C++ function candidate)；sc_module@252 (C/C++ function candidate)；ingress@256 (C/C++ function candidate)；egress@291 (C/C++ function candidate)；sc_module@328 (C/C++ function candidate) … | systemc.h；algorithm；cctype；cmath；deque；fstream；iomanip；numeric … |
| [ucie-model/src/ucie_unit_tests.cpp](../../../ucie-model/src/ucie_unit_tests.cpp) | source / 185 | UCIe行为链路接口、编码或原生测试 | check@19 (C/C++ function candidate)；check_throws@29 (C/C++ function candidate)；make_phy_result@39 (C/C++ function candidate)；sc_main@48 (C/C++ function candidate) | systemc.h；cmath；cstdint；iostream；stdexcept；string；vector；ucie_common.h … |
| [ucie-model/tests/external_payloads.expected](../../../ucie-model/tests/external_payloads.expected) | text/data / 3 | UCIe行为链路接口、编码或原生测试 |  |  |
| [ucie-model/tests/external_payloads.hex](../../../ucie-model/tests/external_payloads.hex) | text/data / 4 | UCIe行为链路接口、编码或原生测试 |  |  |
