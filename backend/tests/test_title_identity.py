from app.domains.ingest.title_identity import merge_title_identity_metadata, title_fingerprint


def test_title_fingerprint_is_stable_for_same_title():
    title = "Central Bank Announces New Policy Framework"

    assert title_fingerprint(title) == title_fingerprint(title)
    assert len(title_fingerprint(title)) == 16


def test_title_identity_preserves_existing_duplicate_group():
    metadata = merge_title_identity_metadata(
        {"duplicate_group_id": "manual-group"},
        title="Central Bank Announces New Policy Framework",
    )

    assert metadata["duplicate_group_id"] == "manual-group"
    assert len(metadata["title_fp"]) == 16


def test_title_identity_skips_low_information_titles():
    assert merge_title_identity_metadata({}, title="AI") == {}
