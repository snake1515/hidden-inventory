from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import create_engine, text
import bcrypt

app = Flask(__name__)
app.secret_key = "clave_secreta_inventario_2026"

ADMIN_USER = "hanzo_hasashi"
ADMIN_PASS = "Chicharron123"

DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DATABASE_URL)

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def get_current_user():
    if session.get('admin'):
        return ADMIN_USER
    if session.get('usuario_nombre'):
        return session['usuario_nombre']
    return 'desconocido'

def usuario_puede_editar_almacen():
    if session.get('admin'):
        return True
    return session.get('puede_editar_almacen', False)

def usuario_puede_editar_bodega():
    if session.get('admin'):
        return True
    return session.get('puede_editar_bodega', False)

def get_grupos_usuario():
    if session.get('admin'):
        return None
    return session.get('grupos', [])

# ─────────────────────────────────────────
# LOGIN USUARIOS NORMALES
# ─────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('usuario_id') or session.get('admin'):
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        nombre = request.form.get('usuario', '').strip()
        password = request.form.get('contrasena', '').strip()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, nombre, password, puede_editar_almacen, puede_editar_bodega FROM usuarios WHERE nombre = :n AND activo = TRUE"),
                {"n": nombre}
            ).fetchone()
        if row:
            if bcrypt.checkpw(password.encode(), row.password.encode()):
                with engine.connect() as conn:
                    grupos_rows = conn.execute(
                        text("SELECT grupo FROM usuario_grupos WHERE usuario_id = :uid"),
                        {"uid": row.id}
                    ).fetchall()
                grupos = [g.grupo for g in grupos_rows]
                session['usuario_id'] = row.id
                session['usuario_nombre'] = row.nombre
                session['puede_editar_almacen'] = row.puede_editar_almacen
                session['puede_editar_bodega'] = row.puede_editar_bodega
                session['grupos'] = grupos
                return redirect(url_for('index'))
            else:
                error = "Contraseña incorrecta."
        else:
            error = "Usuario no encontrado o inactivo."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────────────────────────────────────
# RUTAS PRINCIPALES
# ─────────────────────────────────────────

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin') and not session.get('usuario_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           usuario=get_current_user(),
                           puede_editar_almacen=usuario_puede_editar_almacen(),
                           puede_editar_bodega=usuario_puede_editar_bodega(),
                           grupos=get_grupos_usuario())

@app.route('/buscar')
@login_required
def buscar():
    texto = request.args.get('q', '').lower().strip()
    grupos = get_grupos_usuario()

    with engine.connect() as conn:
        if grupos is None:
            df = pd.read_sql(
                text("""SELECT codigo, nombre, referencia, grupo,
                               existencias_bodega, existencias_almacen,
                               ultima_mod_cantidad, ultima_mod_nombre, modificado_por
                        FROM inventario
                        WHERE lower(nombre) LIKE :q OR lower(codigo::text) LIKE :q
                           OR lower(coalesce(referencia,'')) LIKE :q
                        ORDER BY nombre ASC LIMIT 200"""),
                conn, params={"q": f"%{texto}%"}
            )
        else:
            if not grupos:
                return jsonify([])
            placeholders = ','.join([f"'{g}'" for g in grupos])
            df = pd.read_sql(
                text(f"""SELECT codigo, nombre, referencia, grupo,
                                existencias_bodega, existencias_almacen,
                                ultima_mod_cantidad, ultima_mod_nombre, modificado_por
                         FROM inventario
                         WHERE (lower(nombre) LIKE :q OR lower(codigo::text) LIKE :q
                            OR lower(coalesce(referencia,'')) LIKE :q)
                           AND grupo IN ({placeholders})
                         ORDER BY nombre ASC LIMIT 200"""),
                conn, params={"q": f"%{texto}%"}
            )
    df['rowid'] = df['codigo']
    return jsonify(df.to_dict(orient='records'))

