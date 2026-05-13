# Person Tag Source Lists

Place manually curated or exported source lists here, then run:

```bash
make person-registry-refresh
```

Supported CSV columns:

```text
name,tag_type,aliases,source_links,matched_affiliations,openalex_author_ids,orcid_ids,dblp_author_ids,known_institutions,note
```

List-valued columns use `;` as the separator:

```csv
name,tag_type,aliases,source_links,matched_affiliations,openalex_author_ids,orcid_ids,dblp_author_ids,known_institutions,note
Grace Hopper,ieee_fellow,G. Hopper,https://example.com/grace,,https://openalex.org/A123;https://openalex.org/A456,orcid:0000-0001-2345-6789,,Yale University;Harvard University,"IEEE Fellow source"
Alan Turing,acm_fellow,A. Turing,https://example.com/turing,Princeton University,,,turing/T/Alan,Princeton University,"ACM Fellow source"
```

`openalex_author_ids`, `orcid_ids`, `dblp_author_ids`, and `known_institutions` are optional enrichment fields used by the automatic person-match resolver. They are merged and preserved by `make person-registry-refresh`.

You can also paste the copied ACM Fellows award table into a `.txt` or `.tsv` file. The importer recognizes rows shaped like:

```text
Adar, Eytan	ACM Fellows	2025	North America	Digital Library
Bengio, Yoshua	ACM Fellows	2023	North America	Digital Library
```

Save browser-copied ACM rows as, for example:

```text
data/reference/source_lists/acm_fellows_paste.txt
```

Then run `make person-registry-refresh`.

IEEE Computer Society Fellow class pages can be handled the same way. Save the copied page text as, for example:

```text
data/reference/source_lists/ieee_cs_fellows_2026.txt
```

Rows shaped like these are imported as `ieee_fellow`:

```text
IEEE Computer Society Announces 2026 Class of Fellows
Tamim Asfour - for contributions to humanoid robotics and robot learning
Anupam Chattopadhyay for contributions to embedded systems security
```

You can also try live IEEE CS fetches:

```bash
make person-registry-refresh PERSON_REGISTRY_FETCH_IEEE_CS=1
```

If the site returns HTTP 403, paste the page text into a `.txt` file instead.

When `computer.org` is blocked, the Wikipedia page for `List of fellows of IEEE Computer Society` can be used as a secondary-source fallback. Copied tables shaped like this are also imported as `ieee_fellow`:

```text
Year	Fellow	Citation
2020	Hussein Abbass	For contributions to evolutionary learning and optimization
2023	Gail-Joon Ahn	For development of applications of information and systems security
```

The live fallback fetch is:

```bash
make person-registry-refresh PERSON_REGISTRY_FETCH_IEEE_CS_WIKIPEDIA=1
```

This repository also includes a generated secondary-source snapshot:

```text
data/reference/source_lists/ieee_computer_society_fellows_wikipedia.json
data/reference/source_lists/ieee_cross_field_fellows_wikipedia.json
```

Regenerate it only when the source page changes, and prefer official IEEE / Computer Society source files when they are reachable.

The cross-field IEEE snapshot currently covers the Wikipedia lists that were reachable for Communications, Circuits and Systems, Computational Intelligence, and Control Systems. Wikipedia redlinks or list pages with non-table structures are skipped until an official or parseable source is available.

CAS / CAE information-field academicians are also maintained as generated official-source snapshots:

```text
data/reference/source_lists/cas_information_technology_academicians_official.json
data/reference/source_lists/cae_information_electronics_academicians_official.json
```

Full CAS / CAE academicians and foreign academicians are maintained as separate official-source snapshots:

```text
data/reference/source_lists/cas_all_academicians_official.json
data/reference/source_lists/cas_foreign_academicians_official.json
data/reference/source_lists/cas_deceased_academicians_official.json
data/reference/source_lists/cas_deceased_foreign_academicians_official.json
data/reference/source_lists/cae_all_academicians_official.json
data/reference/source_lists/cae_foreign_academicians_official.json
data/reference/source_lists/cae_deceased_academicians_official.json
data/reference/source_lists/cae_deceased_foreign_academicians_official.json
```

Current official-count checkpoints:

- CAS all academicians: 892, parsed from the current all-academician detail links.
- CAS deceased academicians: 738, parsed from deceased academician detail links.
- CAS deceased foreign academicians: 42, English names are kept as `name` where the official label includes English in parentheses.
- CAE all academicians: 981, deduplicated by CAE detail URL; the engineering-management cross-division display is merged rather than counted twice.
- CAE foreign academicians: 146, from the CAE foreign member list.
- CAE deceased academicians: 380, from the CAE deceased academician table.
- CAE deceased foreign academicians: 24, from the CAE deceased foreign academician table.

For matching DBLP / OpenAlex / Scopus author names, Chinese CAS / CAE entries include generated pinyin aliases. Foreign academician entries use English names as `name` and keep Chinese official names in `aliases` where available.

Supported JSON formats:

```json
{
  "items": [
    {
      "name": "Grace Hopper",
      "tag_type": "ieee_fellow",
      "aliases": ["G. Hopper"],
      "source_links": ["https://example.com/grace"],
      "matched_affiliations": [],
      "openalex_author_ids": ["https://openalex.org/A123"],
      "orcid_ids": ["orcid:0000-0001-2345-6789"],
      "dblp_author_ids": [],
      "known_institutions": ["Yale University"],
      "note": "IEEE Fellow source"
    }
  ]
}
```

or a raw list of the same objects.

Supported `tag_type` values:

- `acm_fellow`
- `ieee_fellow`
- `cas_academician`
- `cae_academician`
- `top_school`

The refresh script only creates registry entries. Candidates remain pending until reviewed in the session page.

For conservative OpenAlex identity enrichment against a known comparison pack or shortlist, use:

```bash
python3 scripts/enrich_person_tag_registry_openalex.py \
  --registry-path data/reference/person_tag_registry.json \
  --review-zip /path/to/author_level_analysis_outputs.zip \
  --dry-run
```

Drop `--dry-run` to persist only the high-confidence matches. The enrichment gate is intentionally strict: common-name collisions are skipped rather than guessed.
