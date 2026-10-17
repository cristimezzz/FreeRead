"""在 .engines/docling 环境中运行 Docling（版面 + 表格结构 + 公式 LaTeX 增强 + 自动 OCR）。

用法：.engines/docling/Scripts/python scripts/engines/run_docling.py <pdf> <out_dir>
输出：out_dir/docling.json（DoclingDocument 导出）、out_dir/engine.json
"""

import argparse
import importlib.metadata
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--no-formula", action="store_true", help="关闭公式 LaTeX 增强（较慢）")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    opts.do_formula_enrichment = not a.no_formula
    opts.generate_picture_images = False
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    res = conv.convert(a.pdf)
    data = res.document.export_to_dict()
    (out / "docling.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / "engine.json").write_text(
        json.dumps(
            {
                "engine": "docling",
                "engine_version": importlib.metadata.version("docling"),
                "formula_enrichment": not a.no_formula,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
