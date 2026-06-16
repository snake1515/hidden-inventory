"""
pdf_ingreso.py
Genera el PDF de comprobante de ingreso de inventario.
Devuelve bytes listos para subir a Supabase Storage.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, HRFlowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
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

def _estilo(nombre, **kw):
    base = dict(fontName="Helvetica", fontSize=10, textColor=NEGRO,
                leading=14, spaceAfter=0, spaceBefore=0)
    base.update(kw)
    return ParagraphStyle(nombre, **base)

# ─────────────────────────────────────────────────────────────────────────────
def generar_pdf_ingreso(datos: dict) -> bytes:
    """
    datos = {
        consecutivo: "ING-0042",
        proveedor:   "Dist. Nacional S.A.",
        numero_factura: "FAC-2024-00871",
        fecha_documento: "2026-06-12",   # o None
        fecha_recepcion: "2026-06-14",   # o None
        documento_soporte: "FAC-001",    # doc soporte libre, puede ser None
        comentario: "...",               # puede ser None
        realizado_por: "jk2m_admin",
        fecha_registro: "2026-06-14 10:32",
        items: [
            {codigo, nombre, cantidad, destino}   # destino: 'bodega'|'almacen'
        ]
    }
    """
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )

    story = []

    # ── 1. ESPACIO LOGO (90pt ≈ 3.2cm) ──────────────────────────────────────
    logo_data = [
        [
            Paragraph('<font color="#aaaaaa"><i>[ Logo y datos de la empresa ]</i></font>',
                      _estilo("logo_hint", fontSize=9, textColor=colors.HexColor("#aaaaaa"),
                              alignment=TA_LEFT)),
            Paragraph(f'<font size="9" color="#888888">INGRESO DE INVENTARIO</font><br/>'
                      f'<font size="22" color="#1a1a1a"><b>{datos.get("consecutivo","—")}</b></font>',
                      _estilo("consec", alignment=TA_RIGHT))
        ]
    ]
    logo_tbl = Table(logo_data, colWidths=[10*cm, 8*cm])
    logo_tbl.setStyle(TableStyle([
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [BLANCO]),
        ("BOX",        (0,0), (-1,-1), 0.5, BORDE),
        ("TOPPADDING", (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 18),
        ("LEFTPADDING",   (0,0), (0,-1), 14),
        ("RIGHTPADDING",  (1,0), (1,-1), 14),
    ]))
    story.append(logo_tbl)
    story.append(Spacer(1, 0.4*cm))

    # ── 2. DATOS DE CABECERA ─────────────────────────────────────────────────
    def campo(label, valor):
        label_p = Paragraph(
            f'<font size="8" color="#888888">{label.upper()}</font>',
            _estilo("lbl", alignment=TA_LEFT))
        valor_p = Paragraph(
            f'<font size="10" color="#1a1a1a"><b>{valor or "—"}</b></font>',
            _estilo("val", alignment=TA_LEFT))
        return [label_p, valor_p]

    def fmt_fecha(s):
        if not s: return "—"
        try:
            from datetime import date, datetime
            if isinstance(s, (date, datetime)):
                return s.strftime("%d/%m/%Y")
            d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
            return d.strftime("%d/%m/%Y")
        except:
            return str(s)[:10]

    def lbl(texto):
        return Paragraph(f'<font size="8" color="#888888">{texto.upper()}</font>',
                         _estilo("lbl", alignment=TA_LEFT))
    def val(texto):
        return Paragraph(f'<font size="10" color="#1a1a1a"><b>{str(texto or "—")}</b></font>',
                         _estilo("val", alignment=TA_LEFT))

    cab_data = [
        [lbl("Proveedor"), val(datos.get("proveedor") or "—"),
         lbl("N° Factura / Remisión"), val(datos.get("numero_factura") or "—")],
        [lbl("Fecha documento"), val(fmt_fecha(datos.get("fecha_documento"))),
         lbl("Fecha recepción"), val(fmt_fecha(datos.get("fecha_recepcion")))],
        [lbl("Registrado por"), val(datos.get("realizado_por") or "—"),
         lbl("Fecha y hora"), val(datos.get("fecha_registro") or "—")],
    ]
    if datos.get("documento_soporte"):
        cab_data.append([
            lbl("Doc. soporte"), val(datos["documento_soporte"]),
            Paragraph("", _estilo("x")), Paragraph("", _estilo("x"))
        ])

    cab_tbl = Table(cab_data, colWidths=[4*cm, 5*cm, 4.5*cm, 4.5*cm])
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
    story.append(Paragraph(
        '<font size="8" color="#888888">PRODUCTOS INGRESADOS</font>',
        _estilo("sec_title", spaceBefore=4, spaceAfter=6)))

    items = datos.get("items", [])
    total_uds = sum(i.get("cantidad", 0) for i in items)

    thead = [
        Paragraph('<font size="8" color="#ffffff"><b>#</b></font>',        _estilo("th", alignment=TA_CENTER)),
        Paragraph('<font size="8" color="#ffffff"><b>CÓDIGO</b></font>',   _estilo("th", alignment=TA_LEFT)),
        Paragraph('<font size="8" color="#ffffff"><b>PRODUCTO</b></font>',  _estilo("th", alignment=TA_LEFT)),
        Paragraph('<font size="8" color="#ffffff"><b>CANT.</b></font>',    _estilo("th", alignment=TA_CENTER)),
        Paragraph('<font size="8" color="#ffffff"><b>DESTINO</b></font>',  _estilo("th", alignment=TA_CENTER)),
    ]
    tabla_data = [thead]

    for n, item in enumerate(items, 1):
        dest = (str(item.get("destino") or "bodega")).lower()
        dest_color = "#1a6fb5" if dest == "bodega" else "#1a7a50"
        dest_label = "Bodega" if dest == "bodega" else "Almacén"
        codigo  = str(item.get("codigo") or "")
        nombre  = str(item.get("nombre") or "")
        cantidad = str(item.get("cantidad") or 0)
        tabla_data.append([
            Paragraph(str(n), _estilo("td_num", alignment=TA_CENTER,
                                       textColor=GRIS_TEXTO, fontSize=9)),
            Paragraph(codigo, _estilo("td_cod", fontSize=9,
                                      textColor=GRIS_TEXTO,
                                      fontName="Helvetica-Oblique")),
            Paragraph(nombre,  _estilo("td_nom", fontSize=9)),
            Paragraph(cantidad,
                      _estilo("td_cant", alignment=TA_CENTER, fontSize=10,
                               fontName="Helvetica-Bold")),
            Paragraph(f'<font color="{dest_color}"><b>{dest_label}</b></font>',
                      _estilo("td_dest", alignment=TA_CENTER, fontSize=9)),
        ])

    # Fila total
    tabla_data.append([
        Paragraph("", _estilo("x")),
        Paragraph("", _estilo("x")),
        Paragraph('<font size="9" color="#888888"><b>TOTAL UNIDADES</b></font>',
                  _estilo("tot_lbl", alignment=TA_RIGHT)),
        Paragraph(f'<b>{str(total_uds)}</b>', _estilo("tot_val", alignment=TA_CENTER,
                                                   fontSize=11, fontName="Helvetica-Bold")),
        Paragraph("", _estilo("x")),
    ])

    prod_tbl = Table(tabla_data, colWidths=[1*cm, 3*cm, 8.5*cm, 2*cm, 3.5*cm])
    n_rows = len(tabla_data)

    row_colors = []
    for i in range(1, n_rows - 1):
        bg = BLANCO if i % 2 == 1 else GRIS_CLARO
        row_colors.append(("ROWBACKGROUNDS", (0,i), (-1,i), [bg]))

    prod_tbl.setStyle(TableStyle([
        # Encabezado
        ("BACKGROUND",    (0,0), (-1,0), NEGRO),
        ("ROWBACKGROUNDS",(0,1), (-1,n_rows-2), [BLANCO, GRIS_CLARO]),
        # Fila total
        ("BACKGROUND",    (0,n_rows-1), (-1,n_rows-1), GRIS_CLARO),
        ("LINEABOVE",     (0,n_rows-1), (-1,n_rows-1), 0.8, BORDE),
        # Bordes generales
        ("BOX",           (0,0), (-1,-1), 0.5, BORDE),
        ("INNERGRID",     (0,0), (-1,-1), 0.3, BORDE),
        # Padding
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
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
        ("VALIGN",  (0,0), (-1,-1), "MIDDLE"),
        ("LINEABOVE",(0,0),(-1,0), 0.4, BORDE),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(pie_tbl)

    doc.build(story)
    return buf.getvalue()


