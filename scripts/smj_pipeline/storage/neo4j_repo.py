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
                    MERGE (s)-[r:DIRECT_EFFECT {paper_id: $paper_id, source: $source, target: $target, hypothesis_label: $hypothesis_label}]->(t)
                    SET r.direction = $direction,
                        r.relation_form = $relation_form,
                        r.verification = $verification,
                        r.evidence_section = $evidence_section
                    MERGE (p)-[:MENTIONS_EFFECT]->(r)
                    """,
                    paper_id=paper_id,
                    source=row.get("source", ""),
                    target=row.get("target", ""),
                    direction=row.get("direction", ""),
                    relation_form=row.get("relation_form", ""),
                    verification=row.get("verification", ""),
                    evidence_section=row.get("evidence_section", ""),
                    hypothesis_label=row.get("hypothesis_label", ""),
                )

            for row in bundle.get("moderations", []) or []:
                moderator = str(row.get("moderator", "") or "")
                targets = row.get("moderated_effects", []) or []
                for target in targets:
                    session.run(
                        """
                        MERGE (p:Paper {paper_id: $paper_id})
                        MERGE (m:Variable {name: $moderator})
                        MERGE (s:Variable {name: $source})
                        MERGE (t:Variable {name: $target})
                        MERGE (m)-[r:MODERATES {paper_id: $paper_id, moderator: $moderator, source: $source, target: $target}]->(t)
                        SET r.direction = $direction,
                            r.verification = $verification,
                            r.evidence_section = $evidence_section,
                            r.hypothesis_label = $hypothesis_label
                        MERGE (p)-[:MENTIONS_MODERATION]->(r)
                        """,
                        paper_id=paper_id,
                        moderator=moderator,
                        source=target.get("source", ""),
                        target=target.get("target", ""),
                        direction=row.get("direction", ""),
                        verification=row.get("verification", ""),
                        evidence_section=row.get("evidence_section", ""),
                        hypothesis_label=row.get("hypothesis_label", ""),
                    )

            for row in bundle.get("interactions", []) or []:
                output = str(row.get("output", "") or "")
                interaction_type = str(row.get("type", "") or "")
                inputs = row.get("inputs", []) or []
                for input_var in inputs:
                    session.run(
                        """
                        MERGE (p:Paper {paper_id: $paper_id})
                        MERGE (i:Variable {name: $input_var})
                        MERGE (o:Variable {name: $output})
                        MERGE (i)-[r:INTERACTION_EFFECT {paper_id: $paper_id, input_var: $input_var, output: $output, interaction_type: $interaction_type, hypothesis_label: $hypothesis_label}]->(o)
                        SET r.effect = $effect,
                            r.verification = $verification,
                            r.evidence_section = $evidence_section
                        MERGE (p)-[:MENTIONS_INTERACTION]->(r)
                        """,
                        paper_id=paper_id,
                        input_var=input_var,
                        output=output,
                        interaction_type=interaction_type,
                        hypothesis_label=row.get("hypothesis_label", ""),
                        effect=row.get("effect", ""),
                        verification=row.get("verification", ""),
                        evidence_section=row.get("evidence_section", ""),
                    )
