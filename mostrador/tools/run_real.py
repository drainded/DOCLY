"""
tools/run_real.py
===================
Ejecuta engine.core.pipeline.run() sobre documentos reales (sin pasar por la
web) y deja un informe por corrida. Usa las claves de .env (via
webapp.config), asi que HACE LLAMADAS REALES a Gemini: el contenido de cada
documento sale hacia ese servicio (ver aviso de privacidad, spec seccion 9).

Uso (desde mostrador/)::

    ../.venv/Scripts/python.exe tools/run_real.py RUTA [RUTA ...] [--styles apa ieee]
                                                   [--out ../real_runs] [--pause 6]

RUTA puede ser un .docx/.doc o una carpeta (se procesan sus .docx/.doc, sin
recursion). Cada documento se procesa una vez por estilo. Si el pipeline
pausa por estilos conflictivos (spec seccion 7), se reintenta con
overwrite_styles=True salvo que se pase --no-overwrite.

Salida en --out/<marca-de-tiempo>/: .docx y .png de cada corrida, run.log
(logs del motor) y report.md con una fila por corrida.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import docx  # noqa: E402

from engine.core import pipeline  # noqa: E402
from engine.document.models import FormatStyle, ProcessingResult  # noqa: E402
from engine.document.xsd_validator import validate_docx_against_xsd  # noqa: E402
from webapp.config import load_processing_config  # noqa: E402

_ACCEPTED = {".docx", ".doc"}
_MAX_MISSING_SHOWN = 5


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    documents = _collect_documents(args.paths)
    if not documents:
        print("No se encontraron .docx/.doc en las rutas dadas.")
        return 2

    out_dir = args.out / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=out_dir / "run.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8",
    )

    rows: list[dict] = []
    runs = [(doc, FormatStyle(style)) for doc in documents for style in args.styles]
    for number, (doc, style) in enumerate(runs, start=1):
        print(f"[{number}/{len(runs)}] {doc.name} -> {style.value} ...", flush=True)
        rows.append(_run_one(doc, style, out_dir, overwrite=not args.no_overwrite))
        print(f"    {rows[-1]['status']}  ({rows[-1]['seconds']:.1f}s)", flush=True)
        if number < len(runs):
            time.sleep(args.pause)  # respeta el limite por minuto del tier gratuito (spec seccion 9)

    report = _render_report(rows)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Resultados en: {out_dir}")
    return 0 if all(row["ok"] for row in rows) else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prueba el pipeline con documentos reales (usa Gemini real).")
    parser.add_argument("paths", nargs="+", type=Path, help=".docx/.doc o carpetas")
    parser.add_argument("--styles", nargs="+", default=[s.value for s in FormatStyle],
                        choices=[s.value for s in FormatStyle])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "real_runs")
    parser.add_argument("--pause", type=float, default=6.0, help="segundos entre corridas (default 6)")
    parser.add_argument("--no-overwrite", action="store_true",
                        help="no reintentar con overwrite_styles=True ante estilos conflictivos")
    return parser.parse_args(argv)


def _collect_documents(paths: list[Path]) -> list[Path]:
    documents: list[Path] = []
    for path in paths:
        if path.is_dir():
            documents.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in _ACCEPTED))
        elif path.suffix.lower() in _ACCEPTED and path.exists():
            documents.append(path)
    return documents


def _run_one(doc: Path, style: FormatStyle, out_dir: Path, overwrite: bool) -> dict:
    config = load_processing_config(style=style)
    config.output_dir = out_dir / f"{doc.stem}_{style.value}"

    started = time.perf_counter()
    result = pipeline.run(doc, config)
    paused = result.error_code == "CONFLICTING_STYLES"
    if paused and overwrite:
        result = pipeline.run(doc, config, overwrite_styles=True)
    seconds = time.perf_counter() - started

    row = {
        "document": doc.name, "style": style.value, "seconds": seconds,
        "ok": result.success, "paused": paused,
        "status": "OK" if result.success else f"ERROR {result.error_code}",
        "message": "" if result.success else (result.error_message or ""),
        "fallback": result.fallback_used, "rate_limited": result.gemini_rate_limited,
        "preview": result.preview_path is not None,
        "headings": result.doc_meta.heading_count if result.doc_meta else None,
        "language": result.doc_meta.detected_language.value if result.doc_meta else None,
        "xsd": None, "missing": [],
    }
    if result.success:
        row["xsd"] = len(validate_docx_against_xsd(result.output_docx_path))
        if doc.suffix.lower() == ".docx":
            row["missing"] = _missing_text(doc, result.output_docx_path)
    return row


def _document_texts(path: Path) -> list[str]:
    document = docx.Document(path)
    texts = [p.text for p in document.paragraphs]
    for table in document.tables:
        texts.extend(cell.text for row in table.rows for cell in row.cells)
    return [" ".join(text.split()) for text in texts if text.strip()]


def _missing_text(original: Path, output: Path) -> list[str]:
    """Textos del original que no aparecen en la salida (spec seccion 6: sin perdida de contenido)."""
    produced = "\n".join(_document_texts(output))
    return [text for text in _document_texts(original) if text not in produced]


def _render_report(rows: list[dict]) -> str:
    lines = [
        "# Informe de corridas reales", "",
        "| Documento | Estilo | Resultado | Seg | Idioma | Headings | XSD | Preview | Fallback | Texto perdido |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        xsd = "-" if r["xsd"] is None else ("OK" if r["xsd"] == 0 else f"{r['xsd']} errores")
        lines.append(
            f"| {r['document']} | {r['style']} | {r['status']}{' (tras confirmar estilos)' if r['paused'] and r['ok'] else ''} "
            f"| {r['seconds']:.1f} | {r['language'] or '-'} | {r['headings'] if r['headings'] is not None else '-'} "
            f"| {xsd} | {'si' if r['preview'] else 'no'} | {'si' if r['fallback'] else 'no'} "
            f"| {len(r['missing'])} |"
        )
    problems = [r for r in rows if not r["ok"] or r["missing"]]
    if problems:
        lines += ["", "## Detalle de problemas", ""]
        for r in problems:
            lines.append(f"### {r['document']} ({r['style']})")
            if not r["ok"]:
                lines.append(f"- {r['status']}: {r['message']}")
            for text in r["missing"][:_MAX_MISSING_SHOWN]:
                lines.append(f"- Falta en la salida: `{text[:100]}`")
            if len(r["missing"]) > _MAX_MISSING_SHOWN:
                lines.append(f"- ... y {len(r['missing']) - _MAX_MISSING_SHOWN} mas")
            lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
