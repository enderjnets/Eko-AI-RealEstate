# Otoño 2026 — los 36 guiones de @denverhomestory

**Formato fijo, uno solo.** Réplica del paquete de `Dc_eGJtxy8E`, la única pieza
de la cuenta que funcionó: **485 reproducciones** contra una mediana de **6**,
el 63 % del alcance total. Lo que se mueve respecto a ella es **una sola cosa**,
el gancho, hacia lo contable y específico — el patrón común de todos los
outliers del nicho (`@coloradomamalife` 168,8 K con «7 fall-color day trips
within 90 minutes of Denver»; `@yourdenverrealtorco` 676 K con 2,9 K seguidores).

| | |
|---|---|
| Duración | **12–13 s**, cuatro clips de ~3,2 s |
| Voz | **ninguna** |
| Texto | **un bloque estático**, sostenido los 12 s. Nunca subtítulos karaoke |
| Música | `worker/assets/bgm/01-piano.mp3` |
| Bloque de marca | desde el **segundo 6**: el enlace, y debajo la línea de la correduría leída de la organización |
| Montaje | `worker/static_piece.py`. **No pasa por el obrero**, que añadiría voz y subtítulos |
| Alta | `POST /api/v1/content/upload?kind=generated` → `PATCH` → `submit` → **aprueba Natalia** |
| CTA | **uno solo por pieza.** Nueve piden comentario, nueve dan el enlace — ver abajo |
| Modelo de vídeo | `fal-ai/bytedance/seedance/v1/pro/fast/text-to-video`, 720p 9:16, 4 s por clip. El `…/v1/lite/…` que decía este documento está **retirado** y fal lo redirige en silencio a este mismo modelo: se llama por su nombre, nunca por el desvío. Precio por la fórmula de fal (`h × w × fps × s / 1024` tokens, $1/M fuera de 1080p), comprobada contra su precio publicado de 1080p: **≈ $0,08 por clip de 4 s a 704×1248**, ~$0,33 la pieza |

**La regla que no se rompe:** mientras el metraje sea generado, **ninguna pieza
nombra un sitio real en pantalla**. Es la misma regla que `frontend/lib/fallGuide.ts`
ya defiende para las fotos de la página. Las cinco piezas marcadas ★ sí lo
nombran, porque llevan la **foto con licencia de ese sitio**
(`frontend/public/landing/fall/`) con su crédito quemado en el fotograma.

Los `visual_prompt` van **en inglés**: un prompt en español no da error, devuelve
otra imagen. Sin personas, sin carteles, sin texto legible.

**Y van por imagen, no por texto.** Medido el 8-sep generando F1: pedirle el
clip directamente al modelo de vídeo da un otoño **europeo**. Cuatro tomas de
texto→vídeo dieron un abedular con hoja de arce, un pico alpino afilado con
alerces dorados y un mar de nubes carpático; el prior de «montaña en otoño» de
ese modelo no es Colorado. Añadir «no birch, no larch» **no lo arregla**: los
modelos de difusión ignoran las negaciones — se probó y volvió a dar abedul.

Lo que sí funciona es cambiar de modelo para la parte que falla. `flux/schnell`
($0,003) sí distingue el álamo temblón del abedul y el pico redondeado del
cuerno alpino. Así que el mecanismo de cada clip es:

1. `fal-gen image "<escena, nombrando Colorado y la especie>" --size portrait_16_9`
   → **mirar la imagen**; si el bioma está mal, se repite aquí, donde cuesta 3 milésimas.
2. Sacar la URL alojada del JSON (`images[0].url`) y pasarla **en el mismo minuto**
   a `fal-gen video --model fal-ai/bytedance/seedance/v1/pro/fast/image-to-video
   --image <url> --duration 4`. El prompt del vídeo describe **solo el
   movimiento** («slow drift», «leaves trembling»), nunca el contenido: el
   contenido ya lo fija la imagen.
3. Verificar el fichero (`ffprobe`: existe, 4,04 s, 704×1248) antes de montar.

