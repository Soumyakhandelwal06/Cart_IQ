const express = require('express');
const User = require('../models/User');
const auth = require('../middleware/auth');
const axios = require('axios');

const router = express.Router();
const SCRAPER_URL = process.env.SCRAPER_URL || 'http://localhost:8001';

/**
 * 1. Trigger Platform OTP
 * Starts a Playwright session on the scraper service
 */
router.post('/trigger-otp', auth, async (req, res) => {
  try {
    const { platform, phone } = req.body;
    const targetPhone = phone || req.user.phone; // Auto-fill from CartIQ profile

    if (!['zepto', 'blinkit', 'bigbasket'].includes(platform)) {
      return res.status(400).json({ error: 'Invalid platform' });
    }

    // Proxy to Scraper Service
    const response = await axios.post(`${SCRAPER_URL}/auth/${platform}/trigger`, {
      phone: targetPhone
    });

    res.json(response.data);
  } catch (err) {
    console.error(`[Platforms] Error triggering OTP for ${req.body.platform}:`, err.message);
    res.status(500).json({ error: 'Failed to trigger platform OTP' });
  }
});

/**
 * 2. Verify Platform OTP & Save Session
 * Captures context.storage_state() from Scraper
 */
router.post('/verify-otp', auth, async (req, res) => {
  try {
    const { platform, phone, otp } = req.body;
    const targetPhone = phone || req.user.phone;

    // Proxy to Scraper Service
    const response = await axios.post(`${SCRAPER_URL}/auth/${platform}/verify`, {
      phone: targetPhone,
      otp: otp
    });

    if (response.data.success && response.data.storage_state) {
      // Save session to user record
      const update = {};
      update[`platformAccounts.${platform}`] = {
        phone: targetPhone,
        isConnected: true,
        storageState: response.data.storage_state,
        lastLogin: new Date()
      };

      await User.findByIdAndUpdate(req.user.id, { $set: update });
      return res.json({ success: true, message: `${platform} connected successfully` });
    }

    res.status(400).json({ error: 'Invalid OTP or session capture failed' });
  } catch (err) {
    console.error(`[Platforms] Error verifying OTP for ${req.body.platform}:`, err.message);
    res.status(500).json({ error: 'Platform verification failed' });
  }
});

/**
 * 3. Sync Platform Status
 */
router.get('/status', auth, async (req, res) => {
  try {
    const user = await User.findById(req.user.id);
    const status = {
      zepto: user.platformAccounts?.zepto?.isConnected || false,
      blinkit: user.platformAccounts?.blinkit?.isConnected || false,
      bigbasket: user.platformAccounts?.bigbasket?.isConnected || false,
      phone: user.phone
    };
    res.json(status);
  } catch (err) {
    res.status(500).json({ error: 'Failed to fetch status' });
  }
});

/**
 * 4. Disconnect a Platform
 */
router.post('/disconnect', auth, async (req, res) => {
  try {
    const { platform } = req.body;
    if (!['zepto', 'blinkit', 'bigbasket'].includes(platform)) {
      return res.status(400).json({ error: 'Invalid platform' });
    }

    const unset = {};
    unset[`platformAccounts.${platform}`] = 1;

    await User.findByIdAndUpdate(req.user.id, { $unset: unset });
    return res.json({ success: true, message: `${platform} disconnected successfully` });
  } catch (err) {
    console.error(`[Platforms] Error disconnecting ${req.body.platform}:`, err.message);
    res.status(500).json({ error: 'Failed to disconnect platform' });
  }
});

module.exports = router;

