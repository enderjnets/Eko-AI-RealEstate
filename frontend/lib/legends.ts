/**
 * The 3D legends: one page per video, opened by the short path the video says
 * out loud (`/colfax`, `/cheesman`, `/mollybrown`, `/unionstation`, `/georgetownloop`, `/confluencepark`, `/redrocks` in `next.config.js`).
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
];

export function legendBySlug(slug: string): Legend | undefined {
  return LEGENDS.find((l) => l.slug === slug);
}
