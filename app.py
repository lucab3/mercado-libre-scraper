import os
import csv
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify
from datetime import datetime, timedelta
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
import uuid

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
    'max_products': 20,              # Número máximo de productos a buscar
    'max_pages': 2,                  # Número máximo de páginas a buscar
    'delay_min': 1.0,                # Tiempo mínimo entre solicitudes (segundos)
    'delay_max': 2.5,                # Tiempo máximo entre solicitudes (segundos)
    'cache_ttl': 3600,               # Tiempo de vida de la caché (1 hora)
    'deep_sales_search': False,      # Por defecto no usar búsqueda profunda de ventas
    'max_requests_per_minute': 15,   # Límite de solicitudes por minuto
    'cache_file': 'request_cache.json',  # Archivo de caché
    'use_adaptive_delay': True,      # Activar retraso adaptativo
    'enable_proxy': False,           # Activar rotación de IPs
    'proxy_config': {                # Configuración de proxies
        'type': 'none',              # 'none', 'list', 'service'
        'list': [],                  # Lista manual de proxies
        'service_name': '',          # Nombre del servicio (brightdata, smartproxy, etc.)
        'api_key': '',               # API key del servicio
        'username': ''               # Usuario del servicio
    },
    'scheduler_enabled': False,      # Activar programador de tareas
    'low_traffic_hours': {           # Horas de bajo tráfico (0-23)
        'start': 22,                 # Hora de inicio (22:00)
        'end': 6                     # Hora de fin (06:00)
    }
}

# Variables globales para los componentes
request_manager = None
proxy_manager = None
task_scheduler = None
adaptive_delay = None

class AdaptiveDelay:
    """
    Gestiona retrasos adaptativos basados en el comportamiento del servidor.
    Incrementa automáticamente los tiempos de espera si detecta señales de bloqueo.
    """
    def __init__(self, min_delay=1.0, max_delay=3.0, backoff_factor=1.5, max_backoff=30):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.current_min = min_delay
        self.current_max = max_delay
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self.consecutive_errors = 0
        self.request_count = 0
        self.last_request_time = 0
        
    def get_delay(self):
        """Calcula el tiempo de espera basado en el estado actual"""
        # Si hemos tenido errores consecutivos, aumentar el retraso
        if self.consecutive_errors > 0:
            delay = min(
                self.current_min * (self.backoff_factor ** self.consecutive_errors),
                self.max_backoff
            )
            return random.uniform(delay, delay * 1.25)
        
        # Retraso normal aleatorio
        return random.uniform(self.current_min, self.current_max)
    
    def success(self):
        """Registrar una solicitud exitosa"""
        self.request_count += 1
        self.consecutive_errors = 0
        
        # Cada 20 solicitudes exitosas, reducir ligeramente los tiempos (si están elevados)
        if self.request_count % 20 == 0 and self.current_min > self.min_delay:
            self.current_min = max(self.current_min * 0.9, self.min_delay)
            self.current_max = max(self.current_max * 0.9, self.max_delay)
        
    def error(self, error_type=None):
        """Registrar un error y ajustar los retrasos"""
        self.consecutive_errors += 1
        
        # Aumentar los tiempos de retraso
        self.current_min = min(self.current_min * self.backoff_factor, self.max_backoff/2)
        self.current_max = min(self.current_max * self.backoff_factor, self.max_backoff)
        
        # Si recibimos muchos errores consecutivos, podemos implementar una pausa larga
        if self.consecutive_errors >= 5:
            logger.warning(f"Detectados {self.consecutive_errors} errores consecutivos. Implementando pausa larga.")
            return True
        return False
    
    def should_pause(self):
        """Determina si debemos hacer una pausa larga en las solicitudes"""
        return self.consecutive_errors >= 5

