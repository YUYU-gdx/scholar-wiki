from __future__ import annotations


class Neo4jRepo:
    """Graph projection repository with injected driver/session protocol."""

    def __init__(self, driver: object) -> None:
        self.driver = driver

    def project_bundle(self, paper_id: str, bundle: dict[str, object]) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (p:Paper {paper_id: $paper_id})
                SET p.extractability_status = $extractability_status,
                    p.paper_type = $paper_type
                """,
                paper_id=paper_id,
                extractability_status=str(bundle.get("extractability_status", "") or ""),
                paper_type=str(bundle.get("paper_type", "") or ""),
            )

            for row in bundle.get("direct_effects", []) or []:
                session.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    MERGE (s:Variable {name: $source})
                    MERGE (t:Variable {name: $target})
                    MERGE (s)-[r:DIRECT_EFFECT {paper_id: $paper_id, source: $source, target: $target, theory_name: $theory_name}]->(t)
                    SET r.effect_form = $effect_form,
                        r.verification = $verification,
                        r.evidence_text = $evidence_text
                    MERGE (p)-[:MENTIONS_EFFECT]->(r)
                    """,
                    paper_id=paper_id,
                    source=row.get("source", ""),
                    target=row.get("target", ""),
                    effect_form=row.get("effect_form", ""),
                    verification=row.get("verification", ""),
                    evidence_text=row.get("evidence_text", ""),
                    theory_name=row.get("theory_name", ""),
                )

            for row in bundle.get("moderations", []) or []:
                moderator = str(row.get("moderator", "") or "")
                source = str(row.get("source", "") or "")
                target = str(row.get("target", "") or "")
                session.run(
                    """
                    MERGE (p:Paper {paper_id: $paper_id})
                    MERGE (m:Variable {name: $moderator})
                    MERGE (s:Variable {name: $source})
                    MERGE (t:Variable {name: $target})
                    MERGE (m)-[r:MODERATES {paper_id: $paper_id, moderator: $moderator, source: $source, target: $target, theory_name: $theory_name}]->(t)
                    SET r.effect_form = $effect_form,
                        r.verification = $verification,
                        r.evidence_text = $evidence_text
                    MERGE (p)-[:MENTIONS_MODERATION]->(r)
                    """,
                    paper_id=paper_id,
                    moderator=moderator,
                    source=source,
                    target=target,
                    effect_form=row.get("effect_form", ""),
                    verification=row.get("verification", ""),
                    evidence_text=row.get("evidence_text", ""),
                    theory_name=row.get("theory_name", ""),
                )

            for row in bundle.get("interactions", []) or []:
                output = str(row.get("output", "") or "")
                inputs = row.get("inputs", []) or []
                for input_var in inputs:
                    session.run(
                        """
                        MERGE (p:Paper {paper_id: $paper_id})
                        MERGE (i:Variable {name: $input_var})
                        MERGE (o:Variable {name: $output})
                        MERGE (i)-[r:INTERACTION_EFFECT {paper_id: $paper_id, input_var: $input_var, output: $output, theory_name: $theory_name}]->(o)
                        SET r.effect_form = $effect_form,
                            r.verification = $verification,
                            r.evidence_text = $evidence_text
                        MERGE (p)-[:MENTIONS_INTERACTION]->(r)
                        """,
                        paper_id=paper_id,
                        input_var=input_var,
                        output=output,
                        effect_form=row.get("effect_form", ""),
                        verification=row.get("verification", ""),
                        evidence_text=row.get("evidence_text", ""),
                        theory_name=row.get("theory_name", ""),
                    )
