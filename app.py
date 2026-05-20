from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import pandas as pd
import os
from datetime import datetime
from sqlalchemy import create_engine, text
import bcrypt
 
app = Flask(__name__)
app.secret_key = "clave_secreta_inventario_2026"
 
ADMIN_USER = "jk2m_admin"
ADMIN_PASS = "Chicharron123"
 
DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(
    DATABASE_URL,
    connect_args={"connect_timeout": 10},
    pool_pre_ping=True
)
 
# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
 
def get_current_user():
    if session.get('admin'):
        return ADMIN_USER
    return session.get('usuario_nombre', 'desconocido')
 
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
 
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin') and not session.get('usuario_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
 
# ─────────────────────────────────────────
# LOGIN
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
                session['usuario_id'] = row.id
                session['usuario_nombre'] = row.nombre
                session['puede_editar_almacen'] = row.puede_editar_almacen
                session['puede_editar_bodega'] = row.puede_editar_bodega
                session['grupos'] = [g.grupo for g in grupos_rows]
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
# INVENTARIO PRINCIPAL
# ─────────────────────────────────────────
 
@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           usuario=get_current_user(),
                           puede_editar_almacen=usuario_puede_editar_almacen(),
                           puede_editar_bodega=usuario_puede_editar_bodega())
 
@app.route('/buscar')
@login_required
def buscar():
    texto = request.args.get('q', '').lower().strip()
    grupos = get_grupos_usuario()
    q = f"%{texto}%"
 
    # Palabras separadas para búsqueda en nombre
    palabras = texto.split()
    nombre_conditions = ' AND '.join([f"lower(nombre) LIKE :p{i}" for i in range(len(palabras))])
    nombre_params = {f"p{i}": f"%{p}%" for i, p in enumerate(palabras)}
 
    base_select = """SELECT codigo, nombre, referencia, marca, grupo,
                            existencias_bodega, existencias_almacen,
                            ultima_mod_cantidad, ultima_mod_nombre, modificado_por
                     FROM inventario"""
 
    where = f"""WHERE (
        ({nombre_conditions})
        OR lower(codigo::text) LIKE :q
        OR lower(coalesce(referencia,'')) LIKE :q
        OR lower(coalesce(marca,'')) LIKE :q
    )"""
 
    params = {"q": q, **nombre_params}
 
    with engine.connect() as conn:
        if grupos is None:
            df = pd.read_sql(text(f"{base_select} {where} ORDER BY nombre ASC LIMIT 200"),
                             conn, params=params)
        else:
            if not grupos:
                return jsonify([])
            placeholders = ','.join([f"'{g}'" for g in grupos])
            df = pd.read_sql(text(f"{base_select} {where} AND grupo IN ({placeholders}) ORDER BY nombre ASC LIMIT 200"),
                             conn, params=params)
    df['rowid'] = df['codigo']
    return jsonify(df.to_dict(orient='records'))
 
@app.route('/actualizar', methods=['POST'])
@login_required
def actualizar():
    if not usuario_puede_editar_bodega():
        return jsonify({'success': False, 'error': 'Sin permiso para editar bodega'}), 403
    data = request.json
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario SET existencias_bodega = :e, ultima_mod_cantidad = :f, modificado_por = :u
                WHERE codigo = :c
            """), {"e": data['existencias_bodega'], "f": fecha, "u": usuario, "c": data['rowid']})
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
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario SET existencias_almacen = :e, ultima_mod_cantidad = :f, modificado_por = :u
                WHERE codigo = :c
            """), {"e": data['existencias_almacen'], "f": fecha, "u": usuario, "c": data['rowid']})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha, 'usuario': usuario})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/actualizar_referencia', methods=['POST'])
@login_required
def actualizar_referencia():
    data = request.json
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario SET referencia = :r, ultima_mod_cantidad = :f, modificado_por = :u
                WHERE codigo = :c
            """), {"r": data['referencia'].strip(), "f": fecha, "u": usuario, "c": data['rowid']})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha, 'usuario': usuario})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/actualizar_marca', methods=['POST'])
@login_required
def actualizar_marca():
    data = request.json
    usuario = get_current_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario SET marca = :m, ultima_mod_cantidad = :f, modificado_por = :u
                WHERE codigo = :c
            """), {"m": data['marca'].strip(), "f": fecha, "u": usuario, "c": data['rowid']})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha, 'usuario': usuario})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/descargar')