class ProxyManager:
    """
    Gestiona una lista de proxies para rotación de IPs.
    Se puede implementar con diferentes proveedores.
    """
    def __init__(self, proxy_config=None):
        self.proxy_config = proxy_config or {}
        self.proxy_list = []
        self.current_index = 0
        self.proxy_errors = {}  # Tracking de errores por proxy
        self.enabled = False
        
        # Inicializar según configuración
        self._initialize()
        
    def _initialize(self):
        """Inicializa el gestor de proxies según configuración"""
        proxy_type = self.proxy_config.get('type', 'none')
        
        if proxy_type == 'none':
            logger.info("Rotación de IPs desactivada")
            self.enabled = False
            return
            
        elif proxy_type == 'list':
            # Lista manual de proxies
            self.proxy_list = self.proxy_config.get('list', [])
            logger.info(f"Inicializado gestor de proxies con {len(self.proxy_list)} proxies manuales")
            
        elif proxy_type == 'service':
            # Servicio externo de proxies
            service_name = self.proxy_config.get('service_name')
            api_key = self.proxy_config.get('api_key')
            
            if service_name and api_key:
                try:
                    self._load_from_service(service_name, api_key)
                except Exception as e:
                    logger.error(f"Error al cargar proxies del servicio {service_name}: {str(e)}")
            else:
                logger.error("Configuración incompleta para servicio de proxies")
                self.enabled = False
                return
        
        # Verificar si tenemos proxies disponibles
        if len(self.proxy_list) > 0:
            self.enabled = True
            logger.info(f"Rotación de IPs activada con {len(self.proxy_list)} proxies")
        else:
            logger.warning("No hay proxies disponibles, desactivando rotación de IPs")
            self.enabled = False
    
    def _load_from_service(self, service_name, api_key):
        """Carga proxies desde un servicio externo"""
        if service_name == 'brightdata':
            # Ejemplo para BrightData
            self._load_from_brightdata(api_key)
        elif service_name == 'smartproxy':
            # Ejemplo para SmartProxy
            pass
        elif service_name == 'oxylabs':
            # Ejemplo para Oxylabs
            pass
        else:
            logger.error(f"Servicio de proxies desconocido: {service_name}")
    
    def _load_from_brightdata(self, api_key):
        """
        Carga proxies desde BrightData
        NOTA: Este es solo un ejemplo, deberás implementar según la API de tu proveedor
        """
        logger.info("Cargando proxies desde BrightData")
        # En una implementación real, harías una solicitud a la API de BrightData
        username = self.proxy_config.get('username', '')
        password = api_key
        
        if username and password:
            # Formato común para el proxy de BrightData
            zones = ['zone1', 'zone2', 'zone3']  # Diferentes zonas/países
            
            for zone in zones:
                proxy = f"brd.superproxy.io:22225:{username}-zone-{zone}:{password}"
                self.proxy_list.append({
                    'http': f"http://{proxy}",
                    'https': f"http://{proxy}",
                    'zone': zone
                })
                
            logger.info(f"Cargados {len(self.proxy_list)} proxies de BrightData")
        else:
            logger.error("Credenciales incompletas para BrightData")
    
    def get_proxy(self):
        """
        Obtiene el próximo proxy de la lista
        
        Returns:
            dict or None: Diccionario de proxy para requests o None si está desactivado
        """
        if not self.enabled or not self.proxy_list:
            return None
            
        # Obtener proxy actual y avanzar al siguiente
        proxy = self.proxy_list[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxy_list)
        
        return proxy
    
    def report_error(self, proxy, error_type):
        """
        Reporta un error con un proxy específico
        
        Args:
            proxy (dict): El proxy que falló
            error_type (str): Tipo de error
        """
        if not proxy:
            return
            
        proxy_str = str(proxy)
        if proxy_str not in self.proxy_errors:
            self.proxy_errors[proxy_str] = {'count': 0, 'types': {}}
            
        self.proxy_errors[proxy_str]['count'] += 1
        
        if error_type not in self.proxy_errors[proxy_str]['types']:
            self.proxy_errors[proxy_str]['types'][error_type] = 0
            
        self.proxy_errors[proxy_str]['types'][error_type] += 1
        
        # Si un proxy tiene muchos errores, podemos eliminarlo temporalmente
        if self.proxy_errors[proxy_str]['count'] >= 5:
            logger.warning(f"Proxy {proxy_str} ha fallado demasiadas veces, removiendo temporalmente")
            try:
                self.proxy_list.remove(proxy)
            except ValueError:
                pass
            
            # Si no quedan proxies, desactivar
            if not self.proxy_list:
                logger.error("No quedan proxies disponibles, desactivando rotación de IPs")
                self.enabled = False
    
    def report_success(self, proxy):
        """Reporta un uso exitoso de un proxy"""
        if not proxy:
            return
            
        proxy_str = str(proxy)
        if proxy_str in self.proxy_errors:
            # Reducir contador de errores en caso de éxito
            self.proxy_errors[proxy_str]['count'] = max(0, self.proxy_errors[proxy_str]['count'] - 1)
    
    def is_enabled(self):
        """Verifica si la rotación de IPs está activada"""
        return self.enabled

