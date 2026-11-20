# 后置视频初始化与可靠抓帧

目的：当前H264样片已能经Canvas/GE2D读出完整图像，下一步修复初始化时序缺口并继续定位HDMI视频黑屏。这不是硬解适配已完成的声明。

## 0010：总线就绪后再初始化视频

当前旧内核已核对的初始化表是 `video_init6` 在前、`gxlx2_reg_ops_late_init7s` 在后。`amvideom_probe()` 中的 `video_hw_init()` 经真实codec分发接口访问总线。回调尚未注册时，写入直接返回，读取返回0。

补丁加入 `codec_reg_bus_ready()`，只检查回调指针，不访问硬件。实验启用后，GXLX2跳过原initcall6的视频初始化，改到late-init-sync阶段；先确认VC、HHI和DMC回调就绪，再调用原有 `video_init()`。不提前发布媒体总线，不重复初始化，不改变CPU身份；其他SoC和默认关闭路径保持原时机。

实验默认关闭，新构建通过以下启动参数启用：

```text
amvideo.gxlx2_late_video_init=1
```

它不是Actions里的 `source_trace` 开关。仍选择 `decoder / image`、`source_trace=false`；测试部署时才在独立USB脚本中启用此参数。

完整ARM构建后须验证：

1. 新Image的初始化表中，媒体总线7s入口早于 `e900_video_init_late7s`。可检查System.map，或从新Image离线恢复符号。源码Makefile顺序不能替代最终链接证据。
2. 参数关闭时先启动，核对原有菜单、网络和回退入口；确认新参数存在且值为N。
3. 独立脚本启用参数后，核对新boot ID及参数Y，日志应依次出现：

```text
e900-video-init: defer video_init until late media buses
e900-video-init: media buses ready; initialise video now
e900-video-init: late video_init returned 0
```

若总线未就绪则明确报错并拒绝初始化，不把忽略写入当成功。最终需验证物理H264视频及菜单，随后才扩展到HEVC等码流。

## 0011：等待GE2D完成再报告抓帧成功

原抓帧代码调用 `stretchblt_noalpha_noblk()`，随后释放Canvas、归还帧并报告完成。203实测比较立即读取与“先读1字节、等500ms、再读余量”：320、640、1280宽度均在等待后得到完整色条，立即读取可能出现局部未完成或旧内容。

补丁仅对GXLX2使用既有 `stretchblt_noalpha()` 阻塞接口，正常提交成功路径等待后再释放引用。其他SoC、坐标、像素格式和颜色转换不变。用户态字节解读为BGR24；不把通道顺序改成一个新的内核问题。

这是抓帧可靠性修复，不直接修复HDMI视频。真实DMA、中断等待失败或取消，以及新驱动硬件回归仍需验证。

## 验证边界

- 原视频与盒子播放文件SHA256一致。203取得完整1280×720 H264帧，显示配置前后相同，测试后已停片。
- 0010宿主测试使用真实寄存器宏、分发代码及初始化包装器，复现早期丢写，覆盖CPU0..0x3f、默认路径、缺失回调、分配和初始化失败。
- 0011宿主测试使用真实捕获调用片段、GE2D命令生成和队列代码，模拟完成事件，验证Canvas释放顺序、坐标和其他SoC路径。
- 补丁顺序应用、安装器保护、缓存失效测试通过。内核变更重建linux和media_modules-aml，兼容工具链保留。

完整ARM构建和0010/0011的新驱动实机测试尚未执行。模拟完成事件不等于真实DMA完成；当前样片抓帧成功不证明所有H264、HEVC、音视频同步、Wi-Fi/蓝牙或eMMC已经适配。

图像及链路证据见 [显示链路复盘](DISPLAY-CHAIN-REVIEW.md) 和 [量化记录](evidence/frame-readback-203.json)。
