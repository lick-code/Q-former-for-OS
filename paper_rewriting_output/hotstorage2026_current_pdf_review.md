# HotStorage 2026 Simulated Review: CAPD

Reviewed file: `HotStorage_2022_Concise_Paper_Template__李康诚_.pdf`

Local evidence checked:

- `current_pdf_extract_for_review.txt`
- `outputs/results/real_workload_suite/1m/summary.md`
- `outputs/results/real_workload_suite_pressure/selected/summary.md`
- `outputs/results/seed_stability/summary.md`
- `outputs/results/capacity_sensitivity/summary.md`
- `outputs/results/candidate_sensitivity/summary.md`
- `outputs/results/real_ablation/summary.md`
- `outputs/results/ml_baselines/summary.md`
- `outputs/results/cost_weight_sensitivity/summary.md`

## Simulated Decision

**Decision: Borderline / Weak Reject, with a clear path to Borderline Accept if revised.**

The work is a plausible HotStorage-style paper because it targets tiered memory, caching/tiering, and applying ML to storage-system policy decisions. The paper has an early working prototype, trace-driven evidence, and a result that is interesting under pressure: CAPD reduces weighted replay cost by **10.83%** on the `streamcluster-pressure` window. That is enough to be discussable at HotStorage.

The current submission is still easy to reject because the main claim is broader than the evidence. The positive result is concentrated in one pressure regime; `dedup-pressure` is a tie; `blackscholes` is a near-tie with a tiny active page set; and `canneal` is a stable failure in the local artifacts but is only mentioned briefly in the conclusion. The paper also claims lightweight cost-aware demotion, but the current prototype has millisecond-level decision time and the ablation evidence does not clearly support the value of the read/write and cost terms.

## What Works

1. **Venue fit is real.** CAPD sits at the intersection of memory-centric storage systems, caching/tiering, and ML for storage-system policy decisions. That is directly in HotStorage's topic area.

2. **The core framing is understandable.** Treating DRAM demotion as a candidate ranking problem is a clean formulation. It is easier to evaluate and discuss than a broad "learned memory manager" claim.

3. **The best result is meaningful.** On `streamcluster-pressure`, CAPD improves weighted cost from CLOCK's `301,767` to `269,095`, improves hit rate from `95.52%` to `97.00%`, and reduces migrations from `8,937` to `5,981`. This is the strongest systems result in the paper.

4. **The latest PDF is more honest than the earlier framing.** The abstract and discussion now say "under DRAM capacity pressure" and "workload-dependent boundary cases." That is the right direction.

5. **The experiment repository contains more evidence than the paper currently shows.** Seed stability, capacity sensitivity, candidate-count sensitivity, and cost-weight sensitivity exist. The paper should use this to look more rigorous.

## Major Concerns

### 1. The paper hides the most important negative result

The PDF only reports `blackscholes`, `streamcluster-pressure`, and `dedup-pressure` in Table 1. It mentions `canneal` only in the conclusion as a boundary case. But the local artifacts show `canneal` is not a minor edge case:

- Seed stability: CAPD is worse than LRU on all three seeds, with mean delta **+16.81%**.
- Capacity sensitivity: `canneal` is **+85.03%** at 8 pages and **+19.09%** at 16 pages.
- Candidate sensitivity: `canneal` is worse at all candidate counts, from **+6.87%** to **+134.56%**.

A reviewer will ask whether the main table was selected to avoid showing failure. For HotStorage, the failure is actually valuable if framed correctly.

**Fix:** Add `canneal` to the main result table or add a compact "failure boundary" table. Make the paper's claim: CAPD helps when pressure exposes learnable victim quality, but can be unsafe when candidate sets contain near-future-reuse pages. That is a better workshop contribution than a too-clean win.

### 2. Pressure-window selection looks under-specified

The strongest result comes from `streamcluster-pressure`, while the standard `parsec_streamcluster` test split has no meaningful replacement decisions and all policies tie at `100,033`. The paper says "pressure window" but does not explain enough:

