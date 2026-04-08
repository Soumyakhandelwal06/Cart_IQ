const mongoose = require('mongoose');

const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/cartiq';

mongoose.connect(MONGODB_URI)
  .then(() => console.log('✅ MongoDB connected successfully'))
  .catch((err) => {
    console.error('❌ MongoDB connection error:', err.message);
    process.exit(1); // Exit if DB connection fails
  });

module.exports = mongoose;
