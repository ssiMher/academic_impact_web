# Person Tag Source Lists

Place manually curated or exported source lists here, then run:

```bash
make person-registry-refresh
```

Supported CSV columns:

```text
name,tag_type,aliases,source_links,matched_affiliations,note
```

List-valued columns use `;` as the separator:

```csv
name,tag_type,aliases,source_links,matched_affiliations,note
Grace Hopper,ieee_fellow,G. Hopper,https://example.com/grace,,"IEEE Fellow source"
Alan Turing,acm_fellow,A. Turing,https://example.com/turing,Princeton University,"ACM Fellow source"
```

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
```

Regenerate it only when the source page changes, and prefer official IEEE / Computer Society source files when they are reachable.

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
