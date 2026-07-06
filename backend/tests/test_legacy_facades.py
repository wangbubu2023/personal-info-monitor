from __future__ import annotations

import importlib


def test_processor_facades_reexport_canonical_objects():
    from app.domains.ingest.extractor import ContentExtractor
    from app.domains.ingest.keywords.matcher import KeywordMatcher
    from app.platform.llm.summarizer import Summarizer
    from app.platform.llm.translator import Translator
    from app.processors import extractor, keyword_matcher, summarizer, translator

    assert extractor.ContentExtractor is ContentExtractor
    assert keyword_matcher.KeywordMatcher is KeywordMatcher
    assert summarizer.Summarizer is Summarizer
    assert translator.Translator is Translator


def test_pipeline_facades_reexport_canonical_objects():
    canonical_collector_stage = importlib.import_module("app.domains.fetch.collector_stage")
    canonical_coordinator = importlib.import_module("app.domains.fetch.coordinator")
    legacy_collector_stage = importlib.import_module("app.pipeline.collector_stage")
    legacy_coordinator = importlib.import_module("app.pipeline.coordinator")

    from app.domains.fetch.collector_stage import dedupe_raw_contents
    from app.domains.ingest.dedupe import handle_external_id_duplicate
    from app.domains.ingest.normalizer import NormalizerStage, _materialize_hydrated_fulltext
    from app.domains.ingest.storage import StorageStage
    from app.pipeline import dedupe, normalizer_stage, storage_stage, utils
    from app.utils.url import normalize_external_id

    assert legacy_collector_stage is canonical_collector_stage
    assert legacy_coordinator is canonical_coordinator
    assert dedupe.handle_external_id_duplicate is handle_external_id_duplicate
    assert normalizer_stage.NormalizerStage is NormalizerStage
    assert normalizer_stage._materialize_hydrated_fulltext is _materialize_hydrated_fulltext
    assert storage_stage.StorageStage is StorageStage
    assert utils.dedupe_raw_contents is dedupe_raw_contents
    assert utils.normalize_external_id is normalize_external_id


def test_service_facades_reexport_canonical_objects():
    from app.domains.ingest.keywords import rules
    from app.services import keyword_rules

    assert keyword_rules.normalize_keyword_value is rules.normalize_keyword_value
    assert keyword_rules.keyword_identity_key is rules.keyword_identity_key
    assert keyword_rules.dedupe_keywords_case_insensitive is rules.dedupe_keywords_case_insensitive
    assert keyword_rules.build_equivalent_terms is rules.build_equivalent_terms
    assert keyword_rules.compute_stored_equivalent_terms is rules.compute_stored_equivalent_terms
    assert keyword_rules._translation_cache is rules._translation_cache
