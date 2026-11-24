# Build288 实机配对（2026-11-24/25）

构建45399538605，源码49dc688d3f70c0996354e97a78328e6e820b197f；成对Image288/SYSTEM288，U盘启动。原287保留回退，未写eMMC。完整ARM构建成功，新像素扫描在实机完成128/128并恢复探针字段。

## 现场确认配对

boot_id=311e174a-d3fc-4ef3-a657-5a937979f8a6。

- observed-first-ready：用户确认开头卡顿、白条快速闪现，随后正常；Canvas彩条正常。selector1/33/2/34均有随横坐标变化的彩条分量。
- observed-repeat：用户确认黑屏；Canvas与首播相同（BGR SHA256=01a2c70e83efc2b1643ed056928f100ecd78fd5469ec1a2f83bca3a15e3c1f76），但selector1/33/2/34全为legacy分量[64,512,512]。两次扫描均完成且恢复成功。
- selector8/40两次均零，不作为有效后混合观测点；16/48的物理命名仍未校准。
- 最初observed-first为无效尝试：Kodi尚未就绪，未打开视频；探针guard30/count0，不属于首播证据。

因此，已取得“Canvas正确而源码名VADJ1输入候选点为黑电平”的实际像素差异。结合寄存器差异，优先调查VD1取图/使能及配置提交。候选取点的精确物理位置仍需校准，不能声称已分离MIF与PPS的责任。

## 配置未落实

首播阶段live_gen=38420043，混合live=100054b0。黑屏重播live_gen=0（软件shadow=38400043）；混合live=100010b0，requested/shadow=100054b0。阶段记录发生在快照区间前部，不应说成与所有128个像素同时采样。

视频RDMA handle1的irq=0、configured=4，两次均不变；表items持续增长，最终有buf overflow直接回放。故首播出现画面不能证明正常RDMA执行。

源码rdma_mgr.c全局rdma_watchdog_count被视频rdma.c和OSD osd_rdma.c共同调用；任一方rdma_watchdog_setting(0)清零。OSD正常完成有可能掩盖视频停滞，属于已确认的共享状态设计和待验证的因果解释，尚未修改源码。

## 单次强制重提实验

使用现有rdma.force_rdma_config参数，不写原始寄存器、不切换RDMA模式。第一轮因基线全零而自动拒绝干预。第二轮基线为上述黑电平，设置1,0后恢复原0,0。

- 干预前irq0/configured4，VD1 live_gen0、blend100010b0。
- 干预后irq525/configured530，live_gen38400043/38420043，blend100054b0。
- 说明单次重提确实重启了视频RDMA完成链，并落实取图/混合使能。
- 但干预后的全部候选探针均为raw0=raw1=0；这不能解释为已证实的黑色像素，也不能声称修好画面。物理屏幕结果待用户反馈；诊断格式/有效位和探针启用环境需复核。

原始文件位于本地trial-build288：screen-observation.json、observed-pixel-comparison.json，以及各snapshot目录和force-once2/result.json。未自动提交或推送。

## 强制提交后重播：用户确认仍黑屏

observed-rdma-recovered，用户明确观察为黑屏。视频RDMA irq6374→8011/configured8016，VD1 live_gen38420043、blend100054b0，软件/硬件使能已恢复；GEN3=3033。全部候选探针仍为raw0/raw1零，扫描128点完成并恢复。不能将零值冒充有效黑色像素；也不能宣称该状态下最后有效点已经定位。RDMA恢复不足以恢复画面；不排除此前停滞/溢出留下的其他状态。下一步需对比已恢复提交状态下的取图/时钟/数据有效与探针有效性，不能重复归因于队列不执行。

## 冷启动播放前恢复RDMA对照

boot_id=0fa3f919-f32c-49e9-81ab-b6ba2ae7d47c；初始化后、任何播放前重提一次队列；首播前irq3430/configured3435。首播扫描时irq5314/configured5319，重播扫描时irq7404/configured7409，均有正常完成。

