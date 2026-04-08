const express = require('express');
const User = require('../models/User');
const redis = require('../redis');
const authMiddleware = require('../middleware/auth');
const smsService = require('../services/smsService');

const router = express.Router();

// 1. Send OTP
router.post('/send-otp', async (req, res) => {
  try {
    const { phone } = req.body;
    if (!phone) {
      return res.status(400).json({ error: 'Phone number is required' });
    }

    // Generate 6-digit random OTP
    const otp = Math.floor(100000 + Math.random() * 900000).toString();

    // Store in Redis (Expiries in 2 min)
    await redis.set(`otp:${phone}`, otp, 'EX', 120);

    // Send Real SMS via Twilio
    const sent = await smsService.sendOTP(phone, otp);

    // MOCK SMS: Log to console (Always keep for fallback debugging)
    console.log(`\n--------------------------------------`);
    console.log(`🔐 OTP for ${phone}: ${otp} (SMS Sent: ${sent})`);
    console.log(`--------------------------------------\n`);

    if (!sent) {
      return res.status(500).json({ error: 'Failed to send SMS OTP. Check server logs.' });
    }

    const user = await User.findOne({ phone });
    res.json({ message: 'OTP sent successfully', isNew: !user });
  } catch (err) {
    console.error('OTP Send Error:', err.message);
    res.status(500).json({ error: 'Failed to send OTP' });
  }
});

// 2. Verify OTP
router.post('/verify-otp', async (req, res) => {
  try {
    const { phone, otp, name } = req.body;
    if (!phone || !otp) {
      return res.status(400).json({ error: 'Phone and OTP are required' });
    }

    // Check Redis
    const storedOtp = await redis.get(`otp:${phone}`);
    if (!storedOtp || storedOtp !== otp) {
      return res.status(400).json({ error: 'Invalid or expired OTP' });
    }

    // OTP is valid - delete from Redis
    await redis.del(`otp:${phone}`);

    // Find or Create User
    let user = await User.findOne({ phone });
    if (!user) {
      user = new User({ phone, name, isVerified: true });
      await user.save();
    } else {
      user.isVerified = true;
      if (name) user.name = name; // Update name if provided later
      await user.save();
    }

    // Generate JWT
    const token = await user.generateAuthToken();

    res.json({ user, token });
  } catch (err) {
    console.error('Verify OTP Error:', err.message);
    res.status(500).json({ error: 'Authentication failed' });
  }
});

// 3. Get Auth Context (Me)
router.get('/me', authMiddleware, async (req, res) => {
  try {
    const user = await User.findById(req.user.id);
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }
    res.json({ user });
  } catch (err) {
    res.status(500).send();
  }
});

module.exports = router;
