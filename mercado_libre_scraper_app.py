import os
import csv
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_file, redirect, url_for
from datetime import datetime
import re
import difflib
import webbrowser
from threading import Timer
import platform

app = Flask(__name__)

def open_browser():
    """Abre el navegador automáticamente cuando la aplicación inicia"""
    webbrowser.open_new('http://127.0.0.1:5000/')

def scrape_mercado_libre(search_query, exact_match=False, max_pages=5):
    """
    Realiza scraping de productos en Mercado Libre con paginación.
    
    Args:
        search_query (str): Término de búsqueda
        exact_match (bool): Si es True, busca coincidencias exactas
        max_pages (int): Número máximo de páginas a recorrer
        
    Returns:
        list: Lista de productos encontrados
    """
    formatted_query = search_query.replace(' ', '-')
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }

    products = []
    page_number = 0

    for page in range(max_pages):
        offset = page_number * 50
        url = f"https://listado.mercadolibre.com.ar/{formatted_query}_Desde_{offset + 1}_NoIndex_True"

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            items = soup.find_all('div', class_='ui-search-result__wrapper')

            if not items:
                break

            for item in items:
                try:
                    title_element = item.find('h2', class_='ui-search-item__title')
                    price_element = item.find('span', class_='andes-money-amount__fraction')
                    seller_element = item.find('span', class_='ui-search-official-store-label')
                    link_element = item.find('a', class_='ui-search-item__group__element')

                    if title_element and price_element:
                        title = title_element.text.strip()
                        if exact_match:
                            similarity = difflib.SequenceMatcher(None, search_query.lower(), title.lower()).ratio()
                            if similarity < 0.7:
                                continue

                        price_text = price_element.text.strip().replace('.', '')
                        price = int(price_text) if price_text.isdigit() else 0
                        seller = seller_element.text.strip() if seller_element else "Vendedor particular"
                        link = link_element['href'] if link_element else ""

                        products.append({
                            'title': title,
                            'price': price,
                            'seller': seller,
                            'link': link
                        })
                except Exception as e:
                    print(f"Error al procesar un item: {e}")
                    continue

            page_number += 1
            time.sleep(1)
        except Exception as e:
            print(f"Error en el scraping: {e}")
            break

    return products
    
def analyze_products(products):
    """
    Analiza los productos para encontrar el más caro, el más barato y el promedio
    
    Args:
        products (list): Lista de productos
        
    Returns:
        dict: Resultados del análisis
    """
    if not products:
        return {
            "cheapest": None,
            "most_expensive": None,
            "average_price": 0
        }
    
    # Encontrar el producto más barato
    cheapest = min(products, key=lambda x: x['price'])
    
    # Encontrar el producto más caro
    most_expensive = max(products, key=lambda x: x['price'])
    
    # Calcular el precio promedio
    total_price = sum(product['price'] for product in products)
    average_price = total_price / len(products) if products else 0
    
    return {
        "cheapest": cheapest,
        "most_expensive": most_expensive,
        "average_price": int(average_price)
    }

def export_to_csv(products, filename):
    """
    Exporta los productos a un archivo CSV
    
    Args:
        products (list): Lista de productos
        filename (str): Nombre del archivo
        
    Returns:
        str: Ruta del archivo exportado
    """
    if not os.path.exists('exports'):
        os.makedirs('exports')
    
    filepath = os.path.join('exports', filename)
    
    with open(filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['title', 'price', 'seller', 'link'])
        writer.writeheader()
        for product in products:
            writer.writerow(product)
    
    return filepath

def export_to_excel(products, filename):
    """
    Exporta los productos a un archivo Excel
    
    Args:
        products (list): Lista de productos
        filename (str): Nombre del archivo
        
    Returns:
        str: Ruta del archivo exportado
    """
    if not os.path.exists('exports'):
        os.makedirs('exports')
    
    filepath = os.path.join('exports', filename)
    
    df = pd.DataFrame(products)
    df.to_excel(filepath, index=False)
    
    return filepath

@app.route('/')
def index():
    """Renderiza la página principal"""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    """Maneja la búsqueda de productos"""
    search_query = request.form.get('search_query', '')
    exact_match = request.form.get('exact_match') == 'on'
    
    if not search_query:
        return render_template('index.html', error='Por favor ingresa un término de búsqueda')
    
    products = scrape_mercado_libre(search_query, exact_match)
    
    if not products:
        return render_template('index.html', 
                              error='No se encontraron productos. Intenta con otro término de búsqueda.',
                              search_query=search_query)
    
    analysis = analyze_products(products)
    
    return render_template('results.html', 
                          products=products, 
                          analysis=analysis,
                          search_query=search_query)

@app.route('/export', methods=['POST'])
def export():
    """Maneja la exportación de datos"""
    export_type = request.form.get('export_type')
    products_data = request.form.get('products_data')
    search_query = request.form.get('search_query', 'productos')
    
    if not products_data:
        return redirect(url_for('index'))
    
    # Convertir la cadena JSON de vuelta a una lista de diccionarios
    import json
    products = json.loads(products_data)
    
    filename = f"mercado_libre_{search_query.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    if export_type == 'csv':
        filepath = export_to_csv(products, f"{filename}.csv")
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    
    elif export_type == 'excel':
        filepath = export_to_excel(products, f"{filename}.xlsx")
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Abre el navegador automáticamente
    Timer(1, open_browser).start()
    # Inicia la aplicación Flask
    app.run(debug=True)