class RequestManager:
    """
    Gestiona las solicitudes HTTP con estrategias para evitar bloqueos.
    Implementa rate limiting, caché, y gestión de sesiones.
    """
    def __init__(self, 
                 max_requests_per_minute=20, 
                 session_reset_after=20,
                 cache_ttl=3600,
                 cache_file="request_cache.json"):
        self.session = requests.Session()
        self.max_requests_per_minute = max_requests_per_minute
        self.session_reset_after = session_reset_after
        self.request_timestamps = []
        self.request_count = 0
        self.cache = {}
        self.cache_ttl = cache_ttl
        self.cache_file = cache_file
        
        # Cargar caché desde disco si existe
        self._load_cache()
        
    def _load_cache(self):
        """Carga la caché desde el archivo"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    
                # Filtrar entradas caducadas
                now = time.time()
                valid_cache = {}
                for url, data in cache_data.items():
                    if now - data['timestamp'] < self.cache_ttl:
                        valid_cache[url] = data
                
                self.cache = valid_cache
                logger.info(f"Caché cargada con {len(self.cache)} URLs válidas")
        except Exception as e:
            logger.error(f"Error al cargar la caché: {str(e)}")
            self.cache = {}
            
    def _save_cache(self):
        """Guarda la caché en el archivo"""
        try:
            # Asegurar que el directorio existe
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False)
            logger.debug(f"Caché guardada con {len(self.cache)} URLs")
        except Exception as e:
            logger.error(f"Error al guardar la caché: {str(e)}")
    
    def get(self, url, cache=True, force_new=False):
        """
        Realiza una solicitud GET con gestión inteligente para evitar bloqueos
        
        Args:
            url (str): URL a solicitar
            cache (bool): Si se debe usar caché
            force_new (bool): Si se debe forzar una nueva solicitud
            
        Returns:
            str: Contenido HTML de la respuesta
        """
        # Verificar caché si está habilitada y no se fuerza nueva solicitud
        if cache and not force_new and url in self.cache:
            cached_data = self.cache[url]
            # Verificar si la caché está vigente
            if time.time() - cached_data['timestamp'] < self.cache_ttl:
                logger.debug(f"Usando caché para: {url}")
                return cached_data['content']
        
        # Limitar la tasa de solicitudes
        self._rate_limit()
        
        # Renovar sesión periódicamente
        if self.request_count >= self.session_reset_after:
            logger.debug("Reiniciando sesión HTTP")
            self.session = requests.Session()
            self.request_count = 0
            
        # Obtener retraso adaptativo
        if adaptive_delay and CONFIG['use_adaptive_delay']:
            delay = adaptive_delay.get_delay()
        else:
            delay = random.uniform(CONFIG['delay_min'], CONFIG['delay_max'])
            
        logger.debug(f"Esperando {delay:.2f} segundos antes de la solicitud")
        time.sleep(delay)
        
        # Headers aleatorios
        headers = get_random_headers()
        
        # Obtener proxy si está habilitado
        proxy = None
        if proxy_manager and proxy_manager.is_enabled():
            proxy = proxy_manager.get_proxy()
            logger.debug(f"Usando proxy: {proxy}")
        
        try:
            # Registrar timestamp para rate limiting
            self.request_timestamps.append(time.time())
            self.request_count += 1
            
            # Realizar la solicitud
            response = self.session.get(url, headers=headers, proxies=proxy, timeout=15)
            response.raise_for_status()
            
            # Actualizar retraso adaptativo
            if adaptive_delay and CONFIG['use_adaptive_delay']:
                adaptive_delay.success()
                
            # Reportar éxito del proxy si se usó
            if proxy_manager and proxy_manager.is_enabled() and proxy:
                proxy_manager.report_success(proxy)
            
            # Guardar en caché si está habilitada
            if cache:
                self.cache[url] = {
                    'content': response.text,
                    'timestamp': time.time()
                }
                # Guardar caché cada 10 solicitudes
                if len(self.request_timestamps) % 10 == 0:
                    self._save_cache()
            
            return response.text
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') else None
            logger.error(f"Error HTTP {status_code} al solicitar {url}: {str(e)}")
            
            # Reportar error del proxy si se usó
            if proxy_manager and proxy_manager.is_enabled() and proxy:
                proxy_manager.report_error(proxy, "http_error")
            
            # Actualizar retraso adaptativo
            if adaptive_delay and CONFIG['use_adaptive_delay']:
                if status_code:
                    error_type = "rate_limit" if status_code == 429 else "server_error"
                    needs_pause = adaptive_delay.error(error_type)
                    if needs_pause:
                        logger.warning(f"Implementando pausa larga de 120 segundos debido a error {status_code}")
                        time.sleep(120)  # Pausa larga en caso de muchos errores
            
            raise
        except Exception as e:
            logger.error(f"Error al solicitar {url}: {str(e)}")
            
            # Reportar error del proxy si se usó
            if proxy_manager and proxy_manager.is_enabled() and proxy:
                proxy_manager.report_error(proxy, "connection_error")
                
            # Actualizar retraso adaptativo
            if adaptive_delay and CONFIG['use_adaptive_delay']:
                adaptive_delay.error("connection_error")
                
            raise
            
    def _rate_limit(self):
        """Implementa rate limiting para mantener las solicitudes bajo el límite"""
        now = time.time()
        
        # Filtrar timestamps de la último minuto
        minute_ago = now - 60
        self.request_timestamps = [ts for ts in self.request_timestamps if ts > minute_ago]
        
        # Si hemos alcanzado el límite, esperar
        if len(self.request_timestamps) >= self.max_requests_per_minute:
            # Calcular tiempo a esperar
            oldest = min(self.request_timestamps)
            wait_time = 60 - (now - oldest) + 1  # +1 segundo adicional por seguridad
            
            logger.warning(f"Rate limit alcanzado. Esperando {wait_time:.2f} segundos")
            time.sleep(max(0, wait_time))
        
    def clear_cache(self):
        """Limpia la caché"""
        self.cache = {}
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
        logger.info("Caché limpiada correctamente")

class TaskScheduler:
    """
    Scheduler para programar y distribuir las tareas de scraping en el tiempo.
    Permite programar búsquedas en horarios específicos o distribuirlas.
    """
    def __init__(self, db_file="scheduled_tasks.json"):
        self.db_file = db_file
        self.tasks = []
        self._load_tasks()
        
    def _load_tasks(self):
        """Carga las tareas programadas desde el archivo"""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    self.tasks = json.load(f)
                logger.info(f"Cargadas {len(self.tasks)} tareas programadas")
        except Exception as e:
            logger.error(f"Error al cargar tareas programadas: {str(e)}")
            self.tasks = []
            
    def _save_tasks(self):
        """Guarda las tareas programadas en el archivo"""
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
            logger.debug(f"Guardadas {len(self.tasks)} tareas programadas")
        except Exception as e:
            logger.error(f"Error al guardar tareas programadas: {str(e)}")
    
    def add_task(self, task_type, params, schedule_time=None, recurrence=None):
        """
        Añade una nueva tarea programada
        
        Args:
            task_type (str): Tipo de tarea ('product_search' o 'seller_search')
            params (dict): Parámetros de la búsqueda
            schedule_time (datetime): Momento de ejecución (None = inmediato)
            recurrence (str): Recurrencia ('daily', 'weekly', 'monthly', None = una vez)
            
        Returns:
            str: ID de la tarea
        """
        task_id = str(uuid.uuid4())
        
        task = {
            'id': task_id,
            'type': task_type,
            'params': params,
            'created_at': datetime.now().isoformat(),
            'schedule_time': schedule_time.isoformat() if schedule_time else None,
            'recurrence': recurrence,
            'status': 'pending',
            'last_run': None,
            'next_run': schedule_time.isoformat() if schedule_time else datetime.now().isoformat()
        }
        
        self.tasks.append(task)
        self._save_tasks()
        
        return task_id
    
    def get_pending_tasks(self):
        """
        Obtiene las tareas pendientes que deben ejecutarse ahora
        
        Returns:
            list: Lista de tareas pendientes
        """
        now = datetime.now()
        pending = []
        
        for task in self.tasks:
            if task['status'] == 'pending' and task['next_run']:
                next_run = datetime.fromisoformat(task['next_run'])
                if next_run <= now:
                    pending.append(task)
                    
        return pending
    
    def update_task_status(self, task_id, status, result=None):
        """
        Actualiza el estado de una tarea
        
        Args:
            task_id (str): ID de la tarea
            status (str): Nuevo estado ('running', 'completed', 'failed')
            result (dict): Resultado de la ejecución
        """
        for task in self.tasks:
            if task['id'] == task_id:
                task['status'] = status
                task['last_run'] = datetime.now().isoformat()
                
                if result:
                    task['last_result'] = result
                    
                # Si es recurrente, programar la próxima ejecución
                if task['recurrence']:
                    next_run = datetime.fromisoformat(task['last_run'])
                    
                    if task['recurrence'] == 'daily':
                        next_run = next_run + timedelta(days=1)
                    elif task['recurrence'] == 'weekly':
                        next_run = next_run + timedelta(weeks=1)
                    elif task['recurrence'] == 'monthly':
                        # Aproximación simple para mes siguiente
                        if next_run.month == 12:
                            next_run = next_run.replace(year=next_run.year+1, month=1)
                        else:
                            next_run = next_run.replace(month=next_run.month+1)
                            
                    task['next_run'] = next_run.isoformat()
                    task['status'] = 'pending'
                
                self._save_tasks()
                break
                
    def delete_task(self, task_id):
        """Elimina una tarea programada"""
        self.tasks = [task for task in self.tasks if task['id'] != task_id]
        self._save_tasks()
        
    def get_task(self, task_id):
        """Obtiene una tarea por su ID"""
        for task in self.tasks:
            if task['id'] == task_id:
                return task
        return None
        
    def get_all_tasks(self):
        """Obtiene todas las tareas"""
        return self.tasks

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')

def init_components():
    """Inicializa los componentes según la configuración"""
    global request_manager, proxy_manager, task_scheduler, adaptive_delay
    
    # Inicializar el gestor de retrasos adaptativos
    adaptive_delay = AdaptiveDelay(
        min_delay=CONFIG['delay_min'],
        max_delay=CONFIG['delay_max']
    )
    
    # Inicializar el gestor de proxies si está habilitado
    if CONFIG['enable_proxy']:
        proxy_manager = ProxyManager(CONFIG['proxy_config'])
    else:
        proxy_manager = ProxyManager({'type': 'none'})
    
    # Inicializar el gestor de solicitudes
    request_manager = RequestManager(
        max_requests_per_minute=CONFIG['max_requests_per_minute'],
        session_reset_after=20,
        cache_ttl=CONFIG['cache_ttl'],
        cache_file=CONFIG['cache_file']
    )
    
    # Inicializar el programador de tareas si está habilitado
    if CONFIG['scheduler_enabled']:
        task_scheduler = TaskScheduler()

def is_low_traffic_hour():
    """Verifica si estamos en horas de bajo tráfico"""
    now = datetime.now()
    start = CONFIG['low_traffic_hours']['start']
    end = CONFIG['low_traffic_hours']['end']
    
    current_hour = now.hour
    
    # Si start > end, significa que el rango cruza la medianoche
    if start > end:
        return current_hour >= start or current_hour < end
    else:
        return start <= current_hour < end

def get_random_headers():
    """Generar headers aleatorios para evitar bloqueos"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.55 Safari/537.36'
    ]
    
    accept_languages = [
        'es-ES,es;q=0.9,en;q=0.8',
        'es-AR,es;q=0.9,es-419;q=0.8,en;q=0.7',
        'es-MX,es;q=0.9,es-ES;q=0.8,en;q=0.7',
        'en-US,en;q=0.9,es;q=0.8',
        'es,en;q=0.8,es-ES;q=0.7'
    ]
    
    return {
        'User-Agent': random.choice(user_agents),
        'Accept-Language': random.choice(accept_languages),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://www.mercadolibre.com.ar/' if random.random() < 0.7 else 'https://www.google.com/'
    }

