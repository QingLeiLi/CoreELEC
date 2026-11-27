# 连续采集修复二次审查

审查基线：`1ec2c80db9`。本轮只读本地源码、运行主机测试并修订用户态工具；没有连接或操作盒子，0043内核补丁没有新增修改。

## 已发现并修复

1. **P1：把配置成功误作观测完整。** 原display_coverage无条件要求HDR request/submitted、PPS正常exit，出现unsupported/null-input或CSC无变化返回时永久判缺覆盖。这些返回已被0042记录，不能一律当作缺日志，也不能说明硬件配置成功。现在按明确返回原因记录disposition；PPS unsupported对应其外层调用终点；DCU/PPS调用仍需配对，实际VD1 HDR请求仍必须有对应提交。未知原因、悬空请求或缺事件仍不完整。反例测试覆盖正常CSC no-change、PPS unsupported、错误会话及未返回调用。
2. **P1：跨阶段关联不足。** 同boot、每份原页合法，不代表来自同一次实验。旧测试甚至把三个阶段都设成generation1、stamp从100重新开始，比较器仍接受。现在要求连续generation、窗口kernel stamp有序、result与冻结state一致、工具hash一致；正常参考的活动读回属于首播会话，重播进入新provider会话。新增同boot时间倒序、混工具版本、错误参考session的拒绝测试。正常参考对重播的读回另行比较，不只比较两个启动瞬间。
3. **P2：preflight未排除实验/日志残留。** 原来只查hold/HDR/RDMA/stage预算，G12-MIF、GEN3 clear-high、OSD隔离或其它verbose预算仍可启用。现在只读检查并保存上述开关，拒绝未退出的pixel/edge探针和活动verbose通道；不代用户写入清理。比较阶段要求所检查策略相同，避免把不同条件拼起来。

## 保留的边界

- 连续性指同一generation的append-only记录，没有人为freeze/re-arm空隙；不证明所有硬件写者都被hook。
- Stop的No vdec、disable请求/状态和300ms稳定期不是所有延迟工作完成证明；后续与重播仍在同一记录中。
- 新的首帧note仅证明软件session中的首次非fake toggle，不证明像素已到HDMI。不同CPU ID、显示寄存器策略不在本轮调整范围。
- 65536条仍可能溢出，实时读取也会增加CPU开销；遇到溢出/超时保存失败证据并停止，不能拼接重试冒充完整。
- 显式no-op也可能正是故障线索。工具只承认其被观察到，不认定跳过正确，不把“覆盖完成”写成“硬件正常”。

## 验证与待办

`check-playback-session.py`覆盖真实Build292过早冻结反例、已知跳过、请求/返回配对、实时前缀、错误会话、同boot错序/混工具、Stop超时不重播及实验残留；`check-playback-audit.py`和产物导出检查保持通过。

完整ARM构建、新hook可达性、实际记录速率及电视画面仍待实测。下一次构建使用包含本修订的提交；参数仍为decoder/image。没有因本审查增加第二次内核修改或宣称黑屏修复。