Efecto colateral bueno: las cuatro tomas de una pieza comparten el look porque
las cuatro salen del mismo modelo de imagen.

---

## Parte 1 — Otoño (18 piezas, 3 por semana, 15-sep → 26-oct)

Las franjas y sus fechas salen de `frontend/lib/fallGuide.ts`. Ninguna fecha ni
distancia de este documento está inventada.

| Franja | Cuándo | Enlace |
|---|---|---|
| 1 · Above 9,500 ft | mid to late September | `/fall/1` |
| 2 · 7,000–9,000 ft | late September to mid October | `/fall/2` |
| 3 · 6,000–8,000 ft | most of October | `/fall/3` |
| 4 · Denver, 5,280 ft | October into November | `/fall/4` |

**Caption común a las 18** (cambia solo el primer párrafo y el enlace):

> …
>
> The full guide is 12 places sorted by elevation, each with the drive from
> Denver and the week to go. Nothing to fill in, no email needed to read it:
> denverhomestory.com/fall/N
>
> Denver Home Story · Natalia & Robbie · Real estate advisors, Engel & Völkers Aspen
>
> #colorado #denver #coloradofall #fall

### F1 — La escalera · `/fall/1` · 15-sep

**Pantalla:** `12 places near Denver, sorted by elevation.` / `The ones above 9,500 ft go first.`
**Clips:** aerial over a range of yellow aspen slopes among conifers, low cloud, late light · narrow mountain road climbing between golden aspens, no vehicles or signs · low angle up white aspen trunks, yellow leaves backlit · high ridge with first snow above and yellow just below treeline.
**Primer párrafo:** Aspens turn from the top down, so fall here isn't one weekend — it's six weeks moving downhill. Above 9,500 ft: mid to late September. The high passes go first, and they go fast — a windy week can end it.

### F2 — Por qué de arriba abajo · `/fall/1` · 17-sep

**Pantalla:** `Aspens turn from the top down.` / `That's why fall here lasts six weeks.`
**Clips:** same hillside in two exposures, upper third gold and lower third green · wide valley with a colour line partway up the slope · close on a single aspen crown against sky · slow pan down a slope from gold to green.
**Primer párrafo:** Higher means colder sooner, and colder sooner means gold sooner. So the useful question is never *where* — it is *how high, this week*.

### F3 — La semana de viento · `/fall/1` · 19-sep

**Pantalla:** `One windy week can end it.` / `Above 9,500 ft, that's the whole risk.`
**Clips:** aspen leaves shaking hard in wind, blurred motion · bare pale trunks with a thin gold canopy left · leaves on a dirt road surface · overcast ridge with scattered gold.
**Primer párrafo:** The high passes are the shortest window of the season and the least forgiving. If the forecast has wind, go before it, not after.

### F4 — ★ Guanella Pass · `/fall/1` · 22-sep

**Foto:** `guanella-pass.jpg` (CC, crédito quemado). **Sí nombra el sitio.**
**Pantalla:** `Guanella Pass. 40 miles from Denver.` / `Above 9,500 ft — it goes first.`
**Primer párrafo:** Forty miles out and the whole byway is above the band that turns first.

### F5 — ★ Kenosha Pass · `/fall/1` · 24-sep

**Foto:** `kenosha-pass.jpg`.
**Pantalla:** `Kenosha Pass. 60 miles, US 285.` / `Mid to late September.`
**Primer párrafo:** Sixty miles on US 285, and one of the widest stands of aspen on the Front Range.

### F6 — ★ Peak to Peak · `/fall/1` · 26-sep

**Foto:** `peak-to-peak.jpg`.
**Pantalla:** `Peak to Peak Byway.` / `CO 72 and CO 7, end to end in an afternoon.`
**Primer párrafo:** Not a pass but a byway — the one you drive rather than park at.

### F7 — La franja ancha · `/fall/2` · 29-sep

**Pantalla:** `Between 7,000 and 9,000 ft:` / `the widest window of the season.`
**Clips:** mid valley, mixed gold and dark green slopes, river below · aspen forest on a slope, side light, low mist lifting · mountain reservoir with a golden shoreline reflected · narrow-gauge rails through aspens, no train.
**Primer párrafo:** Late September into mid October. It is the band that survives a bad forecast: when the passes are already bare, this is still going.

