"""Cuentas de la app, permisos y auditoria de cambios.

La identidad se toma de la sesion de Windows, no de una clave: no hay
passwords. Cada persona entra con su cuenta de Windows del dominio.

La identidad se resuelve por esta via, de la mas segura a la menos:

1. GetUserNameExW        -> DOMINIO\\usuario, leido del token del proceso
2. SID + LookupAccountSid-> DOMINIO\\usuario, si la anterior no existe
3. GetUserNameW          -> solo el nombre de usuario
4. Variables de entorno  -> falseable a proposito, deja rastro en el log

Si ninguna funciona se devuelve None y la app cierra: caer a variables de
entorno en silencio permitiria falsear la identidad.
"""

import ctypes
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONTROL = BASE_DIR / "db" / "control.db"
ESQUEMA = BASE_DIR / "db" / "control_schema.sql"
WFH = BASE_DIR / "db" / "wfh.db"

ROLES = ("admin", "usuario")

# Unicas cuentas de Windows autorizadas a crear el primer admin. Sin esta
# lista, borrar control.db daria acceso total a quien abriera la app.
PUEDE_CREAR_ADMIN = {
    "david.arjona",
    "julio.lerma",
}

_aviso = []


def avisos() -> list[str]:
    return list(_aviso)


# --- identidad de Windows -----------------------------------------------
def _por_getusernameex() -> str | None:
    from ctypes import wintypes
    fn = ctypes.windll.advapi32.GetUserNameExW
    fn.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPWSTR,
                   ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    tam = wintypes.DWORD(0)
    if not fn(None, 0, None, ctypes.byref(tam)):
        return None
    buf = ctypes.create_unicode_buffer(tam.value)
    return buf.value if fn(None, 0, buf, ctypes.byref(tam)) else None


