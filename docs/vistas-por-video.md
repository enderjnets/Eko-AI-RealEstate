# Vistas por vídeo: qué se lee solo y qué hay que teclear

Hasta ahora todo lo que el embudo sabía empezaba en la landing. Eso deja un
punto ciego grande: **un vídeo que llegó a cuatro personas y uno que llegó a
cuatro mil y no convenció a nadie se ven idénticos** desde dentro del producto.
Son problemas opuestos —hacer mejores vídeos, o arreglar la página— y sin la
cifra de vistas no se pueden distinguir.

## Qué hace cada plataforma

| Red | Cómo llega la cifra | Por qué |
|---|---|---|
| **YouTube** | sola, cada 6 horas | `videos.list` sirve los contadores públicos de cualquier vídeo público a una simple clave de API: sin OAuth, sin ser dueño del canal, sin revisión |
| **TikTok** | **a mano**, desde la consola de contenido | su API solo da las vistas a una app propia que haya pasado la revisión de la plataforma |
| **Instagram** | **a mano**, desde la consola de contenido | igual, con la revisión de Meta |

Cada número guarda **de dónde vino**. En la página, una cifra leída por la
máquina dice «leídas» y una tecleada dice «a mano». No es decoración: una
estimación escrita a ojo y una medición no pueden mirarse igual.

## La clave de YouTube: qué hay que crear

Es lo único que no puede hacer el sistema por sí mismo.

1. Entra en `console.cloud.google.com` y elige un proyecto (o crea uno; el
   nombre da igual, por ejemplo `denver-home-story`).
2. **APIs y servicios → Biblioteca** → busca **«YouTube Data API v3»** →
   **Habilitar**. Sin este paso la clave existe pero contesta 403.
3. **APIs y servicios → Credenciales → Crear credenciales → Clave de API**.
4. Edita la clave recién creada:
   - **Restricciones de API** → *Restringir clave* → marca solo
     **YouTube Data API v3**.
   - **Restricciones de aplicación** → **Ninguna**.
     ⚠️ **Nunca «Referentes HTTP»**: eso es para páginas web, y a un servidor le
     devuelve un 403 que parece exactamente una clave equivocada.

### Lo que cuesta

`videos.list` cuesta **1 unidad por llamada**, y una llamada puede pedir hasta
50 vídeos. La cuota diaria gratuita es de **10.000 unidades**. Con una lectura
cada 6 horas, el gasto es de unas **4 unidades al día** — el 0,04 % de la cuota.

## Qué pasa si algo falla

Nada se rompe, y esa es la decisión de diseño:

- **Sin clave**: no se lee nada, la columna dice «sin lectura». No dice `0`,
  porque un cero afirmaría que el vídeo no lo vio nadie.
- **Cuota agotada o clave mal restringida** (403): queda un hueco en la gráfica
  de ese día y un aviso en el registro. El resto del sistema sigue igual.
- **Vídeo borrado o puesto en privado**: YouTube contesta 200 con una lista
  vacía. Eso es «no hay dato para ese id», no un error.
- **Publicaciones anteriores a agosto de 2026**: no tienen dirección guardada
  (Buffer empezó a reportarla hace poco), así que no se pueden leer. Es un hueco
  en el pasado, no una avería.

## Corregir un número a mano

En la tarjeta de contenido de `/analytics`, la cifra de vistas de TikTok e
Instagram se pulsa y se escribe. También se puede corregir la de YouTube: una
persona mirando la app ahora mismo sabe más que una lectura de hace seis horas.

Se guarda **una lectura por día**. Escribir la cifra dos veces el mismo día la
corrige; no inventa un segundo dato.