def get_html(url, use_cache=True):
    """
    Función centralizada para obtener HTML con todas las protecciones.
    Reemplaza las llamadas directas a requests.get() y cached_request()
    """
    # Inicializar componentes si es necesario
    if request_manager is None:
        init_components()
    
    # Verificar si estamos en horas de bajo tráfico para ajustar parámetros
    if is_low_traffic_hour():
        # En horas de bajo tráfico podemos ser más agresivos
        request_manager.max_requests_per_minute = CONFIG['max_requests_per_minute'] * 1.5
        adaptive_delay.current_min = max(CONFIG['delay_min'] * 0.7, 0.5)
        adaptive_delay.current_max = max(CONFIG['delay_max'] * 0.7, 1.5)
    else:
        # En horas normales, usar los valores por defecto
        request_manager.max_requests_per_minute = CONFIG['max_requests_per_minute']
        adaptive_delay.current_min = CONFIG['delay_min']
        adaptive_delay.current_max = CONFIG['delay_max']
    
    # Hacer la solicitud a través del gestor
    try:
        html = request_manager.get(url, cache=use_cache)
        return html
    except Exception as e:
        logger.error(f"Error al obtener HTML de {url}: {str(e)}")
        raise

# Mantener función de compatibilidad para no romper código existente
def cached_request(url, cache_key=None):
    """Función de compatibilidad - usa get_html internamente"""
    return get_html(url, use_cache=True)

