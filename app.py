from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = "clave_secreta_proyecto"

RUTA_RECURSOS = "data/recursos.csv"
RUTA_PRESTAMOS = "data/prestamos.csv"


def cargar_recursos():
    return pd.read_csv(RUTA_RECURSOS)


def guardar_recursos(df):
    df.to_csv(RUTA_RECURSOS, index=False)


def cargar_prestamos():
    columnas = [
        "Usuario", "ID_Recurso", "Nombre_Recurso", "Categoria",
        "Fecha_Inicio", "Fecha_Fin", "Estado", "Bloqueo_Hasta"
    ]

    if os.path.exists(RUTA_PRESTAMOS):
        prestamos = pd.read_csv(RUTA_PRESTAMOS)

        for col in columnas:
            if col not in prestamos.columns:
                prestamos[col] = ""

        return prestamos[columnas]

    return pd.DataFrame(columns=columnas)


def guardar_prestamos(df):
    df.to_csv(RUTA_PRESTAMOS, index=False)


def actualizar_retrasos():
    prestamos = cargar_prestamos()
    hoy = datetime.now()

    if prestamos.empty:
        return

    for i, row in prestamos.iterrows():

        if row["Estado"] == "Activo":

            fecha_fin = datetime.strptime(
                row["Fecha_Fin"],
                "%Y-%m-%d %H:%M:%S"
            )

            if hoy > fecha_fin:
                prestamos.at[i, "Estado"] = "No devuelto"

                bloqueo = fecha_fin + timedelta(days=1)

                prestamos.at[i, "Bloqueo_Hasta"] = bloqueo.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

    guardar_prestamos(prestamos)


def limpiar_prestamos_finalizados():
    prestamos = cargar_prestamos()

    if prestamos.empty:
        return

    hoy = datetime.now()
    filas_a_conservar = []

    for i, row in prestamos.iterrows():

        if row["Estado"] in ["Devuelto", "Devuelto tarde"]:

            fecha_fin = datetime.strptime(
                row["Fecha_Fin"],
                "%Y-%m-%d %H:%M:%S"
            )

            if hoy <= fecha_fin + timedelta(minutes=10):
                filas_a_conservar.append(i)

        else:
            filas_a_conservar.append(i)

    prestamos = prestamos.loc[filas_a_conservar]

    guardar_prestamos(prestamos)


def usuario_bloqueado_categoria(usuario, categoria):
    prestamos = cargar_prestamos()
    hoy = datetime.now()

    bloqueos = prestamos[
        (prestamos["Usuario"] == usuario) &
        (prestamos["Categoria"] == categoria) &
        (prestamos["Estado"] == "No devuelto")
    ]

    for _, row in bloqueos.iterrows():

        if row["Bloqueo_Hasta"] != "":

            bloqueo_hasta = datetime.strptime(
                row["Bloqueo_Hasta"],
                "%Y-%m-%d %H:%M:%S"
            )

            if hoy < bloqueo_hasta:
                return True, bloqueo_hasta

    return False, None


