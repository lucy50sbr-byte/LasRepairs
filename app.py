from flask import Flask, jsonify
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
from datetime import datetime, timedelta
import json
import os
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

# CONFIGURACIÓN DE FAST-CHEAP (Completa con tus datos)
USER = "lucy50.sbr@gmail.com"
PASS = "Hola2026"

# Ruta del archivo donde guardaremos los precios
JSON_FILE = os.path.join(os.path.dirname(__file__), "precios.json")
REPARACIONES_FILE = os.path.join(os.path.dirname(__file__), "reparaciones.json")

# Cache para no saturar el sitio ni ralentizar tu web
cache_datos = {"lista": [], "ultima_actualizacion": None}

def cargar_desde_archivo():
    """Carga los datos del archivo JSON si existe."""
    global cache_datos
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cache_datos["lista"] = data.get("lista", [])
                if data.get("ultima_actualizacion"):
                    cache_datos["ultima_actualizacion"] = datetime.fromisoformat(data["ultima_actualizacion"])
                print("Datos cargados desde precios.json correctamente.")
        except Exception as e:
            print(f"Error al cargar archivo JSON: {e}")

def scrape_category(url, category_type, start_id):
    """Función auxiliar para scrapear una categoría específica."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    wait = WebDriverWait(driver, 20)
    
    items = []
    try:
        driver.get("https://www.fast-cheap.com.ar/mi-cuenta/")
        try:
            email_input = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            email_input.send_keys(USER)
            driver.find_element(By.ID, "password").send_keys(PASS)
            driver.find_element(By.NAME, "login").click()
            time.sleep(3)
        except: pass

        driver.get(url)
        for i in range(1, 4):
            driver.execute_script(f"window.scrollTo(0, {i * 1000});")
            time.sleep(0.5)
        
        selector_productos = "li.product, .product, .type-product"
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector_productos)))
        productos = driver.find_elements(By.CSS_SELECTOR, selector_productos)
        
        for i, prod in enumerate(productos):
            try:
                nombre = prod.find_element(By.CSS_SELECTOR, ".woocommerce-loop-product__title, h2").text.strip()
                try:
                    precio_str = prod.find_element(By.CSS_SELECTOR, ".price bdi, .price .amount").text
                except: precio_str = "0"
                
                # (Lógica de limpieza de precio y marca simplificada para el ejemplo)
                p_limpio = "".join(c for c in precio_str if c.isdigit() or c in ".,").replace('.','').replace(',','.')
                precio = float(p_limpio) if p_limpio else 0.0

                items.append({
                    "id": start_id + i,
                    "marca": "Genérico", # Aquí iría la lógica de detección de marca
                    "modelo": nombre,
                    "type": category_type,
                    "costoChina": precio,
                    "costoOriginal": precio * 1.2
                })
            except: continue
    finally:
        driver.quit()
    return items

def get_fast_cheap_prices(force=False):
    global cache_datos
    
    if not cache_datos["lista"]:
        cargar_desde_archivo()

    # Si actualizamos hace menos de 1 hora, devolvemos lo guardado (a menos que sea forzado)
    if not force and cache_datos["ultima_actualizacion"] and datetime.now() < cache_datos["ultima_actualizacion"] + timedelta(hours=1):
        print("Cargando precios desde el cache...")
        return cache_datos["lista"]

    chrome_options = Options()
    chrome_options.add_argument("--headless=new") # Versión moderna de headless
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    # User agent para evitar bloqueos por parecer un bot
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    wait = WebDriverWait(driver, 20) # Aumentamos a 20 segundos
    
    paso_actual = "Inicio"
    lista_repuestos = []
    
    try: # Bloque principal para módulos
        print("Iniciando sesión en Fast-Cheap...")
        # WooCommerce suele usar /mi-cuenta/ para el login
        driver.get("https://www.fast-cheap.com.ar/mi-cuenta/")
        
        paso_actual = "Login"
        # Verificamos si ya estamos logueados o si hay que loguear
        try:
            email_input = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            email_input.clear()
            email_input.send_keys(USER)
            
            password_input = driver.find_element(By.ID, "password")
            password_input.send_keys(PASS)
            
            driver.find_element(By.NAME, "login").click()
            time.sleep(5) 
        except TimeoutException:
            print("Ya parece haber una sesión activa o el formulario cambió.")
        
        paso_actual = "Navegación a Módulos"
        print("Navegando a la sección de Módulos...")
        driver.get("https://www.fast-cheap.com.ar/categorias/modulo/?per_page=900") # Aumentamos el límite para módulos
        
        # Scroll progresivo para disparar la carga de contenido dinámico
        paso_actual = "Cargando Contenido"
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {i * 1000});")
            time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, 0);")
        
        # Esperar a que los productos estén presentes con un selector MUCHO más amplio
        selector_productos = "li.product, .product, .type-product, article.product"
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector_productos)))
        
        paso_actual = "Extracción de Productos"
        productos_modulos = driver.find_elements(By.CSS_SELECTOR, selector_productos)
        print(f"DEBUG: Elementos encontrados con el selector: {len(productos_modulos)}")
        
        for i, prod in enumerate(productos_modulos): 
            try:
                # Buscamos el nombre en varios posibles tags
                nombre_el = prod.find_element(By.CSS_SELECTOR, ".woocommerce-loop-product__title, h2, h3, .product-title")
                nombre = nombre_el.text.strip()
                
                # Extracción de precio más precisa (buscando etiquetas bdi de WooCommerce)
                try:
                    # Buscamos el precio dentro de bdi o el contenedor de precio
                    precio_el = prod.find_element(By.CSS_SELECTOR, ".price ins .amount, .price bdi, .price .amount")
                    precio_str = precio_el.text
                except:
                    precio_str = "0"
                
                # Extracción robusta de imagen
                imagen = ""
                try:
                    img_el = prod.find_element(By.TAG_NAME, "img")
                    # Buscamos la URL real en data-src, srcset o src
                    cand = img_el.get_attribute("data-src") or img_el.get_attribute("srcset") or img_el.get_attribute("src")
                    if cand:
                        # Si es un srcset, tomamos la primera; si es base64 (placeholder), la ignoramos
                        url_candidata = cand.split(",")[0].split(" ")[0]
                        if not url_candidata.startswith("data:image"):
                            imagen = url_candidata
                except:
                    pass
                
                # Limpieza robusta para Pesos Argentinos (ARS)
                # Eliminamos todo lo que no sea número, coma o punto
                p_limpio = "".join(c for c in precio_str if c.isdigit() or c in ".,").strip()
                if ',' in p_limpio and '.' in p_limpio:
                    # Detectamos cual es el separador decimal (el que está más a la derecha)
                    if p_limpio.rfind(',') > p_limpio.rfind('.'):
                        p_limpio = p_limpio.replace('.', '').replace(',', '.')
                    else:
                        p_limpio = p_limpio.replace(',', '')
                elif ',' in p_limpio:
                    parts = p_limpio.split(',')
                    if len(parts[-1]) == 2: p_limpio = p_limpio.replace(',', '.')
                    else: p_limpio = p_limpio.replace(',', '')
                elif '.' in p_limpio:
                    parts = p_limpio.split('.')
                    if len(parts[-1]) != 2: p_limpio = p_limpio.replace('.', '')

                precio = float(p_limpio) if p_limpio else 0.0
                
                # Detección de marca mejorada (insensible a mayúsculas)
                nombre_lower = nombre.lower()
                marca = "Otros"
                
                # Diccionario de palabras clave para categorización automática
                busqueda_marcas = {
                    "samsung": "Samsung",
                    "motorola": "Motorola",
                    "moto": "Motorola",
                    "iphone": "iPhone",
                    "alcatel": "Alcatel",
                    "honor": "Honor",
                    "infinix": "Infinix",
                    "lg": "LG",
                    "nokia": "Nokia",
                    "nubia": "Nubia",
                    "xiaomi": "Xiaomi",
                    "redmi": "Xiaomi"
                }

                for key, val in busqueda_marcas.items():
                    if key in nombre_lower:
                        marca = val
                        break

                lista_repuestos.append({
                    "id": i,
                    "marca": marca,
                    "modelo": nombre,
                    "imagen": imagen,
                    "type": "modulo", # Añadimos el tipo de producto
                    "costoChina": round(precio, 2),
                    "costoOriginal": round(precio * 1.2, 2)
                })
            except:
                continue
        
        # --- INICIO DE EXTRACCIÓN DE BATERÍAS ---
        paso_actual = "Navegación a Baterías"
        print("Navegando a la sección de Baterías...")
        driver.get("https://www.fast-cheap.com.ar/categorias/bateria/?per_page=400") # URL de baterías

        # Scroll progresivo para disparar la carga de contenido dinámico
        paso_actual = "Cargando Contenido (Baterías)"
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {i * 1000});")
            time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, 0);")

        # Esperar a que los productos estén presentes con un selector MUCHO más amplio
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector_productos)))

        paso_actual = "Extracción de Productos (Baterías)"
        productos_baterias = driver.find_elements(By.CSS_SELECTOR, selector_productos)
        print(f"DEBUG: Elementos encontrados (Baterías) con el selector: {len(productos_baterias)}")

        for i, prod in enumerate(productos_baterias):
            try:
                nombre_el = prod.find_element(By.CSS_SELECTOR, ".woocommerce-loop-product__title, h2, h3, .product-title")
                nombre = nombre_el.text.strip()
                
                try:
                    precio_el = prod.find_element(By.CSS_SELECTOR, ".price ins .amount, .price bdi, .price .amount")
                    precio_str = precio_el.text
                except:
                    precio_str = "0"
                
                imagen = ""
                try:
                    img_el = prod.find_element(By.TAG_NAME, "img")
                    cand = img_el.get_attribute("data-src") or img_el.get_attribute("srcset") or img_el.get_attribute("src")
                    if cand:
                        url_candidata = cand.split(",")[0].split(" ")[0]
                        if not url_candidata.startswith("data:image"):
                            imagen = url_candidata
                except:
                    pass
                
                p_limpio = "".join(c for c in precio_str if c.isdigit() or c in ".,").strip()
                if ',' in p_limpio and '.' in p_limpio:
                    if p_limpio.rfind(',') > p_limpio.rfind('.'): p_limpio = p_limpio.replace('.', '').replace(',', '.')
                    else: p_limpio = p_limpio.replace(',', '')
                elif ',' in p_limpio:
                    parts = p_limpio.split(',')
                    if len(parts[-1]) == 2: p_limpio = p_limpio.replace(',', '.')
                    else: p_limpio = p_limpio.replace(',', '')
                elif '.' in p_limpio:
                    parts = p_limpio.split('.')
                    if len(parts[-1]) != 2: p_limpio = p_limpio.replace('.', '')

                precio = float(p_limpio) if p_limpio else 0.0
                
                nombre_lower = nombre.lower()
                marca = "Otros"
                busqueda_marcas = {
                    "samsung": "Samsung", "motorola": "Motorola", "moto": "Motorola", "iphone": "iPhone",
                    "alcatel": "Alcatel", "honor": "Honor", "infinix": "Infinix", "lg": "LG",
                    "nokia": "Nokia", "nubia": "Nubia", "xiaomi": "Xiaomi", "redmi": "Xiaomi",
                    "zte": "ZTE", "tcl": "TCL", "realme": "Realme", "oppo": "Oppo", "tecno": "Tecno"
                }
                for key, val in busqueda_marcas.items():
                    if key in nombre_lower:
                        marca = val
                        break

                lista_repuestos.append({
                    "id": len(lista_repuestos), # ID único para cada producto
                    "marca": marca,
                    "modelo": nombre,
                    "imagen": imagen,
                    "type": "bateria", # Añadimos el tipo de producto
                    "costoChina": round(precio, 2),
                    "costoOriginal": round(precio * 1.2, 2)
                })
            except:
                continue
        # --- FIN DE EXTRACCIÓN DE BATERÍAS ---

        # Guardar en cache
        cache_datos["lista"] = lista_repuestos
        cache_datos["ultima_actualizacion"] = datetime.now()

        # Guardar en archivo físico para persistencia
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "lista": cache_datos["lista"],
                "ultima_actualizacion": cache_datos["ultima_actualizacion"].isoformat()
            }, f, indent=4)
            
        print(f"Se extrajeron {len(lista_repuestos)} productos exitosamente.")

    except (TimeoutException, WebDriverException, Exception) as e:
        print(f"Aviso: No se pudo actualizar desde la web ({paso_actual}). Usando datos locales.")
        # Si falla el scraping, intentamos recargar el JSON por si acaso cambió
        if not cache_datos["lista"]:
            cargar_desde_archivo()
        return cache_datos["lista"]
    finally:
        if 'driver' in locals():
            driver.quit()
    
    return lista_repuestos

@app.route('/')
def home():
    return "Servidor LAS Repairs activo. La API está en /api/precios"

def cargar_db_reparaciones():
    """Carga los estados de reparación desde el archivo JSON."""
    if os.path.exists(REPARACIONES_FILE):
        with open(REPARACIONES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "1001": {"msg": "Equipo en revisión técnica.", "paso": 2},
        "1002": {"msg": "¡Listo! Podés pasar por el local.", "paso": 4}
    }

@app.route('/api/estado/<ticket>')
def consultar_estado(ticket):
    db = cargar_db_reparaciones()
    # Si el ticket no existe, devolvemos un mensaje genérico
    info = db.get(str(ticket), {"msg": "Ticket no encontrado. Verificá el número.", "paso": 0})
    return jsonify({"ticket": ticket, "msg": info["msg"], "paso": info["paso"]})

@app.route('/api/precios')
def precios():
    get_fast_cheap_prices()
    return jsonify({
        "lista": cache_datos["lista"],
        "ultima_actualizacion": cache_datos["ultima_actualizacion"].isoformat() if cache_datos["ultima_actualizacion"] else None
    })

@app.route('/api/actualizar', methods=['POST'])
def actualizar():
    get_fast_cheap_prices(force=True)
    return jsonify({
        "lista": cache_datos["lista"],
        "ultima_actualizacion": cache_datos["ultima_actualizacion"].isoformat() if cache_datos["ultima_actualizacion"] else None
    })

if __name__ == '__main__':
    # Cargar datos al iniciar el servidor
    cargar_desde_archivo()
    print("Servidor de precios iniciado en http://localhost:5000")
    app.run(port=5000, debug=True)