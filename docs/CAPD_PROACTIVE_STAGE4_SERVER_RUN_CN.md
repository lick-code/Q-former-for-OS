# CAPD 主动降级阶段 4：Linux 服务器运行说明

## 1. 前提

服务器仓库根目录应包含 PyTorch 环境以及阶段 3 使用的六个 Train/Validation
原始 CSV。不得向本流程提供 Test 文件。

先进入仓库：

```bash
cd /home/likc/Q-former-for-OS
git status --short
python3 -c 'import sys,torch; print(sys.version); print(torch.__version__); print(torch.cuda.is_available())'
```

推荐先提交或保存当前 diff，再从同一代码状态运行。dirty worktree 不会被伪装成
clean；其状态指纹会写入 provenance。

## 2. 选择非重叠证明方式

当前 `finals_v3_official` 的 Train/Validation 不是六次独立采集，而是每个
workload 从同一次真实 RW 采集中按不重叠半开区间切分。来源身份和区间记录在
`dataset/metadata/finals_v3_source_specs/*.json`，Stage 4 已将对应 Train/Validation
区间固化到：

```bash
export CAPD_STAGE4_SOURCE_RANGES_JSON="$PWD/configs/finals/capd_proactive_stage4_source_ranges.json"
```

不得对当前 official 数据设置
`CAPD_STAGE4_ATTEST_DISTINCT_SOURCE_TRACES=1`。若以后改用新的输入数据，才应根据
新数据的真实来源重新生成区间 JSON；其结构为：

```json
{
  "canneal": {
    "train": {"source_trace_id": "canneal-source", "start": 0, "end": 3000000},
    "validation": {"source_trace_id": "canneal-source", "start": 3000000, "end": 5000000}
  }
}
```

然后：

```bash
export CAPD_STAGE4_SOURCE_RANGES_JSON=/absolute/path/stage4_source_ranges.json
```

脚本会核对 `end-start` 与实际 CSV 访问数，并拒绝重叠。

## 3. 一条命令完成环境检查、审计、测试、训练、续跑和验收

使用现有阶段 3 Train/Validation manifest 作为路径来源：

```bash
bash scripts/validate_capd_proactive_stage4_server.sh \
  stage4-real-001 \
  outputs/capd_proactive_calibration/stage3/stage3-real-001/input_manifest.json \
  cuda
```

如果只用 CPU：

```bash
bash scripts/validate_capd_proactive_stage4_server.sh \
  stage4-real-001 \
  outputs/capd_proactive_calibration/stage3/stage3-real-001/input_manifest.json \
  cpu
```

脚本依次执行：

1. Python/PyTorch/CUDA 环境检查；
2. 生成带真实 SHA-256、访问数和非重叠证据的 Stage4 manifest；
3. 阶段 0～3 继承审计和 Test 硬拒绝预检；
4. Python 语法编译；
5. 阶段 1～4 单元、合成 E2E 和回归测试；
6. 4-B Lookahead；
7. 4-C 标签权重；
8. 4-D K/H；
9. 4-E 最终数据重建和三个 seed 训练；
10. 测试回执、工件 SHA-256 和污染审计；
11. 仅在全部通过后输出 `[FINAL] STAGE4_VERIFIED`。

训练中断后用完全相同的 RUN_ID 重跑同一命令。合同一致时会复用完整工件，并从
`qmap_last.pth` 继续未完成训练；合同或指纹不一致会停止，不覆盖旧结果。

## 4. 分步运行与定位

需要逐阶段观察时：

```bash
python3 scripts/prepare_capd_proactive_stage4_manifest.py \
  --source-manifest outputs/capd_proactive_calibration/stage3/stage3-real-001/input_manifest.json \
  --output outputs/capd_proactive_stage4/manifests/stage4-real-001.json \
  --project-root "$PWD" \
  --attest-distinct-source-traces

COMMON=(
  --manifest outputs/capd_proactive_stage4/manifests/stage4-real-001.json
  --run-id stage4-real-001
  --project-root "$PWD"
  --device cuda
)

python3 scripts/run_capd_proactive_stage4.py preflight "${COMMON[@]}"
python3 scripts/run_capd_proactive_stage4.py lookahead "${COMMON[@]}"
python3 scripts/run_capd_proactive_stage4.py label-weights "${COMMON[@]}"
python3 scripts/run_capd_proactive_stage4.py candidate-history "${COMMON[@]}"
python3 scripts/run_capd_proactive_stage4.py finalize "${COMMON[@]}"
```

这组分步命令不会验证服务器测试回执，因此不会打印最终 VERIFIED。正式验收仍应运行
完整验收脚本，或在测试通过后执行 `record-tests` 与 `verify`。

## 5. 运行期间查看进度

```bash
tail -f outputs/capd_proactive_stage4/stage4-real-001/logs/progress.jsonl
```

查看状态：

```bash
cat outputs/capd_proactive_stage4/stage4-real-001/run_state.json
```

查看三阶段选择：

```bash
for f in outputs/capd_proactive_stage4/stage4-real-001/selections/*.json; do
  echo "===== $f"
  python3 -m json.tool "$f" | sed -n '1,120p'
done
```

## 6. 请回传

服务器命令结束后，请把以下内容同步回本地：

```bash
tar -czf stage4-real-001-results.tar.gz \
  outputs/capd_proactive_stage4/stage4-real-001 \
  outputs/capd_proactive_stage4/manifests/stage4-real-001.json

sha256sum stage4-real-001-results.tar.gz
```

同时回传终端最后约 100 行：

```bash
tail -n 100 outputs/capd_proactive_stage4/stage4-real-001/logs/progress.jsonl
cat outputs/capd_proactive_stage4/stage4-real-001/run_state.json
cat outputs/capd_proactive_stage4/stage4-real-001/verification.json
```

如果失败，不要删除运行目录；请回传报错、`run_state.json`、对应训练日志和
`progress.jsonl`，以便沿同一 RUN_ID 安全续跑。
