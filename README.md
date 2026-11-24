# MyRestaurant — API del restaurante

Proyecto final de Tópicos. Django REST Framework, autenticación por token y catálogo de restaurante.

## Inicio local

Requiere Python 3.9 o superior compatible con las versiones de requirements.txt.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python manage.py migrate
python manage.py loaddata restaurant_menu
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

Conserva DJANGO_SECRET_KEY en tu entorno durante las siguientes ejecuciones. Para acceder desde otro dispositivo, agrega la IP del servidor a la lista ALLOWED_HOSTS de restaurant/settings.py y usa esa IP en src/utils/api.ts de la app. Admin: http://127.0.0.1:8000/admin/.

La entrega incluye el catálogo y sus imágenes en media/cards. La base se crea con las migraciones y el catálogo se carga desde restaurant_menu.json; no se incluyen cuentas, tokens, pagos ni datos personales. Los clientes se registran en la app. Para operadores, crea usuarios desde el administrador y asigna el rol en Perfiles: kitchen, bar o sushi. Estos operadores no necesitan Es staff. El superusuario puede administrar el catálogo.

## Evidencia de requisitos

Autenticación: /api-token-auth/, /register/, /logout/. Modelos: categorías, productos y variantes, usuarios/perfiles, favoritos, pedidos y líneas. Serialización anidada: categoría y presentaciones del producto; líneas del pedido. Catálogo: /cards/ y /categories/. Búsqueda: /cards/?search=ramen. Filtros: category, category__area, is_available. Paginación: page y page_size (máximo 30). CRUD: /cards/ y /cards/{id}/ con permisos por rol. Imagen: multipart/form-data, campo image. Favoritos: /cards/{id}/favorite/ y /cards/favorites/. Preferencias: GET/PATCH /preferences/ (theme_mode e language).

## Pruebas

```bash
python manage.py test restaurant.catalog
```

La colección MyRestaurant.postman_collection.json utiliza variables base_url, username, password, token y card_id. El login guarda el token automáticamente. Los ejemplos de escritura de productos requieren una cuenta con permisos. No ejecutar pruebas de eliminación sobre datos que se quieran conservar.

Los enlaces de pago se proporcionan externamente y los comprobantes se verifican por el restaurante; no hay cobro automático integrado. Google/Facebook quedan fuera del alcance de esta entrega.
