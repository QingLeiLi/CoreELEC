# GXLX2早期OSD RDMA恢复

2026-11-28，用户要求“先修osd”。基准为已验收build294启动补偿；相关证据在[原始OSD依赖分析](OSD-STARTUP-RDMA-20261128.md)及[引导时间线](BOOT-CHAIN-20261128.md)。新增Linux0048源码修正，已通过主机检查，ARM构建、真实并发及画面尚待验收。没有操作盒子、重启或改用户正在运行的构建。

## 修复范围

0006仍在late_initcall_sync发布GXLX2 codec寄存器总线，避免重新引入早期硬件访问导致的启动失败。OSD私有表START/END仍走原生访问器，保留既有分配/准备路径。0048仅记录OSD自己的早期start意图，在总线就绪后调用原有`rdma_config(handle, VSYNC|AUTO)`，恢复此前丢失的触发/方向/增量字段。不是缓存并重放任意寄存器写，不重跑probe，不改RDMA CTRL、共享reset、DMA地址、表内容或等待超时。

仅当GXLX2且`CONFIG_AMLOGIC_MEDIA_RDMA`启用时走新路径，其余CPU及关闭开关时仍用原来的start/stop调用。首次初始化取得OSD通道之后订阅已有codec ready notifier，优先级-10排在video默认0之后：正常自动初始化时先执行固定video完成回调，再处理OSD；诊断wait1仍可能让video回调保留等待，不能将优先级解释成无条件video初始化完成。

## 状态与生命周期

- 总线不可用时，start在OSD私有rdma_lock下记录pending，不再把必然丢失的RMW当成已配置。
- 发布总线与start边界交错时，notifier也取得同一锁；回调不会越过尚未记录完的请求。若总线已就绪，start直接走原API，无须等待另一通知。
- 回调只接受init成功、rdma_enable有效、没有释放且存在pending。只接受本板审计的RDMA-v1通道3，DMA地址来自当前驱动分配，要求START一致、END字节范围在一页内且按8字节对齐。允许原生准备空表的END=START-1。
- 已有正确CH3字段时零写跳过。否则通过manager API恢复，只改变它管理的CH3字段；读回字段验证并记录结果，不把配置成功当作有效新鲜像素。
- stop在同一锁下取消pending并清通道，避免late callback重新启动已停通道。
- release先标记releasing并取消pending，放锁后注销blocking notifier，待回调退出再释放DMA与通道。不能持有OSD锁等待notifier注销。
- 重复通知不会重放同一请求；订阅失败告警并保留原启动补偿兜底，没有自动重试/持续写寄存器。

锁顺序沿用既有osd_rdma_reset_and_flush → osd_reset_rdma_func → rdma_config的OSD私有锁→manager锁。manager ISR调用OSD完成回调时不持有manager锁。本轮未改变此顺序，主机锁模型只能验证显式路径，不能替代实际IRQ并发验收。

## 诊断与开关

内核日志：

- `e900-osd-rearm: defer handle=3`：早期请求等待总线，没有配置成功的含义。
- `e900-osd-rearm: replay status=2 ... auto=...->... irq=...`：原API返回成功且CH3字段读回正确，IRQ可能尚未来得及增长。
- `reject`、订阅失败或负status：记录具体阻止条件，不能写成修复通过。
- `e900-osd-wait: timeout task=... elapsed_ms=...`：原等待确实到期，记录实际耗时，限速输出；保留等待条件与1000ms上限，不靠缩短timeout伪造提速。健康等待路径无CPU ID查询/日志，仅增加计时读取。

`/sys/module/fb/parameters/gxlx2_osd_rearm_status`只读：0=无延期记录、1=pending、2=配置重放并读回成功、3=字段已就绪零写、负值=拒绝/失败。status2/3都不能替代完成计数和用户画面。

默认开启。诊断启动可加`fb.gxlx2_osd_boot_rearm=0`，只禁本次内核重放，回到原start/stop；保留正常wait0时，已有SYSTEM开机补偿仍能在Kodi前修复。该开关只读，不能在释放过程临时切换。`amvideo.gxlx2_hw_init_wait`仍是原video初始化开关，与OSD开关分别记录。

## 主机验证

新增`check-osd-bus-rearm.py`应用所有补丁，抽取真实start/stop/notifier/cancel函数，以gnu89/gnu99、Wall/Wextra/Werror编译执行。覆盖：其它CPU/关闭开关原调用保持、总线发布前后两种顺序、重复通知、停止/释放取消、活跃状态保护、32位DMA截断/错误地址/范围/对齐拒绝、空表、字段已就绪跳过、其它通道字段保持、manager失败和读回失败。真实内核锁/IRQ、ARM链接和像素不在该模型内。

45项workflow主机检查通过。最后显式补入jiffies/ratelimit头文件后，重测新增C检查通过；未因重复无变化而重跑整套。没有本轮ARM产物，现机仍运行旧build294。

## 下一次实机验收

1. 构建decoder + image（不是单独linux），将内核/SYSTEM/DTB配套部署；现有OSD启动服务保留。
2. 用户确认可观察后，以同样显示器/USB盘软重启，不自动播放、不先按遥控器。保存同boot日志、独立OSD完成计数、status和critical-chain。
3. 正常预期：总线发布约1.3s附近出现replay，早于platform_init framebuffer操作；计数持续增长；SYSTEM补偿记录already-completing并零写；用户菜单自行正常出现。若初始化已晚于总线，status0也可能正常，需按日志判断是否原本无需延期。
4. 对比platform_init原先2.4/3.4/4.46/5.48秒的操作间隔和6.52秒模块加载起点，结合timeout日志判断实际减少了哪些等待。hwdb提速单独按service的skip理由与时长核算，不合并归因。
5. 若回调拒绝、OSD不完成或黑屏，先保留日志；不叠加改CTRL/分辨率。需要重启回退时先等用户确认，使用保留的build294或禁用OSD重放开关。
6. 菜单通过后再验证正常首播、Stop/replay及菜单返回；后续再做断电启动。HDR/HLG偏灰仍是独立未解决问题。
