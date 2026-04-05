# Variable Alias & Domain Extraction Design

## Summary

- Add paper-level domain extraction with source priority:
  1. Wiley metadata `topics.topicLabel`
  2. `citation_keywords`
  3. Model output fallback
- Add variable alias and canonical-id fields into relation extraction.
- Add nonlinear relation form and map to UI display classes: `positive|negative|nonlinear`.

## JSON Contract

Top-level:
- `paper_domains: string[]`
- `relations: object[]`
- `variable_level_theory_grounding: object[]`
- `relation_level_theory_grounding: object[]`
- `hypotheses: object[]`
- `citations: object[]`

Relation object required keys:
- `source_var`
- `target_var`
- `source_aliases: string[]`
- `target_aliases: string[]`
- `source_canonical_var_id`
- `target_canonical_var_id`
- `relation_type`
- `model_tag = "main_model"`
- `relation_form = "linear|nonlinear"`
- `direction`
- `verification`
- `evidence_anchor`

Canonical naming priority:
1. Hypothesis phrasing
2. Variable-definition section phrasing
3. Hypothesis-test table phrasing

## Storage Shape

- `paper_domains(paper_id, domain, source)`
- `canonical_variables(canonical_var_id, canonical_name)`
- `variable_aliases(canonical_var_id, alias_text, alias_norm, source, paper_id)`
- `relations(...)` includes:
  - `source_canonical_var_id`
  - `target_canonical_var_id`
  - `source_alias_text`
  - `target_alias_text`
  - `relation_form`
- `alias_mentions(paper_id, relation_row_id, canonical_var_id, alias_text, alias_norm, role)`

## Frontend Mapping

- Edge display class computed as:
  - `nonlinear` if `relation_form == nonlinear`
  - else `negative` if direction negative
  - else `positive` if direction positive
  - else fallback `nonlinear`
- UI colors are configurable for all 3 classes.
