"""PerioVision · interfaz Streamlit con inicio de sesión y dos roles.

- administrador: mantenimiento de la web (modelo, parámetros, usuarios, pruebas QA, auditoría).
- usuario: uso de la web (analizar y validar radiografías, historial de informes).
La lógica vive en core.py (validación, inferencia, revisión), informe.py (informes e historial)
y auth.py (acceso y perfiles).
"""
from __future__ import annotations

import copy
import hashlib
import html
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path

import streamlit as st

import core
from auth import (ROLES, SPECIALTIES, AuthError, UserStore, display_name, generate_password,
                  profile_complete)
from core import Case, ProductError, YoloDetector, draw_detections
from informe import CaseArchive, build_report

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PERIOVISION_DATA", ROOT / "datos"))  # alternativa solo para pruebas
MODEL_PATH = ROOT / "best.pt"
CONFIG_PATH = DATA / "config.json"
BACKUPS = DATA / "respaldos"
EVIDENCE = ROOT / "evidencias"
WORK = Path(tempfile.gettempdir()) / "periovision"
DEFAULTS = {"model_authorized": True, "conf": 0.25, "imgsz": 640, "session_minutes": 30}

st.set_page_config(page_title="PerioVision", page_icon="🦷", layout="wide",
                   initial_sidebar_state="expanded")
store = UserStore(DATA / "usuarios.json")
archive = CaseArchive(DATA / "casos")


# ─────────────────────────────── utilidades ───────────────────────────────
def load_config() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    DATA.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def esc(value) -> str:
    return html.escape(str(value if value is not None else "—"))


def file_sha(path: Path) -> str:
    return core.sha256(path) if path.exists() else ""


@st.cache_resource(show_spinner=False)
def _model_loader(path: str, digest: str):  # digest invalida la caché al reemplazar el modelo
    """Carga y calienta el modelo en segundo plano, una sola vez por proceso (defecto D-05).

    La primera inferencia de PyTorch es lenta (~2-3 s); hacerla al iniciar sesión evita que el
    primer análisis del usuario supere la meta de 3 s carga-visualización.
    """
    box: dict = {}

    def run() -> None:
        try:
            det = YoloDetector(path, authorization=True)
            det.predict(core.synthetic_image())  # calentamiento
            box["det"] = det
        except Exception as e:  # se informa al pedir el detector
            box["err"] = e

    worker = threading.Thread(target=run, name="periovision-warmup", daemon=True)
    worker.start()
    return box, worker


def base_detector(path: str, digest: str) -> YoloDetector:
    box, worker = _model_loader(path, digest)
    if worker.is_alive():
        with st.spinner("Preparando el modelo…"):
            worker.join()
    if "err" in box:
        _model_loader.clear()
        raise box["err"]
    return box["det"]


base_detector.clear = _model_loader.clear


def cloud_bootstrap() -> str:
    """Despliegue en Streamlit Community Cloud: crea el administrador inicial y trae los pesos desde
    los secrets (`[periovision]` admin_user, admin_password, model_url, model_sha256). En local no hace nada."""
    try:
        cfg = dict(st.secrets.get("periovision", {}))
    except Exception:  # sin archivo de secrets
        return "sin secrets"
    if not cfg:
        return "sin secrets"
    done = []
    if not store.path.exists() and cfg.get("admin_user") and cfg.get("admin_password"):
        store.create_user(cfg["admin_user"], cfg["admin_password"], "administrador", actor="despliegue", must_change=True)
        done.append("administrador inicial")
    if not MODEL_PATH.exists() and cfg.get("model_url"):
        expected = str(cfg.get("model_sha256", "")).lower()
        if len(expected) != 64:
            raise ProductError("Falta model_sha256 en los secrets: no se descargan pesos sin verificar su huella.")
        import urllib.request
        if not str(cfg["model_url"]).startswith("https://"):
            raise ProductError("model_url debe usar https:// (no se aceptan file:, http: ni otros esquemas).")
        tmp = MODEL_PATH.with_suffix(".descarga")
        with urllib.request.urlopen(cfg["model_url"], timeout=120) as r, tmp.open("wb") as f:  # noqa: S310 (esquema validado)
            shutil.copyfileobj(r, f)
        if core.sha256(tmp) != expected:
            tmp.unlink(missing_ok=True)
            raise ProductError("La huella SHA-256 de los pesos descargados no coincide; se descartaron.")
        tmp.replace(MODEL_PATH)
        done.append("modelo verificado")
    return ", ".join(done) or "sin cambios"


def preload_model() -> None:
    """Inicia la carga del modelo sin bloquear la página."""
    if MODEL_PATH.exists() and load_config()["model_authorized"]:
        _model_loader(str(MODEL_PATH), file_sha(MODEL_PATH))


def detector() -> YoloDetector:
    """Detector con la calibración vigente definida por el administrador."""
    cfg = load_config()
    if not cfg["model_authorized"]:
        raise ProductError("El administrador no ha autorizado el modelo. Contacte al administrador.")
    if not MODEL_PATH.exists():
        raise ProductError("Modelo no disponible. El administrador debe cargar best.pt.")
    det = copy.copy(base_detector(str(MODEL_PATH), file_sha(MODEL_PATH)))
    det.conf, det.imgsz = float(cfg["conf"]), int(cfg["imgsz"])
    return det


def version(pkg: str) -> str:
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return "no instalado"


def refresh_user() -> dict:
    user = st.session_state["user"]
    user["perfil"] = store.get_profile(user["usuario"])
    return user