def cantidad_prestamos_activos(usuario):
    prestamos = cargar_prestamos()

    activos = prestamos[
        (prestamos["Usuario"] == usuario) &
        (prestamos["Estado"].isin(["Activo", "No devuelto"]))
    ]

    return len(activos)


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        session["usuario"] = request.form["usuario"]
        session["correo"] = request.form["correo"]

        return redirect(url_for("inicio"))

    return render_template("login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


@app.route("/")
def inicio():

    if "usuario" not in session:
        return redirect(url_for("login"))

    return render_template(
        "index.html",
        usuario=session["usuario"]
    )


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

    recursos = cargar_recursos()

    recursos_filtrados = recursos[
        recursos["Categoria"] == categoria
    ]

    return render_template(
        "catalogo.html",
        recursos=recursos_filtrados.to_dict(orient="records"),
        categoria=categoria
    )


@app.route("/solicitar/<id_recurso>", methods=["GET", "POST"])
def solicitar(id_recurso):

    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()

    recursos = cargar_recursos()

    recurso = recursos[
        recursos["ID"] == id_recurso
    ]

    if recurso.empty:
        return "Recurso no encontrado"

    recurso = recurso.iloc[0]

    usuario = session["usuario"]
    categoria = recurso["Categoria"]

    bloqueado, bloqueo_hasta = usuario_bloqueado_categoria(
        usuario,
        categoria
    )

    if bloqueado:
        return f"""
        <h2 style='font-family: Arial; color: red;'>
            Estás bloqueado para solicitar recursos de la categoría {categoria}.
        </h2>
        <p style='font-family: Arial;'>
            Podrás volver a solicitar hasta: {bloqueo_hasta}
        </p>
        <a href='/catalogo'>Volver al catálogo</a>
        """

    if cantidad_prestamos_activos(usuario) >= 3:
        return """
        <h2 style='font-family: Arial; color: red;'>
            Has alcanzado el máximo de 3 préstamos activos.
        </h2>
        <a href='/catalogo'>Volver al catálogo</a>
        """

    if request.method == "POST":

        cantidad = int(request.form["cantidad"])
        unidad = request.form["unidad"]

        if unidad == "horas":

            if cantidad < 1 or cantidad > 48:
                return "El máximo permitido es de 48 horas."

            duracion = timedelta(hours=cantidad)

        elif unidad == "dias":

            if cantidad < 1 or cantidad > 2:
                return "El máximo permitido es de 2 días."

            duracion = timedelta(days=cantidad)

        else:
            return "Unidad inválida."

        if recurso["Estado"] == "Prestado":
            return "Este recurso ya está prestado."

        fecha_inicio = datetime.now()
        fecha_fin = fecha_inicio + duracion

        prestamos = cargar_prestamos()

        nuevo = pd.DataFrame([{
            "Usuario": usuario,
            "ID_Recurso": recurso["ID"],
            "Nombre_Recurso": recurso["Nombre"],
            "Categoria": recurso["Categoria"],
            "Fecha_Inicio": fecha_inicio.strftime("%Y-%m-%d %H:%M:%S"),
            "Fecha_Fin": fecha_fin.strftime("%Y-%m-%d %H:%M:%S"),
            "Estado": "Activo",
            "Bloqueo_Hasta": ""
        }])

        prestamos = pd.concat(
            [prestamos, nuevo],
            ignore_index=True
        )

        guardar_prestamos(prestamos)

        recursos.loc[
            recursos["ID"] == id_recurso,
            "Estado"
        ] = "Prestado"

        guardar_recursos(recursos)

        return redirect(url_for("prestamos"))

    return render_template(
        "solicitar.html",
        recurso=recurso
    )


@app.route("/prestamos")
def prestamos():

    if "usuario" not in session:
        return redirect(url_for("login"))

    actualizar_retrasos()
    limpiar_prestamos_finalizados()

    prestamos = cargar_prestamos()

    return render_template(
        "prestamos.html",
        prestamos=prestamos.to_dict(orient="records")
    )


@app.route("/devolver/<id_recurso>")
def devolver(id_recurso):

    if "usuario" not in session:
        return redirect(url_for("login"))

    prestamos = cargar_prestamos()
    recursos = cargar_recursos()
    usuario = session["usuario"]

    for i, row in prestamos.iterrows():

        if (
            row["ID_Recurso"] == id_recurso
            and row["Usuario"] == usuario
            and row["Estado"] in ["Activo", "No devuelto"]
        ):

            if row["Estado"] == "No devuelto":
                prestamos.at[i, "Estado"] = "Devuelto tarde"
            else:
                prestamos.at[i, "Estado"] = "Devuelto"

            recursos.loc[
                recursos["ID"] == id_recurso,
                "Estado"
            ] = "Disponible"

            break

    guardar_prestamos(prestamos)
    guardar_recursos(recursos)

    return redirect(url_for("prestamos"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)