"""Create the sole Stage B observation table without touching domain rows."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import engine
from app.models.external_failure_observation import (
    ensure_external_failure_observation_schema,
)


def upgrade(bind=None):
    bind = bind or engine
    if hasattr(bind, "exec_driver_sql"):
        ensure_external_failure_observation_schema(bind)
        return
    with bind.begin() as connection:
        ensure_external_failure_observation_schema(connection)


if __name__ == "__main__":
    upgrade()
    print("External failure observation schema ready; no historical diagnostics inferred")
