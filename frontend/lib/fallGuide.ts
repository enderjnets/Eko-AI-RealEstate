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
    elevation: "High passes and mountain byways",
    when: "Often September; check current reports",
    note: "Higher locations often turn earlier. Wind and weather can shorten the viewing window.",
    spots: [
      {
        name: "Guanella Pass Scenic Byway",
        maps: [
          { label: "Open in Maps", query: "Guanella Pass Scenic Byway, Colorado" },
        ],
        drive: "Georgetown area — map your route",
        what:
          "Twenty-two miles of byway between Georgetown and Grant, topping out at " +
          "about 11,670 ft. Elevation varies along the route; check road and " +
          "viewing conditions before setting out.",
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
        drive: "US 285 — map your route",
        what:
          "A mountain stop on US 285 with views toward South Park. Check current " +
          "conditions and parking information, and have a backup plan on busy days.",
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
          "Plan a scenic drive between the Black Hawk area and Estes Park. " +
          "Allow time for your chosen stops and check travel conditions.",
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
    elevation: "Mountain towns and scenic stops",
    when: "September into October; timing varies",
    note: "Compare current conditions across several stops before choosing your route.",
    spots: [
      {
        name: "Georgetown Loop Railroad",
        maps: [
          { label: "Open in Maps", query: "Georgetown Loop Railroad, Georgetown, Colorado" },
        ],
        drive: "Georgetown area — map your route",
        what:
          "A scenic railroad ride between Georgetown and Silver Plume. " +
          "Check the operator's schedule, ticket availability and accessibility " +
          "information before planning your visit.",
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
        drive: "Idaho Springs — map your route",
        what:
          "A cable-car option in Idaho Springs. Check the operator's current " +
          "opening status, hours and ticket information before traveling.",
      },
      {
        name: "Dillon Reservoir — Frisco and Silverthorne",
        maps: [
          { label: "Open in Maps", query: "Dillon Reservoir, Colorado" },
        ],
        drive: "Frisco and Silverthorne — map your route",
        what:
          "Explore the reservoir's path network from a starting point that suits " +
          "your plans. Check the route, distance and conditions before setting out.",
      },
    ],
  },
  {
    id: "band-3",
    elevation: "Parks and foothill towns",
    when: "Check from September; do not wait for late October",
    note: "These places span different elevations. A date that works for one may be late for another.",
    spots: [
      {
        name: "Golden Gate Canyon State Park",
        maps: [
          { label: "Open in Maps", query: "Golden Gate Canyon State Park, Colorado" },
        ],
        drive: "Northwest of Golden",
        what:
          "Mountain trails and aspen groves northwest of Golden. Start checking " +
          "conditions in September; do not assume color will remain through late October.",
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
          "Explore the historic town and nearby routes. Check road conditions " +
          "and vehicle suitability before considering Oh My God Road.",
      },
    ],
  },
  {
    id: "band-4",
    elevation: "Denver parks and trails",
    when: "Often October; weather dependent",
    note: "Look for local color too, without assuming it will last a fixed number of weeks.",
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
          "Choose a segment of the creek or river trail network. Check the route " +
          "length, access points and any closures before leaving.",
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
          "Three city-park options for a local outing. Choose a route from your " +
          "neighborhood and check current conditions.",
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