# ─────────────────────────────── estilo (HIG) ───────────────────────────────
def inject_css() -> None:
    # Colores semánticos de Apple (claro, oscuro). light-dark() sigue el color-scheme que Streamlit
    # aplica a .stApp, así el cambio de tema es inmediato y no depende de un rerun.
    t = {
        "label": ("#1D1D1F", "#F5F5F7"),
        "secondary": ("rgba(60,60,67,.76)", "rgba(235,235,245,.70)"),
        "card": ("#FFFFFF", "#1C1C1E"),
        "fill": ("rgba(118,118,128,.12)", "rgba(118,118,128,.26)"),
        "separator": ("#D2D2D7", "#38383A"),
        "blue": ("#0066CC", "#2997FF"),
        "green": ("#1B7A34", "#30D158"),
        "orange": ("#C93400", "#FF9F0A"),
        "red": ("#D70015", "#FF453A"),
        "shadow-c": ("rgba(0,0,0,.06)", "rgba(0,0,0,0)"),
    }
    tokens = "".join(f"--pv-{k}:light-dark({a},{b});" for k, (a, b) in t.items())
    tokens += "--pv-shadow:0 1px 2px var(--pv-shadow-c),0 4px 16px var(--pv-shadow-c);"
    st.markdown(f"""<style>
.stApp {{ {tokens} }}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
.pv-large-title {{ font-size: 2.125rem; font-weight: 700; line-height: 1.18; letter-spacing: -0.026em;
  color: var(--pv-label); margin: 0 0 1rem; }}
.pv-subtitle {{ font-size: 1.0625rem; color: var(--pv-secondary); margin: -.75rem 0 1.5rem; }}
.pv-section {{ font-size: .8125rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em;
  color: var(--pv-secondary); margin: 1.4rem 0 .5rem .25rem; }}
.pv-card {{ background: var(--pv-card); border-radius: 14px; padding: 1.1rem 1.25rem; box-shadow: var(--pv-shadow);
  border: 1px solid var(--pv-separator); color: var(--pv-secondary); }}
.pv-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .75rem; margin-bottom: .5rem; }}
.pv-tile {{ background: var(--pv-card); border-radius: 14px; padding: .9rem 1.1rem; border: 1px solid var(--pv-separator);
  box-shadow: var(--pv-shadow); }}
.pv-tile .k {{ font-size: .8125rem; color: var(--pv-secondary); margin-bottom: .2rem; }}
.pv-tile .v {{ font-size: 1.5rem; font-weight: 600; color: var(--pv-label); letter-spacing: -0.02em; }}
.pv-tile .s {{ font-size: .8125rem; color: var(--pv-secondary); }}
.pv-pill {{ display: inline-block; padding: .14rem .6rem; border-radius: 980px; font-size: .8125rem; font-weight: 600;
  background: var(--pv-fill); color: var(--pv-label); white-space: nowrap; }}
.pv-pill.ok {{ color: var(--pv-green); }} .pv-pill.bad {{ color: var(--pv-red); }}
.pv-ok {{ color: var(--pv-green); }} .pv-warn {{ color: var(--pv-orange); }} .pv-bad {{ color: var(--pv-red); }}
.pv-notice {{ display: flex; gap: .6rem; align-items: flex-start; background: var(--pv-fill); border-radius: 12px;
  padding: .7rem .9rem; font-size: .9375rem; color: var(--pv-label); margin: .25rem 0 1rem; }}
table.pv-table {{ width: 100%; border-collapse: separate; border-spacing: 0; background: var(--pv-card);
  border: 1px solid var(--pv-separator); border-radius: 14px; overflow: hidden; font-size: .9375rem; }}
table.pv-table caption {{ text-align: left; color: var(--pv-secondary); font-size: .8125rem; padding: 0 0 .4rem .25rem; }}
table.pv-table th {{ text-align: left; font-weight: 600; color: var(--pv-secondary); font-size: .8125rem;
  padding: .6rem .9rem; border-bottom: 1px solid var(--pv-separator); }}
table.pv-table td {{ padding: .6rem .9rem; color: var(--pv-label); border-bottom: 1px solid var(--pv-separator); }}
table.pv-table tr:last-child td {{ border-bottom: none; }}
.pv-scroll {{ overflow-x: auto; max-width: 100%; }}
table.pv-table td:first-child, table.pv-table th {{ white-space: nowrap; }}
.pv-dot {{ display: inline-block; width: .7rem; height: .7rem; border-radius: 50%; margin-right: .45rem;
  vertical-align: middle; border: 1px solid rgba(0,0,0,.25); }}
.pv-appicon {{ width: 72px; height: 72px; border-radius: 16px; margin: 0 auto 1rem; display: grid; place-items: center;
  background: linear-gradient(160deg, #5AC8FA 0%, #0071E3 100%); box-shadow: 0 6px 18px rgba(0,113,227,.28); }}
.pv-login-title {{ text-align: center; font-size: 1.75rem; font-weight: 700; letter-spacing: -0.024em; margin: 0; color: var(--pv-label); }}
.pv-login-sub {{ text-align: center; color: var(--pv-secondary); margin: .3rem 0 1.4rem; }}
.pv-foot {{ text-align: center; color: var(--pv-secondary); font-size: .8125rem; margin-top: 1.5rem; }}
[data-testid="stForm"] {{ background: var(--pv-card); border-radius: 18px; border: 1px solid var(--pv-separator);
  box-shadow: var(--pv-shadow); padding: 1.4rem 1.4rem 1rem; }}
/* Sin texto superpuesto en los campos ni segundo botón de "mostrar" del navegador (Edge) */
[data-testid="InputInstructions"] {{ display: none !important; }}
input::-ms-reveal, input::-ms-clear {{ display: none !important; }}
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button {{ font-weight: 500; min-height: 44px; padding: 0 1.25rem; }}
[data-testid="stFileUploaderDropzone"] {{ border-radius: 14px; }}
[data-testid="stImage"] img {{ border-radius: 12px; }}
:focus-visible {{ outline: 3px solid var(--pv-blue) !important; outline-offset: 2px !important; border-radius: 8px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>""", unsafe_allow_html=True)
    # Idioma del documento para lectores de pantalla (WCAG 3.1.1); Streamlit lo deja en "en".
    st.html("<script>document.documentElement.lang='es'</script>", unsafe_allow_javascript=True)


TOOTH = ('<svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
         '<path d="M7.5 3C5 3 3.5 5 3.5 7.6c0 2 .8 3.4 1.4 5 .7 1.9.8 4.1 1.4 6 .4 1.3 1 2.4 1.9 2.4 1.5 0 '
         '1.4-3.4 2.1-5 .3-.8.9-1.2 1.7-1.2s1.4.4 1.7 1.2c.7 1.6.6 5 2.1 5 .9 0 1.5-1.1 1.9-2.4.6-1.9.7-4.1 '
         '1.4-6 .6-1.6 1.4-3 1.4-5C20.5 5 19 3 16.5 3c-1.9 0-2.8 1-4.5 1S9.4 3 7.5 3Z" fill="white"/></svg>')


def header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="pv-large-title" role="heading" aria-level="1">{esc(title)}</div>'
                + (f'<p class="pv-subtitle">{esc(subtitle)}</p>' if subtitle else ""), unsafe_allow_html=True)


def section(text: str) -> None:
    st.markdown(f'<div class="pv-section" role="heading" aria-level="2">{esc(text)}</div>', unsafe_allow_html=True)


def tiles(items: list[tuple[str, str, str]]) -> None:
    body = "".join(f'<div class="pv-tile" role="group" aria-label="{esc(k)}"><div class="k">{esc(k)}</div>'
                   f'<div class="v">{v}</div><div class="s">{esc(s)}</div></div>' for k, v, s in items)
    st.markdown(f'<div class="pv-tiles">{body}</div>', unsafe_allow_html=True)


def table(headers: list[str], rows: list[list[str]], caption: str = "", raw_cols: tuple[int, ...] = ()) -> None:
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c if i in raw_cols else esc(c)}</td>" for i, c in enumerate(r)) + "</tr>"
                   for r in rows)
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    st.markdown(f'<div class="pv-scroll" tabindex="0"><table class="pv-table">{cap}<thead><tr>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>', unsafe_allow_html=True)


def notice(text: str = core.NOTICE) -> None:
    st.markdown(f'<div class="pv-notice" role="note"><span aria-hidden="true">ⓘ</span><span>{esc(text)}</span></div>',
                unsafe_allow_html=True)


def card(text: str) -> None:
    st.markdown(f'<div class="pv-card">{esc(text)}</div>', unsafe_allow_html=True)


def result_pill(result: str) -> str:
    kind = "ok" if result.startswith("Aprobada") else ("" if result == "No evaluable" else "bad")
    return f'<span class="pv-pill {kind}">{esc(result)}</span>'


# ─────────────────────────────── sesión ───────────────────────────────
def logout(reason: str = "") -> None:
    if st.session_state.get("user"):
        store.audit("cierre_sesion", st.session_state["user"]["usuario"], detail=reason)
    st.session_state.clear()
    if reason:
        st.session_state["flash"] = reason


def check_timeout() -> None:
    if not st.session_state.get("user"):
        return
    minutes = load_config()["session_minutes"]
    if time.time() - st.session_state.get("last_seen", time.time()) > minutes * 60:
        logout(f"Tu sesión se cerró tras {minutes} minutos de inactividad.")
        st.rerun()
    st.session_state["last_seen"] = time.time()


