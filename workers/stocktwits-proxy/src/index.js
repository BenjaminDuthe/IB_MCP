const STOCKTWITS_BASE = "https://api.stocktwits.com/api/2";

const ALLOWED_PATHS = [
  /^\/streams\/symbol\/[A-Z]{1,10}\.json$/,
  /^\/trending\/symbols\.json$/,
];

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Only allow known StockTwits API paths
    if (!ALLOWED_PATHS.some((re) => re.test(path))) {
      return new Response(JSON.stringify({ error: "Not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }

    const targetUrl = `${STOCKTWITS_BASE}${path}${url.search}`;

    try {
      const resp = await fetch(targetUrl, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
          Accept: "application/json",
        },
      });

      const body = await resp.text();

      return new Response(body, {
        status: resp.status,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
          "X-Proxy": "stocktwits-proxy",
        },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
};
