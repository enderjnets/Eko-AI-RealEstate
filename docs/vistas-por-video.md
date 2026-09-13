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

Cada lectura guarda **de dónde vino** y puede contener vistas, likes y
comentarios. En la página, una lectura de YouTube dice que llegó de la plataforma
y una de Instagram o TikTok dice que se escribió a mano. No es decoración: una
cifra transcrita y una medición automática no pueden mirarse igual.

Un hueco significa **sin lectura**. Un `0` visible significa que la plataforma sí
mostró cero. El panel conserva esa diferencia para no convertir un dato que falta
en un rendimiento que nunca se midió.

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
- **Las 15 publicaciones anteriores al 3 de septiembre de 2026**: no tienen la
  dirección guardada, porque el sistema empezó a recogerla de Buffer ese día
  (medido: 15 publicadas sin dirección, 4 con ella). No se pueden leer nunca.
  Es un hueco en el pasado, no una avería en el presente.

## Escribir una lectura manual

En la tarjeta de contenido de `/analytics`, usa el lápiz de una publicación de
TikTok o Instagram para escribir las vistas y, si están disponibles, los likes y
comentarios. YouTube no tiene editor manual en esta pantalla: sus contadores
proceden de la lectura automática y así queda claro qué fuente produjo el dato.

Se guarda **una lectura por día y plataforma**. Escribirla dos veces el mismo día
la corrige; no inventa un segundo dato. Si el guardado falla, la tarjeta conserva
lo escrito y muestra el error para que se pueda intentar de nuevo.
