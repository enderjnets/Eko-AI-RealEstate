/**
 * Las dos puertas de The Journal.
 *
 * Existen porque «desplegado», «enlazado» y «indexado» no son lo mismo aqui, y
 * meterlos en una sola constante fue un error de diseno mio: obligaba a elegir
 * entre no ensenar la seccion a nadie o entregarsela a Google. Son dos
 * decisiones distintas, con dos costes distintos, y una de ellas no se deshace.
 *
 * `LINKED` — la portada enlaza The Journal en la navegacion, en el menu del
 * movil y en el pie. Es **reversible**: se apaga, se despliega y en un minuto
 * no hay rastro. Quien llega es una persona que ya estaba en nuestra web.
 *
 * `INDEXED` — `robots: index/follow` en las dos paginas y la entrada del
 * sitemap. Es la mitad que **no se deshace**: una vez que el rastreador pasa,
 * las cuarenta y ocho fotografias —de ocho corredurias ajenas, y con el 11%
 * inferior recortado, que es justo donde iba la marca de agua de copyright del
 * MLS— quedan en cache y en resultados de busqueda aunque la pagina se apague
 * el mismo dia. Esta es la que la Regla 6.10.F.1.a de Colorado mira de verdad:
 * difundir el anuncio de otro corredor exige su permiso escrito.
 *
 * Con `INDEXED = true`, `lib/__tests__/journal.test.ts` exige que **las doce**
 * fichas tengan `permission: "granted"`. Ponerlo a `true` con una sola
 * pendiente pone la suite en rojo, que es justo lo que tiene que pasar.
 *
 * Lo que falta para poder cambiarlo esta en `lib/journal/DERECHOS.md`, fila a
 * fila. Ese fichero dice la verdad pase lo que pase aqui: ninguna fila pasa a
 * «concedido» sin un permiso que exista.
 */

/** 20-sep-2026: Ender pidio el acceso desde la portada. Reversible. */
export const LINKED = true;

/** Sigue cerrada: las doce fichas siguen en «pendiente». No es reversible. */
export const INDEXED = false;
