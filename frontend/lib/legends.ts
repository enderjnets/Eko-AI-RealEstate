/**
 * The 3D legends: one page per video, opened by the short path the video says
 * out loud (`/colfax`, `/cheesman`, `/mollybrown` in `next.config.js`).
 *
 * Asked for on 11-oct-2026. Until then every short path landed on `/start` —
 * "Buy / Sell / Talk now" — and the owner, opening `/mollybrown` on his phone
 * the way a viewer would, said what a viewer would think: the video invites to
 * something else. Someone who typed an address after a story about Molly Brown
 * expects more of that story, not a menu. So each page continues the video: the
 * legend, what the records say with a source for every line, the public-domain
 * photographs, and only then the same three ways in that `/start` offers.
 *
 * Every fact here was checked against two sources when the video was scripted
 * (the `fuentes.md` beside each production); a fact that rests on one source
 * names it in the text ("the museum says", "her biographer found"). Photographs
 * are public domain or CC BY only, credited as their licence asks.
 *
 * Fair Housing: these are a street, a park and a museum. Nothing here describes
 * a neighbourhood, its homes or its residents, and nothing calls a place
 * haunted or unsafe — `legends.test.ts` reads every string for those words.
 */

export interface LegendSource {
  name: string;
  url: string;
}

export interface LegendFact {
  /** The story people tell, when the fact answers one. */
  legend?: string;
  /** What the records say. */
  record: string;
  sources: LegendSource[];
}

export type LegendLicence = "Public domain" | "CC0" | "CC BY 2.0" | "CC BY 4.0";

export interface LegendPhoto {
  src: string;
  alt: string;
  caption: string;
  credit: string;
  licence: LegendLicence;
  page: string;
}

export interface LegendWatch {
  network: "YouTube" | "Instagram" | "TikTok";
  url: string;
}

export interface Legend {
  slug: string;
  eyebrow: string;
  title: string;
  dek: string;
  hero: { src: string; alt: string };
  facts: LegendFact[];
  photos: LegendPhoto[];
  watch: LegendWatch[];
  visit?: { label: string; url: string };
}

const MODEL_NOTE =
  "The flyover in the video is a 3D model, not drone footage: USGS 3DEP lidar, USDA NAIP aerial imagery and " +
  "building footprints from OpenStreetMap (© OpenStreetMap contributors, ODbL). Narrated with a synthetic voice.";

export const LEGEND_MODEL_NOTE = MODEL_NOTE;

