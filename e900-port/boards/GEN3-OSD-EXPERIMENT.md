# GEN3来源日志与legacy OSD实验（0024）

状态：同版完整补丁应用及主机C检查通过；完整ARM构建、链接、实际播放仍待验证。不是黑屏修复。默认不输出新增日志，OSD策略默认保持原样。

## GEN3 RMW取证

新增三个独立root-only预算（0..512，默认0）：rdma、rdma_mgr、register_ops模块的`gxlx2_gen3_rmw_events`。`e900-debug.py arm --budget 128`同时开启，disarm同时归零。IRQ完成日志不会消耗这些预算。只针对GXLX2的固定1aa7，没有任意地址入口。

- rdma/source=-1：请求意图，result字段此时是传入位字段值，hardware/base为占位0；不能当作硬件0或整字结果。caller保留VSYNC API业务调用点。
- rdma/source=0：直接模式的既有硬件原值、mask位置及合成整字。
- rdma_mgr/source=0/1/2/3：合成基值来自硬件/当前队列/已提交表/冲突表。hardware是进入函数时原来就执行的硬件读取；base为最终选中基值，result为合成值。
- registers/source=0：直接codec_reg_write_bits入口，包括可经过该入口的DI、amvecm等共享写者。caller可能仍为业务包装；结合rdma请求事件追上层。

这些hook只记录既有读取的值，不新增硬件读取，不重放丢写，不操作停止态寄存器。没有日志不等于没有操作：完整整字写入仍看原write_vc事件；独立OSD等RDMA通道、DMA实际执行、固件/硬件侧变化并非全部覆盖。日志本身有耗时，应在结果里记录预算并用关闭日志的运行复核。

新版snapshot解析`e900-gen3`并保留最近arm后的事件和模块预算。旧核缺参数明确记unavailable，不把旧核测试当新hook生效。

判读顺序：

1. 直接模式清位后下一次hardware仍3033：不是仅靠RDMA旧表就能解释；检查同次caller与硬件返回过程，不能宣称外部业务主动置高位。
2. hardware=33但base=3033、source非0：优先追相应队列/软件表的保留和写者。
3. base=33而result高位变3033：查看该次start/len/val请求与业务caller。
4. 普通bit0 RMW以3033为基值：它会保留高位；“再次写入3033”本身不能证明它创造了高位。

## 主线OSD案例的对应实验

