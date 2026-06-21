from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import pandas as pd
import os
import io
from datetime import datetime
from sqlalchemy import create_engine, text
import bcrypt
import httpx
from pdf_ingreso import generar_pdf_ingreso

app = Flask(__name__)
app.secret_key = "clave_secreta_inventario_2026"

ADMIN_USER = "jk2m_admin"
ADMIN_PASS = "Chicharron123"

DATABASE_URL  = os.environ.get("DATABASE_URL")
SUPABASE_URL  = os.environ.get("SUPABASE_URL")   # ej: https://xxxx.supabase.co
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY")   # service_role key
STORAGE_BUCKET = "movimientos-pdfs"

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

def usuario_puede_ver_movimientos():
    if session.get('admin'):
        return True
    return session.get('puede_ver_movimientos', False)

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

def movimientos_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin') and not session.get('usuario_id'):
            return redirect(url_for('login'))
        if not usuario_puede_ver_movimientos():
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

# ─── Supabase Storage helpers ───
def _storage_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

def subir_pdf_supabase(file_bytes: bytes, filename: str) -> str | None:
    """Sube un PDF al bucket y devuelve el path almacenado, o None si falla."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    path = f"{datetime.now().strftime('%Y/%m')}/{filename}"
    url  = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    headers = {**_storage_headers(), "Content-Type": "application/pdf"}
    r = httpx.put(url, content=file_bytes, headers=headers, timeout=30)
    if r.status_code in (200, 201):
        return path
    return None

def obtener_pdf_supabase(path: str) -> bytes | None:
    """Descarga un PDF del bucket y devuelve los bytes, o None si falla."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    r = httpx.get(url, headers=_storage_headers(), timeout=30)
    if r.status_code == 200:
        return r.content
    return None

# ─────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('usuario_id') or session.get('admin'):
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        nombre   = request.form.get('usuario', '').strip()
        password = request.form.get('contrasena', '').strip()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, nombre, password, puede_editar_almacen, puede_editar_bodega, puede_ver_movimientos FROM usuarios WHERE nombre = :n AND activo = TRUE"),
                {"n": nombre}
            ).fetchone()
        if row:
            if bcrypt.checkpw(password.encode(), row.password.encode()):
                with engine.connect() as conn:
                    grupos_rows = conn.execute(
                        text("SELECT grupo FROM usuario_grupos WHERE usuario_id = :uid"),
                        {"uid": row.id}
                    ).fetchall()
                session['usuario_id']           = row.id
                session['usuario_nombre']        = row.nombre
                session['puede_editar_almacen']  = row.puede_editar_almacen
                session['puede_editar_bodega']   = row.puede_editar_bodega
                session['puede_ver_movimientos'] = row.puede_ver_movimientos
                session['grupos']                = [g.grupo for g in grupos_rows]
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
        puede_editar_bodega=usuario_puede_editar_bodega(),
        puede_ver_movimientos=usuario_puede_ver_movimientos(),
        es_admin=session.get('admin', False))

@app.route('/buscar')
@login_required
def buscar():
    texto  = request.args.get('q', '').lower().strip()
    grupos = get_grupos_usuario()
    q      = f"%{texto}%"
    palabras = texto.split()
    nombre_conditions = ' AND '.join([f"lower(nombre) LIKE :p{i}" for i in range(len(palabras))])
    nombre_params     = {f"p{i}": f"%{p}%" for i, p in enumerate(palabras)}
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
            df = pd.read_sql(text(f"{base_select} {where} ORDER BY nombre ASC LIMIT 200"), conn, params=params)
        else:
            if not grupos:
                return jsonify([])
            placeholders = ','.join([f"'{g}'" for g in grupos])
            df = pd.read_sql(text(f"{base_select} {where} AND grupo IN ({placeholders}) ORDER BY nombre ASC LIMIT 200"), conn, params=params)
    df['rowid'] = df['codigo']
    return jsonify(df.to_dict(orient='records'))

