/**
 * POST /api/v1/query
 *
 * Main entry point. Receives a natural language grocery query + location,
 * calls the Python parser, dispatches scraping, stores results in Redis,
 * and returns a search_id for the client to stream results from.
 */
const express = require('express');
const axios = require('axios');
const { v4: uuidv4 } = require('uuid');
const redis = require('../redis');
const auth = require('../middleware/auth');

const router = express.Router();
const SCRAPER_URL = process.env.SCRAPER_URL || 'http://localhost:8001';
const CACHE_TTL_SECONDS = 300; // Cache results for 5 minutes

router.post('/', auth, async (req, res) => {
  const { query, lat, lon } = req.body;

  if (!query || query.trim().length < 3) {
    return res.status(400).json({ error: 'Query is too short. Please describe what you need.' });
  }

  const searchId = uuidv4();

  // Immediately respond with searchId so frontend can open SSE
  res.status(202).json({ search_id: searchId, status: 'processing' });

  // Run the full pipeline asynchronously
  _runPipeline(searchId, query.trim(), lat, lon).catch((err) => {
    console.error(`[${searchId}] Pipeline failed:`, err.message);
    _publishState(searchId, { status: 'error', error: err.message });
  });
});

async function _runPipeline(searchId, query, lat, lon) {
  try {
    // ── Step 1: Check cache (TEMPORARILY DISABLED FOR DEBUGGING) ─────────
    const cacheKey = `qc:result:${_hashQuery(query, lat, lon)}`;
    /*
    const cached = await redis.get(cacheKey).catch(() => null);
    if (cached) {
      console.log(`[${searchId}] Cache hit!`);
      const result = JSON.parse(cached);
      result.from_cache = true;
      await _publishState(searchId, { status: 'complete', data: result });
      return;
    }
    */

    // ── Step 2: Parse the NL query ───────────────────────────────────────────
    await _publishState(searchId, { status: 'parsing', message: 'Understanding your grocery list...' });

    const parseRes = await axios.post(`${SCRAPER_URL}/parse/`, { query }, { timeout: 12000 });
    const parsedQuery = parseRes.data;

    await _publishState(searchId, {
      status: 'scraping',
      message: `Found ${parsedQuery.items.length} item(s). Checking prices on all platforms...`,
      items: parsedQuery.items
    });

    // ── Step 3: Scrape all platforms ─────────────────────────────────────────
    await _publishState(searchId, {
      status: 'scraping',
      message: `Found ${parsedQuery.items.length} item(s). Fetching LIVE prices from all platforms (this takes ~30-60 seconds)...`,
      items: parsedQuery.items
    });

    const scrapeRes = await axios.post(
      `${SCRAPER_URL}/scrape/`,
      { items: parsedQuery.items, lat: lat || 28.6139, lon: lon || 77.2090 },
      { timeout: 330000 }   // 5.5 min — real Playwright scraping might take up to 4-5 mins for >10 items
    );

    const scrapeData = scrapeRes.data;

    // ── Step 4: Cache the result ─────────────────────────────────────────────
    await redis.set(cacheKey, JSON.stringify(scrapeData), 'EX', CACHE_TTL_SECONDS).catch(() => {});

    // ── Step 5: Publish final results ────────────────────────────────────────
    await _publishState(searchId, {
      status: 'complete',
      data: scrapeData
    });

  } catch (err) {
    console.error(`[${searchId}] Pipeline Error:`, err);
    const msg = err.response?.data?.detail || err.message || 'Unknown error';
    await _publishState(searchId, { status: 'error', error: msg });
  }
}

async function _publishState(searchId, state) {
  const ttl = 120; // Keep state alive for 2 minutes for SSE clients
  await redis.set(`qc:state:${searchId}`, JSON.stringify(state), 'EX', ttl).catch(() => {
    // If Redis is down, we still need the SSE to work — store in a Map
    global._fallbackStore = global._fallbackStore || new Map();
    global._fallbackStore.set(searchId, state);
  });
}

function _hashQuery(query, lat, lon) {
  // Simple cache key: query + rounded location (to ~500m grid)
  const roundedLat = lat ? Math.round(lat * 100) / 100 : 'default';
  const roundedLon = lon ? Math.round(lon * 100) / 100 : 'default';
  return `${query.toLowerCase().replace(/\s+/g, '_')}_${roundedLat}_${roundedLon}`;
}

module.exports = router;