- how many windows were scanned;
- whether the selected window was chosen by replacement pressure only or by CAPD performance;
- whether other high-pressure windows show the same trend;
- whether the same selection rule was applied to all workloads.

This is the most likely cherry-picking objection.

**Fix:** Add one small table: top 5 windows ranked by LRU decision count, with LRU/CLOCK/CAPD deltas for all five. If space is tight, put one row in main text and the full table in appendix. The key sentence should be: "Windows were selected before CAPD evaluation using only baseline replacement pressure, not CAPD performance."

### 3. "Cost-aware" is not yet proven by the ablation

The method emphasizes read/write flags, write sensitivity, and demotion cost. But `outputs/results/real_ablation/summary.md` shows:

- On `streamcluster-pressure`, `no_rw` is slightly better than CAPD: `267,644` vs `269,095`.
- `no_cost` is essentially tied: `269,174` vs `269,095`.
- On `blackscholes`, `no_rw` and `no_cost` are both better than the reported CAPD variant in that ablation run.

This does not kill the paper, but it weakens the specific mechanism claim. The evidence currently supports "context-aware ranking can help in one pressure regime" more than "read/write and demotion-cost terms are essential."

**Fix:** Either add a carefully explained ablation table and interpret it honestly, or soften the claim. Do not say the cost-aware label is the reason for the win unless the ablation supports it.

### 4. "Lightweight" is not credible as written

The PDF says inference is only invoked at demotion events and keeps the path short. That is qualitatively true, but the measured decision times in the artifacts are large:

- `streamcluster-pressure`: CAPD about **2.35 ms/decision**.
- `blackscholes`: about **3.46 ms/decision**.
- `dedup-pressure`: about **9.03 ms/decision**.
- Baselines are microseconds or below.

For a storage/memory systems reviewer, "off the regular access path" is not the same as "lightweight."

**Fix:** Replace "lightweight" with "off-access-path prototype" unless you add an optimized inference estimate. A credible fix would report batched inference, TorchScript/ONNX/C++ inference, or amortized overhead per million accesses and per migration.

### 5. The learned baselines are weakly positioned

The paper compares against `Kleio-lite` and `PatternS-lite`, but says they are not full reproductions. That is honest, but reviewers may see them as straw baselines.

**Fix:** Do not make the learned-baseline gap central. The central comparison should be against classical demotion policies plus a clear explanation of why full learned-cache systems are not directly comparable to DRAM-NVM demotion. If possible, add one stronger adaptive baseline: LeCaR-style mixture, SIEVE-like simple eviction, or a page-hotness predictor without candidate cross-attention.

### 6. The evaluation metric needs stronger justification

The weighted cost metric is:

`hits + 2 * nvm_reads + 8 * nvm_writes + 10 * migrations`

This is plausible, but the paper needs to explain why these weights are reasonable for DRAM-NVM/CXL/NVM tiering. The cost-weight sensitivity is only summarized for `streamcluster-pressure`; meanwhile local artifacts show other workloads remain negative or unstable under alternate weights.

**Fix:** State that the absolute weights are illustrative, not measured device costs. Show that the main `streamcluster-pressure` conclusion holds under multiple cost settings, and separately admit that `blackscholes` and `canneal` do not.

### 7. The paper needs a compact related-work section

The PDF has references but no real related-work positioning section. For HotStorage, this can be short, but it must sharpen the gap:

- tiered memory page placement/migration systems such as TPP, HeMem, Memtis, Nimble;
- learned or adaptive cache replacement such as LeCaR and deep-learning cache replacement;
- production/simple cache-policy work such as CacheLib, SIEVE, and recent HotStorage cache-policy papers.

The key distinction should be: CAPD is not a general cache replacement paper; it studies cost-aware victim ranking for DRAM demotion under asymmetric slow-tier write/migration cost.

## Section-Level Notes

### Abstract

