/**
 * The fall guide's content: twelve places near Denver, sorted by the elevation
 * their aspens turn at.
 *
 * It lives beside the page rather than inside it because a Next page module
 * may export only the framework's own names — a `BANDS_FOR_TEST` export failed
 * the typecheck, which is the framework saying what this file is for. The test
 * imports the table from here; the page renders it.
 */

/**
 * A photograph of one of these places, and the credit that has to travel with
 * it.
 *
 * The credit is DATA, not five hand-written lines of markup, because CC BY and
 * CC BY-SA both require it and a hand-written one is the kind of thing that
 * survives four copy-pastes and loses a name on the fifth. Author, licence
 * name, licence deed and the original file page all render from here, under
 * every photo, every time.
 *
 * `position` exists because the files are served UNCROPPED. A saved crop is a
 * derivative work and would inherit the share-alike clause four of these five
 * carry; framing the original with `object-position` is not. See
 * `public/landing/fall/LICENCIA.txt` for each file's provenance — and for the
 * seven places that have no free photograph at all.
 */
export type Photo = {
  src: string;
  alt: string;
  /**
   * A raw `object-position` value (`"50% 58%"`), applied as an inline style.
   *
   * NOT a Tailwind `[object-position:…]` class, and that is the whole point:
   * `tailwind.config.ts` scans `app/` and `components/`, not `lib/`, so the
   * moment this table moved out of the page the generated class stopped being
   * generated — no error, no warning, just a photo quietly re-centred and a
   * comment that had become a lie. An inline style depends on nothing.
   */
  position?: string;
  author: string;
  license: string;
  licenseUrl: string;
  sourceUrl: string;
};

/**
 * Where to point a phone when somebody decides to actually go.
 *
 * A search query, never coordinates. Three of these entries are 22-mile
 * byways, city-wide trails or three parks at once — a pin would be a made-up
 * point on a road, and inventing a coordinate for a real place on a page that
 * names real places is the same failure as putting a stock photograph under a
 * place name. The official Maps URL scheme searches; the query carries the
 * state so "Central City" cannot land in Kentucky.
 *
 * An ARRAY because the entries that cover several places need several links,
 * and one link labelled "Open in Maps" under a heading that names three parks
 * would be a promise the link does not keep. `label` is what the reader sees:
 * "Open in Maps" when the heading already names the destination, and the
 * place's own name when it does not.
 */
export type MapLink = { label: string; query: string };

export type Spot = {
  name: string;
  drive: string;
  what: string;
  photo?: Photo;
  /** At least one. `fallGuide.test.ts` refuses a spot without one. */
  maps: MapLink[];
};

/**
 * The official Google Maps URL scheme — documented, keyless, and stable.
 * `encodeURIComponent` and not a hand-built string: three of these queries
 * carry commas, one carries a slash and one an apostrophe.
 */
