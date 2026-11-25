# VDIN回采slot与新鲜度白盒审计

日期：2026-11-25；仅离线阅读固定4.9源码与补丁0012/0013/0014/0026，**未操作黑屏设备**。目的：审查[A1独立复核](A1-REPEAT-20261125.md)中VDIN包计数/时间戳推进、像素内容却跨slot保持相同的证据边界。固定源码在本地`../coreelec-audit/gen3-research-20261124/linux-amlogic/drivers/amlogic/media/vin/tvin/vdin/`，实际Build291还应用了本仓库补丁。

## 已能从源码追到的关系

1. `vdin_canvas.c`的`vdin_cma_alloc`给自动buffer逐个设置`vfmem_start[i] = mem_start + frame_size*i`（约793行）；`vdin_canvas_auto_config`把第`i`个canvas ID配置到`vfmem_start[i]`（约407–416行）。`vdin_drv.c:460,489–495`使master `vf.index=i`及`vf.canvas0Addr=vdin_canvas_ids[index][i]`（此轮YUV444，单canvas）。这是软件预期的index→canvas ID→物理slot映射。
2. 正常ISR在`vdin_drv.c:2517–2551`把当前写vfe转为`last_wr_vfe`，从writer空闲表取下一个`next_wr_vfe`，将其`canvas0Addr`写到VDIN写控制寄存器，再设为`curr_wr_vfe`。实际写控制由`vdin_ctl.c:2374–2417`的`vdin_set_canvas_id`完成，RDMA或直接写分支均取同一个`canvas_id`。`vdin_vf.c:535–562,597–628`定义writer/ready队列转移；上一写帧经`provider_vf_put`进入`rd_list`，快照从`receiver_vf_get`取ready帧。
3. 补丁`0014-gxlx2-vdin-ready-snapshot.patch`的快照在`receiver_vf_get`后记录`vfe->vf.index`，拒绝当前/上一写slot，调用`e900_vdin_dma_sync_frame(devp,index,true)`，随后从`page_address(venc_pages) + index*frame_size`逐行拷贝；header的`frame_index=index`、`frame_timestamp=vfe->vf.timestamp`、`completion_count=devp->frame_cnt`（约106–166行）。补丁0013的DMA sync又要求`vfmem_start[index]-mem_start == index*frame_size`（约59–91行），使**软件分配地址**与拷贝offset一致；未在每次快照时读回VDIN当前硬件WR_CANVAS或canvas table物理地址。
4. `vdin_drv.c:2462–2467`在ISR处理当前vfe时赋`vf.timestamp=jiffies_64`；补丁0026用它与请求时刻比较以淘汰旧ready项。header的`completion_count`来自`devp->frame_cnt`全局计数，ISR末端在设置next writer后递增（约2551–2557行）。它们证明软件ISR/队列进展，**不是该slot本次DMA像素已被重写的硬件完成cookie**。本轮before两张同index0但内容不同，after两张同index2且相同；补采两张index3仍与after完全同RGB hash。重复选同slot本身合法，跨slot相同也不能单独归因，需结合电视黑屏和源码边界审计。
5. `e900-loopback.py:46`设置`E900_CAPTURE_NO_GATE=1`和`E900_CAPTURE_SKIP_SYNC=1`。`e900-capture-ready.sh:17–25`仍要求VDIN IRQ增长但不写共享CLKB gate；`:39`的SKIP_SYNC只跳过shell全局`sync`，**不跳过补丁0013/0014中的内核`dma_sync_single_range_for_cpu/device`**。因此不能把本轮静态像素直接归因于SKIP_SYNC漏做DMA缓存同步。

## 仍未证明的链接与最小验证

源码已建立软件分配/队列/拷贝的一致预期，尚无同一异常帧的`next_wr_vfe.index/canvas0Addr`、实际VDIN WR_CANVAS读回、该canvas ID当前物理地址、ready vfe.index和payload hash的联合记录。RDMA写入可能存在提交时序；本审计**未发现一个可直接宣称导致黑屏或静态包的确定软件缺陷**。也不能凭电视黑屏断言VDIN tap有bug：tap之后的电视路径仍可能单独异常。

若后续需要新观测，先设计**只针对VDIN1、同一frame代次的有界只读日志**：记录ISR拟写`index/canvas ID`及实际提交/读回、ready队列`index/timestamp`、snapshot选中`index/slot物理起点`与payload hash；明确何时允许安全读回，不用任意地址接口或整机扫描。先由astra审源码覆盖与无扰动性，再构建；本轮不执行。若实际WR_CANVAS/物理地址与软件index不符，再沿那一条差异定位；若完全一致，静态像素仍可能来自VDIN输入或更下游，需要新的分层证据。
