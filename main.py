import flet as ft
import sqlite3
import os
import json
import uuid
import hashlib
import shutil
from datetime import datetime

# === CONFIGURACIÓN DE RUTAS ===
STORAGE_PATH = os.getenv("FLET_APP_STORAGE_DATA", ".")
DB_PATH = os.path.join(STORAGE_PATH, "inventario.db")

# === SISTEMA DE LICENCIAS ===
SECRETO = "TuCompraRapida2026"
DIAS_PRUEBA = 7

def obtener_id_maquina():
    id_crudo = str(uuid.getnode())
    return hashlib.md5(id_crudo.encode()).hexdigest()[:8].upper()

async def verificar_licencia(page):
    hoy = datetime.now()
    prefs = ft.SharedPreferences()
    
    if prefs not in page.services:
        page.services.append(prefs)
    
    licencia_str = await prefs.get("tcr_licencia")
    
    if not licencia_str:
        datos = {"tipo": "prueba", "fecha_inicio": hoy.strftime("%Y-%m-%d"), "ultima_fecha_vista": hoy.strftime("%Y-%m-%d")}
        await prefs.set("tcr_licencia", json.dumps(datos))
        return True, "Prueba: 7 días"
        
    datos = json.loads(licencia_str)
        
    if datos.get("tipo") == "activa":
        return True, "✅ Licencia Activa"
        
    ultima_fecha = datetime.strptime(datos.get("ultima_fecha_vista", datos["fecha_inicio"]), "%Y-%m-%d")
    if hoy < ultima_fecha:
        return False, "❌ Error de fecha"
        
    datos["ultima_fecha_vista"] = hoy.strftime("%Y-%m-%d")
    await prefs.set("tcr_licencia", json.dumps(datos))
        
    fecha_inicio = datetime.strptime(datos["fecha_inicio"], "%Y-%m-%d")
    dias = (hoy - fecha_inicio).days
    
    if dias >= DIAS_PRUEBA:
        return False, "❌ Prueba Vencida"
        
    return True, f"⏳ Prueba: {DIAS_PRUEBA - dias} días"

