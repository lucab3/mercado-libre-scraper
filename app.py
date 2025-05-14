import os
import csv
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify
from datetime import datetime
import re
import difflib
import webbrowser
from threading import Timer
import platform
import json
import logging
import sys
import traceback
from functools import lru_cache
import random

# Configuración de logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper_debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MercadoLibreScraper")

app = Flask(__name__)

# Configuración global para el scraper
CONFIG = {
    'max_products': 20,  # Número máximo de productos a buscar (ajustable desde la interfaz)
    'max_pages': 2,      # Número máximo de páginas a buscar (ajustable desde la interfaz)
    'delay_min': 1.0,    # Tiempo mínimo entre solicitudes (segundos)
    'delay_max': 2.5,    # Tiempo máximo entre solicitudes (segundos)
    'cache_ttl': 3600,   # Tiempo de vida de la caché (1 hora)
    'deep_sales_search': False  # Por defecto no usar búsqueda profunda de ventas
}

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')

# Cache para almacenar resultados de solicitudes HTTP
@lru_cache(maxsize=100)
def cached_request(url, cache_key=None):
    """Hacer solicitud HTTP con caché"""
    logger.debug(f"Realizando solicitud a {url}")
    headers = get_random_headers()
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Error en solicitud HTTP a {url}: {str(e)}")
        raise

