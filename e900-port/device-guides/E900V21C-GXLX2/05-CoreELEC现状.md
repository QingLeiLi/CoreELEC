# CoreELEC适配：基线、改动和当前线索

截至2026-11-27，目标仍是USB CoreELEC；黑屏未修复。下面区分已有实机能力和源码候选，不把编译或日志存在当验收。

## 固定官方/上游代码

|部分|固定版本|
|---|---|
|CoreELEC系统/构建|21.3 NG / Omega，fc61125e8900ab0c2593a29b615980ed0cd5b939|
|Linux|CoreELEC/linux-amlogic 4.9.269，50c8e8154c5aba3c7cd8438d04dd5fdd51733e41|
|媒体模块|CoreELEC/media_modules-aml，60561618f2bf154c1438d3c790b625ff01f215c3|
|Kodi|项目固定CE Kodi包，acc0fc66bc6af69c31a93c5d17e36900343263b7|
|libamcodec|沿用NG预编译库，未修改其内部算法|

这里“官方代码修改”指本地fork基于这些固定上游的补丁，**不是已被CoreELEC官方接收或官方支持本机**。实际安装列表在`e900-port/scripts/install-patches.py`，pin在`e900-port/pins.json`。

借鉴来源：同CE版本的GXL/P212 DTS及厂商媒体栈；原厂/工作Android P291资料用于板级接线和寄存器行为核对；ophub Armbian用于USB启动链与社区机型经验；Linux主线/TVBian代码作为能力与寄存器语义参考，没有直接把主线内核换成CoreELEC媒体栈。详见[基线与播放导航](../../BASELINE-AND-PLAYBACK.md)。

## 主要源码改动

|范围|实现内容|状态界限|
|---|---|---|
|板级/身份|识别GXLX2而非强行别名GXL/G12；P291 1GB、USB、RMII、MP2 GPU、framebuffer/安全内存保留区|已有等价配置及源码启动实测；不推定其它内存板兼容|
|HDMI/总线|GXL PHY配置配直接TOP/DWC访问；媒体总线发布/延后固定视频寄存器初始化|HDMI菜单/音频有实测；不代表HDCP或所有显示模式通过|
|视频/解码|legacy VPP/MIF选择、避免不支持POST2/SR访问；DI缺失可选时钟保护；VLD DMC通道/时钟能力处理|H.264解码推进与部分正常视频实测；重播异常仍在|
|遥控|原厂remote资料提取、meson-ir及按键映射|用户确认按键可用；相同外壳遥控器仍应核型号|
|构建/USB|媒体模块安装修复、下载与增量缓存、成套USB镜像、原CE initramfs复用|构建/镜像检查通过；不能混用不同构建的SYSTEM和内核|
|诊断|生命周期、RDMA/OSD/直接写、受保护配置读回、netconsole、像素候选与回采|观测工具不是根因修复；每种数据均有有效性门槛|

补丁目录：`e900-port/patches/linux/`、`e900-port/patches/media/`。播放路径：Kodi VideoPlayer → libamcodec接口 → vdec媒体模块解码 → vframe/provider → Canvas/MIF/格式器 → PPS/VPP → HDR/CSC/混合 → ENCP/HDMI。部分变换实际位置受legacy路由控制，不把上述概念顺序当作每一级都有独立像素tap。

## 已确定、可以用于后续定位的事实

- 源Canvas在对应实验中有正常彩条并持续更新，保留该证据；本轮不重复增加Canvas源读取。它不等于Canvas下游都正常。
- 新启动首播存在正常画面；真实Stop/replay及`global_output`关闭/恢复后可出现黑屏。两种触发单独对照，不能默认同一根因。
- 解码与帧/PTS仍可能推进；恢复后混合位为正常值也不能证明实际像素通过。
- 正常/异常配置差异曾集中在HDR2_CTRL 0x3800及矩阵系数0x3802/04/06/0e。0x1d25是POSTBLEND当前位置，0x1d28是FIFO状态；归零不证明缺某个“重启触发”。
- 未证明`new_vframe_count==0`会停止提交，源码不存在该短路判断；全局输出脉冲也非必经真实关层。
- 静态彩条回采不能证明电视正常，用户明确报告过黑屏而回采像素不变。因此采集需验证帧槽关联、动态内容和物理反馈。

## 最新已提交的源码候选（未部署实测）

|提交/补丁|用途|
|---|---|
|f190a91f80 / 0037|替换Claude的bit12猜测，默认关闭的一次HDR恢复实验；删除原“计数赋1重启VPP”hack|
|29752e9db4 / 新0038|首播→Stop→重播独立有界时间线，保留调用、写入来源及顺序|
|544fd3e6ca / 0039、0040|VDIN pre-ACK完成槽→读槽/包CRC关联；活动态HDR/PPS读回及TX状态采集|
|13dc362fa0 / 0041|DCU/PPS进入/返回；四项HDR矩阵实际读回及函数/寄存器差分索引|
|136b8016a2 / 0042|DCU/PPS跳过、CSC/HDR七条返回原因，避免把外层返回当配置完成|

这些提交已有相关主机测试；这轮ARM编译/部署/真实首播重播配对尚未完成。当前盒子最近核对是Claude内核（Nov26 15:36:29 UTC），不是最新源码。不能拿旧盒子读出的日志当新0039/0042已验证。

## 后续新机的选择

若只是要建立稳定管理入口：到Android root ADB和Armbian有线SSH即完成相应目标。若要CoreELEC播放器：使用同板型实验镜像，只装U盘，保留Android；首播、重播、菜单和音频分别验收。目前不能对外发布“各种硬解均可用”或“CoreELEC可装eMMC”的结论。

开发接手入口：[当前台账](../../boards/VD1-VPP-CONVERGENCE.md)、[成对采集](../../boards/PLAYBACK-AUDIT-20261127.md)、[全链路覆盖](../../boards/FULL-CHAIN-OBSERVABILITY-20261127.md)。