async def mostrar_ventana_activacion(page):
    id_maquina = obtener_id_maquina()
    entry_codigo = ft.TextField(label="Código de Activación", text_align=ft.TextAlign.CENTER)
    prefs = ft.SharedPreferences()

    async def activar(e):
        codigo_ingresado = entry_codigo.value.strip().upper()
        texto_a_encriptar = f"{id_maquina}-{SECRETO}"
        codigo_esperado = hashlib.sha256(texto_a_encriptar.encode()).hexdigest()[:8].upper()
        
        if codigo_ingresado == codigo_esperado:
            datos = {"tipo": "activa", "fecha_vencimiento": "2099-12-31"}
            await prefs.set("tcr_licencia", json.dumps(datos))
            
            dialogo.open = False
            page.update()
            
            page.controls.clear()
            await main(page)
            page.update()
        else:
            sb = ft.SnackBar(ft.Text("Código incorrecto ❌"), bgcolor=ft.Colors.RED)
            page.overlay.append(sb)
            sb.open = True
            page.update()

    dialogo = ft.AlertDialog(
        title=ft.Text("🔒 Activación Requerida", text_align=ft.TextAlign.CENTER),
        content=ft.Column([
            ft.Text("Su período de prueba ha terminado.\nEnvíe este código a su proveedor:", text_align=ft.TextAlign.CENTER),
            ft.Container(
                content=ft.Text(id_maquina, size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN),
                bgcolor="#2b2b2b", padding=10, border_radius=5, alignment=ft.Alignment(0, 0)
            ),
            entry_codigo
        ], tight=True),
        actions=[ft.Button("Activar Programa 🔓", on_click=activar, bgcolor=ft.Colors.GREEN, width=300)],
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
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_usd REAL, total_bs REAL, productos_detalles TEXT, iva_usd REAL DEFAULT 0)""")
    conexion.commit()
    conexion.close()

# === FUNCIÓN PRINCIPAL ===
async def main(page: ft.Page):
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
    
    licencia_ok, txt_licencia = await verificar_licencia(page)
    if not licencia_ok:
        await mostrar_ventana_activacion(page)
        return

    tasa_del_dia = 887.30
    lista_carrito = []
    
    txt_licencia_ui = ft.Text(txt_licencia, color=ft.Colors.YELLOW, weight=ft.FontWeight.BOLD, size=12)
    txt_tasa_ui = ft.Text(f"Tasa: {tasa_del_dia:.2f} Bs.", color=ft.Colors.CYAN, weight=ft.FontWeight.BOLD, size=12)
    
    # === COMPONENTES DE VISTA ===
    vista_carrito = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=5)
    txt_total_ui = ft.Text("Total: $0.00", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)
    txt_total_bs_ui = ft.Text("0.00 Bs.", size=16, color=ft.Colors.GREEN)
    
    contenedor_busqueda = ft.Container(visible=False, expand=True)
    contenedor_carrito = ft.Container(visible=True, expand=True)
    
    # === FUNCIONES DE LÓGICA ===
    def cargar_productos_vista(filtro=""):
        vista_productos.controls.clear()
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        if filtro:
            cursor.execute("SELECT id, nombre, costo_dolar FROM productos WHERE estatus='Activo' AND nombre LIKE ?", (f'%{filtro}%',))
        else:
            cursor.execute("SELECT id, nombre, costo_dolar FROM productos WHERE estatus='Activo'")
        
        for prod in cursor.fetchall():
            id_p, nombre, precio = prod
            vista_productos.controls.append(
                ft.Button(
                    content=ft.Text(f"{nombre} - ${precio:.2f}", size=16),
                    on_click=lambda e, i=id_p, n=nombre, p=precio: abrir_dialogo_cantidad(i, n, p),
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE),
                    height=50, width=400
                )
            )
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
                            ft.Text(f"${precio:.2f}", size=14, color=ft.Colors.GREEN)
                        ], expand=True),
                        ft.IconButton(ft.Icons.EDIT, icon_color=ft.Colors.BLUE, on_click=lambda e, i=id_p, n=nombre, p=precio: abrir_dialogo_producto(i, n, p)),
                        ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED, on_click=lambda e, i=id_p: eliminar_producto(i))
                    ]),
                    padding=10, border=ft.Border.all(1, ft.Colors.GREY_800), border_radius=10
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

    def abrir_dialogo_cantidad(id_p, nombre, precio):
        entry_cant = ft.TextField(
            label="Cantidad o Peso (Ej: 1, 0.5)", 
            value="1", 
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER
        )
        
        def agregar(e):
            try:
                cant = float(entry_cant.value)
                if cant > 0:
                    agregar_al_carrito(id_p, nombre, precio, cant)
                    dialog.open = False
                    page.update()
            except ValueError:
                sb = ft.SnackBar(ft.Text("Por favor, ingrese un número válido"), bgcolor=ft.Colors.RED)
                page.overlay.append(sb)
                sb.open = True
                page.update()

        dialog = ft.AlertDialog(
            title=ft.Text(f"Agregar: {nombre}"),
            content=ft.Column([
                ft.Text(f"Precio por unidad: ${precio:.2f}", size=14, color=ft.Colors.GREY),
                entry_cant
            ], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Añadir al Carrito", on_click=agregar, bgcolor=ft.Colors.GREEN)
            ]
        )
        
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def agregar_al_carrito(id_p, nombre, precio, cantidad):
        for item in lista_carrito:
            if item["id"] == id_p:
                item["cantidad"] += cantidad
                actualizar_carrito()
                return
        lista_carrito.append({"id": id_p, "nombre": nombre, "precio": precio, "cantidad": cantidad})
        actualizar_carrito()

    def restar_unidad(id_p):
        for item in lista_carrito:
            if item["id"] == id_p:
                item["cantidad"] -= 1
                if item["cantidad"] <= 0.01:
                    lista_carrito.remove(item)
                break
        actualizar_carrito()

    def eliminar_del_carrito(id_p):
        for item in lista_carrito:
            if item["id"] == id_p:
                lista_carrito.remove(item)
                break
        actualizar_carrito()

    def actualizar_carrito():
        subtotal = sum(item["precio"] * item["cantidad"] for item in lista_carrito)
        txt_total_ui.value = f"Total: ${subtotal:.2f}"
        txt_total_bs_ui.value = f"{subtotal * tasa_del_dia:.2f} Bs."
        
        vista_carrito.controls.clear()
        if not lista_carrito:
            vista_carrito.controls.append(ft.Text("El carrito está vacío. Toca '+ Añadir Productos'", color=ft.Colors.GREY))
        else:
            for item in lista_carrito:
                cant_str = int(item['cantidad']) if float(item['cantidad']).is_integer() else item['cantidad']
                fila = ft.Row([
                    ft.Text(f"{cant_str}x {item['nombre']}", expand=True, size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"${item['precio'] * item['cantidad']:.2f}", size=14, color=ft.Colors.GREEN),
                    ft.IconButton(ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_color=ft.Colors.ORANGE, on_click=lambda e, i=item['id']: restar_unidad(i), icon_size=20),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED, on_click=lambda e, i=item['id']: eliminar_del_carrito(i), icon_size=20)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                vista_carrito.controls.append(fila)
        
        page.update()

    def vaciar_carrito(e):
        lista_carrito.clear()
        actualizar_carrito()

    # === VISTA 1: BÚSQUEDA DE PRODUCTOS ===
    entry_buscador = ft.TextField(hint_text="🔍 Buscar producto...", on_change=lambda e: cargar_productos_vista(e.control.value), prefix_icon=ft.Icons.SEARCH)
    vista_productos = ft.ListView(expand=True, spacing=10)
    
    contenedor_busqueda.content = ft.Column([
        ft.Row([
            ft.IconButton(ft.Icons.ARROW_BACK, on_click=cambiar_a_carrito, icon_color=ft.Colors.WHITE, tooltip="Volver al Carrito"),
            ft.Text("Añadir Productos", size=20, weight=ft.FontWeight.BOLD)
        ]),
        entry_buscador,
        vista_productos
    ], expand=True)

    # === FUNCIÓN COBRAR (CORREGIDA) ===
    async def cobrar_ticket(e):
        try:
            if not lista_carrito:
                sb = ft.SnackBar(ft.Text("El carrito está vacío"), bgcolor=ft.Colors.RED)
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
            
            # Copiar al portapapeles
            await clipboard.set(texto)
            
            # Guardar en BD
            conexion = sqlite3.connect(DB_PATH)
            cursor = conexion.cursor()
            detalle_str = ", ".join([f"{int(i['cantidad']) if float(i['cantidad']).is_integer() else i['cantidad']}x {i['nombre']}" for i in lista_carrito])
            cursor.execute("INSERT INTO ventas (total_usd, total_bs, productos_detalles) VALUES (?, ?, ?)", (subtotal, total_bs, detalle_str))
            conexion.commit()
            conexion.close()
            
            lista_carrito.clear()
            actualizar_carrito()
            
            sb = ft.SnackBar(ft.Text("¡Ticket copiado y venta registrada!"), bgcolor=ft.Colors.GREEN)
            page.overlay.append(sb)
            sb.open = True
            page.update()
        except Exception as ex:
            sb = ft.SnackBar(ft.Text(f"Error al cobrar: {ex}"), bgcolor=ft.Colors.RED)
            page.overlay.append(sb)
            sb.open = True
            page.update()

    # === VISTA 2: CARRITO DE VENTA ===
    contenedor_carrito.content = ft.Column([
        ft.Row([
            ft.Text("🛒 Carrito Actual", size=20, weight=ft.FontWeight.BOLD),
            ft.TextButton("Vaciar Todo", on_click=vaciar_carrito, style=ft.ButtonStyle(color=ft.Colors.RED))
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        
        ft.Button(
            "➕ Añadir Productos", 
            on_click=cambiar_a_busqueda, 
            bgcolor=ft.Colors.BLUE_700, 
            icon=ft.Icons.ADD_SHOPPING_CART,
            height=50
        ),
        
        ft.Container(content=vista_carrito, border=ft.Border.all(1, ft.Colors.GREY_700), border_radius=5, padding=10, expand=True),
        ft.Divider(),
        txt_total_ui,
        txt_total_bs_ui,
        
        # AQUI ESTA EL CAMBIO: on_click=cobrar_ticket SIN EL LAMBDA
        ft.Button("COBRAR Y COPIAR TICKET", on_click=cobrar_ticket, bgcolor=ft.Colors.GREEN, height=50)
    ], expand=True)

    # === LÓGICA DE ALMACÉN ===
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
            except Exception as ex:
                sb = ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=ft.Colors.RED)
                page.overlay.append(sb)
                sb.open = True
                page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Editar Producto" if id_p else "Nuevo Producto"),
            content=ft.Column([entry_nombre, switch_bs, entry_precio], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: setattr(dialog, 'open', False) or page.update()),
                ft.Button("Guardar", on_click=guardar, bgcolor=ft.Colors.GREEN)
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
                ft.Button("Eliminar", on_click=confirmar, bgcolor=ft.Colors.RED)
            ]
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    # === PESTAÑA ALMACÉN ===
    vista_almacen = ft.ListView(expand=True, spacing=10)
    tab_almacen = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Inventario", size=20, weight=ft.FontWeight.BOLD),
                ft.Button("Añadir +", on_click=lambda e: abrir_dialogo_producto(), bgcolor=ft.Colors.BLUE)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            vista_almacen
        ], expand=True),
        padding=10
    )

    # === PESTAÑA CIERRE ===
    txt_cierre = ft.Text("Cargando...")
    def cargar_cierre():
        conexion = sqlite3.connect(DB_PATH)
        cursor = conexion.cursor()
        cursor.execute("SELECT total_usd, total_bs FROM ventas WHERE DATE(fecha_hora) = DATE('now', 'localtime')")
        ventas = cursor.fetchall()
        conexion.close()
        
        t_usd = sum(v[0] for v in ventas)
        t_bs = sum(v[1] for v in ventas)
        txt_cierre.value = f"Ventas de hoy: {len(ventas)}\n\nTotal Recaudado: ${t_usd:.2f}\nTotal Bs: {t_bs:.2f} Bs."
        page.update()

    tab_cierre = ft.Container(
        content=ft.Column([
            ft.Text("Cierre de Caja Diario", size=20, weight=ft.FontWeight.BOLD),
            txt_cierre,
            ft.Button("Actualizar Datos", on_click=lambda e: cargar_cierre(), bgcolor=ft.Colors.BLUE)
        ]),
        padding=10
    )

    # === NAVEGACIÓN PRINCIPAL ===
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

    cabecera = ft.Row([
        ft.Column([ft.Text("Tu Compra Rápida", size=18, weight=ft.FontWeight.BOLD), txt_licencia_ui]),
        ft.Column([txt_tasa_ui], alignment=ft.MainAxisAlignment.END)
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    contenido_principal.content = ft.Column([contenedor_busqueda, contenedor_carrito], expand=True)
    
    page.add(cabecera, contenido_principal, barra_nav)

    cargar_productos_vista()
    actualizar_carrito()

if __name__ == "__main__":
    ft.run(main)
