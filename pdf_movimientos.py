"""
pdf_movimientos.py
Genera el PDF de comprobante para ingresos, egresos y traslados de inventario.
Devuelve bytes listos para subir a Supabase Storage.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from datetime import date, datetime
import io

# ── Paleta ──────────────────────────────────────────────────────────────────
NEGRO      = colors.HexColor("#1a1a1a")
GRIS_TEXTO = colors.HexColor("#555555")
GRIS_CLARO = colors.HexColor("#f5f5f5")
BORDE      = colors.HexColor("#d0d0d0")
AZUL       = colors.HexColor("#1a6fb5")   # Bodega
VERDE      = colors.HexColor("#1a7a50")   # Almacén
BLANCO     = colors.white

PAGE_W, PAGE_H = A4

TITULOS = {
    "ingreso":  "INGRESO DE INVENTARIO",
    "egreso":   "EGRESO DE INVENTARIO",
    "traslado": "TRASLADO DE INVENTARIO",
}
SECCION_PRODUCTOS = {
    "ingreso":  "PRODUCTOS INGRESADOS",
    "egreso":   "PRODUCTOS RETIRADOS",
    "traslado": "PRODUCTOS TRASLADADOS",
}


def _estilo(nombre, **kw):
    base = dict(fontName="Helvetica", fontSize=10, textColor=NEGRO,
                leading=14, spaceAfter=0, spaceBefore=0)
    base.update(kw)
    return ParagraphStyle(nombre, **base)


def fmt_fecha(s):
    if not s: return "—"
    try:
        if isinstance(s, (date, datetime)):
            return s.strftime("%d/%m/%Y")
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(s)[:10]


def _ubi_label(u):
    u = (str(u or "bodega")).lower()
    return ("Bodega", "#1a6fb5") if u == "bodega" else ("Almacén", "#1a7a50")


def lbl(texto):
    return Paragraph(f'<font size="8" color="#888888">{texto.upper()}</font>',
                     _estilo("lbl", alignment=TA_LEFT))


def val(texto):
    return Paragraph(f'<font size="10" color="#1a1a1a"><b>{str(texto or "—")}</b></font>',
                     _estilo("val", alignment=TA_LEFT))


# ─────────────────────────────────────────────────────────────────────────────
def _generar_pdf_base(tipo: str, datos: dict, cab_rows: list) -> bytes:
    """
    Motor común de generación. cab_rows ya viene armado con las filas
    específicas de cada tipo de movimiento (listas de 4 elementos: lbl,val,lbl,val).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    story = []

    # ── 1. LOGO + TÍTULO/CONSECUTIVO ─────────────────────────────────────────
    titulo = TITULOS.get(tipo, "MOVIMIENTO DE INVENTARIO")
    logo_data = [
        [
            Paragraph('<font color="#aaaaaa"><i>[ Logo y datos de la empresa ]</i></font>',
                      _estilo("logo_hint", fontSize=9, textColor=colors.HexColor("#aaaaaa"),
                              alignment=TA_LEFT)),
            Table([
                [Paragraph(f'<font size="8" color="#888888">{titulo}</font>',
                           _estilo("tit_label", alignment=TA_RIGHT))],
                [Paragraph(f'<font size="24" color="#1a1a1a"><b>{datos.get("consecutivo","—")}</b></font>',
                           _estilo("consec", alignment=TA_RIGHT))],
            ], colWidths=[8*cm])
        ]
    ]
    logo_tbl = Table(logo_data, colWidths=[10*cm, 8*cm])
    logo_tbl.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0,0), (-1,-1), [BLANCO]),
        ("BOX",           (0,0), (-1,-1), 0.5, BORDE),
        ("TOPPADDING",    (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 18),
        ("LEFTPADDING",   (0,0), (0,-1), 14),
        ("RIGHTPADDING",  (1,0), (1,-1), 14),
    ]))
    story.append(logo_tbl)
    story.append(Spacer(1, 0.4*cm))

    # ── 2. CABECERA (filas específicas por tipo) ─────────────────────────────
    cab_tbl = Table(cab_rows, colWidths=[4*cm, 5*cm, 4.5*cm, 4.5*cm])
    cab_tbl.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("ROWBACKGROUNDS",(0,0), (-1,-1), [BLANCO, GRIS_CLARO]),
        ("BOX",           (0,0), (-1,-1), 0.5, BORDE),
        ("LINEBELOW",     (0,0), (-1,-2), 0.3, BORDE),
        ("LINEBEFORE",    (2,0), (2,-1), 0.3, BORDE),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
    ]))
    story.append(cab_tbl)
    story.append(Spacer(1, 0.4*cm))

    # ── 3. TABLA DE PRODUCTOS ────────────────────────────────────────────────
    seccion = SECCION_PRODUCTOS.get(tipo, "PRODUCTOS")
    story.append(Paragraph(
        f'<font size="8" color="#888888">{seccion}</font>',
        _estilo("sec_title", spaceBefore=4, spaceAfter=6)))

    items = datos.get("items", [])
    total_uds = sum(int(i.get("cantidad", 0) or 0) for i in items)

    if tipo == "traslado":
        thead = [
            Paragraph('<font size="8" color="#ffffff"><b>#</b></font>',        _estilo("th", alignment=TA_CENTER)),
            Paragraph('<font size="8" color="#ffffff"><b>CÓDIGO</b></font>',   _estilo("th", alignment=TA_LEFT)),
            Paragraph('<font size="8" color="#ffffff"><b>PRODUCTO</b></font>',  _estilo("th", alignment=TA_LEFT)),
            Paragraph('<font size="8" color="#ffffff"><b>CANT.</b></font>',    _estilo("th", alignment=TA_CENTER)),
            Paragraph('<font size="8" color="#ffffff"><b>DESDE</b></font>',    _estilo("th", alignment=TA_CENTER)),
            Paragraph('<font size="8" color="#ffffff"><b>HACIA</b></font>',    _estilo("th", alignment=TA_CENTER)),
        ]
        col_widths = [1*cm, 2.3*cm, 6.2*cm, 1.8*cm, 2.7*cm, 3*cm]
    else:
        col_label = "DESTINO" if tipo == "ingreso" else "DESDE"
        thead = [
            Paragraph('<font size="8" color="#ffffff"><b>#</b></font>',        _estilo("th", alignment=TA_CENTER)),
            Paragraph('<font size="8" color="#ffffff"><b>CÓDIGO</b></font>',   _estilo("th", alignment=TA_LEFT)),
            Paragraph('<font size="8" color="#ffffff"><b>PRODUCTO</b></font>',  _estilo("th", alignment=TA_LEFT)),
            Paragraph('<font size="8" color="#ffffff"><b>CANT.</b></font>',    _estilo("th", alignment=TA_CENTER)),
            Paragraph(f'<font size="8" color="#ffffff"><b>{col_label}</b></font>',  _estilo("th", alignment=TA_CENTER)),
        ]
        col_widths = [1*cm, 3*cm, 8.5*cm, 2*cm, 3.5*cm]

    tabla_data = [thead]

    for n, item in enumerate(items, 1):
        codigo   = str(item.get("codigo") or "")
        nombre   = str(item.get("nombre") or "")
        cantidad = str(item.get("cantidad") or 0)

        fila_num = Paragraph(str(n), _estilo("td_num", alignment=TA_CENTER,
                                              textColor=GRIS_TEXTO, fontSize=9))
        fila_cod = Paragraph(codigo, _estilo("td_cod", fontSize=9,
                                              textColor=GRIS_TEXTO,
                                              fontName="Helvetica-Oblique"))
        fila_nom = Paragraph(nombre, _estilo("td_nom", fontSize=9))
        fila_cant = Paragraph(cantidad, _estilo("td_cant", alignment=TA_CENTER,
                                                 fontSize=10, fontName="Helvetica-Bold"))

        if tipo == "traslado":
            desde_label, desde_color = _ubi_label(item.get("origen"))
            hacia_label, hacia_color = _ubi_label(item.get("destino"))
            fila_desde = Paragraph(f'<font color="{desde_color}"><b>{desde_label}</b></font>',
                                    _estilo("td_desde", alignment=TA_CENTER, fontSize=9))
            fila_hacia = Paragraph(f'<font color="{hacia_color}"><b>{hacia_label}</b></font>',
                                    _estilo("td_hacia", alignment=TA_CENTER, fontSize=9))
            tabla_data.append([fila_num, fila_cod, fila_nom, fila_cant, fila_desde, fila_hacia])
        else:
            ubi_campo = item.get("destino") if tipo == "ingreso" else item.get("origen")
            ubi_label, ubi_color = _ubi_label(ubi_campo)
            fila_ubi = Paragraph(f'<font color="{ubi_color}"><b>{ubi_label}</b></font>',
                                  _estilo("td_ubi", alignment=TA_CENTER, fontSize=9))
            tabla_data.append([fila_num, fila_cod, fila_nom, fila_cant, fila_ubi])

    # Fila total — el label va en la columna PRODUCTO (índice 2), el valor en CANT. (índice 3)
    n_cols = len(thead)
    fila_total = [Paragraph("", _estilo("x")) for _ in range(n_cols)]
    fila_total[2] = Paragraph('<font size="9" color="#888888"><b>TOTAL UNIDADES</b></font>',
                               _estilo("tot_lbl", alignment=TA_RIGHT))
    fila_total[3] = Paragraph(f'<b>{str(total_uds)}</b>', _estilo("tot_val", alignment=TA_CENTER,
                               fontSize=11, fontName="Helvetica-Bold"))
    tabla_data.append(fila_total)

    prod_tbl = Table(tabla_data, colWidths=col_widths)
    n_rows = len(tabla_data)
    prod_tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0,0), (-1,0), NEGRO),
        ("ROWBACKGROUNDS", (0,1), (-1,n_rows-2), [BLANCO, GRIS_CLARO]),
        ("BACKGROUND",     (0,n_rows-1), (-1,n_rows-1), GRIS_CLARO),
        ("LINEABOVE",      (0,n_rows-1), (-1,n_rows-1), 0.8, BORDE),
        ("BOX",            (0,0), (-1,-1), 0.5, BORDE),
        ("INNERGRID",      (0,0), (-1,-1), 0.3, BORDE),
        ("TOPPADDING",     (0,0), (-1,-1), 7),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 7),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(prod_tbl)

    # ── 4. COMENTARIO ────────────────────────────────────────────────────────
    if datos.get("comentario"):
        story.append(Spacer(1, 0.35*cm))
        com_data = [[
            Paragraph('<font size="8" color="#888888">COMENTARIO</font><br/>'
                      f'<font size="9" color="#555555"><i>{datos["comentario"]}</i></font>',
                      _estilo("com", leading=15))
        ]]
        com_tbl = Table(com_data, colWidths=[18*cm])
        com_tbl.setStyle(TableStyle([
            ("BOX",           (0,0), (-1,-1), 0.5, BORDE),
            ("TOPPADDING",    (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
            ("LEFTPADDING",   (0,0), (-1,-1), 12),
            ("RIGHTPADDING",  (0,0), (-1,-1), 12),
            ("BACKGROUND",    (0,0), (-1,-1), GRIS_CLARO),
        ]))
        story.append(com_tbl)

    # ── 5. PIE ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5*cm))
    pie_data = [[
        Paragraph('<font size="8" color="#aaaaaa">Generado por sistema de inventario</font>',
                  _estilo("pie_l", alignment=TA_LEFT)),
        Paragraph(f'<font size="8" color="#aaaaaa">{datos.get("consecutivo","—")} · {datos.get("fecha_registro","")}</font>',
                  _estilo("pie_r", alignment=TA_RIGHT)),
    ]]
    pie_tbl = Table(pie_data, colWidths=[9*cm, 9*cm])
    pie_tbl.setStyle(TableStyle([
        ("VALIGN",   (0,0), (-1,-1), "MIDDLE"),
        ("LINEABOVE",(0,0), (-1,0), 0.4, BORDE),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(pie_tbl)

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
def generar_pdf_ingreso(datos: dict) -> bytes:
    """
    datos = {
        consecutivo, proveedor, numero_factura,
        fecha_documento, fecha_recepcion, documento_soporte,
        comentario, realizado_por, fecha_registro,
        items: [{codigo, nombre, cantidad, destino}]   # destino: 'bodega'|'almacen'
    }
    """
    cab_rows = [
        [lbl("Proveedor"), val(datos.get("proveedor") or "—"),
         lbl("N° Factura / Remisión"), val(datos.get("numero_factura") or "—")],
        [lbl("Fecha documento"), val(fmt_fecha(datos.get("fecha_documento"))),
         lbl("Fecha recepción"), val(fmt_fecha(datos.get("fecha_recepcion")))],
        [lbl("Registrado por"), val(datos.get("realizado_por") or "—"),
         lbl("Fecha y hora"), val(datos.get("fecha_registro") or "—")],
    ]
    if datos.get("documento_soporte"):
        cab_rows.append([
            lbl("Doc. soporte"), val(datos["documento_soporte"]),
            Paragraph("", _estilo("x")), Paragraph("", _estilo("x"))
        ])
    return _generar_pdf_base("ingreso", datos, cab_rows)


def generar_pdf_egreso(datos: dict) -> bytes:
    """
    datos = {
        consecutivo, motivo_egreso, documento_soporte, cliente,
        comentario, realizado_por, fecha_registro,
        items: [{codigo, nombre, cantidad, origen}]   # origen: 'bodega'|'almacen'
    }
    """
    origen_principal = "—"
    items = datos.get("items", [])
    if items:
        vistos = set(str(i.get("origen") or "bodega").lower() for i in items)
        if len(vistos) == 1:
            origen_principal, _ = _ubi_label(next(iter(vistos)))
        else:
            origen_principal = "Mixto (ver detalle)"

    cab_rows = [
        [lbl("Motivo"), val(datos.get("motivo_egreso") or "—"),
         lbl("Cliente / Destinatario"), val(datos.get("cliente") or "—")],
        [lbl("Sale de"), val(origen_principal),
         lbl("Doc. soporte"), val(datos.get("documento_soporte") or "—")],
        [lbl("Registrado por"), val(datos.get("realizado_por") or "—"),
         lbl("Fecha y hora"), val(datos.get("fecha_registro") or "—")],
    ]
    return _generar_pdf_base("egreso", datos, cab_rows)


def generar_pdf_traslado(datos: dict) -> bytes:
    """
    datos = {
        consecutivo, documento_soporte,
        comentario, realizado_por, fecha_registro,
        items: [{codigo, nombre, cantidad, origen, destino}]
    }
    """
    cab_rows = [
        [lbl("Doc. soporte"), val(datos.get("documento_soporte") or "—"),
         lbl(""), val("")],
        [lbl("Registrado por"), val(datos.get("realizado_por") or "—"),
         lbl("Fecha y hora"), val(datos.get("fecha_registro") or "—")],
    ]
    return _generar_pdf_base("traslado", datos, cab_rows)
