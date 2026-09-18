# 开发与历史追溯

内部模块以及gem5、CoralNPU、ramulator2作为同一系统维护，直接在主仓库创建功能分支，允许一个提交同时修改
处理器适配、AXI、UCIe和内存接口。只有Vortex及其递归依赖保留子模块。

```bash
git switch -c feature/功能名称
# 修改对应目录，运行相关验证
git add <实际修改的源码路径>
git commit -m "说明本次行为变化的中文提交信息"
# 验证后在main合并；涉及完整功能的分支可以使用--no-ff保留合并记录
```

不要对普通源码目录执行git pull；它们没有独立仓库。在根目录同步并合并主仓库分支，
主仓库地址为https://github.com/jiahuiwu121-sys/full_link_simulation_system.git（HTTPS地址见README）。
更新主仓库后运行git submodule update --init --recursive，使外部依赖匹配主仓库记录。
若子模块有自己的源码修改，先保存和核对这些修改，不要用reset清除本地适配。

gem5、CoralNPU 的本地快照已展开为主仓库源码，导入来源与版本核实边界见
[内置源码说明](source-layout.md)及env/vendored_sources.json。必要基础适配直接维护源码，
构建不重复打补丁。mem_sim已由此前提交移除，历史内存导入记录继续保留供追溯。当前默认在线后端为 Ramulator2，接入契约见[在线后端说明](ramulator-integration.md)。

## 迁移历史

本轮先为已有本地改动建立中文提交，再对有远端的四个内部仓库执行
`git pull --no-rebase --no-commit origin main`，产生的合并使用中文提交。
gem5_axi原来没有远端和首次提交，因此单独建立源码基线。

随后通过不带--squash的git subtree add导入各目录，保留原提交对象与父链。
此操作仅用于一次性历史导入，日常不再按subtree同步多个仓库。
来源URL、拉取到的远端版本、包含本地改动的版本、各导入提交见env/internal_imports.json。

```bash
git log --graph --oneline --all
git log --oneline -- mem_sim
git show <旧提交号>
```

原历史的文件路径仍是各库导入前的相对路径；未重写旧提交哈希。
archive/*分支是原维护机器上的辅助历史入口，不要求新克隆中存在，也不用于继续独立开发。
新克隆可用env/internal_imports.json中的提交号配合git log/git show追溯。
原内部Git元数据已归档至本地integrate_doc/handoff_20260911/retired_git_metadata，
活动登记和.git/modules中只保留三个外部库及其递归依赖。
这些历史分支的提交也通过导入合并
成为主仓库的祖先，即使克隆时不额外获取这些分支，主分支历史仍包含原提交。

## 源码归属

- UCIe的AoU格式支持和观察接口直接在ucie-model源码中维护；不再由axi2flit/gem5_axi打补丁。
- AoU公共帧映射在protocol/include，UCIe与AXI2Flit共同引用。
- gem5设备封装在gem5_new/gem5int/src/dev；每次env/build.sh自动刷新gem5中的构建副本。
- Vortex SimX/ABI的上游差异归并为gem5_new/vortexint/patches/simx_online.patch。
- gem5/CoralNPU基础适配已纳入主仓库源码；安装入口只刷新设备和库构建副本，不重复打补丁。
- Ramulator2在线C ABI在ramulator2/integration；桥接和唯一backing在gem5_axi。原生库仅导出ssr_*，避免与Vortex内部Ramulator冲突。
- env/record.py输出的*.patch是运行时差异快照，不是构建时对内部目录应用的补丁。
- 指标收集/统计契约在gem5_axi/scripts/collect_metrics.py、check_metrics.py；原生采样在ramulator2/integration。
  每个模块独立输出及整体汇总、功耗窗口口径见[实验指标说明](experiment-metrics.md)。修改统计也要验证不改变命令序列与原有总值。

迁移备份在本地integrate_doc/repository_migration_20260911，包括原Git bundle、
工作区压缩包和每次pull日志。integrate_doc暂不进入主仓库；核心维护说明以本文件为准。
