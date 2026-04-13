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
