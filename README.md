# WFH-APP

App de escritorio en Python para asignar y consultar la modalidad de trabajo
(**WFH** / **OFFICE**) de los empleados.

Los datos se importan desde un Excel de RRHH a una base de datos SQLite
normalizada. La app muestra únicamente a los empleados **Active**; los
`Inactive` permanecen en la base como historial pero no aparecen.

> Este repositorio contiene solo código. Ni el Excel de origen ni la base de
> datos se versionan: ambas están en `.gitignore` porque contienen datos
> personales.

## Requisitos

- Python 3.11 o superior
- `pandas` y `openpyxl` (para la carga del Excel)
- Tkinter (viene con Python en Windows y macOS; en Linux puede necesitar
  `sudo apt install python3-tk`)

```bash
pip install pandas openpyxl
```

## Uso

```bash
python db/load_db.py   # 1. carga el Excel -> db/wfh.db
python app.py          # 2. abre la app
```

La primera vez `db/wfh.db` no existe, así que el paso 1 es obligatorio.

## Estructura

```
app.py              GUI (Tkinter): lista, filtros y asignacion de modalidad
db/load_db.py       Carga y limpieza del Excel
db/schema.sql       Esquema de la base
db/wfh.db           Base generada (no se versiona)
```

## La app

- **Buscar**: por nombre, apellido, puesto, departamento o `Emp. #`.
- **Departamento** y **Modalidad**: filtros desplegables.
- **Estado**: `Solo activos` (por defecto), `Activos`, `Inactivos`, `Todos`.

La lista de departamentos depende del filtro de estado: con `Solo activos`
muestra solo los que tienen alguien activo (9 de 31), no los que quedaron
históricamente vacíos. Si el departamento elegido ya no aplica, vuelve a
`Todos`.
- **Ordenar**: clic en el encabezado de cualquier columna.
- **Asignar**: selecciona una o varias filas y marca `WFH` u `OFFICE`.
  `Quitar asignacion` las deja sin definir; `Seleccionar visibles` toma todas
  las filas que pasan el filtro actual.
- **Recargar Excel**: relee el origen y reconstruye la base, para que los
  cambios de RRHH (por ejemplo un `Active` que pasa a `Inactive`) se apliquen.

El color de la fila indica la modalidad: verde WFH, naranja OFFICE, gris sin
asignar.

## Esquema de la base

Normalizado, siete tablas:

| Tabla | Contenido |
|---|---|
| `empleados` | Persona: nombres, puesto, salario, fechas, `modalidad`, `estado_laboral` |
| `departamentos` | Catálogo de departamentos |
| `reportes_de` | Catálogo de jefes |
| `direcciones` | Dirección y ciudad |
| `telefonos` | Fijo y celular |
| `contactos_emergencia` | Contacto y teléfono |
| `eventos_laborales` | Altas y bajas con fecha y motivo |

`v_empleados` es una vista que une empleado + departamento + jefe.

Dos decisiones de modelado que conviene conocer:

**La modalidad es una columna con `CHECK IN ('WFH', 'OFFICE')`**, no texto
libre. La base rechaza cualquier otro valor, no solo la app.

**Las fechas de alta y baja viven en `eventos_laborales`**, no como columnas
fijas. El Excel trae `hire_original` / `hire_new` y `termination` /
`termination_new`, que son en realidad el mismo concepto con más de una
versión; como filas ordenadas quedan consultables como historial.

## Notas de la carga

`load_db.py` es idempotente: borra y reconstruye. Al hacerlo, **conserva la
modalidad ya asignada**, emparejando por cédula, para que recargar el Excel no
borre el trabajo hecho en la app.

Limpieza que aplica, reportada en consola al terminar:

- Columnas 100% vacías se descartan.
- Valores que no son datos válidos (p. ej. un nombre de columna que se coló en
  `Department`) se guardan como `NULL` en vez de inventar un valor.
- Variantes de mayúsculas/acentos se unifican a la forma más frecuente. No hay
  una lista de aliases escrita a mano: la forma canónica se deduce de los
  datos, así que no hay nombres de la empresa en el código.
- Duplicados en `Emp. #`, cédula y seguro social: se conserva la primera
  aparición y se anula la segunda, sin borrar la fila. Casi siempre son dos
  personas distintas que comparten un número por error de captura.
- Cadenas vacías, `No tiene`, `N/A` y similares se normalizan a `NULL`.

## Límites conocidos

- Sin deshacer: las asignaciones se escriben directo en la base. Los cambios
  masivos sobre un filtro piden confirmación, pero no hay historial.
- La preservación de modalidad al recargar depende de la cédula. Un empleado
  sin cédula, o con una duplicada, no conserva su modalidad.
- `load_db.py` y la app no se sincronizan si se ejecutan a la vez; la app
  cierra su conexión antes de recargar por ese motivo.
