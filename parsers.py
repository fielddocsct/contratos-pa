import re
from io import BytesIO
from PIL import Image, ImageOps
import pytesseract
from pypdf import PdfReader


def _bytes(f):
    if hasattr(f, "getvalue"): return f.getvalue()
    if hasattr(f, "read"): return f.read()
    return open(f, "rb").read()


def _is_pdf(data):
    return data[:4] == b"%PDF"


def _pdf_first_page_image(data):
    import subprocess, tempfile, glob, os
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        open(src, "wb").write(data)
        subprocess.run(["pdftoppm", "-r", "250", "-l", "1", "-png", src, os.path.join(tmp, "p")],
                       check=True, stderr=subprocess.DEVNULL)
        return Image.open(sorted(glob.glob(os.path.join(tmp, "p*.png")))[0]).copy()


def _ocr_image(img, passes=("6", "4", "11")):
    """OCR de una foto con varias configuraciones; une los textos (la 1ra manda)."""
    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)
    if img.width < 2400:
        k = 2400 / img.width
        img = img.resize((int(img.width * k), int(img.height * k)))
    return "\n".join(pytesseract.image_to_string(img, config=f"--psm {p}") for p in passes)


def read_id(image_file):
    """OCR de la foto del ID. Devuelve dict con lo que logre encontrar."""
    data = _bytes(image_file)
    img = _pdf_first_page_image(data) if _is_pdf(data) else Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)
    img = img.resize((img.width * 2, img.height * 2)) if img.width < 1600 else img
    text = pytesseract.image_to_string(img, config="--psm 6")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = {"raw": text, "license": "", "dob": "", "name": "", "address": ""}
    m = re.search(r"\b(\d{9})\b", text)
    if m: out["license"] = m.group(1)
    m = re.search(r"DOB\W*(\d{2}/\d{2}/\d{4})", text)
    if m: out["dob"] = m.group(1)
    # Direccion: linea de calle + linea "CIUDAD, ST 0xxxx"; nombre: las 2 lineas anteriores
    street_re = r"\d+\s+[A-Za-z]+\s+(?:ST|AVE|RD|DR|LN|BLVD|CT|WAY|PL|CIR|TER)\b"
    word_re = r"[A-Z][A-Z\-']{2,}(?:\s+[A-Z][A-Z\-']{2,})*\s*$"
    for i, l in enumerate(lines):
        sm = re.search(street_re, l, re.I)
        if sm and i >= 2 and i + 1 < len(lines):
            cm = re.search(r"([A-Z]{3,}(?:\s[A-Z]+)*),\s*([A-Z]{2})\s+(\d{5})", lines[i + 1])
            if cm:
                city = re.sub(r"^(?:[A-Z]{1,3}\s+)+", "", cm.group(1))  # quita basura del OCR
                out["address"] = f"{sm.group(0).title()}, {city.title()}, {cm.group(2)} {cm.group(3)}"
            parts = []
            for prev in (lines[i - 1], lines[i - 2]):  # nombre, apellido
                wm = re.search(word_re, prev)
                parts.append(wm.group(0).title() if wm else "")
            out["name"] = " ".join(p for p in parts if p).strip()
            break
    return out


def _flip_name(n):
    """'DE TORRES, SARA' -> 'Sara De Torres'"""
    n = n.strip()
    if "," in n:
        last, first = [x.strip() for x in n.split(",", 1)]
        n = f"{first} {last}"
    return n.title()


_SUF = r"(?:ST|STREET|AVE|AVENUE|RD|ROAD|DR|DRIVE|LN|LANE|BLVD|CT|COURT|WAY|PL|PLACE|CIR|TER|HWY)"


def _clean_policy(p):
    p = p.strip("-")
    # State Farm: el 2do grupo son 2 letras; el OCR confunde Q con 0
    return re.sub(r"^(\d{2})-[0O]([A-Z])-", r"\1-Q\2-", p)


