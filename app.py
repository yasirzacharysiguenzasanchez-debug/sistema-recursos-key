from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from flask import send_file
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
import os
import psycopg

app = Flask(__name__)
app.secret_key = "clave_secreta_proyecto"



# =========================================
# CONEXIÓN POSTGRESQL
# =========================================

def conectar_bd():

    return psycopg.connect(
        dbname="key_resources",
        user="postgres",
        password="1234",
        host="localhost",
        port="5433"
    )


# =========================================
# RECURSOS
# =========================================

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

    return pd.DataFrame(
        filas,
        columns=["ID", "Nombre", "Categoria", "Estado", "Imagen"]
    )


# =========================================
# USUARIOS
# =========================================

def cargar_usuarios():

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
    SELECT usuario, correo, fecha_registro, rol, password_hash
    FROM usuarios
    ORDER BY fecha_registro DESC;
""")

    filas = cursor.fetchall()

    cursor.close()
    conexion.close()

    return pd.DataFrame(
        filas,
        columns=["Usuario", "Correo", "Fecha_Registro", "Rol", "Password_Hash"]
    )


def guardar_usuario(usuario, correo, password):

    password_hash = generate_password_hash(password)

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO usuarios (
            usuario,
            correo,
            fecha_registro,
            rol,
            password_hash
        )
        VALUES (%s, %s, %s, %s, %s);
    """, (
        usuario,
        correo,
        datetime.now(),
        "usuario",
        password_hash
    ))

    conexion.commit()

    cursor.close()
    conexion.close()


# =========================================
# PRÉSTAMOS
# =========================================

def cargar_prestamos():

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            usuario,
            correo,
            id_recurso,
            nombre_recurso,
            categoria,
            fecha_inicio,
            fecha_fin,
            estado,
            bloqueo_hasta
        FROM prestamos
        ORDER BY fecha_inicio DESC;
    """)

    filas = cursor.fetchall()

    cursor.close()
    conexion.close()

    return pd.DataFrame(
        filas,
        columns=[
            "Usuario",
            "Correo",
            "ID_Recurso",
            "Nombre_Recurso",
            "Categoria",
            "Fecha_Inicio",
            "Fecha_Fin",
            "Estado",
            "Bloqueo_Hasta"
        ]
    )


def actualizar_retrasos():

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE prestamos
        SET
            estado = 'No devuelto',
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


def cantidad_prestamos_activos(correo):

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM prestamos
        WHERE correo = %s
        AND estado IN ('Activo', 'No devuelto');
    """, (correo,))

    cantidad = cursor.fetchone()[0]

    cursor.close()
    conexion.close()

    return cantidad


