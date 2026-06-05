# HotStorage 2026 Review Report

## Overall Decision

**Current simulated decision: Weak Reject / Major Revision.**

The paper has a relevant systems problem and a plausible prototype, but the current submission is too easy to reject as an under-evidenced learned-cache policy. The strongest positive result is concentrated in one pressure window, while the standard 1M split contains weak or non-informative cases and canneal is a stable large failure. This can still become a good HotStorage paper, but only if the paper stops claiming "RAVE is a generally effective learned eviction policy" and instead makes the sharper workshop claim:

**Learned DRAM-NVM victim ranking is promising only under real replacement pressure, but unsafe unless candidate selection and over-eviction control are made explicit.**

That framing turns the current weakness into a HotStorage-style debate.

## Reviewer Configuration

- EIC perspective: HotStorage systems reviewer focused on novelty, discussion value, and whether this is a workshop-worthy storage idea rather than a small ML benchmark.
- Methodology reviewer: trace-driven evaluation, replay validity, leakage, workload selection, cost model, reproducibility.
- Domain reviewer: hybrid memory, NVM/CXL/tiered memory, page placement and replacement, learned replacement baselines.
- Devil's advocate: strongest case for rejection.

## Strengths

1. **The problem is real.** Hybrid DRAM-NVM and tiered memory policies must consider writes, demotion cost, and capacity pressure, not just hit rate.
2. **The current results are honest enough to be useful.** The paper reports the canneal failure and dedup tie instead of hiding them.
3. **The experiment pipeline is more complete than the paper currently conveys.** The repository contains real trace processing, pressure-window experiments, ablations, seed stability, cost-weight sensitivity, capacity sensitivity, and candidate-count sensitivity.
4. **The method is simple enough for a workshop paper.** Single-layer Transformer plus mean pooling is easier to discuss than a heavy architecture.

## Critical Issues

### 1. The paper's contribution is overstated relative to the evidence

The abstract says RAVE reduces cost on real traces and highlights 12.35% on streamcluster pressure. The actual picture is narrower:

- blackscholes: -0.91% vs LFU, but active page set is only 23 pages and all policies have very high hit rate.
- streamcluster standard split: 0 migrations, no replacement-policy comparison.
- streamcluster pressure: -12.35%, the strongest positive result.
- dedup pressure: exact tie with LRU.
- canneal: +19.32% worse than LRU, stable across seeds.

**Fix:** Reframe the paper around pressure-dependent behavior and failure boundaries. The title/abstract should say the paper studies when learned victim ranking helps and when it fails, not just present RAVE as an improved policy.

### 2. The evaluation has a cherry-picking risk even if the implementation did not select by RAVE performance

`scripts/scan_pressure_windows.py` ranks windows by LRU decision count, not by RAVE performance, which is defensible. But the paper only states this briefly. A reviewer will still ask: how many windows were scanned, where did this selected window rank, and what happens on the other top windows?

**Fix:** Add a compact main-text table or plot: top 5 pressure windows by LRU decision count, with RAVE delta for all of them. If only one window is shown, the result looks cherry-picked.

### 3. The method is workload-specialized, but the writing sounds like a general policy

The experiment pipeline trains one QMAP/RAVE checkpoint per workload and evaluates on the same workload's later split/window. The model also uses page and PC embeddings, so it may learn workload-specific page identities and PC patterns.

**Fix:** State this explicitly. Either position RAVE as a trace-trained per-workload policy, or add cross-workload / cross-phase experiments:

- train on earlier windows, test on multiple later disjoint windows;
- train on one PARSEC workload, test on another, even if it fails;
- remove page ID embeddings or report a no-page-id ablation.

Without this, reviewers may read the result as trace memorization.

### 4. The cost-aware label is not as physically grounded as the paper implies

The manuscript says labels use future inactivity, coldness, write sensitivity, and demotion cost. In `qmap_generator.py`, write sensitivity is future write frequency, but migration cost is currently `1.0 if candidate > 0x20 else 0.0`. That is not a calibrated demotion cost. It is an address-threshold proxy.

**Fix:** Do not call this a real demotion-cost label unless you replace it. Use an observable proxy: dirty bit, page size, writeback bytes, migration bytes, or measured memcpy/writeback time. If keeping the current implementation, call it an experimental proxy and move the contribution away from "cost-aware demotion cost".

### 5. Runtime overhead currently contradicts the "lightweight" claim

The paper says RAVE is off the critical path of regular accesses, but decision-time values are still huge in prototype terms:

- blackscholes QMAP: 3.39 ms/decision.
- streamcluster pressure QMAP: 2.36 ms/decision.
- dedup QMAP: 9.09 to 18.41 ms/decision.

Even if Python replay is not optimized, a storage systems reviewer will not accept "lightweight" without a credible deployment argument.

**Fix:** Replace "low overhead" with "off-access-path prototype" unless you can add one of:

- C++/TorchScript/ONNX microbenchmark;
- batched decision cost estimate;
- amortized cost per 1K accesses;
- a clear argument that eviction frequency is low enough in the target tiering system.

### 6. Canneal is not just a limitation; it is the central scientific problem

Canneal gets much worse because RAVE increases migrations from 2350 to 4567. Candidate-count sensitivity makes this more severe: canneal degrades from +6.83% at c4 to +93.58% at c16. That means the learned ranker becomes less safe as the choice set expands.

