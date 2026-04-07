PHASE1_SMOKE_QUERY ?= Attention Is All You Need
PHASE1_SMOKE_PAPER_IDS ?=
PHASE1_SMOKE_LIMIT ?= 5
PHASE1_SMOKE_TOP_K_SPANS ?= 3
PHASE1_SMOKE_SORT ?= recent
FULLTEXT_CHECK_SESSION_ID ?=
FULLTEXT_CHECK_PAPER_ID ?=
PYTHON_CMD ?= python

.PHONY: phase1-smoke fulltext-check
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
