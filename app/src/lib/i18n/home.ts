// Strings of the home screens. French is the reference; `en` must keep the same shape.
// Wording describes entries; it never advises (design spec, section 5).
const fr = {
  searchLabel: "Quelle gare ?",
  searchPlaceholder: "Châtelet, Nation, La Défense",
  searchOffline: "Recherche indisponible hors ligne",
  searchOfflineWhy: "La recherche a besoin du réseau. Vos gares restent consultables.",
  resultsLabel: "Gares trouvées",
  resultsCount: (n: number) => (n === 1 ? "1 gare trouvée." : `${n} gares trouvées.`),
  noResult: "Aucune gare trouvée.",
  savedHeading: "Vos gares, en ce moment",
  bigHeading: "Grandes gares, en ce moment",
  recentHeading: "Consultées récemment",
  favHint: "Touchez l’étoile d’une gare pour la garder ici.",
  tileUnavailable: "Pas disponible hors ligne.",
  tileLoading: "Chargement…",
  offlineBold: "Hors ligne.",
  offlineBody: "Vos gares enregistrées restent consultables.",
  installButton: "Installer l’application",
  installTitle: "Installer à point",
  installBody: "Vos gares s’ouvrent depuis l’écran d’accueil et restent consultables sans réseau.",
  install: "Installer",
  later: "Plus tard",
  gotIt: "Compris",
  iosHint: "Sur iPhone : touchez Partager, puis « Sur l’écran d’accueil ».",
};

export type HomeStrings = typeof fr;

// English reviewed (British spelling, 24-hour clock, entries described, never advice).
const en: HomeStrings = {
  searchLabel: "Which station?",
  searchPlaceholder: "Châtelet, Nation, La Défense",
  searchOffline: "Search unavailable offline",
  searchOfflineWhy: "Search needs a connection. Your stations stay available.",
  resultsLabel: "Stations found",
  resultsCount: (n: number) => (n === 1 ? "1 station found." : `${n} stations found.`),
  noResult: "No station found.",
  savedHeading: "Your stations, right now",
  bigHeading: "Major stations, right now",
  recentHeading: "Recently viewed",
  favHint: "Tap the star on a station to keep it here.",
  tileUnavailable: "Not available offline.",
  tileLoading: "Loading…",
  offlineBold: "Offline.",
  offlineBody: "Your saved stations stay available.",
  installButton: "Install the app",
  installTitle: "Install à point",
  installBody: "Your stations open from the home screen and stay available without a connection.",
  install: "Install",
  later: "Later",
  gotIt: "Got it",
  iosHint: "On iPhone: tap Share, then “Add to Home Screen”.",
};

export const home = { fr, en };
