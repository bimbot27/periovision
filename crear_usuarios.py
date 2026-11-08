"""Crea los usuarios iniciales (un administrador y un usuario) con contraseñas aleatorias.

Las contraseñas se guardan cifradas (hash PBKDF2) en datos/usuarios.json y, en claro,
solo una vez en CREDENCIALES_INICIALES.txt para entregarlas. Ambas cuentas deben
cambiar su contraseña en el primer acceso. Borre ese archivo después de entregarlas.

Uso:  .venv\\Scripts\\python.exe crear_usuarios.py
"""
from pathlib import Path

from auth import UserStore, generate_password

ROOT = Path(__file__).resolve().parent
store = UserStore(ROOT / "datos" / "usuarios.json")
created = []
for username, role in (("admin", "administrador"), ("usuario", "usuario")):
    if store.exists(username):
        print(f"'{username}' ya existe; no se modifica.")
        continue
    password = generate_password()
    store.create_user(username, password, role, actor="instalacion", must_change=True)
    created.append((username, role, password))

if created:
    out = ROOT / "CREDENCIALES_INICIALES.txt"
    with out.open("a", encoding="utf-8") as f:
        f.write("PerioVision · credenciales iniciales (cambiar en el primer acceso y borrar este archivo)\n")
        for username, role, password in created:
            f.write(f"  Rol: {role:<14} Usuario: {username:<10} Contraseña: {password}\n")
    print(f"Usuarios creados: {', '.join(u for u, _, _ in created)}. Credenciales en {out.name}.")
