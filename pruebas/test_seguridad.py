"""Pruebas adicionales 31-40: inicio de sesión, cifrado de contraseñas y roles (RNF04)."""
import json
from pathlib import Path
import tempfile
import unittest

import auth
from auth import AuthError, UserStore

GOOD = "Clave-Segura-2026"


class SeguridadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = UserStore(Path(self.tmp.name) / "usuarios.json")
        self.store.create_user("admin", GOOD, "administrador", must_change=False)
        self.store.create_user("usuario", GOOD + "x", "usuario", must_change=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_31_contrasena_no_se_guarda_en_claro(self):
        raw = self.store.path.read_text(encoding="utf-8")
        self.assertNotIn(GOOD, raw)
        record = json.loads(raw)["admin"]["password"]
        self.assertEqual(record["algorithm"], "pbkdf2_sha256")
        self.assertGreaterEqual(record["iterations"], 600_000)

    def test_32_sal_unica_por_usuario(self):
        a = auth.hash_password(GOOD); b = auth.hash_password(GOOD)
        self.assertNotEqual(a["salt"], b["salt"]); self.assertNotEqual(a["hash"], b["hash"])

    def test_33_acceso_correcto_devuelve_rol(self):
        self.assertEqual(self.store.authenticate("admin", GOOD)["rol"], "administrador")
        self.assertEqual(self.store.authenticate("USUARIO ", GOOD + "x")["rol"], "usuario")

    def test_34_mensaje_generico_no_revela_usuario(self):
        with self.assertRaisesRegex(AuthError, "incorrectos") as wrong_pass:
            self.store.authenticate("admin", "Otra-Clave-2026")
        with self.assertRaisesRegex(AuthError, "incorrectos") as no_user:
            self.store.authenticate("fantasma", GOOD)
        self.assertEqual(str(wrong_pass.exception), str(no_user.exception))

    def test_35_bloqueo_tras_intentos_fallidos(self):
        for _ in range(auth.MAX_FAILED):
            with self.assertRaises(AuthError):
                self.store.authenticate("usuario", "Mala-Clave-2026")
        with self.assertRaisesRegex(AuthError, "bloqueada"):
            self.store.authenticate("usuario", GOOD + "x")
        self.store.unlock("usuario", "admin")
        self.assertEqual(self.store.authenticate("usuario", GOOD + "x")["rol"], "usuario")

    def test_36_politica_de_contrasena(self):
        for weak in ["corta1!", "sinmayusculas-2026", "SINMINUSCULAS-2026", "SinNumeros-Clave", "SinSimbolo2026", "Admin-Clave-2026"]:
            with self.assertRaises(AuthError, msg=weak):
                self.store.create_user("nuevo", weak.replace("Admin", "nuevo"), "usuario")

    def test_37_solo_dos_roles(self):
        with self.assertRaises(AuthError):
            self.store.create_user("otro", GOOD, "superusuario")
        self.assertEqual(auth.ROLES, ("administrador", "usuario"))

    def test_38_usuario_invalido_o_inyeccion_rechazada(self):
        for bad in ["../admin", "a", "admin' OR '1'='1", "=cmd()", ""]:
            with self.assertRaises(AuthError):
                self.store.authenticate(bad, GOOD)

    def test_39_siempre_queda_un_administrador(self):
        with self.assertRaises(AuthError):
            self.store.set_role("admin", "usuario", "admin")
        with self.assertRaises(AuthError):
            self.store.delete_user("admin", "otro_admin")
        with self.assertRaises(AuthError):
            self.store.delete_user("admin", "admin")

    def test_40_cambio_de_contrasena_y_auditoria_sin_secretos(self):
        self.store.change_password("usuario", GOOD + "x", "Nueva-Clave-2027")
        with self.assertRaises(AuthError):
            self.store.authenticate("usuario", GOOD + "x")
        self.assertEqual(self.store.authenticate("usuario", "Nueva-Clave-2027")["rol"], "usuario")
        log = self.store.audit_path.read_text(encoding="utf-8")
        self.assertIn("contrasena_cambiada", log)
        self.assertNotIn("Nueva-Clave-2027", log); self.assertNotIn(GOOD, log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
