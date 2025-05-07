# Mercado Libre Web Scraper

Una aplicación para realizar web scraping en Mercado Libre, permitiendo buscar productos, analizar precios y exportar resultados a CSV o Excel.

## Características

- Búsqueda de productos por nombre en Mercado Libre
- Búsqueda por coincidencia exacta o similitud
- Visualización del producto más caro y más barato
- Cálculo de precio promedio sugerido para publicación
- Exportación de resultados a CSV o Excel
- Interfaz web amigable
- Compatible con Windows y macOS

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
│   └── results.html       # Página de resultados
│
└── exports/               # Carpeta donde se guardan los archivos exportados (se crea automáticamente)
    ├── mercado_libre_*.csv
    └── mercado_libre_*.xlsx
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

## Uso

1. Ejecuta la aplicación:

```bash
python app.py
```

2. Tu navegador web se abrirá automáticamente mostrando la interfaz de la aplicación (http://127.0.0.1:5000/).

3. Ingresa el nombre del producto que deseas buscar en el formulario.

4. Opcionalmente, marca la casilla "Buscar coincidencia exacta" si deseas resultados más precisos.

5. Haz clic en "Buscar" para iniciar la búsqueda.

6. Explora los resultados:
   - Visualiza el producto más barato y el más caro
   - Consulta el precio promedio sugerido para publicación
   - Revisa todos los productos encontrados

7. Exporta los resultados a CSV o Excel utilizando el formulario de exportación.

## Notas Importantes

- La aplicación utiliza web scraping, lo que implica que está sujeta a cambios en la estructura del sitio web de Mercado Libre. Si la aplicación deja de funcionar correctamente, es posible que sea necesario actualizar el código de scraping.
- El uso excesivo de web scraping puede resultar en limitaciones temporales de acceso al sitio. La aplicación incluye pausas entre solicitudes para minimizar este riesgo.
- Esta aplicación es solo para fines educativos y personales. Respeta los términos de servicio de Mercado Libre.

## Solución de Problemas

### No se encuentran productos

- Intenta con términos de búsqueda más generales
- Verifica tu conexión a Internet
- Asegúrate de que el sitio de Mercado Libre esté disponible

### Error al exportar archivos

- Verifica que tengas permisos de escritura en el directorio de la aplicación
- Cierra cualquier archivo Excel o CSV que pueda estar bloqueando la escritura

### La aplicación no inicia

- Verifica que todas las dependencias estén instaladas correctamente
- Asegúrate de tener una versión compatible de Python

## Contribuir

Si deseas contribuir a este proyecto, puedes:

1. Hacer un fork del repositorio
2. Crear una rama para tu función (`git checkout -b feature/nueva-funcion`)
3. Realizar tus cambios y commits (`git commit -am 'Añade nueva función'`)
4. Subir la rama (`git push origin feature/nueva-funcion`)
5. Crear un Pull Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT. Consulta el archivo LICENSE para más detalles.