def _por_sid() -> str | None:
    from ctypes import wintypes
    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformationW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.LookupAccountSidW.argtypes = [wintypes.LPWSTR, ctypes.c_void_p,
                                           wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD),
                                           wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD),
                                           ctypes.c_void_p]
    advapi32.LookupAccountSidW.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008,
                                     ctypes.byref(token)):
        return None
    try:
        tam = wintypes.DWORD(0)
        advapi32.GetTokenInformationW(token, 1, None, 0, ctypes.byref(tam))
        datos = ctypes.create_string_buffer(tam.value)
        if not advapi32.GetTokenInformationW(token, 1, datos, ctypes.byref(tam)):
            return None

        class SIDyAtributos(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Atributos", wintypes.DWORD)]

        puntero = ctypes.cast(datos, ctypes.POINTER(SIDyAtributos))
        largo = wintypes.DWORD(0)
        advapi32.ConvertSidToStringSidW(puntero.contents.Sid, ctypes.byref(largo))
        sid = ctypes.create_unicode_buffer(largo.value)
        if not advapi32.ConvertSidToStringSidW(puntero.contents.Sid,
                                               ctypes.byref(sid)):
            return None

        n_nombre = wintypes.DWORD(0)
        n_dominio = wintypes.DWORD(0)
        advapi32.LookupAccountSidW(None, puntero.contents.Sid, None,
                                   ctypes.byref(n_nombre), None,
                                   ctypes.byref(n_dominio), None)
        nombre = ctypes.create_unicode_buffer(max(n_nombre.value, 1))
        dominio = ctypes.create_unicode_buffer(max(n_dominio.value, 1))
        if not advapi32.LookupAccountSidW(None, puntero.contents.Sid, nombre,
                                          ctypes.byref(n_nombre), dominio,
                                          ctypes.byref(n_dominio), None):
            return None
        if dominio.value:
            return f"{dominio.value}\\{nombre.value}"
        return nombre.value
    finally:
        kernel32.CloseHandle(token)


def _por_getusername() -> str | None:
    from ctypes import wintypes
    fn = ctypes.windll.kernel32.GetUserNameW
    fn.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    buf = ctypes.create_unicode_buffer(256)
    tam = wintypes.DWORD(len(buf))
    return buf.value if fn(buf, ctypes.byref(tam)) else None


def identidad() -> str | None:
    """DOMINIO\\usuario de la sesion de Windows, o None si no se puede."""
    if not hasattr(ctypes, "windll"):
        _aviso.append("No es Windows: la identidad de usuario no esta disponible.")
        return None

    for nombre, fn in (("GetUserNameExW", _por_getusernameex),
                       ("SID", _por_sid),
                       ("GetUserNameW", _por_getusername)):
        try:
            valor = fn()
        except Exception as error:
            _aviso.append(f"{nombre} fallo: {error}")
            continue
        if valor:
            return valor

    # Ultimo recurso. Se admite pero queda registrado: USERNAME se puede
    # cambiar desde la linea de comandos.
    usuario = os.environ.get("USERNAME") or os.environ.get("USER")
    if usuario:
        dominio = os.environ.get("USERDOMAIN", "")
        _aviso.append(
            f"Identidad tomada de variables de entorno ({usuario}). "
            "No es confiable: se puede falsear desde la consola."
        )
        return f"{dominio}\\{usuario}" if dominio else usuario
    return None


def nombre_corto(windows_id: str) -> str:
    return windows_id.split("\\")[-1]


def nombre_desde_windows(windows_id: str) -> str:
    """'a360inc\\julio.lerma' -> 'Julio Lerma', solo para mostrar."""
    partes = nombre_corto(windows_id).replace("_", ".").replace("-", ".")
    return " ".join(p.capitalize() for p in partes.split(".") if p) or windows_id


def es_arrancador(windows_id: str) -> bool:
    return nombre_corto(windows_id).lower() in PUEDE_CREAR_ADMIN


def departamentos_disponibles() -> list[str]:
    """Departamentos que tienen al menos un empleado activo.

    Lee de wfh.db, que es donde viven los empleados; control.db solo guarda
    los nombres a los que cada usuario tiene acceso.
    """
    if not WFH.exists():
        return []
    con = sqlite3.connect(WFH)
    try:
        filas = con.execute(
            "SELECT DISTINCT departamento FROM v_empleados "
            "WHERE departamento IS NOT NULL AND estado_laboral = 'Active' "
            "ORDER BY departamento"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [f[0] for f in filas]


# --- acceso a control.db -------------------------------------------------
def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(CONTROL)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def crear_si_no_existe() -> None:
    con = conectar()
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    con.commit()
    con.close()


def ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def hay_cuentas() -> bool:
    if not CONTROL.exists():
        return False
    con = conectar()
    total = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    con.close()
    return total > 0


def crear_usuario(windows_id: str, nombre: str, rol: str,
                  departamentos: list[str]) -> int:
    if rol not in ROLES:
        raise ValueError(f"Rol desconocido: {rol}")
    con = conectar()
    with con:
        cur = con.execute(
            "INSERT INTO usuarios (windows_id, nombre, rol, creado_en, ultimo_acceso)"
            " VALUES (?,?,?,?,?)",
            (windows_id, nombre, rol, ahora(), ahora()),
        )
        id_usuario = cur.lastrowid
        _poner_departamentos(con, id_usuario, departamentos)
    con.close()
    return id_usuario


def _poner_departamentos(con, id_usuario: int, departamentos: list[str]) -> None:
    con.execute("DELETE FROM usuarios_departamentos WHERE id_usuario = ?",
                (id_usuario,))
    for depto in sorted({d.strip() for d in departamentos if d.strip()}):
        con.execute(
            "INSERT INTO usuarios_departamentos (id_usuario, departamento)"
            " VALUES (?,?)", (id_usuario, depto))


def buscar_usuario(windows_id: str) -> sqlite3.Row | None:
    con = conectar()
    fila = con.execute(
        "SELECT * FROM usuarios WHERE windows_id = ? COLLATE NOCASE",
        (windows_id,),
    ).fetchone()
    if fila:
        con.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?",
                    (ahora(), fila["id"]))
        con.commit()
    con.close()
    return fila


def departamentos_de(id_usuario: int) -> list[str]:
    con = conectar()
    filas = con.execute(
        "SELECT departamento FROM usuarios_departamentos "
        "WHERE id_usuario = ? ORDER BY departamento", (id_usuario,),
    ).fetchall()
    con.close()
    return [f["departamento"] for f in filas]


def listar_usuarios() -> list[dict]:
    con = conectar()
    try:
        filas = con.execute(
            "SELECT id, windows_id, nombre, rol, creado_en, ultimo_acceso "
            "FROM usuarios ORDER BY rol, nombre"
        ).fetchall()
        departamentos: dict[int, list[str]] = {}
        for f in con.execute(
            "SELECT id_usuario, departamento FROM usuarios_departamentos "
            "ORDER BY departamento"
        ):
            departamentos.setdefault(f["id_usuario"], []).append(
                f["departamento"])
    finally:
        con.close()
    resultado = []
    for fila in filas:
        datos = dict(fila)
        datos["departamentos"] = departamentos.get(fila["id"], [])
        resultado.append(datos)
    return resultado


def actualizar_usuario(id_usuario: int, nombre: str, rol: str,
                       departamentos: list[str]) -> None:
    con = conectar()
    with con:
        con.execute("UPDATE usuarios SET nombre = ?, rol = ? WHERE id = ?",
                    (nombre, rol, id_usuario))
        _poner_departamentos(con, id_usuario, departamentos)
    con.close()


def eliminar_usuario(id_usuario: int) -> None:
    con = conectar()
    with con:
        con.execute("DELETE FROM usuarios_departamentos WHERE id_usuario = ?",
                    (id_usuario,))
        con.execute("DELETE FROM usuarios WHERE id = ?", (id_usuario,))
    con.close()


# --- auditoria -----------------------------------------------------------
def registrar_cambio(cambios: list[dict], windows_id: str, rol: str) -> None:
    """Un registro por empleado.

    Cada dict trae: cedula, emp_num, nombre, departamento, anterior y nueva.
    Se referencia al empleado por cedula, no por id_empleado, porque ese id
    se reasigna cuando la recarga del Excel recrea la tabla empleados.
    """
    momento = ahora()
    con = conectar()
    with con:
        con.executemany(
            "INSERT INTO cambios_modalidad (cedula, emp_num, nombre, departamento,"
            " modalidad_anterior, modalidad_nueva, windows_id, rol, fecha)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [(c.get("cedula"), c.get("emp_num"), c.get("nombre"),
              c.get("departamento"), c.get("anterior"), c.get("nueva"),
              windows_id, rol, momento)
             for c in cambios],
        )
    con.close()


