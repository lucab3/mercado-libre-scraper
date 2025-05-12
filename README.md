# Mercado Libre Web Scraper

Una aplicación web para realizar web scraping en Mercado Libre, permitiendo buscar productos, analizar precios y exportar resultados a CSV o Excel.

## Características

- Búsqueda de productos por nombre en Mercado Libre
- Búsqueda por coincidencia exacta o aproximada
- Filtrado por vendedor, precio mínimo y ventas mínimas
- Búsqueda específica por vendedor/tienda
- Visualización del producto más caro y más barato
- Cálculo de precio promedio sugerido para publicación
- Exportación de resultados a CSV o Excel
- Sistema de logs detallado para depuración
- Interfaz web amigable
- Compatible con Windows, macOS y Linux

## Estructura del Proyecto

```
mercado-libre-scraper/
│
├── app.py                 # Aplicación principal Flask
├── requirements.txt       # Dependencias del proyecto
├── README.md              # Documentación
│
├── templates/             # Plantillas HTML
│   ├── index.html         # Página de inicio con formulario de búsqueda
│   ├── results.html       # Página de resultados
│   ├── seller_results.html # Página de resultados por vendedor
│   ├── search_by_seller.html # Página de búsqueda por vendedor
│   └── debug.html         # Página de depuración
│
├── exports/               # Carpeta donde se guardan los archivos exportados
│   ├── mercado_libre_*.csv
│   └── mercado_libre_*.xlsx
│
└── logs/                  # Archivos de log (se crean automáticamente)
    └── scraper_debug.log
```

## Requisitos

- Python 3.7 o superior
- pip (gestor de paquetes de Python)
- Conexión a Internet

## Instalación

1. Clona este repositorio o descárgalo como ZIP:

```bash
git clone https://github.com/tuusuario/mercado-libre-scraper.git
cd mercado-libre-scraper
```

2. Crea un entorno virtual (opcional pero recomendado):

```bash
# En Windows
python -m venv venv
venv\Scripts\activate

# En macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

3. Instala las dependencias:

```bash
pip install -r requirements.txt
```

## Dependencias Principales

```
flask
requests
beautifulsoup4
pandas
openpyxl
```

## Uso

1. Ejecuta la aplicación:

```bash
python app.py
```

2. Tu navegador web se abrirá automáticamente mostrando la interfaz de la aplicación (http://127.0.0.1:5000/).

3. Para búsqueda por producto:
   - Ingresa el nombre del producto
   - Opcionalmente, aplica filtros como coincidencia exacta, vendedor específico, precio mínimo o ventas mínimas
   - Haz clic en "Buscar"

4. Para búsqueda por vendedor:
   - Navega a la sección "Buscar por vendedor"
   - Ingresa el nombre del vendedor o tienda
   - Opcionalmente, configura filtros de precio mínimo y ventas mínimas
   - Haz clic en "Buscar"

5. Explora los resultados:
   - Visualiza el producto más barato y el más caro
   - Consulta el precio promedio sugerido
   - Revisa el total de productos y ventas
   - Examina la lista completa de productos encontrados

6. Exporta los resultados a CSV o Excel utilizando el formulario de exportación.

7. Para depuración, puedes acceder a la página de información de depuración.

## Características Avanzadas

### Extracción Inteligente de Datos

El scraper utiliza múltiples métodos para extraer información:
- Búsqueda mediante selectores CSS especializados
- Estrategias de extracción alternativas cuando la estructura cambia
- Expresiones regulares para datos que no siguen un patrón estándar
- Manejo de diferentes formatos de precio y ventas

### Sistema de Depuración

- Logs detallados guardados en archivos
- Guardado de HTML de páginas y tarjetas individuales para análisis
- Información de depuración accesible desde la interfaz web

## Notas Importantes

- La aplicación utiliza web scraping, lo que implica que está sujeta a cambios en la estructura del sitio de Mercado Libre. Si deja de funcionar, puede ser necesario actualizar el código.
- Se implementan pausas entre solicitudes para evitar limitaciones temporales de acceso.
- Esta aplicación es solo para fines educativos y personales. Respeta los términos de servicio de Mercado Libre.

## Solución de Problemas

### No se encuentran productos

- Intenta con términos de búsqueda más generales
- Verifica tu conexión a Internet
- Asegúrate de que el sitio de Mercado Libre esté disponible
- Revisa los logs de depuración para más información

### Error al exportar archivos

- Verifica que tengas permisos de escritura en el directorio de la aplicación
- Cierra cualquier archivo Excel o CSV que pueda estar bloqueando la escritura
- Comprueba que la carpeta 'exports' exista o tenga permisos adecuados

### La aplicación no inicia

- Verifica que todas las dependencias estén instaladas correctamente
- Asegúrate de tener una versión compatible de Python
- Revisa los mensajes de error en la consola

## Contribuir

Si deseas contribuir a este proyecto, puedes:

1. Hacer un fork del repositorio
2. Crear una rama para tu función (`git checkout -b feature/nueva-funcion`)
3. Realizar tus cambios y commits (`git commit -am 'Añade nueva función'`)
4. Subir la rama (`git push origin feature/nueva-funcion`)
5. Crear un Pull Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT. Consulta el archivo LICENSE para más detalles.