def _parse_dec(text):
    out = {"policy": "", "carrier": "", "insured": "", "address": ""}
    m = re.search(r"Policy\s*Number:?\s*([A-Z0-9\-]*\d[A-Z0-9\-]*)", text, re.I)
    if m: out["policy"] = _clean_policy(m.group(1))
    m = re.search(r"Underwritten By:\s*(.+)", text)
    if m:
        out["carrier"] = m.group(1).strip()
    else:
        m = re.search(r"(State Farm[A-Za-z ]*?Company|[A-Z][A-Za-z&.]+(?: [A-Z][A-Za-z&.]+)* Insurance Company)", text)
        if m: out["carrier"] = re.sub(r"\s+", " ", m.group(1)).strip()
    if not out["carrier"] and re.search(r"State\s*Farm", text, re.I):
        out["carrier"] = "State Farm Fire and Casualty Company"
    # Nombre: "Named Insured: X" / "Insured Name: X" / linea MAYUSCULAS "APELLIDO, NOMBRE"
    m = re.search(r"Insured Name:\s*(.+)", text, re.I) or re.search(r"Named Insured:\s*\n?\s*([A-Za-z][^\n]+)", text, re.I)
    name = m.group(1).strip() if m else ""
    if not name:
        m = re.search(r"^([A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)*, [A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)*)\s*$", text, re.M)
        name = m.group(1) if m else ""
    name = " ".join(w for w in name.split() if not re.search(r"\d", w))  # quita basura numerica del OCR
    if name: out["insured"] = _flip_name(name) if "," in name else name
    m = re.search(r"^[A-Z][A-Z'\- ]+, [A-Z][A-Z'\- ]+\n(\d+ [^\n]+)\n([A-Z][A-Z ]+?)\s+([A-Z]{2})\s+(\d{5})", text, re.M)
    if m:
        out["address"] = f"{m.group(1).title()}, {m.group(2).title()}, {m.group(3)} {m.group(4)}"
        return out
    # Direccion de la propiedad: calle + "CIUDAD ST ZIP" despues de "Residence Premises"
    i = text.lower().find("residence premises")
    seg = text[i:] if i >= 0 else text
    sm = re.search(r"(\d+\s+[A-Za-z0-9.']+(?:\s+[A-Za-z0-9.']+)?\s+" + _SUF + r")\b", seg, re.I)
    if sm:
        rest = seg[sm.end():]
        cm = re.search(r"([A-Za-z][A-Za-z ]+?),?\s+([A-Z]{2})\s+(\d{5})", rest)
        if cm:
            street, city = sm.group(1).strip(), cm.group(1).strip()
            if street.isupper(): street = street.title()
            if city.isupper(): city = city.title()
            out["address"] = f"{street}, {city}, {cm.group(2)} {cm.group(3)}"
    return out


def policy_candidates(text):
    """Posibles numeros de poliza leidos en el texto (mejor primero), sin repetir."""
    found = []
    # State Farm: 07-QB-F315-6
    found += re.findall(r"\b\d{2}-[A-Z0-9]{2}-[A-Z0-9]{3,5}-\d\b", text)
    # Cerca de "Policy Number / Policy No / Policy #"
    for m in re.finditer(r"Policy\s*(?:Number|No\.?|#)[:\s]*", text, re.I):
        win = text[m.end(): m.end() + 120]
        for tok in re.findall(r"[A-Z0-9][A-Z0-9\-]{5,17}", win):
            if (re.search(r"\d", tok) and "/" not in tok
                    and not re.fullmatch(r"\d{3}-?\d{3}-?\d{4}", tok)      # telefono
                    and not re.fullmatch(r"\d{5}(-\d{4})?", tok)            # codigo postal
                    and not re.match(r"H-\d{2}-", tok)                      # codigo de etiqueta
                    and not (tok.isdigit() and not 8 <= len(tok) <= 12)):
                found.append(tok)
    out = []
    for f in found:
        f = _clean_policy(f)
        if f not in out:
            out.append(f)
    return out[:6]


def _complete(d):
    return bool(d["policy"] and d["insured"] and d["address"])


def _ocr_pdf(pdf_bytes, pages=3):
    """Convierte las primeras paginas a imagen (pdftoppm) y les pasa OCR."""
    import subprocess, tempfile, glob, os
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        open(src, "wb").write(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "200", "-l", str(pages), "-png", src, os.path.join(tmp, "p")], check=True, stderr=subprocess.DEVNULL)
        text = ""
        for f in sorted(glob.glob(os.path.join(tmp, "p*.png"))):
            img = ImageOps.autocontrast(Image.open(f).convert("L"))
            text += pytesseract.image_to_string(img, config="--psm 6") + "\n"
    return text


def _finish(out, text, unverified):
    cands = policy_candidates(text)
    if out["policy"] and out["policy"] not in cands:
        cands.insert(0, out["policy"])
    out["candidates"] = cands[:6]
    if not out["policy"] and out["candidates"]:
        out["policy"] = out["candidates"][0]  # mejor lectura, aunque sea imperfecta
    out["policy_unverified"] = unverified
    return out


def read_declaration(pdf_file):
    """Acepta PDF (digital o escaneado) o foto. Si el PDF no tiene texto util, usa OCR."""
    data = _bytes(pdf_file)
    if not _is_pdf(data):  # foto de la poliza
        text = _ocr_image(Image.open(BytesIO(data)))
        out = _parse_dec(text)
        out["method"] = "OCR (foto)"
        return _finish(out, text, True)
    reader = PdfReader(BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages[:3])
    out = _parse_dec(text)
    out["method"] = "texto del PDF"
    if _complete(out):
        return _finish(out, text, False)
    ocr_text = _ocr_pdf(data)
    ocr = _parse_dec(ocr_text)
    ocr["method"] = "OCR (PDF escaneado o con texto danado)"
    for k in ("policy", "carrier", "insured", "address"):
        ocr[k] = ocr[k] or out[k]
    return _finish(ocr, ocr_text, True)
