PHASE1_SMOKE_QUERY ?= Attention Is All You Need
PHASE1_SMOKE_PAPER_IDS ?=
PHASE1_SMOKE_LIMIT ?= 5
PHASE1_SMOKE_TOP_K_SPANS ?= 3
PHASE1_SMOKE_SORT ?= recent
FULLTEXT_CHECK_SESSION_ID ?=
FULLTEXT_CHECK_PAPER_ID ?=
PERSON_REGISTRY_SOURCE_DIR ?= data/reference/source_lists
PERSON_REGISTRY_PATH ?= data/reference/person_tag_registry.json
PERSON_REGISTRY_FETCH_ACM ?= 0
PERSON_REGISTRY_FETCH_IEEE_CS ?= 0
PERSON_REGISTRY_FETCH_IEEE_CS_WIKIPEDIA ?= 0
PYTHON_CMD ?= python3

.PHONY: test phase1-smoke fulltext-check person-registry-refresh
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

person-registry-refresh:
	$(PYTHON_CMD) scripts/refresh_person_tag_registry.py \
		--registry-path "$(PERSON_REGISTRY_PATH)" \
		--source-dir "$(PERSON_REGISTRY_SOURCE_DIR)" \
		$(if $(filter 1 true yes on,$(PERSON_REGISTRY_FETCH_ACM)),--fetch-acm,) \
		$(if $(filter 1 true yes on,$(PERSON_REGISTRY_FETCH_IEEE_CS)),--fetch-ieee-cs,) \
		$(if $(filter 1 true yes on,$(PERSON_REGISTRY_FETCH_IEEE_CS_WIKIPEDIA)),--fetch-ieee-cs-wikipedia,)