参考[主线G12A关闭primary plane导致blender停滞的修复](https://lists.openwall.net/linux-kernel/2019/06/05/606)。只借用“从混合器摘除输入，保留取图引擎”的方法，**不访问G12寄存器**。

本机原`osd_update_enable`关闭OSD1时既清legacy VPP_MISC bit12，也清OSD1 CTRL_STAT bit0。新增`/sys/module/fb/parameters/gxlx2_osd_blender_only`（bool0600，默认N）开启后，仅对GXLX2、OSD1、osd_ver<=OSD_NORMAL、无AFBC配置跳过后一个清bit0动作；仍走原OSD队列、VPP_MISC和amvideo通知。其他CPU/OSD2/较新blender/AFBC策略不变。开启OSD仍执行原使能步骤。

**必须在首次Stop/隐藏菜单之前设置开关。**它测试预防停滞，并不宣称能恢复已经停滞的硬件。N/Y两组应分别新启动、同一视频、同样Stop/replay，不叠加GEN3清位或RDMA模式实验。

新固件初始化完成、播放器空闲后，可执行受控测试：

```sh
# A组N；新启动的B组用Y。不是两个值在同一故障状态连续试。
printf 'Y\n' > /sys/module/fb/parameters/gxlx2_osd_blender_only
python3 /storage/debug-tools/e900-debug.py arm --budget 128
kodi-send --action='SetVolume(0)'
kodi-send --action='PlayMedia(/storage/videos/Test-H264-720p-60s.mp4)'
# 约15秒：确认首播，记录snapshot first --pixels。
# 同一首播内再隐藏/恢复菜单，分别观察电视和取快照：
printf '1\n' > /sys/class/graphics/fb0/blank
# 保存snapshot osd_hidden --pixels；记录电视菜单/视频状态。
printf '0\n' > /sys/class/graphics/fb0/blank
# 保存snapshot osd_restored --pixels。
# 然后Stop、重播同一文件，约15秒snapshot repeat --pixels。
# 清理次序：先unblank，再恢复原实验开关、关日志。
printf '0\n' > /sys/class/graphics/fb0/blank
printf 'N\n' > /sys/module/fb/parameters/gxlx2_osd_blender_only
python3 /storage/debug-tools/e900-debug.py disarm
```

若依赖现场观察，先取得用户回复再操作隐藏；用户不在时只记录无人观察，不把Canvas截图冒充输出。不要用旧跨Stop VDIN黑图直接验收，先通过场景响应正控验证回采可靠性。fb0/blank在本内核读回为空，不能据空串断言写入失败；日志、受保护配置读回和实际电视观察须分别记录。

## 构建与测试

decoder profile自动安装0024；source_trace保持false，vdin_capture保持此前设置，复用兼容缓存。内核补丁变更只使linux/media_modules-aml失效，不清工具链。要配套部署新Image与SYSTEM；当前盒子的287不包含该开关，因此本轮没有虚称做过新策略实机测试。

新增`check-gen3-rmw-osd.py`编译执行实际VSYNC直接RMW、完整管理器RMW、codec RMW，以及实际OSD legacy使能分支。检查硬件/队列/写表/冲突基值、独立预算与CPU/地址限制、读取/写入次数、OSD默认行为、实验隐藏后保留fetch和unblank恢复。完整patch应用、原基础调试检查及缓存失效检查也通过；这些不替代ARM链接和硬件时序验证。

## 此次构建一起加入的补齐项（0025/0026）

- GEN3除了位修改，也记录VSYNC、管理器入队及通用codec的完整整字写入来源。`source=4,start=0,len=32`表示整字写请求；hardware/base的0是未读取的占位，不代表寄存器原值为0，更不代表DMA已经执行。
- `fb.gxlx2_debug_events`记录OSD enable_request、enable_update、disable_policy，包含OSD编号、请求、先前软件使能、硬件代际、AFBC类型、blender-only是否实际适用。沿原控制路径记录，没有额外OSD硬件读取。
- 既有受保护活动legacy快照新增`black_path`：OSD1 CTRL_STAT、AFBC_ENABLE、VPP_CLIP_MISC0/1、VPP_VADJ_CTRL。可识别菜单取图关断、路径选择及裁剪压黑的差异；仍不是独立中间像素截图。只在原活动帧/legacy银行/VC总线检查之后读，不在停止态新增读取。
- VPU内存请求现在记录既有mempd_switch回调返回值。返回0不是硬件电源波形的证明。
- 可选VDIN补丁0026要求取得的ready帧timestamp不早于本次请求。旧队列帧经既有所有权API回收，继续等待新帧；2秒没有新帧则超时，没有“成功的黑图”。记录request/selected/now、frame、completion、stale/result，包结构仍为80字节v1，新增行为随该构建溯源。
- 新鲜时间仍不能证明DMA写到了预期缓冲区，也不能替代OSD显隐/运动标记的场景响应正控；本轮未把回采矛盾直接宣布修复。

## 一次构建后的运行矩阵

所有实验用同一个匹配Image/SYSTEM，通过运行时开关执行，分别新启动；一次只改变一项。

| 运行 | 控制开关 | 主要回答 |
|---|---|---|
| 默认首播→Stop→重播 | 全部策略实验关闭、有限日志开启 | 首播/停止/重播各阶段状态如何变化 |
| OSD默认关闭/恢复 | OSD实验N | 关闭fetch是否伴随输出停滞 |
| OSD blender-only关闭/恢复 | OSD实验Y、其他策略默认 | 保留fetch是否预防异常 |
| GEN3清位 | OSD实验N、GEN3实验Y | 高位在hardware还是软件表中重新出现 |
| RDMA直接/默认模式 | 其他策略实验N，沿现有参数显式切换 | 缓存基值与立即读改写的差别 |
| VDIN新请求回采 | 其他策略默认 | 超时、旧队列及新像素响应分别是什么 |

要观察开机早期GEN3写入，可在既有诊断boot参数中加有限预算：`rdma.gxlx2_gen3_rmw_events=128 rdma_mgr.gxlx2_gen3_rmw_events=128 register_ops.gxlx2_gen3_rmw_events=128 fb.gxlx2_debug_events=128`。不要求source_trace，也不需要为每个实验重新编译。

## 无VDIN的自动OSD对照

采集器新增`--control-only`，仅采控制状态及Canvas，不启动VDIN。每次Stop之后会额外保存`stopped_unobserved`，记录停止态软件状态；原硬件stage保护不放宽。可新启动分别运行：

```sh
# A：原OSD策略，显式关闭/恢复菜单，随后停止重播。
python3 /storage/debug-tools/e900-calibrate-loopback.py --control-only --osd-cycle
# B：另一新启动，唯一策略变化为保留OSD fetch。
python3 /storage/debug-tools/e900-calibrate-loopback.py --control-only --osd-cycle --osd-blender-only
```

工具检查初始化完成、无活动解码、GEN3关闭、RDMA默认；拒绝将GEN3/OSD实验组合。记录原开关，结束/采集异常均尝试unblank、恢复策略、停止播放和关闭日志。日志恢复失败单独记录。无人观察时仍标记screen_observed=false；不把Canvas图像当电视输出，也不根据自动脚本退出0宣称画面修复。

主机检查已通过：新直接/队列/codec日志C代码、OSD实际分支、默认和实验控制脚本的正常/异常清理；VDIN真实快照/保存45用例（含丢弃过期帧、等待新帧与超时）；可选capture完整测试、基础调试、补丁安装以及缓存失效测试。完整ARM编译/链接及实机仍待此次构建。
