import os
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session
from pymongo import MongoClient
from bson.objectid import ObjectId

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "llave_secreta_petmach")

# --- Configuración para subir archivos ---
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Conexión a la base de datos MongoDB
client = MongoClient(os.getenv("MONGODB_URI"))
db = client['pet_mach_db']
coleccion_mascotas = db['mascotas']
coleccion_usuarios = db['usuarios']
coleccion_refugios = db['refugios'] 
coleccion_mensajes = db['mensajes']
coleccion_solicitudes = db['solicitudes']


# Ruta para el Registro de Usuarios
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        # Tomamos los datos del formulario de registro
        nuevo_usuario = {
            "nombre": request.form['nombre'],
            "edad": request.form['edad'],
            "correo": request.form['correo'],
            "password": request.form['password'],
            "rol": "adoptante" # Por defecto, los que se registren aquí serán adoptantes
        }
        
        # Validamos si el correo ya existe para no tener duplicados
        usuario_existente = coleccion_usuarios.find_one({"correo": nuevo_usuario['correo']})
        
        if usuario_existente:
            return "Ese correo ya está registrado. Intenta con otro o inicia sesión."
        
        # Si no existe, lo guardamos en MongoDB
        coleccion_usuarios.insert_one(nuevo_usuario)
        
        # Lo mandamos directo al login para que entre con su nueva cuenta
        return redirect(url_for('login'))
        
    # Si es GET, mostramos el formulario
    return render_template('registro.html')

# Ruta para el Muro de Adopción con Búsqueda
@app.route('/dashboard')
def dashboard():
    # Leemos si el usuario escribió algo en la barra de búsqueda (la letra 'q')
    query = request.args.get('q')
    
    if query:
        # Si escribió algo, buscamos coincidencias en 'nombre' o 'raza' ignorando mayúsculas/minúsculas
        filtro = {
            "$or": [
                {"nombre": {"$regex": query, "$options": "i"}},
                {"raza": {"$regex": query, "$options": "i"}}
            ]
        }
        mascotas = list(coleccion_mascotas.find(filtro))
    else:
        # Si no escribió nada, traemos a todos los peluditos
        mascotas = list(coleccion_mascotas.find())

    return render_template('dashboard.html', mascotas=mascotas)

# Ruta para agregar una nueva mascota (Dar en adopción)
@app.route('/agregar', methods=['GET', 'POST'])
def agregar_mascota():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        nombre = request.form['nombre']
        raza = request.form['raza']
        descripcion = request.form['descripcion']
        refugio_seleccionado = request.form['refugio'] # Recibimos el refugio
        
        ruta_imagen = "https://cdn-icons-png.flaticon.com/512/194/194279.png"
        
        if 'foto' in request.files:
            archivo_foto = request.files['foto']
            if archivo_foto.filename != '':
                nombre_seguro = secure_filename(archivo_foto.filename)
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                archivo_foto.save(ruta_guardado)
                ruta_imagen = f"/static/uploads/{nombre_seguro}"
        
        nueva_mascota = {
            "nombre": nombre,
            "raza": raza,
            "descripcion": descripcion,
            "imagen": ruta_imagen,
            "refugio": refugio_seleccionado, # Guardamos el refugio
            "creador_id": session['usuario_id'] # Guardamos quién lo publicó
        }
        coleccion_mascotas.insert_one(nueva_mascota)
        return redirect(url_for('dashboard'))
    
    # Mandamos la lista de refugios al formulario
    lista_refugios = list(coleccion_refugios.find())
    return render_template('agregar.html', refugios=lista_refugios)

# Ruta para el directorio de Refugios
@app.route('/refugios')
def refugios():
    # Traemos los refugios de la base de datos
    lista_refugios = list(coleccion_refugios.find())
    return render_template('refugios.html', refugios=lista_refugios)

# Ruta para la bandeja de Mensajes (ACTUALIZADA)
@app.route('/mensajes')
def mensajes():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    
    # Si es Admin, ve todos los chats. Si es adoptante, solo ve los suyos.
    if usuario_actual['correo'] == 'admin@petmach.com':
        mis_chats = list(coleccion_solicitudes.find())
    else:
        mis_chats = list(coleccion_solicitudes.find({"id_adoptante": session['usuario_id']}))
        
    return render_template('mensajes.html', chats=mis_chats)