def random_delay():
    """Genera una pausa aleatoria para evitar ser detectado como bot"""
    if adaptive_delay and CONFIG['use_adaptive_delay']:
        delay = adaptive_delay.get_delay()
    else:
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
                    # Usar el gestor de solicitudes en lugar de cached_request
                    detail_html = get_html(product_link)
                    
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
    
    # Inicializar componentes si aún no se ha hecho
    if request_manager is None:
        init_components()
    
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
    page = 0
    
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
                # Usar el gestor de solicitudes para obtener HTML
                html_content = get_html(url)
                
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

                # No necesitamos random_delay aquí - ya está gestionado por el request_manager

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
        
        # Re-inicializar componentes si están activos
        if adaptive_delay:
            adaptive_delay.min_delay = CONFIG['delay_min']
            adaptive_delay.max_delay = CONFIG['delay_max']
            adaptive_delay.current_min = CONFIG['delay_min']
            adaptive_delay.current_max = CONFIG['delay_max']
        
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
        # Usar el request manager para limpiar caché si está disponible
        if request_manager:
            request_manager.clear_cache()
        else:
            # Compatibilidad con la versión anterior
            cached_request.cache_clear()
            
        logger.info("Cache limpiada correctamente")
        return jsonify({"success": True, "message": "Cache limpiada correctamente"})
    except Exception as e:
        logger.error(f"Error al limpiar la cache: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/advanced_config')
def advanced_config():
    """Muestra la página de configuración avanzada"""
    return render_template('advanced_config.html', config=CONFIG, message=None, message_type=None)

@app.route('/save_advanced_config', methods=['POST'])
def save_advanced_config():
    """Guarda la configuración avanzada"""
    try:
        # Configuración de solicitudes
        CONFIG['max_requests_per_minute'] = int(request.form.get('max_requests_per_minute', CONFIG['max_requests_per_minute']))
        CONFIG['cache_ttl'] = int(request.form.get('cache_ttl', CONFIG['cache_ttl']))
        CONFIG['delay_min'] = float(request.form.get('delay_min', CONFIG['delay_min']))
        CONFIG['delay_max'] = float(request.form.get('delay_max', CONFIG['delay_max']))
        CONFIG['use_adaptive_delay'] = request.form.get('use_adaptive_delay') == 'on'
        
        # Programación de búsquedas
        CONFIG['scheduler_enabled'] = request.form.get('scheduler_enabled') == 'on'
        CONFIG['low_traffic_hours']['start'] = int(request.form.get('low_traffic_start', CONFIG['low_traffic_hours']['start']))
        CONFIG['low_traffic_hours']['end'] = int(request.form.get('low_traffic_end', CONFIG['low_traffic_hours']['end']))
        
        # Rotación de IPs
        CONFIG['enable_proxy'] = request.form.get('enable_proxy') == 'on'
        CONFIG['proxy_config']['type'] = request.form.get('proxy_type', 'none')
        
        # Configuración específica del tipo de proxy
        if CONFIG['proxy_config']['type'] == 'list':
            proxy_list_text = request.form.get('proxy_list_text', '')
            CONFIG['proxy_config']['list'] = [line.strip() for line in proxy_list_text.split('\n') if line.strip()]
        elif CONFIG['proxy_config']['type'] == 'service':
            CONFIG['proxy_config']['service_name'] = request.form.get('service_name', '')
            CONFIG['proxy_config']['api_key'] = request.form.get('api_key', '')
            CONFIG['proxy_config']['username'] = request.form.get('username', '')
        
        # Guardar configuración en archivo
        try:
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"No se pudo guardar la configuración en disco: {str(e)}")
        
        # Re-inicializar componentes
        init_components()
        
        logger.info("Configuración avanzada actualizada correctamente")
        return render_template('advanced_config.html', 
                              config=CONFIG, 
                              message="Configuración guardada correctamente", 
                              message_type="success")
    except Exception as e:
        logger.error(f"Error al guardar configuración avanzada: {str(e)}")
        return render_template('advanced_config.html', 
                              config=CONFIG, 
                              message=f"Error al guardar configuración: {str(e)}", 
                              message_type="danger")

