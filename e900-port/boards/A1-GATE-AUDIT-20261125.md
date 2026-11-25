# A1 离线证据检查器审计

日期：2026-11-25；审计者：astra。对应[完整执行计划](EXPERIMENT-EXECUTION-PLAN-20261125.md)。**本页没有新增实机结果。**

sol因额度中断留下检查器草稿，astra修正后完成离线验证。参数化执行脚本由sol另行准备，不能把检查器完成等同A1已就绪或已执行。

## 修正及验证

- 恢复global的首个phase0中enabled仍可为0，随后才变1；原草稿把这个正常时序误判为失败，现按单调0→1恢复检查。
- boot必须与本轮manifest核对；缺manifest为UNKNOWN，不能默认通过。
- 重新解析原始寄存器页、扩展页和提交页，与导出的行/批次逐项核对，拒绝仅修改摘要或缺行。
- 同时要求mode2有效、guard=0、完整1→0→1窗口、实际混合位始终保持、PPS/CSC计数及实际表存在、提交无溢出并覆盖恢复后16个VSync。
- 图像需检查完成计数/时间戳、前帧彩条及移动标记。提供原包目录时，重新解包、解色并逐项核对元数据/hash/PNG，不能用旧PNG冒充当前结果。
- 环境及清理仍需审计manifest、原始日志。检查器永远不会自动授予VALID；最终按计划给VALID/PARTIAL/INVALID及下一分支。

负对照使用真实历史默认0.2秒脉冲：boot `b8356d5d-a96f-405e-ad16-74121e661f92`，66条寄存器、1472条提交。结果保存在[负对照报告](evidence/build291-a1-gate-negative-control.json)：实际hold检查FAIL（第10–37行确实关闭），after双帧检查FAIL（仅一张）；原始页、提交覆盖及现有三张原包/PNG均PASS。它证明检查器能识别不合格数据，**不是hold3实机结论**。

主机检查通过：`check-a1-evidence-gate.py`、`check-register-transition-client.py`。包含错boot、原始页/摘要不一致、缺行、溢出、覆盖不足、陈旧图像、缺元数据的拒绝案例；未进行ARM构建或新设备操作。

## sol调用方式

从repo根目录运行，参数指向复制到主机的同一run：

```sh
python3 e900-port/scripts/check-a1-transition.py "$RUN/transition.json" \
  --manifest "$RUN/manifest.json" --image-dir "$RUN/transition-images" \
  --out "$RUN/verdict.json"
```

退出码1表示未通过**完整A1证据门槛**，2表示等待人工审计；没有自动通过的0。非零不能阻止归档/收尾，不删除部分有效证据。单张新鲜黑帧等部分证据是否允许因果分支，由astra按计划单独判断。

局限：逐VSync采样不能排除采样间瞬变；软件表/完成中断不能证明每条硬件写入；检查器不替代实际PNG审阅、环境审计或用户电视反馈。
