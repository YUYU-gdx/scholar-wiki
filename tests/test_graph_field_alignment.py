from __future__ import annotations

import unittest

from kn_graph.services.graph_builder import _resolve_display_effect_class
from kn_graph.services.graph_service import GraphService


class GraphFieldAlignmentTest(unittest.TestCase):
    def test_display_effect_class_follows_effect_form(self) -> None:
        self.assertEqual(_resolve_display_effect_class("positive"), "positive")
        self.assertEqual(_resolve_display_effect_class("negative"), "negative")
        self.assertEqual(_resolve_display_effect_class("nonlinear"), "nonlinear")
        self.assertEqual(_resolve_display_effect_class("unclear"), "unclear")

    def test_normalize_edge_uses_canonical_fields_only(self) -> None:
        row = {
            "source": "var::A",
            "target": "var::B",
            "relation_type_raw": "interaction",
            "relation_form": "negative",
            "paper_id": "p1",
        }
        normalized = GraphService._normalize_edge(row)
        self.assertEqual(normalized["relation_type_std"], "")
        self.assertEqual(normalized["effect_form"], "")
        self.assertEqual(normalized["display_effect_class"], "")


if __name__ == "__main__":
    unittest.main()
