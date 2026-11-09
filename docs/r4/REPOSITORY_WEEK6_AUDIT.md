# Repository audit against the Week 6 execution plan

Snapshot: 9 November 2026. This is the START of Week 6 (9–13 November), not its
Friday deadline. This audit compares visible repository evidence with the plan's
end-of-Week-6 target. It does not evaluate private/local work, attendance or marks.

Main inspected: `bac19dbfb79861b446d92b55169da29482bc473f`.
R4 prior Week 6: `346826754fce822ca9a89f7d0f3679eb783338aa`.
Method: refreshed all remote refs; inspected main and all role branches/open and
merged PRs; read source, tests, configs and reports; ran targeted reproductions.
No other member's branch was changed or merged by this audit.

## Executive finding

The repository is NOT yet ready for the plan's full Week 6 feature freeze.
Subsystems exist, but main does not yet provide the integrated three-condition
system, complete CSP, replay demo, or experiment/evaluation pipeline. R4's six
weekly PRs cover its catch-up work; this follow-up PR covers the audit and two
R3/R4 compatibility corrections. There are no uncommitted R4 changes outside PRs
once this branch is pushed. All catch-up work uses actual November commit dates.

## Role-by-role evidence

| Role | Merged / visible work | Open work | End-of-Week-6 gaps / assessment |
|---|---|---|---|
| R1 simulation/lead | CI, world/model/interfaces, SimPy core, logger, Poisson events: PR #4 describes Weeks 1–2; later API fixes merged through #12 | No additional R1 commits beyond main found on r1/sim-core | Foundation present; not fully integrated. Default runner labels mode but does not switch planners. Closures cause polling, no connectivity guard; generated new-order events only announce IDs. Need actual dynamic orders, complete mode wiring, freeze/determinism/performance evidence. |
| R2 maps/search/viz | Real Secunderabad graph, Dijkstra/A*, alternatives, time-dependent search/FIFO checks, benchmarks: #1/#6/#12 | No newer R2 commits beyond the Week 2 PR observed | Strong search foundations and some supporting work. PR #12 explicitly leaves travel_time_matrix (W3) and replay visualization (W4) pending. Only static plot_route.py exists; no three-pane replay/performance evidence. |
| R3 KR/demand | No src/kr or src/data order generator on main | #8 has demand profiling/generator, ontology, forward-chaining rules, tests; more than its Week 1 title suggests | Partial Weeks 1–2 visible, unmerged. src/kr/csp.py is zero bytes: no CSP/MRV/forward checking/AC-3 implementation. No final scenario grid, complete planner integration or violation audit evidence. |
| R4 allocation | Six new weekly PRs #14–#19; not merged yet | Tested CNP, partial-state OR-Tools, mode/event controller, opt-in allocation harness, quality/budget study and handoff. This audit adds R3 compatibility | R4 scoped work is submitted through W6; team integration/review still pending. Harness full mode is allocation-only, not proof of R5/R7 integration. |
| R5 coordination | No coordination package on main | #13 adds conflict detector, trigger classes, Vickrey primitive in one file | Partial core exists, unmerged; not W6-ready. No dedicated pytest files added, no simulator hookup/tuning evidence. Reproduced capacity and credit-budget defects below; message-result recipient accounting also needs review. |
| R6 prediction | #3/#7 merged; chronological prep, persistence/historical baselines, LSTM/checkpoint/config, cached predictor, F4/results and robustness tests | No newer unmerged R6 work observed | Most advanced ML evidence: largely through W4, some later robustness. No model card/config+weights freeze hash or static-vs-predicted delivery ablation found. Exact W6 freeze and full in-sim validation not established by available files. Raw-data-dependent tests were not rerun for this audit. |
| R7 replanning | D* Lite core/property tests through W2 merged in #5/#9/#10 | #11 adds multi-stop planning, simulator adapter, F3 benchmark and tests | W3 work visible but unmerged; GitHub reports merge conflicts. Adapter also fails against current World API. No complete trigger toggle/hysteresis/latency integration evidence through W6. |
| R8 evaluation/report/process | Shared JSONL schema and AI-use log exist through other roles | No R8 branch or PR found | No src/eval package, main experiment YAML, bootstrap/paired-statistics runner, global WEEKLY_LOG/CONTRIBUTIONS, or report draft found. R4's pilot is not a substitute for the shared disruption sweep. |

## Concrete issues and reproductions

### R5 capacity check is pairwise rather than concurrent-capacity aware