首播selector1/33/2/34均取得与彩条顺序相符的分量变化；Stop/replay后全部候选raw0/raw1变零。两个扫描均128/128且恢复成功。Canvas截图均已保存；本轮无用户屏幕确认。VD1 GEN、混合、尺寸、缩放、格式/路由配置均已使能；GEN3由33变3033。

这个对照排除了“必须先发生早期视频RDMA停滞/队列溢出，才导致重播像素异常”的解释。重播异常可在RDMA全程完成时出现。全零数据依旧没有被当作有效黑色像素：目前问题是Stop后数据有效或探针有效性丢失，不能仅凭候选名字进一步划定物理边界。

另一次黑屏活动播放通过现有只读/sys/class/vpu/info读得actual clk664MHz，mem_pd0(0x41)=c0，VD1[5:4]=0。源码ext_get_cur_video_frame使用VD1硬件Canvas0索引，GE2D截图由此索引读取，未改成解码器独立输出。

GEN3既有清位实验在RDMA健康时重新执行：submit2，RMW日志记录生成33；稍后硬件读回3033、像素探针全零，参数恢复N。尚无证据确认bit12/13含义或持续覆盖者，不能当作已验证可写配置位。网络补查的[S922X手册](https://www.scs.stanford.edu/~zyedidia/docs/amlogic/s922x.pdf)为另一代寄存器银行0x3216，其GEN3表没有给出这两个位，不能移植解释到GXLX2的0x1aa7。

## 分阶段生命周期二分与空操作对照

boot2b8801e3-0326-40bd-bdd5-813bc033c1af：播放前恢复RDMA，首播port1有8种原始值。播放器和解码器保持运行，只写video_global_output=0，1秒后恢复1，恢复后port1变为raw0/raw1均零。解码帧254→522，错误0；RDMA irq2743→3250；MIF GEN、VPP混合已恢复。脚本在此停止，没有执行下一阶段disable_video关开或完整Stop/replay（最后的清理Stop发生在结果采集后）。

为了排除诊断本身导致该差异，独立冷启动boot56956c13-d111-4a0f-af89-3d3cc85d1e36依次运行：纯像素扫描1→纯像素扫描2→寄存器日志快照→像素扫描3→GE2D Canvas截图→像素扫描4；四次port1均有8种值，全部128点完成并恢复，未切换显示状态。该正控支持“混合输入关闭/恢复是目前更小的复现边界”，不需要播放器teardown或VD1内存掉电。仍未取得本轮人工屏幕反馈，不将探针全零称作已确认的物理黑色像素。

另外：二分基线寄存器两次采样间GEN3已从33变3033，之后该基线像素仍有彩条，故3033本身不是足够的黑屏判据。

精简证据：[二分结果](evidence/build288-mix-bisect.json)、[空操作正控](evidence/build288-diagnostic-sham.json)。

下一版增加默认关闭的0028对照开关；见[预/后混合边界实验](BLEND-BOUNDARY-EXPERIMENT.md)。仅源码和主机检查，尚未ARM构建或实机测试此开关。

## 停止掩码试错，补齐时间边界（0029待构建）

临时Image289单指令预混合保留和后混合保留均未保留恢复后的候选信号；后混合版用户确认前半段正常、后半段黑屏且持续。双位保留版仅写入并重启，未测试。随后停止这组策略实验，启动入口恢复e900-Image288/SYSTEM288，并完成基线初始化。不得将这些试验声称为已实现完整0028源码保护的等价版本。

当前工作转为[固定点混合边界记录器](BLEND-TRANSITION-RECORDER.md)：原策略不变，同一点覆盖关闭前、软件enabled=0的混合关闭期间、恢复后的前16个VSync。数据保留unknown有效性，停止态不读硬件。源代码及主机检查通过，尚未ARM构建/部署0029。已有0028默认关闭，下一轮不启用它。