**Fix:** Make the canneal failure a first-class analysis:

- show LRU-tail candidate quality distribution;
- show whether RAVE evicts pages that are reused soon;
- report oracle top-1 / top-k headroom;
- add a conservative gate or hybrid fallback, even if it reduces streamcluster gains.

### 7. The paper is too equation-heavy for the amount of systems insight

Pages 2-4 spend a lot of space on standard embedding, Transformer, pooling, MLP, and NDCG equations. For HotStorage, this is less valuable than explaining why replacement pressure, candidate-set quality, dirty state, and workload phase shape the outcome.

**Fix:** Cut at least 30-40% of formulas. Keep one compact algorithm and one label equation. Use the saved space for pressure-window methodology, canneal diagnosis, and runtime discussion.

### 8. Figure strategy is not yet reviewer-proof

Figure 2 is useful but risky: it makes the paper look like "one big win, one big loss, two near-zero cases." Figure 3 is good for seed stability, but it only checks training randomness, not workload/window robustness.

**Fix:** Add a "where RAVE helps" figure: x-axis replacement pressure or LRU decision count, y-axis cost delta, one point per window. This directly supports a HotStorage-style claim.

### 9. Naming and artifact consistency are credibility risks

The paper says RAVE; the repository and scripts say QMAP/QMAP-Pool. Internal naming differences are fine during development, but if artifact reviewers or advisors inspect the repo, the mismatch weakens trust.

**Fix:** Before any artifact release or appendix reference, add a short mapping: "RAVE was named QMAP-Pool in the experimental artifact." Better: rename user-visible summaries and figures to RAVE.

### 10. The related work is adequate but not used to sharpen the gap

The paper cites key hybrid memory and learned replacement work, but the gap is still generic: "learning-based methods are not optimized for write sensitivity/cost." That is too easy to dismiss.

**Fix:** Position against specific dimensions:

- page placement vs victim selection;
- hit-rate replacement vs write/migration-cost replacement;
- policy trained per trace vs online tiering systems;
- NVM/PCM-era tiering vs CXL-era tiering.

## Suggested Rewrite

### New Abstract Shape

Start with the controversy:

"Learned page-management policies are attractive for DRAM-NVM tiering, but our trace replay shows that they are useful only when replacement pressure exposes learnable structure and can be harmful when candidate sets contain unsafe near-future-reuse pages."

Then state RAVE, strongest win, and failure:

"On a streamcluster pressure window, RAVE reduces weighted cost by 12.35%, but on canneal it increases cost by 19.32% due to over-eviction. We use this contrast to identify candidate-set quality and conservative fallback as the key open problems."

This is more honest and more HotStorage-friendly.

### Main-Text Experiment Restructure

1. Main result: show all four workload outcomes in one table.
2. Pressure-window validity: show selected-window methodology plus top-k windows.
3. Failure analysis: canneal over-eviction and candidate-count sensitivity.
4. Mechanism evidence: no_rw and no_cost ablations, but do not overclaim because effects are small.
5. Robustness: seed stability and cost-weight sensitivity, summarized briefly.

### Experiments To Add If Time Allows

Highest priority:

- Top-k pressure windows, not just selected streamcluster/dedup.
- No page-ID embedding ablation.
- No PC ablation, since paper claims PC helps.
- Oracle candidate-ranking headroom: how much better than LRU is possible within the LRU-tail candidate set?
- Canneal error analysis: fraction of evicted pages reused within 16/64/256 accesses.

Medium priority:

- More workloads: at least one storage-like workload such as RocksDB/YCSB, Redis, or a graph/in-memory analytics workload.
- Cross-phase train/test: train on one earlier high-pressure phase, test on another phase.
- C++/optimized inference estimate.

Lower priority:

- More Transformer-depth sweeps. The paper already has enough evidence that one layer is the right choice.

## Page-Level Writing Notes

- Page 1: The introduction is still generic. The first page must say why learned victim ranking is controversial now, not just why DRAM-NVM exists.
- Page 1 contributions: Replace "we design" with "we show when it helps and when it fails." That is the stronger contribution.
- Page 3 Figure 1: The framework is cluttered and repeats offline training labels. Simplify into offline labeling/training vs online eviction.
- Page 4 complexity: The O(H^2 d + H d^2 + |C| d^2) formula undermines "lightweight" unless paired with real decision frequency and optimized inference.
- Page 5 results: The canneal paragraph is good but should be promoted, not hidden as a boundary case.
- Page 6-7 appendix: Sensitivity results are important enough that one summary row should be in the main text.

## Final Recommendation

If the deadline is near, do not try to add a whole new system. The fastest high-impact revision is:

1. Reframe the paper as a pressure-aware and failure-aware learned eviction study.
2. Add a small table proving pressure-window selection is not cherry-picked.
3. Add one failure-analysis table for canneal.
4. Tone down "lightweight" and "cost-aware demotion cost" claims.
5. Make RAVE/QMAP naming and artifact mapping consistent.

With those changes, the paper becomes a credible HotStorage submission because it invites discussion around a real open problem. Without those changes, it reads like a small learned replacement prototype with one strong result and several caveats, which is likely to be rejected.