def login_view() -> None:
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(f'<div class="pv-appicon">{TOOTH}</div>'
                    '<div class="pv-login-title" role="heading" aria-level="1">PerioVision</div>'
                    '<p class="pv-login-sub">Inicia sesión para continuar</p>', unsafe_allow_html=True)
        if msg := st.session_state.pop("flash", None):
            st.info(msg)
        with st.form("login", clear_on_submit=False, border=False):
            username = st.text_input("Usuario", autocomplete="username", placeholder="nombre de usuario")
            password = st.text_input("Contraseña", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Iniciar sesión", type="primary", width="stretch")
        if submitted:
            if not username or not password:
                st.error("Escribe tu usuario y tu contraseña.")
            elif len(username) > 32 or len(password) > 128:
                st.error("Usuario o contraseña incorrectos.")
            else:
                try:
                    user = store.authenticate(username, password)
                except AuthError as e:
                    st.error(str(e))
                else:
                    st.session_state.update(user=user, last_seen=time.time())
                    st.rerun()
        st.markdown(f'<p class="pv-foot">{esc(core.VERSION)}</p>', unsafe_allow_html=True)


def change_password_form(forced: bool = False) -> None:
    user = st.session_state["user"]
    if forced:
        st.warning("Por seguridad, cambia la contraseña inicial antes de continuar.")
    with st.form("cambiar_clave", clear_on_submit=True):
        current = st.text_input("Contraseña actual", type="password", autocomplete="current-password")
        new = st.text_input("Nueva contraseña", type="password", autocomplete="new-password",
                            help="Mínimo 10 caracteres con mayúscula, minúscula, número y símbolo.")
        repeat = st.text_input("Repite la nueva contraseña", type="password", autocomplete="new-password")
        ok = st.form_submit_button("Cambiar contraseña", type="primary")
    if ok:
        if new != repeat:
            st.error("Las contraseñas nuevas no coinciden.")
            return
        try:
            store.change_password(user["usuario"], current, new)
        except AuthError as e:
            st.error(str(e))
        else:
            user["debe_cambiar"] = False
            st.success("Contraseña actualizada.")
            if forced:
                st.rerun()


def profile_inputs(profile: dict, role: str, cop_editable: bool, key: str) -> dict:
    """Campos de datos generales (dentro de un formulario)."""
    p = profile or {}
    c1, c2 = st.columns(2)
    nombres = c1.text_input("Nombres", p.get("nombres", ""), key=f"{key}_n", autocomplete="given-name")
    apellidos = c2.text_input("Apellidos", p.get("apellidos", ""), key=f"{key}_a", autocomplete="family-name")
    c3, c4 = st.columns(2)
    correo = c3.text_input("Correo electrónico", p.get("correo", ""), key=f"{key}_c", autocomplete="email")
    cop_label = "N.º de COP (Colegio Odontológico del Perú)" + ("" if role == "usuario" else " · opcional")
    cop = c4.text_input(cop_label, p.get("cop", ""), key=f"{key}_cop", disabled=not cop_editable,
                        help=None if cop_editable else "Solo el administrador puede modificar el N.º de COP.")
    c5, c6 = st.columns(2)
    spec_value = p.get("especialidad") or None
    especialidad = c5.selectbox("Especialidad", SPECIALTIES, index=SPECIALTIES.index(spec_value) if spec_value in SPECIALTIES else None,
                                placeholder="Elige una opción", key=f"{key}_e")
    today = date.today()
    born = date.fromisoformat(p["fecha_nacimiento"]) if p.get("fecha_nacimiento") else None
    nacimiento = c6.date_input("Fecha de nacimiento", born, min_value=date(today.year - 100, 1, 1),
                               max_value=date(today.year - 18, today.month, min(today.day, 28)),
                               format="DD/MM/YYYY", key=f"{key}_f")
    return {"nombres": nombres, "apellidos": apellidos, "correo": correo, "cop": cop,
            "especialidad": especialidad or "", "fecha_nacimiento": nacimiento.isoformat() if nacimiento else ""}


def profile_form(forced: bool = False) -> None:
    user = refresh_user()
    has_cop = bool(user["perfil"].get("cop"))
    if forced:
        st.info("Completa tus datos profesionales. Aparecerán en los informes que valides.")
    with st.form("perfil"):
        data = profile_inputs(user["perfil"], user["rol"], cop_editable=not has_cop, key="perfil")
        ok = st.form_submit_button("Guardar datos", type="primary")
    if ok:
        try:
            user["perfil"] = store.update_profile(user["usuario"], data, user["usuario"], allow_cop=not has_cop)
        except AuthError as e:
            st.error(str(e))
        else:
            st.success("Datos guardados.")
            if forced:
                st.rerun()


def account_page() -> None:
    user = refresh_user()
    p = user["perfil"]
    header("Mi cuenta")
    tiles([("Nombre", esc(display_name(p, user["usuario"])), user["usuario"]),
           ("Rol", esc(user["rol"].capitalize()), ""),
           ("N.º COP", esc(p.get("cop") or "—"), p.get("especialidad", "")),
           ("Cierre automático", f'{load_config()["session_minutes"]} min', "por inactividad")])
    section("Datos generales")
    profile_form()
    section("Cambiar contraseña")
    change_password_form()
    section("Apariencia")
    st.markdown("La app sigue el modo **claro u oscuro** de tu sistema. Para fijar uno, abre el menú **⋮** "
                "(arriba a la derecha) › **Settings** › **Choose app theme**.")


# ─────────────────────────────── vista de usuario ───────────────────────────────
def reset_case() -> None:
    for k in ("case", "case_digest", "case_error", "saved_code"):
        st.session_state.pop(k, None)
    st.session_state["uploader"] = st.session_state.get("uploader", 0) + 1


def load_upload(upload) -> "Case | None":
    """Convierte el archivo subido en un caso (una vez por archivo) y muestra el rechazo si lo hay."""
    if upload is None:
        if st.session_state.get("case_digest"):
            for k in ("case", "case_digest", "case_error", "saved_code"):
                st.session_state.pop(k, None)
        return None
    data = upload.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("case_digest") != digest:
        for k in ("case", "case_error", "saved_code"):
            st.session_state.pop(k, None)
        WORK.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.name).suffix.lower()
        tmp = WORK / f"in_{digest[:16]}{suffix if suffix in ('.png', '.jpg', '.jpeg') else '.bin'}"
        tmp.write_bytes(data)
        try:
            st.session_state["case"] = Case(tmp, f"CASO_{datetime.now():%Y%m%d_%H%M%S}")
        except ProductError as e:
            st.session_state["case_error"] = str(e)
        finally:
            st.session_state["case_digest"] = digest
            tmp.unlink(missing_ok=True)  # el registro no conserva la ruta ni el nombre original
    if err := st.session_state.get("case_error"):
        st.error(f"Imagen rechazada: {err}")
    return st.session_state.get("case")


def run_analysis(case: Case, user: dict) -> None:
    try:
        case.quality(True)  # confirmado por el usuario al pulsar Analizar
        with st.spinner("Analizando imagen…"):
            case.infer(detector())
        st.session_state.pop("saved_code", None)
        store.audit("analisis", user["usuario"], detail=case.data["case_code"])
        st.rerun()
    except ProductError as e:
        st.error(str(e))
    except Exception as e:  # fallo inesperado del motor: se conserva el registro
        st.error(f"No se pudo procesar la imagen. Se conservan los registros anteriores. ({type(e).__name__})")


def input_panel(case: Case | None, user: dict) -> None:
    if not case:
        return
    w, h = case.image.size
    st.image(case.image, caption=f"Original · {w} × {h} px · {case.data['case_code']}", width="stretch")
    first = not case.data["runs"]
    if st.button("Analizar radiografía" if first else "Volver a analizar", type="primary" if first else "secondary",
                 width="stretch", icon=":material/radiology:"):
        run_analysis(case, user)
    st.caption("Al analizar confirmas que la imagen es nítida, completa y no muestra datos personales.")
    if first and not st.session_state.get("saved_code"):
        unevaluable_form(case, user)


def new_case_button() -> None:
    if st.button("Nuevo análisis", icon=":material/add_photo_alternate:", width="stretch"):
        reset_case()
        st.rerun()


def result_panel(case: Case, last: dict) -> None:
    items = last["original"]
    sha = (last["model"].get("weights_sha256") or "")[:12]
    st.image(draw_detections(case.image, items), width="stretch",
             caption=f"Propuesta del modelo · {len(items)} hallazgo(s) · {core.VERSION} · modelo {sha}")
    best = max((i["confidence"] for i in items), default=None)
    tiles([("Hallazgos", str(len(items)), f"umbral {last['model'].get('confidence_threshold', 0):.0%}"),
           ("Confianza máxima", f"{best:.0%}" if best is not None else "—", ""),
           ("Tiempo", f"{last['elapsed_adapter_ms'] / 1000:.2f} s", f"{last['model'].get('imgsz', '')} px")])
    if not items:
        st.info("El modelo no encontró hallazgos sobre el umbral configurado. " + core.NOTICE)
        return
    from informe import DESCRIPTIONS, location
    rows = [[str(n), f'<span class="pv-dot" style="background:{core.COLORS.get(i["class"], "#0071E3")}"></span>'
             f'{esc(i["class"])}', DESCRIPTIONS.get(i["class"], ""), f'{i["confidence"]:.1%}',
             location(i["box"], case.image.size)] for n, i in enumerate(items, 1)]
    table(["#", "Clase", "Descripción", "Confianza", "Ubicación"], rows,
          caption="Hallazgos propuestos por el modelo", raw_cols=(1,))


