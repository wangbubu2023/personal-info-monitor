"""Platform-level persistence primitives.

Phase 5 step 4 of the refactor relocates ``app.database`` (SQLAlchemy
sync + async engines, ``Base`` declarative, ``SessionLocal`` /
``AsyncSessionLocal`` factories, SQLite WAL pragmas, FastAPI ``get_db``
dependency) into the platform layer. The legacy :mod:`app.database`
path remains as a thin re-export shim — over 50 modules consume it,
and a single big-bang rewrite would dwarf this slice's risk budget.
Phase 7 (or an opportunistic future PR) can drive the bulk migration
once the rest of Phase 5 is settled.
"""
