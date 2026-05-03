# Scholar Session Schema

Scholar impact sessions are stored as UTF-8 JSON at
`data/scholar_sessions/{session_id}/session.json`.

## Root Fields

- `schema_version`: currently `1.0`.
- `session_type`: always `scholar_impact`.
- `session_id`: directory/session identifier.
- `query`: author display name used to create the session.
- `selected_author`: resolved author identity.
- `publications`: scholar publication records with stable local IDs.
- `citation_edges`: citing-paper links for scholar publications.
- `statistics`: aggregate publication and citation statistics.
- `deep_analysis_queue`: citing papers selected for later full-text analysis.
- `task_state`: background task status.
- `created_at`, `updated_at`: ISO timestamps with second precision.

## Selected Author

`selected_author` keeps the disambiguated identity used for publication fetches:

- `display_name`
- `dblp_id`
- `openalex_id`
- `scopus_author_id`
- `affiliations`
- `source`

## Publication

Each publication receives a local ID such as `S001` and includes:

- `title`, `year`, `venue`, `doi`
- `unique_ids`, such as `DBLP`, `DOI`, `OpenAlex`, or `Scopus`
- `authors`
- `author_position`
- `citation_count`
- optional `venue_tier`

## Citation Edge

Citation edges link one scholar publication to one citing paper:

- `source_publication_id`
- `citing_paper_id`
- `citing_title`, `citing_year`, `citing_venue`, `citing_doi`
- `citing_authors`
- `provider`
- `cited_publication_title`

## Statistics

Initial sessions include:

- `publication_count`
- `citation_edge_count`
- `total_citation_count`
- `publication_tiers`
- `citing_venue_tiers`
- `person_tag_statistics`
- `yearly_citations`
- `top_publications`
- `strong_evidence_count`

`top_publications` is sorted by citation count descending, year descending, then title
ascending, and is capped at 10 records.

## Task State

Idle sessions use:

```json
{
  "active": false,
  "task_type": null,
  "status": "idle",
  "message": "",
  "started_at": null,
  "updated_at": null,
  "finished_at": null,
  "error": ""
}
```