def box_editor(case: Case, items: list[dict], run_id: str):
    st.caption("Cambia la clase o las coordenadas, quita filas o agrega hallazgos que el modelo no vio. "
               "La propuesta original se conserva.")
    w, h = case.image.size

    def coord(name: str, limit: int):
        return st.column_config.NumberColumn(f"{name} (px)", min_value=0, max_value=limit, step=1, required=True)

    return st.data_editor(
        [{"Clase": i["class"], "x1": round(i["box"][0]), "y1": round(i["box"][1]),
          "x2": round(i["box"][2]), "y2": round(i["box"][3])} for i in items],
        num_rows="dynamic", width="stretch", key=f"editor_{run_id}",
        column_config={"Clase": st.column_config.SelectboxColumn("Clase", options=list(core.LABELS), required=True),
                       "x1": coord("x1", w), "y1": coord("y1", h), "x2": coord("x2", w), "y2": coord("y2", h)})


def save_review(case: Case, user: dict, action: str, edited, obs: str) -> None:
    items = case.data["runs"][-1]["original"]
    try:
        revised = corrected_items(edited, items) if action == "corregir" else None
        case.review(action, user["usuario"].replace(".", "_"), revised)
        report = build_report(case, user["usuario"], user["perfil"], obs)
        archive.save(case, report, draw_detections(case.image, revised if revised is not None else items))
        st.session_state["saved_code"] = report["codigo_caso"]
        store.audit("revision", user["usuario"], detail=f"{report['codigo_caso']}:{report['resultado_validacion']}")
    except ProductError as e:
        st.error(str(e))


def validation_panel(case: Case, last: dict, user: dict) -> None:
    complete = profile_complete(user["perfil"], user["rol"])
    if not complete:
        st.warning("Completa tus datos profesionales (nombre, correo y N.º de COP) en **Mi cuenta** para validar.")
    labels = {"aceptar": "Aprobar", "corregir": "Corregir hallazgos", "descartar": "Rechazar"}
    action = st.radio("Resultado de tu revisión", list(labels), horizontal=True, key=f"accion_{last['run_id']}",
                      format_func=labels.get)
    with st.form("validacion", border=False):
        edited = box_editor(case, last["original"], last["run_id"]) if action == "corregir" else None
        obs = st.text_area("Observaciones (opcional)", max_chars=500, height=90,
                           placeholder="Ej.: correlacionar con sondaje; control en 6 meses.")
        send = st.form_submit_button("Registrar revisión", type="primary", width="stretch",
                                     disabled=not complete, icon=":material/verified:")
    if send:
        save_review(case, user, action, edited, obs)
    if code := st.session_state.get("saved_code"):
        saved = next((r for r in archive.list() if r["codigo_caso"] == code), None)
        if saved:
            st.success(f"Revisión registrada: {saved['resultado_validacion']}. El informe quedó en el historial.")
            downloads(code)
        new_case_button()


def analyze_page() -> None:
    user = refresh_user()
    header("Analizar radiografía")
    notice()
    left, right = st.columns([1, 1], gap="large")
    with left:
        section("1 · Radiografía")
        upload = st.file_uploader("Radiografía periapical (PNG o JPEG, máx. 20 MB)", type=["png", "jpg", "jpeg"],
                                  key=f"up_{st.session_state.get('uploader', 0)}")
        case = load_upload(upload)
        input_panel(case, user)
    with right:
        section("2 · Resultado")
        if not case:
            card("Sube una radiografía para iniciar el análisis.")
        elif not case.data["runs"] and st.session_state.get("saved_code"):
            st.success("Imagen registrada como no evaluable. El registro quedó en el historial.")
            downloads(st.session_state["saved_code"])
            new_case_button()
        elif not case.data["runs"]:
            card("Pulsa «Analizar radiografía» para ver la propuesta del modelo.")
        else:
            last = case.data["runs"][-1]
            result_panel(case, last)
            section("3 · Validación")
            validation_panel(case, last, user)


def corrected_items(edited, original: list[dict]) -> list[dict]:
    """Filas del editor → detecciones revisadas. Las filas nuevas son hallazgos del profesional (confianza 1)."""
    rows = edited.to_dict("records") if hasattr(edited, "to_dict") else list(edited or [])
    out = []
    for n, r in enumerate(rows):
        if not r.get("Clase"):
            continue
        conf = original[n]["confidence"] if n < len(original) else 1.0
        try:
            box = [float(r["x1"]), float(r["y1"]), float(r["x2"]), float(r["y2"])]
        except (TypeError, ValueError, KeyError) as e:
            raise ProductError(f"Fila {n + 1}: completa las cuatro coordenadas.") from e
        out.append({"class": r["Clase"], "confidence": conf, "box": box})
    return out


def unevaluable_form(case: Case, user: dict) -> None:
    """RF05: registrar una imagen no evaluable sin ejecutar el modelo."""
    with st.expander("¿La imagen no sirve? Marcar como no evaluable"):
        with st.form("no_evaluable", border=False):
            reason = st.selectbox("Motivo", ["Imagen borrosa o movida", "Zona de interés incompleta",
                                             "Contraste o exposición inadecuados", "Muestra datos personales",
                                             "No es una radiografía periapical", "Otro"])
            detail = st.text_input("Detalle (opcional)", max_chars=200)
            ok = st.form_submit_button("Registrar como no evaluable",
                                       disabled=not profile_complete(user["perfil"], user["rol"]))
        if ok:
            from informe import build_unevaluable_report
            try:
                case.quality(False)
                report = build_unevaluable_report(case, user["usuario"], user["perfil"],
                                                  reason + (f": {detail}" if detail.strip() else ""))
                archive.save(case, report, case.image)
                st.session_state["saved_code"] = report["codigo_caso"]
                store.audit("no_evaluable", user["usuario"], detail=report["codigo_caso"])
                st.rerun()
            except ProductError as e:
                st.error(str(e))


def downloads(code: str) -> None:
    top = st.container()
    c1, c2 = st.columns(2)
    for col, (kind, label) in zip((top, c1, c2), (("pdf", "Descargar informe PDF"), ("csv", "Tabla CSV"), ("json", "Datos JSON")), strict=True):
        try:
            data, name, mime = archive.file(code, kind)
        except (OSError, ProductError):
            continue
        col.download_button(label, data, file_name=name, mime=mime, width="stretch",
                            key=f"dl_{code}_{kind}", icon=":material/download:")


