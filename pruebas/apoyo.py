"""Utilidades compartidas por las suites de prueba (no contiene pruebas)."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "ejemplos" / "radiografia_ejemplo.jpg"
MODEL = ROOT / "best.pt"
PASSWORD = "Prueba-Local-2026!"
PERFIL = {"nombres": "Lucía", "apellidos": "Prueba Ramos", "correo": "lucia.prueba@ejemplo.test",
          "cop": "54321", "especialidad": "Periodoncia", "fecha_nacimiento": "1990-05-17"}

_detector = None


def real_detector():
    """Un solo detector YOLO por proceso (cargar pesos cuesta ~1 s)."""
    global _detector
    if _detector is None:
        from core import YoloDetector
        _detector = YoloDetector(MODEL, authorization=True)
    return _detector


class TempData:
    """Carpeta de datos aislada para la app (PERIOVISION_DATA) con usuarios de prueba."""

    def __init__(self, with_profile: bool = True):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        from auth import UserStore
        self.store = UserStore(self.path / "usuarios.json")
        self.store.create_user("qa.admin", PASSWORD, "administrador", must_change=False,
                               profile={**PERFIL, "nombres": "Admin", "cop": ""})
        self.store.create_user("qa.user", PASSWORD, "usuario", must_change=False,
                               profile=PERFIL if with_profile else None)
        self.store.create_user("qa.nuevo", PASSWORD, "usuario", must_change=True)
        self._old = os.environ.get("PERIOVISION_DATA")
        os.environ["PERIOVISION_DATA"] = str(self.path)

    def close(self):
        if self._old is None:
            os.environ.pop("PERIOVISION_DATA", None)
        else:
            os.environ["PERIOVISION_DATA"] = self._old
        self._tmp.cleanup()


def app_test(timeout: int = 120):
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=timeout)


def logged_app(user: str, role: str, profile: dict | None = None, timeout: int = 120):
    at = app_test(timeout)
    at.session_state["user"] = {"usuario": user, "rol": role, "debe_cambiar": False, "perfil": profile or {}}
    at.session_state["last_seen"] = time.time()
    return at


def pages(at) -> dict[str, str]:
    """Páginas que la navegación registró en la última ejecución: {url_path: nombre}."""
    return {info.get("url_pathname", ""): info["page_name"] for info in at._registered_pages.values()}


def goto(at, url_path: str, page_hash: str | None = None):
    """Navega a una página por su url_path (o por un hash tomado de otra sesión) y ejecuta."""
    if page_hash is None:
        page_hash = next(h for h, i in at._registered_pages.items() if i.get("url_pathname", "") == url_path)
    at._page_hash = page_hash
    return at.run()


def title(at) -> str:
    """Texto del título grande (role=heading, aria-level=1) de la página mostrada."""
    import re
    for m in at.markdown:
        if 'aria-level="1"' in m.value:
            return re.sub(r"<[^>]+>", " ", m.value).split("  ")[0].strip()
    return ""


def percentile(values: list[float], p: float) -> float:
    """Percentil por rango más próximo (el método citado en el informe del proyecto)."""
    ordered = sorted(values)
    import math
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]