def usuario_bloqueado(correo, categoria):

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT bloqueo_hasta
        FROM prestamos
        WHERE correo = %s
        AND categoria = %s
        AND estado = 'No devuelto'
        AND bloqueo_hasta > NOW()
        LIMIT 1;
    """, (correo, categoria))

    resultado = cursor.fetchone()

    cursor.close()
    conexion.close()

    if resultado:
        return True, resultado[0]

    return False, None


# =========================================
# LOGIN
# =========================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        usuario = request.form["usuario"].strip()
        correo = request.form["correo"].strip().lower()
        password = request.form["password"]

        usuarios = cargar_usuarios()

        existente = usuarios[
            usuarios["Correo"].str.lower() == correo
        ]

        if not existente.empty:

            nombre_guardado = existente.iloc[0]["Usuario"]
            password_hash = existente.iloc[0]["Password_Hash"]
            rol_guardado = existente.iloc[0]["Rol"]

            if nombre_guardado != usuario:

                flash(
                    "Este correo ya está registrado con otro usuario.",
                    "danger"
                )

                return redirect(url_for("login"))

            if not password_hash or not check_password_hash(password_hash, password):

                flash(
                    "Contraseña incorrecta.",
                    "danger"
                )

                return redirect(url_for("login"))

            session["rol"] = rol_guardado

        else:

            guardar_usuario(usuario, correo, password)

            session["rol"] = "usuario"

        session["usuario"] = usuario
        session["correo"] = correo

        return redirect(url_for("inicio"))

    return render_template("login.html")

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================
# INICIO
# =========================================
def obtener_estadisticas_dashboard():
    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("SELECT COUNT(*) FROM recursos;")
    total_recursos = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM recursos WHERE estado = 'Disponible';")
    disponibles = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM prestamos
        WHERE estado = 'Activo';
    """)
    activos = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM prestamos
        WHERE estado = 'No devuelto';
    """)
    vencidos = cursor.fetchone()[0]

    cursor.close()
    conexion.close()

    return {
        "total_recursos": total_recursos,
        "disponibles": disponibles,
        "activos": activos,
        "vencidos": vencidos
    }

@app.route("/")
def inicio():

    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    estadisticas = obtener_estadisticas_dashboard()

    return render_template(
        "index.html",
        usuario=session["usuario"],
        estadisticas=estadisticas
    )

# =========================================
# PERFIL
# =========================================

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

        nombre_archivo = (
            session["correo"]
            .replace("@", "_")
            .replace(".", "_")
            + ".png"
        )

        ruta = os.path.join(carpeta, nombre_archivo)

        foto.save(ruta)

        flash(
            "Foto de perfil actualizada correctamente.",
            "success"
        )

    return redirect(url_for("perfil"))


# =========================================
# CATÁLOGO
# =========================================

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

    recursos_filtrados = recursos[
        recursos["Categoria"] == categoria
    ]

    return render_template(
        "catalogo.html",
        recursos=recursos_filtrados.to_dict(orient="records"),
        categoria=categoria
    )


# =========================================
# SOLICITAR
# =========================================

@app.route("/solicitar/<id_recurso>", methods=["GET", "POST"])
def solicitar(id_recurso):

    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    recursos = cargar_recursos()

    recurso = recursos[
        recursos["ID"] == id_recurso
    ]

    if recurso.empty:

        flash(
            "Recurso no encontrado.",
            "danger"
        )

        return redirect(url_for("catalogo"))

    recurso = recurso.iloc[0]

    usuario = session["usuario"]
    correo = session["correo"]

    categoria = recurso["Categoria"]

    bloqueado, bloqueo_hasta = usuario_bloqueado(
        correo,
        categoria
    )

    if bloqueado:

        flash(
            f"Tienes un bloqueo temporal en {categoria} hasta {bloqueo_hasta}.",
            "danger"
        )

        return redirect(
            url_for(
                "catalogo_categoria",
                categoria=categoria
            )
        )

    if cantidad_prestamos_activos(correo) >= 3:

        flash(
            "Ya alcanzaste el máximo de 3 préstamos activos.",
            "warning"
        )

        return redirect(
            url_for(
                "catalogo_categoria",
                categoria=categoria
            )
        )

    if request.method == "POST":

        cantidad = int(request.form["cantidad"])
        unidad = request.form["unidad"]

        if unidad == "horas":

            if cantidad < 1 or cantidad > 48:

                flash(
                    "Máximo permitido: 48 horas.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "solicitar",
                        id_recurso=id_recurso
                    )
                )

            duracion = timedelta(hours=cantidad)

        elif unidad == "dias":

            if cantidad < 1 or cantidad > 2:

                flash(
                    "Máximo permitido: 2 días.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "solicitar",
                        id_recurso=id_recurso
                    )
                )

            duracion = timedelta(days=cantidad)

        else:

            flash(
                "Unidad inválida.",
                "danger"
            )

            return redirect(
                url_for(
                    "solicitar",
                    id_recurso=id_recurso
                )
            )

        if recurso["Estado"] == "Prestado":

            flash(
                "Este recurso ya está prestado.",
                "warning"
            )

            return redirect(
                url_for(
                    "catalogo_categoria",
                    categoria=categoria
                )
            )

        fecha_inicio = datetime.now()
        fecha_fin = fecha_inicio + duracion

        conexion = conectar_bd()
        cursor = conexion.cursor()

        cursor.execute("""
            INSERT INTO prestamos (
                usuario,
                correo,
                id_recurso,
                nombre_recurso,
                categoria,
                fecha_inicio,
                fecha_fin,
                estado,
                bloqueo_hasta
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, NULL
            );
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

        flash(
            "Préstamo registrado correctamente.",
            "success"
        )

        return redirect(url_for("prestamos"))

    return render_template(
        "solicitar.html",
        recurso=recurso
    )


