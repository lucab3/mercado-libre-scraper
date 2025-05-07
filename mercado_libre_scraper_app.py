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
import json

app = Flask(__name__)

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')

def scrape_mercado_libre(search_query, exact_match=False, max_pages=5):
    formatted_query = search_query.replace(' ', '-')
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }

    products = []

    for page in range(max_pages):
        offset = page * 50
        url = f"https://listado.mercadolibre.com.ar/{formatted_query}_Desde_{offset + 1}_NoIndex_True"
        print(f"\nScrapeando página número {page + 1}. {url}")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Nueva estructura de tarjetas
            cards = soup.find_all('div', class_='poly-card__content')

            if not cards:
                print("No se encontraron más productos.")
                break

            for card in cards:
                try:
                    title_tag = card.find('a', class_='poly-component__title')
                    title = title_tag.text.strip() if title_tag else "Sin título"
                    link = title_tag['href'] if title_tag and title_tag.has_attr('href') else ""

                    if exact_match:
                        similarity = difflib.SequenceMatcher(None, search_query.lower(), title.lower()).ratio()
                        if similarity < 0.7:
                            continue

                    price_div = card.find('div', class_='poly-price__current')
                    price_text = price_div.text.strip().replace('$', '').replace('.', '') if price_div else "0"
                    price = int(price_text) if price_text.isdigit() else 0

                    img_tag = card.find('img')
                    image_link = img_tag.get("data-src") or img_tag.get("src") if img_tag else ""

                    products.append({
                        'title': title,
                        'price': price,
                        'seller': "",  # Información de vendedor no disponible en esta estructura
                        'link': link,
                        'image': image_link
                    })
                except Exception as e:
                    print(f"Error al procesar un post: {e}")
                    continue

            time.sleep(1)

        except Exception as e:
            print(f"Error en el scraping: {e}")
            break

    return products

def analyze_products(products):
    if not products:
        return {
            "cheapest": None,
            "most_expensive": None,
            "average_price": 0
        }

    cheapest = min(products, key=lambda x: x['price'])
    most_expensive = max(products, key=lambda x: x['price'])
    total_price = sum(product['price'] for product in products)
    average_price = total_price / len(products) if products else 0

    return {
        "cheapest": cheapest,
        "most_expensive": most_expensive,
        "average_price": int(average_price)
    }

def export_to_csv(products, filename):
    if not os.path.exists('exports'):
        os.makedirs('exports')

    filepath = os.path.join('exports', filename)

    with open(filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['title', 'price', 'seller', 'link', 'image'])
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
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
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
                          search_query=search_query,
                          products_json=json.dumps(products))

@app.route('/export', methods=['POST'])
def export():
    export_type = request.form.get('export_type')
    products_data = request.form.get('products_data')
    search_query = request.form.get('search_query', 'productos')

    if not products_data:
        return redirect(url_for('index'))

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
    Timer(1, open_browser).start()
    app.run(debug=True)
