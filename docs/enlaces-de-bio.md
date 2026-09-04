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
https://www.denverhomestory.com?utm_source=tiktok&utm_medium=social&utm_campaign=video&utm_content=piece-10
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

Cada una redirige (302, no 301: un permanente se cachea a fuego en el navegador
y el día que cambie la campaña estaríamos peleando con cachés de aparatos que no
podemos tocar) a la landing con su `utm_source`, `utm_medium=bio` y
`utm_campaign=profile`.

## Cómo comprobar que funciona

Abre cada uno de los tres desde el teléfono y luego, en el panel, mira
`/analytics`. Deben aparecer tres visitas con `source` distinto. Si aparecen como
`direct`, el enlace se pegó sin la query — algunas apps la recortan al guardarla,
y hay que volver a pegarlo comprobando que se guardó entero.

## Lo que esto NO resuelve

**La atribución por vídeo sigue sin ser certeza.** El enlace del pie va etiquetado,
pero en Shorts nadie puede pulsarlo: quien llega desde ahí teclea el dominio y
aparece como `direct`. Lo que se puede decir con honradez es *asociación
temporal* — visitas y leads en las 48 h siguientes a publicar — y la página lo
etiqueta así, nunca como «atribución».
