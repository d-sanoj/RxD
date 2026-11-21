"""Per-drug rules with their label chunks and verification status."""

from app.models.catalog import RulesCatalog


def list_rules(catalog: RulesCatalog) -> list[dict]:
    items = []
    for drug in catalog.drugs():
        rule = catalog.rule(drug)
        verified_by = rule.get("verified_by")
        items.append({
            "drug": drug,
            "product": rule["product"],
            "measure": rule["measure"],
            "source": rule["source"],
            "verified_by": verified_by,
            "verified": bool(verified_by),
            "chunks": [{"chunk_id": c.chunk_id, "text": c.text} for c in catalog.label_chunks(drug)],
        })
    return items
