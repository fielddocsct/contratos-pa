
import os, json
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from parsers import read_id, read_declaration
from fill import fill_contract

CONTRATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contratos")

LABELS = {
    "insured": "Named insured", "phone": "Teléfono del asegurado", "email": "Email del asegurado",
    "address": "Dirección postal", "carrier": "Aseguradora", "policy": "Número de póliza",
    "claim": "Claim No. (si existe)", "loss_type": "Tipo de pérdida",
    "loss_address": "Dirección de la pérdida", "loss_date": "Fecha de la pérdida (MM/DD/AAAA)",
    "capacity": "Capacidad del firmante", "sign_date": "Fecha de firma (MM/DD/AAAA)",
    "second_name": "Nombre del segundo firmante", "second_capacity": "Capacidad del segundo firmante",
    "second_date": "Fecha de firma del segundo firmante (MM/DD/AAAA)",
}


class Blank(dict):
    def __missing__(self, k):
        return ""


def secret(name):
    try:
        return st.secrets.get(name, None)
    except Exception:
        return None


def contratos_disponibles():
    return sorted(d for d in os.listdir(CONTRATOS) if os.path.isfile(os.path.join(CONTRATOS, d, "config.json")))


def cargar(pa):
    with open(os.path.join(CONTRATOS, pa, "config.json"), encoding="utf-8") as f:
        return json.load(f)


# --- Qué contrato usa esta app: lo define el Secret PA (ej. PA = "tibbils") ---
opts = contratos_disponibles()
pa = secret("PA")
if pa and pa not in opts:
    st.set_page_config(page_title="Contratos")
    st.error(f"No existe el contrato '{pa}'. Disponibles: {', '.join(opts)}")
    st.stop()
if not pa and len(opts) == 1:
    pa = opts[0]
cfg = cargar(pa) if pa else None
st.set_page_config(page_title=cfg["title"] if cfg else "Contratos", page_icon="📄")

# Contraseña (Secret APP_PASSWORD)
pw = secret("APP_PASSWORD")
if pw and st.text_input("Contraseña", type="password") != pw:
    st.stop()

if not pa:  # sin Secret PA y con varios contratos: se elige a mano
    pa = st.selectbox("¿Para qué PA es el contrato?", opts)
    cfg = cargar(pa)

TEMPLATE = os.path.join(CONTRATOS, pa, cfg["pdf"])
form = cfg["form"]

st.title("📄 " + cfg["title"])
st.caption("Sube el ID y la declaration page. Revisa los datos y descarga el PDF. Nada se guarda en el servidor.")

c1, c2 = st.columns(2)
id_file = c1.file_uploader("ID (foto o PDF)", type=["jpg", "jpeg", "png", "pdf"])
dec_file = c2.file_uploader("Declaration page (PDF o foto)", type=["pdf", "jpg", "jpeg", "png"])

idd, dec = {}, {}
if id_file:
    with st.spinner("Leyendo ID..."):
        idd = read_id(id_file)
if dec_file:
    with st.spinner("Leyendo póliza..."):
        dec = read_declaration(dec_file)

if dec.get("method", "").startswith("OCR"):
    st.info("Esta póliza se leyó con OCR (escaneada, foto o con texto dañado). Revisa los datos con cuidado.")

if dec:
    pedidos = (("policy", "número de póliza"), ("insured", "nombre"), ("address", "dirección"), ("carrier", "aseguradora"))
    faltan = [n for k, n in pedidos if not dec.get(k) and (k in form or k in ("insured", "address"))]
    if faltan:
        st.warning("No pude leer: " + ", ".join(faltan) + ". Escríbelo a mano abajo (o sube una foto más nítida y recta).")

if idd and dec and idd["name"] and dec["insured"]:
    a = idd["name"].lower().split()[0]
    if a not in dec["insured"].lower():
        st.warning(f"El nombre del ID (**{idd['name']}**) no coincide con la póliza (**{dec['insured']}**). Verifica la ortografía.")

