"""Source CRUD, probe, scheduling and status views.

Phase 1 of the refactor migrates the following into this package:

* ``domains/sources/scheduling.py`` — owns the formerly-private ``_effective_due_interval_minutes``
  (currently private in ``app.tasks.fetch_tasks``) and ``list_due_source_ids``
* ``domains/sources/policy.py``, ``serialization.py``, ``probe.py``,
  ``status.py`` — split from ``app/api/sources/_helpers.py`` (404 lines)
* ``domains/sources/probe/`` — ``ProbeService`` + already-extracted strategies
* ``domains/sources/source_types.py`` — moved from ``app/data/source_types.py``

The package intentionally starts empty; importers MUST NOT rely on any
attribute here until the migrations land.
"""
