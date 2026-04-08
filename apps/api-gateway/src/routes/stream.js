/**
 * GET /api/v1/stream/:search_id
 *
 * Server-Sent Events endpoint. Polls Redis for the pipeline state associated
 * with the search_id and pushes updates to the client in real-time.
 */
const express = require('express');
const redis = require('../redis');
const auth = require('../middleware/auth');

const router = express.Router();
const POLL_INTERVAL_MS = 400;
const MAX_WAIT_MS = 150000; // 2.5 min — real Playwright scraping takes 30-90s


router.get('/:searchId', auth, (req, res) => {
  const { searchId } = req.params;

  // ── SSE Headers ──────────────────────────────────────────────────────────────
  // ── Connection Hardening ───────────────────────────────────────────────────
  req.socket.setTimeout(0);
  req.socket.setKeepAlive(true, 1000);
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.setHeader('Content-Encoding', 'none');
  res.flushHeaders();

  // Send initial heartbeat
  res.write('event: heartbeat\ndata: {"ts": ' + Date.now() + '}\n\n');

  let elapsed = 0;
  let lastStatus = null;

  // ── Repeated Heartbeat ──────────────────────────────────────────────────────
  const heartbeat = setInterval(() => {
    res.write('event: heartbeat\ndata: {"ts": ' + Date.now() + '}\n\n');
  }, 5000); // Pulse every 5s for maximum stability

  const interval = setInterval(async () => {
    elapsed += POLL_INTERVAL_MS;

    try {
      // Try Redis first, then fallback in-memory store
      let raw = await redis.get(`qc:state:${searchId}`).catch(() => null);
      if (!raw && global._fallbackStore) {
        const fb = global._fallbackStore.get(searchId);
        if (fb) raw = JSON.stringify(fb);
      }

      if (!raw) {
        if (elapsed >= MAX_WAIT_MS) {
          _send(res, 'error', { error: 'Request timed out. Please try again.' });
          return cleanup();
        }
        return; // Still processing, keep polling
      }

      const state = JSON.parse(raw);

      // Only send if state has changed (avoid duplicate events)
      if (JSON.stringify(state) === lastStatus) return;
      lastStatus = JSON.stringify(state);

      if (state.status === 'complete') {
        _send(res, 'result', state);
        return cleanup();
      } else if (state.status === 'error') {
        _send(res, 'error', state);
        return cleanup();
      } else {
        // Intermediate progress update (parsing / scraping)
        _send(res, 'progress', state);
      }

    } catch (err) {
      console.error(`[SSE] Error for ${searchId}:`, err.message);
    }
  }, POLL_INTERVAL_MS);

  // Clean up when client disconnects
  req.on('close', () => {
    clearInterval(interval);
    clearInterval(heartbeat);
  });

  function cleanup() {
    clearInterval(interval);
    clearInterval(heartbeat);
    res.end();
  }
});

function _send(res, event, data) {
  try {
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  } catch (_) {}
}

module.exports = router;