@app.route('/schedule_task', methods=['POST'])
def schedule_task():
    """Programa una tarea para ejecución posterior"""
    try:
        # Comprobar si el programador está habilitado
        if not CONFIG['scheduler_enabled']:
            return jsonify({
                "success": False, 
                "error": "El programador de tareas no está habilitado. Actívalo en la configuración avanzada."
            }), 400
            
        # Inicializar componentes si es necesario
        if task_scheduler is None:
            init_components()
            
        # Si aún así el programador no está disponible, error
        if task_scheduler is None:
            return jsonify({
                "success": False, 
                "error": "No se pudo inicializar el programador de tareas."
            }), 500
        
        # Obtener datos del formulario
        task_type = request.form.get('task_type')  # 'product_search' o 'seller_search'
        
        # Común para ambos tipos
        schedule_time_str = request.form.get('schedule_time')
        recurrence = request.form.get('recurrence', None)  # None, 'daily', 'weekly', 'monthly'
        
        # Convertir fecha y hora
        schedule_time = None
        if schedule_time_str:
            try:
                schedule_time = datetime.fromisoformat(schedule_time_str)
            except ValueError:
                return jsonify({
                    "success": False, 
                    "error": "Formato de fecha y hora inválido."
                }), 400
        
        # Parámetros específicos según el tipo de tarea
        params = {}
        
        if task_type == 'product_search':
            params['search_query'] = request.form.get('search_query', '')
            params['exact_match'] = request.form.get('exact_match') == 'on'
            params['seller_filter'] = request.form.get('seller_filter', '')
        elif task_type == 'seller_search':
            params['seller_name'] = request.form.get('seller_name', '')
        else:
            return jsonify({
                "success": False, 
                "error": "Tipo de tarea no válido."
            }), 400
            
        # Parámetros comunes
        params['min_price'] = int(request.form.get('min_price', '0'))
        params['min_sales'] = int(request.form.get('min_sales', '0'))
        params['deep_sales_search'] = request.form.get('deep_sales_search') == 'on'
        params['max_products'] = int(request.form.get('max_products', CONFIG['max_products']))
        params['max_pages'] = int(request.form.get('max_pages', CONFIG['max_pages']))
        
        # Crear la tarea
        task_id = task_scheduler.add_task(
            task_type=task_type,
            params=params,
            schedule_time=schedule_time,
            recurrence=recurrence
        )
        
        return jsonify({
            "success": True,
            "message": "Tarea programada correctamente",
            "task_id": task_id
        })
        
    except Exception as e:
        logger.error(f"Error al programar tarea: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Error al programar tarea: {str(e)}"
        }), 500