# Ruta para ver el chat y responder (SEPARADOS EN DOS SALAS CON BOT)
@app.route('/chat/<id_solicitud>/<tipo>', methods=['GET', 'POST'])
def chat(id_solicitud, tipo):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    solicitud = coleccion_solicitudes.find_one({"_id": ObjectId(id_solicitud)})
    
    if request.method == 'POST':
        mensaje_texto = request.form['mensaje']
        
        # 1. Preparamos nuestro mensaje, agregando la etiqueta de a dónde va
        nuevo_mensaje = {
            "remitente": usuario_actual['nombre'],
            "mensaje": mensaje_texto,
            "destino": tipo # 'sistema' o 'refugio'
        }
        
        mensajes_a_guardar = [nuevo_mensaje]
        
        # 2. Lógica del Bot (Solo responde si estamos en el chat del refugio y no somos admin)
        if usuario_actual['correo'] != 'admin@petmach.com' and tipo == 'refugio':
            mensaje_minusculas = mensaje_texto.lower()
            respuesta_auto = "¡Gracias por tu mensaje! En breve un voluntario revisará tu caso."
            
            if "hola" in mensaje_minusculas or "buenos dias" in mensaje_minusculas:
                respuesta_auto = "¡Hola! Qué gusto saludarte. ¿En qué podemos ayudarte con la adopción?"
            elif "requisito" in mensaje_minusculas or "documento" in mensaje_minusculas:
                respuesta_auto = "Para adoptar te pediremos: Identificación oficial y comprobante de domicilio reciente. ¿Tienes alguna duda?"
            elif "tiempo" in mensaje_minusculas or "cuando" in mensaje_minusculas:
                respuesta_auto = "El proceso suele tardar entre 2 y 3 días hábiles. ¡Te pedimos un poco de paciencia!"

            mensaje_automatico = {
                "remitente": solicitud.get('refugio', 'Refugio'),
                "mensaje": respuesta_auto
            }
            mensajes_a_guardar.append(mensaje_automatico)
            
        # 3. Guardamos los mensajes
        coleccion_solicitudes.update_one(
            {"_id": ObjectId(id_solicitud)},
            {"$push": {"chat": {"$each": mensajes_a_guardar}}}
        )
        return redirect(url_for('chat', id_solicitud=id_solicitud, tipo=tipo))
        
    # 4. Filtramos los mensajes para mostrar solo los de esta sala
    mensajes_filtrados = []
    for msg in solicitud.get('chat', []):
        # Es del sistema si el remitente fue el sistema, o si el destino era el sistema
        es_sistema = (msg['remitente'] == 'Sistema Pet Mach') or (msg.get('destino') == 'sistema')
        
        if tipo == 'sistema' and es_sistema:
            mensajes_filtrados.append(msg)
        elif tipo == 'refugio' and not es_sistema:
            mensajes_filtrados.append(msg)
            
    return render_template('chat.html', solicitud=solicitud, usuario=usuario_actual, mensajes=mensajes_filtrados, tipo=tipo)

# 1. NUEVA RUTA PRINCIPAL (La Portada o Landing Page)
@app.route('/')
def index():
    # Si el usuario ya tiene sesión iniciada, lo mandamos directo a los perritos
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    # Si no, le mostramos la portada bonita
    return render_template('index.html')

# 2. RUTA DE LOGIN (Se movió a /login)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form['correo']
        password = request.form['password']
        
        # Buscamos al usuario en MongoDB
        usuario = coleccion_usuarios.find_one({'correo': correo})
        
        # Aquí asumo que validas tu contraseña (ajusta esto si usas hash)
        if usuario and usuario['password'] == password:
            # Guardamos sus datos en la sesión
            session['usuario_id'] = str(usuario['_id'])
            session['correo'] = usuario['correo']
            
            # 🔥 LA NUEVA MAGIA: Leemos su "gafete" (Si no tiene, es adoptante)
            tipo_cuenta = usuario.get('tipo_cuenta', 'adoptante')
            session['tipo_cuenta'] = tipo_cuenta
            
            # El Guardia de Seguridad lo dirige a su zona
            if tipo_cuenta == 'refugio':
                return redirect(url_for('panel_refugio'))
            else:
                return redirect(url_for('dashboard'))
                
        else:
            # Contraseña incorrecta
            return "Correo o contraseña incorrectos", 401
            
    return render_template('login.html')