### F8 — Un viaje, dos franjas · `/fall/2` · 1-oct

**Pantalla:** `Late September, one drive,` / `two bands of colour.`
**Clips:** road descending from bare high ground into gold · two-tone hillside · switchback with gold below and grey above · wide shot with snowline and colour in one frame.
**Primer párrafo:** The high band ending and the middle band starting overlap by about a week. That week is the only one where a single drive shows you both.

### F9 — ★ Georgetown Loop · `/fall/2` · 3-oct

**Foto:** `georgetown-loop.jpg`.
**Pantalla:** `Georgetown Loop. 40 miles out.` / `The one you ride, not drive.`
**Primer párrafo:** Forty miles from Denver and the only entry on the guide you experience from a train window.

### F10 — Entre semana · `/fall/2` · 6-oct

**Pantalla:** `The colour is the same on a Tuesday.` / `The parking is not.`
**Clips:** empty pull-out at golden hour · full pull-out, cars, midday · quiet trail through aspens · empty overlook with long shadows.
**Primer párrafo:** Everything on this list is better between Monday and Thursday, and the difference is not the leaves.

### F11 — Cuando parece acabado · `/fall/3` · 8-oct

**Pantalla:** `When the passes are bare,` / `everyone assumes it's over. It isn't.`
**Clips:** low canyon with red oak and yellow aspen, grey rock, clear October sky · dirt road among ponderosa with golden understory · low mountainside with patches of colour among dry grassland · historic mountain town seen from a distance, wooden facades, no legible signage.
**Primer párrafo:** Most of October belongs to the band between 6,000 and 8,000 ft.

### F12 — ★ Golden Gate Canyon · `/fall/3` · 10-oct

**Foto:** `golden-gate-canyon.jpg`.
**Pantalla:** `Golden Gate Canyon State Park.` / `Northwest of Golden — most of October.`
**Primer párrafo:** Northwest of Golden, and it holds colour for weeks after the passes have finished.

### F13 — El roble que nadie cuenta · `/fall/3` · 13-oct

**Pantalla:** `Aspens get the photographs.` / `The oak is what October actually looks like.`
**Clips:** scrub oak turning deep red on a hillside · red and gold mixed against grey rock · close on red oak leaves · wide low-elevation slope in red.
**Primer párrafo:** Gambel oak turns red and rust rather than gold, it grows lower down, and it is most of the colour left in the second half of October.

### F14 — Un pueblo de montaña · `/fall/3` · 15-oct

**Pantalla:** `Some of this band is a town,` / `not a trailhead.`
**Clips:** historic wooden storefronts among yellow trees, no legible signs · quiet street with leaves on brick · porch and railing with gold behind · main street at low sun.
**Primer párrafo:** Two of the three places in this band are somewhere you park and walk around rather than somewhere you hike.

### F15 — Las últimas tres semanas · `/fall/4` · 17-oct

**Pantalla:** `The last three weeks of colour` / `happen at 5,280 ft.`
**Clips:** tree-lined residential street, yellow leaves, brick sidewalks · canal path with golden cottonwoods both sides · urban lake with mountains behind · wide city park, empty bench, last light.
**Primer párrafo:** October into November, at home. The part people forget.

### F16 — Sin coche · `/fall/4` · 20-oct

**Pantalla:** `Denver's best fall week` / `does not require a car.`
**Clips:** creek path under cottonwoods · bridge over water with gold on both banks · bike path through leaves · bench facing a lake.
**Primer párrafo:** A canal trail that crosses the whole metro, and the creek trails out of downtown.

### F17 — El árbol de la calle · `/fall/4` · 22-oct

**Pantalla:** `The street trees are the reason` / `some blocks feel different in October.`
**Clips:** mature street trees arching over a residential road · leaves against a porch · same street wide, low sun · pavement covered in yellow.
**Primer párrafo:** Denver's canopy is not evenly distributed, and October is the month you can see exactly where it is.