def history_page() -> None:
    user = st.session_state["user"]
    header("Historial de radiografías", "Casos validados por el equipo. Puedes volver a descargar cada informe.")
    reports = archive.list()
    approved = sum(r["resultado_validacion"].startswith("Aprobada") for r in reports)
    rejected = sum(r["resultado_validacion"] == "Rechazada" for r in reports)
    mine = sum(r["profesional"]["usuario"] == user["usuario"] for r in reports)
    tiles([("Casos", str(len(reports)), "registrados"), ("Aprobadas", f'<span class="pv-ok">{approved}</span>', ""),
           ("Rechazadas", f'<span class="pv-bad">{rejected}</span>', ""),
           ("No evaluables", str(len(reports) - approved - rejected), ""), ("Míos", str(mine), "")])
    if not reports:
        card("Aún no hay casos validados. Analiza una radiografía y registra tu revisión.")
        return
    state = st.segmented_control("Estado", ["Todas", "Aprobadas", "Rechazadas", "No evaluables"], default="Todas")
    c2, c3 = st.columns([2, 1], vertical_alignment="bottom")
    query = c2.text_input("Buscar", placeholder="Código, profesional o COP")
    only_mine = c3.toggle("Solo mis análisis")
    q = query.strip().lower()
    rows = [r for r in reports
            if (state in (None, "Todas") or r["resultado_validacion"].startswith(state[:-1]))
            and (not only_mine or r["profesional"]["usuario"] == user["usuario"])
            and (not q or q in f"{r['codigo_caso']} {r['profesional']['nombre']} {r['profesional']['cop']}".lower())]
    table(["Fecha", "Caso", "Resultado", "Hallazgos", "Analizado y validado por"],
          [[r["fecha_validacion"], r["codigo_caso"], result_pill(r["resultado_validacion"]),
            f'{len(r["hallazgos"])}', f'{esc(r["profesional"]["nombre"])} · COP {esc(r["profesional"]["cop"])}']
           for r in rows], caption=f"{len(rows)} de {len(reports)} casos", raw_cols=(2, 4))
    if not rows:
        return
    section("Detalle")
    code = st.selectbox("Caso", [r["codigo_caso"] for r in rows],
                        format_func=lambda c: next(f"{c} · {r['resultado_validacion']} · {r['fecha_validacion']}"
                                                   for r in rows if r["codigo_caso"] == c))
    r = next(x for x in rows if x["codigo_caso"] == code)
    a, b = st.columns([1, 1], gap="large")
    with a:
        if archive.image(code).exists():
            st.image(str(archive.image(code)), width="stretch", caption=f"Imagen analizada · {code}")
    with b:
        p = r["profesional"]
        st.markdown(f'{result_pill(r["resultado_validacion"])}', unsafe_allow_html=True)
        table(["Campo", "Valor"], [["Analizado y validado por", p["nombre"]], ["N.º COP", p["cop"]],
                                   ["Especialidad", p["especialidad"]], ["Fecha de análisis", r["fecha_analisis"]],
                                   ["Fecha de validación", r["fecha_validacion"]], ["Resumen", r["resumen"]],
                                   ["Observaciones", r["observaciones"]]])
        st.write("")
        downloads(code)


# ─────────────────────────────── vistas de administrador ───────────────────────────────
def last_qa() -> dict | None:
    logs = sorted(EVIDENCE.glob("log_pruebas_QA_*.json"), key=lambda f: f.stat().st_mtime)
    return json.loads(logs[-1].read_text(encoding="utf-8")) if logs else None


def status_page() -> None:
    header("Estado del sistema", "Resumen del modelo, los usuarios y la última verificación de calidad.")
    if not st.session_state.get("auto_backup_done"):
        import datos
        made = datos.auto_backup(DATA)  # RNF07: un respaldo diario, se conservan 7
        st.session_state["auto_backup_done"] = True
        if made:
            store.audit("respaldo_automatico", st.session_state["user"]["usuario"], detail=made.name)
    cfg = load_config()
    users = store.list_users()
    qa = last_qa()
    reports = archive.list()
    model_ok = MODEL_PATH.exists()
    active = model_ok and cfg["model_authorized"]
    tiles([
        ("Modelo", f'<span class="{"pv-ok" if active else "pv-bad"}">{"Activo" if active else ("Sin autorizar" if model_ok else "Ausente")}</span>',
         f"{MODEL_PATH.stat().st_size / 1e6:.1f} MB" if model_ok else "best.pt no encontrado"),
        ("Usuarios", str(len(users)), f'{sum(u["bloqueado"] for u in users)} bloqueado(s)'),
        ("Casos validados", str(len(reports)), f"{archive.size_mb():.1f} MB en disco"),
        ("Pruebas QA", f'<span class="{"pv-ok" if qa and qa["dictamen"] == "APTA" else "pv-warn"}">'
                       f'{esc(qa["dictamen"]) if qa else "Sin ejecutar"}</span>',
         f'{qa["aprobadas"]}/{qa["total"]} aprobadas' if qa else ""),
    ])
    section("Calibración vigente")
    table(["Parámetro", "Valor"], [
        ["Confianza mínima", f'{cfg["conf"]:.0%}'], ["Tamaño de análisis", f'{cfg["imgsz"]} px'],
        ["Cierre de sesión por inactividad", f'{cfg["session_minutes"]} min'],
        ["Tamaño máximo de imagen", f"{core.MAX_BYTES // (1024 * 1024)} MB · {core.MAX_PIXELS:,} píxeles"],
        ["Clases admitidas", ", ".join(core.LABELS)]])
    section("Entorno")
    table(["Componente", "Versión"], [
        ["PerioVision", core.VERSION], ["Python", platform.python_version()],
        ["Streamlit", version("streamlit")], ["Ultralytics", version("ultralytics")],
        ["Pillow", version("Pillow")], ["Sistema", platform.platform()]])


