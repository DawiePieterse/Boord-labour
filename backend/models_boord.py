"""Read-only projection of Boord's worker table.

The authoritative definition is ../Boord/backend/models.py. This is a
deliberately partial copy - only the columns this app reads - so schema
drift review has one short list to check.

RULES:
  * Never create this table (db.init_labour_db() passes an explicit list).
  * Never write through it - db.boord_engine is query_only, and Boord is
    the only writer of that file.
  * If Boord renames or drops a column below, main._assert_boord_schema()
    refuses to boot rather than 500-ing at the warehouse door.
"""
from sqlmodel import Field, SQLModel


class Worker(SQLModel, table=True):
    id: str = Field(primary_key=True)  # employee number - also exactly what the badge QR holds
    first_name: str = ""
    last_name: str = ""
    name: str = ""
    photo_filename: str = ""  # basename under Boord's data/photos/
    active: bool = True
