# gem5 与 CoralNPU 内置源码

gem5、CoralNPU 已从外部 Git 子模块转为主仓库普通源码目录。现在直接在以下位置阅读和修改：

```text
gem5/SConstruct
gem5/src/
coralnpu/MODULE.bazel
coralnpu/hdl/
coralnpu/hw_sim/
```

不再有重复的 gem5/gem5、coralnpu/coralnpu 目录，也不需要进入上游独立仓库。普通 Git 克隆会包含两者源码；只有 Vortex 及其递归依赖仍需要 submodule update。

## 来源与维护

这次导入保留当前本地快照的全部源码、许可证、测试输入、文件执行属性和符号链接。上游来源与原声明的版本记录在 [env/vendored_sources.json](../env/vendored_sources.json)。原快照的 .git 文件指向缺失的 Git 元数据，无法核实其确切上游提交，所以记录 revision_verified=false，不将声明版本当成已经验证的版本。

两者此后的源码版本由主仓库提交标识。不要在目录里建立内部 .git，也不要对子目录执行 git pull。需要升级时，在主仓库分支上审阅上游差异，再完成构建和回归。

## 已纳入的适配

- gem5：DMA byte-enable、TLM masked-write、原生 VCD integral trace 修复。
- CoralNPU：异步 AXI issue/completion、非阻塞启动/状态、native C++ 构建适配。

统一构建不再给这两个内部源码目录应用基础补丁。gem5_new/gem5int/src/dev 仍是设备适配源码真值，coralnpuint 仍是设备库源码真值；安装脚本只刷新对应构建副本。现存补丁文件保留为外部独立源码的兼容参考，不驱动本项目内置源码构建。

对内置源码，旧安装脚本的 --revert 被拒绝，避免删除主仓库代码；恢复修改应使用主仓库审阅流程。

## 检查

```bash
python3 env/check_sources.py --only gem5 coralnpu
python3 -m unittest discover -s env/tests -v
```

检查源码属于主仓库、索引没有 gitlink、目录没有内部 .git，并核对关键入口文件。默认不带 --only 会检查完整链路所需模块。

迁移验证已确认全部 12,010 个原始文件与链接保留，执行权限和链接目标一致，仅 8 个原始文件纳入必要适配。安装脚本重复执行两次未改变源码内容；7 项布局和旧依赖包回归检查通过。通过导出索引到临时仓库并普通克隆，确认源码、链接与执行权限可完整交付；没有在当前主仓库创建提交。

mem_sim 已在此前提交 b5f35ab 移除，Vortex 在本次迁移前也未初始化，因此当前副本仍不能执行完整在线构建。这次目录与 Git 归属迁移不代表整机运行验收，也不会自动把独立 ramulator2 接到在线链路。

## 依赖包

新依赖包通过 system.bundle 包含 gem5/CoralNPU 源码，不再为两者创建单独 bare Git 仓库。新包增加 vendored_sources.json 来源记录。

旧包若只有 gem5/CoralNPU 从 source lock 移除这一项布局差异，且原声明版本和其他工具锁匹配，仍可恢复工具缓存；install 跳过两者旧子模块，不覆盖当前主仓库源码。Vortex 仍按固定版本恢复。

本次迁移原文件与索引备份放在本机 integrate_doc/vendor-migration-*，不提交。源码纳入后，仓库体积和初次克隆量会增加；日常修改、提交与评审都在主仓库完成。
