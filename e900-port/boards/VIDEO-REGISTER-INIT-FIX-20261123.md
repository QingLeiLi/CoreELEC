# GXLX2 视频寄存器初始化拆分（2026-11-23）

状态：源码候选已完成，宿主检查通过；未完成此次修改的ARM构建、启动及物理显示验收。本次没有操作设备。

补充：[网络日志诊断流程](NETCONSOLE-INIT-DIAGNOSTICS.md)。USB-TEST启动脚本现默认`gxlx2_hw_init_wait=1`，先等待SSH/网络日志，再显式释放固定配置；不是启动时立即执行本修复。内核自动模式仍保留。

## 问题与范围

build278的同构建对照确认：延后整个`video_init()`无法上线，关闭该选项后能启动。关闭路径还记录`video_hw_init()`前后VCBUS丢写7→16，说明该函数有9次配置未落地。不能据此断言这些丢写是硬解黑屏的唯一原因。

这次只修复**已明确的video_hw_init寄存器配置时序**；不把任意早期总线调用缓存后重放，也不声称其他调用者的早期丢写已全部消除。原先进入该函数前已有的7次累计丢写仍需按调用者审计。

## 修改

* [0010](../patches/linux/0010-gxlx2-late-video-init-probe.patch)保留软件总线就绪查询，移除整个video_init延后路径。原`amvideo.gxlx2_late_video_init`选项不再提供；新功能使用独立选项，旧启动脚本中的`=0`不会禁用本次修复。
* 新增[0019](../patches/linux/0019-gxlx2-deferred-video-register-init.patch)，并加入decoder profile。它与先前删除的0019 FIFO/hold_line猜测补丁无关。
* 保留原来的`module_init(video_init)`。probe、IRQ、sysfs、VFM接收器、DI软件状态、VPU_ARB供电及security回调仍走早期路径，不重复注册。
* GXLX2的`video_hw_init()`只准备软件状态并排队；成功probe及完整video_init结束后，订阅总线就绪通知。注册整张总线表后通知；若总线早已发布，订阅时立即检查。无需依赖两个late_initcall在链接中的相对顺序。
* VC/HHI/DMC三个回调均就绪后，只执行原GXLX2分支中的固定寄存器操作。保留既有BSP数值，不顺带修改主线显示策略。
* 非GXLX2及显式关闭本功能时，原video_hw_init函数体保留。卸载/移除时注销通知，避免残留回调；失败probe不会提交配置。

## 固定配置和软件状态

| 项目 | 操作 |
|---|---|
| VPP_OFIFO_SIZE | 按原字段宽度设置0xfff |
| VPP_PREBLEND_VD1_H_START_END / VPP_BLEND_VD2_H_START_END | 各4096 |
| VPP_DUMMY_DATA | 原分支值0x4080200 |
| VPP_SRSHARP0_CTRL / VPP_SRSHARP1_CTRL | 各0 |
| sr_info.sr0_sharp_sync_ctrl | 按原分支分别置bit0、bit8 |
| DOLBY_PATH_CTRL | 仅dv_support关闭时设置原低6位值0xf |
| VPP_HOLD_LINES | 总线就绪后真实读取低字节，按原规则限制到0x1f再赋给vpp_hold_line；不写入该寄存器 |

默认板级配置为9次写入；若dv_support开启则少一次。只支持当前legacy VPP、无film-grain的GXLX2板级配置；出现不符配置时报告错误，避免静默遗漏另一条初始化路径。

`VPP_HOLD_LINES`不是这9次写入之一。这次避免了总线未就绪时的伪零覆盖软件默认值，但如果真实硬件值就是0，仍按原规则采用0；没有未经验证地强制写成主线的0x404或VD1的9。

## 执行、失败及读回

执行过程固定输出`e900-hw-init:`日志：queued → begin → fifo/windows/dummy → sharp/bypass → complete。读取OFIFO和两个窗口配置核对关键写入，失败则保留错误状态，不宣布完成；其他写入仍需实机核对，不能把有限读回当成整条视频链路验收。

