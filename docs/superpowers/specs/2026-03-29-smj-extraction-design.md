# SMJ Extraction and Knowledge Base Design (Subproject 2)

Date: 2026-03-29
Status: Draft (pending user review)

## 1. Goals and Scope

This design defines the extraction and knowledge-base layer for local papers, focused on variable relationships, theory grounding, hypothesis verification, and citation edges for downstream 3D graph visualization.

In scope:
- Use local papers only (current corpus is mainly SMJ)
- No OCR in this phase
- Process fulltext-qualified documents only
- Dual storage: PostgreSQL (source of truth) + Neo4j (graph projection)

Out of scope:
- OCR pipeline
- Control variables extraction
- Robustness/appendix model extraction
- Sentence-level citation intent classification

## 2. Input Qualification

### 2.1 Document classes
- Class A (fulltext): eligible for formal extraction
- Class B (abstract + references only): skip directly
- Class C (broken structure or missing key fields): queue for remediation

### 2.2 Class A rule
Must satisfy both:
1. Has at least one major body block among `Hypotheses` or `Results`
2. Has at least one main-model result table or equivalent main-model statistical paragraph

Rules confirmed:
- Class B does not count toward the 100-paper sample denominator
- Only Class A enters extraction

## 3. Extraction Targets

### 3.1 Variable roles and relation types
Variable roles:
- independent
- dependent
- moderator
- mediator

Not extracted:
- control variables

Relation types:
- direct
- moderation
- mediation

### 3.2 Required relation fields
- direction: `positive | negative | u_shape | inverted_u | non_significant`
- effect strength: main-model stats only (for example beta, OR/HR, r, CI, p)
- hypothesis verification: `supported | partially_supported | not_supported`
- evidence anchor: text span/table ref/section tag

### 3.3 Two theory-grounding categories
- Variable-level theory grounding (why a variable is defined/valid)
- Relation-level theory grounding (why A->B should hold)

## 4. Citation Extraction

Phase-1 output:
- `Paper A -> Paper B (cited)` edge
- citation location tag: `background | hypothesis | discussion`

Not in phase-1:
- sentence-level citation motivation classification

## 5. Architecture (Recommended Hybrid)

Use a hybrid extraction flow: rule-based localization + LLM structured extraction + rule-based validation.

Pipeline:
1. Document normalization parse (HTML/PDF text layer)
2. Section and main-model localization (Hypotheses/Results/Table)
3. Candidate relation extraction (variables/hypotheses/stats)
4. LLM normalization (roles, direction, strength, verification, two theory categories)
5. Rule validation (consistency, format, main-model constraint)
6. Write facts to PostgreSQL and project graph to Neo4j
7. Route failed validations to review queue

## 6. Data Model (MVP)

### 6.1 PostgreSQL (source of truth)
Core tables:
- `paper`
- `variable`
- `hypothesis`
- `relation`
- `variable_theory`
- `relation_theory`
- `evidence`
- `citation_edge`

Constraints:
- Every formal `relation` must link to at least one `evidence`
- `model_tag` must be `main_model`

### 6.2 Neo4j (query projection)
Core node labels:
- `Paper`
- `Variable`
- `Theory`
- `Hypothesis`

Core edges:
- `(:Variable)-[:AFFECTS {type,direction,strength,...}]->(:Variable)`
- `(:Variable)-[:GROUNDED_BY]->(:Theory)`
- `(:RelationProxy)-[:JUSTIFIED_BY]->(:Theory)`
- `(:Paper)-[:CITES {section_tag}]->(:Paper)`

Note:
- Neo4j stores graph-query fields only
- Detailed evidence remains in PostgreSQL and is linked by IDs

## 7. Validation and Failure Handling

Validation checks:
- hypothesis label consistency (H1/H2a vs conclusion)
- direction/stat-sign consistency
- effect-strength format validity
- main-model-only enforcement (exclude robustness/appendix)

Failure categories:
- `parse_failed`
- `main_model_uncertain`
- `hypothesis_mismatch`
- `effect_conflict`
- `evidence_missing`

Policy:
- Failed items go to review queue
- Raw candidate and evidence are retained for human correction

## 8. MVP Acceptance

Sample policy:
- Class A only
- 100-paper baseline (Class B excluded from denominator)

Acceptance metrics:
- valid relation coverage on Class A
- field completeness (direction/strength/verification/evidence)
- hypothesis-verification accuracy
- traceability of both theory categories
- citation-edge locatability

## 9. Risks and Mitigations

Risks:
- heterogeneous writing styles in older papers
- noisy table structures causing stat misalignment
- same-name variables with semantic drift across papers

Mitigations:
- start with 100-paper high-precision baseline and refine rules
- maintain variable normalization dictionary with review loop
- prioritize review queue by high-impact relations

## 10. Next Step

After user approval of this design:
- create implementation plan (module boundaries, schema, sample-run and evaluation plan)
