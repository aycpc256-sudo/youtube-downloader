const CACHE =
  "downloader-v6";

const ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./manifest.json",
];


self.addEventListener(
  "install",
  (event) => {

    event.waitUntil(
      caches
        .open(CACHE)
        .then(
          (cache) =>
            cache.addAll(
              ASSETS
            )
        )
    );

    self.skipWaiting();
  }
);


self.addEventListener(
  "activate",
  (event) => {

    event.waitUntil(

      caches
        .keys()
        .then(
          (keys) =>
            Promise.all(
              keys
                .filter(
                  (key) =>
                    key !== CACHE
                )
                .map(
                  (key) =>
                    caches.delete(
                      key
                    )
                )
            )
        )
    );

    self.clients.claim();
  }
);


self.addEventListener(
  "fetch",
  (event) => {

    // Render API는 캐시하지 않는다.
    if (
      event.request.url.includes(
        "/api/"
      )
    ) {
      return;
    }

    event.respondWith(

      caches
        .match(
          event.request
        )
        .then(
          (cached) =>
            cached ||
            fetch(
              event.request
            )
        )
    );
  }
);
