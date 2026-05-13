# Automatic Person Match Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace review-dependent person matching with deterministic auto-resolution that prefers strong evidence and suppresses ambiguous name-only matches.

**Architecture:** Keep raw candidate generation in `person_candidates.py`, then run an automatic resolution pass that scores author-to-candidate matches per tag, keeps only a confident winner, and feeds resolved counts into statistics/CSV exports. Add support for external identity and institution evidence now so OpenAlex author IDs and future registry enrichment can immediately improve match precision.

**Tech Stack:** Python stdlib, existing scholar/person candidate pipeline, unittest.

---

### Task 1: Lock the desired resolution behavior with failing tests

**Files:**
- Modify: `tests/test_person_registry_refresh.py`
- Modify: `tests/test_scholar_stats.py`
- Modify: `tests/test_scholar_web.py`

- [ ] Add a failing test that CAS/CAE name-only collisions do not count toward resolved author totals.
- [ ] Add a failing test that a unique ACM/IEEE exact-name match can still auto-resolve when there is no collision.
- [ ] Add a failing test that registry-provided OpenAlex/ORCID/institution evidence upgrades a match into the resolved set.
- [ ] Add a failing CSV export test for new auto-resolution fields (`auto_match_status`, resolved author list, score/confidence summary).
- [ ] Run the focused tests and confirm they fail for the intended reasons.

### Task 2: Implement evidence-aware auto-resolution in candidate building

**Files:**
- Modify: `skills/academic_impact_analyzer/person_candidates.py`

- [ ] Extend registry loading to preserve optional identity/context evidence fields (`openalex_author_ids`, `orcid_ids`, `dblp_author_ids`, `known_institutions`).
- [ ] Enrich evidence rows from `author_details` with source author IDs, source URLs, and author institutions when available.
- [ ] Add a deterministic scorer that evaluates each author/candidate pair using identity, institution, exact-name, alias, variant, and collision signals.
- [ ] Add a resolution pass that keeps only one confident winner per normalized author per tag and suppresses unresolved name-only collisions.
- [ ] Persist auto-resolution results on candidates (`resolved_matched_authors`, `auto_match_status`, `auto_match_score`, `auto_match_confidence`, suppression reasons) without removing the existing manual review fields.

### Task 3: Feed resolved matches into statistics and exports

**Files:**
- Modify: `skills/academic_impact_analyzer/person_candidates.py`
- Modify: `skills/scholar_impact_analyzer/scholar_stats.py`
- Modify: `app/services/scholar_core.py`

- [ ] Update candidate summarization to count only resolved authors in headline statistics while preserving raw candidate counts and high-risk diagnostics.
- [ ] Ensure scholar statistics and deep-analysis prioritization consume the resolved author view consistently.
- [ ] Extend citation statistics CSV (and raw citing authors CSV if needed) with the auto-resolution columns needed for deterministic audits.

### Task 4: Verify end-to-end behavior

**Files:**
- Verify only

- [ ] Run the focused unit tests for person candidate resolution and scholar stats/web exports.
- [ ] Run the broader scholar test suite used by this feature.
- [ ] Run `git diff --check`.
- [ ] Review the diff for unintended UI/status regressions before reporting completion.