@app.route('/actualizar', methods=['POST'])
@login_required
def actualizar():
    if not usuario_puede_editar_bodega():
        return jsonify({'success': False, 'error': 'Sin permiso para editar bodega'}), 403
    data = request.json
    codigo = data['rowid']
    nueva_existencia = data['existencias_bodega']
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario
                SET existencias_bodega = :existencias,
                    ultima_mod_cantidad = :fecha,
                    modificado_por = :usuario
                WHERE codigo = :codigo
            """), {"existencias": nueva_existencia, "fecha": fecha,
                   "usuario": usuario, "codigo": codigo})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha, 'usuario': usuario})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/actualizar_almacen', methods=['POST'])
@login_required
def actualizar_almacen():
    if not usuario_puede_editar_almacen():
        return jsonify({'success': False, 'error': 'Sin permiso para editar almacén'}), 403
    data = request.json
    codigo = data['rowid']
    nueva_existencia = data['existencias_almacen']
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario
                SET existencias_almacen = :existencias,
                    ultima_mod_cantidad = :fecha,
                    modificado_por = :usuario
                WHERE codigo = :codigo
            """), {"existencias": nueva_existencia, "fecha": fecha,
                   "usuario": usuario, "codigo": codigo})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha, 'usuario': usuario})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/actualizar_referencia', methods=['POST'])
@login_required
def actualizar_referencia():
    data = request.json
    codigo = data['rowid']
    nueva_ref = data['referencia'].strip()
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario
                SET referencia = :ref,
                    ultima_mod_cantidad = :fecha,
                    modificado_por = :usuario
                WHERE codigo = :codigo
            """), {"ref": nueva_ref, "fecha": fecha,
                   "usuario": usuario, "codigo": codigo})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha, 'usuario': usuario})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/descargar')
@login_required
def descargar():
    grupos = get_grupos_usuario()
    with engine.connect() as conn:
        if grupos is None:
            df = pd.read_sql(text("""
                SELECT codigo, nombre, referencia, grupo,
                       existencias_bodega AS existencias_almacen,
                       existencias_almacen AS existencias_bodega,
                       ultima_mod_cantidad, ultima_mod_nombre, modificado_por
                FROM inventario ORDER BY nombre
            """), conn)
        else:
            if not grupos:
                df = pd.DataFrame()
            else:
                placeholders = ','.join([f"'{g}'" for g in grupos])
                df = pd.read_sql(text(f"""
                    SELECT codigo, nombre, referencia, grupo,
                           existencias_bodega AS existencias_almacen,
                           existencias_almacen AS existencias_bodega,
                           ultima_mod_cantidad, ultima_mod_nombre, modificado_por
                    FROM inventario WHERE grupo IN ({placeholders}) ORDER BY nombre
                """), conn)
    archivo = "/tmp/inventario_editado.xlsx"
    df.to_excel(archivo, index=False)
    return send_file(archivo, as_attachment=True)

# ─────────────────────────────────────────
# ADMIN LOGIN / PANEL
# ─────────────────────────────────────────

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
            session['usuario_nombre'] = ADMIN_USER
            return redirect(url_for('admin_panel'))
        else:
            error = "Usuario o contraseña incorrectos."
    return render_template('admin_login.html', error=error)

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    with engine.connect() as conn:
        grupos_rows = conn.execute(text("SELECT DISTINCT grupo FROM inventario ORDER BY grupo")).fetchall()
        grupos_disponibles = [g.grupo for g in grupos_rows]
        usuarios_rows = conn.execute(text("""
            SELECT u.id, u.nombre, u.puede_editar_almacen, u.puede_editar_bodega, u.activo,
                   STRING_AGG(ug.grupo, ', ' ORDER BY ug.grupo) as grupos
            FROM usuarios u
            LEFT JOIN usuario_grupos ug ON u.id = ug.usuario_id
            GROUP BY u.id, u.nombre, u.puede_editar_almacen, u.puede_editar_bodega, u.activo
            ORDER BY u.nombre
        """)).fetchall()
        usuarios = [dict(row._mapping) for row in usuarios_rows]
    return render_template('admin.html',
                           grupos_disponibles=grupos_disponibles,
                           usuarios=usuarios)

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

# ─────────────────────────────────────────
# ADMIN — USUARIOS
# ─────────────────────────────────────────

@app.route('/admin/crear_usuario', methods=['POST'])
def crear_usuario():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    nombre = data['nombre'].strip()
    password = data['password'].strip()
    puede_almacen = data.get('puede_editar_almacen', False)
    puede_bodega = data.get('puede_editar_bodega', False)
    grupos = data.get('grupos', [])
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO usuarios (nombre, password, puede_editar_almacen, puede_editar_bodega, activo)
                VALUES (:n, :p, :a, :b, TRUE) RETURNING id
            """), {"n": nombre, "p": hashed, "a": puede_almacen, "b": puede_bodega})
            nuevo_id = result.fetchone().id
            for g in grupos:
                conn.execute(text("INSERT INTO usuario_grupos (usuario_id, grupo) VALUES (:uid, :g)"),
                             {"uid": nuevo_id, "g": g})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/editar_usuario', methods=['POST'])
