# Claude 2026-11-26历史判断（已被审查纠正）

以下保留历史原文，不作为已证实根因或当前执行指令。详见CLAUDE-PATCH-REVIEW-20261127.md。

**最新进展** (2026-11-26)：✅ **根因已定位，修复补丁已创建**

VPP 寄存器差分测试与 HDR2 写回验证完成（boot `d49e20f2`），根因确认：
1. **前轮 HDR2 结论更正**：前轮在菜单状态误读 0x3800=0x0001c040 为"正常态"，实际播放中为 0x0000d05f（激活）
2. **差分结果**：7 个寄存器变化，HDR2_CTRL 从激活变 bypass，0x1d25/1d28 (VPP 管线) 归零
3. **写回测试失败**：手动恢复 HDR2_CTRL 正确值后画面依然黑屏，vpp_fifo 仍为 0
4. **新证据链**：解码器正常 → MIF canvas 更新 → VPP_MISC 混合位正确 → **但 VPP FIFO=0 无输出**
5. **根因确认**：HDR2 配置未恢复只是副作用；**真正根因是 VPP 处理单元停止且未收到重启触发**

**修复方案**（详见 [BLACK-SCREEN-FIX-PLAN.md](BLACK-SCREEN-FIX-PLAN.md)）：
- 补丁 1 (linux-20): 强制 HDR2 在 global_output 恢复时重新配置，绕过 signal_change_flag 门控
  - ✅ 已验证：amcsc.c line 8133，检测 VD1_HDR2_CTRL bypass bit，强制 SIG_FORCE_CHG
- 补丁 2 (linux-21): **核心修复** - 在 global_output 恢复时显式重启 VPP 处理单元
  - ✅ 已验证：video_hw.c vpp_blend_update()，VIDEO_ENABLE_STATE_ON_PENDING 分支重置 new_vframe_count
- 补丁 3 (linux-22): 增强 Stop 流程状态清理，确保下次播放完整初始化
  - ✅ 已验证：video_hw.c disable_vd1_blend()，添加状态清理文档和调试日志

补丁位置：`projects/Amlogic-ce/devices/Amlogic-ng/patches/linux/`

**补丁验证** (commit f60c09be64)：
- 基于实际内核源码（linux-amlogic@50c8e8154c5a）验证并修正
- 所有补丁通过 `patch --dry-run` 测试，能够正确应用
- 内核源码位置：/Volumes/linux-amlogic/linux-amlogic

**下一项**：用户构建测试。GitHub Actions 正在编译（已运行约 15-30 分钟）。构建完成后部署到设备验证黑屏修复效果。

