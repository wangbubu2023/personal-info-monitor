"""Playwright stealth helpers.

Paywalled sites (NYT, WSJ, Bloomberg…) fingerprint the browser even when a
valid login cookie is present: they look for ``navigator.webdriver``, empty
plugin arrays, ``window.chrome`` surface missing, and CDP-only WebGL
parameters. The defaults below cover the common signals that matter on those
sites. Not a full ``playwright-stealth`` replacement, but enough to stop most
one-line automation detectors.
"""


def stealth_init_script() -> str:
    """Return an init script injected before every page load."""
    return r"""
// navigator.webdriver — the single biggest tell. Delete the getter entirely
// so ``'webdriver' in navigator`` returns false (not just ``=== false``).
Object.defineProperty(Navigator.prototype, 'webdriver', {
    get: () => undefined,
    configurable: true,
});
try { delete navigator.__proto__.webdriver; } catch (_) {}

// window.chrome surface — Chrome has this; headless used to lack it.
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
window.chrome.loadTimes = window.chrome.loadTimes || function () { return {}; };
window.chrome.csi = window.chrome.csi || function () { return {}; };

// navigator.languages — should be a non-empty array of strings.
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
});

// navigator.plugins / mimeTypes — real Chrome exposes a non-empty PluginArray.
// Returning a faux array of descriptors masks the "plugins.length === 0" heuristic.
const fakePlugin = (name, filename, description) => {
    const plugin = { name, filename, description, length: 1 };
    plugin[0] = { type: 'application/pdf', suffixes: 'pdf', description };
    return plugin;
};
const fakePlugins = [
    fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('Microsoft Edge PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('WebKit built-in PDF', 'internal-pdf-viewer', 'Portable Document Format'),
];
Object.defineProperty(navigator, 'plugins', {
    get: () => fakePlugins,
    configurable: true,
});

// Permissions query patch — headless Chrome used to return 'denied' for 'notifications'
// without a prior permission grant. Real Chrome returns 'default'.
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
        parameters && parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification && Notification.permission || 'default' })
            : originalQuery(parameters)
    );
}

// WebGL renderer/vendor — common fingerprint. Expose the Intel/Apple strings
// instead of the generic "SwiftShader"/"Google Inc." that headless reports.
try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
        // UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL
        if (parameter === 37445) return 'Apple Inc.';
        if (parameter === 37446) return 'Apple M1';
        return getParameter.call(this, parameter);
    };
} catch (_) {}

// navigator.hardwareConcurrency / deviceMemory — sensible desktop values.
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
    configurable: true,
});
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
    configurable: true,
});
"""
