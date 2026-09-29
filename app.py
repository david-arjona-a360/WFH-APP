"""App para asignar la modalidad de trabajo (WFH / OFFICE) de cada empleado.

El acceso no usa contrasenas: se toma de la sesion de Windows del dominio.
Cada persona entra con su cuenta de Windows y solo ve lo que su rol y sus
departamentos le permiten. Las cuentas y la auditoria viven en db/control.db,
separada de db/wfh.db, porque la recarga del Excel reconstruye esta ultima.
"""

import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import db.control as control

DB = BASE_DIR / "db" / "wfh.db"
MODALIDADES = ("WFH", "OFFICE")
SIN_ASIGNAR = "Sin asignar"
# La app trabaja sobre Active. Inactive = fuera de la empresa, solo historial.
ESTADOS_FILTRO = ("Solo activos", "Activos", "Inactivos", "Todos")
VALOR_ESTADO = {"Activos": "Active", "Inactivos": "Inactive"}

COLS = ("emp_num", "nombres", "apellidos", "puesto", "departamento",
        "estado_laboral", "modalidad")
ENCABEZADOS = {
    "emp_num": "Emp. #", "nombres": "Nombres", "apellidos": "Apellidos",
    "puesto": "Puesto", "departamento": "Departamento",
    "estado_laboral": "Estado", "modalidad": "Modalidad",
}
ANCHOS = {"emp_num": 60, "nombres": 110, "apellidos": 130, "puesto": 190,
          "departamento": 130, "estado_laboral": 80, "modalidad": 100}
COL_MODALIDAD = COLS.index("modalidad")

COLS_HIST = ("fecha", "departamento", "nombre", "anterior", "nueva", "quien")
ENCAB_HIST = {
    "fecha": "Fecha", "departamento": "Departamento", "nombre": "Empleado",
    "anterior": "Antes", "nueva": "Despues", "quien": "Cambio por",
}
ANCHOS_HIST = {"fecha": 130, "departamento": 130, "nombre": 190,
               "anterior": 90, "nueva": 90, "quien": 170}


def para_mostrar(fila: tuple) -> tuple:
    """La modalidad vacia se muestra como texto, no como celda en blanco.

    Con las letras en negro la columna Modalidad es la unica senal de que un
    empleado no tiene asignada; si la celda quedara vacia no se distinguiria
    de un dato que falta.
    """
    valores = list(fila)
    if not valores[COL_MODALIDAD]:
        valores[COL_MODALIDAD] = SIN_ASIGNAR
    return tuple(valores)


def fecha_corta(iso: str | None) -> str:
    """'2026-09-29T14:03:00-04:00' -> '2026-09-29 14:03'."""
    if not iso:
        return ""
    return iso[:16].replace("T", " ")


class Sesion:
    """Quien esta usando la app y que puede ver."""

    def __init__(self, fila: sqlite3.Row, departamentos: list[str],
                 avisos: list[str] | None = None) -> None:
        self.id = fila["id"]
        self.windows_id = fila["windows_id"]
        self.nombre = fila["nombre"]
        self.rol = fila["rol"]
        self.departamentos = departamentos
        self.avisos = avisos or []

    @property
    def es_admin(self) -> bool:
        return self.rol == "admin"

    @property
    def identidad_no_verificada(self) -> bool:
        return bool(self.avisos)


def _dialogo(titulo: str, mensaje: str, icono: str = "error") -> None:
    """Mensaje antes de que exista la ventana principal."""
    raiz = tk.Tk()
    raiz.withdraw()
    if icono == "error":
        messagebox.showerror(titulo, mensaje, parent=raiz)
    elif icono == "warning":
        messagebox.showwarning(titulo, mensaje, parent=raiz)
    else:
        messagebox.showinfo(titulo, mensaje, parent=raiz)
    raiz.destroy()


