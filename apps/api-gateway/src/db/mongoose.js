const mongoose = require('mongoose');

const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/cartiq';

mongoose.connect(MONGODB_URI)
  .then(() => console.log(`✅ MongoDB connected successfully to ${MONGODB_URI}`))
  .catch(async (err) => {
    console.warn('⚠️  Primary MongoDB failed, falling back to local MongoDB:', err.message);
    try {
      await mongoose.connect('mongodb://localhost:27017/cartiq');
      console.log('✅ MongoDB connected successfully to local fallback');
    } catch (localErr) {
      console.error('❌ Local MongoDB connection error:', localErr.message);
      process.exit(1);
    }
  });

module.exports = mongoose;
