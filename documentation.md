# Documentación Técnica: Web Scraper para Mercado Libre

## Descripción General

Esta aplicación es un web scraper para Mercado Libre que permite buscar productos por nombre, analizar sus precios y exportar los resultados. La aplicación está desarrollada en Python utilizando Flask para la interfaz web y BeautifulSoup para el scraping de datos.

## Tecnologías Utilizadas

- **Python**: Lenguaje de programación principal
- **Flask**: Framework web para la interfaz de usuario
- **BeautifulSoup**: Biblioteca para web scraping
- **Requests**: Biblioteca para realizar peticiones HTTP
- **Pandas**: Para manipulación y exportación de datos
- **Bootstrap**: Framework CSS para el diseño de la interfaz

## Arquitectura de la Aplicación

### Componentes Principales

1. **Servidor Web (Flask)**
   - Gestiona las rutas y las solicitudes HTTP
   - Renderiza las plantillas HTML
   - Maneja la lógica de la aplicación

2. **Motor de Scraping**
   - Realiza las solicitudes a Mercado Libre
   - Extrae los datos de los productos
   - Analiza y procesa la información obtenida

3. **Sistema de Exportación**
   - Convierte los datos a formatos CSV y Excel
   - Genera archivos descargables

### Flujo de Datos

1. El usuario ingresa un término de búsqueda
2. La aplicación envía una solicitud a Mercado Libre
3. Se extraen los datos de los productos encontrados
4. Se procesan y analizan los datos (producto más caro, más barato, promedio)
5. Se muestran los resultados al usuario
6. Opcionalmente, se exportan los datos a un archivo

## Descripción Detallada de Funciones

### `scrape_mercado_libre(search_query, exact_match=False)`

Esta función realiza el scraping de productos en Mercado Libre.

#### Parámetros:
- `search_query` (str): Término de búsqueda
- `exact_match` (bool): Si es True, busca coincidencias exactas usando similitud de texto

#### Proceso:
1. Formatea la consulta para la URL
2. Realiza una petición HTTP a Mercado Libre
3. Parsea el HTML con BeautifulSoup
4. Extrae los datos de cada producto encontrado
5. Si se solicita coincidencia exacta, filtra los resultados por similitud
6. Devuelve una lista de productos con sus datos

### `analyze_products(products)`

Analiza los productos para encontrar el más caro, el más barato y el promedio.

#### Parámetros:
- `products` (list): Lista de productos

#### Devuelve:
- Un diccionario con el producto más barato, el más caro y el precio promedio

### `export_to_csv(products, filename)` y `export_to_excel(products, filename)`

Exportan los productos a archivos CSV o Excel respectivamente.

#### Parámetros:
- `products` (list): Lista de productos
- `filename` (str): Nombre del archivo

#### Devuelve:
- La ruta del archivo exportado

### Rutas Flask

- **/** (GET): Renderiza la página principal con el formulario de búsqueda
- **/search** (POST): Procesa la búsqueda y muestra los resultados
- **/export** (POST): Exporta los resultados a un archivo CSV o Excel

## Estructura de Carpetas

```
mercado-libre-scraper/
│
├── app.py                 # Aplicación principal Flask
├── requirements.txt       # Dependencias del proyecto
├── README.md              # Documentación para usuarios
├── DOCUMENTACION.md       # Documentación técnica
│
├── templates/             # Plantillas HTML
│   ├── index.html         # Página de inicio con formulario de búsqueda
│   └── results.html       # Página de resultados
│
└── exports/               # Carpeta donde se guardan los archivos exportados (se c