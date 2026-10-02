"""Collect ten CC-BY JMLR papers; PDFs remain byte-for-byte unmodified."""
import hashlib
import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://jmlr.org"


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "FreeRead-M0-fixture-curation"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def collect():
    html = download(BASE + "/papers/v25/").decode()
    links = list(dict.fromkeys(re.findall(r"href=['\"]([^'\"]+\.pdf)['\"]", html)))[:10]
    if len(links) != 10:
        raise ValueError("Expected ten JMLR PDF links")
    entries = []
    for link in links:
        source = urllib.parse.urljoin(BASE + "/papers/v25/", link)
        identifier = "jmlr-" + Path(link).stem
        target = ROOT / "fixtures" / "golden" / identifier
        target.mkdir(parents=True, exist_ok=True)
        pdf = download(source)
        paper = target / "paper.pdf"
        paper.write_bytes(pdf)
        reader = PdfReader(paper)
        first = reader.pages[0].extract_text()
        license_match = re.search(r"creativecommons\.org/licenses/by/([0-9.]+)", first)
        if not license_match:
            raise ValueError(f"Missing explicit CC-BY evidence: {identifier}")
        license_id = "CC-BY-" + license_match[1].rstrip(".")
        if license_id != "CC-BY-4.0":
            raise ValueError(f"Unexpected license: {license_id}")
        bib_url = BASE + "/papers/v25/" + Path(link).stem + ".bib"
        bib = download(bib_url).decode()
        title = re.search(r"title\s*=\s*\{(.*?)\},", bib, re.S)
        authors = re.search(r"author\s*=\s*\{(.*?)\},", bib, re.S)
        if not title or not authors:
            raise ValueError(f"Missing attribution: {identifier}")
        entry = {"id": identifier, "file": identifier + "/paper.pdf",
                 "category": "formula-heavy", "source": source, "license": license_id,
                 "licenseEvidence": "paper.pdf page 1: https://creativecommons.org/licenses/by/4.0/",
                 "sha256": hashlib.sha256(pdf).hexdigest(), "pages": len(reader.pages),
                 "title": " ".join(title[1].split()), "authors": authors[1].split(" and "),
                 "annotationStatus": "pending-M2", "downloadedAt": "2026-10-03"}
        entries.append(entry)
        (target / "attribution.bib").write_text(bib, encoding="utf-8")
        print(identifier, len(reader.pages), license_id, flush=True)
        time.sleep(1)
    (ROOT / "fixtures/golden/index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    collect()