def get_random_headers():
    """Generar headers aleatorios para evitar bloqueos"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
    ]
    
    return {
        'User-Agent': random.choice(user_agents),
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://www.mercadolibre.com.ar/'
    }

def random_delay():
    """Genera una pausa aleatoria para evitar ser detectado como bot"""
    delay = random.uniform(CONFIG['delay_min'], CONFIG['delay_max'])
    logger.debug(f"Esperando {delay:.2f} segundos")
    time.sleep(delay)

def extract_price_from_html(element):
    """Extrae el precio de un elemento HTML probando diferentes estructuras"""
    logger.debug("Intentando extraer precio...")
    
    try:
        # Lista de posibles selectores para precios
        price_selectors = [
            # Selectores para estructura de tienda
            ('div', {'class': 'poly-component__price'}),
            ('div', {'class': 'poly-price__current'}),
            ('span', {'class': 'andes-money-amount__fraction'}),
            # Selectores generales
            ('span', {'class': 'price-tag-amount'}),
            ('span', {'class': 'ui-search-price__part'}),
            ('div', {'class': 'ui-search-price__second-line'}),
            ('span', {'class': 'price-tag-fraction'})
        ]
        
        # Buscar usando los selectores
        price_text = None
        for tag, attrs in price_selectors:
            price_element = element.find(tag, attrs)
            if price_element:
                # Si encontramos poly-price__current o andes-money-amount__fraction
                if 'poly-price__current' in str(attrs.values()):
                    fraction_element = price_element.find('span', {'class': 'andes-money-amount__fraction'})
                    if fraction_element:
                        price_text = fraction_element.text.strip()
                    else:
                        # Aquí es donde necesitamos extraer sólo el precio principal, no las cuotas
                        # Buscamos el precio siguiendo el formato "$X.XXX" o "$XX.XXX"
                        full_text = price_element.text.strip()
                        price_match = re.search(r'\$\s*([\d.,]+)', full_text)
                        if price_match:
                            price_text = price_match.group(1)
                        else:
                            price_text = full_text
                else:
                    # Aquí también debemos extraer sólo el precio principal
                    full_text = price_element.text.strip()
                    price_match = re.search(r'\$\s*([\d.,]+)', full_text)
                    if price_match:
                        price_text = price_match.group(1)
                    else:
                        price_text = full_text
                    
                logger.debug(f"Encontrado precio con selector {tag}, {attrs}: {price_text}")
                break
        
        # Si no encontramos con selectores, intentamos con regex
        if not price_text:
            # Buscar cualquier texto que parezca un precio
            price_pattern = re.compile(r'\$\s*([\d.,]+)')
            for span in element.find_all(['span', 'div']):
                match = price_pattern.search(span.text)
                if match:
                    price_text = match.group(1)
                    logger.debug(f"Encontrado precio con regex: {price_text}")
                    break
        
        if price_text:
            # Limpiar y convertir a entero, teniendo en cuenta posibles puntos y comas
            # Primero reemplazamos puntos por nada (separador de miles)
            clean_price = price_text.replace('.', '')
            # Luego reemplazamos comas por puntos (separador decimal)
            clean_price = clean_price.replace(',', '.')
            
            # Convertir a float primero para manejar decimales, luego a entero
            try:
                price = int(float(clean_price))
                logger.debug(f"Precio extraído correctamente: {price}")
                return price
            except ValueError:
                # Si falla la conversión, intentamos otro enfoque eliminando todos los no dígitos
                clean_price = re.sub(r'[^\d]', '', price_text)
                if clean_price.isdigit():
                    price = int(clean_price)
                    logger.debug(f"Precio extraído correctamente (método alternativo): {price}")
                    return price
        
        logger.warning("No se pudo extraer el precio")
        return 0
    
    except Exception as e:
        logger.error(f"Error al extraer precio: {str(e)}")
        logger.error(traceback.format_exc())
        return 0

def extract_seller_info(element):
    """Extrae la información del vendedor probando diferentes estructuras"""
    logger.debug("Intentando extraer información del vendedor...")
    
    try:
        # Lista de posibles selectores para vendedor
        seller_selectors = [
            # Selectores específicos para tiendas
            ('span', {'class': 'poly-component__seller'}),
            # Selectores generales
            ('p', {'class': 'ui-search-official-store-label'}),
            ('p', {'class': 'shops__item-seller-detail'}),
            ('span', {'class': 'ui-search-item__brand-discoverability'}),
            ('span', {'class': 'ui-search-item__group__element'}),
            # Selectores adicionales
            ('div', {'class': 'store-info'}),
            ('a', {'class': 'store-name'})
        ]
        
        # Buscar usando los selectores
        for tag, attrs in seller_selectors:
            seller_element = element.find(tag, attrs)
            if seller_element:
                seller_info = seller_element.text.strip()
                # Limpiar: quitar "Por " si está presente
                seller_info = re.sub(r'^Por\s+', '', seller_info)
                # Quitar texto de tienda oficial si existe
                seller_info = re.sub(r'\s*Tienda\s*oficial.*$', '', seller_info)
                
                logger.debug(f"Encontrado vendedor con selector {tag}, {attrs}: {seller_info}")
                return seller_info
        
        # Si no encontramos con selectores, intentamos con regex
        seller_patterns = [
            re.compile(r'por\s+(.+)', re.IGNORECASE),
            re.compile(r'Vendido por\s+(.+)', re.IGNORECASE),
            re.compile(r'de\s+(.+)', re.IGNORECASE)
        ]
        
        for pattern in seller_patterns:
            for div in element.find_all(['div', 'span', 'p']):
                match = pattern.search(div.text)
                if match:
                    seller_info = match.group(1).strip()
                    # Quitar texto de tienda oficial
                    seller_info = re.sub(r'\s*Tienda\s*oficial.*$', '', seller_info)
                    logger.debug(f"Encontrado vendedor con regex: {seller_info}")
                    return seller_info
        
        # Si todavía no encontramos, buscar en atributos de datos o enlaces
        for a_tag in element.find_all('a', href=True):
            if 'tienda' in a_tag['href'] or 'seller' in a_tag['href']:
                logger.debug(f"Encontrado vendedor en URL: {a_tag.text.strip()}")
                return a_tag.text.strip()
        
        logger.warning("No se pudo extraer información del vendedor")
        return "No disponible"
    except Exception as e:
        logger.error(f"Error al extraer información del vendedor: {str(e)}")
        logger.error(traceback.format_exc())
        return "Error al extraer vendedor"

def extract_sales_count(element, get_from_detail=False, product_url=None):
    """
    Extrae la cantidad de ventas probando diferentes estructuras.
    Si get_from_detail es True, accede a la página de detalle del producto.
    """
    logger.debug("Intentando extraer cantidad de ventas...")
    
    try:
        # Intentar extraer ventas desde la tarjeta (como está en el código original)
        sales_patterns = [
            re.compile(r'(\d+)\s*vendido(s)?'),
            re.compile(r'Vendido(s)?\s*(\d+)'),
            re.compile(r'(\d+)\s*ventas'),
            re.compile(r'Más de\s*(\d+)\s*vendidos'),
            re.compile(r'(\d+)\+\s*vendidos')
        ]
        
        sales_selectors = [
            ('span', {'class': 'ui-search-sales__label'}),
            ('div', {'class': 'sales-info'}),
            ('span', {'class': 'item-sales'}),
            ('p', {'class': 'ui-search-seller-info'}),
            ('div', {'class': 'ui-search-item__info'})
        ]
        
        # Buscar con selectores en la tarjeta
        for tag, attrs in sales_selectors:
            sales_element = element.find(tag, attrs)
            if sales_element:
                sales_text = sales_element.text.strip()
                for pattern in sales_patterns:
                    match = pattern.search(sales_text)
                    if match:
                        group = match.group(1) if match.group(1) else match.group(2)
                        sales = int(group)
                        logger.debug(f"Encontradas {sales} ventas con selector {tag}, {attrs}")
                        return sales
        
        # Buscar en cualquier texto dentro del elemento
        for text_element in element.find_all(text=True):
            text = str(text_element).strip()
            for pattern in sales_patterns:
                match = pattern.search(text)
                if match:
                    group = match.group(1) if match.group(1) else (match.group(2) if len(match.groups()) > 1 else '0')
                    sales = int(group)
                    logger.debug(f"Encontradas {sales} ventas en texto")
                    return sales
                
        # Si no encontramos ventas y get_from_detail es True, acceder a la página de detalle
        if get_from_detail:
            # Usar URL pasada como parámetro o buscarla en el elemento
            product_link = product_url
            
            if not product_link:
                # Buscar el enlace al producto
                link_selectors = [
                    ('a', {'class': 'ui-search-item__group__element'}),
                    ('a', {'class': 'ui-search-link'}),
                    ('a', {'class': 'poly-component__title'}),
                    ('a', {'class': 'shops__item-link'})
                ]
                
                for tag, attrs in link_selectors:
                    link_element = element.find(tag, attrs)
                    if link_element and link_element.has_attr('href'):
                        product_link = link_element['href']
                        break
                        
                # Si no encontramos con selectores específicos, buscar cualquier enlace
                if not product_link:
                    for a_tag in element.find_all('a', href=True):
                        if 'MLA' in a_tag['href'] and '/p/' in a_tag['href']:
                            product_link = a_tag['href']
                            break
            
            if product_link:
                logger.debug(f"Accediendo a página de detalle: {product_link}")
                
                try:
                    # Usar caché para la página de detalle
                    detail_html = cached_request(product_link)
                    
                    # Analizar el HTML de la página de detalle
                    detail_soup = BeautifulSoup(detail_html, 'html.parser')
                    
                    # Buscar la cantidad de ventas en la página de detalle
                    # Selectores para la página de detalle
                    detail_selectors = [
                        ('span', {'class': 'ui-pdp-subtitle'}),
                        ('span', {'class': 'ui-pdp-header__stats-info'}),
                        ('div', {'class': 'ui-pdp-header__info-container'}),
                        ('div', {'class': 'ui-pdp-header__subtitle'})
                    ]
                    
                    for tag, attrs in detail_selectors:
                        detail_elements = detail_soup.find_all(tag, attrs)
                        for element in detail_elements:
                            text = element.text.strip()
                            for pattern in sales_patterns:
                                match = pattern.search(text)
                                if match:
                                    group = match.group(1) if match.group(1) else match.group(2)
                                    sales = int(group)
                                    logger.debug(f"Encontradas {sales} ventas en página de detalle")
                                    return sales
                    
                    # Buscar en toda la página por patrones de ventas
                    for text_element in detail_soup.find_all(text=True):
                        text = str(text_element).strip()
                        for pattern in sales_patterns:
                            match = pattern.search(text)
                            if match:
                                group = match.group(1) if match.group(1) else (match.group(2) if len(match.groups()) > 1 else '0')
                                sales = int(group)
                                logger.debug(f"Encontradas {sales} ventas en texto de página de detalle")
                                return sales
                                
                    logger.debug("No se encontraron ventas en la página de detalle")
                    
                    # Añade este tiempo de espera después de cada solicitud de detalle
                    random_delay()
                    
                except Exception as e:
                    logger.error(f"Error al acceder a la página de detalle: {str(e)}")
                    logger.error(traceback.format_exc())
        
        logger.debug("No se encontraron ventas")
        return 0
    
    except Exception as e:
        logger.error(f"Error al extraer cantidad de ventas: {str(e)}")
        logger.error(traceback.format_exc())
        return 0

def scrape_mercado_libre(search_query, exact_match=False, max_pages=None, seller_filter=None, min_price=0, min_sales=0, deep_sales_search=False, max_products=None):
    """Función principal de web scraping para Mercado Libre"""
    formatted_query = search_query.replace(' ', '-')
    
    # Usar valores de configuración si no se proporcionan
    if max_pages is None:
        max_pages = CONFIG['max_pages']
    if max_products is None:
        max_products = CONFIG['max_products']
    
    # Iniciar contador de tiempo
    start_time = time.time()
    
    products = []
    debug_info = []
    total_products_found = 0
    
    # Determinar si estamos buscando por tienda
    is_store_search = 'tienda/' in formatted_query or seller_filter is not None
    
    try:
        for page in range(max_pages):
            if len(products) >= max_products:
                logger.info(f"Se alcanzó el límite de {max_products} productos. Terminando búsqueda.")
                break
                
            offset = page * 50
            
            # Construir URL basada en tipo de búsqueda
            if is_store_search and 'tienda/' not in formatted_query:
                # URL para tienda específica
                url = f"https://listado.mercadolibre.com.ar/tienda/{formatted_query}/_OrderId_PRICE*DESC_NoIndex_True"
                logger.info(f"Búsqueda por tienda página {page + 1}: {url}")
            else:
                # URL normal de búsqueda
                url = f"https://listado.mercadolibre.com.ar/{formatted_query}_Desde_{offset + 1}_NoIndex_True"
                logger.info(f"Scrapeando página normal número {page + 1}: {url}")
            
            try:
                # Usar caché para la página de resultados
                html_content = cached_request(url)
                
                # Guardar HTML para debug si es necesario
                with open(f"debug_page_{page+1}.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
                
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Intentar diferentes estructuras de tarjetas
                cards = []
                card_selectors = [
                    # Selectores específicos para tiendas
                    ('li', {'class': 'ui-search-layout__item'}),
                    ('div', {'class': 'poly-card__content'}),
                    # Selectores generales
                    ('li', {'class': 'shops__layout-item'}),
                    ('div', {'class': 'ui-search-result__wrapper'}),
                    ('div', {'class': 'ui-search-result__content-wrapper'}),
                    # Selectores adicionales
                    ('div', {'class': 'store-items__layout-item'}),
                    ('div', {'class': 'store-items__result-wrapper'})
                ]
                
                for tag, attrs in card_selectors:
                    found_cards = soup.find_all(tag, attrs)
                    if found_cards:
                        logger.info(f"Encontrados {len(found_cards)} productos con selector {tag}, {attrs}")
                        cards.extend(found_cards)
                
                if not cards:
                    # Último intento - buscar cualquier contenedor que tenga información de productos
                    logger.warning("No se encontraron tarjetas con los selectores conocidos, intentando método alternativo")
                    possible_cards = soup.find_all('div', class_=lambda c: c and ('item' in c.lower() or 'product' in c.lower() or 'result' in c.lower()))
                    cards.extend(possible_cards)

                if not cards:
                    logger.error("No se encontraron productos en esta página")
                    # Intentar detectar si hay un mensaje de "no hay productos"
                    no_results = soup.find('div', {'class': 'ui-search-no-results'})
                    if no_results:
                        logger.warning("Página muestra explícitamente que no hay resultados")
                    break
                    
                logger.info(f"Total de {len(cards)} tarjetas encontradas en la página {page+1}")
                total_products_found += len(cards)

                for idx, card in enumerate(cards):
                    # Verificar si hemos alcanzado el límite de productos
                    if len(products) >= max_products:
                        logger.info(f"Se alcanzó el límite de {max_products} productos durante el procesamiento de tarjetas.")
                        break
                        
                    product_debug = {"index": idx, "success": False, "errors": []}
                    
                    try:
                        # Guardar HTML de la tarjeta para debug
                        with open(f"debug_card_{page+1}_{idx+1}.html", "w", encoding="utf-8") as f:
                            f.write(str(card))
                        
                        # Buscar el título
                        title = "Sin título"
                        link = ""
                        
                        # Intentar diferentes selectores para título y enlace
                        title_selectors = [
                            ('a', {'class': 'poly-component__title'}),
                            ('h2', {'class': 'ui-search-item__title'}),
                            ('h3', {'class': 'poly-component__title-wrapper'}),
                            ('h2', {'class': 'shops__item-title'}),
                            ('h2', {'class': 'ui-search-result-title'})
                        ]
                        
                        for tag, attrs in title_selectors:
                            title_tag = card.find(tag, attrs)
                            if title_tag:
                                # Si encontramos h3 con poly-component__title-wrapper, buscar el enlace a
                                if tag == 'h3' and 'poly-component__title-wrapper' in str(attrs.values()):
                                    a_tag = title_tag.find('a')
                                    if a_tag:
                                        title = a_tag.text.strip()
                                        if a_tag.has_attr('href'):
                                            link = a_tag['href']
                                else:
                                    title = title_tag.text.strip()
                                    # Intentar obtener el enlace
                                    if title_tag.name == 'a' and title_tag.has_attr('href'):
                                        link = title_tag['href']
                                    elif title_tag.parent and title_tag.parent.name == 'a' and title_tag.parent.has_attr('href'):
                                        link = title_tag.parent['href']
                                break
                        
                        # Si no se encontró título con los selectores, buscar cualquier enlace con título
                        if title == "Sin título":
                            for a_tag in card.find_all('a', href=True):
                                if a_tag.text.strip() and len(a_tag.text.strip()) > 10:
                                    title = a_tag.text.strip()
                                    link = a_tag['href']
                                    break
                        
                        product_debug["title"] = title
                        product_debug["link"] = link
                        
                        logger.debug(f"Producto {idx+1}: Título: {title}")
                        
                        # Aplicar filtro de coincidencia exacta
                        if exact_match:
                            similarity = difflib.SequenceMatcher(None, search_query.lower(), title.lower()).ratio()
                            if similarity < 0.7:
                                product_debug["skipped"] = "No cumple con coincidencia exacta"
                                continue
                        
                        # Extraer precio - OPTIMIZACIÓN: Verificar precio primero
                        price = extract_price_from_html(card)
                        product_debug["price"] = price
                        
                        # OPTIMIZACIÓN: Si el precio no cumple con el filtro, evitar buscar más información
                        if min_price > 0 and price < min_price:
                            product_debug["skipped"] = f"Precio {price} menor que mínimo {min_price}"
                            continue
                        
                        # Extraer imagen
                        img_tag = card.find('img')
                        image_link = ""
                        if img_tag:
                            for attr in ['data-src', 'src']:
                                if img_tag.get(attr):
                                    image_link = img_tag.get(attr)
                                    break
                        product_debug["image"] = image_link
                        
                        # Extraer vendedor - usar el seller_filter si está buscando en una tienda específica
                        if is_store_search and seller_filter:
                            seller_info = seller_filter
                        else:
                            seller_info = extract_seller_info(card)
                        product_debug["seller"] = seller_info
                        
                        # Aplicar filtro de vendedor antes de buscar ventas
                        if seller_filter and seller_filter.lower() not in seller_info.lower():
                            product_debug["skipped"] = f"No coincide con vendedor {seller_filter}"
                            continue
                        
                        # Extraer ventas - OPTIMIZACIÓN: Solo usar búsqueda profunda si es necesario
                        get_from_detail = deep_sales_search or (min_sales > 0)
                        sales_count = extract_sales_count(card, get_from_detail=get_from_detail, product_url=link)
                        product_debug["sales"] = sales_count
                        
                        # Aplicar filtro de ventas
                        if min_sales > 0 and sales_count < min_sales:
                            product_debug["skipped"] = f"Ventas {sales_count} menor que mínimo {min_sales}"
                            continue
                        
                        # Si hemos llegado hasta aquí, el producto cumple todos los filtros
                        product_data = {
                            'title': title,
                            'price': price,
                            'seller': seller_info,
                            'sales': sales_count,
                            'link': link,
                            'image': image_link
                        }
                        
                        products.append(product_data)
                        product_debug["success"] = True
                        logger.info(f"Añadido producto: {title} - ${price} - Vendedor: {seller_info} - Ventas: {sales_count}")
                        
                    except Exception as e:
                        error_msg = f"Error al procesar producto {idx+1}: {str(e)}"
                        product_debug["errors"].append(error_msg)
                        logger.error(error_msg, exc_info=True)
                    
                    # Añadir información de depuración
                    debug_info.append(product_debug)

                # Pausa entre páginas para evitar ser bloqueado
                random_delay()

            except Exception as e:
                logger.error(f"Error en el scraping de la página {page+1}: {str(e)}", exc_info=True)
                logger.error(traceback.format_exc())
                break
    finally:
        # Calcular tiempo total de ejecución
        execution_time = time.time() - start_time
        
        # Añadir información de rendimiento
        performance_data = {
            "execution_time": execution_time,
            "total_products_found": total_products_found,
            "total_products_processed": len(products),
            "pages_scraped": page + 1 if 'page' in locals() else 0
        }
        
        # Guardar información de depuración y rendimiento
        with open("debug_info.json", "w", encoding="utf-8") as f:
            debug_data = {
                "performance": performance_data,
                "products": debug_info,
                "config": {
                    "search_query": search_query,
                    "exact_match": exact_match,
                    "max_pages": max_pages,
                    "seller_filter": seller_filter,
                    "min_price": min_price,
                    "min_sales": min_sales,
                    "deep_sales_search": deep_sales_search,
                    "max_products": max_products
                }
            }
            json.dump(debug_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Scraping completado en {execution_time:.2f} segundos. Encontrados {len(products)} productos de {total_products_found} analizados.")
    
    return products, performance_data

def analyze_products(products):
    if not products:
        return {
            "cheapest": None,
            "most_expensive": None,
            "average_price": 0,
            "total_products": 0,
            "total_sales": 0
        }

    # Filtrar productos con precio mayor a cero
    valid_products = [p for p in products if p['price'] > 0]
    
    if not valid_products:
        return {
            "cheapest": None,
            "most_expensive": None,
            "average_price": 0,
            "total_products": len(products),
            "total_sales": sum(p.get('sales', 0) for p in products)
        }

    cheapest = min(valid_products, key=lambda x: x['price'])
    most_expensive = max(valid_products, key=lambda x: x['price'])
    total_price = sum(product['price'] for product in valid_products)
    average_price = total_price / len(valid_products)
    total_sales = sum(p.get('sales', 0) for p in products)

    return {
        "cheapest": cheapest,
        "most_expensive": most_expensive,
        "average_price": int(average_price),
        "total_products": len(products),
        "total_sales": total_sales
    }

def export_to_csv(products, filename):
    if not os.path.exists('exports'):
        os.makedirs('exports')

    filepath = os.path.join('exports', filename)

    with open(filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['title', 'price', 'seller', 'sales', 'link', 'image'])
        writer.writeheader()
        for product in products:
            writer.writerow(product)

    return filepath

def export_to_excel(products, filename):
    if not os.path.exists('exports'):
        os.makedirs('exports')

    filepath = os.path.join('exports', filename)

    df = pd.DataFrame(products)
    df.to_excel(filepath, index=False)

    return filepath

@app.route('/')
def index():
    return render_template('index.html', config=CONFIG)

@app.route('/update_config', methods=['POST'])
def update_config():
    """Actualiza la configuración global del scraper"""
    try:
        # Actualizar la configuración con los valores del formulario
        CONFIG['max_products'] = int(request.form.get('max_products', CONFIG['max_products']))
        CONFIG['max_pages'] = int(request.form.get('max_pages', CONFIG['max_pages']))
        CONFIG['delay_min'] = float(request.form.get('delay_min', CONFIG['delay_min']))
        CONFIG['delay_max'] = float(request.form.get('delay_max', CONFIG['delay_max']))
        CONFIG['deep_sales_search'] = request.form.get('deep_sales_search') == 'on'
        
        logger.info(f"Configuración actualizada: {CONFIG}")
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error al actualizar configuración: {str(e)}")
        return render_template('index.html', error=f'Error al actualizar configuración: {str(e)}', config=CONFIG)

@app.route('/search', methods=['POST'])
def search():
    search_query = request.form.get('search_query', '')
    exact_match = request.form.get('exact_match') == 'on'
    seller_filter = request.form.get('seller_filter', '')
    deep_sales_search = request.form.get('deep_sales_search') == 'on'
    
    # Convertir a entero o usar 0 si está vacío o no es un número
    try:
        min_price = int(request.form.get('min_price', '0'))
    except ValueError:
        min_price = 0
        
    try:
        min_sales = int(request.form.get('min_sales', '0'))
    except ValueError:
        min_sales = 0
        
    try:
        max_products = int(request.form.get('max_products', CONFIG['max_products']))
    except ValueError:
        max_products = CONFIG['max_products']
        
    try:
        max_pages = int(request.form.get('max_pages', CONFIG['max_pages']))
    except ValueError:
        max_pages = CONFIG['max_pages']

    if not search_query:
        return render_template('index.html', error='Por favor ingresa un término de búsqueda', config=CONFIG)

    try:
        logger.info(f"Iniciando búsqueda para: '{search_query}'")
        logger.info(f"Parámetros: exact_match={exact_match}, seller_filter='{seller_filter}', min_price={min_price}, min_sales={min_sales}, max_products={max_products}, max_pages={max_pages}, deep_sales_search={deep_sales_search}")
        
        # Inicio del tiempo de ejecución
        start_time = time.time()
        
        products, performance = scrape_mercado_libre(
            search_query=search_query, 
            exact_match=exact_match,
            max_pages=max_pages,
            seller_filter=seller_filter,
            min_price=min_price,
            min_sales=min_sales,
            deep_sales_search=deep_sales_search,
            max_products=max_products
        )
        
        # Cálculo del tiempo total
        execution_time = time.time() - start_time

        if not products:
            logger.warning(f"No se encontraron productos para la búsqueda: '{search_query}'")
            return render_template('index.html', 
                                  error='No se encontraron productos. Intenta con otros parámetros de búsqueda.',
                                  search_query=search_query,
                                  config=CONFIG,
                                  execution_time=execution_time)

        analysis = analyze_products(products)
        logger.info(f"Búsqueda completada: {len(products)} productos encontrados en {execution_time:.2f} segundos")

        return render_template('results.html', 
                              products=products, 
                              analysis=analysis,
                              search_query=search_query,
                              seller_filter=seller_filter,
                              min_price=min_price,
                              min_sales=min_sales,
                              products_json=json.dumps(products),
                              performance=performance,
                              execution_time=execution_time)
    except Exception as e:
        logger.error(f"Error en la búsqueda: {str(e)}", exc_info=True)
        logger.error(traceback.format_exc())
        return render_template('index.html', 
                              error=f'Error al realizar la búsqueda: {str(e)}',
                              search_query=search_query,
                              config=CONFIG)

@app.route('/export', methods=['POST'])
def export():
    export_type = request.form.get('export_type')
    products_data = request.form.get('products_data')
    search_query = request.form.get('search_query', 'productos')

    if not products_data:
        return redirect(url_for('index'))

    try:
        products = json.loads(products_data)
        filename = f"mercado_libre_{search_query.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if export_type == 'csv':
            filepath = export_to_csv(products, f"{filename}.csv")
            return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

        elif export_type == 'excel':
            filepath = export_to_excel(products, f"{filename}.xlsx")
            return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error al exportar datos: {str(e)}", exc_info=True)
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Error al exportar: {str(e)}"}), 500

@app.route('/search_by_seller', methods=['GET', 'POST'])
def search_by_seller():
    if request.method == 'POST':
        seller_name = request.form.get('seller_name', '').strip()
        deep_sales_search = request.form.get('deep_sales_search') == 'on'
        
        try:
            min_price = int(request.form.get('min_price', '0'))
        except ValueError:
            min_price = 0
            
        try:
            min_sales = int(request.form.get('min_sales', '0'))
        except ValueError:
            min_sales = 0
            
        try:
            max_products = int(request.form.get('max_products', CONFIG['max_products']))
        except ValueError:
            max_products = CONFIG['max_products']
            
        try:
            max_pages = int(request.form.get('max_pages', CONFIG['max_pages']))
        except ValueError:
            max_pages = CONFIG['max_pages']
        
        if not seller_name:
            return render_template('search_by_seller.html', error='Por favor ingresa un nombre de vendedor', config=CONFIG)
        
        logger.info(f"Iniciando búsqueda por vendedor: '{seller_name}'")
        logger.info(f"Parámetros: min_price={min_price}, min_sales={min_sales}, max_products={max_products}, max_pages={max_pages}, deep_sales_search={deep_sales_search}")
        
        try:
            # Inicio del tiempo de ejecución
            start_time = time.time()
            
            seller_products, performance = scrape_mercado_libre(
                search_query=f"tienda/{seller_name}",  # Usar formato tienda/nombre
                exact_match=False,                    # No requerir coincidencia exacta
                max_pages=max_pages,                  # Máximo de páginas a scrapear
                seller_filter=seller_name,            # Filtrar por nombre de vendedor
                min_price=min_price,                  # Precio mínimo
                min_sales=min_sales,                  # Ventas mínimas
                deep_sales_search=deep_sales_search,  # Búsqueda profunda de ventas
                max_products=max_products             # Máximo de productos a devolver
            )
            
            # Cálculo del tiempo total
            execution_time = time.time() - start_time
            
            if not seller_products:
                logger.warning(f"No se encontraron productos para el vendedor: {seller_name}")
                return render_template('search_by_seller.html', 
                                      error='No se encontraron productos para este vendedor.',
                                      seller_name=seller_name,
                                      config=CONFIG,
                                      execution_time=execution_time)
            
            analysis = analyze_products(seller_products)
            logger.info(f"Búsqueda por vendedor completada: {len(seller_products)} productos encontrados en {execution_time:.2f} segundos")
            
            return render_template('seller_results.html',
                                  products=seller_products,
                                  analysis=analysis,
                                  seller_name=seller_name,
                                  min_price=min_price,
                                  min_sales=min_sales,
                                  products_json=json.dumps(seller_products),
                                  performance=performance,
                                  execution_time=execution_time)
                                  
        except Exception as e:
            logger.error(f"Error en la búsqueda por vendedor: {str(e)}", exc_info=True)
            logger.error(traceback.format_exc())
            return render_template('search_by_seller.html', 
                                  error=f'Error al realizar la búsqueda: {str(e)}',
                                  seller_name=seller_name,
                                  config=CONFIG)
    else:
        return render_template('search_by_seller.html', config=CONFIG)

@app.route('/debug_info')
def debug_info():
    try:
        with open("debug_info.json", "r", encoding="utf-8") as f:
            debug_data = json.load(f)
        return render_template('debug.html', debug_data=debug_data)
    except Exception as e:
        logger.error(f"Error al cargar información de depuración: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error al cargar información de depuración: {str(e)}"}), 500

@app.route('/clear_cache')
def clear_cache():
    """Limpia la caché de solicitudes HTTP"""
    try:
        cached_request.cache_clear()
        logger.info("Cache limpiada correctamente")
        return jsonify({"success": True, "message": "Cache limpiada correctamente"})
    except Exception as e:
        logger.error(f"Error al limpiar la cache: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    Timer(1, open_browser).start()
    app.run(debug=True)