export const LEGENDS: readonly Legend[] = [
  {
    slug: "colfax",
    eyebrow: "Denver, decoded · Colfax Avenue",
    title: "The street Playboy never named",
    dek: "Everyone in Denver can quote what Playboy said about Colfax. Nobody can find it.",
    hero: { src: "/landing/legends/colfax/hero.jpg", alt: "3D model of Colfax Avenue running west through Denver toward the mountains" },
    facts: [
      {
        legend: "Playboy called Colfax “the longest, wickedest street in America.”",
        record:
          "In 2017 a Denverite reporter paid for Playboy's searchable archive, every page it ever printed, and found no such line. The Denver Public Library's researchers gave up too.",
        sources: [{ name: "Denverite, 6 Oct 2017", url: "https://denverite.com/2017/10/06/playboy-never-said-colfax-longest-wickedest-street-america/" }],
      },
      {
        record: "What Playboy did print, in 1977, was a writer calling Denver “Omaha with mountains.”",
        sources: [{ name: "Denverite, 6 Oct 2017", url: "https://denverite.com/2017/10/06/playboy-never-said-colfax-longest-wickedest-street-america/" }],
      },
      {
        record: "The road is older than its name: by 1859 it was already the wagon road to the gold camps at Golden.",
        sources: [{ name: "Wikipedia, Colfax Avenue", url: "https://en.wikipedia.org/wiki/Colfax_Avenue" }],
      },
      {
        record:
          "In 1868 Denver named it for Schuyler Colfax, Speaker of the House, likely hoping he would back Colorado for statehood. He became Vice President the next year.",
        sources: [{ name: "Denver Public Library, East Colfax Avenue", url: "https://history.denverlibrary.org/" }],
      },
      {
        record:
          "In the 1920s it became U.S. Route 40, and the neon came with the motels and diners built for drivers. In the 1960s, Interstate 70 let the traffic go around it.",
        sources: [{ name: "Denver Public Library, East Colfax Avenue", url: "https://history.denverlibrary.org/" }],
      },
    ],
    photos: [
      {
        src: "/landing/legends/colfax/schuyler-colfax.jpg",
        alt: "Portrait of Schuyler Colfax",
        caption: "Schuyler Colfax, the Speaker the street was named for.",
        credit: "Mathew Brady",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Schuyler_Colfax_portrait.jpg",
      },
      {
        src: "/landing/legends/colfax/heart-o-denver-1975.jpg",
        alt: "The Heart o' Denver Motor Hotel sign on Colfax in 1975",
        caption: "Route 40 neon: the Heart o' Denver Motor Hotel, 1975.",
        credit: "Dennis Harper",
        licence: "CC BY 2.0",
        page: "https://commons.wikimedia.org/wiki/File:Heart_o%27_Denver_Motor_Hotel_-_Aug_1975.jpg",
      },
      {
        src: "/landing/legends/colfax/car-wash-2004.jpg",
        alt: "A car wash sign on Colfax Avenue in 2004",
        caption: "Car wash, Colfax Avenue (Route 40), 2004.",
        credit: "John Margolies, Library of Congress",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Car_wash,_Colfax_Avenue_(Route_40),_Denver,_Colorado_LCCN2017704211.tif",
      },
    ],
    watch: [
      { network: "YouTube", url: "https://www.youtube.com/shorts/KcVhEt3zKEQ" },
      { network: "Instagram", url: "https://www.instagram.com/reel/DeXMuJaiLvs/" },
      { network: "TikTok", url: "https://tiktok.com/@denverhomestory/video/7695556592770632973" },
    ],
  },
  {
    slug: "cheesman",
    eyebrow: "Denver, decoded · Cheesman Park",
    title: "The park on top of a cemetery",
    dek: "One of Denver's most beautiful parks was a burial ground, and not all the graves were moved.",
    hero: { src: "/landing/legends/cheesman/hero.jpg", alt: "3D model of the marble pavilion in Cheesman Park" },
    facts: [
      {
        record: "In 1859 William Larimer staked out this hill as Denver's burial ground.",
        sources: [{ name: "Colorado Encyclopedia, Cheesman Park", url: "https://coloradoencyclopedia.org/article/cheesman-park" }],
      },
      {
        record:
          "By 1890 the city had grown around it and Congress made it park land. Families were told to move their dead; thousands never were.",
        sources: [
          { name: "Denver Public Library", url: "https://history.denverlibrary.org/news/denver/cheesman-parks-past-lifeas-cemetery" },
          { name: "Colorado Encyclopedia", url: "https://coloradoencyclopedia.org/article/cheesman-park" },
        ],
      },
      {
        legend: "The undertaker hired in 1893 cut bodies up to fill several coffins.",
        record:
          "The Denver Republican printed it. Rocky Mountain PBS calls that coverage politically motivated, and the Rocky Mountain News said the work was done by the book. The city stopped the work before every grave was moved.",
        sources: [
          { name: "Rocky Mountain PBS, Colorado Experience", url: "https://www.rmpbs.org/news/colorado-experience/colorado-experience-hidden-history-of-cheesman-park" },
          { name: "Denver Public Library", url: "https://history.denverlibrary.org/news/denver/cheesman-parks-past-lifeas-cemetery" },
        ],
      },
      {
        record:
          "Denver Parks and Recreation has said as many as 2,000 people may still be buried here. Several skeletons turned up in 2010, and an arm bone at the Botanic Gardens next door in 2022.",
        sources: [
          { name: "CNN, 2010", url: "https://www.cnn.com/2010/US/11/18/denver.park.cemetery/index.html" },
          { name: "KRDO, 2022", url: "https://krdo.com/news/2022/03/29/human-remains-uncovered-at-botanic-gardens/" },
        ],
      },
      {
        record: "The marble pavilion was paid for by Walter Cheesman's family, and the park took his name.",
        sources: [
          { name: "Denver Public Library", url: "https://history.denverlibrary.org/news/denver/cheesman-parks-past-lifeas-cemetery" },
          { name: "Colorado Encyclopedia", url: "https://coloradoencyclopedia.org/article/cheesman-park" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/cheesman/pavilion-2015.jpg",
        alt: "The marble pavilion in Cheesman Park",
        caption: "The pavilion in Cheesman Park, 2015.",
        credit: "Carol M. Highsmith, Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/item/2015633573/",
      },
      {
        src: "/landing/legends/cheesman/park-map.jpg",
        alt: "Hand-drawn map of historical points of interest in Cheesman Park",
        caption: "Hand-drawn map of the park's history.",
        credit: "Denver Public Library, via DPLA",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Hand_drawn_map_of_historical_points_of_interest_in_Cheesman_Park_-_DPLA_-_434916f81a66bd76e192e2c12779f887.jpg",
      },
      {
        src: "/landing/legends/cheesman/calvary-map.jpg",
        alt: "Map of Cheesman Park and Mount Calvary Cemetery",
        caption: "The park and Mount Calvary Cemetery, where the Botanic Gardens are now.",
        credit: "Denver Parks and Recreation / Denver Public Library, via DPLA",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Map_of_Cheesman_Park_and_Mt._Calvary_Cemetery_-_DPLA_-_116461882262f6e96c7df0b624af5cdc.jpg",
      },
    ],
    watch: [{ network: "Instagram", url: "https://www.instagram.com/reel/DeX80WZDNZh/" }],
  },
  {
    slug: "mollybrown",
    eyebrow: "Denver, decoded · 1340 Pennsylvania Street",
    title: "The Molly Brown House",
    dek: "The Unsinkable Molly Brown never went by Molly. Here's what the records say.",
    hero: { src: "/landing/legends/mollybrown/hero.jpg", alt: "3D model of the Molly Brown House seen from Pennsylvania Street" },
    facts: [
      {
        legend: "Her name was Molly.",
        record:
          "In life she was Maggie, then Margaret, then Mrs. J.J. Brown. “Molly” took off after her death, with Gene Fowler's 1933 book and then the 1960 Broadway musical.",
        sources: [
          { name: "Molly Brown House Museum", url: "https://mollybrown.org/many-myths-molly-brown/" },
          { name: "Boston Globe, 2012", url: "https://www.bostonglobe.com/arts/2012/03/26/denver-museum-tries-sink-myths-about-molly-brown/4VcVy8AbU3yB76eJt36iAP/story.html" },
        ],
      },
      {
        legend: "She burned the family fortune in a stove.",
        record:
          "That's a scene from the 1964 movie. The museum in her house says she kept coins in the stove, but never burned a fortune.",
        sources: [{ name: "Molly Brown House Museum", url: "https://mollybrown.org/many-myths-molly-brown/" }],
      },
      {
        legend: "Denver society shut her out.",
        record:
          "Her biographer, Kristen Iversen, found that the Browns took up more space in Denver's society pages than nearly any other family.",
        sources: [{ name: "Molly Brown House Museum, citing Iversen", url: "https://mollybrown.org/the-denver-years/" }],
      },
      {
        record:
          "April 1912, the Titanic, lifeboat No. 6: the women rowed, and she pressed the crewman in charge to go back for people in the water. He refused.",
        sources: [
          { name: "Wikipedia, Margaret Brown", url: "https://en.wikipedia.org/wiki/Margaret_Brown" },
          { name: "Mental Floss", url: "https://www.mentalfloss.com/history/titanic/molly-brown-titanic-facts" },
        ],
      },
      {
        legend: "She called herself unsinkable.",
        record: "That was the newspapers' word. There's no proof she ever used it about herself.",
        sources: [{ name: "Boston Globe, 2012", url: "https://www.bostonglobe.com/arts/2012/03/26/denver-museum-tries-sink-myths-about-molly-brown/4VcVy8AbU3yB76eJt36iAP/story.html" }],
      },
      {
        record:
          "After she died in 1932 the house was cut up into rooms for boarders, and by 1970 it faced demolition. A group of Denverites formed Historic Denver to save it. Today it's a museum.",
        sources: [
          { name: "Molly Brown House Museum", url: "https://mollybrown.org/about-molly-brown-house-museum/" },
          { name: "National Park Service", url: "https://www.nps.gov/places/molly-brown-house.htm" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/mollybrown/house-2015.jpg",
        alt: "The front of the Molly Brown House on Pennsylvania Street",
        caption: "The Molly Brown House, 2015.",
        credit: "Carol M. Highsmith, Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/item/2015633624/",
      },
      {
        src: "/landing/legends/mollybrown/margaret-brown.jpg",
        alt: "Portrait of Margaret Brown standing beside a chair",
        caption: "Margaret Brown.",
        credit: "Bain News Service, Library of Congress",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Margaret_Brown,_3qtr_view,_with_chair.jpg",
      },
      {
        src: "/landing/legends/mollybrown/rostron-1912.jpg",
        alt: "Margaret Brown presenting a cup to Captain Arthur Rostron in 1912",
        caption: "1912: presenting a cup to Captain Rostron of the Carpathia, the ship that rescued the survivors.",
        credit: "Bain News Service, Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/item/98509447/",
      },
    ],
    watch: [],
    visit: { label: "Visit the Molly Brown House Museum", url: "https://mollybrown.org/" },
  },
];

export function legendBySlug(slug: string): Legend | undefined {
  return LEGENDS.find((l) => l.slug === slug);
}
