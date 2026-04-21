from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse


INVALID_CHARS = '<>:"/\\|?*'
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unzip MinerU zip files and reorganize by first H1 title with safe Windows filenames."
    )
    parser.add_argument("--zip-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def sanitize_windows_name(name: str, fallback: str = "untitled") -> str:
    text = re.sub(r"\s+", " ", (name or "").strip())
    text = "".join("_" if c in INVALID_CHARS else c for c in text)
    text = text.rstrip(" .")
    if not text:
        text = fallback
    if text.upper() in RESERVED_NAMES:
        text = f"_{text}"
    return text[:180].rstrip(" .")


def unique_name(base: str, used_keys: set[str]) -> str:
    key = base.casefold()
    if key not in used_keys:
        used_keys.add(key)
        return base
    idx = 2
    while True:
        cand = f"{base}_{idx}"
        ckey = cand.casefold()
        if ckey not in used_keys:
            used_keys.add(ckey)
            return cand
        idx += 1


def first_h1(md_text: str) -> str:
    for line in md_text.splitlines():
        m = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return ""


def is_remote_url(link: str) -> bool:
    parsed = urlparse(link)
    return parsed.scheme.lower() in {"http", "https", "mailto", "ftp", "data"}


def rewrite_md_links(md_text: str, doc_name: str) -> str:
    image_prefixes = ("images/", "./images/", "../images/")

    def repl_md_link(match: re.Match[str]) -> str:
        alt = match.group(1)
        link = match.group(2).strip()
        if is_remote_url(link) or link.startswith("#"):
            return match.group(0)
        link_body = link.split("#", 1)[0].split("?", 1)[0]
        if link_body.lower().startswith(image_prefixes):
            suffix = re.sub(r"^(?:\./|\.\./)*images/", "", link_body, flags=re.IGNORECASE)
            new_link = f"../images/{doc_name}/{suffix.replace('\\', '/')}"
            if "?" in link:
                new_link += "?" + link.split("?", 1)[1]
            if "#" in link:
                new_link += "#" + link.split("#", 1)[1]
            return f"![{alt}](<{new_link}>)"
        return match.group(0)

    def repl_html_img(match: re.Match[str]) -> str:
        src = match.group(1).strip()
        if is_remote_url(src):
            return match.group(0)
        src_body = src.split("#", 1)[0].split("?", 1)[0]
        if src_body.lower().startswith(image_prefixes):
            suffix = re.sub(r"^(?:\./|\.\./)*images/", "", src_body, flags=re.IGNORECASE)
            new_src = f"../images/{doc_name}/{suffix.replace('\\', '/')}"
            return match.group(0).replace(src, new_src)
        return match.group(0)

    out = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl_md_link, md_text)
    out = re.sub(r'<img[^>]*\ssrc=["\']([^"\']+)["\'][^>]*>', repl_html_img, out, flags=re.IGNORECASE)
    return out


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> None:
    args = parse_args()
    zip_dir = args.zip_dir.resolve()
    out_dir = args.out_dir.resolve()

    md_dir = out_dir / "markdown"
    pdf_dir = out_dir / "pdf"
    json_dir = out_dir / "json"
    img_dir = out_dir / "images"
    for p in (md_dir, pdf_dir, json_dir, img_dir):
        p.mkdir(parents=True, exist_ok=True)

    used_name_keys: set[str] = set()
    rows: list[dict[str, str]] = []
    zips = sorted(zip_dir.glob("*.zip"))
    if not zips:
        raise RuntimeError(f"no zip files found in {zip_dir}")

    for idx, zip_path in enumerate(zips, start=1):
        with tempfile.TemporaryDirectory(prefix="mineru_unzip_") as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_path)

            md_path = tmp_path / "full.md"
            md_text = md_path.read_text(encoding="utf-8", errors="replace") if md_path.exists() else ""
            title = first_h1(md_text)
            raw_name = sanitize_windows_name(title or zip_path.stem, fallback=zip_path.stem)
            doc_name = unique_name(raw_name, used_name_keys)

            rewritten = rewrite_md_links(md_text, doc_name)
            out_md = md_dir / f"{doc_name}.md"
            out_md.write_text(rewritten, encoding="utf-8")

            origin_pdf = None
            pdf_candidates = sorted(tmp_path.glob("*_origin.pdf"))
            if pdf_candidates:
                origin_pdf = pdf_candidates[0]
            else:
                fallback_pdfs = sorted(tmp_path.glob("*.pdf"))
                if fallback_pdfs:
                    origin_pdf = fallback_pdfs[0]
            if origin_pdf is not None:
                copy_if_exists(origin_pdf, pdf_dir / f"{doc_name}.pdf")

            src_images = tmp_path / "images"
            if src_images.exists():
                target_images = img_dir / doc_name
                if target_images.exists():
                    shutil.rmtree(target_images)
                shutil.copytree(src_images, target_images)

            for j in sorted(tmp_path.glob("*.json")):
                copy_if_exists(j, json_dir / f"{doc_name}__{j.name}")

            rows.append(
                {
                    "zip": str(zip_path),
                    "doc_name": doc_name,
                    "title": title,
                    "markdown": str(out_md),
                    "pdf": str((pdf_dir / f"{doc_name}.pdf")) if (pdf_dir / f"{doc_name}.pdf").exists() else "",
                    "images_dir": str((img_dir / doc_name)) if (img_dir / doc_name).exists() else "",
                }
            )
            if idx % 100 == 0:
                print(f"processed {idx}/{len(zips)}")

    manifest = out_dir / "index.tsv"
    lines = ["zip\tdoc_name\ttitle\tmarkdown\tpdf\timages_dir"]
    for r in rows:
        lines.append(
            "\t".join(
                [
                    r["zip"],
                    r["doc_name"],
                    r["title"].replace("\t", " "),
                    r["markdown"],
                    r["pdf"],
                    r["images_dir"],
                ]
            )
        )
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done: {len(rows)} docs")
    print(f"output: {out_dir}")
    print(f"index: {manifest}")


if __name__ == "__main__":
    main()
