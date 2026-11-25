# PPS/HDR 实际准备表记录器（0035）

## 要回答的问题

Build290已确认Canvas有彩条、关闭/恢复后下游采样未恢复。0031记录业务决策，0033只记录HDR调用参数，均不能证明具体提交了哪些字。0035因此在rdma_config复制reg_buf到实际rdma_table_addr之后、正常触发器编程之前，记录选中寄存器的完整表项序列；在管理器看到IRQ且尚未调用下一批回调之前记录完成事件。

**这不是黑屏修复。尚需ARM构建和实机采集。**

## 覆盖与限制

- 默认关闭，仅GXLX2；固定4096条、128KiB内存，满后冻结并标记overflow。无新增MMIO、无逐项printk、不改变表项/合并/触发器配置。开启后增加内存复制和锁开销，实机应保留关闭记录器的对照，避免把观察时序变化误判成修复。
- 只记录现有正常触发提交（trigger 1..0x100）的软件表副本。0036进一步加入legacy VD1 MIF窗口1a50..1a6f、GEN3 1aa7及路由1a06/1a07的软件表项；legacy VPP完整地址窗口1d00..1dff（包括PPS系数/相位/尺寸、混合、VADJ和矩阵），HDR2 3800..38ff，OSD矩阵3d60..3d6f。这些是**观察地址筛选**，并不证明GXLX2具有所有同名硬件；不会为采集去读取这些地址。
- 同地址连续系数不会去重。保留原表索引，所选表项可能不连续；未选中地址不导出。
- 准备表不等于硬件执行。IRQ只有软件pending批次关联，没有硬件逐表cookie；延迟IRQ/重提仍需结合已有进度和像素证据解释，不能逐字保证落地。
- stop/clear/自动模式/调试直写/溢出回退会取消已有pending关联；重提前一批标记为被替换，不冒充完成。自动启动和直接写路径的完整写值未覆盖，基础实验保持rdma.enable=1,0。OSD自有提交机制及其他寄存器不在完整覆盖承诺内。
- 对选中软件准备表可以精确逐项比较，对完整硬件写入历史不能作此承诺。

## 设备用法

工具随新构建debug-tools导出，不自动开启，不触发播放或输出切换。

```sh
python3 /storage/debug-tools/e900-submit-trace.py start
# 返回generation=N；在受控阶段播放或执行既有global_output边界工具。
python3 /storage/debug-tools/e900-submit-trace.py stop --generation N --out /storage/first-submit.json
# 重新start并单独记录关闭/恢复阶段，保留该次generation。
python3 /storage/debug-tools/e900-submit-trace.py stop --generation M --out /storage/restore-submit.json
python3 /storage/debug-tools/e900-submit-trace.py compare /storage/first-submit.json /storage/restore-submit.json
```

先采首播配置窗口，再在同次播放中另采关闭/恢复窗口；不要把很长稳态播放填满缓冲。当前盒子工具目录实际为/storage/e900-build290/debug-tools；0035内核尚未部署，现有290内核不支持此记录器。

`stop`核对generation后冻结；`dump --out FILE`只导出已冻结的数据。导出逐页验证前后状态、索引、代次、列数和记录顺序；兼容sysfs追加空行。溢出记录保留用于检查，但比较工具拒绝将其视作完整证据，空记录同样拒绝比较。compare保留重复写入，忽略时间戳及批次号，对比选中表项的地址/值序列；源场景和动态相位不同也会造成合法差异。

## 字段与事件

每行：index generation stamp batch handle kind reg value item。前两列十进制，其余十六进制；stamp是内核jiffies，需结合同次启动的时钟，不直接当秒。

kind0=正常触发表准备，value是trigger，item是完整表项数量；kind1=表项，reg/value为地址与实际完整写值，item为原表索引；kind2=IRQ观测，value为已有RDMA_STATUS读取值；kind3=取消关联，value原因：0空表或停止，1clear，2auto模式，3debug模式，4溢出直写回退，5被新提交替换。

sysfs在rdma_mgr模块下：gxlx2_submit_scan（1新建/0冻结）、gxlx2_submit_page、gxlx2_submit_data。均root权限，data只读且运行中拒绝读取，防止把活动缓冲当稳定证据。标准e900-debug快照会保存状态；arm不自动开启此大表记录器。

## 验证

主机执行实际上游及修改后的rdma_config，比较6种CPU、7种触发方式、记录关闭/开启时的原有MMIO调用与返回值；验证重复系数、IRQ及clear/重提关联、容量、代次、冻结读出与最大行长度。Python采集器验证坏页、丢行、重复、越界、导出期间代次变化、溢出拒绝和顺序比较。主机结果不替代ARM编译与硬件实验。
