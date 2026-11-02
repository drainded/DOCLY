"""
tests/formatting/test_apa_layout.py
=====================================
Maquetacion APA 7 por tipo de documento (template_engine.apply_template +
docx_builder.build_docx con `apa_layout`).
"""

import docx
import pytest
from docx.oxml.ns import qn

from engine.document.models import DocumentType, FormatStyle, SemanticBlock, SemanticRole
from engine.formatting import section_titles, template_engine
from engine.formatting.docx_builder import build_docx

TITLE = "Efectos de la desinformacion en la memoria"


def _b(index, role, text="", **kwargs) -> SemanticBlock:
    return SemanticBlock(index=index, role=role, text=text, **kwargs)


def _h1(index, text) -> SemanticBlock:
    return _b(index, SemanticRole.HEADING1, text, heading_level=1)


def _student_blocks(with_abstract=True, repeated_title=True) -> list[SemanticBlock]:
    blocks = [
        _b(0, SemanticRole.COVER_TITLE, TITLE),
        _b(1, SemanticRole.COVER_AUTHOR, "Ana Perez"),
        _b(2, SemanticRole.COVER_INSTITUTION, "Universidad X"),
        _b(3, SemanticRole.COVER_COURSE, "PSY 101"),
        _b(4, SemanticRole.COVER_INSTRUCTOR, "Dr. Gil"),
        _b(5, SemanticRole.COVER_DATE, "1 de mayo de 2025"),
    ]
    if with_abstract:
        blocks += [_h1(6, "Abstract"), _b(7, SemanticRole.ABSTRACT, "Resumen del trabajo."),
                   _b(8, SemanticRole.KEYWORDS, "Keywords: memoria, recuerdo")]
    if repeated_title:
        blocks.append(_h1(9, TITLE))
    blocks += [_b(10, SemanticRole.BODY, "Texto principal."), _h1(11, "References"),
               _b(12, SemanticRole.REFERENCE, "Autor, A. (2020). Obra.")]
    return blocks


def _apply(blocks, document_type=DocumentType.STUDENT_PAPER):
    return template_engine.apply_template(blocks, FormatStyle.APA, document_type)


def _breaks(blocks):
    return {b.text: b.page_break_before for b in blocks if b.page_break_before}


