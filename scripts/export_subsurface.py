#!/usr/bin/env python3
"""Export dive sites from data/osm_clean/{slug}.json to a Subsurface divesite XML file.

Subsurface's own dive-site export format (see core/save-xml.cpp: save_one_dive_site)
is XML, not CSV -- there is no native CSV import for standalone dive sites. This
generates that same format so it can be loaded via File > Import > Divesites (or
File > Open, for a sites-only .ssrf/.xml) in Subsurface.

Usage:
    python3 scripts/export_subsurface.py grenada
    python3 scripts/export_subsurface.py grenada bonaire curacao -o out/caribbean.xml
    python3 scripts/export_subsurface.py --all
"""

import argparse
import json
import sys
import zlib
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "osm_clean"
DESTINATIONS_FILE = REPO_ROOT / "destinations.json"


def all_slugs() -> list[str]:
    with DESTINATIONS_FILE.open(encoding="utf-8") as f:
        destinations = json.load(f)
    return [d["slug"] for d in destinations if (DATA_DIR / f"{d['slug']}.json").exists()]


def load_sites(slug: str) -> list[dict]:
    path = DATA_DIR / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No data file at {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("sites", [])
    return data


def make_uuid(slug: str, name: str, used: set[str]) -> str:
    """Deterministic 8-hex-digit id, matching Subsurface's uuid attribute width.

    Keyed on slug + name (not list position) so a site keeps its id across
    re-exports. Subsurface uuids are only 32 bits, so collisions are possible
    over thousands of sites; on a clash, rehash with a counter suffix.
    """
    attempt = 0
    while True:
        key = f"{slug}:{name}" + (f":{attempt}" if attempt else "")
        uuid = f"{zlib.crc32(key.encode('utf-8')) & 0xFFFFFFFF:08x}"
        if uuid not in used and uuid != "00000000":
            used.add(uuid)
            return uuid
        attempt += 1


def format_gps(lat: float, lon: float) -> str:
    # Matches core/membuffer.cpp put_degrees(): signed, 6 decimal places, space-separated.
    return f"{lat:.6f} {lon:.6f}"


def build_notes(site: dict) -> str:
    parts = []
    site_type = site.get("site_type")
    if site_type:
        parts.append(f"Type: {site_type}")
    depth = site.get("depth")
    if depth:
        parts.append(f"Max depth: {depth}m")
    difficulty = site.get("difficulty")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}")
    entry_type = site.get("entry_type")
    if entry_type:
        parts.append(f"Entry: {entry_type}")
    return " | ".join(parts)


def site_to_xml(site: dict, slug: str, used: set[str]) -> str:
    name = site.get("name", "").strip()
    lat = site.get("lat")
    lon = site.get("lon")
    if not name or lat is None or lon is None:
        return ""

    uuid = make_uuid(slug, name, used)
    lines = [f"<site uuid={quoteattr(uuid)}"]
    lines.append(f" name={quoteattr(name)}")
    lines.append(f" gps={quoteattr(format_gps(lat, lon))}")
    lines.append(">\n")

    notes = build_notes(site)
    if notes:
        lines.append(f"  <notes>{escape(notes)}</notes>\n")

    lines.append("</site>\n")
    return "".join(lines)


def build_document(sites_by_slug: dict[str, list[dict]]) -> str:
    body = []
    used: set[str] = set()
    for slug, sites in sites_by_slug.items():
        for site in sites:
            xml = site_to_xml(site, slug, used)
            if xml:
                body.append(xml)

    return (
        "<divelog program='dive-vibe-community' version='3'>\n"
        "<divesites>\n"
        + "".join(body)
        + "</divesites>\n"
        "</divelog>\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="Destination slug(s), e.g. 'grenada'")
    parser.add_argument("--all", action="store_true", help="Export every destination")
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: out/{slug}_divesites.xml for one slug, "
        "out/all_divesites.xml for --all, out/divesites.xml otherwise)",
    )
    args = parser.parse_args()

    if args.all == bool(args.slugs):
        parser.error("pass one or more slugs, or --all (not both)")

    slugs = all_slugs() if args.all else args.slugs

    sites_by_slug = {}
    for slug in slugs:
        try:
            sites = load_sites(slug)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        if not sites:
            print(f"Warning: no sites found for '{slug}'", file=sys.stderr)
            continue
        sites_by_slug[slug] = sites

    if not sites_by_slug:
        print("Error: no sites to export", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    elif args.all:
        output_path = REPO_ROOT / "out" / "all_divesites.xml"
    elif len(slugs) == 1:
        output_path = REPO_ROOT / "out" / f"{slugs[0]}_divesites.xml"
    else:
        output_path = REPO_ROOT / "out" / "divesites.xml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = build_document(sites_by_slug)
    output_path.write_text(document, encoding="utf-8")

    written = document.count("<site ")
    print(f"Wrote {written} dive site(s) to {output_path}")


if __name__ == "__main__":
    main()
