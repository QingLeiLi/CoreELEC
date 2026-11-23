# 主线/TVBian与CE播放路径核对：2026-11-23

目的：以可读源码对照当前CE4.9实现；本轮未切换系统、未修改设备寄存器、未再次重启。

## 实机对照先决事实

云构建45134615879、提交`c19cb745ee`，以完全相同的Image278/SYSTEM278/DTB278/uInitrd278进行开关对照：

* `amvideo.gxlx2_late_video_init=1`：用户看到安卓引导logo后HDMI无信号、U盘空闲，SSH/Kodi未上线。没有可用pstore记录，尚不知道具体卡在哪条语句。
* `amvideo.gxlx2_late_video_init=0`：正常进入CE，boot_id为`3cf65dc4-8dc4-4fa8-9a95-e951786c8aeb`。H.264 1280×720@30解码5秒149帧，帧错误及硬件错误均0；没有据此宣布HDMI视频正常。
* 关闭路径仍记录初始化VCBUS丢写7→16。由此可确认9次丢写现象，但不能确认它就是硬解黑屏根因。

结论：不能将0010默认开启称为已验证修复。当前完整晚初始化路径存在启动回归；不能只因为主线工作就整体推迟CE的`video_init()`。

## 先区分正式主线与主线内核加树外驱动

* [Linux v6.18 vdec_platform.c](https://github.com/torvalds/linux/blob/v6.18/drivers/staging/media/meson/vdec/vdec_platform.c)有`VDEC_REVISION_GXLX`；本轮读取的上游master同文件也未见GXLX2专用revision。GXLX与本机GXLX2不能仅凭名字混同。
* TVBian的[meson-codecs说明](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/patches/meson-codecs/README.md)明确是`meson-sm1-codecs`基于`eb7a444`的树外解码器加补丁，Upstream一节写明尚未提交。
* [GXLX2解码补丁](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/patches/meson-codecs/0001-vdec-gxlx2-is-g12a-class.patch)使用G12A类解码配置，但保留GX DMC地址，排除不存在的HEVC front clock，并保留特定线性输出对齐位复位值。它不意味着显示VPP也应全局改成G12A。
* [视频支持表](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/docs/video-support.md)包含解码及输出测试，但S905L3的压缩帧、10bit及无复制送屏相关项仍有“已到显示驱动，尚未屏幕验证”的边界。不能统称全部零拷贝显示已完成。

这证明有可借鉴的同类硬件实现，不等于换一个未打补丁的主线镜像就能直接运行本机CoreELEC。

## 具体显示配置差异

以下行号对应本地`coreelec-audit`阅读副本，主线版本v6.18、CE版本见pins.json。

| 项目 | 主线实现 | CE4.9实现/当前证据 | 如何使用该差异 |
|---|---|---|---|
| VPP保持行数 | `meson_vpp.c:115`显式写PRE=4、POST=4，即`VPP_HOLD_LINES=0x404` | `video_hw.c:6663`仅读取其低字节，保存到软件`vpp_hold_line` | **重新执行读取并不等于初始化这个寄存器**；不能只说晚初始化自然修好hold_line |
| VD1 MIF保持行数 | `meson_overlay.c:544`独立设置`VD_HOLD_LINES(9)`，对应GEN bits24:19 | `video_hw.c:1047`用`vpp_hold_line`构造GEN。旧读回GEN=`0x38000043`，该字段为0；这是此前读回，不冒充本轮278已读回 | VPP保持行数和VD1保持行数是不同字段；主线自己的4和9也不是同一个值 |
| 输出FIFO | `meson_vpp.c:111`，legacy分支掩码设置`VPP_OFIFO_SIZE=0x77f` | `video_hw.c:6613`，legacy分支设置`0xfff` | 输出FIFO与下面的VD1亮度FIFO是两个寄存器；不得混用数值 |
| VD1亮度FIFO | `meson_viu.c:465`设置`0x00ff00c0` | 历史实机为`0xff00c0`；CE仅对TXL/TXLX另写`0x180` | 没有依据把本机一律改成TXL的`0x180` |
| GEN其他控制位 | 主线线性分支设置urgent、保持行数、色度重复等 | CE GEN还有GO_FIELD复位等BSP控制；此前单独改变复位/自由时钟未修复 | 不能照搬整个GEN常量；应逐字段比较，避免同时改变多项 |
| 帧提交 | `meson_overlay_atomic_update()`准备影子配置，`meson_crtc.c:476`等在提交路径写入硬件 | CE由amvideo VSync和RDMA提交 | 不把“atomic_update函数里算出配置”说成该函数立即逐帧直接MMIO写全部寄存器 |
| 初始化范围 | DRM对VPP、VIU、plane和输出分别配置 | CE `video_init()`注册platform驱动、probe、中断、sysfs和字符设备等；probe调用`video_hw_init()` | 延后整个video_init会影响远多于9次寄存器写入；0010失败不能直接归咎于某个hold_line值 |

主线来源：[meson_vpp.c](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/meson/meson_vpp.c)、[meson_overlay.c](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/meson/meson_overlay.c)、[meson_viu.c](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/meson/meson_viu.c)、[meson_crtc.c](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/meson/meson_crtc.c)。

## 下一步可以怎样缩小试验

1. 保持已能启动的`late_video_init=0`，先确认当前HDMI和菜单现象，不再整体延后初始化。
2. CE现成的`vpp_hold_line`是可写模块参数（`video_hw.c:7015`），可用于不重新构建的单字段对照。先读取本次实际值；若测试9，必须在新帧配置生效后通过已有受限探针确认GEN字段实际变化，并在试验后恢复原值。它只测试VD1保持行数，不等同于主线`VPP_HOLD_LINES=0x404`。
3. 若需恢复完整一次性配置，应拆出可审计的VCBUS初始化子集，放到总线就绪后的合适位置；单独处理软件状态、供电、IRQ和RDMA依赖，不能直接再次调用整个video_init或video_hw_init。
4. 主线/TVBian的像素验证方法仍有价值：解码帧与软件参考对比、显示平面单独验证。当前CE的GE2D读图只能证明Canvas内容；未校准的VDIN回采依然不能作为VD1/PPS像素通过的证据。

以上是候选试验设计，**本轮没有写入vpp_hold_line、没有添加修复补丁，也没有宣称已找到黑屏根因**。资料副本保存在`coreelec-audit/research-20261123/tvbian/`；部署对照在`trial-build278/result.json`。
