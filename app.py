from flask import Flask, render_template, request, redirect, url_for, session, flash
import pandas as pd
from datetime import datetime, timedelta
import os
import psycopg

app = Flask(__name__)
app.secret_key = "clave_secreta_proyecto"

RUTA_USUARIOS = "data/usuarios.csv"

COLUMNAS_USUARIOS = ["Usuario", "Correo", "Fecha_Registro"]


def conectar_bd():
    return psycopg.connect(
        dbname="key_resources",
        user="postgres",
        password="1234",
        host="localhost",
        port="5433"
    )


# =========================
# RECURSOS - POSTGRESQL
# =========================

def cargar_recursos():
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT id, nombre, categoria, estado, imagen
        FROM recursos
        ORDER BY id;
    """)

    filas = cursor.fetchall()
    cursor.close()
    conexion.close()

    return pd.DataFrame(filas, columns=[
        "ID", "Nombre", "Categoria", "Estado", "Imagen"
    ])


def actualizar_estado_recurso(id_recurso, estado):
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recursos
        SET estado = %s
        WHERE id = %s;
    """, (estado, id_recurso))

    conexion.commit()
    cursor.close()
    conexion.close()


# =========================
# USUARIOS - CSV
# =========================

def cargar_usuarios():
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT usuario, correo, fecha_registro
        FROM usuarios
        ORDER BY fecha_registro DESC;
    """)

    filas = cursor.fetchall()

    cursor.close()
    conexion.close()

    return pd.DataFrame(
        filas,
        columns=["Usuario", "Correo", "Fecha_Registro"]
    )


def guardar_usuario(usuario, correo):
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO usuarios (usuario, correo, fecha_registro)
        VALUES (%s, %s, %s);
    """, (
        usuario,
        correo,
        datetime.now()
    ))

    conexion.commit()

    cursor.close()
    conexion.close()


# =========================
# PRÉSTAMOS - POSTGRESQL
# =========================

def cargar_prestamos():
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT usuario, id_recurso, nombre_recurso, categoria,
               fecha_inicio, fecha_fin, estado, bloqueo_hasta
        FROM prestamos
        ORDER BY fecha_inicio DESC;
    """)

    filas = cursor.fetchall()
    cursor.close()
    conexion.close()

    return pd.DataFrame(filas, columns=[
        "Usuario", "ID_Recurso", "Nombre_Recurso", "Categoria",
        "Fecha_Inicio", "Fecha_Fin", "Estado", "Bloqueo_Hasta"
    ])


def actualizar_retrasos():
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE prestamos
        SET estado = 'No devuelto',
            bloqueo_hasta = fecha_fin + INTERVAL '1 day'
        WHERE estado = 'Activo'
        AND fecha_fin < NOW();
    """)

    conexion.commit()
    cursor.close()
    conexion.close()


def limpiar_prestamos_finalizados():
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        DELETE FROM prestamos
        WHERE estado IN ('Devuelto', 'Devuelto tarde')
        AND fecha_fin + INTERVAL '10 minutes' < NOW();
    """)

    conexion.commit()
    cursor.close()
    conexion.close()


def cantidad_prestamos_activos(usuario):
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM prestamos
        WHERE usuario = %s
        AND estado IN ('Activo', 'No devuelto');
    """, (usuario,))

    cantidad = cursor.fetchone()[0]

    cursor.close()
    conexion.close()

    return cantidad


