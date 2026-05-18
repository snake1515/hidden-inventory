from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = "clave_secreta_inventario_2026"

ADMIN_USER = "hanzo_hasashi"
ADMIN_PASS = "Chicharron123"

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# ── RUTAS PÚBLICAS ──

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/buscar')
def buscar():
    texto = request.args.get('q', '').lower().strip()
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT codigo, nombre, grupo, existencias_bodega, existencias_almacen, ultima_mod_cantidad, ultima_mod_nombre FROM inventario WHERE lower(nombre) LIKE :q ORDER BY nombre ASC LIMIT 100"),
            conn,
            params={"q": f"%{texto}%"}
        )
    # Usamos codigo como rowid para compatibilidad con el frontend
    df['rowid'] = df['codigo']
    return jsonify(df.to_dict(orient='records'))

@app.route('/actualizar', methods=['POST'])
def actualizar():
    data = request.json
    codigo = data['rowid']
    nueva_existencia = data['existencias_bodega']
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario
                SET existencias_bodega = :existencias,
                    ultima_mod_cantidad = :fecha
                WHERE codigo = :codigo
            """), {"existencias": nueva_existencia, "fecha": fecha, "codigo": codigo})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/descargar')
def descargar():
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT codigo, nombre, grupo,
                   existencias_bodega, existencias_almacen,
                   ultima_mod_cantidad, ultima_mod_nombre
            FROM inventario
        """), conn)
    archivo = "/tmp/inventario_editado.xlsx"
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
    codigo = data['rowid']
    nuevo_nombre = data['nombre'].strip()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario
                SET nombre = :nombre,
                    ultima_mod_nombre = :fecha
                WHERE codigo = :codigo
            """), {"nombre": nuevo_nombre, "fecha": fecha, "codigo": codigo})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

