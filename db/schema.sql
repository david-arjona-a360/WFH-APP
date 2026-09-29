-- Esquema normalizado - WFH app
PRAGMA foreign_keys = ON;

-- Orden importa: primero las tablas hijas, luego empleados, y al final las
-- que empleados referencia (si no, el DROP choca con las claves foraneas).
DROP TABLE IF EXISTS eventos_laborales;
DROP TABLE IF EXISTS contactos_emergencia;
DROP TABLE IF EXISTS telefonos;
DROP TABLE IF EXISTS direcciones;
DROP TABLE IF EXISTS empleados;
DROP TABLE IF EXISTS reportes_de;
DROP TABLE IF EXISTS departamentos;
DROP VIEW IF EXISTS v_empleados;

CREATE TABLE departamentos (
    id_departamento INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL UNIQUE
);

CREATE TABLE reportes_de (
    id_reports_to  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT NOT NULL UNIQUE
);

CREATE TABLE empleados (
    id_empleado          INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_num              INTEGER UNIQUE,
    id_departamento      INTEGER REFERENCES departamentos(id_departamento),
    id_reports_to        INTEGER REFERENCES reportes_de(id_reports_to),
    cedula               TEXT UNIQUE,
    seguro_social        TEXT UNIQUE,
    nombres              TEXT NOT NULL,
    apellidos            TEXT NOT NULL,
    nombre_completo      TEXT,
    genero               TEXT CHECK (genero IN ('Male', 'Female')),
    estado_civil         TEXT CHECK (estado_civil IN ('Single', 'Married')),
    puesto               TEXT,
    salario              NUMERIC,
    tarifa_por_hora      NUMERIC,
    fecha_nacimiento     DATE,
    antiguedad_anios     INTEGER,
    tiene_hijos          BOOLEAN,
    correo               TEXT,
    estado_laboral       TEXT CHECK (estado_laboral IN ('Active', 'Inactive')),
    modalidad            TEXT CHECK (modalidad IN ('WFH', 'OFFICE')),
    numero_insignia      TEXT
);

CREATE TABLE direcciones (
    id_direccion     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_empleado      INTEGER NOT NULL REFERENCES empleados(id_empleado) ON DELETE CASCADE,
    linea1           TEXT,
    ciudad           TEXT,
    region           TEXT
);

CREATE TABLE telefonos (
    id_telefono      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_empleado      INTEGER NOT NULL REFERENCES empleados(id_empleado) ON DELETE CASCADE,
    tipo             TEXT NOT NULL CHECK (tipo IN ('home', 'mobile')),
    numero           TEXT NOT NULL
);

CREATE TABLE contactos_emergencia (
    id_contacto          INTEGER PRIMARY KEY AUTOINCREMENT,
    id_empleado          INTEGER NOT NULL REFERENCES empleados(id_empleado) ON DELETE CASCADE,
    nombre               TEXT,
    telefono             TEXT,
    UNIQUE (id_empleado, telefono)
);

CREATE TABLE eventos_laborales (
    id_evento        INTEGER PRIMARY KEY AUTOINCREMENT,
    id_empleado      INTEGER NOT NULL REFERENCES empleados(id_empleado) ON DELETE CASCADE,
    tipo             TEXT NOT NULL CHECK (tipo IN ('hire_original', 'hire_new', 'termination', 'rehire', 'termination_new')),
    fecha            DATE,
    motivo           TEXT,
    orden            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX ix_empleados_depto ON empleados(id_departamento);
CREATE INDEX ix_empleados_estado ON empleados(estado_laboral);
CREATE INDEX ix_empleados_modalidad ON empleados(modalidad);
CREATE INDEX ix_empleados_apellidos ON empleados(apellidos, nombres);
CREATE INDEX ix_telefonos_empleado ON telefonos(id_empleado);
CREATE INDEX ix_eventos_empleado ON eventos_laborales(id_empleado, orden);

CREATE VIEW v_empleados AS
SELECT
    e.id_empleado,
    e.emp_num,
    e.nombres,
    e.apellidos,
    e.nombre_completo,
    e.puesto,
    d.nombre AS departamento,
    r.nombre AS reporta_a,
    e.estado_laboral,
    e.salario,
    e.tarifa_por_hora,
    e.fecha_nacimiento,
    e.antiguedad_anios,
    e.modalidad,
    e.correo
FROM empleados e
LEFT JOIN departamentos d ON d.id_departamento = e.id_departamento
LEFT JOIN reportes_de  r ON r.id_reports_to   = e.id_reports_to;