@app.route('/actualizar', methods=['POST'])
@login_required
def actualizar():
    if not usuario_puede_editar_bodega():
        return jsonify({'success': False, 'error': 'Sin permiso para editar bodega'}), 403
    data    = request.json
    usuario = get_current_user()
    fecha   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    data    = request.json
    usuario = get_current_user()
    fecha   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    data    = request.json
    usuario = get_current_user()
    fecha   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    data    = request.json
    usuario = get_current_user()
    fecha   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                        existencias_almacen, existencias_bodega,
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
# MOVIMIENTOS
# ─────────────────────────────────────────
@app.route('/movimientos')
@movimientos_required
def movimientos():
    return render_template('movimientos.html',
        usuario=get_current_user(),
        es_admin=session.get('admin', False))

@app.route('/movimientos/lista')
@movimientos_required
def movimientos_lista():
    tipo        = request.args.get('tipo', '')
    fecha_desde = request.args.get('desde', '')
    fecha_hasta = request.args.get('hasta', '')
    usuario_f   = request.args.get('usuario', '')

    conditions = ["1=1"]
    params     = {}
    if tipo:
        conditions.append("m.tipo = :tipo")
        params['tipo'] = tipo
    if fecha_desde:
        conditions.append("m.fecha >= :desde")
        params['desde'] = fecha_desde + ' 00:00:00'
    if fecha_hasta:
        conditions.append("m.fecha <= :hasta")
        params['hasta'] = fecha_hasta + ' 23:59:59'
    if usuario_f:
        conditions.append("lower(m.realizado_por) LIKE :usuario")
        params['usuario'] = f"%{usuario_f.lower()}%"

    where = ' AND '.join(conditions)
    sql = text(f"""
        SELECT m.id, m.tipo, m.consecutivo, m.documento, m.comentario,
               m.pdf_path, m.pdf_generado, m.proveedor, m.numero_factura,
               m.motivo_egreso, m.realizado_por, m.fecha,
               COUNT(mi.id) as num_items,
               SUM(mi.cantidad) as total_unidades
        FROM movimientos m
        LEFT JOIN movimiento_items mi ON mi.movimiento_id = m.id
        WHERE {where}
        GROUP BY m.id
        ORDER BY m.fecha DESC
        LIMIT 300
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        d['fecha'] = str(d['fecha'])
        d['tiene_pdf']     = bool(d.get('pdf_path'))
        d['tiene_pdf_gen'] = bool(d.get('pdf_generado'))
        d.pop('pdf_path',     None)
        d.pop('pdf_generado', None)
        result.append(d)
    return jsonify(result)

@app.route('/movimientos/detalle/<int:mov_id>')
@movimientos_required
def movimiento_detalle(mov_id):
    with engine.connect() as conn:
        mov = conn.execute(text("""
            SELECT id, tipo, consecutivo, documento, comentario,
                   pdf_path, pdf_generado,
                   proveedor, numero_factura, fecha_documento, fecha_recepcion,
                   motivo_egreso, realizado_por, fecha
            FROM movimientos WHERE id = :id
        """), {"id": mov_id}).fetchone()
        if not mov:
            return jsonify({'error': 'No encontrado'}), 404
        items = conn.execute(text("""
            SELECT producto_codigo, producto_nombre, cantidad,
                   ubicacion_origen, ubicacion_destino
            FROM movimiento_items WHERE movimiento_id = :id
            ORDER BY id
        """), {"id": mov_id}).fetchall()
    mov_d = dict(mov._mapping)
    mov_d['fecha'] = str(mov_d['fecha'])
    mov_d['tiene_pdf']     = bool(mov_d.get('pdf_path'))
    mov_d['tiene_pdf_gen'] = bool(mov_d.get('pdf_generado'))
    mov_d.pop('pdf_path', None)
    mov_d.pop('pdf_generado', None)
    if mov_d.get('fecha_documento'):
        mov_d['fecha_documento'] = str(mov_d['fecha_documento'])
    if mov_d.get('fecha_recepcion'):
        mov_d['fecha_recepcion'] = str(mov_d['fecha_recepcion'])
    mov_d['items'] = [dict(i._mapping) for i in items]
    return jsonify(mov_d)

def _siguiente_consecutivo(conn, tipo: str) -> str:
    """Obtiene y actualiza el consecutivo para el tipo dado. Debe llamarse dentro de una transacción."""
    prefijos = {'ingreso': 'ING', 'egreso': 'EGR', 'traslado': 'TRL'}
    prefijo  = prefijos.get(tipo, 'MOV')
    result = conn.execute(text("""
        UPDATE movimientos_consecutivos SET ultimo = ultimo + 1
        WHERE tipo = :tipo RETURNING ultimo
    """), {"tipo": tipo})
    row = result.fetchone()
    numero = row.ultimo if row else 1
    return f"{prefijo}-{numero:04d}"


@app.route('/movimientos/crear', methods=['POST'])
@movimientos_required
def movimientos_crear():
    data    = request.json
    usuario = get_current_user()
    tipo    = data.get('tipo', '').strip()
    if tipo not in ('ingreso', 'egreso', 'traslado'):
        return jsonify({'success': False, 'error': 'Tipo inválido'}), 400
    items = data.get('items', [])
    if not items:
        return jsonify({'success': False, 'error': 'Sin productos'}), 400

    ahora     = datetime.now()
    fecha_str = ahora.strftime("%Y-%m-%d %H:%M:%S")
    fecha_pdf = ahora.strftime("%d/%m/%Y %I:%M %p")

    try:
        with engine.connect() as conn:
            # Consecutivo
            consecutivo = _siguiente_consecutivo(conn, tipo)

            # Insertar cabecera
            row = conn.execute(text("""
                INSERT INTO movimientos
                    (tipo, consecutivo, documento, comentario, pdf_path,
                     proveedor, numero_factura, fecha_documento, fecha_recepcion,
                     motivo_egreso, realizado_por, fecha)
                VALUES
                    (:tipo, :consec, :doc, :com, :pdf,
                     :prov, :nfac, :fdoc, :frec,
                     :motivo, :usuario, NOW())
                RETURNING id
            """), {
                "tipo":   tipo,
                "consec": consecutivo,
                "doc":    data.get('documento', '').strip() or None,
                "com":    data.get('comentario', '').strip() or None,
                "pdf":    data.get('pdf_path') or None,
                "prov":   data.get('proveedor', '').strip() or None,
                "nfac":   data.get('numero_factura', '').strip() or None,
                "fdoc":   data.get('fecha_documento') or None,
                "frec":   data.get('fecha_recepcion') or None,
                "motivo": data.get('motivo_egreso', '').strip() or None,
                "usuario": usuario
            })
            mov_id = row.fetchone().id

            # Insertar items y ajustar existencias
            for item in items:
                codigo   = str(item['codigo']).strip()
                nombre   = str(item['nombre']).strip()
                cantidad = int(item['cantidad'])
                origen   = item.get('origen')
                destino  = item.get('destino')

                conn.execute(text("""
                    INSERT INTO movimiento_items
                        (movimiento_id, producto_codigo, producto_nombre, cantidad,
                         ubicacion_origen, ubicacion_destino)
                    VALUES (:mid, :cod, :nom, :cant, :orig, :dest)
                """), {
                    "mid": mov_id, "cod": codigo, "nom": nombre,
                    "cant": cantidad, "orig": origen, "dest": destino
                })

                if tipo == 'ingreso':
                    col = 'existencias_bodega' if destino == 'bodega' else 'existencias_almacen'
                    conn.execute(text(f"""
                        UPDATE inventario SET {col} = {col} + :c,
                            ultima_mod_cantidad = :f, modificado_por = :u
                        WHERE codigo = :cod
                    """), {"c": cantidad, "f": fecha_str, "u": usuario, "cod": codigo})

                elif tipo == 'egreso':
                    col = 'existencias_bodega' if origen == 'bodega' else 'existencias_almacen'
                    conn.execute(text(f"""
                        UPDATE inventario SET {col} = GREATEST({col} - :c, 0),
                            ultima_mod_cantidad = :f, modificado_por = :u
                        WHERE codigo = :cod
                    """), {"c": cantidad, "f": fecha_str, "u": usuario, "cod": codigo})

                elif tipo == 'traslado':
                    col_out = 'existencias_bodega' if origen == 'bodega' else 'existencias_almacen'
                    col_in  = 'existencias_bodega' if destino == 'bodega' else 'existencias_almacen'
                    if col_out != col_in:
                        conn.execute(text(f"""
                            UPDATE inventario
                            SET {col_out} = GREATEST({col_out} - :c, 0),
                                {col_in}  = {col_in} + :c,
                                ultima_mod_cantidad = :f, modificado_por = :u
                            WHERE codigo = :cod
                        """), {"c": cantidad, "f": fecha_str, "u": usuario, "cod": codigo})

            # ── Generar PDF para ingresos ──────────────────────────────────
            pdf_generado_path = None
            if tipo == 'ingreso':
                try:
                    items_pdf = [
                        {
                            "codigo":   str(i.get("codigo", "")),
                            "nombre":   str(i.get("nombre", "")),
                            "cantidad": int(i.get("cantidad", 0)),
                            "destino":  str(i.get("destino") or "bodega"),
                        }
                        for i in items
                    ]
                    pdf_bytes = generar_pdf_ingreso({
                        "consecutivo":     consecutivo,
                        "proveedor":       data.get('proveedor', ''),
                        "numero_factura":  data.get('numero_factura', ''),
                        "fecha_documento": data.get('fecha_documento'),
                        "fecha_recepcion": data.get('fecha_recepcion'),
                        "documento_soporte": data.get('documento', ''),
                        "comentario":      data.get('comentario', ''),
                        "realizado_por":   usuario,
                        "fecha_registro":  fecha_pdf,
                        "items":           items_pdf,
                    })
                    filename = f"{consecutivo}.pdf"
                    pdf_generado_path = subir_pdf_supabase(pdf_bytes, filename)
                    if pdf_generado_path:
                        conn.execute(text("""
                            UPDATE movimientos SET pdf_generado = :p WHERE id = :id
                        """), {"p": pdf_generado_path, "id": mov_id})
                except Exception as pdf_err:
                    import traceback
                    print(f"[PDF] Error generando PDF: {pdf_err}")
                    print(traceback.format_exc())

            conn.commit()

        return jsonify({
            'success':      True,
            'id':           mov_id,
            'consecutivo':  consecutivo,
            'tiene_pdf_gen': bool(pdf_generado_path)
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/movimientos/upload_pdf', methods=['POST'])
@movimientos_required
def movimientos_upload_pdf():
    if 'pdf' not in request.files:
        return jsonify({'success': False, 'error': 'Sin archivo'}), 400
    f = request.files['pdf']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'error': 'Solo PDF'}), 400
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{ts}_{f.filename}"
    path     = subir_pdf_supabase(f.read(), filename)
    if path:
        return jsonify({'success': True, 'path': path})
    return jsonify({'success': False, 'error': 'Error subiendo PDF. Verifica SUPABASE_URL y SUPABASE_KEY.'}), 500

@app.route('/movimientos/pdf/<int:mov_id>')
@movimientos_required
def movimientos_pdf(mov_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT pdf_path FROM movimientos WHERE id = :id"), {"id": mov_id}
        ).fetchone()
    if not row or not row.pdf_path:
        return "Sin PDF adjunto", 404
    data = obtener_pdf_supabase(row.pdf_path)
    if not data:
        return "Error descargando PDF", 500
    import io
    return send_file(io.BytesIO(data), mimetype='application/pdf',
                     download_name=f"soporte_mov_{mov_id}.pdf")

@app.route('/movimientos/pdf_generado/<int:mov_id>')
@movimientos_required
def movimientos_pdf_generado(mov_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT pdf_generado, consecutivo FROM movimientos WHERE id = :id"), {"id": mov_id}
        ).fetchone()
    if not row or not row.pdf_generado:
        return "Sin PDF generado", 404
    data = obtener_pdf_supabase(row.pdf_generado)
    if not data:
        return "Error descargando PDF", 500
    nombre = f"{row.consecutivo or 'ingreso'}.pdf"
    return send_file(io.BytesIO(data), mimetype='application/pdf', download_name=nombre)


@app.route('/movimientos/eliminar/<int:mov_id>', methods=['POST'])
@movimientos_required
def movimientos_eliminar(mov_id):
    """Elimina un movimiento (solo admin). Si el movimiento afectó existencias,
    revierte el ajuste antes de borrar el registro."""
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Solo el administrador puede eliminar movimientos'}), 403

    fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    usuario   = get_current_user()

    try:
        with engine.connect() as conn:
            mov = conn.execute(
                text("SELECT id, tipo FROM movimientos WHERE id = :id"), {"id": mov_id}
            ).fetchone()
            if not mov:
                return jsonify({'success': False, 'error': 'Movimiento no encontrado'}), 404

            tipo  = mov.tipo
            items = conn.execute(text("""
                SELECT producto_codigo, cantidad, ubicacion_origen, ubicacion_destino
                FROM movimiento_items WHERE movimiento_id = :id
            """), {"id": mov_id}).fetchall()

            # Revertir existencias (lógica inversa exacta a movimientos_crear)
            for item in items:
                codigo   = item.producto_codigo
                cantidad = item.cantidad
                origen   = item.ubicacion_origen
                destino  = item.ubicacion_destino

                if tipo == 'ingreso' and destino:
                    col = 'existencias_bodega' if destino == 'bodega' else 'existencias_almacen'
                    conn.execute(text(f"""
                        UPDATE inventario SET {col} = GREATEST({col} - :c, 0),
                            ultima_mod_cantidad = :f, modificado_por = :u
                        WHERE codigo = :cod
                    """), {"c": cantidad, "f": fecha_str, "u": usuario, "cod": codigo})

                elif tipo == 'egreso' and origen:
                    col = 'existencias_bodega' if origen == 'bodega' else 'existencias_almacen'
                    conn.execute(text(f"""
                        UPDATE inventario SET {col} = {col} + :c,
                            ultima_mod_cantidad = :f, modificado_por = :u
                        WHERE codigo = :cod
                    """), {"c": cantidad, "f": fecha_str, "u": usuario, "cod": codigo})

                elif tipo == 'traslado' and origen and destino:
                    col_out = 'existencias_bodega' if origen == 'bodega' else 'existencias_almacen'
                    col_in  = 'existencias_bodega' if destino == 'bodega' else 'existencias_almacen'
                    if col_out != col_in:
                        conn.execute(text(f"""
                            UPDATE inventario
                            SET {col_out} = {col_out} + :c,
                                {col_in}  = GREATEST({col_in} - :c, 0),
                                ultima_mod_cantidad = :f, modificado_por = :u
                            WHERE codigo = :cod
                        """), {"c": cantidad, "f": fecha_str, "u": usuario, "cod": codigo})

            conn.execute(text("DELETE FROM movimiento_items WHERE movimiento_id = :id"), {"id": mov_id})
            conn.execute(text("DELETE FROM movimientos WHERE id = :id"), {"id": mov_id})
            conn.commit()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/movimientos/buscar_productos')
@movimientos_required
def movimientos_buscar_productos():
    """Mismo buscador multi-palabra que el inventario principal."""
    texto  = request.args.get('q', '').lower().strip()
    if not texto:
        return jsonify([])
    q        = f"%{texto}%"
    palabras = texto.split()
    nombre_conditions = ' AND '.join([f"lower(nombre) LIKE :p{i}" for i in range(len(palabras))])
    nombre_params     = {f"p{i}": f"%{p}%" for i, p in enumerate(palabras)}
    params = {"q": q, **nombre_params}
    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT codigo, nombre, referencia, marca, grupo,
                   existencias_bodega, existencias_almacen
            FROM inventario
            WHERE (
                ({nombre_conditions})
                OR lower(codigo::text) LIKE :q
                OR lower(coalesce(referencia,'')) LIKE :q
                OR lower(coalesce(marca,'')) LIKE :q
            )
            ORDER BY nombre ASC LIMIT 50
        """), conn, params=params)
    return jsonify(df.to_dict(orient='records'))

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
            SELECT u.id, u.nombre, u.puede_editar_almacen, u.puede_editar_bodega,
                   u.activo, u.puede_ver_movimientos,
                   STRING_AGG(ug.grupo, ', ' ORDER BY ug.grupo) as grupos
            FROM usuarios u
            LEFT JOIN usuario_grupos ug ON u.id = ug.usuario_id
            GROUP BY u.id, u.nombre, u.puede_editar_almacen, u.puede_editar_bodega,
                     u.activo, u.puede_ver_movimientos
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
    data   = request.json
    hashed = bcrypt.hashpw(data['password'].strip().encode(), bcrypt.gensalt()).decode()
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO usuarios (nombre, password, puede_editar_almacen, puede_editar_bodega,
                                      puede_ver_movimientos, activo)
                VALUES (:n, :p, :a, :b, :mov, TRUE) RETURNING id
            """), {"n": data['nombre'].strip(), "p": hashed,
                   "a": data.get('puede_editar_almacen', False),
                   "b": data.get('puede_editar_bodega', False),
                   "mov": data.get('puede_ver_movimientos', False)})
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
                UPDATE usuarios SET puede_editar_almacen=:a, puede_editar_bodega=:b,
                    puede_ver_movimientos=:mov, activo=:activo WHERE id=:id
            """), {"a": data.get('puede_editar_almacen', False),
                   "b": data.get('puede_editar_bodega', False),
                   "mov": data.get('puede_ver_movimientos', False),
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
            result = conn.execute(text("DELETE FROM inventario"))
            conn.commit()
        return jsonify({'success': True, 'eliminados': result.rowcount})
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
    data  = request.json
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
    texto   = request.args.get('q', '').lower().strip()
    palabras = texto.split()
    q        = f"%{texto}%"
    nombre_conditions = ' AND '.join([f"lower(nombre) LIKE :p{i}" for i in range(len(palabras))])
    nombre_params     = {f"p{i}": f"%{p}%" for i, p in enumerate(palabras)}
    params = {"q": q, **nombre_params}
    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT codigo, nombre, referencia, marca, grupo,
                existencias_almacen, existencias_bodega,
                ultima_mod_cantidad, modificado_por
            FROM inventario
            WHERE (
                ({nombre_conditions})
                OR lower(codigo::text) LIKE :q
                OR lower(coalesce(referencia,'')) LIKE :q
                OR lower(coalesce(marca,'')) LIKE :q
            )
            ORDER BY nombre ASC LIMIT 100
        """), conn, params=params)
    return jsonify(df.to_dict(orient='records'))

@app.route('/admin/actualizar_nombre', methods=['POST'])
def actualizar_nombre():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    data  = request.json
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
                    grupo  = str(row.get('grupo', '')).strip()
                    if not codigo or not nombre or not grupo:
                        omitidos += 1; continue
                    referencia = str(row.get('referencia', '') or '').strip()
                    marca      = str(row.get('marca', '') or '').strip()
                    for val in ('nan', 'none'):
                        if referencia.lower() == val: referencia = ''
                        if marca.lower() == val:      marca = ''
                    def parse_int(v):
                        try:
                            s = str(v).strip()
                            if not s or s.lower() in ('nan','none',''): return 0
                            return int(float(s))
                        except: return 0
                    bodega  = parse_int(row.get('existencias_bodega', 0))
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
                except Exception:
                    omitidos += 1; continue
            conn.commit()
        return jsonify({'success': True, 'insertados': insertados, 'omitidos': omitidos})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/carga_csv_referencias_lote', methods=['POST'])
def carga_csv_referencias_lote():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
    try:
        filas  = request.json.get('filas', [])
        fecha  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        actualizados = omitidos = 0
        with engine.connect() as conn:
            for row in filas:
                codigo  = str(row.get('codigo', '')).strip()
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)






















































































































































































































































































































































































































































































































































































































































































































































































































































































































