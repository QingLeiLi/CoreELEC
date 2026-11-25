# VDIN回采slot与新鲜度白盒审计

日期：2026-11-25；仅离线阅读固定4.9源码与补丁0012/0013/0014/**0018**/0026，**未操作黑屏设备**。目的：审查[A1独立复核](A1-REPEAT-20261125.md)中VDIN包计数/时间戳推进、像素内容却跨slot保持相同的证据边界。固定源码在本地`../coreelec-audit/gen3-research-20261124/linux-amlogic/drivers/amlogic/media/vin/tvin/vdin/`，实际Build291还应用了本仓库补丁。

## 已能从源码追到的关系

1. `vdin_canvas.c`的`vdin_cma_alloc`给自动buffer逐个设置`vfmem_start[i] = mem_start + frame_size*i`（约793行）；`vdin_canvas_auto_config`把第`i`个canvas ID配置到`vfmem_start[i]`（约407–416行）。`vdin_drv.c:460,489–495`使master `vf.index=i`及`vf.canvas0Addr=vdin_canvas_ids[index][i]`（此轮YUV444，单canvas）。这是软件预期的index→canvas ID→物理slot映射。
2. 正常ISR在`vdin_drv.c:2517–2551`把当前写vfe转为`last_wr_vfe`，从writer空闲表取下一个`next_wr_vfe`，将其`canvas0Addr`写到VDIN写控制寄存器，再设为`curr_wr_vfe`。实际写控制由`vdin_ctl.c:2374–2417`的`vdin_set_canvas_id`完成，RDMA或直接写分支均取同一个`canvas_id`。`vdin_vf.c:535–562,597–628`定义writer/ready队列转移；上一写帧经`provider_vf_put`进入`rd_list`，快照从`receiver_vf_get`取ready帧。
3. 补丁`0014-gxlx2-vdin-ready-snapshot.patch`的快照在`receiver_vf_get`后记录`vfe->vf.index`，拒绝当前/上一写slot，调用`e900_vdin_dma_sync_frame(devp,index,true)`，随后从`page_address(venc_pages) + index*frame_size`逐行拷贝；header的`frame_index=index`、`frame_timestamp=vfe->vf.timestamp`、`completion_count=devp->frame_cnt`（约106–166行）。补丁0013的DMA sync又要求`vfmem_start[index]-mem_start == index*frame_size`（约59–91行），使**软件分配地址**与拷贝offset一致；未在每次快照时读回VDIN当前硬件WR_CANVAS或canvas table物理地址。
4. `vdin_drv.c:2462–2467`在ISR处理当前vfe时赋`vf.timestamp=jiffies_64`；补丁0026用它与请求时刻比较以淘汰旧ready项。header的`completion_count`来自`devp->frame_cnt`全局计数，ISR末端在设置next writer后递增（约2551–2557行）。**这不等于没有硬件完成检查：**`vdin_v4l2_isr`在推进当前帧前调用`vdin_write_done_check`（固定源码约2417行）；补丁0018让GXLX2先读`VDIN_COM_STATUS0.DIRECT_DONE`，只有为1才ACK并继续，否则本帧跳过。该硬件完成门槛仍不能单独证明读出的canvas ID对应选中的slot，或该slot像素相对前次有变化。header时间戳/全局计数也不是逐slot内容cookie。本轮before两张同index0但内容不同，after两张同index2且相同；补采两张index3仍与after完全同RGB hash。重复选同slot本身合法，跨slot相同也不能单独归因，需结合电视黑屏和源码边界审计。
5. `e900-loopback.py:46`设置`E900_CAPTURE_NO_GATE=1`和`E900_CAPTURE_SKIP_SYNC=1`。`e900-capture-ready.sh:17–25`仍要求VDIN IRQ增长但不写共享CLKB gate；`:39`的SKIP_SYNC只跳过shell全局`sync`，**不跳过补丁0013/0014中的内核`dma_sync_single_range_for_cpu/device`**。因此不能把本轮静态像素直接归因于SKIP_SYNC漏做DMA缓存同步。

