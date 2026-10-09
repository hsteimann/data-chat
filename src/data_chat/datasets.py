"""The demo datasets: which database, catalog, notes and questions belong together.

``demo``        Five tables, ten questions — the original setup. Unchanged, so
                the published results stay reproducible.
``demo-large``  The same fictional shop as a real client's platform sees it:
                35 tables, several of them easy to mix up. Built to measure
                how much of the catalog the model should see at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Dataset:
    name: str
    db: Path
    catalog: Path
    freetext: Path
    questions: Path
    #: The module with ``build_tables``, ``write_duckdb``, ``START`` and ``END``.
    generator: str
    #: What ``data-chat eval`` runs without --stage.
    default_stages: tuple[str, ...] = ("schema", "freetext", "catalog")

    def _module(self):
        return import_module(self.generator)

    @property
    def period(self) -> tuple[date, date]:
        mod = self._module()
        return mod.START, mod.END

    def write_duckdb(self, path: str | Path | None = None) -> Path:
        return self._module().write_duckdb(path or self.db)


DATASETS = {
    "demo": Dataset(
        name="demo",
        db=REPO_ROOT / "data" / "demo.duckdb",
        catalog=REPO_ROOT / "catalog" / "data_catalog.yaml",
        freetext=REPO_ROOT / "catalog" / "freetext.md",
        questions=REPO_ROOT / "eval" / "questions.yaml",
        generator="data_chat.demo_data",
    ),
    "demo-large": Dataset(
        name="demo-large",
        db=REPO_ROOT / "data" / "demo-large.duckdb",
        catalog=REPO_ROOT / "catalog" / "demo-large" / "data_catalog.yaml",
        freetext=REPO_ROOT / "catalog" / "demo-large" / "freetext.md",
        questions=REPO_ROOT / "eval" / "demo-large" / "questions.yaml",
        generator="data_chat.demo_large",
        default_stages=("catalog", "catalog_selected"),
    ),
}


def get_dataset(name: str) -> Dataset:
    try:
        return DATASETS[name]
    except KeyError:
        raise ValueError(f"unknown dataset {name!r} — use one of {', '.join(DATASETS)}") from None
