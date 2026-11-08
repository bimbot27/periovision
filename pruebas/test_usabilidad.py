"""Pruebas de USABILIDAD y ACCESIBILIDAD 95-100 (WCAG 2.1 AA y heurísticas de Nielsen, automatizables)."""
import re
import tomllib
import unittest

from pruebas.apoyo import PERFIL, ROOT, TempData, app_test, goto, logged_app


def _rgb(color: str, over: tuple = (255, 255, 255)) -> tuple:
    color = color.strip()
    if color.startswith("#"):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", color))
    return tuple(round(a * c + (1 - a) * o) for c, o in zip((r, g, b), over))


def contrast(fg: str, bg: str) -> float:
    def lum(rgb):
        ch = [c / 255 for c in rgb]
        ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    b = _rgb(bg); f = _rgb(fg, over=b)
    hi, lo = sorted((lum(f), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class UsabilidadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.tokens = {k: (a, b) for k, a, b in re.findall(r'"([\w-]+)": \("([^"]+)", "([^"]+)"\)', cls.src)}
        cls.theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]

    def setUp(self):
        self.data = TempData()

    def tearDown(self):
        self.data.close()

    def test_95_contraste_wcag_aa_en_claro_y_oscuro(self):
        failures = []
        for mode, i in (("claro", 0), ("oscuro", 1)):
            card, bg = self.tokens["card"][i], self.theme[("light", "dark")[i]]["backgroundColor"]
            for token in ("label", "secondary", "blue", "green", "orange", "red"):
                for surface in (card, bg):
                    ratio = contrast(self.tokens[token][i], surface)
                    if ratio < 4.5:
                        failures.append(f"{mode}: {token} sobre {surface} = {ratio:.2f}")
            button = contrast("#FFFFFF", self.theme[("light", "dark")[i]]["primaryColor"])
            if button < 4.5:
                failures.append(f"{mode}: texto del botón principal = {button:.2f}")
        self.assertEqual(failures, [])

    def test_96_todos_los_campos_tienen_etiqueta_visible(self):
        screens = [app_test().run(), goto(logged_app("qa.user", "usuario", PERFIL).run(), "cuenta"),
                   goto(logged_app("qa.admin", "administrador").run(), "usuarios")]
        for at in screens:
            for kind in ("text_input", "selectbox", "date_input", "text_area", "slider", "radio"):
                for w in at.get(kind):
                    label = getattr(w, "label", None) or w.proto.label
                    self.assertTrue(label and label.strip(), f"{kind} sin etiqueta")
                    self.assertNotEqual(getattr(w.proto, "label_visibility", None) and w.proto.label_visibility.value, 2)

    def test_97_mensajes_de_error_claros_y_en_espanol(self):
        at = app_test().run()
        at.button[0].click().run()
        self.assertEqual(at.error[0].value, "Escribe tu usuario y tu contraseña.")
        account = goto(logged_app("qa.user", "usuario", PERFIL).run(), "cuenta")
        fields = {t.label: t for t in account.text_input}
        fields["Correo electrónico"].input("sin-arroba")
        next(b for b in account.button if b.label == "Guardar datos").click().run()
        self.assertTrue(any("correo electrónico válido" in e.value for e in account.error))

    def test_98_objetivos_tactiles_foco_movimiento_e_idioma(self):
        self.assertIn("min-height: 44px", self.src)                       # HIG: objetivos de 44 pt
        self.assertIn(":focus-visible", self.src)                         # WCAG 2.4.7
        self.assertIn("prefers-reduced-motion", self.src)                 # WCAG 2.3.3
        self.assertIn("documentElement.lang='es'", self.src)              # WCAG 3.1.1
        self.assertIn('role="heading"', self.src)                         # WCAG 1.3.1
        self.assertIn('<th scope="col">', self.src)                       # tablas con encabezados

    def test_99_flujo_de_analisis_sin_pasos_innecesarios(self):
        at = logged_app("qa.user", "usuario", PERFIL).run()
        self.assertEqual(len(at.get("file_uploader")), 1)
        self.assertEqual(len(at.slider) + len(at.select_slider) + len(at.checkbox), 0)
        self.assertEqual(len([b for b in at.button if b.label != "Cerrar sesión"]), 0)  # nada que hacer antes de cargar

    def test_100_estados_vacios_con_guia(self):
        at = logged_app("qa.user", "usuario", PERFIL).run()
        self.assertTrue(any("Sube una radiografía para iniciar el análisis." in m.value for m in at.markdown))
        hist = goto(at, "historial")
        self.assertTrue(any("Aún no hay casos validados" in m.value for m in hist.markdown))


if __name__ == "__main__":
    unittest.main(verbosity=2)
