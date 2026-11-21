"""Loads the verified label rules and label text from data/ (provided with the kit)."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabelChunk:
    chunk_id: str
    drug: str
    product: str
    text: str
    source: str


class RulesCatalog:
    def __init__(self, rules: dict[str, dict], labels: list[LabelChunk]) -> None:
        self._rules = rules
        self._labels = labels

    @classmethod
    def load(cls, data_dir: Path) -> "RulesCatalog":
        rules = json.loads((data_dir / "dosing_rules.json").read_text(encoding="utf-8"))
        raw = json.loads((data_dir / "label_excerpts.json").read_text(encoding="utf-8"))
        labels = [
            LabelChunk(chunk_id=r["chunk_id"], drug=r["drug"], product=r["product"], text=r["text"], source=r["source"])
            for r in raw
        ]
        return cls(rules, labels)

    def drugs(self) -> list[str]:
        return list(self._rules)

    def rule(self, drug: str) -> dict:
        return self._rules[drug]

    def label_chunks(self, drug: str) -> list[LabelChunk]:
        return [c for c in self._labels if c.drug == drug]

    def all_labels(self) -> list[LabelChunk]:
        return list(self._labels)