def iniciar_sesion() -> Sesion | None:
    """Identifica al usuario de Windows y valida que tenga cuenta. Si no, None."""
    control.crear_si_no_existe()
    windows_id = control.identidad()
    if not windows_id:
        _dialogo(
            "No se pudo identificar al usuario",
            "No se pudo obtener la identidad de Windows de esta sesion.\n\n"
            "La app no puede seguir sin saber quien entro.\n\n"
            "Detalle: " + ("; ".join(control.avisos()) or "sin informacion"),
        )
        return None

    if not control.hay_cuentas():
        # Sin cuentas cualquiera que abra la app entraria como admin. Solo las
        # cuentas de arranque autorizadas pueden crear el primer admin.
        if not control.es_arrancador(windows_id):
            _dialogo(
                "Sin cuentas configuradas",
                f"{windows_id} no esta autorizado a configurar la app.\n\n"
                "La base de control esta vacia. Una de las cuentas de "
                "arranque debe abrirla primero para crear el primer admin.",
            )
            return None
        _dialogo(
            "Primer uso",
            f"Se creara la cuenta de administrador:\n\n"
            f"  Usuario Windows: {windows_id}\n"
            f"  Nombre: {control.nombre_desde_windows(windows_id)}\n\n"
            "El admin ve todos los empleados, administra las cuentas y puede "
            "cargar el Excel.",
            icono="info",
        )
        control.crear_usuario(
            windows_id, control.nombre_desde_windows(windows_id), "admin", [])

    fila = control.buscar_usuario(windows_id)
    if fila is None:
        _dialogo(
            "Acceso denegado",
            f"La cuenta de Windows {windows_id} no tiene acceso a esta app.\n\n"
            "Pide a un administrador que la agregue desde 'Gestionar usuarios'.",
        )
        return None

    # Si la identidad se resolvio por variables de entorno, no es una garantia:
    # se puede falsear desde la consola. Se avisa al abrir y ademas queda a la
    # vista en la cabecera, porque un cartel inicial se pasa por alto.
    avisos = control.avisos()
    if avisos:
        _dialogo(
            "Identidad no verificada",
            "La identidad de Windows se resolvio por un metodo que no es "
            "confiable:\n\n"
            + "\n".join(avisos)
            + "\n\nAlguien con acceso a esta consola podria suplantar una "
              "identidad. En una maquina de dominio esto no deberia pasar.",
            icono="warning",
        )
    return Sesion(fila, control.departamentos_de(fila["id"]), avisos)


