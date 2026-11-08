"""Pruebas de SISTEMA 63-70: la aplicación Streamlit completa (app.py) ejecutada con AppTest."""
import json

import core
import time
import unittest

from pruebas.apoyo import PASSWORD, PERFIL, TempData, app_test, goto, logged_app, pages, title


class SistemaTests(unittest.TestCase):
    def setUp(self):
        self.data = TempData()

    def tearDown(self):
        self.data.close()

    def login(self, user, password=PASSWORD):
        at = app_test().run()
        at.text_input[0].input(user); at.text_input[1].input(password)
        at.button[0].click().run()
        return at

    def test_63_pantalla_de_acceso_sin_contenido_protegido(self):
        at = app_test().run()
        self.assertEqual([t.label for t in at.text_input], ["Usuario", "Contraseña"])
        self.assertEqual(list(pages(at).values()), ["Iniciar sesión"])
        self.assertTrue(any(core.VERSION in m.value for m in at.markdown))
        self.assertFalse(at.exception)

    def test_64_acceso_incorrecto_y_correcto(self):
        at = self.login("qa.admin", "Incorrecta-2026!")
        self.assertEqual([e.value for e in at.error], ["Usuario o contraseña incorrectos."])
        at = self.login("qa.admin")
        self.assertEqual(title(at), "Estado del sistema")
        self.assertFalse(at.exception)

    def test_65_navegacion_por_rol(self):
        admin = self.login("qa.admin")
        self.assertEqual(set(pages(admin).values()),
                         {"Estado del sistema", "Modelo y calibración", "Evaluación del modelo", "Datos", "Usuarios",
                          "Respaldos", "Pruebas QA", "Auditoría", "Mi cuenta"})
        user = self.login("qa.user")
        self.assertEqual(set(pages(user).values()), {"Analizar radiografía", "Historial", "Mi cuenta"})
        self.assertEqual(title(user), "Analizar radiografía")

    def test_66_cambio_de_contrasena_obligatorio(self):
        at = self.login("qa.nuevo")
        self.assertEqual(title(at), "Cambia tu contraseña")
        self.assertIn("cambia la contraseña inicial", at.warning[0].value)

    def test_67_perfil_obligatorio_para_usuario(self):
        self.data.store.update_profile("qa.user", PERFIL, "qa.admin", allow_cop=True)
        users = json.loads(self.data.store.path.read_text(encoding="utf-8"))
        users["qa.user"]["profile"] = {}
        self.data.store.path.write_text(json.dumps(users), encoding="utf-8")
        at = self.login("qa.user")
        self.assertEqual(title(at), "Completa tu perfil")
        self.assertIn("N.º de COP (Colegio Odontológico del Perú)", [t.label for t in at.text_input])

    def test_68_cierre_de_sesion_por_inactividad(self):
        at = logged_app("qa.user", "usuario", PERFIL)
        at.session_state["last_seen"] = time.time() - 31 * 60
        at.run()
        self.assertEqual([t.label for t in at.text_input], ["Usuario", "Contraseña"])
        self.assertIn("inactividad", at.info[0].value)

    def test_69_admin_crea_usuario_desde_formulario(self):
        at = goto(logged_app("qa.admin", "administrador").run(), "usuarios")
        fields = {t.label: t for t in at.text_input}
        fields["Nombre de usuario"].input("dr.prueba")
        fields["Contraseña inicial (vacía = generar una segura)"].input("Inicial-Prueba-2026#")
        fields["Nombres"].input("Carlos"); fields["Apellidos"].input("Prueba")
        fields["Correo electrónico"].input("carlos@ejemplo.test")
        fields["N.º de COP (Colegio Odontológico del Perú)"].input("777")
        next(b for b in at.button if b.label == "Crear usuario").click().run()
        self.assertTrue(self.data.store.exists("dr.prueba"))
        self.assertEqual(self.data.store.get_profile("dr.prueba")["cop"], "777")

    def test_70_calibracion_del_admin_y_vista_de_usuario_sin_parametros(self):
        at = goto(logged_app("qa.admin", "administrador").run(), "modelo")
        at.slider[0].set_value(0.40)
        next(b for b in at.button if b.label == "Guardar calibración").click().run()
        cfg = json.loads((self.data.path / "config.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(cfg["conf"], 0.40)
        user = logged_app("qa.user", "usuario", PERFIL).run()
        self.assertEqual(len(user.slider) + len(user.select_slider) + len(user.checkbox), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