# =========================================
# PRÉSTAMOS
# =========================================

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
        usuario_actual=session["usuario"],
        correo_actual=session["correo"]
    )


@app.route("/devolver/<id_recurso>")
def devolver(id_recurso):

    if "usuario" not in session:
        return redirect(url_for("login"))

    correo = session["correo"]

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT estado
        FROM prestamos
        WHERE id_recurso = %s
        AND correo = %s
        AND estado IN ('Activo', 'No devuelto')
        ORDER BY fecha_inicio DESC
        LIMIT 1;
    """, (
        id_recurso,
        correo
    ))

    resultado = cursor.fetchone()

    if resultado:

        estado_actual = resultado[0]

        if estado_actual == "No devuelto":
            nuevo_estado = "Devuelto tarde"
        else:
            nuevo_estado = "Devuelto"

        cursor.execute("""
            UPDATE prestamos
            SET estado = %s
            WHERE id_recurso = %s
            AND correo = %s
            AND estado IN ('Activo', 'No devuelto');
        """, (
            nuevo_estado,
            id_recurso,
            correo
        ))

        cursor.execute("""
            UPDATE recursos
            SET estado = 'Disponible'
            WHERE id = %s;
        """, (id_recurso,))

        conexion.commit()

        flash(
            "Recurso devuelto correctamente.",
            "success"
        )

    else:

        flash(
            "No se pudo devolver el recurso.",
            "danger"
        )

    cursor.close()
    conexion.close()

    return redirect(url_for("prestamos"))


# =========================================
# MAIN
# =========================================
@app.route("/admin")
def admin():

    if "usuario" not in session:
        return redirect(url_for("login"))

    if session.get("rol") != "admin":
        flash("No tienes permisos para acceder al panel admin.", "danger")
        return redirect(url_for("inicio"))

    usuarios = cargar_usuarios()
    prestamos = cargar_prestamos()
    recursos = cargar_recursos()

    return render_template(
        "admin.html",
        usuarios=usuarios.to_dict(orient="records"),
        prestamos=prestamos.to_dict(orient="records"),
        recursos=recursos.to_dict(orient="records")
    )
@app.route("/admin/recursos")
def admin_recursos():

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    recursos = cargar_recursos()

    return render_template(
        "admin_recursos.html",
        recursos=recursos.to_dict(orient="records")
    )
@app.route("/admin/eliminar/<id_recurso>")
def eliminar_recurso(id_recurso):

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        DELETE FROM recursos
        WHERE id = %s
    """, (id_recurso,))

    conexion.commit()

    cursor.close()
    conexion.close()

    flash("Recurso eliminado correctamente.", "success")

    return redirect(url_for("admin_recursos"))

