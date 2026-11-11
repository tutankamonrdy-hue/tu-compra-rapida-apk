import flet as ft
import sqlite3
import os
import json
import hashlib
import shutil
import requests
import threading
import uuid
import re
import warnings
from bs4 import BeautifulSoup
from datetime import datetime
import time

# === CONFIGURACIÓN DE RUTAS ===
STORAGE_PATH = os.getenv("FLET_APP_STORAGE_DATA", ".")
DB_PATH = os.path.join(STORAGE_PATH, "inventario.db")

# === VARIABLES GLOBALES ===
tasa_del_dia = 887.30 
SECRETO = "TuCompraRapida2026"
DIAS_PRUEBA = 2
tasa_lock = threading.Lock()

warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# === TASA BCV AUTOMÁTICA ROBUSTA ===
def obtener_tasa_bcv(page, txt_tasa_ui):
    global tasa_del_dia
    
    def show_loading():
        txt_tasa_ui.value = "Tasa: Buscando..."
        page.update()
    try:
        page.run_thread(show_loading)
    except:
        show_loading()

    nueva_tasa = None
    
    try:
        print("Conectando al BCV...")
        url_bcv = "https://bcv.org.ve"
        respuesta = requests.get(url_bcv, verify=False, timeout=10)
        if respuesta.status_code == 200:
            soup = BeautifulSoup(respuesta.text, 'html.parser')
            contenedor_dolar = soup.find('div', id='dolar')
            if contenedor_dolar:
                precio_texto = contenedor_dolar.find('strong').get_text(strip=True)
                precio_limpio = re.sub(r'[^\d.]', '', precio_texto)
                if precio_limpio and '.' in precio_limpio:
                    nueva_tasa = float(precio_limpio)
                    print(f"Tasa obtenida vía BCV: {nueva_tasa}")
    except Exception as e:
        print(f"Fallo BCV (intentando Plan B): {e}")

    if nueva_tasa is None:
        try:
            print("Intentando Plan B (DolarAPI)...")
            url_api = "https://ve.dolarapi.com/v1/dolares/oficial"
            respuesta_api = requests.get(url_api, verify=False, timeout=10)
            if respuesta_api.status_code == 200:
                datos = respuesta_api.json()
                if "promedio" in datos and datos["promedio"] is not None:
                    nueva_tasa = float(datos["promedio"])
                    print(f"Tasa obtenida vía API Alternativa: {nueva_tasa}")
        except Exception as e:
            print(f"Fallo Plan B: {e}")

    if nueva_tasa is not None:
        with tasa_lock:
            tasa_del_dia = nueva_tasa
        
        def update_ui():
            txt_tasa_ui.value = f"Tasa: {nueva_tasa:.2f} Bs."
            page.update()
        
        try:
            page.run_thread(update_ui)
        except Exception:
            update_ui()
    else:
        def mostrar_error():
            txt_tasa_ui.value = f"Tasa: {tasa_del_dia:.2f} Bs."
            sb = ft.SnackBar(ft.Text("No se pudo actualizar la tasa. Verifica tu internet."), bgcolor=ft.Colors.ORANGE_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()
        
        try:
            page.run_thread(mostrar_error)
        except Exception:
            mostrar_error()

def actualizar_tasa_en_hilo(page, txt_tasa_ui):
    thread = threading.Thread(target=obtener_tasa_bcv, args=(page, txt_tasa_ui), daemon=True)
    thread.start()

# === SISTEMA DE LICENCIAS ===
async def verificar_licencia(page):
    hoy = datetime.now()
    prefs = None
    if hasattr(page, 'services') and page.services:
        for s in page.services:
            if isinstance(s, ft.SharedPreferences):
                prefs = s
                break
    
    if not prefs:
        prefs = ft.SharedPreferences()
        if hasattr(page, 'services'):
            page.services.append(prefs)

    licencia_str = await prefs.get("tcr_licencia")
    
    if not licencia_str:
        codigo_id = f"{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:4].upper()}-{uuid.uuid4().hex[:4].upper()}"
        fecha_inicio = hoy.strftime("%Y-%m-%d")
        datos = {"tipo": "prueba", "codigo_id": codigo_id, "fecha_inicio": fecha_inicio, "ultima_fecha_vista": fecha_inicio}
        await prefs.set("tcr_licencia", json.dumps(datos))
        return True, f"Prueba: {DIAS_PRUEBA} días", codigo_id
        
    try:
        datos = json.loads(licencia_str)
    except json.JSONDecodeError:
        return await verificar_licencia(page)

    codigo_id = datos.get("codigo_id", "ERROR")
        
    if datos.get("tipo") == "activa":
        return True, "✅ Licencia Activa", codigo_id
        
    try:
        ultima_fecha = datetime.strptime(datos.get("ultima_fecha_vista"), "%Y-%m-%d")
    except ValueError:
        return False, "❌ Error de formato de fecha", codigo_id
        
    datos["ultima_fecha_vista"] = hoy.strftime("%Y-%m-%d")
    await prefs.set("tcr_licencia", json.dumps(datos))
        
    try:
        fecha_inicio_dt = datetime.strptime(datos["fecha_inicio"], "%Y-%m-%d")
        dias = (hoy - fecha_inicio_dt).days
    except KeyError:
        dias = 0
    
    if dias >= DIAS_PRUEBA:
        return False, f"❌ Prueba Vencida ({dias} días)", codigo_id
        
    return True, f"⏳ Prueba: {DIAS_PRUEBA - dias} días restantes", codigo_id

async def mostrar_ventana_activacion(page, codigo_id):
    entry_codigo = ft.TextField(
        label="Código de Activación (8 caracteres)", 
        text_align=ft.TextAlign.CENTER, 
        autofocus=True,
        border_color=ft.Colors.BLUE_500,
        focused_border_color=ft.Colors.BLUE_700
    )
    
    prefs = ft.SharedPreferences()
    if prefs not in page.services:
        page.services.append(prefs)

    async def activar(e):
        codigo_ingresado = entry_codigo.value.strip().upper()
        if not codigo_ingresado:
            return

        codigo_id_limpio = codigo_id.replace("-", "")
        texto_a_encriptar = f"{codigo_id_limpio}-{SECRETO}"
        codigo_esperado = hashlib.sha256(texto_a_encriptar.encode()).hexdigest()[:8].upper()
        
        if codigo_ingresado == codigo_esperado:
            datos = {"tipo": "activa", "codigo_id": codigo_id, "fecha_inicio": datetime.now().strftime("%Y-%m-%d"), "ultima_fecha_vista": datetime.now().strftime("%Y-%m-%d")}
            await prefs.set("tcr_licencia", json.dumps(datos))
            
            dialogo.open = False
            page.update()
            
            page.controls.clear()
            try:
                await main(page)
            except Exception as ex:
                print(f"Error recargando main: {ex}")
            page.update()
        else:
            sb = ft.SnackBar(ft.Text("Código incorrecto ❌"), bgcolor=ft.Colors.RED_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()

    dialogo = ft.AlertDialog(
        title=ft.Text("🔒 Activación Requerida", text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
        content=ft.Column([
            ft.Text("Envíe este código a su proveedor:", text_align=ft.TextAlign.CENTER, size=12, color=ft.Colors.GREY_400),
            ft.Container(
                content=ft.Text(codigo_id, size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                bgcolor="#2b2b2b", padding=15, border_radius=8, alignment=ft.Alignment(0, 0),
                border=ft.Border.all(1, ft.Colors.GREY_600)
            ),
            entry_codigo,
            ft.Row([
                ft.Button("Activar", on_click=activar, bgcolor=ft.Colors.BLUE_700),
                ft.OutlinedButton("Cancelar", on_click=lambda e: (setattr(dialogo, 'open', False), page.update()))
            ], alignment=ft.MainAxisAlignment.END, spacing=10)
        ], spacing=20, width=320), 
        actions_alignment=ft.MainAxisAlignment.CENTER
    )
    
    page.overlay.append(dialogo)
    dialogo.open = True
    page.update()

# === BASE DE DATOS ===
def inicializar_bd(page):
    if not os.path.exists(DB_PATH):
        try:
            asset_db = page.get_asset_path("inventario.db")
            if asset_db and os.path.exists(asset_db):
                shutil.copy(asset_db, DB_PATH)
        except Exception as e:
            print(f"No se pudo copiar la BD: {e}")

    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, categoria TEXT NOT NULL, 
        costo_dolar REAL NOT NULL, estatus TEXT DEFAULT 'Activo', cantidad INTEGER DEFAULT 0)""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha_hora TIMESTAMP,
        total_usd REAL, total_bs REAL, productos_detalles TEXT, iva_usd REAL DEFAULT 0)""")
    conexion.commit()
    conexion.close()

# === FUNCIÓN PRINCIPAL ===
async def main(page: ft.Page):
    global tasa_del_dia
    page.title = "Tu Compra Rápida"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10 
    page.spacing = 10
    
    prefs = ft.SharedPreferences()
    if prefs not in page.services:
        page.services.append(prefs)
        
    clipboard = ft.Clipboard()
    if clipboard not in page.services:
        page.services.append(clipboard)
    
    inicializar_bd(page)
    
    licencia_ok, txt_licencia, codigo_id = await verificar_licencia(page)
    if not licencia_ok:
        await mostrar_ventana_activacion(page, codigo_id)
        return

    lista_carrito = []
    diccionario_badges = {}
    
    txt_licencia_ui = ft.Text(txt_licencia, color=ft.Colors.YELLOW_700, weight=ft.FontWeight.W_500, size=12)
    txt_tasa_ui = ft.Text(f"Tasa: {tasa_del_dia:.2f} Bs.", color=ft.Colors.CYAN_300, weight=ft.FontWeight.BOLD, size=14)
    
    def abrir_dialogo_tasa(e):
        entry_tasa = ft.TextField(label="Nueva Tasa BCV", value=str(tasa_del_dia), keyboard_type=ft.KeyboardType.NUMBER)
        
        def guardar_tasa(e):
            global tasa_del_dia
            try:
                tasa_del_dia = float(entry_tasa.value)
                txt_tasa_ui.value = f"Tasa: {tasa_del_dia:.2f} Bs."
                dialog.open = False
                page.update()
            except:
                pass
                
        dialog = ft.AlertDialog(
            title=ft.Text("Tasa Manual", weight=ft.FontWeight.BOLD),
            content=ft.Column([entry_tasa], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Guardar", on_click=guardar_tasa, bgcolor=ft.Colors.GREEN_700)
            ]
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    vista_carrito = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=8)
    txt_total_ui = ft.Text("Total: $0.00", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
    txt_total_bs_ui = ft.Text("0.00 Bs.", size=18, color=ft.Colors.GREEN_400)
    
    contenedor_busqueda = ft.Container(visible=False, expand=True)
    contenedor_carrito = ft.Container(visible=True, expand=True)
    
    def actualizar_badge(id_p):
        if str(id_p) in diccionario_badges:
            cont_badge, lbl_badge = diccionario_badges[str(id_p)]
            cant = 0
            for item in lista_carrito:
                if str(item["id"]) == str(id_p):
                    cant = item["cantidad"]
                    break
            if cant > 0:
                lbl_badge.value = str(int(cant)) if float(cant).is_integer() else str(cant)
                cont_badge.visible = True
            else:
                cont_badge.visible = False

    def cargar_productos_vista(filtro=""):
        vista_productos.controls.clear()
        diccionario_badges.clear()
        
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        if filtro:
            cursor.execute("SELECT id, nombre, costo_dolar FROM productos WHERE estatus='Activo' AND nombre LIKE ?", (f'%{filtro}%',))
        else:
            cursor.execute("SELECT id, nombre, costo_dolar FROM productos WHERE estatus='Activo'")
        
        for prod in cursor.fetchall():
            id_p, nombre, precio = prod
            
            cant_actual = 0
            for item in lista_carrito:
                if str(item["id"]) == str(id_p):
                    cant_actual = item["cantidad"]
                    break
            
            lbl_badge = ft.Text(str(int(cant_actual)) if cant_actual > 0 else "", color=ft.Colors.WHITE, size=12, weight=ft.FontWeight.BOLD)
            cont_badge = ft.Container(
                content=lbl_badge,
                bgcolor=ft.Colors.RED_700,
                width=24, height=24,
                border_radius=12,
                alignment=ft.Alignment(0, 0),
                right=5, top=-5, 
                visible=(cant_actual > 0)
            )
            
            btn = ft.Button(
                content=ft.Text(f"{nombre} - ${precio:.2f}", size=16),
                on_click=lambda e, i=id_p, n=nombre, p=precio: agregar_al_carrito(i, n, p, 1),
                style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=8)),
                height=55, width=400
            )
            
            stack = ft.Stack([btn, cont_badge], width=400, height=55)
            diccionario_badges[str(id_p)] = (cont_badge, lbl_badge)
            vista_productos.controls.append(stack)
            
        conexion.close()
        page.update()

    def cargar_productos_almacen():
        vista_almacen.controls.clear()
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        cursor.execute("SELECT id, nombre, costo_dolar FROM productos WHERE estatus='Activo' ORDER BY nombre ASC")
        
        for prod in cursor.fetchall():
            id_p, nombre, precio = prod
            vista_almacen.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(nombre, weight=ft.FontWeight.BOLD),
                            ft.Text(f"${precio:.2f}", size=14, color=ft.Colors.GREEN_400)
                        ], expand=True),
                        ft.Row([
                            ft.IconButton(ft.Icons.EDIT, icon_color=ft.Colors.BLUE_400, on_click=lambda e, i=id_p, n=nombre, p=precio: abrir_dialogo_producto(i, n, p)),
                            ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED_400, on_click=lambda e, i=id_p: eliminar_producto(i))
                        ])
                    ]),
                    padding=12, border=ft.Border.all(1, ft.Colors.GREY_700), border_radius=8, margin=ft.Margin.only(bottom=8)
                )
            )
        conexion.close()
        page.update()

    def cambiar_a_busqueda(e):
        contenedor_carrito.visible = False
        contenedor_busqueda.visible = True
        entry_buscador.focus()
        page.update()

    def cambiar_a_carrito(e):
        contenedor_busqueda.visible = False
        contenedor_carrito.visible = True
        page.update()

    def abrir_dialogo_monto_bs(e):
        entry_monto = ft.TextField(label="Monto en Bs", keyboard_type=ft.KeyboardType.NUMBER, text_align=ft.TextAlign.CENTER)
        
        def agregar_monto(e):
            try:
                monto_bs = float(entry_monto.value)
                if monto_bs > 0:
                    precio_usd = monto_bs / tasa_del_dia
                    id_unico = f"libre_{uuid.uuid4().hex[:6]}"
                    agregar_al_carrito(id_unico, f"Venta Libre ({monto_bs:.0f} Bs)", precio_usd, 1)
                    dialog.open = False
                    page.update()
            except:
                pass

        dialog = ft.AlertDialog(
            title=ft.Text("Monto de Venta (Bs)", weight=ft.FontWeight.BOLD),
            content=ft.Column([ft.Text("Ingresa el monto total en Bolívares:"), entry_monto], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Añadir al Carrito", on_click=agregar_monto, bgcolor=ft.Colors.GREEN_700)
            ]
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def agregar_al_carrito(id_p, nombre, precio, cantidad):
        for item in lista_carrito:
            if item["id"] == id_p:
                item["cantidad"] += cantidad
                actualizar_badge(id_p)
                actualizar_carrito()
                return
        lista_carrito.append({"id": id_p, "nombre": nombre, "precio": precio, "cantidad": cantidad})
        actualizar_badge(id_p)
        actualizar_carrito()

    def restar_unidad(id_p):
        for item in lista_carrito:
            if item["id"] == id_p:
                item["cantidad"] -= 1
                if item["cantidad"] <= 0.01:
                    lista_carrito.remove(item)
                break
        actualizar_badge(id_p)
        actualizar_carrito()

    def eliminar_del_carrito(id_p):
        for item in lista_carrito:
            if item["id"] == id_p:
                lista_carrito.remove(item)
                break
        actualizar_badge(id_p)
        actualizar_carrito()

    def actualizar_carrito():
        subtotal = sum(item["precio"] * item["cantidad"] for item in lista_carrito)
        txt_total_ui.value = f"Total: ${subtotal:.2f}"
        txt_total_bs_ui.value = f"{subtotal * tasa_del_dia:.2f} Bs."
        
        vista_carrito.controls.clear()
        if not lista_carrito:
            # CORRECCIÓN AQUÍ: Envolvemos el Text en un Container para usar padding
            vista_carrito.controls.append(
                ft.Container(
                    content=ft.Text("El carrito está vacío. Toca '+ Añadir Productos'", color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER),
                    padding=20
                )
            )
        else:
            for item in lista_carrito:
                cant_str = int(item['cantidad']) if float(item['cantidad']).is_integer() else item['cantidad']
                fila = ft.Row([
                    ft.Text(f"{cant_str}x {item['nombre']}", expand=True, size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"${item['precio'] * item['cantidad']:.2f}", size=14, color=ft.Colors.GREEN_400),
                    ft.IconButton(ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_color=ft.Colors.ORANGE_400, on_click=lambda e, i=item['id']: restar_unidad(i), icon_size=20),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400, on_click=lambda e, i=item['id']: eliminar_del_carrito(i), icon_size=20)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                vista_carrito.controls.append(fila)
                vista_carrito.controls.append(ft.Divider(height=1, color=ft.Colors.GREY_800))
        
        page.update()

    def vaciar_carrito(e):
        lista_carrito.clear()
        for id_p in diccionario_badges:
            actualizar_badge(id_p)
        actualizar_carrito()

    entry_buscador = ft.TextField(hint_text="🔍 Buscar producto...", on_change=lambda e: cargar_productos_vista(e.control.value), prefix_icon=ft.Icons.SEARCH, expand=True)
    vista_productos = ft.ListView(expand=True, spacing=12, padding=10)
    
    contenedor_busqueda.content = ft.Column([
        ft.Row([
            ft.IconButton(ft.Icons.ARROW_BACK, on_click=cambiar_a_carrito, icon_color=ft.Colors.WHITE),
            ft.Text("Añadir Productos", size=22, weight=ft.FontWeight.BOLD)
        ], alignment=ft.MainAxisAlignment.START, spacing=20),
        ft.Row([entry_buscador], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        vista_productos
    ], expand=True, spacing=15)

    async def cobrar_ticket(e):
        try:
            if not lista_carrito:
                sb = ft.SnackBar(ft.Text("El carrito está vacío"), bgcolor=ft.Colors.RED_700)
                page.overlay.append(sb)
                sb.open = True
                page.update()
                return
                
            ahora = datetime.now()
            texto = f"=========================\n🛒 *TU COMPRA RÁPIDA*\n=========================\n📅 _{ahora.strftime('%d/%m/%Y %I:%M %p')}_\nTasa BCV: {tasa_del_dia:.2f} Bs.\n\n *Detalle:* \n"
            
            subtotal = 0
            for item in lista_carrito:
                sub = item['precio'] * item['cantidad']
                cant_str = int(item['cantidad']) if float(item['cantidad']).is_integer() else item['cantidad']
                texto += f"• {cant_str}x {item['nombre']} - ${sub:.2f}\n"
                subtotal += sub
                
            total_bs = subtotal * tasa_del_dia
            texto += f"\n=========================\n *Total Ref:* ${subtotal:.2f}\n *Total a Pagar:* {total_bs:.2f} Bs.\n=========================\n¡Gracias por tu compra! 🙏✨"
            
            await clipboard.set(texto)
            
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            detalle_str = ", ".join([f"{int(i['cantidad']) if float(i['cantidad']).is_integer() else i['cantidad']}x {i['nombre']}" for i in lista_carrito])
            
            fecha_hora_local = ahora.strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute("INSERT INTO ventas (fecha_hora, total_usd, total_bs, productos_detalles) VALUES (?, ?, ?, ?)", 
                           (fecha_hora_local, subtotal, total_bs, detalle_str))
            conexion.commit()
            conexion.close()
            
            lista_carrito.clear()
            for id_p in diccionario_badges:
                actualizar_badge(id_p)
            actualizar_carrito()
            
            sb = ft.SnackBar(ft.Text("¡Ticket copiado y venta registrada!"), bgcolor=ft.Colors.GREEN_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()
        except Exception as ex:
            sb = ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=ft.Colors.RED_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()

    contenedor_carrito.content = ft.Column([
        ft.Row([
            ft.Text("🛒 Carrito Actual", size=22, weight=ft.FontWeight.BOLD),
            ft.TextButton("Vaciar Todo", on_click=vaciar_carrito, style=ft.ButtonStyle(color=ft.Colors.RED_400))
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        
        ft.Row([
            ft.Button("➕ Añadir", on_click=cambiar_a_busqueda, bgcolor=ft.Colors.BLUE_700, icon=ft.Icons.ADD_SHOPPING_CART, height=55, expand=True),
            ft.Button("💵 Monto en Bs", on_click=abrir_dialogo_monto_bs, bgcolor=ft.Colors.ORANGE_700, height=55, expand=True)
        ]),
        
        ft.Container(content=vista_carrito, border=ft.Border.all(1, ft.Colors.GREY_700), border_radius=8, padding=10, expand=True),
        ft.Divider(height=2),
        txt_total_ui,
        txt_total_bs_ui,
        ft.Button("COBRAR Y COPIAR TICKET", on_click=cobrar_ticket, bgcolor=ft.Colors.GREEN_700, height=60, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))
    ], expand=True, spacing=15)

    def abrir_dialogo_producto(id_p=None, nombre="", precio=0.0):
        entry_nombre = ft.TextField(label="Nombre del Producto", value=nombre)
        switch_bs = ft.Switch(label="El precio está en Bolívares (Bs)", value=False)
        entry_precio = ft.TextField(label="Precio en $", value=str(precio) if precio else "", keyboard_type=ft.KeyboardType.NUMBER)
        
        def cambiar_moneda(e):
            entry_precio.label = "Precio en Bs" if switch_bs.value else "Precio en $"
            page.update()
            
        switch_bs.on_change = cambiar_moneda

        def guardar(e):
            try:
                valor_ingresado = float(entry_precio.value)
                precio_final_usd = valor_ingresado / tasa_del_dia if switch_bs.value else valor_ingresado

                conexion = sqlite3.connect(DB_PATH)
                cursor = conexion.cursor()
                
                if id_p:
                    cursor.execute("UPDATE productos SET nombre=?, costo_dolar=? WHERE id=?", (entry_nombre.value, precio_final_usd, id_p))
                else:
                    cursor.execute("INSERT INTO productos (nombre, categoria, costo_dolar, estatus, cantidad) VALUES (?, 'General', ?, 'Activo', 0)", (entry_nombre.value, precio_final_usd))
                
                conexion.commit()
                conexion.close()
                dialog.open = False
                cargar_productos_almacen()
                cargar_productos_vista()
                page.update()
            except:
                pass

        dialog = ft.AlertDialog(
            title=ft.Text("Editar Producto" if id_p else "Nuevo Producto", weight=ft.FontWeight.BOLD),
            content=ft.Column([entry_nombre, switch_bs, entry_precio], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Guardar", on_click=guardar, bgcolor=ft.Colors.GREEN_700)
            ]
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def eliminar_producto(id_p):
        def confirmar(e):
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            cursor.execute("UPDATE productos SET estatus='Inactivo' WHERE id=?", (id_p,))
            conexion.commit()
            conexion.close()
            dialog.open = False
            cargar_productos_almacen()
            cargar_productos_vista()
            page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("¿Eliminar Producto?"),
            content=ft.Text("El producto ya no aparecerá en la lista de ventas."),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Eliminar", on_click=confirmar, bgcolor=ft.Colors.RED_700)
            ]
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    vista_almacen = ft.ListView(expand=True, spacing=10, padding=10)
    tab_almacen = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Inventario", size=22, weight=ft.FontWeight.BOLD),
                ft.Button("Añadir +", on_click=lambda e: abrir_dialogo_producto(), bgcolor=ft.Colors.BLUE_700)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            vista_almacen
        ], expand=True),
        padding=10
    )

    # === LÓGICA Y DISEÑO DEL CIERRE DE CAJA ===
    txt_cierre = ft.Text("Cargando...")
    
    def cargar_cierre(e=None):
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        fecha_busqueda = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT total_usd, total_bs FROM ventas WHERE DATE(fecha_hora) = ?", (fecha_busqueda,))
        ventas = cursor.fetchall()
        conexion.close()
        
        t_usd = sum(v[0] for v in ventas)
        t_bs = sum(v[1] for v in ventas)
        txt_cierre.value = f"Ventas de hoy: {len(ventas)}\n\nTotal Recaudado: ${t_usd:.2f}\nTotal Bs: {t_bs:.2f} Bs."
        page.update()

        if e is not None: 
            sb = ft.SnackBar(ft.Text("Datos del cierre actualizados"), bgcolor=ft.Colors.BLUE_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()

    async def copiar_cierre(e):
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        fecha_busqueda = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT fecha_hora, total_usd, total_bs, productos_detalles FROM ventas WHERE DATE(fecha_hora) = ?", (fecha_busqueda,))
        ventas = cursor.fetchall()
        conexion.close()

        if not ventas:
            sb = ft.SnackBar(ft.Text("No hay ventas para copiar hoy."), bgcolor=ft.Colors.ORANGE_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()
            return

        texto = f"=== CIERRE DE CAJA - {datetime.now().strftime('%d/%m/%Y')} ===\n\n"
        t_usd = 0
        t_bs = 0
        for i, v in enumerate(ventas, 1):
            hora = v[0][11:16]
            t_usd += v[1]
            t_bs += v[2]
            texto += f"Venta #{i} ({hora}): {v[3]}\n Total: ${v[1]:.2f} / {v[2]:.2f} Bs.\n"

        texto += f"\n=========================\n💰 TOTAL VENTAS: {len(ventas)}\n🟢 Total Ref: ${t_usd:.2f}\n🔵 Total Bs: {t_bs:.2f} Bs.\n=========================\n"

        await clipboard.set(texto)
        
        sb = ft.SnackBar(ft.Text("¡Cierre copiado al portapapeles!"), bgcolor=ft.Colors.GREEN_700)
        page.overlay.append(sb)
        sb.open = True
        page.update()

    def reiniciar_dia(e):
        def confirmar_reset(e):
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            fecha_busqueda = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("DELETE FROM ventas WHERE DATE(fecha_hora) = ?", (fecha_busqueda,))
            conexion.commit()
            conexion.close()
            dialog.open = False
            cargar_cierre()
            sb = ft.SnackBar(ft.Text("Ventas de hoy reiniciadas."), bgcolor=ft.Colors.GREEN_700)
            page.overlay.append(sb)
            sb.open = True
            page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("¿Reiniciar Día?"),
            content=ft.Text("Se borrarán las ventas de hoy de la base de datos. ¿Estás seguro?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Sí, Reiniciar", on_click=confirmar_reset, bgcolor=ft.Colors.RED_700)
            ]
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    tab_cierre = ft.Container(
        content=ft.Column([
            ft.Text("Cierre de Caja Diario", size=22, weight=ft.FontWeight.BOLD),
            txt_cierre,
            ft.Row([
                ft.Button("Actualizar", on_click=cargar_cierre, bgcolor=ft.Colors.BLUE_700),
                ft.Button("Copiar Cierre", on_click=copiar_cierre, bgcolor=ft.Colors.GREEN_700),
                ft.Button("Reiniciar Día", on_click=reiniciar_dia, bgcolor=ft.Colors.RED_700)
            ], alignment=ft.MainAxisAlignment.CENTER, wrap=True)
        ], spacing=20), 
        padding=10
    )

    contenido_principal = ft.Container(content=contenedor_carrito, expand=True)
    
    def cambiar_pestana(e):
        idx = e.control.selected_index
        if idx == 0:
            contenido_principal.content = ft.Column([contenedor_busqueda, contenedor_carrito], expand=True)
            contenedor_busqueda.visible = False
            contenedor_carrito.visible = True
            cargar_productos_vista()
        elif idx == 1:
            contenido_principal.content = tab_almacen
            cargar_productos_almacen()
        elif idx == 2:
            contenido_principal.content = tab_cierre
            cargar_cierre()
        page.update()

    barra_nav = ft.NavigationBar(
        selected_index=0,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.POINT_OF_SALE, label="Vender"),
            ft.NavigationBarDestination(icon=ft.Icons.INVENTORY, label="Productos"),
            ft.NavigationBarDestination(icon=ft.Icons.ASSESSMENT, label="Cierre"),
        ],
        on_change=cambiar_pestana
    )

    btn_editar_tasa = ft.IconButton(ft.Icons.EDIT, icon_color=ft.Colors.ORANGE_400, tooltip="Cambiar Tasa Manual", on_click=abrir_dialogo_tasa)
    btn_activar_manual = ft.IconButton(ft.Icons.KEY, icon_color=ft.Colors.AMBER_400, tooltip="Activar Licencia", on_click=lambda e: page.run_task(mostrar_ventana_activacion, page, codigo_id))

    cabecera = ft.Row([
        ft.Column([
            ft.Text("Tu Compra Rápida", size=20, weight=ft.FontWeight.BOLD), 
            ft.Row([txt_licencia_ui, btn_activar_manual], spacing=5)
        ]),
        ft.Row([
            txt_tasa_ui,
            btn_editar_tasa
        ], spacing=2)
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN) 

    contenido_principal.content = ft.Column([contenedor_busqueda, contenedor_carrito], expand=True)
    
    page.add(cabecera, contenido_principal, barra_nav)

    cargar_productos_vista()
    actualizar_carrito()
    actualizar_tasa_en_hilo(page, txt_tasa_ui)

if __name__ == "__main__":
    ft.run(main)