def model_page() -> None:
    header("Modelo", "Verifica, autoriza, calibra o reemplaza los pesos del detector.")
    cfg = load_config()
    if MODEL_PATH.exists():
        stat = MODEL_PATH.stat()
        table(["Propiedad", "Valor"], [
            ["Archivo", MODEL_PATH.name], ["Tamaño", f"{stat.st_size / 1e6:.2f} MB"],
            ["Modificado", datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")],
            ["SHA-256", file_sha(MODEL_PATH)]])
    else:
        st.error("No se encontró best.pt. Carga un modelo abajo.")

    section("Verificación")
    if st.button("Verificar modelo", disabled=not MODEL_PATH.exists()):
        try:
            start = time.perf_counter()
            det = base_detector(str(MODEL_PATH), file_sha(MODEL_PATH))
            det.predict(core.synthetic_image())
            st.success(f"Modelo válido · tarea {det.model.task} · clases {', '.join(det.names.values())} · "
                       f"prueba en {time.perf_counter() - start:.2f} s")
            store.audit("modelo_verificado", st.session_state["user"]["usuario"])
        except ProductError as e:
            st.error(str(e))

    section("Autorización y calibración")
    st.caption("Los usuarios analizan siempre con esta calibración; no pueden cambiarla.")
    with st.form("params"):
        authorized = st.toggle("Modelo autorizado para uso", value=cfg["model_authorized"],
                               help="Confirma la autorización de datos, saneamiento y procedencia de los pesos.")
        c1, c2, c3 = st.columns(3)
        conf = c1.slider("Confianza mínima", 0.05, 0.95, float(cfg["conf"]), 0.05,
                         help="Solo se muestran hallazgos con una confianza igual o mayor.")
        imgsz = c2.select_slider("Tamaño de análisis (px)", [320, 480, 640, 800, 960, 1024], int(cfg["imgsz"]))
        minutes = c3.number_input("Cierre por inactividad (min)", 5, 240, int(cfg["session_minutes"]), 5)
        if st.form_submit_button("Guardar calibración", type="primary"):
            save_config({**cfg, "model_authorized": authorized, "conf": conf, "imgsz": imgsz,
                         "session_minutes": int(minutes)})
            store.audit("parametros_actualizados", st.session_state["user"]["usuario"],
                        detail=f"auth={authorized} conf={conf} imgsz={imgsz} min={minutes}")
            st.success("Calibración guardada.")

    section("Reemplazar modelo")
    new = st.file_uploader("Nuevo archivo de pesos (.pt)", type=["pt"],
                           help="Debe ser un modelo de detección con las clases Normal, Stage 1, Stage 2 y Stage 3.")
    if new and st.button("Validar y reemplazar", type="primary"):
        WORK.mkdir(parents=True, exist_ok=True)
        tmp = WORK / f"candidato_{hashlib.sha256(new.getvalue()).hexdigest()[:12]}.pt"
        tmp.write_bytes(new.getvalue())
        try:
            YoloDetector(tmp, authorization=True)  # valida tarea y clases antes de reemplazar
        except ProductError as e:
            st.error(f"Modelo rechazado: {e}")
        else:
            BACKUPS.mkdir(parents=True, exist_ok=True)
            if MODEL_PATH.exists():
                shutil.copy2(MODEL_PATH, BACKUPS / f"best_{datetime.now():%Y%m%d_%H%M%S}.pt")
            shutil.move(tmp, MODEL_PATH)
            base_detector.clear()
            store.audit("modelo_reemplazado", st.session_state["user"]["usuario"], detail=file_sha(MODEL_PATH))
            st.success("Modelo reemplazado. Se guardó una copia del anterior en datos/respaldos.")
        finally:
            tmp.unlink(missing_ok=True)
    backups = sorted(BACKUPS.glob("best_*.pt"), reverse=True) if BACKUPS.exists() else []
    if backups:
        table(["Respaldo", "Tamaño"], [[b.name, f"{b.stat().st_size / 1e6:.2f} MB"] for b in backups],
              caption="Respaldos de modelos anteriores")


def users_page() -> None:
    me = st.session_state["user"]["usuario"]
    header("Usuarios", "Altas, datos profesionales, roles, bloqueos y contraseñas.")
    users = store.list_users()
    fmt = lambda v: datetime.fromisoformat(v).astimezone().strftime("%d/%m/%Y %H:%M") if v else "—"
    table(["Usuario", "Nombre", "Rol", "COP", "Último acceso", "Estado"], [
        [u["usuario"], display_name(u["perfil"], "—"), u["rol"].capitalize(), u["perfil"].get("cop") or "—",
         fmt(u["ultimo_acceso"]),
         '<span class="pv-bad">Bloqueado</span>' if u["bloqueado"] else
         ('<span class="pv-warn">Debe cambiar contraseña</span>' if u["debe_cambiar"] else
          ('<span class="pv-warn">Perfil incompleto</span>' if not profile_complete(u["perfil"], u["rol"])
           else '<span class="pv-ok">Activo</span>'))]
        for u in users], caption=f"{len(users)} cuentas", raw_cols=(5,))

    section("Crear usuario")
    role = st.segmented_control("Rol de la nueva cuenta", ROLES, default="usuario", format_func=str.capitalize,
                                key="new_role") or "usuario"
    with st.form("nuevo_usuario", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Nombre de usuario", help="3 a 32 caracteres: minúsculas, números, . _ -")
        pwd = c2.text_input("Contraseña inicial (vacía = generar una segura)", type="password",
                            autocomplete="new-password")
        profile = profile_inputs({}, role, cop_editable=True, key="nuevo")
        if st.form_submit_button("Crear usuario", type="primary"):
            password = pwd or generate_password()
            try:
                store.create_user(name, password, role, actor=me, must_change=True, profile=profile)
            except AuthError as e:
                st.error(str(e))
            else:
                st.success(f"Usuario «{name.strip().lower()}» creado. Deberá cambiar la contraseña en su primer acceso.")
                if not pwd:
                    st.code(password, language=None)
                    st.caption("Contraseña generada: cópiala y entrégala de forma segura. No se volverá a mostrar.")

    section("Gestionar cuenta")
    target = st.selectbox("Cuenta", [u["usuario"] for u in users], index=None, placeholder="Elige una cuenta",
                          format_func=lambda n: f"{n} · {display_name(next(u for u in users if u['usuario'] == n)['perfil'], '')}")
    if not target:
        return
    current = next(u for u in users if u["usuario"] == target)
    c1, c2, c3, c4 = st.columns(4)
    try:
        if c1.button("Restablecer contraseña", width="stretch"):
            temp = generate_password()
            store.reset_password(target, temp, me)
            st.success("Contraseña restablecida. Entrégala de forma segura; se pedirá cambiarla al ingresar.")
            st.code(temp, language=None)
        if c2.button("Desbloquear", width="stretch", disabled=not current["bloqueado"]):
            store.unlock(target, me); st.rerun()
        other = "usuario" if current["rol"] == "administrador" else "administrador"
        if c3.button(f"Cambiar a {other}", width="stretch"):
            store.set_role(target, other, me); st.rerun()
        if c4.button("Eliminar", width="stretch", disabled=target == me):
            st.session_state["confirm_delete"] = target
        if st.session_state.get("confirm_delete") == target:
            st.warning(f"¿Eliminar la cuenta «{target}»? Esta acción no se puede deshacer.")
            k1, k2 = st.columns(2)
            if k1.button("Sí, eliminar", type="primary"):
                store.delete_user(target, me); st.session_state.pop("confirm_delete"); st.rerun()
            if k2.button("Cancelar"):
                st.session_state.pop("confirm_delete"); st.rerun()
    except AuthError as e:
        st.error(str(e))
    with st.form(f"editar_{target}"):
        st.markdown(f"**Datos generales de {esc(target)}**")
        data = profile_inputs(current["perfil"], current["rol"], cop_editable=True, key=f"ed_{target}")
        if st.form_submit_button("Guardar datos"):
            try:
                store.update_profile(target, data, me, allow_cop=True)
                st.success("Datos actualizados.")
            except AuthError as e:
                st.error(str(e))


def qa_page() -> None:
    header("Pruebas QA", "30 pruebas documentadas del Sprint 2 y 14 adicionales de seguridad, perfil e informes.")
    if st.button("Ejecutar pruebas", type="primary", icon=":material/play_arrow:"):
        with st.spinner("Ejecutando pruebas… (puede tardar un minuto)"):
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run([sys.executable, str(ROOT / "ejecutar_pruebas_qa.py"), "panel_admin"],  # noqa: S603 (argumentos fijos)
                                  cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
        store.audit("pruebas_qa", st.session_state["user"]["usuario"], detail=f"exit={proc.returncode}")
        (st.success if proc.returncode == 0 else st.error)("Resultado: APTA" if proc.returncode == 0 else "Resultado: NO APTA")
    qa = last_qa()
    if qa:
        tiles([("Dictamen", f'<span class="{"pv-ok" if qa["dictamen"] == "APTA" else "pv-bad"}">{esc(qa["dictamen"])}</span>', qa["etiqueta"]),
               ("Documentadas (01-30)", f'{qa["documentadas_aprobadas"]}/30', "aprobadas"),
               ("Total", f'{qa["aprobadas"]}/{qa["total"]}', "aprobadas"),
               ("Fecha", datetime.fromisoformat(qa["fecha_local"]).strftime("%d/%m %H:%M"), "UTC-05")])
        icon = {"APROBADA": '<span class="pv-ok">✓ Aprobada</span>', "FALLIDA": '<span class="pv-bad">✕ Fallida</span>',
                "ERROR": '<span class="pv-bad">✕ Error</span>', "OMITIDA": '<span class="pv-warn">– Omitida</span>'}
        table(["ID", "Grupo", "Prueba", "Estado", "ms"],
              [[r["id"], r["grupo"], r["prueba"].split("_", 2)[-1].replace("_", " "), icon[r["estado"]], r["duracion_ms"]]
               for r in qa["resultados"]], caption="Log de la última ejecución", raw_cols=(3,))
    logs = sorted(EVIDENCE.glob("log_pruebas_QA_*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    if logs:
        section("Logs guardados")
        pick = st.selectbox("Log", [p.name for p in logs])
        st.download_button("Descargar log", (EVIDENCE / pick).read_bytes(), file_name=pick, mime="text/plain")


def audit_page() -> None:
    header("Auditoría", "Accesos y acciones registradas. No se guardan contraseñas.")
    rows = store.read_audit(300)
    if rows:
        kinds = sorted({r["evento"] for r in rows})
        pick = st.multiselect("Filtrar por evento", kinds, format_func=lambda k: k.replace("_", " "))
        rows = [r for r in rows if not pick or r["evento"] in pick]
        table(["Fecha", "Evento", "Usuario", "Actor", "Detalle"],
              [[datetime.fromisoformat(r["utc"]).astimezone().strftime("%d/%m/%Y %H:%M:%S"), r["evento"].replace("_", " "),
                r["usuario"], r["actor"], r["detalle"]] for r in rows[:150]], caption=f"{len(rows)} eventos (más recientes primero)")
        st.download_button("Descargar auditoría (JSONL)", store.audit_path.read_bytes(), file_name="auditoria.jsonl")
    else:
        st.info("Aún no hay eventos.")
    section("Mantenimiento")
    size = sum(f.stat().st_size for f in WORK.rglob("*") if f.is_file()) if WORK.exists() else 0
    st.markdown(f"Archivos temporales de análisis: **{size / 1e6:.1f} MB** · Historial de casos: **{archive.size_mb():.1f} MB**")
    if st.button("Limpiar archivos temporales"):
        shutil.rmtree(WORK, ignore_errors=True)
        store.audit("temporales_limpiados", st.session_state["user"]["usuario"])
        st.success("Temporales eliminados.")


def pct(value) -> str:
    return "No calculable" if value is None else f"{value * 100:.1f} %"


GOALS = [("I01 Precisión (micro)", "precision_micro", 0.65), ("I02 Sensibilidad (micro)", "sensibilidad_micro", 0.70),
         ("I04 F1 (micro)", "f1_micro", 0.67), ("I05 mAP@0.5", "map50", 0.65), ("I06 mAP@0.5:0.95", "map50_95", 0.45)]


def show_metrics(m: dict) -> None:
    g, s1 = m["global"], m["stage1"]
    ci = s1["ic95_wilson"]
    rows = [[name, pct(g[key]), f"≥ {goal:.0%}",
             "—" if g[key] is None else ('<span class="pv-ok">Cumple</span>' if g[key] >= goal else '<span class="pv-bad">No cumple</span>')]
            for name, key, goal in GOALS]
    rows.append(["I03 Sensibilidad Stage 1", f'{pct(s1["sensibilidad"])} (VP {s1["VP"]}, FN {s1["FN"]}'
                 + (f', IC95 % {ci[0] * 100:.0f}–{ci[1] * 100:.0f} %)' if ci else ")"), "≥ 75 %",
                 "—" if s1["sensibilidad"] is None else ('<span class="pv-ok">Cumple</span>' if s1["sensibilidad"] >= .75 else '<span class="pv-bad">No cumple</span>')])
    table(["Indicador", "Valor", "Meta", "Estado"], rows, raw_cols=(3,),
          caption=f'{m["imagenes"]} imágenes · {m["regiones_referencia"]} regiones de referencia · umbral {m["umbral_confianza"]:.2f}')
    section("Por clase")
    table(["Clase", "Soporte", "VP", "FP", "FN", "Precisión", "Sensibilidad", "F1", "AP@0.5", "AP@0.5:0.95"],
          [[c, v["soporte"], v["VP"], v["FP"], v["FN"], pct(v["precision"]), pct(v["sensibilidad"]), pct(v["f1"]),
            pct(v["ap50"]), pct(v["ap50_95"])] for c, v in m["por_clase"].items()])
    section("Matriz de confusión (filas: referencia · columnas: modelo)")
    labels = list(m["matriz_confusion"])
    table(["Referencia"] + labels, [[r] + [str(m["matriz_confusion"][r][c]) for c in labels] for r in labels])
    st.caption(m["nota"])


def evaluation_page() -> None:
    import evaluacion as ev
    from metrics_csv import summarize
    header("Evaluación del modelo", "Métricas sobre una prueba congelada con la calibración vigente (HU07).")
    section("Prueba congelada")
    st.caption("Sube un .zip con imágenes y etiquetas YOLO (carpetas images/ y labels/, como las exporta Roboflow). "
               "No uses este conjunto para ajustar el umbral.")
    data = st.file_uploader("Conjunto de prueba (.zip)", type=["zip"], key="eval_zip")
    if data and st.button("Evaluar", type="primary", icon=":material/analytics:"):
        try:
            det = detector()
            with st.spinner("Analizando el conjunto de prueba…"):
                items = ev.read_test_zip(data.getvalue(), list(core.LABELS))
                preds = ev.predict_items(det, items)
            gts = [g for _, _, gs in items for g in gs]
            metrics = ev.compute_metrics(preds, gts, list(core.LABELS), det.conf)
            folder = DATA / "evaluaciones" / datetime.now().strftime("%Y%m%d_%H%M%S")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "metricas.json").write_bytes(ev.metrics_json({**metrics, "modelo_sha256": det.digest}))
            (folder / "predicciones.csv").write_bytes(ev.predictions_csv(preds, gts))
            st.session_state["eval"] = (metrics, folder.name)
            store.audit("evaluacion_modelo", st.session_state["user"]["usuario"], detail=folder.name)
        except ProductError as e:
            st.error(str(e))
    if "eval" in st.session_state:
        metrics, name = st.session_state["eval"]
        show_metrics(metrics)
        folder = DATA / "evaluaciones" / name
        c1, c2 = st.columns(2)
        c1.download_button("Métricas (JSON)", (folder / "metricas.json").read_bytes(), file_name=f"metricas_{name}.json",
                           width="stretch", icon=":material/download:")
        c2.download_button("Predicciones (CSV)", (folder / "predicciones.csv").read_bytes(),
                           file_name=f"predicciones_{name}.csv", width="stretch", icon=":material/download:")

    section("Recalcular desde predicciones guardadas")
    st.caption("Reproduce las métricas a partir del CSV de predicciones (CA09: diferencia ≤ 0,1 pp).")
    saved = st.file_uploader("Predicciones (.csv)", type=["csv"], key="eval_csv")
    if saved:
        try:
            preds, gts = ev.read_predictions_csv(saved.getvalue())
            show_metrics(ev.compute_metrics(preds, gts, list(core.LABELS), load_config()["conf"]))
        except ProductError as e:
            st.error(str(e))

    section("Serie de entrenamiento")
    series = st.file_uploader("results.csv del entrenamiento", type=["csv"], key="results_csv")
    if series:
        WORK.mkdir(parents=True, exist_ok=True)
        tmp = WORK / "results.csv"; tmp.write_bytes(series.getvalue())
        try:
            s = summarize(tmp)
            row = lambda r: [r["epoch"], pct(r["precision"]), pct(r["recall"]), pct(r["map50"]), pct(r["map50_95"])]
            table(["Fila", "Época", "Precisión", "Sensibilidad", "mAP@0.5", "mAP@0.5:0.95"],
                  [["Última época"] + row(s["last_epoch"]), ["Máx. media armónica P–R"] + row(s["maximum_harmonic_row"]),
                   ["Máx. mAP@0.5:0.95"] + row(s["maximum_map50_95_row"])], caption=f'{s["rows"]} épocas · validación, no prueba')
        except ValueError as e:
            st.error(str(e))
        finally:
            tmp.unlink(missing_ok=True)


def data_page() -> None:
    import datos
    header("Datos", "Preparación de lotes, auditoría de particiones y concordancia entre lectores.")
    me = st.session_state["user"]["usuario"]
    section("Lote desidentificado (HU01)")
    st.caption("Quita metadatos (EXIF, texto PNG) y renombra con códigos. El texto impreso en la imagen no se puede "
               "quitar automáticamente: revisa cada imagen antes de usarla.")
    files = st.file_uploader("Imágenes del lote (PNG o JPEG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    c1, c2 = st.columns(2)
    code = c1.text_input("Código de lote", value=f"LOTE{datetime.now():%Y%m%d}", max_chars=20)
    mapping = c2.file_uploader("Correspondencia opcional (nombre_original, patient_code)", type=["csv"])
    if files and st.button("Preparar lote", type="primary"):
        try:
            pmap = {}
            if mapping:
                import csv as _csv
                import io as _io
                pmap = {r["nombre_original"]: r["patient_code"] for r in _csv.DictReader(_io.StringIO(mapping.getvalue().decode("utf-8-sig")))}
            zip_bytes, manifest, corr = datos.deidentify_batch([(f.name, f.getvalue()) for f in files], code, pmap)
            st.session_state["lote"] = (code, zip_bytes, corr, len(manifest))
            store.audit("lote_desidentificado", me, detail=f"{code}:{len(manifest)} imágenes")
        except (ProductError, KeyError) as e:
            st.error(f"No se pudo preparar el lote: {e}")
    if "lote" in st.session_state:
        code_, zip_bytes, corr, n = st.session_state["lote"]
        st.success(f"Lote {code_} listo: {n} imágenes sin metadatos y manifiesto con huellas SHA-256.")
        d1, d2 = st.columns(2)
        d1.download_button("Lote (.zip)", zip_bytes, file_name=f"{code_}.zip", width="stretch", icon=":material/download:")
        d2.download_button("Correspondencia (solo custodio)", corr, file_name=f"{code_}_correspondencia.csv",
                           width="stretch", icon=":material/lock:")

    section("Auditoría de partición (RF03)")
    man = st.file_uploader("Manifiesto (image_id, patient_code, sha256, subset)", type=["csv"], key="manifest")
    if man:
        WORK.mkdir(parents=True, exist_ok=True)
        tmp = WORK / "manifiesto.csv"; tmp.write_bytes(man.getvalue())
        try:
            r = core.audit_manifest(tmp)
            (st.success if r["structural_check_passed"] else st.error)(
                "Sin pacientes ni huellas compartidos entre subconjuntos." if r["structural_check_passed"]
                else f'{len(r["issues"])} problema(s) estructural(es).')
            tiles([(k, str(v), "imágenes") for k, v in sorted(r["counts"].items())] or [("Filas", str(r["rows"]), "")])
            if r["issues"]:
                table(["Problema"], [[i] for i in r["issues"][:50]])
            st.caption("La auditoría es estructural: no certifica identidad, permisos ni etiquetas clínicas.")
        except ProductError as e:
            st.error(str(e))
        finally:
            tmp.unlink(missing_ok=True)

    section("Concordancia entre lectores (I09)")
    readers = st.file_uploader("Etiquetas de dos lectores (columnas lector_1, lector_2)", type=["csv"], key="kappa")
    if readers:
        try:
            pairs = datos.read_readers_csv(readers.getvalue())
            kq, kl = datos.weighted_kappa(pairs), datos.weighted_kappa(pairs, "linear")
            agree = sum(a == b for a, b in pairs) / len(pairs) if pairs else 0
            tiles([("Kappa ponderado cuadrático", "—" if kq is None else f"{kq:.2f}", "meta ≥ 0,70"),
                   ("Kappa ponderado lineal", "—" if kl is None else f"{kl:.2f}", ""),
                   ("Acuerdo exacto", f"{agree:.0%}", f"{len(pairs)} regiones")])
        except ProductError as e:
            st.error(str(e))


def backups_page() -> None:
    import datos
    header("Respaldos", "Respaldo diario automático y restauración verificada con huellas (RNF07).")
    me = st.session_state["user"]["usuario"]
    folder = DATA / "respaldos_datos"
    if st.button("Crear respaldo ahora", type="primary", icon=":material/backup:"):
        folder.mkdir(parents=True, exist_ok=True)
        data, manifest = datos.create_backup(DATA)
        path = datos.backup_path(folder)
        path.write_bytes(data)
        store.audit("respaldo_creado", me, detail=f"{path.name}:{len(manifest['archivos'])} archivos")
        st.success(f"Respaldo creado: {len(manifest['archivos'])} archivos.")
    backups = sorted(folder.glob("respaldo_*.zip"), reverse=True) if folder.exists() else []
    if backups:
        table(["Respaldo", "Fecha", "Tamaño"], [[b.name, datetime.fromtimestamp(b.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
                                                f"{b.stat().st_size / 1e6:.2f} MB"] for b in backups],
              caption="Se conservan los últimos 7; uno nuevo por día al abrir Estado del sistema.")
        pick = st.selectbox("Descargar respaldo", [b.name for b in backups])
        st.download_button("Descargar", (folder / pick).read_bytes(), file_name=pick, icon=":material/download:")
    section("Restaurar")
    st.warning("Restaurar reemplaza usuarios, configuración, auditoría y casos por los del respaldo. "
               "Antes se guarda un respaldo del estado actual.")
    up = st.file_uploader("Respaldo (.zip)", type=["zip"], key="restore")
    confirm = st.checkbox("Entiendo que se reemplazarán los datos actuales")
    if up and st.button("Restaurar respaldo", disabled=not confirm):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            pre, _ = datos.create_backup(DATA)
            datos.backup_path(folder, "_previo").write_bytes(pre)
            report = datos.restore_backup(up.getvalue(), DATA)
            store.audit("respaldo_restaurado", me, detail=f"{report['archivos']} archivos en {report['segundos']} s")
            st.success(f"Restaurados {report['archivos']} archivos en {report['segundos']} s; huellas verificadas.")
        except ProductError as e:
            st.error(str(e))


# ─────────────────────────────── navegación ───────────────────────────────
def sidebar(user: dict) -> None:
    with st.sidebar:
        p = user.get("perfil") or {}
        role = "Administrador" if user["rol"] == "administrador" else "Usuario"
        extra = f" · COP {esc(p['cop'])}" if p.get("cop") else ""
        st.markdown(f'<div style="display:flex;gap:.7rem;align-items:center;margin:.2rem 0 .6rem">'
                    f'<div class="pv-appicon" style="width:40px;height:40px;border-radius:10px;margin:0;flex:none">'
                    f'{TOOTH.replace("40", "24")}</div><div><div style="font-weight:600;line-height:1.2">'
                    f'{esc(display_name(p, user["usuario"]))}</div>'
                    f'<span class="pv-pill">{role}{extra}</span></div></div>', unsafe_allow_html=True)
        if st.button("Cerrar sesión", width="stretch", icon=":material/logout:"):
            logout("Sesión cerrada.")
            st.rerun()
        st.caption(core.VERSION)


def main() -> None:
    inject_css()
    check_timeout()
    try:
        cloud_bootstrap()
    except (ProductError, OSError) as e:
        st.error(f"Configuración del despliegue: {e}")
    preload_model()  # empieza a cargar el modelo mientras el usuario inicia sesión
    user = st.session_state.get("user")
    if not user:
        st.navigation([st.Page(login_view, title="Iniciar sesión", icon=":material/lock:")], position="hidden").run()
        return
    if user.get("debe_cambiar"):
        sidebar(user)
        header("Cambia tu contraseña")
        change_password_form(forced=True)
        return
    if user["rol"] == "usuario" and not profile_complete(store.get_profile(user["usuario"]), "usuario"):
        sidebar(user)
        header("Completa tu perfil")
        profile_form(forced=True)
        return
    account = st.Page(account_page, title="Mi cuenta", icon=":material/account_circle:", url_path="cuenta")
    if user["rol"] == "administrador":
        pages = {"Mantenimiento": [
            st.Page(status_page, title="Estado del sistema", icon=":material/monitor_heart:", default=True),
            st.Page(model_page, title="Modelo y calibración", icon=":material/memory:", url_path="modelo"),
            st.Page(evaluation_page, title="Evaluación del modelo", icon=":material/analytics:", url_path="evaluacion"),
            st.Page(data_page, title="Datos", icon=":material/dataset:", url_path="datos"),
            st.Page(users_page, title="Usuarios", icon=":material/group:", url_path="usuarios"),
            st.Page(backups_page, title="Respaldos", icon=":material/backup:", url_path="respaldos"),
            st.Page(qa_page, title="Pruebas QA", icon=":material/task_alt:", url_path="pruebas"),
            st.Page(audit_page, title="Auditoría", icon=":material/receipt_long:", url_path="auditoria")],
            "Cuenta": [account]}
    else:
        pages = {"PerioVision": [
            st.Page(analyze_page, title="Analizar radiografía", icon=":material/radiology:", default=True),
            st.Page(history_page, title="Historial", icon=":material/history:", url_path="historial")],
            "Cuenta": [account]}
    nav = st.navigation(pages)
    sidebar(user)
    nav.run()


main()
