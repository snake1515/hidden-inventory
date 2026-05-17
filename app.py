from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

DB_NAME = "inventario.db"
CSV_NAME = "hidden-inventory.csv"


def init_db():

    if os.path.exists(DB_NAME):
        return

    print("Importando CSV...")

    conn = sqlite3.connect(DB_NAME)

    df = pd.read_csv(
        CSV_NAME,
        sep=';',
        encoding='latin1',
        low_memory=False
    )

    # D = nombre
    # G = grupo real
    # I = existencias bodega
    # J = existencias almacen

    df = df.iloc[:, [3, 6, 8, 9]]

    df.columns = [
        'nombre',
        'grupo',
        'existencias_bodega',
        'existencias_almacen'
    ]

    # Código automático
    df.insert(0, 'codigo', range(1, len(df) + 1))

    # Nueva columna
    df['ultima_modificacion'] = ''

    # Limpiar datos
    df = df.fillna('')

    df['nombre'] = df['nombre'].astype(str)
    df['grupo'] = df['grupo'].astype(str)

    df['grupo'] = df['grupo'].replace(
        ['undefined', 'nan', 'None'],
        ''
    )

    # Guardar SQLite
    df.to_sql(
        'inventario',
        conn,
        index=False,
        if_exists='replace'
    )

    conn.close()

    print("Base creada correctamente.")


@app.route('/')
def index():

    return render_template('index.html')


@app.route('/buscar')
def buscar():

    texto = request.args.get('q', '').lower().strip()

    conn = sqlite3.connect(DB_NAME)

    query = f"""
    SELECT rowid, *
    FROM inventario
    WHERE lower(nombre) LIKE '%{texto}%'
    ORDER BY nombre ASC
    LIMIT 100
    """

    df = pd.read_sql(query, conn)

    conn.close()

    return jsonify(
        df.to_dict(orient='records')
    )


@app.route('/actualizar', methods=['POST'])
def actualizar():

    data = request.json

    rowid = data['rowid']
    nueva_existencia = data['existencias_bodega']

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_NAME)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE inventario
        SET existencias_bodega = ?,
            ultima_modificacion = ?
        WHERE rowid = ?
    """, (
        nueva_existencia,
        fecha,
        rowid
    ))

    conn.commit()

    conn.close()

    return jsonify({
        'success': True,
        'fecha': fecha
    })


@app.route('/descargar')
def descargar():

    conn = sqlite3.connect(DB_NAME)

    df = pd.read_sql("""
        SELECT
            codigo,
            nombre,
            grupo,
            existencias_bodega,
            existencias_almacen,
            ultima_modificacion
        FROM inventario
    """, conn)

    conn.close()

    archivo = "inventario_editado.xlsx"

    df.to_excel(
        archivo,
        index=False
    )

    return send_file(
        archivo,
        as_attachment=True
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)