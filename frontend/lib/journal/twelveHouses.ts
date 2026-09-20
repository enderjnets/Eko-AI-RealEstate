/**
 * "Twelve houses worth the detour" — el contenido del primer articulo.
 *
 * Generado desde el prototipo de diseno, no escrito a mano: son doce fichas,
 * doce cuerpos de texto y noventa y seis cifras, y una errata en cualquiera de
 * ellas es una afirmacion falsa sobre la casa de otro. El generador comprueba
 * que cada cadena vuelve a aparecer en el HTML de origen antes de emitir nada.
 *
 * Vive en `lib/` y no en la pagina porque un modulo de pagina de Next solo
 * puede exportar los nombres del framework. Ojo con la consecuencia que ya
 * mordio en `fallGuide.ts`: **Tailwind no escanea `lib/`**, asi que aqui no
 * puede haber ni una clase de Tailwind. Todo valor visual va crudo.
 *
 * Ninguna de estas casas es nuestra. Cada ficha acredita a la correduria que la
 * tiene y enlaza al registro completo, que es lo que exige la Regla 6.10.F.1.b
 * de Colorado; el permiso escrito de la letra `a` se lleva en `permission`.
 */

/** Un tramo de texto. `em` marca la italica; no hay HTML crudo en los datos. */
export interface Segment {
  readonly t: string;
  readonly em?: boolean;
}

/** Un par de la rejilla de datos. La ficha 05 trae seis, no ocho, a proposito. */
export interface Fact {
  readonly label: string;
  readonly value: string;
}

export type PermissionState = "pending" | "granted";

export interface Entry {
  readonly n: number;
  readonly slug: string;
  readonly indexLabel: string;
  readonly eyebrow: string;
  readonly headline: string;
  readonly address: string;
  /** Los cuatro ficheros: principal primero, luego las tres miniaturas. */
  readonly photos: readonly string[];
  readonly alts: readonly string[];
  readonly caption: string;
  readonly body: string;
  readonly facts: readonly Fact[];
  readonly noteLabel: string;
  readonly note: readonly Segment[];
  readonly listingUrl: string;
  readonly brokerage: string;
  readonly mls: string;
  /**
   * Permiso escrito de la correduria (Regla 6.10.F.1.a). Mientras alguna siga
   * en "pending" el articulo no sale a publico: lo vigila `journal.test.ts`.
   */
  readonly permission: PermissionState;
}

export interface Panel {
  readonly n: number;
  readonly label: string;
  readonly name: string;
  readonly where: string;
}

export interface Passed {
  readonly price: string;
  readonly city: string;
  readonly street: string;
  readonly reason: readonly Segment[];
}

/** Titular con el acento en italica al final, que es la voz de la pagina. */
export interface Heading {
  readonly lead: string;
  readonly accent: string;
}

/**
 * La fecha del corte. Las cifras son una foto del registro de ese dia y la
 * Regla 6.10.F.1.c exige que el anuncio sea exacto: una ficha ya vendida lo
 * vuelve enganoso. Se comprueba antes de publicar, no se supone.
 */
export const AS_OF = "2026-09-20";

export const SLUG = "twelve-houses-worth-the-detour";