Source: `r5/conflict-trigger` at `a0c3c2640e192db5b748960e91739ad6dd15c5d6`,
`src/coordination/conflict.py`, detect_conflicts and verify_conflicts_brute_force.

Reproduction on one edge with capacity 2: vehicle A occupies [0,10], B [0,10], C
[20,30]. Maximum concurrent occupancy is 2, so no capacity violation exists. The
implementation returns 1 conflict because the total user list has length 3 and
then it reports overlapping pairs. Its brute-force checker also does not enforce
capacity >1, so agreement between them would not independently validate this rule.
Fix needs an occupancy sweep or a separate capacity-aware oracle plus tests.

### R5 virtual credits can become negative

Two bidders value the slot at 10 and 9; the first has only 1 credit. Current code
allows any positive-credit bidder to bid its full value; it wins at price 9 and
ends at -8 credits. Define affordability and auction utility assumptions, and test
the resulting budget policy before claiming bounded-credit fairness/truthfulness.
The current primitive counts one result irrespective of the number of recipients;
confirm whether the result must be delivered to all contestants under D7.

### R7 is incompatible with the current World argument order

Source: `r7/dstar-lite-week3` at `c619f7122877bc33425999d26bf534b961d45826`,
`src/search/sim_replanner.py`, world_cost.

It calls `world.is_blocked(u,v,key,t)` and `spike_multiplier(u,v,key,t)`. Current
main expects `(u,v,t,key=None)`. Calling world_cost on a one-edge graph at 21600s
raises `KeyError: Edge (1, 2, 21600) not found in road graph.` PR #12 already calls
out this required follow-up. Resolve #11's merge conflicts, update both calls,
then run adapter tests against current main before integration.

### R3/R4 conventions needed an adapter: corrected in THIS follow-up

R3 ontology sets HIGH=1, MEDIUM=2, LOW=3; R4's earlier proposal used tier 3 as highest.
This follow-up uses priority weight `4 - tier` consistently in central penalties,
exact checking and pilot comparison, with a capacity-limited regression test.
R3 run_feasibility_engine returns a dictionary; R4's optional hook takes a
`(bool, trace)` tuple. `adapt_r3_feasibility` now converts and validates that result.
This is compatibility support, not a claim that R3's unmerged module or CSP is
already fully integrated. Pilot outputs were regenerated after the polarity fix.

### Process / submission evidence

- GitHub main branch inventory reported protected=false, despite the plan's
  protected-main recommendation. No settings were changed by this audit.
- No weekly release tags returned by `git tag -l` after fetch.
- No global weekly contribution record or final experiment config found.
- The plan requires human buddy review and teach-back; code/PR existence cannot
  establish those activities. They remain unverified.

## Recommended integration order

1. Review/merge R4 #14 → #19 in order, retargeting successor PRs as needed. Review
   this follow-up before combining with R3 so priority and feasibility agree.
2. R3 completes CSP and the operational feasibility interface/scenario units;
   update #8 and validate volume units, absolute-second windows and shift rules.
3. R5 adds capacity-aware tests, budget enforcement, per-recipient messages and
   real route/yield decisions; then integrates with R7/R1 (not just a toy demo).
4. R7 resolves #11 conflicts/API mismatch and demonstrates closure recovery on
   current main, including commitments mid-edge and after service.
5. R1 wires actual order creation, closure reachability guard and all modes in the
   main runner. R2 completes travel matrices/replay visualization. R6 records
   model freeze/hash and delivery ablation.
6. R8 supplies shared metrics, paired seeds/CIs, pilot runner and frozen experiment
   config; only then profile the integrated fleet and freeze features for W7.

These are recommendations from repository evidence, not assignments sent to the
team. No email/comments/messages were sent to other members.

## Sources

Execution-plan PDF supplied by user: 28 pages, especially Sections 5–8. The guide's
assumed calendar and TBA dates have not been replaced with official course dates.

- R1 #4: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/pull/4
- R2 #12: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/pull/12
- R3 #8: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/pull/8
- R5 #13: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/pull/13
- R6 #3: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/pull/3
- R7 #11: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/pull/11
- Main tree: https://github.com/f20241014/Pathfinders-Multi-Agent-AI-Delivery-System/tree/bac19dbfb79861b446d92b55169da29482bc473f

Raw targeted results: reports/r4/audit_reproductions.json. The audit is an evidence
review with targeted executions; it is not full test certification of other roles'
unmerged branches. Missing evidence means not visible here, not proof that a team
member has done no work.
