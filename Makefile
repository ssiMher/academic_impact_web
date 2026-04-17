PHASE1_SMOKE_QUERY ?= Attention Is All You Need
PHASE1_SMOKE_PAPER_IDS ?=
PHASE1_SMOKE_LIMIT ?= 5
PHASE1_SMOKE_TOP_K_SPANS ?= 3
PHASE1_SMOKE_SORT ?= recent
FULLTEXT_CHECK_SESSION_ID ?=
FULLTEXT_CHECK_PAPER_ID ?=
ANALYSIS_SCOPE_BENCH_SESSION ?=
ANALYSIS_SCOPE_BENCH_IDS ?=
ANALYSIS_SCOPE_BENCH_TOP_N ?= 5
ANALYSIS_SCOPE_BENCH_CONCURRENCY ?= 1
ANALYSIS_SCOPE_BENCH_TOP_K_SPANS ?= 8
ANALYSIS_SCOPE_BENCH_OUTPUT_DIR ?=
PYTHON_CMD ?= python3

.PHONY: test phase1-smoke fulltext-check analysis-scope-bench
test:
	PYTHONPATH=.:$${PYTHONPATH:-} $(PYTHON_CMD) -m unittest discover -s tests -q

phase1-smoke:
	$(PYTHON_CMD) scripts/phase1_smoke.py \
		--query "$(PHASE1_SMOKE_QUERY)" \
		--limit "$(PHASE1_SMOKE_LIMIT)" \
		--sort-preference "$(PHASE1_SMOKE_SORT)" \
		--top-k-spans "$(PHASE1_SMOKE_TOP_K_SPANS)" \
		$(if $(strip $(PHASE1_SMOKE_PAPER_IDS)),--paper-ids "$(PHASE1_SMOKE_PAPER_IDS)",)

fulltext-check:
	$(PYTHON_CMD) scripts/fulltext_ready_check.py \
		$(if $(strip $(FULLTEXT_CHECK_SESSION_ID)),--session-id "$(FULLTEXT_CHECK_SESSION_ID)",) \
		$(if $(strip $(FULLTEXT_CHECK_PAPER_ID)),--paper-id "$(FULLTEXT_CHECK_PAPER_ID)",)

analysis-scope-bench:
	$(PYTHON_CMD) scripts/compare_analysis_scopes.py "$(ANALYSIS_SCOPE_BENCH_SESSION)" \
		--top-n "$(ANALYSIS_SCOPE_BENCH_TOP_N)" \
		--top-k-spans "$(ANALYSIS_SCOPE_BENCH_TOP_K_SPANS)" \
		--concurrency "$(ANALYSIS_SCOPE_BENCH_CONCURRENCY)" \
		$(if $(strip $(ANALYSIS_SCOPE_BENCH_IDS)),--ids "$(ANALYSIS_SCOPE_BENCH_IDS)",) \
		$(if $(strip $(ANALYSIS_SCOPE_BENCH_OUTPUT_DIR)),--output-dir "$(ANALYSIS_SCOPE_BENCH_OUTPUT_DIR)",)