使用互斥锁及尝试/完成标志防止重复通知重放。缺总线时等待后续发布；一旦开始硬件配置，出现错误也不会自动反复尝试。没有提供用户寄存器地址接口。

### 启动问题的日志粒度与保留边界

新增probe完成、订阅前后、通知进入/获得锁/退出及总线软件就绪状态日志。固定硬件配置分13个步骤；每一次实际读写都有`read.begin/read.end`或`write.begin/write.end`，读改写的读和写分别记录。读返回后记录值，写之前记录目标值。

| step | 配置/读回 |
|---|---|
| 1 | OFIFO字段读改写 |
| 2 / 3 | VD1 / VD2窗口写入 |
| 4 | dummy data写入 |
| 5 / 6 | SR0 / SR1控制写入 |
| 7 / 8 | SR0同步位0 / 位8读改写 |
| 9 | 可选Dolby旁路读改写 |
| 10 | 读取真实VPP保持行数 |
| 11 / 12 / 13 | OFIFO / VD1窗口 / VD2窗口读回 |

例如最后只有`step=7 read.begin`而没有`read.end`，在记录完整的前提下，可把停滞范围缩到该次访问；若停在`notify.enter`，则应查锁及调度，不直接归因于MMIO。日志缺失或丢失时不能这样推断。

准备USB镜像使用的`boards/e900-usb-image.src`已从`loglevel=4`改为7，使INFO级标记能进入控制台路径；后续在现有U盘上部署的自定义脚本也必须使用7，否则虽有dmesg记录，INFO标记未必进入ramoops console。

内核已启用PSTORE_RAM/PSTORE_CONSOLE，继承DT的ramoops区在0x07400000，console-size为0x8000。它使用保留RAM，**不是写入U盘**：温重启可能保留，断电或bootloader/另一系统覆盖会丢失；此前失败恢复后的pstore为空，不能保证这次能取回。发生硬卡、SSH未起且无可用串口时，仍不能承诺拿到日志；增加日志不等于解决日志取回问题。尚未实机验收ramoops保留链路。

新构建的查询入口：

```sh
cat /sys/module/amvideo/parameters/gxlx2_hw_init
cat /sys/module/amvideo/parameters/gxlx2_hw_init_status
cat /sys/module/amvideo/parameters/gxlx2_hw_init_step
dmesg | grep e900-hw-init
```

`gxlx2_hw_init_status`：0=未排队/清理，1=等待，2=固定配置完成并通过有限读回，负数=错误（如-5读回失败）。若总线始终未就绪，状态保持1，不能认为初始化已完成。

功能默认开启；回退对照使用启动参数`amvideo.gxlx2_hw_init=0`，保留原有可启动但丢写的路径。不是旧的late_video_init参数。

## 已执行检查

* 所有补丁按固定源码顺序应用通过；decoder实际安装顺序在source_trace开/关、vdin_capture开/关四组合中均通过。
* 重写check-video-init-order，编译真实补丁中的就绪查询、总线分发/发布和固定配置函数；覆盖早/晚订阅、缺总线、分配/订阅/读回失败、重复事件、取消以及其他CPU/关闭路径。
* 检查非GXLX2/关闭分支的原硬件初始化函数体未改变；早期准备阶段没有MMIO读写，DI/供电/security操作不重复执行。
* 宿主模型检查每次固定MMIO访问前已有对应begin标记，正常返回后有end标记；包含13步骤和读改写的两半。
* 显示阶段探针检查及本地补丁/安装检查通过；缓存检查确认Linux变化重建内核和媒体模块并保留兼容工具链。

这些检查使用模拟MMIO、锁和通知器，不能代替ARM链接、真实IRQ时序或硬件寄存器支持验证。

## 下一步验收

推送后构建decoder镜像，source_trace可以关闭，vdin_capture不是本修复的必需条件。部署必须使用新构建的配套Image/SYSTEM/DTB/initrd，保留当前build278-off和Image277回退。

先验收稳定启动、status=2、关键读回及真实hold值，再测试视频。若卡启动或status为负，保留分阶段日志，不扩大为整函数重放。若初始化完成而硬解仍黑，继续独立VD1已知YUV帧验证，不宣称初始化修复已等于黑屏修复。