def historial(departamentos: list[str] | None, limite: int = 500
               ) -> list[sqlite3.Row]:
    con = conectar()
    if departamentos is None:
        filas = con.execute(
            "SELECT * FROM cambios_modalidad ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    elif not departamentos:
        filas = []
    else:
        marcadores = ",".join("?" * len(departamentos))
        filas = con.execute(
            f"SELECT * FROM cambios_modalidad WHERE departamento COLLATE NOCASE"
            f" IN ({marcadores}) ORDER BY id DESC LIMIT ?",
            [*departamentos, limite],
        ).fetchall()
    con.close()
    return filas


# --- diagnostico ---------------------------------------------------------
def diagnostico() -> None:
    print("Diagnostico de identidad de Windows\n")
    print("  USERNAME (env)      =", os.environ.get("USERNAME"))
    print("  USERDOMAIN (env)    =", os.environ.get("USERDOMAIN"))
    print("  getpass.getuser()   =", __import__("getpass").getuser())
    print()
    for nombre, fn in (("GetUserNameExW", _por_getusernameex),
                       ("SID + LookupAccountSid", _por_sid),
                       ("GetUserNameW", _por_getusername)):
        try:
            print(f"  {nombre:<26} = {fn()}")
        except Exception as error:
            print(f"  {nombre:<26} fallo: {error}")
    print()
    print("  identidad resuelta  =", identidad())
    for a in avisos():
        print("  aviso:", a)


if __name__ == "__main__":
    diagnostico()
