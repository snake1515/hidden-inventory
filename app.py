from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import pandas as pd
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "clave_secreta_inventario_2026"

DB_NAME = "inventario.db"
CSV_NAME = "hidden-inventory.csv"

ADMIN_USER = "hanzo_hasashi"
ADMIN_PASS = "Chicharron123"

def get_conn():
    return sqlite3.connect(DB_NAME, timeout=10)

def init_db():
    if os.path.exists(DB_NAME):
        return
    print("Importando CSV...")
    conn = get_conn()
    df = pd.read_csv(
        CSV_NAME,
        sep=';',
        encoding='latin1',
        low_memory=False
    )
    df = df.iloc[:, [3, 6, 8, 9]]
    df.columns = [
        'nombre',
        'grupo',
        'existencias_bodega',
        'existencias_almacen'
    ]
    df.insert(0, 'codigo', range(1, len(df) + 1))
    df['ultima_mod_cantidad'] = ''
    df['ultima_mod_nombre'] = ''
    df = df.fillna('')
    df['nombre'] = df['nombre'].astype(str)
    df['grupo'] = df['grupo'].astype(str)
    df['grupo'] = df['grupo'].replace(['undefined', 'nan', 'None'], '')
    df.to_sql('inventario', conn, index=False, if_exists='replace')
    conn.close()
    print("Base creada correctamente.")

# ── RUTAS PÚBLICAS ──

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/buscar')
def buscar():
    texto = request.args.get('q', '').lower().strip()
    conn = get_conn()
    query = """
    SELECT rowid, *
    FROM inventario
    WHERE lower(nombre) LIKE ?
    ORDER BY nombre ASC
    LIMIT 100
    """
    df = pd.read_sql(query, conn, params=(f'%{texto}%',))
    conn.close()
    return jsonify(df.to_dict(orient='records'))

@app.route('/actualizar', methods=['POST'])
def actualizar():
    data = request.json
    rowid = data['rowid']
    nueva_existencia = data['existencias_bodega']
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE inventario
            SET existencias_bodega = ?,
                ultima_mod_cantidad = ?
            WHERE rowid = ?
        """, (nueva_existencia, fecha, rowid))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'fecha': fecha})
    except sqlite3.OperationalError as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/descargar')
def descargar():
    conn = get_conn()
    df = pd.read_sql("""
        SELECT codigo, nombre, grupo,
               existencias_bodega, existencias_almacen,
               ultima_mod_cantidad, ultima_mod_nombre
        FROM inventario
    """, conn)
    conn.close()
    archivo = "inventario_editado.xlsx"
    df.to_excel(archivo, index=False)
    return send_file(archivo, as_attachment=True)

# ── RUTAS ADMIN ──

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin'):
        return redirect(url_for('admin_panel'))
    error = None
    if request.method == 'POST':
        usuario = request.form.get('usuario', '')
        contrasena = request.form.get('contrasena', '')
        if usuario == ADMIN_USER and contrasena == ADMIN_PASS:
            session['admin'] = True
            return redirect(url_for('admin_panel'))
        else:
            error = "Usuario o contraseña incorrectos."
    return render_template('admin_login.html', error=error)

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    return render_template('admin.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/actualizar_nombre', methods=['POST'])
def actualizar_nombre():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    rowid = data['rowid']
    nuevo_nombre = data['nombre'].strip()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE inventario
            SET nombre = ?,
                ultima_mod_nombre = ?
            WHERE rowid = ?
        """, (nuevo_nombre, fecha, rowid))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'fecha': fecha})
    except sqlite3.OperationalError as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

