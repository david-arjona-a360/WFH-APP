"""App para asignar la modalidad de trabajo (WFH / OFFICE) de cada empleado."""

import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
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


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Modalidad de trabajo - WFH / OFFICE")
        self.geometry("1080x620")
        self.minsize(900, 480)
        self.con = self.conectar()

        self.busqueda = tk.StringVar()
        self.f_depto = tk.StringVar(value="Todos")
        self.f_modalidad = tk.StringVar(value="Todas")
        self.f_estado = tk.StringVar(value="Solo activos")
        self.mensaje = tk.StringVar(value="Listo.")
        self.seleccion = tk.StringVar(value="Ningun empleado seleccionado")

        self.ids_seleccionados: set[int] = set()
        self.filas: dict[str, tuple] = {}
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

    def refrescar_filtros(self) -> None:
        self.deptos = sorted(
            r["departamento"] for r in self.consultar(
                "SELECT DISTINCT departamento FROM v_empleados "
                "WHERE departamento IS NOT NULL")
        )
        self.combo_depto["values"] = ["Todos", *self.deptos]
        self.combo_mod["values"] = ["Todas", *MODALIDADES, SIN_ASIGNAR]

    def condicion_estado(self) -> tuple[str, list]:
        """El filtro de estado manda: los departamentos se listan segun el."""
        if self.f_estado.get() == "Solo activos":
            return "estado_laboral = 'Active'", []
        if self.f_estado.get() in VALOR_ESTADO:
            return "estado_laboral = ?", [VALOR_ESTADO[self.f_estado.get()]]
        return "", []

    def refrescar_filtros(self) -> None:
        where_estado, params = self.condicion_estado()
        extra = f" AND {where_estado}" if where_estado else ""
        self.deptos = sorted(
            r["departamento"] for r in self.consultar(
                "SELECT DISTINCT departamento FROM v_empleados "
                f"WHERE departamento IS NOT NULL{extra}",
                tuple(params),
            )
        )
        # Si el departamento seleccionado ya no aplica, se vuelve a "Todos"
        # para no dejar el filtro en un valor que no existe en la lista.
        if self.f_depto.get() != "Todos" and self.f_depto.get() not in self.deptos:
            self.f_depto.set("Todos")
        self.combo_depto["values"] = ["Todos", *self.deptos]
        self.combo_mod["values"] = ["Todas", *MODALIDADES, SIN_ASIGNAR]

    def condiciones(self) -> tuple[str, list]:
        where, params = [], []
        where_estado, params_estado = self.condicion_estado()
        if where_estado:
            where.append(where_estado)
            params.extend(params_estado)
        if self.f_depto.get() != "Todos":
            where.append("departamento = ?")
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

    # --- interfaz ------------------------------------------------------
    def construir_widgets(self) -> None:
        marco = ttk.Frame(self, padding=10)
        marco.pack(fill="both", expand=True)

        filtros = ttk.Frame(marco)
        filtros.pack(fill="x")

        ttk.Label(filtros, text="Buscar:").pack(side="left")
        self.entrada = ttk.Entry(filtros, textvariable=self.busqueda, width=28)
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
        self.combo_estado = ttk.Combobox(
            filtros, textvariable=self.f_estado, state="readonly", width=13,
            values=ESTADOS_FILTRO)
        self.combo_estado.pack(side="left", padx=(4, 14))
        self.combo_estado.bind("<<ComboboxSelected>>",
                               lambda _: self.al_cambiar_estado())

        ttk.Button(filtros, text="Limpiar filtros",
                   command=self.limpiar_filtros).pack(side="left")
        ttk.Button(filtros, text="Recargar Excel",
                   command=self.recargar_excel).pack(side="left", padx=(10, 0))

        self.tabla = ttk.Treeview(
            marco, columns=COLS, show="headings", selectmode="extended")
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

        scroll = ttk.Scrollbar(marco, orient="vertical",
                               command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tabla.pack(fill="both", expand=True, pady=10)

        acciones = ttk.Frame(marco)
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

        ttk.Label(marco, textvariable=self.mensaje, relief="sunken",
                  anchor="w", padding=4).pack(fill="x", pady=(10, 0))

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
        self.con.execute(
            f"UPDATE empleados SET modalidad = ? "
            f"WHERE id_empleado IN ({marcadores})",
            [modalidad, *ids],
        )
        self.con.commit()
        self.mensaje.set(f"{len(ids)} empleado(s) -> {modalidad or SIN_ASIGNAR}")
        self.cargar_empleados()
        if not self.filas and where:
            self.mensaje.set(
                f"{len(ids)} empleado(s) -> {modalidad or SIN_ASIGNAR}  |  "
                f"ya no coinciden con el filtro activo"
            )

    def actualizar_estado(self, filas: list[sqlite3.Row]) -> None:
        wfh = sum(1 for f in filas if f["modalidad"] == "WFH")
        office = sum(1 for f in filas if f["modalidad"] == "OFFICE")
        activos = self.consultar(
            "SELECT COUNT(*) FROM v_empleados WHERE estado_laboral = 'Active'"
        )[0][0]
        self.mensaje.set(
            f"{len(filas)} en la lista  |  WFH: {wfh}  |  OFFICE: {office}  |  "
            f"{SIN_ASIGNAR}: {len(filas) - wfh - office}  |  "
            f"{activos} empleados activos en total"
        )

    def cerrar(self) -> None:
        self.con.close()
        self.destroy()


if __name__ == "__main__":
    ventana = App()
    ventana.protocol("WM_DELETE_WINDOW", ventana.cerrar)
    ventana.mainloop()
