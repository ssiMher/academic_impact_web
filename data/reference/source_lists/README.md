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
