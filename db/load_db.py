"""Carga el Excel de empleados a SQLite aplicando limpieza y normalizacion."""

import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
EXCEL = BASE_DIR / "Employees General Info.xlsx"
DB = BASE_DIR / "db" / "wfh.db"
SCHEMA = BASE_DIR / "db" / "schema.sql"

SIN_DATO = {"", "no tiene", "n/a", "na", "none", "-", "nan"}
# Valores que aparecen en 'Department' pero son el nombre de otra columna.
DEPARTAMENTOS_INVALIDOS = {"title"}
warnings: list[str] = []


def sin_acentos(valor: str) -> str:
    descompuesto = unicodedata.normalize("NFD", valor)
    return "".join(ch for ch in descompuesto if unicodedata.category(ch) != "Mn")


def canonico(serie: pd.Series) -> dict[str, str]:
    """Forma canonica de cada variante: la que mas se repite.

    El Excel a veces mezcla mayusculas para el mismo departamento. En vez de
    de mantener una lista de alias escrita a mano, se gana la variante mas
    frecuente y se le apuntan las demas. Asi no hay que hardcodear nombres.
    """
    conteo: dict[str, int] = {}
    for valor in serie.dropna().astype(str).str.strip():
        conteo[valor] = conteo.get(valor, 0) + 1
    grupos: dict[str, list[tuple[str, int]]] = {}
    for valor, n in conteo.items():
        grupos.setdefault(sin_acentos(valor).lower(), []).append((valor, n))
    mapa: dict[str, str] = {}
    for variantes in grupos.values():
        gana = max(variantes, key=lambda par: (par[1], par[0]))[0]
        for valor, _ in variantes:
            mapa[valor] = gana
    return mapa


def texto(valor) -> str | None:
    if pd.isna(valor):
        return None
    t = str(valor).strip()
    return None if t.lower() in SIN_DATO else t


def entero(valor) -> int | None:
    if pd.isna(valor):
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def decimal(valor):
    if pd.isna(valor):
        return None
    try:
        return round(float(valor), 4)
    except (TypeError, ValueError):
        return None


def fecha(valor):
    if pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date().isoformat()
    try:
        return pd.to_datetime(valor).date().isoformat()
    except (TypeError, ValueError):
        return None


def booleano(valor):
    t = texto(valor)
    if t is None:
        return None
    return 1 if t.lower() == "yes" else 0


def motivo(valor) -> str | None:
    t = texto(valor)
    if t is None:
        return None
    return re.sub(r"\s+", " ", t).replace("Art.212", "Art. 212").strip()


def advertencias_unicidad(df: pd.DataFrame) -> dict:
    """Mapa indice de fila -> columnas duplicadas que deben anularse."""
    duplicados: dict[int, set] = {}
    for col, etiqueta in (
        ("Emp. #", "emp_num"),
        ("I.D.", "cedula"),
        ("Social Security", "seguro_social"),
    ):
        mask = df[col].notna()
        repetidos = df.loc[mask, col][df.loc[mask, col].duplicated()].unique()
        for valor in repetidos:
            filas = df.index[mask & (df[col] == valor)].tolist()
            for fila in filas[1:]:
                duplicados.setdefault(fila, set()).add(etiqueta)
            warnings.append(
                f"{etiqueta}={valor!r} duplicado: se conserva la primera fila "
                f"(indice {filas[0]}) y se anula en {filas[1:]}"
            )
    return duplicados


