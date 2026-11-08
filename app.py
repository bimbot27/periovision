from __future__ import annotations
import hashlib
import tempfile
from pathlib import Path

import streamlit as st
from PIL import Image
from ultralytics import YOLO

st.set_page_config(page_title="PerioVision | Demo", page_icon="🦷", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #f5f8fb; }
[data-testid="stSidebar"] { background: #102f3c; }
[data-testid="stSidebar"] * { color: #eef7f8 !important; }
[data-testid="stSidebar"] [data-testid="stFileUploader"] section { background: #ffffff; border: 1px dashed #a9c1c9; }
[data-testid="stSidebar"] [data-testid="stFileUploader"] section * { color: #163744 !important; }
.hero { background: linear-gradient(120deg,#103744,#176675); padding: 30px 34px; border-radius: 20px; color: white; margin-bottom: 22px; }
.hero h1 { font-family: 'Manrope',sans-serif; color: white; font-size: 2rem; margin: 0 0 7px; }
.hero p { color: #d8ebee; margin: 0; }
.eyebrow { color: #9ed8cf; font-weight: 700; font-size: .76rem; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 10px; }
.panel-title { color: #163744; font-family: 'Manrope',sans-serif; font-size: 1.12rem; font-weight: 800; margin-bottom: 12px; }
.muted { color: #70818b; font-size: .9rem; }
div[data-testid="stMetric"] { background: #f3f8f8; border: 1px solid #e3eeee; padding: 14px 16px; border-radius: 12px; }
.stButton button { border-radius: 10px; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource(show_spinner="Cargando el modelo…")
def load_model(model_path: str) -> YOLO:
    return YOLO(model_path)

def save_model(contents: bytes) -> str:
    digest = hashlib.sha256(contents).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"periovision_{digest}.pt"
    if not path.exists():
        path.write_bytes(contents)
    return str(path)

st.markdown("""
<div class="hero"><div class="eyebrow">Visión computacional · demostración</div>
<h1>PerioVision</h1><p>Analiza una radiografía y visualiza las detecciones de tu modelo en una sola pantalla.</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🦷 PerioVision")
    st.caption("Panel de demostración del modelo YOLO")
    st.markdown("---")
    st.markdown("### 1 · Carga el modelo")
    model_upload = st.file_uploader("Cargar modelo entrenado (.pt)", type=["pt"], help="Descarga best.pt desde Colab.")
    st.markdown("---")
    st.markdown("### 2 · Ajusta el análisis")
    confidence = st.slider("Confianza mínima", 0.05, 0.95, 0.25, 0.05)
    image_size = st.select_slider("Tamaño de análisis", options=[320, 480, 640, 800, 1024], value=640)
    st.markdown("---")
    st.caption("Demo académica. Las detecciones requieren interpretación profesional.")

model_path = save_model(model_upload.getvalue()) if model_upload else None
if model_path is None:
    local_model = Path(__file__).with_name("best.pt")
    if local_model.exists():
        model_path = str(local_model)
if model_path is None:
    st.info("Para empezar, carga **best.pt** de tu modelo entrenado en el panel izquierdo.")

left, right = st.columns(2, gap="large")
with left:
    st.markdown('<div class="panel-title">Radiografía de entrada</div>', unsafe_allow_html=True)
    image_upload = st.file_uploader("Sube una imagen", type=["jpg", "jpeg", "png", "bmp", "webp"], label_visibility="collapsed")
    if image_upload:
        original = Image.open(image_upload).convert("RGB")
        st.image(original, use_container_width=True)
        st.caption(f"{image_upload.name} · {original.width} × {original.height} px")
    else:
        st.markdown('<div class="muted">Formatos: JPG, PNG, BMP o WEBP.</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel-title">Resultado del análisis</div>', unsafe_allow_html=True)
    if not model_path:
        st.markdown('<div class="muted">Carga el modelo y una imagen para mostrar el resultado.</div>', unsafe_allow_html=True)
    elif not image_upload:
        st.markdown('<div class="muted">Sube una radiografía para iniciar el análisis.</div>', unsafe_allow_html=True)
    elif st.button("Analizar radiografía", type="primary", use_container_width=True):
        try:
            model = load_model(model_path)
            with st.spinner("Analizando imagen…"):
                result = model.predict(source=original, conf=confidence, imgsz=image_size, verbose=False)[0]
            annotated = result.plot()[:, :, ::-1]  # YOLO dibuja BGR; Streamlit recibe RGB.
            st.image(annotated, caption="Detecciones del modelo", use_container_width=True)
            boxes = result.boxes
            count = 0 if boxes is None else len(boxes)
            st.metric("Detecciones encontradas", count)
            if count:
                names = result.names
                rows = []
                for box in boxes:
                    class_id = int(box.cls.item())
                    label = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]
                    rows.append({"Clase detectada": label, "Confianza": f"{float(box.conf.item()):.1%}"})
                st.dataframe(rows, hide_index=True, use_container_width=True)
            else:
                st.success("El modelo no encontró detecciones por encima del umbral seleccionado.")
        except Exception as exc:
            st.error(f"No se pudo procesar la imagen: {exc}")

st.caption("Interfaz de demostración basada en el modelo YOLO del notebook. No constituye un diagnóstico.")