@login_required
def descargar():
    grupos = get_grupos_usuario()
    solo_existencias = request.args.get('solo_existencias') == '1'
 
    base_select = """SELECT codigo, nombre, referencia, marca, grupo,
                            existencias_almacen,
                            existencias_bodega,
                            ultima_mod_cantidad, ultima_mod_nombre, modificado_por
                     FROM inventario"""
 
    with engine.connect() as conn:
        if grupos is None:
            df = pd.read_sql(text(f"{base_select} ORDER BY nombre"), conn)
        else:
            if not grupos:
                df = pd.DataFrame()
            else:
                placeholders = ','.join([f"'{g}'" for g in grupos])
                df = pd.read_sql(text(f"{base_select} WHERE grupo IN ({placeholders}) ORDER BY nombre"), conn)
 
    if solo_existencias and not df.empty:
        df = df[(df['existencias_almacen'] > 0) | (df['existencias_bodega'] > 0)]
 
    nombre_archivo = "inventario_con_existencias.xlsx" if solo_existencias else "inventario_completo.xlsx"
    archivo = f"/tmp/{nombre_archivo}"
    df.to_excel(archivo, index=False)
    return send_file(archivo, as_attachment=True, download_name=nombre_archivo)
 
# ─────────────────────────────────────────
# ADMIN LOGIN / PANEL
# ─────────────────────────────────────────
 
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin'):
        return redirect(url_for('admin_panel'))
    error = None
    if request.method == 'POST':
        if request.form.get('usuario') == ADMIN_USER and request.form.get('contrasena') == ADMIN_PASS:
            session['admin'] = True
            session['usuario_nombre'] = ADMIN_USER
            return redirect(url_for('admin_panel'))
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
    return render_template('admin.html', grupos_disponibles=grupos_disponibles, usuarios=usuarios)
 
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
    hashed = bcrypt.hashpw(data['password'].strip().encode(), bcrypt.gensalt()).decode()
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO usuarios (nombre, password, puede_editar_almacen, puede_editar_bodega, activo)
                VALUES (:n, :p, :a, :b, TRUE) RETURNING id
            """), {"n": data['nombre'].strip(), "p": hashed,
                   "a": data.get('puede_editar_almacen', False), "b": data.get('puede_editar_bodega', False)})
            uid = result.fetchone().id
            for g in data.get('grupos', []):
                conn.execute(text("INSERT INTO usuario_grupos (usuario_id, grupo) VALUES (:uid, :g)"), {"uid": uid, "g": g})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/editar_usuario', methods=['POST'])
def editar_usuario():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE usuarios SET puede_editar_almacen=:a, puede_editar_bodega=:b, activo=:activo WHERE id=:id
            """), {"a": data.get('puede_editar_almacen', False), "b": data.get('puede_editar_bodega', False),
                   "activo": data.get('activo', True), "id": data['id']})
            conn.execute(text("DELETE FROM usuario_grupos WHERE usuario_id=:uid"), {"uid": data['id']})
            for g in data.get('grupos', []):
                conn.execute(text("INSERT INTO usuario_grupos (usuario_id, grupo) VALUES (:uid, :g)"), {"uid": data['id'], "g": g})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/eliminar_usuario', methods=['POST'])
def eliminar_usuario():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM usuarios WHERE id=:id"), {"id": request.json['id']})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
# ─────────────────────────────────────────
# ADMIN — INVENTARIO
# ─────────────────────────────────────────
 
@app.route('/admin/purgar_inventario', methods=['POST'])
def purgar_inventario():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    try:
        with engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE inventario RESTART IDENTITY"))
            conn.commit()
        return jsonify({'success': True, 'eliminados': 'todos'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/agregar_item', methods=['POST'])
def agregar_item():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO inventario (codigo, nombre, referencia, marca, grupo,
                                        existencias_bodega, existencias_almacen,
                                        ultima_mod_cantidad, ultima_mod_nombre, modificado_por)
                VALUES (:codigo, :nombre, :referencia, :marca, :grupo, :bodega, :almacen, :fecha, :admin, :admin)
            """), {
                "codigo": data['codigo'].strip(), "nombre": data['nombre'].strip(),
                "referencia": data.get('referencia', '').strip(), "marca": data.get('marca', '').strip(),
                "grupo": data['grupo'].strip(), "bodega": data.get('existencias_bodega', 0),
                "almacen": data.get('existencias_almacen', 0),
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "admin": ADMIN_USER
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
                UPDATE inventario SET codigo=:cn, nombre=:nombre, referencia=:ref, marca=:marca,
                    grupo=:grupo, existencias_bodega=:bodega, existencias_almacen=:almacen,
                    ultima_mod_cantidad=:fecha, ultima_mod_nombre=:fecha, modificado_por=:usuario
                WHERE codigo=:co
            """), {
                "cn": data['codigo'].strip(), "nombre": data['nombre'].strip(),
                "ref": data.get('referencia', '').strip(), "marca": data.get('marca', '').strip(),
                "grupo": data['grupo'].strip(), "bodega": data.get('existencias_bodega', 0),
                "almacen": data.get('existencias_almacen', 0),
                "fecha": fecha, "usuario": ADMIN_USER, "co": data['codigo_original'].strip()
            })
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/eliminar_item', methods=['POST'])
def eliminar_item():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM inventario WHERE codigo=:c"), {"c": request.json['codigo']})
            conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/buscar_items')
