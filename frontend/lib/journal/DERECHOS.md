# Derechos de las fotografías de "Twelve houses worth the detour"

Estado al **20 de septiembre de 2026**. Esta es la única prueba documental de
la letra `a` de la Regla 6.10.F.1 de Colorado. Si no está aquí, no existe.

## Estado de las dos puertas (20-sep-2026)

| Puerta | Valor | Qué hace | ¿Se deshace? |
|---|---|---|---|
| `LINKED` | **abierta** | la portada enlaza The Journal en la navegación, el menú del móvil y el pie | **sí**, en un despliegue |
| `INDEXED` | **cerrada** | `robots: noindex, nofollow` en las dos páginas y `/blog` fuera del sitemap | **no**: lo que el rastreador cachea, se queda |

El enlace lo abrió Ender el 20-sep-2026 después de que le diera el coste por
escrito. **Ninguna fila de la tabla de abajo cambió por eso**, y ninguna cambia
hasta que exista el permiso: este fichero dice la verdad pase lo que pase en
`publication.ts`.

Lo que sigue pendiente, y es lo que de verdad mira la Regla 6.10.F.1.a: el
permiso escrito de las ocho corredurías y, con él, **los originales sin
recortar**.

## Lo que hay que saber antes de tocar nada

**Ninguna de las doce casas es de nuestra correduría.** Son de ocho corredurías
ajenas. Eso cambia el marco entero: no es publicar una ficha propia, es
difundir el anuncio de otro corredor.

**A las 48 fotografías del paquete de diseño se les recortó el 11% inferior
para quitar la marca de agua de copyright** del MLS de Aspen/Glenwood y de
REcolorado. Medido en los píxeles, no leído en una nota: un fichero de 2000 px
de ancho que debería medir 1333 de alto en 3:2 mide 1188, que es 0,891 — el
10,9% desaparecido. Los de 1280×854 son un 4:3 al que le falta el 11,0%.

Eso son dos problemas, no uno:

1. **Usar la foto.** La *MLS Policy* de REcolorado dice literalmente: «Use of a
   photograph from another Subscriber's listing is **strictly prohibited**
   unless you have written permission from the owner of the copyright», y
   recuerda que los daños estatutarios del DMCA llegan a **$150.000 por obra**.
2. **Haberle quitado el aviso de copyright.** Es una cuestión aparte de la
   licencia y más seria. Este proyecto ya tiene escrita la norma contraria, en
   `public/landing/fall/LICENCIA.txt`: *«Todas se sirven SIN RECORTAR. El
   encuadre lo hace el CSS, no un fichero recortado, y eso es deliberado: un
   recorte guardado es una obra derivada.»*

Por eso las fotos **no están en este repositorio**, que es público. Viven fuera,
y `frontend/scripts/journal-photos.sh` las trae. Ver `.gitignore`.

## Lo que hace falta antes de publicar

Para cada una de las ocho corredurías:

1. **Permiso escrito** para difundir su anuncio (6.10.F.1.a). Guardar el correo:
   es la única prueba.
2. **Los originales sin recortar.** El encuadre lo hace el CSS, como en `/fall`.
3. **Comprobar que la ficha sigue activa el día de publicar** (6.10.F.1.c): una
   ficha vendida convierte el anuncio en engañoso. La fecha del corte está en
   `AS_OF` dentro de `twelveHouses.ts`.

Lo que ya cumple el diseño y hay que conservar: cada ficha acredita a su
correduría en el `figcaption` (6.10.F.1.b), enlaza al registro completo, y la
sección cierra con el aviso de derechos. El pie nombra la correduría propia
desde configuración (6.10.A.4 y 6.10.D.1).

## Estado por correduría

Mientras quede una sola fila en «pendiente», el artículo no sale a público. Lo
vigila `lib/__tests__/journal.test.ts`, que falla si algún `permission` del
módulo de datos no es `granted`.

| # | Ficha | MLS | Correduría | Permiso |
|---|---|---|---|---|
| 01 | 1221 Richmond Hill Road, Aspen | 194310 | Whitman Fine Properties | pendiente |
| 02 | 660 Brush Creek Road, Snowmass Village | 193160 | Aspen Snowmass Sotheby's International Realty — Hyman Mall | pendiente |
| 03 | Lakota Road, Indian Hills | 9072374 | Novella Real Estate | pendiente |
| 04 | Taylor Canyon, Gunnison | 189883 | Mirr Ranch Group LLC | pendiente |
| 05 | 29830 County Road 8, Yampa | 192889 | Hall and Hall Partners | pendiente |
| 06 | Red Mountain, Aspen | 193409 | Coldwell Banker Mason Morse — Aspen | pendiente |
| 07 | West Creek, Gateway | 189022 | Mirr Ranch Group LLC | pendiente |
| 08 | County Road 501, Bayfield | 5992563 | Live Water Properties | pendiente |
| 09 | Sweetwater Road, Gypsum | 189337 | Hall and Hall Partners | pendiente |
| 10 | Powderbowl Trail, Aspen | 193810 | Aspen Snowmass Sotheby's International Realty — Hyman Mall | pendiente |
| 11 | Fall Creek, Aspen | 193352 | Compass Aspen | pendiente |
| 12 | W Buttermilk, Aspen | 193933 | Compass Aspen | pendiente |

Son ocho corredurías distintas, no doce: Mirr Ranch, Hall and Hall, Sotheby's y
Compass tienen dos fichas cada una.

## El skyline

`public/blog/denver-skyline.jpg` sí está versionado. Lo entregó el cliente, sus
derechos están limpios y no es la ficha de nadie.