def usuario_bloqueado(usuario, categoria):
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT bloqueo_hasta
        FROM prestamos
        WHERE usuario = %s
        AND categoria = %s
        AND estado = 'No devuelto'
        AND bloqueo_hasta > NOW()
        LIMIT 1;
    """, (usuario, categoria))

    resultado = cursor.fetchone()

    cursor.close()
    conexion.close()

    if resultado:
        return True, resultado[0]

    return False, None


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"].strip()
        correo = request.form["correo"].strip().lower()

        usuarios = cargar_usuarios()

        existente = usuarios[usuarios["Correo"].str.lower() == correo]

        if not existente.empty:
            nombre_guardado = existente.iloc[0]["Usuario"]

            if nombre_guardado != usuario:
                flash("Este correo ya está registrado con otro usuario.", "danger")
                return redirect(url_for("login"))

        else:
            nuevo = pd.DataFrame([{
                "Usuario": usuario,
                "Correo": correo,
                "Fecha_Registro": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }])

            usuarios = pd.concat([usuarios, nuevo], ignore_index=True)
            guardar_usuario(usuario, correo)

        session["usuario"] = usuario
        session["correo"] = correo

        return redirect(url_for("inicio"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# INICIO
# =========================

@app.route("/")
def inicio():
    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    return render_template("index.html", usuario=session["usuario"])


# =========================
# PERFIL
# =========================

@app.route("/perfil")
def perfil():
    if "usuario" not in session:
        return redirect(url_for("login"))

    return render_template("perfil.html")


@app.route("/subir_foto", methods=["POST"])
def subir_foto():
    if "usuario" not in session:
        return redirect(url_for("login"))

    foto = request.files.get("foto")

    if foto:
        carpeta = "static/img/users"

        if not os.path.exists(carpeta):
            os.makedirs(carpeta)

        nombre_archivo = session["correo"].replace("@", "_").replace(".", "_") + ".png"
        ruta = os.path.join(carpeta, nombre_archivo)

        foto.save(ruta)

        flash("Foto de perfil actualizada correctamente.", "success")

    return redirect(url_for("perfil"))


# =========================
# CATÁLOGO
# =========================

@app.route("/catalogo")
def catalogo():
    if "usuario" not in session:
        return redirect(url_for("login"))

    return render_template("categorias.html")


@app.route("/catalogo/<categoria>")
def catalogo_categoria(categoria):
    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    recursos = cargar_recursos()
    recursos_filtrados = recursos[recursos["Categoria"] == categoria]

    return render_template(
        "catalogo.html",
        recursos=recursos_filtrados.to_dict(orient="records"),
        categoria=categoria
    )


# =========================
# SOLICITAR
# =========================

@app.route("/solicitar/<id_recurso>", methods=["GET", "POST"])
def solicitar(id_recurso):
    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    recursos = cargar_recursos()
    recurso = recursos[recursos["ID"] == id_recurso]

    if recurso.empty:
        flash("Recurso no encontrado.", "danger")
        return redirect(url_for("catalogo"))

    recurso = recurso.iloc[0]

    usuario = session["usuario"]
    correo = session["correo"]
    categoria = recurso["Categoria"]

    bloqueado, bloqueo_hasta = usuario_bloqueado(usuario, categoria)

    if bloqueado:
        flash(f"Tienes un bloqueo temporal en {categoria} hasta {bloqueo_hasta}.", "danger")
        return redirect(url_for("catalogo_categoria", categoria=categoria))

    if cantidad_prestamos_activos(usuario) >= 3:
        flash("Ya alcanzaste el máximo de 3 préstamos activos.", "warning")
        return redirect(url_for("catalogo_categoria", categoria=categoria))

    if request.method == "POST":
        cantidad = int(request.form["cantidad"])
        unidad = request.form["unidad"]

        if unidad == "horas":
            if cantidad < 1 or cantidad > 48:
                flash("Máximo permitido: 48 horas.", "warning")
                return redirect(url_for("solicitar", id_recurso=id_recurso))

            duracion = timedelta(hours=cantidad)

        elif unidad == "dias":
            if cantidad < 1 or cantidad > 2:
                flash("Máximo permitido: 2 días.", "warning")
                return redirect(url_for("solicitar", id_recurso=id_recurso))

            duracion = timedelta(days=cantidad)

        else:
            flash("Unidad inválida.", "danger")
            return redirect(url_for("solicitar", id_recurso=id_recurso))

        if recurso["Estado"] == "Prestado":
            flash("Este recurso ya está prestado.", "warning")
            return redirect(url_for("catalogo_categoria", categoria=categoria))

        fecha_inicio = datetime.now()
        fecha_fin = fecha_inicio + duracion

        conexion = conectar_bd()
        cursor = conexion.cursor()

        cursor.execute("""
            INSERT INTO prestamos (
                usuario, correo, id_recurso, nombre_recurso,
                categoria, fecha_inicio, fecha_fin, estado, bloqueo_hasta
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL);
        """, (
            usuario,
            correo,
            recurso["ID"],
            recurso["Nombre"],
            recurso["Categoria"],
            fecha_inicio,
            fecha_fin,
            "Activo"
        ))

        cursor.execute("""
            UPDATE recursos
            SET estado = 'Prestado'
            WHERE id = %s;
        """, (id_recurso,))

        conexion.commit()
        cursor.close()
        conexion.close()

        flash("Préstamo registrado correctamente.", "success")

        return redirect(url_for("prestamos"))

    return render_template("solicitar.html", recurso=recurso)


# =========================
# PRÉSTAMOS
# =========================

@app.route("/prestamos")
def prestamos():
    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    prestamos = cargar_prestamos()

    return render_template(
        "prestamos.html",
        prestamos=prestamos.to_dict(orient="records"),
        usuario_actual=session["usuario"]
    )


@app.route("/devolver/<id_recurso>")
def devolver(id_recurso):
    if "usuario" not in session:
        return redirect(url_for("login"))

    usuario = session["usuario"]

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT estado
        FROM prestamos
        WHERE id_recurso = %s
        AND usuario = %s
        AND estado IN ('Activo', 'No devuelto')
        ORDER BY fecha_inicio DESC
        LIMIT 1;
    """, (id_recurso, usuario))

    resultado = cursor.fetchone()

    if resultado:
        estado_actual = resultado[0]

        nuevo_estado = "Devuelto tarde" if estado_actual == "No devuelto" else "Devuelto"

        cursor.execute("""
            UPDATE prestamos
            SET estado = %s
            WHERE id_recurso = %s
            AND usuario = %s
            AND estado IN ('Activo', 'No devuelto');
        """, (nuevo_estado, id_recurso, usuario))

        cursor.execute("""
            UPDATE recursos
            SET estado = 'Disponible'
            WHERE id = %s;
        """, (id_recurso,))

        conexion.commit()

        flash("Recurso devuelto correctamente.", "success")

    else:
        flash("No se pudo devolver el recurso.", "danger")

    cursor.close()
    conexion.close()

    return redirect(url_for("prestamos"))


# =========================
# USUARIOS
# =========================

@app.route("/usuarios")
def usuarios():
    if "usuario" not in session:
        return redirect(url_for("login"))

    usuarios = cargar_usuarios()

    return render_template(
        "usuarios.html",
        usuarios=usuarios.to_dict(orient="records")
    )


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    app.run(debug=True, port=5001)