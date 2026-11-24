# 中间像素观测（0027）

状态：源码与主机状态机/采集器检查通过；完整ARM构建、每个取点的实机校准尚未完成。**下面是8个源码命名的候选取点，不是8个已经确认有效的物理观测点。**

## 取点来源

复用固定基线`amvecm.c:amvecm_set_post_matrix_show/store`公开的VPP matrix probe选择器和坐标功能。候选列表固定，不接受寄存器地址、任意selector或坐标：

| selector | 源码命名 |
|---|---|
| 1 / 33 | VADJ1 input / output |
| 2 / 34 | VADJ2 input / output |
| 8 / 40 | postblend input / output |
| 16 / 48 | OSD1 input / output |

这些名字来自驱动接口。硬件是否支持每个值、某些端口是否别名，以及它们与VD1/PPS/blender的确切物理边界，都需要校准，不能仅凭名字断言“VD1后”或“混合前”。没有开启G12 WB0/1回写路径。

每个selector按输入图像宽高、输出宽高分别取一行8个中心坐标，共128个稀疏像素；同时保留两套坐标，避免把缩放前后坐标范围混用后的空值当故障。不是整帧截图，不会自动重建视频图像。

## 内核工作方式与保护

`video_hw.c`在正常`vpp_blend_update`末尾调用VSync状态机。默认为idle，每帧不访问新增硬件；root显式启动后才工作。

- 只允许GXLX2、legacy VD1、非压缩、已使能且拥有活动帧、VC回调就绪、MIF地址1a50/1aa7、主VPP、逐行输出，输入/输出均不超过1920×1080。
- 只修改VPP_MATRIX_CTRL的探针选择字段bit10..15和VPP_MATRIX_PROBE_POS的坐标字段，保留其他转换/使能位。
- 每次选点后等待两个后续VSync，再读固定PROBE_COLOR（1d5c）和legacy第二字（1dd7）。不访问G12寄存器银行。
- 每次读像素前检查selector和坐标仍为本次配置；被其他写者改动就判invalid，不能返回“有效黑色”。
- 采完恢复原探针字段并检查即时读回；只恢复仍由自己占用的字段，不覆盖别人的选择器改动。正常图像配置的其他位在运行中变化时予以保留。
- 关层前显式取消/恢复；如果已经无活动帧或总线不可用，绝不为清理而强读停止态银行，标记restore-deferred，下一次安全活动帧再恢复。未恢复时拒绝新扫描。
- 同一扫描中provider epoch或尺寸变化则失效。记录frame/PTS用于区间关联，**不声称128点来自同一帧**。

固定总数约需257次VSync：60Hz约4.3秒，30Hz约8.6秒。工具默认15秒超时，超时尝试取消；恢复仍未完成会明确报告failed/restore_pending。

## 数据与格式

逐点记录：generation、selector、输入/输出坐标网格、x/y、两个原始字、活动帧index/PTS。

保留同版amvecm的两种解析候选：legacy 12bit三分量（跨两字）以及G12 10bit三分量（第一字）。本机CPU数值较大不足以决定格式，因此不按CPU ID自动选定。JSON同时保留原始字和两种结果；SVG仅画两种RGB解释下的色块，醒目标记UNCALIBRATED/NOT a screenshot。实际颜色空间/分量顺序仍需用已知场景验证。

控制接口均在amvideo模块：

- `gxlx2_pixel_scan`：写1启动固定扫描，写0请求取消；读回状态与generation/count/owned/restored/epoch、原因和guard。
- `gxlx2_pixel_page`：0..7，仅选择软件结果页。
- `gxlx2_pixel_data`：只读，每页16条软件缓存结果，不访问硬件。

状态0 idle、1 queued、2 running、3 complete、4 cancelled、5 invalid、6 restore-deferred。

reason：1不活动/总线不可用；2 epoch或尺寸变化；3选择器争用；4恢复读回失败；5取消。

guard位：1其他CPU、2非legacy、4 G12 MIF选项、8借用VD2、16层未启用、32无帧、64压缩、128总线未就绪、256银行不符、512副VPP、1024无输出模式、2048尺寸不支持、4096隔行输出。guard读取软件状态，不用停止态寄存器判断。

## 自动取证

新版`debug-tools`包含内核配套采集器：

```sh
python3 /storage/debug-tools/e900-debug.py snapshot --label first --pixels --pipeline-pixels
# Stop/replay后，在活动播放期间：
python3 /storage/debug-tools/e900-debug.py snapshot --label repeat --pixels --pipeline-pixels
python3 /storage/debug-tools/e900-debug.py compare FIRST_DIR REPEAT_DIR > comparison.json
```

每份快照新增`pipeline-pixels.json`、成功时`pipeline-pixels.svg`。采集器用进程锁保护分页读取，并核对generation、点数、序号、selector、坐标网格以及恢复状态；缺点、换代、争用、超时保持failed，不据零值判黑。

新版首播/重播runner在活动播放快照时自动调用这一观测；停止态快照不启动它。配套的OSD control-only测试也会取到各阶段的点阵。工具停止播放前等待扫描结束/取消，异常清理仍记录恢复结果。

比较报告的`pipeline_pixel_comparison`按selector/grid列出8对原始值及变化数；坐标不一致则incompatible。**不会自动挑“最早变黑”的点**，除非已经独立确认该点的物理位置、格式和场景响应。

## 实机校准与二分顺序

1. 新启动首播已知运动彩条，保留Canvas图、每个端口原始值及两种分量解释；先验证哪个端口/格式能响应已知彩条。
2. 改变已知视频内容，重复取点，排除常量/陈旧值；只有selector读回一致还不够。
3. 保持视频不变，分别隐藏/恢复OSD，验证哪些端口响应OSD变化、哪些响应视频。未响应的候选标unknown，不拿它做定位。
4. 同一启动执行Stop/replay，比较已经校准的端口。依据最后一个正常与第一个异常的有效点缩小范围，再选单一状态恢复验证因果。
5. 若全部端口无响应、疑似别名或格式不能确定，本轮观测判未校准；不能将128个零值包装成128份黑屏证据。

这次新增点可以绕开VDIN向DDR写回/CPU读缓冲区的路径，提供另一种像素观察；仍需它自身的场景正控，不能用“不同机制”替代校准。

## 已完成检查

真实内核状态机在GNU89/GNU99主机桩环境编译执行；覆盖默认零读写、13类保护、128点与两VSync等待、停止前/延后恢复、保留非探针位、被抢占、写入不生效及8页结果。真实Python采集器覆盖成功、内核invalid、超时取消、generation变化、缺点及未校准预览标识。还修正了旧stage和初始化测试对新增GEN3日志辅助函数的测试依赖，避免CI在构建前失败。

这些检查验证软件行为，不替代完整ARM链接、真实像素探针支持和物理HDMI验收。
