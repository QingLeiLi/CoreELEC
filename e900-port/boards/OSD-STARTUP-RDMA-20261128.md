# 菜单迟到：OSD RDMA早期配置丢失

当前boot `2a016423-613c-402f-b41f-9bd02954b476`，build294/491fb30742，wait0/log4、网络等待关闭，屏保mode空。用户反馈不按遥控等3分钟仍没菜单；1分多钟按键无效、3分钟后按键才亮。显示器2K，EDID声明2560x1440p60，也声明1080p60；实际1080p60受支持，本轮未切分辨率。

## 纠正屏保解释

上一轮一次方向键恢复亮度，只与dim唤醒相容，不能解释此前黑屏。用户指出读取前可能已按键，故先前false值不能证明接口错误。此轮明确关闭屏保且重启后确认mode=""，迟到仍出现；“只是3分钟屏保”不足以解释。初始恢复亮度和启动迟到不是同一结论。

## 独立实机证据

- uptime3855.485→3856.489s，fb/rdma_irq_count=0→0；video rdma irq_count231247→231307，configured同步+60。先前仅看/proc/interrupts共享IRQ增长，不能推出OSD完成。
- OSD注册handle3、reset handle2，DMA表p=0x34e10000。manager的used=0并不代表未注册（实际由op指针区分），auto模式也不更新prev_trigger_type，不用这两个字段断言调用未发生。
- 固定7寄存器读回前后reset_count均2、OSD完成均0，无跨复位：CH1 START34e00000/END34e00007；CH3 START34e10000/END34e10a47（范围有效）；RDMA_ACCESS_AUTO=00000120、CTRL=0、STATUS=900。
- RDMA_VER_1通道3映射：触发字段bits24..31，写方向bit7，地址递增bit3。0x120只使能视频通道1，OSD通道3未触发且写方向未设。
- 源码update_table_item在item_count>500或reset flag时，把整个积压表逐项osd_reg_write直写，再重置表计数。现场268.867s记录overflow、rdma_cnt=0；与迟到后按键才可见相吻合，但确切亮屏瞬间和overflow因果仍需对照，不把它叫固定3分钟定时。

## 白盒依赖缺口（本项目适配引入）

1. `osd_io.c:osd_reg_write`直接调用aml_write_vcbus（或自身映射），表START/END可在早期写入。
2. `osd_rdma.c:start_osd_rdma`在CONFIG_AMLOGIC_MEDIA_RDMA路径调用`rdma_config(channel3, VSYNC|AUTO)`。
3. `rdma_mgr.c:rdma_config`的AUTO分支通过WRITE_VCBUS_REG_BITS配置触发、增量及方向。`vdec_reg.h`宏转codec_vcbus_write/read，最终经过register_ops dispatcher。
4. 本项目0006将GXLX2总线接口延后到late_initcall_sync；本boot约1.338s才发布，前面0.513s OSD配置、0.930/1.171s两次重启都早于发布。ops未就绪时codec_reg_write直接返回，RMW也读假0；缺乏后续OSD触发重放。
5. 视频通道随后每帧配置/独立stall重提，因此通道1能恢复；OSD没有同样的独立重放。现状恰为有效OSD表地址+触发位0+OSD完成0，而视频通道正常。

这是晚发布媒体接口后没有补齐RDMA初始化依赖；0019已处理video_hw，但没有覆盖本条OSD/manager路径。不能通过把晚发布简单提前来绕过（早期发布曾造成启动失败）。RDMA probe中的CTRL初始化也经过晚注册接口，CTRL0因此有独立来源；本轮不一起改CTRL，避免混淆。

## 已准备的最小因果验证（尚未执行）

仅在同boot、No vdec、OSD完成0、CH3 DMA范围合法且AUTO仍0x120时，按现有驱动字段定义恢复通道3：AUTO→0x010001a0。只改bits24..31/7/3，保留其它通道；不写CTRL、不做共享复位、不改分辨率。观察两秒OSD完成是否持续增长及用户菜单反馈；失败恢复原通道3字段并停止。脚本[osd-rearm-once.py](evidence/osd-startup-20261128/osd-rearm-once.py)只允许该固定boot和值，当前只编译语法，未执行写入。

已询问用户是否方便观察，等待确认。实测前不把候选写成已修复；若成功，再处理启动时的RDMA就绪依赖和重放，不能把单次寄存器修补当永久驱动修复。

原始记录：[独立计数](evidence/osd-startup-20261128/no-screensaver/visible/osd-counters.json)、[固定寄存器读回](evidence/osd-startup-20261128/no-screensaver/visible/rdma-fixed-read.json)、[EDID/迟到现场](evidence/osd-startup-20261128/no-screensaver/visible/display.txt)、[试验计划](evidence/osd-startup-20261128/osd-rearm-plan.json)。Android Logo可能被保留到Linux早期，不能仅按该图案判断仍停在Android；缺少CE Logo也要先排除OSD更新缺失，尚未精确分段测出U-Boot读盘耗时。
