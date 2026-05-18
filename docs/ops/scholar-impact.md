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

## PDF Source Priority

For scholar queue items, the current PDF priority is:

1. manually uploaded PDF
2. matched local library PDF
3. auto-downloaded PDF

Local library matching checks:

- `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS`
- `ACADEMIC_IMPACT_DOWNLOAD_DIR`
- `ACADEMIC_IMPACT_PDF_INDEX_PATH`

Filename matching is case-insensitive and also strips common download noise such as `arxiv`, `preprint`, `accepted version`, and `supplementary`.

If `ACADEMIC_IMPACT_PDF_INDEX_PATH` points to an existing JSON index, scholar queue matching will use that cache first and only fall back to directory scanning when needed.

## Local PDF Index Refresh

The scholar detail page now shows a local PDF index status panel with:

- current index entry count
- last scanned PDF count
- last index build duration
- last queue rematch duration
- last refresh total duration
- current deep-analysis queue matches resolved from the local library
- index path
- refresh button for rebuilding the JSON index and refreshing the current scholar queue

Use the refresh button after:

- adding new PDFs into the local library
- rebuilding a large local library index offline
- changing `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS`
- changing `ACADEMIC_IMPACT_PDF_INDEX_PATH`

The refresh action intentionally stays local-PDF-scoped:

- rebuild the JSON index
- rematch the current deep-analysis queue against the refreshed index
- preserve the rest of the scholar-derived statistics

It does **not** rebuild person candidates or regenerate the queue from citation edges. That keeps the button aligned with its name and avoids paying the full scholar-derivation cost when the user only added or renamed local PDFs.

## Expected Runtime

Metadata-only statistics should finish in minutes for tens of publications.

Deep fulltext analysis should be treated as a background batch. A queue of 100 citing papers may take 30 to 90 minutes depending on PDF availability and LLM latency.