### F18 — Cierre · `/fall/4` · 26-oct

**Pantalla:** `Twelve places, sorted by when to go.` / `The season, from 9,500 ft down to 5,280.`
**Clips:** high ridge with snow · mid valley in gold · low canyon in red · city street with leaves.
**Primer párrafo:** Six weeks, four bands, twelve places. This is the whole season in one list, and it stays up for next year.

---


## El CTA va partido en TRES, y por qué

**Seis piezas dan el enlace, seis piden un comentario, seis piden un reenvío.**
Rotando (F1 enlace, F2 comentario, F3 reenvío, F4 enlace…), no en bloques: así
el clima de la semana y la franja de altitud afectan igual a los tres grupos, y
a los quince días la diferencia de alcance y de leads se puede leer.

**Por qué tres y no dos.** Instagram publicó cuáles son sus señales de
ranking, y no coinciden con la intuición. Las tres que Mosseri nombra como más
importantes en 2026 son **tiempo de visionado**, **`sends per reach`** y likes;
en sus palabras, «piensa en crear algo que la gente quiera **enviar a un
amigo**». Un envío por DM pesa **3-5× más que un like** para llegar a quien no
te sigue. **Los comentarios cuentan, pero van terceros**, y solo si son más que
un emoji.

Y hay una distinción que se confunde en casi todo lo que se lee: «sends» es un
**espectador reenviando el reel a otra persona**, no el DM que la marca le
manda a él. La mecánica del comentario sube la señal nº 3; lo que sube la nº 1
es que la pieza sea *reenviable*. Una guía de dónde ver los álamos lo es por
naturaleza —se manda a la persona con la que irías el sábado—, así que el
trabajo no es forzarlo sino no estorbarlo.

| Grupo | Piezas | Última línea del texto |
|---|---|---|
| **Enlace** | F1, F4, F7, F10, F13, F16 | `Free guide → denverhomestory.com/fall/N` |
| **Comentario** | F2, F5, F8, F11, F14, F17 | `Comment FALL and I'll send you the guide` |
| **Reenvío** | F3, F6, F9, F12, F15, F18 | `Send this to whoever you'd go with` + el enlace |

**Regla dura del grupo «comentario»: el enlace NO aparece en ninguna parte** —
ni en pantalla, ni en la caption. Ya se probó al revés y dio 0 %: el reel de
otoño llevaba «Comment FALL for the guide» **y** el enlace en su propia
caption. Cuatro comentarios, ninguno escribió FALL. Nadie pide lo que ya tiene
delante. Una sola puerta o la mecánica no existe.

**Regla del grupo «reenvío»: el dato tiene que merecer el reenvío.** Una fecha
concreta, una distancia, «una semana de viento lo acaba». Nadie manda a un
amigo un paisaje bonito; manda un plan.

🔴 **Lo que bloquea el grupo «comentario» a escala.** La automatización
comentario→DM es legítima y va por la API oficial de Meta, pero exige una
**cuenta Business enlazada a una página de Facebook**, y según el estado del
proyecto eso sigue **pendiente desde el 25-ago-2026**. Sin esa página, cada
comentario lo contesta una persona el mismo día — una promesa de enlace que
tarda dos días es peor que no haberla hecho. Con ella, es instantáneo.

**Lo que se gana igualmente:** un comentario es un nombre al que Natalia ya
está escribiendo, y el enlace que le mande puede ser
`denverhomestory.com/fall/N`, así que **la atribución por pieza se conserva**
aunque vaya por mensaje privado.

## Parte 2 — Calculadora (18 piezas, 3 por semana, permanente)

**Los números salen de `frontend/lib/calculator.ts`** ejecutada con `DEFAULTS`,
crédito `good`. No hay ni una cifra inventada. Los supuestos —tasa, apreciación,
impuestos, seguro— están **a la vista y son editables en la página**, y cada
caption lo dice.