def editar_usuario():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    uid = data['id']
    puede_almacen = data.get('puede_editar_almacen', False)
    puede_bodega = data.get('puede_editar_bodega', False)
    grupos = data.get('grupos', [])
    activo = data.get('activo', True)
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE usuarios SET puede_editar_almacen = :a, puede_editar_bodega = :b,
                activo = :activo WHERE id = :id
            """), {"a": puede_almacen, "b": puede_bodega, "activo": activo, "id": uid})
            conn.execute(text("DELETE FROM usuario_grupos WHERE usuario_id = :uid"), {"uid": uid})
            for g in grupos:
                conn.execute(text("INSERT INTO usuario_grupos (usuario_id, grupo) VALUES (:uid, :g)"),
                             {"uid": uid, "g": g})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/eliminar_usuario', methods=['POST'])
def eliminar_usuario():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    uid = request.json['id']
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM usuarios WHERE id = :id"), {"id": uid})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ─────────────────────────────────────────
# ADMIN — INVENTARIO
# ─────────────────────────────────────────

@app.route('/admin/agregar_item', methods=['POST'])
def agregar_item():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO inventario (codigo, nombre, referencia, grupo,
                                        existencias_bodega, existencias_almacen,
                                        ultima_mod_cantidad, ultima_mod_nombre, modificado_por)
                VALUES (:codigo, :nombre, :referencia, :grupo, :bodega, :almacen, :fecha, :admin, :admin)
            """), {
                "codigo": data['codigo'].strip(),
                "nombre": data['nombre'].strip(),
                "referencia": data.get('referencia', '').strip(),
                "grupo": data['grupo'].strip(),
                "bodega": data.get('existencias_bodega', 0),
                "almacen": data.get('existencias_almacen', 0),
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "admin": ADMIN_USER
            })
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/editar_item', methods=['POST'])
def editar_item():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario
                SET codigo = :codigo_nuevo, nombre = :nombre, referencia = :referencia,
                    grupo = :grupo, existencias_bodega = :bodega, existencias_almacen = :almacen,
                    ultima_mod_cantidad = :fecha, ultima_mod_nombre = :fecha, modificado_por = :usuario
                WHERE codigo = :codigo_original
            """), {
                "codigo_nuevo": data['codigo'].strip(),
                "nombre": data['nombre'].strip(),
                "referencia": data.get('referencia', '').strip(),
                "grupo": data['grupo'].strip(),
                "bodega": data.get('existencias_bodega', 0),
                "almacen": data.get('existencias_almacen', 0),
                "fecha": fecha,
                "usuario": ADMIN_USER,
                "codigo_original": data['codigo_original'].strip()
            })
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/eliminar_item', methods=['POST'])
def eliminar_item():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    codigo = request.json['codigo']
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM inventario WHERE codigo = :c"), {"c": codigo})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/carga_csv', methods=['POST'])
def carga_csv():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    if 'archivo' not in request.files:
        return jsonify({'success': False, 'error': 'No se envió archivo'}), 400
    archivo = request.files['archivo']
    try:
        df = pd.read_csv(archivo)
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        required = {'codigo', 'nombre', 'grupo'}
        if not required.issubset(set(df.columns)):
            return jsonify({'success': False,
                            'error': f'El CSV debe tener: codigo, nombre, grupo. Encontradas: {list(df.columns)}'}), 400
        df['existencias_bodega'] = pd.to_numeric(df.get('existencias_bodega', 0), errors='coerce').fillna(0).astype(int)
        df['existencias_almacen'] = pd.to_numeric(df.get('existencias_almacen', 0), errors='coerce').fillna(0).astype(int)
        df['referencia'] = df['referencia'].astype(str).str.strip() if 'referencia' in df.columns else ''
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        insertados = 0
        omitidos = 0
        with engine.connect() as conn:
            for _, row in df.iterrows():
                try:
                    conn.execute(text("""
                        INSERT INTO inventario (codigo, nombre, referencia, grupo,
                                                existencias_bodega, existencias_almacen,
                                                ultima_mod_cantidad, ultima_mod_nombre, modificado_por)
                        VALUES (:codigo, :nombre, :referencia, :grupo, :bodega, :almacen, :fecha, :admin, :admin)
                        ON CONFLICT (codigo) DO NOTHING
                    """), {
                        "codigo": str(row['codigo']).strip(),
                        "nombre": str(row['nombre']).strip(),
                        "referencia": str(row.get('referencia', '')).strip(),
                        "grupo": str(row['grupo']).strip(),
                        "bodega": int(row['existencias_bodega']),
                        "almacen": int(row['existencias_almacen']),
                        "fecha": fecha,
                        "admin": ADMIN_USER
                    })
                    insertados += 1
                except Exception:
                    omitidos += 1
            conn.commit()
        return jsonify({'success': True, 'insertados': insertados, 'omitidos': omitidos})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/carga_csv_referencias', methods=['POST'])
def carga_csv_referencias():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    if 'archivo' not in request.files:
        return jsonify({'success': False, 'error': 'No se envió archivo'}), 400
    archivo = request.files['archivo']
    try:
        # Intentar con coma, si falla con punto y coma
        try:
            df = pd.read_csv(archivo, sep=',', encoding='utf-8-sig')
            if len(df.columns) < 2:
                archivo.seek(0)
                df = pd.read_csv(archivo, sep=';', encoding='utf-8-sig')
        except Exception:
            archivo.seek(0)
            df = pd.read_csv(archivo, sep=';', encoding='utf-8-sig')

        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
        if 'codigo' not in df.columns or 'referencia' not in df.columns:
            return jsonify({'success': False,
                            'error': f'El CSV debe tener columnas: codigo, referencia. Encontradas: {list(df.columns)}'}), 400
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        actualizados = 0
        omitidos = 0
        with engine.connect() as conn:
            for _, row in df.iterrows():
                codigo = str(row['codigo']).strip()
                ref_raw = str(row['referencia']).strip() if pd.notna(row['referencia']) else ''
                # Ignorar vacíos, 'nan', '0', 'None'
                if not ref_raw or ref_raw.lower() in ('nan', '0', 'none', ''):
                    omitidos += 1
                    continue
                result = conn.execute(text("""
                    UPDATE inventario
                    SET referencia = :ref,
                        modificado_por = :usuario,
                        ultima_mod_cantidad = :fecha
                    WHERE codigo = :codigo
                """), {"ref": ref_raw, "usuario": ADMIN_USER,
                       "fecha": fecha, "codigo": codigo})
                if result.rowcount > 0:
                    actualizados += 1
                else:
                    omitidos += 1
            conn.commit()
        return jsonify({'success': True, 'actualizados': actualizados, 'omitidos': omitidos})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/buscar_items')
def admin_buscar_items():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    texto = request.args.get('q', '').lower().strip()
    with engine.connect() as conn:
        df = pd.read_sql(
            text("""SELECT codigo, nombre, referencia, grupo,
                           existencias_bodega, existencias_almacen,
                           ultima_mod_cantidad, modificado_por
                    FROM inventario
                    WHERE lower(nombre) LIKE :q OR lower(codigo::text) LIKE :q
                       OR lower(coalesce(referencia,'')) LIKE :q
                    ORDER BY nombre ASC LIMIT 100"""),
            conn, params={"q": f"%{texto}%"}
        )
    return jsonify(df.to_dict(orient='records'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
