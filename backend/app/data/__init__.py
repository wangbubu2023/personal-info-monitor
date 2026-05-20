"""Static data resources (JSON catalogs) consumed at runtime.

The only file currently shipped here is ``model_providers.json``, loaded
via :func:`pathlib.Path` from :mod:`app.utils.model_catalog`. Keeping this
directory as a real Python package (with an explicit ``__init__.py``)
guards against future tooling that does not honour PEP 420 namespace
packages.
"""
