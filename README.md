# WFH-APP

App de escritorio en Python para asignar y consultar la modalidad de trabajo
(**WFH** / **OFFICE**) de los empleados.

Los datos se importan desde un Excel de RRHH a una base de datos SQLite
normalizada. La app muestra únicamente a los empleados **Active**; los
`Inactive` permanecen en la base como historial pero no aparecen.

El acceso se controla con la **identidad de Windows** del dominio: no hay
contrasenas. Cada persona entra con su cuenta corporativa y solo ve lo que su
rol le permite.

> Este repositorio contiene solo código. Ni el Excel de origen ni las bases de
> datos se versionan: están en `.gitignore` porque contienen datos personales.

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

## Acceso y roles

No hay usuario ni contraseña que escribir: la app lee la identidad de Windows
de la sesión y busca esa cuenta en `db/control.db`. Si no existe, **no entra**.

| Rol | Qué ve |
|---|---|
| `admin` | Todos los empleados, todos los estados, gestión de cuentas, recarga del Excel e historial completo |
| `usuario` | Solo los empleados **Active** de los departamentos que el admin le asignó, e historial de esos mismos departamentos |

El ámbito se impone en la consulta SQL, no escondiendo filas: un usuario no
logra ver a nadie de otro departamento ni usando el filtro de Estado, porque
esas opciones ni siquiera se le ofrecen.

**Primer arranque.** Sin `db/control.db` cualquiera que abriera la app entraría
como administrador, así que el primer admin solo puede crearlo una cuenta de
arranque autorizada (`david.arjona` o `julio.lerma`, en `db/control.py`). Las
demás cuentas las agrega un admin desde **Gestionar usuarios**.

La app no deja quedarse sin administración: no se puede eliminar la única
cuenta de admin, ni degradarla, ni borrar la propia sesión.

**Sobre la identidad.** Se resuelve por `GetUserNameExW`, luego por el SID del
token del proceso, luego `GetUserNameW`. Si las tres fallan se cae a las
variables de entorno, que **son falseables a mano** desde la consola: la app lo
avisa por pantalla, pero conviene saber que ahí la identidad ya no es una
garantía. Para diagnosticar:

```bash
python db/control.py
```

## Estructura

```
app.py               GUI (Tkinter): lista, filtros, asignacion, historial
db/load_db.py        Carga y limpieza del Excel
db/schema.sql        Esquema de empleados
db/control.py        Cuentas, permisos, auditoria e identidad de Windows
db/control_schema.sql Esquema de cuentas y auditoria
db/wfh.db            Base generada (no se versiona)
db/control.db        Cuentas e historial (no se versiona)
```

`wfh.db` y `control.db` están separadas a propósito: recargar el Excel
reconstruye `wfh.db` desde cero, y las cuentas no pueden desaparecer con ella.

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

La tabla arranca sin nada seleccionado, y filtrar o cambiar el estado tampoco
selecciona: la selección solo cambia si la haces tú, con clic o con
`Seleccionar visibles`. Así marcar `WFH` nunca arrastra a los 201 empleados
por accident. Ordenar conserva lo que estuviera seleccionado.

El texto de la tabla es negro. Para distinguir la modalidad hay que mirar la
columna `Modalidad`, que muestra `WFH`, `OFFICE` o `Sin asignar`: sin ese
texto, una celda vacía no se diferenciaría de un dato que falta.

La pestaña **Historial** registra cada cambio real de modalidad: quién lo hizo,
en qué departamento y de qué valor a qué valor. Si a alguien se le repite la
modalidad que ya tenía, no se anota, para que el historial muestre cambios y no
clics. Un usuario solo ve los movimientos de sus departamentos.

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

- Sin deshacer. Hay historial de cambios, pero no una acción que los revierta:
  corregir un error es volver a marcar la modalidad correcta.
- El historial registra la **modalidad**, no quién-editó-cualquier-otra-cosa.
  Cambiar el Excel, el rol o los departamentos de una cuenta no queda auditado.
- El preservador de modalidad al recargar depende de la cédula. Un empleado
  sin cédula, o con una duplicada, no conserva su modalidad.
- `load_db.py` y la app no se sincronizan si se ejecutan a la vez; la app
  cierra su conexión antes de recargar por ese motivo.
- Los departamentos de un usuario se guardan por **nombre**. Si el Excel
  renombra un departamento, ese usuario deja de ver a su gente hasta que un
  admin vuelva a asignarlo; la app lo avisa en la barra inferior en vez de
  mostrar una lista vacía sin explicación.
- La identidad de Windows es un control de acceso, no una autenticación fuerte:
  se apoya en que la máquina y la sesión de Windows sean confiables. No protege
  contra alguien con acceso administrativo al equipo.
