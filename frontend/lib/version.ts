export const CURRENT_VERSION = "0.54.1";

/** A string available in both UI languages. Rendered per the active language. */
export interface LocalizedText {
  en: string;
  es: string;
}

export interface VersionEntry {
  version: string;
  date: string;
  title: LocalizedText;
  changes: LocalizedText[];
}

export const CHANGELOG: VersionEntry[] = [
  {
    version: "0.54.1",
    date: "2026-08-20",
    title: {
      en: "Two gaps closed before they could open",
      es: "Dos huecos cerrados antes de poder abrirse",
    },
    changes: [
      {
        en: "First full audit of the Content Studio. Both findings were latent \u2014 the publisher does not exist yet, so neither was visible today \u2014 and closing them before it exists is what auditing is for. The watchdog over the future publisher trusted names (a publisher called anything but publish_* would have skipped the approval gate with everything green); it now classifies by what a function does, and everything that touches the wire must be declared or exempted with a reason.",
        es: "Primera auditor\u00eda completa del Estudio de Contenido. Los dos hallazgos eran latentes \u2014 el publicador a\u00fan no existe, as\u00ed que ninguno era visible hoy \u2014 y cerrarlos antes de que exista es para lo que se audita. La vigilancia del futuro publicador se fiaba de los nombres (un publicador llamado de otra forma habr\u00eda saltado la puerta de aprobaci\u00f3n con todo en verde); ahora clasifica por lo que la funci\u00f3n hace, y todo lo que toca la red debe estar declarado o exento con motivo.",
      },
      {
        en: "One agency could reference another's piece: the database's existence check does not pass through tenant isolation, so agency B could plant a publication record on a piece of agency A it cannot even read \u2014 blocking A from ever recording its own. The database itself now requires publication and piece to belong to the same agency. Plus: the Fair Housing filter learns \"kid-free\"/\"child-free\", and the counter repair pins its exact edges in tests.",
        es: "Una agencia pod\u00eda referenciar la pieza de otra: la comprobaci\u00f3n de existencia de la base de datos no pasa por el aislamiento entre agencias, as\u00ed que la agencia B pod\u00eda plantar un registro de publicaci\u00f3n sobre una pieza de la agencia A que ni siquiera puede leer \u2014 bloqueando que A registrara la suya. Ahora la base de datos misma exige que publicaci\u00f3n y pieza pertenezcan a la misma agencia. Adem\u00e1s: el filtro de vivienda justa aprende \"kid-free\"/\"child-free\", y la reparaci\u00f3n de contadores fija sus bordes exactos en pruebas.",
      },
    ],
  },
  {
    version: "0.54.0",
    date: "2026-08-20",
    title: {
      en: "Phone clips come out ready to publish",
      es: "El clip del móvil sale listo para publicar",
    },
    changes: [
      {
        en: "The Content Studio's first render lane: a clip filmed on the phone becomes a vertical 1080\u00d71920 video on its own \u2014 scaled over a blurred copy of itself, never cropped, because the agent framed the shot. And your brokerage identification is BURNED into the final seconds of the video itself: Colorado requires advertising to identify the brokerage, and burned pixels survive every platform's crops, mutes and re-encodes where a caption does not. Without a brokerage line in Settings, clips wait with the reason visible and render themselves the moment it is filled in.",
        es: "El primer carril de render del Estudio de Contenido: un clip grabado con el tel\u00e9fono se convierte solo en un v\u00eddeo vertical 1080\u00d71920 \u2014 escalado sobre una copia desenfocada de s\u00ed mismo, nunca recortado, porque el encuadre lo eligi\u00f3 el agente. Y la identificaci\u00f3n de su brokerage va QUEMADA en los segundos finales del propio v\u00eddeo: Colorado exige que la publicidad identifique la brokerage, y unos p\u00edxeles grabados sobreviven a los recortes, silencios y re-codificaciones de cada plataforma donde un pie de texto no. Sin l\u00ednea de brokerage en Ajustes, los clips esperan con el motivo visible y se renderizan solos en cuanto se rellena.",
      },
      {
        en: "The quality gate measures structure, never looks: there is a video stream, the duration is workable, the original's audio survived. The output is verified against the file that exists, not the command that ran \u2014 a render that claimed success but produced something else is a failed render. A corrupt clip fails visibly on its own row and never blocks the rest.",
        es: "La puerta de calidad mide estructura, nunca est\u00e9tica: que haya v\u00eddeo, que la duraci\u00f3n sea trabajable, que el audio del original siga en el resultado. La salida se verifica contra el archivo que existe, no contra el comando que corri\u00f3 \u2014 un render que dijo \u00e9xito pero produjo otra cosa es un render fallido. Un clip corrupto falla visible en su propia fila y nunca bloquea a los dem\u00e1s.",
      },
    ],
  },
  {
    version: "0.53.1",
    date: "2026-08-20",
    title: {
      en: "The repair of the counter our own fix poisoned",
      es: "La reparación del contador que nuestra propia corrección envenenó",
    },
    changes: [
      {
        en: "0.51.2 gave the consent fortnight its own counter, and its data migration copied the error-inflated total: a client held ONCE who sat through an outage arrived with the counter at 14, their second real hold became give-up number fifteen, and the whole sequence died two days after the viewing \u2014 the very defect that release fixed, resurrected by its own migration. The repair caps the counter at the days actually elapsed (holds happen at most once a day), so an honestly-held row keeps its exact count and a poisoned one gets its fortnight back. And this time the migration has tests that run it against data \u2014 which is precisely what was missing the first time.",
        es: "La 0.51.2 le dio contador propio a la quincena de permiso, y su migraci\u00f3n de datos copi\u00f3 el total inflado por errores: un cliente retenido UNA vez que atraves\u00f3 una aver\u00eda llegaba con el contador en 14, su segunda retenci\u00f3n real se convert\u00eda en la rendici\u00f3n n\u00famero quince, y la secuencia entera mor\u00eda dos d\u00edas despu\u00e9s de la visita \u2014 el mismo defecto que esa versi\u00f3n arreglaba, resucitado por su propia migraci\u00f3n. La reparaci\u00f3n acota el contador a los d\u00edas realmente transcurridos (las retenciones son como mucho una al d\u00eda): una fila retenida con honestidad conserva su cuenta exacta y una envenenada recupera su quincena. Y esta vez la migraci\u00f3n tiene pruebas que la ejecutan contra datos \u2014 justo lo que falt\u00f3 la primera vez.",
      },
      {
        en: "A transient error no longer pardons a stale message: its retry mark used to count as \"somebody decided to defer this\", so after a long outage the twin that had erred days ago went out 30 hours late while the clean one was cancelled. An error's mark buys its retry hour and nothing more. The error counter also measures one episode now, not a lifetime.",
        es: "Un error pasajero ya no indulta un mensaje rancio: su marca de reintento contaba como \"alguien decidi\u00f3 aplazar esto\", as\u00ed que tras una ca\u00edda larga el gemelo que err\u00f3 hace d\u00edas sal\u00eda 30 horas tarde mientras el limpio se cancelaba. La marca de un error compra su hora de reintento y nada m\u00e1s. El contador de errores adem\u00e1s mide ahora un episodio, no una vida.",
      },
      {
        en: "The watchdog over sending channels no longer trusts names: it only examined functions called send_*, so a new channel named anything else shipped with zero opt-out enforcement and everything green. It now classifies by what a function DOES, and all three escape shapes found across three audit rounds are caught.",
        es: "La vigilancia de canales de env\u00edo ya no se f\u00eda de los nombres: solo examinaba funciones llamadas send_*, as\u00ed que un canal nuevo con otro nombre entraba con cero control de bajas y todo en verde. Ahora clasifica por lo que la funci\u00f3n HACE, y las tres formas de fuga halladas en tres rondas de auditor\u00eda quedan cazadas.",
      },
    ],
  },
  {
    version: "0.53.0",
    date: "2026-08-20",
    title: {
      en: "The Content Studio writes drafts on its own",
      es: "El Estudio de Contenido escribe borradores solo",
    },
    changes: [
      {
        en: "Daily generated drafts \u2014 off by default, capped at 3 per day, and still publishing nothing: generated work lands, at most, in the console's approval queue. Topics rotate through the Denver questions every buyer and seller asks (inspections, offer to close, earnest money, pre-approval, reading the market), the language alternates between the ones your agency works in, and property listings are deliberately out until the MLS feed and image rights exist.",
        es: "Borradores generados a diario \u2014 apagado de f\u00e1brica, tope de 3 al d\u00eda, y sigue sin publicar nada: lo generado termina, como mucho, en la cola de aprobaci\u00f3n de la consola. Los temas rotan por las preguntas de Denver que todo comprador y vendedor hace (inspecci\u00f3n, de la oferta al cierre, dep\u00f3sito de seriedad, preaprobaci\u00f3n, leer el mercado), el idioma alterna entre los que trabaje su agencia, y las fichas de propiedades quedan fuera a prop\u00f3sito hasta tener feed MLS y derechos de imagen.",
      },
      {
        en: "The Fair Housing filter corrects the machine before it corrects anyone: a draft that comes out with forbidden phrasing gets exactly one rewrite with the phrases named, and if it comes back dirty it stays in Drafts wearing the findings for a person to edit. A flagged draft never walks itself into the queue.",
        es: "El filtro de vivienda justa corrige a la m\u00e1quina antes que a nadie: un borrador con frases prohibidas recibe exactamente una reescritura con las frases nombradas, y si reincide se queda en Borradores con los hallazgos puestos para que una persona lo edite. Un borrador marcado nunca entra solo en la cola.",
      },
    ],
  },
  {
    version: "0.52.0",
    date: "2026-08-20",
    title: {
      en: "Content Studio: the rail and the gate",
      es: "Estudio de Contenido: el carril y la puerta",
    },
    changes: [
      {
        en: "A new Content tab in the console: drafts, pieces awaiting approval, approved and rejected, with an inline editor and a player for clips. Nothing generates or publishes yet \u2014 this release deliberately builds the gate first: nothing can ever be published without a person approving it here, and the approval records who and when. Editing an approved piece sends it back to the queue, because the approval was of the old text.",
        es: "Nueva pesta\u00f1a Contenido en la consola: borradores, piezas por aprobar, aprobadas y rechazadas, con editor en l\u00ednea y reproductor para clips. Todav\u00eda no genera ni publica nada \u2014 esta versi\u00f3n construye primero la puerta, a prop\u00f3sito: nada puede publicarse sin que una persona lo apruebe aqu\u00ed, y la aprobaci\u00f3n registra qui\u00e9n y cu\u00e1ndo. Editar una pieza aprobada la devuelve a la cola: lo aprobado era el texto anterior.",
      },
      {
        en: "A deterministic Fair Housing filter, in English and Spanish. Over 90 phrases that cannot appear in housing advertising \u2014 \"perfect for families\", \"safe neighborhood\", \"good schools\" \u2014 are flagged as you write, on submit, and AGAIN at publish time. A draft with flagged phrases stays a draft, with the phrases named, until a person fixes them.",
        es: "Filtro de vivienda justa determinista, en ingl\u00e9s y espa\u00f1ol. M\u00e1s de 90 frases que no pueden aparecer en publicidad de vivienda \u2014 \"perfect for families\", \"barrio seguro\", \"good schools\" \u2014 se marcan al escribir, al enviar y OTRA VEZ al publicar. Un borrador con frases marcadas se queda en borrador, con las frases se\u00f1aladas, hasta que una persona las corrige.",
      },
      {
        en: "Without your brokerage identification nothing publishes: Colorado requires advertising to identify the brokerage, the field now lives in Settings, and the gate refuses while it is empty. Plus: clip uploads from the phone (up to 500 MB, streamed), served only behind sign-in and inside each agency's boundary.",
        es: "Sin la identificaci\u00f3n de su brokerage nada se publica: Colorado exige que la publicidad identifique la brokerage, el campo vive ahora en Ajustes y la puerta se niega mientras est\u00e9 vac\u00edo. Adem\u00e1s: subida de clips desde el m\u00f3vil (hasta 500 MB, en streaming), servidos solo tras iniciar sesi\u00f3n y dentro de la frontera de cada agencia.",
      },
    ],
  },
  {
    version: "0.51.2",
    date: "2026-08-19",
    title: {
      en: "An hour of errors no longer kills a whole sequence",
      es: "Una hora de errores ya no mata una secuencia entera",
    },
    changes: [
      {
        en: "One counter was doing three jobs: the days we have waited for permission to write to a client, failures picking a channel, and delivery attempts. Only the first should ever exhaust the fortnight of retries \u2014 but any of the three spent it, and the error path left no \"try again later\" mark, so the message fell due again five minutes on. Thirteen passes of a one-hour outage burned thirteen days of grace; two ordinary passes later the sequence closed, and since 0.51.0 it closes entirely. A client who viewed a property on the 3rd received none of the three messages and the sequence was dead on the 5th. The fortnight now has its own counter and only a wait for permission can spend it.",
        es: "Un contador hac\u00eda tres trabajos: los d\u00edas esperando permiso para escribir a un cliente, los fallos al elegir canal, y los intentos de env\u00edo. Solo el primero debe agotar la quincena de reintentos \u2014 pero cualquiera la gastaba, y la rama de error no dejaba marca de \"reintentar luego\", as\u00ed que el mensaje volv\u00eda a vencer a los cinco minutos. Trece pasadas de una aver\u00eda de una hora agotaban trece d\u00edas de margen; dos pasadas despu\u00e9s la secuencia se cerraba, y desde la 0.51.0 se cierra entera. Un cliente que visit\u00f3 una propiedad el d\u00eda 3 no recib\u00eda ninguno de los tres mensajes y la secuencia mor\u00eda el d\u00eda 5. Ahora la quincena tiene contador propio y solo una espera de permiso puede gastarla.",
      },
      {
        en: "A follow-up with no viewing attached no longer reaches your other clients. The cascade looked for \"the rest of the messages about this viewing\"; on a call reminder, which has no viewing, that meant every call reminder in the account.",
        es: "Un seguimiento sin visita ya no alcanza a sus dem\u00e1s clientes. El cierre en cadena buscaba \"los dem\u00e1s mensajes de esta visita\"; en un recordatorio de llamada, que no tiene visita, eso significaba todos los recordatorios de llamada de la cuenta.",
      },
      {
        en: "Two ways of sending could slip past the opt-out safeguard \u2014 one common form of HTTP request it did not recognise, and anything outside one folder, which is exactly where the voice channel is going to live. Both are covered now.",
        es: "Dos formas de enviar pod\u00edan escaparse del control de bajas: una manera habitual de hacer una petici\u00f3n HTTP que no reconoc\u00eda, y cualquier cosa fuera de una carpeta concreta \u2014 justo donde va a vivir el canal de voz. Las dos quedan cubiertas.",
      },
    ],
  },
  {
    version: "0.51.1",
    date: "2026-08-19",
    title: {
      en: "Three guards that were not guarding",
      es: "Tres salvaguardas que no salvaguardaban",
    },
    changes: [
      {
        en: "Found by deleting each of yesterday's fixes and checking whether anything went red. None of these changes what you receive; all three change what we can promise you about what is already running.",
        es: "Encontrados borrando cada arreglo de ayer y comprobando si algo se pon\u00eda en rojo. Ninguno cambia lo que usted recibe; los tres cambian lo que podemos garantizarle sobre lo que ya est\u00e1 en marcha.",
      },
      {
        en: "A message already given up on could keep taking retries. When a whole sequence was closed, the messages that fell with it went back through the sending rules in the same pass and ended up marked \"retry tomorrow\" despite being closed \u2014 a record that contradicts itself, and the one the console reads.",
        es: "Un mensaje ya descartado pod\u00eda seguir acumulando reintentos. Al cerrar una secuencia entera, los mensajes que ca\u00edan con ella volv\u00edan a pasar por las reglas de env\u00edo en la misma pasada y quedaban marcados como \"reintentar ma\u00f1ana\" pese a estar cerrados \u2014 un registro que se contradice a s\u00ed mismo, y es el que lee la consola.",
      },
      {
        en: "The 30-day limit was anchored to nothing: it could be changed without any check noticing. We verified that by setting it to 114 days and watching everything stay green. It is now pinned to the number we publish here.",
        es: "El plazo de 30 d\u00edas no estaba anclado a nada: se pod\u00eda cambiar sin que ninguna comprobaci\u00f3n se enterara. Lo verificamos poni\u00e9ndolo en 114 d\u00edas y viendo que todo segu\u00eda en verde. Ahora est\u00e1 fijado al n\u00famero que publicamos aqu\u00ed.",
      },
    ],
  },
  {
    version: "0.51.0",
    date: "2026-08-19",
    title: {
      en: "A follow-up sequence now ends all at once",
      es: "Una secuencia de seguimiento ahora termina de una vez",
    },
    changes: [
      {
        en: "When a fortnight goes by with no channel permitted to write to a client, we stop trying. Until now we stopped trying with that one message only: the next in the sequence was released and began its own fortnight, and the third began a third. Strung end to end those outlast our staleness limit, so the 7-day message was cancelled unsent \u2014 and if permission did arrive late, the client received a single \"how did the viewing go?\" a month after the viewing, with the two earlier messages never sent. A sequence has one fate and now closes as one.",
        es: "Cuando pasan quince d\u00edas sin que ning\u00fan canal tenga permiso para escribir a un cliente, dejamos de intentarlo. Hasta ahora dej\u00e1bamos de intentarlo solo con ese mensaje: el siguiente de la secuencia quedaba liberado y empezaba su propia quincena, y el tercero la suya. Encadenadas superan nuestro l\u00edmite de antig\u00fcedad, as\u00ed que el mensaje de los 7 d\u00edas se cancelaba sin enviarse \u2014 y si el permiso llegaba tarde, al cliente le llegaba un \u00fanico \"\u00bfqu\u00e9 tal la visita?\" un mes despu\u00e9s de la visita, con los dos anteriores nunca enviados. Una secuencia tiene un solo destino y ahora se cierra entera.",
      },
      {
        en: "The limit that stops us sending something too late is now worked out from the retry window it has to clear, instead of being a number somebody picked. The window itself does not change \u2014 it is still 30 days \u2014 but it can no longer end up shorter than the work still in progress underneath it.",
        es: "El l\u00edmite que impide enviar algo demasiado tarde se calcula ahora a partir del plazo de reintentos que tiene que dejar pasar, en vez de ser un n\u00famero elegido. El plazo no cambia \u2014 siguen siendo 30 d\u00edas \u2014 pero ya no puede quedarse por debajo del trabajo que todav\u00eda est\u00e1 en curso.",
      },
      {
        en: "Correcting our own record: the ordering rule we announced in 0.50.0 was real, but nothing tested it \u2014 it could be deleted outright and every check stayed green. It is covered now, and we verified the cover by deleting the rule and watching the check fail. The same applies to the safeguard that keeps any sending channel from escaping opt-out control, which was written in a way that accepted anything.",
        es: "Corrigiendo nuestro propio registro: la regla de orden que anunciamos en la 0.50.0 era real, pero nada la probaba \u2014 se pod\u00eda borrar entera y todas las comprobaciones segu\u00edan en verde. Ya est\u00e1 cubierta, y lo verificamos borr\u00e1ndola y viendo fallar la comprobaci\u00f3n. Lo mismo con la salvaguarda que impide que un canal de env\u00edo se escape del control de bajas, que estaba escrita de forma que aceptaba cualquier cosa.",
      },
    ],
  },
  {
    version: "0.50.0",
    date: "2026-08-16",
    title: {
      en: "Follow-ups really do arrive in order now",
      es: "Los seguimientos sí llegan ahora en orden",
    },
    changes: [
      {
        en: "Correcting the previous entry: the fix that claimed follow-ups would arrive in the right order did not actually take effect. A client could still be asked \"just checking in on the property you saw\" before \"how did the viewing go?\". A later message now waits for the earlier one about the same viewing, which no timing quirk can get around.",
        es: "Corrigiendo la entrada anterior: el arreglo que decía que los seguimientos llegarían en el orden correcto no llegaba a aplicarse. A un cliente aún podía llegarle \"solo por saber cómo va lo del piso que viste\" antes que \"¿qué tal fue la visita?\". Ahora un mensaje posterior espera al anterior de la misma visita, y eso no depende de la hora exacta de nada.",
      },
      {
        en: "A postponed follow-up shows on the calendar at the date it will actually go out, instead of weeks in the past.",
        es: "Un seguimiento aplazado aparece en el calendario en la fecha en que va a salir de verdad, y no semanas atrás.",
      },
      {
        en: "Nothing reaches a client absurdly late any more: a message more than a month past its moment is dropped rather than sent. A buyer with many viewings was getting \"new listings similar to what you saw\" six weeks afterwards.",
        es: "Ya no llega nada absurdamente tarde: un mensaje con más de un mes de retraso se descarta en vez de enviarse. Un comprador con muchas visitas recibía \"hay pisos nuevos como el que viste\" seis semanas después.",
      },
    ],
  },
  {
    version: "0.49.0",
    date: "2026-08-16",
    title: {
      en: "Follow-ups keep their place, however long they wait",
      es: "Los seguimientos mantienen su sitio, esperen lo que esperen",
    },
    changes: [
      {
        en: "A client with several viewings on the same day now gets asked about every one of them. Before, the third \"how did the viewing go?\" could be dropped without a trace.",
        es: "Un cliente con varias visitas el mismo día ahora recibe la pregunta por todas. Antes, el tercer \"¿qué tal fue la visita?\" podía perderse sin dejar rastro.",
      },
      {
        en: "Follow-up messages arrive in the right order again. After a long wait for a client's permission, they could come out backwards — \"new listings similar to what you saw\" before \"how did the viewing go?\".",
        es: "Los seguimientos vuelven a llegar en el orden correcto. Tras una espera larga por el permiso del cliente, podían salir al revés: \"hay pisos nuevos como el que viste\" antes que \"¿qué tal fue la visita?\".",
      },
      {
        en: "The \"not getting through\" list shows only the people the system genuinely could not reach. It had started listing every upcoming booking, which buried the ones that needed you.",
        es: "La lista de \"no consigo contactar\" muestra solo a quien de verdad no se ha podido alcanzar. Había empezado a listar toda reserva futura, y eso enterraba las que te necesitaban.",
      },
      {
        en: "A call follow-up left over from months ago is no longer sent as if the conversation were yesterday.",
        es: "Un seguimiento de llamada que quedó de hace meses ya no se envía como si la conversación hubiera sido ayer.",
      },
      {
        en: "A momentary database hiccup no longer cancels a client's follow-up for good.",
        es: "Un fallo momentáneo de base de datos ya no cancela para siempre el seguimiento de un cliente.",
      },
    ],
  },
  {
    version: "0.48.0",
    date: "2026-08-16",
    title: {
      en: "The Inbox stays fast as your list grows",
      es: "La bandeja sigue rápida según crece tu lista",
    },
    changes: [
      {
        en: "The Inbox and its unread badge no longer slow down as leads pile up. Measured on ten thousand leads: what took ten seconds now takes under a fifth of a second.",
        es: "La bandeja y su contador ya no se ralentizan según se acumulan los leads. Medido con diez mil: lo que tardaba diez segundos ahora tarda menos de dos décimas.",
      },
      {
        en: "A client is never sent more than one follow-up message in the same run, whatever happened to the schedule beforehand — including after the system has been paused, or after a long wait for their permission to write to them.",
        es: "A un cliente nunca le llega más de un seguimiento en la misma pasada, pase lo que pase antes con el calendario — incluso tras una parada del sistema o una espera larga por su permiso para escribirle.",
      },
      {
        en: "Booking by phone now refuses the hour that does not exist on the night the clocks move forward, the same as booking through the dashboard did already.",
        es: "Reservar por teléfono ahora rechaza la hora que no existe en la noche en que los relojes se adelantan, igual que ya hacía reservar desde el panel.",
      },
    ],
  },
  {
    version: "0.47.8",
    date: "2026-08-16",
    title: {
      en: "An hour that does not exist, and a pause that is not a cancellation",
      es: "Una hora que no existe, y una pausa que no es una cancelación",
    },
    changes: [
      {
        en: "Booking 2:30am on the night the clocks move forward is now refused instead of quietly becoming 3:30am — which could also collide with a real 3:30 appointment.",
        es: "Reservar a las 2:30 de la madrugada en que los relojes se adelantan ahora se rechaza, en vez de convertirse calladamente en las 3:30 — que además podía chocar con una cita real de las 3:30.",
      },
      {
        en: "Follow-ups waiting for a client's permission are no longer cancelled if the system pauses for a day. They keep the two weeks of grace they are meant to have.",
        es: "Los seguimientos que esperan el permiso de un cliente ya no se cancelan si el sistema se para un día. Conservan las dos semanas de margen que les corresponden.",
      },
      {
        en: "If a follow-up fails to send in a way that also breaks the record of it, it is now marked failed rather than being silently re-sent to the client on the next run.",
        es: "Si un seguimiento falla al enviarse de una forma que además rompe su registro, ahora queda marcado como fallido en vez de reenviarse al cliente en la siguiente pasada.",
      },
    ],
  },
  {
    version: "0.47.7",
    date: "2026-08-16",
    title: {
      en: "A send that just failed is visible again",
      es: "Un envío recién fallido vuelve a verse",
    },
    changes: [
      {
        en: "When a message fails to send, the Inbox now shows that attempt as the latest thing that happened, at the time it happened. Last version it was hidden and the conversation looked a day older than it was, so the failure fell out of the recent activity list.",
        es: "Cuando un mensaje falla al enviarse, la bandeja muestra ese intento como lo último ocurrido, a su hora. En la versión anterior quedaba oculto y la conversación parecía un día más vieja de lo que era, así que el fallo se caía de la lista de actividad reciente.",
      },
      {
        en: "The Leads list now agrees with the Inbox about leads you have already marked as handled.",
        es: "La lista de leads ya coincide con la bandeja en los leads que has marcado como atendidos.",
      },
      {
        en: "If the follow-up worker is stopped for days, the messages that piled up are no longer all sent at once when it starts again — the client gets at most the one that is still timely.",
        es: "Si el worker de seguimientos se para varios días, los mensajes acumulados ya no salen todos de golpe al arrancar de nuevo: al cliente le llega como mucho el que sigue teniendo sentido.",
      },
    ],
  },
  {
    version: "0.47.6",
    date: "2026-08-16",
    title: {
      en: "A time without a timezone is not a time",
      es: "Una hora sin zona horaria no es una hora",
    },
    changes: [
      {
        en: "Booking a showing by typing a plain time — 10:00, with no timezone — no longer slips past the double-booking check. It was being compared against a diary kept in a different format, which never matched, so two clients could be confirmed for the same half-hour.",
        es: "Reservar una visita escribiendo una hora a secas —10:00, sin zona horaria— ya no se cuela por delante de la comprobación de solapamiento. Se comparaba contra una agenda guardada en otro formato, que nunca coincidía, así que dos clientes podían quedar confirmados en la misma media hora.",
      },
      {
        en: "A lead you could not reach no longer disappears from the Inbox. Last version's fix hid them from Pending as intended, but a lead whose only message was a failed first outreach dropped out of every tab. They are back, with the failed attempt shown.",
        es: "Un lead al que no pudiste llegar ya no desaparece de la bandeja. El arreglo de la versión anterior lo sacaba de Pendientes como debía, pero un lead cuyo único mensaje era un primer contacto fallido se caía de todas las pestañas. Vuelve a estar, con el intento fallido a la vista.",
      },
      {
        en: "The Inbox and the Leads list no longer disagree about who is waiting for an answer.",
        es: "La bandeja y la lista de leads ya no se contradicen sobre quién está esperando respuesta.",
      },
      {
        en: "Replying START now gets its confirmation even if the first attempt fails, so nobody is left thinking they resubscribed to silence.",
        es: "Responder ALTA ahora recibe su confirmación aunque falle el primer intento, para que nadie se quede creyendo que se resuscribió al silencio.",
      },
      {
        en: "Recording a visit that already happened no longer sends the client three follow-up messages at once. A visit entered with a past date queued \"how did it go?\", the reminder and \"new listings just came up\" all overdue, and they went out seconds apart. A visit logged the morning after still gets its check-in, on time.",
        es: "Registrar una visita que ya ocurrió ya no le manda al cliente tres seguimientos de golpe. Una visita con fecha pasada encolaba \"¿qué tal fue?\", el recordatorio y \"hay pisos nuevos\" los tres vencidos, y salían con segundos de diferencia. Una visita registrada a la mañana siguiente sigue recibiendo su mensaje, a su hora.",
      },
    ],
  },
  {
    version: "0.47.5",
    date: "2026-08-16",
    title: {
      en: "A message that did not send no longer looks like one that did",
      es: "Un mensaje que no salió ya no parece uno que sí salió",
    },
    changes: [
      {
        en: "When your reply cannot be handed to the phone or email provider, you are told so and it is queued and retried automatically. Before, the box cleared and nothing was said — the reply sat in the database forever and you had no way of knowing the client never heard from you.",
        es: "Cuando tu respuesta no se puede entregar al proveedor de SMS o correo, ahora se te dice y queda en cola para reintentarla sola. Antes se vaciaba la caja y no se decía nada: la respuesta se quedaba parada para siempre y no había forma de saber que el cliente nunca la recibió.",
      },
      {
        en: "A lead you tried to answer but could not reach stays in Pending. Writing a reply used to be enough to clear them from the list, so the person still waiting disappeared from the one screen where you would have noticed.",
        es: "Un lead al que intentaste contestar sin conseguirlo sigue en Pendientes. Antes bastaba con escribir la respuesta para que saliera de la lista, así que la persona que seguía esperando desaparecía de la única pantalla donde lo habrías visto.",
      },
      {
        en: "Follow-up messages are no longer sent twice. One lead with unreadable data could abort the whole batch before it recorded what it had already sent, and the next run sent those messages again to people who had received them.",
        es: "Los seguimientos ya no se envían dos veces. Un lead con datos ilegibles podía abortar toda la tanda antes de anotar lo que ya había enviado, y la siguiente pasada volvía a mandar esos mensajes a quien ya los tenía.",
      },
      {
        en: "Someone who replied STOP can no longer receive a message that was queued before they said it. The check that protects them was being skipped for anything a person had typed.",
        es: "Quien responde STOP ya no puede recibir un mensaje que estuviera en cola de antes. La comprobación que le protege se estaba saltando para todo lo que hubiera escrito una persona.",
      },
    ],
  },
  {
    version: "0.46.14",
    date: "2026-08-14",
    title: {
      en: "Nothing a machine writes can lose what you said",
      es: "Nada que escriba una máquina puede perder lo que dijiste",
    },
    changes: [
      {
        en: "A long or oddly-shaped value coming from a message, a phone call or the property feed used to be able to take down the write that was saving it — and on the inbound paths that write was the one storing what the customer actually said, so the message itself was lost and every retry lost it again. Those values are now fitted before they land, and what cannot be read is dropped rather than guessed at.",
        es: "Un valor largo o con forma rara —llegado de un mensaje, de una llamada o del feed de propiedades— podía tumbar la escritura que lo estaba guardando. En las rutas de entrada esa escritura era justo la que guardaba lo que dijo el cliente, así que se perdía el mensaje, y cada reintento lo volvía a perder. Ahora esos valores se ajustan antes de llegar, y lo que no se puede leer se descarta en vez de adivinarse.",
      },
      {
        en: "Two different people can no longer end up as the same contact. Where an identifier was too long to store, it used to be cut — and two addresses that matched for the first part became one lead, with one person's messages in another person's conversation.",
        es: "Dos personas distintas ya no pueden acabar siendo el mismo contacto. Cuando un identificador era demasiado largo se recortaba, y dos direcciones que coincidían al principio se convertían en un solo contacto, con los mensajes de una persona en la conversación de otra.",
      },
      {
        en: "Booking a showing can no longer leave an appointment on your calendar that the app cannot see. The invitation is created at the calendar first, so a failure while recording it left something real that nothing here could list or cancel.",
        es: "Agendar una visita ya no puede dejarte una cita en el calendario que la aplicación no ve. La invitación se crea antes en el calendario, así que un fallo al registrarla dejaba algo real que aquí no se podía ni listar ni cancelar.",
      },
    ],
  },
  {
    version: "0.45.0",
    date: "2026-08-14",
    title: {
      en: "What you learn on a call now does something",
      es: "Lo que aprendes en una llamada ya hace algo",
    },
    changes: [
      {
        en: "Every lead page now has a panel to log a call. It is taps, not typing, and it is meant to take under a minute: pick how the call went, correct anything that changed, and save. What you record goes onto the lead itself, so the property matcher and the lead score immediately reflect the conversation you just had.",
        es: "Cada ficha de contacto tiene ahora un panel para registrar la llamada. Son toques, no escritura, y está pensado para tardar menos de un minuto: eliges cómo fue, corriges lo que haya cambiado y guardas. Lo que anotas va al contacto, así que el buscador de propiedades y la puntuación reflejan al instante la conversación que acabas de tener.",
      },
      {
        en: "Saving is not filing. Each outcome does one thing: a follow-up gets scheduled, or everything pending gets cancelled when someone says they already have an agent or asks you to stop. Nothing further is sent to them after that.",
        es: "Guardar no es archivar. Cada resultado hace una cosa: se programa un seguimiento, o se cancela todo lo pendiente cuando alguien dice que ya tiene agente o pide que no le contacten. A partir de ahí no se le envía nada más.",
      },
      {
        en: "You can record that someone asked, on the call, to be sent options by text. That writes down their permission with the date and who logged it — which is what makes texting them lawful, and what you would need if it were ever questioned.",
        es: "Puedes registrar que alguien pidió en la llamada que le mandes opciones por mensaje. Eso deja escrito su permiso con la fecha y quién lo marcó — que es lo que hace lícito escribirle, y lo que haría falta si algún día se cuestiona.",
      },
      {
        en: "A new Today page lists what needs a person: the leads who asked to be called or emailed (nothing sends those automatically), the follow-ups we are holding because we have no record of permission to write to them, and the highly-ranked leads nobody has spoken to lately. The middle one used to be invisible — you could not tell being patient apart from being stuck.",
        es: "Una página nueva, Hoy, lista lo que necesita a una persona: los contactos que pidieron llamada o correo (eso no sale solo), los seguimientos que estamos reteniendo porque no consta su permiso para escribirles, y los bien puntuados con los que nadie habla hace tiempo. El del medio antes era invisible: no se distinguía tener paciencia de estar atascado.",
      },
    ],
  },
  {
    version: "0.44.0",
    date: "2026-08-13",
    title: {
      en: "Your public page",
      es: "Tu página pública",
    },
    changes: [
      {
        en: "Your agency now has a public page at the root of your address, in English and Spanish. Someone who arrives from an ad or a video can read what you do and book a fifteen-minute consult without signing in to anything.",
        es: "Tu agencia ya tiene una página pública en la raíz de tu dirección, en inglés y español. Quien llega desde un anuncio o un vídeo puede leer a qué te dedicas y agendar una asesoría de quince minutos sin registrarse en nada.",
      },
      {
        en: "The consult form arrives in your inbox exactly like the contact form does, with the same spam protection and the same written record of the visitor's permission to text them.",
        es: "El formulario de la asesoría te llega a la bandeja igual que el de contacto, con la misma protección antispam y el mismo registro escrito del permiso del visitante para escribirle por SMS.",
      },
      {
        en: "The page only shows what you have actually given it. Phone numbers, years in business, the office address and client testimonials each appear once you fill them in, and their section is simply absent until then — nothing is invented to fill a gap on a page advertising a licensed brokerage.",
        es: "La página solo muestra lo que le has dado de verdad. Teléfonos, años de oficio, la dirección de la oficina y los testimonios de clientes aparecen cuando los rellenas, y hasta entonces su sección sencillamente no está: no se inventa nada para tapar un hueco en el anuncio de una inmobiliaria con licencia.",
      },
      {
        en: "Because the address now opens the public page, you sign in at /login. There is a discreet link at the bottom of the page too.",
        es: "Como la dirección ahora abre la página pública, entras por /login. También hay un enlace discreto al pie de la página.",
      },
    ],
  },
  {
    version: "0.43.0",
    date: "2026-08-12",
    title: {
      en: "Settings that were being ignored",
      es: "Ajustes que se estaban ignorando",
    },
    changes: [
      {
        en: "Eighteen settings in your configuration file were never reaching the application — including your calendar connection, your office timezone and the contact form's spam protection. Changing them appeared to do nothing, because it did nothing. They work now.",
        es: "Dieciocho ajustes de tu fichero de configuración no llegaban a la aplicación — entre ellos la conexión del calendario, la zona horaria de la oficina y la protección antispam del formulario. Cambiarlos parecía no hacer nada, porque no hacía nada. Ya funcionan.",
      },
      {
        en: "The contact form's captcha can now actually be switched on, and the system tells you whether it is really verifying — before, an unconfigured captcha accepted everything while looking perfectly normal.",
        es: "El captcha del formulario ya se puede activar de verdad, y el sistema te dice si está verificando realmente — antes, sin configurar, aceptaba todo con aspecto de estar funcionando.",
      },
      {
        en: "WhatsApp is now explicitly switched off rather than \"simulated\". This is a US brokerage: text, call and email. The old setting was a trap — turning it off would have silently blocked every incoming message.",
        es: "WhatsApp queda explícitamente desactivado en vez de \"simulado\". Esto es una inmobiliaria de EE. UU.: SMS, llamada y email. El ajuste anterior era una trampa: desactivarlo habría bloqueado en silencio todos los mensajes entrantes.",
      },
    ],
  },
  {
    version: "0.42.4",
    date: "2026-08-11",
    title: {
      en: "A way in for people who found you online",
      es: "Una puerta de entrada para quien te encuentra online",
    },
    changes: [
      {
        en: "There is now a contact form anyone can fill in, at /contact. Put the link in your social media bio: someone who watches a video can reach you without already having your number, and they arrive in your Inbox like any other lead.",
        es: "Ya hay un formulario de contacto que puede rellenar cualquiera, en /contact. Pon el enlace en la bio de tus redes: quien vea un vídeo puede escribirte sin tener ya tu número, y llega a tu bandeja como cualquier otro lead.",
      },
      {
        en: "Each lead now records which video or link brought them, so you can tell which content actually produces appointments instead of only counting views.",
        es: "Cada lead guarda ahora qué vídeo o enlace lo trajo, así puedes saber qué contenido produce citas de verdad en vez de contar solo visitas.",
      },
      {
        en: "When someone ticks the box agreeing to receive texts, we store the exact wording they saw along with the date. Automatic texts are held back for anyone who did not agree and never wrote to you first.",
        es: "Cuando alguien marca la casilla aceptando recibir mensajes, guardamos el texto exacto que vio junto con la fecha. Los mensajes automáticos se retienen para quien no aceptó y nunca te escribió primero.",
      },
      {
        en: "Fixed: replying to a lead who came through the form failed, and their scheduled follow-ups were marked as failed too.",
        es: "Corregido: responder a un lead llegado por el formulario fallaba, y sus seguimientos programados también se marcaban como fallidos.",
      },
      {
        en: "Fixed: the Inbox labelled form submissions as SMS, and left them at the bottom of the priority list.",
        es: "Corregido: la bandeja etiquetaba los envíos del formulario como SMS y los dejaba al fondo de la lista de prioridad.",
      },
      {
        en: "\"Baja\" and \"alta\" are no longer treated as opt-out and opt-in — in this business they are the answer to \"ground floor or upper floor?\", and treating them as unsubscribe requests silenced live buyers.",
        es: "\"Baja\" y \"alta\" ya no se interpretan como baja y alta del servicio: en este negocio son la respuesta a \"¿planta baja o alta?\", y tomarlas por bajas silenciaba a compradores activos.",
      },
      {
        en: "Fixed: a single blank contact name could stop the whole follow-up worker, which then re-sent the same message on every tick without recording any of them.",
        es: "Corregido: un nombre de contacto en blanco podía parar todo el worker de seguimientos, que reenviaba el mismo mensaje en cada ciclo sin registrar ninguno.",
      },
      {
        en: "Answering \"yes\" or \"sí\" no longer switches automated messages back on for someone who had opted out — only replying START does.",
        es: "Responder \"sí\" ya no vuelve a activar los mensajes automáticos de quien se dio de baja: solo lo hace responder ALTA.",
      },
      {
        en: "Fixed: a \"your viewing is tomorrow\" reminder could arrive days after the viewing.",
        es: "Corregido: un recordatorio de \"tu visita es mañana\" podía llegar días después de la visita.",
      },
      {
        en: "If someone replies STOP, that now sticks: no message reaches them again on that channel — not the next day, not one that was already queued when they said it, and not one you write yourself, which the composer will refuse. Their messages still arrive in your Inbox and the lead is clearly marked. Calling them is a separate consent and your decision.",
        es: "Si alguien responde STOP, ahora se mantiene: no le llega ningún mensaje más por ese canal, ni al día siguiente, ni uno que ya estuviera en cola cuando lo dijo, ni uno que escribas tú — el compositor lo rechaza. Sus mensajes siguen llegando a tu bandeja y el lead queda marcado. Llamarla es otro consentimiento y una decisión tuya.",
      },
      {
        en: "Replying STOP now works, in English and Spanish. The person gets one confirmation, no automated messages after that, and START brings them back. Before this it did nothing at all, even though the form promised it.",
        es: "Responder STOP ya funciona, en inglés y en español. La persona recibe una confirmación, ningún mensaje automático después, y ALTA la reactiva. Antes no hacía nada, aunque el formulario lo prometía.",
      },
    ],
  },
  {
    version: "0.41.2",
    date: "2026-08-09",
    title: {
      en: "The installer now installs what the release says",
      es: "El instalador instala lo que dice la versión",
    },
    changes: [
      {
        en: "A fresh installation reported an old version number, because the version was written down in four places and three of them were never updated. It now comes from one place.",
        es: "Una instalación nueva reportaba un número de versión antiguo, porque la versión estaba escrita en cuatro sitios y tres no se actualizaban nunca. Ahora sale de uno solo.",
      },
      {
        en: "The technical API description was still being served when the developer documentation was switched off.",
        es: "La descripción técnica de la API se seguía sirviendo con la documentación de desarrollo apagada.",
      },
    ],
  },
  {
    version: "0.41.1",
    date: "2026-08-09",
    title: {
      en: "Sign in tells you where it works",
      es: "El acceso te dice dónde funciona",
    },
    changes: [
      {
        en: "Opening the dashboard on its local network address showed a Google button that could only ever fail — Google does not accept sign-ins from a bare IP address. It now tells you the web address to use instead. The same applies to Apple.",
        es: "Abrir el panel en su dirección de red local mostraba un botón de Google que solo podía fallar — Google no acepta accesos desde una IP a secas. Ahora te dice qué dirección web usar. Lo mismo con Apple.",
      },
      {
        en: "Your session is now protected in transit whenever the dashboard is served over a secure connection, and still works when it is reached on the local network.",
        es: "Tu sesión viaja protegida siempre que el panel se sirva por conexión segura, y sigue funcionando cuando se entra por la red local.",
      },
    ],
  },
  {
    version: "0.41.0",
    date: "2026-08-09",
    title: {
      en: "Your replies get through, and every listing is credited",
      es: "Tus respuestas llegan, y cada propiedad va acreditada",
    },
    changes: [
      {
        en: "A reply that hit a provider outage used to be lost silently. Failed messages are now retried automatically, backing off over about an hour and a half before giving up.",
        es: "Una respuesta que topaba con una caída del proveedor se perdía en silencio. Ahora los mensajes fallidos se reintentan solos, espaciándose durante hora y media antes de darse por vencidos.",
      },
      {
        en: "When every AI provider is unreachable, the lead now gets a short note in their own language instead of silence.",
        es: "Cuando ningún proveedor de IA responde, el lead recibe una nota breve en su idioma en vez de silencio.",
      },
      {
        en: "Listings shown to a lead now carry the listing broker's credit automatically, on the message itself — a Colorado requirement that rested on the AI choosing to repeat it.",
        es: "Las propiedades que se enseñan a un lead llevan ahora el crédito del corredor listante automáticamente, en el propio mensaje — un requisito de Colorado que dependía de que la IA decidiera repetirlo.",
      },
      {
        en: "One city-filtered property import used to hide every listing outside that city from the automatic sync, permanently — including ones that had just sold.",
        es: "Una importación filtrada por ciudad ocultaba para siempre del sync automático todas las propiedades de fuera de esa ciudad — incluidas las que acababan de venderse.",
      },
      {
        en: "The properties list now shows active listings by default instead of mixing in sold and pending ones.",
        es: "La lista de propiedades muestra ahora las activas por defecto, en vez de mezclar vendidas y pendientes.",
      },
      {
        en: "The same person writing from WhatsApp and then from email is now one lead instead of two.",
        es: "La misma persona escribiendo por WhatsApp y luego por email es ahora un solo lead en vez de dos.",
      },
    ],
  },
  {
    version: "0.40.0",
    date: "2026-08-08",
    title: {
      en: "Each agency books on its own calendar",
      es: "Cada agencia reserva en su propio calendario",
    },
    changes: [
      {
        en: "Every agency now books on its own Cal.com. Before this, a booking wrote your client's name, email and phone onto the operator's calendar, where another agency's realtors could see it — and your bookings blocked out their availability.",
        es: "Cada agencia reserva ahora en su propio Cal.com. Antes, una reserva escribía el nombre, email y teléfono de tu cliente en el calendario del operador, donde lo veían los realtors de otra agencia — y tus reservas tapaban su disponibilidad.",
      },
      {
        en: "Two different leads could be offered the same half-hour and both bookings went through, sending one realtor to two houses at once. Availability is now de-conflicted across the whole agency.",
        es: "A dos leads distintos se les podía ofrecer la misma media hora y ambas reservas prosperaban, mandando a un realtor a dos casas a la vez. La disponibilidad ahora se resuelve para toda la agencia.",
      },
      {
        en: "An email could name another agency inside a group address and route your lead to them. Any grouped address now makes the whole header untrusted, and the delivery envelope wins over what the sender wrote.",
        es: "Un email podía nombrar a otra agencia dentro de una dirección de grupo y desviarle tu lead. Ahora cualquier dirección agrupada invalida la cabecera entera, y el sobre de entrega manda sobre lo que escribió quien envía.",
      },
      {
        en: "Cancelling a visit returned an error and left it scheduled when the calendar was not set up. It now says the calendar is unavailable and leaves the visit untouched, so retrying means something.",
        es: "Cancelar una visita devolvía un error y la dejaba agendada si el calendario no estaba configurado. Ahora avisa de que el calendario no está disponible y deja la visita intacta, así reintentar sirve de algo.",
      },
      {
        en: "Lead phone numbers, inbound message payloads and uploaded contact lists are no longer written to the logs in full.",
        es: "Los teléfonos de los leads, los mensajes entrantes y las listas de contactos subidas ya no se escriben enteros en los logs.",
      },
    ],
  },
  {
    version: "0.39.2",
    date: "2026-08-08",
    title: {
      en: "Each phone line verifies with its own key",
      es: "Cada línea verifica con su propia clave",
    },
    changes: [
      {
        en: "An agency with two numbers on one channel now has each one checked against its own signing key. Messages to the second number were being checked against the first one's, so they failed and the lead was lost with nothing to explain it.",
        es: "Una agencia con dos números en un mismo canal comprueba ahora cada uno con su propia clave de firma. Los mensajes al segundo número se comprobaban con la del primero, así que fallaban y el lead se perdía sin explicación.",
      },
      {
        en: "The database role that enforces separation between agencies gets its password rotated on upgrade instead of keeping the one it was created with.",
        es: "El rol de base de datos que separa a las agencias rota su contraseña al actualizar, en vez de conservar la que se le puso al crearlo.",
      },
      {
        en: "A call whose line is not mapped now hears a hand-off message instead of the assistant going quiet.",
        es: "Una llamada cuya línea no está mapeada oye ahora un mensaje de traspaso en vez de que el asistente se quede callado.",
      },
    ],
  },
  {
    version: "0.39.1",
    date: "2026-08-08",
    title: {
      en: "Hardening found by four more independent audits",
      es: "Refuerzos encontrados por cuatro auditorías independientes más",
    },
    changes: [
      {
        en: "Only named operators can create or enter agencies. The shared office password no longer grants that, and it can no longer be used to derive the key that would forge it.",
        es: "Solo los operadores con nombre pueden crear agencias o entrar en ellas. La contraseña compartida de la oficina ya no lo concede, ni sirve para derivar la clave que lo falsificaría.",
      },
      {
        en: "A message that arrives at an unmapped number is held back rather than filed under whichever agency happens to be the only active one, unless that agency's own provider account authenticated it.",
        es: "Un mensaje que llega a un número sin mapear se retiene en vez de archivarse en la única agencia activa, salvo que lo haya autenticado la cuenta de proveedor de esa misma agencia.",
      },
      {
        en: "Two agencies can no longer be pointed at the same provider credential, which would have let one of them sign messages into the other's inbox.",
        es: "Dos agencias ya no pueden apuntar a la misma credencial de proveedor, lo que habría permitido a una firmar mensajes dentro del buzón de la otra.",
      },
      {
        en: "A duplicate message no longer discards the lead that arrived with it — the safeguard for that was opening after the write it was meant to protect.",
        es: "Un mensaje duplicado ya no descarta el lead que llegó con él: la protección se abría después de la escritura que debía proteger.",
      },
      {
        en: "An email whose body could not be retrieved is retried instead of answered blind.",
        es: "Un correo cuyo cuerpo no se pudo recuperar se reintenta en vez de responderse a ciegas.",
      },
    ],
  },
  {
    version: "0.39.0",
    date: "2026-08-08",
    title: {
      en: "Each agency now replies from its own number",
      es: "Cada agencia responde ahora desde su propio número",
    },
    changes: [
      {
        en: "Replies to a lead now go out from the number, WhatsApp line or email address of the agency they wrote to. Previously every reply left from the first agency's number, so the lead answered the wrong agency and the rest of the conversation ended up in the wrong dashboard.",
        es: "Las respuestas a un lead salen ahora desde el número, la línea de WhatsApp o el correo de la agencia a la que escribieron. Antes toda respuesta salía desde el número de la primera agencia, así que el lead contestaba a la agencia equivocada y el resto de la conversación acababa en el panel que no era.",
      },
      {
        en: "Two messages arriving at the same instant no longer lose leads. Four simultaneous first contacts used to leave one lead out of four, with every delivery reported as successful.",
        es: "Dos mensajes que llegan a la vez ya no pierden leads. Cuatro primeros contactos simultáneos dejaban un lead de cuatro, y cada entrega se reportaba como correcta.",
      },
      {
        en: "An email that copies two agencies is held back instead of being filed under whichever address happened to come first.",
        es: "Un correo con copia a dos agencias se retiene en vez de archivarse en la dirección que viniera primero.",
      },
      {
        en: "The voice assistant can book visits again on lines mapped by phone number — it used to fail mid-call while the transcript still saved correctly.",
        es: "El asistente de voz vuelve a poder agendar visitas en las líneas mapeadas por número — antes fallaba a mitad de llamada mientras el transcript sí se guardaba bien.",
      },
      {
        en: "Platform operators are named by email instead of sharing one password, so entering an agency records who did it.",
        es: "Los operadores de la plataforma se identifican por correo en vez de compartir una contraseña, así que entrar en una agencia registra quién lo hizo.",
      },
    ],
  },
  {
    version: "0.38.0",
    date: "2026-08-07",
    title: {
      en: "Each agency's messages now reach only that agency",
      es: "Los mensajes de cada agencia llegan solo a esa agencia",
    },
    changes: [
      {
        en: "Incoming texts, WhatsApp messages and emails are matched to an agency by the number or mailbox they were sent to, so a second agency's leads can never land in another's dashboard.",
        es: "Los mensajes de texto, WhatsApp y correos entrantes se asignan a una agencia por el número o buzón al que se enviaron, así que los leads de una agencia nunca aparecen en el panel de otra.",
      },
      {
        en: "A message sent to an address nobody has claimed is refused and retried rather than filed under the wrong agency.",
        es: "Un mensaje enviado a una dirección que nadie ha reclamado se rechaza y se reintenta, en vez de archivarse en la agencia equivocada.",
      },
      {
        en: "Platform operators can create and suspend agencies, and enter one when support is needed — every entry is recorded.",
        es: "Los operadores de la plataforma pueden crear y suspender agencias, y entrar en una cuando hace falta dar soporte — cada entrada queda registrada.",
      },
      {
        en: "A suspended agency now loses access immediately instead of keeping it.",
        es: "Una agencia suspendida ahora pierde el acceso de inmediato en vez de conservarlo.",
      },
    ],
  },
  {
    version: "0.37.0",
    date: "2026-08-06",
    title: {
      en: "Each agency now has its own separate workspace",
      es: "Cada agencia tiene ahora su propio espacio separado",
    },
    changes: [
      {
        en: "Eko AI Realtors now hosts multiple agencies in one installation. Every agency is a separate organization: its leads, conversations, visits and settings are visible only to its own members.",
        es: "Eko AI Realtors aloja ahora varias agencias en una sola instalación. Cada agencia es una organización aparte: sus leads, conversaciones, visitas y ajustes solo los ven sus propios miembros.",
      },
      {
        en: "Separation is enforced by the database itself, not by the application. A query that forgets to filter returns nothing rather than another agency's data.",
        es: "La separación la impone la propia base de datos, no la aplicación. Una consulta que olvide filtrar devuelve nada, no los datos de otra agencia.",
      },
      {
        en: "Fixed an error handler in the WhatsApp webhook that crashed while reporting a failure, hiding the original cause.",
        es: "Corregido un manejador de errores del webhook de WhatsApp que fallaba al reportar un fallo y ocultaba la causa original.",
      },
    ],
  },
  {
    version: "0.36.0",
    date: "2026-07-31",
    title: {
      en: "REcolorado feed aligned with MLS Grid's real rules",
      es: "El feed de REcolorado, alineado con las reglas reales de MLS Grid",
    },
    changes: [
      {
        en: "Now that we have MLS Grid access, the integration was checked against the official documentation. Three things it was doing would have failed on the very first call: filtering by city (MLS Grid only allows a fixed set of searchable fields, and City is not one), sorting the results, and firing requests with no pacing — MLS Grid caps at 2 per second and suspends tokens that go over.",
        es: "Ahora que tenemos acceso a MLS Grid, la integración se contrastó con la documentación oficial. Tres cosas que hacía habrían fallado en la primera llamada: filtrar por ciudad (MLS Grid solo permite un conjunto fijo de campos buscables, y City no es uno), ordenar los resultados, y lanzar peticiones sin pausa — MLS Grid limita a 2 por segundo y suspende los tokens que se pasan.",
      },
      {
        en: "Rentals were being classified as sales. The lease signal lives in PropertyType (“Residential Lease”), not in the subtype we were reading — so rental leads were being shown homes for sale, and buyers were being shown rentals.",
        es: "Los alquileres se clasificaban como ventas. La señal de alquiler está en PropertyType (“Residential Lease”), no en el subtipo que leíamos — así que a los leads de alquiler se les enseñaban casas en venta, y a los compradores, alquileres.",
      },
      {
        en: "New sync-status endpoint so a failing background sync is visible instead of buried in the logs, and the replication cursor now keeps millisecond precision.",
        es: "Nuevo endpoint sync-status para que un sync en segundo plano que falla se vea, en vez de quedar enterrado en los logs, y el cursor de replicación ahora conserva la precisión de milisegundos.",
      },
    ],
  },
  {
    version: "0.35.0",
    date: "2026-07-21",
    title: {
      en: "REcolorado (MLS Grid) listings integration — ready to switch on",
      es: "Integración de listings de REcolorado (MLS Grid) — lista para activar",
    },
    changes: [
      {
        en: "The listings engine can now replicate real MLS data from REcolorado via MLS Grid's RESO Web API — incremental sync by ModificationTimestamp, @odata.nextLink pagination, status reconciliation (sold/pending homes drop out of buyer matches), and IDX broker attribution (“Cortesía de …”) when a home is shown to a lead.",
        es: "El motor de listings ya puede replicar datos MLS reales de REcolorado vía el RESO Web API de MLS Grid — sync incremental por ModificationTimestamp, paginación @odata.nextLink, reconciliación de estatus (las casas vendidas/pendientes salen de las coincidencias del comprador) y atribución de broker IDX (“Cortesía de …”) cuando se le muestra una casa a un lead.",
      },
      {
        en: "A background worker (off by default) keeps the feed fresh on an interval and resumes crash-safely from the last synced page. Switch to real data by setting the RESO credentials and flipping LISTINGS_SIMULATED=false — no code change.",
        es: "Un worker en segundo plano (apagado por defecto) mantiene el feed actualizado en intervalos y reanuda de forma segura ante fallos desde la última página sincronizada. Se cambia a datos reales configurando las credenciales RESO y poniendo LISTINGS_SIMULATED=false — sin cambios de código.",
      },
      {
        en: "Backend: sync_state table (Alembic 014), a RESO/MLS Grid adapter with retry/backoff, and 24 new tests. No behavior change until a feed is provisioned.",
        es: "Backend: tabla sync_state (Alembic 014), un adaptador RESO/MLS Grid con reintentos/backoff, y 24 tests nuevos. Sin cambios de comportamiento hasta que se aprovisione un feed.",
      },
    ],
  },
  {
    version: "0.34.1",
    date: "2026-06-05",
    title: {
      en: "Version history now follows the selected language",
      es: "El historial de versiones ahora sigue el idioma seleccionado",
    },
    changes: [
      {
        en: "The version history was always shown in Spanish, even with English selected. Now every changelog entry is bilingual and the modal renders in the active UI language (EN/ES).",
        es: "El historial de versiones se mostraba siempre en español, incluso con inglés seleccionado. Ahora cada entrada del changelog es bilingüe y el modal se muestra en el idioma activo de la interfaz (EN/ES).",
      },
    ],
  },
  {
    version: "0.34.0",
    date: "2026-06-04",
    title: {
      en: "Admin: change access to Member + per-user usage stats",
      es: "Admin: cambiar acceso a Member + estadísticas de uso por usuario",
    },
    changes: [
      {
        en: "Admins can switch a demo registration from 'View-only' to 'Member' (it stops being read-only and can operate the dashboard). Changed from the dropdown on each registration in Settings.",
        es: "El admin puede cambiar el acceso de un registro demo de 'Solo lectura' a 'Member' (deja de ser read-only y puede operar el dashboard). Se cambia desde el selector en cada registro de Settings.",
      },
      {
        en: "Per-user engagement stats (Google/Apple and demos): every row in Settings has a 📊 button showing logins, total actions, active days, last seen, most-used sections, device/browser and IP.",
        es: "Estadísticas de engagement por usuario (Google/Apple y demos): cada fila en Settings tiene un botón 📊 que muestra inicios de sesión, acciones totales, días activos, última vez visto, secciones más usadas, dispositivo/navegador e IP.",
      },
      {
        en: "Activity is captured lightly (one row per user, via middleware) attributed to the session email. The office password (owner) is not tracked. Admin-only.",
        es: "La actividad se captura de forma liviana (1 fila por usuario, vía middleware) atribuida al email de la sesión. La contraseña de oficina (dueño) no se rastrea. Solo visible para admins.",
      },
      {
        en: "Backend: `user_activity` table (Alembic 013), tracking middleware, `PATCH /api/v1/team/accounts/{id}` (role) and `GET /api/v1/team/activity`.",
        es: "Backend: tabla `user_activity` (Alembic 013), middleware de tracking, `PATCH /api/v1/team/accounts/{id}` (rol) y `GET /api/v1/team/activity`.",
      },
    ],
  },
  {
    version: "0.33.0",
    date: "2026-06-04",
    title: {
      en: "Admin: registered-users view (Google/Apple + view-only demos)",
      es: "Admin: panel de usuarios registrados (Google/Apple + demos view-only)",
    },
    changes: [
      {
        en: "Settings now shows a 'Demo registrations (view-only)' panel with every account that signed up via the public form: name, email, phone, company, location and date — for sales follow-up.",
        es: "Settings ahora muestra un panel 'Registros de demostración (solo lectura)' con todas las cuentas que se registraron por el formulario público: nombre, email, teléfono, empresa, ubicación y fecha — para seguimiento comercial.",
      },
      {
        en: "Admins can delete registrations (e.g. test accounts) from there.",
        es: "El admin puede eliminar registros (ej. cuentas de prueba) desde ahí.",
      },
      {
        en: "Google/Apple access is still managed in the 'Team & access (Google/Apple)' panel (the allow-list). Both sit together in Settings, admin-only.",
        es: "El acceso por Google/Apple se sigue gestionando en el panel 'Equipo y acceso (Google/Apple)' (la allow-list). Ambos quedan juntos en Settings, admin-only.",
      },
      {
        en: "Backend: admin endpoints `GET /api/v1/team/accounts` and `DELETE /api/v1/team/accounts/{id}`.",
        es: "Backend: endpoints admin `GET /api/v1/team/accounts` y `DELETE /api/v1/team/accounts/{id}`.",
      },
    ],
  },
  {
    version: "0.32.1",
    date: "2026-06-04",
    title: {
      en: "Fix: the 'Create account' (register) link did nothing",
      es: "Fix: el botón 'Crear cuenta' (registro) no hacía nada",
    },
    changes: [
      {
        en: "AuthGuard only exempted /login, so going to /register bounced you back to /login (the link seemed to do nothing). Now /register is also a public route → the registration page opens correctly.",
        es: "El AuthGuard solo eximía /login, así que al ir a /register te rebotaba de vuelta a /login (parecía que el botón no hacía nada). Ahora /register también es ruta pública → la página de registro abre correctamente.",
      },
    ],
  },
  {
    version: "0.32.0",
    date: "2026-06-04",
    title: {
      en: "Self-registration with email + password → read-only demo accounts",
      es: "Auto-registro con email + contraseña → cuentas de demostración (solo lectura)",
    },
    changes: [
      {
        en: "New registration page (/register): anyone can create an account with name, email, phone, company, address, state, country and password. Registration signs them in automatically.",
        es: "Nueva página de registro (/register): cualquiera puede crear una cuenta con nombre, email, teléfono, empresa, dirección, estado, país y contraseña. Al registrarse entra automáticamente.",
      },
      {
        en: "These accounts are READ-ONLY (role 'viewer'): they can see the whole dashboard but CANNOT change anything. Meant to showcase the system to prospective clients.",
        es: "Estas cuentas son SOLO LECTURA (rol 'viewer'): pueden ver todo el dashboard pero NO pueden modificar nada. Pensadas para mostrar el sistema a futuros clientes.",
      },
      {
        en: "The write block is enforced server-side (any POST/PUT/PATCH/DELETE from a viewer → 403) and in the UI: a 'read-only' banner + create/edit buttons hidden (Add lead, reply, book/create events, mark won…).",
        es: "El bloqueo de escritura se aplica en el servidor (cualquier POST/PUT/PATCH/DELETE de un viewer → 403) y en la interfaz: banner 'solo lectura' + se ocultan los botones de crear/editar (Agregar lead, responder, agendar/crear eventos, marcar ganado…).",
      },
      {
        en: "Email + password sign-in for these accounts was added to /login, alongside the office password and Google/Apple.",
        es: "En /login se agregó el ingreso con email + contraseña para estas cuentas, además de la contraseña de oficina y Google/Apple.",
      },
    ],
  },
  {
    version: "0.31.1",
    date: "2026-06-03",
    title: {
      en: "Calendar: clicking an appointment opens the lead",
      es: "Calendario: clic en una cita abre el lead",
    },
    changes: [
      {
        en: "Clicking a calendar appointment/follow-up (in both the Agenda and Month views) now opens the lead's page directly. Lead-less manual events are not clickable.",
        es: "Al hacer clic en una cita/seguimiento del calendario (tanto en la vista Agenda como en la grilla Mes) ahora se abre directamente la ficha del lead. Los eventos manuales sin lead no son clickeables.",
      },
    ],
  },
  {
    version: "0.31.0",
    date: "2026-06-02",
    title: {
      en: "New Calendar tab: agenda + month grid + manual events",
      es: "Nuevo tab Calendario: agenda + grilla mensual + eventos manuales",
    },
    changes: [
      {
        en: "New Calendar tab in the nav that brings together, in one place, all lead visits, manual events and pending system tasks (follow-ups), in the office timezone.",
        es: "Nuevo tab Calendario en el nav que reúne en un solo lugar todas las visitas de leads, los eventos manuales y los pendientes del sistema (follow-ups), en la zona horaria de la oficina.",
      },
      {
        en: "Two toggleable views: Agenda (list grouped by day — Today/Tomorrow/date) and Month (month grid with the events per day).",
        es: "Dos vistas con toggle: Agenda (lista agrupada por día — Hoy/Mañana/fecha) y Mes (grilla mensual con los eventos por día).",
      },
      {
        en: "'Add event' button to create manual events (title, date/time, duration, notes) — they don't need to be tied to a lead. Interpreted in the office timezone.",
        es: "Botón 'Agregar evento' para crear eventos manuales (título, fecha/hora, duración, notas) — no necesitan estar ligados a un lead. Se interpretan en la zona horaria de la oficina.",
      },
      {
        en: "Backend: visit `lead_id` is now optional (+ `title`), endpoints `GET /visits` (all), `POST /visits` (manual event) and `GET /visits/agenda` (visits + pending).",
        es: "Backend: `lead_id` de las visitas ahora es opcional (+ `title`), endpoints `GET /visits` (todas), `POST /visits` (evento manual) y `GET /visits/agenda` (visitas + pendientes).",
      },
    ],
  },
  {
    version: "0.30.0",
    date: "2026-06-02",
    title: {
      en: "Office timezone: appointments booked in local time (not UTC)",
      es: "Zona horaria de la oficina: las citas se agendan en hora local (no UTC)",
    },
    changes: [
      {
        en: "Bug: the voice agent read \"2 PM\" as 2 PM UTC → the appointment landed at 8 AM. Now the spoken time is interpreted in the office TIMEZONE and stored correctly (2 PM Denver = 20:00 UTC).",
        es: "Bug: la agente de voz interpretaba \"2 PM\" como 2 PM UTC → la cita quedaba a las 8 AM. Ahora la hora hablada se interpreta en la ZONA HORARIA de la oficina y se guarda correctamente (2 PM Denver = 20:00 UTC).",
      },
      {
        en: "New Timezone preference in Settings: auto-detected from the browser the first time and changeable anytime. Defines how the agent interprets times and how all visits are shown.",
        es: "Nueva preferencia de Zona Horaria en Settings: se auto-detecta del navegador la primera vez y podés cambiarla cuando quieras. Define cómo el agente interpreta las horas y cómo se muestran todas las visitas.",
      },
      {
        en: "Visits now show in the office timezone with its abbreviation (e.g. \"2:00 PM MDT\"), no matter where you view the dashboard from.",
        es: "Las visitas se muestran ahora en la zona horaria de la oficina con su abreviatura (ej. \"2:00 PM MDT\"), sin importar desde dónde mires el dashboard.",
      },
    ],
  },
  {
    version: "0.29.1",
    date: "2026-06-02",
    title: {
      en: "Missing lead: friendly 'not found' state (no more raw red error)",
      es: "Lead inexistente: estado 'no encontrado' amigable (no más error rojo crudo)",
    },
    changes: [
      {
        en: "Opening a lead that no longer exists (e.g. an old link to a merged/deleted record) showed a raw red 'API 404: Lead not found' box. Now it shows a clean 'Lead not found' state with a hint that it may have been merged/removed and a button back to the leads list.",
        es: "Abrir un lead que ya no existe (ej. un link viejo a una ficha que se fusionó o se borró) mostraba un cuadro rojo crudo 'API 404: Lead not found'. Ahora muestra un estado limpio 'Lead no encontrado' con la pista de que pudo fusionarse/eliminarse y un botón para volver a la lista de leads.",
      },
    ],
  },
  {
    version: "0.29.0",
    date: "2026-06-02",
    title: {
      en: "Inbox: 'new + pending' counter and quick-access dropdown",
      es: "Inbox: contador 'nuevo + pendiente' y menú desplegable de acceso rápido",
    },
    changes: [
      {
        en: "The Inbox number in the nav now also counts NEW unreviewed communications (e.g. a voice call that just ended), not only those awaiting your reply. So a new call shows up instantly.",
        es: "El número del Inbox en el nav ahora cuenta también las comunicaciones NUEVAS sin revisar (ej. una llamada de voz recién terminada), no solo las que esperan tu respuesta. Así una llamada nueva se refleja al instante.",
      },
      {
        en: "Clicking the Inbox opens a menu: 'Go to inbox' (general section) on top and, below, direct access to each new/pending communication (with its channel icon 🗣️✉️💬 and preview) that jumps straight to the lead.",
        es: "Clic en el Inbox abre un menú: arriba 'Ir a la bandeja' (sección general) y debajo acceso directo a cada comunicación nueva/pendiente (con su ícono de canal 🗣️✉️💬 y vista previa) que lleva directo a la ficha del lead.",
      },
      {
        en: "Opening a lead marks it reviewed and removes it from the counter — unless it's still awaiting your reply (that clears on reply or with 'Handled').",
        es: "Abrir un lead lo marca como revisado y lo saca del contador — salvo que todavía esté esperando tu respuesta (ese se limpia al responder o con 'Atendido').",
      },
      {
        en: "Backend: new `needs_attention` (= awaiting reply OR new unhandled activity in the last 24h) + `attention` filter in `GET /inbox` and `attention` field in the counter.",
        es: "Backend: nuevo `needs_attention` (= esperando respuesta O actividad nueva sin atender en las últimas 24h) + filtro `attention` en `GET /inbox` y campo `attention` en el contador.",
      },
    ],
  },
  {
    version: "0.28.1",
    date: "2026-06-02",
    title: {
      en: "Voice fix: the call stays on ONE lead (transcript + visit + data)",
      es: "Fix voz: la llamada queda en UNA sola ficha (transcript + visita + datos)",
    },
    changes: [
      {
        en: "Bug: a call split into two leads — the VISIT landed on the number the caller dictated and the TRANSCRIPT on the real caller id. Fix: `book_visit` now anchors the lead to the caller id (the same one the end-of-call ingest uses) and keeps the dictated number as a callback note. So visit and transcript stay on the same lead.",
        es: "Bug: una llamada se partía en dos leads — la VISITA caía en el número que el cliente dictaba y la TRANSCRIPCIÓN en el caller id real. Fix: `book_visit` ahora ancla el lead al caller id (el mismo que usa el ingest del end-of-call), y guarda el número dictado como nota de callback. Así visita y transcripción quedan en la misma ficha.",
      },
      {
        en: "Bug: VAPI returned `structuredData` in a nested shape (`customer_info`/`property_inquiry`) that wasn't mapped → the lead ended up with no intent/zone/budget. Fix: `_flatten_voice_structured` normalizes both flat and nested shapes; plus an EXPLICIT schema is set on the assistant so future calls are deterministic.",
        es: "Bug: VAPI devolvía el `structuredData` en un shape anidado (`customer_info`/`property_inquiry`) que no se mapeaba → el lead quedaba sin intención/zona/presupuesto. Fix: `_flatten_voice_structured` normaliza el shape plano Y el anidado; además se define un schema EXPLÍCITO en el assistant para que las llamadas futuras vengan deterministas.",
      },
    ],
  },
  {
    version: "0.28.0",
    date: "2026-06-02",
    title: {
      en: "Phase 13 · Voice agent (VAPI) — calls that qualify and book visits",
      es: "Phase 13 · Agente de voz (VAPI) — llamadas que cualifican y agendan visitas",
    },
    changes: [
      {
        en: "New VOICE channel: the agent answers calls via VAPI (11labs female English voice + Claude Sonnet 4.5 as the realtime brain). It qualifies the client (buy/rent/valuation, zone, budget, timeline) and can BOOK A VISIT during the same call.",
        es: "Nuevo canal de VOZ: el agente atiende llamadas vía VAPI (voz femenina en inglés 11labs + Claude Sonnet 4.5 como cerebro en tiempo real). Cualifica al cliente (compra/renta/tasación, zona, presupuesto, timeline) y puede AGENDAR UNA VISITA durante la misma llamada.",
      },
      {
        en: "On hang-up, the call is ingested into the lead timeline (channel=\"voice\") with the full transcript, extracted fields and recomputed score — same as SMS/email. It shows in `/leads/{id}` with voice bubbles 🗣️.",
        es: "Al colgar, la llamada se ingiere al timeline del lead (channel=\"voice\") con la transcripción completa, los campos extraídos y el score recalculado — igual que SMS/email. Aparece en `/leads/{id}` con las burbujas de voz 🗣️.",
      },
      {
        en: "Backend: `services/voice.py` (VAPI secret verification, end-of-call-report parsing, `check_availability`/`book_visit` tool-calls reusing Phase 5 Cal.com) + `POST /api/v1/webhooks/voice` (answers tool-calls live and, with no LLM, ingests the finished call). Idempotent per call_id.",
        es: "Backend: `services/voice.py` (verificación del secret de VAPI, parseo del end-of-call-report, tool-calls `check_availability`/`book_visit` que reutilizan Cal.com de Phase 5) + `POST /api/v1/webhooks/voice` (responde los tool-calls en vivo y, sin LLM, ingiere la llamada terminada). Idempotente por call_id.",
      },
      {
        en: "`VOICE_SIMULATED=true` by default (dev + demo need no VAPI account). Outbound (the agent CALLING leads) is left for a future phase. Doc: `docs/setup-vapi.md`.",
        es: "`VOICE_SIMULATED=true` por defecto (dev + demo no necesitan cuenta VAPI). Outbound (que el agente LLAME a leads) queda para una fase futura. Doc: `docs/setup-vapi.md`.",
      },
    ],
  },
  {
    version: "0.27.1",
    date: "2026-06-01",
    title: {
      en: "More robust email threading: full References chain",
      es: "Threading de email más robusto: References con la cadena completa del hilo",
    },
    changes: [
      {
        en: "Threading hardening: the agent's reply now sets the `References` header to the FULL CHAIN (thread root … lead's message), not just `In-Reply-To` to the parent. This makes Gmail/Outlook reliably nest the reply inside the conversation instead of opening a new thread.",
        es: "Refuerzo del threading: la respuesta del agente ahora setea el header `References` con la CADENA COMPLETA (raíz del hilo … mensaje del lead), no solo el `In-Reply-To` al padre. Esto hace que Gmail/Outlook aniden la respuesta dentro de la conversación de forma confiable en vez de abrir un hilo nuevo.",
      },
      {
        en: "`services/email.py::send_email` accepts `references`; `conversation.py` builds the chain from `thread_id` (root) + `external_id` (inbound message) and passes it to the send.",
        es: "`services/email.py::send_email` acepta `references`; `conversation.py` arma la cadena desde `thread_id` (raíz) + `external_id` (mensaje entrante) y la pasa al envío.",
      },
    ],
  },
  {
    version: "0.27.0",
    date: "2026-06-01",
    title: {
      en: "Inbound email: fetch real body + Message-ID (Received Emails API) → correct threading",
      es: "Inbound email: traer cuerpo + Message-ID reales (Received Emails API) → threading correcto",
    },
    changes: [
      {
        en: "Cause of 'replies as a new email instead of nesting into the thread': Resend's `email.received` webhook is METADATA-ONLY (no body or headers), so the inbound arrived with empty content and without the real Message-ID → the reply couldn't be threaded.",
        es: "Causa del 'responde con correo nuevo en vez de enganchar al hilo': el webhook `email.received` de Resend es SOLO-METADATA (sin cuerpo ni headers), así que el inbound entraba con contenido vacío y sin el Message-ID real → la respuesta no podía threadearse.",
      },
      {
        en: "Fix: the webhook handler now calls `GET /emails/inbound/{id}` (Received Emails API) to fetch the FULL email — `text`, RFC822 `message_id` and `references`/`in_reply_to` — and passes it to the orchestrator. So the agent reads the real message and the reply goes out with correct `In-Reply-To`/`References` → Gmail nests it into the thread.",
        es: "Fix: el handler del webhook ahora hace `GET /emails/inbound/{id}` (Received Emails API) para traer el correo COMPLETO — `text`, `message_id` RFC822 y `references`/`in_reply_to` — y se lo pasa al orquestador. Así el agente lee el mensaje real y la respuesta sale con `In-Reply-To`/`References` correctos → Gmail la engancha al hilo.",
      },
      {
        en: "`services/email.py`: new `fetch_inbound_email(id)` + `_strip_quoted_reply()` (drops the quoted history like 'On … wrote:' / '>' so the agent sees only the new message). The SIMULATED path (tests) skips the fetch (it already carries the body).",
        es: "`services/email.py`: nuevo `fetch_inbound_email(id)` + `_strip_quoted_reply()` (quita el historial citado tipo 'On … wrote:' / '>' para que el agente vea solo el mensaje nuevo). El path SIMULADO (tests) no hace fetch (ya trae el cuerpo).",
      },
      {
        en: "Note: external delivery (Gmail→Resend) WAS working — the emails were in the Received Emails API; what was missing was pulling their content into the backend.",
        es: "Nota: la entrega externa (Gmail→Resend) SÍ funcionaba — los correos estaban en la Received Emails API; lo que faltaba era traer su contenido al backend.",
      },
    ],
  },
  {
    version: "0.26.1",
    date: "2026-06-01",
    title: {
      en: "Email anti-loop guard: the agent never replies to itself",
      es: "Guard anti-loop de email: el agente nunca se responde a sí mismo",
    },
    changes: [
      {
        en: "Security fix: an inbound email whose sender is OUR OWN sending address (`noreply@<domain>`) is now ignored. Without this, a reply/bounce addressed to noreply@ re-entered through the inbound webhook and the agent answered itself in an infinite loop (burning LLM + sending emails). Found during inbound testing.",
        es: "Fix de seguridad: un email entrante cuyo remitente es NUESTRA propia dirección de envío (`noreply@<dominio>`) ahora se ignora. Sin esto, una respuesta/bounce dirigida a noreply@ volvía a entrar por el webhook inbound y el agente se respondía a sí mismo en un loop infinito (gastando LLM + enviando emails). Detectado en pruebas de inbound.",
      },
      {
        en: "`services/conversation.py`: guard at the start of `handle_inbound_message` — if `channel=email` and the sender == the `RESEND_FROM` address, it returns `ignored_self_loop` without creating a lead or replying. +1 test.",
        es: "`services/conversation.py`: guard al inicio de `handle_inbound_message` — si `channel=email` y el remitente == la dirección de `RESEND_FROM`, retorna `ignored_self_loop` sin crear lead ni responder. +1 test.",
      },
    ],
  },
  {
    version: "0.26.0",
    date: "2026-06-01",
    title: {
      en: "Agent language: English by default, mirroring the lead's language (or the one they ask for)",
      es: "Idioma del agente: inglés por defecto, espejando el idioma del lead (o el que pida)",
    },
    changes: [
      {
        en: "The agent's communications are now in ENGLISH by default. If the lead writes in another supported language (es/en) it replies in that language (mirroring), and if they explicitly ask for another language, the agent switches to it.",
        es: "Las comunicaciones del agente ahora son en INGLÉS por defecto. Si el lead escribe en otro idioma soportado (es/en) se le responde en ese idioma (mirroring), y si pide explícitamente otro idioma, el agente cambia a ese.",
      },
      {
        en: "`services/i18n.py`: `DEFAULT_LANGUAGE` changed from `es` to `en` (default when the language can't be detected / text is ambiguous). The steering line now allows an explicit override ('UNLESS the client asks for another language').",
        es: "`services/i18n.py`: `DEFAULT_LANGUAGE` pasó de `es` a `en` (default cuando no se detecta idioma / texto ambiguo). La línea de steering ahora permite override explícito ('UNLESS the client asks for another language' / 'SALVO que pida otro idioma').",
      },
      {
        en: "`services/conversation.py`: the default supported-language order is now `['en','es']` (in the reply and the suggestions) → an unsupported language falls back to English. Before, the default was Spanish.",
        es: "`services/conversation.py`: el orden de idiomas soportados por defecto pasó a `['en','es']` (en el reply y en las sugerencias) → un idioma no soportado cae a inglés. Antes el default era español.",
      },
      {
        en: "i18n tests: +3 (English default, en-first mirroring, override on explicit request).",
        es: "Tests i18n: +3 (default inglés, mirroring con orden en-first, override por solicitud explícita).",
      },
    ],
  },
  {
    version: "0.25.0",
    date: "2026-06-01",
    title: {
      en: "Local LLM fallback with Gemma (Google) via Ollama — the agent replies even when paid quotas are exhausted",
      es: "Fallback LLM local con Gemma (Google) vía Ollama — el agente responde aunque las cuotas de pago estén agotadas",
    },
    changes: [
      {
        en: "Detected cause: the agent stopped replying to leads because BOTH paid LLM providers ran out of quota (Kimi: 'usage limit for this billing cycle'; MiniMax: 'usage limit exceeded'). It wasn't email or code.",
        es: "Causa detectada: el agente dejó de responder a los leads porque los DOS proveedores LLM de pago quedaron sin cuota (Kimi: 'usage limit for this billing cycle'; MiniMax: 'usage limit exceeded'). No era el email ni el código.",
      },
      {
        en: "Solution: a third LLM provider was added — Gemma (Google's open model) running LOCALLY on Ollama on the ROG — as a free final fallback. Order: Kimi → MiniMax → local Gemma. The paid ones stay first for quality; when both fail, local Gemma guarantees the lead gets a reply at no cost or quota.",
        es: "Solución: se agregó un tercer proveedor LLM — Gemma (modelo open de Google) corriendo LOCAL en Ollama en el ROG — como fallback final gratuito. Orden: Kimi → MiniMax → Gemma local. Los de pago siguen primero por calidad; cuando ambos fallan, Gemma local garantiza que el lead reciba respuesta sin costo ni cuota.",
      },
      {
        en: "`services/llm.py`: new `ollama` provider speaking Ollama's native API (`/api/chat`, with `format=json` for the classifier), separate from Kimi/MiniMax's Anthropic protocol. Enabled with `OLLAMA_ENABLED=true`. +1 test.",
        es: "`services/llm.py`: nuevo provider `ollama` que habla la API nativa de Ollama (`/api/chat`, con `format=json` para el clasificador), separado del protocolo Anthropic de Kimi/MiniMax. Se activa con `OLLAMA_ENABLED=true`. +1 test.",
      },
      {
        en: "Config: `OLLAMA_ENABLED`/`OLLAMA_BASE_URL`/`OLLAMA_MODEL`/`OLLAMA_TIMEOUT_SECONDS` in config.py + docker-compose. On the ROG the demo uses `gemma3:4b` (fits the RTX 3070 8GB).",
        es: "Config: `OLLAMA_ENABLED`/`OLLAMA_BASE_URL`/`OLLAMA_MODEL`/`OLLAMA_TIMEOUT_SECONDS` en config.py + docker-compose. En el ROG el demo usa `gemma3:4b` (entra en la RTX 3070 8GB).",
      },
    ],
  },
  {
    version: "0.24.1",
    date: "2026-05-31",
    title: {
      en: "Fix Add Lead: budget accepts '600k'/'1.2M' and readable validation errors",
      es: "Fix Add Lead: presupuesto acepta '600k'/'1.2M' y errores de validación legibles",
    },
    changes: [
      {
        en: "Bug: in Add Lead, typing the budget as '600k'/'800k' sent the raw string to the backend → 422 'Input should be a valid decimal', and the error showed as raw JSON in the modal.",
        es: "Bug: en Add Lead, escribir el presupuesto como '600k'/'800k' mandaba el string crudo al backend → 422 'Input should be a valid decimal', y el error se mostraba como JSON crudo en el modal.",
      },
      {
        en: "Fix: the budget is now normalized on the client — it accepts '600k', '1.2M', '600,000', '$850000' and converts them to a number before sending (k=×1,000, M=×1,000,000). If something stays non-numeric, it shows a clear notice instead of sending garbage to the backend.",
        es: "Fix: el presupuesto ahora se normaliza en el cliente — acepta '600k', '1.2M', '600,000', '$850000' y los convierte a número antes de enviar (k=×1.000, M=×1.000.000). Si queda algo no numérico, muestra un aviso claro en vez de mandar basura al backend.",
      },
      {
        en: "Fix: `errorDetail` (lib/api.ts) now formats FastAPI validation errors (when `detail` is an array) as readable 'field: message' text instead of dumping raw JSON (which could also break React if rendered as an object).",
        es: "Fix: `errorDetail` (lib/api.ts) ahora formatea los errores de validación de FastAPI (cuando `detail` es un array) como texto legible 'campo: mensaje' en vez de volcar el JSON crudo (que además podía romper React si se renderizaba como objeto).",
      },
    ],
  },
  {
    version: "0.24.0",
    date: "2026-05-31",
    title: {
      en: "Power layer in Properties (search + type chips + sort) and Analytics (weekly trend)",
      es: "Capa de potencia en Properties (buscador + chips de tipo + orden) y Analytics (tendencia semanal)",
    },
    changes: [
      {
        en: "Continues the Claude Design desktop work: the same 'intuitive but powerful' layer, now in Properties and Analytics. Frontend only, no backend changes.",
        es: "Continúa el diseño de escritorio de Claude Design: misma capa 'intuitivo pero potente' ahora en Properties y Analytics. Solo frontend, sin cambios de backend.",
      },
      {
        en: "Properties = CRM-style explorer: live search (zone/address/title/type) with `/` shortcut, filter chips by property type (derived from loaded listings), max-price filter, toggleable Recent↔Price sort, 'N of M active' counter, empty state with clear. The Sync MLS button stays.",
        es: "Properties = explorador estilo CRM: buscador en vivo (zona/dirección/título/tipo) con atajo `/`, chips de filtro por tipo de propiedad (derivados de los listings cargados), filtro de precio máximo, orden conmutable Recientes↔Precio, contador 'N de M activas', estado vacío con limpiar. Se mantiene el botón Sincronizar MLS.",
      },
      {
        en: "Analytics: ▲/▼ trend indicators computed for real from `leads_per_day` — a new 'New this week' card (sum of the last 7 days) with a % delta vs the previous 7 days, and the per-day chart highlights the current week (live bars) vs the previous one (dimmed). No invented metrics: the trend only shows where there's real time series.",
        es: "Analytics: indicadores de tendencia ▲/▼ calculados de verdad desde `leads_per_day` — nueva tarjeta 'Nuevos esta semana' (suma de los últimos 7 días) con delta % vs. los 7 días previos, y la gráfica por día resalta la semana actual (barras vivas) vs la anterior (atenuadas). Sin métricas inventadas: la tendencia solo se muestra donde hay serie temporal real.",
      },
      {
        en: "i18n EN+ES for everything new. All responsive; doesn't touch mobile or the rest of the dashboard.",
        es: "i18n EN+ES para todo lo nuevo. Todo responsive; no toca móvil ni el resto del dashboard.",
      },
    ],
  },
  {
    version: "0.23.0",
    date: "2026-05-29",
    title: {
      en: "More powerful desktop: CRM-style Leads (search + filters + sort) and detail with quick actions + 'Why this score'",
      es: "Escritorio más potente: Leads tipo CRM (buscador + filtros + orden) y detalle con acciones rápidas + 'Why this score'",
    },
    changes: [
      {
        en: "Implements the Claude Design desktop design: make the realtor feel the system is intuitive yet powerful. (Mobile shipped in v0.22.0; this is the desktop layer.)",
        es: "Implementa el diseño de escritorio de Claude Design: que el realtor sienta el sistema intuitivo pero potente. (El móvil quedó en v0.22.0; esto es la capa de escritorio.)",
      },
      {
        en: "Leads is now a CRM-style explorer (`LeadsExplorer`, replaces FilterBar+LeadsTable): live search (name/zone/contact/intent/type) with `/` keyboard shortcut, smart filter chips (All · 🔥 Hot · To reply · New · Qualified · Visiting · Won), toggleable Priority↔Recent sort (server-side) with 'N of M' counter, richer rows (red→amber accent bar on hot, amber 'to reply' dot, hover chevron) and an empty state with clear filters.",
        es: "Leads ahora es un explorador tipo CRM (`LeadsExplorer`, reemplaza FilterBar+LeadsTable): buscador en vivo (nombre/zona/contacto/intención/tipo) con atajo de teclado `/`, chips de filtro inteligentes (Todos · 🔥 Hot · Por responder · New · Qualified · Visiting · Won), orden conmutable Prioridad↔Reciente (server-side vía sort) con contador 'N de M', filas más ricas (barra de acento rojo→ámbar en hot, punto ámbar de 'por responder', chevron al hover) y estado vacío con limpiar filtros.",
      },
      {
        en: "Backend: `GET /leads` now returns `needs_response` per lead (last inbound message = awaiting reply), with a grouped query scoped to the page (no N+1, same pattern as the inbox). Feeds the 'To reply' chip and the row dot. +1 test.",
        es: "Backend: `GET /leads` ahora devuelve `needs_response` por lead (último mensaje entrante = espera respuesta), con una query agrupada scoped a la página (sin N+1, mismo patrón que el buzón). Alimenta el chip 'Por responder' y el punto de la fila. +1 test.",
      },
      {
        en: "Lead detail: a quick-actions bar (Reply → focuses the composer · Call → tel: on phone leads · Book visit → scroll to visits · Mark won → PATCH status=won) + a 'Why this score' card visualizing the real `score_breakdown` (Intent/Budget/Engagement/Urgency/Zone/Type/Recency/Visit) with gradient bars.",
        es: "Detalle del lead: barra de acciones rápidas (Responder → enfoca el composer · Llamar → tel: en leads con teléfono · Agendar visita → scroll a visitas · Marcar ganado → PATCH status=won) + tarjeta 'Why this score' que visualiza el `score_breakdown` real (Intención/Presupuesto/Interacción/Urgencia/Zona/Tipo/Recencia/Visita) con barras degradadas.",
      },
      {
        en: "Global polish: accessible focus ring (`:focus-visible`) + dark scrollbar matching the noir.",
        es: "Pulido global: anillo de foco accesible (`:focus-visible`) + scrollbar oscuro a juego con el noir.",
      },
      {
        en: "i18n EN+ES for everything new. The desktop gains power without breaking the mobile version (all responsive).",
        es: "i18n EN+ES para todo lo nuevo. El escritorio gana potencia sin romper la versión móvil (todo responsive).",
      },
    ],
  },
  {
    version: "0.22.1",
    date: "2026-05-29",
    title: {
      en: "Fix: 'Sign in with Google' works on mobile (popup → redirect)",
      es: "Fix: 'Sign in with Google' funciona en móvil (popup → redirect)",
    },
    changes: [
      {
        en: "Bug: on the phone, tapping 'Sign in with Google' opened a new tab at `accounts.google.com/gsi/transform` that stayed BLANK and wouldn't continue. Cause: the button used popup mode by default; mobile browsers open the popup as a separate tab and the credential never returns to the original tab. (On desktop the popup did work.) The v0.22.0 mobile release didn't cause it — the Google config was correct.",
        es: "Bug: en el teléfono, tocar 'Sign in with Google' abría una pestaña nueva en `accounts.google.com/gsi/transform` que quedaba EN BLANCO y no dejaba continuar. Causa: el botón usaba el modo popup por defecto; los navegadores móviles abren el popup como pestaña separada y el credencial nunca vuelve a la pestaña original. (En desktop el popup sí funcionaba.) No lo causó la release móvil v0.22.0 — la config de Google estaba correcta.",
      },
      {
        en: "Fix: the button now uses `ux_mode=redirect` + `login_uri` → Google does a full-page navigation (no popups) and posts the ID token to the backend. Works the same on mobile and desktop.",
        es: "Fix: el botón ahora usa `ux_mode=redirect` + `login_uri` → Google hace una navegación de página completa (sin popups) y postea el ID token al backend. Funciona igual en móvil y desktop.",
      },
      {
        en: "Backend: new `POST /api/v1/auth/login/google/callback` that verifies the anti-CSRF double-submit token (`g_csrf_token` body == cookie), validates the ID token + allow-list (reuses the JSON-flow helpers), sets the session cookie and redirects to `/leads`. Failures → `/login?error=google_failed|google_denied` (the login page shows the notice). +4 tests.",
        es: "Backend: nuevo `POST /api/v1/auth/login/google/callback` que verifica el token doble-submit anti-CSRF (`g_csrf_token` body == cookie), valida el ID token + allow-list (reusa los helpers del flujo JSON), setea la cookie de sesión y redirige a `/leads`. Fallos → `/login?error=google_failed|google_denied` (la página de login muestra el aviso). +4 tests.",
      },
      {
        en: "Requires adding ONE URL in Google Cloud Console → Authorized redirect URIs: `https://inmo-demo.ekoaiautomation.com/api/v1/auth/login/google/callback` (see docs/setup-google-signin.md). Password login didn't change.",
        es: "Requiere agregar UNA URL en Google Cloud Console → Authorized redirect URIs: `https://inmo-demo.ekoaiautomation.com/api/v1/auth/login/google/callback` (ver docs/setup-google-signin.md). El login por contraseña no cambió.",
      },
    ],
  },
  {
    version: "0.22.0",
    date: "2026-05-29",
    title: {
      en: "Native-app-style mobile dashboard: bottom tab bar + slim top bar + notch",
      es: "Dashboard móvil tipo app nativa: barra de pestañas inferior + barra superior delgada + notch",
    },
    changes: [
      {
        en: "Fixed bottom tab bar (phones only, hidden on desktop): Discovery · Leads · Inbox · Properties · Stats. The active tab is highlighted in violet per the current route; Inbox shows an amber dot when there are pending items. It's the primary navigation on mobile, native-app style.",
        es: "Barra de pestañas inferior fija (solo en teléfonos, oculta en escritorio): Discovery · Leads · Inbox · Properties · Stats. La pestaña activa se resalta en violeta según la ruta actual; Inbox muestra un punto ámbar cuando hay pendientes. Es la navegación principal en móvil, estilo app nativa.",
      },
      {
        en: "The top bar is simplified on mobile: brand + language + logout (and a Settings gear for admins, since it's not in the tab bar). The full desktop links hide below `md`. Desktop doesn't change.",
        es: "La barra superior se simplifica en móvil: marca + idioma + salir (y engranaje de Settings para admins, ya que no está en la tab bar). Los enlaces completos de escritorio se ocultan por debajo de `md`. El escritorio no cambia.",
      },
      {
        en: "Notch / safe-area support: `viewport-fit=cover` + dark `theme-color` + apple-web-app metadata; the tab bar respects `env(safe-area-inset-bottom)` and content reserves bottom space (via `body:has(.eko-tabbar)`, without affecting login/about which have no tab bar).",
        es: "Soporte de notch / safe-area: `viewport-fit=cover` + `theme-color` oscuro + metadatos apple-web-app; la tab bar respeta `env(safe-area-inset-bottom)` y el contenido reserva espacio inferior (vía `body:has(.eko-tabbar)`, sin afectar login/about que no tienen tab bar).",
      },
      {
        en: "Touch composer on mobile: full-width channel selector (SMS/Email/Voice) with bigger tap targets; 'Suggest replies' and 'Send' buttons easier on the thumb. Desktop stays the same.",
        es: "Composer táctil en móvil: selector de canal (SMS/Email/Voz) a ancho completo con áreas de toque más grandes; botones 'Sugerir respuestas' y 'Enviar' más cómodos para el dedo. En escritorio queda igual.",
      },
      {
        en: "Single-column stacking was already handled in the pages via Tailwind responsive classes; this release adds the missing native mobile chrome.",
        es: "El stacking a una columna ya estaba resuelto en las páginas vía clases responsive de Tailwind; este release añade la capa de chrome nativo móvil que faltaba.",
      },
    ],
  },
  {
    version: "0.21.2",
    date: "2026-05-28",
    title: {
      en: "Inbox 'handled' state in its own column (removes the Lead.meta race)",
      es: "Estado 'atendido' del buzón en columna propia (elimina race en Lead.meta)",
    },
    changes: [
      {
        en: "The inbox 'handled' state moved from `Lead.meta[\"inbox\"][\"handled_at\"]` (JSON blob) to a dedicated column `leads.inbox_handled_at` (Alembic 009, backfilled from the existing JSON). Before, marking handled reassigned the WHOLE meta dict → it could clobber (or be clobbered by) another concurrent meta writer (e.g. discovery enrichment writing `meta.enrichment`). Now they're separate columns and don't interfere.",
        es: "El estado 'atendido' del buzón se movió de `Lead.meta[\"inbox\"][\"handled_at\"]` (blob JSON) a una columna dedicada `leads.inbox_handled_at` (Alembic 009, con backfill desde el JSON existente). Antes, marcar atendido reasignaba TODO el dict meta → podía pisar (o ser pisado por) otro writer concurrente del meta (p.ej. el enriquecimiento de discovery escribiendo `meta.enrichment`). Ahora son columnas distintas y no se interfieren.",
      },
      {
        en: "set_handled() now does `lead.inbox_handled_at = when` (no ISO parsing or dict reassignment). Removed the silent parse that could leave a lead 'pending' forever on a corrupt value.",
        es: "set_handled() ahora hace `lead.inbox_handled_at = when` (sin parseo de ISO ni reasignación de dict). Eliminado el parse silencioso que podía dejar un lead 'pendiente' para siempre ante un valor corrupto.",
      },
      {
        en: "Regression test +1: two concurrent sessions on the same lead (one writes meta.enrichment, the other marks handled) → both survive (with the old approach, the last commit erased the other).",
        es: "Test de regresión +1: dos sesiones concurrentes sobre el mismo lead (una escribe meta.enrichment, otra marca atendido) → ambos sobreviven (con el enfoque viejo, el último commit borraba el otro).",
      },
    ],
  },
  {
    version: "0.21.1",
    date: "2026-05-28",
    title: {
      en: "Inbox code-review fixes: past visits, incompatible channel, per-channel counts",
      es: "Fixes de code-review del buzón: visitas pasadas, canal incompatible, counts por canal",
    },
    changes: [
      {
        en: "Fix: the 'Booked' filter showed already-past visits still in scheduled/confirmed (never marked completed). Now _next_visit_per_lead filters scheduled_at >= now → it only counts the NEXT future visit (before it could show the oldest, even a past one).",
        es: "Fix: el filtro 'Con cita' mostraba visitas ya pasadas que seguían en estado scheduled/confirmed (nunca se marcaron completed). Ahora _next_visit_per_lead filtra scheduled_at >= ahora → solo cuenta la PRÓXIMA visita futura (antes podía mostrar la más vieja, incluso pasada).",
      },
      {
        en: "Fix: the channel selector let you pick Email for a phone-only lead (or SMS for an email-only one), which tried to send to an invalid recipient and stored the message as FAILED. Now it validates the channel can reach the lead's identifier (email→address, sms/whatsapp→phone); if not, it returns 'channel_identifier_mismatch' without creating an undeliverable conversation, and the composer shows a clear notice.",
        es: "Fix: el selector de canal permitía elegir Email para un lead identificado solo por teléfono (o SMS para uno de email), lo que intentaba enviar a un destinatario inválido y guardaba el mensaje como FAILED. Ahora se valida que el canal pueda alcanzar al identificador del lead (email→dirección, sms/whatsapp→teléfono); si no, devuelve 'channel_identifier_mismatch' sin crear una conversación no entregable, y el composer muestra un aviso claro.",
      },
      {
        en: "Fix: with ?channel=X the pending/booked counters were computed before filtering by channel → the badges didn't match the rows. Now they're computed over the already-channel-filtered set.",
        es: "Fix: con ?channel=X los contadores pending/booked se calculaban antes de filtrar por canal → los badges no coincidían con las filas. Ahora se calculan sobre el conjunto ya filtrado por canal.",
      },
      {
        en: "Tests +4: past visit doesn't count as 'booked' (+ next_visit_at is the future one), incompatible channel rejected without creating a conversation, create-when-missing uses a compatible channel (whatsapp→sms), counts scoped by channel.",
        es: "Tests +4: visita pasada no cuenta como 'con cita' (+ next_visit_at es la futura), canal incompatible rechazado sin crear conversación, create-when-missing usa canal compatible (whatsapp→sms), counts scoped por canal.",
      },
    ],
  },
  {
    version: "0.21.0",
    date: "2026-05-28",
    title: {
      en: "Communications inbox — lead mailbox with badges, filters and priority",
      es: "Bandeja de comunicaciones — buzón de leads con badges, filtros y prioridad",
    },
    changes: [
      {
        en: "New 'Inbox' tab in the Nav (with a pending counter): an email-style mailbox listing leads with open conversations. Each lead shows its priority (🔥/🟡/⚪), a pending channel badge (✉️ Email / 💬 SMS / 🗣️ Voice) when we owe a reply, and 📅 Visit with date if it has a booked visit; those with nothing pending show '✅ Up to date'.",
        es: "Nueva pestaña 'Bandeja' en el Nav (con contador de pendientes): un buzón estilo correo que lista los leads con conversaciones abiertas. Cada lead muestra su prioridad (🔥/🟡/⚪), un badge del canal pendiente (✉️ Email / 💬 SMS / 🗣️ Voz) cuando esperamos responderle, y 📅 Cita con fecha si tiene una visita agendada; los que no tienen nada pendiente muestran '✅ Al día'.",
      },
      {
        en: "Filters: Pending (default) / Booked / All. Auto-sort by priority (score desc; within the same, the one waiting longest first). 'Pending' = the lead's last message is inbound and we haven't replied/handled it since.",
        es: "Filtros: Pendientes (default) / Con cita / Todos. Orden automático por prioridad (score desc; dentro del mismo, el que espera hace más tiempo primero). 'Pendiente' = el último mensaje del lead es entrante y no lo respondimos/atendimos desde entonces.",
      },
      {
        en: "Marking 'Handled' removes the lead from pending (saved in Lead.meta — no migration); it reappears only if a new lead message arrives. Replying from the conversation also removes it from pending (the last message becomes outbound). A 'Reply' button opens the lead's unified conversation.",
        es: "Marcar 'Atendido' quita el lead de pendientes (se guarda en Lead.meta — sin migración); reaparece solo si entra un nuevo mensaje del lead. Responder desde la conversación también lo saca de pendientes (el último mensaje pasa a saliente). Botón 'Responder' abre la conversación unificada del lead.",
      },
      {
        en: "Backend: services/inbox.py (derived states via grouped queries, no N+1: last message per lead, channels per lead, next active visit) + api/v1/inbox.py (GET /api/v1/inbox?filter=pending|booked|all, GET /inbox/count for the Nav badge, POST/DELETE /inbox/{id}/handled). Protected by the same require_auth as the rest of the data API.",
        es: "Backend: services/inbox.py (estados derivados con queries agrupadas, sin N+1: último mensaje por lead, canales por lead, próxima visita activa) + api/v1/inbox.py (GET /api/v1/inbox?filter=pending|booked|all, GET /inbox/count para el badge del Nav, POST/DELETE /inbox/{id}/handled). Protegido por el mismo require_auth que el resto del data API.",
      },
      {
        en: "Tests +5: pending reflects the last inbound per channel; 'handled' suppresses and a new inbound re-arms; filter=booked only with a visit ordered by date; priority sort + consistent count; mark-handled idempotent + isolated between leads + 404.",
        es: "Tests +5: pending refleja el último entrante por canal; 'atendido' suprime y un nuevo entrante re-arma; filter=booked solo con cita ordenado por fecha; orden por prioridad + count coherente; mark-handled idempotente + aislado entre leads + 404.",
      },
    ],
  },
  {
    version: "0.20.0",
    date: "2026-05-28",
    title: {
      en: "Unified multichannel thread per lead + channel selector + real email (plumbing)",
      es: "Hilo unificado multicanal por lead + selector de canal + email real (plumbing)",
    },
    changes: [
      {
        en: "The lead conversation is now ONE thread that merges ALL channels (SMS + email + WhatsApp) into a time-ordered timeline; each bubble shows its channel icon and the header lists the active channels. Before, you only saw the most recent channel.",
        es: "La conversación del lead ahora es UN solo hilo que junta TODOS los canales (SMS + email + WhatsApp) en una línea de tiempo ordenada por fecha; cada burbuja muestra el ícono de su canal y el header lista los canales activos. Antes solo se veía el canal más reciente.",
      },
      {
        en: "New endpoint GET /api/v1/conversations/{lead_id}/timeline (merges messages from all the lead's conversations with their channel; returns channels[], primary_channel and per-channel summaries; empty 200 if the lead has no conversation yet). MessageOut now includes `channel`.",
        es: "Nuevo endpoint GET /api/v1/conversations/{lead_id}/timeline (mergea los mensajes de todas las conversaciones del lead con su canal; devuelve channels[], primary_channel y resúmenes por canal; 200 vacío si el lead aún no tiene conversación). MessageOut ahora incluye `channel`.",
      },
      {
        en: "The composer lets you CHOOSE the channel when replying (SMS / Email active; Voice disabled 'coming soon', Phase 13). If the lead didn't have that channel, the conversation is created on send. send_human_message accepts `channel` (auto-pick if omitted, back-compat) and rejects voice; HumanMessageIn.channel = Literal[sms,email,whatsapp] (voice → 422).",
        es: "El composer permite ELEGIR el canal al responder (SMS / Email activos; Voz deshabilitada 'próximamente', Phase 13). Si el lead no tenía ese canal, se crea la conversación al enviar. send_human_message acepta `channel` (auto-pick si se omite, back-compat) y rechaza voz; HumanMessageIn.channel = Literal[sms,email,whatsapp] (voz → 422).",
      },
      {
        en: "Fix: the sent message now appears instantly (timeline refetch on the client) instead of relying on router.refresh() — which didn't re-run the client component's effect (the outbound wasn't visible until reload).",
        es: "Fix: el mensaje enviado ahora aparece al instante (refetch del timeline en el cliente) en vez de depender de router.refresh() — que no re-ejecutaba el efecto del componente cliente (el outbound no se veía hasta recargar).",
      },
      {
        en: "Real email (plumbing): docker-compose now passes EMAIL_SIMULATED/RESEND_API_KEY/RESEND_FROM/RESEND_WEBHOOK_SECRET to the backend (was missing); RESEND_FROM default moved to a DEDICATED subdomain (realtors.ekoaiautomation.com) — never mixed with Eko AI Main's biz.ekoaiautomation.com. New guide docs/setup-email.md (subdomain signup + Cloudflare DNS, isolated from the sales platform).",
        es: "Email real (plumbing): docker-compose ahora pasa EMAIL_SIMULATED/RESEND_API_KEY/RESEND_FROM/RESEND_WEBHOOK_SECRET al backend (faltaba); RESEND_FROM default movido a un subdominio DEDICADO (realtors.ekoaiautomation.com) — nunca se mezcla con biz.ekoaiautomation.com de Eko AI Main. Nueva guía docs/setup-email.md (alta de subdominio + DNS Cloudflare, aislado de la sales platform).",
      },
      {
        en: "Tests +8: timeline (2-channel ordered merge, id tiebreak, empty 200) + channel selection (reuses existing conversation, creates if missing, voice 422 + service-level unsupported_channel, auto-pick with no channel).",
        es: "Tests +8: timeline (merge 2 canales ordenado, tiebreak por id, vacío 200) + selección de canal (reusa conversación existente, crea si falta, voz 422 + unsupported_channel a nivel servicio, auto-pick sin canal).",
      },
    ],
  },
  {
    version: "0.19.0",
    date: "2026-05-27",
    title: {
      en: "Sign in with Apple — Apple login (alongside Google + password)",
      es: "Sign in with Apple — login con Apple (además de Google + contraseña)",
    },
    changes: [
      {
        en: "New 'Sign in with Apple' button on /login, below the Google one under the same 'or' separator. Coexists with the password and Google — none replaces the other.",
        es: "Nuevo botón 'Entrar con Apple' en /login, debajo del de Google bajo el mismo separador 'o'. Convive con la contraseña y con Google — ninguno reemplaza al otro.",
      },
      {
        en: "Uses Sign in with Apple JS in popup mode: Apple authenticates in a popup and returns the id_token on the same page; the frontend posts it to POST /api/v1/auth/login/apple.",
        es: "Usa Sign in with Apple JS en modo popup: Apple autentica en una ventana emergente y devuelve el id_token en la misma página; el frontend lo manda a POST /api/v1/auth/login/apple.",
      },
      {
        en: "Backend: verify_apple_id_token validates the identity token's RS256 signature against Apple's public keys (appleid.apple.com/auth/keys), + iss=https://appleid.apple.com, aud=APPLE_CLIENT_ID (the Services ID) and expiry. Reuses the SAME access list as Google (resolve_email_access) — the list is keyed by email, not provider — so an already-authorized email gets in via Apple with the same role.",
        es: "Backend: verify_apple_id_token valida la firma RS256 del identity token contra las llaves públicas de Apple (appleid.apple.com/auth/keys), + iss=https://appleid.apple.com, aud=APPLE_CLIENT_ID (el Services ID) y expiración. Reutiliza la MISMA lista de acceso que Google (resolve_email_access) — la lista se llava por email, no por proveedor — así un correo ya autorizado entra por Apple con el mismo rol.",
      },
      {
        en: "The popup flow returns the id_token directly, so it does NOT require a client secret or .p8 key: just the public Services ID. Apple hidden-relay emails (@privaterelay.appleid.com) only get in if explicitly allow-listed.",
        es: "El flujo popup devuelve el id_token directo, así que NO requiere client secret ni llave .p8: solo el Services ID público. Los correos ocultos de Apple (@privaterelay.appleid.com) solo entran si se autorizan explícitamente.",
      },
      {
        en: "Config: APPLE_CLIENT_ID (backend) + NEXT_PUBLIC_APPLE_CLIENT_ID + NEXT_PUBLIC_APPLE_REDIRECT_URI (frontend, inlined at build). Passed via docker-compose + Dockerfile like Google's. /api/v1/auth/me now reports apple_signin_enabled.",
        es: "Config: APPLE_CLIENT_ID (backend) + NEXT_PUBLIC_APPLE_CLIENT_ID + NEXT_PUBLIC_APPLE_REDIRECT_URI (frontend, inlined en build). Pasados por docker-compose + Dockerfile como los de Google. /api/v1/auth/me ahora reporta apple_signin_enabled.",
      },
      {
        en: "New dependency: pyjwt[crypto] (PyJWKClient to fetch Apple's keys + RSA verification). docs/setup-apple-signin.md with the App ID/Services ID signup at developer.apple.com + troubleshooting.",
        es: "Dependencia nueva: pyjwt[crypto] (PyJWKClient para traer las llaves de Apple + verificación RSA). docs/setup-apple-signin.md con el alta de App ID/Services ID en developer.apple.com + troubleshooting.",
      },
      {
        en: "Tests +4: verify_apple_id_token (happy path with mocked JWKS+decode → verified email; rejects not-configured and unverified email), /me reports apple_signin_enabled, and the Apple login flows (pinned admin + DB member + denied off-list) reusing the Google list.",
        es: "Tests +4: verify_apple_id_token (happy path con JWKS+decode mockeados → email verificado; rechaza no-configurado y email no verificado), /me reporta apple_signin_enabled, y los flujos de login Apple (admin fijado + member de DB + denegado fuera de la lista) reutilizando la lista de Google.",
      },
    ],
  },
  {
    version: "0.18.0",
    date: "2026-05-27",
    title: {
      en: "Version button + changelog in the dashboard",
      es: "Botón de versión + historial de cambios en el dashboard",
    },
    changes: [
      {
        en: "New version button (pill `v0.18.0`) top-right in the Nav, next to the language selector. Clicking it opens a modal with the full version history (version, date, title and changes) read from `lib/version.ts` — like Eko AI Main's.",
        es: "Nuevo botón de versión (pill `v0.18.0`) arriba a la derecha en el Nav, junto al selector de idioma. Al hacer click abre un modal con el historial completo de versiones (versión, fecha, título y cambios) leído de `lib/version.ts` — igual que el de Eko AI Main.",
      },
      {
        en: "The modal closes with ESC, click-outside or the Close button; it locks body scroll while open; rendered via portal. Dashboard violet/noir palette and EN/ES i18n.",
        es: "El modal cierra con ESC, click afuera o el botón Cerrar; bloquea el scroll del body mientras está abierto; se renderiza vía portal. Paleta violeta/noir del dashboard e i18n EN/ES.",
      },
    ],
  },
  {
    version: "0.17.0",
    date: "2026-05-27",
    title: {
      en: "Add Lead — manual lead creation (demo + operational use) with AI kickoff",
      es: "Add Lead — alta manual de leads (demo + uso operativo) con arranque de IA",
    },
    changes: [
      {
        en: "New 'Add Lead' button on /leads + a modal to create a lead by hand. Two uses, same flow: (1) the realtor poses as a client to experience the agent, and (2) the realtor adds a real lead (referral/contact) to their CRM. In both cases the lead enters the SAME pipeline as auto-captured ones — scoring, intent classification, property matching and follow-ups.",
        es: "Nuevo botón 'Add Lead' en /leads + modal para crear un lead a mano. Dos usos con el mismo flujo: (1) el realtor se hace pasar por un cliente para experimentar al agente, y (2) el realtor agrega un lead real (referido/contacto) a su CRM. En ambos casos el lead entra al MISMO pipeline que los capturados automáticamente — scoring, clasificación de intent, matching de propiedades y follow-ups.",
      },
      {
        en: "Optional 'client first message' field: if filled, it's injected as an INBOUND message and triggers the full AI turn (classify + reply + send on the chosen channel) through the same path as a real webhook. On save, the dashboard lands right in the lead's conversation with the AI reply already generated.",
        es: "Campo opcional 'primer mensaje del cliente': si se llena, se inyecta como mensaje INBOUND y dispara el turno completo de la IA (clasifica + responde + envía por el canal elegido) por el mismo camino que un webhook real. Al guardar, el dashboard cae directo en la conversación del lead con la respuesta de la IA ya generada.",
      },
      {
        en: "Modal channels: SMS (default) and Email work today; Voice appears disabled ('coming soon', Phase 13) and WhatsApp is out for now (re-added when enabled). The backend only accepts sms/email for the kickoff, so it doesn't create a conversation that can't be delivered.",
        es: "Canales del modal: SMS (default) y Email funcionan hoy; Voz aparece deshabilitada ('próximamente', Phase 13) y WhatsApp queda fuera por ahora (se re-agrega cuando se habilite). El backend solo acepta sms/email para el arranque, así no se crea una conversación que no se pueda entregar.",
      },
      {
        en: "Backend: POST /api/v1/leads (LeadCreate schema, extra='forbid') with dedupe by identifier (409 if exists), marks meta.source='manual' (NOT demo → a first-class lead, not deletable by seed_demo --reset) and rescores on create. Reuses handle_inbound_message for the first turn; behind the same require_auth as the rest of the data API.",
        es: "Backend: POST /api/v1/leads (schema LeadCreate, extra='forbid') con dedupe por identificador (409 si ya existe), marca meta.source='manual' (NO demo → es un lead de primera clase, no borrable por seed_demo --reset) y rescorea al crear. Reutiliza handle_inbound_message para el primer turno; queda detrás del mismo require_auth que el resto del data API.",
      },
      {
        en: "Frontend: AddLeadButton (modal with the dashboard violet/noir palette), leadsApi.create + LeadCreate interface, EN/ES i18n.",
        es: "Frontend: AddLeadButton (modal con paleta violeta/noir del dashboard), leadsApi.create + interface LeadCreate, i18n EN/ES.",
      },
      {
        en: "Tests +5: create without message (source=manual + score + no conversation), create with first message (mocked LLM → conversation + inbound/outbound), duplicate 409, missing phone 422, unknown field 422.",
        es: "Tests +5: create sin mensaje (source=manual + score + sin conversación), create con primer mensaje (LLM mockeado → conversación + inbound/outbound), duplicado 409, falta phone 422, campo desconocido 422.",
      },
    ],
  },
  {
    version: "0.16.2",
    date: "2026-05-27",
    title: {
      en: "Fix — Google login was failing (missing `requests` library)",
      es: "Fix — el login con Google fallaba (faltaba la librería `requests`)",
    },
    changes: [
      {
        en: "Symptom: the Google button appeared but choosing the account gave 'Google sign-in failed'. Cause: google-auth uses `requests` as the HTTP transport to fetch Google's public keys when validating the ID token, but `requests` is an OPTIONAL dependency and wasn't in requirements → verify_oauth2_token threw 'requests library is not installed' → 401.",
        es: "Síntoma: el botón de Google aparecía pero al elegir la cuenta daba 'Google sign-in failed'. Causa: google-auth usa `requests` como transporte HTTP para traer las llaves públicas de Google al validar el ID token, pero `requests` es dependencia OPCIONAL y no estaba en requirements → verify_oauth2_token tiraba 'requests library is not installed' → 401.",
      },
      {
        en: "Fix: added `requests==2.32.3` to backend/requirements.txt. (Password login was never affected.)",
        es: "Fix: agregado `requests==2.32.3` a backend/requirements.txt. (El password login nunca se vio afectado.)",
      },
      {
        en: "Regression test: `verify_google_id_token` with a malformed token must now fail with 'invalid_id_token', NOT 'google_auth_library_missing' — so a missing transport is caught in CI (before, the tests mocked the verification and didn't catch it).",
        es: "Test de regresión: `verify_google_id_token` con un token malformado ahora debe fallar con 'invalid_id_token', NO con 'google_auth_library_missing' — así un transporte ausente se detecta en CI (antes los tests mockeaban la verificación y no lo agarraban).",
      },
    ],
  },
  {
    version: "0.16.1",
    date: "2026-05-27",
    title: {
      en: "Fix — pass the Google Sign In variables to the containers (compose + Dockerfile)",
      es: "Fix — pasar las variables de Google Sign In a los contenedores (compose + Dockerfile)",
    },
    changes: [
      {
        en: "v0.16.0 brought the Google Sign In code but docker-compose.yml didn't pass the GOOGLE_* variables to the backend, so GOOGLE_ADMIN_EMAILS never reached the container and the bootstrap admin wasn't seeded into allowed_users.",
        es: "v0.16.0 trajo el código de Google Sign In pero el docker-compose.yml no pasaba las variables GOOGLE_* al backend, así que GOOGLE_ADMIN_EMAILS no llegaba al contenedor y el admin bootstrap no se sembraba en allowed_users.",
      },
      {
        en: "Fix: the backend environment block now passes GOOGLE_CLIENT_ID, GOOGLE_ADMIN_EMAILS, GOOGLE_ALLOWED_EMAILS and GOOGLE_ALLOWED_DOMAIN; the frontend receives NEXT_PUBLIC_GOOGLE_CLIENT_ID as a build arg (Next.js inlines NEXT_PUBLIC_* at build time, hence in the Dockerfile, not runtime).",
        es: "Fix: el bloque environment del backend ahora pasa GOOGLE_CLIENT_ID, GOOGLE_ADMIN_EMAILS, GOOGLE_ALLOWED_EMAILS y GOOGLE_ALLOWED_DOMAIN; el frontend recibe NEXT_PUBLIC_GOOGLE_CLIENT_ID como build arg (Next.js inyecta NEXT_PUBLIC_* en tiempo de build, por eso va en el Dockerfile, no en runtime).",
      },
    ],
  },
  {
    version: "0.16.0",
    date: "2026-05-27",
    title: {
      en: "Google Sign In + admin-managed access control (team managed from Settings)",
      es: "Google Sign In + control de acceso por admin (equipo gestionado desde Settings)",
    },
    changes: [
      {
        en: "Google login (Google Identity Services): a 'Sign in with Google' button on /login that coexists with the password. The backend validates the ID token (signature + email_verified) with google-auth and issues the same HMAC session cookie.",
        es: "Login con Google (Google Identity Services): botón 'Entrar con Google' en /login que convive con la contraseña. El backend valida el ID token (firma + email_verified) con la librería google-auth y emite la misma cookie de sesión HMAC.",
      },
      {
        en: "The session now carries identity + role (admin/member). Password login signs in as ADMIN (master key); Google login takes the role from the access list.",
        es: "La sesión ahora lleva identidad + rol (admin/member). El login por contraseña entra como ADMIN (llave maestra); el login por Google toma el rol de la lista de acceso.",
      },
      {
        en: "The allowed-emails list moved from environment variables to the DATABASE (allowed_users table) — admins manage it live from Settings, no redeploy. Each email has an admin or member role.",
        es: "La lista de correos permitidos se movió de variables de entorno a la BASE DE DATOS (tabla allowed_users) — el admin la gestiona en vivo desde Settings, sin redeploy. Cada correo tiene rol admin o member.",
      },
      {
        en: "Settings is back in the nav bar and is ADMIN-ONLY (hidden + 403 for members). It includes the 'Team / Access' panel: add Gmail addresses, set role, promote to admin or remove.",
        es: "Settings volvió a la barra de navegación y es SOLO para admins (oculto y 403 para members). Incluye el panel 'Equipo / Acceso': agregar correos Gmail, asignar rol, promover a admin o quitar.",
      },
      {
        en: "Bootstrap admin pinned by env (GOOGLE_ADMIN_EMAILS) — can't be demoted or removed from the UI, and the API refuses to remove the last admin. Together with the admin-password, this guarantees you never lock yourself out.",
        es: "Admin bootstrap fijado por entorno (GOOGLE_ADMIN_EMAILS) — no se puede degradar ni eliminar desde la UI, y la API rechaza quitar al último admin. Junto con la contraseña-admin, esto garantiza que nunca te quedás afuera.",
      },
      {
        en: "Security: members use the dashboard but get 403 on /team and /settings; a Google account off the list is rejected with a clear message. The GIS flow has no client secret (just the public Client ID).",
        es: "Seguridad: members usan el dashboard pero reciben 403 en /team y /settings; una cuenta de Google fuera de la lista es rechazada con mensaje claro. El flujo GIS no tiene client secret (solo el Client ID público).",
      },
    ],
  },
  {
    version: "0.15.2",
    date: "2026-05-27",
    title: {
      en: "Nav reordered: Discovery · Leads · Properties · Analytics · API · EN",
      es: "Nav reordenado: Discovery · Leads · Properties · Analytics · API · EN",
    },
    changes: [
      {
        en: "Reordered the nav bar to: Discovery, Leads, Properties, Analytics, API, EN (language selector). Discovery goes first (the prospecting flow starts there).",
        es: "Reordené la barra de navegación a: Discovery, Leads, Properties, Analytics, API, EN (selector de idioma). Discovery queda primero (el flujo de prospección arranca ahí).",
      },
      {
        en: "Settings was removed from the top bar so the menu matches what was requested; the page is still available at /settings.",
        es: "Settings se quitó de la barra superior para que el menú coincida con lo pedido; la página sigue disponible en /settings.",
      },
    ],
  },
  {
    version: "0.15.1",
    date: "2026-05-27",
    title: {
      en: "Discovery — SIMULATED fallback per category without a real provider (demo always shows leads)",
      es: "Discovery — fallback a SIMULATED por categoría sin proveedor real (demo siempre muestra leads)",
    },
    changes: [
      {
        en: "In real mode (DISCOVERY_SIMULATED=false, as the ROG demo runs) only investor_llc returned data (free Colorado SOS); the seller categories (fsbo/expired/absentee/preforeclosure/high_equity) and renter came back EMPTY because they have no free real source (ATTOM is paid, FSBO needs a licensed feed).",
        es: "En modo real (DISCOVERY_SIMULATED=false, como corre el demo del ROG) sólo investor_llc traía datos (Colorado SOS gratis); las categorías de vendedor (fsbo/expired/absentee/preforeclosure/high_equity) y renter salían VACÍAS porque no tienen fuente real gratis (ATTOM es pago, FSBO necesita feed licenciado).",
      },
      {
        en: "Fix: if a category has no real provider configured (or returns empty), Discovery falls back to that category's curated SIMULATED leads — so all 7 categories always show demoable leads. Real data (Colorado SOS, and ATTOM once the key is set) takes precedence when present.",
        es: "Fix: si una categoría no tiene proveedor real configurado (o devuelve vacío), Discovery cae a los leads curados SIMULATED de esa categoría — así las 7 categorías siempre muestran leads demoables. Los datos reales (Colorado SOS, y ATTOM cuando se ponga la key) tienen precedencia cuando existen.",
      },
      {
        en: "Test: in real mode, fsbo with no provider still returns simulated leads.",
        es: "Test: en modo real, fsbo sin proveedor sigue devolviendo leads simulados.",
      },
    ],
  },
  {
    version: "0.15.0",
    date: "2026-05-27",
    title: {
      en: "Discovery v2 — search re-oriented to real real-estate leads (not businesses)",
      es: "Discovery v2 — búsqueda reorientada a leads inmobiliarios reales (no negocios)",
    },
    changes: [
      {
        en: "Discovery stopped searching for 'businesses' (Google Maps/Yelp/LinkedIn) and now searches REAL-ESTATE LEADS by category, like an agent prospects. Sellers: FSBO (for sale by owner), expired listings, absentee/out-of-state owners, pre-foreclosure (distressed), high equity (likely-to-sell). Buyers: LLC investors, renters/relocators.",
        es: "Discovery dejó de buscar 'negocios' (Google Maps/Yelp/LinkedIn) y ahora busca LEADS INMOBILIARIOS por categoría, como prospecta un agente. Vendedores: FSBO (venta por dueño), listings expirados, dueños ausentes/fuera del estado, pre-ejecución (distressed), alta plusvalía (likely-to-sell). Compradores: inversores LLC, inquilinos/relocators.",
      },
      {
        en: "Deep research documented in docs/discovery-realestate-research.md (sources by ROI, accessible APIs ATTOM/PropStream/county records/Colorado SOS, and TCPA/DNC compliance).",
        es: "Investigación profunda documentada en docs/discovery-realestate-research.md (fuentes por ROI, APIs accesibles ATTOM/PropStream/county records/Colorado SOS, y cumplimiento TCPA/DNC).",
      },
      {
        en: "Each lead carries motivation ('listing expired 2 weeks ago', 'notice of default'), timeline (immediate/3-6m/exploring), property type and estimated value — which enrichment uses to classify intent (seller→valuation, buyer→buy/rent) and score the lead's heat.",
        es: "Cada lead trae motivación ('listing expiró hace 2 semanas', 'notice of default'), timeline (inmediato/3-6m/explorando), tipo de propiedad y valor estimado — que el enriquecimiento usa para clasificar intent (vendedor→valuation, comprador→buy/rent) y puntuar el calor del lead.",
      },
      {
        en: "SIMULATED-first as always: a curated set of ~17 realistic CO leads per category, $0 without keys. Real per category: investor_llc via Colorado SOS (FREE, already worked); absentee/preforeclosure/high_equity via ATTOM (ATTOM_API_KEY, key-gated stub); fsbo/expired/renter need a licensed feed (stay SIMULATED).",
        es: "SIMULATED-first como siempre: set curado de ~17 leads CO realistas por categoría, $0 sin keys. Real por categoría: investor_llc vía Colorado SOS (GRATIS, ya andaba); absentee/preforeclosure/high_equity vía ATTOM (ATTOM_API_KEY, stub key-gated); fsbo/expired/renter requieren feed licenciado (quedan SIMULATED).",
      },
      {
        en: "API: /discovery/search now takes `category` (instead of `sources`) + an optional `query` refine. BusinessOut/Lead.meta carry motivation/timeline/property_type/est_value.",
        es: "API: /discovery/search ahora toma `category` (en vez de `sources`) + `query` opcional de refine. BusinessOut/Lead.meta llevan motivation/timeline/property_type/est_value.",
      },
      {
        en: "Frontend: category chips (Sellers / Buyers) instead of source toggles, optional refine, and results show motivation + timeline + type + value. Visible DNC/TCPA compliance notice (the leads are prospects, not consented contacts). EN/ES i18n.",
        es: "Frontend: chips de categoría (Vendedores / Compradores) en vez de toggles de fuente, refine opcional, y los resultados muestran motivación + timeline + tipo + valor. Aviso de cumplimiento DNC/TCPA visible (los leads son prospectos, no contactos con consentimiento). i18n EN/ES.",
      },
      {
        en: "Tests updated to categories (simulated search per category, filtering, default to fsbo, cap).",
        es: "Tests actualizados a categorías (search simulado por categoría, filtrado, default a fsbo, cap).",
      },
    ],
  },
  {
    version: "0.14.4",
    date: "2026-05-27",
    title: {
      en: "Fix — show the real error in the UI (no more 'body stream already read')",
      es: "Fix — error real visible en la UI (no más 'body stream already read')",
    },
    changes: [
      {
        en: "The API client (`lib/api.ts`) read an error response body twice (`res.json()` then `res.text()` in the catch), which threw 'Failed to execute text on Response: body stream already read' and MASKED the real error (e.g. a backend 500 showed as that confusing message).",
        es: "El cliente API (`lib/api.ts`) leía el body de una respuesta de error dos veces (`res.json()` y luego `res.text()` en el catch), lo que tiraba 'Failed to execute text on Response: body stream already read' y TAPABA el error real (p.ej. un 500 del backend se mostraba como ese mensaje confuso).",
      },
      {
        en: "Fix: an `errorDetail()` helper that reads the body ONCE as text and then tries `JSON.parse` to extract the `detail`. Applied in `api()` and in `discoveryApi.upload()`.",
        es: "Fix: helper `errorDetail()` que lee el body UNA sola vez como texto y luego intenta `JSON.parse` para sacar el `detail`. Aplicado en `api()` y en `discoveryApi.upload()`.",
      },
      {
        en: "Context: the symptom appeared when the backend returned 500 because the ROG disk was at 100% and Postgres went into recovery mode (crash-loop on 'No space left on device'); space was freed (Docker build cache) and the DB recovered. This fix ensures next time you see the real error, not the double-read one.",
        es: "Contexto: el síntoma apareció cuando el backend devolvió 500 porque el disco del ROG estaba al 100% y Postgres quedó en recovery mode (crash-loop por 'No space left on device'); se liberó espacio (Docker build cache) y la base se recuperó. Este fix asegura que la próxima vez se vea el error real, no el de doble lectura.",
      },
    ],
  },
  {
    version: "0.14.3",
    date: "2026-05-27",
    title: {
      en: "Discovery — server-side enrichment (no longer depends on the browser)",
      es: "Discovery — enriquecimiento server-side (deja de depender del navegador)",
    },
    changes: [
      {
        en: "Problem: leads that went through the flow but stayed un-enriched. Cause: enrichment was only triggered by the FRONTEND loop over the just-CREATED leads — so leads imported before classification (v0.14.2), or skipped by dedupe on re-import, or if the user closed the tab, never got enriched (stayed score 0, no intent).",
        es: "Problema: leads que pasaban por el flujo pero quedaban sin enriquecer. Causa: el enriquecimiento solo lo disparaba el loop del FRONTEND sobre los leads recién CREADOS — así que leads importados antes de la clasificación (v0.14.2), o saltados por dedupe al re-importar, o si el usuario cerraba la pestaña, nunca se enriquecían (quedaban score 0, sin intent).",
      },
      {
        en: "Fix: a server-side enrichment worker. `enrich_pending_leads()` finds unclassified discovery leads (score 0) and enriches them; it runs as an in-process loop (`ENRICHMENT_ENABLED`, every 120s) like the follow-ups one, + a manual endpoint `POST /api/v1/discovery/enrich-pending`. Now enrichment does NOT depend on the browser: every discovery lead ends up classified even if the UI never touched it.",
        es: "Fix: worker server-side de enriquecimiento. `enrich_pending_leads()` busca leads de discovery sin clasificar (score 0) y los enriquece; corre como loop in-process (`ENRICHMENT_ENABLED`, cada 120s) igual que el de follow-ups, + endpoint manual `POST /api/v1/discovery/enrich-pending`. Ahora el enriquecimiento NO depende del navegador: todo lead de discovery termina clasificado aunque la UI no lo haya tocado.",
      },
      {
        en: "Retry-cap: `enrich_lead` counts attempts in `meta.enrichment.attempts`; the sweep gives up on a lead after 3 failures so it doesn't retry forever.",
        es: "Retry-cap: `enrich_lead` cuenta intentos en `meta.enrichment.attempts`; el sweep abandona un lead tras 3 fallos para no reintentar infinito.",
      },
      {
        en: "Backfill: on deploy, the worker (or the manual endpoint) classifies the old leads that were at score 0 / no intent.",
        es: "Backfill: al desplegar, el worker (o el endpoint manual) clasifica los leads viejos que estaban en score 0 / sin intent.",
      },
      {
        en: "The frontend loop stays as immediate feedback (progress bar); the server-side worker is the safety net. Tests +1 (sweep only touches unclassified discovery, respects the cap, doesn't touch conversation leads).",
        es: "El loop del frontend se mantiene como feedback inmediato (barra de progreso); el worker server-side es la red de seguridad. Tests +1 (sweep solo toca discovery sin clasificar, respeta el cap, no toca leads de conversación).",
      },
    ],
  },
  {
    version: "0.14.2",
    date: "2026-05-26",
    title: {
      en: "Discovery — imported leads now get classified (intent + score 🔥) like the rest",
      es: "Discovery — los leads importados ahora se clasifican (intent + score 🔥) como el resto",
    },
    changes: [
      {
        en: "Discovery leads appeared 'bare' in /leads (status new, no intent, score 0 ⚪) versus worked leads showing 🔥/qualified/buy. Now enrichment ALSO classifies and scores the lead, so it shows the same badges (IntentBadge + ScoreBadge with the little flame).",
        es: "Los leads de discovery aparecían 'pelados' en /leads (status new, sin intent, score 0 ⚪) frente a los leads trabajados que muestran 🔥/qualified/buy. Ahora el enriquecimiento TAMBIÉN clasifica y puntúa el lead, así muestra los mismos badges (IntentBadge + ScoreBadge con fueguito).",
      },
      {
        en: "The enrichment LLM now also returns `intent` (buy/rent/valuation/other — best-fit if the contact could be a client, else other) and `relevance` (0-10). enrich_lead sets `lead.intent` and computes `lead.score` + `score_breakdown` with a dedicated scoring for prospected leads (no conversation): partner_type (referral_partner 35 / prospect 32 / vendor 18 / competitor 6 / other 12) + relevance×2 + real contact (+25) + web (+10), mapped to hot≥67/warm≥34/cold with the same thresholds as scoring.py.",
        es: "El LLM de enriquecimiento ahora devuelve también `intent` (buy/rent/valuation/other — best-fit si el contacto pudiera ser cliente, sino other) y `relevance` (0-10). enrich_lead setea `lead.intent` y calcula `lead.score` + `score_breakdown` con un scoring propio para leads prospectados (sin conversación): partner_type (referral_partner 35 / prospect 32 / vendor 18 / competitor 6 / other 12) + relevance×2 + contacto real (+25) + web (+10), mapeado a tier hot≥67/warm≥34/cold con los mismos umbrales que scoring.py.",
      },
      {
        en: "Result: a referring mortgage broker (referral_partner) with contact and high relevance comes out 🔥 hot; a competitor with no contact comes out ⚪ cold — and the leads list ranks them by score alongside the rest.",
        es: "Resultado: un broker hipotecario que refiere (referral_partner) con contacto y alta relevancia sale 🔥 hot; un competidor sin contacto sale ⚪ cold — y la lista de leads los rankea por score junto a los demás.",
      },
      {
        en: "The status stays 'new' (it's honest: they're freshly brought-in, unworked leads). If enrichment fails, the lead is saved anyway unclassified (not lost).",
        es: "El status se mantiene en 'new' (es honesto: son leads recién traídos, sin trabajar). Si el enriquecimiento falla, el lead se guarda igual sin clasificar (no se pierde).",
      },
      {
        en: "Tests +3: _coerce of intent/relevance (normalizes + clamps), discovery_score (referral+contact+web+relevance→hot, other with nothing→cold), and the happy path now verifies enrich sets lead.intent=buy + score>0 + breakdown source=discovery_enrichment.",
        es: "Tests +3: _coerce de intent/relevance (normaliza + clampa), discovery_score (referral+contacto+web+relevancia→hot, other sin nada→cold), y el happy path ahora verifica que enrich setea lead.intent=buy + score>0 + breakdown source=discovery_enrichment.",
      },
    ],
  },
  {
    version: "0.14.1",
    date: "2026-05-26",
    title: {
      en: "Hotfix — widen leads.phone 32→254 (importing discovery gave 500)",
      es: "Hotfix — ensanchar leads.phone 32→254 (importar discovery daba 500)",
    },
    changes: [
      {
        en: "FIX: importing discovery leads with a long identifier (LinkedIn URLs, or the synthetic key `discovery:<source>:<slug>:<city>`) gave HTTP 500 `StringDataRightTruncationError`. Root cause: the `leads.phone` column was still VARCHAR(32) in the DB, even though the model declares String(254) since Phase 3 — the Phase 3 migration never actually widened the column (emails <32 chars worked by luck).",
        es: "FIX: importar leads de discovery con identificador largo (URLs de LinkedIn, o la clave sintética `discovery:<fuente>:<slug>:<ciudad>`) daba HTTP 500 `StringDataRightTruncationError`. Causa raíz: la columna `leads.phone` seguía siendo VARCHAR(32) en la base, aunque el modelo declara String(254) desde Phase 3 — la migración de Phase 3 nunca llegó a ensanchar la columna (los emails <32 chars funcionaban de casualidad).",
      },
      {
        en: "Alembic migration 007_phase12_widen_phone: `ALTER leads.phone TYPE VARCHAR(254)` to align the DB with the model. Safe widening operation (no data loss, keeps the unique index).",
        es: "Migración Alembic 007_phase12_widen_phone: `ALTER leads.phone TYPE VARCHAR(254)` para alinear la base con el modelo. Operación de ensanchado segura (sin pérdida de datos, mantiene el índice único).",
      },
      {
        en: "Without this, the v0.14.0 fix (importing leads with no contact) failed in production for most Colorado SOS/LinkedIn results.",
        es: "Sin esto, el fix de v0.14.0 (importar leads sin contacto) fallaba en producción para la mayoría de los resultados de Colorado SOS/LinkedIn.",
      },
    ],
  },
  {
    version: "0.14.0",
    date: "2026-05-26",
    title: {
      en: "Discovery fix — leads DO get saved + enrichment with progress bar",
      es: "Discovery fix — los leads SÍ se guardan + enriquecimiento con barra de progreso",
    },
    changes: [
      {
        en: "Critical FIX: clicking 'Import selected' didn't show the leads in /leads. Cause: the import used phone|email as the identifier and most sources (Colorado SOS, LinkedIn) carry neither phone nor email → ALL were silently skipped. Now the identifier cascades phone → email → website → stable synthetic key `discovery:<source>:<slug>:<city>`, so every named business is imported AND re-imports dedupe instead of duplicating.",
        es: "FIX crítico: al darle 'Importar seleccionados' los leads no aparecían en /leads. Causa: el import usaba phone|email como identificador y la mayoría de las fuentes (Colorado SOS, LinkedIn) no traen ni teléfono ni email → se saltaban TODOS silenciosamente. Ahora el identificador cae en cascada phone → email → website → clave sintética estable `discovery:<fuente>:<slug>:<ciudad>`, así cada negocio con nombre se importa Y los re-imports deduplican en vez de duplicar.",
      },
      {
        en: "The import now returns `lead_ids` (the created IDs) so they can be enriched.",
        es: "El import ahora devuelve `lead_ids` (los IDs creados) para poder enriquecerlos.",
      },
      {
        en: "NEW lead enrichment (`services/enrichment.py` + `POST /api/v1/discovery/enrich/{lead_id}`): for each imported lead the LLM (Kimi/MiniMax json_mode) infers a normalized business type, partner_type (referral_partner/vendor/prospect/competitor), a summary, an outreach angle and tags — saved in `meta.enrichment`. Marks `contact_missing` when there's no real phone/email. Graceful: if the LLM fails or returns invalid JSON, `status=failed` and the lead is never lost.",
        es: "NUEVO enriquecimiento de leads (`services/enrichment.py` + `POST /api/v1/discovery/enrich/{lead_id}`): por cada lead importado el LLM (Kimi/MiniMax json_mode) infiere tipo de negocio normalizado, partner_type (referral_partner/vendor/prospect/competitor), un resumen, un ángulo de outreach y tags — guardado en `meta.enrichment`. Marca `contact_missing` cuando no hay teléfono/email real. Graceful: si el LLM falla o devuelve JSON inválido, `status=failed` y nunca se pierde el lead.",
      },
      {
        en: "Real progress bar: after importing, the frontend enriches lead by lead showing an X/N bar that visibly advances, and at the end shows a summary + a 'View in Leads' link. Before there was no processing signal.",
        es: "Barra de progreso real: tras importar, el frontend enriquece lead por lead mostrando una barra X/N que avanza visiblemente, y al terminar muestra un resumen + link 'Ver en Leads'. Antes no había ninguna señal de procesamiento.",
      },
      {
        en: "The /leads table now shows contactless discovery leads cleanly (synthetic identifier → '—' with a magnifier icon; URLs like linkedin.com/in/… with a globe icon) instead of the raw slug.",
        es: "La tabla de /leads ahora muestra los leads de discovery sin contacto de forma limpia (identificador sintético → '—' con icono de lupa; URLs como linkedin.com/in/… con icono de globo) en vez del slug crudo.",
      },
      {
        en: "Tests +9: lead_identifier (cascade + deterministic synthetic), contactless import NOW creates + dedupes + returns lead_ids, _coerce (invalid partner_type→other, tags string→list + cap 4), enrich_lead (happy path persists meta + contact_missing, graceful on LLM down and invalid JSON).",
        es: "Tests +9: lead_identifier (cascada + sintético determinista), import sin contacto AHORA crea + deduplica + devuelve lead_ids, _coerce (partner_type inválido→other, tags string→list + cap 4), enrich_lead (happy path persiste meta + contact_missing, graceful ante LLM caído y JSON inválido).",
      },
    ],
  },
  {
    version: "0.13.0",
    date: "2026-05-26",
    title: {
      en: "Phase 12 — Discovery: lead search (4 sources) + import from any file",
      es: "Phase 12 — Discovery: búsqueda de leads (4 fuentes) + importar desde cualquier archivo",
    },
    changes: [
      {
        en: "New Discovery tab (like the sales platform's): find new business leads from 4 sources — Google Maps, Yelp, LinkedIn and Colorado SOS — plus a section to import your existing database from ANY file (PDF, JPG/PNG, TXT, CSV, XLSX, HTML).",
        es: "Nueva pestaña Discovery (como la del sales platform): buscá nuevos leads de negocios en 4 fuentes — Google Maps, Yelp, LinkedIn y Colorado SOS — y sumá una sección para importar tu base de datos existente desde CUALQUIER archivo (PDF, JPG/PNG, TXT, CSV, XLSX, HTML).",
      },
      {
        en: "Preview-and-select flow: searching/uploading returns transient results (not persisted); the dashboard shows a checklist with select-all and you choose which to import → they're created as Leads (status new, meta.source). Dedupe by identifier (phone, else email) against existing leads.",
        es: "Flujo preview-and-select: buscar/subir devuelve resultados transitorios (no se persisten); el dashboard muestra un checklist con select-all y vos elegís cuáles importar → se crean como Leads (status new, meta.source). Dedupe por identificador (teléfono, sino email) contra leads existentes.",
      },
      {
        en: "services/discovery.py (ported and adapted from the Eko AI Main sales platform, Paperclip dropped): SIMULATED-first pattern like listings.py. Default DISCOVERY_SIMULATED=true → curated set of plausible-real CO businesses (no keys). Real adapters per source: Colorado SOS (public Socrata, FREE no key), Yelp Fusion, Google Maps (Outscraper), LinkedIn (SerpApi) — each degrades to [] without its key.",
        es: "services/discovery.py (portado y adaptado del sales platform Eko AI Main, drop de Paperclip): patrón SIMULATED-first como listings.py. Default DISCOVERY_SIMULATED=true → set curado de negocios CO reales-plausibles (sin keys). Adapters reales por fuente: Colorado SOS (Socrata público, GRATIS sin key), Yelp Fusion, Google Maps (Outscraper), LinkedIn (SerpApi) — cada uno degrada a [] sin su key.",
      },
      {
        en: "services/file_import.py — 'any format' extraction: PDF (pypdf), XLSX (openpyxl), JPG/PNG images via OCR (pytesseract + tesseract-ocr in the Dockerfile), CSV/TXT/HTML (stdlib + tag strip). Then extract_leads passes the text through the LLM (json_mode) to pull contacts as a JSON array, with graceful degradation (bad output → [], never crashes).",
        es: "services/file_import.py — extracción 'cualquier formato': PDF (pypdf), XLSX (openpyxl), imágenes JPG/PNG vía OCR (pytesseract + tesseract-ocr en el Dockerfile), CSV/TXT/HTML (stdlib + strip de tags). Luego extract_leads pasa el texto por el LLM (json_mode) para sacar contactos como array JSON, con degradación graceful (output malo → [], nunca crashea).",
      },
      {
        en: "Protected API under /api/v1/discovery: POST /search (query/city/state/sources/max_results), POST /upload (multipart, cap FILE_IMPORT_MAX_MB=25), POST /import (creates the chosen leads). Frontend: /discovery (DiscoveryPanel with 4 source chips + reusable ResultsList + FileImport with drag-drop). Discovery link in the Nav (Search icon).",
        es: "API protegida bajo /api/v1/discovery: POST /search (query/city/state/sources/max_results), POST /upload (multipart, cap FILE_IMPORT_MAX_MB=25), POST /import (crea los leads elegidos). Frontend: /discovery (DiscoveryPanel con 4 chips de fuente + ResultsList reutilizable + FileImport con drag-drop). Link Discovery en el Nav (icono Search).",
      },
      {
        en: "config + .env.example + compose: DISCOVERY_SIMULATED + YELP_API_KEY/OUTSCRAPER_API_KEY/SERPAPI_API_KEY (reuse the sales platform keys) + FILE_IMPORT_MAX_MB. requirements: pypdf/openpyxl/pillow/pytesseract. docs/setup-discovery.md (which source needs which key; Colorado SOS free; flip DISCOVERY_SIMULATED=false).",
        es: "config + .env.example + compose: DISCOVERY_SIMULATED + YELP_API_KEY/OUTSCRAPER_API_KEY/SERPAPI_API_KEY (se reusan las keys del sales platform) + FILE_IMPORT_MAX_MB. requirements: pypdf/openpyxl/pillow/pytesseract. docs/setup-discovery.md (qué fuente necesita qué key; Colorado SOS gratis; flip DISCOVERY_SIMULATED=false).",
      },
      {
        en: "Tests +13 (total 145): test_discovery.py (6 — simulated search returns businesses, filter by source, cap max_results, sanitize_email, import creates+dedupes, import without identifier skip) + test_file_import.py (7 — extract_text plaintext/csv/html-strip/empty, extract_leads parses JSON array, tolerates prose, bad output→[], empty text doesn't call the LLM).",
        es: "Tests +13 (total 145): test_discovery.py (6 — búsqueda simulada devuelve negocios, filtro por fuente, cap max_results, sanitize_email, import crea+dedupe, import sin identificador skip) + test_file_import.py (7 — extract_text plaintext/csv/html-strip/empty, extract_leads parsea JSON array, tolera prosa, output malo→[], texto vacío no llama LLM).",
      },
    ],
  },
  {
    version: "0.12.0",
    date: "2026-05-26",
    title: {
      en: "Phase 11 — Hardening for 1st client: dashboard auth + analytics",
      es: "Phase 11 — Hardening para 1er cliente: auth del dashboard + analíticas",
    },
    changes: [
      {
        en: "Dashboard login (one office = one shared password): /login page + AuthGuard that redirects if the session is missing. HMAC-signed session token (httpOnly cookie, no new dependency). Logout button in the Nav.",
        es: "Login del dashboard (una oficina = un password compartido): página /login + AuthGuard que redirige si la sesión falta. Token de sesión firmado con HMAC (cookie httpOnly, sin dependencia nueva). Botón de salir en el Nav.",
      },
      {
        en: "Gate via `AUTH_ENABLED`: the data API (leads/conversations/visits/settings/properties/analytics) requires login when on; webhooks + health stay open. Default OFF (dev + public demo open); the installer turns it on with a password. WARN at startup if APP_ENV=production and AUTH_ENABLED=false.",
        es: "Gate por `AUTH_ENABLED`: el data API (leads/conversations/visits/settings/properties/analytics) requiere login cuando está activo; webhooks + health quedan abiertos. Default OFF (dev + demo público abiertos); el instalador lo activa con un password. WARN al startup si APP_ENV=production y AUTH_ENABLED=false.",
      },
      {
        en: "/analytics page: funnel by status, conversion rate, leads by channel, by score tier (🔥/🟡/⚪), average first-response time, and new leads per day (14d). GET /api/v1/analytics endpoint (read-only). No charts library (div bars).",
        es: "Página /analytics: funnel por status, tasa de conversión, leads por canal, por tier de score (🔥/🟡/⚪), tiempo de primera respuesta promedio, y nuevos leads por día (14d). Endpoint GET /api/v1/analytics (solo lectura). Sin librería de charts (barras div).",
      },
      {
        en: "config + .env.example + compose: AUTH_ENABLED/DASHBOARD_PASSWORD/AUTH_SECRET/AUTH_TTL_HOURS. The installer (scripts/install.sh) asks for the dashboard password and turns on auth + generates AUTH_SECRET.",
        es: "config + .env.example + compose: AUTH_ENABLED/DASHBOARD_PASSWORD/AUTH_SECRET/AUTH_TTL_HOURS. El instalador (scripts/install.sh) pregunta el password del dashboard y activa auth + genera AUTH_SECRET.",
      },
      {
        en: "EN/ES i18n for login + analytics; Analytics link in the Nav.",
        es: "i18n EN/ES para login + analytics; link Analytics en el Nav.",
      },
      {
        en: "Tests +6 (total 132): auth service (password/token/tamper/expiry) + gate (open if disabled, 401/login/cookie if enabled) + analytics envelope.",
        es: "Tests +6 (total 132): auth service (password/token/tamper/expiry) + gate (abierto si disabled, 401/login/cookie si enabled) + envelope de analytics.",
      },
      {
        en: "Voice (VAPI/Retell) renumbered to Phase 12.",
        es: "Voz (VAPI/Retell) renumerado a Phase 12.",
      },
    ],
  },
  {
    version: "0.11.0",
    date: "2026-05-26",
    title: {
      en: "Phase 10 — Autonomous nurture + the agent offers listings in the conversation",
      es: "Phase 10 — Nurture autónomo + el agente ofrece listings en la conversación",
    },
    changes: [
      {
        en: "Autonomous post-visit follow-up: booking a visit enqueues a reminder 24h before + a post-visit sequence (24h 'how did it go?', 72h nudge if no reply, 7d 'new similar ones'). Bilingual messages sent as the AI agent on the lead's channel.",
        es: "Seguimiento autónomo post-visita: al agendar una visita se encola un recordatorio 24h antes + secuencia post-visita (24h '¿qué te pareció?', 72h nudge si no respondió, 7d 'nuevas similares'). Mensajes bilingües enviados como el agente IA por el canal del lead.",
      },
      {
        en: "FollowUp model + Alembic 006 (lead/visit/kind/status/scheduled_for, UNIQUE visit+kind → idempotent enqueue). services/followups.py: enqueue_for_visit + process_due_followups (skips if human_takeover, visit cancelled, or the 72h if the lead already replied after the visit).",
        es: "Modelo FollowUp + Alembic 006 (lead/visit/kind/status/scheduled_for, UNIQUE visit+kind → enqueue idempotente). services/followups.py: enqueue_for_visit + process_due_followups (se salta si human_takeover, visita cancelada, o el 72h si el lead ya respondió tras la visita).",
      },
      {
        en: "In-process worker (asyncio loop in main.py, FOLLOWUPS_ENABLED + FOLLOWUPS_INTERVAL_SECONDS) that processes the due ones; scripts/run_followups.py for cron. Booking a visit enqueues the sequence.",
        es: "Worker in-process (loop asyncio en main.py, FOLLOWUPS_ENABLED + FOLLOWUPS_INTERVAL_SECONDS) que procesa los vencidos; scripts/run_followups.py para cron. El booking de visita encola la secuencia.",
      },
      {
        en: "The agent now OFFERS listings in the conversation: if the lead is buy/rent and has a zone, the orchestrator injects the REAL matched listings into the system prompt (only those, no inventing) and the LLM offers them naturally. Closes the Phase 7 loop (matching was dashboard-only before).",
        es: "El agente ahora OFRECE listings en la conversación: si el lead es buy/rent y tiene zona, el orquestador inyecta los listings emparejados REALES en el system prompt (solo esos, sin inventar) y el LLM los ofrece naturalmente. Cierra el loop de Phase 7 (antes el matching era solo dashboard).",
      },
      {
        en: "Fix: the matcher mis-coerced the budget (classifier float * Decimal → silent crash); normalized with Decimal(str()). Without this the injection failed live.",
        es: "Fix: el matcher coercía mal el presupuesto (float del classifier * Decimal → crash silencioso); normalizado con Decimal(str()). Sin esto la inyección fallaba en vivo.",
      },
      {
        en: "Tests +6 (total 126): followups (enqueue sequence + idempotent, past-visit no reminder, sends due, human_takeover skip, cancelled doesn't enqueue) + agent receives real listings in the system prompt.",
        es: "Tests +6 (total 126): followups (enqueue secuencia + idempotente, past-visit sin reminder, envía vencido, human_takeover skip, cancelada no encola) + agente recibe listings reales en el system prompt.",
      },
      {
        en: "Voice (VAPI/Retell) renumbered to Phase 11.",
        es: "Voz (VAPI/Retell) renumerado a Phase 11.",
      },
    ],
  },
  {
    version: "0.10.0",
    date: "2026-05-26",
    title: {
      en: "Multilingual dashboard (EN default + ES) with a language selector",
      es: "Dashboard multilingüe (EN default + ES) con selector de idioma",
    },
    changes: [
      {
        en: "The dashboard is now multilingual: English by default, Spanish as the second option, with a language selector (globe + EN/ES) in the Nav, visible on ALL pages.",
        es: "El dashboard ahora es multilingüe: inglés por defecto, español como segunda opción, con un selector de idioma (globo + EN/ES) en el Nav, visible en TODAS las páginas.",
      },
      {
        en: "lib/i18n.tsx: client LanguageProvider + useI18n hook + full EN/ES dictionaries. The choice persists to localStorage and syncs <html lang>. t(key) with fallback to EN and to the key itself.",
        es: "lib/i18n.tsx: LanguageProvider client + hook useI18n + diccionarios completos EN/ES. La elección persiste en localStorage y sincroniza <html lang>. t(key) con fallback a EN y a la propia key.",
      },
      {
        en: "All UI strings go through t(): Nav, pages (leads/properties/settings/detail), badges (status/intent/score/visit), leads table and detail, composer, suggestions, matches, visits, booking, properties, settings, takeover, messages.",
        es: "Todos los strings de UI pasan por t(): Nav, páginas (leads/propiedades/settings/detalle), badges (status/intent/score/visit), tabla y detalle de leads, composer, sugerencias, matches, visitas, booking, propiedades, settings, takeover, mensajes.",
      },
      {
        en: "Locale-aware formatters: relativeTime/exactTime/formatBudget (USD, en/es) + visit/booking dates per the active language.",
        es: "Formatters locale-aware: relativeTime/exactTime/formatBudget (USD, en/es) + fechas de visitas/booking según el idioma activo.",
      },
      {
        en: "Client PageHeader for the titles; the lead detail page is client. /about landing with refreshed copy (MLS matching).",
        es: "PageHeader client para los títulos; la página de detalle de lead es client. Landing /about con copy refrescado (MLS matching).",
      },
      {
        en: "English default aligned with the USA pivot; the backend agent already replied in the lead's language (Phase 3) — this also makes the realtor's interface bilingual.",
        es: "Default English alineado con el pivote USA; el agente backend ya respondía en el idioma del lead (Phase 3) — esto hace bilingüe también la interfaz del realtor.",
      },
    ],
  },
  {
    version: "0.9.1",
    date: "2026-05-26",
    title: {
      en: "SMS hardening — A2P MessagingServiceSid + delivery status callbacks",
      es: "SMS hardening — A2P MessagingServiceSid + delivery status callbacks",
    },
    changes: [
      {
        en: "After reading Twilio's official docs, two production improvements to the SMS channel: (1) sending via MessagingServiceSid for A2P 10DLC, (2) real delivery tracking via StatusCallback.",
        es: "Tras leer la doc oficial de Twilio, dos mejoras de producción del canal SMS: (1) envío vía MessagingServiceSid para A2P 10DLC, (2) tracking de entrega real vía StatusCallback.",
      },
      {
        en: "send_sms: if TWILIO_MESSAGING_SERVICE_SID is set, it sends with MessagingServiceSid (uses the registered A2P campaign/pool) instead of the raw From — recommended by Twilio for US delivery. Fallback to TWILIO_PHONE_NUMBER.",
        es: "send_sms: si TWILIO_MESSAGING_SERVICE_SID está seteado, envía con MessagingServiceSid (usa la campaña/pool A2P registrado) en vez del From crudo — recomendado por Twilio para entrega US. Fallback a TWILIO_PHONE_NUMBER.",
      },
      {
        en: "StatusCallback: new endpoint POST /api/v1/webhooks/sms/status. If TWILIO_STATUS_CALLBACK_URL is set, send_sms asks Twilio to post updates (sent→delivered/undelivered/failed + ErrorCode). The backend reflects the final state on the Message → the dashboard shows real delivery (and logs carrier errors like 30034 = A2P unregistered). twilio_status_to_delivery mapper.",
        es: "StatusCallback: nuevo endpoint POST /api/v1/webhooks/sms/status. Si TWILIO_STATUS_CALLBACK_URL está seteado, send_sms pide a Twilio que postee actualizaciones (sent→delivered/undelivered/failed + ErrorCode). El backend refleja el estado final en el Message → el dashboard muestra entrega real (y loguea errores de carrier como 30034 = A2P sin registrar). Mapper twilio_status_to_delivery.",
      },
      {
        en: "config.py + .env.example + compose: TWILIO_MESSAGING_SERVICE_SID + TWILIO_STATUS_CALLBACK_URL.",
        es: "config.py + .env.example + compose: TWILIO_MESSAGING_SERVICE_SID + TWILIO_STATUS_CALLBACK_URL.",
      },
      {
        en: "docs/setup-twilio.md expanded: A2P 10DLC registration (Sole Proprietor vs Standard), the Messaging Service webhook gotcha (overrides the number's), and STOP/HELP opt-out (Twilio handles it by default).",
        es: "docs/setup-twilio.md ampliado: registro A2P 10DLC (Sole Proprietor vs Standard), gotcha del webhook del Messaging Service (anula el del número), y opt-out STOP/HELP (Twilio lo maneja por default).",
      },
      {
        en: "Inbound webhook: cleaner signature-failure log (without the temporary verbose diagnostic).",
        es: "Webhook inbound: log de fallo de firma más limpio (sin el diagnóstico verbose temporal).",
      },
      {
        en: "Tests +4 (total 120): status mapper (1) + status callback e2e (delivered, undelivered/30034→failed, unknown sid = no-op).",
        es: "Tests +4 (total 120): mapper de estado (1) + status callback e2e (delivered, undelivered/30034→failed, sid desconocido = no-op).",
      },
    ],
  },
  {
    version: "0.9.0",
    date: "2026-05-26",
    title: {
      en: "Phase 9 — SMS channel (Twilio)",
      es: "Phase 9 — Canal SMS (Twilio)",
    },
    changes: [
      {
        en: "Third channel: SMS via Twilio Programmable Messaging, on the same multichannel architecture from Phase 3 (ParsedMessage + dispatcher + channel='sms'). The agent captures, classifies, scores and replies just like WhatsApp/Email.",
        es: "Tercer canal: SMS vía Twilio Programmable Messaging, sobre la misma arquitectura multicanal de Phase 3 (ParsedMessage + dispatcher + channel='sms'). El agente captura, clasifica, scorea y responde igual que WhatsApp/Email.",
      },
      {
        en: "services/sms.py: send_sms (SIMULATED logs / real POST to Twilio's REST API with basic auth), verify_twilio_signature (HMAC-SHA1 over URL + sorted POST params, keyed by the auth token), parse_inbound_sms(form)->ParsedMessage.",
        es: "services/sms.py: send_sms (SIMULATED loguea / real POST a la REST API de Twilio con basic auth), verify_twilio_signature (HMAC-SHA1 sobre URL + params POST ordenados, keyed por el auth token), parse_inbound_sms(form)->ParsedMessage.",
      },
      {
        en: "Webhook POST /api/v1/webhooks/sms: parses Twilio's form, validates X-Twilio-Signature (except SIMULATED), delegates to the orchestrator, returns empty TwiML (the reply goes async via REST). The signature URL is TWILIO_WEBHOOK_URL or rebuilt from forwarded headers (proxy/tunnel).",
        es: "Webhook POST /api/v1/webhooks/sms: parsea el form de Twilio, valida X-Twilio-Signature (salvo SIMULATED), delega al orquestador, responde TwiML vacío (la respuesta sale async vía REST). La URL para la firma es TWILIO_WEBHOOK_URL o se reconstruye de los forwarded headers (proxy/tunnel).",
      },
      {
        en: "Idempotency via UNIQUE messages.external_id (MessageSid) — Twilio retries don't duplicate.",
        es: "Idempotencia vía UNIQUE messages.external_id (MessageSid) — los reintentos de Twilio no duplican.",
      },
      {
        en: "config.py + .env.example + compose: SMS_SIMULATED (default true), TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER/WEBHOOK_URL. scripts/simulate_inbound_sms.py for smoke testing.",
        es: "config.py + .env.example + compose: SMS_SIMULATED (default true), TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER/WEBHOOK_URL. scripts/simulate_inbound_sms.py para smoke testing.",
      },
      {
        en: "docs/setup-twilio.md: account + number + webhook + signature + cost/security notes.",
        es: "docs/setup-twilio.md: cuenta + número + webhook + firma + notas de costo/seguridad.",
      },
      {
        en: "Tests +9 (total 116): test_sms_service.py (7 — valid/tampered/wrong-token/missing signature, parse ok/missing, send simulated) + test_sms_webhook_e2e.py (2 — inbound creates lead+conversation channel=sms, idempotency on retry).",
        es: "Tests +9 (total 116): test_sms_service.py (7 — firma válida/tampered/wrong-token/missing, parse ok/missing, send simulated) + test_sms_webhook_e2e.py (2 — inbound crea lead+conversation channel=sms, idempotencia en reintento).",
      },
      {
        en: "Voice (VAPI/Retell) still deferred as Phase 10 until a provider account exists.",
        es: "Voz (VAPI/Retell) sigue diferida como Phase 10 hasta tener cuenta de proveedor.",
      },
    ],
  },
  {
    version: "0.8.0",
    date: "2026-05-26",
    title: {
      en: "Phase 8 — Lead intelligence (scoring + prioritization + digest)",
      es: "Phase 8 — Lead intelligence (scoring + priorización + digest)",
    },
    changes: [
      {
        en: "Deterministic, explainable 0-100 lead scoring: services/scoring.py scores signals the pipeline already produced (LLM intent + extracted entities + engagement + recency + visit) WITHOUT extra LLM calls per lead, so the list ranks fast and cheap. Components: intent 20 · budget 15 · engagement 15 · urgency 12 · zone 10 · recency 10 · visit 10 · property_type 8. Status gate: WON/LOST→0, PAUSED→half.",
        es: "Lead scoring 0-100 determinista y explicable: services/scoring.py puntúa señales que el pipeline ya produjo (intent LLM + entidades extraídas + engagement + recency + visita) SIN llamadas LLM extra por lead, así la lista rankea rápido y barato. Componentes: intent 20 · budget 15 · engagement 15 · urgency 12 · zone 10 · recency 10 · visit 10 · property_type 8. Status gate: WON/LOST→0, PAUSED→mitad.",
      },
      {
        en: "leads.score (indexed Int) + score_breakdown (JSON with per-component breakdown + tier) columns. Alembic 005. The orchestrator recomputes the score after each inbound turn; POST /leads/rescore-all for backfill.",
        es: "Columnas leads.score (Int indexado) + score_breakdown (JSON con desglose por componente + tier). Alembic 005. El orquestador recomputa el score tras cada turno inbound; POST /leads/rescore-all para backfill.",
      },
      {
        en: "Tiers 🔥 hot (≥67) / 🟡 warm (≥34) / ⚪ cold. ScoreBadge on each leads-table row; the list now sorts by score by default (sort=score|recent).",
        es: "Tiers 🔥 hot (≥67) / 🟡 warm (≥34) / ⚪ cold. ScoreBadge en cada fila de la tabla de leads; la lista ahora ordena por score por defecto (sort=score|recent).",
      },
      {
        en: "GET /leads/digest — top hot/active leads (excludes won/lost/paused, score>0) → 'Hot leads — who to call first' panel atop /leads. scripts/daily_digest.py for cron (prints the digest, pipe-able to email/Telegram).",
        es: "GET /leads/digest — top leads calientes/activos (excluye won/lost/paused, score>0) → panel 'Leads calientes — a quién llamar primero' arriba de /leads. scripts/daily_digest.py para cron (imprime el digest, pipe-able a email/Telegram).",
      },
      {
        en: "Lead detail shows the ScoreBadge with a label in the header. score + score_breakdown exposed in LeadOut.",
        es: "Lead detail muestra el ScoreBadge con label en el header. score + score_breakdown expuestos en LeadOut.",
      },
      {
        en: "Tests +11 (total 107): test_scoring.py (8 — empty lead 0, fully-qualified=100 hot, won/lost zeroed, paused halved, engagement scales, recency decays, clamp 0-100, tier thresholds) + test_lead_digest.py (3 — rescore+digest ranks and excludes closed, list default sort=score, LeadOut has score).",
        es: "Tests +11 (total 107): test_scoring.py (8 — lead vacío 0, fully-qualified=100 hot, won/lost zeroed, paused halved, engagement escala, recency decae, clamp 0-100, umbrales de tier) + test_lead_digest.py (3 — rescore+digest rankea y excluye cerrados, list default sort=score, LeadOut tiene score).",
      },
      {
        en: "No external accounts. SMS (Twilio) renumbered to Phase 9, Voice (VAPI/Retell) to Phase 10 — still deferred until accounts exist.",
        es: "Sin cuentas externas. SMS (Twilio) renumerado a Phase 9, Voz (VAPI/Retell) a Phase 10 — siguen diferidas hasta tener cuentas.",
      },
    ],
  },
  {
    version: "0.7.0",
    date: "2026-05-25",
    title: {
      en: "Phase 7 — MLS/IDX listings (RESO) + per-lead property matching",
      es: "Phase 7 — MLS/IDX listings (RESO) + per-lead property matching",
    },
    changes: [
      {
        en: "Property model reworked for the USA: source enum reso/idx/mls/manual + status enum (active/pending/sold/off_market), bedrooms/bathrooms (half-baths 2.5)/sqft/property_type/address/city/state/zip/zone/lat-lng/photos/description/listed_at. Alembic 004 drops+recreates the EU placeholder table (it was empty).",
        es: "Property model reworked para USA: source enum reso/idx/mls/manual + status enum (active/pending/sold/off_market), bedrooms/bathrooms (half-baths 2.5)/sqft/property_type/address/city/state/zip/zone/lat-lng/photos/description/listed_at. Alembic 004 dropea+recrea la tabla placeholder EU (estaba vacía).",
      },
      {
        en: "services/listings.py: fetch_listings (SIMULATED = curated set of 9 Miami listings / real = RESO Web API OData with RESO_BASE_URL+RESO_ACCESS_TOKEN), sync_listings (idempotent upsert by source+external_id), match_properties_for_lead (intent gate rent/sale + zone + budget ±10% + type).",
        es: "services/listings.py: fetch_listings (SIMULATED = set curado de 9 listings Miami / real = RESO Web API OData con RESO_BASE_URL+RESO_ACCESS_TOKEN), sync_listings (upsert idempotente por source+external_id), match_properties_for_lead (gate de intención rent/sale + zona + presupuesto ±10% + tipo).",
      },
      {
        en: "Endpoints: GET /properties (status/source/city/zone/type/min-max price filters + pagination), POST /properties/sync (ingest), GET /properties/{id}, GET /leads/{id}/matches (listings that fit the lead).",
        es: "Endpoints: GET /properties (filtros status/source/city/zone/type/min-max price + paginado), POST /properties/sync (ingest), GET /properties/{id}, GET /leads/{id}/matches (listings que encajan con el lead).",
      },
      {
        en: "Frontend: /properties page with a grid of PropertyCard + zone/price filters + a 'Sync MLS' button. MatchesSection in the lead detail shows 'Suggested properties' with a 'Send to lead' button (sends a formatted blurb via the composer). 'Properties' link in the Nav.",
        es: "Frontend: página /properties con grid de PropertyCard + filtros zona/precio + botón 'Sincronizar MLS'. MatchesSection en el detalle del lead muestra 'Propiedades sugeridas' con botón 'Enviar al lead' (manda blurb formateado vía composer). Link 'Propiedades' en el Nav.",
      },
      {
        en: "Listings SIMULATED by default (LISTINGS_SIMULATED=true) — the dashboard + matching work without an MLS account; production via docs/setup-mls.md. The demo set's zones match the demo leads (Brickell/Coral Gables/Doral/Wynwood/Edgewater/Little Havana).",
        es: "Listings SIMULATED por default (LISTINGS_SIMULATED=true) — el dashboard + matching funcionan sin cuenta MLS; producción vía docs/setup-mls.md. Las zonas del set demo coinciden con los leads demo (Brickell/Coral Gables/Doral/Wynwood/Edgewater/Little Havana).",
      },
      {
        en: "scripts/sync_listings.py ingest CLI (idempotent, cron-friendly). config.py + .env.example + docker-compose env (LISTINGS_SIMULATED/PROVIDER/RESO_*).",
        es: "scripts/sync_listings.py ingest CLI (idempotente, cron-friendly). config.py + .env.example + docker-compose env (LISTINGS_SIMULATED/PROVIDER/RESO_*).",
      },
      {
        en: "Tests +12 (total 96): test_listings_service.py (5 — simulated fetch, sale+rent, city filter, non-existent city empty, limit) + test_properties_api.py (7 — idempotent sync, list+filters, price filter, get 404, matches 404, buy-lead Brickell sale-only, rent-lead rentals-only).",
        es: "Tests +12 (total 96): test_listings_service.py (5 — fetch simulado, sale+rent, filtro ciudad, ciudad inexistente vacía, limit) + test_properties_api.py (7 — sync idempotente, list+filtros, filtro precio, get 404, matches 404, buy-lead Brickell sale-only, rent-lead solo rentals).",
      },
    ],
  },
  {
    version: "0.6.0",
    date: "2026-05-25",
    title: {
      en: "Phase 6 — Single-customer installer + branding panel + public demo",
      es: "Phase 6 — Single-customer installer + branding panel + public demo",
    },
    changes: [
      {
        en: "Settings API: GET/PUT /api/v1/settings over the AgentSettings singleton (auto-created with defaults). PUT does a partial update with languages normalization/dedupe (lowercase, no blanks). Each office can brand its own instance.",
        es: "Settings API: GET/PUT /api/v1/settings sobre el singleton AgentSettings (auto-creado con defaults). PUT hace partial update con normalización/dedupe de languages (lowercase, sin vacíos). Cada oficina puede brandear su propia instancia.",
      },
      {
        en: "Frontend /settings — branding panel: agency name + phone, agent persona (system prompt), greeting, languages (es/en/pt/fr chips), business hours (per day, open/close or closed). 'Settings' link in the Nav. Changes apply to replies immediately.",
        es: "Frontend /settings — panel de branding: nombre + teléfono de la agencia, persona del agente (system prompt), saludo, idiomas (chips es/en/pt/fr), horario de atención (por día, open/close o cerrado). Link 'Configuración' en el Nav. Cambios aplican de inmediato a las respuestas.",
      },
      {
        en: "scripts/install.sh — interactive single-customer installer: checks prereqs (docker/compose/daemon), generates .env with strong random secrets (POSTGRES_PASSWORD, WHATSAPP_VERIFY_TOKEN) mode 600 never printed, build+up, waits for health, alembic upgrade head, sets branding via API. Channels stay SIMULATED except explicit opt-in. --no-prompt for provisioning.",
        es: "scripts/install.sh — instalador single-customer interactivo: chequea prereqs (docker/compose/daemon), genera .env con secretos aleatorios fuertes (POSTGRES_PASSWORD, WHATSAPP_VERIFY_TOKEN) mode 600 nunca impresos, build+up, espera health, alembic upgrade head, fija branding vía API. Canales quedan SIMULATED salvo opt-in explícito. --no-prompt para provisioning.",
      },
      {
        en: "backend/scripts/seed_demo.py — idempotent demo dataset (Sunset Realty Group, Miami): 6 bilingual EN/ES leads + realistic conversations + 2 visits (scheduled/completed). Marks meta.demo=true; --reset only deletes demo rows; --keep-settings preserves branding. So inmo-demo.ekoaiautomation.com looks alive.",
        es: "backend/scripts/seed_demo.py — dataset demo idempotente (Sunset Realty Group, Miami): 6 leads bilingües EN/ES + conversaciones realistas + 2 visitas (scheduled/completed). Marca meta.demo=true; --reset borra solo filas demo; --keep-settings preserva branding. Para que inmo-demo.ekoaiautomation.com luzca vivo.",
      },
      {
        en: "deploy/cloudflared/config.example.yml + docs/setup-demo.md — DEDICATED tunnel for inmo-demo.ekoaiautomation.com (isolated from the sales platform's eko-landing tunnel). Security model: all channels SIMULATED (a visitor never triggers a real send), seed data (no real PII), optional Cloudflare Access.",
        es: "deploy/cloudflared/config.example.yml + docs/setup-demo.md — tunnel DEDICADO para inmo-demo.ekoaiautomation.com (aislado del tunnel eko-landing de la sales platform). Modelo de seguridad: todos los canales SIMULATED (un visitante nunca dispara un envío real), datos seed (sin PII real), opcional Cloudflare Access.",
      },
      {
        en: "docs/install.md — full single-office install guide + channel enabling (WhatsApp/Resend/Cal.com) + upgrade. No GPU (cloud LLM Kimi+MiniMax).",
        es: "docs/install.md — guía completa de instalación single-office + enable de canales (WhatsApp/Resend/Cal.com) + upgrade. Sin GPU (LLM en la nube Kimi+MiniMax).",
      },
      {
        en: "CI green for the first time since Phase 1: backend adds a Postgres service + alembic upgrade head (DB tests now actually run) + ruff config ignores 3 rules that clash with intentional idioms (B008 FastAPI Depends, UP042 str-Enum, UP037 SQLAlchemy forward-refs) + auto-fixes the rest. Frontend removes npm cache (no package-lock.json → aborted the job).",
        es: "CI verde por primera vez desde Phase 1: backend agrega servicio Postgres + alembic upgrade head (los tests con DB ahora corren de verdad) + ruff config ignora 3 reglas que chocan con idioms intencionales (B008 FastAPI Depends, UP042 str-Enum, UP037 SQLAlchemy forward-refs) + auto-fix del resto. Frontend quita cache npm (no había package-lock.json → abortaba el job).",
      },
      {
        en: "Tests +7 (total 84): test_settings_api.py (GET auto-create defaults, PUT update + persists, partial update doesn't touch other fields, languages normalize/dedupe, empty body 400, unknown field 422, empty languages 422). test_models singleton made robust (doesn't couple agency_name to a fixed value).",
        es: "Tests +7 (total 84): test_settings_api.py (GET auto-create defaults, PUT update + persiste, partial update no toca otros campos, languages normalize/dedupe, body vacío 400, campo desconocido 422, languages vacío 422). test_models singleton hecho robusto (no acopla agency_name a un valor fijo).",
      },
    ],
  },
  {
    version: "0.5.0",
    date: "2026-05-25",
    title: {
      en: "Phase 5 — Calendar booking (Cal.com) with SIMULATED + dashboard VisitsSection",
      es: "Phase 5 — Calendar booking (Cal.com) con SIMULATED + dashboard VisitsSection",
    },
    changes: [
      {
        en: "Visit model (id, lead_id FK CASCADE, calendar_provider, external_booking_id UNIQUE, status enum scheduled/confirmed/cancelled/completed/no_show, scheduled_at indexed, duration_minutes, timezone, property_address, meeting_url, notes, timestamps). Alembic migration 003_phase5_visits.",
        es: "Visit model (id, lead_id FK CASCADE, calendar_provider, external_booking_id UNIQUE, status enum scheduled/confirmed/cancelled/completed/no_show, scheduled_at indexed, duration_minutes, timezone, property_address, meeting_url, notes, timestamps). Alembic migration 003_phase5_visits.",
      },
      {
        en: "services/calendar_cal.py — Cal.com v2 API wrapper: list_available_slots, create_booking, cancel_booking. SIMULATED mode generates weekday slots 10/11/14/15/16 in-memory + calcom-sim-<uuid> IDs; production hits api.cal.com with the cal-api-version 2024-08-13 header.",
        es: "services/calendar_cal.py — Cal.com v2 API wrapper: list_available_slots, create_booking, cancel_booking. SIMULATED mode genera slots weekday 10/11/14/15/16 in-memory + IDs calcom-sim-<uuid>; producción hace HTTP a api.cal.com con cal-api-version 2024-08-13 header.",
      },
      {
        en: "4 new endpoints: GET /leads/{id}/calendar/slots?days=N&timezone=, POST /leads/{id}/calendar/book, GET /leads/{id}/visits, POST /visits/{id}/cancel. Slots filters the lead's busy_starts (no double-booking in the same conversation).",
        es: "4 endpoints nuevos: GET /leads/{id}/calendar/slots?days=N&timezone=, POST /leads/{id}/calendar/book, GET /leads/{id}/visits, POST /visits/{id}/cancel. Slots filtra busy_starts del lead (no double-booking en la misma conversación).",
      },
      {
        en: "Auto-pick email vs phone for the attendee: if lead.phone contains '@' → email for Cal.com; else phone. Lead with no email + real production → 503 with a clear message.",
        es: "Auto-pick email vs phone para attendee: si lead.phone contiene '@' → email para Cal.com; sino phone. Lead sin email + producción real → 503 con mensaje claro.",
      },
      {
        en: "Frontend: VisitsSection in LeadDetail shows upcoming + past visits with cards (VisitStatusBadge, localized ES date, address, notes, cancel button). BookingDialog modal with a date-grouped slot picker, optional address, notes, confirm.",
        es: "Frontend: VisitsSection en LeadDetail muestra upcoming + past visits con cards (VisitStatusBadge, fecha localizada ES, dirección, notas, cancel button). BookingDialog modal con date-grouped slot picker, dirección opcional, notas, confirm.",
      },
      {
        en: "Dashboard URLs: /leads/{id} now shows (top→bottom): Header with metadata + TakeoverToggle (Phase 2), chat Conversation (Phase 1-3), Composer + Suggest (Phase 4), VisitsSection + Book visit (Phase 5).",
        es: "Dashboard URLs: /leads/{id} ahora muestra (top→bottom): Header con metadata + TakeoverToggle (Phase 2), Conversación chat (Phase 1-3), Composer + Sugerir (Phase 4), VisitsSection + Agendar visita (Phase 5).",
      },
      {
        en: "Tests +13 (total 77): test_calendar_service.py (7 — weekday-only, hours match, busy filter, simulated mode, booking sim id, cancel sim, calcom-sim-* always-local-cancel) + test_visits_api.py (6 — slots endpoint, slots 404, book creates Visit, list visits, cancel flips + rejects re-cancel, no double-booking).",
        es: "Tests +13 (total 77): test_calendar_service.py (7 — weekday-only, hours match, busy filter, simulated mode, booking sim id, cancel sim, calcom-sim-* always-local-cancel) + test_visits_api.py (6 — slots endpoint, slots 404, book creates Visit, list visits, cancel flips + rejects re-cancel, no double-booking).",
      },
      {
        en: "docs/setup-calcom.md production walkthrough (Cal.com account + event type + API key + DNS-less). CALENDAR_SIMULATED env var (default true) + CALCOM_BASE_URL (default api.cal.com).",
        es: "docs/setup-calcom.md producción walkthrough (Cal.com account + event type + API key + DNS-less). CALENDAR_SIMULATED env var (default true) + CALCOM_BASE_URL (default api.cal.com).",
      },
    ],
  },
  {
    version: "0.4.0",
    date: "2026-05-25",
    title: {
      en: "Phase 4 — Manual composer + AI reply suggestions (completes the takeover loop)",
      es: "Phase 4 — Composer manual + AI reply suggestions (completa el loop de takeover)",
    },
    changes: [
      {
        en: "Composer box in /leads/[id]: the realtor writes a reply and sends it via the lead's channel (WhatsApp/Email). It's persisted as Message(sender=HUMAN, direction=OUTBOUND) and routed through the existing multichannel dispatcher.",
        es: "Composer box en /leads/[id]: el realtor escribe una respuesta y la envía vía el canal del lead (WhatsApp/Email). Se persiste como Message(sender=HUMAN, direction=OUTBOUND) y se rutea por el dispatcher multichannel existente.",
      },
      {
        en: "'Suggest replies' button: generates 3 reply drafts via the LLM (Kimi/MiniMax). Each suggestion is clickable and fills the composer textarea — the realtor can edit it before sending.",
        es: "Botón 'Sugerir respuestas': genera 3 borradores de respuesta vía LLM (Kimi/MiniMax). Cada sugerencia es clickeable y llena el textarea del composer — el realtor puede editarla antes de enviar.",
      },
      {
        en: "New backend: POST /api/v1/leads/{id}/messages (human send with auto-pick of the last active conversation's channel; email threading via In-Reply-To of the last inbound) + POST /api/v1/leads/{id}/suggestions (generates N replies in JSON array format, degrades to [] + error on LLM fail or invalid JSON).",
        es: "Backend nuevo: POST /api/v1/leads/{id}/messages (human send con auto-pick del canal de la última conversación activa; threading email via In-Reply-To del último inbound) + POST /api/v1/leads/{id}/suggestions (genera N respuestas en formato JSON array, degrada a [] + error en caso de LLM fail o JSON inválido).",
      },
      {
        en: "Orchestrator: 2 new functions — send_human_message + generate_reply_suggestions. They use the existing dispatcher, Phase 3 language detection, and AgentSettings.languages.",
        es: "Orchestrator: 2 funciones nuevas — send_human_message + generate_reply_suggestions. Usan el dispatcher existente, la detección de idioma del Phase 3, y AgentSettings.languages.",
      },
      {
        en: "Auto-pick channel: if the lead has multiple active conversations (multichannel), the composer uses the last active one. For email it auto-prepends 'Re:' + In-Reply-To header.",
        es: "Auto-pick canal: si el lead tiene múltiples conversaciones activas (multichannel), el composer usa la última activa. Para email auto-prepende 'Re:' + In-Reply-To header.",
      },
      {
        en: "UX: 'count' clamped to [1, 5]. The composer shows a 0/4000 chars counter. In-line errors (no toast/modal). router.refresh() after send → the new bubble appears in the chat without reloading.",
        es: "UX: 'count' clampado a [1, 5]. Composer muestra contador 0/4000 chars. Errores in-line (no toast/modal). router.refresh() tras send → nueva burbuja aparece en el chat sin recargar.",
      },
      {
        en: "Tests +8: human-send happy path (WhatsApp simulated routing), lead-not-found error, empty text 400, lead-without-conversation error, suggestions happy path, suggestions with prose around the JSON, suggestions LLM fail graceful degrade, suggestions count clamp 99→5.",
        es: "Tests +8: human-send happy path (WhatsApp simulated routing), lead-not-found error, empty text 400, lead-without-conversation error, suggestions happy path, suggestions con prose alrededor del JSON, suggestions LLM fail degrade graceful, suggestions count clamp 99→5.",
      },
    ],
  },
  {
    version: "0.3.0",
    date: "2026-05-25",
    title: {
      en: "Phase 3 — Multichannel + Email (Resend) + Bilingual (USA pivot)",
      es: "Phase 3 — Multichannel + Email (Resend) + Bilingual (USA pivot)",
    },
    changes: [
      {
        en: "Strategic USA pivot: the target client moves from EU agencies (WhatsApp-first) to USA realtors where SMS, Email and calls dominate. WhatsApp stays as an optional channel for international clients.",
        es: "Pivote estratégico USA: el target de clientes pasa de inmobiliarias EU (WhatsApp-first) a realtors USA donde dominan SMS, Email y llamadas. WhatsApp queda como canal opcional para clientes internacionales.",
      },
      {
        en: "Multichannel refactor: channel-agnostic schema. Renames messages.wa_message_id→external_id, wa_status→delivery_status, conversations.wa_thread_id→external_thread_id. + messages.subject (email). leads.phone widened 32→254 chars (accepts emails as identifier). Alembic migration 002_phase3_multichannel preserves existing rows.",
        es: "Multichannel refactor: schema agnóstico al canal. Renames messages.wa_message_id→external_id, wa_status→delivery_status, conversations.wa_thread_id→external_thread_id. + messages.subject (email). leads.phone widened 32→254 chars (acepta emails como identifier). Alembic migration 002_phase3_multichannel preserva rows existentes.",
      },
      {
        en: "Shared ParsedMessage in services/_common.py — a dataclass with channel, external_id, from_identifier, content, subject, thread_id. Each channel (WhatsApp / Email / SMS / Voice) emits the same type.",
        es: "ParsedMessage común en services/_common.py — dataclass con channel, external_id, from_identifier, content, subject, thread_id. Cada canal (WhatsApp / Email / SMS / Voice) emite el mismo tipo.",
      },
      {
        en: "Orchestrator with dispatcher: handle_inbound_message now routes outbound to whatsapp_send / email_send per conversation.channel. Lazy imports — a deploy may not have the Resend SDK if it doesn't use email.",
        es: "Orchestrator con dispatcher: handle_inbound_message ahora rutea outbound a whatsapp_send / email_send según conversation.channel. Lazy imports — un deploy puede no tener Resend SDK si no usa email.",
      },
      {
        en: "Email channel (Resend): services/email.py with send_email (threading via In-Reply-To + References), parse_inbound_email (Resend payload + HTML fallback), verify_resend_signature (Svix-style HMAC with multi-sig support). EMAIL_SIMULATED=true in dev (logs outbound, needs no Resend account or DNS).",
        es: "Email channel (Resend): services/email.py con send_email (threading via In-Reply-To + References), parse_inbound_email (Resend payload + HTML fallback), verify_resend_signature (Svix-style HMAC con multi-sig support). EMAIL_SIMULATED=true en dev (loguea outbound, no requiere cuenta Resend ni DNS).",
      },
      {
        en: "New webhook: POST /api/v1/webhooks/email — same contract as WhatsApp (200 + UNIQUE external_id catches retries).",
        es: "Webhook nuevo: POST /api/v1/webhooks/email — mismo contrato que WhatsApp (200 + UNIQUE external_id catches retries).",
      },
      {
        en: "Bilingual: services/i18n.py with detect_language (langdetect, deterministic seed) + pick_supported_language (whitelist AgentSettings.languages) + language_instruction (ES/EN steering line for the system prompt). Detects from the last inbound, NO bias from historical agent replies. The classifier accepts an optional language_hint.",
        es: "Bilingüe: services/i18n.py con detect_language (langdetect, seed determinista) + pick_supported_language (whitelist AgentSettings.languages) + language_instruction (steering line ES/EN para el system prompt). Detecta del último inbound, NO bias en réplicas históricas del agente. Classifier acepta language_hint opcional.",
      },
      {
        en: "Dashboard: MessageBubble shows a channel icon (envelope email, message-circle WhatsApp, message-square SMS, phone voice) + the email subject visible when it applies. LeadsTable shows a heuristic-based glyph next to the identifier (email vs phone).",
        es: "Dashboard: MessageBubble muestra channel icon (envelope email, message-circle WhatsApp, message-square SMS, phone voice) + asunto del email visible cuando applies. LeadsTable muestra heuristic-based glyph al lado del identificador (email vs phone).",
      },
      {
        en: "Backend: the Phase 2 PATCH lead endpoint still works. Pydantic schemas in conversations.py updated to the new naming (external_id / delivery_status / subject / external_thread_id).",
        es: "Backend: PATCH lead endpoint Phase 2 sigue funcionando. Pydantic schemas en conversations.py actualizados al naming nuevo (external_id / delivery_status / subject / external_thread_id).",
      },
      {
        en: "Tests: 55 total (45 + 10 new = 8 email service + 9 i18n - 7 duplicated/collected). Email E2E creates a Lead via address, Conversation(channel=email), 2 Messages with subject + threading.",
        es: "Tests: 55 total (45 + 10 nuevos = 8 email service + 9 i18n - 7 duplicados/colectados). E2E email crea Lead via address, Conversation(channel=email), 2 Messages con subject + threading.",
      },
      {
        en: "Frontend lib/api.ts: Message + Conversation interfaces aligned to the new backend (external_id, delivery_status, subject, external_thread_id).",
        es: "Frontend lib/api.ts: Message + Conversation interfaces alineadas al backend nuevo (external_id, delivery_status, subject, external_thread_id).",
      },
      {
        en: "Roadmap reordered after the USA pivot: Phase 4=SMS (Twilio), Phase 5=Voice (VAPI/Retell), Phase 6=Calendar (moved from Phase 3), Phase 7=MLS/IDX (USA equivalent of Idealista), Phase 8=installer + demo subdomain.",
        es: "Roadmap reordenado post-pivote USA: Phase 4=SMS (Twilio), Phase 5=Voice (VAPI/Retell), Phase 6=Calendar (movido desde Phase 3), Phase 7=MLS/IDX (USA equivalente Idealista), Phase 8=installer + demo subdomain.",
      },
    ],
  },
  {
    version: "0.2.0",
    date: "2026-05-25",
    title: {
      en: "Phase 2 — Realtor dashboard (leads list + chat view + human takeover)",
      es: "Phase 2 — Realtor dashboard (lista leads + chat view + human takeover)",
    },
    changes: [
      {
        en: "Functional frontend dashboard in Next.js 14 App Router. Replaces the landing placeholder at `/` (which now redirects to `/leads`). The old landing stays available at `/about`.",
        es: "Dashboard frontend funcional en Next.js 14 App Router. Reemplaza el landing placeholder en `/` (que ahora redirige a `/leads`). La landing vieja queda accesible en `/about`.",
      },
      {
        en: "`/leads` — leads table with filters by status (New/Qualified/Visiting/Post-visit/Won/Lost/Paused) and intent (Rent/Buy/Valuation/Other). Clicking a lead → detail view.",
        es: "`/leads` — tabla de leads con filtros por status (Nuevo/Cualificado/Visitando/Post-visita/Cerrado/Perdido/Pausado) e intent (Alquiler/Compra/Tasación/Otro). Click en un lead → vista detalle.",
      },
      {
        en: "`/leads/[id]` — detail view with lead metadata (name, phone, zone, budget, type, urgency, timestamps) + full chat-style conversation (inbound/outbound bubbles, LLM provider indicator, Meta send status) + human takeover toggle.",
        es: "`/leads/[id]` — vista detalle con metadata del lead (nombre, teléfono, zona, presupuesto, tipo, urgencia, timestamps) + conversación completa estilo chat (burbujas inbound/outbound, indicador de provider LLM, status de envío Meta) + toggle de control humano.",
      },
      {
        en: "'Human vs AI' toggle — a button that calls `PATCH /api/v1/leads/{id}` with `{human_takeover: true|false}`. When ON, the orchestrator does NOT auto-generate a reply for the next inbound message (Phase 1 already respects this flag).",
        es: "Toggle 'Humano vs IA' — botón que llama `PATCH /api/v1/leads/{id}` con `{human_takeover: true|false}`. Cuando está ON, el orchestrator NO genera respuesta automática para el siguiente mensaje entrante (Phase 1 ya respeta esta flag).",
      },
      {
        en: "Components: `Nav` (top bar with branding + links), `StatusBadge` + `IntentBadge` (palette by category), `FilterBar` (querystring-based, Suspense for SSR), `LeadsTable` (list with light virtualization), `MessageBubble` (chat-style with sender icons), `LeadDetail`, `TakeoverToggle`.",
        es: "Componentes: `Nav` (top bar con branding + links), `StatusBadge` + `IntentBadge` (paleta por categoría), `FilterBar` (querystring-based, Suspense para SSR), `LeadsTable` (lista con virtualización ligera), `MessageBubble` (chat-style con sender icons), `LeadDetail`, `TakeoverToggle`.",
      },
      {
        en: "Typed API client in `lib/api.ts` — TypeScript interfaces for Lead, Conversation, Message + `leadsApi.list/get/patch` and `conversationsApi.get` functions. `format.ts` helper with relative times in Spanish + budget formatting.",
        es: "API client tipado en `lib/api.ts` — interfaces TypeScript para Lead, Conversation, Message + funciones `leadsApi.list/get/patch` y `conversationsApi.get`. Helper `format.ts` con tiempos relativos en castellano + formato de presupuesto.",
      },
      {
        en: "Backend: new endpoint `PATCH /api/v1/leads/{id}` with `LeadPatch` schema (partial update, `extra='forbid'` rejects unknown fields with 422). Accepts name, status, intent, zone, budget_min/max, property_type, urgency, human_takeover.",
        es: "Backend: nuevo endpoint `PATCH /api/v1/leads/{id}` con schema `LeadPatch` (partial update, `extra='forbid'` rechaza campos desconocidos con 422). Acepta name, status, intent, zone, budget_min/max, property_type, urgency, human_takeover.",
      },
      {
        en: "`next.config.js` proxies `/api/*` to `INTERNAL_API_URL` (default `http://backend:8000`) — the JS client always talks same-origin, works from LAN/Tailscale/future Cloudflare without reconfiguring URLs.",
        es: "`next.config.js` proxya `/api/*` a `INTERNAL_API_URL` (default `http://backend:8000`) — cliente JS siempre habla same-origin, funciona desde LAN/Tailscale/futuro Cloudflare sin reconfigurar URLs.",
      },
      {
        en: "Tests +8: `test_leads_api.py` covers list envelope, get 404, PATCH takeover toggle, PATCH partial update (status+zone without touching name), PATCH empty body 400, PATCH unknown field 422, PATCH invalid status 422, PATCH 404. Total now: 33 tests.",
        es: "Tests +8: `test_leads_api.py` cubre list envelope, get 404, PATCH takeover toggle, PATCH partial update (status+zone sin tocar name), PATCH body vacío 400, PATCH campo desconocido 422, PATCH status inválido 422, PATCH 404. Total ahora: 33 tests.",
      },
      {
        en: "Full brand rename Inmobiliario → Realtors in `<title>`, landing copy, README.",
        es: "Brand rename completo Inmobiliario → Realtors en `<title>`, landing copy, README.",
      },
    ],
  },
  {
    version: "0.1.0",
    date: "2026-05-25",
    title: {
      en: "Phase 1 CORE — WhatsApp 24/7 agent with Kimi + MiniMax fallback",
      es: "Phase 1 CORE — WhatsApp 24/7 agent with Kimi + MiniMax fallback",
    },
    changes: [
      {
        en: "Identity setup: root CLAUDE.md with anti-patterns + port map + 3-lines-of-work distinction; GitHub topics + 5 milestones; CI workflow (ruff + pytest + tsc + lint).",
        es: "Identity setup: CLAUDE.md raíz con anti-patterns + port map + 3-líneas-de-trabajo distinction; GitHub topics + 5 milestones; CI workflow (ruff + pytest + tsc + lint).",
      },
      {
        en: "Port remap: `eko-realestate-*` container stack on 3004/8011/5434/6381 to coexist with the sales platform prod (3001/8000/5432/6379), its parallel main dev (3003/8010/5433/6380) and the pricing-v2 preview (3002). Zero collision.",
        es: "Port remap: container stack `eko-realestate-*` en 3004/8011/5434/6381 para coexistir con la sales platform prod (3001/8000/5432/6379), su main dev paralela (3003/8010/5433/6380) y el preview pricing-v2 (3002). Cero colisión.",
      },
      {
        en: "DB layer: SQLAlchemy 2.x async + Alembic baseline migration. 5 models: Lead (with status/intent enums, budget, zone, urgency, human_takeover), Conversation, Message (UNIQUE wa_message_id for webhook idempotency), Property (Phase 4 placeholder), AgentSettings (singleton with a Spanish persona + business_hours).",
        es: "DB layer: SQLAlchemy 2.x async + Alembic baseline migration. 5 modelos: Lead (con status/intent enums, budget, zone, urgency, human_takeover), Conversation, Message (UNIQUE wa_message_id para idempotencia de webhooks), Property (placeholder Phase 4), AgentSettings (singleton con persona en castellano + business_hours).",
      },
      {
        en: "LLM client: Kimi 2.6 primary + MiniMax M2.7 fallback. INLINE fallback per request (if Kimi times out/429/5xx, the same request retries with MiniMax before failing). Both via the `anthropic` SDK with a different `base_url`. An A/B test script with 5 typical ES prompts validated real quality (Kimi ~3.4s avg, MiniMax ~5.6s; both produce natural Spanish).",
        es: "LLM client: Kimi 2.6 primary + MiniMax M2.7 fallback. Fallback INLINE por request (si Kimi timeout/429/5xx, mismo request reintenta con MiniMax antes de fallar). Ambos via SDK `anthropic` con `base_url` distinto. A/B test script con 5 prompts ES típicos validó calidad real (Kimi ~3.4s avg, MiniMax ~5.6s; ambos producen castellano natural).",
      },
      {
        en: "Intent classifier: classifies rent/buy/valuation/other + extracts zone, budget, type, urgency. Pydantic schema validates; degrades to OTHER + logs raw_response on invalid JSON. Coerces \"1.500€\" → 1500.0.",
        es: "Intent classifier: clasifica rent/buy/valuation/other + extrae zona, presupuesto, tipo, urgencia. Pydantic schema valida; degrada a OTHER + log raw_response cuando JSON inválido. Coerce \"1.500€\" → 1500.0.",
      },
      {
        en: "WhatsApp webhook: GET handshake verify (token + challenge), POST inbound with HMAC-SHA256 verify (`X-Hub-Signature-256`). SIMULATED mode by default (logs outbound instead of POSTing to Meta) — development without a Meta Business App. Warning at startup if SIMULATED=true AND APP_ENV=production.",
        es: "WhatsApp webhook: GET handshake verify (token + challenge), POST inbound con HMAC-SHA256 verify (`X-Hub-Signature-256`). Modo SIMULATED por default (loguea outbound en vez de POST a Meta) — desarrollo sin Meta Business App. Warning al startup si SIMULATED=true Y APP_ENV=production.",
      },
      {
        en: "Conversation orchestrator: inbound → upsert Lead → save inbound Message → classify intent (applies if confidence ≥ 0.55) → generate reply with the LLM → save outbound Message (status=PENDING) → send via WhatsApp Cloud API → update wa_message_id + status (SENT/FAILED). Idempotency via UNIQUE wa_message_id (Meta retries don't duplicate leads).",
        es: "Conversation orchestrator: inbound → upsert Lead → save inbound Message → classify intent (aplica si confidence ≥ 0.55) → genera reply con LLM → save outbound Message (status=PENDING) → send via WhatsApp Cloud API → update wa_message_id + status (SENT/FAILED). Idempotencia via UNIQUE wa_message_id (Meta retries no duplican leads).",
      },
      {
        en: "API routes: `GET /api/v1/leads` (paginated list with status/intent filters), `GET /api/v1/leads/{id}` (detail), `GET /api/v1/conversations/{lead_id}` (full history).",
        es: "API routes: `GET /api/v1/leads` (lista paginada con filtros status/intent), `GET /api/v1/leads/{id}` (detail), `GET /api/v1/conversations/{lead_id}` (full history).",
      },
      {
        en: "Tests: 23 total — 4 LLM fallback (mocked anthropic SDK), 7 classifier (mocked LLM responses), 7 signature (HMAC valid/invalid/missing/tampered/wrong-secret), 2 webhook E2E (full flow + idempotency), 2 models (roundtrip + AgentSettings), 1 health. Live DB required for E2E + models.",
        es: "Tests: 23 total — 4 LLM fallback (mocked anthropic SDK), 7 classifier (mocked LLM responses), 7 signature (HMAC valid/invalid/missing/tampered/wrong-secret), 2 webhook E2E (full flow + idempotency), 2 models (roundtrip + AgentSettings), 1 health. Live DB required for E2E + models.",
      },
      {
        en: "Script `simulate_inbound.py` for manual CLI testing: `python scripts/simulate_inbound.py \"+34666123456\" \"Hola...\"` → simulated POST to the webhook.",
        es: "Script `simulate_inbound.py` para CLI testing manual: `python scripts/simulate_inbound.py \"+34666123456\" \"Hola...\"` → POST simulado al webhook.",
      },
      {
        en: "`setup-whatsapp.md` doc with the full flow Meta App → secrets → webhook registration → production checklist + troubleshooting.",
        es: "Doc `setup-whatsapp.md` con flow completo Meta App → secrets → webhook registration → production checklist + troubleshooting.",
      },
    ],
  },
  {
    version: "0.0.1",
    date: "2026-05-25",
    title: {
      en: "Bootstrap",
      es: "Bootstrap",
    },
    changes: [
      {
        en: "Repo skeleton: FastAPI backend + Next.js frontend + Postgres + Redis + Ollama via docker-compose.",
        es: "Esqueleto del repo: backend FastAPI + frontend Next.js + Postgres + Redis + Ollama vía docker-compose.",
      },
      {
        en: "Health endpoint at GET /api/v1/health.",
        es: "Endpoint de salud en GET /api/v1/health.",
      },
      {
        en: "Landing placeholder with brand-aligned design (Eko AI violet palette).",
        es: "Landing placeholder con diseño alineado a la marca (paleta violeta de Eko AI).",
      },
      {
        en: "README + roadmap + architecture docs.",
        es: "Docs de README + roadmap + arquitectura.",
      },
    ],
  },
];