export function mapsUrl(query: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

/**
 * `id` is the anchor the ladder at the top jumps to. The ladder is this page's
 * table of contents and its single idea at once, so those hrefs and these ids
 * are one mechanism written in two places — `fallGuide.test.ts` pins them
 * together, because a renamed band would break the jump silently.
 */
export type Band = { id: string; elevation: string; when: string; note: string; spots: Spot[] };

/**
 * The bands, and why the guide is built out of them rather than out of a
 * ranked list of places.
 *
 * Aspens turn from the top down. A page that names "the seven best spots" is
 * wrong twice in one season: too early for the low valleys in September, and
 * pointing at bare passes in October. Elevation is the axis that keeps the
 * advice true the whole time, and it is also the single most useful thing a
 * local knows that a visitor does not.
 */
export const BANDS: Band[] = [
  {
    id: "band-1",
    elevation: "Above 9,500 ft",
    when: "Mid to late September",
    note: "The high passes go first, and they go fast — a windy week can end it.",
    spots: [
      {
        name: "Guanella Pass Scenic Byway",
        maps: [
          { label: "Open in Maps", query: "Guanella Pass Scenic Byway, Colorado" },
        ],
        drive: "40 miles",
        what:
          "Twenty-two miles of byway between Georgetown and Grant, topping out at " +
          "11,670 ft under Mount Blue Sky and Mount Bierstadt, with thick aspen " +
          "stands on both sides near the summit.",
        photo: {
          src: "/landing/fall/guanella-pass.jpg",
          alt: "The valley below Guanella Pass, aspens turning gold among the spruce",
          position: "50% 58%",
          author: "JenFulmer",
          license: "CC BY-SA 4.0",
          licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0/",
          sourceUrl:
            "https://commons.wikimedia.org/wiki/File:Scenic_Guanella_Pass,_Colorado.jpg",
        },
      },
      {
        name: "Kenosha Pass",
        maps: [
          { label: "Open in Maps", query: "Kenosha Pass, Colorado" },
        ],
        drive: "60 miles, US 285",
        what:
          "The classic Denver leaf drive. At about 10,000 ft the highway tops out " +
          "and the whole South Park basin opens up in gold. The lots on both sides " +
          "of the road fill early — this is a sunrise trip, not a lunchtime one.",
        photo: {
          src: "/landing/fall/kenosha-pass.jpg",
          alt: "The South Park basin seen from Kenosha Pass, with gold aspens beside US 285",
          author: "Kimon Berlin",
          license: "CC BY-SA 2.0",
          licenseUrl: "https://creativecommons.org/licenses/by-sa/2.0/",
          sourceUrl:
            "https://commons.wikimedia.org/wiki/File:South_Park_from_Kenosha_Pass.jpg",
        },
      },
      {
        name: "Peak to Peak Byway",
        maps: [
          { label: "Open in Maps", query: "Peak to Peak Scenic Byway, Colorado" },
        ],
        drive: "CO 72 and CO 7",
        what:
          "Black Hawk up to Estes Park, with high aspen groves most of the way. " +
          "The long option: it works as a loop rather than an out-and-back.",
        photo: {
          src: "/landing/fall/peak-to-peak.jpg",
          alt: "An aspen-streaked hillside along the Peak to Peak Highway",
          author: "Kimon Berlin",
          license: "CC BY-SA 2.0",
          licenseUrl: "https://creativecommons.org/licenses/by-sa/2.0/",
          sourceUrl:
            "https://commons.wikimedia.org/wiki/File:Peak-to-Peak_Highway_(3960744912).jpg",
        },
      },
    ],
  },
  {
    id: "band-2",
    elevation: "7,000 – 9,000 ft",
    when: "Late September to mid October",
    note: "The widest window of the season, and the one that survives a bad forecast.",
    spots: [
      {
        name: "Georgetown Loop Railroad",
        maps: [
          { label: "Open in Maps", query: "Georgetown Loop Railroad, Georgetown, Colorado" },
        ],
        drive: "40 miles",
        what:
          "A vintage steam locomotive between Georgetown and Silver Plume, " +
          "surrounded by aspen. The one on this list that works with small " +
          "children and with anyone who would rather not hike.",
        photo: {
          src: "/landing/fall/georgetown-loop.jpg",
          alt: "The Georgetown Loop train curving between pines and turning aspen",
          author: "PhotogOne",
          license: "CC BY-SA 4.0",
          licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0/",
          sourceUrl:
            "https://commons.wikimedia.org/wiki/File:Georgetown_Loop_Railroad_in_autumn.jpg",
        },
      },
      {
        name: "Mighty Argo Cable Car, Idaho Springs",
        maps: [
          { label: "Open in Maps", query: "Mighty Argo Cable Car, Idaho Springs, Colorado" },
        ],
        drive: "33 miles",
        what:
          "Gondolas climbing from 7,550 ft to 8,800 ft at Miners Point. Height " +
          "without a trailhead, and the shortest drive of any real overlook here.",
      },
      {
        name: "Dillon Reservoir — Frisco and Silverthorne",
        maps: [
          { label: "Open in Maps", query: "Dillon Reservoir, Colorado" },
        ],
        drive: "69 miles",
        what:
          "An 18-mile paved path circles the lake, so you can take as much or as " +
          "little of it as the afternoon allows.",
      },
    ],
  },
  {
    id: "band-3",
    elevation: "6,000 – 8,000 ft",
    when: "Most of October",
    note: "When the passes are bare and everyone assumes it is over, this is where it is.",
    spots: [
      {
        name: "Golden Gate Canyon State Park",
        maps: [
          { label: "Open in Maps", query: "Golden Gate Canyon State Park, Colorado" },
        ],
        drive: "Northwest of Golden",
        what:
          "Lower-elevation aspen groves with the mountain vistas behind them. " +
          "Close enough to go after work.",
        photo: {
          src: "/landing/fall/golden-gate-canyon.jpg",
          alt: "A trail through yellow aspens and dry grass at Golden Gate Canyon State Park",
          author: "Tony Webster",
          license: "CC BY 2.0",
          licenseUrl: "https://creativecommons.org/licenses/by/2.0/",
          sourceUrl:
            "https://commons.wikimedia.org/wiki/File:Autumn_at_Golden_Gate_Canyon_State_Park,_Colorado_Mountains.jpg",
        },
      },
      {
        name: "Evergreen",
        maps: [
          { label: "Maxwell Falls", query: "Maxwell Falls Trailhead, Evergreen, Colorado" },
          { label: "Alderfer/Three Sisters", query: "Alderfer/Three Sisters Park, Evergreen, Colorado" },
        ],
        drive: "CO 74, the Lariat Loop",
        what:
          "Maxwell Falls and Alderfer/Three Sisters Park for walking, and the " +
          "Lariat Loop Scenic Byway through Bergen Park and back down to Golden " +
          "for driving.",
      },
      {
        name: "Central City",
        maps: [
          { label: "Open in Maps", query: "Central City, Colorado" },
        ],
        drive: "Oh My God Road to Idaho Springs",
        what:
          "Aspen around the old cemeteries above town, and a slow unpaved road " +
          "down to Idaho Springs that is worth the hour it takes.",
      },
    ],
  },
  {
    id: "band-4",
    elevation: "Denver itself, 5,280 ft",
    when: "October into November",
    note: "The part people forget: the last three weeks of color happen at home.",
    spots: [
      {
        name: "High Line Canal Trail",
        maps: [
          { label: "Open in Maps", query: "High Line Canal Trail, Denver, Colorado" },
        ],
        drive: "City-wide",
        what: "More than 70 miles of cottonwoods threading the whole metro area.",
      },
      {
        name: "Cherry Creek and South Platte trails",
        maps: [
          { label: "Cherry Creek Trail", query: "Cherry Creek Trail, Denver, Colorado" },
          { label: "South Platte River Trail", query: "South Platte River Trail, Denver, Colorado" },
        ],
        drive: "From downtown",
        what:
          "Forty-plus miles each — downtown out to Cherry Creek State Park, and " +
          "the river down to Chatfield and Waterton Canyon.",
      },
      {
        name: "Washington Park, City Park, Sloan's Lake",
        maps: [
          { label: "Washington Park", query: "Washington Park, Denver, Colorado" },
          { label: "City Park", query: "City Park, Denver, Colorado" },
          { label: "Sloan's Lake", query: "Sloan's Lake Park, Denver, Colorado" },
        ],
        drive: "In town",
        what:
          "The three that hold their color longest, and the ones you can walk " +
          "to from a Denver neighborhood.",
      },
    ],
  },
];

/**
 * The same table, under the name the test imports.
 *
 * Named `…ForTest` like `isUngatedForTest` in `AuthGuard`: it marks which
 * import exists to be asserted on rather than rendered, so nothing in the app
 * reaches for it to decide something else.
 */
export const BANDS_FOR_TEST = BANDS;