export const PAGE = {
  breadcrumb: "Colorado · Guide",
  h1: {
    lead: "Twelve houses",
    accent: "worth the detour.",
  },
  dek: "We read every active listing in Colorado above $11.7 million, one at a time, and looked at the photographs rather than the asking price. These are the twelve we would drive to see. The most expensive house in the state came sixth.",
  byline: "Natalia & Robbie",
  date: "20 September 2026",
  readTime: "9 min read",
  markets: "Aspen · Snowmass · Denver Metro",
  stripCaption: "Hover a panel to leaf through its photographs · tap on a phone",
  stats: [
    {
      label: "Cards scanned",
      value: 180,
    },
    {
      label: "Listings opened",
      value: 175,
    },
    {
      label: "Residential, active",
      value: 150,
    },
    {
      label: "Selected",
      value: 12,
    },
  ],
  method: {
    heading: {
      lead: "How we",
      accent: "chose them.",
    },
    skylineCaption: "Denver at dusk — the metro end of a market that runs from Aspen to Cherry Creek.",
    paragraphs: [
      "Sorted by price, the top of the Colorado market is repetitive: large, beige and competent. Price tells you very little about whether a house is worth looking at. So we scored each one on five things instead — how the lead photograph reads at a glance, whether there is one feature you could name in four words, whether the listing itself tells a story you can verify on the page, the gap between what the photographs promise and what the number says, and whether there are enough usable frames to show it properly.",
      "Every figure below comes from the listing record itself. Where a field is missing, we say so rather than estimate it. Where a number is misleading, we flag it under Worth knowing — including one case where the published square footage describes a single cabin on a 744-acre ranch.",
      "Nothing here is our listing. We have no interest in whether any of them sells. Each entry credits the brokerage that holds it, and links to the full record.",
    ],
  },
  twelveHeading: {
    lead: "The twelve.",
    accent: "",
  },
  twelveDek: "Ranked by how hard they are to scroll past, not by price. All active as of 20 September 2026.",
  passedHeading: {
    lead: "What we",
    accent: "passed on.",
  },
  passedDek: "Six that looked promising in the list and did not survive being opened. Included so you can see the filter working.",
  rights: "Listing data and photographs belong to the brokerages credited above and may not be reproduced without their permission. Figures are as published on 20 September 2026 and change without notice.",
  talkHeading: {
    lead: "Fifteen minutes,",
    accent: "no pitch.",
  },
} as const;

export const STRIP: readonly Panel[] = [
  {
    n: 1,
    label: "01",
    name: "Richmond Hill",
    where: "Aspen · $16.9M",
  },
  {
    n: 2,
    label: "02",
    name: "Brush Creek",
    where: "Snowmass · $29.95M",
  },
  {
    n: 3,
    label: "03",
    name: "Lakota Road",
    where: "Indian Hills · $30M",
  },
  {
    n: 4,
    label: "04",
    name: "Taylor Canyon",
    where: "Gunnison · $19.95M",
  },
  {
    n: 5,
    label: "05",
    name: "Eagle Rock Ranch",
    where: "Yampa · $26M",
  },
  {
    n: 6,
    label: "06",
    name: "Red Mountain",
    where: "Aspen · $85M",
  },
  {
    n: 7,
    label: "07",
    name: "West Creek",
    where: "Gateway · $45M",
  },
  {
    n: 8,
    label: "08",
    name: "County Road 501",
    where: "Bayfield · $28.5M",
  },
  {
    n: 9,
    label: "09",
    name: "Sweetwater Road",
    where: "Gypsum · $17.5M",
  },
  {
    n: 10,
    label: "10",
    name: "Powderbowl Trail",
    where: "Aspen · $29.99M",
  },
  {
    n: 11,
    label: "11",
    name: "Fall Creek",
    where: "Aspen · $19.5M",
  },
  {
    n: 12,
    label: "12",
    name: "W Buttermilk",
    where: "Aspen · $34.9M",
  },
];

