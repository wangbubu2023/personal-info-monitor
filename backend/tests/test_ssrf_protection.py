import pytest

from app.utils.ssrf import assert_public_http_target


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