# Ruta para Mi Perfil (CORREGIDA PARA NO REPETIR FORMULARIOS)
@app.route('/perfil', methods=['GET', 'POST'])
def perfil():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    
    if request.method == 'POST':
        nuevo_nombre = request.form['nombre']
        
        # Revisamos si el usuario subió una foto nueva
        if 'foto' in request.files:
            archivo_foto = request.files['foto']
            
            if archivo_foto.filename != '': # Si realmente seleccionó un archivo
                # Aseguramos el nombre del archivo y lo guardamos
                nombre_seguro = secure_filename(archivo_foto.filename)
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                archivo_foto.save(ruta_guardado)
                
                # Actualizamos la base de datos con la ruta local de la nueva foto
                coleccion_usuarios.update_one(
                    {"_id": ObjectId(session['usuario_id'])},
                    {"$set": {"foto": f"/static/uploads/{nombre_seguro}"}}
                )
        
        # Actualizamos el nombre
        coleccion_usuarios.update_one(
            {"_id": ObjectId(session['usuario_id'])},
            {"$set": {"nombre": nuevo_nombre}}
        )
        return redirect(url_for('perfil'))
        
    # 🔥 AQUÍ ESTÁ EL FILTRO MÁGICO 🔥
    # Revisamos qué tipo de cuenta está viendo el perfil
    if usuario_actual.get('tipo_cuenta') == 'refugio':
        # Si es un refugio, ve únicamente los formularios dirigidos a él
        formularios = list(coleccion_solicitudes.find({"refugio": usuario_actual.get('correo')}))
    else:
        # Si es un adoptante normal, ve únicamente los formularios que él envió
        formularios = list(coleccion_solicitudes.find({"id_adoptante": session['usuario_id']}))
        
    return render_template('perfil.html', usuario=usuario_actual, solicitudes=formularios)

# RUTA PARA CERRAR SESIÓN CORRECTAMENTE
@app.route('/logout')
def logout():
    session.clear()  # 🔥 Esto destruye el gafete y borra la memoria del usuario
    return redirect(url_for('index')) # Te regresa a la portada amarilla

# Ruta para ver el perfil detallado de una mascota (ACTUALIZADA)
@app.route('/detalle/<id_mascota>') # El nombre de tu ruta
def detalle_mascota(id_mascota):
    mascota = coleccion_mascotas.find_one({"_id": ObjectId(id_mascota)})
    
    # 🔥 NUEVA LÓGICA: ¿Este usuario ya solicitó a esta mascota?
    ya_solicito = False
    if 'usuario_id' in session:
        solicitud_previa = coleccion_solicitudes.find_one({
            "id_mascota": id_mascota,
            "id_adoptante": session['usuario_id']
        })
        if solicitud_previa:
            ya_solicito = True

    # Le pasamos la variable "ya_solicito" al HTML
    return render_template('detalle.html', mascota=mascota, ya_solicito=ya_solicito)

