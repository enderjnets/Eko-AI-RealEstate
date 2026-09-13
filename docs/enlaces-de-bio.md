# Los enlaces de bio, y por qué son la única atribución fiable por red

> Escrito el 4-sep-2026, después de medir el primer tráfico real.

## El problema, medido

Las primeras visitas reales a `denverhomestory.com` llegaron **todas como
`direct`**, sin referente. No es un fallo: es el techo del medio.

| Red | Qué pasa con el enlace |
|---|---|
| YouTube Shorts | el enlace de la descripción **no es pulsable** |
| Instagram | **borra el referente**; conserva la query |
| TikTok | acorta el enlace, pero **conserva la query** |
| Navegadores dentro de las apps | borran el referente |

O sea: leer `document.referrer` no sirve. **Una query en el enlace es la única
parte que sobrevive a las cuatro cosas.**

## Lo que ya hace el sistema solo

Desde la v0.75.0, el enlace del pie de cada vídeo sale etiquetado y **distinto en
cada red**. No hay que hacer nada:

```
https://www.denverhomestory.com/start?utm_source=tiktok&utm_medium=social&utm_campaign=video&utm_content=piece-10
```

`utm_source` dice la red, `utm_content` dice **qué vídeo**. Eso es lo que permite
decir «este vídeo trajo once visitas» en vez de «los vídeos trajeron once».

## Lo que hay que poner a mano, una vez

**Usa las rutas cortas.** La URL larga con `?utm_...` no se puede pegar en dos de
las tres redes, medido el 4-sep: TikTok solo ofrece el campo de sitio web en una
cuenta de empresa, e Instagram rechazó la edición. Además, varias apps recortan
en silencio todo lo que va detrás del `?` al guardar.

Una ruta corta esquiva las tres cosas — no hay query que perder, el perfil
muestra algo legible, y la etiqueta se pone en el servidor, donde está
versionada y probada en vez de escrita en el móvil de alguien:

| Red | Qué pegar |
|---|---|
| **YouTube** (Personalizar canal → Enlaces) | `https://www.denverhomestory.com/yt` |
| **TikTok** (Editar perfil → Sitio web) | `https://www.denverhomestory.com/tt` |
| **Instagram** (Editar perfil → Enlaces) | `https://www.denverhomestory.com/ig` |

También valen escritas enteras: `/youtube`, `/tiktok`, `/instagram`.

Cada una redirige temporalmente (307: un permanente se cachea a fuego en el
navegador y el día que cambie la campaña estaríamos peleando con cachés de
aparatos que no podemos tocar) a `/start` con su `utm_source`, `utm_medium=bio` y
`utm_campaign=profile`.

`/start` es una pantalla corta, bilingüe y pensada para el navegador interno de
las redes. Ofrece tres decisiones: calcular qué puede comprar, vender o conocer
el valor de una casa, o hablar con un asesor. Al seguir cualquiera de ellas se
conservan las etiquetas de la visita; el panel puede enlazar la red con la
acción, el lead y la cita que resulten.

## Cómo comprobar que funciona

Primero comprueba el salto sin cargar la página ni crear una visita. Por ejemplo:

```
curl -I https://www.denverhomestory.com/ig
```

La cabecera `location` debe empezar por
`/start?utm_source=instagram&utm_medium=bio&utm_campaign=profile`. Repite con
`/tt` y `/yt`, cambiando la fuente esperada a `tiktok` y `youtube`.

Para probar botones y formulario sin ensuciar las cifras medidas, abre **una
ventana privada nueva** en
`https://www.denverhomestory.com/start?utm_source=eko_qa&utm_medium=test`. La
ventana nueva importa porque el origen de una sesión se fija en su primera
visita. Esas sesiones aparecen en el total de pruebas excluidas, pero no entran
en visitas, engagement, acciones ni conversión. Si completas el formulario, el
lead de prueba permanece en el CRM para que se pueda auditar el flujo completo,
pero tampoco cuenta como lead, respuesta, llamada, cita o cierre en Analytics.

## Lo que esto NO resuelve

**La atribución exacta exige que sobreviva el enlace etiquetado.** El enlace de
cada contenido lleva red y `piece-<id>`, pero en Shorts nadie puede pulsarlo:
quien llega desde ahí teclea el dominio y aparece como `direct`. El panel separa
dos lecturas: atribución exacta cuando coinciden la etiqueta y la red, y
*asociación temporal* para visitas y leads en las 48 h siguientes a publicar.
La segunda nunca se presenta como certeza.