export const ENTRIES: readonly Entry[] = [
  {
    n: 1,
    slug: "richmond",
    indexLabel: "01",
    eyebrow: "Aspen · 81611",
    headline: "A 1,136-square-foot cabin. No power line. $16.9 million.",
    address: "1221 Richmond Hill Road, Aspen, Colorado",
    photos: [
      "richmond-0.jpg",
      "richmond-1.jpg",
      "richmond-2.jpg",
      "richmond-3.jpg",
    ],
    alts: [
      "1221 Richmond Hill Road, Aspen — lead photograph",
      "1221 Richmond Hill Road, photograph 2",
      "1221 Richmond Hill Road, photograph 3",
      "1221 Richmond Hill Road, photograph 4",
    ],
    caption: "Photographs courtesy of Whitman Fine Properties.",
    body: "This is the highest price per square foot of anything for sale in Colorado right now — $14,877 — and it buys a two-bedroom off-grid cabin on a 10.38-acre mining claim along Richmond Ridge. You reach it by car or snowmobile from the gondola. Al Beyer drew it; every wall that could be glass is glass.",
    facts: [
      {
        label: "Price",
        value: "$16,900,000",
      },
      {
        label: "Living area",
        value: "1,136 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$14,877",
      },
      {
        label: "Land",
        value: "10.38 acres",
      },
      {
        label: "Beds / baths",
        value: "2 / 2",
      },
      {
        label: "Built",
        value: "2026",
      },
      {
        label: "MLS",
        value: "194310",
      },
      {
        label: "Photos",
        value: "39",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "Two bedrooms and two baths, and several interior photos frame the same window. Built in 2026, so there is no history to tell yet.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/1221-Richmond%20Hill-Aspen-CO-81611-Aspen-194310",
    brokerage: "Whitman Fine Properties",
    mls: "194310",
    permission: "pending",
  },
  {
    n: 2,
    slug: "brushcreek",
    indexLabel: "02",
    eyebrow: "Snowmass Village · 81615",
    headline: "Red barns from 1913, now worth $29.95 million.",
    address: "660 Brush Creek Road, Snowmass Village, Colorado",
    photos: [
      "brushcreek-0.jpg",
      "brushcreek-1.jpg",
      "brushcreek-2.jpg",
      "brushcreek-3.jpg",
    ],
    alts: [
      "660 Brush Creek Road, Snowmass Village — lead photograph",
      "660 Brush Creek Road, photograph 2",
      "660 Brush Creek Road, photograph 3",
      "660 Brush Creek Road, photograph 4",
    ],
    caption: "Photographs courtesy of Aspen Snowmass Sotheby's International Realty — Hyman Mall.",
    body: "Saturated red against green pasture with the range behind it — the highest-contrast frame in the whole search, and the only one still legible at thumbnail size. It is 102 acres of working-ranch history inside Snowmass Village, not out in the middle of nowhere.",
    facts: [
      {
        label: "Price",
        value: "$29,950,000",
      },
      {
        label: "Living area",
        value: "4,995 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$5,996",
      },
      {
        label: "Land",
        value: "102.62 acres",
      },
      {
        label: "Beds / baths",
        value: "6 / 6",
      },
      {
        label: "Built",
        value: "1913",
      },
      {
        label: "MLS",
        value: "193160",
      },
      {
        label: "Photos",
        value: "33",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "The interiors are far quieter than the exteriors. Choose the sequence carefully.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/660-Brush%20Creek-Snowmass%20Village-CO-81615-Aspen-193160",
    brokerage: "Aspen Snowmass Sotheby's International Realty - Hyman Mall",
    mls: "193160",
    permission: "pending",
  },
  {
    n: 3,
    slug: "lakota",
    indexLabel: "03",
    eyebrow: "Indian Hills · 80454",
    headline: "453 acres and a guarded gate, 35 minutes from Denver.",
    address: "4095 Lakota Road, Indian Hills, Colorado",
    photos: [
      "lakota-0.jpg",
      "lakota-1.jpg",
      "lakota-2.jpg",
      "lakota-3.jpg",
    ],
    alts: [
      "4095 Lakota Road, Indian Hills — lead photograph",
      "4095 Lakota Road, photograph 2",
      "4095 Lakota Road, photograph 3",
      "4095 Lakota Road, photograph 4",
    ],
    caption: "Photographs courtesy of Novella Real Estate.",
    body: "Nothing else at this scale sits inside the Denver metro belt. Behind a 24/7 manned entry and a fenced perimeter there are two separate estates — 11,200 and 17,189 square feet — plus an indoor pool, a helipad and a basketball court.",
    facts: [
      {
        label: "Price",
        value: "$30,000,000",
      },
      {
        label: "Living area",
        value: "11,200 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$2,679",
      },
      {
        label: "Land",
        value: "453.19 acres",
      },
      {
        label: "Beds / baths",
        value: "4 / 8",
      },
      {
        label: "Built",
        value: "2000",
      },
      {
        label: "MLS",
        value: "9072374",
      },
      {
        label: "Photos",
        value: "50",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "The interiors are conventional traditional luxury and can read as generic. The listing points to its own website; verify any figure you take from there.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/4095-Lakota-Indian%20Hills-CO-80454-REColorado-9072374",
    brokerage: "Novella Real Estate",
    mls: "9072374",
    permission: "pending",
  },
  {
    n: 4,
    slug: "taylor",
    indexLabel: "04",
    eyebrow: "Gunnison · 81230",
    headline: "A 1960s general store, now twelve bedrooms and seventeen baths.",
    address: "10931 County Rd. 742, Gunnison, Colorado",
    photos: [
      "taylor-0.jpg",
      "taylor-1.jpg",
      "taylor-2.jpg",
      "taylor-3.jpg",
    ],
    alts: [
      "10931 County Rd. 742, Gunnison — lead photograph",
      "10931 County Rd. 742, photograph 2",
      "10931 County Rd. 742, photograph 3",
      "10931 County Rd. 742, photograph 4",
    ],
    caption: "Photographs courtesy of Mirr Ranch Group LLC.",
    body: "Eleven Experience turned a general store and fishing outpost in Taylor Canyon into a riverside lodge under the cliffs. The ratio alone — twelve beds, seventeen baths — is the headline.",
    facts: [
      {
        label: "Price",
        value: "$19,950,000",
      },
      {
        label: "Living area",
        value: "13,927 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$1,432",
      },
      {
        label: "Land",
        value: "8.17 acres",
      },
      {
        label: "Beds / baths",
        value: "12 / 17",
      },
      {
        label: "Built",
        value: "2012",
      },
      {
        label: "MLS",
        value: "189883",
      },
      {
        label: "Photos",
        value: "56",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "This is a hospitality property, not a family house. Do not present it as an ordinary single-family home.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/10931-County%20Rd.%20742-Gunnison-CO-81230-Aspen-189883",
    brokerage: "Mirr Ranch Group LLC",
    mls: "189883",
    permission: "pending",
  },
  {
    n: 5,
    slug: "eaglerock",
    indexLabel: "05",
    eyebrow: "Yampa · 80483",
    headline: "Twenty-six acres of trout lakes, on water rights from the 1800s.",
    address: "29830 County Road 8, Yampa, Colorado",
    photos: [
      "eaglerock-0.jpg",
      "eaglerock-1.jpg",
      "eaglerock-2.jpg",
      "eaglerock-3.jpg",
    ],
    alts: [
      "29830 County Road 8, Yampa — lead photograph",
      "29830 County Road 8, photograph 2",
      "29830 County Road 8, photograph 3",
      "29830 County Road 8, photograph 4",
    ],
    caption: "Photographs courtesy of Hall and Hall Partners.",
    body: "Eagle Rock Ranch runs to 744 acres with Routt National Forest on three sides and more than 3.25 miles of shared boundary. At its centre, a system of interconnected lakes fed by a year-round stream, and a compound of historic cabins with equestrian facilities.",
    facts: [
      {
        label: "Price",
        value: "$26,000,000",
      },
      {
        label: "Land",
        value: "744 acres",
      },
      {
        label: "Beds / baths",
        value: "2 / 1",
      },
      {
        label: "Built",
        value: "1964",
      },
      {
        label: "MLS",
        value: "192889",
      },
      {
        label: "Photos",
        value: "67",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "The 644-square-foot living area in the MLS is one structure — the listing says ",
      },
      {
        t: "cabins",
        em: true,
      },
      {
        t: ", plural. We have left price per square foot out here; it is a data artefact. There is also no hero building: the strong images are all aerial.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/29830-County%20Road%208-Yampa-CO-80483-Aspen-192889",
    brokerage: "Hall and Hall Partners",
    mls: "192889",
    permission: "pending",
  },
  {
    n: 6,
    slug: "redmtn",
    indexLabel: "06",
    eyebrow: "Aspen · 81611",
    headline: "Steel, stone and glass by Aidlin Darling Design.",
    address: "979 Red Mountain Road, Aspen, Colorado",
    photos: [
      "redmtn-0.jpg",
      "redmtn-1.jpg",
      "redmtn-2.jpg",
      "redmtn-3.jpg",
    ],
    alts: [
      "979 Red Mountain Road, Aspen — lead photograph",
      "979 Red Mountain Road, photograph 2",
      "979 Red Mountain Road, photograph 3",
      "979 Red Mountain Road, photograph 4",
    ],
    caption: "Photographs courtesy of Coldwell Banker Mason Morse-Aspen.",
    body: "The great room frames downtown Aspen and three ski areas through floor-to-ceiling glass. Below grade: a bar and lounge, a wine room, a spa and gym, and a private theater.",
    facts: [
      {
        label: "Price",
        value: "$85,000,000",
      },
      {
        label: "Living area",
        value: "9,641 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$8,817",
      },
      {
        label: "Land",
        value: "0.97 acres",
      },
      {
        label: "Beds / baths",
        value: "7 / 10",
      },
      {
        label: "Built",
        value: "2014",
      },
      {
        label: "MLS",
        value: "193409",
      },
      {
        label: "Photos",
        value: "30",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "Only 30 photos, several of them dim interiors. It is also the most expensive listing in the state — easy for the story to become nothing but the number.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/979-Red%20Mountain-Aspen-CO-81611-Aspen-193409",
    brokerage: "Coldwell Banker Mason Morse-Aspen",
    mls: "193409",
    permission: "pending",
  },
  {
    n: 7,
    slug: "westcreek",
    indexLabel: "07",
    eyebrow: "Gateway · 81522",
    headline: "1,093 acres inside a red rock canyon.",
    address: "40275 Highway 141, Gateway, Colorado",
    photos: [
      "westcreek-0.jpg",
      "westcreek-1.jpg",
      "westcreek-2.jpg",
      "westcreek-3.jpg",
    ],
    alts: [
      "40275 Highway 141, Gateway — lead photograph",
      "40275 Highway 141, photograph 2",
      "40275 Highway 141, photograph 3",
      "40275 Highway 141, photograph 4",
    ],
    caption: "Photographs courtesy of Mirr Ranch Group LLC.",
    body: "It does not look like Colorado: red cliffs and canyon meadow, minutes from Gateway Canyons Resort. With 22,000 square feet built, it works out to $2,045 a foot — among the cheapest here.",
    facts: [
      {
        label: "Price",
        value: "$45,000,000",
      },
      {
        label: "Living area",
        value: "22,000 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$2,045",
      },
      {
        label: "Land",
        value: "1,093 acres",
      },
      {
        label: "Beds / baths",
        value: "8 / 8",
      },
      {
        label: "Built",
        value: "1999",
      },
      {
        label: "MLS",
        value: "189022",
      },
      {
        label: "Photos",
        value: "77",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "The house barely appears in the best photographs; the landscape is the subject. Check you are not confusing the neighbouring resort with the property.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/40275-Highway%20141-Gateway-CO-81522-Aspen-189022",
    brokerage: "Mirr Ranch Group LLC",
    mls: "189022",
    permission: "pending",
  },
  {
    n: 8,
    slug: "bayfield",
    indexLabel: "08",
    eyebrow: "Bayfield · 81122",
    headline: "940 acres, an 1890 farmhouse, and a lake of its own.",
    address: "23490 County Road 501, Bayfield, Colorado",
    photos: [
      "bayfield-0.jpg",
      "bayfield-1.jpg",
      "bayfield-2.jpg",
      "bayfield-3.jpg",
    ],
    alts: [
      "23490 County Road 501, Bayfield — lead photograph",
      "23490 County Road 501, photograph 2",
      "23490 County Road 501, photograph 3",
      "23490 County Road 501, photograph 4",
    ],
    caption: "Photographs courtesy of Live Water Properties.",
    body: "A log lodge, a white nineteenth-century farmhouse and private water — three distinct visual registers in one property. At $4,453 a foot, what you are buying is the land.",
    facts: [
      {
        label: "Price",
        value: "$28,500,000",
      },
      {
        label: "Living area",
        value: "6,400 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$4,453",
      },
      {
        label: "Land",
        value: "940 acres",
      },
      {
        label: "Beds / baths",
        value: "7 / 5",
      },
      {
        label: "Built",
        value: "1890",
      },
      {
        label: "MLS",
        value: "5992563",
      },
      {
        label: "Photos",
        value: "44",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "Photography quality is uneven between the lodge and the historic house.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/23490-County%20Road%20501-Bayfield-CO-81122-REColorado-5992563",
    brokerage: "Live Water Properties",
    mls: "5992563",
    permission: "pending",
  },
  {
    n: 9,
    slug: "sweetwater",
    indexLabel: "09",
    eyebrow: "Gypsum · 81637",
    headline: "Built in 1880. 411 acres. One bedroom.",
    address: "2650 Sweetwater Road, Gypsum, Colorado",
    photos: [
      "sweetwater-0.jpg",
      "sweetwater-1.jpg",
      "sweetwater-2.jpg",
      "sweetwater-3.jpg",
    ],
    alts: [
      "2650 Sweetwater Road, Gypsum — lead photograph",
      "2650 Sweetwater Road, photograph 2",
      "2650 Sweetwater Road, photograph 3",
      "2650 Sweetwater Road, photograph 4",
    ],
    caption: "Photographs courtesy of Hall and Hall Partners.",
    body: "A fishing and equestrian ranch in the upper Sweetwater valley with the Flat Tops behind it and streams professionally enhanced for dry-fly water. It carries 102 photographs — more than enough for a long sequence.",
    facts: [
      {
        label: "Price",
        value: "$17,500,000",
      },
      {
        label: "Living area",
        value: "3,464 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$5,052",
      },
      {
        label: "Land",
        value: "411 acres",
      },
      {
        label: "Beds / baths",
        value: "1 / 3",
      },
      {
        label: "Built",
        value: "1880",
      },
      {
        label: "MLS",
        value: "189337",
      },
      {
        label: "Photos",
        value: "102",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "One bedroom across 3,464 square feet will confuse a reader. Explain it or leave the figure out.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/2650-Sweetwater-Gypsum-CO-81637-Aspen-189337",
    brokerage: "Hall and Hall Partners",
    mls: "189337",
    permission: "pending",
  },
  {
    n: 10,
    slug: "powderbowl",
    indexLabel: "10",
    eyebrow: "Aspen · 81611",
    headline: "A channel of water runs the length of the property.",
    address: "111 Powderbowl Trail, Aspen, Colorado",
    photos: [
      "powderbowl-0.jpg",
      "powderbowl-1.jpg",
      "powderbowl-2.jpg",
      "powderbowl-3.jpg",
    ],
    alts: [
      "111 Powderbowl Trail, Aspen — lead photograph",
      "111 Powderbowl Trail, photograph 2",
      "111 Powderbowl Trail, photograph 3",
      "111 Powderbowl Trail, photograph 4",
    ],
    caption: "Photographs courtesy of Aspen Snowmass Sotheby's International Realty — Hyman Mall.",
    body: "The lead photograph is a long reflecting channel cutting the site up to a dark facade — a composition that crops cleanly to vertical. It is the most graphic frame in the search.",
    facts: [
      {
        label: "Price",
        value: "$29,995,000",
      },
      {
        label: "Living area",
        value: "8,006 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$3,747",
      },
      {
        label: "Land",
        value: "1.01 acres",
      },
      {
        label: "Beds / baths",
        value: "6 / 9",
      },
      {
        label: "Built",
        value: "2005",
      },
      {
        label: "MLS",
        value: "193810",
      },
      {
        label: "Photos",
        value: "29",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "Only 29 photos, and the interiors are not at the level of the exterior.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/111-Powderbowl-Aspen-CO-81611-Aspen-193810",
    brokerage: "Aspen Snowmass Sotheby's International Realty - Hyman Mall",
    mls: "193810",
    permission: "pending",
  },
  {
    n: 11,
    slug: "fallcreek",
    indexLabel: "11",
    eyebrow: "Aspen · 81611",
    headline: "It has its own waterfall, on twenty private acres.",
    address: "27 & 33 Fall Creek, Aspen, Colorado",
    photos: [
      "fallcreek-0.jpg",
      "fallcreek-1.jpg",
      "fallcreek-2.jpg",
      "fallcreek-3.jpg",
    ],
    alts: [
      "27 and 33 Fall Creek, Aspen — lead photograph",
      "27 and 33 Fall Creek, photograph 2",
      "27 and 33 Fall Creek, photograph 3",
      "27 and 33 Fall Creek, photograph 4",
    ],
    caption: "Photographs courtesy of Compass Aspen.",
    body: "The waterfall in deep forest is the most cinematic image of the whole search and needs no explanation to work. The house is secondary here; the water is the reason to stop.",
    facts: [
      {
        label: "Price",
        value: "$19,500,000",
      },
      {
        label: "Living area",
        value: "5,356 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$3,641",
      },
      {
        label: "Land",
        value: "20 acres",
      },
      {
        label: "Beds / baths",
        value: "5 / 5",
      },
      {
        label: "Built",
        value: "2015",
      },
      {
        label: "MLS",
        value: "193352",
      },
      {
        label: "Photos",
        value: "27",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "Only 27 photos and the house itself is modest. The whole thing rests on one image.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/27%20%26%2033-Fall%20Creek-Aspen-CO-81611-Aspen-193352",
    brokerage: "Compass Aspen",
    mls: "193352",
    permission: "pending",
  },
  {
    n: 12,
    slug: "buttermilk",
    indexLabel: "12",
    eyebrow: "Aspen · 81611",
    headline: "A wine cellar cut in below 11,275 square feet.",
    address: "1330 W Buttermilk Road, Aspen, Colorado",
    photos: [
      "buttermilk-0.jpg",
      "buttermilk-1.jpg",
      "buttermilk-2.jpg",
      "buttermilk-3.jpg",
    ],
    alts: [
      "1330 W Buttermilk Road, Aspen — lead photograph",
      "1330 W Buttermilk Road, photograph 2",
      "1330 W Buttermilk Road, photograph 3",
      "1330 W Buttermilk Road, photograph 4",
    ],
    caption: "Photographs courtesy of Compass Aspen.",
    body: "The lower level is given over to entertaining — theater, media lounge and a cellar cut into the ground. Above it, a stone colonnade and floor-to-ceiling glass open onto a resort-scale pool on two acres in West Buttermilk.",
    facts: [
      {
        label: "Price",
        value: "$34,900,000",
      },
      {
        label: "Living area",
        value: "11,275 sq ft",
      },
      {
        label: "Per sq ft",
        value: "$3,095",
      },
      {
        label: "Land",
        value: "2.03 acres",
      },
      {
        label: "Beds / baths",
        value: "6 / 9",
      },
      {
        label: "Built",
        value: "2002",
      },
      {
        label: "MLS",
        value: "193933",
      },
      {
        label: "Photos",
        value: "56",
      },
    ],
    noteLabel: "Worth knowing",
    note: [
      {
        t: "Heavy stone and timber interiors, a register that already appears several times on this list. The hook is underground, not on the facade.",
      },
    ],
    listingUrl: "https://www.evrealestate.com/en/shops/aspen/properties/our-listings/1330-Buttermilk-Aspen-CO-81611-Aspen-193933",
    brokerage: "Compass Aspen",
    mls: "193933",
    permission: "pending",
  },
];

export const PASSED: readonly Passed[] = [
  {
    price: "$20,000,000",
    city: "Glenwood Springs",
    street: "TBD County Road 117",
    reason: [
      {
        t: "1,441 acres ringed by federal land with senior water rights — but the MLS files it as ",
      },
      {
        t: "Ranch",
        em: true,
      },
      {
        t: ", with no living area, no bedrooms and no year built. It is land, not a house.",
      },
    ],
  },
  {
    price: "$19,850,000",
    city: "Cherry Hills Village",
    street: "12 Lynn Road",
    reason: [
      {
        t: "The largest house in the search at 23,060 square feet, and the 2007 interiors read dated. Visual score 10 out of 30.",
      },
    ],
  },
  {
    price: "$34,950,000",
    city: "Aspen",
    street: "433 Gillespie Street",
    reason: [
      {
        t: "Dark volumes that photograph beautifully — but only seven published photos. Not enough for a sequence.",
      },
    ],
  },
  {
    price: "$16,500,000",
    city: "Boulder",
    street: "1750 Sunset Boulevard",
    reason: [
      {
        t: "Crisp new-build white with the Flatirons behind it, and nothing else: no nameable feature, no history, no price anomaly.",
      },
    ],
  },
  {
    price: "$14,995,000",
    city: "Breckenridge",
    street: "19 Peak Eight Court",
    reason: [
      {
        t: "Timber lodge with mining detail and gondola access, visually indistinguishable from twenty other mountain houses in the same set.",
      },
    ],
  },
  {
    price: "$12,000,000",
    city: "Cherry Hills Village",
    street: "5800 Piedmont Drive",
    reason: [
      {
        t: "14,210 square feet in the Denver metro, but traditional stone and a mansion staircase — the most generic frame in the category.",
      },
    ],
  },
];

export const INDEX = {
  latestLabel: "Latest",
  latestCount: "One piece so far",
  cardCategory: "Colorado · Guide",
  cardDate: "20 Sept 2026",
  cardReadTime: "9 min read",
  articleTitle: "worth the detour.",
  cardCta: "Read the piece →",
  cardPhoto: "brushcreek-0.jpg",
  cardAlt: "Red barns at 660 Brush Creek Road, Snowmass Village",
  cardDek: "We read every active listing in Colorado above $11.7 million and looked at the photographs rather than the asking price. The most expensive house in the state came sixth.",
  h1: {
    lead: "What we notice,",
    accent: "written down.",
  },
  dek: "We look at the Aspen, Roaring Fork and Denver markets every week anyway. When something in the listings is worth a second look — a price that does not add up, a house nobody is talking about, a neighbourhood turning over — we write it here rather than keep it to ourselves.",
  next: [
    {
      title: "Looking around",
      body: "We read a whole slice of the market and tell you which houses are actually worth the drive, and why the rest are not.",
    },
    {
      title: "Market notes",
      body: "What sold, what withdrew, and what the gap between asking and closing is doing this quarter in Aspen and the metro.",
    },
    {
      title: "Neighbourhood files",
      body: "One street or one valley at a time — who buys there, what it costs, and what you give up by choosing it.",
    },
  ],
} as const;

/** Copias para los tests; ver la nota de `fallGuide.ts` sobre esto. */
export const ENTRIES_FOR_TEST = ENTRIES;
