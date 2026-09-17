# env 文件索引

共 30 条；源码 21 条、1,374 行。符号展示最多 12 个，依赖展示最多 8 个；HTML/CSV 保留更多提取项。

[索引说明与模块统计](README.md) · [系统集成语义解读](../03-integration-code.md) · [上游子系统解读](../04-upstream-code.md)

| 文件 | 类型 / 行数 | 职责提示（自动归类） | 候选符号及行号 | 静态依赖提示 |
|---|---|---|---|---|
| [env/README.md](../../../env/README.md) | documentation / 204 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/activate.sh](../../../env/activate.sh) | source / 36 | 当前 shell 的统一环境变量 |  |  |
| [env/bootstrap.sh](../../../env/bootstrap.sh) | source / 32 | 锁定工具链、依赖下载或缓存准备 |  |  |
| [env/bootstrap_xpu.sh](../../../env/bootstrap_xpu.sh) | source / 40 | 锁定工具链、依赖下载或缓存准备 |  | hashlib,json,os,subprocess；pathlib；json,os；"$(dirname -- "${BASH_SOURCE[0]}")/activate.sh" |
| [env/build.sh](../../../env/build.sh) | source / 16 | 统一构建入口及构建参数 |  | "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh" |
| [env/build_xpu.sh](../../../env/build_xpu.sh) | source / 66 | 统一构建入口及构建参数 |  | os,shutil,subprocess；pathlib；"$(dirname -- "${BASH_SOURCE[0]}")/activate.sh" |
| [env/check_sources.py](../../../env/check_sources.py) | source / 84 | 普通源码与外部子模块来源检查 | git@20 (def)；check_local@27 (def)；check_external@46 (def)；main@62 (def) | argparse；json；pathlib；subprocess |
| [env/compare_axi_width.py](../../../env/compare_axi_width.py) | source / 131 | 统一环境配置、版本锁定或来源记录 | read@16 (def)；first_write@20 (def)；link@87 (def)；table@93 (def) | argparse；csv；html；json；os；pathlib |
| [env/conda-linux-64.lock](../../../env/conda-linux-64.lock) | config / 136 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/dependency_bundle.py](../../../env/dependency_bundle.py) | source / 230 | 依赖包打包、校验与恢复 | run@17 (def)；digest@21 (def)；copy_file@29 (def)；submodules@34 (def)；write_manifest@56 (def)；pack@68 (def)；verify@148 (def)；install@179 (def)；main@209 (def) | argparse；hashlib；json；os；pathlib；shutil；subprocess；urllib.parse … |
| [env/environment.yml](../../../env/environment.yml) | config / 19 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/fetch_vortex_tools.py](../../../env/fetch_vortex_tools.py) | source / 40 | 锁定工具链、依赖下载或缓存准备 | fetch@18 (def) | concurrent.futures；hashlib,json,os；pathlib；subprocess,tarfile |
| [env/internal_imports.json](../../../env/internal_imports.json) | config / 37 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/native_tests.py](../../../env/native_tests.py) | source / 13 | 统一环境配置、版本锁定或来源记录 | passed_count@3 (def) | json |
| [env/prepare_cmake_sources.py](../../../env/prepare_cmake_sources.py) | source / 39 | 锁定工具链、依赖下载或缓存准备 |  | hashlib；json；os；pathlib；subprocess；tarfile；tempfile |
| [env/prepare_vortex_llvm.py](../../../env/prepare_vortex_llvm.py) | source / 22 | 锁定工具链、依赖下载或缓存准备 |  | os；pathlib；subprocess |
| [env/record.py](../../../env/record.py) | source / 69 | 运行环境、来源和产物记录 | command@15 (def)；sha@19 (def) | hashlib；json；os；pathlib；platform；subprocess；sys |
| [env/record_xpu.py](../../../env/record_xpu.py) | source / 63 | 运行环境、来源和产物记录 |  | hashlib；json；os；pathlib；subprocess；sys |
| [env/run.sh](../../../env/run.sh) | source / 35 | 统一用例运行与验证调度 |  | "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh" |
| [env/run_memsim.sh](../../../env/run_memsim.sh) | source / 49 | 统一用例运行与验证调度 | run_case@16 (shell function) | "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh" |
| [env/run_xpu.sh](../../../env/run_xpu.sh) | source / 38 | 统一用例运行与验证调度 | run_case@17 (shell function) | "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh" |
| [env/sources.lock.json](../../../env/sources.lock.json) | config / 3 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/tests/test_source_layout.py](../../../env/tests/test_source_layout.py) | source / 126 | 统一验收、结果对照或源码布局检查 | module@14 (def)；SourceLayoutTests@21 (class/type)；setUp@24 (def)；test_ordinary_sources_are_accepted_without_upstream_git@36 (def)；test_leftover_gitlink_is_rejected@40 (def)；test_inner_git_pointer_is_rejected@47 (def)；test_double_nested_source_is_rejected@52 (def)；LegacyBundleTests@60 (class/type)；setUp@63 (def)；write_manifest@88 (def)；test_old_cache_restore_preserves_project_sources@100 (def)；test_changed_external_revision_is_rejected@111 (def) … | contextlib；hashlib；importlib.util；io；json；pathlib；subprocess；tempfile … |
| [env/upload_sources.json](../../../env/upload_sources.json) | config / 12 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/vendored_sources.json](../../../env/vendored_sources.json) | config / 22 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/verify_memsim.py](../../../env/verify_memsim.py) | source / 61 | 统一验收、结果对照或源码布局检查 | read@13 (def)；rows@14 (def)；finish@16 (def)；insts@17 (def) | csv；json；pathlib；re；sys；native_tests；hettrace.reader；hettrace.validate |
| [env/verify_run.py](../../../env/verify_run.py) | source / 96 | 统一验收、结果对照或源码布局检查 | rows@13 (def)；finish@18 (def)；instructions@74 (def) | csv；json；pathlib；re；sys；hettrace.reader；hettrace.validate |
| [env/verify_xpu.py](../../../env/verify_xpu.py) | source / 88 | 统一验收、结果对照或源码布局检查 | read@13 (def)；rows@14 (def)；finish@16 (def) | csv；json；pathlib；re；sys；native_tests；hettrace.reader；hettrace.validate |
| [env/xpu-artifacts.lock.json](../../../env/xpu-artifacts.lock.json) | config / 118 | 统一环境配置、版本锁定或来源记录 |  |  |
| [env/xpu-runtime-linux-64.lock](../../../env/xpu-runtime-linux-64.lock) | config / 10 | 统一用例运行与验证调度 |  |  |