@app.route("/admin/agregar-recurso", methods=["GET", "POST"])
def agregar_recurso():

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    if request.method == "POST":

        id_recurso = request.form["id"].strip()
        nombre = request.form["nombre"].strip()
        categoria = request.form["categoria"]

        imagen_file = request.files.get("imagen")

        if imagen_file and imagen_file.filename != "":

            carpeta_categoria = categoria

            carpeta_destino = os.path.join(
                "static",
                "img",
                carpeta_categoria
            )

            if not os.path.exists(carpeta_destino):
                os.makedirs(carpeta_destino)

            nombre_archivo = imagen_file.filename

            ruta_guardado = os.path.join(
                carpeta_destino,
                nombre_archivo
            )

            imagen_file.save(ruta_guardado)

            ruta_bd = f"{carpeta_categoria}/{nombre_archivo}"

        else:
            ruta_bd = ""

        conexion = conectar_bd()
        cursor = conexion.cursor()

        cursor.execute("""
            INSERT INTO recursos (id, nombre, categoria, estado, imagen)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            id_recurso,
            nombre,
            categoria,
            "Disponible",
            ruta_bd
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        flash("Recurso agregado correctamente.", "success")

        return redirect(url_for("admin_recursos"))

    return render_template("agregar_recurso.html")

@app.route("/admin/editar/<id_recurso>", methods=["GET", "POST"])
def editar_recurso(id_recurso):

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    conexion = conectar_bd()
    cursor = conexion.cursor()

    if request.method == "POST":

        nombre = request.form["nombre"].strip()
        categoria = request.form["categoria"]
        estado = request.form["estado"]
        imagen = request.form["imagen"].strip()

        cursor.execute("""
            UPDATE recursos
            SET nombre = %s,
                categoria = %s,
                estado = %s,
                imagen = %s
            WHERE id = %s;
        """, (
            nombre,
            categoria,
            estado,
            imagen,
            id_recurso
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        flash("Recurso actualizado correctamente.", "success")

        return redirect(url_for("admin_recursos"))

    cursor.execute("""
        SELECT id, nombre, categoria, estado, imagen
        FROM recursos
        WHERE id = %s;
    """, (id_recurso,))

    recurso = cursor.fetchone()

    cursor.close()
    conexion.close()

    if not recurso:
        flash("Recurso no encontrado.", "danger")
        return redirect(url_for("admin_recursos"))

    recurso = {
        "ID": recurso[0],
        "Nombre": recurso[1],
        "Categoria": recurso[2],
        "Estado": recurso[3],
        "Imagen": recurso[4]
    }

    return render_template(
        "editar_recurso.html",
        recurso=recurso
    )

@app.route("/admin/prestamos")
def admin_prestamos():

    if session.get("rol") != "admin":
        flash("No tienes permisos para acceder.", "danger")
        return redirect(url_for("inicio"))

    prestamos = cargar_prestamos()

    return render_template(
        "admin_prestamos.html",
        prestamos=prestamos.to_dict(orient="records")
    )

@app.route("/admin/exportar-excel")
def exportar_excel():

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    prestamos = cargar_prestamos()

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        prestamos.to_excel(writer, index=False, sheet_name="Prestamos")

    output.seek(0)

    return send_file(
        output,
        download_name="prestamos.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/admin/exportar-pdf")
def exportar_pdf():

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    prestamos = cargar_prestamos()

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter)

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, 750, "Reporte de Préstamos")

    y = 710
    pdf.setFont("Helvetica", 9)

    for _, prestamo in prestamos.iterrows():

        texto = f"{prestamo['Usuario']} | {prestamo['Nombre_Recurso']} | {prestamo['Estado']} | {prestamo['Fecha_Fin']}"
        pdf.drawString(40, y, texto)

        y -= 18

        if y < 50:
            pdf.showPage()
            pdf.setFont("Helvetica", 9)
            y = 750

    pdf.save()
    output.seek(0)

    return send_file(
        output,
        download_name="prestamos.pdf",
        as_attachment=True,
        mimetype="application/pdf"
    )


@app.route("/admin/eliminar-usuario/<correo>")
def eliminar_usuario(correo):

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        DELETE FROM usuarios
        WHERE correo = %s;
    """, (correo,))

    conexion.commit()
    cursor.close()
    conexion.close()

    flash("Usuario eliminado correctamente.", "success")

    return redirect(url_for("admin"))

@app.route("/admin/devolver/<id_recurso>/<correo>")
def admin_devolver(id_recurso, correo):

    if session.get("rol") != "admin":
        return redirect(url_for("inicio"))

    conexion = conectar_bd()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE prestamos
        SET estado = 'Devuelto'
        WHERE id_recurso = %s
        AND correo = %s
        AND estado IN ('Activo', 'No devuelto');
    """, (id_recurso, correo))

    cursor.execute("""
        UPDATE recursos
        SET estado = 'Disponible'
        WHERE id = %s;
    """, (id_recurso,))

    conexion.commit()
    cursor.close()
    conexion.close()

    flash("Préstamo devuelto por administrador.", "success")

    return redirect(url_for("admin_prestamos"))
    

if __name__ == "__main__":
    app.run(debug=True, port=5001)