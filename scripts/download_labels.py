"""
OPTIONAL: download the full FDA label PDFs for the 6 RxD drugs from DailyMed, to add to the RAG store.
The POC already ships verified label excerpts in data/label_excerpts.json, so this is not required.

Usage (on your laptop):
    pip install requests
    python scripts/download_labels.py   (run from the project root)

Creates:
    data/labels/<drug>.pdf     one current label per drug
    data/labels/sources.csv    title, setid, published date and link for each label

Data source: DailyMed, U.S. National Library of Medicine (public domain).
"""

import csv
import time
from pathlib import Path

import requests

DRUGS = ["metformin", "sitagliptin", "gabapentin", "nitrofurantoin", "levofloxacin", "famotidine"]

SEARCH_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
PDF_URL = "https://dailymed.nlm.nih.gov/dailymed/downloadpdffile.cfm?setId={setid}"
LABEL_PAGE = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
HEADERS = {"User-Agent": "RxD-student-project/1.0"}
OUT = Path("data/labels")


def find_label(drug):
    """Return the first single-ingredient label whose title starts with the drug name."""
    resp = requests.get(SEARCH_URL, params={"drug_name": drug, "pagesize": 100},
                        headers=HEADERS, timeout=30)
    resp.raise_for_status()
    labels = resp.json().get("data", [])
    for label in labels:
        title = label.get("title", "").upper()
        # skip combination products such as "LOSARTAN POTASSIUM AND HYDROCHLOROTHIAZIDE"
        if title.startswith(drug.upper()) and " AND " not in title.split("[")[0]:
            return label
    return labels[0] if labels else None


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for drug in DRUGS:
        try:
            label = find_label(drug)
            if not label:
                print(f"{drug}: no label found")
                continue
            setid = label["setid"]
            pdf = requests.get(PDF_URL.format(setid=setid), headers=HEADERS, timeout=60)
            pdf.raise_for_status()
            path = OUT / f"{drug}.pdf"
            path.write_bytes(pdf.content)
            rows.append({
                "file": path.name,
                "drug": drug,
                "title": label.get("title", ""),
                "setid": setid,
                "published_date": label.get("published_date", ""),
                "link": LABEL_PAGE.format(setid=setid),
            })
            print(f"{drug}: saved {path} ({len(pdf.content) // 1024} KB)")
        except requests.RequestException as err:
            print(f"{drug}: failed ({err})")
        time.sleep(1)  # be polite to the server

    with open(OUT / "sources.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "drug", "title", "setid", "published_date", "link"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nDone: {len(rows)} labels saved, listed in {OUT / 'sources.csv'}")


if __name__ == "__main__":
    main()
