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

El enlace del **perfil** de cada red no lo pone el sistema. Estos tres, tal cual,
en el sitio del enlace de cada perfil:

**YouTube** (`@denverhomestory` → Personalizar canal → Enlaces):
```
https://www.denverhomestory.com?utm_source=youtube&utm_medium=bio&utm_campaign=profile
```

**TikTok** (Editar perfil → Sitio web):
```
https://www.denverhomestory.com?utm_source=tiktok&utm_medium=bio&utm_campaign=profile
```

**Instagram** (Editar perfil → Enlaces → Enlace externo):
```
https://www.denverhomestory.com?utm_source=instagram&utm_medium=bio&utm_campaign=profile
```

`utm_medium=bio` es lo que los separa del pie de los vídeos: así se puede ver si
la gente llega desde el vídeo o desde el perfil, que son dos intenciones
distintas — una es curiosidad y la otra es alguien que fue a buscarte.

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
