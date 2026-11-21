# GXLX2 显示与分阶段取图资料核查（2026-11-21）

范围：E900V21C、GXLX2/S905L3-B、P291、1GB。此次只查资料，没有改盒子、部署或重启。结论用于安排验证，不代表黑屏根因已找到。

## 1. 最值得使用的新资源：TVBian 的同芯片实现

固定提交：[sormy/tvbian 90185b682c9ab9cfd6409e65e7d05d3124fe1f4a](https://github.com/sormy/tvbian/commit/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a)，提交日期 2026-11-20，避免将未来版本或移动分支当作本次依据。

作者的 [H96 Max M20 板卡记录](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/docs/h96max-m20/board.md) 对象是 GXLX2/S905L3、P291、RevE，2GB LPDDR3；声明 HDMI、GPU、解码可用。[板卡工作日志](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/docs/h96max-m20/worklog.md) 记录在屏幕上观看硬解视频：4K30正常，4K60有异常；作者将后者联系到显示端读取带宽。这是其他板卡上的实测报告，不是 E900V21C 的验证。

可提取的内容：

| 资源 | 对当前工作的用途 | 边界 |
|---|---|---|
| [解码器补丁说明](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/patches/meson-codecs/README.md) | GXLX2 的 HEVC/VP9 采用 G12A 类能力，但时钟、行对齐有例外；提供实际补丁 | 主线 V4L2 驱动，不能直接套进 CE 4.9 |
| [解码排查日志](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/research/h96max-m20-video-codecs/worklog.md) | 记录逐帧与软件解码对比、失败对照；解释微码、邮箱、stride 问题 | 该项目的解码成功不证明本机显示输出正常 |
| [微码来源](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/firmware/amlogic/README.md) | 有原厂微码版本和重打包规则，适合后续 HEVC/VP9 核对 | 不按文件名盲目替换本机微码 |
| [视频能力与验证边界](https://github.com/sormy/tvbian/blob/90185b682c9ab9cfd6409e65e7d05d3124fe1f4a/docs/video-support.md) | 明确区分解码、显示和压缩帧传递 | 部分零拷贝/压缩帧输出仍标注未实机显示，不能称为全部硬解直出已完成 |

建议把它作为可工作的另一套驱动与测试方法参照；本机只有1GB，不直接套用它的板级镜像、内存声明或CMA配置。用户目标仍为CoreELEC。

## 2. 2026年已有GXLX2主线HDMI成功案例

[Zinan Zhou 的2026-07-18 RFC](https://lkml.iu.edu/hypermail/linux/kernel/2607.2/05033.html) 描述：显示管线、时钟及PHY沿用GXL风格，但HDMI控制器采用直接映射访问；提出独立GXLX2匹配数据，而非整套采用G12A配置。作者报告HG680-LC上的1080p/1440p显示和音频测试。

[ophub #3604](https://github.com/ophub/amlogic-s9xxx-armbian/issues/3604) 的维护者给出补丁提交，用户随后报告HDMI恢复；[具体维护者回复](https://github.com/ophub/amlogic-s9xxx-armbian/issues/3604#issuecomment-5086853294) 列出包括e900v22e在内的DTS更新。[#3650](https://github.com/ophub/amlogic-s9xxx-armbian/issues/3650) 则记录运行时识别回退造成挂死及显式compatible的修正，后续还有回归反馈，不能只看“已关闭”。

这修正了旧资料中“S905L3B主线永远没有HDMI”的说法。但当前CE的菜单和软件视频已能显示，这些HDMI访问补丁不能被当作当前VD1硬解黑屏修复。新资料的主要用途是确认不同子模块必须分别选择兼容路径。

| 子模块 | 查到的依据 | 当前采用方式 |
|---|---|---|
| VPP/显示与HDMI PHY | RFC明确为GXL风格 | 继续以legacy路径比较，避免全局改成G12 |
| HDMI控制器寄存器访问 | RFC及社区成功案例为直接映射 | 主线移植参照，当前CE黑屏不先改此处 |
| HEVC/VP9解码器 | TVBian有G12A类实现和例外 | 后续核对解码能力，不推广到VPP/VDIN |
| VDIN独立VD1/PPS取点 | 此次没有查到GXLX2上的可靠截图案例 | 仍标未验证，不以驱动枚举证明硬件支持 |

## 3. 数据手册提供了两个应先核对的具体点

[Amlogic S905X Datasheet Rev0.2](https://www.scs.stanford.edu/~zyedidia/docs/amlogic/s905x.pdf) 是GXL家族参考，不是GXLX2专用手册；寄存器定义应再与本机原厂路径交叉确认。

* 印刷页126：VPU_VIU_VENC_MUX_CTRL(0x271a)的数据和时钟源切换均要求先清零，再选择新源。故VIDEO回采校准需记录切换前/清零后/选择后状态。是否影响此前246/247尚未验证，不能据此直接宣布原因已找到。
* 印刷页139：VIU_MISC_CTRL0(0x1a06)的bit29选择VD1帧/行同步来源。它与VD1 GEN中的手动启动、遇GO_FIELD复位控制不同。应先读当前来源并对照原厂，而不是继续重复手动脉冲。
* 印刷页140–141：VD1 GEN含独立时钟、复位、状态字段。因此270的VPP门控阴性不能排除VD1自己的内部时钟/同步问题。

后续最小诊断应固定读这些已明确的字段，并保持活动帧/总线/预算保护；不新增用户态原始寄存器地址接口。仅在与原厂行为核对后安排单项试验。

## 4. 旧issue与相似黑屏帖的实际价值

重新读取了用户之前给出的四个issue正文：

| 链接 | 可用资料 | 不能推出的结论 |
|---|---|---|
| [#2447](https://github.com/ophub/amlogic-s9xxx-armbian/issues/2447) | 同系列线刷、外置启动、遥控码迁移记录 | Armbian引导成功不证明Linux硬解显示 |
| [#1256](https://github.com/ophub/amlogic-s9xxx-armbian/issues/1256) | 底包、引导和无HDMI时的SSH操作 | 旧的无HDMI记录不是当前驱动支持上限 |
| [#1514](https://github.com/ophub/amlogic-s9xxx-armbian/issues/1514) | eMMC频率、extlinux及板级DTB经验 | 无VD1/PPS出图修复证据 |
| [#939](https://github.com/ophub/amlogic-s9xxx-armbian/issues/939) | eMMC兼容讨论入口 | 无当前硬解黑屏的直接结论 |

以上四帖本轮未逐条复核全部历史评论；新#3604、#3650的评论已读取。不要声称所有帖子及附件均完整审计。

[windyard/android-box-to-linux](https://github.com/windyard/android-box-to-linux/blob/master/README.md) 是同为GXLX2/P291的BSP显示记录，指出logo平面、OSD提交、透明度等会造成黑屏，也明确记载一些早期推断后来被推翻。当前本机OSD已有实测，保留其排查方法，不重新把这些OSD问题当成VD1根因。

## 5. 用资料替代下一轮试猜

1. 先按手册和原厂路径核对VD1同步源，以及回采源切换顺序；目前仅有假说，没有新硬件结论。
2. 校准VIDEO取点时，先规定可观察的已知图像及新鲜度判据，再执行；无帧或旧图不能判为该级黑图。BIST271/272未通过正控，停止使用其结果定位。
3. 比较TVBian所用主线VD1初始化、Canvas/格式和同步处理与CE4.9对应功能，形成具体差异表；不要求立刻换发行版或全量构建。
4. 仅为已确认差异设计一个可证伪试验。若无可校准的中间像素取点，应明确观测能力边界，不承诺通过加软件日志截到每个硬件级。

未找到可直接套用、且已在E900V21C验证硬解出图的CoreELEC补丁；这只是本轮检索结论，不代表不存在其他未公开实现。来源索引：本地 coreelec-audit/research-20261121/sources.json。