def leer_modalidades() -> dict[str, str]:
    """Modalidad ya configurada, indexada por cedula, para sobrevivir a la recarga."""
    if not DB.exists():
        return {}
    try:
        con = sqlite3.connect(DB)
        filas = con.execute(
            "SELECT cedula, modalidad FROM empleados "
            "WHERE modalidad IS NOT NULL AND cedula IS NOT NULL"
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    return dict(filas)


def cargar() -> None:
    df = pd.read_excel(EXCEL, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    duplicados = advertencias_unicidad(df)

    if "Parking Assignment" in df.columns and df["Parking Assignment"].isna().all():
        warnings.append("Columna 'Parking Assignment' descartada: esta 100% vacia")

    # Unifica variantes de mayusculas/acentos en columnas de texto libre y
    # avisa de las que encontro, en lugar de mantener aliases a mano.
    canonicos: dict[str, dict[str, str]] = {}
    for columna in ("Department", "Reports To", "City", "Region"):
        if columna not in df.columns:
            continue
        serie = df[columna].dropna().astype(str).str.strip()
        mapa = canonico(serie)
        unidas = {v: mapa[v] for v in mapa if v != mapa[v]}
        if unidas:
            canonicos[columna] = mapa
            df[columna] = serie.map(lambda v: mapa.get(v, v))
            warnings.append(
                f"'{columna}': {len(set(unidas.values()))} variante(s) unificadas "
                f"a su forma mas frecuente -> {sorted(set(unidas.values()))}"
            )

    modalidades = leer_modalidades()
    if modalidades:
        warnings.append(
            f"Se preserva la modalidad de {len(modalidades)} empleados ya configurada"
        )

    if DB.exists():
        try:
            DB.unlink()
            for sufijo in ("-wal", "-shm"):
                auxiliar = DB.with_name(DB.name + sufijo)
                if auxiliar.exists():
                    auxiliar.unlink()
        except PermissionError:
            # Otro proceso tiene el archivo abierto; el DROP TABLE del esquema
            # hace el trabajo equivalente.
            warnings.append(
                f"'{DB.name}' estaba abierto por otro proceso; se recreo sin borrarlo"
            )

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))

    cur = con.cursor()
    depto_id: dict[str, int] = {}
    invalidos: dict[str, int] = {}
    reporta_id: dict[str, int] = {}
    insertados = {"empleados": 0, "direcciones": 0, "telefonos": 0,
                  "emergencia": 0, "eventos": 0}

    for idx, row in df.iterrows():
        nombres = texto(row.get("First Name"))
        apellidos = texto(row.get("Last Name"))
        if not nombres or not apellidos:
            warnings.append(f"Fila {idx}: descartada, sin nombre o apellido")
            continue

        anulados_fila = duplicados.get(idx, set())
        emp_num = None if "emp_num" in anulados_fila else entero(row.get("Emp. #"))
        cedula = None if "cedula" in anulados_fila else texto(row.get("I.D."))
        seguro = (
            None if "seguro_social" in anulados_fila
            else texto(row.get("Social Security"))
        )

        depto = texto(row.get("Department"))
        if depto and depto.lower() in DEPARTAMENTOS_INVALIDOS:
            depto = None
            invalidos["Department"] = invalidos.get("Department", 0) + 1
        if depto and depto not in depto_id:
            cur.execute("INSERT INTO departamentos (nombre) VALUES (?)", (depto,))
            depto_id[depto] = cur.lastrowid

        reporta = texto(row.get("Reports To"))
        if reporta and reporta not in reporta_id:
            cur.execute("INSERT INTO reportes_de (nombre) VALUES (?)", (reporta,))
            reporta_id[reporta] = cur.lastrowid

        modalidad = modalidades.get(cedula) if cedula else None

        cur.execute(
            """
            INSERT INTO empleados (
                emp_num, id_departamento, id_reports_to, cedula, seguro_social,
                nombres, apellidos,
                nombre_completo, genero, estado_civil, puesto, salario,
                tarifa_por_hora, fecha_nacimiento, antiguedad_anios, tiene_hijos,
                correo, estado_laboral, modalidad, numero_insignia
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                emp_num,
                depto_id.get(depto),
                reporta_id.get(reporta),
                cedula,
                seguro,
                nombres,
                apellidos,
                texto(row.get("Nombre completo")),
                texto(row.get("Gender")),
                texto(row.get("Marital Status")),
                texto(row.get("Title")),
                decimal(row.get("Salary")),
                decimal(row.get("Rate")),
                fecha(row.get("Birth Date")),
                entero(row.get("Years of Tenure")) or entero(row.get("Tenure")),
                booleano(row.get("Children")),
                texto(row.get("Email")),
                texto(row.get("Employment Status")),
                modalidad,
                texto(row.get("Badge No")),
            ),
        )
        emp_id = cur.lastrowid
        insertados["empleados"] += 1

        direccion = texto(row.get("Address"))
        ciudad = texto(row.get("City"))
        if direccion or ciudad:
            cur.execute(
                "INSERT INTO direcciones (id_empleado, linea1, ciudad, region) "
                "VALUES (?,?,?,?)",
                (emp_id, direccion, ciudad, texto(row.get("Region"))),
            )
            insertados["direcciones"] += 1

        for tipo, col in (("home", "Home Phone"), ("mobile", "Cellular Phone")):
            numero = texto(row.get(col))
            if numero:
                cur.execute(
                    "INSERT INTO telefonos (id_empleado, tipo, numero) VALUES (?,?,?)",
                    (emp_id, tipo, numero),
                )
                insertados["telefonos"] += 1

        contacto = texto(row.get("Emergency Contact"))
        telefono_emergencia = texto(row.get("Emergency Number"))
        if contacto or telefono_emergencia:
            cur.execute(
                "INSERT INTO contactos_emergencia (id_empleado, nombre, telefono) "
                "VALUES (?,?,?)",
                (emp_id, contacto, telefono_emergencia),
            )
            insertados["emergencia"] += 1

        eventos = (
            ("hire_original", "Original Hire Date", None),
            ("hire_new", "New Hire Date", None),
            ("termination", "Termination Date", "Motive"),
            ("rehire", "Rehire Date", None),
            ("termination_new", "New Termination Date", "Motive2"),
        )
        for orden, (tipo, col_fecha, col_motivo) in enumerate(eventos):
            f = fecha(row.get(col_fecha))
            if not f:
                continue
            cur.execute(
                "INSERT INTO eventos_laborales (id_empleado, tipo, fecha, motivo, orden) "
                "VALUES (?,?,?,?,?)",
                (emp_id, tipo, f, motivo(row.get(col_motivo)) if col_motivo else None, orden),
            )
            insertados["eventos"] += 1

    con.commit()
    integridad = con.execute("PRAGMA foreign_key_check").fetchall()
    con.execute("CREATE INDEX IF NOT EXISTS ix_eventos_tipo ON eventos_laborales(tipo)")
    con.commit()
    con.close()

    for columna, total in invalidos.items():
        warnings.append(
            f"'{columna}' contenia {total} valores que no son datos validos "
            f"({', '.join(sorted(DEPARTAMENTOS_INVALIDOS))}); se guardaron como NULL"
        )


    print(f"Base de datos creada en {DB}")
    print(f"Departamentos: {len(depto_id)} | Reporta a: {len(reporta_id)}")
    for tabla, total in insertados.items():
        print(f"  {tabla}: {total}")
    print(f"Integridad referencial: {'OK' if not integridad else integridad}")
    if warnings:
        print(f"\nAdvertencias ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    cargar()