def admin_buscar_items():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    texto = request.args.get('q', '').lower().strip()
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT codigo, nombre, referencia, marca, grupo,
                   existencias_bodega, existencias_almacen,
                   ultima_mod_cantidad, modificado_por
            FROM inventario
            WHERE lower(nombre) LIKE :q OR lower(codigo::text) LIKE :q
               OR lower(coalesce(referencia,'')) LIKE :q OR lower(coalesce(marca,'')) LIKE :q
            ORDER BY nombre ASC LIMIT 100
        """), conn, params={"q": f"%{texto}%"})
    return jsonify(df.to_dict(orient='records'))
 
# ─────────────────────────────────────────
# ADMIN — CSV LOTES
# ─────────────────────────────────────────
 
@app.route('/admin/carga_csv_lote', methods=['POST'])
def carga_csv_lote():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    try:
        filas = request.json.get('filas', [])
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        insertados = omitidos = 0
        with engine.connect() as conn:
            for row in filas:
                try:
                    codigo = str(row.get('codigo', '')).strip()
                    nombre = str(row.get('nombre', '')).strip()
                    grupo = str(row.get('grupo', '')).strip()
                    if not codigo or not nombre or not grupo:
                        omitidos += 1
                        continue
                    referencia = str(row.get('referencia', '') or '').strip()
                    marca = str(row.get('marca', '') or '').strip()
                    for val in ('nan', 'none'):
                        if referencia.lower() == val: referencia = ''
                        if marca.lower() == val: marca = ''
                    def parse_int(v):
                        try:
                            s = str(v).strip()
                            if not s or s.lower() in ('nan','none',''): return 0
                            return int(float(s))
                        except: return 0
                    bodega = parse_int(row.get('existencias_bodega', 0))
                    almacen = parse_int(row.get('existencias_almacen', 0))
                    result = conn.execute(text("""
                        INSERT INTO inventario (codigo, nombre, referencia, marca, grupo,
                                                existencias_bodega, existencias_almacen,
                                                ultima_mod_cantidad, ultima_mod_nombre, modificado_por)
                        VALUES (:codigo, :nombre, :ref, :marca, :grupo, :bodega, :almacen, :fecha, :admin, :admin)
                        ON CONFLICT (codigo) DO NOTHING
                    """), {"codigo": codigo, "nombre": nombre, "ref": referencia, "marca": marca,
                           "grupo": grupo, "bodega": bodega, "almacen": almacen,
                           "fecha": fecha, "admin": ADMIN_USER})
                    if result.rowcount > 0: insertados += 1
                    else: omitidos += 1
                except Exception as row_err:
                    omitidos += 1
                    continue
            conn.commit()
        return jsonify({'success': True, 'insertados': insertados, 'omitidos': omitidos})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/carga_csv_referencias_lote', methods=['POST'])
def carga_csv_referencias_lote():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    try:
        filas = request.json.get('filas', [])
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        actualizados = omitidos = 0
        with engine.connect() as conn:
            for row in filas:
                codigo = str(row.get('codigo', '')).strip()
                ref_raw = str(row.get('referencia', '')).strip()
                if not codigo or not ref_raw or ref_raw.lower() in ('nan', '0', 'none', ''):
                    omitidos += 1; continue
                result = conn.execute(text("""
                    UPDATE inventario SET referencia=:ref, modificado_por=:u, ultima_mod_cantidad=:f
                    WHERE codigo=:c
                """), {"ref": ref_raw, "u": ADMIN_USER, "f": fecha, "c": codigo})
                if result.rowcount > 0: actualizados += 1
                else: omitidos += 1
            conn.commit()
        return jsonify({'success': True, 'actualizados': actualizados, 'omitidos': omitidos})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
@app.route('/admin/actualizar_nombre', methods=['POST'])
def actualizar_nombre():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data = request.json
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE inventario SET nombre=:n, ultima_mod_nombre=:f, modificado_por=:u WHERE codigo=:c
            """), {"n": data['nombre'].strip(), "f": fecha, "u": ADMIN_USER, "c": data['rowid']})
            conn.commit()
        return jsonify({'success': True, 'fecha': fecha})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
 
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