class TestApaStructure:
    def test_abstract_repeated_title_and_references_start_new_pages(self):
        result = _apply(_student_blocks())

        assert _breaks(result) == {"Abstract": True, TITLE: True, "References": True}
        assert not any(b.synthetic for b in result)

    def test_title_is_repeated_when_the_document_does_not_repeat_it(self):
        result = _apply(_student_blocks(repeated_title=False))

        synthetic = [b for b in result if b.synthetic]
        assert [(b.role, b.text, b.page_break_before) for b in synthetic] == [
            (SemanticRole.HEADING1, TITLE, True),
        ]
        assert result[result.index(synthetic[0]) + 1].text == "Texto principal."

    def test_title_is_inserted_after_the_abstract_not_before_it(self):
        result = _apply(_student_blocks(repeated_title=False))

        order = [b.text for b in result if not b.is_cover_field()]
        assert order.index("Keywords: memoria, recuerdo") < order.index(TITLE) < order.index("Texto principal.")

    def test_paper_without_cover_gets_no_title_and_no_leading_break(self):
        result = _apply([_h1(0, "Introduccion"), _b(1, SemanticRole.BODY, "Texto.")])

        assert not any(b.synthetic or b.page_break_before for b in result)

    def test_professional_author_note_stays_on_the_title_page(self):
        blocks = [
            _b(0, SemanticRole.COVER_TITLE, TITLE),
            _b(1, SemanticRole.COVER_AUTHOR, "Ana Perez"),
            _h1(2, "Author Note"),
            _b(3, SemanticRole.AUTHOR_NOTE, "Sin conflictos de interes."),
            _h1(4, "Abstract"),
            _b(5, SemanticRole.ABSTRACT, "Resumen."),
            _b(6, SemanticRole.BODY, "Texto."),
        ]

        result = _apply(blocks, DocumentType.PROFESSIONAL_PAPER)

        assert _breaks(result) == {"Abstract": True, TITLE: True}

    def test_title_left_as_heading_becomes_the_cover_title(self):
        blocks = [
            _h1(0, TITLE),
            _b(1, SemanticRole.COVER_AUTHOR, "Ana Perez"),
            _b(2, SemanticRole.COVER_INSTITUTION, "Universidad X"),
            _h1(3, "Author Note"),
            _b(4, SemanticRole.AUTHOR_NOTE, "Sin conflictos."),
            _h1(5, "Abstract"),
            _b(6, SemanticRole.ABSTRACT, "Resumen."),
            _h1(7, TITLE),
            _b(8, SemanticRole.BODY, "Texto."),
        ]

        result = _apply(blocks, DocumentType.PROFESSIONAL_PAPER)

        assert [b.role for b in result[:3]] == [
            SemanticRole.COVER_TITLE, SemanticRole.COVER_AUTHOR, SemanticRole.COVER_INSTITUTION,
        ]
        assert _breaks(result) == {"Abstract": True, TITLE: True}

    def test_two_line_title_left_as_headings_is_kept_together_and_repeated(self):
        blocks = [
            _h1(0, "Primera linea del titulo:"),
            _h1(1, "Segunda linea"),
            _b(2, SemanticRole.COVER_AUTHOR, "Ana Perez"),
            _b(3, SemanticRole.BODY, "Texto."),
        ]

        result = _apply(blocks, DocumentType.PROFESSIONAL_PAPER)

        assert [(b.role, b.text, b.synthetic) for b in result] == [
            (SemanticRole.COVER_TITLE, "Primera linea del titulo:", False),
            (SemanticRole.COVER_TITLE, "Segunda linea", False),
            (SemanticRole.COVER_AUTHOR, "Ana Perez", False),
            (SemanticRole.HEADING1, "Primera linea del titulo:", True),
            (SemanticRole.HEADING1, "Segunda linea", True),
            (SemanticRole.BODY, "Texto.", False),
        ]
        assert [b.page_break_before for b in result if b.synthetic] == [True, False]

    def test_professional_cover_is_inferred_when_the_ia_marked_none(self):
        blocks = [
            _h1(0, TITLE),
            _b(1, SemanticRole.BODY, "Ana Perez"),
            _b(2, SemanticRole.BODY, "Departamento X, Universidad Y"),
            _h1(3, "Author Note"),
            _b(4, SemanticRole.AUTHOR_NOTE, "Sin conflictos."),
            _h1(5, "Abstract"),
            _b(6, SemanticRole.ABSTRACT, "Resumen."),
            _b(7, SemanticRole.BODY, "Texto."),
        ]

        result = _apply(blocks, DocumentType.PROFESSIONAL_PAPER)

        assert [b.role for b in result[:3]] == [
            SemanticRole.COVER_TITLE, SemanticRole.COVER_AUTHOR, SemanticRole.COVER_INSTITUTION,
        ]

    def test_student_cover_is_inferred_by_position(self):
        blocks = [_h1(0, TITLE)] + [
            _b(i, SemanticRole.BODY, text) for i, text in
            enumerate(["Ana", "Universidad X", "PSY 101", "Dr. Gil", "1 de mayo"], start=1)
        ] + [_h1(6, "Abstract"), _b(7, SemanticRole.ABSTRACT, "Resumen.")]

        result = _apply(blocks, DocumentType.STUDENT_PAPER)

        assert [b.role for b in result[:6]] == [
            SemanticRole.COVER_TITLE, SemanticRole.COVER_AUTHOR, SemanticRole.COVER_INSTITUTION,
            SemanticRole.COVER_COURSE, SemanticRole.COVER_INSTRUCTOR, SemanticRole.COVER_DATE,
        ]

    def test_long_paragraphs_before_the_abstract_are_not_taken_for_a_cover(self):
        blocks = [_h1(0, TITLE), _b(1, SemanticRole.BODY, "x" * 400), _h1(2, "Abstract")]

        result = _apply(blocks, DocumentType.PROFESSIONAL_PAPER)

        assert not any(b.is_cover_field() for b in result)

    def test_no_inference_for_other_document_types(self):
        blocks = [_h1(0, TITLE), _b(1, SemanticRole.BODY, "Ana"), _h1(2, "Abstract")]

        result = _apply(blocks, DocumentType.OTHER)

        assert not any(b.is_cover_field() for b in result)

    def test_first_reference_without_heading_starts_a_new_page(self):
        blocks = _student_blocks()
        blocks.remove(blocks[-2])  # sin heading "References"

        result = _apply(blocks)

        assert _breaks(result)["Autor, A. (2020). Obra."] is True

    def test_annotated_bibliography_repeats_the_title_but_adds_no_references_break(self):
        blocks = _student_blocks(with_abstract=False, repeated_title=False)[:6] + [
            _b(10, SemanticRole.REFERENCE, "Autor, A. (2020). Obra."),
            _b(11, SemanticRole.ANNOTATION, "Anotacion."),
        ]

        result = _apply(blocks, DocumentType.ANNOTATED_BIBLIOGRAPHY)

        assert [b.text for b in result if b.synthetic] == [TITLE]
        assert _breaks(result) == {TITLE: True}

    def test_appendix_starts_a_new_page(self):
        result = _apply(_student_blocks() + [_h1(13, "Appendix A")])

        assert _breaks(result)["Appendix A"] is True

    def test_ieee_is_untouched_by_the_apa_layout(self):
        result = template_engine.apply_template(_student_blocks(), FormatStyle.IEEE, DocumentType.STUDENT_PAPER)

        assert not any(b.synthetic or b.page_break_before for b in result)


