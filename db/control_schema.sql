-- Control de acceso y auditoria.
-- Va en db/control.db, separado de wfh.db, porque ese se borra y se
-- reconstruye en cada recarga del Excel.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    -- DOMINIO\usuario de Windows, leido del token del proceso.
    windows_id    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nombre        TEXT NOT NULL,
    rol           TEXT NOT NULL CHECK (rol IN ('admin', 'usuario')),
    creado_en     TEXT NOT NULL,
    ultimo_acceso TEXT
);

-- El departamento se guarda por NOMBRE y no por id: 'departamentos' vive en
-- wfh.db y SQLite no valida claves foraneas entre dos archivos distintos.
CREATE TABLE IF NOT EXISTS usuarios_departamentos (
    id_usuario   INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    departamento TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (id_usuario, departamento)
);

-- El empleado se referencia por cedula, no por id_empleado: ese id se
-- reasigna cada vez que se recrea la tabla empleados.
CREATE TABLE IF NOT EXISTS cambios_modalidad (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    cedula             TEXT,
    emp_num            INTEGER,
    nombre             TEXT NOT NULL,
    departamento       TEXT,
    modalidad_anterior TEXT,
    modalidad_nueva    TEXT,
    windows_id         TEXT NOT NULL,
    rol                TEXT NOT NULL,
    fecha              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cambios_departamento ON cambios_modalidad(departamento);
CREATE INDEX IF NOT EXISTS ix_cambios_fecha ON cambios_modalidad(fecha DESC);
CREATE INDEX IF NOT EXISTS ix_cambios_cedula ON cambios_modalidad(cedula);
