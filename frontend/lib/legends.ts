/**
 * The 3D legends: one page per video, opened by the short path the video says
 * out loud (`/colfax`, `/cheesman`, `/mollybrown`, `/unionstation`, `/georgetownloop`, `/confluencepark`, `/redrocks`, `/mint`, `/gateway`, `/abasin`, `/arsenal`, `/hotels`, `/adx`, `/cheyenne`, `/brownpalace`, `/sloanslake`, `/dia`, `/lookout`, `/mountfalcon` in `next.config.js`).
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
  "building footprints from OpenStreetMap (© OpenStreetMap contributors, ODbL) or the DRCOG Regional Data Catalog " +
  "(CC BY 3.0). Narrated with a synthetic voice.";

export const LEGEND_MODEL_NOTE = MODEL_NOTE;

/**
 * Whether search engines and AI assistants are invited to index the legend
 * pages and their index. ONE switch, read by the pages' `robots`, by the
 * sitemap and by `/llms.txt`, so the three can never disagree (the Journal's
 * `INDEXED` rule). On since 13-oct-2026, with the owner's yes, knowing the
 * cost: linking is reversible in a deploy, an index entry is not — Google's
 * removal tool hides a page for about six months.
 */
export const LEGENDS_INDEXED = true;

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
  {
    slug: "unionstation",
    eyebrow: "Denver, decoded · 17th & Wynkoop",
    title: "Union Station and the Mizpah Arch",
    dek: "Denver once greeted every train with a giant glowing arch. The word on its back still fools people.",
    hero: { src: "/landing/legends/unionstation/hero.jpg", alt: "3D model of Denver Union Station and the rebuilt 1906 arch on 17th Street" },
    facts: [
      {
        record: "Union Station opened in 1881. Its two wings, built of volcanic stone, are still the originals.",
        sources: [
          { name: "History Colorado", url: "https://www.historycolorado.org/story/classroom-resources/2019/04/05/6-things-you-didnt-know-about-union-station" },
          { name: "Lower Downtown District", url: "https://lodo.org/union-station-history/" },
        ],
      },
      {
        record: "In 1894 a fire that started in the ladies' room destroyed the middle of the station. The grand hall you walk through today opened in 1914.",
        sources: [
          { name: "History Colorado", url: "https://www.historycolorado.org/story/classroom-resources/2019/04/05/6-things-you-didnt-know-about-union-station" },
          { name: "Denver Union Station, Our History", url: "https://www.denverunionstation.com/about/our-history/" },
        ],
      },
      {
        record:
          "In 1906 the city built an arch over 17th Street in front of the station: sixty-five feet tall, lit with more than two thousand bulbs. It said “Welcome,” and soon the side travelers saw on their way out got a new word: Mizpah.",
        sources: [
          { name: "Lower Downtown District", url: "https://lodo.org/union-station-history/" },
          { name: "Wikipedia, Denver Union Station", url: "https://en.wikipedia.org/wiki/Denver_Union_Station" },
        ],
      },
      {
        legend: "Mizpah is a Native American word for “Howdy, partner.”",
        record:
          "It's Hebrew, for watchtower. In Genesis it's the pile of stones Jacob and Laban set up when they parted: a watchtower between two people who are apart.",
        sources: [
          { name: "Lower Downtown District", url: "https://lodo.org/union-station-history/" },
          { name: "Wikipedia, Mizpah", url: "https://en.wikipedia.org/wiki/Mizpah_(emotional_bond)" },
        ],
      },
      {
        record: "In the early 1930s, with traffic growing, the arch came down.",
        sources: [
          { name: "Wikipedia, Denver Union Station", url: "https://en.wikipedia.org/wiki/Denver_Union_Station" },
          { name: "History Colorado", url: "https://www.historycolorado.org/story/classroom-resources/2019/04/05/6-things-you-didnt-know-about-union-station" },
        ],
      },
      {
        record:
          "In the 1950s, as travelers moved to cars and planes, the station put up its “Travel by Train” signs. Today the trains are back, and there's a hotel upstairs.",
        sources: [
          { name: "History Colorado", url: "https://www.historycolorado.org/story/classroom-resources/2019/04/05/6-things-you-didnt-know-about-union-station" },
          { name: "Wikipedia, Denver Union Station", url: "https://en.wikipedia.org/wiki/Denver_Union_Station" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/unionstation/welcome-arch-1908.jpg",
        alt: "The Welcome Arch over 17th Street in 1908",
        caption: "The arch in 1908, its Welcome side towards the station.",
        credit: "Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/item/93505882/",
      },
      {
        src: "/landing/legends/unionstation/union-depot-postcard.jpg",
        alt: "Postcard of Union Depot with its clock tower and the train yard",
        caption: "Union Depot before the 1914 hall, with its clock tower.",
        credit: "Detroit Publishing Co., New York Public Library",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Union_Depot,_Denver,_Colo_(NYPL_b12647398-68814).tiff",
      },
      {
        src: "/landing/legends/unionstation/union-station-2016.jpg",
        alt: "Union Station at dusk with its Union Station and Travel by Train signs lit",
        caption: "The station at dusk, 2016.",
        credit: "Carol M. Highsmith, Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/item/2017885046/",
      },
    ],
    watch: [],
    visit: { label: "Denver Union Station", url: "https://www.denverunionstation.com/" },
  },
  {
    slug: "georgetownloop",
    eyebrow: "Denver, decoded · Clear Creek, west of Denver",
    title: "The Georgetown Loop, the railroad to nowhere",
    dek: "This railroad crosses over itself to go two miles. Its name promised two places it never reached.",
    hero: {
      src: "/landing/legends/georgetownloop/hero.jpg",
      alt: "3D model of the Georgetown Loop with its route marked in gold, crossing over itself at the Devil's Gate High Bridge",
    },
    facts: [
      {
        record:
          "Silver Plume sits two miles from Georgetown and about six hundred feet higher. Laid straight up the valley, the track would have climbed a six percent grade: too steep.",
        sources: [
          { name: "Colorado Encyclopedia, Georgetown Loop", url: "https://coloradoencyclopedia.org/article/georgetown-loop" },
          { name: "Trains magazine, Colorado's Georgetown Loop", url: "https://www.trains.com/?p=18950" },
        ],
      },
      {
        record:
          "Union Pacific engineers curled the line into about four and a half miles, roughly halving the grade. At the Devil's Gate High Bridge, ninety-five feet above Clear Creek, the track crosses over itself. Trains reached Silver Plume in 1884.",
        sources: [
          { name: "Wikipedia, Georgetown Loop Railroad", url: "https://en.wikipedia.org/wiki/Georgetown_Loop_Railroad" },
          { name: "Georgetown Loop Railroad, Our History", url: "https://www.georgetownlooprr.com/our-history/" },
        ],
      },
      {
        legend: "It was built as a scenic ride.",
        record:
          "It was the Georgetown, Breckenridge and Leadville, built to haul silver ore and push over the mountains to Leadville. Other railroads got there first; the track stopped a few miles past Silver Plume and never reached Breckenridge either. One history calls it Colorado's railroad to nowhere.",
        sources: [
          { name: "National Register of Historic Places nomination, 1970", url: "https://npgallery.nps.gov/GetAsset/769d12ec-421c-4ee2-8290-a02e692013cd" },
          { name: "Colorado Encyclopedia, Georgetown Loop", url: "https://coloradoencyclopedia.org/article/georgetown-loop" },
        ],
      },
      {
        record: "Instead of Leadville, it found tourists. The Loop became one of Colorado's first great attractions.",
        sources: [
          { name: "National Register of Historic Places nomination, 1970", url: "https://npgallery.nps.gov/GetAsset/769d12ec-421c-4ee2-8290-a02e692013cd" },
          { name: "Wikipedia, Georgetown Loop Railroad", url: "https://en.wikipedia.org/wiki/Georgetown_Loop_Railroad" },
        ],
      },
      {
        record:
          "By 1939 the line was torn up and the bridge sold off. Interstate 70 was later built higher up the mountain to spare the old grade, and in 1984 the Colorado Historical Society finished rebuilding the Loop, with a new bridge to the old design.",
        sources: [
          { name: "Colorado Encyclopedia, Georgetown Loop", url: "https://coloradoencyclopedia.org/article/georgetown-loop" },
          { name: "History Colorado, National and State Register", url: "https://www.historycolorado.org/location/georgetown-loop-railroadr-georgetown-loop-historic-mining-railroad-parkr" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/georgetownloop/loop-photochrom.jpg",
        alt: "Colour photochrom of the Georgetown Loop: a train on the high bridge and another on the track below",
        caption: "The Loop with a train on the bridge and another below it.",
        credit: "William Henry Jackson / Detroit Photographic Co., Beinecke Library, Yale",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Detroit_Photographic_Company_(0239).jpg",
      },
      {
        src: "/landing/legends/georgetownloop/high-bridge-postcard-1904.jpg",
        alt: "Postcard of the High Bridge with a passenger train crossing and another train on the track beneath it",
        caption: "The High Bridge on a 1904 postcard: one train over another.",
        credit: "Detroit Photographic Co., New York Public Library",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Loop_High_Bridge,_Georgetown,_Colo_(NYPL_b12647398-62949).tiff",
      },
      {
        src: "/landing/legends/georgetownloop/rebuilt-bridge-2002.jpg",
        alt: "A steam locomotive and red coaches crossing the rebuilt Devil's Gate High Bridge",
        caption: "The rebuilt bridge, 2002.",
        credit: "Don O'Brien",
        licence: "CC BY 2.0",
        page: "https://commons.wikimedia.org/wiki/File:Georgetown_Loop_RR.jpg",
      },
    ],
    watch: [],
    visit: { label: "Georgetown Loop Railroad", url: "https://www.georgetownlooprr.com/" },
  },
  {
    slug: "confluencepark",
    eyebrow: "Denver, decoded · Where Cherry Creek meets the South Platte",
    title: "Confluence Park, and the barrel of whiskey",
    dek: "They say Denver was bought with a barrel of whiskey. The records tell it differently.",
    hero: {
      src: "/landing/legends/confluencepark/hero.jpg",
      alt: "3D model of Confluence Park with Cherry Creek marked in gold and the South Platte in blue where they meet",
    },
    facts: [
      {
        record:
          "Cherry Creek meets the South Platte here, and Denver started here. Under the 1851 Fort Laramie Treaty, this was Cheyenne and Arapaho land.",
        sources: [
          { name: "The Cultural Landscape Foundation, Confluence Park", url: "https://www.tclf.org/landscapes/confluence-park" },
          { name: "National Park Service, Sand Creek Massacre NHS timeline", url: "https://home.nps.gov/sand/learn/timeline.htm" },
        ],
      },
      {
        record:
          "In 1858 Georgia prospectors found gold up the river. That fall, Kansas men staked a town on the east bank of Cherry Creek, St. Charles, and most of them went home for the winter. Across the creek, miners laid out Auraria.",
        sources: [
          { name: "Colorado Encyclopedia, William Larimer Jr.", url: "https://coloradoencyclopedia.org/article/william-larimer-jr" },
          { name: "Jerome C. Smiley, Semi-Centennial History of the State of Colorado (1913)", url: "https://archive.org/details/semicentennialhi01smil" },
        ],
      },
      {
        legend: "Larimer's men won the claim with a barrel of whiskey and the threat of a hanging.",
        record:
          "In November 1858, William Larimer's party moved in. Charles Nichols, for the St. Charles men, protested and was warned: next time, a rope. Then he made a deal, and the St. Charles men got shares in the Denver City company. Jumped, then bought off.",
        sources: [
          { name: "Jerome C. Smiley, Semi-Centennial History of the State of Colorado (1913)", url: "https://archive.org/details/semicentennialhi01smil" },
          { name: "Reminiscences of General William Larimer (1918)", url: "https://archive.org/details/reminiscencesofg00lari" },
        ],
      },
      {
        record:
          "Barrels of whiskey did come, at Christmas 1858. Uncle Dick Wootton rolled in with Taos Lightning, opened one, and invited the whole camp to help themselves.",
        sources: [
          { name: "Jerome C. Smiley, History of Denver (1901), chapter 23", url: "https://cogenweb.org/denver/1901_History/chap23.html" },
          { name: "Reminiscences of General William Larimer (1918)", url: "https://archive.org/details/reminiscencesofg00lari" },
        ],
      },
      {
        record:
          "In April 1860 the two towns voted to merge, and celebrated by moonlight on the Larimer Street bridge.",
        sources: [
          { name: "History of the City of Denver (1880)", url: "https://archive.org/details/historyofcityofd00inolba" },
          { name: "Jerome C. Smiley, Semi-Centennial History of the State of Colorado (1913)", url: "https://archive.org/details/semicentennialhi01smil" },
        ],
      },
      {
        record: "After the South Platte flood of 1965, the old dumping ground at the confluence became a park.",
        sources: [
          { name: "The Cultural Landscape Foundation, Confluence Park", url: "https://www.tclf.org/landscapes/confluence-park" },
          { name: "The Greenway Foundation, history", url: "https://thegreenwayfoundation.org/about/history/" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/confluencepark/denver-city-leslies-1859.jpg",
        alt: "Wood engraving of Denver City in 1859: a row of log cabins and a wagon on the open plain",
        caption: "\u201cDenver City, K.T.\u201d in Frank Leslie\u2019s Illustrated Newspaper, August 1859.",
        credit: "Frank Leslie\u2019s Illustrated Newspaper, Library of Congress",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Three_illustrations-_Denver_City,_K.T.;_The_Rocky_Mountain_News_Office,_Aurabia,_K.T.;_View_at_Pike's_Peak_LCCN98505273.tif",
      },
      {
        src: "/landing/legends/confluencepark/denver-1859-lithograph-1891.jpg",
        alt: "Colour lithograph of the camps where Cherry Creek runs into the South Platte, with wagons, tents and the mountains behind",
        caption: "Denver in 1859, as an 1891 lithograph imagined it.",
        credit: "Collier & Cleveland Litho Co., Library of Congress",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Denver_in_1859_LCCN2003674703.jpg",
      },
      {
        src: "/landing/legends/confluencepark/confluence-2005.jpg",
        alt: "The sand spit and boulders where Cherry Creek and the South Platte meet, with a bridge behind",
        caption: "Where the two rivers meet, 2005.",
        credit: "Robin DeGrassi",
        licence: "CC BY 2.0",
        page: "https://commons.wikimedia.org/wiki/File:Platte-Cherry.jpg",
      },
    ],
    watch: [],
  },
  {
    slug: "redrocks",
    eyebrow: "Denver, decoded · Red Rocks Park, a Denver Mountain Park",
    title: "Red Rocks, and the Beatles show that didn't sell out",
    dek: "They say the Beatles couldn't sell out Red Rocks. Seven thousand tickets sold; nearly ten thousand fans, by one estimate.",
    hero: {
      src: "/landing/legends/redrocks/hero.jpg",
      alt: "3D model of Red Rocks Amphitheatre between Ship Rock and Creation Rock, with the rock faces shown in red",
    },
    facts: [
      {
        record:
          "Red Rocks Amphitheatre sits between two sandstone monoliths: Ship Rock to the south and Creation Rock to the north. Denver bought the park by 1928.",
        sources: [
          { name: "Red Rocks Amphitheatre, history", url: "https://www.redrocksonline.com/our-story/history/" },
          { name: "History Colorado, Red Rocks Park and Mount Morrison CCC Camp", url: "https://www.historycolorado.org/location/red-rocks-park-and-mount-morrison-civilian-conservation-corps-camp-national-historic" },
        ],
      },
      {
        record:
          "From 1936 the Civilian Conservation Corps built the amphitheatre to a design by Denver architect Burnham Hoyt. It opened in June 1941.",
        sources: [
          { name: "Colorado Encyclopedia, Red Rocks Park and Amphitheatre", url: "https://coloradoencyclopedia.org/article/red-rocks-park-and-amphitheatre" },
          { name: "The Cultural Landscape Foundation, Red Rocks Amphitheatre", url: "https://tclf.org/landscapes/red-rocks-amphitheatre" },
        ],
      },
      {
        legend: "The Beatles couldn't sell out Red Rocks: the one show of their American tour that didn't.",
        record:
          "On August 26, 1964, the Beatles played here. About 7,000 tickets were sold, at $6.60, for about 9,000 seats. That is a ticket count, and the press at the time blamed the location: no public transportation for teenagers.",
        sources: [
          { name: "Red Rocks Amphitheatre, notable performances", url: "https://www.redrocksonline.com/our-story/notable-performances/" },
          { name: "CPR, The Beatles at Red Rocks, 50 years on (2014)", url: "https://www.cpr.org/2014/08/25/the-beatles-at-red-rocks-50-years-on-still-a-big-deal/" },
        ],
      },
      {
        record:
          "An Associated Press photo caption said they played to nearly 10,000. There were hardly any ticket takers, fans came in over the rocks, and photos from that night show it packed. The tickets were reported; every crowd figure we found is an estimate.",
        sources: [
          { name: "Colorado Music Experience, The Beatles' Colorado connection", url: "https://colomusic.org/blog/the-beatles-colorado-connection/" },
          { name: "Broadcast Pioneers of Colorado, The Beatles in Denver", url: "https://broadcastpioneersofcolorado.com/the-beatles-in-denver/" },
        ],
      },
      {
        record: "Nor was it the only show of the tour that fell short: Kansas City, an extra date, drew well below its stadium's capacity.",
        sources: [
          { name: "The Beatles Bible, Municipal Stadium, Kansas City", url: "https://www.beatlesbible.com/1964/09/17/live-municipal-stadium-kansas-city/" },
          { name: "Wikipedia, The Beatles' 1964 North American tour", url: "https://en.wikipedia.org/wiki/The_Beatles%27_1964_North_American_tour" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/redrocks/aerial-1938.jpg",
        alt: "Black-and-white aerial photograph of the amphitheatre under construction between the rocks, April 1938",
        caption: "The amphitheatre half built, April 1938.",
        credit: "U.S. Army Air Corps, National Archives",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Colorado_-_Rocky_Mountains_through_Red_Rocks_-_NARA_-_23936001.jpg",
      },
      {
        src: "/landing/legends/redrocks/aerial-1941.jpg",
        alt: "Black-and-white aerial photograph of the finished amphitheatre between the two monoliths, June 1941",
        caption: "Finished, a week before the June 1941 dedication.",
        credit: "Air Corps Technical School, Lowry Field, National Archives",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Colorado_-_Rocky_Mountains_through_Red_Rocks_-_NARA_-_23935999.jpg",
      },
      {
        src: "/landing/legends/redrocks/postcard-c1941.jpg",
        alt: "Colour linen postcard of the amphitheatre's rows of seats below a red sandstone monolith",
        caption: "\u201cRed Rocks Theatre\u201d on a postcard of the early 1940s.",
        credit: "Tichnor Bros. for Sanborn Souvenir Co.",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Red_Rock_Theatre,_Park_of_the_Red_Rocks,_Denver_Mountain_Parks,_Colorado_(7725170254).jpg",
      },
    ],
    watch: [],
    visit: { label: "Red Rocks Park & Amphitheatre", url: "https://www.redrocksonline.com/" },
  },
  {
    slug: "mint",
    eyebrow: "Denver, decoded · The U.S. Mint at Denver, West Colfax Avenue",
    title: "The Denver Mint, and a quarter of the nation's gold",
    dek: "They say a quarter of the nation's gold is in Denver. The Treasury's monthly report lists about one ounce in six.",
    hero: {
      src: "/landing/legends/mint/hero.jpg",
      alt: "3D model of the Denver Mint at Colfax and Cherokee: rusticated granite, arched windows and a red tile roof",
    },
    facts: [
      {
        record:
          "The U.S. Mint on West Colfax is faced with rusticated Colorado granite on its ground story and smoother ashlar above. It is modeled on the Palazzo Medici Riccardi in Florence, and it opened in 1904.",
        sources: [
          { name: "Colorado Encyclopedia, Denver Mint", url: "https://coloradoencyclopedia.org/article/denver-mint" },
          { name: "National Register of Historic Places nomination, Denver Mint (1971)", url: "https://npgallery.nps.gov/NRHP/GetAsset/NRHP/72000270_text" },
          { name: "History Colorado, Denver Mint", url: "https://www.historycolorado.org/location/denver-mint" },
        ],
      },
      {
        record:
          "Congress created a branch mint in Denver in 1862, to coin gold, and the government bought the private mint of Clark, Gruber & Co. to house it. For more than forty years it only tested gold and silver. The new building's machinery was first shown at the 1904 World's Fair in St. Louis, and the first coins came in February 1906.",
        sources: [
          { name: "Director of the Mint, Annual Report 1906 (FRASER)", url: "https://fraser.stlouisfed.org/files/docs/publications/usmint/usmint_1906_annual-report.pdf" },
          { name: "Colorado Encyclopedia, Denver Mint", url: "https://coloradoencyclopedia.org/article/denver-mint" },
        ],
      },
      {
        legend: "A quarter of the nation's gold is behind these walls.",
        record:
          "Stories about the Mint tour printed it in 2005 and in 2014, the second quoting the Mint's own press office, and a travel guide still does.",
        sources: [
          { name: "Westword, Child's Play: It's two for the money at the Denver Mint (2014)", url: "https://www.westword.com/?p=40648217" },
          { name: "The E-Sylum, excerpt of the Longmont Daily Times-Call (2005)", url: "https://coinbooks.org/esylum_v08n22a14.html" },
          { name: "Michelin Guide, Denver Mint (2026)", url: "https://www.viamichelin.com/maps/tourist-attractions/poi/denver-80202-bc095a2723e3" },
        ],
      },
      {
        record:
          "In 1934 the government moved gold inland, from San Francisco to Denver. The Mint calls it a third of the country's gold; the Director of the Mint's ledger for June 1935 shows Denver holding about four in ten of the ounces in the mints' hands.",
        sources: [
          { name: "Colorado Encyclopedia, Denver Mint", url: "https://coloradoencyclopedia.org/article/denver-mint" },
          { name: "Director of the Mint, Annual Report 1935 (FRASER)", url: "https://fraser.stlouisfed.org/files/docs/publications/usmint/usmint_1935_annual-report.pdf" },
        ],
      },
      {
        record:
          "Today the Treasury reports its gold every month, by location. Denver holds about 43.9 million fine troy ounces of 261.5 million, about one ounce in six. It is the same figure in every report we opened, back to May 2005, including the months those stories ran.",
        sources: [
          { name: "U.S. Treasury, Fiscal Data: Status Report of U.S. Government Gold Reserve", url: "https://fiscaldata.treasury.gov/datasets/status-report-government-gold-reserve/" },
          { name: "Bureau of the Fiscal Service, gold reports", url: "https://fiscal.treasury.gov/resources/gold-report/" },
        ],
      },
      {
        record: "And the coins in your change: Denver and Philadelphia make the ones for general circulation.",
        sources: [
          { name: "Colorado Encyclopedia, Denver Mint", url: "https://coloradoencyclopedia.org/article/denver-mint" },
          { name: "U.S. Mint, production and sales figures", url: "https://www.usmint.gov/about/production-sales-figures" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/mint/palazzo-medici-riccardi.jpg",
        alt: "Sepia photograph of the corner of the Palazzo Medici Riccardi in Florence: rusticated stone, arched paired windows and a deep cornice",
        caption: "The Palazzo Medici Riccardi in Florence, the building the Mint is modeled on.",
        credit: "Fratelli Alinari, c. 1865\u20131900, Rijksmuseum",
        licence: "CC0",
        page: "https://commons.wikimedia.org/wiki/File:Gezicht_op_het_Palazzo_Riccardi_te_Florence,_RP-F-2006-18-39.jpg",
      },
      {
        src: "/landing/legends/mint/mint-c1906.jpg",
        alt: "Black-and-white photograph of the new Denver Mint at a dirt street corner, about 1906",
        caption: "The new Mint at Colfax and Cherokee, about 1906, the year its first coins came.",
        credit: "Detroit Publishing Co., Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/pictures/item/2016805898/",
      },
      {
        src: "/landing/legends/mint/branch-mint-c1865.jpg",
        alt: "Sepia stereograph view of the old brick branch mint with a square tower, 1865 to 1870",
        caption: "The old branch mint, once Clark, Gruber & Co.'s, in the years it made no coins.",
        credit: "Stereograph, 1865\u201370, Library of Congress",
        licence: "Public domain",
        page: "https://www.loc.gov/pictures/item/2017651960/",
      },
    ],
    watch: [],
    visit: { label: "U.S. Mint at Denver, tours", url: "https://www.usmint.gov/about/tours-and-locations/denver" },
  },
  {
    slug: "gateway",
    eyebrow: "Colorado, decoded · Highway 141 and Unaweep Canyon, Mesa County",
    title: "The road that only leads to one hotel",
    dek: "They say the best road on the planet only leads to one hotel. The highway runs on for 130 miles, and the canyon it climbs is the real story.",
    hero: {
      src: "/landing/legends/gateway/hero.jpg",
      alt: "3D model of Gateway, Colorado: Gateway Canyons Resort in the green valley of the Dolores River below the red sandstone butte of The Palisade",
    },
    facts: [
      {
        record:
          "Colorado Highway 141 leaves US 50 at Whitewater, southeast of Grand Junction, and climbs through Unaweep Canyon to Gateway, about 43 miles. With Highway 145 on to Placerville it is the Unaweep-Tabeguache Scenic and Historic Byway, one of Colorado's 26 state byways.",
        sources: [
          { name: "Bureau of Land Management, Unaweep/Tabeguache Scenic and Historic Byway", url: "https://www.blm.gov/visit/unaweep-tabeguache-2" },
          { name: "CDOT, Unaweep Tabeguache Scenic and Historic Byway", url: "https://www.codot.gov/travel/colorado-byways/southwest/unaweep-tabeguache" },
          { name: "CDOT, Online Transportation Information System (highway reference points)", url: "https://dtdapps.codot.gov/otis/HighwayData" },
        ],
      },
      {
        legend: "The best road on the planet: about 130 miles, state-maintained, and it only goes to one hotel.",
        record:
          "About 130 miles is right: measured along the two highways the byway is 130 miles, and BLM and CDOT publish 133. It does not stop at a hotel. It runs from Whitewater through Gateway, Naturita and Norwood to Placerville, and Highway 141 itself goes on south to US 491.",
        sources: [
          { name: "Bureau of Land Management, Unaweep/Tabeguache Scenic and Historic Byway", url: "https://www.blm.gov/visit/unaweep-tabeguache-2" },
          { name: "CDOT, Unaweep Tabeguache Scenic and Historic Byway", url: "https://www.codot.gov/travel/colorado-byways/southwest/unaweep-tabeguache" },
          { name: "FHWA, America's Byways record for the Unaweep/Tabeguache byway", url: "https://fhwaapps.fhwa.dot.gov/bywaysp/byway/2121" },
        ],
      },
      {
        record:
          "The hotel is real. John Hendricks, who founded the Discovery Channel in 1985, first came to Gateway in 1995 and opened Gateway Canyons Resort in 2005. Noble House Hotels & Resorts has managed it since 2011.",
        sources: [
          { name: "Gateway Canyons Resort, about the resort (founded 2005, first visit 1995)", url: "https://www.gatewaycanyons.com/llm-info/" },
          { name: "Gateway Canyons Resort, history and location", url: "https://www.gatewaycanyons.com/history-location/" },
          { name: "CNBC, Discovery Channel founder's Colorado ranch (2019)", url: "https://www.cnbc.com/2019/06/11/photos-discovery-channel-founders-multimillion-dollar-colorado-ranch.html" },
          { name: "Leisure Opportunities, Noble House takes over Gateway Canyons (2011)", url: "https://leisureopportunities.co.uk/news/Noble-House-takes-over-Gateway-Canyons/274893" },
        ],
      },
      {
        record:
          "In May 2019 the resort and West Creek Ranch were listed for $279 million, and in 2020 the listing was pulled while a buyer negotiated. That sale was never completed, The Daily Sentinel reported in July 2025, and the resort stayed with Western Sky Investments, which the paper says is owned by Hendricks. The Mesa County Assessor lists Western Sky Investments LLC as the owner of record.",
        sources: [
          { name: "The Daily Sentinel, Gateway Canyons for sale at $279 million (2019)", url: "https://www.gjsentinel.com/news/business/gateway-canyons-for-sale-at-279-million/article_08bd2476-7d19-11e9-acab-20677ce06c14.html" },
          { name: "The Daily Sentinel, Gateway Canyons Resort may have found a buyer (2020)", url: "https://www.gjsentinel.com/news/western_colorado/gateway-canyons-resort-may-have-found-a-buyer/article_c528811e-e942-11ea-bfc8-1f0969cfc696.html" },
          { name: "The Daily Sentinel, Discovery Channel founder's Gateway ranches for sale (2025)", url: "https://www.gjsentinel.com/news/discovery-channel-founders-gateway-ranches-for-sale/article_12011a44-cda9-48f7-bdfb-a49a8b703af5.html" },
          { name: "Mesa County Assessor, parcel report R098230", url: "https://emap.mesacounty.us/Assessor_Lookup/Assessor_Parcel_Report.aspx?Account=R098230" },
        ],
      },
      {
        legend: "No cars on it.",
        record:
          "CDOT estimates about 580 vehicles a day on Highway 141 through Unaweep Canyon, between Whitewater and Gateway (its 2025 estimate, last counted in 2018), and about 370 a day south of Gateway. Its byway page asks drivers to obey posted speed limit signs, and reminds them that livestock has the right-of-way.",
        sources: [
          { name: "CDOT, Online Transportation Information System, traffic data", url: "https://dtdapps.codot.gov/otis/TrafficData" },
          { name: "CDOT, Unaweep Tabeguache Scenic and Historic Byway", url: "https://www.codot.gov/travel/colorado-byways/southwest/unaweep-tabeguache" },
        ],
      },
      {
        record:
          "The canyon is the story. From the Unaweep Divide, about 7,000 feet up, East Creek flows northeast toward the Gunnison and West Creek southwest to the Dolores. The name is often translated as \u201ccanyon with two mouths.\u201d Surveying it in 1875 for the Hayden Survey, the geologist A. C. Peale wrote that some large stream must once have occupied it.",
        sources: [
          { name: "Hayden, Ninth Annual Report of the U.S. Geological and Geographical Survey, for 1875 (1877)", url: "https://archive.org/details/ninthannualrepor1875geol" },
          { name: "Henry Gannett, The Unaweep Ca\u00f1on, Popular Science Monthly (1882)", url: "https://en.wikisource.org/wiki/Popular_Science_Monthly/Volume_20/April_1882/The_Unaweep_Ca%C3%B1on" },
          { name: "Gateway Canyons Resort, history and location", url: "https://www.gatewaycanyons.com/history-location/" },
        ],
      },
      {
        record:
          "Geologists still argue how it formed. In one reading the ancestral Gunnison River cut it and abandoned it between 1.4 and 0.8 million years ago. In another, its inner gorge is a glacial valley about 300 million years old, buried and later dug out again.",
        sources: [
          { name: "Aslan et al., Abandonment of Unaweep Canyon, Geosphere (2014)", url: "https://pure.psu.edu/en/publications/abandonment-of-unaweep-canyon-14-08-ma-western-colorado-effects-o/" },
          { name: "Soreghan et al., Journal of Geology (2007), USGS record", url: "https://pubs.usgs.gov/publication/70031077" },
          { name: "Patterson et al., Geophysical Research Letters (2021)", url: "https://experts.umn.edu/en/publications/seismic-reflection-and-electrical-resistivity-imaging-support-pre/" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/gateway/palisade-dolores.jpg",
        alt: "The Dolores River curving past a gravel bar below The Palisade, a red sandstone butte, in winter",
        caption: "The Dolores River and The Palisade at Gateway, where West Creek comes out of Unaweep Canyon.",
        credit: "Jeffrey Beall, 2020, Wikimedia Commons",
        licence: "CC BY 4.0",
        page: "https://commons.wikimedia.org/wiki/File:Dolores_River_at_Gateway_Colorado.JPG",
      },
      {
        src: "/landing/legends/gateway/unaweep-divide-sign.jpg",
        alt: "Green highway sign reading Unaweep Divide, elevation 7048 feet, with arrows for West Creek and East Creek",
        caption: "The Unaweep Divide on Highway 141: West Creek one way, East Creek the other.",
        credit: "Jeffrey Beall, 2020, Wikimedia Commons",
        licence: "CC BY 4.0",
        page: "https://commons.wikimedia.org/wiki/File:Unaweep_Divide_sign.JPG",
      },
      {
        src: "/landing/legends/gateway/unaweep-canyon-1925.jpg",
        alt: "Black-and-white photograph of layered cliffs above brush at the east end of Unaweep Canyon, 1925",
        caption: "The east end of Unaweep Canyon in 1925, photographed for the U.S. Geological Survey.",
        credit: "W. T. Lee, 1925, USGS Photographic Library",
        licence: "Public domain",
        page: "https://www.sciencebase.gov/catalog/item/51dd76eae4b0f72b4471aa9c",
      },
    ],
    watch: [],
    visit: { label: "CDOT, Unaweep Tabeguache Scenic and Historic Byway", url: "https://www.codot.gov/travel/colorado-byways/southwest/unaweep-tabeguache" },
  },
  {
    slug: "abasin",
    eyebrow: "Colorado, decoded · Arapahoe Basin, Loveland Pass",
    title: "The highest ski area in North America?",
    dek: "They say Arapahoe Basin is the highest ski area in North America. A-Basin's own website says something more modest.",
    hero: {
      src: "/landing/legends/abasin/hero.jpg",
      alt: "3D model of Arapahoe Basin in winter: a snow-covered bowl below the Continental Divide ridge, with two chairlifts drawn in gold climbing to the top",
    },
    facts: [
      {
        record:
          "Arapahoe Basin sits off Loveland Pass, west of Denver, on the White River National Forest under a Forest Service special use permit. Larry Jump and Sandy Schauffler started it after World War II, and it opened in December 1946.",
        sources: [
          { name: "Arapahoe Basin, 2025 Master Development Plan", url: "https://www.arapahoebasin.com/uploaded/trailmaps/arapahoe%20basin%20final%202025%20master%20development%20planx.pdf" },
          { name: "U.S. Forest Service, White River National Forest, ski area prohibitions", url: "https://www.fs.usda.gov/r02/whiteriver/alerts/ski-area-prohibitions" },
          { name: "Arapahoe Basin, our history", url: "https://www.arapahoebasin.com/our-history/" },
        ],
      },
      {
        legend: "Arapahoe Basin is the highest ski area in North America.",
        record:
          "In 2007 NBC reported that A-Basin claims the highest skiable terrain in North America. Its website today says \u201csome of the highest terrain in North America.\u201d The 13,050 feet it advertises are above the lifts: its 2025 master plan says lift-serviced terrain extends to 12,470 feet, and USGS elevation data at the tops of its lifts reads 12,465 to 12,479 feet.",
        sources: [
          { name: "NBC News, America's highest lifts (Dec. 13, 2007)", url: "https://www.nbcnews.com/id/wbna22245326" },
          { name: "Arapahoe Basin, about", url: "https://www.arapahoebasin.com/about/" },
          { name: "Arapahoe Basin, 2025 Master Development Plan", url: "https://www.arapahoebasin.com/uploaded/trailmaps/arapahoe%20basin%20final%202025%20master%20development%20planx.pdf" },
          { name: "USGS, Elevation Point Query Service (3DEP)", url: "https://epqs.nationalmap.gov/v1/docs" },
        ],
      },
      {
        record:
          "The highest chairlift in North America is at Breckenridge Ski Resort, about sixteen miles southwest: the Imperial Express SuperChair, opened in 2005. Its top station is at 12,840 feet, and USGS elevation data gives the same figure for that spot.",
        sources: [
          { name: "Vail Resorts newsroom, North America's highest chairlift opens at Breckenridge (2016)", url: "https://news.vailresorts.com/2016-12-21-North-Americas-Highest-Chairlift-Opens-at-Breckenridge-Ski-Resort-Today" },
          { name: "Summit Daily, Imperial Express SuperChair opens (2021)", url: "https://www.summitdaily.com/news/breckenridge-ski-resort-opens-imperial-express-superchair/" },
          { name: "USGS, Elevation Point Query Service (3DEP)", url: "https://epqs.nationalmap.gov/v1/docs" },
        ],
      },
      {
        record:
          "Before it, Loveland's Lift 9, across Loveland Pass from A-Basin, reached 12,700 feet when it went in for the 1998\u201399 season; Loveland says it was the highest chair lift in the world at the time. USGS data reads 12,684 feet at its top.",
        sources: [
          { name: "Loveland Ski Area, history", url: "https://skiloveland.com/history/" },
          { name: "Loveland Ski Area, mountain stats", url: "https://skiloveland.com/the-mountain/trail-map-mountain-stats/" },
          { name: "USGS, Elevation Point Query Service (3DEP)", url: "https://epqs.nationalmap.gov/v1/docs" },
        ],
      },
      {
        record:
          "The ski area that does call itself the highest in North America is Silverton Mountain, in southwest Colorado, for a peak of 13,487 feet. Its one chairlift tops out at 12,300 feet by its own figure, lower than A-Basin's lifts.",
        sources: [
          { name: "Silverton Mountain, mountain stats", url: "https://silvertonmountain.com/mountain/stats/" },
        ],
      },
      {
        record:
          "So it depends on what you measure. The highest chairlift is Breckenridge's, the highest advertised peak is Silverton's, and A-Basin has, in its own words, some of the highest terrain in North America.",
        sources: [
          { name: "Arapahoe Basin, about", url: "https://www.arapahoebasin.com/about/" },
          { name: "Vail Resorts newsroom (2016)", url: "https://news.vailresorts.com/2016-12-21-North-Americas-Highest-Chairlift-Opens-at-Breckenridge-Ski-Resort-Today" },
          { name: "Silverton Mountain, mountain stats", url: "https://silvertonmountain.com/mountain/stats/" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/abasin/east-wall.jpg",
        alt: "Arapahoe Basin's East Wall and the ridge toward Lenawee Mountain under snow, with a chairlift line below",
        caption: "The East Wall at Arapahoe Basin, above the lifts.",
        credit: "Adam Ginsburg, 2005, Wikimedia Commons",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Eastwall.jpg",
      },
      {
        src: "/landing/legends/abasin/abasin-1961.jpg",
        alt: "Black-and-white photograph of two skiers seen from behind, looking up a snowy slope at Arapahoe Basin, 1961",
        caption: "Arapahoe Basin in February 1961, photographed for the U.S. Forest Service.",
        credit: "Charles E. Grover, U.S. Forest Service, National Archives",
        licence: "Public domain",
        page: "https://catalog.archives.gov/id/7016002",
      },
      {
        src: "/landing/legends/abasin/loveland-pass-sign.jpg",
        alt: "Brown sign reading Loveland Pass, elevation 11,990 feet, Continental Divide, against snowy peaks",
        caption: "Loveland Pass, between Loveland and Arapahoe Basin.",
        credit: "vxla, 2011, Flickr via Wikimedia Commons",
        licence: "CC BY 2.0",
        page: "https://commons.wikimedia.org/wiki/File:Loveland_Pass,_Elevation_11,990-feet.jpg",
      },
    ],
    watch: [],
    visit: { label: "Arapahoe Basin", url: "https://www.arapahoebasin.com/" },
  },
  {
    slug: "arsenal",
    eyebrow: "Denver, decoded · Rocky Mountain Arsenal",
    title: "Did a well make Denver shake?",
    dek: "They say a hole the Army drilled made Denver shake. The records say the legend holds, with a twist.",
    hero: {
      src: "/landing/legends/arsenal/hero.jpg",
      alt: "3D diagram of the ground under the Rocky Mountain Arsenal: the well drawn in gold down to 12,045 feet, and orange dots for the earthquakes located in 1967 and 1968",
    },
    facts: [
      {
        record:
          "The Rocky Mountain Arsenal is about 10 miles northeast of downtown Denver. In 1961 a deep disposal well was completed there for the U.S. Army: 12,045 feet, through the layered rock of the Denver Basin and into Precambrian crystalline rock, to get rid of liquid waste from chemical manufacturing at the Arsenal.",
        sources: [
          { name: "Healy, Rubey, Griggs & Raleigh, The Denver Earthquakes, Science (1968)", url: "https://earthquake.usgs.gov/static/lfs/research/induced/Healy-et-al-1968-Science-(New-York-NY).pdf" },
          { name: "USGS Circular 631 (Piper, 1969)", url: "https://pubs.usgs.gov/circ/1969/0631/report.pdf" },
          { name: "U.S. Army, Deep Injection Well fact sheet", url: "https://home.army.mil/carson/download_file/view/947ae991-39d6-41f7-8bc5-3e48ac632168/1916" },
        ],
      },
      {
        legend: "In the 1960s, a well at the Arsenal set off earthquakes in the Denver area.",
        record:
          "Injection began on March 8, 1962. Seven weeks later, on April 24, 1962, a newly installed seismograph recorded a magnitude 1.5 earthquake from the area northeast of Denver. Through August 1967, more than 1,500 were recorded.",
        sources: [
          { name: "USGS Open-File Report 66-60 (Healy and others, 1966)", url: "https://pubs.usgs.gov/of/1966/0060/report.pdf" },
          { name: "USGS Circular 631 (Piper, 1969)", url: "https://pubs.usgs.gov/circ/1969/0631/report.pdf" },
          { name: "Hsieh & Bredehoeft, Journal of Geophysical Research (1981)", url: "https://earthquake.usgs.gov/static/lfs/research/induced/Hsieh-Bredehoeft-1981-Journal-of-Geophysical-Research.pdf" },
        ],
      },
      {
        record:
          "In November 1965, Denver consulting geologist David Evans showed that the number of earthquakes tracked the volume of fluid injected into the well. The USGS began studies the next month, and injection stopped on February 20, 1966, after about 165 million gallons.",
        sources: [
          { name: "Healy, Rubey, Griggs & Raleigh, The Denver Earthquakes, Science (1968)", url: "https://earthquake.usgs.gov/static/lfs/research/induced/Healy-et-al-1968-Science-(New-York-NY).pdf" },
          { name: "USGS Open-File Report 66-60 (Healy and others, 1966)", url: "https://pubs.usgs.gov/of/1966/0060/report.pdf" },
          { name: "USGS Circular 631 (Piper, 1969)", url: "https://pubs.usgs.gov/circ/1969/0631/report.pdf" },
          { name: "Evans, The Denver Area Earthquakes and the Rocky Mountain Arsenal Disposal Well, The Mountain Geologist (1966), record", url: "https://www.osti.gov/biblio/6805542" },
        ],
      },
      {
        record:
          "The three largest earthquakes came more than a year later: April 10, August 9 and November 26, 1967. The strongest, on August 9, was about magnitude 5 (reported between 4.8 and 5.5 depending on the method) and was felt over at least 15,000 square miles. USGS scientists explained it: after injection stopped, the pressure kept spreading outward through the fractured rock, to cracks farther from the well.",
        sources: [
          { name: "USGS Open-File Report 82-64 (Spence, 1982)", url: "https://pubs.usgs.gov/of/1982/0064/report.pdf" },
          { name: "USGS Open-File Report 84-967, United States Earthquakes, 1967", url: "https://pubs.usgs.gov/of/1984/0967/report.pdf" },
          { name: "Healy, Rubey, Griggs & Raleigh, The Denver Earthquakes, Science (1968)", url: "https://earthquake.usgs.gov/static/lfs/research/induced/Healy-et-al-1968-Science-(New-York-NY).pdf" },
          { name: "Hsieh & Bredehoeft, Journal of Geophysical Research (1981)", url: "https://earthquake.usgs.gov/static/lfs/research/induced/Hsieh-Bredehoeft-1981-Journal-of-Geophysical-Research.pdf" },
        ],
      },
      {
        record:
          "The National Research Council calls it \u201cthe earliest and probably most familiar documented example of an induced seismic event related to fluid injection.\u201d It led to a USGS experiment at the Rangely oil field in western Colorado (1969\u201373): lowering the fluid pressure stopped the small earthquakes near the wells, and raising it brought them back.",
        sources: [
          { name: "National Research Council, Induced Seismicity Potential in Energy Technologies (2013)", url: "https://www.nationalacademies.org/read/13355/chapter/4" },
          { name: "Raleigh, Healy & Bredehoeft, An Experiment in Earthquake Control at Rangely, Colorado, Science (1976)", url: "https://earthquake.usgs.gov/static/lfs/research/induced/Raleigh-Healy-Bredehoeft-1976-Science-(New-York-NY).pdf" },
          { name: "USGS Open-File Report 82-64 (Spence, 1982)", url: "https://pubs.usgs.gov/of/1982/0064/report.pdf" },
        ],
      },
      {
        record:
          "The Army sealed the well in 1985. The Arsenal is now the Rocky Mountain Arsenal National Wildlife Refuge: 15,000 acres, established in 2004, with bison since 2007.",
        sources: [
          { name: "U.S. Army, Deep Injection Well fact sheet", url: "https://home.army.mil/carson/download_file/view/947ae991-39d6-41f7-8bc5-3e48ac632168/1916" },
          { name: "U.S. Fish and Wildlife Service, Rocky Mountain Arsenal National Wildlife Refuge, about us", url: "https://www.fws.gov/locations/rocky-mountain-arsenal-national-wildlife-refuge/about-us" },
          { name: "U.S. Fish and Wildlife Service, wild bison reintroduced to the Rocky Mountain Arsenal (2007)", url: "https://fws.gov/story/2007-03/us-fish-and-wildlife-service-and-partners-reintroduce-wild-bison-rocky-mountain" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/arsenal/bison-downtown.jpg",
        alt: "A bison standing in dry prairie grass, with more of the herd and the downtown Denver skyline and the mountains behind",
        caption: "Bison on the Rocky Mountain Arsenal refuge, with downtown Denver behind.",
        credit: "Linda Broeren, 2010, U.S. Fish and Wildlife Service, via Wikimedia Commons",
        licence: "CC BY 2.0",
        page: "https://commons.wikimedia.org/wiki/File:Bison_Framed_by_Downtown_(14900019530).jpg",
      },
      {
        src: "/landing/legends/arsenal/south-entrance-1960.jpg",
        alt: "Black-and-white photograph of a guard booth under a sign reading U.S. Army Chemical Arsenal, Rocky Mountain Arsenal, around 1960",
        caption: "The Arsenal's south entrance, around 1960.",
        credit: "U.S. Army, Library of Congress (Historic American Engineering Record), via Wikimedia Commons",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Rocky_Mountain_Arsenal_south_entrance.jpg",
      },
      {
        src: "/landing/legends/arsenal/usgs-cross-section-1966.jpg",
        alt: "USGS cross section from 1966: dots for earthquake hypocenters plotted below the Rocky Mountain Arsenal well, in Precambrian rock",
        caption: "The quakes under the well, as the USGS drew them in 1966.",
        credit: "U.S. Geological Survey, Open-File Report 66-60",
        licence: "Public domain",
        page: "https://pubs.usgs.gov/publication/ofr6660",
      },
      {
        src: "/landing/legends/arsenal/bison-front-range.jpg",
        alt: "A small herd of bison on the prairie with the Front Range in the haze behind",
        caption: "The refuge's bison herd, below the Front Range.",
        credit: "Cindy Souders, U.S. Fish and Wildlife Service, via Wikimedia Commons",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Bison_in_Front_of_the_Rocky_Mountains_(14833740068).jpg",
      },
    ],
    watch: [],
    visit: { label: "Rocky Mountain Arsenal National Wildlife Refuge", url: "https://www.fws.gov/refuge/rocky-mountain-arsenal" },
  },
  {
    slug: "hotels",
    eyebrow: "Denver, decoded · Downtown hotels",
    title: "Is there a five-star hotel in Denver?",
    dek: "Depends on who's counting: no Five-Star by Forbes, two Five Diamonds by AAA, four MICHELIN Keys.",
    hero: {
      src: "/landing/legends/hotels/hero.jpg",
      alt: "3D model of downtown Denver from the air, its towers and streets seen from the northwest",
    },
    facts: [
      {
        legend: "Is there a five-star hotel in Denver?",
        record:
          "Forbes Travel Guide's 2026 Star Awards list no Five-Star hotel in Denver. Colorado's only two are The Little Nell, in Aspen, and The Broadmoor, in Colorado Springs. Denver's two rated hotels are Four-Star: Four Seasons Hotel Denver and The Ritz-Carlton, Denver.",
        sources: [
          { name: "Forbes Travel Guide, 2026 Star Award winners", url: "https://www.forbestravelguide.com/award-winners.json" },
          { name: "Forbes Travel Guide, Denver", url: "https://www.forbestravelguide.com/destinations/denver-colorado" },
        ],
      },
      {
        record:
          "The Four Seasons opened in October 2010 in a 45-story tower that also holds private residences; the Ritz-Carlton opened on January 11, 2008.",
        sources: [
          { name: "Four Seasons Hotel Denver, hotel facts", url: "https://press.fourseasons.com/denver/hotel-facts" },
          { name: "The Ritz-Carlton, Denver, opening release (2008)", url: "https://journaldespalaces.com/pressrelease-10994-the-january-11-2008-opening-of-the-ritz-carlton-denver-offers-the-mile-high-city-a-new-level-of-luxury.html" },
        ],
      },
      {
        record:
          "AAA gives those same two its highest rating, Five Diamonds: the Ritz-Carlton since 2010 and the Four Seasons since 2014. Its 2026 Four Diamond list includes The Brown Palace, The Crawford, The Oxford, Halcyon and Hotel Clio.",
        sources: [
          { name: "AAA, Five Diamond hotels 2026", url: "https://newsroom.aaa.com/wp-content/uploads/2024/04/AAA-Five-Diamond-Hotels-2026-4.pdf" },
          { name: "AAA, Four Diamond hotels 2026", url: "https://newsroom.aaa.com/wp-content/uploads/2024/04/AAA-Four-Diamond-Hotels-2026-12.pdf" },
        ],
      },
      {
        record:
          "The 2026 MICHELIN Guide gives One Key each to four Denver hotels: Four Seasons Hotel Denver, the Clayton, The Crawford, inside Denver Union Station, and Populus. No Denver hotel has two or three Keys.",
        sources: [
          { name: "MICHELIN Guide, all the Key hotels in the United States (2026)", url: "https://guide.michelin.com/us/en/article/travel/all-the-key-hotels-united-states" },
          { name: "MICHELIN Guide, Populus", url: "https://guide.michelin.com/us/en/hotels-stays/denver/populus-14929" },
          { name: "The Crawford Hotel, history", url: "https://www.thecrawfordhotel.com/our-story/history/" },
          { name: "History Colorado, Denver Union Station", url: "https://historycolorado.org/node/6303" },
        ],
      },
      {
        record:
          "Populus, the newest, opened on October 15, 2024: 13 stories and 265 rooms, designed by Studio Gang, with windows that Studio Gang says evoke the dark, eye-shaped marks on aspen bark.",
        sources: [
          { name: "Studio Gang, Populus", url: "https://studiogang.com/project/populus" },
          { name: "Studio Gang, Populus completes", url: "https://studiogang.com/now/studio-gang-completes-populus-a-new-hotel-and-social-hub-in-downtown-denver/" },
          { name: "Westword, Populus opening date (2024)", url: "https://www.westword.com/news/populus-hotel-in-downtown-denver-postpones-opening-date-to-october-15-21989031" },
        ],
      },
      {
        record:
          "The oldest predate every rating. The Oxford opened in 1891; a year later the same architect, Frank E. Edbrooke, finished The Brown Palace, listed on the National Register of Historic Places in 1970.",
        sources: [
          { name: "National Register of Historic Places, The Oxford Hotel", url: "https://npgallery.nps.gov/NRHP/GetAsset/NRHP/79000590_text" },
          { name: "The Oxford Hotel, history", url: "https://www.theoxfordhotel.com/our-hotel/history" },
          { name: "National Register of Historic Places, Brown Palace Hotel", url: "https://npgallery.nps.gov/NRHP/GetAsset/NRHP/70000157_text" },
          { name: "History Colorado, Brown Palace Hotel", url: "https://historycolorado.org/node/5702" },
        ],
      },
      {
        record:
          "Sun Yat-sen arrived at The Brown Palace on October 10, 1911. Resting in room 321, he read in the Rocky Mountain News of the overthrow of China's Qing dynasty, according to the hotel's National Register documentation.",
        sources: [
          { name: "National Register of Historic Places, Brown Palace Hotel", url: "https://npgallery.nps.gov/NRHP/GetAsset/NRHP/70000157_text" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/hotels/populus.jpg",
        alt: "The white facade of the Populus hotel in Denver, covered in eye-shaped windows of different sizes, against a blue sky",
        caption: "Populus, opened in 2024 and designed by Studio Gang.",
        credit: "Daniel Hartwig, 2025, Wikimedia Commons",
        licence: "CC BY 4.0",
        page: "https://commons.wikimedia.org/wiki/File:Populus_Hotel_Denver_(54940682635).jpg",
      },
      {
        src: "/landing/legends/hotels/brown-palace.jpg",
        alt: "The red sandstone corner of the Brown Palace Hotel in downtown Denver, with an American flag on the roof",
        caption: "The Brown Palace, finished in 1892 by Frank E. Edbrooke.",
        credit: "Carol M. Highsmith, Library of Congress, via Wikimedia Commons",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:The_historic_Brown_Palace_Hotel_in_Denver,_one_of_the_first_to_employ_an_%22atrium_style%22_with_entire_floors_exposed_to_the_lobby_LCCN2017885320.tif",
      },
      {
        src: "/landing/legends/hotels/oxford.jpg",
        alt: "The red brick Oxford Hotel on a downtown Denver street corner, with green awnings at street level",
        caption: "The Oxford, opened in 1891.",
        credit: "Trueshow111, Wikimedia Commons",
        licence: "CC0",
        page: "https://commons.wikimedia.org/wiki/File:OxfordHotelDenver.jpg",
      },
      {
        src: "/landing/legends/hotels/sun-yat-sen-1911.jpg",
        alt: "Black-and-white portrait of Sun Yat-sen seated, holding papers, 1911",
        caption: "Sun Yat-sen in 1911, the year he stayed at the Brown Palace.",
        credit: "Agence Rol, Bibliothèque nationale de France, via Wikimedia Commons",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Dr_Sun-Yat-Sen_-_btv1b6917598r.jpg",
      },
    ],
    watch: [],
  },
  {
    slug: "adx",
    eyebrow: "Colorado, decoded · The federal supermax",
    title: "America's highest-security prison?",
    dek: "The press calls it that. The records say something narrower: the federal system's most restrictive prison, and its only supermax.",
    hero: {
      src: "/landing/legends/adx/hero.jpg",
      alt: "3D model from the air of a fenced federal prison complex on dry high plains, its outline drawn in gold, with mountains on the horizon",
    },
    facts: [
      {
        legend: "America's highest-security prison.",
        record:
          "The federal supermax sits about 96 miles south of downtown Denver. The records describe something narrower than the nickname: the most restrictive prison in the federal system, and the Bureau of Prisons' only supermax. By 1999, more than 30 states ran supermax facilities of their own.",
        sources: [
          { name: "U.S. Court of Appeals for the 10th Circuit, No. 11-1069 (2012)", url: "https://www.ca10.uscourts.gov/sites/ca10/files/opinions/01018831331.pdf" },
          { name: "U.S. Department of Justice, Report and Recommendations Concerning the Use of Restrictive Housing (2016)", url: "https://www.justice.gov/dag/file/815551/download" },
          { name: "U.S. Senate Judiciary subcommittee hearing (2012)", url: "https://www.govinfo.gov/content/pkg/CHRG-112shrg87630/html/CHRG-112shrg87630.htm" },
        ],
      },
      {
        legend: "Twenty-three hours a day in a cell.",
        record:
          "In the most restrictive units, about 23 hours a day are spent in the cell, according to the GAO. The Justice Department's minimum time outside the cell ranges from 5 hours a week in some units to 10.5 in general population.",
        sources: [
          { name: "GAO-13-429, Bureau of Prisons segregated housing (2013)", url: "https://www.gao.gov/assets/gao-13-429.pdf" },
          { name: "U.S. Department of Justice, Report and Recommendations Concerning the Use of Restrictive Housing (2016)", url: "https://www.justice.gov/dag/file/815551/download" },
        ],
      },
      {
        record:
          "The outside window measures 5 by 38 inches. Cells are about 75 to 87 square feet, behind a solid outer door and an inner grille.",
        sources: [
          { name: "U.S. Department of Justice, Report and Recommendations Concerning the Use of Restrictive Housing (2016)", url: "https://www.justice.gov/dag/file/815551/download" },
        ],
      },
      {
        legend: "Nobody has ever escaped.",
        record:
          "That claim comes from press reports. In the records we checked, we found no escape.",
        sources: [
          { name: "5280 magazine (2025)", url: "https://5280.com/adx-florence-facts-supermax/" },
          { name: "DOJ Office of the Inspector General, Restrictive Housing (2017)", url: "https://oig.justice.gov/sites/default/files/reports/e1705.pdf" },
        ],
      },
      {
        legend: "The secret Range 13.",
        record:
          "Range 13 is real. The Justice Department's Inspector General found two prisoners held there, each in his own cell more than 22 hours a day, and a federal appeals court opinion describes it too.",
        sources: [
          { name: "DOJ Office of the Inspector General, Restrictive Housing (2017)", url: "https://oig.justice.gov/sites/default/files/reports/e1705.pdf" },
          { name: "U.S. Court of Appeals for the 10th Circuit, No. 12-1450 (2014)", url: "https://www.ca10.uscourts.gov/sites/ca10/files/opinions/01019253486.pdf" },
        ],
      },
      {
        record:
          "Its name is ADX Florence, part of the Federal Correctional Complex, Florence. It has been in use since November 1994; the Bureau of Prisons listed 404 people there on October 15, 2026.",
        sources: [
          { name: "DOJ Office of the Inspector General, Restrictive Housing (2017)", url: "https://oig.justice.gov/sites/default/files/reports/e1705.pdf" },
          { name: "Federal Bureau of Prisons, USP Florence ADMAX", url: "https://www.bop.gov/locations/institutions/flm/" },
          { name: "Federal Bureau of Prisons, facility data", url: "https://www.bop.gov/PublicInfo/execute/phyloc?todo=query&output=json&code=FLM" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/adx/entrance.jpg",
        alt: "The brick entrance building of the federal supermax with a guard tower behind it, on dry grassland",
        caption: "The entrance, photographed by the Federal Bureau of Prisons.",
        credit: "Federal Bureau of Prisons, via Wikimedia Commons",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Florence_ADMAX.jpg",
      },
      {
        src: "/landing/legends/adx/range-13-cell.jpg",
        alt: "An empty cell with a concrete bed and stool, a steel sink and toilet, a narrow window and a solid door",
        caption: "A cell on Range 13, as the Bureau of Prisons photographed it for the GAO.",
        credit: "Federal Bureau of Prisons, published in GAO-13-429 (2013)",
        licence: "Public domain",
        page: "https://www.gao.gov/products/gao-13-429",
      },
    ],
    watch: [],
  },
  {
    slug: "cheyenne",
    eyebrow: "Colorado, decoded · The city inside a mountain",
    title: "Built to withstand a nuclear strike?",
    dek: "A city inside a mountain, on giant springs, behind blast doors. Each claim, against the record.",
    hero: {
      src: "/landing/legends/cheyenne/hero.jpg",
      alt: "3D model of a block of mountain cut open, with a long tunnel leading to a chamber of buildings inside the rock",
    },
    facts: [
      {
        legend: "A city inside a mountain.",
        record:
          "The complex sits about 70 miles south of downtown Denver. Excavation began on May 18, 1961, and the Defense Department built it in the early 1960s to withstand a multimegaton-yield-weapon strike, according to the GAO. Inside the granite stand 15 steel buildings.",
        sources: [
          { name: "NORAD Office of History, A Brief History of NORAD (2012)", url: "https://web.archive.org/web/20150420161330/http://www.norad.mil/Portals/29/Documents/History/A%20Brief%20History%20of%20NORAD.pdf" },
          { name: "GAO-07-803R, Cheyenne Mountain realignment (2007)", url: "https://www.gao.gov/products/gao-07-803r" },
          { name: "U.S. Space Command, Cheyenne Mountain information booklet (archived 2000)", url: "https://web.archive.org/web/20001025233012/http://www.spacecom.af.mil/usspace/fbcmas.htm" },
          { name: "USGS Geographic Names Information System, Cheyenne Mountain and Denver", url: "https://edits.nationalmap.gov/apps/gaz-domestic/public/summary/203681" },
        ],
      },
      {
        legend: "The buildings sit on giant springs.",
        record:
          "True. The Space Force says the 15 buildings rest on more than 1,300 springs, 18 inches from the rock walls, so they could move independently in the event of a nuclear blast or an earthquake.",
        sources: [
          { name: "U.S. Space Force, Beyond the blast doors (2016)", url: "https://www.petersonschriever.spaceforce.mil/Newsroom/News/Display/Article/733431/beyond-the-blast-doors-50-years-later-cheyenne-mountain-remains-the-dragon-that/" },
        ],
      },
      {
        legend: "Blast doors weighing 25 tons.",
        record:
          "Air Force figures for the main blast doors range from 20 to 25 tons each; a 2014 Air Force article lists two 25-ton doors and a 17-ton one. In 2012 the Air Force said the doors were closed and opened once a week.",
        sources: [
          { name: "U.S. Air Force photo 121025-F-ZZ000-001 and caption (2012)", url: "https://commons.wikimedia.org/wiki/File:121025-F-ZZ000-001_Cheyenne_Mountain_20-ton_blast_door_closing.jpg" },
          { name: "U.S. Space Force, Beyond the blast doors (2016)", url: "https://www.petersonschriever.spaceforce.mil/Newsroom/News/Display/Article/733431/beyond-the-blast-doors-50-years-later-cheyenne-mountain-remains-the-dragon-that/" },
          { name: "U.S. Air Force, Airmen operate America's fortress (2014)", url: "https://www.af.mil/News/Features/Article/497017/airmen-operate-americas-fortress/" },
        ],
      },
      {
        legend: "It would survive a direct nuclear hit.",
        record:
          "Not quite. The GAO says it was built to withstand a multimegaton-yield-weapon strike, but a U.S. Space Command booklet said it would probably not survive a direct hit from today's accurate and high-yield nuclear weapons.",
        sources: [
          { name: "GAO-07-803R, Cheyenne Mountain realignment (2007)", url: "https://www.gao.gov/products/gao-07-803r" },
          { name: "U.S. Space Command, The Cheyenne Mountain Story (archived 2000)", url: "https://web.archive.org/web/20001204224500/http://www.spacecom.af.mil/usspace/cmocfb.htm" },
        ],
      },
      {
        legend: "It was abandoned.",
        record:
          "No. On May 12, 2008, its command center was re-designated the NORAD and USNORTHCOM Alternate Command Center, and it remains a training site for crew qualification. It was renamed Cheyenne Mountain Space Force Station on July 26, 2021.",
        sources: [
          { name: "U.S. Northern Command, Cheyenne Mountain", url: "https://www.northcom.mil/CheyenneMountain/" },
          { name: "U.S. Space Force, CMSFS updates base sign (2021)", url: "https://www.petersonschriever.spaceforce.mil/Newsroom/News/Display/Article/2816876/cmsfs-updates-base-sign-to-reflect-space-force/" },
        ],
      },
      {
        record:
          "Its name is Cheyenne Mountain. NORAD moved its Combat Operations Center there from Ent Air Force Base on April 20, 1966. The figures in our animations are illustrations: the interior layout is not published.",
        sources: [
          { name: "NORAD Office of History, A Brief History of NORAD (2012)", url: "https://web.archive.org/web/20150420161330/http://www.norad.mil/Portals/29/Documents/History/A%20Brief%20History%20of%20NORAD.pdf" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/cheyenne/springs.jpg",
        alt: "A worker in a hard hat crouches among large steel coil springs under a building inside the mountain",
        caption: "The coil springs under the steel buildings, photographed in 1984.",
        credit: "Bob Simons, U.S. Air Force (National Archives)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:NORADSprings1.jpg",
      },
      {
        src: "/landing/legends/cheyenne/blast-door.jpg",
        alt: "People watch a massive ribbed steel blast door close in a white-walled tunnel",
        caption: "One of the blast doors closing during an exercise, October 2012.",
        credit: "Joann Missey, U.S. Air Force",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:121025-F-ZZ000-001_Cheyenne_Mountain_20-ton_blast_door_closing.jpg",
      },
    ],
    watch: [],
  },
  {
    slug: "brownpalace",
    eyebrow: "Denver, decoded · The tunnel under Tremont Place",
    title: "A secret tunnel to a gambling house?",
    dek: "Across Tremont Place from a grand hotel stood a gambling house. Was there a tunnel between them, and what was it for?",
    hero: {
      src: "/landing/legends/brownpalace/hero.jpg",
      alt: "3D model of a downtown block cut open at dusk, with a lit tunnel under the street joining the basements of two buildings",
    },
    facts: [
      {
        legend: "Across the street from a grand hotel stood a gambling house.",
        record:
          "The Brown Palace has been open since August 12, 1892. Across Tremont Place, a brick building from 1880 began as the Brinker Collegiate Institute, reopened in 1889 as the Richelieu Hotel, run by gambling operators, and was later renamed the Navarre.",
        sources: [
          { name: "The Brown Palace, hotel history (2019)", url: "https://web.archive.org/web/20190701/https://www.brownpalace.com/our-hotel/history/" },
          { name: "National Register of Historic Places nomination, Navarre Building (1977)", url: "https://npgallery.nps.gov/GetAsset/61b2ae42-2ca4-4e28-a3b8-ddb88963ef07" },
        ],
      },
      {
        legend: "A tunnel ran under the street.",
        record:
          "On paper, yes. The Navarre's 1977 National Register nomination describes a rail passageway emerging from a tunnel under Tremont Place from the Brown Palace Hotel, now sealed off, leading to the building's steam heating plant. The same form says it carried coal.",
        sources: [
          { name: "National Register of Historic Places nomination, Navarre Building (1977)", url: "https://npgallery.nps.gov/GetAsset/61b2ae42-2ca4-4e28-a3b8-ddb88963ef07" },
        ],
      },
      {
        legend: "Hotel guests used it to reach the gambling house unseen.",
        record:
          "No record shows it. The same 1977 form says the tunnel allowed \u201cunseen passage\u201d but gives no evidence, and historian Thomas J. Noel calls it in fact a utility tunnel, too tiny to allow any substantial hotel guest patronage of the Navarre. The hotel's own history pages never mention the Navarre.",
        sources: [
          { name: "Thomas J. Noel, Museum of Western Art (The Navarre), SAH Archipedia", url: "https://sah-archipedia.org/buildings/CO-01-DV026" },
          { name: "National Register of Historic Places nomination, Navarre Building (1977)", url: "https://npgallery.nps.gov/GetAsset/61b2ae42-2ca4-4e28-a3b8-ddb88963ef07" },
        ],
      },
      {
        legend: "The hotel has a tunnel under Tremont Place.",
        record:
          "A different one. On December 15, 1957, the Denver Post reported a tunnel finished between the hotel and its new addition across the same street, the tower that opened as Brown Palace West and is also joined to the hotel by a bridge over Tremont Place.",
        sources: [
          { name: "Denver Public Library, Western History subject index (Denver Post, Dec. 15, 1957)", url: "https://digital.denverlibrary.org/nodes/view/1298707" },
          { name: "Historic Hotels of America, The Brown Palace history", url: "https://www.historichotels.org/us/hotels-resorts/the-brown-palace-hotel-and-spa-autograph-collection/history" },
        ],
      },
      {
        record:
          "The hotel is The Brown Palace. In our animation the street and the buildings come from OpenStreetMap; the tunnel's route and size, the basements and the boiler are illustrations, because no published plan gives them.",
        sources: [
          { name: "National Register of Historic Places nomination, Navarre Building (1977)", url: "https://npgallery.nps.gov/GetAsset/61b2ae42-2ca4-4e28-a3b8-ddb88963ef07" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/brownpalace/1898.jpg",
        alt: "A tall red stone hotel with rows of arched windows rises over low buildings and trees, seen from above",
        caption: "The Brown Palace around 1898, six years after it opened.",
        credit: "William Henry Jackson (Library of Congress)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Brown_Palace_Hotel,_1898.JPG",
      },
      {
        src: "/landing/legends/brownpalace/exterior-2016.jpg",
        alt: "The rounded corner of a red sandstone hotel on a sunny street, with glass towers behind it",
        caption: "The hotel's corner at 17th Street and Tremont Place, 2016.",
        credit: "Carol M. Highsmith (Library of Congress)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:The_historic_Brown_Palace_Hotel_in_Denver,_one_of_the_first_to_employ_an_%22atrium_style%22_with_entire_floors_exposed_to_the_lobby_LCCN2017885320.tif",
      },
    ],
    watch: [],
  },
  {
    slug: "sloanslake",
    eyebrow: "Denver, decoded · Sloan's Lake",
    title: "The lake that wasn't there, and the elephant that wasn't buried",
    dek: "Denver's biggest lake has two legends, and one of them is an elephant. Here is what the records say.",
    hero: {
      src: "/landing/legends/sloanslake/hero.jpg",
      alt: "3D model of Denver from the west, with Sloan's Lake in the foreground and the downtown towers behind it",
    },
    facts: [
      {
        legend: "In 1861 a farmer named Thomas Sloan dug a well, hit water, and woke up to a lake on his farm.",
        record:
          "Nobody knows for sure how the lake formed. A gold-rush stagecoach driver, Bill Turner, said it was not there when he left for Kansas in June 1861 and was there when he came back in early 1863. Thomas M. Sloan received his land patent in December 1866, and it is unlikely he would have patented farmland that was already under water.",
        sources: [{ name: "Sloan's Lake Park Foundation, Lake History", url: "https://sloanslakeparkfoundation.org/lake-history" }],
      },
      {
        record:
          "Since 1859 the road from Denver to Golden had crossed the spot. The water flooded it, and the road that replaced it is now Colfax Avenue.",
        sources: [{ name: "Sloan's Lake Park Foundation, Lake History", url: "https://sloanslakeparkfoundation.org/lake-history" }],
      },
      {
        record:
          "On the north shore stood Manhattan Beach, an amusement park with a roller coaster, boats and a zoo. Its biggest draw was Roger, an elephant who gave children rides.",
        sources: [
          { name: "Denver7, The history of Sloan's Lake and Roger the Elephant", url: "https://www.denver7.com/news/local-news/why-is-there-an-elephant-buried-in-edgewater-the-history-of-sloans-lake-and-roger-the-elephant" },
          { name: "Sloan's Lake Park Foundation, Lake History", url: "https://sloanslakeparkfoundation.org/lake-history" },
        ],
      },
      {
        record:
          "On July 5, 1891, a balloon went up beside the zoo. Roger panicked and a six-year-old boy riding him, George W. Eaton, was killed, as the Rocky Mountain News reported the next day.",
        sources: [
          { name: "Denver7, quoting the Rocky Mountain News (July 1891)", url: "https://www.denver7.com/news/local-news/why-is-there-an-elephant-buried-in-edgewater-the-history-of-sloans-lake-and-roger-the-elephant" },
          { name: "Colorado Public Radio, interview with historian David Forsyth (2024)", url: "https://www.cpr.org/2024/03/16/the-lost-history-of-denvers-manhattan-beach-amusement-park/" },
        ],
      },
      {
        legend: "Roger was put down and buried by the park, under what is now a supermarket parking lot.",
        record:
          "Historian David Forsyth, who wrote the book on the park, says it never happened: Roger was on loan from the Central Park Zoo in New York, so the park could not have put him down, and in 1892 he was still there, still getting his bath in the lake. Where he went after that, the records do not say.",
        sources: [{ name: "Colorado Public Radio, interview with historian David Forsyth (2024)", url: "https://www.cpr.org/2024/03/16/the-lost-history-of-denvers-manhattan-beach-amusement-park/" }],
      },
      {
        record: "The park burned in 1908, reopened that year as Luna Park and closed for good in 1914. The lake stayed.",
        sources: [{ name: "Sloan's Lake Park Foundation, Lake History", url: "https://sloanslakeparkfoundation.org/lake-history" }],
      },
    ],
    photos: [
      {
        src: "/landing/legends/sloanslake/frolic.jpg",
        alt: "A postcard of a white two-deck steamboat full of passengers, flags strung along its roof, on calm water",
        caption: "The steamboat Frolic at Luna Park, the park's last name, between 1908 and 1914.",
        credit: "Unknown photographer, postcard",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Luna_Park_steamboat_Denver.jpg",
      },
      {
        src: "/landing/legends/sloanslake/east-2008.jpg",
        alt: "A wide lake under a blue sky, with the downtown Denver skyline small on the far shore",
        caption: "Looking east across the lake toward downtown, 2008.",
        credit: "coulderbolorado",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Looking_east_from_Sloan%27s_Lake_towards_Downtown_Denver_(1_July_2008).jpg",
      },
    ],
    watch: [
      { network: "YouTube", url: "https://www.youtube.com/shorts/XfEFxF4VNlU" },
      { network: "Instagram", url: "https://www.instagram.com/reel/DeVX_rvEvnn/" },
      { network: "TikTok", url: "https://tiktok.com/@denverhomestory/video/7695185516861410573" },
    ],
  },
  {
    slug: "dia",
    eyebrow: "Denver, decoded · Denver International Airport",
    title: "The airport's “cursed” horse",
    dek: "Most people fly through Denver's airport without ever really seeing it. Here is what the records say about the roof, the price and the blue horse.",
    hero: {
      src: "/landing/legends/dia/hero.jpg",
      alt: "3D model of Denver International Airport from above: the white peaked terminal roof, the parking lots and the runways on the open plains",
    },
    facts: [
      {
        record:
          "The airport sits on a 52.4-square-mile site 25 miles northeast of the city: the largest airport in North America by land area, and the second largest in the world.",
        sources: [
          { name: "Colorado Encyclopedia, Denver International Airport", url: "https://coloradoencyclopedia.org/article/denver-international-airport" },
          { name: "Wikipedia, Denver International Airport", url: "https://en.wikipedia.org/wiki/Denver_International_Airport" },
        ],
      },
      {
        record:
          "It opened on February 28, 1995, sixteen months behind schedule, after its automated baggage system kept failing.",
        sources: [{ name: "Wikipedia, Denver International Airport", url: "https://en.wikipedia.org/wiki/Denver_International_Airport" }],
      },
      {
        record:
          "The Colorado Encyclopedia calls it a $2.3 billion airport that has wound up costing more than $6 billion with everything added since. Wikipedia puts the cost on opening day at $4.8 billion.",
        sources: [
          { name: "Colorado Encyclopedia, Denver International Airport", url: "https://coloradoencyclopedia.org/article/denver-international-airport" },
          { name: "Wikipedia, Denver International Airport", url: "https://en.wikipedia.org/wiki/Denver_International_Airport" },
        ],
      },
      {
        legend: "The white roof is a circus tent.",
        record:
          "It is a fabric roof designed by the architects Curt Fentress and James Bradburn after the snow-capped peaks of the Rockies.",
        sources: [
          { name: "Colorado Encyclopedia, Denver International Airport", url: "https://coloradoencyclopedia.org/article/denver-international-airport" },
          { name: "Wikipedia, Denver International Airport", url: "https://en.wikipedia.org/wiki/Denver_International_Airport" },
        ],
      },
      {
        legend: "The blue horse with the glowing red eyes, “Blucifer”, is cursed.",
        record:
          "Its name is Mustang, a 32-foot fiberglass horse by the sculptor Luis Jiménez. Jiménez was killed in 2006 when a section of it came loose and severed an artery in his leg. The red eyes are a tribute to his father, who ran a neon sign shop.",
        sources: [
          { name: "Denver Public Library, A local's guide to DIA conspiracy theories", url: "https://history.denverlibrary.org/news/denver/locals-guide-dia-conspiracy-theories" },
          { name: "Wikipedia, Blue Mustang", url: "https://en.wikipedia.org/wiki/Blue_Mustang" },
        ],
      },
    ],
    photos: [
      {
        src: "/landing/legends/dia/roof.jpg",
        alt: "White fabric peaks of the airport terminal roof against a blue sky with clouds",
        caption: "The terminal roof up close.",
        credit: "Carol M. Highsmith (Library of Congress)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Roof_detail,_Denver_International_Airport,_Denver,_Colorado_LCCN2011630369.tif",
      },
    ],
    watch: [
      { network: "YouTube", url: "https://www.youtube.com/shorts/W31VwxOl09c" },
      { network: "Instagram", url: "https://www.instagram.com/reel/DeQOaLQjs1o/" },
      { network: "TikTok", url: "https://tiktok.com/@denverhomestory/video/7694814497701104910" },
    ],
  },
  {
    slug: "lookout",
    eyebrow: "Denver, decoded · Lookout Mountain",
    title: "Who is buried on Lookout Mountain?",
    dek: "Two states have argued for a century about who is really in Buffalo Bill's grave. Here is what the records say.",
    hero: {
      src: "/landing/legends/lookout/hero.jpg",
      alt: "3D model of Lookout Mountain above Golden: forested ridges and dry slopes, with the plains beyond",
    },
    facts: [
      {
        record:
          "Buffalo Bill Cody died on January 10, 1917, at his sister's home in Denver.",
        sources: [
          { name: "Buffalo Bill Center of the West, Points West (2015)", url: "https://centerofthewest.org/2015/05/31/points-west-buffalo-bill-last-stand/" },
          { name: "Buffalo Bill Museum and Grave, History", url: "https://www.buffalobill.org/history/" },
        ],
      },
      {
        legend: "He wanted to be buried in Cody, Wyoming, the town he founded, and friends from Cody swapped his body for a ranch hand's and took him home.",
        record:
          "His wife, Louisa, said he chose Lookout Mountain. His friends Goldie Griffith and Johnny Baker, and the priest who gave him last rites, said the same. An earlier will had named Cedar Mountain above Cody; an updated one named Lookout Mountain. The swap story is still told in Cody; the records place him on Lookout Mountain.",
        sources: [
          { name: "Buffalo Bill Museum and Grave, History", url: "https://www.buffalobill.org/history/" },
          { name: "Denver Public Library, Is Buffalo Bill Cody really buried on Lookout Mountain? (2016)", url: "https://history.denverlibrary.org/news/western-history/buffalo-bill-cody-really-buried-lookout-mountain" },
          { name: "Cody Yellowstone, The mystery of Buffalo Bill Cody's two graves", url: "https://www.codyyellowstone.org/blog/the-mystery-of-buffalo-bill-codys-two-graves/" },
        ],
      },
      {
        record:
          "Winter had closed the road up the mountain, so his body was kept at a Denver mortuary until June 3, 1917, when thousands filed past the casket and he was buried on the mountain.",
        sources: [
          { name: "Denver Public Library, Is Buffalo Bill Cody really buried on Lookout Mountain? (2016)", url: "https://history.denverlibrary.org/news/western-history/buffalo-bill-cody-really-buried-lookout-mountain" },
          { name: "Buffalo Bill Center of the West, Points West (2015)", url: "https://centerofthewest.org/2015/05/31/points-west-buffalo-bill-last-stand/" },
        ],
      },
      {
        record:
          "The grave was put under concrete to deter a raid from Wyoming. In 1948, members of an American Legion post in Cody offered $10,000 to anyone who brought the body back, and the Colorado National Guard stationed troops around the grave. The Center of the West places that 1948 plan with a post in Cheyenne.",
        sources: [
          { name: "Denver Public Library, Is Buffalo Bill Cody really buried on Lookout Mountain? (2016)", url: "https://history.denverlibrary.org/news/western-history/buffalo-bill-cody-really-buried-lookout-mountain" },
          { name: "Buffalo Bill Center of the West, Points West (2015)", url: "https://centerofthewest.org/2015/05/31/points-west-buffalo-bill-last-stand/" },
        ],
      },
      {
        record:
          "Louisa was buried beside him in 1921. That same year Johnny Baker, his unofficial foster son, opened the museum next to the grave; it moved into its current building in 1977.",
        sources: [{ name: "Buffalo Bill Museum and Grave, History", url: "https://www.buffalobill.org/history/" }],
      },
    ],
    photos: [
      {
        src: "/landing/legends/lookout/cody-1911.jpg",
        alt: "Black-and-white portrait of an older man with a white moustache and goatee in a wide-brimmed hat",
        caption: "William F. Cody in 1911.",
        credit: "Moffett Studio, Chicago (Library of Congress)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Cody-Buffalo-Bill-LOC.jpg",
      },
      {
        src: "/landing/legends/lookout/funeral-1917.jpg",
        alt: "A crowd and a marching band fill a downtown street in black and white, with soldiers in the procession",
        caption: "Buffalo Bill's funeral parade in Denver, 1917.",
        credit: "Unknown photographer (Library of Congress)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Buffalo_Bill%27s_funeral_cph.3b14503.jpg",
      },
      {
        src: "/landing/legends/lookout/grave.jpg",
        alt: "A stone monument with a bronze plaque behind an iron fence, flowers at its base, under pine trees",
        caption: "The grave on Lookout Mountain.",
        credit: "Carol M. Highsmith (Library of Congress)",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:William_%27Buffalo_Bill%27_Cody_gravesite_on_Lookout_Mountain_outside_Denver,_Colorado_LCCN2011631818.tif",
      },
    ],
    watch: [
      { network: "YouTube", url: "https://www.youtube.com/shorts/RpIZt-MlQQc" },
      { network: "Instagram", url: "https://www.instagram.com/reel/DeNptpDkXkb/" },
      { network: "TikTok", url: "https://tiktok.com/@denverhomestory/video/7694443366729239821" },
    ],
    visit: { label: "Visit the Buffalo Bill Museum and Grave", url: "https://www.buffalobill.org/" },
  },  {
    slug: "mountfalcon",
    eyebrow: "Denver, decoded · Mount Falcon",
    title: "Why is there a White House cornerstone above Red Rocks?",
    dek: "A magazine millionaire promised the presidents a summer home on the mountain above Morrison. Here is what the records say about the house that was never built.",
    hero: {
      src: "/landing/legends/mountfalcon/hero.jpg",
      alt: "3D model of Mount Falcon: forested ridges above the red rock formations, with the plains beyond",
    },
    facts: [
      {
        record:
          "John Brisben Walker bought Cosmopolitan magazine in 1889 and sold it to William Randolph Hearst in 1905.",
        sources: [
          { name: "Morrison History, John Brisben Walker", url: "https://morrisonhistory.org/john-brisben-walker/" },
          { name: "Wikipedia, John Brisben Walker", url: "https://en.wikipedia.org/wiki/John_Brisben_Walker" },
        ],
      },
      {
        record:
          "From 1905 he bought up Red Rocks and the land around it, called it the Garden of the Titans and opened it with a concert on May 31, 1906. Denver bought the park in 1927.",
        sources: [
          { name: "Red Rocks Park and Amphitheatre, History", url: "https://www.redrocksonline.com/?p=6966" },
          { name: "Wikipedia, John Brisben Walker", url: "https://en.wikipedia.org/wiki/John_Brisben_Walker" },
        ],
      },
      {
        legend: "A president was coming to spend his summers on Mount Falcon.",
        record:
          "Walker conceived a summer home for the presidents in 1910 and had the Denver architect J. B. Benedict draw it. In October 1911 he showed the cornerstone, a block of Colorado Yule marble, in Denver. President Taft said no better location could be found. In July 1914 the Rocky Mountain News announced that President Wilson would lay the cornerstone on August 15; the trip was put off until October, and October passed. A plaque at the site says the stone was laid on July 4, 1914.",
        sources: [
          { name: "Francis Russell, The Summer White House in the Clouds, American Heritage (1973)", url: "https://www.americanheritage.com/summer-white-house-clouds" },
          { name: "Read the Plaque, Summer White House that was never built", url: "https://readtheplaque.com/plaque/summer-white-house-that-was-never-built" },
        ],
      },
      {
        record:
          "The stone reads: Summer Home for the Presidents of the United States, the gift of the people of Colorado, 1911. Walker asked every schoolchild in the country for ten cents, and some of them paid, but the three hundred thousand dollars he hoped to raise never came. World War I and his shrinking fortune ended the project with only the foundation built.",
        sources: [
          { name: "Francis Russell, The Summer White House in the Clouds, American Heritage (1973)", url: "https://www.americanheritage.com/summer-white-house-clouds" },
          { name: "Wikipedia, John Brisben Walker", url: "https://en.wikipedia.org/wiki/John_Brisben_Walker" },
        ],
      },
      {
        legend: "Lightning burned the castle.",
        record:
          "Walker built a stone house on the mountain for his family. His wife, Ethel, died in 1916, and in 1918 the house burned. Most accounts say lightning; Morrison's history walking tour adds that others suggested a more sinister cause. Walker died in Brooklyn in 1931.",
        sources: [
          { name: "Morrison History, John Brisben Walker", url: "https://morrisonhistory.org/john-brisben-walker/" },
          { name: "Wikipedia, John Brisben Walker", url: "https://en.wikipedia.org/wiki/John_Brisben_Walker" },
        ],
      },
      {
        record:
          "Mount Falcon Park is free and part of Jefferson County Open Space. Its trails lead to the ruins of Walker's house and to the cornerstone of the summer home.",
        sources: [{ name: "Jefferson County Open Space, Mount Falcon Park", url: "https://www.jeffco.us/1332/Mount-Falcon-Park" }],
      },
    ],
    photos: [
      {
        src: "/landing/legends/mountfalcon/walker-1890.jpg",
        alt: "Black-and-white oval portrait of a man with a moustache resting his head on his hand",
        caption: "John Brisben Walker, around 1890.",
        credit: "Unknown photographer",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:John_Brisben_Walker_ca_1890.jpg",
      },
      {
        src: "/landing/legends/mountfalcon/ruins.jpg",
        alt: "Stone chimneys and broken walls of a ruined house among pine trees under a blue sky",
        caption: "The ruins of Walker's house on Mount Falcon.",
        credit: "Nicolas Raymond",
        licence: "CC BY 2.0",
        page: "https://commons.wikimedia.org/wiki/File:Walker_Home_Ruins_(53015080957).jpg",
      },
      {
        src: "/landing/legends/mountfalcon/ruins-pano.jpg",
        alt: "Panorama of stone walls with empty window openings behind a wooden fence",
        caption: "The house ruins from the inside, 2009.",
        credit: "Fitchhollister",
        licence: "Public domain",
        page: "https://commons.wikimedia.org/wiki/File:Walker_home_pano.jpg",
      },
    ],
    watch: [],
    visit: { label: "Plan a hike: Mount Falcon Park", url: "https://www.jeffco.us/1332/Mount-Falcon-Park" },
  },
];

export function legendBySlug(slug: string): Legend | undefined {
  return LEGENDS.find((l) => l.slug === slug);
}
