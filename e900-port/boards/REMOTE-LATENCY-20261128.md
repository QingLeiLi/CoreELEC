# 遥控慢半拍：阶段记录

2026-11-28，用户随后决定“先不管这个了，可能是红外遥控器的正常延迟”，当前停止排查，不再调整遥控/皮肤。

现机旧293H、boot91eb4cd5；meson-ir→eventlircd→Kodi。5次轻按Down都只到达一次，没有LIRC连发。基准采样CPU约96%空闲、可用内存725MiB，不能据此排除瞬时界面阻塞。内核repeat delay500ms/period125ms原样保留，不能把长按等待等同于首次轻按延迟。

第二轮同时记录LIRC接收时间和Kodi HandleKey：转发端到Kodi执行Down分别14.32、4.50、2.76、26.57、34.40ms。这一段未观察到半秒排队；IR解码前及真正上屏延迟未量化。原始数据在[evidence](evidence/remote-latency-20261128/)。

内核曾以独立ftrace instance采input_event；trace_clock为local，与Python monotonic有约50ms偏移，不能直接相减。校时归档步骤覆盖了完整kernel trace，只剩校时数据；因此本轮不使用它给出内核→转发端的精确时延。LIRC及Kodi原始5对记录完整且不受影响。

用户感觉开启Kodi调试文字时更快。于是只测试用户advancedsettings `gui/algorithmdirtyregions=0`（官方定义为每次绘制整个viewport），重启Kodi，debug.showloginfo=false。GUI报告约60.52FPS，用户反馈“感觉没变化”，故该项未通过，不认定dirty-region为根因。重启本身也改变初态，没有做AB/BA重复对照。

恢复：用户原先没有advancedsettings.xml；确认测试文件内容未被修改后删除该文件并重启Kodi。调试文字关闭、ftrace instance tracing_on=0/current_tracer=nop，未改repeat、皮肤、内核或显示寄存器。当前保留原刷新策略。单次Home默认scrolltime500ms在源码可见，但Control.HasFocus(9000)=false，未证明它解释当前焦点的延迟，也未修改。

参考：[Kodi官方dirty-region说明](https://kodi.wiki/view/HOW-TO:Modify_dirty_regions)。原始采集文件仍在盒子 `/storage/e900-remote-latency`；临时采集脚本未作为产品启动服务。
