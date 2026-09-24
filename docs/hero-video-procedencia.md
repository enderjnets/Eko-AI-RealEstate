# Procedencia del vídeo hero (`/landing/casa-hero.mp4`)

Registro de qué es exactamente ese vídeo, porque una parte está generada por IA y
la otra deriva de una foto con copyright de terceros. Si alguien tiene que
responder por este material algún día, que no dependa de la memoria de nadie.

## Qué se ve

Un plano continuo, sin cortes, de 20,57 s: la cámara retrocede desde el salón de
una casa, cruza unas puertas acristaladas, sale al patio pasando por debajo de la
sombrilla y se eleva hasta descubrir la casa entera al atardecer.

| Tramo | Qué es | Procedencia |
|---|---|---|
| 0,0 – 8,7 s | Interior: salón, chimenea, cruce de las puertas | **Generado por IA. No es esa casa. No es ninguna casa real.** |
| 8,7 – 20,57 s | Patio, sombrilla, jardín y fachada | Derivado de la foto original (ver abajo) |
| Último fotograma | La casa completa | Es la foto original, fotograma a fotograma |

## Foto original

- Fichero de trabajo: `3975285848.jpeg` (2528×1684)
- **Marca de agua: «©2026 Property of Aspen/Glenwood MLS»**
- Se recortó la franja inferior para quitar la marca de agua antes de usarla.
  Quitar la marca **no quita el copyright**.
- Del recorte salieron los dos fotogramas ancla del tramo exterior: el patio con
  la sombrilla (primer fotograma) y la vista general (último fotograma).

## Cómo se generó

- Motor: Kling AI, modelo `kling-v1-6`, modo `pro`, salida 1920×1080.
- Se rodó el vuelo **de fuera hacia dentro** y luego se invirtió, porque el modelo
  no atraviesa una puerta que no ve delante de la cámara.
- Tres clips encadenados: cada uno arranca en el último fotograma real del
  anterior, por eso no hay cortes ni fundidos.
- El interior no se copió de ninguna referencia: lo inventó el modelo.

## Versión vertical (`/landing/casa-hero-vertical.mp4`), 23-sep-2026

La web la sirve solo a pantallas verticales (`<source media="(max-aspect-ratio: 4/5)">`):
en un iPhone el 16:9 enseñaba una cuarta parte de su anchura, ampliada (feedback de
Demetra, «adjust aspect for iPhone»). Mismo recorrido y **misma foto de partida**,
elegido así por el dueño el 23-sep sabiendo lo del copyright (ver abajo).

- Cabecera: recorte 9:16 de `3975285848.jpeg` (`crop=800:1422:880:112`), **sin la marca
  de agua**, que queda fuera del recorte. Mismo caso que el 16:9: quitarla no quita el copyright.
- Motor: Kling AI **`kling-v3`**, modo `pro`, 1080×1920. `kling-v1-6` y todos los v1/v2.1
  están retirados por Kling desde antes del 23-sep. Coste medido: **0,8 unidades/s**.
- Tres clips encadenados, de fuera hacia dentro e invertidos, con los prompts del 16:9
  (el segundo gira a la derecha: en el 9:16 la puerta queda en el borde): jardín → bajo
  la sombrilla → patio (10 s) · giro y cruce de la puerta (5 s) · salón (5 s).
- Montaje: invertido, fotograma duplicado quitado en cada empalme, 0,5 s/1 s de pausa,
  30 fps, `-crf 25 -g 15 -bf 0 +faststart`, sin audio. 21,53 s, 14,2 MB.
  Barrido fotograma a fotograma: sin saltos aislados; el pico (8,6 s) es el marco de la
  puerta pasando junto a la cámara, varios fotogramas seguidos.
- El interior vuelve a ser **inventado por el modelo**: no es esa casa.
- `hero-poster-vertical.jpg` (720×1280) = su último fotograma. `poster` no admite
  `media`, así que `Landing.tsx` lo pone al montar con la misma consulta.
- Unidades: 16 en los tres clips + 5,6 de una sonda que por error creó un clip real.

## Restricciones de uso

1. **No sirve como material de un listing de esa propiedad.** El interior no es
   el suyo. Presentarlo como tal sería publicidad engañosa.
2. Como hero de marca —sin dirección, sin ficha, sin precio— no se afirma nada
   sobre ninguna propiedad concreta.
3. **Los derechos de la foto original están pendientes de confirmar** con la MLS
   o con el agente que la encargó. El dueño del proyecto asumió esa gestión de
   forma explícita el 3 de septiembre de 2026.

## Verificación

Los ficheros fuente, el arnés de tests y el detalle de cada fase están en
`~/Desktop/denverhomestory_hero/` (`PROJECT_STATUS.md` y `PRE-DEPLOY.md`).

## Aviso de integración pendiente

`LandingEffects.tsx` pone `v.loop = true` cuando el scroll pasa del 30% del hero.
Este vídeo **no es bucleable**: empieza dentro de la casa y termina en la foto
exterior, así que al reiniciarse da un salto duro con el hero aún en pantalla.
El arreglo mínimo es no forzar el bucle en esa rama y dejar que el vídeo se pare
en su último fotograma, que además es la imagen de la casa. No se ha tocado
porque ese fichero declara que cualquier diff de comportamiento es un bug.