## 仍未证明的链接与最小验证

**实际运行路径已确认：**`e900-start-capture.sh:58`写`v4l2start viuin ...`；固定`vdin_debug.c:~1860,1975`选`TVIN_PORT_VIU1`并调用`start_tvin_service`。补丁0013在该服务中为GXLX2显式`request_irq(..., vdin_v4l2_isr, ...)`（补丁约266–274行），且强制`rdma_enable=0`、清`VDIN_FLAG_RDMA_ENABLE`（约220–224行），所以`vdin_ctl.c:2374–2417`的WR_CANVAS走直接`wr_bits`，不是VDIN RDMA排队。现有dmesg有`vdin1 start_tvin_service flags=0x161806`、4缓冲分配、`format_convert=YUV444`、连续`e900-capture request ... result=0`，与该路径一致；不能把`vdin_isr_simple`或VDIN0的`vdin_isr`当作本轮ISR。

**路由与格式：**补丁0012把GXLX2的VDIN1寄存器offset明确设为`0x80`（约67行），限制输入`TVIN_PORT_VIU1`并选legacy VIU1 WB0（约79行）；VIU frontend对GXLX2屏蔽数值`cpu_after_eq(G12A)`进入的新MUX路径（约190–235行）。同补丁阻断G12 HDR矩阵选择（约99–111行）。固定`vdin_ctl.c:2055–2157`中YUV444写格式为`MIF_FMT_YUV444`，`VDIN_WR_CTRL.WR_FMT`按格式写入；动态`vdin_set_canvas_id`也没有依赖G12数值分支，使用`devp->addr_offset`和同一个canvas ID。源码尚未给本轮实际WR_FMT及WR_CANVAS读回，故这些是**已选软件路径**，不是硬件正确配置的证明。

源码已建立软件分配/队列/拷贝的一致预期，尚无同一异常帧的`curr_wr_vfe.index/canvas0Addr`、`DIRECT_DONE`采样、实际VDIN WR_CANVAS读回、该canvas ID当前硬件Canvas地址、ready vfe.index和payload hash的联合记录。本轮VDIN RDMA已禁，无该路RDMA提交时序；本审计**未发现一个可直接宣称导致黑屏或静态包的确定软件缺陷**。也不能凭电视黑屏断言VDIN tap有bug：tap之后的电视路径仍可能单独异常。

**最小一处候选补丁，先审后实现：**仅在GXLX2/VDIN1诊断模式的`vdin_v4l2_isr`完成门槛附近（`vdin_drv.c`约2417行）关联当前`curr_wr_vfe->vf.index`和`canvas0Addr&0xff`；在补丁0018的`vdin_write_done_check`读取`DIRECT_DONE`且ACK前记录该位，并用现成`vdin_get_canvas_id(devp->addr_offset)`窄读`VDIN_WR_CTRL.WR_CANVAS`。对已完成的当前slot保存有界最近记录（slot索引、软件canvas ID、硬件WR_CANVAS读回、done位、frame_cnt/时间）；快照在`receiver_vf_get`取到该slot时，把该记录与`vf.index`、`vfmem_start[index]`、`index*frame_size`、payload hash一起**每次请求仅输出一行**。不可在每VSync无限printk。已有`canvas_read()`只读软件Canvas shadow；`canvas_read_hw()`会**写Canvas LUT地址选择寄存器**（`canvas.c:186–207`），不能在本轮硬件ISR里随意调用。故硬件Canvas RAM真实物理地址仍是剩余缺口，先不要为它打开任意寄存器接口。审计者应先检查锁/slot代次、防复用、对现有done ACK时序无扰动及输出预算，再批准构建。若WR_CANVAS与预期ID不符，才沿此差异定位；若相符，静态像素仍可能来自VDIN输入或更下游，需要新分层证据。
