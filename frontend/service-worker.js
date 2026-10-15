// App-shell cache so the scanner still opens with no signal. Scans
// themselves are queued in IndexedDB (idb.js), never here.
const CACHE_PREFIX = "boord-labour-";
const CACHE = "boord-labour-v1";
const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./idb.js",
  "./manifest.json",
  "./shared/styles.css",
  "./shared/api.js",
  "./shared/sw-core.js",
  "./shared/tailwind.js",
  "./shared/vendor/fontawesome/css/all.min.css",
  "./shared/vendor/fontawesome/webfonts/fa-solid-900.woff2",
  "./shared/vendor/html5-qrcode.min.js",
];

// Install/activate/fetch handling is Boord's - see shared/sw-core.js.
importScripts("./shared/sw-core.js");
