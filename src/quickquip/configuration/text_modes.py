"""Persistent per-group game text choices, separate from player records."""

from pathlib import Path

from quickquip.configuration.database import connect
from quickquip.configuration.paths import PATHS, data_directory
from quickquip.common.config_writes import configuration_write


class TextModeRepository:
    def __init__(self, path: Path = PATHS.configuration):
        self.path = Path(path)

    def get(self, group_id: str) -> str:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT text_mode FROM niuniu_group_text WHERE group_id=?", (str(group_id),)
            ).fetchone()
        return row[0] if row else "default"

    def set(self, group_id: str, mode: str):
        with (
            configuration_write(data_directory(self.path)),
            connect(self.path, write=True) as connection,
        ):
            connection.execute(
                "INSERT INTO niuniu_group_text VALUES(?,?) "
                "ON CONFLICT(group_id) DO UPDATE SET text_mode=excluded.text_mode",
                (str(group_id), mode),
            )

    def list(self):
        with connect(self.path) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT group_id,text_mode FROM niuniu_group_text ORDER BY group_id"
                )
            ]