Good: the abstract now says "under DRAM capacity pressure" and gives the strongest result.

Problem: it still sounds like CAPD generally "reduces weighted replay cost on real traces." Since the main evidence is narrow, revise to: "CAPD reduces cost on a high-pressure streamcluster window, ties on dedup, and exposes failure modes on canneal."

### Introduction

The first page is solid but generic. It spends too much time restating DRAM/NVM asymmetry and not enough on the controversy: learned eviction can help, but can also over-evict and amplify migrations.

Recommended first-page thesis:

> Learned demotion is useful only when replacement pressure exposes learnable victim quality; otherwise it can match simple policies or become actively unsafe.

### Design

The equations are technically coherent but too much of the 5-page budget is spent on standard Transformer machinery. HotStorage reviewers care more about:

- when the model runs;
- what metadata it needs;
- whether it leaks future information at test time;
- how the offline labels are built;
- how the candidate set is generated;
- what overhead the system pays.

Cut formulas for embedding/positional encoding if space is needed. Keep the ranking objective and a concise algorithm.

### Evaluation

The evaluation is the decisive section. It needs to answer three questions:

1. Where does CAPD help?
2. Where does it not help?
3. Why?

The current PDF answers 1 reasonably, answers 2 only partially, and barely answers 3. Add canneal failure analysis and pressure-window selection details.

### Discussion

This is currently too short and too positive. It should explicitly discuss:

- per-workload training and generalization limits;
- page-ID and PC embedding memorization risk;
- runtime overhead;
- unsafe candidate expansion on canneal;
- pressure-window selection.

## Missing Experiments, Ranked by Value

1. **Top-k pressure-window table.** Highest value. Defuses cherry-picking.
2. **Canneal failure table.** Show migrations, near-future reuse of evicted pages, and candidate-count sensitivity.
3. **No page-ID embedding ablation.** This addresses memorization.
4. **No PC / no RW / no cost ablation on the final exact run.** Current ablation evidence is not aligned with the claim.
5. **Optimized inference estimate.** Needed if keeping "lightweight."
6. **Cross-window train/test.** Train on one earlier pressure window, test on later pressure windows.
7. **One storage-like workload.** PARSEC is acceptable for memory traces, but HotStorage readers would trust a RocksDB/YCSB/Redis/in-memory KV or graph workload more.

## Fastest Revision Plan

If the deadline is close, do not add a new system. Do these instead:

1. Reframe the paper as "when learned page demotion helps and fails."
2. Put canneal back into the main story.
3. Add the pressure-window selection methodology and top-k table.
4. Change "lightweight" to "off-access-path prototype" unless optimized timing is added.
5. Add one paragraph of related work positioning against tiered memory and cache-replacement systems.
6. Make all result artifacts use one consistent policy name: CAPD, not QMAP/QMAP-Pool.

## Suggested New Title and Abstract Direction

Possible title:

**Regular: When Does Learned Page Demotion Help in Hybrid Memory?**

Abstract direction:

> DRAM-NVM and CXL-like tiered memory systems make page demotion decisions cost-sensitive: a bad victim can increase slow-tier reads, writes, and migration traffic. We study whether a learned candidate-ranking policy can improve demotion under real trace pressure. CAPD uses recent address, PC, read/write context and page-state features to rank DRAM candidates. On a high-pressure streamcluster window, CAPD reduces weighted replay cost by 10.83% over the best rule-based baseline, mainly by reducing migrations. However, our results also show sharp boundaries: CAPD ties on dedup and can over-evict on canneal. These findings suggest that learned demotion is promising under replacement pressure, but needs pressure-aware candidate selection and conservative fallback before deployment.

## Final Verdict

As submitted, I would lean **Weak Reject** because the paper still looks like a learned eviction prototype with one strong positive result and an under-discussed failure case. But the work is not far from a HotStorage-quality submission. The best path is not to make it sound stronger; it is to make the boundary more explicit and turn the failure into the technical insight.