# NUEVA RUTA: Borrar una mascota de la base de datos (ACTUALIZADA CON BORRADO EN CASCADA)
@app.route('/mascota/borrar/<id>', methods=['POST'])
def borrar_mascota(id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    
    # 1. Eliminamos el registro del peludito en MongoDB usando su ID único
    coleccion_mascotas.delete_one({"_id": ObjectId(id)})
    
    # 🔥 2. EL BORRADO EN CASCADA 🔥
    # Buscamos en la colección de solicitudes todas las que tengan este ID y las borramos
    coleccion_solicitudes.delete_many({"id_mascota": id})
    
    # 3. Redirigimos de vuelta al muro principal
    return redirect(url_for('dashboard'))

# Ruta para el Formulario de Pre-Adopción (ACTUALIZADA PARA INICIAR EL CHAT Y CAMBIAR ESTATUS)
@app.route('/adoptar/<id_mascota>', methods=['GET', 'POST'])
def preadopcion(id_mascota):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    mascota = coleccion_mascotas.find_one({"_id": ObjectId(id_mascota)})
    refugio_nombre = mascota.get('refugio', 'Refugio Asociado')
    
    if request.method == 'POST':
        nueva_solicitud = {
            "id_mascota": id_mascota,
            "nombre_mascota": mascota['nombre'],
            "refugio": refugio_nombre,
            "id_adoptante": session['usuario_id'], # Guardamos de quién es el trámite
            "nombre_adoptante": request.form['nombre'],
            "telefono": request.form['telefono'],
            "motivo": request.form['motivo'],
            # Iniciamos el historial de chat con dos mensajes automáticos
            "chat": [
                {"remitente": "Sistema Pet Mach", "mensaje": f"Tu solicitud por {mascota['nombre']} ha sido recibida."},
                {"remitente": refugio_nombre, "mensaje": "¡Hola! Analizaremos tu perfil y te responderemos por este medio."}
            ]
        }
        # 1. Guardamos la solicitud en la colección de solicitudes
        coleccion_solicitudes.insert_one(nueva_solicitud)
        
        # 🔥 2. CAMBIO DE ESTATUS AUTOMÁTICO EN LA BASE DE DATOS 🔥
        # Buscamos esta mascota específica y le inyectamos el campo estatus como 'en_proceso'
        coleccion_mascotas.update_one(
            {"_id": ObjectId(id_mascota)},
            {"$set": {"estatus": "en_proceso"}}
        )
        
        # 3. Redirigimos al usuario a sus mensajes
        return redirect(url_for('mensajes'))
        
    return render_template('preadopcion.html', mascota=mascota)

# NUEVA RUTA: Editar publicación
@app.route('/mascota/editar/<id>', methods=['GET', 'POST'])
def editar_mascota(id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    mascota = coleccion_mascotas.find_one({"_id": ObjectId(id)})

    # Validación: Solo el creador puede editar
    if mascota.get('creador_id') != session['usuario_id']:
        return "No tienes permiso para editar esta publicación."

    if request.method == 'POST':
        nuevos_datos = {
            "nombre": request.form['nombre'],
            "raza": request.form['raza'],
            "descripcion": request.form['descripcion'],
            "refugio": request.form['refugio']
        }

        # Si subió una foto nueva, la actualizamos
        if 'foto' in request.files:
            archivo_foto = request.files['foto']
            if archivo_foto.filename != '':
                nombre_seguro = secure_filename(archivo_foto.filename)
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                archivo_foto.save(ruta_guardado)
                nuevos_datos["imagen"] = f"/static/uploads/{nombre_seguro}"

        coleccion_mascotas.update_one({"_id": ObjectId(id)}, {"$set": nuevos_datos})
        return redirect(url_for('detalle_mascota', id=id))

    lista_refugios = list(coleccion_refugios.find())
    return render_template('editar.html', mascota=mascota, refugios=lista_refugios)

# NUEVA RUTA: Página de Nuestra Historia
@app.route('/historia')
def historia():
    return render_template('historia.html')

# NUEVA RUTA: Página de Donaciones
@app.route('/donar')
def donar():
    return render_template('donar.html')

# NUEVA RUTA: El Panel de Control exclusivo para Refugios
@app.route('/panel_refugio')
def panel_refugio():
    # 1. Validamos que haya iniciado sesión
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    # 2. Validamos que de verdad sea un refugio (El "cadenero")
    if session.get('tipo_cuenta') != 'refugio':
        return redirect(url_for('dashboard'))
        
    # 3. Buscamos todas las solicitudes que ha recibido este refugio en específico
    # (Asumiendo que el nombre del refugio está ligado a su cuenta)
    solicitudes_recibidas = list(coleccion_solicitudes.find({"refugio": session.get('correo')})) 
    
    return render_template('panel_refugio.html', solicitudes=solicitudes_recibidas)



if __name__ == '__main__':
    app.run(debug=True)