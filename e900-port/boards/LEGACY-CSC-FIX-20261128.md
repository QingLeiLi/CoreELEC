# GXLX2 legacy CSC：通过实机的五处选择正式源码化

## 变更与依据

默认Build293首播正常、Stop/replay黑屏；仅禁止Stop HDR家族写入后重播正常；五指令293L实验在未禁flush时首播与默认Stop/replay均正常。证据、原始记录与限制见[legacy实测](BUILD293-LEGACY-CSC-TRIAL-20261128.md)。

新增默认decoder补丁`patches/linux/0044-gxlx2-legacy-sdr-csc-routing.patch`。内容与已通过293L的源等价候选0045完全一致，额外在源码谓词上限定`is_meson_gxlx2_cpu()`，避免二进制实验的无条件分支影响其它SoC。

只改变五个选择，不修改全局CPU ID、MMIO值、LUT内容、显示初始化或legacy/G12 helper内部写序：

1. GXLX2执行legacy `hdr_support_process`策略准备。
2. source/policy选legacy，避开G12 `hdr_policy_process`。
3. HDMI元数据发送使用legacy callback。
4. 主处理进入`video_process`，不走`video_post_process`。
5. `bypass_hdr_process`内部也使用legacy矩阵/LUT，不通过CPU数值绕回HDR2。

`candidates/0044-gxlx2-defer-signal-cache-while-layer-held.patch`仍只是另一个目录内的缓存候选，**没有安装**；不要与本次正式0044混淆。源等价0045保留为二进制provenance参考，安装器只安装patches/linux中的正式补丁。

## 格式审查：本轮没有扩大的部分

|入口|目前状态|含义|
|---|---|---|
|普通SDR/bypass|五处修改对应293L实测通过|仍需源码构建及重复验收|
|HDR10→SDR `hdr_process`|内部仍有数值>=G12→hdr_func|未宣称legacy完整接管|
|HDR10+ `hdr10p_process`|独立G12分支/hdr10p_func|未验证|
|HLG→SDR `hlg_process`|独立G12分支|未验证|
|HLG→HDR `hlg_hdr_process`|独立G12分支|未验证|
|SDR→HDR `sdr_hdr_process`|独立G12分支|未验证|
|格式特定histogram/HDR10 tone-map/CUVA更新|保留原规则|不能因SDR修复就认为这些HDR2能力安全|

不能简单全文件替换CPU判断：能力分类应按硬件模块建立，先验证需要处理的格式，再决定转换或明确限制。此补丁改善有实测证据的SDR重播，不承诺HDR色彩/色调映射能力，也不是全格式发布验收。

## 验证与构建

- 新host测试编译实际五条生产谓词，覆盖CPU ID0..127：仅GXLX2改变；其余CPU选择保持。剥除这五条谓词后全文与改前一致，证明没有顺便改helper写序；正式patch与293L source counterpart一致。
- 完整Linux补丁栈应用、strict启用/禁用debug编译、HDR原写序、return reason、init顺序、采集器及缓存回归通过。
- 缓存身份仍兼容原工具链，内核修改按已有规则清理linux/media，保留可复用工具链。不承诺GitHub缓存一定命中。
- CI已加入`check-legacy-csc-routing.py`。本轮没有触发云构建、没有操作盒子；盒子仍为正常播放的293L。
- 下一次Actions选`profile=decoder`、`target=image`、`source_trace=false`、`vdin_capture=true`（沿用293配置）。源码ARM构建/链接及部署待完成，不用二进制实测代替源码产物验收。

新构建后优先默认开关下首播/连续重播、global_output关闭恢复、菜单和视频画面，重复及真正冷启动；然后再扩其它格式。按协作约定每轮用户确认画面后再进入下一动作，不在黑态叠加试验。

## CI测试同步修复

用户构建在check-blend-transition.py报substring not found：该测试仍抽取0044之前不含GXLX2排除条件的dispatch文本，并期待0x2a走post。现更新为当前生产分支，执行同一段真实C，明确断言GXLX2走legacy，其它CPU选择和branch计数/active/path断言保留。不是移除检查或跳过GXLX2。

按工作流列出的37项主机检查全部通过。本地check-local首次失败来自旧audit/source-manifest漏osd_rdma.c；使用仓库当前source-fixtures清单及同一已固定hash源码后通过，CI的fetch步骤原本就生成该当前清单，未因此改生产代码。相关日志在本地/tmp/e900-workflow-host-review-20261128。未操作盒子、未改内核补丁；源码ARM构建仍待本次CI继续验证。
