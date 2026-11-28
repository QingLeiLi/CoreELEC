# E900 hwdb预生成

2026-11-28。用户同意将[引导链研究](BOOT-CHAIN-20261128.md)中实测3.150385s的运行时hwdb编译移到镜像打包阶段。此项与早期OSD等待候选分开实现，不改OSD/RDMA、内核配置或用户屏保。

## 实现

`install-patches.py`仅为decoder配置在固定CE `scripts/image`中插入单次调用，位置在所有包、项目/板型filesystem overlay均安装完成之后、SquashFS压缩之前。被审计原脚本SHA256为`2bbd3ecc28388562360b20eaa86527a91f601eb731d1de59689c688b179d22ee`；本地改动或未知上游脚本拒绝覆盖，禁用decoder时可恢复原脚本。

调用构建目录中的`scripts/e900-prebuild-hwdb.py`（来自port的`prebuild-hwdb.py`），而不是执行ARM二进制。Linux构建主机systemd-hwdb使用镜像最终的`/usr/lib/udev/hwdb.d/*.hwdb`，在独立临时根中生成数据库。临时根只复制镜像vendor规则，不跟随目标`/etc`指向STORAGE的链接、不读取主机规则。临时根`lib -> usr/lib`同时兼容Ubuntu Jammy的/lib/udev与CE的/usr/lib/udev工具路径；拒绝未知vendor链接。

输出：

- SYSTEM内`/usr/lib/udev/hwdb.bin`，只读0444。
- `/usr/lib/e900-boot/hwdb-build.json`，记录生成工具版本、规则文件hash及数据库hash，便于追溯。

每次重打包重新根据最终规则生成，不复用旧库；开始前删除旧输出，生成失败则中止打包。支持审查过的systemd249～255生成器，核对LE header、文件长度、节点布局和工具版本。Ubuntu22构建器与Docker补装systemd/udev，不改变原编译器依赖脚本/兼容键；镜像hook和helper变更只更新构建状态，不清内核、无线模块或工具链。

格式依据：[systemd255 hwdb结构](https://github.com/systemd/systemd/blob/v255/src/libsystemd/sd-hwdb/hwdb-internal.h)、[读取和旧布局兼容](https://github.com/systemd/systemd/blob/v255/src/libsystemd/sd-hwdb/sd-hwdb.c)、[249生成工具接口](https://github.com/systemd/systemd/blob/v249/src/hwdb/hwdb.c)。这是版本与格式审查依据，不代替下一次真实Ubuntu249→ARM255镜像验收。

## 用户规则和回退

不mask、不删CE的`systemd-hwdb-update.service`。上游已移除只读/etc的ConditionNeedsUpdate。因默认用户目录带README，新增drop-in清除ConditionDirectoryNotEmpty，改为ConditionPathExistsGlob匹配`/etc/udev/hwdb.d/*.hwdb`；保留缺少/usr/lib/udev/hwdb.bin、存在/run/hwdb.bin两个OR条件。README不能当作用户规则，否则预生成后仍会重建。正常无用户覆盖时可直接读取预生成库；用户在`/storage/.config/hwdb.d`放规则后仍按原机制重建到/run，读取顺序优先于/usr库。当前boot内新增规则仍按原流程手工update/retrigger或下次启动生效，不新增动态监控承诺。

库丢失时仍重建。格式或规则问题若在打包时发现直接失败，不产出被当成可用的新镜像。实机失败回退上一套已知正常内核/SYSTEM/DTB，不写eMMC。

## 已执行和待验

- 主机检查覆盖实际固定CE脚本hook顺序、幂等/撤回、本地修改保护、失败清旧输出、隔离规则、/lib与/usr/lib兼容，以及错误数据库头拒绝。
- 43项既有主机检查通过（VDIN fixture补入scripts/image后重测通过）；新增第44项在Mac执行上述保护检查，真实Linux生成/查询/条件项明确标记待验，CI必须执行而非跳过。
- 使用盒子原生systemd255在独立/tmp临时根实测：2个测试规则生成381字节合法库，真实libsystemd按路径打开并读到ID_E900_TEST=vendor和后文件覆盖ID_E900_ORDER=late；systemd-analyze实际条件判断无用户规则跳过、有用户规则触发重建；随后针对README细化条件另验无库/仅README/有实际规则。[条件实测原始记录](evidence/boot-chain-20261128/hwdb-condition-target.txt)。所有临时目录自动清理，没有覆盖系统库、启动service、切画面或重启。
- 新增Linux CI测试执行实际注入的hook，再由本机libsystemd查询输出并核对优先级；Ubuntu249生成器路径/格式、真实镜像规则及ARM目标最终读取仍需本次新代码的云构建和部署验收。
- 系统实际能减少多少上电时间尚未测量。3.15秒是旧库编译任务耗时，受并行依赖影响，不能等同最终菜单提前3.15秒。

下一次构建选择decoder + image。正在运行的旧任务不会自动包含新提交；无需为此取消已运行任务。新镜像验收先检查库/manifest、服务跳过原因、输入设备功能，再比较同条件的critical-chain与可见菜单时间。
