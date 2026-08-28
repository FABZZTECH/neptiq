"""Local type stubs for `pgvector.sqlalchemy`.

pgvector ships no ``py.typed``. ``Vector`` is used as a SQLAlchemy column type
in neptiq_db.models, so leaving it as ``Any`` would make the embeddings model
untyped. Declared as a TypeEngine subclass, which is what it is.
"""

from typing import Any

from sqlalchemy.types import TypeEngine

class Vector(TypeEngine[Any]):
    def __init__(self, dim: int | None = ...) -> None: ...
