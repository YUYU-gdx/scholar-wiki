from __future__ import annotations


class Neo4jRepo:
    """Graph projection repository with injected driver/session protocol."""

    def __init__(self, driver: object) -> None:
        self.driver = driver

    def project_bundle(self, paper_id: str, bundle: dict[str, list[dict[str, str]]]) -> None:
        with self.driver.session() as session:
            for row in bundle.get("relations", []):
                session.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    MERGE (s:Variable {name: $source_var})
                    MERGE (t:Variable {name: $target_var})
                    MERGE (p)-[:MENTIONS_RELATION {
                      source_var: $source_var,
                      relation_type: $relation_type,
                      direction: $direction,
                      verification: $verification,
                      model_tag: $model_tag
                    }]->(t)
                    MERGE (s)-[:AFFECTS {
                      relation_type: $relation_type,
                      direction: $direction,
                      verification: $verification,
                      model_tag: $model_tag
                    }]->(t)
                    """,
                    paper_id=paper_id,
                    source_var=row.get("source_var", ""),
                    target_var=row.get("target_var", ""),
                    relation_type=row.get("relation_type", ""),
                    direction=row.get("direction", ""),
                    verification=row.get("verification", ""),
                    model_tag=row.get("model_tag", ""),
                )

            for row in bundle.get("variable_level_theory_grounding", []):
                session.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    MERGE (v:Variable {name: $variable})
                    MERGE (th:Theory {name: $theory})
                    MERGE (p)-[:GROUNDED_IN]->(th)
                    MERGE (v)-[:GROUNDED_IN]->(th)
                    """,
                    paper_id=paper_id,
                    variable=row.get("variable", ""),
                    theory=row.get("theory", ""),
                )

            for row in bundle.get("hypotheses", []):
                session.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    MERGE (h:Hypothesis {paper_id: $paper_id, label: $label})
                    SET h.statement = $statement, h.verification = $verification
                    MERGE (p)-[:SUPPORTS_HYPOTHESIS]->(h)
                    """,
                    paper_id=paper_id,
                    label=row.get("label", ""),
                    statement=row.get("statement", ""),
                    verification=row.get("verification", ""),
                )

            for row in bundle.get("citations", []):
                session.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    MERGE (c:Citation {key: $citation_key})
                    SET c.source_text = $source_text
                    MERGE (p)-[:CITES]->(c)
                    """,
                    paper_id=paper_id,
                    citation_key=row.get("citation_key", ""),
                    source_text=row.get("source_text", ""),
                )

            for row in bundle.get("relation_level_theory_grounding", []):
                session.run(
                    """
                    MERGE (s:Variable {name: $source_var})
                    MERGE (t:Variable {name: $target_var})
                    MERGE (th:Theory {name: $theory})
                    MERGE (s)-[:GROUNDED_IN]->(th)
                    MERGE (t)-[:GROUNDED_IN]->(th)
                    """,
                    paper_id=paper_id,
                    source_var=row.get("source_var", ""),
                    target_var=row.get("target_var", ""),
                    theory=row.get("theory", ""),
                )