class TestCaptions:
    def test_label_and_the_title_after_it_become_captions(self):
        blocks = [_b(0, SemanticRole.BODY, "Table 1"), _b(1, SemanticRole.BODY, "Medias por grupo"),
                  _b(2, SemanticRole.BODY, "Texto normal.")]

        result = _apply(blocks)

        assert [b.role for b in result] == [SemanticRole.CAPTION, SemanticRole.CAPTION, SemanticRole.BODY]

    @pytest.mark.parametrize("text", ["Table 1", "Figure 2.", "Tabla 3", "Figura A1", "Table 2.1"])
    def test_caption_labels_are_recognised(self, text):
        assert section_titles.is_caption_label(text)

    @pytest.mark.parametrize("text", ["Table 1 shows the results", "Tabla", "Figure"])
    def test_other_lines_are_not_caption_labels(self, text):
        assert not section_titles.is_caption_label(text)


class TestSectionTitles:
    @pytest.mark.parametrize("text", ["References", "Referencias", "Bibliografía", "Fuentes de información", "REFERENCES:"])
    def test_reference_titles(self, text):
        assert section_titles.is_reference_title(text)

    @pytest.mark.parametrize("text", ["Appendix", "Appendix A", "Apéndice B", "Anexo 1"])
    def test_appendix_titles(self, text):
        assert section_titles.is_appendix_title(text)

    def test_ordinary_heading_is_none_of_them(self):
        assert not any(check("Resultados") for check in (
            section_titles.is_reference_title, section_titles.is_appendix_title,
            section_titles.is_abstract_title, section_titles.is_author_note_title,
        ))


def _build(tmp_path, blocks, document_type=DocumentType.STUDENT_PAPER):
    out = tmp_path / "out.docx"
    build_docx(blocks=_apply(blocks, document_type), style=FormatStyle.APA, output_path=out,
               document_type=document_type)
    return docx.Document(out)


def _header_text(document) -> str:
    return "".join(document.sections[0].header._element.xpath(".//w:t/text()")).strip()


