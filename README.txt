CONTRATOS PUBLIC ADJUSTER - VARIAS APPS, UN SOLO CODIGO

ESTRUCTURA
  app.py, parsers.py, fill.py, requirements.txt, packages.txt   (codigo comun)
  contratos/
     silva/    contrato.pdf + config.json
     tibbils/  contrato.pdf + config.json

CADA APP (cada enlace) USA UN CONTRATO: se elige en Streamlit > Settings > Secrets
  APP_PASSWORD = "clave-de-esta-app"
  PA = "tibbils"          (o "silva")

AGREGAR UN PA NUEVO
  1. Crea contratos/<nombre>/ con su contrato.pdf y su config.json
     (copia el config.json de silva o tibbils y ajusta los nombres de los campos).
  2. Crea una app nueva en Streamlit con el MISMO repositorio y pon su Secret PA = "<nombre>".

Si una app no tiene el Secret PA y hay varios contratos, mostrara un selector para elegir.
