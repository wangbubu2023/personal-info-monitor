"""Tests for atom vocabulary enums."""

from app.domains.atoms.vocab import AtomType, Domain, RelationType


def test_atom_type_values():
    assert AtomType.INFO.value == "信息"
    assert AtomType.OPINION.value == "观点"
    assert AtomType.DATA.value == "数据"


def test_domain_includes_tech():
    assert Domain.TECH.value == "科技"


def test_relation_type_corroboration():
    assert RelationType.CORROBORATION.value == "印证"