class TestApaBuild:
    def test_no_toc_no_color_no_separator_lines(self, tmp_path):
        document = _build(tmp_path, _student_blocks())

        assert not any(p.style.name.startswith("Mostrador toc_entry") for p in document.paragraphs)
        assert "Índice" not in [p.text for p in document.paragraphs]
        body = document.element.body
        assert not body.xpath(".//w:pBdr")
        colors = {
            color.get(qn("w:val"))
            for style in document.styles.element.xpath(".//w:style[starts-with(w:name/@w:val, 'Mostrador')]")
            for color in style.xpath(".//w:color")
        }
        assert colors == {"000000"}

    def test_page_breaks_are_applied_to_the_marked_paragraphs(self, tmp_path):
        document = _build(tmp_path, _student_blocks())

        broken = [p.text for p in document.paragraphs if p.paragraph_format.page_break_before]
        assert broken == ["Abstract", TITLE, "References"]

    def test_references_title_is_not_duplicated(self, tmp_path):
        document = _build(tmp_path, _student_blocks())

        assert [p.text for p in document.paragraphs].count("References") == 1

    def test_references_title_is_added_when_missing(self, tmp_path):
        blocks = _student_blocks()
        blocks.remove(blocks[-2])

        document = _build(tmp_path, blocks)

        assert [p.text for p in document.paragraphs].count("Referencias") == 1

    def test_annotated_bibliography_has_no_references_title_and_unindented_annotations(self, tmp_path):
        blocks = _student_blocks(with_abstract=False, repeated_title=False)[:6] + [
            _b(10, SemanticRole.REFERENCE, "Autor, A. (2020). Obra."),
            _b(11, SemanticRole.ANNOTATION, "\tAnotacion de la obra."),
        ]

        document = _build(tmp_path, blocks, DocumentType.ANNOTATED_BIBLIOGRAPHY)

        texts = [p.text for p in document.paragraphs]
        assert "Referencias" not in texts and "References" not in texts
        assert "Anotacion de la obra." in texts

    def test_page_number_header_without_running_head_for_student_paper(self, tmp_path):
        document = _build(tmp_path, _student_blocks())

        header = document.sections[0].header._element
        assert header.xpath(".//w:fldSimple[@w:instr='PAGE']")
        assert _header_text(document) == "1"

    def test_professional_paper_has_a_running_head_of_at_most_50_characters(self, tmp_path):
        long_title = "Rethinking Emotions in the Context of Infants Prosocial Behavior Role of Interest"
        blocks = [_b(0, SemanticRole.COVER_TITLE, long_title), _b(1, SemanticRole.COVER_AUTHOR, "A. Perez"),
                  _b(2, SemanticRole.BODY, "Texto.")]

        document = _build(tmp_path, blocks, DocumentType.PROFESSIONAL_PAPER)

        running_head = _header_text(document).removesuffix("1").strip()
        assert running_head and len(running_head) <= 50
        assert running_head == running_head.upper()
        assert long_title.upper().startswith(running_head)

    def test_keywords_label_is_italic_and_the_list_is_not(self, tmp_path):
        document = _build(tmp_path, _student_blocks())

        paragraph = next(p for p in document.paragraphs if p.text.startswith("Keywords"))
        assert [(run.text, run.italic) for run in paragraph.runs] == [
            ("Keywords:", True), (" memoria, recuerdo", None),
        ]

    def test_caption_label_is_bold_and_title_italic(self, tmp_path):
        blocks = [_b(0, SemanticRole.BODY, "Table 1"), _b(1, SemanticRole.BODY, "Medias por grupo")]

        document = _build(tmp_path, blocks)

        label, title = document.paragraphs[0], document.paragraphs[1]
        assert (label.runs[0].bold, title.runs[0].italic) == (True, True)

    def test_apa_table_has_only_horizontal_rules_and_no_shading(self, tmp_path):
        blocks = [
            _b(0, SemanticRole.TABLE_HEADER, "Grupo", table_id="t", row_index=0, col_index=0),
            _b(1, SemanticRole.TABLE_CELL, "A", table_id="t", row_index=1, col_index=0),
        ]

        document = _build(tmp_path, blocks)

        table = document.tables[0]._tbl
        assert table.xpath(".//w:tblBorders/w:top") and table.xpath(".//w:tblBorders/w:bottom")
        assert not table.xpath(".//w:tblBorders/w:left") and not table.xpath(".//w:shd")
        assert table.xpath(".//w:tcBorders/w:bottom")

    def test_margins_are_one_inch(self, tmp_path):
        section = _build(tmp_path, _student_blocks()).sections[0]

        assert [round(m.inches, 2) for m in (section.left_margin, section.right_margin,
                                              section.top_margin, section.bottom_margin)] == [1.0] * 4
