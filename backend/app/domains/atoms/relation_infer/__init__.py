"""Cross-article relation inference (P2)."""

from app.domains.atoms.relation_infer.worker import enqueue_relation_infer, infer_relations

__all__ = ["enqueue_relation_infer", "infer_relations"]