| Renta/mes | Ahorro | Precio tope | Neto a 5 años |
|---|---|---|---|
| $1,800 | $60,000 | **$279,070** | +$17,133 |
| $2,200 | $60,000 | **$313,263** | +$21,760 |
| $2,600 | $60,000 | **$360,794** | +$20,996 |
| $3,000 | $60,000 | **$408,325** | +$24,359 |
| $3,500 | $60,000 | **$467,682** | +$28,590 |
| $4,000 | $60,000 | **$527,039** | +$32,820 |

Efecto del ahorro, con la renta fija en $2,600: **$40,000 → $343,475** ·
**$60,000 → $360,794** · **$80,000 → $378,113**.

**Caption común a las 18:**

> …
>
> The assumptions are on the page and you can change them — rate, appreciation,
> taxes, insurance. Nothing to fill in to see the number:
> denverhomestory.com/calculator
>
> Denver Home Story · Natalia & Robbie · Real estate advisors, Engel & Völkers Aspen
>
> #colorado #denver #denverrealestate #firsttimehomebuyer

**Clips (compartidos, cuatro por pieza):** Denver residential street with
bungalows, morning light · front door and porch of a brick home, no numbers
visible · kitchen window with light across a counter · wide view of a Denver
neighbourhood with the Front Range behind.

### Serie A — «esa renta compra hasta» (6 piezas: C1–C6)

Pantalla, una por renta:

- **C1** `$1,800 a month in rent` / `buys up to $279,000.`
- **C2** `$2,200 a month in rent` / `buys up to $313,000.`
- **C3** `$2,600 a month in rent` / `buys up to $360,000.`
- **C4** `$3,000 a month in rent` / `buys up to $408,000.`
- **C5** `$3,500 a month in rent` / `buys up to $467,000.`
- **C6** `$4,000 a month in rent` / `buys up to $527,000.`

**Primer párrafo:** The same money you already pay every month, turned into a
price. With $60,000 saved and good credit, at today's assumptions.

### Serie B — «lo que cambia el ahorro» (6 piezas: C7–C12)

- **C7** `$40,000 saved: up to $343,000.` / `$80,000 saved: up to $378,000.`
- **C8** `Doubling the deposit` / `moves the ceiling by $35,000. Not double.`
- **C9** `The deposit is not the ceiling.` / `The monthly payment is.`
- **C10** `Same rent, more savings,` / `and the price barely moves. Here's why.`
- **C11** `What $20,000 more actually buys` / `at $2,600 a month.`
- **C12** `Most people over-estimate the deposit` / `and under-estimate the rate.`

**Primer párrafo (C7–C12):** At $2,600 a month, going from $40,000 saved to
$80,000 moves the ceiling from $343,000 to $378,000 — real, and smaller than
most people expect. What sets the ceiling is what you can pay every month.

### Serie C — «comprar vs. alquilar a cinco años» (6 piezas: C13–C18)

- **C13** `$2,200 a month, five years:` / `about $21,700 ahead by buying.`
- **C14** `$2,600 a month, five years:` / `about $21,000 ahead.`
- **C15** `$3,000 a month, five years:` / `about $24,300 ahead.`
- **C16** `$3,500 a month, five years:` / `about $28,500 ahead.`
- **C17** `$4,000 a month, five years:` / `about $32,800 ahead.`
- **C18** `Five years is the number that matters,` / `not the monthly payment.`

**Primer párrafo:** Rent, appreciation, the loan you pay down, the cost of
selling — all of it, over five years. The appreciation assumption is the one
that moves this most, and it is a slider on the page, not a promise.

---

## Lo que hay que verificar antes de publicar

1. **`/fall/1..4` vivas en producción.** Hoy dan 404 hasta que se despliegue la
   0.93.0. Mientras: `denverhomestory.com/fall` pelado, sin atribución.
2. **Una pieza de prueba primero**, montada y vista por el dueño, antes de
   generar los 52 clips restantes (D-2).
3. **`RENDER_STOCK_FALLBACK=false`** en el ROG antes de la primera educativa.
4. **Aprueba Natalia**, siempre. Ninguna pieza se publica sin pasar por
   `POST /content/{id}/approve`.
