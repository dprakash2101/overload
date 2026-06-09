from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DataSource:
    rows: list[dict[str, str]]
    columns: list[str]

    @classmethod
    def from_csv(cls, path_or_file: str | io.IOBase) -> DataSource:
        if isinstance(path_or_file, str):
            with open(path_or_file, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                rows = [dict(row) for row in reader]
                columns = list(reader.fieldnames) if reader.fieldnames else []
        else:
            content = path_or_file.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            rows = [dict(row) for row in reader]
            columns = list(reader.fieldnames) if reader.fieldnames else []

        logger.debug("DataSource: %d rows, columns: %s", len(rows), columns)
        return cls(rows=rows, columns=columns)

    def row_for(self, index: int) -> dict[str, str]:
        if not self.rows:
            return {}
        return self.rows[index % len(self.rows)]