@app.route('/scheduled_tasks')
def scheduled_tasks():
    """Muestra las tareas programadas"""
    try:
        # Inicializar componentes si es necesario
        if task_scheduler is None:
            init_components()
            
        # Si el programador no está disponible, error
        if task_scheduler is None:
            return render_template('scheduled_tasks.html', 
                                  error="El programador de tareas no está habilitado.",
                                  tasks=[])
        
        # Obtener tareas
        tasks = task_scheduler.get_all_tasks()
        
        return render_template('scheduled_tasks.html', tasks=tasks)
    except Exception as e:
        logger.error(f"Error al obtener tareas programadas: {str(e)}")
        return render_template('scheduled_tasks.html', 
                              error=f"Error al obtener tareas programadas: {str(e)}",
                              tasks=[])

@app.route('/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    """Elimina una tarea programada"""
    try:
        # Comprobar si el programador está habilitado
        if not CONFIG['scheduler_enabled'] or task_scheduler is None:
            return jsonify({
                "success": False, 
                "error": "El programador de tareas no está habilitado."
            }), 400
            
        # Eliminar tarea
        task_scheduler.delete_task(task_id)
        
        return jsonify({
            "success": True,
            "message": "Tarea eliminada correctamente"
        })
    except Exception as e:
        logger.error(f"Error al eliminar tarea: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Error al eliminar tarea: {str(e)}"
        }), 500

# Inicializar componentes al inicio
init_components()

if __name__ == '__main__':
    # Cargar configuración desde archivo si existe
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                # Actualizar solo las claves que existen en ambos
                for key in CONFIG:
                    if key in saved_config:
                        CONFIG[key] = saved_config[key]
            logger.info("Configuración cargada desde archivo")
    except Exception as e:
        logger.warning(f"No se pudo cargar la configuración desde archivo: {str(e)}")
    
    # Inicializar componentes después de cargar la configuración
    init_components()
    
    # Abrir navegador y ejecutar la aplicación
    Timer(1, open_browser).start()
    app.run(debug=True)
