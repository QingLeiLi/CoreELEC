> 2026-11-27审查更正：本文件的“根因已定位”、bit12 bypass判断及计数赋1重启VPP主张不成立；以下仅保留历史方案。当前实施入口见VD1-VPP-CONVERGENCE.md，依据见CLAUDE-PATCH-REVIEW-20261127.md。

# E900 黑屏问题修复方案

**日期**: 2026-11-26  
**状态**: 准备中，等待 media_modules-aml 源码  
**根因定位**: 完成（见 VD1-VPP-CONVERGENCE.md L15-L19）

## 问题总结

### 故障现象
- 新启动首播正常
- `global_output` 关闭/恢复后黑屏
- Stop 后 replay 黑屏
- 仅冷启动能完全恢复

### 根因机制

通过 VPP 寄存器差分测试（boot `d49e20f2`）和 HDR2 写回验证确认：

1. **触发路径**：
   - `global_output=0` 脉冲触发 `disable_vd1_blend()`
   - VPP 处理单元停止（0x1d25: 0x01df01b8 → 0x00000000）
   - HDR2_CTRL 设为 bypass 模式（0x3800: 0x0000d05f → 0x0001c040）

2. **恢复失败原因**：
   - **主因**：VPP 处理单元未收到显式重启触发
   - **副作用**：HDR2 重配置被 `signal_change_flag` 门控跳过
   - **遗留问题**：Stop 流程未清理初始化标志

3. **验证证据**：
   - 手动写回 HDR2_CTRL = 0x0000d05f 成功，但画面仍黑屏
   - vpp_fifo_status 仍为 0（VPP 无输出）
   - 解码器正常、MIF canvas 更新、VPP_MISC 混合位正确
   - **结论**：HDR2 配置未恢复不是黑屏的充分根因，只是副作用

## 修复策略

需要创建 3 个补丁，放置在 `projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/patches/`：

### 补丁 1: 004-force-hdr2-reconfig-on-global-output-recovery.patch

**目标文件**: `drivers/amvecm/amcsc.c`（或类似路径）  
**目标行数**: ~8133

**问题**：
```c
// signal_change_flag 门控在参数看似不变时跳过 HDR2 重配置
if (signal_change_flag) {
    // 跳过重配置
    return;
}
```

**修复**：
- 检测 `global_output` 从 0→1 的转换
- 在此转换时强制清零 `signal_change_flag` 或设置 `force_reconfig` 标志
- 确保 HDR2 完整重新配置，即使软件认为参数未变

**预期效果**：
- HDR2_CTRL 在恢复时被正确重写为 0x0000d05f
- 但这本身不足以修复黑屏（需要配合补丁 2）

### 补丁 2: 005-restart-vpp-on-global-output-recovery.patch

**目标文件**: `drivers/video_sink/video_hw.c` 和/或 `drivers/video_sink/video.c`  
**目标函数**: 
- `video_set_global_output()` (line 7921-7936 in video.c)
- `disable_vd1_blend()` 的恢复对应路径 (line 3252-3308 in video_hw.c)

**问题**：
- `disable_vd1_blend()` 停止 VPP 处理单元
- 恢复时 (`global_output=1`) 未显式重启 VPP
- 寄存器 0x1d25 保持为 0，VPP_FIFO_STATUS 保持为 0

**修复**：
- 在 `global_output` 从 0→1 转换时，显式触发 VPP 处理单元重启
- 可能需要：
  - 重置 VPP scaler 状态机
  - 触发 VPP "go" 信号
  - 确保 `new_vframe_count` 不为 0 或重置 VPP 同步
  - 重新初始化 VPP 与 ENCP 的握手信号

**预期效果**：
- 0x1d25 从 0 恢复到类似 0x01df01b8 的激活值
- vpp_fifo_status 恢复非零值
- VPP 管线重新开始输出像素

**关键**：这是修复黑屏的核心补丁

### 补丁 3: 006-enhance-stop-state-cleanup.patch

**目标文件**: `drivers/video_sink/video_hw.c`  
**目标函数**: Stop 流程相关函数

**问题**：
- Stop 流程后 `signal_change_flag` 等状态标志未清理
- 下次播放时跳过必要的初始化
- 热重启可能保留部分硬件状态

**修复**：
- 在 Stop 流程中清理所有初始化标志：
  - 清零 `signal_change_flag`
  - 重置 HDR/CSC 相关状态变量
  - 确保下次播放执行完整初始化序列

**预期效果**：
- Stop 后 replay 能正常工作
- 避免残留状态影响下次播放

## 实施步骤

1. **获取源码**：✅ 进行中
   - 克隆 `https://github.com/CoreELEC/media_modules-aml.git`
   - 切换到 commit `60561618f2bf154c1438d3c790b625ff01f215c3`
   - 保存到 `/Users/lql/Downloads/IPTV/CoreELEC-E900V21C/media_modules-aml/`

2. **定位代码**：待完成
   - 找到 `drivers/amvecm/amcsc.c` 中的 `signal_change_flag` 门控
   - 找到 `drivers/video_sink/video_hw.c` 中的 VPP 控制逻辑
   - 找到 `drivers/video_sink/video.c` 中的 `global_output` 处理
   - 确认精确的行号和上下文

3. **创建补丁**：待完成
   - 生成 unified diff 格式补丁
   - 命名为 004-*.patch, 005-*.patch, 006-*.patch
   - 保存到 `projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/patches/`

4. **文档更新**：待完成
   - 更新 VD1-VPP-CONVERGENCE.md
   - 记录补丁详情和预期效果
   - 更新台账

5. **构建测试**：用户执行
   - CoreELEC 构建系统会下载 media_modules-aml 源码
   - 自动应用 patches/ 目录中的所有补丁
   - 编译生成新的 .ko 模块
   - 用户部署到设备测试

## 验收标准

按 AGENTS.md 要求：

1. **所有诊断开关关闭**：
   - 不使用任何隔离开关
   - 不使用 hold=3 或其他实验参数
   - 使用默认配置

2. **全场景测试**：
   - ✅ 正常首播（视频和菜单）
   - ✅ global_output 关闭/恢复（1秒脉冲）
   - ✅ Stop 后 replay
   - ✅ 多次重复通过

3. **用户确认**：
   - 物理电视画面正常
   - 视频播放流畅
   - Kodi 菜单正常显示
   - 无副作用

## 风险评估

### 低风险
- 补丁 1（HDR2 强制重配）：在已有重配置路径中强制执行，不引入新逻辑
- 补丁 3（Stop 清理）：只是增强清理，不改变主流程

### 中等风险
- 补丁 2（VPP 重启）：需要触发硬件重启，必须找到正确的重启序列
- 如果重启序列不正确，可能导致：
  - VPP 仍然无输出
  - 或引入新的时序问题

### 缓解措施
- 仔细研究现有的 VPP 初始化代码
- 复用已有的安全重启路径
- 在恢复时执行与首次播放相同的 VPP 启动序列
- 保持最小化改动原则

## 参考文档

- [VD1-VPP-CONVERGENCE.md](VD1-VPP-CONVERGENCE.md) - 主台账
- [VPP 差分测试记录](../trial-build291/experiments/VPP-REGDIFF-20261126/EXPERIMENT-RECORD.md)
- [差分测试结果](../trial-build291/vpp-regdiff-result.json)
- [Build291 验证结果](BUILD290-VALIDATION.md)

## 下一步

等待 media_modules-aml 源码克隆完成，然后：
1. 定位精确代码位置
2. 创建 3 个补丁文件
3. 提交到 git（hotfix/cllaude 分支）
4. 更新台账
5. 通知用户准备构建测试
