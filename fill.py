from io import BytesIO
from pypdf import PdfReader, PdfWriter


def fill_contract(template_path, values):
    """values: {nombre_del_campo_en_el_PDF: texto}"""
    reader = PdfReader(template_path)
    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        if page.get("/Annots"):
            writer.update_page_form_field_values(page, values, auto_regenerate=False)
    writer.set_need_appearances_writer(True)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()
