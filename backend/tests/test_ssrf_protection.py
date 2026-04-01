import pytest

from app.utils.ssrf import assert_public_http_target, check_before_fetch, hosts_match


# ---------------------------------------------------------------------------
# assert_public_http_target
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejects_localhost():
    with pytest.raises(ValueError, match="localhost"):
        await assert_public_http_target("http://localhost/admin")


@pytest.mark.asyncio
async def test_rejects_private_ip_192():
    with pytest.raises(ValueError, match="private"):
        await assert_public_http_target("http://192.168.1.1/admin")


@pytest.mark.asyncio
async def test_rejects_loopback():
    with pytest.raises(ValueError, match="private"):
        await assert_public_http_target("http://127.0.0.1:8080/secret")


@pytest.mark.asyncio
async def test_rejects_non_http():
    with pytest.raises(ValueError, match="unsupported scheme"):
        await assert_public_http_target("ftp://example.com/file")


@pytest.mark.asyncio
async def test_rejects_missing_hostname():
    with pytest.raises(ValueError, match="missing hostname"):
        await assert_public_http_target("http:///path")


@pytest.mark.asyncio
async def test_rejects_10_network():
    with pytest.raises(ValueError, match="private"):
        await assert_public_http_target("http://10.0.0.1/internal")


@pytest.mark.asyncio
async def test_rejects_link_local():
    with pytest.raises(ValueError, match="private"):
        await assert_public_http_target("http://169.254.1.1/metadata")


@pytest.mark.asyncio
async def test_allows_public_url():
    await assert_public_http_target("https://example.com")


# ---------------------------------------------------------------------------
# hosts_match
# ---------------------------------------------------------------------------

def test_hosts_match_same():
    assert hosts_match("https://example.com/a", "https://example.com/b") is True


def test_hosts_match_trailing_dot():
    assert hosts_match("https://example.com./a", "https://example.com/b") is True


def test_hosts_match_different():
    assert hosts_match("https://evil.com/x", "https://legit.com/y") is False


def test_hosts_match_case_insensitive():
    assert hosts_match("https://EXAMPLE.COM/a", "https://example.com/b") is True


# ---------------------------------------------------------------------------
# check_before_fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_before_fetch_blocks_private():
    with pytest.raises(ValueError):
        await check_before_fetch("http://192.168.1.1/secret")


@pytest.mark.asyncio
async def test_check_before_fetch_blocks_localhost():
    with pytest.raises(ValueError):
        await check_before_fetch("http://127.0.0.1:8080/admin")


@pytest.mark.asyncio
async def test_check_before_fetch_cookie_host_mismatch():
    with pytest.raises(ValueError, match="Cookie host mismatch"):
        await check_before_fetch(
            "https://evil.com/steal",
            source_url="https://legit-site.com",
            cookies={"session": "abc123"},
        )


@pytest.mark.asyncio
async def test_check_before_fetch_cookie_same_host_ok():
    await check_before_fetch(
        "https://example.com/article",
        source_url="https://example.com",
        cookies={"session": "abc"},
    )


@pytest.mark.asyncio
async def test_check_before_fetch_no_cookies_no_source_ok():
    await check_before_fetch("https://example.com/page")


@pytest.mark.asyncio
async def test_check_before_fetch_cookies_no_source_ok():
    """When source_url is empty, cookie-host check is skipped (SSRF still runs)."""
    await check_before_fetch(
        "https://example.com/article",
        cookies={"session": "abc"},
    )
