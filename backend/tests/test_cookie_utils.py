from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.utils.cookies import normalize_cookie_dict


def test_normalize_cookie_dict_filters_expired_and_cross_domain_items():
    now = datetime(2026, 3, 31, tzinfo=timezone.utc)
    cookie_payload = json.dumps(
        [
            {
                "name": "session",
                "value": "abc",
                "domain": ".wsj.com",
                "expires": (now + timedelta(hours=1)).timestamp(),
            },
            {
                "name": "expired",
                "value": "nope",
                "domain": ".wsj.com",
                "expires": (now - timedelta(hours=1)).timestamp(),
            },
            {
                "name": "other",
                "value": "skip",
                "domain": ".example.com",
                "expires": (now + timedelta(hours=1)).timestamp(),
            },
        ]
    )

    normalized = normalize_cookie_dict(
        cookie_payload,
        site_host="www.wsj.com",
        now=now,
    )

    assert normalized == {"session": "abc"}


def test_normalize_cookie_dict_keeps_plain_cookie_headers():
    normalized = normalize_cookie_dict("a=1; b=2", site_host="wsj.com")
    assert normalized == {"a": "1", "b": "2"}
