"""Autenticación de PerioVision: usuarios, roles, hash de contraseñas y bloqueo por intentos.

- Contraseñas: PBKDF2-HMAC-SHA256 con sal aleatoria de 16 bytes y 600 000 iteraciones
  (recomendación OWASP 2023). Nunca se guarda ni se registra la contraseña en claro.
- Comparación en tiempo constante (hmac.compare_digest) y verificación ficticia para
  usuarios inexistentes, de modo que la respuesta no revela si el usuario existe.
- Bloqueo temporal tras 5 intentos fallidos consecutivos.
- Solo dos roles: "administrador" (mantenimiento) y "usuario" (uso de la web).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROLES = ("administrador", "usuario")
ITERATIONS = 600_000
MAX_FAILED = 5
LOCK_MINUTES = 5
USERNAME_RE = re.compile(r"[a-z0-9._-]{3,32}")
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/~"
GENERIC_ERROR = "Usuario o contraseña incorrectos."

_lock = threading.RLock()


class AuthError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> dict:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {"algorithm": "pbkdf2_sha256", "iterations": iterations,
            "salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(digest).decode()}


def verify_password(password: str, record: dict) -> bool:
    salt = base64.b64decode(record["salt"])
    expected = base64.b64decode(record["hash"])
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(record["iterations"]))
    return hmac.compare_digest(digest, expected)


_DUMMY = hash_password(secrets.token_urlsafe(16))


def validate_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise AuthError("El usuario debe tener de 3 a 32 caracteres: minúsculas, números, punto, guion o guion bajo.")
    return username


def password_problems(password: str, username: str = "") -> list[str]:
    problems = []
    if len(password or "") < 10:
        problems.append("al menos 10 caracteres")
    if not re.search(r"[a-z]", password or ""):
        problems.append("una minúscula")
    if not re.search(r"[A-Z]", password or ""):
        problems.append("una mayúscula")
    if not re.search(r"\d", password or ""):
        problems.append("un número")
    if not any(c in SYMBOLS for c in password or ""):
        problems.append("un símbolo")
    if username and username.lower() in (password or "").lower():
        problems.append("no contener el nombre de usuario")
    if len(password or "") > 128:
        problems.append("como máximo 128 caracteres")
    return problems


def validate_password(password: str, username: str = "") -> None:
    problems = password_problems(password, username)
    if problems:
        raise AuthError("La contraseña debe tener " + ", ".join(problems) + ".")


SPECIALTIES = ("Odontología general", "Periodoncia", "Radiología oral y maxilofacial", "Implantología", "Otra")
NAME_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{2,60}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
COP_RE = re.compile(r"\d{1,6}")
PROFILE_FIELDS = ("nombres", "apellidos", "correo", "cop", "especialidad", "fecha_nacimiento")


def validate_profile(profile: dict, role: str) -> dict:
    """Normaliza y valida los datos generales. El COP es obligatorio para el rol usuario."""
    p = {k: str(profile.get(k) or "").strip() for k in PROFILE_FIELDS}
    errors = []
    for key, label in (("nombres", "Nombres"), ("apellidos", "Apellidos")):
        if not NAME_RE.fullmatch(p[key]):
            errors.append(f"{label}: de 2 a 60 letras")
        p[key] = " ".join(w[:1].upper() + w[1:] for w in p[key].split())
    p["correo"] = p["correo"].lower()
    if not EMAIL_RE.fullmatch(p["correo"]) or len(p["correo"]) > 120:
        errors.append("correo electrónico válido")
    if p["cop"] or role == "usuario":
        p["cop"] = p["cop"].lstrip("0") or p["cop"]
        if not COP_RE.fullmatch(p["cop"]):
            errors.append("N.º de COP de 1 a 6 dígitos")
    if p["especialidad"] and p["especialidad"] not in SPECIALTIES:
        errors.append("especialidad de la lista")
    if p["fecha_nacimiento"]:
        try:
            born = datetime.fromisoformat(p["fecha_nacimiento"]).date()
            age = (_now().date() - born).days / 365.25
            if not 18 <= age <= 100:
                errors.append("fecha de nacimiento (edad entre 18 y 100 años)")
            p["fecha_nacimiento"] = born.isoformat()
        except ValueError:
            errors.append("fecha de nacimiento AAAA-MM-DD")
    if errors:
        raise AuthError("Revisa: " + "; ".join(errors) + ".")
    return p


def profile_complete(profile: dict | None, role: str) -> bool:
    try:
        validate_profile(profile or {}, role)
        return True
    except AuthError:
        return False


def display_name(profile: dict | None, username: str) -> str:
    profile = profile or {}
    full = f"{profile.get('nombres', '')} {profile.get('apellidos', '')}".strip()
    return full or username


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + SYMBOLS
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if not password_problems(value):
            return value


class UserStore:
    """Almacén JSON con escritura atómica. Ruta por defecto: datos/usuarios.json."""

    def __init__(self, path: str | Path, audit_path: str | Path | None = None):
        self.path = Path(path)
        self.audit_path = Path(audit_path) if audit_path else self.path.with_name("auditoria.jsonl")

    # ---------- persistencia ----------
    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, users: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def audit(self, event: str, username: str = "", actor: str = "", detail: str = "") -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        row = {"utc": _now().isoformat(timespec="seconds"), "evento": event,
               "usuario": username, "actor": actor, "detalle": detail}
        with _lock, self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_audit(self, limit: int = 200) -> list[dict]:
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in reversed(lines) if line.strip()]

    # ---------- consultas ----------
    def list_users(self) -> list[dict]:
        with _lock:
            users = self._load()
        return [{"usuario": name, "rol": u["role"], "creado": u["created"],
                 "ultimo_acceso": u.get("last_login"), "bloqueado": self._is_locked(u),
                 "intentos_fallidos": u.get("failed", 0), "debe_cambiar": u.get("must_change", False),
                 "perfil": u.get("profile", {})}
                for name, u in sorted(users.items())]

    def get_profile(self, username: str) -> dict:
        with _lock:
            return dict(self._load().get(username, {}).get("profile", {}))

    def update_profile(self, username: str, profile: dict, actor: str, allow_cop: bool = False) -> dict:
        """Actualiza los datos generales. Solo el administrador (allow_cop) puede cambiar el COP."""
        with _lock:
            users = self._load()
            if username not in users:
                raise AuthError("Usuario no encontrado.")
            current = users[username].get("profile", {})
            if not allow_cop and current.get("cop"):
                profile = {**profile, "cop": current["cop"]}
            clean = validate_profile(profile, users[username]["role"])
            users[username]["profile"] = clean
            self._save(users)
        self.audit("perfil_actualizado", username, actor)
        return clean

    def exists(self, username: str) -> bool:
        with _lock:
            return username in self._load()

    @staticmethod
    def _is_locked(user: dict) -> bool:
        until = user.get("locked_until")
        return bool(until) and datetime.fromisoformat(until) > _now()

    # ---------- altas y cambios ----------
    def create_user(self, username: str, password: str, role: str, actor: str = "sistema",
                    must_change: bool = True, profile: dict | None = None) -> None:
        username = validate_username(username)
        if role not in ROLES:
            raise AuthError("Rol no permitido. Use administrador o usuario.")
        validate_password(password, username)
        clean_profile = validate_profile(profile, role) if profile and any(profile.values()) else {}
        with _lock:
            users = self._load()
            if username in users:
                raise AuthError("Ese usuario ya existe.")
            users[username] = {"role": role, "password": hash_password(password),
                               "created": _now().isoformat(timespec="seconds"),
                               "failed": 0, "locked_until": None, "last_login": None,
                               "must_change": must_change, "profile": clean_profile}
            self._save(users)
        self.audit("usuario_creado", username, actor, role)

    def authenticate(self, username: str, password: str) -> dict:
        """Devuelve {'usuario','rol','debe_cambiar'} o lanza AuthError con mensaje genérico."""
        try:
            username = validate_username(username)
        except AuthError:
            verify_password(password or "", _DUMMY)
            raise AuthError(GENERIC_ERROR) from None
        with _lock:
            users = self._load()
            user = users.get(username)
            if user is None:
                verify_password(password or "", _DUMMY)  # tiempo similar al de un usuario real
                self.audit("acceso_fallido", username, detail="usuario inexistente")
                raise AuthError(GENERIC_ERROR)
            if self._is_locked(user):
                self.audit("acceso_bloqueado", username)
                raise AuthError(f"Cuenta bloqueada temporalmente por intentos fallidos. Intente en {LOCK_MINUTES} minutos o contacte al administrador.")
            if not verify_password(password or "", user["password"]):
                user["failed"] = user.get("failed", 0) + 1
                if user["failed"] >= MAX_FAILED:
                    user["locked_until"] = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat()
                    user["failed"] = 0
                    self.audit("cuenta_bloqueada", username, detail=f"{MAX_FAILED} intentos fallidos")
                else:
                    self.audit("acceso_fallido", username, detail=f"intento {user['failed']}")
                self._save(users)
                raise AuthError(GENERIC_ERROR)
            user["failed"] = 0
            user["locked_until"] = None
            user["last_login"] = _now().isoformat(timespec="seconds")
            self._save(users)
        self.audit("acceso_correcto", username, detail=user["role"])
        return {"usuario": username, "rol": user["role"], "debe_cambiar": user.get("must_change", False),
                "perfil": user.get("profile", {})}

    def change_password(self, username: str, current: str, new: str) -> None:
        with _lock:
            users = self._load()
            user = users.get(username)
            if user is None or not verify_password(current or "", user["password"]):
                raise AuthError("La contraseña actual no es correcta.")
            if current == new:
                raise AuthError("La nueva contraseña debe ser distinta de la actual.")
            validate_password(new, username)
            user["password"] = hash_password(new)
            user["must_change"] = False
            self._save(users)
        self.audit("contrasena_cambiada", username, username)

    def reset_password(self, username: str, new: str, actor: str) -> None:
        validate_password(new, username)
        with _lock:
            users = self._load()
            if username not in users:
                raise AuthError("Usuario no encontrado.")
            users[username].update(password=hash_password(new), must_change=True, failed=0, locked_until=None)
            self._save(users)
        self.audit("contrasena_restablecida", username, actor)

    def unlock(self, username: str, actor: str) -> None:
        with _lock:
            users = self._load()
            if username not in users:
                raise AuthError("Usuario no encontrado.")
            users[username].update(failed=0, locked_until=None)
            self._save(users)
        self.audit("cuenta_desbloqueada", username, actor)

    def set_role(self, username: str, role: str, actor: str) -> None:
        if role not in ROLES:
            raise AuthError("Rol no permitido.")
        with _lock:
            users = self._load()
            if username not in users:
                raise AuthError("Usuario no encontrado.")
            if users[username]["role"] == "administrador" and role != "administrador" and self._admins(users) == 1:
                raise AuthError("Debe existir al menos un administrador.")
            users[username]["role"] = role
            self._save(users)
        self.audit("rol_cambiado", username, actor, role)

    def delete_user(self, username: str, actor: str) -> None:
        if username == actor:
            raise AuthError("No puede eliminar su propia cuenta.")
        with _lock:
            users = self._load()
            if username not in users:
                raise AuthError("Usuario no encontrado.")
            if users[username]["role"] == "administrador" and self._admins(users) == 1:
                raise AuthError("Debe existir al menos un administrador.")
            del users[username]
            self._save(users)
        self.audit("usuario_eliminado", username, actor)

    @staticmethod
    def _admins(users: dict) -> int:
        return sum(u["role"] == "administrador" for u in users.values())