if idd or dec:
    st.subheader("Revisa y corrige")
    hoy = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d/%Y")
    defaults = {
        "insured": idd.get("name") or dec.get("insured", ""),
        "address": idd.get("address") or dec.get("address", ""),
        "carrier": dec.get("carrier", ""),
        "loss_address": dec.get("address") or idd.get("address", ""),
        "capacity": "Owner", "sign_date": hoy,
        "second_capacity": "Owner", "second_date": hoy,
    }
    plantillas = list(cfg["map"].values())
    second_fields = [f for f in ("second_name", "second_capacity", "second_date") if any("{" + f + "}" in t for t in plantillas)]

    # Opciones que cambian la pantalla: van FUERA del formulario
    dos = st.checkbox("Hay un segundo firmante", key=f"dos_{pa}") if second_fields else False
    unverified = bool(dec.get("policy_unverified")) and "policy" in form
    cands = dec.get("candidates", [])
    pol_default = dec.get("policy", "")
    if unverified and len(cands) > 1:
        choice = st.selectbox("Posibles números de póliza leídos", cands + ["(escribir a mano)"])
        pol_default = "" if choice == "(escribir a mano)" else choice

    # Formulario: nada se aplica hasta pulsar "Generar contrato" (así no se pierde lo que escribes)
    v, policy = Blank(), ""
    with st.form(f"datos_{pa}"):
        for k in form:
            if k == "policy":
                v[k] = policy = st.text_input(LABELS[k], pol_default, key=f"pol_{pol_default}")
                if unverified:
                    st.error("⚠️ Número de póliza sin verificar: se leyó con OCR y puede tener letras o números mal leídos (por ejemplo 0 por O, o Q por 0). Compáralo con el documento.")
            else:
                v[k] = st.text_input(LABELS[k], defaults.get(k, ""))
        if dos:
            for k in second_fields:
                v[k] = st.text_input(LABELS[k], defaults.get(k, ""))
        enviado = st.form_submit_button("Generar contrato", type="primary")

    with st.expander("Datos extra leídos (no van en el contrato)"):
        st.write(f"ID: licencia {idd.get('license', '')}  |  nacimiento {idd.get('dob', '')}")
        st.write(f"Póliza: {dec.get('policy', '')}  |  aseguradora: {dec.get('carrier', '')}")
        st.text(idd.get("raw", ""))

    # Datos derivados
    calle, _, resto = v.get("address", "").partition(",")
    v["street"], v["city_state_zip"] = calle.strip(), resto.strip()
    nombres = [x for x in (v.get("insured", ""), v.get("second_name", "")) if x.strip()]
    v["insured_all"] = " and ".join(nombres)

    firma = (pa, id_file.name if id_file else "", id_file.size if id_file else 0,
             dec_file.name if dec_file else "", dec_file.size if dec_file else 0, dos)
    if enviado:
        values = {campo: plantilla.format_map(v) for campo, plantilla in cfg["map"].items()}
        st.session_state["res"] = {
            "firma": firma, "pdf": fill_contract(TEMPLATE, values), "policy": policy,
            "nombre": f"Contrato_{(v.get('insured') or 'cliente').strip().replace(' ', '_')}.pdf",
            "vacios": [LABELS[k] for k in ("loss_type", "loss_date") if k in form and not v.get(k, "").strip()],
        }

    res = st.session_state.get("res")
    if res and res["firma"] == firma:
        st.success("Contrato generado con los datos de arriba.")
        if res["vacios"]:
            st.warning("Quedaron vacíos: " + ", ".join(res["vacios"]) + ". Si hace falta, complétalos arriba y pulsa «Generar contrato» otra vez.")
        verified = True
        if unverified:
            verified = st.checkbox("✅ Verifiqué el número de póliza contra el documento", key=f"ver_{dec_file.name}_{res['policy']}")
            if not res["policy"].strip():
                st.warning("Escribe el número de póliza y vuelve a generar el contrato para poder descargar.")
            verified = verified and bool(res["policy"].strip())
        st.download_button("⬇️ Descargar contrato en PDF", res["pdf"], disabled=not verified,
                           file_name=res["nombre"], mime="application/pdf", type="primary")
    else:
        st.caption("Revisa los datos y pulsa «Generar contrato».")