class App(tk.Tk):
    def __init__(self, sesion: Sesion) -> None:
        super().__init__()
        self.sesion = sesion
        self.title("Modalidad de trabajo - WFH / OFFICE")
        self.geometry("1180x660")
        self.minsize(950, 500)
        self.con = self.conectar()

        self.busqueda = tk.StringVar()
        self.f_depto = tk.StringVar(value="Todos")
        self.f_modalidad = tk.StringVar(value="Todas")
        self.f_estado = tk.StringVar(value="Solo activos")
        self.mensaje = tk.StringVar(value="Listo.")
        self.seleccion = tk.StringVar(value="Ningun empleado seleccionado")

        self.ids_seleccionados: set[int] = set()
        self.filas: dict[str, tuple] = {}
        self.deptos: list[str] = []
        self.deptos_faltantes: list[str] = []
        self.columna_orden = ""
        self.orden_desc = False

        self.construir_widgets()
        self.refrescar_filtros()
        self.cargar_empleados()

    # --- datos ---------------------------------------------------------
    def conectar(self) -> sqlite3.Connection:
        if not DB.exists():
            messagebox.showerror(
                "Base de datos no encontrada",
                f"No se encontro {DB}.\n\nEjecuta primero:  python db/load_db.py",
            )
            raise SystemExit(1)
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def consultar(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.con.execute(sql, params).fetchall()

    def condicion_estado(self) -> tuple[str, list]:
        """El filtro de estado manda: los departamentos se listan segun el.

        Para un usuario sin permiso de admin el estado no se elige, siempre
        son los activos.
        """
        if not self.sesion.es_admin:
            return "estado_laboral = 'Active'", []
        if self.f_estado.get() == "Solo activos":
            return "estado_laboral = 'Active'", []
        if self.f_estado.get() in VALOR_ESTADO:
            return "estado_laboral = ?", [VALOR_ESTADO[self.f_estado.get()]]
        return "", []

    def refrescar_filtros(self) -> None:
        if self.sesion.es_admin:
            where_estado, params = self.condicion_estado()
            extra = f" AND {where_estado}" if where_estado else ""
            self.deptos = sorted(
                r["departamento"] for r in self.consultar(
                    "SELECT DISTINCT departamento FROM v_empleados "
                    f"WHERE departamento IS NOT NULL{extra}",
                    tuple(params),
                )
            )
            self.deptos_faltantes = []
        else:
            # El admin asigna los departamentos por nombre. Si el Excel ya no
            # trae empleados de alguno, se avisa en vez de mostrarlo vacio.
            existentes = {
                r["departamento"] for r in self.consultar(
                    "SELECT DISTINCT departamento FROM v_empleados "
                    "WHERE estado_laboral = 'Active' AND departamento IS NOT NULL"
                )
            }
            self.deptos = sorted(
                d for d in self.sesion.departamentos if d in existentes)
            self.deptos_faltantes = sorted(
                d for d in self.sesion.departamentos if d not in existentes)
        # Si el departamento seleccionado ya no aplica, se vuelve a "Todos"
        # para no dejar el filtro en un valor que no existe en la lista.
        if self.f_depto.get() != "Todos" and self.f_depto.get() not in self.deptos:
            self.f_depto.set("Todos")
        self.combo_depto["values"] = ["Todos", *self.deptos]
        self.combo_mod["values"] = ["Todas", *MODALIDADES, SIN_ASIGNAR]

    def ambito(self) -> tuple[str, list]:
        """Restricciones que impone el rol, no el filtro de la pantalla."""
        if self.sesion.es_admin:
            return "", []
        where = ["estado_laboral = 'Active'"]
        params: list = []
        if not self.sesion.departamentos:
            # Cuenta sin departamentos asignados: no ve a nadie.
            where.append("1 = 0")
        else:
            marcadores = ",".join("?" * len(self.sesion.departamentos))
            where.append(
                f"departamento COLLATE NOCASE IN ({marcadores})")
            params.extend(self.sesion.departamentos)
        return " AND ".join(where), params

    def condiciones(self) -> tuple[str, list]:
        where, params = [], []
        ambito, params_ambito = self.ambito()
        if ambito:
            where.append(ambito)
            params.extend(params_ambito)
        if self.sesion.es_admin:
            where_estado, params_estado = self.condicion_estado()
            if where_estado:
                where.append(where_estado)
                params.extend(params_estado)
        if self.f_depto.get() != "Todos":
            where.append("departamento COLLATE NOCASE = ?")
            params.append(self.f_depto.get())
        if self.f_modalidad.get() == SIN_ASIGNAR:
            where.append("(modalidad IS NULL OR modalidad = '')")
        elif self.f_modalidad.get() != "Todas":
            where.append("modalidad = ?")
            params.append(self.f_modalidad.get())
        texto = self.busqueda.get().strip()
        if texto:
            where.append(
                "(nombres LIKE ? OR apellidos LIKE ? OR puesto LIKE ? "
                "OR CAST(emp_num AS TEXT) LIKE ? OR departamento LIKE ?)"
            )
            params.extend([f"%{texto}%"] * 5)
        return (" WHERE " + " AND ".join(where) if where else ""), params

    def cargar_empleados(self) -> None:
        where, params = self.condiciones()
        filas = self.consultar(
            f"SELECT id_empleado, {', '.join(COLS)} FROM v_empleados"
            f"{where} ORDER BY apellidos, nombres",
            tuple(params),
        )
        self.tabla.delete(*self.tabla.get_children())
        self.filas.clear()
        for fila in filas:
            iid = str(fila["id_empleado"])
            self.filas[iid] = tuple(fila[c] for c in COLS)
            self.tabla.insert(
                "", "end", iid=iid, values=para_mostrar(self.filas[iid]),
                tags=(fila["modalidad"] or "vacio",),
            )
        if self.columna_orden:
            self.ordenar(self.columna_orden)
        self.actualizar_estado(filas)
        # Sin auto-seleccion: al abrir o al filtrar la tabla arranca vacia.
        # Para tomar todo lo que se ve esta el boton "Seleccionar visibles".
        self.limpiar_seleccion()

    def cargar_historial(self) -> None:
        depts = None if self.sesion.es_admin else self.sesion.departamentos
        filas = control.historial(depts)
        self.tabla_hist.delete(*self.tabla_hist.get_children())
        for f in filas:
            self.tabla_hist.insert(
                "", "end",
                values=(fecha_corta(f["fecha"]), f["departamento"] or "",
                        f["nombre"] or "",
                        f["modalidad_anterior"] or SIN_ASIGNAR,
                        f["modalidad_nueva"] or SIN_ASIGNAR,
                        f["windows_id"] or ""),
            )
        alcance = "todos los departamentos" if self.sesion.es_admin else (
            ", ".join(self.sesion.departamentos) or "sin departamentos")
        self.mensaje_hist.set(
            f"{len(filas)} cambios mostrados (ultimos 500)  |  ambito: {alcance}")

    # --- interfaz ------------------------------------------------------
    def construir_widgets(self) -> None:
        marco = ttk.Frame(self, padding=10)
        marco.pack(fill="both", expand=True)

        cabecera = ttk.Frame(marco)
        cabecera.pack(fill="x", pady=(0, 8))
        ttk.Label(
            cabecera,
            text=f"{self.sesion.nombre}  ({self.sesion.rol})",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        ttk.Label(cabecera, text=self.sesion.windows_id).pack(side="left",
                                                               padx=(8, 0))
        if self.sesion.identidad_no_verificada:
            # Queda visible mientras la app este abierta, no solo en el cartel
            # de arranque: es el dato que invalida la garantia de acceso.
            ttk.Label(
                cabecera, text="identidad no verificada", foreground="#b35c00",
                font=("Segoe UI", 9, "bold"),
            ).pack(side="left", padx=(12, 0))
        ttk.Button(cabecera, text="Salir", command=self.cerrar).pack(
            side="right")
        if self.sesion.es_admin:
            ttk.Button(cabecera, text="Gestionar usuarios", width=20,
                       command=self.abrir_gestion_usuarios).pack(
                side="right", padx=(0, 6))

        self.libros = ttk.Notebook(marco)
        self.libros.pack(fill="both", expand=True)
        pag_empleados = ttk.Frame(self.libros, padding=6)
        pag_historial = ttk.Frame(self.libros, padding=6)
        self.libros.add(pag_empleados, text="Empleados")
        self.libros.add(pag_historial, text="Historial")

        self.construir_pagina_empleados(pag_empleados)
        self.construir_pagina_historial(pag_historial)
        # El enlace se pone al final: cambiar de pestana carga el historial, y
        # esa tabla todavia no existia mientras se armaban las paginas.
        self.libros.bind("<<NotebookTabChanged>>",
                         lambda _e: self.cargar_historial())

        ttk.Label(marco, textvariable=self.mensaje, relief="sunken",
                  anchor="w", padding=4).pack(fill="x", pady=(10, 0))

    def construir_pagina_empleados(self, pagina: ttk.Frame) -> None:
        filtros = ttk.Frame(pagina)
        filtros.pack(fill="x")

        ttk.Label(filtros, text="Buscar:").pack(side="left")
        self.entrada = ttk.Entry(filtros, textvariable=self.busqueda, width=26)
        self.entrada.pack(side="left", padx=(4, 14))
        self.entrada.bind("<KeyRelease>", lambda _: self.cargar_empleados())

        ttk.Label(filtros, text="Departamento:").pack(side="left")
        self.combo_depto = ttk.Combobox(
            filtros, textvariable=self.f_depto, state="readonly", width=18)
        self.combo_depto.pack(side="left", padx=(4, 14))
        self.combo_depto.bind("<<ComboboxSelected>>",
                              lambda _: self.cargar_empleados())

        ttk.Label(filtros, text="Modalidad:").pack(side="left")
        self.combo_mod = ttk.Combobox(
            filtros, textvariable=self.f_modalidad, state="readonly", width=12)
        self.combo_mod.pack(side="left", padx=(4, 14))
        self.combo_mod.bind("<<ComboboxSelected>>",
                            lambda _: self.cargar_empleados())

        ttk.Label(filtros, text="Estado:").pack(side="left")
        if self.sesion.es_admin:
            self.combo_estado = ttk.Combobox(
                filtros, textvariable=self.f_estado, state="readonly", width=13,
                values=ESTADOS_FILTRO)
        else:
            # El ambito de un usuario ya es solo Active: no tiene sentido
            # ofrecerle un filtro que la app le va a ignorar.
            self.combo_estado = ttk.Combobox(
                filtros, textvariable=self.f_estado, state="disabled", width=13,
                values=("Solo activos",))
        self.combo_estado.pack(side="left", padx=(4, 14))
        self.combo_estado.bind("<<ComboboxSelected>>",
                               lambda _: self.al_cambiar_estado())

        ttk.Button(filtros, text="Limpiar filtros",
                   command=self.limpiar_filtros).pack(side="left")
        if self.sesion.es_admin:
            ttk.Button(filtros, text="Recargar Excel",
                       command=self.recargar_excel).pack(side="left", padx=(10, 0))

        self.tabla = ttk.Treeview(
            pagina, columns=COLS, show="headings", selectmode="extended")
        for col in COLS:
            self.tabla.heading(col, text=ENCABEZADOS[col],
                               command=lambda c=col: self.ordenar(c))
            self.tabla.column(col, width=ANCHOS[col], anchor="w")
        # Texto negro en toda la tabla: los colores por modalidad se
        # distinguian por la fila, no por la letra.
        self.tabla.tag_configure("wfh", foreground="#000000")
        self.tabla.tag_configure("office", foreground="#000000")
        self.tabla.tag_configure("vacio", foreground="#000000")
        self.tabla.bind("<<TreeviewSelect>>", self.al_seleccionar)

        scroll = ttk.Scrollbar(pagina, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tabla.pack(fill="both", expand=True, pady=10)

        acciones = ttk.Frame(pagina)
        acciones.pack(fill="x")
        ttk.Label(acciones, textvariable=self.seleccion).pack(
            side="left", padx=(0, 20))

        for modalidad in MODALIDADES:
            ttk.Button(acciones, text=f"Marcar {modalidad}", width=15,
                       command=lambda m=modalidad: self.asignar(m)
                       ).pack(side="left", padx=4)
        ttk.Button(acciones, text="Quitar asignacion", width=18,
                   command=lambda: self.asignar(None)).pack(side="left", padx=4)
        ttk.Button(acciones, text="Seleccionar visibles", width=18,
                   command=self.seleccionar_visibles).pack(side="left", padx=4)

    def construir_pagina_historial(self, pagina: ttk.Frame) -> None:
        self.mensaje_hist = tk.StringVar(value="")
        self.tabla_hist = ttk.Treeview(
            pagina, columns=COLS_HIST, show="headings", selectmode="browse")
        for col in COLS_HIST:
            self.tabla_hist.heading(col, text=ENCAB_HIST[col])
            self.tabla_hist.column(col, width=ANCHOS_HIST[col], anchor="w")
        scroll = ttk.Scrollbar(pagina, orient="vertical",
                               command=self.tabla_hist.yview)
        self.tabla_hist.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tabla_hist.pack(fill="both", expand=True)
        ttk.Label(pagina, textvariable=self.mensaje_hist, relief="sunken",
                  anchor="w", padding=4).pack(fill="x", pady=(10, 0))

    def abrir_gestion_usuarios(self) -> None:
        VentanaUsuarios(self)

    def al_cambiar_estado(self) -> None:
        """Cambiar el estado recalcula que departamentos aplican."""
        self.refrescar_filtros()
        self.cargar_empleados()

    def limpiar_filtros(self) -> None:
        self.busqueda.set("")
        self.f_modalidad.set("Todas")
        self.f_estado.set("Solo activos")
        self.f_depto.set("Todos")
        self.refrescar_filtros()
        self.cargar_empleados()

    def recargar_excel(self) -> None:
        """Relee el Excel: asi los cambios de HR (Active -> Inactive) se aplican."""
        if not messagebox.askyesno(
            "Recargar desde Excel",
            "Se releera el Excel y se reconstruira la base de datos.\n\n"
            "Las modalidades ya asignadas se conservan.\nContinuar?",
        ):
            return
        self.mensaje.set("Recargando Excel...")
        self.update_idletasks()
        try:
            # Cerrar la conexion para que load_db pueda recrear el archivo.
            self.con.close()
            from db.load_db import cargar as recargar
            recargar()
            self.con = self.conectar()
        except Exception as error:
            try:
                self.con = self.conectar()
            except SystemExit:
                raise
            messagebox.showerror("Error al recargar", str(error))
            self.mensaje.set(f"Error: {error}")
            return
        self.refrescar_filtros()
        self.cargar_empleados()
        self.mensaje.set("Excel recargado.")

    def ordenar(self, col: str) -> None:
        if self.columna_orden == col:
            self.orden_desc = not self.orden_desc
        else:
            self.columna_orden, self.orden_desc = col, False
        posicion = COLS.index(col)
        indices = sorted(
            self.filas,
            key=lambda k: (self.filas[k][posicion] is None,
                           str(self.filas[k][posicion] or "").lower()),
            reverse=self.orden_desc,
        )
        # Reordenar no debe cambiar lo que esta seleccionado.
        marcadas = self.tabla.selection()
        self.tabla.delete(*self.tabla.get_children())
        for iid in indices:
            modalidad = self.filas[iid][COL_MODALIDAD]
            self.tabla.insert("", "end", iid=iid, values=para_mostrar(self.filas[iid]),
                              tags=(modalidad or "vacio",))
        flecha = " ▼" if self.orden_desc else " ▲"
        for c in COLS:
            texto = f"{ENCABEZADOS[c]}{flecha}" if c == col else ENCABEZADOS[c]
            self.tabla.heading(c, text=texto)
        siguen = [i for i in marcadas if i in self.filas]
        if siguen:
            self.tabla.selection_set(*siguen)
        else:
            self.limpiar_seleccion()

    def seleccionar_visibles(self) -> None:
        if not self.filas:
            self.limpiar_seleccion()
            return
        self.tabla.selection_set(*self.filas)

    def limpiar_seleccion(self) -> None:
        self.tabla.selection_remove(*self.tabla.selection())
        self.ids_seleccionados = set()
        self.seleccion.set("Ningun empleado seleccionado")

    def al_seleccionar(self, _event) -> None:
        self.ids_seleccionados = {int(i) for i in self.tabla.selection()}
        n = len(self.ids_seleccionados)
        if n == 0:
            self.seleccion.set("Ningun empleado seleccionado")
        elif n == 1:
            fila = self.filas[str(next(iter(self.ids_seleccionados)))]
            self.seleccion.set(
                f"{fila[1]} {fila[2]}  (actual: {fila[COL_MODALIDAD] or SIN_ASIGNAR})"
            )
        else:
            self.seleccion.set(f"{n} empleados seleccionados")

    # --- escritura -----------------------------------------------------
    def asignar(self, modalidad: str | None) -> None:
        # Se lee la seleccion real de la tabla, no una copia cacheada: si el
        # evento de seleccion no llego, se evita tocar a la persona equivocada.
        ids = sorted(int(i) for i in self.tabla.selection())
        if not ids:
            messagebox.showinfo(
                "Sin seleccion", "Selecciona al menos un empleado en la tabla.")
            return

        where, _ = self.condiciones()
        if len(ids) == len(self.filas) and where:
            if not messagebox.askyesno(
                "Confirmar",
                f"Vas a cambiar {len(ids)} empleados, que son todos los que "
                f"cumplen el filtro actual.\n\nContinuar?",
            ):
                return

        marcadores = ",".join("?" * len(ids))
        # Se leen los datos antes de actualizar: el historial guarda la
        # modalidad anterior de cada persona, no un valor comun a todos.
        previos = self.consultar(
            "SELECT e.id_empleado, e.cedula, e.emp_num, e.nombre_completo AS nombre,"
            " d.nombre AS departamento, e.modalidad"
            " FROM empleados e"
            " LEFT JOIN departamentos d ON d.id_departamento = e.id_departamento"
            f" WHERE e.id_empleado IN ({marcadores})",
            ids,
        )
        cambios = [
            {"cedula": p["cedula"], "emp_num": p["emp_num"], "nombre": p["nombre"],
             "departamento": p["departamento"],
             "anterior": p["modalidad"] or None, "nueva": modalidad}
            for p in previos if (p["modalidad"] or None) != modalidad
        ]

        self.con.execute(
            f"UPDATE empleados SET modalidad = ? "
            f"WHERE id_empleado IN ({marcadores})",
            [modalidad, *ids],
        )
        self.con.commit()
        if cambios:
            # Si a alguien se le repite la modalidad que ya tenia no se anota:
            # el historial sirve para ver cambios reales, no cada clic.
            control.registrar_cambio(
                cambios, self.sesion.windows_id, self.sesion.rol)
        self.cargar_empleados()
        if not self.filas and where:
            self.mensaje.set(
                f"{len(ids)} empleado(s) -> {modalidad or SIN_ASIGNAR}  |  "
                f"ya no coinciden con el filtro activo"
            )
        else:
            self.mensaje.set(
                f"{len(ids)} empleado(s) -> {modalidad or SIN_ASIGNAR}"
                f"  |  {len(cambios)} registrado(s) en el historial"
            )

    def total_en_ambito(self) -> int:
        """Cuantos empleados le corresponden a esta persona, sin los filtros
        de la pantalla: el ambito del rol mas el filtro de estado."""
        where, params = self.ambito()
        if self.sesion.es_admin:
            where_estado, params_estado = self.condicion_estado()
            if where_estado:
                where = f"{where} AND {where_estado}" if where else where_estado
                params = params + params_estado
        if not where:
            return self.consultar("SELECT COUNT(*) FROM v_empleados")[0][0]
        return self.consultar(
            f"SELECT COUNT(*) FROM v_empleados WHERE {where}", tuple(params))[0][0]

    def actualizar_estado(self, filas: list[sqlite3.Row]) -> None:
        wfh = sum(1 for f in filas if f["modalidad"] == "WFH")
        office = sum(1 for f in filas if f["modalidad"] == "OFFICE")
        texto = (
            f"{len(filas)} en la lista  |  WFH: {wfh}  |  OFFICE: {office}  |  "
            f"{SIN_ASIGNAR}: {len(filas) - wfh - office}  |  "
            f"{self.total_en_ambito()} visibles en tu ambito"
        )
        if self.deptos_faltantes:
            texto += "  |  sin empleados activos: " + ", ".join(
                self.deptos_faltantes)
        self.mensaje.set(texto)

    def cerrar(self) -> None:
        self.con.close()
        self.destroy()


class VentanaUsuarios(tk.Toplevel):
    """Alta y edicion de cuentas. Solo la abre un admin."""

    COLS = ("nombre", "windows_id", "rol", "departamentos", "ultimo_acceso")
    ENCAB = {"nombre": "Nombre", "windows_id": "Usuario Windows", "rol": "Rol",
             "departamentos": "Departamentos",
             "ultimo_acceso": "Ultimo acceso"}
    ANCHOS = {"nombre": 160, "windows_id": 170, "rol": 80, "departamentos": 220,
              "ultimo_acceso": 130}

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        self.title("Gestionar usuarios")
        self.geometry("900x560")
        self.minsize(820, 500)
        self.editando: int | None = None
        self.vars_depto: dict[str, tk.BooleanVar] = {}

        marco = ttk.Frame(self, padding=10)
        marco.pack(fill="both", expand=True)

        self.tabla = ttk.Treeview(marco, columns=self.COLS, show="headings",
                                  selectmode="browse")
        for col in self.COLS:
            self.tabla.heading(col, text=self.ENCAB[col])
            self.tabla.column(col, width=self.ANCHOS[col], anchor="w")
        self.tabla.bind("<<TreeviewSelect>>", self.al_seleccionar)
        scroll = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tabla.pack(fill="both", expand=True, pady=(0, 10))

        form = ttk.LabelFrame(marco, text="Cuenta", padding=10)
        form.pack(fill="x")
        self.e_windows = ttk.Entry(form, width=26)
        self.e_nombre = ttk.Entry(form, width=26)
        self.cb_rol = ttk.Combobox(form, width=14, state="readonly",
                                   values=control.ROLES)

        ttk.Label(form, text="Usuario Windows:").grid(row=0, column=0,
                                                      sticky="w", pady=3)
        self.e_windows.grid(row=0, column=1, columnspan=3, sticky="w", pady=3)
        ttk.Label(form, text="Nombre:").grid(row=1, column=0, sticky="w", pady=3)
        self.e_nombre.grid(row=1, column=1, columnspan=3, sticky="w", pady=3)
        ttk.Label(form, text="Rol:").grid(row=2, column=0, sticky="w", pady=3)
        self.cb_rol.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(
            form,
            text="admin: ve todos los empleados. usuario: solo los activos de "
                 "los departamentos marcados.",
        ).grid(row=2, column=1, columnspan=3, sticky="w", padx=(110, 0))

        marco_deptos = ttk.LabelFrame(marco, text="Departamentos", padding=10)
        marco_deptos.pack(fill="x", pady=(10, 0))
        for i, depto in enumerate(control.departamentos_disponibles()):
            var = tk.BooleanVar(value=False)
            self.vars_depto[depto] = var
            ttk.Checkbutton(marco_deptos, text=depto, variable=var).grid(
                row=i // 4, column=i % 4, sticky="w", padx=4, pady=2)

        botones = ttk.Frame(marco)
        botones.pack(fill="x", pady=(10, 0))
        ttk.Button(botones, text="Guardar", width=14,
                   command=self.guardar).pack(side="left")
        ttk.Button(botones, text="Eliminar", width=14,
                   command=self.eliminar).pack(side="left", padx=6)
        ttk.Button(botones, text="Cerrar", width=14,
                   command=self.destroy).pack(side="right")

        self.recargar()
        self.limpiar_formulario()

    def recargar(self) -> None:
        self.tabla.delete(*self.tabla.get_children())
        for u in control.listar_usuarios():
            self.tabla.insert(
                "", "end", iid=str(u["id"]),
                values=(u["nombre"], u["windows_id"], u["rol"],
                        ", ".join(u["departamentos"]),
                        fecha_corta(u["ultimo_acceso"])))

    def al_seleccionar(self, _event) -> None:
        sel = self.tabla.selection()
        if not sel:
            return
        u = next(x for x in control.listar_usuarios() if str(x["id"]) == sel[0])
        self.editando = u["id"]
        self.e_windows.delete(0, "end")
        self.e_windows.insert(0, u["windows_id"])
        self.e_nombre.delete(0, "end")
        self.e_nombre.insert(0, u["nombre"])
        self.cb_rol.set(u["rol"])
        asignados = {d.lower() for d in u["departamentos"]}
        for depto, var in self.vars_depto.items():
            var.set(depto.lower() in asignados)

    def limpiar_formulario(self) -> None:
        self.editando = None
        self.e_windows.delete(0, "end")
        self.e_nombre.delete(0, "end")
        self.cb_rol.set("usuario")
        for var in self.vars_depto.values():
            var.set(False)
        self.tabla.selection_remove(*self.tabla.selection())

    def departamentos_elegidos(self) -> list[str]:
        return [d for d, var in self.vars_depto.items() if var.get()]

    def admas(self) -> list[dict]:
        return [u for u in control.listar_usuarios() if u["rol"] == "admin"]

    def guardar(self) -> None:
        windows_id = self.e_windows.get().strip()
        nombre = self.e_nombre.get().strip()
        rol = self.cb_rol.get().strip() or "usuario"
        depts = self.departamentos_elegidos()

        if not windows_id:
            messagebox.showerror("Falta el usuario", "Escribe el usuario de Windows.")
            return
        if not nombre:
            messagebox.showerror("Falta el nombre", "Escribe el nombre.")
            return
        if rol not in control.ROLES:
            messagebox.showerror("Rol invalido", f"Rol desconocido: {rol}")
            return
        if rol == "usuario" and not depts:
            messagebox.showerror(
                "Faltan departamentos",
                "Un usuario necesita al menos un departamento, o no vera a nadie.")
            return

        existentes = control.listar_usuarios()
        if self.editando is None:
            if any(u["windows_id"].lower() == windows_id.lower() for u in existentes):
                messagebox.showerror("Ya existe",
                                     f"La cuenta {windows_id} ya existe.")
                return
            control.crear_usuario(windows_id, nombre, rol, depts)
        else:
            actual = next((u for u in existentes if u["id"] == self.editando), None)
            if actual is None:
                messagebox.showerror("No existe", "La cuenta ya no existe.")
                return
            otro = next((u for u in existentes
                         if u["id"] != self.editando
                         and u["windows_id"].lower() == windows_id.lower()), None)
            if otro is not None:
                messagebox.showerror("Ya existe",
                                     f"La cuenta {windows_id} ya existe.")
                return
            # No dejar la app sin ningun admin.
            if actual["rol"] == "admin" and rol != "admin" and len(self.admas()) == 1:
                messagebox.showerror(
                    "Ultimo admin",
                    "Esta es la unica cuenta de administrador. "
                    "Crea otra antes de quitarle el rol.")
                return
            control.actualizar_usuario(self.editando, nombre, rol, depts)

        self.recargar()
        self.limpiar_formulario()

    def eliminar(self) -> None:
        if self.editando is None:
            messagebox.showinfo("Nada seleccionado", "Elige una cuenta de la lista.")
            return
        if self.editando == self.app.sesion.id:
            messagebox.showerror("No puedes", "No puedes eliminar tu propia cuenta.")
            return
        if len(self.admas()) == 1 and self.cb_rol.get() == "admin":
            messagebox.showerror("Ultimo admin",
                                 "No se puede eliminar la unica cuenta de admin.")
            return
        usuario = self.e_windows.get().strip()
        if not messagebox.askyesno("Eliminar cuenta",
                                   f"Eliminar el acceso de {usuario}?\n\n"
                                   "El historial de cambios que hizo se conserva."):
            return
        control.eliminar_usuario(self.editando)
        self.recargar()
        self.limpiar_formulario()


if __name__ == "__main__":
    sesion = iniciar_sesion()
    if sesion is None:
        raise SystemExit(1)
    ventana = App(sesion)
    ventana.protocol("WM_DELETE_WINDOW", ventana.cerrar)
    ventana.mainloop()
