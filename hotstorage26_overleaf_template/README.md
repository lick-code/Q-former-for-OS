# HotStorage 2026 Overleaf Template

This folder is ready to upload to Overleaf as a ZIP project.

## Official Submission Facts Checked

- Venue: 18th ACM Workshop on Hot Topics in Storage and File Systems, September 28--29, 2026, Prague, Czechia.
- Deadline: May 22, 2026, 11:59 p.m. AOE.
- Review: double-blind.
- Paper categories: title must begin with `Position:` or `Regular:`.
- Length: at most 5 pages for main text, excluding references and appendix.
- Format: ACM two-column format.
- Camera-ready change to remember: accepted papers are expected to fit in 7 pages including references.

Always re-check the official CFP before submission:
https://www.hotstorage.org/2026/cfp.html

## Recommended Structure for a Regular Paper

| Section | Target length | Purpose |
| --- | ---: | --- |
| Title + abstract | 0.3--0.4 pages | Problem, insight, result in one breath |
| 1. Introduction | 0.75--0.9 pages | Motivate, state gap, summarize contributions |
| 2. Motivation and Background | 0.5--0.65 pages | Define workload, cache stack, and failure mode |
| 3. Design | 1.1--1.35 pages | Explain policy state, admission, eviction, overhead |
| 4. Evaluation | 1.1--1.3 pages | Trace setup, main result, ablation, limitations |
| 5. Discussion and Limitations | 0.45--0.6 pages | Deployment risks and why the topic is workshop-worthy |
| 6. Related Work | 0.3--0.45 pages | Short grouped comparison |
| 7. Conclusion | 0.15--0.25 pages | One storage-systems implication |

Keep the main text under 5 pages. Put parameter sweeps, extra traces, and
longer formulas in the appendix because reviewers are not required to read it.

## If You Submit a Position Paper

Use this shape instead:

| Section | Target length | Purpose |
| --- | ---: | --- |
| Introduction | 0.8 pages | A sharp claim and why now |
| Evidence | 1.2 pages | Measurements, traces, or examples showing the problem |
| Argument | 1.4 pages | The thesis and design space |
| Research Agenda | 0.9 pages | Concrete next steps for the community |
| Risks and Counterarguments | 0.5 pages | Show intellectual honesty |
| Related Work + Conclusion | 0.4 pages | Place the idea and close |

## Representative Papers to Read First

For a cache replacement or storage-cache submission, start with:

1. PaperCache: In-Memory Caching with Dynamic Eviction Policies, HotStorage 2025.
2. Can a Client--Server Cache Tango Accelerate Disaggregated Storage?, HotStorage 2025.
3. CableCache: In-Network Request Deduplication for Key-Value Stores, HotStorage 2025.
4. CacheLib: A General-Purpose Caching Engine, OSDI 2020.
5. SIEVE is Simpler than LRU, NSDI 2024.

Use the first three for HotStorage-style scope and framing. Use the last two for
system/evaluation expectations around modern cache replacement.

## Overleaf Notes

- Main file: `main.tex`.
- Bibliography file: `references.bib`.
- Compile with `LaTeX -> BibTeX -> LaTeX -> LaTeX`; Overleaf does this automatically in most ACM projects.
- Do not add author names, affiliations, acknowledgments, repository URLs, or self-identifying artifact links before review.
- Replace placeholder traces and figure text before submission.
