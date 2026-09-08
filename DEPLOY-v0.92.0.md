# Pre-despliegue v0.92.0 — Denver Home Story

**Estado: preparado. NO desplegado.** Requiere tu autorización en un mensaje aparte.

## Qué entra

Dos cambios, ambos de frontend. El backend solo cambia su cadena de versión.

1. **Nombre y apellido obligatorios** en los cuatro formularios públicos (`/`, `/fall`, `/calculator`, `/contact`). Las dos mitades se unen en el único campo `name` que ya acepta la API.
2. **El host del panel deja de servir las páginas públicas**: `inmo-demo.ekoaiautomation.com/fall`, `/contact` y `/calculator` pasan a **308** hacia `www.denverhomestory.com`, con la ruta y la query intactas.

## Precondiciones (medidas hoy, 8-sep, no supuestas)

| Comprobación | Estado |
|---|---|
| VPS en `2588c2c`, rama `feat/maquina-de-video-dhs`, árbol limpio | ✅ verificado |
| `/api/v1/health` del VPS | ✅ `0.92.0` esperado tras desplegar; hoy `0.91.0` |
| Los cuatro contenedores arriba (`backend`, `frontend`, `db`, `redis`) | ✅ |
| `2588c2c` es ancestro de la rama (el `--ff-only` no fallará) | ✅ |
| `origin/main` (`ab6b442`) también es ancestro | ✅ |
| **Migraciones** | ✅ **ninguna** — `alembic current` se queda en `055`, **no se ejecuta `alembic upgrade`** |
| **Variables de entorno nuevas** | ✅ **ninguna** — `.env.example` y `docker-compose.yml` sin cambios funcionales |
| Destino del 308 vivo | ✅ `www.denverhomestory.com` responde **200** en `/`, `/fall`, `/contact`, `/calculator` |
| Sesión par avisada, versión 0.92.0 concedida | ✅ |
| Bundle | ✅ `git bundle verify` limpio, 48.609 bytes |

**Precondición que hay que comprobar EN EL VPS antes de construir** — si estas dos variables están vacías o mal escritas, todo el cambio del host se despliega como **no-op silencioso**: sin error, sin log, y `/health` diría `0.92.0` igualmente.

```
ssh ender-vps 'grep -E "^NEXT_PUBLIC_(BRAND|PANEL)_URL=" ~/Eko-AI-RealEstate/.env'
```
Debe devolver exactamente:
```
NEXT_PUBLIC_BRAND_URL=https://www.denverhomestory.com
NEXT_PUBLIC_PANEL_URL=https://inmo-demo.ekoaiautomation.com
```

## Orden de pasos

**Hay que reconstruir, no basta con reiniciar.** El middleware se compila dentro de `.next` y los `NEXT_PUBLIC_*` se hornean en el build.

**Lo que hago yo** (llevar la rama; bundle, nunca push directo al VPS):
```
cd ~/eko-calculator && git bundle create /tmp/v092.bundle 2588c2c..feat/f4-version
scp /tmp/v092.bundle ender-vps:/tmp/
ssh ender-vps 'cd ~/Eko-AI-RealEstate && git fetch /tmp/v092.bundle feat/f4-version:refs/remotes/bundle/v092'
```

**Lo que ejecutas tú, en tu terminal** (el clasificador ha bloqueado `git merge --ff-only` en el VPS cuatro veces; no se rodea):
```
cd ~/Eko-AI-RealEstate && cp .env .env.bak.20260908_v0910
cd ~/Eko-AI-RealEstate && git merge --ff-only refs/remotes/bundle/v092
cd ~/Eko-AI-RealEstate && docker compose build backend frontend
cd ~/Eko-AI-RealEstate && docker compose up -d backend frontend
curl -s localhost:8011/api/v1/health
```
La última tiene que decir **0.92.0**. `docker compose ... backend frontend` nombra los dos servicios: `db`, `redis` y los stacks de Zorros y Black Volt no se tocan.

## Verificación posterior (con salida pegada)

```
# El panel redirige, con la cabecera que hace reversible un error
curl -sI https://inmo-demo.ekoaiautomation.com/fall       | grep -iE 'HTTP|location|cache-control'
curl -sI https://inmo-demo.ekoaiautomation.com/calculator | grep -iE 'HTTP|location|cache-control'
curl -sI https://inmo-demo.ekoaiautomation.com/contact    | grep -iE 'HTTP|location|cache-control'
#   -> 308 · cache-control: no-store · location: https://www.denverhomestory.com/…

# El panel sigue siendo el panel
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://inmo-demo.ekoaiautomation.com/    # 307 -> /leads
curl -s -o /dev/null -w '%{http_code}\n'                 https://inmo-demo.ekoaiautomation.com/leads # 200

# La marca sirve las cuatro
for p in / /fall /contact /calculator; do curl -s -o /dev/null -w "$p %{http_code}\n" "https://www.denverhomestory.com$p"; done  # 200 x4

# La versión
curl -s https://www.denverhomestory.com/api/v1/health   # 0.92.0
```
Más una captura real del formulario en producción a 390 px con los dos campos.

**Ningún lead de prueba a producción**: el aviso llega al correo real de Natalia.

## Reversión

```
cd ~/Eko-AI-RealEstate && git reset --hard 2588c2c
cd ~/Eko-AI-RealEstate && docker compose build backend frontend
cd ~/Eko-AI-RealEstate && docker compose up -d backend frontend
```
**Limpia y sin esquema que deshacer.** Los 308 salieron `no-store`, así que ningún navegador los cacheó: revertir devuelve el panel a servir las públicas de inmediato. El `.env` no cambia; la copia es por patrón, no por necesidad.

## Lo que quiero que sepas antes de autorizar

- **Dos campos obligatorios más cuestan conversión**, y el abandono **no se ve en el embudo**: la validación del navegador corta el envío antes de que se registre nada. Si el ritmo de leads cae, los datos no dirán por qué. Tú tomaste la decisión con este dato delante; lo repito porque es el momento de revisarla.
- **Los leads que ya existen no se rellenan.** El primer nombre guardado gana, así que quien ya esté como «Ana» sigue como «Ana» aunque reenvíe el formulario. Solo los nuevos traerán apellido.
- **Los enlaces de bio** (`/yt`, `/ig`, `/tt`) redirigen a `/?utm_source=…` con destino relativo, y la regla de `/` en el panel descarta la query. Si el enlace pegado en algún perfil apunta a `inmo-demo`, ese visitante acaba en el login y la atribución se pierde. **Merece que mires qué URL hay hoy en los tres perfiles**; no depende de este despliegue.
