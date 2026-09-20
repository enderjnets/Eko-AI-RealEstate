/**
 * La puerta de publicacion de The Journal.
 *
 * Existe porque «desplegado» y «publicado» no son lo mismo aqui, y confundirlos
 * cuesta dinero de verdad. El codigo puede vivir en produccion —y conviene, es
 * la unica forma de probarlo contra la instalacion real— mucho antes de que las
 * ocho corredurias hayan dado por escrito el permiso que exige la Regla
 * 6.10.F.1.a de Colorado para difundir el anuncio de otro corredor.
 *
 * Con `false`:
 *   - las dos paginas declaran `robots: index:false, follow:false`;
 *   - la portada no enlaza The Journal ni en la navegacion, ni en el menu del
 *     movil, ni en el pie.
 *
 * Con `true`, `lib/__tests__/journal.test.ts` exige que **las doce** fichas
 * tengan `permission: "granted"`. Ponerlo a `true` con una sola pendiente pone
 * la suite en rojo, que es justo lo que tiene que pasar.
 *
 * Lo que falta para poder cambiarlo esta en `lib/journal/DERECHOS.md`, fila a
 * fila. No se cambia esta linea sin haber leido ese fichero.
 */
export const PUBLISHED = false;
