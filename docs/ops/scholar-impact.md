# Scholar Impact Workflow

## Required IDs

Prefer DBLP ID, Scopus Author ID, or OpenAlex Author ID. Name-only search is only for finding candidates.

The current web create flow requires a DBLP ID because the publication fetcher is DBLP-backed. Scopus and OpenAlex IDs are preserved in the session payload for later provider expansion.

## Required Environment

Use Scopus when available:

```bash
export ACADEMIC_IMPACT_CITATION_SOURCE=scopus
export ELSEVIER_API_KEY="..."
```

Use OpenAlex fallback when Scopus is unavailable:

```bash
export ACADEMIC_IMPACT_CITATION_SOURCE=openalex
```

## MVP Workflow

1. Open the web app.
2. Create a scholar session with author name and DBLP ID.
3. Review publication statistics.
4. Expand citations with a conservative limit per publication.
5. Review Fellow and venue statistics.
6. Select high-value citation cases for PDF upload or download.
7. Run fulltext analysis only for selected cases.

## Expected Runtime

Metadata-only statistics should finish in minutes for tens of publications.

Deep fulltext analysis should be treated as a background batch. A queue of 100 citing papers may take 30 to 90 minutes depending on PDF availability and LLM latency.
