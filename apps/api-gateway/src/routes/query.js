/**
 * POST /api/v1/query
 *
 * Main entry point. Receives a natural language grocery query + location,
 * calls the Python parser, dispatches scraping (with user's stored platform sessions),
 * auto-adds items to all connected carts, and returns results via SSE.
 */
const express = require('express');
const axios = require('axios');
const { v4: uuidv4 } = require('uuid');
const redis = require('../redis');
const auth = require('../middleware/auth');
const User = require('../models/User');

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
  _runPipeline(searchId, query.trim(), lat, lon, req.user.id).catch((err) => {
    console.error(`[${searchId}] Pipeline failed:`, err.message);
    _publishState(searchId, { status: 'error', error: err.message });
  });
});

async function _runPipeline(searchId, query, lat, lon, userId) {
  try {
    // ── Step 1: Fetch user's linked platform sessions ─────────────────────────
    let storage_states = {};
    if (userId) {
      try {
        const user = await User.findById(userId).select('platformAccounts');
        if (user && user.platformAccounts) {
          for (const platform of ['zepto', 'blinkit', 'bigbasket']) {
            const acc = user.platformAccounts[platform];
            if (acc && acc.isConnected && acc.storageState) {
              storage_states[platform] = acc.storageState;
            }
          }
        }
        const connectedCount = Object.keys(storage_states).length;
        console.log(`[${searchId}] Found ${connectedCount} connected platform(s): ${Object.keys(storage_states).join(', ') || 'none'}`);
      } catch (e) {
        console.warn(`[${searchId}] Could not load user sessions (continuing anonymously):`, e.message);
      }
    }

    // ── Step 2: Parse the NL query ───────────────────────────────────────────
    await _publishState(searchId, { status: 'parsing', message: '🧠 Understanding your grocery list...' });

    const parseRes = await axios.post(`${SCRAPER_URL}/parse/`, { query }, { timeout: 12000 });
    const parsedQuery = parseRes.data;

    const connectedPlatforms = Object.keys(storage_states);
    const cartMsg = connectedPlatforms.length > 0
      ? `Found ${parsedQuery.items.length} item(s). Fetching prices & adding to your carts on ${connectedPlatforms.join(', ')}...`
      : `Found ${parsedQuery.items.length} item(s). Checking prices on all platforms...`;

    await _publishState(searchId, {
      status: 'scraping',
      message: cartMsg,
      items: parsedQuery.items
    });

    // ── Step 3: Scrape + auto-add to cart ────────────────────────────────────
    const scrapeRes = await axios.post(
      `${SCRAPER_URL}/scrape/`,
      {
        items: parsedQuery.items,
        lat: lat || 28.6139,
        lon: lon || 77.2090,
        storage_states: Object.keys(storage_states).length > 0 ? storage_states : undefined
      },
      { timeout: 330000 }   // 5.5 min — real Playwright scraping + checkout can take ~4-5 mins
    );

    const scrapeData = scrapeRes.data;

    // ── Step 4: Cache and publish results ─────────────────────────────────────
    const cacheKey = `qc:state:${searchId}`;
    const finalLat = lat || 28.6139;
    const finalLon = lon || 77.2090;
    await redis.set(cacheKey, JSON.stringify({ status: 'complete', data: scrapeData, lat: finalLat, lon: finalLon }), 'EX', CACHE_TTL_SECONDS).catch(() => {});

    await _publishState(searchId, {
      status: 'complete',
      data: scrapeData,
      lat: finalLat,
      lon: finalLon
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
    global._fallbackStore = global._fallbackStore || new Map();
    global._fallbackStore.set(searchId, state);
  });
}

module.exports = router;
