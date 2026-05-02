const express = require('express');
const axios = require('axios');
const User = require('../models/User');
const redis = require('../redis');
const authMiddleware = require('../middleware/auth');

const router = express.Router();
const SCRAPER_URL = process.env.SCRAPER_URL || 'http://127.0.0.1:8001';

router.post('/', authMiddleware, async (req, res) => {
  try {
    const { platform, search_id } = req.body;

    if (!platform || !search_id) {
      return res.status(400).json({ error: 'platform and search_id are required' });
    }

    if (!['zepto', 'blinkit', 'bigbasket'].includes(platform)) {
      return res.status(400).json({ error: 'Unsupported platform' });
    }

    // 1. Get user and verify they are connected to this platform
    const user = await User.findById(req.user.id);
    if (!user || !user.platformAccounts || !user.platformAccounts[platform] || !user.platformAccounts[platform].isConnected) {
      return res.status(400).json({ error: `You are not connected to ${platform}` });
    }

    const storageState = user.platformAccounts[platform].storageState;
    if (!storageState) {
      return res.status(400).json({ error: `Authentication session missing for ${platform}` });
    }

    // 2. Get the items from the cached search results
    const cacheKey = `qc:state:${search_id}`;
    const cachedState = await redis.get(cacheKey);
    
    if (!cachedState) {
      return res.status(400).json({ error: 'Search results expired. Please search again.' });
    }

    const stateObj = JSON.parse(cachedState);
    if (stateObj.status !== 'complete' || !stateObj.data || !stateObj.data.platforms) {
      return res.status(400).json({ error: 'Search is not complete or data is missing' });
    }

    // Find the cart for the requested platform
    const platformCart = stateObj.data.platforms.find(p => p.platform === platform);
    if (!platformCart || !platformCart.items) {
      return res.status(400).json({ error: `Could not find cart data for ${platform}` });
    }

    // Filter available items and extract URLs/quantities
    const itemsToAdd = platformCart.items
      .filter(item => item.available && item.product_url)
      .map(item => ({
        product_url: item.product_url,
        quantity: item.quantity,
        name: item.matched_product_name || item.item_name
      }));

    if (itemsToAdd.length === 0) {
      return res.status(400).json({ error: 'No available items with valid URLs to add to cart' });
    }

    // 3. Send request to Scraper checkout endpoint
    console.log(`[Checkout] Forwarding ${itemsToAdd.length} items to Scraper for ${platform}...`);
    
    const scraperRes = await axios.post(`${SCRAPER_URL}/checkout/${platform}`, {
      storage_state: storageState,
      items: itemsToAdd
    }, { timeout: 300000 }); // 5 minutes timeout

    const scraperResults = scraperRes.data.results;

    // For Blinkit: cart is localStorage-only, so save the updated storageState back to MongoDB
    // so the user's session in their own browser gets the cart when they open blinkit.com
    if (platform === 'blinkit') {
      const updatedStateResult = scraperResults.find(r => r.type === 'updated_storage_state');
      if (updatedStateResult && updatedStateResult.state) {
        try {
          user.platformAccounts[platform].storageState = updatedStateResult.state;
          user.markModified('platformAccounts');
          await user.save();
          console.log(`[Checkout] Saved updated Blinkit storageState (with cart) back to MongoDB ✅`);
        } catch (saveErr) {
          console.error('[Checkout] Failed to save updated Blinkit storageState:', saveErr.message);
        }
      }
    }

    // Filter out internal result types before returning to client
    const clientResults = scraperResults.filter(r => r.type !== 'updated_storage_state');

    return res.json({
      success: true,
      message: `Successfully synced ${itemsToAdd.length} items to your ${platform} cart!`,
      details: clientResults
    });

  } catch (err) {
    console.error(`[Checkout] Error:`, err.response?.data || err.message);
    const detail = err.response?.data?.detail || err.message || 'Checkout failed';
    res.status(500).json({ error: detail });
  }
});

module.exports = router;
